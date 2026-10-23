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

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import util

from . import cache, contas_novas, rest

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
    #: As contas do cadastro com o MESMO número e outro nome (a conta foi
    #: renomeada no ERP, ver `contas_novas.renomeacoes`). Vazia = conta nova.
    antes: list = field(default_factory=list)

    nome = property(lambda s: s.conta.nome)
    banco = property(lambda s: s.conta.banco)
    agencia = property(lambda s: s.conta.agencia)
    numero = property(lambda s: s.conta.numero)
    resumo = property(lambda s: s.conta.resumo)
    pasta_sugerida = property(lambda s: s.conta.pasta_sugerida)

    def empresa_sugerida(self, nomes) -> str:
        return self.conta.empresa_sugerida(nomes)

    @property
    def renomeada(self):
        """A conta do cadastro que esta é, com outro nome; None se não há UMA
        só (nova, ou o número bate com mais de uma) ou se a linha do cadastro
        é disputada por mais de uma conta do ERP."""
        if len(self.antes) != 1 or self.antes[0].get("disputada"):
            return None
        return self.antes[0]

    @property
    def conferida(self) -> bool:
        """Renomeação com número do campo da conta e banco e agência batendo
        dos dois lados: a única que a janela traz marcada."""
        r = self.renomeada
        return bool(r is not None and r.get("conferida"))

    @property
    def falta_em(self) -> str:
        if self.falta_cadastro and self.antes:
            if any(c.get("disputada") for c in self.antes):
                texto = contas_novas.RECADO_DISPUTADA
            elif self.renomeada is not None:
                texto = (f"nome mudou no ERP: antes "
                         f"'{self.renomeada.get('nome_erp') or '(sem nome)'}'")
                if not self.conferida:
                    texto += (" — confira: o número bate, mas banco, agência "
                              "ou a origem do número não foram conferidos")
            else:
                texto = (f"nome mudou no ERP? o número bate com "
                         f"{len(self.antes)} contas do cadastro")
            return texto + (" (e falta no painel)" if self.falta_painel else "")
        if self.falta_cadastro and self.falta_painel:
            return "cadastro e painel"
        return "cadastro" if self.falta_cadastro else "painel"


def pendencias(crus, pasta=None, pasta_painel=None,
               cadastradas=None) -> list[Pendencia]:
    """O que falta no cadastro (Supabase) e/ou no painel, por conta ativa.

    `cadastradas` é a tabela `conta` da nuvem (`contas_novas.
    contas_cadastradas`): com ela, a conta que só mudou de NOME no ERP vem
    com `antes` preenchido, e o "Incluir" corrige o nome em vez de inserir.
    Sem ela (None, nuvem muda), segue como nova.

    A conta ignorada pelo botão "Ignorar" da janela some inteira — também da
    pendência só de painel: "ela não aparece mais nesta janela"."""
    from conciliacao.erp.api import conta_do_erp
    from conciliacao.painel_novas import rotulo_sugerido

    ignorar = contas_novas.ignorados(pasta_painel or pasta)
    locais = [p for p in ignorar if isinstance(p, contas_novas.NomeInteiro)]
    todas = [c for c in (crus or []) if isinstance(c, dict)
             and c.get("isActive") is not False and c.get("name")]
    # A renomeação olha TODAS as ativas, ignoradas inclusive: uma conta
    # ignorada com o nome antigo (ou com o mesmo número) continua existindo
    # no ERP, e é isso que decide se a nova é a antiga renomeada. O filtro
    # das ignoradas vale só para o que aparece na janela.
    ren = (contas_novas.renomeacoes(todas, cadastradas)
           if cadastradas is not None else {})
    ativas = [c for c in todas if not contas_novas.casa_ignorada(
        util.norm_espaco(str(c.get("name"))), locais)]
    sem_cadastro = {n.id_erp for n in contas_novas.comparar(
        ativas, contas_novas.nomes_cadastrados(pasta), ignorar)}
    mapa = mapa_do_painel(pasta_painel)
    erps = [conta_do_erp(c) for c in ativas]
    sem_painel = ({c.id for c in _fora_do_painel(erps, mapa)}
                  if mapa is not None else set())
    saida = []
    for cru, erp in zip(ativas, erps):
        fc, fp = erp.id in sem_cadastro, erp.id in sem_painel
        if fc or fp:
            saida.append(Pendencia(contas_novas.como_conta_nova(cru), erp,
                                   fc, fp, rotulo_sugerido(erp),
                                   list(ren.get(erp.id, [])) if fc else []))
    return sorted(saida, key=lambda p: p.nome)


