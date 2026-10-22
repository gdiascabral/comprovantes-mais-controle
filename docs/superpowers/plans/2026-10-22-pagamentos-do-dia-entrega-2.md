# Pagamentos do dia — Entrega 2 (tela única, parte 2): plano de implementação

> **Quem for executar:** use superpowers:subagent-driven-development (ou superpowers:executing-plans) e vá tarefa por tarefa. Cada passo tem uma caixa (`- [ ]`) para marcar.
> Worktree: `C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2`, branch `codigo/pagamentos-do-dia-2`, base `297d655` (v2.0.248, já com a entrega 1). Todas as assinaturas citadas como `arquivo:linha` foram conferidas nessa base.

**Goal:** completar a aba "Pagamentos do dia" com estes cinco itens:
- (a) **Conferência editável no passo 2.** O dono pode incluir um bloqueado com motivo, desmarcar, editar a forma de pagar, o dado de reembolso e a descrição, e lançar um pagamento à mão com link opcional do lançamento do ERP. Tudo isso entra no "a pagar", no mínimo de aporte, na planilha, no HTML, na remessa e no Excel.
- (b) **Passo 6, "Marcar agendados".** Guarda uma foto de cada pagamento.
- (c) **Passo 7, "Lista do diretor".** Nome curto por conta, ordinais, a ordem de ontem como sugestão e "Copiar para o WhatsApp".
- (d) **"Agendados a confirmar" no topo da aba.** O app pré-marca o que consegue provar. Título que sumiu ou mudou de valor nunca se resolve sozinho.
- (e) **Persistência na nuvem.** Tudo isso fica no Supabase, com quem, quando e motivo.

**Architecture:**
- **Seis tabelas novas e uma view.** Ficam numa migration só (`20261022100000_pagamentos_do_dia_na_nuvem.sql`).
  - Todas são append-only: o app só faz INSERT e SELECT.
  - A RLS de todas usa `privado.e_ativo()`.
  - O `quem` é carimbado pelo servidor (`default auth.uid()`).
  - O estado de cada coisa é a última linha de evento, "dobrada" no Python.
  - A view `agendado_em_aberto` usa `security_invoker`. É ela que garante que "nada some até responder".
- **Cliente:** `nuvem/pagamentos_do_dia.py`, no padrão de `nuvem/registro.py`: `rest.ler`/`rest.inserir`, com conferência de linha gravada.
- **Regras em módulos puros novos dentro de `tela_do_dia/`** (pasta já empacotada; nada de pasta nova):
  - `conferencia` (eventos → decisões; validações);
  - `geracao` (o `Resultado` da tela para planilha, HTML e remessa);
  - `lancamento_do_erp` (o link do lançamento);
  - `agendados` (passo 6 e "a confirmar");
  - `lista_diretor` (passo 7);
  - `nuvem_do_dia` (a leitura orquestrada, testável com dublês).
  - A tela continua fina: `frame.py` + `janelas.py`.
- **Como as mudanças da tela chegam aos arquivos sem mudar o sentido para a Remessa:**
  - `confirmacao.remontar` e `relatorio.montar_registros` ganham `ids_liberados=()`. O padrão vazio dá resultado idêntico ao de hoje.
  - O registro da linha editada ganha a chave `descricao_editada`, que só a tela põe. `html_pagamentos.descricao_para_colar` a honra, e `remessa_dia._CHAVES_DA_DESCRICAO` a repassa.
  - `PagamentosDiaFrame.receber_apuracao` ganha `resultado=None`.
  - O resto (status LIBERADO/EDITADO/À MÃO, linhas à mão) é pós-processamento puro em `tela_do_dia/geracao.py`, em cima do `Resultado` que a Remessa já monta.
- **Ajustes de saldo, simulação e `enviados_aportes` continuam no JSON local do dia.** Justificativa:
  - o ajuste é rascunho que "vale só para o dia";
  - não decide o que é pago nem vai a banco ou ERP;
  - muda várias vezes por dia, o que seria UPDATE numa base que aqui é append-only;
  - já guarda `quando` e o original (`saldos.Ajuste`);
  - já falha fechado (`dia_de_trabalho.ler` levanta);
  - o Excel cópia do dia registra o resultado.
  
  Pôr rede no caminho de cada clique de simulação não compraria nenhuma garantia de dinheiro. O que decide o que SAI da conta (liberação, edição, à mão, agendado) é o que vai para a nuvem.

**Tech Stack:** Python 3.11 (`vermin --target=3.11`), tkinter/ttk + `widgets.py`, `decimal.Decimal`, pytest, Supabase/PostgREST (`nuvem/rest.py`), Playwright pelo Chrome do app (`anexar/mc_api.py`).

**Spec:** `C:\AUTOMAÇÕES MAIS CONTROLE\PROPOSTA - 2026-10-21 pagamentos do dia numa tela so.html` (v3; fora do repo), item "A tela única, parte 2", e as decisões do dono em `.superpowers/sdd/contexto-entregas-2-a-5.md`.

**Global Constraints:**
- **Repositório público.** Nenhum nome real, CPF, CNPJ ou conta. Use só os fictícios: "Conta Alfa - Banco", "CONTA EXEMPLO - SICOOB", "Fornecedor Modelo Ltda", "Fulano Ficticio", "OBRA MODELO", "fulano@exemplo.com".
- **Dinheiro em `Decimal`.** Float só na fronteira com o `Resultado` da Remessa (`registro["valor"]`), que é float hoje; ali a conversão é `valores.de_float`.
- **Remessa/Retorno, Saldo de pagamentos e Anexar NÃO mudam de comportamento.** Todo parâmetro novo em código compartilhado é opcional, com padrão igual ao comportamento atual, e tem um teste "golden" provando a igualdade. Nada em `anexar/`, `cnab240/`, `modelos_html.py` ou `conciliacao/` é tocado.
- **ERP só pelo Chrome do app.** `anx.garantir_sessao()` + `mc_api`, sem login HTTP. Nada desta aba escreve no ERP.
- **Sem nuvem, nada desta entrega grava** (falha fechada). A tela volta ao comportamento da entrega 1, com o recado no topo.
- **SQL em dois lugares.**
  - `supabase/migrations/20261022100000_pagamentos_do_dia_na_nuvem.sql`: só estrutura.
  - `C:\AUTOMAÇÕES MAIS CONTROLE\APLICAR NO SUPABASE - 2026-10-22 pagamentos do dia na nuvem.sql`: mesmo conteúdo, sem dado real nesta entrega.
  - Passa pelo revisor de SQL, e o coordenador aplica pelo CLI **antes** do merge.
- **Sem pasta nova e sem import novo de submódulo da stdlib.** Só `re`, `json`, `dataclasses`, `decimal`, `datetime`, `threading`, `queue` e `tkinter.ttk`/`messagebox`. Por isso não se mexe em `.github/workflows/build.yml`, `motor_minimo.txt` nem `tests/test_imports_do_motor.py`. Rode `git add` dos `.py` novos antes de `tests/test_empacotamento.py`.
- **Testes de tela (fixture `raiz`) não rodam sem o dono liberar.** Regra nova vai para módulo puro. As chamadas `anx.submeter(dona=)` e `avisar_se_ocupado(aba=)` ficam SÓ em `tela_do_dia/frame.py` (guarda AST de `tests/test_abas_em_paralelo.py`).
- **Antes do PR:**
  - `python -m ruff check --select E9,F .`
  - `python -m vermin --target=3.11 --no-tips --violations tela_do_dia nuvem/pagamentos_do_dia.py` (vale a lista de violações, não o código de saída)
  - a suíte pura da Tarefa 13.
