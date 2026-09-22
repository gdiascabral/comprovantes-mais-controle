# -*- coding: utf-8 -*-
"""A gravação no ERP. Ids e nomes INVENTADOS: o repositório é público.

O transporte falso CONSOME o corpo que recebe, e não só devolve resposta:
dublê que não consome a entrada muda o transporte e produz teste que falha
sozinho de vez em quando.
"""
import json
from datetime import date
from decimal import Decimal

from guias import lancar as mod
from guias.modelos import (ALTERADO, ANEXO_PENDENTE, CRIADO, DIVERGE, ERRO,
                           Decisao, Guia)


class _Fila:
    """Respostas em sequência para a MESMA chamada (o GET do título antes e
    depois do PUT).

    Uma classe própria, e não "lista = fila": a listagem de prova do anexo É
    uma lista legítima, e tratá-la como fila devolvia o primeiro item em vez da
    lista inteira — foi o que derrubou três testes.
    """

    def __init__(self, *respostas):
        self.respostas = list(respostas)

    def proxima(self):
        # A última fica, para chamadas extras não estourarem.
        return (self.respostas.pop(0) if len(self.respostas) > 1
                else self.respostas[0])


class _Transporte:
    """GET/POST/PUT do ERP, do tamanho que `lancar` usa."""

    def __init__(self, respostas):
        self.respostas = respostas          # {(metodo, fragmento): resposta}
        self.chamadas = []

    def _achar(self, metodo, url):
        for (m, fragmento), resposta in self.respostas.items():
            if m == metodo and fragmento in url:
                return resposta
        raise AssertionError(f"chamada não prevista: {metodo} {url}")

    def buscar(self, url):
        self.chamadas.append(("GET", url, None))
        resposta = self._achar("GET", url)
        return resposta.proxima() if isinstance(resposta, _Fila) else resposta

    def postar(self, url, corpo):
        # consome de verdade: um corpo que não serializa é erro aqui, e não
        # três camadas adiante
        self.chamadas.append(("POST", url, json.loads(json.dumps(corpo))))
        return self._achar("POST", url)

    def trocar(self, url, corpo):
        self.chamadas.append(("PUT", url, json.loads(json.dumps(corpo))))
        return self._achar("PUT", url)

    def subir(self, url, dados, content_type="application/pdf"):
        self.chamadas.append(("PUT-S3", url, len(dados)))
        return self._achar("PUT-S3", url)

    def cabecalho(self, nome):
        return "user-1111" if nome == "user-id" else None


def _decisao(tmp_path, **campos):
    pdf = tmp_path / "guia.pdf"
    pdf.write_bytes(b"%PDF-1.4 fingido")
    guia = Guia(vip_id="701", empresa="EMPRESA UM", desc="HONORARIO",
                anx_id="111", competencia="2026-09", pdf=pdf,
                valor=Decimal("641.31"), vencimento=date(2026, 9, 12),
                documento="DOC-1")
    base = dict(guia=guia, acao="alterar", tipo="honorario",
                categoria="Honorários", trade_payable_id="tp-1",
                parcela_id="par-1")
    base.update(campos)
    return Decisao(**base)


TITULO = {"id": "tp-1", "documentNumber": "ANTIGO", "value": 620.0,
          "category": {"id": "cat-velha", "name": "Outras Despesas"},
          "recurring": {"plannedDate": "2026-09-12"},
          "costCentreDetails": [{"value": 620.0, "percentage": 100,
                                 "work": {"id": "obra-9", "name": "OBRA X"}}],
          "account": {"id": "conta-3", "name": "CONTA X"},
          "installments": [{"id": "par-1", "plannedDate": "2026-09-12",
                            "plannedValue": 620.0}]}


def _gravado(valor=641.31, doc="DOC-1", cat="Honorários"):
    depois = json.loads(json.dumps(TITULO))
    depois["documentNumber"] = doc
    depois["value"] = valor
    depois["category"] = {"id": "cat-nova", "name": cat}
    depois["installments"][0]["plannedValue"] = valor
    return depois


