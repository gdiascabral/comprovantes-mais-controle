# -*- coding: utf-8 -*-
"""Comprovantes de pagamento do Sicoob, por API, para várias contas num login.

**A diferença que manda no desenho:** no Inter cada conta é um login — 18
contas seriam 18 QR. Aqui um login enxerga as 18, e é por isso que o Sicoob vem
primeiro na fila da aba: um acesso resolve o que no Inter custaria dezoito.

O que a tela faz, e que aqui se faz direto:

    GET  /api/comprovantes/consultar?tipoPagamento=&dataInicio=&dataFim=
         devolve a lista, com data, valor, situação e o código de barras
    POST /api/comprovantes/detalhar   [os itens]
         devolve o comprovante em HTML — um por item

**O PDF não existe do lado do banco.** O `detalhar` entrega HTML, e a tela o
imprime. Isso cai na armadilha que o `extratos_sicoob/sicoob_client.py` já
documenta e já resolveu: o botão de imprimir chama `window.print()`, que abre o
diálogo modal do Windows e trava o lote inteiro. A saída, copiada de lá, é
gerar o arquivo por `Page.printToPDF` do CDP — `page.pdf()` do Playwright
recusa navegador com janela.

**A sessão expira em 20 minutos**, e são 18 contas. Por isso cada conta é um
`Resultado` próprio e a falha de uma não derruba as outras: quem chama percorre
a fila e reentra se precisar, como o `sicoob_baixar.baixar_mes` dos extratos já
faz.

**A tela de Comprovantes não tem Pix.** É outra tela do Sicoob
(`#/pix/extrato-pix`), com API própria (`/api/pix/lancamentos`) — confirmado
lendo a Rede do navegador em 10/09/2026 (não achado antes por dedução: o
Sicoob não documenta nada disso). Ela devolve, para o Pix, o que o Comprovantes
devolve para o resto: uma lista e um detalhe por item — só que o detalhe vem
em **JSON estruturado**, não em HTML pronto (`detalhar_pix`), porque nem a
PRÓPRIA tela do Sicoob tem um comprovante de Pix pré-montado: ela monta a
modal "Comprovante Pix" no navegador a partir desses mesmos campos, e o botão
de imprimir dela é o mesmo `window.print()` de sempre — confirmado clicando
"Exportar" (baixa Excel, não PDF) e "Emitir comprovantes" (abre a mesma tela
de impressão). `html_do_comprovante_pix` reconstrói esse layout à mão, o que
é mais simples que o caminho do Comprovantes comum: não precisa abrir a modal
na tela nem lidar com o CSS do banco.

**A lista de Pix é pedida pela PRÓPRIA tela, não por URL montada à mão.**
`numCooperativa`, `numCpfCnpj`, `ispbCooperativa` e o fuso exato de
`dataInicial`/`dataFinal` só existem dentro da sessão da conta aberta —
chutar um deles arrisca pedir o Pix de OUTRA conta sem nada denunciar, a
mesma razão pela qual `ir_para_comprovantes` não usa `goto`. `listar_pix`
preenche o filtro de período de verdade e lê a resposta que a tela recebeu.

**Os seletores do formulário saem do HTML de verdade, não de rótulo.** A
primeira versão (v2.0.188) procurava "Inicial"/"Final" por `get_by_label` e
`text=`, e travou 45s em todas as contas na primeira rodada real: aqueles
textos são `placeholder`, sem `<label>` nenhum, e `text=` só enxerga texto
renderizado. Em 11/09/2026 o `outerHTML` dos campos foi copiado do console do
navegador, e hoje o formulário é tocado pelos atributos fixos que ele tem:
`input[name=selecao][value="2"]` (rádio "Período"), `input[name=dataInicial]`,
`input[name=dataFinal]` e `button[data-content-label=Consultar]`. O que ainda
falta é uma rodada ao vivo inteira — lista, detalhe e PDF — com esses
seletores."""
from __future__ import annotations

import base64
import html
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import util

#: O diagnóstico do módulo. As funções que baixam recebem um `log` PRÓPRIO —
#: o recado que aparece no Registro da aba — e o parâmetro SOMBREIA este nome
#: lá dentro; este aqui é para o que falha longe do Registro.
log = util.log(__name__)

from . import ja_baixados, nome_final

BASE = "https://ib.sicoob.com.br/sicoobnet"
URL_COMPROVANTES = f"{BASE}/ib/#/comprovantes"