- **Rodapé de todo commit:** `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

**Review Focus (5 linhas → testes):**
1. **Abas antigas intactas.** Sem os parâmetros novos, `montar_registros`/`remontar` devolvem o MESMO `Resultado`, e `descricao_para_colar`/`etiqueta_do_banco` o MESMO texto. `receber_apuracao` sem `resultado=` remonta como hoje. → `tests/test_ganchos_da_tela_do_dia.py`; os testes antigos de `tests/test_remessa_receber_apuracao.py`, `test_html_pagamentos.py` e `test_remessa_dia.py` passando sem mudança.
2. **Tela e arquivos concordam.** O que soma no "a pagar" (fora o já enviado) é exatamente o que sai em planilha e HTML, inclusive liberados, editados e à mão. À mão não vai para a remessa. → `tests/test_tela_do_dia_pagamentos.py::test_a_tela_e_os_arquivos_concordam`; `tests/test_tela_do_dia_geracao.py`.
3. **Liberar e editar não apagam alarme nem marcam remessa sozinhos.**
   - LIBERADO/EDITADO/À MÃO não começam com "APTO", então nascem desmarcados na conferência da Remessa.
   - ATENÇÃO grave (valor diverge, documento não bate…) continua ATENÇÃO.
   - Edição de forma de pagar exige chave com tipo ou linha digitável que fecha nos DVs.
   - "Desfazer" volta ao ERP.
   
   → `tests/test_tela_do_dia_conferencia.py`; `tests/test_tela_do_dia_geracao.py`.
4. **Agendado nunca se resolve sozinho quando sumiu ou mudou.** Só pré-marca com prova (baixa no ERP, baixa parcial batendo ao centavo, retorno "ok"). Nada sai da lista sem resposta final. → `tests/test_tela_do_dia_agendados.py`; `tests/test_nuvem_do_dia.py`; `tests/test_pagamentos_do_dia_sql.py::test_a_lista_de_abertos_respeita_a_rls`.
5. **Nuvem só acrescenta, só para conta liberada, e o servidor diz quem fez.** Falha da nuvem trava edições e agendados. → `tests/test_pagamentos_do_dia_sql.py`; `tests/test_rls_supabase.py`; `tests/test_nuvem_pagamentos_do_dia.py`; `tests/test_nuvem_do_dia.py::test_nuvem_muda_trava_tudo`.

---

## ⚠️ ARQUIVOS EXISTENTES QUE ESTE PLANO MODIFICA (para as entregas 3, 4 e 5)

| Arquivo existente | O que muda | Tarefa |
|---|---|---|
| `pagamentos_dia/relatorio.py` | `montar_registros(..., ids_liberados=())` (`:1516`). Bloco do `motivo` (`:2002`–`:2020`). Chave `bloqueio_liberado` no registro, só quando liberado (`:2121`–`:2190`). | 3 |
| `pagamentos_dia/confirmacao.py` | `remontar(entradas, ids_nao_confirmados=(), *, ids_liberados=())` (`:121`) | 3 |
| `pagamentos_dia/html_pagamentos.py` | `descricao_para_colar` honra `registro["descricao_editada"]` (`:296`, logo após `:343`) | 3 |
| `pagamentos_dia/remessa_dia.py` | `_CHAVES_DA_DESCRICAO` += `"descricao_editada"` (`:981`) | 3 |
| `pagamentos_dia/pagamentos_frame.py` | `receber_apuracao(self, leitura, desmarcados=(), *, hoje=None, resultado=None)` (`:3788`, troca a linha `:3826`) | 3 |
| `tela_do_dia/pagamentos.py` | `Pagamento.origem/nota`, `PagamentosDaConta.desmarcados`, `por_conta(grupos, mapping, conferencia=None)` (`:39`, `:54`, `:93`) | 6 |
| `tela_do_dia/decisoes.py` | `celulas_da_conta` cita liberados, à mão e desmarcados (`:128`) | 6 |
| `tela_do_dia/frame.py` | leitura da nuvem, passo 2 editável, cartões 5–7 e "Agendados a confirmar" | 11, 12 |
| `tests/test_remessa_receber_apuracao.py`, `tests/test_tela_do_dia_pagamentos.py`, `tests/test_tela_do_dia_decisoes.py` | só testes acrescentados (nenhum existente muda) | 3, 6 |
| `.claude/rules/arquitetura-tela-do-dia.md`, `.claude/rules/nuvem-e-remessas.md`, `.claude/rules/arquitetura-pagamentos-dia.md` | documentação | 13 |

**Não tocados:**
- `anexar/*`, `cnab240/*`, `pagamentos_dia/modelos_html.py`, `conciliacao/*`;
- `comprovantes_app.py`, `.github/workflows/build.yml`, `motor_minimo.txt`;
- `tests/test_imports_do_motor.py`, `tests/test_abas_em_paralelo.py`;
- `tela_do_dia/excel_do_dia.py` (o "a pagar" novo chega pelo `totais_para_o_painel`, que não muda).

---

## Mapa de arquivos

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `supabase/migrations/20261022100000_pagamentos_do_dia_na_nuvem.sql` | criar | 6 tabelas append-only, a view `agendado_em_aberto` e a RLS |
| `C:\AUTOMAÇÕES MAIS CONTROLE\APLICAR NO SUPABASE - 2026-10-22 pagamentos do dia na nuvem.sql` | criar (fora do repo) | cópia para aplicar |
| `nuvem/pagamentos_do_dia.py` | criar | `DiaNaNuvem` (ler e acrescentar), `NaoGravou` |
| `tela_do_dia/conferencia.py` | criar | `Evento`, `Decisao`, `dobrar`, `Conferencia`, `PagamentoAMao`, validações, `aviso_de_casamento`, `nova_a_mao` |
| `tela_do_dia/geracao.py` | criar | `resultado_da_tela`, `aplicar_decisao`, `registro_a_mao`, `para_a_remessa`, `chaves_que_saem`, `registro_atual` |
| `tela_do_dia/lancamento_do_erp.py` | criar | `id_do_link`, `LancamentoLido`, `do_item`, `ler` |
| `tela_do_dia/agendados.py` | criar | `Agendado`, `Resposta`, `pendentes`, `situacao`, `intervalo_de_releitura`, `ParaMarcar`, `para_marcar`, `linhas_para_nuvem`, `validar_resposta` |
| `tela_do_dia/lista_diretor.py` | criar | `LinhaDaLista`, `montar`, `sugerir_ordem`, `mover`, `alternar_ordinal`, `texto_whatsapp`, `para_nuvem`, `validar_nome_curto` |
| `tela_do_dia/nuvem_do_dia.py` | criar | `LidoDaNuvem`, `ler` (nuvem + releitura do ERP + retorno) |
| `tela_do_dia/janelas.py` | criar | diálogos finos (`pedir_motivo`, `pedir_edicao`, `pedir_a_mao`, `pedir_resposta`, `pedir_nome_curto`) |
| `tests/test_pagamentos_do_dia_sql.py`, `tests/test_nuvem_pagamentos_do_dia.py`, `tests/test_ganchos_da_tela_do_dia.py`, `tests/test_tela_do_dia_conferencia.py`, `tests/test_tela_do_dia_geracao.py`, `tests/test_tela_do_dia_lancamento_erp.py`, `tests/test_tela_do_dia_agendados.py`, `tests/test_tela_do_dia_lista_diretor.py`, `tests/test_nuvem_do_dia.py` | criar | testes puros |
| (existentes) | modificar | ver a tabela em destaque acima |

**Funções reaproveitadas (conferidas em `297d655`):**
- `pagamentos_dia/confirmacao.py`:
  - `:50` `Entradas`
  - `:121` `remontar(entradas, ids_nao_confirmados=())`
  - `:676` `NAO_APTO`
  - `:680` `Linha` (`secao`, `id`, `conta`, `valor: float`, `favorecido`, `situacao`, `candidato`, `envio_rejeitado`; `marcavel` em `:726`)
  - `:733` `Grupo(conta, entram, nao_aptos, sem_remessa)`
  - `:765` `grupos_da_confirmacao(resultado, analise, lancamentos, destacar=(), fornecedores=None)`
  - `:872` `marcada_de_inicio(linha)`
- `pagamentos_dia/relatorio.py`:
  - `:81` `para_data`
  - `:116` `data_do_item`
  - `:155` `nome_da_conta`
  - `:911` `achar_oc(item, files, comentario="", overview=None)`
  - `:926` `achar_doc(item, files, overview=None)`
  - `:992` `centro_de_custo(item)`
  - `:1505` `Resultado(contas, omitidos)`
  - `:1516` `montar_registros(...)`
  - `:2266` `gerar_excel(resultado, caminho, log=print)`
- `pagamentos_dia/html_pagamentos.py`:
  - `:127` `centavos`
  - `:205` `_e_inter`
  - `:213` `limite_da_descricao`
  - `:218` `_sem_hifen`
  - `:236` `_palavras`
  - `:265` `_que_cabem`
  - `:296` `descricao_para_colar(registro, conta, limite=None)`
  - `:500` `_motivo_do_bloqueio` (bloqueia só status `ATENÇÃO`/`JÁ PAGO`, `parcial`, `valor_diverge`, "PAGAR A MAO" na obs)
  - `:521` `contas_do_html_geral(resultado)`
  - `:812` `gravar(resultado, lancamentos, anexos, pasta, ini, fim, hoje=None, pastas_extras=())`
- `pagamentos_dia/remessa_dia.py`:
  - `:81` `MOTIVO_SEM_DOCUMENTO` ("o favorecido não está no cadastro de Contatos do ERP, …")
  - `:604` `Candidato.apto` (= `status.startswith("APTO")`)
  - `:832` `preparar(contas, participantes=None, quando=None, historico=None)`
  - `:981` `_CHAVES_DA_DESCRICAO`
  - `:990` `etiqueta_do_banco(c)`
- `pagamentos_dia/regras_pagamento.py`:
  - `:182` `MOTIVO_NAO_CONFIRMADO`
  - `:187` `MOTIVO_SEM_ANEXO`
  - `:336` `tipo_de_chave_pix(texto)` ("" para 11 dígitos crus ambíguos)
  - `:519` `documento_valido`
- `pagamentos_dia/ocr_boleto.py:227` `codigo_de_barras(linha)` ("" se os DVs não fecham)
- `pagamentos_dia/pagamentos_frame.py:3788` `receber_apuracao(self, leitura, desmarcados=(), *, hoje=None)`; `:3826` `self.resultado = confirmacao.remontar(leitura.entradas, set(desmarcados))`
- `anexar/matcher.py` (como o Anexar casa depois):
  - `:55` `_norm`
  - `:73` `_com_hifen`
  - `:78` `_sem_zeros`
  - `:92` `_numeros_soltos(desc, cents)` (o ÚLTIMO número da descrição, antes de "OC")
  - `:128` `_numeros_do_documento(doc)`
  - `:205` `_ocnf_rotulados(*textos)`
- `anexar/mc_api.py`:
  - `:299` `capturar_credenciais(log)`
  - `:555` `listar_a_pagar(data_inicio, data_fim, log=print)` (type=ALL, traz `paid`)
  - `:597` `listar_overviews(installment_ids, log=print, ...)`
- `nuvem/rest.py`:
  - `:78` `ErroDaNuvem`
  - `:93` `RecusadoPeloBanco`
  - `:174` `ler(tabela, token, *, colunas="*", filtro="")`
  - `:182` `inserir(tabela, token, linhas, *, devolver=True)`
- `nuvem/registro.py`:
  - `:132` `Envio.retorno_estado`
  - `:161` `Registro(token)`
  - `:615` `envios_em_lote(identificadores, referencias) -> (dict, dict)`, com valores `(Envio, None) | None`
- `nuvem/sessao.py`:
  - `:241` `token()`
  - `:278` `quem() -> Quem` (`primeiro_nome`)
- `tela_do_dia/valores.py`:
  - `:21` `ler_valor_editado`
  - `:35` `de_float`
  - `:40` `brl` (`"R$ 30.500,00"`)
- `tela_do_dia/pagamentos.py`:
  - `:39` `Pagamento`
  - `:54` `PagamentosDaConta`
  - `:93` `por_conta(grupos, mapping)`
  - `:130` `ids_que_nao_saem(grupos)`
  - `:137` `totais_para_o_painel`
- `tela_do_dia/frame.py`:
  - `:71` `__init__`
  - `:97` `_build`
  - `:289` `_drain`
  - `:357` `_limpar`
  - `:375` `_t_ler`
  - `:419` `_receber_leitura`
  - `:476` `_recalcular`
  - `:520` `_encher_pagamentos`
  - `:584` `_janela`
  - `:597` `_rodape`
  - `:805` `_resultado_que_sai`
  - `:910` `_ir_para_remessa`
- `conciliacao/mapping.py`: `:111` `resolve_label`; `:134` `is_ignored`

**Como o Anexar casa depois, e o que isto preserva:**
- O matcher filtra pelo valor pago e casa por OC/NF rotulados, depois pelo centro de custo (≥ 6 caracteres na descrição do comprovante) e depois pelo último número solto da descrição.
- A descrição que vai ao banco sai de `descricao_para_colar`: CC na frente, documento no fim.
- **Linha editada:** a descrição escrita pelo dono vai crua (só limpa e cortada). A tela roda `conferencia.aviso_de_casamento` com as MESMAS funções do matcher e pergunta antes de gravar quando a descrição perdeu o CC ou o número do documento no fim.
- **À mão com link:** monta a descrição pelas peças do lançamento (CC, NF, OC), igual a uma linha do ERP. O lançamento existe, então o Anexar acha o pagamento quando a baixa for feita.
- **À mão sem link:** não tem lançamento para casar. A tela diz isso na hora de gravar.

---

## Tarefa 1 — Migration: o dia de trabalho na nuvem
**Modelo sugerido:** sonnet (o revisor de SQL confere antes de aplicar).

**Files:**
- Create: `supabase/migrations/20261022100000_pagamentos_do_dia_na_nuvem.sql`, `tests/test_pagamentos_do_dia_sql.py`
- Create (fora do repo, mesmo conteúdo): `C:\AUTOMAÇÕES MAIS CONTROLE\APLICAR NO SUPABASE - 2026-10-22 pagamentos do dia na nuvem.sql`

**Interfaces:**
- Tabelas: `pagamento_decisao`, `pagamento_a_mao`, `pagamento_agendado`, `agendado_resposta`, `lista_diretor_nome`, `lista_diretor`.
- View: `agendado_em_aberto`.
- Toda tabela tem `quem uuid not null default auth.uid() references auth.users (id)`, `quem_nome text`, `quando timestamptz default now()`.

- [ ] **Passo 1: teste que falha** — `tests/test_pagamentos_do_dia_sql.py`
```python
# -*- coding: utf-8 -*-
"""A estrutura das tabelas do dia de trabalho na nuvem, lida da migration
(sem Postgres — o mesmo jeito de `test_rls_supabase.py`)."""
import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
_SQL = _RAIZ / "supabase" / "migrations" / "20261022100000_pagamentos_do_dia_na_nuvem.sql"
TABELAS = ("pagamento_decisao", "pagamento_a_mao", "pagamento_agendado",
           "agendado_resposta", "lista_diretor_nome", "lista_diretor")


def _texto() -> str:
    sql = re.sub(r"--[^\n]*", " ", _SQL.read_text(encoding="utf-8"))
    return " ".join(sql.split()).lower()


def test_cria_as_seis_tabelas():
    t = _texto()
    for nome in TABELAS:
        assert f"create table if not exists public.{nome} (" in t


def test_toda_tabela_tem_rls_e_as_duas_politicas_com_a_porteira():
    t = _texto()
    for nome in TABELAS:
        assert f"alter table public.{nome} enable row level security" in t
        assert (f"create policy {nome}_le on public.{nome} for select to authenticated "
                "using ((select privado.e_ativo()))") in t
        assert (f"create policy {nome}_grava on public.{nome} for insert to authenticated "
                "with check ((select privado.e_ativo()) and quem = (select auth.uid()))") in t


def test_o_app_so_le_e_acrescenta():
    t = _texto()
    for nome in TABELAS:
        assert f"revoke all on table public.{nome} from anon, authenticated" in t
        assert f"grant select, insert on table public.{nome} to authenticated" in t
    assert " for update " not in t and " for delete " not in t
    assert not re.search(r"grant [^;]*(update|delete)[^;]*to authenticated", t)


def test_quem_e_carimbado_pelo_servidor():
    assert _texto().count(
        "quem uuid not null default auth.uid() references auth.users (id)") == len(TABELAS)


def test_agendado_nao_se_repete_no_dia_e_as_respostas_sao_fechadas():
    t = _texto()
    assert ("create unique index if not exists pagamento_agendado_um_por_dia "
            "on public.pagamento_agendado (dia, alvo)") in t
    assert "check (resposta in ('pago', 'nao_saiu', 'reagendado'))" in t
    assert "check (valor > 0)" in t
    assert "check (valor_em_aberto is null or valor <= valor_em_aberto)" in t


def test_a_lista_de_abertos_respeita_a_rls():
    t = _texto()
    assert ("create or replace view public.agendado_em_aberto "
            "with (security_invoker = true)") in t
    assert "revoke all on table public.agendado_em_aberto from anon, authenticated" in t
    assert "grant select on table public.agendado_em_aberto to authenticated" in t
```
- [ ] **Passo 2:** `python -m pytest tests/test_pagamentos_do_dia_sql.py -q`. Esperado: FALHA (arquivo ausente).
- [ ] **Passo 3: a migration** (só ASCII nos comentários, como as outras):
```sql
-- ------------------------------------------------ pagamentos do dia na nuvem
-- Entrega 2 da aba "Pagamentos do dia" (especificacao v3, 21/10/2026): o que
-- o dono LIBERA, EDITA e paga A MAO, o que ele marca como AGENDADO e o que
-- responde depois, e a lista do diretor. Tudo com quem/quando/motivo.
--
-- Recorte (o mesmo da `remessa` e da `auditoria`): o app so ACRESCENTA e LE.
--   insert -> sim, para conta liberada (`privado.e_ativo()`), e o `quem` e
--             carimbado pelo servidor (default auth.uid() + with check).
--   update -> NAO. Mudar de ideia e uma linha nova (desfazer, resposta nova).
--   delete -> NAO. Historico de dinheiro nao se apaga.
-- O estado de cada linha e a ULTIMA linha de evento; quem dobra e o app.
--
-- Os ajustes de saldo (simulacao) continuam no JSON local do dia: sao
-- rascunho que vale so para o dia e nao decidem o que e pago.
--
-- Idempotente. Tudo numa transacao.

begin;

create table if not exists public.pagamento_decisao (
  id              bigint generated always as identity primary key,
  dia             date not null,
  alvo            text not null,
  conta           text not null default '',
  acao            text not null,
  motivo          text not null default '',
  campos          jsonb not null default '{}'::jsonb,
  antes           jsonb not null default '{}'::jsonb,
  corrigir_no_erp boolean not null default false,
  quem            uuid not null default auth.uid() references auth.users (id),
  quem_nome       text not null default '',
  quando          timestamptz not null default now(),
  constraint pagamento_decisao_alvo check (length(trim(alvo)) > 0),
  constraint pagamento_decisao_acao check (acao in ('liberar', 'desmarcar', 'editar', 'desfazer', 'remover_a_mao')),
  constraint pagamento_decisao_motivo check (length(motivo) <= 200
    and (acao not in ('liberar', 'editar', 'remover_a_mao') or length(trim(motivo)) >= 3)),
  constraint pagamento_decisao_json check (jsonb_typeof(campos) = 'object' and jsonb_typeof(antes) = 'object')
);
create index if not exists pagamento_decisao_dia_idx on public.pagamento_decisao (dia, id);

create table if not exists public.pagamento_a_mao (
  id              bigint generated always as identity primary key,
  dia             date not null,
  conta           text not null,
  valor           numeric(14,2) not null,
  favorecido      text not null default '',
  tipo            text not null default '',
  dados           text not null default '',
  descricao       text not null,
  lancamento_id   text not null default '',
  centro_custo    text not null default '',
  nf              text not null default '',
  oc              text not null default '',
  valor_em_aberto numeric(14,2),
  motivo          text not null,
  quem            uuid not null default auth.uid() references auth.users (id),
  quem_nome       text not null default '',
  quando          timestamptz not null default now(),
  constraint pagamento_a_mao_valor check (valor > 0),
  constraint pagamento_a_mao_em_aberto check (valor_em_aberto is null or valor <= valor_em_aberto),
  constraint pagamento_a_mao_conta check (length(trim(conta)) > 0),
  constraint pagamento_a_mao_descricao check (length(trim(descricao)) >= 3 and length(descricao) <= 200),
  constraint pagamento_a_mao_motivo check (length(trim(motivo)) >= 3 and length(motivo) <= 200),
  constraint pagamento_a_mao_tipo check (tipo in ('', 'Pix', 'Boleto', 'Transferência'))
);
create index if not exists pagamento_a_mao_dia_idx on public.pagamento_a_mao (dia, id);

create table if not exists public.pagamento_agendado (
  id            bigint generated always as identity primary key,
  dia           date not null,
  conta         text not null,
  alvo          text not null,
  lancamento_id text not null default '',
  a_mao_id      bigint references public.pagamento_a_mao (id),
  favorecido    text not null default '',
  valor         numeric(14,2) not null,
  descricao     text not null default '',
  tipo          text not null default '',
  foto          jsonb not null default '{}'::jsonb,
  quem          uuid not null default auth.uid() references auth.users (id),
  quem_nome     text not null default '',
  quando        timestamptz not null default now(),
  constraint pagamento_agendado_valor check (valor > 0),
  constraint pagamento_agendado_alvo check (length(trim(alvo)) > 0),
  constraint pagamento_agendado_foto check (jsonb_typeof(foto) = 'object')
);
-- Duas maquinas marcando o mesmo pagamento no mesmo dia: o banco recusa a
-- segunda (a trava e o indice, como o `seu_numero_unico_no_dia`).
create unique index if not exists pagamento_agendado_um_por_dia on public.pagamento_agendado (dia, alvo);
create index if not exists pagamento_agendado_dia_idx on public.pagamento_agendado (dia desc);

create table if not exists public.agendado_resposta (
  id          bigint generated always as identity primary key,
  agendado_id bigint not null references public.pagamento_agendado (id),
  resposta    text not null,
  motivo      text not null default '',
  nova_data   date,
  prova       text not null default '',
  quem        uuid not null default auth.uid() references auth.users (id),
  quem_nome   text not null default '',
  quando      timestamptz not null default now(),
  constraint agendado_resposta_tipo check (resposta in ('pago', 'nao_saiu', 'reagendado')),
  constraint agendado_resposta_motivo check (length(motivo) <= 200
    and (resposta <> 'nao_saiu' or length(trim(motivo)) >= 3)),
  constraint agendado_resposta_data check (resposta <> 'reagendado' or nova_data is not null)
);
create index if not exists agendado_resposta_agendado_idx on public.agendado_resposta (agendado_id, id);

create table if not exists public.lista_diretor_nome (
  id         bigint generated always as identity primary key,
  conta      text not null,
  nome_curto text not null,
  quem       uuid not null default auth.uid() references auth.users (id),
  quem_nome  text not null default '',
  quando     timestamptz not null default now(),
  constraint lista_diretor_nome_conta check (length(trim(conta)) > 0),
  constraint lista_diretor_nome_nome check (length(trim(nome_curto)) between 1 and 60)
);
create index if not exists lista_diretor_nome_conta_idx on public.lista_diretor_nome (conta, id);

create table if not exists public.lista_diretor (
  id        bigint generated always as identity primary key,
  dia       date not null,
  ordem     jsonb not null,
  texto     text not null,
  quem      uuid not null default auth.uid() references auth.users (id),
  quem_nome text not null default '',
  quando    timestamptz not null default now(),
  constraint lista_diretor_ordem check (jsonb_typeof(ordem) = 'array')
);
create index if not exists lista_diretor_dia_idx on public.lista_diretor (dia desc, id desc);

-- "Nada some ate voce responder": o agendado cuja ULTIMA resposta nao e
-- final. `security_invoker` faz a RLS das tabelas valer para quem consulta.
create or replace view public.agendado_em_aberto with (security_invoker = true) as
  select a.*
    from public.pagamento_agendado a
   where coalesce((select r.resposta from public.agendado_resposta r
                    where r.agendado_id = a.id order by r.id desc limit 1), '')
         not in ('pago', 'nao_saiu');

revoke all on table public.pagamento_decisao  from anon, authenticated;
revoke all on table public.pagamento_a_mao    from anon, authenticated;
revoke all on table public.pagamento_agendado from anon, authenticated;
revoke all on table public.agendado_resposta  from anon, authenticated;
revoke all on table public.lista_diretor_nome from anon, authenticated;
revoke all on table public.lista_diretor      from anon, authenticated;
revoke all on table public.agendado_em_aberto from anon, authenticated;

grant select, insert on table public.pagamento_decisao  to authenticated;
grant select, insert on table public.pagamento_a_mao    to authenticated;
grant select, insert on table public.pagamento_agendado to authenticated;
grant select, insert on table public.agendado_resposta  to authenticated;
grant select, insert on table public.lista_diretor_nome to authenticated;
grant select, insert on table public.lista_diretor      to authenticated;
grant select on table public.agendado_em_aberto to authenticated;

grant select, insert, update, delete on table public.pagamento_decisao, public.pagamento_a_mao,
  public.pagamento_agendado, public.agendado_resposta, public.lista_diretor_nome,
  public.lista_diretor to service_role;

alter table public.pagamento_decisao  enable row level security;
alter table public.pagamento_a_mao    enable row level security;
alter table public.pagamento_agendado enable row level security;
alter table public.agendado_resposta  enable row level security;
alter table public.lista_diretor_nome enable row level security;
alter table public.lista_diretor      enable row level security;

drop policy if exists pagamento_decisao_le on public.pagamento_decisao;
create policy pagamento_decisao_le on public.pagamento_decisao for select to authenticated using ((select privado.e_ativo()));
drop policy if exists pagamento_decisao_grava on public.pagamento_decisao;
create policy pagamento_decisao_grava on public.pagamento_decisao for insert to authenticated with check ((select privado.e_ativo()) and quem = (select auth.uid()));
-- (o mesmo par `_le`/`_grava`, letra por letra, para pagamento_a_mao,
--  pagamento_agendado, agendado_resposta, lista_diretor_nome, lista_diretor)

commit;

-- Reverter:
--   drop view if exists public.agendado_em_aberto;
--   drop table if exists public.agendado_resposta, public.pagamento_agendado,
--     public.pagamento_a_mao, public.pagamento_decisao, public.lista_diretor,
--     public.lista_diretor_nome;
```
> As 5 linhas de `drop policy`/`create policy` restantes vão ESCRITAS por extenso. O comentário acima é só o lembrete deste plano, e o teste cobra cada uma.
- [ ] **Passo 4:** `python -m pytest tests/test_pagamentos_do_dia_sql.py tests/test_rls_supabase.py -q`. Esperado: PASSA (inclui `test_toda_politica_de_dado_exige_conta_liberada` e `test_a_api_nao_tem_truncate_nem_as_outras_sobras`).
- [ ] **Passo 5:** copie o arquivo, byte a byte, para `C:\AUTOMAÇÕES MAIS CONTROLE\APLICAR NO SUPABASE - 2026-10-22 pagamentos do dia na nuvem.sql`.
- [ ] **Passo 6: commit** — `"Pagamentos do dia: tabelas do dia de trabalho na nuvem (só acrescenta e lê)"` + rodapé.

---

## Tarefa 2 — `nuvem/pagamentos_do_dia.py`: o cliente
**Modelo sugerido:** sonnet.

**Files:** Create `nuvem/pagamentos_do_dia.py`, `tests/test_nuvem_pagamentos_do_dia.py`

**Interfaces:**
```python
class NaoGravou(rest.ErroDaNuvem)
class DiaNaNuvem:
    def __init__(self, token: str, quem_nome: str = "") -> None
    def decisoes_do_dia(self, dia: date) -> list[dict]
    def registrar_decisao(self, dia, *, alvo, conta, acao, motivo="", campos=None, antes=None, corrigir_no_erp=False) -> dict
    def pagamentos_a_mao(self, dia) -> list[dict]
    def registrar_a_mao(self, dia, linha: dict) -> dict
    def agendados_do_dia(self, dia) -> list[dict]
    def agendados_em_aberto(self) -> list[dict]
    def respostas(self, ids) -> list[dict]
    def marcar_agendados(self, dia, linhas: list[dict]) -> tuple[list[dict], list[dict]]   # (gravadas, já marcadas)
    def responder(self, agendado_id, resposta, *, motivo="", nova_data=None, prova="") -> dict
    def nomes_curtos(self) -> dict[str, str]
    def gravar_nome_curto(self, conta, nome) -> dict
    def lista_anterior(self, dia) -> list[dict]
    def gravar_lista(self, dia, ordem: list[dict], texto: str) -> dict
```

- [ ] **Passo 1: teste que falha**
```python
"""O cliente da nuvem do dia, sem rede (dublê do `rest`, como em test_registro_nuvem)."""
from datetime import date

import pytest

from nuvem import pagamentos_do_dia as pdd
from nuvem import rest

DIA = date(2026, 10, 22)


class _RestFalso:
    def __init__(self):
        self.lidas, self.inseridas, self.respostas = [], [], {}
        self.recusar_lote = False

    def ler(self, tabela, _token, *, colunas="*", filtro=""):
        self.lidas.append((tabela, filtro))
        return self.respostas.get(tabela, [])

    def inserir(self, tabela, _token, linhas, *, devolver=True):
        if self.recusar_lote and len(linhas) > 1:
            raise rest.RecusadoPeloBanco("HTTP 409: duplicate key")
        if any(l.get("alvo") == "REPETIDO" for l in linhas):
            raise rest.RecusadoPeloBanco("HTTP 409: duplicate key")
        self.inseridas.append((tabela, linhas))
        return [{"id": i + 1, **l} for i, l in enumerate(linhas)]


@pytest.fixture
def falso(monkeypatch):
    f = _RestFalso()
    monkeypatch.setattr(pdd.rest, "ler", f.ler)
    monkeypatch.setattr(pdd.rest, "inserir", f.inserir)
    return f


def test_decisao_nao_manda_quem_e_leva_o_nome_para_mostrar(falso):
    linha = pdd.DiaNaNuvem("tok", "Fulano").registrar_decisao(
        DIA, alvo="L1", conta="CONTA EXEMPLO - SICOOB", acao="liberar", motivo="pago pelo app")
    tabela, enviadas = falso.inseridas[0]
    assert tabela == "pagamento_decisao"
    assert "quem" not in enviadas[0] and enviadas[0]["quem_nome"] == "Fulano"
    assert enviadas[0]["dia"] == "2026-10-22" and linha["id"] == 1


def test_resposta_sem_a_linha_gravada_e_erro(falso, monkeypatch):
    monkeypatch.setattr(pdd.rest, "inserir", lambda *a, **k: [])
    with pytest.raises(pdd.NaoGravou):
        pdd.DiaNaNuvem("tok").responder(7, "pago")


def test_marcar_agendados_pula_os_ja_marcados_e_cai_no_um_a_um(falso):
    falso.respostas["pagamento_agendado"] = [{"alvo": "L1"}]
    falso.recusar_lote = True
    linhas = [{"alvo": a, "conta": "C", "valor": "10.00"} for a in ("L1", "L2", "REPETIDO")]
    gravadas, repetidas = pdd.DiaNaNuvem("tok").marcar_agendados(DIA, linhas)
    assert [g["alvo"] for g in gravadas] == ["L2"]
    assert sorted(r["alvo"] for r in repetidas) == ["L1", "REPETIDO"]


def test_respostas_em_blocos_de_cem(falso):
    pdd.DiaNaNuvem("tok").respostas(range(1, 251))
    filtros = [f for t, f in falso.lidas if t == "agendado_resposta"]
    assert len(filtros) == 3 and filtros[0].startswith("agendado_id=in.(1,2,")


def test_nome_curto_mais_recente_vale(falso):
    falso.respostas["lista_diretor_nome"] = [{"conta": "Conta Alfa - Banco", "nome_curto": "Alfa"},
                                             {"conta": "Conta Alfa - Banco", "nome_curto": "Alfa - Banco"}]
    assert pdd.DiaNaNuvem("tok").nomes_curtos() == {"Conta Alfa - Banco": "Alfa - Banco"}


def test_lista_anterior_e_a_do_dia_antes(falso):
    falso.respostas["lista_diretor"] = [{"dia": "2026-10-21", "ordem": [{"conta": "A", "ordinal": 1}]}]
    assert pdd.DiaNaNuvem("tok").lista_anterior(DIA) == [{"conta": "A", "ordinal": 1}]
    assert ("lista_diretor", "dia=lt.2026-10-22&order=dia.desc,id.desc&limit=1") in falso.lidas
```
- [ ] **Passo 2:** `python -m pytest tests/test_nuvem_pagamentos_do_dia.py -q`. Esperado: FALHA (módulo ausente).
- [ ] **Passo 3: implementação**
```python
# -*- coding: utf-8 -*-
"""O dia de trabalho da aba "Pagamentos do dia" na nuvem — só LER e ACRESCENTAR.

Migration `20261022100000_pagamentos_do_dia_na_nuvem.sql`. O `quem` não é
enviado (o servidor carimba pelo token); `quem_nome` é só para MOSTRAR, porque
a RLS da `perfil` não deixa ler o nome dos outros. Mudar de ideia é uma linha
nova — o estado é a última, e quem dobra é `tela_do_dia.conferencia`.
Resposta sem a linha gravada levanta `NaoGravou`: "gravado" sem ter gravado é
pior que a recusa (a mesma conferência de `aportes.cadastros.gravar`).
"""
from __future__ import annotations

import datetime as _dt

from . import rest

DECISAO, A_MAO, AGENDADO = "pagamento_decisao", "pagamento_a_mao", "pagamento_agendado"
RESPOSTA, EM_ABERTO = "agendado_resposta", "agendado_em_aberto"
NOME, LISTA = "lista_diretor_nome", "lista_diretor"
LOTE = 100
_COLUNAS_A_MAO = frozenset({"conta", "valor", "descricao", "motivo", "favorecido", "tipo",
                            "dados", "lancamento_id", "centro_custo", "nf", "oc",
                            "valor_em_aberto"})


class NaoGravou(rest.ErroDaNuvem):
    """O banco respondeu sem devolver as linhas pedidas."""


def _iso(dia: _dt.date) -> str:
    return dia.isoformat()


class DiaNaNuvem:
    def __init__(self, token: str, quem_nome: str = "") -> None:
        self._token = token
        self._quem_nome = (quem_nome or "").strip()[:80]

    def _gravar(self, tabela: str, linhas: list[dict]) -> list[dict]:
        corpo = [{**linha, "quem_nome": self._quem_nome} for linha in linhas]
        gravadas = rest.inserir(tabela, self._token, corpo) or []
        if len(gravadas) != len(corpo):
            raise NaoGravou(f"{tabela}: o banco devolveu {len(gravadas)} de "
                            f"{len(corpo)} linha(s)")
        return gravadas

    # ------------------------------------------------------------ passo 2
    def decisoes_do_dia(self, dia):
        return rest.ler(DECISAO, self._token, filtro=f"dia=eq.{_iso(dia)}&order=id.asc")

    def registrar_decisao(self, dia, *, alvo, conta, acao, motivo="", campos=None,
                          antes=None, corrigir_no_erp=False) -> dict:
        return self._gravar(DECISAO, [{
            "dia": _iso(dia), "alvo": str(alvo), "conta": str(conta), "acao": acao,
            "motivo": (motivo or "").strip(), "campos": dict(campos or {}),
            "antes": dict(antes or {}), "corrigir_no_erp": bool(corrigir_no_erp)}])[0]

    def pagamentos_a_mao(self, dia):
        return rest.ler(A_MAO, self._token, filtro=f"dia=eq.{_iso(dia)}&order=id.asc")

    def registrar_a_mao(self, dia, linha: dict) -> dict:
        corpo = {k: v for k, v in linha.items() if k in _COLUNAS_A_MAO}
        return self._gravar(A_MAO, [{"dia": _iso(dia), **corpo}])[0]

    # ---------------------------------------------------------- agendados
    def agendados_do_dia(self, dia):
        return rest.ler(AGENDADO, self._token, filtro=f"dia=eq.{_iso(dia)}&order=id.asc")

    def agendados_em_aberto(self):
        return rest.ler(EM_ABERTO, self._token, filtro="order=dia.asc,id.asc")

    def respostas(self, ids) -> list[dict]:
        ids = sorted({int(i) for i in ids})
        saida = []
        for i in range(0, len(ids), LOTE):
            bloco = ",".join(str(x) for x in ids[i:i + LOTE])
            saida.extend(rest.ler(RESPOSTA, self._token,
                                  filtro=f"agendado_id=in.({bloco})&order=id.asc"))
        return saida

    def marcar_agendados(self, dia, linhas) -> tuple[list[dict], list[dict]]:
        """(gravadas, já marcadas). O índice único (dia, alvo) recusa a
        segunda máquina; o lote recusado é refeito um a um para gravar o resto."""
        ja = {str(l.get("alvo")) for l in self.agendados_do_dia(dia)}
        repetidas = [l for l in linhas if str(l["alvo"]) in ja]
        corpo = [{"dia": _iso(dia), **l} for l in linhas if str(l["alvo"]) not in ja]
        if not corpo:
            return [], repetidas
        try:
            return self._gravar(AGENDADO, corpo), repetidas
        except rest.RecusadoPeloBanco:
            gravadas = []
            for linha in corpo:
                try:
                    gravadas.extend(self._gravar(AGENDADO, [linha]))
                except rest.RecusadoPeloBanco:
                    repetidas.append(linha)
            return gravadas, repetidas

    def responder(self, agendado_id, resposta, *, motivo="", nova_data=None, prova="") -> dict:
        return self._gravar(RESPOSTA, [{
            "agendado_id": int(agendado_id), "resposta": resposta,
            "motivo": (motivo or "").strip(),
            "nova_data": nova_data.isoformat() if nova_data else None,
            "prova": prova or ""}])[0]

    # ---------------------------------------------------- lista do diretor
    def nomes_curtos(self) -> dict[str, str]:
        nomes = {}
        for linha in rest.ler(NOME, self._token, colunas="conta,nome_curto",
                              filtro="order=id.asc"):
            nomes[str(linha["conta"])] = str(linha["nome_curto"])
        return nomes

    def gravar_nome_curto(self, conta, nome) -> dict:
        return self._gravar(NOME, [{"conta": conta, "nome_curto": (nome or "").strip()}])[0]

    def lista_anterior(self, dia) -> list[dict]:
        linhas = rest.ler(LISTA, self._token, colunas="dia,ordem",
                          filtro=f"dia=lt.{_iso(dia)}&order=dia.desc,id.desc&limit=1")
        return list((linhas[0].get("ordem") if linhas else None) or [])

    def gravar_lista(self, dia, ordem, texto) -> dict:
        return self._gravar(LISTA, [{"dia": _iso(dia), "ordem": list(ordem), "texto": texto}])[0]
```
- [ ] **Passo 4:** `python -m pytest tests/test_nuvem_pagamentos_do_dia.py tests/test_empacotamento.py -q` (antes, `git add nuvem/pagamentos_do_dia.py`). Esperado: PASSA.
- [ ] **Passo 5: commit** — `"Pagamentos do dia: cliente da nuvem do dia de trabalho"` + rodapé.

---

## Tarefa 3 — Ganchos opcionais no código compartilhado (comportamento antigo provado)
**Modelo sugerido:** opus (código de dinheiro usado pela Remessa).

**Files:**
- Modify:
  - `pagamentos_dia/relatorio.py` (`:1516`, `:2002`–`:2020`, dict `:2121`–`:2190`)
  - `pagamentos_dia/confirmacao.py:121`
  - `pagamentos_dia/html_pagamentos.py:296`/`:343`
  - `pagamentos_dia/remessa_dia.py:981`
  - `pagamentos_dia/pagamentos_frame.py:3788`/`:3826`
  - `tests/test_remessa_receber_apuracao.py` (acrescentar)
- Create: `tests/test_ganchos_da_tela_do_dia.py`

**Interfaces:**
```python
relatorio.montar_registros(..., qr_pix=None, titulos_nao_lidos=(), ids_liberados=()) -> Resultado
    # id em ids_liberados (e não desmarcado) NÃO vai para omitidos; o registro leva "bloqueio_liberado": <motivo>
confirmacao.remontar(entradas, ids_nao_confirmados=(), *, ids_liberados=()) -> relatorio.Resultado
html_pagamentos.descricao_para_colar(registro, conta, limite=None) -> str   # honra registro["descricao_editada"]
remessa_dia._CHAVES_DA_DESCRICAO  # + "descricao_editada"
PagamentosDiaFrame.receber_apuracao(self, leitura, desmarcados=(), *, hoje=None, resultado=None) -> None
```

- [ ] **Passo 1: testes que falham** — `tests/test_ganchos_da_tela_do_dia.py`
```python
"""Os ganchos da tela do dia no código da Remessa: SEM eles, tudo igual a hoje."""
from datetime import date

from pagamentos_dia import confirmacao, html_pagamentos as hp, relatorio, remessa_dia
from pagamentos_dia import regras_pagamento as regras

DIA = date(2026, 10, 22)
CONTA = "CONTA EXEMPLO - SICOOB"
NF = {"filename": "nf", "tagName": "Nota Fiscal", "extension": ".pdf",
      "downloadUrl": "https://exemplo.invalid/nf.pdf"}


def _lanc(ident):
    return {"id": ident, "tradePayableId": f"T-{ident}", "paidTo": "Fornecedor Modelo Ltda",
            "remainingValue": 100.0, "plannedDate": "2026-10-22",
            "tradePayableAccount": {"name": CONTA}, "tradePayablePaymentMethod": "Pix",
            "paidToBankAccount": "PIX EMAIL fulano@exemplo.com", "documentNumber": "1234",
            "costCentreDetails": [{"workName": "OBRA MODELO"}], "paid": False}


LANCS = [_lanc("L1"), _lanc("L2")]
ANEXOS = {"T-L1": [NF]}                      # L2 sem anexo -> não apto


def test_sem_liberados_o_resultado_e_identico():
    assert (relatorio.montar_registros(LANCS, ANEXOS, {}, {})
            == relatorio.montar_registros(LANCS, ANEXOS, {}, {}, ids_liberados=()))


def test_liberado_sai_dos_omitidos_com_o_bloqueio_anotado():
    r = relatorio.montar_registros(LANCS, ANEXOS, {}, {}, ids_liberados={"L2"})
    assert not [o for o in r.omitidos if o["id"] == "L2"]
    reg = next(x for x in r.contas[CONTA] if x["id"] == "L2")
    assert reg["bloqueio_liberado"] == regras.MOTIVO_SEM_ANEXO
    assert "bloqueio_liberado" not in next(x for x in r.contas[CONTA] if x["id"] == "L1")


def test_desmarcado_ganha_de_liberado():
    r = relatorio.montar_registros(LANCS, ANEXOS, {}, {}, ids_nao_confirmados={"L2"},
                                   ids_liberados={"L2"})
    assert any(o["id"] == "L2" and o["motivo"] == regras.MOTIVO_NAO_CONFIRMADO
               for o in r.omitidos)


def test_remontar_sem_liberados_e_o_de_sempre():
    e = confirmacao.Entradas(selecionados=LANCS, anexos=ANEXOS, overviews={}, textos={},
                             urls_ocr=set(), cadastro_reembolso=None, regras_fornecedor={},
                             participantes={}, periodo=(DIA, DIA))
    assert confirmacao.remontar(e, {"L1"}) == confirmacao.remontar(e, {"L1"}, ids_liberados=())


REG = {"tipo": "Pix", "dados": "fulano@exemplo.com", "valor": 10.0, "centro_custo": "OBRA MODELO",
       "nf": "1234", "nf_anexada": True, "oc_da_descricao": "", "descricao_lancamento": "compra",
       "utilidade": False}


def test_descricao_sem_a_chave_nova_nao_muda():
    for conta in (CONTA, "CONTA X - INTER"):
        assert hp.descricao_para_colar(REG, conta) == hp.descricao_para_colar(
            {**REG, "descricao_editada": ""}, conta)


def test_descricao_editada_vai_limpa_e_no_tamanho():
    texto = hp.descricao_para_colar({**REG, "descricao_editada": "OBRA MODELO pé-direito 1234"},
                                    CONTA, 20)
    assert texto == "OBRA MODELO pe"       # sem acento, sem hífen fora do Inter, corte em palavra


def test_remessa_so_leva_a_descricao_editada_quando_ela_existe():
    reg = {**REG, "status": "APTO", "id": "L1", "favorecido": "Fornecedor Modelo Ltda"}
    sem = remessa_dia.preparar({CONTA: [reg]})[CONTA][0]
    com = remessa_dia.preparar({CONTA: [{**reg, "descricao_editada": "OBRA MODELO 1234"}]})[CONTA][0]
    assert "descricao_editada" not in sem.partes
    assert remessa_dia.etiqueta_do_banco(com) == "OBRA MODELO 1234"
    assert remessa_dia.etiqueta_do_banco(sem) == hp.descricao_para_colar(sem.partes, None, 38)
```
Acrescentar em `tests/test_remessa_receber_apuracao.py`:
```python
def test_resultado_pronto_da_tela_e_usado_sem_remontar():
    gerou = []
    aba = _aba(gerou)
    pronto = confirmacao.remontar(_leitura().entradas, {"L1"})
    PagamentosDiaFrame.receber_apuracao(aba, _leitura(), set(), hoje=DIA, resultado=pronto)
    assert aba.resultado is pronto and gerou == [True]
```
- [ ] **Passo 2:** `python -m pytest tests/test_ganchos_da_tela_do_dia.py tests/test_remessa_receber_apuracao.py -q`. Esperado: FALHA (`ids_liberados`/`resultado` desconhecidos; etiqueta sem a editada).
- [ ] **Passo 3: implementação**
  - `relatorio.montar_registros`:
    - acrescente `ids_liberados=()` no fim da assinatura e `ids_liberados = {str(i) for i in (ids_liberados or ())}` ao lado de `:1547`;
    - documente o parâmetro na docstring: "lançamentos que a tela 'Pagamentos do dia' liberou com motivo, na nuvem; saem dos omitidos com o bloqueio em `bloqueio_liberado`; vazio = como sempre";
    - no laço, troque `motivo = ""` (`:2002`) por `motivo, liberado_de = "", ""`;
    - logo antes de `if motivo:` (`:2020`) ponha:
    ```python
            if (motivo and motivo != regras.MOTIVO_NAO_CONFIRMADO
                    and str(item.get("id")) in ids_liberados):
                # Liberado na tela do dia: o motivo não some, vai junto
                # (`bloqueio_liberado`) e a tela decide o status. Desmarcado
                # continua ganhando: desmarcar é a última palavra de quem confere.
                liberado_de, motivo = motivo, ""
    ```
    - e, como última entrada do `registros[conta].append({...})` (depois de `"reembolso_para": (...)`, `:2180`): `**({"bloqueio_liberado": liberado_de} if liberado_de else {}),`.
  - `confirmacao.remontar(entradas, ids_nao_confirmados=(), *, ids_liberados=())`: passe `ids_liberados=ids_liberados` no `montar_registros`.
  - `html_pagamentos.descricao_para_colar`: logo depois de `r = registro or {}` (`:343`):
  ```python
      editada = str(r.get("descricao_editada") or "").strip()
      if editada:
          # Escrita pelo dono na tela "Pagamentos do dia" (entrega 2). Vai como
          # ele escreveu, só limpa e no tamanho do banco; a tela avisa antes de
          # gravar se ela perdeu o centro de custo ou o documento no fim
          # (`tela_do_dia.conferencia.aviso_de_casamento`). Registro sem a
          # chave — todos os da Remessa — segue o caminho de sempre abaixo.
          tirar = (lambda ps: ps) if _e_inter(conta) else _sem_hifen
          espaco = limite_da_descricao(conta) if limite is None else limite
          return " ".join(_que_cabem(tirar(_palavras(editada)), espaco))
  ```
  - `remessa_dia._CHAVES_DA_DESCRICAO`: acrescente `"descricao_editada"` no fim da tupla (`:981`). O `preparar` só copia a chave quando ela está no registro (`if k in registro`), então registros da Remessa não mudam.
  - `pagamentos_frame.receber_apuracao`: assinatura `(self, leitura, desmarcados=(), *, hoje=None, resultado=None)`. Acrescente à docstring: "`resultado` é o da tela do dia já com liberados/editados (entrega 2); `None` remonta como sempre". Troque `:3826` por:
  ```python
          self.resultado = (resultado if resultado is not None
                            else confirmacao.remontar(leitura.entradas, set(desmarcados)))
  ```
- [ ] **Passo 4:** `python -m pytest tests/test_ganchos_da_tela_do_dia.py tests/test_remessa_receber_apuracao.py tests/test_html_pagamentos.py tests/test_remessa_dia.py tests/test_confirmacao.py tests/test_pagamentos_dia.py tests/test_descricao_e_ordem.py tests/test_regras_14_10.py -q`. Esperado: PASSA, e nenhum teste antigo alterado.
- [ ] **Passo 5: commit** — `"Remessa: ganchos opcionais para a tela do dia (sem eles, tudo igual)"` + rodapé.

---

## Tarefa 4 — `conferencia.py`: eventos, decisões e validações do passo 2
**Modelo sugerido:** opus.

**Files:** Create `tela_do_dia/conferencia.py`, `tests/test_tela_do_dia_conferencia.py`

**Interfaces:**
```python
LIBERAR, DESMARCAR, EDITAR, DESFAZER, REMOVER_A_MAO: str
PREFIXO_A_MAO = "mao:"; TIPOS = ("Pix", "Boleto", "Transferência")
CAMPOS_EDITAVEIS = ("tipo", "dados", "reembolso_nome", "reembolso_documento", "descricao")
@dataclass(frozen=True) class Evento: id; alvo; conta; acao; motivo; campos: dict; antes: dict; corrigir_no_erp; quem_nome; quando
    @classmethod de_linha(linha: dict) -> Evento
@dataclass class Decisao: alvo; conta=""; liberado=False; motivo_liberacao=""; desmarcado=False; motivo_desmarcar="";
    edicoes: dict; antes: dict; motivo_edicao=""; corrigir_no_erp=False; removido=False; quem_nome=""; quando=""
    editado (property)
def dobrar(eventos) -> dict[str, Decisao]
@dataclass(frozen=True) class PagamentoAMao: id; conta; valor: Decimal; descricao; motivo; favorecido=""; tipo=""; dados="";
    lancamento_id=""; centro_custo=""; nf=""; oc=""; valor_em_aberto: Decimal|None=None; quem_nome=""; quando=""
    alvo (property) ; de_linha(linha) (classmethod)
@dataclass(frozen=True) class Conferencia: eventos: tuple = (); pagamentos_a_mao: tuple = ()
    decisoes (property) ; a_mao (property: sem os removidos)
    da_nuvem(decisoes: list[dict], a_mao: list[dict]) (classmethod) ; com_evento(linha) ; com_a_mao(linha)
def pode_liberar(linha: confirmacao.Linha) -> bool
def pede_certeza(linha: confirmacao.Linha) -> str
def validar_motivo(motivo: str) -> str
def validar_edicao(campos: dict, motivo: str) -> str
def aviso_de_casamento(registro: dict, conta: str) -> str
def nova_a_mao(*, conta, valor_texto, descricao, motivo, contas, lido=None, tipo="", dados="", favorecido="") -> tuple[dict | None, str]
```

- [ ] **Passo 1: teste que falha**
```python
"""A conferência editável: eventos dobrados, travas e o casamento do Anexar."""
from decimal import Decimal as D

from pagamentos_dia import confirmacao
from tela_do_dia import conferencia as cf
from tela_do_dia.lancamento_do_erp import LancamentoLido

LINHA_BANCARIA = "34191.57007 00024.924375 24177.010006 9 15340000115000"   # a de tests/test_remessa_dia.py


def _ev(i, alvo, acao, **k):
    return cf.Evento.de_linha({"id": i, "alvo": alvo, "conta": "C", "acao": acao, **k})


def test_a_ultima_palavra_vale_e_desfazer_volta_ao_erp():
    d = cf.dobrar([_ev(1, "L1", cf.LIBERAR, motivo="pago hoje"),
                   _ev(2, "L1", cf.DESMARCAR)])
    assert d["L1"].desmarcado and not d["L1"].liberado
    d = cf.dobrar([_ev(3, "L1", cf.DESFAZER), _ev(1, "L1", cf.LIBERAR, motivo="pago hoje")])
    assert "L1" not in d                                    # ordem é pelo id, não pela lista


def test_edicao_acumula_e_guarda_o_primeiro_original():
    d = cf.dobrar([_ev(1, "L1", cf.EDITAR, campos={"descricao": "A"}, antes={"descricao": "orig"}, motivo="erro do ERP"),
                   _ev(2, "L1", cf.EDITAR, campos={"descricao": "B"}, antes={"descricao": "A"}, motivo="de novo",
                       corrigir_no_erp=True)])["L1"]
    assert d.edicoes == {"descricao": "B"} and d.antes == {"descricao": "orig"} and d.corrigir_no_erp


def test_a_mao_removida_some_da_conferencia():
    conf = cf.Conferencia.da_nuvem(
        [{"id": 9, "alvo": "mao:5", "acao": cf.REMOVER_A_MAO, "motivo": "lancei errado"}],
        [{"id": 5, "conta": "C", "valor": "30.00", "descricao": "parcela", "motivo": "combinado"},
         {"id": 6, "conta": "C", "valor": "10.00", "descricao": "taxa", "motivo": "combinado"}])
    assert [p.id for p in conf.a_mao] == [6] and conf.a_mao[0].valor == D("10.00")


class _Enviado:
    ja_enviado = "remessa nº 000007 de 20/10"


def _linha(secao, situacao="", candidato=None):
    return confirmacao.Linha(secao=secao, id="L1", conta="C", valor=10.0, favorecido="F", tipo="Pix",
                             dados="", por_onde="", vencimento=None, oc="", centro_custo="",
                             descricao="", situacao=situacao, estado="ok", olhar=False, candidato=candidato)


def test_ja_enviado_e_fora_dos_contatos_pedem_certeza():
    assert "JÁ SAIU" in cf.pede_certeza(_linha("entra", candidato=_Enviado()))
    assert "Contatos" in cf.pede_certeza(_linha("entra", "pix · o favorecido não está no cadastro de Contatos do ERP, …"))
    assert cf.pede_certeza(_linha("nao_apto", "sem anexo — sem anexo, sem pagamento")) == ""
    assert cf.pode_liberar(_linha("nao_apto")) and cf.pode_liberar(_linha("entra", candidato=_Enviado()))
    assert not cf.pode_liberar(_linha("entra"))


def test_edicao_de_forma_exige_chave_com_tipo_ou_linha_que_fecha():
    assert cf.validar_edicao({"tipo": "Pix", "dados": "PIX EMAIL fulano@exemplo.com"}, "erro do ERP") == ""
    assert "tipo" in cf.validar_edicao({"tipo": "Pix", "dados": "62999999999"}, "erro do ERP")
    assert cf.validar_edicao({"tipo": "Boleto", "dados": LINHA_BANCARIA}, "boleto novo") == ""
    assert "dígitos" in cf.validar_edicao({"tipo": "Boleto", "dados": "123"}, "boleto novo")
    assert "motivo" in cf.validar_edicao({"descricao": "OBRA MODELO 1234"}, "")
    assert "CPF" in cf.validar_edicao({"reembolso_nome": "Fulano Ficticio",
                                       "reembolso_documento": "11111111111"}, "reembolso")


def test_aviso_de_casamento_diz_o_que_o_anexar_vai_perder():
    reg = {"centro_custo": "OBRA MODELO QD 1", "nf": "1234", "valor": 10.0}
    assert cf.aviso_de_casamento({**reg, "descricao_editada": "OBRA MODELO QD 1 COMPRA 1234"}, "C") == ""
    aviso = cf.aviso_de_casamento({**reg, "descricao_editada": "COMPRA DE MATERIAL"}, "C")
    assert "centro de custo" in aviso and "número do documento" in aviso


def test_a_mao_com_link_nao_paga_mais_que_o_em_aberto_nem_titulo_pago():
    lido = LancamentoLido(id="L9", conta="C", favorecido="Fornecedor Modelo Ltda",
                          centro_custo="OBRA MODELO", nf="1234", em_aberto=D("80000.00"))
    linha, erro = cf.nova_a_mao(conta="C", valor_texto="30.000,00", descricao="parcela",
                                motivo="combinado", contas={"C"}, lido=lido)
    assert erro == "" and linha["lancamento_id"] == "L9" and linha["valor"] == "30000.00"
    assert linha["valor_em_aberto"] == "80000.00" and linha["favorecido"] == "Fornecedor Modelo Ltda"
    _l, erro = cf.nova_a_mao(conta="C", valor_texto="90.000,00", descricao="parcela",
                             motivo="combinado", contas={"C"}, lido=lido)
    assert "em aberto" in erro
    _l, erro = cf.nova_a_mao(conta="C", valor_texto="10,00", descricao="parcela", motivo="combinado",
                             contas={"C"}, lido=LancamentoLido(id="L9", conta="C", pago=True))
    assert "PAGO" in erro
```
- [ ] **Passo 2:** `python -m pytest tests/test_tela_do_dia_conferencia.py -q`. Esperado: FALHA (módulos ausentes; a Tarefa 7 cria `lancamento_do_erp` — **faça a Tarefa 7 antes desta**, ou crie já o `LancamentoLido` da Tarefa 7).
- [ ] **Passo 3: implementação** (trechos que decidem; docstrings de módulo e funções curtas, em português)
```python
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from anexar import matcher
from pagamentos_dia import confirmacao, html_pagamentos, ocr_boleto
from pagamentos_dia import regras_pagamento as regras

from .valores import brl, ler_valor_editado

LIBERAR, DESMARCAR, EDITAR, DESFAZER, REMOVER_A_MAO = (
    "liberar", "desmarcar", "editar", "desfazer", "remover_a_mao")
PREFIXO_A_MAO = "mao:"
MOTIVO_MINIMO, TEXTO_MAXIMO = 3, 200
TIPOS = ("Pix", "Boleto", "Transferência")
CAMPOS_EDITAVEIS = ("tipo", "dados", "reembolso_nome", "reembolso_documento", "descricao")


@dataclass(frozen=True)
class Evento:
    id: int
    alvo: str
    conta: str
    acao: str
    motivo: str = ""
    campos: dict = field(default_factory=dict)
    antes: dict = field(default_factory=dict)
    corrigir_no_erp: bool = False
    quem_nome: str = ""
    quando: str = ""

    @classmethod
    def de_linha(cls, linha: dict) -> "Evento":
        return cls(id=int(linha.get("id") or 0), alvo=str(linha.get("alvo") or ""),
                   conta=str(linha.get("conta") or ""), acao=str(linha.get("acao") or ""),
                   motivo=str(linha.get("motivo") or ""), campos=dict(linha.get("campos") or {}),
                   antes=dict(linha.get("antes") or {}),
                   corrigir_no_erp=bool(linha.get("corrigir_no_erp")),
                   quem_nome=str(linha.get("quem_nome") or ""), quando=str(linha.get("quando") or ""))


@dataclass
class Decisao:
    alvo: str
    conta: str = ""
    liberado: bool = False
    motivo_liberacao: str = ""
    desmarcado: bool = False
    motivo_desmarcar: str = ""
    edicoes: dict = field(default_factory=dict)
    antes: dict = field(default_factory=dict)
    motivo_edicao: str = ""
    corrigir_no_erp: bool = False
    removido: bool = False
    quem_nome: str = ""
    quando: str = ""

    @property
    def editado(self) -> bool:
        return bool(self.edicoes)


def dobrar(eventos) -> dict[str, Decisao]:
    """O estado de cada alvo depois de TODOS os eventos, na ordem do id
    (a do banco). Ação desconhecida (app mais novo) não decide nada."""
    estado: dict[str, Decisao] = {}
    for ev in sorted(eventos, key=lambda e: e.id):
        if ev.acao == DESFAZER:
            estado.pop(ev.alvo, None)
            continue
        if ev.acao not in (LIBERAR, DESMARCAR, EDITAR, REMOVER_A_MAO):
            continue
        d = estado.setdefault(ev.alvo, Decisao(ev.alvo, conta=ev.conta))
        if ev.acao == LIBERAR:
            d.liberado, d.desmarcado, d.motivo_liberacao = True, False, ev.motivo
        elif ev.acao == DESMARCAR:
            d.desmarcado, d.liberado, d.motivo_desmarcar = True, False, ev.motivo
        elif ev.acao == EDITAR:
            for k, v in ev.antes.items():
                d.antes.setdefault(k, v)
            d.edicoes.update({k: v for k, v in ev.campos.items() if k in CAMPOS_EDITAVEIS})
            d.motivo_edicao = ev.motivo
            d.corrigir_no_erp = d.corrigir_no_erp or ev.corrigir_no_erp
        else:
            d.removido = True
        d.quem_nome, d.quando = ev.quem_nome, ev.quando
    return estado


@dataclass(frozen=True)
class PagamentoAMao:
    id: int
    conta: str
    valor: Decimal
    descricao: str
    motivo: str
    favorecido: str = ""
    tipo: str = ""
    dados: str = ""
    lancamento_id: str = ""
    centro_custo: str = ""
    nf: str = ""
    oc: str = ""
    valor_em_aberto: Decimal | None = None
    quem_nome: str = ""
    quando: str = ""

    @property
    def alvo(self) -> str:
        return f"{PREFIXO_A_MAO}{self.id}"

    @classmethod
    def de_linha(cls, linha: dict) -> "PagamentoAMao":
        aberto = linha.get("valor_em_aberto")
        return cls(id=int(linha["id"]), conta=str(linha["conta"]),
                   valor=Decimal(str(linha["valor"])), descricao=str(linha.get("descricao") or ""),
                   motivo=str(linha.get("motivo") or ""), favorecido=str(linha.get("favorecido") or ""),
                   tipo=str(linha.get("tipo") or ""), dados=str(linha.get("dados") or ""),
                   lancamento_id=str(linha.get("lancamento_id") or ""),
                   centro_custo=str(linha.get("centro_custo") or ""), nf=str(linha.get("nf") or ""),
                   oc=str(linha.get("oc") or ""),
                   valor_em_aberto=None if aberto in (None, "") else Decimal(str(aberto)),
                   quem_nome=str(linha.get("quem_nome") or ""), quando=str(linha.get("quando") or ""))


@dataclass(frozen=True)
class Conferencia:
    eventos: tuple = ()
    pagamentos_a_mao: tuple = ()

    @property
    def decisoes(self) -> dict[str, Decisao]:
        return dobrar(self.eventos)

    @property
    def a_mao(self) -> list[PagamentoAMao]:
        d = self.decisoes
        return [p for p in self.pagamentos_a_mao
                if not (d.get(p.alvo) and d[p.alvo].removido)]

    @classmethod
    def da_nuvem(cls, decisoes, a_mao) -> "Conferencia":
        return cls(tuple(Evento.de_linha(x) for x in decisoes or ()),
                   tuple(PagamentoAMao.de_linha(x) for x in a_mao or ()))

    def com_evento(self, linha: dict) -> "Conferencia":
        return Conferencia((*self.eventos, Evento.de_linha(linha)), self.pagamentos_a_mao)

    def com_a_mao(self, linha: dict) -> "Conferencia":
        return Conferencia(self.eventos, (*self.pagamentos_a_mao, PagamentoAMao.de_linha(linha)))


def pode_liberar(linha) -> bool:
    """Não apto, ou já enviado (entra mas nasce desmarcado). O que já vai
    sair não tem o que liberar."""
    return linha.secao == confirmacao.NAO_APTO or (
        linha.marcavel and not confirmacao.marcada_de_inicio(linha))


def pede_certeza(linha) -> str:
    enviado = getattr(linha.candidato, "ja_enviado", "")
    if enviado and not linha.envio_rejeitado:
        return (f"Este pagamento JÁ SAIU numa remessa ({enviado}). Liberar é gerar de "
                "novo — o banco pode pagar duas vezes.\n\nTem certeza?")
    if "cadastro de Contatos" in (linha.situacao or ""):
        return ("O favorecido não está no cadastro de Contatos do ERP: a remessa não "
                "tem o documento dele.\n\nTem certeza?")
    return ""


def validar_motivo(motivo: str) -> str:
    m = (motivo or "").strip()
    if len(m) < MOTIVO_MINIMO:
        return "Escreva um motivo curto (3 letras ou mais)."
    if len(m) > TEXTO_MAXIMO:
        return "O motivo passa de 200 caracteres."
    return ""


def validar_edicao(campos: dict, motivo: str) -> str:
    erro = validar_motivo(motivo)
    if erro:
        return erro
    if not campos:
        return "Nada mudou."
    fora = set(campos) - set(CAMPOS_EDITAVEIS)
    if fora:
        return "Campo que não se edita aqui: " + ", ".join(sorted(fora))
    if ("tipo" in campos) != ("dados" in campos):
        return "A forma de pagar muda junto: o tipo e o dado."
    if "tipo" in campos:
        tipo, dados = campos["tipo"], str(campos.get("dados") or "").strip()
        if tipo not in TIPOS:
            return f"Forma de pagar desconhecida: {tipo}."
        if tipo == "Pix" and not regras.tipo_de_chave_pix(dados):
            return ("A chave Pix não diz o tipo (CPF ou celular têm 11 dígitos): escreva "
                    "\"PIX CPF …\", \"PIX CELULAR …\", o e-mail ou a chave aleatória.")
        if tipo == "Boleto" and not ocr_boleto.codigo_de_barras(dados):
            return "A linha digitável não fecha nos dígitos verificadores."
        if tipo == "Transferência" and len(dados) < 8:
            return "Escreva banco, agência e conta da transferência."
    if "reembolso_nome" in campos or "reembolso_documento" in campos:
        if not str(campos.get("reembolso_nome") or "").strip():
            return "Falta o nome de quem recebe o reembolso."
        if not regras.documento_valido(campos.get("reembolso_documento") or ""):
            return "O CPF/CNPJ de quem recebe o reembolso não fecha no dígito verificador."
    if "descricao" in campos:
        d = str(campos["descricao"] or "").strip()
        if not MOTIVO_MINIMO <= len(d) <= TEXTO_MAXIMO or d.startswith("="):
            return "A descrição tem de ter de 3 a 200 caracteres (e não começar com \"=\")."
    return ""


def aviso_de_casamento(registro: dict, conta: str) -> str:
    """O que o Anexar vai deixar de achar com ESTA descrição — com as mesmas
    funções dele (`anexar/matcher.py`): centro de custo no texto e o número do
    documento como último número (ou rotulado NF/OC). "" = casa como hoje."""
    texto = html_pagamentos.descricao_para_colar(registro, conta)
    ndesc = matcher._com_hifen(matcher._norm(texto))
    avisos = []
    cc = str(registro.get("centro_custo") or "")
    if cc and not any(len(p) >= 6 and p in ndesc for p in
                      (matcher._com_hifen(matcher._norm(x)) for x in cc.split("|"))):
        avisos.append("o centro de custo não está na descrição")
    numeros = set()
    for doc in (registro.get("nf"), registro.get("oc_da_descricao")):
        numeros |= matcher._numeros_do_documento(str(doc or ""))
    if numeros:
        cents = html_pagamentos.centavos(registro.get("valor"))
        achados = (matcher._numeros_soltos(texto, cents)
                   | {matcher._sem_zeros(n) for n in matcher._ocnf_rotulados(texto)})
        if not numeros & achados:
            avisos.append("o número do documento não é o último número da descrição")
    if not avisos:
        return ""
    return ("O Anexar casa o comprovante pelo centro de custo e pelo último número da "
            "descrição: " + "; ".join(avisos) + f".\nVai ao banco: {texto}")


def nova_a_mao(*, conta, valor_texto, descricao, motivo, contas, lido=None,
               tipo="", dados="", favorecido="") -> tuple[dict | None, str]:
    if conta not in contas:
        return None, "Escolha a conta na lista."
    try:
        valor = ler_valor_editado(valor_texto)
    except ValueError as e:
        return None, str(e)
    if valor <= 0:
        return None, "O valor tem de ser maior que zero."
    descricao = (descricao or "").strip()
    if not MOTIVO_MINIMO <= len(descricao) <= TEXTO_MAXIMO or descricao.startswith("="):
        return None, "A descrição tem de ter de 3 a 200 caracteres."
    erro = validar_motivo(motivo)
    if not erro and (tipo or dados):
        erro = validar_edicao({"tipo": tipo, "dados": dados}, motivo)
    if erro:
        return None, erro
    linha = {"conta": conta, "valor": str(valor), "descricao": descricao,
             "motivo": motivo.strip(), "favorecido": (favorecido or "").strip(),
             "tipo": tipo, "dados": (dados or "").strip()}
    if lido is not None:
        if lido.pago:
            return None, "Este lançamento já está PAGO no ERP."
        if lido.conta and lido.conta != conta:
            return None, f"O lançamento é da conta {lido.conta}, não de {conta}."
        if lido.em_aberto is not None and valor > lido.em_aberto:
            return None, f"O valor passa do que está em aberto no lançamento ({brl(lido.em_aberto)})."
        linha.update(lancamento_id=lido.id, centro_custo=lido.centro_custo, nf=lido.nf,
                     oc=lido.oc, favorecido=linha["favorecido"] or lido.favorecido,
                     valor_em_aberto=None if lido.em_aberto is None else str(lido.em_aberto))
    return linha, ""
```
- [ ] **Passo 4:** `python -m pytest tests/test_tela_do_dia_conferencia.py -q`. Esperado: PASSA.
- [ ] **Passo 5: commit** — `"Pagamentos do dia: liberar, desmarcar, editar e à mão — as regras"` + rodapé.

---

## Tarefa 5 — `geracao.py`: o que sai em planilha, HTML e remessa
**Modelo sugerido:** opus.

**Files:** Create `tela_do_dia/geracao.py`, `tests/test_tela_do_dia_geracao.py`

**Interfaces:**
```python
BLOQUEIO_JA_ENVIADO = "já enviado em remessa"
ATENCOES_DE_FORMA = ("ATENÇÃO — sem anexo", "ATENÇÃO — sem dados de pgto", "ATENÇÃO — pagar à mão")
ORDEM_A_MAO = 1_000_000
def ids_nao_aptos(grupos) -> set[str]
def aplicar_decisao(reg: dict, d: Decisao | None, *, liberavel: bool) -> dict
def registro_a_mao(p: PagamentoAMao, ordem: int) -> dict
def resultado_da_tela(entradas, grupos, conferencia: Conferencia) -> relatorio.Resultado
def para_a_remessa(resultado) -> relatorio.Resultado
def chaves_que_saem(resultado) -> set[str]
def registro_atual(resultado, ident: str) -> dict | None
```

- [ ] **Passo 1: teste que falha**
```python
"""O Resultado da tela: liberados, editados e à mão — e a remessa sem os à mão."""
from datetime import date

import pytest

from pagamentos_dia import confirmacao, html_pagamentos as hp, remessa_dia
from pagamentos_dia import regras_pagamento as regras
from tela_do_dia import conferencia as cf, geracao as ge
from tela_do_dia import pagamentos as pg

DIA = date(2026, 10, 22)
CONTA = "CONTA EXEMPLO - SICOOB"
NF = lambda n: {"filename": n, "tagName": "Nota Fiscal", "extension": ".pdf",  # noqa: E731
                "downloadUrl": f"https://exemplo.invalid/{n}.pdf"}


def _lanc(ident):
    return {"id": ident, "tradePayableId": f"T-{ident}", "paidTo": "Fornecedor Modelo Ltda",
            "remainingValue": 100.0, "plannedDate": "2026-10-22", "tradePayableAccount": {"name": CONTA},
            "tradePayablePaymentMethod": "Pix", "paidToBankAccount": "PIX EMAIL fulano@exemplo.com",
            "documentNumber": "1234", "costCentreDetails": [{"workName": "OBRA MODELO"}], "paid": False}


@pytest.fixture
def dia():
    e = confirmacao.Entradas(selecionados=[_lanc("L1"), _lanc("L2"), _lanc("L3")],
                             anexos={"T-L1": [NF("n1")], "T-L3": [NF("n3")]}, overviews={}, textos={},
                             urls_ocr=set(), cadastro_reembolso=None, regras_fornecedor={},
                             participantes={}, periodo=(DIA, DIA))
    grupos = confirmacao.grupos_da_confirmacao(confirmacao.remontar(e), None, e.selecionados)
    return e, grupos


def _conf(eventos=(), a_mao=()):
    return cf.Conferencia.da_nuvem(list(eventos), list(a_mao))


def test_sem_conferencia_e_o_mesmo_da_entrega_1(dia):
    e, grupos = dia
    assert ge.resultado_da_tela(e, grupos, _conf()) == confirmacao.remontar(e, pg.ids_que_nao_saem(grupos))


def test_liberado_entra_marcado_como_liberado_e_nao_como_apto(dia):
    e, grupos = dia
    r = ge.resultado_da_tela(e, grupos, _conf([{"id": 1, "alvo": "L2", "acao": cf.LIBERAR,
                                                "motivo": "nota chega amanhã", "quem_nome": "Fulano"}]))
    reg = ge.registro_atual(r, "L2")
    assert reg["status"].startswith("LIBERADO — " + regras.MOTIVO_SEM_ANEXO)
    assert "liberado na tela por Fulano" in reg["obs"]
    cand = remessa_dia.preparar(ge.para_a_remessa(r).contas)[CONTA]
    assert not next(c for c in cand if c.id == "L2").apto        # nasce desmarcado na Remessa


def test_desmarcado_vai_para_os_omitidos(dia):
    e, grupos = dia
    r = ge.resultado_da_tela(e, grupos, _conf([{"id": 1, "alvo": "L3", "acao": cf.DESMARCAR}]))
    assert any(o["id"] == "L3" and o["motivo"] == regras.MOTIVO_NAO_CONFIRMADO for o in r.omitidos)


def test_edicao_de_forma_troca_o_dado_e_avisa_corrigir_no_erp(dia):
    e, grupos = dia
    r = ge.resultado_da_tela(e, grupos, _conf([{
        "id": 1, "alvo": "L1", "acao": cf.EDITAR, "motivo": "chave errada no ERP",
        "campos": {"tipo": "Pix", "dados": "PIX EMAIL outro@exemplo.com"},
        "antes": {"tipo": "Pix", "dados": "fulano@exemplo.com"}, "corrigir_no_erp": True}]))
    reg = ge.registro_atual(r, "L1")
    assert reg["dados"] == "PIX EMAIL outro@exemplo.com" and reg["pix_qr"] == ""
    assert reg["status"] == "EDITADO — forma de pagar"
    assert "corrigir no ERP: lançamento L1" in reg["obs"]


def test_so_descricao_mantem_o_status_e_vai_ao_html(dia):
    e, grupos = dia
    r = ge.resultado_da_tela(e, grupos, _conf([{"id": 1, "alvo": "L1", "acao": cf.EDITAR,
                                                "motivo": "texto melhor", "campos": {"descricao": "OBRA MODELO PISO 1234"}}]))
    reg = ge.registro_atual(r, "L1")
    assert reg["status"].startswith("APTO")
    entrada = next(x for c in hp.contas_do_html_geral(r) for x in c["entries"] if x["id"] == "L1")
    assert entrada["descricao"] == "OBRA MODELO PISO 1234"


def test_atencao_grave_nao_some_com_a_edicao():
    d = cf.dobrar([cf.Evento.de_linha({"id": 1, "alvo": "X", "acao": cf.EDITAR, "motivo": "nova chave",
                                       "campos": {"tipo": "Pix", "dados": "PIX EMAIL a@exemplo.com"}})])["X"]
    reg = ge.aplicar_decisao({"id": "X", "status": "ATENÇÃO — valor do boleto diverge", "obs": ""}, d,
                             liberavel=False)
    assert reg["status"].startswith("ATENÇÃO — valor do boleto diverge")


def test_a_mao_entra_no_html_e_na_planilha_mas_nao_na_remessa(dia):
    e, grupos = dia
    r = ge.resultado_da_tela(e, grupos, _conf(a_mao=[{
        "id": 4, "conta": CONTA, "valor": "30.00", "descricao": "parcela combinada",
        "motivo": "acordo", "favorecido": "Fornecedor Modelo Ltda", "tipo": "Pix",
        "dados": "PIX EMAIL fulano@exemplo.com", "lancamento_id": "L9", "centro_custo": "OBRA MODELO",
        "nf": "5678", "valor_em_aberto": "80.00"}]))
    reg = next(x for x in r.contas[CONTA] if x.get("a_mao") == "mao:4")
    assert reg["id"] == "L9" and reg["status"] == "À MÃO — acordo" and reg["valor"] == 30.0
    assert "mao:4" in ge.chaves_que_saem(r)
    assert all(not x.get("a_mao") for x in ge.para_a_remessa(r).contas[CONTA])
    entrada = next(x for c in hp.contas_do_html_geral(r) for x in c["entries"] if x["id"] == "L9")
    assert entrada["descricao"].startswith("OBRA MODELO") and entrada["descricao"].endswith("5678")
    assert entrada["bloqueio"] == ""
```
- [ ] **Passo 2:** `python -m pytest tests/test_tela_do_dia_geracao.py -q`. Esperado: FALHA.
- [ ] **Passo 3: implementação**
```python
"""O `Resultado` que a tela manda para planilha, HTML e remessa — sem tela.

É o da Remessa (`confirmacao.remontar`, com os MESMOS argumentos) e mais o
que o dono decidiu na nuvem: liberados (`ids_liberados`), desmarcados,
edições e pagamentos à mão. Os status novos — LIBERADO, EDITADO, À MÃO — não
começam com "APTO": na conferência da Remessa nascem DESMARCADOS
(`remessa_dia.Candidato.apto`). E não começam com "ATENÇÃO", então o HTML
deixa copiar, exceto quando já havia ATENÇÃO grave (só as de forma de
pagar cedem). À mão NUNCA vai na remessa CNAB: sem lançamento, não há
referência para o retorno nem para a baixa (`para_a_remessa`).
"""
from __future__ import annotations

from pagamentos_dia import confirmacao, relatorio

from . import pagamentos as pg

BLOQUEIO_JA_ENVIADO = "já enviado em remessa"
ATENCOES_DE_FORMA = ("ATENÇÃO — sem anexo", "ATENÇÃO — sem dados de pgto",
                     "ATENÇÃO — pagar à mão")
ORDEM_A_MAO = 1_000_000


def ids_nao_aptos(grupos) -> set[str]:
    return {ln.id for g in grupos for ln in g.nao_aptos if ln.id}


def _status(antes: str, rotulo: str) -> str:
    if antes.startswith("ATENÇÃO") and antes not in ATENCOES_DE_FORMA:
        return f"{antes} · {rotulo}"
    return rotulo


def aplicar_decisao(reg: dict, d, *, liberavel: bool) -> dict:
    if d is None:
        return reg
    antes, notas = str(reg.get("status") or ""), []
    if d.edicoes:
        campos = []
        if "tipo" in d.edicoes:
            reg["tipo"], reg["dados"], reg["pix_qr"] = d.edicoes["tipo"], d.edicoes.get("dados", ""), ""
            campos.append("forma de pagar")
        if "reembolso_nome" in d.edicoes:
            nome = d.edicoes["reembolso_nome"]
            reg.update(reembolso=True, reembolso_nome=nome, reembolso_para=nome,
                       reembolso_documento=d.edicoes.get("reembolso_documento", ""),
                       reembolso_origem="tela", reembolso_impedimento="")
            campos.append("reembolso")
        if "descricao" in d.edicoes:
            reg["descricao"] = reg["descricao_editada"] = d.edicoes["descricao"]
            campos.append("descrição")
        era = "; ".join(f"{k}={v}" for k, v in d.antes.items())
        notas.append(f"editado na tela por {d.quem_nome or '?'} ({d.motivo_edicao})"
                     + (f": era {era}" if era else ""))
        if d.corrigir_no_erp:
            notas.append(f"corrigir no ERP: lançamento {reg.get('id') or '?'}")
        if campos != ["descrição"]:
            reg["status"] = _status(antes, "EDITADO — " + ", ".join(c for c in campos if c != "descrição"))
    if d.liberado and liberavel:
        bloqueio = reg.get("bloqueio_liberado") or BLOQUEIO_JA_ENVIADO
        reg["status"] = _status(antes, f"LIBERADO — {bloqueio} · {d.motivo_liberacao}")
        notas.append(f"liberado na tela por {d.quem_nome or '?'} em {d.quando[:16]}")
    if reg.get("status") != antes and antes:
        notas.append(f"status antes: {antes}")
    if notas:
        reg["obs"] = " · ".join(filter(None, [*notas, reg.get("obs") or ""]))
    return reg


def registro_a_mao(p, ordem: int) -> dict:
    reg = {"tipo": p.tipo or "-", "dados": p.dados, "valor": float(p.valor),
           "descricao": p.descricao, "favorecido": p.favorecido, "pix_qr": "",
           "linha_da_guia": "", "status": f"À MÃO — {p.motivo}", "conferencia": "",
           "obs": " · ".join(filter(None, [
               f"pagamento à mão por {p.quem_nome or '?'}",
               (f"parcial: {p.valor} de {p.valor_em_aberto} em aberto"
                if p.valor_em_aberto is not None and p.valor < p.valor_em_aberto else ""),
               "" if p.lancamento_id else "sem lançamento no ERP: o Anexar não tem o que casar"])),
           "oc": p.oc, "centro_custo": p.centro_custo, "nf": p.nf, "nf_anexada": False,
           "oc_da_descricao": p.oc, "descricao_lancamento": p.descricao if p.lancamento_id else "",
           "utilidade": False, "ordem": ordem, "id": p.lancamento_id, "parcial": False,
           "reembolso": False, "valor_diverge": False, "reembolso_nome": "",
           "reembolso_documento": "", "reembolso_origem": "", "reembolso_impedimento": "",
           "reembolso_para": "", "a_mao": p.alvo}
    if not p.lancamento_id:
        reg["descricao_editada"] = p.descricao
    return reg


def resultado_da_tela(entradas, grupos, conferencia) -> relatorio.Resultado:
    decisoes = conferencia.decisoes
    liberados = {a for a, d in decisoes.items() if d.liberado}
    desmarcados = {a for a, d in decisoes.items() if d.desmarcado}
    ja_enviados = pg.ids_que_nao_saem(grupos)
    nao_aptos = ids_nao_aptos(grupos)
    r = confirmacao.remontar(entradas, (ja_enviados - liberados) | desmarcados,
                             ids_liberados=nao_aptos & liberados)
    contas = {}
    for conta, regs in r.contas.items():
        contas[conta] = [aplicar_decisao(dict(reg), decisoes.get(str(reg.get("id") or "")),
                                         liberavel=str(reg.get("id") or "") in (nao_aptos | ja_enviados))
                         for reg in regs]
    for i, p in enumerate(conferencia.a_mao):
        contas.setdefault(p.conta, []).append(registro_a_mao(p, ORDEM_A_MAO + i))
    return relatorio.Resultado(dict(sorted(contas.items())), r.omitidos)


def para_a_remessa(resultado) -> relatorio.Resultado:
    contas = {c: [r for r in regs if not r.get("a_mao")] for c, regs in resultado.contas.items()}
    return relatorio.Resultado({c: regs for c, regs in contas.items() if regs}, resultado.omitidos)


def chaves_que_saem(resultado) -> set[str]:
    return {r.get("a_mao") or str(r.get("id") or "")
            for regs in resultado.contas.values() for r in regs}


def registro_atual(resultado, ident: str) -> dict | None:
    for regs in resultado.contas.values():
        for r in regs:
            if str(r.get("id") or "") == ident:
                return r
    return next((o for o in resultado.omitidos if str(o.get("id") or "") == ident), None)
```
- [ ] **Passo 4:** `python -m pytest tests/test_tela_do_dia_geracao.py tests/test_ganchos_da_tela_do_dia.py -q`. Esperado: PASSA.
- [ ] **Passo 5: commit** — `"Pagamentos do dia: planilha, HTML e remessa com o que a tela decidiu"` + rodapé.

---

## Tarefa 6 — `pagamentos.py` e `decisoes.py`: o "a pagar" com a conferência
**Modelo sugerido:** sonnet.

**Files:** Modify `tela_do_dia/pagamentos.py` (`:39`, `:54`, `:93`), `tela_do_dia/decisoes.py:128`, `tests/test_tela_do_dia_pagamentos.py` (acrescentar), `tests/test_tela_do_dia_decisoes.py` (acrescentar)

**Interfaces:**
```python
@dataclass(frozen=True) class Pagamento: id; conta_erp; favorecido; valor: Decimal; situacao; estado; origem: str = ""; nota: str = ""
@dataclass class PagamentosDaConta: ... + desmarcados: list (não somam)
def por_conta(grupos, mapping, conferencia=None) -> tuple[dict[int, PagamentosDaConta], list[PagamentosDaConta]]
```

- [ ] **Passo 1: testes que falham** (acrescentar em `tests/test_tela_do_dia_pagamentos.py`, que já tem `mapa`, `_ln`, `_grupos`, `_JaEnviado`)
```python
from tela_do_dia import conferencia as cf


def _conf(eventos=(), a_mao=()):
    return cf.Conferencia.da_nuvem(list(eventos), list(a_mao))


def test_sem_conferencia_e_o_de_antes(mapa):
    a, _ = pg.por_conta(_grupos(), mapa)
    b, _ = pg.por_conta(_grupos(), mapa, None)
    assert {k: v.a_pagar for k, v in a.items()} == {k: v.a_pagar for k, v in b.items()}


def test_liberar_desmarcar_e_a_mao_mudam_o_a_pagar(mapa):
    conf = _conf([{"id": 1, "alvo": "A4", "acao": cf.LIBERAR, "motivo": "ok"},
                  {"id": 2, "alvo": "A1", "acao": cf.DESMARCAR},
                  {"id": 3, "alvo": "A2", "acao": cf.LIBERAR, "motivo": "reenviar"}],
                 [{"id": 7, "conta": "ALFA LTDA - BANCO", "valor": "5.00", "descricao": "taxa",
                   "motivo": "combinado"}])
    alfa = pg.por_conta(_grupos(), mapa, conf)[0][8]
    assert [p.id for p in alfa.liberados] == ["A2", "A4"]
    assert [p.id for p in alfa.desmarcados] == ["A1"] and alfa.ja_enviados == []
    assert [p.id for p in alfa.a_mao] == ["mao:7"]
    assert alfa.a_pagar == D("25.00") + D("50.00") + D("9.99") + D("5.00")   # A3 + A2 + A4 + à mão


def test_a_tela_e_os_arquivos_concordam(tmp_path):
    """O que a tela soma (fora o já enviado) é exatamente o que sai nos arquivos."""
    from datetime import date
    from pagamentos_dia import confirmacao
    from tela_do_dia import geracao as ge
    dia, conta = date(2026, 10, 22), "CONTA EXEMPLO - SICOOB"
    caminho = tmp_path / "mapping.yaml"
    caminho.write_text("model_rows:\n- row: 8\n  label: Conta Exemplo\n  uuid: u\n"
                       f"  erp_name: {conta}\n", encoding="utf-8")
    mapa = AccountMapping.load(caminho)
    lanc = lambda i: {"id": i, "tradePayableId": f"T-{i}", "paidTo": "Fornecedor Modelo Ltda",  # noqa: E731
                      "remainingValue": 100.0, "plannedDate": "2026-10-22",
                      "tradePayableAccount": {"name": conta}, "tradePayablePaymentMethod": "Pix",
                      "paidToBankAccount": "PIX EMAIL fulano@exemplo.com", "documentNumber": "1234",
                      "costCentreDetails": [{"workName": "OBRA MODELO"}], "paid": False}
    nf = {"filename": "n", "tagName": "Nota Fiscal", "extension": ".pdf", "downloadUrl": "https://exemplo.invalid/n.pdf"}
    e = confirmacao.Entradas(selecionados=[lanc("L1"), lanc("L2"), lanc("L3")],
                             anexos={"T-L1": [nf], "T-L3": [nf]}, overviews={}, textos={}, urls_ocr=set(),
                             cadastro_reembolso=None, regras_fornecedor={}, participantes={}, periodo=(dia, dia))
    grupos = confirmacao.grupos_da_confirmacao(confirmacao.remontar(e), None, e.selecionados)
    conf = _conf([{"id": 1, "alvo": "L2", "acao": cf.LIBERAR, "motivo": "ok"},
                  {"id": 2, "alvo": "L3", "acao": cf.DESMARCAR}],
                 [{"id": 4, "conta": conta, "valor": "30.00", "descricao": "parcela", "motivo": "acordo"}])
    painel, fora = pg.por_conta(grupos, mapa, conf)
    na_tela = {p.id for c in [*painel.values(), *fora] for p in c.saem}
    assert na_tela == ge.chaves_que_saem(ge.resultado_da_tela(e, grupos, conf)) == {"L1", "L2", "mao:4"}
```
Em `tests/test_tela_do_dia_decisoes.py`, acrescente um teste: conta com 1 liberado, 1 à mão e 1 desmarcado. A situação contém `"1 liberado"`, `"1 à mão"` e `"1 desmarcado (fora)"`, e conta sem nenhum deles continua com o texto de hoje.
- [ ] **Passo 2:** `python -m pytest tests/test_tela_do_dia_pagamentos.py tests/test_tela_do_dia_decisoes.py -q`. Esperado: FALHA.
- [ ] **Passo 3: implementação** (`pagamentos.py`)
  - `Pagamento`: acrescente `origem: str = ""` e `nota: str = ""` no fim.
  - `PagamentosDaConta`: acrescente `desmarcados: list = field(default_factory=list)` (fora de `saem`/`debitam`). Troque o texto "Ponto de extensão da entrega 2" da docstring do módulo pelo que passou a valer.
  - `por_conta`:
```python
def por_conta(grupos, mapping, conferencia=None):
    """... `conferencia` (`tela_do_dia.conferencia.Conferencia`) põe na conta o
    que o dono liberou, desmarcou e pagou à mão; `None` = entrega 1."""
    painel: dict[int, PagamentosDaConta] = {}
    fora: dict[str, PagamentosDaConta] = {}
    decisoes = conferencia.decisoes if conferencia is not None else {}

    def _destino(conta: str) -> PagamentosDaConta:
        if mapping.is_ignored(conta):
            return fora.setdefault(conta, PagamentosDaConta(conta, None, motivo_fora=FORA_POR_CONFIGURACAO))
        row = mapping.resolve_label(conta)
        if row is None:
            return fora.setdefault(conta, PagamentosDaConta(conta, None, motivo_fora=SEM_LINHA))
        if not row.exists_in_erp:
            return fora.setdefault(conta, PagamentosDaConta(conta, None, motivo_fora=LINHA_FORA_DO_ERP))
        return painel.setdefault(row.row, PagamentosDaConta(row.label, row.row))

    def _pag(ln, d, origem=""):
        p = Pagamento.da_linha(ln)
        if d is not None and d.editado:
            origem = origem or "editado"
            p = replace(p, nota="editado: " + ", ".join(sorted(d.edicoes)))
        if origem == "liberado":
            p = replace(p, situacao=f"liberado · {d.motivo_liberacao} (era: {ln.situacao})")
        return replace(p, origem=origem)

    for g in grupos:
        destino = _destino(g.conta)
        for ln in g.entram:
            d = decisoes.get(ln.id)
            if confirmacao.marcada_de_inicio(ln):
                if d is not None and d.desmarcado:
                    destino.desmarcados.append(_pag(ln, d))
                else:
                    destino.vao_sair.append(_pag(ln, d))
            elif _ja_enviado(ln):
                if d is not None and d.liberado:
                    destino.liberados.append(_pag(ln, d, "liberado"))
                else:
                    destino.ja_enviados.append(_pag(ln, d))
            else:
                destino.bloqueados.append(_pag(ln, d))
        for ln in g.nao_aptos:
            d = decisoes.get(ln.id)
            if d is not None and d.liberado:
                destino.liberados.append(_pag(ln, d, "liberado"))
            else:
                destino.bloqueados.append(Pagamento.da_linha(ln))
    for m in (conferencia.a_mao if conferencia is not None else ()):
        _destino(m.conta).a_mao.append(Pagamento(
            id=m.alvo, conta_erp=m.conta, favorecido=m.favorecido or "(à mão)", valor=m.valor,
            situacao=f"à mão · {m.motivo}", estado="atencao", origem="a_mao"))
    for c in [*painel.values(), *fora.values()]:
        c.liberados.sort(key=lambda p: p.id)
    return painel, list(fora.values())
```
  - Acrescente `replace` ao `from dataclasses import ...`.
  - `decisoes.celulas_da_conta` (`:128`): antes do `return`, acrescente as partes:
```python
    if conta.liberados:
        partes.append(f"{len(conta.liberados)} liberado(s)")
    if conta.a_mao:
        partes.append(f"{len(conta.a_mao)} à mão")
    if conta.desmarcados:
        partes.append(f"{len(conta.desmarcados)} desmarcado(s) (fora)")
```
  Use `getattr(conta, "desmarcados", ())`, para os testes antigos com objetos simples continuarem valendo.
- [ ] **Passo 4:** `python -m pytest tests/test_tela_do_dia_pagamentos.py tests/test_tela_do_dia_decisoes.py tests/test_tela_do_dia_aportes.py tests/test_tela_do_dia_excel.py -q`. Esperado: PASSA.
- [ ] **Passo 5: commit** — `"Pagamentos do dia: o a pagar com liberados, à mão e desmarcados"` + rodapé.

---

## Tarefa 7 — `lancamento_do_erp.py`: o link do lançamento (só leitura)
**Modelo sugerido:** sonnet. **Faça antes da Tarefa 4** (ela importa `LancamentoLido`).

**Files:** Create `tela_do_dia/lancamento_do_erp.py`, `tests/test_tela_do_dia_lancamento_erp.py`

**Interfaces:**
```python
def id_do_link(texto: str) -> str
@dataclass(frozen=True) class LancamentoLido: id; conta=""; favorecido=""; centro_custo=""; nf=""; oc=""; descricao="";
    em_aberto: Decimal | None = None; vencimento: date | None = None; pago: bool = False; avisos: tuple = ()
def do_item(item: dict, overview: dict | None, *, avisos=()) -> LancamentoLido
def ler(api, ident: str, conhecidos=(), *, log=print) -> LancamentoLido   # LookupError se não achar
```

- [ ] **Passo 1: teste que falha**
```python
"""O link do lançamento: id, e a leitura pela sessão do Chrome do app (dublê)."""
from datetime import date
from decimal import Decimal as D

import pytest

from tela_do_dia import lancamento_do_erp as le

ITEM = {"id": "L9", "tradePayableId": "T9", "paidTo": "Fornecedor Modelo Ltda", "remainingValue": 80000.0,
        "plannedDate": "2026-09-29", "tradePayableAccount": {"name": "CONTA EXEMPLO - SICOOB"},
        "documentNumber": "1234", "description": "compra de material",
        "costCentreDetails": [{"workName": "OBRA MODELO"}], "paid": False}


def test_id_do_link_aceita_o_link_e_o_id_cru():
    assert le.id_do_link("https://acessar.maiscontroleerp.com.br/#/payable-installments/abc-123") == "abc-123"
    assert le.id_do_link("  abc-123 ") == "abc-123"
    assert le.id_do_link("https://outro.invalid/x?y=1") == ""


def test_do_item_le_as_pecas_do_lancamento():
    lido = le.do_item(ITEM, {"purchaseOrder": {"number": "55"}})
    assert (lido.favorecido, lido.centro_custo, lido.nf, lido.oc) == ("Fornecedor Modelo Ltda", "OBRA MODELO", "1234", "55")
    assert lido.em_aberto == D("80000.00") and lido.vencimento == date(2026, 9, 29)
    assert lido.conta == "CONTA EXEMPLO - SICOOB" and not lido.pago


class _Api:
    _req_pagos = ("u", {})

    def __init__(self, overview=None, lista=()):
        self.overview, self.lista, self.pedidos = overview, list(lista), []

    def listar_overviews(self, ids, log=print):
        return {ids[0]: self.overview} if self.overview else {}

    def listar_a_pagar(self, ini, fim, log=print):
        self.pedidos.append((ini, fim))
        return self.lista


def test_le_fora_do_periodo_pela_data_do_detalhe():
    api = _Api(overview={"plannedDate": "2026-09-29", "documentNumber": "1234"}, lista=[ITEM])
    lido = le.ler(api, "L9", conhecidos=[])
    assert api.pedidos == [("2026-09-29", "2026-09-29")] and lido.em_aberto == D("80000.00")


def test_sem_o_item_avisa_e_nao_inventa_valor():
    lido = le.ler(_Api(overview={"documentNumber": "1234"}), "L9")
    assert lido.em_aberto is None and any("confira" in a for a in lido.avisos)


def test_lancamento_que_nao_existe_levanta():
    with pytest.raises(LookupError):
        le.ler(_Api(), "L9")
```
- [ ] **Passo 2:** `python -m pytest tests/test_tela_do_dia_lancamento_erp.py -q`. Esperado: FALHA.
- [ ] **Passo 3: implementação**
```python
"""O lançamento do ERP pelo link — só leitura, pela sessão do Chrome do app.

Ordem: (1) os lançamentos que a leitura do dia já trouxe; (2) o detalhe
(`listar_overviews`) e, com a data dele, a lista daquele dia
(`listar_a_pagar(d, d)`), que traz fornecedor, centro de custo e o em aberto;
(3) só o detalhe, com aviso — o campo que não veio fica vazio para o dono
digitar, nunca chutado. Nada aqui escreve no ERP.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pagamentos_dia import relatorio

from .valores import de_float

_NO_LINK = re.compile(r"payable-installments/([A-Za-z0-9-]{1,64})")
_CRU = re.compile(r"[A-Za-z0-9-]{1,64}")


def id_do_link(texto: str) -> str:
    t = (texto or "").strip()
    m = _NO_LINK.search(t)
    if m:
        return m.group(1)
    return t if _CRU.fullmatch(t) else ""


@dataclass(frozen=True)
class LancamentoLido:
    id: str
    conta: str = ""
    favorecido: str = ""
    centro_custo: str = ""
    nf: str = ""
    oc: str = ""
    descricao: str = ""
    em_aberto: Decimal | None = None
    vencimento: date | None = None
    pago: bool = False
    avisos: tuple = ()


def do_item(item: dict, overview: dict | None, *, avisos=()) -> LancamentoLido:
    return LancamentoLido(
        id=str(item.get("id") or ""), conta=relatorio.nome_da_conta(item) if item.get("tradePayableAccount") else "",
        favorecido=(item.get("paidTo") or "").strip(), centro_custo=relatorio.centro_de_custo(item),
        nf=relatorio.achar_doc(item, [], overview), oc=relatorio.achar_oc(item, [], "", overview),
        descricao=(item.get("description") or "").strip(),
        em_aberto=de_float(item["remainingValue"]) if "remainingValue" in item else None,
        vencimento=relatorio.data_do_item(item), pago=bool(item.get("paid")), avisos=tuple(avisos))


def ler(api, ident: str, conhecidos=(), *, log=print) -> LancamentoLido:
    if not getattr(api, "_req_pagos", None) and not api.capturar_credenciais(log):
        raise RuntimeError("A tela de Pagamentos não carregou no Chrome do app.")
    overview = (api.listar_overviews([ident], log=log) or {}).get(ident)
    item = next((i for i in conhecidos or () if str(i.get("id")) == ident), None)
    if item is not None:
        return do_item(item, overview)
    if overview is None:
        raise LookupError(f"não achei o lançamento {ident} no ERP")
    venc = relatorio.para_data(overview.get("plannedDate") or overview.get("dueDate"))
    if venc is not None:
        dia = f"{venc:%Y-%m-%d}"
        item = next((i for i in api.listar_a_pagar(dia, dia, log=log) or ()
                     if str(i.get("id")) == ident), None)
        if item is not None:
            return do_item(item, overview)
    return do_item({**overview, "id": ident}, overview,
                   avisos=("li só o detalhe do lançamento — confira fornecedor, conta e valor em aberto",))
```
> O `do_item` sobre o `overview` só usa campos que existirem. `remainingValue` ausente vira `em_aberto=None`, e aí `nova_a_mao` não limita o valor; a tela mostra o aviso. O formato completo do `overview` não foi medido (ver Riscos).
- [ ] **Passo 4:** `python -m pytest tests/test_tela_do_dia_lancamento_erp.py -q`. Esperado: PASSA.
- [ ] **Passo 5: commit** — `"Pagamentos do dia: ler o lançamento do ERP pelo link (só leitura)"` + rodapé.

---

## Tarefa 8 — `agendados.py`: marcar, responder e o que se prova
**Modelo sugerido:** opus.

**Files:** Create `tela_do_dia/agendados.py`, `tests/test_tela_do_dia_agendados.py`

**Interfaces:**
```python
FINAIS = ("pago", "nao_saiu"); FOLGA_DIAS = 31
PROVA_BAIXA, PROVA_BAIXA_PARCIAL, PROVA_RETORNO = "baixa no ERP", "baixa parcial no ERP", "retorno do banco"
@dataclass(frozen=True) class Agendado: id; dia: date; conta; alvo; lancamento_id; favorecido; valor: Decimal;
    descricao=""; tipo=""; foto: dict; quem_nome=""   ; de_linha(linha) (classmethod)
@dataclass(frozen=True) class Resposta: id; agendado_id; resposta; motivo=""; nova_data: date|None=None; prova=""; quem_nome=""; quando=""
@dataclass(frozen=True) class Situacao: tag: str; frase: str; pre_marca: bool = False; prova: str = ""
def ultima_resposta(respostas) -> dict[int, Resposta]
def pendentes(agendados, respostas) -> list[Agendado]
def situacao(ag, titulo: dict | None, envio=None, *, relido=True, prova_extra="") -> Situacao
def intervalo_de_releitura(pendentes, hoje: date) -> tuple[date, date] | None
@dataclass class ParaMarcar: alvo; conta; rotulo; lancamento_id; a_mao_id; favorecido; valor; descricao; tipo; foto; marcado=True; ja_marcado=False
def foto_do_lancamento(item: dict, valor: Decimal) -> dict
def para_marcar(painel, fora, lancamentos, conferencia, ja_marcados: set[str]) -> list[ParaMarcar]
def linhas_para_nuvem(itens) -> list[dict]
def validar_resposta(resposta: str, motivo: str, nova_data: date | None, hoje: date) -> str
```

- [ ] **Passo 1: teste que falha**
```python
"""Agendados: nada some sem resposta, e sumiu/mudou nunca se resolve sozinho."""
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

from tela_do_dia import agendados as ag

HOJE = date(2026, 10, 23)


def _ag(i=1, valor="100.00", em_aberto="100.00", lanc="L1"):
    return ag.Agendado.de_linha({"id": i, "dia": "2026-10-22", "conta": "C", "alvo": lanc or f"mao:{i}",
                                 "lancamento_id": lanc, "favorecido": "Fornecedor Modelo Ltda",
                                 "valor": valor, "foto": {"em_aberto": em_aberto, "vencimento": "2026-10-22"}})


def _r(i, agendado, resposta, **k):
    return ag.Resposta(id=i, agendado_id=agendado, resposta=resposta, **k)


def test_so_resposta_final_tira_da_lista_e_a_ultima_vale():
    a1, a2, a3 = _ag(1), _ag(2), _ag(3)
    resp = [_r(1, 1, "pago"), _r(2, 2, "reagendado", nova_data=HOJE), _r(3, 3, "pago"), _r(4, 3, "reagendado", nova_data=HOJE)]
    assert [a.id for a in ag.pendentes([a1, a2, a3], resp)] == [2, 3]


def test_pago_no_erp_pre_marca_com_prova():
    s = ag.situacao(_ag(), {"id": "L1", "paid": True, "remainingValue": 0.0})
    assert s.pre_marca and s.prova == ag.PROVA_BAIXA


def test_titulo_sumiu_nunca_se_resolve_mesmo_com_retorno_ok():
    s = ag.situacao(_ag(), None, SimpleNamespace(retorno_estado="ok"))
    assert not s.pre_marca and s.tag == "erro" and "título sumiu do ERP — era R$ 100,00" in s.frase


def test_valor_mudou_espera_o_dono():
    s = ag.situacao(_ag(), {"id": "L1", "paid": False, "remainingValue": 120.0})
    assert not s.pre_marca and "era R$ 100,00, agora R$ 120,00" in s.frase


def test_baixa_parcial_ao_centavo_e_prova():
    s = ag.situacao(_ag(valor="30000.00", em_aberto="80000.00"), {"id": "L1", "paid": False, "remainingValue": 50000.0})
    assert s.pre_marca and s.prova == ag.PROVA_BAIXA_PARCIAL


def test_retorno_ok_com_titulo_igual_e_prova_e_sem_releitura_nao_ha():
    titulo = {"id": "L1", "paid": False, "remainingValue": 100.0}
    assert ag.situacao(_ag(), titulo, SimpleNamespace(retorno_estado="ok")).prova == ag.PROVA_RETORNO
    assert not ag.situacao(_ag(), titulo, SimpleNamespace(retorno_estado="ok"), relido=False).pre_marca


def test_a_mao_sem_lancamento_pede_resposta():
    s = ag.situacao(_ag(lanc=""), None)
    assert not s.pre_marca and "sem lançamento" in s.frase


def test_intervalo_cobre_o_vencimento_mais_antigo():
    assert ag.intervalo_de_releitura([_ag()], HOJE) == (date(2026, 9, 21), date(2026, 11, 23))
    assert ag.intervalo_de_releitura([_ag(lanc="")], HOJE) is None


def test_para_marcar_nasce_marcado_e_pula_o_ja_marcado():
    p1 = SimpleNamespace(id="L1", conta_erp="C", favorecido="F", valor=D("10.00"))
    p2 = SimpleNamespace(id="L2", conta_erp="C", favorecido="F", valor=D("20.00"))
    conta = SimpleNamespace(rotulo="Conta Alfa - Banco", linha=8, saem=[p1, p2])
    lancs = [{"id": "L1", "remainingValue": 10.0, "plannedDate": "2026-10-22", "paidTo": "F",
              "tradePayableId": "T1", "tradePayablePaymentMethod": "Pix", "description": "compra"}]
    itens = ag.para_marcar({8: conta}, [], lancs, None, {"L2"})
    assert [(i.alvo, i.marcado, i.ja_marcado) for i in itens] == [("L1", True, False), ("L2", False, True)]
    assert itens[0].foto["em_aberto"] == "10.00" and itens[0].foto["vencimento"] == "2026-10-22"
    linhas = ag.linhas_para_nuvem(itens)
    assert [l["alvo"] for l in linhas] == ["L1"] and linhas[0]["valor"] == "10.00"


def test_resposta_nao_saiu_exige_motivo_e_reagendado_exige_data():
    assert ag.validar_resposta("pago", "", None, HOJE) == ""
    assert "motivo" in ag.validar_resposta("nao_saiu", "", None, HOJE)
    assert "data" in ag.validar_resposta("reagendado", "", None, HOJE)
    assert "data" in ag.validar_resposta("reagendado", "", date(2026, 10, 1), HOJE)
```
- [ ] **Passo 2:** `python -m pytest tests/test_tela_do_dia_agendados.py -q`. Esperado: FALHA.
- [ ] **Passo 3: implementação**
```python
"""Passo 6 ("Marcar agendados") e "Agendados a confirmar" — sem tela.

Regra do dono/CTO: tudo que foi marcado como agendado fica até o dono
responder (pago, não saiu, reagendado). O app PRÉ-MARCA só o que prova —
baixa no ERP, baixa parcial batendo ao centavo, retorno do banco "ok" — e
título que SUMIU do ERP ou MUDOU de valor nunca se resolve sozinho: mostra a
foto de quando foi agendado ("era R$ X, agora R$ Y") e espera.
A prova "comprovante baixado" chega pela entrega 5 (`prova_extra`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from pagamentos_dia import relatorio

from .valores import CENTAVO, brl, de_float

FINAIS = ("pago", "nao_saiu")
RESPOSTAS = ("pago", "nao_saiu", "reagendado")
FOLGA_DIAS = 31
PROVA_BAIXA, PROVA_BAIXA_PARCIAL, PROVA_RETORNO = (
    "baixa no ERP", "baixa parcial no ERP", "retorno do banco")


def _dinheiro(v) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v)).quantize(CENTAVO)
    except InvalidOperation:
        return None


def _data(v) -> date | None:
    return relatorio.para_data(v) if v else None


@dataclass(frozen=True)
class Agendado:
    id: int
    dia: date
    conta: str
    alvo: str
    lancamento_id: str
    favorecido: str
    valor: Decimal
    descricao: str = ""
    tipo: str = ""
    foto: dict = field(default_factory=dict)
    quem_nome: str = ""

    @classmethod
    def de_linha(cls, linha: dict) -> "Agendado":
        return cls(id=int(linha["id"]), dia=_data(linha["dia"]), conta=str(linha.get("conta") or ""),
                   alvo=str(linha.get("alvo") or ""), lancamento_id=str(linha.get("lancamento_id") or ""),
                   favorecido=str(linha.get("favorecido") or ""), valor=_dinheiro(linha["valor"]),
                   descricao=str(linha.get("descricao") or ""), tipo=str(linha.get("tipo") or ""),
                   foto=dict(linha.get("foto") or {}), quem_nome=str(linha.get("quem_nome") or ""))


@dataclass(frozen=True)
class Resposta:
    id: int
    agendado_id: int
    resposta: str
    motivo: str = ""
    nova_data: date | None = None
    prova: str = ""
    quem_nome: str = ""
    quando: str = ""

    @classmethod
    def de_linha(cls, linha: dict) -> "Resposta":
        return cls(id=int(linha["id"]), agendado_id=int(linha["agendado_id"]),
                   resposta=str(linha["resposta"]), motivo=str(linha.get("motivo") or ""),
                   nova_data=_data(linha.get("nova_data")), prova=str(linha.get("prova") or ""),
                   quem_nome=str(linha.get("quem_nome") or ""), quando=str(linha.get("quando") or ""))


@dataclass(frozen=True)
class Situacao:
    tag: str
    frase: str
    pre_marca: bool = False
    prova: str = ""


def ultima_resposta(respostas) -> dict[int, Resposta]:
    ult = {}
    for r in sorted(respostas, key=lambda r: r.id):
        ult[r.agendado_id] = r
    return ult


def pendentes(agendados, respostas) -> list[Agendado]:
    ult = ultima_resposta(respostas)
    return [a for a in sorted(agendados, key=lambda a: (a.dia, a.id))
            if a.id not in ult or ult[a.id].resposta not in FINAIS]


def situacao(ag, titulo, envio=None, *, relido=True, prova_extra="") -> Situacao:
    pago_no_banco = getattr(envio, "retorno_estado", "") == "ok"
    if not ag.lancamento_id:
        if prova_extra:
            return Situacao("ok", prova_extra, True, prova_extra)
        return Situacao("atencao", "pagamento à mão sem lançamento no ERP — responda")
    if not relido:
        return Situacao("atencao", "não reli o título no ERP — responda")
    if titulo is None:
        extra = " · o retorno do banco diz pago" if pago_no_banco else ""
        return Situacao("erro", f"título sumiu do ERP — era {brl(ag.valor)}, "
                                f"favorecido {ag.favorecido or '?'}{extra}")
    if titulo.get("paid"):
        return Situacao("ok", "pago no ERP (baixa)", True, PROVA_BAIXA)
    agora = de_float(titulo.get("remainingValue"))
    antes = _dinheiro(ag.foto.get("em_aberto"))
    if antes is not None and ag.valor < antes and agora == antes - ag.valor:
        return Situacao("ok", f"baixa parcial no ERP ({brl(antes)} → {brl(agora)})", True,
                        PROVA_BAIXA_PARCIAL)
    if antes is not None and agora != antes:
        return Situacao("erro", f"valor mudou no ERP — era {brl(antes)}, agora {brl(agora)}")
    if pago_no_banco:
        return Situacao("ok", "o retorno do banco diz pago", True, PROVA_RETORNO)
    if prova_extra:
        return Situacao("ok", prova_extra, True, prova_extra)
    return Situacao("", "aguardando — responda")


def intervalo_de_releitura(pend, hoje) -> tuple[date, date] | None:
    datas = [_data(a.foto.get("vencimento")) or a.dia for a in pend if a.lancamento_id]
    if not datas:
        return None
    folga = timedelta(days=FOLGA_DIAS)
    return min(datas) - folga, hoje + folga


@dataclass
class ParaMarcar:
    alvo: str
    conta: str
    rotulo: str
    lancamento_id: str
    a_mao_id: int | None
    favorecido: str
    valor: Decimal
    descricao: str
    tipo: str
    foto: dict
    marcado: bool = True
    ja_marcado: bool = False


def foto_do_lancamento(item: dict, valor: Decimal) -> dict:
    venc = relatorio.data_do_item(item) if item else None
    em_aberto = de_float(item["remainingValue"]) if "remainingValue" in (item or {}) else valor
    return {"em_aberto": str(em_aberto), "vencimento": venc.isoformat() if venc else "",
            "favorecido": str((item or {}).get("paidTo") or ""),
            "titulo": str((item or {}).get("tradePayableId") or "")}


def para_marcar(painel, fora, lancamentos, conferencia, ja_marcados) -> list[ParaMarcar]:
    por_id = {str(i.get("id")): i for i in lancamentos or () if i.get("id")}
    a_mao = {p.alvo: p for p in conferencia.a_mao} if conferencia is not None else {}
    saida = []
    for c in [*sorted(painel.values(), key=lambda c: c.linha), *fora]:
        for p in c.saem:
            m = a_mao.get(p.id)
            if m is not None:
                item = ParaMarcar(p.id, m.conta, c.rotulo, m.lancamento_id, m.id, p.favorecido,
                                  p.valor, m.descricao, m.tipo,
                                  {"a_mao": True, "vencimento": "",
                                   "em_aberto": "" if m.valor_em_aberto is None else str(m.valor_em_aberto)})
            else:
                lanc = por_id.get(p.id) or {}
                item = ParaMarcar(p.id, p.conta_erp, c.rotulo, p.id, None, p.favorecido, p.valor,
                                  str(lanc.get("description") or "")[:200],
                                  str(lanc.get("tradePayablePaymentMethod") or ""),
                                  foto_do_lancamento(lanc, p.valor))
            item.ja_marcado = p.id in ja_marcados
            item.marcado = not item.ja_marcado
            saida.append(item)
    return saida


def linhas_para_nuvem(itens) -> list[dict]:
    return [{"conta": i.conta, "alvo": i.alvo, "lancamento_id": i.lancamento_id,
             "a_mao_id": i.a_mao_id, "favorecido": i.favorecido, "valor": str(i.valor),
             "descricao": i.descricao, "tipo": i.tipo, "foto": i.foto}
            for i in itens if i.marcado and not i.ja_marcado]


def validar_resposta(resposta, motivo, nova_data, hoje) -> str:
    if resposta not in RESPOSTAS:
        return f"Resposta desconhecida: {resposta}."
    if resposta == "nao_saiu" and len((motivo or "").strip()) < 3:
        return "Diga o motivo de não ter saído (3 letras ou mais)."
    if resposta == "reagendado" and (nova_data is None or nova_data < hoje):
        return "Diga a nova data (hoje ou depois)."
    return ""
```
> `CENTAVO` já existe em `tela_do_dia/valores.py` (linha 17).
- [ ] **Passo 4:** `python -m pytest tests/test_tela_do_dia_agendados.py -q`. Esperado: PASSA.
- [ ] **Passo 5: commit** — `"Pagamentos do dia: agendados — marcar, provar e esperar a resposta"` + rodapé.

---

## Tarefa 9 — `lista_diretor.py`: a lista curta para o WhatsApp
**Modelo sugerido:** haiku.

**Files:** Create `tela_do_dia/lista_diretor.py`, `tests/test_tela_do_dia_lista_diretor.py`

**Interfaces:**
```python
@dataclass class LinhaDaLista: rotulo; nome; valor: Decimal; ordinal: int | None = None
def montar(agendados_hoje, rotulo_de, nomes: dict[str, str]) -> list[LinhaDaLista]
def sugerir_ordem(linhas, anterior: list[dict]) -> list[LinhaDaLista]
def renumerar(linhas) -> list[LinhaDaLista]
def mover(linhas, i: int, delta: int) -> list[LinhaDaLista]
def alternar_ordinal(linhas, i: int) -> list[LinhaDaLista]
def texto_whatsapp(linhas) -> str
def para_nuvem(linhas) -> list[dict]
def validar_nome_curto(nome: str) -> str
```

- [ ] **Passo 1: teste que falha**
```python
"""A lista do diretor: só o agendado, nome curto, ordinais e a ordem de ontem."""
from decimal import Decimal as D
from types import SimpleNamespace

from tela_do_dia import lista_diretor as ld
from tela_do_dia.valores import brl


def _ag(conta, valor):
    return SimpleNamespace(conta=conta, valor=D(valor))


def test_soma_por_conta_com_nome_curto():
    linhas = ld.montar([_ag("ERP A", "10.00"), _ag("ERP A", "5.00"), _ag("ERP B", "7.00")],
                       {"ERP A": "Conta Alfa - Banco", "ERP B": "Conta Beta - Banco"}.get,
                       {"Conta Alfa - Banco": "Alfa - Banco"})
    assert [(l.nome, l.valor) for l in linhas] == [("Alfa - Banco", D("15.00")), ("Conta Beta - Banco", D("7.00"))]


def test_ordem_de_ontem_sugere_ordinais_e_demais():
    linhas = [ld.LinhaDaLista(r, r, D(v)) for r, v in (("A", "1"), ("B", "9"), ("C", "5"), ("D", "3"))]
    anterior = [{"conta": "C", "ordinal": 1}, {"conta": "A", "ordinal": 2}, {"conta": "D", "ordinal": None}]
    sug = ld.sugerir_ordem(linhas, anterior)
    assert [(l.rotulo, l.ordinal) for l in sug] == [("C", 1), ("A", 2), ("D", None), ("B", None)]


def test_texto_do_whatsapp():
    linhas = [ld.LinhaDaLista("A", "Alfa - Banco", D("30500"), 1),
              ld.LinhaDaLista("B", "Beta - Banco", D("3760.36"), 2),
              ld.LinhaDaLista("C", "Gama - Banco", D("5028.84"))]
    assert ld.texto_whatsapp(linhas) == (f"1º Alfa - Banco — {brl(D('30500'))}\n"
                                         f"2º Beta - Banco — {brl(D('3760.36'))}\n"
                                         f"Demais:\nGama - Banco — {brl(D('5028.84'))}")
    assert ld.texto_whatsapp(linhas[2:]) == f"Gama - Banco — {brl(D('5028.84'))}"


def test_mover_e_alternar_renumeram():
    linhas = [ld.LinhaDaLista("A", "A", D("1"), 1), ld.LinhaDaLista("B", "B", D("1"), 2),
              ld.LinhaDaLista("C", "C", D("1"))]
    linhas = ld.mover(linhas, 1, -1)
    assert [(l.rotulo, l.ordinal) for l in linhas] == [("B", 1), ("A", 2), ("C", None)]
    linhas = ld.alternar_ordinal(linhas, 2)
    assert [(l.rotulo, l.ordinal) for l in linhas] == [("B", 1), ("A", 2), ("C", 3)]
    assert ld.para_nuvem(linhas)[0] == {"conta": "B", "ordinal": 1}
    assert ld.validar_nome_curto("") and ld.validar_nome_curto("x" * 61) and not ld.validar_nome_curto("Alfa")
```
- [ ] **Passo 2:** `python -m pytest tests/test_tela_do_dia_lista_diretor.py -q`. Esperado: FALHA.
- [ ] **Passo 3: implementação**
```python
"""Passo 7: a lista do diretor — só o que foi AGENDADO hoje, uma linha por
conta, nome curto definido uma vez (nuvem), ordinais marcados na hora com a
ordem de ontem como sugestão, texto pronto para o WhatsApp. ("Arrastar" é
↑/↓ na tela: Treeview não arrasta sem código de tela que não se testa.)"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .valores import brl

ZERO = Decimal("0.00")
NOME_MAXIMO = 60


@dataclass
class LinhaDaLista:
    rotulo: str
    nome: str
    valor: Decimal
    ordinal: int | None = None


def montar(agendados_hoje, rotulo_de, nomes) -> list[LinhaDaLista]:
    soma: dict[str, Decimal] = {}
    for a in agendados_hoje:
        r = rotulo_de(a.conta) or a.conta
        soma[r] = soma.get(r, ZERO) + a.valor
    return [LinhaDaLista(r, nomes.get(r) or r, v) for r, v in soma.items()]


def renumerar(linhas) -> list[LinhaDaLista]:
    com = [l for l in linhas if l.ordinal is not None]
    sem = [l for l in linhas if l.ordinal is None]
    for i, l in enumerate(com, 1):
        l.ordinal = i
    return com + sem


def sugerir_ordem(linhas, anterior) -> list[LinhaDaLista]:
    pos = {str(x.get("conta")): (i, x.get("ordinal")) for i, x in enumerate(anterior or ())}
    com = sorted((l for l in linhas if pos.get(l.rotulo, (0, None))[1]),
                 key=lambda l: pos[l.rotulo][1])
    marcados = {id(l) for l in com}
    sem = sorted((l for l in linhas if id(l) not in marcados),
                 key=lambda l: (pos.get(l.rotulo, (10 ** 6, None))[0], -l.valor, l.rotulo))
    for l in com:
        l.ordinal = 0
    for l in sem:
        l.ordinal = None
    return renumerar(com + sem)


def mover(linhas, i, delta) -> list[LinhaDaLista]:
    linhas, j = list(linhas), i + delta
    if 0 <= i < len(linhas) and 0 <= j < len(linhas):
        linhas[i], linhas[j] = linhas[j], linhas[i]
    return renumerar(linhas)


def alternar_ordinal(linhas, i) -> list[LinhaDaLista]:
    linhas = list(linhas)
    linhas[i].ordinal = None if linhas[i].ordinal is not None else 10 ** 6
    return renumerar(linhas)


def texto_whatsapp(linhas) -> str:
    com = [l for l in linhas if l.ordinal]
    sem = [l for l in linhas if not l.ordinal]
    saida = [f"{l.ordinal}º {l.nome} — {brl(l.valor)}" for l in com]
    if com and sem:
        saida.append("Demais:")
    saida += [f"{l.nome} — {brl(l.valor)}" for l in sem]
    return "\n".join(saida)


def para_nuvem(linhas) -> list[dict]:
    return [{"conta": l.rotulo, "ordinal": l.ordinal} for l in linhas]


def validar_nome_curto(nome: str) -> str:
    n = (nome or "").strip()
    if not 1 <= len(n) <= NOME_MAXIMO or "\n" in n:
        return f"O nome curto tem de ter de 1 a {NOME_MAXIMO} caracteres, numa linha."
    return ""
```
> No `alternar_ordinal`, a linha que ganha ordinal recebe `10**6` para ficar no fim dos numerados, e o `renumerar` mantém a ordem da lista. **Ajuste o teste ao que o código faz** (C vira 3), como está acima.
- [ ] **Passo 4:** `python -m pytest tests/test_tela_do_dia_lista_diretor.py -q`. Esperado: PASSA.
- [ ] **Passo 5: commit** — `"Pagamentos do dia: lista do diretor para o WhatsApp"` + rodapé.

---

## Tarefa 10 — `nuvem_do_dia.py`: a leitura da nuvem, do ERP e do retorno
**Modelo sugerido:** sonnet.

**Files:** Create `tela_do_dia/nuvem_do_dia.py`, `tests/test_nuvem_do_dia.py`

**Interfaces:**
```python
@dataclass class LidoDaNuvem: conferencia: Conferencia; agendados_hoje: list; pendentes: list  # [(Agendado, Situacao, Resposta|None)]
    nomes_curtos: dict; lista_anterior: list; erro: str = ""; avisos: list
def ler(nuvem, dia: date, hoje: date, *, api=None, registro=None, log=print) -> LidoDaNuvem
```

- [ ] **Passo 1: teste que falha**
```python
"""A leitura da nuvem do dia: falha da nuvem trava tudo; ERP/registro mudos só tiram provas."""
from datetime import date
from types import SimpleNamespace

from tela_do_dia import nuvem_do_dia as nd

DIA = HOJE = date(2026, 10, 23)
ABERTO = {"id": 1, "dia": "2026-10-22", "conta": "C", "alvo": "L1", "lancamento_id": "L1",
          "favorecido": "F", "valor": "100.00", "foto": {"em_aberto": "100.00", "vencimento": "2026-10-22"}}


class _Nuvem:
    def __init__(self, falhar=False):
        self.falhar = falhar

    def decisoes_do_dia(self, dia):
        if self.falhar:
            raise RuntimeError("HTTP 500")
        return [{"id": 1, "alvo": "L5", "acao": "liberar", "motivo": "ok"}]

    def pagamentos_a_mao(self, dia): return []
    def agendados_do_dia(self, dia): return []
    def agendados_em_aberto(self): return [ABERTO]
    def respostas(self, ids): return []
    def nomes_curtos(self): return {"Conta Alfa - Banco": "Alfa"}
    def lista_anterior(self, dia): return [{"conta": "Conta Alfa - Banco", "ordinal": 1}]


class _Api:
    def __init__(self, itens=None, falhar=False):
        self.itens, self.falhar = itens or [], falhar

    def listar_a_pagar(self, ini, fim, log=print):
        if self.falhar:
            raise RuntimeError("sessão caiu")
        return self.itens


def test_nuvem_muda_trava_tudo():
    lido = nd.ler(_Nuvem(falhar=True), DIA, HOJE)
    assert lido.erro and not lido.conferencia.decisoes and lido.pendentes == []
    assert nd.ler(None, DIA, HOJE).erro


def test_le_tudo_e_pre_marca_o_pago_no_erp():
    lido = nd.ler(_Nuvem(), DIA, HOJE, api=_Api([{"id": "L1", "paid": True}]))
    assert lido.erro == "" and "L5" in lido.conferencia.decisoes
    (_a, sit, resp), = lido.pendentes
    assert sit.pre_marca and resp is None and lido.nomes_curtos == {"Conta Alfa - Banco": "Alfa"}


def test_erp_mudo_nao_pre_marca_nada_e_avisa():
    lido = nd.ler(_Nuvem(), DIA, HOJE, api=_Api(falhar=True))
    assert not lido.pendentes[0][1].pre_marca and lido.avisos


def test_retorno_ok_vira_prova_quando_o_titulo_nao_mudou():
    registro = SimpleNamespace(envios_em_lote=lambda ids, refs: ({}, {"L1": (SimpleNamespace(retorno_estado="ok"), None)}))
    lido = nd.ler(_Nuvem(), DIA, HOJE, api=_Api([{"id": "L1", "paid": False, "remainingValue": 100.0}]),
                  registro=registro)
    assert lido.pendentes[0][1].prova == "retorno do banco"
```
- [ ] **Passo 2:** `python -m pytest tests/test_nuvem_do_dia.py -q`. Esperado: FALHA.
- [ ] **Passo 3: implementação**
```python
"""O que a aba lê da nuvem a cada Buscar — sem tela, com dublês no teste.

Nuvem que não responde (sem sessão, rede, tabela não aplicada) devolve
`erro` e uma conferência VAZIA: a tela volta a ser a da entrega 1 e trava
liberar/editar/à mão/agendar (falha fechada). ERP ou registro de remessas
mudos só tiram PROVAS: os agendados aparecem, nenhum pré-marcado por eles.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import agendados as ag
from .conferencia import Conferencia


@dataclass
class LidoDaNuvem:
    conferencia: Conferencia
    agendados_hoje: list = field(default_factory=list)
    pendentes: list = field(default_factory=list)
    nomes_curtos: dict = field(default_factory=dict)
    lista_anterior: list = field(default_factory=list)
    erro: str = ""
    avisos: list = field(default_factory=list)


def ler(nuvem, dia, hoje, *, api=None, registro=None, log=print) -> LidoDaNuvem:
    if nuvem is None:
        return LidoDaNuvem(Conferencia(), erro="sem sessão na nuvem — entre de novo no app")
    try:
        conf = Conferencia.da_nuvem(nuvem.decisoes_do_dia(dia), nuvem.pagamentos_a_mao(dia))
        de_hoje = [ag.Agendado.de_linha(x) for x in nuvem.agendados_do_dia(dia)]
        abertos = [ag.Agendado.de_linha(x) for x in nuvem.agendados_em_aberto()]
        respostas = [ag.Resposta.de_linha(x) for x in nuvem.respostas([a.id for a in abertos])]
        nomes, anterior = nuvem.nomes_curtos(), nuvem.lista_anterior(dia)
    except Exception as e:                                   # noqa: BLE001
        return LidoDaNuvem(Conferencia(), erro=f"não li a nuvem ({e})")
    ultimas = ag.ultima_resposta(respostas)
    pend = ag.pendentes(abertos, respostas)
    avisos, titulos, relido = [], {}, False
    janela = ag.intervalo_de_releitura(pend, hoje)
    if janela and api is not None:
        try:
            ini, fim = janela
            titulos = {str(i.get("id")): i for i in api.listar_a_pagar(
                f"{ini:%Y-%m-%d}", f"{fim:%Y-%m-%d}", log=log) or () if i.get("id")}
            relido = True
        except Exception as e:                               # noqa: BLE001
            avisos.append(f"não reli os títulos agendados no ERP ({e}): nada foi pré-marcado")
    elif janela:
        avisos.append("sem a sessão do ERP: os títulos agendados não foram relidos")
    envios = {}
    refs = [a.lancamento_id for a in pend if a.lancamento_id]
    if refs and registro is not None:
        try:
            _por_id, envios = registro.envios_em_lote([], refs)
        except Exception as e:                               # noqa: BLE001
            avisos.append(f"não perguntei os retornos do banco ({e})")
    linhas = []
    for a in pend:
        envio = (envios.get(a.lancamento_id) or (None,))[0]
        sit = ag.situacao(a, titulos.get(a.lancamento_id), envio,
                          relido=relido or not a.lancamento_id)
        linhas.append((a, sit, ultimas.get(a.id)))
    return LidoDaNuvem(conf, de_hoje, linhas, nomes, anterior, "", avisos)
```
- [ ] **Passo 4:** `python -m pytest tests/test_nuvem_do_dia.py -q`. Esperado: PASSA.
- [ ] **Passo 5: commit** — `"Pagamentos do dia: leitura da nuvem, dos títulos agendados e do retorno"` + rodapé.

---

## Tarefa 11 — Tela: leitura com a nuvem e o passo 2 editável
**Modelo sugerido:** opus (fiação de dinheiro, falha fechada).

**Files:** Modify `tela_do_dia/frame.py`. Create `tela_do_dia/janelas.py`.

**Interfaces (tela):**
- `TelaDoDiaFrame.__init__` ganha `self.lido = None`, `self.conferencia = Conferencia()`, `self._nuvem_travada = "ainda não li a nuvem"` e `self._gravando = False`.
- `_t_ler` manda um 8º item no pacote `"leitura"` (o `LidoDaNuvem`).
- Métodos novos: `_cliente_nuvem() -> DiaNaNuvem | None`, `_na_nuvem(titulo, fazer, tipo)`, `_liberar()`, `_desmarcar()`, `_editar()`, `_desfazer()`, `_novo_a_mao()`, `_ler_link(texto, ao_ler)`, `_t_ler_link(ident)`, `_linha_da_selecao() -> confirmacao.Linha | None`.
- `janelas.py`:
  - `pedir_motivo(tela, titulo, explicacao, *, obrigatorio=True) -> str | None`
  - `pedir_edicao(tela, registro: dict) -> dict | None` (`{"campos", "motivo", "corrigir_no_erp"}`)
  - `pedir_a_mao(tela, contas: list[str], ler_link) -> dict | None`
  - `pedir_resposta(tela, titulo, *, com_data: bool) -> tuple[str, date | None] | None`
  - `pedir_nome_curto(tela, rotulo, atual) -> str | None`
  
  Todas usam `tela._janela(...)` (`frame.py:584`) e `tela._rodape(...)` (`:597`), com a mesma modalidade das janelas de hoje.

- [ ] **Passo 1: guarda (teste de importação e AST, sem janela)**
  - `python -c "import tela_do_dia.frame, tela_do_dia.janelas"`.
  - `python -m pytest tests/test_abas_em_paralelo.py -q`. Esperado: PASSA hoje e tem de continuar passando: toda chamada nova a `anx.submeter` em `frame.py` leva `dona=self`, e o `avisar_se_ocupado` dela leva `aba=self`.
- [ ] **Passo 2: leitura** (`_t_ler`, `:375`).
  - Depois de `contas = erp_do_dia.ler_saldos(...)`:
  ```python
              self.q.put(("status", "Lendo a nuvem (liberações, à mão, agendados)..."))
              lido = nuvem_do_dia.ler(self._cliente_nuvem(), periodo.fim, datetime.date.today(),
                                      api=api, registro=self._registro_nuvem(), log=self._log)
  ```
  - Acrescente `lido` ao fim da tupla de `("leitura", (...))`.
  - Os dois construtores levantam calados para `None`:
  ```python
      def _cliente_nuvem(self):
          try:
              return DiaNaNuvem(sessao.token(), sessao.quem().primeiro_nome)
          except Exception as e:                              # noqa: BLE001
              self._log(f"[!] nuvem: {e}")
              return None

      def _registro_nuvem(self):
          try:
              return registro.Registro(sessao.token())
          except Exception:                                   # noqa: BLE001
              return None
  ```
  - Imports novos no topo: `import threading`; `from nuvem import registro, sessao`; `from nuvem.pagamentos_do_dia import DiaNaNuvem`; `from . import agendados as agd, conferencia as cf, geracao, janelas, lancamento_do_erp, lista_diretor as ldr, nuvem_do_dia`.
- [ ] **Passo 3: `_receber_leitura` (`:419`) e `_recalcular` (`:476`).**
  - Desempacote os 8 itens. Faça `self.lido = lido`, `self.conferencia = lido.conferencia`, `self._nuvem_travada = lido.erro`.
  - Sendo `lido.erro`, registre `[!] {lido.erro} — liberar, editar, à mão e agendados ficam travados até buscar de novo` e mostre-o em `self.lbl_nuvem` (um `_ajuda(..., estilo="Erro.TLabel")` novo no cartão 2, fora do layout quando vazio, como `mostrar_periodo`).
  - Registre também cada `lido.avisos`.
  - Em `_recalcular`: `self.pagamentos, self.fora = pg.por_conta(self.leitura.grupos, self.mapping, self.conferencia)`.
  - Em `_limpar` (`:357`): zere `self.lido` e `self.conferencia = cf.Conferencia()`, e ponha `self._nuvem_travada = "ainda não li a nuvem"`.
- [ ] **Passo 4: geradores.**
  - `_resultado_que_sai` (`:805`) passa a ser `return geracao.resultado_da_tela(self.leitura.entradas, self.leitura.grupos, self.conferencia)`.
  - `_ir_para_remessa` (`:910`):
  ```python
          resultado = self._resultado_que_sai()
          fora = [r for regs in resultado.contas.values() for r in regs if r.get("a_mao")]
          for r in fora:
              self._log(f"  à mão não vai na remessa — pague pelo HTML: {r['favorecido']} {brl(de_float(r['valor']))}")
          self.aba_remessa.receber_apuracao(self.leitura, pg.ids_que_nao_saem(self.leitura.grupos),
                                            resultado=geracao.para_a_remessa(resultado))
  ```
  - O Excel não muda: `pg.totais_para_o_painel(self.pagamentos)` já soma liberados e à mão.
- [ ] **Passo 5: a tabela do passo 2** (`_encher_pagamentos`, `:520`).
  - Cada filha ganha `iid=f"{tipo}|{p.id}"`, com `tipo ∈ {vai, lib, mao, desm, env, bloq}`.
  - Valores e tags:
    - `vai` → ("vai sair", valor, "", situação + nota), tag `"atencao"` se `p.origem == "editado"`;
    - `lib` → ("liberado", …), tag `"atencao"`;
    - `mao` → ("à mão", …), tag `"atencao"`;
    - `desm` → ("", "", f"desmarcado · {brl}", situação), tag `"erro"`;
    - `env` e `bloq` como hoje.
  - A ajuda do cartão passa a citar "Selecione uma linha e use os botões abaixo".
  - Linha de botões sob `self.t_pag`:
    - `b_liberar` "Incluir mesmo assim…" → `_liberar`
    - `b_desmarcar` "Desmarcar" → `_desmarcar`
    - `b_editar` "Editar…" → `_editar`
    - `b_desfazer` "Desfazer" → `_desfazer`
    - `b_a_mao` "+ Pagamento à mão…" → `_novo_a_mao`
    
    Todos `papel="neutro"`, entram em `_botoes_do_dia` e ficam `disabled` quando `self._nuvem_travada`.
- [ ] **Passo 6: as ações** (cada uma recusa com `messagebox` quando `self._nuvem_travada` ou `self._gravando`, e grava pelo `_na_nuvem`):
```python
    def _na_nuvem(self, titulo, fazer, tipo):
        """Grava FORA da thread da tela (o rest espera até 20 s) e devolve pelo `q`.
        Nada muda na tela antes de o banco aceitar; falha vira recado."""
        if self._nuvem_travada:
            messagebox.showwarning(titulo, f"{self._nuvem_travada}\n\nSem a nuvem nada desta "
                                           "tela é gravado — busque de novo.")
            return
        if self._gravando:
            messagebox.showinfo(titulo, "Espere a gravação anterior terminar.")
            return
        self._gravando = True

        def correr():
            try:
                cliente = self._cliente_nuvem()
                if cliente is None:
                    raise RuntimeError("sem sessão na nuvem — entre de novo no app")
                self.q.put((tipo, fazer(cliente)))
            except Exception as e:                          # noqa: BLE001
                self.q.put(("aviso", (titulo, widgets.recado_de_erro(e, "Não gravei na nuvem."))))
            finally:
                self.q.put(("gravou", None))
        threading.Thread(target=correr, daemon=True).start()

    def _liberar(self):
        titulo = "Incluir mesmo assim"
        linha = self._linha_da_selecao()
        if linha is None or not cf.pode_liberar(linha):
            messagebox.showinfo(titulo, "Selecione um bloqueado ou um já enviado.")
            return
        certeza = cf.pede_certeza(linha)
        if certeza and not messagebox.askyesno(titulo, certeza, default="no"):
            return
        motivo = janelas.pedir_motivo(self, titulo, f"{linha.favorecido} · {brl(de_float(linha.valor))}\n"
                                                    f"Bloqueado por: {linha.situacao}")
        erro = cf.validar_motivo(motivo or "")
        if motivo is None or erro:
            if erro and motivo is not None:
                messagebox.showwarning(titulo, erro)
            return
        dia = self.periodo.fim
        self._na_nuvem(titulo, lambda c: c.registrar_decisao(
            dia, alvo=linha.id, conta=linha.conta, acao=cf.LIBERAR, motivo=motivo), "decisao")
```
  - `_desmarcar` só aceita linha `vai`. O motivo é opcional (`obrigatorio=False`). Linha `mao` vira `REMOVER_A_MAO`, com motivo obrigatório.
  - `_desfazer` grava `DESFAZER` para o alvo selecionado (pede um "tem certeza?").
  - `_editar`:
    1. pega `geracao.registro_atual(self.leitura.resultado, linha.id)`;
    2. chama `janelas.pedir_edicao`;
    3. roda `cf.validar_edicao(campos, motivo)`, e o erro vira `showwarning`;
    4. roda `cf.aviso_de_casamento({**registro, **{"descricao_editada": campos["descricao"]}} if "descricao" in campos else registro, linha.conta)`; o aviso vira `askyesno(... + "\n\nGravar assim mesmo?")`;
    5. `antes={k: registro.get(k, "") for k in campos}` e `_na_nuvem(... acao=cf.EDITAR, campos=campos, antes=antes, corrigir_no_erp=...)`.
  - `_novo_a_mao`:
    1. `contas = sorted({a.name for a in self.contas_erp if self.mapping.resolve_label(a.name)} | {g.conta for g in self.leitura.grupos})`;
    2. `dados = janelas.pedir_a_mao(self, contas, self._ler_link)`;
    3. `linha, erro = cf.nova_a_mao(conta=..., valor_texto=..., descricao=..., motivo=..., contas=set(contas), lido=dados.get("lido"), tipo=..., dados=..., favorecido=...)`;
    4. sem link → `askyesno("Sem o link do lançamento, o Anexar não tem o que casar depois. Gravar assim mesmo?")`;
    5. `_na_nuvem(titulo, lambda c: c.registrar_a_mao(dia, linha), "a_mao")`.
  - `_ler_link(texto, ao_ler)`:
  ```python
      def _ler_link(self, texto, ao_ler):
          ident = lancamento_do_erp.id_do_link(texto)
          if not ident:
              ao_ler(None, "Isto não parece o link de um lançamento do Mais Controle.")
              return
          if self.anx.avisar_se_ocupado("ler o lançamento", aba=self):
              return
          self._ao_ler_link = ao_ler
          self.anx.submeter("Pagamentos do dia — ler lançamento", self._t_ler_link, ident, dona=self)

      def _t_ler_link(self, ident):
          try:
              api = self.anx.garantir_sessao(self._log)
              lido = lancamento_do_erp.ler(api, ident, self.leitura.lancamentos, log=self._log)
              self.q.put(("link_lido", (lido, "")))
          except Exception as e:                          # noqa: BLE001
              self.q.put(("link_lido", (None, widgets.recado_de_erro(e, "Não li o lançamento."))))
  ```
  - `_drain` (`:289`) ganha os tipos:
    - `"decisao"` → `self.conferencia = self.conferencia.com_evento(valor); self._recalcular()`;
    - `"a_mao"` → `com_a_mao(valor)` + `_recalcular()`;
    - `"link_lido"` → `self._ao_ler_link(*valor)` se existir;
    - `"aviso"` → `messagebox.showwarning(*valor)`;
    - `"gravou"` → `self._gravando = False`.
  - `_linha_da_selecao` monta `{ln.id: ln for g in self.leitura.grupos for ln in [*g.entram, *g.nao_aptos]}` e lê o id do `iid` selecionado (`split("|", 1)[1]`).
- [ ] **Passo 7:**
  - `python -c "import tela_do_dia.frame"`;
  - `python -m pytest tests/test_abas_em_paralelo.py tests/test_tela_do_dia_pagamentos.py tests/test_tela_do_dia_geracao.py tests/test_tela_do_dia_conferencia.py -q`;
  - `python -m ruff check --select E9,F tela_do_dia`.
  
  Esperado: PASSA e sem achados. **Não abra a janela** (teste de tela só com o dono).
- [ ] **Passo 8: commit** — `"Pagamentos do dia: passo 2 editável na tela, gravado na nuvem"` + rodapé.

---

## Tarefa 12 — Tela: "Agendados a confirmar", passo 6 e passo 7
**Modelo sugerido:** sonnet.

**Files:** Modify `tela_do_dia/frame.py`.

**Interfaces (tela):**
- Cartões e tabelas novos:
  - `self.c0`: cartão "Agendados a confirmar", empacotado `before=c1` só com pendentes, com a tabela `self.t_agd`;
  - `c5`: "Agendar (no banco)", só ajuda;
  - `c6`: "Marcar agendados", com `self.t_marcar`;
  - `c7`: "Lista do diretor", com `self.t_lista`.
- Métodos: `_encher_agendados()`, `_clique_agd()`, `_responder(resposta)`, `_montar_para_marcar()`, `_gravar_agendados()`, `_montar_lista()`, `_lista_mover(delta)`, `_lista_ordinal()`, `_nome_curto()`, `_copiar_lista()`.

- [ ] **Passo 1: "Agendados a confirmar".**
  - Colunas `COLS_AGD = (("marca","",30,"center"), ("dia","AGENDADO",80,"w"), ("conta","CONTA",160,"w"), ("fav","FAVORECIDO",170,"w"), ("valor","VALOR",100,"e"), ("sit","SITUAÇÃO",200,"w"))`. A soma cabe a 1280x800, a mesma régua de `LINHAS_VAZIA`/`_ajustar_altura`.
  - `_encher_agendados` lê `self.lido.pendentes`. A marca nasce `☑` quando `sit.pre_marca`, com a tag de `sit.tag`. Uma resposta `reagendado` anterior aparece na situação ("reagendado para dd/mm"). Sem pendentes, `self.c0.pack_forget()`.
  - Clique na 1ª coluna (ou Espaço) troca a marca. Como na lista da Remessa, a marca vive num `dict {agendado_id: bool}`.
  - Botões:
    - **"Pago (os marcados)"** → para cada marcado, `c.responder(id, "pago", prova=sit.prova)`, num `_na_nuvem` só (uma função que faz o laço e devolve os ids gravados).
    - **"Não saiu…"** (selecionado) → `janelas.pedir_resposta(..., com_data=False)` + `agd.validar_resposta`.
    - **"Reagendado…"** (selecionado) → `pedir_resposta(..., com_data=True)`.
  - Resposta gravada (`"respondido"` no `_drain`): pago e não saiu saem da lista; reagendado fica, com a data.
- [ ] **Passo 2: cartão 5** — `widgets.Cartao(corpo, "Agendar (no banco)", 5)`, com a ajuda: "Agende no banco como sempre — isto fica fora do app. Depois, marque aqui embaixo o que agendou."
- [ ] **Passo 3: passo 6 "Marcar agendados".**
  - `t_marcar` com as colunas marca, conta, favorecido, valor, situação. "Montar a lista" faz `agd.para_marcar(self.pagamentos, self.fora, self.leitura.lancamentos, self.conferencia, {a.alvo for a in self.lido.agendados_hoje})`: tudo nasce marcado e o já marcado hoje aparece cinza ("já marcado hoje").
  - "Gravar agendados" faz `_na_nuvem(titulo, lambda c: c.marcar_agendados(dia, agd.linhas_para_nuvem(itens)), "agendados")`.
  - No `_drain`, `"agendados"` → acrescenta as gravadas a `self.lido.agendados_hoje` (via `agd.Agendado.de_linha`), loga as repetidas ("já estava marcado por outra máquina") e chama `_montar_lista()`.
  - Recusa se `self._nuvem_travada`.
- [ ] **Passo 4: passo 7 "Lista do diretor".**
  - `_montar_lista`:
  ```python
          rotulo = lambda conta: (self.mapping.resolve_label(conta).label    # noqa: E731
                                  if self.mapping.resolve_label(conta) else conta)
          self.lista = ldr.sugerir_ordem(
              ldr.montar(self.lido.agendados_hoje, rotulo, self.lido.nomes_curtos),
              self.lido.lista_anterior)
  ```
  - Tabela com ordinal ("1º" ou ""), nome e valor. Botões:
    - "↑" / "↓" → `ldr.mover`;
    - "Ordinal sim/não" → `ldr.alternar_ordinal`;
    - "Nome curto…" → `janelas.pedir_nome_curto` + `ldr.validar_nome_curto` + `_na_nuvem(… c.gravar_nome_curto(rotulo, nome), "nome_curto")`; no `_drain`, atualiza `self.lido.nomes_curtos` e a linha;
    - **"Copiar para o WhatsApp"** → `texto = ldr.texto_whatsapp(self.lista)`, depois `self.clipboard_clear(); self.clipboard_append(texto)`, log "Lista copiada", e grava na nuvem em segundo plano (`c.gravar_lista(dia, ldr.para_nuvem(self.lista), texto)`). Falha na gravação só avisa: a lista já foi copiada, e o que se perde é só a sugestão de amanhã.
  - Só entra o agendado de HOJE (`self.lido.agendados_hoje`).
- [ ] **Passo 5:** todos os botões novos entram em `_botoes_do_dia` e ficam `disabled` sem leitura ou com `self._nuvem_travada`. `mostrar_numeros()` tolera `self.lido is None` (a `ferramentas/galeria.py` chama sem nuvem).
- [ ] **Passo 6:** `python -c "import tela_do_dia.frame"`; `python -m pytest tests/test_abas_em_paralelo.py tests/test_registro_visivel.py -q` (este último pode pular sem display; não force); `python -m ruff check --select E9,F tela_do_dia`. Esperado: PASSA ou pula, sem achados.
- [ ] **Passo 7: commit** — `"Pagamentos do dia: agendados a confirmar, marcar agendados e lista do diretor"` + rodapé.

---

## Tarefa 13 — Documentação e a suíte pura inteira
**Modelo sugerido:** haiku.

**Files:** Modify `.claude/rules/arquitetura-tela-do-dia.md`, `.claude/rules/nuvem-e-remessas.md`, `.claude/rules/arquitetura-pagamentos-dia.md`

- [ ] **Passo 1: `arquitetura-tela-do-dia.md`.**
  - Acrescente à tabela "Quem decide o quê" as linhas de `conferencia`, `geracao`, `lancamento_do_erp`, `agendados`, `lista_diretor`, `nuvem_do_dia` e `janelas`.
  - Seções novas:
    - "Conferência editável": LIBERADO/EDITADO/À MÃO nunca "APTO"; ATENÇÃO grave fica; à mão fora da remessa; casamento do Anexar.
    - "Agendados": nunca se resolve sozinho; provas; reagendado fica.
    - "Lista do diretor".
    - "Sem nuvem, a entrega 2 trava (falha fechada)".
  - Na seção "O JSON do dia", troque "Sem SQL nesta entrega; a nuvem é a entrega 2" pelo motivo de os ajustes continuarem locais.
- [ ] **Passo 2: `nuvem-e-remessas.md`.**
  - Seção "O dia de trabalho da tela na nuvem (22/10/2026)": as 6 tabelas e a view, append-only, `quem` carimbado, `quem_nome` só para mostrar, índice único (dia, alvo).
  - Atualize "O que ainda NÃO está na nuvem": ajustes de saldo e `enviados_aportes`, no JSON do dia.
- [ ] **Passo 3: `arquitetura-pagamentos-dia.md`.** Um parágrafo sobre os quatro ganchos opcionais (`ids_liberados`, `descricao_editada`, `_CHAVES_DA_DESCRICAO`, `receber_apuracao(resultado=)`), cada um com padrão igual ao comportamento de antes e com o teste que prova isso.
- [ ] **Passo 4: suíte pura** (sem `raiz`; `git add` dos arquivos novos antes):
```
python -m pytest tests/test_pagamentos_do_dia_sql.py tests/test_rls_supabase.py tests/test_nuvem_pagamentos_do_dia.py tests/test_ganchos_da_tela_do_dia.py tests/test_tela_do_dia_conferencia.py tests/test_tela_do_dia_geracao.py tests/test_tela_do_dia_lancamento_erp.py tests/test_tela_do_dia_agendados.py tests/test_tela_do_dia_lista_diretor.py tests/test_nuvem_do_dia.py tests/test_tela_do_dia_pagamentos.py tests/test_tela_do_dia_decisoes.py tests/test_tela_do_dia_aportes.py tests/test_tela_do_dia_excel.py tests/test_tela_do_dia_saldos.py tests/test_tela_do_dia_valores.py tests/test_tela_do_dia_dia_de_trabalho.py tests/test_tela_do_dia_para_aportes.py tests/test_tela_do_dia_erp.py tests/test_leitura_do_dia.py tests/test_remessa_receber_apuracao.py tests/test_html_pagamentos.py tests/test_remessa_dia.py tests/test_confirmacao.py tests/test_pagamentos_dia.py tests/test_descricao_e_ordem.py tests/test_regras_14_10.py tests/test_matcher.py tests/test_registro_nuvem.py tests/test_empacotamento.py tests/test_imports_do_motor.py tests/test_nomes_de_modulo.py tests/test_abas_em_paralelo.py -q
python -m ruff check --select E9,F .
python -m vermin --target=3.11 --no-tips --violations tela_do_dia nuvem/pagamentos_do_dia.py
```
Esperado: tudo passa, sem achados e sem violações.
- [ ] **Passo 5:** confira que `C:\AUTOMAÇÕES MAIS CONTROLE\APLICAR NO SUPABASE - 2026-10-22 pagamentos do dia na nuvem.sql` é idêntico à migration (`fc` ou `diff`). Avise o coordenador: o SQL passa pelo revisor e é aplicado pelo CLI **antes** do merge.
- [ ] **Passo 6: commit** — `"Pagamentos do dia: documentação da entrega 2"` + rodapé.

**Ordem de execução:** 1 → 2 → 3 → 7 → 4 → 5 → 6 → 8 → 9 → 10 → 11 → 12 → 13.

---

## Riscos e decisões (para o dono e o revisor)
1. **À mão não vai na remessa CNAB** (vai no HTML, na planilha, no Excel e no a pagar). Sem lançamento não há referência para retorno nem baixa; com link parcial, a baixa automática do retorno arriscaria o valor cheio. A Remessa avisa no Registro.
2. **LIBERADO/EDITADO nascem desmarcados na conferência da Remessa** (é um clique a mais, de propósito), e o HTML deixa copiar. Exceção: ATENÇÃO grave pré-existente (valor diverge, documento não bate, CNPJ, parcial) continua bloqueando o Copiar.
3. **O formato completo do `overview` do ERP não foi medido.** O link lê o item pela lista do dia de vencimento; sem ele, só o detalhe, com aviso, e o campo ausente fica para o dono digitar. Vale medir com o dono logado (só leitura) no dia 22/10, junto com o Sicoob.
4. **Resposta "pago" dada por engano não tem "reabrir" na tela.** É append-only; corrige-se inserindo uma resposta nova pelo painel, e a última vale na view e no Python.
5. **"Comprovante baixado" como prova fica para a entrega 5** (`situacao(prova_extra=)` pronto). A entrega 2 pré-marca por baixa no ERP, baixa parcial ao centavo e retorno "ok".
6. **Reler os títulos agendados custa uma listagem extra do ERP por Buscar** (vencimento mais antigo −31 dias a hoje +31). Título remarcado para fora dessa janela aparece como "sumiu" e espera resposta: o lado seguro.
7. **Ajustes de saldo, simulação e `enviados_aportes` continuam no JSON local** (justificativa no topo). A spec os listava na nuvem; o pedido desta entrega permitiu ficarem.
8. **`quem_nome` é só para mostrar.** A autoridade é `quem` (`auth.uid()`), porque a RLS da `perfil` não deixa ler o nome dos outros.
9. **A migration tem de estar aplicada antes do merge.** Sem as tabelas, a tela trava edições e agendados com "não li a nuvem" (falha fechada, mas o dia fica sem a entrega 2).
10. **"Arrastar para ordenar" virou ↑/↓.** E `pagamentos_frame.py` ganha só o parâmetro opcional `resultado=` (a duplicação declarada da leitura, da entrega 1, continua).

### Critical Files for Implementation
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2\tela_do_dia\pagamentos.py
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2\pagamentos_dia\relatorio.py
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2\pagamentos_dia\confirmacao.py
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2\tela_do_dia\frame.py
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2\nuvem\registro.py