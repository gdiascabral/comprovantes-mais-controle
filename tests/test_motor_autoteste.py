# -*- coding: utf-8 -*-
"""`motor.autoteste`: o app importa DENTRO do exe?

Até 04/09/2026 esta pergunta era respondida por um segundo exe "de fumaça",
construído na build só para importar o app, com o roteiro inteiro escrito
dentro do `build.yml`. Hoje o roteiro mora no motor e quem o roda é o exe
publicado, com `--autoteste`. Estes testes exercitam o roteiro sobre um pacote
de mentira, porque o que se quer provar é a CLASSIFICAÇÃO: falta que derruba
(módulo que alguém importa), falta que só avisa (ferramenta que ninguém
importa) e reclamação de ambiente (que não é falta de módulo).
"""
import importlib
import sys
from pathlib import Path

import motor


def _pacote(tmp_path: Path, *, app_importa="", ferramenta_importa="",
            aba_levanta=False) -> Path:
    """Um `codigo_embutido` de mentira, com nomes que não colidem com o app."""
    raiz = tmp_path / "codigo_embutido"
    raiz.mkdir()
    (raiz / "comprovantes_app.py").write_text(
        (f"import {app_importa}\n" if app_importa else "")
        + "from zz_autoteste_aba import frame\n"
        + "def main():\n    pass\n", encoding="utf-8")
    aba = raiz / "zz_autoteste_aba"
    aba.mkdir()
    (aba / "__init__.py").write_text("", encoding="utf-8")
    (aba / "frame.py").write_text(
        "raise RuntimeError('sem cadastro nesta maquina')\n" if aba_levanta
        else "X = 1\n", encoding="utf-8")
    # Ferramenta que NINGUÉM importa: falta de módulo nela só avisa.
    (raiz / "zz_autoteste_ferramenta.py").write_text(
        (f"import {ferramenta_importa}\n" if ferramenta_importa else "")
        + "print('so por linha de comando')\n", encoding="utf-8")
    return raiz


def _limpar(monkeypatch):
    """Os nomes do pacote de mentira saem do `sys.modules` no fim, e o
    `comprovantes_app` de verdade (se já importado pela suíte) volta."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    for nome in ("comprovantes_app", "zz_autoteste_aba",
                 "zz_autoteste_aba.frame", "zz_autoteste_ferramenta"):
        monkeypatch.delitem(sys.modules, nome, raising=False)
    importlib.invalidate_caches()


def test_pacote_que_importa_inteiro_passa(tmp_path, monkeypatch):
    _limpar(monkeypatch)
    raiz = _pacote(tmp_path)
    relatorio = tmp_path / "autoteste.txt"

    assert motor.autoteste(raiz, relatorio) == 0
    texto = relatorio.read_text(encoding="utf-8")
    assert "-- ok" in texto, texto
    assert "NAO tem modulos" not in texto


def test_modulo_que_falta_em_quem_o_app_importa_derruba(tmp_path, monkeypatch):
    """É a falha da v1.0.71 (`tkinter.font`) e da v2.0.159 (`logging.handlers`):
    o app não abre, e o erro aparece antes de existir janela."""
    _limpar(monkeypatch)
    raiz = _pacote(tmp_path, app_importa="zz_biblioteca_que_nao_existe")
    relatorio = tmp_path / "autoteste.txt"

    assert motor.autoteste(raiz, relatorio) == 1
    texto = relatorio.read_text(encoding="utf-8")
    assert "NAO tem modulos" in texto
    assert "comprovantes_app" in texto
    assert "zz_biblioteca_que_nao_existe" in texto
    assert "_garantir_dependencias" in texto, "não diz onde declarar o import"


def test_falta_em_ferramenta_que_ninguem_importa_so_avisa(tmp_path,
                                                          monkeypatch):
    """`conciliacao/cli.py`, `aportes/teste_lancamento.py`: nenhum caminho do
    exe chega ali, então falta de módulo não derruba release."""
    _limpar(monkeypatch)
    raiz = _pacote(tmp_path, ferramenta_importa="zz_biblioteca_que_nao_existe")
    relatorio = tmp_path / "autoteste.txt"

    assert motor.autoteste(raiz, relatorio) == 0
    texto = relatorio.read_text(encoding="utf-8")
    assert "AVISO  zz_autoteste_ferramenta (ninguem o importa)" in texto, texto


def test_modulo_que_reclama_do_ambiente_nao_e_falta_de_modulo(tmp_path,
                                                              monkeypatch):
    """Cadastro que só existe na máquina de quem usa levanta no import; fica
    registrado, mas não é a v1.0.71."""
    _limpar(monkeypatch)
    raiz = _pacote(tmp_path, aba_levanta=True)
    relatorio = tmp_path / "autoteste.txt"

    assert motor.autoteste(raiz, relatorio) == 0
    texto = relatorio.read_text(encoding="utf-8")
    assert "AVISO  comprovantes_app -- RuntimeError" in texto, texto


def test_sem_relatorio_ainda_devolve_o_codigo(tmp_path, monkeypatch):
    _limpar(monkeypatch)
    raiz = _pacote(tmp_path)
    assert motor.autoteste(raiz) == 0


def test_a_linha_de_comando_le_pasta_e_relatorio(tmp_path, monkeypatch):
    _limpar(monkeypatch)
    raiz = _pacote(tmp_path)
    relatorio = tmp_path / "r.txt"
    monkeypatch.setattr(sys, "argv",
                        ["app.exe", "--autoteste", str(raiz), str(relatorio)])
    assert motor._autoteste_da_linha_de_comando() == 0
    assert relatorio.exists()


def test_o_autoteste_vem_antes_de_qualquer_release(monkeypatch):
    """`principal()` sai pelo autoteste ANTES de `preparar_codigo`: nada de
    rede, de janela nem de troca de exe num runner de CI."""
    import atualizador

    def _nunca(*_, **__):
        raise AssertionError("preparar_codigo foi chamado no autoteste")

    monkeypatch.setattr(atualizador, "preparar_codigo", _nunca)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "argv", ["app.exe", "--autoteste"])
    monkeypatch.setattr(motor, "_autoteste_da_linha_de_comando", lambda: 7)
    try:
        motor.principal()
    except SystemExit as e:
        assert e.code == 7
    else:
        raise AssertionError("principal() não saiu pelo autoteste")
