# Pagamentos do dia — Entrega 1: plano de implementação

> **Para quem vai executar:** use superpowers:subagent-driven-development (ou superpowers:executing-plans) e siga tarefa por tarefa. Cada passo tem caixa de seleção (`- [ ]`) para acompanhar.

**Goal:** Uma aba nova, "Pagamentos do dia", no grupo DIÁRIO. Ela fica ao lado de "Remessa/Retorno" e de "Saldo de pagamentos", que continuam como estão. Cobre os passos 1 a 4 da especificação, sem ler banco nenhum:
- (1) saldos por conta, com o do sistema e o do banco editáveis, o original visível e o ajuste valendo só no dia;
- (2) pagamentos por conta, separando o que vai sair do que está bloqueado, com "a pagar" = o que vai sair;
- (3) aportes: mínimo por conta, sugestão da aba Regras, valor digitado por aportador, conta-mãe primeiro com alerta forte e "Mandar para a aba Aportes";
- (4) Excel do dia (MODELO) preenchido com os números da tela, sem fórmula digitada, e acesso aos geradores da Remessa (planilha, HTML e remessa).

**Architecture:**
- **Pacote novo `tela_do_dia/`.** Módulos puros, testáveis com pytest sem janela: `valores`, `saldos`, `dia_de_trabalho`, `erp_do_dia`, `pagamentos`, `aportes`, `excel_do_dia`, `para_aportes`. Por cima, uma tela fina, `frame.py`.
- **Leitura dos pagamentos.** Mora em `pagamentos_dia/leitura_do_dia.py`, também pura. Ela orquestra as MESMAS regras da Remessa (`relatorio.montar_registros`, `confirmacao.analisar_remessa`, `confirmacao.grupos_da_confirmacao`) sem reescrever nenhuma.
- **Mudanças pequenas em código existente:**
  - `conciliacao/workbook.build` ganha o parâmetro `extras=`;
  - `conciliacao/aportadores.Regra` ganha o campo `linha`;
  - `AportesFrame` ganha `receber_operacoes`;
  - `PagamentosDiaFrame` ganha um único método no fim da classe, `receber_apuracao`. É a única mudança em `pagamentos_frame.py`.
- **Acesso ao ERP: só pelo Chrome do app.**
  - Pagamentos: `anx.garantir_sessao()` e `mc_api`, como a Remessa.
  - Saldos com o central ligado: `SessaoApi.logar`, que devolve `SessaoPelaPagina` (porteiro).
  - Saldos com o central desligado: pela mesma aba do robô, via `mc_api._fetch_json`.
  - Nunca há `POST /users/login` por HTTP.
- **Persistência: JSON local ao lado do Excel do dia** (`DD MM - dia de trabalho.json`), na mesma pasta que o Excel. Não há SQL novo.

**Tech Stack:** Python 3.11 (alvo do exe; `vermin --target=3.11`), tkinter/ttk + `widgets.py`, openpyxl, `decimal.Decimal`, pytest. O ERP passa por Playwright (Chrome do app/central) através de `anexar/mc_api.py` e `erp/`.

**Spec:** especificação v3 aprovada pelo dono em 21/10/2026 (HTML fora do repo, por ter dados reais: `PROPOSTA - 2026-10-21 pagamentos do dia numa tela so.html` na pasta de trabalho). Esta entrega cobre só "A tela única, parte 1".

**Global Constraints:**
- **Repositório público.** Nenhum nome real de pessoa, empresa, fornecedor ou investidor. Nenhum CPF, CNPJ ou número de conta em código, teste, comentário ou documento. Use os fictícios deste plano: "Conta Alfa - Banco", "Mae - Banco", "Socio Ficticio A", "INVESTIDOR X", "33333-3".
- **Dinheiro é sempre `Decimal`.** Float só aparece em dois lugares: na fronteira com o openpyxl (`to_float`/`float(...)`) e no `Linha.valor` que já vem float da Remessa. Esse é convertido na entrada por `valores.de_float`.
- **Nada escreve no ERP nesta entrega.** O único caminho até o ERP é a aba Aportes, depois que o dono confere e clica "Lançar no Mais Controle" lá.
- **Nenhum login HTTP.** Com o central desligado, os saldos saem pela aba do robô. `acessos.json` estragado falha FECHADO, propagando o `ErpErro` de `erp.sessao.central_ligado`.
- **Pasta nova de aba.** Exige linha no `.github/workflows/build.yml` e `"tela_do_dia"` em `_PASTAS` de `tests/test_imports_do_motor.py`. O `motor_minimo.txt` é tocado SEM mudar a versão (tirar ou pôr o fim de linha), conforme `CLAUDE.md` > "Quando só a esteira muda e o mínimo JÁ é a última release". `git add` da pasta nova antes de rodar `tests/test_empacotamento.py`.
- **Nenhum import novo de submódulo da biblioteca padrão.** Só `re`, `os`, `json`, `dataclasses`, `decimal`, `datetime`, `pathlib`, `collections`, `queue`, `threading`, `time`, `subprocess`, `tkinter.ttk`/`messagebox`, todos já usados pelo app.
- **Testes de tela (janela Tk) não entram.** A máquina do dono não os roda sem liberação. Toda regra fica em módulo puro. A tela só tem a guarda por AST de `tests/test_abas_em_paralelo.py`.
- **Antes do PR:** `python -m ruff check --select E9,F .`, `python -m vermin --target=3.11 --violations tela_do_dia pagamentos_dia/leitura_do_dia.py` e `python -m pytest tests -q`.
- **Fim de mensagem de commit:** `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Review Focus (5 linhas → testes):**
1. **Dinheiro em Decimal de ponta a ponta.** O float da Remessa vira Decimal na entrada, e "1500.50" ambíguo é recusado. → `tests/test_tela_do_dia_valores.py`; `tests/test_tela_do_dia_pagamentos.py::test_a_pagar_e_decimal_exato`.
2. **"Vai sair" = linha que ENTRA e nasce marcada.** Já enviado e não apto ficam bloqueados. Conta fora do painel aparece em vez de sumir. → `tests/test_tela_do_dia_pagamentos.py`; `tests/test_leitura_do_dia.py`.
3. **No Excel só mudam as células previstas.** São C, D, J, K, E4, H do Painel e H da Movimentações. Só número entra, sem fórmula. Participante sem valor leva 0, nunca vazio, para não cair no VALOR SUGERIDO. A conferência célula a célula continua valendo. → `tests/test_workbook_extras.py`; `tests/test_tela_do_dia_excel.py`.
4. **ERP só pelo Chrome do app.** Com o central desligado, zero login HTTP. Erro do ERP vira `ErpError`, nunca saldo zero. → `tests/test_tela_do_dia_erp.py`.
5. **Aporte não se repete e não se chuta.** Nome não achado, divisão de subconta diferente do cadastro e item já mandado viram pendência. A aba Aportes recusa operação idêntica. O ajuste de saldo guarda o original e acusa quando o ERP mudou. → `tests/test_tela_do_dia_para_aportes.py`; `tests/test_aportes_receber_operacoes.py`; `tests/test_tela_do_dia_saldos.py`; `tests/test_tela_do_dia_dia_de_trabalho.py`.

---

## Mapa de arquivos

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `tela_do_dia/__init__.py` | criar | Pacote da aba (docstring) |
| `tela_do_dia/valores.py` | criar | `ler_valor_editado` (aceita negativo e zero), `de_float`, `brl` |
| `tela_do_dia/saldos.py` | criar | `Ajuste`, `LinhaSaldo`, `montar_saldos`, `aplicar_ajustes`, `novo_ajuste`, `ordenar` |
| `tela_do_dia/dia_de_trabalho.py` | criar | JSON do dia: `DiaDeTrabalho`, `caminho_do_dia`, `ler`, `gravar` (atômico) |
| `tela_do_dia/erp_do_dia.py` | criar | `ler_saldos` (central → porteiro; desligado → aba do app), `PedirPelaAba` |
| `pagamentos_dia/leitura_do_dia.py` | criar | `LeituraDosPagamentos`, `anexos_a_ler`, `baixar_textos`, `ler_pagamentos` |
| `tela_do_dia/pagamentos.py` | criar | `Pagamento`, `PagamentosDaConta`, `por_conta`, `ids_que_nao_saem`, `totais_para_o_painel` |
| `tela_do_dia/aportes.py` | criar | `Participacao`, `AporteDaConta`, `PainelDeAportes`, `conta_mae`, `montar_aportes` |
| `tela_do_dia/excel_do_dia.py` | criar | `linhas_da_movimentacao`, `celulas_de_aporte`, `gerar` |
| `tela_do_dia/para_aportes.py` | criar | `nome_no_cadastro`, `chave_de_envio`, `Pendente`, `Envio`, `operacoes` |
| `tela_do_dia/frame.py` | criar | `TelaDoDiaFrame` (tela fina) |
| `conciliacao/aportadores.py` | modificar | `Regra.linha` |
| `conciliacao/workbook.py` | modificar | `build(..., *, extras=None)`, `assert_untouched(..., *, extras=None)`, `_conferir_extras` |
| `aportes/aportes_frame.py` | modificar | `receber_operacoes`, `_acrescentar` |
| `pagamentos_dia/pagamentos_frame.py` | modificar (1 método no FIM da classe) | `receber_apuracao` |
| `comprovantes_app.py` | modificar | criar a aba, ligar Aportes e Remessa, item "Pagamentos do dia" no DIÁRIO |
| `widgets.py` | modificar | ícone "🧾" nas duas tabelas de ícones |
| `.github/workflows/build.yml`, `motor_minimo.txt` | modificar | empacotar `tela_do_dia/`; pagar a trava sem mudar a versão |
| `tests/test_imports_do_motor.py`, `tests/test_abas_em_paralelo.py` | modificar | `_PASTAS` e `_CHAMADORES` |
| `.claude/rules/arquitetura-tela-do-dia.md`, `CLAUDE.md` | criar / modificar | documentação |
| `tests/test_tela_do_dia_*.py`, `tests/test_leitura_do_dia.py`, `tests/test_workbook_extras.py`, `tests/test_aportadores_linha.py`, `tests/test_aportes_receber_operacoes.py`, `tests/test_remessa_receber_apuracao.py` | criar | testes |

Funções reaproveitadas, conferidas no código em `origin/main` `8f56575`:

**Conciliação**
- `conciliacao/rules.py:148` `resolve_balances(accounts, mapping)`
- `conciliacao/rules.py:186` `build_row_fills(mapping, balances, aggregates)`
- `conciliacao/workbook.py:36` `output_name(date)`
- `conciliacao/workbook.py:85` `build(modelo, destino, reference_date, fills, mapping, planilha)`
- `conciliacao/workbook.py:129` `assert_untouched(...)`
- `conciliacao/workbook.py:202` `_celulas_escritas(...)`
- `conciliacao/aportadores.py:32` `Regra`; `:40` `ler_regras(modelo)`
- `conciliacao/mapping.py:111` `resolve_label`; `:134` `is_ignored`; `:88` `live_rows`
- `conciliacao/parsing.py:101` `normalize_name`; `:160` `format_brl`
- `conciliacao/models.py:56` `sugerir_periodo(hoje)`
- `conciliacao/frame.py:74` `RAIZ_SAIDA`
- `conciliacao/erp/api.py:170` `SessaoApi`; `:185` `logar`; `:239` `_pedir`; `:319` `contas`

**ERP e Anexar**
- `erp/sessao.py:413` `central_ligado()`
- `anexar/mc_api.py:362` `garantir_credenciais_anexos`; `:411` `_fetch_json(url, headers)`
- `anexar/mc_api.py:555` `listar_a_pagar`; `:597` `listar_overviews`; `:636` `anexos_de_titulos`; `:745` `listar_participantes`; `:1039` `baixar_anexo`
- `anexar/anexar_comprovantes.py:479` `submeter(rotulo, fn, *a, dona=)`; `:631` `avisar_se_ocupado(dona, *, aba=)`; `:766` `garantir_sessao(log)`

**Pagamentos do dia (Remessa)**
- `pagamentos_dia/relatorio.py:125` `filtrar_periodo`; `:150` `separar_pagos`; `:155` `nome_da_conta`; `:159` `conta_entra`; `:2266` `gerar_excel(resultado, caminho, log)`
- `pagamentos_dia/confirmacao.py:50` `Entradas`; `:108` `aviso_de_anexos_nao_lidos`; `:121` `remontar(entradas, ids_nao_confirmados)`; `:353` `analisar_remessa(contas, participantes, carregar_mapas, abrir_historico)`
- `pagamentos_dia/confirmacao.py:680` `Linha`; `:733` `Grupo`; `:765` `grupos_da_confirmacao(...)`; `:872` `marcada_de_inicio(linha)`
- `pagamentos_dia/html_pagamentos.py:605` `tirar_reembolsos`; `:812` `gravar(resultado, lancamentos, anexos, pasta, ini, fim, pastas_extras=)`
- `pagamentos_dia/pagamentos_frame.py:78` `_historico(avisar)`; `:104` `_carregar_mapas()`
- Orquestração espelhada da Remessa: `pagamentos_frame.py:1466` `_t_buscar`, `:1972` `_juntar_entradas`, `:3689` `_anexos_a_ler`, `:3712` `_baixar_textos`

**Aportes**
- `aportes/regras.py:26` `TIPO_INVESTIDOR`; `:61` `numero_da_conta`; `:67` `e_da_subconta`; `:107` `como_dinheiro`; `:131` `ler_valor_brl`; `:229` `dividir_por_peso(total, nomes, pesos)`
- `aportes/regras.py:264` `Operacao` (dataclass); `:273` `validar(entidades, subcontas)`
- `aportes/aportes_frame.py:312` `_adicionar`; `:348` `_lista_travada`; `:432` `_atualizar_total`

**Fato do MODELO que sustenta a Tarefa 10** (medido no `_app/MODELO.xlsx` real):
- Painel: `H7` = "APORTE DEFINIDO", vazio nas linhas.
- Movimentações: `H7` = "VALOR DEFINIDO"; a linha N tem `B = IF(Regras!$C<n>...)` e `I = IF($H<>"",$H,G)`.
- A linha da Movimentações NÃO é a da Regras mais um número fixo: as linhas 25 e 26 estão vazias e a seção 2 começa na 28, que é a regra 21. Por isso o mapeamento sai da fórmula.

---

## Tarefa 1 — Pacote `tela_do_dia/`, empacotamento e `valores.py`
**Modelo sugerido:** sonnet (mexe no `build.yml` e na trava do motor).

**Files:**
- Create: `tela_do_dia/__init__.py`, `tela_do_dia/valores.py`, `tests/test_tela_do_dia_valores.py`
- Modify: `.github/workflows/build.yml` (antes da linha `Compress-Archive`), `tests/test_imports_do_motor.py:28-31` (`_PASTAS`), `motor_minimo.txt` (só o fim de linha)

**Interfaces:**
```python
def ler_valor_editado(texto) -> Decimal      # aceita negativo e zero; ValueError com recado
def de_float(valor) -> Decimal                # float da Remessa -> Decimal 2 casas, HALF_UP
def brl(valor: Decimal | None) -> str         # = conciliacao.parsing.format_brl ("—" para None)
```

- [ ] **Passo 1: teste que falha** — `tests/test_tela_do_dia_valores.py`
```python
"""O dinheiro digitado na aba Pagamentos do dia. Fictício, sem tela."""
from decimal import Decimal

import pytest

from tela_do_dia.valores import brl, de_float, ler_valor_editado


@pytest.mark.parametrize("texto, esperado", [
    ("1.234,56", "1234.56"), ("-1.234,56", "-1234.56"), ("R$ -10,00", "-10.00"),
    ("- R$ 10,00", "-10.00"), ("0", "0.00"), ("0,00", "0.00"), ("1500", "1500.00"),
])
def test_le_o_valor_editado(texto, esperado):
    assert ler_valor_editado(texto) == Decimal(esperado)


@pytest.mark.parametrize("texto", ["1500.50", "", "abc", "1,234", "--5"])
def test_recusa_o_ambiguo_e_o_que_nao_e_valor(texto):
    with pytest.raises(ValueError):
        ler_valor_editado(texto)


def test_de_float_nao_herda_lixo_binario():
    assert de_float(0.1 + 0.2) == Decimal("0.30")
    assert de_float(None) == Decimal("0.00")


def test_brl_mostra_negativo_e_vazio():
    assert brl(Decimal("-1234.5")) == "-R$ 1.234,50"
    assert brl(None) == "—"
