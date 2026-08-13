"""Montagem de registros de 240 posições a partir de um layout + valores.

Os valores são endereçados pelo ``id`` do campo no manual (``"20.3A"``), o que
mantém o código rastreável linha a linha contra o PDF.
"""

from __future__ import annotations

from typing import Any, Mapping

from .campos import CampoInvalido, formatar
from .spec import TAMANHO_REGISTRO, Layout


class RegistroIncompleto(ValueError):
    pass


def montar(layout: Layout, valores: Mapping[str, Any] | None = None) -> str:
    """Monta um registro completo de 240 posições."""
    linha = " " * TAMANHO_REGISTRO
    return aplicar(linha, layout, valores)


def aplicar(
    linha: str,
    layout: Layout,
    valores: Mapping[str, Any] | None = None,
    *,
    remessa: bool = True,
) -> str:
    """Sobrepõe os campos de ``layout`` sobre ``linha``.

    Usado tanto para montar o registro inteiro quanto para gravar sub-layouts
    (Informação 10/11/12 do segmento B, complementos de tributo do segmento N).
    """
    valores = valores or {}
    desconhecidos = set(valores) - {c.id for c in layout.campos}
    if desconhecidos:
        raise RegistroIncompleto(
            f"{layout.chave}: campos inexistentes no layout: {sorted(desconhecidos)}"
        )

    buffer = list(linha.ljust(TAMANHO_REGISTRO))
    for campo in layout.campos:
        if campo.id in valores and valores[campo.id] is not None:
            valor: Any = valores[campo.id]
        elif campo.default is not None:
            valor = campo.default
        elif campo.obrigatorio and remessa and not campo.so_retorno:
            raise RegistroIncompleto(
                f"{layout.chave}: campo obrigatório {campo} não foi informado"
            )
        else:
            valor = None

        texto = formatar(campo, valor)
        if len(texto) != campo.tamanho:  # defesa contra bug de formatação
            raise CampoInvalido(campo, f"formatador devolveu {len(texto)} posições")
        buffer[campo.de - 1 : campo.ate] = texto

    resultado = "".join(buffer)
    if len(resultado) != TAMANHO_REGISTRO:
        raise RegistroIncompleto(
            f"{layout.chave}: registro com {len(resultado)} posições, esperado {TAMANHO_REGISTRO}"
        )
    return resultado


def desmontar(layout: Layout, linha: str) -> dict[str, str]:
    """Devolve o conteúdo cru de cada campo, endereçado pelo id do manual."""
    return {c.id: linha[c.de - 1 : c.ate] for c in layout.campos}
