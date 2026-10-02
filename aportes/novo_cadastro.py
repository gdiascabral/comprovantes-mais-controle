# -*- coding: utf-8 -*-
"""Cadastrar, pela própria aba Aportes, quem paga ou recebe um aporte.

Até 01/10/2026 entrar nesta lista era SQL no painel do Supabase: obra nova no
Mais Controle, conta nova no app (a janela de contas novas já cuidava disso)
e, para lançar o primeiro aporte dela, alguém tinha de escrever um INSERT em
`entidade` à mão. O botão "Novo cadastro" fecha esse buraco.

O que entra é uma linha da tabela `entidade` — a mesma que o `contas.csv`
copia na abertura do app:

    nome_exibicao   como aparece em Pagou/Recebeu (único);
    nome_oficial    o nome do CONTATO no ERP (Favorecido / Cliente) — tem de
                    ser exatamente o do ERP, senão o lançamento não acha;
    conta           o nome da CONTA BANCÁRIA no ERP; vazio para pessoa física
                    que só aparece como contato;
    nome_descricao  apelido opcional para o texto da descrição.

Só INSERT. Corrigir e apagar continuam no painel, pelo mesmo motivo da
migração de 21/08 (`conta_pode_nascer_pelo_app`): um token vazado pode SUJAR
a lista, nunca esvaziá-la.

Aqui mora só a regra — sugerir, validar, montar a linha — para ter teste. A
janela está em `novo_cadastro_dialogo.py`; quem fala com o banco é `gravar`.
"""
from __future__ import annotations

from dataclasses import dataclass

import util

from . import dados as cadastro


@dataclass
class Novo:
    nome_exibicao: str
    nome_oficial: str
    conta: str = ""
    nome_descricao: str = ""

    def linha(self) -> dict:
        """A linha do INSERT. Vazio vira None (é o que o resto do app lê
        como "sem conta" / "sem apelido")."""
        return {
            "nome_exibicao": self.nome_exibicao.strip(),
            "nome_oficial": self.nome_oficial.strip(),
            "conta": self.conta.strip() or None,
            "nome_descricao": self.nome_descricao.strip() or None,
        }


def _chave(texto) -> str:
    """Sem acento, sem caixa, espaços colapsados: "Obra  - Banco" e
    "OBRA - BANCO" são o mesmo nome para quem escolhe na lista."""
    return util.norm_espaco(str(texto or "")).casefold()


def contas_livres(contas: list[dict], entidades: list[dict]) -> list[str]:
    """Contas do cadastro que ainda não estão em Pagou/Recebeu.

    `contas` são linhas da tabela `conta` (`nome_erp`, `ativa`); `entidades`,
    da `entidade`. Conta desativada fica de fora: não se lança aporte nela.
    A ordem é a do nome, como no resto do app."""
    usadas = {_chave(e.get("conta")) for e in entidades if e.get("conta")}
    livres = {str(c["nome_erp"]).strip() for c in contas
              if c.get("nome_erp") and c.get("ativa", True) is not False
              and _chave(c["nome_erp"]) not in usadas}
    return sorted(livres, key=_chave)


def nome_oficial_sugerido(conta: str, contas: list[dict],
                          entidades: list[dict]) -> str:
    """O nome de contato que as OUTRAS contas da mesma empresa já usam.

    Só quando todas usam o MESMO: as subcontas de uma holding saem todas
    como o contato da holding, e a próxima quase sempre também. Empresa do
    cadastro é cliente, não pessoa jurídica — uma empresa pode juntar SPEs
    ou pessoas com contatos diferentes, e aí escolher "o mais comum" poria o
    aporte no contato de outra. Com divergência, ou sem nenhuma outra conta
    na lista, devolve "" e a janela pede."""
    empresa_de = {_chave(c.get("nome_erp")): c.get("empresa_id")
                  for c in contas if c.get("nome_erp")}
    alvo = empresa_de.get(_chave(conta))
    if alvo is None:
        return ""
    vistos = {str(e.get("nome_oficial") or "").strip()
              for e in entidades
              if e.get("conta") and empresa_de.get(_chave(e["conta"])) == alvo}
    vistos.discard("")
    return vistos.pop() if len(vistos) == 1 else ""


