# -*- coding: utf-8 -*-
"""Aportes: a marca de "criado"/"incerto" leva a ASSINATURA do lançamento.

`criados`/`incertos` guardam a POSIÇÃO de cada item do `expandir`. A trava
contra rateio trocado no meio (`_subconta_em_andamento`) só roda no
`_rateios_frescos` e no novo cadastro de investidor; o "Atualizar contas"
refaz `self.subcontas` sem passar por ela, e o Lançar seguinte pulava uma
posição que passou a querer dizer outro par (CC × investidor) e criava as
outras com o valor redividido — valor acima do aporte, ou par duplicado.

Agora cada marca guarda (tipo, conta, CC/obra, participante, valor), e a
operação cujo `expandir` não bate mais com as marcas é recusada — no Lançar,
na pergunta do incerto e na saída da lista — com o recado de conferir no ERP.

Nomes fictícios: o repositório é público."""
from __future__ import annotations

import datetime
from decimal import Decimal
from types import SimpleNamespace

from playwright.sync_api import Error as PlaywrightError

from aportes import aportes_frame as af
from aportes import regras
from aportes.regras import Operacao

ENT = {"SUBCONTA 11111-1 - BANCO - INVESTIDOR": {
    "nome_oficial": "HOLDING", "conta": "Holding - SUBCONTA 11111-1",
    "nome_descricao": None}}
#: Dois aportadores, um CC: posição 0 = INV A, posição 1 = INV B.
SUB_ANTES = {"11111-1": {"obras": ["LOTE 1"],
                         "investidores": ["INV A", "INV B"]}}
#: O mesmo aporte depois do "Atualizar contas": os aportadores trocaram de
#: lugar. A posição 0 passou a ser INV B — pular a 0 deixaria INV B de fora
#: e lançar a 1 criaria INV A pela segunda vez.
SUB_TROCADO = {"11111-1": {"obras": ["LOTE 1"],
                           "investidores": ["INV B", "INV A"]}}
#: Peso novo: os pares são os mesmos, os valores não.
SUB_PESO = {"11111-1": {"obras": ["LOTE 1"],
                        "investidores": ["INV A", "INV B"],
                        "pesos": {"INV A": "3", "INV B": "1"}}}


def _op():
    return Operacao(data=datetime.date(2026, 10, 1),
                    pagador="INVESTIDOR SUBCONTA 11111-1",
                    recebedor="SUBCONTA 11111-1 - BANCO - INVESTIDOR",
                    valor=Decimal("1000.00"), tipo=regras.TIPO_INVESTIDOR,
                    modo="Só recebimento")


# ------------------------------------------------------------ a assinatura
def test_assinatura_do_recebimento_tem_conta_cc_participante_valor_tipo():
    item = regras.expandir(_op(), ENT, SUB_ANTES, "PADRAO")[0]
    assert af.assinatura(item) == (
        "recebimento", "Holding - SUBCONTA 11111-1", "LOTE 1", "INV A",
        Decimal("500.00"))


def test_assinatura_do_pagamento_usa_a_conta_pagadora_e_o_favorecido():
    item = {"tipo_lancamento": "pagamento", "conta_pagadora": "CONTA P",
            "favorecido": "EMPRESA F", "obra": "OBRA", "valor": Decimal("1.50"),
            "descricao": "não entra", "data": datetime.date(2026, 10, 1)}
    assert af.assinatura(item) == ("pagamento", "CONTA P", "OBRA", "EMPRESA F",
                                   Decimal("1.50"))


def test_assinatura_muda_quando_o_par_ou_o_valor_muda():
    antes = [af.assinatura(i) for i in regras.expandir(_op(), ENT, SUB_ANTES, "P")]
    trocado = [af.assinatura(i) for i in regras.expandir(_op(), ENT, SUB_TROCADO, "P")]
    peso = [af.assinatura(i) for i in regras.expandir(_op(), ENT, SUB_PESO, "P")]
    assert antes[0] != trocado[0] and antes[1] != trocado[1]
    assert antes[0] != peso[0]


# ------------------------------------------------------------- a aba
class _Pagina:
    def is_closed(self):
        return False


class _Anx:
    def __init__(self, page):
        self.mc = SimpleNamespace(page=page, garantir_login=lambda: True)

    def garantir_sessao(self, _log):
        return object()

    def dona_ocupada(self, aba=None):
        return None


