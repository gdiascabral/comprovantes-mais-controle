# Aba Pagamentos no portal — E1a: a leitura das 07:30 no servidor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** um job sem tela, `python -m leitura_manha.rodar --config <arquivo>`, que às 07:30 lê o saldo de cada conta (Sicoob pela API Conta Corrente, Inter pela API Banking, ERP pelo porteiro), lê o extrato de ontem, casa esse extrato com os agendados em aberto pela regra pura `tela_do_dia.autenticar.autenticar` (só PRÉ-MARCA) e grava tudo numa migration nova, que só acrescenta, com o usuário de papel `robo`.

**Architecture:** pacote novo `leitura_manha/`, só do repositório, que não vai no `codigo.zip`. O HTTP fica em `transporte.py`, com o ritmo, uma nova tentativa no 429 e a recusa de resposta que não é JSON. Os clientes de leitura ficam em `bancos.py`, e `extrato.py` lê os números sem adivinhar. `leitura.py` orquestra, com uma conta por `try`. `nuvem_leitura.py` grava em três tabelas novas. `rodar.py` é a CLI. O ERP só entra pelo `ler_saldos` com o central ligado. Os clientes, o ERP e a nuvem chegam como portas injetadas, e os testes usam dublês.

**Tech Stack:** Python 3.11, `requests` (já no `requirements.lock`, nenhuma dependência nova), `nuvem/rest.py` (PostgREST), pytest e o Agendador do Windows (PowerShell 5.1).

**Spec:** `docs/superpowers/specs/2026-11-27-aba-pagamentos-no-portal-design.md`: D2, D3 e a entrega E1 da seção 7. Este plano é só o lado do SERVIDOR (E1a). A tela no portal (E1b) e qualquer pagamento ficam FORA.

