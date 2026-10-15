# -*- coding: utf-8 -*-
"""O Chrome central: quem lê o acessos.json e quem sobe o Chrome UMA vez.

Nada aqui abre navegador nem toca rede: `Popen` e `urlopen` são dublês."""
import json
import os
import threading
import time

import pytest

from erp import central


def _escrever(pasta, acessos):
    (pasta / "acessos.json").write_text(
        json.dumps({"acessos": acessos}), encoding="utf-8")


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_CENTRAL", str(tmp_path))
    return tmp_path


def test_sem_arquivo_fica_desligado(pasta):
    assert central.carregar_acessos() == {}
    assert central.ligado() is False


def test_mc_central_off_desliga_mesmo_com_arquivo(pasta, monkeypatch):
    _escrever(pasta, [{"nome": "principal", "perfil": str(pasta / "p"), "porta": 9230}])
    monkeypatch.setenv("MC_CENTRAL", "off")
    assert central.pasta_central() is None
    assert central.ligado() is False


def test_le_os_acessos(pasta):
    _escrever(pasta, [
        {"nome": "principal", "perfil": str(pasta / "p1"), "porta": 9230,
         "credencial": str(pasta / "principal.login.dat")},
        {"nome": "robo2", "perfil": "perfis/robo2", "porta": 9231},
    ])
    acessos = central.carregar_acessos()
    assert set(acessos) == {"principal", "robo2"}
    assert acessos["principal"].porta == 9230
    assert acessos["principal"].credencial.name == "principal.login.dat"
    # caminho relativo é relativo à pasta central
    assert acessos["robo2"].perfil == pasta / "perfis" / "robo2"
    assert acessos["robo2"].credencial is None
    assert central.ligado("principal") and not central.ligado("outro")


@pytest.mark.parametrize("acessos, trecho", [
    ([{"nome": "a", "perfil": "x", "porta": 9230},
      {"nome": "b", "perfil": "y", "porta": 9230}], "porta 9230 repetida"),
    ([{"nome": "a", "perfil": "x", "porta": 80}], "porta 80"),
    ([{"nome": "a", "perfil": "x"}], "porta"),
    ([{"nome": "a", "perfil": "x", "porta": 9230},
      {"nome": "a", "perfil": "y", "porta": 9231}], "nome 'a' repetido"),
])
def test_recusa_acessos_invalidos(pasta, acessos, trecho):
    _escrever(pasta, acessos)
    with pytest.raises(ValueError, match=trecho):
        central.carregar_acessos()


def test_json_quebrado_vira_valueerror_com_o_caminho(pasta):
    (pasta / "acessos.json").write_text("{nao é json", encoding="utf-8")
    with pytest.raises(ValueError, match="acessos.json"):
        central.carregar_acessos()


def test_endereco_e_so_local():
    a = central.Acesso("principal", central.PASTA_PADRAO / "p", 9230)
    assert central.endereco(a) == "http://127.0.0.1:9230"


def test_argumentos_do_chrome(tmp_path):
    a = central.Acesso("principal", tmp_path / "perfil", 9230)
    args = central.argumentos_chrome("C:/chrome.exe", a)
    assert args[0] == "C:/chrome.exe"
    assert "--remote-debugging-port=9230" in args
    assert "--remote-debugging-address=127.0.0.1" in args
    assert f"--user-data-dir={tmp_path / 'perfil'}" in args
    assert "--lang=pt-BR" in args
    assert not any("0.0.0.0" in x for x in args)


def test_chrome_vivo_le_json_version(tmp_path):
    a = central.Acesso("principal", tmp_path, 9230)
    pedidos = []

    class _Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *e): return False
        def read(self): return b'{"Browser": "Chrome/141"}'

    def abrir(url, timeout):
        pedidos.append(url)
        return _Resp()

    assert central.chrome_vivo(a, abrir=abrir) is True
    assert pedidos == ["http://127.0.0.1:9230/json/version"]

    def recusa(url, timeout):
        raise OSError("conexão recusada")
    assert central.chrome_vivo(a, abrir=recusa) is False


