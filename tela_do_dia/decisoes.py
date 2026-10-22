# -*- coding: utf-8 -*-
"""As decisões que a tela do dia toma e que não precisam de janela.

O `frame.py` só mostra e pergunta. O que decide — se dá para gerar, o que
aparece como "—", que movimento à mão é válido, quais operações seguram — mora
aqui, com teste sem Tk (a máquina do dono não roda teste de tela sem
liberação).
"""
from __future__ import annotations

from decimal import Decimal

from .valores import brl, ler_valor_editado

ZERO = Decimal("0.00")
TRACO = "—"
#: A opção de origem do movimento à mão que entra de FORA do painel (o sócio
#: ou o investidor que aporta na mãe). Vira `origem=None`.
DE_FORA = "de fora (sócio ou investidor)"


# ------------------------------------------------------------- passo 3
def celulas_do_aporte(conta) -> tuple[str, str, str, str]:
    """(mínimo, definido, falta ratear, saldo final) de uma `AporteDaConta`.

    Conta sem saldo do sistema mostra "—" nos três números que dependem do
    saldo: o `AporteDaConta` devolve zero ali para não quebrar a soma, e zero
    na tela seria ler "não precisa de aporte" onde a verdade é "não sei"."""
    if conta.sem_saldo:
        return TRACO, brl(conta.definido), TRACO, TRACO
    return (brl(conta.minimo), brl(conta.definido), brl(conta.falta_ratear),
            brl(conta.saldo_final))


def novo_movimento(origem: str, destino: str, valor_texto, rotulos):
    """(origem ou None, destino, Decimal) de um movimento «À MÃO» digitado.

    Levanta ValueError com o motivo. Destino e origem têm de ser contas do
    painel (o Excel só tem linha para elas); "de fora" vira origem None."""
    rotulos = set(rotulos)
    origem = (origem or "").strip()
    destino = (destino or "").strip()
    if not origem:
        # Vazio NÃO é "de fora": numa transferência, é a origem esquecida — e
        # tratá-la como de fora somaria dinheiro que não saiu de conta nenhuma.
        raise ValueError("escolha a origem do movimento")
    de = None if origem == DE_FORA else origem
    if destino not in rotulos:
        raise ValueError(f"o destino {destino!r} não é conta do painel")
    if de is not None and de not in rotulos:
        raise ValueError(f"a origem {de!r} não é conta do painel")
    if de == destino:
        raise ValueError("origem e destino são a mesma conta")
    valor = ler_valor_editado(valor_texto)
    if valor <= ZERO:
        raise ValueError("o valor tem de ser maior que zero")
    return de, destino, valor


def movimentos_validos(a_mao, rotulos) -> list:
    """Os que o Excel recebe: destino conta do painel e valor > 0 — os mesmos
    que a tela soma (`aportes.montar_aportes` ignora os outros, com alerta). O
    Excel recusaria o resto, e a tela e o Excel têm de contar a mesma coisa."""
    rotulos = set(rotulos)
    return [(o, d, v) for o, d, v in (a_mao or ())
            if d in rotulos and v is not None and v > ZERO]


def descrever_movimento(mov) -> str:
    origem, destino, valor = mov
    return f"{origem or 'de fora'} → {destino}: {brl(valor)}"


# ------------------------------------------------------------- passo 4
def motivo_sem_excel(leitura, saldos, exigir_todos_os_saldos: bool) -> str:
    """Vazio = pode gerar. Leitura interrompida nunca vira Excel ("a pagar 0")
    e saldo ausente, com a config exigindo, é aporte calculado sobre zero —
    a mesma trava do `conciliacao/validate.py`."""
    if leitura is None:
        return "Busque os pagamentos e os saldos primeiro."
    if leitura.interrompida:
        return "A leitura foi interrompida — busque de novo."
    if exigir_todos_os_saldos:
        faltam = [ln.rotulo for ln in saldos if ln.saldo_do_dia is None]
        if faltam:
            return ("O sistema não trouxe o saldo de: " + ", ".join(faltam)
                    + ". O Excel calcularia o aporte sobre saldo zero — digite o "
                    "saldo do banco dessas contas ou busque de novo.")
    return ""


def motivo_sem_geradores(leitura) -> str:
    """Planilha por conta, HTML e Remessa precisam da apuração inteira."""
    if leitura is None:
        return "Busque os pagamentos e os saldos primeiro."
    if leitura.interrompida:
        return "A leitura foi interrompida — busque de novo."
    if leitura.entradas is None:
        return "Nenhum pagamento a apurar no período."
    return ""


def contas_sem_saldo(saldos) -> set[str]:
    return {ln.rotulo for ln in saldos if ln.saldo_do_dia is None}


