# -*- coding: utf-8 -*-
"""Baixar OFX (aba Conciliação): a regra, sem tela, sem rede, sem navegador.

Quais contas aparecem na lista e em que grupo (as do pagamento do dia
primeiro), o período pedido, e se um OFX é mesmo o daquela conta e daquele
período. **OFX que não confere não chega ao ERP** (spec de 29/10/2026).

Qual conta do Sicoob é cada conta do ERP sai de `agendamentos_sicoob.
conta_sicoob` (o caminho da Remessa e do "Conferir agendamentos"); qual login
do Inter, do cadastro (`contas_mc` diz o banco e a empresa) cruzado com
`contas_inter.json`, como na Prova de saldos.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, replace

import util
from pagamentos_dia import agendamentos_sicoob as ag
from tela_do_dia import prova_saldos as ps

SICOOB, INTER = ps.SICOOB, ps.INTER
#: O Inter exporta no máximo 2 anos entre as datas (tela de exportar, 29/10).
MAX_DIAS = 730
REPETIDA = "outra linha da lista já baixa esta conta"
INTER_SEM_LOGIN = ("esta conta do Inter não tem login na lista do app "
                   "(contas_inter.json)")
INTER_DOIS_LOGINS = ("a empresa tem mais de um login do Inter na lista do app — "
                     "não sei qual abrir")
IMPORTADO, NAO_IMPORTADO = "importado", "não importado"
#: Enviado e o ERP não confirmou: pode ter entrado (o app não reenvia).
NAO_VERIFICADO = "não verificado"
NADA_NOVO = "nada novo"
_RE_ACCTID = re.compile(r"<ACCTID>([^<\r\n]*)")
_RE_DT = re.compile(r"<(DTSTART|DTEND)>(\d{8})")


@dataclass(frozen=True)
class ContaOfx:
    erp_id: str                     # UUID da conta no ERP (#/transactions/<id>)
    nome: str                       # nome da conta no ERP
    banco: str                      # SICOOB | INTER
    #: Sicoob: como o cadastro escreve ("12.345-6"). Inter: os dígitos que o
    #: ERP tem ("" = não tem; aí confere contra o número da tela do banco).
    numero: str = ""
    apelido: str = ""               # Inter: o login (contas_inter.json)
    do_dia: bool = False            # a conta tem linha no painel do dia
    motivo: str = ""                # não dá para baixar: diz por quê


@dataclass
class Resultado:
    conta: ContaOfx
    situacao: str                   # IMPORTADO | NAO_IMPORTADO | NAO_VERIFICADO | NADA_NOVO
    lancamentos: int | None = None
    motivo: str = ""


def _dig(texto) -> str:
    return ps.digitos(texto).lstrip("0")


def periodo_padrao(hoje: _dt.date) -> tuple[_dt.date, _dt.date]:
    """Ontem a hoje (dono, 29/10/2026)."""
    return hoje - _dt.timedelta(days=1), hoje


def periodo_do_mes(ano: int, mes: int) -> tuple[_dt.date, _dt.date]:
    """O mês inteiro: do dia 1 ao último dia."""
    ini = _dt.date(ano, mes, 1)
    prox = _dt.date(ano + (mes == 12), mes % 12 + 1, 1)
    return ini, prox - _dt.timedelta(days=1)


def validar_periodo(ini: _dt.date, fim: _dt.date, hoje: _dt.date) -> str:
    """"" quando o período pode ser pedido; senão, o porquê."""
    if ini > fim:
        return "a data de início é depois da data de fim"
    if fim > hoje:
        return "a data de fim está no futuro"
    if (fim - ini).days > MAX_DIAS:
        return "o período passa de 2 anos (o Inter não exporta mais que isso)"
    return ""


def conferir_ofx(texto: str, numero: str, ini: _dt.date, fim: _dt.date) -> str:
    """"" quando o OFX é DESTA conta e DESTE período; senão, o porquê.

    O número compara inteiro, sem os zeros à esquerda (o Sicoob escreve
    "0012345-6"); nunca pelo fim — "2.345-6" não é "12.345-6"."""
    if not _dig(numero):
        return "não sei o número desta conta — não confiro o OFX sem ele"
    achado = _RE_ACCTID.search(texto or "")
    if not achado:
        return "o arquivo não tem ACCTID — não parece um OFX"
    if _dig(achado.group(1)) != _dig(numero):
        return f"o OFX é da conta {achado.group(1).strip()}, e esta é a {numero}"
    datas = dict(_RE_DT.findall(texto))
    esperado = (f"{ini:%Y%m%d}", f"{fim:%Y%m%d}")
    if (datas.get("DTSTART"), datas.get("DTEND")) != esperado:
        return (f"o período do OFX é {datas.get('DTSTART')}–{datas.get('DTEND')}, "
                f"e o pedido foi {esperado[0]}–{esperado[1]}")
    return ""


def lancamentos(texto: str) -> int:
    return (texto or "").count("<STMTTRN>")


def contas_para_ofx(contas_erp, mapping, mapa_mc, empresas, contas_inter,
                    linhas_do_dia, ignorar=None) -> list[ContaOfx]:
    """As contas Sicoob e Inter do ERP: as do pagamento do dia (pela linha do
    painel) e depois as outras (pelo nome). Outro banco e as contas
    ignoradas pelo dono (`ofx_periodo.ignoradas`, fora do repositório) não
    entram; a mesma conta do banco em duas linhas entra uma vez — as
    seguintes levam `REPETIDA` (nunca dois uploads do mesmo OFX)."""
    linhas_do_dia = set(linhas_do_dia or ())
    if ignorar is None:
        from extratos_sicoob.ofx_periodo import ignoradas
        ignorar = ignoradas()
    ignorar = {_dig(n) for n in ignorar}
    linha_da_conta: dict[str, int] = {}
    for c in contas_erp or []:
        if mapping.is_ignored(c.name):
            continue
        row = mapping.resolve_account(c)
        if row is not None and row.exists_in_erp:
            linha_da_conta[str(c.id)] = row.row
    achadas: list[ContaOfx] = []
    for c in contas_erp or []:
        erp_id = str(c.id)
        do_dia = linha_da_conta.get(erp_id) in linhas_do_dia
        numero, _motivo = ag.conta_sicoob(c.name, mapa_mc, empresas)
        if numero:
            if _dig(numero) not in ignorar:
                achadas.append(ContaOfx(erp_id, c.name, SICOOB, numero=numero,
                                        do_dia=do_dia))
            continue
        destino = mapa_mc.de(c.name) if mapa_mc is not None else None
        if destino is None or not ps.e_inter(destino.banco):
            continue
        empresa = util.norm_espaco(destino.empresa)
        logins = [i for i in contas_inter or [] if util.norm_espaco(i.empresa) == empresa]
        motivo = "" if len(logins) == 1 else (INTER_SEM_LOGIN if not logins
                                              else INTER_DOIS_LOGINS)
        achadas.append(ContaOfx(erp_id, c.name, INTER,
                                numero=ps.digitos(getattr(c, "account_number", "") or ""),
                                apelido=logins[0].apelido if len(logins) == 1 else "",
                                do_dia=do_dia, motivo=motivo))
    achadas.sort(key=lambda c: (not c.do_dia,
                                linha_da_conta.get(c.erp_id, 0) if c.do_dia else 0,
                                util.norm_espaco(c.nome)))
    vistas: set = set()
    saida: list[ContaOfx] = []
    for c in achadas:
        # Inter: o LOGIN decide a conta (um QR, um extrato), tenha o ERP o
        # número ou não — duas contas do ERP no mesmo login seriam o mesmo
        # OFX lançado duas vezes (revisão de 16/11/2026).
        chave = (c.banco, util.norm_espaco(c.apelido) if c.banco == INTER
                 else _dig(c.numero))
        if chave[1] and chave in vistas and not c.motivo:
            c = replace(c, motivo=REPETIDA)
        if chave[1]:
            vistas.add(chave)
        saida.append(c)
    return saida


def linha_do_resultado(r: Resultado, ini: _dt.date, fim: _dt.date) -> tuple:
    """(conta, período, lançamentos, situação) para a tabela do fim."""
    situacao = r.situacao + (f": {r.motivo}" if r.motivo else "")
    return (r.conta.nome, f"{ini:%d/%m} a {fim:%d/%m}",
            "—" if r.lancamentos is None else str(r.lancamentos), situacao)


def ler_data(texto) -> _dt.date:
    """"28/10/2026" → date; levanta ValueError com o recado para a tela."""
    try:
        return _dt.datetime.strptime(str(texto or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        raise ValueError(f"a data '{str(texto or '').strip()}' não é uma data "
                         "dd/mm/aaaa válida") from None


def nomes_da_conta(conta: ContaOfx, mapa_mc, empresas, contas_inter) -> tuple:
    """(nomes, razões) que conferem a conta aberta no Inter: o nome curto da
    empresa (cadastro), o do login e a razão social inteira — a mesma régua
    de `prova_saldos.contas_da_prova`. Conta fora do cadastro: ((), ())."""
    destino = mapa_mc.de(conta.nome) if mapa_mc is not None else None
    if destino is None:
        return (), ()
    empresa = util.norm_espaco(destino.empresa)
    logins = [i for i in contas_inter or []
              if util.norm_espaco(i.apelido) == util.norm_espaco(conta.apelido)]
    razoes = [getattr(e, "razao_social", "") for e in empresas or []
              if util.norm_espaco(getattr(e, "nome", "")) == empresa]
    candidatos = [destino.empresa, *(i.empresa for i in logins[:1]), *razoes]
    nomes = tuple(dict.fromkeys(n for n in candidatos if (n or "").strip()))
    return nomes, tuple(dict.fromkeys(r for r in razoes if (r or "").strip()))
