# -*- coding: utf-8 -*-
"""HTML dos pagamentos das contas PF e Moura Dantas (aba "Pagamentos do dia" › PF).

Pedido do dono (12/11/2026): o que até ali saía de scripts fora do app — ler as
contas de pessoa física e da Moura Dantas que ele escolhe, montar um HTML com
código de barras e QR Pix COM a descrição dentro, marcar "já paguei" com a
conta que pagou e baixar a lista para a baixa no ERP — passa a ser uma aba.

**Quem decide o que entra é a apuração de sempre.** A leitura é a do Buscar
(`leitura_do_dia.ler_pagamentos`, só com `conta_entra` trocado pelas contas
marcadas), então sem anexo, R$ 1,00, `so_com_reembolso`, boleto em imagem e o
resto valem igual às PJ. Este módulo só (1) tira o que o dono mandou tirar
direto — `regras_pf.json`, ao lado do exe, porque são nomes de gente e de obra
e o repositório é público —, (2) separa os reembolsos dos sócios (a caixa da
tela, como nas PJ) e (3) desenha.

**O QR Pix montado pela chave leva a descrição** no sub-campo 02 do campo 26
do BR Code, pela MESMA regra do HTML das PJ (`html_pagamentos.
descricao_para_colar`). O campo 26 tem no máximo 99 caracteres; o que sobra da
chave é o limite. Provado no PagBank em 12/11/2026: o comprovante traz a
"Descrição". QR que veio pronto do fornecedor não muda (o CRC é dele).

Puro: sem tela, sem ERP, sem rede. Os códigos são SVG do `zxingcpp` (já no exe
desde o `qr_pix`).
"""
from __future__ import annotations

import html
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import html_pagamentos, ocr_boleto, qr_pix
from . import regras_pagamento as regras

ARQ_REGRAS_PF = "regras_pf.json"
#: Link do lançamento no ERP: o MESMO do HTML das PJ, nunca uma cópia.
URL_LANCAMENTO = html_pagamentos.URL_LANCAMENTO


# ---------------------------------------------------------------- contas
def _n(t) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(t or ""))
                   if not unicodedata.combining(c)).upper()


def _chave(t) -> str:
    """Para comparar nomes: sem acento, sem sinal, um espaço só."""
    return re.sub(r"[^A-Z0-9]+", " ", _n(t)).strip()


def e_conta_da_aba(nome) -> bool:
    """A conta aparece na aba PF? Toda conta PESSOA FISICA e toda MOURA DANTAS
    (dono, 12/11/2026: "trazer todas pf + as moura dantas")."""
    u = f" {_chave(nome)} "
    return " PESSOA FISICA " in u or " MOURA DANTAS " in u


def contas_da_aba(nomes) -> list[str]:
    """As contas da aba, sem repetir, em ordem alfabética."""
    vistos = {}
    for nome in nomes or ():
        nome = str(nome or "").strip()
        if nome and e_conta_da_aba(nome):
            vistos.setdefault(_chave(nome), nome)
    return sorted(vistos.values(), key=_chave)


# ---------------------------------------------------------------- regras do dono
@dataclass
class RegrasPF:
    """O que sai direto, sem perguntar. `cc_fora`: pedaço do centro de custo
    (pós-obra, chácara); `favorecidos_fora`: pedaço do nome de quem recebe."""
    cc_fora: list = field(default_factory=list)
    favorecidos_fora: list = field(default_factory=list)


def carregar_regras(base: Path | None = None) -> RegrasPF:
    """`regras_pf.json` ao lado do exe; ausente ou ilegível = nenhuma regra (o
    app roda igual, só sem as exclusões — a tela avisa)."""
    dados = regras._ler_json(ARQ_REGRAS_PF, base)
    if not isinstance(dados, dict):
        return RegrasPF()
    lista = lambda k: [str(x) for x in (dados.get(k) or []) if str(x).strip()]  # noqa: E731
    return RegrasPF(cc_fora=lista("cc_fora"), favorecidos_fora=lista("favorecidos_fora"))


def _contem(texto, pedacos) -> str:
    """O pedaço (como escrito na regra) que aparece em `texto`, ou ""."""
    alvo = f" {_chave(texto)} "
    for p in pedacos:
        k = _chave(p)
        if k and f" {k} " in alvo:
            return p
    return ""


def _e_cartao_ou_link(r: dict) -> bool:
    return bool(re.search(r"CART[AÃ]O|LINK", _n(r.get("tipo"))))


@dataclass
class Separacao:
    entram: list            # [(conta, registro)]
    fora: list              # [(conta, registro, motivo)]
    reembolsos: list        # [(conta, registro, pessoa)] — fora pela caixa desligada


