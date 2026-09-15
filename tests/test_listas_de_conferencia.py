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
import datetime as _dt
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

from pagamentos_dia import confirmacao
from pagamentos_dia import pagamentos_frame as pf
from pagamentos_dia import remessa_dia
from pagamentos_dia.remessa_dia import Candidato


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
# O que entra, a situação, o rodapé e o que volta moram em
# `pagamentos_dia/confirmacao.py` e são testados em `tests/test_confirmacao.py`.
# Aqui fica o detalhe da linha selecionada, que é desenho de texto.

def _linha(i, conta="CONTA A", favorecido=None, valor=100.0,
           chave="fulano@exemplo.com", secao=confirmacao.ENTRA,
           situacao="APTO · vai na remessa", estado="ok", olhar=False, **mais):
    """Uma `confirmacao.Linha` como o `grupos_da_confirmacao` a deixa."""
    campos = dict(secao=secao, id=f"L{i}", conta=conta, valor=valor,
                  favorecido=favorecido or f"FORNECEDOR {i:03d}", tipo="Pix",
                  dados=chave, por_onde=f"PIX  {chave}", vencimento=None,
                  oc=str(1000 + i), centro_custo="OBRA MODELO",
                  descricao=f"MATERIAL OC {1000 + i}", situacao=situacao,
                  estado=estado, olhar=olhar)
    campos.update(mais)
    return confirmacao.Linha(**campos)


def _grupos(linhas, nao_aptos=()):
    """Os grupos por conta, na ordem em que as linhas chegam."""
    por_conta = {}
    for ln in linhas:
        por_conta.setdefault(ln.conta, confirmacao.Grupo(ln.conta, [], [])
                             ).entram.append(ln)
    for ln in nao_aptos:
        por_conta.setdefault(ln.conta, confirmacao.Grupo(ln.conta, [], [])
                             ).nao_aptos.append(ln)
    return [por_conta[conta] for conta in sorted(por_conta)]


def test_o_detalhe_da_confirmacao_traz_tudo_o_que_a_linha_nao_cabe():
    """A observação vai INTEIRA: é nela que mora "pagar só metade" e "a chave
    mudou", e o corte em 110 caracteres da conferência da remessa escondia
    justamente o fim da frase."""
    obs = "Observação do lançamento: " + "pagar só depois da vistoria " * 8
    ln = _linha(1, olhar=True, obs=obs, conferencia="NF ✓ · valor ✓",
                vencimento=_dt.date(2026, 9, 15))
    textos = [texto for texto, _e in pf.detalhe_na_confirmacao(ln, True)]
    assert textos[0] == "⚠  FORNECEDOR 001"
    assert textos[1] == "PIX  fulano@exemplo.com"
    assert "vence 15/09/2026" in textos[2] and "OC 1001" in textos[2]
    assert any(obs in t for t in textos), "a observação não pode sair cortada"
    assert any("NF ✓ · valor ✓" in t for t in textos)
    assert any("APTO · vai na remessa" in t for t in textos)


def test_o_destino_de_quem_fica_de_fora_sai_em_vermelho():
    ln = _linha(1)
    assert pf.detalhe_na_confirmacao(ln, True)[1][1] == "MonoMini.TLabel"
    assert pf.detalhe_na_confirmacao(ln, False)[1][1] == "MonoMiniErro.TLabel"
    atencao = _linha(2, estado="atencao")
    assert pf.detalhe_na_confirmacao(atencao, True)[1][1] \
        == "MonoMiniAtencao.TLabel"
    nao_apto = _linha(3, secao=confirmacao.NAO_APTO, estado="erro",
                      situacao="sem forma de pagar (nem boleto anexado, nem "
                               "chave Pix)")
    detalhe = pf.detalhe_na_confirmacao(nao_apto, True)
    assert detalhe[1][1] == "MonoMiniErro.TLabel"
    assert any("sem forma de pagar" in t and "ERP" in t for t, _e in detalhe), \
        "o não apto diz o motivo e onde se corrige"


