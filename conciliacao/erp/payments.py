"""Leitura dos pagamentos em #/payable-installments (React + MUI DataGrid).

Estrutura confirmada na tela real:
- a grade e um MUI DataGrid: linhas em `[role=row]`, celulas em
  `[role=gridcell]` (NAO existe `[role=cell]` nesta versao);
- a linha de cabecalho tem `[role=columnheader]`; as linhas de dados sao as que
  contem gridcell;
- colunas: Vencimento, Status, Valor, Favorecido, Descricao e Categoria,
  N Doc, Condicao e Conta, Centro de Custo, Pago, Anexo;
- a grade leva varios segundos para preencher: quando o `[role=row]` do
  cabecalho ja existe, as linhas de dados ainda podem nao ter chegado. Ler cedo
  devolvia ZERO pagamentos sem erro nenhum.

ESTRATEGIA DE FILTRO (defesa em profundidade)
---------------------------------------------
1. Status: marcamos "Em aberto" no dropdown da tela.
2. Datas: usamos o seletor de periodo escondido atras do rotulo do mes
   ("julho 2026" -> "Alterar periodo de visualizacao" -> "Personalizado" ->
   data de inicio/fim -> "Confirmar periodo"). Isso pede ao ERP exatamente o
   intervalo desejado, e resolve tambem intervalos que cruzam a virada do mes.
3. Se o seletor de periodo falhar, a reserva e percorrer mes a mes.
4. Em qualquer um dos caminhos, `rules.py` REFILTRA por status e por data. Se a
   tela mudar de layout, a coleta fica mais lenta mas o resultado continua
   correto — nunca silenciosamente errado.
5. A cobertura e conferida contra o total que o proprio rodape da grade informa,
   entao uma coleta parcial vira erro em vez de painel incompleto.

Conferido com dados reais: coletar o mes inteiro e recortar no codigo deu o
mesmo total (R$ 177.046,30 em 73 lancamentos, 27 a 30/07) que usar o seletor de
periodo da tela — ou seja, o filtro do ERP nao esconde nada.

DEDUPLICACAO
------------
A chave e o `data-id` da linha, NUNCA o texto: o ERP tem lancamentos legitimos
identicos (duas tarifas PIX de R$ 0,90 no mesmo dia e conta), e deduplicar por
texto subtraia dinheiro do painel sem aviso.
"""

from __future__ import annotations

import time

from playwright.sync_api import Page

from ..models import ErpPayment, Periodo
from ..parsing import (
    normalize_name,
    parse_brl,
    parse_date_br,
    strip_condition_prefix,
)
from .browser import ErpError

#: Linha de dados da grade (a de cabecalho nao tem gridcell).
SEL_LINHA_DADOS = '[role="row"]:has([role="gridcell"])'

_JS_LER_GRADE = """() => {
  const linhas = [...document.querySelectorAll('[role=row]')];
  const cabecalhos = [...document.querySelectorAll('[role=columnheader]')].map((h, i) => ({
    i,
    campo: h.getAttribute('data-field'),
    texto: (h.innerText || '').replace(/\\s+/g, ' ').trim(),
  }));
  const dados = linhas
    .filter(r => r.querySelector('[role=gridcell]'))
    .map(r => ({
      // `data-id` e o identificador do registro no MUI DataGrid. Sem ele,
      // deduplicar pelo texto apagaria lancamentos legitimamente iguais
      // (ex.: duas tarifas PIX de R$ 0,90 no mesmo dia e conta).
      id: r.getAttribute('data-id'),
      celulas: [...r.querySelectorAll('[role=gridcell]')].map((c, i) => ({
        i,
        campo: c.getAttribute('data-field'),
        texto: (c.innerText || '').replace(/\\n+/g, ' ').replace(/\\s+/g, ' ').trim(),
      })),
    }));
  return {cabecalhos, dados};
}"""

_JS_AGREGADO = """() => {
  const texto = document.body.innerText || '';
  const achado = texto.match(/Em aberto:?\\s*(R\\$\\s*-?\\s*[\\d.]+,\\d{2})/i);
  return achado ? achado[1] : null;
}"""

