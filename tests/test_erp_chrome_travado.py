# -*- coding: utf-8 -*-
"""Chrome central travado: detectar, não empilhar Chrome, reiniciar, avisar.

09/11/2026: o Chrome central parou às 14:04 com a porta 9230 ABERTA e calada.
Porteiro e robôs abriram outro chrome.exe a cada tentativa (cada um preso no
aviso "não está respondendo"), o porteiro ficou preso numa chamada do
Playwright até 14:33 e ninguém foi avisado. Nada aqui abre Chrome de verdade.
"""
import datetime as dt
import json

import pytest

from erp import central, porteiro, vigia


def _a(tmp_path, nome="principal", porta=9230):
    return central.Acesso(nome, tmp_path / nome, porta)


# ------------------------------------------------------- fechado x mudo

def test_estado_vivo(tmp_path):
    assert central.estado_chrome(_a(tmp_path), vivo=lambda a: True) == "vivo"


def test_estado_fechado_quando_a_porta_nao_aceita(tmp_path):
    assert central.estado_chrome(_a(tmp_path), vivo=lambda a: False,
                                 ouvindo=lambda a: False) == "fechado"


def test_estado_mudo_quando_a_porta_aceita_e_nao_responde(tmp_path):
    assert central.estado_chrome(_a(tmp_path), vivo=lambda a: False,
                                 ouvindo=lambda a: True,
                                 vivo_lento=lambda a: False) == "mudo"


def test_estado_so_lento_conta_como_vivo(tmp_path):
    assert central.estado_chrome(_a(tmp_path), vivo=lambda a: False,
                                 ouvindo=lambda a: True,
                                 vivo_lento=lambda a: True) == "vivo"


def test_garantir_chrome_mudo_nao_sobe_outro(tmp_path):
    subidos = []
    with pytest.raises(central.ChromeTravado) as e:
        central.garantir_chrome(_a(tmp_path), popen=lambda *a, **k: subidos.append(a),
                                vivo=lambda a: False, ouvindo=lambda a: True,
                                vivo_lento=lambda a: False, exe="chrome.exe")
    assert subidos == []
    assert "não responde na porta 9230" in str(e.value)     # PASSAGEIRA no rodar_e_relatar
    assert not isinstance(e.value, TimeoutError)             # no app: trava de arquivo


def test_garantir_chrome_lento_nao_sobe_outro(tmp_path):
    subidos = []
    r = central.garantir_chrome(_a(tmp_path), popen=lambda *a, **k: subidos.append(a),
                                vivo=lambda a: False, ouvindo=lambda a: True,
                                vivo_lento=lambda a: True, exe="chrome.exe")
    assert r == "http://127.0.0.1:9230" and subidos == []


def test_matar_chrome_mata_cada_processo_com_os_filhos(tmp_path):
    ordens = []
    pids = central.matar_chrome(_a(tmp_path), pids=lambda a: [11, 22],
                                rodar=lambda cmd, **k: ordens.append(cmd))
    assert pids == [11, 22]
    assert ordens == [["taskkill", "/PID", "11", "/T", "/F"],
                      ["taskkill", "/PID", "22", "/T", "/F"]]


# ------------------------------------------------------- o ciclo com socorro

def _ciclo(a, estado, socorro, feitos):
    return porteiro.um_ciclo(
        {a.nome: a}, vivo=lambda ac: estado[0],
        subir_chrome=lambda ac: feitos.append("subiu"),
        checar_login=lambda ac: feitos.append("login") or True,
        log=lambda *_: None,
        faxinar=lambda ac, logado: feitos.append("faxina") or [],
        socorro=socorro)


def test_mudo_tres_ciclos_mata_e_sobe_de_novo(tmp_path):
    a = _a(tmp_path)
    mortos, soltos, feitos = [], [], []
    s = porteiro.Socorro(matar=lambda ac: mortos.append(ac.nome) or [3384],
                         ao_matar=soltos.append)
    estado = ["mudo"]
    r1 = _ciclo(a, estado, s, feitos)
    r2 = _ciclo(a, estado, s, feitos)
    assert r1 == ["principal: CHROME TRAVADO — a porta 9230 aceita conexão e não "
                  "responde (1ª vez seguida)"]
    assert "2ª vez" in r2[0]
    assert feitos == [] and mortos == []          # nada de Playwright nem faxina
    r3 = _ciclo(a, estado, s, feitos)
    assert mortos == ["principal"] and soltos == ["principal"]
    assert feitos == ["subiu", "login", "faxina"]
    assert r3 == ["principal: Chrome travado há 3 ciclos: reiniciado (processos 3384); "
                  "chrome subiu; ok"]