def validar(novo: Novo, entidades: list[dict]) -> str:
    """"" quando dá para gravar; senão, o motivo em português.

    Repete no app o que o banco também recusa (nome único) para que o recado
    seja uma frase, e não o texto cru da trava de unicidade."""
    exibicao = novo.nome_exibicao.strip()
    if not exibicao:
        return "Falta o nome que vai aparecer em Pagou/Recebeu."
    if not novo.nome_oficial.strip():
        return ("Falta o nome do contato no Mais Controle (como está no "
                "cadastro de Contatos do ERP).")
    if ";" in exibicao + novo.nome_oficial + novo.conta + novo.nome_descricao:
        # O cache local é CSV separado por ";".
        return "Os nomes não podem ter ponto e vírgula (;)."
    if exibicao.startswith(cadastro.INVESTIDOR_PREFIXO):
        return (f"Nomes que começam com \"{cadastro.INVESTIDOR_PREFIXO}\" são "
                "dos rateios de subconta. Escolha outro nome.")
    for e in entidades:
        if _chave(e.get("nome_exibicao")) == _chave(exibicao):
            return f"Já existe \"{e['nome_exibicao']}\" na lista."
        if novo.conta.strip() and _chave(e.get("conta")) == _chave(novo.conta):
            return (f"A conta \"{novo.conta.strip()}\" já está na lista como "
                    f"\"{e['nome_exibicao']}\".")
    return ""


# --------------------------------------------------------------------------
# Subconta de investidor
# --------------------------------------------------------------------------
@dataclass
class Investidor:
    """O que a opção "Subconta de investidor" da janela devolve."""
    conta: str                      # nome da conta no ERP
    dono: str                       # contato da empresa dona da conta
    aportadores: list
    obras: list
    pesos: dict
    banco: str = "SICOOB"

    @property
    def numero(self) -> str:
        from .rateio_subconta import numero_da_conta
        return numero_da_conta(self.conta)

    @property
    def em_recebeu(self) -> str:
        from .rateio_subconta import nome_em_recebeu
        return nome_em_recebeu(self.numero, self.banco)

    @property
    def em_pagou(self) -> str:
        return cadastro.INVESTIDOR_PREFIXO + self.numero


def entidade_da_conta(conta: str, entidades: list[dict]) -> dict | None:
    """A linha de Pagou/Recebeu que já usa esta conta, ou None."""
    alvo = _chave(conta)
    return next((e for e in entidades if e.get("conta")
                 and _chave(e["conta"]) == alvo), None)


def contas_de_investidor(contas: list[dict], entidades: list[dict],
                         subcontas: dict) -> list[str]:
    """O que a opção "Subconta de investidor" oferece: as contas livres e as
    que já são subconta de investidor (para mudar aportadores e obras)."""
    from .rateio_subconta import numero_da_conta
    opcoes = set(contas_livres(contas, entidades))
    for e in entidades:
        numero = numero_da_conta(e.get("conta") or "")
        if numero and numero in subcontas:
            opcoes.add(str(e["conta"]).strip())
    return sorted(opcoes, key=_chave)


def banco_da_conta(conta: str, contas: list[dict]) -> str:
    """O banco pelo cadastro da conta; sem ele, pelo fim do nome; "SICOOB"."""
    alvo = _chave(conta)
    for c in contas:
        if _chave(c.get("nome_erp")) == alvo and str(c.get("banco") or "").strip():
            return str(c["banco"]).strip().upper()
    for banco in ("SICOOB", "INTER", "CAIXA", "BRADESCO", "ITAU", "SANTANDER",
                  "BANCO DO BRASIL", "NUBANK", "NEXT", "PAGBANK", "NEON", "C6"):
        if banco in _chave(conta).upper():
            return banco
    return "SICOOB"


