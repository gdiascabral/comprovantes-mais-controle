# -*- coding: utf-8 -*-
"""A chave da API da Anthropic (leitura de anexo escrito à mão por IA).

Mora cifrada pela DPAPI do Windows em `anthropic.dat`, ao lado do exe — o
mesmo cofre do `login.dat` (`util.proteger_bytes`). Na máquina de quem gera o
HTML também vale o arquivo `_chaves/anthropic-api.txt` (uma linha, só a
chave), que este módulo só LÊ: nunca grava chave em texto, nunca a escreve em
log. Sem chave nenhuma a função fica desligada e as linhas seguem "Não li".

Para guardar a chave cifrada: `python -m pagamentos_dia.chave_ia` (pede a
chave sem mostrá-la).
"""
from __future__ import annotations

from pathlib import Path

ARQUIVO = "anthropic.dat"
TEXTO = Path("_chaves") / "anthropic-api.txt"


def _pasta(pasta) -> Path:
    if pasta is not None:
        return Path(pasta)
    import util
    return util.pasta_base()


def salvar(chave: str, pasta=None, *, cifrar=None) -> bool:
    chave = str(chave or "").strip()
    if not chave or any(c.isspace() for c in chave):
        return False
    if cifrar is None:
        import util
        cifrar = util.proteger_bytes
    (_pasta(pasta) / ARQUIVO).write_bytes(cifrar(chave.encode("utf-8")))
    return True


def _do_texto(base: Path) -> str | None:
    try:
        linhas = (base / TEXTO).read_text(encoding="utf-8").strip().splitlines()
    except (OSError, ValueError):
        return None
    if len(linhas) != 1 or any(c.isspace() for c in linhas[0].strip()):
        return None
    return linhas[0].strip() or None


def carregar(pasta=None, *, decifrar=None) -> str | None:
    """A chave, ou None (função desligada). Nunca levanta."""
    base = _pasta(pasta)
    if decifrar is None:
        import util
        decifrar = util.revelar_bytes
    try:
        cifrado = (base / ARQUIVO).read_bytes()
    except OSError:
        cifrado = None
    if cifrado:
        try:
            chave = decifrar(cifrado).decode("utf-8").strip()
            if chave:
                return chave
        except (OSError, ValueError):
            pass                       # DPAPI recusou: tenta o arquivo de texto
    return _do_texto(base)


if __name__ == "__main__":             # pragma: no cover - uso manual
    import getpass
    print("guardada" if salvar(getpass.getpass("Chave da API (não aparece): "))
          else "nada guardado (chave vazia ou com espaços)")
