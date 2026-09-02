# -*- coding: utf-8 -*-
"""Utilitários compartilhados pelos módulos do app (sem dependências pesadas).

Fica na RAIZ do pacote de código; é copiado para o codigo.zip do auto-update
e para os exes. Módulos em subpastas o importam com um fallback de sys.path
(ver o topo de cada arquivo) para funcionarem também rodados isoladamente.
"""
import ctypes
import logging
import re
import sys
import unicodedata
from logging.handlers import RotatingFileHandler
from pathlib import Path


# ------------------------------------------------------------- cofre local

class _BLOB(ctypes.Structure):
    # DWORD é um inteiro de 32 bits sem sinal. `c_uint32` direto para não
    # depender de `ctypes.wintypes` (submódulo que não vem embutido no motor).
    _fields_ = [("cbData", ctypes.c_uint32),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(dados: bytes) -> _BLOB:
    buf = ctypes.create_string_buffer(dados, len(dados))
    return _BLOB(len(dados), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _dpapi(funcao: str, dados: bytes) -> bytes:
    saida = _BLOB()
    entrada = _blob(dados)
    if not getattr(ctypes.windll.crypt32, funcao)(
            ctypes.byref(entrada), None, None, None, None, 0,
            ctypes.byref(saida)):
        raise OSError(f"{funcao} falhou")
    try:
        return ctypes.string_at(saida.pbData, int(saida.cbData))
    finally:
        ctypes.windll.kernel32.LocalFree(saida.pbData)


def proteger_bytes(dados: bytes) -> bytes:
    """Cifra com a DPAPI do Windows. Levanta OSError se não der.

    O resultado só é decifrável pelo MESMO usuário do Windows, nesta máquina.
    É o cofre de tudo que o app guarda e não pode ficar em texto: a senha do
    ERP (`login.dat`) e a sessão da nuvem (`sessao.dat`).

    Mora aqui, e não junto de um dos dois, porque os dois precisam dela e
    `nuvem` importar de `anexar` acoplaria o login ao módulo de anexos — a
    mesma razão que trouxe `norm_espaco` para cá.
    """
    return _dpapi("CryptProtectData", dados)


def revelar_bytes(dados: bytes) -> bytes:
    """Decifra o que `proteger_bytes` cifrou. Levanta OSError se não der.

    Falhar é esperado e não é defeito: troca de usuário do Windows ou perfil
    restaurado noutra máquina fazem a DPAPI recusar, e o certo é voltar a
    pedir a senha — nunca tentar adivinhar.
    """
    return _dpapi("CryptUnprotectData", dados)


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


def pasta_do_perfil(nome: str = "") -> Path:
    """A pasta do perfil persistente do Chrome (a sessão logada de banco/ERP).

    Existia em DOIS jeitos: ao lado do MÓDULO (`_AQUI = Path(__file__)...`,
    que muda conforme quem executa é o script ou o exe) e na pasta BASE
    (sempre o mesmo lugar, `util.pasta_base()`, script ou exe). Rodando como
    script, o primeiro jeito faz nascer um SEGUNDO conjunto de perfis dentro
    do repositório — medido em 219 MB de sessão de banco duplicada. É a
    mesma família do defeito que o cadastro em cache já teve aqui (ver
    CLAUDE.md, "O cadastro mora na nuvem"): mais de uma cópia de uma regra de
    CAMINHO é como o app passa a guardar a mesma coisa em lugares diferentes.

    `nome` diferencia perfis quando um módulo precisa de mais de um (o Inter
    tem um login por conta). Limpo para caracteres seguros de pasta e cortado
    em 40 — o nome pode vir de fora (conta digitada por gente), e cortar
    evita montar um caminho longo demais só por causa dele."""
    limpo = re.sub(r"[^A-Za-z0-9_-]+", "_", nome.strip())[:40]
    return pasta_base() / f".chrome_profile{'_' + limpo if limpo else ''}"


# --------------------------------------------------------------- diagnóstico

_handler = None  # o UM RotatingFileHandler que TODO nome de logger compartilha


def log(nome: str) -> logging.Logger:
    """O logger de diagnóstico do app — um arquivo só, para qualquer módulo.

    Hoje o diagnóstico sai por `print()` (que não existe: o exe é
    `--noconsole`, sem janela de terminal, e escrever num `stdout` inexistente
    derruba o app) e por escrita à mão no `diagnostico.log`, cada módulo do
    seu jeito — o `anexar/config.py` tinha o `diag()`; o resto não tinha
    nada. Quando uma máquina de usuário diz só "não abriu", não sobra o que
    consultar. Esta função é a BASE: quem for adotar loga com
    `log(__name__).info(...)` e já ganha arquivo e formato certos — a troca
    módulo a módulo vem em PRs seguintes, não aqui.

    UM `RotatingFileHandler` só, reaproveitado por TODO `nome` que passar por
    aqui — não um handler por módulo. Handler por módulo seria trocar o
    diagnóstico espalhado de hoje por outro igualmente espalhado, só que com
    nomes de arquivo em vez de formatos diferentes. `nome` (normalmente o
    `__name__` de quem chama) entra só no FORMATO da linha, nunca no caminho
    do arquivo — que é sempre `pasta_base() / "diagnostico.log"`, o mesmo
    `pasta_base()` de sempre: ao lado do exe, congelado; na raiz, rodando
    como script.

    Formato "%(asctime)s  %(name)s  %(levelname)s  %(message)s", com o MESMO
    prefixo de data e hora (`dd/mm/aaaa hh:mm:ss`) que o `diagnostico.log` de
    hoje já grava à mão: quem abre o arquivo depois desta troca não estranha
    a parte que costuma olhar primeiro.

    Sem handler de console, de propósito: o exe é `--noconsole`, e um
    `StreamHandler` apontado para um `stdout`/`stderr` que não existe é a
    mesma armadilha do `print()` — derruba o app, não só engasga o log.
    `propagate=False` pela razão contrária: sem isso, o logger raiz (se um
    dia ganhar handler próprio) duplicaria cada linha.

    Chamar com o MESMO `nome` duas vezes devolve o MESMO `Logger` — é o
    `logging.getLogger` de sempre, que já faz esse cache — sem acrescentar um
    segundo handler; quem garante isso é o `if not logger.handlers` abaixo."""
    global _handler
    if _handler is None:
        _handler = RotatingFileHandler(
            pasta_base() / "diagnostico.log", maxBytes=1_000_000,
            backupCount=3, encoding="utf-8")
        _handler.setFormatter(logging.Formatter(
            "%(asctime)s  %(name)s  %(levelname)s  %(message)s",
            datefmt="%d/%m/%Y %H:%M:%S"))
    logger = logging.getLogger(nome)
    if not logger.handlers:
        logger.addHandler(_handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


#: Os meses COMO VIRAM NOME DE PASTA no disco — `.../2026/JULHO/...`.
#:
#: Mora aqui, e não em cada módulo, pela mesma razão do `pasta_base()` logo
#: acima: existia em TRÊS cópias (Conciliação, Extratos Sicoob e Relatório
#: Mensal), e as três produzem caminho de arquivamento. Bastava uma divergir —
#: um "MARCO" sem cedilha — para a Conciliação gravar numa pasta e o Relatório
#: Mensal noutra, que é exatamente a família do defeito que partiu julho/2026
#: ao meio e fez nascer o `conferir_mapas.py`.
#:
#: O par de TELA é o `widgets.MESES` ("Janeiro"), e ele fica lá porque
#: `util.py` não importa tkinter. Que os dois digam a mesma coisa é garantido
#: por teste, não por disciplina.
MESES_PASTA = ("JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO",
               "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO")


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
