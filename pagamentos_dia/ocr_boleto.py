# -*- coding: utf-8 -*-
"""Linha digitável de boleto que veio como IMAGEM (PDF sem camada de texto).

Metade dos boletos que os fornecedores anexam é foto ou digitalização: o
`pdfplumber` devolve string vazia e a planilha saía com "Boleto em imagem —
preencher manual". O Tesseract já viaja dentro do exe (é o mesmo OCR do
Separar e Renomear), então falta só ler e — a parte que importa — DESCONFIAR
do que leu.

POR QUE NÃO BASTA "O OCR LEU"
-----------------------------
Uma linha digitável tem 47 ou 48 dígitos e paga sozinha: um `8` lido como `B`
e o dinheiro vai para outro lugar, sem erro na tela e sem volta. Por isso um
número só é aceito depois de passar por DUAS provas independentes:

1. **Dígitos verificadores.** Boleto bancário tem quatro (um por campo mais o
   geral); ficha de arrecadação tem quatro (um por bloco). Errar um dígito
   qualquer derruba pelo menos um DV.
2. **O valor bate com o lançamento.** A própria linha carrega o valor em
   centavos. Conferir contra o que o ERP mandou pagar fecha o cerco: para um
   número errado passar, ele teria de errar E continuar somando certo E
   codificar exatamente o mesmo valor.

Reprovou, a linha volta a ser "preencher manual" — que é chato, mas é o
comportamento de hoje. Recusar leitura duvidosa é a única falha aceitável
aqui; aceitar leitura errada não é.
"""
from __future__ import annotations

import datetime as _dt
import io
import re

#: O OCR troca letra por dígito nos tipos condensados do boleto. Aplicar o
#: mapa inteiro e deixar o DV julgar é mais seguro do que adivinhar caso a
#: caso: chute errado não passa nas provas acima.
_CONFUSOES = str.maketrans({"O": "0", "o": "0", "Q": "0", "D": "0",
                            "l": "1", "I": "1", "i": "1", "|": "1",
                            "S": "5", "s": "5", "B": "8", "Z": "2",
                            "G": "6", "T": "7"})

_PESOS_MOD11 = (2, 3, 4, 5, 6, 7, 8, 9)


# --------------------------------------------------------------------------
# Dígitos verificadores
# --------------------------------------------------------------------------
def _mod10(bloco: str) -> int:
    """FEBRABAN módulo 10: pesos 2 e 1 alternados, da direita para a esquerda,
    somando os ALGARISMOS do produto (produto 12 soma 3, não 12)."""
    soma, peso = 0, 2
    for d in reversed(bloco):
        p = int(d) * peso
        soma += p if p < 10 else p - 9
        peso = 1 if peso == 2 else 2
    return (10 - soma % 10) % 10


def _soma_mod11(bloco: str) -> int:
    return sum(int(d) * _PESOS_MOD11[i % 8] for i, d in enumerate(reversed(bloco)))


def _mod11_arrecadacao(bloco: str) -> int:
    """Módulo 11 da ficha de arrecadação: só resto 0 e 1 zeram o DV.

    Resto 10 dá DV **1**, e não 0 — conferido contra guias reais de IPTU e
    ISS da Prefeitura de Goiânia, onde dois dos oito blocos caem justo nesse
    resto. Zerar os dois casos (como o DV geral do boleto bancário faz, logo
    abaixo) reprovava guia legítima.
    """
    resto = _soma_mod11(bloco) % 11
    return 0 if resto in (0, 1) else 11 - resto


def _mod11_geral(barra43: str) -> int:
    """DV geral do código de barras bancário: 0, 10 e 11 viram 1 (e não 0)."""
    dv = 11 - _soma_mod11(barra43) % 11
    return 1 if dv in (0, 10, 11) else dv


# --------------------------------------------------------------------------
# Boleto bancário (47 dígitos)
# --------------------------------------------------------------------------
def _valida_bancario(d: str) -> bool:
    campo1, campo2, campo3 = d[0:10], d[10:21], d[21:32]
    if _mod10(campo1[:9]) != int(campo1[9]):
        return False
    if _mod10(campo2[:10]) != int(campo2[10]):
        return False
    if _mod10(campo3[:10]) != int(campo3[10]):
        return False
    # O DV geral fecha sobre o código de BARRAS, que é a linha digitável
    # remontada: banco+moeda, fator+valor, e só então o campo livre.
    barra43 = d[0:4] + d[33:47] + campo1[4:9] + campo2[:10] + campo3[:10]
    return _mod11_geral(barra43) == int(d[32])


def _valor_bancario(d: str) -> float:
    return int(d[37:47]) / 100.0