def test_o_detalhe_do_nao_apto_mostra_o_que_o_cadastro_tem():
    """O motivo diz o que falta; o cadastro diz o que ESTÁ lá — é com os dois
    que se corrige no ERP. Junto, a observação e a conferência de sempre."""
    nao_apto = _linha(3, secao=confirmacao.NAO_APTO, estado="erro",
                      situacao="sem forma de pagar (nem boleto anexado, nem "
                               "chave Pix)", chave="",
                      obs="Pix sem chave no cadastro — buscar no ERP",
                      conferencia="(não cruzado)",
                      pagamento_no_cadastro="TED BANCO 001 AG 1234 CC 56789-0")
    textos = [t for t, _e in pf.detalhe_na_confirmacao(nao_apto, True)]
    assert any("sem forma de pagar" in t for t in textos)
    assert "Cadastro do ERP: TED BANCO 001 AG 1234 CC 56789-0" in textos
    assert any("Pix sem chave no cadastro" in t for t in textos)
    assert any("(não cruzado)" in t for t in textos)
    assert len(textos) <= pf.PagamentosDiaFrame.ALTURAS_DO_DETALHE

    sem_cadastro = _linha(4, secao=confirmacao.NAO_APTO, estado="erro",
                          situacao="sem forma de pagar", chave="")
    assert not any(t.startswith("Cadastro do ERP")
                   for t, _e in pf.detalhe_na_confirmacao(sem_cadastro, True))


def test_o_detalhe_do_reembolso_diz_de_quem_e_o_documento():
    c = _cand(1, reembolso=True, reembolso_de="FORNECEDOR ORIGINAL",
              documento_favorecido="11122233344", reembolso_origem="cadastro")
    textos = [t for t, _e in pf.detalhe_na_confirmacao(_linha(1, candidato=c),
                                                      True)]
    assert any("reembolso de FORNECEDOR ORIGINAL" in t
               and "111.222.333-44" in t for t in textos)


def test_no_reembolso_o_detalhe_abre_com_quem_recebe_de_verdade():
    ln = _linha(1, reembolso=True, reembolso_nome="PESSOA DE EXEMPLO")
    assert pf.detalhe_na_confirmacao(ln, True)[0] \
        == ("PESSOA DE EXEMPLO (reembolso de FORNECEDOR 001)", "Forte.TLabel")


# ----------------------------------------- confirmação: as duas fases, sem tela
# O frame é montado sem `_build` e sem Tk (`__new__`), e a janela é trocada
# pela resposta que a pessoa daria. O que se prova é a ordem de dinheiro: a
# leitura não troca `self.resultado`; cancelar não grava nem troca; confirmar
# remonta sem rede e grava o confirmado.

def _lanc_api(ident, conta="CONTA A", favorecido=None, valor=100.0):
    """Um lançamento a pagar, no formato da API — com dados de mentira."""
    return {"id": ident, "tradePayableId": f"T-{ident}",
            "paidTo": favorecido or f"FORNECEDOR {ident}",
            "description": "MATERIAL OC 1234", "documentNumber": "1234",
            "remainingValue": valor, "plannedDate": "2026-09-14",
            "tradePayableAccount": {"name": conta},
            "tradePayablePaymentMethod": "Pix",
            "paidToBankAccount": "PIX EMAIL fulano@exemplo.com",
            "paid": False}


class _RegistroQueAnota:
    """O registro de remessas: responde às leituras e anota escrita."""

    def __init__(self):
        self.escritas = []

    def maior_ordem_do_dia(self, _quando):
        return 0

    def envio_de(self, _codigo):
        return None

    def envio_da_referencia(self, _referencia):
        return None

    def alocar_nsa(self, convenio):
        self.escritas.append(("alocar_nsa", convenio))
        return 1

    def registrar(self, *a, **k):
        self.escritas.append(("registrar", a, k))


def _sem_cadastro():
    raise ValueError("contas_mc.json ilegível")


def _dono_sem_tela(monkeypatch, tmp_path, lancamentos):
    import queue
    from threading import Event

    dono = pf.PagamentosDiaFrame.__new__(pf.PagamentosDiaFrame)
    dono.q = queue.Queue()
    dono._parar = Event()
    dono.worker = None
    dono.lancamentos = lancamentos
    dono.anexos, dono.overviews, dono.participantes = {}, {}, {}
    dono.resultado = "o resultado de antes"
    dono._periodo_do_resultado = "o período de antes"
    dono.lbl = SimpleNamespace(configure=lambda **_k: None)
    dono.update_idletasks = lambda: None
    registro = _RegistroQueAnota()
    monkeypatch.setattr(pf, "_pasta_base", lambda: tmp_path)
    monkeypatch.setattr(pf, "_historico", lambda avisar=None: registro)
    monkeypatch.setattr(pf, "_carregar_mapas", _sem_cadastro)
    monkeypatch.setattr(pf.auditoria, "registrar", lambda *a, **k: None)
    monkeypatch.setattr(pf.regras, "carregar_fornecedores", lambda *_a: {})
    monkeypatch.setattr(pf.regras, "carregar_confirmar", lambda *_a: [])
    return dono, registro


