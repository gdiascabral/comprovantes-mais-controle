# Aba Conciliação (Baixar OFX + Provar saldos) — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uma aba "Conciliação" (grupo DIÁRIO) com dois ambientes: "Baixar OFX" (Sicoob + Inter → importa no Mais Controle) e "Provar saldos" (a prova de hoje, levada de Pagamentos do dia); e o passo mensal "Baixar extratos do Inter" na aba Acessórias.

**Architecture:** Regras num módulo puro (`conciliacao_dia/ofx_regras.py`); três motores finos, cada um com seu navegador e sua thread como já é no app (Sicoob no `SicoobClient`, Inter no perfil da conta, ERP na vaga do Anexar pelo porteiro); uma rodada sem tela que encadeia os três com dublês nos testes; o frame só desenha e chama. A Prova de saldos continua em `tela_do_dia/prova_*`; muda só quem a hospeda.

**Tech Stack:** Python 3.11, tkinter/ttk + `widgets.py`, Playwright sync (Chrome do app), pytest.

**Spec:** `docs/superpowers/specs/2026-10-29-conciliacao-ofx-design.md`

## Global Constraints

- Python 3.11 (`vermin --target=3.11-` sobre o que mudou); `ruff check --select E9,F .`.
- ERP só pelo Chrome do app (porteiro, `anx.submeter(..., dona=aba)` com `anx.avisar_se_ocupado(dona, aba=...)` antes); nunca login HTTP por fora.
- Bancos só como o app abre: `SicoobClient` (perfil `.chrome_profile_sicoob`, pt-BR, NUNCA porta de depuração); Inter em `inter_baixar.pasta_do_perfil(apelido)`.
- Nada real no repositório (nome, conta, CPF/CNPJ, saldo); testes com dados fictícios.
- A conta ignorada pelo dono é sempre ignorada (lista em `conciliacao_ofx.json`, fora do repositório).
- Período padrão: ontem a hoje; início ≤ fim ≤ hoje; no máximo 2 anos (730 dias).
- OFX que não confere (ACCTID, DTSTART/DTEND) NÃO é importado.
- Pasta nova `conciliacao_dia/` = linha nova no `build.yml` + `tests/test_empacotamento.py`; mexer no `build.yml` = `motor_minimo.txt` de `v2.0.234` para `v2.0.235` no MESMO commit.
- Tkinter só na thread da interface (`queue` + `after`); Playwright só na thread dona.
- Testes de janela só com "tela livre" do dono; os demais sem janela antes de juntar.
- Português em toda mensagem de tela.

## Review Focus

1. **QR lido na empresa errada no celular** (medido 29/10): a conta aberta é outra → nada baixado dessa conta, resultado "leia o QR com a empresa X escolhida no celular" (Task 3).
2. **Conta do ERP sem número no Inter** (Buritis): o ACCTID do OFX se confere contra o número da TELA, nunca contra o cadastro vazio; sem número na tela → não baixa (Task 3).
3. **OFX vazio de lançamento** (fim de semana): confere conta e período e importa normalmente; o resultado mostra 0 lançamentos, não "falhou" (Task 1).
4. **Parar no meio da importação**: o que já foi importado fica "importado", o resto "não importado: parado"; nenhuma conta some do resultado (Task 5).
5. **Duas linhas da lista com a mesma conta do Sicoob** (painel com duas linhas no mesmo número): uma só entra, a outra diz por quê — nunca dois uploads do mesmo OFX (Task 1).

---

### Task 1: Regras puras (`conciliacao_dia/ofx_regras.py`)

**Files:**
- Create: `conciliacao_dia/__init__.py` (docstring de uma linha)
- Create: `conciliacao_dia/ofx_regras.py`
- Test: `tests/test_conciliacao_dia_ofx_regras.py`

