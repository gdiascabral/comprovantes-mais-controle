# -*- coding: utf-8 -*-
"""Baixa os comprovantes de pagamento direto do banco.

Depois do dia de pagamentos, os comprovantes vinham à mão de cada banco para
alimentar o Separar/Renomear e o Anexar. A pessoa deve fazer só a parte que o
banco EXIGE dela — escanear o QR code no celular —, e o resto é trabalho de
robô: navegar, filtrar o período, baixar cada PDF e arquivar na pasta certa.

A diferença entre os dois bancos manda no desenho, e não é detalhe:

    Inter    cada conta é um login   -> um QR POR CONTA
    Sicoob   um login vê N contas    -> UM QR para todas

Por isso a fila da aba (fase 4) começa pelo Sicoob: um QR resolve várias
contas, e é o maior ganho pelo menor incômodo de quem está na frente da tela.

    inter_baixar.py   o motor do Inter (portado do CLI que já rodava)
"""