#: Os tipos que a tela oferece, com o código que a API usa. `TODOS` é o que
#: interessa por ora — separar por tipo seria uma consulta por tipo, e a lista
#: já vem completa numa só.
TIPO_TODOS = "TODOS"

#: Quanto se espera o HTML de cada comprovante virar PDF. Generoso: é trabalho
#: local, mas a fonte e o logo do SISBR carregam antes de imprimir.
ESPERA_RENDER = 800


class SicoobFalhou(RuntimeError):
    """O que impediu esta conta de terminar. Não derruba a fila."""


@dataclass
class Resultado:
    """O que aconteceu com UMA conta."""

    conta: str = ""
    baixados: list[Path] = field(default_factory=list)
    falhas: list[str] = field(default_factory=list)
    no_periodo: int = 0
    pix_no_periodo: int = 0               # Pix é tela e API separadas
    motivo: str = ""                     # "" = deu certo

    @property
    def ok(self) -> bool:
        return not self.motivo

    def resumo(self) -> str:
        if self.motivo:
            return self.motivo
        total = self.no_periodo + self.pix_no_periodo
        if not total:
            return "sem comprovantes no período"
        falhou = f" · {len(self.falhas)} falharam" if self.falhas else ""
        pix = f" (+{self.pix_no_periodo} de Pix)" if self.pix_no_periodo else ""
        return f"{len(self.baixados)} de {total} comprovantes{pix}{falhou}"


# --------------------------------------------------------------- sem tela

def data_do_lancamento(texto: str) -> "datetime | None":
    """`"2026-08-24 00:00:00.0"` -> data. None quando não dá para ler.

    O Sicoob devolve a data em formato de banco de dados, e não no `dd/mm/aaaa`
    da tela — quem for comparar com o período precisa passar por aqui."""
    achado = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", texto or "")
    if not achado:
        return None
    try:
        return datetime(*(int(p) for p in achado.groups()))
    except ValueError:
        return None


def dentro_do_periodo(item: dict, inicio: str, fim: str) -> bool:
    """O lançamento cai no período pedido? Sem data legível, fica de FORA.

    A API aceita `dataInicio`/`dataFim`, então isto é cinto e suspensório —
    existe porque no Inter um filtro de tela falhou CALADO e baixou três meses
    no lugar de uma semana. Conferir o que voltou custa nada."""
    quando = data_do_lancamento(item.get("dataLancamento") or "")
    try:
        d1 = datetime.strptime(inicio, "%d/%m/%Y")
        d2 = datetime.strptime(fim, "%d/%m/%Y")
    except (ValueError, TypeError):
        return False
    return bool(quando and d1 <= quando <= d2)


def _sem_acento(texto: str) -> str:
    """`TÍTULO` -> `TITULO`.

    Tirar o acento, e não substituí-lo: trocar por traço produzia `T-TULO`, que
    não se lê nem se procura. Nome de arquivo com acento também viaja mal entre
    máquinas e entre o Windows e o que vier depois."""
    cru = unicodedata.normalize("NFKD", texto or "")
    return re.sub(r"[^A-Za-z0-9]+", "-",
                  "".join(c for c in cru if not unicodedata.combining(c))
                  ).strip("-")


def nome_do_comprovante(item: dict, conta: str = "") -> str:
    """`SICOOB_2026-08-24_7190-20_TITULO_15057364.pdf`.

    Data, valor, o que é e o número do agendamento — que é o identificador do
    Sicoob, como o endToEnd é o do Pix. Sem carimbo de hora: ele diz quando o
    arquivo foi baixado, que não interessa a ninguém depois."""
    quando = data_do_lancamento(item.get("dataLancamento") or "")
    dia = quando.strftime("%Y-%m-%d") if quando else "0000-00-00"
    try:
        valor = f"{float(item.get('valorLancamento') or 0):.2f}".replace(".", "-")
    except (TypeError, ValueError):
        valor = "0-00"
    tipo = _sem_acento(item.get("tipoAgendamento") or "COMPROVANTE")[:24]
    limpar = lambda t: re.sub(r"[^A-Za-z0-9]+", "-", t or "").strip("-")  # noqa: E731
    ident = limpar(str(item.get("idAgendamento") or ""))[:20]
    return f"SICOOB_{dia}_{valor}_{tipo}_{ident}.pdf".replace("__", "_")


