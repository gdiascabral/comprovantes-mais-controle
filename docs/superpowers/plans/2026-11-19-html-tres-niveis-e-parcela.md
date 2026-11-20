# HTML dos pagamentos em três níveis e parcela — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** cada linha dos dois HTML dos pagamentos (PJ e PF) mostra se pode pagar, se o app não leu algo ou se algo pede atenção, com o motivo, a lista do que foi conferido e, em título parcelado, "Parcela k de N" com a observação.

**Architecture:** dois módulos puros novos em `pagamentos_dia/` — `nivel.py` (classifica a linha a partir do que `montar_registros` já decidiu) e `parcelas.py` (diz qual parcela do título a linha paga). A `leitura_do_dia` passa a ler o título dos lançamentos parcelados e o `confirmacao.remontar` anota a parcela. Os dois HTML só mostram; o bloqueio do Copiar não muda.

**Tech Stack:** Python 3.11 (o do exe), pytest, HTML e JavaScript sem biblioteca dentro de `pagamentos_dia/modelos_html.py`.

**Spec:** `docs/superpowers/specs/2026-11-19-html-tres-niveis-parcela-e-letra-de-mao-design.md` (partes 1 e 2; a parte 3, leitura por IA, tem plano próprio depois da medição).

## Global Constraints

- Alvo Python 3.11: rodar `vermin --target=3.11 --violations` sobre os arquivos mudados.
- Nenhuma dependência nova; nenhum import novo de submódulo da biblioteca padrão.
- `pagamentos_dia/*.py` já entra no `codigo.zip`: arquivo novo nessa pasta não mexe no `build.yml` nem no `motor_minimo.txt`.
- Repositório público: nenhum nome real de fornecedor ou pessoa, CPF, CNPJ, e-mail real ou número de conta em código, teste ou comentário.
- Dinheiro em `Decimal` para comparar; o float do registro só vira `Decimal` por `Decimal(str(x))`.
- O bloqueio do Copiar (`html_pagamentos._motivo_do_bloqueio`, `html_pf.bloqueio_duro`) não muda.
- Planilha, remessa CNAB e a tela do app não mudam; o `status` continua no registro e na tela.
- Só leitura no ERP, sempre pelo Chrome do app (porteiro); nunca login HTTP por fora.
- Testes só puros (sem `raiz`/tkinter); rodar com `PYTHONPATH=.` a partir da raiz do worktree.
- Commits em português, sem acento, terminando com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Decisões do dono que este plano usa

A especificação foi aprovada em 19/11/2026 com as recomendações. Duas valem para estas partes e ficam em constantes de `nivel.py`, uma linha para trocar:

- `REEMBOLSO_DE_SOCIO_PODE_PAGAR = True` (decisão 1: "APTO* (reembolso)" fica em "Pode pagar").
- `OBS_DE_PARCELA_UNICA_LEVA_A_OLHE = False` (decisão 6: observação em parcela única só aparece).

## Review Focus

1. **Situação nova que alguém criar depois** (um `ATENÇÃO — …` que este plano não conhece): tem de cair em "Olhe", nunca em "Pode pagar". Teste na Tarefa 3.
2. **Linha sem conferência nenhuma** (linha à mão, sem anexo liberado, conferência vazia): "Não li", nunca "Pode pagar". Teste na Tarefa 3.
3. **Lançamento dividido em N boletos (`parte`) não é parcela**: "1/2" de `boletos_somados` não pode virar "Parcela 1 de 2". Teste na Tarefa 4.
4. **Título parcelado cuja leitura falhou**: "parcelado em N — número da parcela não lido" e "Não li". Teste nas Tarefas 3 e 4.
5. **Mesma linha digitável em dois lançamentos** (o aviso que o HTML acrescenta depois): a linha que estava "Pode pagar" desce para "Olhe". Teste na Tarefa 5.

---

### Tarefa 1: Provar ao vivo como o ERP devolve as parcelas

Não escreve código do app. Decide os nomes de campo da Tarefa 4.

**Files:**
- Usa: `C:/AUTOMAÇÕES MAIS CONTROLE/conferencia-pagamentos/2026-11-19-recibos-a-mao/sonda_parcela.py` (já escrito; só GET, imprime nomes de campo e posições, nada de nome, documento ou conta).

- [ ] **Step 1: Confirmar que o Chrome do app responde.** Em 19/11/2026 a primeira tentativa falhou: três abas do Mais Controle abertas pelo dono não respondiam. Pedir ao dono para fechar as abas dele que não usa, ou rodar quando ele disser que o Chrome está livre. Não fechar aba nenhuma por conta própria.

- [ ] **Step 2: Rodar a sonda**

Run: `cd "C:/AUTOMAÇÕES MAIS CONTROLE/conferencia-pagamentos/2026-11-19-recibos-a-mao" && python sonda_parcela.py`
Expected: para três títulos parcelados, a lista de campos do título, `installments: N` com N igual ao `numberOfFinancingInstallments` da lista, os campos de uma parcela e, para cada parcela, `id_e_o_da_linha=True` em exatamente uma.

- [ ] **Step 3: Anotar no topo de `pagamentos_dia/parcelas.py` (Tarefa 4) o que foi medido**

Três perguntas, cada uma com a resposta da sonda:
1. O `id` de `installments[k]` é o mesmo `id` do lançamento da lista? (Se não for, achar na saída da sonda o campo que é, e usar no lugar de `"id"` em `posicao`.)
2. Há campo de ordem (`installmentOrder`, `order`, `number`)? Qual? Ele vai primeiro em `CAMPOS_DE_ORDEM`.
3. Sem campo de ordem, a data (`plannedDate` ou `dueDate`) ordena as parcelas?

Se a resposta 1 for "não há como ligar a parcela à linha", PARAR e levar ao dono: a parte 2 sai só com "parcelado em N", sem o número.

### Tarefa 2: Descobrir por que o valor fica sem conferir nos Pix

Diagnóstico fora do app; o resultado vai para o dono e pode virar uma tarefa nova antes da IA. Não muda código do app.

**Files:**
- Create: `C:/AUTOMAÇÕES MAIS CONTROLE/conferencia-pagamentos/2026-11-19-recibos-a-mao/valor_sem_conferir.py`

- [ ] **Step 1: Escrever o diagnóstico**

```python
# -*- coding: utf-8 -*-
"""Por que o valor fica "?" nas linhas de Pix: amostra das conferências já
salvas (lista.json + anexos.json + textos.json de cada pasta). Só lê disco."""
import collections
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = Path(r"C:\AUTOMAÇÕES MAIS CONTROLE\conferencia-pagamentos")
causas, exemplos = collections.Counter(), collections.defaultdict(list)


def carregar(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


for pasta in sorted(RAIZ.glob("2026-1*")):
    lista, anexos, textos = (carregar(pasta / n) for n in ("lista.json", "anexos.json", "textos.json"))
    if not isinstance(lista, list) or not isinstance(anexos, dict) or not isinstance(textos, dict):
        continue
    for item in lista:
        if item.get("paid") or "pix" not in str(item.get("tradePayablePaymentMethod") or "").lower():
            continue
        valor = item.get("remainingValue") or 0
        if not valor:
            continue
        arqs = anexos.get(str(item.get("tradePayableId"))) or []
        if not arqs:
            causas["sem anexo"] += 1
            continue
        txts = [textos.get(a.get("downloadUrl") or "", "") for a in arqs]
        alvo = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        if not any(t.strip() for t in txts):
            imagem = any((a.get("extension") or "").lower() in (".jpg", ".jpeg", ".png") for a in arqs)
            causas["anexo só imagem" if imagem else "PDF sem texto"] += 1
        elif any(alvo in t for t in txts):
            causas["valor está no texto (a régua não achou)"] += 1
            exemplos["valor está no texto (a régua não achou)"].append(pasta.name)
        elif any(re.search(r"\d{1,3}(?:\.\d{3})*,\d{2}", t) for t in txts):
            causas["texto tem valores, nenhum igual ao do lançamento"] += 1
        else:
            causas["texto sem valor em dinheiro"] += 1
total = sum(causas.values())
print(f"{total} linhas de Pix a pagar nas conferências salvas")
for k, v in causas.most_common():
    print(f"  {v:5d}  {100 * v / max(total, 1):4.0f}%  {k}")
print("pastas com 'a régua não achou':", sorted(set(exemplos["valor está no texto (a régua não achou)"]))[:10])
```

