# -*- coding: utf-8 -*-
"""Casamento pelo código de barras do boleto (dono, 08/10/2026).

Todo código aqui é SINTÉTICO (`cnab240/ferramentas/_ambiente`): fecha nos
dígitos verificadores e não aponta para título nenhum. O repositório é
público, e boleto de verdade publicado é um pedido de pagamento publicado."""
from anexar import codigo_barras, matcher
from cnab240.ferramentas._ambiente import (barcode_sintetico, boleto_sintetico,
                                           ficha_sintetica)
from pagamentos_dia import ocr_boleto


def _barras(linha):
    return ocr_boleto.codigo_de_barras(linha)


def _bancario(centavos, variante=1):
    """Linha de 47 sintética; `variante` muda o campo livre (outro boleto do
    MESMO valor), refazendo os DVs."""
    linha = boleto_sintetico(centavos)
    if variante == 1:
        return linha
    barras = barcode_sintetico(centavos)
    livre = str(variante) * 25
    base = barras[:4] + barras[5:19] + livre
    dv = str(ocr_boleto._mod11_geral(base))
    barras = base[:4] + dv + base[4:]
    c1 = barras[0:4] + barras[19:24]
    c2, c3 = barras[24:34], barras[34:44]
    linha = (c1 + str(ocr_boleto._mod10(c1)) + c2 + str(ocr_boleto._mod10(c2))
             + c3 + str(ocr_boleto._mod10(c3)) + barras[4] + barras[5:19])
    assert ocr_boleto.valida(linha)
    return linha


def _formatada(linha):
    return ocr_boleto.formatar(linha)


# ------------------------------------------------------------ leitura do texto
def test_linha_inteira_numa_linha_do_texto():
    linha = _bancario(12345)
    texto = f"Comprovante de pagamento\nLinha digitável\n{_formatada(linha)}\nValor R$ 123,45"
    assert codigo_barras.codigos_no_texto(texto) == {_barras(linha)}


def test_linha_partida_em_duas_linhas_como_no_ocr_do_print():
    linha = _formatada(_bancario(9990))
    meio = len(linha) // 2
    texto = f"Pagamento de boleto\n{linha[:meio]}\n{linha[meio:]}\nPagador"
    assert codigo_barras.codigos_no_texto(texto) == {_barras(_bancario(9990))}


def test_ficha_de_arrecadacao():
    linha = ficha_sintetica(4567)
    texto = f"Convênio\n{_formatada(linha)}"
    assert codigo_barras.codigos_no_texto(texto) == {_barras(linha)}


def test_ocr_com_letra_no_lugar_de_digito():
    linha = _formatada(_bancario(12345))
    # 0 lido como O: o mapa de confusões devolve, e o DV julga.
    sujo = linha.replace("0", "O", 3)
    assert codigo_barras.codigos_no_texto(f"x\n{sujo}\ny", ocr=True) == {
        _barras(_bancario(12345))}


def test_mapa_do_ocr_nao_vale_na_camada_de_texto():
    # Letras viram dígitos SÓ no texto de OCR: na camada de texto, um bloco de
    # assinatura em base64 virou "código" na medição de 08/10/2026.
    sujo = _formatada(_bancario(12345)).replace("0", "O", 3)
    assert codigo_barras.codigos_no_texto(f"x\n{sujo}\ny") == set()


def test_achou_numa_linha_nao_cola_linhas():
    # Degraus: achou numa linha, não procura colando vizinhas -- colar a linha
    # digitável com a de baixo deu um 2º "código" falso em 2 de 124 do Sicoob.
    # Aqui o que a colagem acharia é um código VÁLIDO (B, partido em duas
    # linhas), para o teste não depender de um falso aparecer por acaso.
    a, b = _bancario(12345), _bancario(12345, 2)
    texto = f"Linha digitável {_formatada(a)}\n{b[:20]}\n{b[20:]}"
    assert codigo_barras.codigos_no_texto(texto) == {_barras(a)}
    # Sem a linha inteira, a colagem é o degrau que acha.
    assert codigo_barras.codigos_no_texto(f"x\n{b[:20]}\n{b[20:]}") == {_barras(b)}


