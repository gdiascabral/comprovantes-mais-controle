"""Geração do arquivo de remessa CNAB 240 (Sicoob).

    arquivo = ArquivoRemessa(empresa, nsa=1)
    lote = arquivo.novo_lote("TED", tipo_servico=TipoServico.PAGAMENTO_FORNECEDOR)
    lote.adicionar(TransferenciaConta(...))
    arquivo.salvar("REM0001.REM")
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import spec
from .campos import fmt_competencia, fmt_data
from .dominios import (
    BANCO_SICOOB,
    VERSAO_LAYOUT_ARQUIVO,
    FormaIniciacaoPix,
    FormaLancamento,
    TipoInscricao,
)
from .modelos import (
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
    so_digitos,
)
from .registros import aplicar, montar

QUEBRA_LINHA = "\r\n"


class RemessaInvalida(ValueError):
    pass


#: Classe de pagamento aceita por produto.
_ACEITA: dict[str, tuple[type, ...]] = {
    "TRANSFERENCIA_SICOOB": (TransferenciaConta,),
    "TED": (TransferenciaConta,),
    "PIX_TRANSFERENCIA": (PixTransferencia,),
    "TITULOS_COBRANCA": (PagamentoTitulo,),
    "PIX_QRCODE": (PixQRCode,),
    "CONVENIOS_COM_CODIGO_BARRAS": (PagamentoConvenio,),
    "TRIBUTOS_SEM_CODIGO_BARRAS": (TributoDARF, TributoGPS, TributoDARFSimples),
    "FOLHA_PAGAMENTO": (PagamentoFolha,),
}

#: Forma de lançamento default por produto, quando não ambígua.
_FORMA_PADRAO: dict[str, FormaLancamento] = {
    "TRANSFERENCIA_SICOOB": FormaLancamento.CREDITO_CONTA_CORRENTE,
    "PIX_TRANSFERENCIA": FormaLancamento.PIX_TRANSFERENCIA,
    "PIX_QRCODE": FormaLancamento.PIX_QRCODE,
    "CONVENIOS_COM_CODIGO_BARRAS": FormaLancamento.CONTAS_TRIBUTOS_COD_BARRAS,
    "FOLHA_PAGAMENTO": FormaLancamento.CREDITO_CONTA_CORRENTE,
}

_FORMA_POR_TRIBUTO: dict[type, FormaLancamento] = {
    TributoDARF: FormaLancamento.DARF_NORMAL,
    TributoGPS: FormaLancamento.GPS,
    TributoDARFSimples: FormaLancamento.DARF_SIMPLES,
}


def _endereco(e: Endereco | None) -> Endereco:
    return e or Endereco()


@dataclass
class Lote:
    """Um lote de serviço — um único produto, um ou mais pagamentos."""

    numero: int
    produto: str
    tipo_servico: str
    forma_lancamento: str
    empresa: Empresa
    mensagem: str = ""
    indicativo_forma_pagamento: str = ""
    pagamentos: list[Any] = field(default_factory=list)

    def adicionar(self, *pagamentos: Any) -> "Lote":
        aceitos = _ACEITA[self.produto]
        for pagamento in pagamentos:
            if not isinstance(pagamento, aceitos):
                nomes = ", ".join(c.__name__ for c in aceitos)
                raise RemessaInvalida(
                    f"lote {self.numero} ({self.produto}) aceita {nomes}, "
                    f"recebeu {type(pagamento).__name__}"
                )
            if self.produto == "TRIBUTOS_SEM_CODIGO_BARRAS":
                esperada = _FORMA_POR_TRIBUTO[type(pagamento)]
                if self.forma_lancamento != esperada:
                    raise RemessaInvalida(
                        f"lote {self.numero} é forma {self.forma_lancamento}; "
                        f"{type(pagamento).__name__} exige forma {esperada} "
                        "(um lote só pode conter um tipo de transação)"
                    )
            self.pagamentos.append(pagamento)
        return self

    @property
    def total(self) -> Decimal:
        return sum((p.valor for p in self.pagamentos), Decimal("0"))


class ArquivoRemessa:
    def __init__(
        self,
        empresa: Empresa,
        nsa: int,
        *,
        data_geracao: _dt.date | None = None,
        hora_geracao: _dt.time | None = None,
        nome_banco: str = "SICOOB",
        densidade: int = 0,
        reservado_banco: str = "",
        reservado_empresa: str = "",
    ) -> None:
        agora = _dt.datetime.now()
        self.empresa = empresa
        self.nsa = nsa
        self.data_geracao = data_geracao or agora.date()
        self.hora_geracao = hora_geracao or agora.time()
        self.nome_banco = nome_banco
        self.densidade = densidade
        self.reservado_banco = reservado_banco
        self.reservado_empresa = reservado_empresa
        self.lotes: list[Lote] = []

    # -- construção ---------------------------------------------------------

    def novo_lote(
        self,
        produto: str,
        *,
        tipo_servico: str | None = None,
        forma_lancamento: str | None = None,
        mensagem: str = "",
        indicativo_forma_pagamento: str = "",
    ) -> Lote:
        cfg = spec.produto(produto)

        forma = forma_lancamento or _FORMA_PADRAO.get(produto)
        if forma is None:
            raise RemessaInvalida(
                f"produto {produto} exige forma_lancamento explícita "
                f"(opções: {', '.join(cfg['forma_lancamento_G029'])})"
            )
        forma = str(forma)
        if forma not in cfg["forma_lancamento_G029"]:
            raise RemessaInvalida(
                f"forma de lançamento {forma} não é válida para {produto} "
                f"(válidas: {', '.join(cfg['forma_lancamento_G029'])})"
            )

        servico = str(tipo_servico or cfg["tipo_servico_G025"][0])
        if servico not in cfg["tipo_servico_G025"]:
            raise RemessaInvalida(
                f"tipo de serviço {servico} não é válido para {produto} "
                f"(válidos: {', '.join(cfg['tipo_servico_G025'])})"
            )

        if produto == "FOLHA_PAGAMENTO" and not mensagem:
            raise RemessaInvalida(
                "Folha de Pagamento exige 'mensagem' no header do lote — "
                "é o nome da folha (campo 18.1 / G031, obrigatório na v3.1)"
            )

        lote = Lote(
            numero=len(self.lotes) + 1,
            produto=produto,
            tipo_servico=servico,
            forma_lancamento=forma,
            empresa=self.empresa,
            mensagem=mensagem,
            indicativo_forma_pagamento=indicativo_forma_pagamento,
        )
        self.lotes.append(lote)
        return lote

    # -- geração ------------------------------------------------------------

    def gerar(self) -> list[str]:
        if not self.lotes:
            raise RemessaInvalida("arquivo sem lotes")
        vazios = [l.numero for l in self.lotes if not l.pagamentos]
        if vazios:
            raise RemessaInvalida(f"lotes sem pagamentos: {vazios}")

        linhas = [self._header_arquivo()]
        for lote in self.lotes:
            linhas.extend(self._gerar_lote(lote))
        linhas.append(self._trailer_arquivo(len(linhas) + 1))
        return linhas

    def texto(self, quebra: str = QUEBRA_LINHA) -> str:
        return quebra.join(self.gerar()) + quebra

    def salvar(self, caminho: str | Path, *, quebra: str = QUEBRA_LINHA) -> Path:
        destino = Path(caminho)
        destino.write_text(self.texto(quebra), encoding="latin-1", newline="")
        return destino

    # -- registros de arquivo ----------------------------------------------

    def _header_arquivo(self) -> str:
        e = self.empresa
        return montar(
            spec.layout("header_arquivo"),
            {
                "01.0": BANCO_SICOOB,
                "05.0": str(e.tipo_inscricao),
                "06.0": e.documento,
                "07.0": e.convenio,
                "08.0": e.agencia,
                "09.0": e.dv_agencia,
                "10.0": e.conta,
                "11.0": e.dv_conta,
                "12.0": e.dv_ag_conta,
                "13.0": e.nome,
                "14.0": self.nome_banco,
                "16.0": "1",  # remessa
                "17.0": fmt_data(self.data_geracao),
                "18.0": self.hora_geracao,
                "19.0": self.nsa,
                "20.0": VERSAO_LAYOUT_ARQUIVO,
                "21.0": self.densidade,
                "22.0": self.reservado_banco,
                "23.0": self.reservado_empresa,
            },
        )

    def _trailer_arquivo(self, total_registros: int) -> str:
        return montar(
            spec.layout("trailer_arquivo"),
            {
                "05.9": len(self.lotes),
                "06.9": total_registros,
                "07.9": 0,  # nenhum lote de conciliação bancária
            },
        )

    # -- registros de lote --------------------------------------------------

    def _header_lote(self, lote: Lote) -> str:
        cfg = spec.produto(lote.produto)
        layout = spec.layout(cfg["header_lote"])
        e = self.empresa
        end = _endereco(e.endereco)

        valores: dict[str, Any] = {
            "01.1": BANCO_SICOOB,
            "02.1": lote.numero,
            "05.1": lote.tipo_servico,
            "06.1": lote.forma_lancamento,
            "07.1": cfg["versao_layout_lote"],
            "09.1": str(e.tipo_inscricao),
            "10.1": e.documento,
            "11.1": e.convenio,
            "12.1": e.agencia,
            "13.1": e.dv_agencia,
            "14.1": e.conta,
            "15.1": e.dv_conta,
            "16.1": e.dv_ag_conta,
            "17.1": e.nome,
            "18.1": lote.mensagem,
            "19.1": end.logradouro,
            "20.1": so_digitos(end.numero),
            "21.1": end.complemento,
            "22.1": end.cidade,
            "23.1": end.cep_prefixo,
            "24.1": end.cep_sufixo,
            "25.1": end.estado,
        }
        # O header de títulos não tem "Indicativo da Forma de Pagamento".
        if any(c.id == "26.1" and c.ref == "P014" for c in layout.campos):
            valores["26.1"] = lote.indicativo_forma_pagamento
        return montar(layout, valores)

    def _trailer_lote(self, lote: Lote, qtd_registros: int) -> str:
        cfg = spec.produto(lote.produto)
        layout = spec.layout(cfg["trailer_lote"])
        valores: dict[str, Any] = {
            "02.5": lote.numero,
            "05.5": qtd_registros,
            "06.5": lote.total,
        }
        if any(c.id == "07.5" and c.ref == "G058" for c in layout.campos):
            valores["07.5"] = 0  # somatória de quantidade de moedas
        return montar(layout, valores)

    def _gerar_lote(self, lote: Lote) -> list[str]:
        detalhes: list[str] = []
        nsr = 0

        for pagamento in lote.pagamentos:
            for construtor in self._segmentos(lote, pagamento):
                nsr += 1
                detalhes.append(construtor(nsr))

        return [
            self._header_lote(lote),
            *detalhes,
            self._trailer_lote(lote, len(detalhes) + 2),
        ]

    def _segmentos(self, lote: Lote, pagamento: Any):
        """Devolve as funções que montam cada registro tipo 3 do pagamento."""
        p = lote.produto
        if p in ("TRANSFERENCIA_SICOOB", "TED"):
            yield lambda nsr: self._segmento_a(lote, pagamento, nsr)
            yield lambda nsr: self._segmento_b_transferencia(lote, pagamento, nsr)
        elif p == "PIX_TRANSFERENCIA":
            yield lambda nsr: self._segmento_a(lote, pagamento, nsr)
            yield lambda nsr: self._segmento_b_pix(lote, pagamento, nsr)
        elif p == "FOLHA_PAGAMENTO":
            yield lambda nsr: self._segmento_a(lote, pagamento, nsr)
            yield lambda nsr: self._segmento_b_folha(lote, pagamento, nsr)
        elif p == "TITULOS_COBRANCA":
            yield lambda nsr: self._segmento_j(lote, pagamento, nsr)
            yield lambda nsr: self._segmento_j52(lote, pagamento, nsr)
        elif p == "PIX_QRCODE":
            yield lambda nsr: self._segmento_j(lote, pagamento, nsr)
            yield lambda nsr: self._segmento_j52_pix(lote, pagamento, nsr)
        elif p == "CONVENIOS_COM_CODIGO_BARRAS":
            yield lambda nsr: self._segmento_o(lote, pagamento, nsr)
            if pagamento.complemento:
                yield lambda nsr: self._segmento_w(lote, pagamento.complemento, nsr)
        elif p == "TRIBUTOS_SEM_CODIGO_BARRAS":
            yield lambda nsr: self._segmento_n(lote, pagamento, nsr)
            if pagamento.complemento:
                yield lambda nsr: self._segmento_w(lote, pagamento.complemento, nsr)
        else:  # pragma: no cover - protegido por spec.produto()
            raise RemessaInvalida(f"produto {p} sem gerador de segmentos")

    # -- segmentos ----------------------------------------------------------

    def _camara(self, lote: Lote) -> str:
        cfg = spec.produto(lote.produto)
        return cfg.get("camara_P001") or "0"

    def _segmento_a(self, lote: Lote, pg: Any, nsr: int) -> str:
        f: Favorecido = pg.favorecido
        informacao_2 = getattr(pg, "mensagem", "")
        if lote.produto == "PIX_TRANSFERENCIA":
            # G031: 38 brancos + tipo da conta de destino nas 2 últimas posições.
            informacao_2 = " " * 38 + str(pg.tipo_conta_destino)

        return montar(
            spec.layout("segmento_a"),
            {
                "02.3A": lote.numero,
                "04.3A": nsr,
                "08.3A": self._camara(lote),
                "09.3A": f.banco,
                "10.3A": f.agencia,
                "11.3A": f.dv_agencia,
                "12.3A": f.conta,
                "13.3A": f.dv_conta,
                "14.3A": f.dv_ag_conta,
                "15.3A": f.nome,
                "16.3A": pg.seu_numero,
                "17.3A": fmt_data(pg.data_pagamento),
                "19.3A": 0,  # quantidade da moeda
                "20.3A": pg.valor,
                "21.3A": pg.nosso_numero,
                "24.3A": informacao_2,
                "26.3A": getattr(pg, "finalidade_ted", "") or 0,
                "27.3A": getattr(pg, "finalidade_complementar", ""),
                "29.3A": str(pg.aviso),
            },
        )

    def _segmento_b_transferencia(self, lote: Lote, pg: TransferenciaConta, nsr: int) -> str:
        f = pg.favorecido
        end = _endereco(f.endereco)
        linha = montar(
            spec.layout("segmento_b_transferencia"),
            {
                "02.3B": lote.numero,
                "04.3B": nsr,
                "07.3B": str(f.tipo_inscricao),
                "08.3B": f.documento,
            },
        )
        return aplicar(
            linha,
            spec.layout("segmento_b_transferencia.sub_layout_informacao_10_11_12_nao_pix"),
            {
                "b.01": end.logradouro,
                "b.02": so_digitos(end.numero),
                "b.03": end.complemento,
                "b.04": end.bairro,
                "b.05": end.cidade,
                "b.06": end.cep_prefixo,
                "b.07": end.cep_sufixo,
                "b.08": end.estado,
                "b.09": fmt_data(pg.vencimento),
                "b.10": pg.valor_documento,
                "b.11": pg.abatimento,
                "b.12": pg.desconto,
                "b.13": pg.mora,
                "b.14": pg.multa,
                "b.15": pg.codigo_documento_favorecido,
                "b.16": str(pg.aviso),
            },
        )

    def _segmento_b_pix(self, lote: Lote, pg: PixTransferencia, nsr: int) -> str:
        f = pg.favorecido
        linha = montar(
            spec.layout("segmento_b_transferencia"),
            {
                "02.3B": lote.numero,
                "04.3B": nsr,
                "06.3B": str(pg.forma_iniciacao),
                "07.3B": str(f.tipo_inscricao),
                "08.3B": f.documento,
            },
        )
        if pg.forma_iniciacao is FormaIniciacaoPix.DADOS_BANCARIOS:
            informacao_12 = str(pg.tipo_conta_destino)
        elif pg.forma_iniciacao is FormaIniciacaoPix.CHAVE_CPF_CNPJ:
            # O manual descreve a Informação 12 para as formas 01, 02, 04 e 05,
            # e OMITE a 03 — o que se lia como "a chave já está em 07.3B/08.3B,
            # não repita". Não é isso: o SicoobNet recusou o campo em branco na
            # validação de 13/08/2026 ("A linha 8 posição 128 até 226, campo
            # Informação 12, possui valor inválido"). A chave vai aqui também.
            informacao_12 = so_digitos(pg.chave) or f.documento
        else:
            informacao_12 = pg.chave

        return aplicar(
            linha,
            spec.layout("segmento_b_transferencia.sub_layout_informacao_10_11_12_pix"),
            {"b.p1": "", "b.p2": "", "b.p3": informacao_12},
        )

    def _segmento_b_folha(self, lote: Lote, pg: PagamentoFolha, nsr: int) -> str:
        f = pg.favorecido
        end = _endereco(f.endereco)
        return montar(
            spec.layout("segmento_b_folha"),
            {
                "02.3B": lote.numero,
                "04.3B": nsr,
                "07.3B": str(f.tipo_inscricao),
                "08.3B": f.documento,
                "09.3B": end.logradouro,
                "10.3B": so_digitos(end.numero),
                "11.3B": end.complemento,
                "12.3B": end.bairro,
                "13.3B": end.cidade,
                "14.3B": end.cep_prefixo,
                "15.3B": end.cep_sufixo,
                "16.3B": end.estado,
                "24.3B": str(pg.aviso),
            },
        )

    def _segmento_j(self, lote: Lote, pg: Any, nsr: int) -> str:
        if isinstance(pg, PixQRCode):
            cedente = pg.favorecido.nome
        else:
            cedente = pg.nome_cedente
        return montar(
            spec.layout("segmento_j"),
            {
                "02.3J": lote.numero,
                "04.3J": nsr,
                "08.3J": pg.codigo_barras,
                "09.3J": cedente,
                "10.3J": fmt_data(pg.vencimento),
                "11.3J": pg.valor_titulo,
                "12.3J": getattr(pg, "desconto_abatimento", 0),
                "13.3J": getattr(pg, "mora_multa", 0),
                "14.3J": fmt_data(pg.data_pagamento),
                "15.3J": pg.valor,
                "16.3J": 0,
                "17.3J": pg.seu_numero,
                "18.3J": pg.nosso_numero,
            },
        )

    def _segmento_j52(self, lote: Lote, pg: PagamentoTitulo, nsr: int) -> str:
        d = pg.j52
        e = self.empresa

        def inscricao(documento: str) -> tuple[str, str]:
            documento = so_digitos(documento)
            if not documento:
                return "0", "0"
            return str(TipoInscricao.por_documento(documento)), documento

        # Sacado = quem paga (a própria empresa, salvo indicação em contrário).
        sacado_tipo, sacado_num = inscricao(d.sacado_documento or e.documento)
        cedente_tipo, cedente_num = inscricao(d.cedente_documento)
        sacador_tipo, sacador_num = inscricao(d.sacador_documento)

        return montar(
            spec.layout("segmento_j52"),
            {
                "02.4.J52": lote.numero,
                "04.4.J52": nsr,
                "09.4.J52": sacado_tipo,
                "10.4.J52": sacado_num,
                "11.4.J52": d.sacado_nome or e.nome,
                "12.4.J52": cedente_tipo,
                "13.4.J52": cedente_num,
                "14.4.J52": d.cedente_nome or pg.nome_cedente,
                "15.4.J52": sacador_tipo,
                "16.4.J52": sacador_num,
                "17.4.J52": d.sacador_nome,
            },
        )

    def _segmento_j52_pix(self, lote: Lote, pg: PixQRCode, nsr: int) -> str:
        e = self.empresa
        f = pg.favorecido
        devedor_doc = so_digitos(pg.devedor_documento) or e.documento
        devedor_tipo = str(TipoInscricao.por_documento(devedor_doc))

        return montar(
            spec.layout("segmento_j52_pix"),
            {
                "02.4.J52": lote.numero,
                "04.4.J52": nsr,
                "09.4.J52": devedor_tipo,
                "10.4.J52": devedor_doc,
                "11.4.J52": pg.devedor_nome or e.nome,
                "12.4.J52": str(f.tipo_inscricao),
                "13.4.J52": f.documento,
                "14.4.J52": f.nome,
                "15.4.J52": pg.chave_pagamento,
                "16.4.J52": pg.txid,
            },
        )

    def _segmento_o(self, lote: Lote, pg: PagamentoConvenio, nsr: int) -> str:
        return montar(
            spec.layout("segmento_o"),
            {
                "02.3O": lote.numero,
                "04.3O": nsr,
                "08.3O": pg.codigo_barras,
                "09.3O": pg.nome_concessionaria,
                "10.3O": fmt_data(pg.vencimento),
                "11.3O": fmt_data(pg.data_pagamento),
                "12.3O": pg.valor,
                "13.3O": pg.seu_numero,
                "14.3O": pg.nosso_numero,
            },
        )

    def _segmento_n(self, lote: Lote, pg: Any, nsr: int) -> str:
        linha = montar(
            spec.layout("segmento_n"),
            {
                "02.3N": lote.numero,
                "04.3N": nsr,
                "08.3N": pg.seu_numero,
                "09.3N": pg.nosso_numero,
                "10.3N": pg.nome_contribuinte,
                "11.3N": fmt_data(pg.data_pagamento),
                "12.3N": pg.valor,
                "13.3N": "",  # sobrescrito pelo complemento do tributo
            },
        )

        if isinstance(pg, TributoGPS):
            return aplicar(
                linha,
                spec.layout("segmento_n.complemento_gps"),
                {
                    "01.3.N1": pg.codigo_receita,
                    "02.3.N1": str(pg.tipo_identificacao),
                    "03.3.N1": pg.identificacao,
                    "05.3.N1": fmt_competencia(pg.competencia),
                    "06.3.N1": pg.valor_inss,
                    "07.3.N1": pg.valor_outras_entidades,
                    "08.3.N1": pg.atualizacao_monetaria,
                },
            )
        if isinstance(pg, TributoDARFSimples):
            return aplicar(
                linha,
                spec.layout("segmento_n.complemento_darf_simples"),
                {
                    "01.3.N3": pg.codigo_receita,
                    "02.3.N3": str(pg.tipo_identificacao),
                    "03.3.N3": pg.identificacao,
                    "05.3.N3": fmt_data(pg.periodo_apuracao),
                    "06.3.N3": pg.receita_bruta,
                    "07.3.N3": pg.percentual,
                    "08.3.N3": pg.valor_principal,
                    "09.3.N3": pg.valor_multa,
                    "10.3.N3": pg.juros_encargos,
                },
            )
        if isinstance(pg, TributoDARF):
            return aplicar(
                linha,
                spec.layout("segmento_n.complemento_darf"),
                {
                    "01.3.N2": pg.codigo_receita,
                    "02.3.N2": str(pg.tipo_identificacao),
                    "03.3.N2": pg.identificacao,
                    "05.3.N2": fmt_data(pg.periodo_apuracao),
                    "06.3.N2": pg.numero_referencia,
                    "07.3.N2": pg.valor_principal,
                    "08.3.N2": pg.valor_multa,
                    "09.3.N2": pg.juros_encargos,
                    "10.3.N2": fmt_data(pg.vencimento),
                },
            )
        raise RemessaInvalida(f"tributo {type(pg).__name__} sem complemento definido")

    def _segmento_w(self, lote: Lote, w: SegmentoW, nsr: int) -> str:
        return montar(
            spec.layout("segmento_w"),
            {
                "02.3W": lote.numero,
                "04.3W": nsr,
                "06.3W": w.sequencial,
                "07.3W": w.tipo_informacao,
                "08.3W": w.informacao_1,
                "09.3W": w.informacao_2,
                "10.3W": w.identificador_tributo,
                "11.3W": w.informacao_tributo,
            },
        )
