# -*- coding: utf-8 -*-
"""Confere o segmento O campo a campo contra o guia v3.3, seção 9.2.

    python -m cnab240.ferramentas.conferir_segmento_o [--app PASTA]

Gera uma remessa com UMA ficha de arrecadação pelo caminho novo do app —
`preparar` -> `montar_arquivo` —, roda o `cnab240/validador.py` e depois mede
cada campo do segmento O e do header do lote contra a TABELA DO GUIA,
transcrita aqui.

Por que a tabela é transcrita e não lida do `cnab240/spec`: conferir o
arquivo contra a mesma spec que o gerou é o arquivo concordando consigo mesmo.
As posições abaixo foram copiadas do PDF (seções 9.1 e 9.2) — se a spec tiver
um campo fora de lugar, é aqui que aparece.

Grava o .REM para o `Validar` do SicoobNet, com NSA fixo — NÃO consome o
contador de produção. Não transmite: quem envia é você, depois de conferir.
"""
from __future__ import annotations

import argparse
import datetime as dt

from ._ambiente import (contas_mc, exigir, ficha_sintetica, ocr_boleto,
                        pasta_do_app, remessa_dia, sicoob_contas)

from cnab240 import relatorio as rel_cnab, validar

NSA_TESTE = 990002
VALOR = 2670.86
#: Ficha de arrecadação do ramo de saneamento: 48 dígitos começando em 8, DVs
#: fechando. Não aponta para conta nenhuma — é forma válida com conteúdo
#: inexistente —, e o 2º dígito escolhe o RAMO, não a empresa.
LINHA_FICHA = ficha_sintetica(round(VALOR * 100), segmento="2")
#: O nome vai para o campo 09.3O, que tem 30 posições. Aqui ele é inventado de
#: propósito: quem roda a ferramenta está medindo LARGURA e POSIÇÃO de campo,
#: e o nome da concessionária de verdade não acrescenta nada à medição.
FAVORECIDO = "CONCESSIONARIA DE TESTE SA"

#: Guia CNAB 240 Sicoob v3.3 (2025-05-19), seção 9.2 — Detalhe Segmento O.
#: (campo, de, até, dígitos, o que o guia manda)
SEGMENTO_O = [
    ("01.3O Banco",              1,   3,  3, "756"),
    ("02.3O Lote de serviço",    4,   7,  4, "o número do lote"),
    ("03.3O Tipo de registro",   8,   8,  1, "3"),
    ("04.3O Nº do registro",     9,  13,  5, "sequencial no lote"),
    ("05.3O Segmento",          14,  14,  1, "O"),
    ("06.3O Tipo de movimento", 15,  15,  1, "0 = inclusão"),
    ("07.3O Cód. da instrução", 16,  17,  2, "00"),
    ("08.3O Código de barras",  18,  61, 44, "os 44 dígitos da ficha"),
    ("09.3O Concessionária",    62,  91, 30, "nome, alfanumérico"),
    ("10.3O Data vencimento",   92,  99,  8, "DDMMAAAA (nominal)"),
    ("11.3O Data pagamento",   100, 107,  8, "DDMMAAAA"),
    ("12.3O Valor pagamento",  108, 122, 15, "centavos, com zeros à esquerda"),
    ("13.3O Seu número",       123, 142, 20, "atribuído pela empresa"),
    ("14.3O Nosso número",     143, 162, 20, "atribuído pelo banco"),
    ("15.3O CNAB",             163, 230, 68, "brancos"),
    ("16.3O Ocorrências",      231, 240, 10, "brancos na remessa"),
]

#: Seção 9.1 — Header de lote de convênios/tributos. Só o que muda em relação
#: ao header de um lote comum; o resto o validador já cobre.
HEADER_LOTE = [
    ("05.1 Tipo de serviço",    10, 11, 2, "22 = contas/tributos/impostos"),
    ("06.1 Forma lançamento",   12, 13, 2, "11 = com código de barras"),
    ("07.1 Versão do layout",   14, 16, 3, "012"),
]


def _campo(linha: str, de: int, ate: int) -> str:
    """O guia numera as posições a partir de 1, e as duas pontas inclusive."""
    return linha[de - 1:ate]