def separar(resultado, regras_pf: RegrasPF, pessoas=(), reembolso_ligado=True) -> Separacao:
    """O que entra, o que sai direto (com o motivo) e os reembolsos dos sócios.

    Os omitidos da apuração (`resultado.omitidos`) vão para `fora` com o
    motivo deles — nada some calado. Reembolso dos `pessoas` (o mesmo
    `e_reembolso_de` da caixa das PJ) com a caixa desligada vai para
    `reembolsos`, que o HTML mostra recolhidos e deixa pôr de volta."""
    sep = Separacao([], [], [])
    pessoas = [p for p in (pessoas or ()) if str(p).strip()]
    for conta, regs in (getattr(resultado, "contas", None) or {}).items():
        for r in regs:
            cc = _contem(r.get("centro_custo"), regras_pf.cc_fora)
            quem = _contem(r.get("favorecido"), regras_pf.favorecidos_fora)
            if cc:
                sep.fora.append((conta, r, f"centro de custo {cc} (sai direto)"))
            elif quem:
                sep.fora.append((conta, r, f"{quem} (sai direto)"))
            elif _e_cartao_ou_link(r):
                sep.fora.append((conta, r, "pagamento por cartão ou link"))
            elif (not reembolso_ligado and pessoas
                  and html_pagamentos.e_reembolso_de(r.get("reembolso_para"), pessoas)):
                sep.reembolsos.append((conta, r, r.get("reembolso_para")))
            else:
                sep.entram.append((conta, r))
    for o in getattr(resultado, "omitidos", None) or ():
        sep.fora.append((o.get("conta") or "", {
            "favorecido": o.get("favorecido"), "valor": o.get("valor"),
            "vencimento": o.get("vencimento") or "", "id": o.get("id") or ""},
            o.get("motivo") or "não entrou"))
    return sep


# ---------------------------------------------------------------- Pix estático
def _tlv(i: str, v: str) -> str:
    return f"{i}{len(v):02d}{v}"


def _cpf_valido(d: str) -> bool:
    if len(d) != 11 or d == d[0] * 11:
        return False
    for k in (9, 10):
        s = sum(int(d[i]) * (k + 1 - i) for i in range(k))
        if (s * 10 % 11) % 10 != int(d[k]):
            return False
    return True


def chave_normalizada(chave) -> tuple[str, str]:
    """(chave como o DICT a guarda, tipo) ou ("", motivo). Onze dígitos que
    não fecham o CPF só viram celular com o 9 depois do DDD."""
    c = str(chave or "").strip()
    c = re.sub(r"^(CHAVE\s*)?PIX\s*(CPF|CNPJ|CELULAR|TELEFONE|E-?MAIL|ALEAT[OÓ]RIA)?\s*:?\s*",
               "", c, flags=re.I).strip()
    if "@" in c and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", c):
        return c.lower(), "e-mail"
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", c):
        return c.lower(), "aleatória"
    d = re.sub(r"\D", "", c)
    if c.startswith("+55") and len(d) == 13:
        return "+" + d, "celular"
    if len(d) == 14:
        return d, "CNPJ"
    if len(d) == 11 and _cpf_valido(d):
        return d, "CPF"
    if len(d) == 11 and d[2] == "9":
        return "+55" + d, "celular"
    if len(d) == 13 and d.startswith("55"):
        return "+" + d, "celular"
    return "", f"chave não reconhecida ({c or 'vazia'})"


def limite_da_descricao(chave: str) -> int:
    """Quanto cabe no sub-campo 02: o campo 26 tem 99, o GUI 18 com o TLV, a
    chave o tamanho dela + 4, o 02 mais 4. Nunca mais de 72."""
    return max(0, min(99 - 18 - 4 - len(chave) - 4, 72))


def descricao_do_pix(registro: dict, chave: str) -> str:
    """A descrição do HTML das PJ, sem acento nem sinal (o banco recusa)."""
    lim = limite_da_descricao(chave)
    if not lim:
        return ""
    d = html_pagamentos.descricao_para_colar(registro, None, limite=lim)
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", "", _n(d))).strip()[:lim]


def pix_estatico(chave: str, valor: float, nome: str, descricao: str = "") -> str:
    nome = re.sub(r"[^A-Z0-9 ]", "", _n(nome))[:25].strip() or "RECEBEDOR"
    mai = (_tlv("00", "br.gov.bcb.pix") + _tlv("01", chave)
           + (_tlv("02", descricao) if descricao else ""))
    corpo = (_tlv("00", "01") + _tlv("26", mai) + _tlv("52", "0000") + _tlv("53", "986")
             + _tlv("54", f"{valor:.2f}") + _tlv("58", "BR") + _tlv("59", nome)
             + _tlv("60", "GOIANIA") + _tlv("62", _tlv("05", "***")) + "6304")
    return corpo + qr_pix.crc16(corpo)


