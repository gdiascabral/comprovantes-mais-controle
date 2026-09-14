---
paths:
  - "pagamentos_dia/**"
  - "tests/test_pagamentos*.py"
  - "tests/test_remessa*.py"
---

# Arquitetura: pagamentos_dia/

> Trecho da seção "Arquitetura", movido do `CLAUDE.md` em 14/09/2026 sem mudar uma palavra.
> Carrega sozinho quando o Claude lê um arquivo dos caminhos acima.
> Mudou o código? Atualize AQUI — este é o lugar deste texto agora.

- `pagamentos_dia/relatorio.py` — regra de negócio + Excel do relatório dos
  pagamentos do dia (uma aba por conta). Sem navegador e sem tkinter, então
  roda inteiro em teste. Cinco coisas aprendidas lendo a API de produção:
  (1) **boleto ganha de Pix** sempre que houver boleto anexado — o
  `tradePayablePaymentMethod` diz "Pix" só porque o fornecedor tem chave no
  cadastro, e pagar por pix um título que veio com boleto duplica o pagamento;
  (2) `remainingValue` vem **0.0** em título quitado (o valor está em
  `sumOfPaidValues`) — usar só ele zerava o total; (3) `extension` vem COM
  ponto (".pdf"); (4) contas de água/luz se identificam pela **UC e pelo
  endereço**, não pelo "número da NF" (que ali é o número da fatura), e a UC
  aparece no NOME do anexo — dá para conferir sem baixar; (5) o cruzamento
  distingue **DIVERGE** (o documento contradiz o lançamento → ATENÇÃO) de
  **?** (não deu para verificar → não alarma). Alarme falso ensina a ignorar
  alarme. A chave de acesso de 44 dígitos no nome do anexo entrega número da
  NF e CNPJ do emitente de graça.
  `montar_registros` devolve um `Resultado(contas, omitidos)`: **omitir não é
  apagar**. Enquanto "não entrou" era um `continue` mudo, descobrir que uma
  regra errou dependia de sentir falta de um pagamento — o que só acontece
  depois do vencimento. Os omitidos viram a aba "NÃO ENTRARAM", com o motivo
  de cada um, e não somam no TOTAL de conta nenhuma. Três consequências que
  não são óbvias: (a) linha **JÁ PAGA escapa das regras de omissão** — ali
  "sem forma de pagar" é o normal, não defeito; (b) "sem forma de pagar" só
  vale quando NÃO HÁ documento anexado: boleto que virou foto e o OCR não
  fechou continua na planilha, porque alguém abre o anexo e digita; (c) sem
  boleto anexado a regra "boleto ganha de Pix" não tem premissa — não existe
  boleto para ganhar —, então havendo NF ou OC a linha vira Pix com a chave
  do cadastro, e o aviso "pagar o boleto" só é montado DEPOIS de resolver a
  forma de pagar, senão mandaria pagar um documento que não existe.
  (d) **O boleto pode vir DENTRO da nota** (`linha_em_outro_anexo`, 10/09/2026):
  há fornecedor que junta NF e boleto num PDF só, etiquetado "Nota Fiscal" —
  ou até "Recibo", como o de 10/09 —, e há título com dois PDFs sem etiqueta;
  `escolher_pdf_do_boleto` recusa os dois casos pelo rótulo, como deve, e o
  boleto nunca era lido; a linha caía em "sem forma de pagar" e o título
  vencia (nove títulos de 01 a 10/09/2026). Quando o rótulo não acha boleto,
  o texto dos PDFs do título é varrido com a régua do OCR (DV fechando; entre
  várias, a do valor e, empatando, a do vencimento), e o boleto achado ali
  ganha do Pix como qualquer outro. Vários e nenhum que se decida: não se
  escolhe, e a linha fica na planilha para conferir. Fica de fora o que prova
  pagamento — rótulo "Comprovante" ou texto de comprovante —, porque a linha
  dali é de boleto JÁ PAGO, e pagá-la de novo é pagar em dobro.
  (e) **Pix sem chave com QR Code anexado ENTRA** (`anexo_para_pagar_a_mao`,
  11/09/2026). A guia do cartório e o print da compra de marketplace chegam
  sem chave no cadastro e só com a IMAGEM do QR Code; o ramo do Pix nunca
  olhava anexo, então a linha ia para NÃO ENTRARAM como "sem forma de pagar"
  — o boleto em imagem sempre ficou, e este é o mesmo caso. A linha fica com
  "ATENÇÃO — sem dados de pgto" e a Obs diz em QUAL anexo está o QR; o app
  não lê o QR (o exe não tem biblioteca para isso). Comprovante não conta —
  pelo rótulo ou pelo texto de quem já pagou —, e a remessa continua
  recusando a linha (`MOTIVO_SEM_CHAVE`): é pagamento à mão.
