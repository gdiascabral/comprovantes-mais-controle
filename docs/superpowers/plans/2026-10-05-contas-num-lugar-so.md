# Contas num lugar só — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uma busca de contas só (na abertura e num botão "Atualizar contas"), uma janela só para conta nova (cadastro + painel), e as abas lendo dali em vez de cada uma buscar a sua.

**Architecture:** Um módulo novo, `nuvem/contas_central.py`, guarda a lista de contas ativas do ERP num cache local (`contas_erp.json`), calcula o que falta no cadastro e no painel, aplica as respostas da janela única e avisa as abas por um gancho `recarregar_contas()`. A moldura (`comprovantes_app.py`) só liga as peças. As abas perdem os botões próprios.

**Tech Stack:** Python 3.11 (o exe), tkinter/ttk, pytest; Supabase via `nuvem/rest.py`; ERP via `conciliacao/erp/api.SessaoApi` (HTTP).

**Spec:** `docs/superpowers/specs/2026-10-05-contas-num-lugar-so-design.md`

## Global Constraints

- Rodar tudo a partir do worktree `C:/AUTOMAÇÕES MAIS CONTROLE/_worktrees/app-contas-central` (branch `codigo/contas-num-lugar-so`). Nunca `git stash` puro; nunca push na `main`.
- Testes: `python -m pytest tests -q` com `PYTHONPATH` = raiz + `separar_renomear` + `anexar` (o `conftest.py` já arruma). Teste de interface usa a fixture `raiz` do conftest — nunca criar `Tk()` próprio.
- Teste nunca faz rede, nunca abre Chrome, nunca entra no ERP nem no Supabase: tudo por dublê (`monkeypatch`).
- Nome real de fornecedor, pessoa, CPF ou CNPJ não entra em teste nem comentário (repo público). Use "EMPRESA MODELO", "CONTA NOVA FICTICIA 01".
- Régua antes de cada commit: `ruff check --select E9,F <arquivos>`, `python -c "import sys; from vermin.main import main; sys.argv=['vermin','--target=3.11-','--no-tips','--violations',<arquivos>]; main()"`, e os testes do arquivo.
- Sem import novo de submódulo da biblioteca padrão (exige exe novo). `json`, `dataclasses`, `pathlib`, `threading`, `datetime` já estão em uso.
- Arquivo `.py` novo em `nuvem/` já entra no `codigo.zip` (glob `nuvem/*.py`); não mexer no `build.yml`.
- Texto da tela em português, sem jargão; caminho mostrado ao usuário com "/".
- Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Playwright síncrono: objeto do navegador (`anx.mc`) só é tocado dentro de função entregue a `aba_anx.submeter(...)`.

## Review Focus

1. **ERP fora do ar ou login vencido na abertura** — a lista volta vazia: o `contas_erp.json` antigo NÃO pode ser apagado e nenhuma janela abre. Teste em Task 2.
2. **Máquina sem `config.yaml`/`mapping.yaml`** (todas, menos a do dono) — a janela só pergunta pelo cadastro e nada do painel aparece nem quebra. Teste em Task 2.
3. **Conta que já está no cadastro mas falta no painel** (e o contrário) — a janela mostra só o pedaço que falta e grava só ele. Testes em Tasks 3 e 4.
4. **Painel recusado (Excel com o MODELO aberto)** com cadastro gravado — o recado diz as duas coisas, e o cadastro gravado não é desfeito. Teste em Task 4.
5. **Botão "Atualizar contas" clicado com outra aba usando o navegador** — recusa com o aviso de sempre (`avisar_se_ocupado`), sem desabilitar nada. Teste em Task 5.

---

### Task 1: Converter conta crua do ERP num `ErpAccount` em um lugar só

**Files:**
- Modify: `conciliacao/erp/api.py` (método `SessaoApi.contas`, ~L314-330)
- Test: `tests/test_conta_do_erp.py` (novo)

**Interfaces:**
- Produces: `conciliacao.erp.api.conta_do_erp(cru: dict, saldos: dict | None = None) -> ErpAccount`

O corpo é MOVIDO do `contas()`, não redigitado: copie as linhas `ErpAccount(...)` exatamente como estão.

- [ ] **Step 1: Teste que falha**

```python
# tests/test_conta_do_erp.py
from decimal import Decimal

from conciliacao.erp.api import conta_do_erp

CRU = {"id": "u-1", "name": "CONTA NOVA FICTICIA 01", "isActive": True,
       "bankCode": "756", "agency": "1234", "account": "90001",
       "accountDigit": "1"}


def test_conta_crua_vira_erp_account_sem_saldo():
    c = conta_do_erp(CRU)
    assert (c.id, c.name, c.is_active, c.bank_code, c.agency,
            c.account_number) == ("u-1", "CONTA NOVA FICTICIA 01", True,
                                  "756", "1234", "90001-1")
    assert c.balance is None and c.raw_balance is None


def test_com_saldo_usa_o_mapa_pelo_id():
    c = conta_do_erp(CRU, {"u-1": Decimal("10.50")})
    assert c.balance == Decimal("10.50")
    assert c.raw_balance == "10.50"
```

- [ ] **Step 2:** `python -m pytest tests/test_conta_do_erp.py -q` → FAIL (ImportError).

- [ ] **Step 3: Implementar** — em `conciliacao/erp/api.py`, função de módulo logo antes de `coletar_contas_api`:

```python
def conta_do_erp(cru: dict, saldos: dict | None = None) -> ErpAccount:
    """Uma conta CRUA da API vira `ErpAccount`. Sem `saldos`, sai sem saldo
    (`balance=None`, que aqui quer dizer "não lido", nunca zero)."""
    mapa = saldos or {}
    return ErpAccount(
        id=str(cru.get("id") or ""),
        name=str(cru.get("name") or ""),
        is_active=bool(cru.get("isActive", True)),
        bank_code=_texto(cru.get("bankCode")),
        agency=_texto(cru.get("agency")),
        account_number=_numero_conta(cru),
        raw_balance=_bruto(mapa, cru),
        balance=mapa.get(str(cru.get("id"))),
    )
```