def _aba(raiz, monkeypatch, criar):
    """Aba com UM aporte de investidor na lista e o `expandir` de verdade."""
    pagina = _Pagina()
    aba = af.AportesFrame(raiz, _Anx(pagina))
    aba.anotado = []
    aba.avisos = []
    monkeypatch.setattr(aba, "_log",
                        lambda txt="", *_a, **_k: aba.anotado.append(str(txt)))
    monkeypatch.setattr(aba, "_rateios_frescos", lambda: None)
    monkeypatch.setattr(af.widgets, "registrar_atividade", lambda *a, **k: None)
    monkeypatch.setattr(af.messagebox, "showwarning",
                        lambda *a, **k: aba.avisos.append(a))
    monkeypatch.setattr(af, "criar_recebimento", criar)
    cat = SimpleNamespace(pagina=pagina, cabecalho=lambda _n: "u1")
    aba.catalogos = cat
    # O "Atualizar contas" zera os catálogos; a releitura volta com estes.
    monkeypatch.setattr(aba, "_preparar_sessao",
                        lambda recarregar=False: setattr(aba, "catalogos", cat))
    aba.entidades = dict(ENT)
    aba.subcontas = {k: dict(v) for k, v in SUB_ANTES.items()}
    aba.obra_padrao = "PADRAO"
    aba.operacoes = [_op()]
    aba.criados = [set()]
    aba.incertos = [set()]
    aba.assinaturas = [{}]
    return aba


def _so_o_primeiro_entra(chamadas):
    """O primeiro recebimento entra; no segundo o navegador cai."""
    def criar(catalogos, id_usuario, **item):
        chamadas.append(item)
        if len(chamadas) == 1:
            return SimpleNamespace(ok=True, id_criado="v1", erro=None)
        raise PlaywrightError("Target page, context or browser has been closed")
    return criar


def test_lancar_guarda_a_assinatura_do_criado_e_do_incerto(raiz, monkeypatch):
    chamadas = []
    aba = _aba(raiz, monkeypatch, _so_o_primeiro_entra(chamadas))
    try:
        aba._t_lancar()
        itens = regras.expandir(_op(), ENT, SUB_ANTES, "PADRAO")
        assert aba.criados == [{0}] and aba.incertos == [{1}]
        assert aba.assinaturas == [{0: af.assinatura(itens[0]),
                                    1: af.assinatura(itens[1])}]
    finally:
        aba.destroy()


def test_atualizar_contas_trocando_o_rateio_recusa_o_lancar(raiz, monkeypatch):
    """O furo: criado o par (LOTE 1, INV A) e incerto o (LOTE 1, INV B), o
    "Atualizar contas" troca a ordem dos aportadores. Sem a assinatura, o
    Lançar seguinte pulava as posições 0 e 1 — que agora dizem outros pares —
    e, com a resposta "não entrou", criava INV A de novo."""
    chamadas = []
    aba = _aba(raiz, monkeypatch, _so_o_primeiro_entra(chamadas))
    try:
        aba._t_lancar()
        assert len(chamadas) == 2
        monkeypatch.setattr(af.cadastro, "carregar_contas", lambda: dict(ENT))
        monkeypatch.setattr(af.cadastro, "carregar_subcontas",
                            lambda: {k: dict(v) for k, v in SUB_TROCADO.items()})
        monkeypatch.setattr(af.cadastro, "config_obra_padrao", lambda: "PADRAO")
        aba.recarregar_contas()                  # o "Atualizar contas"
        aba.incertos = [set()]                   # "não entrou" na pergunta
        aba.assinaturas[0].pop(1)
        aba._t_lancar()
        assert len(chamadas) == 2                # nada novo foi ao ERP
        texto = "\n".join(aba.anotado)
        assert "Confira no Mais Controle" in texto
        assert "rateio" in texto.lower()
        assert aba.criados == [{0}]
    finally:
        aba.destroy()


def test_peso_novo_nos_mesmos_pares_tambem_recusa(raiz, monkeypatch):
    chamadas = []
    aba = _aba(raiz, monkeypatch, _so_o_primeiro_entra(chamadas))
    try:
        aba._t_lancar()
        aba.subcontas = {k: dict(v) for k, v in SUB_PESO.items()}
        aba.incertos = [set()]
        aba.assinaturas[0].pop(1)
        aba._t_lancar()
        assert len(chamadas) == 2                # INV B não sai com 250
    finally:
        aba.destroy()


def test_rateio_igual_continua_lancando_o_que_falta(raiz, monkeypatch):
    chamadas = []
    aba = _aba(raiz, monkeypatch, _so_o_primeiro_entra(chamadas))
    try:
        aba._t_lancar()
        aba.incertos = [set()]                   # "não entrou"
        aba.assinaturas[0].pop(1)
        monkeypatch.setattr(af, "criar_recebimento", lambda c, id_usuario, **i: (
            chamadas.append(i) or SimpleNamespace(ok=True, id_criado="v2", erro=None)))
        aba._t_lancar()
        assert [c["cliente"] for c in chamadas] == ["INV A", "INV B", "INV B"]
        assert aba.criados == [{0, 1}]
    finally:
        aba.destroy()


