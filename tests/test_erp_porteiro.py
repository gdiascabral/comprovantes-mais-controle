# -*- coding: utf-8 -*-
import json

import pytest

from erp import central, porteiro


def _acessos(tmp_path):
    return {"principal": central.Acesso("principal", tmp_path / "p1", 9230),
            "robo2": central.Acesso("robo2", tmp_path / "p2", 9231)}


def test_estado_lista_cada_acesso(tmp_path):
    e = porteiro.montar_estado(_acessos(tmp_path), vivo=lambda a: a.nome == "principal")
    assert e == {"acessos": [
        {"nome": "principal", "porta": 9230, "chrome_vivo": True},
        {"nome": "robo2", "porta": 9231, "chrome_vivo": False}]}


def test_ciclo_sobe_o_fechado_e_reloga_o_deslogado(tmp_path):
    feitos = []
    r = porteiro.um_ciclo(
        _acessos(tmp_path),
        vivo=lambda a: a.nome == "principal",
        subir_chrome=lambda a: feitos.append(f"subiu {a.nome}"),
        checar_login=lambda a: feitos.append(f"login {a.nome}") or True,
        log=lambda *_: None)
    assert feitos == ["login principal", "subiu robo2", "login robo2"]
    assert r == ["principal: ok", "robo2: chrome subiu; ok"]


def test_erro_num_acesso_nao_para_os_outros(tmp_path):
    def checar(a):
        if a.nome == "principal":
            raise RuntimeError("tela travada")
        return True
    r = porteiro.um_ciclo(_acessos(tmp_path), vivo=lambda a: True,
                          subir_chrome=lambda a: None, checar_login=checar,
                          log=lambda *_: None)
    assert r[0].startswith("principal: ERRO") and r[1] == "robo2: ok"


def test_login_que_nao_entra_aparece_no_relatorio(tmp_path):
    r = porteiro.um_ciclo({"principal": _acessos(tmp_path)["principal"]},
                          vivo=lambda a: True, subir_chrome=lambda a: None,
                          checar_login=lambda a: False, log=lambda *_: None)
    assert r == ["principal: SEM LOGIN — entre na janela do Chrome central"]


def test_ciclo_loga_cada_linha(tmp_path):
    visto = []
    porteiro.um_ciclo({"principal": _acessos(tmp_path)["principal"]},
                      vivo=lambda a: True, subir_chrome=lambda a: None,
                      checar_login=lambda a: True, log=visto.append)
    assert visto == ["principal: ok"]


class _Cli:
    def __init__(self, vivo=True, logado=True):
        self._vivo, self._logado = vivo, logado
        self.saiu = False
        self.logou = 0

    def vivo(self):
        return self._vivo

    def esta_logado(self):
        return self._logado

    def garantir_login(self):
        self.logou += 1
        return True

    def sair(self):
        self.saiu = True

    def pulsar(self):
        self.pulsos = getattr(self, "pulsos", 0) + 1


def test_cliente_e_reaproveitado_e_recriado_se_morrer(tmp_path):
    a = _acessos(tmp_path)["principal"]
    criados = []

    def abrir(ac):
        c = _Cli()
        criados.append(c)
        return c
    m = porteiro.Mantenedor(abrir, lambda c: c.sair())
    assert m.checar(a) and m.checar(a)
    assert len(criados) == 1 and criados[0].logou == 0
    criados[0]._vivo = False
    assert m.checar(a)
    assert len(criados) == 2 and criados[0].saiu


def test_deslogado_chama_garantir_login(tmp_path):
    a = _acessos(tmp_path)["principal"]
    c = _Cli(logado=False)
    m = porteiro.Mantenedor(lambda ac: c, lambda x: x.sair())
    assert m.checar(a) is True and c.logou == 1


