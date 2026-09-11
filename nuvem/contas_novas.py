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
import re
from dataclasses import dataclass
from pathlib import Path

import util

from . import rest

#: O diagnóstico do módulo. `contas_do_erp` e `novidades` recebem um `log`
#: PRÓPRIO (o recado que a abertura do app mostra na tela); lá dentro vale o
#: parâmetro, e é ele que continua sendo chamado. Este aqui é para o resto.
log = util.log(__name__)

#: As duas bases que o `SessaoApi` pede. Um objeto mínimo em vez de importar
#: `conciliacao/config.py`: aquele arquivo é um dos que divergem entre o
#: repositório e a máquina do dono, e a ABERTURA do app não pode depender
#: dessa divergência.
API_BASE = "https://prod-erp-api.maiscontroleerp.com.br"
LEGACY_BASE = "https://legacy-api.maiscontroleerp.com.br/maiscontrole/services"

ARQUIVO_CONTAS = "contas_mc.json"
ARQUIVO_MAPA = "mapping.yaml"

MOTIVO_SEM_PASTA = "marcada, mas sem pasta — a pasta é obrigatória no cadastro"
MOTIVO_SEM_EMPRESA = "marcada, mas sem empresa — o cadastro exige a empresa"

#: Os bancos em que, aqui, só PESSOA FÍSICA tem conta (regra do dono,
#: 11/09/2026): conta do ERP com um destes no nome é de uma pessoa, e vai para
#: a empresa das pessoas físicas, numa pasta só. Casa por PALAVRA inteira —
#: "NEXT" não pode acender numa conta que se chame "NEXTEL".
BANCOS_DE_PESSOA = ("NEXT", "PAGBANK", "NEON")
EMPRESA_DE_PESSOA = "PESSOAS FÍSICAS"
PASTA_DE_PESSOA = "PESSOA FÍSICA"

#: Código do banco (o `bankCode` do ERP) → o NOME que a coluna `banco` guarda.
#: São duas colunas no cadastro porque são duas coisas: o código vai para
#: `banco_codigo`, e o nome entra no nome do arquivo arquivado. Gravar "756"
#: em `banco` fazia o extrato sair `202607 756 MAIS CONTROLE.pdf`.
NOME_DO_BANCO = {"1": "BANCO DO BRASIL", "33": "SANTANDER", "77": "INTER",
                 "104": "CAIXA", "237": "BRADESCO", "260": "NUBANK",
                 "290": "PAGBANK", "341": "ITAU", "536": "NEON",
                 "756": "SICOOB"}

#: Número de conta escrito no NOME ("... SICOOB 60.290-6"). Com ou sem o
#: ponto do milhar, sempre com o dígito depois do hífen.
_RE_NUMERO_NO_NOME = re.compile(r"(?<![\d.])(?:\d{1,3}(?:\.\d{3})+|\d{4,6})-\d(?!\d)")


