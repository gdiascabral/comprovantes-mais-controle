# -*- coding: utf-8 -*-
"""A visão do DIA das remessas, e as duas ações que faltavam. Sem tela.

Com uma conta, a pergunta do dia é "quem foi pago", e quem a responde é a
janela do retorno, pagamento a pagamento. Com dezoito, a pergunta muda: é
**qual conta ainda não fechou**. As respostas possíveis são seis, e elas não
estão em coluna nenhuma — saem do cruzamento do estado da remessa com o que o
retorno gravou em cada item:

    gerada → subida no SicoobNet → retorno lido → aguardando assinatura →
    paga | rejeitada

Nada aqui abre janela, fala com o banco ou lê arquivo: recebe a lista que
`nuvem.registro.Registro.remessas_do_dia` devolve (o dicionário do PostgREST,
com os itens dentro) e entrega linhas prontas. É por isso que as regras de
transição — as duas que decidem o que dá para fazer com uma remessa — moram
aqui e não no frame: elas mexem em dinheiro, e o que só se testa abrindo
janela não se testa.

**Por que "descartado" precisava de tela.** `Registro.marcar` existe desde
17/08/2026 e ninguém no app o chamava: toda remessa nascia `gerado` e só saía
disso quando alguém lia o retorno. Duas consequências, e a segunda é a que
custa dinheiro:

- **a remessa que nunca subiu ao SicoobNet ficava indistinguível da que
  subiu.** "Gerada" e "enviada" são o mesmo estado no banco, e a diferença é
  justamente o que a pessoa precisa saber às cinco da tarde;
- **o pagamento de uma remessa que NUNCA foi ao banco ficava bloqueado para
  sempre.** `remessa_dia._ja_enviado` pergunta "este boleto já saiu?" olhando
  os itens de remessa VIVA (`ESTADOS_VIVOS`), e só `descartado` sai dessa
  lista. Arquivo gerado por engano, arquivo que o banco recusou na subida,
  arquivo substituído por outro — todos continuavam segurando os seus
  pagamentos, e a única saída era mexer no banco pelo painel do Supabase.

E é por isso que **descartar tem duas travas**, escritas em
`pode_descartar`: nunca uma remessa com item PAGO (descartar devolveria o
direito de reenviar dinheiro que já saiu, que é a definição de pagamento em
dobro), e nunca sem motivo por escrito — o mesmo princípio do `ajustar_nsa`,
que exige motivo porque é ele que explica o furo para quem olhar depois.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

#: O tamanho mínimo do motivo de um descarte. Cinco caracteres não conferem
#: nada sobre o CONTEÚDO — "erro" tem quatro e "teste" tem cinco. O que eles
#: barram é o campo em branco e o ponto solto de quem só quer o diálogo fora
#: da frente, que é o modo real de o motivo virar nada.
MOTIVO_MINIMO = 5

#: O que `retorno_estado` guarda em cada item (PR #52), e o que cada um vira
#: aqui. `"?"` é "o banco não citou este pagamento" e `""` é "nenhum retorno
#: foi lido ainda": os dois contam como SEM RESPOSTA, porque a pergunta que
#: esta tela responde é a mesma nos dois casos — falta saber.
_CONTADORES = {"ok": "pagos", "pendente": "aguardando", "rejeitado": "rejeitados"}


@dataclass
class LinhaDoDia:
    """Uma remessa do dia, com o que o retorno já disse dos itens dela."""

    convenio: str
    nsa: int
    empresa: str
    agencia: str
    conta: str
    estado: str
    #: Já convertido para a hora LOCAL — `gerado_em` é `timestamptz`, e o
    #: banco o devolve em UTC. Quem lê a tela quer saber a que horas o arquivo
    #: saiu do computador dela, e não que horas eram em Greenwich.
    gerado_em: "_dt.datetime | None"
    arquivo: str
    pagos: int
    aguardando: int
    rejeitados: int
    sem_resposta: int
    total: Decimal
    #: O retorno mais RECENTE entre os itens. A mesma remessa é lida duas
    #: vezes (a primeira volta `PD`, pendente de assinatura; a segunda, depois
    #: de o master liberar, volta `00`), e o que interessa é a última.
    retorno_lido_em: "_dt.datetime | None"

    @property
    def itens(self) -> int:
        return self.pagos + self.aguardando + self.rejeitados + self.sem_resposta

    @property
    def respondidos(self) -> int:
        """Quantos o banco citou. Zero é "ninguém leu o retorno ainda"."""
        return self.pagos + self.aguardando + self.rejeitados


def _instante(cru) -> "_dt.datetime | None":
    """O `timestamptz` do PostgREST na hora local. `None` quando não dá.

    Data ilegível não derruba a linha: a remessa continua tendo estado,
    contagem e total, que é o que a tela existe para mostrar."""
    texto = str(cru or "").strip()
    if not texto:
        return None
    try:
        quando = _dt.datetime.fromisoformat(texto)
    except ValueError:
        return None
    # Sem fuso é resposta de banco mal configurado, não hora local: deixa
    # como está em vez de inventar um offset.
    return quando.astimezone() if quando.tzinfo else quando


def _valor(cru) -> Decimal:
    """O `numeric(15,2)` como Decimal. Nunca float.

    O PostgREST devolve `numeric` como STRING justamente para o valor não
    passar por binário de base 2 — somar centavos em float é como um total de
    tela deixa de bater com o do arquivo."""
    try:
        return Decimal(str(cru if cru is not None else "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def linhas_do_dia(remessas: list[dict]) -> list[LinhaDoDia]:
    """As remessas do dia viradas em linhas, com os itens já contados.

    Recebe a forma que `Registro.remessas_do_dia` (e `Registro.remessas`)
    devolve: o dicionário da tabela `remessa` com a lista `remessa_item`
    dentro. A ordem que chega é preservada — quem ordena é a consulta
    (`order=gerado_em.asc`), e reordenar aqui daria duas regras de ordenação
    para a mesma lista.
    """
    linhas = []
    for bruto in remessas or ():
        contagem = {"pagos": 0, "aguardando": 0, "rejeitados": 0}
        sem_resposta = 0
        total = Decimal("0")
        ultimo_retorno = None
        for item in bruto.get("remessa_item") or ():
            campo = _CONTADORES.get(str(item.get("retorno_estado") or "").strip())
            if campo:
                contagem[campo] += 1
            else:
                sem_resposta += 1
            total += _valor(item.get("valor"))
            quando = _instante(item.get("retorno_em"))
            if quando and (ultimo_retorno is None or quando > ultimo_retorno):
                ultimo_retorno = quando
        linhas.append(LinhaDoDia(
            convenio=str(bruto.get("convenio") or ""),
            nsa=int(bruto.get("nsa") or 0),
            empresa=str(bruto.get("empresa") or ""),
            agencia=str(bruto.get("agencia") or ""),
            conta=str(bruto.get("conta") or ""),
            estado=str(bruto.get("estado") or ""),
            gerado_em=_instante(bruto.get("gerado_em")),
            arquivo=str(bruto.get("arquivo") or ""),
            pagos=contagem["pagos"],
            aguardando=contagem["aguardando"],
            rejeitados=contagem["rejeitados"],
            sem_resposta=sem_resposta,
            total=total,
            retorno_lido_em=ultimo_retorno))
    return linhas


def situacao(linha: LinhaDoDia) -> tuple[str, str]:
    """(tag da cor, frase) de uma remessa — em que ponto do dia ela está.

    A ORDEM das perguntas é a regra, e não a ordem de leitura:

    - **descartado vem antes de tudo**, inclusive de contagem: a remessa saiu
      da conta, e o que os itens dela dizem já não pesa em decisão nenhuma;
    - **rejeitado vem antes de pendente**, como em
      `pagamentos_frame._situacao_do_retorno`: um item recusado é o que faz
      alguém abrir o detalhe hoje, e escondê-lo atrás de "aguardando
      assinatura" adiaria isso até alguém estranhar a falta do dinheiro;
    - **"falta ler o retorno" vem depois das contagens**, porque uma remessa
      pode estar `enviado` e já ter resposta de parte dos itens.

    A tag é uma das quatro do `widgets` (`ok`/`atencao`/`erro`/`info`) e quem
    a pinta é o `estilo_tabela` — aqui não há cor nenhuma escrita.
    """
    if linha.estado == "descartado":
        return "info", "descartada"
    if linha.estado == "gerado":
        return "atencao", "gerada — falta subir no SicoobNet"
    if linha.rejeitados:
        return "erro", f"{linha.rejeitados} rejeitado(s)"
    if linha.aguardando:
        return "atencao", "aguardando assinatura"
    if not linha.respondidos:
        return "atencao", "enviada — falta ler o retorno"
    if linha.pagos and not linha.sem_resposta:
        return "ok", "paga"
    return "info", "sem resposta do banco por todos"


# ------------------------------------------------------- o que dá para fazer

def pode_marcar_enviada(linha: LinhaDoDia) -> bool:
    """Só de `gerado`, e o "só" é o valor da marcação.

    A marca existe para separar "o arquivo está na pasta" de "o arquivo está
    no SicoobNet" — o passo que o app não vê acontecer, porque quem o dá é
    uma pessoa arrastando o `.REM` no navegador. De qualquer outro estado ela
    não acrescenta nada e pode TIRAR: marcar `enviado` uma remessa já
    `processado` apagaria o desfecho que o retorno gravou, e a conta voltaria
    para a lista do que falta acompanhar com o dinheiro já pago.
    """
    return linha.estado == "gerado"


def pode_descartar(linha: LinhaDoDia,
                   motivo: "str | None" = None) -> tuple[bool, str]:
    """Dá para descartar esta remessa? (pode, frase da recusa).

    `motivo=None` pergunta só pelas travas de ESTADO — é o que o botão usa
    para saber se habilita. Passando o texto, o motivo entra na conferência:
    é a chamada de quem vai descartar de verdade.

    **Nunca com item pago.** Descartar tira a remessa de `ESTADOS_VIVOS`, e
    `remessa_dia._ja_enviado` só enxerga item de remessa viva: os pagamentos
    dela voltam TODOS a ser marcáveis na geração seguinte, com NSA novo e
    nenhum alarme. Numa remessa em que o banco já pagou alguém, isso é
    autorizar o mesmo dinheiro a sair duas vezes — e o dinheiro que já saiu
    não volta porque a tela mudou de ideia. Um item pago no meio de vinte
    rejeitados basta para a resposta ser não: o certo ali é reenviar o que
    faltou numa remessa nova, não ressuscitar esta.

    **Nunca sem motivo por escrito.** É a regra do `ajustar_nsa`, pelo mesmo
    motivo: o histórico é append-only e descreve arquivos que existiram: uma
    remessa `descartado` sem uma linha dizendo por quê é um furo na sequência
    de NSA que ninguém explica meses depois.
    """
    if linha.estado == "descartado":
        return False, "Esta remessa já está descartada."
    if linha.pagos:
        return False, (
            f"Esta remessa tem {linha.pagos} pagamento(s) que o banco já "
            f"PAGOU. Descartá-la devolveria a esses pagamentos o direito de "
            f"sair de novo numa remessa nova — o mesmo dinheiro duas vezes. "
            f"O que faltou pagar entra numa remessa nova.")
    if motivo is not None and len(str(motivo).strip()) < MOTIVO_MINIMO:
        return False, (
            f"Escreva o motivo do descarte (ao menos {MOTIVO_MINIMO} "
            f"caracteres). Ele fica no registro, e é o que explica o furo na "
            f"sequência de arquivos para quem olhar depois.")
    return True, ""


def observacao_do_descarte(motivo: str) -> str:
    """O texto que vai para a coluna `observacao` — um só, para os dois lados.

    A nuvem e o espelho local recebem a MESMA frase: escrita duas vezes, o
    mesmo descarte apareceria com duas redações, e comparar os dois registros
    (que é para isso que o espelho existe) passaria a exigir traduzir um no
    outro. Cortado em 400 como o `registrar` já corta.
    """
    return f"descartada: {str(motivo).strip()}"[:400]
