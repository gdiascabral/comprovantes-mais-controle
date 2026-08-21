# Conta nova no ERP: o app pergunta na abertura — design

Data: 21/08/2026
Onde: abertura do app (`comprovantes_app.py`) + `nuvem/`

Ontem foram criadas quatro contas no Mais Controle. O app não soube — e só
saberia quando um pagamento caísse numa delas, porque a única detecção que
existe hoje é a da Conciliação, que classifica o LANÇAMENTO em conta
desconhecida como `unmapped` depois do fato.

Este é o primeiro de três marcos combinados com o dono:

1. **este** — na abertura, comparar o cadastro do ERP com o nosso e perguntar;
2. o vínculo `entidade.conta` deixar de ser texto solto;
3. as abas deixarem de abrir o Chrome para falar com o ERP.

---

## O que já existe (e por isso este marco é pequeno)

- `conciliacao/erp/api.py::SessaoApi.logar` — **login por HTTP puro**, sem
  navegador, com as credenciais guardadas (`login.dat`, cifrado com a DPAPI).
- `SessaoApi.listar_contas()` — as contas do ERP, paginadas, já com
  `bank_code`, `agency` e `account_number`.
- `nuvem/rest.py::inserir` — escrita no nosso Supabase, já implementada.
- `contas_mc.json` — exatamente as contas do nosso cadastro que têm
  `nome_erp`, que é a chave de comparação.

Faltava ligar as quatro coisas.

## A sessão, e a ordem que ela impõe

O ERP admite **uma sessão por usuário**: o login por API derruba a sessão do
navegador, e vice-versa. Foi o defeito que a Conciliação corrigiu em 18/08.

A ordem resolve: a conferência roda **na abertura**, quando ainda não existe
Chrome nenhum. Quando uma aba abrir o navegador depois, ela derruba o token da
API — e não há problema, porque a conferência já terminou.

`SessaoApi` pede um `config` só para as duas URLs base. Este marco monta um
objeto mínimo com elas em vez de importar `conciliacao/config.py`: aquele
arquivo é um dos que divergem entre o repositório e a máquina do dono, e
depender dele acoplaria a abertura do app a essa divergência.

Pelo mesmo motivo `conciliacao/erp/api.py` **não é movido** de lugar, embora
fosse o certo: mover obrigaria a mexer nos imports de `pipeline.py`, que é
outro dos arquivos divergentes. Fica onde está, importado de fora. Quando o
marco 3 chegar, ele muda de casa.

## O que é conferido, e o que não é

**Contas.** O ERP tem as suas, nós temos as nossas; conta que existe lá e não
aqui é novidade.

**Fornecedor não entra**, e é decisão com motivo: são 394 no cadastro, e
fornecedor novo **não precisa** de cadastro nosso — ele já é pago normalmente.
Só o caso especial tem regra (`so_com_reembolso`, `pagar_a_mao`,
`so_marcador`). Perguntar sobre cada fornecedor novo seria ruído diário sem
decisão do outro lado.

## A janela

Não é um sim/não. O ERP dá `id`, `nome`, banco, agência e número; o nosso
cadastro exige **empresa** e **pasta**, que o ERP não tem como saber. Então:

```
4 contas novas no Mais Controle

[x] MORAIS ENG - SUBCONTA 58123-4 - SICOOB
      empresa: [MORAIS ENGENHARIA v]   pasta: [_______________]
      banco 756 · ag 3299 · conta 58123-4        (vindos do ERP)

[ ] IPANEMA - INTER
```

Marcada sem pasta preenchida não é gravada — e a janela diz qual falta, em vez
de gravar com pasta vazia (que é `not null` no banco e viraria erro de SQL
cru na cara do usuário).

O que ficar desmarcado **não é gravado como "não"** em lugar nenhum: não entra,
e volta a aparecer na próxima abertura. Guardar recusa seria um terceiro estado
para manter; a lista some sozinha quando a conta for cadastrada.

## Onde a resposta é gravada

`INSERT` na tabela `conta` do nosso Supabase, via `rest.inserir`. O Mais
Controle **não é tocado** — conta nasce lá, por gente.

A RLS ganha `insert` e `update` para `conta`; **`delete` continua proibido**.
A decisão de 14/08 (o app só lê) muda no mínimo necessário: um token vazado
passa a poder sujar o cadastro com linhas a mais — chato e reversível — em vez
de esvaziá-lo, que é irreversível sem backup.

## Quando dá errado

Sem rede, login vencido, MFA ligado, ERP fora do ar: o app **abre normalmente**
e a conferência vira uma linha no log. Nunca bloqueia a abertura — travar o app
inteiro por causa de uma conferência opcional seria o pior negócio possível, e
é a mesma regra que já protege o `sincronizar` logo acima dela.

Roda numa thread, e a janela só aparece se houver novidade. Abertura sem conta
nova é indistinguível da de hoje.

## Testes

| Teste | O que prova |
|---|---|
| comparação | acha o que é novo, ignora o que já está, não repete |
| comparação por nome normalizado | acento e caixa não criam novidade falsa |
| ERP vazio / cadastro vazio | nenhum dos dois estoura |
| escolha sem pasta | não é gravada, e o motivo aparece |
| gravação | chama `inserir` com os campos certos, e nunca `apagar` |
| falha de login | devolve lista vazia e não levanta |
