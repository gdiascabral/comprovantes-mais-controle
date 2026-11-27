# -*- coding: utf-8 -*-
"""Leitura das 07:30 (entrega E1a da spec 2026-11-27-aba-pagamentos-no-portal).

Job SEM tela, rodado pelo Agendador do servidor: lê o saldo de cada conta no
Sicoob (API Conta Corrente) e no Inter (API Banking), o saldo de cada conta no
ERP pelo porteiro, o extrato de ontem, casa o extrato com os agendados em
aberto (`tela_do_dia.autenticar`, que só PRÉ-MARCA) e grava tudo na nuvem com
o usuário de papel `robo`. Não paga, não escreve no ERP, não responde
agendado: quem responde "Pago" continua sendo a pessoa (regra de 29/10/2026).

Fica fora do `codigo.zip` (`tests/test_empacotamento.py`): roda só do clone do
repositório no servidor; o app nunca o importa.
"""
