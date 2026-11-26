# -*- coding: utf-8 -*-
"""O que o robô faz com um lote APROVADO: paga item a item, retoma depois de
queda sem pagar duas vezes, e anexa + dá baixa só com o pagamento REALIZADO.

Sem rede própria: o Sicoob, o ERP e o livro (a nuvem) entram como portas, e o
teste passa dublês. Regras da spec de 26/11/2026:
- pagar NUNCA se repete sozinho; buscar comprovante e anexar podem;
- a soma do que saiu nunca passa do total aprovado;
- antes de pagar, o ERP é relido (em aberto, mesmo valor, sem comprovante);
- toda chave de pagamento é gravada no livro ANTES da chamada que paga.
"""
from __future__ import annotations

import unicodedata
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Callable, Protocol

from . import comprovante as cp
from . import lote as lt
from .sicoob import ContaApi, ErroSicoob, Sicoob, chave_de_idempotencia

INICIADO, EM_PROCESSAMENTO, REALIZADO = "iniciado", "em_processamento", "realizado"
NAO_PAGO, FALTA_ANEXAR, CONCLUIDO = "nao_pago", "falta_anexar", "concluido"
#: Estados em que o dinheiro saiu ou pode ter saído: contam no total.
SAIU_OU_PODE_TER_SAIDO = (INICIADO, EM_PROCESSAMENTO, REALIZADO, FALTA_ANEXAR, CONCLUIDO)
FINAIS = (NAO_PAGO, CONCLUIDO)


@dataclass(frozen=True)
class Evento:
    ordem: int
    estado: str
    detalhe: str = ""
    chave: str = ""          # chave de idempotência (boleto) ou endToEndId (Pix)


@dataclass(frozen=True)
class Titulo:
    aberto: bool
    valor: Decimal
    tem_comprovante: bool | None   # None = o ERP não respondeu: nunca vale como "não tem"


class Erp(Protocol):
    def titulo(self, titulo_id: str) -> Titulo | None: ...
    def anexar(self, titulo_id: str, caminho: Path) -> bool: ...
    def baixar(self, titulo_id: str, valor: Decimal, dia: date, conta: str) -> bool: ...


class Livro(Protocol):
    def eventos(self) -> list[Evento]: ...
    def gravar(self, evento: Evento) -> None: ...


@dataclass
class Portas:
    sicoob: Sicoob
    erp: Erp
    livro: Livro
    contas: dict[str, ContaApi]         # nome da conta no ERP -> conta no Sicoob
    pasta: Path                         # onde os PDFs dos comprovantes ficam
    hoje: date
    parar: Callable[[], bool] = lambda: False
    novo_uuid: Callable[[], str] = field(default=lambda: str(_uuid.uuid4()))


def _sem_acento(t) -> str:
    return unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().upper()


def estado_pix(resposta: dict) -> str:
    """Só NAO_REALIZADO é "não pago". Estado desconhecido ou ausente fica em
    processamento: o robô volta a perguntar, e nada é dado como não pago (o que
    mandaria alguém pagar pelo HTML um Pix que pode ter saído)."""
    e = _sem_acento(resposta.get("estado"))
    if e == "REALIZADO":
        return REALIZADO
    if e == "NAO_REALIZADO":
        return NAO_PAGO
    return EM_PROCESSAMENTO


def ultimos(eventos: list[Evento]) -> dict[int, Evento]:
    u: dict[int, Evento] = {}
    for e in eventos:
        u[e.ordem] = e
    return u


def chave_do_item(eventos: list[Evento], ordem: int) -> str:
    for e in eventos:
        if e.ordem == ordem and e.chave:
            return e.chave
    return ""


def ja_comprometido(itens: list[lt.ItemLote], eventos: list[Evento]) -> Decimal:
    u = ultimos(eventos)
    return sum((i.valor for i in itens
                if i.ordem in u and u[i.ordem].estado in SAIU_OU_PODE_TER_SAIDO),
               Decimal("0.00"))


#: Única frase do banco que, DEPOIS de iniciado, vale como "não saiu": o Pix
#: NAO_REALIZADO. Tudo o mais que não se resolve fica EM_PROCESSAMENTO (conta no
#: total, não anexa, pergunta de novo) — revisão da Task 5, 26/11/2026.
CONFERIR = "conferir no banco antes de qualquer pagamento à mão"