e `SessaoApi.contas` passa a ser:

```python
    def contas(self, *, ativas: bool = True) -> list[ErpAccount]:
        """Contas + saldos unidos — o equivalente ao que a tela mostra."""
        crus = self.listar_contas(ativas=ativas)
        mapa = self.saldos([c["id"] for c in crus if c.get("id")])
        return [conta_do_erp(cru, mapa) for cru in crus]
```

- [ ] **Step 4:** `python -m pytest tests/test_conta_do_erp.py tests/ -q -k "api or conta_do_erp or coleta"` → PASS.
- [ ] **Step 5:** Commit `Conciliacao: conta crua do ERP vira ErpAccount numa funcao so`.

---

### Task 2: `nuvem/contas_central.py` — a lista guardada e as pendências

**Files:**
- Create: `nuvem/contas_central.py`
- Test: `tests/test_contas_central.py`

**Interfaces:**
- Consumes: `conta_do_erp` (Task 1); `nuvem.contas_novas.{comparar, nomes_cadastrados, ignorados, contas_do_erp, ContaNova, como_conta_nova}`; `conciliacao.painel_novas.{contas_fora_do_painel, rotulo_sugerido}`; `conciliacao.mapping.AccountMapping.load`; `nuvem.cache.{gravar_json, ler_json}`.
- Produces:
  - `ARQUIVO_ERP = "contas_erp.json"`
  - `guardar_lista(crus: list, pasta=None) -> bool` — grava só se `crus` tem ao menos uma conta com `id` e `name`; devolve se gravou.
  - `ler_lista(pasta=None) -> list[dict]` — `[{"id", "nome", "banco", "agencia", "numero"}]`, ordenada por nome; `[]` sem arquivo.
  - `@dataclass Pendencia`: `conta: ContaNova`, `erp: ErpAccount`, `falta_cadastro: bool`, `falta_painel: bool`, `rotulo: str`; propriedades que delegam a `conta`: `nome`, `banco`, `agencia`, `numero`, `resumo`, `pasta_sugerida`, e o método `empresa_sugerida(nomes)`; propriedade `falta_em -> str` ("cadastro e painel" / "cadastro" / "painel").
  - `pendencias(crus: list, pasta=None, pasta_painel=None) -> list[Pendencia]` — ordenada por nome.
  - `mapa_do_painel(pasta_painel=None) -> AccountMapping | None` — `None` quando não há `mapping.yaml`/`config.yaml` ou não dá para ler.

- [ ] **Step 1: Testes que falham**

```python
# tests/test_contas_central.py
import json

import pytest

from nuvem import contas_central as cc

def _cru(i, ativa=True):
    return {"id": f"u-{i}", "name": f"EMPRESA MODELO - CONTA NOVA FICTICIA {i:02d}",
            "isActive": ativa, "bankCode": "756", "agency": "1234",
            "account": f"{90000 + i}", "accountDigit": "1"}


def _cadastro(pasta, nomes):
    (pasta / "contas_mc.json").write_text(json.dumps(
        {"contas": [{"erp": n} for n in nomes]}), encoding="utf-8")


def test_guarda_e_le_a_lista(tmp_path):
    assert cc.guardar_lista([_cru(2), _cru(1)], tmp_path)
    lista = cc.ler_lista(tmp_path)
    assert [c["id"] for c in lista] == ["u-1", "u-2"]
    assert lista[0] == {"id": "u-1",
                        "nome": "EMPRESA MODELO - CONTA NOVA FICTICIA 01",
                        "banco": "756", "agencia": "1234", "numero": "90001-1"}


def test_lista_vazia_nunca_apaga_a_que_estava(tmp_path):
    cc.guardar_lista([_cru(1)], tmp_path)
    assert cc.guardar_lista([], tmp_path) is False
    assert cc.guardar_lista([{"id": "", "name": ""}], tmp_path) is False
    assert [c["id"] for c in cc.ler_lista(tmp_path)] == ["u-1"]


def test_sem_arquivo_a_lista_e_vazia(tmp_path):
    assert cc.ler_lista(tmp_path) == []


def test_sem_painel_so_pergunta_pelo_cadastro(tmp_path):
    _cadastro(tmp_path, ["EMPRESA MODELO - CONTA NOVA FICTICIA 01"])
    pend = cc.pendencias([_cru(1), _cru(2)], tmp_path, pasta_painel=tmp_path)
    assert [(p.nome, p.falta_cadastro, p.falta_painel) for p in pend] == [
        ("EMPRESA MODELO - CONTA NOVA FICTICIA 02", True, False)]


def test_conta_inativa_nao_e_pendencia(tmp_path):
    _cadastro(tmp_path, [])
    assert cc.pendencias([_cru(1, ativa=False)], tmp_path,
                         pasta_painel=tmp_path) == []


class _MapaDuble:
    """Casa pelo id: as contas em `no_painel` têm linha viva."""

    def __init__(self, no_painel):
        self.no_painel = set(no_painel)


def test_cadastro_e_painel_se_juntam_por_conta(tmp_path, monkeypatch):
    _cadastro(tmp_path, ["EMPRESA MODELO - CONTA NOVA FICTICIA 01"])
    mapa = _MapaDuble({"u-2"})
    monkeypatch.setattr(cc, "mapa_do_painel", lambda _p=None: mapa)
    monkeypatch.setattr(
        cc, "_fora_do_painel",
        lambda contas, m: [c for c in contas if c.id not in m.no_painel])
    pend = {p.erp.id: p for p in cc.pendencias([_cru(1), _cru(2), _cru(3)],
                                               tmp_path, tmp_path)}
    assert (pend["u-1"].falta_cadastro, pend["u-1"].falta_painel) == (False, True)
    assert (pend["u-2"].falta_cadastro, pend["u-2"].falta_painel) == (True, False)
    assert (pend["u-3"].falta_cadastro, pend["u-3"].falta_painel) == (True, True)
    assert pend["u-3"].falta_em == "cadastro e painel"
    assert pend["u-1"].falta_em == "painel"
    assert pend["u-3"].rotulo == "EMPRESA MODELO - CONTA NOVA FICTICIA 03"


def test_ignorada_no_mapping_nao_e_pendencia_de_cadastro(tmp_path):
    _cadastro(tmp_path, [])
    (tmp_path / "mapping.yaml").write_text(
        "ignored_erp_accounts:\n  - CONTA NOVA FICTICIA 01\n", encoding="utf-8")
    pend = cc.pendencias([_cru(1)], tmp_path, pasta_painel=tmp_path)
    assert pend == []
```

