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
# Banco — só aqui o módulo sai da máquina
# --------------------------------------------------------------------------
def ler(token: str) -> tuple[list[dict], list[dict]]:
    """`(contas, entidades)` do banco, frescos — não do cache: o motivo de
    abrir a janela costuma ser uma conta que entrou HOJE."""
    from nuvem import rest
    contas = rest.ler("conta", token, colunas="nome_erp,empresa_id,ativa")
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
