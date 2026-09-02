# -*- coding: utf-8 -*-
"""
Separa PDFs (uma página = um arquivo) e renomeia os comprovantes.

Modelo de nome PADRÃO:

  - com Descrição/Observação (centro de custo + OC/NF):  VALOR - DESCRIÇÃO - DATA
  - aporte/distribuição/transferência:                   VALOR - QUEM PAGOU PARA QUEM RECEBEU - DATA
  - PIX sem descrição (fornecedor):                       VALOR - QUEM RECEBEU - DATA

Também aceita um modelo personalizado escrito com as palavras-chave
VALOR, DESCRIÇÃO, DATA, PAGADOR e RECEBEDOR (ex.: "DATA - VALOR - RECEBEDOR").

Cobre SICOOB (PIX / Boleto / Convênio) e Inter (PIX / Pagamento / Boleto-Guia).
Todos os arquivos renomeados vão para UMA pasta só.
"""
import os
import re
import queue
import threading
from pathlib import Path

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

MODELO_PADRAO = "VALOR - DESCRIÇÃO - DATA"

_sem_acento = util.sem_acento
_fmt_dur = util.fmt_dur


# ------------------------------------------------------------ extração
def _linhas(t): return [l.rstrip() for l in t.splitlines()]

def detectar(t):
    u = t.upper()
    if 'PIX ENVIADO' in u: return ('INTER', 'PIX')
    if 'PAGAMENTO REALIZADO' in u: return ('INTER', 'PGTO')
    if 'EFETIVAÇÃO DE PAGAMENTO PIX' in u or 'EFETIVACAO DE PAGAMENTO PIX' in u: return ('SICOOB', 'PIX')
    if 'PAGAMENTO DE BOLETO' in u: return ('SICOOB', 'BOLETO')
    if 'PAGAMENTO DE CONVÊNIO' in u or 'PAGAMENTO DE CONVENIO' in u: return ('SICOOB', 'CONVENIO')
    return ('?', '?')

def _valor(t):
    # sem o (?i) o comprovante de tributo/DARF do Sicoob, que escreve
    # "VALOR TOTAL: R$ 240,22" em caixa alta, saía sem valor nenhum
    for pat in [r'(?i)Valor\s+total\s*:?\s*R\$\s*([\d\.]+,\d{2})',
                r'(?i)Valor\s*:\s*R\$\s*([\d\.]+,\d{2})',
                r'(?i)Pago\s*:\s*R\$\s*([\d\.]+,\d{2})',
                r'(?m)^\s*R\$\s*([\d\.]+,\d{2})\s*$']:
        m = re.search(pat, t)
        if m: return m.group(1)
    return None

def _data(t):
    # o Inter escreve o dia da semana antes da data ("Sexta, 31/07/2026" e
    # também "Segunda-feira, ..."), por isso a folga generosa antes do dígito
    for pat in [r'(?i)Data\s+d[eo]\s+pagamento[^\d]{0,24}(\d{2}/\d{2}/\d{4})',
                r'(?i)Realizado\s*:\s*(\d{2}/\d{2}/\d{4})']:
        m = re.search(pat, t)
        if m: return m.group(1)
    return None

def _nome_apos(t, rotulo):
    i = t.find(rotulo)
    if i < 0: return None
    m = re.search(r'Nome(?:/Raz[ãa]o\s*[Ss]ocial)?:?\s*(.+)', t[i:])
    return m.group(1).strip() if m else None

RE_TRIBUTO = re.compile(
    r"\bPAGAMENTO\s+(?:DARF|DAS|GPS|FGTS|GRU|GNRE|DAM|IPVA|ITBI|TRIBUTOS?)\b",
    re.I)


def _descricao(t, banco):
    if banco == 'INTER':
        m = re.search(r'(?m)^\s*Descri[çc][ãa]o\s*:?[ \t]+(.+)', t)
        if m:
            return m.group(1).strip() or None
    L = _linhas(t)
    for i, l in enumerate(L):
        m = re.match(r'(?:Descri[çc][ãa]o|Observa[çc][ãa]o):\s*(.*)', l.strip())
        if m:
            resto = m.group(1).strip()
            if resto:
                return resto
            # rótulo sozinho na linha: o valor pode estar na linha vizinha —
            # mas só se a vizinha for texto de verdade, e não outro rótulo
            for viz in (L[i + 1].strip() if i + 1 < len(L) else '',
                        L[i - 1].strip() if i > 0 else ''):
                if viz and not viz.endswith(':') and not _lixo(viz):
                    return viz
            return None
    # tributo/guia não tem campo de descrição: o tipo do pagamento é o que
    # sobra para identificar o comprovante ("PAGAMENTO DARF")
    m = RE_TRIBUTO.search(t)
    return m.group(0).strip() if m else None

def _limpar_empresa(nome):
    if not nome: return ''
    nome = _sem_rotulo(nome)
    if _lixo(nome):            # rótulo técnico (CPF/CNPJ, Instituição...) não é nome
        return ''
    nome = re.sub(r'\b(LTDA|SPE|S/?A|S\.A|EIRELI|ME|EPP)\b\.?', '', nome, flags=re.I)
    return re.sub(r'\s+', ' ', nome).strip(' .-')

def _campos_rotulado(t):
    """Layout clássico: cada rótulo traz o valor NA MESMA LINHA
    (ex.: 'Descrição CENTRO DE CUSTO QD 26A LT 10 OC 1234')."""
    banco, tipo = detectar(t)
    v = _valor(t); d = _data(t); desc = _descricao(t, banco)
    if banco == 'INTER':
        pag = _nome_apos(t, 'Quem pagou'); dest = _nome_apos(t, 'Quem recebeu')
    else:
        pag = _nome_apos(t, 'Pagador')
        dest = _nome_apos(t, 'Destinat') or _nome_apos(t, 'Beneficiário') or _nome_apos(t, 'Beneficiario')
    return dict(banco=banco, tipo=tipo, valor=v, data=d, desc=desc, pag=pag, dest=dest)