def test_chrome_que_volta_zera_a_conta(tmp_path):
    a = _a(tmp_path)
    mortos = []
    s = porteiro.Socorro(matar=lambda ac: mortos.append(1) or [])
    for e in ["mudo", "mudo", "vivo", "mudo", "mudo"]:
        _ciclo(a, [e], s, [])
    assert mortos == []


def test_ciclo_aceita_o_vivo_antigo_em_bool(tmp_path):
    a = _a(tmp_path)
    feitos = []
    assert _ciclo(a, [False], None, feitos) == ["principal: chrome subiu; ok"]


# ------------------------------------------------------- ids das abas: uma vez

class _Sess:
    def __init__(self, n, tid):
        self._n, self._tid = n, tid

    def send(self, metodo):
        self._n.append(metodo)
        return {"targetInfo": {"targetId": self._tid}}

    def detach(self):
        pass


class _Aba:
    def __init__(self, n, tid):
        self.context = self
        self._n, self._tid = n, tid

    def new_cdp_session(self, aba):
        return _Sess(self._n, self._tid)


def test_ids_das_abas_pergunta_uma_vez_por_aba(tmp_path):
    n = []

    class Cli:
        _minhas = [_Aba(n, "T1")]

        def vivo(self):
            return True

        def esta_logado(self):
            return True
    c = Cli()
    m = porteiro.Mantenedor(lambda a: c, lambda c: None)
    m.checar(_a(tmp_path))
    assert m.ids_das_abas("principal") == {"T1"}
    assert m.ids_das_abas("principal") == {"T1"}
    assert len(n) == 1
    c._minhas = [_Aba(n, "T2")]                     # aba nova: pergunta a ela
    assert m.ids_das_abas("principal") == {"T2"} and len(n) == 2


# ------------------------------------------------------- a guarda

class _Rel:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _guarda(tmp_path, estado="vivo", **k):
    rel, feito = _Rel(), {"matar": [], "driver": 0, "sair": []}

    def driver():
        feito["driver"] += 1
        return [4824]
    g = porteiro.Guarda({"principal": _a(tmp_path)}, log=lambda *_: None,
                        estado=lambda a: estado,
                        matar=lambda a: feito["matar"].append(a.nome) or [1],
                        matar_driver=driver, sair=feito["sair"].append,
                        relogio=rel, **k)
    return g, rel, feito


def test_guarda_quieta_com_o_ciclo_andando(tmp_path):
    g, rel, feito = _guarda(tmp_path, estado="mudo")
    rel.t = 299
    assert g.verificar() is None and feito["matar"] == []


def test_guarda_mata_o_chrome_mudo_com_o_ciclo_parado(tmp_path):
    g, rel, feito = _guarda(tmp_path, estado="mudo")
    rel.t = 301
    assert g.verificar() is None and g.verificar() is None
    assert "Chrome reiniciado" in g.verificar()
    assert feito["matar"] == ["principal"] and feito["driver"] == 0


def test_guarda_marcar_zera(tmp_path):
    g, rel, feito = _guarda(tmp_path, estado="mudo")
    rel.t = 301
    g.verificar(); g.verificar()
    g.marcar()
    rel.t = 700
    g.verificar(); g.verificar()
    assert feito["matar"] == []


def test_guarda_com_chrome_vivo_mata_o_driver_uma_vez_e_depois_sai(tmp_path):
    g, rel, feito = _guarda(tmp_path, estado="vivo")
    rel.t = 600
    assert g.verificar() is None                    # login pode esperar 10 min
    rel.t = 901
    assert "driver do Playwright" in g.verificar()
    assert g.verificar() is None and feito["driver"] == 1
    rel.t = 1201
    g.verificar()
    assert feito["sair"] == [3]


def test_guarda_linha_para(tmp_path):
    g, _, _ = _guarda(tmp_path, passo=0.01)
    g.comecar()
    g.parar()
    g._linha.join(2)
    assert not g._linha.is_alive()


# ------------------------------------------------------- sinal de vida

def test_gravar_vivo(tmp_path):
    agora = dt.datetime(2026, 11, 9, 14, 0, tzinfo=dt.timezone.utc)
    porteiro.gravar_vivo(tmp_path, ["principal: ok"], agora=agora)
    d = json.loads((tmp_path / "porteiro-vivo.json").read_text(encoding="utf-8"))
    assert d["ok"] is True and d["em"].startswith("2026-11-09T14:00")
    porteiro.gravar_vivo(tmp_path, ["principal: CHROME TRAVADO — x"], agora=agora)
    assert json.loads((tmp_path / "porteiro-vivo.json").read_text(encoding="utf-8"))["ok"] is False


