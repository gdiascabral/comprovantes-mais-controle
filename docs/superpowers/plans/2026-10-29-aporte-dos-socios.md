# Aporte dos sócios (pacote 1) — plano

> Executado na própria sessão (o dono autorizou na noite de 29/10/2026:
> "pode fazer tudo"). Passos com checkbox.

**Objetivo:** o aporte "de fora" na conta-mãe (e na conta que a mãe só
transfere) vira Aporte de Capital de cada sócio na aba Aportes, dividido
meio a meio numa janela; o cartão Aportes mostra quem precisa igualar,
pela apuração do Controle de aportes, que roda sozinho depois do Buscar.

**Spec:** `docs/superpowers/specs/2026-10-29-aporte-jv-jc-e-autenticar-design.md` (PR 1).

## Restrições globais

- Regra em módulo puro com teste sem janela; `frame.py` e `janelas.py` finos.
- Dinheiro em `Decimal`; nada de nome real, CPF, conta ou saldo no repo.
- Aporte não se repete: chave própria no JSON do dia, gravada ANTES de entregar.
- Python 3.11 (vermin); nada de import novo da stdlib.

## Foco da revisão

1. Arquivo do dia com chave `defora:` de um clique anterior: não manda de novo, mesmo com valor diferente.
2. Sócio do `confirmar_antes.json` que casa com DOIS cadastros (prefixo): pendência, nunca o primeiro.
3. Divisão com centavo ímpar: soma exata (nunca R$ 0,01 perdido).
4. Mesmo par na aba Regras: as DUAS pontas viram pendência.
5. Controle que falha ou está lendo: o Buscar não trava e o cartão diz por quê.

## Arquivos

- Criar `tela_do_dia/aporte_dos_socios.py` — regra pura.
- Criar `tests/test_tela_do_dia_aporte_dos_socios.py`.
- Mudar `tela_do_dia/para_aportes.py` — `operacoes(pares_em_dobro=)`.
- Mudar `tela_do_dia/janelas.py` — `pedir_divisao`.
- Mudar `tela_do_dia/controle_frame.py` — `ouvintes` e `atualizar_se_livre`.
- Mudar `tela_do_dia/frame.py` — janela no Mandar, faixa de igualar, Controle depois do Buscar.
- Mudar `comprovantes_app.py` — `aba_dia.controle = aba_cap`.
- Atualizar `.claude/rules/arquitetura-tela-do-dia.md`.

### Tarefa 1: regra pura `aporte_dos_socios`

Interface (o que o frame usa):

- `PREFIXO = "defora:"`; `chave(socio, destino) -> str`.
- `contas_da_mae(regras, mae) -> list[str]` — a mãe e os destinos para onde
  ela só TRANSFERE na aba Regras (a mesma empresa noutro banco).
- `movimentos_de_fora(a_mao, contas) -> (dict[destino, Decimal], list[(destino, Decimal)])`
  — somados por destino; os de fora fora dessas contas vão na 2ª lista.
- `socios(nomes, entidades) -> (list[str], str)` — os nomes do cadastro, ou o recado.
- `meio_a_meio(valor) -> (Decimal, Decimal)` — centavo ímpar para o primeiro.
- `ler_parte(texto) -> Decimal` (vazio = 0) e `validar_divisao(valor, partes) -> str`.
- `ja_mandados(enviados, destino) -> bool` — há chave `defora:` para o destino.
- `operacoes(divisoes, valores, entidades, subcontas, data, enviados, definidos,
  sem_saldo=(), na_aba_aportes=None) -> (Envio, set[(destino, aportador)])`
  — o segundo valor são os pares da aba Regras em dobro.
- `juntar(envio, outro)` — soma o `Envio` dos sócios no da aba Regras.
- `avisos_de_igualar(apuracoes, erro="") -> list[str]` e
  `avisos_dos_socios(apuracoes, socios) -> list[str]`.

- [ ] Testes que falham (centavo ímpar; soma que não bate; parte zero; as
  duas zero; já mandado com valor igual e diferente; sócio fora do cadastro
  e casado com dois; destino subconta de investidor; par na Regras nas duas
  pontas; conta para onde a mãe transfere; avisos com conta igualada,
  devedor, dois devedores, leitura com erro).
- [ ] Implementar até passar; commit.

### Tarefa 2: `para_aportes.operacoes(pares_em_dobro=)`

Par `(destino, aportador)` da aba Regras que também foi dividido de fora
vira pendência "esse sócio também aporta nesta conta à mão hoje (R$ X) —
tire um dos dois". Teste no mesmo arquivo; commit.

### Tarefa 3: janela e frame

- `janelas.pedir_divisao(tela, linhas, socios, avisos, validar) -> dict | None`
  — `{destino: {socio: Decimal}}`; a validação é a do módulo puro.
- `_mandar_aportes`: antes das operações, se houver de fora não mandado,
  resolve os sócios (recado no Registro se não der), abre a janela; Cancelar
  = nada vai. Junta o `Envio` dos sócios ao da Regras; o resto do fluxo
  (gravar antes, recusas) não muda.
- Faixa `lbl_igualar` no cartão 3 com `avisos_de_igualar`.
- Controle: `ControleAportesFrame.ouvintes` (chamados no fim de cada
  leitura, com as apurações ou o erro) e `atualizar_se_livre()` (não abre
  diálogo de "navegador ocupado"). O frame tenta no fim do `_receber_leitura`
  e de novo a cada 2 s, até 90 vezes, enquanto a vaga do Controle estiver ocupada.
- Guardas por AST: o frame chama `_rodar_controle` no `_receber_leitura` e
  a janela no `_mandar_aportes`.
- [ ] Commit.

### Tarefa 4: regras do pacote, suíte e revisor

- [ ] Atualizar `arquitetura-tela-do-dia.md`.
- [ ] `ruff check --select E9,F`, `vermin --target=3.11`, todos os testes sem janela.
- [ ] `revisor-dinheiro` sobre o diff; consertar; PR.