def test_digito_errado_nao_vira_codigo():
    linha = _bancario(12345)
    errada = linha[:12] + str((int(linha[12]) + 1) % 10) + linha[13:]
    assert codigo_barras.codigos_no_texto(f"Linha\n{errada}\n") == set()


def test_texto_sem_boleto_devolve_vazio():
    assert codigo_barras.codigos_no_texto("Pix enviado\nR$ 50,00\nID E2E 123") == set()
    assert codigo_barras.codigos_no_texto("") == set()


def test_texto_inteiro_so_vale_com_o_valor_esperado():
    # Espalhado por TRÊS linhas: só o último recurso acha, e ele exige o valor.
    linha = _bancario(12345)
    partes = [linha[:15], linha[15:31], linha[31:]]
    texto = "\n".join(["Boleto"] + partes)
    assert codigo_barras.codigos_no_texto(texto) == set()
    assert codigo_barras.codigos_no_texto(texto, {99999}) == set()
    assert codigo_barras.codigos_no_texto(texto, {12345}) == {_barras(linha)}


# ------------------------------------------------------------ casamento
def _pend(paid_id, valor, data="", barras=(), **extra):
    pe = {"paidId": paid_id, "launchId": "L-" + paid_id,
          "tradePayableId": "T-" + paid_id, "valor": valor, "valores": [valor],
          "doc": "", "desc": "", "works": [], "data": data,
          "barras": set(barras)}
    pe.update(extra)
    return pe


def _pdf(nome, barras=()):
    p = matcher.parse_pdf(nome)
    p["barras"] = set(barras)
    return p


def test_codigo_igual_fecha_certeza_entre_dois_do_mesmo_valor():
    a, b = _barras(_bancario(5000, 1)), _barras(_bancario(5000, 2))
    pend = [_pend("1", 5000, "0110", [a]), _pend("2", 5000, "0110", [b])]
    pdfs = [_pdf("50,00 - FULANO - 01-10.pdf", [b]),
            _pdf("50,00 - FULANO - 01-10 (2).pdf", [a])]
    pdfs[1]["fn"] = "50,00 - FULANO - 01-10 B.pdf"
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert {p["paidId"]: p["pdf"] for p in certezas} == {
        "1": "50,00 - FULANO - 01-10 B.pdf", "2": "50,00 - FULANO - 01-10.pdf"}
    assert all("código de barras" in p["motivo"] for p in certezas)
    assert not duvidas and not sem_par


def test_sem_codigo_o_casamento_e_o_de_sempre():
    # Dois pendentes e dois PDFs do mesmo valor e dia, ninguém com código: dúvida.
    pend = [_pend("1", 5000, "0110"), _pend("2", 5000, "0110")]
    pdfs = [_pdf("50,00 - FULANO - 01-10.pdf"), _pdf("50,00 - BELTRANO - 01-10.pdf")]
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    assert not certezas and len(duvidas) == 2


def test_codigo_diferente_vira_duvida_mesmo_com_valor_e_data_unicos():
    # Decisão do dono (08/10/2026): hoje um PDF só, de mesmo valor e data, fecha
    # CERTEZA. Com o código do título e o do comprovante DIFERENTES, não fecha.
    pend = [_pend("1", 5000, "0110", [_barras(_bancario(5000, 1))])]
    pdfs = [_pdf("50,00 - FULANO - 01-10.pdf", [_barras(_bancario(5000, 2))])]
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert not certezas and not sem_par
    assert len(duvidas) == 1
    assert duvidas[0]["cands"][0]["barras_conflito"]


def test_codigo_diferente_nao_fecha_nem_com_oc():
    pend = [_pend("1", 5000, "0110", [_barras(_bancario(5000, 1))], desc="OC 4321")]
    pdfs = [_pdf("50,00 - OBRA OC 4321 - 01-10.pdf", [_barras(_bancario(5000, 2))])]
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    assert not certezas and len(duvidas) == 1


