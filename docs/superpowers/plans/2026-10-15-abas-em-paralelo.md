# Abas em paralelo no modo central — plano

> **Para agentes:** use superpowers:subagent-driven-development ou executing-plans. Passos com `- [ ]`.

**Objetivo:** com o Chrome central ligado (`erp.central.ligado()`), cada aba do app
(Pagamentos do Dia, Saldo de pagamentos, Aportes, Contratos, Relatório Mensal,
Conferência, Guias, Anexar, "Atualizar contas") trabalha numa thread SÓ DELA e
numa aba SÓ DELA no Chrome central. O aviso "Navegador ocupado" passa a valer
só quando a MESMA aba do app já está trabalhando.

**Por quê:** o porteiro (v2.0.238) protege a sessão entre programas e máquinas,
mas dentro do app ainda havia um `MCClient` e uma thread para todas as abas
(`AnexarFrame.exec`, `max_workers=1`). Teste do dono em 15/10: com Pagamentos do
Dia buscando, o Saldo de pagamentos recebeu "Navegador ocupado".

**Spec:** este arquivo + `docs/superpowers/plans/2026-10-14-porteiro-do-erp.md`.

## Restrições globais
- **Desligado = idêntico a hoje.** Sem central, `AnexarFrame` continua com UM
  executor, UM `MCClient`, o mesmo aviso e o mesmo texto. Os testes existentes
  não mudam.
- Playwright sync: cada objeto só na thread que o criou. Uma aba do app = um
  executor de 1 thread = um `MCClient` (que no central já abre a SUA aba no
  Chrome e fecha só ela na saída).
- Login: continua pela trava de login do `MCClient` (arquivo, 600/600) — várias
  threads no mesmo processo respeitam a mesma trava.
- Nenhum login HTTP; nada de fechar o Chrome central.
- Python 3.11; nenhum submódulo novo da stdlib (`threading.local` já existe).
- Repositório público: sem dado real.

## Desenho

`AnexarFrame` ganha "vagas" no modo central:

```
vaga = {executor (1 thread, nome "nav-<rótulo>"), mc: MCClient|None, api: MCApi|None,
        trabalho_atual: Future|None, rotulo_atual: str|None, pulso: Future|None}
```

- A chave da vaga é a ABA DONA (`dona`, o objeto frame que já é passado a
  `submeter(..., dona=self)`). `dona=None` usa a vaga do próprio `AnexarFrame`.
- `submeter(rotulo, fn, *a, dona=None, **k)`: no central, pega/cria a vaga da
  dona e submete NO EXECUTOR DELA, com um embrulho que, dentro da thread da vaga,
  põe a vaga num `threading.local()` antes de chamar `fn`. Fora do central, o
  caminho de hoje sem mudança.
- `self.mc` e `self.api` viram **propriedades**: no central e numa thread de
  vaga, leem/escrevem a vaga dessa thread; em qualquer outro caso (central
  desligado, ou thread da interface), o atributo de sempre (`self._mc`,
  `self._api`). Assim `garantir_sessao`, `_t_*` e as abas que fazem
  `self.anx.mc` / `self.anx.api` DENTRO do trabalho passam a usar o cliente da
  própria aba sem mudar uma linha nelas.
- `ocupado()` / `dona_ocupada()` / `avisar_se_ocupado(rotulo, *, aba=None)`:
  no central, só olham a vaga da `aba` informada (e, se `aba` for None, a vaga
  do próprio `AnexarFrame`). Os 17 chamadores passam a mandar `aba=self` (ou a
  dona que eles já passam a `submeter`). Fora do central, ignora `aba` e faz o
  de hoje. A barra lateral/rodapé que mostra "● quem está trabalhando" precisa
  continuar funcionando: no central, `dona_ocupada()` sem argumento devolve
  qualquer vaga ocupada (a mais recente) — conferir quem chama
  (`grep -rn "dona_ocupada\|\.ocupado()" --include=*.py .`) e manter o efeito
  visível.
- **Minha aba no ERP** (`abrir_minha_aba`, thread da interface): no central, abre
  a aba da pessoa SEM Playwright, por HTTP no CDP local:
  `PUT http://127.0.0.1:<porta>/json/new?<url>` (Chrome 111+ exige PUT) — depois
  de `central.garantir_chrome(acesso)`. Nunca reaproveita aba de robô. Fora do
  central, o caminho de hoje.
