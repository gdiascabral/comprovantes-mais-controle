# -*- coding: utf-8 -*-
"""As duas listas de conferência do Pagamentos do Dia: a confirmação do dia
(passo 2) e a conferência da remessa (passo 3).

A regra de dinheiro — o que entra, o que vem marcado, o que pede olhada, o
NSA previsto por convênio e o que o "Gravar" leva — mora em funções puras e é
testada sem Tk. As janelas são montadas de verdade, mas RETIRADAS (`withdraw`
antes do primeiro `update`), e o `wait_window` do dono é trocado por um
roteiro: a janela abre, o roteiro age como a pessoa, a função devolve.
Marcar é o evento virtual `<<AlternarMarca>>`, o mesmo caminho do Espaço —
janela retirada não recebe tecla.

O teste do TAMANHO é o que dá o motivo de tudo: até 11/09/2026 cada linha era
um bloco de widgets num Canvas rolável, e 300 lançamentos davam 2.802 widgets
(confirmação) e 3.589 (remessa) — 5,4 s e 6,5 s antes de a janela aparecer.
"""
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

from pagamentos_dia import pagamentos_frame as pf
from pagamentos_dia import remessa_dia
from pagamentos_dia.remessa_dia import Candidato


def _lanc(i, conta="CONTA A", favorecido=None, valor=100.0,
          chave="fulano@exemplo.com"):
    """Um lançamento a pagar, no formato da API — com dados de mentira."""
    return {"id": f"L{i}", "tradePayableId": f"T{i}",
            "paidTo": favorecido or f"FORNECEDOR {i:03d}",
            "description": f"MATERIAL OC {1000 + i}",
            "remainingValue": valor, "plannedDate": "2026-09-11",
            "tradePayableAccount": {"name": conta},
            "tradePayablePaymentMethod": "Pix",
            "paidToBankAccount": f"PIX EMAIL {chave}" if chave else "",
            "paid": False}


def _cand(i, conta="CONTA A", **mudancas):
    """Um `Candidato` como o `preparar` o deixa — marcado se é apto, não é
    reembolso nem reenvio, e pode sair — a menos que o teste diga outra
    coisa."""
    campos = dict(id=f"L{i}", conta_erp=conta, tipo="Pix", valor=100.0 + i,
                  favorecido=f"FAVORECIDO {i}", descricao="", status="APTO",
                  chave="fulano@exemplo.com")
    marcado = mudancas.pop("marcado", None)
    campos.update(mudancas)
    c = Candidato(**campos)
    c.marcado = (c.pode and c.apto and not c.reembolso and not c.ja_enviado
                 if marcado is None else marcado)
    return c


# ------------------------------------------------------ confirmação: regras

def test_contas_em_ordem_e_quem_pede_olhada_na_frente():
    alvos = [_lanc(1, "CONTA B", "ZULU MATERIAIS"), _lanc(2, "CONTA A", "BETA"),
             _lanc(3, "CONTA B", "ALFA"), _lanc(4, "CONTA B", "SOCIO FICTICIO")]
    grupos = pf.grupos_para_confirmar(alvos, destacar=["SOCIO FICTICIO"])
    assert [conta for conta, _itens in grupos] == ["CONTA A", "CONTA B"]
    assert [(i["paidTo"], olhar) for i, olhar in grupos[1][1]] == [
        ("SOCIO FICTICIO", True), ("ALFA", False), ("ZULU MATERIAIS", False)]


def test_rodape_e_o_que_volta_saem_das_mesmas_marcas():
    itens = [_lanc(1, valor=100.0), _lanc(2, valor=250.5), _lanc(3, valor=10.0)]
    marcado = [True, False, True]
    assert pf.resumo_da_confirmacao(itens, marcado) == (2, 110.0, 1)
    assert pf.nao_confirmados(itens, marcado) == {"L2"}
    assert pf.nao_confirmados(itens, [True] * 3) == set()


