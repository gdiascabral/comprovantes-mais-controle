# -*- coding: utf-8 -*-
"""Aba Anexar Comprovantes: casa cada PDF com o pagamento dele e anexa no ERP.

Pacote desde 02/09/2026. Antes a pasta entrava inteira no `sys.path`, e era
daqui que saíam os dois nomes mais disputados do repositório: `config` (que
`acessorias/` e `conciliacao/` também têm) e `conferencia` (que `contratos/`
também tem). Quem chegasse depois no caminho ganhava o nome e o outro módulo
sumia sem erro. Agora são `anexar.config` e `anexar.conferencia`, e a disputa
deixou de existir.
"""
