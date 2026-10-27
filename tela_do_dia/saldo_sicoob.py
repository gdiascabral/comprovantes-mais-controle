# -*- coding: utf-8 -*-
"""Passo 1 da tela do dia, entrega 4: o saldo do BANCO das contas do Sicoob
lido sozinho. Sem tela, sem navegador (quem fala com o banco é
`extratos_sicoob.saldo`; quem roda a thread é `sicoob_na_tela`).

Qual conta do Sicoob é cada linha do painel sai do MESMO caminho da Remessa e
da conferência de agendamentos (`agendamentos_sicoob.conta_sicoob`): duas
regras para a mesma pergunta acabariam escolhendo contas diferentes. Conta de
outro banco fica digitada (spec: "só Sicoob"). Conta que diz SICOOB e o
cadastro não resolve, ou duas linhas na MESMA conta, não são preenchidas e
dizem por quê — nunca um saldo na linha errada, nunca R$ 0,00 no lugar de
"não lido".

O lido entra em `LinhaSaldo.banco`; o digitado (ajuste) continua valendo por
cima dele (`saldos.banco_usado`).

A leitura do dia fica num arquivo PRÓPRIO ao lado do dia de trabalho
(`DD MM - saldos do sicoob.json`), para reabrir o app sem trocar de conta 20
vezes de novo. Arquivo de outro dia é ignorado; estragado vira aviso.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pagamentos_dia import agendamentos_sicoob as ag

from . import dia_de_trabalho as ddt

VERSAO = 1
PREFIXO = "Sicoob não lido: "
MOTIVO_REPETIDA = ("duas linhas do painel apontam para a mesma conta do Sicoob "
                   "({numero}) — confira o cadastro de contas")
MOTIVO_FORA_DA_LEITURA = "esta conta não estava na leitura — clique em Reler Sicoob"
_PERFIL_EM_USO = ("already in use", "processsingleton", "existing browser session")


def _digitos(texto) -> str:
    return re.sub(r"\D", "", str(texto or ""))


@dataclass(frozen=True)
class ContaDoPainel:
    rotulo: str
    numero: str = ""        # a ler, como o seletor do Sicoob escreve ("12.345-6")
    motivo: str = ""        # do Sicoob, mas não se lê — e por quê

    @property
    def do_sicoob(self) -> bool:
        return bool(self.numero or self.motivo)


def contas_do_painel(linhas, contas_erp, mapping, mapa_mc, empresas) -> list[ContaDoPainel]:
    """Uma `ContaDoPainel` por linha, na ordem. O nome usado é o da conta do
    ERP que cai na linha (a mesma régua do painel); sem ela, o `erp_name` do
    mapeamento; sem ele, o rótulo."""
    nome_da_linha: dict[int, str] = {}
    for conta in contas_erp or []:
        if mapping.is_ignored(conta.name):
            continue
        row = mapping.resolve_account(conta)
        if row is not None:
            nome_da_linha.setdefault(row.row, conta.name)
    saida = []
    for ln in linhas:
        row = mapping.by_row(ln.linha)
        nome = nome_da_linha.get(ln.linha) or (row.erp_name if row else "") or ln.rotulo
        numero, motivo = ag.conta_sicoob(nome, mapa_mc, empresas)
        if numero:
            saida.append(ContaDoPainel(ln.rotulo, numero=numero))
        elif motivo != ag.MOTIVO_FORA_SICOOB and ag._diz_sicoob(nome):
            saida.append(ContaDoPainel(ln.rotulo, motivo=motivo))
        else:
            saida.append(ContaDoPainel(ln.rotulo))
    vezes = Counter(_digitos(c.numero) for c in saida if c.numero)
    return [ContaDoPainel(c.rotulo, motivo=MOTIVO_REPETIDA.format(numero=c.numero))
            if c.numero and vezes[_digitos(c.numero)] > 1 else c for c in saida]


def numeros_a_ler(contas) -> list[str]:
    vistos, saida = set(), []
    for c in contas:
        if c.numero and _digitos(c.numero) not in vistos:
            vistos.add(_digitos(c.numero))
            saida.append(c.numero)
    return saida


@dataclass
class SaldoLido:
    numero: str
    saldo: Decimal | None
    lido_em: datetime | None
    motivo: str = ""
    #: De que leitura veio: 1 = o primeiro login; 2 = o OUTRO acesso do
    #: Sicoob (`extratos_sicoob.saldo.ler_em_dois_acessos`).
    acesso: int = 1


@dataclass
class LeituraSicoob:
    data: date
    contas: dict = field(default_factory=dict)       # dígitos -> SaldoLido

    @classmethod
    def de_resultados(cls, data: date, resultados) -> "LeituraSicoob":
        return cls(data, {_digitos(r.numero): SaldoLido(r.numero, r.saldo, r.lido_em, r.motivo,
                                                        int(getattr(r, "acesso", 1) or 1))
                          for r in resultados})

    @property
    def hora(self) -> datetime | None:
        """A da conta lida há mais tempo (`None` se nenhuma foi lida)."""
        horas = [l.lido_em for l in self.contas.values()
                 if l.saldo is not None and l.lido_em is not None]
        return min(horas) if horas else None


def aplicar(linhas, contas, leitura) -> list:
    if leitura is None:
        return list(linhas)
    por_rotulo = {c.rotulo: c for c in contas}
    saida = []
    for ln in linhas:
        c = por_rotulo.get(ln.rotulo)
        if c is None or not c.do_sicoob:
            saida.append(ln)
        # Reler SUBSTITUI a leitura: falha zera o lido antigo (nunca um valor
        # velho calado ao lado da nota), e o lido novo apaga a nota antiga.
        elif c.motivo:
            saida.append(replace(ln, banco=None, nota_banco=PREFIXO + c.motivo))
        else:
            lido = leitura.contas.get(_digitos(c.numero))
            if lido is None:
                saida.append(replace(ln, banco=None,
                                     nota_banco=PREFIXO + MOTIVO_FORA_DA_LEITURA))
            elif lido.saldo is None:
                saida.append(replace(ln, banco=None,
                                     nota_banco=PREFIXO + (lido.motivo or "sem motivo")))
            else:
                saida.append(replace(ln, banco=lido.saldo, nota_banco=""))
    return saida


def texto_da_hora(leitura, contas, *, lendo=None, ligado=True) -> str:
    if lendo:
        feitas, total = lendo
        return f"Lendo o Sicoob… {feitas} de {total} contas"
    if not ligado:
        return "Saldo do Sicoob: leitura ainda não ligada — digite o saldo do banco"
    if leitura is None:
        return "Sicoob ainda não lido hoje"
    a_ler = {_digitos(n) for n in numeros_a_ler(contas)} or set(leitura.contas)
    ok = [l for k, l in leitura.contas.items()
          if k in a_ler and l.saldo is not None and l.lido_em is not None]
    if not ok:
        return "Sicoob não lido — veja a situação de cada conta"
    texto = f"Sicoob lido às {min(l.lido_em for l in ok):%H:%M}"
    if len(ok) < len(a_ler):
        texto += f" · {len(ok)} de {len(a_ler)} contas (as outras: veja a situação)"
    return texto


def recusa_pela_data(data: date, hoje: date) -> str:
    """Vazio = pode ler. O saldo lido do Sicoob é o de AGORA: só vale para o
    dia de trabalho de hoje. Com o período escolhido terminando noutro dia
    (campo de datas, 22/10/2026) — ou a tela de ontem depois da meia-noite —,
    ler gravaria o saldo de hoje no arquivo de outro dia."""
    if data == hoje:
        return ""
    return (f"O saldo do Sicoob é o de agora e só vale para hoje: a tela é de "
            f"{data:%d/%m}. Para ler o Sicoob, busque com o período terminando "
            "hoje; para outro dia, digite o saldo do banco.")


def pergunta_outro_acesso(faltam, contas) -> str:
    """A pergunta do fim da leitura quando sobrou conta de OUTRO acesso do
    Sicoob (prova ao vivo de 22/10/2026). Cada conta pelo rótulo do painel;
    sem ele, pelo número."""
    rotulo = {_digitos(c.numero): c.rotulo for c in contas if c.numero}
    nomes = ", ".join(rotulo.get(_digitos(n)) or n for n in faltam)
    n = len(faltam)
    quantas = "1 conta é" if n == 1 else f"{n} contas são"
    return (f"{quantas} de outro acesso do Sicoob ({nomes}). Entrar com o outro "
            "acesso agora?\n\nO Chrome do Sicoob fecha e abre de novo: entre com o "
            "outro acesso (QR Code) e o app lê só essas. É só leitura.")


def recado_da_falha(erro, depois: str = "clique em Reler Sicoob.") -> str:
    """`depois` = o que fazer quando a outra aba terminar (a Prova de saldos
    não tem o botão Reler Sicoob)."""
    texto = str(erro or "").strip()
    if any(p in texto.lower() for p in _PERFIL_EM_USO):
        return ("O Chrome do Sicoob já está aberto por outra aba (Extratos, "
                "Comprovantes ou Conferir agendamentos). Espere ela terminar e "
                + depois)
    primeira = (texto.splitlines() or [""])[0].strip()[:200]
    return f"Sicoob: {primeira or type(erro).__name__}"


# ---------------------------------------------------------------- o arquivo

def caminho(raiz_saida, data: date) -> Path:
    return ddt.pasta_do_dia(raiz_saida, data) / f"{data:%d %m} - saldos do sicoob.json"


def para_dict(leitura: LeituraSicoob) -> dict:
    return {"versao": VERSAO, "data": leitura.data.isoformat(), "contas": [
        {"numero": l.numero, "saldo": None if l.saldo is None else str(l.saldo),
         "lido_em": None if l.lido_em is None else l.lido_em.isoformat(timespec="seconds"),
         "motivo": l.motivo, "acesso": l.acesso} for l in leitura.contas.values()]}


def de_dict(dados: dict, data: date) -> LeituraSicoob:
    try:
        itens = [SaldoLido(str(c["numero"]),
                           None if c.get("saldo") is None else Decimal(str(c["saldo"])),
                           None if c.get("lido_em") is None else datetime.fromisoformat(c["lido_em"]),
                           str(c.get("motivo") or ""),
                           int(c.get("acesso") or 1))
                 for c in dados.get("contas") or []]
    except (KeyError, TypeError, ValueError, AttributeError, InvalidOperation) as e:
        raise ValueError(f"formato inesperado ({e!r})") from e
    for i in itens:
        if i.saldo is not None and not i.saldo.is_finite():
            raise ValueError(f"saldo inválido na conta {i.numero}")
    return LeituraSicoob(data, {_digitos(i.numero): i for i in itens})


def ler(arquivo, data: date) -> tuple[LeituraSicoob | None, str]:
    """`(leitura, "")`; ausente ou de outro dia = `(None, "")`; estragado =
    `(None, aviso)`. Nunca levanta: a leitura se refaz com Reler Sicoob."""
    p = Path(arquivo)
    if not p.is_file():
        return None, ""
    try:
        dados = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(dados, dict):
            raise ValueError("o conteúdo não é um objeto")
        if str(dados.get("data")) != data.isoformat():
            return None, ""
        return de_dict(dados, data), ""
    except (OSError, ValueError) as e:
        return None, f"não consegui ler {p.as_posix()}: {e}"


def gravar(leitura: LeituraSicoob, arquivo) -> Path:
    """Gravação atômica (temporário + `os.replace`), como o dia de trabalho."""
    p = Path(arquivo)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(para_dict(leitura), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    return p
