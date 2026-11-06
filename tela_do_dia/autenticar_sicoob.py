# -*- coding: utf-8 -*-
"""A leitura do Sicoob do "Autenticar no banco" — roda na thread do Sicoob de
quem chama e não toca em Tk. SÓ LEITURA: nada se assina, baixa ou altera.

Por conta do Sicoob que tem agendado pendente:

1. entra na conta (`acessar_conta`) e CONFERE que a aberta é a pedida
   (`sicoob_baixar.conta_aberta` + `mesma_conta`) — as listas não levam a
   conta, ela é implícita na sessão, e a conta errada aberta devolveria o
   pagamento DE OUTRA empresa sem nada denunciar;
2. a lista de comprovantes (mês a mês: o banco recusa período que atravessa
   o mês), só os EFETIVADOS e sem Pix (`autenticar.do_comprovante_sicoob`);
3. a lista de Pix enviados (`sicoob_baixar.listar_pix`);
4. as pendências de assinatura (`extratos_sicoob.pendencias.consultar`), a
   contraprova.

**O comprovante só é aberto (em HTML, sem gerar PDF nem salvar arquivo)
quando a lista não traz código nem descrição E há agendado de mesmo valor
naquela conta** (dono, 29/10/2026). O que o HTML traz é a medir na primeira
rodada (tarefa 0 da spec); o que não se acha nele deixa o item como veio.

Duas contas do ERP no MESMO número do Sicoob não são lidas: um pagamento
casaria nas duas (`autenticar` casa por conta do ERP). Ficam "não lidas" com
o porquê. Conta de outro acesso: `perguntar(nomes)` como no "Conferir
agendamentos" (o mesmo Chrome abre de novo; nada digita senha).
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field

from . import autenticar as au

OCUPADO = "Pagamentos do dia — autenticando no banco"
FORA_DESTE_LOGIN = "esta conta não aparece neste login do Sicoob"
MESMO_NUMERO = ("duas contas do ERP apontam para o mesmo número do Sicoob — "
                "não dá para dizer de qual é o pagamento; responda")
MESMO_ACESSO = ("o Chrome voltou no mesmo acesso do Sicoob: saia do SicoobNet "
                "(botão Sair) e autentique de novo para entrar com o outro acesso")


def _primeira(e) -> str:
    texto = str(e).strip()
    return texto.splitlines()[0] if texto else repr(e)


@dataclass
class Leitura:
    movimentos: list = field(default_factory=list)
    pendencias: list = field(default_factory=list)
    lidas: set = field(default_factory=set)        # contas do ERP lidas inteiras
    falhas: dict = field(default_factory=dict)     # conta do ERP -> motivo


def periodo(pendentes, hoje: _dt.date) -> tuple[_dt.date, _dt.date] | None:
    """Do dia anterior ao agendado mais antigo até hoje (spec)."""
    dias = [a.dia for a in pendentes]
    if not dias:
        return None
    return min(dias) - _dt.timedelta(days=1), hoje


def contas_a_ler(pendentes, conta_sicoob) -> tuple[dict, dict]:
    """({número do Sicoob: conta do ERP}, {conta do ERP: motivo}) — só as
    contas que têm pendente. `conta_sicoob(conta_erp) -> (número, motivo)`
    é o caminho da remessa (`agendamentos_sicoob.conta_sicoob`). Conta de
    outro banco não entra em nenhuma das duas (é do Inter, ou fica sem prova)."""
    from pagamentos_dia.agendamentos_sicoob import MOTIVO_FORA_SICOOB
    por_numero: dict[str, list] = {}
    falhas: dict[str, str] = {}
    for conta in dict.fromkeys(a.conta for a in pendentes):
        numero, motivo = conta_sicoob(conta)
        if numero:
            por_numero.setdefault(numero, []).append(conta)
        elif motivo and motivo != MOTIVO_FORA_SICOOB:
            falhas[conta] = motivo
    saida = {}
    for numero, contas in por_numero.items():
        if len(contas) > 1:
            for c in contas:
                falhas[c] = MESMO_NUMERO
        else:
            saida[numero] = contas[0]
    return saida, falhas


def valores_por_conta(pendentes) -> dict:
    """{conta do ERP: {valores em centavos dos agendados e das partes}} — o
    que faz valer abrir um comprovante."""
    saida: dict[str, set] = {}
    for a in pendentes:
        vs = saida.setdefault(a.conta, set())
        vs.add(a.valor)
        for p in (a.foto or {}).get("partes") or ():
            v = au.dinheiro(p.get("valor"))
            if v is not None:
                vs.add(v)
    return saida


def _texto_do_html(html) -> str:
    # Cada etiqueta vira QUEBRA de linha: a Observação é um campo da tabela
    # do comprovante, e com espaço no lugar ela levava o resto do texto junto.
    t = re.sub(r"<[^>]+>", "\n", str(html or ""))
    return re.sub(r"[ \t\r\f\v]+", " ", t)


def completar_pelo_html(m: au.Movimento, html) -> au.Movimento:
    """O código de barras e a observação lidos do comprovante em HTML, quando
    a lista não os trouxe. A medir: o que não se acha fica como estava."""
    from anexar.codigo_barras import codigos_no_texto
    texto = _texto_do_html(html)
    barras = m.barras
    if not barras:
        achados = codigos_no_texto(texto, valores=(int(m.valor * 100),))
        if len(achados) == 1:
            barras = next(iter(achados))
    descricao = m.descricao
    if not descricao:
        achou = re.search(r"observa[cç][aã]o[ \t]*:?[ \t]*\n*[ \t]*([^\n]+)", texto,
                          flags=re.I)
        valor_obs = achou[1].strip() if achou else ""
        # Observação vazia: a linha seguinte é o RÓTULO do próximo campo.
        if valor_obs and not valor_obs.endswith(":"):
            descricao = valor_obs
    return au.Movimento(m.conta, m.data, m.valor, barras, descricao, m.favorecido,
                        m.origem, m.ident)


def ler_conta(cli, numero: str, conta_erp: str, inicio: _dt.date, fim: _dt.date,
              valores=(), *, listar=None, listar_pix=None, consultar=None,
              detalhar=None, detalhar_pix=None) -> tuple[list, list]:
    """(movimentos, pendências) de UMA conta. Levanta com o motivo; conta
    fora deste login levanta `LookupError(FORA_DESTE_LOGIN)`."""
    from baixar_comprovantes import sicoob_baixar as sb
    if listar is None:
        from extratos_sicoob import pendencias
        listar, listar_pix, consultar = sb.listar, sb.listar_pix, pendencias.consultar
        detalhar, detalhar_pix = sb.detalhar, sb.detalhar_pix
    if not cli.acessar_conta(numero):
        raise LookupError(FORA_DESTE_LOGIN)
    sb.ir_para_comprovantes(cli.page)
    aberta = sb.conta_aberta(cli.page)
    if not sb.mesma_conta(numero, aberta):
        raise RuntimeError(f"pedi a conta {numero} e a tela está em "
                           f"{aberta or '(não consegui ler)'} — não li para não "
                           "provar com o pagamento de outra conta")
    from extratos_sicoob.pendencias import meses
    valores = set(valores or ())
    movimentos, vistos = [], set()
    for de, ate in meses(inicio, fim):
        for item in listar(cli.page, f"{de:%d/%m/%Y}", f"{ate:%d/%m/%Y}") or ():
            ident = item.get("idAgendamento")
            if ident is not None and ident in vistos:
                continue
            vistos.add(ident)
            m = au.do_comprovante_sicoob(item, conta_erp)
            if m is None:
                continue
            if (not m.barras or not m.descricao) and m.valor in valores and detalhar:
                for _item, html in detalhar(cli.page, [item]) or ():
                    m = completar_pelo_html(m, html)
            movimentos.append(m)
    for item in listar_pix(cli.page, f"{inicio:%d/%m/%Y}", f"{fim:%d/%m/%Y}") or ():
        m = au.do_pix_sicoob(item, conta_erp)
        if m is not None and not m.descricao and m.valor in valores and detalhar_pix:
            m = au.do_pix_sicoob({**item, **(detalhar_pix(cli.page, item) or {})},
                                 conta_erp) or m
        if m is not None:
            movimentos.append(m)
    pend = []
    for de, ate in meses(inicio, fim):
        for p in consultar(cli.page, numero, de, ate) or ():
            mp = au.da_pendencia(p, conta_erp)
            if mp is not None:
                pend.append(mp)
    return movimentos, pend


def ler(contas, inicio, fim, valores=None, *, log, abrir=None, ler_uma=None,
        perguntar=None, parar=lambda: False) -> Leitura:
    """Lê as `contas` ({número: conta do ERP}). Toda conta nasce "não lida"
    e só muda quando é lida de verdade: falha no meio não faz conta sumir.
    `abrir()` devolve o `SicoobClient` (o mesmo perfil do app)."""
    valores = valores or {}
    r = Leitura()
    for numero, conta in contas.items():
        r.falhas[conta] = "o Sicoob não foi lido"
    ler_uma = ler_uma or ler_conta

    def uma(cli, numero, conta) -> bool:
        """True = este login não enxerga a conta."""
        try:
            movs, pend = ler_uma(cli, numero, conta, inicio, fim, valores.get(conta, ()))
        except LookupError:
            r.falhas[conta] = FORA_DESTE_LOGIN
            return True
        except Exception as e:                               # noqa: BLE001
            r.falhas[conta] = f"o Sicoob não respondeu: {_primeira(e)}"
            log(f"  {conta} ({numero}): {r.falhas[conta]}")
            return False
        r.movimentos.extend(movs)
        r.pendencias.extend(pend)
        r.lidas.add(conta)
        r.falhas.pop(conta, None)
        log(f"  {conta} ({numero}): {len(movs)} pagamento(s) no banco, "
            f"{len(pend)} pendente(s) de assinatura")
        return False

    faltam, do_login = [], None
    try:
        if abrir is None:
            from extratos_sicoob.sicoob_client import SicoobClient

            def abrir():
                return SicoobClient(log=lambda m: log(f"  {m}"))
        with abrir() as cli:
            cli.aguardar_login()
            for numero, conta in contas.items():
                if parar():
                    break
                if uma(cli, numero, conta):
                    faltam.append((numero, conta))
            if faltam and perguntar is not None:
                try:
                    do_login = list(cli.listar_contas() or [])
                except Exception:                            # noqa: BLE001
                    do_login = None
    except Exception as e:                                   # noqa: BLE001
        log(f"[!] Autenticar no banco (Sicoob): {e}")
        for conta in list(r.falhas):
            if r.falhas[conta] == "o Sicoob não foi lido":
                r.falhas[conta] = f"o Sicoob parou: {_primeira(e)}"
        return r
    if not faltam or perguntar is None or parar() or not perguntar([c for _n, c in faltam]):
        return r
    try:
        with abrir() as cli:
            cli.aguardar_login()
            outra = list(cli.listar_contas() or [])
            if do_login is not None and sorted(map(str, outra)) == sorted(map(str, do_login)):
                for _n, conta in faltam:
                    r.falhas[conta] = MESMO_ACESSO
            else:
                for numero, conta in faltam:
                    if uma(cli, numero, conta):
                        r.falhas[conta] = "a conta não aparece em nenhum dos dois acessos"
    except Exception as e:                                   # noqa: BLE001
        for _n, conta in faltam:
            if conta not in r.lidas:
                r.falhas[conta] = f"o outro acesso do Sicoob não entrou: {_primeira(e)}"
    return r
