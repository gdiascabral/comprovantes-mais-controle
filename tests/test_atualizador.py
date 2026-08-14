# -*- coding: utf-8 -*-
"""
Testes do script que troca o executável.

A troca só acontece quando entra biblioteca nova — raro, e portanto pouco
exercitado. Dois defeitos ficaram escondidos até a v1.0.60: restos de `_MEI`
quebrando a extração seguinte (o erro que apareceu de verdade) e o `start`
rodando mesmo com a troca falhada.
"""
import io
import sys
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


# ------------------------------------------------ o nome longo do exe (14/08/2026)
# O 8.3 é ENDEREÇO, nunca NOME. Ele entrou (com razão) para o caminho não ter
# acento; o defeito foi usá-lo também como ALVO do `move`. Medido: `move /y
# origem "…\COMPRO~1.EXE"` deixa na pasta um arquivo chamado literalmente
# COMPRO~1.EXE, porque o `/y` APAGA o destino antes de renomear a origem — e,
# apagado o arquivo, o apelido 8.3 deixa de ser apelido de coisa nenhuma.
# Aconteceu duas vezes na máquina real e quebrou o atalho da área de trabalho.

def _linha(s: str, comeco: str) -> str:
    return next(l for l in s.splitlines() if l.startswith(comeco))


def test_a_troca_devolve_o_nome_longo_do_exe():
    s = script()
    ren = _linha(s, "ren ")
    # O `ren` recebe NOME, não caminho — é por isso que ele serve aqui: o
    # acento mora na PASTA, e a pasta não passa pelo segundo argumento.
    de, para = ren.split('"')[1], ren.split('"')[3]
    assert para == EXE.name
    assert "\\" not in para and "/" not in para
    assert de.endswith(".exe")
    # e ele vem DEPOIS do move ter dado certo: com o move falhado não há o que
    # renomear, e renomear o exe velho seria estragar o que ainda funciona.
    assert s.index("move /y") < s.index("\nren ")
    assert s.index(":trocou") < s.index("\nren ")


def test_o_app_reabre_pelo_nome_longo():
    """O atalho da área de trabalho aponta para o nome longo: reabrir pelo 8.3
    esconderia que o nome se perdeu — o app subiria e o atalho, não."""
    s = script()
    start = _linha(s, 'start ""')
    assert start.endswith(f'{EXE.name}"')
    assert s.index("\nren ") < s.index('start ""')


def test_com_8_3_o_move_mira_o_curto_e_o_ren_devolve_o_longo(tmp_path):
    """Os dois ao mesmo tempo, que é o ponto: caminho curto para chegar à
    pasta (imune à codepage) e nome longo de volta no fim."""
    pasta = tmp_path / "AUTOMAÇÕES MAIS CONTROLE"
    pasta.mkdir()
    exe = pasta / "Comprovantes Mais Controle.exe"
    exe.write_bytes(b"x")
    novo = tmp_path / "Comprovantes Mais Controle novo.exe"
    novo.write_bytes(b"y")

    curto = atualizador._caminho_curto(exe)
    if not curto:
        pytest.skip("8.3 desligado neste volume")
    s = atualizador.script_de_troca(1234, novo, exe)

    move = _linha(s, "move /y")
    assert exe.name not in move, "o nome longo não pode ser alvo do move"
    assert f'ren "{curto}" "{exe.name}"' in s
    assert f'start "" "{Path(curto).parent / exe.name}"' in s


# ------------------------------------------------------------ travar_versao.txt
# O freio de mão de quem NÃO é programador. Release ruim chega sozinha a todo
# mundo no próximo abrir, e até aqui a única saída era esperar a correção.

def test_sem_arquivo_nao_ha_trava(tmp_path):
    assert atualizador._tag_travada(tmp_path) == ""


def test_a_trava_e_a_tag_escrita(tmp_path):
    (tmp_path / "travar_versao.txt").write_text("v1.0.75\n", encoding="utf-8")
    assert atualizador._tag_travada(tmp_path) == "v1.0.75"


def test_a_trava_ignora_branco_e_comentario(tmp_path):
    """Quem edita no Bloco de Notas deixa linha em branco, e comentar a trava
    é mais natural do que apagá-la."""
    (tmp_path / "travar_versao.txt").write_text(
        "# preso ate a v1.0.78 ser corrigida\n\nv1.0.75\n", encoding="utf-8")
    assert atualizador._tag_travada(tmp_path) == "v1.0.75"