```
- [ ] **Passo 2:** `python -m pytest tests/test_tela_do_dia_valores.py -q`. Esperado: FALHA (`ModuleNotFoundError: tela_do_dia`).
- [ ] **Passo 3: implementação**

`tela_do_dia/__init__.py`:
```python
# -*- coding: utf-8 -*-
"""Aba "Pagamentos do dia": saldos, o que vai sair, aportes e o Excel do dia
numa tela só (entrega 1 da especificação de 21/10/2026).

Toda regra mora nos módulos puros deste pacote e tem teste sem janela; o
`frame.py` é a tela fina por cima. Nada aqui escreve no Mais Controle.
"""
```
`tela_do_dia/valores.py`:
```python
# -*- coding: utf-8 -*-
"""Dinheiro digitado e mostrado na aba Pagamentos do dia. Sem tela.

Saldo pode ser negativo e pode ser zero, ao contrário do valor de aporte. Por
isso `aportes.regras.ler_valor_brl` (que recusa os dois) é usado só para a
MAGNITUDE: o sinal e o zero se resolvem aqui, e a recusa do ambíguo ("1500.50")
continua sendo a dela, sem uma segunda régua.
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

from aportes.regras import ler_valor_brl
from conciliacao.parsing import format_brl

CENTAVO = Decimal("0.01")
_ZERO = re.compile(r"0+(,0{1,2})?")


def ler_valor_editado(texto) -> Decimal:
    t = str(texto or "").replace("\xa0", " ").strip()
    negativo = t.startswith("-")
    if negativo:
        t = t[1:].strip()
    t = re.sub(r"^r\$", "", t, flags=re.IGNORECASE).strip()
    if not negativo and t.startswith("-"):          # "R$ -10,00"
        negativo, t = True, t[1:].strip()
    if _ZERO.fullmatch(t):
        return Decimal("0.00")
    valor = ler_valor_brl(t)
    return -valor if negativo else valor


def de_float(valor) -> Decimal:
    """O `valor` float da apuração da Remessa, em Decimal. Passa por `str`."""
    return Decimal(str(valor or 0)).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def brl(valor) -> str:
    return format_brl(valor)
```
- [ ] **Passo 4: empacotamento**

No `build.yml`, logo depois do bloco do `erp/` e ANTES de `Compress-Archive`:
```yaml
          # `tela_do_dia/` é a aba "Pagamentos do dia". Pasta nova de aba =
          # linha nova aqui, senão o import falha no usuário e o app não abre.
          New-Item -ItemType Directory codigo_embutido/tela_do_dia | Out-Null
          Copy-Item tela_do_dia/*.py codigo_embutido/tela_do_dia/
```
Em `tests/test_imports_do_motor.py:28-31`, acrescentar `"tela_do_dia"` à tupla `_PASTAS`.

Tocar no `motor_minimo.txt` sem mudar a versão:
```
python -c "import pathlib; p=pathlib.Path('motor_minimo.txt'); t=p.read_text(encoding='utf-8'); p.write_text(t.rstrip('\n') if t.endswith('\n') else t+'\n', encoding='utf-8', newline='')"
```
Depois, `git diff motor_minimo.txt` tem de mostrar só o fim de linha, e o conteúdo continua `v2.0.233`.

Depois, `git add tela_do_dia`.
- [ ] **Passo 5:** `python -m pytest tests/test_tela_do_dia_valores.py tests/test_empacotamento.py tests/test_imports_do_motor.py tests/test_nomes_de_modulo.py -q`. Esperado: PASSA.
- [ ] **Passo 6: commit**
```
git add tela_do_dia tests/test_tela_do_dia_valores.py tests/test_imports_do_motor.py .github/workflows/build.yml motor_minimo.txt
git commit -m "Pagamentos do dia: pacote tela_do_dia no codigo.zip e leitura de valor editado

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Tarefa 2 — `Regra.linha` (a linha da aba «Regras»)
**Modelo sugerido:** haiku.

**Files:**
- Modify: `conciliacao/aportadores.py:31-69`
- Create: `tests/test_aportadores_linha.py`

**Interfaces:** `Regra(destino, aportador, peso, tipo, do_painel, linha: int = 0)`. `ler_regras(modelo)` preenche `linha`.

- [ ] **Passo 1: teste que falha**
```python
"""`ler_regras` guarda a linha de cada regra: é por ela que o Excel do dia acha
a linha da aba «Movimentações». Modelo fictício."""
from decimal import Decimal

import openpyxl

from conciliacao.aportadores import Regra, ler_regras


def test_ler_regras_guarda_a_linha_mesmo_com_buraco(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "Painel"
    reg = wb.create_sheet("Regras")
    reg["B5"], reg["C5"], reg["E5"], reg["F5"] = "Conta Alfa - Banco", "Conta Beta - Banco", "Aporte", "sim"
    reg["B7"], reg["C7"], reg["D7"], reg["E7"] = "Conta Alfa - Banco", "Socio Ficticio", 2, "Aporte"
    caminho = tmp_path / "MODELO.xlsx"
    wb.save(caminho)
    regras = ler_regras(caminho)
    assert [(r.linha, r.aportador) for r in regras] == [(5, "Conta Beta - Banco"), (7, "Socio Ficticio")]
    assert regras[1].peso == Decimal("2")


def test_regra_construida_a_mao_continua_valendo():
    assert Regra("A", "B", None, "Aporte", True).linha == 0
```
- [ ] **Passo 2:** `python -m pytest tests/test_aportadores_linha.py -q`. Esperado: FALHA (`unexpected keyword`/atributo `linha`).
- [ ] **Passo 3: implementação.** Em `Regra`, depois de `do_painel`:
```python
    #: A linha da aba «Regras» de onde a regra saiu (0 = montada à mão). É o
    #: endereço que a aba «Movimentações» cita em `Regras!$C<linha>`.
    linha: int = 0
```
Em `ler_regras`, trocar o laço por:
```python
        for numero, linha in enumerate(
                ws.iter_rows(min_row=PRIMEIRA_LINHA, min_col=2, max_col=6,
                             values_only=True), start=PRIMEIRA_LINHA):
            destino, aportador, peso, tipo, do_painel = linha
```
Acrescentar `linha=numero` ao `Regra(...)`.
- [ ] **Passo 4:** `python -m pytest tests/test_aportadores_linha.py tests/test_panel.py tests/test_end_to_end.py -q`. Esperado: PASSA (os dois últimos pulam sem MODELO).
- [ ] **Passo 5: commit** — mensagem `"Regras de aporte guardam a linha da aba Regras"` + rodapé.

---

## Tarefa 3 — `workbook.build(extras=...)`: só número, conferido célula a célula
**Modelo sugerido:** sonnet.

**Files:**
- Modify: `conciliacao/workbook.py:85-214`
- Create: `tests/test_workbook_extras.py`

**Interfaces:**
```python
def build(modelo, destino, reference_date, fills, mapping, planilha, *,
          extras: dict[str, dict[str, float]] | None = None) -> BuildResult
def assert_untouched(modelo, destino, reference_date, fills, planilha, *,
                     extras: dict[str, dict[str, float]] | None = None) -> int
def _conferir_extras(modelo: Path, extras) -> dict[str, dict[str, float]]
```

- [ ] **Passo 1: teste que falha** — `tests/test_workbook_extras.py`
```python
"""Células EXTRAS do painel do dia (aporte definido, valor por aportador).
Modelo fictício no tmp_path — o real fica fora do repositório."""
from datetime import date
from decimal import Decimal

import openpyxl
import pytest

from conciliacao.config import PlanilhaConfig
from conciliacao.mapping import AccountMapping
from conciliacao.models import RowFill
from conciliacao.workbook import WorkbookError, build

HOJE = date(2026, 10, 21)
ROTULOS = ("Conta Alfa - Banco", "Conta Beta - Banco", "Conta Gama - Banco")
PLANILHA = PlanilhaConfig(
    aba="Painel", primeira_linha=8, ultima_linha=10, linha_totais=12,
    ultima_coluna="M", celula_data="E4", celula_total_pagamentos="D12",
    formato_data="DD/MM/YYYY", col_saldo="C", col_pagamento="D",
    col_qtd_sistema="J", col_qtd_banco="K", colunas_formula=("E", "F", "G", "I", "L"))
MAPA = ("model_rows:\n"
        "- row: 8\n  label: Conta Alfa - Banco\n  uuid: uuid-alfa\n"
        "- row: 9\n  label: Conta Beta - Banco\n  uuid: uuid-beta\n"
        "- row: 10\n  label: Conta Gama - Banco\n  uuid: uuid-gama\n")


@pytest.fixture
def mapa(tmp_path):
    caminho = tmp_path / "mapping.yaml"
    caminho.write_text(MAPA, encoding="utf-8")
    return AccountMapping.load(caminho)


@pytest.fixture
def modelo(tmp_path):
    wb = openpyxl.Workbook()
    p = wb.active
    p.title = "Painel"
    mov = wb.create_sheet("Movimentações")
    wb.create_sheet("Regras")
    p["H7"] = "APORTE\nDEFINIDO (R$)"
    for r, rotulo in zip((8, 9, 10), ROTULOS):
        p[f"B{r}"] = rotulo
        p[f"I{r}"] = f"=$C{r}-$D{r}+$H{r}"
    p["C12"] = "=SUM(C8:C10)"
    mov["H7"] = "VALOR\nDEFINIDO (R$)"
    mov["B9"] = '=IF(Regras!$C5="","",Regras!$C5)'
    mov["I9"] = '=IF($H9<>"",$H9,"")'
    caminho = tmp_path / "MODELO.xlsx"
    wb.save(caminho)
    return caminho


def _fills():
    return [RowFill(8, Decimal("100.50"), Decimal("300.00"), 2, None),
            RowFill(9, Decimal("0"), Decimal("0"), 0, 0),
            RowFill(10, None, Decimal("0"), 0, 0)]


def test_sem_extras_continua_como_antes(modelo, mapa, tmp_path):
    assert build(modelo, tmp_path / "s.xlsx", HOJE, _fills(), mapa, PLANILHA).linhas_escritas == 3


def test_extras_entram_e_sao_conferidos(modelo, mapa, tmp_path):
    destino = tmp_path / "s.xlsx"
    build(modelo, destino, HOJE, _fills(), mapa, PLANILHA,
          extras={"Painel": {"H8": 199.5}, "Movimentações": {"H9": 150.0}})
    wb = openpyxl.load_workbook(destino)
    assert wb["Painel"]["H8"].value == 199.5
    assert wb["Movimentações"]["H9"].value == 150.0
    assert wb["Painel"]["I8"].value == "=$C8-$D8+$H8"
    assert wb["Movimentações"]["I9"].value == '=IF($H9<>"",$H9,"")'


@pytest.mark.parametrize("valor", ["=1+1", "199,50", Decimal("1"), None, True])
def test_extra_que_nao_e_numero_e_recusado_antes_de_copiar(modelo, mapa, tmp_path, valor):
    destino = tmp_path / "s.xlsx"
    with pytest.raises(WorkbookError):
        build(modelo, destino, HOJE, _fills(), mapa, PLANILHA, extras={"Painel": {"H8": valor}})
    assert not destino.exists()


def test_extra_em_aba_que_o_modelo_nao_tem_e_recusado(modelo, mapa, tmp_path):
    destino = tmp_path / "s.xlsx"
    with pytest.raises(WorkbookError, match="Fantasma"):
        build(modelo, destino, HOJE, _fills(), mapa, PLANILHA, extras={"Fantasma": {"A1": 1.0}})
    assert not destino.exists()
```
- [ ] **Passo 2:** `python -m pytest tests/test_workbook_extras.py -q`. Esperado: FALHA (`unexpected keyword argument 'extras'`).
- [ ] **Passo 3: implementação** em `conciliacao/workbook.py`.

Nova função, acima de `build`:
```python
def _conferir_extras(modelo: Path, extras) -> dict[str, dict[str, float]]:
    """As células extras (aporte definido, valor por aportador) ANTES de copiar.

    Só NÚMERO entra: texto ou fórmula numa célula que o Excel soma seria o
    "fórmula digitada à mão" que a tela nova existe para acabar — e um "=" vira
    fórmula no openpyxl. Recusar antes de `copy2` é o que garante que o arquivo
    do dia anterior não foi trocado por uma cópia crua do modelo."""
    if not extras:
        return {}
    for aba, celulas in extras.items():
        for coord, valor in celulas.items():
            if isinstance(valor, bool) or not isinstance(valor, (int, float)):
                raise WorkbookError(
                    f"{aba}!{coord}: só número entra no painel do dia, veio {valor!r}")
    wb = openpyxl.load_workbook(modelo, read_only=True)
    try:
        nomes = list(wb.sheetnames)
    finally:
        wb.close()
    faltam = sorted(set(extras) - set(nomes))
    if faltam:
        raise WorkbookError(f"o modelo não tem a(s) aba(s) {faltam}; encontrei {nomes}")
    return {aba: dict(celulas) for aba, celulas in extras.items()}
```
Em `build`:
- a assinatura ganha `*, extras=None`;
- logo depois de `if not modelo.is_file(): ...`, chamar `extras = _conferir_extras(modelo, extras)`;
- depois do laço dos `fills` e antes de `wb.save(destino)`:
```python
    for aba, celulas in extras.items():
        alvo = wb[aba]
        for coord, valor in celulas.items():
            alvo[coord] = valor
```
- e a chamada final passa a ser `assert_untouched(modelo, destino, reference_date, fills, planilha, extras=extras)`.

Em `assert_untouched`:
- a assinatura ganha `*, extras=None`;
- logo depois de montar `esperado`:
```python
    extras = extras or {}
    esperado.update(extras.get(planilha.aba, {}))
```
- o laço das abas de apoio vira:
```python
        for nome in wb_orig.sheetnames:
            if nome == planilha.aba:
                continue
            oa, ob = wb_orig[nome], wb_novo[nome]
            da_aba = extras.get(nome, {})
            for linha_o, linha_n in zip(oa.iter_rows(), ob.iter_rows()):
                for original, novo in zip(linha_o, linha_n):
                    if original.coordinate in da_aba:
                        continue                      # conferida logo abaixo
                    conferidas += 1
                    if original.value != novo.value:
                        problemas.append(
                            f"  {nome}!{original.coordinate}: modelo={original.value!r} "
                            f"virou {novo.value!r}")
            for coord, valor in da_aba.items():
                gravado = ob[coord].value
                conferidas += 1
                if gravado != valor:
                    problemas.append(f"  {nome}!{coord}: gravado={gravado!r} esperado={valor!r}")
```
Atualizar a docstring do módulo: "escreve a data, as quatro colunas de dados e, quando a tela nova manda, as células extras de aporte".
- [ ] **Passo 4:** `python -m pytest tests/test_workbook_extras.py tests/test_workbook.py tests/test_painel_novas.py -q`. Esperado: PASSA (`test_workbook` pula sem MODELO).
- [ ] **Passo 5: commit** — `"Painel do dia: workbook.build aceita células extras, só número e conferidas"` + rodapé.

---

## Tarefa 4 — `saldos.py`: sistema × banco, ajuste com original, ordem
**Modelo sugerido:** sonnet.

**Files:**
- Create: `tela_do_dia/saldos.py`, `tests/test_tela_do_dia_saldos.py`

**Interfaces:**
```python
SISTEMA = "sistema"; BANCO = "banco"
@dataclass(frozen=True) class Ajuste: valor: Decimal; original: Decimal | None; motivo: str = ""; quando: str = ""
@dataclass(frozen=True) class LinhaSaldo:
    linha: int; rotulo: str; sistema: Decimal | None; banco: Decimal | None = None
    ajuste_sistema: Ajuste | None = None; ajuste_banco: Ajuste | None = None
    sistema_usado / banco_usado / diferenca / saldo_do_dia / original_mudou (properties); situacao() -> (tag, frase)
def montar_saldos(contas: list[ErpAccount], mapping) -> list[LinhaSaldo]
def aplicar_ajustes(linhas, ajustes: dict[str, dict[str, Ajuste]]) -> list[LinhaSaldo]
def novo_ajuste(linha: LinhaSaldo, campo: str, valor: Decimal, motivo: str = "", quando: str = "") -> Ajuste
def ordenar(linhas) -> list[LinhaSaldo]
```

- [ ] **Passo 1: teste que falha** — `tests/test_tela_do_dia_saldos.py`
```python
"""Saldos da tela do dia. Contas fictícias."""
from decimal import Decimal as D

import pytest

from conciliacao.mapping import AccountMapping
from conciliacao.models import ErpAccount
from tela_do_dia import saldos as sd

MAPA = ("model_rows:\n"
        "- row: 8\n  label: Conta Alfa - Banco\n  uuid: uuid-alfa\n  erp_name: ALFA LTDA - BANCO\n"
        "- row: 9\n  label: Conta Beta - Banco\n  uuid: uuid-beta\n  erp_name: BETA LTDA - BANCO\n"
        "- row: 10\n  label: Conta Gama - Banco\n  uuid: uuid-gama\n  erp_name: GAMA LTDA - BANCO\n"
        "- row: 11\n  label: Conta Morta - Banco\n  exists_in_erp: false\n")
CONTAS = [ErpAccount("uuid-alfa", "ALFA LTDA - BANCO", balance=D("100.00")),
          ErpAccount("uuid-beta", "BETA LTDA - BANCO", balance=D("50.00"))]


@pytest.fixture
def mapa(tmp_path):
    caminho = tmp_path / "mapping.yaml"
    caminho.write_text(MAPA, encoding="utf-8")
    return AccountMapping.load(caminho)


def test_uma_linha_por_conta_viva_e_saldo_nao_lido_e_none(mapa):
    linhas = sd.montar_saldos(CONTAS, mapa)
    assert [(ln.linha, ln.sistema) for ln in linhas] == [(8, D("100.00")), (9, D("50.00")), (10, None)]


def test_situacao_sem_banco_bate_e_nao_bate(mapa):
    alfa = sd.montar_saldos(CONTAS, mapa)[0]
    assert alfa.situacao()[0] == "info"
    ok = sd.aplicar_ajustes([alfa], {"Conta Alfa - Banco": {sd.BANCO: sd.novo_ajuste(alfa, sd.BANCO, D("100.00"))}})[0]
    assert ok.situacao() == ("ok", "bate")
    ruim = sd.aplicar_ajustes([alfa], {"Conta Alfa - Banco": {sd.BANCO: sd.novo_ajuste(alfa, sd.BANCO, D("90.00"))}})[0]
    tag, frase = ruim.situacao()
    assert tag == "erro" and "R$ 10,00" in frase and ruim.diferenca == D("-10.00")


def test_ajuste_no_sistema_guarda_o_original_e_o_motivo(mapa):
    alfa = sd.montar_saldos(CONTAS, mapa)[0]
    aj = sd.novo_ajuste(alfa, sd.SISTEMA, D("-5.00"), "  simulação  ", quando="2026-10-21T09:00")
    nova = sd.aplicar_ajustes([alfa], {"Conta Alfa - Banco": {sd.SISTEMA: aj}})[0]
    assert (nova.sistema, nova.sistema_usado, nova.ajuste_sistema.original) == (D("100.00"), D("-5.00"), D("100.00"))
    assert nova.ajuste_sistema.motivo == "simulação"
    assert nova.saldo_do_dia == D("-5.00")


def test_o_banco_manda_no_saldo_do_dia_quando_existe(mapa):
    alfa = sd.montar_saldos(CONTAS, mapa)[0]
    com_banco = sd.aplicar_ajustes([alfa], {"Conta Alfa - Banco": {sd.BANCO: sd.novo_ajuste(alfa, sd.BANCO, D("80.00"))}})[0]
    assert com_banco.saldo_do_dia == D("80.00")


def test_sistema_que_mudou_depois_do_ajuste_e_avisado(mapa):
    alfa = sd.montar_saldos(CONTAS, mapa)[0]
    aj = sd.Ajuste(valor=D("70.00"), original=D("60.00"))
    tag, frase = sd.aplicar_ajustes([alfa], {"Conta Alfa - Banco": {sd.SISTEMA: aj}})[0].situacao()
    assert tag == "atencao" and "era R$ 60,00" in frase and "R$ 100,00" in frase


def test_ordem_poe_o_que_nao_bate_em_cima(mapa):
    linhas = sd.montar_saldos(CONTAS, mapa)
    beta = linhas[1]
    linhas = sd.aplicar_ajustes(linhas, {"Conta Beta - Banco": {sd.BANCO: sd.novo_ajuste(beta, sd.BANCO, D("1.00"))}})
    assert [ln.linha for ln in sd.ordenar(linhas)] == [9, 10, 8]
```
- [ ] **Passo 2:** `python -m pytest tests/test_tela_do_dia_saldos.py -q`. Esperado: FALHA (módulo ausente).
- [ ] **Passo 3: implementação** — `tela_do_dia/saldos.py`
```python
# -*- coding: utf-8 -*-
"""Passo 1 da tela do dia: saldo do sistema × saldo do banco, por conta.

O ajuste NUNCA apaga o que foi lido: ele fica ao lado (`original`) e vale só
no dia (o arquivo do dia é por data, ver `dia_de_trabalho`). Se o ERP mudar o
saldo depois do ajuste, a linha avisa em vez de esconder — simulação feita
sobre um número que já não é o do sistema é o tipo de engano que só aparece
quando o dinheiro falta.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from conciliacao.rules import resolve_balances

from .valores import brl

SISTEMA = "sistema"
BANCO = "banco"
_PESO = {"erro": 0, "atencao": 1, "info": 2, "ok": 3}


@dataclass(frozen=True)
class Ajuste:
    valor: Decimal
    original: Decimal | None
    motivo: str = ""
    quando: str = ""


@dataclass(frozen=True)
class LinhaSaldo:
    linha: int
    rotulo: str
    sistema: Decimal | None
    banco: Decimal | None = None          # entrega 3 (Sicoob) preenche
    ajuste_sistema: Ajuste | None = None
    ajuste_banco: Ajuste | None = None

    @property
    def sistema_usado(self) -> Decimal | None:
        return self.ajuste_sistema.valor if self.ajuste_sistema else self.sistema

    @property
    def banco_usado(self) -> Decimal | None:
        return self.ajuste_banco.valor if self.ajuste_banco else self.banco

    @property
    def diferenca(self) -> Decimal | None:
        if self.sistema_usado is None or self.banco_usado is None:
            return None
        return self.banco_usado - self.sistema_usado

    @property
    def saldo_do_dia(self) -> Decimal | None:
        """O que vai para a coluna C: o banco, quando há; senão o sistema."""
        banco = self.banco_usado
        return banco if banco is not None else self.sistema_usado

    @property
    def original_mudou(self) -> bool:
        a = self.ajuste_sistema
        return a is not None and a.original != self.sistema

    def situacao(self) -> tuple[str, str]:
        if self.sistema_usado is None:
            return "erro", "o sistema não trouxe o saldo"
        if self.original_mudou:
            return "atencao", (f"o sistema mudou desde o ajuste: era "
                               f"{brl(self.ajuste_sistema.original)}, agora {brl(self.sistema)}")
        if self.banco_usado is None:
            return "info", "sem o saldo do banco"
        dif = self.diferenca
        if dif == 0:
            return "ok", "bate"
        return "erro", f"não bate — diferença de {brl(dif)}"


def montar_saldos(contas, mapping) -> list[LinhaSaldo]:
    """Uma linha por conta VIVA do painel, na ordem das linhas. Mesma régua do
    painel antigo (`resolve_balances`): não há segunda lista de contas."""
    res = resolve_balances(contas, mapping)
    return [LinhaSaldo(linha=r.row, rotulo=r.label, sistema=res.balances.get(r.row))
            for r in sorted(mapping.live_rows, key=lambda r: r.row)]


def aplicar_ajustes(linhas, ajustes: dict) -> list[LinhaSaldo]:
    saida = []
    for ln in linhas:
        do_rotulo = ajustes.get(ln.rotulo) or {}
        saida.append(replace(ln, ajuste_sistema=do_rotulo.get(SISTEMA),
                             ajuste_banco=do_rotulo.get(BANCO)))
    return saida


def novo_ajuste(linha: LinhaSaldo, campo: str, valor: Decimal,
                motivo: str = "", quando: str = "") -> Ajuste:
    if campo not in (SISTEMA, BANCO):
        raise ValueError(f"campo desconhecido: {campo!r}")
    original = linha.sistema if campo == SISTEMA else linha.banco
    return Ajuste(valor=valor, original=original,
                  motivo=str(motivo or "").strip()[:200], quando=quando)


