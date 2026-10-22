# -*- coding: utf-8 -*-
"""As decisões que a tela do dia toma e que não precisam de janela.

O `frame.py` só mostra e pergunta. O que decide — se dá para gerar, o que
aparece como "—", que movimento à mão é válido, quais operações seguram — mora
aqui, com teste sem Tk (a máquina do dono não roda teste de tela sem
liberação).
"""
from __future__ import annotations

import re
from decimal import Decimal

import util

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


def nova_distribuicao(origem: str, socio: str, valor_texto, rotulos, socios=None):
    """(conta de origem, sócio, Decimal) de uma distribuição de lucros digitada
    (item A, 22/10/2026). Levanta ValueError com o motivo.

    A origem é conta do painel (é de lá que o dinheiro SAI: soma no E dela e
    no mínimo). O sócio não é conta do painel: é quem recebe, pelo NOME do
    cadastro da aba Aportes — `socios` é essa lista, quando a tela a tem; com
    ela, nome fora da lista é recusado (a aba Aportes não o acharia)."""
    origem = (origem or "").strip()
    socio = (socio or "").strip()
    if not origem:
        raise ValueError("escolha a conta de origem")
    if origem not in set(rotulos):
        raise ValueError(f"a origem {origem!r} não é conta do painel")
    if not socio:
        raise ValueError("escolha o sócio ou investidor que recebe")
    if socios is not None and socio not in set(socios):
        raise ValueError(f"{socio!r} não está no cadastro da aba Aportes — escolha da lista")
    if socio in set(rotulos):
        raise ValueError(f"{socio!r} é conta do painel: isso é transferência entre contas")
    valor = ler_valor_editado(valor_texto)
    if valor <= ZERO:
        raise ValueError("o valor tem de ser maior que zero")
    return origem, socio, valor


#: Palavras que fazem de um nome do cadastro uma EMPRESA (sem acento, maiúsculo).
_DE_EMPRESA = re.compile(
    r"\b(?:LTDA|S\s*/?\s*A|SPE|EIRELI|ME|EPP|HOLDING|PARTICIPACOES|EMPREENDIMENTOS|"
    r"ENGENHARIA|INCORPORACOES|INCORPORADORA|CONSTRUTORA|CONSTRUCOES|COMERCIO|SERVICOS|"
    r"CONDOMINIO|ASSOCIACAO|INSTITUTO|BANCO|EMPRESA|SUBCONTA)\b")


def _cara_de_empresa(nome: str, dado: dict) -> bool:
    texto = util.norm_espaco(f"{nome} {(dado or {}).get('nome_oficial') or ''}")
    return bool(_DE_EMPRESA.search(texto))


def socios_do_cadastro(entidades, rotulos, aportadores=()) -> list[str]:
    """Quem pode receber uma distribuição, para a lista da janela: PESSOAS do
    cadastro da aba Aportes (é por ele que o "Mandar" casa) — sem conta no ERP,
    ou aportador da aba Regras (`aportadores`, casado pelo nome completo) —,
    nunca nome com cara de empresa (LTDA, SPE, HOLDING, PARTICIPAÇÕES…: revisão
    geral de 22/10/2026, a lista oferecia o cadastro inteiro e dava para
    "distribuir lucro" para outra empresa), nem a subconta de investidor (ela
    só RECEBE aporte), nem as contas do painel (para elas é transferência)."""
    from aportes.dados import INVESTIDOR_PREFIXO
    rotulos = set(rotulos or ())
    entidades = entidades or {}
    dos_aportadores = {util.norm_espaco(a) for a in aportadores or () if a}
    saida = []
    for n, dado in entidades.items():
        if str(n).startswith(INVESTIDOR_PREFIXO) or n in rotulos:
            continue
        if _cara_de_empresa(n, dado):
            continue
        oficial = util.norm_espaco((dado or {}).get("nome_oficial") or "")
        if ((dado or {}).get("conta") is None or util.norm_espaco(n) in dos_aportadores
                or (oficial and oficial in dos_aportadores)):
            saida.append(n)
    return sorted(saida)


def distribuicoes_validas(distribuicoes, rotulos) -> list:
    """As que o Excel recebe: origem conta do painel e valor > 0 — as mesmas
    que a tela soma (`aportes.montar_aportes` ignora as outras, com alerta)."""
    rotulos = set(rotulos)
    return [(o, s, v) for o, s, v in (distribuicoes or ())
            if o in rotulos and v is not None and v > ZERO]


def descrever_distribuicao(dist) -> str:
    origem, socio, valor = dist
    return f"distribuição de lucros {origem} → {socio}: {brl(valor)}"


#: O tipo de cada movimento à mão, como o HTML e o Registro o escrevem.
TIPO_APORTE_NA_MAE = "Aporte que entra na mãe"
TIPO_TRANSFERENCIA = "Transferência entre contas"
TIPO_DISTRIBUICAO = "Distribuição de lucros"


def movimentos_do_dia(a_mao, distribuicoes) -> list[dict]:
    """Os movimentos à mão como linhas INFORMATIVAS do HTML dos pagamentos
    (dono, 22/10/2026: "só a informação pra não ficar nenhum pra trás"): de,
    para, tipo e valor; os aportes e transferências primeiro, na ordem em
    que foram incluídos, depois as distribuições. Valor zero ou negativo fica
    de fora, como na tela e no Excel."""
    linhas = []
    for origem, destino, valor in (a_mao or ()):
        if valor is None or valor <= ZERO:
            continue
        linhas.append({"de": origem or DE_FORA, "para": destino,
                       "tipo": TIPO_TRANSFERENCIA if origem else TIPO_APORTE_NA_MAE,
                       "valor": valor})
    for origem, socio, valor in (distribuicoes or ()):
        if valor is None or valor <= ZERO:
            continue
        linhas.append({"de": origem, "para": socio, "tipo": TIPO_DISTRIBUICAO,
                       "valor": valor})
    return linhas


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


