# -*- coding: utf-8 -*-
"""
Testes do script que troca o executável.

A troca só acontece quando entra biblioteca nova — raro, e portanto pouco
exercitado. Dois defeitos ficaram escondidos até a v1.0.60: restos de `_MEI`
quebrando a extração seguinte (o erro que apareceu de verdade) e o `start`
rodando mesmo com a troca falhada.
"""
import zipfile
from pathlib import Path

import pytest

import atualizador

NOVO = Path(r"C:\Temp\novo.exe")
EXE = Path(r"C:\App\Comprovantes.exe")


def script() -> str:
    return atualizador.script_de_troca(1234, NOVO, EXE)


def test_espera_o_processo_morrer_antes_de_mexer():
    s = script()
    assert 'tasklist /FI "PID eq 1234"' in s
    # a espera vem ANTES do move, senão trocaria o exe em uso
    assert s.index("goto espera") < s.index("move /y")


def test_usa_expansao_atrasada_no_contador():
    """Ler `%tent%` no mesmo bloco em que o `set /a` escreve dá o valor da
    volta anterior — o retry contava errado (31 tentativas em vez de 30)."""
    s = script()
    assert "setlocal enabledelayedexpansion" in s
    assert "!tent! LSS 30" in s
    assert "%tent%" not in s


def test_o_retry_nao_fica_preso_em_bloco():
    # O `if` de parada em linha própria, fora de `( ... )`, para o contador
    # valer o que aparenta valer.
    linha = next(l for l in script().splitlines() if "LSS 30" in l)
    assert linha.strip().startswith("if !tent!")


def test_so_abre_o_app_se_a_troca_deu_certo():
    s = script()
    assert "if not errorlevel 1 goto trocou" in s
    # o start está depois do rótulo :trocou, e há uma saída de erro antes dele
    assert s.index(":trocou") < s.index('start ""')
    assert s.index("exit /b 1") < s.index(":trocou")


def test_falha_explica_o_que_fazer_e_nao_abre_nada():
    s = script()
    trecho = s[s.index("Nao consegui substituir"):s.index(":trocou")]
    assert "pause" in trecho and "exit /b 1" in trecho
    assert "start" not in trecho


def test_limpa_os_MEI_antes_de_abrir():
    """Resto de extração anterior derruba o exe onefile com 'Failed to load
    Python DLL' — foi o erro real da troca da v1.0.60."""
    s = script()
    assert "_MEI*" in s and "rd /s /q" in s
    assert s.index("_MEI*") < s.index('start ""')


def test_caminhos_vao_entre_aspas():
    # "C:\Arquivos Morais\..." e "Program Files" têm espaço no nome.
    s = script()
    assert f'"{NOVO}"' in s and f'"{EXE}"' in s


def test_o_bat_se_apaga_no_fim():
    assert script().rstrip().endswith('del "%~f0"')


# ------------------------------------------------------- extração do codigo.zip
# O codigo.zip chega pela rede e vira código executado na máquina de quem usa:
# é o caminho mais curto que existe para plantar arquivo fora da pasta do app.

def _zip_com(tmp_path: Path, nomes: list[str]) -> Path:
    z = tmp_path / "codigo.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for n in nomes:
            zf.writestr(n, "print('oi')\n")
    return z


def test_extrai_zip_normal(tmp_path):
    z = _zip_com(tmp_path, ["comprovantes_app.py", "anexar/config.py"])
    destino = tmp_path / "codigo_nova"
    atualizador._extrair_seguro(z, destino)
    assert (destino / "comprovantes_app.py").is_file()
    assert (destino / "anexar" / "config.py").is_file()


def test_recusa_caminho_que_sobe_de_pasta(tmp_path):
    """zip-slip: `extractall` obedeceria "../" e escreveria fora do destino."""
    z = _zip_com(tmp_path, ["../plantado.py"])
    destino = tmp_path / "codigo_nova"
    with pytest.raises(RuntimeError, match="caminho suspeito"):
        atualizador._extrair_seguro(z, destino)
    assert not (tmp_path / "plantado.py").exists()


def test_recusa_caminho_absoluto(tmp_path):
    z = _zip_com(tmp_path, ["C:/Windows/Temp/plantado.py"])
    destino = tmp_path / "codigo_nova"
    with pytest.raises(RuntimeError, match="caminho suspeito"):
        atualizador._extrair_seguro(z, destino)


