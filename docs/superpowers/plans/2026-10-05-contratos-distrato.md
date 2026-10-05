# Contratos: vários por casa e o distrato — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Na casa que tem distrato, arquivar todos os contratos de compra e venda (um por comprador), sugerir pelo nome do comprador qual foi distratado, deixar o dono marcar/desmarcar "Distrato" por linha e gravar o marcado com " (Distratado)" no fim do nome.

**Architecture:** Regras puras novas em `contratos/escolha.py` (achar distratos) e `contratos/distrato.py` (comprador do contrato, grupos, sugestão). `pipeline.levantar` expande a casa com distrato em uma linha (`Achado`) por comprador; `destino.nome_arquivo` ganha o sufixo; `pipeline.arquivar` aceita os irmãos da mesma casa; a aba ganha a coluna DISTRATO; a Acessórias entende o sufixo.

**Tech Stack:** Python 3.11, tkinter/ttk, pytest.

**Spec:** `docs/superpowers/specs/2026-10-05-contratos-distrato-design.md`

## Global Constraints

- Worktree `C:/AUTOMAÇÕES MAIS CONTROLE/_worktrees/app-distrato`, branch `codigo/contratos-distrato`. Nunca `git stash` puro; nunca push na `main`.
- Testes: `python -m pytest tests -q` (o `conftest.py` arruma o `PYTHONPATH`). Interface só com a fixture `raiz`.
- Teste nunca faz rede nem abre navegador; o ERP é o `ApiDuble` de `tests/test_contratos_pipeline.py` (estender, não duplicar).
- Repo público: nenhum nome real de pessoa, CPF ou CNPJ em teste ou comentário. Use "PRIMEIRO COMPRADOR EXEMPLO", "SEGUNDO COMPRADOR EXEMPLO".
- Régua antes de cada commit: `ruff check --select E9,F <arquivos>`, vermin `--target=3.11-` sobre os arquivos, e os testes do pacote `contratos`/`acessorias`.
- Sem import novo de submódulo da biblioteca padrão. `contratos/distrato.py` é arquivo novo numa pasta que já está no `codigo.zip` (`contratos/*.py`).
- Casa SEM distrato tem de sair exatamente como hoje (os testes existentes de `test_contratos_*` continuam passando sem mudança de asserção).
- Sufixo exato: `" (Distratado)"`, antes da extensão.
- Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Casa sem distrato** — mesmo resultado de hoje (um contrato, revisão nas disputas). Teste de regressão em Task 4.
2. **PDF escaneado sem texto / comprador não encontrado** — a linha aparece com Distrato DESMARCADO e o motivo "não consegui ler o comprador"; nada é marcado sozinho. Teste em Task 3 e 4.
3. **Duas versões do MESMO comprador** (minuta + assinado) numa casa com distrato — viram uma linha (regra do mais completo/bytes), não duas. Teste em Task 3.
4. **Rodada refeita no mesmo mês** — o "(Distratado)" já gravado conta como "já estava", e a trava de outro contrato da casa não retém os irmãos da mesma rodada. Teste em Task 4.
5. **Dono desmarca o Distrato sugerido** — o arquivo sai sem o sufixo e com a conferência normal daquele contrato. Teste em Task 5.

---

### Task 1: Nome do arquivo com " (Distratado)" e a trava que aceita irmãos

**Files:**
- Modify: `contratos/destino.py` (`nome_arquivo`, `mesmo_contrato_na_pasta`)
- Test: `tests/test_contratos_conferencia.py` (onde já moram os testes de `nome_arquivo` e `mesmo_contrato_na_pasta`, ~L227-291)

**Interfaces:**
- Produces:
  - `SUFIXO_DISTRATADO = " (Distratado)"`
  - `nome_arquivo(obra, unidade, comprador, extensao=".pdf", distratado=False) -> str`
  - `mesmo_contrato_na_pasta(pasta, obra, unidade, exceto=None) -> Path | None` — `exceto` aceita um `Path` (como hoje) OU uma coleção de `Path`/nomes; nenhum deles conta como "outro".

