# Repaginada visual, etapa 1 (app tkinter): plano de implementação

> **Para quem executa:** SUB-SKILL OBRIGATÓRIA: superpowers:executing-plans (execução nativa, na própria sessão). Os passos usam caixas (`- [ ]`) para acompanhar.
> Ao começar, copie este arquivo para `docs/superpowers/plans/2026-10-22-repaginada-etapa-1.md` no worktree.

**Objetivo:** deixar o app atual com a cara do protótipo aprovado em 22/10/2026: tema escuro em azul-marinho, barra de cima na mesma cor da página (sem faixa azul), item aberto do menu em pílula azul cheia com o botão principal verde, como hoje. Tudo isso sem mexer em nenhuma regra de negócio.

**Arquitetura:** quase tudo é troca de valores na `PALETA` e nos estilos nomeados do `widgets.py`, porque as abas não escrevem cor própria (há um teste que garante isso). Os testes de contraste que já existem em `tests/test_visual.py` são a rede de segurança: toda cor nova precisa passar neles. Os únicos códigos novos são um papel de cor (`barra_texto`) e o jeito de pintar o `ItemMenu` aberto.

**Stack:** Python 3.11 no exe (3.14 na máquina), tkinter + ttk + sv-ttk, pytest.

**Spec:** `C:\AUTOMAÇÕES MAIS CONTROLE\mockups\2026-10-22-repaginada\LEIA-ME.md` (paleta, raios e recomendação) e o `mockup.html` da mesma pasta (o desenho aprovado).

## Restrições globais

- **Começar só depois do merge** dos branches `codigo/pagamentos-do-dia-3` e `codigo/controle-de-aportes`, que mudam 129 linhas do `widgets.py`, entre elas o cabeçalho sem faixa (filete de 1 px, `Filete.TFrame`, `BORDA_DESLIGADO`). Este plano foi escrito sobre o `widgets.py` do `codigo/pagamentos-do-dia-3` em 22/10/2026. Antes da Tarefa 1, confira que os nomes citados aqui existem (Passo 0.3).
- Toda cor de **texto**: ≥ 4,5:1 contra o fundo em que aparece. Forma de botão: ≥ 3:1. Moldura de botão desligado: ≥ 2,0:1. São os limites atuais de `tests/test_visual.py`; não podem baixar.
- Nenhuma aba ganha `#rrggbb` próprio. Cor nova entra **só** na `PALETA`, nos dois temas (`test_os_dois_temas_tem_os_mesmos_papeis`).
- O registro (log) continua escuro nos dois temas (`log_fundo`, `LOG_CORES`): não mexer.
- Repositório público: nada de dado real em teste, comentário ou commit.
- Nada vai direto na `main`: branch `codigo/repaginada-visual` → PR → CI verde → merge → **prévia** na máquina do dono antes de liberar.
- Testes que abrem janela (fixture `raiz`) e a galeria de prints **roubam o foco da tela do dono**: perguntar se a tela está livre antes de rodar.

## Fora desta etapa (de propósito)

Ficam fora: cantos arredondados (o docstring de `Cartao` explica por que o Tk não faz), fonte Manrope (exigiria registrar a fonte no Windows pelo exe, e o exe só tem os módulos que o motor importa; risco alto para ganho pequeno), menu que vira trilho de ícones e registro que mostra só a última linha. Tudo isso vai para as telas novas em HTML.

## Foco da revisão

1. **Troca de tema com o app aberto** (Sistema → Escuro → Claro): nada pode ficar com a cor do tema anterior. A causa típica é widget clássico (`tk.Frame`, `tk.Button`) que não está em `_repintaveis`. A barra de cima e o `ItemMenu` são clássicos.
2. **Campo de busca da barra de cima** no tema claro: hoje o texto é `#FFFFFF` fixo (`BarraTopo._entrou`). Com a barra clara, isso viraria texto branco em fundo claro, invisível. Teste na Tarefa 2.
3. **Aba trabalhando** (● no menu) quando ela é a aba aberta: o ● é pintado de `ativo` (azul). Sobre a pílula azul cheia ele some. Teste na Tarefa 3.
4. **Foco pelo teclado (Tab)** no item aberto: o anel é `marca` sobre `marca_solida`, quase a mesma cor. Ele precisa continuar visível. Teste na Tarefa 3.
5. **Escala de 150% do Windows:** só mudam cores, então o layout não muda. O teste `test_a_barra_de_cima_cresce_com_o_que_tem_dentro` já cobre isso.