- **Pulso** (`_pulsar_navegador`): no central, pulsa cada vaga livre no executor
  DELA (`mc.pulsar`), nunca cruzando threads.
- **Fechar** (`fechar()`): no central, para cada vaga, `executor.submit(mc.__exit__)`
  com prazo, depois `shutdown`. Nunca fecha o Chrome central (o `__exit__` do
  `MCClient` central já só fecha a aba dele).
- `_t_abrir` (erro): o `self.mc.__exit__` + `self.mc = None` já vai para a vaga
  da thread pela propriedade — conferir.
- Revalidação de login depois do HTTP (`conciliacao/frame.py`
  `_revalidar_navegador_aberto`, `comprovantes_app.py` "Atualizar contas"): no
  central não há login HTTP; esses trechos continuam funcionando (o `garantir_login`
  do central responde "sessão ainda aberta"), sem mudança obrigatória.

## Tarefas

### Tarefa 1 — vagas, `submeter`, propriedades `mc`/`api`, `ocupado` por aba
Arquivos: `anexar/anexar_comprovantes.py`; testes novos `tests/test_abas_em_paralelo.py`.
Testes (dublês, sem navegador, `central.ligado` por monkeypatch; `AnexarFrame`
criado como nos testes existentes que o instanciam — ver `tests/test_aba_da_pessoa.py`):
- [ ] central desligado: duas donas → mesmo executor; `avisar_se_ocupado` da
      segunda devolve True enquanto a primeira trabalha (comportamento atual).
- [ ] central ligado: duas donas → executores diferentes; com a dona A presa
      num `Event`, `avisar_se_ocupado(..., aba=B)` devolve False e o trabalho de B
      roda até o fim ANTES de soltar A.
- [ ] central ligado: mesma dona duas vezes → `avisar_se_ocupado(..., aba=A)`
      devolve True.
- [ ] dentro do trabalho de A, `frame.mc = X` e, dentro do de B, `frame.mc` é None
      (vagas isoladas); na thread de A de novo, `frame.mc is X`.
- [ ] fora de thread de vaga (thread do teste), `frame.mc` lê o atributo comum.
- [ ] `fechar()` com duas vagas abertas chama `__exit__` de cada `mc` NA thread
      da vaga (dublê registra `threading.get_ident()`).
Commit.

### Tarefa 2 — os 17 chamadores passam `aba=`
Arquivos: os de `grep -rn "avisar_se_ocupado(" --include=*.py . | grep -v tests`.
- [ ] cada chamada passa `aba=` com a MESMA dona que aquele trecho passa ao
      `submeter` logo depois (ler o trecho; onde o `submeter` usa `dona=None`,
      passar `aba=None`).
- [ ] dublês de teste que implementam `avisar_se_ocupado(self, quem)` passam a
      aceitar `aba=None` (`tests/test_contas_mc.py`, `test_contratos_frame_distrato.py`,
      `test_guias_painel.py` e outros do grep).
- [ ] teste: um teste por arquivo que já testa a aba basta checar que o `aba=`
      chega (onde já houver teste da aba); não criar suíte nova por aba.
Commit.

### Tarefa 3 — Minha aba no ERP, pulso e fechar no central
Arquivos: `anexar/anexar_comprovantes.py`, `anexar/mc_client.py` (função de
módulo `abrir_aba_central(a, url, *, abrir=urllib.request.urlopen) -> bool` com
`PUT {central.endereco(a)}/json/new?<url>`). **`erp/central.py` NÃO muda** — ele
tem cópia byte a byte no agua-energia.
- [ ] teste de `abrir_aba_central`: monta `PUT http://127.0.0.1:9230/json/new?<url>`;
      erro de rede → False.
- [ ] `abrir_minha_aba` no central: chama `central.garantir_chrome` + `abrir_aba_central`, loga a
      mensagem de hoje; nunca chama `submeter`.
- [ ] pulso no central: uma submissão de `mc.pulsar` por vaga livre, no executor dela.
Commit.

