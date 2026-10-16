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
    BLOQUEADO: "agendado, mas não dá para dar como certo",
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
        if self.situacao == BLOQUEADO:
            por = str((self.html or {}).get("bloqueio") or "").strip() or (
                "situação no banco: "
                + str((self.banco or {}).get("situacao") or "?"))
            return f"{FRASES[BLOQUEADO]}: {por}"
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
        """Conta que devia ter sido conferida e não foi: a leitura falhou, ou
        o cadastro não diz em que conta do Sicoob ela está. Só a conta de
        OUTRO banco fica de fora por desenho. A diferença é de cor — esta é
        vermelha, porque as pendências dela seriam assinadas sem conferência
        (revisão de dinheiro, 15/10/2026: a subconta nova que ainda não está
        no `contas_sicoob.json` ficava neutra, igual à do Inter)."""
        return not self.conferida and self.motivo != MOTIVO_FORA_SICOOB

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


GENERICAS = frozenset("""
    REEMBOLSO ENG LTDA EIRELI SPE COM DOS DAS DE DA DO ME EPP MEI SA CIA
    MATERIAIS MATERIAL CONSTRUCAO CONSTRUCOES CONSTRUTORA COMERCIO
    COMERCIAL SERVICOS SERVICO ENGENHARIA DISTRIBUIDORA DISTRIBUICAO
    FERRAGENS ATACADISTA ATACADO VAREJO INDUSTRIA INDUSTRIAL
    EMPREENDIMENTOS IMOBILIARIA IMOBILIARIOS GESTAO PARTICIPACOES LOJA
    CASA CENTRO GRUPO BRASIL GOIANIA GOIAS TRANSPORTES MADEIREIRA
    ELETRICA HIDRAULICA PISOS TINTAS VIDRACARIA CONTABILIDADE NOVA NOVO
    ADVOCACIA CONSULTORIA ASSESSORIA SOLUCOES TECNOLOGIA ELETRICOS
    SILVA SANTOS OLIVEIRA SOUZA SOUSA PEREIRA COSTA RODRIGUES ALMEIDA
    LIMA FERREIRA ALVES GOMES RIBEIRO CARVALHO MARTINS ROCHA DIAS
    MORAIS MORAES BARBOSA ARAUJO NASCIMENTO MENDES CARDOSO TEIXEIRA
    JUNIOR FILHO NETO SOBRINHO
    JOAO JOSE MARIA ANA ANTONIO CARLOS PAULO PEDRO LUCAS LUIZ LUIS MARCOS
    FRANCISCO MANOEL MANUEL RAIMUNDO SEBASTIAO GABRIEL RAFAEL DANIEL
    MARCELO BRUNO EDUARDO FELIPE RODRIGO MATEUS GUSTAVO FERNANDO RICARDO
    JORGE ROBERTO SERGIO ANDRE DIEGO THIAGO TIAGO VITOR VICTOR LEONARDO
    JULIANA FERNANDA PATRICIA ALINE CAMILA AMANDA BRUNA LETICIA MARIANA
    ADRIANA FRANCISCA ANTONIA SANDRA LUCIANA VANESSA JESSICA GABRIELA
    SAO SANTA SANTO BOM BOA JESUS IRMAOS NOSSA SENHORA REAL PRIMAVERA
    ALIANCA MINAS CENTRAL UNIAO ESTRELA FORTE GERAL NACIONAL
""".split())
"""O que não prova que dois nomes são a mesma pessoa ou empresa: o que o
HTML escreve em volta do nome, a forma jurídica, o ramo de negócio, os
sobrenomes e os prenomes mais comuns. Duas rodadas da revisão de dinheiro
(15/10/2026): "ALFA MATERIAIS" × "BETA MATERIAIS" e "MARIA PEREIRA" ×
"MARIA MENDES" saíam verdes por uma palavra que metade do país divide."""


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
    """A força da prova de que o recebedor do banco é o do HTML; 0 = nenhuma.

    Três jeitos de provar, e nada além deles (as duas rodadas da revisão
    de dinheiro mostraram que cada folga a mais vira um verde falso):

    - **os dois nomes iguais**, fora a forma jurídica — "VIDRACARIA ALMEIDA"
      e "VIDRACARIA ALMEIDA LTDA", mesmo feitos só de palavras genéricas.
      Igual, e não "contido": "CASA DAS TINTAS" não é "NOVA CASA DAS TINTAS",
      nem "FULANO SILVA" é "FULANO SILVA PEREIRA";
    - **duas palavras próprias** (fora de `GENERICAS`) em comum;
    - **uma palavra própria**, quando é a ÚNICA do nome do HTML E o nome é de
      gente: o cadastro de reembolso ("Reembolso Eng <prenome raro>") ou o
      recebedor que o banco escreve como MEI (`_e_mei`). Nome de empresa com
      uma palavra própria só ("SAO JORGE MATERIAIS") não prova nada por ela —
      "SAO BENTO TINTAS" dividiria a mesma.

    "Iguais" compara TODOS os pedaços (`_pedacos`), siglas e números
    incluídos: só com as palavras de 3+ letras, "JL MATERIAIS" era igual a
    "JR MATERIAIS" (terceira rodada da revisão, 15/10/2026).
    """
    nome_html = nome_de_quem_recebe(entrada.get("favorecido"))
    do_html = _palavras(nome_html)
    do_banco = _palavras(pendencia.get("detalhe"))
    if not do_html or not do_banco:
        return 0
    detalhe = str(pendencia.get("detalhe") or "").strip()
    if _nomes_iguais(_pedacos(nome_html), _pedacos(detalhe),
                     cortado=len(detalhe) >= CORTE_DO_NOME):
        return 3
    proprias_html = do_html - GENERICAS
    comuns = proprias_html & (do_banco - GENERICAS)
    if len(comuns) >= 2:
        return 2
    reembolso = bool(re.search(r"\(\s*reembolso de",
                               str(entrada.get("favorecido") or ""), re.I))
    de_gente = (reembolso or "REEMBOLSO" in do_html
                or _e_mei(pendencia.get("detalhe")))
    if len(comuns) == 1 and len(proprias_html) == 1 and de_gente:
        return 1
    return 0


