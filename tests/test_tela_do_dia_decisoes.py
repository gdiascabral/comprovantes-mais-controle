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


# ------------------------------------------- recado com o motivo (prova 22/10)
def test_detalhe_do_erro_diz_o_tipo_e_a_mensagem():
    from conciliacao.errors import ErpError
    assert dc.detalhe_do_erro(ErpError("token recusado (401)")) == \
        "detalhe: ErpError: token recusado (401)"
    assert dc.detalhe_do_erro(RuntimeError("")) == "detalhe: RuntimeError: (sem mensagem)"
    longo = dc.detalhe_do_erro(ValueError("linha 1\nlinha 2 " + "x" * 600))
    assert "\n" not in longo and len(longo) <= 400


def test_ler_o_dia_que_falha_escreve_o_detalhe_e_o_traceback():
    """O "Não consegui ler o dia." genérico de 21 e 22/10 não dizia o motivo:
    o `except` de `_t_ler` escreve o detalhe no Registro e o traceback no
    diagnostico.log."""
    import ast
    from pathlib import Path
    fonte = (Path(__file__).resolve().parents[1] / "tela_do_dia" / "frame.py").read_text(
        encoding="utf-8")
    arvore = ast.parse(fonte)
    t_ler = next(n for n in ast.walk(arvore)
                 if isinstance(n, ast.FunctionDef) and n.name == "_t_ler")
    trecho = ast.get_source_segment(fonte, t_ler)
    ultimo = trecho.rsplit("except Exception as e:", 1)[1].split("finally:", 1)[0]
    assert "Não consegui ler o dia." in ultimo
    assert "dc.detalhe_do_erro(e)" in ultimo
    assert 'util.log("tela_do_dia").exception(' in ultimo


# ------------------------------------------- campo de datas (dono, 22/10)
SEG = date(2026, 10, 19)          # segunda: a sugestão é sáb..seg


def test_campos_nascem_com_a_sugestao_de_hoje():
    assert dc.textos_sugeridos(SEG) == ("17/10/2026", "19/10/2026")
    assert dc.textos_sugeridos(HOJE) == ("21/10/2026", "21/10/2026")


def test_buscar_usa_o_periodo_escolhido():
    from conciliacao.models import Periodo
    sug = dc.textos_sugeridos(HOJE)
    p = dc.periodo_da_busca("16/10/2026", "20/10/2026", sug, HOJE)
    assert p == Periodo(date(2026, 10, 16), date(2026, 10, 20))
    # Invertido: troca, como a aba Remessa/Retorno.
    assert dc.periodo_da_busca("20/10/2026", "16/10/2026", sug, HOJE) == p
    # Sem mexer nos campos: a sugestão de hoje.
    assert dc.periodo_da_busca(*sug, sug, HOJE) == Periodo(HOJE, HOJE)


def test_sugestao_de_ontem_nao_mexida_vira_a_de_hoje():
    """App aberto de um dia para o outro: os campos ainda têm a sugestão de
    ontem, que ninguém escolheu. Buscar hoje lê hoje — nunca ontem calado."""
    from conciliacao.models import Periodo
    ontem = dc.textos_sugeridos(date(2026, 10, 16))       # sexta
    assert dc.periodo_da_busca(*ontem, ontem, SEG) == Periodo(date(2026, 10, 17), SEG)
    # Mas se o dono ESCOLHEU (o texto não é o que o app pôs), vale o escolhido.
    assert dc.periodo_da_busca("16/10/2026", "16/10/2026", ("x", "y"), SEG) == \
        Periodo(date(2026, 10, 16), date(2026, 10, 16))


@pytest.mark.parametrize("ini, fim", [("", "21/10/2026"), ("32/10/2026", "21/10/2026"),
                                      ("21/10/2026", "21/10"), ("ontem", "21/10/2026")])
def test_data_invalida_e_recusada_com_recado(ini, fim):
    with pytest.raises(ValueError, match="dd/mm/aaaa"):
        dc.periodo_da_busca(ini, fim, ("a", "b"), HOJE)


def test_periodo_que_nao_termina_hoje_avisa_que_o_sicoob_nao_e_lido():
    from conciliacao.models import Periodo
    assert dc.periodo_na_tela(Periodo(HOJE, HOJE), HOJE) == "Pagamentos de 21/10 a 21/10"
    passado = dc.periodo_na_tela(Periodo(date(2026, 10, 16), date(2026, 10, 16)), HOJE)
    assert passado.startswith("Pagamentos de 16/10 a 16/10")
    assert "dia de trabalho 16/10" in passado and "Sicoob" in passado


def test_buscar_da_tela_usa_os_campos_e_nao_so_a_sugestao():
    import ast
    from pathlib import Path
    fonte = (Path(__file__).resolve().parents[1] / "tela_do_dia" / "frame.py").read_text(
        encoding="utf-8")
    buscar = next(n for n in ast.walk(ast.parse(fonte))
                  if isinstance(n, ast.FunctionDef) and n.name == "buscar")
    trecho = ast.get_source_segment(fonte, buscar)
    assert "dc.busca_do_dia(" in trecho and "sugerir_periodo(" not in trecho
    assert "CampoData(" in fonte