def test_trava_ilegivel_e_o_mesmo_que_nao_travar(tmp_path, monkeypatch):
    """Melhor seguir atualizando do que travar numa versão que não existe."""
    monkeypatch.setattr(atualizador, "_logar", lambda *_: None)
    (tmp_path / "travar_versao.txt").write_text("a ultima que prestava\n",
                                                encoding="utf-8")
    assert atualizador._tag_travada(tmp_path) == ""


# --------------------------------------------- instalação do codigo.zip
# O pacote que roda em TODA abertura era o único sem conferência de tamanho —
# o download do exe, que é raro, já tinha a dele. E a pasta anterior era
# apagada logo depois da troca, o que deixava a atualização sem volta.

class _Resposta:
    def __init__(self, corpo=None, conteudo=b"", cabecalhos=None):
        self._corpo = corpo or {}
        self.content = conteudo
        self.headers = cabecalhos or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._corpo

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _RequestsFalso:
    """Só o que `_atualizar_codigo` usa: a API da release e o zip."""

    def __init__(self, tag, corpo_zip, cabecalhos=None):
        self.tag = tag
        self.corpo_zip = corpo_zip
        self.cabecalhos = cabecalhos
        self.urls = []

    def get(self, url, **_):
        self.urls.append(url)
        if url.startswith("https://api.github.com"):
            return _Resposta({"tag_name": self.tag})
        cab = self.cabecalhos
        if cab is None:
            cab = {"content-length": str(len(self.corpo_zip))}
        return _Resposta(conteudo=self.corpo_zip, cabecalhos=cab)


