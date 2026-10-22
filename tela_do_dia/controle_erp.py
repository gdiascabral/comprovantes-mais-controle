# -*- coding: utf-8 -*-
"""Os recebimentos de aporte, lidos do Mais Controle pelo Chrome do app. Só GET.

Mesmo endereço e mesma paginação da aba Contratos
(`anexar/mc_api.py`, `listar_recebimentos`): `receipt-installments` do
legado, pela aba do robô, com os cabeçalhos que a própria página mandou. NÃO
reaproveita `listar_recebimentos`: ela fixa as naturezas de VENDA e não
filtra conta, e mudá-la mexeria na aba Contratos.

Duas coisas deste endereço não foram medidas em produção, e por isso são
CONFERIDAS em vez de confiadas: se `accountIds` filtra a conta e se
`natureIds` filtra a natureza. Filtro aceito e ignorado em silêncio é o
defeito conhecido da casa (`pageIndex`, ver `listar_recebimentos`). A mesma
parcela em duas contas, em duas naturezas ou na conta de contraprova PARA a
leitura — nada é somado.

Cliente vazio (fato medido em 21/10/2026: a aba Aportes manda o Cliente só
pelo id, `mc_lancamentos.criar_recebimento`): quando o item traz o id do
Cliente, o nome sai do cadastro de contatos (`contacts/participants`, o mesmo
endereço e os mesmos filtros de `aportes/mc_catalogos.py`) e vai ANOTADO no
item, numa chave nossa (`CHAVE_CLIENTE_DO_CADASTRO`) — o `customerName` cru
não é reescrito. Quem decide se o nome é de um aportador continua sendo
`controle_aportes.identificar_aportador`, pelo nome completo. O cadastro só é
lido quando há Cliente vazio com id; se ele falhar, a leitura segue e esses
recebimentos ficam sem dono (fora da conta, à vista) — nunca contados no
escuro.
"""
from __future__ import annotations

from urllib.parse import urlencode

import util
from aportes.regras import NATUREZA_RECEBIMENTO, TIPO_INVESTIDOR
from conciliacao.errors import ErpError

from . import controle_aportes as ca

#: As naturezas que a aba Aportes usa nos recebimentos de aporte
#: (`aportes/regras.py`, `NATUREZA_RECEBIMENTO`). "Outras receitas"
#: (distribuição) fica fora.
NATUREZAS_DE_APORTE = (NATUREZA_RECEBIMENTO["Aporte de Capital"],
                       NATUREZA_RECEBIMENTO[TIPO_INVESTIDOR])
POR_PAGINA = 200
MAX_PAGINAS = 50
CONTATOS_POR_PAGINA = 100
CHAVE_CLIENTE_DO_CADASTRO = ca.CHAVE_CLIENTE_DO_CADASTRO
_CHAVES_CONTA = ("accountName", "defaultAccountName", "bankAccountName")
_RECADO = "Recarregue o Mais Controle no Chrome do app e atualize de novo."
_NADA = "Nada foi somado."


def _parar_se_erro(corpo, o_que: str) -> None:
    if isinstance(corpo, dict) and corpo.get("__erro"):
        raise ErpError(f"o Mais Controle respondeu {corpo['__erro']} ao {o_que}. {_RECADO}")


def _lista(corpo) -> list:
    if isinstance(corpo, list):
        return corpo
    if isinstance(corpo, dict):
        for campo in ("content", "data", "items", "results"):
            if isinstance(corpo.get(campo), list):
                return corpo[campo]
    return []


def garantir_acesso(api, log=print) -> None:
    if not getattr(api, "_req_pagos", None) and not api.capturar_credenciais(log):
        raise ErpError("a tela de Pagamentos do Chrome do app não deu o acesso aos "
                       f"recebimentos. {_RECADO}")
    if not getattr(api, "_req_anexos", None) and not api.garantir_credenciais_anexos(log):
        raise ErpError(f"o Chrome do app não deu o acesso ao cadastro de naturezas. {_RECADO}")