#: Sinonimos aceitos para cada campo, em nome normalizado.
_ALVOS = {
    "vencimento": ("VENCIMENTO", "DATA DE VENCIMENTO", "VENCIMENTO EM"),
    "status": ("STATUS", "SITUACAO", "SITUACAO DO PAGAMENTO"),
    "valor": ("VALOR", "VALOR DA PARCELA", "VALOR PARCELA"),
    "favorecido": ("FAVORECIDO", "FORNECEDOR", "BENEFICIARIO"),
    "conta": ("CONDICAO E CONTA", "CONTA BANCARIA", "CONDICAO CONTA", "CONTA"),
}

#: O mes pode ter mais de mil parcelas; com 100 por pagina isso cabe folgado.
#: Antes o limite era 60 e, com 10 linhas por pagina, a coleta parava no meio do
#: mes SEM ERRO — perdendo justamente os vencimentos do fim do mes.
_MAX_PAGINAS = 400

#: Tamanhos oferecidos pelo seletor do MUI, do maior para o menor.
_TAMANHOS_DESEJADOS = (100, 50, 25)

#: Nomes dos meses como o ERP escreve no navegador de periodo ("julho 2026").
_MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)

#: Le o mes/ano exibido no navegador de periodo da tela.
_JS_MES_ATUAL = """() => {
  const texto = document.body.innerText || '';
  const m = texto.match(
    /(janeiro|fevereiro|mar\\u00e7o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\\s+(\\d{4})/i);
  return m ? {mes: m[1].toLowerCase(), ano: parseInt(m[2], 10)} : null;
}"""

#: Le "1–10 de 1234" do rodape da paginacao para saber o total de linhas.
_JS_TOTAL_GRADE = """() => {
  const alvos = [...document.querySelectorAll(
    '.MuiTablePagination-displayedRows, [class*="MuiTablePagination-displayedRows"]')];
  for (const el of alvos) {
    const m = (el.innerText || '').match(/de\\s+([\\d.,]+)/i);
    if (m) return parseInt(m[1].replace(/[.,]/g, ''), 10);
  }
  return null;
}"""


def _mapear_colunas(cabecalhos: list[dict]) -> tuple[dict[str, int], dict[str, str]]:
    """Casa o cabecalho da grade com os campos que precisamos.

    Devolve (indices, campos): `indices` mapeia alvo -> posicao da celula, e
    `campos` mapeia alvo -> data-field do MUI (quando a grade expoe esse
    atributo, que e a forma mais estavel de identificar a coluna).
    """
    indices: dict[str, int] = {}
    campos: dict[str, str] = {}
    normalizados = [(h, normalize_name(h.get("texto"))) for h in cabecalhos]

    for alvo, sinonimos in _ALVOS.items():
        achado = None
        for header, nome in normalizados:  # igualdade primeiro
            if nome in sinonimos:
                achado = header
                break
        if achado is None:  # depois por continencia ("Conta bancaria (origem)")
            for header, nome in normalizados:
                if nome and any(s in nome for s in sinonimos):
                    achado = header
                    break
        if achado is not None:
            indices[alvo] = achado["i"]
            if achado.get("campo"):
                campos[alvo] = achado["campo"]

    faltando = [c for c in ("vencimento", "valor", "conta") if c not in indices]
    if faltando:
        raise ErpError(
            f"nao encontrei as colunas {faltando} na grade de pagamentos.\n"
            f"Cabecalho lido: {[h.get('texto') for h in cabecalhos]}"
        )
    return indices, campos


def _valor_da_celula(
    celulas: list[dict],
    alvo: str,
    indices: dict[str, int],
    campos: dict[str, str],
) -> str:
    """Le uma celula pelo data-field; se nao houver, cai para a posicao."""
    campo = campos.get(alvo)
    if campo:
        for c in celulas:
            if c.get("campo") == campo:
                return c.get("texto") or ""
    posicao = indices.get(alvo)
    if posicao is not None and posicao < len(celulas):
        return celulas[posicao].get("texto") or ""
    return ""


