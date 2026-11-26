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
from . import nivel, ocr_boleto, quem_recebe, relatorio

#: Decisão 3: teto de leituras PELA API por geração (cache não conta).
TETO_PADRAO = 60
#: Medido em 25/11/2026 (38 anexos): US$ 0,02 por leitura. Estimativa de painel,
#: não fatura.
CUSTO_POR_LEITURA_USD = Decimal("0.02")
ARQUIVO_CACHE = "leituras_ia.json"

FALHOU = "IA não respondeu"
NAO_LIDO = "não lido pela IA"
#: Limites da API (revisão de dinheiro de 25/11/2026): maior que isso nem se envia.
MAX_IMAGEM = 5 * 1024 * 1024
MAX_PDF = 30 * 1024 * 1024
MOTIVO_GRANDE = "arquivo grande demais para a IA"
#: Falhas de rede/prazo/HTTP seguidas que desligam a IA até o fim da geração.
FALHAS_SEGUIDAS = 3
#: Estados em que a IA deu um valor para comparar (os outros viram "Não li").
USAVEIS = (li.BATE, li.TOTAL_BATE_SOMA_NAO_FECHA, li.SEM_SEGUNDA_PROVA, li.DIVERGE)

_COMPROVANTE = re.compile(r"comprovante", re.I)


# ------------------------------------------------------------- a sessão da IA
class IaDoDia:
    """O cliente, o cache e os contadores de UMA geração."""

    def __init__(self, cliente, cache: li.CacheLeituras, *, teto: int = TETO_PADRAO,
                 modelo: str = li.MODELO, agora=datetime.now, anotar=None):
        self.cliente, self.cache, self.teto = cliente, cache, teto
        self.modelo, self._agora, self._anotar = modelo, agora, anotar
        self.feitas = self.do_cache = self.falhas = self.acima_do_teto = 0
        self.grandes = self.pulados_sem_ia = 0
        self.tokens_entrada = self.tokens_saida = 0
        self.falhas_seguidas, self.desligada = 0, False

    @property
    def custo_estimado_usd(self) -> Decimal:
        return CUSTO_POR_LEITURA_USD * self.feitas

    def resumo(self) -> str:
        partes = [f"{self.feitas} lida(s) pela IA", f"{self.do_cache} do cache",
                  f"{self.falhas} falha(s)"]
        if self.acima_do_teto:
            partes.append(f"{self.acima_do_teto} acima do teto de {self.teto} (ficam 'Não li')")
        if self.grandes:
            partes.append(f"{self.grandes} {MOTIVO_GRANDE}")
        if self.desligada:
            partes.append(f"IA desligada nesta geração após {FALHAS_SEGUIDAS} falhas "
                          f"({self.pulados_sem_ia} anexo(s) ficaram sem IA)")
        return (f"Leitura por IA: {', '.join(partes)}; custo estimado US$ "
                f"{self.custo_estimado_usd:.2f} ({self.tokens_entrada} tokens de entrada, "
                f"{self.tokens_saida} de saída).")

    def ler(self, chave: str, dados: bytes, media_type: str) -> dict:
        """`{"ok": True, "leitura", "origem"}`, `{"ok": False, "erro"}` (a IA
        falhou) ou `{"ok": False, "pulado": motivo}` (nem foi pedido: arquivo
        grande, teto usado ou IA desligada pela geração). Pulado não gasta teto."""
        limite = MAX_PDF if media_type == "application/pdf" else MAX_IMAGEM
        if len(dados) > limite:
            self.grandes += 1
            return {"ok": False, "pulado": MOTIVO_GRANDE}
        guardada = self.cache.obter(chave)
        if guardada is not None:
            self.do_cache += 1
            return {"ok": True, "leitura": guardada, "origem": "cache"}
        if self.desligada:
            self.pulados_sem_ia += 1
            return {"ok": False,
                    "pulado": f"IA desligada nesta geração após {FALHAS_SEGUIDAS} falhas"}
        if self.feitas >= self.teto:
            self.acima_do_teto += 1
            return {"ok": False, "pulado": f"acima do teto de {self.teto} leituras por geração"}
        self.feitas += 1                      # conta a tentativa: o pedido já custou
        try:
            leitura, uso = li.pedir_leitura(self.cliente, dados, media_type, modelo=self.modelo)
        except li.FalhaDeRede as e:
            self.falhas += 1
            self.falhas_seguidas += 1
            if self.falhas_seguidas >= FALHAS_SEGUIDAS:
                self.desligada = True
            return {"ok": False, "erro": str(e)}
        except li.LeituraFalhou as e:
            self.falhas += 1
            self.falhas_seguidas = 0          # a API respondeu; o problema é deste arquivo
            return {"ok": False, "erro": str(e)}
        except Exception as e:                # noqa: BLE001 — falha fechada, nunca apta
            self.falhas += 1
            return {"ok": False, "erro": f"erro inesperado ({type(e).__name__})"}
        self.falhas_seguidas = 0
        self.tokens_entrada += uso.entrada
        self.tokens_saida += uso.saida
        try:
            self.cache.guardar(chave, leitura, modelo=uso.modelo or self.modelo,
                               quando=self._agora().strftime("%Y-%m-%d %H:%M"))
        except OSError:
            pass                              # o cache só economiza
        return {"ok": True, "leitura": leitura, "origem": "api"}

    def anotar_na_atividade(self) -> None:
        """Uma linha na atividade do app, só com contagens (nada do anexo)."""
        if self._anotar:
            self._anotar(self.resumo(), {"feitas": self.feitas, "cache": self.do_cache,
                                         "falhas": self.falhas})