def _pedacos(texto) -> list[str]:
    """Todos os pedaços do nome, siglas e números incluídos, fora a forma
    jurídica e o número de CNPJ que o banco põe na frente do MEI."""
    limpo = util.sem_acento(str(texto or "")).upper()
    limpo = re.sub(r"^\s*\d{2}[\s.]?\d{3}[\s.]?\d{3}\b", "", limpo)
    return [p for p in re.findall(r"[A-Z0-9]+", limpo) if p not in _FORMA]


#: Onde o Sicoob corta o nome do recebedor: 40 caracteres, medido em
#: 15/10/2026 ("… GESTAO IMOBILIARI"). Nome mais curto não foi cortado.
CORTE_DO_NOME = 40


def _nomes_iguais(html: list[str], banco: list[str], cortado: bool) -> bool:
    """Os mesmos pedaços, na mesma ordem — e, quando o nome do banco chegou
    ao tamanho em que o Sicoob corta (`cortado`), o último pedaço dele pode
    ser só o começo do último do HTML, com 3+ letras. Sem o corte de
    verdade, "JOSE MARIA" não é "JOSE MARIANO" (revisão, 15/10/2026)."""
    if not html or len(html) != len(banco):
        return False
    if html[:-1] != banco[:-1]:
        return False
    fim_h, fim_b = html[-1], banco[-1]
    return fim_h == fim_b or (cortado and len(fim_b) >= 3
                              and fim_h.startswith(fim_b))


def _e_mei(detalhe) -> bool:
    """O banco escreve o MEI com a raiz do CNPJ na frente
    ("11 222 333 FULANO …"): ali o nome é de UMA pessoa."""
    return bool(re.match(r"\s*\d{2}[\s.]?\d{3}[\s.]?\d{3}\b",
                         str(detalhe or "")))


def mesmo_recebedor(entrada: dict, pendencia: dict) -> bool:
    return pontos_do_nome(entrada, pendencia) > 0


def _descricao(texto) -> str:
    """Descrição comparável: o Sicoob põe "Observação: " na frente do boleto."""
    s = re.sub(r"^\s*observa[cç][aã]o\s*:\s*", "", str(texto or ""), flags=re.I)
    return util.norm_espaco(s)