def test_garantir_chrome_nao_sobe_se_ja_vivo(tmp_path):
    a = central.Acesso("principal", tmp_path / "p", 9230)
    chamadas = []
    end = central.garantir_chrome(a, popen=lambda *x, **k: chamadas.append(x),
                                  vivo=lambda _a: True, exe="C:/chrome.exe")
    assert end == "http://127.0.0.1:9230"
    assert chamadas == []


def test_garantir_chrome_sobe_e_espera_a_porta(tmp_path):
    a = central.Acesso("principal", tmp_path / "p", 9230)
    estado = {"vivo": False, "subidas": 0}

    def popen(args, **kw):
        estado["subidas"] += 1
        estado["vivo"] = True
        assert kw.get("creationflags")   # destacado: sobrevive ao robô
    end = central.garantir_chrome(a, popen=popen, vivo=lambda _a: estado["vivo"],
                                  exe="C:/chrome.exe", dormir=lambda s: None)
    assert end == "http://127.0.0.1:9230"
    assert estado["subidas"] == 1
    assert (tmp_path / "p").is_dir()


def test_garantir_chrome_desiste_com_recado(tmp_path):
    a = central.Acesso("principal", tmp_path / "p", 9230)
    relogio = iter(range(0, 1000))
    with pytest.raises(TimeoutError, match="9230"):
        central.garantir_chrome(a, popen=lambda *x, **k: None,
                                vivo=lambda _a: False, exe="C:/chrome.exe",
                                esperar=3, dormir=lambda s: next(relogio))


def test_garantir_chrome_usa_o_chrome_vivo_do_modulo(tmp_path, monkeypatch):
    """Monkeypatch no módulo tem de valer: nada capturado em default."""
    a = central.Acesso("principal", tmp_path / "p", 9230)
    monkeypatch.setattr(central, "chrome_vivo", lambda _a: True)
    monkeypatch.setattr(central, "endereco", lambda _a: "http://dublê")
    assert central.garantir_chrome(a, popen=lambda *x, **k: 1 / 0) == "http://dublê"


def test_dois_robos_ao_mesmo_tempo_sobem_um_chrome_so(tmp_path):
    a = central.Acesso("principal", tmp_path / "p", 9230)
    estado = {"vivo": False, "subidas": 0}
    trava_de_teste = threading.Lock()

    def popen(args, **kw):
        with trava_de_teste:
            estado["subidas"] += 1
        time.sleep(0.2)              # o Chrome demora a abrir a porta
        estado["vivo"] = True

    erros = []
    def robo():
        try:
            central.garantir_chrome(a, popen=popen, vivo=lambda _a: estado["vivo"],
                                    exe="C:/chrome.exe", dormir=time.sleep)
        except Exception as e:      # pragma: no cover - aparece no assert
            erros.append(e)
    t = [threading.Thread(target=robo) for _ in range(2)]
    for x in t: x.start()
    for x in t: x.join(10)
    assert erros == []
    assert estado["subidas"] == 1


def test_trava_velha_e_recuperada(tmp_path):
    caminho = tmp_path / ".principal.trava"
    caminho.write_text("pid morto")
    antigo = time.time() - 600
    os.utime(caminho, (antigo, antigo))
    with central.trava(caminho, espera=1, velha=120):
        assert caminho.exists()
    assert not caminho.exists()


def test_trava_ocupada_estoura_com_recado(tmp_path):
    caminho = tmp_path / ".principal.trava"
    caminho.write_text("outro")
    with pytest.raises(TimeoutError, match="trava"):
        with central.trava(caminho, espera=0.3, velha=120):
            pass


# ---------------------------------------------------------------- AbaCentral

class _Pagina:
    def __init__(self, registro):
        self.registro, self.fechada = registro, False

    def close(self):
        self.fechada = True
        self.registro.append("page.close")

    def is_closed(self):
        return self.fechada


class _Ctx:
    def __init__(self, registro):
        self.registro, self.pages = registro, [_Pagina(registro)]  # aba de outro robô

    def new_page(self):
        p = _Pagina(self.registro)
        self.pages.append(p)
        return p

    def close(self):
        self.registro.append("ctx.close")


class _Browser:
    def __init__(self, registro):
        self.registro, self.contexts = registro, [_Ctx(registro)]

    def close(self):
        self.registro.append("browser.close")