def definir_periodo_na_tela(pagina: Page, periodo: Periodo, log=print) -> bool:
    """Aplica o intervalo exato no seletor de periodo da propria tela.

    O caminho e: clicar no rotulo do mes ("julho 2026") -> abre o popover
    "Alterar periodo de visualizacao" -> marcar "Personalizado" -> preencher
    "Data de inicio" e "Data de fim" -> "Confirmar periodo".

    Vantagem sobre navegar mes a mes: o ERP devolve so o intervalo pedido, o
    volume cai muito e intervalos que cruzam a virada do mes funcionam de uma
    vez. Devolve False se nao conseguir, e a coleta cai para a navegacao por mes.
    """
    atual = _mes_exibido(pagina)
    if atual is None:
        return False
    nome_mes = _MESES[atual[1] - 1]

    try:
        # 1. Abrir o popover pelo rotulo do mes.
        #    Tem que ser o <button> — existe um <div> envolvendo ele com o mesmo
        #    texto, e clicar no div nao abre nada.
        gatilho = pagina.locator(f'button:has-text("{nome_mes} {atual[0]}")').first
        if gatilho.count() == 0 or not gatilho.is_visible(timeout=4000):
            log("  nao achei o botao do mes para abrir o seletor de periodo")
            return False
        gatilho.click()
        pagina.wait_for_timeout(1200)

        # 2. Marcar "Personalizado" (radio com value="custom"). Os campos de
        #    data so aparecem depois disso.
        personalizado = pagina.locator('input[type="radio"][value="custom"]').first
        if personalizado.count() == 0:
            log("  nao achei a opcao 'Personalizado' no seletor de periodo")
            pagina.keyboard.press("Escape")
            return False
        personalizado.check(timeout=4000)
        pagina.wait_for_timeout(1200)

        # 3. Preencher as duas datas (formato brasileiro).
        if not _preencher_data(pagina, ("Data de início", "Data de inicio"), periodo.inicio):
            pagina.keyboard.press("Escape")
            return False
        if not _preencher_data(pagina, ("Data de fim",), periodo.fim):
            pagina.keyboard.press("Escape")
            return False

        # 4. Confirmar.
        confirmar = pagina.locator(
            'button:has-text("Confirmar período"), button:has-text("Confirmar periodo"), '
            'button:has-text("Confirmar")'
        ).first
        if confirmar.count() == 0:
            log("  nao achei o botao 'Confirmar periodo'")
            pagina.keyboard.press("Escape")
            return False
        confirmar.click()
        pagina.wait_for_timeout(2500)
        _esperar_grade(pagina)

        log(f"  periodo aplicado na tela: {periodo.descrever()}")
        return True

    except Exception as exc:
        log(f"  nao consegui usar o seletor de periodo da tela: {exc}")
        try:
            pagina.keyboard.press("Escape")
        except Exception:
            pass
        return False


def _preencher_data(pagina: Page, rotulos: tuple[str, ...], valor) -> bool:
    """Preenche um campo de data do MUI, tentando rotulo e depois posicao."""
    texto = f"{valor:%d/%m/%Y}"

    for rotulo in rotulos:
        try:
            campo = pagina.get_by_label(rotulo, exact=False).first
            if campo.count() and campo.is_visible(timeout=1500):
                campo.click()
                campo.press("Control+a")
                campo.type(texto, delay=40)
                pagina.wait_for_timeout(400)
                return True
        except Exception:
            continue

    # Reserva: os inputs de data visiveis dentro do popover, na ordem.
    try:
        campos = pagina.locator(
            'input[placeholder*="/"], .MuiPickersTextField-root input, '
            'input[type="text"][value*="/"]'
        )
        indice = 0 if "início" in rotulos[0] or "inicio" in rotulos[0] else 1
        if campos.count() > indice:
            campo = campos.nth(indice)
            campo.click()
            campo.press("Control+a")
            campo.type(texto, delay=40)
            pagina.wait_for_timeout(400)
            return True
    except Exception:
        pass
    return False


def meses_do_periodo(periodo: Periodo) -> list[tuple[int, int]]:
    """Lista (ano, mes) que o periodo cobre, em ordem.

    Numa segunda dia 1o, sabado e domingo caem no mes anterior — sem isso a
    coleta perderia o fim de semana inteiro.
    """
    meses: list[tuple[int, int]] = []
    ano, mes = periodo.inicio.year, periodo.inicio.month
    while (ano, mes) <= (periodo.fim.year, periodo.fim.month):
        meses.append((ano, mes))
        mes += 1
        if mes > 12:
            ano, mes = ano + 1, 1
    return meses


def _mes_exibido(pagina: Page) -> tuple[int, int] | None:
    dados = pagina.evaluate(_JS_MES_ATUAL)
    if not dados:
        return None
    try:
        return int(dados["ano"]), _MESES.index(dados["mes"]) + 1
    except (ValueError, KeyError):
        return None


