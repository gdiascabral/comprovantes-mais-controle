# Contas num lugar só — desenho (05/10/2026)

## O problema, nas palavras do dono

Quase toda aba precisa da lista de contas, e cada uma busca do seu jeito. Às
vezes a conta nova é incluída numa aba e esquecida na outra, e isso causa
confusão. O dono quer a busca num lugar só, de onde todas as abas leem.

## O que existe hoje (mapa lido no código em 05/10/2026)

- **Abertura do app:** `nuvem/cadastro.sincronizar` baixa o cadastro do
  Supabase e regrava os caches (`contas_mc.json`, `contas_sicoob.json`,
  `contas_inter.json`, `contas.csv`, `subcontas.json`). Depois,
  `nuvem/contas_novas.novidades` entra no ERP **por HTTP, sem navegador**,
  lista as contas ativas e abre `nuvem/contas_novas_dialogo.perguntar` para
  as que faltam no cadastro. `contas_novas.gravar` insere no Supabase. **Não
  ressincroniza depois**: a conta só chega às abas na abertura seguinte.
- **Saldo de pagamentos:** o botão "🔎 Verificar contas novas"
  (`conciliacao/frame.py`) faz um segundo login HTTP e abre outra janela
  (`conciliacao/contas_novas_janela.py`), que inclui a conta no painel
  (`MODELO.xlsx` + `mapping.yaml` + `config.yaml`, por
  `conciliacao/painel_novas.incluir_no_painel`).
- **Relatório Mensal:** "Carregar contas" abre o Chrome e lê `allAccounts` da
  tela `#/cash-flow`.
- **Baixar Comprovantes:** botão "Atualizar lista" relê o cache.
- **Aportes:** link "Recarregar cadastros" relê `contas.csv`/`subcontas.json`.
- **Anexar:** "Carregar contas" NÃO é cadastro. Ele entra no ERP e busca os
  PAGAMENTOS do período; as contas que aparecem são as que tiveram pagamento.
- Remessa/Retorno, Extratos Sicoob, Acessórias e Contratos já leem o cache a
  cada uso.

## Decisões do dono (05/10/2026)

1. **Abertura + um botão.** O app continua buscando as contas sozinho ao
   abrir e ganha UM botão, "Atualizar contas", no rodapé do menu, ao lado do
   aviso "cadastro sincronizado". Todas as abas leem dali. Atualizar no meio
   do dia entra no ERP e derruba a sessão do Chrome do app (o ERP aceita uma
   sessão por usuário); o app refaz o login do navegador logo em seguida.
2. **Uma janela só para conta nova.** A janela de contas novas inclui a
   conta no cadastro (Supabase) E no painel do Saldo de pagamentos de uma
   vez, e todas as abas enxergam sem reabrir o app. O botão "Verificar
   contas novas" do Saldo sai.

## O desenho

### Uma fonte: `nuvem/contas_central.py`

- Guarda a lista de contas ATIVAS do ERP lida na última atualização num cache
  local, `contas_erp.json` (pela `nuvem/cache.gravar_json`, como os outros).
  Lista vazia nunca substitui cheia (mesma regra do `sincronizar`).
- Calcula as **pendências**: para cada conta do ERP, se falta no cadastro
  (régua de hoje: `contas_novas.comparar`) e se falta no painel (régua de
  hoje: `painel_novas.contas_fora_do_painel`). O painel só é olhado quando a
  máquina tem `config.yaml` + `mapping.yaml` (é a máquina do dono); nas
  outras, só o cadastro.
- Aplica as respostas da janela: grava no Supabase (`contas_novas.gravar`) e
  no painel (`painel_novas.incluir_no_painel`), e devolve um recado só.
- Depois de gravar, roda `cadastro.sincronizar` de novo e avisa todas as
  abas (`recarregar_contas()`), que relêem o que precisam.

### A janela única

`nuvem/contas_novas_dialogo.perguntar` ganha duas colunas — "FALTA EM"
(cadastro / painel / os dois) e "LINHA NO PAINEL" — e, no editor, o campo
"nome da linha no painel". Empresa e pasta só valem para quem falta no
cadastro; o nome da linha só para quem falta no painel. Devolve
`Respostas(cadastro=[...], painel=[...])`.

### As abas

- **Saldo de pagamentos:** sai o botão "Verificar contas novas" e todo o fluxo
  dele; `conciliacao/contas_novas_janela.py` é apagado.
- **Relatório Mensal:** sai "Carregar contas". A lista aparece ao abrir a
  aba, lida do `contas_erp.json` + `contas_mc.json`. O id que a tela
  `#/cash-flow` usa é lido no próprio "Gerar os extratos", casando pelo nome
  (a conferência `conferir_antes_de_salvar` continua barrando conta trocada).
- **Baixar Comprovantes:** sai "Atualizar lista" (o botão central relê).
- **Aportes:** sai o link "Recarregar cadastros" (o botão central relê).
- **Remessa/Retorno:** relê a prontidão quando o botão central roda.
- **Anexar:** o botão passa a se chamar "Buscar pagamentos", que é o que ele
  faz. Nada mais muda.

## Fora deste trabalho (anotado)

- A tabela `conta` do Supabase não guarda o id (UUID) do ERP; o casamento é
  por nome. Renomear conta no ERP continua exigindo cuidado.
- `contratos/frame.py` grava `cliente_erp` direto no cache
  `contas_sicoob.json` (`sicoob_contas.adicionar_cliente_erp`), que o
  `sincronizar` sobrescreve na abertura seguinte.
- Aportes e Guias continuam lendo o catálogo de contas do ERP pela página
  (precisam do id para o lançamento).
