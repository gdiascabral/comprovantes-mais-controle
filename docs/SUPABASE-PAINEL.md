# O painel do Supabase e o `config.toml`: conferir um contra o outro

O `supabase/config.toml` **descreve** o projeto; quem **manda** é o painel. As
duas coisas podem discordar em silêncio, e já discordaram: o auto-cadastro foi
ligado no painel em 30/08/2026 e o arquivo continuou dizendo
`enable_signup = false` até 02/09/2026. Por três dias, quem lesse o repositório
leria um projeto que não existe.

Esta é a lista do que conferir, campo do painel por campo do arquivo. Leva
poucos minutos e não precisa de terminal.

Projeto: `mais-controle-app` (região sa-east-1).

---

## 1. Authentication → Sign In / Providers → Email

| No painel | No arquivo | Tem de estar |
|---|---|---|
| **Allow new users to sign up** | `[auth]` → `enable_signup` | **ligado / `true`** |
| **Confirm email** | `[auth.email]` → `enable_confirmations` | **ligado / `true`** |
| O provedor **Email** em si (o botão de habilitar) | `[auth.email]` → `enable_signup` | **ligado / `true`** |

Três observações que valem mais que a tabela:

- **"Allow new users to sign up" ligado não é descuido.** Quem barra o
  estranho não é mais o cadastro fechado: é a `privado.e_ativo()`, que está em
  toda política de dado e dentro das duas funções de NSA (migration
  `20260830180000_so_conta_liberada_entra.sql`). Conta nova nasce **pendente** e
  não alcança nada até um administrador liberar. `tests/test_rls_supabase.py`
  falha se alguma política escapar dessa porteira.
- **Os dois `enable_signup` são coisas diferentes** e é fácil desligar o
  errado. O de `[auth.email]` liga o **provedor** — desligá-lo mata o próprio
  **login** com `email_provider_disabled`, para todo mundo, inclusive quem já
  trabalha aqui. O que controla criar conta é só o de `[auth]`.
- **"Confirm email" desligado enche a fila do admin de endereço inventado.**
  Ligado, a conta pendente que chega na fila corresponde a uma caixa de e-mail
  de verdade.

## 2. Authentication → URL Configuration

| No painel | No arquivo | Tem de estar |
|---|---|---|
| **Site URL** | `[auth]` → `site_url` | a página de confirmação — **decisão do dono** |
| **Redirect URLs** | `[auth]` → `additional_redirect_urls` | o mesmo endereço, ou vazio |

O arquivo está com `https://SUBSTITUA-pela-pagina-de-confirmacao` nos dois, de
propósito: é um valor que não funciona por acidente e não deixa dúvida de que
falta uma decisão. **Não é para dar `config push` enquanto ele estiver lá.**

O que estava antes era `http://localhost:3000`, escrito pelo `supabase init`.
Não há servidor nesse endereço e não há como haver — este projeto é um app de
desktop, não um site. Quem confirmava o e-mail caía numa página de erro do
navegador: a conta ficava válida e pendente na fila, mas a última coisa que a
pessoa via dizia o contrário.

### A saída provável: GitHub Pages deste repositório

`docs/confirmado.html` já existe — página estática, sem script, sem dado, sem
nome de empresa. Para ligar:

1. GitHub → **Settings → Pages**
2. **Source: Deploy from a branch**
3. Branch **`main`**, pasta **`/docs`**, Save
4. Esperar o Pages publicar (alguns minutos na primeira vez)
5. Abrir e confirmar que responde:
   `https://gdiascabral.github.io/comprovantes-mais-controle/confirmado.html`
6. Só então pôr esse endereço no painel **e** no `config.toml`, no mesmo dia

Repositório público servindo `docs/` publica **tudo** que está em `docs/`. Hoje
são `DEPENDENCIAS.md`, `SUPABASE-PAINEL.md` (este arquivo), `confirmado.html` e
`superpowers/` — nada disso é segredo, mas quem puser um arquivo novo em
`docs/` a partir de agora está publicando na web.

---

## Ver o que mudaria ANTES de aplicar

**Não dá — e é o ponto.** Conferido na 2.115.0, `supabase config push` tem um
único flag próprio (`--project-ref`). Não existe `--dry-run`, não existe
`--diff`, e não existe `supabase config pull` (o `config` só tem o subcomando
`push`). Confira você mesmo, que é leitura e não muda nada:

```
"C:/AUTOMAÇÕES MAIS CONTROLE/ferramentas/supabase/supabase.exe" config push --help
"C:/AUTOMAÇÕES MAIS CONTROLE/ferramentas/supabase/supabase.exe" config --help
```

Ou seja: **`config push` aplica direto, sem mostrar o que vai mudar**. Rodá-lo
com um `config.toml` recém-criado pelo `init` empurra os DEFAULTS do CLI por
cima do projeto — aqui já desligou o MFA e a confirmação de e-mail e afrouxou o
limite de envio, e ninguém viu acontecer.

**A alternativa é esta lista.** Não há atalho: abra o painel nas duas telas das
seções 1 e 2, leia campo por campo contra o arquivo, corrija a discordância no
lado certo, e só então rode o push (se for rodar). Depois do push, volte ao
painel e confira de novo — é a única confirmação que existe.

Vale um item a mais, fora da lista porque não se mexe nele: `[auth.rate_limit]`
→ `email_sent = 2` (e-mails por hora). É baixo de propósito, mas é o mesmo
balde da confirmação de cadastro: três pessoas se cadastrando na mesma hora e a
terceira não recebe o link. Se isso acontecer, é aqui.

---

## A regra

**Mudou no painel, muda no arquivo no mesmo dia.**

Não "na próxima vez que eu mexer no Supabase", não "quando eu lembrar". No
mesmo dia. O custo de não fazer isso não é o arquivo ficar feio: é alguém ler o
repositório para decidir alguma coisa e decidir errado — que foi exatamente o
que quase aconteceu entre 30/08 e 02/09, quando o arquivo dizia que ninguém
podia criar conta e qualquer um do mundo podia.

Vale nos dois sentidos: mudou no arquivo e deu `config push`, confira o painel
depois. O push não mostra o que fez.
