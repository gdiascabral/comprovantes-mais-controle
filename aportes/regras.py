# -*- coding: utf-8 -*-
"""
Regras de aporte de capital e distribuição de lucro.

Decide, para cada operação, o que vai virar pagamento, o que vira recebimento,
e com que descrição, categoria e natureza. Não conversa com o ERP nem com a
tela: só transforma uma operação em uma lista de lançamentos a criar.

Portado do gerador de planilhas — a regra é a mesma; muda só o destino, que
agora é a API em vez de duas linhas de .xlsx.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

from dados import INVESTIDOR_PREFIXO

PREFIXO_DESCRICAO = {
    "Aporte de Capital": "APORTE CAPITAL",
    "Distribuição de Lucro": "DISTRIBUIÇÃO DE LUCRO",
}
CATEGORIA_PAGAMENTO = {
    "Aporte de Capital": "APORTE CAPITAL",
    "Distribuição de Lucro": "DISTRIBUIÇÃO DE LUCROS",
}
NATUREZA_RECEBIMENTO = {
    "Aporte de Capital": "Aporte de Capital",
    "Distribuição de Lucro": "Outras receitas",
}


def nome_na_descricao(entidades: dict, exibicao: str) -> str:
    """Como a entidade aparece no TEXTO da descrição.

    Ordem: apelido > nome da conta > nome oficial. O apelido existe para conta
    conjunta: o lançamento sai no nome de uma pessoa, mas a descrição precisa
    citar as duas."""
    dados = entidades.get(exibicao) or {}
    return (dados.get("nome_descricao") or dados.get("conta")
            or dados.get("nome_oficial") or exibicao)


def numero_subconta(pagador: str, subcontas: dict) -> str | None:
    if pagador.startswith(INVESTIDOR_PREFIXO):
        numero = pagador[len(INVESTIDOR_PREFIXO):]
        if numero in subcontas:
            return numero
    return None


def dividir_em_centavos(total: float, n: int) -> list[float]:
    """Divide em n partes iguais; a sobra de centavos vai para as primeiras.
    A soma sempre fecha com o total — é dinheiro, não pode faltar centavo."""
    centavos = round(total * 100)
    base, sobra = divmod(centavos, n)
    return [(base + (1 if i < sobra else 0)) / 100 for i in range(n)]


@dataclass
class Operacao:
    data: datetime.date
    pagador: str
    recebedor: str
    valor: float
    tipo: str        # "Aporte de Capital" | "Distribuição de Lucro"
    modo: str        # "Pagamento + Recebimento" | "Só pagamento" | "Só recebimento"
    forma: str = "Pix"

    def validar(self, entidades: dict, subcontas: dict) -> list[str]:
        erros = []
        grupo = numero_subconta(self.pagador, subcontas)
        if grupo is None and self.pagador not in entidades:
            erros.append(f"Pagador desconhecido: {self.pagador}")
        if self.recebedor not in entidades:
            erros.append(f"Recebedor desconhecido: {self.recebedor}")
        if not self.valor or self.valor <= 0:
            erros.append("Valor precisa ser maior que zero")
        if self.pagador == self.recebedor:
            erros.append("Pagador e recebedor não podem ser o mesmo")
        if erros:
            return erros

        if grupo is not None:
            if self.tipo != "Aporte de Capital":
                erros.append(f"'{self.pagador}' só vale para Aporte de Capital.")
            if self.modo != "Só recebimento":
                erros.append(f"'{self.pagador}' gera só recebimentos — "
                             "use o modo 'Só recebimento'.")
            conta_rec = entidades[self.recebedor].get("conta") or ""
            if grupo not in self.recebedor and grupo not in conta_rec:
                erros.append(f"O recebedor de '{self.pagador}' deve ser a "
                             f"subconta {grupo}.")
            return erros

        # Pessoa física não tem conta cadastrada aqui, porque não controlamos
        # contas pessoais. Só existe a perna da empresa:
        #   PF paga   -> lançamos só a entrada  (Só recebimento)
        #   PF recebe -> lançamos só a saída    (Só pagamento)
        if entidades[self.pagador].get("conta") is None and self.modo in (
                "Pagamento + Recebimento", "Só pagamento"):
            erros.append(f"{self.pagador} é pessoa física sem conta — só pode "
                         "ser lançado como 'Só recebimento'.")
        if entidades[self.recebedor].get("conta") is None and self.modo in (
                "Pagamento + Recebimento", "Só recebimento"):
            erros.append(f"{self.recebedor} é pessoa física sem conta — só pode "
                         "ser lançado como 'Só pagamento'.")
        return erros

    def descricao(self, entidades: dict, subcontas: dict) -> str:
        if numero_subconta(self.pagador, subcontas) is not None:
            de = self.pagador
        else:
            de = nome_na_descricao(entidades, self.pagador)
        para = nome_na_descricao(entidades, self.recebedor)
        return f"{PREFIXO_DESCRICAO[self.tipo]} - {de} PARA {para}"

    def resumo(self) -> str:
        return (f"{self.data:%d/%m} · {self.pagador} → {self.recebedor} · "
                f"R$ {self.valor:,.2f} · {self.tipo} · {self.modo}")


def expandir(op: Operacao, entidades: dict, subcontas: dict,
             obra_padrao: str) -> list[dict]:
    """Traduz uma operação nos lançamentos que serão criados no ERP.

    Devolve uma lista de dicionários prontos para `mc_lancamentos`. Uma
    operação pode virar dois lançamentos (pagamento + recebimento) ou vários,
    no caso do rateio de investidores."""
    itens: list[dict] = []
    grupo = numero_subconta(op.pagador, subcontas)
    descricao = op.descricao(entidades, subcontas)

    if grupo is None and op.modo in ("Pagamento + Recebimento", "Só pagamento"):
        itens.append({
            "tipo_lancamento": "pagamento",
            "data": op.data, "valor": op.valor, "descricao": descricao,
            "conta_pagadora": entidades[op.pagador]["conta"],
            "favorecido": entidades[op.recebedor]["nome_oficial"],
            "categoria": CATEGORIA_PAGAMENTO[op.tipo],
            "forma": op.forma, "obra": obra_padrao,
        })

    if op.modo in ("Pagamento + Recebimento", "Só recebimento"):
        conta_recebedora = entidades[op.recebedor]["conta"]
        if grupo is not None:
            # Rateio: uma linha por (obra × investidor), valor dividido igual.
            cfg = subcontas[grupo]
            obras = cfg.get("obras") or []
            investidores = cfg.get("investidores") or []
            partes = dividir_em_centavos(op.valor,
                                         max(1, len(obras) * len(investidores)))
            i = 0
            for obra in obras:
                for investidor in investidores:
                    itens.append({
                        "tipo_lancamento": "recebimento",
                        "data": op.data, "valor": partes[i],
                        "descricao": f"{PREFIXO_DESCRICAO[op.tipo]} - "
                                     f"{investidor} PARA "
                                     f"{nome_na_descricao(entidades, op.recebedor)}",
                        "conta_recebedora": conta_recebedora,
                        "cliente": investidor,
                        "natureza": NATUREZA_RECEBIMENTO[op.tipo],
                        "forma": op.forma, "obra": obra,
                    })
                    i += 1
        else:
            itens.append({
                "tipo_lancamento": "recebimento",
                "data": op.data, "valor": op.valor, "descricao": descricao,
                "conta_recebedora": conta_recebedora,
                "cliente": entidades[op.pagador]["nome_oficial"],
                "natureza": NATUREZA_RECEBIMENTO[op.tipo],
                "forma": op.forma, "obra": obra_padrao,
            })
    return itens