**Interfaces:**
- Consumes: `pagamentos_dia.agendamentos_sicoob.conta_sicoob(nome, mapa_mc, empresas) -> (numero, motivo)`; `tela_do_dia.prova_saldos.e_inter(banco)`, `prova_saldos.digitos(t)`; `conciliacao.models.ErpAccount` (`id`, `name`, `account_number`); `baixar_comprovantes.contas_inter.ContaInter` (`apelido`, `empresa`).
- Produces:
  - `SICOOB = "SICOOB"`, `INTER = "INTER"`, `ignoradas()` (cadastro fora do repositório)
  - `@dataclass(frozen=True) ContaOfx(erp_id: str, nome: str, banco: str, numero: str = "", apelido: str = "", do_dia: bool = False, motivo: str = "")`
  - `contas_para_ofx(contas_erp, mapping, mapa_mc, empresas, contas_inter, linhas_do_dia) -> list[ContaOfx]` — `linhas_do_dia` = números de linha do painel (`saldos.montar_saldos(...)`); ordem: do dia (pela linha) e depois as outras (pelo nome); Sicoob pelo `conta_sicoob`, Inter pelo `mapa_mc.de(nome).banco` + empresa com UM login; conta ignorada pelo dono fora; número repetido → as seguintes com `motivo=REPETIDA`.
  - `periodo_padrao(hoje: date) -> tuple[date, date]` (ontem, hoje)
  - `validar_periodo(ini: date, fim: date, hoje: date) -> str` ("" = ok)
  - `conferir_ofx(texto: str, numero: str, ini: date, fim: date) -> str` ("" = confere)
  - `lancamentos(texto: str) -> int`
  - `nome_do_arquivo(conta: ContaOfx) -> str` ("<dígitos>.ofx"; Inter sem número → "inter <apelido>.ofx")
  - `@dataclass Resultado(conta: ContaOfx, situacao: str, lancamentos: int | None = None, motivo: str = "")` com `IMPORTADO="importado"`, `NAO_IMPORTADO="não importado"`
  - `linha_do_resultado(r: Resultado) -> tuple` (conta, período, lançamentos, situação + motivo)

- [ ] **Step 1: Escrever os testes**

```python
# tests/test_conciliacao_dia_ofx_regras.py
"""Regras do Baixar OFX: lista, período, conferência do OFX. Dados fictícios."""
import datetime as dt
from types import SimpleNamespace as NS

from conciliacao_dia import ofx_regras as r

D = dt.date
OFX = ("OFXHEADER:100\n<OFX><BANKACCTFROM><ACCTID>0012345-6</ACCTID></BANKACCTFROM>"
       "<BANKTRANLIST><DTSTART>20261028</DTSTART><DTEND>20261029</DTEND>"
       "<STMTTRN><TRNAMT>1.00</TRNAMT></STMTTRN><STMTTRN><TRNAMT>-2.00</TRNAMT></STMTTRN>")


def test_periodo_padrao_e_ontem_a_hoje():
    assert r.periodo_padrao(D(2026, 10, 29)) == (D(2026, 10, 28), D(2026, 10, 29))


def test_validar_periodo():
    hoje = D(2026, 10, 29)
    assert r.validar_periodo(D(2026, 10, 28), hoje, hoje) == ""
    assert "depois" in r.validar_periodo(D(2026, 10, 29), D(2026, 10, 28), hoje)
    assert "futuro" in r.validar_periodo(D(2026, 10, 28), D(2026, 10, 30), hoje)
    assert "2 anos" in r.validar_periodo(D(2024, 10, 28), hoje, hoje)


def test_conferir_ofx_conta_e_periodo():
    assert r.conferir_ofx(OFX, "12.345-6", D(2026, 10, 28), D(2026, 10, 29)) == ""
    assert "conta" in r.conferir_ofx(OFX, "99.999-9", D(2026, 10, 28), D(2026, 10, 29))
    assert "período" in r.conferir_ofx(OFX, "12.345-6", D(2026, 10, 27), D(2026, 10, 29))
    assert "ACCTID" in r.conferir_ofx("<OFX></OFX>", "12.345-6", D(2026, 10, 28), D(2026, 10, 29))
    assert "número" in r.conferir_ofx(OFX, "", D(2026, 10, 28), D(2026, 10, 29))


def test_ofx_sem_lancamento_confere_e_conta_zero():
    vazio = OFX.split("<STMTTRN>")[0]
    assert r.conferir_ofx(vazio, "12.345-6", D(2026, 10, 28), D(2026, 10, 29)) == ""
    assert r.lancamentos(vazio) == 0 and r.lancamentos(OFX) == 2


def _mapa(destinos):
    return NS(de=lambda nome: destinos.get(nome))


def test_lista_do_dia_primeiro_ignorada_fora_e_repetida_diz_por_que(monkeypatch):
    numeros = {"ALFA - SICOOB": "12.345-6", "BETA - SICOOB": "12.345-6",
               "GAMA - SICOOB": "99.990-0", "DELTA - SICOOB": "23.456-7"}
    monkeypatch.setattr(r.ag, "conta_sicoob",
                        lambda nome, mapa, emp: (numeros.get(nome, ""), "" if nome in numeros else "x"))
    contas_erp = [NS(id=f"id{i}", name=n, account_number="") for i, n in
                  enumerate(["DELTA - SICOOB", "ALFA - SICOOB", "BETA - SICOOB", "GAMA - SICOOB",
                             "EPSILON - INTER"])]
    linha_de = {"ALFA - SICOOB": 8, "BETA - SICOOB": 9}
    mapping = NS(is_ignored=lambda n: False,
                 resolve_account=lambda c: NS(row=linha_de[c.name], exists_in_erp=True)
                 if c.name in linha_de else None)
    mapa = _mapa({"EPSILON - INTER": NS(banco="077", empresa="EMPRESA E")})
    inter = [NS(apelido="E", empresa="EMPRESA E")]
    lista = r.contas_para_ofx(contas_erp, mapping, mapa, [], inter, linhas_do_dia={8, 9})
    assert [(c.nome, c.do_dia) for c in lista] == [
        ("ALFA - SICOOB", True), ("BETA - SICOOB", True),
        ("DELTA - SICOOB", False), ("EPSILON - INTER", False)]
    assert lista[1].motivo == r.REPETIDA and lista[0].motivo == ""
    assert lista[3].banco == r.INTER and lista[3].apelido == "E"


def test_nome_do_arquivo():
    assert r.nome_do_arquivo(r.ContaOfx("i", "A", r.SICOOB, numero="12.345-6")) == "123456.ofx"
    assert r.nome_do_arquivo(r.ContaOfx("i", "B", r.INTER, apelido="MORAIS ENG")) == "inter MORAIS ENG.ofx"
```

