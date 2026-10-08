# -*- coding: utf-8 -*-
"""QR Code Pix dos anexos do contas a pagar (dono, 08/10/2026).

Nenhum dado real: os BR Codes são montados aqui, com nomes e chaves
inventados, e o primeiro é o exemplo do próprio Manual de Padrões para
Iniciação do Pix (BCB), que vem com o CRC calculado. O repo é público.
"""
import io

import pytest

from pagamentos_dia import html_pagamentos, qr_pix, relatorio

#: O exemplo do manual do BR Code (BCB), com o CRC que o manual publica.
EXEMPLO_DO_MANUAL = (
    "00020126580014br.gov.bcb.pix0136123e4567-e12b-12d1-a456-426655440000"
    "5204000053039865802BR5913Fulano de Tal6008BRASILIA62070503***63041D3D")


def _campo(tag, valor):
    return f"{tag}{len(valor):02d}{valor}"


def brcode(nome="RECEBEDOR EXEMPLO", valor=None, cidade="GOIANIA",
           chave="123e4567-e12b-12d1-a456-426655440000", txid="***"):
    """Um BR Code estático, inventado, com o CRC certo."""
    corpo = (_campo("00", "01")
             + _campo("26", _campo("00", "br.gov.bcb.pix") + _campo("01", chave))
             + _campo("52", "0000") + _campo("53", "986")
             + (_campo("54", f"{valor:.2f}") if valor is not None else "")
             + _campo("58", "BR") + _campo("59", nome) + _campo("60", cidade)
             + _campo("62", _campo("05", txid)) + "6304")
    return corpo + qr_pix.crc16(corpo)


# ----------------------------------------------------------------- a forma
def test_o_crc_e_o_do_manual_do_bcb():
    assert qr_pix.crc16(EXEMPLO_DO_MANUAL[:-4]) == "1D3D"
    assert qr_pix.valido(EXEMPLO_DO_MANUAL)


def test_um_caractere_trocado_derruba_o_crc():
    trocado = EXEMPLO_DO_MANUAL.replace("Fulano", "Fulana")
    assert not qr_pix.valido(trocado)


def test_qr_que_nao_e_pix_nao_serve():
    assert not qr_pix.valido("https://exemplo.invalid/nfce?p=123")
    sem_gui = brcode().replace("br.gov.bcb.pix", "br.gov.xxx.pix")
    corpo = sem_gui[:-4]
    assert not qr_pix.valido(corpo + qr_pix.crc16(corpo))


def test_campos_valor_e_recebedor():
    c = brcode("LOJA EXEMPLO", 123.4)
    assert qr_pix.valor(c) == 123.4
    assert qr_pix.recebedor(c) == "LOJA EXEMPLO"
    assert qr_pix.cidade(c) == "GOIANIA"
    assert qr_pix.valor(brcode()) is None


def test_o_resto_do_app_reconhece_o_que_o_leitor_aceita():
    """Código que o HTML não reconhece como copia-e-cola teria só os dígitos
    copiados — o leitor não pode aceitá-lo."""
    c = brcode("LOJA & CIA", 10.0)          # "&" fora do alfabeto do regex
    assert not qr_pix.valido(c)
    ok = brcode("LOJA EXEMPLO", 10.0)
    assert html_pagamentos.dado_para_colar("Pix", ok) == ok


# ----------------------------------------------------------------- a leitura
# Import DIRETO, sem `importorskip`: a biblioteca está no requirements.lock,
# e um teste que some em silêncio quando ela falta não guarda nada.
import zxingcpp  # noqa: E402


def _png_do_qr(texto) -> bytes:
    from PIL import Image
    img = zxingcpp.create_barcode(texto, zxingcpp.BarcodeFormat.QRCode).to_image(scale=6)
    alto, largo = img.shape[0], img.shape[1]
    pil = Image.frombuffer("L", (largo, alto), bytes(img), "raw", "L", 0, 1)
    moldura = Image.new("L", (largo + 80, alto + 80), 255)
    moldura.paste(pil, (40, 40))
    buf = io.BytesIO()
    moldura.save(buf, "PNG")
    return buf.getvalue()