class _Catalogos:
    def categoria(self, nome):
        return {"id": "cat-nova", "name": nome} if nome else None

    def participante(self, nome):
        return {"id": "part-1", "name": nome} if nome else None

    def condicao_de_pagamento(self, tipo="IN_CASH"):
        return {"id": f"cond-{tipo}", "type": tipo}


REFERENCIA = {"account": {"id": "conta-3", "name": "CONTA X"},
              "paymentMethod": {"id": "forma-1", "name": "FORMA X"}}


#: O nome que `_fechar` calcula para a `_decisao(tmp_path)` PADRÃO (desc
#: "HONORARIO", competência "2026-09"). Desde o achado I3 a prova do anexo
#: exige o NOME exato na listagem, e não só uma lista não vazia — um dublê que
#: devolvesse qualquer nome (como o antigo "guia.pdf") passaria pela prova
#: errada.
ANEXO_OK = [{"filename": "HONORARIO 2026-09.pdf"}]
BATCH = {"attachmentsItem": [{"url": "https://s3.exemplo.invalido/assinada"}]}


def test_alterar_grava_a_categoria_especifica_e_so_esta_parcela(tmp_path):
    # Cópia: `alterar` muta o dicionário do GET em memória antes do PUT, e
    # TITULO é uma fixture do MÓDULO compartilhada por vários testes — sem a
    # cópia, o primeiro teste a rodar "gastaria" o TITULO original para todos
    # os que vierem depois (ver test_alterar_nao_toca_na_descricao_nem_na_conta,
    # que já faz essa cópia).
    t = _Transporte({("GET", "/trade-payables/tp-1"):
                     _Fila(json.loads(json.dumps(TITULO)), _gravado()),
                     ("PUT", "/trade-payables/tp-1"): {"id": "tp-1"},
                     ("POST", "/attachments/v2/batch"): BATCH,
                     ("PUT-S3", "s3.exemplo"): {"status": 200},
                     ("GET", "/attachments/v2?"): ANEXO_OK})

    r = mod.alterar(t, _decisao(tmp_path), _Catalogos(),
                    pasta_backup=tmp_path / "bk")

    assert r.estado == ALTERADO
    put = [c for c in t.chamadas if c[0] == "PUT"][0]
    assert "updateNext=false" in put[1]
    # O ERP casa a categoria pelo ID; mandar só o nome grava a categoria velha
    # em silêncio, que é justamente o que a recorrência já trazia errada.
    assert put[2]["category"]["id"] == "cat-nova"
    assert put[2]["category"]["name"] == "Honorários"
    assert put[2]["documentNumber"] == "DOC-1"
    assert put[2]["installments"][0]["plannedValue"] == 641.31
    assert put[2]["costCentreDetails"][0]["value"] == 641.31


def test_nome_do_anexo_nao_leva_separador_de_caminho(tmp_path):
    """A descrição do portal traz competência com barra, e barra em nome de
    objeto vira caminho no armazenamento."""
    assert "/" not in mod._nome_de_arquivo("HONORARIO 09/2026")
    assert chr(92) not in mod._nome_de_arquivo(f"INSS{chr(92)}IRRF")
    assert mod._nome_de_arquivo("HONORARIO 09/2026") == "HONORARIO 09-2026"


