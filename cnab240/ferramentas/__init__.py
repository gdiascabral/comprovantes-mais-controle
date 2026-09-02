# -*- coding: utf-8 -*-
"""Ferramentas de validação com o banco. NÃO fazem parte do exe.

São os scripts que se roda à mão, na máquina que tem o cadastro, para fazer ao
Sicoob uma pergunta de cada vez: *este layout você aceita?* Cada um gera um
`.REM` inofensivo (centavos, títulos que não existem) para o botão `Validar` do
SicoobNet — nenhum deles transmite nada.

Moram DENTRO do pacote, e não numa pasta solta fora do repositório, porque a
pergunta que fazem só vale se for feita ao MESMO código que vai para a release.
Enquanto viveram fora, importavam uma segunda cópia do `cnab240` que parou no
tempo em 14/08/2026 — e por isso não conheciam `dv_cpf`, `dv_cnpj` nem
`documento_valido`. Os testes dela passavam verdes justamente por não saberem
que a validação existia, e o CPF de preenchimento que derrubou a remessa
000002 teria passado por ali sem um pio.

Não entram no `codigo.zip`: o app nunca as importa, e ferramenta de operador
não tem por que viajar para a máquina de quem usa. É o mesmo tratamento do
`nuvem/migrar.py`, escrito em `tests/test_empacotamento.py`.

Como rodar, da raiz do repositório:

    python -m cnab240.ferramentas.gerar_teste
    python -m cnab240.ferramentas.gerar_teste_2
    python -m cnab240.ferramentas.gerar_teste_3_arrecadacao
    python -m cnab240.ferramentas.conferir_segmento_o
"""
