---
paths:
  - "cnab240/**"
  - "pagamentos_dia/remessa_dia.py"
  - "pagamentos_dia/retorno_dia.py"
  - "tests/test_cnab240*.py"
---

# Arquitetura: cnab240/

> Trecho da seção "Arquitetura", movido do `CLAUDE.md` em 14/09/2026 sem mudar uma palavra.
> Carrega sozinho quando o Claude lê um arquivo dos caminhos acima.
> Mudou o código? Atualize AQUI — este é o lugar deste texto agora.

- `cnab240/` — gerador, validador e leitor de retorno do arquivo CNAB 240 do
  Sicoob (Guia v3.3), **stdlib pura** e sem tela nenhuma: é biblioteca, não aba.
  Quem a usa é o passo 3 da aba Pagamentos do Dia (`pagamentos_dia/remessa_dia.py`).
  **O único pacote do app com arquivo de DADOS**: os layouts vivem em
  `cnab240/spec/*.json`, campo a campo com o id do manual, para auditar contra
  o PDF sem abrir código — daí a linha extra no `build.yml` e o
  `tests/test_cnab240_pacote.py` que a vigia.
  **`historico.py` é a parte que o layout não resolve**: o NSA (nº sequencial
  do arquivo) tem de ser CRESCENTE por convênio — **e o convênio é POR CONTA
  (04/09/2026)**, não por empresa: o Sicoob dá um por conta corrente, e uma
  holding do cadastro tem nove, a principal e oito subcontas. Uma sequência de
  NSA por conta corrente, portanto — quem o controla é quem gera,
  o banco não guarda isso. Ele mora em `remessas.json` ao lado do exe, longe
  do cadastro de propósito: `contas_sicoob.json` é restaurado de backup, e um
  contador que volta no tempo é a única falha inaceitável aqui. Repetir NSA
  pode significar pagamento em dobro; pular número é inofensivo. O mesmo
  arquivo guarda o de-para "seu número → id do lançamento", que é o que o
  retorno usa para achar o caminho de volta.
  **Validado contra o banco em 13/08/2026** (`Válido`): header,
  boleto J+J-52, Pix por chave A+B e dois lotes no mesmo arquivo. Fora dali —
  TED, Pix QR Code, tributos e folha — a biblioteca gera, mas ninguém provou.
  Um achado dessa validação: o guia OMITE a forma de iniciação `03` (CPF/CNPJ)
  na descrição da Informação 12 do segmento B, e o banco recusa o campo em
  branco. Manual incompleto; a correção está comentada em `remessa.py`.
  **Existe UMA cópia deste pacote, e é esta.** Até 02/09/2026 havia uma
  segunda, no repositório das automações avulsas (`fontes/cnab240`), com CLI e
  testes próprios. Ela parou em 14/08 e nunca soube que `dv_cpf`, `dv_cnpj` e
  `documento_valido` passaram a existir em `dominios.py` em 20/08 — depois de
  o Sicoob devolver a remessa 000002 por um CPF de preenchimento vindo do
  cadastro. Os 84 testes dela passavam verdes justamente por não saberem que a
  validação existia, e o exemplo dela, rodado contra este código, produz 16
  problemas de dígito verificador. Quem a importava eram os quatro scripts de
  validação com o banco, por caminho absoluto escrito à mão; eles agora moram
  em `cnab240/ferramentas/`, importam o pacote daqui e **conferem em tempo de
  execução** que foi daqui que ele veio. A pasta fica fora do `codigo.zip` de
  propósito (o app nunca a importa), pelo `_PASTAS_SO_DO_REPO` do
  `test_empacotamento.py` — o mesmo tratamento do `nuvem/migrar.py`. Quatro
  testes em `test_cnab240.py` impedem a volta: um `dominios.py` só no
  repositório, as ferramentas importando `cnab240` e sem caminho externo no
  `sys.path` (por AST), e as três funções de DV existindo **e recusando**. A
  regra geral: uma biblioteca que move dinheiro não tem cópia de trabalho — a
  cópia envelhece em silêncio, e o silêncio dela é uma aprovação falsa.
