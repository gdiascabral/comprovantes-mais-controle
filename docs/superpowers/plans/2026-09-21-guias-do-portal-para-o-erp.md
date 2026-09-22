# Guias do portal no Mais Controle — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um bloco novo na aba Acessórias que traz do portal do escritório tudo que vence no mês escolhido, mostra o que vai fazer, e — só depois da conferência do dono — altera a parcela da recorrência ou cria o título no Mais Controle, com o PDF anexado.

**Architecture:** Módulo `guias/` com sete arquivos de responsabilidade única: ler o portal, ler o PDF, classificar pela regra, decidir a ação, executar no ERP, registrar, e a tela. O acesso ao ERP é por API **de dentro da página logada** (`erp/pagina.TransportePagina`), o mesmo caminho dos aportes, porque o ERP aceita uma sessão por usuário. Nada é gravado sem o dono mandar, e nenhuma gravação é relatada como feita sem releitura que prove.

**Tech Stack:** Python 3.11, tkinter/ttk, Playwright (síncrono), pdfplumber, pytest. Nenhuma dependência nova.

**Spec:** `docs/superpowers/specs/2026-09-21-guias-do-portal-para-o-erp-design.md`

## Global Constraints

- **Alvo Python 3.11.** O CI roda `vermin --target=3.11`; escrever contra interpretador mais novo passa aqui e falha no usuário.
- **Nenhuma dependência nova.** `pdfplumber>=0.11,<1` e `playwright>=1.44,<2` já estão em `requirements.txt` e no `requirements.lock`. Se alguma tarefa precisar de biblioteca nova, o `requirements.lock` tem de ser recompilado com `uv` (`docs/DEPENDENCIAS.md`) — mas nenhuma tarefa deste plano precisa.
- **Repositório público.** Nome real de fornecedor, de escritório, de empresa, de obra, CPF e CNPJ não entram em código, em teste, em fixture nem em comentário. Nos testes, nomes inventados, como `tests/test_acessorias_envio.py` já faz. O endereço do escritório vem sempre de `Mapa.vip_url`, nunca de literal.
- **Testes:** `python -m pytest tests -q` na raiz do worktree. O CI roda, nesta ordem: `ruff check --select E9,F .`, conferência do `requirements.lock`, `vermin --target=3.11`, `pytest --cov`.
- **Teste de interface usa a fixture `raiz` do `conftest.py`** — um `Tk()` para a sessão inteira. Nunca criar e destruir `Tk()` próprio: os módulos seguintes passam a pular com "sem display". Tecla gerada em teste passa por `teclar`, nunca por `event_generate` cru.
- **Branch + PR sempre.** A `main` é protegida; nada entra por push direto. Este plano roda no worktree `_worktrees/app-guias`, branch `codigo/guias-acessorias`.
- **Caminho exibido ao usuário usa `/`.**
- **Nunca relatar sucesso sem prova.** Gravou → releia e compare. Anexou → liste e confirme. Sem a prova, o estado é outro, nunca "feito".

## Review Focus

Cinco entradas que o spec implica e que nenhum caminho feliz exercita. Cada uma tem o teste apontado na tarefa que é dona do código:

1. **Duas guias do mesmo tipo, na mesma empresa, no mesmo mês** (duas competências atrasadas): ambas apontariam para a MESMA recorrência, e a segunda sobrescreveria a primeira. Esperado: as duas vão para DECIDIR. → Tarefa 6.
2. **Valor do PDF diferente do valor que o portal mostra**: o PDF manda (é o documento que se paga), e a linha avisa da divergência em vez de escolher em silêncio. → Tarefa 6.
3. **Guia sem PDF** (download falhou, link expirado, arquivo não é PDF): nunca vira lançamento, nem com todos os outros campos lidos. → Tarefa 6.
4. **Valor com milhar e vírgula** (`R$ 1.234,56`) e vencimento em outro formato: a leitura devolve `Decimal("1234.56")`, e não 1,234 nem erro. → Tarefa 3.
5. **Rodada interrompida no meio** (botão Parar, ou queda entre gravar e anexar): nenhuma linha fica meio-gravada sem registro; o que já foi feito é reconhecido na rodada seguinte. → Tarefas 5 e 7.

---

## Estrutura de arquivos

**Criar:**

| Arquivo | Responsabilidade |
|---|---|
| `guias/__init__.py` | vazio (pacote) |
| `guias/modelos.py` | `Guia`, `Decisao`, `Resultado` e as constantes de ação |
| `guias/regras.py` | `_app/guias_regras.json`: classificar documento, aprender recorrência e obra |
| `guias/leitura.py` | texto do PDF → valor, vencimento, número do documento |
| `guias/calendario.py` | varrer as empresas do portal e baixar os PDFs do mês |
| `guias/casamento.py` | decidir ALTERAR / CRIAR / JÁ LANÇADO / DECIDIR |
| `guias/lancar.py` | executar no ERP e anexar, com conferência |
| `guias/registro.py` | `_app/guias_lancadas.jsonl` |
| `guias/painel.py` | o bloco de tela |

**Modificar:**

| Arquivo | O quê |
|---|---|
| `erp/pagina.py` | `JS_PUT_JSON` + `trocar()`; `JS_PUT_BINARIO` + `subir()` (vindo de `anexar/mc_api._JS_PUT_S3`, para não haver duas cópias) |
| `anexar/mc_api.py` | passa a importar `JS_PUT_BINARIO` em vez de ter a cópia |
| `acessorias/config.py` | `CAMINHO_CALENDARIO` e `SUBPASTA_GUIAS` |
| `acessorias/portal.py` | `empresas()`, `calendario()`, `baixar_guia()` |
| `acessorias/frame.py` | embute `guias.painel`, e `ocupado()`/`fechar()` passam a contar com ele |
| `comprovantes_app.py:326` | `AcessoriasFrame(conteudo, aba_anx)` |

**Testes:** `tests/test_guias_regras.py`, `test_guias_leitura.py`, `test_guias_calendario.py`, `test_guias_registro.py`, `test_guias_casamento.py`, `test_guias_lancar.py`, `test_guias_painel.py`; mais dois testes novos em `tests/test_erp.py`.

---

### Task 1: Tipos e o arquivo de regras

**Files:**
- Create: `guias/__init__.py`, `guias/modelos.py`, `guias/regras.py`
- Test: `tests/test_guias_regras.py`

**Interfaces:**
- Consumes: `util.pasta_base()`, `util.sem_acento()` (já existem)
- Produces:
  - `modelos.ALTERAR = "alterar"`, `CRIAR = "criar"`, `JA_LANCADO = "ja_lancado"`, `DECIDIR = "decidir"`
  - `modelos.Guia(vip_id, empresa, desc, anx_id, vencimento: date | None, competencia: str, pdf: Path | None, valor: Decimal | None, documento: str, erro: str)`
  - `modelos.Decisao(guia, acao: str, motivo: str, tipo: str, categoria: str, obra_id: str, favorecido: str, descricao: str, parcelas: int, trade_payable_id: str, parcela_id: str, aviso: str, obra_sugerida: bool)`
  - `modelos.Resultado(estado: str, tpid: str, motivo: str, anexos: list[str])`
  - `regras.Regras.carregar(caminho=None) -> Regras`
  - `Regras.classificar(desc: str) -> dict | None`
  - `Regras.recorrencia(tipo: str, vip_id: str) -> dict`
  - `Regras.aprender_recorrencia(tipo, vip_id, trade_payable_id, obra_id)`
  - `Regras.aprender_obra(tipo, vip_id, obra_id)`
  - `Regras.gravar()`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_guias_regras.py
# -*- coding: utf-8 -*-
"""A regra que diz o que fazer com cada documento do calendário.

Nomes INVENTADOS: o repositório é público.
"""
import json

import pytest

from guias import regras as mod


def _arquivo(tmp_path, dados):
    caminho = tmp_path / "guias_regras.json"
    caminho.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return caminho


def test_classifica_por_palavra_inteira_e_sem_acento(tmp_path):
    """"RET" não pode casar com "RETENCAO": casar por pedaço de palavra já
    produziu lançamento errado neste projeto (lote 1 x lote 10)."""
    caminho = _arquivo(tmp_path, {"versao": 1, "tipos": [
        {"nome": "regularizacao", "quando": {"desc_contem": ["RET"]},
         "acao": "criar", "categoria": "Taxa de abertura"},
    ]})
    r = mod.Regras.carregar(caminho)

    assert r.classificar("BOLETO RET 62 UNIDADES")["nome"] == "regularizacao"
    assert r.classificar("Guia de RETENCAO na fonte") is None


def test_classifica_ignorando_acento_e_caixa(tmp_path):
    caminho = _arquivo(tmp_path, {"versao": 1, "tipos": [
        {"nome": "honorario", "quando": {"desc_contem": ["HONORARIO"]},
         "acao": "alterar", "categoria": "Honorários"},
    ]})
    r = mod.Regras.carregar(caminho)

    assert r.classificar("Honorário contábil 09/2026")["acao"] == "alterar"


def test_arquivo_ausente_nao_quebra_e_nao_classifica_nada(tmp_path):
    """Primeiro mês: sem regra, tudo cai em "você decide" — e isso é o certo."""
    r = mod.Regras.carregar(tmp_path / "nao-existe.json")

    assert r.classificar("qualquer coisa") is None
    assert r.tipos == []


def test_versao_desconhecida_recusa_em_vez_de_adivinhar(tmp_path):
    caminho = _arquivo(tmp_path, {"versao": 99, "tipos": []})

    with pytest.raises(mod.RegraInvalida):
        mod.Regras.carregar(caminho)


def test_aprender_recorrencia_sobrevive_ao_disco(tmp_path):
    """O que o dono confirma uma vez não pode ser perguntado de novo."""
    caminho = _arquivo(tmp_path, {"versao": 1, "tipos": [
        {"nome": "honorario", "quando": {"desc_contem": ["HONORARIO"]},
         "acao": "alterar", "categoria": "Honorários"},
    ]})
    r = mod.Regras.carregar(caminho)

    r.aprender_recorrencia("honorario", "701", "tp-123", "obra-9")
    r.gravar()

    outra = mod.Regras.carregar(caminho)
    assert outra.recorrencia("honorario", "701") == {
        "trade_payable_id": "tp-123", "obra": "obra-9"}
    assert outra.recorrencia("honorario", "702") == {}


def test_nao_ha_conta_bancaria_em_regra_nenhuma(tmp_path):
    """Decisão do dono (21/09/2026): a conta vem da obra, nunca do cadastro."""
    caminho = _arquivo(tmp_path, {"versao": 1, "tipos": [
        {"nome": "honorario", "quando": {"desc_contem": ["HONORARIO"]},
         "acao": "alterar", "categoria": "Honorários", "conta": "alguma"},
    ]})

    with pytest.raises(mod.RegraInvalida) as e:
        mod.Regras.carregar(caminho)
    assert "conta" in str(e.value).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_guias_regras.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'guias'`

- [ ] **Step 3: Write `guias/modelos.py`**

```python
# -*- coding: utf-8 -*-
"""Os tipos que atravessam o módulo `guias`, num lugar só.

Ficam separados porque `casamento` e `lancar` não podem importar `painel`
(tkinter) nem `calendario` (Playwright) para saber com o que trabalham — é o
que deixa os dois testáveis sem tela e sem navegador.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

#: As quatro ações possíveis para uma guia do mês.
ALTERAR = "alterar"
CRIAR = "criar"
JA_LANCADO = "ja_lancado"
DECIDIR = "decidir"


@dataclass
class Guia:
    """Uma linha do calendário do portal, já com o PDF lido (ou o motivo de não)."""
    vip_id: str
    empresa: str
    desc: str
    anx_id: str
    competencia: str                     # "2026-09"
    vencimento: date | None = None
    pdf: Path | None = None
    valor: Decimal | None = None
    documento: str = ""
    erro: str = ""


@dataclass
class Decisao:
    """O que fazer com uma guia, antes de o dono confirmar."""
    guia: Guia
    acao: str
    motivo: str = ""
    tipo: str = ""
    categoria: str = ""
    obra_id: str = ""
    favorecido: str = ""
    descricao: str = ""
    parcelas: int = 1
    trade_payable_id: str = ""
    parcela_id: str = ""
    aviso: str = ""                      # divergência que não impede lançar
    #: A obra saiu de palpite sobre o texto do documento, e não da regra que o
    #: dono confirmou. A tela marca a linha para ele olhar antes de mandar.
    obra_sugerida: bool = False


@dataclass
class Resultado:
    """O desfecho de UMA gravação. `estado` nunca é "feito" sem prova."""
    estado: str
    tpid: str = ""
    motivo: str = ""
    anexos: list[str] = field(default_factory=list)


#: Os desfechos de `lancar`. "diverge" gravou mas não bateu na releitura;
#: "anexo_pendente" criou/alterou o título e o PDF não subiu.
ALTERADO = "alterado"
CRIADO = "criado"
DIVERGE = "diverge"
ANEXO_PENDENTE = "anexo_pendente"
ERRO = "erro"
```

- [ ] **Step 4: Write `guias/regras.py`**

```python
# -*- coding: utf-8 -*-
"""O cadastro que diz o que fazer com cada documento do calendário.

Mora em `_app/guias_regras.json`, e NÃO no repositório: carrega nome de
fornecedor e de obra, e o repositório é público — a mesma decisão já tomada
para o `contas_sicoob.json`.

Não existe conta bancária aqui. Em todo lançamento do Mais Controle, escolher
a obra já seleciona a conta, e a equipe deixa a que vem (decisão do dono,
21/09/2026). Conta é campo DERIVADO, e cadastro de campo derivado é uma
segunda fonte de verdade esperando divergir.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import util

log = util.log(__name__)

#: A versão que este código entende. Arquivo de versão maior foi escrito por
#: um app mais novo: recusar é melhor que ler metade e lançar com ela.
VERSAO = 1

NOME_ARQUIVO = "guias_regras.json"


class RegraInvalida(RuntimeError):
    """O arquivo de regras não serve. A mensagem é para o usuário final ler."""


def caminho_padrao() -> Path:
    return util.pasta_base() / NOME_ARQUIVO


def _chave(texto: str) -> str:
    return util.sem_acento(str(texto or "")).upper()


def _tem_palavra(texto: str, palavra: str) -> bool:
    """Casa PALAVRA INTEIRA, sem acento. "RET" não casa com "RETENCAO".

    Casar por pedaço de palavra já produziu erro neste projeto (o lote 1
    casando com o lote 10); aqui o estrago seria lançar o documento de um
    tipo com a categoria de outro."""
    if not palavra:
        return False
    return re.search(rf"(?<![0-9A-Z]){re.escape(_chave(palavra))}(?![0-9A-Z])",
                     _chave(texto)) is not None


class Regras:
    def __init__(self, caminho: Path, dados: dict):
        self.caminho = Path(caminho)
        self.dados = dados
        self.tipos: list[dict] = list(dados.get("tipos") or [])

    # ------------------------------------------------------------- leitura

    @classmethod
    def carregar(cls, caminho: Path | None = None) -> "Regras":
        caminho = Path(caminho or caminho_padrao())
        if not caminho.exists():
            # Primeiro mês: sem regra, toda guia cai em "você decide", que é
            # o comportamento correto — e não um erro para mostrar na tela.
            return cls(caminho, {"versao": VERSAO, "tipos": []})
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise RegraInvalida(f"não deu para ler {caminho.as_posix()}: {e}")
        versao = dados.get("versao")
        if versao != VERSAO:
            raise RegraInvalida(
                f"{caminho.as_posix()} está na versão {versao!r} e este app "
                f"entende a {VERSAO}. Atualize o app.")
        for tipo in dados.get("tipos") or []:
            if "conta" in tipo:
                raise RegraInvalida(
                    f"o tipo {tipo.get('nome')!r} tem \"conta\", e regra de "
                    "lançamento não tem conta bancária: a conta vem da obra. "
                    "Tire o campo do arquivo.")
        return cls(caminho, dados)

    def classificar(self, desc: str) -> dict | None:
        """O tipo cujo `desc_contem` casa com a descrição, ou None."""
        for tipo in self.tipos:
            termos = (tipo.get("quando") or {}).get("desc_contem") or []
            if any(_tem_palavra(desc, t) for t in termos):
                return tipo
        return None

    def recorrencia(self, tipo: str, vip_id: str) -> dict:
        """O que já se aprendeu sobre a recorrência deste tipo nesta empresa."""
        for t in self.tipos:
            if t.get("nome") == tipo:
                return dict((t.get("recorrencia") or {}).get(vip_id) or {})
        return {}

    def obra(self, tipo: str, vip_id: str) -> str:
        for t in self.tipos:
            if t.get("nome") == tipo:
                return str((t.get("obra") or {}).get(vip_id) or "")
        return ""

    # ----------------------------------------------------------- aprendizado

    def _tipo(self, nome: str) -> dict:
        for t in self.tipos:
            if t.get("nome") == nome:
                return t
        novo = {"nome": nome, "quando": {"desc_contem": []}}
        self.tipos.append(novo)
        self.dados["tipos"] = self.tipos
        return novo

    def aprender_recorrencia(self, tipo: str, vip_id: str,
                             trade_payable_id: str, obra_id: str = "") -> None:
        """Grava "esta guia é esta recorrência". É o que faz o casamento do mês
        seguinte ser exato, e não adivinhado pelo valor (que muda)."""
        alvo = self._tipo(tipo).setdefault("recorrencia", {})
        alvo[vip_id] = {"trade_payable_id": trade_payable_id, "obra": obra_id}

    def aprender_obra(self, tipo: str, vip_id: str, obra_id: str) -> None:
        self._tipo(tipo).setdefault("obra", {})[vip_id] = obra_id

    def gravar(self) -> None:
        self.dados["versao"] = VERSAO
        self.dados["tipos"] = self.tipos
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.caminho.write_text(
            json.dumps(self.dados, ensure_ascii=False, indent=1),
            encoding="utf-8")
        log.info("regras de guias gravadas (%d tipos)", len(self.tipos))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_guias_regras.py -q`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add guias/__init__.py guias/modelos.py guias/regras.py tests/test_guias_regras.py
git commit -m "Guias: tipos e o cadastro de regras, sem conta bancaria"
```

