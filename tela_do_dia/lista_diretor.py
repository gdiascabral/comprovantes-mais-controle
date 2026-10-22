"""Passo 7: a lista do diretor — só o que foi AGENDADO hoje, uma linha por
conta, nome curto definido uma vez (nuvem), ordinais marcados na hora com a
ordem de ontem como sugestão, texto pronto para o WhatsApp. ("Arrastar" é
↑/↓ na tela: Treeview não arrasta sem código de tela que não se testa.)
Módulo puro: sem tela, sem rede. Dinheiro em Decimal."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, replace
from decimal import Decimal

from .valores import brl

ZERO = Decimal("0.00")
NOME_MAXIMO = 60
_FIM = 10 ** 6


@dataclass
class LinhaDaLista:
    rotulo: str
    nome: str
    valor: Decimal
    ordinal: int | None = None
    sem_nome_curto: bool = False
    sugerido: bool = False          # nome = sugestão do app (não gravada)


def montar(agendados_hoje, rotulo_de, nomes) -> list[LinhaDaLista]:
    """Soma por rótulo de conta. Valor None ou <= 0 não vira linha.

    Conta sem nome curto gravado nasce com a SUGESTÃO (`sugerir_nomes`,
    `sugerido=True`): a lista copia direto, e o dono troca quando quiser.
    A sugestão nunca repete um nome curto gravado de outra conta."""
    soma: dict[str, Decimal] = {}
    for a in agendados_hoje:
        if a.valor is None or a.valor <= 0:
            continue
        r = rotulo_de(a.conta) or a.conta
        if not r:
            raise ValueError("Agendado sem conta nem rótulo: a lista não pode ter linha sem nome.")
        soma[r] = soma.get(r, ZERO) + a.valor
    nomes = nomes or {}
    sug = sugerir_nomes(list(soma), ocupados={v for v in nomes.values() if v})
    linhas = []
    for r, v in soma.items():
        gravado = nomes.get(r)
        nome = gravado or sug.get(r) or r
        linhas.append(LinhaDaLista(r, nome, v, None, sem_nome_curto=not gravado and not sug.get(r),
                                   sugerido=not gravado and bool(sug.get(r))))
    return linhas


# ------------------------------------------------------ nome curto sugerido
# Regra fixa (sem IA, sem rede): o mesmo rótulo dá sempre o mesmo nome.
_BANCOS = {"SICOOB": "Sicoob", "INTER": "Inter", "BRADESCO": "Bradesco",
           "CAIXA": "Caixa", "CEF": "Caixa", "ITAU": "Itaú", "SANTANDER": "Santander",
           "BB": "BB", "SICREDI": "Sicredi", "NUBANK": "Nubank", "C6": "C6"}
_JURIDICOS = {"LTDA", "LTDA.", "SPE", "S/A", "S.A.", "S.A", "SA", "ME", "EIRELI", "EPP"}
_ROMANOS = {"I", "II", "III", "IV", "V", "VI"}
_CURTOS = {"PARTICIPACOES": "Part.", "SUBCONTA": "Sub.", "ENGENHARIA": "Eng.",
           "INCORPORACOES": "Incorp.", "EMPREENDIMENTOS": "Empreend."}
_MINUSCULAS = {"DE", "DA", "DO", "DAS", "DOS", "E"}


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if not unicodedata.combining(c))


def _chave(nome: str) -> str:
    return " ".join(str(nome or "").split()).casefold()


def _numero_de_conta(tok: str) -> str:
    """'20001-1' / '20.003-3' / '1234567' → só os dígitos antes do DV; '' se não é."""
    t = tok.replace(".", "")
    corpo = t.split("-")[0] if t.count("-") == 1 else t
    dv = t.split("-")[1] if t.count("-") == 1 else ""
    if corpo.isdigit() and len(corpo) >= 4 and (dv == "" or (len(dv) == 1 and dv.isalnum())) \
            and (dv or len(corpo) >= 5):
        return corpo[:5] if len(corpo) > 5 else corpo
    return ""


def _palavra(tok: str) -> str:
    base = _sem_acento(tok).upper()
    if base in _CURTOS:
        return _CURTOS[base]
    if tok.endswith(".") or any(c.isdigit() for c in tok):
        return tok
    if base in _MINUSCULAS:
        return tok.lower()
    if len(tok) <= 3 and not any(c in "AEIOU" for c in base):
        return tok.upper()                   # sigla: QRS, TB, QD, LT
    return tok[:1].upper() + tok[1:].lower()


def _pecas(rotulo: str):
    """(nome sem banco nem número, banco curto, número da conta)."""
    banco = ""
    # Banco num trecho só dele, em qualquer lugar ("EMPRESA - SICOOB -
    # SUBCONTA 1234-5"): no meio, ficava no nome ("Empresa Sicoob Sub. …").
    trechos = [t.strip() for t in str(rotulo or "").split(" - ")]
    for i, trecho in enumerate(trechos):
        if _sem_acento(trecho).upper() in _BANCOS:
            banco = _BANCOS[_sem_acento(trechos.pop(i)).upper()]
            break
    toks = [t for t in " ".join(trechos).split() if t != "-"]
    toks = [t.strip("-") for t in toks if t.strip("-")]
    # Senão, o banco é a última palavra que não é número de conta.
    fim = next((i for i in range(len(toks) - 1, -1, -1) if not _numero_de_conta(toks[i])), None)
    if not banco and fim is not None and _sem_acento(toks[fim]).upper() in _BANCOS:
        banco = _BANCOS[_sem_acento(toks.pop(fim)).upper()]
    numero, saida, i = "", [], 0
    while i < len(toks):
        t = toks[i]
        cima = _sem_acento(t).upper()
        if cima == "SUBCONTA" and i + 1 < len(toks) and _numero_de_conta(toks[i + 1]):
            saida.append(f"Sub. {_numero_de_conta(toks[i + 1])}")
            i += 2
            continue
        if cima in _JURIDICOS:
            i += 1
            if cima == "SPE" and i < len(toks) and toks[i].upper() in _ROMANOS:
                i += 1
            continue
        n = _numero_de_conta(t)
        if n:
            numero = numero or n
            i += 1
            continue
        saida.append(_palavra(t))
        i += 1
    if saida and saida[0] in {w.lower() for w in _MINUSCULAS}:
        saida[0] = saida[0].capitalize()
    return " ".join(saida), banco, numero


def _tem_banco(texto: str, banco: str) -> bool:
    return banco.casefold() in [p.strip("-.").casefold() for p in texto.split()]


def _caber(nome: str) -> str:
    nome = " ".join(nome.split())
    return nome if len(nome) <= NOME_MAXIMO else nome[:NOME_MAXIMO].rstrip()


def sugerir_nomes(rotulos, ocupados=()) -> dict[str, str]:
    """Nome curto sugerido para cada rótulo, ÚNICOS entre si e diferentes dos
    `ocupados` (nomes curtos já gravados). Banco sai quando a lista inteira é
    do mesmo banco; senão fica curto no fim ("Obra Beta - Inter"). Empate
    desempata pelo número da conta (5 dígitos), depois pelo banco, depois por
    um contador — na ordem alfabética dos rótulos, então a ordem de chegada
    não muda o resultado."""
    unicos = sorted({str(r) for r in rotulos if r is not None})
    pecas = {r: _pecas(r) for r in unicos}
    bancos = {b for _n, b, _num in pecas.values()}
    tirar_banco = len(bancos) == 1
    usados = {_chave(o) for o in ocupados or () if o}
    candidatos = {}
    for r, (nome, banco, numero) in pecas.items():
        if nome:
            base = nome
        elif numero:
            # Só banco e número: "<Banco> <número curto>", nunca o banco duas
            # vezes ("SICOOB 40001-1 - Sicoob").
            base = f"{banco} {numero}" if banco else numero
        else:
            base = _caber(str(r).strip()) or "Conta"
        sufixo = bool(banco) and not _tem_banco(base, banco)
        com_banco = f"{base} - {banco}" if sufixo and not tirar_banco else base
        lista = [com_banco]
        if numero and numero not in base:
            lista.append(f"{com_banco.removesuffix(f' - {banco}')} {numero}"
                         + (f" - {banco}" if sufixo and not tirar_banco else ""))
        if sufixo and tirar_banco:
            lista.append(f"{lista[-1]} - {banco}")
        candidatos[r] = [_caber(c) for c in lista]
    contagem: dict[str, int] = {}
    for r in unicos:
        k = _chave(candidatos[r][0])
        contagem[k] = contagem.get(k, 0) + 1
    saida: dict[str, str] = {}
    # 1º os que não empatam com ninguém ficam com o nome base.
    for r in unicos:
        k = _chave(candidatos[r][0])
        if contagem[k] == 1 and k not in usados:
            saida[r] = candidatos[r][0]
            usados.add(k)
    for r in unicos:
        if r in saida:
            continue
        escolha = next((c for c in candidatos[r][1:] if _chave(c) not in usados), "")
        n = 2
        while not escolha:
            c = _caber(f"{candidatos[r][-1][:NOME_MAXIMO - 4]} {n}")
            escolha = c if _chave(c) not in usados else ""
            n += 1
        saida[r] = escolha
        usados.add(_chave(escolha))
    return saida


def sugerir_nome_curto(conta, todas) -> str:
    """O nome curto que o app sugere para `conta`, olhando a lista `todas`
    (para decidir o banco e desempatar)."""
    rotulos = list(todas or ())
    if conta not in rotulos:
        rotulos.append(conta)
    return sugerir_nomes(rotulos)[str(conta)]


def renumerar(linhas) -> list[LinhaDaLista]:
    """Lista nova: numerados primeiro, ordenados por (ordinal, posição) e
    renumerados de 1; depois os sem ordinal. Não altera os objetos recebidos."""
    linhas = list(linhas)
    com = sorted((p for p in enumerate(linhas) if p[1].ordinal is not None),
                 key=lambda p: (p[1].ordinal, p[0]))
    sem = [l for l in linhas if l.ordinal is None]
    return [replace(l, ordinal=n) for n, (_, l) in enumerate(com, 1)] + [replace(l) for l in sem]


def _ordinal_de_ontem(x):
    try:
        n = int(x.get("ordinal"))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def sugerir_ordem(linhas, anterior) -> list[LinhaDaLista]:
    pos: dict[str, tuple[int, int | None]] = {}
    for i, x in enumerate(anterior or ()):
        pos.setdefault(str(x.get("conta")), (i, _ordinal_de_ontem(x)))
    com = sorted((l for l in linhas if pos.get(l.rotulo, (0, None))[1]),
                 key=lambda l: (pos[l.rotulo][1], pos[l.rotulo][0]))
    ids = {id(l) for l in com}
    sem = sorted((l for l in linhas if id(l) not in ids),
                 key=lambda l: (pos.get(l.rotulo, (_FIM, None))[0], -l.valor, l.rotulo))
    return renumerar([replace(l, ordinal=n) for n, l in enumerate(com, 1)]
                     + [replace(l, ordinal=None) for l in sem])


def mover(linhas, i, delta) -> list[LinhaDaLista]:
    """Troca a linha i com a vizinha (nos limites não faz nada) e renumera
    os numerados pela posição na lista."""
    linhas, j = list(linhas), i + delta
    if 0 <= i < len(linhas) and 0 <= j < len(linhas):
        linhas[i], linhas[j] = linhas[j], linhas[i]
    com = [l for l in linhas if l.ordinal is not None]
    sem = [l for l in linhas if l.ordinal is None]
    return [replace(l, ordinal=n) for n, l in enumerate(com, 1)] + [replace(l) for l in sem]


def alternar_ordinal(linhas, i) -> list[LinhaDaLista]:
    """Liga/desliga o ordinal da linha i; quem ganha vai para o fim dos
    numerados (`_FIM` só ordena; o `renumerar` põe o número real)."""
    linhas = list(linhas)
    linhas[i] = replace(linhas[i], ordinal=None if linhas[i].ordinal is not None else _FIM)
    return renumerar(linhas)


def texto_whatsapp(linhas) -> str:
    com = [l for l in linhas if l.ordinal]
    sem = [l for l in linhas if not l.ordinal]
    saida = [f"{l.ordinal}º {l.nome} — {brl(l.valor)}" for l in com]
    if com and sem:
        saida.append("Demais:")
    saida += [f"{l.nome} — {brl(l.valor)}" for l in sem]
    return "\n".join(saida)


def para_nuvem(linhas) -> list[dict]:
    return [{"conta": l.rotulo, "ordinal": l.ordinal} for l in linhas]


def validar_nome_curto(nome: str) -> str:
    n = (nome or "").strip()
    if not 1 <= len(n) <= NOME_MAXIMO or "\n" in n:
        return f"O nome curto tem de ter de 1 a {NOME_MAXIMO} caracteres, numa linha."
    return ""
