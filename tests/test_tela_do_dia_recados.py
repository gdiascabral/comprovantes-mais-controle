"""Recados com causa conhecida: o Excel do dia aberto no Excel."""
from tela_do_dia import recados

DIA = "C:/pasta/22 10 - completa.xlsx"


def test_excel_aberto_vira_recado_claro():
    e = PermissionError(13, "Permission denied", DIA)
    assert recados.excel_aberto(e, DIA) == \
        "O Excel do dia está aberto no Excel; feche-o e clique de novo."


def test_excel_aberto_embrulhado_tambem():
    try:
        try:
            raise PermissionError(13, "Permission denied", DIA)
        except PermissionError as dentro:
            raise RuntimeError("não gravei") from dentro
    except RuntimeError as e:
        assert recados.excel_aberto(e, DIA) == recados.EXCEL_ABERTO


def test_outro_erro_nao_tem_recado_proprio():
    assert recados.excel_aberto(FileNotFoundError(2, "No such file", DIA), DIA) == ""
    assert recados.excel_aberto(ValueError("x"), DIA) == ""


def test_permissao_negada_em_outro_caminho_mostra_o_erro_de_verdade():
    """Revisão geral de 22/10/2026, achado 11: pasta sem permissão, o modelo
    travado ou o OneDrive segurando outro arquivo não são "o Excel aberto"."""
    for outro in ("C:/pasta", "C:/modelos/MODELO.xlsx", "C:/pasta/~$22 10 - completa.xlsx"):
        e = PermissionError(13, "Permission denied", outro)
        assert recados.excel_aberto(e, DIA) == "", outro
    assert recados.excel_aberto(PermissionError(13, "Permission denied"), DIA) == ""


def test_mesmo_arquivo_com_barra_ou_caixa_diferente_ainda_e_o_do_dia():
    e = PermissionError(13, "Permission denied", r"c:\PASTA\22 10 - completa.xlsx")
    assert recados.excel_aberto(e, DIA) == recados.EXCEL_ABERTO
