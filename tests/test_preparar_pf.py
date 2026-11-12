# -*- coding: utf-8 -*-
"""Comprovantes de conta de pessoa física (fotos do PagBank, do Neon, PDF do Next).

O que se prova aqui, com textos inventados no formato que o OCR devolve:
- a leitura de valor, data, quem pagou, quem recebeu e banco nos três modelos;
- a pasta: a foto vira PDF no padrão do `matcher`, o original fica, repetido
  não vira dois e o `origem` passa a saber de que conta saiu;
- o casamento com a conta PF: mesmo valor em outra conta PF ou em outro dia
  não é mais dúvida; dois boletos iguais na mesma conta continuam dúvida; o
  Pix que sobra ao lado de um boleto casado pelo código fecha.
Tudo fictício: nomes, valores e códigos inventados.
"""
import json

from PIL import Image

from anexar import matcher, origem, preparar_pf

PIX_PAGBANK = """PagBank
Comprovante de transferência
06/11/2026 às 19:25
Valor da transferência
R$ 565,00
De
FULANO DE TAL EXEMPLO
Para
BELTRANO FORNECEDOR EXEMPLO
Código de transação E12345678202611061925abcdefghijklmnop
4003-1775""".splitlines()

BOLETO_NEON = """neon
Comprovante de transação
Tipo
Boleto
Valor
R$ 450,00
Pago em
10/11/2026 às 15:16
Nome da cobrança
CONTAINERS EXEMPLO LTDA
Pago por
Nome
CICLANO DA SILVA EXEMPLO""".splitlines()

PIX_NEON = """neon
Pix enviado
R$ 3.586,71
Ocorreu em
11 de novembro de 2026 às 11:26
Quem pagou
Nome
CICLANO DA SILVA EXEMPLO
Quem recebeu
Nome
CARTORIO EXEMPLO""".splitlines()


def test_le_pix_do_pagbank():
    c = preparar_pf.ler(PIX_PAGBANK)
    assert c["valor"] == 56500 and c["data"] == "06-11" and c["hora"] == "19h25"
    assert c["banco"] == "PAGBANK"
    assert c["pagador"] == "FULANO DE TAL EXEMPLO"
    assert c["recebedor"] == "BELTRANO FORNECEDOR EXEMPLO"
    assert c["id"].startswith("E12345678")


def test_le_boleto_do_neon_pela_cobranca_e_pelo_pago_por():
    c = preparar_pf.ler(BOLETO_NEON)
    assert c["valor"] == 45000 and c["data"] == "10-11"
    assert c["banco"] == "NEON"
    assert c["recebedor"] == "CONTAINERS EXEMPLO LTDA"
    assert c["pagador"] == "CICLANO DA SILVA EXEMPLO"


def test_le_pix_do_neon_com_data_por_extenso():
    c = preparar_pf.ler(PIX_NEON)
    assert c["valor"] == 358671 and c["data"] == "11-11" and c["hora"] == "11h26"
    assert c["pagador"] == "CICLANO DA SILVA EXEMPLO"
    assert c["recebedor"] == "CARTORIO EXEMPLO"


# ------------------------------------------------------------------ a pasta
def _foto(pasta, nome, cor=(255, 255, 255)):
    Image.new("RGB", (40, 40), cor).save(pasta / nome)


def _ocr_de(textos):
    """OCR de mentira: devolve o texto pela cor da foto (cada foto tem a sua)."""
    def ocr(img):
        return textos[img.convert("RGB").getpixel((0, 0))], "teste"
    return ocr


def test_foto_vira_pdf_no_padrao_e_o_original_fica(tmp_path):
    _foto(tmp_path, "my_account_receipt_to_share.jpg", (1, 1, 1))
    _foto(tmp_path, "IMG_Comprovante_Neon_1.png", (2, 2, 2))
    n = preparar_pf.preparar(tmp_path, log=lambda *_: None,
                             ocr=_ocr_de({(1, 1, 1): PIX_PAGBANK, (2, 2, 2): BOLETO_NEON}))
    assert n["gerados"] == 2
    nomes = sorted(p.name for p in tmp_path.iterdir())
    assert "565,00 - Beltrano Fornecedor Exemplo - 06-11.pdf" in nomes
    assert "450,00 - Containers Exemplo Ltda - 10-11.pdf" in nomes
    assert "my_account_receipt_to_share.jpg" in nomes, "o original não se apaga"
    pdfs = matcher.carregar_pdfs(tmp_path, log=lambda *_: None)
    assert {p["valor"] for p in pdfs} == {56500, 45000}
    # De que conta saiu: banco + quem pagou.
    org = origem.origens_dos_pdfs(tmp_path)
    assert org["565,00 - Beltrano Fornecedor Exemplo - 06-11.pdf"]["origem"] == (
        "PAGBANK", "FULANO DE TAL EXEMPLO")


