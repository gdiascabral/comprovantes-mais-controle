# -*- coding: utf-8 -*-
"""Aportes: lançamento de resultado INCERTO não se relança sem conferir.

Achado do revisor no PR #134: se o Chrome morre no meio de um `criar_*` (o
POST já pode ter chegado ao ERP), sai um erro do Playwright — não
`ErroLancamento` —, o `id_criado` se perde e `criados` não ganha o item. Antes
do #134 o Lançar seguinte morria cedo (catálogo preso à página velha); depois
dele, relê o cadastro e cria a MESMA venda outra vez. Dinheiro duplicado se
desfaz à mão, lançamento por lançamento.
"""
from decimal import Decimal
from types import SimpleNamespace

from playwright.sync_api import Error as PlaywrightError

from aportes import aportes_frame as af
from aportes import mc_lancamentos
from tests.test_aportes_regras import HOJE, _CatalogosFalso

_MSG = "Target page, context or browser has been closed"


# ------------------------------------------------- a baixa do recebimento
class _CatBaixaMorre(_CatalogosFalso):
    """POST /sales responde com a parcela aberta; a baixa encontra o Chrome morto."""

    def postar(self, url, corpo):
        self.postagens.append(url)
        if len(self.postagens) == 1:
            return self._resposta
        raise PlaywrightError(_MSG)


def test_baixa_que_estoura_devolve_a_venda_criada():
    cat = _CatBaixaMorre({"id": "venda-1",
                          "installments": [{"id": "p1", "isReceived": False}]})
    r = mc_lancamentos.criar_recebimento(
        cat, data=HOJE, valor=Decimal("100.00"), descricao="APORTE",
        conta_recebedora="BANCO", cliente="EMPRESA A", natureza="APORTE",
        forma="TED", obra="OBRA 1", id_usuario="u1")
    assert not r.ok
    assert r.id_criado == "venda-1"          # é isso que impede a 2ª venda
    assert "baixa" in (r.erro or "")
    assert len(cat.postagens) == 2


# ------------------------------------------------------------- a aba
class _Pagina:
    def is_closed(self):
        return False

    def evaluate(self, *_a, **_k):
        return {}


class _Anx:
    def __init__(self, page):
        self.mc = SimpleNamespace(page=page, garantir_login=lambda: True)

    def garantir_sessao(self, _log):
        return object()

    def dona_ocupada(self, aba=None):
        return None                    # nenhum comando rodando


def _aba(raiz, monkeypatch, n_itens, criar):
    pagina = _Pagina()
    aba = af.AportesFrame(raiz, _Anx(pagina))
    aba.anotado = []
    monkeypatch.setattr(aba, "_log", lambda txt="", *_a, **_k: aba.anotado.append(str(txt)))
    monkeypatch.setattr(aba, "_rateios_frescos", lambda: None)
    monkeypatch.setattr(af.widgets, "registrar_atividade", lambda *a, **k: None)
    monkeypatch.setattr(af, "expandir", lambda *a, **k: [
        {"tipo_lancamento": "pagamento", "valor": Decimal("10.00")}
        for _ in range(n_itens)])
    monkeypatch.setattr(af, "criar_pagamento", criar)
    aba.catalogos = SimpleNamespace(pagina=pagina, cabecalho=lambda _n: "u1")
    aba.operacoes = [SimpleNamespace(valor=Decimal("10.00") * n_itens, pagador="p",
                                     resumo=lambda: "op")]
    aba.criados = [set()]
    aba.incertos = [set()]
    return aba


def _ok(*_a, **_k):
    return SimpleNamespace(ok=True, id_criado="1", erro=None)


def test_erro_inesperado_no_criar_marca_incerto_e_para(raiz, monkeypatch):
    chamadas = []

    def criar(catalogos, id_usuario, **item):
        chamadas.append(item)
        if len(chamadas) == 2:
            raise PlaywrightError(_MSG)
        return _ok()

    aba = _aba(raiz, monkeypatch, 3, criar)
    try:
        aba._t_lancar()
        assert len(chamadas) == 2                # o 3º não foi tentado
        assert aba.criados == [{0}]
        assert aba.incertos == [{1}]
        texto = "\n".join(aba.anotado)
        assert "INCERTO" in texto
        assert "Confira no Mais Controle" in texto
    finally:
        aba.destroy()


def test_lancar_de_novo_nao_relanca_o_incerto(raiz, monkeypatch):
    chamadas = []

    def criar(catalogos, id_usuario, **item):
        chamadas.append(item)
        return _ok()

    aba = _aba(raiz, monkeypatch, 3, criar)
    try:
        aba.criados = [{0}]
        aba.incertos = [{1}]
        aba._t_lancar()
        assert len(chamadas) == 1                # só o item 2, nunca tentado
        assert aba.criados == [{0, 2}]
        assert aba.incertos == [{1}]
        assert any("incerto" in t.lower() for t in aba.anotado)
    finally:
        aba.destroy()