def _junto(*partes) -> str:
    return " — ".join(p for p in partes if p)


def estado_boleto(resposta) -> str:
    """Só um comprovante EFETIVADO/PAGO/REALIZADO vale como pago. Nenhuma
    situação do comprovante vira "não pago" sozinha: o nome das recusas não está
    documentado, e um engano aqui mandaria pagar de novo à mão."""
    if isinstance(resposta, list):            # o endpoint tem nome no plural
        resposta = next((r for r in resposta if isinstance(r, dict)), {})
    s = _sem_acento((resposta or {}).get("situacaoPagamento") if isinstance(resposta, dict) else "")
    return REALIZADO if s in ("EFETIVADO", "PAGO", "REALIZADO") else EM_PROCESSAMENTO


class Executor:
    def __init__(self, itens: list[lt.ItemLote], total_aprovado: Decimal, portas: Portas):
        self.itens = sorted(itens, key=lambda i: i.ordem)
        self.total = Decimal(total_aprovado)
        self.p = portas

    def _gravar(self, item, estado, detalhe="", chave=""):
        ev = Evento(item.ordem, estado, detalhe[:500], chave)
        ult = ultimos(self.p.livro.eventos()).get(item.ordem)
        if ult == ev:
            return ult                  # nada mudou: não enche o livro a cada rodada
        self.p.livro.gravar(ev)
        return ev

    # ------------------------------------------------------------ o ciclo
    def rodar(self) -> None:
        for item in self.itens:
            if self.p.parar():
                return
            eventos = self.p.livro.eventos()
            ult = ultimos(eventos).get(item.ordem)
            if ult and ult.estado in FINAIS:
                continue
            if ult and ult.estado in (INICIADO, EM_PROCESSAMENTO):
                ult = self._retomar(item, chave_do_item(eventos, item.ordem))
            elif ult is None:
                ult = self._pagar(item, eventos)
            if ult.estado in (REALIZADO, FALTA_ANEXAR):
                chave = chave_do_item(self.p.livro.eventos(), item.ordem)
                try:
                    self._anexar(item, chave)
                except Exception as e:  # anexar não move dinheiro: segue o lote
                    self._gravar(item, FALTA_ANEXAR, f"anexo falhou: {e!r}", chave)

    # ------------------------------------------------------------- pagar
    def _pagar(self, item: lt.ItemLote, eventos: list[Evento]) -> Evento:
        if ja_comprometido(self.itens, eventos) + item.valor > self.total:
            return self._gravar(item, NAO_PAGO, "passaria do total aprovado")
        conta = self.p.contas.get(item.conta)
        if conta is None:
            return self._gravar(item, NAO_PAGO, "conta sem cadastro da API no servidor")
        try:
            t = self.p.erp.titulo(item.titulo)
        except Exception as e:          # antes de iniciar: não saiu dinheiro nenhum
            return self._gravar(item, NAO_PAGO, f"ERP não respondeu: {e!r}")
        if t is None or t.tem_comprovante is None:
            return self._gravar(item, NAO_PAGO, "ERP não confirmou o título")
        try:
            mesmo_valor = Decimal(str(t.valor)) == item.valor
        except ArithmeticError:
            return self._gravar(item, NAO_PAGO, f"ERP devolveu valor ilegível: {t.valor!r}")
        if not t.aberto or t.tem_comprovante or not mesmo_valor:
            return self._gravar(item, NAO_PAGO, "ERP mudou")
        try:
            if item.tipo == lt.PIX_CHAVE:
                return self._pix_chave(item)
            if item.tipo == lt.PIX_QR:
                return self._pix_qr(item)
            if item.tipo == lt.BOLETO:
                return self._boleto(item, conta)
            if item.tipo == lt.CONVENIO:
                return self._convenio(item, conta)
        except (ErroSicoob, ArithmeticError, ValueError, TypeError, OSError) as e:
            # Erro DEPOIS de gravar INICIADO é ambíguo: o dinheiro pode ter
            # saído. Quem decide é a retomada, que pergunta ao banco e, sem
            # resposta, deixa EM_PROCESSAMENTO. Erro antes disso = não pago.
            ult = ultimos(self.p.livro.eventos()).get(item.ordem)
            if ult and ult.estado == INICIADO:
                return self._retomar(item, ult.chave, f"erro ao pagar: {e}")
            return self._gravar(item, NAO_PAGO, f"banco: {e}")
        return self._gravar(item, NAO_PAGO, f"tipo {item.tipo} desconhecido")

    def _pix_chave(self, item):
        ini = self.p.sicoob.pix_iniciar(item.dados)
        e2e = str(ini.get("endToEndId") or "")
        doc = "".join(ch for ch in str((ini.get("proprietario") or {}).get("identificador") or "")
                      if ch.isdigit())
        if not e2e:
            return self._gravar(item, NAO_PAGO, "banco não devolveu o endToEndId")
        if not doc or doc != item.documento_esperado:
            return self._gravar(item, NAO_PAGO, "chave de outra pessoa", e2e)
        self._gravar(item, INICIADO, "", e2e)
        r = self.p.sicoob.pix_confirmar(e2e, item.valor, item.descricao)
        return self._gravar(item, estado_pix(r), str(r.get("detalheRejeicao") or ""), e2e)

    def _pix_qr(self, item):
        # O QR não aceita código nosso: sem o endToEndId da resposta, uma queda
        # aqui só se resolve olhando o banco (EM_PROCESSAMENTO, nunca NAO_PAGO).
        self._gravar(item, INICIADO, "qrcode")
        r = self.p.sicoob.pix_qrcode(item.dados, item.valor, item.documento_esperado)
        e2e = str(r.get("endToEndId") or "")
        est = estado_pix(r)
        if est == NAO_PAGO and not e2e:
            est = EM_PROCESSAMENTO      # "não realizado" sem código para conferir: olhar o banco
        return self._gravar(item, est, str(r.get("detalheRejeicao") or "") if e2e else CONFERIR, e2e)

    def _boleto(self, item, conta):
        c = self.p.sicoob.boleto_consultar(item.dados, conta)
        if c.get("bloquearPagamento"):
            return self._gravar(item, NAO_PAGO, f"banco bloqueia: {c.get('mensagemBloqueioPagamento') or ''}")
        valor = Decimal(str(c.get("valorPagamento") if c.get("valorPagamento") is not None
                            else c.get("valorBoleto") or "0")).quantize(Decimal("0.01"))
        if valor != item.valor:
            return self._gravar(item, NAO_PAGO, f"boleto diferente: banco cobra {valor}")
        docs = {"".join(ch for ch in str(c.get(k) or "") if ch.isdigit())
                for k in ("numeroCpfCnpjBeneficiario", "numeroCpfCnpjBeneficiarioFinal")}
        if item.documento_esperado and item.documento_esperado not in docs:
            return self._gravar(item, NAO_PAGO, "boleto diferente: beneficiário não é o esperado")
        chave = chave_de_idempotencia(conta, self.p.novo_uuid())
        self._gravar(item, INICIADO, "", chave)
        self.p.sicoob.boleto_pagar(item.dados, conta, c, item.valor, item.descricao,
                                   chave, self.p.hoje.isoformat())
        # Pago só com o comprovante EFETIVADO; sem ele, a próxima rodada pergunta.
        return self._retomar(item, chave)

    def _convenio(self, item, conta):
        c = self.p.sicoob.convenio_consultar(item.dados, self.p.hoje.isoformat())
        cobra = Decimal(str(c.get("valorTotal") if c.get("valorTotal") is not None
                            else "0")).quantize(Decimal("0.01"))
        if cobra != item.valor:
            return self._gravar(item, NAO_PAGO, f"convênio diferente: banco cobra {cobra}")
        self._gravar(item, INICIADO, "convenio")
        r = self.p.sicoob.convenio_pagar(item.dados, conta, item.valor,
                                         self.p.hoje.isoformat(), item.ordem)
        nsu = str((r.get("arrecadacao") or {}).get("nsu") or "")
        try:
            caminho = str(cp.salvar_bruto(self.p.pasta, item, "convenio", r))
        except OSError as e:            # pagou: não perder isso por causa do disco
            caminho = f"comprovante não gravado no disco: {e!r}"
        if not nsu:
            return self._gravar(item, EM_PROCESSAMENTO, CONFERIR + " (convênio sem NSU)")
        return self._gravar(item, REALIZADO, caminho, nsu)

    # ----------------------------------------------------------- retomar
    def _retomar(self, item, chave, motivo: str = "") -> Evento:
        """Caiu no meio (ou ainda não se sabe): pergunta ao banco pelo código
        gravado. Nunca paga de novo, e nunca conclui "não pago" sem o banco dizer."""
        try:
            if item.tipo in (lt.PIX_CHAVE, lt.PIX_QR) and chave:
                est = estado_pix(self.p.sicoob.pix_consultar(chave))
                if est == NAO_PAGO:
                    return self._gravar(item, NAO_PAGO, "o banco diz não realizado", chave)
                return self._gravar(item, est, "" if est == REALIZADO else CONFERIR, chave)
            if item.tipo == lt.BOLETO and chave:
                est = estado_boleto(self.p.sicoob.boleto_comprovante(chave))
                return self._gravar(item, est, "" if est == REALIZADO else CONFERIR, chave)
            if item.tipo == lt.CONVENIO:
                b = cp.ler_bruto(self.p.pasta, item, "convenio") or {}
                nsu = str((b.get("arrecadacao") or {}).get("nsu") or "")
                if nsu:
                    return self._gravar(item, REALIZADO, "", nsu)
        except ErroSicoob as e:
            onde = f"HTTP {e.status}" if e.status else "sem resposta"
            return self._gravar(item, EM_PROCESSAMENTO, _junto(CONFERIR, f"consulta falhou: {onde}", motivo), chave)
        except Exception as e:          # resposta num formato inesperado: perguntar de novo
            return self._gravar(item, EM_PROCESSAMENTO, _junto(CONFERIR, f"consulta ilegível: {e!r}", motivo), chave)
        ult = ultimos(self.p.livro.eventos()).get(item.ordem)
        if not motivo and ult is not None and ult.estado == EM_PROCESSAMENTO:
            return ult                  # nada novo: fica o registro que já diz o motivo
        return self._gravar(item, EM_PROCESSAMENTO, _junto(CONFERIR, motivo), chave)

    # ----------------------------------------------------------- anexar
    def _anexar(self, item, chave) -> Evento:
        # Relê o ERP ANTES: anexo/baixa de uma rodada que caiu podem já ter entrado.
        t = self.p.erp.titulo(item.titulo)
        if t is None or t.tem_comprovante is None:
            # "não sei" do ERP nunca vale como "não tem": não anexa nem baixa às cegas
            return self._gravar(item, FALTA_ANEXAR, "ERP não respondeu", chave)
        if not t.aberto and t.tem_comprovante:
            return self._gravar(item, CONCLUIDO, "já estava anexado e baixado no ERP", chave)
        try:
            dados = self._comprovante(item, chave)
        except ErroSicoob as e:
            return self._gravar(item, FALTA_ANEXAR, f"comprovante: {e}", chave)
        if dados is None:
            if item.tipo == lt.CONVENIO:
                return self._gravar(item, FALTA_ANEXAR,
                                    f"comprovante do convênio não está no disco; pedir 2ª via (NSU {chave})", chave)
            return self._gravar(item, FALTA_ANEXAR, "comprovante ainda não disponível", chave)
        caminho = cp.gerar_pdf(self.p.pasta, item, dados, self.p.hoje)
        if not t.tem_comprovante:
            if not self.p.erp.anexar(item.titulo, caminho):
                return self._gravar(item, FALTA_ANEXAR, "ERP recusou o anexo", chave)
        if t.aberto:                    # título já fechado (baixa à mão): nunca baixar de novo
            if not self.p.erp.baixar(item.titulo, item.valor, self.p.hoje, item.conta):
                return self._gravar(item, FALTA_ANEXAR, "ERP recusou a baixa", chave)
        t = self.p.erp.titulo(item.titulo)
        if t is None or t.aberto or t.tem_comprovante is not True:
            return self._gravar(item, FALTA_ANEXAR, "ERP não confirmou anexo e baixa", chave)
        return self._gravar(item, CONCLUIDO, str(caminho), chave)

    def _comprovante(self, item, chave) -> dict | None:
        if item.tipo == lt.BOLETO:
            r = self.p.sicoob.boleto_comprovante(chave)
            return r if estado_boleto(r) == REALIZADO else None
        if item.tipo in (lt.PIX_CHAVE, lt.PIX_QR):
            if not chave:
                return None
            r = self.p.sicoob.pix_consultar(chave)
            return r if estado_pix(r) == REALIZADO else None
        if item.tipo == lt.CONVENIO:
            return cp.ler_bruto(self.p.pasta, item, "convenio")
        return None
