# -*- coding: utf-8 -*-
"""O que o banco respondeu — lido do arquivo de retorno e casado com a remessa.

Sem tela e sem rede: recebe o caminho do arquivo e o registro das remessas,
devolve o que a aba vai mostrar. É o mesmo arranjo do `remessa_dia.py`, e é o
que permite testar a regra inteira sem abrir janela nem falar com o banco.

**O primeiro retorno quase nunca é o desfecho.** No fluxo desta empresa quem
gera o arquivo não é quem assina: o app agenda, e o master entra no SicoobNet
e libera. Por isso o retorno do mesmo dia costuma vir com `PD` (pendente de
assinatura) em tudo — isso é o estado normal, não defeito, e a tela precisa
dizer isso com todas as letras. O desfecho real exige baixar o retorno DE NOVO
depois da assinatura.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path


@dataclass
class Linha:
    """Um pagamento do retorno, já casado (ou não) com o que foi enviado."""
    seu_numero: str
    favorecido: str
    valor: Decimal
    estado: str                      # "ok" | "pendente" | "rejeitado" | "?"
    motivos: str
    #: O id do lançamento no ERP, quando o "seu número" achou par na remessa.
    #: Vazio significa que o banco devolveu algo que não saiu por aqui.
    referencia: str = ""
    #: Quando o dinheiro saiu de verdade (campo 22.3A do retorno). É a data
    #: que a baixa no ERP tem de levar: usar "hoje" registraria o pagamento no
    #: dia em que alguém leu o arquivo, e não no dia em que ele aconteceu.
    data_real: "_dt.date | None" = None

    @property
    def rotulo(self) -> str:
        return {"ok": "PAGO", "pendente": "AGUARDA ASSINATURA",
                "rejeitado": "REJEITADO"}.get(self.estado, "SEM RESPOSTA")


@dataclass
class Resumo:
    convenio: str
    nsa: int
    empresa: str
    linhas: list[Linha] = field(default_factory=list)
    #: Pagamentos que estavam na remessa e NÃO vieram no retorno. É a pergunta
    #: que ninguém faz e que o arquivo não responde sozinho: o banco devolve o
    #: que processou, e o que sumiu no caminho não aparece em lugar nenhum.
    faltando: list[str] = field(default_factory=list)
    #: A remessa não foi encontrada no registro central.
    remessa_desconhecida: bool = False

    def quantos(self, estado: str) -> int:
        return sum(1 for l in self.linhas if l.estado == estado)

    @property
    def total(self) -> Decimal:
        return sum((l.valor for l in self.linhas), Decimal("0"))

    @property
    def estado_da_remessa(self) -> str:
        """Como marcar a remessa no registro, a partir do que veio.

        `processado` só quando TODOS deram certo. Enquanto houver um pendente,
        a remessa continua `enviado` — marcar como processada esconderia que
        falta assinatura, e a remessa sairia da lista de coisas a acompanhar
        com dinheiro ainda parado."""
        if not self.linhas:
            return "enviado"
        if self.quantos("rejeitado"):
            return "com_erro"
        if self.quantos("pendente") or self.quantos("?"):
            return "enviado"
        return "processado"


def _estado(pagamento) -> str:
    if pagamento.sem_ocorrencia:
        return "?"
    if pagamento.sucesso:
        return "ok"
    if pagamento.pendente:
        return "pendente"
    return "rejeitado"


def ler(caminho: str | Path, historico=None) -> Resumo:
    """Lê o arquivo e casa com a remessa que o gerou.

    `historico` é o registro das remessas (o `nuvem.registro.Espelhado`).
    Passando-o, cada linha ganha o id do lançamento no ERP e a lista do que
    ficou faltando. Sem ele, o resumo sai só com o que o arquivo diz.
    """
    from cnab240 import ler_arquivo_retorno

    arquivo = ler_arquivo_retorno(str(caminho))
    if not arquivo.e_retorno:
        raise ValueError(
            "este arquivo não é um retorno: o código do header diz que é "
            "remessa. Baixe o arquivo de RETORNO no SicoobNet.")

    resumo = Resumo(convenio=arquivo.convenio, nsa=arquivo.nsa,
                    empresa=arquivo.empresa)

    # O de-para "seu número" -> id do lançamento vem da remessa registrada.
    enviados: dict[str, str] = {}
    if historico is not None:
        itens = _itens_da_remessa(historico, arquivo.convenio, arquivo.nsa)
        if itens is None:
            resumo.remessa_desconhecida = True
        else:
            enviados = itens

    vistos = set()
    for pagamento in arquivo.pagamentos():
        seu = (pagamento.seu_numero or "").strip()
        vistos.add(seu)
        resumo.linhas.append(Linha(
            seu_numero=seu,
            favorecido=(pagamento.favorecido or "").strip(),
            valor=pagamento.valor,
            estado=_estado(pagamento),
            motivos="; ".join(f"{c}={d}" for c, d in pagamento.ocorrencias),
            referencia=enviados.get(seu, ""),
            data_real=getattr(pagamento, "data_real", None),
        ))

    resumo.faltando = sorted(s for s in enviados if s not in vistos)
    return resumo


def _itens_da_remessa(historico, convenio: str, nsa: int) -> dict | None:
    """{seu_numero: referencia} da remessa. None se ela não está registrada.

    None e {} querem dizer coisas diferentes: o primeiro é "não sei qual
    remessa é esta" — retorno de outra máquina, ou de antes do registro
    central — e o segundo é "conheço, e ela não tinha item nenhum"."""
    try:
        remessas = historico.remessas(convenio=convenio)
    except Exception:
        return None
    for r in remessas:
        if int(r.get("nsa") or 0) == int(nsa):
            itens = r.get("remessa_item") or r.get("itens") or []
            return {str(i.get("seu_numero") or "").strip():
                    str(i.get("referencia") or "") for i in itens}
    return None