- [ ] **Step 1: Testes que falham**

```python
from contratos import destino


def test_nome_do_distratado_leva_o_sufixo_antes_da_extensao():
    assert destino.nome_arquivo("TB 21 QD 46 LT 18", 1,
                                "PRIMEIRO COMPRADOR EXEMPLO", ".pdf",
                                distratado=True) == (
        "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01 - "
        "PRIMEIRO COMPRADOR EXEMPLO (Distratado).pdf")


def test_sem_distrato_o_nome_nao_muda():
    assert destino.nome_arquivo("TB 21 QD 46 LT 18", 1, "X", ".pdf") == \
        "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01 - X.pdf"


def test_trava_aceita_os_irmaos_da_mesma_rodada(tmp_path):
    a = tmp_path / destino.nome_arquivo("TB 21 QD 46 LT 18", 1, "A", ".pdf",
                                        distratado=True)
    b = tmp_path / destino.nome_arquivo("TB 21 QD 46 LT 18", 1, "B", ".pdf")
    a.write_bytes(b"x")
    assert destino.mesmo_contrato_na_pasta(tmp_path, "TB 21 QD 46 LT 18", 1,
                                           exceto=b) == a
    assert destino.mesmo_contrato_na_pasta(tmp_path, "TB 21 QD 46 LT 18", 1,
                                           exceto={a, b}) is None
```

- [ ] **Step 2:** rodar → FAIL. **Step 3:** implementar: em `nome_arquivo`, `if distratado: base += SUFIXO_DISTRATADO` logo antes de `return base + ext`; em `mesmo_contrato_na_pasta`, normalizar `exceto` para um conjunto de NOMES (`{p.name if isinstance(p, Path) else str(p) for p in ...}`, aceitando um `Path` só) e trocar a comparação `p.name == exceto.name` por `p.name in nomes_exceto`. **Step 4:** `python -m pytest tests/test_contratos_conferencia.py -q` → PASS.
- [ ] **Step 5:** Commit `Contratos: nome com (Distratado) e trava que aceita os irmaos da rodada`.

---

### Task 2: Achar os distratos da casa

**Files:**
- Modify: `contratos/escolha.py`
- Test: `tests/test_contratos_escolha.py`

**Interfaces:**
- Produces:
  - `MARCAS_DE_DISTRATO = ("DISTRATO", "RESCIS")`
  - `eh_distrato(nome: str) -> bool` — palavra que começa com uma das marcas (`\bDISTRATO`, `\bRESCIS`), no nome normalizado por `_norm`.
  - `distratos_da_casa(anexos: list[dict], unidade: int | None) -> list[dict]` — anexos com `eh_distrato` e `numero_da_unidade(nome) == unidade`, sem repetir nome normalizado, na ordem do ERP. Sem unidade → `[]`.

- [ ] **Step 1: Testes que falham** (usam `ANEXOS` da própria fixture do arquivo)

```python
from contratos.escolha import distratos_da_casa, eh_distrato


def test_distrato_e_rescisao_sao_distrato():
    assert eh_distrato("DISTRATO TB 21 QD 46 LT 18 C1 .pdf")
    assert eh_distrato("Termo de Rescisão CS 01.pdf")
    assert not eh_distrato("CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01 .pdf")


def test_casa_01_da_obra_real_tem_um_distrato_e_a_02_nenhum():
    assert [a["filename"] for a in distratos_da_casa(ANEXOS, 1)] == [
        "DISTRATO TB 21 QD 46 LT 18 C1 .pdf"]
    assert distratos_da_casa(ANEXOS, 2) == []
    assert distratos_da_casa(ANEXOS, None) == []
```