def navegar_para_mes(pagina: Page, ano: int, mes: int, log=print) -> bool:
    """Move o navegador de periodo da tela ate o mes pedido."""
    atual = _mes_exibido(pagina)
    if atual is None:
        log("  nao localizei o navegador de mes na tela")
        return False
    if atual == (ano, mes):
        return True

    # Distancia em meses; o sinal diz se clicamos em anterior ou proximo.
    distancia = (ano - atual[0]) * 12 + (mes - atual[1])
    seletor = (
        'button[aria-label*="próximo" i], button[aria-label*="next" i]'
        if distancia > 0
        else 'button[aria-label*="anterior" i], button[aria-label*="previous" i]'
    )

    for _ in range(abs(distancia)):
        try:
            botao = pagina.locator(seletor).first
            if botao.count() == 0 or not botao.is_visible(timeout=2000):
                # Reserva: os dois botoes ao redor do rotulo do mes.
                botoes = pagina.locator(
                    'button:near(:text("' + _MESES[mes - 1] + '"), 120)'
                )
                if botoes.count() < 2:
                    log("  nao achei os botoes de mudar o mes")
                    return False
                botao = botoes.last if distancia > 0 else botoes.first
            botao.click()
            pagina.wait_for_timeout(1800)
        except Exception as exc:
            log(f"  falha ao mudar o mes: {exc}")
            return False

    _esperar_grade(pagina)
    chegou = _mes_exibido(pagina)
    if chegou != (ano, mes):
        log(f"  esperava {_MESES[mes - 1]} {ano} e a tela mostra {chegou}")
        return False
    log(f"  mes na tela: {_MESES[mes - 1]} {ano}")
    return True


def filtrar_em_aberto(pagina: Page, log=print) -> bool:
    """Marca "Em aberto" no dropdown de status da tela.

    Otimizacao, nao correcao: se falhar, a coleta segue com o mes inteiro e o
    filtro de `rules.py` garante o mesmo resultado final.
    """
    antes = pagina.locator(SEL_LINHA_DADOS).count()
    try:
        gatilho = pagina.locator(
            'div[role="button"]:has-text("Todos pagamentos"), '
            'button:has-text("Todos pagamentos"), '
            '[role="combobox"]:has-text("Todos pagamentos")'
        ).first
        if not gatilho.is_visible(timeout=4000):
            return False
        gatilho.click()
        pagina.wait_for_timeout(700)

        opcao = pagina.locator(
            'li[role="option"]:has-text("Em aberto"), '
            'li:has-text("Em aberto"), [role="option"]:has-text("Em aberto")'
        ).first
        if opcao.count() == 0:
            pagina.keyboard.press("Escape")
            return False
        opcao.click(timeout=4000)
        pagina.wait_for_timeout(2000)
        _esperar_grade(pagina)

        depois = pagina.locator(SEL_LINHA_DADOS).count()
        log(f"  filtro 'Em aberto' aplicado na tela ({antes} -> {depois} linhas visiveis)")
        return True
    except Exception:
        try:
            pagina.keyboard.press("Escape")
        except Exception:
            pass
        return False


def _esperar_grade(pagina: Page, timeout_s: float = 60.0) -> int:
    """Espera as linhas de DADOS aparecerem (nao apenas o cabecalho)."""
    limite = time.monotonic() + timeout_s
    while time.monotonic() < limite:
        quantas = pagina.locator(SEL_LINHA_DADOS).count()
        if quantas > 0:
            pagina.wait_for_timeout(1200)  # deixa a pagina terminar de pintar
            return pagina.locator(SEL_LINHA_DADOS).count()
        pagina.wait_for_timeout(700)
    return 0


def _aumentar_linhas_por_pagina(pagina: Page) -> int:
    """Aumenta "Linhas por pagina" para o maior valor que o seletor aceitar.

    Devolve o tamanho efetivo (0 se nao conseguiu mexer). Confere olhando a
    quantidade de linhas depois — antes eu assumia sucesso e a coleta seguia com
    10 por pagina, o que estourava o limite de paginas no meio do mes.
    """
    antes = pagina.locator(SEL_LINHA_DADOS).count()

    for quantidade in _TAMANHOS_DESEJADOS:
        try:
            seletor = pagina.locator(
                '.MuiTablePagination-select, [class*="MuiTablePagination-select"]'
            ).first
            if not seletor.is_visible(timeout=3000):
                return 0
            seletor.click()
            opcao = pagina.locator(
                f'li[role="option"]:text-is("{quantidade}"), li[data-value="{quantidade}"]'
            ).first
            if opcao.count() == 0:
                pagina.keyboard.press("Escape")
                continue
            opcao.click(timeout=3000)
            pagina.wait_for_timeout(1800)
            depois = _esperar_grade(pagina)
            if depois > antes:
                return depois
        except Exception:
            try:
                pagina.keyboard.press("Escape")
            except Exception:
                pass
    return 0