- [ ] **Step 2: Rodar e ver falhar** — `python -m pytest tests/test_conciliacao_dia_ofx_regras.py -q` → `ModuleNotFoundError: conciliacao_dia`.

- [ ] **Step 3: Implementar**

```python
# conciliacao_dia/ofx_regras.py
# -*- coding: utf-8 -*-
"""Baixar OFX (aba Conciliação): a regra, sem tela, sem rede, sem navegador.

Quais contas aparecem e em que grupo, o período, e se um OFX é mesmo o da
conta e o do período pedido. OFX que não confere não chega ao ERP."""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass

import util
from pagamentos_dia import agendamentos_sicoob as ag
from tela_do_dia import prova_saldos as ps

SICOOB, INTER = ps.SICOOB, ps.INTER
#: Regra do dono (23/10/2026): as ignoradas vêm de conciliacao_ofx.json.
MAX_DIAS = 730                      # o Inter aceita até 2 anos
REPETIDA = "outra linha da lista já baixa esta conta"
INTER_SEM_LOGIN = "esta conta do Inter não tem login na lista do app (contas_inter.json)"
INTER_DOIS_LOGINS = "a empresa tem mais de um login do Inter na lista — não sei qual abrir"
IMPORTADO, NAO_IMPORTADO = "importado", "não importado"
_RE_ACCTID = re.compile(r"<ACCTID>([^<\r\n]*)")
_RE_DT = re.compile(r"<(DTSTART|DTEND)>(\d{8})")


@dataclass(frozen=True)
class ContaOfx:
    erp_id: str
    nome: str
    banco: str
    numero: str = ""
    apelido: str = ""
    do_dia: bool = False
    motivo: str = ""


@dataclass
class Resultado:
    conta: ContaOfx
    situacao: str
    lancamentos: int | None = None
    motivo: str = ""


def _dig(t) -> str:
    return ps.digitos(t).lstrip("0")


def periodo_padrao(hoje: _dt.date) -> tuple[_dt.date, _dt.date]:
    return hoje - _dt.timedelta(days=1), hoje


def validar_periodo(ini: _dt.date, fim: _dt.date, hoje: _dt.date) -> str:
    if ini > fim:
        return "a data de início é depois da data de fim"
    if fim > hoje:
        return "a data de fim está no futuro"
    if (fim - ini).days > MAX_DIAS:
        return "o período passa de 2 anos (o Inter não exporta mais que isso)"
    return ""


def conferir_ofx(texto: str, numero: str, ini: _dt.date, fim: _dt.date) -> str:
    if not _dig(numero):
        return "não sei o número desta conta — não confiro o OFX sem ele"
    achado = _RE_ACCTID.search(texto or "")
    if not achado:
        return "o arquivo não tem ACCTID — não parece um OFX"
    if _dig(achado.group(1)) != _dig(numero):
        return f"o OFX é da conta {achado.group(1).strip()}, e esta é a {numero}"
    datas = dict(_RE_DT.findall(texto))
    esperado = (f"{ini:%Y%m%d}", f"{fim:%Y%m%d}")
    if (datas.get("DTSTART"), datas.get("DTEND")) != esperado:
        return (f"o período do OFX é {datas.get('DTSTART')}–{datas.get('DTEND')}, "
                f"e o pedido foi {esperado[0]}–{esperado[1]}")
    return ""


def lancamentos(texto: str) -> int:
    return (texto or "").count("<STMTTRN>")


def nome_do_arquivo(conta: ContaOfx) -> str:
    d = ps.digitos(conta.numero)
    return f"{d}.ofx" if d else f"inter {conta.apelido}.ofx"


def contas_para_ofx(contas_erp, mapping, mapa_mc, empresas, contas_inter,
                    linhas_do_dia) -> list[ContaOfx]:
    linha_da_conta = {}
    for c in contas_erp or []:
        if mapping.is_ignored(c.name):
            continue
        row = mapping.resolve_account(c)
        if row is not None and row.exists_in_erp:
            linha_da_conta[c.id] = row.row
    achadas = []
    for c in contas_erp or []:
        do_dia = linha_da_conta.get(c.id) in set(linhas_do_dia or ())
        numero, _motivo = ag.conta_sicoob(c.name, mapa_mc, empresas)
        if numero:
            if _dig(numero) in IGNORAR:
                continue
            achadas.append(ContaOfx(str(c.id), c.name, SICOOB, numero=numero, do_dia=do_dia))
            continue
        destino = mapa_mc.de(c.name) if mapa_mc is not None else None
        if destino is None or not ps.e_inter(destino.banco):
            continue
        empresa = util.norm_espaco(destino.empresa)
        logins = [i for i in contas_inter or [] if util.norm_espaco(i.empresa) == empresa]
        motivo = "" if len(logins) == 1 else (INTER_SEM_LOGIN if not logins else INTER_DOIS_LOGINS)
        achadas.append(ContaOfx(str(c.id), c.name, INTER,
                                numero=ps.digitos(getattr(c, "account_number", "") or ""),
                                apelido=logins[0].apelido if len(logins) == 1 else "",
                                do_dia=do_dia, motivo=motivo))
    achadas.sort(key=lambda c: (not c.do_dia,
                                linha_da_conta.get(c.erp_id, 0) if c.do_dia else 0,
                                util.norm_espaco(c.nome)))
    vistas, saida = set(), []
    for c in achadas:
        chave = (c.banco, _dig(c.numero) or c.apelido)
        if chave in vistas and not c.motivo:
            c = ContaOfx(**{**c.__dict__, "motivo": REPETIDA})
        vistas.add(chave)
        saida.append(c)
    return saida


def linha_do_resultado(r: Resultado, ini: _dt.date, fim: _dt.date) -> tuple:
    situacao = r.situacao + (f": {r.motivo}" if r.motivo else "")
    return (r.conta.nome, f"{ini:%d/%m} a {fim:%d/%m}",
            "—" if r.lancamentos is None else str(r.lancamentos), situacao)
```

