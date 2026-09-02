"""Testes do gerador/validador/leitor CNAB 240 Sicoob.

Rode com:  python -m pytest -q
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from pathlib import Path

import pytest

from cnab240 import (
    ArquivoRemessa,
    DadosJ52,
    Empresa,
    Endereco,
    Favorecido,
    FormaIniciacaoPix,
    FormaLancamento,
    PagamentoConvenio,
    PagamentoFolha,
    PagamentoTitulo,
    PixQRCode,
    PixTransferencia,
    RemessaInvalida,
    TipoContaDestino,
    TipoServico,
    TransferenciaConta,
    TributoDARF,
    TributoDARFSimples,
    TributoGPS,
    ler_retorno,
    validar,
)
from cnab240 import spec
from cnab240.campos import fmt_alfa, fmt_num, sanitizar
from cnab240.validador import NIVEL_ARQUIVO

HOJE = _dt.date(2026, 8, 12)
CODIGO_BARRAS = "75691234500000150001234567890123456789012345"


def empresa() -> Empresa:
    return Empresa(
        nome="ACME COMERCIO E SERVICOS LTDA",
        documento="12.345.678/0001-95",
        convenio="123456",
        agencia="4321",
        dv_agencia="0",
        conta="000000123456",
        dv_conta="7",
        dv_ag_conta="8",
        endereco=Endereco(
            logradouro="AV PAULISTA", numero="1000", complemento="SALA 12",
            bairro="BELA VISTA", cidade="SAO PAULO", cep="01310-100", estado="SP",
        ),
    )


def favorecido(banco: str = "756") -> Favorecido:
    return Favorecido(
        nome="JOAO DA SILVA",
        documento="123.456.789-09",
        banco=banco,
        agencia="1234",
        dv_agencia="5",
        conta="000000987654",
        dv_conta="3",
        endereco=Endereco(
            logradouro="RUA DAS FLORES", numero="55", bairro="CENTRO",
            cidade="CAMPINAS", cep="13010-000", estado="SP",
        ),
    )


# --------------------------------------------------------------------------
# Spec
# --------------------------------------------------------------------------


def test_todos_os_layouts_de_registro_cobrem_240_posicoes():
    for chave, layout in spec.layouts().items():
        if "." in chave:  # sub-layouts são recortes, não registros
            continue
        assert layout.campos[0].de == 1, chave
        assert layout.campos[-1].ate == 240, chave
        for anterior, atual in zip(layout.campos, layout.campos[1:]):
            assert atual.de == anterior.ate + 1, f"{chave}: buraco entre {anterior} e {atual}"


def test_produtos_referenciam_layouts_existentes():
    for produto in spec.produtos()["produtos"]:
        spec.layout(produto["header_lote"])
        spec.layout(produto["trailer_lote"])


def test_trailer_de_tributos_difere_do_de_transferencia():
    # Regressão do erro mais comum: reaproveitar o trailer errado.
    tributos = spec.layout("trailer_lote_tributos")
    transferencia = spec.layout("trailer_lote_transferencia")
    assert tributos.campo("07.5").ate == 230
    assert transferencia.campo("07.5").ate == 59


def test_segmento_b_da_folha_difere_do_de_transferencia():
    folha = spec.layout("segmento_b_folha")
    transferencia = spec.layout("segmento_b_transferencia")
    assert folha.campo("09.3B").de == 33 and folha.campo("09.3B").ate == 62
    assert transferencia.campo("09.3B").de == 33 and transferencia.campo("09.3B").ate == 67


# --------------------------------------------------------------------------
# Formatação
# --------------------------------------------------------------------------


def test_alfa_remove_acento_e_nao_ascii():
    # Acento sai, travessão (não-ASCII) vira espaço, ASCII imprimível permanece.
    assert sanitizar("Ação & Cia — Ltda?") == "ACAO & CIA   LTDA?"
    assert fmt_alfa("José", 10) == "JOSE      "


def test_chave_pix_e_url_preservam_a_caixa():
    # Uppercase quebraria uma URL de QR Code dinâmico; o formatador respeita
    # os campos sensíveis a caixa (ver campos.CAMPOS_PRESERVAM_CASO).
    from cnab240.campos import formatar

    campo_url = spec.layout("segmento_j52_pix").campo("15.4.J52")
    assert formatar(campo_url, "https://Pix.Exemplo/QR").startswith("https://Pix.Exemplo/QR")
    campo_nome = spec.layout("segmento_j52_pix").campo("14.4.J52")
    assert formatar(campo_nome, "joão silva").startswith("JOAO SILVA")


def test_num_aplica_escala_decimal():
    assert fmt_num(Decimal("1234.56"), 15, 2) == "000000000123456"
    assert fmt_num(1500, 15, 2) == "000000000150000"
    assert fmt_num("00012345678909", 14, 0) == "00012345678909"


def test_num_rejeita_valor_que_nao_cabe():
    with pytest.raises(ValueError):
        fmt_num(Decimal("99999999999999999"), 15, 2)


def test_num_rejeita_texto():
    with pytest.raises(ValueError):
        fmt_num("ABC", 5, 0)


# --------------------------------------------------------------------------
# Remessa
# --------------------------------------------------------------------------


def gerar_transferencia() -> list[str]:
    arquivo = ArquivoRemessa(empresa(), nsa=1, data_geracao=HOJE, hora_geracao=_dt.time(10, 30))
    lote = arquivo.novo_lote(
        "TRANSFERENCIA_SICOOB", tipo_servico=TipoServico.PAGAMENTO_FORNECEDOR
    )
    lote.adicionar(
        TransferenciaConta(valor="1500.00", data_pagamento=HOJE, favorecido=favorecido(), seu_numero="NF001"),
        TransferenciaConta(valor=Decimal("250.75"), data_pagamento=HOJE, favorecido=favorecido()),
    )
    return arquivo.gerar()


def test_transferencia_gera_estrutura_correta():
    linhas = gerar_transferencia()
    assert [l[7] for l in linhas] == ["0", "1", "3", "3", "3", "3", "5", "9"]
    assert all(len(l) == 240 for l in linhas)
    assert all(l[:3] == "756" for l in linhas)
    assert [l[13] for l in linhas[2:6]] == ["A", "B", "A", "B"]


def test_transferencia_passa_no_validador():
    assert validar(gerar_transferencia()) == []


def test_totalizacoes_do_trailer():
    linhas = gerar_transferencia()
    trailer_lote, trailer_arquivo = linhas[-2], linhas[-1]
    assert int(trailer_lote[17:23]) == 6  # header + 4 detalhes + trailer
    assert Decimal(trailer_lote[23:41]) / 100 == Decimal("1750.75")
    assert int(trailer_arquivo[17:23]) == 1  # 1 lote
    assert int(trailer_arquivo[23:29]) == len(linhas)


def test_nsr_reinicia_a_cada_lote():
    arquivo = ArquivoRemessa(empresa(), nsa=1, data_geracao=HOJE)
    arquivo.novo_lote("TRANSFERENCIA_SICOOB").adicionar(
        TransferenciaConta(valor="10.00", data_pagamento=HOJE, favorecido=favorecido())
    )
    arquivo.novo_lote(
        "TED", forma_lancamento=FormaLancamento.TED_OUTRA_TITULARIDADE
    ).adicionar(
        TransferenciaConta(
            valor="20.00", data_pagamento=HOJE, favorecido=favorecido("341"), finalidade_ted="5"
        )
    )
    linhas = arquivo.gerar()
    detalhes = [l for l in linhas if l[7] == "3"]
    assert [int(l[8:13]) for l in detalhes] == [1, 2, 1, 2]
    assert [l[3:7] for l in detalhes] == ["0001", "0001", "0002", "0002"]
    assert validar(linhas) == []


def test_ted_grava_camara_e_finalidade():
    arquivo = ArquivoRemessa(empresa(), nsa=7, data_geracao=HOJE)
    arquivo.novo_lote("TED", forma_lancamento=FormaLancamento.TED_OUTRA_TITULARIDADE).adicionar(
        TransferenciaConta(
            valor="900.00", data_pagamento=HOJE, favorecido=favorecido("341"), finalidade_ted="5"
        )
    )
    segmento_a = [l for l in arquivo.gerar() if l[7] == "3" and l[13] == "A"][0]
    assert segmento_a[17:20] == "018"  # câmara TED
    assert segmento_a[20:23] == "341"  # banco do favorecido
    assert segmento_a[219:224] == "00005"  # finalidade da TED


def test_pix_transferencia_por_chave():
    arquivo = ArquivoRemessa(empresa(), nsa=2, data_geracao=HOJE)
    arquivo.novo_lote("PIX_TRANSFERENCIA").adicionar(
        PixTransferencia(
            valor="99.90",
            data_pagamento=HOJE,
            favorecido=favorecido(),
            forma_iniciacao=FormaIniciacaoPix.CHAVE_EMAIL,
            chave="joao@exemplo.com.br",
            tipo_conta_destino=TipoContaDestino.POUPANCA,
        )
    )
    linhas = arquivo.gerar()
    a = [l for l in linhas if l[13] == "A"][0]
    b = [l for l in linhas if l[13] == "B"][0]
    assert a[17:20] == "009"           # câmara Pix (SPI)
    assert a[177:215] == " " * 38      # G031: 38 brancos...
    assert a[215:217] == "03"          # ...e tipo da conta destino
    assert b[14:17] == "02 "           # forma de iniciação = email (Alfa, 3 pos.)
    assert b[127:146].strip() == "joao@exemplo.com.br"  # chave preserva a caixa
    assert validar(linhas) == []


def test_pix_por_cpf_cnpj_repete_a_chave_na_informacao_12():
    """O manual omite a forma 03 na descrição da Informação 12; o banco não.

    Deixar o campo em branco parecia certo (a chave já está em 07.3B/08.3B),
    mas o SicoobNet recusou o arquivo na validação de 13/08/2026 — erro
    estruturante, "campo Informação 12, possui valor inválido".
    """
    arquivo = ArquivoRemessa(empresa(), nsa=3, data_geracao=HOJE)
    arquivo.novo_lote("PIX_TRANSFERENCIA").adicionar(
        PixTransferencia(
            valor="10.00",
            data_pagamento=HOJE,
            favorecido=favorecido(),
            forma_iniciacao=FormaIniciacaoPix.CHAVE_CPF_CNPJ,
            chave="98.765.432/0001-98",
        )
    )
    linhas = arquivo.gerar()
    b = [l for l in linhas if l[13] == "B"][0]
    assert b[14:17] == "03 "
    assert b[127:226].strip() == "98765432000198"
    assert validar(linhas) == []


def test_pix_por_cpf_cnpj_sem_chave_usa_o_documento_do_favorecido():
    arquivo = ArquivoRemessa(empresa(), nsa=4, data_geracao=HOJE)
    arquivo.novo_lote("PIX_TRANSFERENCIA").adicionar(
        PixTransferencia(
            valor="10.00",
            data_pagamento=HOJE,
            favorecido=favorecido(),
            forma_iniciacao=FormaIniciacaoPix.CHAVE_CPF_CNPJ,
        )
    )
    b = [l for l in arquivo.gerar() if l[13] == "B"][0]
    assert b[127:226].strip() == "12345678909"   # o CPF do favorecido


def test_pix_exige_chave_quando_forma_e_por_chave():
    with pytest.raises(ValueError, match="exige a chave Pix"):
        PixTransferencia(
            valor="10", data_pagamento=HOJE, favorecido=favorecido(),
            forma_iniciacao=FormaIniciacaoPix.CHAVE_ALEATORIA,
        )


def test_titulo_gera_j_e_j52():
    arquivo = ArquivoRemessa(empresa(), nsa=3, data_geracao=HOJE)
    arquivo.novo_lote(
        "TITULOS_COBRANCA", forma_lancamento=FormaLancamento.TITULO_OUTROS_BANCOS
    ).adicionar(
        PagamentoTitulo(
            valor="320.00",
            data_pagamento=HOJE,
            codigo_barras=CODIGO_BARRAS,
            nome_cedente="FORNECEDOR SA",
            vencimento=HOJE,
            j52=DadosJ52(cedente_nome="FORNECEDOR SA", cedente_documento="98765432000198"),
        )
    )
    linhas = arquivo.gerar()
    detalhes = [l for l in linhas if l[7] == "3"]
    assert len(detalhes) == 2
    assert detalhes[0][17:61] == CODIGO_BARRAS
    assert detalhes[1][17:19] == "52"          # identificação do registro opcional
    assert linhas[1][13:16] == "040"           # versão do layout do lote
    assert validar(linhas) == []


def test_titulo_rejeita_linha_digitavel():
    with pytest.raises(ValueError, match="44 dígitos"):
        PagamentoTitulo(valor="10", data_pagamento=HOJE, codigo_barras="1" * 47)


def test_pix_qrcode_gera_j52_pix():
    arquivo = ArquivoRemessa(empresa(), nsa=4, data_geracao=HOJE)
    arquivo.novo_lote("PIX_QRCODE").adicionar(
        PixQRCode(
            valor="45.00",
            data_pagamento=HOJE,
            chave_pagamento="https://pix.exemplo.com/qr/abc123",
            txid="TXID0001234567890",
            favorecido=favorecido(),
        )
    )
    linhas = arquivo.gerar()
    j52 = [l for l in linhas if l[7] == "3"][1]
    assert j52[17:19] == "52"
    assert j52[131:210].strip() == "https://pix.exemplo.com/qr/abc123"
    assert j52[210:240].strip() == "TXID0001234567890"
    assert validar(linhas) == []


def test_pix_qrcode_exige_txid():
    with pytest.raises(ValueError, match="TXID"):
        PixQRCode(
            valor="1", data_pagamento=HOJE, chave_pagamento="https://x", txid="",
            favorecido=favorecido(),
        )


def test_convenio_com_codigo_de_barras():
    arquivo = ArquivoRemessa(empresa(), nsa=5, data_geracao=HOJE)
    arquivo.novo_lote("CONVENIOS_COM_CODIGO_BARRAS").adicionar(
        PagamentoConvenio(
            valor="187.43",
            data_pagamento=HOJE,
            codigo_barras="8" * 44,
            nome_concessionaria="CIA DE ENERGIA",
            vencimento=HOJE,
        )
    )
    linhas = arquivo.gerar()
    assert linhas[1][13:16] == "012"
    assert [l[13] for l in linhas if l[7] == "3"] == ["O"]
    assert validar(linhas) == []


def test_tributos_darf_gps_e_darf_simples():
    for pagamento, forma, esperado in [
        (
            TributoDARF(
                valor="500.00", data_pagamento=HOJE, nome_contribuinte="ACME LTDA",
                codigo_receita="0561", identificacao="12345678000195",
                periodo_apuracao=HOJE, valor_principal="500.00", vencimento=HOJE,
            ),
            FormaLancamento.DARF_NORMAL,
            "0561",
        ),
        (
            TributoGPS(
                valor="300.00", data_pagamento=HOJE, nome_contribuinte="ACME LTDA",
                codigo_receita="2100", identificacao="12345678000195",
                competencia=HOJE, valor_inss="300.00",
            ),
            FormaLancamento.GPS,
            "2100",
        ),
        (
            TributoDARFSimples(
                valor="120.00", data_pagamento=HOJE, nome_contribuinte="ACME LTDA",
                identificacao="12345678000195", periodo_apuracao=HOJE,
                receita_bruta="10000.00", percentual="5.00", valor_principal="120.00",
            ),
            FormaLancamento.DARF_SIMPLES,
            "6106",
        ),
    ]:
        arquivo = ArquivoRemessa(empresa(), nsa=6, data_geracao=HOJE)
        arquivo.novo_lote("TRIBUTOS_SEM_CODIGO_BARRAS", forma_lancamento=forma).adicionar(pagamento)
        linhas = arquivo.gerar()
        segmento_n = [l for l in linhas if l[7] == "3"][0]
        assert segmento_n[13] == "N"
        assert segmento_n[110:116].strip() == esperado
        assert validar(linhas) == [], f"{type(pagamento).__name__}: {validar(linhas)}"


def test_lote_de_tributo_nao_mistura_formas():
    arquivo = ArquivoRemessa(empresa(), nsa=6, data_geracao=HOJE)
    lote = arquivo.novo_lote(
        "TRIBUTOS_SEM_CODIGO_BARRAS", forma_lancamento=FormaLancamento.DARF_NORMAL
    )
    with pytest.raises(RemessaInvalida, match="um lote só pode conter um tipo"):
        lote.adicionar(
            TributoGPS(
                valor="1", data_pagamento=HOJE, identificacao="12345678000195",
                competencia=HOJE, valor_inss="1",
            )
        )


def test_folha_de_pagamento():
    arquivo = ArquivoRemessa(empresa(), nsa=8, data_geracao=HOJE)
    lote = arquivo.novo_lote("FOLHA_PAGAMENTO", mensagem="FOLHA AGOSTO 2026")
    lote.adicionar(
        PagamentoFolha(valor="3200.00", data_pagamento=HOJE, favorecido=favorecido())
    )
    linhas = arquivo.gerar()
    header_lote = linhas[1]
    assert header_lote[9:11] == "30"                       # tipo de serviço
    assert header_lote[11:13] == "01"                      # forma de lançamento
    assert header_lote[102:142].strip() == "FOLHA AGOSTO 2026"
    segmento_b = [l for l in linhas if l[13] == "B"][0]
    assert segmento_b[14:17] == "   "                      # folha: 15-17 em branco
    assert segmento_b[32:62].strip() == "RUA DAS FLORES"   # endereço explodido
    assert validar(linhas) == []


def test_folha_exige_nome_da_folha():
    arquivo = ArquivoRemessa(empresa(), nsa=9, data_geracao=HOJE)
    with pytest.raises(RemessaInvalida, match="nome da folha"):
        arquivo.novo_lote("FOLHA_PAGAMENTO")


def test_lote_recusa_pagamento_de_outro_produto():
    arquivo = ArquivoRemessa(empresa(), nsa=10, data_geracao=HOJE)
    lote = arquivo.novo_lote("TRANSFERENCIA_SICOOB")
    with pytest.raises(RemessaInvalida, match="aceita TransferenciaConta"):
        lote.adicionar(PagamentoTitulo(valor="1", data_pagamento=HOJE, codigo_barras=CODIGO_BARRAS))


def test_forma_de_lancamento_invalida_para_o_produto():
    arquivo = ArquivoRemessa(empresa(), nsa=11, data_geracao=HOJE)
    with pytest.raises(RemessaInvalida, match="não é válida"):
        arquivo.novo_lote("TITULOS_COBRANCA", forma_lancamento=FormaLancamento.GPS)


def test_arquivo_com_multiplos_produtos():
    arquivo = ArquivoRemessa(empresa(), nsa=12, data_geracao=HOJE)
    arquivo.novo_lote("TRANSFERENCIA_SICOOB").adicionar(
        TransferenciaConta(valor="10.00", data_pagamento=HOJE, favorecido=favorecido())
    )
    arquivo.novo_lote("PIX_TRANSFERENCIA").adicionar(
        PixTransferencia(
            valor="20.00", data_pagamento=HOJE, favorecido=favorecido(),
            forma_iniciacao=FormaIniciacaoPix.CHAVE_ALEATORIA,
            chave="0e8a2b1c-1111-2222-3333-444455556666",
        )
    )
    arquivo.novo_lote(
        "TITULOS_COBRANCA", forma_lancamento=FormaLancamento.TITULO_PROPRIO_BANCO
    ).adicionar(
        PagamentoTitulo(valor="30.00", data_pagamento=HOJE, codigo_barras=CODIGO_BARRAS)
    )
    linhas = arquivo.gerar()
    assert int(linhas[-1][17:23]) == 3
    assert [l[3:7] for l in linhas if l[7] == "1"] == ["0001", "0002", "0003"]
    assert validar(linhas) == []


def test_arquivo_sem_lote_falha():
    with pytest.raises(RemessaInvalida, match="sem lotes"):
        ArquivoRemessa(empresa(), nsa=1).gerar()


def test_salvar_grava_240_por_linha(tmp_path):
    arquivo = ArquivoRemessa(empresa(), nsa=1, data_geracao=HOJE)
    arquivo.novo_lote("TRANSFERENCIA_SICOOB").adicionar(
        TransferenciaConta(valor="10.00", data_pagamento=HOJE, favorecido=favorecido())
    )
    destino = arquivo.salvar(tmp_path / "REM.txt")
    # `open(newline="")` e não `Path.read_text(newline=...)`: o parâmetro só
    # existe no read_text a partir do 3.13, e o exe do app roda 3.11. Ler sem
    # ele traduziria o CRLF e o teste do tamanho da linha perderia o sentido.
    with open(destino, encoding="latin-1", newline="") as arq:
        bruto = arq.read()
    for linha in bruto.split("\r\n"):
        if linha:
            assert len(linha) == 240


def remessa_de_uma_linha() -> ArquivoRemessa:
    arquivo = ArquivoRemessa(empresa(), nsa=1, data_geracao=HOJE)
    arquivo.novo_lote("TRANSFERENCIA_SICOOB").adicionar(
        TransferenciaConta(valor="10.00", data_pagamento=HOJE, favorecido=favorecido())
    )
    return arquivo


def test_salvar_cria_a_pasta_que_ainda_nao_existe(tmp_path):
    # A pasta do dia/mês pode não existir. Falhar aqui gastaria o NSA sem
    # arquivo — furo no histórico que ninguém sabe explicar depois.
    destino = tmp_path / "2026" / "AGOSTO" / "REMESSAS" / "REM.txt"
    assert not destino.parent.exists()
    assert remessa_de_uma_linha().salvar(destino).exists()


def test_salvar_recusa_arquivo_que_o_banco_rejeitaria_inteiro(tmp_path):
    """O validador existia e era bom — só não era chamado na gravação."""
    arquivo = remessa_de_uma_linha()
    linhas = arquivo.gerar()
    linhas[2] = linhas[2][:239]  # registro com 239 posições: erro de ARQUIVO
    arquivo.gerar = lambda: linhas  # type: ignore[method-assign]

    destino = tmp_path / "REM.txt"
    with pytest.raises(RemessaInvalida, match="239 posições"):
        arquivo.salvar(destino)
    assert not destino.exists()  # e nada foi escrito pela metade


def test_salvar_sem_validar_e_a_saida_para_depurar(tmp_path):
    arquivo = remessa_de_uma_linha()
    linhas = arquivo.gerar()
    linhas[2] = linhas[2][:239]
    arquivo.gerar = lambda: linhas  # type: ignore[method-assign]
    assert arquivo.salvar(tmp_path / "REM.txt", validar_antes=False).exists()


# --------------------------------------------------------------------------
# Dinheiro: 2 casas ou recusa
# --------------------------------------------------------------------------


def test_valor_com_tres_casas_decimais_e_recusado():
    """Arredondar sozinho faria o trailer divergir e o banco recusaria tudo.

    Três parcelas de 33,3333 gravam três registros de 33,33 (99,99) debaixo de
    um trailer que declara 100,00 — e divergência de somatória derruba o
    ARQUIVO inteiro, não a linha. Como é dinheiro de outra pessoa, quem decide
    para onde vai o centavo é quem chama, não a biblioteca.
    """
    with pytest.raises(ValueError, match="mais de 2 casas decimais"):
        TransferenciaConta(
            valor=Decimal("33.3333"), data_pagamento=HOJE, favorecido=favorecido()
        )


def test_valor_com_duas_casas_ou_menos_passa():
    # Menos que duas casas é legítimo: 33,3 e 33 são exatos em centavos.
    for bruto, esperado in [
        (Decimal("33.33"), Decimal("33.33")),
        (Decimal("33.3"), Decimal("33.3")),
        (Decimal("33"), Decimal("33")),
        ("1500.00", Decimal("1500.00")),
        (1500, Decimal("1500")),
    ]:
        pagamento = TransferenciaConta(
            valor=bruto, data_pagamento=HOJE, favorecido=favorecido()
        )
        assert pagamento.valor == esperado


def test_tres_parcelas_de_um_terco_nao_chegam_a_gerar_arquivo():
    # O caso real: 100,00 dividido em três. O erro aparece no primeiro
    # pagamento, e não num trailer divergente descoberto pelo banco.
    arquivo = ArquivoRemessa(empresa(), nsa=1, data_geracao=HOJE)
    lote = arquivo.novo_lote("TRANSFERENCIA_SICOOB")
    with pytest.raises(ValueError, match="mais de 2 casas decimais"):
        lote.adicionar(
            *[
                TransferenciaConta(
                    valor=Decimal("33.3333"), data_pagamento=HOJE, favorecido=favorecido()
                )
                for _ in range(3)
            ]
        )


def test_campos_monetarios_opcionais_do_segmento_b_seguem_a_mesma_regua():
    # Estes cinco nem por dinheiro() passavam: iam crus para a gravação.
    with pytest.raises(ValueError, match="mais de 2 casas decimais"):
        TransferenciaConta(
            valor="10.00", data_pagamento=HOJE, favorecido=favorecido(),
            mora=Decimal("0.001"),
        )
    pagamento = TransferenciaConta(
        valor="10.00", data_pagamento=HOJE, favorecido=favorecido(),
        valor_documento="12.50", desconto=Decimal("1.5"),
    )
    assert pagamento.valor_documento == Decimal("12.50")
    assert pagamento.desconto == Decimal("1.5")
    assert pagamento.abatimento is None  # não informado continua não informado


# --------------------------------------------------------------------------
# Agência e conta com máscara
# --------------------------------------------------------------------------


def test_agencia_e_conta_com_mascara_nao_colam_o_dv_no_numero():
    """"0910-5" é agência 0910 com DV 5 — nunca a agência 09105.

    Cru, o fmt_num tirava a pontuação e tratava o resto como número pronto: a
    agência virava 09105 e a conta, 000000456781. Números plausíveis, o
    validador aprovava, e o dinheiro caía em outra conta.
    """
    f = Favorecido(nome="JOAO DA SILVA", documento="123.456.789-09", banco="341",
                   agencia="0910-5", conta="45.678-1")
    assert (f.agencia, f.dv_agencia) == ("0910", "5")
    assert (f.conta, f.dv_conta) == ("45678", "1")

    e = Empresa(nome="ACME LTDA", documento="12.345.678/0001-95", convenio="123456",
                agencia="4321-0", conta="12.345-6", dv_conta="")
    assert (e.agencia, e.dv_agencia, e.conta, e.dv_conta) == ("4321", "0", "12345", "6")


def test_agencia_com_mascara_chega_certa_ao_segmento_a():
    arquivo = ArquivoRemessa(empresa(), nsa=1, data_geracao=HOJE)
    arquivo.novo_lote("TED", forma_lancamento=FormaLancamento.TED_OUTRA_TITULARIDADE).adicionar(
        TransferenciaConta(
            valor="10.00", data_pagamento=HOJE, finalidade_ted="5",
            favorecido=Favorecido(nome="JOAO DA SILVA", documento="12345678909",
                                  banco="341", agencia="0910-5", conta="45.678-1"),
        )
    )
    a = [l for l in arquivo.gerar() if l[13] == "A"][0]
    assert a[23:28] == "00910"          # agência, sem o DV grudado
    assert a[28:29] == "5"              # DV da agência
    assert a[29:41] == "000000045678"   # conta
    assert a[41:42] == "1"              # DV da conta


def test_agencia_e_conta_grandes_demais_sao_recusadas():
    with pytest.raises(ValueError, match="agência do favorecido"):
        Favorecido(nome="X", documento="12345678909", banco="341", agencia="123456")
    with pytest.raises(ValueError, match="conta do favorecido"):
        Favorecido(nome="X", documento="12345678909", banco="341", conta="1234567890123")


def test_dv_que_nao_e_digito_e_recusado_em_vez_de_virar_branco():
    # DV "X" existe em outros bancos; o campo do CNAB é numérico. Deixá-lo
    # virar branco trocaria a conta de destino sem nada denunciar.
    with pytest.raises(ValueError, match="não é um dígito"):
        Favorecido(nome="X", documento="12345678909", banco="341",
                   conta="12345", dv_conta="X")


def test_dv_da_mascara_que_contradiz_o_campo_e_recusado():
    with pytest.raises(ValueError, match="Um dos dois está errado"):
        Favorecido(nome="X", documento="12345678909", banco="341",
                   conta="45.678-1", dv_conta="2")


# --------------------------------------------------------------------------
# O produto e o banco do favorecido
# --------------------------------------------------------------------------


def test_ted_recusa_favorecido_do_proprio_sicoob():
    """Favorecido.banco vale 756 por omissão — esquecer o banco= era mudo."""
    arquivo = ArquivoRemessa(empresa(), nsa=1, data_geracao=HOJE)
    lote = arquivo.novo_lote("TED", forma_lancamento=FormaLancamento.TED_OUTRA_TITULARIDADE)
    with pytest.raises(RemessaInvalida, match="banco="):
        lote.adicionar(
            TransferenciaConta(
                valor="10.00", data_pagamento=HOJE, favorecido=favorecido(), finalidade_ted="5"
            )
        )


def test_transferencia_sicoob_recusa_favorecido_de_outro_banco():
    arquivo = ArquivoRemessa(empresa(), nsa=1, data_geracao=HOJE)
    lote = arquivo.novo_lote("TRANSFERENCIA_SICOOB")
    with pytest.raises(RemessaInvalida, match="sai por TED"):
        lote.adicionar(
            TransferenciaConta(valor="10.00", data_pagamento=HOJE, favorecido=favorecido("341"))
        )


# --------------------------------------------------------------------------
# Validador
# --------------------------------------------------------------------------


def test_validador_detecta_linha_com_tamanho_errado():
    linhas = gerar_transferencia()
    linhas[2] = linhas[2][:239]
    problemas = validar(linhas)
    assert any("239 posições" in p.mensagem for p in problemas)


def test_validador_detecta_total_divergente():
    linhas = gerar_transferencia()
    trailer = linhas[-2]
    linhas[-2] = trailer[:23] + "0" * 18 + trailer[41:]
    problemas = validar(linhas)
    assert any(p.campo == "06.5" for p in problemas)


def test_validador_detecta_nsr_fora_de_ordem():
    linhas = gerar_transferencia()
    linhas[4] = linhas[4][:8] + "00009" + linhas[4][13:]
    problemas = validar(linhas)
    assert any("sequencial" in p.mensagem for p in problemas)


def test_validador_detecta_dominio_invalido():
    linhas = gerar_transferencia()
    header_lote = linhas[1]
    linhas[1] = header_lote[:11] + "99" + header_lote[13:]
    problemas = validar(linhas)
    assert any(p.nivel == NIVEL_ARQUIVO for p in problemas)


def test_validador_detecta_banco_errado():
    linhas = gerar_transferencia()
    linhas[2] = "001" + linhas[2][3:]
    assert any("esperado 756" in p.mensagem for p in validar(linhas))


def test_validador_detecta_inscricao_que_nao_fecha_o_dv():
    """"Preenchido" nunca foi o mesmo que "válido".

    O Sicoob devolveu a remessa de 20/08/2026 apontando o 08.3B: um CPF de
    preenchimento, onze dígitos, DV que não fecha. O validador daqui só sabia
    perguntar se o campo estava VAZIO — e não estava —, então o arquivo saiu
    limpo daqui e voltou recusado de lá. Conferir o DV é o que traz esse
    veredito para antes do envio.
    """
    linhas = gerar_transferencia()
    i = next(n for n, l in enumerate(linhas) if l[13:14] == "B")
    # Tipo 1 (CPF) e um número de onze dígitos que não fecha: é o CPF sintético
    # das fixtures com o último dígito trocado.
    linhas[i] = linhas[i][:17] + "1" + "12345678900".rjust(14, "0") + linhas[i][32:]
    problemas = validar(linhas)
    assert any(p.campo == "08.3B" and "dígito verificador" in p.mensagem
               for p in problemas)


def test_validador_aceita_cpf_com_zero_a_esquerda():
    """A leitura é pelos ÚLTIMOS onze dígitos, não pelo campo sem os zeros.

    O campo tem catorze posições e é alinhado à direita com zeros. Quem lê
    tirando TODO zero da frente ampute o CPF que começa em zero e reprova gente
    legítima — o oposto exato do defeito que a conferência veio consertar.
    """
    linhas = gerar_transferencia()
    i = next(n for n, l in enumerate(linhas) if l[13:14] == "B")
    linhas[i] = linhas[i][:17] + "1" + "01234567890".rjust(14, "0") + linhas[i][32:]
    assert not [p for p in validar(linhas) if p.campo == "08.3B"]


# --------------------------------------------------------------------------
# Retorno
# --------------------------------------------------------------------------


def simular_retorno(linhas: list[str], ocorrencias: dict[int, str]) -> list[str]:
    """Transforma uma remessa em retorno: marca o header e grava ocorrências."""
    saida = [linhas[0][:142] + "2" + linhas[0][143:]]
    for i, linha in enumerate(linhas[1:], start=1):
        codigo = ocorrencias.get(i, "")
        saida.append(linha[:230] + codigo.ljust(10) if codigo else linha)
    return saida


def test_leitura_de_retorno_confirmado():
    remessa = gerar_transferencia()
    retorno = simular_retorno(remessa, {2: "00", 4: "00"})
    arquivo = ler_retorno(retorno)

    assert arquivo.e_retorno
    assert arquivo.empresa == "ACME COMERCIO E SERVICOS LTDA"
    assert arquivo.nsa == 1

    pagamentos = list(arquivo.pagamentos())
    assert len(pagamentos) == 2
    assert all(p.sucesso for p in pagamentos)
    assert pagamentos[0].valor == Decimal("1500.00")
    assert pagamentos[0].seu_numero == "NF001"
    assert pagamentos[0].favorecido.strip() == "JOAO DA SILVA"


def test_leitura_de_retorno_rejeitado_traz_motivo():
    remessa = gerar_transferencia()
    retorno = simular_retorno(remessa, {2: "00", 4: "PJ"})
    arquivo = ler_retorno(retorno)
    pagamentos = list(arquivo.pagamentos())

    assert pagamentos[0].sucesso
    assert pagamentos[1].rejeitado
    assert pagamentos[1].ocorrencias == [("PJ", "Chave não cadastrada no DICT")]

    resumo = arquivo.resumo()
    assert resumo["confirmados"] == 1
    assert resumo["rejeitados"] == 1
    assert resumo["valor_confirmado"] == Decimal("1500.00")
    assert "PJ - Chave não cadastrada no DICT" in resumo["motivos"]


def test_retorno_le_segmento_z():
    remessa = gerar_transferencia()
    z = (
        "756" + "0001" + "3" + "00005" + "Z"
        + "AUTENTICACAO123".ljust(64)
        + "PROTOCOLO987".ljust(25)
        + " " * 127
        + "00".ljust(10)
    )
    assert len(z) == 240
    retorno = simular_retorno(remessa, {2: "00", 4: "00"})
    retorno.insert(-2, z)
    # o trailer do lote precisa refletir o registro extra
    trailer = retorno[-2]
    retorno[-2] = trailer[:17] + "000007" + trailer[23:]

    arquivo = ler_retorno(retorno)
    pagamentos = list(arquivo.pagamentos())
    assert pagamentos[-1].autenticacao == "AUTENTICACAO123"
    assert pagamentos[-1].protocolo == "PROTOCOLO987"


def test_pendente_de_assinatura_nao_e_rejeicao():
    remessa = gerar_transferencia()
    retorno = simular_retorno(remessa, {2: "00", 4: "PD"})
    pagamentos = list(ler_retorno(retorno).pagamentos())

    assert pagamentos[1].pendente
    assert not pagamentos[1].rejeitado
    assert not pagamentos[1].sucesso

    resumo = ler_retorno(retorno).resumo()
    assert (resumo["confirmados"], resumo["rejeitados"], resumo["pendentes"]) == (1, 0, 1)


def test_segmento_b_nao_gera_ocorrencia_fantasma():
    # 231-232 do segmento B são a UG Centralizadora (zeros); ler ocorrência ali
    # produziria um '00' inexistente e mascararia a rejeição do pagamento.
    remessa = gerar_transferencia()
    retorno = simular_retorno(remessa, {2: "PJ"})
    pagamentos = list(ler_retorno(retorno).pagamentos())
    assert pagamentos[0].codigos == ["PJ"]


def test_retorno_de_titulo_e_lido():
    arquivo_remessa = ArquivoRemessa(empresa(), nsa=3, data_geracao=HOJE)
    arquivo_remessa.novo_lote(
        "TITULOS_COBRANCA", forma_lancamento=FormaLancamento.TITULO_OUTROS_BANCOS
    ).adicionar(
        PagamentoTitulo(
            valor="320.00", data_pagamento=HOJE, codigo_barras=CODIGO_BARRAS,
            nome_cedente="FORNECEDOR SA", seu_numero="DUP-77",
        )
    )
    retorno = simular_retorno(arquivo_remessa.gerar(), {2: "BD"})
    pagamentos = list(ler_retorno(retorno).pagamentos())
    assert len(pagamentos) == 1
    assert pagamentos[0].segmento == "J"
    assert pagamentos[0].seu_numero == "DUP-77"
    assert pagamentos[0].sucesso  # BD = agendado com sucesso


# ---------------------------------------------------------------------------
# Uma fonte só
#
# Até 02/09/2026 existiam DUAS cópias deste pacote: a do app e uma autônoma,
# no repositório das automações avulsas, que os scripts de validação com o
# banco importavam. A autônoma parou em 14/08 e nunca soube que `dv_cpf`,
# `dv_cnpj` e `documento_valido` passaram a existir em 20/08 — depois de o
# Sicoob devolver a remessa 000002 por um CPF de preenchimento vindo do
# cadastro. Os 84 testes dela passavam verdes justamente por não saberem da
# validação, e uma ferramenta que aprova o arquivo que o banco recusa é o pior
# resultado que uma ferramenta de conferência pode dar.
#
# Estes três testes valem no CI, onde só o repositório do app existe: eles não
# procuram a cópia de fora (não haveria como), procuram as condições que
# deixaram a cópia de fora ser possível.
# ---------------------------------------------------------------------------
_RAIZ = Path(__file__).resolve().parent.parent
_FERRAMENTAS = _RAIZ / "cnab240" / "ferramentas"


def test_existe_um_dominios_py_so():
    """Duas cópias do arquivo = duas respostas para "este CPF vale?"."""
    achados = sorted(
        p.relative_to(_RAIZ).as_posix()
        for p in _RAIZ.rglob("dominios.py")
        if "__pycache__" not in p.parts and ".git" not in p.parts
        and "codigo_embutido" not in p.parts and "codigo" not in p.parts)
    assert achados == ["cnab240/dominios.py"], (
        f"achei mais de um `dominios.py` no repositório: {achados}. Uma cópia "
        "a mais é uma segunda régua de dígito verificador esperando divergir "
        "da primeira — foi assim que um CPF inválido chegou ao campo 08.3B.")


def _arvore(arquivo: Path):
    import ast
    return ast.parse(arquivo.read_text(encoding="utf-8"), str(arquivo))


def _py_das_ferramentas() -> list[Path]:
    achados = sorted(p for p in _FERRAMENTAS.glob("*.py"))
    assert achados, "cnab240/ferramentas/ ficou sem nenhum .py"
    return achados


def test_as_ferramentas_importam_o_cnab240_deste_repositorio():
    """Ferramenta que não fala com ESTE pacote não prova nada sobre ele."""
    import ast

    mudos = []
    for arquivo in _py_das_ferramentas():
        fala = False
        for no in ast.walk(_arvore(arquivo)):
            if isinstance(no, ast.Import):
                fala = fala or any(a.name.split(".")[0] == "cnab240"
                                   for a in no.names)
            elif isinstance(no, ast.ImportFrom):
                # `from cnab240... import` ou `from .` — os dois são este
                # pacote; o relativo, por definição, não alcança outra cópia.
                fala = fala or no.level > 0 or (
                    (no.module or "").split(".")[0] == "cnab240")
        if not fala and arquivo.name != "__init__.py":
            mudos.append(arquivo.name)
    assert not mudos, (
        f"{mudos} não importa nada de `cnab240`. Ou a ferramenta fala com o "
        "pacote deste repositório, ou ela está medindo outra coisa.")


def test_as_ferramentas_nao_apontam_o_sys_path_para_fora():
    r"""Caminho absoluto escrito à mão foi o que criou a segunda cópia.

    Era `sys.path.insert(0, r"C:\...\fontes\cnab240")`: amarrava o script à
    máquina de uma pessoa e, pior, a uma cópia do pacote que parou no tempo.
    O caminho tem de sair do `__file__` — assim ele só alcança este repositório,
    esteja ele em que pasta estiver, e nunca alcança um segundo `cnab240`.

    Desde 02/09/2026 o teste cobra mais uma coisa: que o que entra no
    `sys.path` seja a RAIZ, e nada abaixo dela. Toda pasta de aba é pacote e se
    importa pelo nome inteiro; devolver `RAIZ / "pagamentos_dia"` ao caminho
    ressuscitaria o espaço plano em que `config.py`, `frame.py` e
    `conferencia.py` disputam o mesmo nome — e uma ferramenta que importa o
    módulo errado responde com convicção sobre outro assunto.
    """
    import ast
    import re

    #: `C:\...`, `C:/...`, `/...` ou `\servidor\...`
    absoluto = re.compile(r"^([A-Za-z]:[\\/]|[\\/][\\/]|/)")

    problemas = {}
    for arquivo in _py_das_ferramentas():
        arvore = _arvore(arquivo)
        for no in ast.walk(arvore):
            # (1) nenhum literal de caminho absoluto, em lugar nenhum
            if (isinstance(no, ast.Constant) and isinstance(no.value, str)
                    and absoluto.match(no.value)):
                problemas.setdefault(arquivo.name, []).append(
                    f"linha {no.lineno}: caminho absoluto escrito à mão")
            alvo = getattr(no, "func", None)
            if (isinstance(no, ast.Call) and isinstance(alvo, ast.Attribute)
                    and alvo.attr in ("insert", "append")
                    and ast.unparse(alvo.value).replace(" ", "").endswith(
                        "sys.path")):
                for arg in no.args:
                    # (2) nada de constante indo para o sys.path
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        problemas.setdefault(arquivo.name, []).append(
                            f"linha {no.lineno}: sys.path recebendo texto fixo")
                    # (3) e o que entra é a RAIZ, não uma subpasta dela
                    elif isinstance(arg, ast.Call) and arg.args:
                        escrito = ast.unparse(arg.args[0]).replace(" ", "")
                        if escrito not in ("RAIZ", "_RAIZ") and escrito != "0":
                            problemas.setdefault(arquivo.name, []).append(
                                f"linha {no.lineno}: sys.path recebendo "
                                f"`{escrito}` — só a RAIZ pode entrar")
    assert not problemas, (
        "estas ferramentas apontam o caminho de import para fora do "
        f"repositório, ou para dentro de uma subpasta dele: {problemas}. O "
        "caminho sai do `__file__` e para na raiz — ver "
        "`cnab240/ferramentas/_ambiente.py`.")


def test_o_pacote_sabe_recusar_documento_que_nao_fecha():
    """As três funções de 20/08/2026, e a recusa que elas existem para dar.

    A cópia autônoma não tinha nenhuma das três, e por isso aprovava o CPF de
    preenchimento que o Sicoob devolveu. Um teste que só conferisse "a função
    existe" passaria numa função que devolve `True` sempre — daí a recusa
    estar aqui junto.
    """
    from cnab240 import dominios

    for nome in ("dv_cpf", "dv_cnpj", "documento_valido"):
        assert callable(getattr(dominios, nome, None)), (
            f"`cnab240.dominios.{nome}` sumiu. É a conferência de dígito "
            "verificador que faltava quando a remessa 000002 foi recusada.")

    # Um CPF fictício válido, e o MESMO com o último dígito trocado.
    assert dominios.dv_cpf("11144477735")
    assert not dominios.dv_cpf("11144477734")
    assert dominios.documento_valido("111.444.777-35") == "11144477735"
    assert dominios.documento_valido("111.444.777-34") == ""

    # E o mesmo para CNPJ, que é a outra metade do campo de inscrição.
    assert dominios.dv_cnpj("12345678000195")
    assert not dominios.dv_cnpj("12345678000194")
    assert dominios.documento_valido("12.345.678/0001-94") == ""
