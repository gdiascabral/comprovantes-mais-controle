"""O nível no HTML das PF (spec de 19/11/2026). Fictício."""
from datetime import date

from pagamentos_dia import html_pf

HOJE = date(2026, 11, 19)


def _item(**r):
    base = {"tipo": "Pix", "dados": "fulano@exemplo.com", "valor": 50.0, "status": "APTO",
            "conferencia": "valor ✓ · fornecedor ✓", "id": "1", "favorecido": "PESSOA FICTICIA",
            "fornecedor_no_anexo": True,
            "vencimento": "2026-11-19"}
    base.update(r)
    return html_pf.item_do_registro("PESSOA FISICA - CONTA MODELO", base)


def test_cartao_conferido_mostra_pode_pagar():
    html = html_pf._cartao(1, _item(), HOJE)
    assert "PODE PAGAR" in html and 's-PODE_PAGAR' in html


def test_cartao_sem_conferencia_mostra_nao_li():
    html = html_pf._cartao(1, _item(conferencia=""), HOJE)
    assert "NÃO LI" in html and "valor não conferido" in html


def test_cartao_com_alerta_e_olhe_e_o_codigo_continua_escondido():
    it = _item(status="ATENÇÃO — documento declara reembolso")
    html = html_pf._cartao(1, it, HOJE)
    assert "OLHE" in html or "NÃO LI" in html
    assert it.alertas, "o alerta de hoje continua"


def test_cartao_parcelado_mostra_a_parcela():
    html = html_pf._cartao(1, _item(parcela={"numero": 2, "total": 4}), HOJE)
    assert "Parcela 2 de 4" in html


def test_o_alerta_do_cartao_nao_se_repete_nos_motivos():
    it = _item(dados="PIX EMAIL fulano@exemplo.com")
    html = html_pf._cartao(1, it, HOJE)
    for alerta in it.alertas:
        assert html.count(html_pf._e(alerta)) == 1