- [ ] **Step 4: Rodar e ver passar** — mesmo comando → PASS. Acrescentar um teste para `linha_do_resultado` (importado com 0 lançamentos mostra "0"; não importado sem leitura mostra "—").
- [ ] **Step 5: Commit** — `git add conciliacao_dia tests/test_conciliacao_dia_ofx_regras.py && git commit -m "Conciliação: regras puras do Baixar OFX"`

---

### Task 2: OFX do Sicoob por período (`extratos_sicoob/ofx_periodo.py`)

**Files:**
- Create: `extratos_sicoob/ofx_periodo.py`
- Test: `tests/test_sicoob_ofx_periodo.py`

**Interfaces:**
- Consumes: `SicoobClient` (já logado): `.page`, `._clicar_dia(cal, dia)`, `.texto_periodo()`, `.abrir_extrato()`, `.definir_ordenacao()`, `.exportar_ofx(destino)`; `extratos_sicoob.saldo.entrar(cli, numero, lista)` (entra na conta pelos dígitos e confere o cabeçalho); `sicoob_client.TEMPO_PADRAO`.
- Produces: `definir_intervalo(cli, ini, fim) -> None` (levanta `PeriodoNaoMarcou`), `baixar(cli, contas, ini, fim, pasta, *, lista, parar, log, progresso) -> dict[str, tuple[Path | None, str]]` — chave = dígitos da conta; valor `(arquivo, "")` ou `(None, porquê)`; conta fora deste login → motivo `saldo.FORA_DESTE_LOGIN` (a rodada usa para oferecer o outro acesso).