def _opcoes(tmp_path):
    hoje = _dt.date(2026, 9, 14)
    return {"periodo": (hoje, hoje), "cruzar": False, "incluir_pagos": False,
            "pasta": str(tmp_path)}


def _mensagens(dono):
    saida = []
    while not dono.q.empty():
        saida.append(dono.q.get_nowait())
    return saida


def _ler(dono, tmp_path, depois="planilha"):
    """Roda a fase 1 e devolve (pacote da janela, mensagens)."""
    dono._t_apurar(["CONTA A"], _opcoes(tmp_path), depois)
    msgs = _mensagens(dono)
    pacote = next((v for t, v in msgs if t == "confirmar"), None)
    return pacote, msgs


def test_a_leitura_nao_troca_o_resultado_e_manda_a_janela(monkeypatch,
                                                         tmp_path):
    dono, registro = _dono_sem_tela(
        monkeypatch, tmp_path,
        [_lanc_api("L1"), _lanc_api("L2", conta="OUTRA CONTA")])
    pacote, msgs = _ler(dono, tmp_path)
    assert dono.resultado == "o resultado de antes", \
        "só o Confirmar troca o resultado: o Gerar remessa sai dele"
    entradas, resultado, analise, grupos, depois, pasta = pacote
    assert [i["id"] for i in entradas.selecionados] == ["L1"], \
        "só as contas marcadas"
    assert [r["id"] for r in resultado.contas["CONTA A"]] == ["L1"]
    assert (depois, pasta) == ("planilha", str(tmp_path))
    aviso, = analise.avisos
    assert aviso.startswith(confirmacao.AVISO_SEM_CADASTRO), \
        "cadastro ilegível vira aviso na janela, e a planilha segue"
    assert [g.conta for g in grupos] == ["CONTA A"]
    assert registro.escritas == [], "a leitura não reserva NSA nem registra"
    assert msgs[-1] == ("botoes", "normal")


def test_cancelar_a_confirmacao_nao_grava_e_mantem_o_resultado(monkeypatch,
                                                              tmp_path):
    dono, _registro = _dono_sem_tela(monkeypatch, tmp_path, [_lanc_api("L1")])
    pacote, _msgs = _ler(dono, tmp_path)
    dono._janela_confirmar = lambda grupos, avisos, botao: None
    gravou = []
    dono._gravar_planilha = lambda *a: gravou.append(a)

    dono._confirmar_e_seguir(pacote)
    assert dono.resultado == "o resultado de antes"
    assert dono._periodo_do_resultado == "o período de antes"
    assert gravou == []
    assert list(tmp_path.glob("*.xlsx")) == []


def test_confirmar_tira_o_desmarcado_e_grava_a_planilha(monkeypatch, tmp_path):
    dono, _registro = _dono_sem_tela(
        monkeypatch, tmp_path,
        [_lanc_api("L1"), _lanc_api("L2", favorecido="OUTRO FORNECEDOR")])
    pacote, _msgs = _ler(dono, tmp_path)
    # A remontagem não pode voltar à rede: sem navegador nenhum aqui, baixar
    # um anexo estouraria.
    dono.anx = None
    dono._janela_confirmar = lambda grupos, avisos, botao: {"L2"}

    dono._confirmar_e_seguir(pacote)
    contas = dono.resultado.contas
    assert [r["id"] for regs in contas.values() for r in regs] == ["L1"]
    assert [(o["id"], o["motivo"]) for o in dono.resultado.omitidos] \
        == [("L2", pf.regras.MOTIVO_NAO_CONFIRMADO)]
    assert dono._periodo_do_resultado == _opcoes(tmp_path)["periodo"]
    arquivo = next(v for t, v in _mensagens(dono) if t == "arquivo")
    assert arquivo.exists() and arquivo.parent == tmp_path


def _anexo_pdf(nome):
    return {"filename": nome, "tagName": "Nota Fiscal", "extension": ".pdf",
            "downloadUrl": f"https://exemplo.invalid/{nome}.pdf"}


