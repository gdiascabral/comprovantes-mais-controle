# Proveniência: o que rodou no banco, e o que as migrations dizem

As migrations descrevem o schema. Mas **não foram elas que rodaram** — o que
rodou foram arquivos colados no SQL Editor do painel, que viviam soltos na
pasta acima do repositório. Enquanto ficaram fora, "o que está em produção" e
"o que o repositório diz" eram duas perguntas com respostas diferentes e
nenhuma forma de comparar.

`supabase/runbooks/` guarda o que rodou, byte a byte. Este documento diz, para
cada um, **qual migration corresponde e onde os dois divergem**.

A comparação é por **diff normalizado**: cada arquivo virou uma lista de
comandos SQL, sem linha de comentário e sem espaço em branco, e as duas listas
foram comparadas comando a comando. Só a diferença está escrita abaixo.

---

## `2026-08-21_aplicar-no-supabase.sql`

Corresponde a **três** migrations, porque o arquivo trata três assuntos
independentes: `20260820103000_regra_so_marcador.sql`,
`20260821094500_conta_pode_nascer_pelo_app.sql` e
`20260824141500_conta_grant_que_faltou.sql`.

7 comandos no runbook; 2 + 2 + 1 nas três migrations.

**O runbook faz e as migrations não fazem** (3 comandos):

- `insert into public.regra_fornecedor` das três concessionárias
  (`so_marcador`);
- `update public.entidade` apontando uma subconta para o nome exato do ERP;
- o `select` final de conferência, que devolve as três respostas na ordem.

Os dois primeiros são **cadastro do escritório**, e a migration
`20260820103000` diz por escrito que eles não entram nela: *"As concessionarias
em si NAO entram aqui: nome de fornecedor e cadastro do escritorio, nao
esquema."* O terceiro é conferência, que não é schema.

**A migration faz e o runbook não faz** (1 comando):

- `grant insert, update on table public.conta to authenticated`, de
  `20260824141500`.

Essa é a divergência que importa. O runbook criou as políticas `conta_cadastra`
e `conta_corrige` em 21/08 e parou aí; o privilégio de tabela veio três dias
depois, na migration de 24/08, e **não há runbook para ele nesta pasta**. Ou
seja: não está registrado aqui por onde esse `grant` chegou ao projeto de
verdade. É o primeiro item a conferir com o `db diff` da seção final.

Os 2 comandos da migration `20260821094500` e os 2 da `20260820103000` estão
todos no runbook, idênticos depois de normalizados.

---

## `2026-08-21_cadastrar-so-marcador.sql`

Corresponde a `20260820103000_regra_so_marcador.sql`.

6 comandos no runbook; 2 na migration, os dois presentes no runbook.

**O runbook faz e a migration não faz** (4 comandos):

- o mesmo `insert` das três concessionárias;
- o mesmo `update public.entidade` da subconta;
- dois `select` de conferência.

Há ainda um `delete from public.entidade` **comentado**, com a instrução de só
descomentar se o dono decidir tirar a linha do cadastro. Como está comentado,
não conta como comando: nunca rodou.

Este arquivo e o `2026-08-21_aplicar-no-supabase.sql` **se sobrepõem** — as
duas primeiras partes de um são as duas primeiras partes do outro, e o `update`
da subconta está nos dois. Ambos são idempotentes (`on conflict do nothing`,
`update ... where`), então rodar os dois não estraga nada; mas os dois existirem
é sintoma de o registro do que rodou não ter dono, que é o que esta pasta
resolve.

---

## Os dois de 30/08/2026 — **NÃO ESTÃO AQUI**

`APLICAR NO SUPABASE - 2026-08-30 contas de usuario.sql` e
`APLICAR NO SUPABASE - 2026-08-30 auto-cadastro.sql` continuam fora do
repositório. **Os dois contêm um endereço de e-mail real** — o da conta de
administrador, usado para promovê-la e para as provas de RLS —, e este
repositório é público. O valor não está escrito em lugar nenhum deste PR.

A proveniência deles fica registrada assim mesmo, porque ela não depende do
conteúdo:

### `... 2026-08-30 contas de usuario.sql` ↔ `20260830160000_contas_de_usuario.sql`

422 linhas contra 235; 46 comandos contra 32. **Os 32 comandos da migration
estão todos no runbook, idênticos.** O runbook acrescenta 14:

- o `update public.perfil` que promove uma conta a `admin` ativo (a migration
  diz por escrito que ninguém nasce admin: *"virar admin e decisao de gente"*),
  mais o `select` que confere se pegou;
- a conferência da fase 1 inteira — sete provas dentro de blocos `do $$`, com
  `set role authenticated` e `set_config('request.jwt.claims', ...)` para
  simular o que o PostgREST monta a partir de um token, e `reset role` no fim;