def ordenar(linhas) -> list[LinhaSaldo]:
    """O que não bate (e o não lido) sobe; depois atenção; depois o resto."""
    return sorted(linhas, key=lambda ln: (_PESO[ln.situacao()[0]], ln.linha))
```
- [ ] **Passo 4:** `python -m pytest tests/test_tela_do_dia_saldos.py -q`. Esperado: PASSA.
- [ ] **Passo 5: commit** — `"Pagamentos do dia: saldos sistema x banco com ajuste que guarda o original"` + rodapé.

---

## Tarefa 5 — `dia_de_trabalho.py`: o JSON do dia
**Modelo sugerido:** sonnet.

**Por que JSON e não SQL agora:**
- SQL novo exige o revisor de SQL e desenho de RLS, e a especificação põe a nuvem na entrega 2.
- O arquivo mora na pasta do Excel do dia (`RAIZ_SAIDA/<ANO>/<MÊS>`, fora do repositório), então é dado da empresa no lugar onde o dia já é arquivado.
- O nome leva a data, então "vale só no dia" vem de graça.
- Escrita atômica (`os.replace`), como `nuvem/cache.py:60-63`.
- Arquivo ilegível levanta `ValueError` e a tela para de gravar. Nunca é sobrescrito com o dia vazio.

**Files:**
- Create: `tela_do_dia/dia_de_trabalho.py`, `tests/test_tela_do_dia_dia_de_trabalho.py`

**Interfaces:**
```python
VERSAO = 1
@dataclass class DiaDeTrabalho: data: date; ajustes: dict[str, dict[str, Ajuste]]; aportes: dict[tuple[str, str], Decimal]; enviados_aportes: dict[str, str]
def pasta_do_dia(raiz_saida: Path, data: date) -> Path
def nome_do_arquivo(data: date) -> str
def caminho_do_dia(raiz_saida: Path, data: date) -> Path
def para_dict(dia) -> dict;  def de_dict(dados: dict, data: date) -> DiaDeTrabalho
def ler(caminho: Path, data: date) -> DiaDeTrabalho;  def gravar(dia, caminho: Path) -> Path
```

- [ ] **Passo 1: teste que falha**
```python
"""O JSON do dia de trabalho. Valores e contas fictícios."""
import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from tela_do_dia import dia_de_trabalho as ddt
from tela_do_dia.saldos import BANCO, SISTEMA, Ajuste

HOJE = date(2026, 10, 21)


def test_caminho_ao_lado_do_excel_do_dia():
    assert ddt.pasta_do_dia(Path("C:/X"), HOJE) == Path("C:/X/2026/OUTUBRO")
    assert ddt.caminho_do_dia(Path("C:/X"), HOJE).name == "21 10 - dia de trabalho.json"


def test_ida_e_volta_preserva_decimal(tmp_path):
    dia = ddt.DiaDeTrabalho(HOJE)
    dia.ajustes["Conta Alfa - Banco"] = {SISTEMA: Ajuste(D("-5.10"), D("100.00"), "simulação", "2026-10-21T09:00"),
                                          BANCO: Ajuste(D("98.00"), None)}
    dia.aportes[("Conta Alfa - Banco", "Socio Ficticio")] = D("199.50")
    dia.enviados_aportes["Conta Alfa - Banco|Socio Ficticio|199.50"] = "2026-10-21T10:00"
    caminho = ddt.gravar(dia, tmp_path / "x" / "dia.json")
    volta = ddt.ler(caminho, HOJE)
    assert volta == dia
    assert not list(caminho.parent.glob("*.tmp"))


def test_arquivo_ausente_e_dia_vazio(tmp_path):
    assert ddt.ler(tmp_path / "nada.json", HOJE) == ddt.DiaDeTrabalho(HOJE)


def test_arquivo_de_outro_dia_nao_vale_hoje(tmp_path):
    caminho = ddt.gravar(ddt.DiaDeTrabalho(date(2026, 10, 20), aportes={("A", "B"): D("1")}), tmp_path / "d.json")
    assert ddt.ler(caminho, HOJE) == ddt.DiaDeTrabalho(HOJE)


@pytest.mark.parametrize("conteudo", ["{", json.dumps({"data": "2026-10-21", "ajustes": [{"conta": "A"}]})])
def test_arquivo_ilegivel_levanta_com_o_caminho(tmp_path, conteudo):
    caminho = tmp_path / "ruim.json"
    caminho.write_text(conteudo, encoding="utf-8")
    with pytest.raises(ValueError, match="ruim.json"):
        ddt.ler(caminho, HOJE)
```
- [ ] **Passo 2:** `python -m pytest tests/test_tela_do_dia_dia_de_trabalho.py -q`. Esperado: FALHA.
- [ ] **Passo 3: implementação**
```python
# -*- coding: utf-8 -*-
"""O "dia de trabalho" da tela: ajustes de saldo, valores por aportador e o que
já foi mandado para a aba Aportes. Um JSON por dia, ao lado do Excel do dia.

Entrega 1 sem SQL de propósito (a nuvem é a entrega 2). Arquivo ilegível
LEVANTA: a tela então deixa de gravar, porque sobrescrever com o dia vazio
apagaria os ajustes que a pessoa fez e não vê mais.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import util

from .saldos import BANCO, SISTEMA, Ajuste

VERSAO = 1


@dataclass
class DiaDeTrabalho:
    data: date
    ajustes: dict = field(default_factory=dict)
    aportes: dict = field(default_factory=dict)
    enviados_aportes: dict = field(default_factory=dict)


def pasta_do_dia(raiz_saida, data: date) -> Path:
    return Path(raiz_saida) / str(data.year) / util.MESES_PASTA[data.month - 1]


def nome_do_arquivo(data: date) -> str:
    return f"{data:%d %m} - dia de trabalho.json"


def caminho_do_dia(raiz_saida, data: date) -> Path:
    return pasta_do_dia(raiz_saida, data) / nome_do_arquivo(data)


def _dec(v):
    return None if v is None else str(v)


def para_dict(dia: DiaDeTrabalho) -> dict:
    return {
        "versao": VERSAO,
        "data": dia.data.isoformat(),
        "ajustes": [{"conta": conta, "campo": campo, "valor": str(a.valor),
                     "original": _dec(a.original), "motivo": a.motivo, "quando": a.quando}
                    for conta, campos in sorted(dia.ajustes.items())
                    for campo, a in sorted(campos.items())],
        "aportes": [{"destino": d, "aportador": ap, "valor": str(v)}
                    for (d, ap), v in sorted(dia.aportes.items())],
        "enviados_aportes": dict(sorted(dia.enviados_aportes.items())),
    }


def de_dict(dados: dict, data: date) -> DiaDeTrabalho:
    dia = DiaDeTrabalho(data)
    try:
        for a in dados.get("ajustes") or []:
            if a["campo"] not in (SISTEMA, BANCO):
                raise ValueError(f"campo {a['campo']!r}")
            dia.ajustes.setdefault(a["conta"], {})[a["campo"]] = Ajuste(
                valor=Decimal(a["valor"]),
                original=None if a.get("original") is None else Decimal(a["original"]),
                motivo=a.get("motivo") or "", quando=a.get("quando") or "")
        for item in dados.get("aportes") or []:
            dia.aportes[(item["destino"], item["aportador"])] = Decimal(item["valor"])
        dia.enviados_aportes = {str(k): str(v)
                                for k, v in (dados.get("enviados_aportes") or {}).items()}
    except (KeyError, TypeError, InvalidOperation) as e:
        raise ValueError(f"formato inesperado ({e!r})") from e
    return dia


def ler(caminho, data: date) -> DiaDeTrabalho:
    p = Path(caminho)
    if not p.is_file():
        return DiaDeTrabalho(data)
    try:
        dados = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(dados, dict):
            raise ValueError("o conteúdo não é um objeto")
        if str(dados.get("data")) != data.isoformat():
            return DiaDeTrabalho(data)            # vale só no dia
        return de_dict(dados, data)
    except (OSError, ValueError) as e:
        raise ValueError(f"não consegui ler {p.as_posix()}: {e}") from e


def gravar(dia: DiaDeTrabalho, caminho) -> Path:
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    temporario = p.with_name(p.name + ".tmp")
    temporario.write_text(json.dumps(para_dict(dia), ensure_ascii=False, indent=2),
                          encoding="utf-8")
    os.replace(temporario, p)
    return p
```
- [ ] **Passo 4:** `python -m pytest tests/test_tela_do_dia_dia_de_trabalho.py -q`. Esperado: PASSA.
- [ ] **Passo 5: commit** — `"Pagamentos do dia: o dia de trabalho num JSON ao lado do Excel do dia"` + rodapé.

---

## Tarefa 6 — `erp_do_dia.py`: saldos só pelo Chrome do app
**Modelo sugerido:** sonnet.

**Files:**
- Create: `tela_do_dia/erp_do_dia.py`, `tests/test_tela_do_dia_erp.py`

**Interfaces:**
```python
class PedirPelaAba:   # o que SessaoApi._pedir (conciliacao/erp/api.py:239) exige: pedir(url), transporte, espera
    def __init__(self, api): ...
    def pedir(self, url: str): ...
def ler_saldos(config, api, *, central_ligado=None, logar=None, log=print) -> list[ErpAccount]
```

- [ ] **Passo 1: teste que falha**
```python
"""Saldos do ERP sem login HTTP. Dublês; contas fictícias."""
from decimal import Decimal

import pytest

from conciliacao.errors import ErpError
from tela_do_dia import erp_do_dia

CAPTURA = ("https://prod-erp-api.maiscontroleerp.com.br/attachments/v2",
           {"authorization": "Bearer ficticio", "company-id": "c"})
CONTAS = {"items": [{"id": "uuid-alfa", "name": "ALFA LTDA - BANCO", "isActive": True}],
          "hasNextPage": False}
SALDOS = {"uuid-alfa": 1234.56}


class Cfg:
    erp = {}


class ApiDaAba:
    def __init__(self, respostas, capturado=True, garante=True):
        self._req_anexos = CAPTURA if capturado else None
        self.respostas, self.urls, self.garantiu, self._garante = respostas, [], False, garante

    def _fetch_json(self, url, headers):
        self.urls.append((url, headers))
        for pedaco, corpo in self.respostas.items():
            if pedaco in url:
                return corpo
        return {"__erro": 404}

    def garantir_credenciais_anexos(self, log=print):
        self.garantiu = True
        if self._garante:
            self._req_anexos = CAPTURA
        return self._garante


def _nao_loga(*_a, **_k):
    raise AssertionError("login HTTP não pode acontecer")


def test_central_desligado_le_pela_aba_do_app_sem_login():
    api = ApiDaAba({"bank-accounts?": CONTAS, "balances?": SALDOS})
    contas = erp_do_dia.ler_saldos(Cfg(), api, central_ligado=lambda: False, logar=_nao_loga)
    assert [(c.id, c.balance) for c in contas] == [("uuid-alfa", Decimal("1234.56"))]
    assert api.urls and all(h["authorization"] for _u, h in api.urls)


def test_resposta_de_erro_vira_erperror_e_nunca_saldo_zero():
    api = ApiDaAba({"bank-accounts?": {"__erro": 401}})
    with pytest.raises(ErpError, match="401"):
        erp_do_dia.ler_saldos(Cfg(), api, central_ligado=lambda: False, logar=_nao_loga)


def test_sem_captura_pede_a_isca_e_sem_ela_para():
    api = ApiDaAba({"bank-accounts?": CONTAS, "balances?": SALDOS}, capturado=False)
    erp_do_dia.ler_saldos(Cfg(), api, central_ligado=lambda: False, logar=_nao_loga)
    assert api.garantiu
    with pytest.raises(ErpError):
        erp_do_dia.ler_saldos(Cfg(), ApiDaAba({}, capturado=False, garante=False),
                              central_ligado=lambda: False, logar=_nao_loga)


def test_central_ligado_usa_a_sessao_do_porteiro():
    class Sessao:
        def contas(self, *, ativas=True):
            assert ativas
            return ["conta"]
    api = ApiDaAba({})
    assert erp_do_dia.ler_saldos(Cfg(), api, central_ligado=lambda: True,
                                 logar=lambda cfg, log=print: Sessao()) == ["conta"]
    assert api.urls == []


def test_nenhuma_conta_e_erro():
    api = ApiDaAba({"bank-accounts?": {"items": [], "hasNextPage": False}})
    with pytest.raises(ErpError, match="nenhuma conta"):
        erp_do_dia.ler_saldos(Cfg(), api, central_ligado=lambda: False, logar=_nao_loga)
```
- [ ] **Passo 2:** `python -m pytest tests/test_tela_do_dia_erp.py -q`. Esperado: FALHA.
- [ ] **Passo 3: implementação**
```python
# -*- coding: utf-8 -*-
"""Os saldos do ERP pela tela do dia — SEMPRE pelo Chrome do app.

Regra do dono (14/10/2026, `erp/sessao.py:215`): nada de `POST /users/login`
por HTTP, que derruba a sessão do Chrome. Dois caminhos, nenhum com login:

- central ligado: `SessaoApi.logar` já devolve a `SessaoPelaPagina` do
  porteiro (`erp/sessao.py:219`), o mesmo caminho do "Saldo de pagamentos";
- central desligado: a MESMA aba do robô que acabou de ler os pagamentos
  (`mc_api._fetch_json`, com os cabeçalhos do `prod-erp-api` capturados da
  tela de um lançamento). A paginação e o lote de saldos continuam os do
  `SessaoApi` — esta classe só troca o transporte.

`acessos.json` estragado: `central_ligado` levanta `ErpErro` e a leitura para
(falha FECHADA). Nunca cai no login HTTP.
"""
from __future__ import annotations

from conciliacao.erp.api import SessaoApi
from conciliacao.errors import ErpError
from erp import sessao as erp_sessao


class PedirPelaAba:
    def __init__(self, api):
        self._api = api
        self.transporte = None      # `SessaoApi._pedir` escreve os dois
        self.espera = None

    def pedir(self, url: str):
        captura = getattr(self._api, "_req_anexos", None)
        if not captura:
            raise ErpError("o Chrome do app ainda não tem o acesso ao cadastro "
                           "de contas — busque de novo.")
        _base, cabecalhos = captura
        corpo = self._api._fetch_json(url, cabecalhos)
        if isinstance(corpo, dict) and corpo.get("__erro"):
            raise ErpError(f"o Mais Controle respondeu {corpo['__erro']} ao ler as "
                           "contas pela aba do app. Recarregue o Mais Controle no "
                           "Chrome do app e busque de novo.")
        return corpo


def ler_saldos(config, api, *, central_ligado=None, logar=None, log=print):
    central_ligado = central_ligado or erp_sessao.central_ligado
    logar = logar or SessaoApi.logar
    if central_ligado():
        contas = logar(config, log=log).contas(ativas=True)
    else:
        if not getattr(api, "_req_anexos", None) and not api.garantir_credenciais_anexos(log):
            raise ErpError("não consegui o acesso do Chrome do app ao cadastro de "
                           "contas. Abra um lançamento qualquer no Chrome do app e "
                           "busque de novo.")
        sessao = SessaoApi(token="", company_id="", usuario="Chrome do app",
                           empresa=None, config=config, _sessao=PedirPelaAba(api))
        contas = sessao.contas(ativas=True)
    if not contas:
        raise ErpError("o ERP não devolveu nenhuma conta bancária.")
    return contas
```
- [ ] **Passo 4:** `python -m pytest tests/test_tela_do_dia_erp.py tests/test_conciliacao_erp_api.py -q`. Esperado: PASSA.
- [ ] **Passo 5: commit** — `"Pagamentos do dia: saldos do ERP pelo Chrome do app, sem login HTTP"` + rodapé.

---

## Tarefa 7 — `pagamentos_dia/leitura_do_dia.py`: a apuração da Remessa sem tela
**Modelo sugerido:** opus (orquestra regra de dinheiro; o cancelar não pode deixar leitura pela metade com cara de inteira).

**Files:**
- Create: `pagamentos_dia/leitura_do_dia.py`, `tests/test_leitura_do_dia.py`

**Interfaces:**
```python
@dataclass class LeituraDosPagamentos:
    periodo: tuple; lancamentos: list; anexos: dict; overviews: dict; participantes: dict
    entradas: confirmacao.Entradas | None; resultado: relatorio.Resultado | None
    analise: confirmacao.AnaliseRemessa | None; grupos: list; avisos: list; interrompida: bool
def anexos_a_ler(selecionados, anexos) -> list[tuple[str, bool, bool]]        # = pagamentos_frame.py:3689
def baixar_textos(baixar, alvos, *, log=print, progresso=..., cancelar=..., ler_qr=qr_pix.ler,
                  texto_pdf=relatorio.texto_de_pdf, ocr_pdf=ocr_boleto.texto_ocr_pdf,
                  ocr_imagem=ocr_boleto.texto_ocr_imagem) -> tuple[dict, set, set, dict]   # = :3712
def ler_pagamentos(api, ini: date, fim: date, *, abrir_historico, carregar_mapas,
                   cadastro_reembolso=None, regras_fornecedor=None, destacar=(),
                   conta_entra=relatorio.conta_entra, log=print, progresso=..., cancelar=...,
                   **leitores) -> LeituraDosPagamentos
```

- [ ] **Passo 1: teste que falha**
```python
"""A leitura do dia, como a Remessa lê, sem tela. Lançamentos fictícios (o
formato é o de tests/test_regras_14_10.py)."""
from datetime import date

from pagamentos_dia import confirmacao
from pagamentos_dia import leitura_do_dia as ld
from pagamentos_dia import regras_pagamento as regras

DIA = date(2026, 10, 21)


def _lanc(ident, conta="CONTA EXEMPLO - SICOOB", **extra):
    item = {"id": ident, "tradePayableId": f"T-{ident}", "paidTo": "Fornecedor Modelo Ltda",
            "remainingValue": 100.0, "plannedDate": "2026-10-21",
            "tradePayableAccount": {"name": conta}, "tradePayablePaymentMethod": "Pix",
            "paidToBankAccount": "PIX EMAIL fornecedor@exemplo.com", "documentNumber": "1234",
            "costCentreDetails": [{"workName": "OBRA MODELO"}], "paid": False}
    item.update(extra)
    return item


def _anexo(nome, tag="Nota Fiscal", ext=".pdf"):
    return {"filename": nome, "tagName": tag, "extension": ext,
            "downloadUrl": f"https://exemplo.invalid/{nome}{ext}"}


class ApiFalsa:
    def __init__(self, lancamentos, anexos=None, arquivos=None, contatos=None):
        self._lanc, self._anexos = lancamentos, anexos or {}
        self._arq = arquivos or {}
        self._contatos = contatos
        self._req_anexos = ("https://exemplo.invalid/attachments/v2", {"authorization": "x"})
        self.titulos_sem_leitura, self.baixados, self.periodo = set(), [], None

    def capturar_credenciais(self, log=print):
        return True

    def capturar_credenciais_anexos(self, launch_id):
        return True

    def listar_a_pagar(self, ini, fim, log=print):
        self.periodo = (ini, fim)
        return list(self._lanc)

    def anexos_de_titulos(self, ids, log=print, progresso=None, cancelar=None):
        return {i: self._anexos.get(i, []) for i in ids}

    def listar_overviews(self, ids, log=print, progresso=None, cancelar=None):
        return {i: {} for i in ids}

    def listar_participantes(self, log=print):
        if isinstance(self._contatos, Exception):
            raise self._contatos
        return self._contatos or {}

    def baixar_anexo(self, url):
        self.baixados.append(url)
        return self._arq.get(url, b"%PDF-1.4 ficticio")


LEITORES = dict(ler_qr=lambda d, pdf: [], texto_pdf=lambda d: "",
                ocr_pdf=lambda d, log=print: "", ocr_imagem=lambda d: "")


def _sem_nuvem():
    raise RuntimeError("sem nuvem no teste")


def _sem_cadastro():
    raise RuntimeError("sem cadastro no teste")


def _ler(api, **k):
    return ld.ler_pagamentos(api, DIA, DIA, abrir_historico=_sem_nuvem,
                             carregar_mapas=_sem_cadastro, **LEITORES, **k)


def test_le_como_a_remessa_e_separa_quem_pode_sair():
    api = ApiFalsa([_lanc("L1"), _lanc("L2"), _lanc("L3", paid=True, sumOfPaidValues=100.0),
                    _lanc("L4", conta="PESSOA FISICA - APENAS LANCAMENTO")],
                   anexos={"T-L1": [_anexo("nota 1234")]})
    leitura = _ler(api)
    assert api.periodo == ("2026-10-21", "2026-10-21")
    assert leitura.resultado is not None and not leitura.interrompida
    linhas = [ln for g in leitura.grupos for ln in (*g.entram, *g.nao_aptos)]
    assert sorted(ln.id for ln in linhas) == ["L1", "L2"]          # pago e conta de ajuste fora
    sem_anexo = next(ln for ln in linhas if ln.id == "L2")
    assert sem_anexo.secao == confirmacao.NAO_APTO and sem_anexo.situacao == regras.MOTIVO_SEM_ANEXO
    assert any(confirmacao.AVISO_SEM_REGISTRO in a for a in leitura.avisos)
    assert any(confirmacao.AVISO_SEM_CADASTRO in a for a in leitura.avisos)


def test_baixa_cada_url_uma_vez_e_da_foto_so_le_o_qr():
    pdf, foto = _anexo("boleto"), _anexo("foto", tag="Outros", ext=".jpg")
    alvos = ld.anexos_a_ler([_lanc("L1"), _lanc("L2", tradePayableId="T-L1")], {"T-L1": [pdf, foto]})
    assert alvos == [(pdf["downloadUrl"], True, True), (foto["downloadUrl"], False, False)]
    lidos_qr = []
    textos, ocr, nao_lidos, qrs = ld.baixar_textos(
        lambda url: b"x", alvos, ler_qr=lambda d, p: lidos_qr.append(p) or ["000201PIX"],
        texto_pdf=lambda d: "texto do boleto", ocr_pdf=lambda d, log=print: "",
        ocr_imagem=lambda d: "")
    assert list(textos) == [pdf["downloadUrl"]] and lidos_qr == [True, False]
    assert set(qrs) == {pdf["downloadUrl"], foto["downloadUrl"]} and not nao_lidos and not ocr


def test_download_que_falha_vira_anexo_nao_lido():
    def baixar(url):
        raise OSError("caiu")
    _t, _o, nao_lidos, _q = ld.baixar_textos(baixar, [("u", True, True)], **LEITORES)
    assert nao_lidos == {"u"}


def test_parar_no_meio_nao_monta_resultado():
    api = ApiFalsa([_lanc("L1")], anexos={"T-L1": [_anexo("nota 1234")]})
    leitura = _ler(api, cancelar=lambda: True)
    assert leitura.interrompida and leitura.resultado is None and leitura.grupos == []


def test_contatos_que_falham_viram_aviso_e_a_leitura_segue():
    api = ApiFalsa([_lanc("L1")], anexos={"T-L1": [_anexo("nota 1234")]}, contatos=RuntimeError("401"))
    leitura = _ler(api)
    assert leitura.resultado is not None
    assert any("Contatos" in a for a in leitura.avisos)


def test_sem_lancamentos_e_resultado_vazio():
    leitura = _ler(ApiFalsa([]))
    assert leitura.resultado.contas == {} and leitura.grupos == []
```
- [ ] **Passo 2:** `python -m pytest tests/test_leitura_do_dia.py -q`. Esperado: FALHA.
- [ ] **Passo 3: implementação** — `pagamentos_dia/leitura_do_dia.py`
```python
# -*- coding: utf-8 -*-
"""A leitura do dia da Remessa, sem tela — para a aba "Pagamentos do dia".

