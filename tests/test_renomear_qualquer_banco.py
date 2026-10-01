# -*- coding: utf-8 -*-
"""Separar e Renomear: banco que os leitores não conheciam (Next e afins) e
comprovante em IMAGEM.

Textos sintéticos em tests/fixtures/next_*.txt — o repositório é público."""
from pathlib import Path

import pytest

sr = pytest.importorskip("separar_renomear.separar_renomear")

FIX = Path(__file__).resolve().parent / "fixtures"


def _ler(nome):
    return (FIX / nome).read_text(encoding="utf-8")


def test_next_conta_de_consumo():
    c = sr.campos(_ler("next_conta_de_consumo.txt"))
    assert c["valor"] == "206,63"
    assert c["data"] == "30/09/2026"
    assert sr.nome_arquivo(c) == \
        "206,63 - OBRA EXEMPLO QD 51 LT 29 UC 12345 AGO - 30-09"


def test_next_pix_valor_americano_e_descricao_traco():
    """"Valor: 1,400.00" (grafia americana) e "Descrição: -" (campo vazio):
    antes saía "SEM VALOR - -.pdf"."""
    c = sr.campos(_ler("next_pix_sem_descricao.txt"))
    assert c["valor"] == "1.400,00"
    assert not c["desc"]
    assert c["dest"].startswith("EMPRESA DE AGUA EXEMPLO")
    assert sr.nome_arquivo(c) == "1400,00 - EMPRESA DE AGUA EXEMPLO - 30-09"


def test_next_boleto_recebedor_nao_e_o_nome_do_pagador():
    c = sr.campos(_ler("next_boleto_nome_pagador.txt"))
    assert c["valor"] == "1.691,20"
    assert c["dest"] == "LOJA DE TINTAS EXEMPLO"


@pytest.mark.parametrize("texto, valor", [
    ("Valor do pagamento: R$ 30,71", "30,71"),
    ("Valor principal: R$ 233,26 Desconto: R$ 0,00 Valor do pagamento: R$ 240,00",
     "240,00"),
    ("Valor: 41.48", "41,48"),
    ("Valor: 1,400.00", "1.400,00"),
    ("Total pago 1.234,56", "1.234,56"),
    ("Quantia: R$ 12.000,00", "12.000,00"),
    ("Pix enviado\nR$ 500,00 Pix enviado\nSobre a transação R$ 500,00", "500,00"),
    # dois valores diferentes e nenhum rótulo: dúvida, não chute
    ("R$ 5,00 Pix\nR$ 10,00", None),
    # juros, multa, valor original não são o que saiu da conta
    ("Juros R$ 1,00\nR$ 10,00", "10,00"),
    ("Valor original: R$ 99,00", None),
    ("Multa: R$ 0,00", None),
])
def test_valor_generico(texto, valor):
    assert sr._valor_generico(texto) == valor


def test_valor_generico_so_entra_quando_o_leitor_de_sempre_falha():
    """O rótulo clássico do Sicoob continua mandando."""
    c = sr.campos(_ler("sicoob_pix_impresso.txt"))
    assert c["valor"] == "1.890,00"


@pytest.mark.parametrize("vazio", ["-", "—", " - ", "N/A", "Sem descrição"])
def test_descricao_preenchida_com_traco_e_vazia(vazio):
    t = f"Comprovante\nValor: R$ 10,00\nDescrição: {vazio}\nObservação: OC 1234\n"
    assert sr._descricao(t, "?") == "OC 1234"


def test_descricao_com_outros_nomes_de_campo():
    assert sr._descricao("Mensagem: QD 1 LT 2 OC 99\n", "?") == "QD 1 LT 2 OC 99"
    assert sr._descricao("Informações adicionais: NF 10\n", "?") == "NF 10"


def test_rotulo_sozinho_continua_lendo_a_linha_de_baixo():
    """"Descrição:" com o texto na linha seguinte NÃO é campo vazio."""
    t = "Valor: R$ 10,00\nDescrição:\nOBRA QD 1 LT 2 OC 77\n"
    assert sr._descricao(t, "?") == "OBRA QD 1 LT 2 OC 77"


# ------------------------------------------------------------------ imagens
PIL = pytest.importorskip("PIL.Image")


def _paginas(pdf):
    from pypdf import PdfReader
    return PdfReader(str(pdf)).pages


def test_imagem_vira_pdf_de_uma_pagina(tmp_path):
    origem = tmp_path / "comprovante.png"
    PIL.new("RGBA", (300, 600), (255, 255, 255, 0)).save(origem)
    destino = tmp_path / "comprovante.pdf"
    sr.imagem_para_pdf(origem, destino)
    paginas = _paginas(destino)
    assert len(paginas) == 1
    caixa = paginas[0].mediabox
    assert float(caixa.width) < float(caixa.height)       # em pé


def test_foto_deitada_pelo_exif_sai_em_pe(tmp_path):
    origem = tmp_path / "foto.jpg"
    img = PIL.new("RGB", (600, 300), (255, 255, 255))     # deitada
    exif = img.getexif()
    exif[0x0112] = 6                                      # "gire 90°"
    img.save(origem, exif=exif)
    destino = tmp_path / "foto.pdf"
    sr.imagem_para_pdf(origem, destino)
    caixa = _paginas(destino)[0].mediabox
    assert float(caixa.width) < float(caixa.height)


