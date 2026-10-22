# Entrega 5: um lançamento pago com N boletos (Pagamentos do dia + aba "Anexar (novo)"). Plano de implementação

> **Para quem executa:** SUB-SKILL OBRIGATÓRIA: superpowers:subagent-driven-development (ou superpowers:executing-plans). Siga as tarefas na ordem. Em cada tarefa: teste primeiro, depois o código. Cada tarefa termina num commit.

**Goal:** (A) Na aba "Pagamentos do dia", quando os boletos anexados a um lançamento somam **exatamente** (ao centavo) o valor dele, esse lançamento vira N linhas, uma por boleto, cada uma com a sua linha digitável e o seu valor. Todas levam o status "ATENÇÃO — 1 lançamento virou N boletos (somam exato) — conferir". Se a soma não bater, a linha não é dividida e ganha um aviso. A planilha, o HTML e a remessa que saem da tela nova levam as N linhas, com a descrição de sempre, que o Anexar consegue casar. A aba Remessa/Retorno continua igual quando monta a própria leitura. (B) Uma aba nova, "Anexar (novo)", faz tudo o que a Anexar faz hoje e, numa segunda fase, anexa N comprovantes que somam exatamente um pagamento que ficou SEM PAR. Quando há ambiguidade, não anexa nada e registra a dúvida. A aba nova usa o navegador e o executor do `AnexarFrame` que já existe.

**Architecture:**
- **(A)** Um módulo puro novo, `pagamentos_dia/boletos_somados.py`, faz um pós-processamento do `relatorio.Resultado`. Ele só age sobre a linha que o `montar_registros` já marcou como "ATENÇÃO — vários boletos no título". Quem liga a divisão é um campo novo, `confirmacao.Entradas.dividir_boletos` (padrão `False`). Esse campo só recebe `True` em `leitura_do_dia`, e viaja junto com as Entradas para a Remessa (`receber_apuracao`). O frame da Remessa monta as próprias Entradas sem esse campo, e nada muda para ele.
- **(B)** `anexar/anexar_novo.AnexarNovoFrame` é uma subclasse de `AnexarFrame`:
  - **Sem navegador:** `DONO_DO_NAVEGADOR = False`. Não cria executor e não pulsa. `submeter`, `mc`, `api`, `garantir_sessao`, `ocupado` e os avisos são delegados ao `AnexarFrame` dono, com `dona=self`.
  - **Fase 1:** o "Casar e anexar" roda o `AnexarFrame._t_auto` de sempre, inteiro e sem cópia.
  - **Fase 2:** `varios_comprovantes.fase_das_somas` roda sobre os SEM PAR. Usa `matcher_somado.casar_somados`, uma camada pura e opcional por cima de `matcher.casar`, que não muda. Anexa só pela API, com prova por nome.

**Tech Stack:** Python 3.11, tkinter/ttk, `Decimal`, pytest, openpyxl (já está no exe). Nenhuma pasta nova, nenhum import novo da stdlib fora do que o exe já tem (`itertools`, `decimal`, `collections`). Por isso `build.yml` e `motor_minimo.txt` não mudam.

**Spec:** `C:\AUTOMAÇÕES MAIS CONTROLE\PROPOSTA - 2026-10-21 pagamentos do dia numa tela so.html` (v3: "Dividir em dois boletos — Automático só se a soma bater ao centavo; sempre com alerta para você olhar" e "Dividir em dois boletos, na lista e no Anexar"). Também `.superpowers/sdd/contexto-entregas-2-a-5.md`.

---

## Global Constraints

- **O comportamento das abas atuais não muda.** Valem a Remessa/Retorno (`PagamentosDiaFrame`), o Saldo de pagamentos e a **Anexar atual**. Tudo o que é novo é ligado por parâmetro ou campo com padrão "desligado", ou fica em módulo novo. Cada mudança em código compartilhado tem um teste que prova o caminho antigo.
- **Dinheiro em `Decimal`:** na soma dos boletos e no "ao centavo". No matcher, a soma é em centavos `int`, que é a unidade que o `matcher.parse_pdf` e o `mc_api.montar_pagos` já usam. O `float` de `registro["valor"]` só existe porque é o formato que a planilha, o HTML e a remessa já consomem.
- **Repositório público:** nenhum nome, CNPJ, conta ou valor real em código, teste, comentário ou commit. Os testes usam "Fornecedor Modelo Ltda", "OBRA MODELO", "OC 5555" e "CONTA EXEMPLO - SICOOB".
- **Testes puros:** sem fixture `raiz` e sem janela Tk. Frames são testados por `__new__` ou com o `__init__` sob monkeypatch, como já faz `tests/test_abas_em_paralelo.py`.
- **Nunca "anexado" sem prova:** a fase 2 só trabalha com quem `mc_api.estado_anexo` diz `SEM_ANEXO` numa verificação feita na hora (`NAO_VERIFICADO` fica de fora). A prova final é pelo NOME de cada arquivo na listagem do sub-pagamento.
- **Duplicidade de anexo:** a fase 2 nunca passa pela tela, nunca repete um POST e nunca reaproveita um PDF da fase 1. Se dois comprovantes têm o mesmo tamanho, ou se o pagamento já tem algum anexo, nada sobe.
- **Um navegador só:** a cópia não cria `ThreadPoolExecutor`, `MCClient` nem Chrome. No modo central ela ganha uma vaga do dono, como as outras seis abas.
- **Rodar os testes:** `python -m pytest tests/<arquivo> -q`. A suíte inteira: `python -m pytest tests -q`. Antes do PR: `ruff check --select E9,F .` e `vermin --target=3.11 --violations <arquivos novos>`.
- **Commits** em português, terminando com a linha `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus (para o revisor de dinheiro)

1. A Remessa/Retorno, quando monta a própria leitura, continua com UMA linha "vários boletos no título". Só o `leitura_do_dia` passa `dividir_boletos=True` (teste por AST).
2. A divisão só acontece quando o CONJUNTO INTEIRO das linhas válidas do título soma o valor ao centavo, com 1 parcela em aberto e sem pagamento anterior. As N linhas nascem em ATENÇÃO: desmarcadas na remessa e com o Copiar bloqueado no HTML.
3. As N linhas guardam o MESMO `id` do lançamento (retorno, baixa, "já saiu?"). O candidato de cada uma é o k-ésimo daquele id (`AnaliseRemessa.candidato(parte=)`). O HTML separa as linhas pelo id `"L1#k/N"`.
4. `matcher_somado` exige o seguinte e manda para dúvida quando há dois conjuntos possíveis, PDF repetido ou PDF disputado:
   - cada PDF aponta o pagamento sozinho: mesma data e (OC/NF rotulada ou centro de custo);
   - nenhum PDF tem o valor de outro pago do período, nem é de outra conta.
5. `varios_comprovantes.anexar_varios` usa só a API. Exige o pagamento vazio antes e tamanhos distintos, para nos primeiro erro sem tentar de novo e prova pelo nome. A tela (`mc.anexar`) responderia "ja_tinha" para o 2º comprovante.

**Testes que provam:** `tests/test_boletos_somados.py`, `tests/test_matcher_somado.py`, `tests/test_varios_comprovantes.py`, `tests/test_anexar_novo.py`, mais `tests/test_abas_em_paralelo.py` (arquivo novo em `_CHAMADORES`) e `tests/test_usuarios.py` (o aprovador não vê a cópia).

---

## ⚠ ARQUIVOS EXISTENTES MODIFICADOS (outras entregas mexem em `tela_do_dia/` e `pagamentos_dia/`)

| Arquivo | O que muda | Sentido para as abas atuais |
|---|---|---|
| `pagamentos_dia/confirmacao.py` | `Entradas.dividir_boletos: bool = False` (fim do dataclass, :75); `remontar` aplica `boletos_somados.dividir` só com o campo ligado (:121-139); `AnaliseRemessa.candidato(..., parte=0)` (:212); ordinal por id em `grupos_da_confirmacao` (:795-800) | idêntico: campo desligado; `parte=0` = o primeiro de sempre; com ids únicos o ordinal é sempre 0 |
| `pagamentos_dia/leitura_do_dia.py` | `Entradas(..., dividir_boletos=True)` (:198) + `leitura.avisos.extend(boletos_somados.avisos(...))` (:205) | só a tela nova |
| `pagamentos_dia/html_pagamentos.py` | `contas_do_html_geral` :535-537, o `"id"` da entrada ganha `#k/N` só quando o registro tem `parte` | registro sem `parte` → id idêntico |
| `anexar/anexar_comprovantes.py` | três atributos de classe (`TITULO`, `TRILHA`, `DONO_DO_NAVEGADOR = True`) depois de :255; :263 e :300 sob `if self.DONO_DO_NAVEGADOR`; :308/:311 passam a ler `self.TITULO`/`self.TRILHA`. **Nenhuma linha de fluxo, casamento ou anexo muda** | idêntico (os padrões são os textos e o comportamento de hoje) |
| `comprovantes_app.py` | import (:39); `aba_anx2 = AnexarNovoFrame(conteudo, aba_anx)` (depois de :309); `"anx2"` em `quadros` ANTES de `"anx"` (:347); item de menu "Anexar (novo)" logo depois de "Anexar" (:438, :446) | nenhuma aba muda |
| `ferramentas/galeria.py` | `_ORDEM` (:192) + `_montar("anx2", …)` (:366) | só ferramenta |
| `tests/test_abas_em_paralelo.py` | `"anexar/anexar_novo.py"` em `_CHAMADORES` | régua |
| `tests/test_usuarios.py` | caso novo do aprovador | régua |
| `.claude/rules/arquitetura-anexar.md`, `arquitetura-pagamentos-dia.md`, `arquitetura-tela-do-dia.md`, `arquitetura-interface.md` (:25 "treze"→"catorze"), `arquitetura-ferramentas.md` (:16), `CLAUDE.md` (:426 "13 telas"→"14 telas") | documentação | — |

**Não são tocados:** `tela_do_dia/*` (nenhum arquivo), `pagamentos_dia/relatorio.py`, `remessa_dia.py`, `pagamentos_frame.py`, `baixa_erp.py`, `anexar/matcher.py`, `mc_api.py`, `mc_client.py`, `.github/workflows/build.yml` e `motor_minimo.txt`.

## Mapa de arquivos

| Arquivo | Responsabilidade |
|---|---|
| **novo** `pagamentos_dia/boletos_somados.py` | (A) puro: `decidir`, `dividir`, `avisos`, `status_dividido`, `STATUS_VARIOS` |
| **novo** `anexar/matcher_somado.py` | (B) puro: `casar_somados` (N PDFs = 1 pagamento) |
| **novo** `anexar/varios_comprovantes.py` | (B) `anexar_varios`, `Somas`, `fase_das_somas`, `juntar_fim`, `resumo_das_somas`, `acrescentar_ao_relatorio` (a `api` entra por parâmetro) |
| **novo** `anexar/anexar_novo.py` | (B) `AnexarNovoFrame`, `_FilaComDesvio` (tela fina) |
| **novo** `tests/test_boletos_somados.py`, `tests/test_matcher_somado.py`, `tests/test_varios_comprovantes.py`, `tests/test_anexar_novo.py` | testes |

---

## Tarefa 1: Caracterizar o caso de hoje (dois boletos viram uma linha "vários boletos")

**Modelo:** haiku

**Files:** Create `tests/test_boletos_somados.py`

**Interfaces (reais):**
- `relatorio.montar_registros(lancamentos, anexos, overviews, textos, incluir=(), excluir=(), …) -> Resultado` (`pagamentos_dia/relatorio.py:1516`)
- `relatorio._linhas_dos_anexos(files, textos, valor, urls_ocr=(), ignorar="")` (:573)
- `ocr_boleto._mod11_geral`, `_mod10`, `valida` (:75, :48, :133)
- `confirmacao.Entradas(selecionados, anexos, overviews, textos, urls_ocr, cadastro_reembolso, regras_fornecedor, participantes, periodo, anexos_nao_lidos=…, titulos_nao_lidos=…, qr_pix=…)` (`confirmacao.py:50`)

- [ ] **Passo 1: escrever os testes de caracterização**