def test_nome_do_anexo_no_batch_de_alterar_nao_leva_barra(tmp_path):
    """Prova o caminho inteiro: uma descrição com barra de verdade
    ("HONORARIO 09/2026", como o portal do escritório manda) não pode chegar
    ao POST do batch com separador de caminho no nome do arquivo."""
    decisao = _decisao(tmp_path)
    decisao.guia.desc = "HONORARIO 09/2026"
    t = _Transporte({("GET", "/trade-payables/tp-1"):
                     _Fila(json.loads(json.dumps(TITULO)), _gravado()),
                     ("PUT", "/trade-payables/tp-1"): {"id": "tp-1"},
                     ("POST", "/attachments/v2/batch"): BATCH,
                     ("PUT-S3", "s3.exemplo"): {"status": 200},
                     # Nome diferente do ANEXO_OK padrão: o desc desta guia
                     # tem a barra que o teste existe para provar sem
                     # separador de caminho.
                     ("GET", "/attachments/v2?"):
                     [{"filename": "HONORARIO 09-2026 2026-09.pdf"}]})

    r = mod.alterar(t, decisao, _Catalogos(), pasta_backup=tmp_path / "bk")

    assert r.estado == ALTERADO
    batch = [c for c in t.chamadas if c[0] == "POST"][0][2]
    nome = batch["attachmentsItem"][0]["name"]
    assert "/" not in nome
    assert chr(92) not in nome


def test_alterar_nao_toca_na_descricao_nem_na_conta(tmp_path):
    """A conta vem da obra e a equipe nunca mexe nela; a descrição fica como
    está (decisões do dono)."""
    titulo = json.loads(json.dumps(TITULO))
    titulo["description"] = "DESCRICAO QUE JA ESTAVA LA"
    depois = _gravado()
    depois["description"] = "DESCRICAO QUE JA ESTAVA LA"
    t = _Transporte({("GET", "/trade-payables/tp-1"): _Fila(titulo, depois),
                     ("PUT", "/trade-payables/tp-1"): {"id": "tp-1"},
                     ("POST", "/attachments/v2/batch"): BATCH,
                     ("PUT-S3", "s3.exemplo"): {"status": 200},
                     ("GET", "/attachments/v2?"): ANEXO_OK})

    mod.alterar(t, _decisao(tmp_path), _Catalogos(),
                pasta_backup=tmp_path / "bk")

    put = [c for c in t.chamadas if c[0] == "PUT"][0]
    assert put[2]["description"] == "DESCRICAO QUE JA ESTAVA LA"
    assert put[2]["account"]["id"] == "conta-3"


def test_alterar_guarda_o_original_antes_do_put(tmp_path):
    bk = tmp_path / "bk"
    # Cópia: mesmo motivo do teste anterior — TITULO é compartilhado pelo
    # módulo, e este teste em especial confere o CONTEÚDO do backup, então é
    # o mais sensível a uma cópia esquecida (o valor "original" salvo seria o
    # já mutado por outro teste, não o 620.0 de verdade).
    t = _Transporte({("GET", "/trade-payables/tp-1"):
                     _Fila(json.loads(json.dumps(TITULO)), _gravado()),
                     ("PUT", "/trade-payables/tp-1"): {"id": "tp-1"},
                     ("POST", "/attachments/v2/batch"): BATCH,
                     ("PUT-S3", "s3.exemplo"): {"status": 200},
                     ("GET", "/attachments/v2?"): ANEXO_OK})

    mod.alterar(t, _decisao(tmp_path), _Catalogos(), pasta_backup=bk)

    salvos = list(bk.glob("*.json"))
    assert len(salvos) == 1
    assert json.loads(salvos[0].read_text(encoding="utf-8"))["value"] == 620.0


def test_parcela_com_baixa_nao_e_tocada(tmp_path):
    titulo = json.loads(json.dumps(TITULO))
    titulo["installments"][0]["paids"] = [{"id": "pago-1"}]
    t = _Transporte({("GET", "/trade-payables/tp-1"): titulo})

    r = mod.alterar(t, _decisao(tmp_path), _Catalogos(),
                    pasta_backup=tmp_path / "bk")

    assert r.estado == ERRO
    assert "baixa" in r.motivo
    assert not [c for c in t.chamadas if c[0] == "PUT"]


