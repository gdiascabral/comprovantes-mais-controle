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

import util

#: O diagnostico do modulo. Quase toda funcao daqui recebe um `log` PROPRIO (o
#: recado que aparece no Registro da aba) e o parametro SOMBREIA este nome la
#: dentro; nessas, o diagnostico sai por `_diag`, que e este mesmo logger com
#: outro nome. Os dois convivem de proposito: o Registro diz o que a coleta
#: esta fazendo, o arquivo guarda o traceback de por que um passo nao deu.
log = util.log(__name__)
_diag = log

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


def _conferir_mapeamento(dados: list[dict], indices: dict[str, int],
                         campos: dict[str, str]) -> None:
    """Confere que as colunas mapeadas contem mesmo o que prometem.

    `_mapear_colunas` cai para a POSICAO quando a grade nao expoe `data-field`,
    e posicao e a coisa mais fragil aqui: basta o ERP inserir uma coluna para
    "valor" passar a apontar para o favorecido. O sintoma seria um painel de
    numeros errados — que ninguem percebe olhando. Um punhado de linhas basta
    para desmentir isso: se quase nenhum "valor" parseia como dinheiro, o
    mapeamento esta errado.
    """
    amostra = [d.get("celulas") or [] for d in dados[:10]]
    if len(amostra) < 3:
        return                       # pouca linha para concluir qualquer coisa

    for alvo, converte in (("valor", parse_brl), ("vencimento", parse_date_br)):
        if campos.get(alvo):
            continue                 # veio por data-field: e confiavel
        lidos = [_valor_da_celula(c, alvo, indices, campos) for c in amostra]
        preenchidos = [x for x in lidos if (x or "").strip()]
        if not preenchidos:
            continue
        bons = [x for x in preenchidos if converte(x) is not None]
        if len(bons) * 2 < len(preenchidos):    # menos da metade converteu
            raise ErpError(
                f"a coluna '{alvo}' da grade nao parece ser '{alvo}': de "
                f"{len(preenchidos)} celulas lidas, so {len(bons)} fazem "
                f"sentido (ex.: {preenchidos[:3]}).\n"
                "O layout da tela provavelmente mudou. Parei aqui em vez de "
                "gerar um painel com numeros trocados."
            )


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
            _diag.warning("apertando Esc para fechar o seletor de periodo; ele "
                          "fica aberto por cima da grade", exc_info=True)
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
            # Os rotulos sao variantes do MESMO campo ("Data de inicio" com e
            # sem acento): o que nao existe e "ainda nao", nao falha. Quem
            # avisa e a reserva por posicao, logo abaixo, se ela tambem cair.
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
        log.warning("preenchendo o campo de data pela posicao no popover "
                    "(reserva do rotulo %r)", rotulos[0], exc_info=True)
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


def _escolher_status(pagina: Page, rotulo: str) -> bool:
    """Clica uma opcao do dropdown de status. O menu ja deve estar aberto."""
    opcao = pagina.locator(
        f'li[role="option"]:has-text("{rotulo}"), '
        f'li:has-text("{rotulo}"), [role="option"]:has-text("{rotulo}")'
    ).first
    if opcao.count() == 0:
        return False
    opcao.click(timeout=4000)
    pagina.wait_for_timeout(600)
    return True


def _contar_vencidos(pagina: Page) -> int:
    """Quantas linhas visiveis estao com status vencido.

    Existe para tornar VISIVEL a suposicao que o filtro passou a fazer: que
    "Em aberto" traz os vencidos junto. Se um dia parar de trazer, o numero
    zera e o log diz isso -- em vez de o titulo atrasado sumir do painel de
    segunda sem deixar rastro.
    """
    try:
        texto = normalize_name(pagina.locator("body").inner_text(timeout=2500))
    except Exception:
        # Zero aqui e indistinguivel de "nenhuma linha vencida", que e
        # justamente o numero que esta funcao existe para tornar visivel.
        log.warning("lendo a tela para contar as linhas vencidas", exc_info=True)
        return 0
    return texto.count("VENCIDO")


