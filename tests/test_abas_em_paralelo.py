# -*- coding: utf-8 -*-
"""Abas em paralelo no modo central (plano de 15/10/2026).

Teste do dono na v2.0.238: com "Pagamentos do Dia — buscar" rodando, o
"Saldo de pagamentos" levou "Navegador ocupado". Com o Chrome central ligado,
cada aba do app tem a SUA thread e o SEU `MCClient` (a "vaga"); o aviso só
vale quando a MESMA aba já trabalha. Desligado, tudo como antes: uma thread,
um cliente, o mesmo aviso.

Testes puros: a `AnexarFrame` nasce sem `__init__` (sem Tk), com só o que o
código lê — como em `test_aba_da_pessoa.py`."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest


class _Dona:
    """Uma aba do app qualquer (só a identidade importa)."""


class _DonaB:
    pass


@pytest.fixture
def modulo():
    pytest.importorskip("playwright")
    from anexar import anexar_comprovantes as modulo
    return modulo


def _frame(modulo, monkeypatch, *, ligado: bool):
    monkeypatch.setattr(modulo.central, "ligado", lambda *a, **k: ligado)
    f = modulo.AnexarFrame.__new__(modulo.AnexarFrame)
    f.mc = None
    f.api = None
    f.exec = ThreadPoolExecutor(max_workers=1)
    f._trabalho_atual = None
    f._rotulo_atual = None
    f._pulso_nav = None
    f._encerrando = False
    f.registro = []
    f._log = f.registro.append
    f.after = lambda *a, **k: None
    f.winfo_children = lambda: []
    f.chamadas = []
    from tkinter import messagebox
    monkeypatch.setattr(messagebox, "askyesno",
                        lambda *a, **k: f.chamadas.append(("pergunta",)) or False)
    monkeypatch.setattr(messagebox, "showinfo",
                        lambda *a, **k: f.chamadas.append(("aviso",)))
    return f


@pytest.fixture
def desligado(modulo, monkeypatch):
    f = _frame(modulo, monkeypatch, ligado=False)
    try:
        yield f
    finally:
        f._encerrando = True
        f.exec.shutdown(wait=False)


@pytest.fixture
def ligado(modulo, monkeypatch):
    f = _frame(modulo, monkeypatch, ligado=True)
    try:
        yield f
    finally:
        f._encerrando = True
        for vaga in list(getattr(f, "_vagas", {}).values()):
            vaga.executor.shutdown(wait=False)
        f.exec.shutdown(wait=False)


# ------------------------------------------------------------ desligado
def test_desligado_duas_donas_dividem_a_thread_e_o_aviso(desligado):
    a, b = _Dona(), _DonaB()
    solta = threading.Event()
    ids = []
    fa = desligado.submeter("A", lambda: (ids.append(threading.get_ident()),
                                          solta.wait(5)), dona=a)
    try:
        assert desligado.avisar_se_ocupado("a aba B", aba=b) is True
        assert desligado.chamadas == [("pergunta",)]
        assert desligado.ocupado() == "A"
        assert desligado.dona_ocupada() is a
    finally:
        solta.set()
    fa.result(timeout=5)
    fb = desligado.submeter("B", lambda: ids.append(threading.get_ident()), dona=b)
    fb.result(timeout=5)
    assert ids[0] == ids[1]                   # o mesmo executor de sempre
    assert not getattr(desligado, "_vagas", None)


# -------------------------------------------------------------- ligado
def test_ligado_donas_diferentes_nao_se_esperam(ligado):
    a, b = _Dona(), _DonaB()
    solta = threading.Event()
    ordem, ids = [], {}

    def trabalho_a():
        ids["a"] = threading.current_thread()
        solta.wait(5)
        ordem.append("a")

    def trabalho_b():
        ids["b"] = threading.current_thread()
        ordem.append("b")

    fa = ligado.submeter("A", trabalho_a, dona=a)
    try:
        assert ligado.avisar_se_ocupado("a aba B", aba=b) is False
        assert ligado.chamadas == []
        fb = ligado.submeter("B", trabalho_b, dona=b)
        fb.result(timeout=5)                  # B termina com A ainda presa
        assert ordem == ["b"]
    finally:
        solta.set()
    fa.result(timeout=5)
    assert ids["a"] is not ids["b"]
    assert ids["a"].name.startswith("nav-_Dona")
    assert ids["b"].name.startswith("nav-_DonaB")


def test_ligado_mesma_dona_avisa(ligado):
    a = _Dona()
    solta = threading.Event()
    fa = ligado.submeter("A", solta.wait, 5, dona=a)
    try:
        assert ligado.avisar_se_ocupado("a aba A", aba=a) is True
        assert ligado.chamadas == [("pergunta",)]
        # a barra lateral continua vendo quem trabalha
        assert ligado.ocupado() == "A"
        assert ligado.dona_ocupada() is a
        assert ligado.ocupado(aba=_DonaB()) is None
        assert ligado.dona_ocupada(aba=a) is a
    finally:
        solta.set()
    fa.result(timeout=5)
    assert ligado.ocupado() is None
    assert ligado.dona_ocupada() is None


def test_ligado_sem_dona_e_a_vaga_do_proprio_anexar(ligado):
    solta = threading.Event()
    f = ligado.submeter("Abrir o Mais Controle", solta.wait, 5)
    try:
        assert ligado.avisar_se_ocupado("o Anexar") is True
        assert ligado.dona_ocupada() is ligado
    finally:
        solta.set()
    f.result(timeout=5)


def test_ligado_mc_e_api_sao_da_vaga(ligado):
    a, b = _Dona(), _DonaB()
    x, api_x = object(), object()

    def em_a():
        ligado.mc = x
        ligado.api = api_x
        return ligado.mc

    assert ligado.submeter("A", em_a, dona=a).result(timeout=5) is x
    assert ligado.submeter("B", lambda: (ligado.mc, ligado.api),
                           dona=b).result(timeout=5) == (None, None)
    assert ligado.submeter("A", lambda: (ligado.mc, ligado.api),
                           dona=a).result(timeout=5) == (x, api_x)
    # fora de thread de vaga, o atributo de sempre
    assert ligado.mc is None
    y = object()
    ligado.mc = y
    assert ligado._mc is y
    assert ligado.submeter("B", lambda: ligado.mc, dona=b).result(timeout=5) is None


def test_desligado_mc_e_o_atributo_de_sempre(desligado):
    x = object()
    assert desligado.submeter("A", lambda: setattr(desligado, "mc", x),
                              dona=_Dona()).result(timeout=5) is None
    assert desligado.mc is x
    assert desligado._mc is x


def test_fechar_fecha_cada_mc_na_thread_da_vaga(ligado):
    a, b = _Dona(), _DonaB()
    saidas = []

    class _MC:
        fechado = False

        def __exit__(self, *exc):
            saidas.append((self, threading.get_ident()))

    def abrir():
        ligado.mc = _MC()
        return ligado.mc, threading.get_ident()

    mc_a, id_a = ligado.submeter("A", abrir, dona=a).result(timeout=5)
    mc_b, id_b = ligado.submeter("B", abrir, dona=b).result(timeout=5)
    ligado.fechar()
    assert len(saidas) == 2
    assert set(saidas) == {(mc_a, id_a), (mc_b, id_b)}
    assert ligado._vagas == {}


# ------------------------------------------------- os chamadores (Tarefa 2)
_CHAMADORES = ("anexar/anexar_novo.py", "anexar/conferencia.py",
               "aportes/aportes_frame.py",
               "comprovantes_app.py", "conciliacao/frame.py",
               "contratos/frame.py", "guias/painel.py",
               "pagamentos_dia/pagamentos_frame.py",
               "relatorios/relatorio_frame.py", "tela_do_dia/controle_frame.py",
               "tela_do_dia/frame.py")


def _chamadas(arquivo: str, metodo: str, chave: str) -> list[str]:
    import ast
    from pathlib import Path
    raiz_repo = Path(__file__).resolve().parents[1]
    arvore = ast.parse((raiz_repo / arquivo).read_text(encoding="utf-8"))
    achadas = []
    for no in ast.walk(arvore):
        if (isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
                and no.func.attr == metodo):
            kw = [k for k in no.keywords if k.arg == chave]
            achadas.append(ast.unparse(kw[0].value) if kw else "<faltou>")
    return achadas


@pytest.mark.parametrize("arquivo", _CHAMADORES)
def test_todo_aviso_diz_a_aba_que_vai_submeter(arquivo):
    """No central, o aviso só olha a vaga da `aba`. Se ela não for a mesma
    dona do `submeter` daquele fluxo, o aviso olha a vaga errada: deixa
    passar a aba que já trabalha, ou barra a que está livre."""
    abas = _chamadas(arquivo, "avisar_se_ocupado", "aba")
    donas = _chamadas(arquivo, "submeter", "dona")
    assert abas and "<faltou>" not in abas
    assert set(abas) == set(donas)


# ----------------------------------- Minha aba, pulso e fechar (Tarefa 3)
def _acesso(tmp_path):
    from erp import central
    return central.Acesso("principal", tmp_path / "perfil", 9230)


def test_abrir_aba_central_pede_put_no_cdp(tmp_path):
    pytest.importorskip("playwright")
    from anexar import mc_client
    pedidos = []

    class _Resposta:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"{}"

    def abrir(req, timeout=None):
        pedidos.append((req.get_method(), req.full_url))
        return _Resposta()

    url = "https://erp.exemplo/#/payable-installments"
    assert mc_client.abrir_aba_central(_acesso(tmp_path), url, abrir=abrir) is True
    metodo, endereco = pedidos[0]
    assert metodo == "PUT"                    # o Chrome 111+ recusa GET aqui
    assert endereco.startswith("http://127.0.0.1:9230/json/new?")
    from urllib.parse import unquote
    # o "#" vai escapado: sem isso o urllib cortaria a rota do ERP
    assert unquote(endereco.split("?", 1)[1]) == url
    assert "#" not in endereco


def test_abrir_aba_central_sem_rede_devolve_false(tmp_path):
    pytest.importorskip("playwright")
    from anexar import mc_client

    def abrir(req, timeout=None):
        raise OSError("conexão recusada")

    assert mc_client.abrir_aba_central(_acesso(tmp_path), "https://x/",
                                       abrir=abrir) is False


def test_minha_aba_no_central_abre_por_http_sem_submeter(ligado, modulo,
                                                         monkeypatch, tmp_path):
    a = _acesso(tmp_path)
    passos = []
    monkeypatch.setattr(modulo.central, "acesso", lambda *x, **k: a)
    monkeypatch.setattr(modulo.central, "garantir_chrome",
                        lambda ac, **k: passos.append(("chrome", ac)) or "x")
    monkeypatch.setattr(modulo.mc_client, "abrir_aba_central",
                        lambda ac, url, **k: passos.append(("aba", ac, url)) or True)
    monkeypatch.setattr(modulo.mc_client, "abrir_aba_por_fora",
                        lambda *x, **k: pytest.fail("no central não é por fora"))
    ligado.submeter = lambda *x, **k: pytest.fail("Minha aba não usa vaga")
    ligado._em_segundo_plano = lambda fn: fn()
    ligado.abrir_minha_aba()
    assert passos == [("chrome", a), ("aba", a, modulo.config.MC_URL_PAGAMENTOS)]
    assert any("não mexe na sua" in linha for linha in ligado.registro)


def test_minha_aba_no_central_falhando_da_o_caminho_do_ctrl_t(ligado, modulo,
                                                              monkeypatch, tmp_path):
    monkeypatch.setattr(modulo.central, "acesso", lambda *x, **k: _acesso(tmp_path))
    monkeypatch.setattr(modulo.central, "garantir_chrome", lambda ac, **k: "x")
    monkeypatch.setattr(modulo.mc_client, "abrir_aba_central",
                        lambda ac, url, **k: False)
    ligado._em_segundo_plano = lambda fn: fn()
    ligado.abrir_minha_aba()
    assert any("Ctrl+T" in linha for linha in ligado.registro)


def test_pulso_no_central_e_um_por_vaga_livre_na_thread_dela(ligado):
    a, b, c = _Dona(), _DonaB(), object()
    pulsos = []
    solta = threading.Event()

    class _MC:
        fechado = False

        def pulsar(self):
            pulsos.append((self, threading.get_ident()))

    def abrir():
        ligado.mc = _MC()
        return ligado.mc, threading.get_ident()

    mc_a, id_a = ligado.submeter("A", abrir, dona=a).result(timeout=5)
    mc_b, id_b = ligado.submeter("B", abrir, dona=b).result(timeout=5)
    ligado.submeter("C", abrir, dona=c).result(timeout=5)
    ligado.submeter("C", solta.wait, 5, dona=c)        # C trabalhando
    try:
        ligado._pulsar_navegador()
        for vaga in ligado._lista_de_vagas():
            if vaga.pulso is not None:
                vaga.pulso.result(timeout=5)
        assert set(pulsos) == {(mc_a, id_a), (mc_b, id_b)}
        assert ligado.ocupado(aba=a) is None       # pulso não é trabalho
        # pulso ainda correndo não leva outro atrás
        ligado._pulsar_navegador()
    finally:
        solta.set()
    assert ligado._mc is None                       # nada no atributo comum


# ------------------------------------ aba do ERP parada fecha sozinha (23/10)
# Dono, 23/10/2026: "quando roda uma automação, depois que ela acaba a guia
# fica aberta, aí fica lotado de guias". No central cada vaga guardava o seu
# MCClient — e a aba dele no Chrome — até o app fechar: uma aba por tela usada.
class _MCQueFecha:
    fechado = False

    def __init__(self, saidas):
        self.saidas = saidas

    def pulsar(self):
        pass

    def alguma_aba_a_vista(self):
        return False

    def __exit__(self, *exc):
        self.saidas.append((self, threading.get_ident()))


def _abrir_na_vaga(ligado, saidas):
    def abrir():
        ligado.mc = _MCQueFecha(saidas)
        return ligado.mc, threading.get_ident()
    return abrir


def _esperar_pulsos(ligado):
    for vaga in ligado._lista_de_vagas():
        if vaga.pulso is not None:
            vaga.pulso.result(timeout=5)


def _vaga_livre(ligado, dona):
    """A vaga de `dona` depois que o relógio dela ligou.

    O `.result()` acorda quem espera ANTES de o `add_done_callback` rodar
    (é a thread da vaga que chama os dois, nessa ordem): ler `livre_desde`
    logo depois do `.result()` às vezes ainda dá None."""
    import time
    vaga = ligado._vaga_de(dona, criar=False)
    limite = time.perf_counter() + 5     # monotonic pode estar dublado
    while vaga.livre_desde is None:
        assert time.perf_counter() < limite, "o relógio da vaga não ligou"
        time.sleep(0.005)
    return vaga


def test_vaga_parada_ha_tempo_fecha_a_aba_na_thread_dela(ligado, modulo,
                                                         monkeypatch):
    a = _Dona()
    saidas = []
    mc, ident = ligado.submeter("A", _abrir_na_vaga(ligado, saidas),
                                dona=a).result(timeout=5)
    vaga = _vaga_livre(ligado, a)
    agora = vaga.livre_desde + modulo.ABA_OCIOSA_SEG + 1
    monkeypatch.setattr(modulo.time, "monotonic", lambda: agora)
    ligado._pulsar_navegador()
    _esperar_pulsos(ligado)
    assert saidas == [(mc, ident)]
    assert vaga.mc is None and vaga.api is None


def test_vaga_parada_ha_pouco_fica_com_a_aba(ligado, modulo, monkeypatch):
    a = _Dona()
    saidas = []
    ligado.submeter("A", _abrir_na_vaga(ligado, saidas), dona=a).result(timeout=5)
    vaga = _vaga_livre(ligado, a)
    agora = vaga.livre_desde + modulo.ABA_OCIOSA_SEG - 5
    monkeypatch.setattr(modulo.time, "monotonic", lambda: agora)
    ligado._pulsar_navegador()
    _esperar_pulsos(ligado)
    assert saidas == []
    assert vaga.mc is not None


def test_vaga_trabalhando_nunca_fecha_a_aba(ligado, modulo, monkeypatch):
    a = _Dona()
    saidas = []
    solta = threading.Event()
    ligado.submeter("A", _abrir_na_vaga(ligado, saidas), dona=a).result(timeout=5)
    vaga = _vaga_livre(ligado, a)
    antes = vaga.livre_desde
    ligado.submeter("A", solta.wait, 5, dona=a)
    try:
        monkeypatch.setattr(modulo.time, "monotonic",
                            lambda: antes + modulo.ABA_OCIOSA_SEG + 60)
        ligado._pulsar_navegador()
        _esperar_pulsos(ligado)
        assert saidas == []
        assert vaga.livre_desde is None          # trabalho novo zera o relógio
    finally:
        solta.set()


def test_depois_de_fechar_a_proxima_tarefa_abre_outra(ligado, modulo,
                                                      monkeypatch):
    a = _Dona()
    saidas = []
    abrir = _abrir_na_vaga(ligado, saidas)
    ligado.submeter("A", abrir, dona=a).result(timeout=5)
    vaga = _vaga_livre(ligado, a)
    agora = vaga.livre_desde + modulo.ABA_OCIOSA_SEG + 1
    monkeypatch.setattr(modulo.time, "monotonic", lambda: agora)
    ligado._pulsar_navegador()
    _esperar_pulsos(ligado)

    def ve_mc():
        return ligado.mc
    assert ligado.submeter("A", ve_mc, dona=a).result(timeout=5) is None
    mc2, _ = ligado.submeter("A", abrir, dona=a).result(timeout=5)
    assert vaga.mc is mc2 and len(saidas) == 1


# ----------------------- a aba fechada não quebra a etapa seguinte (revisão)
# Fechar a aba parada solta `mc` E `api` da vaga. Toda etapa que roda depois
# de outra ("Buscar" → "Casar e anexar", "Gerar planilha", "Abrir contrato")
# tem de pedir a sessão de novo e recapturar as credenciais — o `MCApi` novo
# nasce sem cabeçalho nenhum.
class _Chega(Exception):
    """Para o `_t_auto` depois do ponto que interessa ao teste."""


class _ApiNova:
    """O `MCApi` recém-criado: sem credenciais até alguém capturar."""

    def __init__(self, cliente=None):
        self.cliente = cliente
        self._req_pagos = None
        self._req_anexos = None
        self.chamadas = []

    def _precisa(self, qual):
        if getattr(self, qual) is None:
            raise RuntimeError("Credenciais ainda não capturadas")

    def capturar_credenciais(self, log=print):
        if not self._req_pagos:
            self.chamadas.append("pagos")
            self._req_pagos = ("https://exemplo.invalid/pagos", {})
        return True

    def capturar_credenciais_anexos(self, launch_id):
        if not self._req_anexos:
            self.chamadas.append("anexos")
            self._req_anexos = ("https://exemplo.invalid/anexos", {})
        return True

    def garantir_credenciais_anexos(self, log=print, dias=365):
        if self._req_anexos:
            return True
        self.capturar_credenciais(log)
        return self.capturar_credenciais_anexos("L-ISCA")

    def verificar_anexos(self, ids, log, progresso=None, cancelar=None):
        self._precisa("_req_anexos")
        self.chamadas.append("verificar")
        raise _Chega()

    def baixar_anexo(self, url):
        self._precisa("_req_anexos")
        return b"%PDF ficticio"

    def anexos_de_obras(self, ids, log=print):
        self._precisa("_req_anexos")
        return {}


class _MCDaVaga:
    """O `MCClient` que o `garantir_sessao` abre, de mentira."""
    fechado = False

    def __init__(self, log=None, a_vista=False):
        self.a_vista = a_vista
        self.saidas = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.saidas += 1

    def vivo(self):
        return True

    def garantir_login(self):
        return True

    def esta_logado(self):
        return True

    def pulsar(self):
        pass

    def alguma_aba_a_vista(self):
        return self.a_vista


def _fechar_por_ociosidade(ligado, modulo, monkeypatch, dona):
    vaga = _vaga_livre(ligado, dona)
    agora = vaga.livre_desde + modulo.ABA_OCIOSA_SEG + 1
    monkeypatch.setattr(modulo.time, "monotonic", lambda: agora)
    ligado._pulsar_navegador()
    _esperar_pulsos(ligado)
    assert vaga.mc is None and vaga.api is None
    return vaga


def test_casar_e_anexar_depois_da_aba_fechada_pede_a_sessao(ligado, modulo,
                                                           monkeypatch,
                                                           tmp_path):
    import queue
    monkeypatch.setattr(modulo, "MCClient", _MCDaVaga)
    monkeypatch.setattr(modulo.mc_api, "MCApi", _ApiNova)
    ligado.q = queue.Queue()
    ligado._parar = threading.Event()
    ligado._checar_pausa = lambda: False
    ligado.pagos = [{"conta": "CONTA EXEMPLO", "launchId": "L1",
                     "paidId": "P1", "desc": "MATERIAL", "categoria": ""}]

    def buscar():                     # o que o "1. Buscar" deixa pronto
        ligado.garantir_sessao().capturar_credenciais()
    ligado.submeter("buscar", buscar).result(timeout=5)
    vaga = _fechar_por_ociosidade(ligado, modulo, monkeypatch, ligado)

    ligado.submeter("casar", ligado._t_auto, {"CONTA EXEMPLO"}, [],
                    str(tmp_path), True).result(timeout=5)
    assert vaga.api is not None, ligado.registro
    assert vaga.api.chamadas == ["pagos", "anexos", "verificar"]


def test_gerar_planilha_depois_da_aba_fechada_baixa_os_anexos(monkeypatch):
    import queue
    from types import SimpleNamespace
    from pagamentos_dia import pagamentos_frame as pf

    nova = _ApiNova()
    dono = pf.PagamentosDiaFrame.__new__(pf.PagamentosDiaFrame)
    # a vaga já soltou o cliente: `anx.api` é None até alguém pedir a sessão
    dono.anx = SimpleNamespace(api=None,
                               garantir_sessao=lambda log=None: nova)
    dono.q = queue.Queue()
    dono._parar = threading.Event()
    url = "https://exemplo.invalid/nf-1.pdf"
    dono._anexos_a_ler = lambda _sel: [(url, True, True)]
    monkeypatch.setattr(pf.relatorio, "texto_de_pdf", lambda _d: "texto da nota")
    monkeypatch.setattr(pf.qr_pix, "ler", lambda *_a: [])
    textos, _ocr, nao_lidos, _qrs = dono._baixar_textos([{"id": "L1"}])
    assert nao_lidos == set()
    assert textos == {url: "texto da nota"}
    assert "anexos" in nova.chamadas


def _aba_de_contratos(monkeypatch, tmp_path, nova):
    import queue
    from types import SimpleNamespace
    from contratos import frame as cf

    aba = cf.ContratosFrame.__new__(cf.ContratosFrame)
    aba.anx = SimpleNamespace(api=None, garantir_sessao=lambda log=None: nova)
    aba.q = queue.Queue()
    aba._parar = threading.Event()
    aba.achados = []
    monkeypatch.setattr(cf.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(cf.os, "startfile", lambda _c: None, raising=False)
    return cf, aba


def _recados(aba):
    saida = []
    while not aba.q.empty():
        saida.append(aba.q.get_nowait())
    return saida


def test_abrir_contrato_depois_da_aba_fechada_tem_credenciais(monkeypatch,
                                                              tmp_path):
    from types import SimpleNamespace
    nova = _ApiNova()
    _cf, aba = _aba_de_contratos(monkeypatch, tmp_path, nova)
    anexo = {"filename": "contrato exemplo.pdf",
             "downloadUrl": "https://exemplo.invalid/c.pdf"}
    aba._t_abrir(SimpleNamespace(obra_id="O1"), anexo)
    assert ("resolver", 'abri "contrato exemplo.pdf" para conferir.'
            ) in _recados(aba)


def test_arquivar_contratos_depois_da_aba_fechada_tem_credenciais(
        monkeypatch, tmp_path):
    from types import SimpleNamespace
    nova = _ApiNova()
    cf, aba = _aba_de_contratos(monkeypatch, tmp_path, nova)
    cfg = SimpleNamespace(RAIZ_PADRAO=str(tmp_path), nome_do_mes=str,
                          nome_pasta_empresa=str)
    contas = SimpleNamespace(
        carregar=lambda: SimpleNamespace(raiz=str(tmp_path)))
    monkeypatch.setattr(cf, "_sicoob", lambda: (cfg, contas))
    aba._periodo = lambda: (2026, 8)
    aba._resumo = lambda *a: None
    monkeypatch.setattr(cf.pipeline, "arquivar",
                        lambda api, *a, **k: api._precisa("_req_anexos"))
    aba._t_arquivar()
    recados = _recados(aba)
    assert any(t == "status" and str(v).startswith("Concluído")
               for t, v in recados), recados