def test_releitura_que_nao_bate_vira_diverge(tmp_path):
    """Gravou, mas não como pedido. Não é erro e não é feito."""
    # Cópia: mesmo motivo dos testes de ALTERAR acima.
    t = _Transporte({("GET", "/trade-payables/tp-1"):
                     _Fila(json.loads(json.dumps(TITULO)), _gravado(valor=1.0)),
                     ("PUT", "/trade-payables/tp-1"): {"id": "tp-1"},
                     ("POST", "/attachments/v2/batch"): BATCH,
                     ("PUT-S3", "s3.exemplo"): {"status": 200},
                     ("GET", "/attachments/v2?"): ANEXO_OK})

    r = mod.alterar(t, _decisao(tmp_path), _Catalogos(),
                    pasta_backup=tmp_path / "bk")

    assert r.estado == DIVERGE


def test_erp_recusa_o_put_e_nada_e_anexado(tmp_path):
    # Cópia: mesmo motivo dos testes de ALTERAR acima (aqui o PUT é recusado
    # antes de qualquer releitura, mas `alterar` já mutou o dicionário do GET
    # em memória por cima do TITULO compartilhado antes de tentar o PUT).
    t = _Transporte({("GET", "/trade-payables/tp-1"): json.loads(json.dumps(TITULO)),
                     ("PUT", "/trade-payables/tp-1"): {"__erro": 400,
                                                       "__corpo": {"m": "não"}}})

    r = mod.alterar(t, _decisao(tmp_path), _Catalogos(),
                    pasta_backup=tmp_path / "bk")

    assert r.estado == ERRO
    assert "400" in r.motivo
    assert not [c for c in t.chamadas if c[0] == "POST"]


def test_criar_manda_a_conta_da_obra_e_nasce_a_pagar(tmp_path):
    decisao = _decisao(tmp_path, acao="criar", categoria="Taxa de abertura",
                       favorecido="FORNECEDOR FICTICIO",
                       descricao="DOC-1 - competencia 2026-09",
                       obra_id="obra-9", trade_payable_id="", parcela_id="")
    criado = {"id": "tp-novo", "documentNumber": "DOC-1",
              "account": {"id": "conta-3"}, "category": {"id": "cat-nova"},
              "costCentreDetails": [{"work": {"id": "obra-9"}}],
              "installments": [{"plannedDate": "2026-09-12",
                                "plannedValue": 641.31}]}
    t = _Transporte({("POST", "/trade-payables?"): {"id": "tp-novo"},
                     ("GET", "/trade-payables/tp-novo"): criado,
                     ("POST", "/attachments/v2/batch"): BATCH,
                     ("PUT-S3", "s3.exemplo"): {"status": 200},
                     ("GET", "/attachments/v2?"): ANEXO_OK})

    r = mod.criar(t, decisao, _Catalogos(), id_usuario="user-1111",
                  referencia=REFERENCIA, obra={"id": "obra-9", "name": "OBRA X"})

    assert r.estado == CRIADO
    corpo = [c for c in t.chamadas if c[0] == "POST" and "trade-payables" in c[1]][0][2]
    assert corpo["markedAsPaid"] is False
    assert corpo["account"]["id"] == "conta-3"
    assert corpo["paymentMethod"]["id"] == "forma-1"
    assert corpo["costCentreType"] == "WORK"
    assert corpo["costCentreDetails"][0]["work"]["id"] == "obra-9"
    assert corpo["whoPays"] == "CLIENT"
    assert corpo["paymentCondition"]["type"] == "IN_CASH"


