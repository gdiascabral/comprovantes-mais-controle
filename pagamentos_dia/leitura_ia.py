# -*- coding: utf-8 -*-
"""Leitura por IA de anexo escrito à mão (spec de 19/11/2026, parte 3).

Recibo de talão, pedido de balcão preenchido à mão e foto com o comprovante
do cartão: o app não lê (texto vazio, OCR sem valor). Aqui só a REGRA, sem
rede nem pacote de terceiros: quem chama entrega o `cliente` (o
`anthropic.Anthropic()` no roteiro de medição; um dublê nos testes). Assim
este módulo entra no `codigo.zip` sem exigir exe novo.

Três peças:
- `pedir_leitura`: monta o pedido (imagem ou PDF + instrução + esquema JSON)
  e devolve a leitura validada, ou levanta `LeituraFalhou` (recusa, resposta
  cortada, JSON fora do esquema). Nunca devolve leitura pela metade.
- `conferir`: compara a leitura com o lançamento, em `Decimal`. A leitura
  NUNCA vale sozinha: o total tem de bater com o lançamento E ter uma segunda
  prova no mesmo papel (valor por extenso, soma dos itens ou comprovante do
  cartão). Medido em 19/11/2026: num pedido de balcão um 4 foi lido como 9,
  e o comprovante do cartão na outra foto desmentia.
- `CacheLeituras`: cada anexo é lido uma vez. A chave é id + tamanho + data
  de alteração do anexo, nunca a URL (assinada, muda a cada leitura).
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

#: O modelo padrão (decisão 3 da spec: trocar só depois da medição).
MODELO = "claude-opus-5-5"
MAX_TOKENS = 4000

TIPOS_DE_PAPEL = ("recibo", "pedido_de_balcao", "comprovante_de_cartao",
                  "nota_fiscal", "boleto", "outro")

_TEXTO = {"type": "string"}
ESQUEMA = {
    "type": "object",
    "properties": {
        "tipo_papel": {"type": "string", "enum": list(TIPOS_DE_PAPEL)},
        "legivel": {"type": "boolean"},
        "total": _TEXTO,
        "total_por_extenso": _TEXTO,
        "ordem_de_compra": _TEXTO,
        "numero_documento": _TEXTO,
        "data": _TEXTO,
        "quadra": _TEXTO,
        "lote": _TEXTO,
        "itens": {"type": "array", "items": {
            "type": "object",
            "properties": {"descricao": _TEXTO, "quantidade": _TEXTO,
                           "unitario": _TEXTO, "total": _TEXTO},
            "required": ["descricao", "quantidade", "unitario", "total"],
            "additionalProperties": False}},
        "cartao_valor": _TEXTO,
        "cartao_nome": _TEXTO,
        "duvidas": {"type": "array", "items": _TEXTO},
    },
    "required": ["tipo_papel", "legivel", "total", "total_por_extenso", "ordem_de_compra",
                 "numero_documento", "data", "quadra", "lote", "itens", "cartao_valor",
                 "cartao_nome", "duvidas"],
    "additionalProperties": False,
}

INSTRUCAO = """Este arquivo é um documento de compra de uma construtora: recibo de talão, \
pedido de balcão preenchido à mão, nota fiscal ou a foto de um desses com o \
comprovante de cartão por cima. Transcreva o que está ESCRITO, sem completar nem \
deduzir.