- [ ] **Step 2:** rodar → FAIL. **Step 3:** implementar (perto de `excluido_por`). **Step 4:** `python -m pytest tests/test_contratos_escolha.py -q` → PASS (os antigos também). **Step 5:** Commit `Contratos: achar os distratos da casa`.

---

### Task 3: `contratos/distrato.py` — comprador do contrato, grupos e sugestão

**Files:**
- Create: `contratos/distrato.py`
- Test: `tests/test_contratos_distrato.py`

**Interfaces:**
- Consumes: `escolha.eh_mais_completo`, `conferencia.conferir_nome`, `conferencia._texto_util`, `util.norm`.
- Produces:
  - `comprador_do_contrato(texto: str) -> str` — o nome depois de `COMPRADOR:` / `COMPRADORA:` / `COMPRADOR(A):` / `COMPRADORES:` até a primeira vírgula, normalizado (`util.norm`, espaços simples). `""` quando não acha.
  - `@dataclass Versao`: `anexo: dict`, `dados: bytes`, `texto: str`; propriedade `comprador -> str` (`comprador_do_contrato(texto)`).
  - `agrupar(versoes: list[Versao], comprador_recebimento: str) -> list[list[Versao]]` — chave = comprador lido (normalizado); versão sem comprador lido entra no grupo do recebimento se `conferir_nome(_texto_util(texto) or "", comprador_recebimento) == CONFERE`, senão num grupo próprio dela. Ordem: o grupo do recebimento primeiro (o que CONFERE com o comprador do recebimento), os outros em ordem de comprador.
  - `escolher(grupo: list[Versao]) -> tuple[Versao | None, str]` — um → ele; todos com bytes iguais → o primeiro; exatamente um `eh_mais_completo(nome)` → ele; senão `None` e o motivo `"N versões diferentes do contrato de <COMPRADOR>"`.
  - `foi_distratado(comprador: str, textos_distrato: list[str]) -> bool` — `True` se `conferir_nome(_texto_util(t) or "", comprador) == CONFERE` em algum texto. Comprador vazio → `False`.

- [ ] **Step 1: Testes que falham**

