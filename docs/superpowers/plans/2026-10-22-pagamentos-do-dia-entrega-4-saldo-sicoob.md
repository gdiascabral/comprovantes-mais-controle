# Entrega 4: saldo do Sicoob lido sozinho. Plano de implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: superpowers:subagent-driven-development (ou superpowers:executing-plans). Os passos usam checkbox (`- [ ]`). Worktree: `C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2`, branch `codigo/pagamentos-do-dia-2`.

**Goal:** A aba "Pagamentos do dia" passa a preencher a coluna BANCO das contas do Sicoob com o saldo lido no SicoobNet, só leitura. Há um botão "Reler Sicoob" e, no alto do passo 1, a frase "Sicoob lido às HH:MM". As contas de outros bancos continuam digitadas à mão. Também fica pronta uma SONDA para medir, em 22/10, o endereço da API de saldo com o dono logado.

**Architecture:** São quatro peças, cada uma num lugar.
- **Sonda:** `ferramentas/sonda_saldo_sicoob.py`, fora do zip. Abre o Chrome do Sicoob pelo próprio `SicoobClient` do app, com o perfil da instalação, escuta a Rede e grava um retrato saneado fora do repositório.
- **Leitura no banco:** `extratos_sicoob/saldo.py`, par de `pendencias.py`. O endereço e o extrator ficam em constantes num bloco só. Antes de pedir, a leitura confere qual conta está aberta.
- **Regra pura da tela:** `tela_do_dia/saldo_sicoob.py`. Decide quais linhas do painel são do Sicoob e qual conta é cada uma, aplica o lido, monta a hora e guarda o JSON do dia.
- **Entrada isolada na aba:** `tela_do_dia/sicoob_na_tela.py`. Tem o botão, o rótulo e uma thread própria. O `frame.py` muda em cerca de 8 linhas.

**Tech Stack:** Python 3.11 (régua do vermin), tkinter, Playwright síncrono (Chrome, `channel="chrome"`), `Decimal`, pytest.

**Spec:** `C:\AUTOMAÇÕES MAIS CONTROLE\PROPOSTA - 2026-10-21 pagamentos do dia numa tela so.html` v3. Trechos que valem aqui:
- Passo 1: "A hora da leitura do banco aparece no alto, com o botão 'Reler Sicoob'" e "Clicar num valor edita. O original fica riscado ao lado".
- Decisões: "Saldo do banco automático: só Sicoob; Inter, Caixa e Bradesco ficam com campo para digitar" e "Saldos: o do sistema e o do banco se editam, inclusive para simular; o original fica visível".
- Entrega "Saldo do Sicoob lido sozinho".

## Global Constraints

- **Só leitura no banco.** Nada assina, agenda, cancela ou altera. O único pedido HTTP novo é o GET/POST do saldo, feito com `fetch` dentro da página logada, como `pendencias.py:55`.
- **Login manual.** O reCAPTCHA não é contornado (`sicoob_client.py:171`). A sonda só começa a escutar DEPOIS do login, então senha e captcha nunca passam por ela.
- **Perfil do banco só como o app abre:** `SicoobClient.__enter__` (`sicoob_client.py:119-155`), com pt-BR, extensão e o perfil `.chrome_profile_sicoob` da INSTALAÇÃO. Nunca num Chrome comum, nunca com porta de depuração, nunca criando um perfil novo (o banco aceita UM PC por usuário).
- **Repositório público.** Nenhum número de conta, nome, CPF/CNPJ ou saldo real em código, teste, comentário, plano ou commit. Os testes usam `12.345-6`, `23.456-7` e `34.567-8`, e cooperativa `0001`. O arquivo da sonda fica fora do repo, e a sonda recusa gravar dentro dele.
- **Dinheiro sempre `Decimal`.** O JSON é lido com `parse_float=Decimal` e todo saldo é quantizado em centavos.
- **Playwright síncrono vive na thread que o criou.** O `SicoobClient` nasce e morre dentro de `LeitorSicoob._t_ler`, nunca na thread do ERP (`anx.submeter`).
- **Testes de tela não rodam.** A lógica fica em módulos puros, o controlador é testado sem Tk (`__new__`, como `tests/test_abas_em_paralelo.py`), e o frame só ganha chamadas.
- **Remessa/Retorno, Saldo de pagamentos, Extratos e Anexar não mudam de comportamento.** `pendencias.py`, `sicoob_client.py`, `agendamentos_sicoob.py` e `pagamentos_frame.py` NÃO são editados.
- **Sem pasta nova de aba:** nada muda em `build.yml`, `_PASTAS` ou `motor_minimo.txt`. `ferramentas/` já está em `_PASTAS_SO_DO_REPO` (`tests/test_empacotamento.py:63`). Nenhum submódulo novo da stdlib no código do zip.
- **Sem SQL.** O mapeamento conta do painel → conta Sicoob sai do cadastro que a nuvem já sincroniza em `contas_sicoob.json`/`contas_mc.json` (`nuvem/cache.py`), pelo MESMO caminho da Remessa: `agendamentos_sicoob.conta_sicoob` (`pagamentos_dia/agendamentos_sicoob.py:131`).

## Decisões (com a razão)

1. **O digitado à mão continua valendo e tem precedência sobre o lido.**
   - A spec trata o banco como valor editável "inclusive para simular", com "o original visível". O lido é esse original e o digitado é o ajuste do dia.
   - O código já faz assim: `LinhaSaldo.banco_usado` (`tela_do_dia/saldos.py:48-50`) prefere `ajuste_banco` a `banco`, e `novo_ajuste` (`saldos.py:104`) guarda `linha.banco` como `original`. Editar depois da leitura já mostra "(era R$ lido)".
   - O que muda: se o Sicoob ler um valor DIFERENTE do que havia quando o ajuste foi feito (por exemplo, digitou antes da leitura), a linha avisa em âmbar: "vale o digitado; o banco leu R$ X depois do seu ajuste". É o espelho de `original_mudou` do sistema. "Voltar ao original" devolve o lido.
2. **O "Buscar" também lê o Sicoob** (spec, passo 1: "Depois … também lê os saldos do Sicoob"), mas só quando ainda não há leitura do dia. Ele dispara ao fim do Buscar, porque só aí se sabe quais linhas são do Sicoob. Com leitura do dia, vale a hora mostrada e o "Reler Sicoob" refaz.
3. **Reler substitui a leitura inteira.** Uma conta que falha na releitura fica "Sicoob não lido: motivo", sem segurar um valor velho calado.
4. **A hora no alto é a da conta lida há mais tempo.** Se a leitura for parcial, a frase diz "N de M contas".
5. **A leitura do dia é guardada** em `<RAIZ_SAIDA>/<ano>/<MÊS>/DD MM - saldos do sicoob.json`, ao lado do dia de trabalho e em arquivo PRÓPRIO, para não disputar `dia_de_trabalho.py` com a entrega 2. Assim, reabrir o app não pede mais 20 trocas de conta. Arquivo de outro dia é ignorado; arquivo estragado vira aviso e "não lido", sem levantar.
6. **Thread:** uma `threading.Thread` daemon por vez, no padrão do "Conferir agendamentos" (`pagamentos_frame.py:892-895`, mesma leitura do Sicoob), em vez de `ThreadPoolExecutor`. As threads do executor não são daemon (`acessorias/frame.py:694`), e fechar o app com o Chrome esperando o login (até 10 min, `sicoob_client.py:41`) deixaria o processo vivo. O essencial da regra do `extratos_sicoob` vale: a thread é própria, não a do ERP, e o cliente fica numa thread só.
7. **Enquanto o endereço não for medido** (`ROTA_SALDO == ""`), o Buscar NÃO abre o Chrome, o rótulo diz "leitura ainda não ligada — digite o saldo do banco" e o "Reler Sicoob" explica isso. A build pode sair assim se a medição de amanhã falhar.

## Review Focus

1. Conta errada: nenhum saldo é aceito sem a conferência do cabeçalho (`conta_do_cabecalho`) igual à conta pedida, e com `CAMPO_CONTA` preenchido, também da resposta.
2. Precedência: o digitado vence o lido em `saldo_do_dia` e no Excel, e o aviso "o banco leu X depois do seu ajuste" aparece só quando o lido mudou.
3. Falhas: sessão caída e endereço mudado PARAM a leitura e marcam as contas que faltavam com o porquê. Nenhuma conta do Sicoob some, e nenhuma vira R$ 0,00.
4. Thread: o `SicoobClient` nasce e morre em `_t_ler`, nunca em `anx.submeter`. A tela só recebe dados pela fila.
5. Sonda: nenhum cabeçalho, cookie, token ou corpo de login vai para o arquivo, e ela nunca grava dentro do repositório.

Testes que provam: `tests/test_sicoob_saldo.py`, `tests/test_tela_do_dia_saldo_sicoob.py`, `tests/test_tela_do_dia_saldos.py` (novos casos), `tests/test_tela_do_dia_sicoob_na_tela.py` e `tests/test_sonda_saldo_sicoob.py`. Suíte inteira: `python -m pytest tests -q`.

## Mapa de arquivos

**Novos**
| Arquivo | Responsabilidade |
|---|---|
| `ferramentas/sonda_saldo_sicoob.py` | sonda de 22/10: abre como o app, escuta, saneia, pontua candidatos, grava fora do repo; modo `--provar N` |
| `tests/test_sonda_saldo_sicoob.py` | saneamento, pontuação, recusa de saída no repo, perfil da instalação, laço de escuta |
| `extratos_sicoob/saldo.py` | constantes do endereço e do extrator; `ler_saldo`, `ler_contas`, exceções |
| `tests/test_sicoob_saldo.py` | troca de conta, conta não encontrada, outra conta na tela, sessão caída, endereço mudado, formato novo, hora, `Decimal` |
| `tela_do_dia/saldo_sicoob.py` | linhas do painel → conta Sicoob, aplicar o lido, texto da hora, recado de falha, JSON do dia |
| `tests/test_tela_do_dia_saldo_sicoob.py` | testes puros do módulo acima |
| `tela_do_dia/sicoob_na_tela.py` | `LeitorSicoob`: botão "Reler Sicoob", rótulo da hora, thread própria, fila |
| `tests/test_tela_do_dia_sicoob_na_tela.py` | controlador sem Tk: thread própria, mensagens, recusas |

**Arquivos EXISTENTES modificados**
| Arquivo | Mudança |
|---|---|
| `tela_do_dia/saldos.py` | `LinhaSaldo.nota_banco` (campo novo com default), `banco_mudou`, `situacao()` |
| `tests/test_tela_do_dia_saldos.py` | casos novos |
| `tela_do_dia/frame.py` | ~8 linhas: import, `LeitorSicoob` no cartão 1, uma linha no `_recalcular`, uma no `_receber_leitura`, `fechar()` |
| `comprovantes_app.py` | 3 linhas: `outros_no_sicoob`, o `sicoob_ocupado` da Remessa passa a ver também esta aba, e o ● da barra |
| `.claude/rules/arquitetura-tela-do-dia.md` | seção "Saldo do Sicoob (entrega 4)" |
| `.claude/rules/arquitetura-extratos-sicoob.md` | parágrafo do `saldo.py` |
| `.claude/rules/arquitetura-ferramentas.md` | parágrafo da `sonda_saldo_sicoob.py` |

**NÃO tocar:** `extratos_sicoob/pendencias.py`, `extratos_sicoob/sicoob_client.py`, `pagamentos_dia/*`, `extratos_sicoob/extratos_frame.py`, `.github/workflows/build.yml`, `motor_minimo.txt`, `tela_do_dia/dia_de_trabalho.py`.

## Quando fica pronto

| Tarefa | Quando | Modelo |
|---|---|---|
| 1. Sonda: saneamento e pontuação (puro) | **HOJE** | sonnet |
| 2. Sonda: abrir como o app, escutar, instruções, `--provar` | **HOJE** | sonnet |
| 3. `extratos_sicoob/saldo.py` com endereço plugável | **HOJE** | opus |
| 4. `saldos.py`: precedência visível e nota do banco | **HOJE** | sonnet |
| 5. `tela_do_dia/saldo_sicoob.py` (regra pura) | **HOJE** | opus |
| 6. `LeitorSicoob` + frame + app | **HOJE** | sonnet |
| 7. Documentação e suíte inteira | **HOJE** | haiku |
| 8. Medir com o dono e plugar o endereço | **AMANHÃ 22/10** | opus + dono |

---

### Task 1: Sonda, parte pura (saneamento, máscara, pontuação) — HOJE · sonnet

**Files:**
- Create: `ferramentas/sonda_saldo_sicoob.py`
- Test: `tests/test_sonda_saldo_sicoob.py`

**Interfaces:**
- Existentes (usar, não editar): `tela_do_dia/valores.py:21` `ler_valor_editado(texto) -> Decimal` (lê o saldo que o dono digita).
- Novas:
  - `e_da_api_do_sicoob(url: str) -> bool`
  - `rota_sensivel(url: str) -> bool`
  - `mascarar_url(url: str) -> str`
  - `retrato(dado, chave: str = "")`
  - `folhas(dado, prefixo="") -> list[tuple[str, object]]`
  - `pontuar(dado, saldos_na_tela=frozenset()) -> tuple[int, list[str]]`
  - `saida_permitida(saida: Path, raiz: Path = RAIZ_DO_REPO) -> bool`
  - `registro(*, metodo, url, status, tipo, cabecalhos, corpo_pedido, texto, saldos_na_tela=frozenset(), conta_na_tela="", hora="") -> dict | None`
  - `relatorio(registros: list[dict]) -> dict`

- [ ] **Step 1: escrever os testes que falham**