def test_mesmo_comprovante_reenviado_vira_um_pdf_so(tmp_path):
    _foto(tmp_path, "a.jpg", (1, 1, 1))
    _foto(tmp_path, "b.jpg", (3, 3, 3))       # outros bytes, mesma transação (E...)
    n = preparar_pf.preparar(tmp_path, log=lambda *_: None,
                             ocr=_ocr_de({(1, 1, 1): PIX_PAGBANK, (3, 3, 3): PIX_PAGBANK}))
    assert n["gerados"] == 1 and n["repetidos"] == 1
    # E rodar de novo não gera outro.
    n2 = preparar_pf.preparar(tmp_path, log=lambda *_: None,
                              ocr=_ocr_de({(1, 1, 1): PIX_PAGBANK, (3, 3, 3): PIX_PAGBANK}))
    assert n2["gerados"] == 0
    assert len(json.loads((tmp_path / preparar_pf.ARQUIVO).read_text(encoding="utf-8"))) == 1


def test_sem_valor_fica_de_fora_com_aviso(tmp_path):
    _foto(tmp_path, "x.jpg", (4, 4, 4))
    avisos = []
    n = preparar_pf.preparar(tmp_path, log=avisos.append,
                             ocr=_ocr_de({(4, 4, 4): ["PagBank", "foto borrada"]}))
    assert n["gerados"] == 0 and n["ilegiveis"] == 1
    assert any("não achei o valor" in a for a in avisos)


def test_conta_pf_do_erp_pela_pessoa():
    assert origem.origem_pf_da_conta("FULANO - PAGBANK") == ("PAGBANK", "FULANO")
    assert origem.origem_pf_da_conta("CICLANO - NEON") == ("NEON", "CICLANO")
    assert origem.origem_pf_da_conta("BELTRANA NEXT") == ("NEXT", "BELTRANA")
    assert origem.origem_pf_da_conta("EMPRESA EXEMPLO - SICOOB") is None


def test_nome_curto_da_conta_dentro_do_nome_inteiro_de_quem_pagou():
    assert matcher.mesma_conta(("PAGBANK", "FULANO"), ("PAGBANK", "FULANO DE TAL EXEMPLO"))
    assert matcher.mesma_conta(("PAGBANK", "FULANO"), ("PAGBANK", "BELTRANO EXEMPLO")) is False
    assert matcher.mesma_conta(("PAGBANK", "FULANO"), ("NEON", "FULANO")) is False


# ------------------------------------------------------------- o casamento
def _pdf(nome, org, barras=()):
    p = matcher.parse_pdf(nome)
    p["origem"], p["recebedor"], p["barras"] = org, None, set(barras)
    return p


def _pend(pid, valor, data, org, barras=()):
    return {"paidId": pid, "launchId": "L" + pid, "valor": valor, "valores": [valor],
            "doc": "", "desc": "", "works": [], "data": data, "origem": org,
            "favorecido": "", "barras": set(barras)}


FULANO = ("PAGBANK", "FULANO")
CICLANO = ("NEON", "CICLANO")
PAG_FULANO = ("PAGBANK", "FULANO DE TAL")
NEON_CICLANO = ("NEON", "CICLANO DA SILVA")


def test_mesmo_valor_em_outra_conta_pf_nao_e_mais_duvida():
    pdfs = [_pdf("139,93 - CARTORIO - 09-11.pdf", PAG_FULANO),
            _pdf("139,93 - CARTORIO - 11-11.pdf", NEON_CICLANO)]
    pend = [_pend("A", 13993, "0911", FULANO), _pend("B", 13993, "1111", CICLANO)]
    cert, duv, _ = matcher.casar(pend, pdfs)
    assert not duv and {c["paidId"]: c["pdf"] for c in cert} == {
        "A": "139,93 - CARTORIO - 09-11.pdf", "B": "139,93 - CARTORIO - 11-11.pdf"}
    assert all("conta" in c["motivo"] for c in cert)