Quem sabe o que VAI SAIR e o que está BLOQUEADO é a apuração da Remessa:
`relatorio.montar_registros` + `confirmacao.analisar_remessa` +
`confirmacao.grupos_da_confirmacao`. Reescrever uma delas seria a segunda
régua que diverge da primeira. Aqui só se ORQUESTRA, na mesma ordem do
`PagamentosDiaFrame._t_buscar` / `_juntar_entradas` / `_baixar_textos`, com o
ERP, o disco e os leitores (QR, PDF, OCR) entrando por parâmetro.

**Só leitura.** Nada reserva NSA, nada registra remessa: a análise da remessa
é a mesma da janela "Confirmar o que entra" (só pergunta "já saiu?").

**Parar no meio não monta nada** (a mesma regra do `_t_apurar`): leitura de
anexos pela metade transforma o boleto dentro da NF em Pix do cadastro.

Duplicação conhecida: as ~90 linhas de orquestração existem também no
`pagamentos_frame.py`. Quando o branch que mexe nele hoje entrar, o frame passa
a chamar `ler_pagamentos`/`baixar_textos` daqui — este teste já cobre o caminho.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import confirmacao, ocr_boleto, qr_pix, relatorio


@dataclass
class LeituraDosPagamentos:
    periodo: tuple
    lancamentos: list = field(default_factory=list)
    anexos: dict = field(default_factory=dict)
    overviews: dict = field(default_factory=dict)
    participantes: dict = field(default_factory=dict)
    entradas: "confirmacao.Entradas | None" = None
    resultado: "relatorio.Resultado | None" = None
    analise: "confirmacao.AnaliseRemessa | None" = None
    grupos: list = field(default_factory=list)
    avisos: list = field(default_factory=list)
    interrompida: bool = False


def anexos_a_ler(selecionados, anexos) -> list[tuple[str, bool, bool]]:
    """[(downloadUrl, é_pdf, ler_texto)] sem repetição — `_anexos_a_ler`."""
    vistos, urls = set(), []
    for item in selecionados:
        for f in anexos.get(str(item.get("tradePayableId"))) or []:
            url = f.get("downloadUrl")
            if not url or url in vistos:
                continue
            pdf = relatorio.eh_pdf(f)
            aviso = bool(relatorio._PAGAR_PARA.search(relatorio._rotulo(f)))
            if pdf or aviso or relatorio._e_imagem(f):
                vistos.add(url)
                urls.append((url, pdf, pdf or aviso))
    return urls


def baixar_textos(baixar, alvos, *, log=print, progresso=lambda f, t: None,
                  cancelar=lambda: False, ler_qr=qr_pix.ler,
                  texto_pdf=relatorio.texto_de_pdf,
                  ocr_pdf=ocr_boleto.texto_ocr_pdf,
                  ocr_imagem=ocr_boleto.texto_ocr_imagem):
    """({url: texto}, {urls por OCR}, {urls não lidas}, {url: [Pix]}) — `_baixar_textos`."""
    textos, urls_ocr, nao_lidos, qrs = {}, set(), set(), {}
    sem_texto, total = 0, len(alvos)
    for i, (url, eh_pdf, ler_texto) in enumerate(alvos, 1):
        if cancelar():
            log("Interrompido a pedido — a leitura dos anexos ficou incompleta.")
            break
        try:
            dados = baixar(url)
        except Exception as e:                               # noqa: BLE001
            log(f"  [!] não consegui baixar um anexo: {e}")
            dados = None
        if not dados:
            nao_lidos.add(url)
            progresso(i, total)
            continue
        codigos = ler_qr(dados, eh_pdf)
        if codigos:
            qrs[url] = codigos
        if not ler_texto:
            progresso(i, total)
            continue
        texto = texto_pdf(dados) if eh_pdf else ""
        if not texto.strip():
            texto = ocr_pdf(dados, log) if eh_pdf else ocr_imagem(dados)
            if texto.strip():
                urls_ocr.add(url)
        textos[url] = texto
        if not texto.strip():
            sem_texto += 1
        progresso(i, total)
    if urls_ocr:
        log(f"  {len(urls_ocr)} anexo(s) sem texto lidos por OCR.")
    if sem_texto:
        log(f"  {sem_texto} anexo(s) que nem o OCR conseguiu ler.")
    return textos, urls_ocr, nao_lidos, qrs


def ler_pagamentos(api, ini, fim, *, abrir_historico, carregar_mapas,
                   cadastro_reembolso=None, regras_fornecedor=None, destacar=(),
                   conta_entra=relatorio.conta_entra, log=print,
                   progresso=lambda f, t: None, cancelar=lambda: False,
                   **leitores) -> LeituraDosPagamentos:
    leitura = LeituraDosPagamentos(periodo=(ini, fim))
    if not api.capturar_credenciais(log):
        raise RuntimeError("A tela de Pagamentos não carregou a lista no Chrome.")
    brutos = api.listar_a_pagar(f"{ini:%Y-%m-%d}", f"{fim:%Y-%m-%d}", log=log)
    leitura.lancamentos = relatorio.filtrar_periodo(brutos, ini, fim, log=log)
    if not leitura.lancamentos:
        leitura.resultado = relatorio.Resultado(contas={}, omitidos=[])
        return leitura

    titulos = sorted({str(i.get("tradePayableId")) for i in leitura.lancamentos
                      if i.get("tradePayableId")})
    if not api._req_anexos:
        api.capturar_credenciais_anexos(leitura.lancamentos[0].get("id"))
    leitura.anexos = api.anexos_de_titulos(titulos, log=log, progresso=progresso,
                                           cancelar=cancelar)
    ids = [str(i.get("id")) for i in leitura.lancamentos if i.get("id")]
    leitura.overviews = api.listar_overviews(ids, log=log, progresso=progresso,
                                             cancelar=cancelar)
    try:
        leitura.participantes = api.listar_participantes(log=log)
    except Exception as e:                                   # noqa: BLE001
        leitura.participantes = {}
        leitura.avisos.append(f"não li o cadastro de Contatos ({e}): o Pix por "
                              "telefone, e-mail ou chave aleatória fica de fora da remessa")
    if cancelar():
        leitura.interrompida = True
        return leitura

    selecionados = [i for i in leitura.lancamentos
                    if conta_entra(relatorio.nome_da_conta(i))]
    a_pagar, _pagos = relatorio.separar_pagos(selecionados)
    textos, urls_ocr, nao_lidos, qrs = baixar_textos(
        api.baixar_anexo, anexos_a_ler(a_pagar, leitura.anexos), log=log,
        progresso=progresso, cancelar=cancelar, **leitores)
    if cancelar():
        leitura.interrompida = True
        return leitura

    entradas = confirmacao.Entradas(
        selecionados=a_pagar, anexos=leitura.anexos, overviews=leitura.overviews,
        textos=textos, urls_ocr=urls_ocr, cadastro_reembolso=cadastro_reembolso,
        regras_fornecedor=regras_fornecedor or {}, participantes=leitura.participantes,
        periodo=(ini, fim), anexos_nao_lidos=nao_lidos, qr_pix=qrs,
        titulos_nao_lidos=set(getattr(api, "titulos_sem_leitura", ()) or ()))
    leitura.entradas = entradas
    leitura.resultado = confirmacao.remontar(entradas)
    leitura.analise = confirmacao.analisar_remessa(
        leitura.resultado.contas, leitura.participantes,
        carregar_mapas=carregar_mapas, abrir_historico=abrir_historico)
    aviso = confirmacao.aviso_de_anexos_nao_lidos(nao_lidos)
    if aviso:
        leitura.avisos.insert(0, aviso)
    leitura.avisos.extend(leitura.analise.avisos)
    leitura.grupos = confirmacao.grupos_da_confirmacao(
        leitura.resultado, leitura.analise, a_pagar, destacar=destacar,
        fornecedores=entradas.regras_fornecedor)
    return leitura
```
- [ ] **Passo 4:** `python -m pytest tests/test_leitura_do_dia.py tests/test_confirmacao.py -q`. Esperado: PASSA. Se `montar_registros` pedir um campo a mais no lançamento fictício, copie-o do `_lanc` de `tests/test_regras_14_10.py:32-41`, sem mexer na regra.
- [ ] **Passo 5: commit** — `"Pagamentos do dia: a leitura da Remessa sem tela (leitura_do_dia)"` + rodapé.

---

## Tarefa 8 — `pagamentos.py`: vão sair × bloqueados por linha do painel
**Modelo sugerido:** sonnet.

**Files:**
- Create: `tela_do_dia/pagamentos.py`, `tests/test_tela_do_dia_pagamentos.py`

**Interfaces:**
```python
@dataclass(frozen=True) class Pagamento: id; conta_erp; favorecido; valor: Decimal; situacao; estado
    @classmethod da_linha(ln: confirmacao.Linha) -> Pagamento
@dataclass class PagamentosDaConta: rotulo; linha: int | None; vao_sair; bloqueados; liberados; a_mao; motivo_fora
    saem / a_pagar: Decimal / qtd_a_pagar / valor_bloqueado: Decimal (properties)
def por_conta(grupos, mapping) -> tuple[dict[int, PagamentosDaConta], list[PagamentosDaConta]]
def ids_que_nao_saem(grupos) -> set[str]
def totais_para_o_painel(painel: dict[int, PagamentosDaConta]) -> dict[int, tuple[Decimal, int]]
```

- [ ] **Passo 1: teste que falha**
```python
"""Pagamentos por conta: vão sair × bloqueados. Linhas fictícias."""
from decimal import Decimal as D

import pytest

from conciliacao.mapping import AccountMapping
from pagamentos_dia import confirmacao
from tela_do_dia import pagamentos as pg

MAPA = ("model_rows:\n"
        "- row: 8\n  label: Conta Alfa - Banco\n  uuid: uuid-alfa\n  erp_name: ALFA LTDA - BANCO\n"
        "- row: 9\n  label: Conta Beta - Banco\n  uuid: uuid-beta\n  erp_name: BETA LTDA - BANCO\n"
        "ignored_erp_accounts:\n- CONTA DE AJUSTE\n")


@pytest.fixture
def mapa(tmp_path):
    caminho = tmp_path / "mapping.yaml"
    caminho.write_text(MAPA, encoding="utf-8")
    return AccountMapping.load(caminho)


class _JaEnviado:
    ja_enviado = "remessa nº 7"


def _ln(secao, ident, conta, valor, candidato=None, rejeitado=False):
    return confirmacao.Linha(secao=secao, id=ident, conta=conta, valor=valor,
                             favorecido=f"Fornecedor {ident}", tipo="Pix", dados="",
                             por_onde="", vencimento=None, oc="", centro_custo="",
                             descricao="", situacao="motivo ficticio", estado="ok",
                             olhar=False, candidato=candidato, envio_rejeitado=rejeitado)


def _grupos():
    alfa = "ALFA LTDA - BANCO"
    return [
        confirmacao.Grupo(alfa, entram=[_ln("entra", "A1", alfa, 100.1),
                                        _ln("entra", "A2", alfa, 50.0, candidato=_JaEnviado()),
                                        _ln("entra", "A3", alfa, 25.0, candidato=_JaEnviado(), rejeitado=True)],
                          nao_aptos=[_ln("nao_apto", "A4", alfa, 9.99)]),
        confirmacao.Grupo("GAMA SPE - BANCO", entram=[_ln("entra", "G1", "GAMA SPE - BANCO", 10.0)], nao_aptos=[]),
        confirmacao.Grupo("CONTA DE AJUSTE", entram=[_ln("entra", "X1", "CONTA DE AJUSTE", 1.0)], nao_aptos=[]),
    ]


def test_vai_sair_e_o_que_entra_marcado_e_bloqueado_o_resto(mapa):
    painel, _fora = pg.por_conta(_grupos(), mapa)
    alfa = painel[8]
    assert [p.id for p in alfa.vao_sair] == ["A1", "A3"]        # rejeitado volta a sair
    assert [p.id for p in alfa.bloqueados] == ["A2", "A4"]      # já enviado e não apto
    assert alfa.valor_bloqueado == D("59.99")


def test_a_pagar_e_decimal_exato(mapa):
    painel, _fora = pg.por_conta(_grupos(), mapa)
    assert painel[8].a_pagar == D("125.10") and painel[8].qtd_a_pagar == 2
    assert pg.totais_para_o_painel(painel) == {8: (D("125.10"), 2)}


def test_conta_fora_do_painel_aparece_com_o_motivo(mapa):
    _painel, fora = pg.por_conta(_grupos(), mapa)
    motivos = {c.rotulo: c.motivo_fora for c in fora}
    assert motivos["GAMA SPE - BANCO"] == pg.SEM_LINHA
    assert motivos["CONTA DE AJUSTE"] == pg.FORA_POR_CONFIGURACAO


def test_liberados_e_a_mao_somam_no_a_pagar(mapa):
    painel, _ = pg.por_conta(_grupos(), mapa)
    alfa = painel[8]
    alfa.a_mao.append(pg.Pagamento("M1", "ALFA LTDA - BANCO", "Fulano Ficticio", D("30.00"), "à mão", "ok"))
    assert alfa.a_pagar == D("155.10")


def test_ids_que_nao_saem_sao_so_os_ja_enviados():
    assert pg.ids_que_nao_saem(_grupos()) == {"A2"}
