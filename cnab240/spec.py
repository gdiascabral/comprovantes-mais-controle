"""Carga e resolução da parametrização CNAB 240 (pasta ``spec/``).

Os layouts vivem em JSON, não em código, para que a auditoria contra o manual do
Sicoob seja direta: cada campo carrega o ``id`` do manual (ex.: ``20.3A``) e o
código da seção 13 (ex.: ``P010``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

TAMANHO_REGISTRO = 240


def _achar_spec_dir() -> Path:
    """Localiza a pasta ``spec/``.

    Fica fora do pacote de propósito — a parametrização é um artefato de
    negócio, auditável contra o PDF sem abrir código. Procuramos ao lado do
    pacote (repositório) e dentro dele (instalação empacotada).
    """
    import os

    if env := os.environ.get("CNAB240_SPEC_DIR"):
        return Path(env)

    aqui = Path(__file__).resolve().parent
    for candidato in (aqui.parent / "spec", aqui / "spec"):
        if (candidato / "layouts.json").is_file():
            return candidato

    raise SpecInvalida(
        "pasta spec/ não encontrada (procurado em "
        f"{aqui.parent / 'spec'} e {aqui / 'spec'}). "
        "Defina CNAB240_SPEC_DIR para apontar a parametrização."
    )


SPEC_DIR = None  # resolvido na primeira leitura, por _spec_dir()


@lru_cache(maxsize=1)
def _spec_dir() -> Path:
    global SPEC_DIR
    SPEC_DIR = _achar_spec_dir()
    return SPEC_DIR


class SpecInvalida(Exception):
    """A parametrização em ``spec/`` está inconsistente."""


@dataclass(frozen=True)
class Campo:
    id: str
    nome: str
    de: int
    ate: int
    dec: int
    tipo: str
    default: str | None
    obrig: str
    ref: str | None

    @property
    def tamanho(self) -> int:
        return self.ate - self.de + 1

    @property
    def obrigatorio(self) -> bool:
        return self.obrig == "O"

    @property
    def so_retorno(self) -> bool:
        return self.obrig == "R"

    def __str__(self) -> str:
        return f"{self.id} {self.nome} ({self.de}-{self.ate})"


@dataclass(frozen=True)
class Layout:
    chave: str
    uso: str
    campos: tuple[Campo, ...]
    tipo_registro: str | None = None
    segmento: str | None = None
    versao_layout_lote: str | None = None
    somente_retorno: bool = False

    _por_id: dict[str, Campo] = field(
        default=None, compare=False, repr=False  # type: ignore[assignment]
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "_por_id", {c.id: c for c in self.campos})

    def campo(self, id_campo: str) -> Campo:
        try:
            return self._por_id[id_campo]
        except KeyError:
            raise SpecInvalida(
                f"campo {id_campo!r} não existe no layout {self.chave!r}"
            ) from None

    def __iter__(self) -> Iterator[Campo]:
        return iter(self.campos)

    @property
    def de(self) -> int:
        return min(c.de for c in self.campos)

    @property
    def ate(self) -> int:
        return max(c.ate for c in self.campos)


def _campo(linha: list[Any]) -> Campo:
    id_, nome, de, ate, dec, tipo, default, obrig, ref = linha
    if tipo not in ("num", "alfa"):
        raise SpecInvalida(f"{id_}: tipo {tipo!r} desconhecido")
    if obrig not in ("O", "C", "R"):
        raise SpecInvalida(f"{id_}: obrigatoriedade {obrig!r} desconhecida")
    if ate < de:
        raise SpecInvalida(f"{id_}: posição final {ate} anterior à inicial {de}")
    return Campo(id_, nome, de, ate, dec, tipo, default, obrig, ref)


def _monta_layout(chave: str, bloco: dict[str, Any], base: dict[str, Any]) -> Layout:
    if "herda_de" in bloco:
        herdados = {c[0]: list(c) for c in base[bloco["herda_de"]]["campos"]}
        for override in bloco.get("overrides", []):
            herdados[override[0]] = list(override)
        linhas = list(herdados.values())
    else:
        linhas = bloco["campos"]

    campos = tuple(sorted((_campo(l) for l in linhas), key=lambda c: c.de))
    return Layout(
        chave=chave,
        uso=bloco.get("_uso", ""),
        campos=campos,
        tipo_registro=bloco.get("tipo_registro"),
        segmento=bloco.get("segmento"),
        versao_layout_lote=bloco.get("versao_layout_lote"),
        somente_retorno=bloco.get("somente_retorno", False),
    )


def _verificar_cobertura(layout: Layout, registro_completo: bool) -> None:
    """Garante que os campos cobrem o intervalo sem buracos nem sobreposição."""
    esperado = 1 if registro_completo else layout.de
    for campo in layout.campos:
        if campo.de != esperado:
            raise SpecInvalida(
                f"{layout.chave}: {campo.id} começa em {campo.de}, "
                f"esperado {esperado} (buraco ou sobreposição no layout)"
            )
        esperado = campo.ate + 1
    if registro_completo and esperado != TAMANHO_REGISTRO + 1:
        raise SpecInvalida(
            f"{layout.chave}: cobre até a posição {esperado - 1}, "
            f"esperado {TAMANHO_REGISTRO}"
        )


@lru_cache(maxsize=1)
def _carregar() -> dict[str, Layout]:
    bruto = json.loads((_spec_dir() / "layouts.json").read_text(encoding="utf-8"))
    layouts: dict[str, Layout] = {}

    for chave, bloco in bruto.items():
        if chave.startswith("_") or not isinstance(bloco, dict):
            continue

        if "campos" in bloco or "herda_de" in bloco:
            layout = _monta_layout(chave, bloco, bruto)
            _verificar_cobertura(layout, registro_completo=True)
            layouts[chave] = layout

        # Sub-layouts: recortes de faixas do registro pai (Informação 10/11/12
        # do segmento B, complementos de tributo do segmento N).
        for sub_chave, sub_bloco in bloco.items():
            if sub_chave.startswith("_") or not isinstance(sub_bloco, dict):
                continue
            if "campos" not in sub_bloco:
                continue
            nome = f"{chave}.{sub_chave}"
            sub = _monta_layout(nome, sub_bloco, bruto)
            _verificar_cobertura(sub, registro_completo=False)
            layouts[nome] = sub

    if not layouts:
        raise SpecInvalida(f"nenhum layout encontrado em {_spec_dir() / 'layouts.json'}")
    return layouts


def layout(chave: str) -> Layout:
    """Devolve um layout pelo nome, ex.: ``segmento_a``."""
    layouts = _carregar()
    try:
        return layouts[chave]
    except KeyError:
        disponiveis = ", ".join(sorted(layouts))
        raise SpecInvalida(
            f"layout {chave!r} não existe. Disponíveis: {disponiveis}"
        ) from None


def layouts() -> dict[str, Layout]:
    return dict(_carregar())


@lru_cache(maxsize=1)
def dominios() -> dict[str, Any]:
    return json.loads((_spec_dir() / "dominios.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def produtos() -> dict[str, Any]:
    return json.loads((_spec_dir() / "produtos.json").read_text(encoding="utf-8"))


def produto(id_produto: str) -> dict[str, Any]:
    for p in produtos()["produtos"]:
        if p["id"] == id_produto:
            return p
    ids = ", ".join(p["id"] for p in produtos()["produtos"])
    raise SpecInvalida(f"produto {id_produto!r} não existe. Disponíveis: {ids}")
