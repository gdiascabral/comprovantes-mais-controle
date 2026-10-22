# -*- coding: utf-8 -*-
"""Aba "Anexar (novo)": a Anexar de sempre + somas, sem um segundo navegador.

Testes puros: sem janela Tk. O `__init__` roda com ttk/StringVar trocados por
dublês, como `tests/test_abas_em_paralelo.py` faz com `__new__`."""
import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def modulo():
    pytest.importorskip("playwright")
    from anexar import anexar_comprovantes as modulo
    return modulo


class _Var:
    def __init__(self, master=None, value=None, **_k):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


def _sem_tk(*_a, **_k):
    raise RuntimeError("sem Tk no teste")


def _construir(modulo, monkeypatch, classe, *args):
    import tkinter as tk
    from tkinter import ttk
    ch = {"executor": 0, "after": []}

    def executor(*_a, **_k):
        ch["executor"] += 1
        return object()

    monkeypatch.setattr(ttk.Frame, "__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(tk, "StringVar", _Var)
    monkeypatch.setattr(tk, "BooleanVar", _Var)
    monkeypatch.setattr(ttk, "Style", _sem_tk)
    monkeypatch.setattr(modulo.AnexarFrame, "_build", lambda self: None)
    monkeypatch.setattr(modulo.AnexarFrame, "after",
                        lambda self, ms, fn=None, *a: ch["after"].append(fn.__name__))
    monkeypatch.setattr(modulo, "ThreadPoolExecutor", executor)
    return classe(None, *args), ch


def test_a_anexar_de_sempre_continua_dona_do_navegador(modulo, monkeypatch):
    assert modulo.AnexarFrame.DONO_DO_NAVEGADOR is True
    assert modulo.AnexarFrame.TITULO == "Anexar Comprovantes"
    assert modulo.AnexarFrame.TRILHA == "Comprovantes  ›  Anexar"
    f, ch = _construir(modulo, monkeypatch, modulo.AnexarFrame)
    assert ch["executor"] == 1 and f.exec is not None
    assert ch["after"] == ["_drain", "_pulsar_navegador"]


def test_o_cabecalho_le_titulo_e_trilha_da_classe(modulo, monkeypatch):
    """O `_build` de sempre passa os atributos ao `Cabecalho` — com os
    padrões, os mesmos textos de antes."""
    vistos = {}

    class _Parou(Exception):
        pass

    def cabecalho(pai, titulo, sub, trilha=None, **_k):
        vistos.update(titulo=titulo, trilha=trilha)
        raise _Parou

    monkeypatch.setattr(modulo.widgets, "Cabecalho", cabecalho)
    f = modulo.AnexarFrame.__new__(modulo.AnexarFrame)
    with pytest.raises(_Parou):
        f._build()
    assert vistos == {"titulo": "Anexar Comprovantes",
                      "trilha": "Comprovantes  ›  Anexar"}


# ------------------------------------------------- tarefa 8: a aba cópia
@pytest.fixture
def novo(modulo):
    from anexar import anexar_novo
    return anexar_novo


class _Dono:
    def __init__(self):
        self.chamadas, self.mc, self.api = [], "mc-do-dono", "api-do-dono"

    def submeter(self, rotulo, fn, *a, dona=None, **k):
        self.chamadas.append(("submeter", rotulo, dona))
        return "fut"

    def avisar_se_ocupado(self, texto, *, aba=None):
        self.chamadas.append(("avisar", aba))
        return False

    def ocupado(self, aba=None):
        self.chamadas.append(("ocupado", aba))

    def dona_ocupada(self, aba=None):
        self.chamadas.append(("dona_ocupada", aba))

    def garantir_sessao(self, log=None):
        self.chamadas.append(("sessao", log))
        return self.api

    def abrir_minha_aba(self):
        self.chamadas.append(("minha aba",))

    def fechar(self):
        self.chamadas.append(("fechar",))


def _nova(novo, dono):
    f = novo.AnexarNovoFrame.__new__(novo.AnexarNovoFrame)
    f.anx, f.q, f.pagos = dono, novo._FilaComDesvio(), []
    f._parar, f._pausa, f._esperas = threading.Event(), threading.Event(), set()
    f._encerrando = False
    f.winfo_children = lambda: []
    return f


def test_a_copia_nao_cria_executor_nem_pulso(modulo, novo, monkeypatch):
    dono = _Dono()
    f, ch = _construir(modulo, monkeypatch, novo.AnexarNovoFrame, dono)
    assert novo.AnexarNovoFrame.DONO_DO_NAVEGADOR is False
    assert novo.AnexarNovoFrame.TITULO == "Anexar (novo)"
    assert novo.AnexarNovoFrame.TRILHA == "Mensal  ›  Anexar (novo)"
    assert ch["executor"] == 0 and f.exec is None
    assert ch["after"] == ["_drain"]
    assert f.anx is dono and isinstance(f.q, novo._FilaComDesvio)
    assert f.pagos == []


def test_todo_trabalho_vai_para_o_dono_com_a_copia_como_dona(novo):
    dono = _Dono()
    f = _nova(novo, dono)
    assert f.submeter("Anexar — casar", print) == "fut"
    assert f.submeter("Anexar — casar", print, dona="outra") == "fut"
    f.avisar_se_ocupado("o Anexar (novo)")
    f.ocupado()
    f.dona_ocupada()
    f.abrir_minha_aba()
    assert dono.chamadas.count(("submeter", "Anexar — casar", f)) == 2
    assert ("avisar", f) in dono.chamadas and ("ocupado", f) in dono.chamadas
    assert ("dona_ocupada", f) in dono.chamadas and ("minha aba",) in dono.chamadas
    assert f.mc == "mc-do-dono" and f.api == "api-do-dono"
    f.mc = "outro"
    f.api = "outra"
    assert dono.mc == "outro" and dono.api == "outra"
    assert f.garantir_sessao() == dono.api
    assert ("sessao", f._log) in dono.chamadas          # o registro é o da cópia


def test_fechar_da_copia_solta_quem_espera_e_nao_fecha_o_chrome(novo):
    dono = _Dono()
    f = _nova(novo, dono)
    ev = threading.Event()
    f._esperas.add(ev)
    f._pausa.set()
    f.fechar()
    assert ev.is_set() and f._parar.is_set() and not f._pausa.is_set()
    assert f._encerrando and ("fechar",) not in dono.chamadas


def test_o_pulso_da_copia_nao_faz_nada(novo):
    f = _nova(novo, _Dono())
    f.after = lambda *a, **k: pytest.fail("a cópia não pulsa nem reagenda")
    assert f._pulsar_navegador() is None


def test_a_fila_segura_o_fim_so_enquanto_desvia(novo):
    q = novo._FilaComDesvio()
    q.desviar = True
    q.put(("log", "a"))
    q.put(("fim", (1, 1, 0, 0, "")))
    q.desviar = False
    q.put(("fim", (2, 2, 0, 0, "")))
    assert [q.get_nowait() for _ in range(2)] == [("log", "a"), ("fim", (2, 2, 0, 0, ""))]
    assert q.fim_desviado == (1, 1, 0, 0, "")


def _itens(q):
    saida = []
    while not q.empty():
        saida.append(q.get_nowait())
    return saida


def _somas(novo, **k):
    return novo.varios_comprovantes.Somas(**k)


def _anexou_um(novo):
    return lambda *a, **k: _somas(novo, anexados=[{"resultado": "anexado", "valor": 1,
                                                    "pdf": "a + b"}])


def test_casar_e_anexar_roda_a_fase_1_inteira_e_sai_um_fim_somado(modulo, novo,
                                                                  monkeypatch, tmp_path):
    dono = _Dono()
    f = _nova(novo, dono)
    f.pagos = [{"paidId": "P1", "valor": 100}]                   # como o montar_pagos deu

    def fase1(self, contas_sel, termos, pasta, simular):
        self.pagos[0].update(status="SEM PAR")
        self.q.put(("fim", (0, 0, 0, 1, "rel.xlsx")))

    chamadas = []

    def somas(api, pagos, pasta, **k):
        chamadas.append((api, pagos))
        return _anexou_um(novo)()

    monkeypatch.setattr(modulo.AnexarFrame, "_t_auto", fase1)
    monkeypatch.setattr(novo.varios_comprovantes, "fase_das_somas", somas)
    relatorio = []
    monkeypatch.setattr(novo.varios_comprovantes, "acrescentar_ao_relatorio",
                        lambda caminho, somas: relatorio.append(caminho))
    f._t_auto({"C"}, [], str(tmp_path), False)
    fins = [v for k, v in _itens(f.q) if k == "fim"]
    assert fins == [(1, 1, 0, 0, "rel.xlsx")]
    assert [api for api, _ in chamadas] == ["api-do-dono"]
    assert chamadas[0][1] is f.pagos and relatorio == ["rel.xlsx"]
    assert f.q.desviar is False


def test_cada_rodada_remonta_os_pagos_sem_sobra_da_anterior(modulo, novo, monkeypatch,
                                                           tmp_path):
    """`motivo_soma`, status, PDF e afins de uma rodada não podem prender a
    seguinte: cada "Casar e anexar" começa dos pagos como a busca os trouxe."""
    f = _nova(novo, _Dono())
    f.pagos = [{"paidId": "P1", "valor": 100, "works": ["OBRA MODELO"]}]
    vistos, nas_somas = [], []

    def fase1(self, *a):
        vistos.append(copy.deepcopy(self.pagos))
        self.pagos[0].update(status="SEM PAR", motivo_sem_par="x", motivo_soma="x",
                             pdf="velho.pdf", resultado="anexado")
        self.pagos[0]["works"].append("SUJEIRA")
        self.q.put(("fim", (0, 0, 0, 1, "")))

    def somas(api, pagos, pasta, **k):
        nas_somas.append(pagos)
        return _somas(novo)

    monkeypatch.setattr(modulo.AnexarFrame, "_t_auto", fase1)
    monkeypatch.setattr(novo.varios_comprovantes, "fase_das_somas", somas)
    monkeypatch.setattr(novo.varios_comprovantes, "acrescentar_ao_relatorio",
                        lambda *a: None)
    f._t_auto({"C"}, [], str(tmp_path), False)
    f._t_auto({"C"}, [], str(tmp_path), False)
    limpo = [{"paidId": "P1", "valor": 100, "works": ["OBRA MODELO"]}]
    assert vistos == [limpo, limpo]
    assert nas_somas[0] is not nas_somas[1]              # lista nova a cada rodada


def test_fase_1_com_erro_nao_roda_a_fase_2(modulo, novo, monkeypatch, tmp_path):
    f = _nova(novo, _Dono())

    def fase1(self, *a):
        self.q.put(("reabilitar2", None))

    monkeypatch.setattr(modulo.AnexarFrame, "_t_auto", fase1)
    monkeypatch.setattr(novo.varios_comprovantes, "fase_das_somas",
                        lambda *a, **k: pytest.fail("não devia somar"))
    f._t_auto({"C"}, [], str(tmp_path), False)
    assert _itens(f.q) == [("reabilitar2", None)] and f.q.desviar is False


def test_fase_1_que_explode_solta_a_fila(modulo, novo, monkeypatch, tmp_path):
    f = _nova(novo, _Dono())

    def fase1(self, *a):
        raise RuntimeError("bug")

    monkeypatch.setattr(modulo.AnexarFrame, "_t_auto", fase1)
    with pytest.raises(RuntimeError):
        f._t_auto({"C"}, [], str(tmp_path), False)
    assert f.q.desviar is False


def test_parado_na_fase_1_nao_soma_e_devolve_o_fim_dela(modulo, novo, monkeypatch, tmp_path):
    f = _nova(novo, _Dono())

    def fase1(self, *a):
        self._parar.set()
        self.q.put(("fim", (1, 2, 0, 0, "")))

    monkeypatch.setattr(modulo.AnexarFrame, "_t_auto", fase1)
    monkeypatch.setattr(novo.varios_comprovantes, "fase_das_somas",
                        lambda *a, **k: pytest.fail("não devia somar"))
    f._t_auto({"C"}, [], str(tmp_path), False)
    assert _itens(f.q) == [("fim", (1, 2, 0, 0, ""))]


def test_erro_na_fase_2_ainda_entrega_o_fim_da_fase_1(modulo, novo, monkeypatch, tmp_path):
    f = _nova(novo, _Dono())

    def fase1(self, *a):
        self.q.put(("fim", (1, 1, 0, 1, "")))

    def somas(*a, **k):
        raise RuntimeError("API caiu")

    monkeypatch.setattr(modulo.AnexarFrame, "_t_auto", fase1)
    monkeypatch.setattr(novo.varios_comprovantes, "fase_das_somas", somas)
    f._t_auto({"C"}, [], str(tmp_path), False)
    itens = _itens(f.q)
    assert [v for k, v in itens if k == "fim"] == [(1, 1, 0, 1, "")]
    assert any(k == "log" and "API caiu" in v for k, v in itens)


def test_relatorio_que_nao_grava_nao_apaga_a_conta_das_somas(modulo, novo, monkeypatch,
                                                            tmp_path):
    """Excel aberto na máquina: o anexo já foi feito, o "Concluído" tem de contá-lo."""
    f = _nova(novo, _Dono())

    def fase1(self, *a):
        self.q.put(("fim", (0, 0, 0, 1, "rel.xlsx")))

    def nao_grava(*a):
        raise PermissionError("rel.xlsx aberto")

    monkeypatch.setattr(modulo.AnexarFrame, "_t_auto", fase1)
    monkeypatch.setattr(novo.varios_comprovantes, "fase_das_somas", _anexou_um(novo))
    monkeypatch.setattr(novo.varios_comprovantes, "acrescentar_ao_relatorio", nao_grava)
    f._t_auto({"C"}, [], str(tmp_path), False)
    itens = _itens(f.q)
    assert [v for k, v in itens if k == "fim"] == [(1, 1, 0, 0, "rel.xlsx")]
    assert any(k == "log" and "rel.xlsx aberto" in v for k, v in itens)


# ---- a fase das somas roda INTEIRA na thread do navegador (Playwright sync)
def _dono_de_verdade(modulo, monkeypatch, *, ligado):
    monkeypatch.setattr(modulo.central, "ligado", lambda *a, **k: ligado)
    d = modulo.AnexarFrame.__new__(modulo.AnexarFrame)
    d.mc = "mc-do-dono"
    d.api = "api-do-dono"
    d.exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nav-do-dono")
    d._trabalho_atual = d._rotulo_atual = d._pulso_nav = None
    d._encerrando = False
    return d


def _desligar(dono):
    for vaga in list(getattr(dono, "_vagas", {}).values()):
        vaga.executor.shutdown(wait=True)
    dono.exec.shutdown(wait=True)


@pytest.mark.parametrize("ligado", [False, True])
def test_fase_1_e_somas_rodam_na_mesma_thread_do_navegador(modulo, novo, monkeypatch,
                                                           tmp_path, ligado):
    dono = _dono_de_verdade(modulo, monkeypatch, ligado=ligado)
    f = _nova(novo, dono)
    if ligado:
        dono._vaga_de(f).api = "api-da-vaga-da-copia"
    f.pagos = [{"paidId": "P1", "valor": 100}]
    visto = {}

    def fase1(self, *a):
        visto["fase1"] = threading.current_thread()
        visto["api1"] = self.api
        self.q.put(("fim", (0, 0, 0, 1, "")))

    def somas(api, pagos, pasta, **k):
        visto["fase2"] = threading.current_thread()
        visto["api2"] = api
        return _somas(novo)

    monkeypatch.setattr(modulo.AnexarFrame, "_t_auto", fase1)
    monkeypatch.setattr(novo.varios_comprovantes, "fase_das_somas", somas)
    monkeypatch.setattr(novo.varios_comprovantes, "acrescentar_ao_relatorio",
                        lambda *a: None)
    try:
        fut = f.submeter("Anexar — casar e anexar", f._t_auto, {"C"}, [], str(tmp_path),
                         False)
        fut.result(timeout=10)
        assert dono.dona_ocupada(aba=f) is None
    finally:
        _desligar(dono)
    assert visto["fase1"] is visto["fase2"]
    assert visto["fase1"] is not threading.main_thread()
    esperado = "nav-AnexarNovoFrame" if ligado else "nav-do-dono"
    assert visto["fase1"].name.startswith(esperado)
    api = "api-da-vaga-da-copia" if ligado else "api-do-dono"
    assert visto["api1"] == visto["api2"] == api


# ------------------------------------------- tarefa 9: menu e galeria
def _grupos_do_app() -> dict:
    import ast
    saida = {}
    arvore = ast.parse((RAIZ / "comprovantes_app.py").read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if isinstance(no, ast.Call) and getattr(no.func, "id", "") == "_grupo":
            saida[ast.literal_eval(no.args[0])] = ast.literal_eval(no.args[2])
    return saida


def test_a_copia_e_o_ultimo_item_do_mensal_e_o_app_a_monta_sobre_o_dono():
    texto = (RAIZ / "comprovantes_app.py").read_text(encoding="utf-8")
    assert "from anexar.anexar_novo import AnexarNovoFrame" in texto
    assert "aba_anx2 = AnexarNovoFrame(conteudo, aba_anx)" in texto
    assert texto.index("aba_anx = AnexarFrame(conteudo)") < texto.index("aba_anx2 =")
    mensal = _grupos_do_app()["mensal"]
    assert mensal[-1] == ("anx2", "📎", "Anexar (novo)")
    assert [c for c, _i, _t in mensal] == ["rel", "ext", "ctr", "acs", "anx2"]
    # a seção Comprovantes não muda: a cópia não está nela
    assert '("bxc", "sep", "anx", "conf", "apt")' in texto
    assert '("anx2"' not in texto[texto.index('lateral.secao("Comprovantes")'):
                                  texto.index("grupos: dict[str, dict] = {}")]


def test_o_sair_fecha_a_copia_antes_do_dono():
    """O `_sair` fecha na ordem de `quadros`: a cópia solta a thread que
    espera na janela de dúvidas ANTES de o dono fechar o Chrome nela."""
    texto = (RAIZ / "comprovantes_app.py").read_text(encoding="utf-8")
    assert texto.index('"anx2": aba_anx2') < texto.index('"anx": aba_anx,')


def test_nenhum_atalho_ctrl_1_a_9_existente_muda_com_a_copia():
    """A ordem do menu é a ordem dos atalhos (`itens`): Início, a seção
    Comprovantes e os grupos. A cópia, no fim, não empurra ninguém."""
    grupos = _grupos_do_app()
    ordem = (["ini", "bxc", "sep", "anx", "conf", "apt"]
             + [c for c, _i, _t in grupos["diario"]]
             + [c for c, _i, _t in grupos["mensal"]])
    assert ordem[:9] == ["ini", "bxc", "sep", "anx", "conf", "apt", "dia", "pag", "con"]
    assert ordem[-1] == "anx2" and ordem.count("anx2") == 1


def test_a_galeria_monta_a_copia_e_nao_perde_os_aportes():
    """Achado 8: a seção Comprovantes da galeria vai por CHAVE — uma fatia
    por posição do `_ORDEM` tiraria a aba Aportes quando entra item novo."""
    import ast
    texto = (RAIZ / "ferramentas" / "galeria.py").read_text(encoding="utf-8")
    ordem = None
    for no in ast.walk(ast.parse(texto)):
        if (isinstance(no, ast.Assign) and getattr(no.targets[0], "id", "") == "_ORDEM"):
            ordem = ast.literal_eval(no.value)
    chaves = [i[0] for i in ordem]
    assert chaves[-1] == "anx2" and ordem[-1][:3] == ("anx2", "📎", "Anexar (novo)")
    assert "_ORDEM[1:" not in texto
    assert 'i[0] in ("bxc", "sep", "anx", "conf", "apt")' in texto
    assert 'i[0] in ("rel", "ext", "ctr", "acs", "anx2")' in texto
    assert '_montar("anx2", lambda: AnexarNovoFrame(conteudo, aba_anx))' in texto
    assert "from anexar.anexar_novo import AnexarNovoFrame" in texto
    # o menu da galeria segue o do app: mesma ordem de chaves
    grupos = _grupos_do_app()
    menu = (["ini", "bxc", "sep", "anx", "conf", "apt"]
            + [c for c, _i, _t in grupos["diario"]] + [c for c, _i, _t in grupos["mensal"]])
    assert chaves == menu


# ------------------------------------------- conserto (rodada 1)
A400 = "400,00 - OBRA MODELO OC 5555 - 22-10.pdf"
A600 = "600,00 - OBRA MODELO OC 5555 - 22-10.pdf"
DOC_X, DOC_Y = "11111111000111", "22222222000122"


class _ApiFalsa:
    def __init__(self):
        self.anexos, self.enviados = {}, []

    def verificar_anexos(self, ids, log=print, progresso=None, cancelar=None):
        return {i: len(self.anexos.get(i, [])) for i in ids}

    def _anexos_brutos(self, pid):
        return list(self.anexos.get(pid, []))

    def anexar_por_api(self, pid, caminho, *, log=None, dry_run=False, tag=None):
        caminho = Path(caminho)
        self.enviados.append(caminho.name)
        self.anexos.setdefault(pid, []).append(
            {"name": caminho.name, "sizeInBytes": caminho.stat().st_size})
        return "anexado"


def _pend_x():
    """Pago a X (o cadastro do ERP, lido na fase 1, deu o CNPJ de X)."""
    return {"paidId": "P1", "launchId": "L-P1", "valor": 100000, "valores": [100000],
            "doc": "", "desc": "COMPRA OC 5555", "works": ["OBRA MODELO"], "data": "2210",
            "conta": "CONTA EXEMPLO - SICOOB", "favorecido": "Fornecedor Modelo Ltda",
            "dataFull": "22/10/2026", "categoria": "", "doc_favorecido": DOC_X}


def _origem_como_a_de_verdade(pendentes, pdfs, pasta, *, documentos=None, **_k):
    """O que o `origem.preencher` faz: recebedor nos PDFs e, sem `documentos`,
    o `doc_favorecido` dos lançamentos vira None."""
    for pd in pdfs:
        pd.update(origem=None, recebedor="Outro Modelo Ltda", doc_recebedor=DOC_Y)
    for pe in pendentes:
        pe["doc_favorecido"] = (documentos or {}).get(pe.get("favorecido"))
        pe["origem"] = None
    return {}


def _fase_com_a_copia(novo, f, tmp_path, pagos, api):
    from anexar import matcher
    for nome, n in ((A600, 10), (A400, 11)):
        (tmp_path / nome).write_bytes(b"x" * n)
    return novo.varios_comprovantes.fase_das_somas(
        api, pagos, tmp_path, simular=False,
        carregar_pdfs=lambda pasta, log: [matcher.parse_pdf(n) for n in (A400, A600)],
        preencher_origem=lambda pend, pdfs: f._preparar_somas(pend, pdfs, tmp_path),
        log=lambda _m: None)


def test_a_fase_2_preserva_o_doc_favorecido_da_fase_1(novo, monkeypatch, tmp_path):
    from anexar import matcher
    monkeypatch.setattr(novo.origem, "preencher", _origem_como_a_de_verdade)
    f = _nova(novo, _Dono())
    pe = _pend_x()
    matcher.casar([pe], [])                               # fase 1: SEM PAR
    api = _ApiFalsa()
    somas = _fase_com_a_copia(novo, f, tmp_path, [pe], api)
    assert pe["doc_favorecido"] == DOC_X
    # PDFs pagos a Y não entram no pagamento de X
    assert somas.anexados == [] and api.enviados == [] and pe["status"] == "SEM PAR"


def test_controle_mesmo_recebedor_casa(novo, monkeypatch, tmp_path):
    """Controle positivo: recebedor = favorecido, a soma sobe."""
    from anexar import matcher

    def mesmo(pendentes, pdfs, pasta, **k):
        _origem_como_a_de_verdade(pendentes, pdfs, pasta, **k)
        for pd in pdfs:
            pd["doc_recebedor"] = DOC_X

    monkeypatch.setattr(novo.origem, "preencher", mesmo)
    f = _nova(novo, _Dono())
    pe = _pend_x()
    matcher.casar([pe], [])
    api = _ApiFalsa()
    somas = _fase_com_a_copia(novo, f, tmp_path, [pe], api)
    assert [p["paidId"] for p in somas.anexados] == ["P1"]
    assert sorted(api.enviados) == sorted([A400, A600])


def test_o_t_auto_passa_o_preparo_da_copia_as_somas(modulo, novo, monkeypatch, tmp_path):
    f = _nova(novo, _Dono())
    vistos = []
    monkeypatch.setattr(novo.AnexarNovoFrame, "_preparar_somas",
                        lambda self, pend, pdfs, pasta: vistos.append((pend, pdfs, pasta)))

    def fase1(self, *a):
        self.q.put(("fim", (0, 0, 0, 1, "")))

    def somas(api, pagos, pasta, *, preencher_origem, **k):
        preencher_origem(["pe"], ["pd"])
        return _somas(novo)

    monkeypatch.setattr(modulo.AnexarFrame, "_t_auto", fase1)
    monkeypatch.setattr(novo.varios_comprovantes, "fase_das_somas", somas)
    f._t_auto({"C"}, [], str(tmp_path), False)
    assert vistos == [(["pe"], ["pd"], Path(str(tmp_path)))]


CODIGO = "1" * 44


def _barras_falsas(novo, monkeypatch, lidos):
    def texto(nome, dados):
        lidos.append(nome)
        return (CODIGO if nome == A400 else ""), False

    monkeypatch.setattr(novo.codigo_barras, "texto_do_arquivo", texto)
    monkeypatch.setattr(novo.codigo_barras, "codigos_no_texto",
                        lambda t, valores=(), ocr=False: {t} if t else set())


def test_a_fase_2_le_o_codigo_de_barras_dos_pdfs_recarregados(novo, monkeypatch, tmp_path):
    lidos = []
    _barras_falsas(novo, monkeypatch, lidos)
    monkeypatch.setattr(novo.origem, "preencher", lambda *a, **k: {})
    f = _nova(novo, _Dono())
    for nome in (A400, A600, "1000,00 - X.pdf"):
        (tmp_path / nome).write_bytes(b"x")
    pdfs = [{"fn": A400, "valor": 40000}, {"fn": A600, "valor": 60000},
            {"fn": "1000,00 - X.pdf", "valor": 100000}]
    f._preparar_somas([_pend_x()], pdfs, tmp_path)
    assert [pd["barras"] for pd in pdfs] == [{CODIGO}, set(), set()]
    assert sorted(lidos) == sorted([A400, A600])         # o do valor cheio não é parcela


def test_pdf_com_codigo_do_titulo_de_outro_nao_entra_na_soma(novo, monkeypatch, tmp_path):
    from anexar import matcher
    _barras_falsas(novo, monkeypatch, [])
    monkeypatch.setattr(novo.origem, "preencher", lambda *a, **k: {})
    f = _nova(novo, _Dono())
    pe = _pend_x()
    outro = dict(_pend_x(), paidId="P2", launchId="L-P2", valor=55500, valores=[55500],
                 data="0110", barras={CODIGO}, status="CERTEZA")
    matcher.casar([pe], [])
    api = _ApiFalsa()
    somas = _fase_com_a_copia(novo, f, tmp_path, [pe, outro], api)
    assert somas.anexados == [] and api.enviados == []


class _Rodando:
    def done(self):
        return False


def _executar_com(modulo, novo, monkeypatch, *, ligado, quem):
    """`quem` está com o navegador: "anexar" (a aba de sempre), "outra" ou None."""
    dono = _dono_de_verdade(modulo, monkeypatch, ligado=ligado)
    f = _nova(novo, dono)
    f.worker = None
    outra = object()
    if quem:
        dona = dono if quem == "anexar" else outra
        if ligado:
            dono._vaga_de(dona).trabalho_atual = _Rodando()
            dono._vaga_de(dona).rotulo_atual = "Anexar — casar e anexar"
        else:
            dono._trabalho_atual, dono._dona_atual = _Rodando(), dona
            dono._rotulo_atual = "Anexar — casar e anexar"
    chamadas = []
    monkeypatch.setattr(modulo.AnexarFrame, "executar", lambda self: chamadas.append("fase"))
    monkeypatch.setattr(novo.messagebox, "showwarning",
                        lambda titulo, texto, **k: chamadas.append(("aviso", texto)))
    try:
        f.executar()
    finally:
        _desligar(dono)
    return chamadas


@pytest.mark.parametrize("ligado", [False, True])
def test_a_copia_nao_comeca_com_a_anexar_de_sempre_trabalhando(modulo, novo, monkeypatch,
                                                               ligado):
    """No central as duas abas têm vagas diferentes: casariam ao mesmo tempo e
    subiriam o mesmo PDF duas vezes."""
    chamadas = _executar_com(modulo, novo, monkeypatch, ligado=ligado, quem="anexar")
    assert "fase" not in chamadas
    assert len(chamadas) == 1 and "Anexar" in chamadas[0][1]


@pytest.mark.parametrize("ligado", [False, True])
@pytest.mark.parametrize("quem", [None, "outra"])
def test_a_copia_comeca_com_a_anexar_livre(modulo, novo, monkeypatch, ligado, quem):
    assert _executar_com(modulo, novo, monkeypatch, ligado=ligado, quem=quem) == ["fase"]


# ---- a atividade do Início: a cópia anota "anx2", não "anx"
def test_cada_aba_anota_a_atividade_com_a_sua_chave(modulo, novo):
    import ast
    assert modulo.AnexarFrame.ATIVIDADE == "anx"
    assert novo.AnexarNovoFrame.ATIVIDADE == "anx2"
    arvore = ast.parse((RAIZ / "anexar" / "anexar_comprovantes.py").read_text(encoding="utf-8"))
    primeiros = [ast.unparse(no.args[0]) for no in ast.walk(arvore)
                 if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
                 and no.func.attr == "registrar_atividade"]
    assert primeiros == ["self.ATIVIDADE"]


def test_o_inicio_da_nome_a_anx2_sem_virar_rotina_nem_mexer_no_anexar():
    from inicio.inicio_frame import OUTRAS_ORIGENS, ROTINAS
    assert OUTRAS_ORIGENS.get("anx2") == "Anexar (novo)"
    assert "anx2" not in {c for c, _n, _r in ROTINAS}


def test_o_inicio_le_eventos_da_anx2_sem_quebrar(monkeypatch):
    import widgets
    from inicio import inicio_frame
    eventos = [
        {"quando": "2026-10-22T10:00:00", "aba": "anx2", "evento": "Casar e anexar",
         "resultado": "ok", "numeros": {"anexados": 7, "pagos": 9}},
        {"quando": "2026-10-21T10:00:00", "aba": "anx", "evento": "Casar e anexar",
         "resultado": "ok", "numeros": {"anexados": 3, "pagos": 4}},
    ]
    monkeypatch.setattr(widgets, "atividades", lambda n: list(eventos))
    f = inicio_frame.InicioFrame.__new__(inicio_frame.InicioFrame)
    pintado = {}
    f._pintar_kpis = lambda numeros: pintado.update(kpis=numeros)
    f._pintar_rotinas = lambda ultimos: pintado.update(rotinas=ultimos)
    f._pintar_atividade = lambda evs: pintado.update(atividade=evs)
    f.ao_abrir()
    assert pintado["kpis"]["anx"]["anexados"] == 3          # cada aba com os seus
    assert pintado["kpis"]["anx2"]["anexados"] == 7
    assert pintado["rotinas"]["anx"]["aba"] == "anx"
    assert len(pintado["atividade"]) == 2


class _Cartao:
    def __init__(self):
        self.valor = None

    def definir(self, valor, apoio="", **_k):
        self.valor = (valor, apoio)


def _kpi_anexados(monkeypatch, eventos):
    import widgets
    from inicio import inicio_frame
    monkeypatch.setattr(widgets, "atividades", lambda n: list(eventos))
    f = inicio_frame.InicioFrame.__new__(inicio_frame.InicioFrame)
    f.kpis = {k: _Cartao() for k in ("hoje", "sem_remessa", "anexados", "pendencias")}
    f._pintar_rotinas = lambda ultimos: None
    f._pintar_atividade = lambda evs: None
    f.ao_abrir()
    return f.kpis["anexados"].valor


def _ev(aba, anexados, pagos, horas_atras):
    import datetime as dt
    quando = (dt.datetime.now() - dt.timedelta(hours=horas_atras)).isoformat(timespec="seconds")
    if quando[:7] != dt.datetime.now().isoformat()[:7]:      # virada do mês: fica no mês
        quando = dt.datetime.now().replace(day=1, hour=0, minute=0).isoformat()
    return {"quando": quando, "aba": aba, "evento": "Casar e anexar", "resultado": "ok",
            "numeros": {"anexados": anexados, "pagos": pagos}}


def test_anexados_no_mes_soma_a_anexar_e_a_anexar_nova_sem_contar_em_dobro(monkeypatch):
    """Para o dono é tudo anexo. Cada aba entra com a SUA última rodada (a
    regra de sempre do Início); a rodada mais velha da cópia não soma de novo."""
    eventos = [_ev("anx2", 7, 9, 0), _ev("anx2", 5, 6, 1), _ev("anx", 3, 4, 2)]
    assert _kpi_anexados(monkeypatch, eventos) == ("10", "76% dos pagos")


def test_anexados_no_mes_so_com_uma_das_duas(monkeypatch):
    assert _kpi_anexados(monkeypatch, [_ev("anx", 3, 4, 0)]) == ("3", "75% dos pagos")
    assert _kpi_anexados(monkeypatch, [_ev("anx2", 7, 9, 0)]) == ("7", "77% dos pagos")
    assert _kpi_anexados(monkeypatch, [])[0] == "—"


# ---- o outro lado: a Anexar de sempre não começa com a cópia casando
class _Seguiu(Exception):
    """A `executar` da Anexar passou da recusa e foi ler o formulário."""


class _Campo:
    def get(self):
        raise _Seguiu


def _anexar_executa(modulo, novo, monkeypatch, *, ligado, quem, registrar=True):
    """`quem` está com o navegador: "copia", "anexar", "outra" ou None."""
    dono = _dono_de_verdade(modulo, monkeypatch, ligado=ligado)
    copia = _nova(novo, dono)
    if registrar:
        dono._copias = (copia,)
    dono.worker = None
    dono.v_pasta = _Campo()
    if quem:
        dona = {"copia": copia, "anexar": dono, "outra": object()}[quem]
        rotulo = "Anexar — casar e anexar"
        if ligado:
            dono._vaga_de(dona).trabalho_atual = _Rodando()
            dono._vaga_de(dona).rotulo_atual = rotulo
        else:
            dono._trabalho_atual, dono._dona_atual, dono._rotulo_atual = (
                _Rodando(), dona, rotulo)
    avisos = []
    monkeypatch.setattr(modulo.messagebox, "showwarning",
                        lambda titulo, texto, **k: avisos.append(texto))
    try:
        try:
            modulo.AnexarFrame.executar(dono)
            seguiu = False
        except _Seguiu:
            seguiu = True
    finally:
        _desligar(dono)
    return seguiu, avisos


@pytest.mark.parametrize("ligado", [False, True])
def test_a_anexar_nao_comeca_com_a_copia_casando(modulo, novo, monkeypatch, ligado):
    seguiu, avisos = _anexar_executa(modulo, novo, monkeypatch, ligado=ligado, quem="copia")
    assert not seguiu and len(avisos) == 1
    assert "Anexar (novo)" in avisos[0] and "Anexar — casar e anexar" in avisos[0]


@pytest.mark.parametrize("ligado", [False, True])
@pytest.mark.parametrize("quem", [None, "anexar", "outra"])
def test_sem_a_copia_trabalhando_a_anexar_e_a_de_hoje(modulo, novo, monkeypatch, ligado,
                                                      quem):
    seguiu, avisos = _anexar_executa(modulo, novo, monkeypatch, ligado=ligado, quem=quem)
    assert seguiu and avisos == []


@pytest.mark.parametrize("ligado", [False, True])
def test_sem_copia_registrada_a_anexar_e_a_de_hoje(modulo, novo, monkeypatch, ligado):
    seguiu, avisos = _anexar_executa(modulo, novo, monkeypatch, ligado=ligado, quem="copia",
                                     registrar=False)
    assert seguiu and avisos == []


def test_a_copia_se_registra_no_dono(modulo, novo, monkeypatch):
    dono = _Dono()
    f, _ch = _construir(modulo, monkeypatch, novo.AnexarNovoFrame, dono)
    assert dono._copias == (f,)
