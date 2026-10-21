# -*- coding: utf-8 -*-
"""Passo 2 da tela do dia: por linha do painel, o que VAI SAIR e o que está
BLOQUEADO. "A pagar" = o que vai sair — deixa de ser "tudo em aberto".

Quem decide é a apuração da Remessa: vai sair = linha que ENTRA e nasce
marcada (`confirmacao.marcada_de_inicio`: o já enviado nasce desmarcado, o
rejeitado volta marcado). Conta do ERP sem linha utilizável no painel NÃO
some: vai para `fora`, com o motivo.

Duas perguntas diferentes, que não se misturam:

- **gera de novo?** Só `saem` (vai sair + liberados + à mão). O já enviado em
  remessa viva NÃO entra em planilha, HTML nem remessa (`ids_que_nao_saem`):
  gerá-lo de novo é o mesmo pagamento duas vezes;
- **sai da conta?** `a_pagar` = `saem` + `ja_enviados`. O já enviado ainda
  está em aberto no ERP (a leitura só traz o que não foi pago), então o banco
  ainda vai debitá-lo: fora do a pagar, o D do painel, o D do Excel e o aporte
  mínimo sairiam baixos. Bloqueado de verdade = não apto, que não sai.

Ponto de extensão da entrega 2: `liberados` (bloqueado que o dono libera, com
motivo) e `a_mao` (pagamento à mão) já somam no `a_pagar`; hoje nascem vazios.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from pagamentos_dia import confirmacao

from .valores import de_float

ZERO = Decimal("0.00")
FORA_POR_CONFIGURACAO = "conta fora do painel (lista de ignoradas do mapping.yaml)"
SEM_LINHA = 'conta do ERP sem linha no painel — inclua pelo "Atualizar contas"'
LINHA_FORA_DO_ERP = "linha do painel marcada como fora do ERP"


@dataclass(frozen=True)
class Pagamento:
    id: str
    conta_erp: str
    favorecido: str
    valor: Decimal
    situacao: str
    estado: str

    @classmethod
    def da_linha(cls, ln) -> "Pagamento":
        return cls(id=ln.id, conta_erp=ln.conta, favorecido=ln.quem_recebe,
                   valor=de_float(ln.valor), situacao=ln.situacao, estado=ln.estado)


@dataclass
class PagamentosDaConta:
    rotulo: str
    linha: int | None
    vao_sair: list = field(default_factory=list)
    bloqueados: list = field(default_factory=list)
    #: Enviados em remessa e ainda em aberto no ERP: não se geram de novo,
    #: mas o dinheiro ainda sai da conta — somam no `a_pagar`.
    ja_enviados: list = field(default_factory=list)
    liberados: list = field(default_factory=list)     # entrega 2
    a_mao: list = field(default_factory=list)         # entrega 2
    motivo_fora: str = ""

    @property
    def saem(self) -> list:
        """O que se GERA hoje (planilha, HTML, remessa)."""
        return [*self.vao_sair, *self.liberados, *self.a_mao]

    @property
    def debitam(self) -> list:
        """O que sai da conta: o que se gera hoje + o já enviado em aberto."""
        return [*self.saem, *self.ja_enviados]

    @property
    def a_pagar(self) -> Decimal:
        return sum((p.valor for p in self.debitam), ZERO)

    @property
    def qtd_a_pagar(self) -> int:
        return len(self.debitam)

    @property
    def valor_ja_enviado(self) -> Decimal:
        return sum((p.valor for p in self.ja_enviados), ZERO)

    @property
    def valor_bloqueado(self) -> Decimal:
        return sum((p.valor for p in self.bloqueados), ZERO)


def por_conta(grupos, mapping):
    painel: dict[int, PagamentosDaConta] = {}
    fora: dict[str, PagamentosDaConta] = {}

    def _fora(conta: str, motivo: str) -> PagamentosDaConta:
        return fora.setdefault(conta, PagamentosDaConta(conta, None, motivo_fora=motivo))

    for g in grupos:
        if mapping.is_ignored(g.conta):
            destino = _fora(g.conta, FORA_POR_CONFIGURACAO)
        else:
            row = mapping.resolve_label(g.conta)
            if row is None:
                destino = _fora(g.conta, SEM_LINHA)
            elif not row.exists_in_erp:
                destino = _fora(g.conta, LINHA_FORA_DO_ERP)
            else:
                destino = painel.setdefault(row.row, PagamentosDaConta(row.label, row.row))
        for ln in g.entram:
            if confirmacao.marcada_de_inicio(ln):
                alvo = destino.vao_sair
            elif _ja_enviado(ln):
                alvo = destino.ja_enviados
            else:
                alvo = destino.bloqueados
            alvo.append(Pagamento.da_linha(ln))
        destino.bloqueados.extend(Pagamento.da_linha(ln) for ln in g.nao_aptos)
    return painel, list(fora.values())


def _ja_enviado(ln) -> bool:
    """Entra, já saiu numa remessa e o envio não foi rejeitado — a mesma
    pergunta que `confirmacao.marcada_de_inicio` faz para desmarcá-la."""
    return bool(ln.marcavel and getattr(ln.candidato, "ja_enviado", "")
                and not ln.envio_rejeitado)


def ids_que_nao_saem(grupos) -> set[str]:
    """Os que ENTRAM mas nascem desmarcados (já enviados) — o que a janela da
    Remessa desmarcaria sozinha. É o `ids_nao_confirmados` do `remontar`."""
    return {ln.id for g in grupos for ln in g.entram
            if ln.id and not confirmacao.marcada_de_inicio(ln)}


def totais_para_o_painel(painel) -> dict[int, tuple[Decimal, int]]:
    """{linha: (a pagar, quantos)} — o `aggregates` do `build_row_fills`."""
    return {row: (c.a_pagar, c.qtd_a_pagar) for row, c in painel.items()}