def test_mesmo_valor_em_dias_diferentes_da_mesma_conta():
    pdfs = [_pdf(f"300,00 - ELETRICISTA - {d}-11.pdf", NEON_CICLANO) for d in ("10", "11")]
    pend = [_pend("A", 30000, "1011", CICLANO), _pend("B", 30000, "1111", CICLANO)]
    cert, duv, _ = matcher.casar(pend, pdfs)
    assert not duv and len(cert) == 2


def test_dois_boletos_iguais_na_mesma_conta_e_dia_continuam_duvida():
    pdfs = [_pdf("58,38 - ENERGIA - 09-11.pdf", PAG_FULANO),
            _pdf("58,38 - ENERGIA - 09-11 (2).pdf", PAG_FULANO)]
    pend = [_pend("A", 5838, "0911", FULANO), _pend("B", 5838, "0911", FULANO)]
    cert, duv, _ = matcher.casar(pend, pdfs)
    assert not cert and len(duv) == 2


def test_codigo_de_barras_separa_os_iguais():
    c1, c2 = "1" * 44, "2" * 44
    pdfs = [_pdf("58,38 - ENERGIA - 09-11.pdf", PAG_FULANO, [c2]),
            _pdf("58,38 - ENERGIA - 09-11 (2).pdf", PAG_FULANO, [c1])]
    pend = [_pend("A", 5838, "0911", FULANO, [c1]), _pend("B", 5838, "0911", FULANO, [c2])]
    cert, duv, _ = matcher.casar(pend, pdfs)
    assert not duv and {c["paidId"]: c["pdf"] for c in cert} == {
        "A": "58,38 - ENERGIA - 09-11 (2).pdf", "B": "58,38 - ENERGIA - 09-11.pdf"}


def test_pix_que_sobra_ao_lado_do_boleto_casado_fecha():
    cod = "3" * 44
    pdfs = [_pdf("450,00 - CONTAINERS - 10-11.pdf", NEON_CICLANO, [cod]),
            _pdf("450,00 - REEMBOLSO - 10-11.pdf", NEON_CICLANO)]
    pend = [_pend("BOLETO", 45000, "1011", CICLANO, [cod]), _pend("PIX", 45000, "1011", CICLANO)]
    cert, duv, _ = matcher.casar(pend, pdfs)
    assert not duv and {c["paidId"]: c["pdf"] for c in cert} == {
        "BOLETO": "450,00 - CONTAINERS - 10-11.pdf", "PIX": "450,00 - REEMBOLSO - 10-11.pdf"}


def test_sem_o_codigo_o_boleto_e_o_pix_iguais_continuam_duvida():
    pdfs = [_pdf("450,00 - CONTAINERS - 10-11.pdf", NEON_CICLANO),
            _pdf("450,00 - REEMBOLSO - 10-11.pdf", NEON_CICLANO)]
    pend = [_pend("BOLETO", 45000, "1011", CICLANO), _pend("PIX", 45000, "1011", CICLANO)]
    cert, duv, _ = matcher.casar(pend, pdfs)
    assert not cert and len(duv) == 2


def test_comprovante_de_outra_pessoa_pf_nao_disputa():
    pdfs = [_pdf("100,00 - X - 10-11.pdf", ("PAGBANK", "BELTRANO EXEMPLO"))]
    pend = [_pend("A", 10000, "1011", FULANO)]
    cert, duv, sem = matcher.casar(pend, pdfs)
    assert not cert and not duv and len(sem) == 1


BOLETO_PAGBANK = """PagBank
Comprovante de pagamento
09/11/2026 às 18:47
Valor do pagamento
R$ 58,38
Beneficiário
ENERGIA EXEMPLO SA
Pagador
CLIENTE DA CONTA DE LUZ EXEMPLO
Pagador Final
FULANO DE TAL EXEMPLO
4003-1775""".splitlines()

