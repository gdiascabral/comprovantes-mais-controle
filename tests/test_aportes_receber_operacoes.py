"""`AportesFrame.receber_operacoes` sem abrir janela: o método é chamado sobre
um dublê com o mesmo estado que a aba guarda. Cadastro fictício."""
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

from aportes.aportes_frame import AportesFrame
from aportes.regras import Operacao

ENTIDADES = {"MAE - BANCO": {"nome_oficial": "MAE LTDA", "conta": "MAE - BANCO"},
             "FILHA - BANCO": {"nome_oficial": "FILHA LTDA", "conta": "FILHA - BANCO"}}


def _aba(travada=False):
    linhas = []
    f = SimpleNamespace(entidades=ENTIDADES, subcontas={}, operacoes=[], criados=[],
                        incertos=[], assinaturas=[], linhas=linhas,
                        tabela=SimpleNamespace(insert=lambda *a, **k: linhas.append(k["values"])))
    f._lista_travada = lambda: travada
    f._atualizar_total = lambda: None
    f._acrescentar = lambda op: AportesFrame._acrescentar(f, op)
    return f


def _op(valor="10,00", pagador="MAE - BANCO"):
    return Operacao(data=date(2026, 10, 21), pagador=pagador, recebedor="FILHA - BANCO",
                    valor=D(valor.replace(",", ".")), tipo="Aporte de Capital",
                    modo="Pagamento + Recebimento")


def test_aceita_a_valida_e_recusa_a_invalida_com_motivo():
    aba = _aba()
    recusas = AportesFrame.receber_operacoes(aba, [_op(), _op(pagador="NINGUEM")])
    assert len(aba.operacoes) == 1 and len(aba.criados) == len(aba.incertos) == len(aba.assinaturas) == 1
    assert recusas == [(1, "Pagador desconhecido: NINGUEM")]
    assert aba.linhas == [(_op().resumo(),)]


def test_acrescentar_mantem_as_quatro_listas_alinhadas():
    aba = _aba()
    AportesFrame._acrescentar(aba, _op())
    AportesFrame._acrescentar(aba, _op("20,00"))
    assert aba.criados == [set(), set()] and aba.incertos == [set(), set()]
    assert aba.assinaturas == [{}, {}] and len(aba.operacoes) == 2
    assert aba.criados[0] is not aba.criados[1]


def test_operacao_igual_a_uma_da_lista_e_recusada():
    aba = _aba()
    AportesFrame.receber_operacoes(aba, [_op()])
    assert AportesFrame.receber_operacoes(aba, [_op()]) == [(0, "já está na lista A lançar")]
    assert len(aba.operacoes) == 1


def test_duas_iguais_no_mesmo_lote_entra_so_uma():
    aba = _aba()
    assert AportesFrame.receber_operacoes(aba, [_op(), _op()]) == [(1, "já está na lista A lançar")]
    assert len(aba.operacoes) == 1


def test_lista_travada_recusa_tudo():
    aba = _aba(travada=True)
    assert [i for i, _m in AportesFrame.receber_operacoes(aba, [_op(), _op("20,00")])] == [0, 1]
    assert aba.operacoes == []