def ids_das_naturezas(api, nomes=NATUREZAS_DE_APORTE) -> dict:
    """{nome da natureza: id}. Natureza que falta ou repete PARA."""
    base, headers = api._base_erp("natures")
    corpo = api._fetch_json(base, headers)
    _parar_se_erro(corpo, "listar as naturezas")
    por_nome: dict = {}
    for n in _lista(corpo):
        if isinstance(n, dict) and n.get("id") and n.get("name"):
            por_nome.setdefault(util.norm_espaco(n["name"]), []).append(str(n["id"]))
    saida = {}
    for nome in nomes:
        ids = por_nome.get(util.norm_espaco(nome)) or []
        if len(ids) != 1:
            onde = "não existe" if not ids else "aparece duas vezes"
            raise ErpError(f'a natureza "{nome}" {onde} no Mais Controle — sem ela o '
                           "controle não sabe o que é aporte.")
        saida[nome] = ids[0]
    return saida


def recebimentos(api, conta_id: str, natureza_id: str, inicio, fim, log=print) -> list:
    """Os itens crus de UMA conta e UMA natureza, todas as páginas."""
    base, headers = api._base_legacy("receipt-installments")
    todos: list = []
    pagina = 0
    while True:
        params = [("startDate", inicio.isoformat()), ("endDate", fim.isoformat()),
                  ("dateField", "DATE_OF_RECEIPT"), ("type", "PAID"),
                  ("accountIds", conta_id), ("natureIds", natureza_id),
                  ("page", str(pagina)), ("size", str(POR_PAGINA))]
        corpo = api._fetch_json(f"{base}?{urlencode(params)}", headers)
        _parar_se_erro(corpo, "listar os recebimentos de aporte")
        # Sem `content` em lista não é "nenhum aporte": é resposta que não sei
        # ler, e lista vazia aqui viraria "em dia" no escuro.
        lote = corpo.get("content") if isinstance(corpo, dict) else None
        if not isinstance(lote, list):
            raise ErpError("o Mais Controle devolveu os recebimentos num formato que não "
                           f"conheço. {_NADA} {_RECADO}")
        todos.extend(lote)
        if corpo.get("last") or not lote:
            return todos
        pagina += 1
        if pagina >= MAX_PAGINAS:
            raise ErpError(f"mais de {MAX_PAGINAS} páginas de recebimentos de aporte: parei "
                           "para não devolver uma lista pela metade.")


def conta_do_item(item) -> str:
    """O nome da conta que o item declara, quando declara; "" quando não."""
    item = item if isinstance(item, dict) else {}
    for chave in _CHAVES_CONTA:
        v = item.get(chave)
        if isinstance(v, str) and v.strip():
            return v.strip()
    conta = item.get("account")
    if isinstance(conta, dict) and str(conta.get("name") or "").strip():
        return str(conta["name"]).strip()
    return ""


def conferir_filtros(crus: dict, nomes_no_erp: dict, contraprova=()) -> None:
    """`crus`: {rótulo: {natureza: [itens]}}. Levanta `ErpError` quando a
    leitura mostra que um filtro foi ignorado."""
    dono: dict = {}
    for rotulo, por_natureza in crus.items():
        alvo = util.norm_espaco(nomes_no_erp.get(rotulo, ""))
        for natureza, itens in por_natureza.items():
            for item in itens:
                ident = str((item if isinstance(item, dict) else {}).get("id") or "")
                if not ident:
                    continue             # `recebimento_do_erp` recusa depois
                visto = dono.get(ident)
                if visto and visto[0] != rotulo:
                    raise ErpError("a mesma parcela veio em duas contas: o Mais Controle "
                                   f"ignorou o filtro de conta. {_NADA} {_RECADO}")
                if visto and visto[1] != natureza:
                    raise ErpError("a mesma parcela veio em duas naturezas: o Mais Controle "
                                   f"ignorou o filtro de natureza. {_NADA} {_RECADO}")
                dono[ident] = (rotulo, natureza)
                conta = conta_do_item(item)
                if conta and util.norm_espaco(conta) != alvo:
                    raise ErpError(f'pedi os recebimentos de "{nomes_no_erp.get(rotulo)}" e '
                                   f'veio um de "{conta}": o filtro de conta não valeu. {_NADA}')
    if any(str((i if isinstance(i, dict) else {}).get("id") or "") in dono for i in contraprova):
        raise ErpError("a conta de contraprova devolveu parcelas das contas do controle: o "
                       f"filtro de conta foi ignorado. {_NADA}")


