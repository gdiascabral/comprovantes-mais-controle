# -*- coding: utf-8 -*-
"""As regras do dono de 14/10/2026 nos pagamentos do dia.

1. **Sem anexo, sem pagamento**: título sem arquivo nenhum não entra na
   planilha nem no HTML — vai para NÃO ENTRARAM com o motivo, mesmo com
   chave Pix no cadastro.
2. **Fornecedor que emite por dois CNPJs** (`cnpj_livre` no
   `regras_fornecedor.json`): o aviso "CNPJ da nota diferente do cadastro"
   não aparece para ele.
3. **A chave Pix da observação paga o título sem boleto** quando há OC/NF
   ("PAGAR PARA <empresa> PIX: <cnpj>", o título desmembrado), em ATENÇÃO.
4. **A pergunta do HTML** ("incluir reembolso para …?"): "não" tira dos dois
   HTMLs os reembolsos das pessoas do `confirmar_antes.json`.
5. **QR estilizado** (módulos pequenos, sem margem): o leitor tenta de novo
   ampliando e binarizando.

Nenhum dado real: nomes, chaves e valores inventados. O repo é público.
"""
import io
import sys
import types

from pagamentos_dia import html_pagamentos, qr_pix
from pagamentos_dia import regras_pagamento as regras
from pagamentos_dia import relatorio

#: CNPJs fictícios com DV válido.
CNPJ_CADASTRO = "11222333000181"
CNPJ_OUTRA_EMPRESA = "11444777000161"


def _lanc(ident="L1", favorecido="Fornecedor Modelo Ltda", valor=100.0, **extra):
    item = {"id": ident, "tradePayableId": f"T-{ident}", "paidTo": favorecido,
            "remainingValue": valor, "plannedDate": "2026-10-14",
            "tradePayableAccount": {"name": "CONTA EXEMPLO - SICOOB"},
            "tradePayablePaymentMethod": "Pix",
            "paidToBankAccount": "PIX EMAIL fornecedor@exemplo.com",
            "documentNumber": "1234",
            "costCentreDetails": [{"workName": "OBRA MODELO"}],
            "paid": False}
    item.update(extra)
    return item


def _anexo(nome, tag=None, ext=".pdf", url=None):
    return {"filename": nome, "tagName": tag, "extension": ext,
            "downloadUrl": url or f"https://exemplo.invalid/{nome}"}


def _linhas(res):
    return [x for regs in res.contas.values() for x in regs]


# ==========================================================================
# 1. Sem anexo, sem pagamento
# ==========================================================================
def test_titulo_sem_anexo_nao_entra_mesmo_com_chave_no_cadastro():
    res = relatorio.montar_registros([_lanc()], {}, {}, {})
    assert res.contas == {}
    o, = res.omitidos
    assert o["motivo"] == regras.MOTIVO_SEM_ANEXO
    assert o["id"] == "L1"


def test_titulo_com_anexo_continua_entrando_pela_chave():
    anexos = {"T-L1": [_anexo("nota 1234", "Nota Fiscal")]}
    res = relatorio.montar_registros([_lanc()], anexos, {}, {})
    assert res.omitidos == []
    assert _linhas(res)[0]["dados"] == "fornecedor@exemplo.com"


def test_ja_pago_sem_anexo_nao_vira_omitido():
    """Já pago é informação: as regras de omissão não valem ali."""
    res = relatorio.montar_registros(
        [_lanc(paid=True, sumOfPaidValues=100.0, remainingValue=0.0)], {}, {}, {})
    assert res.omitidos == []


# ==========================================================================
# 2. cnpj_livre
# ==========================================================================
def _nota_de_outro_cnpj(regras_forn):
    item = _lanc(favorecido="Atacado Exemplo Ltda",
                 paidToBankAccount=f"PIX CNPJ {CNPJ_CADASTRO}")
    anexos = {"T-L1": [_anexo("nota 1234", "Nota Fiscal", url="u-nota")]}
    textos = {"u-nota": ("DANFE NOTA FISCAL ELETRONICA EMITENTE ATACADO "
                         f"EXEMPLO CNPJ {CNPJ_OUTRA_EMPRESA[:2]}."
                         f"{CNPJ_OUTRA_EMPRESA[2:5]}.{CNPJ_OUTRA_EMPRESA[5:8]}/"
                         f"{CNPJ_OUTRA_EMPRESA[8:12]}-{CNPJ_OUTRA_EMPRESA[12:]} "
                         "VALOR TOTAL 100,00")}
    participantes = {"ATACADO EXEMPLO LTDA": CNPJ_CADASTRO}
    return relatorio.montar_registros([item], anexos, {}, textos,
                                      regras_fornecedor=regras_forn,
                                      participantes=participantes)


