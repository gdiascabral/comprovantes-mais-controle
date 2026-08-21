# -*- coding: utf-8 -*-
"""Conta nova no Mais Controle: descobrir na abertura, e não no fechamento.

Em 20/08/2026 foram criadas quatro contas no ERP e o app não soube. A única
detecção que existia era a da Conciliação, que marca o LANÇAMENTO em conta
desconhecida como `unmapped` — ou seja, só descobre depois que alguém pagou
por ali.

Aqui a pergunta é feita antes: na abertura, o app entra no ERP **sem
navegador**, lista as contas e compara com o nosso cadastro.

**Sem navegador** não é figura de linguagem: `conciliacao/erp/api.py` já faz
`POST /users/login` por HTTP puro, com as credenciais guardadas, e já sabe
paginar a lista de contas. Este módulo liga isso ao nosso cadastro; não
reimplementa nada.

A ordem importa, e é a única defesa contra a sessão única do ERP: a API roda na
ABERTURA, quando ainda não há Chrome. A aba que abrir o navegador depois vai
derrubar este token — e tudo bem, porque a conferência já acabou.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

from . import rest

#: As duas bases que o `SessaoApi` pede. Um objeto mínimo em vez de importar
#: `conciliacao/config.py`: aquele arquivo é um dos que divergem entre o
#: repositório e a máquina do dono, e a ABERTURA do app não pode depender
#: dessa divergência.
API_BASE = "https://prod-erp-api.maiscontroleerp.com.br"
LEGACY_BASE = "https://legacy-api.maiscontroleerp.com.br/maiscontrole/services"

ARQUIVO_CONTAS = "contas_mc.json"

MOTIVO_SEM_PASTA = "marcada, mas sem pasta — a pasta é obrigatória no cadastro"
MOTIVO_SEM_EMPRESA = "marcada, mas sem empresa — o cadastro exige a empresa"


class _ConfigMinimo:
    """O bastante do `config` da Conciliação para o `SessaoApi` logar."""

    def __init__(self) -> None:
        self.erp = {"api_base": API_BASE, "legacy_api_base": LEGACY_BASE}


@dataclass
class ContaNova:
    """Uma conta que existe no ERP e não existe no nosso cadastro."""

    id_erp: str
    nome: str
    banco: str = ""
    agencia: str = ""
    numero: str = ""

    @property
    def resumo(self) -> str:
        partes = [p for p in (f"banco {self.banco}" if self.banco else "",
                              f"ag {self.agencia}" if self.agencia else "",
                              f"conta {self.numero}" if self.numero else "")
                  if p]
        return " · ".join(partes)


# --------------------------------------------------------------------------
# O nosso lado
# --------------------------------------------------------------------------
def nomes_cadastrados(pasta=None) -> set[str]:
    """Os nomes de conta do ERP que o nosso cadastro já conhece.

    Sai do `contas_mc.json`, que é exatamente a lista das contas com
    `nome_erp` preenchido — conta que o ERP não tem não entra ali, e também
    não teria como casar com nada vindo de lá.
    """
    caminho = Path(pasta or util.pasta_base()) / ARQUIVO_CONTAS
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return set()
    contas = dados.get("contas") if isinstance(dados, dict) else None
    if not isinstance(contas, list):
        return set()
    return {util.norm_espaco(c.get("erp") or "") for c in contas
            if isinstance(c, dict) and c.get("erp")}


# --------------------------------------------------------------------------
# A comparação — sem rede, sem disco
# --------------------------------------------------------------------------
def comparar(contas_erp, ja_cadastrados: set[str]) -> list[ContaNova]:
    """O que existe no ERP e não no cadastro.

    A comparação é por nome NORMALIZADO (maiúscula, sem acento, sem espaço
    dobrado), a mesma régua que o resto do app usa para nome de conta. Sem
    isso, "Morais Participações" e "MORAIS PARTICIPACOES" viravam duas contas
    diferentes e a janela perguntaria todo dia sobre uma conta já cadastrada.

    Conta inativa no ERP fica de fora: perguntar sobre conta que ninguém usa
    mais é ruído, e a lista precisa ser curta para ser lida.
    """
    novas: list[ContaNova] = []
    vistos = set(ja_cadastrados)
    for conta in contas_erp or []:
        nome = str(getattr(conta, "name", "") or "").strip()
        if not nome or not getattr(conta, "is_active", True):
            continue
        chave = util.norm_espaco(nome)
        if chave in vistos:
            continue
        vistos.add(chave)                # não repete a mesma duas vezes
        novas.append(ContaNova(
            id_erp=str(getattr(conta, "id", "") or ""),
            nome=nome,
            banco=str(getattr(conta, "bank_code", "") or ""),
            agencia=str(getattr(conta, "agency", "") or ""),
            numero=str(getattr(conta, "account_number", "") or ""),
        ))
    return sorted(novas, key=lambda c: c.nome)


# --------------------------------------------------------------------------
# O lado do ERP
# --------------------------------------------------------------------------
def contas_do_erp(log=print) -> list:
    """As contas ativas do ERP, por HTTP puro. `[]` quando não deu.

    Nunca levanta: esta função roda na abertura do app, e nada aqui é motivo
    para o app não abrir. Sem rede, login vencido, MFA ligado ou contrato
    mudado, o resultado é uma linha no log e uma lista vazia.
    """
    try:
        from conciliacao.erp.api import SessaoApi          # import tardio
        sessao = SessaoApi.logar(_ConfigMinimo(), log=lambda *_a, **_k: None)
        return sessao.listar_contas(ativas=True)
    except Exception as e:                                  # noqa: BLE001
        log(f"conferência de contas: não deu para consultar o ERP ({e})")
        return []


def _como_conta(cru: dict):
    """Um item cru da API vira o formato que `comparar` entende."""
    return ContaNova(
        id_erp=str(cru.get("id") or ""),
        nome=str(cru.get("name") or ""),
        banco=str(cru.get("bankCode") or ""),
        agencia=str(cru.get("agency") or ""),
        numero=str(cru.get("accountNumber") or cru.get("number") or ""),
    )


def novidades(pasta=None, log=print) -> list[ContaNova]:
    """O que perguntar ao dono. Lista vazia = nada a fazer, nem abrir janela."""
    crus = contas_do_erp(log=log)
    if not crus:
        return []
    contas = [_como_conta(c) if isinstance(c, dict) else c for c in crus]
    # O item cru não tem `is_active`; a listagem já veio filtrada por ativas.
    for c in contas:
        if not hasattr(c, "is_active"):
            setattr(c, "is_active", True)
    return comparar(contas, nomes_cadastrados(pasta))


# --------------------------------------------------------------------------
# Gravar a resposta — no NOSSO cadastro, nunca no ERP
# --------------------------------------------------------------------------
def empresas(token: str) -> list[tuple]:
    """`[(id, nome)]` para o menu da janela. `[]` quando não deu.

    Vem do nosso cadastro, não do ERP: `empresa_id` é chave estrangeira lá,
    e o ERP não tem como saber a que empresa NOSSA uma conta pertence.
    """
    try:
        linhas = rest.ler("empresa", token, colunas="id,nome_pasta")
    except Exception:
        return []
    return sorted(((l["id"], l.get("nome_pasta") or str(l["id"]))
                   for l in linhas if isinstance(l, dict) and l.get("id")),
                  key=lambda par: par[1])


def validar(escolha: dict) -> str:
    """"" quando dá para gravar; o motivo quando não dá.

    `pasta` é `not null` no banco e `empresa_id` é chave estrangeira: mandar
    sem eles trocaria uma pergunta clara por um erro de SQL cru na cara de
    quem só queria responder "sim".
    """
    if not str(escolha.get("pasta") or "").strip():
        return MOTIVO_SEM_PASTA
    if not escolha.get("empresa_id"):
        return MOTIVO_SEM_EMPRESA
    return ""


def gravar(token: str, escolhas: list[dict]) -> list[str]:
    """Insere as contas escolhidas. Devolve os avisos do que ficou de fora.

    Só INSERT: apagar cadastro continua sendo assunto do painel do Supabase.
    """
    linhas, avisos = [], []
    for escolha in escolhas:
        problema = validar(escolha)
        if problema:
            avisos.append(f"{escolha.get('nome_erp', '?')}: {problema}")
            continue
        linhas.append({
            "empresa_id": escolha["empresa_id"],
            "nome_erp": escolha["nome_erp"],
            "pasta": str(escolha["pasta"]).strip(),
            "banco": str(escolha.get("banco") or "").strip(),
            "agencia": str(escolha.get("agencia") or "").strip(),
            "numero": str(escolha.get("numero") or "").strip() or None,
        })
    if linhas:
        rest.inserir("conta", token, linhas)
    return avisos