def pendencias_da_abertura(pend: list) -> list:
    """O que a ABERTURA do app pergunta: só quem falta no cadastro.

    Conta que falta só no painel do Saldo aparece apenas no botão "Atualizar
    contas" (antes, só o botão do Saldo a mostrava): o dono deixa contas fora
    do painel de propósito, e a abertura não pode perguntar por elas todo dia.
    Quem falta nos dois vem inteira — a parte do painel segue desmarcada."""
    return [p for p in (pend or []) if getattr(p, "falta_cadastro", True)]


def conferidor_do_painel(pasta_painel=None):
    """A conferência que a janela faz antes de incluir no painel, ou None
    se esta máquina não tem painel.

    É a mesma `problemas_da_inclusao` que o `incluir_no_painel` roda antes de
    gravar; feita na janela, o problema aparece com ela aberta e o que foi
    digitado não se perde. O mapping é lido agora, uma vez por janela."""
    mapa = mapa_do_painel(pasta_painel)
    if mapa is None:
        return None
    from conciliacao import painel_novas

    def conferir(painel) -> list[str]:
        return painel_novas.problemas_da_inclusao(
            [painel_novas.Inclusao(p.erp, rotulo) for p, rotulo in painel],
            mapa)
    return conferir


def aplicar(token: str, respostas, crus: list, pasta_painel=None) -> str:
    """Grava o que a janela única devolveu: cadastro primeiro, painel depois.

    Devolve o texto do recado. O painel recusado nunca desfaz o cadastro (são
    dois lugares diferentes, o da nuvem já valeu) e nunca levanta: o motivo
    entra no recado. Cadastrar as novas e corrigir os nomes também são
    independentes: o erro de uma vira recado e a outra roda igual.
    """
    # Módulos buscados na hora da chamada (e não `from ... import`), para o
    # teste poder trocar `gravar` e `incluir_no_painel`.
    from conciliacao import painel_novas
    from conciliacao.erp.api import conta_do_erp

    partes: list[str] = []
    # A conta renomeada no ERP só corrige o nome (UPDATE por id); a nova é
    # inserida. Contadas à parte: "cadastrada" para quem só mudou de nome
    # seria mentir sobre o que aconteceu no banco.
    renomear = [e for e in respostas.cadastro if e.get("renomear")]
    novas = [e for e in respostas.cadastro if not e.get("renomear")]
    avisos: list[str] = []
    # As duas são INDEPENDENTES (revisão de 23/10/2026): a falha de uma não
    # pode pular a outra, e cada uma diz o que houve no próprio recado.
    if novas:
        try:
            av = contas_novas.gravar(token, novas)
        except rest.PrecisaEntrar:
            raise                     # sessão vencida: o chamador pede login
        except Exception as e:                          # noqa: BLE001
            log.warning("cadastrando as contas novas", exc_info=True)
            partes.append(f"As contas novas NÃO foram cadastradas: {e}")
        else:
            avisos.extend(av)
            partes.append(f"{max(len(novas) - len(av), 0)} conta(s) "
                          "cadastrada(s).")
    if renomear:
        try:
            feitas, av = contas_novas.corrigir_nomes(token, renomear)
        except rest.PrecisaEntrar:
            raise
        except Exception as e:                          # noqa: BLE001
            log.warning("corrigindo o nome das contas", exc_info=True)
            partes.append(f"Os nomes NÃO foram corrigidos no cadastro: {e}")
        else:
            avisos.extend(av)
            partes.append(f"{feitas} nome(s) de conta corrigido(s) no "
                          "cadastro.")
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