```python
# tests/test_sonda_saldo_sicoob.py
# -*- coding: utf-8 -*-
"""A sonda do saldo do Sicoob, sem navegador. Contas e valores fictícios."""
import json
from decimal import Decimal as D
from pathlib import Path

from ferramentas import sonda_saldo_sicoob as s

API = "https://ib.sicoob.com.br/sicoobnet/api"


def test_so_api_do_sicoob_e_nunca_login():
    assert s.e_da_api_do_sicoob(f"{API}/conta/saldo")
    assert not s.e_da_api_do_sicoob("https://outro.com/api/conta/saldo")
    assert not s.e_da_api_do_sicoob("https://ib.sicoob.com.br/sicoobnet/ib/#/home")
    assert s.rota_sensivel(f"{API}/autenticacao/login")
    assert s.rota_sensivel(f"{API}/dispositivo-usuario/identificar")


def test_endereco_mascara_conta_e_valor_longo():
    url = f"{API}/conta/123456/saldo?numeroConta=123456&token=abcdefabcdefabcdefabcdefabcdefabcdefabcdef&tipo=1"
    m = s.mascarar_url(url)
    assert "123456" not in m and "abcdef" not in m
    assert "/conta/<NUM>/saldo" in m and "tipo=1" in m


def test_retrato_redige_segredo_corta_lista_e_mascara_conta():
    dado = {"token": "xyz", "contaCorrente": 123456, "saldoDisponivel": D("1234.56"),
            "saldoTexto": "1.234,56", "nome": "x" * 80,
            "itens": [{"a": 1}, {"a": 2}, {"a": 3}, {"a": 4}]}
    r = s.retrato(dado)
    assert r["token"] == "<redigido>"
    assert r["contaCorrente"] == "<NUM>"
    assert r["saldoDisponivel"] == "1234.56" and r["saldoTexto"] == "1.234,56"
    assert r["nome"].startswith("<texto de 80")
    assert r["itens"][-1] == "<+1 itens>" and len(r["itens"]) == 4


def test_pontua_campo_de_saldo_e_acha_o_valor_da_tela():
    dado = {"resultado": {"saldoDisponivel": D("1500.00"), "limite": D("0")}}
    pontos, achados = s.pontuar(dado, frozenset({D("1500.00")}))
    assert pontos >= 13
    assert "resultado.saldoDisponivel" in achados
    assert "resultado.saldoDisponivel = saldo da tela" in achados


def test_registro_ignora_nao_json_outro_host_e_login():
    base = dict(metodo="GET", status=200, cabecalhos={}, corpo_pedido=None)
    assert s.registro(url=f"{API}/x", tipo="text/html", texto="<html>", **base) is None
    assert s.registro(url="https://outro.com/api/x", tipo="application/json", texto="{}", **base) is None
    assert s.registro(url=f"{API}/login", tipo="application/json", texto="{}", **base) is None


def test_nada_de_cabecalho_cookie_nem_token_vai_para_o_arquivo():
    r = s.registro(metodo="POST", url=f"{API}/conta/saldo", status=200, tipo="application/json",
                   cabecalhos={"authorization": "Bearer SEGREDO1", "cookie": "SEGREDO2",
                               "x-cliente": "SEGREDO3", "accept": "*/*"},
                   corpo_pedido=json.dumps({"conta": "123456", "accessToken": "SEGREDO4"}),
                   texto=json.dumps({"saldo": 10.5, "sessionId": "SEGREDO5"}),
                   conta_na_tela="12.345-6")
    texto = json.dumps(r, default=str)
    for segredo in ("SEGREDO1", "SEGREDO2", "SEGREDO3", "SEGREDO4", "SEGREDO5", "123456"):
        assert segredo not in texto
    assert r["cabecalhos"] == ["authorization", "cookie", "x-cliente"]   # só NOMES
    assert r["conta_no_pedido"] is True and r["conta_na_tela"] == "…5-6"
    assert r["resposta"]["saldo"] == "10.5"                              # float nunca: Decimal


def test_arquivo_nunca_dentro_do_repositorio(tmp_path):
    assert not s.saida_permitida(s.RAIZ_DO_REPO / "sonda.json")
    assert not s.saida_permitida(s.RAIZ_DO_REPO / "tests" / "x.json")
    assert s.saida_permitida(tmp_path / "sonda.json")


def test_relatorio_poe_o_melhor_candidato_primeiro():
    a = {"pontos": 1, "hora": "08:00:01"}
    b = {"pontos": 13, "hora": "08:00:02"}
    assert s.relatorio([a, b])["respostas"] == [b, a]
```

- [ ] **Step 2: rodar e ver falhar**
  `python -m pytest tests/test_sonda_saldo_sicoob.py -q` → `ModuleNotFoundError: ferramentas.sonda_saldo_sicoob`.

- [ ] **Step 3: implementar a parte pura**

```python
# ferramentas/sonda_saldo_sicoob.py
# -*- coding: utf-8 -*-
"""Sonda do SALDO do Sicoob: mede, com o dono logado, qual endereço a tela usa.

Ferramenta de UMA medição (22/10/2026), fora do codigo.zip
(`_PASTAS_SO_DO_REPO`). O app nunca a importa. Ela não lê saldo para ninguém:
escuta a Rede enquanto o DONO abre a tela de saldo de duas contas e grava,
FORA do repositório, os endereços JSON candidatos e o FORMATO da resposta.
O que se aprende vira as constantes de `extratos_sicoob/saldo.py`.

PASSO A PASSO (para o dono) — ver `PASSO_A_PASSO`, impresso ao rodar.

O que NUNCA vai para o arquivo: cabeçalhos (só os NOMES dos não-padrão),
cookies, nada de login (só escuta depois que a lista de contas aparece, e
rota de login/dispositivo/token é descartada), valor de chave sensível,
sequência de 5+ dígitos que não seja valor em dinheiro (conta, CPF/CNPJ, id).
"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

RAIZ_DO_REPO = Path(__file__).resolve().parents[1]
HOST = "ib.sicoob.com.br"
LIMITE_CORPO = 2_000_000
MAX_ITENS_LISTA = 3
MAX_TEXTO = 40

_CHAVE_SENSIVEL = re.compile(
    r"(?i)token|senha|password|secret|auth|cookie|sess|jwt|hash|assinatura|"
    r"chave|captcha|cpf|cnpj|documento|email|telefone|celular")
_ROTA_SENSIVEL = re.compile(
    r"(?i)login|autentic|token|senha|captcha|dispositivo|cripto|chave|operador")
_CHAVE_DE_SALDO = re.compile(r"(?i)saldo|balance")
_CHAVE_VIZINHA = re.compile(r"(?i)dispon|limite|bloquead|contabil|projetad")
_DIGITOS_LONGOS = re.compile(r"\d{5,}")
_VALOR = re.compile(r"^-?(\d{1,3}(\.\d{3})*|\d+),\d{2}$|^-?\d+\.\d{1,2}$")
_CABECALHOS_PADRAO = frozenset(
    "accept accept-encoding accept-language content-type content-length origin "
    "referer user-agent sec-ch-ua sec-ch-ua-mobile sec-ch-ua-platform "
    "sec-fetch-dest sec-fetch-mode sec-fetch-site connection host".split())


def e_da_api_do_sicoob(url: str) -> bool:
    p = urlsplit(url or "")
    return p.scheme == "https" and p.netloc == HOST and "/api/" in p.path


def rota_sensivel(url: str) -> bool:
    return bool(_ROTA_SENSIVEL.search(urlsplit(url or "").path))


def _mascarar_valor(v: str) -> str:
    if _DIGITOS_LONGOS.search(v or ""):
        return "<NUM>"
    return f"<{len(v)} chars>" if len(v or "") > MAX_TEXTO else v


def mascarar_url(url: str) -> str:
    p = urlsplit(url or "")
    caminho = _DIGITOS_LONGOS.sub("<NUM>", p.path)
    pares = [(k, "<redigido>" if _CHAVE_SENSIVEL.search(k) else _mascarar_valor(v))
             for k, v in parse_qsl(p.query, keep_blank_values=True)]
    resto = f"?{urlencode(pares, safe='<>/')}" if pares else ""
    return f"{p.scheme}://{p.netloc}{caminho}{resto}"


def retrato(dado, chave: str = ""):
    """A estrutura da resposta, sem segredo e sem número de conta."""
    if chave and _CHAVE_SENSIVEL.search(chave):
        return "<redigido>"
    if isinstance(dado, dict):
        return {k: retrato(v, k) for k, v in dado.items()}
    if isinstance(dado, list):
        itens = [retrato(v, chave) for v in dado[:MAX_ITENS_LISTA]]
        if len(dado) > MAX_ITENS_LISTA:
            itens.append(f"<+{len(dado) - MAX_ITENS_LISTA} itens>")
        return itens
    if dado is None or isinstance(dado, bool):
        return dado
    if isinstance(dado, Decimal):
        return str(dado)
    if isinstance(dado, int):
        dinheiro = _CHAVE_DE_SALDO.search(chave) or _CHAVE_VIZINHA.search(chave)
        return dado if dinheiro or abs(dado) < 10_000 else "<NUM>"
    texto = str(dado)
    if _VALOR.match(texto.strip()):
        return texto
    if _DIGITOS_LONGOS.search(texto):
        return "<NUM>"
    return f"<texto de {len(texto)} chars>" if len(texto) > MAX_TEXTO else texto


def folhas(dado, prefixo: str = ""):
    if isinstance(dado, dict):
        return [f for k, v in dado.items()
                for f in folhas(v, f"{prefixo}.{k}" if prefixo else str(k))]
    if isinstance(dado, list):
        return [f for i, v in enumerate(dado)
                for f in folhas(v, f"{prefixo}.{i}" if prefixo else str(i))]
    return [(prefixo, dado)]


def _como_decimal(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        t = str(v).replace("R$", "").replace(" ", "")
        if "," in t:
            t = t.replace(".", "").replace(",", ".")
        return Decimal(t).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def pontuar(dado, saldos_na_tela=frozenset()) -> tuple[int, list[str]]:
    pontos, achados = 0, []
    for caminho, valor in folhas(dado):
        ultima = caminho.rsplit(".", 1)[-1]
        if _CHAVE_DE_SALDO.search(ultima):
            pontos += 3
            achados.append(caminho)
        elif _CHAVE_VIZINHA.search(ultima):
            pontos += 1
        if saldos_na_tela and _como_decimal(valor) in saldos_na_tela:
            pontos += 10
            achados.append(f"{caminho} = saldo da tela")
    return pontos, achados


def saida_permitida(saida: Path, raiz: Path = RAIZ_DO_REPO) -> bool:
    try:
        Path(saida).resolve().relative_to(Path(raiz).resolve())
    except ValueError:
        return True
    return False


def _retrato_do_corpo(corpo):
    if not corpo:
        return None, False
    try:
        dado = json.loads(corpo, parse_float=Decimal)
    except ValueError:
        return f"<corpo não-JSON de {len(corpo)} bytes>", bool(_DIGITOS_LONGOS.search(corpo))
    tem_conta = any(_DIGITOS_LONGOS.search(str(v)) for _c, v in folhas(dado))
    return retrato(dado), tem_conta


def registro(*, metodo, url, status, tipo, cabecalhos, corpo_pedido, texto,
             saldos_na_tela=frozenset(), conta_na_tela="", hora=""):
    if not e_da_api_do_sicoob(url) or rota_sensivel(url):
        return None
    if "json" not in (tipo or "").lower() or len(texto or "") > LIMITE_CORPO:
        return None
    try:
        dado = json.loads(texto, parse_float=Decimal)
    except ValueError:
        return None
    pontos, achados = pontuar(dado, saldos_na_tela)
    pedido, conta_no_pedido = _retrato_do_corpo(corpo_pedido)
    p = urlsplit(url)
    digitos = re.sub(r"\D", "", conta_na_tela or "")
    return {
        "hora": hora, "metodo": metodo, "endereco": mascarar_url(url),
        "conta_no_endereco": bool(_DIGITOS_LONGOS.search(p.path)
                                  or _DIGITOS_LONGOS.search(p.query)),
        "conta_no_pedido": conta_no_pedido, "status": status,
        "cabecalhos": sorted(k.lower() for k in (cabecalhos or {})
                             if k.lower() not in _CABECALHOS_PADRAO),
        "conta_na_tela": f"…{digitos[-2:-1]}-{digitos[-1:]}" if digitos else "",
        "pontos": pontos, "caminhos_de_saldo": achados,
        "pedido": pedido, "resposta": retrato(dado),
    }


def relatorio(registros: list[dict]) -> dict:
    return {"versao": 1,
            "aviso": "arquivo LOCAL da sonda — não vai para o repositório",
            "respostas": sorted(registros, key=lambda r: (-r["pontos"], r["hora"]))}
```

  `conta_na_tela` guarda só o dígito anterior ao hífen e o verificador ("…5-6"). Isso basta para distinguir a conta A da B, e nenhum número inteiro é gravado.

- [ ] **Step 4: rodar e ver passar**
  `python -m pytest tests/test_sonda_saldo_sicoob.py -q` → passam.

- [ ] **Step 5: commit**
```
git add ferramentas/sonda_saldo_sicoob.py tests/test_sonda_saldo_sicoob.py
git commit -m "Sonda do saldo do Sicoob: retrato saneado e pontuação dos candidatos

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Sonda, parte do navegador, instruções e `--provar` — HOJE · sonnet

**Files:**
- Modify: `ferramentas/sonda_saldo_sicoob.py`
- Test: `tests/test_sonda_saldo_sicoob.py`

**Interfaces:**
- Existentes:
  - `extratos_sicoob/sicoob_config.py:36` `PASTA_PERFIL_CHROME`, lido em `SicoobClient.__enter__` (`sicoob_client.py:126`, `:146`). Trocar o atributo do módulo antes do `__enter__` abre o perfil da instalação com os MESMOS argumentos do app.
  - `util.py:87` `pasta_do_perfil(nome) -> Path` (o nome da pasta é `.chrome_profile_sicoob`).
  - `sicoob_client.py:62` `JS_TEXTOS_DA_CONTA`, `:87` `conta_do_cabecalho(novo, corpo) -> str`, `:171` `aguardar_login(tempo=TEMPO_LOGIN)`.
  - `baixar_comprovantes/sicoob_baixar.py:459-498` `_escutar`: o ouvinte é função Python e o corpo é lido FORA do callback. Copiar a regra, não importar.
  - `extratos_sicoob/sicoob_contas.py:119` `carregar(caminho) -> Mapa`, `:102` `Mapa.contas`.
  - `extratos_sicoob/saldo.py` (Task 3): `ler_contas(...)`.
- Novas:
  - `perfil_do_app(app: Path) -> Path`
  - `abrir_como_o_app(app: Path, log=print)`
  - `escutar(cli, *, ate: float, terminou) -> list[dict]`
  - `perguntar_saldos(entrada=input) -> frozenset[Decimal]`
  - `provar(cli, app: Path, n: int) -> int`
  - `main(argv=None) -> int`

- [ ] **Step 1: testes que falham**

```python
# acrescentar em tests/test_sonda_saldo_sicoob.py
import pytest


def test_recusa_instalacao_sem_o_perfil_do_sicoob_e_nao_cria_outro(tmp_path):
    with pytest.raises(SystemExit, match="perfil"):
        s.perfil_do_app(tmp_path)
    assert not (tmp_path / ".chrome_profile_sicoob").exists()


