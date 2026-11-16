# -*- coding: utf-8 -*-
"""Importa o OFX de cada conta no Mais Controle pela tela "Selecionar novo
OFX" (`#/transactions/<id>`), numa aba PRÓPRIA do robô (porteiro / Chrome do
app), uma aba só para todas, fechada e esquecida no fim.

**Roda na thread da vaga do Anexar** (`anx.submeter(..., dona=aba)`): o
`MCClient` e o Playwright dele só vivem lá. O caminho é o da ferramenta
`ferramentas/ofx-periodo/importar_todos.py`, provado em 23/10/2026: abre a
conta, espera o NOME dela na tela (o OFX nunca vai para a conta que estava
aberta antes), "Selecionar novo OFX" pelo seletor de arquivo e espera
"Arquivo OFX importado com sucesso". Só importa: nada é conciliado.

**Revisão de dinheiro (16/11/2026)**: (1) entre uma conta e outra a aba vai a
`about:blank`, para a página recarregar inteira — com o `goto` só trocando o
`#`, o aviso verde da conta anterior ainda na tela dava a seguinte por
importada, e a tela da anterior ainda montada podia receber o clique; (2) o
endereço tem de ter o `erp_id` e o NOME da conta aparece EXATO (`exact=True`)
— "CONTA X" não abre a porta na tela de "CONTA X 2"; (3) três desfechos:
`ok`, `falhou` (nada saiu: a conta não abriu, o seletor não veio) e
`incerto` (o arquivo foi entregue ao ERP e a confirmação não veio) — o
incerto nunca é reenviado.
"""
from __future__ import annotations

import re

from erp import hosts

OK, FALHOU, INCERTO = "ok", "falhou", "incerto"

TEXTO_BOTAO = "Selecionar novo OFX"
TEXTO_OK = "Arquivo OFX importado com sucesso"
TEMPO_TELA_MS = 40000
TEMPO_ESCOLHA_MS = 15000
_UUID = re.compile(r"[0-9A-Fa-f-]{8,64}")
SEM_UUID = "o ERP não deu o identificador desta conta"
SEM_CONFIRMACAO = "o ERP não confirmou a importação (sem 'importado com sucesso')"
PARADO = "parado pelo botão Parar antes desta conta"


def _primeira_linha(erro) -> str:
    texto = (str(erro or "").strip().splitlines() or [""])[0].strip()
    return texto[:160] or type(erro).__name__


def _importar_um(aba, erp_id: str, nome: str, arquivo) -> tuple[str, str]:
    aba.goto("about:blank")
    aba.goto(f"{hosts.ACESSAR}/#/transactions/{erp_id}", wait_until="domcontentloaded")
    try:
        aba.get_by_text(nome.strip(), exact=True).first.wait_for(timeout=TEMPO_TELA_MS)
        aba.get_by_text(TEXTO_BOTAO).first.wait_for(timeout=TEMPO_TELA_MS)
    except Exception as e:                                   # noqa: BLE001
        return FALHOU, f"a conta não abriu no ERP: {_primeira_linha(e)}"
    if erp_id not in (aba.url or ""):
        return FALHOU, "o ERP abriu outra tela no lugar desta conta"
    if aba.get_by_text(TEXTO_OK).count():
        return FALHOU, "a tela já mostrava um aviso de importação antes do envio"
    aba.wait_for_timeout(1000)
    try:
        with aba.expect_file_chooser(timeout=TEMPO_ESCOLHA_MS) as escolha:
            aba.get_by_text(TEXTO_BOTAO).first.click()
    except Exception as e:                                   # noqa: BLE001
        return FALHOU, f"o ERP não abriu a escolha do arquivo: {_primeira_linha(e)}"
    try:
        escolha.value.set_files(str(arquivo))
        aba.get_by_text(TEXTO_OK).first.wait_for(timeout=TEMPO_TELA_MS)
    except Exception:                                        # noqa: BLE001
        return INCERTO, SEM_CONFIRMACAO
    return OK, ""


def importar(mc, pedidos, *, log=print, parar=lambda: False) -> dict:
    """{erp_id: (OK | FALHOU | INCERTO, porquê)} para cada (erp_id, nome,
    arquivo). Erro de uma conta não derruba as outras."""
    saida: dict = {}
    validos = []
    for erp_id, nome, arquivo in pedidos:
        if _UUID.fullmatch(str(erp_id or "")):
            validos.append((erp_id, nome, arquivo))
        else:
            saida[erp_id] = (FALHOU, SEM_UUID)
    if not validos:
        return saida
    try:
        aba = mc._nova_aba_do_robo()
    except Exception as e:                                   # noqa: BLE001
        motivo = f"a aba do ERP não abriu: {_primeira_linha(e)}"
        log(f"  ERP: {motivo}")
        return {**saida, **{p[0]: (FALHOU, motivo) for p in validos}}
    try:
        for i, (erp_id, nome, arquivo) in enumerate(validos):
            if parar():
                for p in validos[i:]:
                    saida[p[0]] = (FALHOU, PARADO)
                break
            try:
                saida[erp_id] = _importar_um(aba, erp_id, nome, arquivo)
            except Exception as e:                           # noqa: BLE001
                # Não se sabe em que ponto parou: pode ter saído (incerto).
                saida[erp_id] = (INCERTO, f"a importação falhou no meio: {_primeira_linha(e)}")
            estado, motivo = saida[erp_id]
            log(f"  {nome}: " + {OK: "OFX importado", FALHOU: "não importado — ",
                                 INCERTO: "NÃO VERIFICADO — "}[estado] + motivo)
            aba.wait_for_timeout(1500)
    finally:
        try:
            aba.close()
        except Exception:                                    # noqa: BLE001
            pass
        mc._minhas.discard(aba)
    return saida