def _pdf_com(*pngs) -> bytes:
    from PIL import Image
    paginas = [Image.open(io.BytesIO(p)).convert("RGB") for p in pngs]
    buf = io.BytesIO()
    paginas[0].save(buf, "PDF", save_all=True, append_images=paginas[1:],
                    resolution=150)
    return buf.getvalue()


def test_le_o_qr_de_uma_imagem():
    c = brcode("LOJA EXEMPLO", 55.0)
    assert qr_pix.ler(_png_do_qr(c), eh_pdf=False) == [c]


def test_le_o_qr_da_segunda_pagina_do_pdf():
    c = brcode("LOJA EXEMPLO", 55.0)
    pdf = _pdf_com(_png_do_qr("https://exemplo.invalid/nfe"), _png_do_qr(c))
    assert qr_pix.ler(pdf, eh_pdf=True) == [c]


def test_qr_que_nao_e_pix_e_ignorado_e_lixo_nao_levanta():
    assert qr_pix.ler(_png_do_qr("https://exemplo.invalid/x"), eh_pdf=False) == []
    assert qr_pix.ler(b"nao sou pdf", eh_pdf=True) == []
    assert qr_pix.ler(b"", eh_pdf=False) == []


# ------------------------------------------------- a regra (relatorio)
def anexo(nome, tag=None, ext=".pdf", url=None):
    return {"filename": nome, "tagName": tag, "extension": ext,
            "downloadUrl": url or f"https://exemplo.invalid/{nome}"}


def item(favorecido="FORNECEDOR EXEMPLO", valor=55.0, metodo="Pix",
         conta_pix="", doc="1234"):
    return {"id": "i1", "tradePayableId": "t1", "paidTo": favorecido,
            "remainingValue": valor, "tradePayablePaymentMethod": metodo,
            "paidToBankAccount": conta_pix, "documentNumber": doc,
            "tradePayableAccount": {"name": "CONTA TESTE"},
            "costCentreDetails": [{"workName": "OBRA X"}]}


def linha(itens, anexos, textos=None, qrs=None):
    r = relatorio.montar_registros(itens, anexos, {}, textos or {}, qr_pix=qrs)
    contas = r.contas.get("CONTA TESTE") or []
    return (contas[0] if contas else None), r.omitidos


def test_pix_sem_chave_paga_pelo_qr_do_anexo():
    c = brcode("CARTORIO EXEMPLO", 55.0)
    reg, _ = linha([item()], {"t1": [anexo("guia.png", ext=".png", url="u1")]},
                   qrs={"u1": [c]})
    assert reg["tipo"] == "Pix"
    assert reg["dados"] == c
    assert reg["status"] == "APTO"
    assert "QR Code" in reg["obs"]
    assert "sem tipo declarado" not in reg["obs"]


def test_qr_de_outro_valor_nao_paga_e_avisa():
    c = brcode("CARTORIO EXEMPLO", 99.0)
    reg, _ = linha([item()], {"t1": [anexo("guia.png", ext=".png", url="u1")]},
                   qrs={"u1": [c]})
    assert reg["dados"] == ""
    assert "não usado" in reg["obs"]


def test_qr_de_comprovante_nunca_paga():
    c = brcode("CARTORIO EXEMPLO", 55.0)
    pelo_rotulo, _ = linha(
        [item()], {"t1": [anexo("x.png", tag="Comprovante", ext=".png", url="u1")]},
        qrs={"u1": [c]})
    assert pelo_rotulo is None or pelo_rotulo["dados"] != c
    pelo_texto, _ = linha(
        [item()], {"t1": [anexo("x.pdf", url="u1")]},
        textos={"u1": "Comprovante de pagamento Pix enviado"}, qrs={"u1": [c]})
    assert pelo_texto is None or pelo_texto["dados"] != c