def test_codigo_so_de_um_lado_e_neutro():
    # PDF do Inter não mostra o código; título sem boleto anexado também não.
    pend = [_pend("1", 5000, "0110", [_barras(_bancario(5000))])]
    pdfs = [_pdf("50,00 - FULANO - 01-10.pdf")]
    certezas, _, _ = matcher.casar(pend, pdfs)
    assert [p["paidId"] for p in certezas] == ["1"]
    pend = [_pend("1", 5000, "0110")]
    pdfs = [_pdf("50,00 - FULANO - 01-10.pdf", [_barras(_bancario(5000))])]
    certezas, _, _ = matcher.casar(pend, pdfs)
    assert [p["paidId"] for p in certezas] == ["1"]


def test_conflito_nao_impede_o_pdf_certo_de_outro():
    # O PDF X tem o código do pendente 2; o pendente 1 (sem código) não pode
    # levá-lo por data se o 2 o reclama pelo código.
    # O que tem código vem PRIMEIRO de propósito: sem a regra, o fim do
    # `casar` dá o PDF ao ÚLTIMO da lista (o primeiro vira dúvida e deixa de
    # ser concorrente do segundo) -- aqui, o pendente sem código.
    a = _barras(_bancario(5000, 3))
    pend = [_pend("2", 5000, "0110", [a]), _pend("1", 5000, "0110")]
    pdfs = [_pdf("50,00 - FULANO - 01-10.pdf", [a])]
    certezas, _, _ = matcher.casar(pend, pdfs)
    assert [(p["paidId"], p["pdf"]) for p in certezas] == [("2", "50,00 - FULANO - 01-10.pdf")]


def test_mesmo_codigo_em_dois_pdfs_nao_chuta():
    # Comprovante de agendamento + o da efetivação, ou o mesmo arquivo duas vezes.
    a = _barras(_bancario(5000))
    pend = [_pend("1", 5000, "0110", [a])]
    pdfs = [_pdf("50,00 - FULANO - 01-10.pdf", [a]),
            _pdf("50,00 - FULANO - 02-10.pdf", [a])]
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    assert [p["paidId"] for p in certezas] == ["1"]          # a data desempata
    pdfs = [_pdf("50,00 - FULANO - 01-10.pdf", [a]),
            _pdf("50,00 - BELTRANO - 01-10.pdf", [a])]
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    assert not certezas and len(duvidas) == 1


def test_pendentes_sem_chave_barras_continuam_funcionando():
    # Quem chama o matcher sem passar pelo `preencher` (modo antigo, testes).
    pe = _pend("1", 5000, "0110"); del pe["barras"]
    pd = matcher.parse_pdf("50,00 - FULANO - 01-10.pdf")
    certezas, _, _ = matcher.casar([pe], [pd])
    assert [p["paidId"] for p in certezas] == ["1"]


# ------------------------------------------------------------ preencher
def test_preencher_le_so_o_que_pode_mudar_um_casamento():
    a = _bancario(5000)
    pend = [_pend("1", 5000), _pend("2", 7000)]
    pend[0]["barras"] = set(); pend[1]["barras"] = set()
    pdfs = [_pdf("50,00 - FULANO - 01-10.pdf"), _pdf("70,00 - PIX - 01-10.pdf"),
            _pdf("99,00 - OUTRO - 01-10.pdf")]
    textos = {pdfs[0]["fn"]: _formatada(a), pdfs[1]["fn"]: "Pix", pdfs[2]["fn"]: _formatada(a)}
    lidos_pdf, pedidos, baixados = [], [], []

    def ler_pdf(pd):
        lidos_pdf.append(pd["fn"]); return textos[pd["fn"]], False

    def anexos_de(ids):
        pedidos.append(list(ids))
        return {"T-1": [{"filename": "boleto.pdf", "downloadUrl": "u1"},
                        {"filename": "planilha.xlsx", "downloadUrl": "u2"}]}

    def baixar(url):
        baixados.append(url); return b"%PDF"

    n = codigo_barras.preencher(pend, pdfs, ler_pdf=ler_pdf, anexos_de=anexos_de,
                                baixar=baixar, ler_anexo=lambda nome, d: (_formatada(a), False))
    assert "99,00 - OUTRO - 01-10.pdf" not in lidos_pdf      # valor de ninguém
    assert pedidos == [["T-1"]]                               # o 2 só tem Pix
    assert baixados == ["u1"]                                 # xlsx não se lê
    assert pend[0]["barras"] == {_barras(a)} and pend[1]["barras"] == set()
    assert n["lancamentos_com_codigo"] == 1 and n["pdfs_com_codigo"] == 1