def test_abre_pelo_sicoob_client_com_o_perfil_da_instalacao(monkeypatch, tmp_path):
    from extratos_sicoob import sicoob_client as sc
    (tmp_path / ".chrome_profile_sicoob").mkdir()
    visto = {}

    class _Ctx:
        pages = []
        def new_page(self): return object()
        def set_default_timeout(self, _ms): pass

    class _Chromium:
        def launch_persistent_context(self, perfil, **kw):
            visto["perfil"], visto["kw"] = perfil, kw
            return _Ctx()

    class _Pw:
        chromium = _Chromium()
        def start(self): return self

    monkeypatch.setattr(sc, "sync_playwright", lambda: _Pw())
    monkeypatch.setattr(sc.util, "limpar_historico_de_downloads", lambda _p: False)
    monkeypatch.setattr(sc.cfg, "PASTA_PERFIL_CHROME", sc.cfg.PASTA_PERFIL_CHROME)  # restaura
    cli = s.abrir_como_o_app(tmp_path, log=lambda *_: None)
    cli.__enter__()
    assert Path(visto["perfil"]) == tmp_path / ".chrome_profile_sicoob"
    assert visto["kw"]["locale"] == "pt-BR" and "--lang=pt-BR" in visto["kw"]["args"]


class _Resp:
    def __init__(self, url, texto):
        self.url, self.status, self._t = url, 200, texto
        self.headers = {"content-type": "application/json"}
        self.request = type("R", (), {"method": "GET", "post_data": None,
                                      "headers": {"authorization": "x"}})()
    def text(self): return self._t


class _Pagina:
    def __init__(self, ctx): self.ctx, self.voltas = ctx, 0
    def evaluate(self, _js): return {"novo": "0001 | 12.345-6 | PJ", "corpo": ""}
    def wait_for_timeout(self, _ms):
        self.voltas += 1
        if self.voltas == 1:
            self.ctx.disparar(_Resp(f"{API}/conta/saldo", '{"saldo": 1.5}'))


class _CtxEscuta:
    def __init__(self): self.ouvintes = []
    def on(self, _ev, f): self.ouvintes.append(f)
    def remove_listener(self, _ev, f): self.ouvintes.remove(f)
    def disparar(self, r):
        for f in list(self.ouvintes): f(r)


def test_escutar_le_o_corpo_fora_do_ouvinte_e_para_no_enter():
    ctx = _CtxEscuta()
    cli = type("C", (), {})()
    cli.ctx, cli.page = ctx, _Pagina(ctx)
    brutos = s.escutar(cli, ate=float("inf"), terminou=lambda: cli.page.voltas >= 3)
    assert [b["url"] for b in brutos] == [f"{API}/conta/saldo"]
    assert brutos[0]["conta_na_tela"] == "12.345-6"
    assert ctx.ouvintes == []                    # ouvinte removido


def test_main_recusa_saida_dentro_do_repo(tmp_path):
    (tmp_path / ".chrome_profile_sicoob").mkdir()
    with pytest.raises(SystemExit, match="repositório"):
        s.main(["--app", str(tmp_path), "--saida", str(s.RAIZ_DO_REPO / "x.json")])
```

- [ ] **Step 2: rodar e ver falhar** com `python -m pytest tests/test_sonda_saldo_sicoob.py -q`.

- [ ] **Step 3: implementar**

```python
# acrescentar em ferramentas/sonda_saldo_sicoob.py
import argparse
import time
from datetime import datetime

PASSO_A_PASSO = """
SONDA DO SALDO DO SICOOB — só leitura, nada é pago nem alterado.

 1. FECHE o app Comprovantes (o perfil do Sicoob só abre num Chrome por vez).
 2. O Chrome do Sicoob vai abrir (o MESMO do app). Faça o login como sempre:
    cooperativa, chave, senha, captcha. A sonda NÃO escuta o login: ela só
    começa quando a lista de contas aparecer.
 3. Entre numa conta (conta A). Espere a tela inicial carregar com o saldo.
    Abra também "Saldo" / "Extrato" dessa conta. ANOTE o saldo que aparece.
 4. Troque de conta (⇄) para OUTRA conta (conta B) e repita o passo 3.
 5. Volte para esta janela preta e aperte ENTER (ou feche o Chrome).
 6. A sonda vai perguntar os saldos que você anotou (pode só apertar ENTER).
 7. Ela grava o arquivo indicado no fim e mostra os 5 melhores candidatos.
    Mande o arquivo para o Claude. NÃO coloque no repositório.
"""


def perfil_do_app(app: Path) -> Path:
    import util
    perfil = Path(app) / util.pasta_do_perfil("sicoob").name
    if not perfil.is_dir():
        raise SystemExit(
            f"[!] não achei o perfil do Sicoob em {perfil}.\n"
            "    Aponte --app para a pasta do 'Comprovantes Mais Controle.exe'\n"
            "    (a que o banco já reconhece). Um perfil novo pediria o\n"
            "    cadastro do PC — e o Sicoob aceita UM por usuário.")
    return perfil


def abrir_como_o_app(app: Path, log=print):
    """O `SicoobClient` do app, com o perfil da INSTALAÇÃO (não o do repo)."""
    from extratos_sicoob import sicoob_config as cfg
    from extratos_sicoob.sicoob_client import SicoobClient
    cfg.PASTA_PERFIL_CHROME = perfil_do_app(app)
    return SicoobClient(log=log)


def _conta_na_tela(page) -> str:
    from extratos_sicoob.sicoob_client import JS_TEXTOS_DA_CONTA, conta_do_cabecalho
    try:
        t = page.evaluate(JS_TEXTOS_DA_CONTA) or {}
        return conta_do_cabecalho(t.get("novo"), t.get("corpo", ""))
    except Exception:                                        # noqa: BLE001
        return ""


def _bruto(resposta, page) -> dict | None:
    """Lido FORA do ouvinte (ler corpo no callback trava o Playwright sync).
    Fica só em memória; quem saneia antes do disco é `registro`."""
    if not e_da_api_do_sicoob(resposta.url) or rota_sensivel(resposta.url):
        return None
    tipo = (resposta.headers or {}).get("content-type", "")
    if "json" not in tipo.lower():
        return None
    try:
        texto = resposta.text()
    except Exception:                                        # noqa: BLE001
        return None
    pedido = resposta.request
    return {"metodo": pedido.method, "url": resposta.url, "status": resposta.status,
            "tipo": tipo, "cabecalhos": dict(pedido.headers or {}),
            "corpo_pedido": pedido.post_data, "texto": texto,
            "conta_na_tela": _conta_na_tela(page),
            "hora": datetime.now().strftime("%H:%M:%S")}


def escutar(cli, *, ate: float, terminou) -> list[dict]:
    vistas, brutos = [], []

    def guardar(resposta):              # função Python, nunca list.append
        vistas.append(resposta)

    cli.ctx.on("response", guardar)
    examinadas = 0
    try:
        while time.monotonic() < ate and not terminou():
            while examinadas < len(vistas):
                b = _bruto(vistas[examinadas], cli.page)
                examinadas += 1
                if b:
                    brutos.append(b)
            try:
                cli.page.wait_for_timeout(250)
            except Exception:                                # noqa: BLE001
                break                       # o dono fechou o Chrome
        while examinadas < len(vistas):     # o que chegou na última volta
            b = _bruto(vistas[examinadas], cli.page)
            examinadas += 1
            if b:
                brutos.append(b)
    finally:
        try:
            cli.ctx.remove_listener("response", guardar)
        except Exception:                                    # noqa: BLE001
            pass
    return brutos


def _apertou_enter() -> bool:
    import msvcrt                       # só Windows; a ferramenta não vai ao exe
    return bool(msvcrt.kbhit()) and msvcrt.getwch() in "\r\n"


def perguntar_saldos(entrada=input) -> frozenset:
    from tela_do_dia.valores import ler_valor_editado
    saldos = set()
    for conta in ("A", "B"):
        texto = entrada(f"Saldo da conta {conta} como estava na tela (ENTER pula): ")
        if texto.strip():
            try:
                saldos.add(ler_valor_editado(texto))
            except Exception:                                # noqa: BLE001
                print("   não entendi esse valor — seguindo sem ele")
    return frozenset(saldos)