# rótulo com o valor colado na mesma linha -> layout clássico ("rotulado").
# No layout "impresso" o rótulo fica sozinho na linha e o valor vem só depois,
# num bloco separado. Fora da lista: "Nome", porque o Sicoob impresso tem
# "Nome Fantasia:" e "Nome/Razão Social:" — rótulos que parecem ter valor.
RE_ROTULO_INLINE = re.compile(
    r'(?mi)^[ \t]*(?:Descri[çc][ãa]o|Observa[çc][ãa]o|Data\s+do\s+pagamento|'
    r'Valor\s+total)\s*:?[ \t]+(\S.*?)[ \t]*$')


def _tem_rotulo_inline(t) -> bool:
    """True se algum rótulo traz o valor na MESMA linha (layout clássico).
    Um 'valor' que é só outro rótulo (termina em ':') não conta."""
    return any(m.group(1) and not m.group(1).endswith(":")
               for m in RE_ROTULO_INLINE.finditer(t))


def campos(t):
    """Extrai os campos escolhendo o parser pelo LAYOUT — não pelo banco.

    O comprovante do Inter (PIX e Pagamento) traz 'Sobre a transação' e
    'Banco Inter' mesmo quando é o layout clássico, então detectar o banco
    não serve para escolher o parser: o que separa os dois layouts é o
    rótulo trazer (ou não) o valor na mesma linha.
    """
    rot = _campos_rotulado(t)
    imp = _campos_impresso(t)
    tem_rotulo = _tem_rotulo_inline(t)
    if tem_rotulo and rot['valor'] and (rot['desc'] or rot['dest']):
        escolhido, reserva = rot, imp
    elif imp and imp['valor']:
        escolhido, reserva = imp, rot
    else:
        escolhido, reserva = rot, imp
    if reserva:                # completa só o que é objetivo e sem ambiguidade
        for campo in ('valor', 'data'):
            if not escolhido.get(campo):
                escolhido[campo] = reserva.get(campo)
    return escolhido


# --------------------------------------------- layout "impresso" (2026)
# Sicoob Internet Banking e Inter novos geram o comprovante como página
# impressa: rótulos e valores vêm em blocos separados (e o PDF muitas
# vezes nem tem camada de texto — aí entra o OCR).
RE_DIN_L = re.compile(r"^\s*R[S$]?\$?\s*([\d\.]+,\d{2})\s*$")
RE_DATA_HORA = re.compile(r"(\d{2}/\d{2}/\d{4})\s+(?:[àa]s\s+)?\d{2}[:h]\d{2}")
RE_DATA_SO = re.compile(r"^(\d{2}/\d{2}/\d{4})$")
RE_CNPJ_L = re.compile(r"\d{2}[\.\s]?\d{3}[\.\s]?\d{3}\s?/\s?\d{4}\s?-\s?\d{2}")
RE_DESC_SITE = re.compile(r"\b(QD|LT|OC|NF|UC|LOTE|APORTE|DISTRIBUI\w*|REF)\b")
# centro de custo / OC / NF valem mais que APORTE|DISTRIBUI|REF, que também
# aparecem em razão social ("FORNECEDOR DISTRIBUIDORA DE MAT") e roubavam a
# vez da observação verdadeira ("CENTRO DE CUSTO QD 18 LT 8 OC 1234")
RE_DESC_FORTE = re.compile(r"\b(QD|LT|OC|NF|UC|LOTE)\b")
# o comprovante "impresso" vira curvas vetoriais e o OCR come os espaços do
# centro de custo: "TB 21 QD 51 LT 23 C 282 M 3" chega "TB21QD51LT23C282M3".
# Sem \b nenhuma regra acima reconhece isso — daí esta versão "colada".
RE_DESC_COLADO = re.compile(r"(?:QD|LT|OC|NF)\s*\d", re.I)
# token único, sem espaço, misturando letra e número: candidato a código
RE_COD_COLADO = re.compile(r"^(?=[^\d]*\d)(?=[^A-Za-z]*[A-Za-z])[A-Za-z0-9]{8,}$")
RE_ID_LONGO = re.compile(r"^[A-Za-z0-9\-]{20,}$")
# rótulo que às vezes vem grudado na descrição — sai do nome do arquivo
RE_ROTULO_DESC = re.compile(
    r"^\s*(?:Descri[çc][ãa]o|Observa[çc][ãa]o|Hist[óo]rico)\s*:?\s*", re.I)
# linhas que NUNCA servem como descrição/nome de quem pagou ou recebeu:
# são rótulos técnicos do comprovante (foi daí que saíram nomes de arquivo
# como "Instituição Banco Inter" e "Autenticação <código>")
# o \b em todas as alternativas é o que impede engolir nome de verdade
# ("Contabilidade XYZ" não é o rótulo "Conta")
RE_LIXO_NOME = re.compile(
    r"^\s*(?:Institui[çc][ãa]o\b|CPF\s*/?\s*CNPJ\b|CPF\b|CNPJ\b|Ag[êe]ncia\b|"
    r"Conta\b|Autentica[çc][ãa]o\b|Identificador\b|ID\b|C[óo]digo\s+de\s+barras\b|"
    r"Canal\b|Banco\s+cedente\b|Data\s+d[ao]\s+\w+|Hor[áa]rio\b|"
    r"N[úu]mero\s+do\s+documento\b|Valor\b|Tipo\b|Comprovante\b|"
    r"Sobre\s+a\s+transa|Quem\s+(?:pagou|recebeu)\b)",
    re.I)


RE_ROTULO_NOME = re.compile(r"^\s*Nome(?:/Raz[ãa]o\s*Social)?\s*:?\s*", re.I)


def _sem_rotulo(l) -> str:
    """Tira o rótulo grudado no começo da linha ('Nome X' -> 'X')."""
    l = RE_ROTULO_NOME.sub("", (l or "").strip())
    return RE_ROTULO_DESC.sub("", l).strip()


def _espacar_token(t) -> str:
    if not RE_COD_COLADO.match(t) or not RE_DESC_COLADO.search(t):
        return t
    return re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", t)