#: O que o Sicoob escreve quando a conta não tem comprovante no período. Ele
#: responde 400, e não uma lista vazia — o que é escolha dele, não erro nosso.
#: Estas são as marcas conhecidas; qualquer 400 com outro texto continua sendo
#: falha, e a mensagem mostra o que veio.
DIZERES_DE_VAZIO = ("nenhum registro", "nao foram encontrados",
                    "não foram encontrados", "nenhum comprovante",
                    "sem registros", "não encontrado", "nao encontrado")


def e_conta_sem_movimento(resposta: dict) -> bool:
    """Este 400 quer dizer "não há nada aqui"?

    Distinguir importa: conta parada é normal e vira "sem lançamentos"; sessão
    caída é falha e precisa aparecer em vermelho. Tratar as duas igual esconde
    uma ou assusta com a outra."""
    if int(resposta.get("status") or 0) != 400:
        return False
    dito = (resposta.get("corpo") or "").lower()
    return any(marca in dito for marca in DIZERES_DE_VAZIO)


def so_efetivados(itens) -> list:
    """Só o que saiu da conta.

    Agendado ainda não é pagamento, e comprovante de agendamento na pasta do
    mês é o que faz alguém dar por pago o que ainda vai acontecer."""
    return [i for i in itens
            if (i.get("situacao") or "").strip().upper() == "EFETIVADO"]


# --------------------------------------------------------------- com tela

_JS_API = """
async ([url, metodo, corpo]) => {
    const opcoes = {method: metodo, credentials: 'include'};
    if (corpo) {
        opcoes.headers = {'Content-Type': 'application/json'};
        opcoes.body = JSON.stringify(corpo);
    }
    const r = await fetch(url, opcoes);
    if (!r.ok) {
        // O CORPO junto do status: "HTTP 400" sozinho nao diz se a conta nao
        // tem movimento, se o periodo e invalido ou se a sessao caiu -- e as
        // tres pedem coisas diferentes de quem le.
        let dito = '';
        try { dito = (await r.text()).slice(0, 300); } catch (e) { dito = ''; }
        return {status: r.status, erro: `HTTP ${r.status}`, corpo: dito};
    }
    try {
        return {dado: await r.json()};
    } catch (e) {
        return {erro: 'a resposta não é JSON'};
    }
}
"""



JS_IR_PARA = """
([rota]) => { location.hash = rota; return location.href; }
"""


def conta_aberta(page) -> str:
    """Qual conta a TELA diz estar aberta. "" quando não dá para ler.

    Existe porque a pergunta "troquei mesmo?" não tinha resposta: o
    `acessar_conta` devolve True por ter clicado, não por ter chegado.

    Quem LÊ o texto é `sicoob_client.conta_do_cabecalho`, que conhece as duas
    telas do Sicoob. A leitura que morava aqui só achava `CONTA 50.019-4`, e
    na tela "Novo" o cabeçalho é `3299 | 50.019-4 | PJ`."""
    from extratos_sicoob.sicoob_client import (JS_TEXTOS_DA_CONTA,
                                               conta_do_cabecalho)

    try:
        textos = page.evaluate(JS_TEXTOS_DA_CONTA) or {}
        return conta_do_cabecalho(textos.get("novo"), textos.get("corpo", ""))
    except Exception:                                        # noqa: BLE001
        # "" faz `mesma_conta` dizer não, e a troca de conta é recusada como
        # se a tela mostrasse outra — quando o que houve foi não conseguir
        # perguntar. Sem o número da conta na mensagem.
        log.warning("perguntando à tela do Sicoob qual conta está aberta",
                    exc_info=True)
        return ""


def mesma_conta(pedida: str, na_tela: str) -> bool:
    """`50.019-4` e `500194` são a mesma conta; só os dígitos importam."""
    so = lambda t: re.sub(r"\D", "", t or "")                # noqa: E731
    return bool(so(pedida)) and so(pedida) == so(na_tela)


def ir_para_comprovantes(page) -> None:
    """Vai à tela de comprovantes SEM recarregar a aplicação.

    `page.goto` numa URL com `#` recarrega a SPA inteira, e ela reinicia na
    conta PADRÃO — jogando fora a troca que acabou de ser feita. Foi assim que
    uma rodada com 13 contas trouxe o comprovante de outra conta em três
    delas e HTTP 400 em seis: eu trocava e em seguida desfazia a troca.

    Mexer só no `location.hash` dispara a rota do Angular sem recarregar, e a
    conta escolhida continua valendo.
    """
    page.evaluate(JS_IR_PARA, ["#/comprovantes"])
    page.wait_for_timeout(3000)