- [ ] **Step 2:** `python -m pytest tests/test_contas_central.py -q` → FAIL (módulo não existe).

- [ ] **Step 3: Implementar** `nuvem/contas_central.py`:

```python
# -*- coding: utf-8 -*-
"""As contas do ERP num lugar só (pedido do dono, 05/10/2026).

Antes, cada aba buscava a sua lista: a abertura (para o cadastro), o Saldo
de pagamentos (para o painel, com um segundo login) e o Relatório Mensal
(pela tela do Chrome). Conta incluída num lugar era esquecida no outro.

Aqui mora a lista de contas ATIVAS do ERP lida na última atualização
(`contas_erp.json`, um cache como os outros), o cálculo do que falta no
cadastro e no painel e a aplicação das respostas da janela única.

**Vazio nunca substitui cheio**, como no `cadastro.sincronizar`: ERP fora do
ar devolve lista vazia, e isso não pode apagar a lista de ontem.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import util

from . import cache, contas_novas

log = util.log(__name__)

ARQUIVO_ERP = "contas_erp.json"


def guardar_lista(crus, pasta=None) -> bool:
    contas = []
    for cru in crus or []:
        if not isinstance(cru, dict):
            continue
        conta = contas_novas.como_conta_nova(cru)
        if not (conta.id_erp and conta.nome) or cru.get("isActive") is False:
            continue
        contas.append({"id": conta.id_erp, "nome": conta.nome,
                       "banco": conta.banco, "agencia": conta.agencia,
                       "numero": conta.numero})
    if not contas:
        return False
    cache.gravar_json(ARQUIVO_ERP, {
        "lida_em": datetime.now().isoformat(timespec="seconds"),
        "contas": sorted(contas, key=lambda c: c["nome"])}, pasta)
    return True


def ler_lista(pasta=None) -> list[dict]:
    contas = cache.ler_json(ARQUIVO_ERP, pasta).get("contas")
    if not isinstance(contas, list):
        return []
    return [c for c in contas if isinstance(c, dict) and c.get("nome")]


def mapa_do_painel(pasta_painel=None):
    """O `mapping.yaml` do painel, ou None nesta máquina não ter painel."""
    base = Path(pasta_painel or util.pasta_base())
    if not ((base / "mapping.yaml").exists() and (base / "config.yaml").exists()):
        return None
    try:
        from conciliacao.mapping import AccountMapping
        return AccountMapping.load(base / "mapping.yaml")
    except Exception:                                   # noqa: BLE001
        log.warning("lendo o mapping.yaml do painel", exc_info=True)
        return None


def _fora_do_painel(contas, mapa):
    from conciliacao.painel_novas import contas_fora_do_painel
    return contas_fora_do_painel(contas, mapa)


@dataclass
class Pendencia:
    conta: "contas_novas.ContaNova"
    erp: object                      # conciliacao.models.ErpAccount
    falta_cadastro: bool
    falta_painel: bool
    rotulo: str = ""

    nome = property(lambda s: s.conta.nome)
    banco = property(lambda s: s.conta.banco)
    agencia = property(lambda s: s.conta.agencia)
    numero = property(lambda s: s.conta.numero)
    resumo = property(lambda s: s.conta.resumo)
    pasta_sugerida = property(lambda s: s.conta.pasta_sugerida)

    def empresa_sugerida(self, nomes) -> str:
        return self.conta.empresa_sugerida(nomes)

    @property
    def falta_em(self) -> str:
        if self.falta_cadastro and self.falta_painel:
            return "cadastro e painel"
        return "cadastro" if self.falta_cadastro else "painel"


def pendencias(crus, pasta=None, pasta_painel=None) -> list[Pendencia]:
    from conciliacao.erp.api import conta_do_erp
    from conciliacao.painel_novas import rotulo_sugerido

    ativas = [c for c in (crus or []) if isinstance(c, dict)
              and c.get("isActive") is not False and c.get("name")]
    sem_cadastro = {n.id_erp for n in contas_novas.comparar(
        ativas, contas_novas.nomes_cadastrados(pasta),
        contas_novas.ignorados(pasta_painel or pasta))}
    mapa = mapa_do_painel(pasta_painel)
    erps = [conta_do_erp(c) for c in ativas]
    sem_painel = ({c.id for c in _fora_do_painel(erps, mapa)}
                  if mapa is not None else set())
    saida = []
    for cru, erp in zip(ativas, erps):
        fc, fp = erp.id in sem_cadastro, erp.id in sem_painel
        if fc or fp:
            saida.append(Pendencia(contas_novas.como_conta_nova(cru), erp,
                                   fc, fp, rotulo_sugerido(erp)))
    return sorted(saida, key=lambda p: p.nome)
```