```python
# tests/test_contratos_distrato.py
from contratos import distrato as d

TEXTO_A = ("DAS PARTES ... doravante denominado VENDEDOR.\n"
           "COMPRADOR: PRIMEIRO COMPRADOR EXEMPLO, brasileiro, portador da "
           "carteira ... TB 21 QD 46 LT 18 CS 01 " + "x" * 60)
TEXTO_B = TEXTO_A.replace("PRIMEIRO", "SEGUNDO")
DISTRATO = ("TERMO DE DISTRATO entre a vendedora e PRIMEIRO COMPRADOR "
            "EXEMPLO referente a casa 01 " + "y" * 60)


def _v(nome, texto, dados=b"1"):
    return d.Versao({"filename": nome}, dados, texto)


def test_comprador_sai_do_trecho_das_partes():
    assert d.comprador_do_contrato(TEXTO_A) == "PRIMEIRO COMPRADOR EXEMPLO"
    assert d.comprador_do_contrato(
        "COMPRADORA:  Segunda   Compradora Exemplo , casada") == \
        "SEGUNDA COMPRADORA EXEMPLO"
    assert d.comprador_do_contrato("COMPRADOR(A): FULANO EXEMPLO, solteiro") \
        == "FULANO EXEMPLO"
    assert d.comprador_do_contrato("sem qualificação nenhuma") == ""


def test_agrupa_por_comprador_e_o_do_recebimento_vem_primeiro():
    a1 = _v("CCV CS 01.pdf", TEXTO_A, b"1")
    a2 = _v("CCV CS 01 ASSINADO.pdf", TEXTO_A, b"2")
    b = _v("CCV CS01.pdf", TEXTO_B, b"3")
    grupos = d.agrupar([a1, b, a2], "SEGUNDO COMPRADOR EXEMPLO")
    assert [[v.anexo["filename"] for v in g] for g in grupos] == [
        ["CCV CS01.pdf"], ["CCV CS 01.pdf", "CCV CS 01 ASSINADO.pdf"]]


def test_mesmo_comprador_fica_com_a_versao_mais_completa():
    a1 = _v("CCV CS 01.pdf", TEXTO_A, b"1")
    a2 = _v("CCV CS 01 ASSINADO.pdf", TEXTO_A, b"2")
    escolhida, _m = d.escolher([a1, a2])
    assert escolhida is a2


def test_duas_versoes_sem_marca_vao_para_revisao():
    escolhida, motivo = d.escolher([_v("X.pdf", TEXTO_A, b"1"),
                                    _v("Y.pdf", TEXTO_A, b"2")])
    assert escolhida is None
    assert "2 versões diferentes" in motivo


def test_bytes_iguais_sao_o_mesmo_contrato():
    escolhida, _m = d.escolher([_v("X.pdf", TEXTO_A, b"1"),
                                _v("Y.pdf", TEXTO_A, b"1")])
    assert escolhida.anexo["filename"] == "X.pdf"


def test_distratado_e_quem_aparece_no_distrato():
    assert d.foi_distratado("PRIMEIRO COMPRADOR EXEMPLO", [DISTRATO])
    assert not d.foi_distratado("SEGUNDO COMPRADOR EXEMPLO", [DISTRATO])
    assert not d.foi_distratado("", [DISTRATO])
    assert not d.foi_distratado("PRIMEIRO COMPRADOR EXEMPLO", [""])


def test_sem_comprador_lido_e_sem_conferir_fica_sozinho():
    sem = _v("ESCANEADO.pdf", "", b"9")
    a = _v("CCV.pdf", TEXTO_A, b"1")
    grupos = d.agrupar([sem, a], "PRIMEIRO COMPRADOR EXEMPLO")
    assert [len(g) for g in grupos] == [1, 1]
    assert grupos[0][0] is a
```

- [ ] **Step 2:** rodar → FAIL. **Step 3:** implementar. Regex sobre `util.norm(texto)` com os espaços (inclusive quebra de linha) reduzidos a um: `r"\bCOMPRADOR(?:A|ES|AS|\(A\)|\(ES\))?\s*:\s*([A-Z][A-Z' .-]*?)\s*,"`. Conferir com `grep -n "def norm\b" util.py` que `util.norm` tira acento e põe maiúscula. Docstring do módulo explica a decisão do dono (05/10/2026) e por que casa sem distrato não passa por aqui. **Step 4:** rodar → PASS. **Step 5:** Commit `Contratos: comprador do contrato, grupos por comprador e sugestao do distrato`.

---

### Task 4: O pipeline expande a casa com distrato e arquiva os irmãos

**Files:**
- Modify: `contratos/pipeline.py` (`Achado`, `levantar`, `chave_da_casa`, `preparar_destino`, `esperado_da_conferencia`, `arquivar`)
- Test: `tests/test_contratos_pipeline.py` (estender o `ApiDuble`: `baixar_anexo` devolve o conteúdo de um dicionário `self.conteudos.get(url, b"%PDF-falso")`)

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces (campos novos do `Achado`, todos com padrão que mantém a casa sem distrato igual):
  - `distrato: bool = False` — a marca da coluna; vira o sufixo.
  - `distrato_sugerido: bool = False`
  - `casa_com_distrato: bool = False`
  - `outro_contrato: bool = False` — linha extra da casa (não é a do comprador do recebimento).
  - `comprador_contrato: str = ""` — lido do PDF.
  - `dados: bytes | None = None` — o PDF já baixado na busca (o arquivar usa e não baixa de novo).
