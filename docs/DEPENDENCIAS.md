# Dependências: a intenção e o fato

São dois arquivos, e a diferença entre eles é o ponto:

- **`requirements.txt` é a INTENÇÃO** — faixas (`pdfplumber>=0.11,<1`). É onde
  se escreve "qualquer 0.11 serve, 1.0 não".
- **`requirements.lock` é o FATO** — versão exata e hash de cada pacote, o
  próprio e os que ele arrasta. É o que o CI instala, e é ele que decide o que
  vai dentro do exe.

Enquanto só existiam faixas, o mesmo commit construído em dias diferentes
gerava executáveis diferentes. Três consequências, e nenhuma é teórica: versão
nova de terceiro quebrava a entrega sem uma linha de código mudar; defeito que
aparecia na máquina de quem usa não se reproduzia aqui; e uma biblioteca
comprometida entraria no exe que roda nas máquinas que pagam contas. O
PyInstaller e as actions já eram presos por versão e por hash — o cuidado
existia, só não tinha chegado às bibliotecas que vão DENTRO do produto.

## Atualizar uma biblioteca

Três passos, e o terceiro não é opcional:

1. Mude a faixa no `requirements.txt` (ou não mude nada, se o que se quer é só
   pegar a correção mais nova de dentro da faixa que já está lá).
2. Recompile o lock, com **este** comando, exatamente:

   ```
   uv pip compile requirements.txt --python-version 3.11 --python-platform windows --generate-hashes -o requirements.lock
   ```

   Para subir de versão dentro da faixa, acrescente `--upgrade` (ou
   `--upgrade-package pdfplumber` para mexer em uma só). Sem `--upgrade` o uv
   lê o lock que já existe e **mantém** o que estava lá — é isso que faz o
   recompile ser barato e a conferência do CI ser estável.
3. **Commite os dois juntos.** O CI recompila o lock no runner e compara; se o
   `requirements.txt` mudou e o lock não, a build fica vermelha antes de
   publicar release nenhuma.

O `uv` sai do `requirements-dev.txt` (`pip install -r requirements-dev.txt`).
É um binário só, não precisa de um Python 3.11 na máquina — o que nos leva ao
próximo ponto.

## Por que o lock é resolvido para 3.11, e não para o Python da máquina

**O exe roda Python 3.11**, que é o que o CI instala e o que o PyInstaller
embute. A máquina de quem desenvolve quase nunca é 3.11 — hoje é 3.14.

Um lock resolvido no interpretador da máquina fixa a versão que serve ao 3.14:
pode ser uma que não existe para 3.11, ou uma que instala e não roda. E o pior
é onde isso apareceria — não aqui, mas na hora de instalar no runner, com a
build já rodando e o número da release já consumido. É a mesma família do
`Path.read_text(newline=…)` da run #76 e do `tkinter.font` da v1.0.71: código
(ou pacote) que a sua stdlib tem e a do usuário não.

Por isso o `--python-version 3.11 --python-platform windows`: o uv resolve
para o ALVO sem precisar tê-lo instalado. A saída é um `requirements.txt`
comum, então o CI lê com `pip install -r` e não precisa de uv para instalar —
só para recompilar.

## `--require-hashes`

O CI instala com `pip install --require-hashes -r requirements.lock`. O hash é
o que fecha a porta do meio: pacote que chegue com outro conteúdo não instala,
ele PARA a build. Isso só funciona porque **todas as distribuições do lock são
wheel** para cp311/win_amd64 ou puras — nenhuma precisa compilar sdist no
runner. Se algum dia entrar um pacote que só publica sdist, o hash continua
valendo, mas o runner passa a precisar de compilador: vale conferir antes de
alargar a faixa.

## O pedágio do motor

`requirements.lock` está na lista da trava do job `motor`, junto de
`motor.py`, `atualizador.py`, `requirements.txt` e do próprio `build.yml`. As
bibliotecas moram no MOTOR (o exe grande), não no `codigo.zip`: mudar uma
versão fixada é mudar o que está dentro do executável, então o push que mexe
no lock tem de subir o `motor_minimo.txt` junto. Sem isso, código novo rodaria
em motor velho na máquina de quem usa — ver "Regra de ouro", no `CLAUDE.md`.
