"""O cliente da nuvem do dia, sem rede (dublê do `rest`, como em test_registro_nuvem)."""
from datetime import date

import pytest

from nuvem import pagamentos_do_dia as pdd
from nuvem import rest

DIA = date(2026, 10, 22)


class _RestFalso:
    def __init__(self):
        self.lidas, self.inseridas, self.respostas = [], [], {}
        self.recusar_lote = False

    def ler(self, tabela, _token, *, colunas="*", filtro=""):
        self.lidas.append((tabela, filtro))
        return self.respostas.get(tabela, [])

    def inserir(self, tabela, _token, linhas, *, devolver=True):
        if self.recusar_lote and len(linhas) > 1:
            raise rest.RecusadoPeloBanco("HTTP 409: duplicate key")
        if any(l.get("alvo") == "REPETIDO" for l in linhas):
            raise rest.RecusadoPeloBanco("HTTP 409: duplicate key")
        self.inseridas.append((tabela, linhas))
        return [{"id": i + 1, **l} for i, l in enumerate(linhas)]


@pytest.fixture
def falso(monkeypatch):
    f = _RestFalso()
    monkeypatch.setattr(pdd.rest, "ler", f.ler)
    monkeypatch.setattr(pdd.rest, "inserir", f.inserir)
    return f


def test_decisao_nao_manda_quem_nem_quem_nome(falso):
    linha = pdd.DiaNaNuvem("tok").registrar_decisao(
        DIA, alvo="L1", conta="CONTA EXEMPLO - SICOOB", acao="liberar", motivo="pago pelo app")
    tabela, enviadas = falso.inseridas[0]
    assert tabela == "pagamento_decisao"
    assert "quem" not in enviadas[0] and "quem_nome" not in enviadas[0]
    assert enviadas[0]["dia"] == "2026-10-22" and linha["id"] == 1


def test_nenhuma_tabela_recebe_quem_nem_quem_nome(falso):
    c = pdd.DiaNaNuvem("tok")
    c.registrar_a_mao(DIA, {"conta": "C", "valor": "10.00", "descricao": "abc",
                            "motivo": "xyz", "quem_nome": "Fulano", "quem": "x"})
    c.marcar_agendados(DIA, [{"alvo": "L9", "conta": "C", "valor": "1.00",
                              "quem_nome": "Fulano"}])
    c.responder(3, "pago")
    c.gravar_nome_curto("Conta Alfa - Banco", "Alfa")
    c.gravar_lista(DIA, [{"conta": "A", "ordinal": 1}], "texto")
    assert len(falso.inseridas) == 5
    for _tabela, linhas in falso.inseridas:
        assert all("quem" not in l and "quem_nome" not in l for l in linhas)


def test_a_mao_so_leva_as_colunas_da_tabela(falso):
    pdd.DiaNaNuvem("tok").registrar_a_mao(DIA, {
        "conta": "C", "valor": "10.00", "descricao": "abc", "motivo": "xyz",
        "tipo": "Transferência", "lixo": 1})
    enviada = falso.inseridas[0][1][0]
    assert "lixo" not in enviada and enviada["tipo"] == "Transferência"


def test_descricao_do_agendado_e_cortada_em_200(falso):
    pdd.DiaNaNuvem("tok").marcar_agendados(
        DIA, [{"alvo": "L1", "conta": "C", "valor": "10.00", "descricao": "x" * 350}])
    assert len(falso.inseridas[0][1][0]["descricao"]) == 200


def test_resposta_sem_a_linha_gravada_e_erro(falso, monkeypatch):
    monkeypatch.setattr(pdd.rest, "inserir", lambda *a, **k: [])
    with pytest.raises(pdd.NaoGravou):
        pdd.DiaNaNuvem("tok").responder(7, "pago")


def test_marcar_agendados_pula_os_ja_marcados_e_cai_no_um_a_um(falso):
    falso.respostas["pagamento_agendado"] = [{"alvo": "L1"}]
    falso.recusar_lote = True
    linhas = [{"alvo": a, "conta": "C", "valor": "10.00"} for a in ("L1", "L2", "REPETIDO")]
    gravadas, repetidas = pdd.DiaNaNuvem("tok").marcar_agendados(DIA, linhas)
    assert [g["alvo"] for g in gravadas] == ["L2"]
    assert sorted(r["alvo"] for r in repetidas) == ["L1", "REPETIDO"]


def test_respostas_em_blocos_de_cem(falso):
    pdd.DiaNaNuvem("tok").respostas(range(1, 251))
    filtros = [f for t, f in falso.lidas if t == "agendado_resposta"]
    assert len(filtros) == 3 and filtros[0].startswith("agendado_id=in.(1,2,")


def test_nome_curto_mais_recente_vale(falso):
    falso.respostas["lista_diretor_nome"] = [{"conta": "Conta Alfa - Banco", "nome_curto": "Alfa"},
                                             {"conta": "Conta Alfa - Banco", "nome_curto": "Alfa - Banco"}]
    assert pdd.DiaNaNuvem("tok").nomes_curtos() == {"Conta Alfa - Banco": "Alfa - Banco"}


def test_lista_anterior_e_a_do_dia_antes(falso):
    falso.respostas["lista_diretor"] = [{"dia": "2026-10-21", "ordem": [{"conta": "A", "ordinal": 1}]}]
    assert pdd.DiaNaNuvem("tok").lista_anterior(DIA) == [{"conta": "A", "ordinal": 1}]
    assert ("lista_diretor", "dia=lt.2026-10-22&order=dia.desc,id.desc&limit=1") in falso.lidas
