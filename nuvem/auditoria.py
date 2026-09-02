# -*- coding: utf-8 -*-
"""Quem fez o quê, e quando. Nos dois lugares, pelo mesmo motivo duas vezes.

**Por que na nuvem.** "Quem liberou este pagamento?" é uma pergunta que se faz
depois — às vezes semanas depois, de outra máquina, e às vezes sobre alguém
que já saiu. Um arquivo na pasta de quem rodou não responde nada disso: ele
está na máquina errada, e quem o escreveu podia editá-lo.

**Por que também local.** O `atividade.jsonl` é o que a tela de Início lê para
montar o painel, e ele funciona sem internet. Se este módulo gravasse só na
nuvem, um dia sem rede seria um dia sem histórico nenhum na tela.

Então cada registro vai para os dois, e as duas metades falham separado: a
local é síncrona e não fala com ninguém; a da nuvem roda fora da thread de
quem chamou e, se não der, não deixa rastro na tela — de propósito. **Nada
aqui pode derrubar o trabalho de ninguém.** Um pagamento que já saiu não pode
ser desfeito porque o registro dele não subiu.

**Quem assina.** O `quem` NÃO é enviado. A coluna tem `default auth.uid()` e a
política tem `with check (quem = auth.uid())`: o servidor carimba a partir do
token, e o app não tem como dizer que foi outro. Um campo que o cliente
preenche não responde "quem fez" — responde "quem o cliente disse que fez".
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

try:
    from . import rest, sessao
except ImportError:
    import rest
    import sessao

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

log = util.log(__name__)

#: A tabela é append-only: `authenticated` tem insert e select, e não tem
#: update nem delete (migration da fase 1). Corrigir depois é o que faria o
#: registro não servir para nada.
TABELA = "auditoria"


def gravar_agora(acao: str, detalhe: str = "") -> bool:
    """Grava na nuvem, na thread de quem chamou. True se o servidor aceitou.

    Nunca levanta: devolve False. Quem chama está no meio de outra coisa — um
    login, uma aprovação, uma remessa — e nenhuma delas pode parar porque o
    registro não subiu."""
    acao = (acao or "").strip()
    if not acao:
        return False                     # o banco recusaria: `acao` não vazia
    try:
        rest.inserir(TABELA, sessao.token(),
                     [{"acao": acao[:200], "detalhe": (detalhe or "")[:500]}],
                     devolver=False)
        return True
    except Exception:                                        # noqa: BLE001
        # Amplo de propósito. Sem rede, sessão vencida, projeto pausado, disco
        # do servidor cheio: nenhuma dessas é razão para uma remessa parar no
        # meio.
        return False


def registrar(acao: str, detalhe: str = "", *, aba: str = "acesso",
              resultado: str = "ok", numeros: dict | None = None) -> None:
    """Anota o que acabou de acontecer, local e na nuvem.

    A parte local acontece JÁ, e é a que a tela de Início vai ler. A da nuvem
    sai numa thread solta porque o `rest` espera até 20 segundos por uma
    resposta, e alguns destes pontos são o clique de um botão: uma janela
    congelada por 20 segundos é indistinguível de um app travado.

    `aba`, `resultado` e `numeros` são os do `widgets.registrar_atividade` —
    quem já chamava aquele troca por este e a tela de Início continua vendo a
    mesma coisa."""
    _espelhar_local(aba, acao, resultado, detalhe, numeros)
    threading.Thread(target=gravar_agora, args=(acao, detalhe),
                     daemon=True).start()


def _espelhar_local(aba, acao, resultado, detalhe, numeros) -> None:
    """O `widgets` entra aqui dentro, e não no topo do arquivo.

    Importá-lo lá de cima puxaria o tkinter para dentro de `nuvem/usuarios.py`,
    que é regra pura e não tem tela — e o pacote inteiro deixaria de importar
    numa máquina sem display."""
    try:
        import widgets
        widgets.registrar_atividade(aba, acao, resultado, detalhe, numeros)
    except Exception:                                        # noqa: BLE001
        log.warning("espelhando a atividade '%s' no atividade.jsonl", aba,
                    exc_info=True)


def recentes(quantos: int = 50) -> list[dict]:
    """As últimas linhas da nuvem, mais novas primeiro. [] se não der.

    Cada um lê as próprias; o admin lê as de todo mundo — é a política
    `auditoria_le_a_propria` que decide, não este código."""
    try:
        return rest.ler(TABELA, sessao.token(),
                        colunas="id,quem,quando,acao,detalhe",
                        filtro=f"order=quando.desc&limit={int(quantos)}")
    except Exception:                                        # noqa: BLE001
        log.warning("lendo as ultimas linhas da auditoria na nuvem (%s)",
                    quantos, exc_info=True)
        return []
