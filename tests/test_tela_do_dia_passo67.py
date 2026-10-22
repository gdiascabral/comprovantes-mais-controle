"""As regras da tela para "Agendados a confirmar", o passo 6 e o passo 7 — sem janela."""
from datetime import date
from decimal import Decimal as D

import pytest

from nuvem import rest
from tela_do_dia import agendados as ag
from tela_do_dia import lista_diretor as ldr
from tela_do_dia import nuvem_do_dia as nd
from tela_do_dia import passo2
from tela_do_dia import passo67 as p67
from tela_do_dia.conferencia import Conferencia

DIA = HOJE = date(2026, 10, 23)


def _ag(i, alvo="L1", valor="100.00", conta="Conta Alfa - Banco", lanc=None, dia=DIA,
        em_aberto="100.00"):
    return ag.Agendado(id=i, dia=dia, conta=conta, alvo=alvo,
                       lancamento_id=alvo if lanc is None else lanc,
                       favorecido="Fornecedor Modelo Ltda", valor=D(valor),
                       foto={"em_aberto": em_aberto, "vencimento": dia.isoformat()})


def _linha(i, alvo="L1", valor="100.00", conta="Conta Alfa - Banco", dia="2026-10-23"):
    return {"id": i, "dia": dia, "conta": conta, "alvo": alvo, "lancamento_id": alvo,
            "favorecido": "Fornecedor Modelo Ltda", "valor": valor,
            "foto": {"em_aberto": valor, "vencimento": dia}}


PAGO = ag.Situacao("ok", "pago no ERP (baixa)", True, ag.PROVA_BAIXA)
SUMIU = ag.Situacao("erro", "título sumiu do ERP — era R$ 100,00")
AGUARDA = ag.Situacao("", "aguardando — responda")


# ------------------------------------------------- agendados a confirmar
def test_pre_marca_so_vem_da_situacao_e_o_clique_do_dono_fica():
    pend = [(_ag(1), PAGO, None), (_ag(2, "L2"), SUMIU, None)]
    marcas = p67.marcas_iniciais(pend)
    assert marcas == {1: True, 2: False}
    marcas2 = p67.alternar(marcas, 2)
    assert marcas2 == {1: True, 2: True} and marcas == {1: True, 2: False}
    # Releitura: o que o dono clicou continua; pendente novo nasce da situação.
    pend2 = [*pend, (_ag(3, "L3"), AGUARDA, None)]
    assert p67.marcas_iniciais(pend2, marcas2) == {1: True, 2: True, 3: False}
    # Quem saiu dos pendentes sai das marcas.
    assert p67.marcas_iniciais(pend2[1:], marcas2) == {2: True, 3: False}


def test_linhas_dos_agendados_mostram_reagendado_e_a_marca():
    resp = ag.Resposta(id=9, agendado_id=1, resposta="reagendado", motivo="sem saldo",
                       nova_data=date(2026, 10, 26))
    linhas = p67.linhas_agendados([(_ag(1), AGUARDA, resp), (_ag(2, "L2"), SUMIU, None)],
                                  {1: False, 2: True})
    assert [l.iid for l in linhas] == ["1", "2"]
    assert linhas[0].valores[0] == p67.DESMARCADO and linhas[1].valores[0] == p67.MARCADO
    assert linhas[0].valores[1] == "23/10"
    assert "reagendado para 26/10" in linhas[0].valores[5]
    assert "aguardando" in linhas[0].valores[5]
    assert linhas[1].tags == ("erro",) and linhas[0].tags == ()
    assert len(linhas[0].valores) == len(p67.COLS_AGD)


def test_colunas_cabem_a_1280():
    assert sum(c[2] for c in p67.COLS_AGD) <= 760
    assert sum(c[2] for c in p67.COLS_MARCAR) <= 760
    assert sum(c[2] for c in p67.COLS_LISTA) <= 760