def _proxima_pagina(pagina: Page) -> bool:
    """Avanca uma pagina da grade. False quando nao ha proxima."""
    try:
        botoes = pagina.locator(".MuiTablePagination-actions button")
        if botoes.count() == 0:
            return False
        botao = botoes.last  # o ultimo e "proxima pagina"
        if botao.is_disabled():
            return False
        botao.click()
        pagina.wait_for_timeout(1500)
        return True
    except Exception:
        return False


def _coletar_mes_exibido(pagina: Page, log=print) -> list[ErpPayment]:
    """Varre todas as paginas da grade do mes que esta na tela."""
    pagamentos: list[ErpPayment] = []
    vistos: set[tuple] = set()
    indices: dict[str, int] = {}
    campos: dict[str, str] = {}
    paginas_lidas = 0

    total_esperado = pagina.evaluate(_JS_TOTAL_GRADE)

    for pagina_atual in range(1, _MAX_PAGINAS + 1):
        paginas_lidas += 1
        grade = pagina.evaluate(_JS_LER_GRADE) or {}
        cabecalhos, dados = grade.get("cabecalhos", []), grade.get("dados", [])

        if not indices:
            if not cabecalhos:
                raise ErpError("cabecalho da grade de pagamentos nao encontrado")
            indices, campos = _mapear_colunas(cabecalhos)

        for linha in dados:
            celulas = linha.get("celulas") or []
            assinatura = tuple(c.get("texto") or "" for c in celulas)

            # Deduplicar SO pelo id do registro. Duas linhas com texto igual
            # podem ser dois lancamentos de verdade; descartar uma delas
            # subtrairia dinheiro do painel sem aviso.
            identidade = linha.get("id")
            if identidade is None:
                identidade = ("sem-id", pagina_atual, len(pagamentos))
            if identidade in vistos:
                continue
            vistos.add(identidade)

            def campo(alvo: str) -> str:
                return _valor_da_celula(celulas, alvo, indices, campos)

            pagamentos.append(
                ErpPayment(
                    due_date=parse_date_br(campo("vencimento")),
                    status=campo("status"),
                    amount=parse_brl(campo("valor")),
                    payee=campo("favorecido"),
                    account_label=strip_condition_prefix(campo("conta")),
                    raw={"id": linha.get("id"), "celulas": list(assinatura)},
                )
            )

        if not _proxima_pagina(pagina):
            break
        _esperar_grade(pagina)

    # Cobertura: se o ERP diz que ha N parcelas e lemos menos, PARAMOS no meio —
    # e faltar exatamente os vencimentos do fim do mes e o erro mais caro
    # possivel aqui. Falha alto em vez de gerar painel incompleto.
    if total_esperado and len(pagamentos) < total_esperado:
        raise ErpError(
            f"coleta incompleta: o ERP indica {total_esperado} parcela(s), "
            f"mas li apenas {len(pagamentos)} em {paginas_lidas} pagina(s).\n"
            "Isso faria o painel perder pagamentos do periodo."
        )

    log(f"  {len(pagamentos)} linha(s) neste mes ({paginas_lidas} pagina(s))")
    return pagamentos


