# -*- coding: utf-8 -*-
"""
Guarda o login do Mais Controle (e-mail + senha) para o login automático.

A senha é cifrada com a DPAPI do Windows (CryptProtectData): o resultado só
pode ser decifrado pelo MESMO usuário do Windows, neste computador — não fica
em texto puro em lugar nenhum. Se algo falhar (ou em sistema sem DPAPI), as
funções degradam para "sem login salvo" e o app cai no login manual.

Usa apenas a biblioteca padrão (ctypes), então não pesa no executável.
"""
import ctypes
import json
from ctypes import wintypes

try:
    from . import config
except ImportError:
    import config


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _entrada(dados: bytes) -> _BLOB:
    buf = ctypes.create_string_buffer(dados, len(dados))
    return _BLOB(len(dados), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _saida_bytes(blob: _BLOB) -> bytes:
    return ctypes.string_at(blob.pbData, int(blob.cbData))


def _cifrar(dados: bytes) -> bytes:
    out = _BLOB()
    inp = _entrada(dados)
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("CryptProtectData falhou")
    try:
        return _saida_bytes(out)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _decifrar(dados: bytes) -> bytes:
    out = _BLOB()
    inp = _entrada(dados)
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("CryptUnprotectData falhou")
    try:
        return _saida_bytes(out)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def salvar(email: str, senha: str):
    """Cifra e grava o login ao lado do exe."""
    payload = json.dumps({"email": email, "senha": senha}).encode("utf-8")
    config.ARQUIVO_LOGIN.write_bytes(_cifrar(payload))


def carregar() -> tuple[str, str] | None:
    """Devolve (email, senha) do login salvo, ou None se não houver/der erro."""
    try:
        dados = config.ARQUIVO_LOGIN.read_bytes()
        d = json.loads(_decifrar(dados).decode("utf-8"))
        return (d["email"], d["senha"])
    except Exception:
        return None


def existe() -> bool:
    return config.ARQUIVO_LOGIN.exists()


def apagar():
    try:
        config.ARQUIVO_LOGIN.unlink()
    except OSError:
        pass