def test_pago_dos_marcados_leva_a_prova_e_pergunta_sem_prova():
    pend = [(_ag(1), PAGO, None), (_ag(2, "L2"), SUMIU, None), (_ag(3, "L3"), AGUARDA, None)]
    itens = p67.pagos_marcados(pend, {1: True, 2: True, 3: False})
    assert itens == [(1, ag.PROVA_BAIXA), (2, "")]
    pergunta = p67.pergunta_ao_pagar(pend, {1: True, 2: True})
    assert pergunta.startswith("Gravar 2 como pago?")
    assert "Fornecedor Modelo Ltda R$ 100,00 — baixa no ERP" in pergunta
    assert "SEM prova" in pergunta
    # Sempre pergunta, mesmo com tudo provado.
    assert p67.pergunta_ao_pagar(pend, {1: True}).startswith("Gravar 1 como pago?")
    assert p67.recusa_de_pagar([]) and p67.recusa_de_pagar(itens) == ""


def test_pergunta_do_pago_diz_a_hora_da_prova_reaproveitada_e_corta_em_10():
    pend = [(_ag(1), PAGO, None), (_ag(2, "L2"), PAGO, None), (_ag(3, "L3"), PAGO, None)]
    p = p67.pergunta_ao_pagar(pend, {1: True, 2: True, 3: True}, {1: "08:12", 2: ""})
    assert "baixa no ERP — lida às 08:12" in p
    assert "baixa no ERP — da última busca" in p
    assert p.count("lida às") == 1 and p.count("da última busca") == 1
    muitos = [(_ag(i, f"L{i}"), PAGO, None) for i in range(1, 14)]
    p = p67.pergunta_ao_pagar(muitos, {i: True for i in range(1, 14)})
    assert p.startswith("Gravar 13 como pago?") and p.count("•") == 10 and "e mais 3" in p


def test_respondido_volta_desmarcado_e_nao_entra_no_proximo_pago():
    antes = [(_ag(1), PAGO, None), (_ag(2, "L2"), PAGO, None)]
    marcas = p67.marcas_iniciais(antes)
    assert marcas == {1: True, 2: True}
    reag = ag.Resposta(id=7, agendado_id=1, resposta="reagendado", motivo="sem saldo",
                       nova_data=DIA)
    depois = [(_ag(1), PAGO, reag), (_ag(2, "L2"), PAGO, None)]
    marcas = p67.marcas_iniciais(depois, marcas, antes)
    assert marcas == {1: False, 2: True}
    assert p67.pagos_marcados(depois, marcas) == [(2, ag.PROVA_BAIXA)]
    # Sem resposta nova, a marca do dono continua.
    assert p67.marcas_iniciais(depois, {1: True, 2: False}, depois) == {1: True, 2: False}


def test_registro_das_respostas_leva_favorecido_e_valor():
    pend = [(_ag(1), PAGO, None), (_ag(2, "L2", "35.50"), AGUARDA, None)]
    assert p67.registro_das_respostas(pend, ("pago", [1, 2])) == [
        "pago: Fornecedor Modelo Ltda R$ 100,00", "pago: Fornecedor Modelo Ltda R$ 35,50"]
    assert p67.registro_das_respostas(pend, ("nao_saiu", [2])) == [
        "não saiu: Fornecedor Modelo Ltda R$ 35,50"]
    c = _Cliente()
    assert p67.responder_um(c, 5, "reagendado", motivo="x y z", nova_data=DIA) == [5]


class _Cliente:
    def __init__(self, falhar_no=None):
        self.respondidos, self.falhar_no = [], falhar_no

    def responder(self, agendado_id, resposta, *, motivo="", nova_data=None, prova=""):
        if agendado_id == self.falhar_no:
            raise rest.ErroDaNuvem("HTTP 500")
        self.respondidos.append((agendado_id, resposta, prova))
        return {"id": len(self.respondidos)}


