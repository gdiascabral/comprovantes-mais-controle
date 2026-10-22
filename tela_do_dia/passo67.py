# -*- coding: utf-8 -*-
""""Agendados a confirmar", passo 6 ("Marcar agendados") e passo 7 ("Lista do
diretor") — as regras da TELA, sem janela (o mesmo papel de `passo2.py`).

- **Pré-marca só vem da prova** (`agendados.situacao`): o que a tela marca de
  início é `Situacao.pre_marca`; o resto nasce desmarcado. "Pago" é sempre um
  clique do dono, e título que sumiu ou mudou só sai da lista por resposta
  explícita dele.
- **Gravar e reler TUDO** (`reler_tudo`): depois de gravar uma resposta,
  agendados, nome curto ou a lista, a tela relê decisões, à mão, agendados de
  hoje, pendentes, nomes curtos e a lista de ontem — nunca número velho. O ERP
  NÃO é relido aí (corre fora da thread do navegador): pendente que já tinha
  situação da leitura completa a mantém; pendente novo usa o título da leitura
  do dia e, sem ele, "não reli o título no ERP" — nunca "sumiu".
- **Marcar agendados**: as repetidas (índice único, 23505/409 duplicate) viram
  recado; as gravadas contam; qualquer outra recusa é erro, e a tela relê.
- **Lista do diretor**: copiar é recusado enquanto alguma linha não tiver nome
  curto; nome curto igual ao de outra conta, ou com quebra de linha/tab, é
  recusado; ↑/↓ não cruza a fronteira numerados × demais.

Nenhuma função altera os objetos recebidos.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from . import agendados as ag
from . import conferencia as cf
from . import lista_diretor as ldr
from .nuvem_do_dia import LidoDaNuvem
from .valores import brl

MARCADO, DESMARCADO = "☑", "☐"
#: Colunas (a 100%; somam menos que o cartão a 1280x800 com o menu aberto).
COLS_AGD = (("marca", "", 30, "center"), ("dia", "AGENDADO", 80, "w"),
            ("conta", "CONTA", 160, "w"), ("fav", "FAVORECIDO", 170, "w"),
            ("valor", "VALOR", 100, "e"), ("sit", "SITUAÇÃO", 200, "w"))
COLS_MARCAR = (("marca", "", 30, "center"), ("conta", "CONTA", 200, "w"),
               ("fav", "FAVORECIDO", 220, "w"), ("valor", "VALOR", 100, "e"),
               ("sit", "SITUAÇÃO", 200, "w"))
COLS_LISTA = (("ordinal", "ORDEM", 60, "center"), ("nome", "NOME", 300, "w"),
              ("valor", "VALOR", 120, "e"))
JA_MARCADO = "já marcado hoje"
_CONTROLE = ("\r", "\n", "\t")


@dataclass(frozen=True)
class LinhaDaTabela:
    iid: str
    valores: tuple
    tags: tuple


# ------------------------------------------------- agendados a confirmar
def marcas_iniciais(pendentes, antigas=None) -> dict:
    """{agendado_id: marcado}. O que o dono já clicou continua; pendente
    novo nasce com a pré-marca da prova (`Situacao.pre_marca`)."""
    antigas = antigas or {}
    return {a.id: (antigas[a.id] if a.id in antigas else bool(sit.pre_marca))
            for a, sit, _r in pendentes}


def alternar(marcas: dict, ident) -> dict:
    novas = dict(marcas)
    novas[ident] = not novas.get(ident, False)
    return novas


def texto_da_situacao(sit, resposta) -> str:
    """A frase da situação; um "reagendado" anterior vem na frente."""
    if resposta is not None and resposta.resposta == "reagendado" and resposta.nova_data:
        motivo = f" ({resposta.motivo})" if resposta.motivo else ""
        return f"reagendado para {resposta.nova_data:%d/%m}{motivo} · {sit.frase}"
    return sit.frase


def linhas_agendados(pendentes, marcas: dict) -> list[LinhaDaTabela]:
    return [LinhaDaTabela(
        str(a.id),
        (MARCADO if marcas.get(a.id) else DESMARCADO, f"{a.dia:%d/%m}", a.conta,
         a.favorecido, brl(a.valor), texto_da_situacao(sit, r)),
        (sit.tag,) if sit.tag else ())
        for a, sit, r in pendentes]


def pagos_marcados(pendentes, marcas: dict) -> list[tuple]:
    """[(agendado_id, prova)] dos marcados; a prova é a da situação ("" sem)."""
    return [(a.id, sit.prova if sit.pre_marca else "")
            for a, sit, _r in pendentes if marcas.get(a.id)]


def pergunta_ao_pagar(pendentes, marcas: dict) -> str:
    """Marcado SEM prova (sumiu, mudou, aguardando): o dono confirma."""
    sem = [a for a, sit, _r in pendentes if marcas.get(a.id) and not sit.pre_marca]
    if not sem:
        return ""
    return (f"{len(sem)} marcado(s) sem prova de pagamento (o app não viu baixa nem "
            "retorno do banco). Confirma que foram pagos?")


def recusa_de_pagar(itens) -> str:
    return "" if itens else "Marque (clique na 1ª coluna ou Espaço) o que foi pago."


class ParouNoMeio(Exception):
    """A gravação de várias respostas parou no meio: `gravados` entraram."""

    def __init__(self, causa, gravados, total):
        super().__init__(str(causa))
        self.causa, self.gravados, self.total = causa, list(gravados), total


def responder_pagos(cliente, itens) -> list:
    """Uma resposta "pago" por agendado, com a prova. Erro no meio levanta
    `ParouNoMeio` com o que já entrou (a tela relê de qualquer jeito)."""
    gravados = []
    for ident, prova in itens:
        try:
            cliente.responder(ident, "pago", prova=prova)
        except Exception as e:                               # noqa: BLE001
            raise ParouNoMeio(e, gravados, len(itens)) from e
        gravados.append(ident)
    return gravados


def recusa_da_resposta(pendentes, ident, resposta, motivo, nova_data, hoje) -> str:
    """"" = pode gravar a resposta para o pendente selecionado."""
    if ident is None or ident not in {a.id for a, _s, _r in pendentes}:
        return "Selecione um agendado da lista."
    return ag.validar_resposta(resposta, motivo, nova_data, hoje)


# ------------------------------------------------------------- passo 6
def alternar_para_marcar(itens, i) -> tuple[list, str]:
    """(itens novos, recado). O já marcado hoje não se marca de novo."""
    itens = list(itens)
    if not 0 <= i < len(itens):
        return itens, ""
    if itens[i].ja_marcado:
        return itens, ag.recado_das_repetidas([{"favorecido": itens[i].favorecido,
                                                "valor": str(itens[i].valor)}])
    itens[i] = replace(itens[i], marcado=not itens[i].marcado)
    return itens, ""


def linhas_para_marcar(itens) -> list[LinhaDaTabela]:
    return [LinhaDaTabela(
        str(n), (MARCADO if i.marcado and not i.ja_marcado else DESMARCADO, i.rotulo,
                 i.favorecido, brl(i.valor), JA_MARCADO if i.ja_marcado else ""),
        ("info",) if i.ja_marcado else ())
        for n, i in enumerate(itens)]


def remontar_para_marcar(novos, antigos) -> list:
    """A lista nova (depois de reler) com o desmarcado pelo dono guardado."""
    antes = {i.alvo: i.marcado for i in antigos or () if not i.ja_marcado}
    return [replace(i, marcado=antes[i.alvo]) if not i.ja_marcado and i.alvo in antes
            else replace(i) for i in novos]


def recusa_de_marcar(itens) -> str:
    if itens is None:
        return "Clique em «Montar a lista» primeiro."
    if not ag.linhas_para_nuvem(itens):
        return "Nada marcado para gravar (o já marcado hoje não vai de novo)."
    return ""


def resumo_da_marcacao(gravado) -> list[str]:
    gravadas, repetidas = gravado or ([], [])
    linhas = [f"{len(gravadas)} agendado(s) marcado(s) na nuvem." if gravadas
              else "Nenhum agendado novo gravado."]
    recado = ag.recado_das_repetidas(repetidas)
    if recado:
        linhas.append(recado)
    return linhas


def recado_do_erro(e, base: str, *, depois: str = "") -> str:
    """O recado de erro com o que JÁ entrou: as respostas gravadas antes do
    erro (`ParouNoMeio`) ou as linhas do `marcar_agendados` que entraram
    (`gravadas`) e as repetidas."""
    partes = [base]
    if isinstance(e, ParouNoMeio):
        partes.append(f"Gravei {len(e.gravados)} de {e.total} resposta(s) antes do erro.")
    gravadas = getattr(e, "gravadas", None)
    if gravadas:
        partes.append(f"{len(gravadas)} agendado(s) já tinham entrado antes do erro.")
    repetidas = getattr(e, "repetidas", None)
    if repetidas:
        partes.append(ag.recado_das_repetidas(repetidas))
    if depois:
        partes.append(depois)
    return "\n\n".join(partes)


# ------------------------------------------------------------- passo 7
def montar_lista(agendados_hoje, rotulo_de, nomes, anterior, atual=None) -> list:
    """A lista de hoje. Com `atual` (o que o dono arrumou), a ordem dele vale
    em cima da sugestão de ontem; conta nova vai para os demais."""
    base = ldr.montar(agendados_hoje, rotulo_de, nomes)
    ordem = ldr.para_nuvem(atual) if atual else anterior
    return ldr.sugerir_ordem(base, ordem)


def pode_mover(linhas, i, delta) -> bool:
    """Só troca com a vizinha do MESMO lado (numerados × demais)."""
    if i is None:
        return False
    j = i + delta
    if not (0 <= i < len(linhas) and 0 <= j < len(linhas)):
        return False
    return (linhas[i].ordinal is None) == (linhas[j].ordinal is None)


def botoes_da_lista(linhas, i, *, ligado: bool) -> dict:
    tem = ligado and i is not None and 0 <= i < len(linhas)
    return {"subir": ligado and pode_mover(linhas, i, -1),
            "descer": ligado and pode_mover(linhas, i, 1),
            "ordinal": tem, "nome": tem, "copiar": ligado and bool(linhas)}


def recusa_de_copiar(linhas) -> str:
    if not linhas:
        return "Nenhum agendado marcado hoje: a lista está vazia."
    sem = [l.rotulo for l in linhas if l.sem_nome_curto]
    if sem:
        return ("Falta o nome curto de: " + ", ".join(sem)
                + ". Selecione a linha e use «Nome curto…» antes de copiar.")
    return ""


def _comparavel(nome: str) -> str:
    return " ".join(str(nome or "").split()).casefold()


def validar_nome_curto(nome, rotulo, nomes: dict, linhas) -> str:
    """`lista_diretor.validar_nome_curto` + sem quebra de linha/tab + não
    pode ser o nome (curto, ou o mostrado) de OUTRA conta."""
    if any(c in str(nome or "") for c in _CONTROLE):
        return "O nome curto não pode ter quebra de linha nem tabulação."
    erro = ldr.validar_nome_curto(nome)
    if erro:
        return erro
    outros = {_comparavel(v) for c, v in (nomes or {}).items() if c != rotulo}
    outros |= {_comparavel(l.nome) for l in linhas or () if l.rotulo != rotulo}
    if _comparavel(nome) in outros:
        return "Outra conta já usa este nome curto: escolha outro."
    return ""


# ----------------------------------------------------------- releitura
def reler_tudo(cliente, dia, anterior, lancamentos) -> LidoDaNuvem:
    """A releitura depois de gravar (decisão a). Levanta se a nuvem falhar
    (`passo2.gravar_e_reler` transforma em `travar`)."""
    conf = cf.Conferencia.da_nuvem(cliente.decisoes_do_dia(dia), cliente.pagamentos_a_mao(dia))
    de_hoje = [ag.Agendado.de_linha(x) for x in cliente.agendados_do_dia(dia)]
    abertos = [ag.Agendado.de_linha(x) for x in cliente.agendados_em_aberto()]
    respostas = [ag.Resposta.de_linha(x) for x in cliente.respostas([a.id for a in abertos])]
    nomes, lista_anterior = cliente.nomes_curtos(), cliente.lista_anterior(dia)
    ultimas = ag.ultima_resposta(respostas)
    antes = {a.id: sit for a, sit, _r in (anterior.pendentes if anterior is not None else ())}
    titulos = {str(i.get("id")): i for i in lancamentos or () if i.get("id")}
    linhas = []
    for a in ag.pendentes(abertos, respostas):
        sit = antes.get(a.id)
        if sit is None:
            titulo = titulos.get(a.lancamento_id)
            try:
                sit = ag.situacao(a, titulo, None,
                                  relido=titulo is not None or not a.lancamento_id)
            except Exception:                                # noqa: BLE001
                sit = ag.Situacao("atencao", "não consegui ler o título no ERP — responda")
        linhas.append((a, sit, ultimas.get(a.id)))
    return LidoDaNuvem(conf, de_hoje, linhas, nomes, lista_anterior, "", [])