def _linha_do_envio(p) -> str:
    return f"{p.aportador} → {p.destino} ({brl(p.valor)}): {p.motivo}"


def linhas_do_envio(envio) -> tuple[list[str], list[str]]:
    """(pendências, avisos) em texto. Pendência NÃO foi; aviso foi, confira."""
    return ([_linha_do_envio(p) for p in envio.pendentes],
            [_linha_do_envio(p) for p in envio.avisos])


def linhas_informativas(envio) -> list[str]:
    """O que não vai e está certo não ir (transferência entre contas da
    mesma empresa): o Registro informa, sem o "[!]" de erro."""
    return [_linha_do_envio(p) for p in getattr(envio, "informativos", ())]


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


# ------------------------------------------------- período (campo de datas)
FORMATO_DATA = "%d/%m/%Y"
MAXIMO_DE_DIAS = 31


def textos_sugeridos(hoje) -> tuple[str, str]:
    """O DE/ATÉ com que os campos nascem: a sugestão de `sugerir_periodo`
    (hoje e os dias não úteis logo antes; numa segunda, sáb..seg)."""
    from conciliacao.models import sugerir_periodo
    p = sugerir_periodo(hoje)
    return f"{p.inicio:{FORMATO_DATA}}", f"{p.fim:{FORMATO_DATA}}"


def _data(texto: str, campo: str):
    import datetime as _dt
    try:
        return _dt.datetime.strptime((texto or "").strip(), FORMATO_DATA).date()
    except ValueError:
        raise ValueError(f"Data inválida em {campo}: '{(texto or '').strip()}' — "
                         "use dd/mm/aaaa.") from None


def periodo_da_busca(txt_ini: str, txt_fim: str, sugerido, hoje):
    """O período que o Buscar lê (pedido do dono, 22/10/2026: "já senti falta
    de selecionar as datas aqui").

    - O que está nos campos vale; invertido, troca (como a Remessa/Retorno);
      data que não é dd/mm/aaaa levanta `ValueError` com o recado.
    - Os campos AINDA com a sugestão que o app pôs (`sugerido`), de outro
      dia — o app aberto de um dia para o outro —, viram a sugestão de HOJE:
      ninguém escolheu ontem, e ler ontem calado seria o pior erro aqui.

    O dia de trabalho é o ATÉ (`periodo.fim`): o JSON do dia, a nuvem do dia
    (liberações, agendados, lista do diretor), a data dos aportes e o Excel
    são desse dia. O Sicoob só é lido quando ele é hoje
    (`saldo_sicoob.recusa_pela_data`)."""
    from conciliacao.models import Periodo, sugerir_periodo
    atual = ((txt_ini or "").strip(), (txt_fim or "").strip())
    if sugerido is not None and atual == tuple(sugerido) and atual != textos_sugeridos(hoje):
        return sugerir_periodo(hoje)
    ini, fim = _data(atual[0], "DE"), _data(atual[1], "ATÉ")
    ini, fim = min(ini, fim), max(ini, fim)
    if fim > hoje:
        raise ValueError(f"Não dá para buscar o futuro: o ATÉ ({fim:%d/%m/%Y}) é depois "
                         f"de hoje ({hoje:%d/%m/%Y}).")
    dias = (fim - ini).days + 1
    if dias > MAXIMO_DE_DIAS:
        raise ValueError(f"O período tem {dias} dias; o máximo é {MAXIMO_DE_DIAS} dias. "
                         "Para mais, busque em partes.")
    return Periodo(ini, fim)


def pergunta_saldo_de_agora(periodo, lido_em, acao: str = "Gerar") -> str:
    """Vazio = o dia de trabalho é o dia em que os saldos foram lidos. Com o
    ATÉ no passado, os saldos (sistema E Sicoob) são os de AGORA, não os
    daquele dia: Excel do dia e "Mandar para Aportes" perguntam antes, com
    padrão "não" (revisão do pacote, 22/10/2026)."""
    if periodo.fim >= lido_em:
        return ""
    return f"O saldo é o de agora, não o de {periodo.fim:%d/%m}. {acao} mesmo assim?"


def periodo_na_tela(periodo, hoje=None) -> str:
    """O texto do período lido. Sem aviso de feriado: sem calendário não há
    como saber quando avisar ("o dia útil anterior ficou fora" vale em todo
    dia útil, e aviso que aparece sempre é ruído) — com o campo de datas
    (22/10/2026), o dono escolhe o período do dia seguinte a um feriado.

    Com `hoje` e o ATÉ em outro dia, diz qual é o dia de trabalho e que os
    saldos (sistema e Sicoob) são os de agora — e o Sicoob nem é lido."""
    texto = f"Pagamentos de {periodo.inicio:%d/%m} a {periodo.fim:%d/%m}"
    if hoje is not None and periodo.fim != hoje:
        texto += (f" · dia de trabalho {periodo.fim:%d/%m}: os saldos (sistema e Sicoob) "
                  f"são os de agora, não os de {periodo.fim:%d/%m}; o Sicoob não é lido — "
                  "confira antes do Excel e dos aportes")
    return texto


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