# --------------------------------------------------------------------------
# Ficha de arrecadação / convênio (48 dígitos, começa em 8)
# --------------------------------------------------------------------------
def _valida_arrecadacao(d: str) -> bool:
    """Quatro blocos de 11 dígitos + DV.

    O terceiro dígito diz se o DV é módulo 10 ou 11, mas concessionária
    emitindo fora do padrão existe — então, se o indicado falhar, o outro é
    tentado. Os QUATRO blocos precisam fechar pelo MESMO módulo: aceitar
    mistura seria aceitar quase qualquer número.
    """
    blocos = [d[i:i + 12] for i in range(0, 48, 12)]
    indicado = _mod11_arrecadacao if d[2] in "89" else _mod10
    for calc in (indicado, _mod10 if indicado is not _mod10 else _mod11_arrecadacao):
        if all(calc(b[:11]) == int(b[11]) for b in blocos):
            return True
    return False


def _valor_arrecadacao(d: str) -> float:
    barra = "".join(d[i:i + 11] for i in range(0, 48, 12))
    return int(barra[4:15]) / 100.0


# --------------------------------------------------------------------------
# API do módulo
# --------------------------------------------------------------------------
def digitos(linha: str) -> str:
    return re.sub(r"\D", "", linha or "")


def valida(linha: str) -> bool:
    """True se os dígitos verificadores fecham. Não olha valor."""
    d = digitos(linha)
    if len(d) == 47:
        return _valida_bancario(d)
    if len(d) == 48 and d[0] == "8":
        return _valida_arrecadacao(d)
    return False


def valor_da_linha(linha: str) -> float | None:
    d = digitos(linha)
    try:
        if len(d) == 47:
            return _valor_bancario(d)
        if len(d) == 48 and d[0] == "8":
            return _valor_arrecadacao(d)
    except ValueError:
        return None
    return None


def formatar(linha: str) -> str:
    """Nos grupos que a pessoa vê no boleto — é assim que ela confere."""
    d = digitos(linha)
    if len(d) == 47:
        return (f"{d[0:5]}.{d[5:10]} {d[10:15]}.{d[15:21]} "
                f"{d[21:26]}.{d[26:32]} {d[32]} {d[33:47]}")
    if len(d) == 48:
        return " ".join(f"{d[i:i + 11]}-{d[i + 11]}" for i in range(0, 48, 12))
    return (linha or "").strip()


def confere_valor(linha: str, valor_esperado: float, tolerancia: float = 0.01) -> bool:
    """O valor embutido na linha bate com o que o ERP mandou pagar?

    Boleto emitido sem valor (zerado, a combinar) não confere — e não deve
    mesmo: quem preenche o valor à mão preenche a linha à mão também.
    """
    v = valor_da_linha(linha)
    if not v or not valor_esperado:
        return False
    return abs(v - float(valor_esperado)) <= tolerancia


def linha_confiavel(linha: str, valor_esperado: float) -> bool:
    """As duas provas. Só o que passa aqui vai para a planilha."""
    return valida(linha) and confere_valor(linha, valor_esperado)


#: Base do "fator de vencimento" da Febraban: fator 1000 = 03/07/2000. O campo
#: tem 4 dígitos e estourou em 21/02/2025 (fator 9999); a partir de 22/02/2025
#: ele voltou a 1000. Por isso um fator BAIXO hoje significa a segunda volta, e
#: não um vencimento de 2000 — daí a segunda base.
_FATOR_BASE = _dt.date(2000, 7, 3)
_FATOR_BASE_2A_VOLTA = _dt.date(2025, 2, 22)
#: A partir de quando um fator pequeno passa a ser lido como segunda volta. É
#: a data em que a primeira volta acabou; antes dela, fator baixo era 2000.
_VIRADA = _dt.date(2025, 2, 22)


def eh_arrecadacao(linha: str) -> bool:
    """Ficha de arrecadação (48 dígitos, começando em 8) e não boleto bancário.

    São coisas diferentes com aparências parecidas: a ficha paga tributo,
    concessionária ou órgão público, não tem cedente nem vencimento, e no CNAB
    240 é outro PRODUTO (segmento O, forma 11) — não o segmento J dos títulos.
    Distinguir aqui é o que impede as duas de irem pelo mesmo caminho.
    """
    d = digitos(linha)
    return len(d) == 48 and d[:1] == "8" and _valida_arrecadacao(d)