def _codigo_zip(tag: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("comprovantes_app.py", "def main():\n    pass\n")
        zf.writestr("versao.txt", tag + "\n")
    return buf.getvalue()


def _instalado(tmp_path, versao="v1.0.77"):
    """Uma pasta `codigo` já instalada + a cópia de fábrica, como no exe."""
    pasta = tmp_path / "codigo"
    pasta.mkdir()
    (pasta / "comprovantes_app.py").write_text("velho\n", encoding="utf-8")
    (pasta / "versao.txt").write_text(versao + "\n", encoding="utf-8")
    emb = tmp_path / "codigo_embutido"
    emb.mkdir()
    (emb / "versao.txt").write_text("v1.0.70\n", encoding="utf-8")
    return pasta, emb


def _fingir_rede(monkeypatch, falso):
    monkeypatch.setattr(atualizador, "_logar", lambda *_: None)
    monkeypatch.setitem(sys.modules, "requests", falso)
    return falso


def test_a_pasta_anterior_fica_guardada(tmp_path, monkeypatch):
    """São ~370 KB — menos que um comprovante em PDF — pelo direito de voltar
    sem depender de rede: renomear `codigo_velha` para `codigo` desfaz."""
    pasta, emb = _instalado(tmp_path)
    _fingir_rede(monkeypatch, _RequestsFalso("v1.0.78", _codigo_zip("v1.0.78")))
    atualizador._atualizar_codigo(pasta, emb)
    assert (pasta / "versao.txt").read_text(encoding="utf-8").strip() == "v1.0.78"
    velha = tmp_path / "codigo_velha"
    assert (velha / "versao.txt").read_text(encoding="utf-8").strip() == "v1.0.77"


def test_zip_truncado_e_recusado_e_nao_derruba_o_que_ja_havia(tmp_path,
                                                              monkeypatch):
    """Sem esta conferência, o `extractall` grava "até onde deu": o app abria
    com metade dos arquivos de ontem e metade dos de hoje."""
    pasta, emb = _instalado(tmp_path)
    _fingir_rede(monkeypatch, _RequestsFalso(
        "v1.0.78", _codigo_zip("v1.0.78"),
        cabecalhos={"content-length": "999999"}))
    with pytest.raises(RuntimeError, match="incompleto"):
        atualizador._atualizar_codigo(pasta, emb)
    assert (pasta / "versao.txt").read_text(encoding="utf-8").strip() == "v1.0.77"


def test_resposta_que_nao_e_zip_diz_o_que_houve(tmp_path, monkeypatch):
    """A causa provável não é adulteração: é portal de wi-fi respondendo 200
    com HTML. "File is not a zip file" no log não diria isso a ninguém."""
    pasta, emb = _instalado(tmp_path)
    _fingir_rede(monkeypatch, _RequestsFalso(
        "v1.0.78", b"<html>entre com seu e-mail para navegar</html>"))
    with pytest.raises(RuntimeError, match="não é um zip válido"):
        atualizador._atualizar_codigo(pasta, emb)
    assert (pasta / "versao.txt").read_text(encoding="utf-8").strip() == "v1.0.77"


def test_travado_busca_a_tag_e_aceita_ir_para_TRAS(tmp_path, monkeypatch):
    """Voltar é o motivo de a trava existir: "só o que for mais novo" aqui
    seria a mesma coisa que não ter trava."""
    pasta, emb = _instalado(tmp_path, "v1.0.78")
    (tmp_path / "travar_versao.txt").write_text("v1.0.75\n", encoding="utf-8")
    falso = _fingir_rede(monkeypatch,
                         _RequestsFalso("v1.0.75", _codigo_zip("v1.0.75")))
    atualizador._atualizar_codigo(pasta, emb)
    assert "releases/tags/v1.0.75" in falso.urls[0]
    assert "/releases/download/v1.0.75/codigo.zip" in falso.urls[1]
    assert (pasta / "versao.txt").read_text(encoding="utf-8").strip() == "v1.0.75"


def test_travado_no_que_ja_esta_instalado_nao_rebaixa_nada(tmp_path, monkeypatch):
    pasta, emb = _instalado(tmp_path, "v1.0.75")
    (tmp_path / "travar_versao.txt").write_text("v1.0.75\n", encoding="utf-8")
    falso = _fingir_rede(monkeypatch,
                         _RequestsFalso("v1.0.75", _codigo_zip("v1.0.75")))
    atualizador._atualizar_codigo(pasta, emb)
    assert len(falso.urls) == 1, "baixou de novo o que já estava instalado"


def test_sem_trava_o_app_nunca_volta_sozinho(tmp_path, monkeypatch):
    """Release podada (o CI mantém 4) pode fazer a `latest` ficar mais VELHA
    que a instalada. Sem trava, isso não desfaz atualização nenhuma."""
    pasta, emb = _instalado(tmp_path, "v1.0.78")
    falso = _fingir_rede(monkeypatch,
                         _RequestsFalso("v1.0.75", _codigo_zip("v1.0.75")))
    atualizador._atualizar_codigo(pasta, emb)
    assert len(falso.urls) == 1
    assert (pasta / "versao.txt").read_text(encoding="utf-8").strip() == "v1.0.78"


def _fingir_exe(tmp_path, monkeypatch, v_codigo, v_embutida, travar=None):
    exe_dir = tmp_path / "app"
    (exe_dir / "codigo").mkdir(parents=True)
    (exe_dir / "codigo" / "versao.txt").write_text(v_codigo + "\n",
                                                   encoding="utf-8")
    emb = tmp_path / "mei" / "codigo_embutido"
    emb.mkdir(parents=True)
    (emb / "versao.txt").write_text(v_embutida + "\n", encoding="utf-8")
    if travar:
        (exe_dir / "travar_versao.txt").write_text(travar + "\n",
                                                   encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(exe_dir / "app.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "mei"), raising=False)
    monkeypatch.setattr(atualizador, "_atualizar_codigo", lambda *_: None)
    monkeypatch.setattr(atualizador, "_logar", lambda *_: None)
    return exe_dir / "codigo", emb


def test_a_trava_vence_a_copia_de_fabrica(tmp_path, monkeypatch):
    """O caso que interessa: quem trava está voltando de uma release ruim, e o
    exe que a trouxe traz o código ruim EMBUTIDO. A regra ">= embutida"
    desfaria a trava em silêncio — o pior desfecho para um freio de mão."""
    pasta, _ = _fingir_exe(tmp_path, monkeypatch, "v1.0.75", "v1.0.78",
                           travar="v1.0.75")
    assert atualizador.preparar_codigo() == pasta


def test_sem_trava_a_copia_de_fabrica_vence_o_codigo_mais_velho(tmp_path,
                                                                monkeypatch):
    """O contraexemplo que mostra que a regra normal continua de pé."""
    _, emb = _fingir_exe(tmp_path, monkeypatch, "v1.0.75", "v1.0.78")
    assert atualizador.preparar_codigo() == emb