def test_dois_qr_do_mesmo_valor_nao_escolhe():
    a, b = brcode("LOJA A", 55.0), brcode("LOJA B", 55.0)
    reg, _ = linha([item()], {"t1": [anexo("a.png", ext=".png", url="u1"),
                                     anexo("b.png", ext=".png", url="u2")]},
                   qrs={"u1": [a], "u2": [b]})
    assert reg["dados"] == ""
    assert "não dá para saber" in reg["obs"]


def test_qr_sem_valor_unico_paga_mas_manda_conferir_o_valor():
    c = brcode("CARTORIO EXEMPLO")
    reg, _ = linha([item()], {"t1": [anexo("guia.png", ext=".png", url="u1")]},
                   qrs={"u1": [c]})
    assert reg["dados"] == c
    assert "conferir R$ 55,00" in reg["obs"]


LINHA_BANCARIA = "34191.57007 00024.924375 24177.010006 9 15340000115000"
LINHA_ARRECADACAO = "86860000026-5 70860161209-4 22026081001-8 61001177300-1"


def _valor(linha_digitavel):
    from pagamentos_dia import ocr_boleto
    return ocr_boleto.valor_da_linha(linha_digitavel)


def test_boleto_comum_segue_pelo_boleto_e_traz_o_pix_junto():
    v = _valor(LINHA_BANCARIA)
    c = brcode("FORNECEDOR EXEMPLO", v)
    reg, _ = linha([item(valor=v, metodo="Boleto")],
                   {"t1": [anexo("boleto.pdf", tag="Boleto", url="u1")]},
                   textos={"u1": LINHA_BANCARIA}, qrs={"u1": [c]})
    assert reg["tipo"] == "Boleto"
    assert reg["dados"].startswith("34191")
    assert reg["pix_qr"] == c
    assert "Copiar Pix" in reg["obs"]


def test_concessionaria_de_goiania_nao_e_prefeitura():
    v = _valor(LINHA_ARRECADACAO)
    c = brcode("CONCESSIONARIA EXEMPLO", v, cidade="GOIANIA")
    reg, _ = linha([item("CONCESSIONARIA EXEMPLO", valor=v, metodo="Boleto")],
                   {"t1": [anexo("fatura.pdf", tag="Boleto", url="u1")]},
                   textos={"u1": LINHA_ARRECADACAO}, qrs={"u1": [c]})
    assert reg["tipo"] == "Boleto"
    assert reg["pix_qr"] == c


@pytest.mark.parametrize("favorecido,recebedor_qr", [
    ("PREFEITURA DE GOIÂNIA", "RECEBEDOR EXEMPLO"),
    ("GOIANIA PREFEITURA MUNICIPAL GABINETE DO PREFEITO", "RECEBEDOR EXEMPLO"),
    ("FAVORECIDO EXEMPLO", "MUNICIPIO DE GOIANIA"),
])
def test_guia_da_prefeitura_de_goiania_sai_pelo_pix_do_qr(favorecido, recebedor_qr):
    v = _valor(LINHA_ARRECADACAO)
    c = brcode(recebedor_qr, v)
    reg, _ = linha([item(favorecido, valor=v, metodo="Boleto", doc="998877")],
                   {"t1": [anexo("guia.pdf", tag="Boleto", url="u1")]},
                   textos={"u1": LINHA_ARRECADACAO}, qrs={"u1": [c]})
    assert reg["tipo"] == "Pix"
    assert reg["dados"] == c
    assert reg["pix_qr"] == ""
    assert "Prefeitura de Goiânia" in reg["obs"]
    assert reg["status"] == "APTO"
    # A guia continua sendo ficha de arrecadação: o número dela não é NF.
    assert "NF" not in reg["descricao"].split()