def _espacar_codigo(s) -> str:
    """'TB21QD51LT23C282M3' -> 'TB 21 QD 51 LT 23 C 282 M 3'.

    Vale por palavra, então também conserta a descrição meio colada
    ('DONA MORENA QD 18LT811B1C259M5'). Só mexe em palavra longa que misture
    letra e número E tenha cara de centro de custo; texto normal passa
    intacto. Isso importa para o casamento: o matcher procura 'QD <n> LT <n>'
    e, sem os espaços que o OCR comeu, ele não enxerga o centro de custo."""
    s = (s or "").strip()
    if not s or not RE_DESC_COLADO.search(s):
        return s
    return " ".join(_espacar_token(t) for t in s.split())


def _lixo(l) -> bool:
    """True se a linha é rótulo técnico/ID e não serve como nome ou descrição."""
    if not l or len(l.strip()) < 3:
        return True
    l = l.strip()
    return bool(RE_LIXO_NOME.match(l)) or bool(RE_ID_LONGO.match(l))


def _eh_mascara(l):
    """CPF/CNPJ mascarado (ex.: **.168.971/0001-** com ruído de OCR)."""
    return "*" in l and sum(c.isdigit() for c in l) >= 4 and len(l) < 30


# CPF/CNPJ que o OCR entregou torto (ex.: "00.394,460/0058-87" com vírgula no
# lugar do ponto): linha só de dígitos e pontuação, com cara de documento
RE_DOC_L = re.compile(r"^[\d\.\,\-/\s]{11,20}$")


def _eh_documento(l):
    l = l.strip()
    return bool(RE_DOC_L.match(l)) and sum(c.isdigit() for c in l) >= 11


def _nomes_antes_do_documento(nl):
    """No layout impresso os nomes vêm logo ANTES do CPF/CNPJ. Devolve-os na
    ordem em que aparecem, pulando rótulos técnicos."""
    nomes = []
    for i, l in enumerate(nl):
        if i == 0 or not (RE_CNPJ_L.search(l) or _eh_mascara(l) or _eh_documento(l)):
            continue
        for j in range(i - 1, -1, -1):
            cand = _sem_rotulo(nl[j])
            if RE_CNPJ_L.search(cand) or _eh_mascara(cand) or _eh_documento(cand):
                continue
            if len(cand) > 4 and not RE_DIN_L.match(cand) and not _lixo(cand):
                if cand not in nomes:
                    nomes.append(cand)
                break
    return nomes


def _detectar_impresso(t):
    u = _sem_acento(t).upper()
    if "SICOOB" in u and ("INTERNET BANKING" in u or "SISBR" in u
                          or "TIPO PAGAMENTO" in u):
        if "PAGAMENTO DE BOLETO" in u:
            return ("SICOOB", "BOLETO")
        if "PAGAMENTO PIX" in u or "TIPO PAGAMENTO" in u:
            return ("SICOOB", "PIX")
        return ("SICOOB", "?")
    if "SOBRE A TRANSA" in u or "FALE COM A GENTE" in u or "BANCO INTER" in u:
        return ("INTER", "PGTO")
    return (None, None)


def _campos_impresso(t):
    banco, tipo = _detectar_impresso(t)
    if not banco:
        return None
    nl = [l.strip() for l in t.splitlines() if l.strip()]

    # valor: último R$ não-zero em linha própria (boleto: é o "Pago";
    # Inter: é o "Valor total"; PIX: é o único)
    valores = [m.group(1) for l in nl for m in [RE_DIN_L.match(l)] if m]
    naozero = [v for v in valores
               if v.replace(".", "").replace(",", "").strip("0") != ""]
    valor = naozero[-1] if naozero else (valores[-1] if valores else None)

    # data: prioriza data com hora (o cabeçalho de impressão usa vírgula
    # e fica de fora); senão, data sozinha fora das 3 primeiras linhas
    datas = RE_DATA_HORA.findall(t)
    if not datas:
        for i, l in enumerate(nl):
            if i >= 3:
                m = RE_DATA_SO.match(l)
                if m:
                    datas.append(m.group(1))
    data = max(datas, key=lambda d: (datas.count(d), -datas.index(d))) if datas else None

    # descrição: primeiro a linha rotulada ("Descrição X"), que é a fonte
    # certa; só depois o palpite pela cara de centro de custo / OC / NF...
    desc = None
    for l in nl:
        if RE_ROTULO_DESC.match(l):
            cand = RE_ROTULO_DESC.sub("", l).strip()
            if cand and not _lixo(cand):
                desc = cand
                break
    if desc is None:
        for regra in (RE_DESC_FORTE, RE_DESC_COLADO, RE_DESC_SITE):
            for l in nl:
                u = _sem_acento(l).upper()
                if regra.search(u) and not RE_ID_LONGO.match(l) and len(l) < 90 \
                        and "OUVIDORIA" not in u and "COMPROVANTE" not in u:
                    desc = RE_ROTULO_DESC.sub("", l).strip() or None
                    break
            if desc:
                break
    if desc is None and banco == "SICOOB" and tipo == "PIX" and valor:
        # ...ou, no PIX, a linha logo depois do valor
        for i, l in enumerate(nl):
            if RE_DIN_L.match(l):
                if i + 1 < len(nl):
                    cand = nl[i + 1]
                    u = _sem_acento(cand).upper()
                    digitos = sum(c.isdigit() for c in cand) / max(len(cand), 1)
                    # o corte por proporção de dígitos existe para barrar
                    # código/hash, mas centro de custo também é cheio de
                    # número ("TB21QD51LT23C282M3", 58% dígitos) — por isso
                    # ele vale só quando não há cara de centro de custo
                    if not RE_ID_LONGO.match(cand) and len(cand) > 2 \
                            and not u.startswith("FINALIZADO") \
                            and not u.startswith("OUVIDORIA") \
                            and "{" not in cand and "}" not in cand \
                            and (digitos < 0.4 or RE_DESC_COLADO.search(u)):
                        desc = cand
                break

    pag = dest = None
    if banco == "SICOOB":
        if tipo == "BOLETO":
            # nomes: linha imediatamente anterior a cada CNPJ completo
            nomes = []
            for i, l in enumerate(nl):
                if RE_CNPJ_L.search(l):
                    for j in range(i - 1, -1, -1):
                        cand = _sem_rotulo(nl[j])
                        if not RE_CNPJ_L.search(cand) and len(cand) > 4 \
                                and not RE_DIN_L.match(cand) and not _lixo(cand):
                            if cand not in nomes:
                                nomes.append(cand)
                            break
            dest = nomes[0] if nomes else None           # beneficiário
            pag = nomes[1] if len(nomes) > 1 else None   # pagador
        else:  # PIX: nome vem na linha anterior ao CPF/CNPJ (mascarado)
            nomes = []
            for i, l in enumerate(nl):
                if (_eh_mascara(l) or RE_CNPJ_L.search(l)) and i > 0:
                    cand = _sem_rotulo(nl[i - 1])
                    if not _lixo(cand):
                        nomes.append(cand)
            pag = nomes[0] if nomes else None
            dest = nomes[1] if len(nomes) > 1 else None
    else:  # INTER novo — "Quem pagou" vem antes de "Quem recebeu"
        nomes = _nomes_antes_do_documento(nl)
        pag = nomes[0] if nomes else None
        dest = nomes[1] if len(nomes) > 1 else None
        if dest is None:      # sem o 2º documento: último nome antes do rodapé
            for i, l in enumerate(nl):
                u = _sem_acento(l).upper()
                if u.startswith("FALE COM A GENTE") or u.startswith("CAPITAIS E REGI"):
                    for j in range(i - 1, -1, -1):
                        cand = _sem_rotulo(nl[j])
                        if len(cand) > 4 and not RE_DIN_L.match(cand) \
                                and not cand.isdigit() and not _lixo(cand) \
                                and cand != pag:
                            dest = cand
                            break
                    break
    return dict(banco=banco, tipo=tipo, valor=valor, data=data, desc=desc,
                pag=pag, dest=dest)


