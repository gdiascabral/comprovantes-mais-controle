# -*- coding: utf-8 -*-
"""Passo 1 da tela do dia: saldo do sistema × saldo do banco, por conta.

O ajuste NUNCA apaga o que foi lido: ele fica ao lado (`original`) e vale só
no dia (o arquivo do dia é por data, ver `dia_de_trabalho`). Se o ERP mudar o
saldo depois do ajuste, a linha avisa em vez de esconder — simulação feita
sobre um número que já não é o do sistema é o tipo de engano que só aparece
quando o dinheiro falta.

O saldo do dia (coluna C do Excel) é o do BANCO — o digitado, senão o lido do
Sicoob —; senão, o do SISTEMA com o ajuste (decisão do dono). O digitado vale
sobre o lido; se o Sicoob ler um valor diferente DEPOIS do ajuste, a linha
avisa (`banco_mudou`), como faz quando o sistema muda.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from conciliacao.rules import resolve_balances

from .valores import brl

SISTEMA = "sistema"
BANCO = "banco"
_PESO = {"erro": 0, "atencao": 1, "info": 2, "ok": 3}


@dataclass(frozen=True)
class Ajuste:
    valor: Decimal
    original: Decimal | None
    motivo: str = ""
    quando: str = ""


@dataclass(frozen=True)
class LinhaSaldo:
    linha: int
    rotulo: str
    sistema: Decimal | None
    banco: Decimal | None = None          # lido do banco (entrega 4: Sicoob)
    ajuste_sistema: Ajuste | None = None
    ajuste_banco: Ajuste | None = None
    #: Por que o banco não foi lido (conta do Sicoob que falhou). Vazio para
    #: as contas digitadas à mão — o "sem o saldo do banco" de sempre. Por
    #: ÚLTIMO e com default: há quem construa a linha por posição.
    nota_banco: str = ""

    @property
    def sistema_usado(self) -> Decimal | None:
        return self.ajuste_sistema.valor if self.ajuste_sistema else self.sistema

    @property
    def banco_usado(self) -> Decimal | None:
        return self.ajuste_banco.valor if self.ajuste_banco else self.banco

    @property
    def diferenca(self) -> Decimal | None:
        if self.sistema_usado is None or self.banco_usado is None:
            return None
        return self.banco_usado - self.sistema_usado

    @property
    def saldo_do_dia(self) -> Decimal | None:
        """O que vai para a coluna C: o banco, quando há; senão o sistema."""
        banco = self.banco_usado
        return banco if banco is not None else self.sistema_usado

    @property
    def original_mudou(self) -> bool:
        a = self.ajuste_sistema
        return a is not None and a.original != self.sistema

    @property
    def banco_mudou(self) -> bool:
        """O LIDO mudou depois do ajuste do banco (ex.: digitou antes de o
        Sicoob ser lido). O digitado continua valendo — a spec manda o ajuste
        mandar no dia —, mas a linha avisa, como `original_mudou` faz com o
        sistema."""
        a = self.ajuste_banco
        return (a is not None and self.banco is not None
                and a.original != self.banco and a.valor != self.banco)

    def situacao(self) -> tuple[str, str]:
        if self.sistema_usado is None:
            return "erro", "o sistema não trouxe o saldo"
        if self.original_mudou:
            return "atencao", (f"o sistema mudou desde o ajuste: era "
                               f"{brl(self.ajuste_sistema.original)}, agora {brl(self.sistema)}")
        if self.banco_usado is None:
            if self.nota_banco:
                return "atencao", self.nota_banco
            return "info", "sem o saldo do banco"
        aviso = (f" · o banco leu {brl(self.banco)} depois do seu ajuste"
                 if self.banco_mudou else "")
        dif = self.diferenca
        if dif == 0:
            return ("atencao", "bate com o digitado" + aviso) if aviso else ("ok", "bate")
        return "erro", f"não bate — diferença de {brl(dif)}{aviso}"

    def situacao_curta(self) -> tuple[str, str]:
        """A `situacao()` que cabe na coluna SITUAÇÃO a 1280 px (no máximo
        ~20 letras). A mesma tag; a frase inteira vai no `detalhe()`. "Não
        bate" sem o valor: a DIFERENÇA é a coluna ao lado."""
        tag, _frase = self.situacao()
        if self.sistema_usado is None:
            return tag, "sem saldo do sistema"
        if self.original_mudou:
            return tag, "o sistema mudou"
        if self.banco_usado is None:
            return tag, "banco não lido" if self.nota_banco else "sem saldo do banco"
        if self.diferenca == 0:
            return tag, "o banco mudou" if self.banco_mudou else "bate"
        # Com o banco relido depois do ajuste, o aviso fica só no detalhe: o
        # que a linha tem de gritar é "não bate", e as duas não cabem.
        return tag, "não bate"

    def detalhe(self) -> str:
        """A frase inteira da situação e, de cada valor digitado, o original e
        o motivo — o que a célula curta (`celula`) deixa de mostrar."""
        partes = [self.situacao()[1]]
        for nome, aj in (("sistema", self.ajuste_sistema), ("banco", self.ajuste_banco)):
            if aj is None:
                continue
            era = brl(aj.original) if aj.original is not None else "sem leitura"
            motivo = f" · {aj.motivo}" if aj.motivo else ""
            partes.append(f"{nome} digitado {brl(aj.valor)} (era {era}{motivo})")
        return f"{self.rotulo}: " + "; ".join(partes)


#: Marca da célula com valor digitado (o original está no `detalhe`).
MARCA_EDITADO = "✎"


def celula(lido, ajuste: Ajuste | None) -> str:
    """O valor da célula SISTEMA/BANCO: o usado, com a marca se foi digitado.
    O "(era …)" ao lado cortava a coluna a 1280 px; ele vai no `detalhe`."""
    if ajuste is None:
        return brl(lido)
    return f"{brl(ajuste.valor)} {MARCA_EDITADO}"


def montar_saldos(contas, mapping) -> list[LinhaSaldo]:
    """Uma linha por conta VIVA do painel, na ordem das linhas. Mesma régua do
    painel antigo (`resolve_balances`): não há segunda lista de contas."""
    res = resolve_balances(contas, mapping)
    return [LinhaSaldo(linha=r.row, rotulo=r.label, sistema=res.balances.get(r.row))
            for r in sorted(mapping.live_rows, key=lambda r: r.row)]


def aplicar_ajustes(linhas, ajustes: dict) -> list[LinhaSaldo]:
    saida = []
    for ln in linhas:
        do_rotulo = ajustes.get(ln.rotulo) or {}
        saida.append(replace(ln, ajuste_sistema=do_rotulo.get(SISTEMA),
                             ajuste_banco=do_rotulo.get(BANCO)))
    return saida


def novo_ajuste(linha: LinhaSaldo, campo: str, valor: Decimal,
                motivo: str = "", quando: str = "") -> Ajuste:
    if campo not in (SISTEMA, BANCO):
        raise ValueError(f"campo desconhecido: {campo!r}")
    original = linha.sistema if campo == SISTEMA else linha.banco
    return Ajuste(valor=valor, original=original,
                  motivo=str(motivo or "").strip()[:200], quando=quando)


def ordenar(linhas) -> list[LinhaSaldo]:
    """O que não bate (e o não lido) sobe; depois atenção; depois o resto."""
    return sorted(linhas, key=lambda ln: (_PESO[ln.situacao()[0]], ln.linha))
