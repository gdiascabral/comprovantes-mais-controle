# -*- coding: utf-8 -*-
"""Ajustes do envio ao portal Acessórias.

Aqui só entra o que é genérico. **O endereço do portal não mora neste
arquivo**: ele carrega o nome do escritório contábil, que é fornecedor real, e
o repositório é público. O URL sai do `contas_sicoob.json` (chave `vip_url`),
junto do `vip_id` de cada empresa — mesma decisão já tomada para o
`pix_reembolso.json` e para o mapa das contas.

Sem tkinter e sem navegador: só constantes.
"""

import util

#: Perfil do Chrome do portal, separado do Mais Controle e do Sicoob: são três
#: sites e três logins, e o Playwright síncrono não divide thread entre eles.
#: Sai de `util.pasta_do_perfil()`, e não de um `_AQUI` próprio — era a mesma
#: conta de sempre (pasta do exe quando congelado), mas uma segunda cópia da
#: regra é uma divergência esperando acontecer.
PASTA_PERFIL_CHROME = util.pasta_do_perfil("acessorias")

#: O host do fornecedor do portal (não é o nome do escritório). Serve para
#: reconhecer que ainda estamos dentro do portal, e não numa página de erro.
HOST = "vip.acessorias.com"

#: Caminhos, relativos ao endereço do escritório (`vip_url`).
#: O `0` de SOL é o formulário em branco — não é uma solicitação de id 0.
CAMINHO_EMPRESA = "/{vip_id}/"
CAMINHO_SOLICITACOES = "/{vip_id}/SOL/"
CAMINHO_SOLICITACAO_NOVA = "/{vip_id}/SOL/0"

#: Calendário de uma empresa num mês. A página já traz o mês inteiro num JSON
#: (`dataJson`), então é UMA ida ao portal por empresa, e não uma por dia.
CAMINHO_CALENDARIO = "/{vip_id}/CLD/{competencia}"

#: Onde as guias baixadas ficam, dentro da pasta da empresa no mês.
SUBPASTA_GUIAS = "GUIAS"

#: O link do documento devolve um HTML com um iframe apontando para um S3 que
#: expira em 120 s: o download vem LOGO em seguida, na mesma passada.
RE_IFRAME = r"<iframe[^>]+src=['\"]([^'\"]+)['\"]"

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

#: Para onde o Salvar/Enviar manda o formulário, por XHR. É por esta RESPOSTA
#: que o envio espera — a página não troca, e esperar a página não espera o
#: upload (ver `portal.criar_solicitacao`).
CAMINHO_ENVIO = "/sysvipsolAjax"

#: A sessão do portal não expira rápido, mas o upload de um zip de fechamento
#: pode ser grande: o tempo do envio é folgado de propósito.
TEMPO_PADRAO = 45_000
TEMPO_ENVIO = 10 * 60 * 1000
TEMPO_LOGIN = 10 * 60 * 1000        # a pessoa precisa digitar e-mail e senha

#: Depois da resposta do envio: o alert do portal e a troca de página que ele
#: pode fazer sozinho têm a vez antes do `goto` da conferência.
ESPERA_APOS_ENVIO = 1500

#: A conferência relê a lista até achar a solicitação: a resposta do envio já
#: voltou, mas a lista pode levar um instante para mostrá-la.
RELEITURAS_DA_LISTA = 3
ESPERA_RELEITURA = 3000