# --------------------------------------------------------------- OCR
_OCR = {"pronto": None, "lang": "por", "avisado": False}


def _configurar_ocr() -> bool:
    try:
        import pytesseract
    except ImportError:
        return False
    import shutil
    import sys
    cands = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        cands.append(Path(base) / "tesseract" / "tesseract.exe")
    cands.append(Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"))
    achado = shutil.which("tesseract")
    if achado:
        cands.append(Path(achado))
    for c in cands:
        if c.exists():
            pytesseract.pytesseract.tesseract_cmd = str(c)
            tess = c.parent / "tessdata"
            if tess.is_dir():
                os.environ["TESSDATA_PREFIX"] = str(tess)
            # uma thread por processo do Tesseract: quem paraleliza é o nosso
            # pool (_ocr_em_lote). Sem isso, cada chamada tenta usar todos os
            # núcleos e as chamadas simultâneas brigam entre si.
            os.environ.setdefault("OMP_THREAD_LIMIT", "1")
            try:
                langs = set(pytesseract.get_languages(config=""))
            except Exception:
                langs = set()
            _OCR["lang"] = "por" if "por" in langs else "eng"
            return True
    return False


def _ocr_pagina(pagina, log=print, resolucao: int = 300) -> str:
    """OCR de UMA página sem camada de texto (comprovantes 'impressos').
    Para um PDF inteiro use _textos_das_paginas, que paraleliza."""
    if not _ocr_disponivel(log):
        return ""
    import pytesseract
    img = pagina.to_image(resolution=resolucao).original
    return pytesseract.image_to_string(img, lang=_OCR["lang"])


def _ocr_disponivel(log) -> bool:
    if _OCR["pronto"] is None:
        _OCR["pronto"] = _configurar_ocr()
    if not _OCR["pronto"] and not _OCR["avisado"]:
        log("[aviso] Comprovante sem texto e OCR indisponível — use o "
            "executável (já traz o OCR) ou instale o Tesseract OCR.")
        _OCR["avisado"] = True
    return bool(_OCR["pronto"])


def _n_workers_ocr() -> int:
    return min(8, max(2, os.cpu_count() or 4))


def _ocr_em_lote(pl, indices, log, resolucao=300, ao_concluir=None) -> dict:
    """OCR de várias páginas: renderiza em SÉRIE e reconhece em PARALELO.

    A renderização usa pypdfium2, que não é thread-safe, então fica na thread
    principal (é barata: ~0,1s por página). O Tesseract roda em subprocesso e
    solta o GIL, então o pool ganha de verdade — medido nos comprovantes
    reais: 0,96s por página em série contra 0,29s com 6 threads."""
    if not indices or not _ocr_disponivel(log):
        return {}
    import pytesseract
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    lang = _OCR["lang"]
    n = _n_workers_ocr()
    saida = {}

    def reconhecer(img):
        try:
            return pytesseract.image_to_string(img, lang=lang)
        except Exception as e:
            log(f"[ERRO] OCR: {e}")
            return ""

    def colher(futuros):
        for f in futuros:
            saida[pendentes.pop(f)] = f.result()
            if ao_concluir:
                ao_concluir()

    with ThreadPoolExecutor(max_workers=n) as ex:
        pendentes = {}
        for i in indices:
            # segura a produção: uma página a 300 dpi ocupa ~11 MB, não dá
            # para renderizar um PDF de 100 páginas todo de uma vez
            while len(pendentes) >= n * 2:
                prontos, _ = wait(pendentes, return_when=FIRST_COMPLETED)
                colher(prontos)
            try:
                img = pl.pages[i].to_image(resolution=resolucao).original
            except Exception as e:
                log(f"[ERRO] renderizar pág {i+1}: {e}")
                if ao_concluir:
                    ao_concluir()
                continue
            pendentes[ex.submit(reconhecer, img)] = i
        colher(list(pendentes))
    return saida


def _textos_das_paginas(pl, n, log=print, ao_concluir=None):
    """(texto, origem) de cada página — origem é '' | 'OCR' | 'OCR 400'.

    Páginas sem camada de texto vão para o OCR em lote a 300 dpi. As que
    ainda assim não produzirem descrição repetem a 400 dpi: em comprovante
    "impresso" (o texto virou curva vetorial) a resolução maior às vezes
    separa o centro de custo que a 300 dpi funde — e sem descrição o nome cai
    no de quem recebeu. Não usamos 400 dpi sempre porque é ~2x mais lento e,
    medido nos comprovantes reais, cada resolução acerta um conjunto
    diferente; como segunda tentativa, porém, só tem a ganhar."""
    saida = []
    faltam = []
    for i in range(n):
        try:
            t = pl.pages[i].extract_text() or ""
        except Exception as e:
            log(f"[ERRO] ler texto da pág {i+1}: {e}")
            t = ""
        saida.append((t, ""))
        if len(t.strip()) < 30:
            faltam.append(i)
        elif ao_concluir:
            ao_concluir()
    for i, t in _ocr_em_lote(pl, faltam, log, 300, ao_concluir).items():
        if t.strip():
            saida[i] = (t, "OCR")
    retentar = [i for i in faltam
                if saida[i][1] == "OCR" and not campos(saida[i][0]).get("desc")]
    for i, t in _ocr_em_lote(pl, retentar, log, 400).items():
        if t.strip() and campos(t).get("desc"):
            saida[i] = (t, "OCR 400")
    return saida

def _partes_nome(c, com_recebedor: bool = False):
    """Retorna (valor, 'miolo' inteligente do nome, data dd-mm).

    com_recebedor acrescenta quem recebeu ao miolo — serve para separar dois
    comprovantes de mesmo valor e mesma descrição (ex.: dois "ENGENHEIRO" de
    R$ 6.000,00 no mesmo dia, para pessoas diferentes)."""
    v = (c['valor'] or 'SEM VALOR').replace('.', '')
    dd = ''
    if c['data']:
        p = c['data'].split('/'); dd = p[0] + '-' + p[1]
    desc = _espacar_codigo(_sem_rotulo(c['desc'])) or None
    aporte = re.search(r'\b(APORTE|DISTRIBUI|TRANSF)', (desc or '').upper())
    dest = _limpar_empresa(c['dest'])
    if desc and not aporte:
        meio = desc
    else:
        pag = _limpar_empresa(c['pag'])
        if desc and aporte and pag and dest:
            meio = f"{pag} PARA {dest}"
        elif dest:
            meio = dest
        else:
            meio = desc or 'SEM DESCRICAO'
    meio = re.sub(r'\s+', ' ', (meio or '')).strip()
    if com_recebedor and dest and _sem_acento(dest).upper() not in _sem_acento(meio).upper():
        meio = f"{meio} - {dest}"
    return v, meio, dd

def nome_arquivo(c, modelo: str | None = None,
                 com_recebedor: bool = False) -> str:
    """Monta o nome do arquivo. modelo=None (ou igual ao padrão) usa o
    comportamento clássico; senão substitui as palavras-chave do modelo."""
    usar_padrao = not modelo or modelo.strip().upper() in ("", MODELO_PADRAO.upper())
    if com_recebedor and not usar_padrao and re.search(r'RECEBEDOR', modelo, re.I):
        com_recebedor = False          # o modelo já pede o recebedor
    v, meio, dd = _partes_nome(c, com_recebedor)
    if usar_padrao:
        partes = [v] + ([meio] if meio else []) + ([dd] if dd else [])
        nome = ' - '.join(partes)
    else:
        nome = modelo
        for token, valor in (("DESCRIÇÃO", meio), ("DESCRICAO", meio),
                             ("RECEBEDOR", _limpar_empresa(c['dest']) or 'SEM RECEBEDOR'),
                             ("PAGADOR", _limpar_empresa(c['pag']) or 'SEM PAGADOR'),
                             ("VALOR", v),
                             ("DATA", dd or 'SEM DATA')):
            nome = nome.replace(token, valor)
        nome = re.sub(r'\s+', ' ', nome)
    nome = re.sub(r'[<>:"/\\|?*]', '', nome).strip()
    return nome[:150] or 'SEM DADOS'


# ------------------------------------------------------------ processamento
def _destino_unico(pasta: Path, base: str) -> Path:
    alvo = pasta / f"{base}.pdf"; n = 2
    while alvo.exists():
        alvo = pasta / f"{base} ({n}).pdf"; n += 1
    return alvo

def _contar_paginas(pdfs, log) -> int:
    """Total de páginas, para a barra de progresso saber onde é o fim.
    Só lê o índice do PDF (rápido), não o conteúdo."""
    # import tardio: só quem separa paga o pypdf
    from pypdf import PdfReader
    total = 0
    for p in pdfs:
        try:
            total += len(PdfReader(str(p)).pages)
        except Exception:
            pass                    # o erro real aparece ao processar
    return total


def _nomes_finais(lista_campos, modelo=None, ja_existe=None) -> list[str]:
    """Nome de cada comprovante, decidido olhando o lote INTEIRO.

    Quando dois comprovantes caem no mesmo nome (mesmo valor, mesma descrição,
    mesmo dia), TODOS eles ganham o nome de quem recebeu — não só o segundo.
    Deixar um sem o nome não ajudaria nem quem lê a pasta nem o casamento
    automático, que precisa distinguir os dois para não anexar trocado."""
    from collections import Counter
    bases = [nome_arquivo(c, modelo) for c in lista_campos]
    quantos = Counter(bases)
    finais = []
    for c, base in zip(lista_campos, bases):
        repete = quantos[base] > 1 or (ja_existe(base) if ja_existe else False)
        finais.append(nome_arquivo(c, modelo, com_recebedor=True)
                      if repete else base)
    return finais


def processar(pasta_entrada, pasta_saida, log=print, modelo: str | None = None,
              progresso=None, parar=None):
    """Separa e renomeia. `parar` é uma função que responde "pare agora?".

    Sem ela, a única maneira de interromper era matar a thread — e matar no
    meio da 2ª passada, a que GRAVA, deixa PDF pela metade na pasta de saída e
    nenhum registro do que aconteceu. Com ela, a parada acontece entre um
    arquivo e outro (1ª passada) ou entre uma página e outra (2ª), que são os
    dois instantes em que nada está pela metade.

    Parar durante a LEITURA não grava nada: os nomes só podem ser decididos
    com o lote inteiro na mão (ver `_nomes_finais`), e gravar meio lote daria
    nomes diferentes dos que sairiam ao rodar tudo de novo."""
    # import tardio: só quem separa paga o pdfplumber e o pypdf
    import pdfplumber
    from pypdf import PdfReader, PdfWriter
    parou = parar or (lambda: False)
    pasta_entrada = Path(pasta_entrada); pasta_saida = Path(pasta_saida)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    pdfs = [p for p in sorted(pasta_entrada.glob("*.pdf"))
            if pasta_saida not in p.parents and p.parent != pasta_saida]
    total_paginas = 0; erros = 0; sem_descricao = []; paginas_lidas = 0
    total_esperado = _contar_paginas(pdfs, log)
    log(f"{len(pdfs)} arquivo(s) PDF na pasta de entrada, "
        f"{total_esperado} página(s).")
    if progresso:
        progresso(0, total_esperado)

    # ---- 1ª passada: lê tudo. É aqui que mora o OCR (em lote, paralelo) e
    # é aqui que o tempo passa. Guarda só os campos — texto não fica retido.
    itens = []                                    # (pdf_path, pág, campos)
    for pdf_path in pdfs:
        # Entre arquivos: é a granularidade que dá para ter sem interromper um
        # lote de OCR já em voo (o pool interno de `_textos_das_paginas` lê o
        # arquivo inteiro antes de devolver).
        if parou():
            log("\n⏹ Interrompido durante a leitura — nada foi gravado.")
            return 0, erros
        try:
            pl = pdfplumber.open(str(pdf_path))   # abre UMA vez por arquivo
        except Exception as e:
            log(f"[ERRO] abrir {pdf_path.name}: {e}"); erros += 1; continue
        with pl:
            def _uma_lida():
                nonlocal paginas_lidas
                paginas_lidas += 1
                if progresso:
                    progresso(paginas_lidas, total_esperado)

            n = len(pl.pages)
            for i, (txt, via) in enumerate(_textos_das_paginas(pl, n, log,
                                                               _uma_lida)):
                if via:
                    log(f"  [{via}] {pdf_path.name} pág {i+1}")
                itens.append((pdf_path, i, campos(txt)))

    if parou():
        log("\n⏹ Interrompido antes de gravar — nada foi gravado.")
        return 0, erros

    # ---- os nomes só podem ser decididos com o lote todo na mão: é o que
    # permite dar o nome de quem recebeu aos DOIS de um valor repetido
    finais = _nomes_finais([c for _, _, c in itens], modelo,
                           lambda b: (pasta_saida / f"{b}.pdf").exists())

    # ---- 2ª passada: grava (rápido). Reabre cada PDF uma vez só.
    por_arquivo = {}
    for (pdf_path, i, c), base in zip(itens, finais):
        por_arquivo.setdefault(pdf_path, []).append((i, c, base))
    interrompido = False
    for pdf_path, paginas in por_arquivo.items():
        if parou():
            interrompido = True
            break
        try:
            reader = PdfReader(str(pdf_path))
        except Exception as e:
            log(f"[ERRO] abrir {pdf_path.name}: {e}")
            erros += len(paginas); continue
        for i, c, base in paginas:
            # ENTRE páginas, nunca no meio de uma: gravar um PDF de uma página
            # leva milissegundos, então quem pediu para parar espera pouco e a
            # pasta de saída nunca fica com arquivo pela metade.
            if parou():
                interrompido = True
                break
            try:
                w = PdfWriter(); w.add_page(reader.pages[i])
                destino = _destino_unico(pasta_saida, base)
                with open(destino, 'wb') as fh:
                    w.write(fh)
                total_paginas += 1
                if not c.get('desc'):
                    sem_descricao.append(destino.name)
            except Exception as e:
                log(f"[ERRO] {pdf_path.name} pág {i+1}: {e}"); erros += 1
    log(f"\n{'⏹ Interrompido' if interrompido else 'Concluído'}: "
        f"{total_paginas} comprovante(s) gerado(s) em "
        f"{str(pasta_saida).replace(chr(92), '/')}"
        + (f" | {erros} erro(s)" if erros else "")
        + (" — o resto não foi gravado; rode de novo para completar."
           if interrompido else ""))
    if sem_descricao:
        # sem descrição o nome cai em quem recebeu, e o casamento automático
        # perde OC/NF e centro de custo — vale a pena o usuário saber quais são
        log(f"\n{len(sem_descricao)} comprovante(s) sem descrição no banco — "
            f"o nome usou quem recebeu. Confira se precisa ajustar à mão:")
        for n in sem_descricao[:20]:
            log(f"   • {n}")
        if len(sem_descricao) > 20:
            log(f"   ... e mais {len(sem_descricao) - 20}")
    return total_paginas, erros


# ------------------------------------------------------------ GUI
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:                                     # widgets compartilhados (raiz)
    import widgets
except ModuleNotFoundError:              # rodando este módulo isoladamente
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import widgets


class SepararFrame(ttk.Frame):
    """Conteúdo do app Separar e Renomear (usável sozinho ou como aba)."""

    def __init__(self, master):
        super().__init__(master)
        self.ent, self.sai = tk.StringVar(), tk.StringVar()
        self.v_tipo_nome = tk.StringVar(value="padrao")
        self.v_modelo = tk.StringVar(value=MODELO_PADRAO)
        self.fila = queue.Queue()
        # A thread do processamento, o pedido de parada e o que a barra
        # lateral mostra. Antes a thread era anônima: ninguém de fora sabia
        # que ela existia, então a barra não acendia nada num OCR de 107
        # páginas e sair do app a matava no meio da gravação.
        self._thread = None
        self._parar = threading.Event()
        self._tarefa_atual = ""
        # Último motivo de falha do `_drain`, para não repetir a mesma linha a
        # cada 150 ms (ver o `except` de lá).
        self._erro_drain = None
        #: A linha de fecho do último lote (ver `_drenar`).
        self._resumo = ""
        self._montar()
        try:                             # já nasce na cor do tema (sem flash)
            self.aplicar_cores(util.cor_escura(ttk.Style().lookup("TFrame", "background")))
        except Exception:
            pass
        self.after(150, self._drain)

    def _montar(self):
        PADX = widgets.PADX

        # ---- cabeçalho
        cab = widgets.Cabecalho(
            self, "Separar e Renomear",
            "Separa cada página em um comprovante e renomeia lendo o conteúdo.",
            trilha="Comprovantes  ›  Separar e Renomear")
        cab.pack(fill="x", padx=PADX, pady=(16, 12))
        # Ação única: o verde é o único botão do cabeçalho.
        self.btn = widgets.Botao(cab.acoes, "Separar e Renomear", papel="acao",
                                 command=self._executar)
        self.btn.pack(side="left")

        # ---- card: pastas de trabalho
        pastas = widgets.Cartao(self, "Pastas de trabalho", 1)
        pastas.pack(fill="x", padx=PADX, pady=(0, 12))
        ttk.Label(pastas, text="ENTRADA — PDFs ORIGINAIS", style="Rotulo.TLabel"
                  ).grid(row=0, column=0, sticky="w", pady=(0, 3))
        ttk.Entry(pastas, textvariable=self.ent
                  ).grid(row=1, column=0, sticky="we", padx=(0, 8), pady=(0, 12))
        widgets.Botao(pastas, "Selecionar…", papel="neutro",
                      command=lambda: self.ent.set(
                          (filedialog.askdirectory() or self.ent.get())
                          .replace("\\", "/"))
                      ).grid(row=1, column=1, sticky="w", pady=(0, 12))
        ttk.Label(pastas, text="SAÍDA — RENOMEADOS (SUGERIDA AUTOMATICAMENTE)",
                  style="Rotulo.TLabel").grid(row=2, column=0, sticky="w",
                                              pady=(0, 3))
        ttk.Entry(pastas, textvariable=self.sai
                  ).grid(row=3, column=0, sticky="we", padx=(0, 8))
        widgets.Botao(pastas, "Selecionar…", papel="neutro",
                      command=lambda: self.sai.set(
                          (filedialog.askdirectory() or self.sai.get())
                          .replace("\\", "/"))).grid(row=3, column=1, sticky="w")
        pastas.columnconfigure(0, weight=1)
        self.ent.trace_add("write", self._sugerir_saida)

        # ---- card: nome dos arquivos
        nome = widgets.Cartao(self, "Nome dos arquivos", 2)
        nome.pack(fill="x", padx=PADX, pady=(0, 12))
        ttk.Radiobutton(nome, text=f"Padrão:  {MODELO_PADRAO}",
                        variable=self.v_tipo_nome, value="padrao"
                        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(nome, text="Personalizado:",
                        variable=self.v_tipo_nome, value="custom"
                        ).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(nome, textvariable=self.v_modelo, width=48
                  ).grid(row=1, column=1, sticky="we", padx=(8, 0), pady=(6, 0))
        self.lbl_dica = ttk.Label(
            nome, style="Apoio.TLabel", justify="left", wraplength=760,
            text="Use VALOR, DESCRIÇÃO, DATA, PAGADOR e RECEBEDOR na ordem que "
                 "quiser (ex.: DATA - VALOR - RECEBEDOR). Inclua sempre o VALOR: "
                 "é ele que permite o casamento automático na hora de anexar.")
        self.lbl_dica.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 2))
        # O exemplo é monoespaçado de propósito: ele mostra um NOME DE ARQUIVO,
        # e é a mesma fonte em que o nome vai aparecer no registro abaixo.
        self.lbl_ex = ttk.Label(
            nome, style="Apoio.TLabel", font=widgets.FONTE_MONO,
            text="ex.:  70,00 - RPB 24 QD 26A LT 12 OC 5979 - 20-07.pdf")
        self.lbl_ex.grid(row=3, column=0, columnspan=2, sticky="w")
        nome.columnconfigure(1, weight=1)

        # ---- barra de execução, acima do registro
        acao = ttk.Frame(self, style="Fundo.TFrame")
        acao.pack(fill="x", padx=PADX, pady=(0, 10))
        self.barra_exec = widgets.BarraExecucao(acao)
        self.barra_exec.pack(fill="x")
        self.lbl_status = self.barra_exec.lbl
        self.barra = self.barra_exec.pb

        # ---- card: registro (cresce quando tem o que mostrar)
        self.reg = widgets.Cartao(self, "Registro", padding=(12, 10))
        self.reg.pack(fill="x", padx=PADX, pady=(0, 12))
        self.txt = tk.Text(self.reg, wrap="word", relief="flat",
                           borderwidth=0, highlightthickness=0)
        self.txt.pack(fill="both", expand=True)
        widgets.estilo_log(self.txt)
        self._mostrar_placeholder()
        widgets.registro_elastico(self.reg, self.txt)

    def aplicar_cores(self, escuro: bool):
        """Cor do registro. As legendas seguem o tema pelo estilo nomeado."""
        try:
            widgets.estilo_log(self.txt, escuro)
        except tk.TclError:
            pass

    def _mostrar_placeholder(self):
        """Estado inicial do Registro — evita a área vazia parecer 'quebrada'."""
        self.txt.delete("1.0", "end")
        self.txt.insert("end", "\n\n", "ph")
        self.txt.insert("end", "Os comprovantes renomeados aparecerão aqui.\n", "ph")
        self.txt.insert("end", "\nEscolha as pastas acima e clique em "
                               "“Separar e Renomear”.\n", "ph")
        self.txt.insert("end", "Comprovantes sem texto passam por OCR "
                               "automaticamente.\n", "ph")

    def _sugerir_saida(self, *_):
        if self.ent.get() and not self.sai.get():
            self.sai.set(str(Path(self.ent.get()) / "RENOMEADOS").replace("\\", "/"))

    def _log(self, m):
        self.fila.put(("log", m))

    def _drain(self):
        try:
            while True:
                kind, m = self.fila.get_nowait()
                if kind == "log":
                    self.txt.insert("end", m + "\n"); self.txt.see("end")
                    # A linha de fecho do lote é a que o Início mostra como
                    # "resultado". Guardada aqui porque o worker roda noutra
                    # thread, e quem escreve no `atividade.jsonl` é sempre a
                    # thread da interface.
                    if m.lstrip().startswith(("Concluído:", "⏹ Interrompido")):
                        self._resumo = " ".join(m.split())
                elif kind == "prog":
                    feitas, total = m
                    if total:            # dá para mostrar quanto falta
                        self.barra_exec.progresso(feitas, total)
                        self.lbl_status.config(text="Processando as páginas…")
                else:
                    self.barra_exec.terminou("Concluído.")
                    self.btn.config(state="normal")
                    widgets.registrar_atividade(
                        "sep", "Separar e Renomear", "ok",
                        str(self._resumo or "concluído")[:120])
        except queue.Empty:
            pass
        except Exception as e:                              # noqa: BLE001
            # A bomba de UI NUNCA pode morrer, e por isso o reagendamento está
            # no `finally`. Um `tk.TclError` aqui (mexer num widget recém
            # destruído, por exemplo) parava o ciclo para sempre: o registro
            # congelava, o botão nunca voltava e o OCR seguia rodando — sem
            # ninguém saber sequer se dava para fechar o app. É o modelo do
            # `_drain` do Anexar.
            #
            # O motivo vai para o próprio Registro, e não para o
            # `diagnostico.log`: esta aba não importa o `config` do Anexar, e
            # criar essa dependência só para registrar uma linha custaria mais
            # do que resolve. Só quando MUDA — repetido a cada 150 ms, ele
            # afogaria o que a pessoa precisa ler.
            motivo = repr(e)
            if motivo != self._erro_drain:
                self._erro_drain = motivo
                self.fila.put(("log", f"[!] falha ao atualizar a tela: {motivo}"))
        finally:
            self.after(150, self._drain)

    def _executar(self):
        if self._thread is not None and self._thread.is_alive():
            return                       # já está rodando: o clique não enfileira
        if not self.ent.get() or not Path(self.ent.get()).exists():
            messagebox.showerror("Erro", "Selecione a pasta de entrada."); return
        if not self.sai.get():
            self.sai.set(str(Path(self.ent.get()) / "RENOMEADOS").replace("\\", "/"))
        # TUDO que vem do formulário é lido AQUI, na thread da interface, e vai
        # por argumento. O `modelo` já era; as duas pastas eram lidas de dentro
        # da thread, e ler `StringVar` fora da thread da janela é falar com o
        # Tcl de outro lugar — trava ou erra sem hora marcada, que é a falha
        # que nunca aparece em teste.
        entrada = self.ent.get()
        saida = self.sai.get()
        modelo = None if self.v_tipo_nome.get() == "padrao" else self.v_modelo.get()
        self._parar.clear()
        self.btn.config(state="disabled")
        self._resumo = ""
        self.barra_exec.comecou("Processando…")
        self.barra.start(12)
        self._tarefa_atual = "Separar e Renomear"
        self.txt.delete("1.0", "end")

        def work():
            import time as _t
            inicio = _t.time()
            self._log(f"⏱ Início: {_t.strftime('%H:%M:%S')}")
            try:
                processar(entrada, saida, self._log, modelo,
                          progresso=lambda f, t: self.fila.put(("prog", (f, t))),
                          parar=self._parar.is_set)
            except Exception as ex:
                self._log("ERRO FATAL: " + str(ex))
            self._log(f"⏱ Fim: {_t.strftime('%H:%M:%S')} — tempo total: "
                      f"{_fmt_dur(_t.time() - inicio)}")
            self.fila.put(("fim", None))
        self._thread = threading.Thread(target=work, daemon=True,
                                        name="separar-renomear")
        self._thread.start()

    def ocupado(self) -> str | None:
        """O que esta aba está fazendo agora, ou None.

        A barra lateral pergunta isto no pulso dela para acender o ● na aba que
        trabalha. Aqui não há navegador — o trabalho é OCR e disco —, mas um
        arquivo de 107 páginas leva minutos, e sem responder nada a aba parecia
        parada. Mesma forma de `ExtratosSicoobFrame.ocupado`: uma frase ou
        None, nunca um booleano, porque o rodapé escreve a tarefa."""
        t = self._thread
        if t is not None and t.is_alive():
            return self._tarefa_atual or "Separar e Renomear"
        return None

    def fechar(self):
        """Pede parada e espera um pouco (chamar ao sair do app).

        Seguro de chamar SEMPRE, inclusive sem nada rodando.

        A thread continua `daemon=True` de propósito, e isso é uma ESCOLHA
        entre dois modos de falhar. Sem daemon, um OCR longo seguraria o
        processo depois de a janela sumir — exatamente o defeito que a aba
        Acessórias corrige logo ali. Com daemon e sem mais nada, o
        interpretador matava a thread no meio da 2ª passada, a que grava, e
        sobrava PDF pela metade na pasta de saída. A saída é a terceira: pedir
        parada (o `processar` conclui a página em curso — milissegundos) e
        esperar um pouco por ela. Passado o prazo, o daemon garante que o app
        fecha assim mesmo; o que se perde é trabalho ainda não gravado, e não
        um arquivo corrompido.

        Também não trocamos a thread por um `ThreadPoolExecutor`: aqui não há
        navegador nem sessão única a proteger (a regra "Playwright sync = uma
        única thread" não alcança esta aba), e as threads do executor NÃO são
        daemon — adotá-lo traria de volta o processo invisível que o daemon
        evita."""
        self._parar.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=5)


def main():
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)   # texto nítido em telas HiDPI
    except Exception:
        pass
    root = tk.Tk(); root.title("Separar e Renomear Comprovantes")
    try:
        root.state("zoomed")          # ocupa a tela inteira (Windows)
    except tk.TclError:
        root.geometry("900x620")
    try:
        import sv_ttk                 # tema moderno (visual Windows 11)
        sv_ttk.set_theme("light")
    except Exception:
        pass
    SepararFrame(root).pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        processar(sys.argv[1], sys.argv[2],
                  modelo=(sys.argv[3] if len(sys.argv) > 3 else None))
    else:
        main()
