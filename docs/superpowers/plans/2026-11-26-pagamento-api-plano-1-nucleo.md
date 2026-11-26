# Pagamento pela API do Sicoob — plano 1 de 3: núcleo e robô no Sandbox

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** o pacote `pagamento_api/` (lote, cliente do Sicoob, robô, comprovante) e as tabelas da nuvem, provados por testes sem rede e por um ensaio contra o Sandbox do Sicoob — sem tocar no ERP de verdade e sem dinheiro real.

**Architecture:** regras puras (`lote.py`, `executor.py`) com o Sicoob, o ERP e o livro da nuvem como portas injetadas; o cliente HTTP (`sicoob.py`) só fala, não decide; as regras de dinheiro que precisam valer contra qualquer cliente (quem aprova, soma, um título por lote, um INICIADO por item) moram no banco, em gatilhos e índice. O robô (`robo.py`) é uma rodada por chamada, para o Agendador do servidor.

**Tech Stack:** Python 3.11 (o do exe), `requests` e `pypdf` (já no `requirements.lock` — nenhuma dependência nova), Supabase/PostgREST via `nuvem/rest.py`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-26-pagamento-pela-api-sicoob-design.md`

**Os três planos:** 1 (este) núcleo + robô no Sandbox · 2 aba "Aprovar pagamentos" no portal (outro repositório, por PR) · 3 telas do app (Enviar para aprovação, Acompanhar, Parar), ERP de verdade no servidor (porteiro/CDP), token OAuth de produção e o Agendador. O plano 2 e o 3 só nascem depois que este encostar na realidade (regra do cofre: um plano de implementação por vez).

## Global Constraints

- Python 3.11: nada de API de 3.12+ (`vermin --target=3.11` no job `test`).
- Dinheiro em `Decimal`; float só na fronteira do JSON do Sicoob (`sicoob._reais`).
- Nenhuma dependência nova (dependência nova = exe de ~152 MB para todo mundo).
- Repo público: nenhum nome real de fornecedor/pessoa, CPF, CNPJ, número de conta, client_id ou token em código, teste ou comentário. As credenciais do Sandbox são as públicas do portal e ficam num arquivo de ensaio FORA do repo.
- Credenciais de produção, certificado e senha do usuário `robo` só na pasta de chaves do servidor.
- Descrição: a do HTML do dia (`html_pagamentos.descricao_para_colar`), cortada em 100 caracteres.
- Nada se altera nem se apaga na nuvem: só `select` e `insert` (padrão de `20261022100000_pagamentos_do_dia_na_nuvem.sql`).
- O cliente se identifica com `sicoob.USER_AGENT` fixo; nunca trocar a identificação para "passar" no firewall do banco.
- Linha digitável e copia-e-cola em teste saem de fixture que o repo já usa (`tests/test_remessa_dia.py`, `tests/test_html_pagamentos.py`), nunca de memória.
- Mexer no `build.yml` exige subir o `motor_minimo.txt` UMA unidade no mesmo push.

## Desvio consciente da spec

A spec fala em "impressão digital (hash)" do lote. O plano troca por **imutabilidade no banco**: `lote_item` não aceita update/delete, item novo é recusado depois da aprovação, e a aprovação grava a lista exata de itens e o total, conferidos pelo gatilho. Dá a mesma garantia (o robô paga exatamente o que foi aprovado) sem ter de manter o MESMO hash em SQL, Python e JavaScript (portal).

## Review Focus

Medido antes do handoff: o código deste plano foi extraído e rodado (51 testes; sorteio de 500 lotes com quedas e recusas: 0 pagamento em dobro, 0 lote acima do total). O ensaio contra o Sandbox pegou dois defeitos que os dublês não pegariam — o firewall do Sicoob responde **HTTP 200 com HTML** ao `python-requests` padrão, e a consulta do convênio exige `dataPagamento` —, ambos já corrigidos no código abaixo. Os cinco que ainda podem morder:

1. **Corpo do Pix em produção**: o Sandbox não valida; `pix_confirmar` manda o `valor` com vírgula ("1,99") como o exemplo da documentação e sem `origem`. Esperado: antes do primeiro Pix real (plano 3, fase 2), conferir com o Sicoob; o teste `test_confirmar_pix_leva_valor_com_virgula_e_descricao` prende o formato atual para a mudança ser consciente.
2. **Boleto vencido com juros/multa**: o banco cobra mais que o título → `nao_pago` ("boleto diferente: banco cobra X") e volta para o HTML. Esperado e testado (`test_boleto_diferente_nao_paga`).
3. **Convênio "sem dígito verificador"**: a documentação pede o código "sem DV"; o plano manda o código de barras de 44 (sem os DVs de bloco da linha de 48). Confirmar na fase 2; se o banco recusar, o item fica `nao_pago` com o motivo do banco, sem pagar.
4. **Resposta que não é JSON** (firewall, página de erro): nunca vale como "pago" — erro antes do INICIADO é `nao_pago`, depois dele é retomada pela consulta (`test_200_com_html_do_firewall_e_erro_e_nao_sucesso`, `test_erro_500_no_confirmar_tambem_e_ambiguo`).
5. **Duas rodadas ao mesmo tempo** (Agendador sobreposto, duas máquinas): trava de arquivo no servidor (`test_uma_rodada_por_vez`) e, entre máquinas, o índice único `lote_evento_um_iniciado` no banco — o segundo INICIADO do mesmo item é recusado e o robô para sem pagar (`test_um_iniciado_por_item_no_banco`, `test_evento_que_nao_volta_do_banco_impede_o_pagamento`).

## Achados da revisão independente do SQL (já aplicados na migration abaixo)

O agente `revisor-sql-supabase` leu a primeira versão em 26/11/2026. Corrigido: o mesmo título duas vezes no MESMO lote (`unique (lote, titulo)`); corridas entre item, aprovação e cancelamento (trava `for no key update` da linha do lote nos três gatilhos); dois lotes simultâneos com o mesmo título (`pg_advisory_xact_lock` por título); o robô não estava amarrado no banco (gatilho `conferir_evento`: INICIADO só de item aprovado, de lote de hoje, com o robô ligado, mais o índice `lote_evento_um_iniciado`); título de lote aprovado de outro dia não bloqueava; `e_ativo()` nas políticas de gravação (sem isso `test_toda_politica_de_dado_exige_conta_liberada` fica vermelho); `lock_timeout` e `notify pgrst`.

Ficam para o dono e para o plano 3, sem conserto no banco: (F) um admin pode dar papel `aprovador` a uma segunda conta dele e aprovar o próprio lote — atenuação: registrar troca de papel na `auditoria` e o dono decidir quem é admin; (papel `robo` largo) a conta do robô, por ser "ativa", grava nas tabelas que só pedem `e_ativo()` — barrar `robo` nelas numa migration do plano 3; conferir se a tela de Usuários do app aceita o papel novo `robo`.

Reversão (só antes de existir lote real; depois disso apagar é perder histórico de dinheiro): `drop table` das sete tabelas, `drop function` de `conferir_lote/conferir_item/conferir_aprovacao/conferir_cancelamento/conferir_evento/tem_papel/hoje`, e o `perfil_papel_conhecido` de volta a `('admin','operador','aprovador')` — depois de conferir que nenhum perfil tem papel `robo`.

## Modelo por tarefa

| Tarefa | Implementa | Revisa | Por quê |
|---|---|---|---|
| 1 pacote no zip | haiku | sonnet | mecânico, código dado |
| 2 lote | sonnet | sonnet | código dado; regra do HTML |
| 3 cliente Sicoob | sonnet | sonnet | código dado |
| 4 comprovante | haiku | sonnet | código dado, sem dinheiro |
| 5 executor | sonnet | **opus** | decide pagamento: dinheiro irreversível |
| 6 SQL da nuvem | sonnet | **opus** + agente `revisor-sql-supabase` | RLS e regras de dinheiro no banco |
| 7 nuvem do robô | sonnet | sonnet | código dado |
| 8 robô e ensaio | sonnet | sonnet | código dado; ensaio manual |
| revisão final do ramo | — | **opus** + agente `revisor-dinheiro` | antes do PR |

Despacho de executor: tudo aqui é síncrono e de uma thread só (o robô roda fora do app). Não há recurso com afinidade de thread neste plano; a integração com o `AnexarFrame.exec`/Playwright é do plano 3.

---

### Task 1: Pacote `pagamento_api` no `codigo.zip`

**Files:**
- Create: `pagamento_api/__init__.py`
- Modify: `.github/workflows/build.yml` (antes da linha do `Compress-Archive`, hoje a 483)
- Modify: `motor_minimo.txt` (`v2.0.234` → `v2.0.235`)
- Modify: `tests/test_imports_do_motor.py` (acrescentar `"pagamento_api"` ao fim da tupla `_PASTAS`; errata da execução, 26/11/2026)
- Test: `tests/test_empacotamento.py` (já existe; cobra a pasta nova)

**Interfaces:**
- Produces: o pacote importável `pagamento_api` dentro do `codigo.zip` (o plano 3 faz o app importá-lo).

- [ ] **Step 1: criar o pacote e ver o teste de empacotamento falhar**

`pagamento_api/__init__.py`:

```python
"""Pagamento pela API do Sicoob com aprovação do diretor (spec de 26/11/2026)."""
```

Run: `python -m pytest tests/test_empacotamento.py -q`
Expected: FAIL em `test_toda_pasta_de_codigo_entra_no_codigo_zip` citando `pagamento_api`.

- [ ] **Step 2: acrescentar a pasta ao `build.yml`**, logo depois das duas linhas de `conciliacao_dia` e antes do `Compress-Archive`:

```yaml
          New-Item -ItemType Directory codigo_embutido/pagamento_api | Out-Null
          Copy-Item pagamento_api/*.py codigo_embutido/pagamento_api/
```

- [ ] **Step 3: subir o `motor_minimo.txt` uma unidade** (só a esteira mudou; ver CLAUDE.md, "sobe UMA unidade"): conteúdo `v2.0.235`.

- [ ] **Step 4: rodar**

Run: `python -m pytest tests/test_empacotamento.py tests/test_imports_do_motor.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pagamento_api/__init__.py .github/workflows/build.yml motor_minimo.txt
git commit -m "pagamento_api: pacote novo no codigo.zip (motor_minimo +1)"
```

### Task 2: O lote do dia (`lote.py`)

**Files:**
- Create: `pagamento_api/lote.py`
- Test: `tests/test_pagamento_api_lote.py`

**Interfaces:**
- Consumes: `pagamentos_dia.nivel.PODE_PAGAR/OLHE`, `pagamentos_dia.ocr_boleto.digitos/codigo_de_barras`, `pagamentos_dia.regras_pagamento.PIX_COPIA_COLA` (conferidos no código em 26/11/2026); a lista que `pagamentos_dia.html_pagamentos.contas_do_html_geral(resultado, dia)` devolve (`[{"nome", "entries": [{"id", "tipo", "dados_limpo", "centavos", "descricao", "favorecido", "bloqueio", "nivel", "nivel_rotulo", ...}]}]`).
- Produces: `ItemLote(ordem, titulo, alvo, conta, tipo, dados, valor: Decimal, favorecido, documento_esperado, descricao)`, `Fora(alvo, conta, valor, favorecido, motivo)`, `itens_do_html(contas, documento_de) -> (list[ItemLote], list[Fora])`, `total(itens) -> Decimal`, `tipo_api(tipo_html, dados) -> (tipo, dado|motivo)`, `e_sicoob(conta)`, constantes `BOLETO, PIX_CHAVE, PIX_QR, CONVENIO, TIPOS, LIMITE_DESCRICAO`.

- [ ] **Step 1: escrever o teste**

`tests/test_pagamento_api_lote.py`:

```python
# -*- coding: utf-8 -*-
from decimal import Decimal

from pagamento_api import lote
from pagamentos_dia import nivel

#: Linhas que outros testes do repositório já usam e que fecham nos DVs
#: (test_remessa_dia.py). Nunca escrever linha digitável de memória.
BANCARIO = "34191570070002492437524177010006115340000115050"
ARRECADACAO = "818900000019234500012021610150000001000123456789"
#: Copia-e-cola de test_html_pagamentos.py (CRC fictício: o lote só reconhece a forma).
PIX_QR = ("00020126330014br.gov.bcb.pix0111000000000005204000053039865406100.00"
          "5802BR5913FULANO DE TAL6008GOIANIA62070503***6304ABCD")


def _e(id_, tipo, dados, centavos, **k):
    base = {"id": id_, "tipo": tipo, "dados_limpo": dados, "centavos": centavos,
            "favorecido": "FORNECEDOR A", "descricao": "OBRA X NF 1 OC 2",
            "bloqueio": "", "nivel": nivel.PODE_PAGAR, "nivel_rotulo": "PODE PAGAR"}
    base.update(k)
    return base


def _doc(_fav):
    return "11.222.333/0001-81"


def test_boleto_pix_e_convenio_entram_com_o_tipo_certo():
    contas = [{"nome": "OBRA X - SICOOB", "entries": [
        _e("1", "Boleto", BANCARIO, 115050),
        _e("2", "Boleto", ARRECADACAO, 1923),
        _e("3", "Pix", "fornecedor@exemplo.com", 50000),
        _e("4", "Pix", PIX_QR, 1000)]}]
    itens, fora = lote.itens_do_html(contas, _doc)
    assert fora == []
    assert [i.tipo for i in itens] == [lote.BOLETO, lote.CONVENIO, lote.PIX_CHAVE, lote.PIX_QR]
    assert len(itens[0].dados) == 44 and itens[0].dados.startswith("341")
    assert len(itens[1].dados) == 44 and itens[1].dados.startswith("8")
    assert itens[2].documento_esperado == "11222333000181"
    assert [i.ordem for i in itens] == [1, 2, 3, 4]
    assert lote.total(itens) == Decimal("1679.73")


def test_fica_fora_com_motivo():
    contas = [
        {"nome": "OBRA X - INTER", "entries": [_e("10", "Pix", "a@b.com", 100)]},
        {"nome": "OBRA X - SICOOB", "entries": [
            _e("11", "Pix", "a@b.com", 100, nivel=nivel.OLHE, nivel_rotulo="OLHE"),
            _e("12", "Pix", "a@b.com", 100, bloqueio="mesma linha digitável em 2 lançamentos"),
            _e("13#mao:1", "Pix", "a@b.com", 100),
            _e("14#1/2", "Boleto", BANCARIO, 100),
            _e("14#2/2", "Boleto", BANCARIO, 100),
            _e("15", "Boleto", BANCARIO[:-1] + "1", 100),
            _e("16", "Pix", "a@b.com", 0)]}]
    itens, fora = lote.itens_do_html(contas, _doc)
    assert itens == []
    motivos = {f.alvo: f.motivo for f in fora}
    assert motivos["10"] == "conta não é Sicoob"
    assert motivos["11"] == "nível OLHE"
    assert motivos["12"].startswith("mesma linha")
    assert motivos["13#mao:1"] == "pagamento à mão, sem lançamento"
    assert motivos["14#1/2"] == motivos["14#2/2"] == "lançamento dividido em mais de uma linha"
    assert motivos["15"] == "linha digitável não confere"
    assert motivos["16"] == "valor zero"


def test_pix_por_chave_sem_documento_no_cadastro_fica_fora():
    contas = [{"nome": "OBRA X - SICOOB", "entries": [_e("1", "Pix", "a@b.com", 100)]}]
    itens, fora = lote.itens_do_html(contas, lambda f: "")
    assert itens == [] and fora[0].motivo == "Pix sem CPF/CNPJ do favorecido no cadastro"


def test_descricao_cortada_em_100():
    contas = [{"nome": "OBRA X - SICOOB", "entries": [
        _e("1", "Boleto", BANCARIO, 100, descricao="X" * 150)]}]
    itens, _ = lote.itens_do_html(contas, _doc)
    assert len(itens[0].descricao) == 100
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/test_pagamento_api_lote.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'pagamento_api.lote'`.

- [ ] **Step 3: implementar**

`pagamento_api/lote.py`:

```python
# -*- coding: utf-8 -*-
"""O lote do dia que vai para aprovação: o que pode ir pela API e o que fica fora.

Módulo puro: sem tela, sem rede. Entra a lista de
`html_pagamentos.contas_do_html_geral` (o mesmo dado que o HTML do dia mostra) e
sai a lista de `ItemLote`, mais a lista do que fica FORA com o motivo. Dinheiro em
Decimal, sempre a partir dos centavos.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from pagamentos_dia import nivel, ocr_boleto
from pagamentos_dia import regras_pagamento as regras

BOLETO, PIX_CHAVE, PIX_QR, CONVENIO = "boleto", "pix_chave", "pix_qr", "convenio"
TIPOS = (BOLETO, PIX_CHAVE, PIX_QR, CONVENIO)
#: Teto da descrição nos bancos que não são o Inter (decisão de 14/09/2026).
LIMITE_DESCRICAO = 100


@dataclass(frozen=True)
class ItemLote:
    ordem: int
    titulo: str              # id do lançamento no ERP (sem o "#parte")
    alvo: str                # id da linha do HTML (chave do "já paguei")
    conta: str               # nome da conta pagadora, como no ERP
    tipo: str                # um de TIPOS
    dados: str               # código de barras de 44 | chave | copia-e-cola
    valor: Decimal
    favorecido: str
    documento_esperado: str  # CPF/CNPJ só dígitos ("" quando o cadastro não tem)
    descricao: str


@dataclass(frozen=True)
class Fora:
    alvo: str
    conta: str
    valor: Decimal
    favorecido: str
    motivo: str


def _norm(texto) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(t.upper().split())


def e_sicoob(conta) -> bool:
    return "SICOOB" in _norm(conta)


def tipo_api(tipo_html: str, dados) -> tuple[str, str]:
    """(tipo da API, dado pronto) ou ("", motivo) quando não dá para pagar pela API."""
    d = str(dados or "").strip()
    if not d:
        return "", "sem dado de pagamento"
    if tipo_html == "Pix":
        if regras.PIX_COPIA_COLA.search(re.sub(r"\s+", "", d)):
            return PIX_QR, re.sub(r"\s+", "", d)
        return PIX_CHAVE, d
    if tipo_html == "Boleto":
        dig = ocr_boleto.digitos(d)
        barras = ocr_boleto.codigo_de_barras(dig) if len(dig) in (47, 48) else ""
        if len(barras) != 44:
            return "", "linha digitável não confere"
        return (CONVENIO if barras.startswith("8") else BOLETO), barras
    return "", f"tipo {tipo_html or '?'} não vai pela API"


def itens_do_html(contas: list[dict], documento_de) -> tuple[list[ItemLote], list[Fora]]:
    """As entradas do HTML do dia viram itens do lote ou linhas de fora.

    Entra só o que o HTML diz "PODE PAGAR", sem bloqueio, em conta Sicoob, com
    lançamento do ERP e que não seja parte de lançamento dividido (o mesmo título
    em mais de uma linha) nem pagamento à mão. `documento_de(favorecido)` devolve
    o CPF/CNPJ do cadastro ("" se não houver)."""
    itens: list[ItemLote] = []
    fora: list[Fora] = []
    por_titulo: dict[str, int] = {}
    for c in contas:
        for e in c.get("entries", ()):
            t = str(e.get("id") or "").split("#", 1)[0]
            if t:
                por_titulo[t] = por_titulo.get(t, 0) + 1
    for c in contas:
        conta = str(c.get("nome") or "")
        for e in c.get("entries", ()):
            alvo = str(e.get("id") or "")
            valor = (Decimal(int(e.get("centavos") or 0)) / 100).quantize(Decimal("0.01"))
            fav = str(e.get("favorecido") or "")
            titulo, _, resto = alvo.partition("#")
            motivo = ""
            tipo = dado = ""
            if not e_sicoob(conta):
                motivo = "conta não é Sicoob"
            elif not titulo or resto.startswith("mao:"):
                motivo = "pagamento à mão, sem lançamento"
            elif por_titulo.get(titulo, 0) > 1:
                motivo = "lançamento dividido em mais de uma linha"
            elif e.get("bloqueio"):
                motivo = str(e["bloqueio"])
            elif e.get("nivel") != nivel.PODE_PAGAR:
                motivo = f"nível {e.get('nivel_rotulo') or e.get('nivel') or '?'}"
            elif valor <= 0:
                motivo = "valor zero"
            else:
                tipo, dado = tipo_api(str(e.get("tipo") or ""), e.get("dados_limpo"))
                if not tipo:
                    motivo = dado
            doc = re.sub(r"\D", "", str(documento_de(fav) or "")) if not motivo else ""
            if not motivo and tipo == PIX_CHAVE and len(doc) not in (11, 14):
                motivo = "Pix sem CPF/CNPJ do favorecido no cadastro"
            if motivo:
                fora.append(Fora(alvo, conta, valor, fav, motivo))
                continue
            itens.append(ItemLote(len(itens) + 1, titulo, alvo, conta, tipo, dado, valor,
                                  fav, doc, str(e.get("descricao") or "")[:LIMITE_DESCRICAO]))
    return itens, fora


def total(itens) -> Decimal:
    return sum((i.valor for i in itens), Decimal("0.00"))
```

- [ ] **Step 4: rodar e ver passar**

Run: `python -m pytest tests/test_pagamento_api_lote.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add pagamento_api/lote.py tests/test_pagamento_api_lote.py
git commit -m "pagamento_api: lote do dia a partir do HTML (o que vai pela API e o que fica fora)"
```

### Task 3: Cliente do Sicoob (`sicoob.py`)

**Files:**
- Create: `pagamento_api/sicoob.py`
- Test: `tests/test_pagamento_api_sicoob.py`

**Interfaces:**
- Produces: `Ambiente(pix, boleto, convenio)`, `SANDBOX`, `PRODUCAO`, `USER_AGENT`, `ErroSicoob(status|None, corpo)`, `ContaApi(cooperativa, numero, tipo_pessoa)`, `Sicoob(sessao, ambiente, client_id, token: Callable[[], str], cert=None)` com `pix_iniciar(chave)`, `pix_confirmar(e2e, valor, descricao)`, `pix_qrcode(copia_e_cola, valor, documento)`, `pix_consultar(e2e)`, `boleto_consultar(codigo, conta)`, `boleto_pagar(codigo, conta, consulta, valor, descricao, chave, dia)`, `boleto_comprovante(chave)`, `convenio_consultar(codigo, dia)`, `convenio_pagar(codigo, conta, valor, dia, transacao)`; `chave_de_idempotencia(conta, uuid) -> "coop-conta-uuid"`. Todos devolvem `dict` (o `resultado` já desembrulhado) ou levantam `ErroSicoob`.

- [ ] **Step 1: escrever o teste**

`tests/test_pagamento_api_sicoob.py`:

```python
# -*- coding: utf-8 -*-
"""O cliente monta o pedido que a documentação do Sicoob pede. Sessão falsa: nenhuma rede."""
import json
from decimal import Decimal

import pytest

from pagamento_api import sicoob as sc


class Resposta:
    def __init__(self, status, corpo):
        self.status_code, self.text = status, json.dumps(corpo)


class Sessao:
    def __init__(self, status=200, corpo=None, erro=None):
        self.status, self.corpo, self.erro = status, corpo or {}, erro
        self.pedidos = []

    def request(self, metodo, url, **k):
        self.pedidos.append((metodo, url, k))
        if self.erro:
            raise self.erro
        return Resposta(self.status, self.corpo)


CONTA = sc.ContaApi(4342, 1234569, 1)


def _cliente(sessao):
    return sc.Sicoob(sessao, sc.SANDBOX, "cid", lambda: "tok", cert=("c.pem", "k.pem"))


def test_cabecalhos_certificado_e_endereco():
    s = Sessao(corpo={"endToEndId": "E1"})
    _cliente(s).pix_iniciar("a@b.com")
    metodo, url, k = s.pedidos[0]
    assert (metodo, url) == ("POST", sc.SANDBOX.pix + "/pagamentos")
    assert k["headers"]["Authorization"] == "Bearer tok" and k["headers"]["client_id"] == "cid"
    assert k["cert"] == ("c.pem", "k.pem")
    assert json.loads(k["data"]) == {"chave": "a@b.com"}


def test_confirmar_pix_leva_valor_com_virgula_e_descricao():
    s = Sessao(corpo={"estado": "REALIZADO"})
    _cliente(s).pix_confirmar("E1", Decimal("1234.5"), "OBRA X NF 1")
    corpo = json.loads(s.pedidos[0][2]["data"])
    assert corpo["valor"] == "1234,50" and corpo["descricao"] == "OBRA X NF 1"


def test_pagar_boleto_leva_a_chave_de_idempotencia_e_a_conta():
    s = Sessao(corpo={"resultado": {"idPagamento": 9}})
    chave = sc.chave_de_idempotencia(CONTA, "u-1")
    r = _cliente(s).boleto_pagar("3" * 44, CONTA, {"identificadorConsulta": "h"},
                                 Decimal("152.30"), "DESC", chave, "2026-11-27")
    _, url, k = s.pedidos[0]
    assert url == sc.SANDBOX.boleto + "/boletos/pagamentos/" + "3" * 44
    assert k["headers"]["x-idempotency-key"] == "4342-1234569-u-1"
    corpo = json.loads(k["data"])
    assert corpo["valorBoleto"] == 152.3 and corpo["identificadorConsulta"] == "h"
    assert corpo["debtorAccount"] == {"issuer": 4342, "number": 1234569, "accountType": 0, "personType": 1}
    assert r == {"idPagamento": 9}


def test_consultar_boleto_manda_a_conta():
    s = Sessao(corpo={"resultado": {"valorPagamento": 1.0}})
    assert _cliente(s).boleto_consultar("3" * 44, CONTA) == {"valorPagamento": 1.0}
    assert s.pedidos[0][2]["params"] == {"numeroConta": 1234569}


def test_fora_de_2xx_e_sem_rede_viram_erro():
    with pytest.raises(sc.ErroSicoob) as e:
        _cliente(Sessao(status=400, corpo={"mensagens": []})).pix_consultar("E1")
    assert e.value.status == 400
    with pytest.raises(sc.ErroSicoob) as e:
        _cliente(Sessao(erro=TimeoutError("x"))).pix_consultar("E1")
    assert e.value.status is None


def test_producao_usa_os_enderecos_de_producao():
    assert sc.PRODUCAO.boleto == "https://api.sicoob.com.br/pagamentos/v3"
    assert sc.PRODUCAO.pix == "https://api.sicoob.com.br/pix-pagamentos/v2"


class RespostaCrua:
    def __init__(self, status, texto):
        self.status_code, self.text = status, texto


def test_200_com_html_do_firewall_e_erro_e_nao_sucesso():
    class S(Sessao):
        def request(self, metodo, url, **k):
            self.pedidos.append((metodo, url, k))
            return RespostaCrua(200, "<html><head><title>Request Rejected</title></head></html>")
    with pytest.raises(sc.ErroSicoob) as e:
        _cliente(S()).pix_iniciar("a@b.com")
    assert e.value.status == 200 and "não é JSON" in str(e.value)


def test_identificacao_fixa_do_cliente():
    s = Sessao(corpo={})
    _cliente(s).pix_consultar("E1")
    assert s.pedidos[0][2]["headers"]["User-Agent"] == sc.USER_AGENT
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/test_pagamento_api_sicoob.py -q`
Expected: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: implementar**

`pagamento_api/sicoob.py`:

```python
# -*- coding: utf-8 -*-
"""Cliente das APIs de pagamento do Sicoob (Pix, boleto, convênio).

Só fala HTTP: não decide nada. Quem decide se paga é `executor.py`. A sessão
`requests` é injetada (o teste passa uma falsa); certificado e token vêm da
configuração do servidor e nunca passam por log. Endereços lidos do portal
developers.sicoob.com.br em 26/11/2026; no Sandbox o boleto mora em
`cobranca-bancaria-pagamentos/v3`, na produção em `pagamentos/v3`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable


@dataclass(frozen=True)
class Ambiente:
    pix: str
    boleto: str
    convenio: str


SANDBOX = Ambiente(
    pix="https://sandbox.sicoob.com.br/sicoob/sandbox/pix-pagamentos/v2",
    boleto="https://sandbox.sicoob.com.br/sicoob/sandbox/cobranca-bancaria-pagamentos/v3",
    convenio="https://sandbox.sicoob.com.br/sicoob/sandbox/convenios-pagamentos/v2",
)
PRODUCAO = Ambiente(
    pix="https://api.sicoob.com.br/pix-pagamentos/v2",
    boleto="https://api.sicoob.com.br/pagamentos/v3",
    convenio="https://api.sicoob.com.br/convenios-pagamentos/v2",
)


#: Identificação fixa e honesta do cliente. O firewall do Sicoob recusa o
#: "python-requests" padrão com HTTP 200 e uma página HTML (medido no Sandbox
#: em 26/11/2026): por isso a identificação própria E a recusa de resposta
#: que não é JSON, abaixo. Não se troca este valor para "passar" no firewall.
USER_AGENT = "comprovantes-mais-controle/pagamento-api 1.0"


class ErroSicoob(RuntimeError):
    """O banco respondeu fora de 2xx. `status` None = não houve resposta."""

    def __init__(self, status, corpo: str):
        super().__init__(f"Sicoob {status}: {corpo[:300]}")
        self.status = status
        self.corpo = corpo


@dataclass(frozen=True)
class ContaApi:
    """A conta pagadora como o Sicoob a conhece (vem do arquivo do servidor)."""
    cooperativa: int
    numero: int
    tipo_pessoa: int     # o `personType` do Sicoob para esta conta (arquivo do servidor)


def _reais(valor: Decimal) -> float:
    """O JSON do Sicoob quer número; a conversão para float só existe aqui."""
    return float(Decimal(valor).quantize(Decimal("0.01")))


class Sicoob:
    def __init__(self, sessao, ambiente: Ambiente, client_id: str,
                 token: Callable[[], str], cert=None, timeout: float = 30.0):
        self._s = sessao
        self._a = ambiente
        self._cid = client_id
        self._token = token
        self._cert = cert
        self._timeout = timeout

    def _chamar(self, metodo: str, url: str, *, corpo=None, params=None, extra=None) -> dict:
        h = {"User-Agent": USER_AGENT,
             "Authorization": "Bearer " + self._token(), "client_id": self._cid,
             "Accept": "application/json", "Content-Type": "application/json"}
        h.update(extra or {})
        try:
            r = self._s.request(metodo, url, headers=h, params=params,
                                data=json.dumps(corpo) if corpo is not None else None,
                                cert=self._cert, timeout=self._timeout)
        except Exception as e:  # rede caiu: o executor trata como "não sei se saiu"
            raise ErroSicoob(None, repr(e)) from e
        texto = r.text or ""
        if not 200 <= r.status_code < 300:
            raise ErroSicoob(r.status_code, texto)
        if not texto.strip():
            return {}
        try:
            corpo = json.loads(texto)
        except ValueError:
            # 200 com HTML = recusa do firewall, não sucesso. Nunca vale como "pago".
            raise ErroSicoob(r.status_code, "resposta não é JSON: " + texto[:200]) from None
        if not isinstance(corpo, dict):
            raise ErroSicoob(r.status_code, "resposta não é um objeto JSON")
        return corpo

    # ------------------------------------------------------------------ Pix
    def pix_iniciar(self, chave: str) -> dict:
        return self._chamar("POST", self._a.pix + "/pagamentos", corpo={"chave": chave})

    def pix_confirmar(self, e2e: str, valor: Decimal, descricao: str) -> dict:
        corpo = {"endToEndId": e2e, "valor": f"{Decimal(valor):.2f}".replace(".", ","),
                 "descricao": descricao, "repeticao": False, "meioIniciacao": "MANUAL"}
        return self._chamar("POST", self._a.pix + "/pagamentos/confirmacao", corpo=corpo)

    def pix_qrcode(self, copia_e_cola: str, valor: Decimal, documento: str) -> dict:
        corpo = {"qrcode": copia_e_cola, "valor": f"{Decimal(valor):.2f}",
                 "pagarComJurosMulta": False, "destino": {"cpfCnpj": documento}}
        return self._chamar("POST", self._a.pix + "/pagamentos/qrcode", corpo=corpo)

    def pix_consultar(self, e2e: str) -> dict:
        return self._chamar("GET", self._a.pix + f"/pagamentos/{e2e}")

    # --------------------------------------------------------------- boleto
    def boleto_consultar(self, codigo: str, conta: ContaApi) -> dict:
        r = self._chamar("GET", self._a.boleto + f"/boletos/{codigo}",
                         params={"numeroConta": conta.numero})
        return r.get("resultado", r)

    def boleto_pagar(self, codigo: str, conta: ContaApi, consulta: dict, valor: Decimal,
                     descricao: str, chave: str, dia: str) -> dict:
        corpo = {"identificadorConsulta": consulta.get("identificadorConsulta", ""),
                 "valorBoleto": _reais(valor), "amount": _reais(valor),
                 "valorDescontoAbatimento": 0, "valorMultaMora": 0,
                 "aceitaValorDivergente": False, "descricaoObservacao": descricao,
                 "date": dia,
                 "debtorAccount": {"issuer": conta.cooperativa, "number": conta.numero,
                                   "accountType": 0, "personType": conta.tipo_pessoa}}
        r = self._chamar("POST", self._a.boleto + f"/boletos/pagamentos/{codigo}",
                         corpo=corpo, extra={"x-idempotency-key": chave})
        return r.get("resultado", r)

    def boleto_comprovante(self, chave: str) -> dict:
        r = self._chamar("GET", self._a.boleto
                         + f"/boletos/pagamentos/{chave}/idempotency/comprovantes")
        return r.get("resultado", r)

    # ------------------------------------------------------------- convênio
    def convenio_consultar(self, codigo: str, dia: str) -> dict:
        r = self._chamar("GET", self._a.convenio + f"/arrecadacao/codigo-barras/{codigo}",
                         params={"dataPagamento": dia})
        return r.get("resultado", r)

    def convenio_pagar(self, codigo: str, conta: ContaApi, valor: Decimal, dia: str,
                       transacao: int) -> dict:
        corpo = {"identificacao": {"instituicao": conta.cooperativa, "unidade": 0},
                 "pagamento": {"valorPago": _reais(valor), "valorDocumento": _reais(valor),
                               "dataPagamento": dia},
                 "transacao": transacao}
        r = self._chamar("POST", self._a.convenio
                         + f"/arrecadacao/codigo-barras/{codigo}/pagamentos", corpo=corpo)
        return r.get("resultado", r)


def chave_de_idempotencia(conta: ContaApi, uuid_: str) -> str:
    """O formato que o Sicoob pede: cooperativa (até 4), conta (até 14), UUID."""
    return f"{conta.cooperativa}-{conta.numero}-{uuid_}"
```

- [ ] **Step 4: rodar e ver passar**

Run: `python -m pytest tests/test_pagamento_api_sicoob.py -q`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add pagamento_api/sicoob.py tests/test_pagamento_api_sicoob.py
git commit -m "pagamento_api: cliente das APIs de pagamento do Sicoob (Pix, boleto, convênio)"
```

### Task 4: Comprovante em PDF (`comprovante.py`)

**Files:**
- Create: `pagamento_api/comprovante.py`
- Test: `tests/test_pagamento_api_comprovante.py`

**Interfaces:**
- Consumes: `lote.ItemLote` (só os atributos `ordem, titulo, conta, valor, favorecido, descricao`).
- Produces: `gerar_pdf(pasta, item, dados: dict, hoje) -> Path`, `nome_do_arquivo(item, hoje) -> str`, `salvar_bruto(pasta, item, tipo, dados) -> Path`, `ler_bruto(pasta, item, tipo) -> dict | None`, `pdf_de_texto(linhas) -> bytes`.

- [ ] **Step 1: escrever o teste**

`tests/test_pagamento_api_comprovante.py`:

```python
# -*- coding: utf-8 -*-
"""O PDF do comprovante abre num leitor de verdade (pypdf, que já está no exe)."""
from datetime import date
from decimal import Decimal

from pypdf import PdfReader

from pagamento_api import comprovante as cp
from pagamento_api import lote as lt


def test_pdf_do_comprovante_abre_e_tem_a_descricao(tmp_path):
    item = lt.ItemLote(3, "T3", "T3", "OBRA X - SICOOB", lt.BOLETO, "3" * 44,
                       Decimal("152.30"), "FORNECEDOR (A)", "", "OBRA X NF 12 OC 7")
    p = cp.gerar_pdf(tmp_path, item, {"situacaoPagamento": "EFETIVADO", "valorPagamento": 152.3},
                     date(2026, 11, 27))
    assert p.name == "2026-11-27 OBRA X NF 12 OC 7 R$ 152,30 item 3.pdf"
    texto = PdfReader(str(p)).pages[0].extract_text()
    assert "OBRA X NF 12 OC 7" in texto and "FORNECEDOR (A)" in texto and "EFETIVADO" in texto


def test_bruto_do_convenio_volta_igual(tmp_path):
    item = lt.ItemLote(1, "T1", "T1", "C - SICOOB", lt.CONVENIO, "8" * 44, Decimal("1.00"), "F", "", "D")
    cp.salvar_bruto(tmp_path, item, "convenio", {"comprovante": "QUJD", "arrecadacao": {"nsu": 1}})
    assert cp.ler_bruto(tmp_path, item, "convenio") == {"comprovante": "QUJD", "arrecadacao": {"nsu": 1}}
    outro = lt.ItemLote(2, "T2", "T2", "C - SICOOB", lt.CONVENIO, "8" * 44, Decimal("1.00"), "F", "", "D")
    assert cp.ler_bruto(tmp_path, outro, "convenio") is None
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/test_pagamento_api_comprovante.py -q`
Expected: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: implementar**

`pagamento_api/comprovante.py`:

```python
# -*- coding: utf-8 -*-
"""O comprovante em PDF, montado do JSON que o Sicoob devolve.

Sem biblioteca nova (biblioteca nova = exe novo para todo mundo): um PDF de
texto escrito à mão, Helvetica, uma página. A descrição do HTML vai dentro do
PDF e no nome do arquivo. O JSON cru do convênio (o comprovante vem na própria
resposta do pagamento) fica gravado ao lado, para a retomada achar.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from pathlib import Path

#: Campos que aparecem primeiro, nesta ordem, quando existem no JSON.
_PRIMEIROS = ("situacaoPagamento", "estado", "dataPagamento", "horario", "valorPagamento",
              "valor", "nomeRazaoSocialBeneficiario", "numeroCpfCnpjBeneficiario",
              "numeroLinhaDigitavel", "endToEndId", "numeroAutenticacaoPagamento", "nsu",
              "autenticacao")


def _ascii(t) -> str:
    return unicodedata.normalize("NFKD", str(t if t is not None else "")).encode(
        "latin-1", "ignore").decode("latin-1")


def _limpo_para_nome(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r'[\\/:*?"<>|]+', " ", t)
    return " ".join(t.split())[:120]


def nome_do_arquivo(item, hoje: date) -> str:
    valor = f"{item.valor:.2f}".replace(".", ",")
    return _limpo_para_nome(f"{hoje:%Y-%m-%d} {item.descricao} R$ {valor} item {item.ordem}") + ".pdf"


def _achatar(d, prefixo="") -> list[tuple[str, str]]:
    linhas = []
    for k, v in (d or {}).items():
        chave = f"{prefixo}{k}"
        if isinstance(v, dict):
            linhas += _achatar(v, chave + ".")
        elif isinstance(v, list):
            linhas.append((chave, json.dumps(v, ensure_ascii=False)[:200]))
        elif k != "comprovante":          # o base64 do convênio não vai para o texto
            linhas.append((chave, str(v)))
    return linhas


def linhas_do_comprovante(item, dados: dict, hoje: date) -> list[str]:
    pares = _achatar(dados)
    ordem = {k: i for i, k in enumerate(_PRIMEIROS)}
    pares.sort(key=lambda kv: ordem.get(kv[0].rsplit(".", 1)[-1], len(ordem)))
    valor = f"{item.valor:.2f}".replace(".", ",")
    topo = ["COMPROVANTE DE PAGAMENTO - SICOOB (API)",
            f"Descricao: {item.descricao}",
            f"Favorecido: {item.favorecido}",
            f"Valor: R$ {valor}",
            f"Conta: {item.conta}",
            f"Gerado em {hoje:%d/%m/%Y}", ""]
    return topo + [f"{k}: {v}" for k, v in pares]


def _escapar_pdf(t: str) -> str:
    return t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf_de_texto(linhas: list[str]) -> bytes:
    """Uma página A4, Helvetica 10, uma linha por item (corta o que não cabe)."""
    corpo = ["BT", "/F1 10 Tf", "40 800 Td", "13 TL"]
    for ln in linhas[:58]:
        corpo.append(f"({_escapar_pdf(_ascii(ln)[:110])}) Tj T*")
    corpo.append("ET")
    stream = "\n".join(corpo).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    saida = bytearray(b"%PDF-1.4\n")
    posicoes = []
    for n, o in enumerate(objs, start=1):
        posicoes.append(len(saida))
        saida += f"{n} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(saida)
    saida += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for p in posicoes:
        saida += f"{p:010d} 00000 n \n".encode()
    saida += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()
    return bytes(saida)


def gerar_pdf(pasta: Path, item, dados: dict, hoje: date) -> Path:
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / nome_do_arquivo(item, hoje)
    destino.write_bytes(pdf_de_texto(linhas_do_comprovante(item, dados, hoje)))
    return destino


def _bruto(pasta: Path, item, tipo: str) -> Path:
    return Path(pasta) / f"bruto-{tipo}-{item.titulo}-{item.ordem}.json"


def salvar_bruto(pasta: Path, item, tipo: str, dados: dict) -> Path:
    Path(pasta).mkdir(parents=True, exist_ok=True)
    p = _bruto(pasta, item, tipo)
    p.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return p


def ler_bruto(pasta: Path, item, tipo: str) -> dict | None:
    p = _bruto(pasta, item, tipo)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
```

- [ ] **Step 4: rodar e ver passar**

Run: `python -m pytest tests/test_pagamento_api_comprovante.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add pagamento_api/comprovante.py tests/test_pagamento_api_comprovante.py
git commit -m "pagamento_api: comprovante em PDF com a descrição do HTML, sem dependência nova"
```

### Task 5: O que o robô faz com um lote aprovado (`executor.py`)

**Files:**
- Create: `pagamento_api/executor.py`
- Test: `tests/test_pagamento_api_executor.py`, `tests/test_pagamento_api_sorteio.py`

**Interfaces:**
- Consumes: `lote.ItemLote`, `lote.BOLETO/PIX_CHAVE/PIX_QR/CONVENIO` (Task 2); `sicoob.Sicoob`, `ContaApi`, `ErroSicoob`, `chave_de_idempotencia` (Task 3); `comprovante.gerar_pdf/salvar_bruto/ler_bruto` (Task 4).
- Produces: estados `INICIADO, EM_PROCESSAMENTO, REALIZADO, NAO_PAGO, FALTA_ANEXAR, CONCLUIDO` (os mesmos textos do check `lote_evento_estado` da Task 6); `Evento(ordem, estado, detalhe="", chave="")`; `Titulo(aberto, valor, tem_comprovante: bool|None)`; protocolos `Erp` (`titulo`, `anexar`, `baixar`) e `Livro` (`eventos`, `gravar`); `Portas(sicoob, erp, livro, contas, pasta, hoje, parar, novo_uuid)`; `Executor(itens, total_aprovado, portas).rodar()`; `ultimos(eventos)`, `estado_pix(resposta)`.

- [ ] **Step 1: escrever os testes** (dublês do Sicoob, do ERP e do livro; o sorteio reaproveita os dublês)

`tests/test_pagamento_api_executor.py`:

```python
# -*- coding: utf-8 -*-
"""O robô contra dublês: o Sicoob, o ERP e o livro são de mentira, e cada teste
diz o que o banco responde. Nenhuma rede."""
from datetime import date
from decimal import Decimal

import pytest

from pagamento_api import executor as ex
from pagamento_api import lote as lt
from pagamento_api.sicoob import ContaApi, ErroSicoob

CONTA = "OBRA X - SICOOB"
DOC = "11222333000181"
BARRAS = "34191153400001150501570000249243752417701000"   # 44 dígitos, do BANCARIO dos testes do lote


def _item(ordem, tipo, valor="100.00", doc=DOC, dados=None):
    dados = dados or {lt.PIX_CHAVE: "a@b.com", lt.PIX_QR: "000201...6304ABCD",
                      lt.BOLETO: BARRAS, lt.CONVENIO: "8" + "1" * 43}[tipo]
    return lt.ItemLote(ordem, f"T{ordem}", f"T{ordem}", CONTA, tipo, dados, Decimal(valor),
                       "FORNECEDOR A", doc, f"OBRA X NF {ordem}")


class Livro:
    def __init__(self):
        self.lista = []

    def eventos(self):
        return list(self.lista)

    def gravar(self, e):
        self.lista.append(e)


class Erp:
    def __init__(self, titulos):
        self.t = dict(titulos)
        self.anexos, self.baixas = [], []

    def titulo(self, tid):
        return self.t.get(tid)

    def anexar(self, tid, caminho):
        self.anexos.append((tid, caminho))
        return True

    def baixar(self, tid, valor, dia, conta):
        self.baixas.append((tid, valor))
        v = self.t[tid]
        self.t[tid] = ex.Titulo(False, v.valor, True)
        return True


class Sicoob:
    def __init__(self, **resp):
        self.resp = resp
        self.chamadas = []

    def _r(self, nome, *a):
        self.chamadas.append(nome)
        r = self.resp.get(nome)
        if isinstance(r, Exception):
            raise r
        return r(*a) if callable(r) else (r if r is not None else {})

    def pix_iniciar(self, chave):
        return self._r("pix_iniciar", chave)

    def pix_confirmar(self, e2e, valor, descricao):
        return self._r("pix_confirmar", e2e, valor, descricao)

    def pix_qrcode(self, qr, valor, doc):
        return self._r("pix_qrcode", qr, valor, doc)

    def pix_consultar(self, e2e):
        return self._r("pix_consultar", e2e)

    def boleto_consultar(self, codigo, conta):
        return self._r("boleto_consultar", codigo, conta)

    def boleto_pagar(self, *a):
        return self._r("boleto_pagar", *a)

    def boleto_comprovante(self, chave):
        return self._r("boleto_comprovante", chave)

    def convenio_consultar(self, codigo, dia):
        return self._r("convenio_consultar", codigo, dia)

    def convenio_pagar(self, *a):
        return self._r("convenio_pagar", *a)


def _aberto(valor="100.00"):
    return ex.Titulo(True, Decimal(valor), False)


def _rodar(itens, total, sicoob, erp, tmp_path, livro=None, parar=lambda: False):
    livro = livro or Livro()
    portas = ex.Portas(sicoob, erp, livro, {CONTA: ContaApi(4342, 1234569, 1)},
                       tmp_path, date(2026, 11, 27), parar, lambda: "uuid-fixo")
    ex.Executor(itens, Decimal(total), portas).rodar()
    return livro


def _estados(livro, ordem):
    return [e.estado for e in livro.lista if e.ordem == ordem]


PIX_OK = dict(pix_iniciar={"endToEndId": "E1", "proprietario": {"identificador": DOC}},
              pix_confirmar={"estado": "REALIZADO"},
              pix_consultar={"estado": "REALIZADO", "valor": 100.0})


def test_pix_por_chave_paga_anexa_e_conclui(tmp_path):
    erp = Erp({"T1": _aberto()})
    s = Sicoob(**PIX_OK)
    livro = _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, erp, tmp_path)
    assert _estados(livro, 1) == [ex.INICIADO, ex.REALIZADO, ex.CONCLUIDO]
    assert erp.baixas == [("T1", Decimal("100.00"))]
    assert erp.anexos[0][1].read_bytes().startswith(b"%PDF-1.4")


def test_chave_de_outra_pessoa_nao_confirma(tmp_path):
    s = Sicoob(pix_iniciar={"endToEndId": "E1", "proprietario": {"identificador": "99999999999"}})
    livro = _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, Erp({"T1": _aberto()}), tmp_path)
    assert _estados(livro, 1) == [ex.NAO_PAGO]
    assert livro.lista[-1].detalhe == "chave de outra pessoa"
    assert "pix_confirmar" not in s.chamadas


@pytest.mark.parametrize("titulo,motivo", [
    (None, "ERP não confirmou o título"),
    (ex.Titulo(True, Decimal("100.00"), None), "ERP não confirmou o título"),
    (ex.Titulo(False, Decimal("100.00"), False), "ERP mudou"),
    (ex.Titulo(True, Decimal("100.00"), True), "ERP mudou"),
    (ex.Titulo(True, Decimal("100.01"), False), "ERP mudou"),
])
def test_erp_mudou_nao_paga(tmp_path, titulo, motivo):
    s = Sicoob(**PIX_OK)
    livro = _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, Erp({"T1": titulo} if titulo else {}), tmp_path)
    assert livro.lista == [ex.Evento(1, ex.NAO_PAGO, motivo)]
    assert s.chamadas == []


def test_nunca_passa_do_total_aprovado(tmp_path):
    erp = Erp({"T1": _aberto(), "T2": _aberto()})
    livro = _rodar([_item(1, lt.PIX_CHAVE), _item(2, lt.PIX_CHAVE)], "150.00",
                   Sicoob(**PIX_OK), erp, tmp_path)
    assert _estados(livro, 1)[-1] == ex.CONCLUIDO
    assert livro.lista[-1] == ex.Evento(2, ex.NAO_PAGO, "passaria do total aprovado")


def test_queda_no_confirmar_retoma_pela_consulta_e_nao_paga_de_novo(tmp_path):
    erp = Erp({"T1": _aberto()})
    s = Sicoob(pix_iniciar=PIX_OK["pix_iniciar"], pix_confirmar=ErroSicoob(None, "timeout"),
               pix_consultar={"estado": "REALIZADO"})
    livro = _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, erp, tmp_path)
    assert s.chamadas.count("pix_confirmar") == 1
    assert _estados(livro, 1) == [ex.INICIADO, ex.REALIZADO, ex.CONCLUIDO]


def test_erro_500_no_confirmar_tambem_e_ambiguo(tmp_path):
    s = Sicoob(pix_iniciar=PIX_OK["pix_iniciar"], pix_confirmar=ErroSicoob(500, "erro"),
               pix_consultar={"estado": "NAO_REALIZADO"})
    livro = _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, Erp({"T1": _aberto()}), tmp_path)
    assert _estados(livro, 1) == [ex.INICIADO, ex.NAO_PAGO]
    assert "não realizado" in livro.lista[-1].detalhe


def test_retomada_de_rodada_anterior_nao_chama_o_pagamento(tmp_path):
    livro = Livro()
    livro.gravar(ex.Evento(1, ex.INICIADO, "", "E1"))
    s = Sicoob(pix_consultar={"estado": "EM_PROCESSAMENTO"})
    _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, Erp({"T1": _aberto()}), tmp_path, livro)
    assert s.chamadas == ["pix_consultar"]
    assert _estados(livro, 1)[-1] == ex.EM_PROCESSAMENTO


def test_em_processamento_nao_anexa(tmp_path):
    erp = Erp({"T1": _aberto()})
    s = Sicoob(pix_iniciar=PIX_OK["pix_iniciar"], pix_confirmar={"estado": "EM_PROCESSAMENTO"})
    _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, erp, tmp_path)
    assert erp.anexos == [] and erp.baixas == []


def test_pix_com_estado_acentuado_do_sandbox_e_nao_pago(tmp_path):
    s = Sicoob(pix_iniciar=PIX_OK["pix_iniciar"], pix_confirmar={"estado": "NÃO_REALIZADO"})
    livro = _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, Erp({"T1": _aberto()}), tmp_path)
    assert _estados(livro, 1)[-1] == ex.NAO_PAGO


def test_boleto_grava_a_chave_antes_de_pagar_e_busca_o_comprovante_por_ela(tmp_path):
    vistos = []

    def pagar(codigo, conta, consulta, valor, descricao, chave, dia):
        vistos.append([e.estado for e in livro.lista])
        return {}

    livro = Livro()
    s = Sicoob(boleto_consultar={"valorPagamento": 100.0, "numeroCpfCnpjBeneficiario": DOC,
                                 "identificadorConsulta": "h"},
               boleto_pagar=pagar,
               boleto_comprovante={"situacaoPagamento": "EFETIVADO"})
    erp = Erp({"T1": _aberto()})
    _rodar([_item(1, lt.BOLETO)], "100.00", s, erp, tmp_path, livro)
    assert vistos == [[ex.INICIADO]]
    assert livro.lista[0].chave == "4342-1234569-uuid-fixo"
    assert _estados(livro, 1) == [ex.INICIADO, ex.REALIZADO, ex.CONCLUIDO]


@pytest.mark.parametrize("consulta,motivo", [
    ({"valorPagamento": 105.3, "numeroCpfCnpjBeneficiario": DOC}, "boleto diferente: banco cobra 105.30"),
    ({"valorPagamento": 100.0, "numeroCpfCnpjBeneficiario": "99999999000199"},
     "boleto diferente: beneficiário não é o esperado"),
    ({"bloquearPagamento": True, "mensagemBloqueioPagamento": "vencido"}, "banco bloqueia: vencido"),
])
def test_boleto_diferente_nao_paga(tmp_path, consulta, motivo):
    s = Sicoob(boleto_consultar=consulta)
    livro = _rodar([_item(1, lt.BOLETO)], "100.00", s, Erp({"T1": _aberto()}), tmp_path)
    assert livro.lista == [ex.Evento(1, ex.NAO_PAGO, motivo)]
    assert "boleto_pagar" not in s.chamadas


def test_boleto_beneficiario_final_tambem_vale(tmp_path):
    s = Sicoob(boleto_consultar={"valorPagamento": 100.0, "numeroCpfCnpjBeneficiario": "1",
                                 "numeroCpfCnpjBeneficiarioFinal": DOC},
               boleto_comprovante={"situacaoPagamento": "EFETIVADO"})
    livro = _rodar([_item(1, lt.BOLETO)], "100.00", s, Erp({"T1": _aberto()}), tmp_path)
    assert _estados(livro, 1)[-1] == ex.CONCLUIDO


def test_convenio_guarda_o_comprovante_da_resposta(tmp_path):
    s = Sicoob(convenio_consultar={"valorTotal": 100.0},
               convenio_pagar={"comprovante": "QUJD", "arrecadacao": {"nsu": 1833, "valorPago": 100.0}})
    erp = Erp({"T1": _aberto()})
    livro = _rodar([_item(1, lt.CONVENIO)], "100.00", s, erp, tmp_path)
    assert _estados(livro, 1) == [ex.INICIADO, ex.REALIZADO, ex.CONCLUIDO]
    assert livro.lista[1].chave == "1833"


def test_falha_no_anexo_fica_falta_anexar_e_repete_so_o_anexo(tmp_path):
    erp = Erp({"T1": _aberto()})
    erp.anexar = lambda tid, c: False
    s = Sicoob(**PIX_OK)
    livro = _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, erp, tmp_path)
    assert _estados(livro, 1)[-1] == ex.FALTA_ANEXAR
    erp2 = Erp({"T1": _aberto()})
    _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, erp2, tmp_path, livro)
    assert s.chamadas.count("pix_confirmar") == 1
    assert _estados(livro, 1)[-1] == ex.CONCLUIDO


def test_parar_interrompe_antes_do_proximo_item(tmp_path):
    vezes = iter([False, True])
    erp = Erp({"T1": _aberto(), "T2": _aberto()})
    livro = _rodar([_item(1, lt.PIX_CHAVE), _item(2, lt.PIX_CHAVE)], "200.00",
                   Sicoob(**PIX_OK), erp, tmp_path, parar=lambda: next(vezes))
    assert _estados(livro, 2) == []


def test_conta_sem_cadastro_da_api_nao_paga(tmp_path):
    item = lt.ItemLote(1, "T1", "T1", "OUTRA - SICOOB", lt.PIX_CHAVE, "a@b.com",
                       Decimal("100.00"), "F", DOC, "D")
    livro = _rodar([item], "100.00", Sicoob(**PIX_OK), Erp({"T1": _aberto()}), tmp_path)
    assert livro.lista == [ex.Evento(1, ex.NAO_PAGO, "conta sem cadastro da API no servidor")]


def test_convenio_com_valor_diferente_nao_paga(tmp_path):
    s = Sicoob(convenio_consultar={"valorTotal": 117.5})
    livro = _rodar([_item(1, lt.CONVENIO)], "100.00", s, Erp({"T1": _aberto()}), tmp_path)
    assert livro.lista == [ex.Evento(1, ex.NAO_PAGO, "convênio diferente: banco cobra 117.50")]
    assert "convenio_pagar" not in s.chamadas
```

`tests/test_pagamento_api_sorteio.py`:

```python
# -*- coding: utf-8 -*-
"""500 lotes sorteados, com quedas e recusas aleatórias e várias rodadas do robô:
nada passa do total aprovado e nenhum item é pago duas vezes."""
import random
from decimal import Decimal

from pagamento_api import executor as ex
from pagamento_api import lote as lt
from pagamento_api.sicoob import ErroSicoob

from test_pagamento_api_executor import DOC, Erp, Livro, _aberto, _item, _rodar


class SicoobSorteado:
    """Pix por chave: o confirmar às vezes cai (sem resposta ou 500) DEPOIS de
    ter pago, às vezes antes. O banco lembra o que de fato pagou."""

    def __init__(self, rnd):
        self.rnd = rnd
        self.pagos: dict[str, int] = {}
        self.chamadas = []

    def pix_iniciar(self, chave):
        return {"endToEndId": f"E{self.rnd.random()}", "proprietario": {"identificador": DOC}}

    def pix_confirmar(self, e2e, valor, descricao):
        sorte = self.rnd.random()
        if sorte < 0.2:
            raise ErroSicoob(400, "recusado antes de pagar")
        self.pagos[e2e] = self.pagos.get(e2e, 0) + 1
        if sorte < 0.4:
            raise ErroSicoob(None if sorte < 0.3 else 500, "caiu depois de pagar")
        return {"estado": "REALIZADO"}

    def pix_consultar(self, e2e):
        return {"estado": "REALIZADO" if e2e in self.pagos else "NAO_REALIZADO"}


def test_sorteio_total_e_dobra(tmp_path):
    rnd = random.Random(20261126)
    for rodada in range(500):
        n = rnd.randint(1, 6)
        itens = [_item(i, lt.PIX_CHAVE, valor=f"{rnd.randint(1, 50000) / 100:.2f}") for i in range(1, n + 1)]
        soma = sum(i.valor for i in itens)
        total = (soma * Decimal(rnd.choice(["0.3", "0.7", "1"]))).quantize(Decimal("0.01"))
        s = SicoobSorteado(rnd)
        livro = Livro()
        erp = Erp({i.titulo: _aberto(str(i.valor)) for i in itens})
        for _ in range(3):              # o robô roda de novo depois de cada queda
            _rodar(itens, total, s, erp, tmp_path / str(rodada), livro)
        assert all(v == 1 for v in s.pagos.values()), f"rodada {rodada}: pago em dobro"
        u = ex.ultimos(livro.lista)
        pagos = [i for i in itens if u[i.ordem].estado in (ex.REALIZADO, ex.FALTA_ANEXAR, ex.CONCLUIDO)]
        assert sum((i.valor for i in pagos), Decimal("0")) <= total, f"rodada {rodada}: passou do total"
        assert len(s.pagos) == len(pagos), f"rodada {rodada}: banco e livro discordam"
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/test_pagamento_api_executor.py tests/test_pagamento_api_sorteio.py -q`
Expected: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: implementar**

`pagamento_api/executor.py`:

```python
# -*- coding: utf-8 -*-
"""O que o robô faz com um lote APROVADO: paga item a item, retoma depois de
queda sem pagar duas vezes, e anexa + dá baixa só com o pagamento REALIZADO.

Sem rede própria: o Sicoob, o ERP e o livro (a nuvem) entram como portas, e o
teste passa dublês. Regras da spec de 26/11/2026:
- pagar NUNCA se repete sozinho; buscar comprovante e anexar podem;
- a soma do que saiu nunca passa do total aprovado;
- antes de pagar, o ERP é relido (em aberto, mesmo valor, sem comprovante);
- toda chave de pagamento é gravada no livro ANTES da chamada que paga.
"""
from __future__ import annotations

import unicodedata
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Callable, Protocol

from . import comprovante as cp
from . import lote as lt
from .sicoob import ContaApi, ErroSicoob, Sicoob, chave_de_idempotencia

INICIADO, EM_PROCESSAMENTO, REALIZADO = "iniciado", "em_processamento", "realizado"
NAO_PAGO, FALTA_ANEXAR, CONCLUIDO = "nao_pago", "falta_anexar", "concluido"
#: Estados em que o dinheiro saiu ou pode ter saído: contam no total.
SAIU_OU_PODE_TER_SAIDO = (INICIADO, EM_PROCESSAMENTO, REALIZADO, FALTA_ANEXAR, CONCLUIDO)
FINAIS = (NAO_PAGO, CONCLUIDO)


@dataclass(frozen=True)
class Evento:
    ordem: int
    estado: str
    detalhe: str = ""
    chave: str = ""          # chave de idempotência (boleto) ou endToEndId (Pix)


@dataclass(frozen=True)
class Titulo:
    aberto: bool
    valor: Decimal
    tem_comprovante: bool | None   # None = o ERP não respondeu: nunca vale como "não tem"


class Erp(Protocol):
    def titulo(self, titulo_id: str) -> Titulo | None: ...
    def anexar(self, titulo_id: str, caminho: Path) -> bool: ...
    def baixar(self, titulo_id: str, valor: Decimal, dia: date, conta: str) -> bool: ...


class Livro(Protocol):
    def eventos(self) -> list[Evento]: ...
    def gravar(self, evento: Evento) -> None: ...


@dataclass
class Portas:
    sicoob: Sicoob
    erp: Erp
    livro: Livro
    contas: dict[str, ContaApi]         # nome da conta no ERP -> conta no Sicoob
    pasta: Path                         # onde os PDFs dos comprovantes ficam
    hoje: date
    parar: Callable[[], bool] = lambda: False
    novo_uuid: Callable[[], str] = field(default=lambda: str(_uuid.uuid4()))


def _sem_acento(t) -> str:
    return unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().upper()


def estado_pix(resposta: dict) -> str:
    e = _sem_acento(resposta.get("estado"))
    if e == "REALIZADO":
        return REALIZADO
    if e == "EM_PROCESSAMENTO":
        return EM_PROCESSAMENTO
    return NAO_PAGO


def ultimos(eventos: list[Evento]) -> dict[int, Evento]:
    u: dict[int, Evento] = {}
    for e in eventos:
        u[e.ordem] = e
    return u


def chave_do_item(eventos: list[Evento], ordem: int) -> str:
    for e in eventos:
        if e.ordem == ordem and e.chave:
            return e.chave
    return ""


def ja_comprometido(itens: list[lt.ItemLote], eventos: list[Evento]) -> Decimal:
    u = ultimos(eventos)
    return sum((i.valor for i in itens
                if i.ordem in u and u[i.ordem].estado in SAIU_OU_PODE_TER_SAIDO),
               Decimal("0.00"))


class Executor:
    def __init__(self, itens: list[lt.ItemLote], total_aprovado: Decimal, portas: Portas):
        self.itens = sorted(itens, key=lambda i: i.ordem)
        self.total = Decimal(total_aprovado)
        self.p = portas

    def _gravar(self, item, estado, detalhe="", chave=""):
        ev = Evento(item.ordem, estado, detalhe[:500], chave)
        self.p.livro.gravar(ev)
        return ev

    # ------------------------------------------------------------ o ciclo
    def rodar(self) -> None:
        for item in self.itens:
            if self.p.parar():
                return
            eventos = self.p.livro.eventos()
            ult = ultimos(eventos).get(item.ordem)
            if ult and ult.estado in FINAIS:
                continue
            if ult and ult.estado in (INICIADO, EM_PROCESSAMENTO):
                ult = self._retomar(item, chave_do_item(eventos, item.ordem))
            elif ult is None:
                ult = self._pagar(item, eventos)
            if ult.estado in (REALIZADO, FALTA_ANEXAR):
                self._anexar(item, chave_do_item(self.p.livro.eventos(), item.ordem))

    # ------------------------------------------------------------- pagar
    def _pagar(self, item: lt.ItemLote, eventos: list[Evento]) -> Evento:
        if ja_comprometido(self.itens, eventos) + item.valor > self.total:
            return self._gravar(item, NAO_PAGO, "passaria do total aprovado")
        conta = self.p.contas.get(item.conta)
        if conta is None:
            return self._gravar(item, NAO_PAGO, "conta sem cadastro da API no servidor")
        t = self.p.erp.titulo(item.titulo)
        if t is None or t.tem_comprovante is None:
            return self._gravar(item, NAO_PAGO, "ERP não confirmou o título")
        if not t.aberto or t.tem_comprovante or Decimal(t.valor) != item.valor:
            return self._gravar(item, NAO_PAGO, "ERP mudou")
        try:
            if item.tipo == lt.PIX_CHAVE:
                return self._pix_chave(item)
            if item.tipo == lt.PIX_QR:
                return self._pix_qr(item)
            if item.tipo == lt.BOLETO:
                return self._boleto(item, conta)
            if item.tipo == lt.CONVENIO:
                return self._convenio(item, conta)
        except ErroSicoob as e:
            # Erro DEPOIS de gravar INICIADO (no passo que paga) é ambíguo:
            # o dinheiro pode ter saído, com ou sem resposta. Quem decide é a
            # retomada, que pergunta ao banco. Erro antes disso = não pago.
            ult = ultimos(self.p.livro.eventos()).get(item.ordem)
            if ult and ult.estado == INICIADO:
                return self._retomar(item, ult.chave)
            return self._gravar(item, NAO_PAGO, f"banco: {e}")
        return self._gravar(item, NAO_PAGO, f"tipo {item.tipo} desconhecido")

    def _pix_chave(self, item):
        ini = self.p.sicoob.pix_iniciar(item.dados)
        e2e = str(ini.get("endToEndId") or "")
        doc = "".join(ch for ch in str((ini.get("proprietario") or {}).get("identificador") or "")
                      if ch.isdigit())
        if not e2e:
            return self._gravar(item, NAO_PAGO, "banco não devolveu o endToEndId")
        if doc != item.documento_esperado:
            return self._gravar(item, NAO_PAGO, "chave de outra pessoa", e2e)
        self._gravar(item, INICIADO, "", e2e)
        r = self.p.sicoob.pix_confirmar(e2e, item.valor, item.descricao)
        return self._gravar(item, estado_pix(r), str(r.get("detalheRejeicao") or ""), e2e)

    def _pix_qr(self, item):
        self._gravar(item, INICIADO, "qrcode")
        r = self.p.sicoob.pix_qrcode(item.dados, item.valor, item.documento_esperado)
        return self._gravar(item, estado_pix(r), str(r.get("detalheRejeicao") or ""),
                            str(r.get("endToEndId") or ""))

    def _boleto(self, item, conta):
        c = self.p.sicoob.boleto_consultar(item.dados, conta)
        if c.get("bloquearPagamento"):
            return self._gravar(item, NAO_PAGO, f"banco bloqueia: {c.get('mensagemBloqueioPagamento') or ''}")
        valor = Decimal(str(c.get("valorPagamento") if c.get("valorPagamento") is not None
                            else c.get("valorBoleto") or "0")).quantize(Decimal("0.01"))
        if valor != item.valor:
            return self._gravar(item, NAO_PAGO, f"boleto diferente: banco cobra {valor}")
        docs = {"".join(ch for ch in str(c.get(k) or "") if ch.isdigit())
                for k in ("numeroCpfCnpjBeneficiario", "numeroCpfCnpjBeneficiarioFinal")}
        if item.documento_esperado and item.documento_esperado not in docs:
            return self._gravar(item, NAO_PAGO, "boleto diferente: beneficiário não é o esperado")
        chave = chave_de_idempotencia(conta, self.p.novo_uuid())
        self._gravar(item, INICIADO, "", chave)
        self.p.sicoob.boleto_pagar(item.dados, conta, c, item.valor, item.descricao,
                                   chave, self.p.hoje.isoformat())
        return self._gravar(item, REALIZADO, "", chave)

    def _convenio(self, item, conta):
        c = self.p.sicoob.convenio_consultar(item.dados, self.p.hoje.isoformat())
        cobra = Decimal(str(c.get("valorTotal") if c.get("valorTotal") is not None
                            else "0")).quantize(Decimal("0.01"))
        if cobra != item.valor:
            return self._gravar(item, NAO_PAGO, f"convênio diferente: banco cobra {cobra}")
        self._gravar(item, INICIADO, "convenio")
        r = self.p.sicoob.convenio_pagar(item.dados, conta, item.valor,
                                         self.p.hoje.isoformat(), item.ordem)
        arr = r.get("arrecadacao") or {}
        nsu = str(arr.get("nsu") or "")
        caminho = cp.salvar_bruto(self.p.pasta, item, "convenio", r)
        return self._gravar(item, REALIZADO, str(caminho), nsu)

    # ----------------------------------------------------------- retomar
    def _retomar(self, item, chave) -> Evento:
        """Caiu no meio: pergunta ao banco pelo código gravado. Nunca paga de novo."""
        try:
            if item.tipo == lt.PIX_CHAVE and chave:
                r = self.p.sicoob.pix_consultar(chave)
                est = estado_pix(r)
                if est == NAO_PAGO:
                    return self._gravar(item, NAO_PAGO, "interrompido; o banco diz não realizado", chave)
                return self._gravar(item, est, "", chave)
            if item.tipo == lt.BOLETO and chave:
                r = self.p.sicoob.boleto_comprovante(chave)
                if r:
                    return self._gravar(item, REALIZADO, "", chave)
        except ErroSicoob:
            pass
        return self._gravar(item, NAO_PAGO, "interrompido — conferir no banco antes de pagar de novo", chave)

    # ----------------------------------------------------------- anexar
    def _anexar(self, item, chave) -> Evento:
        try:
            dados = self._comprovante(item, chave)
        except ErroSicoob as e:
            return self._gravar(item, FALTA_ANEXAR, f"comprovante: {e}", chave)
        if dados is None:
            return self._gravar(item, FALTA_ANEXAR, "comprovante ainda não disponível", chave)
        caminho = cp.gerar_pdf(self.p.pasta, item, dados, self.p.hoje)
        if not self.p.erp.anexar(item.titulo, caminho):
            return self._gravar(item, FALTA_ANEXAR, "ERP recusou o anexo", chave)
        if not self.p.erp.baixar(item.titulo, item.valor, self.p.hoje, item.conta):
            return self._gravar(item, FALTA_ANEXAR, "ERP recusou a baixa", chave)
        t = self.p.erp.titulo(item.titulo)
        if t is None or t.aberto or t.tem_comprovante is not True:
            return self._gravar(item, FALTA_ANEXAR, "ERP não confirmou anexo e baixa", chave)
        return self._gravar(item, CONCLUIDO, str(caminho), chave)

    def _comprovante(self, item, chave) -> dict | None:
        if item.tipo == lt.BOLETO:
            return self.p.sicoob.boleto_comprovante(chave) or None
        if item.tipo in (lt.PIX_CHAVE, lt.PIX_QR):
            if not chave:
                return None
            r = self.p.sicoob.pix_consultar(chave)
            return r if estado_pix(r) == REALIZADO else None
        if item.tipo == lt.CONVENIO:
            return cp.ler_bruto(self.p.pasta, item, "convenio")
        return None
```

- [ ] **Step 4: rodar e ver passar**

Run: `python -m pytest tests/test_pagamento_api_executor.py tests/test_pagamento_api_sorteio.py -q`
Expected: 24 passed.

- [ ] **Step 5: Commit**

```bash
git add pagamento_api/executor.py tests/test_pagamento_api_executor.py tests/test_pagamento_api_sorteio.py
git commit -m "pagamento_api: executor — paga item a item, retoma sem pagar em dobro, anexa só com REALIZADO"
```

### Task 6: Tabelas e regras na nuvem (migration)

**Files:**
- Create: `supabase/migrations/20261126100000_pagamento_pela_api.sql`
- Create (raiz da pasta de trabalho, fora do repo): `APLICAR NO SUPABASE - 2026-11-26 pagamento pela API.sql` (cópia idêntica)
- Test: `tests/test_pagamento_api_sql.py`

**Interfaces:**
- Consumes: `public.perfil` (constraint `perfil_papel_conhecido`), `privado.e_ativo()`, `privado.e_admin()`, `privado.carimbar_quem_nome()` (conferidos nas migrations de 30/08 e 22/10).
- Produces: tabelas `lote_pagamento`, `lote_item`, `lote_cancelado`, `lote_aprovacao`, `lote_evento`, `robo_pulso`, `robo_parar`; papel `robo`; `privado.tem_papel(text)`, `privado.hoje()`; índice `lote_evento_um_iniciado`. Colunas lidas pela Task 7: `lote_pagamento.id/dia`, `lote_aprovacao.lote/itens/total`, `lote_item.*`, `lote_evento.ordem/estado/detalhe/chave`, `robo_parar.acao`.

- [ ] **Step 1: escrever o teste**

`tests/test_pagamento_api_sql.py`:

```python
# -*- coding: utf-8 -*-
"""A estrutura do pagamento pela API, lida da migration (sem Postgres — o mesmo
jeito de `test_pagamentos_do_dia_sql.py`). Quem prova o COMPORTAMENTO é o
roteiro de prova no banco (begin; ...; rollback;), rodado depois de aplicar."""
import re
from pathlib import Path

_SQL = (Path(__file__).resolve().parent.parent / "supabase" / "migrations"
        / "20261126100000_pagamento_pela_api.sql")
TABELAS = ("lote_pagamento", "lote_item", "lote_cancelado", "lote_aprovacao",
           "lote_evento", "robo_pulso", "robo_parar")


def _texto() -> str:
    sql = re.sub(r"--[^\n]*", " ", _SQL.read_text(encoding="utf-8"))
    return " ".join(sql.split()).lower()


def test_cria_as_tabelas_com_rls():
    t = _texto()
    for nome in TABELAS:
        assert f"create table if not exists public.{nome} (" in t
        assert f"alter table public.{nome} enable row level security" in t
        assert f"create policy {nome}_le on public.{nome} for select to authenticated" in t
        assert f"create policy {nome}_grava on public.{nome} for insert to authenticated" in t


def test_ninguem_altera_nem_apaga():
    t = _texto()
    assert "grant select, insert on table public.lote_pagamento, public.lote_item" in t
    assert not re.search(r"grant[^;]*\b(update|delete|truncate)\b[^;]*to authenticated", t)
    assert "for update" not in t and "for delete" not in t


def test_cada_papel_so_no_que_e_dele():
    t = _texto()
    assert ("create policy lote_aprovacao_grava on public.lote_aprovacao for insert to authenticated "
            "with check ( (select privado.e_ativo()) and (select privado.tem_papel('aprovador')) "
            "and aprovado_por = (select auth.uid()))") in t
    for nome in ("lote_evento", "robo_pulso"):
        assert (f"create policy {nome}_grava on public.{nome} for insert to authenticated with check ( "
                "(select privado.e_ativo()) and (select privado.tem_papel('robo')) "
                "and quem = (select auth.uid()))") in t
    assert "check (papel in ('admin', 'operador', 'aprovador', 'robo'))" in t


def test_as_regras_de_dinheiro_estao_no_banco():
    t = _texto()
    assert "quem preparou o lote não aprova" in t
    assert "aprovação vale só no dia do lote" in t
    assert "total aprovado % não é a soma dos itens %" in t
    assert "já está em outro lote de hoje" in t
    assert "lote já aprovado ou cancelado" in t
    assert "constraint lote_item_titulo_no_lote unique (lote, titulo)" in t
    assert "item % do lote % não está aprovado" in t and "robô parado pelo botão" in t
    assert t.count("for no key update") == 3
    assert "pg_advisory_xact_lock(hashtextextended('lote_item:' || new.titulo, 0))" in t
    for gatilho in ("lote_pagamento_confere", "lote_item_confere", "lote_aprovacao_confere",
                    "lote_cancelado_confere", "lote_evento_confere"):
        assert f"create trigger {gatilho} before insert" in t


def test_funcao_security_definer_tem_search_path_vazio():
    t = _texto()
    for m in re.finditer(r"create or replace function (privado\.\w+)\([^)]*\)(.*?)\$\$", t):
        if "security definer" in m.group(2):
            assert "set search_path = ''" in m.group(2), m.group(1)


def test_um_iniciado_por_item_no_banco():
    assert ("create unique index if not exists lote_evento_um_iniciado on public.lote_evento "
            "(lote, ordem) where estado = 'iniciado'") in _texto()
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/test_pagamento_api_sql.py -q`
Expected: FAIL com `FileNotFoundError` da migration.

- [ ] **Step 3: escrever a migration**

`supabase/migrations/20261126100000_pagamento_pela_api.sql`:

```sql
-- ---------------------------------------------- pagamento pela API do Sicoob
-- Spec de 26/11/2026. O app monta o LOTE do dia, um aprovador aprova (pelo
-- portal), o robô do servidor paga e anota cada passo. Tudo só ACRESCENTA:
-- ninguém altera nem apaga linha (sem grant de update/delete). As regras de
-- dinheiro moram AQUI, no banco, e não na tela: a tela do portal é pública e
-- qualquer um pode chamar a API com o próprio login.
--
--   lote_pagamento / lote_item  -> o app (papel admin|operador) cria; itens só
--                                  entram enquanto o lote não foi aprovado nem
--                                  cancelado, e só por quem o preparou.
--   lote_aprovacao              -> papel aprovador; nunca quem preparou; só no
--                                  dia; soma conferida pelo banco.
--   lote_cancelado              -> quem preparou, antes da aprovação.
--   lote_evento / robo_pulso    -> papel robo (o usuário do servidor).
--   robo_parar                  -> parar: qualquer conta ativa; retomar: aprovador ou admin.
--
-- Idempotente. Tudo numa transação.

begin;
-- O alter do perfil trava a tabela que toda política lê: não esperar mais que isso.
set local lock_timeout = '5s';

-- ----------------------------------------------------------- papel do robô
alter table public.perfil drop constraint if exists perfil_papel_conhecido;
alter table public.perfil add constraint perfil_papel_conhecido
  check (papel in ('admin', 'operador', 'aprovador', 'robo'));

create or replace function privado.tem_papel(p text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.perfil
    where user_id = (select auth.uid()) and situacao = 'ativo' and papel = p
  );
$$;
revoke execute on function privado.tem_papel(text) from public, anon;
grant execute on function privado.tem_papel(text) to authenticated;

create or replace function privado.hoje()
returns date
language sql
stable
set search_path = ''
as $$ select (now() at time zone 'America/Sao_Paulo')::date $$;
revoke execute on function privado.hoje() from public, anon;
grant execute on function privado.hoje() to authenticated;

-- ------------------------------------------------------------------ tabelas
create table if not exists public.lote_pagamento (
  id             bigint generated always as identity primary key,
  dia            date not null,
  total          numeric(14,2) not null,
  preparado_por  uuid not null default auth.uid() references auth.users (id),
  quem_nome      text not null default '',
  quando         timestamptz not null default now(),
  constraint lote_pagamento_total check (total > 0)
);

create table if not exists public.lote_item (
  id                 bigint generated always as identity primary key,
  lote               bigint not null references public.lote_pagamento (id),
  ordem              integer not null,
  titulo             text not null,
  alvo               text not null,
  conta              text not null,
  tipo               text not null,
  dados              text not null,
  valor              numeric(14,2) not null,
  favorecido         text not null default '',
  documento_esperado text not null default '',
  descricao          text not null default '',
  constraint lote_item_ordem unique (lote, ordem),
  constraint lote_item_titulo_no_lote unique (lote, titulo),
  constraint lote_item_ordem_positiva check (ordem > 0),
  constraint lote_item_tipo check (tipo in ('boleto', 'pix_chave', 'pix_qr', 'convenio')),
  constraint lote_item_valor check (valor > 0),
  constraint lote_item_documento check (documento_esperado ~ '^([0-9]{11}|[0-9]{14})?$'),
  constraint lote_item_tamanho check (length(titulo) between 1 and 100 and length(alvo) <= 200
    and length(conta) <= 200 and length(dados) between 1 and 600
    and length(favorecido) <= 200 and length(descricao) <= 100)
);
create index if not exists lote_item_titulo_idx on public.lote_item (titulo);

create table if not exists public.lote_cancelado (
  lote       bigint primary key references public.lote_pagamento (id),
  motivo     text not null,
  quem       uuid not null default auth.uid() references auth.users (id),
  quando     timestamptz not null default now(),
  constraint lote_cancelado_motivo check (length(trim(motivo)) between 3 and 200)
);

create table if not exists public.lote_aprovacao (
  id             bigint generated always as identity primary key,
  lote           bigint not null unique references public.lote_pagamento (id),
  itens          integer[] not null,
  retirados      jsonb not null default '[]'::jsonb,
  total          numeric(14,2) not null,
  aprovado_por   uuid not null default auth.uid() references auth.users (id),
  quem_nome      text not null default '',
  quando         timestamptz not null default now(),
  constraint lote_aprovacao_retirados check (jsonb_typeof(retirados) = 'array'
    and pg_column_size(retirados) <= 16384)
);

create table if not exists public.lote_evento (
  id       bigint generated always as identity primary key,
  lote     bigint not null references public.lote_pagamento (id),
  ordem    integer not null,
  estado   text not null,
  detalhe  text not null default '',
  chave    text not null default '',
  quem     uuid not null default auth.uid() references auth.users (id),
  quando   timestamptz not null default now(),
  constraint lote_evento_estado check (estado in
    ('iniciado', 'em_processamento', 'realizado', 'nao_pago', 'falta_anexar', 'concluido')),
  constraint lote_evento_tamanho check (length(detalhe) <= 500 and length(chave) <= 200)
);
create index if not exists lote_evento_lote_idx on public.lote_evento (lote, id);
-- A trava contra pagar duas vezes que vale até para duas máquinas ao mesmo
-- tempo: o robô grava INICIADO ANTES de pagar, e o segundo INICIADO do mesmo
-- item é recusado aqui (o robô para sem pagar).
create unique index if not exists lote_evento_um_iniciado
  on public.lote_evento (lote, ordem) where estado = 'iniciado';

create table if not exists public.robo_pulso (
  id      bigint generated always as identity primary key,
  quem    uuid not null default auth.uid() references auth.users (id),
  quando  timestamptz not null default now()
);
create index if not exists robo_pulso_quando_idx on public.robo_pulso (quando desc);

create table if not exists public.robo_parar (
  id         bigint generated always as identity primary key,
  acao       text not null,
  motivo     text not null default '',
  quem       uuid not null default auth.uid() references auth.users (id),
  quem_nome  text not null default '',
  quando     timestamptz not null default now(),
  constraint robo_parar_acao check (acao in ('parar', 'retomar')),
  constraint robo_parar_motivo check (length(motivo) <= 200)
);

-- ------------------------------------------------- as regras, no banco
create or replace function privado.conferir_lote()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.dia <> privado.hoje() then
    raise exception 'lote só para hoje (%), não para %', privado.hoje(), new.dia;
  end if;
  return new;
end;
$$;
revoke execute on function privado.conferir_lote() from public, anon, authenticated;

create or replace function privado.conferir_item()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  l public.lote_pagamento%rowtype;
begin
  -- Trava a linha do lote: item, aprovação e cancelamento do MESMO lote passam
  -- um de cada vez, e cada um enxerga o que o outro gravou (revisão de SQL, 26/11).
  perform 1 from public.lote_pagamento where id = new.lote for no key update;
  select * into l from public.lote_pagamento where id = new.lote;
  if l.preparado_por is distinct from (select auth.uid()) then
    raise exception 'só quem preparou o lote acrescenta itens';
  end if;
  if exists (select 1 from public.lote_aprovacao a where a.lote = new.lote)
     or exists (select 1 from public.lote_cancelado c where c.lote = new.lote) then
    raise exception 'lote já aprovado ou cancelado';
  end if;
  -- Dois lotes ao mesmo tempo com o mesmo título: um de cada vez.
  perform pg_advisory_xact_lock(hashtextextended('lote_item:' || new.titulo, 0));
  -- O título bloqueia enquanto estiver num lote não cancelado, sem ter sido
  -- retirado na aprovação e sem ter terminado em nao_pago: de hoje, ou de
  -- qualquer dia quando aquele lote foi aprovado (pode ter sido pago).
  if exists (
    select 1 from public.lote_item i
    join public.lote_pagamento p on p.id = i.lote
    left join public.lote_aprovacao a on a.lote = i.lote
    where i.titulo = new.titulo and i.lote <> new.lote
      and not exists (select 1 from public.lote_cancelado c where c.lote = i.lote)
      and (a.lote is null or i.ordem = any (a.itens))
      and coalesce((select e.estado from public.lote_evento e
                    where e.lote = i.lote and e.ordem = i.ordem
                    order by e.id desc limit 1), '') <> 'nao_pago'
      and (p.dia = l.dia or a.lote is not null)
  ) then
    raise exception 'título % já está em outro lote de hoje', new.titulo;
  end if;
  return new;
end;
$$;
revoke execute on function privado.conferir_item() from public, anon, authenticated;

create or replace function privado.conferir_aprovacao()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  l          public.lote_pagamento%rowtype;
  todas      integer[];
  fora       integer[];
  soma_tudo  numeric(14,2);
  soma_itens numeric(14,2);
begin
  perform 1 from public.lote_pagamento where id = new.lote for no key update;
  select * into l from public.lote_pagamento where id = new.lote;
  if l.id is null then
    raise exception 'lote inexistente';
  end if;
  if l.dia <> privado.hoje() then
    raise exception 'aprovação vale só no dia do lote';
  end if;
  if l.preparado_por = (select auth.uid()) then
    raise exception 'quem preparou o lote não aprova';
  end if;
  if exists (select 1 from public.lote_cancelado c where c.lote = new.lote) then
    raise exception 'lote cancelado';
  end if;
  select array_agg(ordem order by ordem), coalesce(sum(valor), 0)
    into todas, soma_tudo from public.lote_item where lote = new.lote;
  if soma_tudo <> l.total then
    raise exception 'lote incompleto: itens somam % e o lote diz %', soma_tudo, l.total;
  end if;
  if coalesce(array_length(new.itens, 1), 0) = 0 then
    raise exception 'aprovação sem itens';
  end if;
  if (select count(distinct x) from unnest(new.itens) x) <> array_length(new.itens, 1)
     or not (new.itens <@ todas) then
    raise exception 'itens aprovados não conferem com o lote';
  end if;
  select coalesce(array_agg((r ->> 'ordem')::integer order by (r ->> 'ordem')::integer), '{}')
    into fora from jsonb_array_elements(new.retirados) r;
  if exists (select 1 from jsonb_array_elements(new.retirados) r
             where length(trim(coalesce(r ->> 'motivo', ''))) < 3) then
    raise exception 'item retirado sem motivo';
  end if;
  if (select array_agg(x order by x) from unnest(new.itens || fora) x) is distinct from todas then
    raise exception 'todo item do lote tem de estar aprovado ou retirado, uma vez só';
  end if;
  select coalesce(sum(valor), 0) into soma_itens
    from public.lote_item where lote = new.lote and ordem = any (new.itens);
  if new.total <> soma_itens then
    raise exception 'total aprovado % não é a soma dos itens %', new.total, soma_itens;
  end if;
  return new;
end;
$$;
revoke execute on function privado.conferir_aprovacao() from public, anon, authenticated;

create or replace function privado.conferir_cancelamento()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  perform 1 from public.lote_pagamento where id = new.lote for no key update;
  if (select preparado_por from public.lote_pagamento where id = new.lote)
       is distinct from (select auth.uid()) then
    raise exception 'só quem preparou cancela';
  end if;
  if exists (select 1 from public.lote_aprovacao a where a.lote = new.lote) then
    raise exception 'lote aprovado não se cancela: use Parar pagamentos';
  end if;
  return new;
end;
$$;
revoke execute on function privado.conferir_cancelamento() from public, anon, authenticated;

-- O banco amarra o robô: INICIADO (o passo antes de pagar) só para item
-- aprovado, de lote de hoje, com o robô ligado.
create or replace function privado.conferir_evento()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.estado = 'iniciado' then
    if not exists (select 1 from public.lote_aprovacao a
                   where a.lote = new.lote and new.ordem = any (a.itens)) then
      raise exception 'item % do lote % não está aprovado', new.ordem, new.lote;
    end if;
    if (select dia from public.lote_pagamento where id = new.lote) <> privado.hoje() then
      raise exception 'lote não é de hoje';
    end if;
    if coalesce((select acao from public.robo_parar order by id desc limit 1), '') = 'parar' then
      raise exception 'robô parado pelo botão';
    end if;
  end if;
  return new;
end;
$$;
revoke execute on function privado.conferir_evento() from public, anon, authenticated;

drop trigger if exists lote_evento_confere on public.lote_evento;
create trigger lote_evento_confere before insert on public.lote_evento
  for each row execute function privado.conferir_evento();
drop trigger if exists lote_pagamento_confere on public.lote_pagamento;
create trigger lote_pagamento_confere before insert on public.lote_pagamento
  for each row execute function privado.conferir_lote();
drop trigger if exists lote_item_confere on public.lote_item;
create trigger lote_item_confere before insert on public.lote_item
  for each row execute function privado.conferir_item();
drop trigger if exists lote_aprovacao_confere on public.lote_aprovacao;
create trigger lote_aprovacao_confere before insert on public.lote_aprovacao
  for each row execute function privado.conferir_aprovacao();
drop trigger if exists lote_cancelado_confere on public.lote_cancelado;
create trigger lote_cancelado_confere before insert on public.lote_cancelado
  for each row execute function privado.conferir_cancelamento();

drop trigger if exists lote_pagamento_quem_nome on public.lote_pagamento;
create trigger lote_pagamento_quem_nome before insert on public.lote_pagamento
  for each row execute function privado.carimbar_quem_nome();
drop trigger if exists lote_aprovacao_quem_nome on public.lote_aprovacao;
create trigger lote_aprovacao_quem_nome before insert on public.lote_aprovacao
  for each row execute function privado.carimbar_quem_nome();
drop trigger if exists robo_parar_quem_nome on public.robo_parar;
create trigger robo_parar_quem_nome before insert on public.robo_parar
  for each row execute function privado.carimbar_quem_nome();

-- ------------------------------------------------------- permissões e RLS
revoke all on table public.lote_pagamento, public.lote_item, public.lote_cancelado,
  public.lote_aprovacao, public.lote_evento, public.robo_pulso, public.robo_parar
  from anon, authenticated;
grant select, insert on table public.lote_pagamento, public.lote_item, public.lote_cancelado,
  public.lote_aprovacao, public.lote_evento, public.robo_pulso, public.robo_parar
  to authenticated;

alter table public.lote_pagamento enable row level security;
alter table public.lote_item      enable row level security;
alter table public.lote_cancelado enable row level security;
alter table public.lote_aprovacao enable row level security;
alter table public.lote_evento    enable row level security;
alter table public.robo_pulso     enable row level security;
alter table public.robo_parar     enable row level security;

drop policy if exists lote_pagamento_le on public.lote_pagamento;
create policy lote_pagamento_le on public.lote_pagamento for select to authenticated using ((select privado.e_ativo()));
drop policy if exists lote_pagamento_grava on public.lote_pagamento;
create policy lote_pagamento_grava on public.lote_pagamento for insert to authenticated with check (
  (select privado.e_ativo())
  and ((select privado.tem_papel('operador')) or (select privado.tem_papel('admin')))
  and preparado_por = (select auth.uid()));

drop policy if exists lote_item_le on public.lote_item;
create policy lote_item_le on public.lote_item for select to authenticated using ((select privado.e_ativo()));
drop policy if exists lote_item_grava on public.lote_item;
create policy lote_item_grava on public.lote_item for insert to authenticated with check (
  (select privado.e_ativo())
  and ((select privado.tem_papel('operador')) or (select privado.tem_papel('admin'))));

drop policy if exists lote_cancelado_le on public.lote_cancelado;
create policy lote_cancelado_le on public.lote_cancelado for select to authenticated using ((select privado.e_ativo()));
drop policy if exists lote_cancelado_grava on public.lote_cancelado;
create policy lote_cancelado_grava on public.lote_cancelado for insert to authenticated with check (
  (select privado.e_ativo()) and quem = (select auth.uid()));

drop policy if exists lote_aprovacao_le on public.lote_aprovacao;
create policy lote_aprovacao_le on public.lote_aprovacao for select to authenticated using ((select privado.e_ativo()));
drop policy if exists lote_aprovacao_grava on public.lote_aprovacao;
create policy lote_aprovacao_grava on public.lote_aprovacao for insert to authenticated with check (
  (select privado.e_ativo()) and (select privado.tem_papel('aprovador'))
  and aprovado_por = (select auth.uid()));

drop policy if exists lote_evento_le on public.lote_evento;
create policy lote_evento_le on public.lote_evento for select to authenticated using ((select privado.e_ativo()));
drop policy if exists lote_evento_grava on public.lote_evento;
create policy lote_evento_grava on public.lote_evento for insert to authenticated with check (
  (select privado.e_ativo()) and (select privado.tem_papel('robo'))
  and quem = (select auth.uid()));

drop policy if exists robo_pulso_le on public.robo_pulso;
create policy robo_pulso_le on public.robo_pulso for select to authenticated using ((select privado.e_ativo()));
drop policy if exists robo_pulso_grava on public.robo_pulso;
create policy robo_pulso_grava on public.robo_pulso for insert to authenticated with check (
  (select privado.e_ativo()) and (select privado.tem_papel('robo'))
  and quem = (select auth.uid()));

drop policy if exists robo_parar_le on public.robo_parar;
create policy robo_parar_le on public.robo_parar for select to authenticated using ((select privado.e_ativo()));
drop policy if exists robo_parar_grava on public.robo_parar;
create policy robo_parar_grava on public.robo_parar for insert to authenticated with check (
  (select privado.e_ativo()) and quem = (select auth.uid())
  and (acao = 'parar' or (select privado.tem_papel('aprovador')) or (select privado.e_admin())));

notify pgrst, 'reload schema';

commit;
```

- [ ] **Step 4: rodar e ver passar**

Run: `python -m pytest tests/test_pagamento_api_sql.py tests/test_rls_supabase.py -q`
Expected: PASS.

- [ ] **Step 5: revisão independente.** Despachar o agente `revisor-sql-supabase` sobre a migration; corrigir o que ele achar e repetir o Step 4.

- [ ] **Step 6: Commit**

```bash
git add supabase/migrations/20261126100000_pagamento_pela_api.sql tests/test_pagamento_api_sql.py
git commit -m "nuvem: lote, aprovação e livro do pagamento pela API (só ler e acrescentar; regras no banco)"
```

- [ ] **Step 7: aplicar no banco — SÓ com o "pode" do Gustavo no chat.** Copiar a migration para `APLICAR NO SUPABASE - 2026-11-26 pagamento pela API.sql` na raiz e, com o ok dele: `supabase db query --linked -f "APLICAR NO SUPABASE - 2026-11-26 pagamento pela API.sql"`. Depois, a prova de comportamento DENTRO de `begin; ... rollback;` (nada fica gravado), simulando cada papel com `set local role authenticated; set local request.jwt.claims = '{"sub":"<uuid>","role":"authenticated"}';`: (a) operador cria lote e itens; (b) o mesmo operador tenta aprovar → recusa "quem preparou o lote não aprova"; (c) aprovador aprova com total errado → recusa; com o certo → aceita; (d) operador tenta acrescentar item depois → recusa; (e) aprovador tenta gravar `lote_evento` → recusa da RLS; (f) dois `iniciado` do mesmo item → o segundo recusa pelo índice. Usar uuids de contas de teste com cada papel; anotar o resultado de cada letra no PR.

### Task 7: O robô na nuvem (`nuvem_lote.py`)

**Files:**
- Create: `pagamento_api/nuvem_lote.py`
- Test: `tests/test_pagamento_api_nuvem.py`

**Interfaces:**
- Consumes: `nuvem.rest.ler(tabela, token, *, colunas, filtro)`, `nuvem.rest.inserir(tabela, token, linhas, *, devolver=True)`, `nuvem.rest.ErroDaNuvem` (conferidos em `nuvem/rest.py`); `executor.Evento` (Task 5); `lote.ItemLote`, `lote.total` (Task 2); as colunas da Task 6.
- Produces: `LoteAprovado(id, total, itens)`, `lotes_aprovados(token, hoje) -> list[LoteAprovado]`, `LivroNaNuvem(token, lote_id)` (implementa `executor.Livro`), `parado(token) -> bool`, `pulso(token)`, `NaoGravou`.

- [ ] **Step 1: escrever o teste**

`tests/test_pagamento_api_nuvem.py`:

```python
# -*- coding: utf-8 -*-
"""O lado do robô na nuvem, com o `rest` trocado por um dublê: nenhuma rede."""
from datetime import date
from decimal import Decimal

import pytest

from pagamento_api import executor as ex
from pagamento_api import nuvem_lote as nl
from pagamento_api import lote as lt

from test_pagamento_api_executor import DOC, Erp, Sicoob, _aberto, _item, _rodar


def _linha(ordem, valor):
    return {"ordem": ordem, "titulo": f"T{ordem}", "alvo": f"T{ordem}", "conta": "OBRA X - SICOOB",
            "tipo": "pix_chave", "dados": "a@b.com", "valor": valor, "favorecido": "F",
            "documento_esperado": DOC, "descricao": "D"}


class Rest:
    def __init__(self, tabelas):
        self.tabelas = tabelas
        self.gravados = []

    def ler(self, tabela, token, colunas="*", filtro=""):
        return self.tabelas.get(tabela, [])

    def inserir(self, tabela, token, linhas, devolver=True):
        self.gravados.append((tabela, linhas))
        return [] if tabela == "lote_evento" and self.tabelas.get("_recusa") else linhas


@pytest.fixture
def rest(monkeypatch):
    def fazer(tabelas):
        r = Rest(tabelas)
        monkeypatch.setattr(nl.rest, "ler", r.ler)
        monkeypatch.setattr(nl.rest, "inserir", r.inserir)
        return r
    return fazer


def test_lote_aprovado_vem_com_os_itens_aprovados(rest):
    rest({"lote_pagamento": [{"id": 7}],
          "lote_aprovacao": [{"lote": 7, "itens": [2, 1], "total": "300.00"}],
          "lote_item": [_linha(1, "100.00"), _linha(2, "200.00")]})
    (lote,) = nl.lotes_aprovados("tok", date(2026, 11, 27))
    assert lote.id == 7 and lote.total == Decimal("300.00")
    assert [i.ordem for i in lote.itens] == [1, 2] and lote.itens[0].tipo == lt.PIX_CHAVE


def test_leitura_incompleta_ou_soma_diferente_nao_paga_nada(rest):
    rest({"lote_pagamento": [{"id": 7}],
          "lote_aprovacao": [{"lote": 7, "itens": [1, 2], "total": "300.00"}],
          "lote_item": [_linha(1, "100.00")]})
    assert nl.lotes_aprovados("tok", date(2026, 11, 27)) == []
    rest({"lote_pagamento": [{"id": 7}],
          "lote_aprovacao": [{"lote": 7, "itens": [1], "total": "999.00"}],
          "lote_item": [_linha(1, "100.00")]})
    assert nl.lotes_aprovados("tok", date(2026, 11, 27)) == []


def test_parado_vale_o_ultimo_botao(rest):
    rest({"robo_parar": [{"acao": "parar"}]})
    assert nl.parado("tok") is True
    rest({"robo_parar": [{"acao": "retomar"}]})
    assert nl.parado("tok") is False
    rest({})
    assert nl.parado("tok") is False


def test_evento_que_nao_volta_do_banco_impede_o_pagamento(rest, tmp_path):
    rest({"_recusa": True})
    livro = nl.LivroNaNuvem("tok", 7)
    s = Sicoob(pix_iniciar={"endToEndId": "E1", "proprietario": {"identificador": DOC}},
               pix_confirmar={"estado": "REALIZADO"})
    with pytest.raises(nl.NaoGravou):
        _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, Erp({"T1": _aberto()}), tmp_path, livro)
    assert "pix_confirmar" not in s.chamadas
    assert ex.INICIADO == "iniciado"
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/test_pagamento_api_nuvem.py -q`
Expected: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: implementar**

`pagamento_api/nuvem_lote.py`:

```python
# -*- coding: utf-8 -*-
"""O lado do robô na nuvem: ler o lote aprovado de hoje, anotar cada passo,
o pulso e o botão Parar. Migration `20261126100000_pagamento_pela_api.sql`.

O robô entra com o usuário próprio dele (papel `robo`), nunca com a chave de
serviço: a RLS só o deixa LER e acrescentar evento e pulso.
Gravar evento sem a linha voltar levanta `NaoGravou` — o INICIADO é gravado
antes de pagar, e "gravado" sem ter gravado é o pagamento em dobro da retomada.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from nuvem import rest

from . import executor as ex
from . import lote as lt


class NaoGravou(rest.ErroDaNuvem):
    """O banco respondeu sem devolver a linha do evento."""


@dataclass(frozen=True)
class LoteAprovado:
    id: int
    total: Decimal
    itens: list[lt.ItemLote]


def item_da_linha(r: dict) -> lt.ItemLote:
    return lt.ItemLote(int(r["ordem"]), str(r["titulo"]), str(r["alvo"]), str(r["conta"]),
                       str(r["tipo"]), str(r["dados"]), Decimal(str(r["valor"])),
                       str(r.get("favorecido") or ""), str(r.get("documento_esperado") or ""),
                       str(r.get("descricao") or ""))


def lotes_aprovados(token: str, hoje: date) -> list[LoteAprovado]:
    lotes = rest.ler("lote_pagamento", token, colunas="id", filtro=f"dia=eq.{hoje.isoformat()}")
    ids = [int(l["id"]) for l in lotes]
    if not ids:
        return []
    lista = ",".join(map(str, ids))
    aprov = rest.ler("lote_aprovacao", token, colunas="lote,itens,total",
                     filtro=f"lote=in.({lista})&order=lote.asc")
    saida = []
    for a in aprov:
        ordens = sorted(int(o) for o in a["itens"])
        linhas = rest.ler("lote_item", token, filtro=(
            f"lote=eq.{int(a['lote'])}&ordem=in.({','.join(map(str, ordens))})&order=ordem.asc"))
        itens = [item_da_linha(r) for r in linhas]
        if [i.ordem for i in itens] != ordens:
            continue                     # leitura incompleta: não paga nada deste lote
        total = Decimal(str(a["total"]))
        if lt.total(itens) != total:
            continue
        saida.append(LoteAprovado(int(a["lote"]), total, itens))
    return saida


class LivroNaNuvem:
    def __init__(self, token: str, lote_id: int):
        self.token, self.lote = token, int(lote_id)

    def eventos(self) -> list[ex.Evento]:
        linhas = rest.ler("lote_evento", self.token, colunas="ordem,estado,detalhe,chave",
                          filtro=f"lote=eq.{self.lote}&order=id.asc")
        return [ex.Evento(int(r["ordem"]), str(r["estado"]), str(r.get("detalhe") or ""),
                          str(r.get("chave") or "")) for r in linhas]

    def gravar(self, e: ex.Evento) -> None:
        voltou = rest.inserir("lote_evento", self.token, [{
            "lote": self.lote, "ordem": e.ordem, "estado": e.estado,
            "detalhe": e.detalhe, "chave": e.chave}])
        if not voltou:
            raise NaoGravou(f"evento {e.estado} do item {e.ordem} não voltou do banco")


def parado(token: str) -> bool:
    """O último botão apertado vale. Sem nenhum: não está parado."""
    u = rest.ler("robo_parar", token, colunas="acao", filtro="order=id.desc&limit=1")
    return bool(u) and u[0].get("acao") == "parar"


def pulso(token: str) -> None:
    rest.inserir("robo_pulso", token, [{}], devolver=False)
```

- [ ] **Step 4: rodar e ver passar**

Run: `python -m pytest tests/test_pagamento_api_nuvem.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add pagamento_api/nuvem_lote.py tests/test_pagamento_api_nuvem.py
git commit -m "pagamento_api: o robô lê o lote aprovado e anota cada passo na nuvem"
```

### Task 8: O robô e o ensaio no Sandbox (`robo.py`)

**Files:**
- Create: `pagamento_api/robo.py`
- Create: `.claude/rules/arquitetura-pagamento-api.md`
- Modify: `CLAUDE.md` (uma linha na tabela "Pasta ou arquivo | Onde está o mapa")
- Test: `tests/test_pagamento_api_robo.py`

**Interfaces:**
- Consumes: tudo das Tasks 2–5 e 7.
- Produces: `python -m pagamento_api.robo --config <json>` (uma rodada) e `--ensaio-sandbox`; `trava_da_rodada(pasta)`, `TRAVA_VELHA_SEGUNDOS`, `ErpDeEnsaio`, `LivroNaMemoria`, `main(argv)`.

- [ ] **Step 1: escrever o teste**

`tests/test_pagamento_api_robo.py`:

```python
# -*- coding: utf-8 -*-
import os
import time

from pagamento_api import robo


def test_uma_rodada_por_vez(tmp_path):
    with robo.trava_da_rodada(tmp_path) as primeira:
        assert primeira is True
        with robo.trava_da_rodada(tmp_path) as segunda:
            assert segunda is False
    with robo.trava_da_rodada(tmp_path) as depois:
        assert depois is True


def test_trava_velha_e_assumida(tmp_path):
    arq = tmp_path / "robo.trava"
    arq.write_text("123")
    velho = time.time() - robo.TRAVA_VELHA_SEGUNDOS - 60
    os.utime(arq, (velho, velho))
    with robo.trava_da_rodada(tmp_path) as minha:
        assert minha is True


def test_ensaio_sem_credencial_do_sandbox_nao_roda(capsys):
    assert robo.main(["--ensaio-sandbox"]) == 2
    assert "client_id" in capsys.readouterr().out
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/test_pagamento_api_robo.py -q`
Expected: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: implementar**

`pagamento_api/robo.py`:

```python
# -*- coding: utf-8 -*-
"""O robô do servidor: uma rodada por chamada (o Agendador chama a cada 1–2 min).

    python -m pagamento_api.robo --config <arquivo.json>     rodada de verdade
    python -m pagamento_api.robo --ensaio-sandbox            Sicoob do Sandbox, sem nuvem e sem ERP

O arquivo de configuração mora na pasta de chaves do servidor, NUNCA no repo:
    {"ambiente": "sandbox",
     "client_id": "...", "token_fixo": "...",          (sandbox: os do portal)
     "cert": ["c:/.../cert.pem", "c:/.../chave.pem"],   (produção)
     "nuvem_email": "...", "nuvem_senha": "...",
     "pasta_comprovantes": "c:/.../comprovantes-api",
     "contas": {"NOME DA CONTA NO ERP": {"cooperativa": 0, "numero": 0, "tipo_pessoa": 1}}}
Neste plano o ERP é o de ENSAIO (não toca no Mais Controle); o de verdade e o
token de produção entram no plano 3.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

import requests

from . import executor as ex
from . import lote as lt
from . import sicoob as sc


class ErpDeEnsaio:
    """Finge o ERP: todo título em aberto com o valor do item; anexo e baixa anotados."""

    def __init__(self, itens):
        self.t = {i.titulo: ex.Titulo(True, i.valor, False) for i in itens}
        self.feito = []

    def titulo(self, tid):
        return self.t.get(tid)

    def anexar(self, tid, caminho):
        self.feito.append(("anexo", tid, str(caminho)))
        return True

    def baixar(self, tid, valor, dia, conta):
        self.feito.append(("baixa", tid, str(valor)))
        self.t[tid] = ex.Titulo(False, valor, True)
        return True


class LivroNaMemoria:
    def __init__(self):
        self.lista = []

    def eventos(self):
        return list(self.lista)

    def gravar(self, e):
        self.lista.append(e)
        print(f"  item {e.ordem}: {e.estado} {e.detalhe}".rstrip())


def cliente(cfg: dict) -> sc.Sicoob:
    if cfg.get("ambiente") != "sandbox":
        raise SystemExit("produção entra no plano 3 (token OAuth e certificado)")
    tok = str(cfg["token_fixo"])
    return sc.Sicoob(requests.Session(), sc.SANDBOX, str(cfg["client_id"]), lambda: tok,
                     cert=tuple(cfg["cert"]) if cfg.get("cert") else None)


def contas(cfg: dict) -> dict[str, sc.ContaApi]:
    return {nome: sc.ContaApi(int(c["cooperativa"]), int(c["numero"]), int(c["tipo_pessoa"]))
            for nome, c in (cfg.get("contas") or {}).items()}


def ensaio_sandbox(cfg: dict, pasta: Path) -> list[ex.Evento]:
    """Três itens fictícios contra o Sandbox. Os mocks do Sandbox respondem
    sempre igual, então o que se prova é o encanamento, não a regra."""
    conta = "ENSAIO - SICOOB"
    itens = [
        lt.ItemLote(1, "E1", "E1", conta, lt.PIX_CHAVE, "ensaio@exemplo.com", Decimal("1.99"),
                    "ENSAIO", "", "ENSAIO PIX"),
        lt.ItemLote(2, "E2", "E2", conta, lt.BOLETO, "75691234500000152301234567890123456789012345"[:44],
                    Decimal("152.30"), "ENSAIO", "", "ENSAIO BOLETO"),
        lt.ItemLote(3, "E3", "E3", conta, lt.CONVENIO, "8" + "3" * 43, Decimal("1171.23"),
                    "ENSAIO", "", "ENSAIO CONVENIO"),
    ]
    livro = LivroNaMemoria()
    portas = ex.Portas(cliente(cfg), ErpDeEnsaio(itens), livro,
                       {conta: sc.ContaApi(4342, 1234569, 1)}, pasta, date.today())
    ex.Executor(itens, lt.total(itens), portas).rodar()
    return livro.lista


#: Trava velha (o processo morreu sem soltar): depois disso, a rodada seguinte assume.
TRAVA_VELHA_SEGUNDOS = 15 * 60


@contextmanager
def trava_da_rodada(pasta: Path):
    """Uma rodada por vez nesta máquina. Devolve False quando outra está rodando.
    (Entre máquinas, quem segura é o índice `lote_evento_um_iniciado` do banco.)"""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / "robo.trava"
    try:
        if arq.exists() and time.time() - arq.stat().st_mtime > TRAVA_VELHA_SEGUNDOS:
            arq.unlink()
        fd = os.open(str(arq), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        yield False
        return
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield True
    finally:
        try:
            arq.unlink()
        except FileNotFoundError:
            pass


def rodada(cfg: dict) -> None:
    with trava_da_rodada(Path(cfg["pasta_comprovantes"])) as minha:
        if not minha:
            print("outra rodada está rodando; esta sai sem fazer nada")
            return
        _rodada(cfg)


def _rodada(cfg: dict) -> None:
    from nuvem import rest
    from . import nuvem_lote as nl
    s = rest.entrar(cfg["nuvem_email"], cfg["nuvem_senha"])
    token = s["access_token"]
    nl.pulso(token)
    if nl.parado(token):
        print("parado pelo botão; nada a fazer")
        return
    hoje = date.today()
    for lote in nl.lotes_aprovados(token, hoje):
        print(f"lote {lote.id}: {len(lote.itens)} itens, total {lote.total}")
        livro = nl.LivroNaNuvem(token, lote.id)
        portas = ex.Portas(cliente(cfg), ErpDeEnsaio(lote.itens), livro, contas(cfg),
                           Path(cfg["pasta_comprovantes"]), hoje,
                           parar=lambda: nl.parado(token))
        ex.Executor(lote.itens, lote.total, portas).rodar()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--ensaio-sandbox", action="store_true")
    a = ap.parse_args(argv)
    if a.ensaio_sandbox:
        cfg = json.loads(Path(a.config).read_text(encoding="utf-8")) if a.config else {}
        cfg.setdefault("ambiente", "sandbox")
        if "client_id" not in cfg or "token_fixo" not in cfg:
            print("passe --config com client_id e token_fixo do Sandbox (portal, menu Sandbox)")
            return 2
        ensaio_sandbox(cfg, Path(cfg.get("pasta_comprovantes") or "comprovantes-ensaio"))
        return 0
    if not a.config:
        ap.error("--config é obrigatório")
    rodada(json.loads(Path(a.config).read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: rodar e ver passar**

Run: `python -m pytest tests/test_pagamento_api_robo.py -q`
Expected: 3 passed.

- [ ] **Step 5: ensaio contra o Sandbox (manual, fora do CI).** Criar FORA do repo um `ensaio.json` com o Client ID e o Access token que o portal mostra em developers.sicoob.com.br/portal/sandbox (são públicos, iguais para todo desenvolvedor) e `"pasta_comprovantes"` numa pasta temporária. Rodar `python -m pagamento_api.robo --ensaio-sandbox --config <caminho>/ensaio.json`.
Expected (medido em 26/11/2026; os mocks respondem sempre igual):
```
  item 1: iniciado
  item 1: nao_pago string
  item 2: nao_pago banco bloqueia: Pagamento bloqueado
  item 3: iniciado convenio
  item 3: realizado <pasta>/bruto-convenio-E3-3.json
  item 3: concluido <pasta>/<data> ENSAIO CONVENIO R$ 1171,23 item 3.pdf
```
Qualquer `Request Rejected` ou `não é JSON` aqui é o firewall: parar e avisar, sem mexer na identificação.

- [ ] **Step 6: o mapa da pasta.** Criar `.claude/rules/arquitetura-pagamento-api.md` com: o que cada arquivo faz (uma linha cada, as mesmas dos docstrings), as regras de dinheiro da spec, o desvio do hash, o achado do firewall (200 + HTML) e os três planos. Acrescentar na tabela do `CLAUDE.md`: `| pagamento_api/ (pagar pela API do Sicoob) | .claude/rules/arquitetura-pagamento-api.md |`.

- [ ] **Step 7: suíte inteira e régua do CI**

Run: `python -m ruff check --select E9,F . && vermin --target=3.11 --violations pagamento_api tests && python -m pytest tests -q`
Expected: tudo verde (a suíte inteira, não só os arquivos novos).

- [ ] **Step 8: Commit e PR**

```bash
git add pagamento_api/robo.py tests/test_pagamento_api_robo.py .claude/rules/arquitetura-pagamento-api.md CLAUDE.md
git commit -m "pagamento_api: robô de uma rodada, trava contra rodada dupla e ensaio no Sandbox"
git push -u origin codigo/pagamento-api-sicoob
```
Abrir o PR com o resultado da prova da Task 6 (Step 7) e do ensaio (Step 5). Antes do merge: revisão do ramo inteiro (opus) e o agente `revisor-dinheiro`. O PR sai da conversa juntado, fechado com motivo ou anotado em "Pendências e perguntas" com data (regra do dono de 14/10).