def test_responder_pagos_grava_um_a_um_e_conta_o_que_entrou_antes_do_erro():
    c = _Cliente()
    assert p67.responder_pagos(c, [(1, ag.PROVA_BAIXA), (2, "")]) == [1, 2]
    assert c.respondidos == [(1, "pago", ag.PROVA_BAIXA), (2, "pago", "")]
    c = _Cliente(falhar_no=2)
    with pytest.raises(p67.ParouNoMeio) as e:
        p67.responder_pagos(c, [(1, ""), (2, ""), (3, "")])
    assert e.value.gravados == [1]
    recado = p67.recado_do_erro(e.value, "Não gravei na nuvem.")
    assert recado.startswith("Não gravei na nuvem.") and "1 de 3" in recado


def test_resposta_da_selecao_valida_motivo_e_data():
    pend = [(_ag(1), AGUARDA, None)]
    assert p67.recusa_da_resposta(pend, None, "nao_saiu", "", None, HOJE)
    assert p67.recusa_da_resposta(pend, 1, "nao_saiu", "ok", None, HOJE)          # motivo curto
    assert p67.recusa_da_resposta(pend, 1, "nao_saiu", "sem saldo", None, HOJE) == ""
    assert p67.recusa_da_resposta(pend, 1, "reagendado", "sem saldo", date(2026, 10, 22), HOJE)
    assert p67.recusa_da_resposta(pend, 1, "reagendado", "sem saldo", HOJE, HOJE) == ""
    assert p67.recusa_da_resposta(pend, 7, "pago", "", None, HOJE)                # não pendente


# ------------------------------------------------------------- passo 6
def _pm(alvo, marcado=True, ja=False, valor="10.00"):
    return ag.ParaMarcar(alvo=alvo, conta="ERP A", rotulo="Conta Alfa - Banco",
                         lancamento_id=alvo, a_mao_id=None, favorecido="Fornecedor Modelo Ltda",
                         valor=D(valor), descricao="", tipo="", foto={}, marcado=marcado,
                         ja_marcado=ja)


def test_para_marcar_alterna_mas_nao_o_ja_marcado_e_nao_altera_o_recebido():
    itens = [_pm("L1"), _pm("L2", marcado=False, ja=True)]
    novos, recado = p67.alternar_para_marcar(itens, 0)
    assert recado == "" and not novos[0].marcado and itens[0].marcado
    mesmos, recado = p67.alternar_para_marcar(itens, 1)
    assert recado and "reagendado" in recado and not mesmos[1].marcado
    linhas = p67.linhas_para_marcar(itens)
    assert linhas[0].valores[0] == p67.MARCADO and linhas[1].tags == ("info",)
    assert "já marcado hoje" in linhas[1].valores[4]


def test_remontar_para_marcar_guarda_o_desmarcado_pelo_dono():
    antigos = [_pm("L1", marcado=False), _pm("L2")]
    novos = [_pm("L1"), _pm("L2", marcado=False, ja=True), _pm("L3")]
    r = p67.remontar_para_marcar(novos, antigos)
    assert [(i.alvo, i.marcado, i.ja_marcado) for i in r] == [
        ("L1", False, False), ("L2", False, True), ("L3", True, False)]
    assert novos[0].marcado                              # não altera o recebido


def test_gravar_agendados_recusa_lista_vazia():
    assert p67.recusa_de_marcar(None)
    assert p67.recusa_de_marcar([_pm("L1", marcado=False), _pm("L2", marcado=False, ja=True)])
    assert p67.recusa_de_marcar([_pm("L1")]) == ""


def test_resumo_da_marcacao_conta_as_gravadas_e_avisa_as_repetidas():
    linhas = p67.resumo_da_marcacao(([{"id": 1}, {"id": 2}], [{"favorecido": "Fulano Ficticio",
                                                                 "valor": "10.00"}]))
    assert linhas[0].startswith("2 agendado")
    assert "1 pagamento já estava marcado hoje" in linhas[1]
    assert p67.resumo_da_marcacao(([], [])) == ["Nenhum agendado novo gravado."]