```
- [ ] **Passo 2:** `python -m pytest tests/test_tela_do_dia_pagamentos.py -q`. Esperado: FALHA.
- [ ] **Passo 3: implementação**
```python
# -*- coding: utf-8 -*-
"""Passo 2 da tela do dia: por linha do painel, o que VAI SAIR e o que está
BLOQUEADO. "A pagar" = o que vai sair — deixa de ser "tudo em aberto".

Quem decide é a apuração da Remessa: vai sair = linha que ENTRA e nasce
marcada (`confirmacao.marcada_de_inicio`: o já enviado nasce desmarcado, o
rejeitado volta marcado). Bloqueado = não apto + já enviado. Conta do ERP sem
linha no painel NÃO some: vai para `fora`, com o motivo.

Ponto de extensão da entrega 2: `liberados` (bloqueado que o dono libera, com
motivo) e `a_mao` (pagamento à mão) já somam no `a_pagar`; hoje nascem vazios.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from pagamentos_dia import confirmacao

from .valores import de_float

ZERO = Decimal("0.00")
FORA_POR_CONFIGURACAO = "conta fora do painel (lista de ignoradas do mapping.yaml)"
SEM_LINHA = 'conta do ERP sem linha no painel — inclua pelo "Atualizar contas"'


@dataclass(frozen=True)
class Pagamento:
    id: str
    conta_erp: str
    favorecido: str
    valor: Decimal
    situacao: str
    estado: str

    @classmethod
    def da_linha(cls, ln) -> "Pagamento":
        return cls(id=ln.id, conta_erp=ln.conta, favorecido=ln.quem_recebe,
                   valor=de_float(ln.valor), situacao=ln.situacao, estado=ln.estado)


@dataclass
class PagamentosDaConta:
    rotulo: str
    linha: int | None
    vao_sair: list = field(default_factory=list)
    bloqueados: list = field(default_factory=list)
    liberados: list = field(default_factory=list)     # entrega 2
    a_mao: list = field(default_factory=list)         # entrega 2
    motivo_fora: str = ""

    @property
    def saem(self) -> list:
        return [*self.vao_sair, *self.liberados, *self.a_mao]

    @property
    def a_pagar(self) -> Decimal:
        return sum((p.valor for p in self.saem), ZERO)

    @property
    def qtd_a_pagar(self) -> int:
        return len(self.saem)

    @property
    def valor_bloqueado(self) -> Decimal:
        return sum((p.valor for p in self.bloqueados), ZERO)


def por_conta(grupos, mapping):
    painel: dict[int, PagamentosDaConta] = {}
    fora: dict[str, PagamentosDaConta] = {}
    for g in grupos:
        if mapping.is_ignored(g.conta):
            destino = fora.setdefault(g.conta, PagamentosDaConta(
                g.conta, None, motivo_fora=FORA_POR_CONFIGURACAO))
        else:
            row = mapping.resolve_label(g.conta)
            if row is not None and row.exists_in_erp:
                destino = painel.setdefault(row.row, PagamentosDaConta(row.label, row.row))
            else:
                destino = fora.setdefault(g.conta, PagamentosDaConta(
                    g.conta, None, motivo_fora=SEM_LINHA))
        for ln in g.entram:
            alvo = destino.vao_sair if confirmacao.marcada_de_inicio(ln) else destino.bloqueados
            alvo.append(Pagamento.da_linha(ln))
        destino.bloqueados.extend(Pagamento.da_linha(ln) for ln in g.nao_aptos)
    return painel, list(fora.values())


def ids_que_nao_saem(grupos) -> set[str]:
    """Os que ENTRAM mas nascem desmarcados (já enviados) — o que a janela da
    Remessa desmarcaria sozinha. É o `ids_nao_confirmados` do `remontar`."""
    return {ln.id for g in grupos for ln in g.entram
            if ln.id and not confirmacao.marcada_de_inicio(ln)}


def totais_para_o_painel(painel) -> dict[int, tuple[Decimal, int]]:
    """{linha: (a pagar, quantos)} — o `aggregates` do `build_row_fills`."""
    return {row: (c.a_pagar, c.qtd_a_pagar) for row, c in painel.items()}
```
- [ ] **Passo 4:** `python -m pytest tests/test_tela_do_dia_pagamentos.py -q`. Esperado: PASSA.
- [ ] **Passo 5: commit** — `"Pagamentos do dia: o que vai sair e o que está bloqueado, por conta"` + rodapé.

---

## Tarefa 9 — `aportes.py`: mínimo, sugestão, falta ratear, conta-mãe
**Modelo sugerido:** opus.

**Files:**
- Create: `tela_do_dia/aportes.py`, `tests/test_tela_do_dia_aportes.py`

**Interfaces:**
```python
@dataclass(frozen=True) class Participacao: aportador; peso: Decimal | None; tipo; do_painel: bool; linha_regra: int
@dataclass class AporteDaConta: rotulo; saldo: Decimal | None; a_pagar: Decimal; participantes: list; definidos: dict[str, Decimal]; sai: Decimal; e_mae: bool
    minimo / definido / falta_ratear / sobra / saldo_final: Decimal; sugestao: dict[str, Decimal]  (properties)
@dataclass class PainelDeAportes: contas: list[AporteDaConta]; mae: str | None; alertas: list[tuple[str, str]]; definidos_validos: dict[tuple[str, str], Decimal]
def conta_mae(regras) -> str | None
def montar_aportes(saldos: dict[str, Decimal | None], a_pagar: dict[str, Decimal], regras, definidos: dict[tuple[str, str], Decimal]) -> PainelDeAportes
```
Espelho do Painel: `G = D+E-C` (mínimo, com E = o que a conta manda para as outras) e `I = C-D-E+F`.

- [ ] **Passo 1: teste que falha**
```python
"""Aportes do dia. Contas e sócios fictícios."""
from decimal import Decimal as D

from conciliacao.aportadores import Regra
from tela_do_dia import aportes as ap

REGRAS = [
    Regra("Filha Um - Banco", "Mae - Banco", None, "Aporte", True, linha=5),
    Regra("Filha Dois - Banco", "Mae - Banco", D("2"), "Aporte", True, linha=6),
    Regra("Filha Dois - Banco", "Socio Ficticio B", D("1"), "Aporte", False, linha=7),
    Regra("Mae - Banco", "Socio Ficticio A", D("1"), "Aporte", False, linha=8),
    Regra("Mae - Banco", "Socio Ficticio B", D("1"), "Aporte", False, linha=9),
]
SALDOS = {"Mae - Banco": D("1000.00"), "Filha Um - Banco": D("100.00"),
          "Filha Dois - Banco": D("0.00"), "Sobra - Banco": D("50.00")}
A_PAGAR = {"Mae - Banco": D("500.00"), "Filha Um - Banco": D("400.00"),
           "Filha Dois - Banco": D("300.00")}


def _por(painel):
    return {c.rotulo: c for c in painel.contas}


def test_a_conta_mae_e_a_que_mais_aporta_nas_outras():
    assert ap.conta_mae(REGRAS) == "Mae - Banco"
    assert ap.conta_mae([]) is None


def test_minimo_sugestao_e_falta_ratear_sem_nada_definido():
    painel = ap.montar_aportes(SALDOS, A_PAGAR, REGRAS, {})
    assert [c.rotulo for c in painel.contas] == ["Mae - Banco", "Filha Um - Banco", "Filha Dois - Banco"]
    contas = _por(painel)
    assert contas["Filha Um - Banco"].minimo == D("300.00")
    assert contas["Filha Um - Banco"].sugestao == {}                       # sem peso, o rateio é do dono
    assert contas["Filha Dois - Banco"].sugestao == {"Mae - Banco": D("200.00"), "Socio Ficticio B": D("100.00")}
    assert contas["Filha Dois - Banco"].falta_ratear == D("300.00")
    assert contas["Mae - Banco"].minimo == D("0.00") and contas["Mae - Banco"].saldo_final == D("500.00")


def test_o_que_a_mae_manda_entra_no_minimo_e_no_saldo_final_dela():
    definidos = {("Filha Um - Banco", "Mae - Banco"): D("300.00"),
                 ("Filha Dois - Banco", "Mae - Banco"): D("200.00"),
                 ("Filha Dois - Banco", "Socio Ficticio B"): D("100.00")}
    contas = _por(ap.montar_aportes(SALDOS, A_PAGAR, REGRAS, definidos))
    assert contas["Mae - Banco"].sai == D("500.00")
    assert contas["Mae - Banco"].saldo_final == D("0.00")
    assert contas["Filha Dois - Banco"].falta_ratear == D("0.00")
    assert contas["Filha Dois - Banco"].saldo_final == D("0.00")


def test_mae_negativa_da_alerta_forte_e_sobra_aparece():
    painel = ap.montar_aportes(SALDOS, A_PAGAR, REGRAS, {("Filha Um - Banco", "Mae - Banco"): D("800.00")})
    contas = _por(painel)
    assert contas["Mae - Banco"].saldo_final == D("-300.00")
    assert contas["Filha Um - Banco"].sobra == D("500.00")
    fortes = [f for tag, f in painel.alertas if tag == "erro"]
    assert len(fortes) == 1 and "Mae - Banco" in fortes[0] and "NEGATIVA" in fortes[0]


def test_valor_de_quem_nao_esta_na_aba_regras_nao_conta_e_avisa():
    painel = ap.montar_aportes(SALDOS, A_PAGAR, REGRAS, {("Filha Um - Banco", "Intruso Ficticio"): D("10.00")})
    assert painel.definidos_validos == {}
    assert any("Intruso Ficticio" in f for _t, f in painel.alertas)


def test_peso_zero_nao_quebra_so_nao_sugere():
    regras = [Regra("Filha Um - Banco", "Mae - Banco", D("0"), "Aporte", True, linha=5)]
    assert _por(ap.montar_aportes(SALDOS, A_PAGAR, regras, {}))["Filha Um - Banco"].sugestao == {}
```
- [ ] **Passo 2:** `python -m pytest tests/test_tela_do_dia_aportes.py -q`. Esperado: FALHA.
- [ ] **Passo 3: implementação**
```python
# -*- coding: utf-8 -*-
"""Passo 3 da tela do dia: aporte mínimo por conta, quem põe e quanto.

O espelho é o das fórmulas do Painel (ver `conciliacao/panel.py`):
mínimo G = D + E − C (E = o que a conta MANDA para as outras), saldo final
I = C − D − E + F (F = o que entra). A regra (aba «Regras») SUGERE, só quando
todo participante tem peso (peso em branco = "o rateio é seu"); o dono digita
o valor POR aportador. A conta-mãe — a que aporta em mais contas — vem primeiro
e fechar negativa nela é alerta forte: é dela que sai o dinheiro das outras.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from aportes.regras import dividir_por_peso

from .valores import brl

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Participacao:
    aportador: str
    peso: Decimal | None
    tipo: str
    do_painel: bool
    linha_regra: int


@dataclass
class AporteDaConta:
    rotulo: str
    saldo: Decimal | None
    a_pagar: Decimal
    participantes: list = field(default_factory=list)
    definidos: dict = field(default_factory=dict)
    sai: Decimal = ZERO
    e_mae: bool = False

    @property
    def minimo(self) -> Decimal:
        falta = self.a_pagar + self.sai - (self.saldo or ZERO)
        return falta if falta > ZERO else ZERO

    @property
    def definido(self) -> Decimal:
        return sum(self.definidos.values(), ZERO)

    @property
    def falta_ratear(self) -> Decimal:
        return max(ZERO, self.minimo - self.definido)

    @property
    def sobra(self) -> Decimal:
        return max(ZERO, self.definido - self.minimo)

    @property
    def saldo_final(self) -> Decimal:
        return (self.saldo or ZERO) - self.a_pagar - self.sai + self.definido

    @property
    def sugestao(self) -> dict:
        if self.minimo <= ZERO or not self.participantes:
            return {}
        if any(p.peso is None for p in self.participantes):
            return {}
        nomes = [p.aportador for p in self.participantes]
        try:
            partes = dividir_por_peso(self.minimo, nomes,
                                      {p.aportador: p.peso for p in self.participantes})
        except ValueError:
            return {}
        return dict(zip(nomes, partes))


@dataclass
class PainelDeAportes:
    contas: list
    mae: str | None
    alertas: list
    definidos_validos: dict


def conta_mae(regras) -> str | None:
    destinos: dict[str, set] = {}
    for r in regras:
        if r.do_painel:
            destinos.setdefault(r.aportador, set()).add(r.destino)
    if not destinos:
        return None
    return max(destinos, key=lambda a: len(destinos[a]))   # empate: o primeiro da aba


def montar_aportes(saldos, a_pagar, regras, definidos) -> PainelDeAportes:
    participantes: dict[str, list] = {}
    for r in regras:
        participantes.setdefault(r.destino, []).append(
            Participacao(r.aportador, r.peso, r.tipo, r.do_painel, r.linha))
    alertas: list[tuple[str, str]] = []
    validos = {}
    for (destino, aportador), valor in definidos.items():
        if not valor:
            continue
        if any(p.aportador == aportador for p in participantes.get(destino, ())):
            validos[(destino, aportador)] = valor
        else:
            alertas.append(("atencao", f"{aportador} → {destino}: não está na aba "
                                       f"Regras; o valor {brl(valor)} foi ignorado"))
    sai: dict[str, Decimal] = defaultdict(lambda: ZERO)
    por_destino: dict[str, dict] = defaultdict(dict)
    for (destino, aportador), valor in validos.items():
        sai[aportador] += valor
        por_destino[destino][aportador] = valor
    mae = conta_mae(regras)
    contas = []
    for rotulo in dict.fromkeys([*saldos, *a_pagar]):
        c = AporteDaConta(rotulo=rotulo, saldo=saldos.get(rotulo),
                          a_pagar=a_pagar.get(rotulo, ZERO),
                          participantes=participantes.get(rotulo, []),
                          definidos=dict(por_destino.get(rotulo, {})),
                          sai=sai.get(rotulo, ZERO), e_mae=(rotulo == mae))
        if c.e_mae or c.minimo > ZERO or c.definidos:
            contas.append(c)
    contas.sort(key=lambda c: not c.e_mae)                  # estável: mãe primeiro
    for c in contas:
        if c.saldo_final < ZERO:
            if c.e_mae:
                alertas.insert(0, ("erro", f"A CONTA-MÃE {c.rotulo} FECHA NEGATIVA: "
                                           f"{brl(c.saldo_final)}. Ela manda {brl(c.sai)} "
                                           "para as outras — reveja os aportes."))
            else:
                alertas.append(("atencao", f"{c.rotulo} fecha negativa: {brl(c.saldo_final)}"))
        if c.falta_ratear > ZERO:
            if not c.participantes:
                alertas.append(("atencao", f"{c.rotulo}: precisa de {brl(c.minimo)} e a "
                                           "aba Regras não diz quem aporta"))
            else:
                alertas.append(("atencao", f"{c.rotulo}: falta ratear {brl(c.falta_ratear)}"))
    return PainelDeAportes(contas=contas, mae=mae, alertas=alertas,
                           definidos_validos=validos)
```
- [ ] **Passo 4:** `python -m pytest tests/test_tela_do_dia_aportes.py tests/test_aportes_regras.py -q`. Esperado: PASSA.
- [ ] **Passo 5: commit** — `"Pagamentos do dia: aportes por aportador, conta-mãe primeiro e alerta forte"` + rodapé.

---

## Tarefa 10 — `excel_do_dia.py`: o MODELO do dia com os números da tela
**Modelo sugerido:** sonnet.

**Files:**
- Create: `tela_do_dia/excel_do_dia.py`, `tests/test_tela_do_dia_excel.py`

**Interfaces:**
```python
ABA_MOVIMENTACOES = "Movimentações"; COLUNA_DEFINIDO = "H"; CABECALHO_MOVIMENTACOES = "H7"
def linhas_da_movimentacao(ws) -> dict[int, int]            # {linha da Regras: linha da Movimentações}
def celulas_de_aporte(modelo, planilha, mapping, regras, definidos) -> dict[str, dict[str, float]]
def gerar(*, modelo, destino, data, mapping, planilha, saldos: dict[int, Decimal | None],
          a_pagar: dict[int, tuple[Decimal, int]], regras, definidos) -> BuildResult
```

- [ ] **Passo 1: teste que falha**
```python
"""O Excel do dia a partir da tela. Modelo fictício que imita o real: a linha
da «Movimentações» sai da fórmula, não de um deslocamento fixo."""
from datetime import date
from decimal import Decimal as D

import openpyxl
import pytest

from conciliacao.aportadores import ler_regras
from conciliacao.config import PlanilhaConfig
from conciliacao.mapping import AccountMapping
from conciliacao.workbook import WorkbookError
from tela_do_dia import excel_do_dia as xd

HOJE = date(2026, 10, 21)
ROTULOS = ("Conta Alfa - Banco", "Conta Beta - Banco", "Conta Gama - Banco")
PLANILHA = PlanilhaConfig(
    aba="Painel", primeira_linha=8, ultima_linha=10, linha_totais=12, ultima_coluna="M",
    celula_data="E4", celula_total_pagamentos="D12", formato_data="DD/MM/YYYY",
    col_saldo="C", col_pagamento="D", col_qtd_sistema="J", col_qtd_banco="K",
    colunas_formula=("E", "F", "G", "I", "L"))
MAPA = ("model_rows:\n"
        "- row: 8\n  label: Conta Alfa - Banco\n  uuid: uuid-alfa\n"
        "- row: 9\n  label: Conta Beta - Banco\n  uuid: uuid-beta\n"
        "- row: 10\n  label: Conta Gama - Banco\n  uuid: uuid-gama\n")


@pytest.fixture
def mapa(tmp_path):
    caminho = tmp_path / "mapping.yaml"
    caminho.write_text(MAPA, encoding="utf-8")
    return AccountMapping.load(caminho)


def _modelo(caminho, cabecalho_mov="VALOR\nDEFINIDO (R$)"):
    wb = openpyxl.Workbook()
    p = wb.active
    p.title = "Painel"
    mov = wb.create_sheet("Movimentações")
    reg = wb.create_sheet("Regras")
    p["H7"] = "APORTE\nDEFINIDO (R$)"
    for r, rotulo in zip((8, 9, 10), ROTULOS):
        p[f"B{r}"] = rotulo
        p[f"G{r}"] = f'=IF($C{r}>=$D{r}+$E{r},"—",$D{r}+$E{r}-$C{r})'
    mov["H7"] = cabecalho_mov
    for linha_mov, linha_regra in ((9, 5), (10, 6), (13, 7)):
        mov[f"B{linha_mov}"] = f'=IF(Regras!$C{linha_regra}="","",Regras!$C{linha_regra})'
        mov[f"I{linha_mov}"] = f'=IF($H{linha_mov}<>"",$H{linha_mov},"")'
    mov["B12"] = "2 · O QUE OS INVESTIDORES MANDAM"
    for linha, (destino, aportador, painel) in zip((5, 6, 7), (
            ("Conta Alfa - Banco", "Conta Beta - Banco", "sim"),
            ("Conta Gama - Banco", "Conta Beta - Banco", "sim"),
            ("Conta Alfa - Banco", "Socio Ficticio", "não"))):
        reg[f"B{linha}"], reg[f"C{linha}"] = destino, aportador
        reg[f"E{linha}"], reg[f"F{linha}"] = "Aporte", painel
    wb.save(caminho)
    return caminho


def _gerar(tmp_path, mapa, definidos, **k):
    modelo = _modelo(tmp_path / "MODELO.xlsx", **k)
    destino = tmp_path / "saida" / "21 10 - completa.xlsx"
    xd.gerar(modelo=modelo, destino=destino, data=HOJE, mapping=mapa, planilha=PLANILHA,
             saldos={8: D("100.50"), 9: D("-20.00"), 10: None},
             a_pagar={8: (D("300.00"), 2)}, regras=ler_regras(modelo), definidos=definidos)
    return openpyxl.load_workbook(destino)


def test_linhas_da_movimentacao_saem_da_formula(tmp_path):
    ws = openpyxl.load_workbook(_modelo(tmp_path / "M.xlsx"))["Movimentações"]
    assert xd.linhas_da_movimentacao(ws) == {5: 9, 6: 10, 7: 13}


def test_o_excel_do_dia_leva_os_numeros_da_tela(tmp_path, mapa):
    wb = _gerar(tmp_path, mapa, {("Conta Alfa - Banco", "Socio Ficticio"): D("199.50")})
    p, mov = wb["Painel"], wb["Movimentações"]
    assert p["E4"].value.date() == HOJE
    assert (p["C8"].value, p["D8"].value, p["J8"].value, p["K8"].value) == (100.5, 300, 2, None)
    assert (p["C9"].value, p["D9"].value, p["K9"].value) == (-20, 0, 0)
    assert p["C10"].value is None
    assert p["H8"].value == 199.5 and p["H9"].value is None
    assert mov["H13"].value == 199.5
    # Participante da MESMA conta sem valor leva ZERO: vazio faria a coluna I
    # cair no VALOR SUGERIDO e somar dinheiro que ninguém definiu.
    assert mov["H9"].value == 0
    assert mov["H10"].value is None                     # regra de outra conta
    assert p["G8"].value.startswith("=IF(")             # fórmula preservada


def test_so_numero_e_escrito(tmp_path, mapa):
    modelo = _modelo(tmp_path / "MODELO.xlsx")
    extras = xd.celulas_de_aporte(modelo, PLANILHA, mapa, ler_regras(modelo),
                                  {("Conta Alfa - Banco", "Socio Ficticio"): D("1.00")})
    assert all(isinstance(v, float) for celulas in extras.values() for v in celulas.values())


@pytest.mark.parametrize("definidos, trecho", [
    ({("Conta Gama - Banco", "Socio Ficticio"): D("10")}, "Regras"),
    ({("Conta Alfa - Banco", "Socio Ficticio"): D("-1")}, "negativo"),
])
def test_recusa_o_que_nao_tem_lugar_no_modelo(tmp_path, mapa, definidos, trecho):
    with pytest.raises(WorkbookError, match=trecho):
        _gerar(tmp_path, mapa, definidos)


def test_cabecalho_mudado_para_tudo(tmp_path, mapa):
    with pytest.raises(WorkbookError, match="VALOR DEFINIDO"):
        _gerar(tmp_path, mapa, {("Conta Alfa - Banco", "Socio Ficticio"): D("1")},
               cabecalho_mov="VALOR (R$)")