**Ponto de partida:** o branch `codigo/pagamento-api-sicoob` (PR #203). Ele já tem `pagamento_api/` (`USER_AGENT`, `robo.trava_da_rodada`, `robo.FUSO_SP`) e a migration `20261126100000_pagamento_pela_api.sql`, com o papel `robo`, `privado.tem_papel(text)` e `privado.hoje()`. O E1a só pode ser aplicado no banco DEPOIS dela.

## Global Constraints

- Python 3.11: nada de API de 3.12+. No rascunho, `vermin -t=3.11- --violations leitura_manha tests` deu "Minimum required versions: 3.7". No repo, vale o comando do job `test`: `vermin --target=3.11 --no-tips --violations .`.
- Dinheiro em `Decimal`. O JSON do banco é lido com `parse_float=Decimal` (`transporte.pedir_json`), e float nunca é dinheiro (`extrato.centavos` o recusa).
- Nenhuma dependência nova.
- O repo é público. Não entra nome real de empresa ou pessoa, CPF, CNPJ, número de conta, client_id, segredo nem token em código, teste ou comentário. Os testes usam "EMP A", "A1 - SICOOB", "FORNECEDOR TESTE" e números como 11 e 123456.
- Credenciais de produção, certificados e a senha do usuário `robo` ficam só no arquivo da pasta de chaves do servidor. O `.ps1` recusa um `-Config` que esteja dentro do repositório.
- O ERP só é lido pelo porteiro (`tela_do_dia.erp_do_dia.ler_saldos` com o Chrome central ligado). **Nunca login HTTP no ERP.** Com o porteiro desligado, o job grava "ERP não lido" e não toca no ERP.
- Na nuvem só entram `select` e `insert` (sem update/delete), e a gravação é só do papel `robo`. Pré-marca nunca é resposta: nada aqui escreve em `agendado_resposta` (regra de 29/10).
- O cliente se identifica com `pagamento_api.sicoob.USER_AGENT` e trata resposta que não é JSON como erro. O firewall do Sicoob responde 200 com HTML ao User-Agent padrão, e isso foi medido de novo em 27/11 (ver Task 8).
- Sem `argparse` (ele não vem no exe; padrão do `pagamento_api.robo`).
- O pacote `leitura_manha` entra em `_PASTAS_SO_DO_REPO` de `tests/test_empacotamento.py`, com o motivo. A pasta `ferramentas/leitura_manha/` só tem `.ps1` e já é ferramenta.
- O registro no Agendador é ato humano, no servidor. Nenhum teste nem o app registra a tarefa.
- Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Rede nos testes: nenhuma. Os dublês ficam em `tests/falsos_leitura_manha.py`.

## Review Focus

Antes do handoff, o código deste plano foi escrito numa pasta de rascunho e rodado inteiro: **104 testes passando**, `ruff --select E9,F` limpo e vermin com mínimo 3.7. Com a nova migration ao lado das que já existem, os testes de varredura do repo (`test_rls_supabase.py`, `test_pagamento_api_sql.py`, `test_pagamentos_do_dia_sql.py`, `test_tela_do_dia_controle_sql.py`) passaram: 32 testes. A **prova contrária** removeu, uma de cada vez, 20 regras de dinheiro e de casamento (lista na Task 9), e os testes **mataram os 20 mutantes**. No Sandbox do Sicoob foi feito um ensaio real (saída na Task 8). O que ainda pode morder, do mais provável ao menos:

1. **O `tipo` e o `valor` do extrato do Sicoob em produção não estão medidos.** O Sandbox devolve lorem ipsum em todos os campos, e a documentação não diz o texto do tipo nem o formato do valor. O parser aceita só `tipo` em {D, DEBITO, DÉBITO, C, CREDITO, CRÉDITO} e `valor` SEM sinal em "1234.56", "1234,56" ou "1.234,56". O resto cai em `ilegiveis`. Uma linha ilegível tira a conta INTEIRA do casamento ("banco não lido: …") e nunca pré-marca nada. O que se espera no 1º extrato real: se o Sicoob mandar o débito com sinal ("-150.00") ou com outro texto no `tipo`, a conta aparece com N ilegíveis e zero pré-marcas. Corrige-se o `_TIPOS`/`valor_texto`, de forma consciente, depois de ver o JSON real. Fixam isso `test_extrato_lorem_do_sandbox_fica_todo_ilegivel`, `test_valor_com_sinal_fica_ilegivel_ate_confirmar_o_formato` e `test_uma_linha_ilegivel_tira_a_conta_do_casamento`. Também não está medido: se a `data` vem com hora em UTC ("…T02:00:00Z" seria o dia anterior em São Paulo). O parser pega só a parte da data.
2. **O `x-conta-corrente` do Inter com várias contas numa integração não está medido.** O Sandbox tem uma conta só. Pela documentação, ele vai só quando a integração tem mais de uma conta, com dígitos e sem zeros à esquerda, e o `config.py` recusa um valor que não seja só dígitos. O que se espera com a credencial de produção: uma integração por empresa com uma conta (sem o cabeçalho). Com duas contas, conferir no 1º dia se o extrato de cada uma bate com o app do Inter. Teste: `test_inter_extrato_e_saldo_com_conta_corrente_so_quando_configurada`. Já o `tipoOperacao` do Inter **foi medido** no Sandbox em 27/11 pelo coordenador: só "C" ou "D", `valor` como texto com ponto e sem sinal, `dataEntrada` no formato YYYY-MM-DD e `tipoTransacao` às vezes None (não é usado). Fica preso em `test_inter_na_forma_medida_no_sandbox` e no mutante "tipoOperacao do Inter trocado".
3. **Rate limit.** Do Sicoob, 2 por segundo: um `Ritmo(0,55 s)` compartilhado entre TODAS as empresas, porque o limite do banco não sabe de empresa. Do Inter, 10 por minuto em saldo e extrato (`Ritmo(6,5 s)`) e 5 por minuto no token (`Ritmo(13 s)`, um token por empresa). No 429 o cliente espera (2 s no Sicoob, 61 s no Inter) e tenta UMA vez. No segundo 429, a conta fica "não lido: HTTP 429", sem 3ª chamada. Token recusado não é pedido de novo na mesma rodada. Com 10 contas no Inter, a rodada leva uns 2 minutos e meio, e o Agendador dá 30. Testes: `test_sicoob_respeita_2_por_segundo_entre_empresas`, `test_inter_no_maximo_10_por_minuto`, `test_429_duas_vezes_desiste_sem_terceira_chamada` e `test_token_recusado_nao_repete_pedido_nem_mostra_o_segredo`.
4. **A falha de uma empresa ou de uma conta não derruba as outras.** Cada conta é lida no seu próprio `try`, o saldo e o extrato também separados. A fábrica de uma empresa que estoura (certificado faltando) vira o motivo de cada conta dela, e é chamada uma vez só. O ERP fora vira "ERP não lido" em cada conta do arquivo. A nuvem fora devolve o código 1 ao Agendador, e o log ainda guarda os saldos. Testes: `test_token_de_uma_empresa_caido_nao_derruba_a_outra_e_nao_vira_zero`, `test_erro_inesperado_numa_conta_nao_para_as_seguintes`, `test_fabrica_da_empresa_e_chamada_uma_vez_mesmo_quando_falha`, `test_erp_fora_marca_cada_conta_como_nao_lida` e `test_nuvem_fora_devolve_1_e_o_log_ainda_tem_os_saldos`.
5. **O saldo "não lido" nunca vira zero**, e isso vale em três camadas:
   - `SaldoLido.__post_init__` recusa valor sem motivo e motivo sem valor;
   - a nuvem grava `null`;
   - o banco tem `check ((valor is null) = (length(trim(motivo)) > 0))`.

   O saldo do Sandbox do Sicoob vem como float com 8 a 11 casas (medido: `-22996950.34619233`) e sai como "não lido: fora do formato". Isso é falha fechada, de propósito: um número com mais de 2 casas não é dinheiro. O saldo zero DE VERDADE continua zero (`test_saldo_zero_de_verdade_e_zero`). O ERP que não mostra o saldo (`balance=None`) também sai "não lido".
6. **"Ontem" é o de São Paulo**, e não o do relógio do servidor. `dias_sp` exige `datetime` com fuso e converte por `pagamento_api.robo.FUSO_SP` (UTC−3, sem horário de verão desde 2019). Às 02:00 UTC ainda é o dia anterior em SP. O `test_ontem_e_o_de_sao_paulo` cobre a virada de ano e o fim de fevereiro. Uma limitação consciente: se o servidor ficar desligado um dia inteiro, o extrato daquele dia não é lido de novo. O agendado continua em aberto e a pessoa responde no portal, como hoje. Ver "Dúvidas" no fim.

## Modelo por tarefa

| Tarefa | Implementa | Revisa | Por quê |
|---|---|---|---|
| 1 transporte e pacote fora do zip | haiku | sonnet | código dado, mecânico |
| 2 clientes de leitura | haiku | sonnet | código dado; URLs e cabeçalhos conferidos na revisão |
| 3 leitura do número (extrato/saldo) | sonnet | **opus** | decide o que é dinheiro legível; falha fechada |
| 4 arquivo do servidor | haiku | sonnet | código dado; segredos fora de mensagem |
| 5 orquestração e pré-marca | sonnet | **opus** | isolamento das falhas e casamento com `autenticar` |
| 6 migration | sonnet | **opus** + agente `revisor-sql-supabase` | RLS e trava do "não lido" no banco |
| 7 gravação na nuvem | haiku | sonnet | código dado |
| 8 CLI, Agendador e ensaios | sonnet | sonnet | porteiro, código de saída; ensaios manuais |
| 9 verificação final do ramo | — | **opus** + agente `revisor-dinheiro` | antes do PR |

Tudo é síncrono e roda numa thread só, fora do app. Nenhum objeto com afinidade de thread atravessa as tarefas. O `ler_saldos` roda na thread principal do job, como roda no `ferramentas/sonda.py`.

## Arquivos

| Arquivo | Responsabilidade |
|---|---|
| `leitura_manha/__init__.py` | o que o pacote é e por que fica fora do zip |
| `leitura_manha/transporte.py` | `ErroLeitura`, `Ritmo`, `pedir_json`, `TokenOAuth` |
| `leitura_manha/bancos.py` | `ContaCorrenteSicoob`, `BankingInter`, `token_sicoob`, `token_inter`, endereços e ritmos |
| `leitura_manha/extrato.py` | `centavos`, `valor_texto`, `saldo_sicoob`, `saldo_inter`, `movimentos_sicoob`, `movimentos_inter` (sem rede) |
| `leitura_manha/config.py` | o arquivo do servidor: `de_dict`, `carregar`, `Config`/`Empresa`/`ContaBanco` |
| `leitura_manha/leitura.py` | `ler_bancos`, `ler_erp`, `pre_marcas`, `dias_sp`, `SaldoLido`/`ExtratoLido`/`PreMarca` |
| `leitura_manha/nuvem_leitura.py` | `em_aberto`, `gravar` (três tabelas) |
| `leitura_manha/rodar.py` | CLI, `Fabrica`, `ler_erp_pelo_porteiro`, `rodada`, `ensaio_sandbox` |
| `ferramentas/leitura_manha/registrar_leitura_manha.ps1` | registro no Agendador (ato humano) |
| `supabase/migrations/20261127100000_leitura_da_manha.sql` | `saldo_lido`, `extrato_lido`, `pre_marca_banco` |
| `tests/falsos_leitura_manha.py` | dublês: `SessaoFalsa`, `Resp`, `Relogio` |
| `tests/test_leitura_manha_*.py` | um por módulo, mais o `_sql` |
| `tests/test_empacotamento.py` (modificar) | `leitura_manha` em `_PASTAS_SO_DO_REPO` |

## Preparação (uma vez, antes da Task 1)

- [ ] Criar o worktree a partir do branch do PR #203, no padrão do projeto (`_worktrees/app-<tema>`):

```bash
cd "C:/AUTOMAÇÕES MAIS CONTROLE/fontes/comprovantes-mais-controle"   # o clone principal (git-common-dir do worktree do #203)
git fetch origin
git worktree add "C:/AUTOMAÇÕES MAIS CONTROLE/_worktrees/app-leitura-manha" -b codigo/leitura-manha origin/codigo/pagamento-api-sicoob
cd "C:/AUTOMAÇÕES MAIS CONTROLE/_worktrees/app-leitura-manha"
python -m pytest -q tests -p no:cacheprovider    # linha de base: tem de estar verde ANTES
```

Esperado: a suíte verde do PR #203. Se não estiver verde, pare e avise. Este plano não conserta o PR #203.

---

### Task 1: Transporte (ritmo, 429, JSON) e o pacote fora do zip

**Files:**
- Create: `leitura_manha/__init__.py`
- Create: `leitura_manha/transporte.py`
- Create: `tests/falsos_leitura_manha.py`
- Test: `tests/test_leitura_manha_transporte.py`
- Modify: `tests/test_empacotamento.py` (dicionário `_PASTAS_SO_DO_REPO`, por volta da linha 63)

**Interfaces:**
- Consumes: nada de tarefas anteriores.
- Produces:
  - `class ErroLeitura(RuntimeError)`, com `.status: int | None` e `.corpo: str`;
  - `class Ritmo(intervalo: float, relogio=time.monotonic, esperar=time.sleep)`, com `.vez() -> None` e os atributos `.relogio`/`.esperar`;
  - `pedir_json(sessao, metodo, url, *, ritmo, headers, params=None, data=None, cert=None, timeout=30.0, espera_429=0.0) -> dict`, com os números em `Decimal`;
  - `class TokenOAuth(sessao, url, form: dict, *, user_agent, cert=None, ritmo=None, relogio=time.monotonic)`, chamável `() -> str`.

  Nos testes: `SessaoFalsa(*respostas)` (`.request(metodo, url, **k)` e `.pedidos`), `Resp(status, corpo)` e `Relogio()` (chamável, com `.esperar(s)` e `.esperas`).

- [ ] **Step 1: Escrever os dublês e o teste que falha**

`tests/falsos_leitura_manha.py`:

```python
# -*- coding: utf-8 -*-
"""Dublês da leitura das 07:30: sessão HTTP, relógio e ERP. Sem rede."""
from __future__ import annotations

import json
from collections import deque


class Resp:
    def __init__(self, status: int, corpo):
        self.status_code = status
        self.text = corpo if isinstance(corpo, str) else json.dumps(corpo)


class SessaoFalsa:
    """Devolve as respostas na ordem; acabou a fila = AssertionError (chamada a mais
    derruba o teste em vez de repetir a última resposta)."""

    def __init__(self, *respostas):
        self.fila = deque(respostas)
        self.pedidos = []

    def request(self, metodo, url, **k):
        self.pedidos.append((metodo, url, k))
        if not self.fila:
            raise AssertionError(f"chamada a mais: {metodo} {url}")
        r = self.fila.popleft()
        if isinstance(r, Exception):
            raise r
        return r


class Relogio:
    def __init__(self):
        self.t = 0.0
        self.esperas = []

    def __call__(self) -> float:
        return self.t

    def esperar(self, s: float) -> None:
        self.esperas.append(round(s, 3))
        self.t += s
```

`tests/test_leitura_manha_transporte.py`:

```python
# -*- coding: utf-8 -*-
from decimal import Decimal

import pytest
from falsos_leitura_manha import Relogio, Resp, SessaoFalsa

from leitura_manha.transporte import ErroLeitura, Ritmo, TokenOAuth, pedir_json


def _pedir(sessao, ritmo=None, **k):
    return pedir_json(sessao, "GET", "https://banco/x", ritmo=ritmo or Ritmo(0),
                      headers={}, **k)


def test_ritmo_espera_o_que_falta_do_intervalo():
    rel = Relogio()
    r = Ritmo(0.5, relogio=rel, esperar=rel.esperar)
    r.vez()
    rel.t += 0.2
    r.vez()
    r.vez()
    assert rel.esperas == [0.3, 0.5]


def test_numero_vem_em_decimal_nunca_float():
    corpo = _pedir(SessaoFalsa(Resp(200, '{"saldo": 1234.56}')))
    assert corpo["saldo"] == Decimal("1234.56") and isinstance(corpo["saldo"], Decimal)


def test_html_com_200_do_firewall_e_erro():
    with pytest.raises(ErroLeitura, match="não é JSON"):
        _pedir(SessaoFalsa(Resp(200, "<html><title>Request Rejected</title></html>")))


def test_json_que_nao_e_objeto_e_erro():
    with pytest.raises(ErroLeitura, match="objeto"):
        _pedir(SessaoFalsa(Resp(200, "[1, 2]")))


def test_fora_de_2xx_e_erro_com_status():
    with pytest.raises(ErroLeitura) as e:
        _pedir(SessaoFalsa(Resp(500, "pane")))
    assert e.value.status == 500


def test_rede_caida_vira_erro_sem_a_url():
    with pytest.raises(ErroLeitura) as e:
        _pedir(SessaoFalsa(ConnectionError("https://banco/x?numeroContaCorrente=99")))
    assert e.value.status is None and "99" not in str(e.value)


def test_429_espera_e_tenta_uma_vez_so():
    rel = Relogio()
    ritmo = Ritmo(0, relogio=rel, esperar=rel.esperar)
    s = SessaoFalsa(Resp(429, "devagar"), Resp(200, {"ok": 1}))
    assert _pedir(s, ritmo, espera_429=2.0) == {"ok": 1}
    assert rel.esperas == [2.0] and len(s.pedidos) == 2


def test_429_duas_vezes_desiste_sem_terceira_chamada():
    s = SessaoFalsa(Resp(429, "devagar"), Resp(429, "devagar"))
    with pytest.raises(ErroLeitura) as e:
        _pedir(s, Ritmo(0, esperar=lambda _s: None))
    assert e.value.status == 429 and len(s.pedidos) == 2


def _token(sessao, rel=None):
    rel = rel or Relogio()
    return TokenOAuth(sessao, "https://auth/token", {"client_id": "c", "client_secret": "SEGREDO"},
                      user_agent="ua", relogio=rel), rel


def test_token_guardado_ate_60s_antes_de_vencer():
    s = SessaoFalsa(Resp(200, {"access_token": "T1", "expires_in": 3600}),
                    Resp(200, {"access_token": "T2", "expires_in": 3600}))
    tok, rel = _token(s)
    assert tok() == "T1"
    rel.t = 3539
    assert tok() == "T1"
    rel.t = 3541
    assert tok() == "T2"
    metodo, _url, k = s.pedidos[0]
    assert metodo == "POST" and k["data"]["client_secret"] == "SEGREDO"


def test_token_recusado_nao_repete_pedido_nem_mostra_o_segredo():
    s = SessaoFalsa(Resp(401, '{"erro": "client_secret SEGREDO invalido"}'))
    tok, _rel = _token(s)
    for _ in range(3):
        with pytest.raises(ErroLeitura) as e:
            tok()
        assert "SEGREDO" not in str(e.value)
    assert len(s.pedidos) == 1


def test_token_sem_access_token_e_erro():
    tok, _rel = _token(SessaoFalsa(Resp(200, {"token_type": "Bearer"})))
    with pytest.raises(ErroLeitura):
        tok()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest -q tests/test_leitura_manha_transporte.py -p no:cacheprovider`
Esperado: erro de coleta `ModuleNotFoundError: No module named 'leitura_manha'`.

- [ ] **Step 3: Implementar**

`leitura_manha/__init__.py`:

```python
# -*- coding: utf-8 -*-
"""Leitura das 07:30 (entrega E1a da spec 2026-11-27-aba-pagamentos-no-portal).

Job SEM tela, rodado pelo Agendador do servidor: lê o saldo de cada conta no
Sicoob (API Conta Corrente) e no Inter (API Banking), o saldo de cada conta no
ERP pelo porteiro, o extrato de ontem, casa o extrato com os agendados em
aberto (`tela_do_dia.autenticar`, que só PRÉ-MARCA) e grava tudo na nuvem com
o usuário de papel `robo`. Não paga, não escreve no ERP, não responde
agendado: quem responde "Pago" continua sendo a pessoa (regra de 29/10/2026).

Fica fora do `codigo.zip` (`tests/test_empacotamento.py`): roda só do clone do
repositório no servidor; o app nunca o importa.
"""
```

`leitura_manha/transporte.py`:

```python
# -*- coding: utf-8 -*-
"""O HTTP das leituras: ritmo (rate limit), uma nova tentativa no 429 e a
recusa de resposta que não é JSON. Não decide nada sobre dinheiro.

Só GET de leitura e POST de token passam por aqui: repetir uma vez depois do
429 é seguro porque nada aqui move dinheiro.
"""
from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import Callable


class ErroLeitura(RuntimeError):
    """O banco não respondeu, respondeu fora de 2xx, ou respondeu 2xx com algo
    que não serve (HTML do firewall, JSON que não é objeto). `status` None =
    não houve resposta. Nunca carrega token nem certificado."""

    def __init__(self, status, corpo: str):
        super().__init__(f"HTTP {status}: {corpo[:200]}")
        self.status = status
        self.corpo = corpo


class Ritmo:
    """No máximo uma chamada a cada `intervalo` segundos. Um objeto só para
    todos os clientes do mesmo banco: o limite do banco não sabe de empresa."""

    def __init__(self, intervalo: float, relogio: Callable[[], float] = time.monotonic,
                 esperar: Callable[[float], None] = time.sleep):
        self.intervalo = float(intervalo)
        self.relogio, self.esperar = relogio, esperar
        self._ultimo = None

    def vez(self) -> None:
        if self._ultimo is not None:
            falta = self.intervalo - (self.relogio() - self._ultimo)
            if falta > 0:
                self.esperar(falta)
        self._ultimo = self.relogio()


def pedir_json(sessao, metodo: str, url: str, *, ritmo: Ritmo, headers: dict,
               params=None, data=None, cert=None, timeout: float = 30.0,
               espera_429: float = 0.0) -> dict:
    """O corpo JSON (números em Decimal) de uma resposta 2xx, ou ErroLeitura.
    429 na 1ª tentativa: espera `espera_429` e tenta UMA vez de novo."""
    for tentativa in (1, 2):
        ritmo.vez()
        try:
            r = sessao.request(metodo, url, headers=headers, params=params, data=data,
                               cert=cert, timeout=timeout)
        except Exception as e:  # rede caiu: o motivo é só o tipo (a URL leva a conta)
            raise ErroLeitura(None, f"sem resposta ({type(e).__name__})") from e
        if r.status_code == 429 and tentativa == 1:
            ritmo.esperar(espera_429)
            continue
        break
    texto = r.text or ""
    if not 200 <= r.status_code < 300:
        raise ErroLeitura(r.status_code, texto)
    try:
        corpo = json.loads(texto, parse_float=Decimal)
    except ValueError:
        # 200 com HTML = recusa do firewall do Sicoob (medido em 26 e 27/11/2026).
        raise ErroLeitura(r.status_code, "resposta não é JSON: " + texto[:80]) from None
    if not isinstance(corpo, dict):
        raise ErroLeitura(r.status_code, "resposta não é um objeto JSON")
    return corpo


class TokenOAuth:
    """Token client_credentials (com mTLS) guardado até 60 s antes de vencer.

    Falhou uma vez, falha de novo nesta rodada sem pedir outra vez: N contas da
    mesma empresa não viram N pedidos de token (o do Inter aceita 5 por minuto).
    O `form` leva o segredo: nunca vai para mensagem de erro nem para log."""

    def __init__(self, sessao, url: str, form: dict, *, user_agent: str, cert=None,
                 ritmo: Ritmo | None = None, relogio: Callable[[], float] = time.monotonic):
        self._s, self._url, self._form = sessao, url, dict(form)
        self._ua, self._cert = user_agent, cert
        self._ritmo = ritmo or Ritmo(0)
        self._relogio = relogio
        self._token, self._vence, self._erro = "", 0.0, None

    def __repr__(self) -> str:
        return f"TokenOAuth({self._url!r})"

    def __call__(self) -> str:
        if self._erro is not None:
            raise self._erro
        if self._token and self._relogio() < self._vence:
            return self._token
        try:
            corpo = pedir_json(self._s, "POST", self._url, ritmo=self._ritmo,
                               headers={"User-Agent": self._ua, "Accept": "application/json",
                                        "Content-Type": "application/x-www-form-urlencoded"},
                               data=self._form, cert=self._cert)
            tok = corpo.get("access_token")
            if not isinstance(tok, str) or not tok:
                raise ErroLeitura(200, "token sem access_token")
        except ErroLeitura as e:
            # O corpo de erro do servidor de token não volta para a nuvem.
            self._erro = ErroLeitura(e.status, "token recusado")
            raise self._erro from None
        dura = corpo.get("expires_in")
        segundos = int(dura) if isinstance(dura, (int, Decimal)) and not isinstance(dura, bool) else 300
        self._token, self._vence = tok, self._relogio() + max(0, segundos - 60)
        return tok
```

Em `tests/test_empacotamento.py`, acrescente a entrada ao `_PASTAS_SO_DO_REPO`, logo depois da de `"ferramentas"`:

```python
    "leitura_manha": (
        "a leitura das 07:30 (saldo e extrato pela API do Sicoob e do Inter, "
        "saldo do ERP pelo porteiro, pré-marcas na nuvem) roda só do clone do "
        "repositório no servidor, pelo Agendador; o app nunca a importa e ela "
        "não tem por que viajar no zip para a máquina de quem usa"),
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest -q tests/test_leitura_manha_transporte.py tests/test_empacotamento.py -p no:cacheprovider`
Esperado: `11 passed` no transporte e o empacotamento verde. O teste do empacotamento só enxerga o pacote depois do `git add`: rode-o de novo DEPOIS do `git add` do Step 5, antes do commit.

- [ ] **Step 5: Commit**

```bash
git add leitura_manha/__init__.py leitura_manha/transporte.py tests/falsos_leitura_manha.py tests/test_leitura_manha_transporte.py tests/test_empacotamento.py
python -m pytest -q tests/test_empacotamento.py -p no:cacheprovider
git commit -m "leitura_manha: transporte de leitura (ritmo, 1 nova tentativa no 429, nao-JSON e erro, token guardado) e pacote fora do codigo.zip" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Os clientes de leitura (Sicoob Conta Corrente e Inter Banking)

**Files:**
- Create: `leitura_manha/bancos.py`
- Test: `tests/test_leitura_manha_bancos.py`

**Interfaces:**
- Consumes: `transporte.Ritmo`, `transporte.TokenOAuth`, `transporte.pedir_json` (Task 1) e `pagamento_api.sicoob.USER_AGENT` (PR #203, `pagamento_api/sicoob.py:42`).
- Produces:
  - as constantes `SICOOB_PRODUCAO`, `SICOOB_SANDBOX`, `SICOOB_TOKEN`, `INTER_PRODUCAO`, `INTER_SANDBOX`, `INTERVALO_SICOOB=0.55`, `INTERVALO_INTER=6.5` e `INTERVALO_TOKEN_INTER=13.0`;
  - `token_sicoob(sessao, client_id, cert) -> TokenOAuth`;
  - `token_inter(sessao, base, client_id, client_secret, cert, ritmo) -> TokenOAuth`;
  - `ContaCorrenteSicoob(sessao, base, client_id, token, *, ritmo, cert=None)`, com `.saldo(numero: int) -> dict` e `.extrato(numero: int, dia: date) -> dict`;
  - `BankingInter(sessao, base, token, *, ritmo, cert=None, conta_corrente="")`, com `.saldo() -> dict` e `.extrato(dia: date) -> dict`.

Endereços e campos vêm dos portais em 27/11/2026:
- Sicoob: `GET {base}/saldo?numeroContaCorrente=` e `GET {base}/extrato/{mes}/{ano}?numeroContaCorrente=&diaInicial=&diaFinal=`, com o cabeçalho `client_id`, e o token `client_credentials` com mTLS e escopo `cco_consulta`;
- Inter: `GET /banking/v2/saldo` e `GET /banking/v2/extrato?dataInicio=&dataFim=`, com o token `POST /oauth/v2/token` (form, escopo `extrato.read`) e o `x-conta-corrente` só com mais de uma conta.

- [ ] **Step 1: Escrever o teste que falha**

```python
# -*- coding: utf-8 -*-
from datetime import date

from falsos_leitura_manha import Relogio, Resp, SessaoFalsa

from leitura_manha import bancos as bc
from leitura_manha.transporte import Ritmo
from pagamento_api.sicoob import USER_AGENT


def _sicoob(*resps):
    s = SessaoFalsa(*resps)
    return s, bc.ContaCorrenteSicoob(s, bc.SICOOB_SANDBOX, "CID", lambda: "TOK", ritmo=Ritmo(0))


def test_saldo_sicoob_pede_a_conta_com_o_user_agent_proprio():
    s, c = _sicoob(Resp(200, {"saldo": 10}))
    assert c.saldo(1234) == {"saldo": 10}
    metodo, url, k = s.pedidos[0]
    assert (metodo, url) == ("GET", bc.SICOOB_SANDBOX + "/saldo")
    assert k["params"] == {"numeroContaCorrente": 1234}
    assert k["headers"]["User-Agent"] == USER_AGENT
    assert k["headers"]["client_id"] == "CID" and k["headers"]["Authorization"] == "Bearer TOK"


def test_extrato_sicoob_de_um_dia_so():
    s, c = _sicoob(Resp(200, {"transacoes": []}))
    c.extrato(1234, date(2026, 1, 5))
    _m, url, k = s.pedidos[0]
    assert url == bc.SICOOB_SANDBOX + "/extrato/1/2026"
    assert k["params"] == {"numeroContaCorrente": 1234, "diaInicial": 5, "diaFinal": 5}


def test_sicoob_respeita_2_por_segundo_entre_empresas():
    rel = Relogio()
    ritmo = Ritmo(bc.INTERVALO_SICOOB, relogio=rel, esperar=rel.esperar)
    s = SessaoFalsa(Resp(200, {}), Resp(200, {}), Resp(200, {}))
    a = bc.ContaCorrenteSicoob(s, bc.SICOOB_SANDBOX, "A", lambda: "x", ritmo=ritmo)
    b = bc.ContaCorrenteSicoob(s, bc.SICOOB_SANDBOX, "B", lambda: "y", ritmo=ritmo)
    a.saldo(1)
    b.saldo(2)
    a.saldo(3)
    assert rel.esperas == [bc.INTERVALO_SICOOB, bc.INTERVALO_SICOOB]
    assert bc.INTERVALO_SICOOB >= 0.5


def test_inter_extrato_e_saldo_com_conta_corrente_so_quando_configurada():
    s = SessaoFalsa(Resp(200, {"disponivel": 1}), Resp(200, {"transacoes": []}))
    i = bc.BankingInter(s, bc.INTER_PRODUCAO, lambda: "T", ritmo=Ritmo(0), conta_corrente="123")
    i.saldo()
    i.extrato(date(2026, 11, 26))
    (_m1, u1, k1), (_m2, u2, k2) = s.pedidos
    assert u1 == bc.INTER_PRODUCAO + "/banking/v2/saldo" and k1["headers"]["x-conta-corrente"] == "123"
    assert u2 == bc.INTER_PRODUCAO + "/banking/v2/extrato"
    assert k2["params"] == {"dataInicio": "2026-11-26", "dataFim": "2026-11-26"}
    s2 = SessaoFalsa(Resp(200, {}))
    bc.BankingInter(s2, bc.INTER_PRODUCAO, lambda: "T", ritmo=Ritmo(0)).saldo()
    assert "x-conta-corrente" not in s2.pedidos[0][2]["headers"]


def test_inter_no_maximo_10_por_minuto():
    assert 60 / bc.INTERVALO_INTER <= 10 and 60 / bc.INTERVALO_TOKEN_INTER <= 5


def test_tokens_pedem_so_leitura():
    s = SessaoFalsa(Resp(200, {"access_token": "A"}), Resp(200, {"access_token": "B"}))
    bc.token_sicoob(s, "CID", ("c.pem", "k.pem"))()
    bc.token_inter(s, bc.INTER_PRODUCAO, "CI", "CS", ("c.pem", "k.pem"), Ritmo(0))()
    (_m, u1, k1), (_m2, u2, k2) = s.pedidos
    assert u1 == bc.SICOOB_TOKEN and k1["data"]["scope"] == "cco_consulta"
    assert k1["cert"] == ("c.pem", "k.pem")
    assert u2 == bc.INTER_PRODUCAO + "/oauth/v2/token" and k2["data"]["scope"] == "extrato.read"
    assert k2["data"]["grant_type"] == "client_credentials"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest -q tests/test_leitura_manha_bancos.py -p no:cacheprovider`
Esperado: `ImportError: cannot import name 'bancos' from 'leitura_manha'`.

- [ ] **Step 3: Implementar**

```python
# -*- coding: utf-8 -*-
"""Os dois clientes de LEITURA: Sicoob Conta Corrente (v4) e Inter Banking (v2).

Só GET de saldo e de extrato (e o POST do token). Endereços e campos lidos nos
portais developers.sicoob.com.br e developers.inter.co em 27/11/2026. O que os
dois devolvem é cru: quem lê o número é `extrato.py`.
"""
from __future__ import annotations

from datetime import date
from typing import Callable

from pagamento_api.sicoob import USER_AGENT

from .transporte import Ritmo, TokenOAuth, pedir_json

SICOOB_PRODUCAO = "https://api.sicoob.com.br/conta-corrente/v4"
SICOOB_SANDBOX = "https://sandbox.sicoob.com.br/sicoob/sandbox/conta-corrente/v4"
SICOOB_TOKEN = "https://auth.sicoob.com.br/auth/realms/cooperado/protocol/openid-connect/token"
SICOOB_ESCOPO = "cco_consulta"
INTER_PRODUCAO = "https://cdpj.partners.bancointer.com.br"
INTER_SANDBOX = "https://cdpj-sandbox.partners.uatinter.co"
INTER_ESCOPO = "extrato.read"

#: Limites dos portais: Sicoob Conta Corrente 2/s; Inter saldo e extrato 10/min,
#: token do Inter 5/min. O ritmo fica um pouco abaixo de cada um.
INTERVALO_SICOOB = 0.55
INTERVALO_INTER = 6.5
INTERVALO_TOKEN_INTER = 13.0
#: Quanto esperar antes da única nova tentativa depois de um 429.
ESPERA_429_SICOOB = 2.0
ESPERA_429_INTER = 61.0


def token_sicoob(sessao, client_id: str, cert) -> TokenOAuth:
    """Produção: client_credentials com o certificado da empresa (mTLS)."""
    return TokenOAuth(sessao, SICOOB_TOKEN,
                      {"grant_type": "client_credentials", "client_id": client_id,
                       "scope": SICOOB_ESCOPO},
                      user_agent=USER_AGENT, cert=cert)


def token_inter(sessao, base: str, client_id: str, client_secret: str, cert,
                ritmo: Ritmo) -> TokenOAuth:
    return TokenOAuth(sessao, base + "/oauth/v2/token",
                      {"client_id": client_id, "client_secret": client_secret,
                       "grant_type": "client_credentials", "scope": INTER_ESCOPO},
                      user_agent=USER_AGENT, cert=cert, ritmo=ritmo)


class ContaCorrenteSicoob:
    """GET /saldo e GET /extrato/{mes}/{ano} de uma empresa (um client_id)."""

    def __init__(self, sessao, base: str, client_id: str, token: Callable[[], str], *,
                 ritmo: Ritmo, cert=None, timeout: float = 30.0,
                 espera_429: float = ESPERA_429_SICOOB):
        self._s, self._base, self._cid, self._token = sessao, base, client_id, token
        self._ritmo, self._cert, self._timeout, self._429 = ritmo, cert, timeout, espera_429

    def _get(self, caminho: str, params: dict) -> dict:
        h = {"User-Agent": USER_AGENT, "Authorization": "Bearer " + self._token(),
             "client_id": self._cid, "Accept": "application/json"}
        return pedir_json(self._s, "GET", self._base + caminho, ritmo=self._ritmo,
                          headers=h, params=params, cert=self._cert,
                          timeout=self._timeout, espera_429=self._429)

    def saldo(self, numero: int) -> dict:
        return self._get("/saldo", {"numeroContaCorrente": int(numero)})

    def extrato(self, numero: int, dia: date) -> dict:
        return self._get(f"/extrato/{dia.month}/{dia.year}",
                         {"numeroContaCorrente": int(numero), "diaInicial": dia.day,
                          "diaFinal": dia.day})


class BankingInter:
    """GET /banking/v2/saldo e /banking/v2/extrato de UMA conta do Inter."""

    def __init__(self, sessao, base: str, token: Callable[[], str], *, ritmo: Ritmo,
                 cert=None, conta_corrente: str = "", timeout: float = 30.0,
                 espera_429: float = ESPERA_429_INTER):
        self._s, self._base, self._token = sessao, base, token
        self._ritmo, self._cert, self._timeout, self._429 = ritmo, cert, timeout, espera_429
        self._conta = str(conta_corrente or "")

    def _get(self, caminho: str, params: dict | None) -> dict:
        h = {"User-Agent": USER_AGENT, "Authorization": "Bearer " + self._token(),
             "Accept": "application/json"}
        if self._conta:  # só quando a integração tem mais de uma conta
            h["x-conta-corrente"] = self._conta
        return pedir_json(self._s, "GET", self._base + caminho, ritmo=self._ritmo,
                          headers=h, params=params, cert=self._cert,
                          timeout=self._timeout, espera_429=self._429)

    def saldo(self) -> dict:
        return self._get("/banking/v2/saldo", None)

    def extrato(self, dia: date) -> dict:
        return self._get("/banking/v2/extrato",
                         {"dataInicio": dia.isoformat(), "dataFim": dia.isoformat()})
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest -q tests/test_leitura_manha_bancos.py -p no:cacheprovider`
Esperado: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add leitura_manha/bancos.py tests/test_leitura_manha_bancos.py
git commit -m "leitura_manha: clientes de leitura do Sicoob (Conta Corrente v4) e do Inter (Banking v2), com ritmo por banco" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Ler o número sem adivinhar (`extrato.py`)

**Files:**
- Create: `leitura_manha/extrato.py`
- Test: `tests/test_leitura_manha_extrato.py`

**Interfaces:**
- Consumes: `tela_do_dia.autenticar.Movimento` e `tela_do_dia.autenticar.data_do_banco`, ambos no PR #203 (`tela_do_dia/autenticar.py:78` e `:119`).
- Produces:
  - `CENTAVO`, `SAIDA` e `ENTRADA`;
  - `class ExtratoIlegivel(ValueError)`;
  - `centavos(v) -> Decimal | None` e `valor_texto(t) -> Decimal | None`;
  - `saldo_sicoob(corpo) -> (Decimal | None, motivo)` e `saldo_inter(corpo) -> (Decimal | None, motivo)`;
  - `@dataclass(frozen) Extrato(movimentos: tuple[Movimento], entradas: int, ilegiveis: int, fora_do_dia: int, motivos: tuple)`;
  - `movimentos_sicoob(corpo, conta_erp, dia) -> Extrato` e `movimentos_inter(corpo, conta_erp, dia) -> Extrato`. As duas levantam `ExtratoIlegivel` quando falta a lista `transacoes`.

Em `Movimento`, `conta` é o nome da conta no ERP (o mesmo de `Agendado.conta`), e só as SAÍDAS do dia viram `Movimento`. `barras` fica `""`, porque o extrato não traz código de barras. O casamento então cai no passo 2 de `autenticar`: valor ao centavo mais a descrição colada.

- [ ] **Step 1: Escrever o teste que falha**

```python
# -*- coding: utf-8 -*-
from datetime import date
from decimal import Decimal

import pytest

from leitura_manha import extrato as ex

ONTEM = date(2026, 11, 26)


@pytest.mark.parametrize("v, esperado", [
    (Decimal("1234.56"), Decimal("1234.56")), (0, Decimal("0.00")), (Decimal("-10.5"), Decimal("-10.50")),
    (Decimal("436196.58701458573"), None), (1234.56, None), (True, None), ("10.00", None), (None, None),
])
def test_centavos_so_numero_com_ate_duas_casas(v, esperado):
    assert ex.centavos(v) == esperado


@pytest.mark.parametrize("t, esperado", [
    ("1234.56", Decimal("1234.56")), ("1234,56", Decimal("1234.56")), ("1.234,56", Decimal("1234.56")),
    ("150", Decimal("150.00")), ("150.5", Decimal("150.50")),
    ("1.234", None), ("-150.00", None), ("R$ 10,00", None), ("ullamco anim", None), ("", None),
    ("1,234.56", None), (None, None),
])
def test_valor_texto_nao_adivinha(t, esperado):
    assert ex.valor_texto(t) == esperado


def test_saldo_do_sandbox_com_muitas_casas_e_nao_lido_nunca_zero():
    valor, motivo = ex.saldo_sicoob({"saldo": Decimal("436196.58701458573")})
    assert valor is None and "fora do formato" in motivo


def test_saldo_ausente_e_nao_lido():
    assert ex.saldo_sicoob({})[0] is None and ex.saldo_inter({"limite": Decimal("5")})[0] is None


def test_saldo_zero_de_verdade_e_zero():
    assert ex.saldo_sicoob({"saldo": 0}) == (Decimal("0.00"), "")
    assert ex.saldo_inter({"disponivel": Decimal("12.30")}) == (Decimal("12.30"), "")


#: Copiado da resposta do Sandbox em 27/11/2026 (lorem ipsum em todo campo).
LOREM = {"saldoAnterior": "Duis", "transacoes": [
    {"descricao": "minim", "valor": "ullamco anim id aliqua ad", "data": "commodo sit ut cupidatat",
     "tipo": "elit magna", "transactionId": "x"},
    {"descricao": "dolor", "valor": "do fugiat labore in", "data": "qui tempor sunt in Lorem",
     "tipo": "consectetur"}]}


def test_extrato_lorem_do_sandbox_fica_todo_ilegivel():
    x = ex.movimentos_sicoob(LOREM, "CONTA A", ONTEM)
    assert x.movimentos == () and x.ilegiveis == 2 and x.entradas == 0
    assert len(x.motivos) == 2


def test_extrato_sicoob_so_saidas_do_dia_viram_movimento():
    corpo = {"transacoes": [
        {"tipo": "DEBITO", "valor": "150,00", "data": "2026-11-26", "descricao": "PAGAMENTO",
         "descInfComplementar": "OBRA X LT 10", "transactionId": "T1"},
        {"tipo": "CREDITO", "valor": "900.00", "data": "2026-11-26", "descricao": "PIX RECEBIDO"},
        {"tipo": "D", "valor": "80.00", "data": "25/11/2026", "descricao": "ANTERIOR"},
    ]}
    x = ex.movimentos_sicoob(corpo, "CONTA A", ONTEM)
    assert x.ilegiveis == 0 and x.entradas == 1 and x.fora_do_dia == 1
    (m,) = x.movimentos
    assert (m.conta, m.data, m.valor, m.descricao, m.ident) == (
        "CONTA A", ONTEM, Decimal("150.00"), "OBRA X LT 10", "T1")


def test_valor_com_sinal_fica_ilegivel_ate_confirmar_o_formato():
    x = ex.movimentos_sicoob({"transacoes": [
        {"tipo": "DEBITO", "valor": "-150.00", "data": "2026-11-26"}]}, "A", ONTEM)
    assert x.movimentos == () and x.ilegiveis == 1


def test_valor_zero_fica_ilegivel():
    x = ex.movimentos_sicoob({"transacoes": [
        {"tipo": "DEBITO", "valor": "0.00", "data": "2026-11-26"}]}, "A", ONTEM)
    assert x.ilegiveis == 1


def test_extrato_sem_lista_de_transacoes_e_ilegivel_inteiro():
    with pytest.raises(ex.ExtratoIlegivel):
        ex.movimentos_sicoob({"saldoAtual": "1"}, "A", ONTEM)
    with pytest.raises(ex.ExtratoIlegivel):
        ex.movimentos_inter({"transacoes": "nada"}, "A", ONTEM)


def test_inter_tipo_operacao_d_e_saida_c_e_entrada_outro_e_ilegivel():
    corpo = {"transacoes": [
        {"tipoOperacao": "D", "valor": "1171.23", "dataEntrada": "2026-11-26", "titulo": "Pagamento",
         "descricao": "CONVENIO SANEAMENTO"},
        {"tipoOperacao": "C", "valor": "10.00", "dataEntrada": "2026-11-26"},
        {"tipoOperacao": "X", "valor": "10.00", "dataEntrada": "2026-11-26"},
    ]}
    x = ex.movimentos_inter(corpo, "CONTA I", ONTEM)
    assert x.entradas == 1 and x.ilegiveis == 1
    (m,) = x.movimentos
    assert (m.valor, m.descricao, m.origem) == (Decimal("1171.23"), "CONVENIO SANEAMENTO",
                                                "Inter extrato (API)")


def test_inter_na_forma_medida_no_sandbox():
    """Forma medida no Sandbox do Inter em 27/11/2026: tipoOperacao só C/D,
    valor string com ponto e sem sinal, dataEntrada YYYY-MM-DD, tipoTransacao
    às vezes None (não é usado), dados de 2023 (fora do dia pedido)."""
    corpo = {"transacoes": [
        {"dataEntrada": "2026-11-26", "tipoTransacao": None, "tipoOperacao": "D",
         "valor": "33.33", "titulo": "Pix enviado", "descricao": ""},
        {"dataEntrada": "2023-01-26", "tipoTransacao": "PIX", "tipoOperacao": "D",
         "valor": "10.00", "titulo": "Pix enviado", "descricao": "X"},
    ]}
    x = ex.movimentos_inter(corpo, "CONTA I", ONTEM)
    assert x.ilegiveis == 0 and x.fora_do_dia == 1
    (m,) = x.movimentos
    assert (m.valor, m.descricao) == (Decimal("33.33"), "Pix enviado")


def test_saldo_inter_em_float_no_json_chega_decimal_exato():
    import json
    corpo = json.loads('{"disponivel": 1234.5, "limite": 0}', parse_float=Decimal)
    assert ex.saldo_inter(corpo) == (Decimal("1234.50"), "")


def test_linha_que_nao_e_objeto_e_ilegivel():
    assert ex.movimentos_inter({"transacoes": ["x", 3]}, "A", ONTEM).ilegiveis == 2
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest -q tests/test_leitura_manha_extrato.py -p no:cacheprovider`
Esperado: `ImportError: cannot import name 'extrato' from 'leitura_manha'`.

- [ ] **Step 3: Implementar**

```python
# -*- coding: utf-8 -*-
"""O número que o banco devolveu, lido sem adivinhar. Sem rede.

Regra: o que não se lê com certeza fica FORA e é contado — nunca vira zero,
nunca vira um valor parecido. Saldo ilegível = "não lido" (None + motivo).
Linha de extrato ilegível = contada em `ilegiveis`; a conta com qualquer linha
ilegível não entra no casamento (`leitura.py`), porque a linha que faltou pode
ser justamente a que decide.

A CONFIRMAR com o 1º extrato real do Sicoob (o Sandbox devolve lorem ipsum em
todos os campos do extrato, medido em 27/11/2026): o texto do `tipo`, o formato
do `valor` (sinal, separador) e o da `data`. Até lá, só entram as formas
abaixo, e o resto cai em `ilegiveis`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from tela_do_dia.autenticar import Movimento, data_do_banco

CENTAVO = Decimal("0.01")
#: Formas aceitas de valor em TEXTO: "1234.56", "1234,56", "1.234,56", "150".
_PONTO = re.compile(r"^\d+(\.\d{1,2})?$")
_VIRGULA = re.compile(r"^(\d{1,3}(\.\d{3})+|\d+),\d{2}$")
SAIDA, ENTRADA = "saida", "entrada"
_TIPOS = {"D": SAIDA, "DEBITO": SAIDA, "DÉBITO": SAIDA,
          "C": ENTRADA, "CREDITO": ENTRADA, "CRÉDITO": ENTRADA}
#: Quantos motivos de linha ilegível vão para a nuvem (o resto só conta).
MOTIVOS_GUARDADOS = 3


class ExtratoIlegivel(ValueError):
    """O extrato inteiro não tem a forma esperada (sem a lista de transações)."""


def centavos(v) -> Decimal | None:
    """Número JSON (já em Decimal ou int) com até 2 casas, ou None.
    bool, float, texto e número com mais de 2 casas não são dinheiro."""
    if isinstance(v, bool) or not isinstance(v, (int, Decimal)):
        return None
    d = Decimal(v)
    if not d.is_finite() or d != d.quantize(CENTAVO):
        return None
    return d.quantize(CENTAVO)


def valor_texto(t) -> Decimal | None:
    """Valor em texto, SEM sinal, numa das formas de `_PONTO`/`_VIRGULA`; senão None."""
    if isinstance(t, (int, Decimal)) and not isinstance(t, bool):
        return centavos(t)
    if not isinstance(t, str):
        return None
    s = t.strip()
    if _PONTO.match(s):
        return Decimal(s).quantize(CENTAVO)
    if _VIRGULA.match(s):
        return Decimal(s.replace(".", "").replace(",", ".")).quantize(CENTAVO)
    return None


def _saldo(corpo, campo: str, banco: str) -> tuple[Decimal | None, str]:
    bruto = (corpo or {}).get(campo)
    v = centavos(bruto)
    if v is None:
        return None, f"{banco}: saldo fora do formato ({campo}={str(bruto)[:30]!r})"
    return v, ""


def saldo_sicoob(corpo: dict) -> tuple[Decimal | None, str]:
    """`saldo` do GET /saldo (número). `saldoLimite` não é dinheiro da conta."""
    return _saldo(corpo, "saldo", "Sicoob")


def saldo_inter(corpo: dict) -> tuple[Decimal | None, str]:
    """`disponivel` do GET /banking/v2/saldo (número)."""
    return _saldo(corpo, "disponivel", "Inter")


@dataclass(frozen=True)
class Extrato:
    movimentos: tuple          # só as SAÍDAS do dia, como `autenticar.Movimento`
    entradas: int
    ilegiveis: int
    fora_do_dia: int
    motivos: tuple = ()        # até MOTIVOS_GUARDADOS, para a nuvem


def _transacoes(corpo) -> list:
    lista = (corpo or {}).get("transacoes") if isinstance(corpo, dict) else None
    if not isinstance(lista, list):
        raise ExtratoIlegivel("extrato sem a lista 'transacoes'")
    return lista


def _ler(lista, dia: date, linha_para) -> Extrato:
    """`linha_para(t)` -> (SAIDA|ENTRADA, Movimento), ou levanta ValueError(motivo)."""
    movs, entradas, ilegiveis, fora, motivos = [], 0, 0, 0, []
    for t in lista:
        try:
            tipo, mov = linha_para(t)
        except ValueError as e:
            ilegiveis += 1
            if len(motivos) < MOTIVOS_GUARDADOS:
                motivos.append(str(e)[:80])
            continue
        if mov.data != dia:
            fora += 1
        elif tipo == ENTRADA:
            entradas += 1
        else:
            movs.append(mov)
    return Extrato(tuple(movs), entradas, ilegiveis, fora, tuple(motivos))


def _comum(t, campo_tipo: str, campo_data: str):
    if not isinstance(t, dict):
        raise ValueError("linha não é objeto")
    bruto = str(t.get(campo_tipo) or "").strip().upper()
    tipo = _TIPOS.get(bruto)
    if tipo is None:
        raise ValueError(f"{campo_tipo} desconhecido {bruto[:20]!r}")
    valor = valor_texto(t.get("valor"))
    if valor is None or valor <= 0:
        raise ValueError(f"valor ilegível {str(t.get('valor'))[:20]!r}")
    dia = data_do_banco(t.get(campo_data)) if isinstance(t.get(campo_data), str) else None
    if dia is None:
        raise ValueError(f"{campo_data} ilegível {str(t.get(campo_data))[:20]!r}")
    return tipo, valor, dia


def movimentos_sicoob(corpo: dict, conta_erp: str, dia: date) -> Extrato:
    """GET /extrato do Sicoob: tudo string (`tipo`, `valor`, `data`, ...)."""
    def linha(t):
        tipo, valor, d = _comum(t, "tipo", "data")
        desc = str(t.get("descInfComplementar") or "").strip() or str(t.get("descricao") or "").strip()
        return tipo, Movimento(conta_erp, d, valor, "", desc, "", "Sicoob extrato (API)",
                               str(t.get("transactionId") or ""))
    return _ler(_transacoes(corpo), dia, linha)


def movimentos_inter(corpo: dict, conta_erp: str, dia: date) -> Extrato:
    """GET /banking/v2/extrato do Inter: `tipoOperacao` C/D, `valor` string."""
    def linha(t):
        tipo, valor, d = _comum(t, "tipoOperacao", "dataEntrada")
        desc = str(t.get("descricao") or "").strip() or str(t.get("titulo") or "").strip()
        return tipo, Movimento(conta_erp, d, valor, "", desc, "", "Inter extrato (API)", "")
    return _ler(_transacoes(corpo), dia, linha)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest -q tests/test_leitura_manha_extrato.py -p no:cacheprovider`
Esperado: `32 passed`.

- [ ] **Step 5: Commit**

```bash
git add leitura_manha/extrato.py tests/test_leitura_manha_extrato.py
git commit -m "leitura_manha: saldo e extrato lidos sem adivinhar (linha ilegivel contada, nunca zero; lorem do Sandbox fica fora)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: O arquivo do servidor (`config.py`)

**Files:**
- Create: `leitura_manha/config.py`
- Test: `tests/test_leitura_manha_config.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `class ConfigInvalida(ValueError)`;
  - `ContaBanco(empresa, banco, conta_erp, numero=0, conta_corrente="")`;
  - `Empresa(nome, contas: tuple, sicoob: dict | None, inter: dict | None)`, sem as credenciais no `repr`;
  - `Config(ambiente, pasta, empresas, nuvem_email, nuvem_senha)`, com `.contas() -> list[ContaBanco]`;
  - `de_dict(d) -> Config` e `carregar(caminho) -> Config`.

  A credencial do Sicoob é um dict com `client_id` e `cert` (lista de 2 ou None), mais `token_fixo` no Sandbox. A do Inter tem `client_id`, `client_secret` e `cert`.

Credenciais POR EMPRESA (cada CNPJ tem certificado e app próprios). `conta_erp` é o nome da conta no Mais Controle, único no arquivo. A `pasta` (trava e log) tem de ser DIFERENTE da `pasta_comprovantes` do robô de pagamento: as duas usam o nome de arquivo `robo.trava` e, na mesma pasta, uma barraria a outra.

- [ ] **Step 1: Escrever o teste que falha**

```python
# -*- coding: utf-8 -*-
import copy

import pytest

from leitura_manha import config as cf

BOM = {"ambiente": "producao", "nuvem_email": "robo@exemplo.com", "nuvem_senha": "SENHA-ROBO",
       "pasta": "c:/leitura",
       "empresas": [{"nome": "EMPRESA A",
                     "sicoob": {"client_id": "CID", "cert": ["c.pem", "k.pem"]},
                     "inter": {"client_id": "CI", "client_secret": "SEGREDO-INTER",
                               "cert": ["c.pem", "k.pem"]},
                     "contas": [{"banco": "sicoob", "numero": 123456, "conta_erp": "A - SICOOB"},
                                {"banco": "inter", "conta_erp": "A - INTER"}]}]}


def _com(mudar):
    d = copy.deepcopy(BOM)
    mudar(d)
    return d


def test_arquivo_bom():
    c = cf.de_dict(BOM)
    assert [x.conta_erp for x in c.contas()] == ["A - SICOOB", "A - INTER"]
    assert c.contas()[0].numero == 123456 and c.empresas[0].inter["client_secret"] == "SEGREDO-INTER"


def test_repr_nao_mostra_segredo():
    c = cf.de_dict(BOM)
    assert "SEGREDO" not in repr(c) and "SENHA-ROBO" not in repr(c)


@pytest.mark.parametrize("mudar, trecho", [
    (lambda d: d.update(ambiente="teste"), "ambiente"),
    (lambda d: d["empresas"][0]["contas"][0].update(numero="123456"), "numero"),
    (lambda d: d["empresas"][0]["contas"][0].update(numero=True), "numero"),
    (lambda d: d["empresas"][0]["contas"][1].update(conta_erp="A - SICOOB"), "repetida"),
    (lambda d: d["empresas"][0]["sicoob"].pop("cert"), "exige 'cert'"),
    (lambda d: d["empresas"][0]["inter"].pop("client_secret"), "client_secret"),
    (lambda d: d["empresas"][0]["contas"][1].update(conta_corrente="12-3"), "dígitos"),
    (lambda d: d["empresas"][0]["contas"][0].update(banco="caixa"), "banco"),
    (lambda d: d.pop("nuvem_senha"), "nuvem_senha"),
    (lambda d: d.update(empresas=[]), "sem empresas"),
])
def test_arquivo_ruim_diz_o_campo_sem_o_valor(mudar, trecho):
    with pytest.raises(cf.ConfigInvalida) as e:
        cf.de_dict(_com(mudar))
    assert trecho in str(e.value)
    assert "SEGREDO" not in str(e.value) and "SENHA-ROBO" not in str(e.value)


def test_sandbox_pede_token_fixo_e_dispensa_nuvem():
    c = cf.de_dict({"ambiente": "sandbox", "pasta": "p", "empresas": [
        {"nome": "E", "sicoob": {"client_id": "C", "token_fixo": "T"},
         "contas": [{"banco": "sicoob", "numero": 1, "conta_erp": "X"}]}]})
    assert c.empresas[0].sicoob["token_fixo"] == "T" and c.nuvem_email == ""


def test_arquivo_ilegivel(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{nao e json", encoding="utf-8")
    with pytest.raises(cf.ConfigInvalida, match="não consegui ler"):
        cf.carregar(p)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest -q tests/test_leitura_manha_config.py -p no:cacheprovider`
Esperado: `ImportError: cannot import name 'config' from 'leitura_manha'`.

- [ ] **Step 3: Implementar**

```python
# -*- coding: utf-8 -*-
"""O arquivo do servidor (pasta de chaves, NUNCA no repo), lido e conferido.

    {"ambiente": "producao",
     "nuvem_email": "...", "nuvem_senha": "...",          (o usuário de papel robo)
     "pasta": "c:/.../leitura-manha",                     (trava e registro)
     "empresas": [
       {"nome": "EMPRESA A",
        "sicoob": {"client_id": "...", "cert": ["c:/.../cert.pem", "c:/.../chave.pem"]},
        "inter":  {"client_id": "...", "client_secret": "...", "cert": ["...", "..."]},
        "contas": [
          {"banco": "sicoob", "numero": 123456, "conta_erp": "NOME DA CONTA NO ERP"},
          {"banco": "inter", "conta_corrente": "", "conta_erp": "NOME DA CONTA NO ERP"}]}]}

Cada CNPJ tem certificado e app próprios no banco: as credenciais são POR
EMPRESA. `conta_erp` é o nome da conta no Mais Controle (o mesmo de
`pagamento_agendado.conta`). Mensagem de erro nunca repete valor de segredo.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

AMBIENTES = ("producao", "sandbox")
BANCOS = ("sicoob", "inter")


class ConfigInvalida(ValueError):
    """O arquivo do servidor não serve. A mensagem diz o campo, nunca o valor."""


@dataclass(frozen=True)
class ContaBanco:
    empresa: str
    banco: str
    conta_erp: str
    numero: int = 0              # Sicoob: numeroContaCorrente
    conta_corrente: str = ""     # Inter: x-conta-corrente (só com mais de uma conta)


@dataclass(frozen=True)
class Empresa:
    nome: str
    contas: tuple
    sicoob: dict | None = field(default=None, repr=False)
    inter: dict | None = field(default=None, repr=False)


@dataclass(frozen=True)
class Config:
    ambiente: str
    pasta: str
    empresas: tuple
    nuvem_email: str = field(default="", repr=False)
    nuvem_senha: str = field(default="", repr=False)

    def contas(self) -> list[ContaBanco]:
        return [c for e in self.empresas for c in e.contas]


def _texto(d: dict, campo: str, onde: str) -> str:
    v = d.get(campo)
    if not isinstance(v, str) or not v.strip():
        raise ConfigInvalida(f"{onde}: falta '{campo}'")
    return v.strip()


def _cert(d: dict, onde: str):
    c = d.get("cert")
    if c is None:
        return None
    if (not isinstance(c, list) or len(c) != 2
            or not all(isinstance(x, str) and x.strip() for x in c)):
        raise ConfigInvalida(f"{onde}: 'cert' tem de ser [certificado, chave]")
    return [x.strip() for x in c]


def _credencial_sicoob(d, ambiente: str, onde: str) -> dict:
    if not isinstance(d, dict):
        raise ConfigInvalida(f"{onde}: falta o bloco 'sicoob'")
    cred = {"client_id": _texto(d, "client_id", onde), "cert": _cert(d, onde)}
    if ambiente == "sandbox":
        cred["token_fixo"] = _texto(d, "token_fixo", onde)
    elif cred["cert"] is None:
        raise ConfigInvalida(f"{onde}: produção do Sicoob exige 'cert'")
    return cred


def _credencial_inter(d, onde: str) -> dict:
    if not isinstance(d, dict):
        raise ConfigInvalida(f"{onde}: falta o bloco 'inter'")
    cred = {"client_id": _texto(d, "client_id", onde),
            "client_secret": _texto(d, "client_secret", onde), "cert": _cert(d, onde)}
    if cred["cert"] is None:
        raise ConfigInvalida(f"{onde}: o Inter exige 'cert'")
    return cred


def de_dict(d: dict) -> Config:
    if not isinstance(d, dict):
        raise ConfigInvalida("o arquivo não é um objeto JSON")
    ambiente = d.get("ambiente")
    if ambiente not in AMBIENTES:
        raise ConfigInvalida(f"'ambiente' tem de ser um de {AMBIENTES}")
    empresas, vistas = [], set()
    for k, e in enumerate(d.get("empresas") or ()):
        onde = f"empresa {k + 1}"
        if not isinstance(e, dict):
            raise ConfigInvalida(f"{onde}: não é objeto")
        nome = _texto(e, "nome", onde)
        contas = []
        for j, c in enumerate(e.get("contas") or ()):
            ondec = f"{nome}, conta {j + 1}"
            if not isinstance(c, dict) or c.get("banco") not in BANCOS:
                raise ConfigInvalida(f"{ondec}: 'banco' tem de ser um de {BANCOS}")
            erp = _texto(c, "conta_erp", ondec)
            if erp in vistas:
                raise ConfigInvalida(f"{ondec}: conta_erp repetida no arquivo")
            vistas.add(erp)
            if c["banco"] == "sicoob":
                n = c.get("numero")
                if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
                    raise ConfigInvalida(f"{ondec}: 'numero' do Sicoob tem de ser inteiro > 0")
                contas.append(ContaBanco(nome, "sicoob", erp, numero=n))
            else:
                cc = c.get("conta_corrente") or ""
                if not isinstance(cc, str) or (cc and not cc.isdigit()):
                    raise ConfigInvalida(f"{ondec}: 'conta_corrente' do Inter só com dígitos")
                contas.append(ContaBanco(nome, "inter", erp, conta_corrente=cc))
        if not contas:
            raise ConfigInvalida(f"{onde}: sem contas")
        bancos = {c.banco for c in contas}
        sicoob = _credencial_sicoob(e.get("sicoob"), ambiente, nome) if "sicoob" in bancos else None
        inter = _credencial_inter(e.get("inter"), nome) if "inter" in bancos else None
        empresas.append(Empresa(nome, tuple(contas), sicoob, inter))
    if not empresas:
        raise ConfigInvalida("sem empresas")
    pasta = _texto(d, "pasta", "arquivo")
    if ambiente == "producao":
        return Config(ambiente, pasta, tuple(empresas), _texto(d, "nuvem_email", "arquivo"),
                      _texto(d, "nuvem_senha", "arquivo"))
    return Config(ambiente, pasta, tuple(empresas))


def carregar(caminho) -> Config:
    try:
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ConfigInvalida(f"não consegui ler o arquivo ({type(e).__name__})") from None
    return de_dict(dados)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest -q tests/test_leitura_manha_config.py -p no:cacheprovider`
Esperado: `14 passed`.

- [ ] **Step 5: Commit**

```bash
git add leitura_manha/config.py tests/test_leitura_manha_config.py
git commit -m "leitura_manha: arquivo do servidor com credencial por empresa, conferido e sem segredo em mensagem" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: A leitura e a pré-marca (`leitura.py`)

**Files:**
- Create: `leitura_manha/leitura.py`
- Test: `tests/test_leitura_manha_leitura.py`

**Interfaces:**
- Consumes:
  - `config.Config`/`Empresa`/`ContaBanco` (Task 4), `extrato.*` (Task 3) e `transporte.ErroLeitura` (Task 1);
  - `pagamento_api.robo.FUSO_SP` (PR #203, `pagamento_api/robo.py:104`);
  - `tela_do_dia.agendados.Agendado.de_linha` (`tela_do_dia/agendados.py:55`), que levanta `ValueError` em linha sem valor ou dia;
  - `tela_do_dia.autenticar.autenticar(pendentes, movimentos, pendencias=(), lidas=(), falhas=None, hoje=None) -> dict[int, Autenticacao]` (`tela_do_dia/autenticar.py:355`);
  - `conciliacao.models.ErpAccount` (`conciliacao/models.py:75`), cujo `balance` é `Decimal | None`.
- Produces:
  - `SaldoLido(conta, fonte, empresa, valor: Decimal | None, motivo, hora: datetime)`, em que valor None exige motivo e valor presente o proíbe;
  - `ExtratoLido(conta, fonte, empresa, dia, saidas, entradas, ilegiveis, fora_do_dia, motivo)`;
  - `LeituraDosBancos(saldos, extratos, movimentos, lidas: set, falhas: dict)`;
  - `PreMarca(agendado_id, conta, prova, nota)`;
  - `dias_sp(agora) -> (hoje, ontem)`;
  - `ler_bancos(config, fabrica, ontem, agora) -> LeituraDosBancos`, em que a `fabrica` tem `.sicoob(empresa)` e `.inter(empresa, conta)`;
  - `ler_erp(ler, contas_do_arquivo, agora) -> list[SaldoLido]`;
  - `pre_marcas(linhas_em_aberto, leitura, hoje, log=print) -> list[PreMarca]`;
  - `ERP = "erp"`.

A regra do casamento é a de 29/10 e não é reescrita aqui. `autenticar` recebe `lidas` (as contas com extrato inteiro legível) e `falhas` ({conta: motivo}). O que ele devolve com `prova` vira pré-marca, e o que devolve só com `nota` vai junto, para a tela dizer por que não provou.

- [ ] **Step 1: Escrever o teste que falha**

```python
# -*- coding: utf-8 -*-
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from conciliacao.models import ErpAccount
from leitura_manha import config as cf
from leitura_manha import leitura as lt
from leitura_manha.transporte import ErroLeitura

ONTEM, HOJE = date(2026, 11, 26), date(2026, 11, 27)
HORA = datetime(2026, 11, 27, 10, 30, tzinfo=timezone.utc)


def agora():
    return HORA


def _cfg():
    return cf.de_dict({"ambiente": "producao", "nuvem_email": "r@e.com", "nuvem_senha": "s",
                       "pasta": "p", "empresas": [
        {"nome": "EMP A", "sicoob": {"client_id": "A", "cert": ["c", "k"]},
         "contas": [{"banco": "sicoob", "numero": 11, "conta_erp": "A1 - SICOOB"},
                    {"banco": "sicoob", "numero": 12, "conta_erp": "A2 - SICOOB"}]},
        {"nome": "EMP B", "sicoob": {"client_id": "B", "cert": ["c", "k"]},
         "inter": {"client_id": "i", "client_secret": "s", "cert": ["c", "k"]},
         "contas": [{"banco": "sicoob", "numero": 21, "conta_erp": "B1 - SICOOB"},
                    {"banco": "inter", "conta_erp": "B2 - INTER"}]}]})


def _ext(*linhas):
    return {"transacoes": list(linhas)}


def _deb(valor, desc, data="2026-11-26"):
    return {"tipo": "DEBITO", "valor": valor, "data": data, "descInfComplementar": desc}


class Sicoob:
    def __init__(self, saldos, extratos):
        self.saldos, self.extratos = saldos, extratos

    def saldo(self, numero):
        v = self.saldos[numero]
        if isinstance(v, Exception):
            raise v
        return v

    def extrato(self, numero, dia):
        assert dia == ONTEM
        v = self.extratos[numero]
        if isinstance(v, Exception):
            raise v
        return v


class Inter:
    def __init__(self, saldo, extrato):
        self._s, self._e = saldo, extrato

    def saldo(self):
        if isinstance(self._s, Exception):
            raise self._s
        return self._s

    def extrato(self, dia):
        return self._e


class Fabrica:
    def __init__(self, sicoob, inter=None):
        self._sicoob, self._inter = sicoob, inter

    def sicoob(self, empresa):
        c = self._sicoob[empresa.nome]
        if isinstance(c, Exception):
            raise c
        return c

    def inter(self, empresa, conta):
        return self._inter


def _tudo_bom():
    return Fabrica({"EMP A": Sicoob({11: {"saldo": Decimal("100.00")}, 12: {"saldo": 0}},
                                    {11: _ext(_deb("150,00", "OBRA X LT 10")), 12: _ext()}),
                    "EMP B": Sicoob({21: {"saldo": Decimal("5.50")}}, {21: _ext()})},
                   Inter({"disponivel": Decimal("7.00")},
                         {"transacoes": [{"tipoOperacao": "C", "valor": "1.00",
                                          "dataEntrada": "2026-11-26"}]}))


def _saldo(le, conta):
    (s,) = [s for s in le.saldos if s.conta == conta]
    return s


def test_tudo_lido():
    le = lt.ler_bancos(_cfg(), _tudo_bom(), ONTEM, agora)
    assert [(s.conta, s.valor) for s in le.saldos] == [
        ("A1 - SICOOB", Decimal("100.00")), ("A2 - SICOOB", Decimal("0.00")),
        ("B1 - SICOOB", Decimal("5.50")), ("B2 - INTER", Decimal("7.00"))]
    assert le.lidas == {"A1 - SICOOB", "A2 - SICOOB", "B1 - SICOOB", "B2 - INTER"}
    assert [m.valor for m in le.movimentos] == [Decimal("150.00")] and le.falhas == {}


def test_token_de_uma_empresa_caido_nao_derruba_a_outra_e_nao_vira_zero():
    f = _tudo_bom()
    f._sicoob["EMP A"] = Sicoob({11: ErroLeitura(None, "token recusado"),
                                 12: ErroLeitura(None, "token recusado")},
                                {11: ErroLeitura(None, "token recusado"),
                                 12: ErroLeitura(None, "token recusado")})
    le = lt.ler_bancos(_cfg(), f, ONTEM, agora)
    for conta in ("A1 - SICOOB", "A2 - SICOOB"):
        s = _saldo(le, conta)
        assert s.valor is None and "token recusado" in s.motivo
        assert conta in le.falhas and conta not in le.lidas
    assert _saldo(le, "B1 - SICOOB").valor == Decimal("5.50") and "B2 - INTER" in le.lidas


def test_fabrica_que_estoura_vira_motivo_de_cada_conta_da_empresa():
    f = _tudo_bom()
    f._sicoob["EMP A"] = KeyError("cert")
    le = lt.ler_bancos(_cfg(), f, ONTEM, agora)
    assert _saldo(le, "A1 - SICOOB").motivo == "Sicoob: erro inesperado (KeyError)"
    assert _saldo(le, "B1 - SICOOB").valor == Decimal("5.50")


def test_fabrica_da_empresa_e_chamada_uma_vez_mesmo_quando_falha():
    f = _tudo_bom()
    chamadas = []
    original = f.sicoob

    def contando(empresa):
        chamadas.append(empresa.nome)
        if empresa.nome == "EMP A":
            raise ErroLeitura(None, "token recusado")
        return original(empresa)
    f.sicoob = contando
    lt.ler_bancos(_cfg(), f, ONTEM, agora)
    assert chamadas == ["EMP A", "EMP B"]


def test_erro_inesperado_numa_conta_nao_para_as_seguintes():
    f = _tudo_bom()
    f._sicoob["EMP A"].saldos[11] = RuntimeError("bug")
    f._sicoob["EMP A"].extratos[11] = RuntimeError("bug")
    le = lt.ler_bancos(_cfg(), f, ONTEM, agora)
    assert _saldo(le, "A1 - SICOOB").valor is None
    assert _saldo(le, "A2 - SICOOB").valor == Decimal("0.00")
    assert le.falhas["A1 - SICOOB"] == "Sicoob: erro inesperado (RuntimeError)"


def test_saldo_lido_e_extrato_caido_sao_independentes():
    f = _tudo_bom()
    f._sicoob["EMP A"].extratos[11] = ErroLeitura(503, "fora")
    le = lt.ler_bancos(_cfg(), f, ONTEM, agora)
    assert _saldo(le, "A1 - SICOOB").valor == Decimal("100.00")
    assert le.falhas["A1 - SICOOB"] == "Sicoob respondeu HTTP 503"
    assert le.movimentos == []


def test_uma_linha_ilegivel_tira_a_conta_do_casamento():
    f = _tudo_bom()
    f._sicoob["EMP A"].extratos[11] = _ext(_deb("150,00", "OBRA X LT 10"),
                                           {"tipo": "lorem", "valor": "x", "data": "y"})
    le = lt.ler_bancos(_cfg(), f, ONTEM, agora)
    assert "A1 - SICOOB" not in le.lidas and "1 linha(s) ilegível(is)" in le.falhas["A1 - SICOOB"]
    assert le.movimentos == []
    (x,) = [x for x in le.extratos if x.conta == "A1 - SICOOB"]
    assert x.ilegiveis == 1 and x.motivo


def test_saldo_lido_sem_motivo_e_nao_lido_sem_motivo_sao_recusados():
    with pytest.raises(ValueError):
        lt.SaldoLido("A", "sicoob", "E", None, "", HORA)
    with pytest.raises(ValueError):
        lt.SaldoLido("A", "sicoob", "E", Decimal("1.00"), "não lido", HORA)


def test_erp_lido_sem_saldo_e_nao_lido_nunca_zero():
    contas = [ErpAccount("1", "A1 - SICOOB", balance=Decimal("99.9")),
              ErpAccount("2", "B1 - SICOOB", raw_balance="R$ ***", balance=None)]
    saida = lt.ler_erp(lambda: contas, ["A1 - SICOOB", "B1 - SICOOB", "B2 - INTER"], agora)
    por = {s.conta: s for s in saida}
    assert por["A1 - SICOOB"].valor == Decimal("99.90") and por["A1 - SICOOB"].fonte == "erp"
    assert por["B1 - SICOOB"].valor is None and "não mostrou" in por["B1 - SICOOB"].motivo
    assert por["B2 - INTER"].valor is None and "não encontrada" in por["B2 - INTER"].motivo


def test_erp_fora_marca_cada_conta_como_nao_lida():
    def cai():
        raise RuntimeError("porteiro do ERP desligado (Chrome central)")
    saida = lt.ler_erp(cai, ["A1 - SICOOB", "B2 - INTER"], agora)
    assert [(s.conta, s.valor) for s in saida] == [("A1 - SICOOB", None), ("B2 - INTER", None)]
    assert all("porteiro" in s.motivo for s in saida)


@pytest.mark.parametrize("agora_utc, hoje, ontem", [
    (datetime(2026, 11, 27, 10, 30, tzinfo=timezone.utc), date(2026, 11, 27), date(2026, 11, 26)),
    (datetime(2026, 11, 27, 2, 0, tzinfo=timezone.utc), date(2026, 11, 26), date(2026, 11, 25)),
    (datetime(2026, 1, 1, 2, 59, tzinfo=timezone.utc), date(2025, 12, 31), date(2025, 12, 30)),
    (datetime(2026, 3, 1, 3, 0, tzinfo=timezone.utc), date(2026, 3, 1), date(2026, 2, 28)),
])
def test_ontem_e_o_de_sao_paulo(agora_utc, hoje, ontem):
    assert lt.dias_sp(agora_utc) == (hoje, ontem)


def test_agora_sem_fuso_e_recusado():
    with pytest.raises(ValueError):
        lt.dias_sp(datetime(2026, 11, 27, 7, 30))


def _linha(id_, conta, valor, desc, dia="2026-11-26", **foto):
    return {"id": id_, "dia": dia, "conta": conta, "alvo": f"t{id_}", "lancamento_id": f"L{id_}",
            "favorecido": "FORNECEDOR TESTE", "valor": valor, "descricao": desc,
            "foto": {"descricao_colada": desc, **foto}}


def test_pre_marca_so_o_que_o_extrato_de_ontem_prova():
    le = lt.ler_bancos(_cfg(), _tudo_bom(), ONTEM, agora)
    linhas = [_linha(1, "A1 - SICOOB", "150.00", "OBRA X LT 10"),
              _linha(2, "A1 - SICOOB", "150.00", "OUTRA COISA"),
              _linha(3, "B1 - SICOOB", "150.00", "OBRA X LT 10")]
    marcas = {m.agendado_id: m for m in lt.pre_marcas(linhas, le, HOJE)}
    assert marcas[1].prova.startswith("banco — Sicoob extrato (API) 26/11: mesmo valor e descrição")
    assert marcas[2].prova == "" and "mesmo valor" in marcas[2].nota
    assert marcas[3].prova == "" and marcas[3].nota == "nada no banco ainda"


def test_conta_nao_lida_nunca_pre_marca():
    f = _tudo_bom()
    f._sicoob["EMP A"].extratos[11] = _ext(_deb("150,00", "OBRA X LT 10"),
                                           {"tipo": "lorem", "valor": "x", "data": "y"})
    le = lt.ler_bancos(_cfg(), f, ONTEM, agora)
    (m,) = lt.pre_marcas([_linha(1, "A1 - SICOOB", "150.00", "OBRA X LT 10")], le, HOJE)
    assert m.prova == "" and m.nota.startswith("banco não lido: Sicoob: 1 linha(s) ilegível(is)")


def test_conta_fora_do_arquivo_nao_aparece_e_linha_ruim_e_contada():
    le = lt.ler_bancos(_cfg(), _tudo_bom(), ONTEM, agora)
    avisos = []
    ruim = {"id": 9, "dia": "", "valor": None}
    marcas = lt.pre_marcas([_linha(5, "OUTRA CONTA - CAIXA", "150.00", "OBRA X LT 10"), ruim],
                           le, HOJE, log=avisos.append)
    assert marcas == [] and avisos == ["  1 agendado(s) em aberto ilegível(is) na nuvem: ficaram fora"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest -q tests/test_leitura_manha_leitura.py -p no:cacheprovider`
Esperado: `ImportError: cannot import name 'leitura' from 'leitura_manha'`.

- [ ] **Step 3: Implementar**

```python
# -*- coding: utf-8 -*-
"""A leitura das 07:30, sem rede própria: os clientes chegam pela `fabrica`.

Três regras de dinheiro moram aqui:
1. saldo que não se leu é `valor=None` com motivo — NUNCA zero;
2. a falha de uma conta (ou do token de uma empresa) não derruba as outras:
   cada conta é lida no seu próprio `try`, e o motivo vai para a nuvem;
3. a conta só entra no casamento (`lidas`) quando o extrato de ontem veio
   INTEIRO legível; senão vai para `falhas` e nenhum agendado dela é
   pré-marcado ("banco não lido: ...").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Callable

from pagamento_api.robo import FUSO_SP
from tela_do_dia.agendados import Agendado
from tela_do_dia.autenticar import autenticar

from . import extrato as ext
from .transporte import ErroLeitura

ERP = "erp"


@dataclass(frozen=True)
class SaldoLido:
    conta: str
    fonte: str                  # "sicoob" | "inter" | "erp"
    empresa: str
    valor: Decimal | None       # None = não lido (motivo diz por quê), NUNCA zero
    motivo: str
    hora: datetime

    def __post_init__(self):
        if (self.valor is None) != bool(self.motivo):
            raise ValueError("saldo lido não tem motivo; saldo não lido tem de ter")


@dataclass(frozen=True)
class ExtratoLido:
    conta: str
    fonte: str
    empresa: str
    dia: date
    saidas: int = 0
    entradas: int = 0
    ilegiveis: int = 0
    fora_do_dia: int = 0
    motivo: str = ""            # "" = lido inteiro e usado no casamento


@dataclass
class LeituraDosBancos:
    saldos: list = field(default_factory=list)
    extratos: list = field(default_factory=list)
    movimentos: list = field(default_factory=list)
    lidas: set = field(default_factory=set)
    falhas: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PreMarca:
    agendado_id: int
    conta: str
    prova: str                  # "" = não provou (a `nota` diz o que o banco disse)
    nota: str


def dias_sp(agora: datetime) -> tuple[date, date]:
    """(hoje, ontem) no fuso de São Paulo. `agora` tem de ter fuso: o relógio
    do servidor pode estar em UTC, e às 00:30 UTC ainda é ontem em SP."""
    if agora.tzinfo is None:
        raise ValueError("agora sem fuso")
    hoje = agora.astimezone(FUSO_SP).date()
    return hoje, hoje - timedelta(days=1)


def motivo_de(e: Exception, banco: str) -> str:
    if isinstance(e, ErroLeitura):
        if e.status is None:
            return f"{banco}: {e.corpo}"[:200]
        if e.status == 200:
            return f"{banco}: {e.corpo[:120]}"
        return f"{banco} respondeu HTTP {e.status}"
    if isinstance(e, ext.ExtratoIlegivel):
        return f"{banco}: {e}"[:200]
    return f"{banco}: erro inesperado ({type(e).__name__})"


class _Cache:
    """Um cliente por empresa (Sicoob) ou por conta (Inter); falha da fábrica
    vira o motivo de cada conta daquela empresa, sem levantar."""

    def __init__(self, fabrica):
        self._f, self._sicoob = fabrica, {}

    def sicoob(self, empresa):
        if empresa.nome not in self._sicoob:
            try:
                self._sicoob[empresa.nome] = self._f.sicoob(empresa)
            except Exception as e:  # noqa: BLE001 — vira motivo, não derruba
                self._sicoob[empresa.nome] = e
        c = self._sicoob[empresa.nome]
        if isinstance(c, Exception):
            raise c
        return c


def _uma_conta(le: LeituraDosBancos, cache: _Cache, fabrica, empresa, conta, ontem, agora):
    banco = "Sicoob" if conta.banco == "sicoob" else "Inter"
    try:
        if conta.banco == "sicoob":
            cliente = cache.sicoob(empresa)
            ler_saldo, ler_extrato = (lambda: cliente.saldo(conta.numero),
                                      lambda: cliente.extrato(conta.numero, ontem))
            do_saldo, do_extrato = ext.saldo_sicoob, ext.movimentos_sicoob
        else:
            cliente = fabrica.inter(empresa, conta)
            ler_saldo, ler_extrato = cliente.saldo, (lambda: cliente.extrato(ontem))
            do_saldo, do_extrato = ext.saldo_inter, ext.movimentos_inter
    except Exception as e:  # noqa: BLE001
        m = motivo_de(e, banco)
        le.saldos.append(SaldoLido(conta.conta_erp, conta.banco, empresa.nome, None, m, agora()))
        le.extratos.append(ExtratoLido(conta.conta_erp, conta.banco, empresa.nome, ontem, motivo=m))
        le.falhas[conta.conta_erp] = m
        return
    try:
        valor, m = do_saldo(ler_saldo())
    except Exception as e:  # noqa: BLE001
        valor, m = None, motivo_de(e, banco)
    le.saldos.append(SaldoLido(conta.conta_erp, conta.banco, empresa.nome, valor, m, agora()))
    try:
        x = do_extrato(ler_extrato(), conta.conta_erp, ontem)
    except Exception as e:  # noqa: BLE001
        m = motivo_de(e, banco)
        le.extratos.append(ExtratoLido(conta.conta_erp, conta.banco, empresa.nome, ontem, motivo=m))
        le.falhas[conta.conta_erp] = m
        return
    motivo = ""
    if x.ilegiveis:
        motivo = (f"{banco}: {x.ilegiveis} linha(s) ilegível(is) no extrato — "
                  + "; ".join(x.motivos))[:200]
        le.falhas[conta.conta_erp] = motivo
    else:
        le.lidas.add(conta.conta_erp)
        le.movimentos.extend(x.movimentos)
    le.extratos.append(ExtratoLido(conta.conta_erp, conta.banco, empresa.nome, ontem,
                                   len(x.movimentos), x.entradas, x.ilegiveis, x.fora_do_dia,
                                   motivo))


def ler_bancos(config, fabrica, ontem: date, agora: Callable[[], datetime]) -> LeituraDosBancos:
    """Saldo e extrato de ontem de cada conta do arquivo, uma de cada vez."""
    le, cache = LeituraDosBancos(), _Cache(fabrica)
    for empresa in config.empresas:
        for conta in empresa.contas:
            _uma_conta(le, cache, fabrica, empresa, conta, ontem, agora)
    return le


def ler_erp(ler: Callable[[], list], contas_do_arquivo, agora: Callable[[], datetime]) -> list:
    """Saldo de cada conta ATIVA do ERP (`ler` = `ler_saldos` pelo porteiro).
    Falha do ERP: cada conta do arquivo sai "não lido" com o motivo."""
    hora = agora()
    try:
        contas = list(ler())
    except Exception as e:  # noqa: BLE001 — o ERP fora não derruba os bancos
        m = f"ERP não lido: {str(e).strip().splitlines()[0][:150] if str(e).strip() else type(e).__name__}"
        return [SaldoLido(c, ERP, "", None, m, hora) for c in contas_do_arquivo]
    saida, vistas = [], set()
    for c in contas:
        vistas.add(c.name)
        if isinstance(c.balance, Decimal):
            saida.append(SaldoLido(c.name, ERP, "", c.balance.quantize(ext.CENTAVO), "", hora))
        else:
            bruto = f" (tela: {c.raw_balance[:30]!r})" if c.raw_balance else ""
            saida.append(SaldoLido(c.name, ERP, "", None, "o ERP não mostrou o saldo" + bruto, hora))
    for nome in contas_do_arquivo:
        if nome not in vistas:
            saida.append(SaldoLido(nome, ERP, "", None, "conta não encontrada entre as ativas do ERP",
                                   hora))
    return saida


def pre_marcas(linhas_em_aberto, leitura: LeituraDosBancos, hoje: date,
               log=print) -> list[PreMarca]:
    """O casamento de ontem pela regra pura de 29/10 (`autenticar`): só
    PRÉ-MARCA. Linha da nuvem ilegível fica fora (contada no log)."""
    pendentes, ruins = [], 0
    for linha in linhas_em_aberto:
        try:
            pendentes.append(Agendado.de_linha(linha))
        except (ValueError, KeyError, TypeError):
            ruins += 1
    if ruins:
        log(f"  {ruins} agendado(s) em aberto ilegível(is) na nuvem: ficaram fora")
    conta_de = {a.id: a.conta for a in pendentes}
    res = autenticar(pendentes, leitura.movimentos, lidas=leitura.lidas,
                     falhas=leitura.falhas, hoje=hoje)
    return [PreMarca(i, conta_de[i], a.prova, a.nota) for i, a in sorted(res.items())
            if a.prova or a.nota]
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest -q tests/test_leitura_manha_leitura.py -p no:cacheprovider`
Esperado: `18 passed`.

- [ ] **Step 5: Commit**

```bash
git add leitura_manha/leitura.py tests/test_leitura_manha_leitura.py
git commit -m "leitura_manha: leitura conta a conta (falha isolada, nao lido nunca zero, ontem de Sao Paulo) e pre-marca pela regra de 29/10" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: As tabelas na nuvem (migration)

**Files:**
- Create: `supabase/migrations/20261127100000_leitura_da_manha.sql`
- Test: `tests/test_leitura_manha_sql.py`
- Create (na raiz da pasta de trabalho, FORA do repo, só no Step 7): `APLICAR NO SUPABASE - 2026-11-27 leitura da manha.sql`, cópia idêntica.

**Interfaces:**
- Consumes:
  - `privado.e_ativo()`;
  - `privado.tem_papel(text)` e `privado.hoje()`, da migration `20261126100000_pagamento_pela_api.sql`;
  - `public.pagamento_agendado(id)`, de `20261022100000_pagamentos_do_dia_na_nuvem.sql`.
- Produces as tabelas `public.saldo_lido`, `public.extrato_lido` e `public.pre_marca_banco`, com as colunas que a Task 7 grava:
  - `saldo_lido`: `rodada`, `conta`, `fonte`, `empresa`, `valor`, `motivo`, `lido_em`;
  - `extrato_lido`: `rodada`, `conta`, `fonte`, `empresa`, `dia_extrato`, `saidas`, `entradas`, `ilegiveis`, `fora_do_dia`, `motivo`;
  - `pre_marca_banco`: `rodada`, `dia_extrato`, `agendado_id`, `conta`, `prova`, `nota`.

  O banco carimba `dia` (o de SP), `quem` e `quando`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# -*- coding: utf-8 -*-
"""A estrutura da leitura das 07:30, lida da migration (sem Postgres — o mesmo
jeito de `test_pagamento_api_sql.py`). O comportamento se prova no banco com o
roteiro begin; ...; rollback; da Task 7, depois de aplicar."""
import re
from pathlib import Path

_SQL = (Path(__file__).resolve().parent.parent / "supabase" / "migrations"
        / "20261127100000_leitura_da_manha.sql")
TABELAS = ("saldo_lido", "extrato_lido", "pre_marca_banco")


def _texto() -> str:
    sql = re.sub(r"--[^\n]*", " ", _SQL.read_text(encoding="utf-8"))
    return " ".join(sql.split()).lower()


def test_cria_as_tabelas_com_rls_e_so_o_robo_grava():
    t = _texto()
    for nome in TABELAS:
        assert f"create table if not exists public.{nome} (" in t
        assert f"alter table public.{nome} enable row level security" in t
        assert (f"create policy {nome}_le on public.{nome} for select to authenticated "
                "using ((select privado.e_ativo()))") in t
        assert (f"create policy {nome}_grava on public.{nome} for insert to authenticated with check ( "
                "(select privado.e_ativo()) and (select privado.tem_papel('robo')) "
                "and quem = (select auth.uid()))") in t


def test_ninguem_altera_nem_apaga():
    t = _texto()
    assert ("grant select, insert on table public.saldo_lido, public.extrato_lido, "
            "public.pre_marca_banco to authenticated") in t
    assert not re.search(r"grant[^;]*\b(update|delete|truncate)\b", t)
    assert "for update" not in t and "for delete" not in t


def test_saldo_nao_lido_nunca_vira_zero_no_banco():
    t = _texto()
    assert "valor numeric(14,2)," in t           # sem not null e sem default 0
    assert "constraint saldo_lido_nao_lido_tem_motivo check ((valor is null) = (length(trim(motivo)) > 0))" in t
    assert "default 0" not in t.split("create table if not exists public.saldo_lido")[1].split(");")[0]


def test_pre_marca_nao_e_resposta():
    t = _texto()
    assert "agendado_id bigint not null references public.pagamento_agendado (id)" in t
    assert "agendado_resposta" not in t


def test_linha_ilegivel_tem_motivo_e_fonte_conhecida():
    t = _texto()
    assert "check (ilegiveis = 0 or length(trim(motivo)) > 0)" in t
    assert "check (fonte in ('sicoob', 'inter', 'erp'))" in t


def test_transacao_e_recarga_do_esquema():
    t = _texto()
    assert t.startswith("begin;") and t.rstrip().endswith("commit;")
    assert "notify pgrst, 'reload schema'" in t
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest -q tests/test_leitura_manha_sql.py -p no:cacheprovider`
Esperado: `FileNotFoundError` para `20261127100000_leitura_da_manha.sql`.

- [ ] **Step 3: Escrever a migration**

```sql
-- ---------------------------------------------- leitura das 07:30 (E1a)
-- Spec 2026-11-27-aba-pagamentos-no-portal-design.md, D2/D3. O servidor lê
-- saldo e extrato de ontem pela API (Sicoob e Inter), o saldo do ERP pelo
-- porteiro, e casa o extrato com os agendados em aberto (só PRÉ-MARCA). Grava
-- aqui com o usuário de papel `robo`. Tudo só ACRESCENTA: sem update/delete.
--
--   saldo_lido      -> um saldo por conta e fonte (sicoob|inter|erp) por rodada;
--                      valor NULL = não lido, e então o motivo é obrigatório.
--   extrato_lido    -> o resumo do extrato de ontem de cada conta (contagens).
--   pre_marca_banco -> o que o banco provou de cada agendado em aberto. NÃO é
--                      resposta: "Pago" continua em agendado_resposta, pela pessoa.
--
-- Depende de 20261126100000_pagamento_pela_api.sql (papel robo,
-- privado.tem_papel, privado.hoje) e de 20261022100000 (pagamento_agendado).
-- Idempotente. Tudo numa transação.

begin;
set local lock_timeout = '5s';

create table if not exists public.saldo_lido (
  id        bigint generated always as identity primary key,
  rodada    uuid not null,
  dia       date not null default privado.hoje(),
  conta     text not null,
  fonte     text not null,
  empresa   text not null default '',
  valor     numeric(14,2),
  motivo    text not null default '',
  lido_em   timestamptz not null,
  quem      uuid not null default auth.uid() references auth.users (id),
  quando    timestamptz not null default now(),
  constraint saldo_lido_fonte check (fonte in ('sicoob', 'inter', 'erp')),
  -- não lido nunca vira zero: ou tem valor e nenhum motivo, ou não tem valor e diz por quê
  constraint saldo_lido_nao_lido_tem_motivo check ((valor is null) = (length(trim(motivo)) > 0)),
  constraint saldo_lido_tamanho check (length(conta) between 1 and 200
    and length(empresa) <= 200 and length(motivo) <= 200)
);
create index if not exists saldo_lido_conta_idx on public.saldo_lido (conta, fonte, lido_em desc);
create index if not exists saldo_lido_dia_idx on public.saldo_lido (dia);

create table if not exists public.extrato_lido (
  id           bigint generated always as identity primary key,
  rodada       uuid not null,
  dia          date not null default privado.hoje(),
  conta        text not null,
  fonte        text not null,
  empresa      text not null default '',
  dia_extrato  date not null,
  saidas       integer not null default 0,
  entradas     integer not null default 0,
  ilegiveis    integer not null default 0,
  fora_do_dia  integer not null default 0,
  motivo       text not null default '',
  quem         uuid not null default auth.uid() references auth.users (id),
  quando       timestamptz not null default now(),
  constraint extrato_lido_fonte check (fonte in ('sicoob', 'inter')),
  constraint extrato_lido_contagens check (saidas >= 0 and entradas >= 0
    and ilegiveis >= 0 and fora_do_dia >= 0),
  -- linha ilegível tira a conta do casamento, e o motivo diz isso
  constraint extrato_lido_ilegivel_tem_motivo check (ilegiveis = 0 or length(trim(motivo)) > 0),
  constraint extrato_lido_tamanho check (length(conta) between 1 and 200
    and length(empresa) <= 200 and length(motivo) <= 200)
);
create index if not exists extrato_lido_dia_idx on public.extrato_lido (dia);

create table if not exists public.pre_marca_banco (
  id           bigint generated always as identity primary key,
  rodada       uuid not null,
  dia          date not null default privado.hoje(),
  dia_extrato  date not null,
  agendado_id  bigint not null references public.pagamento_agendado (id),
  conta        text not null,
  prova        text not null default '',
  nota         text not null default '',
  quem         uuid not null default auth.uid() references auth.users (id),
  quando       timestamptz not null default now(),
  constraint pre_marca_banco_diz_algo check (length(prova) > 0 or length(nota) > 0),
  constraint pre_marca_banco_tamanho check (length(conta) between 1 and 200
    and length(prova) <= 300 and length(nota) <= 300)
);
create index if not exists pre_marca_banco_agendado_idx on public.pre_marca_banco (agendado_id, id desc);

-- ------------------------------------------------------- permissões e RLS
revoke all on table public.saldo_lido, public.extrato_lido, public.pre_marca_banco
  from anon, authenticated;
grant select, insert on table public.saldo_lido, public.extrato_lido, public.pre_marca_banco
  to authenticated;

alter table public.saldo_lido      enable row level security;
alter table public.extrato_lido    enable row level security;
alter table public.pre_marca_banco enable row level security;

drop policy if exists saldo_lido_le on public.saldo_lido;
create policy saldo_lido_le on public.saldo_lido for select to authenticated using ((select privado.e_ativo()));
drop policy if exists saldo_lido_grava on public.saldo_lido;
create policy saldo_lido_grava on public.saldo_lido for insert to authenticated with check (
  (select privado.e_ativo()) and (select privado.tem_papel('robo'))
  and quem = (select auth.uid()));

drop policy if exists extrato_lido_le on public.extrato_lido;
create policy extrato_lido_le on public.extrato_lido for select to authenticated using ((select privado.e_ativo()));
drop policy if exists extrato_lido_grava on public.extrato_lido;
create policy extrato_lido_grava on public.extrato_lido for insert to authenticated with check (
  (select privado.e_ativo()) and (select privado.tem_papel('robo'))
  and quem = (select auth.uid()));

drop policy if exists pre_marca_banco_le on public.pre_marca_banco;
create policy pre_marca_banco_le on public.pre_marca_banco for select to authenticated using ((select privado.e_ativo()));
drop policy if exists pre_marca_banco_grava on public.pre_marca_banco;
create policy pre_marca_banco_grava on public.pre_marca_banco for insert to authenticated with check (
  (select privado.e_ativo()) and (select privado.tem_papel('robo'))
  and quem = (select auth.uid()));

notify pgrst, 'reload schema';

commit;

-- Reversão (só com autorização do dono):
--   drop table if exists public.pre_marca_banco, public.extrato_lido, public.saldo_lido;
```

- [ ] **Step 4: Rodar e ver passar, junto com as varreduras do repo**

Run: `python -m pytest -q tests/test_leitura_manha_sql.py tests/test_rls_supabase.py tests/test_pagamento_api_sql.py tests/test_pagamentos_do_dia_sql.py tests/test_tela_do_dia_controle_sql.py -p no:cacheprovider`
Esperado: `6 passed` no arquivo novo e todo o resto verde. No rascunho, as quatro varreduras deram 32 passed com a migration nova ao lado.

- [ ] **Step 5: Revisão independente do SQL ANTES de qualquer aplicação**

Despache o agente `revisor-sql-supabase` com o caminho da migration e esta pergunta: "Confira RLS com `privado.e_ativo()`, a ordem de aplicação (depende de 20261126100000), a reversão, a idempotência e dado real em arquivo público. O robô é o único que grava; o 'não lido' nunca pode virar zero." Os achados entram na migration, e o Step 1 e o Step 4 rodam de novo.

- [ ] **Step 6: Commit**

```bash
git add supabase/migrations/20261127100000_leitura_da_manha.sql tests/test_leitura_manha_sql.py
git commit -m "nuvem: saldo_lido, extrato_lido e pre_marca_banco (so ler e acrescentar; so o papel robo grava; nao lido nunca vira zero)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Aplicar no banco, SÓ com o "pode" do Gustavo no chat e DEPOIS da 20261126100000.** Copie a migration para `APLICAR NO SUPABASE - 2026-11-27 leitura da manha.sql` na raiz e, com o ok dele, rode `supabase db query --linked -f "APLICAR NO SUPABASE - 2026-11-27 leitura da manha.sql"`.

  Depois, faça a prova de comportamento DENTRO de `begin; ... rollback;` (nada fica gravado), com um `savepoint` por letra. Cada papel é simulado com `set local role authenticated; set local request.jwt.claims = '{"sub":"<uuid>","role":"authenticated"}';`:
  - (a) o robô grava um `saldo_lido` com `valor 10.00, motivo ''`: aceita;
  - (b) o robô grava `valor null, motivo ''`: recusa por `saldo_lido_nao_lido_tem_motivo`;
  - (c) o robô grava `valor 0, motivo 'x'`: recusa pela mesma constraint;
  - (d) um operador ativo grava em `saldo_lido`: recusa da RLS;
  - (e) o robô grava `pre_marca_banco` com um `agendado_id` que não existe: recusa da FK;
  - (f) o robô grava um `extrato_lido` com `ilegiveis 2, motivo ''`: recusa;
  - (g) qualquer conta tenta `update`/`delete` numa das três: recusa (sem grant);
  - (h) uma conta pendente (não ativa) faz `select`: zero linhas.

  Use os uuids de contas de teste, e anote o resultado de cada letra no PR. **Este roteiro NÃO foi rodado no rascunho**, porque lá não havia Postgres nem acesso ao Supabase.

---

### Task 7: Gravar na nuvem (`nuvem_leitura.py`)

**Files:**
- Create: `leitura_manha/nuvem_leitura.py`
- Test: `tests/test_leitura_manha_nuvem.py`

**Interfaces:**
- Consumes:
  - `nuvem.rest.ler(tabela, token, *, colunas="*", filtro="") -> list` (`nuvem/rest.py:218`);
  - `nuvem.rest.inserir(tabela, token, linhas, *, devolver=True) -> list` (`nuvem/rest.py:226`);
  - `nuvem.rest.ErroDaNuvem`;
  - a view `public.agendado_em_aberto` (`20261022100000`, linha 142);
  - `leitura.SaldoLido`/`ExtratoLido`/`PreMarca` (Task 5).
- Produces:
  - `em_aberto(token) -> list[dict]`, que levanta `LeituraCortada` com 1000 linhas ou mais;
  - `gravar(token, rodada: str, ontem: date, saldos, extratos, marcas) -> {tabela: n}`, que levanta `NaoGravou` com linha a menos;
  - `linhas_de_saldo`, `linhas_de_extrato` e `linhas_de_pre_marca`;
  - as constantes `SALDO`, `EXTRATO`, `PRE_MARCA` e `TETO_DE_LINHAS`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# -*- coding: utf-8 -*-
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from leitura_manha import leitura as lt
from leitura_manha import nuvem_leitura as nl

HORA = datetime(2026, 11, 27, 10, 30, tzinfo=timezone.utc)
ONTEM = date(2026, 11, 26)


class RestFalso:
    def __init__(self, faltar=None, linhas=()):
        self.gravado, self.lido, self.faltar, self.linhas = {}, [], faltar, list(linhas)

    def inserir(self, tabela, token, linhas, devolver=True):
        self.gravado[tabela] = linhas
        return linhas[:-1] if tabela == self.faltar else linhas

    def ler(self, tabela, token, colunas="*", filtro=""):
        self.lido.append((tabela, filtro))
        return self.linhas


@pytest.fixture
def rest(monkeypatch):
    falso = RestFalso()
    monkeypatch.setattr(nl.rest, "inserir", falso.inserir)
    monkeypatch.setattr(nl.rest, "ler", falso.ler)
    return falso


SALDOS = [lt.SaldoLido("A", "sicoob", "E", Decimal("10.5"), "", HORA),
          lt.SaldoLido("B", "erp", "", None, "ERP não lido: porteiro", HORA)]
EXTRATOS = [lt.ExtratoLido("A", "sicoob", "E", ONTEM, 1, 2, 0, 0, "")]
MARCAS = [lt.PreMarca(7, "A", "banco — x", "")]


def test_grava_as_tres_tabelas_e_so_elas(rest):
    r = nl.gravar("TOK", "r-1", ONTEM, SALDOS, EXTRATOS, MARCAS)
    assert r == {"saldo_lido": 2, "extrato_lido": 1, "pre_marca_banco": 1}
    assert set(rest.gravado) == {"saldo_lido", "extrato_lido", "pre_marca_banco"}
    assert "agendado_resposta" not in rest.gravado


def test_nao_lido_vai_como_null_e_dinheiro_como_texto(rest):
    nl.gravar("TOK", "r-1", ONTEM, SALDOS, [], [])
    a, b = rest.gravado["saldo_lido"]
    assert a["valor"] == "10.50" and a["motivo"] == "" and a["lido_em"] == "2026-11-27T10:30:00+00:00"
    assert b["valor"] is None and b["motivo"] == "ERP não lido: porteiro"
    assert "quem" not in a and "quando" not in a


def test_pre_marca_leva_o_dia_do_extrato(rest):
    nl.gravar("TOK", "r-1", ONTEM, [], [], MARCAS)
    (m,) = rest.gravado["pre_marca_banco"]
    assert m == {"rodada": "r-1", "dia_extrato": "2026-11-26", "agendado_id": 7, "conta": "A",
                 "prova": "banco — x", "nota": ""}


def test_linha_a_menos_e_nao_gravou(rest):
    rest.faltar = "saldo_lido"
    with pytest.raises(nl.NaoGravou):
        nl.gravar("TOK", "r-1", ONTEM, SALDOS, EXTRATOS, MARCAS)


def test_float_no_dinheiro_e_recusado():
    with pytest.raises(TypeError):
        nl._dinheiro(10.5)


def test_em_aberto_no_teto_falha_fechado(rest):
    rest.linhas = [{}] * nl.TETO_DE_LINHAS
    with pytest.raises(nl.LeituraCortada):
        nl.em_aberto("TOK")
    rest.linhas = [{"id": 1}]
    assert nl.em_aberto("TOK") == [{"id": 1}]
    assert rest.lido[-1] == ("agendado_em_aberto", "order=dia.asc,id.asc")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest -q tests/test_leitura_manha_nuvem.py -p no:cacheprovider`
Esperado: `ImportError: cannot import name 'nuvem_leitura' from 'leitura_manha'`.

- [ ] **Step 3: Implementar**

```python
# -*- coding: utf-8 -*-
"""O lado da nuvem da leitura das 07:30 (migration 20261127100000_leitura_da_manha.sql).

Só LÊ `agendado_em_aberto` e só ACRESCENTA em `saldo_lido`, `extrato_lido` e
`pre_marca_banco`, com o usuário de papel `robo` (a RLS recusa qualquer outro).
Nunca escreve em `agendado_resposta`: pré-marcar não é responder.
O app não manda `quem`/`quando`: o banco carimba.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from nuvem import rest

EM_ABERTO = "agendado_em_aberto"
SALDO, EXTRATO, PRE_MARCA = "saldo_lido", "extrato_lido", "pre_marca_banco"
#: Teto padrão de linhas por leitura do PostgREST (max_rows do Supabase).
TETO_DE_LINHAS = 1000


class NaoGravou(rest.ErroDaNuvem):
    """O banco respondeu sem devolver as linhas pedidas."""


class LeituraCortada(rest.ErroDaNuvem):
    """A leitura bateu no teto do PostgREST: pode ter ficado agendado de fora."""


def em_aberto(token: str) -> list[dict]:
    linhas = rest.ler(EM_ABERTO, token, filtro="order=dia.asc,id.asc")
    if len(linhas) >= TETO_DE_LINHAS:
        raise LeituraCortada(f"{EM_ABERTO}: {len(linhas)} linhas, pode ter cortado")
    return linhas


def _dinheiro(v: Decimal | None) -> str | None:
    if v is None:
        return None
    if not isinstance(v, Decimal):
        raise TypeError(f"dinheiro em {type(v).__name__}: use Decimal")
    return str(v.quantize(Decimal("0.01"), ROUND_HALF_UP))


def _gravar(tabela: str, token: str, linhas: list[dict]) -> int:
    if not linhas:
        return 0
    gravadas = rest.inserir(tabela, token, linhas) or []
    if len(gravadas) != len(linhas):
        raise NaoGravou(f"{tabela}: o banco devolveu {len(gravadas)} de {len(linhas)} linha(s)")
    return len(gravadas)


def linhas_de_saldo(rodada: str, saldos) -> list[dict]:
    return [{"rodada": rodada, "conta": s.conta[:200], "fonte": s.fonte,
             "empresa": s.empresa[:200], "valor": _dinheiro(s.valor),
             "motivo": s.motivo[:200], "lido_em": s.hora.isoformat()} for s in saldos]


def linhas_de_extrato(rodada: str, extratos) -> list[dict]:
    return [{"rodada": rodada, "conta": x.conta[:200], "fonte": x.fonte,
             "empresa": x.empresa[:200], "dia_extrato": x.dia.isoformat(),
             "saidas": x.saidas, "entradas": x.entradas, "ilegiveis": x.ilegiveis,
             "fora_do_dia": x.fora_do_dia, "motivo": x.motivo[:200]} for x in extratos]


def linhas_de_pre_marca(rodada: str, ontem, marcas) -> list[dict]:
    return [{"rodada": rodada, "dia_extrato": ontem.isoformat(), "agendado_id": int(m.agendado_id),
             "conta": m.conta[:200], "prova": m.prova[:300], "nota": m.nota[:300]}
            for m in marcas]


def gravar(token: str, rodada: str, ontem, saldos, extratos, marcas) -> dict:
    """Grava as três; devolve {tabela: linhas}. Linha a menos levanta NaoGravou."""
    return {SALDO: _gravar(SALDO, token, linhas_de_saldo(rodada, saldos)),
            EXTRATO: _gravar(EXTRATO, token, linhas_de_extrato(rodada, extratos)),
            PRE_MARCA: _gravar(PRE_MARCA, token, linhas_de_pre_marca(rodada, ontem, marcas))}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest -q tests/test_leitura_manha_nuvem.py -p no:cacheprovider`
Esperado: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add leitura_manha/nuvem_leitura.py tests/test_leitura_manha_nuvem.py
git commit -m "leitura_manha: grava saldos, extratos e pre-marcas na nuvem (linha a menos e erro; nunca agendado_resposta)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: A CLI, o porteiro, o Agendador e os ensaios nos Sandboxes

**Files:**
- Create: `leitura_manha/rodar.py`
- Create: `ferramentas/leitura_manha/registrar_leitura_manha.ps1`
- Test: `tests/test_leitura_manha_rodar.py`

**Interfaces:**
- Consumes:
  - tudo das Tasks 1 a 7;
  - `pagamento_api.robo.trava_da_rodada(pasta)` (`pagamento_api/robo.py:127`), um gerenciador de contexto que devolve `bool`;
  - `erp.sessao.central_ligado()` (`erp/sessao.py:413`), que levanta `ErpErro` quando o `acessos.json` está estragado;
  - `tela_do_dia.erp_do_dia.ler_saldos(config, api, *, central_ligado=None, logar=None, esquecer=None, log=print, diag=None)` (`tela_do_dia/erp_do_dia.py:98`);
  - `nuvem.contas_novas.API_BASE`/`LEGACY_BASE` (o mesmo recurso de `ferramentas/sonda.py:_ConfigDoErp`);
  - `conciliacao.errors.ErpError` e `nuvem.rest.entrar(email, senha) -> dict`.
- Produces:
  - `main(argv=None) -> int` (0 = rodou; 1 = não gravou na nuvem; 2 = uso ou arquivo ruim);
  - `rodada(cfg, *, fabrica=None, entrar=None, nuvem=nl, ler_erp=None, agora=agora_utc, log=print) -> int`;
  - `ensaio_sandbox(dados, *, sessao=None, agora=agora_utc, log=print) -> LeituraDosBancos`;
  - `credencial_inter_da_pasta(pasta) -> dict`;
  - `ler_erp_pelo_porteiro(*, central=None, ler_saldos=None, log=print) -> list[ErpAccount]`;
  - `class Fabrica(cfg, sessao=None)`.

`ler_erp_pelo_porteiro` pergunta pelo porteiro ANTES e passa ao `ler_saldos` um `central_ligado` que LEVANTA quando o central está desligado, em vez de devolver False. Assim o `ler_saldos` nunca entra no ramo "central desligado", que usaria a aba do app (que o servidor não tem). E o `Sessao.logar("", "")` dentro dele não tem credencial para login HTTP.

- [ ] **Step 1: Escrever o teste que falha**

```python
# -*- coding: utf-8 -*-
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from falsos_leitura_manha import Resp, SessaoFalsa
from test_leitura_manha_leitura import _cfg, _tudo_bom

from conciliacao.errors import ErpError
from conciliacao.models import ErpAccount
from leitura_manha import config as cf
from leitura_manha import rodar

HORA = datetime(2026, 11, 27, 10, 30, tzinfo=timezone.utc)


def test_erp_desligado_nao_chama_ler_saldos():
    chamou = []
    with pytest.raises(ErpError, match="porteiro"):
        rodar.ler_erp_pelo_porteiro(central=lambda: False,
                                    ler_saldos=lambda *a, **k: chamou.append(1))
    assert chamou == []


def test_erp_ligado_passa_um_central_que_nunca_diz_desligado():
    vistos = []

    def ler_saldos(config, api, *, central_ligado, log):
        vistos.append((api, config.erp["api_base"].startswith("https://"), central_ligado()))
        return [ErpAccount("1", "A1 - SICOOB", balance=Decimal("1.00"))]
    estado = iter([True, False])
    with pytest.raises(ErpError):   # o porteiro caiu entre a 1ª pergunta e a de dentro
        rodar.ler_erp_pelo_porteiro(central=lambda: next(estado), ler_saldos=ler_saldos)
    contas = rodar.ler_erp_pelo_porteiro(central=lambda: True, ler_saldos=ler_saldos)
    assert contas[0].name == "A1 - SICOOB" and vistos == [(None, True, True)]


class NuvemFalsa:
    def __init__(self, em_aberto=(), cair=None):
        self._em_aberto, self.cair, self.gravou = list(em_aberto), cair, None

    def em_aberto(self, token):
        assert token == "TOK"
        return self._em_aberto

    def gravar(self, token, rodada, ontem, saldos, extratos, marcas):
        if self.cair:
            raise self.cair
        self.gravou = (rodada, ontem, saldos, extratos, marcas)
        return {"saldo_lido": len(saldos)}


def _entrar(email, senha):
    assert (email, senha) == ("r@e.com", "s")
    return {"access_token": "TOK"}


def test_rodada_grava_bancos_erp_e_pre_marcas():
    nuvem = NuvemFalsa([{"id": 1, "dia": "2026-11-26", "conta": "A1 - SICOOB", "valor": "150.00",
                         "descricao": "OBRA X LT 10", "foto": {}}])
    log = []
    r = rodar.rodada(_cfg(), fabrica=_tudo_bom(), entrar=_entrar, nuvem=nuvem,
                     ler_erp=lambda: [ErpAccount("1", "A1 - SICOOB", balance=Decimal("90.00"))],
                     agora=lambda: HORA, log=log.append)
    assert r == 0
    _rodada, ontem, saldos, _extratos, marcas = nuvem.gravou
    assert ontem == date(2026, 11, 26)
    assert {(s.fonte, s.conta) for s in saldos} >= {("erp", "A1 - SICOOB"), ("sicoob", "A1 - SICOOB")}
    assert [m.agendado_id for m in marcas if m.prova] == [1]
    assert any(linha.startswith("gravado:") for linha in log)


def test_nuvem_fora_devolve_1_e_o_log_ainda_tem_os_saldos():
    log = []
    r = rodar.rodada(_cfg(), fabrica=_tudo_bom(), entrar=_entrar,
                     nuvem=NuvemFalsa(cair=RuntimeError("caiu")), ler_erp=lambda: [],
                     agora=lambda: HORA, log=log.append)
    assert r == 1 and any("NÃO GRAVOU" in linha for linha in log)
    assert any("saldo sicoob A1 - SICOOB: 100.00" in linha for linha in log)


def test_rodada_de_verdade_recusa_sandbox():
    cfg = cf.de_dict({"ambiente": "sandbox", "pasta": "p", "empresas": [
        {"nome": "E", "sicoob": {"client_id": "C", "token_fixo": "T"},
         "contas": [{"banco": "sicoob", "numero": 1, "conta_erp": "X"}]}]})
    with pytest.raises(SystemExit, match="producao"):
        rodar.rodada(cfg)


def test_ensaio_sandbox_le_o_sandbox_e_nao_grava():
    lorem = {"transacoes": [{"tipo": "elit magna", "valor": "ullamco", "data": "commodo"}]}
    s = SessaoFalsa(Resp(200, '{"saldo": 436196.58701458573}'), Resp(200, lorem))
    le = rodar.ensaio_sandbox({"client_id": "C", "token_fixo": "T"}, sessao=s,
                              agora=lambda: HORA, log=lambda _m: None)
    (_m1, u1, k1), (_m2, u2, _k2) = s.pedidos
    assert u1.startswith("https://sandbox.sicoob.com.br/") and u2.endswith("/extrato/11/2026")
    assert k1["headers"]["Authorization"] == "Bearer T"
    assert le.saldos[0].valor is None and le.extratos[0].ilegiveis == 1 and le.lidas == set()


def _pasta_inter(tmp_path):
    for nome, texto in (("client_id.txt", "﻿CID-FALSO\n"), ("client_secret.txt", "SEGREDO-FALSO"),
                        ("Sandbox_InterAPI_Certificado.crt", "x"), ("Sandbox_InterAPI_Chave.key", "y")):
        (tmp_path / nome).write_text(texto, encoding="utf-8")
    return tmp_path


def test_credencial_do_inter_lida_da_pasta_sem_bom(tmp_path):
    c = rodar.credencial_inter_da_pasta(_pasta_inter(tmp_path))
    assert c["client_id"] == "CID-FALSO" and c["client_secret"] == "SEGREDO-FALSO"
    assert c["cert"][0].endswith(".crt") and c["cert"][1].endswith(".key")


def test_ensaio_inter_le_token_saldo_e_extrato_e_nao_mostra_o_token(tmp_path, monkeypatch):
    monkeypatch.setattr(rodar.bc, "INTERVALO_INTER", 0)    # o teste não espera 6,5 s de verdade
    s = SessaoFalsa(Resp(200, {"access_token": "TOKEN-SECRETO", "expires_in": 3600}),
                    Resp(200, '{"disponivel": 100.5, "limite": 0}'),
                    Resp(200, {"transacoes": [{"dataEntrada": "2023-01-26", "tipoTransacao": None,
                                               "tipoOperacao": "D", "valor": "33.33"}]}))
    log = []
    le = rodar.ensaio_sandbox({"inter_chaves": str(_pasta_inter(tmp_path))}, sessao=s,
                              agora=lambda: HORA, log=log.append)
    (_m0, u0, k0), (_m1, u1, k1), (_m2, u2, k2) = s.pedidos
    assert u0 == "https://cdpj-sandbox.partners.uatinter.co/oauth/v2/token"
    assert k0["cert"][0].endswith(".crt") and k0["data"]["client_secret"] == "SEGREDO-FALSO"
    assert u1.endswith("/banking/v2/saldo") and k1["headers"]["Authorization"] == "Bearer TOKEN-SECRETO"
    assert le.saldos[0].valor == Decimal("100.50") and le.extratos[0].fora_do_dia == 1
    assert le.lidas == {"ENSAIO - INTER"}
    assert not any("TOKEN-SECRETO" in linha or "SEGREDO" in linha for linha in log)


def test_ensaio_sem_banco_nenhum_e_config_invalida():
    with pytest.raises(cf.ConfigInvalida):
        rodar.ensaio_sandbox({}, log=lambda _m: None)


def test_argumentos():
    assert rodar._argumentos(["--config", "a.json"]) == ("a.json", False)
    assert rodar._argumentos(["--config=a.json", "--ensaio-sandbox"]) == ("a.json", True)
    with pytest.raises(SystemExit):
        rodar._argumentos(["--pagar"])
    assert rodar.main([]) == 2


def test_main_com_arquivo_ruim_sai_2_sem_rodar(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"ambiente": "producao"}', encoding="utf-8")
    assert rodar.main(["--config", str(p)]) == 2
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest -q tests/test_leitura_manha_rodar.py -p no:cacheprovider`
Esperado: `ImportError: cannot import name 'rodar' from 'leitura_manha'`.

- [ ] **Step 3: Implementar a CLI**

```python
# -*- coding: utf-8 -*-
"""A leitura das 07:30, uma rodada por chamada (o Agendador chama uma vez por dia).

    python -m leitura_manha.rodar --config <arquivo.json>                    rodada de verdade
    python -m leitura_manha.rodar --config <ensaio.json> --ensaio-sandbox    Sandbox do Sicoob
                                                                              e/ou do Inter, sem
                                                                              nuvem e sem ERP

O arquivo mora na pasta de chaves do servidor (formato em `config.py`). O
ensaio aceita o JSON do plano 1 ({"client_id", "token_fixo"}) e/ou
{"inter_chaves": "<pasta com client_id.txt, client_secret.txt, .crt e .key>"},
e não grava nada.
O ERP só é lido pelo porteiro (Chrome central ligado): nunca login HTTP.
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

from pagamento_api.robo import trava_da_rodada

from . import bancos as bc
from . import config as cf
from . import leitura as lt
from . import nuvem_leitura as nl
from .transporte import Ritmo


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


class Fabrica:
    """Os clientes reais. Um Ritmo por banco, compartilhado entre as empresas."""

    def __init__(self, cfg: cf.Config, sessao=None):
        self._cfg = cfg
        self._s = sessao or requests.Session()
        self.ritmo_sicoob = Ritmo(bc.INTERVALO_SICOOB)
        self.ritmo_inter = Ritmo(bc.INTERVALO_INTER)
        self.ritmo_token_inter = Ritmo(bc.INTERVALO_TOKEN_INTER)
        self._tokens_inter = {}

    def sicoob(self, empresa: cf.Empresa) -> bc.ContaCorrenteSicoob:
        cred = empresa.sicoob
        cert = tuple(cred["cert"]) if cred.get("cert") else None
        if self._cfg.ambiente == "sandbox":
            fixo = cred["token_fixo"]
            return bc.ContaCorrenteSicoob(self._s, bc.SICOOB_SANDBOX, cred["client_id"],
                                          lambda: fixo, ritmo=self.ritmo_sicoob, cert=cert)
        token = bc.token_sicoob(self._s, cred["client_id"], cert)
        return bc.ContaCorrenteSicoob(self._s, bc.SICOOB_PRODUCAO, cred["client_id"], token,
                                      ritmo=self.ritmo_sicoob, cert=cert)

    def inter(self, empresa: cf.Empresa, conta: cf.ContaBanco) -> bc.BankingInter:
        cred = empresa.inter
        cert = tuple(cred["cert"])
        base = bc.INTER_SANDBOX if self._cfg.ambiente == "sandbox" else bc.INTER_PRODUCAO
        if empresa.nome not in self._tokens_inter:   # um token por empresa, não por conta
            self._tokens_inter[empresa.nome] = bc.token_inter(
                self._s, base, cred["client_id"], cred["client_secret"], cert,
                self.ritmo_token_inter)
        return bc.BankingInter(self._s, base, self._tokens_inter[empresa.nome],
                               ritmo=self.ritmo_inter, cert=cert,
                               conta_corrente=conta.conta_corrente)


class _ConfigDoErp:
    """O bastante do `config` da Conciliação para o `SessaoApi` (mesmo recurso de
    `ferramentas/sonda.py:_ConfigDoErp`, sem importar a sonda inteira)."""

    def __init__(self):
        from nuvem.contas_novas import API_BASE, LEGACY_BASE
        self.erp = {"api_base": API_BASE, "legacy_api_base": LEGACY_BASE}


def ler_erp_pelo_porteiro(*, central=None, ler_saldos=None, log=print) -> list:
    """Saldos do ERP SÓ com o porteiro ligado. Desligado: levanta antes de tocar
    no ERP — `ler_saldos` com o central desligado iria para a aba do app (que o
    servidor não tem) e o login HTTP derruba a sessão do Chrome central."""
    from conciliacao.errors import ErpError
    if central is None:
        from erp.sessao import central_ligado as central
    if ler_saldos is None:
        from tela_do_dia.erp_do_dia import ler_saldos

    def so_com_porteiro() -> bool:
        if not central():
            raise ErpError("porteiro do ERP desligado (Chrome central): o ERP não é lido sem ele")
        return True

    so_com_porteiro()
    return ler_saldos(_ConfigDoErp(), None, central_ligado=so_com_porteiro, log=log)


def _registro(pasta: Path):
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / "leitura_manha.log"

    def log(msg: str) -> None:
        print(msg)
        try:
            with arquivo.open("a", encoding="utf-8") as f:
                f.write(f"{agora_utc().isoformat(timespec='seconds')} {msg}\n")
        except OSError:
            pass
    return log


def resumo(le: lt.LeituraDosBancos, erp: list, marcas: list, log) -> None:
    for s in le.saldos + erp:
        log(f"  saldo {s.fonte:6} {s.conta}: " + (f"{s.valor}" if s.valor is not None
                                                 else f"NÃO LIDO — {s.motivo}"))
    for x in le.extratos:
        log(f"  extrato {x.fonte:6} {x.conta} {x.dia:%d/%m}: {x.saidas} saída(s), "
            f"{x.entradas} entrada(s), {x.ilegiveis} ilegível(is), {x.fora_do_dia} fora do dia"
            + (f" — {x.motivo}" if x.motivo else ""))
    log(f"  pré-marcados: {sum(1 for m in marcas if m.prova)} de {len(marcas)} agendado(s) olhados")


def rodada(cfg: cf.Config, *, fabrica=None, entrar=None, nuvem=nl, ler_erp=None,
           agora=agora_utc, log=print) -> int:
    """0 = gravou; 1 = não gravou na nuvem. Banco ou ERP fora não é 1: vira 'não lido'."""
    if cfg.ambiente != "producao":
        raise SystemExit("rodada de verdade só com ambiente 'producao'; Sandbox é --ensaio-sandbox")
    from nuvem import rest
    entrar = entrar or rest.entrar
    ler_erp = ler_erp or (lambda: ler_erp_pelo_porteiro(log=log))
    hoje, ontem = lt.dias_sp(agora())
    rodada_id = str(uuid.uuid4())
    log(f"leitura das 07:30 de {hoje:%d/%m/%Y} (extrato de {ontem:%d/%m}), rodada {rodada_id}")
    le = lt.ler_bancos(cfg, fabrica or Fabrica(cfg), ontem, agora)
    erp = lt.ler_erp(ler_erp, [c.conta_erp for c in cfg.contas()], agora)
    try:
        token = entrar(cfg.nuvem_email, cfg.nuvem_senha)["access_token"]
        marcas = lt.pre_marcas(nuvem.em_aberto(token), le, hoje, log=log)
        resumo(le, erp, marcas, log)
        gravadas = nuvem.gravar(token, rodada_id, ontem, le.saldos + erp, le.extratos, marcas)
    except Exception as e:  # noqa: BLE001 — o Agendador vê o código 1; o log diz o tipo
        resumo(le, erp, [], log)
        log(f"NÃO GRAVOU na nuvem: {type(e).__name__}: {str(e)[:200]}")
        return 1
    log("gravado: " + ", ".join(f"{t} {n}" for t, n in gravadas.items()))
    return 0


def credencial_inter_da_pasta(pasta) -> dict:
    """As credenciais do Sandbox do Inter como o portal as entrega (4 arquivos).
    O conteúdo nunca é impresso: só vai para o bloco `inter` da config."""
    p = Path(pasta)
    return {"client_id": (p / "client_id.txt").read_text(encoding="utf-8-sig").strip(),
            "client_secret": (p / "client_secret.txt").read_text(encoding="utf-8-sig").strip(),
            "cert": [str(p / "Sandbox_InterAPI_Certificado.crt"),
                     str(p / "Sandbox_InterAPI_Chave.key")]}


def ensaio_sandbox(dados: dict, *, sessao=None, agora=agora_utc, log=print) -> lt.LeituraDosBancos:
    """Saldo e extrato de ontem de UMA conta do Sandbox do Sicoob (com `client_id`
    e `token_fixo`) e/ou do Inter (com `inter_chaves`: a pasta dos 4 arquivos).
    Só leitura: sem nuvem, sem ERP."""
    empresa = {"nome": "ENSAIO", "contas": []}
    if dados.get("client_id") or dados.get("token_fixo"):
        empresa["sicoob"] = {"client_id": dados.get("client_id"),
                             "token_fixo": dados.get("token_fixo")}
        empresa["contas"].append({"banco": "sicoob", "numero": int(dados.get("numero_ensaio") or 1),
                                  "conta_erp": "ENSAIO - SICOOB"})
    if dados.get("inter_chaves"):
        try:
            empresa["inter"] = credencial_inter_da_pasta(dados["inter_chaves"])
        except OSError as e:
            raise cf.ConfigInvalida(f"pasta do Inter ilegível ({type(e).__name__})") from None
        empresa["contas"].append({"banco": "inter", "conta_erp": "ENSAIO - INTER"})
    cfg = cf.de_dict({"ambiente": "sandbox", "pasta": str(dados.get("pasta") or "leitura-ensaio"),
                      "empresas": [empresa]})
    _hoje, ontem = lt.dias_sp(agora())
    le = lt.ler_bancos(cfg, Fabrica(cfg, sessao), ontem, agora)
    resumo(le, [], [], log)
    return le


USO = "uso: python -m leitura_manha.rodar --config <arquivo.json> [--ensaio-sandbox]"


def _argumentos(argv) -> tuple[str, bool]:
    """(caminho do --config, --ensaio-sandbox?). Sem `argparse`, como o robô."""
    config, ensaio, resto = "", False, list(argv)
    while resto:
        a = resto.pop(0)
        if a == "--ensaio-sandbox":
            ensaio = True
        elif a == "--config" and resto:
            config = resto.pop(0)
        elif a.startswith("--config="):
            config = a.split("=", 1)[1]
        else:
            raise SystemExit(f"argumento desconhecido: {a}\n{USO}")
    return config, ensaio


def main(argv=None) -> int:
    try:  # console do Agendador em cp1252: caractere fora dela não derruba a rodada
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    config, ensaio = _argumentos(sys.argv[1:] if argv is None else argv)
    if not config:
        print(USO)
        return 2
    if ensaio:
        import json
        try:
            dados = json.loads(Path(config).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"não consegui ler {config} ({type(e).__name__})")
            return 2
        try:
            ensaio_sandbox(dados)
        except cf.ConfigInvalida as e:
            print(f"arquivo de ensaio: {e}")
            return 2
        return 0
    try:
        cfg = cf.carregar(config)
    except cf.ConfigInvalida as e:
        print(f"arquivo do servidor: {e}")
        return 2
    pasta = Path(cfg.pasta)
    log = _registro(pasta)
    with trava_da_rodada(pasta) as minha:
        if not minha:
            log("outra leitura está rodando; esta sai sem fazer nada")
            return 0
        return rodada(cfg, log=log)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Rodar e ver passar; a suíte nova inteira**

Run: `python -m pytest -q tests/test_leitura_manha_rodar.py -p no:cacheprovider`, depois `python -m pytest -q tests -k leitura_manha -p no:cacheprovider`
Esperado: `11 passed`, depois `104 passed`.

- [ ] **Step 5: O registro no Agendador (o arquivo; registrar é ato humano)**

`ferramentas/leitura_manha/registrar_leitura_manha.ps1`, sem acentos de propósito (o PowerShell 5.1 lê `.ps1` sem BOM como ANSI):

```powershell
# Registra (ou refaz) a tarefa do Agendador do Windows que roda a leitura das
# 07:30: saldo e extrato de ontem pela API (Sicoob e Inter), saldo do ERP pelo
# porteiro, pre-marcas de ontem na nuvem (python -m leitura_manha.rodar).
#
#   powershell -ExecutionPolicy Bypass -File registrar_leitura_manha.ps1 -Config C:\chaves\leitura-manha.json
#   powershell -ExecutionPolicy Bypass -File registrar_leitura_manha.ps1 -Config ... -Python C:\caminho\python.exe -Hora 07:30
#
# O que ela garante:
#   - roda todo dia na hora pedida (padrao 07:30), no usuario atual e com a
#     sessao dele aberta (o porteiro do ERP e um Chrome com janela);
#   - se o servidor estava desligado na hora, roda assim que ligar;
#   - no maximo 30 minutos; nao abre duas copias;
#   - roda na raiz do repositorio (python -m leitura_manha.rodar precisa dela).
# Esta tarefa NAO e registrada por nenhum teste nem pelo app: so por voce, aqui.
# O arquivo -Config mora na pasta de chaves, NUNCA no repositorio.
# Sem acentos neste arquivo de proposito: PowerShell 5.1 le .ps1 sem BOM como ANSI.

param(
    [Parameter(Mandatory = $true)][string]$Config,
    [string]$Python = "",
    [string]$Hora = "07:30",
    [string]$Nome = "MoraisEng - Leitura das 07h30"
)

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
if (-not (Test-Path (Join-Path $raiz "leitura_manha\rodar.py"))) { throw "nao achei leitura_manha\rodar.py em $raiz" }
if (-not (Test-Path $Config)) { throw "nao achei o arquivo de configuracao $Config" }
$Config = (Resolve-Path $Config).Path
if ($Config.StartsWith($raiz, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "o arquivo de configuracao tem credenciais: guarde-o FORA do repositorio ($raiz)"
}

Write-Host "1) Python..."
if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "python nao esta no PATH deste usuario; use -Python <caminho>" }
    $Python = $cmd.Source
}
if (-not (Test-Path $Python)) { throw "nao achei $Python" }
& $Python -c "import requests, sys; print('   python', sys.version.split()[0], 'em', sys.executable)"
if ($LASTEXITCODE -ne 0) { throw "esse python nao tem requests. Instale: pip install -r requirements.txt" }

Write-Host "2) Removendo versao antiga da tarefa..."
if (Get-ScheduledTask -TaskName $Nome -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $Nome -Confirm:$false
    Write-Host "   removida: $Nome"
}

Write-Host "3) Registrando '$Nome' todo dia as $Hora..."
$usuario = "$env:USERDOMAIN\$env:USERNAME"
$acao = New-ScheduledTaskAction -Execute $Python -Argument "-m leitura_manha.rodar --config `"$Config`"" -WorkingDirectory $raiz
$gatilho = New-ScheduledTaskTrigger -Daily -At $Hora
$conf = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
$quem = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $Nome -Action $acao -Trigger $gatilho -Settings $conf -Principal $quem `
    -Description "Leitura das 07:30: saldos e extrato de ontem (Sicoob, Inter, ERP) para a nuvem (python -m leitura_manha.rodar)" | Out-Null
Write-Host "   ok."

Write-Host ""
Write-Host "Para rodar agora (o porteiro do ERP tem de estar ligado): Start-ScheduledTask -TaskName '$Nome'"
Write-Host "Log: <campo 'pasta' do arquivo de configuracao>\leitura_manha.log"
```

Confira a sintaxe SEM executar. No rascunho deu "erros de sintaxe: 0" e "bytes não-ASCII: 0":

```powershell
$t=$null; $e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path ferramentas\leitura_manha\registrar_leitura_manha.ps1), [ref]$t, [ref]$e); "erros: $($e.Count)"
```

- [ ] **Step 6: Ensaio real no Sandbox do Sicoob (saldo e extrato, só leitura)**

Use o arquivo de ensaio FORA do repo, com o `client_id` e o `token_fixo` públicos do portal, menu Sandbox. É o mesmo `ensaio.json` do plano 1.

Run: `python -m leitura_manha.rodar --config <pasta-de-ensaio>/ensaio.json --ensaio-sandbox`

Saída MEDIDA no rascunho em 27/11/2026, às 15:20 UTC:

```
  saldo sicoob ENSAIO - SICOOB: NÃO LIDO — Sicoob: saldo fora do formato (saldo='-22996950.34619233')
  extrato sicoob ENSAIO - SICOOB 26/11: 0 saída(s), 0 entrada(s), 2 ilegível(is), 0 fora do dia — Sicoob: 2 linha(s) ilegível(is) no extrato — tipo desconhecido 'LABORE ULLAMCO'; tipo desconhecido 'ELIT SUNT DOLOR SIT '
  pré-marcados: 0 de 0 agendado(s) olhados