#: O pedaço que o banco guardou tem de ter ao menos isto, e ao menos
#: `FRACAO_DO_PREFIXO` da descrição do HTML (ver `mesma_descricao`).
MINIMO_DO_PREFIXO = 20
FRACAO_DO_PREFIXO = 0.6


def mesma_descricao(entrada: dict, pendencia: dict) -> bool:
    """A descrição do HTML é a observação (ou o detalhe) da pendência?

    Em boleto e convênio o Sicoob NÃO devolve quem recebe: o `detalhe` é
    "Observação: <o que se digitou>" (medido em 15/10/2026, em todas as
    contas). Ali a prova de que é o mesmo pagamento é a descrição colada do
    HTML — mais forte que o nome, porque leva centro de custo, NF e OC.

    **O banco corta a observação** (a de 15/10/2026 parou no meio de uma
    palavra). Por isso vale também o texto do BANCO ser o começo do texto do
    HTML — nunca o contrário: o HTML do lote 10 ("… LT 10") é o começo do
    agendamento dos lotes 10 e 11 ("… LT 10 E 11"), e são outro pagamento.
    E o pedaço guardado tem de ser substancial: `MINIMO_DO_PREFIXO`
    caracteres, `FRACAO_DO_PREFIXO` do texto do HTML (uma observação curta,
    só o centro de custo, casaria com toda linha daquela obra), e sem cortar
    um número ao meio ("OC 300" × "OC 3001")."""
    d = _descricao(entrada.get("descricao"))
    if not d:
        return False
    for b in (_descricao(pendencia.get("observacao")),
              _descricao(pendencia.get("detalhe"))):
        if not b:
            continue
        if d == b:
            return True
        if (d.startswith(b) and len(b) >= MINIMO_DO_PREFIXO
                and len(b) >= FRACAO_DO_PREFIXO * len(d)
                and not (b[-1].isdigit() and d[len(b)].isdigit())):
            return True
    return False


def ja_pago(entrada: dict | None) -> bool:
    """A linha do HTML é de título JÁ PAGO (`relatorio`: "JÁ PAGO em …")."""
    return (util.sem_acento(str((entrada or {}).get("status") or "")).upper()
            .lstrip().startswith("JA PAGO"))


#: A única situação que a lista de pendências trouxe em 15/10/2026, em todas
#: as contas. Outra (a consulta pede "Todas") nunca sai verde.
PENDENTE_ASSINATURA = "PENDENTE_ASSINATURA"


def pendente_de_verdade(pendencia: dict) -> bool:
    s = str(pendencia.get("situacao") or "").strip().upper()
    return s in ("", PENDENTE_ASSINATURA)


def sem_recebedor(pendencia: dict) -> bool:
    """O banco não diz quem recebe? É o boleto e o convênio: o `detalhe` vem
    "Observação: …" (ou vazio). No Pix ele é o nome do recebedor."""
    d = str(pendencia.get("detalhe") or "").strip()
    if not d:
        # Vazio não é "boleto": é campo que não veio (ou que o banco
        # renomeou). Contar como sem recebedor deixaria um Pix verde só pela
        # descrição colada — o verde falso que a revisão fechou.
        return False
    if re.match(r"observa[cç][aã]o\s*:", d, flags=re.I):
        return True
    # Convênio (guia, certidão) devolve a observação crua no `detalhe`, sem o
    # rótulo — igual à `observacao`, não é nome de ninguém (15/10/2026).
    return _descricao(d) == _descricao(pendencia.get("observacao"))


def _pontos(entrada: dict, pendencia: dict) -> int:
    """A força da prova de que é o mesmo pagamento.

    Sem recebedor (boleto), a descrição colada é a prova e vale mais que
    tudo. COM recebedor (Pix), a descrição sozinha não prova nada: é o texto
    que o HTML manda colar, e colá-lo certo com a chave de OUTRA pessoa daria
    verde para o Pix errado (revisão de dinheiro, 15/10/2026) — ali manda o
    nome, e a descrição só reforça."""
    nome = pontos_do_nome(entrada, pendencia)
    if sem_recebedor(pendencia):
        return 10 if mesma_descricao(entrada, pendencia) else nome
    if not nome:
        return 0
    return nome + (10 if mesma_descricao(entrada, pendencia) else 0)


