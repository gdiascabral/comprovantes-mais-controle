# -*- coding: utf-8 -*-
"""Conversa do app com o banco na nuvem (Supabase).

Cada módulo daqui tem UM trabalho, e a divisão não é enfeite: é o que permite
mexer no cadastro sem tocar no login, e trocar o transporte sem reescrever
regra nenhuma.

    rest.py           HTTP: URL, cabeçalho, timeout, erro com nome
    sessao.py         entrar, sair, renovar; guarda o token cifrado
                      e quem é a pessoa no cadastro (nome e papel)
    login_dialogo.py  a janela de login
    cache.py          a cópia local (os mesmos JSON/CSV de sempre)
    cadastro.py       contas, empresas, entidades e regras — LÊ, com cache
    registro.py       o que já foi feito — ESCREVE, sem cache

**A assimetria entre `cadastro` e `registro` é deliberada.** Cadastro tolera o
banco mudo: usa a última cópia e avisa. Registro não: o valor inteiro de
gravar "este aporte já foi lançado" é ser verdade nas duas máquinas ao mesmo
tempo, e um cache local que dissesse "provavelmente ninguém lançou" é pior que
não ter nada — lança de novo, e dinheiro duplicado se desfaz à mão.

Fala REST puro por `requests`, que o motor já embute. A biblioteca oficial
`supabase-py` obrigaria exe novo (~150 MB para cada pessoa) a cada correção,
em vez de o `codigo.zip` chegar em segundos.
"""