- [ ] **Step 1: Teste com dublê do cliente** — dublê com `page.locator(...).first.click/wait_for/select_option`, `texto_periodo()` devolvendo o período marcado, `exportar_ofx(destino)` gravando um texto. Casos: (a) duas contas, cada uma grava `<dígitos>.ofx` na pasta; (b) `texto_periodo` diferente do pedido → `(None, "o período ficou …")`, sem exportar; (c) `saldo.entrar` levantando `ContaNaoEncontrada(FORA_DESTE_LOGIN)` → motivo `FORA_DESTE_LOGIN` e segue a próxima; (d) `parar()` verdadeiro antes da 2ª → `(None, "parado")`.
- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar** — levar `definir_intervalo` de `ferramentas/ofx-periodo/baixar_ofx.py` (o código está lá, provado em 23/10/2026: `p-calendar input` → `.ui-datepicker` → `select.ui-datepicker-month` (mês-1) e `-year` → `cli._clicar_dia(cal, d.day)` duas vezes → "Confirmar" → confere `f"{ini:%d/%m/%Y} - {fim:%d/%m/%Y}" in cli.texto_periodo()`). Para cada conta: `saldo.entrar(cli, numero, lista)` → `cli.abrir_extrato()` → `cli.definir_ordenacao()` → `definir_intervalo` → `cli.exportar_ofx(pasta / f"{dígitos}.ofx")`. Erro de uma conta não derruba as outras (motivo na linha); `saldo.SessaoPerdida` para a fila e marca o resto.
- [ ] **Step 4: Ver passar.**
- [ ] **Step 5: Commit** — "Sicoob: OFX de um período, conta por conta".

---

### Task 3: OFX do Inter por período (`baixar_comprovantes/inter_ofx.py`)

**Files:**
- Create: `baixar_comprovantes/inter_ofx.py`
- Test: `tests/test_inter_ofx.py`

**Interfaces:**
- Consumes: `inter_saldo.escutar_sessao(page) -> dict`, `inter_saldo._abrir(page, url)`, `inter_saldo.conferir_conta(texto, numero, nomes, razoes) -> str`, `inter_saldo.SEM_PRINT_OUTRA_CONTA`; `inter_baixar.pasta_do_perfil`, `.esperar_login(page, tempo, log, parar)`, `.URL_LOGIN`, `._texto_da_tela(page)`, `.numero_no_texto(texto)`, `.TEMPO_LOGIN`, `.InterFalhou`.
- Produces:
  - `URL_EXPORTAR = "https://cd.web.bancointer.com.br/ib-pfj/cc/extrato/exportar/v2"`
  - `url_do_ofx(ini: date, fim: date) -> str` (`?formato=OFX&data-inicio=DD-MM-AAAA&data-fim=DD-MM-AAAA`)
  - `@dataclass(frozen=True) OfxInter(arquivo: Path | None, numero_na_tela: str = "", motivo: str = "")`
  - `baixar_conta(apelido, numero_erp, nomes, razoes, ini, fim, arquivo, *, log, avisar_qr, parar, tempo_login=ib.TEMPO_LOGIN) -> OfxInter` — nunca levanta.

- [ ] **Step 1: Testes** — `url_do_ofx(date(2026,10,28), date(2026,10,29))` termina em `formato=OFX&data-inicio=28-10-2026&data-fim=29-10-2026`; `_baixar_na_pagina` com dublê de página: (a) conta errada na tela (texto com outro número) → `OfxInter(None, motivo=…"outra conta aberta"…)` e NENHUM `evaluate` de download; (b) sem número na tela → motivo `inter_saldo.SEM_NUMERO`, sem download; (c) sem `authorization` na sessão → motivo "a página do Inter não abriu a sessão"; (d) resposta `{status: 200}` + download → `OfxInter(arquivo, numero_na_tela="123456789")`; (e) resposta `{status: 412}` → motivo com "HTTP 412". O ACCTID do arquivo NÃO é conferido aqui (Task 5 confere contra `numero_na_tela` quando o ERP não tem o número).
- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar** — mesmo esqueleto de `inter_saldo._ler_no_chrome` (perfil da conta, `--start-maximized`, `no_viewport=True`, `accept_downloads=True`, `sessao = inter_saldo.escutar_sessao(page)`, `_abrir(URL_LOGIN)`, `avisar_qr`, `esperar_login`, `_abrir(URL_LOGIN)` de novo, `sessao.clear()` no `finally`). Na página: conferir a conta ANTES (`conferir_conta(ib._texto_da_tela(page), numero_erp, nomes, razoes)`); depois, dentro de `page.expect_download(timeout=60000)`:

```python
_JS_OFX = """
async ([url, cabecalhos]) => {
    const r = await fetch(url, {headers: cabecalhos});
    if (!r.ok) return {status: r.status};
    const j = await r.json();
    if (!j || !j.fileUrl) return {status: r.status, semArquivo: true};
    const a = document.createElement('a');
    a.href = j.fileUrl; a.download = '';
    document.body.appendChild(a); a.click(); a.remove();
    return {status: r.status};
}
"""
```

  (medido 29/10/2026: a API responde `{fileUrl}` de um S3 assinado que recusa `fetch`; o `<a>` faz o Chrome baixar). `status != 200` ou `semArquivo` → motivo, e o `expect_download` estourando vira "o Inter não entregou o arquivo". Mensagem da conta errada: "a tela do Inter abriu outra conta — leia o QR com a empresa certa escolhida no celular".
- [ ] **Step 4: Ver passar.**
- [ ] **Step 5: Commit** — "Inter: OFX de um período pela sessão da página".

---

### Task 4: Importar no ERP (`conciliacao_dia/importar_erp.py`)

**Files:**
- Create: `conciliacao_dia/importar_erp.py`
- Test: `tests/test_conciliacao_dia_importar_erp.py`

**Interfaces:**
- Consumes: `anx.mc._nova_aba_do_robo()`, `anx.mc._minhas` (set), `erp.hosts.ACESSAR`.
- Produces: `TEXTO_BOTAO = "Selecionar novo OFX"`, `TEXTO_OK = "Arquivo OFX importado com sucesso"`, `importar(mc, pedidos, *, log, parar) -> dict[str, tuple[bool, str]]` — `pedidos = [(erp_id, nome, arquivo)]`; UMA aba do robô para todos, fechada e retirada de `_minhas` no fim; chave = `erp_id`.

- [ ] **Step 1: Testes com dublê de página** (estilo de `tests/test_tela_do_dia_prova_erp.py`): (a) dois pedidos → `goto(.../#/transactions/<id>)` para cada, `set_files(arquivo)` no file chooser, `(True, "")`; uma aba só aberta e fechada; (b) `erp_id` fora do padrão UUID (`[0-9A-Fa-f-]{8,64}`) → `(False, "o ERP não deu o identificador desta conta")` sem `goto`; (c) o texto de sucesso não aparece → `(False, "o ERP não confirmou a importação")` e segue para o próximo; (d) `parar()` → os que faltam `(False, "parado")`; (e) aba que não abre → todos com o motivo.
- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar** — por pedido: `aba.goto(f"{hosts.ACESSAR}/#/transactions/{erp_id}", wait_until="domcontentloaded")`; `aba.get_by_text(nome.strip(), exact=False).first.wait_for(timeout=40000)`; `aba.get_by_text(TEXTO_BOTAO).first.wait_for(timeout=40000)`; `with aba.expect_file_chooser(timeout=15000) as fc: aba.get_by_text(TEXTO_BOTAO).first.click()`; `fc.value.set_files(str(arquivo))`; `aba.get_by_text(TEXTO_OK).first.wait_for(timeout=40000)` (o mesmo caminho de `ferramentas/ofx-periodo/importar_todos.py`, provado em 23/10/2026). Só esses cliques; nada concilia.
- [ ] **Step 4: Ver passar.**
- [ ] **Step 5: Commit** — "Conciliação: importar OFX no ERP pela tela, numa aba do robô".

---

### Task 5: A rodada sem tela (`conciliacao_dia/rodada.py`)

**Files:**
- Create: `conciliacao_dia/rodada.py`
- Test: `tests/test_conciliacao_dia_rodada.py`

**Interfaces:**
- Consumes: Tasks 1–4 (`ofx_regras.*`, `ofx_periodo.baixar`, `inter_ofx.baixar_conta`, `importar_erp.importar`); `extratos_sicoob.saldo.FORA_DESTE_LOGIN`.
- Produces: `rodar(contas: list[ContaOfx], ini, fim, pasta, *, sicoob, inter, erp, perguntar_outro_acesso, avisar, parar, log) -> list[Resultado]` — `sicoob(contas, pasta) -> dict`, `inter(conta, arquivo) -> OfxInter`, `erp(pedidos) -> dict` são injetados (o frame passa os de verdade, os testes passam dublês); `avisar(estado: str)` alimenta o rótulo. UMA `Resultado` por conta pedida, na ordem da lista.