# ------------------------------------------------- envio à aba Aportes
def separar_envio(envio, mandar_sem_saldo: bool):
    """(mandadas, seguradas): as operações de `envio.itens` que vão e as que a
    tela segura (conta sem saldo, quando o dono disse não). Por IDENTIDADE do
    objeto, como `para_aportes.marcar_enviados` — duas operações iguais em
    valor continuam sendo duas."""
    segurar = set() if mandar_sem_saldo else {id(op) for op in envio.sem_saldo}
    mandadas, seguradas = [], []
    for op, _chaves in envio.itens:
        (seguradas if id(op) in segurar else mandadas).append(op)
    return mandadas, seguradas


def linhas_do_envio(envio) -> tuple[list[str], list[str]]:
    """(pendências, avisos) em texto. Pendência NÃO foi; aviso foi, confira."""
    def linha(p):
        return f"{p.aportador} → {p.destino} ({brl(p.valor)}): {p.motivo}"
    return [linha(p) for p in envio.pendentes], [linha(p) for p in envio.avisos]


# ------------------------------------------------------------- passo 2
def celulas_da_conta(conta) -> tuple[str, str, str, str]:
    """(vão sair, a pagar, bloqueados, situação) de uma `PagamentosDaConta`,
    nas colunas do desenho aprovado: quantos saem da conta e quanto, quantos
    estão bloqueados (e quanto somam, que NÃO entra no a pagar). O já enviado
    em remessa soma no a pagar (o banco ainda vai debitá-lo) e aparece na
    situação, separado dos bloqueados: não se gera de novo, mas sai. Da
    conferência (entrega 2) a situação cita "N liberado(s)", "N à mão" e
    "N desmarcado(s) (fora)" — o desmarcado não soma em nada."""
    bloqueados = (f"{len(conta.bloqueados)} · {brl(conta.valor_bloqueado)}"
                  if conta.bloqueados else "0")
    partes = [conta.motivo_fora] if conta.motivo_fora else []
    if conta.ja_enviados:
        partes.append(f"{len(conta.ja_enviados)} já enviado · "
                      f"{brl(conta.valor_ja_enviado)} (soma no a pagar)")
    # `getattr`: objetos da entrega 1 não têm os campos da conferência.
    liberados = len(getattr(conta, "liberados", ()))
    a_mao = len(getattr(conta, "a_mao", ()))
    desmarcados = len(getattr(conta, "desmarcados", ()))
    if liberados:
        partes.append(f"{liberados} liberado" + ("s" if liberados > 1 else ""))
    if a_mao:
        partes.append(f"{a_mao} à mão")
    if desmarcados:
        partes.append(f"{desmarcados} desmarcado" + ("s" if desmarcados > 1 else "") + " (fora)")
    return str(conta.qtd_a_pagar), brl(conta.a_pagar), bloqueados, " · ".join(partes)


# ------------------------------------------------- erro com o motivo
def detalhe_do_erro(erro) -> str:
    """A linha do Registro que diz o QUE caiu: "detalhe: <Tipo>: <mensagem>".

    O recado amigável (`widgets.recado_de_erro`) ficou genérico demais para
    o "Não consegui ler o dia." de 21 e 22/10/2026 (ErpErro/ErpError sem
    detalhe). Uma linha só, com teto: o traceback inteiro vai para o
    diagnostico.log."""
    texto = " ".join(str(erro or "").split())[:300] or "(sem mensagem)"
    return f"detalhe: {type(erro).__name__}: {texto}"


# ------------------------------------------------- período lido
def periodo_na_tela(periodo) -> str:
    """O texto do período lido. Decisão do dono (21/10/2026): esta aba não
    tem campo de data — o período é o de `sugerir_periodo(hoje)`, e a tela
    mostra o que leu. Não há aviso nenhum: sem calendário de feriados não há
    como saber quando avisar ("o dia útil anterior ficou fora" vale em todo
    dia útil, e aviso que aparece sempre é ruído). No dia seguinte a um
    feriado, os vencidos do feriado se buscam pela aba Remessa/Retorno."""
    return f"Pagamentos de {periodo.inicio:%d/%m} a {periodo.fim:%d/%m}"


# ------------------------------------------------- arquivo e data do dia
def pergunta_sobrescrever(destino) -> str:
    """Vazio = o Excel do dia ainda não existe. O nome é o mesmo do painel da
    aba "Saldo de pagamentos" (as duas convivem): sobrescrever sem perguntar
    apagaria o que a outra gerou."""
    if not destino.exists():
        return ""
    return (f"Já existe {destino.name} (pode ter sido gerado pela aba Saldo de "
            "pagamentos ou por esta mesma aba).\n\nSubstituir pelo desta tela?")


def data_das_operacoes(periodo):
    """A data dos aportes mandados para a aba Aportes: a do dia de trabalho
    (`periodo.fim`, que é também o arquivo onde o envio fica anotado), e não a
    do relógio — tela aberta depois da meia-noite mandaria com a data de
    amanhã e anotaria no arquivo de ontem."""
    return periodo.fim
