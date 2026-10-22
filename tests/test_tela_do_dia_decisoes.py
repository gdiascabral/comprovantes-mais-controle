"""As decisões da tela do dia que não precisam de janela. Contas fictícias."""
from datetime import date
from decimal import Decimal as D

import pytest

from aportes.regras import Operacao
from pagamentos_dia.leitura_do_dia import LeituraDosPagamentos
from tela_do_dia import decisoes as dc
from tela_do_dia.aportes import AporteDaConta
from tela_do_dia.para_aportes import MOTIVO_SEM_SALDO, Envio, Pendente
from tela_do_dia.saldos import LinhaSaldo

MAE, ALFA = "Mae - Banco", "Conta Alfa - Banco"
ROTULOS = (MAE, ALFA)
HOJE = date(2026, 10, 21)


def _leitura(**kw):
    base = dict(periodo=(HOJE, HOJE), entradas=object())
    base.update(kw)
    return LeituraDosPagamentos(**base)


# ------------------------------------------------------- células do aporte
def test_conta_sem_saldo_mostra_traco_no_minimo_falta_e_saldo_final():
    c = AporteDaConta(rotulo=ALFA, saldo=None, a_pagar=D("500.00"),
                      definidos={"Socio Ficticio A": D("100.00")})
    minimo, definido, falta, final = dc.celulas_do_aporte(c)
    assert (minimo, falta, final) == ("—", "—", "—")
    assert definido == "R$ 100,00"


def test_conta_com_saldo_mostra_os_numeros():
    c = AporteDaConta(rotulo=ALFA, saldo=D("100.00"), a_pagar=D("500.00"))
    assert dc.celulas_do_aporte(c) == ("R$ 400,00", "R$ 0,00", "R$ 400,00", "-R$ 400,00")


# ------------------------------------------------------- movimentos à mão
def test_aporte_de_fora_vira_origem_none():
    assert dc.novo_movimento(dc.DE_FORA, MAE, "1.000,00", ROTULOS) == (None, MAE, D("1000.00"))


def test_transferencia_entre_contas_do_painel():
    assert dc.novo_movimento(MAE, ALFA, "250,50", ROTULOS) == (MAE, ALFA, D("250.50"))


@pytest.mark.parametrize("origem, destino, valor, trecho", [
    (MAE, MAE, "10,00", "mesma conta"),
    ("", ALFA, "10,00", "origem"),             # transferência sem origem não vira "de fora"
    (dc.DE_FORA, "Conta Inexistente", "10,00", "destino"),
    ("Conta Inexistente", MAE, "10,00", "origem"),
    (dc.DE_FORA, MAE, "0", "maior que zero"),
    (dc.DE_FORA, MAE, "-5,00", "maior que zero"),
    (dc.DE_FORA, MAE, "1500.50", "vírgula"),   # ambíguo: a régua de valores recusa
])
def test_movimento_invalido_e_recusado(origem, destino, valor, trecho):
    with pytest.raises(ValueError, match=trecho):
        dc.novo_movimento(origem, destino, valor, ROTULOS)


def test_so_movimentos_validos_vao_ao_excel():
    a_mao = [(None, MAE, D("10.00")), (MAE, "Conta Fora", D("5.00")),
             (MAE, ALFA, D("0.00")), (MAE, ALFA, D("-1.00")), (MAE, ALFA, D("2.00"))]
    assert dc.movimentos_validos(a_mao, ROTULOS) == [(None, MAE, D("10.00")),
                                                      (MAE, ALFA, D("2.00"))]


def test_descrever_movimento():
    assert dc.descrever_movimento((None, MAE, D("10.00"))) == f"de fora → {MAE}: R$ 10,00"
    assert dc.descrever_movimento((MAE, ALFA, D("2.00"))) == f"{MAE} → {ALFA}: R$ 2,00"


# --------------------------------------------------- o que a leitura deixa
def test_sem_leitura_nada_gera():
    assert "Busque" in dc.motivo_sem_excel(None, [], True)
    assert "Busque" in dc.motivo_sem_geradores(None)


def test_leitura_interrompida_nao_gera_nada():
    leitura = _leitura(interrompida=True, entradas=None)
    assert "interrompida" in dc.motivo_sem_excel(leitura, [], False)
    assert "interrompida" in dc.motivo_sem_geradores(leitura)


