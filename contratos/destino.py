# -*- coding: utf-8 -*-
"""De qual empresa é a obra, e onde o contrato é arquivado.

Puro: sem navegador, sem tkinter e sem escrever em disco — só monta caminho e
nome, e olha o que já existe. Quem grava é o pipeline.

O ERP diz o cliente da obra (`customer.name`), mas esse nome **não é** o nome
da pasta: `TERRA BELA MORAIS ENGENHARIA SPE` é a pasta `TERRA BELA`, e
`MORAIS ENGENHARIA E CONSTRUCAO` é `MORAIS ENG`. Não há regra que derive um do
outro — e arquivar contrato na empresa errada é o pior defeito possível aqui,
o mesmo risco que o `relatorios/conferir_mapas.py` existe para evitar.

Por isso o mapa é EXPLÍCITO, e mora no `contas_sicoob.json` que já existe
(campo `clientes_erp` por empresa) em vez de num terceiro arquivo. Julho de
2026 já ficou partido uma vez porque `contas_mc.json` e `contas_sicoob.json`
discordavam sobre a mesma conta; um mapa a mais é uma divergência a mais
esperando acontecer.

**O nome do arquivo diz que é o contrato de compra e venda.** A pasta
CONTRATOS já guarda, arquivado à mão desde 2024, o contrato da Caixa com o
nome `CONTRATO <obra> CS 01 - COMPRADOR.pdf`. Se o app gravasse o de compra e
venda com o mesmo nome, apagaria o da Caixa — e ninguém perceberia até o
fechamento. O prefixo é a diferença.
"""
from __future__ import annotations

from pathlib import Path

import util

from .regras import numero_da_unidade

#: Subpasta do contrato dentro da pasta da empresa no mês.
SUBPASTA = "CONTRATOS"

#: Começo do nome do arquivo gravado pelo app.
PREFIXO = "CONTRATO DE COMPRA E VENDA"

#: Proibidos em nome de arquivo no Windows. O comprador vem de texto digitado
#: por gente e já apareceu com barra ("MARIA / JOSE").
PROIBIDOS = '\\/:*?"<>|'

#: Limite prático do Windows, o mesmo de `relatorios/contas_mc.py`. Os nomes
#: aqui são longos (obra + casa + nome completo do comprador) e estourar isso
#: aparece como falha de escrita no meio do lote, com causa nada óbvia.
LIMITE_CAMINHO = 260


def empresa_de(cliente_erp: str, empresas) -> object | None:
    """A empresa do cadastro dona daquele cliente do ERP, ou None.

    `empresas` é a lista de `sicoob_contas.Empresa`. A comparação passa por
    `util.norm_espaco` porque os dois lados foram digitados por gente.

    None não é falha do código: boa parte das obras tem como cliente uma
    pessoa física, e **essas obras não têm pasta de fechamento**. O imóvel vai
    para revisão dizendo qual cliente não tem empresa."""
    alvo = util.norm_espaco(cliente_erp)
    if not alvo:
        return None
    for empresa in empresas or []:
        for nome in getattr(empresa, "clientes_erp", None) or []:
            if util.norm_espaco(nome) == alvo:
                return empresa
    return None


def limpar(texto: str) -> str:
    """Nome de arquivo sem os proibidos do Windows e sem espaço dobrado."""
    limpo = "".join(" " if c in PROIBIDOS else c for c in (texto or ""))
    return " ".join(limpo.split())


def nome_arquivo(obra: str, unidade: int, comprador: str,
                 extensao: str = ".pdf") -> str:
    """`CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 02 - FULANO DE TAL.pdf`.

    A extensão vem do anexo e chega COM ponto (`extension` da API), então não
    se acrescenta outro."""
    ext = (extensao or ".pdf").strip()
    if ext and not ext.startswith("."):
        ext = "." + ext
    base = f"{PREFIXO} {limpar(obra)} CS {unidade:02d}"
    comprador = limpar(comprador)
    if comprador:
        base += f" - {comprador}"
    return base + ext


def pasta_do_contrato(raiz: Path, ano: int, mes: int, empresa_nome: str,
                      nome_do_mes, nome_pasta_empresa) -> Path:
    """<raiz>/<ANO>/<MÊS>/<MÊS ANO - EMPRESA>/CONTRATOS/

    Recebe as duas funções de nome (de `sicoob_config`) em vez de importá-las:
    mantém este módulo puro e testável sem arrastar o pacote do Sicoob."""
    return (Path(raiz) / str(ano) / nome_do_mes(mes)
            / nome_pasta_empresa(ano, mes, empresa_nome) / SUBPASTA)


def caminho_longo(caminho: Path) -> int | None:
    """Tamanho do caminho quando ele passa do limite do Windows; None se cabe.

    Conferir ANTES de escrever, como faz o Relatório Mensal: descobrir o
    estouro no meio do lote é caro e o erro não aponta para a causa."""
    n = len(str(caminho))
    return n if n > LIMITE_CAMINHO else None


def _compacto(texto: str) -> str:
    return util.norm_espaco(texto).replace(" ", "")


def mesmo_contrato_na_pasta(pasta: Path, obra: str, unidade: int,
                            exceto: Path | None = None) -> Path | None:
    """Um contrato de compra e venda desta casa que JÁ está na pasta com outro
    nome, ou None.

    Serve para a rodada refeita e para o mês arquivado à mão: gravar um
    segundo arquivo da mesma casa faria a Acessórias listar a casa duas vezes
    ao escritório. Compara sem espaços porque o nome é digitado por gente
    (`QD46 LT18` e `QD 46 LT 18` são a mesma obra)."""
    try:
        if not Path(pasta).is_dir():
            return None
        arquivos = [p for p in Path(pasta).iterdir() if p.is_file()]
    except OSError:
        return None
    alvo_obra = _compacto(obra)
    for p in sorted(arquivos):
        if exceto is not None and p.name == exceto.name:
            continue
        nome = _compacto(p.stem)
        if "COMPRAEVENDA" not in nome and "CCV" not in nome:
            continue
        if alvo_obra and alvo_obra not in nome:
            continue
        if numero_da_unidade(p.stem) == unidade:
            return p
    return None