- [ ] **Step 1: Testes com dublês**: (a) ordem Sicoob → Inter → ERP, e só os OFX que conferem chegam ao `erp`; (b) OFX de outra conta → `NAO_IMPORTADO` com o motivo de `conferir_ofx`, e o `erp` não o recebe; (c) Inter sem número no ERP confere contra `OfxInter.numero_na_tela`; (d) conta com `motivo` (repetida, sem login) → `NAO_IMPORTADO` com ele, sem baixar; (e) Sicoob que volta `FORA_DESTE_LOGIN` → `perguntar_outro_acesso(faltam)` chamado; "não" deixa essas com o motivo; (f) `parar` depois do 1º import → 1 `IMPORTADO`, o resto `NAO_IMPORTADO: parado`, nenhuma conta some; (g) OFX vazio importado mostra `lancamentos == 0`.
- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar** — a ordem acima; `conferir_ofx(texto, conta.numero or ofx.numero_na_tela, ini, fim)`; texto lido com `encoding="cp1252", errors="replace"`.
- [ ] **Step 4: Ver passar.**
- [ ] **Step 5: Commit** — "Conciliação: a rodada Sicoob → Inter → ERP, sem tela".

---

### Task 6: A aba Conciliação (frame, menu, empacotamento, travas, Prova)

**Files:**
- Create: `conciliacao_dia/frame.py`
- Modify: `comprovantes_app.py` (import, `aba_cdi = ConciliacaoDiaFrame(conteudo, aba_anx)`, `quadros["cdi"]`, `_grupo("diario", ...)` ganha `("cdi", "🔁", "Conciliação")`, travas: `aba_cdi.prova.outros_no_sicoob` e `aba_cdi.outros_no_sicoob` como as de `aba_dia.prova` hoje; `aba_bxc.inter_ocupado = lambda: aba_cdi.prova.ocupado() or aba_cdi.ocupado()`; os `outros_no_sicoob` de `aba_dia.sicoob`/`agendamentos`, `aba_pag.sicoob_ocupado`, `aba_ext.sicoob_ocupado`, `aba_bxc.sicoob_ocupado` passam a perguntar também à `aba_cdi`)
- Modify: `tela_do_dia/frame.py` (sai o `ProvaNaTela`; entra o link — Task 7)
- Modify: `.github/workflows/build.yml` (bloco `conciliacao_dia/` ao lado do `tela_do_dia/`), `motor_minimo.txt` (`v2.0.235`), `tests/test_empacotamento.py`
- Test: `tests/test_conciliacao_dia_frame.py` (de janela: só com "tela livre")

**Interfaces:**
- Consumes: Tasks 1–5; `tela_do_dia.prova_na_tela.ProvaNaTela(pai, tela)` — o hospedeiro precisa ter `anx`, `cfg`, `mapping`, `contas_erp`, `_log(msg)`, `_abrir(alvo)` (estático), `_pasta_pagamentos()`; `conciliacao.config.load_config`, `conciliacao.mapping.AccountMapping.load`, `tela_do_dia.erp_do_dia.ler_saldos(cfg, api, log=)`, `tela_do_dia.saldos.montar_saldos`.
- Produces: `ConciliacaoDiaFrame(master, anexar_frame)` com `.prova` (ProvaNaTela), `.ocupado() -> str | None`, `.outros_no_sicoob`, `.fechar()`.

- [ ] **Step 1: Testes de janela** (fixture `raiz`): a aba monta e o ambiente "Baixar OFX" tem altura > 0 dentro da área que rola (a armadilha da v2.0.208); a lista nasce toda desmarcada; o período nasce ontem/hoje; "Baixar e importar" desabilitado até "Ler as contas do ERP" terminar e uma conta ser marcada; `prova.ligar(True)` só depois da leitura.
- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar** — `BarraTopo` "Conciliação"; botão "Ler as contas do ERP" (na vaga do Anexar: `garantir_sessao` → `load_config`/`AccountMapping.load` de `util.pasta_base()` → `erp_do_dia.ler_saldos`; guarda `cfg`, `mapping`, `contas_erp`; monta a lista com `ofx_regras.contas_para_ofx(..., linhas_do_dia={l.linha for l in montar_saldos(contas_erp, mapping)})`, cadastros por `prova_na_tela._carregar_cadastros()`); Treeview com caixa de marcar (☐/☑) e os dois grupos, "Marcar todas" por grupo; dois `CampoData`; "Baixar e importar" (thread `ofx-bancos` para Sicoob e Inter + `anx.submeter("Conciliação — importar OFX", importar_erp.importar, ...)` para o ERP, pela `rodada.rodar`); rótulo, Parar, tabela do resultado (`linha_do_resultado`); pasta `util.pasta_base()/"Pagamentos do dia"/"OFX"/f"{agora:%Y-%m-%d %Hh%M}"`. Segundo ambiente "Provar saldos": `self.prova = ProvaNaTela(caixa, tela=self)`, com `ligar(True)` depois da leitura do ERP.
- [ ] **Step 4: Rodar** `python -m pytest tests -q -m "not janela"`-equivalente desta suíte (sem janela) e os de janela só com "tela livre"; `tests/test_empacotamento.py` e `tests/test_abas_em_paralelo.py` (o frame entra em `_CHAMADORES` se usar `anx.submeter`).
- [ ] **Step 5: Commit** — "Aba Conciliação: Baixar OFX e Provar saldos".