def test_guia_da_prefeitura_com_qr_sem_valor_vale_pela_linha_da_guia():
    v = _valor(LINHA_ARRECADACAO)
    c = brcode("RECEBEDOR EXEMPLO")
    reg, _ = linha([item("PREFEITURA DE GOIANIA", valor=v, metodo="Boleto")],
                   {"t1": [anexo("guia.pdf", tag="Boleto", url="u1")]},
                   textos={"u1": LINHA_ARRECADACAO}, qrs={"u1": [c]})
    assert reg["tipo"] == "Pix" and reg["dados"] == c


def test_aparecida_de_goiania_nao_e_goiania():
    assert relatorio.e_prefeitura_de_goiania("PREFEITURA DE GOIANIA")
    assert relatorio.e_prefeitura_de_goiania("Município de Goiânia")
    assert not relatorio.e_prefeitura_de_goiania(
        "PREFEITURA MUNICIPAL DE APARECIDA DE GOIANIA")
    assert not relatorio.e_prefeitura_de_goiania("CONCESSIONARIA GOIAS", "GOIANIA")


def test_prefeitura_em_reembolso_nao_vira_pix_do_qr():
    v = _valor(LINHA_ARRECADACAO)
    c = brcode("PREFEITURA DE GOIANIA", v)
    reg, _ = linha([item("PREFEITURA DE GOIANIA", valor=v, metodo="Boleto",
                         doc="REEMBOLSO FULANO")],
                   {"t1": [anexo("guia.pdf", tag="Boleto", url="u1")]},
                   textos={"u1": LINHA_ARRECADACAO}, qrs={"u1": [c]})
    assert reg["tipo"] == "Boleto"
    assert reg["dados"] != c


def test_aviso_pagar_para_ignora_o_qr():
    c = brcode("PREFEITURA DE GOIANIA", 55.0)
    reg, _ = linha([item("PREFEITURA DE GOIANIA")],
                   {"t1": [anexo("PAGAR PARA FULANO", url="u1"),
                           anexo("guia.png", ext=".png", url="u2")]},
                   textos={"u1": ""}, qrs={"u2": [c]})
    assert reg["dados"] != c
    assert reg["reembolso"]


def test_boleto_sem_linha_legivel_paga_pelo_qr_do_mesmo_documento():
    c = brcode("FORNECEDOR EXEMPLO", 55.0)
    reg, _ = linha([item(metodo="Boleto")],
                   {"t1": [anexo("boleto.pdf", tag="Boleto", url="u1")]},
                   textos={"u1": "boleto sem linha legivel"}, qrs={"u1": [c]})
    assert reg["tipo"] == "Pix"
    assert reg["dados"] == c
    assert "linha digitável do boleto não foi lida" in reg["obs"]


def test_sem_leitura_de_qr_nada_muda():
    v = _valor(LINHA_BANCARIA)
    reg, _ = linha([item(valor=v, metodo="Boleto")],
                   {"t1": [anexo("boleto.pdf", tag="Boleto", url="u1")]},
                   textos={"u1": LINHA_BANCARIA})
    assert reg["tipo"] == "Boleto" and reg["pix_qr"] == ""


# ----------------------------------------------------------------- o HTML
def test_html_traz_o_pix_do_qr_para_copiar():
    v = _valor(LINHA_BANCARIA)
    c = brcode("FORNECEDOR EXEMPLO", v)
    r = relatorio.montar_registros(
        [item(valor=v, metodo="Boleto")],
        {"t1": [anexo("boleto.pdf", tag="Boleto", url="u1")]}, {},
        {"u1": LINHA_BANCARIA}, qr_pix={"u1": [c]})
    entrada = html_pagamentos.contas_do_html_geral(r)[0]["entries"][0]
    assert entrada["pix_qr"] == c
    assert entrada["dados_limpo"] == "34191570070002492437524177010006915340000115000"
    import datetime
    html = html_pagamentos.html_geral(html_pagamentos.contas_do_html_geral(r),
                                      datetime.date(2026, 10, 8),
                                      datetime.date(2026, 10, 8))
    assert "copy-pix" in html