exit 0
```

Numa rodada anterior, o saldo veio `72434580.14148` e as linhas `'DOLOR'`/`'CUPIDATAT AD'`: o Sandbox sorteia os valores. O que se espera: as duas chamadas respondem 200 com JSON (o encanamento, o User-Agent e o cabeçalho `client_id` funcionam). O saldo, um float com mais de 2 casas, sai "não lido" e nunca zero. Todo o extrato sai ilegível e a conta não entra no casamento. Nos dois casos a falha é fechada. A sonda crua do mesmo dia confirmou que o mesmo GET SEM o User-Agent próprio volta `200 text/html` ("Request Rejected").

- [ ] **Step 7: Ensaio real no Sandbox do Inter (token, saldo e extrato, só leitura)**

As credenciais ficam em `C:\AUTOMAÇÕES MAIS CONTROLE\_chaves\inter-sandbox\`: `client_id.txt`, `client_secret.txt`, `Sandbox_InterAPI_Certificado.crt` e `Sandbox_InterAPI_Chave.key`. **Nunca imprima o conteúdo desses arquivos nem o token**: o `resumo` só mostra saldo e contagens. Crie FORA do repo um `ensaio-inter.json` com uma linha só:

```json
{"inter_chaves": "C:\\AUTOMAÇÕES MAIS CONTROLE\\_chaves\\inter-sandbox"}
```

Run: `python -m leitura_manha.rodar --config <pasta-de-ensaio>/ensaio-inter.json --ensaio-sandbox`

O que se espera, pelo que o coordenador mediu no Sandbox do Inter em 27/11/2026: o token responde 200 (`expires_in` 3600, `scope` "extrato.read") e o saldo responde 200 com `disponivel` numérico. Se esse número vier com mais de 2 casas, o saldo sai "não lido: fora do formato", como no Sicoob, e isso deve ser anotado. O extrato responde 200 com `transacoes`, mas o Sandbox ignora o período e devolve dados fictícios de 2023: espere `0 saída(s) ... N fora do dia` e `0 ilegível(is)`. Uma linha ilegível ali indica uma forma nova, a investigar antes do merge.

**Medido pelo coordenador em 27/11/2026 (código do plano, Sandbox do Inter):** `saldo inter ENSAIO - INTER: 9999.55` · `extrato inter ENSAIO - INTER 26/11: 0 saída(s), 0 entrada(s), 0 ilegível(is), 1237 fora do dia` · `pré-marcados: 0 de 0` · exit 0. Token, saldo e extrato responderam; nenhuma linha ilegível (a forma medida bate); o Sandbox devolve dados de 2023, por isso tudo fora do dia. As formas seguem presas nos testes `test_inter_na_forma_medida_no_sandbox`, `test_saldo_inter_em_float_no_json_chega_decimal_exato` e `test_ensaio_inter_le_token_saldo_e_extrato_e_nao_mostra_o_token`.

- [ ] **Step 8: Commit**

```bash
git add leitura_manha/rodar.py ferramentas/leitura_manha/registrar_leitura_manha.ps1 tests/test_leitura_manha_rodar.py
git commit -m "leitura_manha: CLI da leitura das 07:30 (ERP so com o porteiro, Sandbox do Sicoob e do Inter so leitura) e registro no Agendador" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Verificação final do ramo

