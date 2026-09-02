# -*- coding: utf-8 -*-
"""Remessa de teste nº 3 — a FICHA DE ARRECADAÇÃO no produto dela.

    python -m cnab240.ferramentas.gerar_teste_3_arrecadacao [--app PASTA]

A pergunta que este arquivo faz ao banco é uma só: **o Sicoob aceita o nosso
lote de arrecadação?** — serviço 22, forma 11, segmento O (seção 9 do Guia
CNAB 240 v3.3). É o produto que faltava quando duas guias viajaram como título
de cobrança em 17/08/2026 e o banco aceitou no lugar errado.

Passa pelo CAMINHO REAL do app: `resolver_pagador`, `preparar` e
`montar_arquivo` do `pagamentos_dia/remessa_dia.py`. Se houver defeito no
código que vai para a release, ele aparece aqui.

DIFERENÇA IMPORTANTE PARA O TESTE Nº 2: este **não consome NSA de produção**.
Ele grava com um NSA fixo e alto (`NSA_TESTE`) e não toca no `remessas.json` —
é teste de LAYOUT, e queimar um número do contador compartilhado por um
arquivo que ninguém vai enviar deixa um furo que o histórico depois tem de
explicar. O teste nº 2 consumia porque podia acabar sendo enviado; este não
pode: o boleto e a ficha não existem.

O arquivo é inofensivo de propósito: R$ 0,01 em cada linha, e as duas linhas
digitáveis são fabricadas pelo `_ambiente` — forma válida, conteúdo que não
aponta para conta nenhuma. Se for transmitido por acidente, o banco recusa por
falta de destinatário; não há dinheiro a recuperar.
"""
from __future__ import annotations

import argparse
import datetime as dt

from ._ambiente import (boleto_sintetico, contas_mc, exigir, ficha_sintetica,
                        ocr_boleto, pasta_do_app, remessa_dia, sicoob_contas)

from cnab240 import relatorio as rel_cnab, validar

#: Alto e fixo: não é o contador de produção, e não pode ser confundido com um.
NSA_TESTE = 990001

CENTAVOS = 1
#: Ficha de arrecadação real em FORMA, inexistente em conteúdo: os dígitos
#: verificadores fecham (senão o `preparar` a barra antes de chegar ao
#: arquivo), mas ela não aponta para conta nenhuma.
LINHA_FICHA = ficha_sintetica(CENTAVOS)
#: Um boleto bancário junto, para o arquivo provar as DUAS coisas de uma vez:
#: que os dois produtos convivem no mesmo arquivo, em lotes separados.
LINHA_BOLETO = boleto_sintetico(CENTAVOS)


def registro(**troca):
    base = {"tipo": "Boleto", "dados": LINHA_BOLETO, "valor": CENTAVOS / 100,
            "descricao": "TESTE DE LAYOUT", "favorecido": "FORNECEDOR TESTE",
            "status": "APTO", "conferencia": "", "obs": "",
            "id": "teste", "parcial": False, "oc": "", "centro_custo": ""}
    base.update(troca)
    return base


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="remessa de teste nº 3")
    ap.add_argument("--app", default="", help="pasta da instalação (cadastro)")
    args = ap.parse_args(argv)

    hoje = dt.date.today()
    # Os arquivos da INSTALAÇÃO, não os do repositório: é o cadastro real que
    # o app usa, e o teste só prova alguma coisa se percorrer o mesmo caminho.
    app = pasta_do_app(args.app)
    mapa = contas_mc.carregar(exigir(app / "contas_mc.json"))
    # `resolver_pagador` percorre uma LISTA de empresas; o `carregar`
    # devolve o Mapa que a contém.
    empresas = sicoob_contas.carregar(exigir(app / "contas_sicoob.json")).empresas

    # A primeira conta do mapa que resolve para um pagador Sicoob completo.
    pagador = conta_erp = None
    for conta in [d.erp for d in mapa.destinos]:
        p, motivo = remessa_dia.resolver_pagador(conta, mapa, empresas)
        if p is not None:
            pagador, conta_erp = p, conta
            break
        print(f"  pulei {conta[:44]}: {motivo}")
    if pagador is None:
        print("[!] nenhuma conta do mapa resolveu para um pagador Sicoob.")
        return 1

    print(f"empresa : {pagador.empresa}")
    print(f"conta   : ag {pagador.agencia}-{pagador.dv_agencia} / "
          f"{pagador.conta}-{pagador.dv_conta}   convênio {pagador.convenio}")

    preparado = remessa_dia.preparar({conta_erp: [
        registro(id="teste-boleto"),
        registro(id="teste-ficha", dados=LINHA_FICHA,
                 favorecido="CONCESSIONARIA TESTE",
                 descricao="TESTE DE LAYOUT - ARRECADACAO"),
    ]}, quando=hoje)[conta_erp]

    print("\no que o `preparar` decidiu:")
    for c in preparado:
        produto = ("arrecadação" if c.arrecadacao else
                   "boleto" if c.tipo == "Boleto" else c.tipo.lower())
        print(f"  {c.favorecido[:26]:26} {produto:12} "
              f"{'vai' if c.pode and c.marcado else 'FICA DE FORA'}"
              f"{'  — ' + c.impedimento if c.impedimento else ''}")

    marcados = [c for c in preparado if c.marcado and c.pode]
    if not any(c.arrecadacao for c in marcados):
        print("\n[!] a ficha não entrou — o teste não prova nada. Abortado.")
        return 1

    arquivo = remessa_dia.montar_arquivo(pagador, marcados, nsa=NSA_TESTE,
                                         quando=hoje)
    linhas = arquivo.gerar()

    print(f"\nlotes   : {[l.produto for l in arquivo.lotes]}")
    for l in linhas:
        tipo = l[7:8]
        if tipo == "1":
            print(f"  header de lote {l[3:7]}: serviço {l[9:11]}  forma {l[11:13]}")
        elif tipo == "3":
            print(f"    detalhe  lote {l[3:7]}  segmento {l[13:14]}")

    seg_o = [l for l in linhas if l[7:8] == "3" and l[13:14] == "O"]
    if seg_o:
        o = seg_o[0]
        print("\nsegmento O, campo a campo (guia v3.3, seção 9.2):")
        for rotulo, ini, fim in (("08.3O código de barras", 17, 61),
                                 ("09.3O concessionária  ", 61, 91),
                                 ("10.3O vencimento      ", 91, 99),
                                 ("11.3O data pagamento  ", 99, 107),
                                 ("12.3O valor           ", 107, 122),
                                 ("13.3O seu número      ", 122, 142)):
            print(f"  {rotulo} [{o[ini:fim]}]")
        barras = ocr_boleto.codigo_de_barras(LINHA_FICHA)
        print(f"\n  confere com a linha digitável? "
              f"{'sim' if o[17:61] == barras else 'NÃO'}")

    problemas = validar(linhas)
    print("\nvalidação local:", rel_cnab(problemas))
    if problemas:
        print("[!] nada foi gravado.")
        return 1

    caminho = app / "TESTE_ARRECADACAO_NAO_ENVIAR.REM"
    arquivo.salvar(caminho)
    print(f"\narquivo : {caminho.name}  ({len(linhas)} linhas de 240)")
    print(f"NSA     : {NSA_TESTE} (fixo — o contador de produção não foi tocado)")
    print(f"\ncaminho completo:\n  {caminho}")
    print("\nNo SicoobNet: Empresarial → Arquivos CNAB 240 → Envio de Arquivos")
    print("→ Escolher Arquivos → Validar.  PARE AÍ. Não clique em Enviar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
