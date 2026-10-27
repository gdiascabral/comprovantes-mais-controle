# Prova de saldos (ERP × banco) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um botão "📸 Prova de saldos" no cartão Saldos da aba Pagamentos do dia que lê o saldo atual de cada conta Sicoob e Inter do painel no ERP e no banco, tira um print de cada tela, compara em centavos e gera um PDF (resumo + uma página por conta) na pasta `Pagamentos do dia/`.

**Architecture:** Regra pura em `tela_do_dia/prova_saldos.py` (quais contas, ✅/❌/⚠ em centavos); PDF desenhado com o Pillow que já vai no exe (`tela_do_dia/prova_pdf.py`); três leitores, cada um no navegador e na thread do seu dono — ERP pela vaga do Anexar (`anx.submeter`, aba própria do robô no Chrome do app, fechada no fim), Sicoob pelo `extratos_sicoob.saldo` de sempre com um gancho `ao_ler` que fotografa, Inter por um módulo novo `baixar_comprovantes/inter_saldo.py` no perfil de cada conta. Um controlador `tela_do_dia/prova_na_tela.py` (thread daemon `prova-saldos`, fila + `after`, Parar) junta tudo e abre a pasta no fim; ele entra na trava "quem espera quem" do Chrome do Sicoob e do Inter.

**Tech Stack:** Python 3.11 (alvo do exe), tkinter/ttk, Playwright sync, Pillow 12.3 (já no `requirements.lock`), `decimal.Decimal`, pytest.

**Spec:** `docs/superpowers/specs/2026-10-27-prova-de-saldos-design.md`

## Global Constraints

- **Python 3.11**: nada de API mais nova; `python -m vermin --target=3.11 --violations <arquivos>` limpo em cada tarefa.
- **Lint**: `python -m ruff check --select E9,F <arquivos>` limpo em cada tarefa.
- **Só leitura** no ERP e nos bancos: nenhum clique que mexa em dinheiro; nada de assinar, cancelar, aprovar ou transferir. Os únicos cliques permitidos: "Exibir valores" (olho) e "próxima página" na grade `#/accounts` do ERP, e o "gerar um novo QR" que `inter_baixar.esperar_login` já faz.
- **ERP só pelo Chrome do app**: a leitura dos saldos é `tela_do_dia.erp_do_dia.ler_saldos` (central ligado → porteiro; desligado → aba do robô). Nunca `POST /users/login` por HTTP.
- **Playwright fora da thread Tk**: ERP na vaga do Anexar (`anx.submeter(..., dona=tela)`), Sicoob e Inter na `Thread` daemon `prova-saldos`; a tela só recebe pela fila (`queue` + `after`).
- **Recusar antes de apagar botões** ("Um navegador, seis abas"): toda recusa sai antes de `configure(state="disabled")`, antes de `_parar.clear()` e antes de pôr qualquer coisa na fila.
- **`avisar_se_ocupado(aba=X)` e `submeter(dona=X)` com o MESMO X** no arquivo novo (`tests/test_abas_em_paralelo.py::_CHAMADORES` passa a incluir `tela_do_dia/prova_na_tela.py`).
- **Conta incerta não bate**: falha, conta errada na tela, valor que não chegou → ⚠ com motivo; o número nunca sai de uma imagem.
- **Dinheiro em `Decimal`**, comparado em centavos (`quantize(Decimal("0.01"), ROUND_HALF_UP)`).
- **Testes puros sem Tk real**: controladores nascem por `__new__` com dublês de widget; o `messagebox` é o dublê autouse do `tests/conftest.py` (perguntas respondem "não"); nenhum teste abre Chrome, banco ou ERP.
- **Repo público**: nenhum nome real de empresa/pessoa, número de conta real, CPF/CNPJ em código, teste ou comentário; testes usam "EMPRESA FICTICIA", "12.345-6", "123456789".
- **LF** nos arquivos (o `.gitattributes` normaliza; não salvar com BOM).
- **Sem dependência nova nem exe novo**: só Pillow (já no exe) e o que o app já importa; nenhum submódulo novo da stdlib (`concurrent.futures` já é usado pelo app; `TimeoutError` é o builtin no 3.11).
- **Sem pasta nova de código**: arquivos novos em `tela_do_dia/`, `baixar_comprovantes/` e `util.py`, que já vão no `codigo.zip` (`build.yml`, linhas 463 e 475) — `build.yml` e `motor_minimo.txt` NÃO mudam.
- **Cores do PDF** são tuplas RGB em `prova_pdf.py` (papel impresso, não tema da tela); nunca hexadecimal nem cor com nome em string — `tests/test_visual.py::test_nenhuma_cor_fixa_fora_do_widgets` varre isso.
- **Nomes de teste** `tests/test_tela_do_dia_prova_*.py` (o mapa `.claude/rules/arquitetura-tela-do-dia.md` carrega por esse padrão).
- **Caminho mostrado ao usuário com "/"** (`Path.as_posix()`).
- **Commit por tarefa** com `git add <novos>` + `git commit -m "<mensagem em português>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- <arquivos>`; nunca push na `main`.

## Review Focus

1. **O perfil do Inter abre OUTRA conta** (sessão de outro login, ou o banco troca a conta da tela): a linha vira ⚠ "outra conta aberta" e nunca recebe saldo. Teste: Tarefa 3 (`test_outra_conta_aberta_nao_le`, `test_nome_de_outra_empresa_nao_le`) e Tarefa 6 (`test_inter_com_conta_errada_vira_nao_lida`).
2. **A resposta do saldo do Inter muda de forma ou a sessão vence** (sem `disponivel`, `null`, texto "1.234,56", HTTP 401): ⚠ com o motivo, nunca R$ 0,00. Teste: Tarefa 3 (`test_resposta_sem_disponivel_valido_nao_vira_saldo`, `test_sessao_vencida_e_erro_do_banco`).
3. **Painel com mais contas do que cabem numa página do resumo** (≥ 19 linhas): o resumo continua na página seguinte, nenhuma conta some. Teste: Tarefa 2 (`test_resumo_longo_quebra_em_paginas_sem_perder_linha`).
4. **Outro dono com o Chrome do banco** (Reler Sicoob, Conferir agendamentos, Extratos, Baixar comprovantes — inclusive só Inter): a prova recusa ANTES de apagar botão ou abrir navegador; e o Baixar comprovantes com conta Inter marcada recusa enquanto a prova roda. Teste: Tarefa 6 (`test_chrome_do_banco_em_uso_recusa_antes_de_tudo`, `test_baixar_inter_recusa_durante_a_prova`).
5. **O ERP falha ou não responde, ou a pessoa clica Parar no meio**: ERP com erro → todas as linhas ⚠ "ERP: …" e o PDF sai mesmo assim; Parar → nenhum PDF, recado claro, botões voltam. Teste: Tarefa 6 (`test_erp_que_falha_vira_nao_lida_e_o_pdf_sai`, `test_parar_nao_gera_pdf_e_diz_por_que`).

## Modelo por tarefa

| Tarefa | Implementa | Revisa | Por quê |
|---|---|---|---|
| 1 regra pura | sonnet | sonnet | código e testes inteiros no plano |
| 2 PDF | sonnet | sonnet | Pillow, sem decisão de dinheiro |
| 3 Inter | sonnet | opus | conta errada = saldo de uma empresa na linha de outra |
| 4 Sicoob | sonnet | opus | mexe num motor compartilhado (`extratos_sicoob/saldo.py`) |
| 5 ERP | sonnet | opus | thread da vaga, aba do robô, regra do ERP pelo Chrome do app |
| 6 orquestração | opus | opus | threads, travas entre abas, fiação no app |
| 7 mapas | haiku | sonnet | só texto |
| 8 prova ao vivo | sessão principal com o dono | — | abre ERP/bancos: só com o dono na máquina |

## Decisões que o revisor deve conhecer

- **Aba do ERP**: o spec cita `AbaCentral`; o plano usa a aba do robô do `MCClient` da vaga (`mc._nova_aba_do_robo()`), fechada no fim. Motivo: a vaga já tem um `sync_playwright` vivo naquela thread (um segundo `AbaCentral()` sem `pw=` subiria outro na mesma thread), e com o central DESLIGADO não existe Chrome central — a aba do robô é "a aba própria no Chrome do app" nos dois modos.
- **Ordem**: ERP e bancos correm em PARALELO (vaga do Anexar × thread `prova-saldos`); cada leitura carrega a própria hora, que vai para a tabela.
- **Parar** vale entre contas; a espera do QR do Inter (`esperar_login`, até 300 s) não é interrompida no meio.
- **Situação no PDF** sai em palavra colorida ("BATE", "NÃO BATE", "NÃO LIDA"): Arial/Segoe UI não têm os glifos ✅/❌; os emojis ficam no Registro da aba.

---

## File Structure

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `tela_do_dia/prova_saldos.py` | criar | regra pura: contas da prova, leituras, comparação em centavos, células, nomes de arquivo |
| `tela_do_dia/prova_pdf.py` | criar | PDF com Pillow: resumo (paginado) + uma página por conta |
| `util.py` | modificar | `fotografar(alvo, arquivo) -> str` — print que nunca levanta |
| `baixar_comprovantes/inter_baixar.py` | modificar | `numero_no_texto(texto)` puro; `conta_da_pagina` passa a usá-lo |
| `baixar_comprovantes/inter_saldo.py` | criar | saldo atual de UMA conta Inter: perfil, QR, conferência da conta, `disponivel`, print |
| `extratos_sicoob/saldo.py` | modificar | gancho `ao_ler(page, numero)` em `ler_contas` e `ler_em_dois_acessos` |
| `tela_do_dia/prova_sicoob.py` | criar | leitura do Sicoob com print por conta |
| `tela_do_dia/prova_erp.py` | criar | saldo atual do ERP por linha + print da linha na grade `#/accounts` |
| `tela_do_dia/prova_na_tela.py` | criar | botão, recusas, thread, fila, Parar, abrir a pasta |
| `tela_do_dia/frame.py` | modificar | cria a `ProvaNaTela` no cartão 1; liga/desliga; `sicoob_ocupado`; `fechar` |
| `comprovantes_app.py` | modificar | trava entre abas (Sicoob e Inter) |
| `baixar_comprovantes/comprovantes_frame.py` | modificar | `inter_ocupado` + `_inter_em_uso` |
| `tests/test_tela_do_dia_prova_saldos.py` | criar | Tarefa 1 |
| `tests/test_tela_do_dia_prova_pdf.py` | criar | Tarefa 2 |
| `tests/test_util_fotografar.py` | criar | Tarefa 3 |
| `tests/test_inter_saldo.py` | criar | Tarefa 3 |
| `tests/test_sicoob_saldo.py` | modificar | Tarefa 4 (gancho `ao_ler`) |
| `tests/test_tela_do_dia_prova_sicoob.py` | criar | Tarefa 4 |
| `tests/test_tela_do_dia_prova_erp.py` | criar | Tarefa 5 |
| `tests/test_tela_do_dia_prova_na_tela.py` | criar | Tarefa 6 |
| `tests/test_tela_do_dia_agendamentos.py` | modificar | Tarefa 6 (`t.prova` no teste do `sicoob_ocupado`) |
| `tests/test_abas_em_paralelo.py` | modificar | Tarefa 6 (`_CHAMADORES`) |
| `tests/test_sicoob_disputado.py` | modificar | Tarefa 6 (Baixar Inter × prova) |
| `.claude/rules/arquitetura-tela-do-dia.md`, `arquitetura-extratos-sicoob.md`, `arquitetura-util.md` | modificar | Tarefa 7 |

---

### Task 1: Regra pura da prova (`prova_saldos`)

**Files:**
- Create: `tela_do_dia/prova_saldos.py`
- Test: `tests/test_tela_do_dia_prova_saldos.py`

**Interfaces:**
- Consumes (já existem): `tela_do_dia.saldo_sicoob.contas_do_painel(linhas, contas_erp, mapping, mapa_mc, empresas) -> list[ContaDoPainel]`, `ss.PREFIXO`, `ContaDoPainel(rotulo, numero="", motivo="")` com `.do_sicoob`; `tela_do_dia.valores.brl(Decimal|None) -> str` (`None` → "—"); `util.norm_espaco(str) -> str`; `mapping.is_ignored(nome)`, `mapping.resolve_account(ErpAccount) -> ModelRow|None`, `mapping.by_row(int) -> ModelRow|None`; `ModelRow.row/.erp_name/.account_number/.exists_in_erp`; `ErpAccount.id/.name/.account_number`; `mapa_mc.de(nome_erp) -> Destino|None` com `.banco`, `.empresa`; `ContaInter.apelido/.empresa`; empresa do `sicoob_contas` com `.nome`, `.razao_social`.
- Produces:
  - constantes `SICOOB = "SICOOB"`, `INTER = "INTER"`, `BATE`, `NAO_BATE`, `NAO_LIDA`, `MARCA: dict[str,str]`, `PALAVRA: dict[str,str]`, `COLUNAS: tuple[str,...]`, `NAO_LIDO`, `INTERROMPIDA`, `INTER_FORA_DA_LISTA`, `INTER_DOIS_LOGINS`, `INTER_REPETIDA`
  - `digitos(texto) -> str`; `chave_inter(apelido) -> str`; `e_inter(banco) -> bool`
  - `@dataclass(frozen=True) ContaDaProva(linha: int, rotulo: str, banco: str, numero: str = "", apelido: str = "", nomes: tuple[str, ...] = (), erp_id: str = "", motivo: str = "")`
  - `@dataclass(frozen=True) Leitura(saldo: Decimal | None, lido_em: datetime | None = None, motivo: str = "", imagem: Path | None = None, sem_imagem: str = "")`
  - `@dataclass(frozen=True) LinhaDaProva(conta: ContaDaProva, erp: Leitura, banco: Leitura, situacao: str, diferenca: Decimal | None, motivo: str)`
  - `conta_erp_da_linha(contas_erp, mapping) -> dict[int, ErpAccount]`
  - `contas_da_prova(linhas, contas_erp, mapping, mapa_mc, empresas, contas_inter) -> list[ContaDaProva]`
  - `banco_por_linha(contas, sicoob: dict[str, Leitura], inter: dict[str, Leitura]) -> dict[int, Leitura]` (sicoob por `digitos(numero)`, inter por `chave_inter(apelido)`)
  - `comparar(conta, erp: Leitura, banco: Leitura) -> LinhaDaProva`
  - `montar(contas, erp: dict[int, Leitura], banco: dict[int, Leitura]) -> list[LinhaDaProva]`
  - `contagem(linhas) -> dict[str, int]`; `texto_da_contagem(linhas) -> str`; `hora(leitura) -> str`
  - `celulas(linha, com_marca: bool = True) -> tuple[str, ...]` (na ordem de `COLUNAS`)
  - `texto_do_registro(linha) -> str`; `nome_base(agora: datetime) -> str`; `nome_do_print(linha: int, lado: str) -> str`

- [ ] **Step 1: Write the failing test**

`tests/test_tela_do_dia_prova_saldos.py`:

