# -*- coding: utf-8 -*-
"""
Guarda o login do Mais Controle (e-mail + senha) para o login automático.

A senha é cifrada com a DPAPI do Windows (CryptProtectData): o resultado só
pode ser decifrado pelo MESMO usuário do Windows, neste computador — não fica
em texto puro em lugar nenhum. Se algo falhar (ou em sistema sem DPAPI), as
funções degradam para "sem login salvo" e o app cai no login manual.

Quem cifra é o `util.proteger_bytes` — a MESMA função que guarda a sessão da
nuvem. Enquanto a DPAPI estava aqui dentro, ela era um detalhe do módulo de
anexos, e o `nuvem/sessao.py` teria de importar `anexar` só para cifrar um
token.
"""
import json
import sys
from pathlib import Path

try:
    from . import config
except ImportError:
    import config

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util


def salvar(email: str, senha: str):
    """Cifra e grava o login ao lado do exe."""
    payload = json.dumps({"email": email, "senha": senha}).encode("utf-8")
    config.ARQUIVO_LOGIN.write_bytes(util.proteger_bytes(payload))


def carregar() -> tuple[str, str] | None:
    """Devolve (email, senha) do login salvo, ou None se não houver/der erro.

    Falhar aqui é normal (não há login salvo) mas também pode ser a DPAPI
    recusando — troca de usuário do Windows, perfil restaurado noutra
    máquina. Nesse caso o app cai no login manual sem explicar nada, então
    o motivo fica no diagnostico.log."""
    if not config.ARQUIVO_LOGIN.exists():
        return None                      # sem login salvo: silêncio é correto
    try:
        d = json.loads(
            util.revelar_bytes(config.ARQUIVO_LOGIN.read_bytes()).decode("utf-8"))
        return (d["email"], d["senha"])
    except Exception as e:
        config.diag(f"login salvo não pôde ser lido ({e!r}) — vai pedir login "
                    f"manual. Se persistir, apague {config.ARQUIVO_LOGIN.name}.")
        return None


def existe() -> bool:
    return config.ARQUIVO_LOGIN.exists()


def apagar():
    try:
        config.ARQUIVO_LOGIN.unlink()
    except OSError:
        pass