def test_erro_ao_marcar_conta_o_que_gravou_e_as_repetidas():
    e = rest.ErroDaNuvem("HTTP 400")
    e.gravadas, e.repetidas = [{"id": 1}], [{"favorecido": "Fulano Ficticio", "valor": "5.00"}]
    recado = p67.recado_do_erro(e, "Não gravei na nuvem.")
    assert "1 agendado(s) já tinham entrado" in recado and "já estava marcado" in recado
    # Erro que não leva nada: só o recado de base.
    assert p67.recado_do_erro(rest.ErroDaNuvem("x"), "Base.") == "Base."
    assert p67.recado_do_erro(rest.ErroDaNuvem("x"), "Base.", depois="Copiada.") == "Base.\n\nCopiada."


# ------------------------------------------------------------- passo 7
def _l(rotulo, ordinal=None, nome=None, sem=False, valor="10"):
    return ldr.LinhaDaLista(rotulo, nome or rotulo, D(valor), ordinal, sem)


def test_mover_nao_cruza_a_fronteira_numerado_sem_ordinal():
    linhas = [_l("A", 1), _l("B", 2), _l("C"), _l("D")]
    assert p67.pode_mover(linhas, 0, 1) and p67.pode_mover(linhas, 2, 1)
    assert not p67.pode_mover(linhas, 1, 1)               # 2º → demais
    assert not p67.pode_mover(linhas, 2, -1)              # demais → numerados
    assert not p67.pode_mover(linhas, 0, -1) and not p67.pode_mover(linhas, 3, 1)
    assert not p67.pode_mover(linhas, None, 1)


def test_botoes_da_lista():
    linhas = [_l("A", 1), _l("B")]
    b = p67.botoes_da_lista(linhas, 0, ligado=True)
    assert b == {"subir": False, "descer": False, "ordinal": True, "nome": True, "copiar": True,
                 "sugestoes": False}
    assert not any(p67.botoes_da_lista(linhas, 0, ligado=False).values())
    b = p67.botoes_da_lista(linhas, None, ligado=True)
    assert b["copiar"] and not b["nome"] and not b["ordinal"]
    assert not p67.botoes_da_lista([], None, ligado=True)["copiar"]


def test_copiar_recusa_linha_sem_nome_curto():
    assert p67.recusa_de_copiar([]) != ""
    recado = p67.recusa_de_copiar([_l("Conta Alfa - Banco", sem=True), _l("B", nome="Beta")])
    assert "Conta Alfa - Banco" in recado and "Nome curto" in recado
    assert p67.recusa_de_copiar([_l("B", nome="Beta")]) == ""


def test_nome_curto_recusa_controle_e_nome_de_outra_conta():
    linhas = [_l("Conta Alfa - Banco", nome="Alfa"), _l("Conta Beta - Banco", sem=True)]
    nomes = {"Conta Alfa - Banco": "Alfa", "Conta Gama - Banco": "Gama"}
    v = p67.validar_nome_curto
    assert v("Beta", "Conta Beta - Banco", nomes, linhas) == ""
    assert v("Be\tta", "Conta Beta - Banco", nomes, linhas)
    assert v("Beta\n", "Conta Beta - Banco", nomes, linhas)
    assert v("Be\rta", "Conta Beta - Banco", nomes, linhas)
    assert v(" alfa ", "Conta Beta - Banco", nomes, linhas)       # de outra conta
    assert v("GAMA", "Conta Beta - Banco", nomes, linhas)         # de conta fora de hoje
    assert v("Alfa", "Conta Alfa - Banco", nomes, linhas) == ""    # o dela mesma
    assert v("", "Conta Beta - Banco", nomes, linhas)
    assert v("x" * 61, "Conta Beta - Banco", nomes, linhas)