- [ ] **Step 2: Rodar**

Run: `cd "C:/AUTOMAÇÕES MAIS CONTROLE/conferencia-pagamentos/2026-11-19-recibos-a-mao" && python valor_sem_conferir.py`
Expected: uma tabela de causas que soma o total. A linha "valor está no texto (a régua não achou)" é a que pode ser consertada sem IA.

- [ ] **Step 3: Levar ao dono.** Se "a régua não achou" passar de 10% das linhas, abrir uma tarefa nova (fora deste plano) para estudar `relatorio._valor_nos_textos` com essas pastas, ANTES do plano da IA. Registrar o resultado no cofre (nota `Pagamentos do Dia e HTML de pagamentos`).

### Tarefa 3: `nivel.py` — o nível de cada linha

**Files:**
- Create: `pagamentos_dia/nivel.py`
- Test: `tests/test_nivel_da_linha.py`

**Interfaces:**
- Produces:
  - `PODE_PAGAR`, `OLHE`, `NAO_LI` (str) e `ROTULO: dict[str, str]`
  - `BATE`, `DIVERGE`, `NAO_CONFERIDO` (str)
  - `class Nivel(nome: str, motivos: list[str], conferido: list[tuple[str, str]])`
  - `conferido(r: dict) -> dict[str, str]` (chaves sempre presentes: `"valor"`, `"quem recebe"`; opcionais: `"ordem de compra"`, `"nota"`, `"endereço"`)
  - `nivel_da_linha(r: dict, *, bloqueio: str = "", vencido: bool = False) -> Nivel`
  - `para_o_html(n: Nivel, r: dict) -> dict` com `nivel`, `nivel_rotulo`, `motivos`, `conferido`, `parcela`, `obs_parcela`
  - `rebaixar_no_html(e: dict, motivo: str) -> None`

- [ ] **Step 1: Escrever os testes**

```python
"""O nível de cada linha do HTML (spec de 19/11/2026). Registros fictícios."""
from pagamentos_dia import nivel

# Linha digitável fictícia com DV fechando e R$ 1.150,00 embutido: a mesma
# que tests/test_html_pagamentos.py e tests/test_confirmacao.py já usam.
from pagamentos_dia import ocr_boleto

LINHA_VALIDA = "34191.57007 00024.924375 24177.010006 9 15340000115000"


def _r(**k):
    base = {"tipo": "Pix", "dados": "fulano@exemplo.com", "valor": 100.0,
            "status": "APTO", "conferencia": "valor ✓ · fornecedor ✓", "id": "1"}
    base.update(k)
    return base


def test_valor_e_quem_recebe_conferidos_pode_pagar():
    n = nivel.nivel_da_linha(_r())
    assert n.nome == nivel.PODE_PAGAR and n.motivos == []


def test_valor_nao_conferido_e_nao_li():
    n = nivel.nivel_da_linha(_r(conferencia="valor ? · fornecedor ✓"))
    assert n.nome == nivel.NAO_LI
    assert "valor não conferido em documento nenhum" in n.motivos


def test_anexo_sem_texto_e_nao_li():
    n = nivel.nivel_da_linha(_r(conferencia="valor/fornecedor ? (anexo sem texto)"))
    assert n.nome == nivel.NAO_LI


def test_conferencia_vazia_nunca_pode_pagar():
    for conf in ("", "(não cruzado)", None, []):
        assert nivel.nivel_da_linha(_r(conferencia=conf)).nome == nivel.NAO_LI


def test_situacao_que_ninguem_conhece_cai_em_olhe():
    n = nivel.nivel_da_linha(_r(status="ATENÇÃO — situação inventada amanhã"))
    assert n.nome == nivel.OLHE and "situação inventada amanhã" in n.motivos


def test_nao_li_ganha_de_olhe():
    n = nivel.nivel_da_linha(_r(status="ATENÇÃO — anexo não lido", conferencia="valor ?"))
    assert n.nome == nivel.NAO_LI


def test_status_que_e_nao_li():
    for st in ("ATENÇÃO — anexo não lido", "ATENÇÃO — sem dados de pgto",
               "ATENÇÃO — QR Code sem valor"):
        assert nivel.nivel_da_linha(_r(status=st)).nome == nivel.NAO_LI


def test_divergencia_e_olhe_e_diz_o_que_diverge():
    n = nivel.nivel_da_linha(_r(status="ATENÇÃO — boleto de outra empresa",
                                conferencia="valor ✓ · BENEFICIÁRIO DIVERGE: boleto x × cadastro y"))
    assert n.nome == nivel.OLHE and "quem recebe diverge" in n.motivos
    assert dict(n.conferido)["quem recebe"] == nivel.DIVERGE


def test_bloqueio_e_vencido_levam_a_olhe():
    assert nivel.nivel_da_linha(_r(), bloqueio="já pago — não pagar de novo").nome == nivel.OLHE
    assert nivel.nivel_da_linha(_r(), vencido=True).nome == nivel.OLHE


def test_ja_pago_liberado_e_a_mao_sao_olhe():
    for st in ("JÁ PAGO em 10/11/2026", "LIBERADO — sem anexo", "À MÃO — motivo"):
        assert nivel.nivel_da_linha(_r(status=st)).nome == nivel.OLHE


def test_reembolso_de_socio_pode_pagar_pela_decisao_1():
    n = nivel.nivel_da_linha(_r(status="APTO* (reembolso)", conferencia="valor ✓"))
    assert nivel.REEMBOLSO_DE_SOCIO_PODE_PAGAR is True
    assert n.nome == nivel.PODE_PAGAR


def test_boleto_prova_o_valor_pelo_codigo_de_barras():
    linha = LINHA_VALIDA
    assert ocr_boleto.codigo_de_barras(linha), "a linha fictícia tem de fechar o DV"
    valor = float(ocr_boleto.valor_embutido(linha))           # 1150.0
    n = nivel.nivel_da_linha(_r(tipo="Boleto", dados=linha, valor=valor,
                                conferencia="fornecedor ✓"))
    assert dict(n.conferido)["valor"] == nivel.BATE and n.nome == nivel.PODE_PAGAR


def test_boleto_de_outro_valor_nao_prova():
    n = nivel.nivel_da_linha(_r(tipo="Boleto", dados=LINHA_VALIDA, valor=1.0,
                                conferencia="fornecedor ✓"))
    assert dict(n.conferido)["valor"] == nivel.NAO_CONFERIDO


def test_qr_pix_com_valor_embutido_prova_o_valor():
    copia = "00020126330014br.gov.bcb.pix0111000000000005204000053039865406100.005802BR5913FULANO DE TAL6008GOIANIA62070503***6304ABCD"
    n = nivel.nivel_da_linha(_r(dados=copia, valor=100.0, conferencia="fornecedor ✓"))
    assert dict(n.conferido)["valor"] == nivel.BATE


def test_endereco_nota_e_oc_aparecem_mas_nao_derrubam():
    n = nivel.nivel_da_linha(_r(conferencia="OC 5678 ✓ · NF ? (sem chave no anexo) · valor ✓ · fornecedor ✓ · endereço ?"))
    c = dict(n.conferido)
    assert c["ordem de compra"] == nivel.BATE and c["nota"] == nivel.NAO_CONFERIDO
    assert c["endereço"] == nivel.NAO_CONFERIDO and n.nome == nivel.PODE_PAGAR


def test_lote_diferente_e_olhe():
    n = nivel.nivel_da_linha(_r(conferencia="valor ✓ · fornecedor ✓ · endereço ⚠ LOTE DIFERENTE (QD 1 LT 9)"))
    assert n.nome == nivel.OLHE and "endereço diverge" in n.motivos


def test_parcela_sem_numero_e_nao_li():
    n = nivel.nivel_da_linha(_r(parcela={"numero": None, "total": 10}))
    assert n.nome == nivel.NAO_LI
    assert "parcelado em 10 — número da parcela não lido" in n.motivos


def test_parcela_com_observacao_e_olhe_e_unica_nao():
    assert nivel.nivel_da_linha(_r(parcela={"numero": 3, "total": 10},
                                   obs_parcela="pagar depois da medição")).nome == nivel.OLHE
    assert nivel.nivel_da_linha(_r(obs_parcela="qualquer coisa")).nome == nivel.PODE_PAGAR


def test_para_o_html_e_rebaixar():
    r = _r(parcela={"numero": 3, "total": 10})
    e = nivel.para_o_html(nivel.nivel_da_linha(r), r)
    assert e["nivel"] == nivel.PODE_PAGAR and e["nivel_rotulo"] == "PODE PAGAR"
    assert e["parcela"] == "3 de 10" and ["valor", nivel.BATE] in e["conferido"]
    nivel.rebaixar_no_html(e, "mesma linha digitável em 2 lançamentos")
    assert e["nivel"] == nivel.OLHE and e["motivos"][-1].startswith("mesma linha")
    e2 = nivel.para_o_html(nivel.nivel_da_linha(_r(conferencia="valor ?")), _r())
    nivel.rebaixar_no_html(e2, "x")
    assert e2["nivel"] == nivel.NAO_LI          # rebaixar nunca sobe "Não li"
```

