from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def test_saldo_nao_tem_mais_busca_propria_de_contas():
    fonte = (RAIZ / "conciliacao" / "frame.py").read_text(encoding="utf-8")
    assert "Verificar contas novas" not in fonte
    assert "contas_novas_janela" not in fonte
    assert not (RAIZ / "conciliacao" / "contas_novas_janela.py").exists()
