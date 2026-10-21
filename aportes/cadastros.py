# -*- coding: utf-8 -*-
"""Ver e corrigir, pela aba Aportes, quem paga ou recebe aporte.

Até 21/10/2026 a lista de Pagou/Recebeu só se via pelo painel do Supabase, e
só se corrigia por lá. O dono pediu uma janela para ver como ela está e
corrigir — e escolheu **corrigir, sem apagar**: o banco aceita UPDATE só nas
quatro colunas da `entidade`, e DELETE continua sem existir para o app
(migration `20261021100000_entidade_pode_ser_corrigida_pelo_app.sql`). Cada
correção vai para a `auditoria` por um gatilho no próprio banco.

O rateio das subcontas (aportadores, partes e obras) NÃO se corrige aqui: ele
já tem casa, a janela do Novo cadastro. Desta janela só sai o DONO da
subconta, porque o nome dela em Pagou/Recebeu segue o padrão
"SUBCONTA 00000-0 - BANCO - INVESTIDOR" e a conta é a própria subconta.

Aqui mora só a regra — listar, validar, montar a mudança — para ter teste. A
janela está em `cadastros_dialogo.py`; quem fala com o banco é `gravar`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import util

from . import dados as cadastro
from . import regras
from .novo_cadastro import _chave

#: As colunas que a janela mostra e corrige — as mesmas do GRANT.
COLUNAS = ("nome_exibicao", "nome_oficial", "conta", "nome_descricao")

#: Obra que o ERP usa como "ainda não decidido".
_A_CLASSIFICAR = "a classificar"


def _numero(entidade: dict) -> str:
    return regras.numero_da_conta(entidade.get("conta") or "")


def linhas_das_subcontas(entidades: list[dict], rateios: dict) -> dict:
    """{número: a linha de Pagou/Recebeu daquela subconta, ou None}.

    Pelo número lido da conta — mas número de conta se repete entre bancos.
    Com mais de uma candidata, vale a que tem "SUBCONTA 00000-0" no nome em
    Pagou/Recebeu (o padrão do Novo cadastro); sem uma só, None: escolher a
    primeira poria "Corrigir dono" na linha de outra empresa, e é o
    `nome_oficial` dela que vira favorecido nos aportes."""
    saida = {}
    for numero in rateios:
        if numero.startswith("_"):
            continue
        cands = [e for e in entidades if _numero(e) == numero]
        if len(cands) > 1:
            cands = [e for e in cands
                     if f"subconta {numero}" in _chave(e.get("nome_exibicao"))]
        saida[numero] = cands[0] if len(cands) == 1 else None
    return saida


def e_de_subconta(entidade: dict, rateios: dict, entidades: list[dict]) -> bool:
    """A linha é a de uma subconta de investidor que tem rateio?"""
    def mesma(e):
        if e is None:
            return False
        if e is entidade:
            return True
        return e.get("id") is not None and e.get("id") == entidade.get("id")
    return any(mesma(e)
               for e in linhas_das_subcontas(entidades, rateios).values())


def empresas(entidades: list[dict], rateios: dict) -> list[dict]:
    """A aba "Empresas e pessoas": tudo que não é linha de subconta."""
    delas = [e for e in linhas_das_subcontas(entidades, rateios).values()
             if e is not None]
    return sorted((e for e in entidades if not any(e is d for d in delas)),
                  key=lambda e: _chave(e.get("nome_exibicao")))


def como_dict(entidades: list[dict]) -> dict:
    """A lista do banco no formato de `dados.carregar_contas` — o que a aba
    usa para montar e lançar. Montar daqui, e não reler o `contas.csv`,
    é o que garante que a aba lança com o que o banco ACABOU de aceitar:
    com o CSV aberto no Excel a regravação falha, e reler traria a conta
    antiga com o log dizendo "corrigido"."""
    return {str(e["nome_exibicao"]).strip(): {
                "nome_oficial": str(e.get("nome_oficial") or "").strip(),
                "conta": str(e.get("conta") or "").strip() or None,
                "nome_descricao": str(e.get("nome_descricao") or "").strip()
                or None}
            for e in entidades if str(e.get("nome_exibicao") or "").strip()}


@dataclass
class Subconta:
    numero: str
    entidade: dict | None
    dono: str
    aportadores: list = field(default_factory=list)
    obras: list = field(default_factory=list)
    avisos: list = field(default_factory=list)


def _pct(valor) -> str:
    texto = format(valor, "f").replace(".", ",")
    return texto[:-3] if texto.endswith(",00") else texto


def subcontas(entidades: list[dict], rateios: dict) -> list[Subconta]:
    """A aba "Subcontas de investidor", com os avisos que a tela pinta.

    "Dono diferente" compara com o dono MAIS COMUM das outras subcontas: as
    subcontas de uma holding saem todas no contato dela, e uma que destoa
    quase sempre é o investidor posto no lugar do dono."""
    da_conta = linhas_das_subcontas(entidades, rateios)
    saida = []
    for numero in sorted(n for n in rateios if not n.startswith("_")):
        cfg = rateios[numero] or {}
        entidade = da_conta.get(numero)
        invs = list(cfg.get("investidores") or [])
        pcts = regras.percentuais_dos_pesos(invs, cfg.get("pesos") or {})
        saida.append(Subconta(
            numero=numero, entidade=entidade,
            dono=str((entidade or {}).get("nome_oficial") or "").strip(),
            aportadores=[f"{n} {_pct(p)}%" for n, p in zip(invs, pcts)],
            obras=list(cfg.get("obras") or [])))

    donos = [s.dono for s in saida if s.dono]
    for s in saida:
        if s.entidade is None:
            repetidas = sum(1 for e in entidades if _numero(e) == s.numero)
            s.avisos.append("mais de uma conta com este número" if repetidas > 1
                            else "sem conta em Pagou/Recebeu")
        outros = [d for d in donos if _chave(d) != _chave(s.dono)]
        iguais = len(donos) - len(outros)
        if s.dono and outros:
            comum = max(set(outros), key=outros.count)
            if outros.count(comum) > iguais:
                s.avisos.append(f"dono diferente das outras subcontas ({comum})")
        if any(_A_CLASSIFICAR in _chave(o) for o in s.obras):
            s.avisos.append("obra a classificar")
    return saida


def _limpo(valor, coluna: str):
    texto = str(valor or "").strip()
    if coluna in ("conta", "nome_descricao"):
        return texto or None
    return texto


def mudancas(antes: dict, depois: dict) -> dict:
    """Só as colunas que mudaram, já no formato do banco (vazio = None)."""
    saida = {}
    for coluna in COLUNAS:
        novo = _limpo(depois.get(coluna), coluna)
        if novo != _limpo(antes.get(coluna), coluna):
            saida[coluna] = novo
    return saida


def validar(antes: dict, depois: dict, entidades: list[dict], rateios: dict,
            *, contas=None, participantes=None) -> str:
    """"" quando dá para gravar; senão, o motivo em português.

    `contas` (linhas da tabela `conta`) e `participantes` (contatos do ERP)
    são opcionais: sem eles, não se confere se a conta e o contato existem —
    o banco aceitaria, e o Conferir cadastro da aba pega depois."""
    mud = mudancas(antes, depois)
    if not mud:
        return "Nada mudou."
    exibicao = _limpo(depois.get("nome_exibicao"), "nome_exibicao")
    oficial = _limpo(depois.get("nome_oficial"), "nome_oficial")
    conta = _limpo(depois.get("conta"), "conta") or ""
    apelido = _limpo(depois.get("nome_descricao"), "nome_descricao") or ""
    if e_de_subconta(antes, rateios, entidades):
        if "nome_exibicao" in mud:
            return ("O nome de uma subconta em Pagou/Recebeu segue o padrão "
                    "\"SUBCONTA 00000-0 - BANCO - INVESTIDOR\". Corrija só o "
                    "dono.")
        if "conta" in mud:
            return ("A conta de uma subconta não muda: ela É a subconta. "
                    "Corrija só o dono.")
    if not exibicao:
        return "Falta o nome que vai aparecer em Pagou/Recebeu."
    if not oficial:
        return ("Falta o nome do contato no Mais Controle (como está no "
                "cadastro de Contatos do ERP).")
    if ";" in exibicao + oficial + conta + apelido:
        # O cache local é CSV separado por ";".
        return "Os nomes não podem ter ponto e vírgula (;)."
    if "nome_exibicao" in mud and exibicao.startswith(cadastro.INVESTIDOR_PREFIXO):
        return (f"Nomes que começam com \"{cadastro.INVESTIDOR_PREFIXO}\" são "
                "dos rateios de subconta. Escolha outro nome.")
    if participantes is not None and "nome_oficial" in mud and \
            _chave(oficial) not in {_chave(p) for p in participantes}:
        return (f"O contato \"{oficial}\" não existe no Mais Controle com esse "
                "nome. Escolha na lista.")
    if contas is not None and conta and "conta" in mud and \
            _chave(conta) not in {_chave(c.get("nome_erp")) for c in contas}:
        return (f"A conta \"{conta}\" não está no cadastro de contas. Escolha "
                "na lista.")
    for e in entidades:
        if e.get("id") == antes.get("id"):
            continue
        if _chave(e.get("nome_exibicao")) == _chave(exibicao):
            return f"Já existe \"{e['nome_exibicao']}\" na lista."
        if conta and _chave(e.get("conta")) == _chave(conta):
            return (f"A conta \"{conta}\" já está na lista como "
                    f"\"{e['nome_exibicao']}\".")
    return ""


def em_uso(entidade: dict, pares) -> bool:
    """A linha aparece na lista "A lançar"? `pares` = (pagou, recebeu) de
    cada operação.

    Corrigir com a lista cheia é o caminho para o aporte em dobro: a memória
    do que já entrou no ERP (`criados`) é por POSIÇÃO dentro da operação, e a
    operação é montada a partir do cadastro. Trocar o contato ou a conta no
    meio faria o próximo Lançar mandar o resto para outro lugar — ou não
    reconhecer o nome e recusar a operação inteira."""
    nome = _chave(entidade.get("nome_exibicao"))
    numero = _numero(entidade)
    for pagou, recebeu in pares:
        if nome in (_chave(pagou), _chave(recebeu)):
            return True
        if numero and str(pagou or "").startswith(cadastro.INVESTIDOR_PREFIXO) \
                and regras.numero_da_conta(pagou) == numero:
            return True
    return False


# --------------------------------------------------------------------------
# Banco — só aqui o módulo sai da máquina
# --------------------------------------------------------------------------
def _rest():
    from nuvem import rest
    return rest


def ler(token: str) -> list[dict]:
    """As linhas de Pagou/Recebeu COM o id — é por ele que se corrige."""
    return list(_rest().ler(
        "entidade", token,
        colunas="id,nome_exibicao,nome_oficial,conta,nome_descricao") or [])


def _regravar_cache(entidades: list[dict]) -> None:
    """Regrava o `contas.csv` com o que o banco tem agora, no mesmo formato
    do `nuvem.cadastro.sincronizar`. Lista vazia não apaga o arquivo: vazio
    nunca substitui cheio."""
    if not entidades:
        return
    from nuvem import cache
    linhas = [{"nome_exibicao": e["nome_exibicao"],
               "nome_oficial": e.get("nome_oficial") or "",
               "conta": e.get("conta") or "",
               "nome_descricao": e.get("nome_descricao") or ""}
              for e in sorted(entidades, key=lambda x: x["nome_exibicao"])]
    cache.gravar_csv("contas.csv", list(COLUNAS), linhas)


@dataclass
class Gravado:
    """O que `gravar` devolve: a lista como ficou e o que a tela deve
    avisar (a correção já está no banco; os avisos são do resto)."""
    entidades: list
    avisos: list = field(default_factory=list)


def gravar(token: str, id_, mud: dict, atuais=None) -> Gravado:
    """Corrige UMA linha no banco e, só depois, o cache local.

    PATCH barrado pela RLS (o SQL ainda não aplicado, usuário desativado)
    NÃO dá erro no PostgREST: devolve zero linhas. Por isso a resposta é
    conferida — "corrigido" sem ter corrigido é pior que a recusa.

    Depois que o banco aceitou, nada mais aqui vira erro: reler a lista ou
    regravar o `contas.csv` falhando viram AVISO. Erro faria a tela dizer
    "não corrigiu" sobre uma correção que está gravada."""
    if not id_ or not mud:
        raise ValueError("correção sem linha ou sem mudança")
    rest = _rest()
    alteradas = rest.alterar("entidade", token, f"id=eq.{int(id_)}", mud)
    if len(alteradas or []) != 1:
        raise RuntimeError(
            "o banco não aceitou a correção (nenhuma linha alterada). Se é a "
            "primeira vez, falta aplicar o SQL que libera corrigir pelo app.")
    avisos = []
    try:
        entidades = ler(token)
    except Exception as e:                                   # noqa: BLE001
        entidades = [dict(e_, **alteradas[0]) if e_.get("id") == id_ else e_
                     for e_ in (atuais or [])]
        avisos.append(f"a correção foi gravada, mas não deu para reler a "
                      f"lista ({e}); a tela usa a lista de antes com a "
                      "correção aplicada.")
    try:
        _regravar_cache(entidades)
    except Exception as e:                                   # noqa: BLE001
        util.log(__name__).warning("regravando contas.csv", exc_info=True)
        avisos.append(f"o arquivo contas.csv não foi atualizado ({e}) — está "
                      "aberto no Excel? A aba já usa o cadastro corrigido; "
                      "feche o arquivo e ele se acerta na próxima abertura.")
    return Gravado(entidades, avisos)