def test_guardar_login_recusa_acesso_sem_credencial(tmp_path):
    (tmp_path / "acessos.json").write_text(json.dumps(
        {"acessos": [{"nome": "principal", "porta": 9230}]}), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        porteiro.guardar_login(central.carregar_acessos(tmp_path)["principal"])
    assert e.value.code != 0


def test_guardar_login_grava_cifrado_sem_imprimir_senha(tmp_path, capsys):
    a = central.Acesso("principal", tmp_path / "p", 9230,
                       tmp_path / "pasta" / "principal.login.dat")
    porteiro.guardar_login(a, pedir_email=lambda *_: "fulano@exemplo.test",
                           pedir_senha=lambda *_: "segredo-xyz",
                           proteger=lambda b: b"ENC" + b)
    dados = a.credencial.read_bytes()
    assert dados.startswith(b"ENC")
    assert json.loads(dados[3:]) == {"email": "fulano@exemplo.test", "senha": "segredo-xyz"}
    saida = capsys.readouterr()
    assert "segredo-xyz" not in saida.out + saida.err


# ------------------------------------------- vigiar: sair fecha as abas

class _Saida:
    """Dublê do `atexit`: guarda o que o porteiro registrou."""

    def __init__(self):
        self.registradas, self.removidas = [], []

    def register(self, f):
        self.registradas.append(f)

    def unregister(self, f):
        self.removidas.append(f)


def _vigia_com_dubles(tmp_path, monkeypatch, checar=None):
    clientes = []

    def abrir(a):
        c = _Cli()
        clientes.append(c)
        return c
    m = porteiro.Mantenedor(abrir, lambda c: c.sair())
    if checar is not None:
        m.checar = checar(m)
    monkeypatch.setattr(porteiro, "_mantenedor_real", lambda log: m)
    monkeypatch.setattr(central, "chrome_vivo", lambda a: True)
    saida = _Saida()
    monkeypatch.setattr(porteiro, "atexit", saida)
    return m, clientes, saida


def test_vigiar_um_ciclo_fecha_tudo_e_registra_no_atexit(tmp_path, monkeypatch):
    m, clientes, saida = _vigia_com_dubles(tmp_path, monkeypatch)
    porteiro.vigiar(_acessos(tmp_path), tmp_path / "log", ciclos=1)
    assert len(clientes) == 2 and all(c.saiu for c in clientes)
    # atexit cobre a saída que não passa pelo finally (fim do interpretador)
    assert saida.registradas == [m.fechar_tudo]
    assert saida.removidas == [m.fechar_tudo]      # vigia que acabou limpa


def test_vigiar_trata_sigterm_e_cai_no_finally(tmp_path, monkeypatch):
    # Parada/reinício da tarefa agendada: SIGTERM (e SIGBREAK no Windows)
    # tem de virar a mesma saída do Ctrl+C, que fecha a aba do porteiro.
    import signal

    def checar_que_recebe_sinal(m):
        original = m.checar

        def checar(a):
            ok = original(a)
            tratador = signal.getsignal(signal.SIGTERM)
            assert callable(tratador)
            tratador(signal.SIGTERM, None)      # o sinal chega no meio do ciclo
            return ok
        return checar
    antes = signal.getsignal(signal.SIGTERM)
    m, clientes, _ = _vigia_com_dubles(tmp_path, monkeypatch,
                                       checar=checar_que_recebe_sinal)
    porteiro.vigiar(_acessos(tmp_path), tmp_path / "log", ciclos=5)
    assert clientes and all(c.saiu for c in clientes)
    assert signal.getsignal(signal.SIGTERM) is antes    # devolve o tratador


def test_tratador_de_sinal_so_levanta(tmp_path):
    # Roda na thread principal, que é a do Playwright: não toca no navegador.
    with pytest.raises(KeyboardInterrupt):
        porteiro._ao_sinal(15, None)


def test_sinais_de_parar_inclui_sigbreak_quando_existe(monkeypatch):
    import signal
    nomes = porteiro._sinais_de_parar()
    assert signal.SIGTERM in nomes
    if hasattr(signal, "SIGBREAK"):
        assert signal.SIGBREAK in nomes


def test_subir_chrome_delega_a_limpeza_ao_garantir_chrome(tmp_path, monkeypatch):
    # A limpeza do histórico mora em `garantir_chrome`, sob a trava e com o
    # Chrome confirmado fechado; o porteiro não a repete fora da trava.
    a = _acessos(tmp_path)["principal"]
    chamadas = []
    monkeypatch.setattr(central, "garantir_chrome", lambda ac: chamadas.append(ac))
    import util
    monkeypatch.setattr(util, "limpar_historico_de_downloads",
                        lambda p: pytest.fail("limpeza fora da trava"))
    porteiro._subir_chrome(a)
    assert chamadas == [a]


# ------------------------------- entre os ciclos: o porteiro não prende as abas
# Medido no servidor em 29/10/2026: com o porteiro em `time.sleep(120)`, a aba
# nova que OUTRO programa abria no Chrome central só pedia a página quando o
# porteiro acordava (pedido às 11:53:39.157, ciclo às 11:53:39,188) — o robô
# de bases desistia nos 20 s dele. O Playwright sync só trata eventos durante
# uma chamada; por isso o sono entre os ciclos é em passos, pulsando.

class _Relogio:
    def __init__(self):
        self.agora, self.sonos = 0.0, []

    def __call__(self):
        return self.agora

    def dormir(self, s):
        self.sonos.append(s)
        self.agora += s


def test_dormir_pulsa_ao_longo_do_intervalo_sem_sono_longo():
    r, pulsos = _Relogio(), []
    porteiro._dormir(120, lambda: pulsos.append(r.agora), relogio=r, dormir=r.dormir)
    assert 119.9 <= r.agora <= 120.0 + porteiro.PASSO_RESPIRO
    assert max(r.sonos) <= porteiro.PASSO_RESPIRO
    assert len(pulsos) >= 120 / porteiro.PASSO_RESPIRO - 1


def test_dormir_sobrevive_a_pulso_que_falha():
    r = _Relogio()

    def pulso():
        raise RuntimeError("navegador fechado")
    porteiro._dormir(5, pulso, relogio=r, dormir=r.dormir)
    assert r.agora >= 5


def test_respirar_pulsa_cada_cliente_aberto(tmp_path):
    clientes = []

    def abrir(a):
        c = _Cli()
        clientes.append(c)
        return c
    m = porteiro.Mantenedor(abrir, lambda c: c.sair())
    m.respirar()                                   # sem cliente: nada a fazer
    for a in _acessos(tmp_path).values():
        m.checar(a)
    m.respirar()
    assert [c.pulsos for c in clientes] == [1, 1]


def test_vigiar_dorme_respirando_entre_os_ciclos(tmp_path, monkeypatch):
    m, _, _ = _vigia_com_dubles(tmp_path, monkeypatch)
    sonos = []
    monkeypatch.setattr(porteiro, "_dormir",
                        lambda s, respirar: sonos.append((s, respirar)))
    monkeypatch.setattr(porteiro.time, "sleep",
                        lambda s: pytest.fail("sono que prende as abas novas"))
    porteiro.vigiar(_acessos(tmp_path), tmp_path / "log", intervalo=120, ciclos=3)
    assert sonos == [(120, m.respirar)] * 2
