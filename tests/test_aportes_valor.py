# -*- coding: utf-8 -*-
"""O valor digitado na aba Aportes, e o dinheiro que ela mostra.

O defeito que este arquivo guarda: a tela lia o campo com
`.replace(".", "").replace(",", ".")`, que apaga TODO ponto — inclusive
quando ele é o separador decimal. Quem digitava "1500.50" lançava
R$ 150.050,00 no ERP, e a confirmação antes de lançar mostrava
"R$ 150,050.00" (formato americano), que para quem lê em português não
parece 150 mil. Sem Tk: só a regra (`aportes.regras`).
Nenhum dado real — nomes e contas são inventados.
"""
import ast
import datetime
import re
from decimal import Decimal
from pathlib import Path

import pytest

from aportes import regras
from aportes.regras import Operacao, expandir, formatar_brl, ler_valor_brl

RAIZ = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------- aceitos
@pytest.mark.parametrize("texto, esperado", [
    ("1.500,50", Decimal("1500.50")),
    ("1500,50", Decimal("1500.50")),
    ("1500,5", Decimal("1500.50")),
    ("R$ 1.500,50", Decimal("1500.50")),
    (" 1.500,50 ", Decimal("1500.50")),
    ("1.234.567,89", Decimal("1234567.89")),
    ("R$1.500,50", Decimal("1500.50")),
    ("r$ 10,00", Decimal("10.00")),
    ("\xa01.500,50\xa0", Decimal("1500.50")),   # espaço fixo, de copiar e colar
    ("1500", Decimal("1500.00")),
    ("0,50", Decimal("0.50")),
    ("0,01", Decimal("0.01")),
])
def test_valor_em_formato_brasileiro_e_aceito(texto, esperado):
    valor = ler_valor_brl(texto)
    assert valor == esperado
    assert isinstance(valor, Decimal)            # dinheiro não vira float
    assert valor.as_tuple().exponent == -2       # sempre com 2 casas


# ----------------------------------------------- recusados: ponto ambíguo
def test_1500_ponto_50_e_recusado_e_nunca_vira_150050():
    """O cenário do defeito: 1500.50 virava R$ 150.050,00 no ERP."""
    try:
        valor = ler_valor_brl("1500.50")
    except ValueError as e:
        assert "vírgula" in str(e)
        assert "1.500,50" in str(e)
        return
    assert valor != Decimal("150050"), "1500.50 virou 150.050 — o defeito voltou"
    pytest.fail(f"1500.50 é ambíguo e devia ser recusado, mas virou {valor}")


@pytest.mark.parametrize("texto", ["1500.50", "1500.5", "1.500", "R$ 1500.50",
                                   "10.00", "1.234.567"])
def test_ponto_sem_virgula_e_ambiguo_e_recusado(texto):
    with pytest.raises(ValueError, match="vírgula para os centavos"):
        ler_valor_brl(texto)


# ------------------------------------------- recusados: zero e negativo
@pytest.mark.parametrize("texto", ["0", "0,00", "R$ 0,00", "-10,00",
                                   "R$ -1.500,50", "(10,00)", "- 5,00"])
def test_zero_ou_negativo_e_recusado(texto):
    with pytest.raises(ValueError, match="maior que zero"):
        ler_valor_brl(texto)


# --------------------------------------- recusados: mais de 2 casas
@pytest.mark.parametrize("texto", ["10,505", "1.500,505", "0,001"])
def test_mais_de_duas_casas_e_recusado_em_vez_de_arredondar(texto):
    with pytest.raises(ValueError, match="2 casas"):
        ler_valor_brl(texto)


# ------------------------------------------------- recusados: lixo
@pytest.mark.parametrize("texto", ["", "   ", "R$", "abc", "1,500,00",
                                   "1.50,00", "12.34,56", "1234.567,89",
                                   "1500,", ",50", "1 500,00", "10,5a",
                                   "9" * 40 + ",00", None])
def test_texto_que_nao_e_valor_e_recusado_com_mensagem(texto):
    with pytest.raises(ValueError) as e:
        ler_valor_brl(texto)
    assert str(e.value).strip()                  # a tela mostra a mensagem