**Files:** nenhum arquivo novo. Esta tarefa só confere.

**Interfaces:** consome tudo, não produz nada.

- [ ] **Step 1: A suíte inteira do repositório, a régua de lint e o vermin**

```bash
python -m pytest -q tests -p no:cacheprovider
python -m ruff check --select E9,F leitura_manha tests
vermin --target=3.11 --no-tips --violations .
```

O `vermin` é o comando do job `test` (`build.yml`) e roda no repo inteiro. Rodado só na pasta nova, ele acusaria "Target versions not met", porque o mínimo dela é 3.7, abaixo de 3.11.

Esperado: tudo verde. O `test_empacotamento.py` passa com `leitura_manha` em `_PASTAS_SO_DO_REPO`, e o `test_nomes_de_modulo.py` passa (a pasta é pacote, e nenhum subdiretório entra no `sys.path`).

- [ ] **Step 2: Prova contrária (as regras de dinheiro e de casamento têm teste que as segura)**

Aplique cada mutante abaixo, um de cada vez, rode `python -m pytest -q tests -k leitura_manha -p no:cacheprovider` e desfaça com `git checkout -- <arquivo>`. **Cada um tem de deixar pelo menos 1 teste vermelho.** No rascunho, os 20 morreram:

| # | Arquivo | Troca | Morto no rascunho |
|---|---|---|---|
| 1 | `extrato.py` | `centavos` sem `d != d.quantize(CENTAVO)` (saldo com 11 casas aceito) | 3 falhas |
| 2 | `extrato.py` | `_comum` sem `valor <= 0` | 1 |
| 3 | `extrato.py` | `valor_texto` pela régua frouxa `autenticar.dinheiro` | 5 |
| 4 | `extrato.py` | `_TIPOS.get(bruto, SAIDA)` (tipo desconhecido vira saída) | 1 |
| 5 | `extrato.py` | `"C": SAIDA` (tipoOperacao do Inter trocado) | 4 |
| 6 | `leitura.py` | `if x.ilegiveis:` → `if False:` (ilegível não tira a conta do casamento) | 3 |
| 7 | `leitura.py` | saldo com erro vira `Decimal("0.00"), ""` | 2 |
| 8 | `leitura.py` | `_Cache` sem guardar a falha da fábrica | 1 |
| 9 | `leitura.py` | o `except` do saldo só pega `ErroLeitura` | 1 |
| 10 | `leitura.py` | `dias_sp` com `agora.date()` (sem fuso) | 2 |
| 11 | `leitura.py` | `ler_erp` só pega `ZeroDivisionError` | 1 |
| 12 | `leitura.py` | ERP sem saldo vira `Decimal(0)` | 1 |
| 13 | `rodar.py` | `ler_saldos` chamado com o `central` cru, sem conferir antes | 2 |
| 14 | `nuvem_leitura.py` | sem a conferência de linhas gravadas | 1 |
| 15 | `transporte.py` | 429 tenta três vezes | 1 |
| 16 | `transporte.py` | HTML do firewall vira `{}` | 1 |
| 17 | `bancos.py` | `INTERVALO_SICOOB = 0.4` (acima de 2/s) | 1 |
| 18 | `transporte.py` | token recusado pedido de novo | 1 |
| 19 | migration | sem `saldo_lido_nao_lido_tem_motivo` | 1 |
| 20 | migration | `pre_marca_banco_grava` sem `tem_papel('robo')` | 1 |