class _PW:
    def __init__(self, registro):
        self.registro = registro
        outer = self

        class _Chromium:
            def connect_over_cdp(self, endereco):
                outer.registro.append(f"cdp {endereco}")
                return _Browser(outer.registro)
        self.chromium = _Chromium()

    def stop(self):
        self.registro.append("pw.stop")


def test_aba_central_fecha_so_as_proprias_e_nunca_o_chrome(tmp_path):
    reg = []
    a = central.Acesso("principal", tmp_path / "p", 9230)
    with central.AbaCentral(a, pw=_PW(reg), garantir=lambda _a: "http://127.0.0.1:9230") as aba:
        alheia = aba.ctx.pages[0]
        extra = aba.nova_aba()
        assert aba.page is not alheia and extra is not alheia
    assert "cdp http://127.0.0.1:9230" in reg
    assert "ctx.close" not in reg and "browser.close" not in reg
    assert alheia.fechada is False
    assert aba.page.fechada and extra.fechada
    assert reg[-1] == "pw.stop"


def test_aba_central_fecha_mesmo_com_erro_no_meio(tmp_path):
    reg = []
    a = central.Acesso("principal", tmp_path / "p", 9230)
    with pytest.raises(RuntimeError):
        with central.AbaCentral(a, pw=_PW(reg), garantir=lambda _a: "http://127.0.0.1:9230"):
            raise RuntimeError("robô caiu")
    assert reg.count("page.close") == 1 and "browser.close" not in reg


def test_trava_espera_quando_o_windows_devolve_permissionerror(tmp_path, monkeypatch):
    """Arquivo em delete-pending: O_EXCL levanta PermissionError, não
    FileExistsError. A trava espera e tenta de novo em vez de derrubar o robô."""
    caminho = tmp_path / ".principal.trava"
    real = os.open
    falhas = []

    def open_dublê(path, *a, **k):
        if len(falhas) < 2:
            falhas.append(path)
            raise PermissionError("delete pending")
        return real(path, *a, **k)

    monkeypatch.setattr(central.os, "open", open_dublê)
    with central.trava(caminho, espera=5, velha=120):
        assert caminho.exists()
    assert len(falhas) == 2
    assert not caminho.exists()


def test_trava_nao_gira_sem_fim_se_o_stat_falha(tmp_path, monkeypatch):
    """stat com PermissionError (antivírus) não pode ignorar `espera`."""
    caminho = tmp_path / ".principal.trava"
    caminho.write_text("outro")
    stat_real = type(caminho).stat

    def stat_dublê(self, *a, **k):
        if self.name == caminho.name:
            raise PermissionError("antivírus")
        return stat_real(self, *a, **k)

    monkeypatch.setattr(type(caminho), "stat", stat_dublê)
    inicio = time.monotonic()
    with pytest.raises(TimeoutError, match="trava"):
        with central.trava(caminho, espera=0.3, velha=120):
            pass
    assert time.monotonic() - inicio < 3


def test_trava_nao_gira_se_nao_consegue_criar_por_permissao(tmp_path, monkeypatch):
    """os.open sempre com PermissionError e o arquivo não existe (stat dá
    FileNotFoundError): estoura o prazo com recado, sem laço a toda velocidade."""
    caminho = tmp_path / ".principal.trava"

    def open_negado(path, *a, **k):
        raise PermissionError("sem permissão")

    monkeypatch.setattr(central.os, "open", open_negado)
    inicio = time.monotonic()
    with pytest.raises(TimeoutError, match="criar a trava") as exc:
        with central.trava(caminho, espera=0.3, velha=120):
            pass
    assert str(caminho) in str(exc.value)
    assert time.monotonic() - inicio < 3


def test_trava_roubada_nao_e_apagada_pelo_dono_antigo(tmp_path):
    """Quem segurou a trava além de `velha` pode tê-la perdido para outro
    processo. Ao sair, ele não apaga a trava que agora é do outro."""
    caminho = tmp_path / ".principal.trava"
    with central.trava(caminho, espera=1, velha=120):
        caminho.unlink()
        caminho.write_text("123 token-do-outro")
    assert caminho.read_text() == "123 token-do-outro"