A linha fictícia e o copia-e-cola dos testes foram conferidos ao escrever o plano (19/11/2026): `codigo_de_barras(LINHA_VALIDA)` devolve 44 dígitos e `valor_embutido` devolve 1150.00; o copia-e-cola tem o campo 54 = 100.00.

- [ ] **Step 2: Rodar e ver falhar**

Run: `PYTHONPATH=. python -m pytest tests/test_nivel_da_linha.py -q -p no:cacheprovider`
Expected: FAIL com `ModuleNotFoundError: No module named 'pagamentos_dia.nivel'`

- [ ] **Step 3: Escrever `pagamentos_dia/nivel.py`**

```python
# -*- coding: utf-8 -*-
"""O nível de cada linha do HTML dos pagamentos (spec de 19/11/2026).

"Pode pagar", "Olhe" ou "Não li", com os motivos e a lista do que foi
conferido. Só CLASSIFICA o que `relatorio.montar_registros` já decidiu
(`status`, `conferencia`) e o que a leitura acrescentou (`parcela`,
`obs_parcela`); não confere nada de novo e não libera nem trava o Copiar.

Os essenciais são dois, valor e quem recebe (medido em 3.946 linhas de
set–nov/2026: exigir "nenhum ?" deixaria 4 em 5 linhas fora do verde).
Endereço, nota e ordem de compra aparecem, mas não derrubam o nível.
Peça de conferência que este módulo não reconhece é ignorada: os
essenciais nascem "não conferido", então o desconhecido nunca vira verde.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from . import ocr_boleto

PODE_PAGAR, OLHE, NAO_LI = "PODE_PAGAR", "OLHE", "NAO_LI"
ROTULO = {PODE_PAGAR: "PODE PAGAR", OLHE: "OLHE", NAO_LI: "NÃO LI"}
BATE, DIVERGE, NAO_CONFERIDO = "bate", "diverge", "nao"

#: Decisão 1 da spec: reembolso de sócio do cadastro fica em "Pode pagar".
REEMBOLSO_DE_SOCIO_PODE_PAGAR = True
#: Decisão 6 da spec: observação em título de parcela única só aparece.
OBS_DE_PARCELA_UNICA_LEVA_A_OLHE = False

_STATUS_NAO_LI = ("anexo não lido", "sem dados de pgto", "QR Code sem valor")
_PREFIXO = re.compile(r"^ATENÇÃO\s+—\s+")
_CENTAVO = Decimal("0.01")


@dataclass
class Nivel:
    nome: str
    motivos: list = field(default_factory=list)
    conferido: list = field(default_factory=list)        # [(item, estado)]


def _pecas(conferencia) -> list[str]:
    if isinstance(conferencia, (list, tuple)):
        conferencia = " · ".join(str(x) for x in conferencia)
    return [p.strip() for p in str(conferencia or "").split(" · ") if p.strip()]


def _marcar(estado: dict, chave: str, novo: str) -> None:
    """Diverge fica; bate só ocupa o lugar de "não conferido"."""
    atual = estado.get(chave)
    if atual == DIVERGE:
        return
    if novo == DIVERGE or atual in (None, NAO_CONFERIDO):
        estado[chave] = novo


def _dinheiro(valor) -> Decimal | None:
    try:
        return Decimal(str(valor)).quantize(_CENTAVO)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _valor_do_pix(copia: str) -> Decimal | None:
    """O campo 54 (valor) do copia-e-cola, ou None. Só o nível de cima do TLV."""
    i, s = 0, str(copia or "")
    while i + 4 <= len(s):
        tag, tam = s[i:i + 2], s[i + 2:i + 4]
        if not tam.isdigit():
            return None
        valor = s[i + 4:i + 4 + int(tam)]
        if tag == "54":
            return _dinheiro(valor)
        i += 4 + int(tam)
    return None


def _valor_pelo_codigo(r: dict) -> bool:
    """O código conferido prova o valor: linha digitável com DV fechando e o
    valor embutido igual ao da linha; ou Pix copia-e-cola com o campo 54."""
    tipo, dados, valor = str(r.get("tipo") or ""), str(r.get("dados") or ""), _dinheiro(r.get("valor"))
    if valor is None or not dados:
        return False
    if tipo.upper().startswith("BOLETO"):
        embutido = ocr_boleto.valor_embutido(dados) if ocr_boleto.codigo_de_barras(dados) else None
        return embutido is not None and embutido.quantize(_CENTAVO) == valor
    if dados.startswith("000201"):
        return _valor_do_pix(dados) == valor
    return False


def conferido(r: dict) -> dict:
    estado = {"valor": NAO_CONFERIDO, "quem recebe": NAO_CONFERIDO}
    for p in _pecas(r.get("conferencia")):
        if p.startswith("valor ✓"):
            _marcar(estado, "valor", BATE)
        elif p.startswith("VALOR DIVERGE"):
            _marcar(estado, "valor", DIVERGE)
        if p.startswith(("fornecedor ✓", "beneficiário ✓", "CNPJ ✓")) or re.match(r"UC \S+ ✓", p):
            _marcar(estado, "quem recebe", BATE)
        elif p.startswith(("BENEFICIÁRIO DIVERGE", "CNPJ DIVERGE", "UC DIVERGE")):
            _marcar(estado, "quem recebe", DIVERGE)
        if re.match(r"OC \S+ ✓", p):
            _marcar(estado, "ordem de compra", BATE)
        elif p.startswith("OC DIVERGE"):
            _marcar(estado, "ordem de compra", DIVERGE)
        if re.match(r"NF \S+ ✓", p):
            _marcar(estado, "nota", BATE)
        elif p.startswith("NF DIVERGE"):
            _marcar(estado, "nota", DIVERGE)
        elif p.startswith("NF ?"):
            _marcar(estado, "nota", NAO_CONFERIDO)
        if "LOTE DIFERENTE" in p:
            _marcar(estado, "endereço", DIVERGE)
        elif p.startswith("endereço ✓"):
            _marcar(estado, "endereço", BATE)
        elif p.startswith("endereço ?"):
            _marcar(estado, "endereço", NAO_CONFERIDO)
    if _valor_pelo_codigo(r):
        _marcar(estado, "valor", BATE)
    if REEMBOLSO_DE_SOCIO_PODE_PAGAR and str(r.get("status") or "").startswith("APTO* (reembolso)"):
        # A chave é a do cadastro de sócios, com o CPF fechando o DV
        # (`reembolso.socio_do_documento`): quem recebe está provado.
        _marcar(estado, "quem recebe", BATE)
    return estado


def _sem_prefixo(status: str) -> str:
    return _PREFIXO.sub("", status).strip()


def nivel_da_linha(r: dict, *, bloqueio: str = "", vencido: bool = False) -> Nivel:
    status = str(r.get("status") or "")
    estado = conferido(r)
    nao_li, olhe = [], []
    if any(x in status for x in _STATUS_NAO_LI):
        nao_li.append(_sem_prefixo(status))
    parcela = r.get("parcela") or {}
    total = int(parcela.get("total") or 0)
    if total > 1 and not parcela.get("numero"):
        nao_li.append(f"parcelado em {total} — número da parcela não lido")
    if estado["valor"] == NAO_CONFERIDO:
        nao_li.append("valor não conferido em documento nenhum")
    if estado["quem recebe"] == NAO_CONFERIDO:
        nao_li.append("quem recebe não conferido")
    if not status.startswith("APTO"):
        olhe.append(_sem_prefixo(status) or "sem situação")
    elif status.startswith("APTO* (reembolso)") and not REEMBOLSO_DE_SOCIO_PODE_PAGAR:
        olhe.append("reembolso de sócio")
    if bloqueio:
        olhe.append(bloqueio)
    if vencido:
        olhe.append("vencido — confira se já não foi pago")
    for item, e in estado.items():
        if e == DIVERGE:
            olhe.append(f"{item} diverge")
    if r.get("obs_parcela") and (total > 1 or OBS_DE_PARCELA_UNICA_LEVA_A_OLHE):
        olhe.append("a parcela tem observação: leia antes de pagar")
    nome = NAO_LI if nao_li else OLHE if olhe else PODE_PAGAR
    return Nivel(nome, list(dict.fromkeys(nao_li + olhe)), list(estado.items()))


def para_o_html(n: Nivel, r: dict) -> dict:
    parcela = r.get("parcela") or {}
    total = int(parcela.get("total") or 0)
    return {"nivel": n.nome, "nivel_rotulo": ROTULO[n.nome], "motivos": list(n.motivos),
            "conferido": [[item, estado] for item, estado in n.conferido],
            "parcela": (f"{parcela.get('numero') or '?'} de {total}" if total > 1 else ""),
            "obs_parcela": str(r.get("obs_parcela") or "")}


def rebaixar_no_html(e: dict, motivo: str) -> None:
    """Aviso que o HTML acrescenta depois (mesma cobrança em dois lançamentos):
    "Pode pagar" desce para "Olhe"; "Não li" continua "Não li"."""
    if e.get("nivel") == PODE_PAGAR:
        e["nivel"], e["nivel_rotulo"] = OLHE, ROTULO[OLHE]
    e.setdefault("motivos", []).append(motivo)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `PYTHONPATH=. python -m pytest tests/test_nivel_da_linha.py -q -p no:cacheprovider`
Expected: 19 PASS (conferido ao escrever o plano, com este código e estes testes).

- [ ] **Step 5: Medir contra os HTML já gerados**

Run (fora do repositório, só lê disco):

```bash
cd "C:/AUTOMAÇÕES MAIS CONTROLE/_worktrees/app-html-claro" && PYTHONPATH=. python - <<'EOF'
import collections, json, re
from pathlib import Path
from pagamentos_dia import nivel
P = Path(r"C:\AUTOMAÇÕES MAIS CONTROLE\_app\Pagamentos do dia")
c = collections.Counter()
for h in P.glob("pagamentos_20*.html"):
    m = re.search(r"const DATA\s*=\s*(\{.*?\});\s*\n", h.read_text(encoding="utf-8", errors="replace"), re.S)
    if not m:
        continue
    for conta in json.loads(m.group(1)).get("contas") or []:
        for e in conta.get("entries") or []:
            r = {"tipo": e.get("tipo"), "dados": e.get("dados_limpo"), "valor": e.get("valor_raw") or 0,
                 "status": e.get("status"), "conferencia": e.get("conferencia")}
            c[nivel.nivel_da_linha(r, bloqueio=e.get("bloqueio") or "", vencido=bool(e.get("vencido"))).nome] += 1
