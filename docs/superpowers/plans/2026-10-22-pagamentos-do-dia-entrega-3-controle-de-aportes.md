# Plano de implementação: Entrega 3, aba "Controle de aportes"

> **Para quem executa:** este plano segue o superpowers:writing-plans. Ele vai para `docs/superpowers/plans/2026-10-22-pagamentos-do-dia-entrega-3-controle-de-aportes.md` no worktree `C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2` (branch `codigo/pagamentos-do-dia-2`). O código de cada tarefa sai na ordem; as tarefas 2 a 6 são puras e seguem TDD.

**Goal:** uma aba nova, "Controle de aportes", que mostra por conta e por aportador:
- quanto cada um aportou desde a data de abertura;
- quanto deveria ter aportado pela proporção;
- a diferença, isto é, quem deve quanto para igualar.

A leitura dos recebimentos de aporte do ERP é só-leitura e vai pelo Chrome do app. Abertura, proporção e os apontamentos dos recebimentos "sem dono" ficam no Supabase, e só o dono (admin) edita.

**Architecture:** tudo mora no pacote existente `tela_do_dia/`, com o prefixo `controle_`. Não precisa de pasta nova nem de linha nova no `build.yml`: o `tela_do_dia/*.py` já entra no zip (`.github/workflows/build.yml:472-475`) e já está em `_PASTAS` (`tests/test_imports_do_motor.py:31`). A regra `.claude/rules/arquitetura-tela-do-dia.md` carrega sozinha nos caminhos `tela_do_dia/**` e `tests/test_tela_do_dia*.py`, que são exatamente os arquivos desta entrega. Os módulos são quatro:

| Módulo | Papel |
|---|---|
| `controle_aportes.py` | Puro: dados, a conta, identificação do aportador, formulário |
| `controle_erp.py` | Leitura `GET receipt-installments` pela aba do robô, com os filtros conferidos |
| `controle_nuvem.py` | Supabase pelo `nuvem.rest` |
| `controle_frame.py` | Tela fina |

**Tech Stack:** Python 3.11, tkinter/ttk, `Decimal`, PostgREST (`nuvem/rest.py`), Playwright pela `MCApi` (`anexar/mc_api.py`), Postgres com RLS.

**Spec:** `C:\AUTOMAÇÕES MAIS CONTROLE\PROPOSTA - 2026-10-21 pagamentos do dia numa tela so.html`, versão 3, seção "Aba nova: Controle de aportes". O contexto está em `.superpowers/sdd/contexto-entregas-2-a-5.md`.

---

## Global Constraints

1. **Repositório público.** Nenhum nome real de pessoa, empresa ou conta em código, teste, comentário, plano ou commit. Os testes usam nomes fictícios: "FULANO ALFA DA SILVA" e "FULANO BETA SOUZA", de mesmo primeiro nome de propósito, e "CONTA MAE - BANCO". Os dados reais vão só no arquivo da raiz, fora do repositório.
2. **Nada escreve no ERP.** Só `GET`, pelo Chrome do app. Os caminhos são `self.anx.garantir_sessao`, `MCApi._fetch_json`, `_base_legacy` e `_base_erp`. Nunca usar `POST /users/login` nem login HTTP. Os saldos e contas vêm de `erp_do_dia.ler_saldos` (`tela_do_dia/erp_do_dia.py:74`).
3. **Dinheiro em `Decimal`.** A fronteira do JSON da nuvem é texto (`format(..., "f")`), nunca float.
4. **Falha fechada.** Recebimento ilegível, filtro do ERP ignorado ou parcela repetida não viram zero nem "em dia": a conta mostra erro e nenhum número dela.
5. **O aportador se casa pelo nome COMPLETO.** A comparação é `util.norm_espaco(customerName) == util.norm_espaco(nome_erp)`, contra os aportadores daquela conta. Nunca por primeiro nome nem por pedaço. O que não casa vai para "sem dono".
6. **Testes de tela não rodam sem o dono liberar.** A regra fica em módulo puro e a tela é fina. Na tela, só a guarda por AST de `tests/test_abas_em_paralelo.py` (`avisar_se_ocupado(aba=self)` = `submeter(dona=self)`).
7. **As abas Remessa/Retorno, Saldo de pagamentos, Anexar, Aportes e Pagamentos do dia não mudam de comportamento.** Nenhum módulo delas é editado. `mc_api.listar_recebimentos` NÃO é reaproveitada nem alterada, porque ela fixa as naturezas de venda da aba Contratos.
8. **SQL em dois lugares:**
   - migration no repositório, só estrutura;
   - `C:\AUTOMAÇÕES MAIS CONTROLE\APLICAR NO SUPABASE - 2026-10-22 controle de aportes.sql` com estrutura e dados reais (o coordenador preenche).
   
   A leitura exige `privado.e_ativo()` e a escrita exige `privado.e_ativo()` e `privado.e_admin()`. O SQL passa pelo revisor de SQL e o coordenador aplica pelo CLI **antes** de liberar o app.