- `pagamentos_dia/regras_pagamento.py` — quem NÃO entra na planilha, e por quê.
  Os CRITÉRIOS moram aqui; os NOMES (fornecedor que só recebe por reembolso,
  pessoa cujo pagamento é confirmado antes) ficam em `regras_fornecedor.json` e
  `confirmar_antes.json`, ao lado do exe e fora do repo — como o
  `pix_reembolso.json`. Cadastro ausente ou ilegível não vira erro: o app roda
  igual, só sem as regras. O sufixo `_pagamento` no nome do módulo é
  obrigatório: `aportes/regras.py` já existe, nome de módulo é global no
  sys.path e `pagamentos_dia` entra ANTES de `aportes` — um `regras.py` aqui
  sequestraria o import da aba Aportes (a mesma armadilha do `extratos_sicoob`).
  **O boleto manda no valor.** "R$ 1,00 é marcador de recorrência" vale só
  enquanto nada prova o contrário: havendo código de barras anexado (que é
  conferido por DV e carrega o valor em centavos), quem erra é o LANÇAMENTO, e
  a linha entra com "ATENÇÃO — valor do boleto diverge" em vez de sumir. Sem
  essa ressalva a regra apagava, no arquivo de 08 a 10/08/2026, exatamente uma
  linha — uma conta da Equatorial lançada como R$ 1,00 cujo boleto dizia
  R$ 56,24 — e ninguém sentiria falta antes do vencimento.
  **O tipo da chave Pix não se chuta** (`tipo_de_chave_pix`). O ERP não tem o
  campo: a chave chega dentro de texto livre (`paidToBankAccount`, e o mesmo
  texto no `bankAccount` do cadastro). Medido nos 116 lançamentos com o campo
  preenchido no período, 75 DECLARAM o tipo por escrito ("PIX CNPJ" 65 vezes,
  "PIX CELULAR" 7, "PIX CPF" 3) — é dali que ele sai, e só depois do formato
  inequívoco (o "@", o UUID, a pontuação de CNPJ ou de CPF). **Onze dígitos
  crus devolvem ""**: CPF e celular têm os dois onze, e a planilha prefere
  perguntar a escolher para quem o dinheiro vai. É também o dado que falta
  para montar o segmento B de uma remessa CNAB.
- `pagamentos_dia/ocr_boleto.py` — linha digitável de boleto que veio como
  IMAGEM, e a desconfiança que ela exige. **Texto de OCR nunca passa pelo
  extrator solto**: um `8` lido como `B` paga a conta de outra pessoa sem erro
  na tela e sem volta, então a linha só é aceita depois de (1) fechar os
  dígitos verificadores e (2) codificar o MESMO valor do lançamento. Reprovou,
  volta a ser "preencher manual" — recusar leitura duvidosa é a única falha
  aceitável aqui. Módulo 11 da ficha de arrecadação: só resto 0 e 1 zeram o
  DV; **resto 10 dá DV 1**, e não 0 (conferido contra guias reais de IPTU/ISS
  de Goiânia, onde dois de oito blocos caem nesse resto — zerar os dois casos,
  como o DV geral do boleto bancário faz, reprovava guia legítima).