```python
# -*- coding: utf-8 -*-
"""A regra da Prova de saldos, sem tela nem rede. Contas e valores fictícios."""
import datetime as dt
from decimal import Decimal as D
from types import SimpleNamespace as NS

from conciliacao.models import ErpAccount, ModelRow
from tela_do_dia import prova_saldos as ps
from tela_do_dia import saldo_sicoob as ss
from tela_do_dia import saldos as sd
from baixar_comprovantes.contas_inter import ContaInter

AGORA = dt.datetime(2026, 10, 27, 14, 5)
ALFA = ps.ContaDaProva(8, "CONTA ALFA", ps.SICOOB, numero="12.345-6")
BETA = ps.ContaDaProva(9, "CONTA BETA", ps.INTER, apelido="BETA")


class _Mapa:
    def __init__(self, rows):
        self.rows = rows

    @property
    def live_rows(self):
        return [r for r in self.rows if r.exists_in_erp]

    def is_ignored(self, nome):
        return False

    def resolve_account(self, conta):
        return next((r for r in self.rows if r.erp_name == conta.name), None)

    def by_row(self, n):
        return next((r for r in self.rows if r.row == n), None)


class _MapaMc:
    def __init__(self, destinos):
        self.destinos = destinos

    def de(self, nome):
        return self.destinos.get(nome)


def _l(valor, motivo=""):
    return ps.Leitura(None if valor is None else D(valor), AGORA if valor else None, motivo)


def test_bate_em_centavos_com_arredondamento():
    assert ps.comparar(ALFA, _l("100.004"), _l("100.00")).situacao == ps.BATE
    assert ps.comparar(ALFA, _l("10.005"), _l("10.01")).situacao == ps.BATE
    linha = ps.comparar(ALFA, _l("10.00"), _l("10.00"))
    assert (linha.diferenca, linha.motivo) == (D("0.00"), "")


def test_nao_bate_mostra_a_diferenca_banco_menos_erp():
    linha = ps.comparar(ALFA, _l("1500.00"), _l("1499.90"))
    assert linha.situacao == ps.NAO_BATE
    assert linha.diferenca == D("-0.10")
    assert linha.motivo == "diferença de -R$ 0,10"


def test_sem_leitura_de_um_lado_e_nao_lida_com_o_motivo():
    sem_banco = ps.comparar(ALFA, _l("1.00"), _l(None, "esta conta não aparece neste login do Sicoob"))
    assert sem_banco.situacao == ps.NAO_LIDA and sem_banco.diferenca is None
    assert sem_banco.motivo == "banco: esta conta não aparece neste login do Sicoob"
    sem_erp = ps.comparar(ALFA, _l(None, "o ERP não trouxe o saldo desta conta"), _l("1.00"))
    assert sem_erp.motivo == "ERP: o ERP não trouxe o saldo desta conta"
    assert ps.comparar(ALFA, _l(None), _l(None)).motivo == "ERP: não lido"


def test_conta_com_motivo_nunca_bate_mesmo_com_valores_iguais():
    conta = ps.ContaDaProva(9, "CONTA BETA", ps.INTER, motivo=ps.INTER_DOIS_LOGINS)
    linha = ps.comparar(conta, _l("5.00"), _l("5.00"))
    assert linha.situacao == ps.NAO_LIDA and linha.motivo == ps.INTER_DOIS_LOGINS


def test_inter_com_outra_conta_aberta_vira_nao_lida():
    linha = ps.comparar(BETA, _l("5.00"), _l(None, "outra conta aberta, não leio"))
    assert linha.situacao == ps.NAO_LIDA and "outra conta aberta" in linha.motivo


def test_montar_ordena_pela_linha_e_preenche_o_que_falta():
    linhas = ps.montar([BETA, ALFA], {8: _l("1.00")}, {8: _l("1.00")})
    assert [l.conta.linha for l in linhas] == [8, 9]
    assert linhas[0].situacao == ps.BATE
    assert linhas[1].situacao == ps.NAO_LIDA and linhas[1].motivo == "ERP: não lido"


def test_contagem_e_registro():
    linhas = [ps.comparar(ALFA, _l("1.00"), _l("1.00")),
              ps.comparar(BETA, _l("1.00"), _l("2.00"))]
    assert ps.contagem(linhas) == {ps.BATE: 1, ps.NAO_BATE: 1, ps.NAO_LIDA: 0}
    assert ps.texto_da_contagem(linhas) == "1 batem, 1 não batem, 0 não lidas"
    assert ps.texto_do_registro(linhas[1]) == (
        "  ❌ CONTA BETA: ERP R$ 1,00 · banco R$ 2,00 — diferença de R$ 1,00")


def test_celulas_na_ordem_das_colunas():
    linha = ps.comparar(ALFA, _l("1500.00"), _l("1499.90"))
    assert ps.celulas(linha) == ("CONTA ALFA", "R$ 1.500,00", "R$ 1.499,90", "-R$ 0,10",
                                 "❌ não bate", "14:05", "14:05")
    assert ps.celulas(linha, com_marca=False)[4] == "não bate"
    vazia = ps.comparar(BETA, _l(None), _l(None))
    assert ps.celulas(vazia)[1:4] == ("—", "—", "—") and ps.celulas(vazia)[5:] == ("—", "—")


def test_nomes_de_arquivo():
    assert ps.nome_base(AGORA) == "Prova de saldos 2026-10-27 14h05"
    assert ps.nome_do_print(8, "erp") == "08 erp.png"


def test_banco_por_linha_casa_sicoob_pelos_digitos_e_inter_pelo_apelido():
    contas = [ALFA, BETA, ps.ContaDaProva(10, "X", ps.INTER, motivo="m")]
    lidas = ps.banco_por_linha(contas, {"123456": _l("1.00")}, {"BETA": _l("2.00")})
    assert lidas == {8: _l("1.00"), 9: _l("2.00")}


def _cenario():
    rows = [ModelRow(8, "ALFA SICOOB", erp_name="ALFA SICOOB"),
            ModelRow(9, "BETA INTER", erp_name="BETA INTER"),
            ModelRow(10, "GAMA CAIXA", erp_name="GAMA CAIXA"),
            ModelRow(11, "DELTA INTER", erp_name="DELTA INTER")]
    contas_erp = [ErpAccount("u-8", "ALFA SICOOB", balance=D("1")),
                  ErpAccount("u-9", "BETA INTER", account_number="12345-67", balance=D("2")),
                  ErpAccount("u-10", "GAMA CAIXA", balance=D("3")),
                  ErpAccount("u-11", "DELTA INTER", balance=D("4"))]
    mapa = _Mapa(rows)
    linhas = sd.montar_saldos(contas_erp, mapa)
    mapa_mc = _MapaMc({"ALFA SICOOB": NS(banco="SICOOB", empresa="ALFA"),
                       "BETA INTER": NS(banco="077", empresa="EMPRESA BETA"),
                       "GAMA CAIXA": NS(banco="CAIXA", empresa="GAMA"),
                       "DELTA INTER": NS(banco="INTER", empresa="EMPRESA DELTA")})
    empresas = [NS(nome="EMPRESA BETA", razao_social="EMPRESA BETA FICTICIA LTDA")]
    return linhas, contas_erp, mapa, mapa_mc, empresas


def _sicoob_do_painel(monkeypatch, *contas):
    monkeypatch.setattr(ps.ss, "contas_do_painel", lambda *a: list(contas))


def test_contas_da_prova_so_sicoob_e_inter_com_o_que_cada_uma_precisa(monkeypatch):
    linhas, contas_erp, mapa, mapa_mc, empresas = _cenario()
    _sicoob_do_painel(monkeypatch, ss.ContaDoPainel("ALFA SICOOB", numero="12.345-6"),
                      ss.ContaDoPainel("BETA INTER"), ss.ContaDoPainel("GAMA CAIXA"),
                      ss.ContaDoPainel("DELTA INTER"))
    contas = ps.contas_da_prova(linhas, contas_erp, mapa, mapa_mc, empresas,
                                [ContaInter("BETA", "EMPRESA BETA")])
    assert contas == [
        ps.ContaDaProva(8, "ALFA SICOOB", ps.SICOOB, numero="12.345-6", erp_id="u-8"),
        ps.ContaDaProva(9, "BETA INTER", ps.INTER, numero="1234567", apelido="BETA",
                        nomes=("EMPRESA BETA", "EMPRESA BETA FICTICIA LTDA"), erp_id="u-9"),
        ps.ContaDaProva(11, "DELTA INTER", ps.INTER, nomes=("EMPRESA DELTA",),
                        erp_id="u-11", motivo=ps.INTER_FORA_DA_LISTA)]


def test_sicoob_que_o_cadastro_nao_resolve_entra_com_o_motivo(monkeypatch):
    linhas, contas_erp, mapa, mapa_mc, empresas = _cenario()
    _sicoob_do_painel(monkeypatch, ss.ContaDoPainel("ALFA SICOOB", motivo="sem convênio"))
    [alfa] = [c for c in ps.contas_da_prova(linhas, contas_erp, mapa, mapa_mc, empresas, [])
              if c.banco == ps.SICOOB]
    assert alfa.motivo == ss.PREFIXO + "sem convênio" and alfa.numero == ""


def test_inter_com_dois_logins_da_mesma_empresa_nao_escolhe(monkeypatch):
    linhas, contas_erp, mapa, mapa_mc, empresas = _cenario()
    _sicoob_do_painel(monkeypatch)
    contas = ps.contas_da_prova(linhas, contas_erp, mapa, mapa_mc, empresas,
                                [ContaInter("BETA", "EMPRESA BETA"),
                                 ContaInter("BETA 2", "EMPRESA BETA")])
    beta = next(c for c in contas if c.linha == 9)
    assert beta.motivo == ps.INTER_DOIS_LOGINS and beta.apelido == ""


def test_duas_linhas_no_mesmo_login_do_inter_nao_sao_lidas(monkeypatch):
    linhas, contas_erp, mapa, mapa_mc, empresas = _cenario()
    mapa_mc.destinos["DELTA INTER"] = NS(banco="INTER", empresa="EMPRESA BETA")
    _sicoob_do_painel(monkeypatch)
    contas = ps.contas_da_prova(linhas, contas_erp, mapa, mapa_mc, empresas,
                                [ContaInter("BETA", "EMPRESA BETA")])
    assert [c.motivo for c in contas] == [ps.INTER_REPETIDA.format(apelido="BETA")] * 2


def test_e_inter():
    assert ps.e_inter("077") and ps.e_inter("77") and ps.e_inter("Banco Inter")
    assert not ps.e_inter("SICOOB") and not ps.e_inter("756") and not ps.e_inter("")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tela_do_dia_prova_saldos.py -q`
Expected: FAIL — `ImportError: cannot import name 'prova_saldos' from 'tela_do_dia'`

- [ ] **Step 3: Write minimal implementation**

`tela_do_dia/prova_saldos.py`:

```python
# -*- coding: utf-8 -*-
"""Prova de saldos (ERP × banco): a regra, sem tela, sem rede, sem navegador.

Quem lê é outro (`prova_erp`, `prova_sicoob`, `baixar_comprovantes.
inter_saldo`); quem desenha é `prova_pdf`; quem roda a thread é
`prova_na_tela`. Aqui só se decide: quais contas do painel entram, de que
banco é cada uma, e se o saldo do ERP e o do banco batem em CENTAVOS.

**Conta incerta não bate.** Falha de leitura, conta errada aberta no banco,
valor que não chegou: vira ⚠ com o motivo, nunca ✅ nem ❌. O número nunca
sai de dentro de uma imagem — o print é só prova (spec de 27/10/2026).

Qual conta do Sicoob é cada linha sai de `saldo_sicoob.contas_do_painel` (o
caminho do "Reler Sicoob" e da Remessa). Qual login do Inter é cada linha sai
do cadastro (`contas_mc` diz o banco e a empresa da conta do ERP) cruzado com
`contas_inter.json`: a empresa com UM login é lida; sem login ou com dois, a
linha entra como ⚠ e o banco não é aberto.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import util

from . import saldo_sicoob as ss
from .valores import brl

SICOOB = "SICOOB"
INTER = "INTER"
BATE, NAO_BATE, NAO_LIDA = "bate", "nao_bate", "nao_lida"
MARCA = {BATE: "✅", NAO_BATE: "❌", NAO_LIDA: "⚠"}
PALAVRA = {BATE: "bate", NAO_BATE: "não bate", NAO_LIDA: "não lida"}
CENTAVO = Decimal("0.01")
COLUNAS = ("CONTA", "SALDO ERP", "SALDO BANCO", "DIFERENÇA", "SITUAÇÃO",
           "HORA ERP", "HORA BANCO")
NAO_LIDO = "não lido"
INTERROMPIDA = "prova interrompida antes desta conta"
INTER_FORA_DA_LISTA = ("esta conta do Inter não está na lista do app "
                       "(contas_inter.json) — a prova não abre o banco")
INTER_DOIS_LOGINS = ("a empresa tem mais de uma conta do Inter na lista do "
                     "app — não sei qual login abrir")
INTER_REPETIDA = ("duas linhas do painel caem no mesmo login do Inter "
                  "({apelido}) — confira o cadastro de contas")


def digitos(texto) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def chave_inter(apelido) -> str:
    return util.norm_espaco(apelido or "")


def e_inter(banco) -> bool:
    """"077", "77", "Inter", "BANCO INTER" — a régua de `anexar.origem._banco`."""
    t = util.norm_espaco(banco or "")
    return "INTER" in t or (bool(t) and t.lstrip("0") == "77")


@dataclass(frozen=True)
class ContaDaProva:
    linha: int
    rotulo: str
    banco: str                       # SICOOB | INTER
    #: Sicoob: como o cadastro escreve ("12.345-6"). Inter: os dígitos que o
    #: ERP tem da conta ("" = o ERP não diz; aí só o nome confere).
    numero: str = ""
    apelido: str = ""                # Inter: o login (contas_inter.json)
    nomes: tuple[str, ...] = ()      # Inter: nomes aceitos da empresa na tela
    erp_id: str = ""                 # UUID da conta no ERP (linha da grade)
    motivo: str = ""                 # não dá para provar: ⚠ sem abrir o banco


@dataclass(frozen=True)
class Leitura:
    saldo: Decimal | None
    lido_em: datetime | None = None
    motivo: str = ""
    imagem: Path | None = None
    sem_imagem: str = ""             # por que não há print


@dataclass(frozen=True)
class LinhaDaProva:
    conta: ContaDaProva
    erp: Leitura
    banco: Leitura
    situacao: str
    diferenca: Decimal | None
    motivo: str


def conta_erp_da_linha(contas_erp, mapping) -> dict:
    """{linha do painel: ErpAccount}, pela MESMA régua do saldo do painel
    (`conciliacao.rules.resolve_balances`): ignoradas primeiro, a última
    conta que cai na linha vence."""
    saida = {}
    for conta in contas_erp or []:
        if mapping.is_ignored(conta.name):
            continue
        row = mapping.resolve_account(conta)
        if row is not None and row.exists_in_erp:
            saida[row.row] = conta
    return saida


def contas_da_prova(linhas, contas_erp, mapping, mapa_mc, empresas,
                    contas_inter) -> list[ContaDaProva]:
    """As contas Sicoob e Inter do painel, na ordem das linhas. Conta de
    outro banco não entra (spec: "Contas fora do escopo")."""
    da_linha = conta_erp_da_linha(contas_erp, mapping)
    do_sicoob = {c.rotulo: c for c in ss.contas_do_painel(
        linhas, contas_erp, mapping, mapa_mc, empresas)}
    saida: list[ContaDaProva] = []
    for ln in sorted(linhas, key=lambda x: x.linha):
        erp = da_linha.get(ln.linha)
        erp_id = str(getattr(erp, "id", "") or "")
        sic = do_sicoob.get(ln.rotulo)
        if sic is not None and sic.do_sicoob:
            saida.append(ContaDaProva(
                ln.linha, ln.rotulo, SICOOB, numero=sic.numero, erp_id=erp_id,
                motivo=(ss.PREFIXO + sic.motivo) if sic.motivo else ""))
            continue
        row = mapping.by_row(ln.linha)
        nome = (getattr(erp, "name", "") or (row.erp_name if row else "")
                or ln.rotulo)
        destino = mapa_mc.de(nome) if mapa_mc is not None else None
        if destino is None or not e_inter(destino.banco):
            continue
        numero = digitos(getattr(erp, "account_number", "")
                         or (row.account_number if row else ""))
        empresa = util.norm_espaco(destino.empresa)
        logins = [c for c in contas_inter or []
                  if util.norm_espaco(c.empresa) == empresa]
        apelido, motivo = "", ""
        if not logins:
            motivo = INTER_FORA_DA_LISTA
        elif len(logins) > 1:
            motivo = INTER_DOIS_LOGINS
        else:
            apelido = logins[0].apelido
        razoes = [getattr(e, "razao_social", "") for e in empresas or []
                  if util.norm_espaco(getattr(e, "nome", "")) == empresa]
        candidatos = [destino.empresa, *(c.empresa for c in logins[:1]), *razoes]
        nomes = tuple(dict.fromkeys(n for n in candidatos if (n or "").strip()))
        saida.append(ContaDaProva(ln.linha, ln.rotulo, INTER, numero=numero,
                                  apelido=apelido, nomes=nomes, erp_id=erp_id,
                                  motivo=motivo))
    vezes = Counter(chave_inter(c.apelido) for c in saida
                    if c.banco == INTER and c.apelido and not c.motivo)
    return [replace(c, motivo=INTER_REPETIDA.format(apelido=c.apelido))
            if c.banco == INTER and c.apelido and not c.motivo
            and vezes[chave_inter(c.apelido)] > 1 else c
            for c in saida]


def banco_por_linha(contas, sicoob: dict, inter: dict) -> dict:
    """{linha: Leitura do banco}. Sicoob por `digitos(numero)`, Inter por
    `chave_inter(apelido)`. Conta com motivo não tem leitura."""
    saida = {}
    for c in contas:
        if c.motivo:
            continue
        lida = (sicoob.get(digitos(c.numero)) if c.banco == SICOOB
                else inter.get(chave_inter(c.apelido)))
        if lida is not None:
            saida[c.linha] = lida
    return saida


def _centavos(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def comparar(conta: ContaDaProva, erp: Leitura, banco: Leitura) -> LinhaDaProva:
    if conta.motivo:
        return LinhaDaProva(conta, erp, banco, NAO_LIDA, None, conta.motivo)
    if erp.saldo is None:
        return LinhaDaProva(conta, erp, banco, NAO_LIDA, None,
                            f"ERP: {erp.motivo or NAO_LIDO}")
    if banco.saldo is None:
        return LinhaDaProva(conta, erp, banco, NAO_LIDA, None,
                            f"banco: {banco.motivo or NAO_LIDO}")
    dif = _centavos(banco.saldo) - _centavos(erp.saldo)
    if dif == 0:
        return LinhaDaProva(conta, erp, banco, BATE, dif, "")
    return LinhaDaProva(conta, erp, banco, NAO_BATE, dif, f"diferença de {brl(dif)}")


def montar(contas, erp: dict, banco: dict) -> list[LinhaDaProva]:
    vazia = Leitura(None, motivo=NAO_LIDO)
    return [comparar(c, erp.get(c.linha, vazia), banco.get(c.linha, vazia))
            for c in sorted(contas, key=lambda c: c.linha)]


def contagem(linhas) -> dict:
    n = {BATE: 0, NAO_BATE: 0, NAO_LIDA: 0}
    for linha in linhas:
        n[linha.situacao] += 1
    return n


def texto_da_contagem(linhas) -> str:
    n = contagem(linhas)
    return f"{n[BATE]} batem, {n[NAO_BATE]} não batem, {n[NAO_LIDA]} não lidas"


def hora(leitura: Leitura) -> str:
    return f"{leitura.lido_em:%H:%M}" if leitura.lido_em is not None else "—"


def celulas(linha: LinhaDaProva, com_marca: bool = True) -> tuple:
    palavra = PALAVRA[linha.situacao]
    situacao = f"{MARCA[linha.situacao]} {palavra}" if com_marca else palavra
    return (linha.conta.rotulo, brl(linha.erp.saldo), brl(linha.banco.saldo),
            brl(linha.diferenca), situacao, hora(linha.erp), hora(linha.banco))


def texto_do_registro(linha: LinhaDaProva) -> str:
    texto = (f"  {MARCA[linha.situacao]} {linha.conta.rotulo}: ERP "
             f"{brl(linha.erp.saldo)} · banco {brl(linha.banco.saldo)}")
    return texto + (f" — {linha.motivo}" if linha.motivo else "")


def nome_base(agora: datetime) -> str:
    return f"Prova de saldos {agora:%Y-%m-%d %Hh%M}"


def nome_do_print(linha: int, lado: str) -> str:
    return f"{linha:02d} {lado}.png"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tela_do_dia_prova_saldos.py -q && python -m ruff check --select E9,F tela_do_dia/prova_saldos.py tests/test_tela_do_dia_prova_saldos.py && python -m vermin --target=3.11 --violations tela_do_dia/prova_saldos.py`
Expected: PASS (15 passed), ruff e vermin sem achados.

- [ ] **Step 5: Commit**

```bash
git add tela_do_dia/prova_saldos.py tests/test_tela_do_dia_prova_saldos.py
git commit -m "Prova de saldos: regra pura (contas, centavos, situação)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- tela_do_dia/prova_saldos.py tests/test_tela_do_dia_prova_saldos.py
```

---

### Task 2: PDF com Pillow (`prova_pdf`)

**Files:**
- Create: `tela_do_dia/prova_pdf.py`
- Test: `tests/test_tela_do_dia_prova_pdf.py`

**Interfaces:**
- Consumes: Tarefa 1 — `ps.LinhaDaProva`, `ps.Leitura`, `ps.ContaDaProva`, `ps.celulas(linha, com_marca=False)`, `ps.texto_da_contagem(linhas)`, `ps.hora(leitura)`, `ps.PALAVRA`, `ps.COLUNAS`, `ps.SICOOB`, `ps.NAO_LIDO`, `ps.comparar`; `tela_do_dia.valores.brl`.
- Produces:
  - `gerar(linhas: list[ps.LinhaDaProva], quando: datetime, destino: Path) -> Path` (grava atômico: `.tmp` + `os.replace`)
  - `titulo(quando: datetime) -> str`
  - `paginas_do_resumo(linhas) -> list[list[ps.LinhaDaProva]]`
  - `legenda(lado: str, leitura: ps.Leitura) -> str`
  - `textos_da_conta(linha: ps.LinhaDaProva) -> list[str]`
  - `fonte(tamanho: int, negrito: bool = False)` (TrueType do Windows, com recuo para `ImageFont.load_default(size=)`)
  - constantes `LINHAS_POR_PAGINA = 18`, `DPI = 150`, `LARGURA, ALTURA = 1754, 1240`, `_PASTA_FONTES: Path`