```python
# -*- coding: utf-8 -*-
"""Entrega 5 (A): um lançamento pago com N boletos. Dados fictícios — o repo é público."""
import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

from pagamentos_dia import confirmacao, ocr_boleto, relatorio

DIA = date(2026, 10, 21)
CONTA = "CONTA EXEMPLO - SICOOB"
RAIZ = Path(__file__).resolve().parents[1]
OUTRO_LIVRE = "2680800035545486352881211"


def gera_linha(valor_centavos, fator=9999, livre="1570700024434375241770100"):
    """Linha digitável bancária com os DVs fechando (a de tests/test_casamento_html.py)."""
    b43 = "3419" + f"{fator:04d}" + f"{valor_centavos:010d}" + livre
    b = b43[:4] + str(ocr_boleto._mod11_geral(b43)) + b43[4:]
    campos = [b[0:4] + b[19:24], b[24:34], b[34:44]]
    c = [x + str(ocr_boleto._mod10(x)) for x in campos]
    linha = (f"{c[0][:5]}.{c[0][5:]} {c[1][:5]}.{c[1][5:]} "
             f"{c[2][:5]}.{c[2][5:]} {b[4]} {b[5:19]}")
    assert ocr_boleto.valida(linha)
    return linha


def _anexo(nome, url):
    return {"filename": nome, "tagName": "Boleto", "extension": ".pdf", "downloadUrl": url}


def _item(**extra):
    base = {"id": "L1", "tradePayableId": "T1", "paidTo": "Fornecedor Modelo Ltda",
            "remainingValue": 1000.0, "plannedDate": "2026-10-21", "paid": False,
            "tradePayableAccount": {"name": CONTA}, "tradePayablePaymentMethod": "Boleto",
            "documentNumber": "64000", "costCentreDetails": [{"workName": "OBRA MODELO"}]}
    base.update(extra)
    return base


def _linhas_dos_boletos(valores_centavos, livres=None):
    livres = livres or [None] * len(valores_centavos)
    return [gera_linha(v, livre=l) if l else gera_linha(v)
            for v, l in zip(valores_centavos, livres)]


def _entradas(itens, valores_centavos, livres=None, **k):
    linhas = _linhas_dos_boletos(valores_centavos, livres)
    anexos = {"T1": [_anexo(f"boleto {i}", f"u{i}") for i in range(1, len(linhas) + 1)]}
    textos = {f"u{i}": f"Banco Exemplo\n{ln}\n" for i, ln in enumerate(linhas, 1)}
    return confirmacao.Entradas(
        selecionados=itens, anexos=anexos, overviews={}, textos=textos, urls_ocr=set(),
        cadastro_reembolso=None, regras_fornecedor={}, participantes={},
        periodo=(DIA, DIA), **k)


def _linhas(resultado):
    return [r for regs in resultado.contas.values() for r in regs]


# ------------------------------------------------------ o caso de hoje
def test_dois_boletos_que_somam_o_lancamento_viram_uma_linha_de_varios_boletos():
    """O caso real: 400 + 600 anexados a um lançamento de 1.000. Hoje nenhuma
    linha tem o valor do lançamento e a linha sai sem dado de pagamento."""
    (linha,) = _linhas(confirmacao.remontar(_entradas([_item()], [40000, 60000])))
    assert linha["status"] == "ATENÇÃO — vários boletos no título"
    assert linha["dados"] == ""
    assert linha["obs"].split(" · ")[0] == ("Há 2 boletos no título, não dá para saber "
                                            "qual é desta parcela — conferir antes de pagar")


def test_o_frame_da_remessa_nunca_liga_a_divisao():
    """Guarda: a Remessa/Retorno monta as Entradas dela sem a chave nova."""
    arvore = ast.parse((RAIZ / "pagamentos_dia/pagamentos_frame.py").read_text(encoding="utf-8"))
    assert not [kw for no in ast.walk(arvore) if isinstance(no, ast.Call)
                for kw in no.keywords if kw.arg == "dividir_boletos"]
```

- [ ] **Passo 2:** `python -m pytest tests/test_boletos_somados.py -q`. Esperado: **2 passed** (caracterizam o código de hoje). Se o 1º falhar, ajuste SÓ o fixture até o status ser o de hoje, sem mexer em código.
- [ ] **Passo 3: commit**
```
git add tests/test_boletos_somados.py
git commit -m "Testes: caracteriza o lançamento com dois boletos que somam o valor" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Tarefa 2: `pagamentos_dia/boletos_somados.py`, dividir quando a soma é exata

**Modelo:** opus

**Files:** Create `pagamentos_dia/boletos_somados.py`; Modify `tests/test_boletos_somados.py`

**Interfaces (reais):**
- `relatorio.Resultado(contas: dict, omitidos: list)` (`relatorio.py:1505`)
- `relatorio._linhas_dos_anexos(files, textos, valor: float, urls_ocr=())` → `[(linha, anexo)]` (:573)
- `relatorio.ja_pago_do_item(item) -> float` (:199)
- `relatorio.brl(v) -> str` (:74)
- `ocr_boleto.valor_da_linha(linha) -> float | None` (`ocr_boleto.py:143`)
- `confirmacao.Entradas.selecionados/anexos/textos/urls_ocr` (`confirmacao.py:50`). O módulo recebe as Entradas por duck typing e NÃO importa `confirmacao` (evita ciclo).

**Saída (assinaturas novas):**
```python
STATUS_VARIOS: str
def status_dividido(n: int) -> str
@dataclass(frozen=True) class Decisao: partes: tuple = (); aviso: str = ""
def decidir(registro: dict, item: dict, files, textos: dict, urls_ocr=(), parcelas_abertas: int = 1) -> Decisao
def dividir(resultado: relatorio.Resultado, entradas) -> relatorio.Resultado
def avisos(resultado: relatorio.Resultado) -> list[str]
```

- [ ] **Passo 1: testes que falham** (acrescentar ao arquivo)

```python
from pagamentos_dia import boletos_somados as bs


def _dividido(valores, itens=None, livres=None):
    itens = itens or [_item()]
    entradas = _entradas(itens, valores, livres)
    base = relatorio.montar_registros(entradas.selecionados, entradas.anexos, {}, entradas.textos)
    return base, bs.dividir(base, entradas)


def test_o_status_que_dispara_e_o_do_relatorio():
    (linha,) = _linhas(confirmacao.remontar(_entradas([_item()], [40000, 60000])))
    assert linha["status"] == bs.STATUS_VARIOS
    assert bs._OBS_VARIOS.fullmatch(linha["obs"].split(" · ")[0])


def test_boletos_que_somam_exato_viram_n_linhas():
    base, res = _dividido([40000, 60000])
    linhas = _linhas(res)
    assert [r["parte"] for r in linhas] == ["1/2", "2/2"]
    valores = [Decimal(str(r["valor"])) for r in linhas]
    assert sorted(valores) == [Decimal("400.00"), Decimal("600.00")]
    assert sum(valores) == Decimal("1000.00")
    assert {ocr_boleto.valor_da_linha(r["dados"]) for r in linhas} == {400.0, 600.0}
    assert all(r["status"] == bs.status_dividido(2) for r in linhas)
    assert all(r["id"] == "L1" for r in linhas)                   # o lançamento é o mesmo
    assert linhas[0]["descricao"] == linhas[1]["descricao"]       # o Anexar casa pela descrição
    assert not any(bs._OBS_VARIOS.fullmatch(p) for r in linhas for p in r["obs"].split(" · "))
    assert _linhas(base)[0]["dados"] == ""                        # o Resultado original não muda


def test_tres_boletos_que_somam_exato():
    _base, res = _dividido([20000, 30000, 50000])
    assert [r["parte"] for r in _linhas(res)] == ["1/3", "2/3", "3/3"]


def test_soma_que_nao_bate_ao_centavo_nao_divide_e_avisa():
    _base, res = _dividido([40000, 59999])
    (linha,) = _linhas(res)
    assert linha["status"] == bs.STATUS_VARIOS and linha["dados"] == ""
    assert "somam R$ 999,99" in linha["obs"] and "R$ 1.000,00" in linha["obs"]
    assert "não dividi" in bs.avisos(res)[0]


def test_parcelas_abertas_do_mesmo_titulo_nao_dividem():
    _base, res = _dividido([40000, 60000], itens=[_item(id="L1"), _item(id="L2")])
    assert [r["status"] for r in _linhas(res)] == [bs.STATUS_VARIOS] * 2
    assert all("2 parcelas em aberto" in r["obs"] for r in _linhas(res))


def test_titulo_com_pagamento_anterior_nao_divide():
    _base, res = _dividido([40000, 60000], itens=[_item(sumOfPaidValues=200.0)])
    (linha,) = _linhas(res)
    assert linha["status"] == bs.STATUS_VARIOS and "já tem pagamento" in linha["obs"]


def test_linha_que_nao_e_de_varios_boletos_passa_intacta():
    entradas = _entradas([_item(remainingValue=400.0)], [40000])
    base = relatorio.montar_registros(entradas.selecionados, entradas.anexos, {}, entradas.textos)
    assert bs.dividir(base, entradas).contas == base.contas


def test_avisos_dizem_que_o_lancamento_virou_n_boletos():
    _base, res = _dividido([40000, 60000])
    assert bs.avisos(res) == [
        "1 lançamento virou 2 boletos (somam exato) — conferir: Fornecedor Modelo Ltda, "
        f"R$ 1.000,00 ({CONTA})"]
