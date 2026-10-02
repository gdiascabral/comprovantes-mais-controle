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
import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

import util

from .dados import INVESTIDOR_PREFIXO

#: "Aporte de Investidor" (01/10/2026): o dinheiro que um investidor de
#: fora manda para a SUBCONTA dele. Só existe a perna do recebimento — o
#: investidor não tem conta aqui —, e a natureza é a própria do ERP.
TIPO_INVESTIDOR = "Aporte de Investidor"

PREFIXO_DESCRICAO = {
    "Aporte de Capital": "APORTE CAPITAL",
    "Distribuição de Lucro": "DISTRIBUIÇÃO DE LUCRO",
    TIPO_INVESTIDOR: "APORTE INVESTIDOR",
}
CATEGORIA_PAGAMENTO = {
    "Aporte de Capital": "APORTE CAPITAL",
    "Distribuição de Lucro": "DISTRIBUIÇÃO DE LUCROS",
}
NATUREZA_RECEBIMENTO = {
    "Aporte de Capital": "Aporte de Capital",
    "Distribuição de Lucro": "Outras receitas",
    TIPO_INVESTIDOR: "Aporte de Investidor",
}


def nome_na_descricao(entidades: dict, exibicao: str) -> str:
    """Como a entidade aparece no TEXTO da descrição.

    Ordem: apelido > nome da conta > nome oficial. O apelido existe para conta
    conjunta: o lançamento sai no nome de uma pessoa, mas a descrição precisa
    citar as duas."""
    dados = entidades.get(exibicao) or {}
    return (dados.get("nome_descricao") or dados.get("conta")
            or dados.get("nome_oficial") or exibicao)


#: "11111-1", "22.222-2", "33333 - 3": o número da conta no nome. O
#: `(?<!\d)` é o que impede ler "34567-8" de dentro de "1234567-8" — sem ele
#: uma conta de 7 dígitos virava a subconta de outra pessoa.
_NUMERO_CONTA = re.compile(r"(?<!\d)(\d{2})\.?(\d{3})\s*-\s*(\d)\b")


def numero_da_conta(texto) -> str:
    """O número no formato da tabela `subconta` ("00000-0"), ou ""."""
    m = _NUMERO_CONTA.search(str(texto or ""))
    return f"{m.group(1)}{m.group(2)}-{m.group(3)}" if m else ""


def e_da_subconta(nome: str, dados: dict, numero: str) -> bool:
    """A linha de Pagou/Recebeu é a conta desta subconta? Pelo NÚMERO lido
    da conta (ou do nome), e não por "o texto contém": "112345-6" contém
    "12345-6" e é outra conta."""
    return numero_da_conta((dados or {}).get("conta") or "") == numero or \
        numero_da_conta(nome) == numero


def numero_subconta(pagador: str, subcontas: dict) -> str | None:
    if pagador.startswith(INVESTIDOR_PREFIXO):
        numero = pagador[len(INVESTIDOR_PREFIXO):]
        if numero in subcontas:
            return numero
    return None


def como_dinheiro(valor) -> Decimal:
    """Converte para Decimal com 2 casas, arredondando como banco.

    Dinheiro em float erra: 0.1 + 0.2 != 0.3, e aqui o número vai DIRETO para
    um lançamento no ERP. O padrão do projeto já é Decimal (ver
    conciliacao/models.py); os aportes eram a última ilha de float — logo no
    módulo que ESCREVE valores."""
    if isinstance(valor, Decimal):
        d = valor
    elif isinstance(valor, float):
        d = Decimal(str(valor))          # str() evita o lixo binário do float
    else:
        d = Decimal(valor or 0)
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


#: Valor como se escreve no Brasil: ponto no milhar (em grupos de três) e
#: vírgula nos centavos. "1.500,50", "1500,50", "1.234.567,89", "1500".
_VALOR_BR = re.compile(r"(?P<inteiro>\d{1,3}(?:\.\d{3})+|\d+)"
                       r"(?:,(?P<centavos>\d+))?")

_EXEMPLO = "Use vírgula para os centavos, ex.: 1.500,50"


