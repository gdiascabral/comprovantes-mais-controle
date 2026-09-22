# -*- coding: utf-8 -*-
"""O livro do que cada rodada lançou. É uma das duas travas contra duplicar."""
import logging

from guias import registro as mod


def test_anotar_e_reconhecer_na_rodada_seguinte(tmp_path):
    caminho = tmp_path / "guias_lancadas.jsonl"
    r = mod.Registro.carregar(caminho)
    r.anotar(vip_id="701", anx_id="111", competencia="2026-09",
             acao="alterar", estado="alterado", tpid="tp-1", conferido=True)

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


def test_a_trava_nao_depende_do_tipo_da_chave(tmp_path):
    """Um lado número e o outro texto faria a trava falhar ABERTA, e a guia
    seria lançada de novo."""
    caminho = tmp_path / "guias_lancadas.jsonl"
    r = mod.Registro.carregar(caminho)
    r.anotar(vip_id=701, anx_id=111, competencia="2026-09",
             acao="criar", estado="criado", tpid="tp-7")

    outra = mod.Registro.carregar(caminho)

    assert outra.ja_feito("701", "111", "2026-09")["tpid"] == "tp-7"


def test_estado_desconhecido_avisa_em_vez_de_passar_calado(tmp_path, caplog):
    """A trava falha ABERTA para o que não reconhece: silêncio aqui é
    lançamento duplicado sem ninguém saber por quê.

    O handler do `caplog` é pendurado no logger NOMEADO porque `util.log` cria
    os loggers do projeto com `propagate = False`: sem isso a asserção sobre a
    mensagem passaria por construção, com o captador vendo nada.
    """
    caminho = tmp_path / "guias_lancadas.jsonl"
    caminho.write_text('{"vip_id": "701", "anx_id": "111", '
                       '"competencia": "2026-09", "estado": "inventado"}\n',
                       encoding="utf-8")
    logger = logging.getLogger("guias.registro")
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger="guias.registro"):
            r = mod.Registro.carregar(caminho)
    finally:
        logger.removeHandler(caplog.handler)

    assert r.ja_feito("701", "111", "2026-09") is None
    assert "inventado" in caplog.text