```

- [ ] **Passo 2:** `python -m pytest tests/test_boletos_somados.py -q`. Esperado: FAIL, `ModuleNotFoundError: No module named 'pagamentos_dia.boletos_somados'`.
- [ ] **Passo 3: implementar**

```python
# -*- coding: utf-8 -*-
"""Um lançamento pago com N boletos (entrega 5, dono 21/10/2026).

O caso real: dois boletos do mesmo fornecedor anexados a UM lançamento, cuja
soma dava exatamente o valor dele; o dono agendou os dois. O
`relatorio.montar_registros` não acha linha com o valor do lançamento e
devolve UMA linha "ATENÇÃO — vários boletos no título", sem dado de
pagamento. Aqui essa linha vira N — uma por boleto, com a linha digitável e o
valor DELE — quando, e só quando, as linhas válidas do título somam o
lançamento AO CENTAVO. Não bateu: não divide, só avisa.

Só a aba "Pagamentos do dia" liga isto (`confirmacao.Entradas.dividir_boletos`,
posto pela `leitura_do_dia`). A Remessa/Retorno monta as Entradas dela sem a
chave e continua vendo uma linha só.

As N linhas guardam o MESMO `id` (o retorno do banco e a baixa voltam ao
lançamento por ele) e a MESMA descrição (é por ela que o Anexar casa os N
comprovantes). Nascem em ATENÇÃO: desmarcadas na remessa, Copiar bloqueado no
HTML — o dono pediu "sempre com alerta para você olhar".
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from . import ocr_boleto, relatorio

CENTAVO = Decimal("0.01")
ZERO = Decimal("0.00")
#: O status que o `montar_registros` dá ao título com várias linhas válidas e
#: nenhuma do valor do lançamento. Cópia do texto, guardada por teste.
STATUS_VARIOS = "ATENÇÃO — vários boletos no título"
#: A frase da Obs que deixa de ser verdade depois de dividir.
_OBS_VARIOS = re.compile(r"Há \d+ boletos no título, não dá para saber qual é desta "
                         r"parcela — conferir antes de pagar")


def status_dividido(n: int) -> str:
    return f"ATENÇÃO — 1 lançamento virou {n} boletos (somam exato) — conferir"


def _em_centavos(valor) -> Decimal:
    return Decimal(str(valor or 0)).quantize(CENTAVO, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Decisao:
    #: ((linha digitável, valor Decimal, anexo), ...) — vazio: não divide.
    partes: tuple = ()
    #: Por que não dividiu, quando há o que dizer.
    aviso: str = ""


def decidir(registro: dict, item: dict, files, textos: dict, urls_ocr=(),
            parcelas_abertas: int = 1) -> Decisao:
    """Divide? Só a linha de "vários boletos", sem dado de pagamento, de título
    com UMA parcela em aberto e sem pagamento anterior, e só com o CONJUNTO
    INTEIRO das linhas válidas — nunca um subconjunto escolhido aqui."""
    if (registro.get("tipo") != "Boleto" or registro.get("status") != STATUS_VARIOS
            or (registro.get("dados") or "").strip() or item.get("paid")
            or registro.get("parcial") or registro.get("valor_diverge")
            or registro.get("reembolso")):
        return Decisao()
    if parcelas_abertas != 1:
        return Decisao(aviso=f"o título tem {parcelas_abertas} parcelas em aberto — não "
                             "dá para saber quais boletos são desta; não dividi")
    if relatorio.ja_pago_do_item(item) > 0:
        return Decisao(aviso="o título já tem pagamento — não dividi os boletos")
    valor = float(registro.get("valor") or 0)
    linhas = relatorio._linhas_dos_anexos(files, textos, valor, urls_ocr)
    if len(linhas) < 2:
        return Decisao()
    partes = []
    for linha, anexo in linhas:
        v = ocr_boleto.valor_da_linha(linha)
        if not v or v <= 0:
            return Decisao(aviso="um dos boletos do título não diz o valor — não dividi")
        partes.append((linha, _em_centavos(v), anexo))
    total, alvo = sum((p[1] for p in partes), ZERO), _em_centavos(valor)
    if total != alvo:
        return Decisao(aviso=f"os {len(partes)} boletos do título somam "
                             f"{relatorio.brl(total)} e o lançamento é "
                             f"{relatorio.brl(alvo)} — não dividi; conferir")
    return Decisao(partes=tuple(partes))


def _obs_sem_a_frase(obs: str) -> list[str]:
    return [p for p in (obs or "").split(" · ") if p and not _OBS_VARIOS.fullmatch(p)]


def _partes_do_registro(registro: dict, decisao: Decisao) -> list[dict]:
    n = len(decisao.partes)
    total = sum((p[1] for p in decisao.partes), ZERO)
    resto = _obs_sem_a_frase(registro.get("obs"))
    saida = []
    for k, (linha, valor, anexo) in enumerate(decisao.partes, 1):
        nome = (anexo.get("filename") or "?").strip()
        obs = (f"boleto {k} de {n} (anexo '{nome}') · os {n} boletos somam "
               f"{relatorio.brl(total)}, o valor do lançamento")
        saida.append({**registro, "dados": linha, "valor": float(valor),
                      "status": status_dividido(n), "obs": " · ".join([obs, *resto]),
                      "parte": f"{k}/{n}", "valor_do_lancamento": float(total)})
    return saida


def dividir(resultado: relatorio.Resultado, entradas) -> relatorio.Resultado:
    """O `Resultado` com cada lançamento de boletos que somam exato em N
    linhas, no lugar da original. Não muda o `resultado` recebido."""
    selecionados = list(entradas.selecionados or ())
    por_id = {str(i.get("id")): i for i in selecionados if i.get("id")}
    abertas = Counter(str(i.get("tradePayableId")) for i in selecionados
                      if not i.get("paid"))
    contas = {}
    for conta, registros in (resultado.contas or {}).items():
        novos = []
        for reg in registros:
            item = por_id.get(str(reg.get("id") or ""))
            if item is None:
                novos.append(reg)
                continue
            titulo = str(item.get("tradePayableId"))
            d = decidir(reg, item, entradas.anexos.get(titulo) or [], entradas.textos,
                        entradas.urls_ocr, abertas[titulo])
            if d.partes:
                novos.extend(_partes_do_registro(reg, d))
            elif d.aviso:
                novos.append({**reg, "aviso_soma": d.aviso,
                              "obs": " · ".join(filter(None, [d.aviso, reg.get("obs")]))})
            else:
                novos.append(reg)
        contas[conta] = novos
    return relatorio.Resultado(contas, resultado.omitidos)


def avisos(resultado: relatorio.Resultado) -> list[str]:
    """As frases do topo da tela (uma por lançamento dividido ou recusado)."""
    saida = []
    for conta, registros in (resultado.contas or {}).items():
        for reg in registros:
            parte = str(reg.get("parte") or "")
            if parte.startswith("1/"):
                saida.append(f"1 lançamento virou {parte.split('/')[1]} boletos (somam "
                             f"exato) — conferir: {reg.get('favorecido') or '?'}, "
                             f"{relatorio.brl(reg.get('valor_do_lancamento'))} ({conta})")
            elif reg.get("aviso_soma"):
                saida.append(f"{reg.get('favorecido') or '?'} ({conta}): {reg['aviso_soma']}")
    return saida
```

Os testes de três boletos usam `_dividido([20000, 30000, 50000])` e cada linha sai com dígitos distintos, porque o valor está dentro do código. Se algum par repetir dígitos, passe `livres=[None, OUTRO_LIVRE, None]`.

- [ ] **Passo 4:** `python -m pytest tests/test_boletos_somados.py -q`. Esperado: tudo passa.
- [ ] **Passo 5: commit**
```
git add pagamentos_dia/boletos_somados.py tests/test_boletos_somados.py
git commit -m "Pagamentos do dia: lançamento cujos boletos somam exato vira N linhas (módulo puro)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Tarefa 3: Ligar a divisão só na tela nova (`Entradas.dividir_boletos`) e dar a cada linha o seu candidato

**Modelo:** opus

**Files:** Modify `pagamentos_dia/confirmacao.py`, `pagamentos_dia/leitura_do_dia.py`, `tests/test_boletos_somados.py`

**Interfaces (reais):**
- `confirmacao.Entradas` (:50-75, último campo `qr_pix: dict = field(default_factory=dict)`)
- `confirmacao.remontar(entradas, ids_nao_confirmados=()) -> relatorio.Resultado` (:121)
- `AnaliseRemessa.candidato(self, conta: str, ident: str)` (:212)
- `grupos_da_confirmacao(resultado, analise, lancamentos, destacar=(), fornecedores=None)` (:765; laço em :795-800)
- `leitura_do_dia.ler_pagamentos(api, ini, fim, *, abrir_historico, carregar_mapas, cadastro_reembolso=None, regras_fornecedor=None, destacar=(), conta_entra=…, log=print, progresso=…, cancelar=…, **leitores)` (:143); `Entradas(` em :198; `remontar` em :205
- `remessa_dia.preparar` cria UM `Candidato` por registro, na ordem dos registros (`remessa_dia.py:886-967`, `linhas.append(candidato)`). É isso que torna o "k-ésimo do id" seguro.

- [ ] **Passo 1: testes que falham**

```python
from pagamentos_dia import leitura_do_dia as ld
from pagamentos_dia import remessa_dia


def test_entradas_nascem_sem_dividir_e_o_remontar_de_sempre_fica():
    entradas = _entradas([_item()], [40000, 60000])
    assert entradas.dividir_boletos is False
    assert [r["status"] for r in _linhas(confirmacao.remontar(entradas))] == [bs.STATUS_VARIOS]


def test_com_a_chave_o_remontar_divide():
    entradas = _entradas([_item()], [40000, 60000], dividir_boletos=True)
    assert [r["parte"] for r in _linhas(confirmacao.remontar(entradas))] == ["1/2", "2/2"]


def test_desmarcar_o_lancamento_tira_as_n_linhas():
    entradas = _entradas([_item()], [40000, 60000], dividir_boletos=True)
    res = confirmacao.remontar(entradas, {"L1"})
    assert _linhas(res) == [] and [o["id"] for o in res.omitidos] == ["L1"]


def _cand(ident):
    return remessa_dia.Candidato(id=ident, conta_erp=CONTA, tipo="Boleto", valor=1.0,
                                 favorecido="F", descricao="D", status="APTO")


def test_candidato_sem_parte_e_o_primeiro_de_sempre():
    a, b, c = _cand("1"), _cand("2"), _cand("2")
    analise = confirmacao.AnaliseRemessa(preparado={CONTA: [a, b, c]})
    assert analise.candidato(CONTA, "2") is b
    assert analise.candidato(CONTA, "2", 1) is c
    assert analise.candidato(CONTA, "2", 2) is None


class _ApiDoDia:
    """O mínimo que `ler_pagamentos` chama (formato de tests/test_leitura_do_dia.py)."""
    _req_anexos = ("https://exemplo.invalid/attachments/v2", {"authorization": "x"})
    titulos_sem_leitura = ()

    def __init__(self, itens, anexos, arquivos):
        self._itens, self._anexos, self._arquivos = itens, anexos, arquivos

    def capturar_credenciais(self, log=print):
        return True

    def capturar_credenciais_anexos(self, launch_id):
        return True

    def listar_a_pagar(self, ini, fim, log=print):
        return list(self._itens)

    def anexos_de_titulos(self, ids, log=print, progresso=None, cancelar=None):
        return {i: self._anexos.get(i, []) for i in ids}

    def listar_overviews(self, ids, log=print, progresso=None, cancelar=None):
        return {i: {} for i in ids}

    def listar_participantes(self, log=print):
        return {}

    def baixar_anexo(self, url):
        return self._arquivos[url]


def _sem(*_a):
    raise RuntimeError("sem nuvem/cadastro no teste")


def _ler_o_dia(valores):
    linhas = _linhas_dos_boletos(valores)
    anexos = {"T1": [_anexo(f"boleto {i}", f"u{i}") for i in range(1, len(linhas) + 1)]}
    arquivos = {f"u{i}": f"Banco Exemplo\n{ln}\n".encode("utf-8")
                for i, ln in enumerate(linhas, 1)}
    leitura = ld.ler_pagamentos(
        _ApiDoDia([_item()], anexos, arquivos), DIA, DIA,
        abrir_historico=_sem, carregar_mapas=_sem, ler_qr=lambda d, pdf: [],
        texto_pdf=lambda d: d.decode("utf-8"), ocr_pdf=lambda d, log=print: "",
        ocr_imagem=lambda d: "")
    return leitura, linhas


def test_a_leitura_do_dia_divide_e_cada_linha_tem_o_seu_candidato():
    leitura, linhas = _ler_o_dia([40000, 60000])
    assert leitura.entradas.dividir_boletos is True
    entram = [ln for g in leitura.grupos for ln in g.entram]
    assert sorted(ln.valor for ln in entram) == [400.0, 600.0]
    assert {ln.candidato.codigo_barras for ln in entram} == {
        ocr_boleto.codigo_de_barras(x) for x in linhas}
    assert all(bs.status_dividido(2) in ln.situacao for ln in entram)
    assert any("1 lançamento virou 2 boletos" in a for a in leitura.avisos)


def test_o_que_a_remessa_recebe_da_tela_nova_tem_as_n_linhas():
    """`PagamentosDiaFrame.receber_apuracao` chama `remontar(leitura.entradas, …)`."""
    leitura, _ = _ler_o_dia([40000, 60000])
    assert len(_linhas(confirmacao.remontar(leitura.entradas, set()))) == 2


def test_so_a_leitura_do_dia_liga_a_divisao():
    arvore = ast.parse((RAIZ / "pagamentos_dia/leitura_do_dia.py").read_text(encoding="utf-8"))
    (kw,) = [kw for no in ast.walk(arvore) if isinstance(no, ast.Call)
             for kw in no.keywords if kw.arg == "dividir_boletos"]
    assert isinstance(kw.value, ast.Constant) and kw.value.value is True
```

- [ ] **Passo 2:** `python -m pytest tests/test_boletos_somados.py -q`. Esperado: FAIL (`TypeError: ... unexpected keyword argument 'dividir_boletos'` / `candidato() takes 3 positional arguments`).
- [ ] **Passo 3: implementar**

`pagamentos_dia/confirmacao.py`:
```python
# imports (depois da :38)
from . import boletos_somados

# Entradas, depois de `qr_pix` (:75)
    #: Só a aba "Pagamentos do dia" liga (`leitura_do_dia`): o lançamento
    #: cujos boletos somam EXATAMENTE o valor vira N linhas
    #: (`boletos_somados`). A Remessa/Retorno monta as dela sem isto, e nada
    #: muda para ela — nem quando recebe a apuração da tela nova, que já
    #: chega dividida porque a chave viaja com as Entradas.
    dividir_boletos: bool = False

# remontar (:121): guardar o retorno e
    resultado = relatorio.montar_registros(...)   # a chamada de hoje, sem mudar
    if entradas.dividir_boletos:
        resultado = boletos_somados.dividir(resultado, entradas)
    return resultado

# AnaliseRemessa.candidato (:212)
    def candidato(self, conta: str, ident: str, parte: int = 0):
        """O `Candidato` do lançamento, ou None. Pelo id, e não pela posição na
        conta. `parte`: o lançamento dividido em N boletos tem N linhas com o
        MESMO id, e o `preparar` faz um Candidato por linha, na ordem delas —
        a k-ésima linha do id é o k-ésimo Candidato do id. Sem divisão,
        `parte` é sempre 0: o de sempre."""
        ident = str(ident or "")
        if not ident:
            return None
        mesmos = [c for c in self.preparado.get(conta, ()) if c.id == ident]
        return mesmos[parte] if parte < len(mesmos) else None

# grupos_da_confirmacao (:795-800)
    for conta, registros in (resultado.contas or {}).items():
        vistos: dict[str, int] = {}
        for reg in registros:
            ident = str(reg.get("id") or "")
            # Conta TODA linha (até a já paga, que o `preparar` também vira
            # Candidato), para a k-ésima linha do id achar o k-ésimo Candidato.
            parte = vistos.get(ident, 0)
            vistos[ident] = parte + 1
            if _ja_pago(reg, por_id.get(ident) or {}):
                continue
            candidato = analise.candidato(conta, ident, parte) if analise else None
            ...  # o resto igual
```

`pagamentos_dia/leitura_do_dia.py`:
```python
from . import boletos_somados, confirmacao, ocr_boleto, qr_pix, relatorio   # :32
...
        titulos_nao_lidos=set(getattr(api, "titulos_sem_leitura", ()) or ()),
        # A tela nova divide o lançamento cujos boletos somam exato
        # (`boletos_somados`); a Remessa/Retorno, lendo sozinha, não.
        dividir_boletos=True)
    leitura.entradas = entradas
    leitura.resultado = confirmacao.remontar(entradas)
    leitura.avisos.extend(boletos_somados.avisos(leitura.resultado))
```

- [ ] **Passo 4:** `python -m pytest tests/test_boletos_somados.py tests/test_confirmacao.py tests/test_leitura_do_dia.py tests/test_listas_de_conferencia.py tests/test_tela_do_dia*.py -q`. Esperado: tudo passa.
- [ ] **Passo 5: commit**
```
git add pagamentos_dia/confirmacao.py pagamentos_dia/leitura_do_dia.py tests/test_boletos_somados.py
git commit -m "Pagamentos do dia: só a tela nova divide os boletos que somam exato; cada linha com o seu candidato" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Tarefa 4: HTML e remessa da tela nova com as N linhas

**Modelo:** sonnet

**Files:** Modify `pagamentos_dia/html_pagamentos.py`, `tests/test_boletos_somados.py`

**Interfaces (reais):**
- `html_pagamentos.contas_do_html_geral(resultado) -> list[dict]` (:521; `"id": id_` em :537; `URL_LANCAMENTO`)
- `html_pagamentos.descricao_para_colar(registro, conta, limite=None)` (:296)
- `remessa_dia.preparar(contas, participantes=None, quando=None, historico=None) -> dict` (:832)
- `remessa_dia.referencias(candidatos) -> dict` (:1204)
- `modelos_html.py:214`: `rowKey(c, e, idx)` usa `e.id`
- `agendamentos_sicoob.chave_da_linha` (:715) inclui `h["id"]`

- [ ] **Passo 1: testes que falham**

```python
from pagamentos_dia import html_pagamentos as hp


def test_html_separa_as_partes_pelo_id_e_mantem_o_link_do_lancamento():
    _base, res = _dividido([40000, 60000])
    entradas = [e for c in hp.contas_do_html_geral(res) for e in c["entries"]]
    assert [e["id"] for e in entradas] == ["L1#1/2", "L1#2/2"]          # "já paguei" separado
    assert {e["link"] for e in entradas} == {hp.URL_LANCAMENTO + "L1"}
    assert not any("mesma linha digitável" in e["bloqueio"] for e in entradas)
    assert all(e["bloqueio"] for e in entradas)                          # ATENÇÃO: conferir


def test_html_de_linha_sem_parte_continua_com_o_id_do_lancamento():
    base, _res = _dividido([40000, 60000])
    assert [e["id"] for c in hp.contas_do_html_geral(base) for e in c["entries"]] == ["L1"]


def test_remessa_da_tela_nova_leva_as_n_linhas_com_seus_numeros_proprios():
    _base, res = _dividido([40000, 60000])
    cands = remessa_dia.preparar(res.contas, {}, quando=DIA)[CONTA]
    assert len(cands) == 2 and len({c.seu_numero for c in cands}) == 2
    assert len({c.codigo_barras for c in cands}) == 2
    assert all(c.id == "L1" and c.pode and not c.marcado for c in cands)   # nasce desmarcada
    assert sorted(c.valor for c in cands) == [400.0, 600.0]
    for c in cands:
        c.marcado = True
    assert set(remessa_dia.referencias(cands).values()) == {"L1"}


def test_descricao_de_colar_e_a_mesma_nas_partes():
    _base, res = _dividido([40000, 60000])
    a, b = _linhas(res)
    assert hp.descricao_para_colar(a, CONTA) == hp.descricao_para_colar(b, CONTA)
    assert "OBRA MODELO" in hp.descricao_para_colar(a, CONTA)
```

- [ ] **Passo 2:** `python -m pytest tests/test_boletos_somados.py -q`. Esperado: FAIL só no 1º (`['L1', 'L1'] != ['L1#1/2', 'L1#2/2']`).
- [ ] **Passo 3: implementar** (`html_pagamentos.py:535-537`)

```python
            id_ = str(r.get("id") or "")
            parte = str(r.get("parte") or "")
            entradas.append({
                # A linha de um lançamento dividido em N boletos
                # (`boletos_somados`) leva a parte no id: é ele a chave do
                # "já paguei" do HTML (`rowKey`) e da marca "Conferido"
                # (`agendamentos_sicoob.chave_da_linha`). O link continua
                # sendo o do lançamento. Sem `parte`, o id de sempre.
                "id": f"{id_}#{parte}" if id_ and parte else id_,
                # Sem id não há para onde ir: link vazio, sem botão na tela.
                "link": URL_LANCAMENTO + id_ if id_ else "",
```

- [ ] **Passo 4:** `python -m pytest tests/test_boletos_somados.py tests/test_html_pagamentos.py tests/test_descricao_e_ordem.py tests/test_remessa_dia.py -q`. Esperado: tudo passa.
- [ ] **Passo 5: commit**
```
git add pagamentos_dia/html_pagamentos.py tests/test_boletos_somados.py
git commit -m "HTML dos pagamentos: as partes de um lançamento dividido têm id próprio" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Tarefa 5: `anexar/matcher_somado.py`, N PDFs que somam exatamente um pagamento

**Modelo:** opus

**Files:** Create `anexar/matcher_somado.py`, `tests/test_matcher_somado.py`

**Interfaces (reais):**
- `matcher.casar(pendentes, pdfs) -> (certezas, duvidas, sem_par)` (`anexar/matcher.py:305`). Põe `status` e `motivo_sem_par` ("nenhum PDF com esse valor na pasta", :499) e `used_by` nos PDFs.
- `matcher._features(pe, pd) -> (ocnf, cc, date, docnum)` (:217)
- `matcher.mesma_conta(a, b) -> bool | None` (:242)
- `matcher._vals(pe) -> set` (:288)
- `matcher.parse_pdf(fn) -> dict | None` (:145; `valor` em centavos, `ndesc`, `data`, `fn`, `used_by`)
- Pendente no formato de `mc_api.montar_pagos` (`mc_api.py:~1221`: `paidId`, `launchId`, `valor`, `valores`, `data`, `doc`, `works`, `desc`, `conta`, `favorecido`, `dataFull`).

**Saída:**
```python
MOTIVO_NENHUM_PDF: str ; STATUS_SOMA = "SOMA" ; MAX_PDFS_POR_SOMA = 4 ; MAX_CANDIDATOS = 12
def casar_somados(pendentes, pdfs, *, todos, max_pdfs=4, max_candidatos=12) -> tuple[list, list]
```

- [ ] **Passo 1: testes que falham**

```python
# -*- coding: utf-8 -*-
"""N comprovantes que somam um pagamento (aba "Anexar (novo)"). Puro; dados fictícios."""
from anexar import matcher
from anexar import matcher_somado as ms

A400 = "400,00 - OBRA MODELO OC 5555 - 22-10.pdf"
A600 = "600,00 - OBRA MODELO OC 5555 - 22-10.pdf"


def _pend(paid_id="P1", valor=100000, desc="COMPRA OC 5555", works=("OBRA MODELO",),
          data="2210", doc=""):
    return {"paidId": paid_id, "launchId": "L-" + paid_id, "valor": valor,
            "valores": [valor], "doc": doc, "desc": desc, "works": list(works),
            "data": data, "conta": "CONTA EXEMPLO - SICOOB",
            "favorecido": "Fornecedor Modelo Ltda", "dataFull": "22/10/2026",
            "categoria": ""}


def _rodar(pendentes, nomes, todos=None, preparar=None):
    pdfs = [matcher.parse_pdf(n) for n in nomes]
    if preparar:
        preparar(pendentes, pdfs)
    matcher.casar(pendentes, pdfs)
    return ms.casar_somados(pendentes, pdfs, todos=todos if todos is not None else pendentes), pdfs


def test_o_motivo_do_sem_par_e_o_do_matcher():
    pe = _pend()
    matcher.casar([pe], [])
    assert pe["motivo_sem_par"] == ms.MOTIVO_NENHUM_PDF


def test_dois_comprovantes_que_somam_exato_casam():
    pe = _pend()
    (somados, duvidas), pdfs = _rodar([pe], [A400, A600])
    assert somados == [pe] and duvidas == []
    assert pe["status"] == ms.STATUS_SOMA
    assert pe["pdfs"] == [A600, A400]
    assert pe["motivo"] == "soma exata de 2 comprovantes (OC/NF + centro de custo + data)"
    assert all(pd["used_by"] == "P1" for pd in pdfs)


def test_dois_conjuntos_possiveis_viram_duvida_e_nada_e_usado():
    pe = _pend()
    nomes = [A400, A600, "300,00 - OBRA MODELO OC 5555 - 22-10.pdf",
             "700,00 - OBRA MODELO OC 5555 - 22-10.pdf"]
    (somados, duvidas), pdfs = _rodar([pe], nomes)
    assert somados == [] and duvidas == [pe]
    assert "2 conjuntos" in pe["motivo_sem_par"]
    assert all(pd["used_by"] is None for pd in pdfs)


def test_soma_que_nao_bate_ao_centavo_nao_casa():
    pe = _pend()
    (somados, duvidas), _ = _rodar([pe], [A400, "599,99 - OBRA MODELO OC 5555 - 22-10.pdf"])
    assert somados == duvidas == [] and pe["status"] == "SEM PAR"


def test_comprovante_de_outra_data_nao_entra():
    pe = _pend()
    (somados, _d), _ = _rodar([pe], [A400, "600,00 - OBRA MODELO OC 5555 - 21-10.pdf"])
    assert somados == []


def test_comprovante_que_nao_aponta_o_pagamento_nao_entra():
    pe = _pend()
    (somados, _d), _ = _rodar([pe], [A400, "600,00 - OUTRA COISA - 22-10.pdf"])
    assert somados == []


def test_valor_de_outro_pago_do_periodo_nao_entra_na_soma():
    pe, outro = _pend(), _pend(paid_id="P2", valor=40000, desc="X", works=("OUTRA",))
    (somados, _d), _ = _rodar([pe], [A400, A600], todos=[pe, outro])
    assert somados == []


def test_pagamento_com_pdf_do_proprio_valor_fica_com_a_regra_de_sempre():
    pe = _pend()
    (somados, _d), _ = _rodar([pe], ["1.000,00 - OBRA MODELO OC 5555 - 22-10.pdf", A400, A600])
    assert pe["status"] == "CERTEZA" and somados == []


def test_comprovante_repetido_nao_soma():
    pe = _pend()
    nomes = ["500,00 - OBRA MODELO OC 5555 - 22-10.pdf",
             "500,00 - OBRA MODELO OC 5555 - 22-10 (2).pdf"]
    (somados, duvidas), _ = _rodar([pe], nomes)
    assert somados == [] and duvidas == [pe] and "repetem" in pe["motivo_sem_par"]


def test_comprovante_que_soma_para_dois_pagamentos_vira_duvida_dos_dois():
    a, b = _pend("PA", 100000), _pend("PB", 90000)
    nomes = [A400, A600, "500,00 - OBRA MODELO OC 5555 - 22-10.pdf"]
    (somados, duvidas), pdfs = _rodar([a, b], nomes)
    assert somados == [] and {p["paidId"] for p in duvidas} == {"PA", "PB"}
    assert all(pd["used_by"] is None for pd in pdfs)


def test_pdf_de_outra_conta_nao_entra():
    def contas(pendentes, pdfs):
        pendentes[0]["origem"] = ("SICOOB", "1")
        pdfs[1]["origem"] = ("INTER", "2")
    pe = _pend()
    (somados, _d), _ = _rodar([pe], [A400, A600], preparar=contas)
    assert somados == []


def test_mais_de_quatro_comprovantes_nao_soma():
    pe = _pend(valor=100000)
    nomes = [f"200,{c:02d} - OBRA MODELO OC 5555 - 22-10.pdf" for c in range(4)] + \
            ["199,94 - OBRA MODELO OC 5555 - 22-10.pdf"]
    (somados, _d), _ = _rodar([pe], nomes)
    assert somados == []                                   # precisaria de 5
```

- [ ] **Passo 2:** `python -m pytest tests/test_matcher_somado.py -q`. Esperado: FAIL (`ModuleNotFoundError: anexar.matcher_somado`).
- [ ] **Passo 3: implementar**

```python
# -*- coding: utf-8 -*-
"""N comprovantes que somam EXATAMENTE um pagamento — só para a aba "Anexar (novo)".

