# -*- coding: utf-8 -*-
"""O nome do arquivo, no padrão do Separar e Renomear.

    2.980,00 - RPB 24 QD 26A LT 08 OC 6974 - 24-08.pdf

**Chama a função de lá, não copia o padrão.** `separar_renomear.nome_arquivo`
é quem sabe montar esse nome; reproduzi-lo aqui criaria duas verdades que
divergem no dia em que alguém mudar a regra num lado só — e divergem em
silêncio, porque nada quebra: os arquivos só passam a sair diferentes.

Renomear na BAIXA, e não depois: economiza uma passada e evita o erro de
esquecer a passada.

**De onde vem cada campo, e por que não é do PDF.** O Inter entrega valor,
data, descrição, favorecido e pagador no JSON da API — ler o PDF para
descobrir o que já se tem seria trabalho e risco de graça. O Sicoob entrega
valor e data, mas NÃO o favorecido nem a descrição: os dois só existem dentro
do comprovante (a descrição é a linha "Observação"), e é por isso (e só por
isso) que o caminho do Sicoob passa pelo documento.

A descrição vale mais que o favorecido porque é ela que diz A QUE o pagamento
se refere (obra, lote, NF, OC), e é por ela que o nome fica no padrão
VALOR - DESCRIÇÃO - DATA. Até 11/09/2026 o Sicoob só lia o favorecido, e 121
dos 144 comprovantes comuns baixados em 10 e 11/09 saíram com o nome de quem
recebeu, com a descrição escrita no PDF.
"""
from __future__ import annotations

import re
from pathlib import Path

import util

log = util.log(__name__)


def _renomeador():
    """O módulo do Renomear, importado na hora de usar.

    Tardio de propósito: ele carrega `pdfplumber` e `tkinter` no topo, e quem
    só quer baixar comprovante não deve pagar isso na abertura do app."""
    from separar_renomear import separar_renomear

    return separar_renomear


