# -*- coding: utf-8 -*-
"""Traz o cadastro do banco e o deixa nos arquivos que o app já lê.

Uma função importa daqui: `sincronizar()`. Ela é chamada uma vez, ao abrir o
app, e o resto do programa continua exatamente como estava — lendo
`contas_sicoob.json`, `contas_mc.json` e `contas.csv` do jeito de sempre.

**Por que reconstruir os arquivos em vez de trocar os leitores.** Trocar
`sicoob_contas`, `contas_mc` e `dados` por consultas ao banco significaria
mexer em cinco abas que hoje funcionam, para ganhar o quê — a mesma
informação. E deixaria cada uma delas com um caminho de erro novo ("e se o
banco não responder no meio do lote?"). Reconstruindo os arquivos, existe UM
ponto onde a rede pode falhar, ele acontece antes de qualquer trabalho
começar, e o pior caso é o app rodar com o cadastro de ontem.

Banco mudo não é erro: `sincronizar` devolve o que houve, e quem chamou
decide o que dizer na tela. O que ela nunca faz é apagar o cache por não ter
conseguido falar com o servidor.
"""
from __future__ import annotations

from dataclasses import dataclass

try:
    from . import cache, rest
except ImportError:
    import cache
    import rest


@dataclass
class Resultado:
    """O que aconteceu na sincronização, em vez de um bool sem explicação."""
    atualizou: bool
    motivo: str = ""
    contas: int = 0
    empresas: int = 0

    @property
    def usando_copia(self) -> bool:
        return not self.atualizou


def _por_id(linhas: list[dict]) -> dict:
    return {l["id"]: l for l in linhas}


def _agrupar(linhas: list[dict], chave: str) -> dict:
    saida: dict = {}
    for l in linhas:
        saida.setdefault(l[chave], []).append(l)
    return saida


# ------------------------------------------------------- montagem dos arquivos

def _contas_sicoob(dados: dict) -> dict:
    """Reconstrói o `contas_sicoob.json` a partir das tabelas.

    Só as contas COM número entram: o arquivo descreve o que o SicoobNet
    baixa, e conta sem número não é buscável lá."""
    empresas = []
    por_empresa = _agrupar(dados["conta"], "empresa_id")
    vazias = _agrupar(dados["pasta_vazia"], "empresa_id")
    clientes = _agrupar(dados["cliente_erp"], "empresa_id")

    for e in sorted(dados["empresa"], key=lambda x: x["nome_pasta"]):
        contas = []
        for c in por_empresa.get(e["id"], []):
            if not c["numero"]:
                continue
            linha = {"numero": c["numero"], "pasta": c["pasta"],
                     "banco": c["banco_codigo"], "agencia": c["agencia"]}
            # A MESMA chave `sufixo` do lado do Mais Controle, e pelo mesmo
            # motivo: é ele que impede duas contas da mesma pasta de gravarem
            # o mesmo arquivo. Enquanto ele só descia para o `contas_mc.json`,
            # o PDF do ERP saía desempatado e o OFX do banco não — a segunda
            # conta apagava o extrato da primeira, sem erro na tela.
            # Condicional como em `_contas_mc`: o desempate só existe onde
            # alguém o cadastrou, e escrevê-lo vazio sugeriria um campo a
            # preencher em toda conta.
            if c["sufixo"]:
                linha["sufixo"] = c["sufixo"]
            contas.append(linha)
        # Todos os campos, sempre, mesmo vazios. A tentação é omitir o que
        # está em branco para o arquivo ficar igualzinho ao que a pessoa
        # digitou — mas aí a regra de escrita passa a depender do CONTEÚDO, e
        # `convenio: ""` deixa de aparecer justamente onde ele é um lembrete
        # de que falta aderir. Ausente e vazio querem dizer a mesma coisa
        # para quem lê (`.get(campo, "")`); presente e vazio diz mais.
        empresas.append({
            "nome": e["nome_pasta"],
            "pastas_vazias": [p["nome"] for p in vazias.get(e["id"], [])],
            "contas": contas,
            "clientes_erp": [c["nome"] for c in clientes.get(e["id"], [])],
            "cnpj": e["cnpj"],
            "razao_social": e["razao_social"],
            "convenio": e["convenio"],
            "vip_id": e["vip_id"],
        })
    return {"raiz": dados["config"].get("raiz", ""),
            "empresas": empresas,
            "vip_url": dados["config"].get("vip_url", "")}


def _contas_mc(dados: dict) -> dict:
    """Reconstrói o `contas_mc.json`.

    Só as contas com `nome_erp`: o mapa responde "onde salvo o extrato DESTA
    conta do ERP?", e conta que o ERP não tem não é perguntável."""
    empresas = _por_id(dados["empresa"])
    contas = []
    for c in dados["conta"]:
        if not c["nome_erp"]:
            continue
        linha = {"erp": c["nome_erp"],
                 "empresa": empresas[c["empresa_id"]]["nome_pasta"],
                 "pasta": c["pasta"],
                 "banco": c["banco"]}
        if c["sufixo"]:
            linha["sufixo"] = c["sufixo"]
        contas.append(linha)
    contas.sort(key=lambda x: (x["empresa"], x["pasta"], x.get("sufixo", "")))
    return {"raiz": dados["config"].get("raiz", ""), "contas": contas}


def _subcontas(dados: dict) -> dict:
    saida: dict = {}
    padrao = dados["config"].get("obra_padrao", "")
    if padrao:
        saida["_obra_padrao"] = padrao
    obras = _agrupar(dados["subconta_obra"], "subconta_id")
    invs = _agrupar(dados["subconta_investidor"], "subconta_id")
    for s in sorted(dados["subconta"], key=lambda x: x["nome"]):
        saida[s["nome"]] = {
            "obras": [o["nome"] for o in obras.get(s["id"], [])],
            "investidores": [i["nome"] for i in invs.get(s["id"], [])],
        }
    return saida


