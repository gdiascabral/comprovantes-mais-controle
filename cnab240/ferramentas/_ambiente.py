# -*- coding: utf-8 -*-
"""Onde estas ferramentas acham o app, e a prova de que só existe UM `cnab240`.

Duas coisas, e as duas pelo mesmo motivo.

**O caminho de import.** As pastas de aba do app (`pagamentos_dia`,
`relatorios`, `extratos_sicoob`) não são pacotes: `remessa_dia` importa
`ocr_boleto` pelo nome curto, e quem põe essas pastas no `sys.path` é o
`comprovantes_app.py` quando roda como script. Ferramenta que quer percorrer o
caminho REAL do app precisa montar o mesmo `sys.path` — e monta-o a partir do
`__file__`, nunca de um caminho absoluto escrito à mão. Caminho escrito à mão
foi o que amarrou estes scripts à máquina de uma pessoa, e à cópia velha da
biblioteca que morava nela.

**A conferência de fonte única.** Depois de arrumar o caminho, `_uma_fonte_so`
pergunta de ONDE o `cnab240` foi importado e exige que seja o deste
repositório. Parece paranoia; é a lição de 20/08/2026. Havia duas cópias do
pacote, a de fora parou em 14/08 sem `dv_cpf`/`dv_cnpj`/`documento_valido`, e
uma ferramenta que aponta para a cópia errada aprova um arquivo que o banco
recusa — o pior resultado possível para uma ferramenta cujo trabalho é dizer
"pode enviar".

**Os instrumentos sintéticos.** `boleto_sintetico` e `ficha_sintetica` fabricam
linha digitável com todos os dígitos verificadores fechando e que não aponta
para título nenhum. Precisam fechar porque o `preparar` recusa linha que não
fecha (é a mesma trava que protege leitura de OCR), e precisam ser inventadas
porque um boleto de verdade num repositório público é um pedido de pagamento
publicado. Ficam aqui, e não em cada script, para as três ferramentas que
usam boleto usarem a MESMA regra.
"""
from __future__ import annotations

import sys
from pathlib import Path

#: A raiz do repositório. Este arquivo mora em `cnab240/ferramentas/`, então
#: são dois níveis acima — a mesma conta que o `util.pasta_base()` faz com um.
RAIZ = Path(__file__).resolve().parents[2]

#: A raiz mais as pastas de aba que o app põe no caminho quando roda como
#: script. A lista é a MENOR que faz os quatro scripts importarem.
_PASTAS = ("", "pagamentos_dia", "relatorios", "extratos_sicoob")


def _preparar_caminho() -> None:
    """Só pastas DESTE repositório, todas derivadas do `__file__`."""
    for nome in _PASTAS:
        pasta = RAIZ / nome if nome else RAIZ
        if pasta.is_dir() and str(pasta) not in sys.path:
            sys.path.insert(0, str(pasta))


_preparar_caminho()

import cnab240                                                  # noqa: E402
import contas_mc                                                # noqa: E402
import ocr_boleto                                               # noqa: E402
import remessa_dia                                              # noqa: E402
import sicoob_contas                                            # noqa: E402
import util                                                     # noqa: E402


def _uma_fonte_so() -> None:
    """O `cnab240` importado é o deste repositório, ou o script para aqui."""
    de_onde = Path(cnab240.__file__).resolve().parent
    esperado = RAIZ / "cnab240"
    if de_onde != esperado:
        raise SystemExit(
            f"[!] o `cnab240` foi importado de {de_onde}, e não de {esperado}.\n"
            "    Há uma segunda cópia do pacote no caminho de import. A "
            "ferramenta seria capaz de aprovar um arquivo que o banco recusa; "
            "prefiro não responder a responder errado.")


_uma_fonte_so()


