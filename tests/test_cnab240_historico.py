"""Testes da memória das remessas — contador do NSA, histórico e de-para.

Rode com:  python -m pytest -q
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cnab240 import (  # noqa: E402
    ArquivoRemessa,
    Empresa,
    Favorecido,
    FormaLancamento,
    PagamentoTitulo,
    TransferenciaConta,
)
from cnab240.historico import (  # noqa: E402
    NSA_MAXIMO,
    Historico,
    HistoricoInvalido,
    Item,
    itens_de,
)

HOJE = _dt.date(2026, 8, 13)
BARRAS = "75691234500000150001234567890123456789012345"
OUTRO_BARRAS = "34191234500000297001234567890123456789012345"


def empresa(convenio: str = "123456") -> Empresa:
    return Empresa(
        nome="ACME COMERCIO E SERVICOS LTDA",
        documento="12.345.678/0001-95",
        convenio=convenio,
        agencia="4321",
        dv_agencia="9",
        conta="000000012345",
        dv_conta="4",
        dv_ag_conta="0",
    )


def favorecido() -> Favorecido:
    return Favorecido(
        nome="FORNECEDOR SA",
        documento="98.765.432/0001-98",
        banco="341",
        agencia="0910",
        conta="000000045678",
        dv_conta="1",
    )


def remessa_de_boleto(nsa: int, *, seu_numero: str = "260813-0001", barras: str = BARRAS,
                      valor: str = "1500.00", conv: str = "123456") -> ArquivoRemessa:
    arquivo = ArquivoRemessa(empresa(conv), nsa=nsa, data_geracao=HOJE)
    arquivo.novo_lote(
        "TITULOS_COBRANCA", forma_lancamento=FormaLancamento.TITULO_OUTROS_BANCOS
    ).adicionar(
        PagamentoTitulo(
            valor=Decimal(valor),
            data_pagamento=HOJE,
            seu_numero=seu_numero,
            codigo_barras=barras,
            nome_cedente="FORNECEDOR SA",
        )
    )
    return arquivo


def remessa_de_ted(nsa: int, *, seu_numero: str = "260813-0009") -> ArquivoRemessa:
    arquivo = ArquivoRemessa(empresa(), nsa=nsa, data_geracao=HOJE)
    arquivo.novo_lote("TED", forma_lancamento=FormaLancamento.TED_OUTRA_TITULARIDADE).adicionar(
        TransferenciaConta(
            valor=Decimal("840.00"),
            data_pagamento=HOJE,
            seu_numero=seu_numero,
            finalidade_ted="5",
            favorecido=favorecido(),
        )
    )
    return arquivo


@pytest.fixture()
def historico(tmp_path) -> Historico:
    return Historico(tmp_path / "remessas.json")


# -- contador ---------------------------------------------------------------


def test_convenio_novo_comeca_em_um(historico):
    assert historico.ultimo_nsa("123456") == 0
    assert historico.proximo_nsa("123456") == 1


def test_registrar_consome_o_numero(historico):
    historico.registrar(remessa_de_boleto(1))
    assert historico.ultimo_nsa("123456") == 1
    assert historico.proximo_nsa("123456") == 2


def test_proximo_nsa_nao_consome(historico):
    assert historico.proximo_nsa("123456") == 1
    assert historico.proximo_nsa("123456") == 1


def test_o_contador_e_por_convenio(historico):
    historico.registrar(remessa_de_boleto(1))
    historico.registrar(remessa_de_boleto(1, seu_numero="X-1", conv="2025"))
    assert historico.ultimo_nsa("123456") == 1
    assert historico.ultimo_nsa("2025") == 1
    assert historico.proximo_nsa("123456") == 2


def test_nsa_repetido_e_recusado(historico):
    historico.registrar(remessa_de_boleto(1))
    with pytest.raises(HistoricoInvalido, match="crescente"):
        historico.registrar(remessa_de_boleto(1, seu_numero="260813-0002",
                                              barras=OUTRO_BARRAS))


def test_nsa_que_anda_para_tras_e_recusado(historico):
    historico.registrar(remessa_de_boleto(7))
    with pytest.raises(HistoricoInvalido, match="crescente"):
        historico.registrar(remessa_de_boleto(5, seu_numero="260813-0002",
                                              barras=OUTRO_BARRAS))


def test_pular_numero_e_permitido(historico):
    """Furo na sequência é inofensivo; o manual só exige crescente."""
    historico.registrar(remessa_de_boleto(1))
    historico.registrar(remessa_de_boleto(50, seu_numero="260813-0002", barras=OUTRO_BARRAS))
    assert historico.ultimo_nsa("123456") == 50


def test_empresa_sem_convenio_nao_gera(historico):
    with pytest.raises(HistoricoInvalido, match="convênio vazio"):
        historico.proximo_nsa("")


def test_teto_de_seis_posicoes(historico):
    historico.ajustar_nsa("123456", NSA_MAXIMO, motivo="teste do teto")
    with pytest.raises(HistoricoInvalido, match="teto"):
        historico.proximo_nsa("123456")


# -- o campo editável -------------------------------------------------------


def test_ajuste_para_conta_que_ja_enviava_por_fora(historico):
    """O caso de começo de vida: o banco já viu arquivos até o 30."""
    historico.ajustar_nsa("123456", 30, motivo="conta ja enviava pelo SicoobNet")
    assert historico.proximo_nsa("123456") == 31


def test_ajuste_exige_motivo(historico):
    with pytest.raises(HistoricoInvalido, match="motivo"):
        historico.ajustar_nsa("123456", 10, motivo="   ")


def test_ajuste_fica_registrado(historico):
    historico.ajustar_nsa("123456", 30, motivo="migracao do sistema antigo")
    ajustes = historico.ajustes(convenio="123456")
    assert len(ajustes) == 1
    assert (ajustes[0].de, ajustes[0].para) == (0, 30)
    assert ajustes[0].motivo == "migracao do sistema antigo"


def test_ajuste_nao_pode_baixar_para_aquem_do_que_ja_saiu(historico):
    historico.registrar(remessa_de_boleto(9))
    with pytest.raises(HistoricoInvalido, match="repetir um número já enviado"):
        historico.ajustar_nsa("123456", 5, motivo="tentando voltar")


def test_ajuste_pode_recuar_ate_o_ultimo_gravado(historico):
    historico.registrar(remessa_de_boleto(9))
    historico.ajustar_nsa("123456", 9, motivo="cancelando um pulo dado a mais")
    assert historico.proximo_nsa("123456") == 10


# -- descarte ---------------------------------------------------------------


def test_descartar_a_ultima_devolve_o_numero(historico):
    historico.registrar(remessa_de_boleto(1))
    historico.descartar("123456", 1, motivo="faltou um pagamento, refiz")
    assert historico.ultimo_nsa("123456") == 0
    assert historico.proximo_nsa("123456") == 1


def test_descartar_uma_do_meio_mantem_o_furo(historico):
    historico.registrar(remessa_de_boleto(1))
    historico.registrar(remessa_de_boleto(2, seu_numero="260813-0002", barras=OUTRO_BARRAS))
    historico.descartar("123456", 1, motivo="essa nao foi ao banco")
    assert historico.ultimo_nsa("123456") == 2


def test_descarte_tira_a_remessa_das_consultas(historico):
    historico.registrar(remessa_de_boleto(1))
    assert historico.envio_de(BARRAS) is not None
    historico.descartar("123456", 1, motivo="nao enviada")
    assert historico.envio_de(BARRAS) is None


def test_descartar_remessa_que_nao_existe(historico):
    with pytest.raises(HistoricoInvalido, match="não há remessa"):
        historico.descartar("123456", 3, motivo="x")


# -- de-para e duplicidade --------------------------------------------------


def test_boleto_ja_enviado_e_reconhecido(historico):
    historico.registrar(remessa_de_boleto(1))
    achado = historico.envio_de(BARRAS)
    assert achado is not None
    remessa, item = achado
    assert remessa.nsa == 1
    assert item.valor == Decimal("1500.00")


def test_codigo_de_barras_compara_so_digitos(historico):
    historico.registrar(remessa_de_boleto(1))
    assert historico.envio_de(f"{BARRAS[:5]}.{BARRAS[5:]}") is not None


def test_boleto_diferente_nao_alarma(historico):
    historico.registrar(remessa_de_boleto(1))
    assert historico.envio_de(OUTRO_BARRAS) is None


def test_ted_nao_gera_identificador(historico):
    """Chave Pix e conta se repetem legitimamente — não viram 'duplicado'."""
    remessa = historico.registrar(remessa_de_ted(1))
    assert remessa.itens[0].identificador == ""


def test_lancamento_ja_enviado_e_reconhecido_por_referencia(historico):
    historico.registrar(remessa_de_ted(1), referencias={"260813-0009": "id-do-erp-123"})
    achado = historico.envio_da_referencia("id-do-erp-123")
    assert achado is not None
    assert achado[1].seu_numero == "260813-0009"


def test_referencia_ausente_fica_vazia_e_nao_casa(historico):
    historico.registrar(remessa_de_ted(1))
    assert historico.envio_da_referencia("") is None
    assert historico.remessas()[0].itens[0].referencia == ""


def test_seu_numero_leva_de_volta_ao_lancamento(historico):
    """O caminho que o arquivo de retorno percorre."""
    historico.registrar(remessa_de_boleto(1), referencias={"260813-0001": "id-do-erp-987"})
    achado = historico.item_por_seu_numero("260813-0001")
    assert achado is not None
    assert achado[1].referencia == "id-do-erp-987"


def test_seu_numero_repetido_entre_remessas_e_recusado(historico):
    historico.registrar(remessa_de_boleto(1))
    with pytest.raises(HistoricoInvalido, match="já usado"):
        historico.registrar(remessa_de_boleto(2, barras=OUTRO_BARRAS))


def test_seu_numero_repetido_dentro_da_remessa_e_recusado(historico):
    arquivo = remessa_de_boleto(1)
    arquivo.lotes[0].adicionar(
        PagamentoTitulo(
            valor=Decimal("10.00"),
            data_pagamento=HOJE,
            seu_numero="260813-0001",
            codigo_barras=OUTRO_BARRAS,
        )
    )
    with pytest.raises(HistoricoInvalido, match="repetido dentro da mesma remessa"):
        historico.registrar(arquivo)


def test_descarte_libera_o_seu_numero_para_a_segunda_tentativa(historico):
    historico.registrar(remessa_de_boleto(1))
    historico.descartar("123456", 1, motivo="arquivo nao enviado")
    historico.registrar(remessa_de_boleto(1))
    assert historico.remessas(estado="gerado")[0].nsa == 1


# -- o registro em si -------------------------------------------------------


def test_remessa_guarda_o_que_saiu(historico):
    arquivo = remessa_de_boleto(1)
    remessa = historico.registrar(arquivo, caminho_arquivo="C:/tmp/REM0001.REM")
    assert remessa.convenio == "123456"
    assert remessa.arquivo == "REM0001.REM"
    assert remessa.quantidade == 1
    assert remessa.total == Decimal("1500.00")
    assert remessa.estado == "gerado"
    assert len(remessa.sha256) == 64


def test_sha256_identifica_o_conteudo_enviado(historico):
    import hashlib

    arquivo = remessa_de_boleto(1)
    esperado = hashlib.sha256(arquivo.texto().encode("latin-1")).hexdigest()
    assert historico.registrar(arquivo).sha256 == esperado


def test_itens_saem_de_todos_os_lotes():
    arquivo = remessa_de_boleto(1)
    arquivo.novo_lote("TED", forma_lancamento=FormaLancamento.TED_OUTRA_TITULARIDADE).adicionar(
        TransferenciaConta(
            valor=Decimal("840.00"), data_pagamento=HOJE, seu_numero="260813-0002",
            finalidade_ted="5", favorecido=favorecido(),
        )
    )
    itens = itens_de(arquivo)
    assert [i.produto for i in itens] == ["TITULOS_COBRANCA", "TED"]
    assert [i.favorecido for i in itens] == ["FORNECEDOR SA", "FORNECEDOR SA"]


def test_marcar_anda_com_o_estado(historico):
    historico.registrar(remessa_de_boleto(1))
    historico.marcar("123456", 1, "enviado", observacao="subido no SicoobNet")
    assert historico.remessa("123456", 1).estado == "enviado"


def test_estado_invalido_e_recusado(historico):
    historico.registrar(remessa_de_boleto(1))
    with pytest.raises(HistoricoInvalido, match="não existe"):
        historico.marcar("123456", 1, "quase-enviado")


def test_listagem_vem_da_mais_recente(historico):
    historico.registrar(remessa_de_boleto(1), quando=_dt.datetime(2026, 8, 13, 9, 0))
    historico.registrar(
        remessa_de_boleto(2, seu_numero="260813-0002", barras=OUTRO_BARRAS),
        quando=_dt.datetime(2026, 8, 13, 15, 0),
    )
    assert [r.nsa for r in historico.remessas(convenio="123456")] == [2, 1]


# -- o arquivo em disco -----------------------------------------------------


def test_sobrevive_a_reabertura(tmp_path):
    caminho = tmp_path / "remessas.json"
    Historico(caminho).registrar(remessa_de_boleto(4))
    assert Historico(caminho).ultimo_nsa("123456") == 4


def test_grava_json_legivel_com_ajuda(tmp_path):
    caminho = tmp_path / "remessas.json"
    Historico(caminho).registrar(remessa_de_boleto(1))
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    assert dados["convenios"]["123456"]["ultimo_nsa"] == 1
    assert any("CRESCENTE" in linha for linha in dados["_ajuda"])


def test_valor_nao_passa_por_float(tmp_path):
    caminho = tmp_path / "remessas.json"
    Historico(caminho).registrar(remessa_de_boleto(1, valor="0.10"))
    assert Historico(caminho).remessas()[0].total == Decimal("0.10")


def test_arquivo_corrompido_nao_passa_batido(tmp_path):
    caminho = tmp_path / "remessas.json"
    caminho.write_text("{ isso nao e json", encoding="utf-8")
    with pytest.raises(HistoricoInvalido, match="não consegui ler"):
        Historico(caminho)


def test_instancia_velha_nao_atropela_a_nova(tmp_path):
    """Duas janelas abertas: a segunda grava, a primeira não pode repetir."""
    caminho = tmp_path / "remessas.json"
    primeira = Historico(caminho)
    segunda = Historico(caminho)
    segunda.registrar(remessa_de_boleto(1))
    with pytest.raises(HistoricoInvalido, match="crescente"):
        primeira.registrar(remessa_de_boleto(1, seu_numero="X-9", barras=OUTRO_BARRAS))


def test_trava_orfa_nao_prende_para_sempre(tmp_path):
    import os
    import time

    caminho = tmp_path / "remessas.json"
    trava = tmp_path / "remessas.json.lock"
    trava.write_text("")
    antigo = time.time() - 3600
    os.utime(trava, (antigo, antigo))
    Historico(caminho).registrar(remessa_de_boleto(1))
    assert not trava.exists()


def test_itens_avulsos_podem_ser_gravados(historico):
    """Quem monta o de-para fora do arquivo também consegue registrar."""
    arquivo = remessa_de_boleto(1)
    remessa = historico.registrar(
        arquivo,
        itens=[Item(seu_numero="A-1", valor=Decimal("1500.00"), referencia="erp-1")],
    )
    assert remessa.itens[0].referencia == "erp-1"
