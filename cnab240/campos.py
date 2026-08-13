"""Formatação de campos conforme o item 2.2 do manual.

- ``Num``  : alinhado à direita, zeros à esquerda, sem separador decimal.
- ``Alfa`` : alinhado à esquerda, brancos à direita, maiúsculas, sem acentuação
             e sem caracteres especiais.
"""

from __future__ import annotations

import datetime as _dt
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .spec import Campo

# O manual desaconselha acentuação e caracteres especiais. Removemos acentuação e
# tudo que não for ASCII imprimível; o resto passa, porque chaves Pix, e-mails e
# URLs dependem de '@', ':', '/', '?' e '='.
_PERMITIDOS = frozenset(chr(c) for c in range(32, 127))

#: Campos cujo conteúdo é sensível a maiúsculas/minúsculas e não pode ser
#: normalizado: URL de QR Code dinâmico, chave de endereçamento e TXID.
CAMPOS_PRESERVAM_CASO = frozenset({"15.4.J52", "16.4.J52", "b.p1", "b.p3"})


class CampoInvalido(ValueError):
    def __init__(self, campo: Campo, motivo: str, valor: Any = None) -> None:
        self.campo = campo
        self.valor = valor
        super().__init__(f"{campo}: {motivo}" + (f" (valor={valor!r})" if valor is not None else ""))


def sanitizar(texto: str, *, maiusculas: bool = True) -> str:
    """Remove acentuação e caracteres não-ASCII; por padrão devolve maiúsculas."""
    sem_acento = unicodedata.normalize("NFKD", str(texto))
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    sem_acento = sem_acento.replace("Ç", "C").replace("ç", "c")
    if maiusculas:
        sem_acento = sem_acento.upper()
    return "".join(c if c in _PERMITIDOS else " " for c in sem_acento)


def fmt_alfa(valor: Any, tamanho: int, *, maiusculas: bool = True) -> str:
    if valor is None:
        return " " * tamanho
    return sanitizar(valor, maiusculas=maiusculas)[:tamanho].ljust(tamanho)


def _erro(campo: Campo | None, motivo: str, valor: Any) -> Exception:
    if campo is not None:
        return CampoInvalido(campo, motivo, valor)
    return ValueError(f"{motivo} (valor={valor!r})")


def fmt_num(valor: Any, tamanho: int, decimais: int = 0, *, campo: Campo | None = None) -> str:
    if valor is None or valor == "":
        return "0" * tamanho

    if isinstance(valor, str):
        limpo = valor.strip()
        for lixo in (".", ",", "-", "/", " "):
            limpo = limpo.replace(lixo, "")
        if not limpo:
            return "0" * tamanho
        if not limpo.isdigit():
            raise _erro(campo, "campo numérico com caracteres não numéricos", valor)
        # String de dígitos já vem na escala do arquivo (ex.: CNPJ, conta, data).
        inteiro = int(limpo)
    elif isinstance(valor, bool):
        inteiro = int(valor)
    elif isinstance(valor, int):
        inteiro = valor * (10 ** decimais)
    elif isinstance(valor, (Decimal, float)):
        d = Decimal(str(valor))
        inteiro = int((d * (10 ** decimais)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        raise _erro(campo, f"tipo {type(valor).__name__} não suportado em campo numérico", valor)

    if inteiro < 0:
        raise _erro(campo, "valor negativo não é representável", valor)

    texto = str(inteiro)
    if len(texto) > tamanho:
        raise _erro(campo, f"não cabe em {tamanho} posições", valor)
    return texto.rjust(tamanho, "0")


def fmt_data(valor: Any) -> str:
    """Data no formato DDMMAAAA. Aceita ``date``/``datetime``/``str``/``None``."""
    if valor is None or valor == "":
        return "00000000"
    if isinstance(valor, _dt.datetime):
        valor = valor.date()
    if isinstance(valor, _dt.date):
        return valor.strftime("%d%m%Y")
    texto = str(valor).strip()
    if len(texto) == 8 and texto.isdigit():
        return texto
    raise ValueError(f"data inválida: {valor!r} (use date ou 'DDMMAAAA')")


def fmt_hora(valor: Any) -> str:
    """Hora no formato HHMMSS."""
    if valor is None or valor == "":
        return "000000"
    if isinstance(valor, _dt.datetime):
        valor = valor.time()
    if isinstance(valor, _dt.time):
        return valor.strftime("%H%M%S")
    texto = str(valor).strip()
    if len(texto) == 6 and texto.isdigit():
        return texto
    raise ValueError(f"hora inválida: {valor!r} (use time ou 'HHMMSS')")


def fmt_competencia(valor: Any) -> str:
    """Mês/ano de competência no formato MMAAAA (GPS)."""
    if valor is None or valor == "":
        return "000000"
    if isinstance(valor, (_dt.date, _dt.datetime)):
        return valor.strftime("%m%Y")
    texto = str(valor).strip()
    if len(texto) == 6 and texto.isdigit():
        return texto
    raise ValueError(f"competência inválida: {valor!r} (use date ou 'MMAAAA')")


def formatar(campo: Campo, valor: Any) -> str:
    """Formata um valor conforme o tipo declarado no layout."""
    if isinstance(valor, (_dt.date, _dt.datetime)) and campo.tipo == "num":
        valor = fmt_data(valor) if campo.tamanho == 8 else fmt_competencia(valor)
    if isinstance(valor, _dt.time):
        valor = fmt_hora(valor)

    if campo.tipo == "num":
        return fmt_num(valor, campo.tamanho, campo.dec, campo=campo)
    return fmt_alfa(valor, campo.tamanho, maiusculas=campo.id not in CAMPOS_PRESERVAM_CASO)


def ler(campo: Campo, linha: str) -> str:
    """Extrai o texto cru de um campo a partir de um registro de 240 posições."""
    return linha[campo.de - 1 : campo.ate]


def ler_num(campo: Campo, linha: str) -> Decimal | int:
    """Extrai um campo numérico já com a escala decimal aplicada."""
    cru = ler(campo, linha).strip() or "0"
    if not cru.isdigit():
        raise CampoInvalido(campo, "conteúdo não numérico no arquivo", cru)
    if campo.dec:
        return Decimal(cru) / (10 ** campo.dec)
    return int(cru)


def ler_data(campo: Campo, linha: str) -> _dt.date | None:
    cru = ler(campo, linha).strip()
    if not cru or not cru.isdigit() or int(cru) == 0:
        return None
    try:
        return _dt.datetime.strptime(cru.zfill(8), "%d%m%Y").date()
    except ValueError:
        return None