def vencimento_da_linha(linha: str, hoje: _dt.date | None = None) -> _dt.date | None:
    """A data de vencimento embutida no código de barras, ou None.

    Só o boleto BANCÁRIO carrega vencimento: a ficha de arrecadação (48
    dígitos, começando em 8) não tem o campo, e devolve None em vez de uma
    data inventada.

    Fator `0000` significa "sem vencimento" (boleto a combinar) e também é
    None — zero não é uma data.
    """
    d = digitos(linha)
    if len(d) != 47 or not _valida_bancario(d):
        return None
    fator = int(d[33:37])
    if fator == 0:
        return None
    hoje = hoje or _dt.date.today()
    base = _FATOR_BASE_2A_VOLTA if hoje >= _VIRADA else _FATOR_BASE
    return base + _dt.timedelta(days=fator - 1000)


def codigo_de_barras(linha: str) -> str:
    """Os 44 dígitos do código de barras, a partir da linha digitável.

    A planilha mostra a LINHA DIGITÁVEL — 47 dígitos no boleto bancário, 48 na
    ficha de arrecadação —, que é a versão feita para gente digitar: ela
    reordena o código de barras e intercala dígitos verificadores de bloco. A
    remessa CNAB quer o código de barras cru, de 44, e o segmento J recusa
    qualquer outro tamanho.

    A conversão é um rearranjo, sem conta nenhuma:

        bancário (47)    banco+moeda, DV geral, fator+valor, e o campo livre
                         remontado dos três blocos (tirando o DV de cada um)
        arrecadação (48) quatro blocos de 11, jogando fora o DV de cada bloco

    Devolve "" para linha que não fecha nos dígitos verificadores. Não é zelo
    de sobra: a linha pode ter vindo de OCR, e um dígito trocado aqui vira um
    pagamento para outra pessoa sem erro na tela e sem volta.
    """
    d = digitos(linha)
    if not valida(d):
        return ""
    if len(d) == 47:
        return d[0:4] + d[32] + d[33:47] + d[4:9] + d[10:20] + d[21:31]
    return d[0:11] + d[12:23] + d[24:35] + d[36:47]


# --------------------------------------------------------------------------
# Achar a linha no texto do OCR
# --------------------------------------------------------------------------
def achar_linha_digitavel(texto: str, valor_esperado: float) -> str:
    """A linha digitável confiável dentro de um texto de OCR, ou "".

    Varre linha a linha (e o texto inteiro colado, para o caso de o OCR ter
    quebrado o número no meio), tenta com e sem o mapa de confusões, e só
    devolve o que passa nas duas provas.
    """
    if not texto:
        return ""
    candidatos = [t for t in texto.splitlines() if sum(c.isdigit() for c in t) >= 20]
    candidatos.append(texto)
    for bruto in candidatos:
        for tentativa in (bruto, bruto.translate(_CONFUSOES)):
            d = digitos(tentativa)
            for tamanho in (47, 48):
                for i in range(0, max(len(d) - tamanho, 0) + 1):
                    trecho = d[i:i + tamanho]
                    if linha_confiavel(trecho, valor_esperado):
                        return formatar(trecho)
    return ""


# --------------------------------------------------------------------------
# OCR
# --------------------------------------------------------------------------
def texto_ocr_pdf(dados: bytes, log=print, limite_paginas: int = 3) -> str:
    """OCR das primeiras páginas de um PDF sem camada de texto.

    Mesmo caminho do `separar_renomear` e do `contratos`. O limite existe
    porque a linha digitável mora na primeira página do boleto: varrer um
    anexo de 40 páginas para achá-la custaria meio minuto por título.
    Falha aqui não é erro — devolve vazio, e a planilha segue pedindo o
    preenchimento manual.
    """
    if not dados:
        return ""
    try:
        import pdfplumber
    except ImportError:                                   # pragma: no cover
        return ""
    try:
        from separar_renomear import _ocr_pagina
    except Exception:                                     # pragma: no cover
        return ""
    try:
        with pdfplumber.open(io.BytesIO(dados)) as pl:
            return "\n".join(_ocr_pagina(pg, log)
                             for pg in pl.pages[:limite_paginas])
    except Exception:
        return ""


def texto_ocr_imagem(dados: bytes) -> str:
    """OCR de anexo que é foto (jpg/png) — o caso dos avisos "PAGAR PARA"."""
    if not dados:
        return ""
    try:
        import pytesseract
        from PIL import Image
        from separar_renomear import _OCR, _ocr_disponivel
    except Exception:                                     # pragma: no cover
        return ""
    if not _ocr_disponivel(lambda *_: None):
        return ""
    try:
        with Image.open(io.BytesIO(dados)) as img:
            return pytesseract.image_to_string(img, lang=_OCR["lang"])
    except Exception:
        return ""