Camada OPCIONAL sobre `matcher.casar`, que continua sendo a régua de um PDF
por pagamento e NÃO muda (lá, somar "afrouxaria a regra" do valor único).
Roda depois dela, só sobre quem ficou SEM PAR por "nenhum PDF com esse valor
na pasta", e só com PDFs que ninguém usou. O caso: o lançamento pago com dois
boletos (entrega 5), cujos comprovantes chegam com a MESMA descrição colada.

Cada PDF do conjunto tem de apontar o pagamento SOZINHO pela régua do matcher:
a MESMA data e OC/NF rotulada ou centro de custo (`matcher._features`), sem
ser de outra conta (`matcher.mesma_conta`). E NUNCA soma quando há dúvida:
- PDF cujo valor é de OUTRO pago do período não entra (pode ser o dele);
- dois conjuntos possíveis → dúvida;
- PDF repetido (mesmo valor, descrição e data) → dúvida (pode ser o mesmo
  comprovante duas vezes);
- PDF que entra na soma de dois pagamentos → dúvida dos dois;
- até `MAX_PDFS_POR_SOMA` PDFs e `MAX_CANDIDATOS` candidatos.
A dúvida daqui NÃO vai para a janela de dúvidas (ela escolhe UM PDF): vai para
o relatório e o Registro, e a pessoa anexa à mão.
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations

