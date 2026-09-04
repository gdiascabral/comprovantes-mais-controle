"""Leitura do arquivo de retorno CNAB 240.

O retorno é o mesmo arquivo enviado com os códigos de ocorrência gravados nas
posições 231-240 de cada registro, mais o segmento Z de autenticação nos
pagamentos processados com sucesso.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Iterator, Sequence

from . import spec
from .campos import ler, ler_data, ler_num
from .dominios import (
    OCORRENCIAS_PENDENTES,
    OCORRENCIAS_SUCESSO,
    decodificar_ocorrencias,
    sucesso as _ocorrencia_sucesso,
)
from .registros import desmontar
from .spec import Layout
from .validador import _layout_detalhe, produto_do_header_lote

#: layout -> (seu número, nome, valor, data de pagamento, nosso número)
_CAMPOS_PAGAMENTO: dict[str, tuple[str, str, str, str, str]] = {
    "segmento_a": ("16.3A", "15.3A", "20.3A", "17.3A", "21.3A"),
    "segmento_j": ("17.3J", "09.3J", "15.3J", "14.3J", "18.3J"),
    "segmento_o": ("13.3O", "09.3O", "12.3O", "11.3O", "14.3O"),
    "segmento_n": ("08.3N", "10.3N", "12.3N", "11.3N", "09.3N"),
}


class RetornoInvalido(ValueError):
    pass


@dataclass
class Registro:
    numero_linha: int
    tipo: str
    lote: int
    segmento: str | None
    layout: Layout | None
    linha: str

    @property
    def campos(self) -> dict[str, str]:
        if self.layout is None:
            return {}
        return desmontar(self.layout, self.linha)

    @property
    def _campo_ocorrencias(self) -> str:
        """Só alguns segmentos têm G059 em 231-240.

        No segmento B de transferência as posições 231-232 são o Código da UG
        Centralizadora, e no J-52-Pix as 211-240 são o TXID — ler ocorrências
        ali produziria códigos fantasma.
        """
        if self.layout is None:
            return ""
        for campo in self.layout.campos:
            if campo.ref == "G059" and campo.de == 231:
                return self.linha[230:240]
        return ""

    @property
    def ocorrencias(self) -> list[tuple[str, str]]:
        return decodificar_ocorrencias(self._campo_ocorrencias)

    @property
    def sucesso(self) -> bool:
        return _ocorrencia_sucesso(self._campo_ocorrencias)

    def valor(self, campo_id: str) -> str:
        if self.layout is None:
            raise RetornoInvalido(f"linha {self.numero_linha} sem layout resolvido")
        return ler(self.layout.campo(campo_id), self.linha)


@dataclass
class ResultadoPagamento:
    """Visão consolidada de um pagamento no retorno."""

    lote: int
    nsr: int
    segmento: str
    seu_numero: str
    nosso_numero: str
    favorecido: str
    valor: Decimal
    data_pagamento: _dt.date | None
    ocorrencias: list[tuple[str, str]]
    autenticacao: str = ""
    protocolo: str = ""
    valor_real: Decimal | None = None
    data_real: _dt.date | None = None

    @property
    def codigos(self) -> list[str]:
        return [c for c, _ in self.ocorrencias]

    @property
    def sucesso(self) -> bool:
        """Confirmado ou agendado com sucesso (00, BD, 68)."""
        return bool(self.codigos) and all(c in OCORRENCIAS_SUCESSO for c in self.codigos)

    @property
    def pendente(self) -> bool:
        """Aguardando ação do usuário — PD, transação pendente de assinatura."""
        return any(c in OCORRENCIAS_PENDENTES for c in self.codigos)

    @property
    def rejeitado(self) -> bool:
        return bool(self.codigos) and not self.sucesso and not self.pendente

    @property
    def sem_ocorrencia(self) -> bool:
        """Registro sem código nas posições 231-240 — nem confirmado, nem rejeitado."""
        return not self.ocorrencias

    def __str__(self) -> str:
        motivos = "; ".join(f"{c}={d}" for c, d in self.ocorrencias)
        if self.sem_ocorrencia:
            estado, motivos = "  ? ", "sem ocorrência informada"
        elif self.sucesso:
            estado = " OK "
        elif self.pendente:
            estado = "PEND"
        else:
            estado = "ERRO"
        return (
            f"[{estado}] lote {self.lote} nsr {self.nsr} {self.segmento} "
            f"{self.favorecido.strip()[:30]:30} R$ {self.valor:>12,.2f}  {motivos}"
        )


@dataclass
class LoteRetorno:
    numero: int
    produto: str | None
    tipo_servico: str
    forma_lancamento: str
    header: Registro
    detalhes: list[Registro] = field(default_factory=list)
    trailer: Registro | None = None

    @property
    def total(self) -> Decimal:
        if self.trailer is None or self.trailer.layout is None:
            return Decimal("0")
        return Decimal(str(ler_num(self.trailer.layout.campo("06.5"), self.trailer.linha)))


@dataclass
class ArquivoRetorno:
    header: Registro
    lotes: list[LoteRetorno]
    trailer: Registro

    # -- metadados ----------------------------------------------------------

    @property
    def empresa(self) -> str:
        return self.header.valor("13.0").strip()

    @property
    def convenio(self) -> str:
        return self.header.valor("07.0").strip()

    @property
    def agencia(self) -> str:
        """Agência mantenedora da conta (08.0), sem os zeros de enchimento.

        O header do retorno diz de que CONTA ele fala, e quem lê 18 retornos
        no mesmo dia precisa disso para saber qual é qual — o convênio é do
        contrato, não da conta. Sem os zeros porque o layout enche à esquerda
        e ninguém escreve "04321" ao falar da agência.
        """
        return self.header.valor("08.0").strip().lstrip("0")

    @property
    def conta(self) -> str:
        """Número da conta corrente (10.0), sem os zeros de enchimento."""
        return self.header.valor("10.0").strip().lstrip("0")

    @property
    def nsa(self) -> int:
        return int(self.header.valor("19.0"))

    @property
    def data_geracao(self) -> _dt.date | None:
        return ler_data(spec.layout("header_arquivo").campo("17.0"), self.header.linha)

    @property
    def e_retorno(self) -> bool:
        return self.header.valor("16.0") == "2"

    # -- consulta -----------------------------------------------------------

    def pagamentos(self) -> Iterator[ResultadoPagamento]:
        for lote in self.lotes:
            pendente: ResultadoPagamento | None = None
            for registro in lote.detalhes:
                if registro.layout is None:
                    continue
                chave = registro.layout.chave

                if chave == "segmento_z":
                    if pendente is not None:
                        pendente.autenticacao = registro.valor("06.3Z").strip()
                        pendente.protocolo = registro.valor("07.3Z").strip()
                        # Ocorrências do Z complementam as do pagamento.
                        for oc in registro.ocorrencias:
                            if oc not in pendente.ocorrencias:
                                pendente.ocorrencias.append(oc)
                    continue

                if chave not in _CAMPOS_PAGAMENTO:
                    # Segmentos acessórios (B, J-52, W) herdam as ocorrências
                    # para o pagamento a que pertencem.
                    if pendente is not None:
                        for oc in registro.ocorrencias:
                            if oc not in pendente.ocorrencias:
                                pendente.ocorrencias.append(oc)
                    continue

                if pendente is not None:
                    yield pendente

                pendente = self._resultado(lote, registro, chave)

            if pendente is not None:
                yield pendente

    def _resultado(self, lote: LoteRetorno, registro: Registro, chave: str) -> ResultadoPagamento:
        layout = registro.layout
        assert layout is not None
        id_seu, id_nome, id_valor, id_data, id_nosso = _CAMPOS_PAGAMENTO[chave]

        resultado = ResultadoPagamento(
            lote=lote.numero,
            nsr=int(registro.linha[8:13]),
            segmento=registro.segmento or "",
            seu_numero=ler(layout.campo(id_seu), registro.linha).strip(),
            nosso_numero=ler(layout.campo(id_nosso), registro.linha).strip(),
            favorecido=ler(layout.campo(id_nome), registro.linha),
            valor=Decimal(str(ler_num(layout.campo(id_valor), registro.linha))),
            data_pagamento=ler_data(layout.campo(id_data), registro.linha),
            ocorrencias=registro.ocorrencias,
        )
        if chave == "segmento_a":
            resultado.data_real = ler_data(layout.campo("22.3A"), registro.linha)
            valor_real = Decimal(str(ler_num(layout.campo("23.3A"), registro.linha)))
            resultado.valor_real = valor_real or None
        return resultado

    def resumo(self) -> dict[str, object]:
        pagamentos = list(self.pagamentos())
        ok = [p for p in pagamentos if p.sucesso]
        erro = [p for p in pagamentos if p.rejeitado]
        pendentes = [p for p in pagamentos if p.pendente]
        motivos: dict[str, int] = {}
        for p in erro:
            for codigo, descricao in p.ocorrencias:
                motivos[f"{codigo} - {descricao}"] = motivos.get(f"{codigo} - {descricao}", 0) + 1
        return {
            "empresa": self.empresa,
            "convenio": self.convenio,
            "nsa": self.nsa,
            "data_geracao": self.data_geracao,
            "lotes": len(self.lotes),
            "pagamentos": len(pagamentos),
            "confirmados": len(ok),
            "rejeitados": len(erro),
            "pendentes": len(pendentes),
            "sem_ocorrencia": len(pagamentos) - len(ok) - len(erro) - len(pendentes),
            "valor_confirmado": sum((p.valor for p in ok), Decimal("0")),
            "valor_rejeitado": sum((p.valor for p in erro), Decimal("0")),
            "motivos": dict(sorted(motivos.items(), key=lambda kv: -kv[1])),
        }


def ler_retorno(conteudo: str | Sequence[str]) -> ArquivoRetorno:
    if isinstance(conteudo, str):
        linhas = [l for l in conteudo.replace("\r\n", "\n").split("\n") if l.strip()]
    else:
        linhas = [l for l in conteudo if l.strip()]

    if len(linhas) < 2:
        raise RetornoInvalido("arquivo com menos de duas linhas")
    if linhas[0][7] != "0" or linhas[-1][7] != "9":
        raise RetornoInvalido("arquivo não começa com header (0) e termina com trailer (9) de arquivo")

    header = Registro(1, "0", 0, None, spec.layout("header_arquivo"), linhas[0])
    trailer = Registro(len(linhas), "9", 9999, None, spec.layout("trailer_arquivo"), linhas[-1])

    lotes: list[LoteRetorno] = []
    atual: LoteRetorno | None = None
    ja_teve_j = False

    for numero, linha in enumerate(linhas[1:-1], start=2):
        tipo = linha[7]
        numero_lote = int(linha[3:7])

        if tipo == "1":
            produto = produto_do_header_lote(linha)
            cfg = spec.produto(produto) if produto else None
            layout = spec.layout(cfg["header_lote"] if cfg else "header_lote_transferencia")
            atual = LoteRetorno(
                numero=numero_lote,
                produto=produto,
                tipo_servico=linha[9:11],
                forma_lancamento=linha[11:13],
                header=Registro(numero, tipo, numero_lote, None, layout, linha),
            )
            lotes.append(atual)
            ja_teve_j = False

        elif tipo == "3":
            if atual is None:
                raise RetornoInvalido(f"linha {numero}: detalhe fora de lote")
            segmento = linha[13]
            layout = _layout_detalhe(atual.produto, segmento, ja_teve_j)
            if segmento == "J":
                ja_teve_j = not ja_teve_j
            atual.detalhes.append(Registro(numero, tipo, numero_lote, segmento, layout, linha))

        elif tipo == "5":
            if atual is None:
                raise RetornoInvalido(f"linha {numero}: trailer de lote sem header")
            cfg = spec.produto(atual.produto) if atual.produto else None
            layout = spec.layout(cfg["trailer_lote"] if cfg else "trailer_lote_transferencia")
            atual.trailer = Registro(numero, tipo, numero_lote, None, layout, linha)
            atual = None

    return ArquivoRetorno(header=header, lotes=lotes, trailer=trailer)


def ler_arquivo_retorno(caminho: str | Path, *, encoding: str = "latin-1") -> ArquivoRetorno:
    return ler_retorno(Path(caminho).read_text(encoding=encoding))