def listar(page, inicio: str, fim: str, tipo: str = TIPO_TODOS) -> list:
    """Os comprovantes da conta ABERTA no período.

    Devolve lista vazia quando a conta não tem nada — inclusive quando o
    servidor diz isso por um HTTP 400, que foi o que ele fez em 6 das 13
    contas na primeira rodada de verdade. Conta parada não é falha: virar
    pill vermelha faria alguém procurar defeito onde não há.

    Levanta quando o 400 traz OUTRA coisa, e aí a mensagem carrega o que o
    servidor escreveu — "HTTP 400" sozinho não separa "conta sem movimento" de
    "sessão caiu"."""
    url = (f"{BASE}/api/comprovantes/consultar?tipoPagamento={tipo}"
           f"&dataInicio={inicio}&dataFim={fim}")
    resposta = page.evaluate(_JS_API, [url, "GET", None])
    if resposta.get("erro"):
        if e_conta_sem_movimento(resposta):
            return []
        dito = (resposta.get("corpo") or "").strip()
        raise SicoobFalhou("a consulta falhou: " + resposta["erro"]
                           + (f" — {dito[:160]}" if dito else ""))
    dado = resposta.get("dado")
    return dado if isinstance(dado, list) else []


def detalhar(page, itens: list) -> list:
    """O HTML de cada comprovante. Uma chamada, um item — ver o porquê.

    O endpoint aceita uma LISTA, e é tentador mandar tudo de uma vez. Não vale:
    no Inter, o endpoint equivalente também aceitava, e pedindo dois devolveu
    UM — grudou os comprovantes num arquivo só. Aqui o casamento entre item e
    HTML seria por posição, e um a menos faria cada arquivo levar o nome do
    pagamento errado. Ninguém veria até procurar um comprovante e achar outro.
    """
    saida = []
    for item in itens:
        resposta = page.evaluate(
            _JS_API, [f"{BASE}/api/comprovantes/detalhar", "POST", [item]])
        if resposta.get("erro"):
            saida.append((item, ""))
            continue
        dado = resposta.get("dado") or []
        html = ""
        if isinstance(dado, list) and dado:
            html = (dado[0] or {}).get("comprovante") or ""
        saida.append((item, html))
    return saida


#: De onde o HTML do comprovante foi tirado. `_com_base_href` ancora nele
#: qualquer caminho relativo (CSS, fonte, logo) que o HTML carregue — sem
#: isso o layout não resolve quando o arquivo é aberto de fora do site (ver
#: `_com_base_href`).
BASE_SICOOB = "https://ib.sicoob.com.br/sicoobnet/"


def _com_base_href(html: str, base: str = BASE_SICOOB) -> str:
    """Insere `<base href="...">` no HTML antes de imprimir.

    **Por que isto existe.** Um comprovante já baixado (Transferência entre
    Contas, 06/08/2026) sai com a data, o título e a hora um em cima do
    outro, e o resto da folha vazio — o layout que separaria essas três
    coisas em colunas não chega a carregar. O `detalhar` devolve um
    fragmento de página do Sicoob, cujo CSS é referenciado por caminho
    RELATIVO (`/sicoobnet/...`); `html_para_pdf` grava esse HTML num arquivo
    solto e abre por `file://`, onde um caminho relativo não aponta para
    lugar nenhum — o texto chega, o estilo que o organiza não. Um `<base
    href>` resolve isso sem tocar no HTML do banco: todo caminho relativo
    passa a resolver contra o site de origem, mesmo a página sendo aberta de
    um arquivo local.

    Pura de propósito — sem navegador — para o efeito valer prova por teste,
    e não só pela leitura de um PDF."""
    tag = f'<base href="{base}">'
    com_head = re.sub(r"(<head[^>]*>)", r"\1" + tag, html, count=1,
                      flags=re.IGNORECASE)
    if com_head != html:
        return com_head
    com_html = re.sub(r"(<html[^>]*>)", r"\1<head>" + tag + "</head>", html,
                      count=1, flags=re.IGNORECASE)
    if com_html != html:
        return com_html
    return tag + html