- [ ] **Step 1: Write the failing test**

`tests/test_tela_do_dia_prova_pdf.py`:

```python
# -*- coding: utf-8 -*-
"""O PDF da prova, com imagens fictícias. Pillow desenha a página como
imagem, então o texto é conferido nas funções que o montam e o PDF pelo
número e tamanho das páginas."""
import datetime as dt
from decimal import Decimal as D

import pytest
from PIL import Image

from tela_do_dia import prova_pdf as pdf
from tela_do_dia import prova_saldos as ps

pdfplumber = pytest.importorskip("pdfplumber")

AGORA = dt.datetime(2026, 10, 27, 14, 5)


def _png(caminho, tamanho=(800, 120)):
    Image.new("RGB", tamanho, (200, 200, 200)).save(caminho)
    return caminho


def _linhas(tmp_path, n=2):
    alfa = ps.ContaDaProva(8, "CONTA ALFA", ps.SICOOB, numero="12.345-6")
    beta = ps.ContaDaProva(9, "CONTA BETA", ps.INTER, apelido="BETA")
    l1 = ps.comparar(alfa, ps.Leitura(D("10.00"), AGORA, imagem=_png(tmp_path / "e.png")),
                     ps.Leitura(D("10.00"), AGORA, imagem=_png(tmp_path / "b.png", (1200, 700))))
    l2 = ps.comparar(beta, ps.Leitura(D("5.00"), AGORA),
                     ps.Leitura(None, motivo="QR não lido a tempo", sem_imagem="sem sessão"))
    extras = [ps.comparar(ps.ContaDaProva(20 + i, f"CONTA {i}", ps.SICOOB, numero=str(i)),
                          ps.Leitura(D("1.00"), AGORA), ps.Leitura(D("1.00"), AGORA))
              for i in range(max(0, n - 2))]
    return [l1, l2, *extras]


def _paginas(caminho):
    with pdfplumber.open(caminho) as doc:
        return [(round(p.width), round(p.height)) for p in doc.pages]


def test_gera_resumo_e_uma_pagina_por_conta(tmp_path):
    destino = tmp_path / "Prova de saldos 2026-10-27 14h05.pdf"
    assert pdf.gerar(_linhas(tmp_path), AGORA, destino) == destino
    assert destino.read_bytes()[:4] == b"%PDF"
    assert not destino.with_name(destino.name + ".tmp").exists()
    assert _paginas(destino) == [(842, 595)] * 3          # A4 deitado


def test_resumo_longo_quebra_em_paginas_sem_perder_linha(tmp_path, monkeypatch):
    linhas = _linhas(tmp_path, n=19)
    blocos = pdf.paginas_do_resumo(linhas)
    assert [len(b) for b in blocos] == [18, 1]
    assert [l for b in blocos for l in b] == linhas
    monkeypatch.setattr(pdf, "LINHAS_POR_PAGINA", 2)
    destino = tmp_path / "longo.pdf"
    pdf.gerar(linhas[:3], AGORA, destino)
    assert len(_paginas(destino)) == 2 + 3


def test_resumo_sem_contas_ainda_tem_uma_pagina():
    assert pdf.paginas_do_resumo([]) == [[]]


def test_textos_da_pagina_da_conta(tmp_path):
    _l1, l2 = _linhas(tmp_path)
    assert pdf.titulo(AGORA) == "Prova de saldos — 27/10/2026 14:05"
    assert pdf.textos_da_conta(l2) == [
        "CONTA BETA — NÃO LIDA",
        "ERP (Mais Controle): R$ 5,00 · lido às 14:05",
        "Banco (Inter): não lido — QR não lido a tempo",
        "banco: QR não lido a tempo"]


def test_sem_fonte_do_windows_usa_a_padrao(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "_PASTA_FONTES", tmp_path / "nao-existe")
    assert pdf.fonte(20) is not None
    destino = tmp_path / "sem-fonte.pdf"
    pdf.gerar(_linhas(tmp_path), AGORA, destino)
    assert len(_paginas(destino)) == 3


def test_print_que_nao_abre_vira_caixa_com_o_porque(tmp_path):
    ruim = tmp_path / "ruim.png"
    ruim.write_bytes("isto não é png".encode("utf-8"))
    conta = ps.ContaDaProva(8, "CONTA ALFA", ps.SICOOB, numero="1")
    linha = ps.comparar(conta, ps.Leitura(D("1.00"), AGORA, imagem=ruim),
                        ps.Leitura(D("1.00"), AGORA))
    destino = tmp_path / "ruim.pdf"
    pdf.gerar([linha], AGORA, destino)
    assert len(_paginas(destino)) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tela_do_dia_prova_pdf.py -q`
Expected: FAIL — `ImportError: cannot import name 'prova_pdf' from 'tela_do_dia'`

- [ ] **Step 3: Write minimal implementation**

`tela_do_dia/prova_pdf.py`:

```python
# -*- coding: utf-8 -*-
"""O PDF da Prova de saldos, desenhado com o Pillow que já vai no exe.

Sem biblioteca de PDF nova (decisão do spec de 27/10/2026): cada página é uma
imagem A4 deitada a 150 dpi e o PDF sai de `Image.save(save_all=True)`. Por
isso o texto do PDF não é selecionável — o que importa conferir é montado por
funções puras (`titulo`, `textos_da_conta`, `ps.celulas`) e testado ali.

As cores são tuplas RGB DAQUI e não da `widgets.PALETA`: isto é papel
impresso, não tema da tela (o dark mode não vale para PDF).

A situação sai em palavra colorida (BATE / NÃO BATE / NÃO LIDA): a Arial e a
Segoe UI não têm os glifos ✅/❌, que ficam no Registro da aba.
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import prova_saldos as ps
from .valores import brl

DPI = 150
LARGURA, ALTURA = 1754, 1240            # A4 deitado a 150 dpi
MARGEM = 60
LINHAS_POR_PAGINA = 18
ALTURA_LINHA = 52
COLUNAS_X = (MARGEM, 560, 790, 1020, 1230, 1440, 1600)
BRANCO = (255, 255, 255)
PRETO = (20, 20, 20)
CINZA = (110, 110, 110)
COR = {ps.BATE: (22, 128, 61), ps.NAO_BATE: (185, 28, 28), ps.NAO_LIDA: (180, 83, 9)}
_PASTA_FONTES = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
_NOMES = {False: ("arial.ttf", "segoeui.ttf"), True: ("arialbd.ttf", "segoeuib.ttf")}


def fonte(tamanho: int, negrito: bool = False):
    for nome in _NOMES[negrito]:
        caminho = _PASTA_FONTES / nome
        if caminho.is_file():
            try:
                return ImageFont.truetype(str(caminho), tamanho)
            except OSError:
                continue
    return ImageFont.load_default(size=tamanho)


def _cortar(texto: str, n: int) -> str:
    return texto if len(texto) <= n else texto[: n - 1] + "…"


def _pagina() -> Image.Image:
    return Image.new("RGB", (LARGURA, ALTURA), BRANCO)


def titulo(quando) -> str:
    return f"Prova de saldos — {quando:%d/%m/%Y %H:%M}"


def paginas_do_resumo(linhas) -> list:
    linhas = list(linhas)
    if not linhas:
        return [[]]
    return [linhas[i:i + LINHAS_POR_PAGINA] for i in range(0, len(linhas), LINHAS_POR_PAGINA)]


def _desenhar_resumo(bloco, quando, pagina: int, total: int, contagem: str) -> Image.Image:
    img = _pagina()
    d = ImageDraw.Draw(img)
    d.text((MARGEM, MARGEM), titulo(quando), font=fonte(40, True), fill=PRETO)
    sufixo = f" · página {pagina} de {total}" if total > 1 else ""
    d.text((MARGEM, MARGEM + 60), contagem + sufixo, font=fonte(24), fill=CINZA)
    y = MARGEM + 120
    cabecalho = fonte(20, True)
    for x, nome in zip(COLUNAS_X, ps.COLUNAS):
        d.text((x, y), nome, font=cabecalho, fill=PRETO)
    y += 36
    d.line((MARGEM, y, LARGURA - MARGEM, y), fill=CINZA, width=2)
    y += 10
    corpo, nota = fonte(20), fonte(16)
    for linha in bloco:
        for i, (x, valor) in enumerate(zip(COLUNAS_X, ps.celulas(linha, com_marca=False))):
            texto = _cortar(valor, 38) if i == 0 else valor
            if i == 4:
                texto = texto.upper()
            d.text((x, y), texto, font=corpo, fill=COR[linha.situacao] if i == 4 else PRETO)
        if linha.motivo:
            d.text((MARGEM + 20, y + 26), _cortar(linha.motivo, 150), font=nota, fill=CINZA)
        y += ALTURA_LINHA
    return img


def legenda(lado: str, leitura) -> str:
    if leitura.saldo is None:
        return f"{lado}: não lido — {leitura.motivo or ps.NAO_LIDO}"
    return f"{lado}: {brl(leitura.saldo)} · lido às {ps.hora(leitura)}"


def textos_da_conta(linha) -> list:
    banco = "Sicoob" if linha.conta.banco == ps.SICOOB else "Inter"
    textos = [f"{linha.conta.rotulo} — {ps.PALAVRA[linha.situacao].upper()}",
              legenda("ERP (Mais Controle)", linha.erp),
              legenda(f"Banco ({banco})", linha.banco)]
    if linha.motivo:
        textos.append(linha.motivo)
    return textos


def _colar(img, d, leitura, caixa) -> None:
    x, y, w, h = caixa
    if leitura.imagem is not None:
        try:
            with Image.open(leitura.imagem) as aberta:
                foto = aberta.convert("RGB")
            escala = min(w / foto.width, h / foto.height, 2.0)
            novo = (max(1, int(foto.width * escala)), max(1, int(foto.height * escala)))
            foto = foto.resize(novo, Image.Resampling.LANCZOS)
            img.paste(foto, (x + (w - novo[0]) // 2, y + (h - novo[1]) // 2))
            return
        except (OSError, ValueError):
            pass                 # arquivo que não abre vira a caixa com o porquê
    d.rectangle((x, y, x + w, y + h), outline=CINZA, width=2)
    porque = leitura.sem_imagem or "sem print"
    d.text((x + 20, y + 20), _cortar(f"Sem print: {porque}", 60), font=fonte(20), fill=CINZA)


def _desenhar_conta(linha) -> Image.Image:
    img = _pagina()
    d = ImageDraw.Draw(img)
    textos = textos_da_conta(linha)
    d.text((MARGEM, MARGEM), _cortar(textos[0], 70), font=fonte(34, True),
           fill=COR[linha.situacao])
    largura = (LARGURA - 3 * MARGEM) // 2
    topo = MARGEM + 70
    altura = ALTURA - topo - 200
    caixas = ((MARGEM, topo, largura, altura), (2 * MARGEM + largura, topo, largura, altura))
    for caixa, leitura in zip(caixas, (linha.erp, linha.banco)):
        _colar(img, d, leitura, caixa)
    base = topo + altura + 30
    d.text((MARGEM, base), _cortar(textos[1], 60), font=fonte(22), fill=PRETO)
    d.text((2 * MARGEM + largura, base), _cortar(textos[2], 60), font=fonte(22), fill=PRETO)
    if len(textos) > 3:
        d.text((MARGEM, base + 50), _cortar(textos[3], 140), font=fonte(18), fill=CINZA)
    return img


def gerar(linhas, quando, destino) -> Path:
    destino = Path(destino)
    linhas = list(linhas)
    blocos = paginas_do_resumo(linhas)
    contagem = ps.texto_da_contagem(linhas)
    paginas = [_desenhar_resumo(b, quando, i, len(blocos), contagem)
               for i, b in enumerate(blocos, 1)]
    paginas += [_desenhar_conta(linha) for linha in linhas]
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".tmp")
    paginas[0].save(tmp, "PDF", resolution=float(DPI), save_all=True,
                    append_images=paginas[1:])
    os.replace(tmp, destino)
    return destino
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tela_do_dia_prova_pdf.py tests/test_visual.py -q -k "prova or cor_fixa or varredura" && python -m ruff check --select E9,F tela_do_dia/prova_pdf.py tests/test_tela_do_dia_prova_pdf.py && python -m vermin --target=3.11 --violations tela_do_dia/prova_pdf.py`
Expected: PASS (6 do PDF + os 2 da varredura de cor), ruff e vermin sem achados.

- [ ] **Step 5: Commit**

```bash
git add tela_do_dia/prova_pdf.py tests/test_tela_do_dia_prova_pdf.py
git commit -m "Prova de saldos: PDF pelo Pillow (resumo paginado + página por conta)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- tela_do_dia/prova_pdf.py tests/test_tela_do_dia_prova_pdf.py
```

---

### Task 3: Inter — saldo, conferência da conta e print (`inter_saldo`)

**Files:**
- Modify: `util.py` (acrescentar `fotografar` depois de `pasta_do_perfil`, ~linha 103)
- Modify: `baixar_comprovantes/inter_baixar.py:1128-1149` (`conta_da_pagina`) + nova `numero_no_texto` logo acima dela
- Create: `baixar_comprovantes/inter_saldo.py`
- Test: `tests/test_util_fotografar.py`, `tests/test_inter_saldo.py`

**Interfaces:**
- Consumes (existem): `inter_baixar.API_INTER`, `URL_LOGIN` (= `https://contadigital.inter.co/home`), `TEMPO_LOGIN`, `InterFalhou`, `pasta_do_perfil(conta) -> Path`, `esperar_login(page, tempo=, log=)`, `escutar_autorizacao(page) -> dict`, `_texto_da_tela(page) -> str`; `util.norm_espaco`.
- Produces:
  - `util.fotografar(alvo, arquivo) -> str` ("" = saiu; senão o porquê; nunca levanta)
  - `inter_baixar.numero_no_texto(texto: str) -> str`
  - `inter_saldo.ROTA_SALDO = "/cc/saldo/v3/"`, `URL_SALDO`, `CAMPO = "disponivel"`, `TEMPO_SALDO = 30`, `SELETOR_AREA_SALDO = ""`, `SEM_NUMERO`, `SEM_COMO_CONFERIR`
  - `class SaldoInterFalhou(RuntimeError)`
  - `@dataclass(frozen=True) LidoInter(saldo: Decimal | None = None, lido_em: datetime | None = None, motivo: str = "", imagem: Path | None = None, sem_imagem: str = "")`
  - `saldo_da_resposta(status: int, dado) -> Decimal`
  - `conferir_conta(texto: str, numero_esperado: str, nomes) -> str` ("" = é a conta)
  - `escutar_saldo(page) -> list`
  - `_resposta_do_saldo(page, ouvidas: list, autorizacao: dict, tempo: float = TEMPO_SALDO) -> tuple[int, object]`
  - `ler_conta(apelido: str, numero_esperado: str, nomes, arquivo: Path, *, log=print, avisar_qr=lambda apelido: None, agora=datetime.now, tempo_login: int = ib.TEMPO_LOGIN) -> LidoInter`

- [ ] **Step 1: Write the failing tests**

`tests/test_util_fotografar.py`:

```python
# -*- coding: utf-8 -*-
"""`util.fotografar`: o print é prova, não leitura — falhar não levanta."""
from pathlib import Path

import util


class _Alvo:
    def __init__(self, erro=None):
        self.erro, self.caminhos = erro, []

    def screenshot(self, path):
        if self.erro:
            raise self.erro
        self.caminhos.append(path)
        Path(path).write_bytes(b"png")


def test_fotografar_grava_e_devolve_vazio(tmp_path):
    arquivo = tmp_path / "sub" / "a.png"
    assert util.fotografar(_Alvo(), arquivo) == ""
    assert arquivo.read_bytes() == b"png"


def test_fotografar_que_falha_diz_por_que_e_nao_levanta(tmp_path):
    motivo = util.fotografar(_Alvo(RuntimeError("Target closed\nmais coisa")), tmp_path / "a.png")
    assert motivo == "o print não saiu (Target closed)"
```

`tests/test_inter_saldo.py`:

```python
# -*- coding: utf-8 -*-
"""O saldo do Inter para a Prova de saldos. Sem Chrome: a parte de tela é
dublê; a lógica (resposta, conta aberta) é pura. Tela e números fictícios,
no formato medido ao vivo em 27/10/2026."""
from decimal import Decimal as D

import pytest

from baixar_comprovantes import inter_baixar as ib
from baixar_comprovantes import inter_saldo as m

TELA = ("Saldo\nR$ 1.234,56\n123456789\n\nEMPRESA FICTICIA LTDA\n"
        "Saldo em conta R$ 1.234,56")


def test_saldo_e_o_disponivel_em_decimal():
    dado = {"disponivel": 1234.56, "chequeEspecialDisponivel": 0.0,
            "disponivelComChequeEspecial": 1234.56}
    assert m.saldo_da_resposta(200, dado) == D("1234.56")
    assert m.saldo_da_resposta(200, {"disponivel": -12.3}) == D("-12.30")
    assert m.saldo_da_resposta(200, {"disponivel": 0}) == D("0.00")


@pytest.mark.parametrize("dado", [{}, {"disponivel": None}, {"disponivel": True},
                                  {"disponivel": "1.234,56"}, [], None])
def test_resposta_sem_disponivel_valido_nao_vira_saldo(dado):
    with pytest.raises(m.SaldoInterFalhou):
        m.saldo_da_resposta(200, dado)


def test_sessao_vencida_e_erro_do_banco():
    with pytest.raises(m.SaldoInterFalhou, match="sessão"):
        m.saldo_da_resposta(401, {"disponivel": 1})
    with pytest.raises(m.SaldoInterFalhou, match="HTTP 500"):
        m.saldo_da_resposta(500, None)


def test_numero_no_texto_da_tela_medida():
    assert ib.numero_no_texto(TELA) == "123456789"
    assert ib.numero_no_texto("R$ 1.234,56\n01/10/2026") == ""
    assert ib.numero_no_texto("") == ""


def test_conta_da_pagina_usa_a_mesma_leitura():
    pagina = type("P", (), {"evaluate": lambda self, js: TELA})()
    assert ib.conta_da_pagina(pagina) == "123456789"


def test_conferir_a_conta_certa():
    assert m.conferir_conta(TELA, "12345678-9", ("Empresa Fictícia",)) == ""
    assert m.conferir_conta(TELA, "0123456789", ("EMPRESA FICTICIA",)) == ""


def test_outra_conta_aberta_nao_le():
    motivo = m.conferir_conta(TELA, "987654321", ("EMPRESA FICTICIA",))
    assert "outra conta aberta" in motivo and "987654321" in motivo


def test_nome_de_outra_empresa_nao_le():
    motivo = m.conferir_conta(TELA, "123456789", ("OUTRA EMPRESA",))
    assert "nome da empresa" in motivo and "outra conta aberta" in motivo


def test_sem_numero_na_tela_nao_le():
    assert m.conferir_conta("Saldo\nR$ 1,00", "123456789", ("X",)) == m.SEM_NUMERO


def test_sem_numero_esperado_confere_pelo_nome():
    assert m.conferir_conta(TELA, "", ("EMPRESA FICTICIA",)) == ""


def test_sem_numero_nem_nome_recusa():
    assert m.conferir_conta(TELA, "", ()) == m.SEM_COMO_CONFERIR


class _Resp:
    def __init__(self, status, dado, url=m.URL_SALDO):
        self.status, self._dado, self.url = status, dado, url

    def json(self):
        return self._dado


class _Pag:
    def __init__(self):
        self.pedidos, self.ouvintes = [], {}

    def evaluate(self, js, args=None):
        self.pedidos.append((js, args))
        return {"status": 200, "dado": {"disponivel": 1.5}}

    def wait_for_timeout(self, ms):
        pass

    def on(self, evento, fn):
        self.ouvintes[evento] = fn


def test_resposta_ouvida_vale():
    pag = _Pag()
    assert m._resposta_do_saldo(pag, [_Resp(200, {"disponivel": 2})], {"valor": ""},
                                tempo=0) == (200, {"disponivel": 2})
    assert pag.pedidos == []


def test_sem_ouvir_pede_de_dentro_da_pagina():
    pag = _Pag()
    assert m._resposta_do_saldo(pag, [], {"valor": "Bearer x"}, tempo=0) == (
        200, {"disponivel": 1.5})
    assert pag.pedidos[0][1] == [m.URL_SALDO, "Bearer x"]


def test_sem_ouvir_e_sem_sessao_falha():
    with pytest.raises(m.SaldoInterFalhou, match="não pediu o saldo"):
        m._resposta_do_saldo(_Pag(), [], {"valor": ""}, tempo=0)


def test_escutar_saldo_so_guarda_a_rota_do_saldo():
    pag = _Pag()
    ouvidas = m.escutar_saldo(pag)
    pag.ouvintes["response"](_Resp(200, {}, url=ib.API_INTER + "/cc/pix/v1/extrato"))
    pag.ouvintes["response"](_Resp(200, {"disponivel": 1}))
    assert [r.url for r in ouvidas] == [m.URL_SALDO]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_util_fotografar.py tests/test_inter_saldo.py -q`
Expected: FAIL — `AttributeError: module 'util' has no attribute 'fotografar'` e `ImportError: cannot import name 'inter_saldo'`.

- [ ] **Step 3: Write minimal implementation**

(a) `util.py`, logo depois da função `pasta_do_perfil` (antes da seção `# --- diagnóstico`):

```python
def fotografar(alvo, arquivo) -> str:
    """Print de `alvo` (página ou pedaço de página do Playwright) em `arquivo`.

    "" = saiu; senão, o porquê numa linha. NUNCA levanta: o print é prova, não
    leitura (Prova de saldos, 27/10/2026) — sem ele a conta continua com o
    saldo lido, e o PDF diz que faltou a imagem."""
    try:
        Path(arquivo).parent.mkdir(parents=True, exist_ok=True)
        alvo.screenshot(path=str(arquivo))
    except Exception as e:                                   # noqa: BLE001
        texto = (str(e).strip().splitlines() or [""])[0].strip()[:160]
        return f"o print não saiu ({texto or type(e).__name__})"
    return ""
```

(b) `baixar_comprovantes/inter_baixar.py`: acima de `def conta_da_pagina`, acrescentar:

```python
def numero_no_texto(texto: str) -> str:
    """O número da conta num texto de tela do Inter: a primeira linha (das 40
    primeiras) que é só de sete a dez dígitos. "" se não houver.

    Sete a dez dígitos soltos numa linha é a forma da conta do Inter. Data e
    valor não passam por aqui — têm barra e vírgula. Pura para a Prova de
    saldos conferir a conta aberta sem abrir navegador no teste."""
    for linha in (texto or "").splitlines()[:40]:
        achado = re.fullmatch(r"\s*(\d{7,10})\s*", linha)
        if achado:
            return achado.group(1)
    return ""
```

e, dentro de `conta_da_pagina`, trocar o trecho final

```python
    # Sete a dez dígitos soltos numa linha: é a forma da conta do Inter
    # (123456789). Data e valor não passam por aqui — têm barra e vírgula.
    for linha in texto.splitlines()[:40]:
        achado = re.fullmatch(r"\s*(\d{7,10})\s*", linha)
        if achado:
            return achado.group(1)
    return ""
```

por

```python
    return numero_no_texto(texto)
```

(c) `baixar_comprovantes/inter_saldo.py`:

```python
# -*- coding: utf-8 -*-
"""O saldo ATUAL de UMA conta do Inter, com print — para a Prova de saldos.

Medido ao vivo em 27/10/2026 (dono leu o QR): a tela inicial
(`inter_baixar.URL_LOGIN`, ".../home") pede `GET {API_INTER}/cc/saldo/v3/` e
recebe JSON com `disponivel` (o "Saldo em conta" da tela),
`chequeEspecialDisponivel` e `disponivelComChequeEspecial`. O texto da tela
traz no alto "Saldo / R$ … / <número da conta> / <NOME DA EMPRESA>".

**O valor é OUVIDO da resposta que a própria tela pede** (`escutar_saldo`);
se ela não pedir em `TEMPO_SALDO`, o pedido é repetido DE DENTRO da página
com o cabeçalho de sessão que a página usou (`inter_baixar.
escutar_autorizacao`). Nunca por fora do navegador. O cabeçalho nunca é
gravado nem escrito no Registro.

**Confere a conta antes de usar o número**: o número e o nome da empresa na
tela têm de ser os da linha do painel (`conferir_conta`). Outra conta aberta
= "não lida" com o motivo — nunca o saldo de uma empresa na linha de outra.

Perfil POR CONTA (`inter_baixar.pasta_do_perfil`), o mesmo do Baixar
comprovantes: os dois não rodam juntos (trava em `comprovantes_app.py`). O
Inter pede o QR a cada abertura (conferido em 31/08/2026): quem chama avisa a
tela ANTES (`avisar_qr`), para ela dizer de QUAL conta é o QR.

Só leitura: nada é clicado além do "gerar um novo QR" do `esperar_login`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

import util

from . import inter_baixar as ib

ROTA_SALDO = "/cc/saldo/v3/"
URL_SALDO = ib.API_INTER + ROTA_SALDO
CAMPO = "disponivel"
CENTAVO = Decimal("0.01")
TEMPO_SALDO = 30
#: Seletor da área do saldo na tela inicial (medir ao vivo, Tarefa 8);
#: "" = fotografa a parte visível da tela.
SELETOR_AREA_SALDO = ""
SEM_NUMERO = ("não achei o número da conta na tela inicial do Inter — não "
              "leio o saldo sem saber de quem é")
SEM_COMO_CONFERIR = ("não tenho número nem nome da empresa para conferir a "
                     "conta aberta no Inter — não leio")

_JS_SALDO = """
async ([url, cabecalho]) => {
    const r = await fetch(url, {headers: {Authorization: cabecalho}});
    let dado = null;
    try { dado = await r.json(); } catch (e) { dado = null; }
    return {status: r.status, dado};
}
"""


class SaldoInterFalhou(RuntimeError):
    """O saldo desta conta do Inter não foi lido; a mensagem diz o porquê."""


@dataclass(frozen=True)
class LidoInter:
    saldo: Decimal | None = None
    lido_em: datetime | None = None
    motivo: str = ""
    imagem: Path | None = None
    sem_imagem: str = ""


def _digitos(texto) -> str:
    return "".join(ch for ch in str(texto or "") if ch.isdigit())


def _primeira_linha(erro) -> str:
    texto = (str(erro or "").strip().splitlines() or [""])[0].strip()
    return texto[:160] or type(erro).__name__


def saldo_da_resposta(status: int, dado) -> Decimal:
    if status in (401, 403):
        raise SaldoInterFalhou(f"a sessão do Inter não vale mais (HTTP {status}) — "
                               "leia o QR de novo")
    if status != 200:
        raise SaldoInterFalhou(f"o Inter respondeu HTTP {status} ao pedir o saldo")
    if not isinstance(dado, dict) or CAMPO not in dado:
        raise SaldoInterFalhou("a resposta do saldo do Inter veio sem 'disponivel' — "
                               "o formato do banco mudou")
    valor = dado[CAMPO]
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str, Decimal)):
        raise SaldoInterFalhou(f"o saldo do Inter veio como {valor!r}, que não é número")
    try:
        d = Decimal(str(valor))
    except InvalidOperation:
        raise SaldoInterFalhou(f"o saldo do Inter veio como {str(valor)[:30]!r}, "
                               "que não é número") from None
    if not d.is_finite():
        raise SaldoInterFalhou("o saldo do Inter veio como um número inválido")
    return d.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def conferir_conta(texto: str, numero_esperado: str, nomes) -> str:
    """"" quando a tela é da conta pedida; senão, o porquê (vira ⚠)."""
    na_tela = ib.numero_no_texto(texto)
    if not na_tela:
        return SEM_NUMERO
    esperado = _digitos(numero_esperado).lstrip("0")
    if esperado and _digitos(na_tela).lstrip("0") != esperado:
        return (f"a tela do Inter está na conta {na_tela}, e a desta linha do "
                f"painel é {numero_esperado} — outra conta aberta, não leio")
    validos = [util.norm_espaco(n) for n in nomes or () if (n or "").strip()]
    if validos:
        tela = util.norm_espaco(texto)
        if not any(n in tela for n in validos):
            return ("o nome da empresa na tela do Inter não é o desta conta ("
                    + ", ".join(n for n in nomes if (n or "").strip())
                    + ") — outra conta aberta, não leio")
    elif not esperado:
        return SEM_COMO_CONFERIR
    return ""


def escutar_saldo(page) -> list:
    """As respostas do saldo que a própria tela recebe (o objeto, e não o
    corpo: o corpo é lido depois, fora do evento)."""
    ouvidas: list = []

    def ouvir(resposta):
        if ROTA_SALDO in resposta.url and "cdpj-api" in resposta.url:
            ouvidas.append(resposta)

    page.on("response", ouvir)
    return ouvidas


def _resposta_do_saldo(page, ouvidas: list, autorizacao: dict,
                       tempo: float = TEMPO_SALDO) -> tuple:
    limite = time.time() + tempo
    while time.time() < limite and not ouvidas:
        page.wait_for_timeout(500)
    if ouvidas:
        resposta = ouvidas[-1]
        try:
            return resposta.status, resposta.json()
        except Exception:                                    # noqa: BLE001
            return resposta.status, None
    if autorizacao.get("valor"):
        r = page.evaluate(_JS_SALDO, [URL_SALDO, autorizacao["valor"]]) or {}
        return int(r.get("status") or 0), r.get("dado")
    raise SaldoInterFalhou(f"a tela inicial do Inter não pediu o saldo em {int(tempo)} s "
                           "e não há sessão para pedir de dentro da página")


def _fotografar(page, arquivo: Path) -> tuple:
    alvo = page
    if SELETOR_AREA_SALDO:
        area = page.locator(SELETOR_AREA_SALDO).first
        if area.count():
            alvo = area
    motivo = util.fotografar(alvo, arquivo)
    return (None, motivo) if motivo else (arquivo, "")


def ler_conta(apelido: str, numero_esperado: str, nomes, arquivo: Path, *,
              log=print, avisar_qr=lambda apelido: None, agora=datetime.now,
              tempo_login: int = ib.TEMPO_LOGIN) -> LidoInter:
    """Abre o Chrome no perfil da conta, espera o QR, confere a conta, lê o
    `disponivel` e fotografa. Nunca levanta: o desfecho vem no `LidoInter`."""
    from playwright.sync_api import sync_playwright

    perfil = ib.pasta_do_perfil(apelido)
    perfil.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(perfil), channel="chrome", headless=False,
            args=["--start-maximized"], no_viewport=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ouvidas = escutar_saldo(page)
        autorizacao = ib.escutar_autorizacao(page)
        try:
            page.goto(ib.URL_LOGIN)
            avisar_qr(apelido)
            ib.esperar_login(page, tempo=tempo_login, log=log)
            ouvidas.clear()
            page.goto(ib.URL_LOGIN)
            status, dado = _resposta_do_saldo(page, ouvidas, autorizacao)
            imagem, sem_imagem = _fotografar(page, Path(arquivo))
            motivo = conferir_conta(ib._texto_da_tela(page), numero_esperado, nomes)
            if motivo:
                return LidoInter(motivo=motivo, imagem=imagem, sem_imagem=sem_imagem)
            return LidoInter(saldo_da_resposta(status, dado), agora(), "",
                             imagem, sem_imagem)
        except (ib.InterFalhou, SaldoInterFalhou) as e:
            return LidoInter(motivo=str(e), sem_imagem="a leitura parou antes do print")
        except Exception as e:                               # noqa: BLE001
            return LidoInter(motivo=f"erro inesperado no Inter: {_primeira_linha(e)}",
                             sem_imagem="a leitura parou antes do print")
        finally:
            autorizacao["valor"] = ""
            try:
                ctx.close()
            except Exception:                                # noqa: BLE001
                log("o Chrome do Inter pode ter ficado aberto — feche-o.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_util_fotografar.py tests/test_inter_saldo.py -q && python -m ruff check --select E9,F util.py baixar_comprovantes/inter_baixar.py baixar_comprovantes/inter_saldo.py tests/test_util_fotografar.py tests/test_inter_saldo.py && python -m vermin --target=3.11 --violations util.py baixar_comprovantes/inter_baixar.py baixar_comprovantes/inter_saldo.py`
Expected: PASS (2 + 20 passed), ruff e vermin sem achados.

- [ ] **Step 5: Commit**

```bash
git add baixar_comprovantes/inter_saldo.py tests/test_util_fotografar.py tests/test_inter_saldo.py
git commit -m "Prova de saldos: saldo do Inter com conferência da conta e print" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- util.py baixar_comprovantes/inter_baixar.py baixar_comprovantes/inter_saldo.py tests/test_util_fotografar.py tests/test_inter_saldo.py
```

---

### Task 4: Sicoob — print da conta aberta (`ao_ler` + `prova_sicoob`)

**Files:**
- Modify: `extratos_sicoob/saldo.py` — `ler_contas` (assinatura e o `else:` do laço) e `ler_em_dois_acessos` (assinatura e as duas chamadas a `ler_contas`)
- Create: `tela_do_dia/prova_sicoob.py`
- Test: `tests/test_sicoob_saldo.py` (acrescentar no fim), `tests/test_tela_do_dia_prova_sicoob.py`

**Interfaces:**
- Consumes: `saldo.ler_em_dois_acessos(abrir, numeros, *, perguntar, agora, parar, log, progresso)`, `saldo.Lido(numero, saldo, lido_em, motivo, acesso)`, `saldo.so_digitos`; Tarefa 1 `ps.Leitura`; Tarefa 3 `util.fotografar(alvo, arquivo) -> str`.
- Produces:
  - `saldo.ler_contas(..., ao_ler=None)` e `saldo.ler_em_dois_acessos(..., ao_ler=None)` — `ao_ler(page, numero)` chamado só depois de uma leitura OK, com a conta ainda aberta; exceção dele vira linha no `log` e não desfaz a leitura
  - `prova_sicoob.SELETOR_AREA_SALDO = ""`
  - `prova_sicoob.nome_do_print(numero: str) -> str` (`"sicoob 123456.png"`)
  - `prova_sicoob.ler_com_prints(abrir, numeros, pasta: Path, *, perguntar, parar, log, progresso=lambda f, t: None, agora=datetime.now) -> dict[str, ps.Leitura]` (chave = `saldo.so_digitos(numero)`)

- [ ] **Step 1: Write the failing tests**

Acrescentar ao fim de `tests/test_sicoob_saldo.py`:

```python
# ------------------------------------------------- Prova de saldos: ao_ler
def test_ao_ler_tira_o_print_so_da_conta_lida(medido):
    pagina = Pagina({"123456": ok("1.00"), "234567": {"status": 500, "corpo": "x"}})
    cli = Cliente(pagina, ["12.345-6", "23.456-7"])
    vistos = []
    lidos = S.ler_contas(cli, ["12.345-6", "23.456-7"], agora=lambda: AGORA,
                         ao_ler=lambda page, numero: vistos.append((page, numero, page.aberta)))
    assert [l.ok for l in lidos] == [True, False]
    assert vistos == [(pagina, "12.345-6", "12.345-6")]      # com a conta ABERTA


def test_print_que_falha_nao_desfaz_a_leitura(medido):
    pagina = Pagina({"123456": ok("1.00")})
    cli = Cliente(pagina, ["12.345-6"])
    registro = []

    def quebra(page, numero):
        raise RuntimeError("tela fechou")
    [a] = S.ler_contas(cli, ["12.345-6"], agora=lambda: AGORA, log=registro.append,
                       ao_ler=quebra)
    assert a.ok and a.saldo == D("1.00")
    assert any("print" in r and "tela fechou" in r for r in registro)


def test_ao_ler_vale_tambem_no_outro_acesso(medido):
    c1 = Cliente(Pagina({"123456": ok("1")}), ["12.345-6"])
    c2 = Cliente(Pagina({"234567": ok("2")}), ["23.456-7"])
    vistos = []
    S.ler_em_dois_acessos(_Abrir(c1, c2), ["12.345-6", "23.456-7"],
                          perguntar=lambda faltam: True, agora=lambda: AGORA,
                          ao_ler=lambda page, numero: vistos.append(numero))
    assert vistos == ["12.345-6", "23.456-7"]
```

`tests/test_tela_do_dia_prova_sicoob.py`:

```python
# -*- coding: utf-8 -*-
"""Sicoob com print na Prova de saldos. O motor do saldo é dublê: aqui se
prova que cada conta lida ganha o SEU print, e que o print que falha não
apaga o saldo. Contas fictícias."""
import datetime as dt
from decimal import Decimal as D

from extratos_sicoob import saldo
from tela_do_dia import prova_sicoob as m

AGORA = dt.datetime(2026, 10, 27, 14, 5)


def _motor(monkeypatch, pagina):
    def falso(abrir, numeros, *, perguntar, agora, parar, log, progresso, ao_ler):
        ao_ler(pagina, "12.345-6")
        return [saldo.Lido("12.345-6", D("5.00"), AGORA),
                saldo.Lido("23.456-7", motivo=saldo.FORA_DESTE_LOGIN)]
    monkeypatch.setattr(saldo, "ler_em_dois_acessos", falso)


def _ler(tmp_path):
    return m.ler_com_prints(lambda: None, ["12.345-6", "23.456-7"], tmp_path,
                            perguntar=lambda faltam: False, parar=lambda: False,
                            log=lambda s: None)


def test_cada_conta_lida_ganha_o_seu_print(monkeypatch, tmp_path):
    pagina = object()
    _motor(monkeypatch, pagina)
    fotos = []
    monkeypatch.setattr(m.util, "fotografar",
                        lambda alvo, arquivo: fotos.append((alvo, arquivo)) or "")
    lidas = _ler(tmp_path)
    assert lidas["123456"].saldo == D("5.00") and lidas["123456"].lido_em == AGORA
    assert lidas["123456"].imagem == tmp_path / "sicoob 123456.png"
    assert fotos == [(pagina, tmp_path / "sicoob 123456.png")]
    nao = lidas["234567"]
    assert nao.saldo is None and nao.motivo == saldo.FORA_DESTE_LOGIN
    assert nao.imagem is None and nao.sem_imagem


def test_print_que_falha_mantem_o_saldo(monkeypatch, tmp_path):
    _motor(monkeypatch, object())
    monkeypatch.setattr(m.util, "fotografar", lambda alvo, arquivo: "o print não saiu (x)")
    lida = _ler(tmp_path)["123456"]
    assert lida.saldo == D("5.00") and lida.imagem is None
    assert lida.sem_imagem == "o print não saiu (x)"


def test_seletor_da_area_do_saldo_fotografa_so_ela(monkeypatch, tmp_path):
    class _Area:
        first = property(lambda self: self)
        def count(self): return 1

    area = _Area()
    pagina = type("P", (), {"locator": lambda self, sel: area})()
    _motor(monkeypatch, pagina)
    monkeypatch.setattr(m, "SELETOR_AREA_SALDO", "#saldo")
    fotos = []
    monkeypatch.setattr(m.util, "fotografar", lambda alvo, arquivo: fotos.append(alvo) or "")
    _ler(tmp_path)
    assert fotos == [area]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sicoob_saldo.py tests/test_tela_do_dia_prova_sicoob.py -q`
Expected: FAIL — `TypeError: ler_contas() got an unexpected keyword argument 'ao_ler'` e `ImportError: cannot import name 'prova_sicoob'`.

- [ ] **Step 3: Write minimal implementation**

(a) `extratos_sicoob/saldo.py`, assinatura de `ler_contas`:

```python
def ler_contas(cli, numeros, *, agora=_dt.datetime.now, parar=lambda: False,
               log=print, progresso=lambda feitas, total: None,
               lista: dict | None = None, ao_ler=None) -> list[Lido]:
```

acrescentar ao docstring dela a frase: `` `ao_ler(page, numero)` (Prova de saldos) roda logo depois de cada leitura OK, com a conta ainda aberta; se falhar, a leitura continua valendo e o porquê vai ao `log`. ``

e trocar o `else:` final do laço

```python
        else:
            formato_ruim_seguido = 0
            lidos.append(Lido(numero, valor, agora()))
            log(f"{numero}: lido")
```

por

```python
        else:
            formato_ruim_seguido = 0
            lidos.append(Lido(numero, valor, agora()))
            log(f"{numero}: lido")
            if ao_ler is not None:
                try:
                    ao_ler(cli.page, numero)
                except Exception as e:                       # noqa: BLE001
                    log(f"{numero}: lido, mas o print não saiu — {_primeira_linha(e)}")
```

assinatura de `ler_em_dois_acessos`:

```python
def ler_em_dois_acessos(abrir, numeros, *, perguntar, agora=_dt.datetime.now,
                        parar=lambda: False, log=print,
                        progresso=lambda feitas, total: None,
                        ao_ler=None) -> list[Lido]:
```

e as duas chamadas a `ler_contas` dentro dela passam `ao_ler=ao_ler`:

```python
        lidos = ler_contas(cli, numeros, agora=agora, parar=parar, log=log,
                           progresso=progresso, lista=primeira, ao_ler=ao_ler)
```

```python
                segunda = ler_contas(cli, faltam, agora=agora, parar=parar, log=log,
                                     progresso=progresso, lista=outra, ao_ler=ao_ler)
```

(b) `tela_do_dia/prova_sicoob.py`:

```python
# -*- coding: utf-8 -*-
"""O saldo do Sicoob com print, para a Prova de saldos.

O MESMO caminho do "Reler Sicoob" (`extratos_sicoob.saldo.
ler_em_dois_acessos`: confere a conta no cabeçalho, pede o saldo de dentro
da página, pergunta pelo outro acesso). O print sai pelo gancho `ao_ler`,
com a conta ainda aberta na tela inicial — a mesma em que o saldo foi lido.
Roda na thread de quem chama (a `prova-saldos`); o `SicoobClient` nasce e
morre dentro de `abrir()`.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

import util

from . import prova_saldos as ps

#: Seletor da área do saldo na Home do SicoobNet (medir ao vivo, Tarefa 8);
#: "" = fotografa a parte visível da tela.
SELETOR_AREA_SALDO = ""
SEM_LEITURA = "a conta não foi lida, então não há print"


def nome_do_print(numero: str) -> str:
    from extratos_sicoob import saldo
    return f"sicoob {saldo.so_digitos(numero)}.png"


def ler_com_prints(abrir, numeros, pasta, *, perguntar, parar, log,
                   progresso=lambda feitas, total: None,
                   agora=_dt.datetime.now) -> dict:
    """{dígitos da conta: ps.Leitura}, uma por conta pedida."""
    from extratos_sicoob import saldo

    pasta = Path(pasta)
    imagens: dict = {}

    def ao_ler(page, numero):
        alvo = page
        if SELETOR_AREA_SALDO:
            area = page.locator(SELETOR_AREA_SALDO).first
            if area.count():
                alvo = area
        arquivo = pasta / nome_do_print(numero)
        motivo = util.fotografar(alvo, arquivo)
        imagens[saldo.so_digitos(numero)] = (None, motivo) if motivo else (arquivo, "")

    lidos = saldo.ler_em_dois_acessos(abrir, numeros, perguntar=perguntar, agora=agora,
                                      parar=parar, log=log, progresso=progresso,
                                      ao_ler=ao_ler)
    saida = {}
    for lido in lidos:
        d = saldo.so_digitos(lido.numero)
        imagem, sem = imagens.get(d, (None, SEM_LEITURA))
        saida[d] = ps.Leitura(lido.saldo, lido.lido_em, lido.motivo, imagem, sem)
    return saida
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sicoob_saldo.py tests/test_tela_do_dia_prova_sicoob.py tests/test_tela_do_dia_sicoob_na_tela.py tests/test_tela_do_dia_agendamentos.py -q && python -m ruff check --select E9,F extratos_sicoob/saldo.py tela_do_dia/prova_sicoob.py tests/test_sicoob_saldo.py tests/test_tela_do_dia_prova_sicoob.py && python -m vermin --target=3.11 --violations extratos_sicoob/saldo.py tela_do_dia/prova_sicoob.py`
Expected: PASS (os antigos continuam verdes: `ao_ler=None` é o comportamento de antes), ruff e vermin sem achados.

- [ ] **Step 5: Commit**

```bash
git add tela_do_dia/prova_sicoob.py tests/test_tela_do_dia_prova_sicoob.py
git commit -m "Prova de saldos: print do Sicoob pelo gancho ao_ler do saldo" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- extratos_sicoob/saldo.py tela_do_dia/prova_sicoob.py tests/test_sicoob_saldo.py tests/test_tela_do_dia_prova_sicoob.py
```

---

### Task 5: ERP — saldo atual por linha + print da linha na grade de contas (`prova_erp`)

**Files:**
- Create: `tela_do_dia/prova_erp.py`
- Test: `tests/test_tela_do_dia_prova_erp.py`

**Onde o ERP mostra conta e saldo (descoberto no código):** a tela `#/accounts` (`conciliacao/erp/browser.py:48-62`, seletores levantados na tela real em 10/08/2026): grade MUI, cada linha `.MuiDataGrid-row` com `data-id` = UUID da conta (o `ErpAccount.id`), célula `[data-field="currentBalance"]`, valores mascarados até o botão `button[aria-label="Exibir valores"]`, 10 linhas por página com paginação do servidor. Não há rota por conta conhecida no código. **Medição ao vivo obrigatória (Tarefa 8, passo 2)** antes de liberar: os seletores são de 10/08 e o rótulo do botão "próxima página" da MUI depende do idioma. **Alternativa segura já embutida:** linha que não aparece, seletor que mudou ou aba que cai viram "sem print" com o motivo no PDF; o SALDO do ERP continua vindo da API (`erp_do_dia.ler_saldos`), então a comparação não depende do print.

**Interfaces:**
- Consumes: `tela_do_dia.erp_do_dia.ler_saldos(cfg, api, *, log) -> list[ErpAccount]`; `tela_do_dia.saldos.montar_saldos(contas, mapping) -> list[LinhaSaldo]` (`.linha`, `.sistema`); `anx.garantir_sessao(log) -> api` e `anx.mc` (na thread da vaga, é o `MCClient` dela); `MCClient._nova_aba_do_robo()` e `MCClient._minhas: set`; `conciliacao.erp.browser.SEL_CONTAS_LINHA`, `SEL_CONTAS_OLHO`; `erp.hosts.ACESSAR`; Tarefa 1 `ps.ContaDaProva`, `ps.Leitura`, `ps.conta_erp_da_linha`, `ps.nome_do_print`; Tarefa 3 `util.fotografar`.
- Produces:
  - `URL_CONTAS`, `SEL_PROXIMA_PAGINA`, `MAX_PAGINAS = 10`, `TEMPO_GRADE_MS = 30000`, `NAO_ACHEI`, `SEM_UUID`, `SEM_SALDO`
  - `fotografar_contas(mc, pedidos: list[tuple[int, str]], pasta: Path, *, log=print, parar=lambda: False) -> dict[int, tuple[Path | None, str]]`
  - `ler(anx, cfg, mapping, contas: list[ps.ContaDaProva], pasta: Path, *, log=print, parar=lambda: False, agora=datetime.now, ler_saldos=None) -> dict[int, ps.Leitura]` — roda na thread da vaga (`anx.submeter(..., dona=tela)`)

- [ ] **Step 1: Write the failing test**

`tests/test_tela_do_dia_prova_erp.py`:

```python
# -*- coding: utf-8 -*-
"""ERP na Prova de saldos: o saldo vem da API (como o Buscar) e o print da
linha da conta na grade #/accounts, numa aba do robô fechada no fim. Página
e Chrome são dublês; UUIDs e valores fictícios."""
import datetime as dt
import re
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("playwright")

from conciliacao.models import ErpAccount, ModelRow  # noqa: E402
from tela_do_dia import prova_erp as pe  # noqa: E402
from tela_do_dia import prova_saldos as ps  # noqa: E402

AGORA = dt.datetime(2026, 10, 27, 14, 5)
UA, UB, UC = "aaaaaaaa-0001", "bbbbbbbb-0002", "cccccccc-0003"


class _Loc:
    def __init__(self, pagina, sel):
        self.p, self.sel = pagina, sel

    @property
    def first(self):
        return self

    def count(self):
        return self.p.conta(self.sel)

    def click(self):
        self.p.cliques.append(self.sel)
        if self.sel == pe.SEL_PROXIMA_PAGINA:
            self.p.atual += 1

    def is_enabled(self):
        return self.p.atual + 1 < len(self.p.paginas)

    def scroll_into_view_if_needed(self):
        pass

    def screenshot(self, path):
        Path(path).write_bytes(b"png")
        self.p.fotos.append(self.sel)


class _Pagina:
    def __init__(self, paginas, quebra=None):
        self.paginas, self.atual, self.quebra = paginas, 0, quebra
        self.cliques, self.fotos, self.fechada, self.url = [], [], False, ""

    def goto(self, url, **k):
        if self.quebra:
            raise RuntimeError(self.quebra)
        self.url = url

    def wait_for_selector(self, sel, **k):
        pass

    def wait_for_timeout(self, ms):
        pass

    def locator(self, sel):
        return _Loc(self, sel)

    def conta(self, sel):
        if sel in (pe.SEL_CONTAS_OLHO, pe.SEL_PROXIMA_PAGINA):
            return 1
        achado = re.search(r'data-id="([^"]+)"', sel)
        return 1 if achado and achado.group(1) in self.paginas[self.atual] else 0

    def close(self):
        self.fechada = True


class _Mc:
    def __init__(self, pagina):
        self.pagina, self._minhas, self.abertas = pagina, set(), 0

    def _nova_aba_do_robo(self):
        self.abertas += 1
        self._minhas.add(self.pagina)
        return self.pagina


def test_fotografa_cada_conta_procurando_nas_paginas(tmp_path):
    pagina = _Pagina([[UA], [UB]])
    mc = _Mc(pagina)
    prints = pe.fotografar_contas(mc, [(8, UA), (9, UB)], tmp_path)
    assert prints == {8: (tmp_path / "08 erp.png", ""), 9: (tmp_path / "09 erp.png", "")}
    assert pagina.url == pe.URL_CONTAS
    assert pagina.cliques == [pe.SEL_CONTAS_OLHO, pe.SEL_PROXIMA_PAGINA]
    assert pagina.fechada and mc._minhas == set()


def test_conta_que_nao_aparece_diz_por_que(tmp_path):
    prints = pe.fotografar_contas(_Mc(_Pagina([[UA]])), [(8, UC)], tmp_path)
    assert prints == {8: (None, pe.NAO_ACHEI)}


def test_uuid_invalido_nem_abre_aba(tmp_path):
    mc = _Mc(_Pagina([[UA]]))
    prints = pe.fotografar_contas(mc, [(8, ""), (9, 'x"]; drop')], tmp_path)
    assert prints == {8: (None, pe.SEM_UUID), 9: (None, pe.SEM_UUID)}
    assert mc.abertas == 0


def test_aba_que_cai_vira_motivo_e_fecha(tmp_path):
    pagina = _Pagina([[UA]], quebra="net::ERR_ABORTED\ndetalhe")
    mc = _Mc(pagina)
    prints = pe.fotografar_contas(mc, [(8, UA)], tmp_path, log=lambda s: None)
    assert prints == {8: (None, "print do ERP falhou: net::ERR_ABORTED")}
    assert pagina.fechada and mc._minhas == set()


def test_parar_deixa_as_que_faltam_sem_print(tmp_path):
    prints = pe.fotografar_contas(_Mc(_Pagina([[UA, UB]])), [(8, UA)], tmp_path,
                                  parar=lambda: True)
    assert prints == {8: (None, ps.INTERROMPIDA)}


class _Mapa:
    def __init__(self, rows):
        self.rows = rows

    @property
    def live_rows(self):
        return [r for r in self.rows if r.exists_in_erp]

    def is_ignored(self, nome):
        return False

    def resolve_account(self, conta):
        return next((r for r in self.rows if r.erp_name == conta.name), None)

    def by_row(self, n):
        return next((r for r in self.rows if r.row == n), None)


def _contas():
    return [ps.ContaDaProva(8, "ALFA", ps.SICOOB, numero="1"),
            ps.ContaDaProva(9, "BETA", ps.INTER, apelido="B")]


def test_ler_junta_o_saldo_da_api_e_o_print(tmp_path):
    mapa = _Mapa([ModelRow(8, "ALFA", erp_name="ALFA"), ModelRow(9, "BETA", erp_name="BETA")])
    contas_erp = [ErpAccount(UA, "ALFA", balance=D("10.00")), ErpAccount(UB, "BETA", balance=None)]
    anx = NS(mc=_Mc(_Pagina([[UA, UB]])), garantir_sessao=lambda log: "api")
    pedidos = []
    lidas = pe.ler(anx, "cfg", mapa, _contas(), tmp_path, log=lambda s: None,
                   agora=lambda: AGORA,
                   ler_saldos=lambda cfg, api, log: pedidos.append((cfg, api)) or contas_erp)
    assert pedidos == [("cfg", "api")]
    assert lidas[8] == ps.Leitura(D("10.00"), AGORA, "", tmp_path / "08 erp.png", "")
    assert lidas[9].saldo is None and lidas[9].motivo == pe.SEM_SALDO
    assert lidas[9].imagem == tmp_path / "09 erp.png"


def test_erp_que_falha_vira_motivo_em_todas_e_nao_abre_aba(tmp_path):
    mc = _Mc(_Pagina([[UA]]))
    anx = NS(mc=mc, garantir_sessao=lambda log: "api")

    def quebra(cfg, api, log):
        raise RuntimeError("o Mais Controle respondeu 500\nmais")
    lidas = pe.ler(anx, "cfg", _Mapa([]), _contas(), tmp_path, log=lambda s: None,
                   ler_saldos=quebra)
    assert {k: (v.saldo, v.motivo) for k, v in lidas.items()} == {
        8: (None, "o Mais Controle respondeu 500"), 9: (None, "o Mais Controle respondeu 500")}
    assert mc.abertas == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tela_do_dia_prova_erp.py -q`
Expected: FAIL — `ImportError: cannot import name 'prova_erp' from 'tela_do_dia'`

- [ ] **Step 3: Write minimal implementation**

`tela_do_dia/prova_erp.py`:

```python
# -*- coding: utf-8 -*-
"""O lado do ERP na Prova de saldos: saldo atual + print da conta.

**Roda na thread da vaga do Anexar** (`anx.submeter(..., dona=tela)`): o
`MCClient` e o Playwright dele só vivem lá. O saldo vem do MESMO caminho do
Buscar (`erp_do_dia.ler_saldos`: porteiro com o central ligado; aba do robô
desligado — nunca login HTTP), casado com as linhas do painel pela régua do
painel (`saldos.montar_saldos`).

**O print** é da linha da conta na grade `#/accounts` (React/MUI; cada linha
tem `data-id` = UUID da conta; seletores de `conciliacao/erp/browser.py`,
levantados em 10/08/2026). Numa aba PRÓPRIA do robô
(`MCClient._nova_aba_do_robo`), fechada e esquecida no fim — nunca a aba da
pessoa, nunca `ctx.close()`. Os únicos cliques: "Exibir valores" (só mostra
o que está mascarado) e "próxima página". Linha que não aparece vira "sem
print" com o motivo; o saldo continua o da API.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

import util
from conciliacao.erp.browser import SEL_CONTAS_LINHA, SEL_CONTAS_OLHO
from erp import hosts

from . import prova_saldos as ps
from . import saldos as sd