def test_criar_sem_vencimento_no_pdf_usa_o_do_portal(tmp_path):
    """I7: uma ficha de arrecadação (FGTS, INSS/IRRF, contribuição) não traz
    vencimento no código de barras. Sem o `prz` do portal como segundo dado
    autoritativo, o título nasceria vencendo HOJE."""
    decisao = _decisao(tmp_path, acao="criar", obra_id="obra-9",
                       favorecido="FORNECEDOR FICTICIO", descricao="DOC-1",
                       trade_payable_id="", parcela_id="")
    decisao.guia.vencimento = None
    decisao.guia.vencimento_portal = date(2026, 9, 20)
    criado = {"id": "tp-novo", "documentNumber": "DOC-1",
              "account": {"id": "conta-3"},
              "costCentreDetails": [{"work": {"id": "obra-9"}}],
              "installments": [{"plannedDate": "2026-09-20",
                                "plannedValue": 641.31}]}
    t = _Transporte({("POST", "/trade-payables?"): {"id": "tp-novo"},
                     ("GET", "/trade-payables/tp-novo"): criado,
                     ("POST", "/attachments/v2/batch"): BATCH,
                     ("PUT-S3", "s3.exemplo"): {"status": 200},
                     ("GET", "/attachments/v2?"): ANEXO_OK})

    mod.criar(t, decisao, _Catalogos(), id_usuario="user-1111",
              referencia=REFERENCIA, obra={"id": "obra-9"})

    corpo = [c for c in t.chamadas
            if c[0] == "POST" and "trade-payables" in c[1]][0][2]
    assert corpo["referenceDate"] == "2026-09-20"
    assert corpo["installments"][0]["plannedDate"] == "2026-09-20"


def test_criar_sem_obra_no_catalogo_recusa_em_vez_de_criar_sem_centro_de_custo(
        tmp_path):
    """I8a: `_obra_do_erp` falha FECHADO (devolve `{}`) quando a obra não
    está no catálogo — o gatilho mais comum é a listagem de obras ter
    falhado em silêncio. Criar título sem centro de custo é pior que
    recusar."""
    decisao = _decisao(tmp_path, acao="criar", obra_id="obra-9",
                       favorecido="FORNECEDOR FICTICIO", descricao="DOC-1",
                       trade_payable_id="", parcela_id="")
    t = _Transporte({})

    r = mod.criar(t, decisao, _Catalogos(), id_usuario="user-1111",
                  referencia=REFERENCIA, obra={})

    assert r.estado == ERRO
    assert "obra" in r.motivo.lower()
    assert t.chamadas == []


def test_criar_com_obra_diferente_na_releitura_vira_diverge(tmp_path):
    """I8b: a conferência da criação tem de comparar também obra e
    categoria — não só parcelas, conta e documento, como o spec exige."""
    decisao = _decisao(tmp_path, acao="criar", obra_id="obra-9",
                       favorecido="FORNECEDOR FICTICIO", descricao="DOC-1",
                       trade_payable_id="", parcela_id="")
    criado = {"id": "tp-novo", "documentNumber": "DOC-1",
              "account": {"id": "conta-3"}, "category": {"id": "cat-nova"},
              "costCentreDetails": [{"work": {"id": "obra-ERRADA"}}],
              "installments": [{"plannedDate": "2026-09-12",
                                "plannedValue": 641.31}]}
    t = _Transporte({("POST", "/trade-payables?"): {"id": "tp-novo"},
                     ("GET", "/trade-payables/tp-novo"): criado,
                     ("POST", "/attachments/v2/batch"): BATCH,
                     ("PUT-S3", "s3.exemplo"): {"status": 200},
                     ("GET", "/attachments/v2?"): ANEXO_OK})

    r = mod.criar(t, decisao, _Catalogos(), id_usuario="user-1111",
                  referencia=REFERENCIA, obra={"id": "obra-9"})

    assert r.estado == DIVERGE


def test_criar_com_categoria_diferente_na_releitura_vira_diverge(tmp_path):
    """I8b, o outro campo: categoria errada na releitura também não pode
    passar como CRIADO."""
    decisao = _decisao(tmp_path, acao="criar", obra_id="obra-9",
                       favorecido="FORNECEDOR FICTICIO", descricao="DOC-1",
                       trade_payable_id="", parcela_id="")
    criado = {"id": "tp-novo", "documentNumber": "DOC-1",
              "account": {"id": "conta-3"}, "category": {"id": "cat-ERRADA"},
              "costCentreDetails": [{"work": {"id": "obra-9"}}],
              "installments": [{"plannedDate": "2026-09-12",
                                "plannedValue": 641.31}]}
    t = _Transporte({("POST", "/trade-payables?"): {"id": "tp-novo"},
                     ("GET", "/trade-payables/tp-novo"): criado,
                     ("POST", "/attachments/v2/batch"): BATCH,
                     ("PUT-S3", "s3.exemplo"): {"status": 200},
                     ("GET", "/attachments/v2?"): ANEXO_OK})

    r = mod.criar(t, decisao, _Catalogos(), id_usuario="user-1111",
                  referencia=REFERENCIA, obra={"id": "obra-9"})

    assert r.estado == DIVERGE


