# -*- coding: utf-8 -*-
"""Ajustes do envio ao portal Acessórias.

Aqui só entra o que é genérico. **O endereço do portal não mora neste
arquivo**: ele carrega o nome do escritório contábil, que é fornecedor real, e
o repositório é público. O URL sai do `contas_sicoob.json` (chave `vip_url`),
junto do `vip_id` de cada empresa — mesma decisão já tomada para o
`pix_reembolso.json` e para o mapa das contas.

Sem tkinter e sem navegador: só constantes.
"""
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # Empacotado: a pasta do .exe, para o perfil do Chrome persistir entre
    # execuções (é ele que guarda o "Manter conectado" do portal).
    _AQUI = Path(sys.executable).resolve().parent
else:
    _AQUI = Path(__file__).resolve().parent.parent

#: Perfil do Chrome do portal, separado do Mais Controle e do Sicoob: são três
#: sites e três logins, e o Playwright síncrono não divide thread entre eles.
PASTA_PERFIL_CHROME = _AQUI / ".chrome_profile_acessorias"

#: O host do fornecedor do portal (não é o nome do escritório). Serve para
#: reconhecer que ainda estamos dentro do portal, e não numa página de erro.
HOST = "vip.acessorias.com"

#: Caminhos, relativos ao endereço do escritório (`vip_url`).
#: O `0` de SOL é o formulário em branco — não é uma solicitação de id 0.
CAMINHO_EMPRESA = "/{vip_id}/"
CAMINHO_SOLICITACOES = "/{vip_id}/SOL/"
CAMINHO_SOLICITACAO_NOVA = "/{vip_id}/SOL/0"

#: Rótulos do formulário. Escolha por RÓTULO, nunca por índice: os `value` dos
#: dois selects não seguem a ordem da tela (DPTO_FINANCEIRO é o último item e
#: vale 4; a prioridade é invertida, Baixa=3 e Muito Alta=0). Escolher por
#: posição manda o fechamento para o departamento errado, e a tela não denuncia.
DEPARTAMENTO = "DEPTO_FISCAL"
PRIORIDADE = "Baixa"

#: Seletores do formulário de solicitação nova.
#: `#SolAss` fica FORA do `<form>` e é recolhido por JS no envio — por isso o
#: preenchimento é sempre pela tela, nunca um multipart montado à mão.
SEL_ASSUNTO = "#SolAss"
SEL_DEPARTAMENTO = "#SolDpto"
SEL_COMENTARIO = "#txt_comentario"
SEL_ANEXO = "#txt_anexo"
SEL_PRIORIDADE = "#SolPrioridade"
SEL_SALVAR = "#btn_salvar"

#: A sessão do portal não expira rápido, mas o upload de um zip de fechamento
#: pode ser grande: o tempo do envio é folgado de propósito.
TEMPO_PADRAO = 45_000
TEMPO_ENVIO = 10 * 60 * 1000
TEMPO_LOGIN = 10 * 60 * 1000        # a pessoa precisa digitar e-mail e senha