- `levantar(api, ano, mes, empresas, log=print, cancelar=None, abrir_pdf=None)` — `abrir_pdf` é o mesmo de `arquivar`. Sem ele, casa com distrato segue a regra de hoje (compatível).
- `MAXIMO_COM_DISTRATO = 6`, `MAXIMO_DE_DISTRATOS = 3`.
- `chave_da_casa(a)` → `a.imovel.chave + ((a.comprador_contrato,) if a.outro_contrato else ())`.

Regras do `levantar` para casa com distrato (`distratos_da_casa(...)` não vazio e `abrir_pdf` dado):
1. `cands = candidatos_distintos(...)`; vazio → regra de hoje (revisão "nenhum anexo de COMPRA E VENDA"). Mais de `MAXIMO_COM_DISTRATO` → revisão `"N contratos e distrato na casa — escolha à mão"`.
2. Baixa cada candidato (`api.baixar_anexo`), lê `abrir_pdf(dados).texto(PAGINAS_INICIAIS)`; download vazio → revisão `"não consegui baixar <nome>"`.
3. Baixa e lê até `MAXIMO_DE_DISTRATOS` distratos (texto inteiro: `leitor.texto(None)`); falha num distrato só tira aquele da sugestão.
4. `grupos = distrato.agrupar(versoes, a.imovel.comprador)`; para cada grupo, `escolher` → `Versao` ou motivo.
5. O primeiro grupo preenche o próprio `a`; os demais viram `Achado` novos (cópia rasa de `a` via `dataclasses.replace`, com `outro_contrato=True`), inseridos logo depois de `a` na lista.
6. Em cada linha: `casa_com_distrato=True`, `anexo=versao.anexo`, `dados=versao.dados`, `comprador_contrato=versao.comprador`, `distrato_sugerido = distrato.foi_distratado(versao.comprador, textos_distrato)`, `distrato = distrato_sugerido`; grupo sem escolha → `revisao = motivo`. Comprador não lido → `revisao` vazio, mas o log diz `"não consegui ler o comprador de <nome>; Distrato fica desmarcado"`.
7. Empresa: a mesma resolução de hoje para todas as linhas da casa.
8. Log por casa: `"  <obra> <casa>: N contrato(s) e M distrato(s) — <comprador> (distratado), <comprador>"`.

`preparar_destino`: `comprador = achado.comprador_contrato or achado.imovel.comprador`; `nome_arquivo(..., distratado=achado.distrato)`.

`esperado_da_conferencia`: quando `achado.outro_contrato or achado.distrato`, `"comprador": achado.comprador_contrato` e `"valor_venda": None` (é outra venda; `conferir_valor` com `None` devolve `?`, que não retém).

`arquivar`:
- Antes do laço, `irmaos = {}` por `achado.imovel.chave` com os destinos já preparados; trocar o `exceto=achado.destino` por `exceto={achado.destino, *destinos_dos_irmaos}` — preparar os destinos de TODOS os prontos num primeiro passo (`preparar_destino` não toca disco), e o laço de download usa os já preparados.
- `dados = achado.dados or api.baixar_anexo(...)`.

