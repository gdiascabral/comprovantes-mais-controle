# tests/test_tela_do_dia_controle_erp.py
# -*- coding: utf-8 -*-
"""Recebimentos de aporte pelo Chrome do app — só GET. Dublês; contas fictícias."""
import datetime
from dataclasses import replace
from decimal import Decimal
from urllib.parse import parse_qs, parse_qsl, urlsplit

import pytest

from conciliacao.errors import ErpError
from conciliacao.models import ErpAccount
from tela_do_dia import controle_aportes as ca
from tela_do_dia import controle_erp as ce

ABRE, HOJE = datetime.date(2026, 10, 21), datetime.date(2026, 10, 23)
NATS = [{"id": "n-cap", "name": "Aporte de Capital"},
        {"id": "n-inv", "name": "Aporte de Investidor"}, {"id": "n-venda", "name": "Venda"}]
PAR_A = ca.Par("CONTA A - BANCO", "id-a", "CONTA A - BANCO", ABRE)
PAR_B = ca.Par("CONTA B - BANCO", "id-b", "CONTA B - BANCO", ABRE)


def _item(ident, valor=100.0, cliente="FULANO ALFA DA SILVA", **extra):
    return dict({"id": ident, "dateOfReceipt": "2026-10-22", "sumOfReceivedValues": valor,
                 "customerName": cliente}, **extra)


class Api:
    def __init__(self, recebimentos, naturezas=NATS, erro=None):
        self._req_pagos = ("https://legacy/x", {"authorization": "a"})
        self._req_anexos = ("https://erp/attachments/v2", {"authorization": "b"})
        self.recebimentos, self.naturezas, self.erro, self.urls = recebimentos, naturezas, erro, []

    def _base_legacy(self, caminho):
        return f"https://legacy/maiscontrole/services/{caminho}", {"authorization": "a"}

    def _base_erp(self, caminho):
        return f"https://erp/{caminho}", {"authorization": "b"}

    def capturar_credenciais(self, log=print):
        return True

    def garantir_credenciais_anexos(self, log=print):
        return True

    def _fetch_json(self, url, headers):
        self.urls.append(url)
        if url.startswith("https://erp/natures"):
            return self.naturezas
        if self.erro:
            return {"__erro": self.erro}
        q = dict(parse_qsl(urlsplit(url).query))
        itens = self.recebimentos.get((q["accountIds"], q["natureIds"]), [])
        pagina, tam = int(q["page"]), int(q["size"])
        return {"content": itens[pagina * tam:(pagina + 1) * tam],
                "last": (pagina + 1) * tam >= len(itens)}


def test_pede_conta_natureza_e_data_de_recebimento_e_pagina_por_page_size():
    api = Api({("id-a", "n-cap"): [_item(f"r{i}") for i in range(450)]})
    crus = ce.ler_recebimentos(api, [PAR_A], HOJE)
    assert len(crus["CONTA A - BANCO"]["Aporte de Capital"]) == 450
    assert crus["CONTA A - BANCO"]["Aporte de Investidor"] == []
    primeira = [u for u in api.urls if "receipt-installments" in u][0]
    q = dict(parse_qsl(urlsplit(primeira).query))
    assert q == {"startDate": "2026-10-21", "endDate": "2026-10-23",
                 "dateField": "DATE_OF_RECEIPT", "type": "PAID", "accountIds": "id-a",
                 "natureIds": "n-cap", "page": "0", "size": "200"}
    assert not any("pageIndex" in u or "users/login" in u for u in api.urls)


def test_natureza_que_falta_ou_repete_para():
    with pytest.raises(ErpError, match="Aporte de Investidor"):
        ce.ids_das_naturezas(Api({}, naturezas=NATS[:1]))
    with pytest.raises(ErpError, match="duas vezes"):
        ce.ids_das_naturezas(Api({}, naturezas=NATS + [{"id": "n-x", "name": "APORTE DE CAPITAL"}]))


def test_erro_do_erp_vira_erperror_e_nunca_lista_vazia():
    with pytest.raises(ErpError, match="403"):
        ce.ler_recebimentos(Api({}, erro=403), [PAR_A], HOJE)


def test_mais_de_50_paginas_para(monkeypatch):
    monkeypatch.setattr(ce, "POR_PAGINA", 1)
    api = Api({("id-a", "n-cap"): [_item(f"r{i}") for i in range(60)]})
    with pytest.raises(ErpError, match="páginas"):
        ce.ler_recebimentos(api, [PAR_A], HOJE)