---

### Task 2: PUT no transporte da página logada

**Files:**
- Modify: `erp/pagina.py` (constantes ao lado de `JS_POST_JSON`; métodos ao lado de `postar`)
- Modify: `anexar/mc_api.py` (trocar `_JS_PUT_S3` pelo import)
- Test: `tests/test_erp.py` (junto dos testes de `TransportePagina`, a partir da linha 407)

**Interfaces:**
- Consumes: `erp/pagina.TransportePagina` (já existe), `_PaginaFalsa` de `tests/test_erp.py`
- Produces:
  - `pagina.JS_PUT_JSON`, `pagina.JS_PUT_BINARIO`
  - `TransportePagina.trocar(url: str, corpo: dict) -> dict` — PUT JSON; `{"__erro": status, "__corpo": …}` na recusa
  - `TransportePagina.subir(url: str, dados: bytes, content_type: str = "application/pdf") -> dict` — PUT binário cru; `{"status": int}`

- [ ] **Step 1: Write the failing test**

```python
# em tests/test_erp.py, depois de test_o_transporte_de_pagina_serve_o_baixa_erp_sem_adaptador

def test_o_put_manda_content_type_json_e_pode_ser_sobrescrito():
    """Mesma regra do POST: o `content-type` vem primeiro no Object.assign,
    para que um cabeçalho capturado da página possa trocá-lo."""
    falsa = _PaginaFalsa({"id": "tp-1"})
    transporte = pagina.TransportePagina(falsa, {"authorization": "Bearer x"})

    transporte.trocar(f"{hosts.LEGACY}/trade-payables/tp-1", {"value": 10})

    js, arg = falsa.chamadas[-1]
    assert "method: 'PUT'" in js
    assert arg["corpo"] == {"value": 10}
    assert arg["headers"]["authorization"] == "Bearer x"


def test_o_put_binario_nao_manda_authorization():
    """A URL pré-assinada do S3 recusa a requisição que traz `authorization`:
    a assinatura está na própria URL (`anexar/mc_api._JS_PUT_S3`)."""
    falsa = _PaginaFalsa({"status": 200})
    transporte = pagina.TransportePagina(falsa, {"authorization": "Bearer x"})

    transporte.subir("https://s3.exemplo.invalido/assinada", b"%PDF-1.4 ...")

    _js, arg = falsa.chamadas[-1]
    assert "authorization" not in {k.lower() for k in arg.get("headers", {})}
    assert arg["contentType"] == "application/pdf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_erp.py -q -k "put"`
Expected: FAIL com `AttributeError: 'TransportePagina' object has no attribute 'trocar'`

- [ ] **Step 3: Write the implementation in `erp/pagina.py`**

Acrescentar ao `__all__` e depois de `JS_POST_JSON`:

```python
__all__ = ["JS_FETCH_JSON", "JS_POST_JSON", "JS_PUT_JSON", "JS_PUT_BINARIO",
           "TransportePagina"]

#: PUT com corpo JSON. Mesma regra do POST quanto ao `content-type`.
JS_PUT_JSON = """async ({url, headers, corpo}) => {
  const r = await fetch(url, {
    method: 'PUT',
    headers: Object.assign({'content-type': 'application/json'}, headers),
    body: JSON.stringify(corpo),
  });
  let dados = null;
  try { dados = await r.json(); } catch (e) { dados = null; }
  if (!r.ok) return {__erro: r.status, __corpo: dados};
  return dados;
}"""

#: PUT cru do binário numa URL pré-assinada (S3). SÓ `Content-Type`: qualquer
#: outro cabeçalho — `authorization` em primeiro lugar — faz a assinatura da
#: URL não bater e o S3 recusar. Estava em `anexar/mc_api._JS_PUT_S3`; mora
#: aqui para haver UMA cópia da regra de transporte (o mesmo motivo de
#: `aportes/erp_sessao.py` existir).
JS_PUT_BINARIO = """async ({ url, b64, contentType }) => {
  const bin = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const r = await fetch(url, { method: 'PUT',
    headers: { 'Content-Type': contentType }, body: bin });
  return { status: r.status, body: (await r.text()).slice(0, 500) };
}"""
```

**O literal acima é o de `anexar/mc_api._JS_PUT_S3`, verbatim.** Mover uma
cópia não pode mudar o que ela faz: o campo `body` continua no retorno (a
docstring de `_put_s3` o promete) e a conversão segue sendo o
`Uint8Array.from`. Redigitar "parecido" aqui seria trocar uma duplicação por
uma divergência silenciosa, que é pior.

E, depois de `postar`:

```python
    def trocar(self, url: str, corpo: dict):
        """PUT. Devolve o JSON, ou `{"__erro": status, "__corpo": …}`."""
        return self.pagina.evaluate(
            JS_PUT_JSON,
            {"url": url, "headers": self.cabecalhos_para(url), "corpo": corpo})

    def subir(self, url: str, dados: bytes,
              content_type: str = "application/pdf"):
        """PUT do binário cru na URL pré-assinada. Devolve `{"status": …}`.

        Sem cabeçalho de autenticação, de propósito: a assinatura está na URL.
        """
        return self.pagina.evaluate(
            JS_PUT_BINARIO,
            {"url": url, "b64": base64.b64encode(dados).decode(),
             "contentType": content_type})
```

Acrescentar `import base64` no topo do arquivo, junto dos outros imports.

- [ ] **Step 4: Point `anexar/mc_api.py` at the single copy**

Trocar a definição de `_JS_PUT_S3` por:

```python
from erp.pagina import JS_POST_JSON, JS_PUT_BINARIO

#: Mantido com o nome antigo para os usos locais; a regra mora em
#: `erp/pagina.JS_PUT_BINARIO`, para não haver duas cópias.
_JS_PUT_S3 = JS_PUT_BINARIO
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_erp.py tests/test_anexar_por_api.py -q`
Expected: todos passam — os de `test_anexar_por_api.py` provam que o anexo que já funcionava não mudou de comportamento.

- [ ] **Step 6: Commit**

```bash
git add erp/pagina.py anexar/mc_api.py tests/test_erp.py
git commit -m "Transporte da pagina: PUT JSON e PUT binario numa copia so"
```

---

### Task 3: Ler valor, vencimento e número do documento do PDF

**Files:**
- Create: `guias/leitura.py`
- Test: `tests/test_guias_leitura.py`

**Interfaces:**
- Consumes: `guias.modelos` (nada obrigatório), `pdfplumber`
- Produces:
  - `leitura.ItemLido(valor: Decimal | None, vencimento: date | None, documento: str, pagina: int)`
  - `leitura.ler_texto(texto: str, pagina: int = 1) -> ItemLido`
  - `leitura.ler_pdf(caminho: Path) -> list[ItemLido]` — um item por página com cobrança

A separação importa: `ler_texto` é função pura e é onde mora toda a regra; `ler_pdf` só extrai texto com pdfplumber e delega. Assim o teste não precisa de PDF nenhum — e guia real tem CNPJ e nome de fornecedor, que não entram no repositório.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_guias_leitura.py
# -*- coding: utf-8 -*-
"""Leitura do texto de uma guia/boleto. Texto INVENTADO: o repo é público."""
from datetime import date
from decimal import Decimal

from guias import leitura


def test_valor_com_milhar_e_virgula():
    """`R$ 1.234,56` é mil duzentos e trinta e quatro — não 1,234 e não erro."""
    item = leitura.ler_texto("Valor do documento R$ 1.234,56")

    assert item.valor == Decimal("1234.56")


def test_valor_sem_milhar():
    assert leitura.ler_texto("Valor R$ 641,31").valor == Decimal("641.31")


def test_vencimento_em_dd_mm_aaaa():
    item = leitura.ler_texto("Vencimento 18/09/2026")

    assert item.vencimento == date(2026, 9, 18)


def test_numero_do_documento_pelo_rotulo():
    item = leitura.ler_texto("Nosso numero 0126090459266352-0")

    assert item.documento == "0126090459266352-0"


def test_linha_digitavel_vira_documento_quando_nao_ha_rotulo():
    """Boleto sem "nosso número" legível ainda tem a linha digitável."""
    linha = "34191.79001 01043.510047 91020.150008 1 96610000104200"
    item = leitura.ler_texto(f"Pague em qualquer banco {linha}")

    assert item.documento.replace(".", "").replace(" ", "").isdigit()
    assert len(item.documento.replace(".", "").replace(" ", "")) >= 44


def test_texto_sem_nada_devolve_item_vazio_e_nao_explode():
    item = leitura.ler_texto("pagina em branco")

    assert item.valor is None
    assert item.vencimento is None
    assert item.documento == ""


def test_duas_paginas_com_cobranca_viram_dois_itens(tmp_path, monkeypatch):
    """Guia com duas cobranças no mesmo arquivo (imposto + consignado) é
    separada por página: uma cobrança, um lançamento."""
    paginas = ["Valor R$ 10,00 Vencimento 01/09/2026 Nosso numero AAA",
               "Valor R$ 20,00 Vencimento 02/09/2026 Nosso numero BBB"]
    monkeypatch.setattr(leitura, "_paginas_de_texto", lambda _c: paginas)

    itens = leitura.ler_pdf(tmp_path / "qualquer.pdf")

    assert [i.valor for i in itens] == [Decimal("10.00"), Decimal("20.00")]
    assert [i.pagina for i in itens] == [1, 2]


def test_pagina_sem_cobranca_nao_vira_item(tmp_path, monkeypatch):
    paginas = ["Valor R$ 10,00 Vencimento 01/09/2026 Nosso numero AAA",
               "Instrucoes ao caixa: nao receber apos o vencimento"]
    monkeypatch.setattr(leitura, "_paginas_de_texto", lambda _c: paginas)

    assert len(leitura.ler_pdf(tmp_path / "qualquer.pdf")) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_guias_leitura.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'guias.leitura'`

- [ ] **Step 3: Write the implementation**

```python
# -*- coding: utf-8 -*-
"""Do texto de uma guia/boleto para valor, vencimento e número do documento.

`ler_texto` é pura de propósito: é nela que mora toda a regra, e é ela que o
teste exercita. `ler_pdf` só extrai o texto e delega — assim nenhum PDF real
precisa entrar no repositório, que é público.

Os boletos da contabilidade têm texto (não são imagem), então não há OCR aqui.
PDF sem texto devolve lista vazia, e quem chamou trata como "não consegui ler".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import util

log = util.log(__name__)

#: `1.234,56` e `641,31`. O milhar é opcional e os centavos não: valor sem
#: centavos num boleto é quase sempre outro número da página (código, conta).
RE_VALOR = re.compile(r"R?\$?\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]+),([0-9]{2})")
RE_VALOR_ROTULO = re.compile(
    r"(?:valor\s+(?:do\s+)?(?:documento|cobran[çc]a|total)?)\s*[:\-]?\s*"
    r"R?\$?\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]+),([0-9]{2})", re.I)
RE_VENCIMENTO = re.compile(
    r"vencimento\s*[:\-]?\s*([0-3]?[0-9])[/.-]([01]?[0-9])[/.-](20[0-9]{2})", re.I)
RE_DOCUMENTO = re.compile(
    r"(?:nosso\s*n[uú]mero|n[uú]mero\s*(?:do\s*)?documento|documento)\s*"
    r"[:\-]?\s*([0-9][0-9./\-]{5,})", re.I)
#: A linha digitável do boleto: 47 dígitos com pontos e espaços, ou 44 corridos.
RE_LINHA = re.compile(r"\b([0-9]{5}[.\s][0-9]{5,6}[\s.][0-9]{5}[.\s][0-9]{6}"
                      r"[\s.][0-9]{5}[.\s][0-9]{6}[\s.][0-9][\s.][0-9]{14})\b")


@dataclass
class ItemLido:
    valor: Decimal | None = None
    vencimento: date | None = None
    documento: str = ""
    pagina: int = 1

    @property
    def tem_cobranca(self) -> bool:
        """Página que vale um lançamento: tem valor E (vencimento ou documento)."""
        return self.valor is not None and bool(self.vencimento or self.documento)


def _decimal(inteiro: str, centavos: str) -> Decimal | None:
    try:
        return Decimal(f"{inteiro.replace('.', '')}.{centavos}")
    except InvalidOperation:
        return None


def ler_texto(texto: str, pagina: int = 1) -> ItemLido:
    texto = texto or ""
    item = ItemLido(pagina=pagina)

    achado = RE_VALOR_ROTULO.search(texto) or RE_VALOR.search(texto)
    if achado:
        item.valor = _decimal(achado.group(1), achado.group(2))

    venc = RE_VENCIMENTO.search(texto)
    if venc:
        dia, mes, ano = (int(g) for g in venc.groups())
        try:
            item.vencimento = date(ano, mes, dia)
        except ValueError:
            log.warning("vencimento fora do calendário numa guia")

    doc = RE_DOCUMENTO.search(texto)
    if doc:
        item.documento = doc.group(1).strip()
    else:
        linha = RE_LINHA.search(texto)
        if linha:
            item.documento = linha.group(1).strip()
    return item


def _paginas_de_texto(caminho: Path) -> list[str]:
    """O texto de cada página. Isolado para o teste não precisar de PDF."""
    import pdfplumber
    with pdfplumber.open(str(caminho)) as pdf:
        return [(p.extract_text() or "") for p in pdf.pages]


def ler_pdf(caminho: Path) -> list[ItemLido]:
    """Um item por página que tenha cobrança. Lista vazia = não deu para ler."""
    try:
        paginas = _paginas_de_texto(Path(caminho))
    except Exception:
        log.warning("não deu para abrir a guia com o pdfplumber", exc_info=True)
        return []
    itens = [ler_texto(t, i) for i, t in enumerate(paginas, start=1)]
    return [i for i in itens if i.tem_cobranca]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_guias_leitura.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add guias/leitura.py tests/test_guias_leitura.py
git commit -m "Guias: ler valor, vencimento e documento do texto da guia"
```

---

### Task 4: Varrer o calendário do portal e baixar as guias

**Files:**
- Modify: `acessorias/config.py` (duas constantes, junto dos outros caminhos)
- Modify: `acessorias/portal.py` (três métodos, depois de `_ir`)
- Create: `guias/calendario.py`
- Test: `tests/test_guias_calendario.py`

**Interfaces:**
- Consumes: `acessorias.portal.PortalClient` (`_ir`, `_conferir_sessao`, `ctx`, `page`), `guias.modelos.Guia`, `guias.leitura.ler_pdf`
- Produces:
  - `PortalClient.empresas() -> list[tuple[str, str]]` — `[(vip_id, nome na tela)]`
  - `PortalClient.calendario(vip_id: str, ano: int, mes: int) -> dict` — o `dataJson` do mês
  - `PortalClient.baixar_guia(lnk: str, destino: Path) -> Path` — levanta `RuntimeError` se não vier PDF
  - `calendario.itens_do_mes(cal: dict) -> list[dict]` — só os que têm vencimento e não são certidão
  - `calendario.varrer(cliente, mapa, ano, mes, pasta_de, log, parar) -> list[Guia]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_guias_calendario.py
# -*- coding: utf-8 -*-
"""A varredura do calendário do portal, sem navegador.