def html_para_pdf(ctx, html: str, destino: Path) -> Path:
    """Vira PDF sem passar pelo diálogo de impressão.

    O Sicoob não entrega PDF: entrega HTML, e a tela o manda para
    `window.print()`, que abre o preview modal do Chrome — trava o navegador,
    não fecha nem por CDP, e um clique distraído manda folha para a impressora.
    A saída é a mesma do `extratos_sicoob/sicoob_client.py`: abrir o HTML numa
    aba e imprimir por `Page.printToPDF`. (`page.pdf()` do Playwright recusa
    navegador com janela, e este roda com janela por causa do login manual.)

    Antes de gravar, `_com_base_href` ancora o HTML no site do Sicoob — sem
    isso o CSS do comprovante não carrega (ver o docstring dela)."""
    if not html.strip():
        raise SicoobFalhou("o comprovante veio vazio")
    with tempfile.TemporaryDirectory(prefix="sicoob_comp_") as tmp:
        arquivo = Path(tmp) / "comprovante.html"
        arquivo.write_text(_com_base_href(html), encoding="utf-8")
        aba = ctx.new_page()
        try:
            aba.goto(arquivo.as_uri(), wait_until="load")
            aba.wait_for_timeout(ESPERA_RENDER)
            sessao = ctx.new_cdp_session(aba)
            resposta = sessao.send("Page.printToPDF", {
                "printBackground": True,
                "marginTop": 0.4, "marginBottom": 0.4,
                "marginLeft": 0.4, "marginRight": 0.4,
            })
        finally:
            aba.close()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(base64.b64decode(resposta["data"]))
    return destino


def nome_livre(pasta: Path, nome: str) -> Path:
    """Um caminho que ainda não existe, numerando o repetido a partir do
    nome ORIGINAL — empilhar sufixo faz o terceiro sair `_1_2`."""
    base = Path(nome)
    destino = pasta / nome
    n = 1
    while destino.exists():
        destino = pasta / f"{base.stem}_{n}{base.suffix}"
        n += 1
    return destino


# --------------------------------------------------------------------- Pix
# A tela de Comprovantes não tem Pix -- é outra tela (#/pix/extrato-pix), com
# API própria. Ver o docstring do módulo para o que já foi confirmado lendo a
# Rede do navegador, e o que ainda depende de uma primeira rodada real.

_MEIO_INICIACAO_PIX = {"CHAVE": "Pix via chave", "QR_CODE": "Pix via QR Code",
                       "MANUAL": "Pix manual"}


def ir_para_pix(page) -> None:
    """Vai à tela de Pix sem recarregar a SPA — mesmo cuidado do
    `ir_para_comprovantes`: `page.goto` com `#` reinicia a aplicação na
    conta PADRÃO, jogando fora a troca de conta que acabou de ser feita."""
    page.evaluate(JS_IR_PARA, ["#/pix/extrato-pix"])
    page.wait_for_timeout(2500)


def _selecionar_periodo_pix(page) -> None:
    """Liga o rádio "Período" (`input[name=selecao][value="2"]`) — a tela
    nasce no rádio "Selecione o mês" (`value="1"`), que deixa Inicial/Final
    desabilitados.

    Não clica no TEXTO "Período": não há `<label>` ligando o texto ao rádio,
    e `page.locator("text=Período")` foi exatamente o que ficou preso 45s
    tentando achar "Inicial"/"Final" (ver o docstring de
    `_preencher_data_pix`) — o mesmo defeito, num campo vizinho."""
    page.locator('input[name="selecao"][value="2"]').click()
    page.wait_for_timeout(300)


def _preencher_data_pix(page, campo_nome: str, valor: str) -> None:
    """Preenche `dataInicial`/`dataFinal` pelo NAME real do campo, tecla a
    tecla — o mesmo cuidado do `aplicar_filtro_datas` do Inter: campo de
    data reage mal a um valor posto de uma vez só (`fill`).

    **Por que não por rótulo.** A primeira versão usava
    `get_by_label`/`text=Inicial`, e as duas travaram 45s tentando achar o
    campo: "Inicial" e "Final" são só o `placeholder` do `<input>` — não há
    `<label>` associado (nem por `for`/`id`, nem por texto visível), e
    `text=` do Playwright só enxerga texto que RENDERIZA na página, nunca
    atributo. Medido lendo o HTML de verdade em 11/09/2026 (o `outerHTML` de
    cada campo, copiado do console do navegador): os inputs têm
    `name="dataInicial"`/`name="dataFinal"` fixos, e é isso que se usa
    agora."""
    campo = page.locator(f'input[name="{campo_nome}"]')
    campo.click()
    campo.press("Control+a")
    campo.press("Delete")
    campo.type(valor, delay=40)


