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

Entrega 2 (a conferência do passo 2, `tela_do_dia.conferencia`):

- `liberados`: bloqueado (não apto OU já enviado) que o dono liberou, com
  motivo. O liberado de já enviado SAI de `ja_enviados` e entra aqui: soma
  uma vez só no `a_pagar` (era "já enviado" e agora é gerado de novo);
- `a_mao`: pagamento à mão, chave "mao:<n>" (nunca o id do lançamento do
  link, que pode estar na lista do dia);
- `desmarcados`: o que ia sair e o dono tirou. Não soma em nada (nem no
  `a_pagar`): é o que `geracao.resultado_da_tela` põe nos omitidos.

Regra de ouro: `saem` é, id a id, o `geracao.chaves_que_saem` do resultado
que vai para planilha, HTML e remessa; `a_pagar` = `saem` + `ja_enviados`
(o já enviado ainda não pago). Os dois lados leem as mesmas decisões; quem
muda um muda o outro (teste `test_a_tela_e_os_arquivos_concordam`).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    #: "" (do ERP), "liberado", "editado" ou "a_mao": de onde veio a decisão.
    origem: str = ""
    #: Texto curto para a tabela: o que o dono mudou ("editado: descricao").
    nota: str = ""

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
    #: Tirados pelo dono: NÃO somam (nem em `saem` nem em `debitam`).
    desmarcados: list = field(default_factory=list)
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


def por_conta(grupos, mapping, conferencia=None):
    """{linha do painel: contas} e as contas de fora. `conferencia`
    (`tela_do_dia.conferencia.Conferencia`) põe na conta o que o dono liberou,
    desmarcou, editou e pagou à mão; `None` (ou vazia) = entrega 1."""
    painel: dict[int, PagamentosDaConta] = {}
    fora: dict[str, PagamentosDaConta] = {}
    decisoes = conferencia.decisoes if conferencia is not None else {}

    def _destino(conta: str) -> PagamentosDaConta:
        if mapping.is_ignored(conta):
            return fora.setdefault(conta, PagamentosDaConta(conta, None, motivo_fora=FORA_POR_CONFIGURACAO))
        row = mapping.resolve_label(conta)
        if row is None:
            return fora.setdefault(conta, PagamentosDaConta(conta, None, motivo_fora=SEM_LINHA))
        if not row.exists_in_erp:
            return fora.setdefault(conta, PagamentosDaConta(conta, None, motivo_fora=LINHA_FORA_DO_ERP))
        return painel.setdefault(row.row, PagamentosDaConta(row.label, row.row))

    def _pag(ln, d, origem=""):
        p = Pagamento.da_linha(ln)
        if origem == "liberado":
            p = replace(p, situacao=f"liberado · {d.motivo_liberacao} (era: {ln.situacao})")
        if d is not None and d.editado:
            origem = origem or "editado"
            p = replace(p, nota="editado: " + ", ".join(sorted(d.edicoes)))
        return replace(p, origem=origem)

    for g in grupos:
        destino = _destino(g.conta)
        for ln in g.entram:
            d = decisoes.get(ln.id)
            if confirmacao.marcada_de_inicio(ln):
                if d is not None and d.desmarcado:
                    destino.desmarcados.append(_pag(ln, d))
                else:
                    destino.vao_sair.append(_pag(ln, d))
            elif _ja_enviado(ln):
                if d is not None and d.liberado:
                    destino.liberados.append(_pag(ln, d, "liberado"))
                else:
                    destino.ja_enviados.append(_pag(ln, d))
            else:
                destino.bloqueados.append(_pag(ln, d))
        for ln in g.nao_aptos:
            d = decisoes.get(ln.id)
            if d is not None and d.liberado:
                destino.liberados.append(_pag(ln, d, "liberado"))
            else:
                destino.bloqueados.append(Pagamento.da_linha(ln))
    for m in (conferencia.a_mao if conferencia is not None else ()):
        _destino(m.conta).a_mao.append(Pagamento(
            id=m.alvo, conta_erp=m.conta, favorecido=m.favorecido or "(à mão)", valor=m.valor,
            situacao=f"à mão · {m.motivo}", estado="atencao", origem="a_mao"))
    for c in [*painel.values(), *fora.values()]:
        c.liberados.sort(key=lambda p: p.id)
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