URL_CONTAS = hosts.ACESSAR + "/#/accounts"
#: O rótulo do botão depende do idioma da MUI (medir ao vivo, Tarefa 8).
SEL_PROXIMA_PAGINA = ('button[aria-label="Go to next page"], '
                      'button[aria-label="Ir para a próxima página"], '
                      'button[aria-label="Próxima página"]')
MAX_PAGINAS = 10
TEMPO_GRADE_MS = 30000
_UUID = re.compile(r"[0-9A-Fa-f-]{8,64}")
NAO_ACHEI = "a conta não apareceu na tela de contas do ERP (#/accounts)"
SEM_UUID = "o ERP não deu o identificador desta conta — sem print"
SEM_SALDO = "o ERP não trouxe o saldo desta conta"


def _primeira_linha(erro) -> str:
    texto = (str(erro or "").strip().splitlines() or [""])[0].strip()
    return texto[:160] or type(erro).__name__


def fotografar_contas(mc, pedidos, pasta, *, log=print, parar=lambda: False) -> dict:
    """{linha: (arquivo, "") ou (None, porquê)} para cada (linha, uuid)."""
    saida: dict = {}
    faltam: dict = {}
    for linha, uuid in pedidos:
        if _UUID.fullmatch(str(uuid or "")):
            faltam[linha] = uuid
        else:
            saida[linha] = (None, SEM_UUID)
    if not faltam:
        return saida
    pasta = Path(pasta)
    aba = mc._nova_aba_do_robo()
    try:
        aba.goto(URL_CONTAS, wait_until="domcontentloaded")
        aba.wait_for_selector(SEL_CONTAS_LINHA, timeout=TEMPO_GRADE_MS)
        olho = aba.locator(SEL_CONTAS_OLHO).first
        if olho.count():
            olho.click()               # só mostra os valores mascarados
            aba.wait_for_timeout(1500)
        for _ in range(MAX_PAGINAS):
            for linha, uuid in list(faltam.items()):
                if parar():
                    break
                alvo = aba.locator(f'{SEL_CONTAS_LINHA}[data-id="{uuid}"]').first
                if alvo.count():
                    arquivo = pasta / ps.nome_do_print(linha, "erp")
                    alvo.scroll_into_view_if_needed()
                    motivo = util.fotografar(alvo, arquivo)
                    saida[linha] = (None, motivo) if motivo else (arquivo, "")
                    del faltam[linha]
            if not faltam or parar():
                break
            proxima = aba.locator(SEL_PROXIMA_PAGINA).first
            if not proxima.count() or not proxima.is_enabled():
                break
            proxima.click()
            aba.wait_for_timeout(1500)
        for linha in faltam:
            saida[linha] = (None, ps.INTERROMPIDA if parar() else NAO_ACHEI)
    except Exception as e:                                   # noqa: BLE001
        motivo = f"print do ERP falhou: {_primeira_linha(e)}"
        log(f"  ERP: {motivo}")
        for linha in faltam:
            saida.setdefault(linha, (None, motivo))
    finally:
        try:
            aba.close()
        except Exception:                                    # noqa: BLE001
            pass
        mc._minhas.discard(aba)
    return saida


def ler(anx, cfg, mapping, contas, pasta, *, log=print, parar=lambda: False,
        agora=_dt.datetime.now, ler_saldos=None) -> dict:
    """{linha: ps.Leitura do ERP}. Erro do ERP vira motivo em todas as
    linhas (nunca saldo zero) e nenhuma aba é aberta."""
    if ler_saldos is None:
        from . import erp_do_dia
        ler_saldos = erp_do_dia.ler_saldos
    api = anx.garantir_sessao(log)
    try:
        contas_erp = ler_saldos(cfg, api, log=log)
    except Exception as e:                                   # noqa: BLE001
        motivo = _primeira_linha(e)
        log(f"  ERP: não li os saldos — {motivo}")
        return {c.linha: ps.Leitura(None, motivo=motivo) for c in contas}
    hora = agora()
    sistema = {ln.linha: ln.sistema for ln in sd.montar_saldos(contas_erp, mapping)}
    da_linha = ps.conta_erp_da_linha(contas_erp, mapping)
    pedidos = [(c.linha, str(getattr(da_linha.get(c.linha), "id", "") or c.erp_id))
               for c in contas]
    prints = fotografar_contas(anx.mc, pedidos, pasta, log=log, parar=parar)
    saida = {}
    for c in contas:
        valor = sistema.get(c.linha)
        imagem, sem = prints.get(c.linha, (None, NAO_ACHEI))
        saida[c.linha] = ps.Leitura(valor, hora if valor is not None else None,
                                    "" if valor is not None else SEM_SALDO, imagem, sem)
    return saida
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tela_do_dia_prova_erp.py -q && python -m ruff check --select E9,F tela_do_dia/prova_erp.py tests/test_tela_do_dia_prova_erp.py && python -m vermin --target=3.11 --violations tela_do_dia/prova_erp.py`
Expected: PASS (7 passed), ruff e vermin sem achados.

- [ ] **Step 5: Commit**

```bash
git add tela_do_dia/prova_erp.py tests/test_tela_do_dia_prova_erp.py
git commit -m "Prova de saldos: saldo do ERP pela API e print da conta em #/accounts" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- tela_do_dia/prova_erp.py tests/test_tela_do_dia_prova_erp.py
```

---

### Task 6: Botão, thread, trava e PDF no fim (`prova_na_tela` + fiação)

**Files:**
- Create: `tela_do_dia/prova_na_tela.py`
- Modify: `tela_do_dia/frame.py` — import (linha 47-48), cartão 1 (linhas 189-190), `_ligar_botoes` (linha 437), `_limpar` (linha 645), `fechar` (linhas 554-558), `sicoob_ocupado` (linha 564)
- Modify: `comprovantes_app.py:349-358` e `:383`
- Modify: `baixar_comprovantes/comprovantes_frame.py` — atributo `inter_ocupado`, método `_inter_em_uso`, chamada em `_comecar` (linha ~329)
- Modify: `tests/test_tela_do_dia_agendamentos.py:265-272`, `tests/test_abas_em_paralelo.py:212-218`, `tests/test_sicoob_disputado.py` (fim)
- Test: `tests/test_tela_do_dia_prova_na_tela.py`

**Interfaces:**
- Consumes: Tarefa 1 (`ps.contas_da_prova`, `ps.montar`, `ps.banco_por_linha`, `ps.texto_da_contagem`, `ps.texto_do_registro`, `ps.nome_base`, `ps.nome_do_print`, `ps.digitos`, `ps.chave_inter`, `ps.Leitura`, `ps.SICOOB`, `ps.INTER`, `ps.INTERROMPIDA`); Tarefa 2 (`prova_pdf.gerar(linhas, quando, destino) -> Path`); Tarefa 3 (`inter_saldo.ler_conta(apelido, numero_esperado, nomes, arquivo, *, log, avisar_qr) -> LidoInter`); Tarefa 4 (`prova_sicoob.ler_com_prints(abrir, numeros, pasta, *, perguntar, parar, log, progresso) -> dict[str, Leitura]`); Tarefa 5 (`prova_erp.ler(anx, cfg, mapping, contas, pasta, *, log, parar) -> dict[int, Leitura]`); `saldos.montar_saldos`; `saldo_sicoob.pergunta_outro_acesso(faltam, contas)`, `saldo_sicoob.recado_da_falha(e)`; `extratos_sicoob.sicoob_client.SicoobClient(log=)`; `pagamentos_frame._carregar_mapas() -> (mapa_mc, empresas)`; `contas_inter.carregar() -> list[ContaInter]`; da tela: `tela.mapping`, `tela.contas_erp`, `tela.cfg`, `tela.anx.avisar_se_ocupado(dona, *, aba)`, `tela.anx.submeter(rotulo, fn, *a, dona=, **k) -> Future`, `tela._pasta_pagamentos() -> Path`, `tela._log(str)`, `tela._abrir(Path)`; `widgets.Botao(pai, texto, papel=, state=, command=)`, `widgets.px`.
- Produces:
  - `prova_na_tela.TITULO = "Prova de saldos"`, `OCUPADO = "Pagamentos do dia — prova de saldos"`, `ROTULO_ERP = "Pagamentos do dia — prova de saldos (ERP)"`, `ESPERA_ERP = 600`
  - `pergunta_de_abrir(contas) -> str`
  - `class ProvaNaTela(pai, tela)` com `.barra`, `.b_prova`, `.b_parar`, `.lbl`, `.outros_no_sicoob: Callable[[], str | None]`, `ocupado() -> str | None`, `ligar(pode: bool)`, `comecar()`, `parar()`, `fechar()`
  - `TelaDoDiaFrame.prova: ProvaNaTela`; `TelaDoDiaFrame.sicoob_ocupado()` passa a incluir `self.prova.ocupado()`
  - `ComprovantesFrame.inter_ocupado = None` (ligado pelo app a `aba_dia.prova.ocupado`) e `_inter_em_uso() -> bool`

- [ ] **Step 1: Write the failing tests**

`tests/test_tela_do_dia_prova_na_tela.py`:

```python
# -*- coding: utf-8 -*-
"""O botão "📸 Prova de saldos" sem Tk: o controlador nasce por __new__.
Prova as recusas (antes de apagar botão), a thread própria, o ERP pela vaga
do Anexar (dona = a tela), o Parar, o PDF no fim e a trava entre abas.
Bancos, ERP e PDF são dublês; contas fictícias."""
import concurrent.futures
import datetime as dt
import queue
import threading
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("playwright")

from tela_do_dia import prova_erp  # noqa: E402
from tela_do_dia import prova_na_tela as m  # noqa: E402
from tela_do_dia import prova_pdf  # noqa: E402
from tela_do_dia import prova_saldos as ps  # noqa: E402

AGORA = dt.datetime(2026, 10, 27, 14, 5)
RAIZ = Path(__file__).resolve().parents[1]
ALFA = ps.ContaDaProva(8, "CONTA ALFA", ps.SICOOB, numero="12.345-6")
BETA = ps.ContaDaProva(9, "CONTA BETA", ps.INTER, numero="123456789", apelido="BETA",
                       nomes=("EMPRESA FICTICIA",))


class _Widget:
    def __init__(self):
        self.estado = {}

    def configure(self, **kw):
        self.estado.update(kw)

    def after(self, *a, **k):
        pass


class _Anx:
    def __init__(self, ocupado=False, erp=None, erro=None):
        self.ocupado_, self.erp, self.erro = ocupado, erp or {}, erro
        self.submetidos, self.avisos = [], []

    def avisar_se_ocupado(self, dona, *, aba=None):
        self.avisos.append((dona, aba))
        return self.ocupado_

    def submeter(self, rotulo, fn, *a, dona=None, **k):
        self.submetidos.append((rotulo, fn, a, dona, k))
        fut = concurrent.futures.Future()
        if self.erro is not None:
            fut.set_exception(self.erro)
        else:
            fut.set_result(self.erp)
        return fut


def _tela(tmp_path, anx):
    registro, abertos = [], []
    return NS(mapping=object(), contas_erp=[object()], cfg="cfg", anx=anx,
              _log=registro.append, registro=registro, abertos=abertos,
              _pasta_pagamentos=lambda: tmp_path, _abrir=abertos.append)


def _prova(tela):
    p = m.ProvaNaTela.__new__(m.ProvaNaTela)
    p.tela, p.q, p._thread, p._erp, p._contas = tela, queue.Queue(), None, None, []
    p._parar, p._pode = threading.Event(), True
    p.outros_no_sicoob = lambda: None
    p.barra, p.lbl, p.b_prova, p.b_parar = _Widget(), _Widget(), _Widget(), _Widget()
    return p


@pytest.fixture
def cenario(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "_carregar_cadastros", lambda: (None, [], []))
    monkeypatch.setattr(m.sd, "montar_saldos", lambda contas, mapping: [])
    monkeypatch.setattr(m.ps, "contas_da_prova", lambda *a: [ALFA, BETA])
    monkeypatch.setattr(m, "_agora", lambda: AGORA)
    gerados = []

    def gerar(linhas, quando, destino):
        gerados.append(linhas)
        Path(destino).write_bytes(b"%PDF")
        return Path(destino)
    monkeypatch.setattr(prova_pdf, "gerar", gerar)
    return NS(gerados=gerados, tmp=tmp_path)


def _fila(p):
    itens = []
    while not p.q.empty():
        itens.append(p.q.get())
    return itens


def _sim(monkeypatch):
    monkeypatch.setattr(m.messagebox, "askokcancel", lambda *a, **k: True)


def test_sem_buscar_recusa_e_nada_apaga(cenario, janelas_do_messagebox):
    anx = _Anx()
    tela = _tela(cenario.tmp, anx)
    tela.mapping = None
    p = _prova(tela)
    p.comecar()
    assert anx.avisos == [] and anx.submetidos == [] and p._thread is None
    assert p.b_prova.estado == {}
    assert "Busque" in janelas_do_messagebox[0][1][1]


def test_chrome_do_banco_em_uso_recusa_antes_de_tudo(cenario, janelas_do_messagebox):
    anx = _Anx()
    p = _prova(_tela(cenario.tmp, anx))
    p.outros_no_sicoob = lambda: "Baixar comprovantes — baixando do banco"
    p.comecar()
    assert anx.avisos == [] and anx.submetidos == [] and p._thread is None
    assert p.b_prova.estado == {} and p.q.empty()
    assert "Baixar comprovantes" in janelas_do_messagebox[0][1][1]


def test_erp_ocupado_recusa_pelo_aviso_da_vaga_da_tela(cenario):
    anx = _Anx(ocupado=True)
    tela = _tela(cenario.tmp, anx)
    p = _prova(tela)
    p.comecar()
    assert anx.avisos == [("a Prova de saldos", tela)]
    assert anx.submetidos == [] and p._thread is None and p.b_prova.estado == {}


def test_pergunta_com_nao_nao_comeca(cenario):
    anx = _Anx()
    p = _prova(_tela(cenario.tmp, anx))
    p.comecar()                                   # o dublê responde "não"
    assert anx.submetidos == [] and p._thread is None


def test_caminho_feliz_erp_na_vaga_bancos_na_thread_e_pdf(cenario, monkeypatch):
    _sim(monkeypatch)
    lido = ps.Leitura(D("10.00"), AGORA)
    anx = _Anx(erp={8: lido, 9: lido})
    tela = _tela(cenario.tmp, anx)
    p = _prova(tela)
    monkeypatch.setattr(m.ProvaNaTela, "_ler_bancos",
                        lambda self, contas, pasta: {8: lido, 9: ps.Leitura(D("10.01"), AGORA)})
    p.comecar()
    p._thread.join(5)
    assert p._thread.name == "prova-saldos" and p._thread.daemon
    [(rotulo, fn, args, dona, kw)] = anx.submetidos
    assert (rotulo, fn, dona) == (m.ROTULO_ERP, prova_erp.ler, tela)
    assert args[0] is anx and args[3] == [ALFA, BETA]
    assert args[4] == cenario.tmp / "Prova de saldos 2026-10-27 14h05"
    assert p.b_prova.estado["state"] == "disabled" and p.b_parar.estado["state"] == "normal"
    itens = _fila(p)
    pdf = cenario.tmp / "Prova de saldos 2026-10-27 14h05.pdf"
    assert ("pronto", (pdf, "1 batem, 1 não batem, 0 não lidas")) in itens
    assert itens[-1] == ("fim", None)
    [linhas] = cenario.gerados
    assert [l.situacao for l in linhas] == [ps.BATE, ps.NAO_BATE]


def test_erp_que_falha_vira_nao_lida_e_o_pdf_sai(cenario, monkeypatch):
    _sim(monkeypatch)
    anx = _Anx(erro=RuntimeError("sessão caiu"))
    p = _prova(_tela(cenario.tmp, anx))
    monkeypatch.setattr(m.ProvaNaTela, "_ler_bancos", lambda self, contas, pasta: {})
    p.comecar()
    p._thread.join(5)
    [linhas] = cenario.gerados
    assert all(l.situacao == ps.NAO_LIDA for l in linhas)
    assert linhas[0].motivo == "ERP: RuntimeError: sessão caiu"


def test_parar_nao_gera_pdf_e_diz_por_que(cenario, monkeypatch):
    _sim(monkeypatch)
    p = _prova(_tela(cenario.tmp, _Anx()))

    def para(self, contas, pasta):
        self._parar.set()
        return {}
    monkeypatch.setattr(m.ProvaNaTela, "_ler_bancos", para)
    p.comecar()
    p._thread.join(5)
    itens = _fila(p)
    assert cenario.gerados == []
    assert ("falhou", "Prova interrompida — nenhum PDF foi gerado.") in itens
    assert itens[-1] == ("fim", None)


def test_inter_com_conta_errada_vira_nao_lida(cenario, monkeypatch, tmp_path):
    from baixar_comprovantes import inter_saldo
    chamadas = []

    def ler_conta(apelido, numero, nomes, arquivo, *, log, avisar_qr):
        avisar_qr(apelido)
        chamadas.append((apelido, numero, nomes, arquivo))
        return inter_saldo.LidoInter(motivo="a tela do Inter está na conta 987654321 — "
                                            "outra conta aberta, não leio")
    monkeypatch.setattr(inter_saldo, "ler_conta", ler_conta)
    p = _prova(_tela(tmp_path, _Anx()))
    lidas = p._ler_bancos([BETA], tmp_path)
    assert chamadas == [("BETA", "123456789", ("EMPRESA FICTICIA",), tmp_path / "09 banco.png")]
    assert ("qr", "BETA") in _fila(p)
    linha = ps.comparar(BETA, ps.Leitura(D("1.00"), AGORA), lidas[9])
    assert linha.situacao == ps.NAO_LIDA and "outra conta aberta" in linha.motivo


def test_sicoob_que_falha_inteiro_vira_motivo_em_cada_conta(cenario, monkeypatch, tmp_path):
    from tela_do_dia import prova_sicoob

    def quebra(*a, **k):
        raise RuntimeError("ProcessSingleton: profile in use")
    monkeypatch.setattr(prova_sicoob, "ler_com_prints", quebra)
    p = _prova(_tela(tmp_path, _Anx()))
    lidas = p._ler_bancos([ALFA], tmp_path)
    assert lidas[8].saldo is None and "já está aberto" in lidas[8].motivo


def test_drain_pronto_abre_a_pasta_e_fim_religa(cenario):
    tela = _tela(cenario.tmp, _Anx())
    p = _prova(tela)
    pdf = cenario.tmp / "x.pdf"
    p.q.put(("qr", "BETA"))
    p.q.put(("pronto", (pdf, "1 batem, 0 não batem, 0 não lidas")))
    p.q.put(("fim", None))
    p._drain()
    assert tela.abertos == [cenario.tmp]
    assert p.b_prova.estado["state"] == "normal" and p.b_parar.estado["state"] == "disabled"
    assert any("leia o QR da BETA" in r for r in tela.registro)
    assert any(pdf.as_posix() in r for r in tela.registro)