def listar_pix(page, inicio: str, fim: str, tempo: float = 15.0) -> list:
    """Os Pix enviados no período, pedidos pela PRÓPRIA tela de Pix.

    Não monta a URL da API à mão: `numCooperativa`, `numCpfCnpj` e o formato
    exato de `dataInicial`/`dataFinal` só a tela sabe montar — dependem da
    sessão e do fuso do navegador, e chutar um deles arrisca pedir o Pix de
    OUTRA conta sem nada denunciar. Em vez disso, preenche o filtro de
    verdade (Período, Inicial, Final) e lê a resposta que a própria tela
    recebeu ao clicar Consultar."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    ir_para_pix(page)
    _selecionar_periodo_pix(page)
    _preencher_data_pix(page, "dataInicial", inicio)
    _preencher_data_pix(page, "dataFinal", fim)
    botao = page.locator('button[data-content-label="Consultar"]').first
    if botao.count() == 0:
        raise SicoobFalhou("não achei o botão Consultar na tela de Pix")
    try:
        with page.expect_response(
                lambda r: "/api/pix/lancamentos" in r.url
                         and "/comprovante" not in r.url,
                timeout=tempo * 1000) as resposta:
            botao.click()
        corpo = resposta.value.json()
    except PlaywrightTimeout:
        raise SicoobFalhou(
            f"a tela de Pix não respondeu ao filtro em {tempo:.0f}s")
    return (corpo or {}).get("lancamentos") or []


def detalhar_pix(page, item: dict) -> dict:
    """O detalhe de UM Pix — pagador, destinatário, valor, data, id.

    Diferente do `detalhar` dos Comprovantes comuns: aqui o Sicoob devolve
    JSON estruturado, não HTML pronto — é a própria tela quem MONTA o
    comprovante a partir dele, e é o que permite montar o PDF sem abrir a
    modal na tela (ver `html_do_comprovante_pix`)."""
    id_ = item.get("id") or ""
    url = f"{BASE}/api/pix/lancamentos/{id_}/comprovante?isDevolucaoPix=false"
    resposta = page.evaluate(_JS_API, [url, "GET", None])
    if resposta.get("erro"):
        dito = (resposta.get("corpo") or "").strip()
        raise SicoobFalhou("o comprovante de Pix falhou: " + resposta["erro"]
                           + (f" — {dito[:160]}" if dito else ""))
    return resposta.get("dado") or {}


def _mascarar_documento(doc: str) -> str:
    """Mascara CPF/CNPJ como o próprio Sicoob mostra no comprovante —
    `***.865.821-**` (CPF) ou `**.750.602/0001-**` (CNPJ): os dígitos das
    pontas saem cobertos, e o miolo — que sozinho não identifica ninguém —
    continua visível. Medido no comprovante de 10/09/2026."""
    digitos = re.sub(r"\D", "", doc or "")
    if len(digitos) == 14:                                   # CNPJ
        return f"**.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-**"
    if len(digitos) == 11:                                   # CPF
        return f"***.{digitos[3:6]}.{digitos[6:9]}-**"
    return doc or ""


def _hora_pix(texto: str) -> str:
    """`"2026-09-08 17:57:29.63"` -> `"17:57:29"`. "" quando não há hora."""
    achado = re.search(r"\d{2}:\d{2}:\d{2}", str(texto or ""))
    return achado.group(0) if achado else ""


def nome_do_pix_sicoob(item: dict) -> str:
    """`SICOOB-PIX_2026-09-08_1208-36_E04388688...gfJ0.pdf` — provisório,
    até `nome_final.renomear` trocar pelo padrão do Renomear."""
    campos = nome_final.do_sicoob_pix(item)
    dia = "-".join(reversed(campos["data"].split("/"))) if campos["data"] \
        else "0000-00-00"
    valor = (campos["valor"] or "0,00").replace(".", "").replace(",", "-")
    ident = re.sub(r"[^A-Za-z0-9]+", "-",
                   str(item.get("id") or "")).strip("-")[:24]
    return f"SICOOB-PIX_{dia}_{valor}_{ident}.pdf".replace("__", "_")


def html_do_comprovante_pix(detalhe: dict) -> str:
    """Monta o comprovante de Pix no formato que a tela mostra — o Sicoob
    não entrega HTML pronto para esta tela (ao contrário dos Comprovantes
    comuns): só os dados. `detalhar_pix` traz o JSON; esta função desenha.

    HTML e CSS embutidos, sem NENHUM recurso externo — ao contrário do
    comprovante dos Comprovantes comuns, este nunca depende do `<base
    href>` (`_com_base_href`) para ficar legível, porque não referencia CSS
    nenhum de fora."""
    origem = detalhe.get("origem") or {}
    destino = detalhe.get("destino") or {}
    banco_origem = (origem.get("banco") or {}).get("NomeBanco", "")
    banco_destino = (destino.get("banco") or {}).get("NomeBanco", "")
    campos = nome_final.do_sicoob_pix(detalhe)
    quando = detalhe.get("atualizadoEm") or detalhe.get("criadoEm") or ""
    data_pagamento = f"{campos['data']} {_hora_pix(quando)}".strip()
    situacao = ("Finalizado com sucesso"
               if detalhe.get("estado") == "FINALIZADO_SUCESSO"
               else detalhe.get("estado") or "")
    tipo_pagamento = _MEIO_INICIACAO_PIX.get(detalhe.get("meioIniciacaoPix"),
                                             "Pix enviado")

    def linha(rotulo, valor):
        return (f'<tr><td class="rotulo">{html.escape(rotulo)}</td>'
               f'<td>{html.escape(str(valor))}</td></tr>')

    def secao(titulo):
        return f'<tr><td class="secao" colspan="2">{html.escape(titulo)}</td></tr>'

    linhas = "".join((
        linha("Tipo Pagamento", tipo_pagamento),
        secao("Pagador"),
        linha("Instituição", banco_origem),
        linha("Nome", origem.get("nome") or ""),
        linha("CPF/CNPJ", _mascarar_documento(origem.get("cpfCnpj") or "")),
        secao("Destinatário"),
        linha("Nome", destino.get("nome") or ""),
        linha("CPF/CNPJ", _mascarar_documento(destino.get("cpfCnpj") or "")),
        linha("Instituição/Banco", banco_destino),
        secao("Dados do pagamento"),
        linha("Data do pagamento", data_pagamento),
        linha("Valor", f"R$ {campos['valor']}" if campos["valor"] else ""),
        linha("ID Transação", detalhe.get("id") or ""),
        linha("Situação do pagamento", situacao),
    ))
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
body {{ font-family: Arial, Helvetica, sans-serif; font-size: 12px;
       color: #222; margin: 24px; }}
h1 {{ font-size: 13px; margin: 0 0 2px; }}
h2 {{ font-size: 13px; margin: 12px 0 10px; }}
table {{ border-collapse: collapse; width: 100%; }}
td {{ padding: 3px 6px 3px 0; vertical-align: top; }}
td.rotulo {{ font-weight: bold; width: 220px; }}
td.secao {{ font-weight: bold; padding-top: 12px; }}
.rodape {{ margin-top: 24px; font-size: 11px; color: #555; }}
</style></head><body>
<h1>SICOOB - SISTEMA DE COOPERATIVAS DE CRÉDITO DO BRASIL</h1>
<h1>SISBR - SISTEMA DE INFORMÁTICA DO SICOOB</h1>
<h2>COMPROVANTE DE EFETIVAÇÃO DE PAGAMENTO PIX</h2>
<table>{linhas}</table>
<div class="rodape">OUVIDORIA SICOOB : 08007250996</div>
</body></html>"""