def test_mesma_parcela_em_duas_contas_e_filtro_de_conta_ignorado():
    api = Api({("id-a", "n-cap"): [_item("r1")], ("id-b", "n-cap"): [_item("r1")]})
    with pytest.raises(ErpError, match="duas contas"):
        ce.ler_recebimentos(api, [PAR_A, PAR_B], HOJE)


def test_mesma_parcela_em_duas_naturezas_e_filtro_de_natureza_ignorado():
    api = Api({("id-a", "n-cap"): [_item("r1")], ("id-a", "n-inv"): [_item("r1")]})
    with pytest.raises(ErpError, match="duas naturezas"):
        ce.ler_recebimentos(api, [PAR_A], HOJE)


def test_contraprova_com_parcela_do_controle_para():
    prova = ca.Par("", "id-z", "CONTA Z", ABRE)
    api = Api({("id-a", "n-cap"): [_item("r1")], ("id-z", "n-cap"): [_item("r1")]})
    with pytest.raises(ErpError, match="contraprova"):
        ce.ler_recebimentos(api, [PAR_A], HOJE, contraprova=prova)
    api = Api({("id-a", "n-cap"): [_item("r1")], ("id-z", "n-cap"): [_item("r2")]})
    assert ce.ler_recebimentos(api, [PAR_A], HOJE, contraprova=prova)


def test_conta_do_item_divergente_para_e_igual_passa():
    api = Api({("id-a", "n-cap"): [_item("r1", accountName="CONTA B - BANCO")]})
    with pytest.raises(ErpError, match="filtro de conta"):
        ce.ler_recebimentos(api, [PAR_A], HOJE)
    api = Api({("id-a", "n-cap"): [_item("r1", accountName="conta a -  banco")]})
    assert ce.ler_recebimentos(api, [PAR_A], HOJE)


# ---- a parte pura que mora em controle_aportes
def _conta(nome="CONTA A - BANCO"):
    return ca.ContaControlada(nome, ABRE, (ca.Aportador("FULANO ALFA DA SILVA", Decimal(1)),), id=1)


def test_pares_para_ler_casa_o_nome_inteiro_da_conta():
    erp = [ErpAccount(id="id-a", name="Conta A - Banco"), ErpAccount(id="id-b", name="CONTA A - BANCO 2")]
    pares, erros = ca.pares_para_ler([_conta()], erp)
    assert pares == [ca.Par("CONTA A - BANCO", "id-a", "Conta A - Banco", ABRE)] and erros == {}
    pares, erros = ca.pares_para_ler([_conta("CONTA C")], erp)
    assert pares == [] and "não está entre as contas" in erros["CONTA C"]
    pares, erros = ca.pares_para_ler([_conta()], erp + [ErpAccount(id="id-c", name="CONTA A - BANCO")])
    assert "duas contas" in erros["CONTA A - BANCO"]


def test_contraprova_e_uma_conta_fora_do_controle():
    erp = [ErpAccount(id="id-a", name="CONTA A - BANCO"), ErpAccount(id="id-z", name="CONTA Z")]
    assert ca.conta_de_contraprova(erp, [PAR_A]) == ca.Par("", "id-z", "CONTA Z", ABRE)
    assert ca.conta_de_contraprova(erp[:1], [PAR_A]) is None


def test_apurar_tudo_isola_o_erro_de_cada_conta():
    contas = [_conta(), _conta("CONTA B - BANCO"), replace(_conta("CONTA C"), id=3)]
    crus = {"CONTA A - BANCO": {"Aporte de Capital": [_item("r1")]},
            "CONTA B - BANCO": {"Aporte de Capital": [{"id": "r2"}]}}
    aps = ca.apurar_tudo(contas, {"CONTA C": "não está entre as contas"}, crus, {}, HOJE)
    assert aps[0].linhas[0].do_erp == Decimal("100.00") and not aps[0].erro
    assert "não se lê" in aps[1].erro and aps[1].linhas == []
    assert aps[2].erro == "não está entre as contas"


# ---- além do brief: formato da resposta e o Cliente vazio (fato medido 21/10/2026)
ALFA, BETA = "FULANO ALFA DA SILVA", "FULANO BETA SOUZA"