def test_criar_sem_referencia_da_obra_nao_inventa_conta(tmp_path):
    """A conta vem da obra. Sem título de referência, o robô não escolhe uma:
    lançar na conta errada manda o pagamento sair do lugar errado."""
    decisao = _decisao(tmp_path, acao="criar", obra_id="obra-9",
                       descricao="DOC-1", favorecido="FORNECEDOR FICTICIO",
                       trade_payable_id="", parcela_id="")
    t = _Transporte({})

    r = mod.criar(t, decisao, _Catalogos(), id_usuario="user-1111",
                  referencia=None, obra={"id": "obra-9"})

    assert r.estado == ERRO
    assert "conta" in r.motivo.lower()
    assert t.chamadas == []


def test_criar_parcelado_manda_as_quatro_parcelas_mensais(tmp_path):
    decisao = _decisao(tmp_path, acao="criar", parcelas=4, obra_id="obra-9",
                       favorecido="FORNECEDOR FICTICIO",
                       descricao="DOC-1", trade_payable_id="", parcela_id="")
    criado = {"id": "tp-novo", "documentNumber": "DOC-1",
              "account": {"id": "conta-3"},
              "costCentreDetails": [{"work": {"id": "obra-9"}}],
              "installments": [{"plannedDate": d, "plannedValue": 160.33}
                               for d in ("2026-09-12", "2026-10-12",
                                         "2026-11-12", "2026-12-12")]}
    t = _Transporte({("POST", "/trade-payables?"): {"id": "tp-novo"},
                     ("GET", "/trade-payables/tp-novo"): criado,
                     ("POST", "/attachments/v2/batch"): BATCH,
                     ("PUT-S3", "s3.exemplo"): {"status": 200},
                     ("GET", "/attachments/v2?"): ANEXO_OK})

    mod.criar(t, decisao, _Catalogos(), id_usuario="user-1111",
              referencia=REFERENCIA, obra={"id": "obra-9"})

    corpo = [c for c in t.chamadas if c[0] == "POST" and "trade-payables" in c[1]][0][2]
    assert len(corpo["installments"]) == 4
    assert corpo["numberOfInstallments"] == 4
    assert corpo["numberOfFinancingInstallments"] == 4
    assert corpo["paymentCondition"]["type"] == "FINANCING"
    assert [i["plannedDate"] for i in corpo["installments"]] == [
        "2026-09-12", "2026-10-12", "2026-11-12", "2026-12-12"]


def test_parcelas_com_vencimento_em_31_prende_no_ultimo_dia_do_mes():
    """I4: dia 31 não existe em todo mês. Sem prender ao último dia, a 2ª
    parcela de um vencimento em 31/03 levantava ValueError e derrubava o
    resto da rodada, sem dizer quais linhas ficaram sem lançar."""
    parcelas = mod._parcelas_mensais(date(2026, 3, 31), 4, 400.00)

    assert [p["plannedDate"] for p in parcelas] == [
        "2026-03-31", "2026-04-30", "2026-05-31", "2026-06-30"]


def test_parcelado_a_ultima_parcela_fecha_o_total(tmp_path):
    """Três parcelas de R$ 10,00 não somam R$ 30,01 nem R$ 29,99: a última
    absorve o centavo, senão o título nasce com valor diferente da guia."""
    parcelas = mod._parcelas_mensais(date(2026, 9, 12), 3, 100.00)

    assert [p["plannedValue"] for p in parcelas] == [33.33, 33.33, 33.34]
    assert round(sum(p["plannedValue"] for p in parcelas), 2) == 100.00