def motivo_da_grade_vazia(total_rodape, tem_texto_vazio: bool) -> str:
    """Explica uma grade sem linhas, separando as tres causas possiveis.

    O rodape e a chave: ele soma o mes inteiro, independente do que a grade
    lista. Total zerado significa mes sem lancamentos; total com valor e
    grade vazia significa que a listagem foi barrada — quase sempre a sessao
    do navegador nao estava valida, e o ERP respondeu sem dados.

    Funcao pura para poder ser testada: o caso real so aparece com a sessao
    quebrada, que e dificil de reproduzir de proposito.
    """
    if total_rodape:
        return (
            "a grade de pagamentos veio vazia, mas o rodape da tela soma "
            f"{total_rodape} no mes.\n"
            "Ou seja: ha lancamentos, o ERP e que nao os listou.\n"
            "A causa comum e a sessao do navegador nao estar valida — entre "
            "na janela do Chrome e rode de novo.\n"
            "Se voce estava logado, veja o screenshot: pode haver filtro "
            "aplicado na tela."
        )
    if tem_texto_vazio:
        return (
            "a grade de pagamentos esta vazia e o rodape tambem esta zerado: "
            "o mes nao tem lancamentos.\n"
            "Se voce esperava lancamentos, confira o mes selecionado na tela."
        )
    return (
        "a grade de pagamentos nao carregou nenhuma linha.\n"
        "Nao achei nem os totais do rodape, entao a tela pode nao ter aberto "
        "por completo ou o layout do ERP mudou (veja o screenshot)."
    )


def _diagnostico_grade_vazia(pagina: Page) -> str:
    try:
        total = pagina.evaluate(_JS_AGREGADO)
    except Exception:
        total = None
    try:
        vazio = pagina.locator("text=Nenhum registro encontrado").count() > 0
    except Exception:
        vazio = False
    return motivo_da_grade_vazia(total, vazio)


def coletar_pagamentos(
    pagina: Page,
    config,
    periodo: Periodo,
    log=print,
) -> tuple[list[ErpPayment], object]:
    """Coleta os pagamentos de todos os meses que o periodo cobre.

    A tela nao tem filtro de intervalo de datas — so navegacao por mes. Por isso
    percorremos mes a mes e o recorte fino por data fica em `rules.py`.
    """
    if _esperar_grade(pagina) == 0:
        raise ErpError(_diagnostico_grade_vazia(pagina))

    # O agregado do rodape precisa ser lido ANTES do filtro, senao passa a
    # refletir so o subconjunto filtrado e a conferencia cruzada perde sentido.
    agregado = parse_brl(pagina.evaluate(_JS_AGREGADO))

    if not filtrar_em_aberto(pagina, log=log):
        log("  nao consegui usar o filtro de status da tela")

    # Caminho preferido: pedir o intervalo exato ao ERP.
    periodo_na_tela = definir_periodo_na_tela(pagina, periodo, log=log)

    _aumentar_linhas_por_pagina(pagina)
    todos: list[ErpPayment] = []

    if periodo_na_tela:
        todos.extend(_coletar_mes_exibido(pagina, log=log))
    else:
        # Reserva: sem o seletor de periodo, percorremos mes a mes.
        log("  vou percorrer mes a mes (reserva)")
        alvos = meses_do_periodo(periodo)
        for ano, mes in alvos:
            if len(alvos) > 1 or _mes_exibido(pagina) != (ano, mes):
                if not navegar_para_mes(pagina, ano, mes, log=log):
                    raise ErpError(
                        f"nao consegui abrir {_MESES[mes - 1]} {ano} na tela de pagamentos.\n"
                        f"O periodo pedido ({periodo.descrever()}) precisa desse mes."
                    )
                _aumentar_linhas_por_pagina(pagina)
            todos.extend(_coletar_mes_exibido(pagina, log=log))

    # Dedup entre meses (a mesma parcela nao deveria aparecer duas vezes, mas o
    # ERP pode repetir na virada dependendo do filtro aplicado).
    unicos: list[ErpPayment] = []
    vistos: set[tuple] = set()
    for p in todos:
        # Mesma razao da dedup por pagina: a chave e o id do registro, nunca o
        # texto — lancamentos identicos podem ser dois pagamentos distintos.
        chave = p.raw.get("id") or id(p)
        if chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(p)

    # Confere se o filtro da tela realmente pegou. Nao e erro (o recorte fino
    # acontece em `rules.py`), mas achar que filtrou sem ter filtrado esconde
    # problema — entao registramos o que de fato veio.
    datas = [p.due_date for p in unicos if p.due_date]
    if datas:
        fora = sum(1 for d in datas if not periodo.contem(d))
        log(
            f"  {len(unicos)} linha(s) coletada(s), vencimentos de "
            f"{min(datas):%d/%m} a {max(datas):%d/%m}"
        )
        if periodo_na_tela and fora:
            log(
                f"  atencao: {fora} linha(s) fora do periodo pedido — o filtro da "
                "tela nao restringiu tudo; o recorte por data no codigo cobre isso"
            )

    return unicos, agregado