def test_marca_sem_assinatura_e_recusada(raiz, monkeypatch):
    """Marca sem assinatura não se confere: recusar é o lado seguro."""
    chamadas = []
    aba = _aba(raiz, monkeypatch, _so_o_primeiro_entra(chamadas))
    try:
        aba.criados = [{0}]
        aba.assinaturas = [{}]
        aba._t_lancar()
        assert chamadas == []
    finally:
        aba.destroy()


def test_outra_operacao_da_lista_segue_normalmente(raiz, monkeypatch):
    chamadas = []
    aba = _aba(raiz, monkeypatch, lambda c, id_usuario, **i: (
        chamadas.append(i) or SimpleNamespace(ok=True, id_criado="v", erro=None)))
    try:
        itens = regras.expandir(_op(), ENT, SUB_ANTES, "PADRAO")
        aba.operacoes = [_op(), _op()]
        aba.criados = [{0}, set()]
        aba.incertos = [set(), set()]
        aba.assinaturas = [{0: af.assinatura(itens[0])}, {}]
        aba.subcontas = {k: dict(v) for k, v in SUB_TROCADO.items()}
        aba._t_lancar()
        # A 1ª é recusada; a 2ª, sem marca nenhuma, sai inteira pelo atual.
        assert [c["cliente"] for c in chamadas] == ["INV B", "INV A"]
        assert aba.criados == [{0}, {0, 1}]
    finally:
        aba.destroy()


def test_pergunta_do_incerto_recusa_quando_o_rateio_mudou(raiz, monkeypatch):
    chamadas = []
    aba = _aba(raiz, monkeypatch, _so_o_primeiro_entra(chamadas))
    perguntas = []
    monkeypatch.setattr(af.messagebox, "askyesnocancel",
                        lambda *a, **k: perguntas.append(a) or True)
    try:
        aba._t_lancar()
        aba.subcontas = {k: dict(v) for k, v in SUB_TROCADO.items()}
        aba._resolver_incertos()
        assert perguntas == []                   # não pergunta por outro par
        assert aba.criados == [{0}] and aba.incertos == [{1}]
        assert aba.avisos and "Mais Controle" in aba.avisos[0][1]
    finally:
        aba.destroy()


def test_entrou_na_pergunta_leva_a_assinatura_junto(raiz, monkeypatch):
    chamadas = []
    aba = _aba(raiz, monkeypatch, _so_o_primeiro_entra(chamadas))
    monkeypatch.setattr(af.messagebox, "askyesnocancel", lambda *a, **k: True)
    try:
        aba._t_lancar()
        guardada = aba.assinaturas[0][1]
        aba._resolver_incertos()
        assert aba.criados == [{0, 1}] and aba.incertos == [set()]
        assert aba.assinaturas[0][1] == guardada
    finally:
        aba.destroy()


def test_nao_entrou_na_pergunta_solta_a_assinatura(raiz, monkeypatch):
    chamadas = []
    aba = _aba(raiz, monkeypatch, _so_o_primeiro_entra(chamadas))
    monkeypatch.setattr(af.messagebox, "askyesnocancel", lambda *a, **k: False)
    try:
        aba._t_lancar()
        aba._resolver_incertos()
        assert aba.incertos == [set()]
        assert set(aba.assinaturas[0]) == {0}
    finally:
        aba.destroy()


def test_rateio_trocado_nao_conclui_a_operacao(raiz, monkeypatch):
    """Com as duas posições marcadas e o rateio trocado, a contagem por
    posição dava a operação por concluída e a tirava da lista — sumindo com
    o único lugar onde a pessoa vê que falta conferir."""
    aba = _aba(raiz, monkeypatch, None)
    try:
        itens = regras.expandir(_op(), ENT, SUB_ANTES, "PADRAO")
        aba.criados = [{0, 1}]
        aba.assinaturas = [{0: af.assinatura(itens[0]),
                            1: af.assinatura(itens[1])}]
        aba.subcontas = {k: dict(v) for k, v in SUB_TROCADO.items()}
        aba._retirar_concluidas()
        assert len(aba.operacoes) == 1
    finally:
        aba.destroy()


def test_remover_limpar_e_adicionar_mantem_as_assinaturas_alinhadas(raiz, monkeypatch):
    aba = _aba(raiz, monkeypatch, None)
    monkeypatch.setattr(af.messagebox, "showinfo", lambda *a, **k: None)
    # O total expandiria a operação vazia dos combos; não é o que se mede.
    monkeypatch.setattr(aba, "_atualizar_total", lambda: None)
    try:
        aba._limpar()
        assert aba.assinaturas == []
        aba.var_valor.set("10,00")
        monkeypatch.setattr(Operacao, "validar", lambda *a, **k: [])
        aba._adicionar()
        assert aba.assinaturas == [{}]
        aba.tabela.selection_set(aba.tabela.get_children())
        aba._remover()
        assert aba.assinaturas == [] and aba.operacoes == []
    finally:
        aba.destroy()
