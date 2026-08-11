"""Coleta completa: ERP -> Snapshot em disco.

A coleta usa DOIS caminhos diferentes, por motivo pratico:

  saldos      -> API REST (`api.py`). Nao precisa de navegador.
  pagamentos  -> raspagem da grade (`payments.py`), que ainda depende da tela.

Ate 10/08/2026 os dois vinham da tela. A leitura de saldos migrou para a API
quando o redesenho da tela de contas quebrou a raspagem pela segunda vez.
A grade de pagamentos nao foi investigada ainda — quando for, o navegador sai
de cena por completo.
"""

from __future__ import annotations

from datetime import date, datetime

from ..config import Config
from ..models import Periodo, Snapshot, sugerir_periodo
from .accounts import coletar_contas
from .auth import entrar, garantir_login
from .browser import abrir_erp, aguardar_sistema, ir_para, salvar_screenshot
from .payments import coletar_pagamentos

#: Linhas da grade de pagamentos (MUI DataGrid).
SEL_LINHAS_PAGAMENTOS = '[role="row"]'


def coletar(
    config: Config,
    *,
    data_referencia: date | None = None,
    periodo: Periodo | None = None,
    visivel: bool = True,
    log=print,
) -> Snapshot:
    """Le saldos e pagamentos e devolve o snapshot do periodo."""
    if periodo is None:
        periodo = (
            Periodo.de_um_dia(data_referencia)
            if data_referencia
            else sugerir_periodo(date.today())
        )
    # A data de referencia do painel e sempre o fim do periodo.
    referencia = periodo.fim
    log(f"Periodo: {periodo.descrever()}")

    # Saldos primeiro, de proposito: sao rapidos e nao abrem janela. Se a
    # credencial estiver errada, o erro aparece aqui — antes de o navegador
    # subir e o usuario ficar olhando para uma janela que vai morrer.
    log("Lendo saldos das contas (API do Mais Controle)...")
    contas = coletar_contas(config, log=log)
    log(f"  {len(contas)} conta(s) lida(s)")

    with abrir_erp(config, visivel=visivel) as pagina:
        try:
            # Entrar ANTES de pedir tela interna: navegar direto para uma rota
            # sem sessao faz o ERP mostrar "sem permissao".
            log("Entrando no Mais Controle...")
            entrar(pagina, config, visivel=visivel, log=log)

            log("Abrindo pagamentos...")
            ir_para(pagina, config, config.erp["rota_pagamentos"])
            garantir_login(
                pagina,
                config,
                seletor_sucesso=SEL_LINHAS_PAGAMENTOS,
                visivel=visivel,
                log=log,
            )
            pagamentos, agregado = _ler_pagamentos(pagina, config, periodo, log=log)

        except Exception:
            caminho = salvar_screenshot(pagina, config, f"falha-{referencia:%Y-%m-%d}")
            log(f"Screenshot do erro: {caminho}")
            raise

    return _montar_snapshot(referencia, contas, pagamentos, agregado, periodo)


def coletar_com_pagina(
    pagina,
    config: Config,
    *,
    data_referencia: date | None = None,
    periodo: Periodo | None = None,
    log=print,
) -> Snapshot:
    """Mesma coleta, sobre uma pagina JA LOGADA — a do app.

    O ERP aceita uma sessao por usuario: se a aba abrisse o proprio navegador,
    derrubaria a sessao do Anexar, e vice-versa. Aqui a sessao e emprestada, e
    por isso nao ha `entrar()` nem `garantir_login()` — quem cuida do login e o
    dono da pagina. Fora isso, e a mesma coleta de `coletar()`.
    """
    if periodo is None:
        periodo = (
            Periodo.de_um_dia(data_referencia)
            if data_referencia
            else sugerir_periodo(date.today())
        )
    referencia = periodo.fim
    log(f"Periodo: {periodo.descrever()}")

    log("Lendo saldos das contas (API do Mais Controle)...")
    contas = coletar_contas(config, log=log)
    log(f"  {len(contas)} conta(s) lida(s)")

    try:
        log("Abrindo pagamentos...")
        ir_para(pagina, config, config.erp["rota_pagamentos"])
        pagamentos, agregado = _ler_pagamentos(pagina, config, periodo, log=log)
    except Exception:
        caminho = salvar_screenshot(pagina, config, f"falha-{referencia:%Y-%m-%d}")
        log(f"Screenshot do erro: {caminho}")
        raise

    return _montar_snapshot(referencia, contas, pagamentos, agregado, periodo)


def _ler_pagamentos(pagina, config: Config, periodo: Periodo, *, log=print):
    aguardar_sistema(pagina, SEL_LINHAS_PAGAMENTOS)
    log("Lendo a grade de pagamentos (todas as paginas do mes)...")
    pagamentos, agregado = coletar_pagamentos(pagina, config, periodo, log=log)
    log(f"  {len(pagamentos)} linha(s) lida(s) no mes")
    return pagamentos, agregado


def _montar_snapshot(referencia, contas, pagamentos, agregado, periodo) -> Snapshot:
    return Snapshot(
        reference_date=referencia,
        collected_at=datetime.now().isoformat(timespec="seconds"),
        accounts=contas,
        payments=pagamentos,
        page_aggregate_open=agregado,
        periodo=periodo,
    )


def testar_login(config: Config, log=print) -> bool:
    """Confere os DOIS acessos que a coleta usa, sem coletar nada.

    Serve para validar a senha recem-guardada: se a API responde e a grade de
    pagamentos carrega, a conciliacao do dia vai passar.
    """
    log("1/2 — API de saldos...")
    contas = coletar_contas(config, log=log)
    log(f"  OK: {len(contas)} conta(s) ativa(s) com saldo.")

    log("2/2 — navegador (grade de pagamentos)...")
    with abrir_erp(config, visivel=True) as pagina:
        entrar(pagina, config, visivel=True, log=log)
        ir_para(pagina, config, config.erp["rota_pagamentos"])
        aguardar_sistema(pagina, SEL_LINHAS_PAGAMENTOS)
        linhas = pagina.locator(SEL_LINHAS_PAGAMENTOS).count()
        log(f"  OK: a grade de pagamentos carregou com {linhas} linha(s).")
    return True