def test_operacao_com_incerto_nao_sai_da_lista_como_concluida(raiz, monkeypatch):
    aba = _aba(raiz, monkeypatch, 2, _ok)
    try:
        aba.criados = [{0}]
        aba.incertos = [{1}]
        aba._retirar_concluidas()
        assert len(aba.operacoes) == 1           # fica à vista até conferir
        assert aba.incertos == [{1}]
    finally:
        aba.destroy()


def test_remover_e_limpar_levam_os_incertos_junto(raiz, monkeypatch):
    aba = _aba(raiz, monkeypatch, 1, _ok)
    try:
        aba._limpar()
        assert aba.incertos == [] and aba.criados == []
    finally:
        aba.destroy()


# --------------------------------------------- aba do robô fechada pela pessoa
class _PaginaFechada(_Pagina):
    def is_closed(self):
        return True


def test_catalogos_de_pagina_fechada_sao_relidos_mesmo_sendo_a_mesma(raiz, monkeypatch):
    fechada = _PaginaFechada()
    aba = af.AportesFrame(raiz, _Anx(fechada))
    novo = SimpleNamespace(pagina=fechada)
    leituras = []
    monkeypatch.setattr(aba, "_log", lambda *_a, **_k: None)
    monkeypatch.setattr(aba, "_ler_cadastros", lambda: leituras.append(1) or novo)
    monkeypatch.setattr(aba, "_carregar_obras", lambda api: None)
    try:
        aba.catalogos = SimpleNamespace(pagina=fechada)
        aba._preparar_sessao()
        assert leituras == [1]
        assert aba.catalogos is novo
    finally:
        aba.destroy()


# --------------------------------------- resolver o incerto sem Remover (2ª revisão)
def _aba_lista(raiz, monkeypatch, respostas):
    """Aba no ponto do clique em Lançar, com um incerto na posição 1."""
    aba = _aba(raiz, monkeypatch, 3, _ok)
    aba.criados = [{0}]
    aba.incertos = [{1}]
    fila = list(respostas)
    aba.perguntas = []

    def pergunta(titulo, texto, **_k):
        aba.perguntas.append(texto)
        return fila.pop(0)

    monkeypatch.setattr(af.messagebox, "askyesnocancel", pergunta)
    monkeypatch.setattr(af.messagebox, "askyesno", lambda *a, **k: False)
    monkeypatch.setattr(af.messagebox, "showinfo", lambda *a, **k: None)
    return aba


def test_lancar_pergunta_o_incerto_e_entrou_vira_criado(raiz, monkeypatch):
    aba = _aba_lista(raiz, monkeypatch, [True])
    try:
        aba._lancar()
        assert len(aba.perguntas) == 1
        assert "10,00" in aba.perguntas[0]
        assert aba.criados == [{0, 1}] and aba.incertos == [set()]
    finally:
        aba.destroy()


def test_lancar_pergunta_o_incerto_e_nao_entrou_volta_a_lancar(raiz, monkeypatch):
    aba = _aba_lista(raiz, monkeypatch, [False])
    try:
        aba._lancar()
        assert aba.criados == [{0}] and aba.incertos == [set()]
    finally:
        aba.destroy()


def test_lancar_sem_conferir_mantem_o_incerto(raiz, monkeypatch):
    aba = _aba_lista(raiz, monkeypatch, [None])
    try:
        aba._lancar()
        assert aba.criados == [{0}] and aba.incertos == [{1}]
    finally:
        aba.destroy()


def test_recado_do_incerto_nao_manda_remover_a_operacao(raiz, monkeypatch):
    def criar(catalogos, id_usuario, **item):
        raise PlaywrightError(_MSG)

    aba = _aba(raiz, monkeypatch, 1, criar)
    try:
        aba._t_lancar()
        texto = "\n".join(aba.anotado).lower()
        assert "tire a operação" not in texto
        assert "lançar de novo" in texto
    finally:
        aba.destroy()


def test_subconta_com_incerto_conta_como_em_andamento(raiz, monkeypatch):
    aba = _aba(raiz, monkeypatch, 2, _ok)
    monkeypatch.setattr(af, "numero_subconta", lambda pagador, subcontas: "7")
    try:
        aba.criados = [set()]
        aba.incertos = [{0}]
        assert aba._subconta_em_andamento("7")
    finally:
        aba.destroy()


# ------------------------------------- a lista não muda com o Lançar rodando
def test_remover_e_limpar_recusam_com_o_lancar_rodando(raiz, monkeypatch):
    aba = _aba(raiz, monkeypatch, 1, _ok)
    aba.anx.dona_ocupada = lambda aba=None: aba
    avisos = []
    monkeypatch.setattr(af.messagebox, "showinfo", lambda *a, **k: avisos.append(a))
    try:
        aba.tabela.insert("", "end", values=("op",))
        aba.tabela.selection_set(aba.tabela.get_children())
        aba._remover()
        aba._limpar()
        assert len(aba.operacoes) == 1
        assert aba.criados == [set()] and aba.incertos == [set()]
        assert len(avisos) == 2
    finally:
        aba.destroy()