- `pagamentos_dia/remessa_dia.py` — a regra do passo 3, **sem tela**: quem pode
  sair na remessa e como o arquivo é montado. **Impedimento ≠ desmarcado.**
  Desmarcar é escolha de quem confere; impedido é o que não *pode* sair, e nem
  aparece marcável: observação que manda pagar outra pessoa, pagamento parcial
  como boleto, linha digitável que não fecha nos DVs, e Pix sem o CPF/CNPJ do
  favorecido. **O Pix vale para qualquer tipo de chave**, e quem paga isso é o
  **cadastro de Contatos** (`mc_api.listar_participantes`): os campos
  07.3B/08.3B do segmento B exigem o documento de quem recebe, o lançamento só
  traz o nome (`paidTo`) e nem o id do participante. A ligação é pelo NOME —
  medido em 13/08/2026 sobre 300 lançamentos e 455 participantes: 296 casaram
  e **todos tinham documento**; as 4 sobras eram `paidTo` = "-".
  Duas travas nasceram daí: **nome ambíguo** (dois participantes, documentos
  diferentes) sai do mapa, porque escolher um é pagar com o documento de
  outro; e **onze dígitos crus** só viram chave CPF quando batem com o
  documento DO CADASTRO — se o desempate aceitasse o documento já resolvido,
  ele viria da própria chave e confirmaria a si mesmo.
  O mapa conta-do-ERP → empresa vem do `contas_mc.json` que já existia; um mapa
  a mais seria uma divergência a mais esperando acontecer.
  **`ocr_boleto.codigo_de_barras`** converte a linha digitável (47/48) no código
  de barras (44) que o segmento J exige — e devolve "" para linha cujos DVs não
  fecham, porque a linha pode ter vindo de OCR.
  **`resolver_pagador` lê o convênio da CONTA, e recusa sem herdar.** A
  checagem vem DEPOIS de a conta estar escolhida — antes dela não há conta
  para perguntar —, e não existe `or empresa.convenio`: herdar faria uma
  subconta ainda não aderida sair com o número da principal, que é o campo
  07.0 do header e o nome da sequência do NSA. Conta sem convênio para
  sozinha, com `MOTIVO_SEM_CONVENIO`, e a irmã que já aderiu segue.
  **`_e_sicoob(banco)` aceita `SICOOB`, `756` e `0756`** — o precedente é o
  `nuvem/cadastro._e_inter`, que aceita nome ou código "porque o cadastro tem
  os dois jeitos". Enquanto a comparação era `!= "SICOOB"`, a conta cadastrada
  por código levava `MOTIVO_FORA_SICOOB`: "esta conta é de outro banco" para
  uma conta que É do Sicoob, que é a pior espécie de recado — manda conferir a
  coisa errada. Ela passa a gerar, e o dado torto continua sendo AVISO na
  prontidão, porque é esse campo cru que nomeia o extrato do Relatório Mensal
  (`202607 756 MAIS CONTROLE.pdf`).
  **A prontidão do cadastro (`Conferencia`, `conferir_conta`, `prontidao`)
  mora aqui, e não em `sicoob_contas.impedimentos()`.** Duas razões, e as duas
  são de escopo: aquela função barra o LOTE da aba Extratos — parar 17 contas
  em 12 empresas porque uma está sem convênio é exatamente o dia que este
  código veio devolver —, e ela não conhece o `contas_mc.json`, que é onde
  começa a pergunta ("de que empresa é esta conta do ERP?"). O que ela julga é
  o cadastro do Sicoob sozinho; o que a remessa precisa é dos dois mapas de uma
  vez.
  **`conferir_conta` junta TODOS os problemas; `resolver_pagador` para no
  primeiro** — e a diferença é o motivo de as duas existirem. Quem GERA precisa
  de um veredito ("sai ou não sai"); quem CORRIGE precisa da lista, porque
  descobrir a agência hoje, o convênio amanhã e o CNPJ depois de amanhã é o
  mesmo dia parado três vezes. São dez conferências, na ordem em que o ARQUIVO
  precisaria: banco vazio (falta) ou escrito por código (aviso), a empresa no
  `contas_sicoob.json`, a conta na pasta (com o `sufixo` desempatando), agência
  de 4–5 dígitos, conta COM dígito verificador, **o CNPJ do pagador conferido
  por DV** (`regras_pagamento.documento_valido`, que reexporta o
  `cnab240.dominios` — ninguém conferia o documento de quem PAGA antes do
  validador, e foi um CPF de preenchimento do favorecido que devolveu a remessa
  de 20/08/2026), razão social vazia (aviso: o header cai para o nome de pasta,
  cortado nas 30 posições do campo 13.0), o convênio, e a duplicidade entre
  contas — mesmo convênio, ou mesma agência+conta, é falta nas DUAS, porque não
  há como saber qual delas está errada. Conta de OUTRO banco não entra na
  lista: não é pendência, é conta que não faz remessa CNAB, e uma lista que
  carrega dez contas do Inter para sempre é uma lista que ninguém lê.
  **As duas concordam POR TESTE, e não por disciplina.** `resolver_pagador`
  não tem régua própria: depois das duas perguntas que decidem se a conta
  ENTRA na prontidão (banco vazio, banco de outro banco) ele devolve a PRIMEIRA
  falta da `Conferencia` daquela conta. Duas listas de checagens se separam sem
  ninguém perceber — a tabela diria "pronta" e o botão recusaria, ou, pior, a
  tabela diria "falta" e o arquivo sairia assim mesmo —, e quem impede a volta
  é `test_a_prontidao_e_o_resolver_pagador_concordam`, que roda um cadastro com
  uma conta de cada defeito e exige `c.pronta ⟺ resolver_pagador(...)` devolver
  pagador.
  **`contas_sem_remessa(preparado, gerados)`** é a aritmética do cartão
  "Contas sem remessa" do Início, tirada de dentro do frame para poder ser
  testada — ver o achado K em `pagamentos_frame.py`.
  **`diagnostico_documentos`** existe para fechar a lacuna do Pix: varre o
  `overview` que o "1. Buscar" já trouxe e diz ONDE há CPF/CNPJ válido, sem
  imprimir documento nenhum — só caminho, contagem e **valores distintos**. É o
  "distintos" que separa o fornecedor (um por lançamento) da própria empresa (o
  mesmo em todos). Os DVs são conferidos: sem eles todo celular de onze dígitos
  viraria "CPF encontrado", a mesma armadilha do `tipo_de_chave_pix`. Um campo
  que aparece em 1% dos lançamentos é acaso (dois DVs fechando por sorte), não
  achado — daí a contagem estar no relatório.
  **`nome_do_arquivo` leva agência-conta desde 04/09/2026** (`REM_<EMPRESA>_
  <AG>-<CONTA>_<NSA>.REM`): o convênio do Sicoob é POR CONTA CORRENTE, o NSA
  recomeça em cada uma, e sem a agência-conta no nome uma holding com várias
  subcontas gerava o mesmo nome em pastas diferentes — a pasta separa, mas o
  arrasto para o SicoobNet mostra só o nome.
  **`MOTIVO_CNPJ` diz os DOIS casos desde 04/09/2026** ("o CNPJ da empresa está
  vazio ou não fecha no dígito verificador"), porque a checagem é uma só:
  `documento_valido` recusa o campo em branco pelo mesmo caminho que recusa o
  DV torto, e o cadastro sem CNPJ é o caso comum (conta nova, empresa
  recém-criada no painel). Mandar conferir o dígito verificador de um campo
  vazio é perder a tarde no lugar errado.
- `pagamentos_dia/painel_dia.py` — **a visão do DIA e as duas transições que o
  app não expunha**, puro e sem tela (04/09/2026). Com uma conta, a pergunta do
  dia é "quem foi pago", e quem responde é a janela do retorno, pagamento a
  pagamento. Com dezoito, ela vira **"qual conta ainda não fechou"** — e a
  resposta não está em coluna nenhuma: sai do cruzamento de `remessa.estado`
  com o `remessa_item.retorno_estado` que o retorno grava. `linhas_do_dia`
  recebe a forma que `Registro.remessas_do_dia` devolve e conta
  pago/aguardando/rejeitado/sem resposta por item, somando o `valor` em
  Decimal; `situacao` devolve `(tag, frase)` para as seis situações — gerada,
  enviada sem retorno, aguardando assinatura, rejeitada, paga e descartada.
  Duas ordens que não são a da leitura: **descartada vem antes de tudo** (a
  remessa saiu de conta, e o que os itens dela dizem já não pesa) e
  **rejeitado ganha de pendente**, como em `_situacao_do_retorno` — um item
  recusado é o que faz alguém abrir o detalhe hoje.
  **Por que ele precisou existir**: `Registro.marcar` está no código desde
  17/08/2026 e nenhuma tela o chamava. Toda remessa ficava `gerado` até alguém
  ler o retorno, então a que NUNCA subiu ao SicoobNet era indistinguível da que
  subiu — e, pior, o pagamento de uma remessa que jamais foi ao banco ficava
  bloqueado **para sempre**: `remessa_dia._ja_enviado` só enxerga item de
  remessa VIVA, e só `descartado` sai de `ESTADOS_VIVOS`. Arquivo gerado por
  engano, recusado na subida ou substituído por outro continuava segurando os
  seus pagamentos, e a única saída era mexer no banco pelo painel do Supabase.
  **As duas regras de transição, que são de dinheiro e por isso moram aqui e
  não no frame** (o que só se testa abrindo janela não se testa):
  `pode_marcar_enviada` só de `gerado` — de qualquer outro estado a marca não
  acrescenta nada e pode TIRAR, porque sobre uma remessa `processado` ela
  apagaria o desfecho que o retorno gravou e a conta voltaria à lista do que
  falta acompanhar com o dinheiro já pago; e `pode_descartar`, que recusa em
  dois casos. **Nunca com item PAGO**: descartar devolve TODOS os pagamentos da
  remessa à fila da geração seguinte, com NSA novo e nenhum alarme, e numa
  remessa em que o banco já pagou alguém isso é autorizar o mesmo dinheiro a
  sair duas vezes — um item pago no meio de vinte rejeitados basta para a
  resposta ser não, e o certo ali é reenviar o que faltou numa remessa nova.
  **Nunca sem motivo por escrito** (≥ 5 caracteres), pela regra do
  `ajustar_nsa`: o histórico é append-only, e uma remessa `descartado` sem uma
  linha dizendo por quê é um furo na sequência de NSA que ninguém explica meses
  depois. `motivo=None` pergunta só pelas travas de estado — é o que o BOTÃO
  usa para saber se habilita; com o texto, o motivo entra na conferência.
  `observacao_do_descarte` monta a frase que vai para a coluna `observacao`,
  uma só para a nuvem e para o espelho local: escrita duas vezes, comparar os
  dois registros passaria a exigir traduzir um texto no outro.
- `pagamentos_dia/pagamentos_frame.py` — aba Pagamentos do Dia, em 3 passos
  (Buscar / Gerar planilha / Gerar remessa). **O passo 3 não passa pelo
  `anx.submeter`**: não há navegador nem ERP nele — a remessa sai do
  `self.resultado` que o passo 2 deixou em memória, e escrever texto local não
  justifica ocupar a sessão que só aceita um por vez. **Reserva o NSA, valida,
  grava e registra — nessa ordem.** Arquivo reprovado não é escrito, mas o NSA
  já foi reservado e fica **queimado**: o número entra no CONTEÚDO do arquivo
  (o G018 do header, que é o que o validador confere), então não há como
  validar antes sem validar um arquivo sem número, e espiar aqui para reservar
  depois abriria a janela em que a outra máquina pega o mesmo. É o lado certo
  de errar — pular número é inofensivo, repetir pode ser pagamento em dobro.
  O número queimado **não deixa rastro**: `alocar_nsa` só empurra o
  `remessa_contador` da nuvem, o `remessas.json` só aprende um NSA quando
  `registrar` é chamado, e `remessa_ajuste`/`ajustes` guardam só a correção
  manual do contador (`ajustar_nsa`, que exige motivo por escrito). O furo
  aparece como número faltando na sequência, e ninguém o explica por escrito.
  Compartilha navegador e thread do Anexar. O passo separado
  existe porque quem confere quer VER a lista de contas antes de gerar, e cada
  rodada custa uma sessão do ERP (que só aceita uma por usuário). Contas
  "APENAS LANÇAMENTO/AJUSTE" aparecem desmarcadas, não escondidas. As chaves
  Pix dos avisos "PAGAR PARA" ficam em `pix_reembolso.json` ao lado do exe —
  é CPF de gente, não entra no repositório. A janela de confirmação dos
  pagamentos aos sócios abre em `gerar()`, na thread da INTERFACE e **antes**
  de `submeter()`: quem cancela ali não pode ter consumido a sessão do ERP.
  Anexo que é foto só é baixado quando é aviso "PAGAR PARA" — baixar toda
  imagem de todo título seria pagar OCR por nada.
  **As duas listas de conferência são UMA tabela cada (11/09/2026).** A
  confirmação "Lançamentos do dia" (`_janela_confirmar`) e a conferência da
  remessa (`_janela_remessa`) eram um bloco de widgets por lançamento dentro
  de um Canvas rolável, o mesmo desenho que travava a janela de dúvidas do
  Anexar: medido com a janela fora da tela e dados fictícios, 300 lançamentos
  davam 2.802 e 3.589 widgets, 5,4 s e 6,5 s antes de a janela aparecer — e
  a rolagem ainda arrastava essas janelas nativas todas. Hoje cada uma é um
  `Treeview`, os mesmos widgets com 3 ou 300 linhas. O que o Treeview não
  faz foi resolvido assim: a marca é o símbolo ☑/☐ da primeira coluna
  (clique nela ou Espaço — na confirmação várias linhas de uma vez, na
  remessa uma por vez, de propósito, para um "já saiu na remessa nº…" nunca
  ir junto sem ser lido); a conta é uma linha em negrito em cima das suas
  (por isso a tabela não ordena pelo cabeçalho); a coluna POR ONDE tem a
  largura mínima MEDIDA no texto mais comprido, pelo `font measure` do Tcl,
  porque o Treeview corta sem aviso e ali mora a linha digitável; e a linha
  selecionada se repete embaixo, inteira, com o destino em fonte de largura
  fixa. O reembolso e o reenvio, que moravam na 2ª e na 3ª altura da célula,
  sobem para a SITUAÇÃO. A regra saiu da tela e tem teste
  (`tests/test_listas_de_conferencia.py`): `grupos_para_confirmar`,
  `resumo_da_confirmacao`, `nao_confirmados` e `estado_na_confirmacao` aqui;
  `nsa_previstos`, `resumo_da_conferencia` e `aplicar_marcas` no
  `remessa_dia`. A janela de contas novas da abertura
  (`nuvem/contas_novas_dialogo.py`) virou lista + editor pelo mesmo motivo:
  21 contas custavam 2,2 s. **Lista que cresce com o dado é UMA Treeview,
  nunca N widgets num Canvas** — as listas de contas desta aba e do
  Relatório Mensal ficaram no Canvas porque medem 0,1 s com 40 contas.
  **"Contas prontas para remessa" é UMA LINHA no cartão e a TABELA numa
  janela — e quem decidiu isso foi a régua do Registro.** O PR #55 pôs aqui um
  cartão com `Treeview` de oito linhas, e ele empurrou o Registro para fora da
  janela: `tests/test_registro_visivel.py` ficou vermelho na `main` em três
  casos, com o campo em 1,4 linha (48 px) a 1,25x e o cabeçalho da aba parando
  ABAIXO dele. A causa não é o cartão ser feio, é aritmética de altura: o
  Registro era o último a ser empacotado nas onze telas, então ficava com a
  SOBRA (desde 11/09 ele fica preso no pé e quem cede é a `AreaRolavel`), e o
  teste cobra que ele mostre ao menos quatro linhas legíveis a 1,0x e a 1,25x. MEDIDO na moldura do teste (1920x1040), acima desse piso sobram
  **103 px** para este cartão, e a tabela custava 149. Daí a forma de hoje, e
  as duas consequências que não são estilo: a lista inteira mudou-se para a
  janela do "Ver detalhes" (`tk.Toplevel` modal, como as outras da aba), que é
  onde ela pertence — quem a lê está indo ao painel do Supabase corrigir
  cadastro, o que acontece raramente, enquanto o Registro é lido em toda
  rodada; e **o cartão ficou SEM cabeçalho**, porque um `Cartao` titulado custa
  120 px só de moldura, título e filete, contra os 103 disponíveis — caberia a
  moldura e não o que ela emoldura. Sem ele são 88 px, e quem nomeia o assunto
  passa a ser a própria frase, que diz "prontas para remessa" nos quatro
  estados (`resumo_da_prontidao`, função de módulo pelo mesmo motivo de
  `remessa_dia.contas_sem_remessa`: dentro do frame só se testaria abrindo
  janela). A pílula é `widgets.Pilula`: `ok` quando não sobra pendência,
  `atencao` quando sobra, `info` enquanto ninguém conferiu ou o cadastro não
  abriu — e o DETALHE do erro fica para a janela, porque na pílula ele viraria
  três linhas, que é a altura que este cartão não tem.
  **O resumo é apurado quando a aba é MOSTRADA, não na construção.** O
  esqueleto (a pílula e o link) nasce no `_build`, porque custa microssegundos;
  quem custa é LER os dois JSON, e isso acontece no `ao_abrir()` — o mesmo
  gancho que o Início usa, chamado por `comprovantes_app.mostrar` a cada troca
  de aba. As doze abas somam ~1,2 s na abertura do app (a Início sozinha
  ~670 ms), e pagar disco adiantado por uma linha que ninguém está olhando é o
  oposto do que se quer. De graça: quem corrigiu o cadastro no painel não
  precisa reabrir a aba de propósito — sair dela e voltar já relê —, e há um
  "Conferir de novo" no rodapé da janela. **Custo real: dois arquivos locais.**
  Sem rede, sem ERP e sem navegador, então roda na thread da interface.
  **A leitura do retorno é de VÁRIOS arquivos, e o `.RET` passou a ser
  guardado.** O retorno nunca foi um arquivo só: são até 18 contas no mesmo
  dia, cada uma lida DUAS vezes (a primeira volta `PD`, pendente de
  assinatura; a segunda, depois de o master liberar), e o SicoobNet
  ("Gerenciamento de Arquivos → Obter Retorno") baixa vários de uma vez,
  soltos ou num `.zip`. Um `askopenfilename` no singular, uma janela modal por
  arquivo e 35 rodadas é o caminho mais curto para alguém deixar de conferir
  uma conta. Hoje o diálogo é `askopenfilenames`, aceita `.zip` junto, e
  `retorno_dia.ler_varios` devolve uma lista de `Resumo` **e `Falha`**: o
  arquivo que não é retorno, o zip corrompido e o membro ilegível viram uma
  linha vermelha na tabela em vez de derrubar a leitura dos outros — a essa
  altura o diálogo de escolha já foi fechado, e parar no primeiro erro custa a
  escolha inteira. **Um arquivo só e sem falha continua abrindo a janela de
  sempre**, que é o caso comum e já estava certo; do segundo em diante abre a
  `_janela_retornos`, uma linha por arquivo (empresa, ag-conta, NSA, os quatro
  contadores, total e situação), com o detalhe de sempre a um duplo clique —
  a mesma `_janela_retorno`, reaproveitada, e não uma segunda tela dizendo a
  mesma coisa de outro jeito. A remessa que o registro central não conhece sai
  em âmbar, porque é ela que decide o que dá para fazer com a linha: sem
  registro não há o que guardar nem como baixar. "Guardar tudo" é um
  `aplicar_retorno` por remessa, e uma que falhe não fala pelas outras; "Dar
  baixa no Mais Controle" junta as linhas `ok` de TODAS as remessas conhecidas
  num saco só, porque a baixa não depende da conta pagadora — ela casa pela
  `referencia` do item, que é o id do lançamento no ERP.
  **O retorno casa por DOIS caminhos, e o segundo é o "seu número"
  (04/09/2026).** O primeiro é o header do arquivo — convênio + NSA —, e ele
  falha em casos reais: retorno de remessa gerada por outra máquina antes do
  registro central, convênio reescrito no painel, NSA ajustado à mão. Até aqui
  isso virava `remessa_desconhecida`: a tela lia o arquivo e não guardava nem
  dava baixa, porque a `referencia` de cada linha — o id do lançamento no ERP —
  só existe com a remessa conhecida. **O "seu número" é a chave melhor para o
  segundo caminho porque ela é NOSSA**: `yymmdd-NNNN[-OC…]`, 20 posições que
  nós definimos e o banco devolve idênticas, únicas no dia entre todas as
  contas e todas as máquinas desde o índice
  `remessa_item_seu_numero_unico_no_dia`, e o `remessa_item` a guarda com a
  `remessa` ligada. Falhando o header, `retorno_dia._itens_da_remessa` pergunta
  `historico.remessa_dos_seus_numeros([seu de cada pagamento do arquivo])`;
  achando, o `Resumo` passa a carregar o convênio e o NSA **DO REGISTRO** (é
  para essa remessa que o `aplicar_retorno` grava e é esse número que nomeia a
  cópia do `.RET`), guarda os do arquivo em `convenio_do_header`/`nsa_do_header`
  e marca `casado_pelo_seu_numero` — que vira a linha de aviso na janela e o
  prefixo "reencontrado ·" na lista consolidada, porque a partir daí os números
  da tela não são os do arquivo que a pessoa tem aberto no SicoobNet.
  **Ele exige que TODOS os "seus números" achados caiam na MESMA remessa.** O
  índice é PARCIAL pela data (`criado_em >= 2026-09-05`), porque o histórico é
  append-only e a repetição de 20/08/2026 continua lá dentro — naquele dia a
  segunda remessa do dia repetiu `260820-0004`…`0010`. Um número daquela época
  aponta para duas remessas, e escolher uma é aplicar o retorno na remessa
  errada: dar por pago o pagamento de outra conta e baixar o lançamento errado
  no ERP. Duas remessas, ou nenhuma, devolve `None`, e o desfecho volta a ser o
  `remessa_desconhecida` de sempre — que é o que já existia e não custa nada.
  A consulta da nuvem **não filtra estado**, ao contrário do `_procurar`: aqui
  não se pergunta onde o pagamento ainda vale, e sim de que remessa o arquivo
  fala, então a descartada que compartilhe o número é a segunda candidata que
  faz recusar. O espelho local (`cnab240.Historico.remessa_dos_seus_numeros`,
  que substituiu o `item_por_seu_numero`) filtra vivos, como o resto dele — e o
  app pergunta sempre à nuvem, pelo `Espelhado`, porque o caso que este caminho
  existe para resolver é o retorno de uma remessa gerada em OUTRA máquina.
  **O `.RET` é COPIADO para a pasta da conta, e nunca sobrescrito.** Até aqui
  ele ficava só onde o navegador o baixou: passada a janela, a única prova do
  que o banco respondeu era o que tinha ido para o banco de dados. Agora, ao
  guardar, `retorno_dia.guardar_copia` grava
  `RET_<EMPRESA>_<AG>-<CONTA>_<NSA>_<AAAAMMDD-HHMM>.RET` na pasta do `.REM`
  que aquela remessa gerou (o caminho vem do próprio registro,
  `remessa.arquivo`) — pergunta e resposta na mesma pasta —, caindo em
  `<destino do dia>/_RETORNOS/` quando a pasta não existe nesta máquina.
  **Copiar e não mover**: o arquivo está na pasta de downloads, é de lá que a
  pessoa o reabre, e movê-lo faria sumir o que ela acabou de baixar. **Nome
  repetido vira `-2`, `-3`…, jamais sobrescrita**: o mesmo NSA é lido duas
  vezes, e o primeiro `.RET` é a prova de que o arquivo foi ACEITO — é o mesmo
  defeito que o `retorno_historico` fechou do lado do banco. A cópia é
  best-effort e vem DEPOIS do `aplicar_retorno`: falhar ali vira uma linha no
  Registro, nunca um retorno que deixou de ser guardado.
  **O zip é lido em memória, sem `tempfile`.** `zipfile.read(nome)` devolve os
  bytes do membro sem tocar o disco, e o `zipfile` já está no exe (o
  `atualizador.py` troca o `codigo.zip` com ele). Extrair para `tempfile`
  traria um módulo da biblioteca padrão que ninguém importa hoje, e módulo que
  ninguém importa não entra no exe — é a v1.0.71 da regra de ouro, medida por
  `tests/test_imports_do_motor.py`. É por causa do zip que a regra da leitura
  mora em `retorno_dia.ler_conteudo(texto, nome, historico)`, sobre TEXTO:
  membro de compactado não tem caminho no disco, e `ler(caminho)` virou a
  casca que abre o arquivo.
  **O cartão "Contas prontas para remessa" é montado quando a aba é MOSTRADA,
  não na construção.** O esqueleto (o `Treeview` e o rodapé) nasce no `_build`,
  porque custa microssegundos; quem custa é LER os dois JSON, e isso acontece
  no `ao_abrir()` — o mesmo gancho que o Início usa, chamado por
  `comprovantes_app.mostrar` a cada troca de aba. As doze abas somam ~1,2 s na
  abertura do app (a Início sozinha ~670 ms), e pagar disco adiantado por uma
  tabela que ninguém está olhando é o oposto do que se quer. De graça: quem
  corrigiu o cadastro no painel não precisa reabrir a aba de propósito — sair
  dela e voltar já relê —, e há um "Conferir de novo" no rodapé. **Custo real:
  dois arquivos locais.** Sem rede, sem ERP e sem navegador, então roda na
  thread da interface.
  Cinco colunas — `CONTA (ERP) · EMPRESA · AG-CONTA · CONVÊNIO · SITUAÇÃO` —,
  e a situação é `✓ pronta`, `⚠ falta: agência, convênio` ou `· aviso: …`: o
  símbolo vem de `widgets.MARCAS_ESTADO` e a cor da tag do `widgets`, nenhuma
  escrita aqui. **Falta é `atencao` e não `erro`** porque nada falhou — o
  cadastro está incompleto e ninguém tentou gerar nada ainda. O rodapé da
  janela diz "corrija no painel do Supabase e reabra o app", e o "reabra" não é
  zelo: o cache só é regravado na abertura (`nuvem.cadastro.sincronizar`).
  A MESMA lista aparece no lugar dos dois recados genéricos do `gerar_remessa`:
  quando os `carregar()` levantam (aí sem tabela, porque não há cadastro para
  conferir — o que o recado ganhou foi o `contas_mc.carregar` dizendo QUAL
  linha está torta) e quando `pagadores` sai vazio, onde "Nenhuma conta marcada
  gera remessa" passa a listar `conta: faltas` — todas as faltas, e não só o
  primeiro motivo, porque quem lê ali vai consertar.
  **Achado K: o dia em que NENHUM arquivo sai também é um dia em que alguém
  rodou.** `_gravar_remessas` só chamava `auditoria.registrar` no caminho em
  que houve arquivo, e o cartão "Contas sem remessa" do Início mostrava "—" —
  exatamente o que ele mostra quando ninguém rodou nada. O pior dia do mês
  ficava indistinguível de um dia comum. Hoje registra nos dois desfechos, com
  `resultado="atencao"` quando nada saiu, e a aritmética é a mesma função pura
  nos dois (`remessa_dia.contas_sem_remessa`): escrita duas vezes, seria o
  mesmo cartão dizendo duas coisas.
  **O "Painel do dia" é JANELA e é um botão da BARRA DE AÇÕES, e as duas
  coisas são a mesma régua** (`_janela_painel_do_dia`, 04/09/2026). Ele entra
  na linha de "Abrir planilha" / "Abrir local da remessa" / "Ler retorno",
  porque tem o papel deles — não é passo do fluxo, é uma janela que se abre
  para olhar o que já aconteceu, e o arquivo chega ao SicoobNet horas depois.
  Uma FAIXA nova ali entraria na doca, presa no pé junto do Registro, e
  sairia da parte da aba que rola em toda rodada (antes de 11/09 saía do
  próprio Registro — foi o que o PR #55 pagou com a tabela de prontidão); um
  botão a mais na mesma linha custa largura, e largura sobra. Dez colunas —
  `EMPRESA · AG-CONTA · ARQUIVO Nº · GERADA ÀS · SITUAÇÃO · PAGOS · AGUARDA ·
  REJEIT. · SEM RESP. · TOTAL` —, com a SITUAÇÃO antes dos contadores porque
  ela é a resposta e os quatro números são a conferência. Um `CampoData` com
  hoje e "Recarregar" no alto; toda ação escreve no Registro da aba e recarrega
  a lista, porque decidir a próxima pelo que já estava na tela é decidir pelo
  que era verdade quando a janela abriu.
  **O rodapé habilita o que a linha aceita, com uma exceção deliberada**:
  "Marcar como enviada" só acende em `gerado` (`painel_dia.pode_marcar_enviada`)
  e "Abrir a pasta" só com `arquivo` gravado, mas **"Descartar…" continua
  clicável mesmo quando a resposta é não** — a recusa de `pode_descartar` diz
  POR QUE (o item que o banco já pagou), e botão apagado não ensina isso a quem
  precisa justamente entender por que aquela remessa não sai da frente. A trava
  de estado é conferida ANTES de pedir o motivo: escrever a justificativa e só
  então ouvir "não dá" é o pior desfecho possível desta tela. E o registro
  central confere as duas regras DE NOVO ao gravar — `marcar_enviada` e
  `descartar` releem a remessa —, o que não é redundância boba: a regra do item
  pago precisa dos ITENS, e outra máquina pode ter guardado um retorno desde
  que a janela abriu.
  **Sem nuvem a janela ABRE**, ao contrário do `gerar_remessa`, que é a única
  operação do app que para: aqui a tela é de acompanhamento, e recusar-se a
  abrir esconderia até o recado que explica por quê. Ela abre com a linha de
  aviso preenchida e sem linhas — a mesma linha que carrega a data inválida, o
  erro da consulta e o "nenhuma remessa neste dia", porque as quatro respondem
  à mesma pergunta (por que a tabela está vazia?) e três labels dariam três
  lugares para procurar a resposta.
  **"Gerar HTML dos pagamentos" é PROVISÓRIO** (11/09/2026, até a remessa
  CNAB virar o caminho do dia). Botão da barra de ações, aceso depois do
  passo 2: grava na pasta da planilha `pagamentos_<período>.html` (todas as
  contas do `self.resultado`, com "Copiar" e a caixa "já paguei", guardada
  pelo id do lançamento) e `pagamentos_pessoa_fisica_lancamento_<período>.html`
  (a conta PESSOA FISICA - APENAS LANÇAMENTO, tirada da lista do passo 1 —
  que traz vencimento, categoria, nº doc e centro de custo —, com o PDF no
  layout do Mais Controle), e abre o geral. Sem ERP e sem rede, na thread da
  interface. Substitui o script que rodava fora do app. Os modelos são
  TEXTO em `pagamentos_dia/modelos_html.py` (o `codigo.zip` não leva
  `.html`), a regra é `pagamentos_dia/html_pagamentos.py` (pura, com
  `tests/test_html_pagamentos.py`), e nada da empresa mora no repositório: o
  logotipo e o rodapé do PDF vêm de `logo_relatorio_pf.png` e
  `rodape_relatorio_pf.txt` ao lado da planilha (ou do app), e faltando saem
  em branco. **Para remover**: apagar os dois módulos e o teste, o método
  `_gerar_html_pagamentos` e as linhas marcadas "HTML provisório" deste
  arquivo (import, botão `b_html` e as duas que o acendem e apagam), e este
  parágrafo.