# ----------------------------------------------------------- formatador
@pytest.mark.parametrize("valor, esperado", [
    (Decimal("150050"), "R$ 150.050,00"),
    (Decimal("1500.50"), "R$ 1.500,50"),
    (Decimal("1500.5"), "R$ 1.500,50"),
    (Decimal("0.50"), "R$ 0,50"),
    (Decimal("1234567.89"), "R$ 1.234.567,89"),
    (Decimal("0"), "R$ 0,00"),
    ("1000.00", "R$ 1.000,00"),
])
def test_formatador_escreve_dinheiro_em_portugues(valor, esperado):
    assert formatar_brl(valor) == esperado


@pytest.mark.parametrize("valor", [Decimal("150050"), Decimal("1500.50"),
                                   Decimal("0.50"), Decimal("1234567.89")])
def test_formatador_da_regra_concorda_com_o_da_tela(valor):
    """A lista (regras) e o total/confirmação (widgets.brl) dizem o mesmo."""
    import widgets                               # importa tkinter, não abre janela
    assert formatar_brl(valor) == widgets.brl(valor)


HOJE = datetime.date(2026, 8, 11)
ENTIDADES = {
    "EMPRESA A": {"nome_oficial": "EMPRESA A LTDA", "conta": "EMPRESA A - BANCO",
                  "nome_descricao": None},
    "EMPRESA B": {"nome_oficial": "EMPRESA B LTDA", "conta": "EMPRESA B - BANCO",
                  "nome_descricao": None},
    "SUBCONTA 111-1": {"nome_oficial": "EMPRESA C LTDA",
                       "conta": "EMPRESA C - SUBCONTA 111-1",
                       "nome_descricao": None},
}


def test_resumo_da_lista_mostra_o_valor_em_portugues():
    op = Operacao(data=HOJE, pagador="EMPRESA A", recebedor="EMPRESA B",
                  valor=Decimal("150050.00"), tipo="Aporte de Capital",
                  modo="Pagamento + Recebimento")
    assert "R$ 150.050,00" in op.resumo()
    assert "150,050.00" not in op.resumo()


def test_erro_de_rateio_vazio_mostra_o_valor_em_portugues():
    subcontas = {"111-1": {"obras": [], "investidores": ["INVESTIDOR X"]}}
    op = Operacao(data=HOJE, pagador=regras.INVESTIDOR_PREFIXO + "111-1",
                  recebedor="SUBCONTA 111-1", valor=Decimal("1500.50"),
                  tipo="Aporte de Capital", modo="Só recebimento")
    with pytest.raises(ValueError, match=re.escape("R$ 1.500,50")):
        expandir(op, ENTIDADES, subcontas, "OBRA")


# ------------------------------------------------------------ guardas
def test_regras_nao_importa_tkinter_nem_widgets():
    """`regras.py` roda sem interface; o formatador dele é próprio."""
    arvore = ast.parse(Path(regras.__file__).read_text(encoding="utf-8"))
    nomes = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            nomes.update(a.name.split(".")[0] for a in no.names)
        elif isinstance(no, ast.ImportFrom) and no.module:
            nomes.add(no.module.split(".")[0])
    assert not nomes & {"tkinter", "widgets"}


def test_nenhum_dinheiro_em_formato_americano_nos_aportes():
    """`f"R$ {x:,.2f}"` escreve 150,050.00 — foi o que escondia o defeito."""
    americano = re.compile(r"R\$ \{[^}]*:,\.2f\}")
    achados = [f"{p.name}:{n}" for p in sorted((RAIZ / "aportes").glob("*.py"))
               for n, linha in enumerate(
                   p.read_text(encoding="utf-8").splitlines(), 1)
               if americano.search(linha)]
    assert not achados, achados


def test_a_tela_nao_apaga_mais_todo_ponto_do_valor():
    fonte = (RAIZ / "aportes" / "aportes_frame.py").read_text(encoding="utf-8")
    assert '.replace(".", "").replace(",", ".")' not in fonte
    assert "ler_valor_brl(" in fonte
