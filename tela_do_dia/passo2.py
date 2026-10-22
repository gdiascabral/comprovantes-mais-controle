# -*- coding: utf-8 -*-
"""O passo 2 editável da tela do dia — as regras da TELA, sem janela.

`frame.py` só desenha, pergunta e manda gravar; o que ele decidiria com `if`
mora aqui, com teste puro (a máquina do dono não roda teste de tela):

- as linhas da tabela do passo 2 (`linhas_da_conta`): iid = a chave
  (id, parte_linha) — um lançamento dividido em partes (entrega 5) tem o mesmo
  id em N linhas, e a linha digitável da parte as separa; a chave não muda
  quando a linha troca de grupo ou de posição (desmarcar, reler), e nunca se
  repete (o Treeview recusa iid repetido);
- quais ações cada linha aceita (`acoes_da_linha`): o à mão só se REMOVE;
- a edição (`campos_da_edicao`, `validar_edicao_da_tela`): o reembolso muda
  junto com a forma de pagar (tipo + dado de quem recebe);
- o "tem certeza?" do liberar (`certeza_ao_liberar`), depois do motivo;
- gravar e RELER (`gravar_e_reler`): a tela nunca mostra o número de antes
  da gravação; releitura que falha trava a tela até buscar de novo.

Nada aqui fala com a rede por conta própria: `gravar_e_reler` recebe o
cliente e roda na thread de quem chama (a tela a roda fora da thread do Tk).
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass

from pagamentos_dia import html_pagamentos

from . import conferencia as cf
from .valores import brl

VAI, LIB, MAO, DESM, ENV, BLOQ = "vai", "lib", "mao", "desm", "env", "bloq"
#: Ações da tela (os botões sob a tabela).
A_LIBERAR, A_DESMARCAR, A_EDITAR, A_DESFAZER, A_REMOVER = (
    "liberar", "desmarcar", "editar", "desfazer", "remover")
SEM_NUVEM = "ainda não li a nuvem"
#: O que a forma de pagar e o reembolso mostram no diálogo de edição.
CAMPOS_DO_DIALOGO = ("tipo", "dados", "reembolso_nome", "reembolso_documento", "descricao")


@dataclass(frozen=True)
class LinhaDaTabela:
    iid: str
    tipo: str
    pagamento: object             # `pagamentos.Pagamento`
    texto: str
    valores: tuple
    tags: tuple


def _com_nota(p) -> str:
    return " · ".join(filter(None, [p.situacao, p.nota]))


def chave_da_linha(p) -> str:
    """A chave da linha na tela: "<id>|<parte_linha>" (decisão do
    coordenador, 22/10/2026). Estável entre recálculos — nada de posição."""
    return f"{p.id}|{getattr(p, 'parte_linha', '') or ''}"


def linhas_da_conta(conta, posicao: int, vistos: set | None = None) -> list[LinhaDaTabela]:
    """As filhas de uma conta do passo 2, na ordem: vai sair, liberados, à
    mão, já enviados, desmarcados, bloqueados. O iid é `chave_da_linha`;
    `vistos` (o mesmo conjunto para a tabela inteira) garante que ele nunca
    se repete: a chave igual (id vazio, o mesmo lançamento em duas contas)
    ganha "#2", "#3"… `posicao` fica por compatibilidade."""
    vistos = set() if vistos is None else vistos
    grupos = (
        (VAI, conta.vao_sair, lambda p: ("vai sair", brl(p.valor), "", _com_nota(p)),
         lambda p: ("atencao",) if p.origem == "editado" else ()),
        (LIB, conta.liberados, lambda p: ("liberado", brl(p.valor), "", _com_nota(p)),
         lambda p: ("atencao",)),
        (MAO, conta.a_mao, lambda p: ("à mão", brl(p.valor), "", p.situacao),
         lambda p: ("atencao",)),
        (ENV, conta.ja_enviados,
         lambda p: ("já enviado", brl(p.valor), "", f"já enviado (soma no a pagar) · {p.situacao}"),
         lambda p: ("atencao",)),
        (DESM, getattr(conta, "desmarcados", ()),
         lambda p: ("", "", f"desmarcado · {brl(p.valor)}", _com_nota(p)), lambda p: ("erro",)),
        (BLOQ, conta.bloqueados,
         lambda p: ("", "", f"bloqueado · {brl(p.valor)}", _com_nota(p)), lambda p: ("erro",)),
    )
    linhas = []
    for tipo, pagamentos, valores, tags in grupos:
        for p in pagamentos:
            base = iid = chave_da_linha(p)
            n = 1
            while iid in vistos:
                n += 1
                iid = f"{base}#{n}"
            vistos.add(iid)
            linhas.append(LinhaDaTabela(iid, tipo, p, f"   {p.favorecido}", valores(p), tags(p)))
    return linhas


def acoes_da_linha(tipo: str, tem_decisao: bool) -> frozenset:
    """O que a linha selecionada aceita. O à mão só se remove (editar à mão
    é remover e lançar de novo); o já enviado só se libera (editar o que
    não se gera de novo não muda nada); "desfazer" só onde há decisão."""
    base = {VAI: {A_DESMARCAR, A_EDITAR}, LIB: {A_EDITAR, A_DESFAZER},
            MAO: {A_REMOVER}, DESM: {A_DESFAZER}, ENV: {A_LIBERAR},
            BLOQ: {A_LIBERAR, A_EDITAR}}.get(tipo, set())
    if tem_decisao and tipo in (VAI, BLOQ, ENV):
        base = base | {A_DESFAZER}
    return frozenset(base)


def recusa_de_gravar(travada: str, gravando: bool) -> str:
    """"" = pode gravar; senão, o recado (nuvem travada ganha da gravação)."""
    if travada:
        return f"{travada}\n\nSem a nuvem nada desta tela é gravado — busque de novo."
    if gravando:
        return "Espere a gravação anterior terminar."
    return ""


def pode_liberar(linha) -> bool:
    """`conferencia.pode_liberar`, e nunca a PARTE de um lançamento dividido:
    liberar é por id e devolveria também a parte já enviada (pagar em dobro).
    Parte se resolve no ERP ou na Remessa."""
    return linha is not None and not getattr(linha, "parte", "") and cf.pode_liberar(linha)


def recusa_de_liberar(linha) -> str:
    """O recado de liberar a parte de um lançamento dividido, ou ""."""
    return cf.recusa_de_dividido(linha) if linha is not None else ""


def texto_do_desmarcar(pagamento) -> str:
    """O que o diálogo do Desmarcar diz. Desmarcar é por id: no lançamento
    dividido, saem TODAS as partes."""
    texto = "Sai da planilha, do HTML e da remessa."
    n = cf.partes_de(pagamento)
    if n:
        texto += chr(10) + f"Lançamento dividido em {n} boletos: saem as {n} partes."
    return texto


def certeza_ao_liberar(linha) -> str:
    """A 2ª pergunta, DEPOIS do motivo: já enviado ou favorecido fora dos
    Contatos. É a única trava contra pagar em dobro pelo HTML."""
    return cf.pede_certeza(linha)


def ids_do_dia(grupos) -> set[str]:
    return {ln.id for g in grupos for ln in (*g.entram, *g.nao_aptos) if ln.id}


def linha_do_id(grupos, ident: str, conta: str = "", parte_linha: str = ""):
    """A `confirmacao.Linha` do lançamento (a da conta, se houver duas; a da
    parte daquela linha digitável, no lançamento dividido)."""
    achadas = [ln for g in grupos for ln in (*g.entram, *g.nao_aptos) if ln.id == ident]
    if parte_linha:
        achadas = ([ln for ln in achadas if getattr(ln, "parte_linha", "") == parte_linha]
                   or achadas)
    return next((ln for ln in achadas if not conta or ln.conta == conta),
                achadas[0] if achadas else None)


def contas_para_a_mao(contas_erp, mapping, grupos) -> list[str]:
    """As contas do painel e as do dia — sem a PF (paga pelo celular, fora
    do HTML: `conferencia.nova_a_mao` a recusa)."""
    nomes = {a.name for a in contas_erp if mapping.resolve_label(a.name)}
    nomes |= {g.conta for g in grupos}
    return sorted(c for c in nomes if c and not html_pagamentos.e_conta_pf(c))


# ----------------------------------------------------------------- edição
def _limpo(valor) -> str:
    return str(valor or "").strip()


def valores_iniciais(registro: dict, conta: str) -> dict:
    """O que o diálogo mostra: o registro como está, e a descrição como vai
    ao banco (`descricao_para_colar`)."""
    vals = {k: _limpo(registro.get(k)) for k in ("tipo", "dados", "reembolso_nome",
                                                 "reembolso_documento")}
    vals["descricao"] = html_pagamentos.descricao_para_colar(registro, conta)
    return vals


def campos_da_edicao(iniciais: dict, digitados: dict) -> dict:
    """Só o que mudou. Forma de pagar muda inteira (tipo + dado); reembolso
    leva nome + documento E a forma de pagar (tipo + dado de quem recebe)."""
    mudou = {k for k in CAMPOS_DO_DIALOGO if _limpo(digitados.get(k)) != _limpo(iniciais.get(k))}
    campos = {}
    if mudou & {"reembolso_nome", "reembolso_documento"}:
        mudou |= {"reembolso_nome", "reembolso_documento", "tipo", "dados"}
    if mudou & {"tipo", "dados"}:
        mudou |= {"tipo", "dados"}
    for k in CAMPOS_DO_DIALOGO:
        if k in mudou:
            campos[k] = _limpo(digitados.get(k))
    return campos


def validar_edicao_da_tela(registro: dict, campos: dict, motivo: str) -> str:
    """`conferencia.validar_edicao` e as regras da tela:
    - reembolso exige tipo + dado juntos, e o dado não pode ser o do
      fornecedor (o dinheiro vai para OUTRA pessoa);
    - parte de lançamento dividido não muda a forma de pagar (a mesma linha
      digitável iria às N partes)."""
    if "reembolso_nome" in campos and not _limpo(campos["reembolso_nome"]):
        return "Para tirar o reembolso, use «Desfazer» (volta tudo ao que o ERP diz)."
    if cf.recusa_de_dividido(registro) and campos.keys() & {
            "tipo", "dados", "reembolso_nome", "reembolso_documento"}:
        return cf.recusa_de_dividido(registro)
    erro = cf.validar_edicao(campos, motivo)
    if erro:
        return erro
    if "reembolso_nome" in campos or "reembolso_documento" in campos:
        if not campos.get("tipo") or not campos.get("dados"):
            return ("O reembolso muda junto com a forma de pagar: escolha o tipo e "
                    "escreva o dado de quem recebe o reembolso.")
        if (not registro.get("reembolso")
                and _limpo(campos["dados"]) == _limpo(registro.get("dados"))):
            return ("Com o reembolso o dinheiro vai para outra pessoa: escreva a "
                    "chave (ou conta) DELA, não a do fornecedor.")
    return ""


def pergunta_do_valor(registro: dict, campos: dict) -> str:
    """A pergunta antes de gravar a linha digitável editada cujo valor
    embutido NÃO é o do pagamento (a tela pergunta com `default="no"`), ou
    "". Linha sem valor embutido não pergunta: grava com observação
    (`geracao`)."""
    if campos.get("tipo") != "Boleto":
        return ""
    return cf.conferir_valor_da_linha(_limpo(campos.get("dados")),
                                      registro.get("valor")).pergunta


def antes_da_edicao(iniciais: dict, campos: dict) -> dict:
    return {k: iniciais.get(k, "") for k in campos}


def descricao_de(pagamento) -> str:
    return f"{pagamento.favorecido} · {brl(pagamento.valor)}"


# ------------------------------------------------------- gravar e reler
@dataclass(frozen=True)
class Gravacao:
    """O que volta da thread de gravação para a tela."""

    #: A conferência relida depois de gravar; None = não reli.
    conferencia: object = None
    #: A gravação falhou (o recado); a releitura pode ter dado certo.
    erro: str = ""
    #: A releitura falhou: a tela limpa e pede para buscar de novo.
    travar: str = ""
    #: O que `fazer` devolveu (a linha gravada), para quem quiser.
    gravado: object = None


def reler_conferencia(cliente, dia) -> cf.Conferencia:
    return cf.Conferencia.da_nuvem(cliente.decisoes_do_dia(dia), cliente.pagamentos_a_mao(dia))


def gravar_e_reler(cliente, dia, fazer, *, recado=str, reler=reler_conferencia) -> Gravacao:
    """Grava (`fazer(cliente)`) e relê SEMPRE — também depois de um erro: a
    gravação pode ter entrado e a resposta se perdido, ou outra máquina ter
    gravado. Sem sessão, nem tenta."""
    if cliente is None:
        msg = "sem sessão na nuvem — entre de novo no app"
        return Gravacao(erro=f"Não gravei na nuvem: {msg}.", travar=msg)
    erro, gravado = "", None
    try:
        gravado = fazer(cliente)
    except Exception as e:                                   # noqa: BLE001
        erro = recado(e) + chr(10) * 2 + CONFIRA_DEPOIS_DO_ERRO
        # Parou no meio (`passo67.ParouNoMeio`): o que já entrou.
        gravado = getattr(e, "gravado_parcial", None)
    try:
        conf = reler(cliente, dia)
    except Exception as e:                                   # noqa: BLE001
        return Gravacao(erro=erro, gravado=gravado,
                        travar=f"não reli a nuvem depois de gravar ({e}) — busque de novo")
    return Gravacao(conferencia=conf, erro=erro, gravado=gravado)


# ---------------------------------------------------------------- datas
def ler_data(texto: str) -> _dt.date:
    """DD/MM/AAAA (ou DD/MM/AA); ValueError com recado."""
    m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\s*", texto or "")
    if not m:
        raise ValueError("Escreva a data como DD/MM/AAAA.")
    d, mes, ano = (int(x) for x in m.groups())
    if ano < 100:
        ano += 2000
    try:
        return _dt.date(ano, mes, d)
    except ValueError:
        raise ValueError("Esta data não existe.") from None



# ------------------------------------------------------------ à mão
def recado_do_link(texto: str, lido, ident_do_texto: str) -> str:
    """"" = o link (ou a falta dele) está em ordem com o que foi lido.
    `ident_do_texto` = `lancamento_do_erp.id_do_link(texto)`."""
    if not (texto or "").strip():
        return ""
    if lido is None:
        return "Clique em «Ler o lançamento» antes de gravar (ou apague o link)."
    if lido.id != ident_do_texto:
        return "O link mudou depois de lido: leia o lançamento de novo."
    return ""


# ------------------------------------------------- conserto da rodada 1
#: Depois de um erro de gravação a resposta pode ter se perdido com a linha
#: já gravada: a tabela relida é a verdade, e não o recado.
CONFIRA_DEPOIS_DO_ERRO = ("Pode ter gravado ou não — a tabela abaixo mostra o que está na "
                          "nuvem agora; confira antes de repetir.")
PERGUNTA_SEM_NUVEM = ("Não consegui ler a nuvem: as decisões de hoje (liberados, "
                      "desmarcados, edições, à mão) NÃO estão aplicadas. Gerar mesmo assim?")


@dataclass(frozen=True)
class Botoes:
    """O que fica ligado na tela. `dia` = Excel, Mandar aportes, sugestão e
    movimentos à mão; `geradores` = planilha, HTML e remessa; `passo2` = os
    que gravam na nuvem; `buscar` = o Buscar."""

    dia: bool
    geradores: bool
    passo2: bool
    buscar: bool


def botoes(*, tem_leitura: bool, gravando: bool, travada: str, sem_geradores: bool) -> Botoes:
    """Gravando na nuvem, NADA fica ligado: gerar no meio da gravação
    sairia com a decisão de antes; buscar limparia a tela embaixo dela.
    Lendo o ERP, a tela está sem leitura (o Buscar limpa antes): só buscar."""
    if gravando:
        return Botoes(False, False, False, False)
    if not tem_leitura:
        return Botoes(False, False, False, True)
    return Botoes(True, not sem_geradores, not travada, True)


def pergunta_ao_gerar(travada: str) -> str:
    """Nuvem que FALHOU (não a que ainda não foi lida): planilha, HTML e
    remessa perguntam antes de sair sem as decisões do dono."""
    return PERGUNTA_SEM_NUVEM if travada and travada != SEM_NUVEM else ""


def recusa_da_selecao(ld, acao: str, tem_decisao: bool, recado: str) -> str:
    """"" = a linha selecionada aceita `acao`; senão, o recado."""
    if ld is None or acao not in acoes_da_linha(ld.tipo, tem_decisao):
        return recado
    if not str(getattr(ld.pagamento, "id", "") or "").strip():
        return ("Esta linha não tem o número do lançamento: não dá para gravar uma "
                "decisão para ela. Corrija no ERP.")
    return ""


def valores_para_editar(registro_erp: dict, conta: str, decisao) -> dict:
    """O que o diálogo de edição mostra: o do ERP com as edições que já
    valem (a decisão dobrada) por cima. Quem compara para saber o que mudou
    é ISTO; o `antes` continua o do ERP (`valores_iniciais`)."""
    vals = valores_iniciais(registro_erp, conta)
    for k, v in (getattr(decisao, "edicoes", None) or {}).items():
        if k in vals:
            vals[k] = _limpo(v)
    return vals