t = sum(c.values()); print({k: f"{v} ({100*v//t}%)" for k, v in c.items()})
EOF
```

Expected (medido com este código ao escrever o plano, 19/11/2026, 3.946 linhas): `PODE_PAGAR` 1.988 (50%), `NAO_LI` 1.842 (46%), `OLHE` 116 (2%). "Olhe" fica pequeno porque "Não li" ganha quando os dois valem; os motivos de "Olhe" continuam na lista da linha. Primeiro motivo mais comum: "valor não conferido em documento nenhum" (1.545). Se "Pode pagar" ficar abaixo de 35% numa rodada nova, PARAR e levar ao dono antes da Tarefa 5.

- [ ] **Step 6: Commit**

```bash
git add pagamentos_dia/nivel.py tests/test_nivel_da_linha.py
git commit -m "HTML: nivel de cada linha (pode pagar, olhe, nao li)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Tarefa 4: `parcelas.py` e a leitura das parcelas

Depende da Tarefa 1 (nomes de campo).

**Files:**
- Create: `pagamentos_dia/parcelas.py`
- Modify: `pagamentos_dia/confirmacao.py` (classe `Entradas`, função `remontar`)
- Modify: `pagamentos_dia/leitura_do_dia.py` (`ler_pagamentos`, logo depois de `entradas.titulos_erp = ler_titulos_no_erp(...)`)
- Test: `tests/test_parcelas.py`
- Modify: `tests/test_leitura_so_o_que_entra.py` (lista de etapas do cronômetro)

