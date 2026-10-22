"""Recados com causa conhecida: o Excel do dia aberto no Excel."""
from tela_do_dia import recados


def test_excel_aberto_vira_recado_claro():
    e = PermissionError(13, "Permission denied", "C:/pasta/22 10 - completa.xlsx")
    assert recados.excel_aberto(e) == "O Excel do dia está aberto no Excel; feche-o e clique de novo."


def test_excel_aberto_embrulhado_tambem():
    try:
        try:
            raise PermissionError(13, "Permission denied")
        except PermissionError as dentro:
            raise RuntimeError("não gravei") from dentro
    except RuntimeError as e:
        assert recados.excel_aberto(e) == recados.EXCEL_ABERTO


def test_outro_erro_nao_tem_recado_proprio():
    assert recados.excel_aberto(FileNotFoundError(2, "No such file")) == ""
    assert recados.excel_aberto(ValueError("x")) == ""
