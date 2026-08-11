# -*- coding: utf-8 -*-
"""Utilitários compartilhados pelos módulos do app (sem dependências pesadas).

Fica na RAIZ do pacote de código; é copiado para o codigo.zip do auto-update
e para os exes. Módulos em subpastas o importam com um fallback de sys.path
(ver o topo de cada arquivo) para funcionarem também rodados isoladamente.
"""
import re
import sys
import unicodedata
from pathlib import Path


def pasta_base() -> Path:
    """Onde ficam os arquivos que o usuário edita e os que o app gera.

    Congelado, é a pasta do .exe; rodando como script, a raiz do projeto —
    e este arquivo mora justamente na raiz, por isso um `parent` só.

    Existia em três cópias byte a byte (Conciliação, Pagamentos do Dia e
    Relatório Mensal). Três cópias de uma regra de CAMINHO é como um app passa
    a procurar o mesmo arquivo em lugares diferentes."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def fmt_dur(seg: float) -> str:
    """Formata uma duração em segundos: '45 s', '3 min 07 s', '1 h 02 min'."""
    seg = int(round(seg))
    m, s = divmod(seg, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h} h {m:02d} min"
    if m:
        return f"{m} min {s:02d} s"
    return f"{s} s"


def data_api(txt: str) -> str | None:
    """'dd/mm/aaaa' -> 'aaaa-mm-dd' (aceita também dd-mm-aaaa). None se não bate.

    É o formato que a API do ERP espera nos filtros de período."""
    m = re.match(r"^\s*(\d{2})[/-](\d{2})[/-](\d{4})\s*$", txt or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def fmt_val(cents: int) -> str:
    """Centavos -> "1234,56" (sem "R$" e sem ponto de milhar).

    É a forma que o ERP mostra na grade, e é assim que os valores são
    comparados com o texto da tela."""
    return f"{cents // 100},{cents % 100:02d}"


def sem_acento(s: str) -> str:
    """Remove acentos, preservando maiúsculas/minúsculas.

    NFKD e não NFD: além dos acentos, desfaz as formas de compatibilidade
    (ligaduras, "º" sobrescrito, dígitos de largura dupla) que às vezes vêm
    coladas de PDF e de campo do ERP. Era o que três das cinco cópias desta
    função já faziam; unificar no mais abrangente evita que dois textos
    "iguais na tela" comparem diferente."""
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c))


def norm(s: str) -> str:
    """Sem acento, em MAIÚSCULAS (para comparações)."""
    return sem_acento(s).upper()


def norm_espaco(s: str) -> str:
    """Forma comparável de um NOME: sem acento, maiúsculo, sem espaço dobrado.

    É a função que decide se dois nomes de conta são o mesmo — e por isso
    precisa ser UMA só. Ela escolhia a PASTA do extrato em `contas_mc.py` e
    julgava a VALIDADE do extrato em `extrato_mc.py`, em duas cópias
    separadas: bastava uma divergir para o arquivo ser aceito e arquivado no
    lugar errado.

    O nome vem do cadastro do ERP e é digitado por gente: "Morais
    Participações" e "MORAIS  PARTICIPACOES" são a mesma conta."""
    return re.sub(r"\s+", " ", norm(s)).strip()


def filtrar(itens, termo: str, chave=None) -> list:
    """Itens cujo texto CONTÉM o termo, ignorando acento, caixa e espaço duplo.

    Substring em qualquer posição, de propósito: quem procura digita o pedaço
    que lembra, não o começo. "livia" acha "Livian"; "696" acha a subconta
    55696-3; "buritis" acha "MORAIS EMPREENDIMENTOS BURITIS - SICOOB".

    Termo vazio devolve tudo — filtro que esconde a lista inteira quando o
    campo está vazio é pior do que não ter filtro."""
    alvo = norm_espaco(termo)
    if not alvo:
        return list(itens)
    return [i for i in itens
            if alvo in norm_espaco(chave(i) if chave else str(i))]


def cor_escura(cor_hex) -> bool:
    """True se a cor de fundo '#rrggbb' for escura. Usado para já criar os
    campos de log na cor certa do tema e evitar o 'flash' branco no escuro."""
    cor = (cor_hex or "").lstrip("#")
    if len(cor) != 6:
        return False
    try:
        r, g, b = (int(cor[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return False
    return (r + g + b) / 3 < 128