def confrontar(entradas, pendencias) -> list[Linha]:
    """Casa as linhas do HTML de UMA conta com as pendências dela no banco.

    Três passadas, da prova mais forte para a mais fraca, e cada pendência
    é usada uma vez só: (1) mesmo valor e prova de que é o mesmo pagamento —
    os pares são escolhidos do MAIS provado para o menos, na conta inteira,
    e não na ordem do HTML (senão a primeira linha pegava o agendamento que
    era de outra); (2) mesmo valor; (3) mesma descrição com valor
    diferente. O que sobra de cada lado é "falta no banco" ou "só no banco".

    Exceções que vêm da própria linha (revisão de dinheiro, 15/10/2026):
    a linha JÁ PAGO só disputa agendamento DEPOIS dos pares provados das que
    estão por pagar (e ANTES das passadas sem prova), e só com prova de nome
    ou descrição — casada, é pagamento em DOBRO; sem
    par, não é falta nenhuma. A linha com `bloqueio` e a pendência que não
    está "pendente de assinatura" nunca saem verdes."""
    vivas = [e for e in (entradas or []) if not ja_pago(e)]
    pagas = [e for e in (entradas or []) if ja_pago(e)]
    sobra_banco = list(pendencias or [])
    casadas: list[Linha] = []

    def situacao(e, p, base):
        if ja_pago(e):
            return PAGO_E_AGENDADO
        if base == OK and (str(e.get("bloqueio") or "").strip()
                           or not pendente_de_verdade(p)):
            return BLOQUEADO
        return base

    def mesmo_valor(e, p):
        return int(e.get("centavos") or 0) == centavos_do_banco(p)

    def provadas(sobra_html):
        """Passada (1): todos os pares provados, do mais forte ao mais fraco."""
        pares = sorted(((_pontos(e, p), -i, -j, e, p)
                        for i, e in enumerate(sobra_html)
                        for j, p in enumerate(sobra_banco)
                        if mesmo_valor(e, p) and _pontos(e, p) > 0),
                       key=lambda x: x[:3], reverse=True)
        usados_e, usados_p = set(), set()
        for _pts, _i, _j, e, p in pares:
            if id(e) in usados_e or id(p) in usados_p:
                continue
            usados_e.add(id(e))
            usados_p.add(id(p))
            casadas.append(Linha(situacao(e, p, OK), e, p))
        sobra_banco[:] = [p for p in sobra_banco if id(p) not in usados_p]
        return [e for e in sobra_html if id(e) not in usados_e]

    def passada(sobra_html, combina, base):
        resto = []
        for e in sobra_html:
            par = next((p for p in sobra_banco if combina(e, p)), None)
            if par is None:
                resto.append(e)
                continue
            sobra_banco.remove(par)
            casadas.append(Linha(situacao(e, par, base), e, par))
        return resto

    # As JÁ PAGO procuram par logo depois das vivas PROVADAS e antes das
    # passadas sem prova: senão o agendamento repetido de um título pago era
    # levado só pelo valor por uma linha viva, e o pagamento em dobro saía
    # âmbar em vez de vermelho (revisão de dinheiro, 15/10/2026).
    vivas = provadas(vivas)
    pagas = provadas(pagas)
    vivas = passada(vivas, mesmo_valor, NOME_DIFERENTE)
    vivas = passada(vivas, mesma_descricao, VALOR_DIVERGE)

    linhas = (casadas
              + [Linha(FALTA_NO_BANCO, e, None) for e in vivas]
              + [Linha(JA_PAGO, e, None) for e in pagas]
              + [Linha(SO_NO_BANCO, None, p) for p in sobra_banco])
    ordem = {s: i for i, s in enumerate(GRAVIDADE)}
    posicao = {id(e): i for i, e in enumerate(entradas or [])}
    # Dentro da mesma situação, a ordem do HTML (que é a do dono).
    return sorted(linhas, key=lambda li: (
        ordem[li.situacao],
        posicao.get(id(li.html), len(posicao))))