# ------------------------------------------------------- codificação do .bat
# 11/08/2026: a troca falhou na máquina real com
#   "O Windows não pode encontrar 'C:\AUTOMA├ç├òES MAIS CONTROLE\...'"
# O .bat era gravado em UTF-8 e o cmd.exe lê .bat na codepage OEM (850 aqui):
# "Ç" e "Õ" viravam "├ç" e "├ò". O app entrava em laço — abria, baixava 152 MB,
# falhava, fechava.

def test_o_bat_nao_estraga_caminho_com_acento(tmp_path):
    """Com acento no caminho, o conteúdo tem de sobreviver à codepage do cmd.

    Ou o caminho sai em 8.3 (ASCII puro), ou ele precisa ao menos ser
    gravável na codepage OEM sem virar outra coisa."""
    pasta = tmp_path / "AUTOMAÇÕES MAIS CONTROLE"
    pasta.mkdir()
    exe = pasta / "App.exe"
    exe.write_bytes(b"x")
    novo = tmp_path / "App novo.exe"
    novo.write_bytes(b"y")

    s = atualizador.script_de_troca(1234, novo, exe)
    cp = atualizador._codepage_do_cmd()
    # O teste de verdade: gravar como o app grava e reler como o cmd lê.
    de_volta = s.encode(cp, errors="strict").decode(cp)
    assert de_volta == s, "o .bat não sobrevive à ida e volta pela codepage do cmd"
    assert "├" not in de_volta


def test_codepage_do_cmd_nunca_e_utf8():
    """Se um dia isto devolver utf-8, o bug de 11/08/2026 volta inteiro."""
    cp = atualizador._codepage_do_cmd()
    assert cp.startswith("cp")
    assert cp not in ("cp65001", "utf-8", "utf8")


def test_caminho_curto_e_ascii_quando_existe(tmp_path):
    pasta = tmp_path / "PASTA COM ACENTO ÇÕ"
    pasta.mkdir()
    alvo = pasta / "arquivo.exe"
    alvo.write_bytes(b"x")
    curto = atualizador._caminho_curto(alvo)
    if curto:                       # 8.3 pode estar desligado no volume
        assert all(ord(c) < 128 for c in curto), curto


def test_caminho_curto_de_arquivo_inexistente_devolve_vazio(tmp_path):
    """Sem o arquivo, o Windows não tem 8.3 para dar — e aí vale o caminho
    longo, gravado na codepage do cmd."""
    assert atualizador._caminho_curto(tmp_path / "nao-existe.exe") == ""


# ------------------------------------------------- o nome do exe sobrevive
# A regressão real da v1.0.75: o destino do `move` era o caminho 8.3 INTEIRO,
# e `move` apaga o destino antes de renomear a origem. O apelido deixava de
# resolver no meio da operação e o exe renascia chamado `COMPRO~1.EXE` — o
# app abria, mas o atalho da área de trabalho apontava para o nada.

def test_o_move_preserva_o_nome_do_executavel(tmp_path):
    pasta = tmp_path / "PASTA COM ACENTO ÇÕ"
    pasta.mkdir()
    exe = pasta / "Comprovantes.Mais.Controle.exe"
    exe.write_bytes(b"x")
    novo = tmp_path / "baixado.exe"
    novo.write_bytes(b"y")

    s = atualizador.script_de_troca(1234, novo, exe)

    linha = next(ln for ln in s.splitlines() if ln.startswith("move /y"))
    destino = linha.rsplit('"', 3)[-2]
    assert destino.endswith("Comprovantes.Mais.Controle.exe"), destino
    assert "~" not in Path(destino).name, destino
    # e o `start` reabre exatamente o arquivo que acabou de ser gravado
    assert f'start "" "{destino}"' in s


def test_o_nome_do_exe_sobrevive_mesmo_com_8_3_ligado(tmp_path):
    """A pasta pode encurtar — é dela que vinham os acentos. O nome, não."""
    pasta = tmp_path / "PASTA COM ACENTO ÇÕ"
    pasta.mkdir()
    exe = pasta / "Comprovantes.Mais.Controle.exe"
    exe.write_bytes(b"x")

    ascii_ = atualizador._caminho_ascii(exe)

    assert Path(ascii_).name == "Comprovantes.Mais.Controle.exe"
    if atualizador._caminho_curto(pasta):     # 8.3 pode estar desligado
        assert all(ord(c) < 128 for c in ascii_), ascii_
