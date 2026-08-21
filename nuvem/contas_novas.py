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
def _texto(valor) -> str:
    return str(valor if valor is not None else "").strip()


def _com_digito(numero, digito) -> str:
    n, d = _texto(numero), _texto(digito)
    return f"{n}-{d}" if n and d else n


def como_conta_nova(cru: dict) -> ContaNova:
    """Uma conta CRUA da API vira o nosso formato.

    O ERP parte o número em `account` + `accountDigit` (e a agência em
    `agency` + `agencyDigit`), e devolve `bankCode` nulo na maioria das
    contas. Nada disso é obrigatório aqui: o que a janela precisa mesmo é do
    nome; o resto entra como ajuda para quem for conferir.
    """
    return ContaNova(
        id_erp=_texto(cru.get("id")),
        nome=_texto(cru.get("name")),
        banco=_texto(cru.get("bankCode")),
        agencia=_com_digito(cru.get("agency"), cru.get("agencyDigit")),
        numero=_com_digito(cru.get("account"), cru.get("accountDigit")),
    )


def comparar(contas_erp, ja_cadastrados: set[str]) -> list[ContaNova]:
    """O que existe no ERP e não no cadastro.

    Recebe as contas CRUAS, como `SessaoApi.listar_contas` devolve — e não um
    formato nosso. A primeira versão convertia antes de comparar, e a
    comparação lia `name` num objeto que já tinha virado `nome`: casava zero,
    devolvia lista vazia, e o app abria sem perguntar nada. Os testes não
    pegaram porque testavam o formato convertido, que produção nenhuma usa.
    Um formato só, e é o de quem fala do outro lado.

    A comparação é por nome NORMALIZADO (maiúscula, sem acento, sem espaço
    dobrado), a mesma régua que o resto do app usa para nome de conta.

    Conta inativa fica de fora: perguntar sobre conta que ninguém usa mais é
    ruído, e a lista precisa ser curta para ser lida.
    """
    novas: list[ContaNova] = []
    vistos = set(ja_cadastrados)
    for cru in contas_erp or []:
        if not isinstance(cru, dict):
            continue
        if cru.get("isActive") is False:
            continue
        conta = como_conta_nova(cru)
        if not conta.nome:
            continue
        chave = util.norm_espaco(conta.nome)
        if chave in vistos:
            continue
        vistos.add(chave)                # não repete a mesma duas vezes
        novas.append(conta)
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


def novidades(pasta=None, log=print) -> list[ContaNova]:
    """O que perguntar ao dono. Lista vazia = nada a fazer, nem abrir janela."""
    crus = contas_do_erp(log=log)
    if not crus:
        return []
    return comparar(crus, nomes_cadastrados(pasta))


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