def filtrar_em_aberto(pagina: Page, log=print) -> bool:
    """Marca "Em aberto" no dropdown de status da tela.

    Otimizacao, nao correcao: se falhar, a coleta segue com o mes inteiro e o
    filtro de `rules.py` garante o mesmo resultado final.

    SO "Em aberto", e nao mais "Em aberto" + "Vencido". O dropdown do Mais
    Controle e de escolha UNICA: o segundo clique trocava em vez de somar, a
    checagem via isso, desfazia tudo e caia para "Todos pagamentos" -- entao o
    filtro nunca pegava e as 15 paginas do mes eram varridas a toa. Confirmado
    com o dono do sistema em 18/08/2026: "Em aberto" na tela ja devolve os
    vencidos junto.

    Como isso contraria o que este arquivo assumia, o log passa a CONTAR
    quantos vencidos vieram. Se um dia o ERP mudar e o filtro comecar a
    esconde-los, aparece na hora, em vez de o painel de segunda perder o
    titulo de sabado sem ninguem notar. E `rules.STATUS_A_PAGAR` continua
    aceitando os dois: a rede de seguranca nao muda.
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

        if not _escolher_status(pagina, "Em aberto"):
            pagina.keyboard.press("Escape")
            return False
        pagina.keyboard.press("Escape")
        pagina.wait_for_timeout(1400)
        _esperar_grade(pagina)

        # Confere no proprio gatilho o que ficou selecionado: filtro que nao
        # pegou e pior que filtro nenhum, porque a contagem some sem aviso.
        try:
            selecionado = (gatilho.inner_text(timeout=2000) or "")
        except Exception:
            # Vazio cai no ramo de baixo, que acusa "o filtro nao ficou
            # selecionado" — mas o que houve foi nao conseguir LER o gatilho.
            _diag.warning("lendo o gatilho do dropdown para conferir o filtro "
                          "de status", exc_info=True)
            selecionado = ""
        if "EM ABERTO" not in normalize_name(selecionado):
            log("  o filtro 'Em aberto' nao ficou selecionado — seguindo com "
                "o mes inteiro")
            _desfazer_filtro_status(pagina)
            return False

        depois = pagina.locator(SEL_LINHA_DADOS).count()
        vencidos = _contar_vencidos(pagina)
        log(f"  filtro 'Em aberto' aplicado na tela "
            f"({antes} -> {depois} linhas visiveis, {vencidos} vencida(s))")
        if depois and not vencidos:
            # Nao e erro: pode nao haver vencido nenhum hoje. Mas e a unica
            # pista de que o filtro talvez esteja escondendo-os, e o custo de
            # descobrir isso tarde e um titulo atrasado fora do painel.
            log("  (nenhuma linha vencida no filtro — se voce esperava alguma, "
                "confira na tela do ERP)")
        return True
    except Exception:
        _diag.warning("aplicando o filtro 'Em aberto' no dropdown de status; a "
                      "coleta segue com o mes inteiro", exc_info=True)
        try:
            pagina.keyboard.press("Escape")
        except Exception:
            _diag.warning("apertando Esc para fechar o dropdown de status",
                          exc_info=True)
        _desfazer_filtro_status(pagina)
        return False


def _desfazer_filtro_status(pagina: Page) -> None:
    """Volta o dropdown para "Todos pagamentos" (melhor esforco)."""
    try:
        gatilho = pagina.locator(
            'div[role="button"], button, [role="combobox"]'
        ).filter(has_text="Em aberto").first
        if gatilho.count() == 0 or not gatilho.is_visible(timeout=2000):
            return
        gatilho.click()
        pagina.wait_for_timeout(600)
        _escolher_status(pagina, "Todos pagamentos")
        pagina.keyboard.press("Escape")
        pagina.wait_for_timeout(1200)
        _esperar_grade(pagina)
    except Exception:
        log.warning("devolvendo o dropdown de status para 'Todos pagamentos'; "
                    "a tela fica com o filtro pela metade", exc_info=True)


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
            # Tamanho que a grade nao aceita e "o proximo", nao falha: o laco
            # tenta 100, 50 e 25, e so ter esgotado os tres e que importa.
            try:
                pagina.keyboard.press("Escape")
            except Exception:
                pass                     # idem: a proxima volta reabre o menu

    # Esgotados os tamanhos. O retorno 0 nao e olhado por ninguem, e a coleta
    # segue com 10 por pagina — mais paginas para varrer, e o `_MAX_PAGINAS`
    # mais perto. Sem `exc_info`: aqui nao ha excecao viva, so o desfecho.
    log.warning("nao consegui aumentar as linhas por pagina (tentei %s); a "
                "grade segue com o tamanho padrao",
                ", ".join(str(q) for q in _TAMANHOS_DESEJADOS))
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
        # False aqui e lido como "acabaram as paginas" e encerra a varredura.
        # Quem impede a coleta parcial de virar painel e a conferencia contra o
        # total do rodape, mais adiante — mas o motivo se perdia aqui.
        log.warning("avancando para a proxima pagina da grade", exc_info=True)
        return False


def _coletar_mes_exibido(pagina: Page, log=print,
                         periodo: Periodo | None = None) -> list[ErpPayment]:
    """Varre todas as paginas da grade do mes que esta na tela."""
    pagamentos: list[ErpPayment] = []
    vistos: set[tuple] = set()
    indices: dict[str, int] = {}
    campos: dict[str, str] = {}
    paginas_lidas = 0
    nao_parseadas: list[str] = []

    total_esperado = pagina.evaluate(_JS_TOTAL_GRADE)

    for pagina_atual in range(1, _MAX_PAGINAS + 1):
        paginas_lidas += 1
        grade = pagina.evaluate(_JS_LER_GRADE) or {}
        cabecalhos, dados = grade.get("cabecalhos", []), grade.get("dados", [])

        if not indices:
            if not cabecalhos:
                raise ErpError("cabecalho da grade de pagamentos nao encontrado")
            indices, campos = _mapear_colunas(cabecalhos)
            _conferir_mapeamento(dados, indices, campos)

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

            # `reference` importa: a grade as vezes mostra "29/07" sem o ano, e
            # sem referencia parse_date_br devolve None — a linha entrava com
            # vencimento vazio e sumia do recorte por data, em silencio.
            vencimento = parse_date_br(campo("vencimento"),
                                       reference=periodo.fim if periodo else None)
            if vencimento is None and (campo("vencimento") or "").strip():
                nao_parseadas.append(campo("vencimento").strip())

            pagamentos.append(
                ErpPayment(
                    due_date=vencimento,
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

    if nao_parseadas:
        # Linha com vencimento ilegivel some do recorte por data sem deixar
        # rastro. Nao e erro (o total do rodape ainda protege o volume), mas
        # tem de aparecer.
        amostra = ", ".join(sorted(set(nao_parseadas))[:5])
        log(f"  [aviso] {len(nao_parseadas)} linha(s) com vencimento que nao "
            f"consegui ler (ex.: {amostra})")

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


def _recuperar_grade(pagina: Page, log=print) -> bool:
    """Uma segunda chance para a grade, recarregando a tela.

    O ERP e single-spa: trocar de rota nao levanta a aplicacao de novo, entao
    ela pode estar de pe com token vencido ou com estado preso da grade
    (pagina, filtro) — repintando a casca e a lista vazia. O reload obriga o
    bootstrap: ou os dados vem, ou a tela de login aparece e o erro passa a
    dizer a verdade.

    Barato: so acontece quando a grade ja veio vazia.
    """
    log("  a grade veio vazia; recarregando a tela e tentando de novo...")
    try:
        pagina.reload(wait_until="domcontentloaded")
    except Exception:
        _diag.warning("recarregando a tela de pagamentos para dar uma segunda "
                      "chance a grade", exc_info=True)
        return False
    pagina.wait_for_timeout(3000)
    quantas = _esperar_grade(pagina, timeout_s=45.0)
    if quantas:
        log(f"  recuperado: {quantas} linha(s) apos recarregar")
        return True
    return False


def motivo_da_grade_vazia(total_rodape, tem_texto_vazio: bool) -> str:
    """Explica uma grade sem linhas, separando as tres causas possiveis.

    O rodape e a chave: ele soma o mes inteiro, independente do que a grade
    lista. Total zerado significa mes sem lancamentos; total com valor e
    grade vazia significa que a listagem foi barrada — quase sempre a sessao
    do navegador nao estava valida, e o ERP respondeu sem dados.

    Funcao pura para poder ser testada: o caso real so aparece com a sessao
    quebrada, que e dificil de reproduzir de proposito.

    `total_rodape` chega como TEXTO da tela ("R$ 0,00"), e toda string nao
    vazia e verdadeira em Python: um mes legitimamente zerado caia no primeiro
    ramo e o app acusava "sua sessao caiu" — mandando procurar problema onde
    nao havia. Por isso o valor e convertido antes de ser testado.
    """
    valor = parse_brl(total_rodape) if isinstance(total_rodape, str) \
        else total_rodape
    if valor and valor > 0:
        return (
            "a grade de pagamentos veio vazia, mas o rodape da tela soma "
            f"{total_rodape} no mes.\n"
            "Ou seja: ha lancamentos, o ERP e que nao os listou — e nem "
            "recarregar a tela resolveu.\n"
            "O caso tipico e a sessao ter vencido sem o ERP avisar: ele "
            "repinta a tela e recusa os dados por baixo.\n"
            "Entre na janela do Chrome (se pedir login, faca) e rode de novo. "
            "Persistindo, veja o screenshot: pode haver filtro na tela."
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
    if _esperar_grade(pagina) == 0 and not _recuperar_grade(pagina, log=log):
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
        todos.extend(_coletar_mes_exibido(pagina, log=log, periodo=periodo))
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
            todos.extend(_coletar_mes_exibido(pagina, log=log, periodo=periodo))

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