def _anotar_na_auditoria(resumo: str, numeros: dict) -> None:
    from nuvem import auditoria
    auditoria.registrar("Leitura por IA", resumo, aba="pag", resultado="ok", numeros=numeros)


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
                   teto=teto, anotar=_anotar_na_auditoria)


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


def _valor_provado_por(item: dict, files, textos: dict, qrs: dict) -> bool:
    """Algum anexo do lançamento já prova o valor: texto com o valor, linha
    digitável válida com ele, ou QR Pix com o campo 54 igual."""
    valor = relatorio.valor_do_item(item)
    alvo = Decimal(str(valor)).quantize(Decimal("0.01"))
    for f in files:
        url = f.get("downloadUrl") or ""
        texto = textos.get(url) or ""
        if texto.strip() and (relatorio._valor_nos_textos(valor, [texto])
                              or ocr_boleto.achar_linha_digitavel(texto, valor)):
            return True
        if any(nivel._valor_do_pix(c) == alvo for c in (qrs or {}).get(url) or ()):
            return True
    return False


def selecionar(a_pagar, anexos: dict, textos: dict, brutos: dict, *,
               ocr_imagem=ocr_boleto.texto_ocr_imagem, qr_pix=None) -> dict:
    """`{downloadUrl: {"arquivo", "dados", "media_type", "ids"}}` dos anexos que
    vão para a IA, com os ids dos lançamentos para os quais valem."""
    candidatos, ocr_das_fotos = {}, {}
    for item in a_pagar:
        valor = relatorio.valor_do_item(item)
        arquivos = anexos.get(str(item.get("tradePayableId"))) or []
        if _valor_provado_por(item, arquivos, textos, qr_pix):
            continue                           # outro anexo já prova o valor
        for f in arquivos:
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
            elif (textos.get(url) or "").strip():
                texto = textos[url]               # a leitura já fez o OCR da foto
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
    """`{downloadUrl: {"ok", "leitura"|"erro"|"pulado", "origem", "ids"}}`."""
    saida = {}
    if candidatos:
        log(f"\nLeitura por IA: {len(candidatos)} anexo(s) escrito(s) à mão a ler...")
    for url, c in candidatos.items():
        if cancelar():
            break
        chave = chave_do_anexo(c["arquivo"], c["dados"])
        r = ia.ler(chave, c["dados"], c["media_type"])
        # `papel`: o CONTEÚDO do arquivo. O mesmo PDF subido em dois títulos
        # tem ids (e `chave`) diferentes, e é o mesmo papel (26/11/2026).
        saida[url] = {**r, "ids": set(c["ids"]), "chave": chave,
                      "papel": hashlib.sha256(c["dados"]).hexdigest()}
    if candidatos:
        log("  " + ia.resumo())
        ia.anotar_na_atividade()
    return saida


def _centavos(valor) -> Decimal | None:
    try:
        return Decimal(str(valor)).quantize(Decimal("0.01"))
    except Exception:                         # noqa: BLE001
        return None


def anotar_papeis(leituras_ia: dict, a_pagar) -> None:
    """O MESMO papel (mesmo conteúdo do arquivo, `papel`, em uma ou várias URLs) lido para
    dois ou mais lançamentos a pagar: anota em cada entrada `papel_ids` (os ids)
    e `papel_valores` ({id: valor}) — é o "lançamento com o valor dividido para
    duas pessoas" (dono, 26/11/2026: OC de R$ X paga em duas partes, cada uma a
    um favorecido). Quem decide se a soma fecha é `leitura_do_item`.

    Falha fechada: id sem valor na lista a pagar desfaz o grupo (soma sem ele
    seria soma pela metade)."""
    valores = {str(i.get("id")): _centavos(relatorio.valor_do_item(i)) for i in a_pagar or ()}
    grupos: dict[str, set] = {}
    for e in (leituras_ia or {}).values():
        if e.get("papel"):
            grupos.setdefault(e["papel"], set()).update(e.get("ids") or ())
    for e in (leituras_ia or {}).values():
        ids = grupos.get(e.get("papel") or "", set())
        if len(ids) < 2 or any(valores.get(i) is None for i in ids):
            continue
        e["papel_ids"] = sorted(ids)
        e["papel_valores"] = {i: str(valores[i]) for i in ids}


def _soma_do_papel(e: dict) -> tuple[Decimal, list] | None:
    vals = [_centavos(v) for v in (e.get("papel_valores") or {}).values()]
    if len(vals) < 2 or any(v is None for v in vals):
        return None
    return sum(vals, Decimal("0")), vals