Nota: `contas_novas.comparar` devolve `ContaNova` com `id_erp`; conferir com `grep -n "id_erp" nuvem/contas_novas.py` antes de usar. `ignorados` lê o `mapping.yaml` da pasta que receber — na máquina do dono, a pasta do painel e a dos dados são a mesma (`util.pasta_base()`).

- [ ] **Step 4:** `python -m pytest tests/test_contas_central.py -q` → PASS.
- [ ] **Step 5:** Commit `Contas: lista do ERP guardada num lugar so e o que falta em cadastro e painel`.

---

### Task 3: A janela única (cadastro + painel)

**Files:**
- Modify: `nuvem/contas_novas_dialogo.py`
- Test: `tests/test_contas_novas_dialogo.py` (atualizar os existentes, acrescentar novos)

**Interfaces:**
- Consumes: `Pendencia` (Task 2) — mas a janela aceita QUALQUER objeto com `nome, banco, agencia, numero, resumo, pasta_sugerida, empresa_sugerida(nomes)`; `falta_cadastro` vale `True` se ausente, `falta_painel` vale `False` se ausente, `rotulo` vale `nome` se ausente (os testes antigos usam `SimpleNamespace` sem esses campos).
- Produces:
  - `@dataclass Respostas`: `cadastro: list[dict]`, `painel: list[tuple]` (`(conta, rotulo)`), com `__bool__` = há algo em qualquer um.
  - `escolhas_marcadas(linhas, por_nome) -> list[dict]` — mesma saída de hoje; `linhas` passa a ser `[(conta, marcada, empresa, pasta, rotulo)]` e só entram as com `falta_cadastro`.
  - `painel_marcadas(linhas) -> list[tuple]` — `(conta, rotulo.strip())` das marcadas com `falta_painel`.
  - `perguntar(pai, novas, empresas) -> Respostas`.

Mudanças na janela:
- Colunas: `("marca", "conta", "falta", "erp", "empresa", "pasta", "linha")`, títulos `"", "CONTA NO ERP", "FALTA EM", "VINDOS DO ERP", "EMPRESA", "PASTA", "LINHA NO PAINEL"`. Para quem não falta no cadastro, empresa/pasta mostram "já cadastrada"; para quem não falta no painel, linha mostra "—".
- Editor: terceiro campo `"linha no painel:"` (`ttk.Entry`, `width=34`). Ao mostrar uma conta: combobox e pasta ficam `state="disabled"` se não falta no cadastro (`readonly`/`normal` caso contrário); o campo da linha fica `disabled` se não falta no painel.
- Texto do cabeçalho: `f"{len(novas)} conta(s) do Mais Controle faltando no app"`, e a frase de apoio acrescenta: "Quem falta no painel do Saldo de pagamentos entra com o nome da linha que está embaixo da lista."
- Botão "Cadastrar" passa a "Incluir".
- Estado: cada linha `[conta, marcada, empresa, pasta, rotulo]`; `escreveu` grava o rótulo também e atualiza a coluna `linha`.
- `confirmar()` monta `Respostas(escolhas_marcadas(...), painel_marcadas(linhas))`.
- Fechar/"Agora não" devolve `Respostas([], [])`.

- [ ] **Step 1: Atualizar/acrescentar testes**

No `tests/test_contas_novas_dialogo.py`:
- `test_so_as_marcadas_vao_e_a_empresa_vira_id`: linhas ganham o 5º elemento (`"ROTULO"`); asserções iguais.
- `test_sugerida_chega_marcada...`: troca `"Cadastrar"` por `"Incluir"`; `escolhas` vira `respostas.cadastro`; o `TEntry` da pasta deixa de ser o único — pegar os `TEntry` em ordem (`[w for w in _todos(top) if w.winfo_class() == "TEntry"]`, o primeiro é a pasta, o segundo a linha).
- `test_agora_nao_nao_grava_nada`: `assert not respostas` e `respostas.cadastro == [] and respostas.painel == []`.
- `_perguntar` devolve `(respostas, widgets)`.

Novos:

```python
def _pend(i, *, cadastro=True, painel=False, sugerida=""):
    c = _conta(i, sugerida)
    c.falta_cadastro, c.falta_painel = cadastro, painel
    c.rotulo = f"LINHA {i:02d}"
    return c


def test_painel_marcadas_so_quem_falta_no_painel():
    a, b = _pend(1, painel=True), _pend(2, painel=False)
    linhas = [(a, True, "EMPRESA MODELO", "P", " LINHA 01 "),
              (b, True, "EMPRESA MODELO", "P", "LINHA 02")]
    assert dialogo.painel_marcadas(linhas) == [(a, "LINHA 01")]


def test_quem_ja_tem_cadastro_nao_volta_para_o_cadastro():
    a = _pend(1, cadastro=False, painel=True)
    linhas = [(a, True, "", "", "LINHA 01")]
    assert dialogo.escolhas_marcadas(linhas, {}) == []
    assert dialogo.painel_marcadas(linhas) == [(a, "LINHA 01")]


def test_so_painel_trava_empresa_e_pasta_e_grava_a_linha(raiz, monkeypatch):
    novas = [_pend(1, cadastro=False, painel=True)]
    visto = {}

    def roteiro(top, tabela):
        visto["falta"] = tabela.set("0", "falta")
        visto["empresa"] = str(_um(top, "TCombobox").cget("state"))
        entradas = [w for w in _todos(top) if w.winfo_class() == "TEntry"]
        visto["pasta"] = str(entradas[0].cget("state"))
        entradas[1].delete(0, "end")
        entradas[1].insert(0, "LINHA NOVA")
        tabela.event_generate("<<AlternarMarca>>")
        next(w for w in _todos(top) if w.winfo_class() == "TButton"
             and str(w.cget("text")) == "Incluir").invoke()

    respostas, _w = _perguntar(raiz, monkeypatch, novas, roteiro)
    assert visto["falta"] == "painel"
    assert visto["empresa"] == "disabled" and visto["pasta"] == "disabled"
    assert respostas.cadastro == []
    assert respostas.painel == [(novas[0], "LINHA NOVA")]
```