def ler_valor_brl(texto) -> Decimal:
    """O valor digitado na tela, em Decimal com 2 casas. Recusa com
    `ValueError` — a mensagem é para mostrar a quem digitou.

    Ponto SEM vírgula é recusado, e não adivinhado: "1500.50" pode ser mil e
    quinhentos com centavos ou cento e cinquenta mil, e a leitura antiga
    (apagar todo ponto) escolhia a segunda — lançava R$ 150.050,00 no ERP.
    Recusar custa redigitar; chutar errado custa desfazer lançamento no ERP.
    Pelo mesmo motivo, mais de 2 casas depois da vírgula é recusado em vez de
    arredondado, e zero ou negativo nunca é valor de aporte.

    Não reaproveita os leitores que já existem, e cada um tem o seu motivo:
    `widgets.valor_de_brl` arrasta tkinter para o módulo de regra, devolve
    float e apaga todo ponto (o mesmo defeito); `conciliacao.parsing.parse_brl`
    procura o PRIMEIRO valor dentro de um texto (aceitaria "10,00 abc"); e o
    `_centavos` do `anexar/mc_client.py` lê "1500.50" como decimal americano,
    que é justamente o chute que aqui não se faz."""
    t = str(texto or "").replace("\xa0", " ").strip()
    t = re.sub(r"^r\$", "", t, flags=re.IGNORECASE).strip()
    negativo = t.startswith("-") or (t.startswith("(") and t.endswith(")"))
    if negativo:
        t = t.strip("()-").strip()
    if not t:
        raise ValueError(f"Digite o valor. {_EXEMPLO}")
    if "." in t and "," not in t:
        raise ValueError(f"\"{t}\" é ambíguo: o ponto pode ser milhar ou "
                         f"centavos. {_EXEMPLO}")
    m = _VALOR_BR.fullmatch(t)
    if not m:
        raise ValueError(f"Valor inválido: \"{t}\". {_EXEMPLO}")
    centavos = m.group("centavos") or "0"
    if len(centavos) > 2:
        raise ValueError("Use no máximo 2 casas depois da vírgula, "
                         "ex.: 1.500,50")
    try:
        valor = como_dinheiro(
            Decimal(f"{m.group('inteiro').replace('.', '')}.{centavos}"))
    except ArithmeticError:
        # Dígitos demais para o Decimal (`quantize` passa da precisão). A
        # tela só mostra `ValueError`; o resto viraria clique sem resposta.
        raise ValueError(f"Valor grande demais: \"{t}\".") from None
    if negativo or valor <= 0:
        raise ValueError("O valor precisa ser maior que zero.")
    return valor


def formatar_brl(valor) -> str:
    """R$ 1.234,56 — o que `widgets.brl` escreve na tela, sem tkinter e sem
    float (este módulo roda sem interface; ver "util.py não importa tkinter"
    no CLAUDE.md). O formato `,.2f` cru, com "R$" na frente, escrevia
    "R$ 150,050.00", que para quem lê em português não parece 150 mil."""
    texto = f"{como_dinheiro(valor):,.2f}"
    return "R$ " + texto.replace(",", "X").replace(".", ",").replace("X", ".")


def dividir_em_centavos(total, n: int) -> list[Decimal]:
    """Divide em n partes iguais; a sobra de centavos vai para as primeiras.
    A soma sempre fecha com o total — é dinheiro, não pode faltar centavo."""
    if n <= 0:
        raise ValueError("não dá para dividir em zero partes")
    centavos = int(como_dinheiro(total) * 100)
    base, sobra = divmod(centavos, n)
    return [Decimal(base + (1 if i < sobra else 0)) / 100 for i in range(n)]


def peso_de(pesos: dict, investidor: str):
    """A parte de um aportador (Decimal) ou None. Sem acento e sem caixa."""
    alvo = util.norm_espaco(investidor)
    for nome, peso in (pesos or {}).items():
        if util.norm_espaco(nome) == alvo and str(peso).strip() != "":
            return Decimal(str(peso).replace(",", "."))
    return None


def problema_dos_pesos(investidores, pesos) -> str:
    """"" quando a divisão entre aportadores pode ser feita; senão, o motivo.

    A parte é um PESO, não um %: "60 e 40" e "3 e 2" dão o mesmo rateio, e
    "2:1" se escreve 2 e 1. Por isso não há soma a fechar. Vazio em todos =
    partes iguais. Preenchido, é em TODOS e maior que zero — um aportador sem
    parte não teria como receber a dele."""
    if not pesos:
        return ""
    valores = [peso_de(pesos, i) for i in investidores]
    if all(v is None for v in valores):
        return ""
    faltam = [i for i, v in zip(investidores, valores) if v is None]
    if faltam:
        return f"falta a parte de: {', '.join(faltam)}"
    if any(not v.is_finite() for v in valores):
        return "parte que não é número"
    if any(v <= 0 for v in valores):
        return "toda parte precisa ser maior que zero"
    if any(v != v.quantize(Decimal("0.0001")) for v in valores):
        return "use no máximo 4 casas na parte"
    return ""


def dividir_por_peso(total, nomes, pesos) -> list[Decimal]:
    """O valor de cada um, na proporção dos pesos. Sem peso = partes iguais.

    Cada um leva a sua fração arredondada PARA BAIXO em centavos, e os
    centavos que sobram vão um a um para quem teve o maior resto (empate: o
    que vem antes). A soma fecha sempre com o total — é dinheiro."""
    problema = problema_dos_pesos(nomes, pesos)
    if problema:
        raise ValueError(f"divisão entre aportadores: {problema}")
    valores = [peso_de(pesos, n) for n in nomes]
    if not pesos or all(v is None for v in valores):
        return dividir_em_centavos(total, len(nomes))
    centavos = int(como_dinheiro(total) * 100)
    soma = sum(valores)
    brutos = [Decimal(centavos) * v / soma for v in valores]
    base = [int(b) for b in brutos]                  # para baixo
    sobra = centavos - sum(base)
    ordem = sorted(range(len(nomes)), key=lambda i: (-(brutos[i] - base[i]), i))
    for i in ordem[:sobra]:
        base[i] += 1
    return [Decimal(c) / 100 for c in base]


