# -*- coding: utf-8 -*-
"""A verificação de release saiu da frente da janela (04/09/2026).

Até aqui `preparar_codigo` esperava, em SÉRIE e antes de qualquer tela, a API
do GitHub (até 5 s), o download do `codigo.zip` e a troca da pasta. Agora a
abertura só faz trabalho LOCAL (`aplicar_pendente`), o download roda numa
thread solta (`_baixar_em_segundo_plano`) e deixa o resultado em
`codigo_nova`, e quem instala é a SAÍDA do app — ou a abertura seguinte.

Estes testes usam os mesmos dublês de `test_atualizador.py` (a API falsa e o
zip de mentira), importados de lá, para a semântica de release ser uma só.
"""
import sys
from pathlib import Path

import atualizador
import motor

from test_atualizador import (_GitHubFalso, _RequestsFalso, _codigo_zip,
                              _fingir_rede, _instalado, _release)


def _exe(tmp_path, monkeypatch, v_codigo="v2.0.170", v_emb="v2.0.160",
         travar=None):
    """Um exe instalado, sem rede fingida ainda."""
    exe_dir = tmp_path / "app"
    pasta = exe_dir / "codigo"
    pasta.mkdir(parents=True)
    (pasta / "versao.txt").write_text(v_codigo + "\n", encoding="utf-8")
    (pasta / "comprovantes_app.py").write_text("velho\n", encoding="utf-8")
    emb = tmp_path / "mei" / "codigo_embutido"
    emb.mkdir(parents=True)
    (emb / "versao.txt").write_text(v_emb + "\n", encoding="utf-8")
    if travar:
        (exe_dir / "travar_versao.txt").write_text(travar + "\n",
                                                   encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(exe_dir / "app.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "mei"), raising=False)
    monkeypatch.setattr(atualizador, "_logar", lambda *_: None)
    return exe_dir, pasta, emb


def _pendente(pasta: Path, versao: str, com_app: bool = True) -> Path:
    nova = pasta.with_name("codigo_nova")
    nova.mkdir()
    (nova / "versao.txt").write_text(versao + "\n", encoding="utf-8")
    if com_app:
        (nova / "comprovantes_app.py").write_text("novo\n", encoding="utf-8")
    return nova


def _versao(pasta: Path) -> str:
    return (pasta / "versao.txt").read_text(encoding="utf-8").strip()


# ----------------------------------------------------- a abertura não espera
def test_sem_trava_a_abertura_nao_toca_a_rede(tmp_path, monkeypatch):
    """O que a pessoa paga ao abrir é zero rede: a API só é perguntada pela
    thread, que é disparada DEPOIS de a fonte estar escolhida."""
    exe_dir, pasta, emb = _exe(tmp_path, monkeypatch)
    falso = _GitHubFalso([_release("v2.0.175")])
    monkeypatch.setitem(sys.modules, "requests", falso)
    disparos = []
    monkeypatch.setattr(atualizador, "_iniciar_download_em_segundo_plano",
                        lambda p, e: disparos.append((p, e)))

    assert atualizador.preparar_codigo() == pasta
    assert falso.urls == [], "a abertura perguntou à rede antes da janela"
    assert disparos == [(pasta, emb)], "a thread do download não foi disparada"


def test_com_trava_continua_tudo_na_hora(tmp_path, monkeypatch):
    """Trava é ato deliberado: quem a escreveu quer AQUELA versão agora, e não
    na próxima abertura. O caminho síncrono de sempre fica para ela."""
    exe_dir, pasta, emb = _exe(tmp_path, monkeypatch, v_codigo="v2.0.170",
                               travar="v2.0.165")
    falso = _GitHubFalso([_release("v2.0.175"), _release("v2.0.165")])
    monkeypatch.setitem(sys.modules, "requests", falso)
    disparos = []
    monkeypatch.setattr(atualizador, "_iniciar_download_em_segundo_plano",
                        lambda p, e: disparos.append((p, e)))

    assert atualizador.preparar_codigo() == pasta
    assert _versao(pasta) == "v2.0.165"
    assert any("/releases/tags/v2.0.165" in u for u in falso.urls)
    assert disparos == [], "com trava não há segundo plano"


# ---------------------------------------------- o segundo plano só deixa pronto
def test_o_segundo_plano_deixa_codigo_nova_e_nao_troca_a_pasta(tmp_path,
                                                                 monkeypatch):
    pasta, emb = _instalado(tmp_path, "v1.0.77")
    registro = []
    falso = _fingir_rede(monkeypatch,
                         _RequestsFalso("v1.0.78", _codigo_zip("v1.0.78")))
    monkeypatch.setattr(atualizador, "_logar", registro.append)

    atualizador._baixar_em_segundo_plano(pasta, emb)

    assert _versao(pasta) == "v1.0.77", "trocou a pasta com o app aberto"
    nova = pasta.with_name("codigo_nova")
    assert _versao(nova) == "v1.0.78"
    assert not nova.with_name("codigo_nova.parcial").exists()
    assert not pasta.with_name("codigo_velha").exists()
    assert any("próxima abertura" in m for m in registro), registro
    assert len(falso.urls) == 2


def test_o_segundo_plano_nao_baixa_de_novo_o_que_ja_esta_pendente(tmp_path,
                                                                    monkeypatch):
    """Abrir o app três vezes no dia não pode ser três downloads do mesmo zip."""
    pasta, emb = _instalado(tmp_path, "v1.0.77")
    _pendente(pasta, "v1.0.78")
    falso = _fingir_rede(monkeypatch,
                         _RequestsFalso("v1.0.78", _codigo_zip("v1.0.78")))

    atualizador._baixar_em_segundo_plano(pasta, emb)

    assert len(falso.urls) == 1, "baixou o zip que já estava esperando"


def test_o_segundo_plano_engole_a_falha_de_rede(tmp_path, monkeypatch):
    """Nunca levanta: é uma thread solta, e exceção ali seria traceback num
    console que o exe não tem."""
    pasta, emb = _instalado(tmp_path, "v1.0.77")
    registro = []
    monkeypatch.setattr(atualizador, "_logar", registro.append)

    class _SemRede:
        def get(self, *_, **__):
            raise OSError("DNS")

    monkeypatch.setitem(sys.modules, "requests", _SemRede())
    atualizador._baixar_em_segundo_plano(pasta, emb)      # não levanta
    assert any("DNS" in m for m in registro), registro
    assert _versao(pasta) == "v1.0.77"


# ------------------------------------------------------------ aplicar_pendente
def test_aplicar_pendente_instala_o_mais_novo_e_guarda_o_anterior(tmp_path,
                                                                   monkeypatch):
    exe_dir, pasta, emb = _exe(tmp_path, monkeypatch, v_codigo="v2.0.170")
    _pendente(pasta, "v2.0.175")

    assert atualizador.aplicar_pendente(pasta) is True
    assert _versao(pasta) == "v2.0.175"
    assert _versao(pasta.with_name("codigo_velha")) == "v2.0.170"
    assert not pasta.with_name("codigo_nova").exists()


def test_sem_trava_o_pendente_mais_velho_e_descartado(tmp_path, monkeypatch):
    """Um download de ontem que a poda tornou mais velho que o instalado, ou um
    resto de decisão que mudou: não instala, e não fica esperando para sempre."""
    exe_dir, pasta, emb = _exe(tmp_path, monkeypatch, v_codigo="v2.0.170")
    _pendente(pasta, "v2.0.165")

    assert atualizador.aplicar_pendente(pasta) is False
    assert _versao(pasta) == "v2.0.170"
    assert not pasta.with_name("codigo_nova").exists()
    assert not pasta.with_name("codigo_velha").exists()


def test_com_trava_o_pendente_so_vale_se_for_a_tag_travada(tmp_path,
                                                            monkeypatch):
    """Voltar é o motivo de a trava existir: a tag travada instala mesmo sendo
    mais VELHA; qualquer outra versão pendente é resto e vai embora."""
    exe_dir, pasta, emb = _exe(tmp_path, monkeypatch, v_codigo="v2.0.170",
                               travar="v2.0.165")
    _pendente(pasta, "v2.0.165")
    assert atualizador.aplicar_pendente(pasta) is True
    assert _versao(pasta) == "v2.0.165"

    _pendente(pasta, "v2.0.175")                  # mais nova, mas não é a trava
    assert atualizador.aplicar_pendente(pasta) is False
    assert _versao(pasta) == "v2.0.165"
    assert not pasta.with_name("codigo_nova").exists()


def test_pendente_sem_o_app_dentro_nao_instala(tmp_path, monkeypatch):
    exe_dir, pasta, emb = _exe(tmp_path, monkeypatch, v_codigo="v2.0.170")
    _pendente(pasta, "v2.0.175", com_app=False)

    assert atualizador.aplicar_pendente(pasta) is False
    assert _versao(pasta) == "v2.0.170"
    assert not pasta.with_name("codigo_nova").exists()


def test_sem_pendente_nada_muda(tmp_path, monkeypatch):
    exe_dir, pasta, emb = _exe(tmp_path, monkeypatch, v_codigo="v2.0.170")
    assert atualizador.aplicar_pendente(pasta) is False
    assert _versao(pasta) == "v2.0.170"


def test_o_parcial_so_e_limpo_na_abertura(tmp_path, monkeypatch):
    """Na saída a thread pode estar escrevendo em `.parcial`; apagar embaixo
    dela é o jeito de instalar meia pasta na abertura seguinte."""
    exe_dir, pasta, emb = _exe(tmp_path, monkeypatch)
    parcial = pasta.with_name("codigo_nova.parcial")
    parcial.mkdir()
    (parcial / "versao.txt").write_text("v9\n", encoding="utf-8")

    atualizador.aplicar_pendente(pasta, limpar_parcial=False)
    assert parcial.exists(), "apagou o download em andamento na saída"
    atualizador.aplicar_pendente(pasta)
    assert not parcial.exists(), "não limpou o resto na abertura"


def test_a_abertura_instala_o_que_a_anterior_deixou(tmp_path, monkeypatch):
    """O caminho inteiro de um dia comum: a abertura de ontem baixou, a de
    hoje instala ANTES de escolher a fonte — sem rede."""
    exe_dir, pasta, emb = _exe(tmp_path, monkeypatch, v_codigo="v2.0.170")
    _pendente(pasta, "v2.0.175")
    monkeypatch.setitem(sys.modules, "requests", _GitHubFalso([]))
    monkeypatch.setattr(atualizador, "_iniciar_download_em_segundo_plano",
                        lambda *_: None)

    assert atualizador.preparar_codigo() == pasta
    assert _versao(pasta) == "v2.0.175"


# ------------------------------------------------------------------- o motor
def test_o_motor_instala_o_pendente_na_saida_sem_limpar_o_parcial(monkeypatch):
    chamadas = []
    monkeypatch.setattr(atualizador, "aplicar_pendente",
                        lambda *a, **k: chamadas.append((a, k)))
    motor._instalar_o_que_chegou()
    assert chamadas == [((), {"limpar_parcial": False})]


def test_a_saida_engole_o_que_o_instalar_levantar(monkeypatch):
    """O app já está fechando: exceção aqui viraria traceback sem console."""
    registro = []
    monkeypatch.setattr(atualizador, "_logar", registro.append)

    def _estoura(*_, **__):
        raise OSError("OneDrive segurando a pasta")

    monkeypatch.setattr(atualizador, "aplicar_pendente", _estoura)
    motor._instalar_o_que_chegou()                        # não levanta
    assert any("OneDrive" in m for m in registro), registro
