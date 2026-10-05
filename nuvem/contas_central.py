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



def ler_do_erp(pasta=None, log=print) -> list:
    """Lê as contas ativas do ERP (por HTTP), guarda e devolve as cruas.

    Lista vazia quando o ERP não respondeu, e aí a lista guardada de antes
    fica onde está (`guardar_lista` não grava vazio). Quem chama decide o que
    fazer com o vazio; apagar a lista de ontem nunca é uma das opções.
    """
    crus = contas_novas.contas_do_erp(log=log)
    guardar_lista(crus, pasta)
    return crus


def avisar_abas(quadros: dict, log=print) -> None:
    """Avisa as abas que a lista de contas mudou.

    Só as que têm o gancho `recarregar_contas`; as outras não usam a lista.
    Cada uma num `try` próprio: uma aba que quebra ao recarregar não pode
    deixar as seguintes com a lista velha, e o motivo vai para o log.
    """
    for nome, quadro in (quadros or {}).items():
        recarregar = getattr(quadro, "recarregar_contas", None)
        if recarregar is None:
            continue
        try:
            recarregar()
        except Exception as e:                          # noqa: BLE001
            log(f"aba {nome}: não recarregou as contas ({e})")

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


def aplicar(token: str, respostas, crus: list, pasta_painel=None) -> str:
    """Grava o que a janela única devolveu: cadastro primeiro, painel depois.

    Devolve o texto do recado. O painel recusado nunca desfaz o cadastro (são
    dois lugares diferentes, o da nuvem já valeu) e nunca levanta: o motivo
    entra no recado. Erro de rede/SQL do cadastro sobe, e o chamador mostra.
    """
    # Módulos buscados na hora da chamada (e não `from ... import`), para o
    # teste poder trocar `gravar` e `incluir_no_painel`.
    from conciliacao import painel_novas
    from conciliacao.erp.api import conta_do_erp

    partes: list[str] = []
    if respostas.cadastro:
        avisos = contas_novas.gravar(token, respostas.cadastro)
        feitas = max(len(respostas.cadastro) - len(avisos), 0)
        partes.append(f"{feitas} conta(s) cadastrada(s).")
        if avisos:
            partes.append("Não gravadas no cadastro:\n" + "\n".join(avisos))
    if respostas.painel:
        try:
            inclusoes = [painel_novas.Inclusao(p.erp, rotulo)
                         for p, rotulo in respostas.painel]
            contas_erp = [conta_do_erp(c) for c in crus if isinstance(c, dict)]
            res = painel_novas.incluir_no_painel(
                Path(pasta_painel or util.pasta_base()), inclusoes, contas_erp)
        except painel_novas.InclusaoRecusada as e:
            partes.append(f"O painel do Saldo NÃO mudou:{chr(10)}{e}")
        except Exception as e:                          # noqa: BLE001
            # O cadastro já foi gravado: o recado tem de chegar inteiro, senão
            # a pessoa tenta de novo e duplica.
            log.warning("incluindo no painel do Saldo", exc_info=True)
            partes.append(f"O painel do Saldo NÃO mudou:{chr(10)}{e}")
        else:
            numeros = sorted(n for n, _ in res.linhas)
            if len(numeros) == 1:
                onde = f"linha {numeros[0]}"
            else:
                onde = f"linhas {numeros[0]} a {numeros[-1]}"
            partes.append(f"{len(res.linhas)} conta(s) incluída(s) no painel "
                          f"do Saldo ({onde}).")
            partes.append("Quem aporta em cada uma é a aba Regras do "
                          "MODELO.xlsx.")
    return "\n".join(partes)
