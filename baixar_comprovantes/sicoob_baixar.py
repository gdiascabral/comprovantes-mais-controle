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
"""
from __future__ import annotations

import base64
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

try:                                     # utilitários compartilhados (raiz)
    import util                          # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from . import ja_baixados
except ImportError:                      # rodando este módulo isoladamente
    import ja_baixados

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
    motivo: str = ""                     # "" = deu certo

    @property
    def ok(self) -> bool:
        return not self.motivo

    def resumo(self) -> str:
        if self.motivo:
            return self.motivo
        if not self.no_periodo:
            return "sem comprovantes no período"
        falhou = f" · {len(self.falhas)} falharam" if self.falhas else ""
        return f"{len(self.baixados)} de {self.no_periodo} comprovantes{falhou}"


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



JS_CONTA_ABERTA = """
() => {
    // O cabecalho diz "SICOOB ENGECRED 3299 CONTA 50.019-4 / PJ".
    const achado = (document.body.innerText || '').match(/CONTA\\s+([\\d.]+-\\d)/);
    return achado ? achado[1] : '';
}
"""

JS_IR_PARA = """
([rota]) => { location.hash = rota; return location.href; }
"""


def conta_aberta(page) -> str:
    """Qual conta a TELA diz estar aberta. "" quando não dá para ler.

    Existe porque a pergunta "troquei mesmo?" não tinha resposta: o
    `acessar_conta` devolve True por ter clicado, não por ter chegado."""
    try:
        return page.evaluate(JS_CONTA_ABERTA) or ""
    except Exception:                                        # noqa: BLE001
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


def html_para_pdf(ctx, html: str, destino: Path) -> Path:
    """Vira PDF sem passar pelo diálogo de impressão.

    O Sicoob não entrega PDF: entrega HTML, e a tela o manda para
    `window.print()`, que abre o preview modal do Chrome — trava o navegador,
    não fecha nem por CDP, e um clique distraído manda folha para a impressora.
    A saída é a mesma do `extratos_sicoob/sicoob_client.py`: abrir o HTML numa
    aba e imprimir por `Page.printToPDF`. (`page.pdf()` do Playwright recusa
    navegador com janela, e este roda com janela por causa do login manual.)
    """
    if not html.strip():
        raise SicoobFalhou("o comprovante veio vazio")
    with tempfile.TemporaryDirectory(prefix="sicoob_comp_") as tmp:
        arquivo = Path(tmp) / "comprovante.html"
        arquivo.write_text(html, encoding="utf-8")
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
        if not no_periodo:
            return resultado

        pendentes = []
        for item in no_periodo:
            marca = ja_baixados.chave("sicoob", item.get("idAgendamento"),
                                      numero)
            if registro is not None and registro.tem(marca):
                continue
            pendentes.append(item)
        if len(pendentes) < len(no_periodo):
            log(f"    {len(no_periodo) - len(pendentes)} já baixado(s) antes")
        if not pendentes:
            return resultado

        for item, html in detalhar(cli.page, pendentes):
            try:
                alvo = nome_livre(destino, nome_do_comprovante(item, numero))
                html_para_pdf(cli.ctx, html, alvo)
                resultado.baixados.append(alvo)
                if registro is not None:
                    registro.anotar(
                        ja_baixados.chave("sicoob", item.get("idAgendamento"),
                                          numero), alvo)
                log(f"    {alvo.name}")
            except Exception as e:                           # noqa: BLE001
                ident = item.get("idAgendamento") or "?"
                resultado.falhas.append(str(ident))
                log(f"    {ident} falhou ({e}) — seguindo")
    except SicoobFalhou as e:
        resultado.motivo = str(e)
    except Exception as e:                                   # noqa: BLE001
        resultado.motivo = f"erro inesperado: {e}"
    return resultado