def test_imagens_da_pasta_entram_e_ruim_nao_derruba(tmp_path):
    entrada = tmp_path / "entrada"; entrada.mkdir()
    saida = entrada / "RENOMEADOS"; saida.mkdir()
    temp = tmp_path / "temp"; temp.mkdir()
    PIL.new("RGB", (100, 200)).save(entrada / "a.jpg")
    PIL.new("RGB", (100, 200)).save(entrada / "b.PNG")
    (entrada / "quebrada.jpg").write_bytes(b"nao e imagem")
    (entrada / "nota.txt").write_text("x")
    PIL.new("RGB", (100, 200)).save(saida / "ja_renomeada.jpg")
    erros = []
    feitas = sr._imagens_como_pdf(entrada, saida, temp, erros.append)
    assert sorted(p.name for p in feitas) == ["a.jpg.pdf", "b.PNG.pdf"]
    assert len(erros) == 1 and "quebrada.jpg" in erros[0]


def test_imagem_lida_em_colunas_acha_o_valor_do_rotulo_solto():
    """O OCR de imagem lê a coluna dos rótulos e depois a dos valores."""
    t = ("Dados do pagamento\nValor:\nDescrição:\nIdentificador:\n"
         "Valor original:\nMulta:\nDesconto:\n41.48\n0000000000000\n"
         "R$ 0,00\nR$ 0,00\nData: 30/09/2026\n")
    c = sr.campos(t)
    assert c["valor"] == "41,48"
    assert c["data"] == "30/09/2026"


def test_valor_zero_nao_vira_nome():
    t = "Comprovante\nMulta:\nR$ 0,00\n"
    assert sr.campos(t)["valor"] is None


def test_descricao_em_colunas_so_com_rotulo_presente():
    com = "Valor do pagamento:\nDescrição:\nR$ 10,00\nOBRA QD 5 LT 9 UC 1234\n"
    sem = "Valor do pagamento: R$ 10,00\nEndereço: RUA X QD 5 LT 9\n"
    assert sr.campos(com)["desc"] == "OBRA QD 5 LT 9 UC 1234"
    assert not sr.campos(sem)["desc"]


def test_descricao_quebrada_em_volta_do_rotulo_junta_as_duas_metades():
    t = ("Valor: R$ 84,00\nOBRA EXEMPLO QD 18 LT 8 NF 1616 OC\nDescrição:\n"
         "5587\nID Transação: E0000\n")
    assert sr._descricao(t, "?") == "OBRA EXEMPLO QD 18 LT 8 NF 1616 OC 5587"


def test_boleto_pago_com_juros_usa_o_valor_pago_e_nao_o_de_face():
    t = _ler("next_boleto_nome_pagador.txt").replace(
        "Juros: R$ 0,00", "Juros: R$ 10,00").replace(
        "Valor do pagamento: R$ 1.691,20", "Valor do pagamento: R$ 1.701,20")
    assert sr.campos(t)["valor"] == "1.701,20"


def test_colunas_com_valor_original_antes_do_pago_e_duvida():
    t = ("Valor original:\nJuros:\nValor pago:\n100.00\n5.00\n105.00\n"
         "Data: 30/09/2026\n")
    assert sr.campos(t)["valor"] is None


def test_rotulo_nao_atravessa_a_quebra_de_linha():
    assert sr._valor_generico("Valor pago:\n100.00\n") is None or \
        sr._valor_generico("Valor pago:\n100.00\n") == "100,00"
    # o que importa: "Valor pago:" do fim não pega o número do rótulo de cima
    t = "Valor original:\n100.00\nValor pago:\n105.00\n"
    assert sr._valor_generico(t) != "100,00"


def test_descricao_em_colunas_nao_pega_endereco_nem_o_que_vem_antes():
    antes = "OBRA QD 1 LT 2 OC 77\nDescrição:\nIdentificador:\nR$ 10,00\n"
    endereco = "Descrição:\nRUA DAS FLORES QD 5 LT 9\nR$ 10,00\n"
    distribuidora = "Descrição:\nDISTRIBUIDORA EXEMPLO\nR$ 10,00\n"
    for t in (antes, endereco, distribuidora):
        assert not sr._desc_em_colunas(t), t


def test_numero_solto_embaixo_do_rotulo_continua_valendo():
    t = "Valor: R$ 84,00\nDescrição:\n5587\nID Transação: E0000\n"
    assert sr._descricao(t, "?") == "5587"


def test_tiff_de_varias_paginas_vira_pdf_de_varias_paginas(tmp_path):
    origem = tmp_path / "scanner.tif"
    a, b = PIL.new("RGB", (100, 200)), PIL.new("RGB", (100, 200), (9, 9, 9))
    a.save(origem, save_all=True, append_images=[b])
    destino = tmp_path / "scanner.pdf"
    sr.imagem_para_pdf(origem, destino)
    assert len(_paginas(destino)) == 2