def banco_de_pessoa(nome: str) -> str:
    """O banco de pessoa física citado no nome da conta, ou ""."""
    chave = util.norm_espaco(nome or "")
    for banco in BANCOS_DE_PESSOA:
        if re.search(rf"\b{banco}\b", chave):
            return banco
    return ""


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
    def pasta_sugerida(self) -> str:
        """Onde o extrato desta conta provavelmente vai ser arquivado.

        É o nome do ERP sem o prefixo da empresa: as contas já cadastradas
        seguem esse padrão ("Morais Participações - SUBCONTA 55696-3 - TB 21
        QD 51 LT 40 - SICOOB" está arquivada em "SUBCONTA - 55696-3 - TB 21 QD
        51 LT 40 - SICOOB").

        É SUGESTÃO, não decisão: nasce no campo para ser corrigida. A primeira
        versão deixava o campo vazio, e a pessoa marcou quatro contas, não
        preencheu nada e levou quatro recusas de uma vez — trabalho que o app
        tinha como poupar.

        Conta de pessoa física (NEXT, PAGBANK, NEON no nome) vai toda para a
        MESMA pasta — quem separa uma da outra no nome do arquivo é o
        `sufixo`, que `gravar` põe sozinho (ver `desempatar`).
        """
        if banco_de_pessoa(self.nome):
            return PASTA_DE_PESSOA
        partes = self.nome.split(" - ", 1)
        return (partes[1] if len(partes) == 2 else self.nome).strip()

    def empresa_sugerida(self, nomes) -> str:
        """A empresa do NOSSO cadastro que esta conta provavelmente é. "" se
        não dá para dizer.

        Duas regras, e só elas: conta de pessoa física vai para a empresa das
        pessoas físicas (se ela existir no cadastro); qualquer outra, para a
        empresa cujo nome abre o nome da conta ("EMPRESA X SPE - SICOOB" →
        "EMPRESA X"), ficando com a mais comprida quando mais de uma abre.
        É SUGESTÃO, como a pasta: nasce no menu para ser conferida.
        """
        nomes = [n for n in (nomes or []) if n]
        if banco_de_pessoa(self.nome):
            alvo = util.norm_espaco(EMPRESA_DE_PESSOA)
            return next((n for n in nomes if util.norm_espaco(n) == alvo), "")
        if " - " not in self.nome:
            return ""
        prefixo = util.norm_espaco(self.nome.split(" - ", 1)[0])
        abrem = [n for n in nomes
                 if prefixo == util.norm_espaco(n)
                 or prefixo.startswith(util.norm_espaco(n) + " ")]
        return max(abrem, key=lambda n: len(util.norm_espaco(n)), default="")

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
        log.warning("lendo o cadastro local de contas (%s)", ARQUIVO_CONTAS,
                    exc_info=True)
        return set()
    contas = dados.get("contas") if isinstance(dados, dict) else None
    if not isinstance(contas, list):
        return set()
    return {util.norm_espaco(c.get("erp") or "") for c in contas
            if isinstance(c, dict) and c.get("erp")}


def ignorados(pasta=None) -> list[str]:
    """Os pedaços de nome que o painel já mandou ignorar para sempre.

    Sai de `ignored_erp_accounts`, no `mapping.yaml` — a MESMA lista que a
    Conciliação respeita ha meses. A primeira versão desta janela não a
    conhecia, e perguntava sobre conta que o dono já tinha decidido ignorar:
    das 15 que ela mostrou em 21/08/2026, sete eram isso. Cadastro de decisão
    já tomada não se duplica; se lê de onde ele está.

    Casa por PEDAÇO, como lá: "APENAS AJUSTE DE CAIXA" cobre a conta da Morais
    Engenharia e a da Buritis de uma vez.
    """
    caminho = Path(pasta or util.pasta_base()) / ARQUIVO_MAPA
    try:
        import yaml
        dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    except Exception:
        log.warning("lendo a lista de contas ignoradas (%s)", ARQUIVO_MAPA,
                    exc_info=True)
        return []
    lista = dados.get("ignored_erp_accounts") or []
    return [util.norm_espaco(str(x)) for x in lista if str(x).strip()]


# --------------------------------------------------------------------------
# A comparação — sem rede, sem disco
# --------------------------------------------------------------------------
def _texto(valor) -> str:
    return str(valor if valor is not None else "").strip()


def _com_digito(numero, digito) -> str:
    n, d = _texto(numero), _texto(digito)
    return f"{n}-{d}" if n and d else n


def numero_no_nome(nome: str) -> str:
    """O número de conta escrito no nome, quando há UM só. "" se nenhum ou
    mais de um.

    O ERP deixa `account` vazio em conta cadastrada às pressas, e o número
    acaba só no nome ("EMPRESA X SPE - SICOOB 60.290-6"). Sem ele a conta
    nasce sem `numero`, fica fora do `contas_sicoob.json` e o extrato do
    Sicoob dela nunca é baixado — sem erro nenhum na tela. Dois números no
    nome não se escolhem: a pergunta fica para o painel.
    """
    achados = _RE_NUMERO_NO_NOME.findall(nome or "")
    return achados[0] if len(achados) == 1 else ""


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
        numero=(_com_digito(cru.get("account"), cru.get("accountDigit"))
                or numero_no_nome(_texto(cru.get("name")))),
    )


def comparar(contas_erp, ja_cadastrados: set[str],
             ignorar=()) -> list[ContaNova]:
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
        if any(pedaco in chave for pedaco in ignorar):
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
    return comparar(crus, nomes_cadastrados(pasta), ignorados(pasta))


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
        log.warning("lendo as empresas para o menu da janela de contas novas",
                    exc_info=True)
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