def test_preencher_descarta_boleto_de_outra_parcela_do_titulo():
    # Título parcelado: o boleto das DUAS parcelas mora no mesmo título.
    esta, vizinha = _bancario(5000), _bancario(6000)
    pend = [_pend("1", 5000)]
    pdfs = [_pdf("50,00 - FULANO - 01-10.pdf")]
    codigo_barras.preencher(
        pend, pdfs, ler_pdf=lambda pd: (_formatada(esta), False),
        anexos_de=lambda ids: {"T-1": [{"filename": "p1.pdf", "downloadUrl": "a"},
                                       {"filename": "p2.pdf", "downloadUrl": "b"}]},
        baixar=lambda url: url.encode(),
        ler_anexo=lambda nome, d: (_formatada(esta if d == b"a" else vizinha), False))
    assert pend[0]["barras"] == {_barras(esta)}


def test_preencher_sem_codigo_nos_pdfs_nem_consulta_o_erp():
    pend = [_pend("1", 5000)]
    pdfs = [_pdf("50,00 - FULANO - 01-10.pdf")]

    def anexos_de(ids):
        raise AssertionError("não devia consultar o ERP")

    codigo_barras.preencher(pend, pdfs, ler_pdf=lambda pd: ("Pix", False),
                            anexos_de=anexos_de,
                            baixar=None)
    assert pend[0]["barras"] == set() and pdfs[0]["barras"] == set()


def test_preencher_conta_quem_ficou_sem_o_titulo():
    pend = [_pend("1", 5000)]
    del pend[0]["tradePayableId"]
    pdfs = [_pdf("50,00 - FULANO - 01-10.pdf")]
    n = codigo_barras.preencher(
        pend, pdfs, ler_pdf=lambda pd: (_formatada(_bancario(5000)), False),
        anexos_de=lambda ids: {}, baixar=None)
    assert n["sem_titulo"] == 1 and pend[0]["barras"] == set()


def test_nome_do_anexo_com_extensao_separada():
    assert codigo_barras._nome_do_anexo({"filename": "boleto", "extension": ".PDF"}) == "boleto.pdf"
    assert codigo_barras._nome_do_anexo({"filename": "b.pdf", "extension": "pdf"}) == "b.pdf"


def test_valor_das_barras_bate_com_o_da_linha():
    for linha in (_bancario(12345), ficha_sintetica(4567)):
        assert codigo_barras._valor_das_barras(_barras(linha)) == round(
            ocr_boleto.valor_da_linha(linha) * 100)


# ------------------------------------------------------------ ligação no Anexar
def test_montar_pagos_guarda_o_titulo_onde_mora_o_boleto():
    from anexar import mc_api
    pagos = mc_api.montar_pagos([{"id": "P1", "tradePayableId": "T9",
                                  "paids": [{"id": "S1", "value": 50.0,
                                             "paidValue": 50.0,
                                             "payingDate": "2026-10-01"}]}])
    assert pagos[0]["tradePayableId"] == "T9" and pagos[0]["launchId"] == "P1"


def test_sinais_mostram_o_codigo_e_o_conflito():
    from anexar import anexar_comprovantes as ac
    assert ac._sinais({"barras": True, "date": True}) == ["código de barras", "data"]
    assert ac._sinais({"barras_conflito": True, "date": True, "conta": True}) == [
        "código de barras DIFERENTE", "conta", "data"]


def test_falha_na_leitura_deixa_o_casamento_como_antes():
    import threading
    from types import SimpleNamespace
    from anexar import anexar_comprovantes as ac

    class ApiQuebrada:
        def anexos_de_titulos(self, *a, **k):
            raise RuntimeError("ERP fora")

    log = []
    falso = SimpleNamespace(_parar=threading.Event(), _log=log.append,
                            _checar_pausa=lambda: False, api=ApiQuebrada())
    pend = [_pend("1", 5000, "0110")]
    pdfs = [_pdf("50,00 - FULANO - 01-10.pdf")]
    ler = codigo_barras.texto_do_arquivo
    codigo_barras.texto_do_arquivo = lambda nome, dados: (_formatada(_bancario(5000)), False)
    try:
        ac.AnexarFrame._ler_codigos_de_barras(falso, pend, pdfs, _PASTA_FALSA)
    finally:
        codigo_barras.texto_do_arquivo = ler
    assert any("[aviso]" in m for m in log)
    assert pend[0]["barras"] == set() and pdfs[0]["barras"] == set()
    certezas, _, _ = matcher.casar(pend, pdfs)
    assert [p["paidId"] for p in certezas] == ["1"]