def _regras_fornecedor(dados: dict) -> dict:
    """As duas listas que moram em `regras_fornecedor.json`.

    `pagar_a_mao` volta a se chamar `confirmar_sempre` no arquivo — é o nome
    que `regras_pagamento.py` lê hoje, e renomear ali seria mexer numa regra
    de dinheiro para ganhar consistência de vocabulário."""
    saida: dict = {}
    for r in dados["regra_fornecedor"]:
        if r["tipo"] == "so_reembolso":
            saida.setdefault(r["nome"], {})["so_com_reembolso"] = True
        elif r["tipo"] == "pagar_a_mao":
            saida.setdefault(r["nome"], {})["confirmar_sempre"] = True
    return saida


def _confirmar_antes(dados: dict) -> dict:
    return {"nomes": [r["nome"] for r in dados["regra_fornecedor"]
                      if r["tipo"] == "confirmar_antes"]}


def _pix_reembolso(dados: dict) -> dict:
    return {r["nome"]: r["valor"] for r in dados["regra_fornecedor"]
            if r["tipo"] == "pix_reembolso"}


def _regras_boletos(dados: dict) -> dict:
    regras = []
    for r in dados["regra_boleto"]:
        linha = {k: r[k] for k in ("remetente", "assunto_contem",
                                   "fornecedor_erp", "descricao_contem",
                                   "valor_varia", "janela_dias", "automatico")}
        if r.get("confirmado_em"):
            linha["confirmado_em"] = r["confirmado_em"]
        if r.get("nota"):
            linha["nota"] = r["nota"]
        if r.get("ambiguo"):
            linha["ambiguo"] = r["ambiguo"]
        regras.append(linha)
    return {"regras": regras}


def _contas_csv(dados: dict) -> list[dict]:
    return [{"nome_exibicao": e["nome_exibicao"],
             "nome_oficial": e["nome_oficial"],
             "conta": e["conta"] or "",
             "nome_descricao": e["nome_descricao"] or ""}
            for e in sorted(dados["entidade"], key=lambda x: x["nome_exibicao"])]


# ------------------------------------------------------------------ público

TABELAS = ("empresa", "cliente_erp", "conta", "pasta_vazia", "entidade",
           "subconta", "subconta_obra", "subconta_investidor",
           "regra_fornecedor", "regra_boleto", "configuracao")


def sincronizar(token: str, pasta=None) -> Resultado:
    """Baixa o cadastro e regrava os arquivos locais.

    Devolve o que houve; não levanta por falta de rede. `rest.PrecisaEntrar`
    sobe, porque sessão vencida é assunto de quem cuida do login."""
    try:
        dados = {t: rest.ler(t, token) for t in TABELAS}
    except rest.SemRede as e:
        return Resultado(False, f"sem conexão com o banco ({e})")
    except rest.RecusadoPeloBanco as e:
        return Resultado(False, f"o banco recusou a leitura ({e})")

    dados["config"] = {c["chave"]: c["valor"] for c in dados["configuracao"]}

    # Banco vazio quase certamente é engano (projeto novo, migração não
    # rodada). Regravar os arquivos com nada apagaria o cadastro de todo
    # mundo -- e o cache é justamente a última cópia que sobraria.
    if not dados["empresa"] or not dados["conta"]:
        return Resultado(False, "o banco respondeu sem empresas ou sem contas "
                                "— os arquivos locais foram mantidos")

    # Arquivo por arquivo, a mesma regra que protege o conjunto: conteúdo
    # vazio vindo do banco NÃO apaga conteúdo que existe no disco.
    #
    # A checagem de `empresa`/`conta` acima cobre o caso grosso (banco vazio),
    # e não cobre o caso fino, que é mais provável: alguém apaga as entidades
    # pelo painel sem querer, e a próxima abertura do app zera o `contas.csv`
    # de todas as máquinas. Vazio legítimo existe — `pix_reembolso` está
    # assim hoje —, e por isso a regra não é "nunca escreva vazio", e sim
    # "não troque cheio por vazio".
    def _gravar(nome, conteudo, vazio_quando):
        if vazio_quando and cache.existe(nome, pasta):
            antigo = cache.ler_json(nome, pasta)
            if any(not k.startswith("_") for k in antigo):
                return                   # tinha coisa; não apaga em silêncio
        cache.gravar_json(nome, conteudo, pasta)

    sic = _contas_sicoob(dados)
    _gravar("contas_sicoob.json", sic, not sic["empresas"])
    mc = _contas_mc(dados)
    _gravar("contas_mc.json", mc, not mc["contas"])
    sub = _subcontas(dados)
    _gravar("subcontas.json", sub, not dados["subconta"])
    _gravar("regras_fornecedor.json", _regras_fornecedor(dados),
            not dados["regra_fornecedor"])
    _gravar("confirmar_antes.json", _confirmar_antes(dados),
            not dados["regra_fornecedor"])
    _gravar("regras_boletos.json", _regras_boletos(dados),
            not dados["regra_boleto"])
    pix = _pix_reembolso(dados)
    if pix:
        cache.gravar_json("pix_reembolso.json", pix, pasta)

    linhas = _contas_csv(dados)
    if linhas or not cache.existe("contas.csv", pasta):
        cache.gravar_csv(
            "contas.csv",
            ["nome_exibicao", "nome_oficial", "conta", "nome_descricao"],
            linhas, pasta)

    return Resultado(True, "", contas=len(dados["conta"]),
                     empresas=len(dados["empresa"]))