(`_conta` hoje devolve `SimpleNamespace`, então dá para pôr atributos; `falta_em` vem por `getattr(conta, "falta_em", "cadastro")` na janela — no `_pend` acrescente `c.falta_em = "painel" if not cadastro else ("cadastro e painel" if painel else "cadastro")`.)

- [ ] **Step 2:** `python -m pytest tests/test_contas_novas_dialogo.py -q` → os novos e os atualizados FALHAM.
- [ ] **Step 3:** Implementar as mudanças descritas acima em `nuvem/contas_novas_dialogo.py`. Leitura tolerante: `getattr(conta, "falta_cadastro", True)`, `getattr(conta, "falta_painel", False)`, `getattr(conta, "rotulo", conta.nome)`, `getattr(conta, "falta_em", "cadastro")`. Atualizar o docstring do módulo (um parágrafo: "desde 05/10/2026 a mesma janela inclui no painel do Saldo").
- [ ] **Step 4:** `python -m pytest tests/test_contas_novas_dialogo.py -q` → PASS (todos, inclusive o de "não cresce com o número de contas").
- [ ] **Step 5:** Commit `Contas novas: uma janela so inclui no cadastro e no painel do Saldo`.

---

### Task 4: Aplicar as respostas (cadastro + painel) com um recado só

**Files:**
- Modify: `nuvem/contas_central.py`
- Test: `tests/test_contas_central.py`

**Interfaces:**
- Consumes: `Respostas` (Task 3), `contas_novas.gravar(token, escolhas) -> list[str]`, `painel_novas.{incluir_no_painel, Inclusao, InclusaoRecusada}`, `conta_do_erp`.
- Produces: `aplicar(token: str, respostas, crus: list, pasta_painel=None) -> str` — devolve o texto do recado (para `messagebox`). Nunca levanta por causa do painel; deixa subir erro do cadastro só se for de rede/SQL (o chamador já mostra `recado_de_erro`).

Regras:
- Cadastro primeiro (`gravar`); painel depois. Painel recusado não desfaz o cadastro.
- Para o painel: `Inclusao(p.erp, rotulo)` para cada `(p, rotulo)` de `respostas.painel`; `contas_erp = [conta_do_erp(c) for c in crus if isinstance(c, dict)]`.
- Recado: linhas `"N conta(s) cadastrada(s)."`, `"N conta(s) incluída(s) no painel do Saldo (linhas X a Y)."`, `"Não gravadas no cadastro:\n..."` com os avisos, e, se o painel recusar, `"O painel do Saldo NÃO mudou:\n<motivo>"`. Ao incluir no painel, acrescenta: `"Quem aporta em cada uma é a aba Regras do MODELO.xlsx."`.

- [ ] **Step 1: Testes que falham**

```python
from types import SimpleNamespace

from nuvem import contas_novas_dialogo as dialogo


def _p(i):
    from conciliacao.erp.api import conta_do_erp
    return SimpleNamespace(erp=conta_do_erp(_cru(i)), nome=_cru(i)["name"])


def test_aplica_cadastro_e_painel(monkeypatch, tmp_path):
    from conciliacao import painel_novas
    gravados, incluidos = [], []
    monkeypatch.setattr(cc.contas_novas, "gravar",
                        lambda tok, esc: gravados.extend(esc) or [])

    def incluir(pasta, inclusoes, contas_erp):
        incluidos.extend((i.conta.id, i.rotulo) for i in inclusoes)
        assert {c.id for c in contas_erp} == {"u-1", "u-2"}
        return painel_novas.ResultadoInclusao(linhas=[(34, "LINHA 02")],
                                             copia=tmp_path)

    monkeypatch.setattr(painel_novas, "incluir_no_painel", incluir)
    r = dialogo.Respostas(cadastro=[{"nome_erp": "X"}],
                          painel=[(_p(2), "LINHA 02")])
    recado = cc.aplicar("tok", r, [_cru(1), _cru(2)], tmp_path)
    assert gravados == [{"nome_erp": "X"}]
    assert incluidos == [("u-2", "LINHA 02")]
    assert "1 conta(s) cadastrada(s)." in recado
    assert "1 conta(s) incluída(s) no painel do Saldo (linha 34)." in recado


def test_painel_recusado_nao_desfaz_o_cadastro(monkeypatch, tmp_path):
    from conciliacao import painel_novas
    monkeypatch.setattr(cc.contas_novas, "gravar", lambda tok, esc: [])

    def recusa(*_a, **_k):
        raise painel_novas.InclusaoRecusada("o MODELO.xlsx está aberto no Excel")

    monkeypatch.setattr(painel_novas, "incluir_no_painel", recusa)
    r = dialogo.Respostas(cadastro=[{"nome_erp": "X"}],
                          painel=[(_p(1), "LINHA 01")])
    recado = cc.aplicar("tok", r, [_cru(1)], tmp_path)
    assert "1 conta(s) cadastrada(s)." in recado
    assert "O painel do Saldo NÃO mudou" in recado
    assert "aberto no Excel" in recado


def test_sem_painel_nao_chama_o_painel(monkeypatch, tmp_path):
    from conciliacao import painel_novas
    monkeypatch.setattr(cc.contas_novas, "gravar", lambda tok, esc: [])
    monkeypatch.setattr(painel_novas, "incluir_no_painel",
                        lambda *a, **k: pytest.fail("não devia incluir"))
    recado = cc.aplicar("tok", dialogo.Respostas([{"nome_erp": "X"}], []),
                        [_cru(1)], tmp_path)
    assert "painel" not in recado
```