def nomes_dos_clientes(api, ids, log=print) -> dict:
    """{id do Cliente: nome} para os `ids` pedidos, pelo cadastro de contatos.

    Mesmo endereço e mesmos filtros de `aportes/mc_catalogos.py` (`carregar`),
    que já rodam em produção: `pageIndex` base 1, `pageSize`, fim por
    `hasNextPage`. Id que aparece com dois nomes diferentes não resolve
    (fica de fora). Erro do ERP levanta `ErpError`."""
    procurados = {str(i) for i in ids if str(i).strip()}
    if not procurados:
        return {}
    base, headers = api._base_erp("contacts/participants")
    achados: dict = {}
    for pagina in range(1, MAX_PAGINAS + 1):
        params = {"statusesList": "ACTIVE",
                  "rolesList": ["SUPPLIER", "CUSTOMER", "EMPLOYEE", "BOTH"],
                  "pageSize": CONTATOS_POR_PAGINA, "pageIndex": pagina}
        corpo = api._fetch_json(f"{base}?{urlencode(params, doseq=True)}", headers)
        _parar_se_erro(corpo, "ler o cadastro de contatos")
        lote = _lista(corpo)
        for c in lote:
            if not isinstance(c, dict):
                continue
            ident, nome = str(c.get("id") or "").strip(), c.get("name")
            if ident in procurados and isinstance(nome, str) and nome.strip():
                achados.setdefault(ident, set()).add(nome.strip())
        if not (isinstance(corpo, dict) and corpo.get("hasNextPage")) or not lote:
            break
    else:
        raise ErpError(f"mais de {MAX_PAGINAS} páginas no cadastro de contatos: parei.")
    saida = {}
    for ident, nomes in achados.items():
        if len({util.norm_espaco(n) for n in nomes}) == 1:
            saida[ident] = sorted(nomes)[0]
        else:
            log(f"[!] O mesmo id de Cliente aparece com {len(nomes)} nomes no cadastro de "
                "contatos — o recebimento dele fica sem dono.")
    return saida


def _anotar_clientes_vazios(api, crus: dict, log=print) -> dict:
    """Devolve `crus` com os itens de Cliente vazio e id conhecido COPIADOS e
    anotados com o nome do cadastro. Não muda os dicionários recebidos."""
    vazios = [(rotulo, natureza, n, item)
              for rotulo, por_natureza in crus.items()
              for natureza, itens in por_natureza.items()
              for n, item in enumerate(itens)
              if isinstance(item, dict) and not ca.nome_do_cliente(item)]
    if not vazios:
        return crus
    sem_id = [item for _, _, _, item in vazios if not ca.id_do_cliente(item)]
    if sem_id:
        campos = sorted({str(k) for item in sem_id for k in item})
        log(f"[!] {len(sem_id)} recebimento(s) de aporte sem Cliente e sem id de Cliente: "
            f"ficam sem dono até alguém apontar. Campos que o Mais Controle mandou: "
            f"{', '.join(campos)}.")
    ids = {ca.id_do_cliente(item) for _, _, _, item in vazios} - {""}
    if not ids:
        return crus
    try:
        nomes = nomes_dos_clientes(api, ids, log)
    except ErpError as e:
        log(f"[!] Não deu para ler o cadastro de contatos ({e}): os recebimentos de aporte "
            "sem Cliente ficam sem dono até alguém apontar.")
        return crus
    saida = {rotulo: {natureza: list(itens) for natureza, itens in por_natureza.items()}
             for rotulo, por_natureza in crus.items()}
    for rotulo, natureza, n, item in vazios:
        nome = nomes.get(ca.id_do_cliente(item))
        if nome:
            saida[rotulo][natureza][n] = dict(item, **{CHAVE_CLIENTE_DO_CADASTRO: nome})
    return saida


def ler_recebimentos(api, pares, hoje, *, contraprova=None, log=print) -> dict:
    """{rótulo da conta no controle: {natureza: [itens crus]}}, conferido."""
    garantir_acesso(api, log)
    naturezas = ids_das_naturezas(api)
    crus: dict = {}
    for par in pares:
        log(f"Lendo os aportes de {par.nome_no_erp} desde {par.inicio:%d/%m/%Y}...")
        crus[par.rotulo] = {nome: recebimentos(api, par.conta_id, ident, par.inicio, hoje, log)
                            for nome, ident in naturezas.items()}
    prova: list = []
    if contraprova is not None and pares:
        for ident in naturezas.values():
            prova.extend(recebimentos(api, contraprova.conta_id, ident,
                                      contraprova.inicio, hoje, log))
    conferir_filtros(crus, {p.rotulo: p.nome_no_erp for p in pares}, prova)
    return _anotar_clientes_vazios(api, crus, log)
