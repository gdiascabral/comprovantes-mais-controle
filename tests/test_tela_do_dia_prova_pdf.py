# -*- coding: utf-8 -*-
"""O PDF da prova, com imagens fictícias. Pillow desenha a página como
imagem, então o texto é conferido nas funções que o montam e o PDF pelo
número e tamanho das páginas."""
import datetime as dt
import io
from decimal import Decimal as D

import pytest
from PIL import Image, ImageChops, JpegImagePlugin

from tela_do_dia import prova_pdf as pdf
from tela_do_dia import prova_saldos as ps

pdfplumber = pytest.importorskip("pdfplumber")

AGORA = dt.datetime(2026, 10, 27, 14, 5)


def _png(caminho, tamanho=(800, 120)):
    Image.new("RGB", tamanho, (200, 200, 200)).save(caminho)
    return caminho


def _linhas(tmp_path, n=2):
    alfa = ps.ContaDaProva(8, "CONTA ALFA", ps.SICOOB, numero="12.345-6")
    beta = ps.ContaDaProva(9, "CONTA BETA", ps.INTER, apelido="BETA")
    l1 = ps.comparar(alfa, ps.Leitura(D("10.00"), AGORA, imagem=_png(tmp_path / "e.png")),
                     ps.Leitura(D("10.00"), AGORA, imagem=_png(tmp_path / "b.png", (1200, 700))))
    l2 = ps.comparar(beta, ps.Leitura(D("5.00"), AGORA),
                     ps.Leitura(None, motivo="QR não lido a tempo", sem_imagem="sem sessão"))
    extras = [ps.comparar(ps.ContaDaProva(20 + i, f"CONTA {i}", ps.SICOOB, numero=str(i)),
                          ps.Leitura(D("1.00"), AGORA), ps.Leitura(D("1.00"), AGORA))
              for i in range(max(0, n - 2))]
    return [l1, l2, *extras]


def _paginas(caminho):
    with pdfplumber.open(caminho) as doc:
        return [(round(p.width), round(p.height)) for p in doc.pages]


def test_gera_resumo_e_uma_pagina_por_conta(tmp_path):
    destino = tmp_path / "Prova de saldos 2026-10-27 14h05.pdf"
    assert pdf.gerar(_linhas(tmp_path), AGORA, destino) == destino
    assert destino.read_bytes()[:4] == b"%PDF"
    assert not destino.with_name(destino.name + ".tmp").exists()
    assert _paginas(destino) == [(842, 595)] * 3          # A4 deitado


def test_resumo_longo_quebra_em_paginas_sem_perder_linha(tmp_path, monkeypatch):
    linhas = _linhas(tmp_path, n=19)
    blocos = pdf.paginas_do_resumo(linhas)
    assert [len(b) for b in blocos] == [18, 1]
    assert [l for b in blocos for l in b] == linhas
    monkeypatch.setattr(pdf, "LINHAS_POR_PAGINA", 2)
    destino = tmp_path / "longo.pdf"
    pdf.gerar(linhas[:3], AGORA, destino)
    assert len(_paginas(destino)) == 2 + 3


def test_resumo_sem_contas_ainda_tem_uma_pagina():
    assert pdf.paginas_do_resumo([]) == [[]]


def test_textos_da_pagina_da_conta(tmp_path):
    _l1, l2 = _linhas(tmp_path)
    assert pdf.titulo(AGORA) == "Prova de saldos — 27/10/2026 14:05"
    assert pdf.textos_da_conta(l2) == [
        "CONTA BETA — NÃO LIDA",
        "ERP (Mais Controle): R$ 5,00 · lido às 14:05",
        "Banco (Inter): não lido — QR não lido a tempo",
        "banco: QR não lido a tempo"]


def test_sem_fonte_do_windows_usa_a_padrao(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "_PASTA_FONTES", tmp_path / "nao-existe")
    assert pdf.fonte(20) is not None
    destino = tmp_path / "sem-fonte.pdf"
    pdf.gerar(_linhas(tmp_path), AGORA, destino)
    assert len(_paginas(destino)) == 3


def test_print_que_nao_abre_vira_caixa_com_o_porque(tmp_path):
    ruim = tmp_path / "ruim.png"
    ruim.write_bytes("isto não é png".encode("utf-8"))
    conta = ps.ContaDaProva(8, "CONTA ALFA", ps.SICOOB, numero="1")
    linha = ps.comparar(conta, ps.Leitura(D("1.00"), AGORA, imagem=ruim),
                        ps.Leitura(D("1.00"), AGORA))
    destino = tmp_path / "ruim.pdf"
    pdf.gerar([linha], AGORA, destino)
    assert len(_paginas(destino)) == 2


# ------------------------------------------- legível no celular (revisão 27/10)
AZUL, VERMELHO = (0, 0, 255), (255, 0, 0)


def _caixa_da_cor(pagina, cor):
    """O retângulo (x0, y0, x1, y1) da cor pura na página, ou None."""
    canais = pagina.convert("RGB").split()
    mascara = None
    for canal, alvo in zip(canais, cor):
        parte = canal.point(lambda v, a=alvo: 255 if abs(v - a) < 16 else 0)
        mascara = parte if mascara is None else ImageChops.multiply(mascara, parte)
    return mascara.getbbox()