(Para o recado com uma linha só, escreva "(linha 34)"; com várias, "(linhas 34 a 36)".)

- [ ] **Step 2:** rodar → FAIL. **Step 3:** implementar `aplicar` em `contas_central.py` (imports tardios de `conciliacao.painel_novas` e `conciliacao.erp.api`). **Step 4:** rodar → PASS.
- [ ] **Step 5:** Commit `Contas: aplicar a janela unica grava cadastro e painel com um recado so`.

---

### Task 5: A rodada central e o botão "Atualizar contas" na moldura

**Files:**
- Modify: `nuvem/contas_central.py` (orquestração testável)
- Modify: `comprovantes_app.py` (rodapé do menu, abertura, `_conferir_contas`/`_perguntar_contas`)
- Test: `tests/test_contas_central.py`

**Interfaces:**
- Consumes: Tasks 2-4; `contas_novas.{contas_do_erp, empresas}`; `cadastro.sincronizar`; `contas_novas_dialogo.perguntar`.
- Produces:
  - `ler_do_erp(pasta=None, log=print) -> list` — chama `contas_novas.contas_do_erp(log=log)`, guarda com `guardar_lista` e devolve os crus (vazio quando o ERP não respondeu).
  - `avisar_abas(quadros: dict, log=print) -> None` — para cada aba com `recarregar_contas`, chama dentro de `try` (aba que falha só vai para o log).
  - Na moldura: `_atualizar_contas(origem: str)` com `origem in ("abertura", "botao")`.

Fluxo (na moldura):
1. **Abertura** (thread, como hoje, antes de existir Chrome): `crus = contas_central.ler_do_erp(pasta, log=_anotar)`; `pend = contas_central.pendencias(crus, pasta)`; se `pend`, `empresas = contas_novas.empresas(token)` e `root.after(0, lambda: _perguntar(pend, empresas, token, crus))`.
2. **Botão** "⟳  Atualizar contas" no rodapé do menu, logo abaixo da pílula do cadastro (`widgets.Botao(lateral.rodape, ..., papel="neutro")`): se `aba_anx.avisar_se_ocupado("a atualização das contas")` → sai. Senão desliga o botão, e `aba_anx.submeter("Atualizar contas", _t_atualizar, dona=None)`; `_t_atualizar` roda na thread do navegador: `cadastro.sincronizar` → `ler_do_erp` → refaz o login do Chrome se estiver aberto (`cli = aba_anx.mc; if cli is not None and cli.vivo(): cli.garantir_login()`, dentro de `try`, como `conciliacao/frame._revalidar_navegador_aberto`) → `pendencias` → `root.after(0, ...)` para (a) atualizar a pílula com o resultado do `sincronizar` (`Pilula.definir(texto, estado)`), (b) `avisar_abas(quadros)`, (c) abrir a janela se houver pendência, ou `messagebox.showinfo("Contas", "Nenhuma conta nova. As abas já estão com a lista de agora.")`, e religar o botão.
3. `_perguntar(pend, empresas, token, crus)`: `respostas = contas_novas_dialogo.perguntar(root, pend, empresas)`; se vazio, sai; `recado = contas_central.aplicar(token, respostas, crus)`; depois, em thread: `cadastro.sincronizar(token, pasta)` e `root.after(0, lambda: (avisar_abas(quadros), pilula.definir(...)))`; mostra `messagebox.showinfo("Contas", recado)`.
4. A pílula guarda a referência (`_pilula_cadastro`), e o texto nasce igual ao de hoje.

- [ ] **Step 1: Testes que falham** (na `tests/test_contas_central.py`)

```python
def test_ler_do_erp_guarda_e_devolve(monkeypatch, tmp_path):
    monkeypatch.setattr(cc.contas_novas, "contas_do_erp",
                        lambda log=print: [_cru(1)])
    assert cc.ler_do_erp(tmp_path) == [_cru(1)]
    assert [c["id"] for c in cc.ler_lista(tmp_path)] == ["u-1"]


def test_erp_fora_do_ar_nao_apaga_a_lista(monkeypatch, tmp_path):
    cc.guardar_lista([_cru(1)], tmp_path)
    monkeypatch.setattr(cc.contas_novas, "contas_do_erp", lambda log=print: [])
    assert cc.ler_do_erp(tmp_path) == []
    assert [c["id"] for c in cc.ler_lista(tmp_path)] == ["u-1"]


def test_avisar_abas_chama_quem_tem_o_gancho_e_aguenta_falha():
    chamadas = []

    class Ok:
        def recarregar_contas(self):
            chamadas.append("ok")

    class Quebra:
        def recarregar_contas(self):
            raise RuntimeError("x")

    class Sem:
        pass

    linhas = []
    cc.avisar_abas({"a": Quebra(), "b": Ok(), "c": Sem()}, log=linhas.append)
    assert chamadas == ["ok"]
    assert any("a" in l for l in linhas)
```

E um teste de fiação lendo o fonte da moldura (a moldura não monta fora do `main()`):

```python
def test_a_moldura_usa_a_central_e_tem_o_botao():
    from pathlib import Path
    fonte = Path("comprovantes_app.py").read_text(encoding="utf-8")
    assert "Atualizar contas" in fonte
    assert "contas_central.ler_do_erp" in fonte
    assert "contas_central.avisar_abas" in fonte
    assert "avisar_se_ocupado(\"a atualização das contas\")" in fonte
    assert "contas_novas.novidades(" not in fonte
```