```
- [ ] **Passo 2:** `python -m pytest tests/test_tela_do_dia_excel.py -q`. Esperado: FALHA.
- [ ] **Passo 3: implementação**
```python
# -*- coding: utf-8 -*-
"""Passo 4 da tela do dia: o MODELO.xlsx do dia com os números da TELA.

Escreve o que o painel antigo escrevia (data, C saldo do dia, D a pagar, J/K)
e mais o que antes era digitado à mão: o APORTE DEFINIDO (Painel H) e o VALOR
DEFINIDO de cada aportador (Movimentações H). Só número — nenhuma fórmula
digitada —, e o `workbook.build` confere o resto célula por célula.

A linha da «Movimentações» de cada regra sai da FÓRMULA da coluna B
(`Regras!$C<n>`): no modelo real há linhas vazias e um título entre as seções,
e "linha da regra + 4" erraria a partir da seção 2.

Participante de uma conta com aporte e sem valor leva 0: célula vazia faria
`I = IF(H<>"",H,G)` cair no VALOR SUGERIDO e somar dinheiro que ninguém definiu.
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import openpyxl

from conciliacao.rules import build_row_fills
from conciliacao.workbook import BuildResult, WorkbookError, build

ABA_MOVIMENTACOES = "Movimentações"
COLUNA_DEFINIDO = "H"
CABECALHO_MOVIMENTACOES = "H7"
ZERO = Decimal("0.00")
_REGRA_NA_FORMULA = re.compile(r"Regras!\$?C\$?(\d+)", re.IGNORECASE)


def linhas_da_movimentacao(ws) -> dict[int, int]:
    mapa = {}
    for (celula,) in ws.iter_rows(min_col=2, max_col=2):
        m = _REGRA_NA_FORMULA.search(str(celula.value or ""))
        if m:
            mapa[int(m.group(1))] = celula.row
    return mapa


def _conferir_cabecalho(ws, coord: str, oque: str) -> None:
    if "DEFINIDO" not in str(ws[coord].value or "").upper():
        raise WorkbookError(
            f"{ws.title}!{coord} devia ser o {oque} e é {ws[coord].value!r}: o modelo "
            "mudou — não escrevo valor numa coluna que não sei qual é.")


def celulas_de_aporte(modelo, planilha, mapping, regras, definidos) -> dict:
    validos = {par: valor for par, valor in definidos.items() if valor}
    if not validos:
        return {}
    for (destino, aportador), valor in validos.items():
        if valor < 0:
            raise WorkbookError(f"aporte negativo de {aportador} para {destino}: {valor}")
    wb = openpyxl.load_workbook(Path(modelo))
    try:
        if planilha.aba not in wb.sheetnames or ABA_MOVIMENTACOES not in wb.sheetnames:
            raise WorkbookError(f"o modelo precisa das abas {planilha.aba!r} e "
                                f"{ABA_MOVIMENTACOES!r}; encontrei {wb.sheetnames}")
        _conferir_cabecalho(wb[planilha.aba],
                            f"{COLUNA_DEFINIDO}{planilha.primeira_linha - 1}",
                            "APORTE DEFINIDO")
        _conferir_cabecalho(wb[ABA_MOVIMENTACOES], CABECALHO_MOVIMENTACOES,
                            "VALOR DEFINIDO")
        linhas_mov = linhas_da_movimentacao(wb[ABA_MOVIMENTACOES])
    finally:
        wb.close()

    regras_do_par = {(r.destino, r.aportador) for r in regras}
    linha_do_rotulo = {r.label: r.row for r in mapping.rows}
    totais: dict[str, Decimal] = {}
    for (destino, aportador), valor in validos.items():
        if (destino, aportador) not in regras_do_par:
            raise WorkbookError(f"{aportador} → {destino} não está na aba «Regras» do "
                                "modelo: não sei em que linha da «Movimentações» escrever.")
        totais[destino] = totais.get(destino, ZERO) + valor

    painel, mov = {}, {}
    for destino, total in totais.items():
        row = linha_do_rotulo.get(destino)
        if row is None or row not in planilha.linhas:
            raise WorkbookError(f"{destino!r} não é uma linha do painel.")
        painel[f"{COLUNA_DEFINIDO}{row}"] = float(total)
        for regra in regras:
            if regra.destino != destino:
                continue
            linha_mov = linhas_mov.get(regra.linha)
            if linha_mov is None:
                raise WorkbookError(f"a regra da linha {regra.linha} da aba «Regras» não "
                                    f"tem linha na «{ABA_MOVIMENTACOES}».")
            mov[f"{COLUNA_DEFINIDO}{linha_mov}"] = float(
                validos.get((destino, regra.aportador), ZERO))
    return {planilha.aba: painel, ABA_MOVIMENTACOES: mov}


def gerar(*, modelo, destino, data, mapping, planilha, saldos, a_pagar, regras,
          definidos) -> BuildResult:
    extras = celulas_de_aporte(modelo, planilha, mapping, regras, definidos)
    fills = build_row_fills(mapping, saldos, a_pagar)
    return build(modelo, destino, data, fills, mapping, planilha, extras=extras)
```
- [ ] **Passo 4:** `python -m pytest tests/test_tela_do_dia_excel.py tests/test_workbook_extras.py -q`. Esperado: PASSA.
- [ ] **Passo 5: commit** — `"Pagamentos do dia: Excel do dia com saldo, a pagar e aportes da tela"` + rodapé.

---

## Tarefa 11 — Pontes: `para_aportes.py`, `AportesFrame.receber_operacoes`, `PagamentosDiaFrame.receber_apuracao`
**Modelo sugerido:** opus (dinheiro indo para outra aba; duplicidade; divisão da subconta).

**Files:**
- Create: `tela_do_dia/para_aportes.py`, `tests/test_tela_do_dia_para_aportes.py`, `tests/test_aportes_receber_operacoes.py`, `tests/test_remessa_receber_apuracao.py`
- Modify: `aportes/aportes_frame.py:312-346`. O `_adicionar` passa a chamar `_acrescentar`, e entram dois métodos novos.
- Modify: `pagamentos_dia/pagamentos_frame.py`. Um método NOVO no FIM da classe `PagamentosDiaFrame`, sem tocar em mais nada.

**Interfaces:**
```python
# tela_do_dia/para_aportes.py
@dataclass(frozen=True) class Pendente: destino: str; aportador: str; valor: Decimal; motivo: str
@dataclass class Envio: itens: list[tuple[Operacao, list[str]]]; pendentes: list[Pendente]
def nome_no_cadastro(rotulo: str, entidades: dict) -> str | None
def chave_de_envio(destino: str, aportador: str, valor: Decimal) -> str
def operacoes(definidos, regras, entidades, subcontas, data, enviados=()) -> Envio
# aportes/aportes_frame.py
def receber_operacoes(self, ops) -> list[tuple[int, str]]      # (índice, motivo) das recusadas
def _acrescentar(self, op) -> None
# pagamentos_dia/pagamentos_frame.py
def receber_apuracao(self, leitura, desmarcados=()) -> None
```

- [ ] **Passo 1: testes que falham**

`tests/test_tela_do_dia_para_aportes.py`:
```python
"""Da tela do dia para a aba Aportes. Cadastro fictício."""
from datetime import date
from decimal import Decimal as D

from aportes.regras import TIPO_INVESTIDOR
from conciliacao.aportadores import Regra
from tela_do_dia import para_aportes as pa

HOJE = date(2026, 10, 21)
ENTIDADES = {
    "MAE - BANCO": {"nome_oficial": "MAE FICTICIA LTDA", "conta": "MAE - BANCO", "nome_descricao": None},
    "FILHA UM - BANCO": {"nome_oficial": "FILHA UM LTDA", "conta": "FILHA UM - BANCO", "nome_descricao": None},
    "SOCIO FICTICIO A": {"nome_oficial": "SOCIO FICTICIO A", "conta": None, "nome_descricao": None},
    "HOLDING - SUBCONTA 33333-3": {"nome_oficial": "HOLDING FICTICIA", "conta": "HOLDING - SUBCONTA 33.333-3",
                                   "nome_descricao": None},
}
SUBCONTAS = {"33333-3": {"obras": ["OBRA MODELO"], "investidores": ["INVESTIDOR X", "INVESTIDOR Y"],
                         "pesos": {"INVESTIDOR X": 1, "INVESTIDOR Y": 1}}}
REGRAS = [
    Regra("Filha Um - Banco", "Mae - Banco", None, "Aporte", True, linha=5),
    Regra("Mae - Banco", "Socio Ficticio A", None, "Aporte", False, linha=6),
    Regra("Holding - Subconta 33333-3", "INVESTIDOR X", None, "Aporte", False, linha=7),
    Regra("Holding - Subconta 33333-3", "INVESTIDOR Y", None, "Aporte", False, linha=8),
    Regra("Filha Um - Banco", "Desconhecido Ficticio", None, "Aporte", False, linha=9),
]


def _envio(definidos, enviados=()):
    return pa.operacoes(definidos, REGRAS, ENTIDADES, SUBCONTAS, HOJE, enviados=enviados)


def test_conta_do_painel_para_conta_do_painel_e_pagamento_mais_recebimento():
    envio = _envio({("Filha Um - Banco", "Mae - Banco"): D("300.00")})
    (op, chaves), = envio.itens
    assert (op.pagador, op.recebedor, op.valor, op.tipo, op.modo) == (
        "MAE - BANCO", "FILHA UM - BANCO", D("300.00"), "Aporte de Capital", "Pagamento + Recebimento")
    assert chaves == [pa.chave_de_envio("Filha Um - Banco", "Mae - Banco", D("300.00"))]
    assert op.validar(ENTIDADES, SUBCONTAS) == []


def test_socio_pessoa_fisica_e_so_recebimento():
    (op, _), = _envio({("Mae - Banco", "Socio Ficticio A"): D("50.00")}).itens
    assert op.modo == "Só recebimento"


def test_nome_que_o_cadastro_nao_tem_vira_pendencia_e_nunca_chute():
    envio = _envio({("Filha Um - Banco", "Desconhecido Ficticio"): D("10.00")})
    assert envio.itens == [] and "não achei" in envio.pendentes[0].motivo


def test_subconta_de_investidor_vira_uma_operacao_quando_a_divisao_bate():
    (op, chaves), = _envio({("Holding - Subconta 33333-3", "INVESTIDOR X"): D("500.00"),
                            ("Holding - Subconta 33333-3", "INVESTIDOR Y"): D("500.00")}).itens
    assert (op.pagador, op.recebedor, op.valor, op.tipo, op.modo) == (
        "INVESTIDOR SUBCONTA 33333-3", "HOLDING - SUBCONTA 33333-3", D("1000.00"),
        TIPO_INVESTIDOR, "Só recebimento")
    assert len(chaves) == 2 and op.validar(ENTIDADES, SUBCONTAS) == []


def test_subconta_com_divisao_diferente_do_cadastro_vira_pendencia():
    envio = _envio({("Holding - Subconta 33333-3", "INVESTIDOR X"): D("600.00"),
                    ("Holding - Subconta 33333-3", "INVESTIDOR Y"): D("400.00")})
    assert envio.itens == [] and len(envio.pendentes) == 2
    assert all("divisão" in p.motivo for p in envio.pendentes)


def test_o_que_ja_foi_mandado_nao_vai_de_novo():
    chave = pa.chave_de_envio("Filha Um - Banco", "Mae - Banco", D("300.00"))
    envio = _envio({("Filha Um - Banco", "Mae - Banco"): D("300.00")}, enviados={chave})
    assert envio.itens == [] and "já mandado" in envio.pendentes[0].motivo
```
`tests/test_aportes_receber_operacoes.py`:
```python
"""`AportesFrame.receber_operacoes` sem abrir janela: o método é chamado sobre
um dublê com o mesmo estado que a aba guarda. Cadastro fictício."""
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

from aportes.aportes_frame import AportesFrame
from aportes.regras import Operacao

ENTIDADES = {"MAE - BANCO": {"nome_oficial": "MAE LTDA", "conta": "MAE - BANCO"},
             "FILHA - BANCO": {"nome_oficial": "FILHA LTDA", "conta": "FILHA - BANCO"}}


def _aba(travada=False):
    linhas = []
    f = SimpleNamespace(entidades=ENTIDADES, subcontas={}, operacoes=[], criados=[],
                        incertos=[], assinaturas=[], linhas=linhas,
                        tabela=SimpleNamespace(insert=lambda *a, **k: linhas.append(k["values"])))
    f._lista_travada = lambda: travada
    f._atualizar_total = lambda: None
    f._acrescentar = lambda op: AportesFrame._acrescentar(f, op)
    return f


def _op(valor="10,00", pagador="MAE - BANCO"):
    return Operacao(data=date(2026, 10, 21), pagador=pagador, recebedor="FILHA - BANCO",
                    valor=D(valor.replace(",", ".")), tipo="Aporte de Capital",
                    modo="Pagamento + Recebimento")


def test_aceita_a_valida_e_recusa_a_invalida_com_motivo():
    aba = _aba()
    recusas = AportesFrame.receber_operacoes(aba, [_op(), _op(pagador="NINGUEM")])
    assert len(aba.operacoes) == 1 and len(aba.criados) == len(aba.incertos) == len(aba.assinaturas) == 1
    assert recusas == [(1, "Pagador desconhecido: NINGUEM")]


def test_operacao_igual_a_uma_da_lista_e_recusada():
    aba = _aba()
    AportesFrame.receber_operacoes(aba, [_op()])
    assert AportesFrame.receber_operacoes(aba, [_op()]) == [(0, "já está na lista A lançar")]
    assert len(aba.operacoes) == 1


def test_lista_travada_recusa_tudo():
    aba = _aba(travada=True)
    assert [i for i, _m in AportesFrame.receber_operacoes(aba, [_op(), _op("20,00")])] == [0, 1]
    assert aba.operacoes == []
```
`tests/test_remessa_receber_apuracao.py`:
```python
"""A Remessa recebe a leitura da tela do dia: o que não sai não vai para a
remessa. Dublê no lugar da janela; lançamentos fictícios."""
import queue
from datetime import date
from types import SimpleNamespace

from pagamentos_dia import confirmacao, leitura_do_dia
from pagamentos_dia import regras_pagamento as regras
from pagamentos_dia.pagamentos_frame import PagamentosDiaFrame

DIA = date(2026, 10, 21)


def _lanc(ident):
    return {"id": ident, "tradePayableId": f"T-{ident}", "paidTo": "Fornecedor Modelo Ltda",
            "remainingValue": 100.0, "plannedDate": "2026-10-21",
            "tradePayableAccount": {"name": "CONTA EXEMPLO - SICOOB"},
            "tradePayablePaymentMethod": "Pix", "paidToBankAccount": "PIX EMAIL f@exemplo.com",
            "documentNumber": "1234", "costCentreDetails": [{"workName": "OBRA MODELO"}], "paid": False}


class _Var:
    def __init__(self):
        self.valor = ""

    def set(self, v):
        self.valor = v


def test_receber_apuracao_poe_em_memoria_so_o_que_sai_e_abre_a_remessa():
    anexo = lambda n: {"filename": n, "tagName": "Nota Fiscal", "extension": ".pdf",  # noqa: E731
                       "downloadUrl": f"https://exemplo.invalid/{n}.pdf"}
    entradas = confirmacao.Entradas(
        selecionados=[_lanc("L1"), _lanc("L2")], anexos={"T-L1": [anexo("n1")], "T-L2": [anexo("n2")]},
        overviews={}, textos={}, urls_ocr=set(), cadastro_reembolso=None,
        regras_fornecedor={}, participantes={}, periodo=(DIA, DIA))
    leitura = leitura_do_dia.LeituraDosPagamentos(
        periodo=(DIA, DIA), lancamentos=entradas.selecionados, anexos=entradas.anexos,
        entradas=entradas)
    gerou = []
    aba = SimpleNamespace(worker=None, q=queue.Queue(), v_ini=_Var(), v_fim=_Var(),
                          _log=lambda m="": None, gerar_remessa=lambda: gerou.append(True))
    PagamentosDiaFrame.receber_apuracao(aba, leitura, {"L2"})
    ids = [r["id"] for regs in aba.resultado.contas.values() for r in regs]
    assert ids == ["L1"]
    assert any(o["motivo"] == regras.MOTIVO_NAO_CONFIRMADO for o in aba.resultado.omitidos)
    assert aba._periodo_do_resultado == aba._periodo_da_busca == (DIA, DIA)
    assert aba.v_ini.valor == "21/10/2026" and gerou == [True]
```
- [ ] **Passo 2:** `python -m pytest tests/test_tela_do_dia_para_aportes.py tests/test_aportes_receber_operacoes.py tests/test_remessa_receber_apuracao.py -q`. Esperado: FALHA.
- [ ] **Passo 3: implementação**

`tela_do_dia/para_aportes.py`:
```python
# -*- coding: utf-8 -*-
"""Os aportes definidos na tela do dia viram operações da aba Aportes.

Nada vai ao ERP daqui: as operações entram na lista "A lançar" e o dono confere
e clica "Lançar no Mais Controle" lá, como sempre. Três regras de dinheiro:

- **nome não se chuta.** O rótulo da aba Regras e o cadastro da aba Aportes
  (`contas.csv`) são vocabulários diferentes; casa por `normalize_name`
  (sem acento, caixa ou pontuação) ou pelo NÚMERO da conta, e só com UM
  candidato. Sobrou dúvida, vira pendência;
- **subconta de investidor é UMA operação** ("INVESTIDOR SUBCONTA 00000-0"),
  porque a aba Aportes rateia pelo `subcontas.json`. Se a divisão digitada não
  for a do cadastro, é pendência — a outra aba lançaria a dela, não a sua;
- **o que já foi mandado hoje não vai de novo** sem o dono pedir (a chave
  guarda conta, aportador e valor). Aporte em dobro se desfaz à mão no ERP.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import util
from aportes.dados import INVESTIDOR_PREFIXO
from aportes.regras import (TIPO_INVESTIDOR, Operacao, como_dinheiro,
                            dividir_por_peso, e_da_subconta, numero_da_conta)
from conciliacao.parsing import normalize_name

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Pendente:
    destino: str
    aportador: str
    valor: Decimal
    motivo: str


@dataclass
class Envio:
    itens: list = field(default_factory=list)       # [(Operacao, [chave_de_envio])]
    pendentes: list = field(default_factory=list)


def chave_de_envio(destino: str, aportador: str, valor) -> str:
    return f"{destino}|{aportador}|{como_dinheiro(valor):.2f}"


def nome_no_cadastro(rotulo: str, entidades: dict) -> str | None:
    alvo = normalize_name(rotulo)
    if not alvo:
        return None
    iguais = [n for n, d in entidades.items()
              if alvo in (normalize_name(n), normalize_name((d or {}).get("nome_oficial") or ""))]
    if len(iguais) == 1:
        return iguais[0]
    if iguais:
        return None
    numero = numero_da_conta(rotulo)
    if not numero:
        return None
    pelo_numero = [n for n, d in entidades.items() if e_da_subconta(n, d or {}, numero)]
    return pelo_numero[0] if len(pelo_numero) == 1 else None


def _tipo(tipo_regra: str) -> str:
    t = util.sem_acento(tipo_regra or "Aporte").casefold().strip()
    if t.startswith("aporte"):
        return "Aporte de Capital"
    if t.startswith("distribui"):
        return "Distribuição de Lucro"
    return ""


def _modo(pagador: str, recebedor: str, entidades: dict) -> str:
    if (entidades[pagador] or {}).get("conta") is None:
        return "Só recebimento"
    if (entidades[recebedor] or {}).get("conta") is None:
        return "Só pagamento"
    return "Pagamento + Recebimento"


def operacoes(definidos, regras, entidades, subcontas, data, enviados=()) -> Envio:
    envio = Envio()
    regra_do_par = {(r.destino, r.aportador): r for r in regras}
    da_subconta: dict[tuple[str, str], dict] = {}

    def pendente(destino, aportador, valor, motivo):
        envio.pendentes.append(Pendente(destino, aportador, valor, motivo))

    for (destino, aportador), valor in definidos.items():
        if not valor or valor <= 0:
            continue
        if chave_de_envio(destino, aportador, valor) in enviados:
            pendente(destino, aportador, valor, "já mandado para a aba Aportes hoje — "
                                                "confira lá antes de mandar de novo")
            continue
        regra = regra_do_par.get((destino, aportador))
        if regra is None:
            pendente(destino, aportador, valor, "não está na aba Regras do modelo")
            continue
        numero = numero_da_conta(destino)
        if numero and numero in subcontas and not regra.do_painel:
            da_subconta.setdefault((destino, numero), {})[aportador] = valor
            continue
        tipo = _tipo(regra.tipo)
        pagador, recebedor = nome_no_cadastro(aportador, entidades), nome_no_cadastro(destino, entidades)
        if not tipo:
            pendente(destino, aportador, valor, f"tipo {regra.tipo!r} da aba Regras não é aporte nem distribuição")
            continue
        if pagador is None or recebedor is None:
            falta = aportador if pagador is None else destino
            pendente(destino, aportador, valor, f"não achei {falta!r} (um só) no cadastro da aba Aportes")
            continue
        op = Operacao(data=data, pagador=pagador, recebedor=recebedor, valor=como_dinheiro(valor),
                      tipo=tipo, modo=_modo(pagador, recebedor, entidades))
        erros = op.validar(entidades, subcontas)
        if erros:
            pendente(destino, aportador, valor, "; ".join(erros))
            continue
        envio.itens.append((op, [chave_de_envio(destino, aportador, valor)]))

    for (destino, numero), valores in da_subconta.items():
        def todos(motivo):
            for a, v in valores.items():
                pendente(destino, a, v, motivo)
        cfg = subcontas[numero]
        investidores = cfg.get("investidores") or []
        total = sum(valores.values(), ZERO)
        recebedor = nome_no_cadastro(destino, entidades)
        por_nome = {util.norm_espaco(a): v for a, v in valores.items()}
        if recebedor is None:
            todos(f"não achei {destino!r} (um só) no cadastro da aba Aportes")
            continue
        if set(por_nome) != {util.norm_espaco(i) for i in investidores}:
            todos(f"os investidores digitados não são os da subconta {numero} no cadastro")
            continue
        try:
            partes = dividir_por_peso(total, investidores, cfg.get("pesos") or {})
        except ValueError as e:
            todos(str(e))
            continue
        if any(por_nome[util.norm_espaco(i)] != p for i, p in zip(investidores, partes)):
            todos(f"a divisão digitada difere da do cadastro da subconta {numero} "
                  "(a aba Aportes divide pelo cadastro)")
            continue
        op = Operacao(data=data, pagador=INVESTIDOR_PREFIXO + numero, recebedor=recebedor,
                      valor=como_dinheiro(total), tipo=TIPO_INVESTIDOR, modo="Só recebimento")
        erros = op.validar(entidades, subcontas)
        if erros:
            todos("; ".join(erros))
            continue
        envio.itens.append((op, [chave_de_envio(destino, a, v) for a, v in valores.items()]))
    return envio
