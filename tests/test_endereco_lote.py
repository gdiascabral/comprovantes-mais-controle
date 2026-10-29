"""Conferência de quadra e lote do anexo × centro de custo (dono, 28/10/2026:
"dificuldade para achar o LT … é extremamente importante, para não pagarmos
nada errado"). Nomes e endereços fictícios: o repositório é público."""
import pytest

from pagamentos_dia import relatorio


def _item(cc, descricao="", fornecedor="Servicos Modelo"):
    return {"documentNumber": "1", "paidTo": fornecedor, "remainingValue": 100.0,
            "description": descricao,
            "costCentreDetails": [{"workName": w.strip()} for w in cc.split("|")]}


def _endereco(cc, anexo, observacao=None):
    textos = [anexo] + ([observacao] if observacao else [])
    resumo, divergiu = relatorio.conferir_documento(
        _item(cc), [], textos, textos_valor=[anexo])
    parte = next((p for p in resumo.split(" · ") if p.startswith("endereço")), "")
    return parte, divergiu


@pytest.mark.parametrize("texto, esperado", [
    ("RUA X QD 9 LT 7A", ["QD 9", "LT 7A"]),
    ("QD9LT7A", ["QD 9", "LT 7A"]),
    ("LT 7-A", ["LT 7A"]),
    ("QUADRA 9 LOTE 7", ["QD 9", "LT 7"]),
    ("Q. 9 L. 7", ["QD 9", "LT 7"]),
    ("QD-9 LT-7", ["QD 9", "LT 7"]),
    ("QD 09 LT 007", ["QD 9", "LT 7"]),
    ("LT 10, 11 e 12", ["LT 10", "LT 11", "LT 12"]),
    ("LT 10/11", ["LT 10", "LT 11"]),
    ("LT 10-11", ["LT 10", "LT 11"]),
    ("LOTES 7A, 7B", ["LT 7A", "LT 7B"]),
    ("QD 5 E LT 7", ["QD 5", "LT 7"]),
    ("QD.26A LT.11", ["QD 26A", "LT 11"]),
])
def test_formas_de_escrever_quadra_e_lote(texto, esperado):
    assert relatorio._tokens_de_endereco(texto) == esperado


RATEIO = "RUA X QD 9 LT 7A | RUA X QD 9 LT 7B | RUA X QD 9 LT 7C"


def test_lote_com_letra_do_rateio_confere():
    parte, divergiu = _endereco(RATEIO, "GUIA DESMEMBRAMENTO QD 9 LT 7B")
    assert parte == "endereço ✓ (QD 9 LT 7B; falta LT 7A, 7C)" and not divergiu


def test_outro_lote_da_mesma_quadra_diverge():
    """Antes saía "endereço ✓ (QD 9)": o anexo era de outro imóvel."""
    parte, divergiu = _endereco(RATEIO, "GUIA QD 9 LT 05")
    assert parte.startswith("endereço DIVERGE (lote: anexo LT 5") and divergiu


def test_lote_parecido_pede_conferencia_sem_alarmar():
    """O OCR come a letra: "LT 7" contra "LT 7A" é dúvida, não divergência."""
    parte, divergiu = _endereco("RUA X QD 9 LT 7A", "GUIA QD 9 LT 7")
    assert "confira a letra do lote" in parte and not divergiu


def test_quadra_sem_lote_no_anexo_e_duvida():
    parte, divergiu = _endereco(RATEIO, "GUIA QD 9 SEM LOTE")
    assert parte.startswith("endereço ? (QD 9 ok, LT 7A, 7B, 7C não aparece)") and not divergiu


def test_lote_com_letra_trocada_diverge():
    parte, divergiu = _endereco("RUA X QD 1 LT 7B", "PEDIDO QD 1 LT 7-A")
    assert "DIVERGE" in parte and divergiu


def test_anexo_com_varios_lotes_incluindo_o_nosso_confere():
    parte, divergiu = _endereco("RUA X QD 5 LT 7", "PEDIDO QD 5 LT 7 E QD 5 LT 9")
    assert parte.startswith("endereço ✓ (QD 5 LT 7)") and not divergiu


def test_lote_so_na_observacao_do_lancamento_nao_prova():
    parte, divergiu = _endereco("RUA X QD 9 LT 7A", "GUIA SEM ENDERECO",
                                observacao="PAGAR QD 9 LT 7A")
    assert parte.startswith("endereço ?") and not divergiu


def test_sinonimos_e_zero_a_esquerda_conferem():
    parte, divergiu = _endereco("RUA X QD 9 LT 7", "IMOVEL QUADRA 09 LOTE 007")
    assert parte == "endereço ✓ (QD 9 LT 7)" and not divergiu


def test_quadra_de_outra_quadra_nao_diverge_so_informa():
    parte, divergiu = _endereco("RUA X QD 9 LT 7", "GUIA QD 3 LT 5")
    assert parte.startswith("endereço ?") and not divergiu