def validar_investidor(inv: Investidor, entidades: list[dict], *,
                       participantes=None, centros=None) -> str:
    """"" quando dá para gravar; senão, o motivo em português."""
    from . import rateio_subconta
    if not inv.conta.strip():
        return "Escolha a conta da subconta."
    if not inv.numero:
        return ("Não achei o número da conta (00000-0) no nome dela. Essa "
                "conta não parece ser uma subconta.")
    existente = entidade_da_conta(inv.conta, entidades)
    for e in entidades:
        outra = str(e.get("conta") or "")
        if outra and _chave(outra) != _chave(inv.conta) and \
                rateio_subconta.numero_da_conta(outra) == inv.numero:
            return (f"O número {inv.numero} já é da conta \"{outra}\" "
                    f"(\"{e['nome_exibicao']}\"). Duas contas não podem ser "
                    "a mesma subconta.")
    if existente is None:
        if not inv.dono.strip():
            return ("Falta o dono da conta (contato da empresa no Mais "
                    "Controle).")
        if participantes is not None and _chave(inv.dono) not in {
                _chave(p) for p in participantes}:
            return (f"O dono \"{inv.dono}\" não existe no Mais Controle com "
                    "esse nome. Escreva como está no cadastro de Contatos.")
        for e in entidades:
            if _chave(e.get("nome_exibicao")) == _chave(inv.em_recebeu):
                return f"Já existe \"{e['nome_exibicao']}\" na lista."
    return rateio_subconta.validar(inv.numero, inv.aportadores, inv.obras,
                                   participantes=participantes,
                                   centros=centros, pesos=inv.pesos)


def gravar_investidor(token: str, inv: Investidor, entidades: list[dict]) -> bool:
    """Cria a linha de Recebeu (se a conta ainda não tem) e grava o rateio.
    Devolve True quando criou a linha de Recebeu.

    A linha primeiro: rateio sem a conta em Recebeu não teria para onde
    lançar. Se o rateio falhar depois, a linha fica — e gravar de novo pela
    mesma janela completa o resto, sem duplicar (a conta já está lá)."""
    from . import rateio_subconta
    criou = False
    if entidade_da_conta(inv.conta, entidades) is None:
        gravar(token, Novo(inv.em_recebeu, inv.dono, inv.conta))
        criou = True
    rateio_subconta.gravar(token, inv.numero, inv.aportadores, inv.obras,
                           inv.pesos)
    return criou


# --------------------------------------------------------------------------
# Banco — só aqui o módulo sai da máquina
# --------------------------------------------------------------------------
def ler(token: str) -> tuple[list[dict], list[dict]]:
    """`(contas, entidades)` do banco, frescos — não do cache: o motivo de
    abrir a janela costuma ser uma conta que entrou HOJE."""
    from nuvem import rest
    contas = rest.ler("conta", token, colunas="nome_erp,empresa_id,ativa,banco")
    entidades = rest.ler("entidade", token,
                         colunas="nome_exibicao,nome_oficial,conta")
    return list(contas or []), list(entidades or [])


def gravar(token: str, novo: Novo) -> dict:
    """Insere no banco e, só depois, no cache local.

    Nessa ordem: o cache é regravado a partir do banco a cada abertura, então
    linha só no cache sumiria amanhã sem aviso. Com o INSERT aceito, copiar
    para o `contas.csv` faz a lista de hoje já trazê-la, sem reabrir o app —
    e reabrir no meio de uma lista lançada pela metade é o que duplica
    aporte: a memória do que já entrou no ERP morre com a janela."""
    from nuvem import rest
    linha = novo.linha()
    gravadas = rest.inserir("entidade", token, [linha])
    cadastro.acrescentar_conta(linha["nome_exibicao"], linha["nome_oficial"],
                               linha["conta"], linha["nome_descricao"])
    return gravadas[0] if gravadas else linha