from . import matcher

#: O motivo de SEM PAR do `matcher.casar` que abre a porta (guardado por teste).
MOTIVO_NENHUM_PDF = "nenhum PDF com esse valor na pasta"
STATUS_SOMA = "SOMA"
MAX_PDFS_POR_SOMA = 4
MAX_CANDIDATOS = 12
_ORDEM_DOS_SINAIS = ("OC/NF", "centro de custo", "data")


def _identifica(pe, pd) -> list[str]:
    """Os sinais com que o PDF aponta o pagamento sozinho; [] quando não aponta."""
    if matcher.mesma_conta(pe.get("origem"), pd.get("origem")) is False:
        return []
    ocnf, cc, data, _docnum = matcher._features(pe, pd)
    if not data or not (ocnf or cc):
        return []
    return [s for s, ok in zip(_ORDEM_DOS_SINAIS, (ocnf, cc, data)) if ok]


def _valores_dos_outros(pe, todos) -> set:
    return {v for q in todos
            if q is not pe and q.get("paidId") != pe.get("paidId")
            for v in matcher._vals(q)}


def _repetidos(conjunto) -> bool:
    chaves = [(pd["valor"], pd["ndesc"], pd["data"]) for pd in conjunto]
    return len(set(chaves)) < len(chaves)


def _duvida(pe, motivo, duvidas):
    pe["motivo_soma"] = pe["motivo_sem_par"] = motivo
    duvidas.append(pe)


def casar_somados(pendentes, pdfs, *, todos, max_pdfs=MAX_PDFS_POR_SOMA,
                  max_candidatos=MAX_CANDIDATOS) -> tuple[list, list]:
    """(somados, dúvidas). `todos` são TODOS os pagos do período (todas as
    contas): é contra eles que se pergunta "este valor é de outro?".

    No somado: `status = STATUS_SOMA`, `pdfs` (nomes, do maior valor para o
    menor), `motivo`, e `used_by` em cada PDF. Na dúvida: `motivo_soma` (e o
    `motivo_sem_par` do relatório); nenhum PDF é marcado."""
    alvos = [pe for pe in pendentes if pe.get("status") == "SEM PAR"
             and pe.get("motivo_sem_par") == MOTIVO_NENHUM_PDF]
    duvidas, unicos, tocados, sinais = [], [], Counter(), {}
    for pe in alvos:
        outros, proprios = _valores_dos_outros(pe, todos), matcher._vals(pe)
        eleg = []
        for pd in pdfs:
            if (pd.get("used_by") is not None or pd["valor"] in outros
                    or pd["valor"] in proprios):
                continue
            s = _identifica(pe, pd)
            if s:
                eleg.append(pd)
                sinais[(id(pe), id(pd))] = s
        if len(eleg) > max_candidatos:
            tocados.update(id(pd) for pd in eleg)
            _duvida(pe, f"{len(eleg)} comprovantes apontam este pagamento — muitos "
                        "para somar com segurança; anexe à mão", duvidas)
            continue
        achados = [c for n in range(2, min(max_pdfs, len(eleg)) + 1)
                   for c in combinations(eleg, n)
                   if sum(pd["valor"] for pd in c) in proprios]
        tocados.update({id(pd) for c in achados for pd in c})
        if any(_repetidos(c) for c in achados):
            _duvida(pe, "os comprovantes que somam o valor se repetem (mesmo valor, "
                        "descrição e data) — pode ser o mesmo arquivo duas vezes; "
                        "anexe à mão", duvidas)
        elif len(achados) > 1:
            _duvida(pe, f"{len(achados)} conjuntos de comprovantes somam o valor — "
                        "anexe à mão", duvidas)
        elif achados:
            unicos.append((pe, achados[0]))
    somados = []
    for pe, conjunto in unicos:
        if any(tocados[id(pd)] > 1 for pd in conjunto):
            _duvida(pe, "um dos comprovantes também soma o valor de outro "
                        "pagamento — anexe à mão", duvidas)
            continue
        for pd in conjunto:
            pd["used_by"] = pe["paidId"]
        usados = {s for pd in conjunto for s in sinais[(id(pe), id(pd))]}
        pe["status"] = STATUS_SOMA
        pe["pdfs"] = [pd["fn"] for pd in sorted(conjunto, key=lambda p: (-p["valor"], p["fn"]))]
        pe["motivo"] = (f"soma exata de {len(conjunto)} comprovantes ("
                        + " + ".join(s for s in _ORDEM_DOS_SINAIS if s in usados) + ")")
        somados.append(pe)
    return somados, duvidas
```

- [ ] **Passo 4:** `python -m pytest tests/test_matcher_somado.py tests/test_matcher.py -q`. Esperado: tudo passa (o `test_matcher.py` prova que `matcher.py` não mudou).
- [ ] **Passo 5: commit**
```
git add anexar/matcher_somado.py tests/test_matcher_somado.py
git commit -m "Anexar: camada opcional que casa N comprovantes que somam exato um pagamento" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Tarefa 6: `anexar/varios_comprovantes.py`, anexar N arquivos com prova e a fase das somas

**Modelo:** opus

**Files:** Create `anexar/varios_comprovantes.py`, `tests/test_varios_comprovantes.py`

**Interfaces (reais):**
- `mc_api.MCApi.anexar_por_api(self, paid_id, pdf_path, *, tag=..., log=None, dry_run=False) -> str` (`mc_api.py:905`): `"anexado"`, `"ja_anexado"`, `"dry_run"` e `"erro:…"`. A prova dele é por nome OU por tamanho (`_mesmo_arquivo`, :181).
- `MCApi._anexos_brutos(self, paid_id)` (:862): lista ou `{"__erro": …}`
- `mc_api._nomes_do_item(item) -> set[str]` (:150)
- `MCApi.verificar_anexos(self, paid_ids, log=print, progresso=None, cancelar=None) -> dict[str, int]` (:494)
- `mc_api.estado_anexo(att, paid_id)` (:213), `SEM_ANEXO`/`NAO_VERIFICADO` (:102-103), `ANEXADO` (:108)
- `matcher.carregar_pdfs(pasta, log=print)` (:186)
- `util.fmt_val`, `config.MC_URL_LANCAMENTO`
- A tela `mc_client.MCClient.anexar` devolve `"ja_tinha"` quando o sub-pagamento já tem QUALQUER anexo (`mc_client.py:981-983`). Por isso este módulo nunca a usa.

**Saída:**
```python
@dataclass class ResultadoVarios: estado: str; por_arquivo: list ; ok: bool (property)
def anexar_varios(api, paid_id, arquivos, *, dry_run=False, log=None) -> ResultadoVarios
@dataclass class Somas: anexados: list; duvidas: list; nao_verificados: int ; ok: int (property)
def fase_das_somas(api, pagos, pasta, *, simular, carregar_pdfs=matcher.carregar_pdfs, preencher_origem=None, log=print, cancelar=lambda: False) -> Somas
def juntar_fim(fim1: tuple, somas: Somas) -> tuple
def resumo_das_somas(somas: Somas) -> list[str]
def acrescentar_ao_relatorio(caminho, somas: Somas) -> None
```

- [ ] **Passo 1: testes que falham**

```python
# -*- coding: utf-8 -*-
"""Anexar N comprovantes num pagamento só (aba "Anexar (novo)"). Sem rede: dublê da API."""
from pathlib import Path

from anexar import matcher, matcher_somado, varios_comprovantes as vc

A400 = "400,00 - OBRA MODELO OC 5555 - 22-10.pdf"
A600 = "600,00 - OBRA MODELO OC 5555 - 22-10.pdf"


class ApiFalsa:
    def __init__(self, respostas=None, some=False, nao_verifica=()):
        self.anexos, self.enviados = {}, []
        self.respostas, self.some, self.nao_verifica = list(respostas or []), some, set(nao_verifica)

    def verificar_anexos(self, ids, log=print, progresso=None, cancelar=None):
        return {i: (-1 if i in self.nao_verifica else len(self.anexos.get(i, []))) for i in ids}

    def _anexos_brutos(self, pid):
        return list(self.anexos.get(pid, []))

    def anexar_por_api(self, pid, caminho, *, log=None, dry_run=False, tag=None):
        caminho = Path(caminho)
        self.enviados.append(caminho.name)
        if dry_run:
            return "dry_run"
        r = self.respostas.pop(0) if self.respostas else "anexado"
        if r == "anexado" and not self.some:
            self.anexos.setdefault(pid, []).append(
                {"name": caminho.name, "sizeInBytes": caminho.stat().st_size})
        return r


def _arquivos(tmp_path, tamanhos=(10, 11)):
    caminhos = []
    for nome, n in zip((A600, A400), tamanhos):
        p = tmp_path / nome
        p.write_bytes(b"x" * n)
        caminhos.append(p)
    return caminhos


def test_anexa_os_dois_e_prova_pelo_nome(tmp_path):
    api = ApiFalsa()
    r = vc.anexar_varios(api, "P1", _arquivos(tmp_path))
    assert r.estado == "anexado" and r.ok and api.enviados == [A600, A400]


def test_tamanhos_iguais_nao_sobem_nada(tmp_path):
    api = ApiFalsa()
    r = vc.anexar_varios(api, "P1", _arquivos(tmp_path, (10, 10)))
    assert r.estado == "erro:tamanhos_iguais" and api.enviados == []


def test_pagamento_que_ja_tem_anexo_nao_recebe_mais(tmp_path):
    api = ApiFalsa()
    api.anexos["P1"] = [{"name": "outro.pdf", "sizeInBytes": 5}]
    r = vc.anexar_varios(api, "P1", _arquivos(tmp_path))
    assert r.estado == "erro:ja_tem_anexo" and api.enviados == []


def test_erro_no_segundo_para_sem_tentar_de_novo(tmp_path):
    api = ApiFalsa(respostas=["anexado", "erro:upload:500"])
    r = vc.anexar_varios(api, "P1", _arquivos(tmp_path))
    assert r.estado.startswith("erro:parcial:") and not r.ok
    assert api.enviados == [A600, A400]                   # nenhum POST repetido


def test_sem_a_prova_pelo_nome_nao_e_anexado(tmp_path):
    api = ApiFalsa(some=True)
    r = vc.anexar_varios(api, "P1", _arquivos(tmp_path))
    assert r.estado == "erro:nao_confirmado:0/2"


def test_simular_nao_sobe(tmp_path):
    api = ApiFalsa()
    r = vc.anexar_varios(api, "P1", _arquivos(tmp_path), dry_run=True)
    assert r.estado == "dry_run" and api.anexos == {}


def test_nunca_passa_pela_tela():
    texto = Path(vc.__file__).read_text(encoding="utf-8")
    assert "anexar_um" not in texto and ".anexar(" not in texto


def _pend(paid_id="P1", valor=100000):
    return {"paidId": paid_id, "launchId": "L-" + paid_id, "valor": valor, "valores": [valor],
            "doc": "", "desc": "COMPRA OC 5555", "works": ["OBRA MODELO"], "data": "2210",
            "conta": "CONTA EXEMPLO - SICOOB", "favorecido": "Fornecedor Modelo Ltda",
            "dataFull": "22/10/2026", "categoria": ""}


def _fase(tmp_path, api, pagos, nomes=(A400, A600)):
    _arquivos(tmp_path)
    return vc.fase_das_somas(api, pagos, tmp_path, simular=False,
                             carregar_pdfs=lambda pasta, log: [matcher.parse_pdf(n) for n in nomes],
                             log=lambda _m: None)


def test_fase_das_somas_anexa_quem_ficou_sem_par(tmp_path):
    pe = _pend()
    matcher.casar([pe], [])
    somas = _fase(tmp_path, ApiFalsa(), [pe])
    assert [p["paidId"] for p in somas.anexados] == ["P1"] and somas.ok == 1
    assert pe["resultado"] == "anexado" and pe["pdf"] == f"{A600} + {A400}"


def test_fase_das_somas_ignora_nao_verificado(tmp_path):
    pe = _pend()
    matcher.casar([pe], [])
    api = ApiFalsa(nao_verifica={"P1"})
    somas = _fase(tmp_path, api, [pe])
    assert somas.anexados == [] and somas.nao_verificados == 1 and api.enviados == []


def test_fase_das_somas_nao_reusa_pdf_da_fase_1(tmp_path):
    pe, outro = _pend(), _pend("P2", 70000)
    matcher.casar([pe], [])
    outro.update(status="CERTEZA", pdf=A400)
    somas = _fase(tmp_path, ApiFalsa(), [pe, outro])
    assert somas.anexados == []


def test_juntar_fim_soma_as_duas_fases():
    somas = vc.Somas(anexados=[{"resultado": "anexado"}], duvidas=[{}])
    assert vc.juntar_fim((3, 4, 1, 5, "r.xlsx"), somas) == (4, 5, 2, 3, "r.xlsx")


def test_relatorio_ganha_as_abas_das_somas(tmp_path):
    from openpyxl import Workbook, load_workbook
    caminho = tmp_path / "relatorio.xlsx"
    Workbook().save(caminho)
    pe = dict(_pend(), pdfs=[A600, A400], motivo="soma exata", resultado="anexado")
    vc.acrescentar_ao_relatorio(str(caminho), vc.Somas(anexados=[pe]))
    assert "ANEXADOS POR SOMA" in load_workbook(caminho).sheetnames
```