def test_ocupado_e_ligar():
    p = _prova(NS())
    assert p.ocupado() is None
    p.ligar(False)
    assert p.b_prova.estado["state"] == "disabled"
    p._thread = NS(is_alive=lambda: True)
    assert p.ocupado() == m.OCUPADO
    p.ligar(True)
    assert p.b_prova.estado["state"] == "disabled"


def test_frame_conta_a_prova_como_dona_do_chrome_do_sicoob():
    from tela_do_dia import frame as f
    t = f.TelaDoDiaFrame.__new__(f.TelaDoDiaFrame)
    t.sicoob = NS(ocupado=lambda: None)
    t.agendamentos = NS(ocupado=lambda: None)
    t.prova = NS(ocupado=lambda: None)
    assert t.sicoob_ocupado() is None
    t.prova = NS(ocupado=lambda: m.OCUPADO)
    assert t.sicoob_ocupado() == m.OCUPADO


def test_frame_cria_liga_e_fecha_a_prova():
    frame = (RAIZ / "tela_do_dia" / "frame.py").read_text(encoding="utf-8")
    assert "self.prova = ProvaNaTela(c1, tela=self)" in frame
    assert "self.prova.ligar(b.dia)" in frame and "self.prova.ligar(False)" in frame
    assert "self.prova.fechar()" in frame


def test_app_liga_a_prova_em_todas_as_pontas():
    app = (RAIZ / "comprovantes_app.py").read_text(encoding="utf-8")

    def trecho(chave):
        return app.split(chave, 1)[1].split("\n    #", 1)[0]
    propria = trecho("aba_dia.prova.outros_no_sicoob =")
    for quem in ("aba_ext.ocupado()", "baixar_comprovantes_no_sicoob(aba_bxc)",
                 "aba_dia.sicoob.ocupado()", "aba_dia.agendamentos.ocupado()",
                 "_remessa_conferindo()"):
        assert quem in propria, quem
    assert "aba_dia.prova.ocupado()" in trecho("aba_dia.sicoob.outros_no_sicoob =")
    assert "aba_dia.prova.ocupado()" in trecho("aba_dia.agendamentos.outros_no_sicoob =")
    assert "aba_bxc.inter_ocupado = aba_dia.prova.ocupado\n" in app
```

Acrescentar ao fim de `tests/test_sicoob_disputado.py`:

```python
# ---------------------------------------- Prova de saldos × Baixar do Inter
PROVA = "Pagamentos do dia — prova de saldos"


def test_baixar_inter_recusa_durante_a_prova(monkeypatch, tmp_path):
    m, aba, criadas = _comprovantes(monkeypatch, tmp_path, bancos=("Inter",))
    vistos = _avisos(monkeypatch, m)
    aba.sicoob_ocupado = lambda: None
    aba.inter_ocupado = lambda: PROVA
    aba._comecar()
    assert criadas == [] and aba.b_ir.estado == {}
    assert len(vistos) == 1 and PROVA in vistos[0][1] and "Inter" in vistos[0][1]


def test_baixar_so_sicoob_nao_olha_a_trava_do_inter(monkeypatch, tmp_path):
    m, aba, criadas = _comprovantes(monkeypatch, tmp_path)
    aba.sicoob_ocupado = lambda: None
    aba.inter_ocupado = lambda: PROVA
    aba._comecar()
    assert criadas == [aba._trabalhar]
```

Em `tests/test_tela_do_dia_agendamentos.py`, `test_frame_junta_saldo_e_conferencia_numa_resposta_so`, acrescentar a linha `t.prova = NS(ocupado=lambda: None)` logo depois de `t.agendamentos = NS(ocupado=lambda: None)` (o `sicoob_ocupado` passa a perguntar à prova).

Em `tests/test_abas_em_paralelo.py`, `_CHAMADORES`, trocar

```python
               "relatorios/relatorio_frame.py", "tela_do_dia/controle_frame.py",
               "tela_do_dia/frame.py")
```

por

```python
               "relatorios/relatorio_frame.py", "tela_do_dia/controle_frame.py",
               "tela_do_dia/frame.py", "tela_do_dia/prova_na_tela.py")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tela_do_dia_prova_na_tela.py tests/test_sicoob_disputado.py tests/test_abas_em_paralelo.py -q -k "prova or inter or aviso"`
Expected: FAIL — `ImportError: cannot import name 'prova_na_tela'`; `test_baixar_inter_recusa_durante_a_prova` falha (`criadas == [aba._trabalhar]`); `test_todo_aviso_diz_a_aba_que_vai_submeter[tela_do_dia/prova_na_tela.py]` falha com `FileNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

(a) `tela_do_dia/prova_na_tela.py`:

```python
# -*- coding: utf-8 -*-
"""O botão "📸 Prova de saldos" no cartão Saldos (spec de 27/10/2026).

Todo dia alguém do financeiro tirava, à mão, o print do saldo de cada conta
no ERP e no banco para o grupo de conferência. Aqui o app lê os dois lados,
fotografa, compara em centavos (`prova_saldos`) e gera um PDF
(`prova_pdf`) em `Pagamentos do dia/`; a pessoa arrasta para o grupo. O app
NÃO mexe no WhatsApp.

**Duas threads, cada uma com o navegador do seu dono**, em paralelo:
- ERP: `anx.submeter(..., dona=tela)` — a vaga desta aba no Anexar, com o
  `MCClient` dela (`prova_erp.ler`); recusa antes pelo `avisar_se_ocupado`
  com a MESMA aba (guarda em `tests/test_abas_em_paralelo.py`);
- bancos: `Thread` daemon `prova-saldos` — Sicoob (`prova_sicoob`, o
  `SicoobClient` nasce e morre lá) e depois cada Inter (`inter_saldo`, um
  Chrome e um QR por conta). No fim ela espera o ERP, monta as linhas e o
  PDF, e põe "pronto" na fila.

A tela só recebe pela fila (`_drain` + `after`). "Parar" vale entre contas;
parado, não sai PDF. **Trava**: recusa com o Chrome do Sicoob ou o Baixar
comprovantes em uso (`outros_no_sicoob`, ligado no `comprovantes_app.py`) e,
enquanto roda, é dona do Chrome do Sicoob (`TelaDoDiaFrame.sicoob_ocupado`) e
dos perfis do Inter (`ComprovantesFrame.inter_ocupado`).
"""
from __future__ import annotations

import datetime
import queue
import threading
from tkinter import messagebox, ttk

import widgets

from . import prova_saldos as ps
from . import saldo_sicoob as ss
from . import saldos as sd

TITULO = "Prova de saldos"
OCUPADO = "Pagamentos do dia — prova de saldos"
ROTULO_ERP = "Pagamentos do dia — prova de saldos (ERP)"
ESPERA_ERP = 600               # segundos esperando o ERP depois dos bancos


def _agora() -> datetime.datetime:
    """Separado para o teste fixar a hora (vai no nome do PDF)."""
    return datetime.datetime.now()


def _carregar_cadastros():
    """(mapa_mc, empresas, contas_inter) — função à parte para o teste."""
    from baixar_comprovantes import contas_inter
    from pagamentos_dia import pagamentos_frame
    mapa_mc, empresas = pagamentos_frame._carregar_mapas()
    return mapa_mc, empresas, contas_inter.carregar()


def pergunta_de_abrir(contas) -> str:
    sicoob = sum(1 for c in contas if c.banco == ps.SICOOB and not c.motivo)
    inter = [c.apelido for c in contas if c.banco == ps.INTER and not c.motivo]
    partes = [f"Vou tirar a prova de {len(contas)} conta(s): o saldo atual no ERP e "
              "no banco, com um print de cada tela."]
    if sicoob:
        partes.append(f"Sicoob: {sicoob} conta(s) — faça o login quando o Chrome do "
                      "Sicoob abrir.")
    if inter:
        partes.append("Inter: um QR por conta, nesta ordem: " + ", ".join(inter) + ".")
    partes.append("É só leitura: nada é pago, agendado nem alterado no banco ou no "
                  "ERP. No fim sai um PDF na pasta Pagamentos do dia.")
    return "\n\n".join(partes)


class ProvaNaTela:
    def __init__(self, pai, tela):
        self.tela = tela
        self.q = queue.Queue()
        self._thread = None
        self._erp = None
        self._contas = []
        self._parar = threading.Event()
        self._pode = False
        #: Ligado pelo app: quem mais está com o Chrome do Sicoob ou o Baixar
        #: comprovantes (que abre os perfis do Inter).
        self.outros_no_sicoob = lambda: None
        self.barra = ttk.Frame(pai)
        self.lbl = ttk.Label(self.barra, style="Secao.TLabel", text="")
        self.lbl.pack(side="left")
        self.b_parar = widgets.Botao(self.barra, "Parar", papel="neutro",
                                     state="disabled", command=self.parar)
        self.b_parar.pack(side="right")
        self.b_prova = widgets.Botao(self.barra, "📸  Prova de saldos", papel="neutro",
                                     state="disabled", command=self.comecar)
        self.b_prova.pack(side="right", padx=widgets.px((0, 8)))
        self.barra.after(200, self._drain)

    # ------------------------------------------------------------ perguntas
    def ocupado(self) -> str | None:
        t = self._thread
        return OCUPADO if t is not None and t.is_alive() else None

    def ligar(self, pode: bool) -> None:
        self._pode = bool(pode)
        self.b_prova.configure(state="normal" if self._pode and not self.ocupado()
                               else "disabled")

    # ------------------------------------------------------------- ações
    def _banco_em_uso(self) -> bool:
        quem = self.outros_no_sicoob()
        if quem:
            messagebox.showinfo(TITULO, f"O Chrome do banco está em uso ({quem}). Espere "
                                        "terminar: os dois usariam o mesmo perfil.")
            return True
        return False

    def comecar(self):
        if self.ocupado():
            return
        tela = self.tela
        if tela.mapping is None or not tela.contas_erp:
            messagebox.showinfo(TITULO, "Busque os pagamentos e saldos primeiro: é a "
                                        "leitura do ERP que diz quais contas do painel "
                                        "são do Sicoob e do Inter.")
            return
        try:
            mapa_mc, empresas, inter = _carregar_cadastros()
        except Exception as e:                               # noqa: BLE001
            messagebox.showwarning(TITULO, widgets.recado_de_erro(
                e, "Não consegui ler o cadastro de contas."))
            return
        linhas = sd.montar_saldos(tela.contas_erp, tela.mapping)
        contas = ps.contas_da_prova(linhas, tela.contas_erp, tela.mapping,
                                    mapa_mc, empresas, inter)
        if not contas:
            messagebox.showinfo(TITULO, "Nenhuma conta do painel é do Sicoob ou do "
                                        "Inter — não há o que provar.")
            return
        if self._banco_em_uso():
            return
        if tela.anx.avisar_se_ocupado("a Prova de saldos", aba=tela):
            return
        if not messagebox.askokcancel(TITULO, pergunta_de_abrir(contas)):
            return
        # De novo depois da pergunta: com ela aberta, o fim do Buscar pode ter
        # aberto o Chrome do Sicoob no MESMO perfil.
        if self._banco_em_uso():
            return
        agora = _agora()
        base = ps.nome_base(agora)
        pasta_pdf = tela._pasta_pagamentos()
        pasta_prints = pasta_pdf / base
        self._contas = contas            # para a pergunta do outro acesso
        self._parar.clear()
        self.b_prova.configure(state="disabled")
        self.b_parar.configure(state="normal")
        self.lbl.configure(text="Prova de saldos: começando…")
        tela._log("")
        tela._log(f"{TITULO}: {len(contas)} conta(s)")
        from . import prova_erp
        self._erp = tela.anx.submeter(ROTULO_ERP, prova_erp.ler, tela.anx, tela.cfg,
                                      tela.mapping, contas, pasta_prints,
                                      log=tela._log, parar=self._parar.is_set, dona=tela)
        self._thread = threading.Thread(
            target=self._t_prova, name="prova-saldos", daemon=True,
            args=(contas, pasta_prints, pasta_pdf / f"{base}.pdf", agora))
        self._thread.start()

    def parar(self):
        self._parar.set()
        self.b_parar.configure(state="disabled")
        self.lbl.configure(text="Prova de saldos: parando…")

    # ------------------------------------------------------- thread dos bancos
    def _t_prova(self, contas, pasta_prints, destino, agora):
        """Thread `prova-saldos`. Só fala com a tela pela fila; sempre termina com "fim"."""
        try:
            pasta_prints.mkdir(parents=True, exist_ok=True)
            bancos = self._ler_bancos(contas, pasta_prints)
            erp = self._esperar_erp(contas)
            if self._parar.is_set():
                self.q.put(("falhou", "Prova interrompida — nenhum PDF foi gerado."))
                return
            linhas = ps.montar(contas, erp, bancos)
            from . import prova_pdf
            pdf = prova_pdf.gerar(linhas, agora, destino)
            for linha in linhas:
                self.q.put(("log", ps.texto_do_registro(linha)))
            self.q.put(("pronto", (pdf, ps.texto_da_contagem(linhas))))
        except Exception as e:                               # noqa: BLE001
            self.q.put(("falhou", f"Prova de saldos: {type(e).__name__}: {e}"))
        finally:
            self.q.put(("fim", None))

    def _registrar_sicoob(self, msg):
        self.tela._log(f"  Sicoob: {msg}")

    def _ler_bancos(self, contas, pasta) -> dict:
        sicoob, inter = {}, {}
        numeros = [c.numero for c in contas
                   if c.banco == ps.SICOOB and c.numero and not c.motivo]
        if numeros and not self._parar.is_set():
            self.q.put(("estado", f"Sicoob: lendo {len(numeros)} conta(s)…"))
            from extratos_sicoob.sicoob_client import SicoobClient

            from . import prova_sicoob
            try:
                sicoob = prova_sicoob.ler_com_prints(
                    lambda: SicoobClient(log=self._registrar_sicoob), numeros, pasta,
                    perguntar=self._perguntar_outro_acesso, parar=self._parar.is_set,
                    log=self._registrar_sicoob,
                    progresso=lambda f, t: self.q.put(("estado", f"Sicoob: {f} de {t} contas")))
            except Exception as e:                           # noqa: BLE001
                motivo = ss.recado_da_falha(e)
                sicoob = {ps.digitos(n): ps.Leitura(None, motivo=motivo) for n in numeros}
        for c in contas:
            if c.banco != ps.INTER or c.motivo or not c.apelido:
                continue
            if self._parar.is_set():
                inter[ps.chave_inter(c.apelido)] = ps.Leitura(None, motivo=ps.INTERROMPIDA)
                continue
            from baixar_comprovantes import inter_saldo
            self.q.put(("estado", f"Inter: abrindo a conta {c.apelido}…"))
            lido = inter_saldo.ler_conta(
                c.apelido, c.numero, c.nomes, pasta / ps.nome_do_print(c.linha, "banco"),
                log=lambda msg, a=c.apelido: self.tela._log(f"  Inter {a}: {msg}"),
                avisar_qr=lambda apelido: self.q.put(("qr", apelido)))
            inter[ps.chave_inter(c.apelido)] = ps.Leitura(
                lido.saldo, lido.lido_em, lido.motivo, lido.imagem, lido.sem_imagem)
        return ps.banco_por_linha(contas, sicoob, inter)

    def _esperar_erp(self, contas) -> dict:
        fut = self._erp
        if fut is None:
            motivo = "a leitura do ERP não começou"
        else:
            try:
                return fut.result(timeout=ESPERA_ERP)
            except TimeoutError:
                motivo = f"o ERP não respondeu em {ESPERA_ERP // 60} minutos"
            except Exception as e:                           # noqa: BLE001
                primeira = (str(e).strip().splitlines() or [""])[0][:160]
                motivo = f"{type(e).__name__}: {primeira}"
        return {c.linha: ps.Leitura(None, motivo=motivo) for c in contas}

    def _perguntar_outro_acesso(self, faltam) -> bool:
        """Da thread dos bancos: a pergunta vai pela fila e a thread espera.
        Parar (ou fechar o app) responde "não"."""
        caixa = {"ev": threading.Event(), "sim": False}
        self.q.put(("perguntar", (ss.pergunta_outro_acesso(faltam, self._contas), caixa)))
        while not caixa["ev"].wait(0.2):
            if self._parar.is_set():
                return False
        return bool(caixa["sim"]) and not self._parar.is_set()

    # ------------------------------------------------------------- tela
    def _drain(self):
        try:
            while True:
                tipo, valor = self.q.get_nowait()
                if tipo == "perguntar":
                    texto, caixa = valor
                    try:
                        caixa["sim"] = bool(messagebox.askyesno(
                            TITULO, texto, default=messagebox.YES))
                    finally:
                        caixa["ev"].set()
                elif tipo == "estado":
                    self.lbl.configure(text=valor)
                elif tipo == "qr":
                    self.lbl.configure(text=f"Leia o QR da {valor} no Chrome do Inter")
                    self.tela._log(f"  Inter: leia o QR da {valor}")
                elif tipo == "log":
                    self.tela._log(valor)
                elif tipo == "pronto":
                    pdf, contagem = valor
                    self.lbl.configure(text=f"Prova pronta: {contagem}")
                    self.tela._log(f"{TITULO}: {pdf.as_posix()} — {contagem}")
                    self.tela._abrir(pdf.parent)
                elif tipo == "falhou":
                    self.tela._log(f"[!] {valor}")
                    self.lbl.configure(text=valor[:120])
                elif tipo == "fim":
                    self.b_parar.configure(state="disabled")
                    self.b_prova.configure(state="normal" if self._pode else "disabled")
        except queue.Empty:
            pass
        except Exception as e:                               # noqa: BLE001
            self.tela._log(f"[!] falha ao mostrar a prova de saldos: {e!r}")
        finally:
            self.barra.after(200, self._drain)

    def fechar(self):
        self._parar.set()
```

(b) `tela_do_dia/frame.py`:

- import, depois de `from .agendamentos_na_tela import ConferenciaNaTela`:

```python
from .prova_na_tela import ProvaNaTela
```

- no cartão 1, trocar

```python
        self.sicoob = LeitorSicoob(c1, tela=self)
        self.sicoob.barra.pack(fill="x", pady=px((6, 0)))
```

por

```python
        self.sicoob = LeitorSicoob(c1, tela=self)
        self.sicoob.barra.pack(fill="x", pady=px((6, 0)))
        # Prova de saldos (27/10/2026): ERP × banco com print, em PDF.
        self.prova = ProvaNaTela(c1, tela=self)
        self.prova.barra.pack(fill="x", pady=px((6, 0)))
```

- em `_ligar_botoes`, trocar `        self.sicoob.ligar(b.dia)` por

```python
        self.sicoob.ligar(b.dia)
        self.prova.ligar(b.dia)
```

