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
devolve o nome do recebedor como o banco o conhece ("11 222 333 FULANO" de
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
PAGO_E_AGENDADO = "pago_e_agendado"
VALOR_DIVERGE = "valor_diverge"
FALTA_NO_BANCO = "falta_no_banco"
SO_NO_BANCO = "so_no_banco"
BLOQUEADO = "bloqueado"
NOME_DIFERENTE = "nome_diferente"
JA_PAGO = "ja_pago"
OK = "ok"

GRAVIDADE = (PAGO_E_AGENDADO, VALOR_DIVERGE, FALTA_NO_BANCO, SO_NO_BANCO,
             BLOQUEADO, NOME_DIFERENTE, JA_PAGO, OK)

FRASES = {
    PAGO_E_AGENDADO: "JÁ PAGO e agendado de novo — pagamento em dobro",
    VALOR_DIVERGE: "valor diferente no banco",
    FALTA_NO_BANCO: "não está agendado no banco",
    SO_NO_BANCO: "agendado no banco e não está no HTML",
    BLOQUEADO: "agendado, mas o HTML bloqueia esta linha",
    NOME_DIFERENTE: "valor bate; conferir quem recebe",
    JA_PAGO: "já pago — nada a agendar",
    OK: "bate",
}

#: Estado da tela (`widgets.ESTADOS`) de cada situação.
ESTADO = {
    PAGO_E_AGENDADO: "erro",
    VALOR_DIVERGE: "erro",
    FALTA_NO_BANCO: "erro",
    SO_NO_BANCO: "atencao",
    BLOQUEADO: "atencao",
    NOME_DIFERENTE: "atencao",
    JA_PAGO: "info",
    OK: "ok",
}

#: Situações que não pedem nada de ninguém: ficam fora do resumo da conta.
SEM_PENDENCIA = (OK, JA_PAGO)

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


#: Estado de toda conta do Sicoob ANTES de ser lida: se a leitura parar no
#: meio, é isto que a tela mostra — nunca a conta sumindo da lista.
MOTIVO_NAO_LIDA = "não foi lida (a leitura parou antes de chegar nela)"


def agrupar_por_numero(no_sicoob) -> list[tuple[str, str, list]]:
    """`[(nomes das contas do ERP, número do Sicoob, linhas do HTML)]`.

    `no_sicoob` é `[(conta do HTML, número, motivo)]`. Duas contas do ERP
    apontando para o MESMO número do Sicoob viram uma só conferência, com as
    linhas das duas juntas: conferidas separadas, o mesmo agendamento seria
    lido duas vezes e casaria uma vez em cada, pintando de verde dois
    pagamentos com um só agendado (revisão de dinheiro, 15/10/2026). A ordem
    é a do HTML, pela primeira aparição de cada número."""
    grupos: dict[str, tuple[str, list[str], list]] = {}
    for conta, numero, _motivo in no_sicoob:
        chave = re.sub(r"\D", "", numero or "")
        _numero, nomes, linhas = grupos.setdefault(chave, (numero, [], []))
        nomes.append(str(conta.get("nome") or ""))
        linhas.extend(conta.get("entries") or [])
    # dict guarda a ordem de inserção: é a do HTML.
    return [(" + ".join(nomes), numero, linhas)
            for numero, nomes, linhas in grupos.values()]


def periodo_da_consulta(hoje: date) -> tuple[date, date]:
    """Do dia 1 do mês PASSADO ao último dia do mês que vem.

    Pendente de assinatura é o que ainda não saiu: o que se agendou hoje
    para daqui a três semanas também tem de ser conferido, e o que ficou
    sem assinar também. Começava no dia 1 DESTE mês, e no dia 1º o
    agendamento feito na véspera ficava de fora sem aviso (revisão de
    dinheiro, 15/10/2026) — e o que fica de fora da consulta é justamente o
    que a tela não mostra como "agendado e não está no HTML"."""
    inicio = (hoje.replace(day=1) - timedelta(days=1)).replace(day=1)
    depois = (hoje.replace(day=1) + timedelta(days=32)).replace(day=1)
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
        if self.situacao == BLOQUEADO and self.html is not None:
            return f"{FRASES[BLOQUEADO]}: {self.html.get('bloqueio')}"
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

    @property
    def falhou(self) -> bool:
        """Conta DO Sicoob que devia ter sido lida e não foi. Não é a conta do
        Inter que fica de fora por desenho: essa nem tem número do Sicoob.
        A diferença é de cor — esta é vermelha, porque as pendências dela
        vão ser assinadas sem conferência (revisão de dinheiro, 15/10)."""
        return bool(self.numero) and not self.conferida

    def quantos(self, situacao: str) -> int:
        return sum(1 for li in self.linhas if li.situacao == situacao)

    @property
    def total_html(self) -> Decimal:
        """O que o HTML manda pagar: a linha JÁ PAGO não entra, porque não
        tem de estar agendada e o total é para comparar com o do banco."""
        return sum((li.valor_html for li in self.linhas
                    if li.valor_html is not None and not ja_pago(li.html)),
                   Decimal("0.00"))

    @property
    def total_banco(self) -> Decimal:
        return sum((li.valor_banco for li in self.linhas
                    if li.valor_banco is not None), Decimal("0.00"))

    @property
    def pior(self) -> str:
        """A situação mais grave da conta (`OK` quando tudo bate)."""
        presentes = {li.situacao for li in self.linhas} - {JA_PAGO}
        return next((s for s in GRAVIDADE if s in presentes), OK)

    def resumo(self) -> str:
        if not self.conferida:
            return f"não conferida: {self.motivo}"
        if not self.linhas:
            return "nada no HTML e nada agendado"
        partes = [f"{self.quantos(s)} {FRASES[s]}" for s in GRAVIDADE
                  if s not in SEM_PENDENCIA and self.quantos(s)]
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


#: O que não prova que dois nomes são a mesma pessoa ou empresa: o que o
#: HTML escreve em volta do nome, a forma jurídica, o ramo de negócio e os
#: sobrenomes mais comuns. Revisão de dinheiro (15/10/2026): com só a forma
#: jurídica aqui, "ALFA MATERIAIS" no HTML e "BETA MATERIAIS" no banco
#: saíam verdes pela palavra MATERIAIS — dinheiro para outra empresa.
GENERICAS = frozenset("""
    REEMBOLSO ENG LTDA EIRELI SPE COM DOS DAS DE DA DO ME EPP MEI SA CIA
    MATERIAIS MATERIAL CONSTRUCAO CONSTRUCOES CONSTRUTORA COMERCIO
    COMERCIAL SERVICOS SERVICO ENGENHARIA DISTRIBUIDORA DISTRIBUICAO
    FERRAGENS ATACADISTA ATACADO VAREJO INDUSTRIA INDUSTRIAL
    EMPREENDIMENTOS IMOBILIARIA IMOBILIARIOS GESTAO PARTICIPACOES LOJA
    CASA CENTRO GRUPO BRASIL GOIANIA GOIAS TRANSPORTES MADEIREIRA
    ELETRICA HIDRAULICA PISOS TINTAS VIDRACARIA CONTABILIDADE
    ADVOCACIA CONSULTORIA ASSESSORIA SOLUCOES TECNOLOGIA
    SILVA SANTOS OLIVEIRA SOUZA SOUSA PEREIRA COSTA RODRIGUES ALMEIDA
    LIMA FERREIRA ALVES GOMES RIBEIRO CARVALHO MARTINS ROCHA DIAS
    MORAIS MORAES BARBOSA ARAUJO NASCIMENTO MENDES CARDOSO TEIXEIRA
    JUNIOR FILHO NETO SOBRINHO
""".split())


def nome_de_quem_recebe(favorecido) -> str:
    """No reembolso o HTML escreve "<PESSOA> (reembolso de <FORNECEDOR>)",
    e quem recebe é SÓ a pessoa. Comparar com o texto inteiro deixava a
    pendência para o FORNECEDOR sair verde (revisão de dinheiro, 15/10):
    o dinheiro iria para a loja, não para quem pagou. "?" é "não sei"."""
    nome = re.split(r"\s*\(\s*reembolso de", str(favorecido or ""),
                    maxsplit=1, flags=re.I)[0].strip()
    return "" if nome in ("", "?") else nome


#: Forma jurídica e conectivos: tirados antes de comparar o NOME INTEIRO.
_FORMA = frozenset("LTDA EIRELI SPE DOS DAS DE DA DO ME EPP MEI SA CIA".split())


def pontos_do_nome(entrada: dict, pendencia: dict) -> int:
    """Quantas palavras PRÓPRIAS o nome do HTML divide com o do banco.

    O nome INTEIRO do HTML (duas palavras ou mais, fora a forma jurídica)
    contido no do banco vale como prova mesmo feito só de palavras
    genéricas: "VIDRACARIA ALMEIDA" é a mesma "VIDRACARIA ALMEIDA LTDA", e
    tratá-la como "conferir quem recebe" era alarme falso (prova ao vivo de
    15/10/2026). "ALFA MATERIAIS" × "BETA MATERIAIS" continua sem prova."""
    do_html = _palavras(nome_de_quem_recebe(entrada.get("favorecido")))
    do_banco = _palavras(pendencia.get("detalhe"))
    inteiro = do_html - _FORMA
    if len(inteiro) >= 2 and inteiro <= do_banco:
        return len(inteiro)
    return len((do_html & do_banco) - GENERICAS)


def mesmo_recebedor(entrada: dict, pendencia: dict) -> bool:
    return pontos_do_nome(entrada, pendencia) > 0


def _descricao(texto) -> str:
    """Descrição comparável: o Sicoob põe "Observação: " na frente do boleto."""
    s = re.sub(r"^\s*observa[cç][aã]o\s*:\s*", "", str(texto or ""), flags=re.I)
    return util.norm_espaco(s)


#: Quantos caracteres o pedaço comum precisa ter para "uma descrição é o
#: começo da outra" contar como prova (ver `mesma_descricao`).
MINIMO_DO_PREFIXO = 20


def mesma_descricao(entrada: dict, pendencia: dict) -> bool:
    """A descrição do HTML é a observação (ou o detalhe) da pendência?

    Em boleto e convênio o Sicoob NÃO devolve quem recebe: o `detalhe` é
    "Observação: <o que se digitou>" (medido em 15/10/2026, em todas as
    contas). Ali a prova de que é o mesmo pagamento é a descrição colada do
    HTML — mais forte que o nome, porque leva centro de custo, NF e OC.

    **O banco corta a observação** (a de 15/10/2026 parou no meio de uma
    palavra, bem antes dos 100 caracteres que o HTML deixa colar). Por isso
    vale também uma ser o COMEÇO da outra, com duas travas: o pedaço comum
    tem `MINIMO_DO_PREFIXO` caracteres (curto demais, "OBRA X" casaria com
    qualquer lançamento da mesma obra), e o corte não cai no MEIO de um
    número — "OC 300" é o começo de "OC 3001", e são duas ordens de compra."""
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
        if (len(curta) >= MINIMO_DO_PREFIXO and longa.startswith(curta)
                and not (curta[-1].isdigit() and longa[len(curta)].isdigit())):
            return True
    return False


def ja_pago(entrada: dict | None) -> bool:
    """A linha do HTML é de título JÁ PAGO (`relatorio`: "JÁ PAGO em …")."""
    return (util.sem_acento(str((entrada or {}).get("status") or "")).upper()
            .lstrip().startswith("JA PAGO"))


def _pontos(entrada: dict, pendencia: dict) -> int:
    """A força da prova de que é o mesmo pagamento: a descrição colada vale
    mais que qualquer nome; entre nomes, mais palavras próprias em comum."""
    return (10 if mesma_descricao(entrada, pendencia) else 0) + \
        pontos_do_nome(entrada, pendencia)


def confrontar(entradas, pendencias) -> list[Linha]:
    """Casa as linhas do HTML de UMA conta com as pendências dela no banco.

    Três passadas, da prova mais forte para a mais fraca, e cada pendência
    é usada uma vez só: (1) mesmo valor e prova de que é o mesmo pagamento
    (a MELHOR prova entre as candidatas, não a primeira — senão a primeira
    linha do HTML pegava o agendamento de outra); (2) mesmo valor;
    (3) mesma descrição com valor diferente. O que sobra de cada lado é
    "falta no banco" ou "só no banco".

    Duas exceções que vêm da própria linha do HTML (revisão de dinheiro):
    linha JÁ PAGO que casa com um agendamento é pagamento em DOBRO, e sem
    agendamento não é falta nenhuma; linha com `bloqueio` (risco de pagar em
    dobro, pagar à mão…) nunca sai verde."""
    sobra_html = list(entradas or [])
    sobra_banco = list(pendencias or [])
    casadas: list[Linha] = []

    def situacao(e, base):
        if ja_pago(e):
            return PAGO_E_AGENDADO
        if base == OK and str(e.get("bloqueio") or "").strip():
            return BLOQUEADO
        return base

    def passada(combina, base, pontos=None):
        for e in list(sobra_html):
            candidatas = [p for p in sobra_banco if combina(e, p)]
            if not candidatas:
                continue
            par = (max(candidatas, key=lambda p: pontos(e, p)) if pontos
                   else candidatas[0])
            sobra_html.remove(e)
            sobra_banco.remove(par)
            casadas.append(Linha(situacao(e, base), e, par))

    def mesmo_valor(e, p):
        return int(e.get("centavos") or 0) == centavos_do_banco(p)

    passada(lambda e, p: mesmo_valor(e, p) and _pontos(e, p) > 0, OK, _pontos)
    passada(mesmo_valor, NOME_DIFERENTE)
    passada(mesma_descricao, VALOR_DIVERGE)

    linhas = (casadas
              + [Linha(JA_PAGO if ja_pago(e) else FALTA_NO_BANCO, e, None)
                 for e in sobra_html]
              + [Linha(SO_NO_BANCO, None, p) for p in sobra_banco])
    ordem = {s: i for i, s in enumerate(GRAVIDADE)}
    # Estável: dentro da mesma situação, a ordem do HTML (que é a do dono).
    return sorted(linhas, key=lambda li: ordem[li.situacao])
