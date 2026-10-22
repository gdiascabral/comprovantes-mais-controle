# -*- coding: utf-8 -*-
"""Um lançamento pago com N boletos (entrega 5, dono 21/10/2026).

O caso real: dois boletos do mesmo fornecedor anexados a UM lançamento, cuja
soma dava exatamente o valor dele; o dono agendou os dois. O
`relatorio.montar_registros` não acha linha com o valor do lançamento e
devolve UMA linha "ATENÇÃO — vários boletos no título", sem dado de
pagamento. Aqui essa linha vira N — uma por boleto, com a linha digitável e o
valor DELE — quando, e só quando, as linhas válidas do título somam o
lançamento AO CENTAVO. Não bateu: não divide, só avisa.

Só a aba "Pagamentos do dia" liga isto (`confirmacao.Entradas.dividir_boletos`,
posto pela `leitura_do_dia`). A Remessa/Retorno monta as Entradas dela sem a
chave e continua vendo uma linha só.

As N linhas guardam o MESMO `id` (o retorno do banco e a baixa voltam ao
lançamento por ele) e a MESMA descrição (é por ela que o Anexar casa os N
comprovantes). Nascem em ATENÇÃO: desmarcadas na remessa, Copiar bloqueado no
HTML — o dono pediu "sempre com alerta para você olhar".
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from . import ocr_boleto, relatorio

CENTAVO = Decimal("0.01")
ZERO = Decimal("0.00")
#: O status que o `montar_registros` dá ao título com várias linhas válidas e
#: nenhuma do valor do lançamento. Cópia do texto, guardada por teste.
STATUS_VARIOS = "ATENÇÃO — vários boletos no título"
#: A frase da Obs que deixa de ser verdade depois de dividir.
_OBS_VARIOS = re.compile(r"Há \d+ boletos no título, não dá para saber qual é desta "
                         r"parcela — conferir antes de pagar")


def status_dividido(n: int) -> str:
    return f"ATENÇÃO — 1 lançamento virou {n} boletos (somam exato) — conferir"


def _em_centavos(valor) -> Decimal:
    return Decimal(str(valor or 0)).quantize(CENTAVO, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Decisao:
    #: ((linha digitável, valor Decimal, anexo), ...) — vazio: não divide.
    partes: tuple = ()
    #: Por que não dividiu, quando há o que dizer.
    aviso: str = ""


def decidir(registro: dict, item: dict, files, textos: dict, urls_ocr=(),
            parcelas_abertas: int = 1) -> Decisao:
    """Divide? Só a linha de "vários boletos", sem dado de pagamento, de título
    com UMA parcela em aberto e sem pagamento anterior, e só com o CONJUNTO
    INTEIRO das linhas válidas — nunca um subconjunto escolhido aqui."""
    if (registro.get("tipo") != "Boleto" or registro.get("status") != STATUS_VARIOS
            or (registro.get("dados") or "").strip() or item.get("paid")
            or registro.get("parcial") or registro.get("valor_diverge")
            or registro.get("reembolso")):
        return Decisao()
    if parcelas_abertas != 1:
        return Decisao(aviso=f"o título tem {parcelas_abertas} parcelas em aberto — não "
                             "dá para saber quais boletos são desta; não dividi")
    if relatorio.ja_pago_do_item(item) > 0:
        return Decisao(aviso="o título já tem pagamento — não dividi os boletos")
    valor = float(registro.get("valor") or 0)
    linhas = relatorio._linhas_dos_anexos(files, textos, valor, urls_ocr)
    if len(linhas) < 2:
        return Decisao()
    partes = []
    for linha, anexo in linhas:
        v = ocr_boleto.valor_da_linha(linha)
        if not v or v <= 0:
            return Decisao(aviso="um dos boletos do título não diz o valor — não dividi")
        partes.append((linha, _em_centavos(v), anexo))
    total, alvo = sum((p[1] for p in partes), ZERO), _em_centavos(valor)
    if total != alvo:
        return Decisao(aviso=f"os {len(partes)} boletos do título somam "
                             f"{relatorio.brl(total)} e o lançamento é "
                             f"{relatorio.brl(alvo)} — não dividi; conferir")
    return Decisao(partes=tuple(partes))


def _obs_sem_a_frase(obs: str) -> list[str]:
    return [p for p in (obs or "").split(" · ") if p and not _OBS_VARIOS.fullmatch(p)]


def _partes_do_registro(registro: dict, decisao: Decisao) -> list[dict]:
    n = len(decisao.partes)
    total = sum((p[1] for p in decisao.partes), ZERO)
    resto = _obs_sem_a_frase(registro.get("obs"))
    saida = []
    for k, (linha, valor, anexo) in enumerate(decisao.partes, 1):
        nome = (anexo.get("filename") or "?").strip()
        obs = (f"boleto {k} de {n} (anexo '{nome}') · os {n} boletos somam "
               f"{relatorio.brl(total)}, o valor do lançamento")
        saida.append({**registro, "dados": linha, "valor": float(valor),
                      "status": status_dividido(n), "obs": " · ".join([obs, *resto]),
                      "parte": f"{k}/{n}", "valor_do_lancamento": float(total)})
    return saida


def dividir(resultado: relatorio.Resultado, entradas) -> relatorio.Resultado:
    """O `Resultado` com cada lançamento de boletos que somam exato em N
    linhas, no lugar da original. Não muda o `resultado` recebido."""
    selecionados = list(entradas.selecionados or ())
    por_id = {str(i.get("id")): i for i in selecionados if i.get("id")}
    abertas = Counter(str(i.get("tradePayableId")) for i in selecionados
                      if not i.get("paid"))
    contas = {}
    for conta, registros in (resultado.contas or {}).items():
        novos = []
        for reg in registros:
            item = por_id.get(str(reg.get("id") or ""))
            if item is None:
                novos.append(reg)
                continue
            titulo = str(item.get("tradePayableId"))
            d = decidir(reg, item, (entradas.anexos or {}).get(titulo) or [],
                        entradas.textos, entradas.urls_ocr, abertas[titulo])
            if d.partes:
                novos.extend(_partes_do_registro(reg, d))
            elif d.aviso:
                novos.append({**reg, "aviso_soma": d.aviso,
                              "obs": " · ".join(filter(None, [d.aviso, reg.get("obs")]))})
            else:
                novos.append(reg)
        contas[conta] = novos
    return relatorio.Resultado(contas, resultado.omitidos)


def avisos(resultado: relatorio.Resultado) -> list[str]:
    """As frases do topo da tela (uma por lançamento dividido ou recusado)."""
    saida = []
    for conta, registros in (resultado.contas or {}).items():
        for reg in registros:
            parte = str(reg.get("parte") or "")
            if parte.startswith("1/"):
                saida.append(f"1 lançamento virou {parte.split('/')[1]} boletos (somam "
                             f"exato) — conferir: {reg.get('favorecido') or '?'}, "
                             f"{relatorio.brl(reg.get('valor_do_lancamento'))} ({conta})")
            elif reg.get("aviso_soma"):
                saida.append(f"{reg.get('favorecido') or '?'} ({conta}): {reg['aviso_soma']}")
    return saida