def test_desmarcado_e_vermelho_seja_qual_for_o_dado():
    assert pf.estado_na_confirmacao("ok", True) == "ok"
    assert pf.estado_na_confirmacao("atencao", True) == "atencao"
    assert pf.estado_na_confirmacao("ok", False) == "erro"
    assert pf.estado_na_confirmacao("atencao", False) == "erro"
    assert pf.ESTILO_DO_DADO[pf.estado_na_confirmacao("atencao", False)] \
        == "MonoMiniErro.TLabel"


# --------------------------------------------------------- remessa: regras

class _Historico:
    def __init__(self, proximos):
        self.proximos, self.perguntas = proximos, []

    def proximo_nsa(self, convenio):
        self.perguntas.append(convenio)
        return self.proximos[convenio]


def test_nsa_previsto_e_por_convenio_e_consulta_uma_vez_so():
    pagadores = {"A": SimpleNamespace(convenio="C1"),
                 "B": SimpleNamespace(convenio="C2"),
                 "C": SimpleNamespace(convenio="C1")}
    hist = _Historico({"C1": 31, "C2": 7})
    assert remessa_dia.nsa_previstos(pagadores, hist) == {"A": 31, "B": 7,
                                                          "C": 32}
    assert hist.perguntas == ["C1", "C2"], "cada convênio é perguntado UMA vez"


def test_de_fora_soma_impedidos_de_todas_as_contas_e_os_desmarcados():
    a1, a2, impedido = _cand(1), _cand(2), _cand(3, impedimento="parcial")
    sem_remessa = [_cand(4, conta="SEM"), _cand(5, conta="SEM", impedimento="x")]
    preparado = {"CONTA A": [a1, a2, impedido], "SEM": sem_remessa}
    n, total, de_fora = remessa_dia.resumo_da_conferencia(
        preparado, [(a1, True), (a2, False)])
    assert (n, total) == (1, a1.valor)
    # Os dois impedidos (inclusive o da conta que não gera arquivo) e o
    # desmarcado. O que PODE sair da conta sem arquivo não tem marca e não
    # entra nesta conta — como sempre foi.
    assert de_fora == 3


def test_gravar_leva_as_marcas_da_tela():
    a, b = _cand(1), _cand(2, marcado=False)
    remessa_dia.aplicar_marcas([(a, False), (b, 1)])
    assert a.marcado is False and b.marcado is True


def test_por_onde_diz_o_produto():
    assert pf.forma_na_conferencia(_cand(1)) == ("PIX", "fulano@exemplo.com")
    boleto = _cand(2, tipo="Boleto", chave="", codigo_barras="1" * 44)
    assert pf.forma_na_conferencia(boleto) == ("BOLETO", "1" * 44)
    ficha = _cand(3, tipo="Boleto", chave="", arrecadacao=True,
                  codigo_barras="8" * 44)
    assert pf.forma_na_conferencia(ficha)[0] == "ARRECADAÇÃO"


def test_situacao_mostra_primeiro_o_que_faz_parar():
    assert pf.situacao_na_conferencia(_cand(1)) == ("apto", "ok")
    texto, estado = pf.situacao_na_conferencia(_cand(
        2, ja_enviado="já saiu na remessa nº 000001 de 10/09/2026",
        reembolso=True, reembolso_de="FORNECEDOR ORIGINAL",
        status="APTO* (reembolso)"))
    assert estado == "atencao"
    assert texto.startswith("já saiu na remessa nº 000001"), \
        "reenviar é o mesmo pagamento duas vezes: vem primeiro"
    assert "reembolso de FORNECEDOR ORIGINAL" in texto
    assert pf.situacao_na_conferencia(_cand(3, status="ATENÇÃO — conferir")) \
        == ("ATENÇÃO — conferir", "atencao")
    motivo = "pagamento parcial — boleto não se paga pela metade"
    assert pf.situacao_na_conferencia(_cand(4, impedimento=motivo)) \
        == (motivo, "atencao"), "impedido é âmbar: não falhou, não vai"