- em `_limpar`, trocar `        self.sicoob.ligar(False)` por

```python
        self.sicoob.ligar(False)
        self.prova.ligar(False)
```

- `fechar`:

```python
    def fechar(self):
        """O `_sair` do app chama `fechar` de toda aba: a leitura do Sicoob
        para entre uma conta e outra (a thread é daemon)."""
        self.sicoob.fechar()
        self.agendamentos.fechar()
        self.prova.fechar()
```

- `sicoob_ocupado`: trocar `        return self.sicoob.ocupado() or self.agendamentos.ocupado()` por

```python
        return (self.sicoob.ocupado() or self.agendamentos.ocupado()
                or self.prova.ocupado())
```

(c) `comprovantes_app.py`, trocar

```python
    aba_dia.sicoob.outros_no_sicoob = lambda: aba_ext.ocupado() or (
        _sicoob_na_tela.baixar_comprovantes_no_sicoob(aba_bxc)) or (
        aba_dia.agendamentos.ocupado()) or _remessa_conferindo()
    # O "Conferir agendamentos" da própria tela do dia (dono, 23/10/2026) abre o
    # MESMO perfil: pergunta a todos, inclusive ao saldo da própria aba.
    aba_dia.agendamentos.outros_no_sicoob = lambda: aba_ext.ocupado() or (
        _sicoob_na_tela.baixar_comprovantes_no_sicoob(aba_bxc)) or (
        aba_dia.sicoob.ocupado()) or _remessa_conferindo()
```

por

```python
    aba_dia.sicoob.outros_no_sicoob = lambda: aba_ext.ocupado() or (
        _sicoob_na_tela.baixar_comprovantes_no_sicoob(aba_bxc)) or (
        aba_dia.agendamentos.ocupado()) or aba_dia.prova.ocupado() or (
        _remessa_conferindo())
    # O "Conferir agendamentos" da própria tela do dia (dono, 23/10/2026) abre o
    # MESMO perfil: pergunta a todos, inclusive ao saldo da própria aba.
    aba_dia.agendamentos.outros_no_sicoob = lambda: aba_ext.ocupado() or (
        _sicoob_na_tela.baixar_comprovantes_no_sicoob(aba_bxc)) or (
        aba_dia.sicoob.ocupado()) or aba_dia.prova.ocupado() or _remessa_conferindo()
    # A Prova de saldos (27/10/2026) abre o Chrome do Sicoob E os perfis do
    # Inter: pergunta a todos, inclusive ao Baixar comprovantes (Inter também).
    aba_dia.prova.outros_no_sicoob = lambda: aba_ext.ocupado() or (
        _sicoob_na_tela.baixar_comprovantes_no_sicoob(aba_bxc)) or (
        aba_dia.sicoob.ocupado()) or aba_dia.agendamentos.ocupado() or (
        _remessa_conferindo())
```

e, depois de `    aba_bxc.sicoob_ocupado = aba_dia.sicoob_ocupado`, acrescentar:

```python
    aba_bxc.inter_ocupado = aba_dia.prova.ocupado
```

(d) `baixar_comprovantes/comprovantes_frame.py`: logo depois do método `_sicoob_em_uso`, acrescentar

```python
    #: Ligado pelo comprovantes_app.py: a Prova de saldos da tela do dia abre os
    #: MESMOS perfis do Inter (um por conta). Sem ele, nada muda.
    inter_ocupado = None

    def _inter_em_uso(self) -> bool:
        """Recusa com recado se há conta do Inter marcada e a Prova de saldos
        está com os perfis do Inter."""
        pergunta = getattr(self, "inter_ocupado", None)
        if pergunta is None or not any(
                c["marcada"] and c["banco"] == "Inter"
                for c in self.linhas.values()):
            return False
        quem = pergunta()
        if not quem:
            return False
        messagebox.showinfo(
            "Baixar comprovantes",
            f"O Chrome do Inter está em uso ({quem}). Espere terminar: os dois "
            "usariam o mesmo perfil da conta.")
        return True
```

e em `_comecar` trocar

```python
        if self._sicoob_em_uso():
            return
```

por

```python
        if self._sicoob_em_uso() or self._inter_em_uso():
            return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tela_do_dia_prova_na_tela.py tests/test_sicoob_disputado.py tests/test_abas_em_paralelo.py tests/test_tela_do_dia_agendamentos.py tests/test_tela_do_dia_sicoob_na_tela.py tests/test_empacotamento.py -q && python -m ruff check --select E9,F tela_do_dia/prova_na_tela.py tela_do_dia/frame.py comprovantes_app.py baixar_comprovantes/comprovantes_frame.py tests/test_tela_do_dia_prova_na_tela.py tests/test_sicoob_disputado.py tests/test_abas_em_paralelo.py tests/test_tela_do_dia_agendamentos.py && python -m vermin --target=3.11 --violations tela_do_dia/prova_na_tela.py tela_do_dia/frame.py comprovantes_app.py baixar_comprovantes/comprovantes_frame.py`
Expected: PASS (inclusive `test_todo_aviso_diz_a_aba_que_vai_submeter[tela_do_dia/prova_na_tela.py]`: `{"tela"} == {"tela"}`), ruff e vermin sem achados. Depois, a suíte inteira: `python -m pytest tests -q` — PASS (a galeria e a suíte de tela só com a máquina livre; perguntar ao dono antes).

- [ ] **Step 5: Commit**

```bash
git add tela_do_dia/prova_na_tela.py tests/test_tela_do_dia_prova_na_tela.py
git commit -m "Prova de saldos: botão no cartão Saldos, thread, trava e PDF no fim" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- tela_do_dia/prova_na_tela.py tela_do_dia/frame.py comprovantes_app.py baixar_comprovantes/comprovantes_frame.py tests/test_tela_do_dia_prova_na_tela.py tests/test_sicoob_disputado.py tests/test_abas_em_paralelo.py tests/test_tela_do_dia_agendamentos.py
```

---

### Task 7: Mapas em `.claude/rules`

**Files:**
- Modify: `.claude/rules/arquitetura-tela-do-dia.md` (tabela "Quem decide o quê", linha 38, e seção nova antes de `## Leitura: duplicação conhecida`)
- Modify: `.claude/rules/arquitetura-extratos-sicoob.md` (fim do arquivo)
- Modify: `.claude/rules/arquitetura-util.md` (fim do arquivo)

**Interfaces:**
- Consumes: os nomes reais das Tarefas 1–6.
- Produces: texto; nenhum código.

- [ ] **Step 1: Write the check that fails**

Run: `grep -c "prova_saldos\|prova_na_tela\|inter_saldo\|ao_ler\|fotografar" .claude/rules/arquitetura-tela-do-dia.md .claude/rules/arquitetura-extratos-sicoob.md .claude/rules/arquitetura-util.md`
Expected: `0` nos três arquivos.

- [ ] **Step 2: (o mesmo comando acima é a verificação que falha)**

- [ ] **Step 3: Write the text**

(a) `arquitetura-tela-do-dia.md`, na tabela "Quem decide o quê", depois da linha de `agendamentos_na_tela.py`:

```markdown
| `prova_saldos.py` | Prova de saldos: quais contas Sicoob/Inter do painel entram (Sicoob por `saldo_sicoob.contas_do_painel`; Inter por `contas_mc` × `contas_inter.json`, só empresa com UM login), ✅/❌/⚠ em centavos, células e nomes de arquivo |
| `prova_pdf.py` | o PDF da prova com o Pillow do exe: resumo paginado (18 linhas) + uma página por conta com os dois prints |
| `prova_erp.py` | saldo atual do ERP (o caminho do Buscar) + print da linha da conta na grade `#/accounts`, numa aba do robô fechada no fim |
| `prova_sicoob.py` | saldo do Sicoob com print pelo gancho `ao_ler` de `extratos_sicoob.saldo` |
| `prova_na_tela.py` | o botão "📸 Prova de saldos": recusas, ERP na vaga do Anexar, bancos na thread `prova-saldos`, Parar, PDF e pasta |
```

e a seção nova, antes de `## Leitura: duplicação conhecida`:

```markdown
## Prova de saldos (27/10/2026)

Botão "📸 Prova de saldos" no cartão Saldos (`prova_na_tela.ProvaNaTela`,
criada logo abaixo da barra do "Reler Sicoob"). Spec:
`docs/superpowers/specs/2026-10-27-prova-de-saldos-design.md`; plano:
`docs/superpowers/plans/2026-10-27-prova-de-saldos.md`.

- **Duas threads em paralelo**: o ERP vai para a vaga desta aba no Anexar
  (`anx.submeter(ROTULO_ERP, prova_erp.ler, ..., dona=tela)`, com
  `avisar_se_ocupado(aba=tela)` antes — o arquivo está em `_CHAMADORES` de
  `tests/test_abas_em_paralelo.py`); Sicoob e Inter vão na `Thread` daemon
  `prova-saldos`, que no fim espera o ERP (até `ESPERA_ERP`), monta as linhas
  e grava `Pagamentos do dia/Prova de saldos AAAA-MM-DD HHhMM.pdf`, com os
  prints em `Pagamentos do dia/Prova de saldos AAAA-MM-DD HHhMM/`. A pasta
  abre no fim.
- **Conta incerta não bate**: falha, outra conta aberta no Inter, valor que
  não chegou → ⚠ com o motivo; Parar → nenhum PDF. O print é só prova: o
  número nunca sai de imagem; print que falha vira "Sem print: <porquê>".
- **Trava**: a prova pergunta `outros_no_sicoob` (Extratos, Baixar
  comprovantes — inclusive só Inter —, Reler Sicoob, Conferir agendamentos
  das duas abas) antes de qualquer botão apagar; enquanto roda, entra no
  `sicoob_ocupado` desta aba (que Extratos, Remessa e Baixar consultam) e no
  `ComprovantesFrame.inter_ocupado` (Baixar com conta Inter marcada recusa).
- **ERP**: saldo pelo `erp_do_dia.ler_saldos` (nunca login HTTP); print da
  linha `.MuiDataGrid-row[data-id=<UUID>]` em `#/accounts`, clicando só
  "Exibir valores" e "próxima página", numa aba do robô
  (`MCClient._nova_aba_do_robo`) fechada e retirada de `_minhas` no fim.
- **PDF**: cores RGB do próprio `prova_pdf` (papel, não tema); situação em
  palavra (BATE/NÃO BATE/NÃO LIDA), porque Arial/Segoe UI não têm ✅/❌.
```

(b) `arquitetura-extratos-sicoob.md`, no fim:

```markdown
- **Prova de saldos (27/10/2026)**: `saldo.ler_contas` e
  `saldo.ler_em_dois_acessos` aceitam `ao_ler(page, numero)`, chamado só
  depois de uma leitura OK, com a conta ainda aberta; exceção dele vai ao
  `log` e não desfaz a leitura. Quem usa é `tela_do_dia/prova_sicoob.py`
  (print da Home). E `baixar_comprovantes/inter_saldo.py` lê o saldo ATUAL de
  uma conta Inter no perfil dela (`inter_baixar.pasta_do_perfil`): espera o
  QR (`esperar_login`), OUVE `GET cdpj-api…/cc/saldo/v3/` (`disponivel`) ou
  repete o pedido de dentro da página, confere número E nome da empresa na
  tela (`conferir_conta`) antes de usar o valor, e fotografa. O número da
  conta na tela sai de `inter_baixar.numero_no_texto`, a MESMA regra de
  `conta_da_pagina`.
```

(c) `arquitetura-util.md`, no fim:

```markdown
- `util.fotografar(alvo, arquivo) -> str` (27/10/2026, Prova de saldos):
  print de uma página ou pedaço de página do Playwright; "" = saiu, senão o
  porquê numa linha. Nunca levanta — o print é prova, não leitura. Não
  importa Playwright (duck typing), então o `util.py` continua sem tkinter e
  sem navegador.
```

- [ ] **Step 4: Run the check to verify it passes**

Run: `grep -c "prova_saldos\|prova_na_tela\|inter_saldo\|ao_ler\|fotografar" .claude/rules/arquitetura-tela-do-dia.md .claude/rules/arquitetura-extratos-sicoob.md .claude/rules/arquitetura-util.md`
Expected: número maior que 0 nos três.

- [ ] **Step 5: Commit**

```bash
git commit -m "Mapas: Prova de saldos na tela do dia, no Sicoob/Inter e no util" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- .claude/rules/arquitetura-tela-do-dia.md .claude/rules/arquitetura-extratos-sicoob.md .claude/rules/arquitetura-util.md
```

---

### Task 8: Prova ao vivo (com o dono)

Só com o dono na máquina e autorização explícita: abrir o app, o ERP e os bancos derruba/disputa sessões (memória "Não abrir o app nem o ERP sem autorização"). Nenhum subagente faz esta tarefa.

**Files:**
- Modify (só se a medição mandar): `tela_do_dia/prova_erp.py` (`SEL_PROXIMA_PAGINA`, ou outro seletor), `tela_do_dia/prova_sicoob.py` (`SELETOR_AREA_SALDO`), `baixar_comprovantes/inter_saldo.py` (`SELETOR_AREA_SALDO`)

- [ ] **Step 1: Rodar a prova inteira numa prévia travada** (`travar_versao.txt`) com o dono: Buscar → "📸 Prova de saldos" → login do Sicoob → um QR por conta Inter. Esperado: PDF em `Pagamentos do dia/`, pasta aberta, Registro com uma linha ✅/❌/⚠ por conta.
- [ ] **Step 2: ERP** — conferir no PDF que cada página tem o print da LINHA certa da grade `#/accounts` com o saldo à mostra. Se alguma vier "a conta não apareceu…": no Chrome do app, `copy(document.querySelector('.MuiDataGrid-footerContainer').outerHTML)` no Console (memória "HTML real pelo console") e ajustar `SEL_PROXIMA_PAGINA`; se as linhas não tiverem mais `data-id`, o print fica "sem print" (saldo continua pela API) e o seletor novo entra num PR à parte.
- [ ] **Step 3: Sicoob** — o print da Home mostra o saldo aberto (não "R$ ****")? Se mascarado ou grande demais, medir o seletor da área do saldo pelo Console e preencher `prova_sicoob.SELETOR_AREA_SALDO`.
- [ ] **Step 4: Inter** — para cada conta: a linha veio ✅/❌ (não ⚠ "não achei o número")? Se ⚠ por número: o texto da tela tem o número com hífen/DV? ajustar a regra em `inter_baixar.numero_no_texto` SÓ com teste novo do formato medido; se ⚠ por nome: comparar o nome da tela com `contas_inter.json`/razão social. Conferir que o valor bate com o "Saldo em conta" da tela.
- [ ] **Step 5: Commit** dos ajustes medidos (se houver), um por arquivo tocado, com teste do formato medido; depois liberar pela esteira (PR → prévia → "Liberar uma versão").

---

## Self-review

**Cobertura do spec:**
- Botão no cartão Saldos da aba Pagamentos do dia → Tarefa 6 (`frame.py`, `ProvaNaTela`).
- ERP: saldo atual (o mesmo do "sistema") + print em aba própria do Chrome do app, fechada → Tarefa 5 (decisão "aba do robô" registrada acima).
- Sicoob: saldo pelo `extratos_sicoob/saldo.py` + print; 2º acesso com a pergunta da tela → Tarefas 4 e 6 (`_perguntar_outro_acesso`).
- Inter: perfil da conta, "Leia o QR da X", `esperar_login`, conferência número+empresa, `disponivel` ouvido ou repetido de dentro da página, print → Tarefa 3 + `("qr", apelido)` na Tarefa 6; só contas de `contas_inter.json` → Tarefa 1 (`INTER_FORA_DA_LISTA`).
- Comparação em centavos ✅/❌/⚠ → Tarefa 1.
- PDF `Pagamentos do dia/Prova de saldos AAAA-MM-DD HHhMM.pdf`, página 1 com título/tabela/contagem/horas, página por conta lado a lado com valores → Tarefa 2 (+ nome na Tarefa 1, pasta na Tarefa 6); abre a pasta → Tarefa 6.
- Segurança: só leitura (Global Constraints + cliques listados), conta incerta não bate (Tarefas 1/3/5/6), trava Sicoob e Baixar Inter (Tarefa 6), ERP pelo Chrome do app (Tarefa 5), thread + fila + Parar (Tarefa 6), dado real fora do repo (Global Constraints, testes fictícios).
- Testes do spec: regra pura (T1), PDF (T2), Inter com dublê (T3), trava (T6), nenhum Chrome real (todas), prova ao vivo (T8).

**Placeholders:** nenhum "TBD"/"tratar erros"; os três seletores vazios (`SELETOR_AREA_SALDO` ×2) são configuração com comportamento definido (fotografa a tela visível) e medição marcada na Tarefa 8.

**Consistência de tipos:** `ps.Leitura(saldo, lido_em, motivo, imagem, sem_imagem)` igual em T1/T2/T4/T5/T6; `LidoInter` (T3) convertido em `ps.Leitura` na T6 campo a campo; chaves: Sicoob por `ps.digitos` = `saldo.so_digitos` (ambos só tiram não-dígitos), Inter por `ps.chave_inter`; `prova_erp.ler(anx, cfg, mapping, contas, pasta, *, log, parar)` = chamada da T6; `prova_sicoob.ler_com_prints(abrir, numeros, pasta, *, perguntar, parar, log, progresso)` = chamada da T6; `inter_saldo.ler_conta(apelido, numero_esperado, nomes, arquivo, *, log, avisar_qr)` = chamada da T6 e dublê do teste; `ps.nome_do_print(linha, lado)` com "erp" (T5) e "banco" (T6). Nomes que atravessam para código existente conferidos por busca: `MCClient._nova_aba_do_robo`/`_minhas` (`anexar/mc_client.py:513`, `:340`), `anx.submeter(rotulo, fn, *a, dona=None, **k)` (`anexar/anexar_comprovantes.py:502`), `avisar_se_ocupado(dona, *, aba=None)` (`:662`), `garantir_sessao(log=None)` (`:834`), `erp_do_dia.ler_saldos(config, api, *, ..., log=print)`, `SEL_CONTAS_LINHA`/`SEL_CONTAS_OLHO` (`conciliacao/erp/browser.py:58-59`), `hosts.ACESSAR` (`erp/hosts.py:23`), `inter_baixar.esperar_login(page, tempo=, log=)`, `escutar_autorizacao(page)`, `_texto_da_tela(page)`, `URL_LOGIN`, `API_INTER`, `TEMPO_LOGIN`, `pasta_do_perfil`, `InterFalhou`; `ss.pergunta_outro_acesso(faltam, contas)` usa `c.numero`/`c.rotulo`, que `ContaDaProva` tem.

**Review Focus:** as cinco linhas têm teste na tarefa dona (T3, T2, T6).