def test_sem_a_regra_o_cnpj_diferente_alarma():
    linha, = _linhas(_nota_de_outro_cnpj({}))
    assert "CNPJ" in linha["status"] or "CNPJ DIVERGE" in linha["conferencia"]


def test_cnpj_livre_tira_o_aviso_do_cnpj():
    linha, = _linhas(_nota_de_outro_cnpj({"ATACADO EXEMPLO": {"cnpj_livre": True}}))
    assert "CNPJ" not in linha["status"]
    assert "CNPJ DIVERGE" not in linha["conferencia"]
    assert "CNPJ DIVERGE" not in linha["obs"]


def test_cnpj_livre_vem_do_cadastro_por_pedaco_do_nome():
    forn = {"ATACADO EXEMPLO": {"cnpj_livre": True}}
    assert regras.cnpj_livre("Atacado Exemplo Ltda", forn)
    assert not regras.cnpj_livre("Outro Fornecedor", forn)


# ==========================================================================
# 3. A chave da observação
# ==========================================================================
def test_titulo_de_boleto_sem_boleto_paga_pela_chave_da_observacao():
    item = _lanc(tradePayablePaymentMethod="Boleto", paidToBankAccount=None)
    overview = {"comment": "PAGAR PARA EMPRESA EXEMPLO PIX: 11.222.333/0001-81",
                "purchaseOrder": {"number": "4321"}}
    # Dois PDFs sem rótulo (o pedido e o comprovante do cartão), como no
    # título real: nenhum dos dois se anuncia boleto.
    anexos = {"T-L1": [_anexo("PEDIDO"), _anexo("CARTAO"),
                       _anexo("aviso", ext=".jpg")]}
    res = relatorio.montar_registros([item], anexos, {"L1": overview}, {})
    linha, = _linhas(res)
    assert linha["tipo"] == "Pix"
    assert linha["dados"] == "11.222.333/0001-81"
    assert linha["status"] == "ATENÇÃO — pagar à mão"
    assert linha["reembolso_para"] == "EMPRESA EXEMPLO"


def test_sem_oc_nem_nf_a_chave_da_observacao_nao_basta():
    item = _lanc(tradePayablePaymentMethod="Boleto", paidToBankAccount=None,
                 documentNumber="")
    overview = {"comment": "PAGAR PARA EMPRESA EXEMPLO PIX: 11.222.333/0001-81"}
    anexos = {"T-L1": [_anexo("PEDIDO"), _anexo("outro")]}
    res = relatorio.montar_registros([item], anexos, {"L1": overview}, {})
    assert res.contas == {}


def test_quem_a_observacao_manda_pagar():
    q = relatorio.quem_a_observacao_manda_pagar
    assert q("REEMBOLSAR FULANO DE TAL PIX: 111.222.333-44") == "FULANO DE TAL"
    assert q("PAGAR PARA EMPRESA EXEMPLO PIX: 11.222.333/0001-81") == "EMPRESA EXEMPLO"
    assert q("REEMBOLSAR CICRANO - PIX 62 99999-0000") == "CICRANO"
    assert q("pagar o boleto até sexta") == ""
    assert q(None) == ""


# ==========================================================================
# 4. A pergunta do HTML
# ==========================================================================
def test_reembolso_de_casa_pelo_comeco_do_nome():
    pessoas = ["FULANO SILVA", "BELTRANO SOUZA"]
    e = html_pagamentos.e_reembolso_de
    assert e("FULANO", pessoas)                 # o aviso traz só o primeiro nome
    assert e("Fulano Silva Neto", pessoas)       # o documento, o nome inteiro
    assert e("BELTRANO SOUZA", pessoas)
    assert not e("FULANA", pessoas)
    assert not e("FULANO PEREIRA", pessoas)
    assert not e("", pessoas)
    assert not e("FULANO", [])