class _PastaFalsa:
    """`pasta / nome` devolve um arquivo que se lê sem tocar no disco."""
    def __truediv__(self, nome):
        return _ArquivoFalso()


class _ArquivoFalso:
    def read_bytes(self):
        return b"%PDF"


_PASTA_FALSA = _PastaFalsa()


# ------------------------------------------------------------ revisão do 916959b
def test_parcela_vizinha_de_mesmo_valor_nao_fecha_pelo_codigo():
    # Achado 1: o título guarda o boleto da parcela 1 (mesmo valor); a parcela
    # 2 está pendente, o comprovante dela não tem código, e o da parcela 1
    # (pago no mês anterior) ainda está na pasta. Antes fechava pela data.
    c1 = _barras(_bancario(100000, 1))
    pend = [_pend("2", 100000, "0110", [c1])]
    pdfs = [_pdf("1.000,00 - ALUGUEL - 01-09.pdf", [c1]),
            _pdf("1.000,00 - ALUGUEL - 01-10.pdf")]
    certezas, _, _ = matcher.casar(pend, pdfs)
    assert [p["pdf"] for p in certezas] == ["1.000,00 - ALUGUEL - 01-10.pdf"]


def test_preencher_ignora_comprovante_anexado_no_titulo():
    # Mesma família do achado 1: comprovante de parcela anterior anexado no
    # TÍTULO não é boleto desta parcela.
    pago, este = _bancario(5000, 1), _bancario(5000, 2)
    pend = [_pend("1", 5000)]
    pdfs = [_pdf("50,00 - FULANO - 01-10.pdf")]
    anexos = {"T-1": [{"filename": "pgto.pdf", "tagName": "Comprovante", "downloadUrl": "a"},
                      {"filename": "Comprovante setembro.pdf", "downloadUrl": "b"},
                      {"filename": "boleto.pdf", "downloadUrl": "c"}]}
    codigo_barras.preencher(
        pend, pdfs, ler_pdf=lambda pd: (_formatada(este), False),
        anexos_de=lambda ids: anexos, baixar=lambda url: url.encode(),
        ler_anexo=lambda nome, d: (_formatada(este if d == b"c" else pago), False))
    assert pend[0]["barras"] == {_barras(este)}


def test_veto_nao_entrega_o_lancamento_ao_rival_sem_codigo():
    # Achado 2: o comprovante certo (obra e data batem) tem código diferente do
    # boleto anexado (2ª via); um Pix da mesma obra e valor, de outro dia, não
    # pode fechar por eliminação. Tem de ser dúvida.
    pend = [_pend("1", 5000, "0110", [_barras(_bancario(5000, 1))],
                  works=["OBRA EXEMPLO NORTE"])]
    pdfs = [_pdf("50,00 - OBRA EXEMPLO NORTE - 01-10.pdf", [_barras(_bancario(5000, 2))]),
            _pdf("50,00 - OBRA EXEMPLO NORTE PIX - 03-10.pdf")]
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    assert not certezas and [p["paidId"] for p in duvidas] == ["1"]


def test_segunda_copia_do_comprovante_nao_vai_para_outro_lancamento():
    # Achado 3: agendamento + efetivação com o MESMO código. O 1 leva a
    # efetivação pelo código; a cópia do agendamento é do título do 1 e não
    # pode fechar o 2 (mesmo valor, sem código) por data -- o código prova que
    # ela não é dele, então ela nem é candidata do 2.
    a = _barras(_bancario(5000))
    pend = [_pend("1", 5000, "0110", [a]), _pend("2", 5000, "3009")]
    pdfs = [_pdf("50,00 - FULANO - 01-10.pdf", [a]),
            _pdf("50,00 - FULANO AGENDADO - 30-09.pdf", [a])]
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert [(p["paidId"], p["pdf"]) for p in certezas] == [("1", "50,00 - FULANO - 01-10.pdf")]
    assert [p["paidId"] for p in sem_par] == ["2"]
    assert "outro título" in sem_par[0]["motivo_sem_par"]