**Interfaces:**
- Consumes: `leitura_do_dia.ler_titulos_no_erp(api, tpids, log, cancelar) -> dict`, `relatorio.comentario_do(overview) -> str`
- Produces:
  - `parcelas.CAMPOS_DE_ORDEM: tuple[str, ...]`
  - `parcelas.total_do_item(item: dict) -> int`
  - `parcelas.titulos_parcelados(itens) -> list[str]`
  - `parcelas.posicao(titulo: dict | None, id_parcela) -> int | None`
  - `parcelas.anotar(resultado, selecionados, parcelas_erp: dict, overviews: dict) -> Resultado` (põe `registro["parcela"] = {"numero": int | None, "total": int}` só quando total > 1, e `registro["obs_parcela"]` quando o detalhe tem comentário)
  - `Entradas.parcelas_erp: dict | None = None` (None = não anota; só a `leitura_do_dia` preenche)

- [ ] **Step 1: Escrever os testes**

```python
"""Qual parcela do título a linha paga (spec de 19/11/2026, parte 2).
Títulos fictícios no formato medido na Tarefa 1 do plano."""
from pagamentos_dia import parcelas
from pagamentos_dia.relatorio import Resultado


def _titulo(*ids, campo="installmentOrder"):
    return {"installments": [{"id": i, campo: k, "plannedDate": f"2026-{k:02d}-10"}
                             for k, i in enumerate(ids, 1)]}


def test_posicao_pela_ordem_do_erp():
    assert parcelas.posicao(_titulo("a", "b", "c"), "b") == 2


def test_posicao_pela_data_quando_nao_ha_campo_de_ordem():
    t = {"installments": [{"id": "x", "plannedDate": "2026-03-10"},
                          {"id": "y", "plannedDate": "2026-01-10"}]}
    assert parcelas.posicao(t, "x") == 2 and parcelas.posicao(t, "y") == 1


def test_parcela_fora_do_titulo_ou_titulo_vazio_e_none():
    assert parcelas.posicao(_titulo("a"), "z") is None
    assert parcelas.posicao(None, "a") is None and parcelas.posicao({}, "a") is None


def test_titulos_parcelados_so_os_de_mais_de_uma():
    itens = [{"tradePayableId": "T1", "numberOfFinancingInstallments": 1},
             {"tradePayableId": "T2", "numberOfFinancingInstallments": 10},
             {"tradePayableId": "T3", "numberOfFinancingInstallments": "lixo"},
             {"tradePayableId": "T2", "numberOfFinancingInstallments": 10}]
    assert parcelas.titulos_parcelados(itens) == ["T2"]


def _res(*regs):
    return Resultado({"CONTA EXEMPLO": list(regs)}, [])


def test_anotar_parcela_e_observacao():
    sel = [{"id": "b", "tradePayableId": "T2", "numberOfFinancingInstallments": 3}]
    r = {"id": "b"}
    parcelas.anotar(_res(r), sel, {"T2": _titulo("a", "b", "c")},
                    {"b": {"comment": "pagar depois da medição"}})
    assert r["parcela"] == {"numero": 2, "total": 3}
    assert r["obs_parcela"] == "pagar depois da medição"


def test_titulo_que_nao_leu_fica_sem_numero():
    sel = [{"id": "b", "tradePayableId": "T2", "numberOfFinancingInstallments": 3}]
    r = {"id": "b"}
    parcelas.anotar(_res(r), sel, {}, {})
    assert r["parcela"] == {"numero": None, "total": 3}


def test_parcela_unica_nao_ganha_parcela_mas_ganha_observacao():
    sel = [{"id": "u", "tradePayableId": "T1", "numberOfFinancingInstallments": 1}]
    r = {"id": "u"}
    parcelas.anotar(_res(r), sel, {}, {"u": {"comment": "nota da parcela"}})
    assert "parcela" not in r and r["obs_parcela"] == "nota da parcela"


def test_lancamento_dividido_em_boletos_nao_e_parcela():
    # boletos_somados: duas linhas do MESMO id, com "parte" 1/2 e 2/2,
    # num título de UMA parcela. Nenhuma das duas vira "Parcela k de N".
    sel = [{"id": "d", "tradePayableId": "T9", "numberOfFinancingInstallments": 1}]
    p1, p2 = {"id": "d", "parte": "1/2"}, {"id": "d", "parte": "2/2"}
    parcelas.anotar(_res(p1, p2), sel, {}, {})
    assert "parcela" not in p1 and "parcela" not in p2


def test_remontar_sem_parcelas_erp_nao_anota(monkeypatch):
    from pagamentos_dia import confirmacao
    chamou = []
    monkeypatch.setattr(parcelas, "anotar", lambda *a, **k: chamou.append(1) or a[0])
    e = confirmacao.Entradas(selecionados=[], anexos={}, overviews={}, textos={}, urls_ocr=set(),
                             cadastro_reembolso=None, regras_fornecedor={}, participantes={},
                             periodo=(None, None))
    confirmacao.remontar(e)
    assert chamou == []
    e.parcelas_erp = {}
    confirmacao.remontar(e)
    assert chamou == [1]
```

Antes de rodar, conferir que `confirmacao.Entradas(...)` aceita esses argumentos sem outros obrigatórios: `grep -n "class Entradas" -A45 pagamentos_dia/confirmacao.py`. Se houver outro campo sem padrão, acrescentá-lo ao teste com o valor vazio do tipo.

- [ ] **Step 2: Rodar e ver falhar**

Run: `PYTHONPATH=. python -m pytest tests/test_parcelas.py -q -p no:cacheprovider`
Expected: FAIL com `ModuleNotFoundError: No module named 'pagamentos_dia.parcelas'`

- [ ] **Step 3: Escrever `pagamentos_dia/parcelas.py`**

```python
# -*- coding: utf-8 -*-
"""Qual parcela do título a linha paga (spec de 19/11/2026, parte 2).

A lista de a pagar traz o total de parcelas (`numberOfFinancingInstallments`)
e não o número. O número sai do título inteiro (`trade-payables/<id>`, lido
por `leitura_do_dia.ler_titulos_no_erp`), pela posição da parcela em
`installments`. Medido em 19/11/2026: cerca de 2% dos lançamentos de seis
meses são de título com mais de uma parcela.

Formato de `installments` medido na Tarefa 1 do plano de 19/11/2026:
<escrever aqui as três respostas da sonda antes do commit>

Falha fechada: título que não leu ou parcela que não se acha fica com
`numero` None, e `nivel.nivel_da_linha` põe a linha em "Não li".
"""
from __future__ import annotations

from . import relatorio

#: Campo de ordem da parcela no título, na ordem em que se tenta. Sem nenhum,
#: vale a data. Conferido na Tarefa 1 (o medido vai primeiro).
CAMPOS_DE_ORDEM = ("installmentOrder", "order", "number")


def total_do_item(item: dict) -> int:
    try:
        return int((item or {}).get("numberOfFinancingInstallments") or 0)
    except (TypeError, ValueError):
        return 0


def titulos_parcelados(itens) -> list[str]:
    return sorted({str(i.get("tradePayableId")) for i in itens or ()
                   if i.get("tradePayableId") and total_do_item(i) > 1})


def _ordem(p: dict):
    for campo in CAMPOS_DE_ORDEM:
        v = p.get(campo)
        if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
            return (0, int(v), "")
    return (1, 0, str(p.get("plannedDate") or p.get("dueDate") or ""))


def posicao(titulo, id_parcela) -> int | None:
    lista = [p for p in ((titulo or {}).get("installments") or []) if isinstance(p, dict)]
    for k, p in enumerate(sorted(lista, key=_ordem), 1):
        if str(p.get("id")) == str(id_parcela):
            return k
    return None


def anotar(resultado, selecionados, parcelas_erp, overviews):
    """Põe `parcela` (só título de mais de uma) e `obs_parcela` (o comentário
    do detalhe da parcela) nos registros, pelo id do lançamento. Linha
    dividida em N boletos (`parte`) é do mesmo lançamento: herda o que o
    lançamento tem, e um título de uma parcela não vira "parcela k de N"."""
    por_id = {str(i.get("id")): i for i in selecionados or () if i.get("id")}
    for regs in (getattr(resultado, "contas", None) or {}).values():
        for r in regs:
            item = por_id.get(str(r.get("id") or "").split("#")[0])
            if item is None:
                continue
            obs = relatorio.comentario_do((overviews or {}).get(str(item.get("id"))))
            if obs:
                r["obs_parcela"] = obs
            total = total_do_item(item)
            if total > 1:
                titulo = (parcelas_erp or {}).get(str(item.get("tradePayableId")))
                r["parcela"] = {"numero": posicao(titulo, item.get("id")) if titulo else None,
                                "total": total}
    return resultado
```

