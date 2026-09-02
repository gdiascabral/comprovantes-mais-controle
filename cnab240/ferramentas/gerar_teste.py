# -*- coding: utf-8 -*-
"""Monta o arquivo de teste nº 1 para o botão `Validar` do SicoobNet.

    python -m cnab240.ferramentas.gerar_teste [--app PASTA] [--empresa NOME]

O arquivo existe para uma pergunta só: **o Sicoob aceita o nosso layout?**
Ele não deve ser enviado, e por isso o conteúdo é inofensivo de propósito —
R$ 0,01 por pagamento, boleto que não existe e chave Pix da própria empresa.
Se por acidente ele for transmitido, o banco recusa os dois pagamentos por
falta de destinatário; não há dinheiro a recuperar.

Nada aqui é digitado à mão: a empresa sai do `contas_sicoob.json`, para que o
teste prove o mesmo caminho que o app vai usar. Sem `--empresa`, vale a
primeira do cadastro que tenha convênio — o nome de empresa nenhuma entra
neste arquivo, que mora num repositório público.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from decimal import Decimal

from ._ambiente import barcode_sintetico, exigir, pasta_do_app

from cnab240 import (
    ArquivoRemessa,
    DadosJ52,
    Empresa,
    Favorecido,
    FormaIniciacaoPix,
    FormaLancamento,
    PagamentoTitulo,
    PixTransferencia,
    TipoServico,
    relatorio,
    validar_arquivo,
)
from cnab240.campos import sanitizar

CENTAVO = Decimal("0.01")


def carregar_empresa(caminho, nome: str = "") -> tuple[Empresa, dict]:
    cadastro = json.loads(caminho.read_text(encoding="utf-8"))
    com_convenio = [e for e in cadastro["empresas"] if e.get("convenio")]
    if not com_convenio:
        raise SystemExit("nenhuma empresa do cadastro tem convênio")
    if nome:
        bruta = next((e for e in com_convenio if e["nome"] == nome), None)
        if bruta is None:
            raise SystemExit(f"{nome} não está no cadastro, ou está sem convênio")
    else:
        bruta = com_convenio[0]

    conta = bruta["contas"][0]
    agencia, dv_agencia = conta["agencia"].split("-")
    numero, dv_conta = conta["numero"].replace(".", "").split("-")

    empresa = Empresa(
        nome=bruta["razao_social"],
        documento=bruta["cnpj"],
        convenio=bruta["convenio"],
        agencia=agencia,
        dv_agencia=dv_agencia,
        conta=numero,
        dv_conta=dv_conta,
        # G012: só existe para banco cujo DV da conta tem DUAS posições —
        # "preencher com a 2ª posição deste dígito". O DV daqui tem uma, então
        # não há segunda posição e o campo fica branco (por isso ele é Alfa).
        dv_ag_conta="",
    )
    return empresa, bruta


def montar(empresa: Empresa, quando: dt.date, nsa: int) -> ArquivoRemessa:
    arquivo = ArquivoRemessa(empresa, nsa=nsa, data_geracao=quando)

    # Lote 1 — boleto: exercita segmento J + J-52 (obrigatório desde 2019).
    arquivo.novo_lote(
        "TITULOS_COBRANCA",
        tipo_servico=TipoServico.PAGAMENTO_FORNECEDOR,
        forma_lancamento=FormaLancamento.TITULO_OUTROS_BANCOS,
    ).adicionar(
        PagamentoTitulo(
            valor=CENTAVO,
            data_pagamento=quando,
            seu_numero="TESTE-LAYOUT-0001",
            codigo_barras=barcode_sintetico(1),
            nome_cedente="TESTE DE LAYOUT NAO ENVIAR",
            vencimento=quando,
            j52=DadosJ52(
                sacado_nome=sanitizar(empresa.nome),
                sacado_documento=empresa.documento,
                cedente_nome="TESTE DE LAYOUT NAO ENVIAR",
                cedente_documento=empresa.documento,
            ),
        )
    )

    # Lote 2 — Pix: exercita segmento A + B com o sub-layout Pix. A chave é o
    # CNPJ da própria empresa: se isto for enviado por engano, o dinheiro não
    # sai da casa.
    arquivo.novo_lote(
        "PIX_TRANSFERENCIA",
        tipo_servico=TipoServico.PAGAMENTO_FORNECEDOR,
        forma_lancamento=FormaLancamento.PIX_TRANSFERENCIA,
    ).adicionar(
        PixTransferencia(
            valor=CENTAVO,
            data_pagamento=quando,
            seu_numero="TESTE-LAYOUT-0002",
            forma_iniciacao=FormaIniciacaoPix.CHAVE_CPF_CNPJ,
            chave=empresa.documento,
            favorecido=Favorecido(nome=empresa.nome, documento=empresa.documento),
        )
    )
    return arquivo


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--app", default="", help="pasta da instalação (cadastro)")
    ap.add_argument("--empresa", default="",
                    help="nome no cadastro; sem isto, a 1ª com convênio")
    args = ap.parse_args(argv)

    app = pasta_do_app(args.app)
    empresa, bruta = carregar_empresa(
        exigir(app / "contas_sicoob.json"), args.empresa)
    quando = dt.date.today()
    arquivo = montar(empresa, quando, nsa=1)

    # Ao lado do cadastro, e não na pasta do código: um `.REM` é um pedido de
    # pagamento, e o `.gitignore` do repositório é a última linha de defesa,
    # não a primeira.
    destino = app / "TESTE_LAYOUT_NAO_ENVIAR.REM"
    arquivo.salvar(destino)

    problemas = validar_arquivo(destino)
    print(f"empresa .....: {empresa.nome}")
    print(f"convênio ....: {empresa.convenio}")
    print(f"conta .......: ag {bruta['contas'][0]['agencia']} / "
          f"{bruta['contas'][0]['numero']}")
    print(f"arquivo .....: {destino}")
    print(f"registros ...: {len(arquivo.gerar())} linhas de 240")
    print(f"lotes .......: {[l.produto for l in arquivo.lotes]}")
    print(f"total .......: R$ {sum(l.total for l in arquivo.lotes):.2f}")
    print()
    print(relatorio(problemas))

    header = arquivo.gerar()[0]
    print("\nheader, campo a campo (o que o Sicoob vai conferir):")
    for rotulo, fatia in (
        ("01.0 banco        1-3", header[0:3]),
        ("06.0 CNPJ        19-32", header[18:32]),
        ("07.0 convênio    33-52", header[32:52]),
        ("08/09 agência    53-58", header[52:58]),
        ("10.0 conta       59-70", header[58:70]),
        ("11.0 DV conta       71", header[70:71]),
        ("12.0 DV ag/conta    72", header[71:72]),
        ("19.0 NSA       158-163", header[157:163]),
        ("20.0 layout    164-166", header[163:166]),
    ):
        print(f"  {rotulo}: {fatia!r}")
    return 0 if not problemas else 1


if __name__ == "__main__":
    raise SystemExit(main())
