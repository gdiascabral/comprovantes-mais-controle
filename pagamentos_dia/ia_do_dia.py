# -*- coding: utf-8 -*-
"""Leitura por IA no HTML dos pagamentos (spec de 19/11/2026, parte 3, fase 1).

Liga o módulo puro `leitura_ia` à leitura do dia:

1. `baixar_textos` guarda os bytes dos anexos que não têm camada de texto
   (`brutos`). Nada é pedido à IA lá.
2. `selecionar` aplica as condições da spec, por título a pagar: imagem ou PDF
   sem camada de texto; o OCR local não achou linha digitável válida nem o valor
   do lançamento; não é comprovante de pagamento nem aviso "PAGAR PARA"; tipo
   de arquivo que a API aceita.
3. `ler_candidatos` lê cada anexo UMA vez (cache em `leituras_ia.json`), com
   teto por geração, e devolve `{downloadUrl: entrada}`.
4. `leitura_do_item` (chamada por `relatorio.montar_registros`) confere a
   leitura contra o lançamento e devolve o que vai em `registro["leitura_ia"]`.
   `nivel.py` e os dois HTML só LEEM esse dicionário.

Falha fechada: erro, prazo, recusa ou resposta fora do esquema viram uma
entrada `ok=False` — a linha sai "Não li (IA não respondeu)", nunca apta. Teto
estourado: o anexo não é lido e a linha segue "Não li", como antes da IA.
Nenhum dado do ERP vai para a API: só a imagem/PDF do anexo e a instrução.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from . import leitura_ia as li
from . import ocr_boleto, relatorio

#: Decisão 3: teto de leituras PELA API por geração (cache não conta).
TETO_PADRAO = 60
#: Medido em 25/11/2026 (38 anexos): US$ 0,02 por leitura. Estimativa de painel,
#: não fatura.
CUSTO_POR_LEITURA_USD = Decimal("0.02")
ARQUIVO_CACHE = "leituras_ia.json"

FALHOU = "IA não respondeu"
#: Estados em que a IA deu um valor para comparar (os outros viram "Não li").
USAVEIS = (li.BATE, li.TOTAL_BATE_SOMA_NAO_FECHA, li.SEM_SEGUNDA_PROVA, li.DIVERGE)

_COMPROVANTE = re.compile(r"comprovante", re.I)


# ------------------------------------------------------------- a sessão da IA
class IaDoDia:
    """O cliente, o cache e os contadores de UMA geração."""

    def __init__(self, cliente, cache: li.CacheLeituras, *, teto: int = TETO_PADRAO,
                 modelo: str = li.MODELO, agora=datetime.now):
        self.cliente, self.cache, self.teto = cliente, cache, teto
        self.modelo, self._agora = modelo, agora
        self.feitas = self.do_cache = self.falhas = self.acima_do_teto = 0
        self.tokens_entrada = self.tokens_saida = 0

    @property
    def custo_estimado_usd(self) -> Decimal:
        return CUSTO_POR_LEITURA_USD * self.feitas

    def resumo(self) -> str:
        partes = [f"{self.feitas} lida(s) pela IA", f"{self.do_cache} do cache",
                  f"{self.falhas} falha(s)"]
        if self.acima_do_teto:
            partes.append(f"{self.acima_do_teto} acima do teto de {self.teto} (ficam 'Não li')")
        return (f"Leitura por IA: {', '.join(partes)}; custo estimado US$ "
                f"{self.custo_estimado_usd:.2f} ({self.tokens_entrada} tokens de entrada, "
                f"{self.tokens_saida} de saída).")

    def ler(self, chave: str, dados: bytes, media_type: str) -> dict | None:
        """`{"ok", "leitura", "origem"}` ou `{"ok": False, "erro"}`; None quando
        o teto de leituras pela API já foi usado (o anexo não é lido)."""
        guardada = self.cache.obter(chave)
        if guardada is not None:
            self.do_cache += 1
            return {"ok": True, "leitura": guardada, "origem": "cache"}
        if self.feitas >= self.teto:
            self.acima_do_teto += 1
            return None
        self.feitas += 1                      # conta a tentativa: o pedido já custou
        try:
            leitura, uso = li.pedir_leitura(self.cliente, dados, media_type, modelo=self.modelo)
        except li.LeituraFalhou as e:
            self.falhas += 1
            return {"ok": False, "erro": str(e)}
        except Exception as e:                # noqa: BLE001 — falha fechada, nunca apta
            self.falhas += 1
            return {"ok": False, "erro": f"erro inesperado ({type(e).__name__})"}
        self.tokens_entrada += uso.entrada
        self.tokens_saida += uso.saida
        try:
            self.cache.guardar(chave, leitura, modelo=self.modelo,
                               quando=self._agora().strftime("%Y-%m-%d %H:%M"))
        except OSError:
            pass                              # o cache só economiza
        return {"ok": True, "leitura": leitura, "origem": "api"}


def da_maquina(pasta=None, *, log=print, teto: int = TETO_PADRAO) -> IaDoDia | None:
    """A IA desta máquina, ou None (sem chave: função desligada, tudo como antes)."""
    from . import chave_ia
    from .cliente_anthropic import ClienteAnthropic
    chave = chave_ia.carregar(pasta)
    if not chave:
        return None
    if pasta is None:
        import util
        pasta = util.pasta_base()
    log("Leitura por IA ligada: anexos escritos à mão serão lidos (Olhe, nunca Pode pagar).")
    return IaDoDia(ClienteAnthropic(chave), li.CacheLeituras(Path(pasta) / ARQUIVO_CACHE),
                   teto=teto)


# ------------------------------------------------------------- quais anexos vão
def _nome_com_extensao(f: dict) -> str:
    nome = str(f.get("filename") or "")
    ext = str(f.get("extension") or "").strip().lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    return nome if li.media_type_do_nome(nome) else nome + ext


def chave_do_anexo(f: dict, dados: bytes) -> str:
    """id + tamanho + data de alteração (decisão da spec); nunca a URL. O
    tamanho é o dos bytes baixados; sem data na lista do ERP entra o hash dos
    bytes, o que também faz o anexo trocado ser anexo novo."""
    ident = f.get("id") or f.get("fileId") or f.get("filename") or "?"
    data = (f.get("updatedAt") or f.get("modifiedAt") or f.get("lastModified")
            or f.get("createdAt") or hashlib.sha256(dados).hexdigest()[:16])
    return li.CacheLeituras.chave(ident, len(dados), data)


def selecionar(a_pagar, anexos: dict, textos: dict, brutos: dict, *,
               ocr_imagem=ocr_boleto.texto_ocr_imagem) -> dict:
    """`{downloadUrl: {"arquivo", "dados", "media_type", "ids"}}` dos anexos que
    vão para a IA, com os ids dos lançamentos para os quais valem."""
    candidatos, ocr_das_fotos = {}, {}
    for item in a_pagar:
        valor = relatorio.valor_do_item(item)
        for f in anexos.get(str(item.get("tradePayableId"))) or []:
            url = f.get("downloadUrl") or ""
            if url not in brutos:
                continue
            dados, eh_pdf = brutos[url]
            media = li.media_type_do_nome(_nome_com_extensao(f))
            if (not media or not dados or _COMPROVANTE.search(relatorio._rotulo(f))
                    or relatorio._PAGAR_PARA.search(relatorio._rotulo(f))):
                continue
            if eh_pdf:
                texto = textos.get(url) or ""
            else:
                if url not in ocr_das_fotos:
                    ocr_das_fotos[url] = ocr_imagem(dados) or ""
                texto = ocr_das_fotos[url]
            if texto.strip() and (ocr_boleto.achar_linha_digitavel(texto, valor)
                                  or relatorio._valor_nos_textos(valor, [texto])):
                continue                       # o OCR local já achou o que a IA acharia
            c = candidatos.setdefault(url, {"arquivo": f, "dados": dados,
                                            "media_type": media, "ids": set()})
            c["ids"].add(str(item.get("id")))
    return candidatos


def ler_candidatos(ia: IaDoDia, candidatos: dict, *, log=print, cancelar=lambda: False) -> dict:
    """`{downloadUrl: {"ok", "leitura"|"erro", "origem", "ids"}}`; anexo acima do
    teto fica de fora."""
    saida = {}
    if candidatos:
        log(f"\nLeitura por IA: {len(candidatos)} anexo(s) escrito(s) à mão a ler...")
    for url, c in candidatos.items():
        if cancelar():
            break
        r = ia.ler(chave_do_anexo(c["arquivo"], c["dados"]), c["dados"], c["media_type"])
        if r is None:
            continue
        saida[url] = {**r, "ids": set(c["ids"])}
    if candidatos:
        log("  " + ia.resumo())
    return saida


# ------------------------------------------------------------- por lançamento
_GRAVIDADE = {li.DIVERGE: 0, FALHOU: 1, li.ILEGIVEL: 2, li.SEM_SEGUNDA_PROVA: 4,
              li.TOTAL_BATE_SOMA_NAO_FECHA: 5, li.BATE: 6}


def _escolher(resultados: list[dict]) -> dict:
    """Vários anexos do mesmo lançamento: divergência manda; depois falha;
    ilegível só vale se nada foi lido; senão a leitura mais forte."""
    usaveis = [r for r in resultados if r["estado"] in USAVEIS]
    for alvo in (li.DIVERGE, FALHOU):
        achou = [r for r in resultados if r["estado"] == alvo]
        if achou and (alvo == li.DIVERGE or not usaveis):
            return achou[0]
    if usaveis:
        return max(usaveis, key=lambda r: _GRAVIDADE[r["estado"]])
    return resultados[0]


def _endereco(item: dict, leitura: dict) -> str:
    quadra, lote = str(leitura.get("quadra") or "").strip(), str(leitura.get("lote") or "").strip()
    if not quadra and not lote:
        return ""
    texto = " ".join(p for p in (f"QD {quadra}" if quadra else "", f"LT {lote}" if lote else "") if p)
    try:
        return relatorio._conferir_endereco(item, [texto])[0]
    except Exception:                         # noqa: BLE001 — informação extra, nunca derruba a linha
        return ""


def _oc(leitura: dict, oc_do_lancamento: str) -> str:
    lida = re.sub(r"\D", "", str(leitura.get("ordem_de_compra") or "")).lstrip("0")
    if not lida:
        return ""
    esperada = re.sub(r"\D", "", str(oc_do_lancamento or "")).lstrip("0")
    if not esperada:
        return f"OC {lida} lida no papel (lançamento sem OC)"
    return f"OC {lida} ✓" if lida == esperada else f"OC DIVERGE: papel {lida} × lançamento {esperada}"


def leitura_do_item(item: dict, files, leituras_ia: dict, *, oc: str = "") -> dict | None:
    """O `registro["leitura_ia"]` do lançamento, ou None quando nenhum anexo dele
    foi para a IA. Só contém texto e números simples (vai para o HTML)."""
    id_ = str(item.get("id"))
    achados = []
    for f in files or ():
        e = (leituras_ia or {}).get(f.get("downloadUrl") or "")
        if e and id_ in e.get("ids", ()):
            achados.append(e)
    if not achados:
        return None
    valor = relatorio.valor_do_item(item)
    resultados = []
    for e in achados:
        if not e.get("ok"):
            resultados.append({"estado": FALHOU, "falhou": True, "provas": [],
                               "total_lido": "", "motivos": [f"{FALHOU}: {e.get('erro') or '?'}"],
                               "tipo_papel": "", "origem": "", "endereco": "", "oc": "",
                               "duvidas": []})
            continue
        leitura = e["leitura"]
        c = li.conferir(leitura, valor)
        resultados.append({
            "estado": c.estado, "falhou": False, "provas": list(c.provas),
            "total_lido": "" if c.total_lido is None else str(c.total_lido),
            "motivos": list(c.motivos), "tipo_papel": str(leitura.get("tipo_papel") or ""),
            "origem": e.get("origem") or "", "endereco": _endereco(item, leitura),
            "oc": _oc(leitura, oc), "duvidas": [str(d) for d in leitura.get("duvidas") or []]})
    return _escolher(resultados)

