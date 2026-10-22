# -*- coding: utf-8 -*-
"""O passo 2 editável da tela do dia — as regras da TELA, sem janela.

`frame.py` só desenha, pergunta e manda gravar; o que ele decidiria com `if`
mora aqui, com teste puro (a máquina do dono não roda teste de tela):

- as linhas da tabela do passo 2 (`linhas_da_conta`): iid por POSIÇÃO, nunca
  pelo id do lançamento — um lançamento dividido em partes (entrega 5) teria
  o mesmo id em N linhas, e o Treeview recusa iid repetido;
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


def linhas_da_conta(conta, posicao: int) -> list[LinhaDaTabela]:
    """As filhas de uma conta do passo 2, na ordem: vai sair, liberados, à
    mão, já enviados, desmarcados, bloqueados. `posicao` = a da conta na
    tabela; o iid é "<tipo>|<posicao>.<n>"."""
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
    linhas, n = [], 0
    for tipo, pagamentos, valores, tags in grupos:
        for p in pagamentos:
            linhas.append(LinhaDaTabela(f"{tipo}|{posicao}.{n}", tipo, p,
                                        f"   {p.favorecido}", valores(p), tags(p)))
            n += 1
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


def botoes_ligados(tem_leitura: bool, travada: str, gravando: bool) -> bool:
    return bool(tem_leitura) and not travada and not gravando


def pode_liberar(linha) -> bool:
    """`conferencia.pode_liberar`, e nunca a PARTE de um lançamento dividido:
    liberar é por id e devolveria também a parte já enviada (pagar em dobro).
    Parte se resolve no ERP ou na Remessa."""
    return linha is not None and not getattr(linha, "parte", "") and cf.pode_liberar(linha)


def certeza_ao_liberar(linha) -> str:
    """A 2ª pergunta, DEPOIS do motivo: já enviado ou favorecido fora dos
    Contatos. É a única trava contra pagar em dobro pelo HTML."""
    return cf.pede_certeza(linha)


def ids_do_dia(grupos) -> set[str]:
    return {ln.id for g in grupos for ln in (*g.entram, *g.nao_aptos) if ln.id}


def linha_do_id(grupos, ident: str, conta: str = ""):
    """A `confirmacao.Linha` do lançamento (a da conta, se houver duas)."""
    achadas = [ln for g in grupos for ln in (*g.entram, *g.nao_aptos) if ln.id == ident]
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
    erro = cf.validar_edicao(campos, motivo)
    if erro:
        return erro
    if registro.get("parte") and ("tipo" in campos or "dados" in campos):
        return ("Este lançamento está dividido em partes: a forma de pagar de uma "
                "parte se corrige no ERP.")
    if "reembolso_nome" in campos or "reembolso_documento" in campos:
        if not campos.get("tipo") or not campos.get("dados"):
            return ("O reembolso muda junto com a forma de pagar: escolha o tipo e "
                    "escreva o dado de quem recebe o reembolso.")
        if (not registro.get("reembolso")
                and _limpo(campos["dados"]) == _limpo(registro.get("dados"))):
            return ("Com o reembolso o dinheiro vai para outra pessoa: escreva a "
                    "chave (ou conta) DELA, não a do fornecedor.")
    return ""


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
        erro = recado(e)
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