def test_detalhe_traz_o_destino_inteiro_e_os_avisos():
    c = _cand(1, tipo="Boleto", chave="", codigo_barras="2" * 44,
              reembolso=True, reembolso_de="FORNECEDOR ORIGINAL",
              documento_favorecido="11122233344", reembolso_origem="cadastro",
              obs="pagar só depois da vistoria")
    linhas = pf.detalhe_na_conferencia(c)
    assert linhas[0] == ("FAVORECIDO 1", "Forte.TLabel")
    assert linhas[1] == ("BOLETO  " + "2" * 44, "MonoMini.TLabel")
    assert any("111.222.333-44" in texto for texto, _e in linhas)
    assert linhas[-1] == ("↳ pagar só depois da vistoria", "Tenue.TLabel")
    assert pf.detalhe_na_conferencia(_cand(2, chave=""))[1] \
        == ("PIX  —", "MonoMiniErro.TLabel")


class _TabelaFalsa:
    def __init__(self, regiao, coluna, linha):
        self.regiao, self.coluna, self.linha = regiao, coluna, linha

    def identify_region(self, _x, _y):
        return self.regiao

    def identify_column(self, _x):
        return self.coluna

    def identify_row(self, _y):
        return self.linha


def test_so_a_coluna_da_marca_alterna():
    ev = SimpleNamespace(x=5, y=5)
    assert pf._marca_clicada(_TabelaFalsa("cell", "#1", "i3"), ev) == "i3"
    assert pf._marca_clicada(_TabelaFalsa("cell", "#2", "i3"), ev) == ""
    assert pf._marca_clicada(_TabelaFalsa("heading", "#1", ""), ev) == ""


# --------------------------------------------------------------- as janelas

def _todos(pai):
    for filho in pai.winfo_children():
        yield filho
        yield from _todos(filho)


def _tabela(top):
    return next(w for w in _todos(top) if w.winfo_class() == "Treeview")


def _botao(top, texto):
    for w in _todos(top):
        if w.winfo_class() in ("Button", "TButton") and texto in str(w.cget("text")):
            return w
    raise AssertionError(f"não achei o botão {texto!r}")


def _rotulo(top, pedaco):
    return next(w for w in _todos(top) if w.winfo_class() == "TLabel"
                and pedaco in str(w.cget("text")))


def _resumo(top):
    """O rodapé que soma — "2 marcados · R$ … · 1 fica de fora". Começa pelo
    número; o subtítulo da janela também diz "marcado", e vem antes."""
    return next(str(w.cget("text")) for w in _todos(top)
                if w.winfo_class() == "TLabel"
                and str(w.cget("text"))[:1].isdigit())


def _dono(raiz, monkeypatch):
    """Um PagamentosDiaFrame sem o `_build`, com toda janela nova RETIRADA."""
    original = tk.Toplevel

    class Retirada(original):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.withdraw()

        def deiconify(self):
            pass

        def grab_set(self):              # grab em janela retirada estoura
            pass

    monkeypatch.setattr(tk, "Toplevel", Retirada)
    dono = pf.PagamentosDiaFrame.__new__(pf.PagamentosDiaFrame)
    ttk.Frame.__init__(dono, raiz)
    dono.resultado = None
    dono.anexos = {}
    dono.overviews = {}
    return dono


def _abrir(raiz, monkeypatch, janela, *args, roteiro=None):
    """Abre a janela, deixa o `roteiro(top, tabela)` agir e devolve
    (o que ela devolveu, quantos widgets ela tinha)."""
    dono = _dono(raiz, monkeypatch)
    visto = {}

    def esperar(top):
        raiz.update()
        visto["widgets"] = len(list(_todos(top)))
        if roteiro:
            roteiro(top, _tabela(top))

    dono.wait_window = esperar
    try:
        return getattr(dono, janela)(*args), visto["widgets"]
    finally:
        dono.destroy()


def _alternar(raiz, tabela, iid):
    tabela.selection_set(iid)
    tabela.focus(iid)
    tabela.event_generate("<<AlternarMarca>>")
    raiz.update()