O portal é site de terceiro e segue fora de teste de verdade; o que se prova
aqui é a REGRA: o que entra, o que fica de fora, e que guia sem PDF não vira
lançamento. Nomes e endereços INVENTADOS: o repositório é público.
"""
from pathlib import Path

import pytest

from guias import calendario as mod
from guias import leitura

CAL = {
    "12": [
        {"desc": "HONORARIO CONTABIL 09/2026", "prz": "12/09/2026",
         "TemVcto": "S", "AnxID": "111", "lnk": "https://exemplo.invalido/1"},
        {"desc": "CND FEDERAL", "prz": "12/09/2026",
         "TemVcto": "S", "AnxID": "112", "lnk": "https://exemplo.invalido/2"},
    ],
    "18": [
        {"desc": "BALANCETE 08/2026", "prz": "18/09/2026",
         "TemVcto": "N", "AnxID": "113", "lnk": "https://exemplo.invalido/3"},
    ],
}


def test_so_entra_o_que_tem_vencimento_e_nao_e_certidao():
    itens = mod.itens_do_mes(CAL)

    assert [i["AnxID"] for i in itens] == ["111"]


def test_calendario_vazio_nao_quebra():
    assert mod.itens_do_mes({}) == []
    assert mod.itens_do_mes(None) == []


# ------------------------------------------------------------ portal falso

class _PortalFalso:
    def __init__(self, falhar_download=()):
        self.baixados = []
        self.falhar = set(falhar_download)

    def empresas(self):
        return [("701", "EMPRESA UM"), ("702", "EMPRESA DOIS")]

    def calendario(self, vip_id, ano, mes):
        return CAL if vip_id == "701" else {}

    def baixar_guia(self, lnk, destino):
        if lnk in self.falhar:
            raise RuntimeError("o link da guia expirou")
        self.baixados.append(destino)
        Path(destino).write_bytes(b"%PDF-1.4 fingido")
        return Path(destino)


class _MapaFalso:
    class _Empresa:
        def __init__(self, vip_id, nome):
            self.vip_id, self.nome = vip_id, nome

    empresas = [_Empresa("701", "EMPRESA UM")]


def test_varre_le_e_devolve_uma_guia_por_cobranca(tmp_path, monkeypatch):
    monkeypatch.setattr(
        mod.leitura, "ler_pdf",
        lambda _c: [leitura.ItemLido(valor=None, documento="DOC-1")])
    portal = _PortalFalso()

    guias = mod.varrer(portal, _MapaFalso(), 2026, 9,
                       pasta_de=lambda _e: tmp_path, log=lambda _m: None)

    assert len(guias) == 1
    assert guias[0].vip_id == "701"
    assert guias[0].documento == "DOC-1"
    assert guias[0].pdf is not None


def test_empresa_do_portal_sem_cadastro_vira_linha_de_aviso(tmp_path):
    """O id vem do portal, mas sem empresa cadastrada não há pasta para o PDF
    nem obra para o lançamento — e some em silêncio é o que não pode."""
    portal = _PortalFalso()

    guias = mod.varrer(portal, _MapaFalso(), 2026, 9,
                       pasta_de=lambda _e: tmp_path, log=lambda _m: None)

    avisos = [g for g in guias if g.vip_id == "702"]
    assert len(avisos) == 1
    assert "cadastr" in avisos[0].erro.lower()
    assert avisos[0].pdf is None


def test_guia_cujo_download_falhou_fica_com_erro_e_sem_pdf(tmp_path):
    """Review Focus 3: sem PDF não se lança, por mais completo que esteja."""
    portal = _PortalFalso(falhar_download=["https://exemplo.invalido/1"])

    guias = mod.varrer(portal, _MapaFalso(), 2026, 9,
                       pasta_de=lambda _e: tmp_path, log=lambda _m: None)

    guia = [g for g in guias if g.anx_id == "111"][0]
    assert guia.pdf is None
    assert "expirou" in guia.erro


def test_download_e_tentado_de_novo_uma_vez(tmp_path, monkeypatch):
    """O link do iframe expira em 120 s: a segunda tentativa pede um link novo,
    e é ela que costuma funcionar. Tentar mais que isso só demora."""
    tentativas = []

    class _PortalTeimoso(_PortalFalso):
        def baixar_guia(self, lnk, destino):
            tentativas.append(lnk)
            if len(tentativas) == 1:
                raise RuntimeError("o link da guia expirou")
            Path(destino).write_bytes(b"%PDF-1.4 fingido")
            return Path(destino)

    monkeypatch.setattr(
        mod.leitura, "ler_pdf",
        lambda _c: [leitura.ItemLido(valor=None, documento="DOC-1")])

    guias = mod.varrer(_PortalTeimoso(), _MapaFalso(), 2026, 9,
                       pasta_de=lambda _e: tmp_path, log=lambda _m: None)

    assert len(tentativas) == 2
    assert [g for g in guias if g.vip_id == "701"][0].pdf is not None


def test_parar_interrompe_entre_empresas(tmp_path):
    portal = _PortalFalso()

    guias = mod.varrer(portal, _MapaFalso(), 2026, 9,
                       pasta_de=lambda _e: tmp_path, log=lambda _m: None,
                       parar=lambda: True)

    assert guias == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_guias_calendario.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'guias.calendario'`

- [ ] **Step 3: Add the two constants to `acessorias/config.py`**

Junto dos outros caminhos, depois de `CAMINHO_SOLICITACAO_NOVA`:

```python
#: Calendário de uma empresa num mês. A página já traz o mês inteiro num JSON
#: (`dataJson`), então é UMA ida ao portal por empresa, e não uma por dia.
CAMINHO_CALENDARIO = "/{vip_id}/CLD/{competencia}"

#: Onde as guias baixadas ficam, dentro da pasta da empresa no mês.
SUBPASTA_GUIAS = "GUIAS"

#: O link do documento devolve um HTML com um iframe apontando para um S3 que
#: expira em 120 s: o download vem LOGO em seguida, na mesma passada.
RE_IFRAME = r"<iframe[^>]+src=['\"]([^'\"]+)['\"]"
```

- [ ] **Step 4: Add the three methods to `acessorias/portal.py`**

Depois de `_ir`, antes da seção de solicitações:

```python
    # ------------------------------------------------------ calendário

    def empresas(self) -> list[tuple[str, str]]:
        """As empresas do "Trocar empresa": [(vip_id, nome na tela)].

        Sai do portal, e não do nosso cadastro: empresa que o escritório
        passou a atender aparece aqui antes de alguém cadastrá-la, e some em
        silêncio é justamente o que não pode acontecer com guia a pagar."""
        self.page.goto(self.vip_url, wait_until="domcontentloaded")
        self._conferir_sessao()
        caminho = urlsplit(self.vip_url).path.rstrip("/")
        brutos = self.page.evaluate(
            """(caminho) => [...document.querySelectorAll('[onclick]')]
                 .map(e => [(e.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 90),
                            e.getAttribute('onclick') || ''])
                 .filter(x => x[1].includes(caminho + '/'))""",
            caminho)
        vistos, saida = set(), []
        for texto, onclick in brutos:
            achado = re.search(re.escape(caminho) + r"/(\d+)", onclick)
            if achado and achado.group(1) not in vistos:
                vistos.add(achado.group(1))
                saida.append((achado.group(1), texto))
        return saida

    def calendario(self, vip_id: str, ano: int, mes: int) -> dict:
        """O `dataJson` do mês: {dia: [documento, …]}. `{}` quando não há."""
        self._ir(cfg.CAMINHO_CALENDARIO, vip_id=vip_id,
                 competencia=f"{ano:04d}-{mes:02d}")
        dados = self.page.evaluate(
            "() => (typeof dataJson !== 'undefined') ? dataJson : null")
        return dados if isinstance(dados, dict) else {}

    def baixar_guia(self, lnk: str, destino: Path) -> Path:
        """Baixa o PDF do documento. O link do iframe expira em 120 s."""
        resposta = self.ctx.request.get(lnk)
        achado = re.search(cfg.RE_IFRAME, resposta.text() or "")
        if not achado:
            raise RuntimeError("o portal não devolveu o documento")
        arquivo = self.ctx.request.get(achado.group(1))
        dados = arquivo.body()
        if dados[:4] != b"%PDF":
            raise RuntimeError(
                "o que veio não é PDF (o link da guia costuma expirar em 2 min)")
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(dados)
        return destino
```

Acrescentar `from urllib.parse import urlsplit` e `from pathlib import Path` aos imports do topo, se ainda não estiverem.

- [ ] **Step 5: Write `guias/calendario.py`**

```python
# -*- coding: utf-8 -*-
"""Varre o calendário do portal e baixa as guias do mês.

Uma ida ao portal por empresa: a página do calendário já traz o mês inteiro.
Baixar marca o documento como lido no portal (some o "Novo") — efeito
conhecido e aceito, porque é o mesmo que a pessoa faria à mão.
"""
from __future__ import annotations

from pathlib import Path

import util
from acessorias import config as cfg
from guias import leitura
from guias.modelos import Guia

log = util.log(__name__)

#: Certidão não é conta a pagar. É o único descarte por assunto.
PREFIXOS_FORA = ("CND",)


def itens_do_mes(cal: dict | None) -> list[dict]:
    """Os documentos do mês que têm pagamento, em ordem de dia."""
    saida = []
    for _dia, itens in sorted((cal or {}).items()):
        for item in itens or []:
            desc = str(item.get("desc") or "")
            if item.get("TemVcto") != "S":
                continue
            if desc.upper().startswith(PREFIXOS_FORA):
                continue
            saida.append(item)
    return saida


def _nome_do_arquivo(vip_id: str, item: dict) -> str:
    dia = str(item.get("prz") or "")[:2] or "00"
    return f"{vip_id}_{dia}_{item.get('AnxID')}.pdf"


def varrer(cliente, mapa, ano: int, mes: int, *, pasta_de, log=print,
           parar=None) -> list[Guia]:
    """As guias do mês, já baixadas e lidas.

    `pasta_de(empresa)` devolve a pasta onde o PDF daquela empresa vai. `parar`
    é consultado ENTRE empresas: interromper no meio de uma deixaria metade
    das guias baixadas sem ninguém saber quais.
    """
    competencia = f"{ano:04d}-{mes:02d}"
    por_vip = {e.vip_id: e for e in mapa.empresas if getattr(e, "vip_id", "")}
    guias: list[Guia] = []

    for vip_id, nome_na_tela in cliente.empresas():
        if parar and parar():
            log("Parado a pedido.")
            return guias
        empresa = por_vip.get(vip_id)
        if empresa is None:
            guias.append(Guia(
                vip_id=vip_id, empresa=nome_na_tela, desc="", anx_id="",
                competencia=competencia,
                erro="empresa do portal sem cadastro aqui: sem pasta para o "
                     "PDF e sem obra para o lançamento"))
            continue

        pasta = Path(pasta_de(empresa)) / cfg.SUBPASTA_GUIAS
        itens = itens_do_mes(cliente.calendario(vip_id, ano, mes))
        log(f"{empresa.nome}: {len(itens)} documento(s) a pagar em {competencia}.")

        for item in itens:
            guias.extend(_uma_guia(cliente, empresa, item, competencia, pasta))
    return guias


def _uma_guia(cliente, empresa, item: dict, competencia: str,
              pasta: Path) -> list[Guia]:
    base = Guia(vip_id=empresa.vip_id, empresa=empresa.nome,
                desc=str(item.get("desc") or ""),
                anx_id=str(item.get("AnxID") or ""), competencia=competencia)
    destino = pasta / _nome_do_arquivo(empresa.vip_id, item)

    # Duas tentativas, e não mais: o link do iframe expira em 120 s e a
    # segunda passada pede um link novo. Insistir além disso só demora.
    ultimo = ""
    for _ in range(2):
        try:
            cliente.baixar_guia(item.get("lnk") or "", destino)
            ultimo = ""
            break
        except Exception as e:
            ultimo = str(e)[:200]
            log.warning("não deu para baixar uma guia do portal", exc_info=True)
    if ultimo:
        base.erro = ultimo
        return [base]

    itens = leitura.ler_pdf(destino)
    if not itens:
        base.pdf = destino
        base.erro = "não consegui ler valor nem vencimento no PDF"
        return [base]

    saida = []
    for lido in itens:
        guia = Guia(vip_id=base.vip_id, empresa=base.empresa, desc=base.desc,
                    anx_id=base.anx_id, competencia=competencia, pdf=destino,
                    valor=lido.valor, vencimento=lido.vencimento,
                    documento=lido.documento)
        if len(itens) > 1:
            # Duas cobranças no mesmo arquivo: o `anx_id` deixa de ser único,
            # e a trava do registro depende dele.
            guia.anx_id = f"{base.anx_id}p{lido.pagina}"
        saida.append(guia)
    return saida
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_guias_calendario.py tests/test_acessorias_envio.py -q`
Expected: 8 passed no arquivo novo; os de `test_acessorias_envio.py` seguem passando (o `PortalClient` ganhou métodos, não mudou os que existiam).

- [ ] **Step 7: Commit**

```bash
git add acessorias/config.py acessorias/portal.py guias/calendario.py tests/test_guias_calendario.py
git commit -m "Guias: varrer o calendario do portal e baixar os PDFs do mes"
```

---

### Task 5: O registro do que cada rodada fez

**Files:**
- Create: `guias/registro.py`
- Test: `tests/test_guias_registro.py`

**Interfaces:**
- Consumes: `util.pasta_base()`
- Produces:
  - `registro.Registro.carregar(caminho=None) -> Registro`
  - `Registro.ja_feito(vip_id: str, anx_id: str, competencia: str) -> dict | None`
  - `Registro.anotar(**campos) -> None` — grava uma linha e mantém o índice em memória
  - `registro.caminho_padrao() -> Path`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_guias_registro.py
# -*- coding: utf-8 -*-
"""O livro do que cada rodada lançou. É uma das duas travas contra duplicar."""
from guias import registro as mod


def test_anotar_e_reconhecer_na_rodada_seguinte(tmp_path):
    caminho = tmp_path / "guias_lancadas.jsonl"
    r = mod.Registro.carregar(caminho)
    r.anotar(vip_id="701", anx_id="111", competencia="2026-09",
             acao="alterar", tpid="tp-1", conferido=True)

    outra = mod.Registro.carregar(caminho)

    assert outra.ja_feito("701", "111", "2026-09")["tpid"] == "tp-1"
    assert outra.ja_feito("701", "111", "2026-10") is None
    assert outra.ja_feito("702", "111", "2026-09") is None


def test_linha_de_erro_nao_conta_como_feito(tmp_path):
    """Review Focus 5: a rodada caiu entre gravar e anexar. O que falhou tem
    de ser tentado de novo, e não pulado como se estivesse pronto."""
    caminho = tmp_path / "guias_lancadas.jsonl"
    r = mod.Registro.carregar(caminho)
    r.anotar(vip_id="701", anx_id="111", competencia="2026-09",
             acao="criar", estado="erro", motivo="o ERP recusou (HTTP 400)")

    assert mod.Registro.carregar(caminho).ja_feito("701", "111", "2026-09") is None


def test_anexo_pendente_conta_como_feito_para_nao_duplicar_o_titulo(tmp_path):
    """O título FOI criado. Repetir criaria um segundo — o que falta é o anexo,
    e isso a tela mostra como pendência, não como lançamento a refazer."""
    caminho = tmp_path / "guias_lancadas.jsonl"
    r = mod.Registro.carregar(caminho)
    r.anotar(vip_id="701", anx_id="111", competencia="2026-09",
             acao="criar", estado="anexo_pendente", tpid="tp-9")

    feito = mod.Registro.carregar(caminho).ja_feito("701", "111", "2026-09")
    assert feito["tpid"] == "tp-9"
    assert feito["estado"] == "anexo_pendente"


def test_arquivo_com_linha_corrompida_nao_derruba_a_leitura(tmp_path):
    caminho = tmp_path / "guias_lancadas.jsonl"
    caminho.write_text('{"vip_id": "701", "anx_id": "111", '
                       '"competencia": "2026-09", "estado": "alterado"}\n'
                       'isto nao e json\n', encoding="utf-8")

    r = mod.Registro.carregar(caminho)

    assert r.ja_feito("701", "111", "2026-09") is not None


def test_arquivo_ausente_comeca_vazio(tmp_path):
    r = mod.Registro.carregar(tmp_path / "nao-existe.jsonl")

    assert r.ja_feito("701", "111", "2026-09") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_guias_registro.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'guias.registro'`

- [ ] **Step 3: Write the implementation**

```python
# -*- coding: utf-8 -*-
"""O que cada rodada de guias fez, uma linha por ação.

Mora em `_app/guias_lancadas.jsonl`. Serve a três coisas: a trava contra
lançar duas vezes, a conferência do mês seguinte, e responder "o que a rodada
de ontem fez" sem abrir o ERP.

Formato de linha, e não JSON único: a rodada grava uma linha por ação, logo
depois de cada gravação no ERP. Se o app fechar no meio, o que já foi feito
está no arquivo — um JSON reescrito no fim perderia tudo.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import util

log = util.log(__name__)

NOME_ARQUIVO = "guias_lancadas.jsonl"

#: Estados que significam "o título existe no ERP". Repetir criaria um segundo.
#: `anexo_pendente` entra: o que falta é o PDF, não o lançamento.
FEITOS = ("alterado", "criado", "diverge", "anexo_pendente")


def caminho_padrao() -> Path:
    return util.pasta_base() / NOME_ARQUIVO