- [ ] **Step 1: Testes que falham** — no `tests/test_contratos_pipeline.py`. Montar uma obra própria do teste (não mexer nas existentes) com três anexos da casa 01: `"CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01 .pdf"` (texto do PRIMEIRO comprador), `"CONTRATO DE COMPRA E VENDA TB 21 QD46 LT18 CS 01 .pdf"` (texto do SEGUNDO), `"DISTRATO TB 21 QD 46 LT 18 C1 .pdf"` (texto que cita o PRIMEIRO); o recebimento do mês é do SEGUNDO. `abrir_pdf` dublê: `lambda dados: LeitorDuble(dados.decode())` com `texto(ate)` devolvendo o texto. Casos:
  - `test_casa_com_distrato_vira_uma_linha_por_comprador`: 2 achados da casa; o primeiro é do SEGUNDO (`outro_contrato False`, `distrato False`), o segundo do PRIMEIRO (`outro_contrato True`, `distrato True`, `distrato_sugerido True`).
  - `test_sem_abrir_pdf_a_casa_segue_a_regra_de_hoje`: `levantar(...)` sem `abrir_pdf` → 1 achado em revisão, como hoje.
  - `test_casa_sem_distrato_nao_baixa_nada_na_busca`: obra com um contrato só e sem distrato → `api.baixados == []` depois do `levantar`.
  - `test_comprador_ilegivel_fica_desmarcado`: o contrato do PRIMEIRO com texto vazio → a linha extra existe com `distrato False` e `comprador_contrato == ""`.
  - `test_arquivar_grava_os_dois_e_o_distratado_com_sufixo(tmp_path)`: depois de `levantar` + `arquivar` (com o `abrir_pdf` dublê e endereço do `detalhe_da_obra`), a pasta tem os dois arquivos, um terminando em `"(Distratado).pdf"`; nenhum dos dois em revisão; `api.baixados` não cresce no arquivar (usou `dados`).
  - `test_rodada_refeita_diz_ja_estava`: rodar `arquivar` duas vezes → na segunda, os dois com `ja_existia True`.
  - Regressão: os testes atuais do arquivo passam sem mudar asserção.
- [ ] **Step 2:** rodar → os novos FALHAM. **Step 3:** implementar como descrito; atualizar docstrings de `levantar`/`arquivar` com a casa com distrato. **Step 4:** `python -m pytest tests -q -k contratos` → PASS. **Step 5:** Commit `Contratos: casa com distrato vira uma linha por comprador e os irmaos sao arquivados`.

---

### Task 5: A coluna DISTRATO na aba

**Files:**
- Modify: `contratos/frame.py` (colunas, `_mostrar`, `_clique_na_tabela`, `_duplo_clique`, `_t_buscar` passa `abrir_pdf`, `_resumo`)
- Test: `tests/test_contratos_frame_distrato.py` (novo, monta a aba de verdade com a fixture `raiz`)

**Interfaces:**
- Consumes: campos do `Achado` (Task 4).
- Produces: `ContratosFrame._alternar_distrato(iid: str) -> None`.

Mudanças:
- `colunas = ("marca", "distrato", "obra", "casa", "comprador", ...)`; título `"DISTRATO"`, largura 70, centro. Valor: `_MARCA[a.distrato]` quando `a.anexo`, senão `""`.
- Coluna "comprador": `a.comprador_contrato or i.comprador or i.descricao`; linha extra acrescenta `"  (outro contrato da casa)"`.
- `_clique_na_tabela`: coluna `#2` → `_alternar_distrato(iid)`; `_duplo_clique` também devolve `"break"` em `#2`.
- `_alternar_distrato`: sem `anexo` → aviso no `self.lbl` ("Esta linha não tem contrato para marcar como distrato."); com → inverte `a.distrato` e atualiza a célula.
- `_t_buscar`: `pipeline.levantar(..., abrir_pdf=lambda dados: leitura.abrir_pdf(dados, self._log))`.
- `_resumo` (o .txt): linhas com distrato ganham `"  (Distratado)"`.
- O texto de ajuda do cartão menciona: "Casa com distrato aparece com um contrato por comprador; marque DISTRATO no que foi distratado — ele é salvo com (Distratado) no nome."

- [ ] **Step 1: Teste que falha** (antes, ver como `tests/test_registro_visivel.py` monta o `ContratosFrame` e copiar o dublê do `anexar_frame`)