def test_a_confirmacao_nao_cresce_com_o_numero_de_lancamentos(raiz, monkeypatch):
    linhas = {}

    def contar(_top, tabela):
        linhas["n"] = len(tabela.get_children())

    _r, pequena = _abrir(raiz, monkeypatch, "_janela_confirmar",
                         [_lanc(i) for i in range(3)])
    _r, grande = _abrir(raiz, monkeypatch, "_janela_confirmar",
                        [_lanc(i, conta=f"CONTA {i % 18:02d}")
                         for i in range(300)], roteiro=contar)
    assert grande == pequena
    assert linhas["n"] == 300 + 18, "um lançamento por linha, mais as contas"


def test_desmarcar_tira_do_dia_e_o_rodape_acompanha(raiz, monkeypatch):
    alvos = [_lanc(1, valor=100.0), _lanc(2, valor=250.0), _lanc(3, valor=40.0)]
    visto = {}

    def roteiro(top, tabela):
        assert [tabela.set(f"i{k}", "marca") for k in range(3)] \
            == [pf.MARCADA] * 3, "já vem tudo marcado"
        _alternar(raiz, tabela, "i1")            # FORNECEDOR 002, R$ 250
        visto["marca"] = tabela.set("i1", "marca")
        visto["tags"] = tabela.item("i1", "tags")
        visto["rodape"] = _resumo(top)
        _botao(top, "Confirmar e gerar").invoke()

    fora, _w = _abrir(raiz, monkeypatch, "_janela_confirmar", alvos,
                      roteiro=roteiro)
    assert fora == {"L2"}
    assert visto["marca"] == pf.DESMARCADA
    assert "erro" in visto["tags"], "desmarcado é 'fica de fora', na legenda"
    assert "2 marcados" in visto["rodape"]
    assert "R$ 140,00" in visto["rodape"]
    assert "1 fica de fora" in visto["rodape"]


def test_marcar_de_novo_devolve_ao_dia(raiz, monkeypatch):
    def roteiro(top, tabela):
        _alternar(raiz, tabela, "i0")
        _alternar(raiz, tabela, "i0")
        _botao(top, "Confirmar e gerar").invoke()

    fora, _w = _abrir(raiz, monkeypatch, "_janela_confirmar",
                      [_lanc(1), _lanc(2)], roteiro=roteiro)
    assert fora == set()


def test_cancelar_ou_fechar_nao_gera_nada(raiz, monkeypatch):
    def cancelar(top, tabela):
        _alternar(raiz, tabela, "i0")
        _botao(top, "Cancelar").invoke()

    assert _abrir(raiz, monkeypatch, "_janela_confirmar", [_lanc(1)],
                  roteiro=cancelar)[0] is None
    assert _abrir(raiz, monkeypatch, "_janela_confirmar", [_lanc(1)])[0] is None


def test_o_destaque_vem_na_frente_e_o_detalhe_mostra_o_destino(raiz,
                                                               monkeypatch):
    alvos = [_lanc(1, favorecido="ALFA"),
             _lanc(2, favorecido="SOCIO FICTICIO", chave="socio@exemplo.com")]
    _nome, dado, _estado = pf.quem_recebe(alvos[1], {})
    visto = {}

    def roteiro(top, tabela):
        visto["primeira"] = tabela.set("i0", "quem")
        tabela.selection_set("i0")
        tabela.focus("i0")
        raiz.update()
        visto["antes"] = str(_rotulo(top, dado).cget("style"))
        _alternar(raiz, tabela, "i0")
        visto["depois"] = str(_rotulo(top, dado).cget("style"))

    _abrir(raiz, monkeypatch, "_janela_confirmar", alvos, ["SOCIO FICTICIO"],
           roteiro=roteiro)
    assert visto["primeira"] == "⚠  SOCIO FICTICIO"
    assert visto["antes"] != "MonoMiniErro.TLabel"
    assert visto["depois"] == "MonoMiniErro.TLabel", \
        "o destino de quem fica de fora sai em vermelho no detalhe"


def _pagador(convenio="C1", conta="50001"):
    return SimpleNamespace(convenio=convenio, empresa="EMPRESA MODELO LTDA",
                           agencia="1234", dv_agencia="5", conta=conta,
                           dv_conta="1")


def _remessa(raiz, monkeypatch, preparado, pagadores, recusadas=(),
             proximos=None, roteiro=None):
    hist = _Historico(proximos or {"C1": 31})
    return _abrir(raiz, monkeypatch, "_janela_remessa", preparado, pagadores,
                  list(recusadas), hist, roteiro=roteiro)


