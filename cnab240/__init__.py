"""CNAB 240 — Sicoob (Sicoobnet Empresarial).

Gera, valida e lê arquivos de pagamento no padrão do "Guia de Importação de
Arquivos CNAB 240" v3.1 (26/03/2025).

    from cnab240 import *

    empresa = Empresa(nome="ACME LTDA", documento="12345678000199",
                      convenio="123456", agencia="4321", conta="123456",
                      dv_conta="7")

    arquivo = ArquivoRemessa(empresa, nsa=1)
    lote = arquivo.novo_lote("TED", forma_lancamento=FormaLancamento.TED_OUTRA_TITULARIDADE)
    lote.adicionar(TransferenciaConta(
        valor="1500.00", data_pagamento=date(2026, 8, 12),
        favorecido=Favorecido(nome="FORNECEDOR SA", documento="98765432000155",
                              banco="341", agencia="1234", conta="56789", dv_conta="0"),
        finalidade_ted="5",
    ))
    arquivo.salvar("REM0001.REM")
"""

from .dominios import (
    BANCO_SICOOB,
    VERSAO_LAYOUT_ARQUIVO,
    AvisoFavorecido,
    Camara,
    FormaIniciacaoPix,
    FormaLancamento,
    TipoContaDestino,
    TipoIdentificacaoContribuinte,
    TipoInscricao,
    TipoServico,
    decodificar_ocorrencias,
    descrever,
)
from .historico import (
    ESTADOS,
    Ajuste,
    Historico,
    HistoricoInvalido,
    Item,
    NSA_MAXIMO,
    RemessaGerada,
    itens_de,
)
from .modelos import (
    DadosJ52,
    Empresa,
    Endereco,
    Favorecido,
    PagamentoConvenio,
    PagamentoFolha,
    PagamentoTitulo,
    PixQRCode,
    PixTransferencia,
    SegmentoW,
    TransferenciaConta,
    TributoDARF,
    TributoDARFSimples,
    TributoGPS,
)
from .remessa import ArquivoRemessa, Lote, RemessaInvalida
from .retorno import (
    ArquivoRetorno,
    ResultadoPagamento,
    RetornoInvalido,
    ler_arquivo_retorno,
    ler_retorno,
)
from .validador import Problema, relatorio, validar, validar_arquivo

__version__ = "1.0.0"

__all__ = [
    "Ajuste",
    "ArquivoRemessa",
    "ArquivoRetorno",
    "AvisoFavorecido",
    "BANCO_SICOOB",
    "Camara",
    "DadosJ52",
    "ESTADOS",
    "Empresa",
    "Endereco",
    "Favorecido",
    "FormaIniciacaoPix",
    "FormaLancamento",
    "Historico",
    "HistoricoInvalido",
    "Item",
    "Lote",
    "NSA_MAXIMO",
    "PagamentoConvenio",
    "PagamentoFolha",
    "PagamentoTitulo",
    "PixQRCode",
    "PixTransferencia",
    "Problema",
    "RemessaGerada",
    "RemessaInvalida",
    "ResultadoPagamento",
    "RetornoInvalido",
    "SegmentoW",
    "TipoContaDestino",
    "TipoIdentificacaoContribuinte",
    "TipoInscricao",
    "TipoServico",
    "TransferenciaConta",
    "TributoDARF",
    "TributoDARFSimples",
    "TributoGPS",
    "VERSAO_LAYOUT_ARQUIVO",
    "decodificar_ocorrencias",
    "descrever",
    "itens_de",
    "ler_arquivo_retorno",
    "ler_retorno",
    "relatorio",
    "validar",
    "validar_arquivo",
]