def test_lancamento_travado_continua_disputando_os_pdfs():
    # 2ª revisão, bloqueio: o 1 tem um candidato em conflito e não fecha; se
    # ele sumisse da disputa, o 2 levaria A pelo centro de custo -- mas A pode
    # ser justamente o comprovante do 1. Antes do código, os dois eram dúvida.
    obra = ["RESIDENCIAL EXEMPLO"]
    pend = [_pend("1", 5000, "0110", [_barras(_bancario(5000, 1))], works=obra),
            _pend("2", 5000, "0110", works=obra)]
    pdfs = [_pdf("50,00 - RESIDENCIAL EXEMPLO BOLETO - 30-09.pdf",
                 [_barras(_bancario(5000, 9))]),
            _pdf("50,00 - RESIDENCIAL EXEMPLO - 01-10.pdf")]
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    assert not certezas and len(duvidas) == 2


def test_pdf_de_outro_titulo_nao_prende_quem_fechava_sem_codigo():
    # 2ª revisão, ajuste: o PDF da parcela anterior do título do 1 (c1) sobra
    # na pasta; o 3 (outro título, sem código) tem o próprio PDF na data dele
    # e fechava certo antes. O PDF de c1 não é do 3 -- sai, não prende.
    c1, c2 = _barras(_bancario(5000, 1)), _barras(_bancario(5000, 2))
    pend = [_pend("1", 5000, "0110", [c1, c2]), _pend("3", 5000, "0510")]
    pdfs = [_pdf("50,00 - PARCELA - 01-10.pdf", [c2]),
            _pdf("50,00 - PARCELA - 01-09.pdf", [c1]),
            _pdf("50,00 - OUTRO - 05-10.pdf")]
    certezas, _, _ = matcher.casar(pend, pdfs)
    assert {p["paidId"]: p["pdf"] for p in certezas} == {
        "1": "50,00 - PARCELA - 01-10.pdf", "3": "50,00 - OUTRO - 05-10.pdf"}


def test_motivo_so_cita_o_codigo_quando_ele_decidiu():
    # O PDF da parcela anterior tem o código do título, mas fecha por outra
    # regra (centro de custo): o motivo não pode dizer "código de barras".
    c1 = _barras(_bancario(5000, 1))
    pend = [_pend("2", 5000, "0110", [c1], works=["RESIDENCIAL EXEMPLO"])]
    pdfs = [_pdf("50,00 - RESIDENCIAL EXEMPLO - 01-09.pdf", [c1])]
    certezas, _, _ = matcher.casar(pend, pdfs)
    assert len(certezas) == 1 and "código de barras" not in certezas[0]["motivo"]


def test_dois_pendentes_e_um_pdf_so_pela_data_e_duvida_em_qualquer_ordem():
    # Achado 5 (anterior a este PR): o 1º virava dúvida e deixava de ser
    # concorrente do 2º, que fechava pela data -- a ORDEM decidia o anexo.
    for ordem in (("1", "2"), ("2", "1")):
        pend = [_pend(i, 5000, "0110") for i in ordem]
        pdfs = [_pdf("50,00 - FULANO - 01-10.pdf")]
        certezas, duvidas, _ = matcher.casar(pend, pdfs)
        assert not certezas and len(duvidas) == 2, ordem


def test_resumo_da_duvida_conta_os_pdfs_de_outro_titulo():
    from anexar import anexar_comprovantes as ac
    pe = {"cands": [], "de_outro_titulo": 2}
    assert "2 PDF(s) de mesmo valor com o código de barras de outro título" in (
        ac._resumo_cands(pe))


def test_sinais_do_conflito_mostram_o_resto_tambem():
    from anexar import anexar_comprovantes as ac
    assert ac._sinais({"barras_conflito": True, "date": True, "cc": True}) == [
        "código de barras DIFERENTE", "centro de custo", "data"]