## Arquivos

- Modificar: `widgets.py`: `PALETA`, `aplicar_estilos`, `Botao` (papéis `passo` e `barra`), `BarraTopo` (pintura e campo de busca), `ItemMenu._pintar`.
- Modificar: `tests/test_visual.py`: `PARES_DE_TEXTO`, `PARES_DE_COMPONENTE` e os testes novos de cada tarefa.
- Nenhuma aba muda.

---

### Tarefa 0: preparar

- [ ] **0.1** Conferir que os dois branches foram mesclados:
```bash
git -C "C:/AUTOMAÇÕES MAIS CONTROLE/_worktrees/app-dia-ajustes" fetch origin
git -C "C:/AUTOMAÇÕES MAIS CONTROLE/_worktrees/app-dia-ajustes" branch -r --merged origin/main | grep -E "pagamentos-do-dia-3|controle-de-aportes"
```
Esperado: as duas linhas aparecem. Se faltar alguma, **pare** e avise o dono.

- [ ] **0.2** Criar o worktree (padrão do projeto):
```bash
git -C "C:/AUTOMAÇÕES MAIS CONTROLE/_worktrees/app-dia-ajustes" worktree add "C:/AUTOMAÇÕES MAIS CONTROLE/_worktrees/app-repaginada" -b codigo/repaginada-visual origin/main
```

- [ ] **0.3** Conferir os nomes que o plano usa (grep no código, não de memória):
```bash
cd "C:/AUTOMAÇÕES MAIS CONTROLE/_worktrees/app-repaginada"
grep -n "Filete.TFrame\|^BORDA_DESLIGADO\|def _pintar(self, hover\|class BarraTopo\|\"barra\":  (\|\"passo\":  (\|def _entrou\|def _mostrar_dica" widgets.py
grep -n "^PARES_DE_TEXTO\|^PARES_DE_COMPONENTE\|^COR_DO_PASSO" tests/test_visual.py
```
Esperado: todos aparecem. Se algum sumiu, ajuste a tarefa que o usa antes de seguir.

- [ ] **0.4** Rodar a linha de base dos testes que não abrem janela:
```bash
python -m pytest tests/test_visual.py -k "contraste or legivel or papeis or forma or desligado" -q
```
Esperado: tudo passa. Anote o número.

---

### Tarefa 1: tema escuro em azul-marinho

**Arquivos:** `widgets.py` (`PALETA["escuro"]`), `tests/test_visual.py`
**Interfaces:** produz os novos valores de `PALETA["escuro"]` (mesmos papéis de hoje, sem papel novo).

- [ ] **1.1 Teste que falha:** em `tests/test_visual.py`, logo depois de `test_os_dois_temas_tem_os_mesmos_papeis`:
```python
def test_o_escuro_e_azul_marinho():
    """Pedido do dono em 22/10/2026: o tema escuro em azul-marinho, como no
    protótipo aprovado, e não no cinza quase preto de antes. "Azul" aqui é
    medido: o canal azul passa o vermelho com folga e passa o verde."""
    escuro = widgets.PALETA["escuro"]
    for papel in ("fundo", "cartao", "borda", "zebra", "cabecalho"):
        cor = escuro[papel]
        r, g, b = (int(cor[i:i + 2], 16) for i in (1, 3, 5))
        assert b >= r + 20 and b > g, f"{papel} não é azul-marinho: {cor}"
```

