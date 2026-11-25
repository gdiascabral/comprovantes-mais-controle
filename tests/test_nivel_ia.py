"""Nível da linha quando a prova de valor vem da leitura por IA (spec de
19/11/2026, parte 3, fase 1). Registros fictícios, sem rede."""
import pytest

from pagamentos_dia import leitura_ia as li
from pagamentos_dia import nivel


def _ia(estado=li.BATE, total="410.00", provas=("valor por extenso",), **k):
    base = {"estado": estado, "falhou": False, "provas": list(provas), "total_lido": total,
            "motivos": [], "tipo_papel": "recibo", "origem": "api", "endereco": "", "oc": "",
            "duvidas": []}
    base.update(k)
    return base


def _r(ia=None, **k):
    # Foto escrita à mão: sem texto no anexo, mas quem recebe provado por outro caminho.
    base = {"tipo": "Pix", "dados": "fulano@exemplo.com", "valor": 410.0, "status": "APTO",
            "conferencia": "valor/fornecedor ? (anexo sem texto) · CNPJ ✓", "id": "1",
            "fornecedor_no_anexo": False, "leitura_ia": ia}
    base.update(k)
    return base


def test_sem_ia_a_linha_continua_nao_li():
    n = nivel.nivel_da_linha(_r(None))
    assert n.nome == nivel.NAO_LI and "valor não conferido em documento nenhum" in n.motivos


@pytest.mark.parametrize("estado,provas,sufixo", [
    (li.BATE, ["valor por extenso"], "— bate (valor por extenso)"),
    (li.TOTAL_BATE_SOMA_NAO_FECHA, ["valor por extenso"],
     "— total bate, soma do papel não fecha (valor por extenso)"),
    (li.SEM_SEGUNDA_PROVA, [], "— sem segunda prova")])
def test_valor_lido_por_ia_nunca_passa_de_olhe(estado, provas, sufixo):
    n = nivel.nivel_da_linha(_r(_ia(estado, provas=provas)))
    assert n.nome == nivel.OLHE
    assert f"lido por IA: R$ 410,00 × lançamento R$ 410,00 {sufixo}" in n.motivos
    assert dict(n.conferido)["valor"] == nivel.BATE


def test_diverge_e_olhe_com_o_motivo_claro():
    n = nivel.nivel_da_linha(_r(_ia(li.DIVERGE, total="435.00", provas=[])))
    assert n.nome == nivel.OLHE
    assert "lido por IA: R$ 435,00 × lançamento R$ 410,00 — diverge" in n.motivos
    assert dict(n.conferido)["valor"] == nivel.DIVERGE and "valor diverge" in n.motivos


def test_falha_da_ia_e_nao_li():
    n = nivel.nivel_da_linha(_r({"estado": "IA não respondeu", "falhou": True,
                                 "motivos": ["IA não respondeu: prazo"]}))
    assert n.nome == nivel.NAO_LI and "IA não respondeu" in n.motivos


def test_ilegivel_e_nao_li():
    n = nivel.nivel_da_linha(_r(_ia(li.ILEGIVEL, total="", provas=[])))
    assert n.nome == nivel.NAO_LI
    assert "lido por IA: não conseguiu ler o documento" in n.motivos


def test_total_nao_lido_aparece_no_motivo():
    n = nivel.nivel_da_linha(_r(_ia(li.SEM_SEGUNDA_PROVA, total="", provas=["valor por extenso"])))
    assert any(m.startswith("lido por IA: total não lido × lançamento R$ 410,00") for m in n.motivos)


def test_ia_nao_prova_quem_recebe():
    n = nivel.nivel_da_linha(_r(_ia(), conferencia="valor/fornecedor ? (anexo sem texto)"))
    assert n.nome == nivel.NAO_LI and "quem recebe não conferido" in n.motivos


def test_titulo_parcelado_nao_usa_a_ia_como_prova_de_valor():
    n = nivel.nivel_da_linha(_r(_ia(), total_parcelas=3, parcela={"numero": 2, "total": 3}))
    assert dict(n.conferido)["valor"] == nivel.NAO_CONFERIDO and n.nome == nivel.NAO_LI


def test_diverge_vale_ate_em_parcelado():
    n = nivel.nivel_da_linha(_r(_ia(li.DIVERGE, total="435.00", provas=[]), total_parcelas=3,
                                parcela={"numero": 2, "total": 3}))
    assert dict(n.conferido)["valor"] == nivel.DIVERGE


def test_valor_ja_provado_pelo_texto_e_ia_que_diverge_vira_diverge():
    n = nivel.nivel_da_linha(_r(_ia(li.DIVERGE, total="435.00", provas=[]),
                                conferencia="valor ✓ · fornecedor ✓", fornecedor_no_anexo=True))
    assert n.nome == nivel.OLHE and dict(n.conferido)["valor"] == nivel.DIVERGE


def test_para_o_html_leva_a_etiqueta_da_ia():
    r = _r(_ia(oc="OC 6803 ✓"))
    e = nivel.para_o_html(nivel.nivel_da_linha(r), r)
    assert e["leitura_ia"]["titulo"].startswith("lido por IA: recibo · total R$ 410,00 · bate")
    assert "OC 6803 ✓" in e["leitura_ia"]["linhas"]
    assert nivel.para_o_html(nivel.nivel_da_linha(_r(None)), _r(None))["leitura_ia"] is None


def test_etiqueta_da_falha():
    e = nivel.etiqueta_da_ia({"leitura_ia": {"falhou": True, "motivos": ["IA não respondeu: x"]}})
    assert "não respondeu" in e["titulo"] and e["linhas"] == ["IA não respondeu: x"]
    assert nivel.etiqueta_da_ia({}) is None