- [ ] **Step 4: Ligar em `confirmacao.py`**

Na classe `Entradas`, depois do campo `titulos_erp`:

```python
    #: `{tradePayableId: título inteiro}` dos lançamentos PARCELADOS, lidos
    #: pela `leitura_do_dia` (spec de 19/11/2026). None — o padrão e o caso da
    #: Remessa — não anota parcela nenhuma.
    parcelas_erp: dict | None = None
```

Em `remontar`, depois do bloco `if entradas.dividir_boletos: ...` e antes do `return resultado`:

```python
    if entradas.parcelas_erp is not None:
        resultado = parcelas.anotar(resultado, entradas.selecionados,
                                    entradas.parcelas_erp, entradas.overviews)
```

E no topo, junto dos outros imports do pacote: `from . import parcelas` (conferir a linha de import existente com `grep -n "^from \. import" pagamentos_dia/confirmacao.py` e acrescentar `parcelas` em ordem alfabética nela).

- [ ] **Step 5: Ler os títulos parcelados em `leitura_do_dia.py`**

Logo depois do bloco que lê `entradas.titulos_erp` e do `if cancelar(): ... return leitura` que vem em seguida, antes de `leitura.entradas = entradas`:

```python
    # Parte 2 da spec de 19/11/2026: o número da parcela sai do título
    # inteiro. O que já foi lido para dividir boletos não é lido de novo.
    parcelados = parcelas.titulos_parcelados(a_pagar)
    ja_lidos = {t: v for t, v in entradas.titulos_erp.items() if t in set(parcelados)}
    entradas.parcelas_erp = {**ja_lidos, **ler_titulos_no_erp(
        api, [t for t in parcelados if t not in ja_lidos], log=log, cancelar=cancelar)}
    crono.etapa("parcelas")
    if cancelar():
        leitura.interrompida = True
        return leitura
```

E no topo: `from . import boletos_somados, confirmacao, ocr_boleto, parcelas, qr_pix, relatorio`.

- [ ] **Step 6: Atualizar a lista de etapas do cronômetro**

Em `tests/test_leitura_so_o_que_entra.py::test_o_tempo_de_cada_etapa_fica_na_leitura`, a lista esperada ganha `"parcelas"` antes de `"apurar"`:

```python
    assert list(leitura.tempos) == ["lista", "anexos e detalhes", "contatos",
                                    "baixar e ler anexos", "conferir a lista",
                                    "parcelas", "apurar"]
```

- [ ] **Step 7: Rodar e ver passar**

Run: `PYTHONPATH=. python -m pytest tests/test_parcelas.py tests/test_leitura_do_dia.py tests/test_leitura_so_o_que_entra.py tests/test_confirmacao.py tests/test_ganchos_da_tela_do_dia.py -q -p no:cacheprovider`
Expected: todos PASS

- [ ] **Step 8: Escrever no docstring de `parcelas.py` as três respostas da Tarefa 1 e commitar**

```bash
git add pagamentos_dia/parcelas.py pagamentos_dia/confirmacao.py pagamentos_dia/leitura_do_dia.py tests/test_parcelas.py tests/test_leitura_so_o_que_entra.py
git commit -m "Leitura do dia: numero da parcela do titulo parcelado e observacao da parcela

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Tarefa 5: o HTML das PJ mostra o nível

**Files:**
- Modify: `pagamentos_dia/html_pagamentos.py` (`contas_do_html_geral`: o laço das entradas e o laço "C2" da linha digitável repetida)
- Modify: `pagamentos_dia/modelos_html.py` (`MODELO_GERAL`: CSS, contadores, célula do fornecedor)
- Test: `tests/test_html_nivel.py`

**Interfaces:**
- Consumes: `nivel.nivel_da_linha`, `nivel.para_o_html`, `nivel.rebaixar_no_html`
- Produces: cada `entries[]` do `DATA` ganha `nivel`, `nivel_rotulo`, `motivos`, `conferido`, `parcela`, `obs_parcela`.

- [ ] **Step 1: Escrever os testes**

```python
"""O nível no HTML das PJ (spec de 19/11/2026). Fictício."""
from pagamentos_dia import html_pagamentos as hp
from pagamentos_dia import nivel
from pagamentos_dia.relatorio import Resultado
from tests.test_html_pagamentos import _gravar, _json, _ler, _linha, _resultado


def _entradas(resultado):
    return [e for c in hp.contas_do_html_geral(resultado) for e in c["entries"]]


def test_toda_entrada_tem_nivel_e_o_bloqueio_nao_mudou():
    antes = {e["id"]: e["bloqueio"] for e in _entradas(_resultado())}
    for e in _entradas(_resultado()):
        assert e["nivel"] in (nivel.PODE_PAGAR, nivel.OLHE, nivel.NAO_LI)
        assert e["bloqueio"] == antes[e["id"]]


def test_linha_conferida_pode_pagar_e_a_sem_conferencia_nao_li():
    res = Resultado({"CONTA EXEMPLO": [
        _linha("FORNECEDOR UM", 10.0, "1", conferencia="valor ✓ · fornecedor ✓"),
        _linha("FORNECEDOR DOIS", 20.0, "2", conferencia="(não cruzado)")]}, [])
    por_id = {e["id"]: e for e in _entradas(res)}
    assert por_id["1"]["nivel"] == nivel.PODE_PAGAR
    assert por_id["2"]["nivel"] == nivel.NAO_LI


def test_mesma_linha_digitavel_em_dois_lancamentos_desce_para_olhe():
    linha = "00190.00009 01234.567890 12345.678901 1 00000000000000"
    res = Resultado({"CONTA EXEMPLO": [
        _linha("FORNECEDOR UM", 10.0, "1", tipo="Boleto", dados=linha,
               conferencia="valor ✓ · fornecedor ✓"),
        _linha("FORNECEDOR DOIS", 10.0, "2", tipo="Boleto", dados=linha,
               conferencia="valor ✓ · fornecedor ✓")]}, [])
    for e in _entradas(res):
        assert e["nivel"] == nivel.OLHE
        assert any("mesma linha digitável" in m for m in e["motivos"])


def test_parcela_vai_para_o_html():
    res = Resultado({"CONTA EXEMPLO": [
        _linha("FORNECEDOR UM", 10.0, "1", conferencia="valor ✓ · fornecedor ✓",
               parcela={"numero": 3, "total": 10}, obs_parcela="depois da medição")]}, [])
    (e,) = _entradas(res)
    assert e["parcela"] == "3 de 10" and e["obs_parcela"] == "depois da medição"
    assert e["nivel"] == nivel.OLHE


