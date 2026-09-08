# Arquitetura — Comprovantes Mais Controle

Documento de decisão. Diz **o que foi escolhido, por quê, o que isso custa** e
**quais regras toda mudança tem de respeitar**. O `CLAUDE.md` conta a história e
os detalhes; este arquivo é a régua curta.

Estado em 02/09/2026: v2.0.106, 169 arquivos Python (~52 mil linhas), 62
arquivos de teste (~14,7 mil linhas), 11 migrations no Supabase.

---

## 1. O que este sistema é

Um app Windows de mesa que faz o trabalho financeiro do escritório: separa,
renomeia e anexa comprovantes; concilia saldos do dia; monta remessa CNAB 240;
baixa comprovantes de dois bancos; lança aportes; envia documentos ao contador.

**Ele não é o banco de dados de nada.** Ele orquestra sistemas que já têm dono
(o ERP, os bancos, o Supabase) e produz arquivos. Toda a arquitetura sai daí.

Quem usa é leigo e não tem suporte ao lado: praticidade acima de tudo, e erro
que não mente vale mais que funcionalidade a mais.

---

## 2. Tecnologias escolhidas

| Camada | Escolha | Por quê | O que custa |
|---|---|---|---|
| Linguagem | **Python 3.11**, travado | é a versão que o PyInstaller embute e que o CI usa | código escrito contra 3.12+ passa aqui e quebra no usuário |
| Interface | **tkinter + ttk + sv-ttk** | zero runtime externo, cabe no onefile, o leigo só abre | visual limitado; tudo na thread da tela |
| Distribuição | **PyInstaller onefile**, partido em motor + código | correção chega em segundos (~100 KB) em vez de ~150 MB | import novo ou dependência nova volta a custar os 150 MB |
| Automação de site | **Playwright sync**, Chrome com perfil persistente | o ERP recusa HTTP feito fora do navegador (403) | uma thread só; uma sessão de ERP por pessoa |
| ERP | **API REST pela página logada** (`accessToken` + 4 cabeçalhos) | a raspagem da tela quebrou duas vezes | acoplado a uma API legada sem documentação |
| Nuvem | **Supabase** (Postgres + Auth + RLS), falado por **REST puro com `requests`** | `supabase-py` seria dependência nova = exe novo a cada ajuste | a RLS é a única defesa; a chave `anon` é pública |
| Planilha | **openpyxl** sobre o `MODELO.xlsx` | o painel É a entrega, e o modelo é do dono | testes acoplados a um layout que mora fora do repo |
| PDF / OCR | **pdfplumber + pypdf + Tesseract embutido** | comprovantes de 2026 vêm sem camada de texto | exe gordo; `--collect-all` obrigatório no build |
| Bancário | **CNAB 240 próprio** (`cnab240/`, spec em JSON) | não há lib confiável; o layout é do banco | manter a spec é trabalho recorrente |
| Testes | **pytest** | é a única prova antes de a release virar produção | ~74 testes só rodam onde há dados locais |
| Entrega | **GitHub Actions**; push na `main` = release | ninguém instala nada à mão | build quebrada consome o número da versão |

### Tecnologias vetadas

Não voltar a discutir sem motivo novo:

- **`supabase-py`, ORM, pandas, framework web** — toda dependência nova obriga
  exe novo, ~150 MB baixados por cada usuário.
- **Selenium** — o Playwright já está pago e embutido.
- **Banco local (SQLite)** — criaria uma terceira verdade sobre dados que já
  têm dono.
- **Servidor próprio / serviço web** — não há quem opere.

---

## 3. A base: cinco camadas, seta só para baixo

```
  1. MOTOR ............. motor.py, atualizador.py   (congelado no exe)

  4. TELAS ............. comprovantes_app.py, widgets.py, *_frame.py
         |               orquestram; nunca calculam
         v
  3. ADAPTADORES ....... anexar/mc_api.py, conciliacao/erp/, nuvem/rest.py,
         |               baixar_comprovantes/, extratos_sicoob/, acessorias/
         |               falam com o mundo; traduzem erro em exceção com NOME
         v
  2. NÚCLEO PURO ....... util.py, cnab240/, conciliacao/pipeline|rules|parsing,
                         pagamentos_dia/relatorio.py
                         sem tkinter, sem rede, sem navegador

  5. DADOS DA MÁQUINA .. cache JSON/CSV, login.dat, perfis do Chrome
                         nunca fonte de verdade compartilhada
```