```
`aportes/aportes_frame.py`: em `_adicionar`, trocar as linhas 340-344 (`self.operacoes.append(op)` … `self.tabela.insert(...)`) por `self._acrescentar(op)`. Logo depois do `_adicionar`, acrescentar:
```python
    def _acrescentar(self, op) -> None:
        """Uma operação no fim da lista, com as três memórias de posição juntas."""
        self.operacoes.append(op)
        self.criados.append(set())
        self.incertos.append(set())
        self.assinaturas.append({})
        self.tabela.insert("", "end", values=(op.resumo(),))

    def receber_operacoes(self, ops) -> list[tuple[int, str]]:
        """Operações vindas de outra aba (hoje, "Pagamentos do dia") entram na
        lista "A lançar" como se tivessem sido digitadas aqui — e só vão ao ERP
        no "Lançar no Mais Controle", depois de conferidas. Devolve
        [(índice, motivo)] das RECUSADAS.

        Duas recusas que o formulário não tem: a lista travada (o Lançar marca
        por POSIÇÃO) e a operação IGUAL a uma que já está na lista — mandar duas
        vezes da outra aba é clique repetido, não dois aportes."""
        if self._lista_travada():
            return [(i, "a aba Aportes está trabalhando — espere e mande de novo")
                    for i in range(len(ops))]
        recusas = []
        for i, op in enumerate(ops):
            if op in self.operacoes:
                recusas.append((i, "já está na lista A lançar"))
                continue
            erros = op.validar(self.entidades, self.subcontas)
            if erros:
                recusas.append((i, "; ".join(erros)))
                continue
            self._acrescentar(op)
        self._atualizar_total()
        return recusas
```
`pagamentos_dia/pagamentos_frame.py` — ÚNICA mudança, no fim da classe:
```python
    # ----------------------------------------- vindo da aba "Pagamentos do dia"
    def receber_apuracao(self, leitura, desmarcados=()) -> None:
        """A leitura que a aba "Pagamentos do dia" já fez vira o passo 2 daqui,
        e a conferência da remessa de sempre abre — sem ler o ERP de novo.

        `desmarcados` são os que a tela do dia não deixa sair (já enviados):
        o `remontar` os tira com o motivo de sempre. A conferência da remessa
        continua perguntando ao registro "já saiu?" (`gerar_remessa`), então a
        trava contra pagamento em dobro não depende desta passagem."""
        if self.worker and not self.worker.done():
            messagebox.showinfo("Remessa", "Espere a rotina desta aba terminar.")
            return
        if leitura is None or leitura.entradas is None:
            messagebox.showinfo("Remessa", "A leitura do dia não terminou — busque de novo.")
            return
        ini, fim = leitura.periodo
        self.lancamentos = list(leitura.lancamentos)
        self.anexos = leitura.anexos
        self.overviews = leitura.overviews
        self.participantes = leitura.participantes
        self._periodo_da_busca = (ini, fim)
        self.v_ini.set(f"{ini:%d/%m/%Y}")
        self.v_fim.set(f"{fim:%d/%m/%Y}")
        self.resultado = confirmacao.remontar(leitura.entradas, set(desmarcados))
        self._periodo_do_resultado = (ini, fim)
        self.contas = relatorio.resumo_por_conta(self.lancamentos)
        self.q.put(("contas", self.contas))
        self._log(f"\nApuração recebida da aba Pagamentos do dia "
                  f"({ini:%d/%m/%Y} a {fim:%d/%m/%Y}).")
        self.gerar_remessa()
```
- [ ] **Passo 4:** `python -m pytest tests/test_tela_do_dia_para_aportes.py tests/test_aportes_receber_operacoes.py tests/test_remessa_receber_apuracao.py tests/test_aportes_regras.py tests/test_aportes_assinatura.py -q`. Esperado: PASSA.
- [ ] **Passo 5: commit** — `"Pagamentos do dia: aportes chegam preenchidos na aba Aportes e a apuração vai para a Remessa"` + rodapé.

---

## Tarefa 12 — A tela fina, o menu e a documentação
**Modelo sugerido:** sonnet.

**Files:**
- Create: `tela_do_dia/frame.py`, `.claude/rules/arquitetura-tela-do-dia.md`
- Modify:
  - `comprovantes_app.py`: perto de `:41-45` (imports), `:324` (criação), `:341` (`quadros`), `:363` (depois de `mostrar`) e `:489` (`_grupo("diario", …)`);
  - `widgets.py:259-292`: entrada `"🧾"` nas DUAS tabelas, com um codepoint de uso privado único;
  - `tests/test_abas_em_paralelo.py:212-216`: `"tela_do_dia/frame.py"` em `_CHAMADORES`;
  - `CLAUDE.md`: lista do `codigo.zip`, lista "chegam sozinhas" e tabela de mapas.

**Interfaces:** `class TelaDoDiaFrame(ttk.Frame)`, com:
- `__init__(master, anexar_frame)`;
- atributos ligados pelo app: `aba_aportes`, `aba_remessa`, `abrir_aportes`, `abrir_remessa`;
- `buscar()`, `aplicar_cores(escuro)`, `b1` (o Enter da aba aciona o b1).

- [ ] **Passo 1: teste que falha.** Acrescente `"tela_do_dia/frame.py"` a `_CHAMADORES` em `tests/test_abas_em_paralelo.py:212`. Depois rode `python -m pytest tests/test_abas_em_paralelo.py -q -k todo_aviso`. Esperado: FALHA (arquivo ausente).
- [ ] **Passo 2: implementação** — `tela_do_dia/frame.py`
```python
# -*- coding: utf-8 -*-
"""Aba "Pagamentos do dia": a tela fina por cima de `tela_do_dia/`.

Tudo o que decide número mora nos módulos puros ao lado e tem teste sem
janela. Aqui só se lê o ERP na thread do navegador (`anx.submeter`,
`dona=self`), mostra, pergunta e grava o dia de trabalho. Nada escreve no Mais
Controle: o único caminho até o ERP é a aba Aportes, depois que a pessoa
confere e confirma lá. As abas antigas continuam no menu até esta estar provada.
"""
from __future__ import annotations

import datetime
import os
import queue
import subprocess
import time
import tkinter as tk
from threading import Event
from tkinter import messagebox, ttk

import util
import widgets
from conciliacao.aportadores import ler_regras
from conciliacao.config import load_config
from conciliacao.frame import RAIZ_SAIDA
from conciliacao.mapping import AccountMapping
from conciliacao.models import sugerir_periodo
from conciliacao.workbook import WorkbookError, output_name
from pagamentos_dia import confirmacao, html_pagamentos, leitura_do_dia
from pagamentos_dia import reembolso, relatorio
from pagamentos_dia import regras_pagamento as regras_pag
from pagamentos_dia.pagamentos_frame import _carregar_mapas, _historico

from . import aportes as ap
from . import dia_de_trabalho as ddt
from . import erp_do_dia, excel_do_dia, para_aportes
from . import pagamentos as pg
from . import saldos as sd
from .valores import brl, ler_valor_editado

px = widgets.px
REMOVER = "remover"


