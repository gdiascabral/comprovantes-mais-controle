# -*- coding: utf-8 -*-
"""
Mapa conta do Mais Controle -> pasta de destino do extrato.

A LISTA de contas não sai daqui: ela é lida do ERP a cada execução, para que
conta nova apareça sozinha. Este mapa responde só uma pergunta — "onde salvo o
extrato desta conta?" — e admite não saber: conta sem destino vira aviso antes
de qualquer download, nunca arquivo no lugar errado.

O arquivo `contas_mc.json` fica FORA do repositório (nome de empresa e número
de conta), como o `contas_sicoob.json` e o `pix_reembolso.json`.

Sem navegador e sem tkinter: roda inteiro em teste.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import util


#: A tabela de pasta mora em `util.MESES_PASTA`: as três cópias que
#: existiam aqui produzem NOME DE PASTA no disco, e uma divergir entre
#: elas parte o mês ao meio. O nome local continua porque é por ele que
#: o resto do módulo chama.
MESES = util.MESES_PASTA

# Limite prático do Windows. Os caminhos daqui são longos (empresa + subconta
# com descrição), e o .zip do fechamento ainda entra por cima.
LIMITE_CAMINHO = 260


# `util.pasta_base()` e não um cálculo próprio: rodando como SCRIPT este
# módulo procurava em `relatorios/`, enquanto o `nuvem/cache.py` regrava o
# mapa na raiz. Congelado dá no mesmo — o desencontro só aparecia em
# desenvolvimento, que é justamente onde se testa.
_AQUI = util.pasta_base()

ARQUIVO_MAPA = _AQUI / "contas_mc.json"


class MapaInvalido(RuntimeError):
    """O JSON não existe, não é JSON, ou não descreve um mapa utilizável."""


@dataclass
class Destino:
    erp: str                    # nome exato da conta no Mais Controle
    empresa: str                # "BURITIS"
    pasta: str                  # "SICOOB" ou "CAIXA/APLICAÇÃO"
    banco: str                  # entra no nome do arquivo
    sufixo: str = ""            # desempate quando várias contas dividem a pasta


@dataclass
class Mapa:
    raiz: Path
    destinos: list[Destino]

    def de(self, nome_erp: str) -> Destino | None:
        alvo = _chave(nome_erp)
        return next((d for d in self.destinos if _chave(d.erp) == alvo), None)


#: A MESMA função dos dois lados, de propósito. Aqui ela escolhe a PASTA do
#: extrato; em `extrato_mc.py`, julga se o extrato baixado é o da conta certa.
#: Enquanto eram duas cópias, bastava uma divergir para o arquivo ser aceito e
#: arquivado no lugar errado — e nada no disco denunciaria.
_chave = util.norm_espaco


# ---------------------------------------------------------------- leitura

def carregar(caminho: Path | None = None) -> Mapa:
    """Lê o `contas_mc.json` inteiro, ou explica por que não dá para lê-lo.

    Obrigatórios são `erp`, `empresa` e `pasta`: sem eles a linha não
    identifica conta nenhuma nem diz onde salvar, e adivinhar seria escolher
    pasta no chute. `banco` NÃO é: linha sem banco carrega com
    `Destino.banco = ""`.

    A diferença é de escopo. `banco` só entra no NOME do arquivo e na escolha
    do produto da remessa — quem o USA é que sabe o que fazer sem ele, e cada
    um faz uma coisa: o Relatório Mensal barra a conta (`impedimentos`), a
    remessa recusa só aquela conta (`MOTIVO_SEM_BANCO`). Recusar o mapa
    inteiro aqui punia todo mundo pelo dado de um: em 04/09/2026, UMA conta
    sem banco derrubou a aba Pagamentos do Dia e o Relatório Mensal por
    completo — nenhuma empresa gerou remessa naquele dia."""
    caminho = caminho or ARQUIVO_MAPA
    if not caminho.exists():
        raise MapaInvalido(
            f"O mapa de contas não existe:\n{str(caminho).replace(chr(92), '/')}\n\n"
            "Ele diz em que pasta cada conta do Mais Controle deve ser salva.")
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise MapaInvalido(f"Não consegui ler {caminho.name}: {e}") from e
    if not isinstance(dados, dict) or not dados.get("contas"):
        raise MapaInvalido(f"{caminho.name} não tem a lista 'contas'.")

    destinos = []
    for i, c in enumerate(dados["contas"], 1):
        faltando = [k for k in ("erp", "empresa", "pasta") if not c.get(k)]
        if faltando:
            raise MapaInvalido(
                f"A conta nº {i} está sem: {', '.join(faltando)}.")
        destinos.append(Destino(erp=c["erp"].strip(), empresa=c["empresa"].strip(),
                                pasta=c["pasta"].strip(),
                                banco=(c.get("banco") or "").strip(),
                                sufixo=(c.get("sufixo") or "").strip()))
    return Mapa(raiz=Path(dados.get("raiz") or "C:/Arquivos Morais/EXTRATOS"),
                destinos=destinos)


# -------------------------------------------------------------- caminhos

def nome_arquivo(destino: Destino, ano: int, mes: int, periodo: str = "") -> str:
    """`202607 SICOOB MAIS CONTROLE.pdf`, com o número da conta no fim quando
    várias contas dividem a mesma pasta (caso da Moura Dantas).

    `periodo` troca o `AAAAMM` do começo, e existe por um motivo só: extrato
    de INTERVALO não pode usar o nome do mês fechado. Pedir 01/07 a 15/07
    para tirar uma dúvida gravava por cima do extrato de julho já arquivado,
    e nada barrava — a trava de paginação aprova, porque o extrato parcial
    está completo *para o período pedido*. O resto do nome fica igual de
    propósito: é por ele que se reconhece de que conta o arquivo é."""
    base = f"{periodo or f'{ano}{mes:02d}'} {destino.banco} MAIS CONTROLE"
    if destino.sufixo:
        base += f" {destino.sufixo}"
    return base + ".pdf"


def caminho_do_mes(mapa: Mapa, ano: int, mes: int) -> Path:
    return mapa.raiz / str(ano) / MESES[mes - 1]


def caminho_do_arquivo(mapa: Mapa, destino: Destino, ano: int, mes: int,
                       periodo: str = "") -> Path:
    pasta = (caminho_do_mes(mapa, ano, mes)
             / f"{MESES[mes - 1]} {ano} - {destino.empresa}"
             / destino.pasta)
    return pasta / nome_arquivo(destino, ano, mes, periodo)


def resolver(mapa: Mapa, contas: list[dict], ano: int, mes: int) -> tuple[list[tuple], list[str]]:
    """Casa as contas lidas do ERP com o mapa.

    Devolve (pares, desconhecidas): cada par é (conta, destino, caminho). As
    desconhecidas travam o lote antes do primeiro download — é preferível não
    baixar nada a espalhar PDF sem destino certo."""
    pares, desconhecidas = [], []
    for conta in contas:
        d = mapa.de(conta.get("nome", ""))
        if d is None:
            desconhecidas.append(conta.get("nome", "?"))
        else:
            pares.append((conta, d, caminho_do_arquivo(mapa, d, ano, mes)))
    return pares, desconhecidas


def impedimentos(mapa: Mapa, contas: list[str] | None = None) -> list[str]:
    """Os problemas do mapa que BARRAM o lote, em vez de só aparecerem no log.

    Hoje é um só: conta sem `banco`. É o banco que nomeia o arquivo
    (`nome_arquivo`), então sem ele o PDF sai como `AAAAMM  MAIS CONTROLE.pdf`
    — dois espaços no meio, sem dizer de que banco é. E se a empresa tiver
    outra conta na mesma pasta sem banco, a segunda grava POR CIMA da primeira
    calada, que é o mesmo estrago que `sicoob_contas.impedimentos()` barra do
    outro lado. Por isso trava antes do primeiro download, e não depois: aí o
    arquivo perdido não volta.

    `contas` limita a conferência aos nomes do ERP que vão rodar agora, como em
    `caminhos_longos`: barrar o lote por causa de uma conta que ninguém marcou
    é recusar trabalho que ia dar certo — foi justamente por punir todo mundo
    pelo dado de um que `carregar` deixou de recusar o mapa inteiro. Sem
    `contas`, confere o mapa inteiro."""
    alvo = {_chave(n) for n in contas} if contas is not None else None
    problemas: list[str] = []
    for d in mapa.destinos:
        if alvo is not None and _chave(d.erp) not in alvo:
            continue
        if not d.banco.strip():
            problemas.append(
                f"A conta '{d.erp}' está sem 'banco' no contas_mc.json, e é o "
                f"banco que nomeia o arquivo: o PDF sairia como "
                f"'AAAAMM  MAIS CONTROLE.pdf', sem dizer de que banco é. "
                f"Preencha o banco no painel ou desmarque a conta.")
    return problemas


def caminhos_longos(mapa: Mapa, ano: int, mes: int,
                    contas: list[str] | None = None,
                    periodo: str = "") -> list[tuple[str, int]]:
    """Destinos que passam do limite do Windows, com o tamanho de cada um.

    Vale conferir antes de rodar: o erro de caminho longo aparece como falha de
    escrita no meio do lote, e a causa não é óbvia para quem está olhando.

    `contas` limita a conferência aos nomes do ERP que vão rodar agora.
    Barrar o lote por causa de uma conta que ninguém marcou seria recusar
    trabalho que ia dar certo — é a mesma regra da trava de "conta sem
    destino", que também só olha as escolhidas. Sem `contas`, confere o mapa
    inteiro.

    `periodo` acompanha o de `nome_arquivo`: um intervalo de datas escreve
    "01-07-2026 a 15-07-2026" onde o mês fechado escreve "202607", 17
    caracteres a mais. Medir o nome curto e gravar o longo seria a
    conferência aprovando justamente o caminho que vai estourar."""
    alvo = {_chave(n) for n in contas} if contas is not None else None
    fora = []
    for d in mapa.destinos:
        if alvo is not None and _chave(d.erp) not in alvo:
            continue
        n = len(str(caminho_do_arquivo(mapa, d, ano, mes, periodo)))
        if n > LIMITE_CAMINHO:
            fora.append((d.erp, n))
    return fora
