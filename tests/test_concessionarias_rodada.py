# -*- coding: utf-8 -*-
"""A rodada do água e energia disparada pelo app: comando, andamento e resumo."""
import os
from pathlib import Path

import pytest

from concessionarias import rodada as R


def _instalar(raiz: Path) -> Path:
    (raiz / "coletor" / "logs").mkdir(parents=True)
    (raiz / "relatorios").mkdir()
    return raiz


def test_pasta_pela_variavel_e_desligada(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_AGUA_ENERGIA", "off")
    assert R.pasta_agua_energia() is None
    monkeypatch.setenv("MC_AGUA_ENERGIA", str(tmp_path))
    assert R.pasta_agua_energia() is None            # sem o .bat não é instalação
    _instalar(tmp_path)
    (tmp_path / "coletor" / "rodada_diaria.bat").write_text("@echo off\n")
    assert R.pasta_agua_energia() == tmp_path


@pytest.mark.parametrize("nome, esperado", [
    ("Fulano", "app: Fulano"),
    ("Fulâno de Tál", "app: Fulano de Tal"),
    ('Fu"la&no|%PATH%^!<x>', "app: FulanoPATHx"),
    ("", "app: sem nome"),
])
def test_origem_segura(nome, esperado):
    assert R.origem_segura(nome) == esperado


def test_linha_de_comando():
    linha = R.linha_de_comando(so=None, origem="app: Fulano")
    cmd = R.caminho_do_cmd()
    assert linha == (f'"{cmd}" /d /s /c ".\\rodada_diaria.bat --forcar --esperar 0 '
                     '--origem "app: Fulano""')
    assert R.linha_de_comando(so="equatorial", origem="app: Fulano").endswith(
        '--origem "app: Fulano" --so equatorial"')
    with pytest.raises(ValueError):
        R.linha_de_comando(so="sanesc; del", origem="app: Fulano")


@pytest.mark.parametrize("origem", ['app: Fu"la', "app: %X%", "app: Fu&la",
                                    "Fulano", "app: ", "app: a\nb", "app: a|b"])
def test_linha_de_comando_recusa_origem_fora_do_formato(origem):
    with pytest.raises(ValueError):
        R.linha_de_comando(so=None, origem=origem)


def test_cmd_pelo_caminho_completo(monkeypatch):
    monkeypatch.setenv("COMSPEC", "C:\\Teste\\cmd.exe")
    assert R.caminho_do_cmd() == "C:\\Teste\\cmd.exe"
    assert R.linha_de_comando(so=None, origem="app: Fulano").startswith(
        '"C:\\Teste\\cmd.exe" /d /s /c ')
    monkeypatch.delenv("COMSPEC")
    monkeypatch.setenv("SystemRoot", "C:\\Win")
    assert R.caminho_do_cmd() == os.path.join("C:\\Win", "System32", "cmd.exe")


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe só existe no Windows")
def test_comando_roda_um_bat_de_verdade_em_pasta_com_acento(tmp_path):
    """O caminho de produção tem acento e espaço; o nome de quem disparou passa
    por `origem_segura`. Um .bat dublê grava os argumentos que recebeu."""
    raiz = _instalar(tmp_path / "AUTOMAÇÕES TESTE" / "agua_energia")
    (raiz / "coletor" / "rodada_diaria.bat").write_text(
        "@echo off\r\n"
        'cd /d "%~dp0"\r\n'
        'if defined RODADA_LOG (set "L=%RODADA_LOG%") else (set "L=logs\\rodada_agendada.log")\r\n'
        'echo args=[%*]>> "%L%"\r\n'
        "exit /b 3\r\n", encoding="ascii")
    escolhido = R.novo_log(raiz)
    proc = R.iniciar(raiz, so="equatorial", origem=R.origem_segura('Fu"la & no'),
                     log=escolhido)
    assert proc.wait(30) == 3
    assert not (raiz / "coletor" / "logs" / "rodada_agendada.log").exists()
    log = escolhido.read_text(encoding="ascii")
    assert 'args=[--forcar --esperar 0 --origem "app: Fula  no" --so equatorial]' in log


def test_leitor_so_le_o_que_chegou_depois_e_guarda_a_linha_pela_metade(tmp_path):
    log = tmp_path / "rodada_agendada.log"
    log.write_text("de ontem\n", encoding="utf-8")
    leitor = R.Leitor(log)
    assert leitor.novas() == []
    with open(log, "a", encoding="utf-8") as f:
        f.write("=== RODADA 14/10/2026 10:00 ===\n[2/4] Equat")
    assert leitor.novas() == ["=== RODADA 14/10/2026 10:00 ==="]
    with open(log, "a", encoding="utf-8") as f:
        f.write("orial:\n")
    assert leitor.novas() == ["[2/4] Equatorial:"]


def test_leitor_com_log_que_ainda_nao_existe(tmp_path):
    log = tmp_path / "logs" / "rodada_agendada.log"
    leitor = R.Leitor(log)
    assert leitor.novas() == []
    log.parent.mkdir()
    log.write_text("primeira\n", encoding="utf-8")
    assert leitor.novas() == ["primeira"]


def test_resumo_do_log_pega_o_ultimo():
    linhas = ["resumo salvo em C:\\x\\rodada_1.txt", "e-mail: enviado",
              "resumo salvo em C:\\x\\rodada_2.txt"]
    assert R.resumo_do_log(linhas) == Path("C:\\x\\rodada_2.txt")
    assert R.resumo_do_log(["RODADA NÃO INICIADA: outra"]) is None


@pytest.mark.skipif(os.name != "nt", reason="trava do Windows")
def test_em_andamento_le_a_trava_de_verdade(tmp_path):
    import msvcrt
    raiz = _instalar(tmp_path)
    assert R.em_andamento(raiz) is None              # nunca rodou
    trava = raiz / "relatorios" / R.NOME_TRAVA
    with open(trava, "a+b") as f:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        (raiz / "relatorios" / R.NOME_INFO).write_text(
            '{"origem": "agendada", "inicio": "2026-10-14T05:30:00", "pid": 9}',
            encoding="utf-8")
        assert R.em_andamento(raiz)["origem"] == "agendada"
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    assert R.em_andamento(raiz) is None              # info velho, trava solta


@pytest.mark.skipif(os.name != "nt", reason="trava do Windows")
def test_em_andamento_trancada_sem_json_da_vazio(tmp_path):
    import msvcrt
    raiz = _instalar(tmp_path)
    with open(raiz / "relatorios" / R.NOME_TRAVA, "a+b") as f:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        assert R.em_andamento(raiz) == {}
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def test_em_andamento_nao_consegue_abrir_a_trava_nao_diz_livre(tmp_path, monkeypatch):
    raiz = _instalar(tmp_path)
    (raiz / "relatorios" / R.NOME_TRAVA).write_bytes(b"")

    def nega(_):
        raise PermissionError(13, "negado")
    monkeypatch.setattr(R, "_abrir_trava", nega)
    assert R.em_andamento(raiz) == {"ilegivel": True}


@pytest.mark.skipif(os.name != "nt", reason="msvcrt")
def test_em_andamento_errno_inesperado_no_locking_da_vazio(tmp_path, monkeypatch):
    import msvcrt
    raiz = _instalar(tmp_path)
    (raiz / "relatorios" / R.NOME_TRAVA).write_bytes(b"")

    def quebra(*a):
        raise OSError(5, "erro de E/S")
    monkeypatch.setattr(msvcrt, "locking", quebra)
    assert R.em_andamento(raiz) == {"ilegivel": True}


def test_leitor_recomeca_quando_o_log_encolhe(tmp_path):
    log = tmp_path / "rodada_agendada.log"
    log.write_text("antiga um\nantiga dois\n", encoding="utf-8")
    leitor = R.Leitor(log)
    with open(log, "a", encoding="utf-8") as f:
        f.write("nova\nmeia")
    assert leitor.novas() == ["nova"]
    log.write_text("zero\nlinha", encoding="utf-8")     # menor que a posição
    assert leitor.novas() == ["zero"]                   # "meia" velho descartado
    with open(log, "a", encoding="utf-8") as f:
        f.write(" completa\n")
    assert leitor.novas() == ["linha completa"]


def test_leitor_letra_partida_entre_duas_escritas_sai_inteira(tmp_path):
    log = tmp_path / "rodada_agendada.log"
    log.write_bytes(b"")
    leitor = R.Leitor(log)
    dados = "ação feita\n".encode("utf-8")           # "ç" ocupa dois bytes
    corte = dados.index("ç".encode("utf-8")) + 1     # no meio dela
    with open(log, "ab") as f:
        f.write(dados[:corte])
    assert leitor.novas() == []
    with open(log, "ab") as f:
        f.write(dados[corte:])
    assert leitor.novas() == ["ação feita"]


def test_leitor_linhas_crlf_saem_sem_cr(tmp_path):
    log = tmp_path / "rodada_agendada.log"
    log.write_bytes(b"")
    leitor = R.Leitor(log)
    with open(log, "ab") as f:
        f.write(b"um\r\ndois\r\n")
    assert leitor.novas() == ["um", "dois"]


def test_veredito_e_descrever():
    assert "sem alertas" in R.veredito(0)
    assert "ALERTA" in R.veredito(1)
    assert "já estava" in R.veredito(R.CODIGO_OCUPADA)
    assert "erro" in R.veredito(9009)
    assert "14/10 05:30" in R.descrever({"origem": "agendada", "inicio": "2026-10-14T05:30:00"})
    assert "não consegui conferir" in R.descrever({"ilegivel": True})
    assert R.descrever({}) == "uma rodada está em andamento"


def test_novo_log_nome_e_colisao(tmp_path):
    from datetime import datetime
    raiz = _instalar(tmp_path)
    agora = datetime(2026, 10, 14, 9, 8, 7)
    base = f"rodada_app_20261014_090807_{os.getpid()}"
    um = R.novo_log(raiz, agora)
    assert um == raiz / "coletor" / "logs" / f"{base}.log"
    dois = R.novo_log(raiz, agora)
    assert dois.name == f"{base}_2.log"
    assert R.novo_log(raiz, agora).name == f"{base}_3.log"
    assert um.exists() and dois.exists() and um != dois
    assert R.novo_log(raiz).name.startswith("rodada_app_")