def test_parar_durante_a_leitura_nao_abre_a_janela(monkeypatch, tmp_path):
    """Parar no meio do download deixava a janela abrir com leitura pela
    metade: o boleto dentro da NF não lido virava Pix do cadastro, verde. Com
    o Parar ligado depois da leitura, nada é apurado e a janela não abre."""
    dono, _registro = _dono_sem_tela(
        monkeypatch, tmp_path, [_lanc_api("L1"), _lanc_api("L2")])
    dono.anexos = {"T-L1": [_anexo_pdf("nf-1")], "T-L2": [_anexo_pdf("nf-2")]}

    def baixar(_url):
        dono._parar.set()               # a pessoa clicou em Parar agora
        return None

    dono.anx = SimpleNamespace(api=SimpleNamespace(baixar_anexo=baixar))
    dono._t_apurar(["CONTA A"], dict(_opcoes(tmp_path), cruzar=True),
                   "planilha")
    msgs = _mensagens(dono)
    assert not [v for t, v in msgs if t == "confirmar"], "a janela não abre"
    assert ("status", "Interrompido — nada foi apurado.") in msgs
    assert any("nterrompido" in str(v) for t, v in msgs if t == "log")
    assert dono.resultado == "o resultado de antes"
    assert msgs[-1] == ("botoes", "normal")


def test_anexo_que_nao_foi_lido_vira_aviso_na_janela(monkeypatch, tmp_path):
    """Download que devolve None ou levanta não pode passar calado: a forma de
    pagar daquela linha foi decidida sem o documento."""
    dono, _registro = _dono_sem_tela(monkeypatch, tmp_path, [_lanc_api("L1")])
    dono.anexos = {"T-L1": [_anexo_pdf("nf-1"), _anexo_pdf("nf-2"),
                            _anexo_pdf("nf-3")]}
    monkeypatch.setattr(pf.relatorio, "texto_de_pdf",
                        lambda dados: "texto da nota" if dados else "")

    def baixar(url):
        if url.endswith("nf-2.pdf"):
            return None
        if url.endswith("nf-3.pdf"):
            raise OSError("o download caiu")
        return b"%PDF ficticio"

    dono.anx = SimpleNamespace(api=SimpleNamespace(baixar_anexo=baixar))
    dono._t_apurar(["CONTA A"], dict(_opcoes(tmp_path), cruzar=True),
                   "planilha")
    msgs = _mensagens(dono)
    entradas, _resultado, analise, _grupos, _depois, _pasta = next(
        v for t, v in msgs if t == "confirmar")
    aviso = confirmacao.aviso_de_anexos_nao_lidos(2)
    assert entradas.anexos_nao_lidos == 2
    assert analise.avisos[0] == aviso
    assert any(aviso in str(v) for t, v in msgs if t == "log")
    assert entradas.textos == {"https://exemplo.invalid/nf-1.pdf":
                               "texto da nota"}


def test_a_remessa_sem_planilha_passa_pela_mesma_confirmacao(monkeypatch,
                                                            tmp_path):
    dono, _registro = _dono_sem_tela(monkeypatch, tmp_path, [_lanc_api("L1")])
    pacote, _msgs = _ler(dono, tmp_path, depois="remessa")
    botoes, conferiu = [], []
    dono._janela_confirmar = lambda grupos, avisos, botao: (
        botoes.append(botao) or set())
    dono._gravar_planilha = lambda *a: conferiu.append("planilha")
    dono.gerar_remessa = lambda: conferiu.append(dono.resultado)

    dono._confirmar_e_seguir(pacote)
    assert botoes == ["Confirmar e conferir a remessa"]
    assert conferiu == [dono.resultado], \
        "confirmado, vai à conferência da remessa — e não grava planilha"
    assert dono.resultado != "o resultado de antes"


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
                         _grupos([_linha(i) for i in range(3)]))
    _r, grande = _abrir(raiz, monkeypatch, "_janela_confirmar",
                        _grupos([_linha(i, conta=f"CONTA {i % 18:02d}")
                                 for i in range(300)]), roteiro=contar)
    assert grande == pequena
    assert linhas["n"] == 300 + 18 + 18, \
        "um lançamento por linha, mais a conta e a seção ENTRAM de cada uma"