class ApiComContatos(Api):
    """O dublê do brief, mais o cadastro de contatos paginado como o ERP
    pagina ali (`pageIndex` base 1, `pageSize`, `hasNextPage`)."""

    def __init__(self, recebimentos, contatos=(), erro_contatos=None, por_pagina=2):
        super().__init__(recebimentos)
        self.contatos, self.erro_contatos, self.por_pagina = list(contatos), erro_contatos, por_pagina

    def _fetch_json(self, url, headers):
        if url.startswith("https://erp/contacts/participants"):
            self.urls.append(url)
            if self.erro_contatos:
                return {"__erro": self.erro_contatos}
            q = parse_qs(urlsplit(url).query)
            pagina = int(q["pageIndex"][0])
            tam = self.por_pagina
            lote = self.contatos[(pagina - 1) * tam:pagina * tam]
            return {"content": lote, "hasNextPage": pagina * tam < len(self.contatos)}
        return super()._fetch_json(url, headers)


def _conta2():
    return ca.ContaControlada("CONTA A - BANCO", ABRE,
                              (ca.Aportador(ALFA, Decimal(1), id=11),
                               ca.Aportador(BETA, Decimal(1), id=12)), id=1)


def test_content_que_nao_e_lista_para():
    class Torta(Api):
        def _fetch_json(self, url, headers):
            if "receipt-installments" in url:
                self.urls.append(url)
                return {"content": {"id": "r1"}, "last": True}
            return super()._fetch_json(url, headers)
    with pytest.raises(ErpError, match="formato"):
        ce.ler_recebimentos(Torta({}), [PAR_A], HOJE)


def test_recebimento_le_o_cliente_aninhado_e_o_id_do_cliente():
    r = ca.recebimento_do_erp(_item("r1", cliente=None, customer={"id": "c-9", "name": ALFA}))
    assert r.cliente == ALFA and r.cliente_id == "c-9"
    r = ca.recebimento_do_erp(_item("r1", cliente="", customerId="c-7"))
    assert r.cliente == "" and r.cliente_id == "c-7" and r.cliente_cadastro == ""
    r = ca.recebimento_do_erp(_item("r1", cliente="", customerId="c-7",
                                    **{ce.CHAVE_CLIENTE_DO_CADASTRO: BETA}))
    assert r.cliente_cadastro == BETA


def test_cliente_vazio_com_id_do_cadastro_e_identificado_pelo_nome_completo():
    r = replace(ca.recebimento_do_erp(_item("r1", cliente="")), cliente_id="c-2",
                cliente_cadastro=BETA)
    dono, motivo = ca.identificar_aportador(_conta2(), r)
    assert dono.nome_erp == BETA and motivo == ""
    ap = ca.apurar(_conta2(), [r], [], HOJE)
    assert [(l.nome, l.do_erp) for l in ap.linhas] == [(ALFA, Decimal("0.00")),
                                                       (BETA, Decimal("100.00"))]
    assert ap.sem_dono == []


def test_cadastro_com_primeiro_nome_ou_de_quem_nao_e_aportador_vai_para_sem_dono():
    base = ca.recebimento_do_erp(_item("r1", cliente=""))
    for nome in ("FULANO", "FULANO ALFA", "SICRANO DE TAL"):
        dono, motivo = ca.identificar_aportador(_conta2(), replace(base, cliente_cadastro=nome))
        assert dono is None and "não é aportador desta conta" in motivo and "cadastro" in motivo


def test_cliente_vazio_sem_cadastro_continua_sem_dono():
    r = replace(ca.recebimento_do_erp(_item("r1", cliente="")), cliente_id="c-2")
    dono, motivo = ca.identificar_aportador(_conta2(), r)
    assert dono is None and "sem Cliente" in motivo


def test_cliente_e_cadastro_divergentes_vao_para_sem_dono():
    r = replace(ca.recebimento_do_erp(_item("r1", cliente=ALFA)), cliente_cadastro=BETA)
    dono, motivo = ca.identificar_aportador(_conta2(), r)
    assert dono is None and "diverge" in motivo
    r = replace(r, cliente_cadastro="fulano  alfa da silva")     # mesmo nome, outra grafia
    assert ca.identificar_aportador(_conta2(), r)[0].nome_erp == ALFA


def test_descricao_e_centro_com_o_nome_completo_nunca_identificam():
    r = replace(ca.recebimento_do_erp(_item("r1", cliente="")), descricao=f"APORTE {ALFA}",
                centro=ALFA, cliente_id="c-1")
    assert ca.identificar_aportador(_conta2(), r)[0] is None


