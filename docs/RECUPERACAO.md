# Recuperação: de uma máquina Windows limpa até a primeira remessa

O sistema é mantido por uma pessoa só. Enquanto este arquivo não existia, o
procedimento de voltar a operar depois de uma máquina perdida morava na cabeça
dela — e a hora de descobrir o que falta é justamente a pior: com pagamento do
dia esperando.

Este runbook vai de **Windows recém-instalado** até **uma remessa gerada e uma
conferência de saldos feita**. Ele é montado SÓ com o que os arquivos do
repositório já dizem (`CLAUDE.md`, `README.md`, `instalar.bat`,
`Comprovantes.bat`, `atualizador.py`, `motor.py`, `.github/workflows/build.yml`
e os módulos citados em cada passo). Onde eles não dizem, está escrito
**NÃO DOCUMENTADO — dono preenche** em vez de um palpite: palpite em runbook de
recuperação é pior que lacuna, porque parece resposta.

**Tempo medido: ___**
(preencher depois de executar isto numa máquina limpa, com cronômetro. Anote
também o que travou e onde — é esse número que decide se o plano B é "reinstalo
em uma hora" ou "fico um dia parado".)

## Legenda

- **[CREDENCIAL]** — o passo pede senha, token ou chave. O rótulo diz QUAL.
  São duas na máquina, e elas não se substituem:
  - **senha do ERP** (Mais Controle), guardada em `login.dat`, cifrada pela
    DPAPI do Windows. É por pessoa, e nunca vai para a nuvem;
  - **conta do Supabase** (e-mail e senha de quem entra no app), que abre o
    cadastro e o registro das remessas. A sessão fica em `sessao.dat`, na mesma
    DPAPI.
  - O `TOKEN_ARTEFATOS` **não entra aqui**: é segredo do CI, usado pelo
    `build.yml`/`liberar.yml` para publicar a release no repositório de
    artefatos. Máquina nenhuma precisa dele.
- **[PAINEL]** — o passo é clique no painel do Supabase ou na página do GitHub,
  não no app.

## O caminho curto (o que este runbook faz)

1. Chrome instalado.
2. Baixar o `Comprovantes Mais Controle.exe` da release e pôr numa pasta
   própria.
3. Abrir. Entrar com a conta do Supabase — **o cadastro desce sozinho**.
4. Repor os três arquivos que a nuvem NÃO traz.
5. Guardar a senha do ERP.
6. Gerar uma remessa (aba Remessa/Retorno).
7. Fazer a conferência de saldos (aba Saldo de pagamentos).

---

## 1. Google Chrome

O app não traz navegador: o `README.md` diz "só do **Google Chrome**
instalado", e o `anexar/mc_client.py` usa `channel="chrome"`, isto é, o Chrome
DA MÁQUINA — não o navegador que o Playwright baixa. Sem ele, a aba Anexar (e
as cinco que dividem o navegador dela) não começa.

**NÃO DOCUMENTADO — dono preenche**: de onde vem o Chrome nesta máquina — qual
instalador, qual canal, se há versão mínima. O único lugar do repositório que
instala navegador é o `instalar.bat`, com
`python -m playwright install chrome`, e ele é do caminho por SCRIPT (seção 9),
não do exe.

## 2. Baixar o executável — [PAINEL] (GitHub)

Página de releases do repositório de código:
`https://github.com/gdiascabral/comprovantes-mais-controle/releases/latest`
(o link do `README.md`). Baixe **`Comprovantes Mais Controle.exe`**.

Duas coisas que valem saber aqui, e que não estão na página:

- **o app não se atualiza a partir desse repositório.** A constante `REPO` do
  `atualizador.py` é `gdiascabral/comprovantes-releases` — é lá que ele procura
  a `latest`. O repositório de código continua publicando a sua cópia porque é
  o arquivo histórico;
- **toda build nasce como prévia.** O `build.yml` publica `prerelease: true` nos
  dois repositórios, e só o workflow "Liberar uma versão para os usuários"
  ([PAINEL], aba Actions) a promove a `latest`. Uma prévia não é baixada por
  máquina nenhuma — para testar uma antes de liberar, crie `travar_versao.txt`
  ao lado do exe com a tag dentro (`atualizador._tag_travada`), que é também
  como se volta de uma release ruim.

Na primeira execução o SmartScreen avisa: **Mais informações → Executar assim
mesmo**. O exe não tem assinatura digital (`CLAUDE.md`, "Restrições
importantes"); assinar está nas ideias pendentes.

## 3. Onde o exe mora — e por que a pasta importa

Ponha o exe numa **pasta própria**. Tudo que o app guarda nasce ao lado dele:
`util.pasta_base()` devolve a pasta do executável quando congelado, e é dali
que saem o cache do cadastro, os perfis do Chrome, os logs e o `sessao.dat`.
Exe solto na Área de Trabalho espalha isso pela Área de Trabalho.

**NÃO DOCUMENTADO — dono preenche**: qual é a pasta que a máquina anterior
usava. O `README.md` diz "ex.: `C:\Comprovantes`" — exemplo, não o caminho
real. Se houver backup dos arquivos da seção 5, ele tem de voltar para ESTA
pasta.

## 4. Primeira abertura: entrar — [CREDENCIAL: conta do Supabase]

Ao abrir, `comprovantes_app.main()` tenta entrar sozinho
(`login_dialogo.entrar_sozinho`) e, não conseguindo, pede e-mail e senha. Numa
máquina limpa não há `sessao.dat`, então **ele sempre pergunta**.

O que essa senha é (e não é): é a da **sua conta no Supabase**, criada quando o
login por pessoa substituiu a senha de ativação (`CLAUDE.md`, "O cadastro mora
na nuvem"). Não é a senha do ERP. A sessão resultante fica em `sessao.dat`,
cifrada pela DPAPI — só o mesmo usuário do Windows, nesta máquina, a decifra.
Restaurar `sessao.dat` de backup **não funciona por desenho**, e isso é
proteção, não defeito: máquina nova entra digitando a senha.

Se a conta for nova (e não a que já existia), ela entra e **não alcança nada**
até um administrador liberá-la: desde 30/08/2026 toda política do banco exige
`privado.e_ativo()`. Liberar é [PAINEL] (Supabase, tabela `perfil`) ou, no app
de um admin, a tela **Usuários**. Se a suspeita for que o projeto está
configurado de um jeito e o repositório descreve outro — cadastro desligado,
confirmação de e-mail, endereço de retorno —, a lista de conferência campo a
campo é o `docs/SUPABASE-PAINEL.md`.

## 5. O cadastro desce sozinho — menos três arquivos

**Confirmado no `CLAUDE.md`** ("Os JSON/CSV continuam existindo — como CACHE"):
`nuvem/cadastro.sincronizar` roda **uma vez, na abertura**, e regrava os
arquivos de sempre, no formato de sempre, na pasta do exe. Máquina nova recebe
o cadastro só por entrar. A lista, lida de `nuvem/cadastro.sincronizar`:

`contas_sicoob.json`, `contas_mc.json`, `contas_inter.json`, `subcontas.json`,
`regras_fornecedor.json`, `confirmar_antes.json`, `regras_boletos.json`,
`pix_reembolso.json` e `contas.csv`.

Duas garantias que valem conhecer antes de se assustar: **vazio nunca substitui
cheio** (banco sem empresas ou sem contas faz o `sincronizar` recusar tudo), e
**banco mudo não impede o app de abrir** — ele usa a última cópia e escreve
"⚠ cadastro offline" no rodapé. Numa máquina limpa não há última cópia: se
aparecer "cadastro offline" aqui, PARE e resolva a rede antes de seguir.

### Os três que a nuvem não traz

`config.yaml`, `mapping.yaml` e `MODELO.xlsx` ficaram FORA da nuvem de
propósito: são a estrutura da planilha da Conciliação, versionados junto do
modelo que descrevem (`CLAUDE.md`, "O que NÃO subiu, de propósito"), e também
ficam fora do repositório, que é público. Sem eles a aba **Saldo de pagamentos**
não gera planilha — é o passo 8 deste runbook.

**NÃO DOCUMENTADO — dono preenche**: onde está o backup de `config.yaml`,
`mapping.yaml` e `MODELO.xlsx`, e como trazê-lo para a pasta do exe. Nenhum
arquivo do repositório diz onde essa cópia vive.

## 6. A senha do ERP — [CREDENCIAL: senha do ERP, em `login.dat`]

No app: aba **Anexar** → **🔑 Login** → e-mail e senha do Mais Controle. O
`anexar/credenciais.salvar` cifra com a DPAPI e grava `login.dat` ao lado do
exe. A partir daí o app entra sozinho.

É a MESMA credencial que a leitura de saldos usa por API
(`conciliacao/erp/auth.obter_credenciais` → `credenciais.carregar()`): duas
senhas guardadas em cofres diferentes só criam a chance de uma envelhecer e o
erro virar "login inválido" sem motivo aparente.

Como o `sessao.dat`, o `login.dat` **não se restaura de backup**: a DPAPI o
recusa noutra máquina, e o certo é voltar a pedir a senha
(`util.revelar_bytes`). Digite de novo.

Duas recusas que o próprio `erp/api.py` sabe nomear, e que aparecem aqui se
existirem: **MFA ligado** nesta conta e **troca de senha exigida** pelo ERP. As
duas param o login automático — resolva no site antes de seguir.

## 7. Gerar uma remessa — aba **Remessa/Retorno**

Três passos na tela, nesta ordem (`pagamentos_dia/pagamentos_frame.py`):

1. **Buscar os lançamentos** — abre o Chrome, entra no ERP com a senha do passo
   6 e lê os pagamentos do período;
2. **Gerar a planilha** — o Excel de conferência, uma aba por conta;
3. **Gerar remessa** — o CNAB 240.

O que precisa estar de pé para o passo 3 funcionar, e não é óbvio:

- **a nuvem.** Sem ela a aba **se recusa a gerar remessa** — é a única operação
  do app que faz isso. O NSA (número sequencial do arquivo) é alocado por
  `nuvem/registro.alocar_nsa`, numa instrução só no Postgres; um contador local
  diria um número que a outra máquina já pode ter usado, e repetir NSA pode
  significar pagamento em dobro;
- **o `remessas.json` não é mais a autoridade do NSA** — ele continua sendo
  escrito como espelho, e o espelho não tem voto. Máquina nova começa sem ele e
  isso está certo;
- **o ERP aceita uma sessão de navegador por usuário.** Não rode os `.bat` da
  Conciliação com o app aberto.

Confira o arquivo: o número exibido antes de gerar é **previsão**
(`proximo_nsa` só olha); o que sai no arquivo é o que `alocar_nsa` reservou.
Arquivo reprovado na validação não é gravado **e não consome o NSA**.

## 8. Conferência de saldos — aba **Saldo de pagamentos**

Um botão: **Coletar e gerar o painel**. Ele lê os saldos pela API REST do ERP
(`conciliacao/erp/api.py`, sem navegador) e os pagamentos a vencer pela grade,
e escreve o painel do dia sobre o `MODELO.xlsx`, em
`C:/Arquivos Morais/CONCILIACAO DIARIA/<ANO>/<MÊS>/`.

Depende dos três arquivos da seção 5. Sem eles, este passo é onde a máquina
nova para.

## 9. O caminho por script (só se o exe não servir)

`instalar.bat` (`pip install -r requirements.txt` +
`python -m playwright install chrome`) e depois `Comprovantes.bat`
(`python comprovantes_app.py`). Duas ressalvas do `CLAUDE.md`:

- **o exe roda Python 3.11**, e a máquina de quem desenvolve quase nunca é.
  Código que passa aqui pode falhar lá;
- **o OCR local exige o Tesseract instalado com o idioma `por`** — pelo exe não
  precisa (próxima seção).

## O que já está resolvido e não precisa de passo

- **Tesseract (OCR): vai DENTRO do exe.** O `build.yml` instala o Tesseract no
  runner, baixa `por.traineddata`, **exige** o `por` em `--list-langs` e embute
  a pasta inteira com
  `--add-data "C:\Program Files\Tesseract-OCR;tesseract"`. Do outro lado,
  `separar_renomear._configurar_ocr` procura primeiro em
  `sys._MEIPASS/tesseract/tesseract.exe`. Máquina limpa com o exe não instala
  OCR nenhum. (Rodando como script, aí sim: `README.md` manda instalar o
  Tesseract com o idioma português.)
- **Cadastro:** desce do Supabase na abertura (seção 5).
- **Sicoob, Inter e o portal da Acessórias:** o login é **manual**, por decisão
  de projeto — a tela do Sicoob tem reCAPTCHA e nada aqui tenta contorná-lo, e
  o Inter pede o QR a cada abertura, mesmo com o perfil salvo. Numa máquina
  nova é login à mão nos três, e não há o que restaurar.

## O que se perde se esta máquina morrer

Só o que existe AQUI. Nada disto está na nuvem nem no repositório:

- **os perfis do Chrome** — `.chrome_profile` (ERP), `.chrome_profile_sicoob`,
  `.chrome_profile_acessorias` e um `.chrome_profile_inter_<conta>` por conta
  do Inter (`util.pasta_do_perfil`). São as sessões logadas: recomeçar custa um
  login manual em cada site, e um QR por conta no Inter. O da Acessórias é o
  mais caro de perder — o "Manter conectado" dele faz a sessão durar de um mês
  para o outro;
- **`remessas.json`** — o espelho legível das remessas geradas. A nuvem tem o
  mesmo histórico (é ela a autoridade), mas o arquivo é o que se abre sem
  internet e sem painel. Perdê-lo não impede gerar a próxima remessa;
- **`diagnostico.log`** (e os `.1`/`.2`/`.3` da rotação) — o único registro do
  que degradou em silêncio: credencial não capturada, login salvo ilegível,
  anexo que não baixou, OCR que não fechou. Quando uma máquina diz só "não
  abriu", é o que sobra para consultar;
- **`atualizacao.log`** — o histórico do auto-update, escrito pelo
  `atualizador.py`;
- **`atividade.jsonl`** — o que a tela de Início mostra. É histórico de UMA
  máquina de propósito, com teto de 400 linhas; ninguém decide dinheiro por
  ele, mas a primeira tela nasce vazia;
- **`log_anexos.csv`** — o resultado de cada anexo feito por esta máquina;
- **`preferencias.json`** — tema e grupos abertos do menu. Volta ao padrão;
- **`sessao.dat` e `login.dat`** — inúteis fora daqui: a DPAPI os prende ao
  usuário do Windows desta máquina. Recuperar é redigitar (seções 4 e 6);
- **`config.yaml`, `mapping.yaml`, `MODELO.xlsx`** — e é aqui que a perda
  morde, porque não descem do Supabase e não estão no Git. Ver a seção 5.

**NÃO DOCUMENTADO — dono preenche**: se existe backup destes arquivos, onde ele
fica, e com que frequência é feito.

## O que este runbook não cobre

**NÃO DOCUMENTADO — dono preenche**, por não haver nada escrito a respeito:

- de onde vem o Google Chrome (seção 1);
- qual é a pasta do exe na máquina que se está substituindo (seção 3);
- onde está o backup de `config.yaml`, `mapping.yaml` e `MODELO.xlsx`
  (seções 5 e "O que se perde");
- o que fazer se a conta do Supabase for a ÚNICA de administrador e ninguém
  puder liberar outra (seção 4);
- restaurar a máquina de desenvolvimento (git, chaves, `gh`) — este runbook
  recupera QUEM USA o app, não quem o constrói.