def test_vigiar_grava_o_sinal_de_vida(tmp_path, monkeypatch):
    class Cli:
        _minhas = []

        def vivo(self):
            return True

        def esta_logado(self):
            return True

        def pulsar(self):
            pass
    m = porteiro.Mantenedor(lambda a: Cli(), lambda c: None)
    monkeypatch.setattr(porteiro, "_mantenedor_real", lambda log: m)
    monkeypatch.setattr(central, "chrome_vivo", lambda a, **k: True)

    class Saida:
        def register(self, f): pass
        def unregister(self, f): pass
    monkeypatch.setattr(porteiro, "atexit", Saida())
    porteiro.vigiar({"principal": _a(tmp_path)}, tmp_path, ciclos=1)
    d = json.loads((tmp_path / "porteiro-vivo.json").read_text(encoding="utf-8"))
    assert d["ok"] is True and d["linhas"] == ["principal: ok"]


# ------------------------------------------------------- o vigia de fora

_AGORA = dt.datetime(2026, 11, 9, 14, 30, tzinfo=dt.timezone(dt.timedelta(hours=-3)))


def _vivo(tmp_path, minutos_atras, ok=True, pid=500, linhas=None):
    em = (_AGORA - dt.timedelta(minutes=minutos_atras)).isoformat()
    (tmp_path / "porteiro-vivo.json").write_text(json.dumps(
        {"em": em, "pid": pid, "ok": ok,
         "linhas": linhas or ["principal: ok" if ok else "principal: CHROME TRAVADO — x"]}),
        encoding="utf-8")


def _passada(tmp_path, minutos=0, pids=(500,), avisar_ok=True):
    feito = {"mortos": [], "iniciou": 0, "emails": []}

    def iniciar():
        feito["iniciou"] += 1
        return "tarefa iniciada"

    def avisar(assunto, texto):
        feito["emails"].append(assunto)
        return avisar_ok
    r = vigia.passada(tmp_path, agora=_AGORA + dt.timedelta(minutes=minutos),
                      pids=lambda: list(pids), matar_pid=feito["mortos"].append,
                      iniciar=iniciar, avisar=avisar, log=lambda *_: None)
    return r, feito


def test_vigia_ok(tmp_path):
    _vivo(tmp_path, 1)
    r, f = _passada(tmp_path)
    assert r.startswith("porteiro ok") and f == {"mortos": [], "iniciou": 0, "emails": []}


def test_vigia_sobe_o_porteiro_que_nao_roda(tmp_path):
    _vivo(tmp_path, 1)
    r, f = _passada(tmp_path, pids=())
    assert f["iniciou"] == 1 and "FORA" in r


def test_vigia_mata_o_porteiro_preso_e_sobe_de_novo(tmp_path):
    _vivo(tmp_path, 26, pid=500)
    _, f = _passada(tmp_path, pids=(500,))
    assert f["mortos"] == [500] and f["iniciou"] == 1


def test_vigia_nao_mata_porteiro_novo_com_arquivo_velho(tmp_path):
    _vivo(tmp_path, 26, pid=500)                    # o arquivo é do processo anterior
    _, f = _passada(tmp_path, pids=(777,))
    assert f["mortos"] == [] and f["iniciou"] == 0


def test_vigia_avisa_uma_vez_depois_de_10_min_e_avisa_a_volta(tmp_path):
    _vivo(tmp_path, 0, ok=False)
    _, f = _passada(tmp_path, minutos=0)
    assert f["emails"] == []                        # pode resolver sozinho
    _vivo(tmp_path, 0, ok=False)
    _, f = _passada(tmp_path, minutos=10)
    assert f["emails"] == ["PORTEIRO FORA — robôs do Mais Controle parados"]
    _, f = _passada(tmp_path, minutos=15)
    assert f["emails"] == []                        # um e-mail só
    _vivo(tmp_path, -20)                            # ciclo ok, depois
    r, f = _passada(tmp_path, minutos=20)
    assert f["emails"] == ["PORTEIRO VOLTOU — Mais Controle"] and r.startswith("porteiro ok")
    _vivo(tmp_path, -25)
    _, f = _passada(tmp_path, minutos=25)
    assert f["emails"] == []


def test_vigia_email_que_falha_tenta_de_novo(tmp_path):
    _vivo(tmp_path, 0, ok=False)
    _passada(tmp_path, minutos=0)
    _, f = _passada(tmp_path, minutos=11, avisar_ok=False)
    assert len(f["emails"]) == 1
    _, f = _passada(tmp_path, minutos=16)
    assert len(f["emails"]) == 1


def test_texto_fora_diz_o_que_fazer_no_sem_login():
    t = vigia.texto_fora(12, "principal: SEM LOGIN — entre", [], [], _AGORA)
    assert "Entre na janela do Chrome central" in t