def test_ler_recebimentos_resolve_o_id_do_cliente_vazio_pelo_cadastro_de_contatos():
    contatos = [{"id": "c-0", "name": "OUTRO CONTATO"}, {"id": "c-1", "name": ALFA},
                {"id": "c-2", "name": BETA}]
    itens = [_item("r1", cliente="", customer={"id": "c-2", "name": ""}),
             _item("r2", cliente=ALFA, customerId="c-1"),
             _item("r3", cliente="", customerId="c-desconhecido")]
    api = ApiComContatos({("id-a", "n-cap"): itens}, contatos)
    crus = ce.ler_recebimentos(api, [PAR_A], HOJE)
    lidos = crus["CONTA A - BANCO"]["Aporte de Capital"]
    assert lidos[0][ce.CHAVE_CLIENTE_DO_CADASTRO] == BETA
    assert lidos[0]["customerName"] == ""                       # o cru não é reescrito
    assert ce.CHAVE_CLIENTE_DO_CADASTRO not in lidos[1]         # tinha nome: não consulta
    assert ce.CHAVE_CLIENTE_DO_CADASTRO not in lidos[2]         # id fora do cadastro
    assert itens[0].get(ce.CHAVE_CLIENTE_DO_CADASTRO) is None   # o dado do dublê não muda
    contatos_urls = [u for u in api.urls if "contacts/participants" in u]
    assert len(contatos_urls) == 2                              # paginou até hasNextPage falso
    aps = ca.apurar_tudo([_conta2()], {}, crus, {}, HOJE)
    assert [(l.nome, l.do_erp) for l in aps[0].linhas] == [(ALFA, Decimal("100.00")),
                                                           (BETA, Decimal("100.00"))]
    assert [s.recebimento.id for s in aps[0].sem_dono] == ["r3"]


def test_sem_cliente_vazio_o_cadastro_de_contatos_nem_e_lido():
    api = ApiComContatos({("id-a", "n-cap"): [_item("r1", customerId="c-1")]}, [])
    ce.ler_recebimentos(api, [PAR_A], HOJE)
    assert not any("contacts" in u for u in api.urls)


def test_id_repetido_no_cadastro_com_nomes_diferentes_nao_resolve():
    contatos = [{"id": "c-1", "name": ALFA}, {"id": "c-1", "name": BETA}]
    api = ApiComContatos({("id-a", "n-cap"): [_item("r1", cliente="", customerId="c-1")]},
                         contatos)
    crus = ce.ler_recebimentos(api, [PAR_A], HOJE)
    assert ce.CHAVE_CLIENTE_DO_CADASTRO not in crus["CONTA A - BANCO"]["Aporte de Capital"][0]


def test_cadastro_de_contatos_que_falha_deixa_sem_dono_e_avisa():
    avisos = []
    api = ApiComContatos({("id-a", "n-cap"): [_item("r1", cliente="", customerId="c-1")]},
                         [{"id": "c-1", "name": ALFA}], erro_contatos=500)
    crus = ce.ler_recebimentos(api, [PAR_A], HOJE, log=avisos.append)
    assert ce.CHAVE_CLIENTE_DO_CADASTRO not in crus["CONTA A - BANCO"]["Aporte de Capital"][0]
    assert any("500" in a and "sem dono" in a for a in avisos)
    aps = ca.apurar_tudo([_conta2()], {}, crus, {}, HOJE)
    assert [s.recebimento.id for s in aps[0].sem_dono] == ["r1"]


def test_cliente_vazio_sem_id_avisa_em_uma_linha_curta():
    avisos = []
    api = ApiComContatos({("id-a", "n-cap"): [_item("r1", cliente="", description="X")]}, [])
    ce.ler_recebimentos(api, [PAR_A], HOJE, log=avisos.append)
    assert not any("contacts" in u for u in api.urls)
    aviso = [a for a in avisos if "sem Cliente" in a]
    assert aviso and "1 recebimento(s) sem Cliente" in aviso[0]
    assert "customerName" not in aviso[0] and "description" not in aviso[0]
    assert "2026-10-22" not in aviso[0]                         # só nomes, nunca valores


def test_conta_que_nao_foi_lida_nao_vira_zero_aportado():
    aps = ca.apurar_tudo([_conta()], {}, {}, {}, HOJE)
    assert "não foram lidos" in aps[0].erro and aps[0].linhas == []


@pytest.mark.parametrize("corpo", [{"last": True}, {"data": [], "last": True}, [], None])
def test_resposta_sem_content_em_lista_nao_vira_nenhum_aporte(corpo):
    class SemContent(Api):
        def _fetch_json(self, url, headers):
            if "receipt-installments" in url:
                return corpo
            return super()._fetch_json(url, headers)
    with pytest.raises(ErpError, match="formato"):
        ce.ler_recebimentos(SemContent({}), [PAR_A], HOJE)