def test_a_conferencia_nao_cresce_com_o_numero_de_pagamentos(raiz,
                                                             monkeypatch):
    def montar(n):
        preparado = {"CONTA A": [_cand(i) for i in range(n)]}
        return preparado, {"CONTA A": _pagador()}

    _r, pequena = _remessa(raiz, monkeypatch, *montar(3))
    _r, grande = _remessa(raiz, monkeypatch, *montar(300))
    assert grande == pequena


def test_vem_marcado_o_apto_e_o_gravar_leva_as_marcas(raiz, monkeypatch):
    apto = _cand(1)
    duvidoso = _cand(2, status="ATENÇÃO — conferir o valor")
    reenvio = _cand(3, ja_enviado="já saiu na remessa nº 000001 de 10/09/2026")
    impedido = _cand(4, impedimento="pagamento parcial — boleto não se paga "
                                    "pela metade")
    preparado = {"CONTA A": [apto, duvidoso, reenvio, impedido]}
    visto = {}

    def roteiro(top, tabela):
        visto["marcas"] = [tabela.set(i, "marca") for i in ("v0", "v1", "v2")]
        visto["impedido"] = tabela.set("f0_0", "marca")
        _alternar(raiz, tabela, "f0_0")          # impedido não tem marca
        _alternar(raiz, tabela, "g0")            # nem a linha da conta
        _alternar(raiz, tabela, "v1")            # o duvidoso, com um clique
        _alternar(raiz, tabela, "v0")            # e o apto sai
        visto["rodape"] = str(_rotulo(top, "pagamento(s)").cget("text"))
        _botao(top, "Gravar os arquivos").invoke()

    ok, _w = _remessa(raiz, monkeypatch, preparado,
                      {"CONTA A": _pagador()}, roteiro=roteiro)
    assert visto["marcas"] == [pf.MARCADA, pf.DESMARCADA, pf.DESMARCADA], \
        "marcado só o apto: o duvidoso e o reenvio pedem um clique"
    assert visto["impedido"] == ""
    assert ok is True
    assert (apto.marcado, duvidoso.marcado, reenvio.marcado) \
        == (False, True, False)
    assert impedido.marcado is False
    assert visto["rodape"].startswith("1 pagamento(s)")
    assert visto["rodape"].endswith("3 de fora")


def test_cancelar_a_conferencia_nao_muda_marca_nenhuma(raiz, monkeypatch):
    apto = _cand(1)

    def roteiro(top, tabela):
        _alternar(raiz, tabela, "v0")
        _botao(top, "Cancelar").invoke()

    ok, _w = _remessa(raiz, monkeypatch, {"CONTA A": [apto]},
                      {"CONTA A": _pagador()}, roteiro=roteiro)
    assert ok is False and apto.marcado is True


def test_o_arquivo_previsto_segue_o_convenio(raiz, monkeypatch):
    pagadores = {"CONTA A": _pagador("C1", "50001"),
                 "CONTA B": _pagador("C2", "50002"),
                 "CONTA C": _pagador("C1", "50003")}
    preparado = {conta: [_cand(i, conta=conta)]
                 for i, conta in enumerate(pagadores)}
    recusadas = [("CONTA SEM CONVENIO", "sem convênio no cadastro")]
    visto = {}

    def roteiro(_top, tabela):
        visto["nsa"] = [tabela.set(f"g{g}", "onde") for g in range(3)]
        visto["recusada"] = (tabela.set("r0", "fornecedor"),
                             tabela.set("r0", "situacao"))

    _remessa(raiz, monkeypatch, preparado, pagadores, recusadas,
             proximos={"C1": 31, "C2": 7}, roteiro=roteiro)
    assert visto["nsa"] == ["arquivo nº 000031", "arquivo nº 000007",
                            "arquivo nº 000032"]
    assert visto["recusada"][0] == "CONTA SEM CONVENIO"
    assert visto["recusada"][1].endswith("sem convênio no cadastro")
