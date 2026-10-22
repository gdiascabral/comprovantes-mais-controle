# -*- coding: utf-8 -*-
"""A conferência editável do passo 2 da aba "Pagamentos do dia". Sem tela.

O dono pode LIBERAR um bloqueado (com motivo), DESMARCAR o que ia sair,
EDITAR a forma de pagar, o dado de reembolso e a descrição, e lançar um
pagamento À MÃO. Cada clique é uma linha nova na nuvem
(`nuvem.pagamentos_do_dia`, só acrescenta); o estado de cada alvo é a
"dobra" de todos os eventos dele, na ordem do id do banco (`dobrar`).
"Desfazer" apaga a decisão e o alvo volta a ser o que o ERP diz.

Quem e quando vêm do servidor (`quem_nome`/`quando` carimbados lá): aqui só
se leem. As validações usam os tetos das constraints do banco (motivo e
descrição até 200, dados até 500), para a tela recusar antes da nuvem.

O casamento do Anexar (`aviso_de_casamento`) usa as MESMAS funções de
`anexar/matcher.py`: centro de custo na descrição e o número do documento
como último número (ou rotulado NF/OC).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from anexar import matcher
from pagamentos_dia import confirmacao, html_pagamentos, ocr_boleto
from pagamentos_dia import regras_pagamento as regras

from .valores import CENTAVO, brl, ler_valor_editado

LIBERAR, DESMARCAR, EDITAR, DESFAZER, REMOVER_A_MAO = (
    "liberar", "desmarcar", "editar", "desfazer", "remover_a_mao")
PREFIXO_A_MAO = "mao:"
#: Tetos das constraints de `pagamento_decisao`/`pagamento_a_mao`.
MOTIVO_MINIMO, TEXTO_MAXIMO, DADOS_MAXIMO = 3, 200, 500
TIPOS = ("Pix", "Boleto", "Transferência")
CAMPOS_EDITAVEIS = ("tipo", "dados", "reembolso_nome", "reembolso_documento", "descricao")
#: O trecho do `remessa_dia.MOTIVO_SEM_DOCUMENTO` que aparece na situação.
_FORA_DOS_CONTATOS = "cadastro de Contatos"
_ONZE_CRUS = re.compile(r"\d{11}")


@dataclass(frozen=True)
class Evento:
    """Uma linha de `pagamento_decisao`."""

    id: int
    alvo: str
    conta: str
    acao: str
    motivo: str = ""
    campos: dict = field(default_factory=dict)
    antes: dict = field(default_factory=dict)
    corrigir_no_erp: bool = False
    quem_nome: str = ""
    quando: str = ""

    @classmethod
    def de_linha(cls, linha: dict) -> "Evento":
        return cls(id=int(linha.get("id") or 0), alvo=str(linha.get("alvo") or ""),
                   conta=str(linha.get("conta") or ""), acao=str(linha.get("acao") or ""),
                   motivo=str(linha.get("motivo") or ""), campos=dict(linha.get("campos") or {}),
                   antes=dict(linha.get("antes") or {}),
                   corrigir_no_erp=bool(linha.get("corrigir_no_erp")),
                   quem_nome=str(linha.get("quem_nome") or ""), quando=str(linha.get("quando") or ""))


@dataclass
class Decisao:
    """O estado de um alvo (id do lançamento, ou "mao:<id>") depois dos eventos."""

    alvo: str
    conta: str = ""
    liberado: bool = False
    motivo_liberacao: str = ""
    desmarcado: bool = False
    motivo_desmarcar: str = ""
    edicoes: dict = field(default_factory=dict)
    antes: dict = field(default_factory=dict)
    motivo_edicao: str = ""
    corrigir_no_erp: bool = False
    removido: bool = False
    quem_nome: str = ""
    quando: str = ""

    @property
    def editado(self) -> bool:
        return bool(self.edicoes)


def dobrar(eventos) -> dict[str, Decisao]:
    """O estado de cada alvo depois de TODOS os eventos, na ordem do id
    (a do banco). Ação desconhecida (app mais novo) não decide nada."""
    estado: dict[str, Decisao] = {}
    for ev in sorted(eventos, key=lambda e: e.id):
        if ev.acao == DESFAZER:
            estado.pop(ev.alvo, None)
            continue
        if ev.acao not in (LIBERAR, DESMARCAR, EDITAR, REMOVER_A_MAO):
            continue
        d = estado.setdefault(ev.alvo, Decisao(ev.alvo, conta=ev.conta))
        if ev.acao == LIBERAR:
            d.liberado, d.desmarcado, d.motivo_liberacao = True, False, ev.motivo
        elif ev.acao == DESMARCAR:
            d.desmarcado, d.liberado, d.motivo_desmarcar = True, False, ev.motivo
        elif ev.acao == EDITAR:
            for k, v in ev.antes.items():
                d.antes.setdefault(k, v)          # o ORIGINAL do ERP, não o da edição anterior
            d.edicoes.update({k: v for k, v in ev.campos.items() if k in CAMPOS_EDITAVEIS})
            d.motivo_edicao = ev.motivo
            d.corrigir_no_erp = d.corrigir_no_erp or ev.corrigir_no_erp
        else:
            d.removido = True
        d.quem_nome, d.quando = ev.quem_nome, ev.quando
    return estado


def _decimal_ou_none(valor) -> Decimal | None:
    return None if valor in (None, "") else Decimal(str(valor))


@dataclass(frozen=True)
class PagamentoAMao:
    """Uma linha de `pagamento_a_mao`. Valores em Decimal (a nuvem manda texto)."""

    id: int
    conta: str
    valor: Decimal
    descricao: str
    motivo: str
    favorecido: str = ""
    tipo: str = ""
    dados: str = ""
    lancamento_id: str = ""
    centro_custo: str = ""
    nf: str = ""
    oc: str = ""
    valor_em_aberto: Decimal | None = None
    quem_nome: str = ""
    quando: str = ""

    @property
    def alvo(self) -> str:
        return f"{PREFIXO_A_MAO}{self.id}"

    @classmethod
    def de_linha(cls, linha: dict) -> "PagamentoAMao":
        return cls(id=int(linha["id"]), conta=str(linha["conta"]),
                   valor=Decimal(str(linha["valor"])), descricao=str(linha.get("descricao") or ""),
                   motivo=str(linha.get("motivo") or ""), favorecido=str(linha.get("favorecido") or ""),
                   tipo=str(linha.get("tipo") or ""), dados=str(linha.get("dados") or ""),
                   lancamento_id=str(linha.get("lancamento_id") or ""),
                   centro_custo=str(linha.get("centro_custo") or ""), nf=str(linha.get("nf") or ""),
                   oc=str(linha.get("oc") or ""),
                   valor_em_aberto=_decimal_ou_none(linha.get("valor_em_aberto")),
                   quem_nome=str(linha.get("quem_nome") or ""), quando=str(linha.get("quando") or ""))


@dataclass(frozen=True)
class Conferencia:
    """Tudo o que a nuvem guarda do passo 2 de um dia. Imutável: `com_*`
    devolve outra, com a linha gravada acrescentada."""

    eventos: tuple = ()
    pagamentos_a_mao: tuple = ()

    @property
    def decisoes(self) -> dict[str, Decisao]:
        return dobrar(self.eventos)

    @property
    def a_mao(self) -> list[PagamentoAMao]:
        """Os pagamentos à mão que valem (sem os removidos)."""
        d = self.decisoes
        return [p for p in self.pagamentos_a_mao
                if not (d.get(p.alvo) and d[p.alvo].removido)]

    @classmethod
    def da_nuvem(cls, decisoes, a_mao) -> "Conferencia":
        return cls(tuple(Evento.de_linha(x) for x in decisoes or ()),
                   tuple(PagamentoAMao.de_linha(x) for x in a_mao or ()))

    def com_evento(self, linha: dict) -> "Conferencia":
        return Conferencia((*self.eventos, Evento.de_linha(linha)), self.pagamentos_a_mao)

    def com_a_mao(self, linha: dict) -> "Conferencia":
        return Conferencia(self.eventos, (*self.pagamentos_a_mao, PagamentoAMao.de_linha(linha)))


def pode_liberar(linha) -> bool:
    """Não apto (qualquer motivo: decisão do dono), ou já enviado (entra mas
    nasce desmarcado). O que já vai sair não tem o que liberar."""
    return linha.secao == confirmacao.NAO_APTO or (
        linha.marcavel and not confirmacao.marcada_de_inicio(linha))


def pede_certeza(linha) -> str:
    """A pergunta a mais ("tem certeza?") antes de liberar, ou "".
    Pedem: o já enviado (não rejeitado) e o favorecido fora dos Contatos."""
    enviado = getattr(linha.candidato, "ja_enviado", "")
    if enviado and not linha.envio_rejeitado:
        return (f"Este pagamento JÁ SAIU numa remessa ({enviado}). Liberar é gerar de "
                "novo — o banco pode pagar duas vezes.\n\nTem certeza?")
    if _FORA_DOS_CONTATOS in (linha.situacao or ""):
        return ("O favorecido não está no cadastro de Contatos do ERP: a remessa não "
                "tem o documento dele.\n\nTem certeza?")
    return ""


def validar_motivo(motivo: str) -> str:
    """"" se o motivo serve; senão, o recado."""
    m = (motivo or "").strip()
    if len(m) < MOTIVO_MINIMO:
        return "Escreva um motivo curto (3 letras ou mais)."
    if len(m) > TEXTO_MAXIMO:
        return f"O motivo passa de {TEXTO_MAXIMO} caracteres."
    return ""


def _validar_texto(nome: str, texto) -> str:
    t = str(texto or "").strip()
    if not MOTIVO_MINIMO <= len(t) <= TEXTO_MAXIMO or t.startswith("="):
        return (f"A {nome} tem de ter de {MOTIVO_MINIMO} a {TEXTO_MAXIMO} caracteres "
                "(e não começar com \"=\").")
    return ""


def _validar_forma(tipo, dados: str) -> str:
    if tipo not in TIPOS:
        return f"Forma de pagar desconhecida: {tipo or '(vazia)'}."
    if not dados:
        return "Escreva o dado da forma de pagar (chave, linha digitável ou conta)."
    if len(dados) > DADOS_MAXIMO:
        return f"O dado da forma de pagar passa de {DADOS_MAXIMO} caracteres."
    if tipo == "Pix":
        chave = regras.tipo_de_chave_pix(dados)
        if chave == regras.CHAVE_COPIA_COLA:
            return ("Pix copia-e-cola não vai pela remessa: escreva a chave, "
                    "ou pague à mão.")
        # Onze dígitos crus: CPF ou celular, e quem digita é quem sabe. Mais
        # estrito que `tipo_de_chave_pix` (que adivinha pelo DV e pelo DDD) de
        # propósito: quem escolhe o tipo aqui escolhe para quem o dinheiro vai.
        if not chave or _ONZE_CRUS.fullmatch(re.sub(r"\s+", "", dados)):
            return ("A chave Pix não diz o tipo (CPF ou celular têm 11 dígitos): escreva "
                    "\"PIX CPF …\", \"PIX CELULAR …\", o e-mail ou a chave aleatória.")
    if tipo == "Boleto" and not ocr_boleto.codigo_de_barras(dados):
        return "A linha digitável não fecha nos dígitos verificadores."
    if tipo == "Transferência" and len(dados) < 8:
        return "Escreva banco, agência e conta da transferência."
    return ""


def validar_edicao(campos: dict, motivo: str) -> str:
    """"" se a edição pode ir à nuvem; senão, o recado. A forma de pagar muda
    inteira (tipo + dado); o reembolso, nome + documento que fecha no DV."""
    erro = validar_motivo(motivo)
    if erro:
        return erro
    if not campos:
        return "Nada mudou."
    fora = set(campos) - set(CAMPOS_EDITAVEIS)
    if fora:
        return "Campo que não se edita aqui: " + ", ".join(sorted(fora))
    if ("tipo" in campos) != ("dados" in campos):
        return "A forma de pagar muda junto: o tipo e o dado."
    if "tipo" in campos:
        erro = _validar_forma(campos["tipo"], str(campos.get("dados") or "").strip())
        if erro:
            return erro
    if "reembolso_nome" in campos or "reembolso_documento" in campos:
        nome = str(campos.get("reembolso_nome") or "").strip()
        if not nome:
            return "Falta o nome de quem recebe o reembolso."
        if len(nome) > TEXTO_MAXIMO:
            return f"O nome de quem recebe o reembolso passa de {TEXTO_MAXIMO} caracteres."
        if not regras.documento_valido(str(campos.get("reembolso_documento") or "")):
            return "O CPF/CNPJ de quem recebe o reembolso não fecha no dígito verificador."
    if "descricao" in campos:
        erro = _validar_texto("descrição", campos["descricao"])
        if erro:
            return erro
    return ""


def _cc_na_descricao(cc: str, ndesc: str) -> bool:
    """O teste do `matcher._features`: algum centro de custo (6+ caracteres)
    dentro da descrição, ou o "QD x LT y" da descrição dentro de um deles."""
    nomes = [matcher._com_hifen(matcher._norm(x)) for x in cc.split("|") if x.strip()]
    if any(len(n) >= 6 and n in ndesc for n in nomes):
        return True
    mq = re.search(r"QD\s*([0-9A-Z]+)\s+LT\s*([0-9A-Z\-]+)", ndesc)
    if mq:
        pat = "QD " + mq.group(1) + " LT " + mq.group(2)
        return any(pat in n for n in nomes)
    return False


def aviso_de_casamento(registro: dict, conta: str) -> str:
    """O que o Anexar vai deixar de achar com ESTA descrição — com as mesmas
    funções dele (`anexar/matcher.py`): centro de custo no texto e o número do
    documento como último número (ou rotulado NF/OC). "" = casa como hoje."""
    texto = html_pagamentos.descricao_para_colar(registro, conta)
    ndesc = matcher._com_hifen(matcher._norm(texto))
    avisos = []
    cc = str(registro.get("centro_custo") or "")
    if cc.strip() and not _cc_na_descricao(cc, ndesc):
        avisos.append("o centro de custo não está na descrição")
    numeros = set()
    for doc in (registro.get("nf"), registro.get("oc_da_descricao")):
        numeros |= matcher._numeros_do_documento(str(doc or ""))
    if numeros:
        cents = html_pagamentos.centavos(registro.get("valor"))
        achados = (matcher._numeros_soltos(texto, cents)
                   | {matcher._sem_zeros(n) for n in matcher._ocnf_rotulados(texto)})
        if not numeros & achados:
            avisos.append("o número do documento não é o último número da descrição")
    if not avisos:
        return ""
    return ("O Anexar casa o comprovante pelo centro de custo e pelo último número da "
            "descrição: " + "; ".join(avisos) + f".\nVai ao banco: {texto}")


def _dinheiro(valor: Decimal) -> str:
    return str(valor.quantize(CENTAVO))


def nova_a_mao(*, conta, valor_texto, descricao, motivo, contas, lido=None,
               tipo="", dados="", favorecido="") -> tuple[dict | None, str]:
    """A linha de `pagamento_a_mao` a gravar e "", ou (None, recado).
    Com `lido` (o lançamento do link), não paga título já PAGO, de outra
    conta, nem mais que o em aberto, e herda CC/NF/OC para o Anexar casar."""
    if conta not in contas:
        return None, "Escolha a conta na lista."
    try:
        valor = ler_valor_editado(valor_texto)
    except ValueError as e:
        return None, str(e)
    if valor <= 0:
        return None, "O valor tem de ser maior que zero."
    erro = _validar_texto("descrição", descricao) or validar_motivo(motivo)
    if not erro and (tipo or dados):
        erro = _validar_forma(tipo, (dados or "").strip())
    favorecido = (favorecido or "").strip()
    if not erro and len(favorecido) > TEXTO_MAXIMO:
        erro = f"O favorecido passa de {TEXTO_MAXIMO} caracteres."
    if erro:
        return None, erro
    linha = {"conta": conta, "valor": _dinheiro(valor), "descricao": descricao.strip(),
             "motivo": motivo.strip(), "favorecido": favorecido,
             "tipo": tipo, "dados": (dados or "").strip()}
    if lido is not None:
        if not lido.id:
            return None, "O link não trouxe o lançamento."
        if lido.pago:
            return None, "Este lançamento já está PAGO no ERP."
        if lido.conta and lido.conta != conta:
            return None, f"O lançamento é da conta {lido.conta}, não de {conta}."
        if lido.em_aberto is not None and valor > lido.em_aberto:
            return None, f"O valor passa do que está em aberto no lançamento ({brl(lido.em_aberto)})."
        # O que vem do ERP cabe no teto do banco (200), para a nuvem não recusar.
        linha.update(lancamento_id=lido.id[:TEXTO_MAXIMO],
                     centro_custo=lido.centro_custo[:TEXTO_MAXIMO],
                     nf=lido.nf[:TEXTO_MAXIMO], oc=lido.oc[:TEXTO_MAXIMO],
                     favorecido=favorecido or lido.favorecido[:TEXTO_MAXIMO],
                     valor_em_aberto=None if lido.em_aberto is None else _dinheiro(lido.em_aberto))
    return linha, ""