class Registro:
    def __init__(self, caminho: Path, linhas: list[dict]):
        self.caminho = Path(caminho)
        self.linhas = linhas
        self._indice = {}
        for linha in linhas:
            self._indexar(linha)

    @classmethod
    def carregar(cls, caminho: Path | None = None) -> "Registro":
        caminho = Path(caminho or caminho_padrao())
        linhas = []
        if caminho.exists():
            for crua in caminho.read_text(encoding="utf-8").splitlines():
                crua = crua.strip()
                if not crua:
                    continue
                try:
                    linhas.append(json.loads(crua))
                except ValueError:
                    # Linha truncada por queda no meio da escrita. Perder uma
                    # linha é ruim; perder o arquivo inteiro é pior.
                    log.warning("linha ilegível no registro de guias")
        return cls(caminho, linhas)

    def _chave(self, vip_id: str, anx_id: str, competencia: str) -> tuple:
        return (str(vip_id), str(anx_id), str(competencia))

    def _indexar(self, linha: dict) -> None:
        if str(linha.get("estado") or "") not in FEITOS:
            return
        self._indice[self._chave(linha.get("vip_id"), linha.get("anx_id"),
                                 linha.get("competencia"))] = linha

    def ja_feito(self, vip_id: str, anx_id: str, competencia: str) -> dict | None:
        """A linha que prova que esta guia já virou título, ou None."""
        return self._indice.get(self._chave(vip_id, anx_id, competencia))

    def anotar(self, **campos) -> None:
        campos.setdefault("quando", dt.datetime.now().isoformat(timespec="seconds"))
        self.linhas.append(campos)
        self._indexar(campos)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with open(self.caminho, "a", encoding="utf-8") as arquivo:
            arquivo.write(json.dumps(campos, ensure_ascii=False) + "\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_guias_registro.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add guias/registro.py tests/test_guias_registro.py
git commit -m "Guias: registro em jsonl do que cada rodada lancou"
```

---

### Task 6: Decidir o que fazer com cada guia

**Files:**
- Create: `guias/casamento.py`
- Test: `tests/test_guias_casamento.py`

**Interfaces:**
- Consumes: `guias.modelos` (Guia, Decisao, ALTERAR/CRIAR/JA_LANCADO/DECIDIR), `guias.regras.Regras`, `guias.registro.Registro`
- Produces:
  - `casamento.decidir(guias, parcelas, regras, registro, competencia, obras=None) -> list[Decisao]`
  - `casamento.parcela_da_recorrencia(parcelas, trade_payable_id) -> dict | None`
  - `casamento.titulo_igual(parcelas, documento, valor, vencimento) -> dict | None`
  - `casamento.sugerir_obra(texto: str, obras: list[dict]) -> str` — id da obra cujo nome aparece no texto do documento, ou `""`

`obras` é a lista do catálogo do ERP (`[{"id": …, "name": …}, …]`); omitida, nenhuma sugestão é feita e a obra fica em branco para o dono escolher.

`parcelas` é a resposta de `payable-installments/paginated-result` já desempacotada (`["content"]`), do mês inteiro.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_guias_casamento.py
# -*- coding: utf-8 -*-
"""A decisão: alterar, criar, já lançado, ou você decide.

É a peça que mexe com dinheiro sem tocar em rede — então é aqui que os casos
ruins têm de estar todos. Nomes e ids INVENTADOS: o repositório é público.
"""
import json
from datetime import date
from decimal import Decimal

import pytest

from guias import casamento as mod
from guias import regras as mod_regras
from guias import registro as mod_registro
from guias.modelos import ALTERAR, CRIAR, DECIDIR, JA_LANCADO, Guia

COMP = "2026-09"


def _guia(**campos):
    base = dict(vip_id="701", empresa="EMPRESA UM", desc="HONORARIO CONTABIL",
                anx_id="111", competencia=COMP, pdf="C:/tmp/x.pdf",
                valor=Decimal("641.31"), vencimento=date(2026, 9, 12),
                documento="DOC-1")
    base.update(campos)
    return Guia(**base)


def _regras(tmp_path, tipos):
    caminho = tmp_path / "guias_regras.json"
    caminho.write_text(json.dumps({"versao": 1, "tipos": tipos},
                                  ensure_ascii=False), encoding="utf-8")
    return mod_regras.Regras.carregar(caminho)


def _registro(tmp_path):
    return mod_registro.Registro.carregar(tmp_path / "r.jsonl")


TIPO_ALTERAR = {"nome": "honorario", "quando": {"desc_contem": ["HONORARIO"]},
                "acao": "alterar", "categoria": "Honorários",
                "recorrencia": {"701": {"trade_payable_id": "tp-1",
                                        "obra": "obra-9"}}}
TIPO_CRIAR = {"nome": "regularizacao", "quando": {"desc_contem": ["RET"]},
              "acao": "criar", "categoria": "Taxa de abertura",
              "favorecido": "FORNECEDOR FICTICIO",
              "descricao": "{documento} - competencia {competencia}",
              "parcelas": 4, "obra": {"701": "obra-7"}}

PARCELAS = [{"id": "par-1", "tradePayableId": "tp-1",
             "plannedDate": "2026-09-12", "plannedValue": 620.00,
             "documentNumber": "ANTIGO"}]


def test_recorrencia_conhecida_vira_alterar(tmp_path):
    [d] = mod.decidir([_guia()], PARCELAS, _regras(tmp_path, [TIPO_ALTERAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == ALTERAR
    assert d.trade_payable_id == "tp-1"
    assert d.parcela_id == "par-1"
    assert d.categoria == "Honorários"


def test_tipo_desconhecido_vira_decidir(tmp_path):
    [d] = mod.decidir([_guia(desc="ALGO QUE NINGUEM CADASTROU")], PARCELAS,
                      _regras(tmp_path, [TIPO_ALTERAR]), _registro(tmp_path), COMP)

    assert d.acao == DECIDIR
    assert "não conheço" in d.motivo.lower() or "nao conheco" in d.motivo.lower()


def test_recorrencia_que_a_regra_aponta_e_nao_esta_no_mes_vira_decidir(tmp_path):
    """A regra diz que existe recorrência e ela não veio: alguma coisa mudou no
    ERP. Criar aqui seria criar um título paralelo à recorrência."""
    [d] = mod.decidir([_guia()], [], _regras(tmp_path, [TIPO_ALTERAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == DECIDIR


def test_duas_guias_do_mesmo_tipo_na_mesma_empresa_viram_decidir(tmp_path):
    """Review Focus 1: apontariam para a MESMA parcela, e a segunda gravação
    apagaria a primeira sem ninguém ver."""
    guias = [_guia(anx_id="111", documento="DOC-1"),
             _guia(anx_id="112", documento="DOC-2")]

    decisoes = mod.decidir(guias, PARCELAS, _regras(tmp_path, [TIPO_ALTERAR]),
                           _registro(tmp_path), COMP)

    assert [d.acao for d in decisoes] == [DECIDIR, DECIDIR]
    assert all("mais de uma" in d.motivo.lower() for d in decisoes)


def test_guia_sem_pdf_nunca_vira_lancamento(tmp_path):
    """Review Focus 3."""
    [d] = mod.decidir([_guia(pdf=None, erro="o link da guia expirou")], PARCELAS,
                      _regras(tmp_path, [TIPO_ALTERAR]), _registro(tmp_path), COMP)

    assert d.acao == DECIDIR
    assert "expirou" in d.motivo


def test_guia_sem_valor_nunca_vira_lancamento(tmp_path):
    [d] = mod.decidir([_guia(valor=None)], PARCELAS,
                      _regras(tmp_path, [TIPO_ALTERAR]), _registro(tmp_path), COMP)

    assert d.acao == DECIDIR


def test_criar_quando_a_regra_manda_criar_e_nao_ha_titulo_igual(tmp_path):
    guia = _guia(desc="BOLETO RET 62 UNIDADES", documento="DOC-RET",
                 valor=Decimal("2504.95"), vencimento=date(2026, 9, 15))

    [d] = mod.decidir([guia], PARCELAS, _regras(tmp_path, [TIPO_CRIAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == CRIAR
    assert d.parcelas == 4
    assert d.obra_id == "obra-7"
    assert d.descricao == "DOC-RET - competencia 2026-09"
    assert d.favorecido == "FORNECEDOR FICTICIO"


def test_titulo_com_o_mesmo_documento_no_mes_vira_ja_lancado(tmp_path):
    """A única camada que enxerga lançamento feito à mão pela tela do ERP."""
    guia = _guia(desc="BOLETO RET 62 UNIDADES", documento="DOC-RET")
    parcelas = PARCELAS + [{"id": "par-9", "tradePayableId": "tp-9",
                            "plannedDate": "2026-09-15",
                            "plannedValue": 641.31,
                            "documentNumber": "DOC-RET"}]

    [d] = mod.decidir([guia], parcelas, _regras(tmp_path, [TIPO_CRIAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == JA_LANCADO
    assert d.trade_payable_id == "tp-9"


def test_registro_da_rodada_anterior_vira_ja_lancado(tmp_path):
    reg = _registro(tmp_path)
    reg.anotar(vip_id="701", anx_id="111", competencia=COMP, acao="alterar",
               estado="alterado", tpid="tp-1")

    [d] = mod.decidir([_guia()], PARCELAS, _regras(tmp_path, [TIPO_ALTERAR]),
                      reg, COMP)

    assert d.acao == JA_LANCADO


OBRAS = [{"id": "obra-1", "name": "CONDOMINIO PRIMEIRO"},
         {"id": "obra-2", "name": "CONDOMINIO SEGUNDO"}]


def test_sugere_a_obra_cujo_nome_aparece_no_documento():
    assert mod.sugerir_obra("BOLETO RET CONDOMINIO SEGUNDO", OBRAS) == "obra-2"


def test_nao_sugere_obra_quando_duas_batem():
    """Duas obras no mesmo texto: escolher uma seria palpite. O dono escolhe."""
    texto = "RET CONDOMINIO PRIMEIRO E CONDOMINIO SEGUNDO"

    assert mod.sugerir_obra(texto, OBRAS) == ""


def test_nao_sugere_obra_quando_nenhuma_bate():
    assert mod.sugerir_obra("BOLETO SEM NOME DE OBRA", OBRAS) == ""


def test_criar_usa_a_obra_da_regra_e_nao_a_sugestao(tmp_path):
    """Regra é o que o dono já confirmou; sugestão é palpite. Regra ganha."""
    guia = _guia(desc="BOLETO RET CONDOMINIO SEGUNDO", documento="DOC-RET")

    [d] = mod.decidir([guia], PARCELAS, _regras(tmp_path, [TIPO_CRIAR]),
                      _registro(tmp_path), COMP, obras=OBRAS)

    assert d.obra_id == "obra-7"


def test_criar_sem_obra_na_regra_recebe_a_sugestao_marcada_como_tal(tmp_path):
    tipo = dict(TIPO_CRIAR)
    tipo.pop("obra")
    guia = _guia(desc="BOLETO RET CONDOMINIO SEGUNDO", documento="DOC-RET")

    [d] = mod.decidir([guia], PARCELAS, _regras(tmp_path, [tipo]),
                      _registro(tmp_path), COMP, obras=OBRAS)

    assert d.obra_id == "obra-2"
    assert d.obra_sugerida is True


def test_criar_sem_obra_nenhuma_vira_decidir(tmp_path):
    """Sem obra não há conta, e sem conta não há lançamento."""
    tipo = dict(TIPO_CRIAR)
    tipo.pop("obra")
    guia = _guia(desc="BOLETO RET SEM NOME DE OBRA", documento="DOC-RET")

    [d] = mod.decidir([guia], PARCELAS, _regras(tmp_path, [tipo]),
                      _registro(tmp_path), COMP, obras=OBRAS)

    assert d.acao == DECIDIR
    assert "obra" in d.motivo.lower()


def test_valor_do_pdf_diferente_do_titulo_avisa_mas_nao_impede(tmp_path):
    """Review Focus 2: o PDF é o documento que se paga, então ele manda — e a
    divergência aparece, em vez de ser escolhida em silêncio."""
    [d] = mod.decidir([_guia(valor=Decimal("999.99"))], PARCELAS,
                      _regras(tmp_path, [TIPO_ALTERAR]), _registro(tmp_path), COMP)

    assert d.acao == ALTERAR
    assert d.aviso
    assert "620" in d.aviso and "999,99" in d.aviso.replace(".", ",")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_guias_casamento.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'guias.casamento'`

- [ ] **Step 3: Write the implementation**

```python
# -*- coding: utf-8 -*-
"""Decide o que fazer com cada guia do mês. Não toca em rede.

Nenhuma decisão é tomada por valor: o valor da guia muda todo mês, e casar por
ele acertaria em fevereiro e erraria em março. O que casa é o
`trade_payable_id` que o dono confirmou uma vez e que a regra guardou.

Quando falta informação, a resposta é DECIDIR — nunca um palpite. Palpite aqui
vira parcela alterada na recorrência errada, e isso só se descobre no extrato.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal

import util
from guias.modelos import ALTERAR, CRIAR, DECIDIR, JA_LANCADO, Decisao

log = util.log(__name__)


def _dec(valor) -> Decimal | None:
    if valor is None:
        return None
    try:
        return Decimal(str(valor)).quantize(Decimal("0.01"))
    except Exception:
        return None


def _brl(valor) -> str:
    return f"{_dec(valor):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def parcela_da_recorrencia(parcelas: list[dict],
                           trade_payable_id: str) -> dict | None:
    for p in parcelas or []:
        if str(p.get("tradePayableId") or "") == str(trade_payable_id):
            return p
    return None


def titulo_igual(parcelas: list[dict], documento: str, valor,
                 vencimento) -> dict | None:
    """Título que já representa esta guia no mês. Primeiro pelo número do
    documento, que é o que identifica a guia; sem ele, por valor + vencimento.
    """
    doc = util.norm_espaco(str(documento or "")).upper()
    if doc:
        for p in parcelas or []:
            if util.norm_espaco(str(p.get("documentNumber") or "")).upper() == doc:
                return p
        return None
    alvo, data = _dec(valor), (vencimento.isoformat() if vencimento else "")
    if alvo is None or not data:
        return None
    for p in parcelas or []:
        if _dec(p.get("plannedValue")) == alvo and str(p.get("plannedDate") or "")[:10] == data:
            return p
    return None


def sugerir_obra(texto: str, obras) -> str:
    """O id da obra cujo nome aparece no texto do documento. `""` se não houver
    exatamente uma.

    Duas obras citadas no mesmo texto não viram escolha: escolher uma seria
    palpite, e obra errada leva junto a conta errada (a conta vem da obra).
    """
    alvo = util.sem_acento(str(texto or "")).upper()
    achadas = {str(o.get("id")) for o in (obras or [])
               if o.get("name")
               and util.sem_acento(str(o["name"])).upper() in alvo}
    return achadas.pop() if len(achadas) == 1 else ""


def decidir(guias, parcelas, regras, registro, competencia: str,
            obras=None) -> list[Decisao]:
    # Duas guias do mesmo tipo na mesma empresa apontariam para a mesma
    # recorrência: a segunda gravação apagaria a primeira. Contar ANTES.
    marcas = Counter()
    for guia in guias:
        tipo = regras.classificar(guia.desc)
        if tipo and tipo.get("acao") == "alterar":
            marcas[(guia.vip_id, tipo.get("nome"))] += 1

    return [_uma(g, parcelas, regras, registro, competencia, marcas, obras)
            for g in guias]


def _uma(guia, parcelas, regras, registro, competencia, marcas,
         obras=None) -> Decisao:
    if guia.erro:
        return Decisao(guia, DECIDIR, motivo=guia.erro)
    if guia.pdf is None:
        return Decisao(guia, DECIDIR, motivo="sem o PDF da guia")
    if guia.valor is None:
        return Decisao(guia, DECIDIR, motivo="não li o valor no PDF")

    feito = registro.ja_feito(guia.vip_id, guia.anx_id, competencia)
    if feito:
        return Decisao(guia, JA_LANCADO, motivo="esta rodada já lançou",
                       trade_payable_id=str(feito.get("tpid") or ""))

    tipo = regras.classificar(guia.desc)
    if tipo is None:
        return Decisao(guia, DECIDIR,
                       motivo=f"não conheço este documento: {guia.desc[:60]}")

    nome = str(tipo.get("nome") or "")
    categoria = str(tipo.get("categoria") or "")

    if tipo.get("acao") == "alterar":
        if marcas[(guia.vip_id, nome)] > 1:
            return Decisao(guia, DECIDIR, tipo=nome, categoria=categoria,
                           motivo="mais de uma guia deste tipo nesta empresa "
                                  "no mês: qual é a parcela da recorrência?")
        conhecida = regras.recorrencia(nome, guia.vip_id)
        tpid = str(conhecida.get("trade_payable_id") or "")
        if not tpid:
            return Decisao(guia, DECIDIR, tipo=nome, categoria=categoria,
                           motivo="ainda não sei qual é a recorrência desta "
                                  "empresa para este documento")
        parcela = parcela_da_recorrencia(parcelas, tpid)
        if parcela is None:
            return Decisao(guia, DECIDIR, tipo=nome, categoria=categoria,
                           motivo="a recorrência que eu conhecia não tem "
                                  "parcela neste mês")
        decisao = Decisao(guia, ALTERAR, tipo=nome, categoria=categoria,
                          obra_id=str(conhecida.get("obra") or ""),
                          trade_payable_id=tpid,
                          parcela_id=str(parcela.get("id") or ""))
        antes = _dec(parcela.get("plannedValue"))
        if antes is not None and antes != _dec(guia.valor):
            decisao.aviso = (f"a parcela está {_brl(antes)} e a guia diz "
                             f"{_brl(guia.valor)}; vale a guia")
        return decisao

    achado = titulo_igual(parcelas, guia.documento, guia.valor, guia.vencimento)
    if achado is not None:
        return Decisao(guia, JA_LANCADO, tipo=nome, categoria=categoria,
                       motivo="já existe título com este documento no mês",
                       trade_payable_id=str(achado.get("tradePayableId") or ""))

    # A regra é o que o dono já confirmou; a sugestão é palpite sobre o texto.
    # A regra ganha sempre, e o palpite viaja marcado como palpite.
    obra_id, sugerida = regras.obra(nome, guia.vip_id), False
    if not obra_id:
        obra_id = sugerir_obra(f"{guia.desc} {guia.documento}", obras)
        sugerida = bool(obra_id)
    if not obra_id:
        # Sem obra não há conta (a conta vem da obra), e sem conta não há
        # lançamento. Perguntar é a única saída honesta.
        return Decisao(guia, DECIDIR, tipo=nome, categoria=categoria,
                       motivo="não sei em que obra este documento entra")

    molde = str(tipo.get("descricao") or "{documento}")
    return Decisao(
        guia, CRIAR, tipo=nome, categoria=categoria,
        obra_id=obra_id, obra_sugerida=sugerida,
        favorecido=str(tipo.get("favorecido") or ""),
        descricao=molde.format(documento=guia.documento,
                               competencia=competencia, desc=guia.desc),
        parcelas=int(tipo.get("parcelas") or 1))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_guias_casamento.py -q`
Expected: 17 passed

- [ ] **Step 5: Commit**

```bash
git add guias/casamento.py tests/test_guias_casamento.py
git commit -m "Guias: decidir alterar, criar, ja lancado ou voce decide"
```

---

### Task 7: Gravar no ERP e anexar, com prova

**Files:**
- Create: `guias/lancar.py`
- Modify: `aportes/mc_catalogos.py` (um método ao lado de `condicao_a_vista_pagamento`, linha 405)
- Test: `tests/test_guias_lancar.py`, `tests/test_aportes_obras.py` (um teste a mais)

**Interfaces:**
- Consumes: `erp.pagina.TransportePagina` (`buscar`, `postar`, `trocar`, `subir`, `cabecalho`), `erp.hosts` (`LEGACY`, `ERP_API`), `guias.modelos`, `aportes.mc_catalogos.Catalogos` (`categoria()`, `participante()`, `condicao_de_pagamento()`)
- Produces:
  - `Catalogos.condicao_de_pagamento(tipo: str = "IN_CASH") -> dict | None` — irmã da `condicao_a_vista_pagamento`, que passa a chamá-la
  - `lancar.referencia_da_obra(transporte, obra_id, parcelas) -> dict | None` — `{"account": …, "paymentMethod": …}` de um título que já existe naquela obra
  - `lancar.alterar(transporte, decisao, catalogos, *, pasta_backup) -> Resultado`
  - `lancar.criar(transporte, decisao, catalogos, *, id_usuario, referencia, obra) -> Resultado`
  - `lancar.anexar(transporte, tpid, pdf, nome) -> list[str]`

Nem a conta nem a forma de pagamento são escolhidas por este código: as duas saem do título de referência da obra. Conta, porque a decisão do dono é que ela vem da obra; forma, porque "Boleto" escrito em literal é um palpite sobre o cadastro de cada instalação — e foi assim que setembro fez, copiando de um título que já existia.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_guias_lancar.py
# -*- coding: utf-8 -*-
"""A gravação no ERP. Ids e nomes INVENTADOS: o repositório é público.

O transporte falso CONSOME o corpo que recebe, e não só devolve resposta:
dublê que não consome a entrada muda o transporte e produz teste que falha
sozinho de vez em quando.
"""
import json
from datetime import date
from decimal import Decimal

import pytest

from guias import lancar as mod
from guias.modelos import (ALTERADO, ANEXO_PENDENTE, CRIADO, DIVERGE, ERRO,
                           Decisao, Guia)


class _Transporte:
    """GET/POST/PUT do ERP, do tamanho que `lancar` usa."""

    def __init__(self, respostas):
        self.respostas = respostas          # {(metodo, fragmento): resposta}
        self.chamadas = []

    def _achar(self, metodo, url):
        for (m, fragmento), resposta in self.respostas.items():
            if m == metodo and fragmento in url:
                return resposta
        raise AssertionError(f"chamada não prevista: {metodo} {url}")

    def buscar(self, url):
        self.chamadas.append(("GET", url, None))
        resposta = self._achar("GET", url)
        return resposta.pop(0) if isinstance(resposta, list) else resposta

    def postar(self, url, corpo):
        # consome de verdade: um corpo que não serializa é erro aqui, e não
        # três camadas adiante
        self.chamadas.append(("POST", url, json.loads(json.dumps(corpo))))
        return self._achar("POST", url)

    def trocar(self, url, corpo):
        self.chamadas.append(("PUT", url, json.loads(json.dumps(corpo))))
        return self._achar("PUT", url)

    def subir(self, url, dados, content_type="application/pdf"):
        self.chamadas.append(("PUT-S3", url, len(dados)))
        return self._achar("PUT-S3", url)

    def cabecalho(self, nome):
        return "user-1111" if nome == "user-id" else None


def _decisao(tmp_path, **campos):
    pdf = tmp_path / "guia.pdf"
    pdf.write_bytes(b"%PDF-1.4 fingido")
    guia = Guia(vip_id="701", empresa="EMPRESA UM", desc="HONORARIO",
                anx_id="111", competencia="2026-09", pdf=pdf,
                valor=Decimal("641.31"), vencimento=date(2026, 9, 12),
                documento="DOC-1")
    base = dict(guia=guia, acao="alterar", tipo="honorario",
                categoria="Honorários", trade_payable_id="tp-1",
                parcela_id="par-1")
    base.update(campos)
    return Decisao(**base)


TITULO = {"id": "tp-1", "documentNumber": "ANTIGO", "value": 620.0,
          "category": {"id": "cat-velha", "name": "Outras Despesas"},
          "recurring": {"plannedDate": "2026-09-12"},
          "costCentreDetails": [{"value": 620.0, "percentage": 100,
                                 "work": {"id": "obra-9", "name": "OBRA X"}}],
          "account": {"id": "conta-3", "name": "CONTA X"},
          "installments": [{"id": "par-1", "plannedDate": "2026-09-12",
                            "plannedValue": 620.0}]}


def _gravado(valor=641.31, doc="DOC-1", cat="Honorários"):
    depois = json.loads(json.dumps(TITULO))
    depois["documentNumber"] = doc
    depois["value"] = valor
    depois["category"] = {"id": "cat-nova", "name": cat}
    depois["installments"][0]["plannedValue"] = valor
    return depois


class _Catalogos:
    def categoria(self, nome):
        return {"id": "cat-nova", "name": nome} if nome else None

    def participante(self, nome):
        return {"id": "part-1", "name": nome} if nome else None

    def condicao_de_pagamento(self, tipo="IN_CASH"):
        return {"id": f"cond-{tipo}", "type": tipo}


REFERENCIA = {"account": {"id": "conta-3", "name": "CONTA X"},
              "paymentMethod": {"id": "forma-1", "name": "FORMA X"}}


ANEXO_OK = [{"filename": "guia.pdf"}]
BATCH = {"attachmentsItem": [{"url": "https://s3.exemplo.invalido/assinada"}]}


def test_alterar_grava_a_categoria_especifica_e_so_esta_parcela(tmp_path):
    t = _Transporte({("GET", "/trade-payables/tp-1"): [TITULO, _gravado()],
                     ("PUT", "/trade-payables/tp-1"): {"id": "tp-1"},
                     ("POST", "/attachments/v2/batch"): BATCH,
                     ("PUT-S3", "s3.exemplo"): {"status": 200},
                     ("GET", "/attachments/v2?"): ANEXO_OK})

    r = mod.alterar(t, _decisao(tmp_path), _Catalogos(),
                    pasta_backup=tmp_path / "bk")

    assert r.estado == ALTERADO
    put = [c for c in t.chamadas if c[0] == "PUT"][0]
    assert "updateNext=false" in put[1]
    # O ERP casa a categoria pelo ID; mandar só o nome grava a categoria velha
    # em silêncio, que é justamente o que a recorrência já trazia errada.
    assert put[2]["category"]["id"] == "cat-nova"
    assert put[2]["category"]["name"] == "Honorários"
    assert put[2]["documentNumber"] == "DOC-1"
    assert put[2]["installments"][0]["plannedValue"] == 641.31
    assert put[2]["costCentreDetails"][0]["value"] == 641.31


def test_alterar_nao_toca_na_descricao_nem_na_conta(tmp_path):
    """A conta vem da obra e a equipe nunca mexe nela; a descrição fica como
    está (decisões do dono)."""
    titulo = json.loads(json.dumps(TITULO))
    titulo["description"] = "DESCRICAO QUE JA ESTAVA LA"
    depois = _gravado()
    depois["description"] = "DESCRICAO QUE JA ESTAVA LA"
    t = _Transporte({("GET", "/trade-payables/tp-1"): [titulo, depois],
                     ("PUT", "/trade-payables/tp-1"): {"id": "tp-1"},
                     ("POST", "/attachments/v2/batch"): BATCH,
                     ("PUT-S3", "s3.exemplo"): {"status": 200},
                     ("GET", "/attachments/v2?"): ANEXO_OK})

    mod.alterar(t, _decisao(tmp_path), _Catalogos(),
                pasta_backup=tmp_path / "bk")

    put = [c for c in t.chamadas if c[0] == "PUT"][0]
    assert put[2]["description"] == "DESCRICAO QUE JA ESTAVA LA"
    assert put[2]["account"]["id"] == "conta-3"


def test_alterar_guarda_o_original_antes_do_put(tmp_path):
    bk = tmp_path / "bk"
    t = _Transporte({("GET", "/trade-payables/tp-1"): [TITULO, _gravado()],
                     ("PUT", "/trade-payables/tp-1"): {"id": "tp-1"},
                     ("POST", "/attachments/v2/batch"): BATCH,
                     ("PUT-S3", "s3.exemplo"): {"status": 200},
                     ("GET", "/attachments/v2?"): ANEXO_OK})

    mod.alterar(t, _decisao(tmp_path), _Catalogos(), pasta_backup=bk)

    salvos = list(bk.glob("*.json"))
    assert len(salvos) == 1
    assert json.loads(salvos[0].read_text(encoding="utf-8"))["value"] == 620.0


def test_parcela_com_baixa_nao_e_tocada(tmp_path):
    titulo = json.loads(json.dumps(TITULO))
    titulo["installments"][0]["paids"] = [{"id": "pago-1"}]
    t = _Transporte({("GET", "/trade-payables/tp-1"): titulo})

    r = mod.alterar(t, _decisao(tmp_path), _Catalogos(),
                    pasta_backup=tmp_path / "bk")

    assert r.estado == ERRO
    assert "baixa" in r.motivo
    assert not [c for c in t.chamadas if c[0] == "PUT"]


def test_releitura_que_nao_bate_vira_diverge(tmp_path):
    """Gravou, mas não como pedido. Não é erro e não é feito."""
    t = _Transporte({("GET", "/trade-payables/tp-1"): [TITULO, _gravado(valor=1.0)],
                     ("PUT", "/trade-payables/tp-1"): {"id": "tp-1"},
                     ("POST", "/attachments/v2/batch"): BATCH,
                     ("PUT-S3", "s3.exemplo"): {"status": 200},
                     ("GET", "/attachments/v2?"): ANEXO_OK})

    r = mod.alterar(t, _decisao(tmp_path), _Catalogos(),
                    pasta_backup=tmp_path / "bk")

    assert r.estado == DIVERGE


def test_erp_recusa_o_put_e_nada_e_anexado(tmp_path):
    t = _Transporte({("GET", "/trade-payables/tp-1"): TITULO,
                     ("PUT", "/trade-payables/tp-1"): {"__erro": 400,
                                                       "__corpo": {"m": "não"}}})

    r = mod.alterar(t, _decisao(tmp_path), _Catalogos(),
                    pasta_backup=tmp_path / "bk")

    assert r.estado == ERRO
    assert "400" in r.motivo
    assert not [c for c in t.chamadas if c[0] == "POST"]


def test_criar_manda_a_conta_da_obra_e_nasce_a_pagar(tmp_path):
    decisao = _decisao(tmp_path, acao="criar", categoria="Taxa de abertura",
                       favorecido="FORNECEDOR FICTICIO",
                       descricao="DOC-1 - competencia 2026-09",
                       obra_id="obra-9", trade_payable_id="", parcela_id="")
    criado = {"id": "tp-novo", "documentNumber": "DOC-1",
              "account": {"id": "conta-3"},
              "costCentreDetails": [{"work": {"id": "obra-9"}}],
              "installments": [{"plannedDate": "2026-09-12",
                                "plannedValue": 641.31}]}
    t = _Transporte({("POST", "/trade-payables?"): {"id": "tp-novo"},
                     ("GET", "/trade-payables/tp-novo"): criado,
                     ("POST", "/attachments/v2/batch"): BATCH,
                     ("PUT-S3", "s3.exemplo"): {"status": 200},
                     ("GET", "/attachments/v2?"): ANEXO_OK})

    r = mod.criar(t, decisao, _Catalogos(), id_usuario="user-1111",
                  referencia=REFERENCIA, obra={"id": "obra-9", "name": "OBRA X"})

    assert r.estado == CRIADO
    corpo = [c for c in t.chamadas if c[0] == "POST" and "trade-payables" in c[1]][0][2]
    assert corpo["markedAsPaid"] is False
    assert corpo["account"]["id"] == "conta-3"
    assert corpo["paymentMethod"]["id"] == "forma-1"
    assert corpo["costCentreType"] == "WORK"
    assert corpo["costCentreDetails"][0]["work"]["id"] == "obra-9"
    assert corpo["whoPays"] == "CLIENT"
    assert corpo["paymentCondition"]["type"] == "IN_CASH"


def test_criar_sem_referencia_da_obra_nao_inventa_conta(tmp_path):
    """A conta vem da obra. Sem título de referência, o robô não escolhe uma:
    lançar na conta errada manda o pagamento sair do lugar errado."""
    decisao = _decisao(tmp_path, acao="criar", obra_id="obra-9",
                       descricao="DOC-1", favorecido="FORNECEDOR FICTICIO",
                       trade_payable_id="", parcela_id="")
    t = _Transporte({})

    r = mod.criar(t, decisao, _Catalogos(), id_usuario="user-1111",
                  referencia=None, obra={"id": "obra-9"})

    assert r.estado == ERRO
    assert "conta" in r.motivo.lower()
    assert t.chamadas == []


def test_criar_parcelado_manda_as_quatro_parcelas_mensais(tmp_path):
    decisao = _decisao(tmp_path, acao="criar", parcelas=4, obra_id="obra-9",
                       descricao="DOC-1", trade_payable_id="", parcela_id="")
    criado = {"id": "tp-novo", "documentNumber": "DOC-1",
              "account": {"id": "conta-3"},
              "costCentreDetails": [{"work": {"id": "obra-9"}}],
              "installments": [{"plannedDate": d, "plannedValue": 160.33}
                               for d in ("2026-09-12", "2026-10-12",
                                         "2026-11-12", "2026-12-12")]}
    t = _Transporte({("POST", "/trade-payables?"): {"id": "tp-novo"},
                     ("GET", "/trade-payables/tp-novo"): criado,
                     ("POST", "/attachments/v2/batch"): BATCH,
                     ("PUT-S3", "s3.exemplo"): {"status": 200},
                     ("GET", "/attachments/v2?"): ANEXO_OK})

    mod.criar(t, decisao, _Catalogos(), id_usuario="user-1111",
              referencia=REFERENCIA, obra={"id": "obra-9"})

    corpo = [c for c in t.chamadas if c[0] == "POST" and "trade-payables" in c[1]][0][2]
    assert len(corpo["installments"]) == 4
    assert corpo["numberOfInstallments"] == 4
    assert corpo["numberOfFinancingInstallments"] == 4
    assert corpo["paymentCondition"]["type"] == "FINANCING"
    assert [i["plannedDate"] for i in corpo["installments"]] == [
        "2026-09-12", "2026-10-12", "2026-11-12", "2026-12-12"]


def test_parcelado_a_ultima_parcela_fecha_o_total(tmp_path):
    """Três parcelas de R$ 10,00 não somam R$ 30,01 nem R$ 29,99: a última
    absorve o centavo, senão o título nasce com valor diferente da guia."""
    parcelas = mod._parcelas_mensais(date(2026, 9, 12), 3, 100.00)

    assert [p["plannedValue"] for p in parcelas] == [33.33, 33.33, 33.34]
    assert round(sum(p["plannedValue"] for p in parcelas), 2) == 100.00


def test_anexo_que_nao_aparece_na_listagem_vira_pendente(tmp_path):
    """Review Focus 5: título criado e PDF não subiu. "Feito" seria mentira, e
    repetir criaria um segundo título."""
    criado = {"id": "tp-novo", "documentNumber": "DOC-1",
              "account": {"id": "conta-3"},
              "costCentreDetails": [{"work": {"id": "obra-9"}}],
              "installments": [{"plannedDate": "2026-09-12",
                                "plannedValue": 641.31}]}
    t = _Transporte({("POST", "/trade-payables?"): {"id": "tp-novo"},
                     ("GET", "/trade-payables/tp-novo"): criado,
                     ("POST", "/attachments/v2/batch"): BATCH,
                     ("PUT-S3", "s3.exemplo"): {"status": 200},
                     ("GET", "/attachments/v2?"): []})

    decisao = _decisao(tmp_path, acao="criar", obra_id="obra-9",
                       favorecido="FORNECEDOR FICTICIO",
                       descricao="DOC-1", trade_payable_id="", parcela_id="")
    r = mod.criar(t, decisao, _Catalogos(), id_usuario="user-1111",
                  referencia=REFERENCIA, obra={"id": "obra-9"})

    assert r.estado == ANEXO_PENDENTE
    assert r.tpid == "tp-novo"


def test_referencia_da_obra_sai_de_um_titulo_da_mesma_obra():
    """A conta não é escolhida: é a que o ERP põe depois da obra. O título que
    já existe naquela obra é quem sabe qual é — e a forma de pagamento junto,
    que também é cadastro de cada instalação e não literal no código."""
    parcelas = [{"tradePayableId": "tp-7",
                 "costCentreDetails": [{"work": {"id": "obra-9"}}]}]
    t = _Transporte({("GET", "/trade-payables/tp-7"): {
        "account": {"id": "conta-3", "name": "CONTA X"},
        "paymentMethod": {"id": "forma-1", "name": "FORMA X"},
        "costCentreDetails": [{"work": {"id": "obra-9"}}]}})

    referencia = mod.referencia_da_obra(t, "obra-9", parcelas)

    assert referencia["account"]["id"] == "conta-3"
    assert referencia["paymentMethod"]["id"] == "forma-1"


def test_referencia_da_obra_sem_titulo_na_obra_devolve_none():
    assert mod.referencia_da_obra(_Transporte({}), "obra-9", []) is None


def test_referencia_da_obra_ignora_titulo_de_outra_obra():
    """Buscar a conta na obra errada é o erro que passa despercebido: a conta
    existe, o lançamento é aceito, e o dinheiro sai do lugar errado."""
    parcelas = [{"tradePayableId": "tp-8",
                 "costCentreDetails": [{"work": {"id": "obra-OUTRA"}}]}]

    assert mod.referencia_da_obra(_Transporte({}), "obra-9", parcelas) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_guias_lancar.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'guias.lancar'`

- [ ] **Step 3: Give `Catalogos` the sibling it was missing**

`condicao_a_vista_pagamento` acha a condição "À Vista" pelo `type`, e não pelo
nome (que varia de instalação para instalação). Parcelado precisa da mesma
busca com `FINANCING`. Em `aportes/mc_catalogos.py`, no lugar do método atual
(linha 405):

```python
    def condicao_de_pagamento(self, tipo: str = "IN_CASH") -> dict | None:
        """A condição de pagamento pelo TYPE, e não pelo nome — o nome varia
        de instalação para instalação, o type não.

        `IN_CASH` é o lançamento de uma parcela só; `FINANCING` é o parcelado
        (é a condição que o ERP usa quando a tela pede número de parcelas).
        """
        for item in self.condicoes_pagamento.values():
            if item.get("type") == tipo:
                return item
            if tipo == "IN_CASH" and item.get("inCash"):
                return item
        return None

    def condicao_a_vista_pagamento(self) -> dict | None:
        """Mantido: `aportes/mc_lancamentos.py` chama por este nome."""
        return self.condicao_de_pagamento("IN_CASH")
```

E o teste, em `tests/test_aportes_obras.py` (que já monta um `Catalogos`):

```python
def test_a_condicao_de_pagamento_e_achada_pelo_type():
    """O nome varia de instalação para instalação; o type não. E "à vista"
    continua funcionando pelo caminho antigo, que os aportes usam."""
    from aportes.mc_catalogos import Catalogos

    cat = Catalogos.__new__(Catalogos)
    cat.condicoes_pagamento = {
        "a": {"id": "c1", "type": "IN_CASH", "name": "À Vista"},
        "b": {"id": "c2", "type": "FINANCING", "name": "Parcelado"},
    }

    assert cat.condicao_de_pagamento("FINANCING")["id"] == "c2"
    assert cat.condicao_de_pagamento()["id"] == "c1"
    assert cat.condicao_a_vista_pagamento()["id"] == "c1"
    assert cat.condicao_de_pagamento("NAO_EXISTE") is None
```

- [ ] **Step 4: Write the implementation**

```python
# -*- coding: utf-8 -*-
"""Grava a guia no Mais Controle: altera a parcela da recorrência, ou cria.

Tudo pela API, de dentro da página logada (`erp/pagina.py`). Um
`POST /users/login` por HTTP derrubaria a sessão do dono — o ERP aceita uma
por usuário.

Três regras que não se negociam aqui:

1. **Backup antes do PUT.** O objeto que vai ser trocado é gravado em disco
   primeiro. Sem isso, uma alteração errada não tem volta.
2. **Releitura depois de gravar.** O que o ERP diz ter guardado é comparado
   campo a campo com o que foi pedido. Não batendo, o desfecho é DIVERGE.
3. **O anexo só é "anexado" com a listagem provando.** E o POST do batch nunca
   se repete: batch reenviado é um segundo registro de anexo no mesmo título.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from decimal import Decimal
from pathlib import Path

import util
from erp import hosts
from guias.modelos import (ALTERADO, ANEXO_PENDENTE, CRIADO, DIVERGE, ERRO,
                           Resultado)

log = util.log(__name__)

#: "Quem paga" nos nossos lançamentos, como nos aportes.
QUEM_PAGA = "CLIENT"

RE_S3 = re.compile(r"https://[^\"' ]*amazonaws[^\"' ]*")


def _num(valor) -> float:
    """Decimal -> float SÓ na fronteira do JSON (a conta é feita em Decimal)."""
    return float(Decimal(str(valor)).quantize(Decimal("0.01")))


def _erro_de(resposta) -> str:
    if isinstance(resposta, dict) and resposta.get("__erro"):
        return f"o ERP recusou (HTTP {resposta['__erro']})"
    return ""


def _mesmo(a, b) -> bool:
    return abs(float(a or 0) - float(b or 0)) < 0.005


# --------------------------------------------------------------- conta e obra

def referencia_da_obra(transporte, obra_id: str, parcelas) -> dict | None:
    """Conta e forma de pagamento que o ERP usaria nesta obra, lidas de um
    título que já existe nela. `None` = não há título de referência.

    A conta NÃO é escolhida por ninguém: pela tela, selecionar a obra já a
    preenche, e a equipe deixa a que vem (decisão do dono, 21/09/2026). Pela
    API ela é campo obrigatório, então o jeito de mandar a MESMA é perguntar a
    um título daquela obra. A forma de pagamento vem junto pelo mesmo motivo:
    o nome dela é cadastro de cada instalação, e escrever "Boleto" em literal
    é palpite sobre um cadastro que este código não conhece.

    Só título da obra pedida serve. Copiar a conta da obra errada produz um
    lançamento que o ERP aceita e que paga pelo lugar errado.
    """
    for p in parcelas or []:
        detalhes = p.get("costCentreDetails") or []
        obras = [str((d.get("work") or {}).get("id") or "") for d in detalhes]
        if str(obra_id) not in obras:
            continue
        tpid = str(p.get("tradePayableId") or "")
        if not tpid:
            continue
        titulo = transporte.buscar(f"{hosts.LEGACY}/trade-payables/{tpid}")
        if _erro_de(titulo):
            continue
        conta = (titulo or {}).get("account")
        if conta and conta.get("id"):
            return {"account": conta,
                    "paymentMethod": (titulo or {}).get("paymentMethod") or {}}
    return None


# ------------------------------------------------------------------- anexo

def anexar(transporte, tpid: str, pdf: Path, nome: str) -> list[str]:
    """Sobe o PDF para o TÍTULO. Devolve os nomes que a listagem de prova traz.

    Lista vazia = não provou. O chamador trata como anexo pendente — nunca
    repete o batch, que criaria um segundo registro de anexo.
    """
    dados = Path(pdf).read_bytes()
    corpo = {"entityOrigin": "TRADE_PAYABLE", "entityId": tpid,
             "attachmentsItem": [{"name": nome, "contentType": "application/pdf",
                                  "extension": "pdf", "sizeInBytes": len(dados)}]}
    resposta = transporte.postar(f"{hosts.ERP_API}/attachments/v2/batch", corpo)
    if _erro_de(resposta):
        log.warning("o batch do anexo foi recusado pelo ERP")
        return []
    urls = RE_S3.findall(json.dumps(resposta))
    if not urls:
        log.warning("o batch do anexo voltou sem URL pré-assinada")
        return []
    subida = transporte.subir(json.loads(f'"{urls[0]}"'), dados)
    if int((subida or {}).get("status") or 0) >= 300:
        return []
    prova = transporte.buscar(
        f"{hosts.ERP_API}/attachments/v2?entityIds={tpid}"
        f"&entityOrigin=TRADE_PAYABLE")
    if not isinstance(prova, list):
        return []
    return [str(a.get("filename") or "") for a in prova]


def _fechar(transporte, decisao, tpid: str, estado_ok: str,
            conferido: bool) -> Resultado:
    """Anexa e devolve o desfecho. Ordem: título primeiro, anexo depois."""
    nome = f"{decisao.guia.desc[:60]} {decisao.guia.competencia}.pdf".strip()
    anexos = anexar(transporte, tpid, decisao.guia.pdf, nome)
    if not anexos:
        return Resultado(ANEXO_PENDENTE, tpid=tpid,
                         motivo="o título está gravado; o PDF não subiu")
    return Resultado(estado_ok if conferido else DIVERGE, tpid=tpid,
                     anexos=anexos,
                     motivo="" if conferido else
                            "gravou, mas a releitura não bateu")


# ----------------------------------------------------------------- alterar

def alterar(transporte, decisao, catalogos, *, pasta_backup: Path) -> Resultado:
    tpid = decisao.trade_payable_id
    url = f"{hosts.LEGACY}/trade-payables/{tpid}"
    titulo = transporte.buscar(url)
    recusa = _erro_de(titulo)
    if recusa:
        return Resultado(ERRO, motivo=recusa)

    parcelas = [i for i in (titulo.get("installments") or [])
                if str(i.get("id")) == str(decisao.parcela_id)]
    if not parcelas:
        return Resultado(ERRO, motivo="a parcela não está mais neste título")
    parcela = parcelas[0]
    if parcela.get("paid") or parcela.get("paids"):
        return Resultado(ERRO, motivo="a parcela já tem baixa — não mexo")

    # O ERP casa a categoria pelo ID. Mandar só o nome guarda a categoria
    # VELHA sem reclamar — e a categoria velha é justamente a genérica com que
    # a recorrência nasce, que é o que esta rotina existe para corrigir.
    categoria = None
    if decisao.categoria:
        categoria = catalogos.categoria(decisao.categoria)
        if not categoria:
            return Resultado(ERRO, motivo=f"categoria não cadastrada no ERP: "
                                          f"{decisao.categoria!r}")

    pasta_backup.mkdir(parents=True, exist_ok=True)
    (pasta_backup / f"{tpid}_{decisao.parcela_id}.json").write_text(
        json.dumps(titulo, ensure_ascii=False), encoding="utf-8")

    data = decisao.guia.vencimento.isoformat() if decisao.guia.vencimento else \
        str(parcela.get("plannedDate") or "")[:10]
    valor = _num(decisao.guia.valor)

    # A descrição fica INTACTA: é o padrão da equipe ao alterar recorrência.
    # A conta e a obra também: vieram do título, e conta vem da obra.
    titulo["value"] = valor
    titulo["documentNumber"] = decisao.guia.documento
    if categoria:
        titulo["category"] = {"id": categoria["id"],
                              "name": categoria.get("name") or decisao.categoria}
    if isinstance(titulo.get("recurring"), dict):
        titulo["recurring"]["plannedDate"] = data
    for detalhe in titulo.get("costCentreDetails") or []:
        detalhe["value"] = _num(valor * float(detalhe.get("percentage") or 100) / 100)
    parcela["plannedDate"] = data
    parcela["plannedValue"] = valor

    resposta = transporte.trocar(
        f"{url}?removeAllEntryItems=false&userApprovesSaleCreation=true"
        "&updateNext=false", titulo)
    recusa = _erro_de(resposta)
    if recusa:
        return Resultado(ERRO, motivo=recusa)

    depois = transporte.buscar(url)
    conferido = False
    if not _erro_de(depois):
        nova = [i for i in (depois.get("installments") or [])
                if str(i.get("id")) == str(decisao.parcela_id)]
        categoria_ok = (not categoria or
                        str((depois.get("category") or {}).get("id") or "")
                        == str(categoria["id"]))
        conferido = bool(nova) and categoria_ok and (
            str(nova[0].get("plannedDate") or "")[:10] == data
            and _mesmo(nova[0].get("plannedValue"), valor)
            and str(depois.get("documentNumber") or "") == decisao.guia.documento)
    return _fechar(transporte, decisao, tpid, ALTERADO, conferido)


# ------------------------------------------------------------------- criar

def _parcelas_mensais(primeira, quantas: int, total) -> list[dict]:
    """`quantas` parcelas no mesmo dia dos meses seguintes. A última fecha o
    total, para a soma bater com o valor do documento."""
    valor = (Decimal(str(total)) / quantas).quantize(Decimal("0.01"))
    saida, somado = [], Decimal("0")
    for i in range(quantas):
        mes = primeira.month - 1 + i
        data = primeira.replace(year=primeira.year + mes // 12, month=mes % 12 + 1)
        parte = valor if i < quantas - 1 else Decimal(str(total)) - somado
        somado += parte
        saida.append({"plannedDate": data.isoformat(), "plannedValue": _num(parte),
                      "markedAsPaid": False, "order": i})
    return saida


def criar(transporte, decisao, catalogos, *, id_usuario: str,
          referencia: dict | None, obra: dict) -> Resultado:
    # A conta é a primeira coisa conferida, e nada sai antes dela: sem o
    # título de referência da obra não há conta, e inventar uma manda o
    # pagamento sair do lugar errado.
    conta = (referencia or {}).get("account") or {}
    if not conta.get("id"):
        return Resultado(ERRO, motivo="sem título de referência nesta obra, "
                                      "não sei qual conta o ERP usaria; "
                                      "lance este pela tela do ERP")
    categoria = catalogos.categoria(decisao.categoria)
    if not categoria:
        return Resultado(ERRO, motivo=f"categoria não cadastrada no ERP: "
                                      f"{decisao.categoria!r}")
    participante = catalogos.participante(decisao.favorecido)
    if not participante:
        return Resultado(ERRO, motivo=f"favorecido não cadastrado no ERP: "
                                      f"{decisao.favorecido!r}")

    parcelado = int(decisao.parcelas or 1) > 1
    condicao = catalogos.condicao_de_pagamento(
        "FINANCING" if parcelado else "IN_CASH")
    if not condicao:
        return Resultado(ERRO, motivo="o ERP não tem a condição de pagamento "
                                      + ("parcelada" if parcelado else "à vista"))
    primeira = decisao.guia.vencimento or dt.date.today()
    total = _num(decisao.guia.valor)
    parcelas = _parcelas_mensais(primeira, int(decisao.parcelas or 1), total)
    forma = (referencia or {}).get("paymentMethod") or {}

    corpo = {
        "paymentCondition": {"id": condicao["id"], "type": condicao["type"],
                             "financing": parcelado, "recurring": False},
        "installments": parcelas,
        "numberOfInstallments": len(parcelas),
        "responsible": {"id": id_usuario},
        "value": total,
        "description": decisao.descricao,
        "documentNumber": decisao.guia.documento,
        "participant": {"id": participante["id"]},
        "referenceDate": primeira.isoformat(),
        "date": dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "category": {"id": categoria["id"]},
        "whoPays": QUEM_PAGA,
        "costCentreType": "WORK",
        "costCentreDetails": [{"value": total, "percentage": 100, "work": obra}],
        "paymentMethod": {"id": forma.get("id")},
        "numberPrecision": 2,
        "markedAsPaid": False,             # é conta A PAGAR, não baixa
        "account": conta,
        "freightageValue": 0, "otherValue": 0, "ipiValue": 0, "discountValue": 0,
        "_saveAndAddNew": False,
    }
    if parcelado:
        corpo["numberOfFinancingInstallments"] = len(parcelas)

    resposta = transporte.postar(
        f"{hosts.LEGACY}/trade-payables?userApprovesSaleCreation=true", corpo)
    recusa = _erro_de(resposta)
    if recusa:
        return Resultado(ERRO, motivo=recusa)
    tpid = str((resposta or {}).get("id") or "")
    if not tpid:
        return Resultado(ERRO, motivo="o ERP respondeu sem o id do título")

    depois = transporte.buscar(f"{hosts.LEGACY}/trade-payables/{tpid}")
    conferido = False
    if not _erro_de(depois):
        criadas = sorted((str(i.get("plannedDate") or "")[:10],
                          round(float(i.get("plannedValue") or 0), 2))
                         for i in (depois.get("installments") or []))
        pedidas = sorted((p["plannedDate"], round(p["plannedValue"], 2))
                         for p in parcelas)
        conferido = (criadas == pedidas
                     and str((depois.get("account") or {}).get("id")) == str(conta["id"])
                     and str(depois.get("documentNumber") or "") == decisao.guia.documento)
    return _fechar(transporte, decisao, tpid, CRIADO, conferido)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_guias_lancar.py tests/test_aportes_obras.py tests/test_aportes_valor.py -q`
Expected: 15 passed em `test_guias_lancar.py`; os de aportes seguem passando — `condicao_a_vista_pagamento` continua existindo e respondendo o mesmo.

- [ ] **Step 6: Commit**

```bash
git add guias/lancar.py aportes/mc_catalogos.py tests/test_guias_lancar.py tests/test_aportes_obras.py
git commit -m "Guias: gravar no ERP com backup, releitura e anexo com prova"
```

---

### Task 8: A tela do bloco

**Files:**
- Create: `guias/painel.py`
- Test: `tests/test_guias_painel.py`

**Interfaces:**
- Consumes: tudo das tarefas 1 e 3-7; `widgets` (`px`, `ComboBusca`, `MESES` de `acessorias.frame`), a fixture `raiz` do `conftest.py`
- Produces:
  - `painel.GuiasPainel(master, aba, anx)` — `ttk.Frame` embutível
  - `GuiasPainel.varrer()` / `.lancar()` / `.parar()` / `.ocupado() -> str | None` / `.fechar()`
  - `GuiasPainel.periodo -> tuple[int, int]` — (ano, mês) escolhidos; **mês atual** por padrão (o bloco de envio de conciliações usa o mês ANTERIOR, e são coisas diferentes)
  - `GuiasPainel.mostrar(decisoes)` / `.marcadas()` / `.alternar(iid)` / `.quantas(acao)` / `.linhas_de(acao)` / `.texto_da_linha(iid)`
  - `GuiasPainel.editar(iid, campo: str, valor: str)` — troca categoria ou obra de uma linha
  - `GuiasPainel.abrir_pdf(iid)` / `.abrir_no_erp(iid)`
  - `painel.SECOES = (ALTERAR, CRIAR, DECIDIR, JA_LANCADO)` — a ordem em que a lista mostra
  - `painel.CAMPOS_EDITAVEIS = ("categoria", "obra")`

O painel não faz rede na thread da interface: `varrer` e `lancar` só jogam trabalho no executor da aba e leem a fila, como `AcessoriasFrame` já faz.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_guias_painel.py
# -*- coding: utf-8 -*-
"""O bloco de guias da aba Acessórias.

Usa a fixture `raiz` do conftest (UM `Tk()` para a sessão inteira): módulo que
cria e destrói o próprio faz os seguintes pularem com "sem display".
"""
from datetime import date
from decimal import Decimal

import pytest

from guias import painel as mod
from guias.modelos import ALTERAR, CRIAR, DECIDIR, JA_LANCADO, Decisao, Guia


def _decisao(acao, **campos):
    guia = Guia(vip_id="701", empresa="EMPRESA UM", desc="HONORARIO",
                anx_id=campos.pop("anx_id", "111"), competencia="2026-09",
                valor=Decimal("641.31"), vencimento=date(2026, 9, 12),
                documento="DOC-1")
    return Decisao(guia=guia, acao=acao, categoria="Honorários", **campos)


@pytest.fixture
def bloco(raiz):
    p = mod.GuiasPainel(raiz, aba=None, anx=None)
    yield p
    p.destroy()


def test_as_secoes_aparecem_na_ordem_do_trabalho(bloco):
    """Primeiro o que vai ser gravado, depois o que precisa de decisão, por
    último o que já está pronto."""
    assert mod.SECOES == (ALTERAR, CRIAR, DECIDIR, JA_LANCADO)


def test_mostrar_separa_as_linhas_por_secao(bloco):
    bloco.mostrar([_decisao(ALTERAR, anx_id="1"),
                   _decisao(CRIAR, anx_id="2"),
                   _decisao(DECIDIR, anx_id="3", motivo="não conheço")])

    assert bloco.quantas(ALTERAR) == 1
    assert bloco.quantas(CRIAR) == 1
    assert bloco.quantas(DECIDIR) == 1
    assert bloco.quantas(JA_LANCADO) == 0


def test_alterar_e_criar_nascem_marcados_e_decidir_nao(bloco):
    """Decidir não pode ser lançado por distração: nasce desmarcado e o botão
    nem o considera."""
    bloco.mostrar([_decisao(ALTERAR, anx_id="1"),
                   _decisao(CRIAR, anx_id="2"),
                   _decisao(DECIDIR, anx_id="3"),
                   _decisao(JA_LANCADO, anx_id="4")])

    marcadas = [d.acao for d in bloco.marcadas()]
    assert sorted(marcadas) == sorted([ALTERAR, CRIAR])


def test_desmarcar_uma_linha_tira_ela_do_lancamento(bloco):
    bloco.mostrar([_decisao(ALTERAR, anx_id="1"), _decisao(ALTERAR, anx_id="2")])
    iid = bloco.linhas_de(ALTERAR)[0]

    bloco.alternar(iid)

    assert len(bloco.marcadas()) == 1


def test_aviso_de_divergencia_aparece_na_linha(bloco):
    """Review Focus 2: a divergência de valor tem de estar visível."""
    bloco.mostrar([_decisao(ALTERAR, anx_id="1",
                            aviso="a parcela está 620,00 e a guia diz 641,31")])
    iid = bloco.linhas_de(ALTERAR)[0]

    assert "620,00" in bloco.texto_da_linha(iid)


def test_lancar_sem_nada_marcado_nao_chama_o_executor(bloco):
    bloco.mostrar([_decisao(DECIDIR, anx_id="1")])
    chamadas = []
    bloco._executar = lambda *a, **k: chamadas.append(a)

    bloco.lancar()

    assert chamadas == []


def test_o_mes_padrao_e_o_ATUAL(bloco):
    """O bloco de envio de conciliações abre no mês ANTERIOR (fechamento); este
    abre no mês corrente, que é onde estão as guias a pagar."""
    hoje = date.today()

    assert bloco.periodo == (hoje.year, hoje.month)


def test_linha_com_obra_sugerida_e_marcada_para_o_dono_olhar(bloco):
    """Sugestão não é confirmação: a linha diz que aquilo é palpite."""
    bloco.mostrar([_decisao(CRIAR, anx_id="1", obra_id="obra-2",
                            obra_sugerida=True)])
    iid = bloco.linhas_de(CRIAR)[0]

    assert "?" in bloco.texto_da_linha(iid)


def test_editar_a_obra_troca_a_decisao_e_tira_a_marca_de_palpite(bloco):
    bloco.mostrar([_decisao(CRIAR, anx_id="1", obra_id="obra-2",
                            obra_sugerida=True)])
    iid = bloco.linhas_de(CRIAR)[0]

    bloco.editar(iid, "obra", "obra-7")

    assert bloco.decisoes[iid].obra_id == "obra-7"
    assert bloco.decisoes[iid].obra_sugerida is False
    assert "?" not in bloco.texto_da_linha(iid)


def test_editar_a_categoria_troca_a_decisao(bloco):
    bloco.mostrar([_decisao(ALTERAR, anx_id="1")])
    iid = bloco.linhas_de(ALTERAR)[0]

    bloco.editar(iid, "categoria", "Outra Categoria")

    assert bloco.decisoes[iid].categoria == "Outra Categoria"
    assert "Outra Categoria" in bloco.texto_da_linha(iid)


def test_editar_campo_que_nao_se_edita_nao_muda_nada(bloco):
    bloco.mostrar([_decisao(ALTERAR, anx_id="1")])
    iid = bloco.linhas_de(ALTERAR)[0]
    antes = bloco.texto_da_linha(iid)

    bloco.editar(iid, "valor", "999,99")

    assert bloco.texto_da_linha(iid) == antes


def test_abrir_pdf_de_linha_sem_pdf_nao_explode(bloco):
    """Linha de "você decide" costuma ser justamente a que não tem PDF."""
    bloco.mostrar([_decisao(DECIDIR, anx_id="1")])
    iid = bloco.linhas_de(DECIDIR)[0]

    bloco.abrir_pdf(iid)          # não levanta


def test_parar_pede_parada_sem_derrubar_a_tela(bloco):
    bloco.parar()                 # sem rodada em pé: não faz nada e não quebra
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_guias_painel.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'guias.painel'`

- [ ] **Step 3: Write the implementation**

```python
# -*- coding: utf-8 -*-
"""O bloco "Guias do mês → Mais Controle" da aba Acessórias.

Treeview, e não um bloco de widgets por linha: as listas de conferência do app
caíram de 5,4 s para 0,14 s quando mudaram para Treeview, e esta lista tem
dezenas de linhas.

Nada de rede nesta thread. `varrer` e `lancar` empurram o trabalho para o
executor da aba e a tela só lê a fila — falar com o Tcl de dentro do worker
trava sem hora marcada, que é a falha que nunca aparece em teste.
"""
from __future__ import annotations

import datetime as dt
import os
import tkinter as tk
import webbrowser
from tkinter import ttk

import util
import widgets
from anexar import config as anx_config
from guias.modelos import ALTERAR, CRIAR, DECIDIR, JA_LANCADO

log = util.log(__name__)

#: Os nomes dos meses vêm de `widgets`, e não de `acessorias.frame`: a aba
#: importa ESTE módulo, e importá-la de volta fecharia o ciclo.
MESES = list(widgets.MESES)

#: A ordem do trabalho: o que vai ser gravado, o que precisa de você, o pronto.
SECOES = (ALTERAR, CRIAR, DECIDIR, JA_LANCADO)

#: As duas colunas que o duplo clique edita. Valor e vencimento saem do
#: documento e não se digitam: o que vale é o que está no PDF.
CAMPOS_EDITAVEIS = ("categoria", "obra")

TITULOS = {ALTERAR: "Alterar a recorrência",
           CRIAR: "Criar o lançamento",
           DECIDIR: "Você decide",
           JA_LANCADO: "Já lançado"}

#: Só estas duas são gravadas. "Você decide" nunca entra por distração.
LANCAVEIS = (ALTERAR, CRIAR)

COLUNAS = (("empresa", "Empresa", 170), ("documento", "Documento", 230),
           ("venc", "Vence", 90), ("valor", "Valor", 100),
           ("categoria", "Categoria", 150), ("obra", "Obra", 150),
           ("estado", "Situação", 260))


class GuiasPainel(ttk.Frame):
    def __init__(self, master, aba=None, anx=None):
        super().__init__(master)
        self.aba = aba                   # AcessoriasFrame: fila, log, executor
        self.anx = anx                   # AnexarFrame: a sessão do ERP
        self.decisoes = {}               # iid -> Decisao
        self.marcado = {}                # iid -> bool
        self.secoes = {}                 # ação -> iid do nó da seção
        self._tarefa = ""
        #: Nomes vindos do cadastro do ERP, para os combos de correção.
        #: Preenchidos pela varredura; vazios antes dela.
        self.categorias: list[str] = []
        self.obras: list[dict] = []

        # O mês é o ATUAL, e não o anterior: o bloco de cima manda o
        # fechamento do mês passado ao escritório; este traz o que vence
        # agora. Mesma aba, dois calendários — e trocar os dois seria o
        # tipo de erro que ninguém percebe até faltar guia no mês.
        hoje = dt.date.today()
        self.v_mes = tk.StringVar(value=MESES[hoje.month - 1])
        self.v_ano = tk.StringVar(value=str(hoje.year))

        self._build()

    @property
    def periodo(self) -> tuple[int, int]:
        """(ano, mês) escolhidos. SÓ na thread da interface: ler `StringVar` é
        falar com o Tcl, e o Tcl é de quem criou a janela."""
        return int(self.v_ano.get()), MESES.index(self.v_mes.get()) + 1

    # ---------------------------------------------------------------- layout

    def _build(self):
        topo = ttk.Frame(self)
        topo.pack(fill="x", pady=(widgets.px(8), widgets.px(4)))
        ttk.Label(topo, text="Guias do mês → Mais Controle",
                  style="Titulo.TLabel").pack(side="left")

        ttk.Combobox(topo, textvariable=self.v_mes, values=MESES, width=12,
                     state="readonly").pack(side="left", padx=(widgets.px(12), 0))
        ttk.Entry(topo, textvariable=self.v_ano, width=6).pack(
            side="left", padx=widgets.px(4))

        ttk.Button(topo, text="Varrer o portal",
                   command=self.varrer).pack(side="right")
        ttk.Button(topo, text="Lançar o marcado",
                   command=self.lancar).pack(side="right", padx=widgets.px(6))
        ttk.Button(topo, text="Parar", command=self.parar).pack(side="right")

        self.lista = ttk.Treeview(self, columns=[c[0] for c in COLUNAS],
                                  show="tree headings", height=14)
        self.lista.heading("#0", text="")
        self.lista.column("#0", width=widgets.px(30), stretch=False)
        for chave, titulo, largura in COLUNAS:
            self.lista.heading(chave, text=titulo)
            self.lista.column(chave, width=widgets.px(largura), stretch=True)
        self.lista.pack(fill="both", expand=True)
        self.lista.bind("<space>", self._tecla_marcar)
        self.lista.bind("<Button-1>", self._clique)
        self.lista.bind("<Double-1>", self._duplo_clique)

        pe = ttk.Frame(self)
        pe.pack(fill="x", pady=widgets.px(4))
        ttk.Button(pe, text="Abrir o PDF",
                   command=lambda: self._na_selecionada(self.abrir_pdf)).pack(
                       side="left")
        ttk.Button(pe, text="Abrir no ERP",
                   command=lambda: self._na_selecionada(self.abrir_no_erp)).pack(
                       side="left", padx=widgets.px(6))

        for acao in SECOES:
            self.secoes[acao] = self.lista.insert(
                "", "end", text="", values=(TITULOS[acao], "", "", "", "", "", ""),
                open=True, tags=("secao",))

    def _na_selecionada(self, funcao):
        for iid in self.lista.selection():
            if iid in self.decisoes:
                funcao(iid)
                return

    # ------------------------------------------------------------- conteúdo

    def mostrar(self, decisoes) -> None:
        """Repõe a lista inteira. SÓ na thread da interface."""
        for iid in list(self.decisoes):
            self.lista.delete(iid)
        self.decisoes.clear()
        self.marcado.clear()
        for decisao in decisoes:
            self._inserir(decisao)

    def _nome_da_obra(self, obra_id: str) -> str:
        for obra in self.obras:
            if str(obra.get("id")) == str(obra_id):
                return str(obra.get("name") or obra_id)
        return str(obra_id or "")

    def _valores(self, decisao) -> tuple:
        guia = decisao.guia
        obra = self._nome_da_obra(decisao.obra_id)
        if obra and decisao.obra_sugerida:
            # Palpite sobre o texto do documento, e não regra confirmada: a
            # linha diz isso, senão o "?" some junto com a diferença.
            obra += "  ?"
        return (guia.empresa, guia.documento or guia.desc[:40],
                guia.vencimento.strftime("%d/%m") if guia.vencimento else "",
                util.fmt_val(int((guia.valor or 0) * 100)) if guia.valor else "",
                decisao.categoria, obra,
                decisao.motivo or decisao.aviso or "")

    def _inserir(self, decisao) -> str:
        marca = decisao.acao in LANCAVEIS
        iid = self.lista.insert(self.secoes[decisao.acao], "end",
                                text="[x]" if marca else "[ ]",
                                values=self._valores(decisao))
        self.decisoes[iid] = decisao
        self.marcado[iid] = marca
        return iid

    # --------------------------------------------------------------- edição

    def editar(self, iid: str, campo: str, valor: str) -> None:
        """Troca categoria ou obra de UMA linha. O que o dono escolhe aqui é o
        que a Tarefa 9 grava na regra — por isso a decisão muda, e não só a
        aparência da linha."""
        decisao = self.decisoes.get(iid)
        if decisao is None or campo not in CAMPOS_EDITAVEIS or not valor:
            return
        if campo == "categoria":
            decisao.categoria = valor
        else:
            decisao.obra_id = valor
            decisao.obra_sugerida = False   # agora é escolha, não palpite
        self.lista.item(iid, values=self._valores(decisao))

    def _duplo_clique(self, evento):
        iid = self.lista.identify_row(evento.y)
        if iid not in self.decisoes:
            return None
        coluna = self.lista.identify_column(evento.x)
        indice = int(coluna[1:]) - 1 if coluna.startswith("#") else -1
        if not 0 <= indice < len(COLUNAS):
            return None
        campo = COLUNAS[indice][0]
        if campo not in CAMPOS_EDITAVEIS:
            return None
        self._pedir_valor(iid, campo)
        return "break"

    def _pedir_valor(self, iid: str, campo: str) -> None:
        """Abre um `ComboBusca` com os nomes do cadastro do ERP.

        Digita-se para procurar, e nada é escolhido por adivinhação: texto que
        não é uma opção não vira nada (é a regra do próprio widget)."""
        if campo == "categoria":
            opcoes = {nome: nome for nome in self.categorias}
        else:
            opcoes = {str(o.get("name")): str(o.get("id")) for o in self.obras}
        if not opcoes:
            if self.aba is not None:
                self.aba._log("[!] Varra o portal primeiro: os nomes de "
                              "categoria e obra vêm do cadastro do ERP.")
            return

        janela = tk.Toplevel(self)
        janela.title("Escolher " + campo)
        widgets.barra_de_titulo(janela)
        combo = widgets.ComboBusca(janela, width=44)
        combo.definir_valores(sorted(opcoes))
        combo.pack(padx=widgets.px(12), pady=widgets.px(12))
        combo.focus_set()

        def confirmar(_ev=None):
            escolhido = opcoes.get(combo.get().strip())
            janela.destroy()
            if escolhido:
                self.editar(iid, campo, escolhido)

        combo.bind("<Return>", confirmar)
        ttk.Button(janela, text="Usar este", command=confirmar).pack(
            pady=(0, widgets.px(10)))

    # --------------------------------------------------------------- atalhos

    def abrir_pdf(self, iid: str) -> None:
        decisao = self.decisoes.get(iid)
        caminho = getattr(getattr(decisao, "guia", None), "pdf", None)
        if not caminho:
            if self.aba is not None:
                self.aba._log("Esta linha não tem PDF.")
            return
        try:
            os.startfile(str(caminho))          # noqa: S606  (Windows)
        except OSError:
            log.warning("não deu para abrir o PDF da guia", exc_info=True)

    def abrir_no_erp(self, iid: str) -> None:
        """Abre a PARCELA no ERP. A rota do ERP é por parcela (`launchId`), e
        não por título: mandar o id do título para lá abre uma tela vazia."""
        decisao = self.decisoes.get(iid)
        if decisao is None or not decisao.parcela_id:
            if self.aba is not None:
                self.aba._log("Esta linha ainda não tem parcela no ERP "
                              "(criação só ganha id depois de lançada).")
            return
        webbrowser.open(anx_config.MC_URL_LANCAMENTO + decisao.parcela_id)

    def parar(self) -> None:
        """Pede a parada da rodada. Quem observa é o worker, entre itens."""
        if self.aba is not None:
            self.aba._parar.set()

    def linhas_de(self, acao) -> list[str]:
        return list(self.lista.get_children(self.secoes[acao]))

    def quantas(self, acao) -> int:
        return len(self.linhas_de(acao))

    def texto_da_linha(self, iid: str) -> str:
        return " ".join(str(v) for v in self.lista.item(iid, "values"))

    def marcadas(self) -> list:
        return [d for iid, d in self.decisoes.items()
                if self.marcado.get(iid) and d.acao in LANCAVEIS]

    def alternar(self, iid: str) -> None:
        if iid not in self.decisoes:
            return
        if self.decisoes[iid].acao not in LANCAVEIS:
            return                        # "você decide" não se marca
        self.marcado[iid] = not self.marcado[iid]
        self.lista.item(iid, text="[x]" if self.marcado[iid] else "[ ]")

    def _clique(self, evento):
        if self.lista.identify_column(evento.x) == "#0":
            self.alternar(self.lista.identify_row(evento.y))
            return "break"
        return None

    def _tecla_marcar(self, _evento=None):
        for iid in self.lista.selection():
            self.alternar(iid)
        return "break"

    # ---------------------------------------------------------------- ações

    def ocupado(self) -> str | None:
        """O que está rodando aqui, para a aba não deixar sair no meio."""
        if self.aba is None:
            return None
        return getattr(self, "_tarefa", "") or None

    def fechar(self) -> None:
        self._tarefa = ""

    def _executar(self, funcao, *args) -> None:
        """Manda para o executor da aba. Trocado por dublê no teste."""
        if self.aba is None:
            return
        self.aba.worker = self.aba.exec.submit(funcao, *args)

    def varrer(self) -> None:
        if self.ocupado():
            return
        ano, mes = self.periodo        # lido AQUI: o worker não fala com o Tcl
        if self.aba is not None:
            self.aba._parar.clear()
        self._tarefa = "varrendo o portal"
        self._executar(self._t_varrer, ano, mes)

    def lancar(self) -> None:
        alvo = self.marcadas()
        if not alvo or self.ocupado():
            return
        ano, mes = self.periodo
        if self.aba is not None:
            self.aba._parar.clear()
        self._tarefa = "lançando no Mais Controle"
        self._executar(self._t_lancar, alvo, ano, mes)

    # Os dois corpos de thread ficam em `_t_varrer`/`_t_lancar`, ligados na
    # Tarefa 9, quando o painel passa a ter a aba e a sessão do ERP.
    def _t_varrer(self, ano, mes):                        # pragma: no cover
        raise NotImplementedError

    def _t_lancar(self, decisoes, ano, mes):              # pragma: no cover
        raise NotImplementedError
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_guias_painel.py -q`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add guias/painel.py tests/test_guias_painel.py
git commit -m "Guias: bloco de tela em Treeview com as quatro secoes"
```

---

### Task 9: Ligar o bloco na aba e ao ERP

**Files:**
- Modify: `guias/painel.py` (`_t_varrer` e `_t_lancar` de verdade)
- Modify: `acessorias/frame.py` (`__init__`, `_build`, `ocupado`, `fechar`)
- Modify: `comprovantes_app.py:326`
- Test: `tests/test_guias_painel.py` (dois testes a mais)

**Interfaces:**
- Consumes: `AnexarFrame.garantir_sessao(log)` e `.mc.page` (é assim que a aba Aportes chega ao ERP), `aportes.erp_sessao.ouvinte` e `HOSTS_CADASTRO`, `aportes.mc_catalogos.Catalogos`, `erp.pagina.TransportePagina`, tudo do `guias/`
- Produces: a aba Acessórias com o bloco funcionando; nada novo para outros módulos

- [ ] **Step 1: Write the failing test**

```python
# em tests/test_guias_painel.py

class _AbaFalsa:
    def __init__(self):
        self.q = __import__("queue").Queue()
        self._parar = __import__("threading").Event()
        self.linhas = []
        self.mapa = None

    def _log(self, msg=""):
        self.linhas.append(msg)

    def _garantir_mapa(self):
        return False              # sem cadastro nesta falsa


def test_varrer_sem_o_mapa_das_contas_avisa_e_nao_abre_navegador(raiz):
    """Sem o cadastro não há vip_url nem pasta: abrir o Chrome só para
    descobrir isso custa meio minuto e assusta."""
    aba = _AbaFalsa()
    p = mod.GuiasPainel(raiz, aba=aba, anx=None)
    try:
        p._t_varrer(2026, 9)
    finally:
        p.destroy()

    assert any("contas" in linha.lower() for linha in aba.linhas)


def test_lancar_anota_no_registro_mesmo_quando_o_erp_recusa(raiz, tmp_path,
                                                            monkeypatch):
    """Review Focus 5: a linha de erro fica registrada, e a rodada seguinte
    sabe que esta guia ainda não foi lançada."""
    from guias import registro as mod_registro
    from guias.modelos import ERRO, Resultado

    aba = _AbaFalsa()
    p = mod.GuiasPainel(raiz, aba=aba, anx=None)
    reg = mod_registro.Registro.carregar(tmp_path / "r.jsonl")
    monkeypatch.setattr(mod, "_sessao_do_erp",
                        lambda _p: (object(), object(), "user-1"))
    monkeypatch.setattr(mod.lancar, "alterar",
                        lambda *a, **k: Resultado(ERRO, motivo="o ERP recusou"))
    try:
        p._gravar([_decisao(ALTERAR, anx_id="1", trade_payable_id="tp-1")],
                  transporte=object(), catalogos=object(), id_usuario="user-1",
                  registro=reg, parcelas=[], regras=None, pasta_backup=tmp_path)
    finally:
        p.destroy()

    assert reg.ja_feito("701", "1", "2026-09") is None
    assert reg.linhas and reg.linhas[-1]["estado"] == ERRO
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_guias_painel.py -q`
Expected: FAIL com `NotImplementedError` no primeiro e `AttributeError: '_gravar'` no segundo

- [ ] **Step 3: Replace the two thread bodies in `guias/painel.py`**

```python
    # --------------------------------------------------------- Mais Controle

def _sessao_do_erp(painel):
    """(transporte, catalogos, id_usuario), pela página que o app já tem logada.

    Mesmo caminho da aba Aportes: passar pela LISTA de Pagamentos faz o ERP
    autenticar os dois back-ends de cadastro, e os cabeçalhos são copiados do
    tráfego da própria página. Sem login novo — o ERP aceita uma sessão por
    usuário, e um login por HTTP derrubaria a do dono.
    """
    from aportes import erp_sessao
    from aportes.mc_catalogos import Catalogos
    from erp.pagina import TransportePagina

    api = painel.anx.garantir_sessao(painel.aba._log)
    pagina = painel.anx.mc.page
    cabecalhos: dict = {}
    ao_requisitar = erp_sessao.ouvinte(cabecalhos)
    pagina.on("request", ao_requisitar)
    try:
        if erp_sessao.na_lista_de_pagamentos(pagina.url):
            pagina.reload(wait_until="domcontentloaded")
        else:
            pagina.goto(anx_config.MC_URL_PAGAMENTOS,
                        wait_until="domcontentloaded")
        for _ in range(60):
            if all(h in cabecalhos for h in erp_sessao.HOSTS_CADASTRO):
                break
            pagina.wait_for_timeout(250)
    finally:
        try:
            pagina.remove_listener("request", ao_requisitar)
        except Exception:
            pass

    faltando = [h for h in erp_sessao.HOSTS_CADASTRO if h not in cabecalhos]
    if faltando:
        raise RuntimeError(
            "não consegui a autenticação de " + ", ".join(faltando) + ".\n"
            "Abra a LISTA de Pagamentos no Chrome (ou recarregue com F5).")

    transporte = TransportePagina(pagina, cabecalhos)
    catalogos = Catalogos(pagina, cabecalhos, painel.aba._log)
    catalogos.carregar()

    # As obras NÃO vêm do `carregar()`: elas saem do REST do outro back-end,
    # pela mesma porta que a aba Contratos usa. Sem este passo `obras` fica
    # vazio e toda criação morre com "Obra não encontrada" — cadastro que
    # está lá, certo, o tempo todo (`aportes/aportes_frame._carregar_obras`).
    try:
        api.garantir_credenciais_anexos(painel.aba._log)
        catalogos.definir_obras(api.listar_obras(painel.aba._log))
    except Exception as e:                                  # noqa: BLE001
        catalogos.definir_obras([])
        painel.aba._log(f"  aviso (obras): {e}")

    return transporte, catalogos, transporte.cabecalho("user-id") or ""


def _nomes_de(indice) -> list[str]:
    """Os `name` de um índice do `Catalogos` (que é {chave: item})."""
    return sorted({str(item.get("name") or "") for item in (indice or {}).values()
                   if item.get("name")})
```

E, na classe, no lugar dos dois `NotImplementedError`:

```python
    def _t_varrer(self, ano: int, mes: int):
        """Roda na thread do executor. Nada de Tcl aqui — só a fila.

        `ano` e `mes` chegam como argumento porque foram lidos na thread da
        interface: ler `StringVar` daqui trava sem hora marcada."""
        try:
            if not self.aba._garantir_mapa():
                self.aba._log("[!] Preencha o arquivo de contas antes: é dele "
                              "que saem o endereço do portal e as empresas.")
                return
            mapa = self.aba.mapa
            scfg, _ = self.aba._sicoob_mods()

            def pasta_de(empresa):
                return (pacote.pasta_do_mes(mapa.raiz, ano, mes, scfg.nome_do_mes)
                        / scfg.nome_pasta_empresa(ano, mes, empresa.nome))

            with PortalClient(mapa.vip_url, log=self.aba._log,
                              headless=True) as cliente:
                cliente.aguardar_login()
                guias = calendario.varrer(cliente, mapa, ano, mes,
                                          pasta_de=pasta_de, log=self.aba._log,
                                          parar=self.aba._parar.is_set)

            transporte, catalogos, _uid = _sessao_do_erp(self)
            parcelas = self._parcelas_do_mes(transporte, ano, mes)
            obras = list(getattr(catalogos, "obras", {}).values())
            regras_ = regras.Regras.carregar()
            registro_ = registro.Registro.carregar()
            decisoes = casamento.decidir(guias, parcelas, regras_, registro_,
                                         f"{ano:04d}-{mes:02d}", obras=obras)
            # Os nomes do cadastro vão junto: é deles que os combos de
            # correção da tela se servem, e sem eles o duplo clique não abre.
            self.aba.q.put(("guias_cadastro",
                            (_nomes_de(catalogos.categorias), obras)))
            self.aba.q.put(("guias", decisoes))
        except Exception as e:
            self.aba._log(f"[!] {e}")
            log.warning("a varredura de guias parou", exc_info=True)
        finally:
            self._tarefa = ""

    def _parcelas_do_mes(self, transporte, ano: int, mes: int) -> list[dict]:
        """As parcelas do mês inteiro, numa leitura só (`size=3000`)."""
        from erp import hosts
        ultimo = calendar.monthrange(ano, mes)[1]
        parametros = urlencode({
            "page": 0, "size": 3000, "type": "ALL", "onlyWork": "false",
            "dateField": "PLANNED", "costCentreType": "ALL",
            "conciliationType": "ALL", "tradePayableType": "ALL",
            "batchOperationType": "NONE",
            "startDate": f"{ano:04d}-{mes:02d}-01",
            "endDate": f"{ano:04d}-{mes:02d}-{ultimo:02d}"})
        resposta = transporte.buscar(
            f"{hosts.LEGACY}/payable-installments/paginated-result?{parametros}")
        if isinstance(resposta, dict) and resposta.get("__erro"):
            raise RuntimeError(f"o ERP recusou a lista de parcelas "
                               f"(HTTP {resposta['__erro']})")
        return list((resposta or {}).get("content") or [])

    def _t_lancar(self, decisoes, ano: int, mes: int):
        try:
            transporte, catalogos, id_usuario = _sessao_do_erp(self)
            parcelas = self._parcelas_do_mes(transporte, ano, mes)
            self._gravar(decisoes, transporte=transporte, catalogos=catalogos,
                         id_usuario=id_usuario,
                         registro=registro.Registro.carregar(),
                         parcelas=parcelas, regras=regras.Regras.carregar(),
                         pasta_backup=util.pasta_base() / "guias_backup")
        except Exception as e:
            self.aba._log(f"[!] {e}")
            log.warning("o lançamento de guias parou", exc_info=True)
        finally:
            self._tarefa = ""

    def _gravar(self, decisoes, *, transporte, catalogos, id_usuario, registro,
                parcelas, regras, pasta_backup) -> None:
        """Grava uma decisão por vez, anotando SEMPRE — inclusive o erro."""
        for decisao in decisoes:
            if self.aba is not None and self.aba._parar.is_set():
                self.aba._log("Parado a pedido; o que já foi gravado está no "
                              "registro.")
                return
            if decisao.acao == ALTERAR:
                resultado = lancar.alterar(transporte, decisao, catalogos,
                                           pasta_backup=pasta_backup)
            else:
                referencia = lancar.referencia_da_obra(
                    transporte, decisao.obra_id, parcelas)
                obra = self._obra_do_erp(catalogos, decisao.obra_id)
                resultado = lancar.criar(transporte, decisao, catalogos,
                                         id_usuario=id_usuario,
                                         referencia=referencia, obra=obra)
            registro.anotar(vip_id=decisao.guia.vip_id,
                            anx_id=decisao.guia.anx_id,
                            competencia=decisao.guia.competencia,
                            acao=decisao.acao, estado=resultado.estado,
                            tpid=resultado.tpid, motivo=resultado.motivo,
                            anexos=resultado.anexos)
            if resultado.tpid and regras is not None and decisao.tipo:
                # O mês seguinte casa exato porque o id ficou guardado — e é
                # isto que impede o parcelado de nascer duas vezes.
                regras.aprender_recorrencia(decisao.tipo, decisao.guia.vip_id,
                                            resultado.tpid, decisao.obra_id)
                if decisao.obra_id:
                    # A obra que o dono deixou passar vale como confirmada.
                    regras.aprender_obra(decisao.tipo, decisao.guia.vip_id,
                                         decisao.obra_id)
            if self.aba is not None:
                self.aba.q.put(("guia_feita", (decisao, resultado)))
        if regras is not None:
            regras.gravar()

    @staticmethod
    def _obra_do_erp(catalogos, obra_id: str) -> dict:
        """A obra inteira, como o ERP a devolve. O POST quer `name` e `status`
        junto do `id` — mandar só o id cria o título sem centro de custo."""
        for obra in (getattr(catalogos, "obras", {}) or {}).values():
            if str(obra.get("id")) == str(obra_id):
                return {k: obra.get(k) for k in ("id", "name", "status",
                                                 "customer", "planning", "cei")
                        if obra.get(k) is not None}
        return {"id": obra_id}
```

E, no `_sessao_do_erp`, a tela por onde passar é `anx_config.MC_URL_PAGAMENTOS`
— a mesma constante que o `anexar/mc_client.py` já usa. Não importar
`aportes.aportes_frame` só para pegar um endereço: seria puxar uma aba inteira
(e o tkinter dela) para dentro deste módulo.

Imports a acrescentar no topo do `guias/painel.py`:

```python
import calendar
from urllib.parse import urlencode

from acessorias import pacote
from acessorias.portal import PortalClient
from guias import calendario, casamento, lancar, regras, registro
```

- [ ] **Step 4: Wire the panel into `acessorias/frame.py`**

No `__init__`, trocar a assinatura e guardar a aba Anexar:

```python
class AcessoriasFrame(ttk.Frame):
    def __init__(self, master, anx=None):
        super().__init__(master)
        self.anx = anx                   # a aba Anexar: dona da sessão do ERP
```

No fim de `_build`, depois do bloco de envio:

```python
        # O bloco das guias é outro assunto e outro arquivo: esta aba já tem
        # 660 linhas e dois assuntos; um terceiro dentro dela não caberia.
        from guias.painel import GuiasPainel
        self.guias = GuiasPainel(self, aba=self, anx=self.anx)
        self.guias.pack(fill="both", expand=True, padx=widgets.px(10))
```

Acrescentar um método que o painel usa e a aba já tinha em forma privada:

```python
    def _sicoob_mods(self):
        """Os módulos do Sicoob, para o painel de guias não repetir o import."""
        return _sicoob()
```

Em `ocupado`, considerar o painel:

```python
    def ocupado(self) -> str | None:
        ocupacao = <o que o método já devolve>
        if ocupacao:
            return ocupacao
        return self.guias.ocupado() if getattr(self, "guias", None) else None
```

Em `fechar`, avisar o painel antes de fechar o portal:

```python
        if getattr(self, "guias", None):
            self.guias.fechar()
```

E em `_drain`, tratar as duas mensagens novas:

```python
            elif tipo == "guias_cadastro":
                self.guias.categorias, self.guias.obras = dados
            elif tipo == "guias":
                self.guias.mostrar(dados)
            elif tipo == "guia_feita":
                decisao, resultado = dados
                self._log(f"  {decisao.guia.empresa}: {resultado.estado}"
                          + (f" — {resultado.motivo}" if resultado.motivo else ""))
```

- [ ] **Step 5: Pass the Anexar tab in `comprovantes_app.py`**

Linha 326:

```python
    aba_acs = AcessoriasFrame(conteudo, aba_anx)
```

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest tests -q`
Expected: tudo passa, inclusive `tests/test_acessorias.py`, `tests/test_acessorias_envio.py` e `tests/test_atalhos_do_app.py` (que monta a janela).

- [ ] **Step 7: Run the CI gates locally**

Run: `python -m ruff check --select E9,F .` — Expected: sem achados
Run: `python -m vermin --target=3.11 --no-tips -vv guias acessorias/portal.py acessorias/config.py erp/pagina.py` — Expected: mínimo ≤ 3.11

- [ ] **Step 8: Commit**

```bash
git add guias/painel.py acessorias/frame.py comprovantes_app.py tests/test_guias_painel.py
git commit -m "Guias: ligar o bloco na aba Acessorias e a sessao do ERP"
```

---

## Depois do plano, antes do PR

Duas coisas que não são código e não podem ser esquecidas:

1. **A medição da conta por obra** (spec, seção "Conta e obra"). Com a tela livre e o dono avisado, ler — só leitura — títulos existentes de duas ou três obras e conferir se a conta é sempre a mesma por obra. Confirmando, `referencia_da_obra` está certa como está. Não confirmando, a linha de criação passa a exigir a conta escolhida na tela, e isso vira uma tarefa nova.
2. **A primeira rodada de verdade**, com o dono à vista, numa empresa só: varrer, conferir a lista, lançar UMA guia e abrir o título no ERP para ver categoria, valor, número do documento e o PDF anexado. Prova ao vivo, como o projeto exige antes de dar qualquer coisa por pronta.

---

## O que a execução mostrou que este plano errou

**Leia esta seção antes de reusar qualquer trecho de código acima.** O plano
foi executado em 21 e 22/09/2026 e as revisões acharam onze defeitos NELE — o
código que está no repositório é o corrigido, e em alguns pontos ele não é mais
o que está escrito acima. O registro completo, com o custo de cada decisão,
ficou no ledger da execução; aqui vai o resumo do que este documento ensinaria
errado.

**Cinco defeitos de dinheiro:**

1. **O valor do boleto vinha ZERO** quando a página trazia Desconto ou Multa
   zerados antes do total — o caso normal de qualquer boleto. O vocabulário de
   rótulo era estreito e o genérico pegava o primeiro `NN,NN` da página.
   Medido: `ler_texto("Desconto R$ 0,00 Valor da cobranca R$ 1.234,56")`
   devolvia `Decimal("0.00")`.
2. **A linha digitável só reconhecia boleto bancário de 47 dígitos.** As guias
   de FGTS e INSS — o alvo primário desta função — são ficha de arrecadação, de
   48 dígitos começando em 8. O projeto já tinha leitor validado por dígito
   verificador para os dois formatos em `pagamentos_dia/ocr_boleto.py`.
3. **A varredura da linha digitável corria a página concatenada**, e o dígito
   verificador sozinho aceita uma janela aleatória em ~0,015% das vezes: com as
   ~200 janelas de uma página (CNPJ, CEP, telefone, datas colados), 2 a 4% de
   chance por página de casar lixo — que numa ficha de arrecadação viraria o
   VALOR do lançamento. A função do projeto filtra por linha física antes.
4. **Sem número de documento, a trava dava JA_LANCADO por coincidência** de
   valor e vencimento. Consequência pior que duplicar: a conta a pagar nunca
   seria criada, e conta que não existe ninguém percebe. Hoje isso vira DECIDIR.
5. **`registro.anotar` aprendeu a SUPOR o estado** a partir da ação, porque o
   primeiro teste deste plano chamava `anotar` sem `estado`. Fabricar prova
   contraria a regra do projeto de não dar nada por feito sem prova.

**Três reinvenções piores de código que o projeto já tinha** — e a lição: antes
de escrever regra de casamento de texto, de leitura de documento ou de
localização de recurso, procurar no repositório quem já faz aquilo.

6. o leitor de linha digitável (item 2);
7. o casamento por palavra inteira: `sugerir_obra` casava por substring, e
   `guias/regras.tem_palavra` existia justamente porque "lote 1" já casou com
   "lote 10" neste projeto;
8. a localização da URL pré-assinada do anexo: o plano escreveu uma regex que
   só aceitava "amazonaws", e `anexar/mc_api.primeira_url_s3` — provada em
   produção com 29 anexos — aceita "s3" também.

**Um defeito de thread que nenhum teste pegaria:**

9. `_sessao_do_erp` tocava os objetos do Playwright síncrono do navegador do
   ERP a partir do executor da aba Acessórias. O `CLAUDE.md` diz que aquele
   navegador só é tocado pelo executor do Anexar, e todas as outras cinco abas
   passam por `anx.submeter`. Sintoma: erro de greenlet no primeiro clique. A
   rodada agora é partida em duas fases, com a emenda pela fila da tela.

**Duas omissões:**

10. **A pasta nova não entrava no pacote.** `guias/` faltava na montagem do
    `codigo.zip` do `build.yml` e em `_PASTAS` de
    `tests/test_imports_do_motor.py` — sem isso o app não abre na máquina do
    usuário. Os testes de empacotamento do projeto pegaram. Entrou junto o
    `motor_minimo.txt` subindo UMA unidade (v2.0.163 → v2.0.164), que é a regra
    para mudança de esteira.
11. **O nome do anexo levava a barra da descrição do portal** ("HONORARIO
    09/2026"), que em nome de objeto vira separador de caminho.

E duas colunas que este plano propôs e que NÃO devem existir: `conta` no
arquivo de regras (a conta vem da obra, decisão do dono), e obra no caminho de
ALTERAR (o título que o ERP devolve já traz conta e obra, e elas não são
tocadas).