def test_leitura_sem_entradas_trava_planilha_html_e_remessa_mas_nao_o_excel():
    leitura = _leitura(entradas=None)
    assert dc.motivo_sem_geradores(leitura)
    assert dc.motivo_sem_excel(leitura, [LinhaSaldo(5, ALFA, D("1.00"))], True) == ""


def test_excel_recusa_saldo_ausente_quando_a_config_exige():
    saldos = [LinhaSaldo(5, ALFA, None), LinhaSaldo(6, MAE, D("1.00"))]
    motivo = dc.motivo_sem_excel(_leitura(), saldos, True)
    assert ALFA in motivo and MAE not in motivo
    assert dc.motivo_sem_excel(_leitura(), saldos, False) == ""


def test_saldo_do_banco_digitado_supre_o_do_sistema_ausente():
    saldos = [LinhaSaldo(5, ALFA, None, banco=D("3.00"))]
    assert dc.motivo_sem_excel(_leitura(), saldos, True) == ""
    assert dc.contas_sem_saldo(saldos) == set()


def test_contas_sem_saldo():
    saldos = [LinhaSaldo(5, ALFA, None), LinhaSaldo(6, MAE, D("1.00"))]
    assert dc.contas_sem_saldo(saldos) == {ALFA}


# ------------------------------------------------------- o envio aos Aportes
def _op(valor):
    return Operacao(data=HOJE, pagador="Socio Ficticio A", recebedor=ALFA,
                    valor=D(valor), tipo="Aporte de Capital", modo="Pagamento + Recebimento")


def test_segurar_as_operacoes_sem_saldo_por_identidade():
    a, b = _op("1.00"), _op("1.00")            # iguais em valor, objetos diferentes
    envio = Envio(itens=[(a, ["k1"]), (b, ["k2"])], sem_saldo=[b])
    mandadas, seguradas = dc.separar_envio(envio, mandar_sem_saldo=False)
    assert [id(x) for x in mandadas] == [id(a)]
    assert [id(x) for x in seguradas] == [id(b)]
    mandadas, seguradas = dc.separar_envio(envio, mandar_sem_saldo=True)
    assert [id(x) for x in mandadas] == [id(a), id(b)] and seguradas == []


def test_pendencias_e_avisos_saem_separados():
    envio = Envio(pendentes=[Pendente(ALFA, "Socio Ficticio A", D("300.00"), "já mandado")],
                  avisos=[Pendente(MAE, "INVESTIDOR X", D("5.00"), MOTIVO_SEM_SALDO)])
    pendentes, avisos = dc.linhas_do_envio(envio)
    assert pendentes == [f"Socio Ficticio A → {ALFA} (R$ 300,00): já mandado"]
    assert avisos == [f"INVESTIDOR X → {MAE} (R$ 5,00): {MOTIVO_SEM_SALDO}"]


# ------------------------------------------------------------ conserto
def test_celulas_da_conta_separam_vao_sair_a_pagar_e_bloqueados():
    from tela_do_dia.pagamentos import Pagamento, PagamentosDaConta
    p = Pagamento(id="1", conta_erp=ALFA, favorecido="Fornecedor Ficticio",
                  valor=D("10.00"), situacao="", estado="")
    q = Pagamento(id="2", conta_erp=ALFA, favorecido="Fornecedor Ficticio",
                  valor=D("7.50"), situacao="não apto", estado="")
    c = PagamentosDaConta(ALFA, 5, vao_sair=[p, p], bloqueados=[q])
    assert dc.celulas_da_conta(c) == ("2", "R$ 20,00", "1 · R$ 7,50", "")
    vazia = PagamentosDaConta(ALFA, 5, vao_sair=[p])
    assert dc.celulas_da_conta(vazia) == ("1", "R$ 10,00", "0", "")
    fora = PagamentosDaConta("Conta Fora", None, bloqueados=[q], motivo_fora="sem linha")
    assert dc.celulas_da_conta(fora)[3] == "sem linha"