def percentuais_dos_pesos(investidores, pesos) -> list[Decimal]:
    """O % de cada aportador, para MOSTRAR (2 casas). Não entra em conta."""
    valores = [peso_de(pesos, i) for i in investidores]
    if not investidores:
        return []
    if not pesos or any(v is None for v in valores):
        return [como_dinheiro(Decimal(100) / len(investidores))] * len(investidores)
    soma = sum(valores)
    return [como_dinheiro(v * 100 / soma) for v in valores]


@dataclass
class Operacao:
    data: datetime.date
    pagador: str
    recebedor: str
    valor: Decimal
    tipo: str        # "Aporte de Capital" | "Distribuição de Lucro" | TIPO_INVESTIDOR
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
            if self.tipo != TIPO_INVESTIDOR:
                erros.append(f"'{self.pagador}' é investidor de subconta: o "
                             f"tipo tem de ser '{TIPO_INVESTIDOR}'.")
            if self.modo != "Só recebimento":
                erros.append(f"'{self.pagador}' gera só recebimentos — "
                             "use o modo 'Só recebimento'.")
            # Sem obras ou sem investidores, o rateio produzia ZERO lançamentos
            # e o valor simplesmente sumia: nenhum erro, nenhum aviso, e a
            # planilha do mês fechando a menos sem ninguém saber por quê.
            cfg = subcontas.get(grupo) or {}
            if not (cfg.get("obras") or []):
                erros.append(f"A subconta {grupo} não tem OBRAS no "
                             "subcontas.json — o rateio ficaria vazio.")
            if not (cfg.get("investidores") or []):
                erros.append(f"A subconta {grupo} não tem INVESTIDORES no "
                             "subcontas.json — o rateio ficaria vazio.")
            problema = problema_dos_pesos(cfg.get("investidores") or [],
                                          cfg.get("pesos") or {})
            if problema:
                erros.append(f"Rateio da subconta {grupo}: {problema}.")
            if not e_da_subconta(self.recebedor, entidades[self.recebedor],
                                 grupo):
                erros.append(f"O recebedor de '{self.pagador}' deve ser a "
                             f"subconta {grupo}.")
            return erros

        if self.tipo == TIPO_INVESTIDOR:
            # Aporte de investidor é sempre dinheiro de FORA entrando numa
            # conta nossa: não há pagamento a lançar do outro lado. Pagador
            # com conta nossa é empresa da casa — com este tipo, a saída dela
            # nunca entraria no ERP.
            if entidades[self.pagador].get("conta"):
                erros.append(f"{self.pagador} tem conta no app: aporte entre "
                             f"contas da casa não é '{TIPO_INVESTIDOR}'.")
            if self.modo != "Só recebimento":
                erros.append(f"'{TIPO_INVESTIDOR}' só existe como 'Só "
                             "recebimento'.")
            if entidades[self.recebedor].get("conta") is None:
                erros.append(f"{self.recebedor} não tem conta para receber.")
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
                f"{formatar_brl(self.valor)} · {self.tipo} · {self.modo}")


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
            # O `max(1, ...)` de antes escondia o problema: sem obras ou sem
            # investidores o laço abaixo não roda, e a operação virava ZERO
            # lançamentos com o valor sumindo em silêncio. `validar()` já
            # barra isso na tela; aqui é a rede de segurança para quem chamar
            # `expandir` direto.
            if not obras or not investidores:
                raise ValueError(
                    f"a subconta {grupo} está sem obras e/ou investidores no "
                    "subcontas.json — o rateio sairia vazio e o valor de "
                    f"{formatar_brl(op.valor)} sumiria.")
            # Primeiro entre os aportadores, na proporção de cada um; depois
            # a parte de cada aportador em partes IGUAIS entre as obras.
            por_investidor = dividir_por_peso(op.valor, investidores,
                                              cfg.get("pesos") or {})
            partes = {inv: dividir_em_centavos(v, len(obras))
                      for inv, v in zip(investidores, por_investidor)}
            for k, obra in enumerate(obras):
                for investidor in investidores:
                    parte = partes[investidor][k]
                    itens.append({
                        "tipo_lancamento": "recebimento",
                        "data": op.data, "valor": parte,
                        "descricao": f"{PREFIXO_DESCRICAO[op.tipo]} - "
                                     f"{investidor} PARA "
                                     f"{nome_na_descricao(entidades, op.recebedor)}",
                        "conta_recebedora": conta_recebedora,
                        "cliente": investidor,
                        "natureza": NATUREZA_RECEBIMENTO[op.tipo],
                        "forma": op.forma, "obra": obra,
                    })
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
