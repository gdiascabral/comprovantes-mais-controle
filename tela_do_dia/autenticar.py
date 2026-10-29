# -*- coding: utf-8 -*-
""""Autenticar no banco": o que o banco prova de cada agendado pendente. Sem
tela e sem rede.

Pedido do dono (29/10/2026): o dia começa conferindo no banco o que foi pago
antes. A prova do banco só PRÉ-MARCA (vira `prova_extra` de
`agendados.situacao`, que nunca deixa ela vencer "sumiu" nem "mudou"); quem
responde "Pago" continua sendo o dono.

Como se casa, sempre NA MESMA CONTA e com data entre o dia anterior ao
agendado e hoje:

1. código de barras (a linha digitável da foto, em 44 dígitos) igual ao do
   comprovante; código dos dois lados e DIFERENTE tira o par de tudo;
2. senão, valor ao centavo + a descrição colada, pela régua de prefixo de
   `agendamentos_sicoob.mesma_descricao` (o banco corta a observação; "LT 10"
   não casa com "LT 10 E 11");
3. o favorecido só desempata candidatos do passo 2, nunca prova sozinho.

Um comprovante prova um agendado só. Os candidatos formam grupos (quem
disputa quem); um grupo só prova quando TODOS os agendados dele casam com
TODOS os movimentos dele e são em mesmo número — dois agendados iguais e dois
pagamentos iguais pré-marcam os dois; dois e um, nenhum ("responda").

Só entra movimento EFETIVADO: quem monta a lista (`do_comprovante_sicoob`)
deixa o comprovante de agendamento de fora; o Pix vem só da lista de Pix
(o espelho TRANSF.PIX da lista comum sai por `sicoob_baixar.sem_pix`).
A pendência de assinatura do Sicoob que casa com o agendado DERRUBA a prova.
Lançamento dividido em N boletos só se prova com as N partes achadas, cada
uma pelo seu código.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import util
from pagamentos_dia import ocr_boleto
from pagamentos_dia.agendamentos_sicoob import mesma_descricao

ZERO = Decimal("0.00")
CENTAVO = Decimal("0.01")
#: Até quantos dias depois do dia do agendado (ou do vencimento da foto, o
#: que vier depois) um pagamento do banco ainda pode ser ELE. Sem teto, um
#: pendente velho olharia semanas de extrato e um pagamento recorrente de
#: mesmo valor e descrição (ou o de um remarcado já respondido) o provaria
#: (revisão de dinheiro, 29/10/2026).
FOLGA_DEPOIS = 3
#: A descrição do banco que é só o COMEÇO da colada só vale quando é longa o
#: bastante para ser o corte do banco, e não outro pagamento mais curto
#: ("... LT 10" provando "... LT 10 E 11"). A MEDIR: o limite real da
#: observação do Sicoob; até lá, só texto deste tamanho para cima.
CORTE_DO_BANCO = 40
#: A situação de Pix que é dinheiro que SAIU. Medido em 29/10/2026 na lista
#: `/api/pix/lancamentos` de 3 contas (97 Pix): `estado` = FINALIZADO_SUCESSO
#: e `tipo` = DEBITO em todos. Outro estado (ou sem estado), ou outro tipo,
#: NÃO prova — falha fechada, como o comprovante só EFETIVADO.
PIX_EFETIVADO = {"FINALIZADO_SUCESSO"}
CAMPOS_SITUACAO_PIX = ("estado",)
PIX_SAIU = "DEBITO"

#: Os nomes de campo do código de barras / linha digitável que a lista do
#: banco pode trazer. A MEDIR com a conta do dono (tarefa 0 da spec): até lá
#: são hipótese, e campo que não vem só deixa o casamento no passo 2.
CAMPOS_BARRAS = ("codigoBarras", "codigoBarra", "codigoDeBarras", "linhaDigitavel",
                 "codBarras", "linhaDigitavelCodigoBarras")
#: Idem para a descrição (observação) que o dono colou.
CAMPOS_DESCRICAO = ("descricao", "observacao", "descricaoPagamento", "complementoHistorico",
                    "campoLivre", "historico")
#: Idem para quem recebe.
CAMPOS_FAVORECIDO = ("nomeFavorecido", "favorecido", "nomeBeneficiario", "beneficiario",
                     "nomeRecebedor")


@dataclass(frozen=True)
class Movimento:
    """Um pagamento que SAIU da conta, como o banco o lista."""
    conta: str            # a conta do ERP (a mesma do `Agendado.conta`)
    data: date
    valor: Decimal
    barras: str = ""      # 44 dígitos, ou ""
    descricao: str = ""
    favorecido: str = ""
    origem: str = ""      # "Sicoob comprovante", "Sicoob Pix", "Inter 2ª via", "Inter Pix"
    ident: str = ""       # o número do banco (agendamento, endToEnd), para o Registro


@dataclass(frozen=True)
class Autenticacao:
    """`prova`: texto curto que vira `prova_extra` (vazio = não provou).
    `nota`: o que o banco disse quando não provou (ou ""), para a tela."""
    prova: str = ""
    nota: str = ""


# ------------------------------------------------------------ conversões
def dinheiro(valor) -> Decimal | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, str):
        t = valor.replace("\xa0", " ").replace("\u2212", "-").strip()
        negativo = t.startswith("-")
        t = t.lstrip("-").strip().replace("R$", "").strip()
        if t.startswith("-"):
            negativo, t = True, t[1:].strip()
        if negativo:
            t = "-" + t
        if "," in t:
            t = t.replace(".", "").replace(",", ".")
        valor = t
    try:
        return Decimal(str(valor)).quantize(CENTAVO)
    except (InvalidOperation, ValueError):
        return None


def data_do_banco(texto) -> date | None:
    """"2026-10-28", "2026-10-28T10:00:00", "28/10/2026", milissegundos."""
    if texto is None or texto == "":
        return None
    if isinstance(texto, (int, float)):
        return datetime.fromtimestamp(texto / 1000).date()
    t = str(texto).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", t)
    if m:
        return date(int(m[3]), int(m[2]), int(m[1]))
    return None


def barras(texto) -> str:
    """Os 44 dígitos do código de barras, a partir do código (44) ou da
    linha digitável (47/48, que precisa fechar nos DVs); senão ""."""
    d = re.sub(r"\D", "", str(texto or ""))
    if len(d) == 44:
        return d
    if len(d) in (47, 48):
        return ocr_boleto.codigo_de_barras(d)
    return ""


def _primeiro(item: dict, campos) -> str:
    for c in campos:
        v = item.get(c)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def do_comprovante_sicoob(item: dict, conta: str) -> Movimento | None:
    """Um item da lista de comprovantes do Sicoob. Só EFETIVADO e sem Pix
    (o Pix vem da lista de Pix); o resto é None."""
    if (item.get("situacao") or "").strip().upper() != "EFETIVADO":
        return None
    if item.get("tipoOperacaoPix") or (item.get("tipoAgendamento") or "").strip().lower(
            ).startswith("pix"):
        return None
    valor, dia = dinheiro(item.get("valorLancamento")), data_do_banco(item.get("dataLancamento"))
    if valor is None or dia is None:
        return None
    return Movimento(conta, dia, valor, barras(_primeiro(item, CAMPOS_BARRAS)),
                     _primeiro(item, CAMPOS_DESCRICAO), _primeiro(item, CAMPOS_FAVORECIDO),
                     "Sicoob comprovante", str(item.get("idAgendamento") or ""))


def do_pix_sicoob(item: dict, conta: str) -> Movimento | None:
    """Um Pix ENVIADO da lista de Pix do Sicoob (`/api/pix/lancamentos`)."""
    from baixar_comprovantes.nome_final import momento_do_pix_sicoob
    situacao = util.sem_acento(_primeiro(item, CAMPOS_SITUACAO_PIX)).upper()
    if situacao not in PIX_EFETIVADO or str(item.get("tipo") or "").upper() != PIX_SAIU:
        return None
    valor = dinheiro(item.get("valor"))
    dia = data_do_banco(momento_do_pix_sicoob(item))
    if valor is None or dia is None or valor <= ZERO:
        return None
    destino = item.get("destino") or {}
    return Movimento(conta, dia, valor, "", str(item.get("descricao") or "").strip(),
                     str(destino.get("nome") or "").strip(), "Sicoob Pix",
                     str(item.get("endToEndId") or item.get("id") or ""))


def do_pix_inter(mov: dict, conta: str) -> Movimento | None:
    """Um Pix ENVIADO do extrato Pix do Inter (os campos de `nome_final.do_pix`).
    O extrato traz os enviados (`tipo` "D") e os RECEBIDOS ("C") juntos
    (medido em 29/10/2026): Pix que entrou nunca prova pagamento."""
    detalhe = mov.get("detalhePix") or {}
    if str(mov.get("tipo") or "").upper() != "D" or detalhe.get("isDevolucao"):
        return None
    valor = dinheiro(mov.get("valor"))
    dia = data_do_banco(mov.get("data"))
    if valor is None or dia is None or valor <= ZERO:
        return None
    desc = next((str(o).strip() for o in (mov.get("descricao"), detalhe.get("descricaoPagamento"),
                                          detalhe.get("campoLivre")) if str(o or "").strip()), "")
    return Movimento(conta, dia, valor, "", desc, str(mov.get("nome") or "").strip(),
                     "Inter Pix", str(mov.get("endToEndId") or mov.get("id") or ""))


def do_2via_inter(item: dict, conta: str) -> Movimento | None:
    """Um PAGAMENTO/DARF da 2ª via do Inter (os campos de `nome_final.do_2via`).
    Medido em 29/10/2026: `pagamento.codigoBarra`/`linhaDigitavel`, a
    descrição em `descricao`, e `pagamento.status` EFETIVADO (em 24 de 26; a
    2ª via só lista o que tem `dataEfetivacao`). Outro status não prova."""
    pagamento = item.get("pagamento") or {}
    if str(pagamento.get("status") or "").upper() != "EFETIVADO":
        return None
    valor = dinheiro(item.get("valor"))
    dia = data_do_banco(item.get("dataEfetivacao"))
    if valor is None or dia is None or valor <= ZERO:
        return None
    desc = str(item.get("descricao") or pagamento.get("complementoHistorico") or "").strip()
    cod = _primeiro(pagamento, CAMPOS_BARRAS) or _primeiro(item, CAMPOS_BARRAS)
    return Movimento(conta, dia, valor, barras(cod), desc,
                     _primeiro(pagamento, CAMPOS_FAVORECIDO), "Inter 2ª via",
                     str(item.get("id") or ""))


def da_pendencia(item: dict, conta: str) -> Movimento | None:
    """Uma transação PENDENTE DE ASSINATURA do Sicoob, como movimento (a
    contraprova). A data é ignorada na comparação: pendente é pendente."""
    from pagamentos_dia.agendamentos_sicoob import pendente_de_verdade
    if not pendente_de_verdade(item):
        return None
    valor = dinheiro(item.get("valor"))
    if valor is None:
        return None
    desc = str(item.get("observacao") or item.get("detalhe") or "")
    return Movimento(conta, data_do_banco(item.get("lancamentoEm")) or date.min, valor, "",
                     desc, str(item.get("detalhe") or ""), "Sicoob pendente de assinatura")


# ------------------------------------------------------------- casamento
@dataclass(frozen=True)
class _Alvo:
    """Um agendado inteiro, ou UMA parte de um lançamento dividido."""
    ag_id: int
    parte: int            # -1 = o agendado inteiro
    conta: str
    dia: date
    valor: Decimal
    barras: str
    descricao: str
    favorecido: str
    ate: date = date.max  # o último dia em que o pagamento ainda pode ser ele
    dividido: bool = False


def _alvos(ag) -> list[_Alvo]:
    foto = ag.foto or {}
    desc = str(foto.get("descricao_colada") or ag.descricao or "")
    fav = str(foto.get("favorecido") or ag.favorecido or "")
    venc = data_do_banco(foto.get("vencimento")) or ag.dia
    ate = max(ag.dia, venc) + timedelta(days=FOLGA_DEPOIS)
    partes = foto.get("partes") or ()
    if partes:
        # Lançamento dividido (mesmo com UMA parte saindo): cada parte só pela
        # SUA linha, nunca a `foto["linha"]`, que é a da 1ª parte do HTML.
        saida = []
        for k, p in enumerate(partes):
            valor = dinheiro(p.get("valor"))
            saida.append(_Alvo(ag.id, k, ag.conta, ag.dia, valor if valor is not None else ZERO,
                                barras(p.get("parte_linha")), desc, fav, ate, True))
        return saida
    return [_Alvo(ag.id, -1, ag.conta, ag.dia, ag.valor, barras(foto.get("linha")), desc, fav,
                  ate)]


def _nome(texto) -> str:
    return util.norm_espaco(util.sem_acento(str(texto or ""))).casefold()


def _mesma_descricao(colada: str, do_banco: str) -> bool:
    """Igual (normalizada), ou o banco cortou um texto LONGO (`CORTE_DO_BANCO`)
    pela régua de prefixo de `agendamentos_sicoob.mesma_descricao`."""
    a, b = _nome(colada), _nome(do_banco)
    if not a or not b:
        return False
    if a == b:
        return True
    return len(b) >= CORTE_DO_BANCO and mesma_descricao({"descricao": colada},
                                                        {"observacao": do_banco})


def _casa(alvo: _Alvo, m: Movimento) -> int:
    """2 = pelo código de barras; 1 = valor + descrição; 0 = não casa. O
    valor tem de bater ao centavo nos dois níveis; parte de lançamento
    dividido só casa pelo código."""
    if m.valor != alvo.valor:
        return 0
    if alvo.barras and m.barras:
        return 2 if alvo.barras == m.barras else 0
    if alvo.dividido:
        return 0
    return 1 if _mesma_descricao(alvo.descricao, m.descricao) else 0


def _candidatos(alvo: _Alvo, movimentos, hoje: date) -> list[int]:
    """Os índices dos movimentos que podem ser este alvo, no melhor nível."""
    inicio = alvo.dia - timedelta(days=1)
    niveis: dict[int, list[int]] = {}
    for i, m in enumerate(movimentos):
        if m.conta != alvo.conta or not (inicio <= m.data <= min(hoje, alvo.ate)):
            continue
        n = _casa(alvo, m)
        if n:
            niveis.setdefault(n, []).append(i)
    if not niveis:
        return []
    melhor = niveis[max(niveis)]
    if max(niveis) == 1 and len(melhor) > 1 and alvo.favorecido:
        # O favorecido só DESEMPATA: tira quem diz outro nome; quem não diz
        # nome nenhum fica (o boleto do Sicoob não diz quem recebe).
        alvo_nome = _nome(alvo.favorecido)
        mesmos = [i for i in melhor if not movimentos[i].favorecido
                  or _nome(movimentos[i].favorecido) == alvo_nome]
        if mesmos:
            melhor = mesmos
    return melhor


def _grupos(arestas: dict) -> list[tuple[set, set]]:
    """Componentes do grafo alvo↔movimento: [(alvos, movimentos)]."""
    por_mov: dict[int, set] = {}
    for a, ms in arestas.items():
        for m in ms:
            por_mov.setdefault(m, set()).add(a)
    vistos, saida = set(), []
    for inicio in arestas:
        if inicio in vistos or not arestas[inicio]:
            continue
        alvos, movs, fila = set(), set(), [inicio]
        while fila:
            a = fila.pop()
            if a in alvos:
                continue
            alvos.add(a)
            for m in arestas[a]:
                if m not in movs:
                    movs.add(m)
                    fila.extend(por_mov[m] - alvos)
        vistos |= alvos
        saida.append((alvos, movs))
    return saida


def _descreve(m: Movimento, nivel: int) -> str:
    como = "mesmo código de barras" if nivel == 2 else "mesmo valor e descrição"
    return f"{m.origem} {m.data:%d/%m}: {como}"


def autenticar(pendentes, movimentos, pendencias=(), lidas=(), falhas=None,
               hoje: date | None = None) -> dict[int, Autenticacao]:
    """{id do agendado: Autenticacao} para os pendentes de conta LIDA no
    banco (`lidas`: as contas do ERP); `falhas`: {conta: motivo} das que
    não deu para ler. Agendado de conta que não é de banco lido fica de fora."""
    hoje = hoje or date.today()
    movimentos = list(movimentos or ())
    pendencias = list(pendencias or ())
    lidas, falhas = set(lidas or ()), dict(falhas or {})
    saida: dict[int, Autenticacao] = {}
    alvos_por_ag: dict[int, list[_Alvo]] = {}
    for ag in pendentes:
        if ag.conta in falhas:
            saida[ag.id] = Autenticacao("", f"banco não lido: {falhas[ag.conta]}")
        elif ag.conta in lidas:
            alvos_por_ag[ag.id] = _alvos(ag)
    arestas: dict[_Alvo, set] = {}
    for alvos in alvos_por_ag.values():
        for a in alvos:
            arestas[a] = set(_candidatos(a, movimentos, hoje))
    provado: dict[_Alvo, int] = {}            # alvo -> índice do movimento
    ambiguo: set = set()
    for alvos, movs in _grupos(arestas):
        completo = all(arestas[a] == movs for a in alvos)
        if completo and len(alvos) == len(movs):
            for a, m in zip(sorted(alvos, key=lambda a: (a.ag_id, a.parte)), sorted(movs)):
                provado[a] = m
        else:
            ambiguo |= alvos
    for ag_id, alvos in alvos_por_ag.items():
        contra = next((p for p in pendencias for a in alvos
                       if p.conta == a.conta and _casa(a, p)), None)
        if contra is not None:
            saida[ag_id] = Autenticacao("", "ainda pendente de assinatura no Sicoob")
            continue
        if all(a in provado for a in alvos):
            m = movimentos[provado[alvos[0]]]
            nivel = 2 if all(a.barras for a in alvos) else 1
            texto = _descreve(m, nivel)
            if alvos[0].dividido:
                texto = (f"{m.origem}: as {len(alvos)} parte(s), cada uma pelo seu "
                         "código de barras")
            saida[ag_id] = Autenticacao(f"banco — {texto}", "")
        elif any(a in ambiguo for a in alvos):
            saida[ag_id] = Autenticacao("", "pagamentos parecidos no banco, sem como "
                                            "separar — responda")
        elif alvos[0].dividido and any(a in provado for a in alvos):
            achadas = sum(a in provado for a in alvos)
            saida[ag_id] = Autenticacao("", f"banco: {achadas} de {len(alvos)} partes "
                                            "achadas — responda")
        else:
            saida[ag_id] = Autenticacao("", "nada no banco ainda")
    return saida


def marcas_com_provas(marcas: dict, antes, depois) -> dict:
    """As marcas ☑ depois do "Autenticar no banco" (`antes`/`depois`: os
    pendentes antes e depois da prova). Só muda a marca de quem MUDOU de
    pré-marca: passou a ser provado nasce ☑, perdeu a prova perde o ☑; quem
    não mudou fica como o dono deixou (ele pode ter desmarcado de propósito)."""
    novas = dict(marcas or {})
    ja = {a.id: bool(s.pre_marca) for a, s, _r in antes or ()}
    for a, sit, _r in depois:
        if ja.get(a.id) != bool(sit.pre_marca):
            novas[a.id] = bool(sit.pre_marca)
    return novas


# --------------------------------------- Inter: o extrato completo (BFF)
# Medido em 29/10/2026 numa conta PJ (3 sondas, só nomes de campo): a tela
# `contadigital.inter.co/extrato` pede `GET cd.web.bancointer.com.br/ib-pfj/
# cc/extrato/bff/v2/home`, e naquela conta o saldo só aparece ali (a tela
# inicial não pede o `/cc/saldo/v3/` da Prova de saldos). A resposta traz:
#   balance.data.balances[] — {id: "DIGITAL_ACCOUNT", available: "R$ …"}
#   transactions.data[].bankStatements[].transactions[].detail — {rawValue,
#     value, description, metadata: {transactionType, operationType D/C, id},
#     data: {transactionDate, aboutTransaction: {description, transactionId},
#     whoReceived: {name}}}
#   schedules — os agendamentos do Inter (vazio na medição).
# É o extrato que traz o pagamento de convênio (a 2ª via e o extrato Pix
# não trazem — cofre, 20/10/2026). A forma do convênio aqui ainda não foi
# vista: só Pix nas amostras.
SALDO_DA_CONTA = "DIGITAL_ACCOUNT"


def saldo_do_extrato_inter(corpo: dict) -> Decimal | None:
    """O saldo da conta digital no extrato completo, ou None — a régua é a
    do leitor de saldo (`inter_saldo.saldo_do_extrato`), uma só."""
    from baixar_comprovantes.inter_saldo import saldo_do_extrato
    return saldo_do_extrato(corpo)


def transacoes_do_extrato_inter(corpo: dict) -> list:
    """As transações do extrato completo, achatadas (cada `detail`)."""
    saida = []
    for mes in ((corpo or {}).get("transactions") or {}).get("data") or ():
        for dia in mes.get("bankStatements") or ():
            for t in dia.get("transactions") or ():
                if isinstance(t.get("detail"), dict):
                    saida.append(t["detail"])
    return saida


def do_extrato_inter(detalhe: dict, conta: str) -> Movimento | None:
    """Uma SAÍDA do extrato completo do Inter. Entrada (C) nunca prova."""
    meta = detalhe.get("metadata") or {}
    if str(meta.get("operationType") or "").upper() != "D":
        return None
    dados = detalhe.get("data") or {}
    sobre = dados.get("aboutTransaction") or {}
    valor = dinheiro(detalhe.get("rawValue")) or dinheiro(dados.get("value")) \
        or dinheiro(detalhe.get("value"))
    if valor is not None:
        valor = abs(valor)
    dia = data_do_banco(dados.get("transactionDate") or sobre.get("transactionDate"))
    if valor is None or dia is None or valor <= ZERO:
        return None
    desc = str(sobre.get("description") or detalhe.get("description") or "").strip()
    quem = str((dados.get("whoReceived") or {}).get("name") or "").strip()
    return Movimento(conta, dia, valor, barras(_primeiro(dados, CAMPOS_BARRAS)), desc, quem,
                     f"Inter extrato ({str(meta.get('transactionType') or '').lower() or '?'})",
                     str(sobre.get("transactionId") or meta.get("id") or ""))