def test_guia_que_virou_pix_sai_no_html_com_o_codigo_inteiro():
    v = _valor(LINHA_ARRECADACAO)
    c = brcode("MUNICIPIO DE GOIANIA", v)
    r = relatorio.montar_registros(
        [item("PREFEITURA DE GOIANIA", valor=v, metodo="Boleto")],
        {"t1": [anexo("guia.pdf", tag="Boleto", url="u1")]}, {},
        {"u1": LINHA_ARRECADACAO}, qr_pix={"u1": [c]})
    entrada = html_pagamentos.contas_do_html_geral(r)[0]["entries"][0]
    assert entrada["dados_limpo"] == c


# ------------------------------------------- as travas que os mutantes pediram
def test_qr_sem_valor_ao_lado_de_outro_qr_nao_paga():
    """Sem valor embutido, só o ÚNICO código do título serve: ao lado de outro
    (mesmo de outro valor), escolher seria chutar."""
    sem, outro = brcode("LOJA A"), brcode("LOJA B", 99.0)
    reg, _ = linha([item()], {"t1": [anexo("a.png", ext=".png", url="u1"),
                                     anexo("b.png", ext=".png", url="u2")]},
                   qrs={"u1": [sem], "u2": [outro]})
    assert reg["dados"] == ""


def test_recado_no_cadastro_nao_vira_chave_ambigua_quando_o_qr_paga():
    c = brcode("CARTORIO EXEMPLO", 55.0)
    reg, _ = linha([item(conta_pix="VER COMENTARIO DA SOLICITACAO")],
                   {"t1": [anexo("guia.png", ext=".png", url="u1")]},
                   qrs={"u1": [c]})
    assert reg["dados"] == c
    assert "sem tipo declarado" not in reg["obs"]


def test_guia_que_virou_pix_continua_sem_rotulo_de_nf():
    """O número da guia não é nota, mesmo com uma NF anexada ao título: a
    linha da guia (arrecadação) segue decidindo o rótulo depois da troca."""
    v = _valor(LINHA_ARRECADACAO)
    c = brcode("MUNICIPIO DE GOIANIA", v)
    reg, _ = linha([item("PREFEITURA DE GOIANIA", valor=v, metodo="Boleto",
                         doc="998877")],
                   {"t1": [anexo("guia.pdf", tag="Boleto", url="u1"),
                           anexo("NF 998877.pdf", tag="Nota Fiscal", url="u2")]},
                   textos={"u1": LINHA_ARRECADACAO, "u2": "nota"},
                   qrs={"u1": [c]})
    assert reg["tipo"] == "Pix"
    assert "NF 998877" not in reg["descricao"]
    assert "998877" in reg["descricao"]


def test_o_modelo_poe_o_pix_do_qr_na_celula_do_pagamento():
    from pagamentos_dia import modelos_html
    fonte = "".join(str(v) for v in vars(modelos_html).values() if isinstance(v, str))
    assert "${dadosCell}${pixQrCell}" in fonte
    assert "copyText(e.pix_qr" in fonte


def test_a_janela_de_confirmacao_mostra_o_qr_curto():
    """O código inteiro alargava a coluna POR ONDE (largura medida no texto
    mais comprido) e empurrava a tabela para fora da janela."""
    from pagamentos_dia import confirmacao
    c = brcode("CARTORIO EXEMPLO", 55.0)
    assert confirmacao.por_onde("Pix", c) == (
        "PIX  copia-e-cola do QR Code — CARTORIO EXEMPLO R$ 55,00")
    assert confirmacao.por_onde("Pix", brcode("LOJA")).endswith("(sem valor no código)")