def test_a_pagina_tem_os_contadores_e_a_etiqueta(tmp_path):
    g = _gravar(tmp_path)
    html = _ler(g.geral)
    assert 'id="niveis"' in html and "nivel-badge" in html
    dados = _json(html, "DATA")
    assert all("nivel" in e for c in dados["contas"] for e in c["entries"])
```

Antes de rodar, conferir dois nomes que este teste assume: o atributo do caminho do HTML geral em `hp.Gerados` (`grep -n "class Gerados" -A12 pagamentos_dia/html_pagamentos.py`; trocar `g.geral` pelo nome real) e a constante do `DATA` (`grep -n "const DATA" pagamentos_dia/modelos_html.py`).

- [ ] **Step 2: Rodar e ver falhar**

Run: `PYTHONPATH=. python -m pytest tests/test_html_nivel.py -q -p no:cacheprovider`
Expected: FAIL com `KeyError: 'nivel'`

- [ ] **Step 3: Calcular o nível em `contas_do_html_geral`**

No topo de `html_pagamentos.py`, no import do pacote, acrescentar `nivel`. No laço `for r in regs:`, logo depois de `entradas[-1].update(qr_do_pix(entradas[-1], r))`:

```python
            # O nível da linha (spec de 19/11/2026): só mostra; o bloqueio do
            # Copiar acima continua o mesmo.
            entradas[-1].update(nivel.para_o_html(
                nivel.nivel_da_linha(r, bloqueio=entradas[-1]["bloqueio"], vencido=vencido), r))
```

No laço "C2" (`for grupo in por_chave.values():`), dentro do `for e in grupo:`, depois da linha que soma `m` ao `e["bloqueio"]`:

```python
                nivel.rebaixar_no_html(e, m)