# ------------------------------------------------------------- por lançamento
_GRAVIDADE = {li.DIVERGE: 0, FALHOU: 1, NAO_LIDO: 1, li.ILEGIVEL: 2, li.SEM_SEGUNDA_PROVA: 4,
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
        forte = dict(max(usaveis, key=lambda r: _GRAVIDADE[r["estado"]]))
        # Papel emitido por outro: a divergência de quem recebe de qualquer
        # leitura utilizável vai junto, mesmo que a mais forte seja de outro anexo.
        ruim = next((r for r in usaveis if r.get("quem_recebe") == quem_recebe.DIVERGE), None)
        if ruim is not None:
            for c in ("emitente", "emitente_cnpj_cpf", "emitente_telefone", "quem_recebe",
                      "quem_recebe_por", "quem_recebe_motivo"):
                forte[c] = ruim[c]
        return forte
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


#: Papéis cujo emitente NÃO é quem recebe o dinheiro (comprovante de banco ou
#: de maquininha): ali "quem emitiu" não diz nada sobre o favorecido.
_SEM_EMITENTE = ("comprovante_de_pagamento", "comprovante_de_cartao")


def _quem_recebe(leitura: dict, item: dict, doc_favorecido: str) -> quem_recebe.QuemRecebe:
    if str(leitura.get("tipo_papel") or "") in _SEM_EMITENTE:
        return quem_recebe.QuemRecebe()
    return quem_recebe.conferir(leitura, item.get("paidTo"), doc_favorecido)


def leitura_do_item(item: dict, files, leituras_ia: dict, *, oc: str = "",
                    doc_favorecido: str = "") -> dict | None:
    """O `registro["leitura_ia"]` do lançamento, ou None quando nenhum anexo dele
    foi para a IA. Só contém texto e números simples (vai para o HTML).

    `anexos` = quantos anexos dele estavam na fila da IA; `nao_lidos` = quantos
    deles não deram leitura (falhou, ilegível, pulado por teto/tamanho/disjuntor)."""
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
        base = {"falhou": False, "pulado": False, "provas": [], "total_lido": "", "motivos": [], "dividido": "",
                "tipo_papel": "", "origem": "", "endereco": "", "oc": "", "duvidas": [],
                "emitente": "", "emitente_cnpj_cpf": "", "emitente_telefone": "",
                "quem_recebe": quem_recebe.NAO, "quem_recebe_por": "", "quem_recebe_motivo": ""}
        if e.get("pulado"):
            resultados.append({**base, "estado": NAO_LIDO, "pulado": True,
                               "motivos": [str(e["pulado"])]})
        elif not e.get("ok"):
            resultados.append({**base, "estado": FALHOU, "falhou": True,
                               "motivos": [f"{FALHOU}: {e.get('erro') or '?'}"]})
        else:
            leitura = e["leitura"]
            c = li.conferir(leitura, valor)
            dividido = ""
            soma = _soma_do_papel(e) if c.estado == li.DIVERGE else None
            if soma is not None:
                # Papel dividido (dono, 26/11/2026): o total do papel contra a
                # SOMA dos lançamentos que o usam. Fechando, vale a conferência
                # da soma — nunca melhor que ela, e o nível segue em "Olhe".
                pela_soma = li.conferir(leitura, soma[0])
                if pela_soma.estado in USAVEIS and pela_soma.estado != li.DIVERGE:
                    partes = " + ".join(f"R$ {nivel._brl(v)}" for v in sorted(soma[1], reverse=True))
                    # O papel prova a SOMA, não o valor de cada um, e só vê os
                    # lançamentos a pagar que foram à IA: um já pago ou uma
                    # duplicata somariam igual (revisão de dinheiro). Por isso
                    # a frase manda conferir, e o nível segue em "Olhe".
                    dividido = (f"papel dividido em {len(soma[1])} lançamentos: "
                                f"{partes} = R$ {nivel._brl(soma[0])} — confira se "
                                "nenhum outro lançamento usa este papel")
                    c = pela_soma
            qr = _quem_recebe(leitura, item, doc_favorecido)
            resultados.append({
                **base, "estado": c.estado, "provas": list(c.provas),
                "total_lido": "" if c.total_lido is None else str(c.total_lido),
                "motivos": ([dividido] if dividido else []) + list(c.motivos),
                "dividido": dividido, "tipo_papel": str(leitura.get("tipo_papel") or ""),
                "origem": e.get("origem") or "", "endereco": _endereco(item, leitura),
                "oc": _oc(leitura, oc), "duvidas": [str(d) for d in leitura.get("duvidas") or []],
                "emitente": str(leitura.get("emitente_nome") or "").strip(),
                "emitente_cnpj_cpf": str(leitura.get("emitente_cnpj_cpf") or "").strip(),
                "emitente_telefone": str(leitura.get("emitente_telefone") or "").strip(),
                "quem_recebe": qr.estado, "quem_recebe_por": qr.por,
                "quem_recebe_motivo": qr.motivo})
    escolhido = dict(_escolher(resultados))
    escolhido["anexos"] = len(resultados)
    escolhido["nao_lidos"] = sum(1 for r in resultados if r["estado"] not in USAVEIS)
    return escolhido