- [ ] **1.2** `python -m pytest tests/test_visual.py::test_o_escuro_e_azul_marinho -q`. Esperado: FALHA (`fundo não é azul-marinho: #0F131B`).

- [ ] **1.3 Implementar:** em `PALETA["escuro"]`, trocar só estes valores e atualizar o comentário de contraste de cada linha com o número medido no passo 1.4:
```python
        "fundo":       "#0B1529",
        "cartao":      "#0F1C36",
        "borda":       "#1F3053",
        "linha":       "#4A5D85",   # filete, ícone — nunca texto
        "zebra":       "#12203D",
        "cabecalho":   "#14223F",
        "texto":       "#E8EDF7",
        "apoio":       "#A9B6CF",
        "tenue":       "#8C9AB8",
        "marca":       "#7C9BFF",   # só como TEXTO
        "marca_solida": "#3D5AFE",  # fundo com branco por cima
        "marca_fundo": "#192A5E",
        "info_fundo":  "#192A5E",
        "ok_fundo":      "#0E3226",
        "atencao_fundo": "#382A0B",
        "erro_fundo":    "#3B1421",
```
(`marca_barra` e `marca_sub` mudam na Tarefa 2; `acao*` não muda.)

- [ ] **1.4** Medir e anotar os contrastes de verdade:
```bash
python -c "import sys; sys.path.insert(0,'tests'); import widgets, test_visual as t; p=widgets.PALETA['escuro']; [print(k, t._br(t._contraste(p[k], p[f]))) for k,f in (('texto','cartao'),('apoio','cartao'),('tenue','fundo'),('marca','cartao'),('linha','fundo'),('linha','cartao'))]; print('branco/solida', t._br(t._contraste('#FFFFFF', p['marca_solida'])))"
```
Escreva os números nos comentários da `PALETA`; é a regra do arquivo ("medido, não estimado").

- [ ] **1.5** `python -m pytest tests/test_visual.py -k "contraste or legivel or papeis or forma or desligado or marinho" -q`. Esperado: tudo passa. Se um par cair abaixo do mínimo, ajuste **só** a cor daquele papel, um tom de cada vez, e meça de novo.

- [ ] **1.6 Commit:**
```bash
git add widgets.py tests/test_visual.py
git commit -m "visual: tema escuro em azul-marinho (repaginada, etapa 1)"
```

---

### Tarefa 2: barra de cima na cor da página

Hoje a barra de cima é azul nos dois temas (`marca_barra`) e escreve em branco fixo. No protótipo ela é da cor da página, com texto normal.

**Arquivos:** `widgets.py` (`PALETA`, `aplicar_estilos`, `Botao`, `BarraTopo`), `tests/test_visual.py`
**Interfaces:** produz o papel novo `barra_texto` (texto da barra) nos dois temas. `marca_barra` passa a ser igual a `fundo`, e `marca_sub` vira o texto secundário da barra (dica da busca).

- [ ] **2.1 Testes que falham:**
```python
@pytest.mark.parametrize("tema", sorted(widgets.PALETA))
def test_a_barra_de_cima_tem_a_cor_da_pagina(tema):
    """22/10/2026: a barra de cima deixa de ser uma faixa azul e fica na cor
    da página, como o cabeçalho das abas."""
    p = widgets.PALETA[tema]
    assert p["marca_barra"] == p["fundo"]


def test_a_barra_de_cima_escreve_na_cor_do_papel(raiz):
    """Nada de branco fixo: no tema claro a barra é clara."""
    st = ttk.Style()
    for escuro in (False, True):
        widgets.aplicar_estilos(escuro)
        p = widgets.PALETA["escuro" if escuro else "claro"]
        assert str(st.lookup("Barra.TLabel", "foreground")).lower() == p["barra_texto"].lower()
        assert str(st.lookup("Marca.TLabel", "foreground")).lower() == p["barra_texto"].lower()
```
E, em `PARES_DE_TEXTO`, acrescentar:
```python
    ("barra_texto", "marca_barra", "texto da barra de cima"),
    ("marca_sub", "cartao", "dica cinza no campo de busca da barra"),
    ("barra_texto", "cartao", "o que se digita no campo de busca da barra"),
```