PIX_NEXT = """Comprovante de transação Pix
Data da operação: 09/11/2026 19:00:02
Dados do pagador
Nome: BELTRANA EXEMPLO
Instituição: Next (237 - Banco Exemplo)
Dados do recebedor
CARTORIO EXEMPLO
Nome:
Dados do pagamento
Valor: 139.93
Id da transação: E60746948202611092159abcdefghij""".splitlines()

BOLETO_NEXT = """Comprovante de Transação Bancária
Data da operação::09/11/2026
Banco de origem: next (237 - Banco Exemplo)
Conta de débito: Agência: 0000 | Conta: 0000-0
Nome: BELTRANA EXEMPLO
Razão social: CONTABILIDADE EXEMPLO LTDA
Nome pagador: OUTRA PESSOA EXEMPLO
Valor: R$ 4.070,97""".splitlines()


def test_no_boleto_o_pagador_e_o_titular_e_nao_quem_pagou():
    # Medido em 12/11/2026: ler "Pagador" apontava outra conta em 29 comprovantes.
    c = preparar_pf.ler(BOLETO_PAGBANK)
    assert c["pagador"] == "FULANO DE TAL EXEMPLO"
    assert c["recebedor"] == "ENERGIA EXEMPLO SA"


def test_le_pix_do_next_com_valor_no_formato_americano():
    c = preparar_pf.ler(PIX_NEXT)
    assert c["valor"] == 13993 and c["data"] == "09-11" and c["banco"] == "NEXT"
    assert c["pagador"] == "BELTRANA EXEMPLO"
    assert c["recebedor"] == "CARTORIO EXEMPLO"


def test_le_boleto_do_next_pela_conta_de_debito():
    c = preparar_pf.ler(BOLETO_NEXT)
    assert c["valor"] == 407097 and c["banco"] == "NEXT"
    assert c["pagador"] == "BELTRANA EXEMPLO", "o 'Nome pagador' do boleto é o titular"
    assert c["recebedor"] == "CONTABILIDADE EXEMPLO LTDA"


def test_boleto_reenviado_com_o_mesmo_codigo_vira_um_so(tmp_path):
    _foto(tmp_path, "a.jpg", (5, 5, 5))
    _foto(tmp_path, "b.jpg", (6, 6, 6))
    cod = "8" * 44
    n = preparar_pf.preparar(tmp_path, log=lambda *_: None,
                             ocr=_ocr_de({(5, 5, 5): BOLETO_PAGBANK, (6, 6, 6): BOLETO_PAGBANK}),
                             codigos=lambda t, v, o: {cod})
    assert n["gerados"] == 1 and n["repetidos"] == 1


def test_dois_boletos_iguais_sem_codigo_nao_se_juntam(tmp_path):
    _foto(tmp_path, "a.jpg", (5, 5, 5))
    _foto(tmp_path, "b.jpg", (6, 6, 6))
    n = preparar_pf.preparar(tmp_path, log=lambda *_: None,
                             ocr=_ocr_de({(5, 5, 5): BOLETO_PAGBANK, (6, 6, 6): BOLETO_PAGBANK}))
    assert n["gerados"] == 2


def test_vencimento_antes_do_pagamento_sai_a_data_do_pagamento():
    # Revisão do PR #176: com a regra "conta e data", a data do vencimento
    # fecharia com OUTRO pagamento de mesmo valor em outro dia.
    linhas = """PagBank
Comprovante de pagamento
Data de vencimento
05/11/2026
Valor do pagamento
R$ 58,38
Solicitado em: 09/11/2026 às 18:47
Pagador Final
FULANO DE TAL EXEMPLO""".splitlines()
    c = preparar_pf.ler(linhas)
    assert (c["data"], c["hora"]) == ("09-11", "18h47")


def test_vencimento_na_mesma_linha_nunca_vira_a_data():
    c = preparar_pf.ler(["Neon", "Vencimento: 05/11/2026", "Valor R$ 10,00",
                         "Pago em", "10/11/2026 às 15:16"])
    assert c["data"] == "10-11"


def test_sem_rotulo_vale_a_primeira_data():
    c = preparar_pf.ler(["PagBank", "R$ 10,00", "07/11/2026 12:00", "08/11/2026"])
    assert c["data"] == "07-11"