class TelaDoDiaFrame(ttk.Frame):
    COLS_SALDOS = (("conta", "CONTA", 300, "w"), ("sistema", "SISTEMA (ERP)", 230, "e"),
                   ("banco", "BANCO", 230, "e"), ("dif", "DIFERENÇA", 130, "e"),
                   ("situacao", "SITUAÇÃO", 320, "w"))
    COLS_PAG = (("qtd", "QUANTOS", 220, "w"), ("valor", "VALOR", 140, "e"),
                ("situacao", "SITUAÇÃO", 440, "w"))
    COLS_APT = (("minimo", "MÍNIMO", 120, "e"), ("sugerido", "SUGERIDO", 120, "e"),
                ("definido", "DEFINIDO", 120, "e"), ("falta", "FALTA RATEAR", 120, "e"),
                ("final", "SALDO FINAL", 130, "e"))

    def __init__(self, master, anexar_frame):
        super().__init__(master)
        self.anx = anexar_frame
        self.q = queue.Queue()
        self.worker = None
        self._parar = Event()
        self._erro_drain = None
        self.aba_aportes = None
        self.aba_remessa = None
        self.abrir_aportes = lambda: None
        self.abrir_remessa = lambda: None
        self.cfg = self.mapping = self.leitura = self.modelo = self.periodo = None
        self.contas_erp, self.regras = [], []
        self.dia = None
        self._dia_bloqueado = ""
        self.saldos, self.fora = [], []
        self.pagamentos = {}
        self.aportes = None
        self._iid_aporte = {}
        self.ultimo_arquivo = None
        self._build()
        self.after(150, self._drain)

    # ---------------------------------------------------------------- layout
    def _build(self):
        PADX = px(widgets.PADX)
        cab = widgets.Cabecalho(
            self, "Pagamentos do dia",
            "Saldos, o que vai sair, os aportes e o Excel do dia — numa tela só. "
            "Nada aqui escreve no Mais Controle.",
            trilha="Diário  ›  Pagamentos do dia")
        cab.pack(fill="x", padx=PADX, pady=px((16, 12)))
        corpo = widgets.AreaRolavel(self)
        self.b1 = widgets.Botao(cab.acoes, "Buscar pagamentos e saldos", papel="acao",
                                command=self.buscar)
        self.b1.pack(side="left")

        c1 = widgets.Cartao(corpo, "Saldos", 1)
        c1.pack(fill="x", padx=PADX, pady=px((0, 12)))
        ttk.Label(c1, style="Tenue.TLabel",
                  text="Dois cliques no valor do sistema ou do banco para editar. "
                       "Vale só hoje; o original fica ao lado.").pack(anchor="w")
        self.t_saldos = self._tabela(c1, self.COLS_SALDOS, arvore=False, altura=8)
        self.t_saldos.bind("<Double-1>", self._duplo_saldo)

        c2 = widgets.Cartao(corpo, "Pagamentos por conta", 2)
        c2.pack(fill="x", padx=PADX, pady=px((0, 12)))
        ttk.Label(c2, style="Tenue.TLabel",
                  text="A pagar = o que vai sair (aptos). Bloqueados não somam: "
                       "não aptos e o que já saiu em remessa.").pack(anchor="w")
        self.t_pag = self._tabela(c2, self.COLS_PAG, arvore=True, altura=10)

        c3 = widgets.Cartao(corpo, "Aportes", 3)
        c3.pack(fill="x", padx=PADX, pady=px((0, 12)))
        self.lbl_alerta = ttk.Label(c3, style="Erro.TLabel", wraplength=px(900),
                                    justify="left", text="")
        self.lbl_alerta.pack(anchor="w")
        self.lbl_avisos = ttk.Label(c3, style="Atencao.TLabel", wraplength=px(900),
                                    justify="left", text="")
        self.lbl_avisos.pack(anchor="w")
        self.t_apt = self._tabela(c3, self.COLS_APT, arvore=True, altura=10)
        self.t_apt.bind("<Double-1>", self._duplo_aporte)
        linha = ttk.Frame(c3)
        linha.pack(fill="x", pady=px((8, 0)))
        self.b_sugestao = widgets.Botao(linha, "Preencher com a sugestão da regra",
                                        papel="neutro", state="disabled",
                                        command=self._usar_sugestoes)
        self.b_sugestao.pack(side="left")
        self.b_mandar = widgets.Botao(linha, "Mandar para a aba Aportes", papel="passo",
                                      state="disabled", command=self._mandar_aportes)
        self.b_mandar.pack(side="left", padx=px((8, 0)))

        c4 = widgets.Cartao(corpo, "Gerar", 4)
        c4.pack(fill="x", padx=PADX, pady=px((0, 12)))
        botoes = ttk.Frame(c4)
        botoes.pack(fill="x")
        self.b_excel = widgets.Botao(botoes, "Excel do dia (painel)", papel="acao",
                                     state="disabled", command=self._gerar_excel)
        self.b_planilha = widgets.Botao(botoes, "Planilha por conta", papel="neutro",
                                        state="disabled", command=self._gerar_planilha)
        self.b_html = widgets.Botao(botoes, "HTML dos pagamentos", papel="neutro",
                                    state="disabled", command=self._gerar_html)
        self.b_remessa = widgets.Botao(botoes, "Remessa do Sicoob…", papel="neutro",
                                       state="disabled", command=self._ir_para_remessa)
        for i, b in enumerate((self.b_excel, self.b_planilha, self.b_html, self.b_remessa)):
            b.pack(side="left", padx=px((0 if i == 0 else 8, 0)))

        acao = ttk.Frame(self, style="Fundo.TFrame")
        acao.pack(fill="x", padx=PADX, pady=px((0, 10)))
        btns = ttk.Frame(acao, style="Fundo.TFrame")
        btns.pack(side="right", padx=px((16, 0)))
        self.b_stop = widgets.Botao(btns, "⏹  Parar", papel="perigo", state="disabled",
                                    command=self._parar_click)
        self.b_stop.pack(side="left")
        self.b_pasta = widgets.Botao(btns, "📂  Abrir a pasta", papel="neutro",
                                     state="disabled",
                                     command=lambda: self._abrir(self.ultimo_arquivo.parent
                                                                 if self.ultimo_arquivo else None))
        self.b_pasta.pack(side="left", padx=px((8, 0)))
        self.barra_exec = widgets.BarraExecucao(acao)
        self.barra_exec.pack(side="left", fill="x", expand=True)
        self.lbl, self.pb = self.barra_exec.lbl, self.barra_exec.pb
        self.reg = widgets.Cartao(self, "Registro", padding=(12, 10))
        self.reg.pack(fill="x", padx=PADX, pady=px((0, 12)))
        self.log = tk.Text(self.reg, wrap="word", relief="flat", borderwidth=0,
                           highlightthickness=0)
        self.log.pack(fill="both", expand=True)
        widgets.estilo_log(self.log)
        widgets.registro_elastico(self.reg, self.log)
        corpo.encaixar(acao, self.reg)

    def _tabela(self, pai, colunas, *, arvore: bool, altura: int):
        grade = ttk.Frame(pai)
        grade.pack(fill="both", expand=True, pady=px((8, 0)))
        t = ttk.Treeview(grade, columns=[c[0] for c in colunas],
                         show="tree headings" if arvore else "headings", height=altura)
        if arvore:
            t.heading("#0", text="CONTA", anchor="w")
            t.column("#0", width=px(320), anchor="w")
        for chave, titulo, largura, ancora in colunas:
            t.heading(chave, text=titulo, anchor=ancora)
            t.column(chave, width=largura, anchor=ancora)
        widgets.estilo_tabela(t, ordenavel=False)
        t.pack(side="left", fill="both", expand=True)
        ttk.Scrollbar(grade, orient="vertical", command=t.yview).pack(side="right", fill="y")
        return t

    # ------------------------------------------------------------- mensagens
    def _log(self, msg=""):
        self.q.put(("log", msg))

    def _drain(self):
        try:
            while True:
                tipo, valor = self.q.get_nowait()
                if tipo == "log":
                    self.log.insert("end", f"{valor}\n")
                    self.log.see("end")
                elif tipo == "status":
                    self.lbl.configure(text=valor)
                elif tipo == "ocupado":
                    (self.pb.start(12) if valor else self.pb.stop())
                elif tipo == "botoes":
                    self.b1.configure(state=valor)
                    self.b_stop.configure(state="disabled" if valor == "normal" else "normal")
                elif tipo == "leitura":
                    self._receber_leitura(valor)
        except queue.Empty:
            pass
        except Exception as e:                              # noqa: BLE001
            motivo = repr(e)
            if motivo != self._erro_drain:
                self._erro_drain = motivo
                self.q.put(("log", f"[!] falha ao atualizar a tela: {motivo}"))
        finally:
            self.after(150, self._drain)

    def aplicar_cores(self, escuro: bool):
        try:
            widgets.estilo_log(self.log, escuro)
        except tk.TclError:
            pass

    def _parar_click(self):
        self._parar.set()
        self.lbl.configure(text="Parando...")
        self.b_stop.configure(state="disabled")

    @staticmethod
    def _abrir(alvo):
        if alvo and alvo.exists():
            try:
                os.startfile(alvo)                          # noqa: S606 (Windows)
            except Exception:                               # noqa: BLE001
                subprocess.Popen(["explorer", str(alvo)])

    # ---------------------------------------------------------------- leitura
    def buscar(self):
        if self.worker and not self.worker.done():
            return
        # Recusar ANTES de apagar os botões (ver "Um navegador, seis abas").
        if self.anx.avisar_se_ocupado("os Pagamentos do dia", aba=self):
            return
        periodo = sugerir_periodo(datetime.date.today())
        self._parar.clear()
        self.q.put(("botoes", "disabled"))
        self.q.put(("ocupado", True))
        self.q.put(("status", f"Lendo {periodo.descrever()}..."))
        self.worker = self.anx.submeter("Pagamentos do dia — ler", self._t_ler,
                                        periodo, dona=self)

    def _t_ler(self, periodo):
        comeco = time.time()
        try:
            base = util.pasta_base()
            cfg = load_config(base / "config.yaml")
            mapping = AccountMapping.load(base / "mapping.yaml")
            api = self.anx.garantir_sessao(self._log)
            self.q.put(("status", "Lendo os pagamentos e os anexos..."))
            leitura = leitura_do_dia.ler_pagamentos(
                api, periodo.inicio, periodo.fim,
                abrir_historico=lambda: _historico(self._log),
                carregar_mapas=_carregar_mapas,
                cadastro_reembolso=reembolso.carregar(base),
                regras_fornecedor=regras_pag.carregar_fornecedores(),
                destacar=regras_pag.carregar_confirmar(),
                log=self._log,
                progresso=lambda f, t: self.q.put(("status", f"Lendo... {f}/{t}")),
                cancelar=self._parar.is_set)
            if leitura.interrompida:
                self._log("\nInterrompido — a leitura ficou pela metade e nada foi "
                          "mostrado. Busque de novo.")
                self.q.put(("status", "Interrompido."))
                return
            self.q.put(("status", "Lendo os saldos..."))
            contas = erp_do_dia.ler_saldos(cfg, api, log=self._log)
            modelo = cfg.caminho("modelo")
            self.q.put(("leitura", (cfg, mapping, leitura, contas, ler_regras(modelo),
                                    periodo, modelo)))
            self.q.put(("status", f"Leitura pronta em {util.fmt_dur(time.time() - comeco)}."))
        except Exception as e:                              # noqa: BLE001
            self._log(f"[!] {e}")
            self.q.put(("status", "Não consegui ler o dia — veja o Registro."))
        finally:
            self.q.put(("ocupado", False))
            self.q.put(("botoes", "normal"))

    def _receber_leitura(self, pacote):
        (self.cfg, self.mapping, self.leitura, self.contas_erp, self.regras,
         self.periodo, self.modelo) = pacote
        caminho = ddt.caminho_do_dia(RAIZ_SAIDA, self.periodo.fim)
        try:
            self.dia, self._dia_bloqueado = ddt.ler(caminho, self.periodo.fim), ""
        except ValueError as e:
            self.dia, self._dia_bloqueado = ddt.DiaDeTrabalho(self.periodo.fim), str(e)
            self._log(f"[!] {e}\n    Os ajustes de hoje NÃO serão gravados até esse "
                      "arquivo ser conferido (ele não é sobrescrito).")
        for aviso in self.leitura.avisos:
            self._log(f"[!] {aviso}")
        self._recalcular()
        for b in (self.b_excel, self.b_planilha, self.b_html, self.b_remessa,
                  self.b_mandar, self.b_sugestao):
            b.configure(state="normal")

    def _gravar_dia(self):
        if self._dia_bloqueado:
            self._log("[!] dia de trabalho NÃO gravado (o arquivo do dia está ilegível).")
            return
        try:
            ddt.gravar(self.dia, ddt.caminho_do_dia(RAIZ_SAIDA, self.periodo.fim))
        except OSError as e:
            self._log(f"[!] não consegui gravar o dia de trabalho: {e}")

    # -------------------------------------------------------------- recálculo
    def _recalcular(self):
        base = sd.montar_saldos(self.contas_erp, self.mapping)
        self.saldos = sd.ordenar(sd.aplicar_ajustes(base, self.dia.ajustes))
        self.pagamentos, self.fora = pg.por_conta(self.leitura.grupos, self.mapping)
        em_ordem = sorted(self.saldos, key=lambda ln: ln.linha)
        self.aportes = ap.montar_aportes(
            {ln.rotulo: ln.saldo_do_dia for ln in em_ordem},
            {c.rotulo: c.a_pagar for c in self.pagamentos.values()},
            self.regras, self.dia.aportes)
        self._encher_saldos()
        self._encher_pagamentos()
        self._encher_aportes()

    @staticmethod
    def _celula(lido, ajuste):
        if ajuste is None:
            return brl(lido)
        motivo = f" · {ajuste.motivo}" if ajuste.motivo else ""
        return f"{brl(ajuste.valor)}  (era {brl(ajuste.original)}{motivo})"

    def _encher_saldos(self):
        t = self.t_saldos
        t.delete(*t.get_children())
        for i, ln in enumerate(self.saldos):
            tag, frase = ln.situacao()
            t.insert("", "end", iid=ln.rotulo, tags=widgets.linha_zebrada(i, tag), values=(
                ln.rotulo, self._celula(ln.sistema, ln.ajuste_sistema),
                self._celula(ln.banco, ln.ajuste_banco), brl(ln.diferenca),
                f"{widgets.MARCAS_ESTADO[tag]} {frase}"))

    def _encher_pagamentos(self):
        t = self.t_pag
        t.delete(*t.get_children())
        contas = sorted(self.pagamentos.values(), key=lambda c: c.linha) + list(self.fora)
        for i, c in enumerate(contas):
            estado = "erro" if c.motivo_fora else ("atencao" if c.bloqueados else "")
            situacao = c.motivo_fora or (f"bloqueado: {brl(c.valor_bloqueado)}" if c.bloqueados else "")
            pai = t.insert("", "end", text=c.rotulo, open=False,
                           tags=widgets.linha_zebrada(i, estado),
                           values=(f"{c.qtd_a_pagar} vão sair · {len(c.bloqueados)} bloqueado(s)",
                                   brl(c.a_pagar), situacao))
            for p in c.vao_sair:
                t.insert(pai, "end", text=f"   {p.favorecido}",
                         values=("vai sair", brl(p.valor), p.situacao))
            for p in c.bloqueados:
                t.insert(pai, "end", text=f"   {p.favorecido}", tags=("erro",),
                         values=("bloqueado", brl(p.valor), p.situacao))

    def _encher_aportes(self):
        t = self.t_apt
        t.delete(*t.get_children())
        self._iid_aporte = {}
        alertas = self.aportes.alertas
        self.lbl_alerta.configure(text="\n".join(f for tag, f in alertas if tag == "erro"))
        self.lbl_avisos.configure(text="\n".join(f for tag, f in alertas if tag != "erro"))
        for i, c in enumerate(self.aportes.contas):
            estado = "erro" if c.saldo_final < 0 else ("atencao" if c.falta_ratear > 0 else "")
            pai = t.insert("", "end", open=True, tags=widgets.linha_zebrada(i, estado),
                           text=("★ CONTA-MÃE · " if c.e_mae else "") + c.rotulo,
                           values=(brl(c.minimo), "", brl(c.definido),
                                   brl(c.falta_ratear), brl(c.saldo_final)))
            sugestao = c.sugestao
            for p in c.participantes:
                peso = f"  (peso {p.peso})" if p.peso is not None else ""
                iid = t.insert(pai, "end", text=f"   {p.aportador}{peso}", values=(
                    "", brl(sugestao.get(p.aportador)), brl(c.definidos.get(p.aportador)), "", ""))
                self._iid_aporte[iid] = (c.rotulo, p.aportador)
            if c.e_mae and c.sai:
                t.insert(pai, "end", text="   sai para as outras contas",
                         values=("", "", brl(c.sai), "", ""))

    # ---------------------------------------------------------------- edição
    def _pedir_valor(self, titulo, explicacao, atual="", com_motivo=True):
        """(Decimal, motivo), REMOVER ou None. Modal: é pergunta que exige resposta."""
        jan = tk.Toplevel(self)
        jan.title(titulo)
        jan.transient(self.winfo_toplevel())
        widgets.barra_de_titulo(jan)
        corpo = ttk.Frame(jan, padding=px(14))
        corpo.pack(fill="both", expand=True)
        ttk.Label(corpo, text=explicacao, wraplength=px(440), justify="left").pack(anchor="w")
        v_valor, v_motivo = tk.StringVar(value=atual), tk.StringVar()
        widgets.Campo(corpo, "Valor R$", lambda p: ttk.Entry(p, textvariable=v_valor, width=18)
                      ).pack(anchor="w", pady=px((10, 0)))
        if com_motivo:
            widgets.Campo(corpo, "Motivo (opcional)",
                          lambda p: ttk.Entry(p, textvariable=v_motivo, width=48)
                          ).pack(anchor="w", pady=px((10, 0)))
        resposta = {}

        def aplicar(_e=None):
            try:
                resposta["v"] = (ler_valor_editado(v_valor.get()), v_motivo.get().strip())
            except ValueError as e:
                messagebox.showwarning(titulo, str(e), parent=jan)
                return
            jan.destroy()

        def remover():
            resposta["v"] = REMOVER
            jan.destroy()

        linha = ttk.Frame(corpo)
        linha.pack(anchor="e", pady=px((14, 0)))
        widgets.Botao(linha, "Voltar ao original", papel="neutro", command=remover).pack(side="left")
        widgets.Botao(linha, "Cancelar", papel="neutro", command=jan.destroy).pack(side="left", padx=px((8, 0)))
        widgets.Botao(linha, "Aplicar", papel="acao", command=aplicar).pack(side="left", padx=px((8, 0)))
        jan.bind("<Return>", aplicar)
        jan.bind("<Escape>", lambda _e: jan.destroy())
        jan.grab_set()
        jan.wait_window()
        return resposta.get("v")

    def _duplo_saldo(self, evento):
        iid = self.t_saldos.identify_row(evento.y)
        campo = {"#2": sd.SISTEMA, "#3": sd.BANCO}.get(self.t_saldos.identify_column(evento.x))
        if not iid or not campo or self.dia is None:
            return
        linha = next(ln for ln in self.saldos if ln.rotulo == iid)
        lido = linha.sistema if campo == sd.SISTEMA else linha.banco
        resposta = self._pedir_valor(f"{iid} — saldo do {campo}",
                                     f"Lido agora: {brl(lido)}. O ajuste vale só hoje e o "
                                     "original continua visível.")
        if resposta is None:
            return
        ajustes = self.dia.ajustes.setdefault(iid, {})
        if resposta == REMOVER:
            ajustes.pop(campo, None)
        else:
            valor, motivo = resposta
            ajustes[campo] = sd.novo_ajuste(linha, campo, valor, motivo,
                                            quando=datetime.datetime.now().isoformat(timespec="minutes"))
        if not ajustes:
            self.dia.ajustes.pop(iid, None)
        self._gravar_dia()
        self._recalcular()

    def _duplo_aporte(self, evento):
        par = self._iid_aporte.get(self.t_apt.identify_row(evento.y))
        if not par or self.dia is None:
            return
        destino, aportador = par
        conta = next(c for c in self.aportes.contas if c.rotulo == destino)
        sugerido = conta.sugestao.get(aportador)
        resposta = self._pedir_valor(
            f"Aporte · {aportador} → {destino}",
            f"Mínimo da conta: {brl(conta.minimo)} · falta ratear: {brl(conta.falta_ratear)}"
            + (f" · a regra sugere {brl(sugerido)}" if sugerido is not None else ""),
            com_motivo=False)
        if resposta is None:
            return
        if resposta == REMOVER or resposta[0] == 0:
            self.dia.aportes.pop((destino, aportador), None)
        elif resposta[0] < 0:
            messagebox.showwarning("Aporte", "Aporte não pode ser negativo.")
            return
        else:
            self.dia.aportes[(destino, aportador)] = resposta[0]
        self._gravar_dia()
        self._recalcular()

    def _usar_sugestoes(self):
        for c in self.aportes.contas:
            for aportador, valor in c.sugestao.items():
                self.dia.aportes.setdefault((c.rotulo, aportador), valor)
        self._gravar_dia()
        self._recalcular()

    # ----------------------------------------------------------------- gerar
    def _resultado_que_sai(self):
        return confirmacao.remontar(self.leitura.entradas, pg.ids_que_nao_saem(self.leitura.grupos))

    def _pasta_pagamentos(self):
        pasta = util.pasta_base() / "Pagamentos do dia"
        pasta.mkdir(parents=True, exist_ok=True)
        return pasta

    def _gerar_excel(self):
        mae = next((c for c in self.aportes.contas if c.e_mae), None)
        if mae and mae.saldo_final < 0 and not messagebox.askyesno(
                "Excel do dia", f"A conta-mãe fecha NEGATIVA ({brl(mae.saldo_final)}). "
                                "Gerar o Excel assim mesmo?", default="no"):
            return
        fim = self.periodo.fim
        destino = ddt.pasta_do_dia(RAIZ_SAIDA, fim) / output_name(fim)
        try:
            r = excel_do_dia.gerar(
                modelo=self.modelo, destino=destino, data=fim, mapping=self.mapping,
                planilha=self.cfg.planilha,
                saldos={ln.linha: ln.saldo_do_dia for ln in self.saldos},
                a_pagar=pg.totais_para_o_painel(self.pagamentos),
                regras=self.regras, definidos=self.aportes.definidos_validos)
        except (WorkbookError, OSError) as e:
            self._log(f"\nO EXCEL DO DIA NÃO FOI GERADO\n{e}")
            messagebox.showwarning("Excel do dia", widgets.recado_de_erro(e, "Não gerei o Excel do dia."))
            return
        self.ultimo_arquivo = r.path
        self.b_pasta.configure(state="normal")
        self._log(f"\nExcel do dia: {str(r.path).replace(chr(92), '/')} "
                  f"({r.celulas_conferidas} células conferidas)")
        widgets.registrar_atividade("dia", "Excel do dia", "ok", r.path.name)
        self._abrir(r.path)

    def _gerar_planilha(self):
        ini, fim = self.leitura.periodo
        nome = f"pagamentos_{ini:%Y-%m-%d}{'' if ini == fim else f'_a_{fim:%Y-%m-%d}'}.xlsx"
        try:
            arquivo = relatorio.gerar_excel(self._resultado_que_sai(),
                                            self._pasta_pagamentos() / nome, log=self._log)
        except Exception as e:                              # noqa: BLE001
            self._log(f"[!] planilha por conta: {e}")
            return
        self._log(f"Planilha por conta: {str(arquivo).replace(chr(92), '/')}")
        self._abrir(arquivo)

    def _gerar_html(self):
        resultado, lancamentos = self._resultado_que_sai(), self.leitura.lancamentos
        pessoas = regras_pag.carregar_confirmar()
        if pessoas:
            nomes = " e ".join(pessoas) if len(pessoas) <= 2 else ", ".join(pessoas)
            if not messagebox.askyesno("HTML dos pagamentos",
                                       f"Incluir reembolso para {nomes}?\n\n"
                                       "Sim = os reembolsos deles entram no HTML.\n"
                                       "Não = ficam fora dos dois HTMLs."):
                resultado, lancamentos, tirados = html_pagamentos.tirar_reembolsos(
                    resultado, lancamentos, pessoas, self.leitura.overviews)
                for linha in tirados:
                    self._log(f"  - fora do HTML: {linha}")
        ini, fim = self.leitura.periodo
        pasta = self._pasta_pagamentos()
        try:
            gerados = html_pagamentos.gravar(resultado, lancamentos, self.leitura.anexos,
                                             pasta, ini, fim, pastas_extras=(pasta, util.pasta_base()))
        except Exception as e:                              # noqa: BLE001
            self._log(f"[!] HTML dos pagamentos: {e}")
            return
        for linha in gerados.registro():
            self._log(linha)
        self._abrir(gerados.geral)

    def _ir_para_remessa(self):
        if self.aba_remessa is None:
            return
        self.abrir_remessa()
        self.aba_remessa.receber_apuracao(self.leitura, pg.ids_que_nao_saem(self.leitura.grupos))

    def _mandar_aportes(self):
        if self.aba_aportes is None:
            return
        enviados = set(self.dia.enviados_aportes)
        envio = para_aportes.operacoes(self.aportes.definidos_validos, self.regras,
                                       self.aba_aportes.entidades, self.aba_aportes.subcontas,
                                       datetime.date.today(), enviados=enviados)
        repetidos = [p for p in envio.pendentes if p.motivo.startswith("já mandado")]
        if repetidos and messagebox.askyesno(
                "Aportes", f"{len(repetidos)} aporte(s) já foram mandados hoje. "
                           "Mandar de novo? (Confira a lista da aba Aportes antes.)",
                default="no"):
            envio = para_aportes.operacoes(self.aportes.definidos_validos, self.regras,
                                           self.aba_aportes.entidades, self.aba_aportes.subcontas,
                                           datetime.date.today(), enviados=())
        for p in envio.pendentes:
            self._log(f"[!] {p.aportador} → {p.destino} ({brl(p.valor)}): {p.motivo}")
        if not envio.itens:
            messagebox.showinfo("Aportes", "Nada para mandar — veja o Registro.")
            return
        recusas = dict(self.aba_aportes.receber_operacoes([op for op, _c in envio.itens]))
        agora = datetime.datetime.now().isoformat(timespec="minutes")
        for i, (op, chaves) in enumerate(envio.itens):
            if i in recusas:
                self._log(f"[!] a aba Aportes recusou {op.resumo()}: {recusas[i]}")
                continue
            for chave in chaves:
                self.dia.enviados_aportes[chave] = agora
        self._gravar_dia()
        self._log(f"\n{len(envio.itens) - len(recusas)} operação(ões) na lista da aba "
                  "Aportes — confira lá e clique em Lançar no Mais Controle.")
        self.abrir_aportes()
```
Em `comprovantes_app.py`:
- import junto dos outros: `from tela_do_dia.frame import TelaDoDiaFrame`;
- logo depois de `aba_con = ConciliacaoFrame(conteudo, aba_anx)` (`:324`):
```python
    # Pagamentos do dia divide navegador e thread do Anexar, como a Remessa e o
    # Saldo; recebe as duas abas para onde manda trabalho (Aportes e Remessa).
    aba_dia = TelaDoDiaFrame(conteudo, aba_anx)
    aba_dia.aba_aportes = aba_apt
    aba_dia.aba_remessa = aba_pag
```
- em `quadros` (`:341`): `"dia": aba_dia`;
- logo depois do `def mostrar(...)`:
```python
    aba_dia.abrir_aportes = lambda: mostrar("apt") if _pode("apt") else None
    aba_dia.abrir_remessa = lambda: mostrar("pag") if _pode("pag") else None
```
- `_grupo("diario", ...)` (`:489`) passa a começar por `("dia", "🧾", "Pagamentos do dia"),`.

Em `widgets.py`, nas duas tabelas (`ICONES_FLUENT` e `ICONES_MDL2`): `"🧾": "\uE8FD",  # BulletedList — Pagamentos do dia`. Confira o glifo na galeria (`python -m ferramentas.galeria`, máquina livre) e troque por outro codepoint de uso privado único se o desenho não servir.

Escreva `.claude/rules/arquitetura-tela-do-dia.md`:
- frontmatter com `paths: ["tela_do_dia/**", "pagamentos_dia/leitura_do_dia.py", "tests/test_tela_do_dia*.py", "tests/test_leitura_do_dia.py"]`;
- o que cada módulo decide, a regra "vai sair = entra e nasce marcada", o JSON do dia;
- o "zero e não vazio" da Movimentações;
- o caminho dos saldos pelo Chrome do app;
- a duplicação conhecida da orquestração e onde ela se resolve.

No `CLAUDE.md`:
- acrescentar `tela_do_dia/*.py` às duas listas da "Regra de ouro";
- acrescentar a linha `| tela_do_dia/ | .claude/rules/arquitetura-tela-do-dia.md |` à tabela.
- [ ] **Passo 3:** `python -m pytest tests/test_abas_em_paralelo.py tests/test_visual.py::test_as_duas_tabelas_de_icones_falam_dos_mesmos_itens tests/test_visual.py::test_nenhum_icone_do_menu_ficou_fora_da_tabela tests/test_empacotamento.py tests/test_imports_do_motor.py -q`. Esperado: PASSA. Os dois de `test_visual` são aritmética sobre constantes e não abrem janela.
- [ ] **Passo 4: régua completa.** `python -m ruff check --select E9,F .` ; `python -m vermin --target=3.11 --violations tela_do_dia pagamentos_dia/leitura_do_dia.py conciliacao/workbook.py conciliacao/aportadores.py` ; `python -m pytest tests -q -k "not raiz"`. Testes de tela só com o dono liberando; o CI roda tudo.
- [ ] **Passo 5: conferência manual** (com o dono, Chrome do app logado): Buscar → os 4 cartões → editar um saldo → digitar um aporte → Excel do dia → abrir e conferir C, D, H e a Movimentações → Mandar para Aportes (NÃO clicar em Lançar) → Remessa do Sicoob… (abre a conferência; cancelar).
- [ ] **Passo 6: commit** — `"Pagamentos do dia: a aba nova no DIÁRIO (passos 1 a 4, sem leitura de banco)"` + rodapé.

---

## Riscos e decisões para o dono / revisor
1. **Saldo que vai para C quando há banco digitado:** decidi o **banco**; o sistema fica ao lado. Se o dono quer o do sistema (editado), a troca é uma linha em `LinhaSaldo.saldo_do_dia`.
2. **O Excel sai com o MESMO nome e na MESMA pasta do "Saldo de pagamentos"** (`DD MM - completa.xlsx`). Enquanto as duas abas convivem, a última que gerar sobrescreve a outra.
3. **Saldos com o central desligado** saem pelos cabeçalhos de anexos (`_req_anexos`) da aba do robô contra o `prod-erp-api`. É plausível pelo código, mas **não foi medido ao vivo**. Na máquina do dono o central está ligado (`_central/acessos.json` existe) e o caminho usado é o do porteiro, já provado.
4. **A leitura dos pagamentos lê TODOS os anexos e faz OCR** (minutos, como o "Gerar planilha" da Remessa). "A pagar" passa a vir do `plannedDate` da Remessa, e não do `dueDate`/status do Saldo antigo. Os números vão diferir da aba antiga, de propósito (aptos × em aberto).
5. **A orquestração da leitura (~90 linhas) fica duplicada** entre `leitura_do_dia.py` e `pagamentos_frame.py` até o branch de agendamentos entrar. Depois disso, o frame deve passar a chamar o módulo novo.
6. **Mexer no `build.yml` refaz o exe do zero** (~8–10 min de CI). O `motor_minimo.txt` só é tocado, sem mudar a versão. Confira na revisão que ninguém "sobe uma unidade", o que cobraria 152 MB de todas as máquinas presas no exe v2.0.233.
7. **"Mandar para Aportes" pode deixar coisas fora.** Casa nomes Regras→`contas.csv` por `normalize_name` ou pelo número da conta, sem chutar. Rótulos que não casam ficam como pendência no Registro e o dono adiciona à mão. Talvez valha um de-para no cadastro (entrega 2).
8. **Modo e tipo do aporte saem de regra minha, a confirmar com o dono.** Conta da casa → "Pagamento + Recebimento"; pessoa sem conta → "Só recebimento"; subconta de investidor → uma operação "INVESTIDOR SUBCONTA", só se a divisão digitada bater com a do `subcontas.json`.
9. **Ícone "🧾" → `\uE8FD`:** não verifiquei o glifo. O teste só garante codepoint único e de uso privado; confira na galeria.
10. **Período = o sugerido** (hoje + fim de semana anterior), sem campo de data na tela. Feriado continua exigindo outra aba ou um campo de data numa próxima entrega.

### Critical Files for Implementation
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia\conciliacao\workbook.py
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia\pagamentos_dia\confirmacao.py
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia\pagamentos_dia\pagamentos_frame.py
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia\aportes\aportes_frame.py
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia\conciliacao\erp\api.py
