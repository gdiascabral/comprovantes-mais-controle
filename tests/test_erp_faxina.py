# -*- coding: utf-8 -*-
"""A faxina das abas esquecidas no Chrome central (erp/faxina.py)."""
import json

from erp import central, faxina, porteiro

LOGADA = "https://acessar.maiscontroleerp.com.br/#/payable-installments"
LOGIN = "https://acessar.maiscontroleerp.com.br/#/login"


class Chrome:
    """Dublê do /json/list + /json/close."""

    def __init__(self, abas):
        self.abas = dict(abas)          # id -> url
        self.fechadas = []

    def listar(self, a):
        return [{"type": "page", "id": i, "url": u} for i, u in self.abas.items()]

    def fechar(self, a, alvo):
        self.fechadas.append(alvo)
        self.abas.pop(alvo, None)


class Relogio:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _acesso(tmp_path):
    return central.Acesso("principal", tmp_path / "perfis" / "principal", 9230)


def _fx(chrome, tmp_path, rel, pid_vivo=lambda pid: True):
    return faxina.Faxina(listar=chrome.listar, fechar=chrome.fechar, pid_vivo=pid_vivo,
                         pasta_reg=tmp_path / "abas-robos", relogio=rel, limite=900)


def test_aba_em_branco_so_fecha_depois_do_limite(tmp_path):
    ch, rel = Chrome({"P": LOGADA, "B": "about:blank"}), Relogio()
    fx, a = _fx(ch, tmp_path, rel), _acesso(tmp_path)
    assert fx.passar(a, minhas={"P"}, logado=True) == []
    rel.t += 899
    assert fx.passar(a, minhas={"P"}, logado=True) == []
    rel.t += 2
    r = fx.passar(a, minhas={"P"}, logado=True)
    assert ch.fechadas == ["B"] and len(r) == 1 and "branco" in r[0]


def test_nunca_fecha_a_do_porteiro_nem_aba_com_trabalho(tmp_path):
    ch, rel = Chrome({"P": "about:blank", "T": LOGADA}), Relogio()
    fx, a = _fx(ch, tmp_path, rel), _acesso(tmp_path)
    fx.passar(a, minhas={"P"}, logado=True)
    rel.t += 10_000
    fx.passar(a, minhas={"P"}, logado=True)
    assert ch.fechadas == []


def test_aba_no_login_so_fecha_com_a_sessao_boa(tmp_path):
    """Sessão fora: a aba no login pode ser o dono entrando."""
    ch, rel = Chrome({"L": LOGIN}), Relogio()
    fx, a = _fx(ch, tmp_path, rel), _acesso(tmp_path)
    fx.passar(a, logado=False)
    rel.t += 10_000
    assert fx.passar(a, logado=False) == [] and ch.fechadas == []
    fx.passar(a, logado=True)            # começa a contar com a sessão boa
    rel.t += 901
    fx.passar(a, logado=True)
    assert ch.fechadas == ["L"]


def test_aba_que_mudou_de_endereco_recomeca_a_conta(tmp_path):
    ch, rel = Chrome({"B": "about:blank"}), Relogio()
    fx, a = _fx(ch, tmp_path, rel), _acesso(tmp_path)
    fx.passar(a, logado=True)
    rel.t += 600
    ch.abas["B"] = LOGIN                 # robô vivo andando
    fx.passar(a, logado=True)
    rel.t += 600
    assert fx.passar(a, logado=True) == []
    rel.t += 301
    fx.passar(a, logado=True)
    assert ch.fechadas == ["B"]


def test_poupa_a_aba_do_login_principal(tmp_path):
    a = _acesso(tmp_path)
    a.perfil.parent.mkdir(parents=True)
    (a.perfil.parent / ".principal.login.aba").write_text("LP\n", encoding="utf-8")
    ch, rel = Chrome({"LP": "about:blank"}), Relogio()
    fx = _fx(ch, tmp_path, rel)
    fx.passar(a, logado=True)
    rel.t += 10_000
    fx.passar(a, logado=True)
    assert ch.fechadas == []


def test_aba_registrada_de_robo_morto_fecha_na_hora(tmp_path):
    a = _acesso(tmp_path)
    arq = faxina.registrar("R", 9230, pasta=tmp_path, pid=4242)
    vivo = faxina.registrar("V", 9230, pasta=tmp_path, pid=777)
    ch = Chrome({"R": LOGADA, "V": "about:blank"})
    rel = Relogio()
    fx = _fx(ch, tmp_path, rel, pid_vivo=lambda pid: pid == 777)
    r = fx.passar(a, logado=True)
    assert ch.fechadas == ["R"] and "4242" in r[0]
    assert not arq.exists() and vivo.exists()
    rel.t += 10_000                     # registrada e viva: a regra 2 não toca
    fx.passar(a, logado=True)
    assert ch.fechadas == ["R"]


def test_registro_de_outra_porta_fica(tmp_path):
    a = _acesso(tmp_path)
    arq = faxina.registrar("R", 9231, pasta=tmp_path, pid=4242)
    ch = Chrome({"R": LOGADA})
    _fx(ch, tmp_path, Relogio(), pid_vivo=lambda pid: False).passar(a, logado=True)
    assert ch.fechadas == [] and arq.exists()


def test_registrar_e_desregistrar(tmp_path):
    arq = faxina.registrar("ABC", 9230, pasta=tmp_path, pid=1)
    assert json.loads(arq.read_text(encoding="utf-8")) == {"pid": 1, "aba": "ABC", "porta": 9230}
    faxina.desregistrar(arq)
    assert not arq.exists()
    faxina.desregistrar(arq)            # duas vezes não quebra


def test_ciclo_chama_a_faxina_com_o_estado_do_login(tmp_path):
    a = _acesso(tmp_path)
    vistos, linhas = [], []
    porteiro.um_ciclo({"principal": a}, vivo=lambda a: True, subir_chrome=lambda a: None,
                      checar_login=lambda a: True, log=linhas.append,
                      faxinar=lambda a, logado: vistos.append(logado) or ["aba X"])
    assert vistos == [True]
    assert linhas == ["principal: ok", "principal: faxina — aba X"]


def test_faxina_que_quebra_nao_muda_o_ciclo(tmp_path):
    a = _acesso(tmp_path)
    linhas = []

    def ruim(a, logado):
        raise OSError("porta fechada")
    r = porteiro.um_ciclo({"principal": a}, vivo=lambda a: True, subir_chrome=lambda a: None,
                          checar_login=lambda a: False, log=linhas.append, faxinar=ruim)
    assert r[0].startswith("principal: SEM LOGIN")
    assert "faxina não rodou" in linhas[-1]