def test_anexo_que_nao_aparece_na_listagem_vira_pendente(tmp_path):
    """Review Focus 5: título criado e PDF não subiu. "Feito" seria mentira, e
    repetir criaria um segundo título."""
    criado = {"id": "tp-novo", "documentNumber": "DOC-1",
              "account": {"id": "conta-3"},
              "costCentreDetails": [{"work": {"id": "obra-9"}}],
              "installments": [{"plannedDate": "2026-09-12",
                                "plannedValue": 641.31}]}
    t = _Transporte({("POST", "/trade-payables?"): {"id": "tp-novo"},
                     ("GET", "/trade-payables/tp-novo"): criado,
                     ("POST", "/attachments/v2/batch"): BATCH,
                     ("PUT-S3", "s3.exemplo"): {"status": 200},
                     ("GET", "/attachments/v2?"): []})

    decisao = _decisao(tmp_path, acao="criar", obra_id="obra-9",
                       favorecido="FORNECEDOR FICTICIO",
                       descricao="DOC-1", trade_payable_id="", parcela_id="")
    r = mod.criar(t, decisao, _Catalogos(), id_usuario="user-1111",
                  referencia=REFERENCIA, obra={"id": "obra-9"})

    assert r.estado == ANEXO_PENDENTE
    assert r.tpid == "tp-novo"


def test_anexo_com_nome_de_outro_mes_na_listagem_vira_pendente(tmp_path):
    """I3: o ALTERAR reusa o MESMO título todo mês, então a listagem do anexo
    nunca fica vazia a partir da segunda alteração — "não está vazia" prova o
    PDF do mês passado, não o de agora. A prova certa é o NOME deste arquivo
    estar na listagem."""
    t = _Transporte({("GET", "/trade-payables/tp-1"):
                     _Fila(json.loads(json.dumps(TITULO)), _gravado()),
                     ("PUT", "/trade-payables/tp-1"): {"id": "tp-1"},
                     ("POST", "/attachments/v2/batch"): BATCH,
                     ("PUT-S3", "s3.exemplo"): {"status": 200},
                     # A listagem não está vazia, mas é o PDF do mês passado.
                     ("GET", "/attachments/v2?"): [{"filename": "guia antiga.pdf"}]})

    r = mod.alterar(t, _decisao(tmp_path), _Catalogos(),
                    pasta_backup=tmp_path / "bk")

    assert r.estado == ANEXO_PENDENTE
    assert r.tpid == "tp-1"


def test_referencia_da_obra_sai_de_um_titulo_da_mesma_obra():
    """A conta não é escolhida: é a que o ERP põe depois da obra. O título que
    já existe naquela obra é quem sabe qual é — e a forma de pagamento junto,
    que também é cadastro de cada instalação e não literal no código."""
    parcelas = [{"tradePayableId": "tp-7",
                 "costCentreDetails": [{"work": {"id": "obra-9"}}]}]
    t = _Transporte({("GET", "/trade-payables/tp-7"): {
        "account": {"id": "conta-3", "name": "CONTA X"},
        "paymentMethod": {"id": "forma-1", "name": "FORMA X"},
        "costCentreDetails": [{"work": {"id": "obra-9"}}]}})

    referencia = mod.referencia_da_obra(t, "obra-9", parcelas)

    assert referencia["account"]["id"] == "conta-3"
    assert referencia["paymentMethod"]["id"] == "forma-1"


def test_referencia_da_obra_sem_titulo_na_obra_devolve_none():
    assert mod.referencia_da_obra(_Transporte({}), "obra-9", []) is None


def test_referencia_da_obra_ignora_titulo_de_outra_obra():
    """Buscar a conta na obra errada é o erro que passa despercebido: a conta
    existe, o lançamento é aceito, e o dinheiro sai do lugar errado."""
    parcelas = [{"tradePayableId": "tp-8",
                 "costCentreDetails": [{"work": {"id": "obra-OUTRA"}}]}]

    assert mod.referencia_da_obra(_Transporte({}), "obra-9", parcelas) is None