def brl(valor) -> str:
    """`2980.0` -> `2.980,00`. É a forma que o Renomear espera receber."""
    try:
        return f"{float(valor):,.2f}".replace(",", "X").replace(
            ".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return ""


def _valor_de_texto(texto: str) -> str:
    """`R$ 108,39` -> `108,39`. O Inter manda com o cifrão na 2ª via."""
    achado = re.search(r"([\d.]+,\d{2})", str(texto or ""))
    return achado.group(1) if achado else ""


def nomear(campos: dict) -> str:
    """O nome final, sem extensão. "" quando não há como montar."""
    try:
        return _renomeador().nome_arquivo(campos)
    except Exception:                                        # noqa: BLE001
        # Sem os campos na mensagem: eles carregam favorecido, pagador e
        # valor, e o diagnostico.log é um arquivo comum na pasta do exe. O
        # comprovante fica com o nome de origem, e é assim que a falha
        # aparece na pasta — só que sem dizer por quê.
        log.warning("montando o nome final de um comprovante pelo padrão do "
                    "Separar e Renomear", exc_info=True)
        return ""


# ------------------------------------------------------------------- Inter

def do_pix(mov: dict) -> dict:
    """Os campos de um Pix enviado, direto do JSON — sem abrir o PDF."""
    detalhe = mov.get("detalhePix") or {}
    descricao = ""
    for onde in (mov.get("descricao"), detalhe.get("descricaoPagamento"),
                 detalhe.get("campoLivre")):
        if (onde or "").strip():
            descricao = onde.strip()
            break
    return {"valor": brl(mov.get("valor")),
            "data": mov.get("data") or "",
            "desc": descricao or None,
            "dest": (mov.get("nome") or "").strip() or None,
            "pag": (detalhe.get("nomeFantasiaPagador") or "").strip() or None}


def do_2via(item: dict) -> dict:
    """Os campos de um pagamento da 2ª via do Inter."""
    pagamento = item.get("pagamento") or {}
    descricao = (item.get("descricao")
                 or pagamento.get("complementoHistorico") or "").strip()
    return {"valor": _valor_de_texto(item.get("valor")),
            "data": item.get("dataEfetivacao") or "",
            "desc": descricao or None,
            "dest": None,
            "pag": (item.get("nomeRemetente") or "").strip() or None}


# ------------------------------------------------------------------ Sicoob

def favorecido_do_comprovante(texto: str) -> str:
    """Quem recebeu, lido do comprovante do Sicoob.

    Cada tipo escreve num lugar: BOLETO no bloco "Beneficiário", campo
    "Nome/Razão Social"; TRANSFERÊNCIA no bloco "Crédito", na linha da conta
    (`Conta 6.135-2 / ROCHA SANTIAGO ENGENHARIA LTDA`).

    A âncora é o BLOCO, e não o rótulo: "Nome/Razão social" aparece duas vezes
    no comprovante de boleto, e a primeira ocorrência pode ser a do PAGADOR —
    que é justamente quem não interessa aqui.
    """
    linhas = [l.strip() for l in (texto or "").splitlines()]

    for i, linha in enumerate(linhas):
        if re.fullmatch(r"Benefici[áa]rio", linha, re.I):
            for seguinte in linhas[i + 1:i + 4]:
                achado = re.match(r"Nome/Raz[ãa]o [Ss]ocial\s+(.+)", seguinte)
                if achado:
                    return achado.group(1).strip()

    for i, linha in enumerate(linhas):
        if re.fullmatch(r"Cr[ée]dito", linha, re.I):
            for seguinte in linhas[i + 1:i + 4]:
                achado = re.match(r"Conta\s+[\d.\-]+\s*/\s*(.+)", seguinte)
                if achado:
                    return achado.group(1).strip()
    return ""


# "Observação" é como o Sicoob chama o texto livre que quem pagou escreveu;
# "Descrição" entra junto porque é o mesmo campo com outro nome, e custa nada
# aceitar os dois, com ou sem ":". O rótulo pode vir sem valor nenhum na mesma
# linha — ver `descricao_do_comprovante`.
_ROTULO_DA_DESCRICAO = re.compile(
    r"(?:Observa[çc][ãa]o|Descri[çc][ãa]o)(?:\s*:|\s|$)\s*(.*)", re.I)

# Os outros campos do comprovante do Sicoob, lidos nos 146 comprovantes
# comuns de 10 e 11/09/2026. Servem para uma pergunta só: a linha vizinha de
# uma "Observação" sem valor é CONTINUAÇÃO do texto ou já é o campo seguinte?
# Sem a lista, "Autenticação 9f3e..." virava descrição. Sem `re.I` de
# propósito: o rótulo vem em caixa mista e a descrição quase sempre em
# maiúsculas, e é isso que separa "Conta 1.234-5 / ..." de "CONTA DE LUZ".
_ROTULOS_DO_SICOOB = re.compile(
    r"(?:Autentica[çc][ãa]o|Situa[çc][ãa]o|OUVIDORIA|Observa[çc][ãa]o|"
    r"Descri[çc][ãa]o|Valor(?:es)?|Pago|Datas?|Pagamento|Realizado|"
    r"Vencimento|Documento|Juros|Desconto|Outr[oa]s|C[óo]digo|Conv[êe]nio|"
    r"Nome|CPF|N[úu]mero|Cooperativa|Conta|Cliente|Linha|Nosso|"
    r"Institui[çc][ãa]o|Tipo|Pagador|Benefici[áa]rio|Natureza|D[ée]bito|"
    r"Cr[ée]dito)\b")

# Largura da coluna da Observação no comprovante de CONVÊNIO, em caracteres.
# O Sicoob corta o texto nessa largura sem respeitar palavra — medido nos 7
# comprovantes de 10 e 11/09 em que o texto passou de uma linha: a de cima
# tinha sempre 48, e o corte caía no meio de "ITBI" e de "AGO2025".
_LARGURA_DA_OBSERVACAO = 48


def _e_rotulo(linha: str) -> bool:
    return bool(_ROTULOS_DO_SICOOB.match(linha))


def descricao_do_comprovante(texto: str) -> str:
    """O que quem pagou escreveu na "Observação" do comprovante do Sicoob.

    Quase sempre vem na mesma linha do rótulo
    (`Observação TB 19 QD 51 LT 17 NF 8529 OC 6608`). Quando o texto passa da
    largura da coluna, o pdfplumber põe o rótulo SOZINHO no meio das duas
    metades — a primeira na linha de cima, o resto na de baixo:

        OBRA EXEMPLO QD 12 LT 3 45 B1 UC 1234567-8 CONTA
        Observação
        S AGO 2026

    Foram os 7 casos que pareciam "Observação vazia" em 10 e 11/09. Ler só a
    linha de baixo daria "S AGO 2026" como descrição, pior que o favorecido.
    Por isso, com o rótulo sozinho: a linha de baixo é o valor se não for
    outro campo; e a de cima só entra quando a de baixo também entrou, porque
    uma metade de cima sem a de baixo não é um desenho que o comprovante faça.

    As metades se emendam SEM espaço quando a de cima enche a coluna (o corte
    é por caractere) e com espaço quando não enche.

    "" quando não há Observação, ou quando ela está vazia — aí o nome cai no
    favorecido, como antes. Os espaços são normalizados e nada mais: tirar
    rótulo que sobrou e separar código colado é trabalho do Separar e
    Renomear, que recebe este texto em `nome_arquivo`.
    """
    linhas = [l.strip() for l in (texto or "").splitlines()]

    for i, linha in enumerate(linhas):
        achado = _ROTULO_DA_DESCRICAO.match(linha)
        if not achado:
            continue
        valor = achado.group(1).strip()
        if not valor:
            acima = linhas[i - 1] if i > 0 else ""
            abaixo = linhas[i + 1] if i + 1 < len(linhas) else ""
            if abaixo and not _e_rotulo(abaixo):
                valor = abaixo
                if acima and not _e_rotulo(acima):
                    cola = ("" if len(acima) >= _LARGURA_DA_OBSERVACAO
                            else " ")
                    valor = acima + cola + abaixo
        valor = " ".join(valor.split())
        if valor:
            return valor
    return ""


def data_do_comprovante(texto: str) -> str:
    """A data do PAGAMENTO, e não a da impressão.

    O topo do comprovante traz "31/08/2026 12:04:52", que é quando o arquivo
    foi gerado. Foi essa que o parser do Renomear pegou ao ler estes PDFs, e
    por isso os 23 saíram carimbados com a data de hoje.

    O comprovante de CONVÊNIO escreve "Data do pagamento", com "p" minúsculo,
    e o primeiro padrão não o via: os 23 convênios de 10 e 11/09/2026 caíam
    na data do JSON em vez da do documento."""
    for padrao in (r"Pagamento\s+(\d{2}/\d{2}/\d{4})",
                   r"Data do pagamento\s+(\d{2}/\d{2}/\d{4})",
                   r"Data do lan[çc]amento\s+(\d{2}/\d{2}/\d{4})",
                   r"Realizado\s+(\d{2}/\d{2}/\d{4})"):
        achado = re.search(padrao, texto or "")
        if achado:
            return achado.group(1)
    return ""


def texto_do_pdf(caminho) -> str:
    """A primeira página em texto. "" quando não dá para ler.

    Nunca levanta: um PDF ilegível vira arquivo com o nome de origem, que é
    achável. Derrubar o lote por causa de um nome seria trocar o problema
    pequeno pelo grande."""
    try:
        import pdfplumber

        with pdfplumber.open(caminho) as doc:
            return doc.pages[0].extract_text() or ""
    except Exception:                                        # noqa: BLE001
        return ""


def do_sicoob(item: dict, texto: str) -> dict:
    """Valor e data do JSON (certos); descrição e favorecido do documento (só
    lá existem).

    A data também é conferida no documento: o JSON traz `dataLancamento`, e o
    comprovante traz a do pagamento — quando as duas existem, vale a do
    documento, que é o que o banco afirma no papel.

    Com a descrição preenchida, é ela que vai para o meio do nome; sem ela,
    o `nome_arquivo` cai no favorecido. A precedência é do Separar e
    Renomear, e não daqui."""
    valor = item.get("valorLancamento")
    return {"valor": brl(valor) or _valor_de_texto(valor),
            "data": data_do_comprovante(texto)
            or _data_do_item(item.get("dataLancamento")),
            "desc": descricao_do_comprovante(texto) or None,
            "dest": favorecido_do_comprovante(texto) or None,
            "pag": None}


def _numero_brl(texto) -> float | None:
    """`"1208,36"` ou `"90.000,00"` -> `float`. Formato brasileiro (ponto
    separa milhar, vírgula separa decimal) -- é como o campo `valor` do Pix
    do Sicoob chega, ao contrário do Inter, que manda número puro."""
    bruto = str(texto or "").strip()
    if not bruto:
        return None
    try:
        return float(bruto.replace(".", "").replace(",", ".")
                     if "," in bruto else bruto)
    except ValueError:
        return None


def do_sicoob_pix(item: dict) -> dict:
    """Os campos de um Pix enviado do Sicoob, direto do JSON do
    `/api/pix/lancamentos/<id>/comprovante` -- ao contrário do Sicoob comum
    (`do_sicoob`), aqui não é preciso abrir PDF nenhum: o banco entrega
    pagador, destinatário, valor e data já estruturados, e é a PRÓPRIA
    ausência de um comprovante pronto (HTML ou PDF) que torna isso possível
    -- ver `sicoob_baixar.html_do_comprovante_pix`.

    Sem descrição: o JSON do Pix do Sicoob não traz nenhum campo de texto
    livre equivalente ao `descricaoPagamento`/`campoLivre` do Inter."""
    destino = item.get("destino") or {}
    valor = _numero_brl(item.get("valor"))
    return {"valor": brl(valor) if valor is not None else "",
            "data": _data_do_item(item.get("criadoEm")
                                  or item.get("atualizadoEm")),
            "desc": None,
            "dest": (destino.get("nome") or "").strip() or None,
            "pag": None}


def _data_do_item(texto: str) -> str:
    """`2026-08-24 00:00:00.0` -> `24/08/2026`."""
    achado = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", str(texto or ""))
    if not achado:
        return ""
    ano, mes, dia = achado.groups()
    return f"{dia}/{mes}/{ano}"


# ------------------------------------------------------------- o arquivo

def renomear(caminho: Path, campos: dict) -> Path:
    """Renomeia o arquivo já gravado. Devolve o novo caminho — ou o antigo.

    Falhar aqui NUNCA perde comprovante: sem nome montável, ou com o disco
    recusando, o arquivo fica onde está, com o nome de origem. Ele é achável
    assim; o que não se pode é sumir com ele por causa de um nome.

    O desempate segue o do Renomear — ` (2)`, ` (3)` —, e não o `_1` do
    downloader: dois arquivos com o mesmo nome final vêm do mesmo padrão, e
    quem os vê na pasta espera a numeração de lá.
    """
    base = nomear(campos)
    if not base:
        return caminho
    alvo = caminho.parent / f"{base}.pdf"
    n = 2
    while alvo.exists():
        alvo = caminho.parent / f"{base} ({n}).pdf"
        n += 1
    try:
        return caminho.rename(alvo)
    except OSError:
        return caminho