def _linha_com(tmp_path, erp_tam, banco_tam):
    erp = tmp_path / f"erp {erp_tam}.png"
    banco = tmp_path / f"banco {banco_tam}.png"
    Image.new("RGB", erp_tam, AZUL).save(erp)
    Image.new("RGB", banco_tam, VERMELHO).save(banco)
    conta = ps.ContaDaProva(8, "CONTA ALFA", ps.SICOOB, numero="1")
    return ps.comparar(conta, ps.Leitura(D("1.00"), AGORA, imagem=erp),
                       ps.Leitura(D("1.00"), AGORA, imagem=banco))


@pytest.mark.parametrize("erp_tam, banco_tam", [
    ((1100, 90), (1200, 700)),         # grade do ERP com cabeçalho + banco recortado
    ((1500, 120), (1920, 1080)),       # banco na tela inteira maximizada
    ((600, 80), (900, 500))])          # prints pequenos: nunca ampliados
def test_print_entra_sem_reduzir_abaixo_da_largura_util(tmp_path, erp_tam, banco_tam):
    """Cada print entra a ~1:1; só reduz o que passa da largura útil da
    página (≥ 1240 px, a de um A4 a 150 dpi). Medido na página desenhada."""
    assert pdf.LARGURA_UTIL >= 1240
    paginas = pdf.paginas_da_conta(_linha_com(tmp_path, erp_tam, banco_tam))
    for cor, tam in ((AZUL, erp_tam), (VERMELHO, banco_tam)):
        caixas = [c for c in (_caixa_da_cor(p, cor) for p in paginas) if c]
        assert len(caixas) == 1, "cada print num bloco só"
        x0, y0, x1, y1 = caixas[0]
        esperado = min(tam[0], pdf.LARGURA_UTIL)
        assert x1 - x0 >= 0.9 * esperado
        assert x1 - x0 <= tam[0]                      # nunca ampliado


def test_erp_em_cima_e_banco_embaixo_na_largura_toda(tmp_path):
    paginas = pdf.paginas_da_conta(_linha_com(tmp_path, (1100, 90), (1200, 700)))
    assert len(paginas) == 1
    erp = _caixa_da_cor(paginas[0], AZUL)
    banco = _caixa_da_cor(paginas[0], VERMELHO)
    assert erp[3] < banco[1]                          # ERP termina antes do banco
    assert erp[0] == banco[0] == pdf.MARGEM           # os dois na largura toda


def test_print_que_nao_cabe_continua_em_outra_pagina(tmp_path):
    paginas = pdf.paginas_da_conta(_linha_com(tmp_path, (1500, 600), (1600, 900)))
    assert len(paginas) == 2
    assert _caixa_da_cor(paginas[0], AZUL) and not _caixa_da_cor(paginas[0], VERMELHO)
    assert _caixa_da_cor(paginas[1], VERMELHO)


def test_pdf_guarda_a_pagina_inteira_em_jpeg_de_alta_qualidade(tmp_path):
    """Pillow grava página RGB em DCT (JPEG): qualidade alta e cor sem
    subamostragem, para o texto pequeno não ganhar halo."""
    destino = tmp_path / "q.pdf"
    pdf.gerar([_linha_com(tmp_path, (1100, 90), (1200, 700))], AGORA, destino)
    with pdfplumber.open(destino) as doc:
        for pagina in doc.pages:
            [imagem] = pagina.images
            assert imagem["srcsize"] == (pdf.LARGURA, pdf.ALTURA)
            jpeg = Image.open(io.BytesIO(imagem["stream"].get_rawdata()))
            assert max(jpeg.quantization[0]) <= 13            # quality ≥ 95
            assert JpegImagePlugin.get_sampling(jpeg) == 0      # 4:4:4


def test_colunas_do_resumo_cabem_na_pagina():
    """HORA BANCO em negrito passava da margem direita (x=1600)."""
    cabecalho, corpo = pdf.fonte(20, True), pdf.fonte(20)
    exemplos = ("CONDOMINIO RESIDENCIAL FICTICIO MODELO - SICOOB", brl_longo := "-R$ 1.234.567,89", brl_longo, brl_longo,
                "NÃO BATE", "23:59", "23:59")
    limites = [*pdf.COLUNAS_X[1:], pdf.LARGURA - pdf.MARGEM]
    for x, fim, nome, exemplo in zip(pdf.COLUNAS_X, limites, ps.COLUNAS, exemplos):
        assert x + cabecalho.getlength(nome) <= fim - 8, nome
        texto = pdf._cortar(exemplo, 38)
        assert x + corpo.getlength(texto) <= fim - 8, nome


def test_exe_sem_freetype_cai_na_fonte_padrao(tmp_path, monkeypatch):
    """Revisão de 27/10: sem o `_imagingft` no exe, `truetype` levanta
    ImportError (não OSError) e a prova caía em "falhou" depois dos QR."""
    def sem_freetype(*a, **k):
        raise ImportError("The _imagingft C module is not installed")
    monkeypatch.setattr(pdf.ImageFont, "truetype", sem_freetype)
    assert pdf.fonte(20, True) is not None
    destino = tmp_path / "sem-freetype.pdf"
    pdf.gerar(_linhas(tmp_path), AGORA, destino)
    assert destino.read_bytes()[:4] == b"%PDF"