- Valores em reais no formato 1.234,56. Se o papel diz "4.700" ou "#4.700#", \
escreva 4.700,00.
- "total" é o valor total do documento; "total_por_extenso" é o valor escrito \
em palavras, se houver ("quatro mil e setecentos reais").
- "itens": uma entrada por linha da tabela de itens, com quantidade, unitário e \
total da linha como estão escritos.
- "quadra" e "lote": do endereço da obra (QD/Q/QUADRA e LT/L/LOTE), só o número \
ou o número com letra.
- "cartao_valor" e "cartao_nome": do comprovante de cartão, se aparecer na \
imagem (o valor impresso e o nome escrito à mão nele).
- Campo que não aparece ou que você não consegue ler: texto vazio.
- Em "duvidas", liste o nome de cada campo em que a leitura é incerta (letra \
ambígua, borrão, número que pode ser outro).
- "legivel" é false se não dá para ler o documento."""


class LeituraFalhou(RuntimeError):
    """A IA não devolveu uma leitura válida (recusa, corte, esquema)."""


@dataclass
class Uso:
    entrada: int = 0
    saida: int = 0


def _bloco_do_arquivo(dados: bytes, media_type: str) -> dict:
    b64 = base64.standard_b64encode(dados).decode("ascii")
    if media_type == "application/pdf":
        return {"type": "document",
                "source": {"type": "base64", "media_type": media_type, "data": b64}}
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}}


def media_type_do_nome(nome: str) -> str:
    """O tipo pelo final do nome; vazio quando não é PDF nem imagem aceita."""
    n = (nome or "").lower()
    if n.endswith(".pdf"):
        return "application/pdf"
    if n.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if n.endswith(".png"):
        return "image/png"
    if n.endswith(".webp"):
        return "image/webp"
    return ""


def validar(dados) -> dict:
    """Confere a forma da resposta (o esquema já vem garantido pela API; aqui
    é a falha fechada caso algo passe)."""
    if not isinstance(dados, dict):
        raise LeituraFalhou("a resposta não é um objeto")
    faltam = [c for c in ESQUEMA["required"] if c not in dados]
    if faltam:
        raise LeituraFalhou(f"faltam campos na resposta: {', '.join(faltam)}")
    if dados["tipo_papel"] not in TIPOS_DE_PAPEL or not isinstance(dados["legivel"], bool):
        raise LeituraFalhou("tipo de papel ou 'legivel' fora do esperado")
    if not isinstance(dados["itens"], list) or not isinstance(dados["duvidas"], list):
        raise LeituraFalhou("'itens' ou 'duvidas' não é lista")
    return dados


def pedir_leitura(cliente, dados: bytes, media_type: str, *, modelo: str = MODELO,
                  max_tokens: int = MAX_TOKENS) -> tuple[dict, Uso]:
    """(leitura validada, tokens usados). Levanta `LeituraFalhou`.

    `cliente` é um `anthropic.Anthropic()` (ou dublê com `.beta.messages.create`).
    Usa o pedido beta para pôr o recurso de reserva por recusa
    (`fallbacks="default"`), como manda a documentação para este modelo."""
    if not media_type:
        raise LeituraFalhou("tipo de arquivo não aceito")
    resposta = cliente.beta.messages.create(
        model=modelo, max_tokens=max_tokens,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        output_config={"effort": "low",
                       "format": {"type": "json_schema", "schema": ESQUEMA}},
        messages=[{"role": "user", "content": [_bloco_do_arquivo(dados, media_type),
                                                {"type": "text", "text": INSTRUCAO}]}])
    uso = Uso(entrada=int(getattr(resposta.usage, "input_tokens", 0) or 0),
              saida=int(getattr(resposta.usage, "output_tokens", 0) or 0))
    parada = getattr(resposta, "stop_reason", None)
    if parada == "refusal":
        raise LeituraFalhou("a IA recusou ler este arquivo")
    if parada == "max_tokens":
        raise LeituraFalhou("a resposta foi cortada (limite de tokens)")
    texto = next((b.text for b in resposta.content if getattr(b, "type", "") == "text"), "")
    try:
        return validar(json.loads(texto)), uso
    except (ValueError, TypeError) as e:
        raise LeituraFalhou(f"a resposta não é JSON válido ({e})") from e


# ------------------------------------------------------------- dinheiro
_CENTAVO = Decimal("0.01")


def dinheiro(texto) -> Decimal | None:
    """ "1.234,56", "#4.700#", "4.700", "4700,00", "R$ 52,30" → Decimal; senão None."""
    s = re.sub(r"[^\d.,]", "", str(texto or ""))
    if not s or not re.search(r"\d", s):
        return None
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):            # "4.700": milhar sem centavos
        s = s.replace(".", "")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d+\.\d{2}", s):                 # "52.30"
        pass
    else:
        s = s.replace(".", "")
    try:
        return Decimal(s).quantize(_CENTAVO)
    except InvalidOperation:
        return None


_UNIDADES = {"zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4,
             "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11,
             "doze": 12, "treze": 13, "quatorze": 14, "catorze": 14, "quinze": 15,
             "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19, "vinte": 20,
             "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60, "setenta": 70,
             "oitenta": 80, "noventa": 90, "cem": 100, "cento": 100, "duzentos": 200,
             "duzentas": 200, "trezentos": 300, "trezentas": 300, "quatrocentos": 400,
             "quatrocentas": 400, "quinhentos": 500, "quinhentas": 500, "seiscentos": 600,
             "seiscentas": 600, "setecentos": 700, "setecentas": 700, "oitocentos": 800,
             "oitocentas": 800, "novecentos": 900, "novecentas": 900}
_TIRA_ACENTO = str.maketrans("áàâãéêíóôõúç", "aaaaeeiooouc")


def _inteiro(palavras: list[str]) -> int | None:
    total, grupo, viu = 0, 0, False
    for p in palavras:
        if p in ("e", "de"):
            continue
        if p in _UNIDADES:
            grupo += _UNIDADES[p]
            viu = True
        elif p == "mil":
            total += (grupo or 1) * 1000
            grupo, viu = 0, True
        elif p in ("milhao", "milhoes"):
            total += (grupo or 1) * 1_000_000
            grupo, viu = 0, True
        else:
            return None
    return total + grupo if viu else None


def extenso_para_valor(texto) -> Decimal | None:
    """ "quatro mil e setecentos reais" → 4700.00; "trezentos reais e
    cinquenta centavos" → 300.50. Palavra que não é número → None."""
    s = str(texto or "").lower().translate(_TIRA_ACENTO)
    s = re.sub(r"[^a-z ]", " ", s)
    palavras = s.split()
    if not palavras:
        return None
    if "centavos" in palavras or "centavo" in palavras:
        corte = next(i for i, p in enumerate(palavras) if p in ("reais", "real"))  \
            if any(p in ("reais", "real") for p in palavras) else -1
        if corte >= 0:
            reais_p, cent_p = palavras[:corte], palavras[corte + 1:]
        else:
            reais_p, cent_p = [], palavras
        cent_p = [p for p in cent_p if p not in ("centavos", "centavo")]
        reais = _inteiro(reais_p) if reais_p else 0
        cent = _inteiro(cent_p)
        if reais is None or cent is None or cent > 99:
            return None
        return (Decimal(reais) + Decimal(cent) / 100).quantize(_CENTAVO)
    palavras = [p for p in palavras if p not in ("reais", "real")]
    n = _inteiro(palavras)
    return Decimal(n).quantize(_CENTAVO) if n is not None else None