- o `insert` de uma linha de `auditoria` como parte da prova, e o `update` que
  devolve a conta de teste à situação `pendente` em que estava.

### `... 2026-08-30 auto-cadastro.sql` ↔ `20260830180000_so_conta_liberada_entra.sql`

388 linhas contra 206 — os 182 de diferença. 40 comandos contra 28, e **os 28
da migration estão todos no runbook, idênticos.** O runbook acrescenta 12, do
mesmo feitio do par acima: a conferência da fase 3 em sete provas, o
`set_config` que guarda uma empresa existente para a prova 4 não morrer no
`not null` antes de a RLS ser consultada, uma chamada de `alocar_nsa` contra o
convênio de mentira `CONFERENCIA-FASE-3` e o `delete from
public.remessa_contador` que apaga esse convênio no fim.

**O padrão dos quatro é o mesmo, e é o que este documento existe para dizer:**
nenhuma migration faz nada que o runbook correspondente não tenha feito. A
diferença toda está do outro lado — os runbooks acrescentam cadastro, promoção
de administrador e conferência. Schema, nos quatro pares, os dois lados
concordam.

---

## Conferir o schema de produção contra as migrations

O acima compara arquivo com arquivo. Nada disso prova o que está **no banco**.
Quem pode provar é o dono, com a credencial dele.

O CLI está em `C:/AUTOMAÇÕES MAIS CONTROLE/ferramentas/supabase/supabase.exe`
(2.115.0). Uma vez, para ligar:

```
"C:/AUTOMAÇÕES MAIS CONTROLE/ferramentas/supabase/supabase.exe" login
"C:/AUTOMAÇÕES MAIS CONTROLE/ferramentas/supabase/supabase.exe" link --project-ref <ref-do-mais-controle-app>
```

Depois, da raiz do repositório, **o comando**:

```
"C:/AUTOMAÇÕES MAIS CONTROLE/ferramentas/supabase/supabase.exe" db diff --linked --schema public,privado
```

- `--linked` compara contra o projeto ligado. Sem ele o padrão é `--local`, que
  compararia com um banco de brincadeira e responderia "tudo igual" sem olhar
  produção.
- `--schema public,privado` porque as funções que sustentam a RLS
  (`privado.e_ativo()`, `privado.e_admin()`) moram fora do `public`. Sem isso a
  conferência não alcança justamente a porteira.
- **Sem `-f`.** Com `-f nome`, o CLI salva o resultado como uma migration nova
  antes de você ler. Sem, ele imprime na tela — que é o que se quer aqui.
- Precisa do **Docker Desktop de pé**: o `db diff` monta um banco-sombra local
  a partir de `supabase/migrations` para ter contra o que comparar. Não há
  atalho pelo CLI sem ele.

Ele **lê**: não escreve no projeto. Saída vazia = o banco é exatamente o que as
migrations dizem.

**A alternativa, com uma ressalva séria.** `supabase db pull --linked` faz o
caminho inverso — escreve a diferença como migration nova. Rode-o **numa branch
temporária**, para o arquivo que nascer não cair na `main` sem ninguém ler:

```
git switch -c conferencia/schema-producao
"C:/AUTOMAÇÕES MAIS CONTROLE/ferramentas/supabase/supabase.exe" db pull --linked
```

A ressalva: o próprio `--help` da 2.115 avisa que o `db pull` em modo migration
*"may record them in that database's migration history"* — ou seja, ele pode
**escrever** no histórico de migrations do projeto na nuvem. `db diff` não faz
isso. Prefira o `db diff`.

## A regra, se der diferença

**Deu diferença, nasce uma migration NOVA de reconciliação. Migration antiga
nunca se edita.**

Não é preciosismo. Uma migration já aplicada é o registro do que aconteceu
naquela data; editá-la reescreve o passado em toda máquina que já a rodou, e
deixa este banco e qualquer banco futuro em estados diferentes com o mesmo
arquivo na mão. O erro não some — só passa a ser invisível.

A migration nova diz, no comentário do topo, **o que se descobriu e como**. A
de 24/08 (`conta_grant_que_faltou`) é o modelo: ela não corrige a de 21/08, ela
acrescenta o `grant` que faltava e explica o sintoma que denunciou a falta.

## E a próxima vez

Rodou alguma coisa no SQL Editor do painel? O arquivo vem para
`supabase/runbooks/`, com a data no nome, **no mesmo dia** — e o que nele for
schema vira migration. O que for cadastro (nome de fornecedor, conta, pessoa)
não vira migration nenhuma: cadastro não é schema, e este repositório é
público.