- [ ] **Step 3: Revisão do ramo inteiro**

Despache o agente `revisor-dinheiro` com o diff `origin/codigo/pagamento-api-sicoob...HEAD` e o foco: "nada aqui paga; confira se alguma leitura pode virar saldo zero, se alguma pré-marca pode virar resposta, se algum dado real vazou, se o ERP pode ser tocado sem o porteiro". Depois, faça uma revisão humana-equivalente em opus do Review Focus, linha por linha.

- [ ] **Step 4: PR e a saída dele (regra do dono de 14/10)**

Abra o PR contra `codigo/pagamento-api-sicoob` (empilhado no #203). No corpo vão: a saída dos dois ensaios, as letras (a) a (h) da Task 6 Step 7 quando a migration for aplicada, e a lista "Depende de fora" abaixo. O PR sai da conversa juntado, fechado com motivo ou anotado em `00 - Início/Pendências e perguntas.md` do cofre (seção "PRs abertos"), com o número, o motivo de esperar e a DATA para decidir. O worktree `_worktrees/app-leitura-manha` e o branch seguem a mesma regra: depois do merge, apagar os dois.

---

## Depende de fora (antes de registrar no Agendador)

- **Gustavo:**
  - criar o app de produção do Sicoob, só de leitura (escopo `cco_consulta`), POR EMPRESA, com o certificado A1 de cada CNPJ;
  - conseguir a credencial de produção do Inter (escopo `extrato.read`);
  - criar o usuário de papel `robo` na nuvem;
  - dar o "pode" da migration (Task 6 Step 7);
  - montar o arquivo do servidor (formato em `config.py`) na pasta de chaves;
  - rodar `registrar_leitura_manha.ps1 -Config <arquivo>` no servidor, com o porteiro já registrado e ligado.
- **1º dia real:** ler o `leitura_manha.log` e o `extrato_lido`. Se houver `ilegiveis > 0` no Sicoob, ver UMA linha crua do extrato real (sem valor, só a forma) e ajustar `_TIPOS`/`valor_texto` num commit consciente, com teste.

## Dúvidas que ficam em aberto

1. **O formato real do `tipo`, do `valor` (com ou sem sinal) e da `data` (com hora? UTC?) do extrato do Sicoob em produção.** A falha fechada cobre: até medir, nenhuma pré-marca nas contas Sicoob.
2. **O `x-conta-corrente` com várias contas** numa mesma integração do Inter.
3. **Um dia perdido:** se o servidor ficar desligado num dia inteiro, o extrato daquele dia não é relido. Ler "desde a última rodada com sucesso" seria o conserto. Fica fora até alguém pedir, e a resposta continua sendo da pessoa no portal.
4. **Mapa conta ERP ↔ número no banco:** neste plano ele vem do arquivo do servidor (`conta_erp`, `numero`), e não da tabela `conta` da nuvem (`nuvem/cadastro.sincronizar` → `contas_mc.json`/`contas_sicoob.json`). Isso foi escolhido porque a credencial já é por empresa no arquivo, e o job não depende da pasta do app. O custo é manter o mesmo nome em dois lugares. A conta que falta no ERP aparece como "conta não encontrada entre as ativas do ERP".
5. **Qual saldo o Sicoob chama de disponível:** o plano usa `saldo` e ignora `saldoLimite`/`saldoBloqueado`. Conferir com o app do banco no 1º dia.
6. **O papel `robo` largo** (achado do plano 1): ele também grava nas tabelas que só pedem `e_ativo()`. Isso continua para o plano 3 e não muda aqui.