def _baixar_pix_da_conta(cli, numero: str, inicio: str, fim: str,
                         destino: Path, resultado: Resultado, *,
                         log=print, registro=None) -> None:
    """A parte de Pix de `baixar_conta`, separada para poder falhar SOZINHA.

    A tela de Pix é nova e não tem, ainda, a mesma prova ao vivo que os
    Comprovantes comuns já têm (ver o docstring do módulo): se ela falhar —
    seletor que mudou, filtro que não abriu —, os Comprovantes já baixados
    continuam valendo. Por isso esta função NUNCA levanta: falhar aqui vira
    aviso no Registro, nunca `resultado.motivo`."""
    try:
        itens = listar_pix(cli.page, inicio, fim)
    except Exception as e:                                   # noqa: BLE001
        log(f"    Pix: {e}")
        return
    resultado.pix_no_periodo = len(itens)
    if not itens:
        return

    pendentes = []
    for item in itens:
        marca = ja_baixados.chave("sicoob_pix", item.get("id"), numero)
        if registro is not None and registro.tem(marca):
            continue
        pendentes.append(item)
    if len(pendentes) < len(itens):
        log(f"    Pix: {len(itens) - len(pendentes)} já baixado(s) antes")
    if not pendentes:
        return

    log(f"  Pix — {numero}: {len(pendentes)} para baixar")
    for item in pendentes:
        ident = item.get("id") or "?"
        try:
            detalhe = detalhar_pix(cli.page, item)
            corpo_html = html_do_comprovante_pix(detalhe)
            alvo = nome_livre(destino, nome_do_pix_sicoob(detalhe))
            html_para_pdf(cli.ctx, corpo_html, alvo)
            alvo = nome_final.renomear(alvo, nome_final.do_sicoob_pix(detalhe))
            resultado.baixados.append(alvo)
            if registro is not None:
                registro.anotar(
                    ja_baixados.chave("sicoob_pix", ident, numero), alvo)
            log(f"    {alvo.name}")
        except Exception as e:                               # noqa: BLE001
            resultado.falhas.append(str(ident))
            log(f"    Pix {ident} falhou ({e}) — seguindo")


