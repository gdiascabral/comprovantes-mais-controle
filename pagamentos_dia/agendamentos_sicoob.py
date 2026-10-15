# -*- coding: utf-8 -*-
"""Confronto do HTML dos pagamentos com os agendamentos pendentes no Sicoob.

Pedido do dono em 15/10/2026: depois de agendar no SicoobNet o que o HTML
mandava pagar, conferir — antes de assinar — se cada agendamento bate com a
linha do HTML: valor, quem recebe e se nada ficou para trás. Feito à mão
naquele dia, o confronto achou um boleto agendado com R$ 0,00 (a linha
digitável dizia o valor certo) e um Pix que o HTML mandava pagar e ninguém
agendou. É o tipo de coisa que só aparece DEPOIS de o dinheiro sair.

Este módulo é a regra, sem tela, sem navegador e sem rede — o par dele que
fala com o banco é `extratos_sicoob/pendencias.py`. Três peças:

- `ler_html` lê as contas de volta do HTML gravado (o `const DATA` que o
  próprio `html_pagamentos` escreve). O confronto é com o HTML, e não com o
  passo 2 em memória, porque é o HTML que se usou para agendar — e ele pode
  ter saído sem os reembolsos, numa rodada que o app já nem tem aberta;
- `conta_sicoob` traduz a conta do ERP no número da conta do Sicoob, pelo
  MESMO caminho da remessa (`contas_mc.json` + `contas_sicoob.json`, pasta e
  sufixo), sem cobrar convênio: conferir agendamento não gera arquivo;
- `confrontar` casa as linhas de uma conta com as pendências dela.

**O casamento é pelo VALOR em centavos, e o nome só desempata.** O Sicoob
devolve o nome do recebedor como o banco o conhece ("40 803 766 FULANO" de
um MEI, a razão social inteira), não como o ERP o escreve; casar pelo nome
erraria justamente onde é legítimo. Entre dois agendamentos do mesmo valor,
ganha o que divide uma palavra com o favorecido. Valor que casa com nome que
não divide palavra nenhuma não é erro — reembolso vai para quem pagou, QR
Code de loja vai para o dono da maquininha —, mas é o que se olha antes de
assinar, e por isso sai em âmbar.

**Sobrou dos dois lados com a mesma descrição = valor diverge.** O boleto de
R$ 0,00 de 15/10 tinha a observação idêntica à descrição do HTML; casar pela
descrição o põe na mesma linha da tela com os dois valores lado a lado, em
vez de um "falta no banco" e um "só no banco" que ninguém liga um ao outro.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import util

from . import remessa_dia


# Situações de uma linha do confronto. A ordem é a da gravidade: é a ordem
# em que a tela as lista e a primeira que o resumo da conta cita.
VALOR_DIVERGE = "valor_diverge"
FALTA_NO_BANCO = "falta_no_banco"
SO_NO_BANCO = "so_no_banco"
NOME_DIFERENTE = "nome_diferente"
OK = "ok"

GRAVIDADE = (VALOR_DIVERGE, FALTA_NO_BANCO, SO_NO_BANCO, NOME_DIFERENTE, OK)

FRASES = {
    VALOR_DIVERGE: "valor diferente no banco",
    FALTA_NO_BANCO: "não está agendado no banco",
    SO_NO_BANCO: "agendado no banco e não está no HTML",
    NOME_DIFERENTE: "valor bate; conferir quem recebe",
    OK: "bate",
}

#: Estado da tela (`widgets.ESTADOS`) de cada situação.
ESTADO = {
    VALOR_DIVERGE: "erro",
    FALTA_NO_BANCO: "erro",
    SO_NO_BANCO: "atencao",
    NOME_DIFERENTE: "atencao",
    OK: "ok",
}

MOTIVO_SEM_DADOS = ("este arquivo não é um HTML dos pagamentos do app "
                    "(não achei os dados dentro dele)")


# ------------------------------------------------------------------ o HTML

_DATA = re.compile(r"const\s+DATA\s*=\s*(\{.*?\});\s*\n", re.S)


def ler_html(texto: str) -> list[dict]:
    """As contas gravadas no HTML geral, como `html_pagamentos` as escreveu.

    O JSON vai para o `<script>` com `<`, `>` e `&` em escape unicode
    (`html_pagamentos.json_para_script`), que é JSON válido — então volta
    por `json.loads` sem tradução. Levanta `ValueError` com
    `MOTIVO_SEM_DADOS` quando o arquivo não é um desses HTMLs (o de pessoa
    física, por exemplo, tem outro formato)."""
    achado = _DATA.search(texto or "")
    if not achado:
        raise ValueError(MOTIVO_SEM_DADOS)
    try:
        dado = json.loads(achado.group(1))
    except json.JSONDecodeError as e:
        raise ValueError(MOTIVO_SEM_DADOS) from e
    contas = dado.get("contas") if isinstance(dado, dict) else None
    if not isinstance(contas, list):
        raise ValueError(MOTIVO_SEM_DADOS)
    return contas


# --------------------------------------------------------- conta do Sicoob

MOTIVO_CONTA_DESCONHECIDA = remessa_dia.MOTIVO_CONTA_DESCONHECIDA
#: Próprio, e não o da remessa: aquele fala de CNAB 240, e aqui ninguém
#: está gerando arquivo. Conta do Inter no HTML é o caso comum, não defeito.
MOTIVO_FORA_SICOOB = "conta de outro banco (não é do Sicoob)"
MOTIVO_SEM_BANCO = remessa_dia.MOTIVO_SEM_BANCO


def conta_sicoob(conta_erp: str, mapa_mc, empresas) -> tuple[str, str]:
    """`(número da conta no Sicoob, "")`, ou `("", motivo)`.

    O caminho é o da remessa (`remessa_dia._escolher_conta`), para as duas
    nunca escolherem contas diferentes para a mesma conta do ERP — mas sem a
    prontidão inteira: convênio, CNPJ e agência servem ao ARQUIVO, e conferir
    um agendamento só precisa saber em qual conta entrar."""
    destino = mapa_mc.de(conta_erp) if mapa_mc else None
    if destino is None:
        return "", MOTIVO_CONTA_DESCONHECIDA
    if not (destino.banco or "").strip():
        return "", MOTIVO_SEM_BANCO
    if not remessa_dia._e_sicoob(destino.banco):
        return "", MOTIVO_FORA_SICOOB
    _empresa, conta, falta = remessa_dia._escolher_conta(destino, empresas)
    if falta or conta is None:
        return "", falta or MOTIVO_CONTA_DESCONHECIDA
    numero = (conta.numero or "").strip()
    if not re.sub(r"\D", "", numero):
        return "", MOTIVO_CONTA_DESCONHECIDA
    return numero, ""


def periodo_da_consulta(hoje: date) -> tuple[date, date]:
    """Do dia 1 deste mês ao último dia do mês que vem.

    Pendente de assinatura é o que ainda não saiu: o que se agendou hoje
    para daqui a três semanas também tem de ser conferido, e o que ficou
    sem assinar desde o começo do mês também. Dois meses cobrem o dia a dia
    sem trazer agendamento antigo esquecido como se fosse de hoje."""
    inicio = hoje.replace(day=1)
    depois = (inicio + timedelta(days=32)).replace(day=1)
    fim = (depois + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return inicio, fim


# -------------------------------------------------------------- o confronto

@dataclass
class Linha:
    situacao: str
    #: A entrada do HTML (`entries` de uma conta), ou None quando só há banco.
    html: dict | None = None
    #: A pendência do Sicoob, ou None quando só há HTML.
    banco: dict | None = None

    @property
    def frase(self) -> str:
        return FRASES[self.situacao]

    @property
    def valor_html(self) -> Decimal | None:
        if self.html is None:
            return None
        return Decimal(int(self.html.get("centavos") or 0)) / 100

    @property
    def valor_banco(self) -> Decimal | None:
        if self.banco is None:
            return None
        return centavos_do_banco(self.banco) / Decimal(100)


@dataclass
class Confronto:
    conta_erp: str
    numero: str = ""
    #: Por que esta conta não foi conferida (fora do Sicoob, cadastro, falha
    #: do banco). Vazio quando foi.
    motivo: str = ""
    linhas: list[Linha] = field(default_factory=list)

    @property
    def conferida(self) -> bool:
        return not self.motivo

    def quantos(self, situacao: str) -> int:
        return sum(1 for li in self.linhas if li.situacao == situacao)

    @property
    def total_html(self) -> Decimal:
        return sum((li.valor_html for li in self.linhas
                    if li.valor_html is not None), Decimal("0.00"))

    @property
    def total_banco(self) -> Decimal:
        return sum((li.valor_banco for li in self.linhas
                    if li.valor_banco is not None), Decimal("0.00"))

    @property
    def pior(self) -> str:
        """A situação mais grave da conta (`OK` quando tudo bate)."""
        presentes = {li.situacao for li in self.linhas}
        return next((s for s in GRAVIDADE if s in presentes), OK)

    def resumo(self) -> str:
        if not self.conferida:
            return f"não conferida: {self.motivo}"
        if not self.linhas:
            return "nada no HTML e nada agendado"
        partes = [f"{self.quantos(s)} {FRASES[s]}" for s in GRAVIDADE
                  if s != OK and self.quantos(s)]
        if not partes:
            return f"tudo bate ({self.quantos(OK)} agendamento(s))"
        return " · ".join(partes)


def centavos_do_banco(pendencia: dict) -> int:
    """O valor da pendência em centavos. O Sicoob manda número (80.0);
    `Decimal(str(...))` evita o 0,1 + 0,2 do float."""
    try:
        return int((Decimal(str(pendencia.get("valor") or 0)) * 100)
                   .quantize(Decimal(1)))
    except (ArithmeticError, ValueError):
        return 0


def _palavras(texto) -> set[str]:
    """Palavras de 3+ letras, sem acento e sem caixa. Número e sigla curta
    não servem de prova de que é a mesma pessoa (QD, LT, NF, 01)."""
    limpo = util.sem_acento(str(texto or "")).upper()
    return {p for p in re.findall(r"[A-Z]+", limpo) if len(p) >= 3}


#: O que o HTML escreve em volta do nome e não é nome de ninguém.
_RUIDO = {"REEMBOLSO", "ENG", "LTDA", "EIRELI", "SPE", "COM", "DOS", "DAS",
          "DE", "DA", "DO"}


def mesmo_recebedor(entrada: dict, pendencia: dict) -> bool:
    """O nome do HTML divide uma palavra própria com o recebedor do banco?"""
    do_html = _palavras(entrada.get("favorecido")) - _RUIDO
    do_banco = _palavras(pendencia.get("detalhe")) - _RUIDO
    return bool(do_html & do_banco)


def _descricao(texto) -> str:
    """Descrição comparável: o Sicoob põe "Observação: " na frente do boleto."""
    s = re.sub(r"^\s*observa[cç][aã]o\s*:\s*", "", str(texto or ""), flags=re.I)
    return util.norm_espaco(s)


def mesma_descricao(entrada: dict, pendencia: dict) -> bool:
    """A descrição do HTML é a observação (ou o detalhe) da pendência?

    Em boleto e convênio o Sicoob NÃO devolve quem recebe: o `detalhe` é
    "Observação: <o que se digitou>" (medido em 15/10/2026, em todas as
    contas). Ali a prova de que é o mesmo pagamento é a descrição colada do
    HTML — mais forte que o nome, porque leva centro de custo, NF e OC.

    **O banco corta a observação** (a de 15/10/2026 parou no meio de uma
    palavra, bem antes dos 100 caracteres que o HTML deixa colar). Por isso
    vale também uma ser o COMEÇO da outra, desde que o pedaço comum tenha
    `MINIMO_DO_PREFIXO` caracteres — curto demais, "OBRA X" casaria com
    qualquer lançamento da mesma obra."""
    d = _descricao(entrada.get("descricao"))
    if not d:
        return False
    for b in (_descricao(pendencia.get("observacao")),
              _descricao(pendencia.get("detalhe"))):
        if not b:
            continue
        if d == b:
            return True
        curta, longa = sorted((d, b), key=len)
        if len(curta) >= MINIMO_DO_PREFIXO and longa.startswith(curta):
            return True
    return False


#: Quantos caracteres o pedaço comum precisa ter para "uma descrição é o
#: começo da outra" contar como prova (ver `mesma_descricao`).
MINIMO_DO_PREFIXO = 20


def mesmo_pagamento(entrada: dict, pendencia: dict) -> bool:
    return mesmo_recebedor(entrada, pendencia) or mesma_descricao(entrada,
                                                                  pendencia)


def confrontar(entradas, pendencias) -> list[Linha]:
    """Casa as linhas do HTML de UMA conta com as pendências dela no banco.

    Três passadas, da prova mais forte para a mais fraca, e cada pendência
    é usada uma vez só: (1) mesmo valor e o nome bate; (2) mesmo valor;
    (3) mesma descrição com valor diferente. O que sobra de cada lado é
    "falta no banco" ou "só no banco"."""
    sobra_html = list(entradas or [])
    sobra_banco = list(pendencias or [])
    casadas: list[Linha] = []

    def passada(combina, situacao_de):
        for e in list(sobra_html):
            par = next((p for p in sobra_banco if combina(e, p)), None)
            if par is not None:
                sobra_html.remove(e)
                sobra_banco.remove(par)
                casadas.append(Linha(situacao_de(e, par), e, par))

    def mesmo_valor(e, p):
        return int(e.get("centavos") or 0) == centavos_do_banco(p)

    passada(lambda e, p: mesmo_valor(e, p) and mesmo_pagamento(e, p),
            lambda e, p: OK)
    passada(mesmo_valor, lambda e, p: NOME_DIFERENTE)
    passada(mesma_descricao, lambda e, p: VALOR_DIVERGE)

    linhas = (casadas
              + [Linha(FALTA_NO_BANCO, e, None) for e in sobra_html]
              + [Linha(SO_NO_BANCO, None, p) for p in sobra_banco])
    ordem = {s: i for i, s in enumerate(GRAVIDADE)}
    # Estável: dentro da mesma situação, a ordem do HTML (que é a do dono).
    return sorted(linhas, key=lambda li: ordem[li.situacao])