def test_desmarcar_tira_do_dia_e_o_rodape_acompanha(raiz, monkeypatch):
    grupos = _grupos([_linha(1, valor=100.0), _linha(2, valor=250.0),
                      _linha(3, valor=40.0)])
    visto = {}

    def roteiro(top, tabela):
        assert [tabela.set(f"i{k}", "marca") for k in range(3)] \
            == [pf.MARCADA] * 3, "já vem tudo marcado"
        _alternar(raiz, tabela, "i1")            # FORNECEDOR 002, R$ 250
        visto["marca"] = tabela.set("i1", "marca")
        visto["tags"] = tabela.item("i1", "tags")
        visto["rodape"] = _resumo(top)
        _botao(top, "Confirmar e gerar").invoke()

    fora, _w = _abrir(raiz, monkeypatch, "_janela_confirmar", grupos,
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
                      _grupos([_linha(1), _linha(2)]), roteiro=roteiro)
    assert fora == set()


def test_cancelar_ou_fechar_nao_gera_nada(raiz, monkeypatch):
    def cancelar(top, tabela):
        _alternar(raiz, tabela, "i0")
        _botao(top, "Cancelar").invoke()

    assert _abrir(raiz, monkeypatch, "_janela_confirmar", _grupos([_linha(1)]),
                  roteiro=cancelar)[0] is None
    assert _abrir(raiz, monkeypatch, "_janela_confirmar",
                  _grupos([_linha(1)]))[0] is None


def test_o_destaque_aparece_e_o_detalhe_mostra_o_destino(raiz, monkeypatch):
    grupos = _grupos([_linha(2, favorecido="SOCIO FICTICIO",
                             chave="socio@exemplo.com", olhar=True),
                      _linha(1, favorecido="ALFA")])
    dado = "PIX  socio@exemplo.com"
    visto = {}

    def roteiro(top, tabela):
        visto["primeira"] = tabela.set("i0", "quem")
        tabela.selection_set("i0")
        tabela.focus("i0")
        raiz.update()
        visto["antes"] = str(_rotulo(top, dado).cget("style"))
        _alternar(raiz, tabela, "i0")
        visto["depois"] = str(_rotulo(top, dado).cget("style"))

    _abrir(raiz, monkeypatch, "_janela_confirmar", grupos, roteiro=roteiro)
    assert visto["primeira"] == "⚠  SOCIO FICTICIO"
    assert visto["antes"] != "MonoMiniErro.TLabel"
    assert visto["depois"] == "MonoMiniErro.TLabel", \
        "o destino de quem fica de fora sai em vermelho no detalhe"


def test_o_nao_apto_aparece_sem_marca_e_nao_se_forca(raiz, monkeypatch):
    """O pedido do dono: ver o que NÃO entrou antes de gerar, para corrigir no
    ERP. Ele aparece em vermelho, com o motivo, e sem marca — um clique nele
    não o põe na planilha."""
    motivo = "sem forma de pagar (nem boleto anexado, nem chave Pix)"
    grupos = _grupos([_linha(1, valor=100.0)],
                     nao_aptos=[_linha(9, valor=250.0, secao=confirmacao.NAO_APTO,
                                       estado="erro", situacao=motivo)])
    visto = {}

    def roteiro(top, tabela):
        visto["marca"] = tabela.set("n0", "marca")
        visto["tags"] = tabela.item("n0", "tags")
        visto["situacao"] = tabela.set("n0", "situacao")
        _alternar(raiz, tabela, "n0")
        visto["depois"] = tabela.set("n0", "marca")
        visto["rodape"] = _resumo(top)
        _botao(top, "Confirmar e gerar").invoke()

    fora, _w = _abrir(raiz, monkeypatch, "_janela_confirmar", grupos,
                      roteiro=roteiro)
    assert fora == set(), "o não apto não volta como desmarcado: nunca entrou"
    assert visto["marca"] == visto["depois"] == ""
    assert "erro" in visto["tags"]
    assert visto["situacao"].endswith(motivo)
    assert visto["rodape"].startswith("1 marcado")
    assert "R$ 100,00" in visto["rodape"], "o não apto não soma no total"
    assert visto["rodape"].endswith("1 não apto")


def test_os_avisos_da_analise_aparecem_em_cima(raiz, monkeypatch):
    visto = {}

    def roteiro(top, _tabela):
        visto["aviso"] = str(_rotulo(top, confirmacao.AVISO_SEM_REGISTRO
                                     ).cget("text"))

    _abrir(raiz, monkeypatch, "_janela_confirmar", _grupos([_linha(1)]),
           [confirmacao.AVISO_SEM_REGISTRO], roteiro=roteiro)
    assert confirmacao.AVISO_SEM_REGISTRO in visto["aviso"]


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