def test_nao_incluir_tira_os_reembolsos_dos_dois_htmls():
    reg = lambda i, para: {"id": i, "reembolso_para": para, "valor": 10.0}
    resultado = relatorio.Resultado(
        {"CONTA A": [reg("a1", "FULANO"), reg("a2", ""), reg("a3", "OUTRA PESSOA")],
         "CONTA B": [reg("b1", "BELTRANO SOUZA")]}, [])
    pf = [_lanc("p1", documentNumber="REEMBOLSO FULANO SILVA",
                tradePayableAccount={"name": "PESSOA FISICA - APENAS LANÇAMENTO"}),
          _lanc("p2", documentNumber="NF 99",
                tradePayableAccount={"name": "PESSOA FISICA - APENAS LANÇAMENTO"}),
          _lanc("p3", documentNumber="REEMBOLSO OUTRA PESSOA",
                tradePayableAccount={"name": "PESSOA FISICA - APENAS LANÇAMENTO"})]
    novo, lanc, tirados = html_pagamentos.tirar_reembolsos(
        resultado, pf, ["FULANO SILVA", "BELTRANO SOUZA"])
    assert [r["id"] for r in novo.contas["CONTA A"]] == ["a2", "a3"]
    assert "CONTA B" not in novo.contas            # conta que esvazia some
    assert [i["id"] for i in lanc] == ["p2", "p3"]
    assert tirados == 3
    # o resultado da planilha/remessa não é tocado
    assert len(resultado.contas["CONTA A"]) == 3


def test_sem_pessoas_nada_sai():
    resultado = relatorio.Resultado({"CONTA A": [{"id": "a1", "reembolso_para": "X"}]}, [])
    novo, lanc, tirados = html_pagamentos.tirar_reembolsos(resultado, [], [])
    assert novo is resultado and tirados == 0


def test_o_registro_diz_para_quem_e_o_reembolso_declarado_no_documento():
    item = _lanc(documentNumber="REEMBOLSO FULANO SILVA")
    anexos = {"T-L1": [_anexo("cupom", "Nota Fiscal")]}
    linha, = _linhas(relatorio.montar_registros([item], anexos, {}, {}))
    assert linha["reembolso_para"] == "FULANO SILVA"


# ==========================================================================
# 5. QR estilizado
# ==========================================================================
def test_variantes_ampliam_a_imagem_pequena_e_binarizam():
    from PIL import Image
    img = Image.new("RGB", (200, 200), (30, 40, 120))
    ampliada, binaria = list(qr_pix._variantes(img))
    assert min(ampliada.size) >= qr_pix.LADO_MINIMO
    assert set(binaria.tobytes()) <= {0, 255}


def test_imagem_grande_so_binariza():
    from PIL import Image
    variantes = list(qr_pix._variantes(Image.new("L", (1200, 1200), 255)))
    assert len(variantes) == 1


def test_ler_tenta_o_plano_b_quando_a_imagem_nao_le(monkeypatch):
    """Leitor falso que só "enxerga" imagem grande: o código só volta se o
    plano B (ampliar) for tentado — e só se passar nas provas de `valido`."""
    from PIL import Image
    sys.path.insert(0, "tests")
    from test_qr_pix import brcode
    codigo = brcode("CARTORIO EXEMPLO", 139.93)

    class _B:
        text = codigo

    falso = types.SimpleNamespace(
        BarcodeFormat=types.SimpleNamespace(QRCode="qr"),
        read_barcodes=lambda img, formats=None: (
            [_B()] if min(img.size) >= qr_pix.LADO_MINIMO else []))
    monkeypatch.setitem(sys.modules, "zxingcpp", falso)
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), 255).save(buf, "PNG")
    assert qr_pix.ler(buf.getvalue(), eh_pdf=False) == [codigo]
    # PDF não passa pelo plano B: a página já é renderizada a DPI
    assert qr_pix.ler(b"", eh_pdf=True) == []


def test_nome_igual_curto_confere():
    assert relatorio.recebedor_confere("ABC", "ABC")
    assert relatorio.recebedor_confere("A.B.C", "abc")
    assert not relatorio.recebedor_confere("ABC", "XYZ")
