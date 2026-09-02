# -*- coding: utf-8 -*-
"""Remessa de teste nº 2 — um Pix de R$ 1,00 e um boleto inexistente.

    python -m cnab240.ferramentas.gerar_teste_2 --chave-pix CPF_OU_CNPJ
                                                [--app PASTA] [--empresa NOME]

Diferente do teste nº 1 (que só media o layout), este passa pelo CAMINHO REAL
do app: `resolver_pagador`, `preparar` e `montar_arquivo` do
`pagamentos_dia/remessa_dia.py`. É o código que vai para a release — se houver
defeito nele, aparece aqui.

Ordem de propósito: **validar -> registrar -> salvar**. O `salvar()` da
biblioteca não valida sozinho, e gravar antes de registrar deixaria um .REM
órfão no disco, com nome legítimo, se o registro fosse recusado.

O contador usado é o de PRODUÇÃO (`remessas.json` da instalação), porque este
arquivo pode acabar sendo enviado. Se for descartado, devolva o número com:

    python -m cnab240 historico "<pasta do app>/remessas.json"
    (e `Historico(...).descartar(convenio, nsa, motivo="...")`)

**A chave Pix é obrigatória na linha de comando e não tem valor padrão.** Ela é
CPF ou CNPJ de gente de verdade — o dinheiro sai para quem estiver ali — e
repositório é público. Quem roda sabe para onde está mandando R$ 1,00; um
padrão escrito no arquivo faria a decisão por quem vier depois.
"""
from __future__ import annotations

import argparse
import datetime as dt

from ._ambiente import (boleto_sintetico, contas_mc, exigir, ocr_boleto,
                        pasta_do_app, remessa_dia, sicoob_contas, util)

from cnab240 import Historico, relatorio as rel_cnab, validar
from cnab240.dominios import documento_valido

FAVORECIDO_PIX = "TESTE REMESSA CNAB"
VALOR_PIX = 1.00
VALOR_BOLETO = 1.00


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="remessa de teste nº 2")
    ap.add_argument("--chave-pix", required=True,
                    help="CPF ou CNPJ que vai RECEBER o R$ 1,00")
    ap.add_argument("--app", default="", help="pasta da instalação (cadastro)")
    ap.add_argument("--empresa", default="",
                    help="nome no cadastro; sem isto, a 1ª conta que resolver")
    args = ap.parse_args(argv)

    chave_pix = documento_valido(args.chave_pix)
    if not chave_pix:
        print("[!] --chave-pix: os dígitos não fecham como CPF nem como CNPJ. "
              "Foi um documento assim, de preenchimento, que fez o Sicoob "
              "devolver a remessa 000002 em 20/08/2026.")
        return 1

    hoje = dt.date.today()
    app = pasta_do_app(args.app)
    mapa = contas_mc.carregar(exigir(app / "contas_mc.json"))
    cadastro = sicoob_contas.carregar(exigir(app / "contas_sicoob.json"))

    if args.empresa:
        contas = [d.erp for d in mapa.destinos
                  if d.empresa == args.empresa and d.banco == "SICOOB"]
    else:
        contas = [d.erp for d in mapa.destinos]
    if not contas:
        print(f"[!] não achei conta Sicoob de {args.empresa!r} no contas_mc.json")
        return 1

    pagador = conta_erp = None
    for conta in contas:
        p, motivo = remessa_dia.resolver_pagador(conta, mapa, cadastro.empresas)
        if p is not None:
            pagador, conta_erp = p, conta
            break
        print(f"  pulei {conta[:44]}: {motivo}")
    if pagador is None:
        print("[!] nenhuma conta do mapa resolveu para um pagador Sicoob.")
        return 1

    print(f"pagador : {pagador.empresa} · convênio {pagador.convenio} · "
          f"ag {pagador.agencia}-{pagador.dv_agencia} / "
          f"conta {pagador.conta}-{pagador.dv_conta}")

    linha = boleto_sintetico(round(VALOR_BOLETO * 100))
    print(f"boleto  : linha sintética {ocr_boleto.formatar(linha)}")
    print(f"          valor embutido R$ {ocr_boleto.valor_da_linha(linha):.2f} "
          "— título que NÃO existe")

    registros = {conta_erp: [
        {"tipo": "Pix", "dados": chave_pix, "valor": VALOR_PIX,
         "descricao": "TESTE REMESSA CNAB 240", "favorecido": FAVORECIDO_PIX,
         "status": "APTO", "conferencia": "", "obs": "",
         "id": "teste-pix-001", "parcial": False},
        {"tipo": "Boleto", "dados": linha, "valor": VALOR_BOLETO,
         "descricao": "TESTE BOLETO INEXISTENTE", "favorecido": "CEDENTE DE TESTE",
         "status": "APTO", "conferencia": "", "obs": "",
         "id": "teste-boleto-001", "parcial": False},
    ]}

    # O cadastro de Contatos do ERP, simulado com a única entrada que este
    # teste usa. Sem ele, onze dígitos crus são ambíguos — CPF e celular têm
    # os dois onze — e a linha não sai; foi o que aconteceu na 1ª tentativa.
    # No app de verdade este mapa vem do `mc_api.listar_participantes`.
    participantes = {util.norm_espaco(FAVORECIDO_PIX): chave_pix}

    preparado = remessa_dia.preparar(registros, participantes, quando=hoje)
    linhas = preparado[conta_erp]
    print("\nconferência (como a janela do passo 3 mostraria):")
    for c in linhas:
        marca = "[x]" if c.marcado else ("[ ]" if c.pode else " — ")
        print(f"  {marca} {c.tipo:<7} R$ {c.valor:>7.2f}  {c.seu_numero:<20} "
              f"{c.impedimento}")
    marcados = [c for c in linhas if c.marcado and c.pode]
    if len(marcados) != 2:
        print("\n[!] esperava os DOIS pagamentos aptos; algo os barrou. Abortando.")
        return 1
    pix = next(c for c in marcados if c.tipo == "Pix")
    print(f"\n  Pix: forma de iniciação {pix.forma_iniciacao} (03 = CPF/CNPJ), "
          f"documento do favorecido "
          f"{'preenchido' if pix.documento_favorecido else 'VAZIO'}")

    historico = Historico(app / "remessas.json")
    nsa = historico.proximo_nsa(pagador.convenio)
    arquivo = remessa_dia.montar_arquivo(pagador, marcados, nsa=nsa, quando=hoje)

    problemas = validar(arquivo.gerar())
    print("\nvalidação local:", rel_cnab(problemas))
    if problemas:
        print("[!] nada foi gravado e o NSA não foi consumido.")
        return 1

    caminho = app / remessa_dia.nome_do_arquivo(pagador, nsa)
    registrada = historico.registrar(
        arquivo, caminho_arquivo=caminho,
        referencias=remessa_dia.referencias(marcados))
    arquivo.salvar(caminho)

    linhas_arq = arquivo.gerar()
    print(f"\narquivo : {caminho.name}  ({len(linhas_arq)} linhas de 240)")
    print(f"lotes   : {[l.produto for l in arquivo.lotes]}")
    print(f"NSA     : {registrada.nsa}   total R$ {registrada.total}")
    print("de-para : {"
          + ", ".join(f"{i.seu_numero}: {i.referencia}" for i in registrada.itens)
          + "}")
    print(f"próximo NSA do convênio: {historico.proximo_nsa(pagador.convenio)}")
    print(f"\ncaminho completo:\n  {caminho}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