# ---------------------------------------------------------------- itens
@dataclass
class Item:
    conta: str
    registro: dict
    grupo: str                       # "BOLETO" ou "PIX"
    codigos: list                    # [(rótulo, conteúdo, "barras"|"qr", texto mostrado)]
    alertas: list
    notas: list
    titulo_id: str = ""
    reembolso_de: str = ""           # pessoa, quando veio da caixa de reembolso


def _copia_e_cola(dados) -> bool:
    return bool(dados) and str(dados).startswith("000201") and qr_pix.valido(str(dados))


def item_do_registro(conta: str, r: dict, titulo_id: str = "") -> Item:
    """Os códigos de UMA linha: boleto → código de barras (+ o QR do mesmo
    boleto); Pix → o copia-e-cola que veio pronto, ou o QR montado pela chave
    com a descrição dentro. Sem nada para escanear, alerta — nunca chute."""
    tipo, dados = str(r.get("tipo") or ""), str(r.get("dados") or "")
    valor = float(r.get("valor") or 0)
    codigos, alertas, notas = [], [], []
    status = str(r.get("status") or "")
    if status.upper().startswith("ATEN"):
        alertas.append(status)
    if tipo.upper().startswith("BOLETO"):
        grupo = "BOLETO"
        barras = ocr_boleto.codigo_de_barras(dados) if dados else ""
        if barras:
            codigos.append(("Código de barras", barras, "barras", ocr_boleto.formatar(dados)))
        if _copia_e_cola(r.get("pix_qr")):
            codigos.append(("QR Pix do boleto", r["pix_qr"], "qr", r["pix_qr"]))
    else:
        grupo = "PIX"
        if _copia_e_cola(dados):
            codigos.append(("QR Pix (veio pronto)", dados, "qr", dados))
        elif dados:
            chave, tipo_ch = chave_normalizada(dados)
            if chave:
                nome = (r.get("reembolso_nome") if r.get("reembolso") else "") or r.get("favorecido")
                desc = descricao_do_pix(r, chave)
                br = pix_estatico(chave, valor, nome or "", desc)
                codigos.append((f"QR Pix montado pela chave ({tipo_ch})", br, "qr", chave))
                if desc:
                    notas.append(f"descrição no QR: {desc}")
                if r.get("reembolso"):
                    notas.append(f"reembolso: o dinheiro vai para {nome}, não para "
                                 f"{r.get('favorecido')}")
            else:
                alertas.append(tipo_ch)
    if not codigos:
        alertas.append("nada para escanear — abrir o anexo")
    return Item(conta=conta, registro=r, grupo=grupo, codigos=codigos,
                alertas=list(dict.fromkeys(alertas)), notas=notas, titulo_id=titulo_id)


def itens(entram, titulos=None) -> list[Item]:
    """Boletos primeiro, do maior para o menor; depois Pix. O mesmo código em
    dois lançamentos (fora a chave, que se repete com o fornecedor) vira
    alerta nos dois: é pagar em dobro."""
    titulos = titulos or {}
    saida = [item_do_registro(c, r, titulos.get(str(r.get("id")), "")) for c, r in entram]
    saida.sort(key=lambda i: (0 if i.grupo == "BOLETO" else 1,
                              -float(i.registro.get("valor") or 0),
                              i.registro.get("vencimento") or ""))
    por_codigo = {}
    for it in saida:
        for rot, conteudo, cl, _t in it.codigos:
            if "chave" in rot:
                continue
            por_codigo.setdefault(re.sub(r"\D", "", conteudo) if cl == "barras" else conteudo,
                                  set()).add(id(it))
    for it in saida:
        for rot, conteudo, cl, _t in it.codigos:
            if "chave" in rot:
                continue
            k = re.sub(r"\D", "", conteudo) if cl == "barras" else conteudo
            if len(por_codigo.get(k, ())) > 1:
                it.alertas.append(f"MESMO CÓDIGO em {len(por_codigo[k])} lançamentos — "
                                  "risco de pagar em dobro")
                break
    return saida


# ---------------------------------------------------------------- desenho
def _svg(texto: str, cl: str) -> str:
    import zxingcpp
    fmt = zxingcpp.BarcodeFormat.ITF if cl == "barras" else zxingcpp.BarcodeFormat.QRCode
    s = zxingcpp.write_barcode_to_svg(zxingcpp.create_barcode(texto, fmt))
    s = s[s.find("<svg"):]
    m = re.match(r'<svg width="(\d+(?:\.\d+)?)" height="(\d+(?:\.\d+)?)"', s)
    if m:
        ajuste = "none" if cl == "barras" else "xMidYMid meet"
        s = s.replace(m.group(0), f'<svg viewBox="0 0 {m.group(1)} {m.group(2)}" '
                                  f'preserveAspectRatio="{ajuste}" shape-rendering="crispEdges"', 1)
    return s