- [ ] **2.2** Rodar os testes. Esperado: FALHAM (`KeyError: 'barra_texto'` e `marca_barra != fundo`).

- [ ] **2.3 Implementar a paleta:** nos dois temas, `"marca_barra"` passa a ter o mesmo valor de `"fundo"` e entra o papel novo:
```python
        # claro
        "marca_barra": "#EEF1F7",   # a barra de cima: a cor da página (22/10/2026)
        "marca_sub":   "#5B6880",   # dica da busca, sobre o campo (cartão)
        "barra_texto": "#1C2537",
        # escuro
        "marca_barra": "#0B1529",
        "marca_sub":   "#A9B6CF",
        "barra_texto": "#E8EDF7",
```

- [ ] **2.4 Implementar os estilos** em `aplicar_estilos`: trocar `foreground="#FFFFFF"` por `foreground=c["barra_texto"]` em `Barra.TLabel` e `Marca.TLabel`.

- [ ] **2.5 Implementar o `Botao`:** a barra deixou de ser escura, então misturar com branco não forma mais um botão. Trocar as entradas `"barra"` e `"passo"` do dicionário de papéis:
```python
            "passo":  ("#FFFFFF", c["marca_solida"],
                       _mistura(c["marca_solida"], "#FFFFFF", 0.12)),
            # Na barra de cima, que agora é a cor da página: um botão cinza
            # como o "neutro", com o realce azul-claro ao passar o cursor.
            "barra":  (c["barra_texto"], c["cartao"], c["marca_fundo"]),
```
(`passo` usava `marca_barra` como cor de cursor por cima; com a barra igual à página, o botão azul ficaria cinza ao passar o mouse.)

- [ ] **2.6 Implementar a `BarraTopo`:** procurar todo branco fixo e toda mistura com a barra:
```bash
grep -n '"#FFFFFF"\|_mistura(c\["marca_barra"\]' widgets.py | awk -F: '$1>2000 && $1<2370'
```
Regra para cada linha achada: texto → `cores()["barra_texto"]`; `insertbackground` → `c["barra_texto"]`; fundo do campo de busca → `c["cartao"]`; `highlightbackground` → `c["borda"]`; `highlightcolor` → `c["marca"]`. O `_entrou` passa a ser `self.busca.configure(foreground=cores()["barra_texto"])`.

- [ ] **2.7** Rodar `python -m pytest tests/test_visual.py -q` (**perguntar ao dono se a tela está livre**, porque abre janela). Esperado: tudo passa. Atenção a `test_o_botao_de_passo_e_o_circulo_pintam_a_cor_medida`: se ele conferir a cor de cursor do botão de passo como `marca_barra`, troque a expectativa para a mistura do passo 2.5 e diga o porquê no teste.

- [ ] **2.8 Commit:** `git commit -am "visual: barra de cima na cor da página, sem faixa azul"`

---

### Tarefa 3: item aberto do menu em pílula azul cheia

Hoje o item aberto tem fundo azul-claro, texto azul e filete de 3 px. No protótipo é azul cheio com texto branco. Fica retangular, porque o Tk não arredonda.

**Arquivos:** `widgets.py` (`aplicar_estilos`: `ItemAtivo.TLabel`; `ItemMenu._pintar`), `tests/test_visual.py`