def provar(cli, app: Path, n: int) -> int:
    """Depois de plugar as constantes: lê o saldo das N primeiras contas."""
    from extratos_sicoob import saldo, sicoob_contas
    from tela_do_dia.valores import brl
    mapa = sicoob_contas.carregar(Path(app) / "contas_sicoob.json")
    numeros = [c.numero for c in mapa.contas][:n]
    falhas = 0
    for lido in saldo.ler_contas(cli, numeros, log=print):
        if lido.ok:
            print(f"  {lido.numero}: {brl(lido.saldo)} às {lido.lido_em:%H:%M:%S}")
        else:
            falhas += 1
            print(f"  {lido.numero}: NÃO LIDO — {lido.motivo}")
    print("Compare com a tela do banco.")
    return 1 if falhas else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="sonda do saldo do Sicoob (só leitura)")
    ap.add_argument("--app", required=True, help="pasta do Comprovantes Mais Controle.exe")
    ap.add_argument("--saida", default="", help="arquivo .json (FORA do repositório)")
    ap.add_argument("--minutos", type=int, default=20)
    ap.add_argument("--provar", type=int, default=0,
                    help="lê o saldo das N primeiras contas com as constantes do saldo.py")
    args = ap.parse_args(argv)
    app = Path(args.app).expanduser().resolve()
    saida = (Path(args.saida) if args.saida
             else app / f"sonda-saldo-sicoob-{datetime.now():%Y%m%d-%H%M}.json")
    if not saida_permitida(saida):
        raise SystemExit(f"[!] {saida} fica dentro do repositório (que é público). "
                         "Escolha outra pasta.")
    perfil_do_app(app)
    print(PASSO_A_PASSO)
    try:
        with abrir_como_o_app(app) as cli:
            cli.aguardar_login()
            if args.provar:
                return provar(cli, app, args.provar)
            print("Escutando... (ENTER aqui quando terminar)")
            brutos = escutar(cli, ate=time.monotonic() + args.minutos * 60,
                             terminou=_apertou_enter)
    except Exception as e:                                   # noqa: BLE001
        if "already in use" in str(e).lower():
            raise SystemExit("[!] o perfil do Sicoob está aberto — feche o app e rode de novo.")
        raise
    saldos = perguntar_saldos()
    registros = [r for b in brutos if (r := registro(**b, saldos_na_tela=saldos))]
    saida.write_text(json.dumps(relatorio(registros), ensure_ascii=False, indent=1,
                                default=str), encoding="utf-8")
    print(f"\nGravado: {saida}  ({len(registros)} respostas JSON)")
    for r in relatorio(registros)["respostas"][:5]:
        print(f"  [{r['pontos']:>3}] {r['metodo']} {r['endereco']} -> {r['caminhos_de_saldo'][:3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

  O walrus (`:=`) é válido em 3.8+, então vermin 3.11 aceita.

- [ ] **Step 4:** `python -m pytest tests/test_sonda_saldo_sicoob.py -q` → passa. Depois `ruff check --select E9,F ferramentas/sonda_saldo_sicoob.py`.

- [ ] **Step 5: commit**
```
git add ferramentas/sonda_saldo_sicoob.py tests/test_sonda_saldo_sicoob.py
git commit -m "Sonda do saldo do Sicoob: abre como o app, escuta e grava fora do repositório

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `extratos_sicoob/saldo.py` com endereço e extrator plugáveis — HOJE · opus

**Files:**
- Create: `extratos_sicoob/saldo.py`
- Test: `tests/test_sicoob_saldo.py`

**Interfaces:**
- Existentes (usar, não editar):
  - `extratos_sicoob/pendencias.py:55` `_JS`: o fetch na página, `[url, metodo, corpo] -> {status, corpo}`.
  - `pendencias.py:143-158`: o padrão "acessar, recarregar e tentar de novo, `False` vira falha".
  - `sicoob_client.py:62` `JS_TEXTOS_DA_CONTA`, `:87` `conta_do_cabecalho`, `:103` `SessaoPerdida`, `:283` `SicoobClient.acessar_conta(numero) -> bool` (levanta `SessaoPerdida` via `_conferir_sessao`, `:202`).
- Novas:
  - Constantes `ROTA_SALDO`, `METODO_SALDO`, `CORPO_SALDO`, `CAMPO_SALDO`, `CAMPO_SINAL`, `CAMPO_CONTA`
  - `medido() -> bool`, `exigir_medido() -> None`
  - `montar_pedido(numero) -> tuple[str, str, dict | None]`
  - `no_caminho(dado, caminho)`, `para_decimal(v) -> Decimal`
  - `extrair_saldo(dado) -> Decimal`, `extrair_conta(dado) -> str`
  - `interpretar(resposta: dict, numero: str, url_da_pagina: str = "") -> Decimal`
  - `conta_na_tela(page) -> str`, `ler_saldo(page, numero) -> Decimal`, `entrar(cli, numero) -> None`
  - `ler_contas(cli, numeros, *, agora=datetime.now, parar=lambda: False, log=print, progresso=lambda f, t: None) -> list[Lido]`
  - `@dataclass(frozen=True) Lido(numero, saldo=None, lido_em=None, motivo="")` com `.ok`
  - Exceções `SaldoFalhou`, `EnderecoMudou`, `ContaNaoEncontrada`, `OutraConta`

- [ ] **Step 1: testes que falham**

```python
# tests/test_sicoob_saldo.py
# -*- coding: utf-8 -*-
"""Saldo do Sicoob sem rede: o endereço e o formato são FICTÍCIOS e plugados
pelo fixture `medido`, exatamente como as constantes serão preenchidas em
22/10/2026. Contas fictícias."""
import datetime as dt
import json
import re
from decimal import Decimal as D

import pytest

from extratos_sicoob import saldo as S
from extratos_sicoob import sicoob_client as sc

AGORA = dt.datetime(2026, 10, 22, 8, 12, 30)


@pytest.fixture
def medido(monkeypatch):
    monkeypatch.setattr(S, "ROTA_SALDO", "/api/ficticio/saldo")
    monkeypatch.setattr(S, "METODO_SALDO", "GET")
    monkeypatch.setattr(S, "CORPO_SALDO", None)
    monkeypatch.setattr(S, "CAMPO_SALDO", "saldo.valor")
    monkeypatch.setattr(S, "CAMPO_SINAL", "")
    monkeypatch.setattr(S, "CAMPO_CONTA", "")


def ok(valor):
    return {"status": 200, "corpo": json.dumps({"saldo": {"valor": valor}})}


class Pagina:
    def __init__(self, respostas):
        self.aberta, self.respostas, self.pedidos = "", respostas, []
        self.url = "https://ib.sicoob.com.br/sicoobnet/ib/#/home"
        self.recargas = 0

    def evaluate(self, js, args=None):
        if js == sc.JS_TEXTOS_DA_CONTA:
            novo = f"0001 | {self.aberta} | PJ | X" if self.aberta else None
            return {"novo": novo, "corpo": ""}
        url, metodo, corpo = args
        self.pedidos.append((url, metodo, corpo, self.aberta))
        r = self.respostas[re.sub(r"\D", "", self.aberta)]
        return r() if callable(r) else r

    def reload(self): self.recargas += 1
    def wait_for_timeout(self, _ms): pass


class Cliente:
    def __init__(self, pagina, na_lista, trava=()):
        self.page, self.na_lista, self.trava, self.trocas = pagina, na_lista, trava, []

    def acessar_conta(self, numero):
        self.trocas.append(numero)
        if numero not in self.na_lista:
            return False
        if numero not in self.trava:                # troca que "não pegou"
            self.page.aberta = numero
        return True


def test_sem_endereco_medido_recusa_antes_de_tocar_no_banco():
    cli = Cliente(Pagina({}), ["12.345-6"])
    with pytest.raises(S.SaldoFalhou, match="ainda não está ligada"):
        S.ler_contas(cli, ["12.345-6"], agora=lambda: AGORA)
    assert cli.trocas == []


def test_le_cada_conta_com_a_sua_conta_aberta(medido):
    pagina = Pagina({"123456": ok("1500.10"), "234567": ok("-20.5")})
    cli = Cliente(pagina, ["12.345-6", "23.456-7"])
    lidos = S.ler_contas(cli, ["12.345-6", "23.456-7"], agora=lambda: AGORA)
    assert [(l.numero, l.saldo, l.lido_em) for l in lidos] == [
        ("12.345-6", D("1500.10"), AGORA), ("23.456-7", D("-20.50"), AGORA)]
    assert [p[3] for p in pagina.pedidos] == ["12.345-6", "23.456-7"]
    assert pagina.pedidos[0][0] == S.BASE + "/api/ficticio/saldo"


def test_troca_que_nao_pegou_nao_le_o_saldo_da_outra(medido):
    pagina = Pagina({"123456": ok("10.00"), "234567": ok("99.00")})
    cli = Cliente(pagina, ["12.345-6", "23.456-7"], trava=("23.456-7",))
    a, b = S.ler_contas(cli, ["12.345-6", "23.456-7"], agora=lambda: AGORA)
    assert a.ok and not b.ok and "a tela está em 12.345-6" in b.motivo
    assert len(pagina.pedidos) == 1                 # B nem chegou a pedir


def test_conta_fora_do_login_vira_motivo_e_a_fila_segue(medido):
    pagina = Pagina({"234567": ok("5")})
    cli = Cliente(pagina, ["23.456-7"])
    a, b = S.ler_contas(cli, ["12.345-6", "23.456-7"], agora=lambda: AGORA)
    assert "não aparece neste login" in a.motivo and b.saldo == D("5.00")


def test_sessao_caida_para_e_marca_as_que_faltavam(medido):
    pagina = Pagina({"123456": ok("1"), "234567": {"status": 401, "corpo": ""},
                     "345678": ok("3")})
    cli = Cliente(pagina, ["12.345-6", "23.456-7", "34.567-8"])
    a, b, c = S.ler_contas(cli, ["12.345-6", "23.456-7", "34.567-8"], agora=lambda: AGORA)
    assert a.ok and b.motivo == S.SESSAO_CAIU and c.motivo == S.SESSAO_CAIU
    assert cli.trocas == ["12.345-6", "23.456-7"]


def test_sessao_caida_pela_tela_de_login(medido):
    pagina = Pagina({"123456": ok("1")})
    pagina.url = "https://ib.sicoob.com.br/sicoobnet/ib/#/login"
    [a] = S.ler_contas(Cliente(pagina, ["12.345-6"]), ["12.345-6"], agora=lambda: AGORA)
    assert a.motivo == S.SESSAO_CAIU


def test_endereco_mudou_para_tudo_com_recado_claro(medido):
    pagina = Pagina({"123456": {"status": 404, "corpo": "Not Found"}, "234567": ok("2")})
    cli = Cliente(pagina, ["12.345-6", "23.456-7"])
    a, b = S.ler_contas(cli, ["12.345-6", "23.456-7"], agora=lambda: AGORA)
    assert "não reconhece mais o endereço do saldo" in a.motivo
    assert "/api/ficticio/saldo" in a.motivo and "HTTP 404" in a.motivo
    assert b.motivo == a.motivo and cli.trocas == ["12.345-6"]


def test_formato_novo_sem_o_campo_e_recado_claro(medido):
    pagina = Pagina({"123456": {"status": 200, "corpo": '{"outro": 1}'}})
    [a] = S.ler_contas(Cliente(pagina, ["12.345-6"]), ["12.345-6"], agora=lambda: AGORA)
    assert "não tem mais 'saldo.valor'" in a.motivo


def test_resposta_que_nao_e_json(medido):
    pagina = Pagina({"123456": {"status": 200, "corpo": "<html>"}})
    [a] = S.ler_contas(Cliente(pagina, ["12.345-6"]), ["12.345-6"], agora=lambda: AGORA)
    assert "não devolveu JSON" in a.motivo


def test_erro_qualquer_numa_conta_nao_derruba_as_outras(medido):
    pagina = Pagina({"123456": {"status": 500, "corpo": "pane"}, "234567": ok("2")})
    a, b = S.ler_contas(Cliente(pagina, ["12.345-6", "23.456-7"]),
                        ["12.345-6", "23.456-7"], agora=lambda: AGORA)
    assert "HTTP 500" in a.motivo and b.ok


def test_dinheiro_e_decimal_nunca_float(medido):
    assert S.interpretar({"status": 200, "corpo": '{"saldo": {"valor": 0.1}}'}, "12.345-6") == D("0.10")
    assert S.para_decimal("1.234,56") == D("1234.56")
    assert S.para_decimal("-1.234,56") == D("-1234.56")
    with pytest.raises(S.EnderecoMudou):
        S.para_decimal(True)


def test_sinal_devedor(medido, monkeypatch):
    monkeypatch.setattr(S, "CAMPO_SALDO", "valor")
    monkeypatch.setattr(S, "CAMPO_SINAL", "natureza")
    r = {"status": 200, "corpo": '{"valor": 50.00, "natureza": "D"}'}
    assert S.interpretar(r, "12.345-6") == D("-50.00")


def test_resposta_de_outra_conta_e_recusada(medido, monkeypatch):
    monkeypatch.setattr(S, "CAMPO_CONTA", "conta")
    r = {"status": 200, "corpo": '{"saldo": {"valor": 1}, "conta": "234567"}'}
    with pytest.raises(S.OutraConta):
        S.interpretar(r, "12.345-6")


def test_conta_no_endereco_e_no_corpo(medido, monkeypatch):
    monkeypatch.setattr(S, "ROTA_SALDO", "/api/ficticio/{conta}/saldo")
    monkeypatch.setattr(S, "METODO_SALDO", "POST")
    monkeypatch.setattr(S, "CORPO_SALDO", {"contas": ["{conta}"], "tipo": 1})
    url, metodo, corpo = S.montar_pedido("12.345-6")
    assert url.endswith("/api/ficticio/123456/saldo") and metodo == "POST"
    assert corpo == {"contas": ["123456"], "tipo": 1}
    assert S.CORPO_SALDO == {"contas": ["{conta}"], "tipo": 1}     # não mutou


def test_parar_marca_as_que_faltavam(medido):
    pagina = Pagina({"123456": ok("1"), "234567": ok("2")})
    feitas = []
    lidos = S.ler_contas(Cliente(pagina, ["12.345-6", "23.456-7"]), ["12.345-6", "23.456-7"],
                         agora=lambda: AGORA, parar=lambda: len(feitas) >= 1,
                         log=feitas.append)
    assert lidos[0].ok and lidos[1].motivo == S.INTERROMPIDA


def test_mesma_conta_duas_vezes_e_lida_uma(medido):
    pagina = Pagina({"123456": ok("1")})
    lidos = S.ler_contas(Cliente(pagina, ["12.345-6"]), ["12.345-6", "123456"], agora=lambda: AGORA)
    assert len(lidos) == 1 and len(pagina.pedidos) == 1


def test_endereco_no_repositorio_nao_carrega_numero_de_conta():
    texto = S.ROTA_SALDO + json.dumps(S.CORPO_SALDO)
    assert not re.search(r"\d{5,}", texto)
```

- [ ] **Step 2:** `python -m pytest tests/test_sicoob_saldo.py -q` → falha (módulo ausente).

- [ ] **Step 3: implementar**

```python
# extratos_sicoob/saldo.py
# -*- coding: utf-8 -*-
"""O saldo de cada conta do Sicoob — só LEITURA. Par de `pendencias.py`.

Usado pela aba "Pagamentos do dia" (botão "Reler Sicoob"): o saldo do banco
das contas do Sicoob deixa de ser digitado. Nada é assinado, agendado ou
alterado no banco.

**A conta é implícita na sessão**, como nas pendências: o robô entra na conta
pelo seletor (`SicoobClient.acessar_conta`), CONFERE no cabeçalho que a conta
aberta é a pedida e só então pede o saldo, com o `fetch` da própria página.
Saldo de uma empresa gravado na linha de outra é o pior erro possível aqui —
e nada na tela o denunciaria.

**O endereço e o formato são do Sicoob, que os troca sem aviso** (fez isso
com os comprovantes em 25/09/2026). Por isso moram num bloco só, logo abaixo,
medido pela `ferramentas/sonda_saldo_sicoob.py`. Endereço que some (404/405/
410), resposta que não é JSON ou sem o campo viram `EnderecoMudou`, que PARA
a leitura (não adianta trocar de conta 20 vezes) com um recado que diz o
endereço; a pessoa digita o saldo à mão até medirem de novo.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .pendencias import _JS as _JS_FETCH        # o mesmo fetch, com a sessão do banco
from .sicoob_client import JS_TEXTOS_DA_CONTA, SessaoPerdida, conta_do_cabecalho

BASE = "https://ib.sicoob.com.br/sicoobnet"

# ======================= O ENDEREÇO E O EXTRATOR =========================
# Medidos em 22/10/2026 com a sonda (`ferramentas/sonda_saldo_sicoob.py`).
# "{conta}" em ROTA_SALDO ou em valor de texto do CORPO_SALDO vira os
# DÍGITOS da conta pedida. Nenhum número de conta real aqui: o repo é público.
ROTA_SALDO = ""                 # caminho a partir de BASE; "" = não medido
METODO_SALDO = "GET"
CORPO_SALDO = None              # dict do POST, ou None
CAMPO_SALDO = ""                # caminho com pontos até o saldo ("0.saldo")
CAMPO_SINAL = ""                # "" = o número já tem sinal
SINAIS_DEVEDORES = ("D", "-", "DEVEDOR", "NEGATIVO")
CAMPO_CONTA = ""                # caminho até a conta na resposta; "" = não diz
# =========================================================================

NAO_MEDIDO = ("a leitura do saldo do Sicoob ainda não está ligada (o "
              "endereço do banco não foi medido) — digite o saldo à mão")
SESSAO_CAIU = ("a sessão do Sicoob caiu antes desta conta — faça o login de "
               "novo e clique em Reler Sicoob")
INTERROMPIDA = "leitura interrompida antes desta conta"
CENTAVO = Decimal("0.01")
_ENDERECO_SUMIU = (404, 405, 410)


class SaldoFalhou(RuntimeError):
    """O saldo desta conta não foi lido; a mensagem diz o porquê."""


class EnderecoMudou(SaldoFalhou):
    """O Sicoob mudou o endereço ou o formato: vale para TODAS as contas."""


class ContaNaoEncontrada(SaldoFalhou):
    pass


class OutraConta(SaldoFalhou):
    pass


@dataclass(frozen=True)
class Lido:
    numero: str
    saldo: Decimal | None = None
    lido_em: _dt.datetime | None = None
    motivo: str = ""

    @property
    def ok(self) -> bool:
        return self.saldo is not None


def so_digitos(texto) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def medido() -> bool:
    return bool(ROTA_SALDO and CAMPO_SALDO)


def exigir_medido() -> None:
    if not medido():
        raise SaldoFalhou(NAO_MEDIDO)


def _com_conta(valor, digitos: str):
    if isinstance(valor, str):
        return valor.replace("{conta}", digitos)
    if isinstance(valor, dict):
        return {k: _com_conta(v, digitos) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_com_conta(v, digitos) for v in valor]
    return valor


def montar_pedido(numero: str) -> tuple[str, str, dict | None]:
    d = so_digitos(numero)
    corpo = None if CORPO_SALDO is None else _com_conta(CORPO_SALDO, d)
    return BASE + ROTA_SALDO.replace("{conta}", d), METODO_SALDO, corpo


def no_caminho(dado, caminho: str):
    atual = dado
    for parte in caminho.split("."):
        if isinstance(atual, list) and parte.isdigit() and int(parte) < len(atual):
            atual = atual[int(parte)]
        elif isinstance(atual, dict) and parte in atual:
            atual = atual[parte]
        else:
            raise EnderecoMudou(f"a resposta do saldo não tem mais '{caminho}' — "
                                "o formato do Sicoob mudou")
    return atual


def para_decimal(valor) -> Decimal:
    if isinstance(valor, bool) or valor is None:
        raise EnderecoMudou(f"o saldo veio como {valor!r}, que não é número")
    if isinstance(valor, (int, Decimal)):
        d = Decimal(valor)
    elif isinstance(valor, float):                 # não chega: parse_float=Decimal
        d = Decimal(str(valor))
    elif isinstance(valor, str):
        t = valor.replace("R$", "").replace("\xa0", "").replace(" ", "")
        if "," in t:
            t = t.replace(".", "").replace(",", ".")
        try:
            d = Decimal(t)
        except InvalidOperation:
            raise EnderecoMudou(f"o saldo veio como '{valor[:30]}', que não é número") from None
    else:
        raise EnderecoMudou("o saldo veio num formato que não é número")
    if not d.is_finite():
        raise EnderecoMudou("o saldo veio como um número inválido")
    return d.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def extrair_saldo(dado) -> Decimal:
    saldo = para_decimal(no_caminho(dado, CAMPO_SALDO))
    if CAMPO_SINAL:
        sinal = str(no_caminho(dado, CAMPO_SINAL) or "").strip().upper()
        if sinal in SINAIS_DEVEDORES:
            saldo = -abs(saldo)
    return saldo


def extrair_conta(dado) -> str:
    return so_digitos(no_caminho(dado, CAMPO_CONTA)) if CAMPO_CONTA else ""


def interpretar(resposta: dict, numero: str, url_da_pagina: str = "") -> Decimal:
    status = int(resposta.get("status") or 0)
    corpo = resposta.get("corpo") or ""
    if status in (401, 403) or "#/login" in url_da_pagina or "#/operador" in url_da_pagina:
        raise SessaoPerdida(SESSAO_CAIU)
    if status in _ENDERECO_SUMIU:
        raise EnderecoMudou(
            f"o Sicoob não reconhece mais o endereço do saldo ({ROTA_SALDO}, "
            f"HTTP {status}) — a tela do banco mudou; digite o saldo à mão e "
            "peça para medir de novo")
    if status != 200:
        raise SaldoFalhou(f"o Sicoob respondeu HTTP {status}: {corpo.strip()[:200]}")
    try:
        dado = json.loads(corpo, parse_float=Decimal)
    except ValueError:
        raise EnderecoMudou("o endereço do saldo não devolveu JSON — a tela "
                            "do banco mudou") from None
    if CAMPO_CONTA and extrair_conta(dado) != so_digitos(numero):
        raise OutraConta(f"pedi o saldo da conta {numero} e a resposta é de "
                         "outra conta — não uso")
    return extrair_saldo(dado)


def conta_na_tela(page) -> str:
    textos = page.evaluate(JS_TEXTOS_DA_CONTA) or {}
    return conta_do_cabecalho(textos.get("novo"), textos.get("corpo", ""))


def ler_saldo(page, numero: str) -> Decimal:
    """O saldo da conta `numero`, que tem de ser a ABERTA na tela."""
    exigir_medido()
    na_tela = conta_na_tela(page)
    if so_digitos(na_tela) != so_digitos(numero):
        raise OutraConta(
            f"pedi a conta {numero} e a tela está em "
            f"{na_tela or '(não consegui ler)'} — não leio o saldo de outra "
            "conta com o nome desta")
    url, metodo, corpo = montar_pedido(numero)
    return interpretar(page.evaluate(_JS_FETCH, [url, metodo, corpo]), numero,
                       getattr(page, "url", ""))


def entrar(cli, numero: str) -> None:
    """Como `pendencias.ler_conta`: o ⇄ some depois de várias trocas, e um
    `reload` o traz de volta — tenta uma segunda vez. Sessão que caiu não volta
    com reload: sobe."""
    try:
        entrou = cli.acessar_conta(numero)
    except SessaoPerdida:
        raise
    except Exception:                                        # noqa: BLE001
        cli.page.reload()
        cli.page.wait_for_timeout(3000)
        entrou = cli.acessar_conta(numero)
    if not entrou:
        raise ContaNaoEncontrada("esta conta não aparece neste login do Sicoob")


def _primeira_linha(erro) -> str:
    texto = (str(erro or "").strip().splitlines() or [""])[0].strip()
    return texto[:160] or type(erro).__name__


def ler_contas(cli, numeros, *, agora=_dt.datetime.now, parar=lambda: False,
               log=print, progresso=lambda feitas, total: None) -> list[Lido]:
    """Uma `Lido` por conta, NA ORDEM pedida; nenhuma some. Sessão caída e
    endereço mudado param a fila (as que faltavam levam o porquê); o resto
    falha só na conta."""
    exigir_medido()
    vistos, fila = set(), []
    for n in numeros:
        if so_digitos(n) and so_digitos(n) not in vistos:
            vistos.add(so_digitos(n))
            fila.append(n)
    lidos: list[Lido] = []
    for i, numero in enumerate(fila):
        if parar():
            lidos += [Lido(n, motivo=INTERROMPIDA) for n in fila[i:]]
            break
        progresso(i, len(fila))
        try:
            entrar(cli, numero)
            valor = ler_saldo(cli.page, numero)
        except SessaoPerdida:
            log(SESSAO_CAIU)
            lidos += [Lido(n, motivo=SESSAO_CAIU) for n in fila[i:]]
            break
        except EnderecoMudou as e:
            log(str(e))
            lidos += [Lido(n, motivo=str(e)) for n in fila[i:]]
            break
        except Exception as e:                               # noqa: BLE001
            lidos.append(Lido(numero, motivo=_primeira_linha(e)))
            log(f"{numero}: não lido — {_primeira_linha(e)}")
        else:
            lidos.append(Lido(numero, valor, agora()))
            log(f"{numero}: lido")
    progresso(len(fila), len(fila))
    return lidos
```

  O `log` de `parar` no teste: `log=feitas.append` recebe uma entrada por conta lida, e `parar` olha esse tamanho. Isso simula "parar depois da 1ª".

- [ ] **Step 4:** `python -m pytest tests/test_sicoob_saldo.py tests/test_agendamentos_sicoob.py tests/test_sicoob_idioma.py -q` → passam. As pendências seguem intactas.

- [ ] **Step 5: commit**
```
git add extratos_sicoob/saldo.py tests/test_sicoob_saldo.py
git commit -m "Sicoob: leitura do saldo por conta, com endereço e extrator plugáveis

Confere a conta aberta antes de pedir; sessão caída e endereço mudado param a
fila com o porquê. O endereço é medido em 22/10 (ROTA_SALDO vazio = desligado).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `saldos.py`, precedência visível e nota do banco — HOJE · sonnet

**Files:**
- Modify: `tela_do_dia/saldos.py` (dataclass `LinhaSaldo` `:35-80`)
- Test: `tests/test_tela_do_dia_saldos.py`

**Interfaces:**
- Existentes: `LinhaSaldo` (`saldos.py:36`), `banco_usado` (`:49`), `saldo_do_dia` (`:59`), `situacao()` (`:69`), `aplicar_ajustes` (`:91`, usa `replace` e preserva os outros campos), `novo_ajuste` (`:100`).
- Novas: o campo `LinhaSaldo.nota_banco: str = ""`, por ÚLTIMO, com default, para não quebrar quem constrói por posição; e a propriedade `LinhaSaldo.banco_mudou -> bool`.

- [ ] **Step 1: testes que falham** (acrescentar no arquivo existente)

```python
from dataclasses import replace


def test_lido_do_banco_vira_saldo_do_dia(mapa):
    alfa = replace(sd.montar_saldos(CONTAS, mapa)[0], banco=D("100.00"))
    assert alfa.saldo_do_dia == D("100.00") and alfa.situacao() == ("ok", "bate")


def test_digitado_vale_sobre_o_lido_e_avisa_quando_o_lido_mudou(mapa):
    alfa = sd.montar_saldos(CONTAS, mapa)[0]                       # banco None
    digitado = sd.aplicar_ajustes([alfa], {alfa.rotulo: {
        sd.BANCO: sd.novo_ajuste(alfa, sd.BANCO, D("100.00"))}})[0]
    lido_depois = replace(digitado, banco=D("80.00"))              # Sicoob leu depois
    assert lido_depois.saldo_do_dia == D("100.00")                 # vale o digitado
    assert lido_depois.banco_mudou
    tag, frase = lido_depois.situacao()
    assert tag == "atencao" and "o banco leu R$ 80,00 depois do seu ajuste" in frase


def test_ajuste_feito_sobre_o_lido_nao_avisa(mapa):
    lida = replace(sd.montar_saldos(CONTAS, mapa)[0], banco=D("80.00"))
    simulada = sd.aplicar_ajustes([lida], {lida.rotulo: {
        sd.BANCO: sd.novo_ajuste(lida, sd.BANCO, D("100.00"), "simulação")}})[0]
    assert not simulada.banco_mudou and simulada.situacao()[0] == "ok"


def test_digitado_igual_ao_lido_nao_avisa(mapa):
    alfa = sd.montar_saldos(CONTAS, mapa)[0]
    d = sd.aplicar_ajustes([alfa], {alfa.rotulo: {sd.BANCO: sd.novo_ajuste(alfa, sd.BANCO, D("100.00"))}})[0]
    assert not replace(d, banco=D("100.00")).banco_mudou


def test_diferenca_continua_erro_e_leva_o_aviso(mapa):
    alfa = sd.montar_saldos(CONTAS, mapa)[0]
    d = sd.aplicar_ajustes([alfa], {alfa.rotulo: {sd.BANCO: sd.novo_ajuste(alfa, sd.BANCO, D("90.00"))}})[0]
    tag, frase = replace(d, banco=D("70.00")).situacao()
    assert tag == "erro" and "R$ 10,00" in frase and "o banco leu R$ 70,00" in frase


def test_nota_do_banco_sobe_como_atencao(mapa):
    alfa = replace(sd.montar_saldos(CONTAS, mapa)[0], nota_banco="Sicoob não lido: x")
    assert alfa.situacao() == ("atencao", "Sicoob não lido: x")
    assert sd.ordenar([sd.montar_saldos(CONTAS, mapa)[1], alfa])[0] is alfa
```

- [ ] **Step 2:** `python -m pytest tests/test_tela_do_dia_saldos.py -q` → falha (`nota_banco`, `banco_mudou`).

- [ ] **Step 3: implementar** em `tela_do_dia/saldos.py`

```python
@dataclass(frozen=True)
class LinhaSaldo:
    linha: int
    rotulo: str
    sistema: Decimal | None
    banco: Decimal | None = None          # lido do banco (entrega 4: Sicoob)
    ajuste_sistema: Ajuste | None = None
    ajuste_banco: Ajuste | None = None
    #: Por que o banco não foi lido (conta do Sicoob que falhou). Vazio para
    #: as contas digitadas à mão — o "sem o saldo do banco" de sempre.
    nota_banco: str = ""
    ...

    @property
    def banco_mudou(self) -> bool:
        """O LIDO mudou depois do ajuste do banco (ex.: digitou antes de o
        Sicoob ser lido). O digitado continua valendo — a spec manda o ajuste
        mandar no dia —, mas a linha avisa, como `original_mudou` faz com o
        sistema."""
        a = self.ajuste_banco
        return (a is not None and self.banco is not None
                and a.original != self.banco and a.valor != self.banco)

    def situacao(self) -> tuple[str, str]:
        if self.sistema_usado is None:
            return "erro", "o sistema não trouxe o saldo"
        if self.original_mudou:
            return "atencao", (f"o sistema mudou desde o ajuste: era "
                               f"{brl(self.ajuste_sistema.original)}, agora {brl(self.sistema)}")
        if self.banco_usado is None:
            if self.nota_banco:
                return "atencao", self.nota_banco
            return "info", "sem o saldo do banco"
        aviso = (f" · o banco leu {brl(self.banco)} depois do seu ajuste"
                 if self.banco_mudou else "")
        dif = self.diferenca
        if dif == 0:
            return ("atencao", "bate com o digitado" + aviso) if aviso else ("ok", "bate")
        return "erro", f"não bate — diferença de {brl(dif)}{aviso}"
```

  Atualizar a docstring do módulo (`saldos.py:10-11`): "o saldo do dia é o do BANCO — o digitado, senão o lido do Sicoob —; senão o do SISTEMA".

- [ ] **Step 4:** `python -m pytest tests/test_tela_do_dia_saldos.py tests/test_tela_do_dia_excel.py tests/test_tela_do_dia_decisoes.py tests/test_tela_do_dia_aportes.py -q` → passam.

- [ ] **Step 5: commit**
```
git add tela_do_dia/saldos.py tests/test_tela_do_dia_saldos.py
git commit -m "Pagamentos do dia: o banco digitado vale sobre o lido e avisa quando o lido mudou

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: `tela_do_dia/saldo_sicoob.py` (regra pura) — HOJE · opus

**Files:**
- Create: `tela_do_dia/saldo_sicoob.py`
- Test: `tests/test_tela_do_dia_saldo_sicoob.py`

**Interfaces:**
- Existentes:
  - `pagamentos_dia/agendamentos_sicoob.py:131` `conta_sicoob(conta_erp, mapa_mc, empresas) -> tuple[str, str]` e `:127` `MOTIVO_FORA_SICOOB`.
  - `conciliacao/mapping.py:97` `by_row(row)`, `:100` `resolve_account(account)`, `:134` `is_ignored(label)`.
  - `conciliacao/models.py:75` `ErpAccount(id, name, …, balance)` e `:121` `ModelRow(row, label, uuid, account_number, erp_name, exists_in_erp)`.
  - `tela_do_dia/dia_de_trabalho.py:40` `pasta_do_dia(raiz_saida, data)` e `:118` `gravar` (o modelo de gravação atômica).
  - `util.sem_acento`.
- Novas:
  - `@dataclass(frozen=True) ContaDoPainel(rotulo, numero="", motivo="")` com `.do_sicoob`
  - `contas_do_painel(linhas, contas_erp, mapping, mapa_mc, empresas) -> list[ContaDoPainel]`
  - `numeros_a_ler(contas) -> list[str]`
  - `@dataclass SaldoLido(numero, saldo, lido_em, motivo="")`
  - `@dataclass LeituraSicoob(data, contas: dict)` com `de_resultados(data, resultados)` e `.hora`
  - `aplicar(linhas, contas, leitura) -> list[LinhaSaldo]`
  - `texto_da_hora(leitura, contas, *, lendo=None, ligado=True) -> str`
  - `recado_da_falha(erro) -> str`
  - `caminho(raiz_saida, data) -> Path`, `para_dict(leitura) -> dict`, `de_dict(dados, data) -> LeituraSicoob`, `ler(caminho, data) -> tuple[LeituraSicoob | None, str]`, `gravar(leitura, caminho) -> Path`

- [ ] **Step 1: testes que falham**

```python
# tests/test_tela_do_dia_saldo_sicoob.py
# -*- coding: utf-8 -*-
"""O saldo do Sicoob na tela do dia, sem tela e sem navegador. Fictício."""
import datetime as dt
from decimal import Decimal as D
from types import SimpleNamespace as NS

import pytest

from conciliacao.mapping import AccountMapping
from conciliacao.models import ErpAccount
from tela_do_dia import saldo_sicoob as ss
from tela_do_dia import saldos as sd

HOJE = dt.date(2026, 10, 22)
MAPA = ("model_rows:\n"
        "- row: 8\n  label: Alfa - Sicoob\n  uuid: u-alfa\n  erp_name: ALFA LTDA - SICOOB\n"
        "- row: 9\n  label: Beta - Inter\n  uuid: u-beta\n  erp_name: BETA LTDA - INTER\n"
        "- row: 10\n  label: Gama - Sicoob\n  uuid: u-gama\n  erp_name: GAMA LTDA - SICOOB\n"
        "- row: 11\n  label: Delta - Sicoob\n  uuid: u-delta\n  erp_name: DELTA LTDA - SICOOB\n")
ERP = [ErpAccount("u-alfa", "ALFA LTDA - SICOOB", balance=D("100")),
       ErpAccount("u-beta", "BETA LTDA - INTER", balance=D("50")),
       ErpAccount("u-gama", "GAMA LTDA - SICOOB", balance=D("10"))]   # Delta sem saldo


def _destino(erp, empresa, banco):
    return NS(erp=erp, empresa=empresa, pasta=banco, banco=banco, sufixo="")


DESTINOS = [_destino("ALFA LTDA - SICOOB", "ALFA", "SICOOB"),
            _destino("BETA LTDA - INTER", "BETA", "INTER"),
            _destino("DELTA LTDA - SICOOB", "DELTA", "SICOOB")]          # Gama fora
MAPA_MC = NS(de=lambda nome: next((d for d in DESTINOS if d.erp == nome), None))
EMPRESAS = [NS(nome="ALFA", contas=[NS(numero="12.345-6", pasta="SICOOB", sufixo="")]),
            NS(nome="DELTA", contas=[NS(numero="23.456-7", pasta="SICOOB", sufixo="")])]


@pytest.fixture
def mapa(tmp_path):
    p = tmp_path / "mapping.yaml"
    p.write_text(MAPA, encoding="utf-8")
    return AccountMapping.load(p)


@pytest.fixture
def linhas(mapa):
    return sd.montar_saldos(ERP, mapa)


def test_cada_linha_sabe_se_e_do_sicoob_e_qual_conta(linhas, mapa):
    contas = {c.rotulo: c for c in ss.contas_do_painel(linhas, ERP, mapa, MAPA_MC, EMPRESAS)}
    assert contas["Alfa - Sicoob"].numero == "12.345-6"
    assert not contas["Beta - Inter"].do_sicoob                      # digitada
    assert contas["Gama - Sicoob"].motivo and not contas["Gama - Sicoob"].numero
    # Delta não veio do ERP: cai no erp_name da linha
    assert contas["Delta - Sicoob"].numero == "23.456-7"
    assert ss.numeros_a_ler(contas.values()) == ["12.345-6", "23.456-7"]


def test_duas_linhas_na_mesma_conta_nao_sao_preenchidas(linhas, mapa):
    empresas = [NS(nome="ALFA", contas=[NS(numero="12.345-6", pasta="SICOOB", sufixo="")]),
                NS(nome="DELTA", contas=[NS(numero="12.345-6", pasta="SICOOB", sufixo="")])]
    contas = {c.rotulo: c for c in ss.contas_do_painel(linhas, ERP, mapa, MAPA_MC, empresas)}
    assert "mesma conta do Sicoob" in contas["Alfa - Sicoob"].motivo
    assert "mesma conta do Sicoob" in contas["Delta - Sicoob"].motivo
    assert ss.numeros_a_ler(contas.values()) == []


def _leitura():
    return ss.LeituraSicoob.de_resultados(HOJE, [
        NS(numero="12.345-6", saldo=D("90.00"), lido_em=dt.datetime(2026, 10, 22, 8, 12), motivo=""),
        NS(numero="23.456-7", saldo=None, lido_em=None, motivo="esta conta não aparece neste login")])


def test_aplicar_preenche_o_banco_e_o_digitado_continua_valendo(linhas, mapa):
    contas = ss.contas_do_painel(linhas, ERP, mapa, MAPA_MC, EMPRESAS)
    com_lido = ss.aplicar(linhas, contas, _leitura())
    por = {ln.rotulo: ln for ln in com_lido}
    assert por["Alfa - Sicoob"].banco == D("90.00")
    assert por["Beta - Inter"].banco is None and por["Beta - Inter"].nota_banco == ""
    assert por["Delta - Sicoob"].nota_banco == "Sicoob não lido: esta conta não aparece neste login"
    assert por["Gama - Sicoob"].nota_banco.startswith("Sicoob não lido: ")
    digitado = sd.aplicar_ajustes(com_lido, {"Alfa - Sicoob": {
        sd.BANCO: sd.Ajuste(valor=D("95.00"), original=D("90.00"))}})
    alfa = next(ln for ln in digitado if ln.rotulo == "Alfa - Sicoob")
    assert alfa.saldo_do_dia == D("95.00") and alfa.banco == D("90.00")


def test_sem_leitura_nada_muda(linhas, mapa):
    contas = ss.contas_do_painel(linhas, ERP, mapa, MAPA_MC, EMPRESAS)
    assert ss.aplicar(linhas, contas, None) == linhas


def test_hora_no_alto(linhas, mapa):
    contas = ss.contas_do_painel(linhas, ERP, mapa, MAPA_MC, EMPRESAS)
    assert ss.texto_da_hora(None, contas) == "Sicoob ainda não lido hoje"
    assert ss.texto_da_hora(_leitura(), contas) == (
        "Sicoob lido às 08:12 · 1 de 2 contas (as outras: veja a situação)")
    assert ss.texto_da_hora(None, contas, lendo=(3, 20)) == "Lendo o Sicoob… 3 de 20 contas"
    assert "ainda não ligada" in ss.texto_da_hora(None, contas, ligado=False)


def test_hora_e_a_da_conta_lida_ha_mais_tempo():
    leitura = ss.LeituraSicoob.de_resultados(HOJE, [
        NS(numero="12.345-6", saldo=D("1"), lido_em=dt.datetime(2026, 10, 22, 8, 15), motivo=""),
        NS(numero="23.456-7", saldo=D("2"), lido_em=dt.datetime(2026, 10, 22, 8, 12), motivo="")])
    contas = [ss.ContaDoPainel("A", numero="12.345-6"), ss.ContaDoPainel("B", numero="23.456-7")]
    assert ss.texto_da_hora(leitura, contas) == "Sicoob lido às 08:12"


def test_recado_quando_o_perfil_esta_em_uso():
    erro = RuntimeError("Failed to create a ProcessSingleton for your profile directory")
    assert "já está aberto por outra aba" in ss.recado_da_falha(erro)
    assert ss.recado_da_falha(RuntimeError("linha 1\nlinha 2")) == "Sicoob: linha 1"


def test_gravar_e_ler_volta_igual_em_decimal(tmp_path):
    p = ss.caminho(tmp_path, HOJE)
    ss.gravar(_leitura(), p)
    lida, aviso = ss.ler(p, HOJE)
    assert aviso == "" and lida.contas["123456"].saldo == D("90.00")
    assert lida.contas["234567"].saldo is None and lida.contas["234567"].motivo
    assert p.name == "22 10 - saldos do sicoob.json"


def test_leitura_de_outro_dia_e_ignorada_e_estragada_nao_derruba(tmp_path):
    p = ss.caminho(tmp_path, HOJE)
    ss.gravar(_leitura(), p)
    assert ss.ler(p, HOJE + dt.timedelta(days=1)) == (None, "")
    p.write_text("{", encoding="utf-8")
    lida, aviso = ss.ler(p, HOJE)
    assert lida is None and "não consegui ler" in aviso
    assert ss.ler(tmp_path / "nao-existe.json", HOJE) == (None, "")
```

- [ ] **Step 2:** `python -m pytest tests/test_tela_do_dia_saldo_sicoob.py -q` → falha.

- [ ] **Step 3: implementar**

```python
# tela_do_dia/saldo_sicoob.py
# -*- coding: utf-8 -*-
"""Passo 1 da tela do dia, entrega 4: o saldo do BANCO das contas do Sicoob
lido sozinho. Sem tela, sem navegador (quem fala com o banco é
`extratos_sicoob.saldo`; quem roda a thread é `sicoob_na_tela`).

Qual conta do Sicoob é cada linha do painel sai do MESMO caminho da Remessa e
da conferência de agendamentos (`agendamentos_sicoob.conta_sicoob`): duas
regras para a mesma pergunta acabariam escolhendo contas diferentes. Conta de
outro banco fica digitada (spec: "só Sicoob"). Conta que diz SICOOB e o
cadastro não resolve, ou duas linhas na MESMA conta, não são preenchidas e
dizem por quê — nunca um saldo na linha errada.

O lido entra em `LinhaSaldo.banco`; o digitado (ajuste) continua valendo por
cima dele (`saldos.banco_usado`).
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import util
from pagamentos_dia import agendamentos_sicoob as ag

from . import dia_de_trabalho as ddt

VERSAO = 1
PREFIXO = "Sicoob não lido: "
MOTIVO_REPETIDA = ("duas linhas do painel apontam para a mesma conta do Sicoob "
                   "({numero}) — confira o cadastro de contas")
MOTIVO_FORA_DA_LEITURA = "esta conta não estava na leitura — clique em Reler Sicoob"
_PERFIL_EM_USO = ("already in use", "processsingleton", "existing browser session")


def _digitos(texto) -> str:
    return re.sub(r"\D", "", str(texto or ""))


@dataclass(frozen=True)
class ContaDoPainel:
    rotulo: str
    numero: str = ""        # a ler, como o seletor do Sicoob escreve ("12.345-6")
    motivo: str = ""        # do Sicoob, mas não se lê — e por quê

    @property
    def do_sicoob(self) -> bool:
        return bool(self.numero or self.motivo)


def _diz_sicoob(nome) -> bool:
    return "SICOOB" in re.findall(r"[A-Z0-9]+", util.sem_acento(str(nome or "")).upper())


def contas_do_painel(linhas, contas_erp, mapping, mapa_mc, empresas) -> list[ContaDoPainel]:
    nome_da_linha: dict[int, str] = {}
    for conta in contas_erp or []:
        if mapping.is_ignored(conta.name):
            continue
        row = mapping.resolve_account(conta)
        if row is not None:
            nome_da_linha.setdefault(row.row, conta.name)
    saida = []
    for ln in linhas:
        row = mapping.by_row(ln.linha)
        nome = nome_da_linha.get(ln.linha) or (row.erp_name if row else "") or ln.rotulo
        numero, motivo = ag.conta_sicoob(nome, mapa_mc, empresas)
        if numero:
            saida.append(ContaDoPainel(ln.rotulo, numero=numero))
        elif motivo != ag.MOTIVO_FORA_SICOOB and _diz_sicoob(nome):
            saida.append(ContaDoPainel(ln.rotulo, motivo=motivo))
        else:
            saida.append(ContaDoPainel(ln.rotulo))
    vezes = Counter(_digitos(c.numero) for c in saida if c.numero)
    return [ContaDoPainel(c.rotulo, motivo=MOTIVO_REPETIDA.format(numero=c.numero))
            if c.numero and vezes[_digitos(c.numero)] > 1 else c for c in saida]


def numeros_a_ler(contas) -> list[str]:
    vistos, saida = set(), []
    for c in contas:
        if c.numero and _digitos(c.numero) not in vistos:
            vistos.add(_digitos(c.numero))
            saida.append(c.numero)
    return saida


@dataclass
class SaldoLido:
    numero: str
    saldo: Decimal | None
    lido_em: datetime | None
    motivo: str = ""


@dataclass
class LeituraSicoob:
    data: date
    contas: dict = field(default_factory=dict)       # dígitos -> SaldoLido

    @classmethod
    def de_resultados(cls, data: date, resultados) -> "LeituraSicoob":
        return cls(data, {_digitos(r.numero): SaldoLido(r.numero, r.saldo, r.lido_em, r.motivo)
                          for r in resultados})


def aplicar(linhas, contas, leitura) -> list:
    if leitura is None:
        return list(linhas)
    por_rotulo = {c.rotulo: c for c in contas}
    saida = []
    for ln in linhas:
        c = por_rotulo.get(ln.rotulo)
        if c is None or not c.do_sicoob:
            saida.append(ln)
        elif c.motivo:
            saida.append(replace(ln, nota_banco=PREFIXO + c.motivo))
        else:
            lido = leitura.contas.get(_digitos(c.numero))
            if lido is None:
                saida.append(replace(ln, nota_banco=PREFIXO + MOTIVO_FORA_DA_LEITURA))
            elif lido.saldo is None:
                saida.append(replace(ln, nota_banco=PREFIXO + (lido.motivo or "sem motivo")))
            else:
                saida.append(replace(ln, banco=lido.saldo))
    return saida


def texto_da_hora(leitura, contas, *, lendo=None, ligado=True) -> str:
    if lendo:
        feitas, total = lendo
        return f"Lendo o Sicoob… {feitas} de {total} contas"
    if not ligado:
        return "Saldo do Sicoob: leitura ainda não ligada — digite o saldo do banco"
    if leitura is None:
        return "Sicoob ainda não lido hoje"
    a_ler = {_digitos(n) for n in numeros_a_ler(contas)} or set(leitura.contas)
    ok = [l for k, l in leitura.contas.items() if k in a_ler and l.saldo is not None]
    if not ok:
        return "Sicoob não lido — veja a situação de cada conta"
    texto = f"Sicoob lido às {min(l.lido_em for l in ok):%H:%M}"
    if len(ok) < len(a_ler):
        texto += f" · {len(ok)} de {len(a_ler)} contas (as outras: veja a situação)"
    return texto


def recado_da_falha(erro) -> str:
    texto = str(erro or "").strip()
    if any(p in texto.lower() for p in _PERFIL_EM_USO):
        return ("O Chrome do Sicoob já está aberto por outra aba (Extratos, "
                "Comprovantes ou Conferir agendamentos). Espere ela terminar e "
                "clique em Reler Sicoob.")
    primeira = (texto.splitlines() or [""])[0].strip()[:200]
    return f"Sicoob: {primeira or type(erro).__name__}"


# ---------------------------------------------------------------- o arquivo

def caminho(raiz_saida, data: date) -> Path:
    return ddt.pasta_do_dia(raiz_saida, data) / f"{data:%d %m} - saldos do sicoob.json"


def para_dict(leitura: LeituraSicoob) -> dict:
    return {"versao": VERSAO, "data": leitura.data.isoformat(), "contas": [
        {"numero": l.numero, "saldo": None if l.saldo is None else str(l.saldo),
         "lido_em": None if l.lido_em is None else l.lido_em.isoformat(timespec="seconds"),
         "motivo": l.motivo} for l in leitura.contas.values()]}


def de_dict(dados: dict, data: date) -> LeituraSicoob:
    try:
        itens = [SaldoLido(str(c["numero"]),
                           None if c.get("saldo") is None else Decimal(str(c["saldo"])),
                           None if c.get("lido_em") is None else datetime.fromisoformat(c["lido_em"]),
                           str(c.get("motivo") or ""))
                 for c in dados.get("contas") or []]
    except (KeyError, TypeError, ValueError, InvalidOperation) as e:
        raise ValueError(f"formato inesperado ({e!r})") from e
    return LeituraSicoob(data, {_digitos(i.numero): i for i in itens})


def ler(arquivo, data: date) -> tuple[LeituraSicoob | None, str]:
    """`(leitura, "")`; ausente ou de outro dia = `(None, "")`; estragado =
    `(None, aviso)`. Nunca levanta: a leitura se refaz com Reler Sicoob."""
    p = Path(arquivo)
    if not p.is_file():
        return None, ""
    try:
        dados = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(dados, dict):
            raise ValueError("o conteúdo não é um objeto")
        if str(dados.get("data")) != data.isoformat():
            return None, ""
        return de_dict(dados, data), ""
    except (OSError, ValueError) as e:
        return None, f"não consegui ler {p.as_posix()}: {e}"


def gravar(leitura: LeituraSicoob, arquivo) -> Path:
    p = Path(arquivo)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(para_dict(leitura), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    return p
```

  Na fixture, Gama diz SICOOB, mas `MAPA_MC.de` devolve None, e `_numero_pelo_nome` (`agendamentos_sicoob.py:182`) não acha número no nome. O resultado é `MOTIVO_CONTA_DESCONHECIDA`, que entra como `motivo`.

- [ ] **Step 4:** `python -m pytest tests/test_tela_do_dia_saldo_sicoob.py tests/test_tela_do_dia_saldos.py -q` → passam.

- [ ] **Step 5: commit**
```
git add tela_do_dia/saldo_sicoob.py tests/test_tela_do_dia_saldo_sicoob.py
git commit -m "Pagamentos do dia: quais linhas são do Sicoob, o saldo lido e a hora da leitura

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `LeitorSicoob` (entrada isolada) + frame + app — HOJE · sonnet

**Files:**
- Create: `tela_do_dia/sicoob_na_tela.py`
- Test: `tests/test_tela_do_dia_sicoob_na_tela.py`
- Modify: `tela_do_dia/frame.py` (`:41` imports, `:116` cartão 1, `:328` junto do `_parar_click`, `:419-442` `_receber_leitura`, `:478` `_recalcular`)
- Modify: `comprovantes_app.py` (`:322`, `:328-330`, `:635-653`)

**Interfaces:**
- Existentes:
  - `TelaDoDiaFrame._log(msg)` (`frame.py:286`, fila e thread-safe), `.mapping`, `.dia`, `.leitura`, `.periodo` (`:85-87`), `_recalcular()` (`:476`).
  - `conciliacao.frame.RAIZ_SAIDA` (`frame.py:26`).
  - `pagamentos_frame._carregar_mapas() -> (mapa_mc, empresas)` (`pagamentos_dia/pagamentos_frame.py:104`, já importado em `frame.py:33`).
  - `SicoobClient(log=…)` como context manager e `aguardar_login()` (`sicoob_client.py:108`, `:171`).
  - `ExtratosSicoobFrame.ocupado() -> str | None` (`extratos_sicoob/extratos_frame.py:207`).
  - `widgets.Botao(pai, texto, papel=…, command=…)` (`widgets.py:780`).
- Nova: `class LeitorSicoob(pai, tela)` com:
  - `.barra`, `.lbl`, `.b_reler`
  - `ocupado() -> str | None`
  - `aplicar(linhas, contas_erp, mapping) -> list[LinhaSaldo]`
  - `ler_se_faltar() -> None`
  - `reler(perguntar=True) -> None`
  - `_t_ler(numeros, data) -> None`
  - `fechar() -> None`
  - `outros_no_sicoob: Callable[[], str | None]`

- [ ] **Step 1: testes que falham**

```python
# tests/test_tela_do_dia_sicoob_na_tela.py
# -*- coding: utf-8 -*-
"""O "Reler Sicoob" sem Tk: o controlador nasce por __new__ (como em
test_abas_em_paralelo.py). Prova a thread própria e as mensagens da fila."""
import datetime as dt
import queue
import threading
from decimal import Decimal as D
from pathlib import Path

import pytest

from tela_do_dia import saldo_sicoob as ss
from tela_do_dia import sicoob_na_tela as m

HOJE = dt.date(2026, 10, 22)


class _Widget:
    def __init__(self): self.estado = {}
    def configure(self, **kw): self.estado.update(kw)


def _leitor(tela):
    l = m.LeitorSicoob.__new__(m.LeitorSicoob)
    l.tela, l.q, l._thread, l._parar = tela, queue.Queue(), None, threading.Event()
    l.leitura, l.contas, l._lendo, l._carregada_de, l._chave_contas = None, [], None, None, None
    l.outros_no_sicoob = lambda: None
    l.lbl, l.b_reler = _Widget(), _Widget()
    return l


def _tela():
    registro = []
    return type("T", (), {"mapping": object(), "dia": object(), "leitura": object(),
                          "periodo": type("P", (), {"fim": HOJE})(),
                          "_log": staticmethod(registro.append), "registro": registro})()


def test_le_numa_thread_propria_e_o_chrome_nasce_e_morre_nela(monkeypatch):
    from extratos_sicoob import saldo, sicoob_client
    threads = []

    class _Cli:
        def __init__(self, log): pass
        def __enter__(self): threads.append(threading.current_thread()); return self
        def __exit__(self, *a): threads.append(threading.current_thread())
        def aguardar_login(self): pass

    monkeypatch.setattr(sicoob_client, "SicoobClient", _Cli)
    monkeypatch.setattr(saldo, "medido", lambda: True)
    monkeypatch.setattr(saldo, "ler_contas", lambda cli, numeros, **kw: [
        saldo.Lido("12.345-6", D("10.00"), dt.datetime(2026, 10, 22, 8, 12))])
    monkeypatch.setattr(m.messagebox, "askokcancel", lambda *a, **k: True)
    l = _leitor(_tela())
    l.contas = [ss.ContaDoPainel("Alfa", numero="12.345-6")]
    l.reler(perguntar=False)
    l._thread.join(5)
    assert threads[0] is threads[1] and threads[0] is not threading.main_thread()
    assert threads[0].name == "sicoob-saldo"
    tipos = []
    while not l.q.empty():
        tipos.append(l.q.get()[0])
    assert tipos[-2:] == ["lida", "fim"]


def test_falha_vira_recado_e_a_fila_sempre_termina(monkeypatch):
    from extratos_sicoob import saldo, sicoob_client

    class _Cli:
        def __init__(self, log): pass
        def __enter__(self): raise RuntimeError("ProcessSingleton: profile in use")
        def __exit__(self, *a): pass

    monkeypatch.setattr(sicoob_client, "SicoobClient", _Cli)
    monkeypatch.setattr(saldo, "medido", lambda: True)
    l = _leitor(_tela())
    l._t_ler(["12.345-6"], HOJE)
    mensagens = [l.q.get() for _ in range(l.q.qsize())]
    assert mensagens[0][0] == "falhou" and "já está aberto" in mensagens[0][1]
    assert mensagens[-1] == ("fim", None)


def test_recusa_sem_buscar_sem_endereco_e_com_o_chrome_em_uso(monkeypatch):
    from extratos_sicoob import saldo
    avisos = []
    monkeypatch.setattr(m.messagebox, "showinfo", lambda t, msg: avisos.append(msg))
    tela = _tela()
    l = _leitor(tela)
    monkeypatch.setattr(saldo, "medido", lambda: False)
    l.reler()
    assert "ainda não está ligada" in avisos[-1] and l._thread is None
    monkeypatch.setattr(saldo, "medido", lambda: True)
    tela.mapping = None
    l.reler()
    assert "Busque os pagamentos e saldos primeiro" in avisos[-1]
    tela.mapping = object()
    l.contas = [ss.ContaDoPainel("Alfa", numero="12.345-6")]
    l.outros_no_sicoob = lambda: "Extratos Sicoob"
    l.reler()
    assert "em uso (Extratos Sicoob)" in avisos[-1] and l._thread is None


def test_ler_se_faltar_nao_abre_sem_endereco(monkeypatch):
    from extratos_sicoob import saldo
    monkeypatch.setattr(saldo, "medido", lambda: False)
    l = _leitor(_tela())
    l.contas = [ss.ContaDoPainel("Alfa", numero="12.345-6")]
    l.ler_se_faltar()
    assert l._thread is None


def test_frame_nao_abre_o_sicoob_na_thread_do_erp():
    raiz = Path(__file__).resolve().parents[1]
    frame = (raiz / "tela_do_dia" / "frame.py").read_text(encoding="utf-8")
    leitor = (raiz / "tela_do_dia" / "sicoob_na_tela.py").read_text(encoding="utf-8")
    assert "SicoobClient" not in frame
    assert "submeter(" not in leitor and "anx." not in leitor
```

- [ ] **Step 2:** `python -m pytest tests/test_tela_do_dia_sicoob_na_tela.py -q` → falha.

- [ ] **Step 3: implementar o controlador**

```python
# tela_do_dia/sicoob_na_tela.py
# -*- coding: utf-8 -*-
"""O "Reler Sicoob" e a hora da leitura — a entrada da entrega 4 na aba.

Isolado do `frame.py` de propósito (outras entregas mexem nele): o frame só
o cria no cartão 1, chama `aplicar` no recálculo e `ler_se_faltar` depois do
Buscar. A regra é `saldo_sicoob` (puro); quem fala com o banco é
`extratos_sicoob.saldo`.

**Thread própria, nunca a do ERP** (`anx.submeter`): o Sicoob é outro site e
outro login, e o Playwright síncrono só vive na thread que o criou — o
`SicoobClient` nasce e morre dentro de `_t_ler`. Uma `Thread` daemon por vez,
como o "Conferir agendamentos" (`pagamentos_frame._t_agendamentos`), e não
`ThreadPoolExecutor`: as threads dele não são daemon, e fechar o app com o
Chrome esperando o login (até 10 min) deixaria o processo vivo
(`acessorias/frame.py`, `fechar`). A tela só recebe pela fila.
"""
from __future__ import annotations

import datetime
import queue
import threading
from tkinter import messagebox, ttk

import widgets

from . import saldo_sicoob as ss

TITULO = "Reler Sicoob"


class LeitorSicoob:
    def __init__(self, pai, tela):
        self.tela = tela
        self.q = queue.Queue()
        self._thread = None
        self._parar = threading.Event()
        self.leitura = None
        self.contas = []
        self._lendo = None
        self._carregada_de = None
        self._chave_contas = None
        #: Ligado pelo app: quem mais está com o Chrome do Sicoob (Extratos).
        self.outros_no_sicoob = lambda: None
        self.barra = ttk.Frame(pai)
        self.lbl = ttk.Label(self.barra, style="Secao.TLabel", text="")
        self.lbl.pack(side="left")
        self.b_reler = widgets.Botao(self.barra, TITULO, papel="neutro", command=self.reler)
        self.b_reler.pack(side="right")
        self._mostrar_hora()
        self.barra.after(200, self._drain)

    # ------------------------------------------------------------ perguntas
    def ocupado(self) -> str | None:
        t = self._thread
        return "Pagamentos do dia — lendo o Sicoob" if t is not None and t.is_alive() else None

    @staticmethod
    def _ligado() -> bool:
        try:
            from extratos_sicoob import saldo
            return saldo.medido()
        except Exception:                                    # noqa: BLE001
            return False

    def _data(self) -> datetime.date:
        periodo = getattr(self.tela, "periodo", None)
        return periodo.fim if periodo is not None else datetime.date.today()

    # ----------------------------------------- chamado pelo recálculo (tela)
    def aplicar(self, linhas, contas_erp, mapping):
        from conciliacao.frame import RAIZ_SAIDA
        data = self._data()
        if self._carregada_de != data:
            self._carregada_de = data
            if self.leitura is None or self.leitura.data != data:
                self.leitura, aviso = ss.ler(ss.caminho(RAIZ_SAIDA, data), data)
                if aviso:
                    self.tela._log(f"[!] {aviso}")
        chave = (id(contas_erp), id(mapping))
        if chave != self._chave_contas:
            self._chave_contas = chave
            try:
                from pagamentos_dia.pagamentos_frame import _carregar_mapas
                mapa_mc, empresas = _carregar_mapas()
                self.contas = ss.contas_do_painel(linhas, contas_erp, mapping, mapa_mc, empresas)
            except Exception as e:                           # noqa: BLE001
                self.contas = []
                self.tela._log(f"[!] Sicoob: não consegui ler o cadastro de contas ({e}); "
                               "o saldo do banco fica digitado.")
        self._mostrar_hora()
        leitura = self.leitura if self.leitura is not None and self.leitura.data == data else None
        return ss.aplicar(linhas, self.contas, leitura)

    # ------------------------------------------------------------- ações
    def ler_se_faltar(self):
        """Fim do Buscar (spec: o Buscar também lê o Sicoob) — só quando ainda
        não há leitura de hoje, e nunca com o endereço ainda não medido."""
        if self.leitura is None and self._ligado() and not self.ocupado() \
                and ss.numeros_a_ler(self.contas):
            self.reler(perguntar=False)

    def reler(self, perguntar=True):
        if self.ocupado():
            return
        if not self._ligado():
            from extratos_sicoob import saldo
            messagebox.showinfo(TITULO, saldo.NAO_MEDIDO[0].upper() + saldo.NAO_MEDIDO[1:] + ".")
            return
        if self.tela.mapping is None or self.tela.dia is None:
            messagebox.showinfo(TITULO, "Busque os pagamentos e saldos primeiro: é a leitura "
                                        "do ERP que diz quais contas do painel são do Sicoob.")
            return
        numeros = ss.numeros_a_ler(self.contas)
        if not numeros:
            messagebox.showinfo(TITULO, "Nenhuma conta do painel é do Sicoob (ou o cadastro não "
                                        "diz qual é) — o saldo do banco fica digitado.")
            return
        quem = self.outros_no_sicoob()
        if quem:
            messagebox.showinfo(TITULO, f"O Chrome do Sicoob está em uso ({quem}). Espere "
                                        "terminar: os dois usariam o mesmo perfil do banco.")
            return
        if perguntar and not messagebox.askokcancel(
                TITULO, f"Vou abrir o Chrome do Sicoob e ler o saldo de {len(numeros)} "
                        "conta(s), trocando de conta uma a uma.\n\nÉ só leitura: nada é "
                        "pago, agendado nem alterado no banco.\n\nFaça o login quando a "
                        "janela abrir."):
            return
        self._parar.clear()
        self.b_reler.configure(state="disabled")
        self._lendo = (0, len(numeros))
        self._mostrar_hora()
        self._thread = threading.Thread(target=self._t_ler, args=(numeros, self._data()),
                                        name="sicoob-saldo", daemon=True)
        self._thread.start()

    def _t_ler(self, numeros, data):
        """Thread do Sicoob. Só fala com a tela pela fila; sempre termina com "fim"."""
        try:
            from extratos_sicoob import saldo
            from extratos_sicoob.sicoob_client import SicoobClient

            def registrar(msg):
                self.tela._log(f"  Sicoob: {msg}")

            with SicoobClient(log=registrar) as cli:
                cli.aguardar_login()
                lidos = saldo.ler_contas(
                    cli, numeros, parar=self._parar.is_set, log=registrar,
                    progresso=lambda f, t: self.q.put(("lendo", (f, t))))
            self.q.put(("lida", ss.LeituraSicoob.de_resultados(data, lidos)))
        except Exception as e:                               # noqa: BLE001
            self.q.put(("falhou", ss.recado_da_falha(e)))
        finally:
            self.q.put(("fim", None))

    # ------------------------------------------------------------- tela
    def _drain(self):
        try:
            while True:
                tipo, valor = self.q.get_nowait()
                if tipo == "lendo":
                    self._lendo = valor
                elif tipo == "lida":
                    self._receber(valor)
                elif tipo == "falhou":
                    self.tela._log(f"[!] {valor}")
                elif tipo == "fim":
                    self._lendo = None
                    self.b_reler.configure(state="normal")
                self._mostrar_hora()
        except queue.Empty:
            pass
        except Exception as e:                               # noqa: BLE001
            self.tela._log(f"[!] falha ao mostrar o Sicoob na tela: {e!r}")
        finally:
            self.barra.after(200, self._drain)

    def _receber(self, leitura):
        from conciliacao.frame import RAIZ_SAIDA
        self.leitura, self._carregada_de = leitura, leitura.data
        try:
            ss.gravar(leitura, ss.caminho(RAIZ_SAIDA, leitura.data))
        except Exception as e:                               # noqa: BLE001
            self.tela._log(f"[!] não consegui guardar a leitura do Sicoob ({e}); "
                           "ela vale até fechar o app.")
        for lido in leitura.contas.values():
            if lido.saldo is None:
                self.tela._log(f"  Sicoob {lido.numero}: não lido — {lido.motivo}")
        if self.tela.dia is not None and self.tela.leitura is not None:
            self.tela._recalcular()

    def _mostrar_hora(self):
        self.lbl.configure(text=ss.texto_da_hora(self.leitura, self.contas,
                                                 lendo=self._lendo, ligado=self._ligado()))

    def fechar(self):
        self._parar.set()
```

- [ ] **Step 4: fiação no frame (só estas linhas)**

```python
# tela_do_dia/frame.py — imports (junto de :37-42)
from .sicoob_na_tela import LeitorSicoob

# _build, no cartão 1, ANTES de `self.t_saldos = self._tabela(...)` (:116)
        # Entrega 4: a hora da leitura do Sicoob e o "Reler Sicoob" no alto do
        # passo 1 (spec). Tudo do Sicoob mora em `sicoob_na_tela`.
        self.sicoob = LeitorSicoob(c1, tela=self)
        self.sicoob.barra.pack(fill="x", pady=px((6, 0)))

# junto do _parar_click (:328) — o `_sair` do app chama `fechar` de toda aba
    def fechar(self):
        self.sicoob.fechar()

# _receber_leitura (:419), ÚLTIMA linha do método
        self.sicoob.ler_se_faltar()

# _recalcular (:478-479)
        base = sd.montar_saldos(self.contas_erp, self.mapping)
        base = self.sicoob.aplicar(base, self.contas_erp, self.mapping)
        self.saldos = sd.ordenar(sd.aplicar_ajustes(base, self.dia.ajustes))
```

  O texto de ajuda do cartão 1 (`:112-115`) ganha, no fim: "Nas contas do Sicoob o banco vem lido (Reler Sicoob refaz); o digitado vale por cima do lido."

- [ ] **Step 5: fiação no app** (`comprovantes_app.py`)

```python
# depois de `aba_dia.aba_remessa = aba_pag` (:330)
    # Pagamentos do dia lê o saldo do Sicoob no MESMO perfil do banco: ela
    # pergunta aos Extratos, e o "Conferir agendamentos" da Remessa passa a
    # perguntar às duas (só acrescenta uma recusa; nada mais muda nela).
    aba_dia.sicoob.outros_no_sicoob = aba_ext.ocupado
    aba_pag.sicoob_ocupado = lambda: aba_ext.ocupado() or aba_dia.sicoob.ocupado()

# em `_quem_trabalha` (:635-653), logo depois de `lambda: ("ext", aba_ext.ocupado()),`
                lambda: ("dia", aba_dia.sicoob.ocupado()),
```

  Remover a linha antiga `aba_pag.sicoob_ocupado = aba_ext.ocupado` (`:322`), porque ela é substituída pela nova, que vem depois da criação de `aba_dia`.

- [ ] **Step 6:** `python -m pytest tests/test_tela_do_dia_sicoob_na_tela.py tests/test_abas_em_paralelo.py tests/test_tela_do_dia_inicio.py -q`, depois `ruff check --select E9,F tela_do_dia comprovantes_app.py` e `python -m pytest tests/test_empacotamento.py tests/test_imports_do_motor.py -q`.

- [ ] **Step 7: commit**
```
git add tela_do_dia/sicoob_na_tela.py tests/test_tela_do_dia_sicoob_na_tela.py tela_do_dia/frame.py comprovantes_app.py
git commit -m "Pagamentos do dia: botão Reler Sicoob e a hora da leitura no passo 1

Thread própria, fora da do ERP; o frame só cria o leitor e o chama no recálculo.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Documentação e suíte inteira — HOJE · haiku

**Files:**
- Modify: `.claude/rules/arquitetura-tela-do-dia.md`, `.claude/rules/arquitetura-extratos-sicoob.md`, `.claude/rules/arquitetura-ferramentas.md`

- [ ] **Step 1:** em `arquitetura-tela-do-dia.md`:
  - Na tabela "Quem decide o quê", acrescentar as linhas `saldo_sicoob.py` ("passo 1: qual conta do Sicoob é cada linha, o lido, a hora, o JSON `DD MM - saldos do sicoob.json`") e `sicoob_na_tela.py` ("o Reler Sicoob: thread própria daemon, fila").
  - Nova seção "Saldo do Sicoob (entrega 4)", que diz:
    - o digitado vale sobre o lido, com a razão da spec;
    - o lido que muda depois do ajuste vira âmbar;
    - o Buscar lê o Sicoob só sem leitura de hoje;
    - o reler substitui;
    - outro banco fica digitado;
    - duas linhas na mesma conta e Sicoob sem cadastro não são preenchidas;
    - `ROTA_SALDO` vazio desliga tudo sem abrir o Chrome.
  - Atualizar a frase "saldo do dia = banco se digitado, senão sistema" para "banco (digitado, senão lido do Sicoob), senão sistema".
- [ ] **Step 2:** em `arquitetura-extratos-sicoob.md`, um parágrafo sobre o `saldo.py`:
  - par de `pendencias.py`;
  - confere o cabeçalho antes de pedir;
  - o bloco de constantes é o ÚNICO lugar do endereço;
  - `EnderecoMudou` para a fila;
  - a sonda que mede.
- [ ] **Step 3:** em `arquitetura-ferramentas.md`, um parágrafo sobre `sonda_saldo_sicoob.py`:
  - abre pelo `SicoobClient` com o perfil da instalação (`--app`);
  - escuta só depois do login;
  - só nomes de cabeçalho;
  - recusa gravar no repo;
  - modo `--provar`.
- [ ] **Step 4:** suíte inteira: `ruff check --select E9,F .` e depois `python -m pytest tests -q`. Tudo verde.
- [ ] **Step 5: commit**
```
git add .claude/rules/arquitetura-tela-do-dia.md .claude/rules/arquitetura-extratos-sicoob.md .claude/rules/arquitetura-ferramentas.md
git commit -m "docs: saldo do Sicoob na tela do dia, a leitura e a sonda

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8 (FINAL, AMANHÃ 22/10): medir com o dono e plugar o endereço — opus + dono

**Só se completa com o dono logado.** Só leitura. Antes disso, as Tasks 1–7 estão no branch e a leitura fica desligada.

**O que exatamente se troca:** SÓ o bloco de constantes de `extratos_sicoob/saldo.py`:
- `ROTA_SALDO`, com `{conta}` se a sonda marcar `conta_no_endereco: true`;
- `METODO_SALDO`;
- `CORPO_SALDO`, com `"{conta}"` onde `conta_no_pedido: true`;
- `CAMPO_SALDO`;
- `CAMPO_SINAL` (se o saldo vier sem sinal e com indicador D/C);
- `CAMPO_CONTA` (se a resposta disser a conta).

Mais a docstring ("medido em 22/10/2026") e dois testes novos. Nenhum outro arquivo de código muda.

**Files:**
- Modify: `extratos_sicoob/saldo.py` (o bloco `# ===… O ENDEREÇO E O EXTRATOR`)
- Modify: `tests/test_sicoob_saldo.py`
- Modify: `.claude/rules/arquitetura-extratos-sicoob.md` (data da medição e endereço)

- [ ] **Step 1 (dono):** fechar o app e rodar, a partir da pasta do worktree: `python -m ferramentas.sonda_saldo_sicoob --app "<pasta do Comprovantes Mais Controle.exe>"`. Seguir o PASSO A PASSO impresso: login, conta A com saldo anotado, ⇄ para a conta B com saldo anotado, ENTER, digitar os dois saldos.
- [ ] **Step 2 (coordenador):** abrir o JSON (local, fora do repo) e escolher a resposta que:
  - aparece para A e para B com o MESMO `endereco`;
  - traz `"<caminho> = saldo da tela"` nas duas;
  - é um JSON pequeno de conta, e não o extrato.

  Confirmar com o dono qual saldo é o do painel: o saldo em conta SEM limite e sem bloqueado. Olhar `cabecalhos`: com nome não-padrão de autorização, ver o passo 5b.
- [ ] **Step 3: teste do formato medido** (falha até as constantes serem preenchidas). Copiar a ESTRUTURA do `retrato` com valores inventados:

```python
def test_formato_medido_em_22_10():
    """Estrutura do Sicoob medida pela sonda em 22/10/2026; valores fictícios."""
    corpo = '<JSON fictício com a MESMA estrutura do retrato escolhido>'
    assert S.medido()
    assert S.interpretar({"status": 200, "corpo": corpo}, "12.345-6") == D("1234.56")
```

  O placeholder do `corpo` é preenchido no ato com a estrutura real e números inventados. Nada do arquivo da sonda é copiado com valor real, conta ou nome.
- [ ] **Step 4:** preencher as constantes (exemplo de forma, não de conteúdo):

```python
ROTA_SALDO = "/api/<caminho medido>"     # sem dígitos de conta; "{conta}" se a conta vai no endereço
METODO_SALDO = "GET"                     # ou "POST", como a sonda mostrou
CORPO_SALDO = None                       # ou o dict do pedido com "{conta}"
CAMPO_SALDO = "<caminho com pontos>"     # o marcado "= saldo da tela"
CAMPO_SINAL = ""
CAMPO_CONTA = ""                         # preencher se a resposta trouxer a conta
```

  Rodar `python -m pytest tests/test_sicoob_saldo.py -q`. Passam o teste do formato e também `test_endereco_no_repositorio_nao_carrega_numero_de_conta`.
- [ ] **Step 5 (dono):** prova ao vivo: `python -m ferramentas.sonda_saldo_sicoob --app "<pasta>" --provar 3`. O dono confere os três saldos com a tela do banco.
  - **5b, contingência:** se der `HTTP 401/403` com a sessão viva (o endereço exige um cabeçalho que o `fetch` com `credentials:'include'` não leva), NÃO plugar. Deixar `ROTA_SALDO = ""`, porque a build sai com o saldo digitado como hoje. Registrar o achado no `.superpowers/sdd/progress.md` e avisar o dono. O caminho seguinte, que é ler a resposta que a própria Home recebe (como `_escutar`, `baixar_comprovantes/sicoob_baixar.py:459`), vira um plano à parte.
- [ ] **Step 6:** acrescentar em `tests/test_sicoob_saldo.py` o teste `def test_leitura_ligada(): assert S.medido()`. Atualizar a docstring do `saldo.py` e o `arquitetura-extratos-sicoob.md` com a data da medição. Depois `python -m pytest tests -q`.
- [ ] **Step 7: commit**
```
git add extratos_sicoob/saldo.py tests/test_sicoob_saldo.py .claude/rules/arquitetura-extratos-sicoob.md
git commit -m "Sicoob: endereço do saldo medido em 22/10 e leitura ligada

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
- [ ] **Step 8 (dono, no app com a prévia travada):** "Buscar pagamentos e saldos" → login no Chrome do Sicoob → coluna BANCO preenchida, "Sicoob lido às HH:MM" no alto. Digitar um banco à mão numa conta do Sicoob → vale o digitado. "Reler Sicoob" → hora nova.

---

## Riscos

1. A API pode exigir um cabeçalho de autorização que o `fetch` não leva (a pendência e os comprovantes não exigiram). A sonda mostra os nomes, e o 5b deixa a leitura desligada sem quebrar a build.
2. O "saldo" do Sicoob pode vir com limite, bloqueado ou projetado. A escolha do `CAMPO_SALDO` é feita com o dono; um campo errado daria um número plausível e errado, que só o "não bate" com o ERP denuncia.
3. String de dinheiro sem vírgula ("1.234") seria lida como 1,23. O formato medido amanhã decide, e o teste do formato o fixa.
4. Já enviado + saldo lido conta em dobro: a remessa já debitada no Sicoob continua no "a pagar" (`progress.md`, menor adiado da entrega 1). O efeito é um mínimo alto, que é o lado conservador. Fica registrado no PR.
5. O perfil do Sicoob abre num Chrome por vez. Extratos e Baixar Comprovantes não sabem desta aba e falham com "perfil em uso"; aqui isso vira recado claro. O ● da barra mostra quem está lendo.
6. São cerca de 20 trocas de conta com a sessão de 20 min. O cabeçalho ⇄ some depois de várias trocas; o `entrar` recarrega e tenta de novo, e sessão caída para a fila e marca as que faltavam.
7. Mapeamento: conta do Sicoob fora do cadastro ou duas linhas na mesma conta ficam âmbar e digitadas. A entrega 2 ("uma lista de contas só") pode trocar `contas_do_painel` sem mexer no resto.
8. A sonda roda com o Playwright do ambiente de desenvolvimento, não o do exe. Os argumentos de abertura são os mesmos (`SicoobClient`), mas uma versão diferente do Chrome/Playwright pode mudar o retrato do PC; o `--app` garante o perfil já reconhecido.
9. O endereço muda sem aviso (precedente de 25/09). `EnderecoMudou` para tudo com o endereço no recado, e o caminho à mão continua.

### Critical Files for Implementation
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2\extratos_sicoob\saldo.py (novo; constantes trocadas em 22/10)
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2\ferramentas\sonda_saldo_sicoob.py (novo)
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2\tela_do_dia\saldo_sicoob.py (novo) e tela_do_dia\sicoob_na_tela.py (novo)
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2\tela_do_dia\saldos.py (modificado)
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2\tela_do_dia\frame.py e comprovantes_app.py (fiação mínima)