9. **Comandos rodam no Python 3.11 de destino:** `vermin --target=3.11 --no-tips --violations <arquivos>` e `ruff check --select E9,F <arquivos>`. Não entra import novo de submódulo da stdlib: só `datetime`, `decimal`, `dataclasses`, `threading`, `queue`, `urllib.parse`, todos já no exe.
10. **Commits em português**, terminando com a linha `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Identificação do aportador.** O casamento é só pelo nome completo normalizado, e os dois "Fulano" nunca se misturam.
2. **A conta.** `aportou` = abertura + ERP; o nível é o maior `aportou ÷ parte`; `deveria` = nível × parte; `para igualar` = deveria − aportou. Com dois sócios meio a meio e abertura 50.000 × 0, o resultado tem de ser "deve R$ 50.000,00".
3. **Filtros do ERP conferidos.** A mesma parcela em duas contas, em duas naturezas ou na contraprova PARA a leitura.
4. **RLS.** A escrita é só do admin ativo, os grants vão por coluna, a conta não se apaga pelo app, e o aportador com apontamento não some.
5. **Tkinter só na thread da interface.** A nuvem roda numa thread própria e os valores de `StringVar` são lidos antes dela.

Testes que guardam isso: `tests/test_tela_do_dia_controle.py`, `test_tela_do_dia_controle_erp.py`, `test_tela_do_dia_controle_nuvem.py`, `test_tela_do_dia_controle_sql.py`, `test_tela_do_dia_controle_menu.py`, `test_rls_supabase.py`, `test_abas_em_paralelo.py -k todo_aviso` e `test_visual.py -k "tabelas_de_icones or nenhum_icone"`.

---

## Decisões de desenho

### De onde vêm as proporções

As proporções vêm de uma tabela própria na nuvem, `controle_aporte_aportador`. O que já existe ficou de fora, por estes motivos:

- **Aba Regras do MODELO.xlsx** (`conciliacao/aportadores.py:43`), NÃO:
  - é um arquivo local, de uma máquina só;
  - usa o vocabulário do painel (o rótulo da conta e o rótulo do aportador), não o nome do Cliente no ERP, então casar seria chutar, que é o que a regra dos dois aportadores de mesmo primeiro nome proíbe;
  - peso vazio quer dizer "sem regra fixa", o que não define dívida;
  - responde "quem manda hoje", não "quem deve desde a abertura".
- **`subconta_investidor`** (`aportes/rateio_subconta.py:148`), NÃO como fonte viva:
  - só existe para subconta de investidor, e a conta-mãe não é uma;
  - mudar o rateio no meio do período reescreveria o passado.
  
  Ela entra como **sugestão** no formulário ("Trazer do rateio da subconta", lendo o cache `aportes.dados.carregar_subcontas`, `aportes/dados.py:81`) e como **aviso de divergência** na tela. Os nomes dela já são os do ERP letra por letra (`rateio_subconta.py:18-20`).

### Como se reconhece um aporte

O código da aba Aportes mostra o que um recebimento de aporte carrega no ERP:

- O recebimento nasce em `mc_lancamentos.criar_recebimento` (`aportes/mc_lancamentos.py:146`), com `customer` = participante (`:180`), `nature` (`:187`), `defaultAccount` (`:188`) e `work` = obra/CC (`:179`).
- A natureza é `NATUREZA_RECEBIMENTO` (`aportes/regras.py:37-41`): "Aporte de Capital", ou "Aporte de Investidor" (`TIPO_INVESTIDOR`, `:26`).
- O Cliente é `entidades[pagador]["nome_oficial"]` (`regras.py:419`), ou o nome do investidor da subconta (`:410`).
- O CC é `obra_padrao` (o "Controle de Aportes", `rateio_subconta.py:16`) ou a obra da subconta (`:412`, `:421`).

Daí a regra: **natureza ∈ {Aporte de Capital, Aporte de Investidor}** (filtro no servidor, por id resolvido em `GET /natures`) e **aportador = `customerName`**. O CC não filtra, porque a equipe pode lançar com outro CC; ele só aparece na tela. A descrição também não casa nada, para não haver risco de primeiro nome; ela só aparece na lista "sem dono" para o dono apontar.

### Endpoint

`GET {legacy}/maiscontrole/services/receipt-installments` com:
- `startDate=abertura`, `endDate=hoje`;
- `dateField=DATE_OF_RECEIPT`, `type=PAID`;
- `accountIds=<id da conta>`, `natureIds=<id>`;
- `page` (base 0) e `size=200`, com fim por `last`.

É o mesmo endereço e a mesma paginação de `MCApi.listar_recebimentos` (`anexar/mc_api.py:699-735`). Os campos `id`, `dateOfReceipt`, `sumOfReceivedValues`, `customerName`, `description` e `workName` já são lidos em produção pela aba Contratos (`contratos/regras.py:183-212`).

**Não medido:** se `accountIds` e `natureIds` filtram de fato. Por isso a leitura é conferida:
- parcela em duas contas ou em duas naturezas → erro;
- uma conta fora do controle é lida como contraprova;
- o `accountName` do item, quando vier, tem de bater com a conta pedida.

### O que é "abertura"

A abertura fica guardada como "já aportado antes da abertura" por aportador. É um crédito ≥ 0, que compõe com qualquer proporção. O formulário tem o atalho "Quem deve quanto…" (`aberturas_para_divida`), que transforma "X deve R$ V" nesses créditos.

Para a conta-mãe, meio a meio: o sócio em dia fica com 50.000,00 e o devedor com 0. Resultado: o devedor deve R$ 50.000,00 para igualar.

### Menu

A aba entra no **grupo DIÁRIO, no fim** (chave `cap`, ícone 🤝 → Fluent/MDL2 `\uE716` "People"):
- ela responde à pergunta do passo 3 de todo dia ("quem põe hoje");
- no fim do grupo, não tira o Ctrl+1..9 de nenhuma tela existente (a 10ª tela só tem Ctrl+Tab, `comprovantes_app.py:757-760`);
- o aprovador não a vê, sem mudar nada: `ABAS_DO_PAPEL["aprovador"]` (`nuvem/usuarios.py:44-48`) já é uma lista fechada.

---

## Mapa de arquivos

**Novos:**
- `supabase/migrations/20261022130000_controle_de_aportes.sql`
- `tela_do_dia/controle_aportes.py`
- `tela_do_dia/controle_erp.py`
- `tela_do_dia/controle_nuvem.py`
- `tela_do_dia/controle_frame.py`
- `tests/test_tela_do_dia_controle.py`
- `tests/test_tela_do_dia_controle_erp.py`
- `tests/test_tela_do_dia_controle_nuvem.py`
- `tests/test_tela_do_dia_controle_sql.py`
- `tests/test_tela_do_dia_controle_menu.py`
- Fora do repositório (o coordenador escreve, nunca commitar): `C:\AUTOMAÇÕES MAIS CONTROLE\APLICAR NO SUPABASE - 2026-10-22 controle de aportes.sql`

> ### ⚠️ ARQUIVOS EXISTENTES MODIFICADOS
> - **`comprovantes_app.py`**: o import, `aba_cap = ControleAportesFrame(...)` mais `liberar_edicao(_eu.admin)`, `"cap"` no `quadros` e no `_grupo("diario", ...)`, e os comentários "treze" → "catorze". Não muda nada em outra aba.
> - **`widgets.py`**: `"🤝": "\uE716"` em `ICONES_FLUENT` e em `ICONES_MDL2` (`widgets.py:262-298`).
> - **`tests/test_abas_em_paralelo.py`**: `"tela_do_dia/controle_frame.py"` em `_CHAMADORES` (`:211-214`).
> - **`ferramentas/galeria.py`**: `_ORDEM` (`:188-202`), `_montar` (`:374`), DIÁRIO (`:450`) e o import.
> - **`.claude/rules/arquitetura-tela-do-dia.md`**, **`.claude/rules/arquitetura-interface.md`** (`:25`), **`.claude/rules/arquitetura-ferramentas.md`** (`:16`), **`docs/ERP-CLIENTES.md`** (linha nova na tabela, `:30+`), **`CLAUDE.md`** (`:426` "13 telas" → 14).
> 
> **NÃO mudam:** `anexar/mc_api.py`, `aportes/*`, `tela_do_dia/frame.py`, `pagamentos_dia/*`, `.github/workflows/build.yml`, `tests/test_imports_do_motor.py`, `motor_minimo.txt`.

---

## Tarefa 1: Migration, arquivo da raiz e teste estático do SQL

**MODELO:** opus (segurança de dado de dinheiro)

**Files:**
- Create: `supabase/migrations/20261022130000_controle_de_aportes.sql`
- Create: `tests/test_tela_do_dia_controle_sql.py`
- Coordenador (fora do repositório): `C:\AUTOMAÇÕES MAIS CONTROLE\APLICAR NO SUPABASE - 2026-10-22 controle de aportes.sql`

**Interfaces (conferidas):**
- `privado.e_ativo()`: `supabase/migrations/20260830180000_so_conta_liberada_entra.sql:39`.
- `privado.e_admin()`: `20260830160000_contas_de_usuario.sql:105`.
- O padrão `revoke` + `grant` por coluna: `20260814100000_app_so_le.sql`.
- A política de update com porteira: `20261021100000_entidade_pode_ser_corrigida_pelo_app.sql:24-30`.
- A guarda global: `tests/test_rls_supabase.py:85-96`, onde toda política tem de citar `e_ativo` e nenhum `grant` pode ter `all`, `truncate`, `trigger`, `references` ou `maintain`.

- [ ] **Passo 1 (RED): o teste**

```python
# tests/test_tela_do_dia_controle_sql.py
# -*- coding: utf-8 -*-
"""A migration do Controle de aportes, lida como texto (sem Postgres).

Ler: quem tem conta liberada. Escrever: só administrador ativo — abertura e
proporção decidem quem deve dinheiro a quem."""
import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
_SQL = _RAIZ / "supabase" / "migrations" / "20261022130000_controle_de_aportes.sql"
_TABELAS = ("controle_aporte_conta", "controle_aporte_aportador",
            "controle_aporte_atribuicao")


def _comandos() -> list[str]:
    texto = re.sub(r"\$\$.*?\$\$", " CORPO ", _SQL.read_text(encoding="utf-8"), flags=re.S)
    texto = re.sub(r"--[^\n]*", " ", texto)
    return [" ".join(c.split()).lower() for c in texto.split(";") if c.strip()]


def test_as_tres_tabelas_tem_rls():
    cmds = _comandos()
    for t in _TABELAS:
        assert f"alter table public.{t} enable row level security" in cmds


def test_le_quem_esta_liberado_e_escreve_so_o_admin():
    pols = [c for c in _comandos() if c.startswith("create policy")]
    for t in _TABELAS:
        deles = [c for c in pols if f" on public.{t} " in f"{c} "]
        assert any(" for select " in c for c in deles), t
        for c in deles:
            assert "privado.e_ativo()" in c, c
            if " for select " not in c:
                assert "privado.e_admin()" in c, c
        assert {v for v in ("insert", "update")
                if any(f" for {v} " in c for c in deles)} == {"insert", "update"}


def test_a_api_so_ganha_o_que_a_tela_usa():
    cmds = _comandos()
    assert any(c.startswith("revoke all on table public.controle_aporte_conta")
               and "anon" in c and "authenticated" in c for c in cmds)
    for c in cmds:
        if c.startswith("grant "):
            assert " all " not in f" {c} " and "anon" not in c, c
    # A conta não se apaga pelo app (só pelo painel): levaria os apontamentos.
    assert not any(c.startswith("grant") and "delete" in c
                   and "public.controle_aporte_conta to" in c for c in cmds)
    assert "using (true)" not in " ".join(cmds)


def test_estrutura_so_sem_dado():
    """Os nomes reais e a abertura vão pelo arquivo da raiz, fora do repositório."""
    assert "insert into" not in _SQL.read_text(encoding="utf-8").lower()
```

- [ ] **Passo 2:** `python -m pytest tests/test_tela_do_dia_controle_sql.py -q` → FAIL (o arquivo não existe).

- [ ] **Passo 3 (GREEN): a migration**

```sql
-- ---------------------------------------------------- controle de aportes
-- Entrega 3 da aba "Pagamentos do dia" (22/10/2026): a aba "Controle de
-- aportes" mostra, por conta e por aportador, quanto cada um aportou desde a
-- abertura, quanto deveria pela proporcao e quem deve quanto para igualar.
--
-- O DINHEIRO vem do ERP (recebimentos de aporte, lidos e nunca escritos).
-- Aqui moram so tres coisas: a ABERTURA de cada conta, a PROPORCAO de cada
-- aportador (com o "ja aportado antes da abertura") e os recebimentos "sem
-- dono" que o dono APONTOU (de quem sao, ou "nao e aporte desta conta").
--
-- Ler: quem tem conta liberada (privado.e_ativo()). Escrever: so
-- administrador ativo (privado.e_admin()) -- abertura e proporcao decidem
-- quem deve dinheiro a quem. A porteira e_ativo() vai junto em toda
-- politica para a regra de tests/test_rls_supabase.py valer a vista.
--
-- `aportador_id` com ON DELETE NO ACTION (e nao RESTRICT): apagar um
-- aportador que tem apontamento falha; apagar a CONTA (so pelo painel) leva
-- aportadores e apontamentos juntos, e NO ACTION confere no fim do comando,
-- depois das duas cascatas.
--
-- `alterado_por` aceita nulo: o arquivo da raiz grava pelo SQL Editor, onde
-- auth.uid() e nulo. Pelo app, o default e o gatilho o preenchem.
--
-- Nada de nome real aqui: os dados de abertura vao pelo arquivo da raiz.
-- ORDEM: aplicar ANTES de liberar o app (app novo com banco velho = a aba
-- mostra erro; as outras abas nao usam estas tabelas).
-- Idempotente; numa transacao.

begin;

create table if not exists public.controle_aporte_conta (
  id            bigint generated always as identity primary key,
  conta_erp     text not null,
  abertura      date not null,
  ativa         boolean not null default true,
  observacao    text not null default '',
  alterado_por  uuid default auth.uid() references auth.users (id),
  alterado_em   timestamptz not null default now(),
  constraint controle_aporte_conta_tem_nome check (length(trim(conta_erp)) > 0),
  constraint controle_aporte_conta_unica unique (conta_erp)
);

comment on table public.controle_aporte_conta is
  'Contas acompanhadas pela aba Controle de aportes. conta_erp = nome da conta '
  'bancaria no Mais Controle, letra por letra. abertura = primeiro dia contado.';

create table if not exists public.controle_aporte_aportador (
  id            bigint generated always as identity primary key,
  conta_id      bigint not null
                references public.controle_aporte_conta (id) on delete cascade,
  nome_erp      text not null,
  peso          numeric not null,
  abertura      numeric(15, 2) not null default 0,
  alterado_por  uuid default auth.uid() references auth.users (id),
  alterado_em   timestamptz not null default now(),
  constraint controle_aporte_aportador_tem_nome check (length(trim(nome_erp)) > 0),
  -- `< 'Infinity'`: scale('NaN') e scale('Infinity') sao NULL (ver a
  -- migration 20261002100000).
  constraint controle_aporte_aportador_peso_possivel
    check (peso > 0 and peso < 'Infinity' and scale(peso) <= 4),
  constraint controle_aporte_aportador_abertura_possivel check (abertura >= 0),
  constraint controle_aporte_aportador_unico unique (conta_id, nome_erp)
);

comment on column public.controle_aporte_aportador.nome_erp is
  'O Cliente dos recebimentos de aporte deste aportador no Mais Controle, '
  'nome COMPLETO. Nunca primeiro nome: dois aportadores com o mesmo primeiro '
  'nome sao pessoas diferentes.';
comment on column public.controle_aporte_aportador.abertura is
  'Ja aportado ANTES da data de abertura (credito de partida, >= 0).';

create index if not exists controle_aporte_aportador_conta_idx
  on public.controle_aporte_aportador (conta_id);

create table if not exists public.controle_aporte_atribuicao (
  id               bigint generated always as identity primary key,
  conta_id         bigint not null
                   references public.controle_aporte_conta (id) on delete cascade,
  recebimento_erp  text not null,
  aportador_id     bigint
                   references public.controle_aporte_aportador (id) on delete no action,
  valor            numeric(15, 2) not null,
  motivo           text not null,
  alterado_por     uuid default auth.uid() references auth.users (id),
  alterado_em      timestamptz not null default now(),
  constraint controle_aporte_atribuicao_valor_positivo check (valor > 0),
  constraint controle_aporte_atribuicao_tem_motivo check (length(trim(motivo)) > 0),
  constraint controle_aporte_atribuicao_unica unique (conta_id, recebimento_erp)
);

comment on table public.controle_aporte_atribuicao is
  'Recebimento "sem dono" que o dono apontou. aportador_id nulo = nao e '
  'aporte desta conta. valor = o do recebimento quando foi apontado: se o '
  'ERP mudar, o app devolve a linha para "sem dono" (nunca se resolve sozinho).';

create index if not exists controle_aporte_atribuicao_aportador_idx
  on public.controle_aporte_atribuicao (aportador_id);

-- ------------------------------------------------ carimbo de quem alterou
create or replace function privado.controle_aporte_carimbo()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  new.alterado_em := now();
  new.alterado_por := coalesce((select auth.uid()), old.alterado_por);
  return new;
end;
$$;

revoke all on function privado.controle_aporte_carimbo() from public, anon, authenticated;

drop trigger if exists controle_aporte_conta_carimbo on public.controle_aporte_conta;
create trigger controle_aporte_conta_carimbo
  before update on public.controle_aporte_conta
  for each row execute function privado.controle_aporte_carimbo();
drop trigger if exists controle_aporte_aportador_carimbo on public.controle_aporte_aportador;
create trigger controle_aporte_aportador_carimbo
  before update on public.controle_aporte_aportador
  for each row execute function privado.controle_aporte_carimbo();
drop trigger if exists controle_aporte_atribuicao_carimbo on public.controle_aporte_atribuicao;
create trigger controle_aporte_atribuicao_carimbo
  before update on public.controle_aporte_atribuicao
  for each row execute function privado.controle_aporte_carimbo();

-- ------------------------------------------------------------- permissoes
alter table public.controle_aporte_conta enable row level security;
alter table public.controle_aporte_aportador enable row level security;
alter table public.controle_aporte_atribuicao enable row level security;

revoke all on table public.controle_aporte_conta, public.controle_aporte_aportador,
  public.controle_aporte_atribuicao from anon, authenticated;

grant select on table public.controle_aporte_conta, public.controle_aporte_aportador,
  public.controle_aporte_atribuicao to authenticated;
grant insert (conta_erp, abertura, ativa, observacao),
      update (conta_erp, abertura, ativa, observacao)
  on table public.controle_aporte_conta to authenticated;
grant insert (conta_id, nome_erp, peso, abertura),
      update (nome_erp, peso, abertura), delete
  on table public.controle_aporte_aportador to authenticated;
grant insert (conta_id, recebimento_erp, aportador_id, valor, motivo),
      update (aportador_id, valor, motivo), delete
  on table public.controle_aporte_atribuicao to authenticated;

drop policy if exists controle_aporte_conta_le on public.controle_aporte_conta;
create policy controle_aporte_conta_le on public.controle_aporte_conta
  for select to authenticated using ((select privado.e_ativo()));
drop policy if exists controle_aporte_conta_cadastra on public.controle_aporte_conta;
create policy controle_aporte_conta_cadastra on public.controle_aporte_conta
  for insert to authenticated
  with check ((select privado.e_ativo()) and (select privado.e_admin()));
drop policy if exists controle_aporte_conta_corrige on public.controle_aporte_conta;
create policy controle_aporte_conta_corrige on public.controle_aporte_conta
  for update to authenticated
  using ((select privado.e_ativo()) and (select privado.e_admin()))
  with check ((select privado.e_ativo()) and (select privado.e_admin()));

drop policy if exists controle_aporte_aportador_le on public.controle_aporte_aportador;
create policy controle_aporte_aportador_le on public.controle_aporte_aportador
  for select to authenticated using ((select privado.e_ativo()));
drop policy if exists controle_aporte_aportador_cadastra on public.controle_aporte_aportador;
create policy controle_aporte_aportador_cadastra on public.controle_aporte_aportador
  for insert to authenticated
  with check ((select privado.e_ativo()) and (select privado.e_admin()));
drop policy if exists controle_aporte_aportador_corrige on public.controle_aporte_aportador;
create policy controle_aporte_aportador_corrige on public.controle_aporte_aportador
  for update to authenticated
  using ((select privado.e_ativo()) and (select privado.e_admin()))
  with check ((select privado.e_ativo()) and (select privado.e_admin()));
drop policy if exists controle_aporte_aportador_tira on public.controle_aporte_aportador;
create policy controle_aporte_aportador_tira on public.controle_aporte_aportador
  for delete to authenticated
  using ((select privado.e_ativo()) and (select privado.e_admin()));

drop policy if exists controle_aporte_atribuicao_le on public.controle_aporte_atribuicao;
create policy controle_aporte_atribuicao_le on public.controle_aporte_atribuicao
  for select to authenticated using ((select privado.e_ativo()));
drop policy if exists controle_aporte_atribuicao_cadastra on public.controle_aporte_atribuicao;
create policy controle_aporte_atribuicao_cadastra on public.controle_aporte_atribuicao
  for insert to authenticated
  with check ((select privado.e_ativo()) and (select privado.e_admin()));
drop policy if exists controle_aporte_atribuicao_corrige on public.controle_aporte_atribuicao;
create policy controle_aporte_atribuicao_corrige on public.controle_aporte_atribuicao
  for update to authenticated
  using ((select privado.e_ativo()) and (select privado.e_admin()))
  with check ((select privado.e_ativo()) and (select privado.e_admin()));
drop policy if exists controle_aporte_atribuicao_tira on public.controle_aporte_atribuicao;
create policy controle_aporte_atribuicao_tira on public.controle_aporte_atribuicao
  for delete to authenticated
  using ((select privado.e_ativo()) and (select privado.e_admin()));

notify pgrst, 'reload schema';

commit;

-- Reverter (primeiro volte o app; GUARDE antes:
--   select * from public.controle_aporte_conta;
--   select * from public.controle_aporte_aportador;
--   select * from public.controle_aporte_atribuicao;):
--   drop table if exists public.controle_aporte_atribuicao;
--   drop table if exists public.controle_aporte_aportador;
--   drop table if exists public.controle_aporte_conta;
--   drop function if exists privado.controle_aporte_carimbo();
```

- [ ] **Passo 4:**
  ```
  python -m pytest tests/test_tela_do_dia_controle_sql.py tests/test_rls_supabase.py -q
  ```
  → PASS.

- [ ] **Passo 5 (só o coordenador, FORA do repositório): o arquivo da raiz**

  É a migration inteira seguida do bloco de dados abaixo. Para montar no Git Bash:
  ```bash
  W="/c/AUTOMAÇÕES MAIS CONTROLE/_worktrees/app-pagamentos-do-dia-2"
  R="/c/AUTOMAÇÕES MAIS CONTROLE/APLICAR NO SUPABASE - 2026-10-22 controle de aportes.sql"
  { echo "-- APLICAR NO SUPABASE - 2026-10-22 - controle de aportes"
    echo "-- PARTE 1: estrutura (copia byte a byte da migration 20261022130000)"
    cat "$W/supabase/migrations/20261022130000_controle_de_aportes.sql"
    echo; echo "-- PARTE 2: dados de abertura (PREENCHER os tres nomes antes de rodar)"
  } > "$R"
  ```
  Depois, acrescente ao final do arquivo o bloco abaixo e troque os três marcadores pelos valores reais, num editor, fora do repositório:

```sql
-- Antes de preencher, confira os nomes EXATOS:
--   conta:   no Mais Controle, tela Contas (o nome como esta la);
--   socios:  o Cliente dos recebimentos de aporte de cada um. Normalmente e o
--            nome_oficial da Pagou/Recebeu da aba Aportes:
--              select nome_exibicao, nome_oficial from public.entidade
--               where conta is null order by 1;
-- Abertura = 21/10/2026, meio a meio. "O devedor deve R$ 50.000,00 para
-- igualar" vira: socio EM DIA com 50.000,00 ja aportado antes da abertura e
-- o DEVEDOR com 0 (com 1:1, para igualar = 50.000 x 1/1 - 0 = 50.000).
-- Os recebimentos de 21/10 ENTRAM na conta (startDate inclusivo).
do $$
declare
  v_conta  text := '<<CONTA_MAE_NO_ERP>>';
  v_em_dia text := '<<SOCIO_EM_DIA_NOME_COMPLETO_NO_ERP>>';
  v_deve   text := '<<SOCIO_QUE_DEVE_NOME_COMPLETO_NO_ERP>>';
  v_id     bigint;
begin
  if v_conta like '<<%' or v_em_dia like '<<%' or v_deve like '<<%' then
    raise exception 'Preencha os tres nomes (conta e os dois socios) antes de rodar.';
  end if;
  if upper(trim(v_em_dia)) = upper(trim(v_deve)) then
    raise exception 'Os dois socios estao com o mesmo nome.';
  end if;
  if not exists (select 1 from public.perfil where papel = 'admin' and situacao = 'ativo') then
    raise exception 'Nenhum administrador ativo: ninguem conseguiria editar a aba.';
  end if;
  insert into public.controle_aporte_conta (conta_erp, abertura, observacao)
  values (trim(v_conta), date '2026-10-21',
          'Abertura: o devedor deve R$ 50.000,00 para igualar; meio a meio.')
  on conflict (conta_erp) do nothing
  returning id into v_id;
  if v_id is null then
    raise exception 'A conta ja esta no controle -- confira antes de rodar de novo.';
  end if;
  insert into public.controle_aporte_aportador (conta_id, nome_erp, peso, abertura)
  values (v_id, trim(v_em_dia), 1, 50000.00),
         (v_id, trim(v_deve),   1,     0.00);
end
$$;

-- Conferencia (tem de mostrar 1 conta e 2 aportadores, 50.000,00 e 0,00):
select c.conta_erp, c.abertura, a.nome_erp, a.peso, a.abertura
  from public.controle_aporte_conta c
  join public.controle_aporte_aportador a on a.conta_id = c.id
 order by a.abertura desc;
```

- [ ] **Passo 6:** o revisor de SQL revisa os dois arquivos, e o coordenador aplica pelo CLI antes de liberar.

- [ ] **Passo 7: commit**
  ```
  git add supabase/migrations/20261022130000_controle_de_aportes.sql tests/test_tela_do_dia_controle_sql.py
  git commit -m "Controle de aportes: tabelas na nuvem, leitura liberada e escrita só do admin" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  ```

---

## Tarefa 2: Núcleo puro, parte 1: dados, leitura do item do ERP, validação e "quem deve quanto"

**MODELO:** sonnet

**Files:**
- Create: `tela_do_dia/controle_aportes.py`
- Create: `tests/test_tela_do_dia_controle.py`

**Interfaces (conferidas):**
- `aportes.regras.como_dinheiro(valor) -> Decimal` (`aportes/regras.py:107`).
- `problema_dos_pesos(investidores, pesos) -> str` (`:205`). Atenção: `peso_de` (`:196`) faz `Decimal(str(peso))`, então **peso `None` tem de ser barrado antes** (`str(None)` vira `"None"` e levanta `InvalidOperation`).
- `util.norm_espaco(s) -> str` (`util.py:230`).
- `tela_do_dia.valores.brl(valor) -> str` (`tela_do_dia/valores.py:40`, que dá "R$ 50.000,00").

- [ ] **Passo 1 (RED): os testes**

```python
# tests/test_tela_do_dia_controle.py
# -*- coding: utf-8 -*-
"""Controle de aportes (`tela_do_dia/controle_aportes.py`). Sem tela, sem rede.

Nomes fictícios: o repositório é público. Os dois aportadores têm o MESMO
primeiro nome de propósito — são pessoas diferentes e nunca se misturam."""
import datetime
from dataclasses import replace
from decimal import Decimal

import pytest

from tela_do_dia import controle_aportes as ca

D = Decimal
ZERO = D("0.00")
ABRE = datetime.date(2026, 10, 21)
HOJE = datetime.date(2026, 10, 23)
ALFA, BETA = "FULANO ALFA DA SILVA", "FULANO BETA SOUZA"


def _conta(alfa_abertura="50000.00", beta_abertura="0.00", pesos=("1", "1")):
    return ca.ContaControlada(
        conta_erp="CONTA MAE - BANCO", abertura=ABRE, id=1, aportadores=(
            ca.Aportador(ALFA, D(pesos[0]), D(alfa_abertura), id=10),
            ca.Aportador(BETA, D(pesos[1]), D(beta_abertura), id=11)))


def _rec(ident, valor, cliente, data=HOJE):
    return ca.Recebimento(id=ident, data=data, valor=D(valor), cliente=cliente)


def test_recebimento_do_erp_le_os_campos_que_a_aba_contratos_ja_le():
    r = ca.recebimento_do_erp(
        {"id": "r1", "dateOfReceipt": "2026-10-22T00:00:00", "sumOfReceivedValues": 1500.5,
         "customerName": f" {ALFA} ", "description": "APORTE CAPITAL - X PARA Y",
         "workName": "CENTRO FICTICIO"}, "Aporte de Capital")
    assert r == ca.Recebimento(id="r1", data=datetime.date(2026, 10, 22), valor=D("1500.50"),
                               cliente=ALFA, natureza="Aporte de Capital",
                               descricao="APORTE CAPITAL - X PARA Y", centro="CENTRO FICTICIO")


@pytest.mark.parametrize("item", [
    {"dateOfReceipt": "2026-10-22", "sumOfReceivedValues": 1},
    {"id": "r", "sumOfReceivedValues": 1},
    {"id": "r", "dateOfReceipt": "2026-10-22"},
    {"id": "r", "dateOfReceipt": "2026-10-22", "sumOfReceivedValues": "abc"},
    {"id": "r", "dateOfReceipt": "2026-10-22", "sumOfReceivedValues": float("nan")},
    {"id": "r", "dateOfReceipt": "2026-10-22", "sumOfReceivedValues": True},
])
def test_recebimento_ilegivel_levanta_e_nunca_vira_zero(item):
    with pytest.raises(ValueError):
        ca.recebimento_do_erp(item)


def test_problemas_da_conta():
    assert ca.problemas_da_conta(_conta(), HOJE) == []
    assert ca.problemas_da_conta(_conta(), HOJE, [_conta()]) == []   # ela mesma não é outra
    texto = lambda c, outras=(): " ".join(ca.problemas_da_conta(c, HOJE, outras))  # noqa: E731
    assert "depois de hoje" in texto(replace(_conta(), abertura=HOJE + datetime.timedelta(days=1)))
    assert "repetido" in texto(replace(_conta(), aportadores=(
        ca.Aportador(ALFA, D(1)), ca.Aportador("fulano álfa da  silva", D(1)))))
    assert "Falta aportador" in texto(replace(_conta(), aportadores=()))
    assert "Proporção" in texto(replace(_conta(), aportadores=(
        ca.Aportador(ALFA, D(0)), ca.Aportador(BETA, D(1)))))
    assert "Proporção" in texto(replace(_conta(), aportadores=(
        ca.Aportador(ALFA, None), ca.Aportador(BETA, D(1)))))
    assert "inválido" in texto(_conta(alfa_abertura="-1.00"))
    assert "já está no controle" in texto(replace(_conta(), id=2), [_conta()])
    assert "nome da conta" in texto(replace(_conta(), conta_erp="  "))


def test_aberturas_para_divida_meio_a_meio():
    assert ca.aberturas_para_divida(_conta().aportadores, "Fulano Beta  Souza", D("50000")) \
        == {ALFA: D("50000.00"), BETA: ZERO}


def test_aberturas_para_divida_recusa_primeiro_nome_e_negativo():
    with pytest.raises(ValueError):
        ca.aberturas_para_divida(_conta().aportadores, "FULANO", D("1"))
    with pytest.raises(ValueError):
        ca.aberturas_para_divida(_conta().aportadores, BETA, D("-1"))
```

- [ ] **Passo 2:** `python -m pytest tests/test_tela_do_dia_controle.py -q` → FAIL (falta o módulo).

- [ ] **Passo 3 (GREEN): o módulo**

```python
# tela_do_dia/controle_aportes.py
# -*- coding: utf-8 -*-
"""Controle de aportes: quanto cada aportador pôs em cada conta desde a
abertura, quanto deveria pela proporção e quem deve quanto para igualar.
Sem tela e sem rede — a aba (`controle_frame.py`) só mostra o que sai daqui.

A conta, numa frase: `aportou` = o já aportado antes da abertura + os
recebimentos de aporte do ERP desde a abertura; o NÍVEL é o maior
`aportou ÷ parte`; `deveria` = nível × parte; `para igualar` = deveria −
aportou. Com dois aportadores meio a meio, "A já pôs 50 mil a mais que B"
vira "B deve R$ 50.000,00 para igualar" — a conta que o dono faz de cabeça.

Quem é o aportador de um recebimento: o Cliente dele no ERP (`customerName`),
pelo nome COMPLETO (`util.norm_espaco`: sem acento, caixa e espaço dobrado),
contra os aportadores DAQUELA conta. Nunca por primeiro nome nem por pedaço:
dois aportadores com o mesmo primeiro nome são pessoas diferentes. O que não
casa vai para `sem_dono`, para o dono apontar — nunca some.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import util
from aportes.regras import como_dinheiro, problema_dos_pesos

ZERO = Decimal("0.00")
CENTAVO = Decimal("0.01")


@dataclass(frozen=True)
class Aportador:
    nome_erp: str                 # o Cliente no ERP, nome completo
    peso: Decimal                 # parte (peso: 1 e 1 = meio a meio)
    abertura: Decimal = ZERO      # já aportado ANTES da abertura (>= 0)
    id: int | None = None


@dataclass(frozen=True)
class ContaControlada:
    conta_erp: str                # nome da conta no ERP, letra por letra
    abertura: datetime.date       # primeiro dia contado (inclusive)
    aportadores: tuple = ()
    id: int | None = None
    ativa: bool = True


@dataclass(frozen=True)
class Recebimento:
    id: str
    data: datetime.date
    valor: Decimal
    cliente: str
    natureza: str = ""
    descricao: str = ""
    centro: str = ""


@dataclass(frozen=True)
class Apontamento:
    recebimento_id: str
    aportador_id: int | None      # None = "não é aporte desta conta"
    valor: Decimal                # o valor do recebimento quando foi apontado
    motivo: str
    id: int | None = None


def _dinheiro_do_erp(valor) -> Decimal:
    if valor is None or isinstance(valor, bool) or str(valor).strip() == "":
        raise ValueError("sem valor recebido")
    try:
        d = Decimal(str(valor))
    except InvalidOperation:
        raise ValueError(f"valor ilegível: {valor!r}") from None
    if not d.is_finite():
        raise ValueError(f"valor ilegível: {valor!r}")
    return d.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def recebimento_do_erp(item: dict, natureza: str = "") -> Recebimento:
    """Um item de `receipt-installments`, com os campos que a aba Contratos já
    lê em produção (`contratos/regras.py:183-212`). Levanta `ValueError` sem
    id, data ou valor: recebimento que não se lê não pode virar zero."""
    item = item if isinstance(item, dict) else {}
    ident = str(item.get("id") or "").strip()
    if not ident:
        raise ValueError("recebimento sem id")
    try:
        data = datetime.date.fromisoformat(str(item.get("dateOfReceipt") or "")[:10])
    except ValueError:
        raise ValueError(f"recebimento {ident} sem data de recebimento") from None
    try:
        valor = _dinheiro_do_erp(item.get("sumOfReceivedValues"))
    except ValueError as e:
        raise ValueError(f"recebimento {ident}: {e}") from None
    return Recebimento(id=ident, data=data, valor=valor,
                       cliente=str(item.get("customerName") or "").strip(),
                       natureza=natureza,
                       descricao=str(item.get("description") or "").strip(),
                       centro=str(item.get("workName") or "").strip())


def problemas_da_conta(conta: ContaControlada, hoje: datetime.date, outras=()) -> list[str]:
    """[] quando a conta pode ser gravada e apurada; senão, os motivos."""
    erros: list[str] = []
    nome = (conta.conta_erp or "").strip()
    if not nome:
        erros.append("Falta o nome da conta, como está no Mais Controle.")
    elif any(util.norm_espaco(o.conta_erp) == util.norm_espaco(nome) and o.id != conta.id
             for o in outras):
        erros.append(f'A conta "{nome}" já está no controle.')
    if conta.abertura > hoje:
        erros.append("A abertura não pode ser depois de hoje.")
    nomes = [(a.nome_erp or "").strip() for a in conta.aportadores]
    if not nomes or not all(nomes):
        erros.append("Falta aportador: o nome COMPLETO, como está no Contato do Mais Controle.")
    elif len({util.norm_espaco(n) for n in nomes}) != len(nomes):
        erros.append("Aportador repetido.")
    elif any(a.peso is None for a in conta.aportadores):
        erros.append("Proporção: falta a parte de alguém.")
    else:
        problema = problema_dos_pesos(nomes, {n: a.peso for n, a in zip(nomes, conta.aportadores)})
        if problema:
            erros.append(f"Proporção: {problema}.")
    for a in conta.aportadores:
        ab = a.abertura
        if (not isinstance(ab, Decimal) or not ab.is_finite() or ab < 0
                or ab != ab.quantize(CENTAVO)):
            erros.append(f"Já aportado antes da abertura de {a.nome_erp}: valor inválido.")
    return erros


def aberturas_para_divida(aportadores, devedor: str, valor) -> dict:
    """"FULANO deve R$ V para igualar" -> o já aportado antes da abertura de
    cada um: o devedor com 0, cada outro com V × parte dele ÷ parte do devedor
    (todos os outros no mesmo nível). Com partes que não dividem exato, a
    dívida pode sair um centavo diferente — a tela mostra o resultado."""
    valor = como_dinheiro(valor)
    if valor < 0:
        raise ValueError("A dívida não pode ser negativa.")
    alvo = util.norm_espaco(devedor)
    achados = [a for a in aportadores if util.norm_espaco(a.nome_erp) == alvo]
    if len(achados) != 1:
        raise ValueError("Escolha o devedor entre os aportadores, pelo nome completo.")
    parte_devedor = Decimal(achados[0].peso)
    return {a.nome_erp: (ZERO if a is achados[0]
                         else como_dinheiro(valor * Decimal(a.peso) / parte_devedor))
            for a in aportadores}
```

- [ ] **Passo 4:** `python -m pytest tests/test_tela_do_dia_controle.py -q` → PASS.

- [ ] **Passo 5:**
  ```
  ruff check --select E9,F tela_do_dia/controle_aportes.py tests/test_tela_do_dia_controle.py
  vermin --target=3.11 --no-tips --violations tela_do_dia/controle_aportes.py
  ```

- [ ] **Passo 6: commit**
  ```
  git add tela_do_dia/controle_aportes.py tests/test_tela_do_dia_controle.py
  git commit -m "Controle de aportes: dados, leitura do recebimento e a dívida de abertura" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  ```

---

## Tarefa 3: Núcleo puro, parte 2: apurar (identificação, apontamentos, deveria, diferença)

**MODELO:** opus (regra de dinheiro)

**Files:**
- Modify: `tela_do_dia/controle_aportes.py` (acrescenta)
- Modify: `tests/test_tela_do_dia_controle.py` (acrescenta)

**Interfaces (conferidas):**
- `aportes.regras.percentuais_dos_pesos(investidores, pesos) -> list[Decimal]` (`aportes/regras.py:252`).
- `como_dinheiro` (`:107`).
- `tela_do_dia.valores.brl` (`valores.py:40`).

- [ ] **Passo 1 (RED): os testes, acrescentados**

```python
def test_so_a_abertura_quem_esta_em_dia_nao_deve_e_o_outro_deve_tudo():
    ap = ca.apurar(_conta(), [], [], HOJE)
    a, b = ap.linhas
    assert (a.aportou, a.deveria, a.diferenca) == (D("50000.00"), D("50000.00"), ZERO)
    assert (b.aportou, b.deveria, b.diferenca) == (ZERO, D("50000.00"), D("50000.00"))
    assert ca.resumo(ap) == [f"CONTA MAE - BANCO: {BETA} deve R$ 50.000,00 para igualar."]
    assert [str(l.parte) for l in ap.linhas] == ["50.00", "50.00"]


def test_aporte_do_devedor_abate_e_o_que_passa_vira_divida_do_outro():
    ap = ca.apurar(_conta(), [_rec("r1", "20000.00", BETA)], [], HOJE)
    assert ap.linhas[1].diferenca == D("30000.00") and ap.total == D("70000.00")
    ap = ca.apurar(_conta(), [_rec("r1", "60000.00", BETA)], [], HOJE)
    assert [l.diferenca for l in ap.linhas] == [D("10000.00"), ZERO]
    assert ca.situacao_do_aportador(ap.linhas[1]) == "em dia"


def test_primeiro_nome_nao_casa_e_vai_para_sem_dono():
    ap = ca.apurar(_conta(), [_rec("r1", "100.00", "FULANO"),
                              _rec("r2", "100.00", "Fulano Álfa da  Silva")], [], HOJE)
    assert [s.recebimento.id for s in ap.sem_dono] == ["r1"]
    assert "não é aportador" in ap.sem_dono[0].motivo
    assert (ap.linhas[0].do_erp, ap.linhas[1].do_erp) == (D("100.00"), ZERO)


def test_dois_aportadores_de_mesmo_primeiro_nome_nao_se_misturam():
    ap = ca.apurar(_conta(), [_rec("r1", "10.00", BETA), _rec("r2", "5.00", ALFA)], [], HOJE)
    assert [l.do_erp for l in ap.linhas] == [D("5.00"), D("10.00")]


def test_sem_cliente_e_valor_zero_vao_para_sem_dono():
    ap = ca.apurar(_conta(), [_rec("r1", "10.00", ""), _rec("r2", "0.00", ALFA)], [], HOJE)
    motivos = {s.recebimento.id: s.motivo for s in ap.sem_dono}
    assert "sem Cliente" in motivos["r1"] and "zero" in motivos["r2"]
    assert ap.linhas[0].do_erp == ZERO
    assert any("sem dono" in linha for linha in ca.resumo(ap))


def test_fora_do_periodo_nao_entra():
    ap = ca.apurar(_conta(), [_rec("r1", "10.00", BETA, ABRE - datetime.timedelta(days=1)),
                              _rec("r2", "10.00", BETA, HOJE + datetime.timedelta(days=1)),
                              _rec("r3", "10.00", BETA, ABRE)], [], HOJE)
    assert ap.linhas[1].do_erp == D("10.00")


def test_parcela_repetida_para_a_conta():
    ap = ca.apurar(_conta(), [_rec("r1", "10.00", BETA), _rec("r1", "10.00", BETA)], [], HOJE)
    assert "duas vezes" in ap.erro and ap.linhas == []


def test_apontamento_conta_para_quem_foi_apontado():
    p = ca.Apontamento("r1", 11, D("100.00"), "pix por outra conta")
    ap = ca.apurar(_conta(), [_rec("r1", "100.00", "OUTRA PESSOA")], [p], HOJE)
    assert ap.linhas[1].do_erp == D("100.00") and not ap.sem_dono
    assert ap.apontados[0][2] == BETA


def test_apontamento_com_valor_mudado_volta_para_sem_dono():
    p = ca.Apontamento("r1", 11, D("100.00"), "x")
    ap = ca.apurar(_conta(), [_rec("r1", "150.00", "OUTRA PESSOA")], [p], HOJE)
    motivo = ap.sem_dono[0].motivo
    assert "R$ 100,00" in motivo and "R$ 150,00" in motivo and ap.linhas[1].do_erp == ZERO


def test_nao_e_aporte_fica_fora_da_conta_mas_a_vista():
    p = ca.Apontamento("r1", None, D("100.00"), "devolução")
    ap = ca.apurar(_conta(), [_rec("r1", "100.00", ALFA)], [p], HOJE)
    assert ap.linhas[0].do_erp == ZERO and ap.apontados[0][2] == "" and not ap.sem_dono


def test_apontamento_para_quem_saiu_da_conta_volta_para_sem_dono():
    p = ca.Apontamento("r1", 99, D("100.00"), "x")
    ap = ca.apurar(_conta(), [_rec("r1", "100.00", "OUTRA PESSOA")], [p], HOJE)
    assert "não é mais aportador" in ap.sem_dono[0].motivo


def test_apontamento_de_recebimento_que_sumiu_vira_alerta():
    ap = ca.apurar(_conta(), [], [ca.Apontamento("r9", 11, D("100.00"), "x")], HOJE)
    assert any("R$ 100,00" in a for a in ap.alertas)


def test_conta_com_problema_nao_mostra_numero():
    ap = ca.apurar(replace(_conta(), aportadores=()), [_rec("r1", "1.00", ALFA)], [], HOJE)
    assert ap.erro and ap.linhas == [] and ca.situacao_da_conta(ap).startswith("erro")


@pytest.mark.parametrize("pesos, valor", [(("1", "1"), "50000.00"), (("2", "1"), "100.00"),
                                          (("1", "2"), "100.00"), (("60", "40"), "50000.00")])
def test_aberturas_para_divida_reproduzem_a_divida_na_apuracao(pesos, valor):
    conta = _conta(alfa_abertura="0", pesos=pesos)
    conta = ca.com_aberturas(conta, ca.aberturas_para_divida(conta.aportadores, BETA, D(valor)))
    ap = ca.apurar(conta, [], [], HOJE)
    assert (ap.linhas[0].diferenca, ap.linhas[1].diferenca) == (ZERO, D(valor))
```

- [ ] **Passo 2:** `python -m pytest tests/test_tela_do_dia_controle.py -q` → FAIL.

- [ ] **Passo 3 (GREEN): acrescentar ao módulo**

  Ajuste os imports do topo para:
  ```python
  from dataclasses import dataclass, field, replace
  from aportes.regras import como_dinheiro, percentuais_dos_pesos, problema_dos_pesos
  from .valores import brl
  ```
  E acrescente:

```python
@dataclass(frozen=True)
class LinhaAportador:
    nome: str
    parte: Decimal        # % com 2 casas, só para mostrar
    abertura: Decimal
    do_erp: Decimal
    aportou: Decimal      # abertura + do_erp
    deveria: Decimal      # nível × parte
    diferenca: Decimal    # deveria − aportou (>= 0): quanto falta para igualar


@dataclass(frozen=True)
class SemDono:
    recebimento: Recebimento
    motivo: str


@dataclass
class Apuracao:
    conta: ContaControlada
    linhas: list = field(default_factory=list)
    sem_dono: list = field(default_factory=list)
    #: [(Recebimento, Apontamento, nome do aportador ou "" = não é aporte)]
    apontados: list = field(default_factory=list)
    alertas: list = field(default_factory=list)
    erro: str = ""

    @property
    def total(self) -> Decimal:
        return sum((l.aportou for l in self.linhas), ZERO)


def com_aberturas(conta: ContaControlada, aberturas: dict) -> ContaControlada:
    por_chave = {util.norm_espaco(n): como_dinheiro(v) for n, v in aberturas.items()}
    return replace(conta, aportadores=tuple(
        replace(a, abertura=por_chave.get(util.norm_espaco(a.nome_erp), a.abertura))
        for a in conta.aportadores))


def _linhas(conta: ContaControlada, do_erp: dict) -> list:
    nomes = [a.nome_erp for a in conta.aportadores]
    pesos = {a.nome_erp: Decimal(a.peso) for a in conta.aportadores}
    aportou = {a.nome_erp: como_dinheiro(a.abertura) + do_erp[a.nome_erp]
               for a in conta.aportadores}
    nivel = max(aportou[n] / pesos[n] for n in nomes)
    partes = percentuais_dos_pesos(nomes, pesos)
    saida = []
    for a, parte in zip(conta.aportadores, partes):
        n = a.nome_erp
        # `max`: o arredondamento de nível × parte nunca deixa o líder "devendo"
        # um centavo para si mesmo.
        deveria = max(aportou[n], como_dinheiro(nivel * pesos[n]))
        saida.append(LinhaAportador(nome=n, parte=parte, abertura=como_dinheiro(a.abertura),
                                    do_erp=do_erp[n], aportou=aportou[n], deveria=deveria,
                                    diferenca=deveria - aportou[n]))
    return saida


def apurar(conta: ContaControlada, recebimentos, apontamentos, hoje: datetime.date) -> Apuracao:
    """A conta de UMA conta. Conta com cadastro ruim ou leitura duvidosa sai
    com `erro` e SEM linhas — nunca números pela metade."""
    ap = Apuracao(conta=conta)
    problemas = problemas_da_conta(conta, hoje)
    if problemas:
        ap.erro = " ".join(problemas)
        return ap
    por_chave = {util.norm_espaco(a.nome_erp): a for a in conta.aportadores}
    por_id = {a.id: a for a in conta.aportadores if a.id is not None}
    do_erp = {a.nome_erp: ZERO for a in conta.aportadores}
    apontado = {p.recebimento_id: p for p in apontamentos}
    vistos: set = set()
    for r in sorted(recebimentos, key=lambda x: (x.data, x.id)):
        if r.id in vistos:
            ap.erro = (f"o recebimento {r.id} veio duas vezes do Mais Controle — leitura "
                       "não confiável, nenhum número desta conta foi mostrado")
            ap.linhas, ap.sem_dono, ap.apontados = [], [], []
            return ap
        vistos.add(r.id)
        if r.data < conta.abertura or r.data > hoje:
            continue                 # o ERP já devia ter filtrado; aqui não entra
        p = apontado.get(r.id)
        if p is not None:
            if como_dinheiro(p.valor) != r.valor:
                ap.sem_dono.append(SemDono(r, f"apontado com {brl(p.valor)}; agora é "
                                              f"{brl(r.valor)} no Mais Controle — aponte de novo"))
                continue
            if p.aportador_id is None:
                ap.apontados.append((r, p, ""))
                continue
            dono = por_id.get(p.aportador_id)
            if dono is None:
                ap.sem_dono.append(SemDono(r, "apontado para quem não é mais aportador "
                                              "desta conta — aponte de novo"))
                continue
            do_erp[dono.nome_erp] += r.valor
            ap.apontados.append((r, p, dono.nome_erp))
            continue
        if r.valor <= 0:
            ap.sem_dono.append(SemDono(r, "valor zero ou negativo no Mais Controle"))
            continue
        dono = por_chave.get(util.norm_espaco(r.cliente))
        if dono is None:
            ap.sem_dono.append(SemDono(r, "recebimento sem Cliente no Mais Controle"
                                          if not r.cliente else
                                          f'o Cliente "{r.cliente}" não é aportador desta conta'))
            continue
        do_erp[dono.nome_erp] += r.valor
    for p in apontamentos:
        if p.recebimento_id not in vistos:
            ap.alertas.append(f"apontamento de um recebimento de {brl(p.valor)} que não veio "
                              "do Mais Controle — foi apagado ou mudou de conta? confira")
    ap.linhas = _linhas(conta, do_erp)
    return ap


def situacao_do_aportador(linha: LinhaAportador) -> str:
    return "em dia" if linha.diferenca <= 0 else f"deve {brl(linha.diferenca)} para igualar"


def situacao_da_conta(ap: Apuracao) -> str:
    if ap.erro:
        return f"erro: {ap.erro}"
    partes = [f"desde {ap.conta.abertura:%d/%m/%Y}"]
    if ap.sem_dono:
        partes.append(f"{len(ap.sem_dono)} sem dono")
    return " · ".join(partes)


def resumo(ap: Apuracao) -> list:
    nome = ap.conta.conta_erp
    if ap.erro:
        return [f"{nome}: {ap.erro}"]
    devem = [l for l in ap.linhas if l.diferenca > 0]
    saida = ([f"{nome}: {l.nome} deve {brl(l.diferenca)} para igualar." for l in devem]
             or [f"{nome}: todos em dia pela proporção."])
    if ap.sem_dono:
        soma = sum((s.recebimento.valor for s in ap.sem_dono), ZERO)
        saida.append(f"{nome}: {len(ap.sem_dono)} recebimento(s) sem dono ({brl(soma)}) "
                     "fora da conta até você apontar.")
    return saida
```

- [ ] **Passo 4:** `python -m pytest tests/test_tela_do_dia_controle.py -q` → PASS. Rode também `ruff` e `vermin` como na Tarefa 2.

- [ ] **Passo 5: commit**
  ```
  git commit -am "Controle de aportes: a conta de quem deve quanto para igualar e a lista sem dono" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  ```

---

## Tarefa 4: Leitura do ERP com os filtros conferidos e a orquestração pura

**MODELO:** opus (filtro do ERP ignorado em silêncio é dinheiro errado com cara de certo)

**Files:**
- Create: `tela_do_dia/controle_erp.py`
- Create: `tests/test_tela_do_dia_controle_erp.py`
- Modify: `tela_do_dia/controle_aportes.py` (acrescenta `Par`, `pares_para_ler`, `conta_de_contraprova`, `recebimentos_de`, `apurar_tudo`)

**Interfaces (conferidas):**
- `MCApi._fetch_json(url, headers)` (`anexar/mc_api.py:411`).
- `MCApi._base_legacy(caminho) -> (url, headers)`, que exige `_req_pagos` (`:677`).
- `MCApi._base_erp(caminho)`, que exige `_req_anexos` (`:685`).
- `MCApi.capturar_credenciais(log) -> bool` (`:299`) e `garantir_credenciais_anexos(log, dias=365) -> bool` (`:362`).
- A paginação `page`/`size` com fim em `last` (`:719-735`); a lista de naturezas não é paginada (`aportes/mc_catalogos.py:384-389`).
- `ErpError` (`conciliacao/errors.py:10`) e `ErpAccount(id, name, ...)` (`conciliacao/models.py:75`).

- [ ] **Passo 1 (RED): os testes**

```python
# tests/test_tela_do_dia_controle_erp.py
# -*- coding: utf-8 -*-
"""Recebimentos de aporte pelo Chrome do app — só GET. Dublês; contas fictícias."""
import datetime
from dataclasses import replace
from decimal import Decimal
from urllib.parse import parse_qsl, urlsplit

import pytest

from conciliacao.errors import ErpError
from conciliacao.models import ErpAccount
from tela_do_dia import controle_aportes as ca
from tela_do_dia import controle_erp as ce

ABRE, HOJE = datetime.date(2026, 10, 21), datetime.date(2026, 10, 23)
NATS = [{"id": "n-cap", "name": "Aporte de Capital"},
        {"id": "n-inv", "name": "Aporte de Investidor"}, {"id": "n-venda", "name": "Venda"}]
PAR_A = ca.Par("CONTA A - BANCO", "id-a", "CONTA A - BANCO", ABRE)
PAR_B = ca.Par("CONTA B - BANCO", "id-b", "CONTA B - BANCO", ABRE)


def _item(ident, valor=100.0, cliente="FULANO ALFA DA SILVA", **extra):
    return dict({"id": ident, "dateOfReceipt": "2026-10-22", "sumOfReceivedValues": valor,
                 "customerName": cliente}, **extra)


class Api:
    def __init__(self, recebimentos, naturezas=NATS, erro=None):
        self._req_pagos = ("https://legacy/x", {"authorization": "a"})
        self._req_anexos = ("https://erp/attachments/v2", {"authorization": "b"})
        self.recebimentos, self.naturezas, self.erro, self.urls = recebimentos, naturezas, erro, []

    def _base_legacy(self, caminho):
        return f"https://legacy/maiscontrole/services/{caminho}", {"authorization": "a"}

    def _base_erp(self, caminho):
        return f"https://erp/{caminho}", {"authorization": "b"}

    def capturar_credenciais(self, log=print):
        return True

    def garantir_credenciais_anexos(self, log=print):
        return True

    def _fetch_json(self, url, headers):
        self.urls.append(url)
        if url.startswith("https://erp/natures"):
            return self.naturezas
        if self.erro:
            return {"__erro": self.erro}
        q = dict(parse_qsl(urlsplit(url).query))
        itens = self.recebimentos.get((q["accountIds"], q["natureIds"]), [])
        pagina, tam = int(q["page"]), int(q["size"])
        return {"content": itens[pagina * tam:(pagina + 1) * tam],
                "last": (pagina + 1) * tam >= len(itens)}


def test_pede_conta_natureza_e_data_de_recebimento_e_pagina_por_page_size():
    api = Api({("id-a", "n-cap"): [_item(f"r{i}") for i in range(450)]})
    crus = ce.ler_recebimentos(api, [PAR_A], HOJE)
    assert len(crus["CONTA A - BANCO"]["Aporte de Capital"]) == 450
    assert crus["CONTA A - BANCO"]["Aporte de Investidor"] == []
    primeira = [u for u in api.urls if "receipt-installments" in u][0]
    q = dict(parse_qsl(urlsplit(primeira).query))
    assert q == {"startDate": "2026-10-21", "endDate": "2026-10-23",
                 "dateField": "DATE_OF_RECEIPT", "type": "PAID", "accountIds": "id-a",
                 "natureIds": "n-cap", "page": "0", "size": "200"}
    assert not any("pageIndex" in u or "users/login" in u for u in api.urls)


def test_natureza_que_falta_ou_repete_para():
    with pytest.raises(ErpError, match="Aporte de Investidor"):
        ce.ids_das_naturezas(Api({}, naturezas=NATS[:1]))
    with pytest.raises(ErpError, match="duas vezes"):
        ce.ids_das_naturezas(Api({}, naturezas=NATS + [{"id": "n-x", "name": "APORTE DE CAPITAL"}]))


def test_erro_do_erp_vira_erperror_e_nunca_lista_vazia():
    with pytest.raises(ErpError, match="403"):
        ce.ler_recebimentos(Api({}, erro=403), [PAR_A], HOJE)


def test_mais_de_50_paginas_para(monkeypatch):
    monkeypatch.setattr(ce, "POR_PAGINA", 1)
    api = Api({("id-a", "n-cap"): [_item(f"r{i}") for i in range(60)]})
    with pytest.raises(ErpError, match="páginas"):
        ce.ler_recebimentos(api, [PAR_A], HOJE)


def test_mesma_parcela_em_duas_contas_e_filtro_de_conta_ignorado():
    api = Api({("id-a", "n-cap"): [_item("r1")], ("id-b", "n-cap"): [_item("r1")]})
    with pytest.raises(ErpError, match="duas contas"):
        ce.ler_recebimentos(api, [PAR_A, PAR_B], HOJE)


def test_mesma_parcela_em_duas_naturezas_e_filtro_de_natureza_ignorado():
    api = Api({("id-a", "n-cap"): [_item("r1")], ("id-a", "n-inv"): [_item("r1")]})
    with pytest.raises(ErpError, match="duas naturezas"):
        ce.ler_recebimentos(api, [PAR_A], HOJE)


def test_contraprova_com_parcela_do_controle_para():
    prova = ca.Par("", "id-z", "CONTA Z", ABRE)
    api = Api({("id-a", "n-cap"): [_item("r1")], ("id-z", "n-cap"): [_item("r1")]})
    with pytest.raises(ErpError, match="contraprova"):
        ce.ler_recebimentos(api, [PAR_A], HOJE, contraprova=prova)
    api = Api({("id-a", "n-cap"): [_item("r1")], ("id-z", "n-cap"): [_item("r2")]})
    assert ce.ler_recebimentos(api, [PAR_A], HOJE, contraprova=prova)


def test_conta_do_item_divergente_para_e_igual_passa():
    api = Api({("id-a", "n-cap"): [_item("r1", accountName="CONTA B - BANCO")]})
    with pytest.raises(ErpError, match="filtro de conta"):
        ce.ler_recebimentos(api, [PAR_A], HOJE)
    api = Api({("id-a", "n-cap"): [_item("r1", accountName="conta a -  banco")]})
    assert ce.ler_recebimentos(api, [PAR_A], HOJE)


# ---- a parte pura que mora em controle_aportes
def _conta(nome="CONTA A - BANCO"):
    return ca.ContaControlada(nome, ABRE, (ca.Aportador("FULANO ALFA DA SILVA", Decimal(1)),), id=1)


def test_pares_para_ler_casa_o_nome_inteiro_da_conta():
    erp = [ErpAccount(id="id-a", name="Conta A - Banco"), ErpAccount(id="id-b", name="CONTA A - BANCO 2")]
    pares, erros = ca.pares_para_ler([_conta()], erp)
    assert pares == [ca.Par("CONTA A - BANCO", "id-a", "Conta A - Banco", ABRE)] and erros == {}
    pares, erros = ca.pares_para_ler([_conta("CONTA C")], erp)
    assert pares == [] and "não está entre as contas" in erros["CONTA C"]
    pares, erros = ca.pares_para_ler([_conta()], erp + [ErpAccount(id="id-c", name="CONTA A - BANCO")])
    assert "duas contas" in erros["CONTA A - BANCO"]


def test_contraprova_e_uma_conta_fora_do_controle():
    erp = [ErpAccount(id="id-a", name="CONTA A - BANCO"), ErpAccount(id="id-z", name="CONTA Z")]
    assert ca.conta_de_contraprova(erp, [PAR_A]) == ca.Par("", "id-z", "CONTA Z", ABRE)
    assert ca.conta_de_contraprova(erp[:1], [PAR_A]) is None


def test_apurar_tudo_isola_o_erro_de_cada_conta():
    contas = [_conta(), _conta("CONTA B - BANCO"), replace(_conta("CONTA C"), id=3)]
    crus = {"CONTA A - BANCO": {"Aporte de Capital": [_item("r1")]},
            "CONTA B - BANCO": {"Aporte de Capital": [{"id": "r2"}]}}
    aps = ca.apurar_tudo(contas, {"CONTA C": "não está entre as contas"}, crus, {}, HOJE)
    assert aps[0].linhas[0].do_erp == Decimal("100.00") and not aps[0].erro
    assert "não se lê" in aps[1].erro and aps[1].linhas == []
    assert aps[2].erro == "não está entre as contas"
```

- [ ] **Passo 2:** `python -m pytest tests/test_tela_do_dia_controle_erp.py -q` → FAIL.

- [ ] **Passo 3 (GREEN): `tela_do_dia/controle_erp.py`**

```python
# -*- coding: utf-8 -*-
"""Os recebimentos de aporte, lidos do Mais Controle pelo Chrome do app. Só GET.

Mesmo endereço e mesma paginação da aba Contratos
(`anexar/mc_api.py:699`, `listar_recebimentos`): `receipt-installments` do
legado, pela aba do robô, com os cabeçalhos que a própria página mandou. NÃO
reaproveita `listar_recebimentos`: ela fixa as naturezas de VENDA e não
filtra conta, e mudá-la mexeria na aba Contratos.

Duas coisas deste endereço não foram medidas em produção, e por isso são
CONFERIDAS em vez de confiadas: se `accountIds` filtra a conta e se
`natureIds` filtra a natureza. Filtro aceito e ignorado em silêncio é o
defeito conhecido da casa (`pageIndex`, `mc_api.py:707-710`). A mesma
parcela em duas contas, em duas naturezas ou na conta de contraprova PARA a
leitura — nada é somado.
"""
from __future__ import annotations

from urllib.parse import urlencode

import util
from aportes.regras import NATUREZA_RECEBIMENTO, TIPO_INVESTIDOR
from conciliacao.errors import ErpError

#: As naturezas que a aba Aportes usa nos recebimentos de aporte
#: (`aportes/regras.py:37-41`). "Outras receitas" (distribuição) fica fora.
NATUREZAS_DE_APORTE = (NATUREZA_RECEBIMENTO["Aporte de Capital"],
                       NATUREZA_RECEBIMENTO[TIPO_INVESTIDOR])
POR_PAGINA = 200
MAX_PAGINAS = 50
_CHAVES_CONTA = ("accountName", "defaultAccountName", "bankAccountName")
_RECADO = "Recarregue o Mais Controle no Chrome do app e atualize de novo."
_NADA = "Nada foi somado."


def _parar_se_erro(corpo, o_que: str) -> None:
    if isinstance(corpo, dict) and corpo.get("__erro"):
        raise ErpError(f"o Mais Controle respondeu {corpo['__erro']} ao {o_que}. {_RECADO}")


def _lista(corpo) -> list:
    if isinstance(corpo, list):
        return corpo
    if isinstance(corpo, dict):
        for campo in ("content", "data", "items", "results"):
            if isinstance(corpo.get(campo), list):
                return corpo[campo]
    return []


def garantir_acesso(api, log=print) -> None:
    if not getattr(api, "_req_pagos", None) and not api.capturar_credenciais(log):
        raise ErpError("a tela de Pagamentos do Chrome do app não deu o acesso aos "
                       f"recebimentos. {_RECADO}")
    if not getattr(api, "_req_anexos", None) and not api.garantir_credenciais_anexos(log):
        raise ErpError(f"o Chrome do app não deu o acesso ao cadastro de naturezas. {_RECADO}")


def ids_das_naturezas(api, nomes=NATUREZAS_DE_APORTE) -> dict:
    """{nome da natureza: id}. Natureza que falta ou repete PARA."""
    base, headers = api._base_erp("natures")
    corpo = api._fetch_json(base, headers)
    _parar_se_erro(corpo, "listar as naturezas")
    por_nome: dict = {}
    for n in _lista(corpo):
        if isinstance(n, dict) and n.get("id") and n.get("name"):
            por_nome.setdefault(util.norm_espaco(n["name"]), []).append(str(n["id"]))
    saida = {}
    for nome in nomes:
        ids = por_nome.get(util.norm_espaco(nome)) or []
        if len(ids) != 1:
            onde = "não existe" if not ids else "aparece duas vezes"
            raise ErpError(f'a natureza "{nome}" {onde} no Mais Controle — sem ela o '
                           "controle não sabe o que é aporte.")
        saida[nome] = ids[0]
    return saida


def recebimentos(api, conta_id: str, natureza_id: str, inicio, fim, log=print) -> list:
    """Os itens crus de UMA conta e UMA natureza, todas as páginas."""
    base, headers = api._base_legacy("receipt-installments")
    todos: list = []
    pagina = 0
    while True:
        params = [("startDate", inicio.isoformat()), ("endDate", fim.isoformat()),
                  ("dateField", "DATE_OF_RECEIPT"), ("type", "PAID"),
                  ("accountIds", conta_id), ("natureIds", natureza_id),
                  ("page", str(pagina)), ("size", str(POR_PAGINA))]
        corpo = api._fetch_json(f"{base}?{urlencode(params)}", headers)
        _parar_se_erro(corpo, "listar os recebimentos de aporte")
        if not isinstance(corpo, dict):
            raise ErpError("o Mais Controle devolveu os recebimentos num formato que não "
                           f"conheço. {_RECADO}")
        lote = corpo.get("content") or []
        todos.extend(lote)
        if corpo.get("last") or not lote:
            return todos
        pagina += 1
        if pagina >= MAX_PAGINAS:
            raise ErpError(f"mais de {MAX_PAGINAS} páginas de recebimentos de aporte: parei "
                           "para não devolver uma lista pela metade.")


def conta_do_item(item) -> str:
    """O nome da conta que o item declara, quando declara; "" quando não."""
    item = item if isinstance(item, dict) else {}
    for chave in _CHAVES_CONTA:
        v = item.get(chave)
        if isinstance(v, str) and v.strip():
            return v.strip()
    conta = item.get("account")
    if isinstance(conta, dict) and str(conta.get("name") or "").strip():
        return str(conta["name"]).strip()
    return ""


def conferir_filtros(crus: dict, nomes_no_erp: dict, contraprova=()) -> None:
    """`crus`: {rótulo: {natureza: [itens]}}. Levanta `ErpError` quando a
    leitura mostra que um filtro foi ignorado."""
    dono: dict = {}
    for rotulo, por_natureza in crus.items():
        alvo = util.norm_espaco(nomes_no_erp.get(rotulo, ""))
        for natureza, itens in por_natureza.items():
            for item in itens:
                ident = str((item or {}).get("id") or "")
                if not ident:
                    continue             # `recebimento_do_erp` recusa depois
                visto = dono.get(ident)
                if visto and visto[0] != rotulo:
                    raise ErpError("a mesma parcela veio em duas contas: o Mais Controle "
                                   f"ignorou o filtro de conta. {_NADA} {_RECADO}")
                if visto and visto[1] != natureza:
                    raise ErpError("a mesma parcela veio em duas naturezas: o Mais Controle "
                                   f"ignorou o filtro de natureza. {_NADA} {_RECADO}")
                dono[ident] = (rotulo, natureza)
                conta = conta_do_item(item)
                if conta and util.norm_espaco(conta) != alvo:
                    raise ErpError(f'pedi os recebimentos de "{nomes_no_erp.get(rotulo)}" e '
                                   f'veio um de "{conta}": o filtro de conta não valeu. {_NADA}')
    if any(str((i or {}).get("id") or "") in dono for i in contraprova):
        raise ErpError("a conta de contraprova devolveu parcelas das contas do controle: o "
                       f"filtro de conta foi ignorado. {_NADA}")


def ler_recebimentos(api, pares, hoje, *, contraprova=None, log=print) -> dict:
    """{rótulo da conta no controle: {natureza: [itens crus]}}, conferido."""
    garantir_acesso(api, log)
    naturezas = ids_das_naturezas(api)
    crus: dict = {}
    for par in pares:
        log(f"Lendo os aportes de {par.nome_no_erp} desde {par.inicio:%d/%m/%Y}...")
        crus[par.rotulo] = {nome: recebimentos(api, par.conta_id, ident, par.inicio, hoje, log)
                            for nome, ident in naturezas.items()}
    prova: list = []
    if contraprova is not None and pares:
        for ident in naturezas.values():
            prova.extend(recebimentos(api, contraprova.conta_id, ident,
                                      contraprova.inicio, hoje, log))
    conferir_filtros(crus, {p.rotulo: p.nome_no_erp for p in pares}, prova)
    return crus
```

- [ ] **Passo 4 (GREEN): acrescentar a `controle_aportes.py`**

```python
@dataclass(frozen=True)
class Par:
    rotulo: str            # conta_erp como está no controle (chave dos resultados)
    conta_id: str          # `ErpAccount.id`
    nome_no_erp: str       # `ErpAccount.name`
    inicio: datetime.date


def pares_para_ler(contas, contas_erp) -> tuple:
    """([Par], {rótulo: motivo}) — a conta do controle casa com UMA conta
    ativa do ERP pelo nome inteiro (`util.norm_espaco`)."""
    pares, erros = [], {}
    for c in contas:
        alvo = util.norm_espaco(c.conta_erp)
        achadas = [e for e in contas_erp if util.norm_espaco(e.name) == alvo]
        if len(achadas) == 1:
            pares.append(Par(c.conta_erp, achadas[0].id, achadas[0].name, c.abertura))
        elif not achadas:
            erros[c.conta_erp] = ("não está entre as contas ativas do Mais Controle (o nome "
                                  "tem de ser o de lá, letra por letra)")
        else:
            erros[c.conta_erp] = ("há duas contas ativas no Mais Controle com esse nome — "
                                  "não dá para saber qual")
    return pares, erros


def conta_de_contraprova(contas_erp, pares):
    """Uma conta ativa FORA do controle, para provar que o filtro de conta vale."""
    usadas = {p.conta_id for p in pares}
    livres = sorted((e for e in contas_erp if e.id and e.id not in usadas),
                    key=lambda e: util.norm_espaco(e.name))
    if not livres or not pares:
        return None
    return Par("", livres[0].id, livres[0].name, min(p.inicio for p in pares))


def recebimentos_de(itens_por_natureza: dict) -> list:
    return [recebimento_do_erp(item, natureza)
            for natureza, itens in itens_por_natureza.items() for item in itens]


def apurar_tudo(contas, erros: dict, crus: dict, apontamentos: dict, hoje) -> list:
    """Uma `Apuracao` por conta; o erro de uma não apaga as outras."""
    saida = []
    for c in contas:
        if c.conta_erp in erros:
            saida.append(Apuracao(conta=c, erro=erros[c.conta_erp]))
            continue
        try:
            recs = recebimentos_de(crus.get(c.conta_erp) or {})
        except ValueError as e:
            saida.append(Apuracao(conta=c, erro=f"recebimento que não se lê no Mais Controle "
                                                f"({e}) — nenhum número desta conta foi mostrado"))
            continue
        saida.append(apurar(c, recs, apontamentos.get(c.id) or [], hoje))
    return saida
```

- [ ] **Passo 5:**
  ```
  python -m pytest tests/test_tela_do_dia_controle.py tests/test_tela_do_dia_controle_erp.py -q
  ```
  → PASS. Rode também `ruff` e `vermin` sobre `tela_do_dia/controle_erp.py` e `tela_do_dia/controle_aportes.py`.

- [ ] **Passo 6: commit**
  ```
  git add tela_do_dia/controle_erp.py tela_do_dia/controle_aportes.py tests/test_tela_do_dia_controle_erp.py
  git commit -m "Controle de aportes: recebimentos de aporte pelo Chrome do app, com os filtros conferidos" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  ```

---

## Tarefa 5: Nuvem: ler, gravar conta e aportadores, apontar e desfazer

**MODELO:** sonnet

**Files:**
- Create: `tela_do_dia/controle_nuvem.py`
- Create: `tests/test_tela_do_dia_controle_nuvem.py`

**Interfaces (conferidas):**
- `nuvem.rest.ler(tabela, token, *, colunas="*", filtro="") -> list` (`nuvem/rest.py:174`).
- `inserir(tabela, token, linhas, *, devolver=True) -> list` (`:182`).
- `alterar(tabela, token, filtro, mudancas) -> list` (`:191`), que recusa filtro vazio.
- `apagar(tabela, token, filtro) -> None` (`:202`).
- `nuvem.auditoria.gravar_agora(acao, detalhe="") -> bool` (`nuvem/auditoria.py:40`), que nunca levanta.
- O padrão "insere antes de apagar" de `aportes/rateio_subconta.py:184-242`. O dublê de banco segue o de `tests/test_aportes_rateio_subconta.py:67-114`.

- [ ] **Passo 1 (RED): os testes**

```python
# tests/test_tela_do_dia_controle_nuvem.py
# -*- coding: utf-8 -*-
"""Controle de aportes na nuvem (`tela_do_dia/controle_nuvem.py`). Dublê do
`nuvem.rest`; nomes fictícios."""
import datetime
from decimal import Decimal
from urllib.parse import unquote

import pytest

from tela_do_dia import controle_aportes as ca
from tela_do_dia import controle_nuvem as cn

D = Decimal
ABRE, HOJE = datetime.date(2026, 10, 21), datetime.date(2026, 10, 23)
ALFA, BETA = "FULANO ALFA DA SILVA", "FULANO BETA SOUZA"


class Banco:
    def __init__(self):
        self.t = {cn.CONTAS: [], cn.APORTADORES: [], cn.APONTAMENTOS: []}
        self.ordem, self._id = [], 0

    @staticmethod
    def _casa(linha, filtro):
        for parte in filter(None, filtro.split("&")):
            campo, _, cond = parte.partition("=")
            op, _, valor = cond.partition(".")
            valor = unquote(valor)
            if op == "eq" and str(linha.get(campo)) != valor:
                return False
            if op == "in" and str(linha.get(campo)) not in valor.strip("()").split(","):
                return False
        return True

    def ler(self, tabela, _tok, colunas="*", filtro=""):
        return [dict(l) for l in self.t[tabela] if self._casa(l, filtro)]

    def inserir(self, tabela, _tok, linhas, devolver=True):
        self.ordem.append(f"inserir {tabela}")
        saida = []
        for l in linhas:
            self._id += 1
            nova = dict(l, id=self._id)
            self.t[tabela].append(nova)
            saida.append(dict(nova))
        return saida

    def alterar(self, tabela, _tok, filtro, mudancas):
        self.ordem.append(f"alterar {tabela}")
        for l in self.t[tabela]:
            if self._casa(l, filtro):
                l.update(mudancas)
        return []

    def apagar(self, tabela, _tok, filtro):
        self.ordem.append(f"apagar {tabela}")
        self.t[tabela] = [l for l in self.t[tabela] if not self._casa(l, filtro)]


@pytest.fixture
def banco(monkeypatch):
    from nuvem import rest
    b = Banco()
    for nome in ("ler", "inserir", "alterar", "apagar"):
        monkeypatch.setattr(rest, nome, getattr(b, nome))
    return b


def _conta(**kw):
    base = dict(conta_erp="CONTA MAE - BANCO", abertura=ABRE, aportadores=(
        ca.Aportador(ALFA, D(1), D("50000.00")), ca.Aportador(BETA, D(1), D("0.00"))))
    base.update(kw)
    return ca.ContaControlada(**base)


def test_grava_conta_nova_com_numero_em_texto_e_le_de_volta(banco):
    anotado = []
    cn.gravar_conta("tok", _conta(), HOJE, anotar=lambda a, d: anotado.append(a))
    assert banco.t[cn.CONTAS][0]["abertura"] == "2026-10-21"
    assert {(l["nome_erp"], l["peso"], l["abertura"]) for l in banco.t[cn.APORTADORES]} == \
        {(ALFA, "1", "50000.00"), (BETA, "1", "0.00")}
    contas, apont = cn.ler("tok")
    assert contas[0].aportadores[0].abertura == D("50000.00") and apont == {}
    assert anotado and "Controle de aportes" in anotado[0]


def test_editar_muda_so_o_que_mudou_e_insere_antes_de_apagar(banco):
    cn.gravar_conta("tok", _conta(), HOJE, anotar=lambda *a: None)
    salva = cn.ler("tok")[0][0]
    banco.ordem.clear()
    nova = ca.ContaControlada(salva.conta_erp, ABRE, id=salva.id, aportadores=(
        ca.Aportador(ALFA, D(1), D("40000.00")), ca.Aportador("CICLANO GAMA", D(1))))
    cn.gravar_conta("tok", nova, HOJE, [salva], anotar=lambda *a: None)
    assert banco.ordem == [f"alterar {cn.CONTAS}", f"inserir {cn.APORTADORES}",
                           f"alterar {cn.APORTADORES}", f"apagar {cn.APORTADORES}"]
    assert {l["nome_erp"] for l in banco.t[cn.APORTADORES]} == {ALFA, "CICLANO GAMA"}


def test_nao_tira_aportador_com_apontamento_e_nao_escreve_nada(banco):
    cn.gravar_conta("tok", _conta(), HOJE, anotar=lambda *a: None)
    salva = cn.ler("tok")[0][0]
    beta = salva.aportadores[1]
    cn.apontar("tok", salva.id, ca.Recebimento("r1", HOJE, D("10.00"), "X"), beta.id, "pix",
               anotar=lambda *a: None)
    banco.ordem.clear()
    sem_beta = ca.ContaControlada(salva.conta_erp, ABRE, (salva.aportadores[0],), id=salva.id)
    with pytest.raises(ValueError, match=BETA):
        cn.gravar_conta("tok", sem_beta, HOJE, [salva], anotar=lambda *a: None)
    assert banco.ordem == []


def test_conta_com_problema_nao_toca_no_banco(banco):
    with pytest.raises(ValueError):
        cn.gravar_conta("tok", _conta(aportadores=()), HOJE, anotar=lambda *a: None)
    assert banco.ordem == []


def test_apontar_insere_e_depois_corrige_o_mesmo_recebimento(banco):
    rec = ca.Recebimento("r/1", HOJE, D("10.00"), "X")
    cn.apontar("tok", 7, rec, 3, "pix", anotar=lambda *a: None)
    cn.apontar("tok", 7, rec, None, "devolução", anotar=lambda *a: None)
    linhas = banco.t[cn.APONTAMENTOS]
    assert len(linhas) == 1 and linhas[0]["aportador_id"] is None
    assert linhas[0]["valor"] == "10.00" and linhas[0]["recebimento_erp"] == "r/1"
    _c, apont = cn.ler("tok")
    assert apont[7][0].motivo == "devolução"
    cn.desfazer("tok", apont[7][0].id, anotar=lambda *a: None)
    assert banco.t[cn.APONTAMENTOS] == []


def test_apontar_sem_motivo_recusa(banco):
    with pytest.raises(ValueError, match="motivo"):
        cn.apontar("tok", 7, ca.Recebimento("r1", HOJE, D("10.00"), "X"), 3, "  ",
                   anotar=lambda *a: None)
```

- [ ] **Passo 2:** `python -m pytest tests/test_tela_do_dia_controle_nuvem.py -q` → FAIL.

- [ ] **Passo 3 (GREEN): o módulo**

```python
# tela_do_dia/controle_nuvem.py
# -*- coding: utf-8 -*-
"""Abertura, proporção e apontamentos do Controle de aportes, na nuvem.

Três tabelas (migration 20261022130000): `controle_aporte_conta`,
`controle_aporte_aportador` e `controle_aporte_atribuicao`. Ler: quem tem
conta liberada; escrever: só administrador (a RLS nega o resto — a tela só
esconde os botões). Números vão como TEXTO, nunca float.

Gravar insere ANTES de apagar (o mesmo de `aportes/rateio_subconta.gravar`):
se a rede cair no meio, sobra um aportador a mais — visível na próxima
leitura —, nunca uma conta sem ninguém.
"""
from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

import util
from aportes.regras import como_dinheiro

from .controle_aportes import Aportador, Apontamento, ContaControlada, problemas_da_conta

CONTAS = "controle_aporte_conta"
APORTADORES = "controle_aporte_aportador"
APONTAMENTOS = "controle_aporte_atribuicao"


def _anotar_na_auditoria(acao: str, detalhe: str) -> None:
    from nuvem import auditoria
    auditoria.gravar_agora(acao, detalhe)


def _dec(valor, o_que: str) -> Decimal:
    try:
        d = Decimal(str(valor))
    except InvalidOperation:
        raise ValueError(f"{o_que} ilegível na nuvem: {valor!r}") from None
    if not d.is_finite():
        raise ValueError(f"{o_que} ilegível na nuvem: {valor!r}")
    return d


def _txt_dinheiro(v) -> str:
    return format(como_dinheiro(v), "f")


def _txt_peso(v) -> str:
    return format(Decimal(v).normalize(), "f")


def contas_das_linhas(contas: list, aportadores: list) -> list:
    saida = []
    for c in sorted(contas, key=lambda x: util.norm_espaco(x.get("conta_erp") or "")):
        deles = sorted((a for a in aportadores if a.get("conta_id") == c["id"]),
                       key=lambda a: a["id"])
        saida.append(ContaControlada(
            conta_erp=str(c["conta_erp"]),
            abertura=datetime.date.fromisoformat(str(c["abertura"])[:10]),
            id=int(c["id"]), ativa=bool(c.get("ativa", True)),
            aportadores=tuple(Aportador(nome_erp=str(a["nome_erp"]),
                                        peso=_dec(a["peso"], "parte"),
                                        abertura=como_dinheiro(_dec(a["abertura"], "já aportado")),
                                        id=int(a["id"])) for a in deles)))
    return saida


def apontamentos_das_linhas(linhas: list) -> dict:
    saida: dict = {}
    for l in linhas:
        saida.setdefault(int(l["conta_id"]), []).append(Apontamento(
            recebimento_id=str(l["recebimento_erp"]),
            aportador_id=None if l.get("aportador_id") is None else int(l["aportador_id"]),
            valor=como_dinheiro(_dec(l["valor"], "valor apontado")),
            motivo=str(l.get("motivo") or ""), id=int(l["id"])))
    return saida


def ler(token: str) -> tuple:
    """([ContaControlada], {conta_id: [Apontamento]}) — como o BANCO tem agora."""
    from nuvem import rest
    contas = rest.ler(CONTAS, token, colunas="id,conta_erp,abertura,ativa")
    aps = rest.ler(APORTADORES, token, colunas="id,conta_id,nome_erp,peso,abertura")
    atrs = rest.ler(APONTAMENTOS, token,
                    colunas="id,conta_id,recebimento_erp,aportador_id,valor,motivo")
    return contas_das_linhas(contas, aps), apontamentos_das_linhas(atrs)


def gravar_conta(token: str, conta: ContaControlada, hoje: datetime.date, outras=(),
                 anotar=None) -> None:
    from nuvem import rest
    erros = problemas_da_conta(conta, hoje, outras)
    if erros:
        raise ValueError(" ".join(erros))
    anotar = anotar or _anotar_na_auditoria
    campos = {"conta_erp": conta.conta_erp.strip(), "abertura": conta.abertura.isoformat(),
              "ativa": bool(conta.ativa)}
    antes, sair = [], []
    if conta.id is not None:
        antes = rest.ler(APORTADORES, token, colunas="id,nome_erp,peso,abertura",
                         filtro=f"conta_id=eq.{int(conta.id)}")
        ficam = {util.norm_espaco(a.nome_erp) for a in conta.aportadores}
        sair = [l for l in antes if util.norm_espaco(l["nome_erp"]) not in ficam]
        if sair:
            # ANTES de escrever qualquer coisa: o banco recusaria o apagar no
            # fim, com a conta e os novos já gravados.
            apontados = {l.get("aportador_id") for l in rest.ler(
                APONTAMENTOS, token, colunas="aportador_id",
                filtro=f"conta_id=eq.{int(conta.id)}")}
            presos = [l["nome_erp"] for l in sair if l["id"] in apontados]
            if presos:
                raise ValueError(f"{', '.join(presos)} tem recebimento(s) apontado(s) nesta "
                                 "conta: desfaça os apontamentos antes de tirá-lo(s).")
    try:
        if conta.id is None:
            ident = int(rest.inserir(CONTAS, token, [campos])[0]["id"])
        else:
            ident = int(conta.id)
            rest.alterar(CONTAS, token, f"id=eq.{ident}", campos)
        por_chave = {util.norm_espaco(l["nome_erp"]): l for l in antes}
        novos, mudados = [], []
        for a in conta.aportadores:
            linha = {"nome_erp": a.nome_erp.strip(), "peso": _txt_peso(a.peso),
                     "abertura": _txt_dinheiro(a.abertura)}
            velho = por_chave.get(util.norm_espaco(a.nome_erp))
            if velho is None:
                novos.append(dict(linha, conta_id=ident))
            elif (velho["nome_erp"] != linha["nome_erp"]
                  or _dec(velho["peso"], "parte") != Decimal(a.peso)
                  or como_dinheiro(_dec(velho["abertura"], "já aportado")) != como_dinheiro(a.abertura)):
                mudados.append((int(velho["id"]), linha))
        if novos:
            rest.inserir(APORTADORES, token, novos, devolver=False)
        for i, linha in mudados:
            rest.alterar(APORTADORES, token, f"id=eq.{i}", linha)
        if sair:
            rest.apagar(APORTADORES, token,
                        "id=in.(" + ",".join(str(int(l["id"])) for l in sair) + ")")
    except Exception as e:
        raise RuntimeError(f"{e}\n\nA gravação parou no meio. Atualize a aba para ver o que "
                           "ficou na nuvem e grave de novo o que você quer.") from e
    anotar("Controle de aportes: conta gravada",
           f"{conta.conta_erp} | abertura {conta.abertura:%d/%m/%Y} | " + "; ".join(
               f"{a.nome_erp} parte {_txt_peso(a.peso)} já aportado {_txt_dinheiro(a.abertura)}"
               for a in conta.aportadores))


def apontar(token: str, conta_id: int, recebimento, aportador_id, motivo: str,
            anotar=None) -> None:
    from nuvem import rest
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Escreva o motivo do apontamento.")
    if recebimento.valor <= 0:
        raise ValueError("Recebimento sem valor não se aponta.")
    corpo = {"aportador_id": None if aportador_id is None else int(aportador_id),
             "valor": _txt_dinheiro(recebimento.valor), "motivo": motivo[:300]}
    filtro = (f"conta_id=eq.{int(conta_id)}"
              f"&recebimento_erp=eq.{quote(recebimento.id, safe='')}")
    achados = rest.ler(APONTAMENTOS, token, colunas="id", filtro=filtro)
    if achados:
        rest.alterar(APONTAMENTOS, token, f"id=eq.{int(achados[0]['id'])}", corpo)
    else:
        rest.inserir(APONTAMENTOS, token, [dict(corpo, conta_id=int(conta_id),
                                                recebimento_erp=recebimento.id)], devolver=False)
    (anotar or _anotar_na_auditoria)(
        "Controle de aportes: recebimento apontado",
        f"conta {int(conta_id)} | recebimento {recebimento.id} | {corpo['valor']} | "
        f"aportador {corpo['aportador_id']} | {motivo[:200]}")


def desfazer(token: str, apontamento_id: int, anotar=None) -> None:
    from nuvem import rest
    rest.apagar(APONTAMENTOS, token, f"id=eq.{int(apontamento_id)}")
    (anotar or _anotar_na_auditoria)("Controle de aportes: apontamento desfeito",
                                     f"apontamento {int(apontamento_id)}")
```

- [ ] **Passo 4:** `python -m pytest tests/test_tela_do_dia_controle_nuvem.py -q` → PASS. Rode também `ruff` e `vermin`.

- [ ] **Passo 5: commit**
  ```
  git add tela_do_dia/controle_nuvem.py tests/test_tela_do_dia_controle_nuvem.py
  git commit -m "Controle de aportes: abertura, proporção e apontamentos na nuvem" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  ```

---

## Tarefa 6: Formulário puro, sugestão da subconta e nomes conhecidos

**MODELO:** sonnet

**Files:**
- Modify: `tela_do_dia/controle_aportes.py`
- Modify: `tests/test_tela_do_dia_controle.py`

**Interfaces (conferidas):**
- `tela_do_dia.valores.ler_valor_editado(texto) -> Decimal` (`valores.py:21`): aceita zero e sinal, e recusa "1500.50" ambíguo.
- `aportes.rateio_subconta.ler_parte(texto) -> str | None` (`aportes/rateio_subconta.py:50`).
- `aportes.regras.numero_da_conta(texto) -> str` (`regras.py:61`) e `peso_de(pesos, investidor)` (`:196`).
- O formato do cache de subcontas `{numero: {"obras", "investidores", "pesos"}, "_obra_padrao": str}` (`nuvem/cadastro.py:186-205`, `aportes/dados.py:81`).
- O formato de `dados.carregar_contas()`: `{exibicao: {"nome_oficial", "conta", "nome_descricao"}}` (`aportes/dados.py:47`).

- [ ] **Passo 1 (RED): os testes, acrescentados**

```python
SUBS = {"_obra_padrao": "X",
        "11111-1": {"investidores": ["INV A LTDA", "INV B LTDA"],
                    "pesos": {"INV A LTDA": "2", "INV B LTDA": "1"}}}


def test_ler_data():
    assert ca.ler_data("21/10/2026") == ca.ler_data("2026-10-21") == ABRE
    for ruim in ("21/10", "31/02/2026", ""):
        with pytest.raises(ValueError):
            ca.ler_data(ruim)


def test_ler_abertura():
    assert ca.ler_abertura("") == ZERO and ca.ler_abertura("0") == ZERO
    assert ca.ler_abertura("50.000,00") == D("50000.00")
    for ruim in ("1500.50", "-1,00"):
        with pytest.raises(ValueError):
            ca.ler_abertura(ruim)


def test_conta_do_formulario_pula_linha_vazia_e_partes_vazias_sao_iguais():
    c = ca.conta_do_formulario(" CONTA MAE - BANCO ", "21/10/2026",
                               [(ALFA, "", "50.000,00"), ("", "", ""), (BETA, "", "")])
    assert c == ca.ContaControlada("CONTA MAE - BANCO", ABRE, (
        ca.Aportador(ALFA, D(1), D("50000.00")), ca.Aportador(BETA, D(1), ZERO)))


def test_conta_do_formulario_recusa_parte_pela_metade_e_linha_sem_nome():
    with pytest.raises(ValueError, match="parte"):
        ca.conta_do_formulario("C", "21/10/2026", [(ALFA, "60", ""), (BETA, "", "")])
    with pytest.raises(ValueError, match="nome"):
        ca.conta_do_formulario("C", "21/10/2026", [("", "1", "10,00")])
    with pytest.raises(ValueError):
        ca.conta_do_formulario("", "21/10/2026", [(ALFA, "1", "")])


def test_do_rateio_da_subconta():
    assert ca.do_rateio_da_subconta("SUBCONTA 11111-1 - SICOOB - INVESTIDOR", SUBS) == (
        ca.Aportador("INV A LTDA", D(2)), ca.Aportador("INV B LTDA", D(1)))
    assert ca.do_rateio_da_subconta("CONTA MAE - BANCO", SUBS) is None


def test_divergencia_do_rateio():
    nome = "SUBCONTA 11111-1 - SICOOB - INVESTIDOR"
    igual = ca.ContaControlada(nome, ABRE, (ca.Aportador("inv a ltda", D(4)),
                                            ca.Aportador("INV B LTDA", D(2))))
    assert ca.divergencia_do_rateio(igual, SUBS) == ""
    outra = replace(igual, aportadores=(ca.Aportador("INV A LTDA", D(1)),
                                        ca.Aportador("INV B LTDA", D(1))))
    assert "11111-1" in ca.divergencia_do_rateio(outra, SUBS)
    assert ca.divergencia_do_rateio(_conta(), SUBS) == ""


def test_nomes_conhecidos_sem_repetir_e_sem_vazio():
    entidades = {"Alfa": {"nome_oficial": ALFA, "conta": None},
                 "Empresa": {"nome_oficial": "EMPRESA FICTICIA LTDA", "conta": "1"},
                 "Vazia": {"nome_oficial": ""}}
    nomes = ca.nomes_conhecidos(entidades, SUBS, [_rec("r1", "1.00", "fulano alfa da silva"),
                                                  _rec("r2", "1.00", "")])
    assert nomes == ["EMPRESA FICTICIA LTDA", ALFA, "INV A LTDA", "INV B LTDA"]


def test_opcoes_de_apontamento_e_descricao():
    assert ca.opcoes_de_apontamento(_conta()) == [(ALFA, 10), (BETA, 11), (ca.NAO_E_APORTE, None)]
    texto = ca.descrever_conta(_conta())
    assert "21/10/2026" in texto and ALFA in texto and "R$ 50.000,00" in texto and "50,00%" in texto
```

- [ ] **Passo 2:** `python -m pytest tests/test_tela_do_dia_controle.py -q` → FAIL.

- [ ] **Passo 3 (GREEN): acrescentar ao módulo**

  Imports a acrescentar no topo:
  ```python
  from aportes import rateio_subconta
  from aportes.regras import numero_da_conta, peso_de
  from .valores import ler_valor_editado
  ```
  E as funções:

```python
NAO_E_APORTE = "Não é aporte desta conta (fica fora da conta)"


def ler_data(texto) -> datetime.date:
    t = str(texto or "").strip()
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(t, formato).date()
        except ValueError:
            pass
    raise ValueError(f'Data inválida: "{t}". Use DD/MM/AAAA, ex.: 21/10/2026.')


def ler_abertura(texto) -> Decimal:
    """O já aportado antes da abertura: vazio é zero; negativo é recusado."""
    t = str(texto or "").strip()
    if not t:
        return ZERO
    valor = ler_valor_editado(t)
    if valor < 0:
        raise ValueError("O já aportado antes da abertura não pode ser negativo.")
    return valor


def conta_do_formulario(conta_erp, abertura, linhas, *, id=None, ativa=True) -> ContaControlada:
    """`linhas`: [(nome, parte, já aportado)] como digitadas. Linha toda
    vazia é pulada; partes vazias em TODOS = partes iguais."""
    nome_conta = str(conta_erp or "").strip()
    if not nome_conta:
        raise ValueError("Escolha a conta, com o nome que ela tem no Mais Controle.")
    data = ler_data(abertura)
    preenchidas = []
    for nome, parte, ja in linhas:
        nome, parte, ja = (str(x or "").strip() for x in (nome, parte, ja))
        if not (nome or parte or ja):
            continue
        if not nome:
            raise ValueError("Há uma linha com parte ou valor e sem o nome do aportador.")
        preenchidas.append((nome, rateio_subconta.ler_parte(parte), ler_abertura(ja)))
    if not preenchidas:
        raise ValueError("Falta pelo menos um aportador.")
    partes = [p for _n, p, _a in preenchidas]
    if all(p is None for p in partes):
        partes = ["1"] * len(preenchidas)
    elif any(p is None for p in partes):
        raise ValueError("Preencha a parte de todos os aportadores, ou de nenhum "
                         "(partes iguais).")
    return ContaControlada(conta_erp=nome_conta, abertura=data, id=id, ativa=ativa,
                           aportadores=tuple(Aportador(nome_erp=n, peso=Decimal(p), abertura=a)
                                             for (n, _p, a), p in zip(preenchidas, partes)))


def do_rateio_da_subconta(conta_erp: str, subcontas: dict):
    """Os aportadores do rateio da subconta (aba Aportes), quando a conta é
    uma subconta de investidor com rateio; senão None. Só SUGESTÃO."""
    numero = numero_da_conta(conta_erp)
    cfg = (subcontas or {}).get(numero) if numero else None
    if not isinstance(cfg, dict) or not cfg.get("investidores"):
        return None
    pesos = cfg.get("pesos") or {}
    saida = []
    for nome in cfg["investidores"]:
        p = peso_de(pesos, nome)
        saida.append(Aportador(nome_erp=str(nome).strip(),
                               peso=p if p is not None else Decimal(1)))
    return tuple(saida)


def _proporcao(aportadores) -> frozenset:
    soma = sum((Decimal(a.peso) for a in aportadores), Decimal(0))
    return frozenset((util.norm_espaco(a.nome_erp),
                      (Decimal(a.peso) / soma).quantize(Decimal("0.000001")))
                     for a in aportadores)


def divergencia_do_rateio(conta: ContaControlada, subcontas: dict) -> str:
    vindos = do_rateio_da_subconta(conta.conta_erp, subcontas)
    if not vindos or not conta.aportadores or any(a.peso is None for a in conta.aportadores):
        return ""
    if _proporcao(vindos) == _proporcao(conta.aportadores):
        return ""
    return (f"a proporção do controle não é a do rateio da subconta "
            f"{numero_da_conta(conta.conta_erp)} (aba Aportes) — confira qual vale")


def nomes_conhecidos(entidades: dict, subcontas: dict, recebimentos=()) -> list:
    """Sugestões para o nome do aportador: o nome oficial da Pagou/Recebeu
    (é o Cliente que a aba Aportes lança), os investidores das subcontas e os
    Clientes que vieram do ERP. Sem repetir, sem vazio."""
    nomes = [str((d or {}).get("nome_oficial") or "") for d in (entidades or {}).values()]
    for cfg in (subcontas or {}).values():
        if isinstance(cfg, dict):
            nomes += [str(n) for n in cfg.get("investidores") or []]
    nomes += [r.cliente for r in recebimentos]
    vistos, saida = set(), []
    for n in sorted((n.strip() for n in nomes if n and n.strip()), key=util.norm_espaco):
        k = util.norm_espaco(n)
        if k not in vistos:
            vistos.add(k)
            saida.append(n)
    return saida


def opcoes_de_apontamento(conta: ContaControlada) -> list:
    return ([(a.nome_erp, a.id) for a in conta.aportadores if a.id is not None]
            + [(NAO_E_APORTE, None)])


def descrever_conta(conta: ContaControlada) -> str:
    nomes = [a.nome_erp for a in conta.aportadores]
    pcts = percentuais_dos_pesos(nomes, {a.nome_erp: a.peso for a in conta.aportadores})
    linhas = [f"Conta: {conta.conta_erp}", f"Abertura: {conta.abertura:%d/%m/%Y}"]
    linhas += [f"• {a.nome_erp} — parte {str(p).replace('.', ',')}% — já aportado antes "
               f"da abertura: {brl(a.abertura)}" for a, p in zip(conta.aportadores, pcts)]
    return "\n".join(linhas)
```

  A ordem esperada no teste de `nomes_conhecidos` é `sorted` por `norm_espaco`: "EMPRESA…", "FULANO…", "INV A…", "INV B…".

- [ ] **Passo 4:** `python -m pytest tests/test_tela_do_dia_controle.py -q` → PASS. Rode também `ruff` e `vermin`.

- [ ] **Passo 5: commit**
  ```
  git commit -am "Controle de aportes: formulário, sugestão do rateio da subconta e nomes conhecidos" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  ```

---

## Tarefa 7: A tela fina `ControleAportesFrame`

**MODELO:** sonnet

**Files:**
- Create: `tela_do_dia/controle_frame.py`
- Modify: `tests/test_abas_em_paralelo.py` (`_CHAMADORES`, `:211-214`)

**Interfaces (conferidas):**
- `AnexarFrame.avisar_se_ocupado(dona, *, aba=None) -> bool` (`anexar/anexar_comprovantes.py:631`).
- `submeter(rotulo, fn, *a, dona=None, **k)` (`:479`) e `garantir_sessao(log=None)`, que devolve a `MCApi` (`:766`).
- `erp_do_dia.ler_saldos(config, api, *, central_ligado=None, logar=None, log=print)` (`tela_do_dia/erp_do_dia.py:74`).
- `conciliacao.config.load_config(path)` (`conciliacao/config.py:71`).
- `nuvem.sessao.token(pasta=None)` (`nuvem/sessao.py:241`).
- Widgets:
  - `Cabecalho(pai, titulo, apoio, trilha=)` (`widgets.py:1358`); `Cartao(pai, titulo, numero)` (`:1164`); `Botao(pai, texto, papel=, command=, state=)` (`:755`);
  - `AreaRolavel` com `.encaixar(*doca)` (`:1543`, `:1654`); `Campo(pai, rotulo, fabrica)` (`:1848`); `BarraExecucao` (`:1096`, com `.lbl`/`.pb`);
  - `estilo_tabela` (`:2693`); `estilo_log` (`:3533`); `registro_elastico` (`:3307`); `recado_de_erro(exc, tentando)` (`:3114`); `barra_de_titulo` (`:716`).
- Reaproveitados da tela do dia: `TelaDoDiaFrame._ajuda` (staticmethod, `tela_do_dia/frame.py:230`) e `_rodape` (staticmethod, `:597`).
- Os dados em memória vêm de `aportes.dados.carregar_contas()` (`aportes/dados.py:47`) e `carregar_subcontas()` (`:81`), que leem só o cache local, sem rede na thread da tela.

- [ ] **Passo 1 (RED): a guarda por AST**

  Em `tests/test_abas_em_paralelo.py:211-214`, acrescente `"tela_do_dia/controle_frame.py"` à tupla `_CHAMADORES`. Depois:
  ```
  python -m pytest tests/test_abas_em_paralelo.py -q -k todo_aviso
  ```
  → FAIL (o arquivo não existe).

- [ ] **Passo 2 (GREEN): `tela_do_dia/controle_frame.py`**

```python
# -*- coding: utf-8 -*-
"""A aba "Controle de aportes" — tela FINA.

Toda regra mora em `controle_aportes` (a conta), `controle_erp` (a leitura
do Mais Controle, só GET, pelo Chrome do app) e `controle_nuvem` (abertura,
proporção e apontamentos). Aqui: ler na thread do navegador (`submeter`,
`dona=self`), mostrar, e mandar para a nuvem — numa thread própria — o que o
dono editar. **Nada desta aba escreve no Mais Controle.**
"""
from __future__ import annotations

import datetime
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import util
import widgets
from aportes import dados as cadastro_aportes
from conciliacao.config import load_config
from nuvem import sessao

from . import controle_aportes as ca
from . import controle_erp, controle_nuvem, erp_do_dia
from .frame import TelaDoDiaFrame
from .valores import brl

px = widgets.px
_ajuda = TelaDoDiaFrame._ajuda
_rodape = TelaDoDiaFrame._rodape
TITULO = "Controle de aportes"


class ControleAportesFrame(ttk.Frame):
    COLS_CONTAS = (("parte", "PARTE", 70, "e"), ("aportou", "APORTOU", 125, "e"),
                   ("deveria", "DEVERIA", 125, "e"), ("dif", "PARA IGUALAR", 125, "e"),
                   ("situacao", "SITUAÇÃO", 220, "w"))
    COLS_SEM_DONO = (("data", "DATA", 85, "w"), ("conta", "CONTA", 170, "w"),
                     ("cliente", "CLIENTE NO ERP", 190, "w"), ("valor", "VALOR", 110, "e"),
                     ("motivo", "MOTIVO", 280, "w"))
    COLS_APONTADOS = (("data", "DATA", 85, "w"), ("conta", "CONTA", 170, "w"),
                      ("valor", "VALOR", 110, "e"), ("para", "APONTADO PARA", 190, "w"),
                      ("motivo", "MOTIVO", 280, "w"))
    LARGURA_CONTA = 220
    LINHAS_VAZIA = 3
    LINHAS_FORM = 6

    def __init__(self, master, anexar_frame):
        super().__init__(master)
        self.anx = anexar_frame
        self.q = queue.Queue()
        self.worker = None
        self._erro_drain = None
        self.pode_editar = False      # o app liga para admin; a RLS nega o resto
        self._nuvem_ocupada = False
        self.contas, self.apontamentos, self.contas_erp, self.apuracoes = [], {}, [], []
        self._linha_sem_dono, self._linha_apontado = {}, {}
        self._build()
        self.after(150, self._drain)

    # ---------------------------------------------------------------- layout
    def _build(self):
        PADX = px(widgets.PADX)
        cab = widgets.Cabecalho(
            self, TITULO,
            "Quanto cada um aportou em cada conta desde a abertura, quanto deveria pela "
            "proporção e quem deve quanto para igualar. Lê o Mais Controle; não escreve "
            "nada nele.", trilha="Diário  ›  Controle de aportes")
        cab.pack(fill="x", padx=PADX, pady=px((16, 12)))
        self.b1 = widgets.Botao(cab.acoes, "Atualizar", papel="acao", command=self.atualizar)
        self.b1.pack(side="left")
        corpo = widgets.AreaRolavel(self)

        c1 = widgets.Cartao(corpo, "Por conta", 1)
        c1.pack(fill="x", padx=PADX, pady=px((0, 12)))
        self.lbl_resumo = _ajuda(c1, "", estilo="Atencao.TLabel")
        _ajuda(c1, "Aportou = o já aportado antes da abertura mais os recebimentos de aporte "
                   "do Mais Controle desde a abertura. Deveria = o que cada um precisa ter "
                   "posto, pela proporção, para igualar quem mais pôs. Para igualar = a "
                   "diferença.")
        self.t_contas = self._tabela(c1, self.COLS_CONTAS, arvore=True, altura=12)
        linha = ttk.Frame(c1)
        linha.pack(fill="x", pady=px((8, 0)))
        self.b_nova = widgets.Botao(linha, "+ Conta no controle…", papel="neutro",
                                    state="disabled", command=lambda: self._editar_conta(None))
        self.b_editar = widgets.Botao(linha, "Editar a conta selecionada…", papel="neutro",
                                      state="disabled", command=self._editar_selecionada)
        for i, b in enumerate((self.b_nova, self.b_editar)):
            b.pack(side="left", padx=px((0 if i == 0 else 8, 0)))

        c2 = widgets.Cartao(corpo, "Sem dono", 2)
        c2.pack(fill="x", padx=PADX, pady=px((0, 12)))
        _ajuda(c2, "Recebimentos de aporte cujo Cliente no Mais Controle não é aportador da "
                   "conta (nome completo, letra por letra). Ficam FORA da conta até você "
                   "apontar de quem são — ou que não são aporte desta conta.")
        self.t_sem_dono = self._tabela(c2, self.COLS_SEM_DONO, arvore=False, altura=8)
        self.b_apontar = widgets.Botao(c2, "Apontar o selecionado…", papel="neutro",
                                       state="disabled", command=self._apontar)
        self.b_apontar.pack(anchor="w", pady=px((8, 0)))

        c3 = widgets.Cartao(corpo, "Apontados por você", 3)
        c3.pack(fill="x", padx=PADX, pady=px((0, 12)))
        self.t_apontados = self._tabela(c3, self.COLS_APONTADOS, arvore=False, altura=6)
        self.b_desfazer = widgets.Botao(c3, "Desfazer o selecionado", papel="link",
                                        state="disabled", command=self._desfazer)
        self.b_desfazer.pack(anchor="w", pady=px((8, 0)))

        acao = ttk.Frame(self, style="Fundo.TFrame")
        acao.pack(fill="x", padx=PADX, pady=px((0, 10)))
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

    @property
    def _botoes_do_dono(self):
        return (self.b_nova, self.b_editar, self.b_apontar, self.b_desfazer)

    def liberar_edicao(self, sim: bool):
        """O app liga para admin. Esconder não protege: quem nega é a RLS."""
        self.pode_editar = bool(sim)
        for b in self._botoes_do_dono:
            b.configure(state="normal" if self.pode_editar else "disabled")

    def _tabela(self, pai, colunas, *, arvore: bool, altura: int):
        grade = ttk.Frame(pai)
        grade.pack(fill="both", expand=True, pady=px((8, 0)))
        t = ttk.Treeview(grade, columns=[c[0] for c in colunas],
                         show="tree headings" if arvore else "headings", height=altura)
        if arvore:
            t.heading("#0", text="CONTA / APORTADOR", anchor="w")
            t.column("#0", width=px(self.LARGURA_CONTA), anchor="w", stretch=True)
        for chave, titulo, largura, ancora in colunas:
            t.heading(chave, text=titulo, anchor=ancora)
            t.column(chave, width=largura, anchor=ancora, stretch=ancora == "w")
        widgets.estilo_tabela(t, ordenavel=False)
        ttk.Scrollbar(grade, orient="vertical", command=t.yview).pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        return t

    def aplicar_cores(self, escuro: bool):
        try:
            widgets.estilo_log(self.log, escuro)
            for t in (self.t_contas, self.t_sem_dono, self.t_apontados):
                widgets.estilo_tabela(t, ordenavel=False)
        except tk.TclError:
            pass

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
                elif tipo == "leitura":
                    self._receber(valor)
                elif tipo == "nuvem":
                    self._depois_da_nuvem(*valor)
        except queue.Empty:
            pass
        except Exception as e:                              # noqa: BLE001
            motivo = repr(e)
            if motivo != self._erro_drain:
                self._erro_drain = motivo
                self.q.put(("log", f"[!] falha ao atualizar a tela: {motivo}"))
        finally:
            self.after(150, self._drain)

    # --------------------------------------------------------------- leitura
    def atualizar(self):
        if self.worker and not self.worker.done():
            return
        # Recusar ANTES de apagar os botões (ver "Um navegador, seis abas").
        if self.anx.avisar_se_ocupado("o Controle de aportes", aba=self):
            return
        self.q.put(("botoes", "disabled"))
        self.q.put(("ocupado", True))
        self.q.put(("status", "Lendo o controle na nuvem e os aportes no Mais Controle..."))
        self.worker = self.anx.submeter("Controle de aportes — ler", self._t_ler,
                                        datetime.date.today(), dona=self)

    def _t_ler(self, hoje):
        try:
            contas, apontamentos = controle_nuvem.ler(sessao.token())
            ativas = [c for c in contas if c.ativa]
            if not ativas:
                self._log("Nenhuma conta no controle ainda. O dono acrescenta em "
                          "\"+ Conta no controle…\".")
                self.q.put(("leitura", (contas, apontamentos, [], [])))
                return
            cfg = load_config(util.pasta_base() / "config.yaml")
            api = self.anx.garantir_sessao(self._log)
            contas_erp = erp_do_dia.ler_saldos(cfg, api, log=self._log)
            pares, erros = ca.pares_para_ler(ativas, contas_erp)
            crus = (controle_erp.ler_recebimentos(
                api, pares, hoje, contraprova=ca.conta_de_contraprova(contas_erp, pares),
                log=self._log) if pares else {})
            apuracoes = ca.apurar_tudo(ativas, erros, crus, apontamentos, hoje)
            self.q.put(("leitura", (contas, apontamentos, contas_erp, apuracoes)))
            self.q.put(("status", "Controle de aportes atualizado."))
        except Exception as e:                              # noqa: BLE001
            self._log("\n" + widgets.recado_de_erro(e, "Não consegui ler o controle de aportes."))
            self.q.put(("status", "Não consegui ler — veja o Registro."))
        finally:
            self.q.put(("ocupado", False))
            self.q.put(("botoes", "normal"))

    def _receber(self, pacote):
        self.contas, self.apontamentos, self.contas_erp, self.apuracoes = pacote
        for t in (self.t_contas, self.t_sem_dono, self.t_apontados):
            t.delete(*t.get_children())
        self._linha_sem_dono, self._linha_apontado = {}, {}
        subcontas = cadastro_aportes.carregar_subcontas()
        resumo = []
        for ap in self.apuracoes:
            pai = self.t_contas.insert(
                "", "end", text=ap.conta.conta_erp, open=True,
                values=("", "—" if ap.erro else brl(ap.total), "", "",
                        ca.situacao_da_conta(ap)))
            for l in ap.linhas:
                self.t_contas.insert(pai, "end", text=l.nome, values=(
                    f"{str(l.parte).replace('.', ',')}%", brl(l.aportou), brl(l.deveria),
                    brl(l.diferenca) if l.diferenca else "—", ca.situacao_do_aportador(l)))
            resumo += ca.resumo(ap)
            aviso = ca.divergencia_do_rateio(ap.conta, subcontas)
            if aviso:
                resumo.append(f"{ap.conta.conta_erp}: {aviso}")
            for alerta in ap.alertas:
                self._log(f"[!] {ap.conta.conta_erp}: {alerta}")
            for s in ap.sem_dono:
                r = s.recebimento
                iid = self.t_sem_dono.insert("", "end", values=(
                    f"{r.data:%d/%m/%Y}", ap.conta.conta_erp, r.cliente or "—",
                    brl(r.valor), s.motivo))
                self._linha_sem_dono[iid] = (ap.conta, r)
            for r, p, nome in ap.apontados:
                iid = self.t_apontados.insert("", "end", values=(
                    f"{r.data:%d/%m/%Y}", ap.conta.conta_erp, brl(r.valor),
                    nome or ca.NAO_E_APORTE, p.motivo))
                self._linha_apontado[iid] = p
        self.lbl_resumo.configure(text="\n".join(resumo))

    # ----------------------------------------------------------------- nuvem
    def _na_nuvem(self, feito: str, trabalho):
        """`trabalho` roda numa thread própria e NÃO toca em Tk: tudo o que
        vem da tela é lido antes."""
        if self._nuvem_ocupada:
            messagebox.showinfo(TITULO, "Ainda gravando a mudança anterior na nuvem — "
                                        "espere um instante.", parent=self)
            return
        self._nuvem_ocupada = True
        self.q.put(("status", "Gravando na nuvem..."))

        def rodar():
            try:
                trabalho()
                self.q.put(("nuvem", (feito, "")))
            except Exception as e:                          # noqa: BLE001
                self.q.put(("nuvem", (feito, widgets.recado_de_erro(
                    e, "Não consegui gravar na nuvem."))))
        threading.Thread(target=rodar, daemon=True).start()

    def _depois_da_nuvem(self, feito: str, erro: str):
        self._nuvem_ocupada = False
        if erro:
            self._log("\n" + erro)
            self.q.put(("status", "Não gravou — veja o Registro."))
            return
        self._log(f"{feito}. Atualizando os números...")
        self.atualizar()

    # -------------------------------------------------------------- diálogos
    def _janela(self, titulo):
        jan = tk.Toplevel(self.winfo_toplevel())
        jan.title(titulo)
        jan.transient(self.winfo_toplevel())
        widgets.barra_de_titulo(jan)
        corpo = ttk.Frame(jan, padding=px(14))
        corpo.pack(fill="both", expand=True)
        return jan, corpo

    def _editar_selecionada(self):
        sel = self.t_contas.selection()
        item = sel[0] if sel else ""
        while item and self.t_contas.parent(item):
            item = self.t_contas.parent(item)
        nome = self.t_contas.item(item, "text") if item else ""
        conta = next((c for c in self.contas if c.conta_erp == nome), None)
        if conta is None:
            messagebox.showinfo(TITULO, "Escolha uma conta na tabela.", parent=self)
            return
        self._editar_conta(conta)

    def _editar_conta(self, conta):
        if not self.pode_editar:
            return
        jan, corpo = self._janela("Conta no controle de aportes")
        ttk.Label(corpo, wraplength=px(560), justify="left", text=(
            "O nome da conta e o de cada aportador têm de ser os do Mais Controle, letra "
            "por letra — o aportador é o Cliente dos recebimentos de aporte dele. Nome "
            "pela metade não casa com ninguém.")).pack(anchor="w")
        v_conta = tk.StringVar(value=conta.conta_erp if conta else "")
        v_abre = tk.StringVar(value=f"{conta.abertura:%d/%m/%Y}" if conta else "")
        widgets.Campo(corpo, "Conta no Mais Controle", lambda p: ttk.Combobox(
            p, textvariable=v_conta, width=52,
            values=sorted(c.name for c in self.contas_erp))).pack(anchor="w", pady=px((10, 0)))
        widgets.Campo(corpo, "Abertura (DD/MM/AAAA)", lambda p: ttk.Entry(
            p, textvariable=v_abre, width=14)).pack(anchor="w", pady=px((10, 0)))
        grade = ttk.Frame(corpo)
        grade.pack(anchor="w", pady=px((10, 0)))
        for col, txt in enumerate(("Aportador (nome completo, como no Contato do ERP)",
                                   "Parte", "Já aportado antes da abertura (R$)")):
            ttk.Label(grade, text=txt, style="Tenue.TLabel").grid(
                row=0, column=col, sticky="w", padx=px((0, 8)))
        conhecidos = ca.nomes_conhecidos(
            cadastro_aportes.carregar_contas(), cadastro_aportes.carregar_subcontas(),
            [s.recebimento for ap in self.apuracoes for s in ap.sem_dono])
        atuais = list(conta.aportadores) if conta else []
        linhas = []
        for i in range(max(self.LINHAS_FORM, len(atuais) + 2)):
            a = atuais[i] if i < len(atuais) else None
            vs = (tk.StringVar(value=a.nome_erp if a else ""),
                  tk.StringVar(value=format(a.peso.normalize(), "f") if a else ""),
                  tk.StringVar(value=brl(a.abertura).replace("R$ ", "") if a else ""))
            ttk.Combobox(grade, textvariable=vs[0], width=46, values=conhecidos).grid(
                row=i + 1, column=0, sticky="w", padx=px((0, 8)), pady=px(2))
            ttk.Entry(grade, textvariable=vs[1], width=8).grid(
                row=i + 1, column=1, sticky="w", padx=px((0, 8)))
            ttk.Entry(grade, textvariable=vs[2], width=16).grid(row=i + 1, column=2, sticky="w")
            linhas.append(vs)

        def digitadas():
            return [tuple(v.get() for v in vs) for vs in linhas]

        def trazer():
            vindos = ca.do_rateio_da_subconta(v_conta.get(), cadastro_aportes.carregar_subcontas())
            if not vindos:
                messagebox.showinfo(TITULO, "Esta conta não é uma subconta de investidor com "
                                            "rateio cadastrado na aba Aportes.", parent=jan)
                return
            for i, vs in enumerate(linhas):
                a = vindos[i] if i < len(vindos) else None
                vs[0].set(a.nome_erp if a else "")
                vs[1].set(format(a.peso.normalize(), "f") if a else "")

        v_dev, v_divida = tk.StringVar(), tk.StringVar()

        def preencher():
            try:
                rascunho = ca.conta_do_formulario(v_conta.get() or "-", v_abre.get(), digitadas())
                aberturas = ca.aberturas_para_divida(rascunho.aportadores, v_dev.get(),
                                                     ca.ler_abertura(v_divida.get()))
            except ValueError as e:
                messagebox.showwarning(TITULO, str(e), parent=jan)
                return
            for vs in linhas:
                for nome, valor in aberturas.items():
                    if util.norm_espaco(nome) == util.norm_espaco(vs[0].get()):
                        vs[2].set(brl(valor).replace("R$ ", ""))

        ajuda = ttk.Frame(corpo)
        ajuda.pack(anchor="w", pady=px((10, 0)))
        widgets.Botao(ajuda, "Trazer do rateio da subconta", papel="neutro",
                      command=trazer).pack(side="left")
        ttk.Label(ajuda, text="   Quem deve:").pack(side="left")
        ttk.Combobox(ajuda, textvariable=v_dev, width=30,
                     postcommand=lambda: None, values=conhecidos).pack(side="left")
        ttk.Label(ajuda, text=" R$ ").pack(side="left")
        ttk.Entry(ajuda, textvariable=v_divida, width=14).pack(side="left")
        widgets.Botao(ajuda, "Preencher o já aportado", papel="neutro",
                      command=preencher).pack(side="left", padx=px((8, 0)))

        def aplicar(_e=None):
            hoje = datetime.date.today()
            try:
                nova = ca.conta_do_formulario(v_conta.get(), v_abre.get(), digitadas(),
                                              id=conta.id if conta else None,
                                              ativa=conta.ativa if conta else True)
            except ValueError as e:
                messagebox.showwarning(TITULO, str(e), parent=jan)
                return "break"
            erros = ca.problemas_da_conta(nova, hoje, self.contas)
            if erros:
                messagebox.showwarning(TITULO, "\n".join(erros), parent=jan)
                return "break"
            if not messagebox.askyesno(TITULO, ca.descrever_conta(nova)
                                       + "\n\nGravar na nuvem?", parent=jan):
                return "break"
            jan.destroy()
            outras = list(self.contas)
            self._na_nuvem("Conta gravada", lambda: controle_nuvem.gravar_conta(
                sessao.token(), nova, hoje, outras))
            return "break"

        _rodape(jan, corpo, (("Cancelar", "neutro", jan.destroy),
                             ("Gravar", "acao", aplicar)), aplicar)

    def _apontar(self):
        if not self.pode_editar:
            return
        sel = self.t_sem_dono.selection()
        if not sel or sel[0] not in self._linha_sem_dono:
            messagebox.showinfo(TITULO, "Escolha um recebimento na lista Sem dono.", parent=self)
            return
        conta, rec = self._linha_sem_dono[sel[0]]
        opcoes = ca.opcoes_de_apontamento(conta)
        jan, corpo = self._janela("Apontar recebimento")
        ttk.Label(corpo, wraplength=px(520), justify="left", text=(
            f"{rec.data:%d/%m/%Y} · {brl(rec.valor)} · {conta.conta_erp}\n"
            f"Cliente no Mais Controle: {rec.cliente or '—'}\n{rec.descricao}")).pack(anchor="w")
        v_quem, v_motivo = tk.StringVar(), tk.StringVar()
        widgets.Campo(corpo, "De quem é este aporte", lambda p: ttk.Combobox(
            p, textvariable=v_quem, state="readonly", width=52,
            values=[o[0] for o in opcoes])).pack(anchor="w", pady=px((10, 0)))
        widgets.Campo(corpo, "Motivo (obrigatório)", lambda p: ttk.Entry(
            p, textvariable=v_motivo, width=52)).pack(anchor="w", pady=px((10, 0)))

        def aplicar(_e=None):
            rotulos = dict(opcoes)
            if v_quem.get() not in rotulos:
                messagebox.showwarning(TITULO, "Escolha de quem é.", parent=jan)
                return "break"
            motivo = v_motivo.get().strip()
            if not motivo:
                messagebox.showwarning(TITULO, "Escreva o motivo.", parent=jan)
                return "break"
            escolhido = rotulos[v_quem.get()]
            jan.destroy()
            self._na_nuvem("Recebimento apontado", lambda: controle_nuvem.apontar(
                sessao.token(), conta.id, rec, escolhido, motivo))
            return "break"

        _rodape(jan, corpo, (("Cancelar", "neutro", jan.destroy),
                             ("Apontar", "acao", aplicar)), aplicar)

    def _desfazer(self):
        if not self.pode_editar:
            return
        sel = self.t_apontados.selection()
        if not sel or sel[0] not in self._linha_apontado:
            messagebox.showinfo(TITULO, "Escolha um apontamento na lista.", parent=self)
            return
        p = self._linha_apontado[sel[0]]
        if not messagebox.askyesno(TITULO, "Desfazer o apontamento? O recebimento volta "
                                           "para Sem dono.", parent=self):
            return
        self._na_nuvem("Apontamento desfeito",
                       lambda: controle_nuvem.desfazer(sessao.token(), p.id))
```

  Uma nota para o implementador: o `postcommand=lambda: None` do combobox "Quem deve" pode sair. A lista dele é a de `conhecidos`. Isso não muda nenhuma regra.

- [ ] **Passo 3:**
  ```
  python -m pytest tests/test_abas_em_paralelo.py -q -k todo_aviso
  ```
  → PASS. Rode também:
  ```
  python -m py_compile tela_do_dia/controle_frame.py
  ruff check --select E9,F tela_do_dia/controle_frame.py
  vermin --target=3.11 --no-tips --violations tela_do_dia/controle_frame.py
  ```
  **Não** rode testes de tela.

- [ ] **Passo 4: commit**
  ```
  git add tela_do_dia/controle_frame.py tests/test_abas_em_paralelo.py
  git commit -m "Controle de aportes: a tela, que lê o ERP e grava só na nuvem" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  ```

---

## Tarefa 8: Menu (DIÁRIO, no fim), ícone, papel e galeria

**MODELO:** sonnet

**Files:**
- Modify: `comprovantes_app.py`: o import (`:46`), a construção depois de `:330`, `quadros` (`:347-351`), `_grupo("diario", ...)` (`:508-510`) e os comentários "treze" (`:484`, `:714-716`, `:758-760`).
- Modify: `widgets.py`: `ICONES_FLUENT` (`:262-277`) e `ICONES_MDL2` (`:283-298`).
- Modify: `ferramentas/galeria.py`: o import, `_ORDEM` (`:188-202`), `_montar` (depois de `:374`) e `_grupo("DIÁRIO", ...)` (`:450`).
- Create: `tests/test_tela_do_dia_controle_menu.py`

**Interfaces (conferidas):**
- `nuvem.usuarios.abas_do_papel(papel, todas) -> tuple` (`nuvem/usuarios.py:191`).
- `_eu = sessao.quem(_pasta_dados())` (`comprovantes_app.py:250`) e `Quem.admin` (`nuvem/sessao.py:168`).
- As guardas de ícone `tests/test_visual.py:636` e `:654`.

- [ ] **Passo 1 (RED): os testes**

```python
# tests/test_tela_do_dia_controle_menu.py
# -*- coding: utf-8 -*-
"""A aba Controle de aportes no menu: fim do DIÁRIO, sem o aprovador. Por AST."""
import ast
from pathlib import Path

from nuvem import usuarios

_APP = Path(__file__).resolve().parents[1] / "comprovantes_app.py"


def _grupos() -> dict:
    saida = {}
    for no in ast.walk(ast.parse(_APP.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Call) and getattr(no.func, "id", "") == "_grupo":
            saida[ast.literal_eval(no.args[0])] = ast.literal_eval(no.args[2])
    return saida


def test_controle_de_aportes_fica_no_fim_do_diario():
    assert [c for c, _i, _t in _grupos()["diario"]] == ["dia", "pag", "con", "cap"]
    assert ("cap", "🤝", "Controle de aportes") in _grupos()["diario"]


def test_o_app_monta_liga_e_libera_so_para_admin():
    fonte = _APP.read_text(encoding="utf-8")
    assert "aba_cap = ControleAportesFrame(conteudo, aba_anx)" in fonte
    assert "aba_cap.liberar_edicao(_eu.admin)" in fonte
    assert '"cap": aba_cap' in fonte


def test_aprovador_nao_ve_e_operador_ve():
    assert "cap" not in usuarios.abas_do_papel("aprovador", ["ini", "pag", "cap"])
    assert "cap" in usuarios.abas_do_papel("operador", ["cap"])
```

- [ ] **Passo 2:**
  ```
  python -m pytest tests/test_tela_do_dia_controle_menu.py -q
  ```
  → FAIL.

- [ ] **Passo 3 (GREEN): as mudanças**

  **`comprovantes_app.py`:**
  - depois de `from tela_do_dia.frame import TelaDoDiaFrame`:
    ```python
    from tela_do_dia.controle_frame import ControleAportesFrame
    ```
  - depois de `aba_dia.aba_remessa = aba_pag`:
    ```python
    # Controle de aportes divide navegador e thread do Anexar: lê o MESMO ERP
    # (só GET). Só o admin edita abertura, proporção e apontamentos — a RLS
    # nega o resto; aqui só se apagam os botões.
    aba_cap = ControleAportesFrame(conteudo, aba_anx)
    aba_cap.liberar_edicao(_eu.admin)
    ```
  - em `quadros`, acrescentar `"cap": aba_cap` (depois de `"dia": aba_dia`);
  - no `_grupo("diario", ...)`, acrescentar no FIM `("cap", "🤝", "Controle de aportes")`, para não tirar o Ctrl+N de nenhuma tela;
  - nos comentários: "treze telas" → "catorze telas", e em `:758-760` "dez teclas de dígito para treze telas (catorze com a de Usuários)" → "…para catorze telas (quinze com a de Usuários)".

  **`widgets.py`:** acrescentar nas DUAS tabelas, com o comentário `# People — Controle de aportes`:
  ```python
  "🤝": "\uE716",
  ```
  O `\uE716` está livre nas duas (os usados são E80F, E896, E8C6, E723, E9D5, E8C7, E787, E8EF, E9F9, E825, E8A5, E724, E77B, E8FD). No texto acima de `ICONES_FLUENT` (`:255-261`), acrescente que o 15º, People, também pede conferência na galeria.

  **`ferramentas/galeria.py`:**
  - `from tela_do_dia.controle_frame import ControleAportesFrame` junto do import do `TelaDoDiaFrame`;
  - em `_ORDEM`, depois de `("con", ...)`: `("cap", "🤝", "Controle de aportes", "controle-de-aportes"),`;
  - dentro de `if aba_anx is not None:`, depois do bloco `dia`: `_montar("cap", lambda: ControleAportesFrame(conteudo, aba_anx))`;
  - `_grupo("DIÁRIO", tuple(i for i in _ORDEM if i[0] in ("dia", "pag", "con", "cap")))`.

- [ ] **Passo 4:**
  ```
  python -m pytest tests/test_tela_do_dia_controle_menu.py tests/test_visual.py -q -k "controle or tabelas_de_icones or nenhum_icone"
  python -m py_compile comprovantes_app.py ferramentas/galeria.py widgets.py
  ruff check --select E9,F comprovantes_app.py ferramentas/galeria.py widgets.py tests/test_tela_do_dia_controle_menu.py
  ```

- [ ] **Passo 5: commit**
  ```
  git add comprovantes_app.py widgets.py ferramentas/galeria.py tests/test_tela_do_dia_controle_menu.py
  git commit -m "Controle de aportes: no fim do DIÁRIO, com ícone próprio e edição só do admin" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  ```

---

## Tarefa 9: Documentação e verificação final

**MODELO:** haiku (texto) e depois o coordenador (verificação)

**Files (Modify):**
- `.claude/rules/arquitetura-tela-do-dia.md`
- `.claude/rules/arquitetura-interface.md` (`:25-29`)
- `.claude/rules/arquitetura-ferramentas.md` (`:16`)
- `docs/ERP-CLIENTES.md` (tabela que começa em `:30`)
- `CLAUDE.md` (`:426`)

- [ ] **Passo 1: `arquitetura-tela-do-dia.md`**

  Acrescente ao fim a seção abaixo. Não precisa mudar o `paths:`: os arquivos novos já casam `tela_do_dia/**` e `tests/test_tela_do_dia*.py`.

```markdown
## Aba "Controle de aportes" (entrega 3, 22/10/2026)

Mora neste pacote (`controle_*.py`) por ser do mesmo projeto e para não
pedir pasta nova no `build.yml`. Grupo DIÁRIO, no FIM (chave `cap`, sem
Ctrl+N), invisível ao aprovador. **Não escreve no Mais Controle.**

| Módulo | Decide |
|---|---|
| `controle_aportes.py` | a conta (aportou = já aportado antes da abertura + recebimentos do ERP; nível = maior aportou÷parte; deveria = nível×parte; para igualar = deveria − aportou), quem é o aportador, sem dono, apontamentos, formulário |
| `controle_erp.py` | `GET receipt-installments` por conta × natureza (Aporte de Capital, Aporte de Investidor), pela aba do robô |
| `controle_nuvem.py` | `controle_aporte_conta`, `_aportador`, `_atribuicao` (ler: e_ativo; escrever: e_admin) |
| `controle_frame.py` | tela fina; nuvem numa thread própria |

**Aportador = Cliente do recebimento pelo nome COMPLETO** (`util.norm_espaco`),
contra os aportadores daquela conta; o resto vai para "Sem dono", fora da conta
até o dono apontar. Apontamento guarda o valor: se o ERP mudar, volta para sem
dono ("apontado com R$ X; agora R$ Y"). **Filtros conferidos**: a mesma parcela
em duas contas, duas naturezas ou na conta de contraprova PARA a leitura
(`accountIds`/`natureIds` deste endereço não foram medidos). Proporção é
PRÓPRIA (não a aba Regras do MODELO, nem viva da `subconta_investidor`, que
entra só como sugestão e aviso de divergência). Distribuição de lucro não
abate.
```

- [ ] **Passo 2:** em `arquitetura-interface.md:25-29`, "As treze telas" → "As catorze telas". A lista do DIÁRIO ganha "…, Saldo de pagamentos, Controle de aportes (desde 22/10/2026)". Em `arquitetura-ferramentas.md:16` e `CLAUDE.md:426`, "13 telas" → "14 telas".

- [ ] **Passo 3:** em `docs/ERP-CLIENTES.md`, uma linha nova na tabela de consumidores:

  `| tela_do_dia/controle_erp.py | recebimentos de aporte por conta e natureza (só GET) | fetch na página (MCApi._fetch_json) | legacy-api (receipt-installments, _base_legacy) e prod-erp-api (natures, _base_erp) | cabeçalhos capturados da página | os da MCApi | page (base 0) + size, fim por last | accountIds/natureIds não medidos: conferidos por parcela repetida entre contas/naturezas e por conta de contraprova |`

- [ ] **Passo 4 (coordenador): verificação, só testes puros**

```
python -m pytest tests/test_tela_do_dia_controle.py tests/test_tela_do_dia_controle_erp.py tests/test_tela_do_dia_controle_nuvem.py tests/test_tela_do_dia_controle_sql.py tests/test_tela_do_dia_controle_menu.py tests/test_rls_supabase.py tests/test_empacotamento.py tests/test_nomes_de_modulo.py tests/test_tela_do_dia_valores.py -q
python -m pytest tests/test_abas_em_paralelo.py -q -k todo_aviso
python -m pytest tests/test_visual.py -q -k "tabelas_de_icones or nenhum_icone"
ruff check --select E9,F .
vermin --target=3.11 --no-tips --violations tela_do_dia/controle_aportes.py tela_do_dia/controle_erp.py tela_do_dia/controle_nuvem.py tela_do_dia/controle_frame.py comprovantes_app.py widgets.py
git grep -n -i -E "<<|nome real" -- tela_do_dia tests supabase
```

  O último `git grep` tem de vir vazio de dado real. Confira também, a olho, que nenhum nome de sócio, empresa ou conta real entrou no diff: `git diff origin/main --stat` e depois `git diff origin/main`.

- [ ] **Passo 5:** com a máquina livre e o dono liberando, rode a galeria (`python -m ferramentas.galeria --escala 0.8`) para conferir o ícone `\uE716` nos dois temas. Os PNG não vão para o PR.

- [ ] **Passo 6: commit**
  ```
  git commit -am "Controle de aportes: o mapa da aba, o inventário do ERP e a contagem de telas" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  ```

- [ ] **Passo 7 (coordenador):**
  - Antes do PR, o revisor de SQL revisa os dois arquivos SQL e o revisor de dinheiro revisa as Tarefas 3 e 4.
  - O coordenador aplica o arquivo da raiz pelo CLI antes de liberar.
  - Prova de aceite no app real (o dono logado): Atualizar mostra a conta-mãe com o devedor devendo R$ 50.000,00 menos o que ele aportou desde 21/10 pelo ERP.

---

## Riscos e decisões (≤10 linhas)

1. **Não medido:** se `accountIds` e `natureIds` filtram em `receipt-installments`. Se o ERP os ignorar, a aba PARA com erro claro, porque a contraprova e as parcelas repetidas acusam. O conserto exige medir com o dono logado.
2. **Só contam as naturezas "Aporte de Capital" e "Aporte de Investidor".** Aporte lançado pela equipe com outra natureza fica invisível, nem aparece em "sem dono". Distribuição de lucro e devolução não abatem nada (fora do escopo).
3. **A abertura é inclusiva (21/10 entra).** Se os R$ 50.000,00 do dono já descontam aportes lançados em 21/10, eles contam em dobro. **Confirmar com o dono antes de aplicar o arquivo da raiz.**
4. **Só quem é admin escreve** (`privado.e_admin()` junto da porteira `e_ativo`). Se o dono não for admin ativo, não edita; o arquivo da raiz para se não houver admin ativo.
5. **A proporção é própria do controle.** A da subconta é só sugestão e aviso de divergência; a aba Regras do MODELO não entra (vocabulário do painel, arquivo local).
6. **O aportador é o Cliente exato no ERP.** Contato duplicado ou grafado diferente vai para "sem dono" (visível) e nunca é chutado.
7. **Menu no fim do DIÁRIO, sem Ctrl+N.** `comprovantes_app.py`, `widgets.py` e `galeria.py` também mudam nas entregas 2, 4 e 5, então o merge desses três é à mão. A migration `20261022130000` pode ter de ser renumerada se colidir.
8. **Leitura cara de propósito.** `ler_saldos` é reaproveitado para achar o id da conta (uma chamada a mais), e são 2 consultas por conta mais a contraprova.

---

### Critical Files for Implementation
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2\tela_do_dia\controle_aportes.py (novo; regra de dinheiro e identificação)
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2\tela_do_dia\controle_erp.py (novo; espelha `anexar/mc_api.py:677-735`)
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2\supabase\migrations\20261022130000_controle_de_aportes.sql (novo; RLS)
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2\comprovantes_app.py (existente; menu e fiação)
- C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\app-pagamentos-do-dia-2\aportes\regras.py (referência só leitura: naturezas `:37-41`, pesos `:196-260`, `como_dinheiro` `:107`)
