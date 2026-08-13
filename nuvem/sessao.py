# -*- coding: utf-8 -*-
"""Quem está usando o app, e como ele continua entrando amanhã.

A sessão fica em `sessao.dat`, ao lado do exe, cifrada pela DPAPI — o mesmo
cofre do `login.dat`. Guardar o token em texto seria pior que guardar a senha:
o token entra sem precisar dela.

**O que acontece quando o servidor não responde** é a parte que exige cuidado,
e são três desfechos diferentes de propósito:

  vencido, com rede    -> pede a senha de novo. Normal.
  sem rede, no prazo   -> ABRE. O app já não faz nada sem internet (ERP,
                          Sicoob e portal são todos web), então travar aqui
                          só transformaria uma queda do Supabase em app
                          parado com o ERP de pé.
  sem rede, vencido    -> não abre, e diz isso.

E é preciso ser exato sobre o que o caso do meio garante: **sem servidor, o
app confere a VALIDADE, não a assinatura.** O token é assinado com um segredo
do projeto, que não pode viajar dentro de um exe público; sem ele, só dá para
ler a data de expiração de dentro do próprio token. Quem sustenta a garantia
aqui é a DPAPI: o `sessao.dat` só é decifrável pelo mesmo usuário do Windows
na mesma máquina que o gravou, e quem chegou nessa conta já tem o app, os
arquivos e o `login.dat`. Havendo rede, quem julga é o servidor — a renovação
é recusada se o usuário foi removido ou teve a senha trocada.
"""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

try:
    from . import rest
except ImportError:
    import rest

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

ARQUIVO = "sessao.dat"

#: Renova com folga: token que vence em 2 minutos vence no meio do trabalho.
FOLGA = 120


def _caminho(pasta=None) -> Path:
    return Path(pasta or util.pasta_base()) / ARQUIVO


def _quando_vence(token: str) -> int:
    """Lê o `exp` de dentro do JWT. 0 quando não dá para ler.

    Sem verificar assinatura — ver o cabeçalho do módulo. `+ "=="` cobre o
    padding que o base64url do JWT omite; sobra de padding é ignorada."""
    try:
        corpo = token.split(".")[1]
        dados = json.loads(base64.urlsafe_b64decode(corpo + "==").decode())
        return int(dados.get("exp") or 0)
    except Exception:
        return 0


def _email(token: str) -> str:
    try:
        corpo = token.split(".")[1]
        return json.loads(
            base64.urlsafe_b64decode(corpo + "==").decode()).get("email", "")
    except Exception:
        return ""


def _ler(pasta=None) -> dict | None:
    caminho = _caminho(pasta)
    if not caminho.exists():
        return None                      # sem sessão salva: silêncio é certo
    try:
        return json.loads(util.revelar_bytes(caminho.read_bytes()).decode())
    except Exception:
        # DPAPI recusando (outro usuário, perfil restaurado) ou arquivo
        # truncado. Nos dois casos o certo é pedir a senha, nunca adivinhar.
        return None


def _gravar(sessao: dict, pasta=None) -> None:
    try:
        _caminho(pasta).write_bytes(
            util.proteger_bytes(json.dumps(sessao).encode()))
    except OSError:
        # Pasta somente-leitura ou antivírus: quem acertou a senha entra
        # assim mesmo, e amanhã o app pergunta de novo. Pior é ficar de fora.
        pass


def entrar(email: str, senha: str, pasta=None) -> str:
    """Entra com e-mail e senha, guarda a sessão e devolve o token de acesso.

    Levanta `rest.PrecisaEntrar` se a senha não confere e `rest.SemRede` se
    não deu para perguntar."""
    corpo = rest.entrar(email.strip(), senha)
    sessao = {"acesso": corpo["access_token"],
              "renovacao": corpo["refresh_token"],
              "email": email.strip()}
    _gravar(sessao, pasta)
    return sessao["acesso"]


def token(pasta=None) -> str:
    """O token de acesso válido de agora, renovando se preciso.

    Levanta `rest.PrecisaEntrar` quando não há sessão utilizável — é o sinal
    de "mostre a janela de login"."""
    sessao = _ler(pasta)
    if not sessao:
        raise rest.PrecisaEntrar("ninguém entrou neste computador ainda")

    if _quando_vence(sessao.get("acesso", "")) - FOLGA > time.time():
        return sessao["acesso"]

    try:
        corpo = rest.renovar(sessao["renovacao"])
    except rest.SemRede:
        # Sem servidor para perguntar: vale enquanto o prazo do token durar.
        if _quando_vence(sessao.get("acesso", "")) > time.time():
            return sessao["acesso"]
        raise rest.PrecisaEntrar(
            "sem internet e a sessão salva venceu — conecte-se para entrar")
    except rest.PrecisaEntrar:
        esquecer(pasta)                  # não vale mais; não insista amanhã
        raise

    novo = {"acesso": corpo["access_token"],
            "renovacao": corpo["refresh_token"],
            "email": sessao.get("email") or _email(corpo["access_token"])}
    _gravar(novo, pasta)
    return novo["acesso"]


def tem_sessao(pasta=None) -> bool:
    """Há sessão salva? Não diz se ela ainda vale — para isso, `token()`."""
    return _ler(pasta) is not None


def quem(pasta=None) -> str:
    """E-mail de quem está usando, ou "" se ninguém entrou."""
    return (_ler(pasta) or {}).get("email", "")


def esquecer(pasta=None) -> None:
    """Apaga a sessão local. Não fala com o servidor."""
    try:
        _caminho(pasta).unlink()
    except OSError:
        pass


def sair(pasta=None) -> None:
    """Encerra a sessão aqui e no servidor."""
    sessao = _ler(pasta)
    if sessao:
        rest.sair(sessao.get("acesso", ""))
    esquecer(pasta)
