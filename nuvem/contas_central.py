# -*- coding: utf-8 -*-
"""As contas do ERP num lugar só (pedido do dono, 05/10/2026).

Antes, cada aba buscava a sua lista: a abertura (para o cadastro), o Saldo
de pagamentos (para o painel, com um segundo login) e o Relatório Mensal
(pela tela do Chrome). Conta incluída num lugar era esquecida no outro.

Aqui mora a lista de contas ATIVAS do ERP lida na última atualização
(`contas_erp.json`, um cache como os outros) e o cálculo do que falta no
cadastro e no painel.

**Vazio nunca substitui cheio**, como no `cadastro.sincronizar`: ERP fora do
ar devolve lista vazia, e isso não pode apagar a lista de ontem.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import util

from . import cache, contas_novas

log = util.log(__name__)

ARQUIVO_ERP = "contas_erp.json"


def guardar_lista(crus, pasta=None) -> bool:
    """Grava a lista das contas ativas. Só grava se houver ao menos uma conta
    com id e nome; devolve se gravou."""
    contas = []
    for cru in crus or []:
        if not isinstance(cru, dict):
            continue
        conta = contas_novas.como_conta_nova(cru)
        if not (conta.id_erp and conta.nome) or cru.get("isActive") is False:
            continue
        contas.append({"id": conta.id_erp, "nome": conta.nome,
                       "banco": conta.banco, "agencia": conta.agencia,
                       "numero": conta.numero})
    if not contas:
        return False
    cache.gravar_json(ARQUIVO_ERP, {
        "lida_em": datetime.now().isoformat(timespec="seconds"),
        "contas": sorted(contas, key=lambda c: c["nome"])}, pasta)
    return True


def ler_lista(pasta=None) -> list[dict]:
    contas = cache.ler_json(ARQUIVO_ERP, pasta).get("contas")
    if not isinstance(contas, list):
        return []
    return [c for c in contas if isinstance(c, dict) and c.get("nome")]


def mapa_do_painel(pasta_painel=None):
    """O `mapping.yaml` do painel, ou None se esta máquina não tem painel."""
    base = Path(pasta_painel or util.pasta_base())
    if not ((base / "mapping.yaml").exists() and (base / "config.yaml").exists()):
        return None
    try:
        from conciliacao.mapping import AccountMapping
        return AccountMapping.load(base / "mapping.yaml")
    except Exception:                                   # noqa: BLE001
        log.warning("lendo o mapping.yaml do painel", exc_info=True)
        return None


def _fora_do_painel(contas, mapa):
    from conciliacao.painel_novas import contas_fora_do_painel
    return contas_fora_do_painel(contas, mapa)


@dataclass
class Pendencia:
    conta: "contas_novas.ContaNova"
    erp: object                      # conciliacao.models.ErpAccount
    falta_cadastro: bool
    falta_painel: bool
    rotulo: str = ""

    nome = property(lambda s: s.conta.nome)
    banco = property(lambda s: s.conta.banco)
    agencia = property(lambda s: s.conta.agencia)
    numero = property(lambda s: s.conta.numero)
    resumo = property(lambda s: s.conta.resumo)
    pasta_sugerida = property(lambda s: s.conta.pasta_sugerida)

    def empresa_sugerida(self, nomes) -> str:
        return self.conta.empresa_sugerida(nomes)

    @property
    def falta_em(self) -> str:
        if self.falta_cadastro and self.falta_painel:
            return "cadastro e painel"
        return "cadastro" if self.falta_cadastro else "painel"


def pendencias(crus, pasta=None, pasta_painel=None) -> list[Pendencia]:
    """O que falta no cadastro (Supabase) e/ou no painel, por conta ativa."""
    from conciliacao.erp.api import conta_do_erp
    from conciliacao.painel_novas import rotulo_sugerido

    ativas = [c for c in (crus or []) if isinstance(c, dict)
              and c.get("isActive") is not False and c.get("name")]
    sem_cadastro = {n.id_erp for n in contas_novas.comparar(
        ativas, contas_novas.nomes_cadastrados(pasta),
        contas_novas.ignorados(pasta_painel or pasta))}
    mapa = mapa_do_painel(pasta_painel)
    erps = [conta_do_erp(c) for c in ativas]
    sem_painel = ({c.id for c in _fora_do_painel(erps, mapa)}
                  if mapa is not None else set())
    saida = []
    for cru, erp in zip(ativas, erps):
        fc, fp = erp.id in sem_cadastro, erp.id in sem_painel
        if fc or fp:
            saida.append(Pendencia(contas_novas.como_conta_nova(cru), erp,
                                   fc, fp, rotulo_sugerido(erp)))
    return sorted(saida, key=lambda p: p.nome)
