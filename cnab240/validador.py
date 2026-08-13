"""Validação de arquivos CNAB 240 — replica as regras do item 12 do manual.

Divide os achados em dois níveis, como o Sicoob faz:

- ``ARQUIVO``  : erro de estrutura/domínio em header/trailer de arquivo ou lote,
                 ou nos campos de controle/serviço dos segmentos → rejeita tudo.
- ``REGISTRO`` : campo obrigatório vazio, numérico com letra, domínio inválido
                 → rejeita apenas aquele registro.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Sequence

from . import spec
from .campos import ler, ler_num
from .dominios import BANCO_SICOOB
from .spec import TAMANHO_REGISTRO, Layout

NIVEL_ARQUIVO = "ARQUIVO"
NIVEL_REGISTRO = "REGISTRO"

#: Campos de controle (posições 1-8) e de serviço — erro aqui rejeita o arquivo.
_LIMITE_CONTROLE_SERVICO = 17


@dataclass(frozen=True)
class Problema:
    linha: int
    nivel: str
    mensagem: str
    campo: str | None = None

    def __str__(self) -> str:
        onde = f" [{self.campo}]" if self.campo else ""
        return f"linha {self.linha}{onde}: {self.mensagem} ({self.nivel})"


# --------------------------------------------------------------------------
# Resolução de layout por linha
# --------------------------------------------------------------------------

_PRODUTO_POR_FORMA: dict[str, str] = {
    "05": "TRANSFERENCIA_SICOOB",
    "41": "TED",
    "43": "TED",
    "45": "PIX_TRANSFERENCIA",
    "30": "TITULOS_COBRANCA",
    "31": "TITULOS_COBRANCA",
    "47": "PIX_QRCODE",
    "11": "CONVENIOS_COM_CODIGO_BARRAS",
    "16": "TRIBUTOS_SEM_CODIGO_BARRAS",
    "17": "TRIBUTOS_SEM_CODIGO_BARRAS",
    "18": "TRIBUTOS_SEM_CODIGO_BARRAS",
}


def produto_do_header_lote(linha: str) -> str | None:
    servico = linha[9:11]
    forma = linha[11:13]
    if forma == "01":
        return "FOLHA_PAGAMENTO" if servico == "30" else "TRANSFERENCIA_SICOOB"
    return _PRODUTO_POR_FORMA.get(forma)


def _layout_detalhe(produto: str | None, segmento: str, ja_teve_j: bool) -> Layout | None:
    if segmento == "A":
        return spec.layout("segmento_a")
    if segmento == "B":
        return spec.layout(
            "segmento_b_folha" if produto == "FOLHA_PAGAMENTO" else "segmento_b_transferencia"
        )
    if segmento == "J":
        if not ja_teve_j:
            return spec.layout("segmento_j")
        return spec.layout("segmento_j52_pix" if produto == "PIX_QRCODE" else "segmento_j52")
    if segmento == "O":
        return spec.layout("segmento_o")
    if segmento == "N":
        return spec.layout("segmento_n")
    if segmento == "W":
        return spec.layout("segmento_w")
    if segmento == "Z":
        return spec.layout("segmento_z")
    return None


#: Campos cujo domínio é conferido, por layout.
_CHECAR_DOMINIO: list[tuple[str, str, str]] = [
    ("header_arquivo", "05.0", "G005"),
    ("header_arquivo", "16.0", "G015"),
    ("header_lote_transferencia", "04.1", "G028"),
    ("header_lote_transferencia", "05.1", "G025"),
    ("header_lote_transferencia", "06.1", "G029"),
    ("header_lote_titulos", "04.1", "G028"),
    ("header_lote_titulos", "05.1", "G025"),
    ("header_lote_titulos", "06.1", "G029"),
    ("header_lote_tributos", "04.1", "G028"),
    ("header_lote_tributos", "05.1", "G025"),
    ("header_lote_tributos", "06.1", "G029"),
    ("header_lote_folha", "04.1", "G028"),
    ("header_lote_folha", "05.1", "G025"),
    ("header_lote_folha", "06.1", "G029"),
    ("segmento_a", "06.3A", "G060"),
    ("segmento_a", "07.3A", "G061"),
    ("segmento_a", "29.3A", "P006"),
    ("segmento_b_transferencia", "07.3B", "G005"),
    ("segmento_b_folha", "07.3B", "G005"),
    ("segmento_j", "06.3J", "G060"),
    ("segmento_j", "19.3J", "G065"),
    ("segmento_o", "06.3O", "G060"),
    ("segmento_n", "06.3N", "G060"),
]

#: Campo de valor do pagamento, por segmento — usado na conferência do trailer.
_CAMPO_VALOR: dict[str, tuple[str, str]] = {
    "segmento_a": ("segmento_a", "20.3A"),
    "segmento_j": ("segmento_j", "15.3J"),
    "segmento_o": ("segmento_o", "12.3O"),
    "segmento_n": ("segmento_n", "12.3N"),
}


#: Campos em que branco/zero significa "não preenchido".
#: A obrigatoriedade do manual não serve como critério direto: zero é conteúdo
#: legítimo em densidade, quantidade de moeda, dígitos verificadores etc.
_CONTEUDO_OBRIGATORIO: dict[str, set[str]] = {
    "header_arquivo": {"06.0", "07.0", "08.0", "10.0", "13.0", "14.0", "17.0", "19.0"},
    "header_lote_transferencia": {"11.1", "12.1", "14.1"},
    "header_lote_folha": {"11.1", "12.1", "14.1", "18.1"},
    "header_lote_titulos": {"11.1", "12.1", "14.1"},
    "header_lote_tributos": {"11.1", "12.1", "14.1"},
    "segmento_a": {"09.3A", "10.3A", "12.3A", "17.3A", "20.3A"},
    "segmento_b_transferencia": {"08.3B"},
    "segmento_b_folha": {"08.3B"},
    "segmento_j": {"08.3J", "14.3J", "15.3J"},
    "segmento_j52_pix": {"15.4.J52", "16.4.J52"},
    "segmento_o": {"08.3O", "11.3O", "12.3O"},
    "segmento_n": {"11.3N", "12.3N", "13.3N"},
    "trailer_lote_transferencia": {"05.5"},
    "trailer_lote_titulos": {"05.5"},
    "trailer_lote_tributos": {"05.5"},
    "trailer_arquivo": {"05.9", "06.9"},
}

#: Exceções por produto: campos que legitimamente ficam zerados.
_SEM_CONTEUDO_NO_PRODUTO: dict[str, set[str]] = {
    # Pix por chave não trafega agência/conta do favorecido.
    "PIX_TRANSFERENCIA": {"10.3A", "12.3A"},
    # Pix QR Code não tem boleto: o campo 08.3J vai zerado.
    "PIX_QRCODE": {"08.3J"},
}


def _dominios_do_layout(chave: str) -> list[tuple[str, str]]:
    return [(c, d) for (l, c, d) in _CHECAR_DOMINIO if l == chave]


# --------------------------------------------------------------------------
# Validação
# --------------------------------------------------------------------------


def _validar_campos(
    linha: str,
    numero: int,
    layout: Layout,
    problemas: list[Problema],
    produto: str | None = None,
) -> None:
    from .dominios import valores as dominio_valores

    def nivel_de(campo) -> str:
        return NIVEL_ARQUIVO if campo.ate <= _LIMITE_CONTROLE_SERVICO else NIVEL_REGISTRO

    exigidos = set(_CONTEUDO_OBRIGATORIO.get(layout.chave, ()))
    exigidos -= _SEM_CONTEUDO_NO_PRODUTO.get(produto or "", set())

    for campo in layout.campos:
        cru = ler(campo, linha)

        if campo.tipo == "num" and cru.strip() and not cru.strip().isdigit():
            problemas.append(
                Problema(numero, nivel_de(campo), f"campo numérico com conteúdo não numérico: {cru!r}", campo.id)
            )
            continue

        if campo.id in exigidos:
            vazio = not cru.strip() if campo.tipo == "alfa" else set(cru) <= {"0", " "}
            if vazio:
                problemas.append(
                    Problema(numero, nivel_de(campo), "campo obrigatório não preenchido", campo.id)
                )

        # Valores fixos de layout: só conferidos nos campos de controle/serviço,
        # que são exatamente os que fazem o Sicoob rejeitar o arquivo inteiro.
        if campo.default and campo.ate <= _LIMITE_CONTROLE_SERVICO:
            if campo.tipo == "num":
                confere = cru == campo.default.rjust(campo.tamanho, "0")
            else:
                confere = cru.strip() == campo.default.strip()
            if not confere:
                problemas.append(
                    Problema(
                        numero,
                        NIVEL_ARQUIVO,
                        f"esperado {campo.default!r} fixo pelo layout, encontrado {cru.strip()!r}",
                        campo.id,
                    )
                )

    for campo_id, codigo in _dominios_do_layout(layout.chave):
        campo = layout.campo(campo_id)
        cru = ler(campo, linha).strip()
        if not cru:
            continue
        if cru not in dominio_valores(codigo):
            nivel = NIVEL_ARQUIVO if campo.ate <= _LIMITE_CONTROLE_SERVICO else NIVEL_REGISTRO
            problemas.append(
                Problema(numero, nivel, f"valor {cru!r} fora do domínio {codigo}", campo.id)
            )


def validar(conteudo: str | Sequence[str]) -> list[Problema]:
    """Valida um arquivo CNAB 240 completo (remessa ou retorno)."""
    if isinstance(conteudo, str):
        linhas = [l for l in conteudo.replace("\r\n", "\n").split("\n") if l.strip()]
    else:
        linhas = [l for l in conteudo if l.strip()]

    problemas: list[Problema] = []
    if not linhas:
        return [Problema(0, NIVEL_ARQUIVO, "arquivo vazio")]

    for i, linha in enumerate(linhas, start=1):
        if len(linha) != TAMANHO_REGISTRO:
            problemas.append(
                Problema(i, NIVEL_ARQUIVO, f"registro com {len(linha)} posições, esperado {TAMANHO_REGISTRO}")
            )

    # Só seguimos com a análise semântica se o tamanho estiver correto.
    if problemas:
        return problemas

    if linhas[0][7] != "0":
        problemas.append(Problema(1, NIVEL_ARQUIVO, "primeira linha não é o header de arquivo (tipo 0)"))
    if linhas[-1][7] != "9":
        problemas.append(
            Problema(len(linhas), NIVEL_ARQUIVO, "última linha não é o trailer de arquivo (tipo 9)")
        )
    if problemas:
        return problemas

    _validar_campos(linhas[0], 1, spec.layout("header_arquivo"), problemas)
    _validar_campos(linhas[-1], len(linhas), spec.layout("trailer_arquivo"), problemas)

    lotes_vistos = 0
    lote_atual: dict | None = None

    for numero, linha in enumerate(linhas[1:-1], start=2):
        if linha[:3] != BANCO_SICOOB:
            problemas.append(
                Problema(numero, NIVEL_ARQUIVO, f"código do banco {linha[:3]!r}, esperado {BANCO_SICOOB}", "01")
            )
        tipo = linha[7]

        if tipo == "1":
            if lote_atual is not None:
                problemas.append(
                    Problema(numero, NIVEL_ARQUIVO, f"header de lote sem trailer do lote {lote_atual['numero']} anterior")
                )
            lotes_vistos += 1
            produto = produto_do_header_lote(linha)
            if produto is None:
                problemas.append(
                    Problema(numero, NIVEL_ARQUIVO, f"forma de lançamento {linha[11:13]!r} não corresponde a nenhum produto", "06.1")
                )
            cfg = spec.produto(produto) if produto else None
            chave_header = cfg["header_lote"] if cfg else "header_lote_transferencia"
            _validar_campos(linha, numero, spec.layout(chave_header), problemas, produto)

            numero_lote = int(linha[3:7])
            if numero_lote != lotes_vistos:
                problemas.append(
                    Problema(numero, NIVEL_ARQUIVO, f"lote numerado {numero_lote}, esperado {lotes_vistos}", "02.1")
                )
            if cfg and linha[13:16] != cfg["versao_layout_lote"]:
                problemas.append(
                    Problema(
                        numero,
                        NIVEL_ARQUIVO,
                        f"versão do layout do lote {linha[13:16]!r}, esperado {cfg['versao_layout_lote']!r} para {produto}",
                        "07.1",
                    )
                )
            lote_atual = {
                "numero": numero_lote,
                "produto": produto,
                "cfg": cfg,
                "registros": 1,
                "detalhes": 0,
                "nsr": 0,
                "total": Decimal("0"),
                "ja_teve_j": False,
                "inicio": numero,
            }

        elif tipo == "3":
            if lote_atual is None:
                problemas.append(Problema(numero, NIVEL_ARQUIVO, "registro de detalhe fora de um lote"))
                continue
            lote_atual["registros"] += 1
            lote_atual["detalhes"] += 1

            segmento = linha[13]
            layout = _layout_detalhe(lote_atual["produto"], segmento, lote_atual["ja_teve_j"])
            if layout is None:
                problemas.append(
                    Problema(numero, NIVEL_ARQUIVO, f"segmento {segmento!r} desconhecido", "05")
                )
                continue
            if segmento == "J":
                lote_atual["ja_teve_j"] = not lote_atual["ja_teve_j"]

            _validar_campos(linha, numero, layout, problemas, lote_atual["produto"])

            lote_atual["nsr"] += 1
            nsr_arquivo = int(linha[8:13])
            if nsr_arquivo != lote_atual["nsr"]:
                problemas.append(
                    Problema(
                        numero,
                        NIVEL_ARQUIVO,
                        f"nº sequencial no lote é {nsr_arquivo}, esperado {lote_atual['nsr']}",
                        "04",
                    )
                )
            if int(linha[3:7]) != lote_atual["numero"]:
                problemas.append(
                    Problema(numero, NIVEL_ARQUIVO, f"detalhe referencia o lote {linha[3:7]}, esperado {lote_atual['numero']:04d}", "02")
                )

            if layout.chave in _CAMPO_VALOR:
                _, campo_id = _CAMPO_VALOR[layout.chave]
                lote_atual["total"] += Decimal(str(ler_num(layout.campo(campo_id), linha)))

        elif tipo == "5":
            if lote_atual is None:
                problemas.append(Problema(numero, NIVEL_ARQUIVO, "trailer de lote sem header de lote"))
                continue
            lote_atual["registros"] += 1
            cfg = lote_atual["cfg"]
            chave_trailer = cfg["trailer_lote"] if cfg else "trailer_lote_transferencia"
            layout = spec.layout(chave_trailer)
            _validar_campos(linha, numero, layout, problemas, lote_atual["produto"])

            qtd = int(linha[17:23])
            if qtd != lote_atual["registros"]:
                problemas.append(
                    Problema(
                        numero,
                        NIVEL_ARQUIVO,
                        f"quantidade de registros do lote é {qtd}, contados {lote_atual['registros']}",
                        "05.5",
                    )
                )
            soma = Decimal(str(ler_num(layout.campo("06.5"), linha)))
            if soma != lote_atual["total"]:
                problemas.append(
                    Problema(
                        numero,
                        NIVEL_ARQUIVO,
                        f"somatória do lote é {soma}, somados {lote_atual['total']}",
                        "06.5",
                    )
                )
            if lote_atual["detalhes"] == 0:
                problemas.append(Problema(numero, NIVEL_ARQUIVO, "lote sem registros de detalhe"))
            lote_atual = None

        else:
            problemas.append(
                Problema(numero, NIVEL_ARQUIVO, f"tipo de registro {tipo!r} inesperado entre header e trailer de arquivo", "03")
            )

    if lote_atual is not None:
        problemas.append(
            Problema(len(linhas), NIVEL_ARQUIVO, f"lote {lote_atual['numero']} não foi encerrado por trailer")
        )

    trailer = linhas[-1]
    qtd_lotes = int(trailer[17:23])
    qtd_registros = int(trailer[23:29])
    if qtd_lotes != lotes_vistos:
        problemas.append(
            Problema(len(linhas), NIVEL_ARQUIVO, f"quantidade de lotes é {qtd_lotes}, contados {lotes_vistos}", "05.9")
        )
    if qtd_registros != len(linhas):
        problemas.append(
            Problema(len(linhas), NIVEL_ARQUIVO, f"quantidade de registros é {qtd_registros}, contados {len(linhas)}", "06.9")
        )

    return problemas


def validar_arquivo(caminho: str | Path, *, encoding: str = "latin-1") -> list[Problema]:
    return validar(Path(caminho).read_text(encoding=encoding))


def relatorio(problemas: Iterable[Problema]) -> str:
    problemas = list(problemas)
    if not problemas:
        return "Arquivo válido: nenhum problema encontrado."
    arquivo = [p for p in problemas if p.nivel == NIVEL_ARQUIVO]
    registro = [p for p in problemas if p.nivel == NIVEL_REGISTRO]
    partes = [
        f"{len(problemas)} problema(s): {len(arquivo)} que rejeitam o ARQUIVO, "
        f"{len(registro)} que rejeitam apenas o REGISTRO.",
        "",
    ]
    partes.extend(str(p) for p in problemas)
    return "\n".join(partes)