def _banco(escolha: dict) -> tuple[str, str]:
    """`(banco, banco_codigo)` da escolha.

    O ERP manda o CÓDIGO ("756"), e ele ia parar na coluna do NOME — foi
    assim que nasceram subcontas com `banco='756'` no cadastro. Código
    conhecido vira nome e o código vai para a coluna dele; desconhecido fica
    como veio, que é o que já acontecia. Sem banco nenhum, conta de pessoa
    física leva o banco que o próprio nome diz (NEXT, PAGBANK, NEON).
    """
    cru = str(escolha.get("banco") or "").strip()
    if cru.isdigit():
        return NOME_DO_BANCO.get(cru.lstrip("0"), cru), cru
    if cru:
        return cru, ""
    return banco_de_pessoa(escolha.get("nome_erp") or ""), ""


def sufixo_do_nome(nome_erp: str) -> str:
    """O desempate que entra no NOME DO ARQUIVO: o nome da conta no ERP, sem
    os caracteres que o Windows recusa em nome de arquivo."""
    limpo = re.sub(r'[\\/:*?"<>|]+', " ", nome_erp or "")
    return re.sub(r"\s+", " ", limpo).strip()


def _destinos_ocupados(token: str):
    """`{(empresa_id, pasta, sufixo)}` das contas que já existem, comparáveis.
    `None` quando não deu para ler — aí o desempate olha só o lote."""
    try:
        linhas = rest.ler("conta", token, colunas="empresa_id,pasta,sufixo")
    except Exception:
        log.warning("lendo as contas já cadastradas para desempatar a pasta",
                    exc_info=True)
        return None
    return {(l.get("empresa_id"), util.norm_espaco(l.get("pasta") or ""),
             util.norm_espaco(l.get("sufixo") or ""))
            for l in linhas if isinstance(l, dict)}


def desempatar(linhas: list[dict], ocupados=()) -> None:
    """Dá `sufixo` às contas que cairiam no MESMO destino. Muda `linhas`.

    O banco recusa duas contas com a mesma `(empresa, pasta, sufixo)` — é o
    `conta_destino_unico`, e ele existe porque duas contas na mesma pasta sem
    desempate gravam o MESMO arquivo, e a segunda apaga a primeira calada.
    Enquanto a janela não sabia disso, marcar as contas de pessoa física
    (todas em "PESSOA FÍSICA") fazia o lote INTEIRO ser recusado, com um erro
    de SQL no lugar da resposta.

    Recebe o sufixo toda conta de um grupo com mais de uma, e a conta que cai
    numa pasta que já tem conta sem sufixo no cadastro. O sufixo é o nome da
    conta no ERP, que é único por construção (`conta_nome_erp_unico`).
    """
    ocupados = set(ocupados or ())
    grupos: dict = {}
    for linha in linhas:
        chave = (linha["empresa_id"], util.norm_espaco(linha["pasta"]))
        grupos.setdefault(chave, []).append(linha)
    for (empresa_id, pasta), grupo in grupos.items():
        if len(grupo) > 1 or (empresa_id, pasta, "") in ocupados:
            for linha in grupo:
                linha["sufixo"] = sufixo_do_nome(linha["nome_erp"])


def gravar(token: str, escolhas: list[dict]) -> list[str]:
    """Insere as contas escolhidas. Devolve os avisos do que ficou de fora.

    Só INSERT: apagar cadastro continua sendo assunto do painel do Supabase.

    Toda linha leva as MESMAS chaves (`sufixo` e `banco_codigo` inclusive,
    vazios): o PostgREST recusa o lote inteiro quando os objetos de um
    INSERT em massa não têm as mesmas colunas.
    """
    linhas, avisos = [], []
    for escolha in escolhas:
        problema = validar(escolha)
        if problema:
            avisos.append(f"{escolha.get('nome_erp', '?')}: {problema}")
            continue
        banco, banco_codigo = _banco(escolha)
        linhas.append({
            "empresa_id": escolha["empresa_id"],
            "nome_erp": escolha["nome_erp"],
            "pasta": str(escolha["pasta"]).strip(),
            "banco": banco,
            "banco_codigo": banco_codigo,
            "agencia": str(escolha.get("agencia") or "").strip(),
            "numero": str(escolha.get("numero") or "").strip() or None,
            "sufixo": "",
        })
    if linhas:
        desempatar(linhas, _destinos_ocupados(token))
        rest.inserir("conta", token, linhas)
    return avisos