def test_trava_grava_pid_e_token_unico(tmp_path):
    caminho = tmp_path / ".principal.trava"
    with central.trava(caminho, espera=1, velha=120):
        primeiro = caminho.read_text()
    with central.trava(caminho, espera=1, velha=120):
        segundo = caminho.read_text()
    assert primeiro.split()[0] == str(os.getpid())
    assert primeiro != segundo
    assert not caminho.exists()


# --------------------------------------------------- acessos.json à mão

def test_acessos_com_bom_do_bloco_de_notas(pasta):
    # O Bloco de Notas grava BOM; o arquivo do servidor é criado à mão.
    texto = json.dumps({"acessos": [{"nome": "principal", "perfil": "p",
                                     "porta": 9230}]})
    (pasta / "acessos.json").write_bytes(b"\xef\xbb\xbf" + texto.encode("utf-8"))
    assert set(central.carregar_acessos()) == {"principal"}


@pytest.mark.parametrize("conteudo, trecho", [
    ([1, 2], "objeto"),
    ("texto", "objeto"),
    ({"acessos": {"nome": "a"}}, "lista"),
    ({"acessos": "a"}, "lista"),
    ({"acessos": ["a"]}, "objeto"),
    ({"acessos": [None]}, "objeto"),
    ({"acessos": [{"nome": "a", "perfil": "x", "porta": 9230}, 7]}, "objeto"),
])
def test_formato_errado_vira_valueerror_com_o_caminho(pasta, conteudo, trecho):
    (pasta / "acessos.json").write_text(json.dumps(conteudo), encoding="utf-8")
    with pytest.raises(ValueError, match=trecho) as e:
        central.carregar_acessos()
    assert "acessos.json" in str(e.value)


# ------------------------------------- histórico de downloads ao subir

def _perfil_com_historico(tmp_path):
    padrao = tmp_path / "p" / "Default"
    padrao.mkdir(parents=True)
    for nome in ("History", "History-journal", "Preferences"):
        (padrao / nome).write_text("x", encoding="utf-8")
    return padrao


def test_garantir_chrome_apaga_o_historico_antes_de_subir(tmp_path):
    # Chrome 152 cai no 1º download de perfil que já baixou: TODO perfil que
    # sobe passa pela limpeza, suba quem subir (robô ou porteiro).
    padrao = _perfil_com_historico(tmp_path)
    a = central.Acesso("principal", tmp_path / "p", 9230)
    visto = {}
    estado = {"vivo": False}

    def popen(args, **kw):
        visto["history"] = (padrao / "History").exists()
        visto["journal"] = (padrao / "History-journal").exists()
        estado["vivo"] = True
    central.garantir_chrome(a, popen=popen, vivo=lambda _a: estado["vivo"],
                            exe="C:/chrome.exe", dormir=lambda s: None)
    assert visto == {"history": False, "journal": False}
    assert (padrao / "Preferences").exists()       # só o histórico


def test_garantir_chrome_com_chrome_vivo_nao_mexe_no_historico(tmp_path):
    padrao = _perfil_com_historico(tmp_path)
    a = central.Acesso("principal", tmp_path / "p", 9230)
    central.garantir_chrome(a, popen=lambda *x, **k: None, vivo=lambda _a: True,
                            exe="C:/chrome.exe")
    assert (padrao / "History").exists() and (padrao / "History-journal").exists()


def test_garantir_chrome_nao_mexe_no_historico_se_outro_subiu_na_espera(tmp_path):
    # Vivo só na 2ª pergunta (dentro da trava): outro robô subiu enquanto
    # esperávamos, e o arquivo é dele.
    padrao = _perfil_com_historico(tmp_path)
    a = central.Acesso("principal", tmp_path / "p", 9230)
    respostas = iter([False, True])
    central.garantir_chrome(a, popen=lambda *x, **k: None,
                            vivo=lambda _a: next(respostas), exe="C:/chrome.exe")
    assert (padrao / "History").exists()


def test_garantir_chrome_sem_perfil_ainda_sobe(tmp_path):
    a = central.Acesso("principal", tmp_path / "novo", 9230)
    estado = {"vivo": False}

    def popen(args, **kw):
        estado["vivo"] = True
    central.garantir_chrome(a, popen=popen, vivo=lambda _a: estado["vivo"],
                            exe="C:/chrome.exe", dormir=lambda s: None)
    assert estado["vivo"]