Invariantes de import:

- `util.py` **não importa tkinter** — ele é usado por módulos de regra que
  rodam sem tela. Widget compartilhado vai em `widgets.py`, o par visual dele.
- Núcleo não importa adaptador. Adaptador não importa tela.
- O motor não sabe regra de negócio nenhuma.

---

## 4. Onde mora a verdade

**Um dado tem um dono.** Duas cópias com autoridade foi o que partiu julho/2026
ao meio, quando `contas_mc.json` e `contas_sicoob.json` divergiram em três
subcontas.

| Dado | Dono | O que existe na máquina |
|---|---|---|
| Pagamentos, lançamentos, anexos | **ERP** | nada |
| Cadastro (contas, empresas, entidades, subcontas, regras) | **Supabase** | JSON/CSV como **cache de leitura**, regravado na abertura |
| NSA da remessa, auditoria de quem fez o quê | **Supabase**, alocação atômica | `remessas.json` é espelho legível, nunca autoridade |
| Extratos e comprovantes | **Banco** (PDF/OFX) | arquivo na pasta de saída |
| Credencial do ERP | **a máquina da pessoa** (`login.dat`, DPAPI) | **nunca** sobe para a nuvem |
| Tema, grupos abertos da barra | a máquina (`preferencias.json`) | é de máquina, por desenho |
| Estrutura do painel (`config.yaml`, `mapping.yaml`, `MODELO.xlsx`) | disco local, junto do modelo que descrevem | fora do repo, de propósito |

---

## 5. As regras

Cada regra tem um motivo real. Onde há guardião automático, ele está citado.

### Dinheiro

- **R1 — Dinheiro é `Decimal` de ponta a ponta.** A conversão para float mora
  só na fronteira do JSON (`mc_lancamentos._num`).
- **R2 — Nada é "feito" sem prova.** `mc_client.anexar` espera o arquivo
  aparecer na lista e relê a grade depois de confirmar; sem isso devolve
  `erro:nao_confirmado`.
- **R3 — Três estados, nunca dois.** `estado_anexo()` distingue tem / não tem /
  não verificado. "Não verificado" jamais pode ser lido como "está certo".
- **R4 — Escrita no ERP é idempotente por lançamento.** Relançar depois de
  falha parcial pula o que já entrou. Dinheiro duplicado se desfaz à mão.
- **R5 — Número que não pode repetir é alocado por quem vê todas as máquinas.**
  O NSA sai do banco, atomicamente. **Espiar não é reservar**: `proximo_nsa()`
  só olha, `alocar_nsa()` consome.

### Segurança

- **R6 — Toda política e toda função no Supabase exige `privado.e_ativo()`.**
  `using (true)` é proibido: com auto-cadastro ligado, "está autenticado"
  deixou de significar "trabalha aqui". Guardião: `tests/test_rls_supabase.py`.
- **R7 — `service_role` nunca aparece no código, no exe nem no CI.** A chave
  `anon` é pública por desenho; quem protege é a RLS.
- **R8 — Nada da empresa no repo público.** Nome de fornecedor ou de pessoa,
  CPF, CNPJ, número de conta, saldo — nem em teste, nem em comentário. As
  fixtures são texto anonimizado.
- **R9 — Credencial fica na máquina, num cofre só.** Duas senhas em dois cofres
  garantem que uma envelheça e o erro vire "login inválido" sem motivo aparente.
- **R10 — Migration que fecha porta roda ANTES da mudança de painel que abre.**
  Invertido, existe uma janela com a porta aberta para o mundo.
- **R11 — Senha não fica em arquivo de texto.** Ver o item 1 da seção 7: hoje
  há dois arquivos assim na raiz do projeto.

### Concorrência

- **R12 — Playwright sync é uma thread só.** Navegador só dentro do executor
  dono dele; `extratos_sicoob/` e `acessorias/` têm os seus, por falarem com
  outro site sob outro login.
