---
paths:
  - "util.py"
  - "tests/test_util.py"
---

# Arquitetura: util.py

> Trecho da seção "Arquitetura", movido do `CLAUDE.md` em 21/09/2026 sem mudar uma palavra.
> Carrega sozinho quando o Claude lê um arquivo dos caminhos acima.
> Mudou o código? Atualize AQUI — este é o lugar deste texto agora.

- `util.py` — o que não é de aba nenhuma, e por isso é de todas: `pasta_base()`,
  `pasta_do_perfil()`, `log()`, `norm_espaco`, `filtrar`, `proteger_bytes`
  (DPAPI). **Não importa tkinter** (ver "Restrições"): o par visual dele é o
  `widgets.py`.
  **`util.log(nome)` é o diagnóstico do app, e é UM handler só.** Um
  `RotatingFileHandler` (1 MB, 3 cópias, utf-8) em
  `pasta_base()/diagnostico.log`, compartilhado por TODO nome que passar por
  aqui — handler por módulo seria trocar o diagnóstico espalhado de hoje por
  outro igualmente espalhado, só que com nomes de arquivo em vez de formatos
  diferentes. `nome` entra no FORMATO da linha, nunca no caminho do arquivo, e
  o prefixo `dd/mm/aaaa hh:mm:ss` é o mesmo que o `diagnostico.log` já gravava
  à mão, para quem abre o arquivo não estranhar a parte que olha primeiro. Três
  escolhas que não são detalhe: `delay=True`, então o arquivo abre no primeiro
  `emit` e uma pasta sem permissão de escrita não derruba a ABERTURA do app;
  **nenhum handler de console**, porque o exe é `--noconsole` e um
  `StreamHandler` apontado para um `stdout` que não existe é a mesma armadilha
  do `print()` — derruba o app, não só engasga o log; e `propagate=False`, para
  que o logger raiz, ganhando handler um dia, não duplique cada linha.
  **A regra de adoção**, aplicada módulo a módulo (PRs #8, #11, #13, #14, #17,
  #19 e #20): `except Exception` que engole **sem comentário que justifique**
  vira `log.warning("o que eu estava fazendo", exc_info=True)` e continua
  engolindo — nenhum `except` foi estreitado nem removido, e nenhum
  comportamento mudou. **A exceção é o laço de espera**: dentro de um
  `while … < limite`, ou de uma escada de seletor/rótulo/tamanho, a exceção não
  é falha, é o "ainda não" da próxima volta; um traceback a cada 0,5 s enche
  1 MB numa rodada só e rotaciona para fora justamente o que interessa. Ali o
  `pass`/`continue` fica, com uma linha dizendo por quê, e quem avisa é o
  **desfecho** do laço — uma vez, e sem `exc_info`, porque ali não há exceção
  viva. Nenhuma mensagem carrega favorecido, valor, número de conta ou token: o
  `diagnostico.log` é arquivo comum na pasta do exe. E cuidado com o nome
  `log`: em `conciliacao/erp/`, `baixar_comprovantes/` e `aportes/` quase toda
  função já recebe um parâmetro `log`, que é o recado do Registro da aba e
  SOMBREIA o logger do módulo — ali o diagnóstico sai por `_diag`, o mesmo
  objeto com outro nome. O Registro conta o que a rotina está fazendo; o
  arquivo guarda o traceback do que não deu.
  **`cnab240/` é a exceção que confirma a regra.** Ele é stdlib pura — nem
  `util` pode importar, e `tests/test_cnab240_pacote.py` cobra isso por AST —,
  então emite em `logging.getLogger(__name__)`, como biblioteca faz, e deixa a
  APLICAÇÃO dizer para onde vai. Quem liga os dois é UMA linha na abertura,
  `util.log("cnab240")` em `main()`, que pendura o handler no logger pai e
  recebe os filhos por propagação. **Nunca pendurar um `NullHandler` no logger
  `cnab240`**: o `util.log()` só instala o handler `if not logger.handlers`, e
  um NullHandler ali silenciaria a ligação para sempre, e em silêncio.
  **`util.pasta_do_perfil(nome)` é o único lugar que sabe onde mora o perfil do
  Chrome.** Ele era calculado de DOIS jeitos: ao lado do MÓDULO
  (`_AQUI = Path(__file__)…`, que muda conforme quem executa é o script ou o
  exe) e na pasta BASE. Rodando como script, o primeiro fazia nascer um SEGUNDO
  conjunto de perfis dentro do repositório — medido em **219 MB** de sessão de
  banco duplicada. Congelado o lugar nunca mudou, então o desencontro só
  aparecia em desenvolvimento, que é justamente onde se testa: é a mesma
  família do defeito do cache do cadastro ("quem lê o cache tem de usar
  `util.pasta_base()`"). Nenhum nome de pasta mudou, e há teste conferindo byte
  a byte os que já estavam instalados. Pelo mesmo caminho vieram depois o
  `ARQUIVO_DIAG` (PR #8) e o `login.dat` (PR #26), que também nasciam dentro de
  `anexar/` em modo script — e era por isso que a sonda, rodando da raiz, não
  achava a senha do ERP. Falta um: o `ARQUIVO_LOG` (`log_anexos.csv`) do
  `anexar/config.py` ainda sai do `_AQUI`.