def _e(t) -> str:
    return html.escape(str(t if t is not None else ""))


def _brl(v) -> str:
    return f"{float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _data(iso) -> str:
    try:
        return date.fromisoformat(str(iso)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return "—"


def _cartao(k: int, it: Item, hoje: date, recolhido: bool = False) -> str:
    r = it.registro
    venc = str(r.get("vencimento") or "")[:10]
    vencido = bool(venc) and venc < hoje.isoformat()
    blocos = "".join(
        f'<figure class="cod {cl}"><figcaption>{_e(rot)}</figcaption>{_svg(conteudo, cl)}'
        f'<div class="txt"><code>{_e(t)}</code><button type="button" data-copiar="{_e(t)}">'
        f'Copiar</button></div></figure>'
        for rot, conteudo, cl, t in it.codigos)
    lista = lambda xs, cl: (f'<ul class="{cl}">' + "".join(f"<li>{_e(x)}</li>" for x in xs)  # noqa: E731
                            + "</ul>") if xs else ""
    desc = html_pagamentos.descricao_para_colar(r, it.conta)
    quem = (f"{r.get('reembolso_nome')} (reembolso de {r.get('favorecido')})"
            if r.get("reembolso") and r.get("reembolso_nome") else r.get("favorecido"))
    return f'''
<article class="card{' atencao' if it.alertas else ''}{' reemb' if recolhido else ''}" data-id="{_e(r.get('id'))}" data-tpid="{_e(it.titulo_id)}" data-forn="{_e(r.get('favorecido'))}" data-venc="{_e(venc)}" data-centavos="{round(float(r.get('valor') or 0) * 100)}">
  <header>
    <span class="num">{k}</span>
    <span class="grupo g-{it.grupo.lower()}">{it.grupo}</span>
    <span class="valor">R$ {_brl(r.get('valor'))}</span>
    <span class="venc{' vencido' if vencido else ''}">venc. {_data(venc)}</span>
    <span class="status s-{'at' if it.alertas else 'ok'}">{'ATENÇÃO' if it.alertas else 'APTO'}</span>
    {f'<span class="tagre">reembolso para {_e(it.reembolso_de)}</span>' if recolhido else ''}
    <label class="pago"><input type="checkbox" class="chk"> já paguei</label>
    <span class="pela"></span>
  </header>
  <div class="corpo">
    <div class="codigos">{blocos or '<p class="semcod">sem código para escanear</p>'}</div>
    <div class="info">
      <h3>{_e(quem)}</h3>
      <dl>
        <dt>Conta</dt><dd>{_e(it.conta)}</dd>
        <dt>Obra / CC</dt><dd>{_e(r.get('centro_custo') or '—')}</dd>
        <dt>OC</dt><dd>{_e(r.get('oc') or '—')}</dd>
        <dt>Para colar</dt><dd><code>{_e(desc)}</code> <button type="button" data-copiar="{_e(desc)}">Copiar</button></dd>
      </dl>
      {lista(it.alertas, 'alertas')}{lista(it.notas, 'notas')}
      {lista([str(x) for x in (r.get('conferencia') or []) if str(x).strip()] if isinstance(r.get('conferencia'), list) else ([r.get('conferencia')] if r.get('conferencia') else []), 'confs')}
      {lista([str(x) for x in (r.get('obs') or []) if str(x).strip()] if isinstance(r.get('obs'), list) else ([r.get('obs')] if r.get('obs') else []), 'obs')}
      <a class="link" href="{URL_LANCAMENTO}{_e(r.get('id'))}" target="_blank" rel="noopener">Abrir no Mais Controle</a>
    </div>
  </div>
</article>'''


def pagina(itens_, fora, reembolsos, contas_pagadoras, ini: date, fim: date,
           nome_arquivo: str, contas_lidas=(), hoje: date | None = None) -> str:
    """O HTML inteiro. `reembolsos` = [Item] tirados pela caixa: vão numa seção
    recolhida, cada um com o mesmo "já paguei" (o dono pode pagar um só).
    `contas_pagadoras` = [{"id", "nome", "saldo"}] para o "já paguei"."""
    hoje = hoje or date.today()
    cards = "".join(_cartao(k, it, hoje) for k, it in enumerate(itens_, 1))
    cards_re = "".join(_cartao(k, it, hoje, recolhido=True)
                       for k, it in enumerate(reembolsos, len(itens_) + 1))
    tot = lambda xs: sum(float(i.registro.get("valor") or 0) for i in xs)  # noqa: E731
    bol = [i for i in itens_ if i.grupo == "BOLETO"]
    pix = [i for i in itens_ if i.grupo == "PIX"]
    por_conta = {}
    for i in itens_:
        por_conta.setdefault(i.conta, []).append(i)
    resumo_contas = "".join(f"<li>{_e(c)}: {len(v)} · R$ {_brl(tot(v))}</li>"
                            for c, v in sorted(por_conta.items()))
    fora_html = "".join(
        f"<li>{_e(r.get('favorecido') or '?')} — R$ {_brl(r.get('valor'))} — "
        f"venc. {_data(r.get('vencimento'))} — {_e(conta)} — {_e(m)}</li>"
        for conta, r, m in sorted(fora, key=lambda x: (str(x[2]), -float(x[1].get('valor') or 0))))
    pf = [c for c in contas_pagadoras if not e_conta_da_aba(c.get("nome"))]
    chave = f"pagamentos_pf_{ini.isoformat()}_{fim.isoformat()}"
    return (MODELO
            .replace("__PERIODO__", f"{ini:%d/%m} a {fim:%d/%m/%Y}")
            .replace("__CONTAS_LIDAS__", _e(", ".join(contas_lidas) or "—"))
            .replace("__NB__", str(len(bol))).replace("__TB__", _brl(tot(bol)))
            .replace("__NP__", str(len(pix))).replace("__TP__", _brl(tot(pix)))
            .replace("__NT__", str(len(itens_))).replace("__TT__", _brl(tot(itens_)))
            .replace("__NA__", str(sum(1 for i in itens_ if i.alertas)))
            .replace("__POR_CONTA__", resumo_contas)
            .replace("__CARDS__", cards)
            .replace("__NR__", str(len(reembolsos))).replace("__TR__", _brl(tot(reembolsos)))
            .replace("__CARDS_RE__", cards_re)
            .replace("__NF__", str(len(fora))).replace("__FORA__", fora_html)
            .replace("__STORAGE__", json.dumps(chave))
            .replace("__CONTAS__", json.dumps(
                [{"id": c.get("id"), "nome": c.get("nome"), "saldo": c.get("saldo"),
                  "pf": c in pf} for c in contas_pagadoras], ensure_ascii=False))
            .replace("__ARQUIVO__", json.dumps(nome_arquivo)))


def nome_do_arquivo(ini: date, fim: date) -> str:
    return f"pagamentos_pf_{ini.isoformat()}_a_{fim.isoformat()}.html"


@dataclass
class Gerado:
    caminho: Path
    entram: int
    total: float
    fora: int
    reembolsos: int


def gravar(resultado, lancamentos, pasta: Path, ini: date, fim: date, *, regras_pf: RegrasPF,
           pessoas=(), reembolso_ligado=True, contas_pagadoras=(), contas_lidas=(),
           hoje: date | None = None) -> Gerado:
    """Separa, desenha e grava `pagamentos_pf_<ini>_a_<fim>.html` em `pasta`."""
    sep = separar(resultado, regras_pf, pessoas, reembolso_ligado)
    titulos = {str(i.get("id")): str(i.get("tradePayableId") or "") for i in lancamentos or ()}
    lista = itens(sep.entram, titulos)
    recolhidos = itens([(c, r) for c, r, _p in sep.reembolsos], titulos)
    pessoa_de = {id(r): str(p or "") for _c, r, p in sep.reembolsos}
    for it in recolhidos:
        it.reembolso_de = pessoa_de.get(id(it.registro), "")
    nome = nome_do_arquivo(ini, fim)
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / nome
    caminho.write_text(pagina(lista, sep.fora, recolhidos, list(contas_pagadoras), ini, fim,
                              nome, contas_lidas, hoje), encoding="utf-8")
    return Gerado(caminho, len(lista), sum(float(i.registro.get("valor") or 0) for i in lista),
                  len(sep.fora), len(recolhidos))


MODELO = r'''<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pagamentos PF e Moura Dantas</title>
<style>
:root { --bg:#f6f7f9; --card:#fff; --tx:#111827; --mu:#6b7280; --bd:#e5e7eb; --ok:#047857; --okbg:#ecfdf5;
  --at:#b45309; --atbg:#fffbeb; --bad:#b91c1c; --badbg:#fef2f2; --ac:#1d4ed8; }
* { box-sizing:border-box }
body { margin:0; background:var(--bg); color:var(--tx); font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif }
.wrap { max-width:1400px; margin:0 auto; padding:20px 16px 60px }
h1 { font-size:22px; margin:0 0 4px } .sub { color:var(--mu); margin:0 0 16px }
.resumo { display:flex; flex-wrap:wrap; gap:10px; margin-bottom:12px; position:sticky; top:0; background:var(--bg); padding:8px 0; z-index:2 }
.resumo div { background:var(--card); border:1px solid var(--bd); border-radius:10px; padding:8px 12px }
.resumo b { display:block; font-size:17px }
.porconta { margin:0 0 16px; color:var(--mu); font-size:14px }
.card { background:var(--card); border:1px solid var(--bd); border-left:5px solid var(--ok); border-radius:12px; margin:0 0 16px; overflow:hidden }
.card.atencao { border-left-color:var(--at) }
.card.feito { opacity:.45 } .card.feito .codigos { filter:grayscale(1) }
header { display:flex; flex-wrap:wrap; align-items:center; gap:10px; padding:10px 14px; border-bottom:1px solid var(--bd) }
.num { color:var(--mu); font-weight:600 }
.grupo { font-size:12px; font-weight:700; padding:2px 8px; border-radius:99px; background:#eef2ff; color:var(--ac) }
.g-pix { background:#ecfeff; color:#0e7490 }
.valor { font-size:20px; font-weight:700 }
.venc { font-size:13px; padding:2px 8px; border-radius:99px; background:#f3f4f6 } .venc.vencido { background:var(--badbg); color:var(--bad) }
.status, .tagre { font-size:12px; font-weight:700; padding:2px 8px; border-radius:99px }
.s-ok { background:var(--okbg); color:var(--ok) } .s-at { background:var(--atbg); color:var(--at) }
.tagre { background:#f5f3ff; color:#6d28d9 }
.pago { margin-left:auto; font-size:14px; cursor:pointer }
.pela { font-size:12px; color:var(--ok); font-weight:600 }
#modal { position:fixed; inset:0; background:rgba(17,24,39,.45); display:none; align-items:center; justify-content:center; z-index:60; padding:16px }
#modal.on { display:flex }
#modal .box { background:#fff; border-radius:12px; padding:18px; width:min(520px,100%); box-shadow:0 10px 30px rgba(0,0,0,.25) }
#modal h2 { font-size:17px; margin:0 0 4px } #modal p { margin:0 0 12px; color:var(--mu); font-size:14px }
#modal label { display:block; font-size:13px; color:var(--mu); margin:10px 0 4px }
#modal select, #modal input { width:100%; font:inherit; padding:8px; border:1px solid var(--bd); border-radius:8px }
#modal .acoes { display:flex; gap:8px; justify-content:flex-end; margin-top:16px }
#modal .acoes button { font-size:14px; padding:7px 14px } #modal .acoes .ok { background:var(--ac); color:#fff; border-color:var(--ac) }
.baixas { display:flex; gap:8px; flex-wrap:wrap; align-items:center } .baixas button { font-size:13px; padding:6px 12px }
.corpo { display:grid; grid-template-columns:minmax(0,680px) minmax(0,1fr); gap:18px; padding:14px }
@media (max-width:760px) { .corpo { grid-template-columns:1fr } .resumo { position:static } }
figure.cod { margin:0 0 14px; background:#fff; padding:10px; border:1px solid var(--bd); border-radius:10px }
figure.cod figcaption { font-size:12px; color:var(--mu); margin-bottom:6px }
figure.cod svg { display:block; width:100%; height:auto; background:#fff }
figure.qr svg { max-width:240px; margin:0 auto; padding:10px; cursor:zoom-in }
figure.barras svg { height:300px; padding:14px 22px; cursor:zoom-in }
figure.cod figcaption::after { content:' · clique no código para tela cheia'; color:var(--ac) }
#zoom { position:fixed; inset:0; background:#fff; z-index:50; display:none; align-items:center; justify-content:center; flex-direction:column; cursor:zoom-out; padding:2vh 2vw }
#zoom.on { display:flex }
#zoom svg { width:auto; height:auto; max-width:96vw; max-height:84vh; flex:1 1 auto }
#zoom.qr svg { width:60vh; height:60vh }
#zoom.barras svg { width:98vw; height:75vh }
#zoom p { margin:1vh 0 0; font:600 2.4vh system-ui,sans-serif; color:#111 }
.txt { display:flex; gap:6px; align-items:flex-start; margin-top:6px }
.txt code { font-size:11px; word-break:break-all; color:var(--mu); flex:1 }
button { font:inherit; font-size:12px; padding:3px 9px; border:1px solid var(--bd); background:#fff; border-radius:6px; cursor:pointer }
button:active { background:#eef2ff }
.info h3 { margin:0 0 8px; font-size:17px }
dl { display:grid; grid-template-columns:auto 1fr; gap:3px 12px; margin:0 0 10px; font-size:14px }
dt { color:var(--mu) } dd { margin:0; word-break:break-word }
ul { margin:6px 0; padding-left:18px; font-size:13px }
.alertas { background:var(--atbg); color:var(--at); border-radius:8px; padding:6px 8px 6px 24px; font-weight:600 }
.notas { color:var(--ok) } .confs { color:var(--mu) } .obs { color:#374151 }
.link { font-size:13px; color:var(--ac) }
details { background:var(--card); border:1px solid var(--bd); border-radius:10px; padding:10px 14px; margin-top:20px }
details > summary { cursor:pointer; font-weight:600 }
.semcod { color:var(--bad); font-weight:600 }
</style></head><body><div class="wrap">
<h1>Pagamentos PF e Moura Dantas</h1>
<p class="sub">Vencimentos de __PERIODO__ em aberto no Mais Controle. Contas lidas: __CONTAS_LIDAS__. Boletos do maior para o menor, depois Pix. Escaneie pelo celular; no Pix montado pela chave, confira o nome que o banco mostra antes de confirmar.</p>
<div class="resumo">
  <div>Boletos<b>__NB__ · R$ __TB__</b></div>
  <div>Pix<b>__NP__ · R$ __TP__</b></div>
  <div>Total<b>__NT__ · R$ __TT__</b></div>
  <div>Com atenção<b>__NA__</b></div>
  <div>Marcados como pagos<b id="pagos">0 · R$ 0,00</b></div>
  <div class="baixas">Para a baixa no ERP:<button type="button" id="exportar">Baixar lista das baixas</button><button type="button" id="copiarBaixas">Copiar lista</button></div>
</div>
<ul class="porconta">__POR_CONTA__</ul>
__CARDS__
<details id="reembolsos"><summary>Reembolsos dos sócios fora deste dia (__NR__ · R$ __TR__) — abra para pagar algum mesmo assim</summary>
__CARDS_RE__
</details>
<details><summary>Não entraram (__NF__)</summary><ul>__FORA__</ul></details>
</div>
<div id="zoom" title="clique ou Esc para fechar"></div>
<div id="modal" role="dialog" aria-modal="true"><div class="box">
  <h2>De qual conta saiu este pagamento?</h2><p id="mInfo"></p>
  <label for="mConta">Conta</label><select id="mConta"></select>
  <label for="mData">Data do pagamento</label><input type="date" id="mData">
  <div class="acoes"><button type="button" id="mCancelar">Cancelar</button><button type="button" class="ok" id="mOk">Confirmar</button></div>
</div></div>
<script>
const K = __STORAGE__;
const CONTAS = __CONTAS__;
let marcas = {};
try { marcas = JSON.parse(localStorage.getItem(K) || "{}"); } catch (e) {}
for (const k in marcas) if (typeof marcas[k] !== "object") delete marcas[k];
function brl(c) { return (c/100).toLocaleString("pt-BR", {minimumFractionDigits:2, maximumFractionDigits:2}); }
function salvar() { try { localStorage.setItem(K, JSON.stringify(marcas)); } catch (e) {} }
function contar() {
  let n = 0, c = 0;
  document.querySelectorAll(".card").forEach(card => {
    const m = marcas[card.dataset.id];
    card.classList.toggle("feito", !!m);
    card.querySelector(".chk").checked = !!m;
    card.querySelector(".pela").textContent = m ? "pago por " + m.conta + " em " + m.data.split("-").reverse().join("/") : "";
    if (m) { n++; c += +card.dataset.centavos; }
  });
  document.getElementById("pagos").textContent = n + " · R$ " + brl(c);
}
const sel = document.getElementById("mConta");
(function montar() {
  const op = (c) => { const o = document.createElement("option"); o.value = c.id;
    o.textContent = c.nome + (c.saldo == null ? "" : "  (saldo R$ " + brl(Math.round(c.saldo * 100)) + ")"); return o; };
  const g1 = document.createElement("optgroup"); g1.label = "Contas de pessoas";
  const g2 = document.createElement("optgroup"); g2.label = "Outras contas";
  const vazio = document.createElement("option"); vazio.value = ""; vazio.textContent = "— escolha a conta —";
  sel.appendChild(vazio);
  CONTAS.forEach(c => (c.pf ? g1 : g2).appendChild(op(c)));
  sel.appendChild(g1); sel.appendChild(g2);
})();
const M = document.getElementById("modal");
let cardAberto = null;
// A conta do pagamento anterior vem preenchida; trocada, a nova passa a vir
// dali em diante (dono, 12/11/2026). A do primeiro do dia, ele escolhe.
let ultimaConta = "";
function hojeISO() { const d = new Date(); return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); }
try { const u = JSON.parse(localStorage.getItem(K + ":ultima") || "null");
      if (u && u.dia === hojeISO()) ultimaConta = u.id; } catch (e) {}
function abrirModal(card) {
  cardAberto = card;
  document.getElementById("mInfo").textContent = card.dataset.forn + " · R$ " + brl(+card.dataset.centavos) +
    " · venc. " + card.dataset.venc.split("-").reverse().join("/");
  sel.value = ultimaConta && CONTAS.some(c => c.id === ultimaConta) ? ultimaConta : "";
  document.getElementById("mData").value = hojeISO();
  M.className = "on"; sel.focus();
}
function fecharModal() { M.className = ""; cardAberto = null; contar(); }
document.getElementById("mCancelar").addEventListener("click", fecharModal);
M.addEventListener("click", ev => { if (ev.target === M) fecharModal(); });
document.getElementById("mOk").addEventListener("click", () => {
  const c = CONTAS.find(x => x.id === sel.value);
  const data = document.getElementById("mData").value;
  if (!c) { alert("Escolha a conta de onde saiu o pagamento."); return; }
  if (!data) { alert("Informe a data do pagamento."); return; }
  const card = cardAberto;
  marcas[card.dataset.id] = { conta: c.nome, conta_id: c.id, data: data, quando: new Date().toISOString() };
  ultimaConta = c.id;
  try { localStorage.setItem(K + ":ultima", JSON.stringify({ id: c.id, dia: hojeISO() })); } catch (e) {}
  salvar(); fecharModal();
});
document.querySelectorAll(".chk").forEach(ch => ch.addEventListener("change", ev => {
  const card = ev.target.closest(".card"), id = card.dataset.id;
  if (ev.target.checked) { ev.target.checked = false; abrirModal(card); return; }
  const m = marcas[id];
  if (m && !confirm("Desmarcar? Sai da lista de baixas (estava: " + m.conta + ").")) { ev.target.checked = true; return; }
  delete marcas[id]; salvar(); contar();
}));
function listaBaixas() {
  const linhas = [];
  document.querySelectorAll(".card").forEach(card => {
    const m = marcas[card.dataset.id]; if (!m) return;
    linhas.push({ lancamento_id: card.dataset.id, titulo_id: card.dataset.tpid, fornecedor: card.dataset.forn,
      valor: (+card.dataset.centavos / 100).toFixed(2), vencimento: card.dataset.venc,
      conta: m.conta, conta_id: m.conta_id, data_pagamento: m.data });
  });
  return { gerado_em: new Date().toISOString(), html: __ARQUIVO__, baixas: linhas };
}
document.getElementById("exportar").addEventListener("click", () => {
  const dados = listaBaixas();
  if (!dados.baixas.length) { alert("Nenhum pagamento marcado ainda."); return; }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(dados, null, 1)], { type: "application/json" }));
  a.download = "baixas_pf_" + hojeISO() + ".json"; a.click();
});
document.getElementById("copiarBaixas").addEventListener("click", ev => {
  const dados = listaBaixas();
  if (!dados.baixas.length) { alert("Nenhum pagamento marcado ainda."); return; }
  navigator.clipboard.writeText(JSON.stringify(dados)).then(() => { ev.target.textContent = "Copiado"; setTimeout(() => ev.target.textContent = "Copiar lista", 1200); });
});
document.addEventListener("click", ev => {
  const b = ev.target.closest("button[data-copiar]"); if (!b) return;
  navigator.clipboard.writeText(b.dataset.copiar).then(() => { const t = b.textContent; b.textContent = "Copiado"; setTimeout(() => b.textContent = t, 1200); });
});
const Z = document.getElementById("zoom");
document.addEventListener("click", ev => {
  const svg = ev.target.closest("figure.cod svg");
  if (svg) {
    const fig = svg.closest("figure"), card = svg.closest(".card");
    Z.className = "on " + (fig.classList.contains("qr") ? "qr" : "barras");
    Z.innerHTML = svg.outerHTML + "<p>" + card.querySelector("h3").textContent + " · " +
      card.querySelector(".valor").textContent + " · " + fig.querySelector("figcaption").textContent + "</p>";
    return;
  }
  if (ev.target.closest("#zoom")) Z.className = "";
});
document.addEventListener("keydown", ev => { if (ev.key === "Escape") { Z.className = ""; if (M.className) fecharModal(); } });
contar();
</script></body></html>'''
