# -*- coding: utf-8 -*-
"""Senha de primeira utilização.

Dois cuidados que valem mais que os testes em si:

1. **a senha real não aparece aqui** — o repositório é público, e escrevê-la no
   teste anularia o motivo de o código guardar só o hash. Os testes usam uma
   senha de mentira e trocam o hash esperado por `monkeypatch`: quem é exercido
   é o mecanismo (montar o hash, comparar, gravar o marcador), que é o que pode
   quebrar. A senha de verdade só entra na conta uma vez, quando alguém gera o
   hash para colar no módulo;
2. **nada abre janela** — `ativacao` só importa tkinter dentro de
   `pedir_ativacao()`, então a suíte roda no CI sem GUI. Aqui nada chama essa
   função.
"""
import hashlib

import ativacao

_SENHA_FALSA = "senha-de-teste-do-pytest"


def _com_senha_falsa(monkeypatch):
    """Faz o módulo aceitar a senha de mentira, sem tocar na verdadeira."""
    monkeypatch.setattr(ativacao, "_HASH_SENHA", ativacao._hash(_SENHA_FALSA))


def test_hash_confere_com_a_senha_certa(monkeypatch):
    _com_senha_falsa(monkeypatch)
    assert ativacao.senha_confere(_SENHA_FALSA)
    # Espaço colado ao redor (senha vinda de copiar e colar) ainda vale.
    assert ativacao.senha_confere(f"  {_SENHA_FALSA}\n")


def test_recusa_senha_errada(monkeypatch):
    _com_senha_falsa(monkeypatch)
    for errada in ("", "   ", _SENHA_FALSA.upper(), _SENHA_FALSA + "x",
                   _SENHA_FALSA[:-1], "123456", None):
        assert not ativacao.senha_confere(errada), errada


def test_hash_do_modulo_nao_guarda_a_senha_em_claro():
    # 64 hex = SHA-256. Se alguém trocar por texto, isto acusa antes do commit.
    assert len(ativacao._HASH_SENHA) == 64
    assert set(ativacao._HASH_SENHA) <= set("0123456789abcdef")
    # O sal precisa entrar na conta: sem ele, o hash da senha estaria em
    # qualquer tabela pronta de sha256 da internet.
    sem_sal = hashlib.sha256(b"x").hexdigest()
    assert ativacao._hash("x") != sem_sal
    assert ativacao._HASH_SENHA != ativacao._hash("")


def test_marcador_faz_o_app_nao_pedir_de_novo(tmp_path, monkeypatch):
    _com_senha_falsa(monkeypatch)
    assert not ativacao.ja_ativado(tmp_path)          # máquina nova: pergunta
    assert ativacao.marcar_ativado(tmp_path)
    assert (tmp_path / "ativacao.dat").is_file()
    assert ativacao.ja_ativado(tmp_path)              # e nunca mais pergunta


def test_marcador_vazio_ou_de_outra_senha_nao_vale(tmp_path, monkeypatch):
    _com_senha_falsa(monkeypatch)
    marcador = tmp_path / "ativacao.dat"

    marcador.write_text("", encoding="utf-8")         # truncado (disco/OneDrive)
    assert not ativacao.ja_ativado(tmp_path)

    marcador.write_text("qualquer coisa\n", encoding="utf-8")
    assert not ativacao.ja_ativado(tmp_path)

    # Marcador gravado quando a senha era outra: hash não bate, pergunta de novo.
    marcador.write_text(ativacao._hash("senha-antiga") + "\n", encoding="utf-8")
    assert not ativacao.ja_ativado(tmp_path)