def test_celulas_da_conta_mostram_o_ja_enviado_somando_no_a_pagar():
    from tela_do_dia.pagamentos import Pagamento, PagamentosDaConta
    p = Pagamento(id="1", conta_erp=ALFA, favorecido="Fornecedor Ficticio",
                  valor=D("10.00"), situacao="", estado="")
    e = Pagamento(id="2", conta_erp=ALFA, favorecido="Fornecedor Ficticio",
                  valor=D("40.00"), situacao="já enviado", estado="")
    c = PagamentosDaConta(ALFA, 5, vao_sair=[p], ja_enviados=[e])
    assert dc.celulas_da_conta(c) == (
        "2", "R$ 50,00", "0", "1 já enviado · R$ 40,00 (soma no a pagar)")
    fora = PagamentosDaConta("Conta Fora", None, ja_enviados=[e], motivo_fora="sem linha")
    assert dc.celulas_da_conta(fora)[3] == "sem linha · 1 já enviado · R$ 40,00 (soma no a pagar)"


def test_excel_do_dia_que_ja_existe_pede_confirmacao(tmp_path):
    destino = tmp_path / "21 10 - completa.xlsx"
    assert dc.pergunta_sobrescrever(destino) == ""
    destino.write_bytes(b"x")
    pergunta = dc.pergunta_sobrescrever(destino)
    assert "21 10 - completa.xlsx" in pergunta and "Saldo de pagamentos" in pergunta


def test_aporte_leva_a_data_do_dia_de_trabalho_e_nao_a_do_relogio():
    from conciliacao.models import Periodo
    assert dc.data_das_operacoes(Periodo(date(2026, 10, 17), date(2026, 10, 19))) == date(2026, 10, 19)


# ------------------------------------------------- período lido (sem campo de data)
def test_periodo_lido_aparece_na_tela():
    from conciliacao.models import Periodo
    assert dc.periodo_na_tela(Periodo(date(2026, 10, 17), date(2026, 10, 19))) == \
        "Pagamentos de 17/10 a 19/10"
    assert dc.periodo_na_tela(Periodo(HOJE, HOJE)) == "Pagamentos de 21/10 a 21/10"


@pytest.mark.parametrize("inicio, fim", [
    (date(2026, 10, 21), date(2026, 10, 21)),     # quarta: período só de hoje
    (date(2026, 10, 17), date(2026, 10, 19)),     # segunda: sáb..seg
    (date(2026, 10, 16), date(2026, 10, 19)),
])
def test_periodo_nunca_avisa_sem_calendario_de_feriados(inicio, fim):
    """Sem calendário, "o dia útil anterior não está no período" vale em TODO
    dia útil — avisar sempre é ruído. O vencido de feriado se busca pela aba
    Remessa/Retorno (notas do PR e arquitetura-tela-do-dia.md)."""
    from conciliacao.models import Periodo
    texto = dc.periodo_na_tela(Periodo(inicio, fim))
    assert isinstance(texto, str) and "útil" not in texto and "fora" not in texto


def test_celulas_da_conta_citam_liberados_a_mao_e_desmarcados():
    from tela_do_dia.pagamentos import Pagamento, PagamentosDaConta

    def pag(i, v):
        return Pagamento(id=i, conta_erp=ALFA, favorecido="Fornecedor Ficticio",
                         valor=D(v), situacao="", estado="")
    c = PagamentosDaConta(ALFA, 5, vao_sair=[pag("1", "10.00")], liberados=[pag("2", "5.00")],
                          a_mao=[pag("mao:1", "2.50")], desmarcados=[pag("3", "99.00")])
    qtd, a_pagar, bloqueados, situacao = dc.celulas_da_conta(c)
    assert (qtd, a_pagar, bloqueados) == ("3", "R$ 17,50", "0")     # o desmarcado não soma
    assert "1 liberado" in situacao and "1 à mão" in situacao and "1 desmarcado (fora)" in situacao
    dois = PagamentosDaConta(ALFA, 5, liberados=[pag("2", "5.00"), pag("4", "1.00")],
                             desmarcados=[pag("3", "9.00"), pag("5", "9.00")])
    texto = dc.celulas_da_conta(dois)[3]
    assert "2 liberados" in texto and "2 desmarcados (fora)" in texto


def test_celulas_da_conta_sem_conferencia_e_o_texto_de_hoje():
    from types import SimpleNamespace
    # objeto da entrega 1: não tem liberados, a_mao nem desmarcados
    antiga = SimpleNamespace(bloqueados=[], valor_bloqueado=D("0"), motivo_fora="", ja_enviados=[],
                             qtd_a_pagar=0, a_pagar=D("0"))
    assert dc.celulas_da_conta(antiga) == ("0", "R$ 0,00", "0", "")