```

- [ ] **Step 4: Mostrar no `MODELO_GERAL`**

No `<style>`, antes de `@media (max-width:640px){`:

```css
  .nivel-badge{display:inline-block;padding:2px 8px;border-radius:6px;font-size:11px;font-weight:800;letter-spacing:.02em;margin-top:3px;}
  .nivel-PODE_PAGAR{background:var(--accent-bg);color:var(--accent);}
  .nivel-OLHE{background:#fff6d6;color:#7a5200;}
  .nivel-NAO_LI{background:var(--danger);color:#fff;}
  .motivos{margin:4px 0 0;padding-left:15px;font-size:11.5px;}
  .confere{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;}
  .c-item{font-size:10.5px;border:1px solid var(--border);border-radius:4px;padding:1px 5px;white-space:nowrap;}
  .c-bate{color:var(--accent);} .c-diverge{color:var(--bloq-text);font-weight:700;} .c-nao{color:var(--muted);border-style:dashed;}
  .parcela{display:inline-block;margin-top:4px;font-size:11px;font-weight:700;background:#eef0f3;border-radius:4px;padding:1px 6px;}
  .obs-parcela{font-size:11px;margin-top:2px;}
  tr[data-nivel="OLHE"] td:first-child{box-shadow:inset 4px 0 0 #d9a400;}
  #niveis{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 16px;}
  #niveis button{border:1px solid var(--border);background:var(--card);border-radius:10px;padding:8px 12px;font-size:13px;cursor:pointer;text-align:left;}
  #niveis button[aria-pressed="true"]{outline:2px solid var(--text);}
  #niveis b{display:block;font-size:20px;line-height:1.1;}
  body[data-filtro] .tabela-conta tbody tr[data-nivel]{display:none;}
  body[data-filtro="PODE_PAGAR"] tr[data-nivel="PODE_PAGAR"],
  body[data-filtro="OLHE"] tr[data-nivel="OLHE"],
  body[data-filtro="NAO_LI"] tr[data-nivel="NAO_LI"]{display:table-row;}
```

Logo antes de `<div class="summary" id="resumo">`:

```html
  <div id="niveis" aria-label="Linhas por nível"></div>
```

No JavaScript, dentro de `renderAccounts`, depois de `if(bloq) tr.classList.add('row-bloqueada');`:

```js
      tr.dataset.nivel = e.nivel || 'NAO_LI';
      const confCell = (e.conferido || []).map(([item, est]) =>
        `<span class="c-item c-${est === 'bate' ? 'bate' : est === 'diverge' ? 'diverge' : 'nao'}">${esc(item)}${est === 'bate' ? ' ✓' : est === 'diverge' ? ' ✗' : ': não conferido'}</span>`).join('');
      const nivelCell = `<span class="nivel-badge nivel-${esc(e.nivel || 'NAO_LI')}">${esc(e.nivel_rotulo || 'NÃO LI')}</span>`
        + ((e.motivos || []).length ? `<ul class="motivos">${e.motivos.map(m => `<li>${esc(m)}</li>`).join('')}</ul>` : '')
        + (e.parcela ? `<div><span class="parcela">Parcela ${esc(e.parcela)}</span></div>` : '')
        + (e.obs_parcela ? `<div class="obs-parcela">Observação: ${esc(e.obs_parcela)}</div>` : '')
        + (confCell ? `<div class="confere">${confCell}</div>` : '');
```

E na célula do fornecedor, trocar `<div class="status-badge">${esc(e.status)}</div>` por `${nivelCell}<div class="status-badge">${esc(e.status)}</div>` (o `status` continua, pequeno, embaixo).

Depois de `function renderSummary(){ ... }` (fim da função), acrescentar a função dos contadores e chamá-la onde `renderSummary()` é chamada (`grep -n "renderSummary()" pagamentos_dia/modelos_html.py`):

```js
function renderNiveis(){
  const caixa = document.getElementById('niveis');
  if(!caixa) return;
  const soma = {PODE_PAGAR:[0,0], OLHE:[0,0], NAO_LI:[0,0]};
  DATA.contas.forEach(c => (c.entries || []).forEach(e => {
    const k = soma[e.nivel] ? e.nivel : 'NAO_LI';
    soma[k][0] += 1; soma[k][1] += (e.centavos || 0);
  }));
  const rot = {PODE_PAGAR:'PODE PAGAR', OLHE:'OLHE', NAO_LI:'NÃO LI'};
  caixa.innerHTML = Object.keys(soma).map(k =>
    `<button type="button" data-n="${k}" aria-pressed="false"><span class="nivel-badge nivel-${k}">${rot[k]}</span><b>${soma[k][0]}</b>linhas · R$ ${brl(soma[k][1])}</button>`).join('');
  caixa.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
    const ligado = document.body.dataset.filtro === b.dataset.n;
    if(ligado) delete document.body.dataset.filtro; else document.body.dataset.filtro = b.dataset.n;
    caixa.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', String(!ligado && x === b)));
  }));
}
```

Conferir o nome da função de formatar centavos usada no resumo (`grep -n "function brl\|const brl\|function reais" pagamentos_dia/modelos_html.py`) e usar o mesmo no lugar de `brl`.

- [ ] **Step 5: Rodar os testes do HTML**

Run: `PYTHONPATH=. python -m pytest tests/test_html_nivel.py tests/test_html_pagamentos.py tests/test_html_vencimento.py tests/test_html_movimentos_do_dia.py tests/test_html_pj_qr_moura.py -q -p no:cacheprovider`
Expected: todos PASS

- [ ] **Step 6: Olhar a página de verdade.** Gerar um HTML fictício (`_gravar` num `tmp_path` dentro do scratchpad) e abrir no navegador do app (built-in browser), conferindo: etiqueta, motivos, chips, parcela, contadores, filtro por clique e o Copiar travado nas linhas bloqueadas como antes. Largura de celular (375 px) também.

- [ ] **Step 7: Commit**

```bash
git add pagamentos_dia/html_pagamentos.py pagamentos_dia/modelos_html.py tests/test_html_nivel.py
git commit -m "HTML das PJ: nivel, motivos, o que foi conferido e parcela em cada linha

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Tarefa 6: o HTML das PF mostra o nível

**Files:**
- Modify: `pagamentos_dia/html_pf.py` (`_cartao` e o CSS da página)
- Test: `tests/test_html_pf_nivel.py`

**Interfaces:**
- Consumes: `nivel.nivel_da_linha`, `nivel.ROTULO`
- Produces: o cabeçalho do cartão troca "APTO/ATENÇÃO" pelo rótulo do nível (`class="status s-<NIVEL>"`), e o corpo ganha a parcela.

- [ ] **Step 1: Escrever os testes**

```python
"""O nível no HTML das PF (spec de 19/11/2026). Fictício."""
from datetime import date

from pagamentos_dia import html_pf, nivel

HOJE = date(2026, 11, 19)


def _item(**r):
    base = {"tipo": "Pix", "dados": "fulano@exemplo.com", "valor": 50.0, "status": "APTO",
            "conferencia": "valor ✓ · fornecedor ✓", "id": "1", "favorecido": "PESSOA FICTICIA",
            "vencimento": "2026-11-19"}
    base.update(r)
    return html_pf.item_do_registro("PESSOA FISICA - CONTA MODELO", base)


def test_cartao_conferido_mostra_pode_pagar():
    html = html_pf._cartao(1, _item(), HOJE)
    assert "PODE PAGAR" in html and 's-PODE_PAGAR' in html


def test_cartao_sem_conferencia_mostra_nao_li():
    html = html_pf._cartao(1, _item(conferencia=""), HOJE)
    assert "NÃO LI" in html and "valor não conferido" in html


def test_cartao_com_alerta_e_olhe_e_o_codigo_continua_escondido():
    it = _item(status="ATENÇÃO — documento declara reembolso")
    html = html_pf._cartao(1, it, HOJE)
    assert "OLHE" in html or "NÃO LI" in html
    assert it.alertas, "o alerta de hoje continua"


def test_cartao_parcelado_mostra_a_parcela():
    html = html_pf._cartao(1, _item(parcela={"numero": 2, "total": 4}), HOJE)
    assert "Parcela 2 de 4" in html
```

Antes de rodar, conferir a assinatura de `item_do_registro` (`grep -n "def item_do_registro" pagamentos_dia/html_pf.py`) e se `_cartao` usa `it.escondido` vindo de `item_do_registro` ou de outro passo (`grep -n "escondido" pagamentos_dia/html_pf.py`); ajustar o teste ao que existe.

- [ ] **Step 2: Rodar e ver falhar**

Run: `PYTHONPATH=. python -m pytest tests/test_html_pf_nivel.py -q -p no:cacheprovider`
Expected: FAIL (o cartão ainda diz "APTO")

- [ ] **Step 3: Mudar `_cartao`**

No topo do arquivo, junto do import de `html_pagamentos`: `from . import nivel`. Dentro de `_cartao`, depois de `vencido = bool(venc) and venc < hoje.isoformat()`:

```python
    nv = nivel.nivel_da_linha(r, bloqueio="; ".join(it.alertas), vencido=vencido)
    parcela = r.get("parcela") or {}
    texto_parcela = (f"Parcela {parcela.get('numero') or '?'} de {parcela.get('total')}"
                     if int(parcela.get("total") or 0) > 1 else "")
```

Trocar a linha do status:

```python
    <span class="status s-{nv.nome}">{nivel.ROTULO[nv.nome]}</span>
```

E, logo depois de `<h3>{_e(quem)}</h3>`:

```python
      {f'<p class="parcela">{_e(texto_parcela)}</p>' if texto_parcela else ''}
      {f'<p class="obs-parcela">Observação: {_e(r.get("obs_parcela"))}</p>' if r.get("obs_parcela") else ''}
      {lista(nv.motivos, 'motivos')}
```

No CSS da página PF (perto de `.alertas {`), acrescentar:

```css
.s-PODE_PAGAR { background:#e8f5ef; color:#0f6b4c }
.s-OLHE { background:#fff6d6; color:#7a5200 }
.s-NAO_LI { background:#c0392b; color:#fff }
.parcela { font-weight:700; margin:2px 0 } .obs-parcela { margin:2px 0 }
.motivos { font-size:.92em; padding-left:18px }
```

Conferir se as classes antigas `s-ok`/`s-at` são usadas no JavaScript da página (`grep -n "s-ok\|s-at" pagamentos_dia/html_pf.py`). Se forem (contador `__NA__`, filtro), manter as duas classes no `<span>`: `class="status s-{nv.nome} s-{'at' if it.alertas else 'ok'}"`.

- [ ] **Step 4: Rodar**

Run: `PYTHONPATH=. python -m pytest tests/test_html_pf_nivel.py tests/test_html_pf.py -q -p no:cacheprovider`
Expected: todos PASS

- [ ] **Step 5: Olhar a página** como na Tarefa 5, Step 6 (cartões no PC e a 375 px).

- [ ] **Step 6: Commit**

```bash
git add pagamentos_dia/html_pf.py tests/test_html_pf_nivel.py
git commit -m "HTML das PF: nivel e parcela em cada cartao

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Tarefa 7: documentação, régua inteira e pedido de mudança

**Files:**
- Modify: `.claude/rules/arquitetura-pagamentos-dia.md` (dois parágrafos novos: `nivel.py` e `parcelas.py`)

- [ ] **Step 1: Escrever na regra da pasta** um parágrafo por módulo novo: o que decide, a medição de 3.946 linhas, as duas constantes de decisão do dono, a falha fechada da parcela e o formato medido na Tarefa 1.

- [ ] **Step 2: Rodar a régua**

Run:

```bash
python -m ruff check --select E9,F .
vermin --target=3.11 --violations pagamentos_dia/nivel.py pagamentos_dia/parcelas.py pagamentos_dia/confirmacao.py pagamentos_dia/leitura_do_dia.py pagamentos_dia/html_pagamentos.py pagamentos_dia/html_pf.py
sem_tk=$(grep -L "raiz\|tkinter\|Tk()\|galeria\|barra\b" tests/test_*.py | tr '\n' ' '); PYTHONPATH=. python -m pytest $sem_tk -q -p no:cacheprovider
```

Expected: ruff limpo; vermin sem violação (se `vermin` não estiver no PATH, `python -m vermin` não funciona nesta máquina: dizer isso no PR em vez de afirmar que passou); pytest todo verde.

- [ ] **Step 3: Revisão de dinheiro** com o agente `revisor-dinheiro` sobre o diff do ramo, pedindo em especial: o bloqueio do Copiar idêntico para todo registro dos testes existentes; nenhum caminho em que linha sem valor conferido saia "Pode pagar"; `parcelas_erp` nunca chegando à Remessa/Retorno sozinha; leitura do título parcelado só por GET.

- [ ] **Step 4: Abrir o pedido de mudança** (ramo próprio a partir da `main`, sem juntar), com o texto: o que muda para quem usa, o que não muda, a medição, o que não foi provado ao vivo. Anotar em `00 - Início/Pendências e perguntas.md` do cofre, seção "PRs abertos", com data para decidir.