- [ ] **Passo 2:** `python -m pytest tests/test_varios_comprovantes.py -q`. Esperado: FAIL (`ModuleNotFoundError`).
- [ ] **Passo 3: implementar**

```python
# -*- coding: utf-8 -*-
"""Anexar N comprovantes num pagamento só — a fase das somas da aba "Anexar (novo)".

Sem tela e sem navegador: a `api` (a `mc_api.MCApi` da sessão) entra por
parâmetro. Quem chama roda na thread do navegador (`AnexarFrame.submeter`).

Por que NÃO usa `anexar_comprovantes.anexar_um` (revisão de dinheiro):
- a tela, plano B dele, devolve "ja_tinha" assim que o sub-pagamento tem
  QUALQUER anexo (`mc_client.MCClient.anexar`): o 2º comprovante sairia "ok"
  sem subir;
- `mc_api.anexar_por_api` dá "ja_anexado" e prova a subida também pelo
  TAMANHO (`mc_api._mesmo_arquivo`): dois comprovantes de mesmo tamanho fariam
  o 2º "já estar lá".
Por isso: só API; tamanhos distintos; pagamento SEM anexo antes; para no
primeiro erro (POST nunca se repete); prova final pelo NOME de cada arquivo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import util

from . import config, matcher, matcher_somado, mc_api

_OK = (mc_api.ANEXADO, "dry_run")


@dataclass
class ResultadoVarios:
    estado: str
    por_arquivo: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.estado in _OK


def _listagem(api, paid_id):
    try:
        lista = api._anexos_brutos(paid_id)
    except Exception as e:                                   # noqa: BLE001
        return None, f"erro:listagem:{e.__class__.__name__}"
    if not isinstance(lista, list):
        motivo = lista.get("__erro") if isinstance(lista, dict) else type(lista).__name__
        return None, f"erro:listagem:{motivo}"
    return lista, ""


def _provado(lista, arquivo: Path) -> bool:
    nome = arquivo.name.lower()
    return any(isinstance(i, dict) and nome in mc_api._nomes_do_item(i) for i in lista)


def anexar_varios(api, paid_id, arquivos, *, dry_run=False, log=None) -> ResultadoVarios:
    log = log or (lambda _m: None)
    arquivos = [Path(a) for a in arquivos]
    if not paid_id:
        return ResultadoVarios("erro:sem_paid_id")
    if len(arquivos) < 2:
        return ResultadoVarios("erro:menos_de_dois_arquivos")
    tamanhos = []
    for a in arquivos:
        try:
            tamanhos.append(a.stat().st_size)
        except OSError as e:
            return ResultadoVarios(f"erro:arquivo:{a.name}:{e.__class__.__name__}")
    if len(set(tamanhos)) < len(tamanhos):
        return ResultadoVarios("erro:tamanhos_iguais")
    antes, erro = _listagem(api, paid_id)
    if erro:
        return ResultadoVarios(erro)
    if antes:
        return ResultadoVarios("erro:ja_tem_anexo")
    por_arquivo, n = [], len(arquivos)
    for k, a in enumerate(arquivos, 1):
        r = api.anexar_por_api(paid_id, a, log=log, dry_run=dry_run)
        por_arquivo.append((a.name, r))
        log(f"   {k}/{n} {a.name} -> {r}")
        if r == "dry_run":
            continue
        if r != mc_api.ANEXADO:
            return ResultadoVarios(f"erro:parcial:{k - 1}/{n} subiram, o {k}º deu {r} — "
                                   "confira o lançamento", por_arquivo)
    if dry_run:
        return ResultadoVarios("dry_run", por_arquivo)
    depois, erro = _listagem(api, paid_id)
    if erro:
        return ResultadoVarios(f"erro:nao_confirmado:{erro}", por_arquivo)
    provados = sum(_provado(depois, a) for a in arquivos)
    if provados == n:
        return ResultadoVarios(mc_api.ANEXADO, por_arquivo)
    return ResultadoVarios(f"erro:nao_confirmado:{provados}/{n}", por_arquivo)


@dataclass
class Somas:
    anexados: list = field(default_factory=list)
    duvidas: list = field(default_factory=list)
    nao_verificados: int = 0

    @property
    def ok(self) -> int:
        return sum(1 for pe in self.anexados if pe.get("resultado") in _OK)


def fase_das_somas(api, pagos, pasta, *, simular, carregar_pdfs=matcher.carregar_pdfs,
                   preencher_origem=None, log=print, cancelar=lambda: False) -> Somas:
    """Depois da fase 1 (o `_t_auto` de sempre): quem ficou SEM PAR por falta de
    PDF do valor é conferido DE NOVO no ERP (só `SEM_ANEXO` segue) e casado
    com N PDFs livres pelo `matcher_somado`. `pagos` são TODOS os do período."""
    somas = Somas()
    sem_par = [p for p in pagos if p.get("status") == "SEM PAR"
               and p.get("motivo_sem_par") == matcher_somado.MOTIVO_NENHUM_PDF]
    if not sem_par or cancelar():
        return somas
    att = api.verificar_anexos([p["paidId"] for p in sem_par], log, cancelar=cancelar)
    if cancelar():
        return somas
    estados = {p["paidId"]: mc_api.estado_anexo(att, p["paidId"]) for p in sem_par}
    livres = [p for p in sem_par if estados[p["paidId"]] == mc_api.SEM_ANEXO]
    somas.nao_verificados = sum(1 for e in estados.values() if e == mc_api.NAO_VERIFICADO)
    if not livres:
        return somas
    pasta = Path(pasta)
    usados = {p["pdf"] for p in pagos if p.get("status") == "CERTEZA" and p.get("pdf")}
    pdfs = [pd for pd in carregar_pdfs(pasta, log) if pd["fn"] not in usados]
    if preencher_origem is not None:
        try:
            preencher_origem(livres, pdfs)
        except Exception:                                   # noqa: BLE001
            log("[aviso] não deu para saber a conta de origem — as somas seguem sem essa regra.")
    somados, somas.duvidas = matcher_somado.casar_somados(livres, pdfs, todos=pagos)
    for pe in somados:
        if cancelar():
            break
        r = anexar_varios(api, pe["paidId"], [pasta / fn for fn in pe["pdfs"]],
                          dry_run=simular, log=log)
        pe["resultado"], pe["pdf"] = r.estado, " + ".join(pe["pdfs"])
        somas.anexados.append(pe)
    return somas


def juntar_fim(fim1: tuple, somas: Somas) -> tuple:
    """O ("fim", …) da fase 1 com as somas: anexados entram no total; os que a
    fase 2 tocou saem do "sem par" (dúvida de soma vira dúvida)."""
    ok, tot, duv, sp, saida = fim1
    n, d = len(somas.anexados), len(somas.duvidas)
    return (ok + somas.ok, tot + n, duv + d, max(sp - n - d, 0), saida)


def resumo_das_somas(somas: Somas) -> list[str]:
    linhas = [f"Somas: {len(somas.anexados)} pagamento(s) com N comprovantes "
              f"({somas.ok} ok) · {len(somas.duvidas)} em dúvida"
              + (f" · {somas.nao_verificados} não verificado(s), ficam para a mão"
                 if somas.nao_verificados else "")]
    linhas += [f"  {util.fmt_val(p['valor'])} = {p['pdf']} -> {p['resultado']}"
               for p in somas.anexados]
    linhas += [f"  {util.fmt_val(p['valor'])} DÚVIDA: {p.get('motivo_soma', '')}"
               for p in somas.duvidas]
    return linhas


_CABECALHO = ["Valor", "Data", "Favorecido", "Centro de custo", "Conta", "Descrição",
              "Nº doc", "PDFs", "Motivo", "Resultado", "Link"]


def acrescentar_ao_relatorio(caminho, somas: Somas) -> None:
    """Duas abas no Excel que a fase 1 gravou: ANEXADOS POR SOMA e SOMA EM DUVIDA."""
    if not caminho or not (somas.anexados or somas.duvidas):
        return
    from openpyxl import load_workbook              # só quem gera paga o openpyxl
    wb = load_workbook(caminho)

    def comuns(p):
        return [util.fmt_val(p["valor"]), p.get("dataFull", ""), p.get("favorecido", ""),
                "; ".join(p.get("works") or []), p.get("conta", ""), p.get("desc", ""),
                p.get("doc", "")]

    for nome, linhas in (
            ("ANEXADOS POR SOMA", [comuns(p) + [" + ".join(p.get("pdfs") or []),
                                                p.get("motivo", ""), p.get("resultado", ""),
                                                config.MC_URL_LANCAMENTO + str(p["launchId"])]
                                   for p in somas.anexados]),
            ("SOMA EM DUVIDA", [comuns(p) + ["", p.get("motivo_soma", ""), "",
                                             config.MC_URL_LANCAMENTO + str(p["launchId"])]
                                for p in somas.duvidas])):
        ws = wb.create_sheet(nome)
        ws.append(_CABECALHO)
        for linha in linhas:
            ws.append(linha)
        ws.freeze_panes = "A2"
    wb.save(caminho)
```

- [ ] **Passo 4:** `python -m pytest tests/test_varios_comprovantes.py tests/test_anexar_por_api.py -q`. Esperado: tudo passa.
- [ ] **Passo 5: commit**
```
git add anexar/varios_comprovantes.py tests/test_varios_comprovantes.py
git commit -m "Anexar (novo): N comprovantes num pagamento só pela API, com prova pelo nome" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Tarefa 7: `AnexarFrame` ganha três atributos de classe (o comportamento não muda)

**Modelo:** sonnet

**Files:** Modify `anexar/anexar_comprovantes.py`; Create `tests/test_anexar_novo.py` (parte 1)

**Interfaces (reais):** `class AnexarFrame(ttk.Frame)` (:251), `_QUALQUER = object()` (:255), `self.exec = ThreadPoolExecutor(max_workers=1)` (:263), `self.after(150, self._drain)` (:299), `self.after(1200, self._pulsar_navegador)` (:300), `widgets.Cabecalho(self, "Anexar Comprovantes", "...", trilha="Comprovantes  ›  Anexar")` (:307-311).

- [ ] **Passo 1: testes que falham**

```python
# -*- coding: utf-8 -*-
"""Aba "Anexar (novo)": a Anexar de sempre + somas, sem um segundo navegador.

Testes puros: sem janela Tk. O `__init__` roda com ttk/StringVar trocados por
dublês, como `tests/test_abas_em_paralelo.py` faz com `__new__`."""
import threading

import pytest


@pytest.fixture
def modulo():
    pytest.importorskip("playwright")
    from anexar import anexar_comprovantes as modulo
    return modulo


class _Var:
    def __init__(self, master=None, value=None, **_k):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


def _sem_tk(*_a, **_k):
    raise RuntimeError("sem Tk no teste")


