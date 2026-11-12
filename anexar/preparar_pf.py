# -*- coding: utf-8 -*-
"""Comprovantes de conta de pessoa física como chegam: foto ou PDF de banco digital.

O dono manda os comprovantes das contas PF (PagBank, Neon, Next) por e-mail,
como imagem do celular (`my_account_receipt_to_share.jpg`,
`IMG_Comprovante_Neon_….png`) ou PDF com nome do banco (`nextpdf….pdf`). O
`matcher` só lê PDF com o nome no padrão `VALOR - DESCRIÇÃO - DD-MM`, então
até 12/11/2026 cada lote era convertido e renomeado fora do app (84 arquivos
naquele dia).

Este módulo faz isso dentro do Anexar, antes de carregar a pasta:

- lê cada imagem (jpg/png) e cada PDF fora do padrão por OCR (ou pela camada
  de texto, no PDF que tem);
- tira valor, data, quem pagou, quem recebeu, o banco e o código de barras;
- grava ao lado um PDF no padrão (`VALOR - RECEBEDOR - DD-MM.pdf`) e, no
  arquivo `.comprovantes-pf.json` da pasta, de que conta saiu (banco + quem
  pagou), quem recebeu e o código de barras, para o `origem` e o
  `codigo_barras` usarem.

Nada aqui apaga nem renomeia o arquivo de quem mandou: o original fica, e o
PDF gerado é um arquivo novo. Arquivo que não deu para ler (sem valor ou sem
data) fica de fora, com aviso -- um comprovante sem valor não casa com nada.
Comprovante repetido (mesmos bytes, ou o mesmo identificador de transação
reenviado) vira um PDF só.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
from pathlib import Path

ARQUIVO = ".comprovantes-pf.json"
_EXT_IMAGEM = (".jpg", ".jpeg", ".png")
#: Bancos das contas de pessoa física. O Inter e o Sicoob são das empresas e
#: têm origem própria (registro da baixa), então ficam de fora daqui.
BANCOS_PF = ("PAGBANK", "NEON", "NEXT")
_MESES = {"JANEIRO": 1, "FEVEREIRO": 2, "MARCO": 3, "ABRIL": 4, "MAIO": 5, "JUNHO": 6,
          "JULHO": 7, "AGOSTO": 8, "SETEMBRO": 9, "OUTUBRO": 10, "NOVEMBRO": 11,
          "DEZEMBRO": 12}
_PADRAO_DO_MATCHER = re.compile(r"(^|\s-\s)\d[\d.]*,\d{2}(\s-\s|$)")


def _n(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).upper().strip()


# ------------------------------------------------------------------ leitura
def _depois(linhas: list[str], rotulos, pular=("NOME", "NOME:")) -> str:
    """O valor do PRIMEIRO rótulo da lista que aparece (a ordem é prioridade):
    na mesma linha ("Rótulo: valor") ou na linha seguinte, pulando "Nome"."""
    for r in rotulos:
        alvo = _n(r)
        for i, linha in enumerate(linhas):
            if _n(linha).rstrip(":") == alvo:
                for prox in linhas[i + 1:i + 4]:
                    if _n(prox) in pular or not prox.strip():
                        continue
                    m = re.match(r"\s*Nome\s*:\s*(.+)$", prox, re.I)
                    return (m.group(1) if m else prox).strip()
            m = re.match(rf"\s*{re.escape(r)}\s*:\s*(.+)$", linha, re.I)
            if m and _n(m.group(1)) not in pular:
                return m.group(1).strip()
    return ""


def _nome_depois_de(linhas: list[str], marca: str) -> str:
    """O "Nome: X" que vem depois da linha que contém `marca` (layout do Next)."""
    for i, linha in enumerate(linhas):
        if _n(marca) in _n(linha):
            for prox in linhas[i + 1:i + 5]:
                m = re.match(r"\s*Nome\s*:\s*(.+)$", prox, re.I)
                if m:
                    return m.group(1).strip()
    return ""


def _valor(linhas: list[str]) -> int | None:
    junto = "\n".join(linhas)

    def br(s):
        return int(s.replace(".", "").replace(",", ""))
    m = re.search(r"Valor(?: da transfer.ncia| do pagamento| pago)?\s*:?\s*\n?\s*R\$\s?([\d.]+,\d\d)", junto, re.I)
    if m and br(m.group(1)):
        return br(m.group(1))
    # O Next escreve o valor do Pix no formato americano: "Valor: 139.93".
    m = re.search(r"Valor\s*:\s*(\d{1,3}(?:,\d{3})*\.\d\d)\b", junto)
    if m:
        return int(m.group(1).replace(",", "").replace(".", ""))
    # Sem rótulo: o primeiro "R$" que não seja zero ("Multa: R$ 0,00" vem antes).
    for s in re.findall(r"R\$\s?([\d.]+,\d\d)", junto):
        if br(s):
            return br(s)
    return None


def _data(linhas: list[str]) -> tuple[str, str]:
    """(DD-MM, HHhMM) do pagamento; vazio quando não achou."""
    junto = "\n".join(linhas)
    m = re.search(r"(\d\d)/(\d\d)/(\d{4})(?:\s*(?:.s|,)?\s*(\d\d)[:h](\d\d))?", junto)
    if m:
        return f"{m.group(1)}-{m.group(2)}", (f"{m.group(4)}h{m.group(5)}" if m.group(4) else "")
    m = re.search(r"(\d{1,2}) de ([A-Za-zçÇ]+) de (\d{4})(?:\s*.s\s*(\d\d):(\d\d))?", junto)
    if m and _n(m.group(2)) in _MESES:
        dd, mm = int(m.group(1)), _MESES[_n(m.group(2))]
        return f"{dd:02d}-{mm:02d}", (f"{m.group(4)}h{m.group(5)}" if m.group(4) else "")
    return "", ""


def _banco(linhas: list[str]) -> str:
    t = _n(" ".join(linhas))
    if "PAGBANK" in t or "PAGSEGURO" in t or "4003-1775" in t:
        return "PAGBANK"
    if "NEON" in t:
        return "NEON"
    if re.search(r"\bNEXT\b", t):
        return "NEXT"
    if re.search(r"\bINTER\b", t):
        return "INTER"
    return ""


def ler(linhas: list[str]) -> dict:
    """Os campos de um comprovante, a partir das linhas do texto (OCR ou PDF)."""
    linhas = [l for l in (x.strip() for x in linhas) if l]
    data, hora = _data(linhas)
    # Quem pagou = o DONO DA CONTA. "Pagador" sozinho NÃO entra: no boleto ele é
    # o titular do boleto (o cliente da conta de luz), e não quem pagou --
    # medido em 12/11/2026, apontou outra conta em 29 comprovantes do PagBank.
    pagador = (_depois(linhas, ("Pagador Final", "De", "Pago por", "Quem pagou", "Origem"))
               or _nome_depois_de(linhas, "Dados do pagador")
               or _nome_depois_de(linhas, "Conta de débito"))
    recebedor = (_depois(linhas, ("Nome da cobrança", "Quem recebeu", "Para", "Favorecido",
                                  "Beneficiário", "Recebedor", "Destino", "Razão social"))
                 or _depois(linhas, ("Dados do recebedor",), pular=("NOME", "NOME:")))
    ident = re.search(r"E\d{8}\w{20,}", " ".join(linhas))
    return {"valor": _valor(linhas), "data": data, "hora": hora, "banco": _banco(linhas),
            "pagador": pagador, "recebedor": recebedor,
            "id": ident.group(0) if ident else ""}


# --------------------------------------------------------------------- OCR
_RAPID = None


def _rapidocr():
    global _RAPID
    if _RAPID is None:
        try:
            from rapidocr import RapidOCR          # noqa: PLC0415 -- opcional
            _RAPID = RapidOCR()
        except Exception:                           # noqa: BLE001
            _RAPID = False
    return _RAPID or None


def ocr_linhas(img) -> tuple[list[str], str]:
    """(linhas, leitor). RapidOCR quando existe -- leu o código de barras em 58
    de 58 prints de banco digital em 12/11/2026 --; senão, o Tesseract do app."""
    eng = _rapidocr()
    if eng is not None:
        try:
            import numpy as np                      # noqa: PLC0415
            return list(eng(np.array(img.convert("RGB"))).txts or []), "rapidocr"
        except Exception:                           # noqa: BLE001
            pass
    try:
        import pytesseract                          # noqa: PLC0415
        from separar_renomear.separar_renomear import _OCR, _ocr_disponivel  # noqa: PLC0415
        if _ocr_disponivel(lambda *_: None):
            texto = pytesseract.image_to_string(img, lang=_OCR["lang"])
            return texto.splitlines(), "tesseract"
    except Exception:                               # noqa: BLE001
        pass
    return [], ""


def _linhas_do_arquivo(caminho: Path, ocr) -> tuple[list[str], str, bytes]:
    """Linhas do comprovante, o leitor usado e os bytes do PDF a gravar."""
    from PIL import Image                           # noqa: PLC0415
    dados = caminho.read_bytes()
    if caminho.suffix.lower() in _EXT_IMAGEM:
        with Image.open(io.BytesIO(dados)) as img:
            linhas, leitor = ocr(img)
            saida = io.BytesIO()
            img.convert("RGB").save(saida, "PDF", resolution=150)
        return linhas, leitor, saida.getvalue()
    # PDF: camada de texto primeiro; sem ela, a 1ª página vira imagem para o OCR.
    texto = ""
    try:
        import pdfplumber                           # noqa: PLC0415
        with pdfplumber.open(io.BytesIO(dados)) as pl:
            texto = "\n".join((p.extract_text() or "") for p in pl.pages[:2])
            if sum(c.isdigit() for c in texto) < 15 and pl.pages:
                img = pl.pages[0].to_image(resolution=200).original
                linhas, leitor = ocr(img)
                return linhas, leitor, dados
    except Exception:                               # noqa: BLE001
        pass
    return texto.splitlines(), "texto", dados


# ----------------------------------------------------------------- a pasta
def _fora_do_padrao(nome: str) -> bool:
    base = Path(nome).stem
    return not _PADRAO_DO_MATCHER.search(base)


def _limpo(s: str, k: int = 50) -> str:
    s = re.sub(r"[^\w.,& ]", " ", _n(s).title())
    return re.sub(r"\s+", " ", s).strip()[:k].strip()


def carregar_registro(pasta: Path) -> dict:
    try:
        dados = json.loads((Path(pasta) / ARQUIVO).read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def preparar(pasta, log=print, ocr=ocr_linhas, codigos=None) -> dict:
    """Gera os PDFs no padrão para as fotos e PDFs fora do padrão da pasta.

    `codigos(texto, valores, ocr) -> set` é a busca do código de barras (o
    `codigo_barras.codigos_no_texto`, que chega por argumento para este módulo
    não depender dele). Devolve as contagens para o Registro da aba."""
    pasta = Path(pasta)
    registro = carregar_registro(pasta)
    fontes_feitas = {v.get("fonte") for v in registro.values()}
    hashes = {v.get("md5") for v in registro.values()}
    ids = {v.get("id") for v in registro.values() if v.get("id")}
    boletos = {f"{k.rsplit(' - ', 1)[-1][:5]}|{','.join(v.get('barras') or [])}"
               for k, v in registro.items() if v.get("barras")}
    cont = {"lidos": 0, "gerados": 0, "repetidos": 0, "ilegiveis": 0, "leitores": {}}
    for caminho in sorted(pasta.iterdir()):
        nome = caminho.name
        if not caminho.is_file() or nome.startswith(".") or nome in fontes_feitas:
            continue
        ext = caminho.suffix.lower()
        if ext not in _EXT_IMAGEM and not (ext == ".pdf" and _fora_do_padrao(nome)):
            continue
        if nome in registro:          # um PDF que este módulo mesmo gerou
            continue
        md5 = hashlib.md5(caminho.read_bytes()).hexdigest()
        cont["lidos"] += 1
        if md5 in hashes:
            cont["repetidos"] += 1
            continue
        try:
            linhas, leitor, pdf = _linhas_do_arquivo(caminho, ocr)
        except Exception as e:        # noqa: BLE001 -- um arquivo ruim não para a pasta
            log(f"[aviso] não li {nome}: {e}")
            cont["ilegiveis"] += 1
            continue
        cont["leitores"][leitor] = cont["leitores"].get(leitor, 0) + 1
        info = ler(linhas)
        if info["id"] and info["id"] in ids:
            cont["repetidos"] += 1
            hashes.add(md5)
            continue
        if not info["valor"] or not info["data"]:
            log(f"[aviso] {nome}: não achei {'o valor' if not info['valor'] else 'a data'}"
                " no comprovante — fica de fora; renomeie à mão se for pagamento.")
            cont["ilegiveis"] += 1
            continue
        barras = sorted(codigos("\n".join(linhas), {info["valor"]}, leitor not in ("texto", ""))
                        if codigos else ())
        # Boleto reenviado: sem o identificador do Pix, o mesmo código de barras
        # no mesmo dia é o mesmo pagamento (o código é único por boleto). Sem
        # código, NÃO se junta: dois pagamentos iguais no mesmo minuto existem.
        chave_boleto = f"{info['data']}|{','.join(barras)}" if barras else ""
        if chave_boleto and chave_boleto in boletos:
            cont["repetidos"] += 1
            hashes.add(md5)
            continue
        valor = f"{info['valor'] / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        base = f"{valor} - {_limpo(info['recebedor']) or 'Comprovante'} - {info['data']}"
        destino = pasta / f"{base}.pdf"
        k = 2
        while destino.exists() or destino.name in registro:
            destino = pasta / f"{base} ({k}).pdf"
            k += 1
        destino.write_bytes(pdf)
        registro[destino.name] = {
            "fonte": nome, "md5": md5, "id": info["id"], "leitor": leitor,
            "banco": info["banco"], "pagador": info["pagador"], "recebedor": info["recebedor"],
            "hora": info["hora"], "barras": barras}
        hashes.add(md5)
        if info["id"]:
            ids.add(info["id"])
        if chave_boleto:
            boletos.add(chave_boleto)
        cont["gerados"] += 1
    if cont["gerados"]:
        (pasta / ARQUIVO).write_text(json.dumps(registro, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    return cont