# ------------------------------------------------------------- conferência
BATE, SEM_SEGUNDA_PROVA, DIVERGE, ILEGIVEL = ("bate", "sem segunda prova",
                                              "diverge", "ilegível")
#: O total escrito é o do lançamento e outra prova do papel (extenso ou cartão)
#: concorda, mas a SOMA dos itens escrita no papel não fecha com o total
#: (25/11/2026: itens 5.132,00 × total 5.120,00; itens 5.864,00 × total
#: 5.864,50). É erro de conta de quem escreveu o papel, não do valor a pagar:
#: pede olho, não é divergência.
TOTAL_BATE_SOMA_NAO_FECHA = "total bate, soma do papel não fecha"
_SOMA = "soma dos itens"


@dataclass
class Conferencia:
    estado: str
    provas: list = field(default_factory=list)     # ["extenso", "soma dos itens", ...]
    total_lido: Decimal | None = None
    motivos: list = field(default_factory=list)


def _soma_dos_itens(itens) -> Decimal | None:
    lidos = [dinheiro((i or {}).get("total")) for i in itens or ()]
    valores = [v for v in lidos if v is not None]
    if not lidos or len(valores) != len(lidos):
        return None
    return sum(valores, Decimal("0")).quantize(_CENTAVO)


def conferir(leitura: dict, valor) -> Conferencia:
    """O total lido contra o valor do lançamento, com segunda prova.

    - BATE: o total lido é o do lançamento E pelo menos uma segunda prova do
      mesmo papel concorda (extenso, soma dos itens ou comprovante do cartão).
    - TOTAL_BATE_SOMA_NAO_FECHA: o total e outra prova (extenso ou cartão)
      concordam com o lançamento, só a soma dos itens escrita no papel não fecha.
    - SEM_SEGUNDA_PROVA: o total bate, nada mais confirma (inclui o caso de a
      soma não fechar e nenhuma outra prova existir).
    - DIVERGE: o TOTAL lido, o extenso ou o cartão dizem outro valor. A soma
      dos itens sozinha, contra um total que bate, não é divergência.
    - ILEGIVEL: a IA disse que não leu, ou não leu total nem prova nenhuma.
    """
    alvo = Decimal(str(valor)).quantize(_CENTAVO)
    if not leitura or not leitura.get("legivel"):
        return Conferencia(ILEGIVEL, motivos=["a IA não conseguiu ler o documento"])
    total = dinheiro(leitura.get("total"))
    candidatas = {"valor por extenso": extenso_para_valor(leitura.get("total_por_extenso")),
                  _SOMA: _soma_dos_itens(leitura.get("itens")),
                  "comprovante do cartão": dinheiro(leitura.get("cartao_valor"))}
    lidas = {k: v for k, v in candidatas.items() if v is not None}
    batem = [k for k, v in lidas.items() if v == alvo]
    contra = [k for k, v in lidas.items() if v != alvo]
    if total is None and not lidas:
        return Conferencia(ILEGIVEL, motivos=["nenhum valor legível no documento"])
    total_ok = total is not None and total == alvo
    # A soma só diverge quando não há total que a contradiga e nada concorda.
    soma_so = contra == [_SOMA] and (total_ok or (total is None and batem))
    fortes_contra = [k for k in contra if k != _SOMA or not soma_so]
    if (total is not None and total != alvo) or fortes_contra:
        motivos = [f"{k} lido: R$ {lidas[k]}" for k in fortes_contra]
        if total is not None and total != alvo:
            motivos.insert(0, f"total lido R$ {total} × lançamento R$ {alvo}")
        return Conferencia(DIVERGE, batem, total, motivos)
    motivo_soma = ([f"{_SOMA} R$ {lidas[_SOMA]} não fecha com o total escrito no papel"]
                   if soma_so else [])
    outras = [k for k in batem if k != _SOMA]
    if total is None:
        return Conferencia(SEM_SEGUNDA_PROVA, batem, None,
                           ["o total não foi lido; só " + ", ".join(batem) + " bate"]
                           + motivo_soma)
    if soma_so and outras:
        return Conferencia(TOTAL_BATE_SOMA_NAO_FECHA, outras, total, motivo_soma)
    if not batem:
        return Conferencia(SEM_SEGUNDA_PROVA, [], total,
                           ["valor lido por IA, sem segunda prova no papel"] + motivo_soma)
    return Conferencia(BATE, batem, total, [])


# ------------------------------------------------------------- cache
class CacheLeituras:
    """`{chave: {"leitura": ..., "modelo": ..., "quando": ...}}` num JSON.

    Arquivo estragado não para nada (o cache só economiza): é renomeado para
    `.estragado` e o cache recomeça vazio."""

    def __init__(self, caminho: Path):
        self.caminho = Path(caminho)
        self._dados = self._ler()

    @staticmethod
    def chave(anexo_id, tamanho, alterado_em) -> str:
        return f"{anexo_id}|{tamanho}|{alterado_em}"

    def _ler(self) -> dict:
        try:
            dados = json.loads(self.caminho.read_text(encoding="utf-8"))
            return dados if isinstance(dados, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            try:
                self.caminho.replace(self.caminho.with_suffix(".estragado"))
            except OSError:
                pass
            return {}

    def obter(self, chave: str) -> dict | None:
        item = self._dados.get(chave)
        return item.get("leitura") if isinstance(item, dict) else None

    def guardar(self, chave: str, leitura: dict, *, modelo: str, quando: str) -> None:
        self._dados[chave] = {"leitura": leitura, "modelo": modelo, "quando": quando}
        tmp = self.caminho.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._dados, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.caminho)