# ------------------------------- revisão do pacote: saldo de agora ≠ do dia
def test_ate_no_futuro_adianta_e_o_dia_continua_sendo_hoje():
    """Dono, 29/10/2026: o diretor pede para adiantar os boletos dos próximos
    dias. O período do dia termina hoje; o resto é só para os boletos."""
    from conciliacao.models import Periodo
    p, ate = dc.busca_do_dia("20/10/2026", "24/10/2026", ("a", "b"), HOJE)
    assert p == Periodo(date(2026, 10, 20), HOJE) and ate == date(2026, 10, 24)
    assert dc.periodo_da_busca("20/10/2026", "24/10/2026", ("a", "b"), HOJE) == p
    # DE também no futuro: o dia é só hoje.
    p, ate = dc.busca_do_dia("23/10/2026", "25/10/2026", ("a", "b"), HOJE)
    assert p == Periodo(HOJE, HOJE) and ate == date(2026, 10, 25)
    # ATÉ até hoje: nada adiantado.
    assert dc.busca_do_dia("20/10/2026", "21/10/2026", ("a", "b"), HOJE)[1] is None
    frase = dc.frase_dos_adiantados(Periodo(HOJE, HOJE), date(2026, 10, 25))
    assert "22/10 a 25/10" in frase and "código de barras" in frase
    assert dc.frase_dos_adiantados(Periodo(HOJE, HOJE), None) == ""


def test_adiantar_tambem_respeita_31_dias():
    with pytest.raises(ValueError, match="31 dias"):
        dc.busca_do_dia("01/10/2026", "05/11/2026", ("a", "b"), HOJE)


def test_periodo_de_no_maximo_31_dias():
    from conciliacao.models import Periodo
    assert dc.periodo_da_busca("21/09/2026", "21/10/2026", ("a", "b"), HOJE) == \
        Periodo(date(2026, 9, 21), HOJE)                          # 31 dias
    with pytest.raises(ValueError, match="31 dias"):
        dc.periodo_da_busca("20/09/2026", "21/10/2026", ("a", "b"), HOJE)


def test_dia_passado_pergunta_antes_de_gerar_com_o_saldo_de_agora():
    from conciliacao.models import Periodo
    assert dc.pergunta_saldo_de_agora(Periodo(HOJE, HOJE), HOJE) == ""
    texto = dc.pergunta_saldo_de_agora(Periodo(date(2026, 10, 16), date(2026, 10, 16)), HOJE)
    assert texto == "O saldo é o de agora, não o de 16/10. Gerar mesmo assim?"
    assert dc.pergunta_saldo_de_agora(Periodo(date(2026, 10, 16), date(2026, 10, 16)), HOJE,
                                      acao="Mandar").endswith("Mandar mesmo assim?")


def test_periodo_passado_avisa_que_todos_os_saldos_sao_os_de_agora():
    from conciliacao.models import Periodo
    texto = dc.periodo_na_tela(Periodo(date(2026, 10, 16), date(2026, 10, 16)), HOJE)
    assert "sistema e Sicoob" in texto and "os de agora" in texto


def test_excel_e_aportes_perguntam_o_saldo_de_agora_com_padrao_nao():
    import ast
    from pathlib import Path
    fonte = (Path(__file__).resolve().parents[1] / "tela_do_dia" / "frame.py").read_text(
        encoding="utf-8")
    funcs = {n.name: ast.get_source_segment(fonte, n) for n in ast.walk(ast.parse(fonte))
             if isinstance(n, ast.FunctionDef)}
    for nome in ("_gerar_excel", "_mandar_aportes"):
        trecho = funcs[nome]
        assert "dc.pergunta_saldo_de_agora(" in trecho, nome
        depois = trecho.split("dc.pergunta_saldo_de_agora(", 1)[1]
        assert 'default="no"' in depois.split("return", 1)[0], nome


# --------------------------- revisão de dinheiro do PR #161 (29/10/2026)
def test_campos_com_ate_futuro_de_ontem_nao_valem_hoje():
    escritos = ("20/10/2026", "24/10/2026")
    assert dc.campos_de_outro_dia(escritos, escritos, date(2026, 10, 20), HOJE)
    assert not dc.campos_de_outro_dia(escritos, escritos, HOJE, HOJE)
    assert not dc.campos_de_outro_dia(("21/10/2026", "24/10/2026"), escritos,
                                      date(2026, 10, 20), HOJE)          # o dono mexeu
    assert not dc.campos_de_outro_dia(escritos, None, None, HOJE)


def test_rotulo_do_periodo_diz_que_ha_adiantados():
    from conciliacao.models import Periodo
    t = dc.periodo_na_tela(Periodo(HOJE, HOJE), HOJE, date(2026, 10, 24))
    assert "adiantados até 24/10" in t
    assert "adiantados" not in dc.periodo_na_tela(Periodo(HOJE, HOJE), HOJE)


def test_lancamento_ja_agendado_em_outro_dia_sai_ate_a_resposta():
    from decimal import Decimal
    from types import SimpleNamespace
    from tela_do_dia import conferencia as cf
    from tela_do_dia import geracao
    ontem = SimpleNamespace(dia=date(2026, 10, 20), lancamento_id="L1",
                            favorecido="LOJA", valor=Decimal("10"))
    hoje = SimpleNamespace(dia=HOJE, lancamento_id="L2", favorecido="LOJA",
                           valor=Decimal("5"))
    sem_lanc = SimpleNamespace(dia=date(2026, 10, 20), lancamento_id="",
                               favorecido="X", valor=Decimal("1"))
    nuvem = cf.Conferencia()
    vale, tirados = geracao.sem_ja_agendados(
        nuvem, [(ontem, None, None), (hoje, None, None), (sem_lanc, None, None)], HOJE)
    assert set(vale.decisoes) == {"L1"} and vale.decisoes["L1"].desmarcado
    assert tirados == ["LOJA — R$ 10,00 — já agendado em 20/10"]
    assert geracao.so_pela_tela(nuvem, vale, "L1") == "agendado"
    assert geracao.so_pela_tela(nuvem, vale, "L2") == ""
    assert geracao.sem_ja_agendados(nuvem, [], HOJE)[0] is nuvem