- **R13 — Uma sessão de ERP por pessoa.** A barra pergunta a três navegadores
  antes de deixar começar, e **a recusa vem antes** de desabilitar botão ou
  enfileirar — senão a aba morre de botões apagados.
- **R14 — Tkinter só na thread da interface.** Toda aba conversa por `queue` +
  `after`.

### Entrega

- **R15 — Arquivo ou pasta nova = linha nova no `build.yml`.** Pacote que tem
  DADOS leva os dados junto (`cnab240/spec/*.json`), senão quebra na primeira
  remessa do usuário. Guardião: `tests/test_cnab240_pacote.py`.
- **R16 — Import novo exige exe novo e `motor_minimo.txt` no MESMO push.** Vale
  até para submódulo da biblioteca padrão: o PyInstaller embute só o que alguém
  importa.
- **R17 — Passar no teste não prova que roda no exe.** Guardiões:
  `tests/test_imports_do_motor.py` e `vermin --target=3.11 --violations`.
- **R18 — Aba nova custa release completa mesmo sem precisar.** Agrupar abas
  novas num push só; o pedágio de 150 MB é por push, não por aba.
- **R19 — Trabalho em branch.** Push na `main` é release para todo mundo.
- **R20 — Build que falha consome o número da versão.** Ao refazer, subir o
  `motor_minimo.txt` junto, senão ele aponta para uma versão que nunca existiu.

### Erro e degradação

- **R21 — Adaptador traduz erro em exceção com NOME.** "Sem rede" e "sua senha
  venceu" pedem coisas diferentes de quem está na frente da tela; um traceback
  não pede nada.
- **R22 — Degradar sim, mentir não.** `diag()` engole o erro e grava o motivo
  em `diagnostico.log`.
- **R23 — Escrita de registro não tem plano B.** Sem banco, a operação para.
  Leitura pode cair no cache; gravação, não.

### Código

- **R24 — Uma comparação, uma implementação.** `util.norm_espaco` é a única
  comparação de nome de conta. Duas cópias de uma regra é uma divergência
  esperando acontecer.
- **R25 — Nome de módulo é global no `sys.path`.** Ou vira pacote com
  `__init__.py`, ou usa prefixo.

---

## 6. Como uma mudança nasce

1. Branch. Nunca direto na `main`.
2. A regra vai no **núcleo puro**, com teste. A tela só chama.
3. Rodar `python -m pytest tests -q` e `vermin --target=3.11 --violations`.
4. Mexeu em `build.yml`, `motor.py`, `atualizador.py` ou `requirements.txt`?
   Sobe o `motor_minimo.txt` no mesmo push e avisa que virá o download grande.
5. Mexeu em política do Supabase? SQL primeiro, painel depois (R10).
6. Merge na `main` = release. Quatro releases ficam guardadas para rollback.

---

## 7. Decisões em aberto — precisam do dono

| # | Assunto | Recomendação |
|---|---|---|
| 1 | **Senhas em texto puro** em dois arquivos `.txt` na raiz do projeto | apagar e guardar no gerenciador de senhas; é o item mais barato desta lista |
| 2 | **Assinatura do exe** (Azure Trusted Signing) — o SmartScreen assusta o usuário leigo a cada release | fazer; é o maior ganho por custo pendente |
| 3 | **Fase 3 da nuvem** — o registro central; `nuvem/registro.py` já cobre o NSA | fechar só o retorno CNAB e os envios; não crescer o escopo |
| 4 | **Site URL do Supabase aponta para `localhost:3000`** — e-mail de confirmação e de troca de senha levam para lugar nenhum | página de pouso no GitHub Pages |
| 5 | **Os ~74 testes que só rodam onde ninguém olha** (dependem de arquivos fora do repo) | um `MODELO.xlsx` de exemplo anonimizado dentro do repo |
| 6 | **`widgets.py` com 2.420 linhas** e `pagamentos_frame.py` com 2.069 | fatiar só quando doer, e nunca junto de outra mudança |
| 7 | **Um perfil de Chrome por empresa** (já são cinco pastas) | aceitar por enquanto; revisar se passar de dez |