def test_montar_lista_sugere_ontem_e_guarda_a_ordem_do_dono():
    hoje = [_ag(1, "L1", "10.00", "ERP A"), _ag(2, "L2", "30.00", "ERP B"),
            _ag(3, "L3", "20.00", "ERP C")]
    rot = {"ERP A": "A", "ERP B": "B", "ERP C": "C"}.get
    ontem = [{"conta": "C", "ordinal": 1}]
    lista = p67.montar_lista(hoje, rot, {"A": "Alfa"}, ontem)
    assert [(l.rotulo, l.ordinal) for l in lista] == [("C", 1), ("B", None), ("A", None)]
    # O dono arrumou: A ganha ordinal. Releitura (nome curto novo) mantém.
    arrumada = ldr.alternar_ordinal(lista, 2)
    de_novo = p67.montar_lista(hoje, rot, {"A": "Alfa", "B": "Beta"}, ontem, atual=arrumada)
    assert [(l.rotulo, l.ordinal, l.nome) for l in de_novo] == [
        ("C", 1, "C"), ("A", 2, "Alfa"), ("B", None, "Beta")]


# ----------------------------------------------------------- releitura
class _Nuvem:
    def __init__(self, de_hoje=(), abertos=(), respostas=()):
        self._hoje, self._abertos, self._resp = list(de_hoje), list(abertos), list(respostas)

    def decisoes_do_dia(self, dia): return [{"id": 1, "alvo": "L5", "acao": "liberar",
                                             "motivo": "ok"}]
    def pagamentos_a_mao(self, dia): return []
    def agendados_do_dia(self, dia): return self._hoje
    def agendados_em_aberto(self): return self._abertos
    def respostas(self, ids): return [r for r in self._resp if r["agendado_id"] in ids]
    def nomes_curtos(self): return {"Conta Alfa - Banco": "Alfa"}
    def lista_anterior(self, dia): return [{"conta": "Conta Alfa - Banco", "ordinal": 1}]


def test_reler_tudo_traz_agendados_nomes_lista_e_nunca_diz_sumiu_sem_reler():
    anterior = nd.LidoDaNuvem(Conferencia(), pendentes=[(_ag(1, "L1"), PAGO, None)],
                              lido_em="08:12")
    nuvem = _Nuvem(de_hoje=[_linha(2, "L2"), _linha(3, "L3")],
                   abertos=[_linha(1, "L1", dia="2026-10-22"), _linha(2, "L2"), _linha(3, "L3")],
                   respostas=[{"id": 1, "agendado_id": 3, "resposta": "pago"}])
    # L2 está na leitura do dia (aberto, mesmo valor); L1 não está, mas já
    # tinha situação da leitura completa (reaproveitada, nada se inventa).
    lido = p67.reler_tudo(nuvem, DIA, anterior,
                          [{"id": "L2", "paid": False, "remainingValue": 100.0}])
    assert lido.erro == "" and "L5" in lido.conferencia.decisoes
    assert [a.alvo for a in lido.agendados_hoje] == ["L2", "L3"]
    assert lido.nomes_curtos == {"Conta Alfa - Banco": "Alfa"} and lido.lista_anterior
    pend = {a.alvo: s for a, s, _r in lido.pendentes}
    assert set(pend) == {"L1", "L2"}                      # L3 respondido pago
    assert pend["L1"] is PAGO
    assert pend["L2"].frase == "aguardando — responda" and not pend["L2"].pre_marca
    assert lido.lido_em == "08:12" and lido.provas_de == {1: "08:12", 2: "08:12"}
    # Segunda releitura: a hora continua a da leitura de onde a prova veio.
    assert p67.reler_tudo(nuvem, DIA, lido, []).provas_de[1] == "08:12"
    # Pendente novo FORA da leitura do dia: "não reli", nunca "sumiu".
    lido = p67.reler_tudo(nuvem, DIA, None, [])
    pend = {a.alvo: s for a, s, _r in lido.pendentes}
    assert "não reli" in pend["L2"].frase and "sumiu" not in pend["L1"].frase


