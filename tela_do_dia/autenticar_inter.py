# -*- coding: utf-8 -*-
"""A leitura do Inter do "Autenticar no banco" — roda na thread de quem
chama e não toca em Tk. SÓ LEITURA.

Dono, 29/10/2026: "Inter: QR por conta toda manhã, a mesma leitura servindo
para saldo (Prova de saldos) e para autenticar". Por isso a sessão é a do
`inter_saldo.ler_conta` da Prova — um QR por conta, a conta aberta
CONFERIDA, o saldo e o print — e, pelo gancho `extra` dela, na mesma sessão:

1. o extrato Pix (`inter_baixar._JS_EXTRATO_PIX`): só os ENVIADOS
   (`autenticar.do_pix_inter`, medido: o extrato mistura D e C);
2. a 2ª via, PAGAMENTO e DARF (`inter_baixar._JS_LISTAR`): código de
   barras, descrição e status EFETIVADO (`autenticar.do_2via_inter`);
3. o extrato completo (o corpo que a tela do extrato pede): é ali que está
   o pagamento de CONVÊNIO, que nem a 2ª via nem o extrato Pix trazem. Para
   não contar o mesmo pagamento duas vezes, dele só entra a saída que NÃO é
   Pix (o Pix já veio no passo 1) e que não tem, na 2ª via, outro de mesmo
   valor no mesmo dia (`do_extrato_sem_repetir`).

O saldo lido vai para `<pasta do dia>/DD MM - saldos do inter.json`
(`gravar_saldos`), e a Prova de saldos o usa no mesmo dia em vez de pedir o
QR de novo (`saldo_do_dia`).
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import util

from . import autenticar as au
from . import autenticar_sicoob as asi
from . import dia_de_trabalho as ddt
from . import prova_saldos as ps

OCUPADO = asi.OCUPADO


@dataclass(frozen=True)
class ContaInter:
    apelido: str
    conta_erp: str
    numero: str = ""
    nomes: tuple = ()
    razoes: tuple = ()


def contas_a_ler(pendentes, mapa_mc, empresas, contas_inter, contas_erp) -> tuple[dict, dict]:
    """({apelido: ContaInter}, {conta do ERP: motivo}) das contas do Inter
    com agendado pendente, pela MESMA régua da Prova de saldos
    (`prova_saldos.contas_da_prova`): o banco pelo `contas_mc`, o login pela
    empresa no `contas_inter.json` (um só), o número pela conta do ERP. Duas
    contas do ERP no mesmo login não são lidas: um pagamento casaria nas duas."""
    por_nome = {util.norm_espaco(getattr(c, "name", "")): c for c in contas_erp or ()}
    por_apelido: dict[str, list] = {}
    falhas: dict[str, str] = {}
    for conta in dict.fromkeys(a.conta for a in pendentes):
        destino = mapa_mc.de(conta) if mapa_mc is not None else None
        if destino is None or not ps.e_inter(destino.banco):
            continue
        empresa = util.norm_espaco(destino.empresa)
        logins = [c for c in contas_inter or [] if util.norm_espaco(c.empresa) == empresa]
        if not logins:
            falhas[conta] = ps.INTER_FORA_DA_LISTA
            continue
        if len(logins) > 1:
            falhas[conta] = ps.INTER_DOIS_LOGINS
            continue
        erp = por_nome.get(util.norm_espaco(conta))
        numero = ps.digitos(getattr(erp, "account_number", "") or "")
        razoes = [getattr(e, "razao_social", "") for e in empresas or []
                  if util.norm_espaco(getattr(e, "nome", "")) == empresa]
        nomes = tuple(dict.fromkeys(n for n in (destino.empresa, logins[0].empresa, *razoes)
                                    if (n or "").strip()))
        inteiras = tuple(dict.fromkeys(r for r in razoes if (r or "").strip()))
        c = ContaInter(logins[0].apelido, conta, numero, nomes, inteiras)
        por_apelido.setdefault(ps.chave_inter(c.apelido), []).append(c)
    saida = {}
    for chave, contas in por_apelido.items():
        if len(contas) > 1:
            for c in contas:
                falhas[c.conta_erp] = ps.INTER_REPETIDA.format(apelido=c.apelido)
        else:
            saida[chave] = contas[0]
    return saida, falhas


def _tipo_do_extrato(detalhe: dict) -> str:
    return str(((detalhe or {}).get("metadata") or {}).get("transactionType") or "").upper()


def do_extrato_sem_repetir(corpo, conta_erp: str, da_2via) -> list:
    """As saídas do extrato completo que NÃO estão nas outras listas: sem
    Pix (veio do extrato Pix) e sem o que a 2ª via já tem (mesmo valor, mesmo
    dia). O que sobra é o convênio e o resto que só o extrato mostra."""
    ja = {(m.data, m.valor) for m in da_2via}
    saida = []
    for detalhe in au.transacoes_do_extrato_inter(corpo):
        if _tipo_do_extrato(detalhe) == "PIX":
            continue
        m = au.do_extrato_inter(detalhe, conta_erp)
        if m is None or (m.data, m.valor) in ja:
            continue
        saida.append(m)
    return saida


def listar_na_sessao(page, autorizacao, extrato, conta_erp: str,
                     inicio: _dt.date, fim: _dt.date) -> list:
    """Os pagamentos que SAÍRAM da conta, com a sessão do `inter_saldo`
    (a conta já conferida). Levanta quando a API do Inter recusa: lista
    incompleta não pode virar "nada no banco"."""
    from baixar_comprovantes import inter_baixar as ib
    cab = autorizacao.get("valor") or ""
    if not cab:
        raise RuntimeError("a sessão do Inter não deu a autorização para listar")
    r = page.evaluate(ib._JS_EXTRATO_PIX, [ib.API_INTER, cab]) or {}
    if r.get("erro"):
        raise RuntimeError(f"extrato Pix do Inter: {r['erro']}")
    pix = [m for m in (au.do_pix_inter(x, conta_erp) for x in r.get("movimentacoes") or ())
           if m is not None]
    da_2via = []
    for tipo in ib.TIPOS_DA_API:
        r = page.evaluate(ib._JS_LISTAR, [ib.API_INTER, cab, f"{inicio:%Y-%m-%d}",
                                          f"{fim:%Y-%m-%d}", tipo]) or {}
        if r.get("erro"):
            raise RuntimeError(f"2ª via do Inter ({tipo}): {r['erro']}")
        da_2via.extend(m for m in (au.do_2via_inter(x, conta_erp)
                                   for x in r.get("operacoes") or ()) if m is not None)
    corpo = extrato()
    if corpo is None:
        raise RuntimeError("a tela do extrato completo do Inter não respondeu")
    return [*pix, *da_2via, *do_extrato_sem_repetir(corpo, conta_erp, da_2via)]


def ler(contas: dict, inicio, fim, pasta_prints, *, log, ler_conta=None, avisar_qr=None,
        ao_entrar=None, parar=lambda: False) -> tuple:
    """(Leitura como a do Sicoob, {apelido: LidoInter}) das `contas`. Uma
    conta por vez, cada uma com o seu QR. Nunca levanta."""
    if ler_conta is None:
        from baixar_comprovantes import inter_saldo
        ler_conta = inter_saldo.ler_conta
    r = asi.Leitura()
    lidos = {}
    for chave, c in contas.items():
        if parar():
            r.falhas[c.conta_erp] = "parado antes desta conta"
            continue

        def extra(page, autorizacao, extrato, c=c):
            return listar_na_sessao(page, autorizacao, extrato, c.conta_erp, inicio, fim)
        try:
            lido = ler_conta(c.apelido, c.numero, c.nomes,
                             Path(pasta_prints) / f"inter {chave}.png", razoes=c.razoes,
                             log=lambda m, a=c.apelido: log(f"  Inter {a}: {m}"),
                             avisar_qr=avisar_qr or (lambda a: None),
                             ao_entrar=ao_entrar or (lambda a: None), parar=parar,
                             extra=extra)
        except Exception as e:                               # noqa: BLE001
            r.falhas[c.conta_erp] = f"o Inter não foi lido: {asi._primeira(e)}"
            continue
        lidos[chave] = lido
        if lido.motivo:
            r.falhas[c.conta_erp] = lido.motivo
        elif lido.extra_erro or lido.extra is None:
            r.falhas[c.conta_erp] = (f"saldo lido, mas as listas do Inter falharam: "
                                     f"{lido.extra_erro or 'sem resposta'}")
        else:
            r.movimentos.extend(lido.extra)
            r.lidas.add(c.conta_erp)
        log(f"  Inter {c.apelido}: " + ("lido" if c.conta_erp in r.lidas
                                       else r.falhas[c.conta_erp]))
    return r, lidos


# ------------------------------------------- o saldo do dia para a Prova
def caminho_dos_saldos(raiz_saida, data: _dt.date) -> Path:
    return ddt.pasta_do_dia(raiz_saida, data) / f"{data:%d %m} - saldos do inter.json"


def gravar_saldos(lidos: dict, arquivo, data: _dt.date) -> Path | None:
    """Junta ao arquivo do dia os saldos LIDOS (com a hora e o print). Sem
    saldo nenhum, não grava. Escreve num .tmp e troca (não deixa meio arquivo)."""
    novos = {chave: {"saldo": str(l.saldo), "lido_em": l.lido_em.isoformat(),
                     "imagem": str(l.imagem or ""), "via": l.via}
             for chave, l in lidos.items()
             if getattr(l, "saldo", None) is not None and getattr(l, "lido_em", None)}
    if not novos:
        return None
    p = Path(arquivo)
    dados = {"data": data.isoformat(), "contas": {}}
    try:
        antes = json.loads(p.read_text(encoding="utf-8"))
        if antes.get("data") == data.isoformat():
            dados["contas"].update(antes.get("contas") or {})
    except (OSError, ValueError, AttributeError):
        pass
    dados["contas"].update(novos)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    return p


def saldo_do_dia(arquivo, data: _dt.date, apelido: str) -> ps.Leitura | None:
    """O saldo que o "Autenticar no banco" leu HOJE desta conta do Inter,
    como `prova_saldos.Leitura`, ou None (arquivo ausente, de outro dia,
    estragado, conta sem saldo). Estragado nunca vira saldo."""
    try:
        dados = json.loads(Path(arquivo).read_text(encoding="utf-8"))
        if dados.get("data") != data.isoformat():
            return None
        c = (dados.get("contas") or {}).get(ps.chave_inter(apelido))
        if not c:
            return None
        saldo = Decimal(str(c["saldo"]))
        lido_em = _dt.datetime.fromisoformat(c["lido_em"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError, InvalidOperation):
        return None
    if lido_em.date() != data or not saldo.is_finite():
        return None
    imagem = Path(c["imagem"]) if c.get("imagem") else None
    if imagem is not None and not imagem.is_file():
        imagem = None
    return ps.Leitura(saldo, lido_em, "", imagem,
                      "" if imagem else "o print do Autenticar no banco não está mais na pasta")