- [ ] **Step 2:** rodar → FAIL. **Step 3:** implementar `ler_do_erp`, `avisar_abas` e a fiação descrita acima em `comprovantes_app.py`, trocando `_conferir_contas`/`_perguntar_contas`. Manter o comentário grande que explica por que a abertura entra no ERP antes de existir Chrome. **Step 4:** `python -m pytest tests/test_contas_central.py tests/test_atalhos_do_app.py -q` → PASS; `python -m py_compile comprovantes_app.py`.
- [ ] **Step 5:** Commit `Contas: botao Atualizar contas no menu e a abertura usando a central`.

---

### Task 6: Saldo de pagamentos perde o "Verificar contas novas"

**Files:**
- Modify: `conciliacao/frame.py` (botão `self.b_contas`, `verificar_contas`, `_t_verificar`, `_janela_contas_novas`, ramo `"contas_novas"` do `_drain`)
- Delete: `conciliacao/contas_novas_janela.py`
- Modify: `tests/test_painel_novas.py` (tirar o import e os testes de `inclusoes_marcadas`)
- Test: `tests/test_conciliacao_sem_botao_de_contas.py` (novo)

- [ ] **Step 1: Teste que falha**

```python
# tests/test_conciliacao_sem_botao_de_contas.py
from pathlib import Path


def test_saldo_nao_tem_mais_busca_propria_de_contas():
    fonte = Path("conciliacao/frame.py").read_text(encoding="utf-8")
    assert "Verificar contas novas" not in fonte
    assert "contas_novas_janela" not in fonte
    assert not Path("conciliacao/contas_novas_janela.py").exists()


def test_a_aba_monta_sem_o_botao(raiz):
    from conciliacao.frame import ConciliacaoFrame

    class AnxDuble:
        mc = None

        def avisar_se_ocupado(self, _d):
            return False

    aba = ConciliacaoFrame(raiz, AnxDuble())
    try:
        assert not hasattr(aba, "b_contas")
        assert not hasattr(aba, "verificar_contas")
    finally:
        aba.destroy()
```

(Antes de escrever o segundo teste, conferir como os testes atuais montam `ConciliacaoFrame` — `grep -rn "ConciliacaoFrame(" tests/` — e usar o mesmo dublê; se não houver nenhum, fica só o primeiro teste.)

- [ ] **Step 2:** rodar → FAIL. **Step 3:** remover o botão, os três métodos, o ramo do `_drain` e o arquivo; `grep -rn "contas_novas_janela\|inclusoes_marcadas\|verificar_contas" --include=*.py .` tem de voltar vazio (fora `docs/`). Ajustar `tests/test_painel_novas.py`. **Step 4:** `python -m pytest tests/test_painel_novas.py tests/test_conciliacao_sem_botao_de_contas.py -q` → PASS.
- [ ] **Step 5:** Commit `Saldo de pagamentos: conta nova passa a ser so pela janela unica`.

---

### Task 7: Relatório Mensal lê a lista central

**Files:**
- Modify: `relatorios/relatorio_frame.py` (`_build`: botão `b1`, texto do `lbl_vazio`; `carregar`/`_t_carregar` saem; novos `recarregar_contas`, `ao_abrir`; `_t_gerar` resolve o id da tela)
- Modify: `relatorios/extrato_mc.py` (função pura `ids_da_tela`)
- Test: `tests/test_relatorio_lista_central.py` (novo)

**Interfaces:**
- Consumes: `contas_central.ler_lista(pasta=None) -> list[dict]` (chaves `id, nome, ...`).
- Produces: `extrato_mc.ids_da_tela(nomes: list[str], contas_tela: list[dict]) -> tuple[dict, list]` — `({nome: id_da_tela}, [nomes que não estão na tela])`, casando por `util.norm_espaco`.

Comportamento:
- `ao_abrir()` e `recarregar_contas()` montam a lista com `_montar_contas(contas_central.ler_lista())` (garantindo antes o `_garantir_mapa()`; se falhar, mostra o motivo no registro). Lista vazia mostra no `lbl_vazio`: `'Ainda não há lista de contas. Clique em "Atualizar contas", no rodapé do menu.'`.
- As chaves de `vars_contas`/`sem_destino`/`sem_banco` continuam sendo `conta["id"]` — agora o id da API. Marcações de quem já estava marcado sobrevivem ao `recarregar_contas` (guardar os nomes marcados antes e remarcar).
- O botão `b1` some; `b2` ("Gerar os extratos") nasce ligado quando há lista.
- `_t_gerar`: depois de `garantir_sessao`, `tela = extrato_mc.listar_contas(pagina)`; `ids, faltam = extrato_mc.ids_da_tela([c["nome"] for c in contas], tela)`; quem falta vai para `falhas` com "não aparece no fluxo de caixa do Mais Controle"; os outros usam `ids[nome]` no `abrir_extrato`. `conferir_antes_de_salvar` continua igual.

- [ ] **Step 1: Testes que falham**

```python
# tests/test_relatorio_lista_central.py
from relatorios import extrato_mc


def test_ids_da_tela_casa_pelo_nome_normalizado():
    tela = [{"id": 7, "nome": "Empresa  Modelo - SICOOB"},
            {"id": 8, "nome": "OUTRA EMPRESA MODELO - INTER"}]
    ids, faltam = extrato_mc.ids_da_tela(
        ["EMPRESA MODELO - SICOOB", "CONTA QUE SUMIU"], tela)
    assert ids == {"EMPRESA MODELO - SICOOB": 7}
    assert faltam == ["CONTA QUE SUMIU"]


def test_aba_monta_a_lista_sem_botao_de_carregar(raiz, monkeypatch):
    from relatorios import relatorio_frame as rf
    monkeypatch.setattr(rf.contas_central, "ler_lista", lambda pasta=None: [
        {"id": "u-1", "nome": "EMPRESA MODELO - SICOOB"}])

    class MapaDuble:
        raiz = "C:/x"

        def de(self, nome):
            return None

    class AnxDuble:
        mc = None

    aba = rf.RelatorioFrame(raiz, AnxDuble())
    try:
        aba.mapa = MapaDuble()
        monkeypatch.setattr(aba, "_garantir_mapa", lambda: True)
        aba.recarregar_contas()
        assert list(aba.vars_contas) == ["u-1"]
        assert aba.vars_contas["u-1"].get() is False   # sem pasta: desmarcada
        assert "Carregar contas" not in [str(b.cget("text")) for b in
                                         aba.cab.acoes.winfo_children()]
    finally:
        aba.destroy()
```

