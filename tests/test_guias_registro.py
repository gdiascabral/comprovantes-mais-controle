# -*- coding: utf-8 -*-
"""O livro do que cada rodada lançou. É uma das duas travas contra duplicar."""
from guias import registro as mod


def test_anotar_e_reconhecer_na_rodada_seguinte(tmp_path):
    caminho = tmp_path / "guias_lancadas.jsonl"
    r = mod.Registro.carregar(caminho)
    r.anotar(vip_id="701", anx_id="111", competencia="2026-09",
             acao="alterar", tpid="tp-1", conferido=True)

    outra = mod.Registro.carregar(caminho)

    assert outra.ja_feito("701", "111", "2026-09")["tpid"] == "tp-1"
    assert outra.ja_feito("701", "111", "2026-10") is None
    assert outra.ja_feito("702", "111", "2026-09") is None


def test_linha_de_erro_nao_conta_como_feito(tmp_path):
    """Review Focus 5: a rodada caiu entre gravar e anexar. O que falhou tem
    de ser tentado de novo, e não pulado como se estivesse pronto."""
    caminho = tmp_path / "guias_lancadas.jsonl"
    r = mod.Registro.carregar(caminho)
    r.anotar(vip_id="701", anx_id="111", competencia="2026-09",
             acao="criar", estado="erro", motivo="o ERP recusou (HTTP 400)")

    assert mod.Registro.carregar(caminho).ja_feito("701", "111", "2026-09") is None


def test_anexo_pendente_conta_como_feito_para_nao_duplicar_o_titulo(tmp_path):
    """O título FOI criado. Repetir criaria um segundo — o que falta é o anexo,
    e isso a tela mostra como pendência, não como lançamento a refazer."""
    caminho = tmp_path / "guias_lancadas.jsonl"
    r = mod.Registro.carregar(caminho)
    r.anotar(vip_id="701", anx_id="111", competencia="2026-09",
             acao="criar", estado="anexo_pendente", tpid="tp-9")

    feito = mod.Registro.carregar(caminho).ja_feito("701", "111", "2026-09")
    assert feito["tpid"] == "tp-9"
    assert feito["estado"] == "anexo_pendente"


def test_arquivo_com_linha_corrompida_nao_derruba_a_leitura(tmp_path):
    caminho = tmp_path / "guias_lancadas.jsonl"
    caminho.write_text('{"vip_id": "701", "anx_id": "111", '
                       '"competencia": "2026-09", "estado": "alterado"}\n'
                       'isto nao e json\n', encoding="utf-8")

    r = mod.Registro.carregar(caminho)

    assert r.ja_feito("701", "111", "2026-09") is not None


def test_arquivo_ausente_comeca_vazio(tmp_path):
    r = mod.Registro.carregar(tmp_path / "nao-existe.jsonl")

    assert r.ja_feito("701", "111", "2026-09") is None