---

### Task 7: Link em Pagamentos do dia

**Files:**
- Modify: `tela_do_dia/frame.py` (linhas ~202-203 e as chamadas `self.prova.*` em ~478, ~600, ~607, ~689), `comprovantes_app.py` (depois de definida a `mostrar(nome)` local, `aba_dia.ir_para_conciliacao = lambda: mostrar("cdi")`)
- Test: `tests/test_tela_do_dia_prova_na_tela.py` (ajustar: a prova não é mais filha da `TelaDoDiaFrame`)

- [ ] **Step 1: Teste** — a `TelaDoDiaFrame` tem um botão-link "Prova de saldos → aba Conciliação" que chama `self.ir_para_conciliacao()` (atributo ligado pelo app; padrão `lambda: None`); não tem mais `self.prova`; `sicoob_ocupado()` não pergunta mais por ela.
- [ ] **Step 2–4:** falhar, implementar, passar.
- [ ] **Step 5: Commit** — "Pagamentos do dia: a Prova de saldos foi para a aba Conciliação".

---

### Task 8: Extratos do Inter na rotina mensal (aba Acessórias)

**Files:**
- Modify: `acessorias/frame.py` (botão "Baixar extratos do Inter" antes de "Gerar os .zip"), `conciliacao_dia/ofx_regras.py` (`periodo_do_mes(ano, mes) -> (date, date)`)
- Test: `tests/test_conciliacao_dia_ofx_regras.py` (`periodo_do_mes(2026, 2) == (date(2026,2,1), date(2026,2,28))`), `tests/test_acessorias_inter.py` (dublê do `inter_ofx.baixar_conta`)

**Interfaces:**
- Consumes: `inter_ofx.baixar_conta`, `ofx_regras.conferir_ofx`, `baixar_comprovantes.contas_inter.carregar()`, `extratos_sicoob.sicoob_pastas.caminho_do_mes(mapa, ano, mes)`.
- Produces: o OFX de cada conta Inter em `caminho_do_mes(...)/<empresa>/<pasta da conta>/<dígitos>.ofx`, conferido conta + mês inteiro; nada vai ao ERP.

- [ ] **Step 1: Testes** — o mês inteiro é pedido; OFX de outra conta não é gravado na pasta; QR da empresa errada vira linha no Registro com o porquê.
- [ ] **Step 2–4:** falhar, implementar no executor PRÓPRIO da aba (não no do ERP), passar. Antes de abrir, perguntar ao `inter_ocupado` (Baixar comprovantes / Conciliação).
- [ ] **Step 5: Commit** — "Acessórias: extratos do Inter do mês para o fechamento".

---

### Task 9: Documentação, revisão e prova ao vivo

**Files:**
- Modify: `.claude/rules/arquitetura-tela-do-dia.md` (a Prova mudou de hospedeiro), `.claude/rules/arquitetura-acessorias.md`, criar `.claude/rules/arquitetura-conciliacao-dia.md` e a linha dele na tabela do `CLAUDE.md`.

- [ ] **Step 1:** atualizar os três arquivos de regra.
- [ ] **Step 2:** suíte inteira sem janela + `ruff --select E9,F .` + `vermin --target=3.11-` nos arquivos mudados.
- [ ] **Step 3:** `revisor-dinheiro` sobre o diff inteiro do branch (importar OFX mexe no ERP); consertar o que ele achar, com teste.
- [ ] **Step 4:** com "tela livre": testes de janela; depois, a prévia travada nesta máquina e uma rodada real: ontem a hoje em 2 contas Sicoob + 1 Inter, importando de verdade, e a Prova de saldos pela aba nova com o PDF mostrado ao dono.
- [ ] **Step 5:** PR; juntar e liberar só com o ok do dono.