- [ ] **3.1 Testes que falham:**
```python
def test_o_item_aberto_do_menu_e_azul_cheio(raiz):
    """Protótipo de 22/10/2026: o item aberto é a pílula azul cheia, com
    texto branco. O ● de aba trabalhando continua visível em cima dela."""
    widgets.aplicar_estilos(False)
    c = widgets.cores()
    item = widgets.ItemMenu(raiz, "Pagamentos do dia")
    item.pack()
    item.ativar(True)
    assert item.cget("background").lower() == c["marca_solida"].lower()
    assert str(ttk.Style().lookup("ItemAtivo.TLabel", "foreground")).lower() == "#ffffff"
    item.trabalhando(True)
    assert str(item.lbl_icone.cget("foreground")).lower() == "#ffffff"
    item.destroy()
```
E, em `PARES_DE_TEXTO`: `("#FFFFFF", "marca_solida", "nome do item aberto do menu"),`
E, em `PARES_DE_COMPONENTE`: `("marca_solida", "cartao", "a pílula do item aberto contra o menu"),`

- [ ] **3.2** Rodar. Esperado: FALHA (o fundo hoje é `marca_fundo`).

- [ ] **3.3 Implementar `aplicar_estilos`:**
```python
    st.configure("ItemAtivo.TLabel", background=c["marca_solida"],
                 foreground="#FFFFFF", font=FONTE_FORTE)
```

- [ ] **3.4 Implementar `ItemMenu._pintar`:** no ramo `if self._ativo:`, usar `fundo, frente, filete = c["marca_solida"], "#FFFFFF", c["marca_solida"]`. O foco no item aberto passa a usar `highlightcolor=c["texto"]` (anel claro no escuro e escuro no claro, visível sobre o azul), e o ● segue a frente quando o item está aberto:
```python
            self.configure(background=fundo, highlightbackground=fundo,
                           highlightcolor=c["texto"] if self._ativo else c["marca"])
            ...
            self.lbl_icone.configure(
                text=desenho, font=fonte_icone, style=estilo,
                foreground=frente if self._ativo
                else (c["ativo"] if self._trabalhando else frente))
```
Atualize o docstring da classe ("Aqui o aberto é fundo azul-claro…") para a regra nova, com a data.

- [ ] **3.5** Rodar `python -m pytest tests/test_visual.py tests/test_widgets.py -q` (tela livre?). Esperado: tudo passa. Se algum teste antigo afirmava `marca_fundo` no item aberto, troque a expectativa, porque a regra mudou por pedido do dono, e cite a data no teste.

- [ ] **3.6 Commit:** `git commit -am "visual: item aberto do menu em azul cheio"`

---

### Tarefa 4: botão principal (CANCELADA pelo dono em 22/10/2026)

O botão de executar continua **verde**. Decisão do dono, 22/10/2026: "pode deixar os botões verde para destacar um pouco" (revogou o azul aprovado minutos antes). Não mexer em `acao`, `acao_ativo` nem `acao_viva`.

---

### Tarefa 5: conferir, abrir o PR, gerar a prévia

- [ ] **5.1** Suíte inteira **pura** (sem janela): `python -m pytest -q -m "not tela"`. Se o projeto não tiver o marcador, rode `python -m pytest -q` só com a tela do dono livre.
- [ ] **5.2** `vermin --target=3.11 widgets.py`. Esperado: nada acima de 3.11.
- [ ] **5.3** Galeria de prints, **com a tela livre**: os dois temas, nas abas Início, Pagamentos do dia, Baixar Comprovantes e Anexar. Compare lado a lado com o `mockup.html`.
- [ ] **5.4** Um revisor (agente, modelo **sonnet**, só leitura) olha o diff contra o "Foco da revisão" acima.
- [ ] **5.5** Push e PR `codigo/repaginada-visual` → `main`, com prints antes e depois na descrição. Depois do CI verde: merge, **prévia** travada no notebook do dono e liberação só com o "ok" dele. Apagar worktree e branch depois do merge (regra "nenhum PR fica para trás").

---

## Custo e tempo estimados

- 3 tarefas pequenas mais a conferência (a Tarefa 4 foi cancelada). Execução **nativa** nesta sessão: cerca de 1h30 a 2h de trabalho, a maior parte em rodar testes e prints.
- Tokens: parecido com um PR médio. Sem subagente por tarefa; só 1 revisor no fim, no modelo mais barato.