(Conferir antes o construtor real: `grep -n "def __init__" -A10 relatorios/relatorio_frame.py`; ajustar o dublê do `anexar_frame` ao que ele lê na construção.)

- [ ] **Step 2:** rodar → FAIL. **Step 3:** implementar (no topo do módulo: `from nuvem import contas_central`). Tirar o `"contas"` do `_drain` se ninguém mais o envia. **Step 4:** `python -m pytest tests/test_relatorio_lista_central.py tests/ -q -k "relatorio or extrato or rolagem"` → PASS.
- [ ] **Step 5:** Commit `Relatorio Mensal: lista de contas vem da busca central, sem Carregar contas`.

---

### Task 8: Os outros botões próprios saem; as abas ganham o gancho

**Files:**
- Modify: `baixar_comprovantes/comprovantes_frame.py` (sai "Atualizar lista"; `recarregar_contas = ao_abrir`)
- Modify: `aportes/aportes_frame.py` (sai o link "Recarregar cadastros"; `recarregar_contas` chama `_recarregar_cadastros`)
- Modify: `pagamentos_dia/pagamentos_frame.py` (`recarregar_contas` chama `_conferir_prontidao`)
- Modify: `anexar/anexar_comprovantes.py` (rótulo "Carregar contas" → "Buscar pagamentos" no botão, no texto vazio, no aviso "Primeiro clique em ..." e no docstring; o rótulo da fila `"Anexar — carregar contas"` → `"Anexar — buscar pagamentos"`)
- Test: `tests/test_ganchos_de_contas.py` (novo)

- [ ] **Step 1: Testes que falham**

```python
# tests/test_ganchos_de_contas.py
from pathlib import Path

import pytest


@pytest.mark.parametrize("arquivo,classe", [
    ("baixar_comprovantes/comprovantes_frame.py", "ComprovantesFrame"),
    ("aportes/aportes_frame.py", "AportesFrame"),
    ("pagamentos_dia/pagamentos_frame.py", "PagamentosDiaFrame"),
    ("relatorios/relatorio_frame.py", "RelatorioFrame"),
])
def test_aba_tem_o_gancho_da_busca_central(arquivo, classe):
    fonte = Path(arquivo).read_text(encoding="utf-8")
    assert f"class {classe}" in fonte
    assert "def recarregar_contas(self)" in fonte


def test_botoes_proprios_sairam():
    assert '"Atualizar lista"' not in Path(
        "baixar_comprovantes/comprovantes_frame.py").read_text(encoding="utf-8")
    assert '"Recarregar cadastros"' not in Path(
        "aportes/aportes_frame.py").read_text(encoding="utf-8")
    anexar = Path("anexar/anexar_comprovantes.py").read_text(encoding="utf-8")
    assert "Carregar contas" not in anexar
    assert "Buscar pagamentos" in anexar
```

E, para a aba que mais muda de comportamento, um teste montando a aba de verdade (Baixar Comprovantes, que só lê o cache): construir `ComprovantesFrame(raiz, lambda: MapaDuble)` como os testes atuais fazem (`grep -rn "ComprovantesFrame(" tests/`), chamar `recarregar_contas()` depois de trocar o dublê do mapa, e conferir que a tabela passou a ter a conta nova.

- [ ] **Step 2:** rodar → FAIL. **Step 3:** implementar. `grep -rn "Carregar contas\|Atualizar lista\|Recarregar cadastros" --include=*.py .` só pode sobrar em `tests/test_rolagem.py` (docstring; trocar o texto para "A busca central enche o cartão..."). **Step 4:** `python -m pytest tests -q -k "ganchos or comprovantes or aportes or pagamentos or anexar or rolagem"` → PASS.
- [ ] **Step 5:** Commit `Abas: sem botao proprio de contas; todas ouvem a busca central`.

---

### Task 9: Documentação e régua inteira

**Files:**
- Modify: `.claude/rules/nuvem-e-remessas.md` (parágrafo "Contas num lugar só": `contas_erp.json`, botão, janela única, ressincroniza depois de gravar)
- Modify: `.claude/rules/arquitetura-conciliacao.md` e `.claude/rules/arquitetura-relatorios.md` (o que saiu de cada aba)
- Modify: `docs/superpowers/specs/2026-08-21-conta-nova-no-erp-design.md` — só uma linha no topo: "Atualizado em 05/10/2026: ver 2026-10-05-contas-num-lugar-so-design.md".

- [ ] **Step 1:** Escrever os parágrafos (curtos, no estilo dos arquivos).
- [ ] **Step 2:** Régua completa: `ruff check --select E9,F .`, vermin 3.11 sobre os arquivos mudados, `python -m pytest tests -q`. Tudo verde (anotar o número de testes).
- [ ] **Step 3:** Commit `Docs: contas num lugar so`.
- [ ] **Step 4:** `git push -u origin codigo/contas-num-lugar-so` e abrir PR como **rascunho** (`gh pr create --draft`), corpo em português com: o que mudou por aba, as duas decisões do dono, o que fica para o dono provar no app (abrir o app, clicar em "Atualizar contas", ver a janela única). Não mesclar.