def pasta_do_app(indicada: str = "") -> Path:
    """Onde moram `contas_sicoob.json`, `contas_mc.json` e `remessas.json`.

    Sem argumento é a regra que o app inteiro usa (`util.pasta_base()`): a
    pasta do exe quando congelado, a raiz do projeto quando script. Uma regra
    de caminho só, e não mais uma — foi assim que o `pasta_base` nasceu.
    Com argumento (a opção `--app` dos scripts), aponta para a instalação que
    tem o cadastro de verdade.
    """
    if indicada:
        pasta = Path(indicada).expanduser().resolve()
        if not pasta.is_dir():
            raise SystemExit(f"[!] --app: {pasta} não é uma pasta")
        return pasta
    return util.pasta_base()


def exigir(caminho: Path) -> Path:
    """O arquivo de cadastro, ou uma recusa que diz onde ele deveria estar."""
    if not caminho.is_file():
        raise SystemExit(
            f"[!] não achei {caminho.name} em {caminho.parent}.\n"
            "    Ele fica FORA do repositório (nome de empresa e número de "
            "conta). Aponte a instalação com --app <pasta>.")
    return caminho


# --------------------------------------------------------------- sintéticos
def barcode_sintetico(centavos: int) -> str:
    """Código de barras bancário (44) com DV geral fechando e sem dono.

    Banco 756, sem fator de vencimento e campo livre óbvio: quem olhar vê na
    hora que não é boleto de ninguém. O DV geral precisa fechar para o teste
    medir o LAYOUT, e não morrer antes num erro de dígito verificador.
    """
    base = "7569" + "0000" + f"{centavos:010d}" + "1" * 25
    barras = base[:4] + str(ocr_boleto._mod11_geral(base)) + base[4:]
    if len(barras) != 44:
        raise AssertionError(f"código de barras com {len(barras)} dígitos")
    return barras


def boleto_sintetico(centavos: int) -> str:
    """Linha digitável bancária (47) com os quatro DVs fechando.

    É o `barcode_sintetico` remontado no formato que gente digita: três blocos
    com módulo 10 cada, o DV geral no meio, fator e valor no fim.
    """
    barras = barcode_sintetico(centavos)
    livre = barras[19:44]
    c1 = barras[0:4] + livre[0:5]
    c2, c3 = livre[5:15], livre[15:25]
    linha = (c1 + str(ocr_boleto._mod10(c1))
             + c2 + str(ocr_boleto._mod10(c2))
             + c3 + str(ocr_boleto._mod10(c3))
             + barras[4] + barras[5:19])
    if len(linha) != 47 or not ocr_boleto.valida(linha):
        raise AssertionError("linha digitável sintética não fecha")
    return linha


def ficha_sintetica(centavos: int, segmento: str = "2") -> str:
    """Linha digitável de ARRECADAÇÃO (48) que não aponta para conta nenhuma.

    Quatro blocos de onze dígitos, cada um com o seu DV — o mesmo desenho da
    ficha de verdade, com conteúdo inventado. O 3º dígito é `8` (valor efetivo
    em reais), que é o que manda o `_valida_arrecadacao` conferir os blocos por
    módulo 11; o `_mod11_arrecadacao` do app é a autoridade, para a ficha
    sintética e a de verdade fecharem pela MESMA conta.

    `segmento` é o 2º dígito (2 = saneamento, 3 = energia, 1 = prefeitura). Ele
    escolhe o RAMO, não a empresa: nenhuma concessionária real é nomeada aqui.
    """
    # O 4º dígito é o DV geral do código de barras; o `_valida_arrecadacao` não
    # o confere (só os DVs de bloco), mas ele é calculado assim mesmo — deixar
    # um dígito de enfeite numa ferramenta de conferência convida a confusão.
    corpo = "8" + segmento + "8" + f"{centavos:011d}" + "0000" + "1" * 25
    barras = corpo[:3] + str(ocr_boleto._mod11_arrecadacao(corpo)) + corpo[3:]
    if len(barras) != 44:
        raise AssertionError(f"ficha com {len(barras)} dígitos")
    blocos = [barras[i:i + 11] for i in range(0, 44, 11)]
    linha = "".join(b + str(ocr_boleto._mod11_arrecadacao(b)) for b in blocos)
    if len(linha) != 48 or not ocr_boleto.valida(linha):
        raise AssertionError("ficha sintética não fecha")
    return linha