def _construir(modulo, monkeypatch, classe, *args):
    import tkinter as tk
    from tkinter import ttk
    ch = {"executor": 0, "after": []}

    def executor(*_a, **_k):
        ch["executor"] += 1
        return object()

    monkeypatch.setattr(ttk.Frame, "__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(tk, "StringVar", _Var)
    monkeypatch.setattr(tk, "BooleanVar", _Var)
    monkeypatch.setattr(ttk, "Style", _sem_tk)
    monkeypatch.setattr(modulo.AnexarFrame, "_build", lambda self: None)
    monkeypatch.setattr(modulo.AnexarFrame, "after",
                        lambda self, ms, fn=None, *a: ch["after"].append(fn.__name__))
    monkeypatch.setattr(modulo, "ThreadPoolExecutor", executor)
    return classe(None, *args), ch


def test_a_anexar_de_sempre_continua_dona_do_navegador(modulo, monkeypatch):
    assert modulo.AnexarFrame.DONO_DO_NAVEGADOR is True
    assert modulo.AnexarFrame.TITULO == "Anexar Comprovantes"
    assert modulo.AnexarFrame.TRILHA == "Comprovantes  ›  Anexar"
    f, ch = _construir(modulo, monkeypatch, modulo.AnexarFrame)
    assert ch["executor"] == 1 and f.exec is not None
    assert ch["after"] == ["_drain", "_pulsar_navegador"]
```

- [ ] **Passo 2:** `python -m pytest tests/test_anexar_novo.py -q`. Esperado: FAIL (`AttributeError: ... has no attribute 'DONO_DO_NAVEGADOR'`).
- [ ] **Passo 3: implementar** (só isto no arquivo)

```python
    #: Marca de "qualquer aba" para `ocupado`/`dona_ocupada` sem argumento.
    _QUALQUER = object()
    #: O cabeçalho da tela. A aba "Anexar (novo)" (`anexar_novo`) troca só isto.
    TITULO = "Anexar Comprovantes"
    TRILHA = "Comprovantes  ›  Anexar"
    #: Esta aba é a DONA do navegador do ERP: cria o executor e pulsa o Chrome.
    #: A cópia "Anexar (novo)" é False — usa o navegador desta, como as outras
    #: seis abas, e não cria executor nem pulso.
    DONO_DO_NAVEGADOR = True
...
        self.exec = (ThreadPoolExecutor(max_workers=1)        # :263
                     if self.DONO_DO_NAVEGADOR else None)
...
        self.after(150, self._drain)                          # :299
        if self.DONO_DO_NAVEGADOR:                            # :300
            self.after(1200, self._pulsar_navegador)
...
        self.cab = widgets.Cabecalho(                         # :307-311
            self, self.TITULO,
            "Busca os pagos do período, descobre quem está sem comprovante "
            "e anexa o PDF certo em cada um.",
            trilha=self.TRILHA)
```

- [ ] **Passo 4:** `python -m pytest tests/test_anexar_novo.py tests/test_abas_em_paralelo.py tests/test_aba_da_pessoa.py tests/test_duvidas_anexar.py tests/test_codigo_barras.py -q`. Esperado: tudo passa.
- [ ] **Passo 5: commit**
```
git add anexar/anexar_comprovantes.py tests/test_anexar_novo.py
git commit -m "Anexar: título e posse do navegador viram atributos de classe (sem mudar a aba)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Tarefa 8: `anexar/anexar_novo.py`, a aba cópia (fase 1 de sempre + fase das somas)

**Modelo:** opus

**Files:** Create `anexar/anexar_novo.py`; Modify `tests/test_anexar_novo.py`, `tests/test_abas_em_paralelo.py` (`_CHAMADORES`)

**Interfaces (reais):**
- `AnexarFrame.submeter(self, rotulo, fn, *a, dona=None, **k)` (:479)
- `ocupado(self, aba=_QUALQUER)` (:607), `dona_ocupada(self, aba=_QUALQUER)` (:620), `avisar_se_ocupado(self, dona, *, aba=None)` (:631)
- `abrir_minha_aba(self)` (:656), `garantir_sessao(self, log=None)` (:766)
- `mc`/`api` são propriedades (:571-596). `_pulsar_navegador` (:733). `fechar(self)` (:1718)
- `_t_auto(self, contas_sel, termos, pasta_pdfs, simular)` (:1416). Põe `("fim", (ok, tot, duv, sp, saida))` em `self.q` (:1534); em erro, `("reabilitar2", None)`.
- `_log(self, msg)` (:468), `_checar_pausa` (:935), `_texto_do_erro` (:100)
- `origem.preencher(pendentes, pdfs, pasta, *, mapa_mc=None, empresas=None, contas_inter=None, documentos=None)` (`origem.py:162`)

- [ ] **Passo 1: testes que falham** (acrescentar)

```python
from queue import Queue  # noqa: F401  (o tipo do q de sempre)


@pytest.fixture
def novo(modulo):
    from anexar import anexar_novo
    return anexar_novo


class _Dono:
    def __init__(self):
        self.chamadas, self.mc, self.api = [], "mc-do-dono", "api-do-dono"

    def submeter(self, rotulo, fn, *a, dona=None, **k):
        self.chamadas.append(("submeter", rotulo, dona))
        return "fut"

    def avisar_se_ocupado(self, texto, *, aba=None):
        self.chamadas.append(("avisar", aba))
        return False

    def ocupado(self, aba=None):
        self.chamadas.append(("ocupado", aba))

    def dona_ocupada(self, aba=None):
        return None

    def garantir_sessao(self, log=None):
        self.chamadas.append(("sessao", log))
        return self.api

    def abrir_minha_aba(self):
        self.chamadas.append(("minha aba",))

    def fechar(self):
        self.chamadas.append(("fechar",))


def _nova(novo, dono):
    f = novo.AnexarNovoFrame.__new__(novo.AnexarNovoFrame)
    f.anx, f.q, f.pagos = dono, novo._FilaComDesvio(), []
    f._parar, f._pausa, f._esperas = threading.Event(), threading.Event(), set()
    f._encerrando = False
    f.winfo_children = lambda: []
    return f


def test_a_copia_nao_cria_executor_nem_pulso(modulo, novo, monkeypatch):
    dono = _Dono()
    f, ch = _construir(modulo, monkeypatch, novo.AnexarNovoFrame, dono)
    assert novo.AnexarNovoFrame.DONO_DO_NAVEGADOR is False
    assert novo.AnexarNovoFrame.TITULO == "Anexar (novo)"
    assert ch["executor"] == 0 and f.exec is None
    assert ch["after"] == ["_drain"]
    assert f.anx is dono and isinstance(f.q, novo._FilaComDesvio)


def test_todo_trabalho_vai_para_o_dono_com_a_copia_como_dona(novo):
    dono = _Dono()
    f = _nova(novo, dono)
    assert f.submeter("Anexar — casar", print) == "fut"
    f.avisar_se_ocupado("o Anexar (novo)")
    f.ocupado()
    f.abrir_minha_aba()
    assert ("submeter", "Anexar — casar", f) in dono.chamadas
    assert ("avisar", f) in dono.chamadas and ("ocupado", f) in dono.chamadas
    assert f.mc == "mc-do-dono" and f.api == "api-do-dono"
    f.mc = "outro"
    assert dono.mc == "outro"
    assert f.garantir_sessao() == dono.api


def test_fechar_da_copia_solta_quem_espera_e_nao_fecha_o_chrome(novo):
    dono = _Dono()
    f = _nova(novo, dono)
    ev = threading.Event()
    f._esperas.add(ev)
    f.fechar()
    assert ev.is_set() and f._parar.is_set() and ("fechar",) not in dono.chamadas


def test_a_fila_segura_o_fim_so_enquanto_desvia(novo):
    q = novo._FilaComDesvio()
    q.desviar = True
    q.put(("log", "a"))
    q.put(("fim", (1, 1, 0, 0, "")))
    q.desviar = False
    q.put(("fim", (2, 2, 0, 0, "")))
    assert [q.get_nowait() for _ in range(2)] == [("log", "a"), ("fim", (2, 2, 0, 0, ""))]
    assert q.fim_desviado == (1, 1, 0, 0, "")


def _itens(q):
    saida = []
    while not q.empty():
        saida.append(q.get_nowait())
    return saida


def test_casar_e_anexar_roda_a_fase_1_inteira_e_sai_um_fim_somado(modulo, novo, monkeypatch, tmp_path):
    dono = _Dono()
    f = _nova(novo, dono)
    f.pagos = [{"paidId": "P1", "status": "CERTEZA"}]              # sobra de rodada anterior

    def fase1(self, contas_sel, termos, pasta, simular):
        assert "status" not in self.pagos[0]                       # limpo antes da fase 1
        self.pagos[0].update(status="SEM PAR")
        self.q.put(("fim", (0, 0, 0, 1, "")))

    chamadas = []
    monkeypatch.setattr(modulo.AnexarFrame, "_t_auto", fase1)
    monkeypatch.setattr(novo.varios_comprovantes, "fase_das_somas",
                        lambda api, pagos, pasta, **k: chamadas.append(api) or
                        novo.varios_comprovantes.Somas(anexados=[{"resultado": "anexado",
                                                                   "valor": 1, "pdf": "a + b"}]))
    monkeypatch.setattr(novo.varios_comprovantes, "acrescentar_ao_relatorio", lambda *a: None)
    f._t_auto({"C"}, [], str(tmp_path), False)
    fins = [v for k, v in _itens(f.q) if k == "fim"]
    assert fins == [(1, 1, 0, 0, "")] and chamadas == ["api-do-dono"]


def test_fase_1_com_erro_nao_roda_a_fase_2(modulo, novo, monkeypatch, tmp_path):
    f = _nova(novo, _Dono())

    def fase1(self, *a):
        self.q.put(("reabilitar2", None))

    monkeypatch.setattr(modulo.AnexarFrame, "_t_auto", fase1)
    monkeypatch.setattr(novo.varios_comprovantes, "fase_das_somas",
                        lambda *a, **k: pytest.fail("não devia somar"))
    f._t_auto({"C"}, [], str(tmp_path), False)
    assert _itens(f.q) == [("reabilitar2", None)]
```

E em `tests/test_abas_em_paralelo.py`, acrescentar `"anexar/anexar_novo.py",` à tupla `_CHAMADORES`.

- [ ] **Passo 2:** `python -m pytest tests/test_anexar_novo.py tests/test_abas_em_paralelo.py -q`. Esperado: FAIL (`ModuleNotFoundError: anexar.anexar_novo`).
- [ ] **Passo 3: implementar**

```python
# -*- coding: utf-8 -*-
"""Aba "Anexar (novo)": a Anexar de sempre + N comprovantes que somam um pagamento.

Decisão do dono (21/10/2026): a aba Anexar atual NÃO muda e fica como plano B;
esta é a CÓPIA com o casamento novo. Ela tem de fazer tudo o que a atual faz —
inclusive o modo "Por lista" e o casamento de um PDF por pagamento, porque
pagamento de PF é feito pelo celular e não se automatiza.

UM NAVEGADOR SÓ. Esta aba NÃO é dona de navegador (`DONO_DO_NAVEGADOR =
False`): não cria executor, não pulsa e não fecha o Chrome. Todo trabalho vai
para o `AnexarFrame` de sempre (`self.anx.submeter(..., dona=self)`), como a
Conferência, os Aportes e as outras; `mc`/`api` são os dele (no modo central,
os da vaga desta aba, que o dono cria e fecha).

"Casar e anexar" em DUAS fases:
1. `AnexarFrame._t_auto`, INTEIRO e sem cópia — a Anexar de hoje, com a
   janela de dúvidas e o relatório dela;
2. `varios_comprovantes.fase_das_somas` sobre quem ficou SEM PAR.
O ("fim", …) da fase 1 é segurado (`_FilaComDesvio`) e sai UMA vez, somado.
"""
from __future__ import annotations

import queue
import tkinter as tk
from pathlib import Path

from . import origem, varios_comprovantes
from .anexar_comprovantes import AnexarFrame, _texto_do_erro


class _FilaComDesvio(queue.Queue):
    """A fila da interface que, com `desviar`, guarda o ("fim", …) em vez de
    entregá-lo — o "Concluído" só aparece depois da fase das somas."""

    def __init__(self):
        super().__init__()
        self.desviar = False
        self.fim_desviado = None

    def put(self, item, block=True, timeout=None):
        if self.desviar and isinstance(item, tuple) and item and item[0] == "fim":
            self.fim_desviado = item[1]
            return
        super().put(item, block, timeout)


class AnexarNovoFrame(AnexarFrame):
    TITULO = "Anexar (novo)"
    TRILHA = "Comprovantes  ›  Anexar (novo)"
    DONO_DO_NAVEGADOR = False

    def __init__(self, master, dono: AnexarFrame):
        self.anx = dono                  # antes do super: tudo abaixo pode perguntar
        super().__init__(master)
        self.q = _FilaComDesvio()        # antes do 1º `_drain` (150 ms)

    # ------------------------------------------- o navegador é do dono
    @property
    def mc(self):
        return self.anx.mc

    @mc.setter
    def mc(self, valor):
        self.anx.mc = valor

    @property
    def api(self):
        return self.anx.api

    @api.setter
    def api(self, valor):
        self.anx.api = valor

    def submeter(self, rotulo: str, fn, *a, dona=None, **k):
        return self.anx.submeter(rotulo, fn, *a, dona=self, **k)

    def ocupado(self, aba=AnexarFrame._QUALQUER):
        return self.anx.ocupado(aba=self)

    def dona_ocupada(self, aba=AnexarFrame._QUALQUER):
        return self.anx.dona_ocupada(aba=self)

    def avisar_se_ocupado(self, dona: str, *, aba=None) -> bool:
        return self.anx.avisar_se_ocupado(dona, aba=self)

    def abrir_minha_aba(self):
        self.anx.abrir_minha_aba()

    def garantir_sessao(self, log=None):
        return self.anx.garantir_sessao(log or self._log)

    def _pulsar_navegador(self):
        return                           # quem pulsa é o dono

    def fechar(self):
        """Solta quem espera nesta aba (pausa, janela de dúvidas). O Chrome é
        do dono e fecha com ele — o `_sair` chama esta antes da dele."""
        self._encerrando = True
        try:
            self._parar.set()
            self._pausa.clear()
        except Exception:                                   # noqa: BLE001
            pass
        for ev in list(getattr(self, "_esperas", ())):
            try:
                ev.set()
            except Exception:                               # noqa: BLE001
                pass
        for filho in list(self.winfo_children()):
            if isinstance(filho, tk.Toplevel):
                try:
                    filho.grab_release()
                    filho.destroy()
                except Exception:                           # noqa: BLE001
                    pass

    # ------------------------------------------- casar e anexar
    def _t_auto(self, contas_sel: set, termos: list, pasta_pdfs: str, simular: bool):
        # Só o SEM PAR DESTA rodada abre a fase das somas: o `self.pagos`
        # guarda o status da rodada anterior em quem não entrou agora.
        for p in self.pagos:
            p.pop("status", None)
            p.pop("motivo_sem_par", None)
        self.q.fim_desviado, self.q.desviar = None, True
        try:
            super()._t_auto(contas_sel, termos, pasta_pdfs, simular)
        finally:
            self.q.desviar = False
        fim1 = self.q.fim_desviado
        if fim1 is None:
            return                       # a fase 1 parou com erro: "reabilitar2" já passou
        if self._parar.is_set():
            self.q.put(("fim", fim1))
            return
        fim = fim1
        try:
            self._log("\nProcurando comprovantes que SOMAM um pagamento sem par...")
            pasta = Path(pasta_pdfs)
            somas = varios_comprovantes.fase_das_somas(
                self.api, self.pagos, pasta, simular=simular,
                preencher_origem=lambda pend, pdfs: origem.preencher(pend, pdfs, pasta),
                log=self._log, cancelar=self._checar_pausa)
            for linha in varios_comprovantes.resumo_das_somas(somas):
                self._log(linha)
            varios_comprovantes.acrescentar_ao_relatorio(fim1[4], somas)
            fim = varios_comprovantes.juntar_fim(fim1, somas)
        except Exception as e:                              # noqa: BLE001
            self._log(_texto_do_erro(e))
        self.q.put(("fim", fim))
```

- [ ] **Passo 4:** `python -m pytest tests/test_anexar_novo.py tests/test_abas_em_paralelo.py -q`. Esperado: tudo passa (o AST de `_CHAMADORES` vê `aba=self` e `dona=self`).
- [ ] **Passo 5: commit**
```
git add anexar/anexar_novo.py tests/test_anexar_novo.py tests/test_abas_em_paralelo.py
git commit -m "Anexar (novo): aba cópia sem navegador próprio, fase 1 de sempre + fase das somas" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Tarefa 9: Ligar no menu, ao lado da Anexar (e na galeria)

**Modelo:** sonnet

**Files:** Modify `comprovantes_app.py`, `ferramentas/galeria.py`, `tests/test_anexar_novo.py`, `tests/test_usuarios.py`

**Interfaces (reais):**
- `comprovantes_app.py`: `from anexar.anexar_comprovantes import AnexarFrame` (:39); `aba_anx = AnexarFrame(conteudo)` (:309); `quadros = {...}` (:347-351); `if any(_pode(c) for c in ("bxc", "sep", "anx", "conf", "apt")):` (:438); a tupla do menu (:443-449); `_sair` fecha na ordem de `quadros` (:~806); `por_frame` (:631).
- `usuarios.abas_do_papel(papel, todas)` (`nuvem/usuarios.py:~190`, `ABAS_DO_PAPEL` :44).
- `ferramentas/galeria.py`: `_ORDEM` (:188-202), `_montar("anx", …)` (:366).

- [ ] **Passo 1: testes que falham**

Em `tests/test_anexar_novo.py`:
```python
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def test_o_menu_poe_a_copia_logo_depois_da_anexar():
    texto = (RAIZ / "comprovantes_app.py").read_text(encoding="utf-8")
    assert "aba_anx2 = AnexarNovoFrame(conteudo, aba_anx)" in texto
    depois = texto[texto.index('("anx", "📎", "Anexar"),'):].split("\n")[1].strip()
    assert depois == '("anx2", "📎", "Anexar (novo)"),'
    # o `_sair` fecha na ordem de `quadros`: a cópia solta a thread dela
    # ANTES de o dono fechar o Chrome
    assert texto.index('"anx2": aba_anx2') < texto.index('"anx": aba_anx,')
    assert '("bxc", "sep", "anx", "anx2", "conf", "apt")' in texto
```

Em `tests/test_usuarios.py`:
```python
def test_o_aprovador_nao_ve_a_anexar_nova():
    assert usuarios.abas_do_papel("aprovador", ["ini", "anx", "anx2", "pag"]) == ("ini", "pag")
```

- [ ] **Passo 2:** `python -m pytest tests/test_anexar_novo.py tests/test_usuarios.py -q`. Esperado: FAIL só no teste do menu. O do aprovador já passa: a lista branca de `ABAS_DO_PAGEL` cuida disso, e o teste é uma guarda.
- [ ] **Passo 3: implementar**

`comprovantes_app.py`:
```python
from anexar.anexar_comprovantes import AnexarFrame
from anexar.anexar_novo import AnexarNovoFrame
...
    aba_anx = AnexarFrame(conteudo)
    # A cópia da Anexar (entrega 5) — a mesma tela, mais os comprovantes que
    # SOMAM um pagamento. NÃO tem navegador: divide o do Anexar, como a
    # Conferência e as outras (`AnexarNovoFrame.DONO_DO_NAVEGADOR = False`).
    aba_anx2 = AnexarNovoFrame(conteudo, aba_anx)
...
    # "anx2" ANTES de "anx": o `_sair` fecha na ordem deste dicionário, e a
    # cópia precisa soltar a thread que espera na janela de dúvidas antes de
    # o dono fechar o Chrome nela.
    quadros = {"ini": aba_ini, "sep": aba_sep, "anx2": aba_anx2, "anx": aba_anx,
               "conf": aba_conf, ...}            # o resto igual
...
    if any(_pode(c) for c in ("bxc", "sep", "anx", "anx2", "conf", "apt")):
...
                                   ("anx", "📎", "Anexar"),
                                   ("anx2", "📎", "Anexar (novo)"),
                                   ("conf", "✅", "Conferência"),
```

`ferramentas/galeria.py`: em `_ORDEM`, depois de `("anx", "📎", "Anexar", "anexar"),`, acrescente `("anx2", "📎", "Anexar (novo)", "anexar-novo"),`. Dentro de `if aba_anx is not None:`, a primeira linha passa a ser `_montar("anx2", lambda: AnexarNovoFrame(conteudo, aba_anx))`. Acrescente `from anexar.anexar_novo import AnexarNovoFrame` junto do import da :98.

- [ ] **Passo 4:** `python -m pytest tests/test_anexar_novo.py tests/test_usuarios.py tests/test_empacotamento.py tests/test_imports_do_motor.py -q`. Esperado: tudo passa.
- [ ] **Passo 5: commit**
```
git add comprovantes_app.py ferramentas/galeria.py tests/test_anexar_novo.py tests/test_usuarios.py
git commit -m "Menu: aba Anexar (novo) logo depois da Anexar" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Tarefa 10: Documentação e régua completa

**Modelo:** haiku

**Files:** Modify `.claude/rules/arquitetura-anexar.md`, `.claude/rules/arquitetura-pagamentos-dia.md`, `.claude/rules/arquitetura-tela-do-dia.md`, `.claude/rules/arquitetura-interface.md` (:25), `.claude/rules/arquitetura-ferramentas.md` (:16), `CLAUDE.md` (:426)

- [ ] **Passo 1:** Em `arquitetura-anexar.md`, acrescente a seção "Anexar (novo) — entrega 5". Ela resume:
  - a subclasse sem navegador (`DONO_DO_NAVEGADOR`);
  - as duas fases e a `_FilaComDesvio`;
  - as regras do `matcher_somado` (data + OC/NF ou centro de custo por PDF, valor de outro pago fora, repetido/dois conjuntos/disputado → dúvida, 4 PDFs e 12 candidatos);
  - as do `varios_comprovantes` (só API, tamanhos distintos, pagamento vazio, prova pelo nome, por que a tela devolveria "ja_tinha");
  - a dúvida de soma vai ao relatório e não à janela de dúvidas.
- [ ] **Passo 2:** Em `arquitetura-pagamentos-dia.md`, um item `boletos_somados.py`: quando divide, o mesmo id e a mesma descrição, o status ATENÇÃO, o `candidato(parte=)`, o id `#k/N` do HTML e a baixa pelo retorno (N baixas parciais na mesma parcela). Em `arquitetura-tela-do-dia.md`, seção "Leitura": "a tela liga `Entradas.dividir_boletos`; a Remessa, lendo sozinha, não".
- [ ] **Passo 3:** "treze" → "catorze" (interface :25), "13 telas" → "14 telas" (ferramentas :16, `CLAUDE.md` :426).
- [ ] **Passo 4: régua inteira**
```
python -m pytest tests -q
ruff check --select E9,F .
vermin --target=3.11 --violations pagamentos_dia/boletos_somados.py anexar/matcher_somado.py anexar/varios_comprovantes.py anexar/anexar_novo.py
```
Esperado: verde. Testes de tela são pulados sem a liberação do dono.
- [ ] **Passo 5: commit**
```
git add .claude/rules CLAUDE.md
git commit -m "docs: entrega 5 — lançamento com N boletos e a aba Anexar (novo)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Riscos e decisões

1. **O id se repete nas N linhas, de propósito:** o retorno, a baixa e o "já saiu?" voltam ao lançamento por ele. Consequências conservadoras: (a) se só uma parte foi numa remessa, a outra aparece "já saiu" pela referência e nasce desmarcada; (b) desmarcar ou "não sai" tira o lançamento inteiro.
2. **Baixa pelo retorno:** as N partes pagas viram N baixas parciais na mesma parcela, cada uma com o valor do seu item. O `default-paid` não traz campo de valor, e `baixa_erp` não foi mexido. **O revisor deve olhar isso.**
3. **(A) Divide só o conjunto inteiro das linhas válidas**, com 1 parcela aberta e sem pagamento anterior. Linha lida por OCR nunca divide, porque o OCR só aceita linha com o valor do lançamento. Linhas com outro alarme (pagar à mão, documento não bate) não são o status de "vários boletos" e não dividem.
4. **(B) Cada PDF tem de ter a MESMA data do pagamento.** Pagamento com boletos de datas diferentes cai na mão. O valor que coincide com outro pago do período também tira o PDF da soma, e isso também vale "mais mão, nunca anexo errado".
5. **A cópia muda três atributos de classe no `AnexarFrame` e nada do fluxo.** A alternativa sem tocar no arquivo (desligar o executor depois do `super().__init__` e trocar o rótulo procurando o widget) foi rejeitada por ser implícita.
6. **Fase 1 sem cópia:** é o `_t_auto` de sempre, e não há duplicação para divergir. O preço é a `_FilaComDesvio` e a limpeza de `status` no `self.pagos` da cópia, antes da rodada.
7. **A dúvida de soma não entra na janela de dúvidas** (ela escolhe 1 PDF por pagamento). Vai ao relatório ("SOMA EM DUVIDA") e ao Registro, e a pessoa anexa à mão.
8. **O "Concluído" da cópia conta no "Anexados no mês" do Início** (`registrar_atividade("anx", …)` herdado). É a mesma rotina.
9. **Conflito com outras entregas:** `confirmacao.py`, `leitura_do_dia.py` e `html_pagamentos.py` podem ser tocados pela entrega 2. As mudanças daqui são aditivas e localizadas, e `tela_do_dia/` não é tocado.

### Critical Files for Implementation
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2\pagamentos_dia\confirmacao.py
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2\pagamentos_dia\relatorio.py (lido: `_linhas_dos_anexos` :573, status "vários boletos" ~:2063)
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2\anexar\anexar_comprovantes.py
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2\anexar\matcher.py (lido: `casar` :305, `_features` :217)
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2\anexar\mc_api.py (lido: `anexar_por_api` :905, `_mesmo_arquivo` :181, `estado_anexo` :213)
