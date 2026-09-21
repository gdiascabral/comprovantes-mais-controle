<!-- Movido do CLAUDE.md em 21/09/2026, sem mudar uma palavra. -->

## 02/09/2026 — a consolidação

Cinco análises (a esteira, o ERP, o front-end, os dados e o código morto)
viraram uma ordem de trabalho, e cerca de trinta PRs entraram no mesmo dia. O
porquê de cada um está no corpo dele; aqui fica o mapa e, principalmente, o que
NÃO foi feito.

**O que entrou, por tema.** *Entrega*: o portão de release (#1), o
`requirements.lock` (#12), o ruff e a cobertura no CI (#6), o `motor_minimo` de
uma unidade (#7, #24). *Diagnóstico*: o `util.log()` e a adoção módulo a módulo
(#8, #11, #13, #14, #17, #19, #20). *ERP*: o inventário (#22), o pacote `erp/`
(#24), o relogin do legado (#27) e as duas primeiras migrações (#31, #33).
*Interface*: o contraste do azul sólido (#15), o teclado e os ícones do menu
(#28), a abertura mais rápida (#29), a busca que leva a uma tela (#32).
*Ferramentas e documento*: a galeria (#10, #23), a sonda (#25), os runbooks e a
proveniência (#18), a recuperação (#21), o painel do Supabase e o `config.toml`
(#16), os caminhos num lugar só (#3, #26), uma cópia só do `cnab240` (#2).
Uma quarta leva de interface fechou o dia, empilhada nesta ordem e toda em
`widgets.py`: a cor fixa que virou teste (#30), os erros com nome (#34), as
tabelas que ordenam pelo cabeçalho (#35) e o layout que escala junto com a
fonte (#37, `widgets.px()`) — o que cada um decidiu está na entrada do
`widgets.py`.

**O que ficou pendente, e por quê.** Está escrito porque pendência que só mora
na cabeça de alguém não é pendência, é esquecimento:

- **`widgets.estado_de` sempre devolve `"info"`, e por isso nenhuma linha de
  tabela se pinta hoje.** `util.norm` devolve MAIÚSCULAS e as chaves de
  `ESTADOS` são minúsculas, então `"apto" in "APTO (AUTORIZADO)"` é falso e a
  varredura inteira passa reto — inclusive o resgate do fim, que procura
  `"atencao"`, `"conferir"` e `"divergen"`, também minúsculos. Conferido
  rodando: `APTO (autorizado)`, `ATENÇÃO — sem anexo`, `JÁ PAGO em 12/08/2026`
  e `SEM PAR` devolvem os quatro `"info"`. É a armadilha de sempre desta casa —
  falha em silêncio, e o que se vê é uma tabela sem cor nenhuma, que parece
  escolha de design. **Correção em andamento em sessão do dono.**
- **a galeria de DEPOIS do PR #37 ainda não foi tirada**: a rodada foi
  interrompida porque o dono estava usando a tela, e a galeria fotografa o
  monitor. O ANTES a 1,5 confirmou os quatro defeitos, e uma primeira rodada do
  DEPOIS já mostrava "ÚLTIMA EXECUÇÃO" por extenso e o logotipo inteiro — mas
  essa captura pegou uma notificação do Windows por cima, e captura suja é
  justamente o que a ferramenta existe para recusar. Falta a rodada limpa, nos
  dois temas, mais a conferência de 0 px na escala de referência. Ao refazer,
  lembrar que **`--escala` multiplica a escala ATUAL** e que esta máquina está a
  125%: 100% é `--escala 0.8` e 150% é `--escala 1.2`;
- **a intermitência dos testes de interface teve DUAS causas, e as duas estão
  fechadas.** O Tab do menu (`test_o_tab_passa_por_cada_item_do_menu`) morria
  com `invalid command name "tk_focusNext"`, e era a captura de saída do
  pytest fechando handles do Tcl — `tcl_com_handles_proprios` no conftest,
  PR #41. Sobrava a família das TECLAS: `event_generate` de tecla descartado
  quando o Windows leva o foco entre uma chamada e outra, mais o ponteiro do
  mouse parado sobre a lista da busca — `teclar`/`focar`/`longe_do_ponteiro`
  no conftest e `tests/test_teclar.py` (ver "Teste de interface usa a fixture
  `raiz`", em Desenvolvimento). O que fica: o `focus_force` de `teclar` ainda
  chama `SetForegroundWindow`, então a suíte continua disputando o primeiro
  plano com quem usa a máquina (e quem digita nesse instante digita na janela
  invisível da suíte) — é o único jeito que o Tk 8.6 dá de escrever o foco
  sem o consentimento do Windows, e trocá-lo exigiria um Tk que aceitasse
  `<FocusIn>` gerado;
- **os consumidores 4 a 8 do ERP** — `aportes/mc_catalogos.py` +
  `aportes/erp_sessao.py`; `conciliacao/erp/payments.py` **migrou em
  08/09/2026** (`payments_api.py`, chave `pagamentos_via_api`), mas era a mais
  cara de conferir, porque o resultado é dinheiro no painel do dia, e a
  conferência — `conciliacao comparar-coleta` num período com coleta antiga
  conhecida — **ainda não foi rodada**; `relatorios/extrato_mc.py` e
  `anexar/mc_client.py`, em que só as constantes de host mudam; e
  `anexar/mc_api.py` por último. A ordem e o motivo de cada posição estão no fim
  do `docs/ERP-CLIENTES.md`;
- **as esperas fixas**: ~124 s somados em 83 pontos com o número escrito no
  código (de 90 chamadas de `wait_for_timeout`/`sleep`), concentrados em
  `baixar_comprovantes/inter_baixar.py` (20), `conciliacao/erp/payments.py`
  (16) e `anexar/mc_client.py` (11). Trocá-las por espera por CONDIÇÃO é a
  mudança de melhor relação ganho/risco que sobrou, e é a única que **só se
  testa contra o portal real** — o que se mede ali é o tempo que o site de
  terceiro leva, e nenhum dublê sabe isso;
- **fixtures sintéticas para os 74 testes que pulam.** Eles pulam por falta dos
  arquivos que não entram no repositório (`config.yaml`, `mapping.yaml`,
  `MODELO.xlsx`, os cadastros), e teste que pula não aparece em vermelho — é a
  mesma armadilha dos 9 do `test_widgets.py`, num tamanho maior;
- **o `_sair` de `comprovantes_app.py`**, cujo `except Exception: pass` em
  volta do `fechar()` de cada aba continua mudo. É o que o PR #20 deixou
  explicitamente de fora;
- **a aba Início custa ~670 ms** para construir, contra menos de 100 ms das
  outras, e o custo é trabalho de construção, não import (PR #29);
- **`conciliacao/workbook.py` e `pagamentos_dia/relatorio.py` importam
  `openpyxl`/`pdfplumber` sem condição** no topo, e por isso o ganho do PR #29
  ficou pela metade: ~0,27 s de openpyxl e ~0,08 s de pdfplumber continuam
  entrando antes de existir janela. No segundo, o `try: import pdfplumber` não
  evita o custo — só evita o erro se a biblioteca faltar;
- **o `ARQUIVO_LOG` (`log_anexos.csv`) do `anexar/config.py` ainda sai do
  `_AQUI`**, e é o último caminho calculado pela pasta do MÓDULO depois que o
  perfil do Chrome, o `diagnostico.log` e o `login.dat` migraram para
  `util.pasta_base()`;
- **o `grant insert, update on table public.conta to authenticated`** da
  migration `20260824141500` não aparece em runbook nenhum: o runbook de 21/08
  criou as políticas `conta_cadastra` e `conta_corrige` e parou aí, e o
  privilégio veio três dias depois, só na migration. Sem ele a política nem
  chega a ser consultada, e não há registro de por onde ele chegou ao projeto de
  verdade — é o primeiro item do `docs/PROVENIENCIA.md`, e a conferência é um
  `db diff` que só lê;
- **nomes de fornecedor que já estão na `main` pública** — em
  `conciliacao/rules.py`, `pagamentos_dia/remessa_dia.py`,
  `conciliacao/parsing.py` e `nuvem/contas_novas.py` —, contra a regra da casa
  de que nome real de fornecedor ou de pessoa não entra no repositório. Foi por
  causa deles que um runbook entrou e depois saiu (commit `25ae569`): o critério
  aplicado ao arquivo novo não estava sendo aplicado ao que já estava
  publicado. Tirá-los mexe em regra de negócio e em histórico já público, então
  **é decisão do dono**, e não de quem estiver com o arquivo aberto.
