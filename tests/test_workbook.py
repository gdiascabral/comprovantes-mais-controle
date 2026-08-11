from datetime import date
from decimal import Decimal

import openpyxl
import pytest

from conciliacao.models import RowFill
from conciliacao.workbook import WorkbookError, build, output_name

HOJE = date(2026, 7, 30)


@pytest.fixture
def fills(planilha, mapping):
    """Um dia tipico: uma conta com pagamento, uma sem, e as linhas mortas."""
    resultado = []
    for row in planilha.linhas:
        modelo = mapping.by_row(row)
        if modelo is not None and not modelo.exists_in_erp:
            resultado.append(RowFill(row, None, None, None, None))
        elif row == 8:
            resultado.append(RowFill(row, Decimal("1536956.24"), Decimal("40608.17"), 35, None))
        elif row == 10:
            resultado.append(RowFill(row, Decimal("-1179.29"), Decimal("0"), 0, 0))
        else:
            resultado.append(RowFill(row, Decimal("100"), Decimal("0"), 0, 0))
    return resultado


def test_output_name_usa_dia_e_mes(planilha):
    assert output_name(date(2026, 7, 30)) == "30 07 - completa.xlsx"
    assert output_name(date(2026, 12, 5)) == "05 12 - completa.xlsx"


def test_build_escreve_valores_e_preserva_formulas(
    modelo_path, tmp_path, fills, mapping, planilha
):
    destino = tmp_path / output_name(HOJE)
    resultado = build(modelo_path, destino, HOJE, fills, mapping, planilha)

    assert resultado.path.is_file()
    assert resultado.linhas_escritas == 24
    # assert_untouched conferiu o resto da planilha celula por celula.
    assert resultado.celulas_conferidas > 200

    ws = openpyxl.load_workbook(destino).worksheets[0]

    # O Excel guarda data como serial; o openpyxl devolve datetime.
    assert ws[planilha.celula_data].value.date() == HOJE
    assert ws[planilha.celula_data].number_format == planilha.formato_data

    assert ws["D8"].value == pytest.approx(1536956.24)
    assert ws["E8"].value == pytest.approx(40608.17)
    assert ws["I8"].value == 35
    assert ws["J8"].value is None  # ha pagamento -> J fica para a conferencia manual

    assert ws["D10"].value == pytest.approx(-1179.29)
    assert (ws["E10"].value, ws["I10"].value, ws["J10"].value) == (0, 0, 0)

    # Formulas intactas, incluindo o encadeamento de aportes e o rateio.
    assert ws["F8"].value == "=SUMIF($N$8:$N$31,B8,$M$8:$M$31)"
    assert ws["G8"].value == "=D8-E8-F8"
    assert ws["M9"].value.endswith("*0.667)))")
    assert ws["H9"].value == "=IF(G9<0,G9+M9+F32,G9)"
    assert ws["F32"].value == "=IF(M9>0,M9/2,0)"
    assert ws["N12"].value == '=IF(M12>0,"MORAIS ENGENHARIA - INTER","")'
    assert ws["E33"].value == "=SUM(E8:E31)"
    assert ws["F12"].value == 0


def test_linhas_sem_conta_no_erp_ficam_vazias_no_arquivo(
    modelo_path, tmp_path, fills, mapping, planilha
):
    destino = tmp_path / "morta.xlsx"
    build(modelo_path, destino, HOJE, fills, mapping, planilha)
    ws = openpyxl.load_workbook(destino).worksheets[0]

    for row in (28, 30, 31):
        for col in planilha.colunas_escritas:
            assert ws[f"{col}{row}"].value is None, f"{col}{row}"


def test_formatacao_condicional_e_validacoes_sobrevivem(
    modelo_path, tmp_path, fills, mapping, planilha
):
    """Round-trip do openpyxl nao pode perder o que o modelo tem de visual."""
    destino = tmp_path / "estilos.xlsx"
    build(modelo_path, destino, HOJE, fills, mapping, planilha)

    orig = openpyxl.load_workbook(modelo_path).worksheets[0]
    novo = openpyxl.load_workbook(destino).worksheets[0]

    assert len(novo.conditional_formatting._cf_rules) == len(orig.conditional_formatting._cf_rules)
    assert len(novo.data_validations.dataValidation) == len(orig.data_validations.dataValidation)
    assert novo.freeze_panes == orig.freeze_panes
    assert novo.merged_cells.ranges == orig.merged_cells.ranges
    assert novo["D8"].number_format == orig["D8"].number_format


def test_o_modelo_original_nao_e_modificado(modelo_path, tmp_path, fills, mapping, planilha):
    antes = modelo_path.read_bytes()
    build(modelo_path, tmp_path / "saida.xlsx", HOJE, fills, mapping, planilha)
    assert modelo_path.read_bytes() == antes


def test_reexecucao_no_mesmo_dia_sobrescreve(modelo_path, tmp_path, fills, mapping, planilha):
    destino = tmp_path / output_name(HOJE)
    build(modelo_path, destino, HOJE, fills, mapping, planilha)
    resultado = build(modelo_path, destino, HOJE, fills, mapping, planilha)
    assert resultado.path == destino


def test_label_divergente_do_modelo_falha_alto(modelo_path, tmp_path, fills, mapping, planilha):
    """Label errado zeraria o SUMIF da coluna F sem erro nenhum no Excel."""
    alvo = mapping.by_row(8)
    object.__setattr__(alvo, "label", "Nome Trocado")
    try:
        with pytest.raises(WorkbookError, match="diverge da coluna B"):
            build(modelo_path, tmp_path / "x.xlsx", HOJE, fills, mapping, planilha)
    finally:
        object.__setattr__(alvo, "label", "Morais Engenharia - Inter")


def test_modelo_inexistente_falha_com_mensagem_clara(tmp_path, fills, mapping, planilha):
    with pytest.raises(WorkbookError, match="modelo nao encontrado"):
        build(tmp_path / "nao-existe.xlsx", tmp_path / "y.xlsx", HOJE, fills, mapping, planilha)