def _confere(linha: str, tabela, esperados: dict) -> int:
    erros = 0
    for rotulo, de, ate, digitos, manda in tabela:
        valor = _campo(linha, de, ate)
        largura_ok = len(valor) == digitos
        alvo = esperados.get(rotulo.split()[0])
        conteudo_ok = alvo is None or valor == alvo
        marca = "  ok " if (largura_ok and conteudo_ok) else "  !! "
        erros += 0 if (largura_ok and conteudo_ok) else 1
        print(f"{marca}{rotulo:26} {de:>3}-{ate:<3} ({digitos:>2}) "
              f"[{valor}]")
        if not largura_ok:
            print(f"       ^ largura {len(valor)}, o guia manda {digitos}")
        if not conteudo_ok:
            print(f"       ^ o guia manda {manda!r}; esperado {alvo!r}")
    return erros


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="conferência do segmento O")
    ap.add_argument("--app", default="", help="pasta da instalação (cadastro)")
    args = ap.parse_args(argv)

    hoje = dt.date.today()
    app = pasta_do_app(args.app)
    mapa = contas_mc.carregar(exigir(app / "contas_mc.json"))
    empresas = sicoob_contas.carregar(exigir(app / "contas_sicoob.json")).empresas

    pagador = conta_erp = None
    for conta in [d.erp for d in mapa.destinos]:
        p, _motivo = remessa_dia.resolver_pagador(conta, mapa, empresas)
        if p is not None:
            pagador, conta_erp = p, conta
            break
    if pagador is None:
        print("[!] nenhuma conta resolveu para um pagador Sicoob.")
        return 1

    print(f"empresa  : {pagador.empresa}   convênio {pagador.convenio}")
    print(f"conta    : ag {pagador.agencia}-{pagador.dv_agencia} / "
          f"{pagador.conta}-{pagador.dv_conta}")
    print(f"favorecido: {FAVORECIDO}")
    print(f"valor    : R$ {VALOR:,.2f}".replace(",", "X").replace(".", ",")
          .replace("X", "."))

    registro = {"tipo": "Boleto", "dados": LINHA_FICHA, "valor": VALOR,
                "descricao": "TESTE DE LAYOUT - ARRECADACAO",
                "favorecido": FAVORECIDO,
                "status": "APTO", "conferencia": "", "obs": "",
                "id": "conferencia-segmento-o", "parcial": False,
                "oc": "", "centro_custo": ""}
    preparado = remessa_dia.preparar({conta_erp: [registro]},
                                     quando=hoje)[conta_erp]
    c, = preparado
    print(f"\no `preparar` disse: arrecadação={c.arrecadacao}  "
          f"pode={c.pode}  marcado={c.marcado}"
          + (f"  impedimento={c.impedimento}" if c.impedimento else ""))
    if not (c.arrecadacao and c.pode and c.marcado):
        print("[!] a ficha não entrou — não há o que conferir.")
        return 1

    arquivo = remessa_dia.montar_arquivo(pagador, [c], nsa=NSA_TESTE,
                                         quando=hoje)
    linhas = arquivo.gerar()

    # ------------------------------------------------------------ validador
    problemas = validar(linhas)
    print(f"\nvalidador (cnab240/validador.py): {rel_cnab(problemas)}")
    for pr in problemas:
        print("   -", pr)

    # ----------------------------------------------- conferência campo a campo
    header, = [l for l in linhas if l[7:8] == "1"]
    o, = [l for l in linhas if l[7:8] == "3" and l[13:14] == "O"]
    barras = ocr_boleto.codigo_de_barras(LINHA_FICHA)
    centavos = f"{round(VALOR * 100):015d}"

    print("\n--- header do lote (guia v3.3, seção 9.1) " + "-" * 30)
    erros = _confere(header, HEADER_LOTE, {
        "05.1": "22", "06.1": "11", "07.1": "012",
    })

    print("\n--- segmento O (guia v3.3, seção 9.2) " + "-" * 34)
    erros += _confere(o, SEGMENTO_O, {
        "01.3O": "756",
        "03.3O": "3",
        "05.3O": "O",
        "08.3O": barras,
        "10.3O": "00000000",
        "11.3O": f"{hoje:%d%m%Y}",
        "12.3O": centavos,
        "15.3O": " " * 68,
        "16.3O": " " * 10,
    })

    print("\n--- as três provas que o layout sozinho não dá " + "-" * 25)
    provas = [
        ("o código de barras é o da linha digitável",
         _campo(o, 18, 61) == barras),
        ("os 44 dígitos são só dígitos",
         _campo(o, 18, 61).isdigit()),
        ("a ficha começa em 8 (arrecadação, não boleto bancário)",
         _campo(o, 18, 61).startswith("8")),
        ("o valor do arquivo é o valor do lançamento",
         int(_campo(o, 108, 122)) == round(VALOR * 100)),
        ("o nome da concessionária cabe nas 30 posições",
         _campo(o, 62, 91).strip() == FAVORECIDO[:30].strip()),
        ("toda linha tem 240 posições",
         all(len(l) == 240 for l in linhas)),
        ("o lote da ficha é SÓ dela (nenhum segmento J junto)",
         not [l for l in linhas if l[3:7] == o[3:7] and l[13:14] == "J"]),
    ]
    for texto, ok in provas:
        print(f"  {'ok ' if ok else '!! '} {texto}")
        erros += 0 if ok else 1

    print("\n" + "=" * 70)
    if erros or problemas:
        print(f"REPROVOU: {erros} campo(s) fora do guia, "
              f"{len(problemas)} problema(s) no validador.")
        return 1
    print("APROVOU: validador limpo e todos os campos conferem com o guia.")

    # Grava para o `Validar` do SicoobNet ter o que receber. Quem escreve é o
    # `salvar` da própria biblioteca: ele já sabe a codificação e o fim de
    # linha que o banco espera, e refazer isso à mão aqui seria uma segunda
    # regra sobre o mesmo arquivo.
    # Nome próprio, e não o do teste nº 3: os dois gravam ficha de arrecadação
    # na MESMA pasta, e um sobrescrever o arquivo do outro apagaria a prova
    # que se acabou de produzir.
    caminho = app / "CONFERENCIA_SEGMENTO_O_NAO_ENVIAR.REM"
    arquivo.salvar(caminho)
    print()
    print(f"arquivo : {caminho.name}  ({len(linhas)} linhas de 240)")
    print(f"NSA     : {NSA_TESTE} (fixo — o remessas.json não foi tocado)")
    print()
    print("caminho completo:")
    print(f"  {caminho}")
    print()
    print("A transmissão é sua: SicoobNet → Empresarial → Arquivos CNAB 240")
    print("→ Envio de Arquivos → Validar.  Só depois, se quiser, Enviar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
