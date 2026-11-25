"""O nível no HTML das PJ (spec de 19/11/2026). Fictício."""
from pagamentos_dia import html_pagamentos as hp
from pagamentos_dia import nivel
from pagamentos_dia.relatorio import Resultado
from tests.test_html_pagamentos import _gravar, _json, _ler, _linha, _resultado


def _entradas(resultado):
    return [e for c in hp.contas_do_html_geral(resultado) for e in c["entries"]]


def test_toda_entrada_tem_nivel_e_o_bloqueio_nao_mudou():
    antes = {e["id"]: e["bloqueio"] for e in _entradas(_resultado())}
    for e in _entradas(_resultado()):
        assert e["nivel"] in (nivel.PODE_PAGAR, nivel.OLHE, nivel.NAO_LI)
        assert e["bloqueio"] == antes[e["id"]]


def test_linha_conferida_pode_pagar_e_a_sem_conferencia_nao_li():
    res = Resultado({"CONTA EXEMPLO": [
        _linha("FORNECEDOR UM", 10.0, "1", conferencia="valor ✓ · fornecedor ✓",
               fornecedor_no_anexo=True),
        _linha("FORNECEDOR DOIS", 20.0, "2", conferencia="(não cruzado)")]}, [])
    por_id = {e["id"]: e for e in _entradas(res)}
    assert por_id["1"]["nivel"] == nivel.PODE_PAGAR
    assert por_id["2"]["nivel"] == nivel.NAO_LI


def test_mesma_linha_digitavel_em_dois_lancamentos_desce_para_olhe():
    linha = "00190.00009 01234.567890 12345.678901 1 00000000000000"
    res = Resultado({"CONTA EXEMPLO": [
        _linha("FORNECEDOR UM", 10.0, "1", tipo="Boleto", dados=linha,
               conferencia="valor ✓ · fornecedor ✓", fornecedor_no_anexo=True),
        _linha("FORNECEDOR DOIS", 10.0, "2", tipo="Boleto", dados=linha,
               conferencia="valor ✓ · fornecedor ✓", fornecedor_no_anexo=True)]}, [])
    for e in _entradas(res):
        assert e["nivel"] == nivel.OLHE
        assert any("mesma linha digitável" in m for m in e["motivos"])


def test_parcela_vai_para_o_html():
    res = Resultado({"CONTA EXEMPLO": [
        _linha("FORNECEDOR UM", 10.0, "1", conferencia="valor ✓ · fornecedor ✓",
               parcela={"numero": 3, "total": 10}, obs_parcela="depois da medição")]}, [])
    (e,) = _entradas(res)
    assert e["parcela"] == "3 de 10" and e["obs_parcela"] == "depois da medição"
    # Pix parcelado: o anexo não prova o valor (pode ser o comprovante de
    # outra parcela), então é "Não li", com a observação nos motivos.
    assert e["nivel"] == nivel.NAO_LI
    assert "a parcela tem observação: leia antes de pagar" in e["motivos"]


def test_a_pagina_tem_os_contadores_e_a_etiqueta(tmp_path):
    g = _gravar(tmp_path)
    html = _ler(g.geral)
    assert 'id="niveis"' in html and "nivel-badge" in html
    dados = _json(html, "DATA")
    assert all("nivel" in e for c in dados["contas"] for e in c["entries"])


def test_leitura_por_ia_vai_para_a_entrada_e_nunca_pode_pagar():
    ia = {"estado": "bate", "falhou": False, "provas": ["valor por extenso"],
          "total_lido": "10.00", "motivos": [], "tipo_papel": "recibo", "origem": "api",
          "endereco": "", "oc": "OC 6803 ✓", "duvidas": []}
    res = Resultado({"CONTA EXEMPLO": [
        _linha("FORNECEDOR UM", 10.0, "1", conferencia="valor/fornecedor ? (anexo sem texto) · CNPJ ✓",
               leitura_ia=ia)]}, [])
    (e,) = _entradas(res)
    assert e["nivel"] == nivel.OLHE
    assert any(m.startswith("lido por IA: R$ 10,00 × lançamento R$ 10,00 — bate") for m in e["motivos"])
    assert e["leitura_ia"]["titulo"] == "lido por IA: recibo · total R$ 10,00 · bate"
    assert "OC 6803 ✓" in e["leitura_ia"]["linhas"]


def test_o_bloqueio_do_copiar_e_o_mesmo_com_ou_sem_ia():
    sem = Resultado({"CONTA EXEMPLO": [_linha("FORNECEDOR UM", 10.0, "1")]}, [])
    com = Resultado({"CONTA EXEMPLO": [_linha("FORNECEDOR UM", 10.0, "1", leitura_ia={
        "estado": "diverge", "falhou": False, "provas": [], "total_lido": "12.00",
        "motivos": [], "tipo_papel": "recibo", "origem": "api", "endereco": "", "oc": "",
        "duvidas": []})]}, [])
    assert _entradas(sem)[0]["bloqueio"] == _entradas(com)[0]["bloqueio"]


def test_o_modelo_do_html_desenha_a_etiqueta_da_ia():
    from pagamentos_dia import modelos_html
    fonte = "".join(str(getattr(modelos_html, n)) for n in dir(modelos_html) if n.isupper())
    assert "e.leitura_ia" in fonte and "ia-tag" in fonte