def baixar_conta(cli, numero: str, inicio: str, fim: str, pasta,
                 log=print, registro=None) -> Resultado:
    """Os comprovantes de UMA conta, com ela já acessível pelo login aberto."""
    resultado = Resultado(conta=numero)
    destino = Path(pasta)
    try:
        if not cli.acessar_conta(numero):
            resultado.motivo = "a conta não está na lista deste login"
            return resultado
        ir_para_comprovantes(cli.page)

        # CONFERIR antes de pedir o dado. O `consultar` não recebe a conta —
        # ela é implícita na sessão —, então pedir com a conta errada aberta
        # devolve o comprovante DE OUTRA e nada na resposta denuncia isso. Os
        # arquivos sairiam com o nome certo e o conteúdo de outra empresa.
        aberta = conta_aberta(cli.page)
        if not mesma_conta(numero, aberta):
            resultado.motivo = (
                f"pedi a conta {numero} e a tela está em "
                f"{aberta or '(não consegui ler)'} — não vou baixar o "
                "comprovante de outra conta com o nome desta")
            return resultado

        itens = so_efetivados(listar(cli.page, inicio, fim))
        no_periodo = [i for i in itens if dentro_do_periodo(i, inicio, fim)]
        resultado.no_periodo = len(no_periodo)
        log(f"  {numero}: {len(itens)} efetivados · {len(no_periodo)} no período")

        # `if no_periodo:` -- e não um `return` antecipado como este bloco
        # tinha antes: sem comprovante NENHUM aqui não quer dizer que não há
        # Pix, e o Pix precisa continuar sendo tentado logo abaixo.
        if no_periodo:
            pendentes = []
            for item in no_periodo:
                marca = ja_baixados.chave("sicoob", item.get("idAgendamento"),
                                          numero)
                if registro is not None and registro.tem(marca):
                    continue
                pendentes.append(item)
            if len(pendentes) < len(no_periodo):
                log(f"    {len(no_periodo) - len(pendentes)} já baixado(s) antes")

            for item, html in detalhar(cli.page, pendentes):
                try:
                    alvo = nome_livre(destino, nome_do_comprovante(item, numero))
                    html_para_pdf(cli.ctx, html, alvo)
                    # O favorecido só existe DENTRO do comprovante — a lista
                    # do Sicoob não o traz. Por isso aqui o PDF é lido, e no
                    # Inter não: lá o JSON já tem tudo.
                    alvo = nome_final.renomear(
                        alvo, nome_final.do_sicoob(item,
                                                   nome_final.texto_do_pdf(alvo)))
                    resultado.baixados.append(alvo)
                    if registro is not None:
                        registro.anotar(
                            ja_baixados.chave("sicoob",
                                              item.get("idAgendamento"),
                                              numero), alvo)
                    log(f"    {alvo.name}")
                except Exception as e:                       # noqa: BLE001
                    ident = item.get("idAgendamento") or "?"
                    resultado.falhas.append(str(ident))
                    log(f"    {ident} falhou ({e}) — seguindo")

        # A conta certa já foi confirmada aberta (as duas checagens de cima
        # passaram) -- é a partir daqui que também vale pedir o Pix dela.
        # `_baixar_pix_da_conta` nunca levanta: uma falha nela não pode
        # apagar um resultado de Comprovantes que já deu certo, então ela
        # fica DENTRO deste `try` só para herdar o `cli`/`destino` já em
        # mãos, não para ser pega pelos `except` abaixo.
        _baixar_pix_da_conta(cli, numero, inicio, fim, destino, resultado,
                             log=log, registro=registro)
    except SicoobFalhou as e:
        resultado.motivo = str(e)
    except Exception as e:                                   # noqa: BLE001
        resultado.motivo = f"erro inesperado: {e}"
    return resultado