```python
# tests/test_contratos_frame_distrato.py
from contratos import frame as cf
from contratos.pipeline import Achado
from contratos.regras import Imovel


def _achado(nome, distrato=False, outro=False):
    im = Imovel(obra="TB 21 QD 46 LT 18", unidade=1,
                comprador="SEGUNDO COMPRADOR EXEMPLO")  # conferir campos reais de Imovel
    return Achado(imovel=im, anexo={"filename": nome}, empresa="EMPRESA MODELO",
                  distrato=distrato, distrato_sugerido=distrato,
                  outro_contrato=outro, comprador_contrato=(
                      "PRIMEIRO COMPRADOR EXEMPLO" if outro else ""))


def test_coluna_distrato_mostra_a_sugestao_e_alterna(raiz):
    aba = cf.ContratosFrame(raiz, AnxDuble())   # dublê copiado do teste existente
    try:
        aba.achados = [_achado("A.pdf"), _achado("B.pdf", distrato=True, outro=True)]
        aba._mostrar(aba.achados)
        assert aba.tabela.set("0", "distrato") == cf._MARCA[False]
        assert aba.tabela.set("1", "distrato") == cf._MARCA[True]
        assert "outro contrato da casa" in aba.tabela.set("1", "comprador")
        aba._alternar_distrato("1")
        assert aba.achados[1].distrato is False
        assert aba.tabela.set("1", "distrato") == cf._MARCA[False]
    finally:
        aba.destroy()
```

(Conferir os campos obrigatórios de `Imovel` com `grep -n "class Imovel" -A20 contratos/regras.py` e ajustar o construtor do teste.)

- [ ] **Step 2:** rodar → FAIL. **Step 3:** implementar. **Step 4:** `python -m pytest tests -q -k "contratos or registro_visivel"` → PASS. **Step 5:** Commit `Contratos: coluna DISTRATO na tabela, sugerida pela busca e alternada no clique`.

---

### Task 6: Acessórias entende o "(Distratado)"

**Files:**
- Modify: `acessorias/pacote.py` (`linha_do_contrato`)
- Test: `tests/test_acessorias.py`

- [ ] **Step 1: Teste que falha**

```python
def test_linha_do_contrato_distratado_mantem_a_marca():
    nome = ("CONTRATO DE COMPRA E VENDA RPB 99 QD 1A LT 2 CS 01 - "
            "FULANO DE TAL (Distratado).pdf")
    assert pacote.linha_do_contrato(nome) == \
        "RPB 99 QD 1A LT 2 Casa 01 - Fulano de Tal (Distratado)"
```

- [ ] **Step 2:** rodar → FAIL. **Step 3:** em `linha_do_contrato`, tirar o sufixo do `base` antes do `RE_CONTRATO.match` (`from contratos.destino import SUFIXO_DISTRATADO` NÃO — acessorias não importa contratos; repetir a constante `SUFIXO_DISTRATADO = " (Distratado)"` com um comentário apontando para `contratos/destino.py`) e devolvê-lo no fim da linha. **Step 4:** `python -m pytest tests/test_acessorias.py -q` → PASS. **Step 5:** Commit `Acessorias: contrato distratado entra na lista com a marca`.

---

### Task 7: Documentação, régua inteira e PR em rascunho

**Files:**
- Modify: `.claude/rules/arquitetura-contratos.md` (decisões 1 e 7: "no máximo um contrato por casa" passa a "um por comprador quando a casa tem distrato"; o sufixo; a leitura do comprador)
- Modify: `C:/AUTOMAÇÕES MAIS CONTROLE/PLANO - 2026-09-09 contratos de venda em todo recebimento.md` — NÃO (fora do repo; não mexer).

- [ ] **Step 1:** Escrever o parágrafo no estilo do arquivo.
- [ ] **Step 2:** Régua completa: `ruff check --select E9,F .`, vermin 3.11 nos arquivos mudados, `python -m pytest tests -q` (anotar o número).
- [ ] **Step 3:** Commit `Docs: contratos com distrato`.
- [ ] **Step 4:** `git push -u origin codigo/contratos-distrato`; `gh pr create --draft` com corpo em português (o pedido, as duas decisões, o que mudou, o que o dono confere no app: buscar um mês com a casa que tem distrato, ver as duas linhas, a marca sugerida e o nome do arquivo). Não mesclar.