def test_gravar_e_reler_com_reler_tudo():
    nuvem = _Nuvem(de_hoje=[_linha(2, "L2")], abertos=[_linha(2, "L2")])
    g = passo2.gravar_e_reler(nuvem, DIA, lambda c: ([{"id": 2}], []),
                              reler=lambda c, d: p67.reler_tudo(c, d, None, []))
    assert isinstance(g.conferencia, nd.LidoDaNuvem) and g.erro == "" and not g.travar
    assert [a.alvo for a in g.conferencia.agendados_hoje] == ["L2"]


# ------------------------------------- "Pago" em lote que para no meio (22/10)
def test_pago_que_para_no_meio_lista_no_registro_cada_um_ja_gravado():
    """O recado dizia só "Gravei 2 de 3"; o Registro passa a dizer QUAIS
    (favorecido e valor), para o dono não responder duas vezes."""
    pend = [(_ag(1), PAGO, None), (_ag(2, "L2", "35.50"), PAGO, None),
            (_ag(3, "L3", "7.00"), PAGO, None)]
    c = _Cliente(falhar_no=3)
    g = passo2.gravar_e_reler(c, DIA, lambda cli: ("pago", p67.responder_pagos(
        cli, [(1, ""), (2, ""), (3, "")])), recado=str, reler=lambda cli, d: "relido")
    assert g.erro and g.gravado == ("pago", [1, 2])
    assert p67.registro_do_parcial(pend, g.gravado) == [
        "já gravado antes do erro — pago: Fornecedor Modelo Ltda R$ 100,00",
        "já gravado antes do erro — pago: Fornecedor Modelo Ltda R$ 35,50"]
    # Nada entrou antes do erro: nada a listar (nem "Nenhuma resposta gravada").
    assert p67.registro_do_parcial(pend, ("pago", [])) == []
    assert p67.registro_do_parcial(pend, None) == []


def test_erro_comum_nao_inventa_gravado_parcial():
    def quebra(_c):
        raise rest.ErroDaNuvem("HTTP 500")
    g = passo2.gravar_e_reler(_Cliente(), DIA, quebra, reler=lambda cli, d: "relido")
    assert g.erro and g.gravado is None


def test_frame_poe_o_parcial_no_registro():
    import ast
    from pathlib import Path
    fonte = (Path(__file__).resolve().parents[1] / "tela_do_dia" / "frame.py"
             ).read_text(encoding="utf-8")
    metodo = next(n for n in ast.walk(ast.parse(fonte))
                  if isinstance(n, ast.FunctionDef) and n.name == "_receber_gravacao")
    chamadas = [n.func.attr for n in ast.walk(metodo)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert "registro_do_parcial" in chamadas


def test_gravar_sugestoes_so_com_linha_sugerida():
    sug = ldr.LinhaDaLista("Obra Beta - Sicoob", "Obra Beta", D("1"), sugerido=True)
    gravada = _l("B", nome="Beta")
    assert p67.botoes_da_lista([sug, gravada], None, ligado=True)["sugestoes"]
    assert not p67.botoes_da_lista([sug], None, ligado=False)["sugestoes"]
    assert not p67.botoes_da_lista([gravada], None, ligado=True)["sugestoes"]
    assert p67.sugestoes_a_gravar([sug, gravada]) == [("Obra Beta - Sicoob", "Obra Beta")]


def test_copiar_aceita_lista_so_com_sugestoes():
    sug = ldr.LinhaDaLista("Obra Beta - Sicoob", "Obra Beta", D("1"), sugerido=True)
    assert p67.recusa_de_copiar([sug]) == ""
