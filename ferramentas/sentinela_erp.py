# -*- coding: utf-8 -*-
"""Sentinela do contrato do ERP. Fotografa o front todo dia e diz o que mudou.

O QUE ELA EXISTE PARA IMPEDIR
----------------------------
A `sonda.py` prova que o ERP RESPONDE. Esta prova que o CONTRATO não mudou —
e são perguntas diferentes, com respostas em dias diferentes. Em 10/08/2026 a
tela `#/accounts` virou React: o ERP respondeu 200 o dia inteiro, a sonda
teria passado, e a leitura de saldos quebrou no meio de um pagamento. O que
mudou naquele dia não foi a disponibilidade, foi o INVENTÁRIO: uma tela que
existia deixou de existir naquele formato.

O Mais Controle publica esse inventário sem querer. O front é servido de dois
bundles JavaScript públicos — o LEGADO (AngularJS, ~5 MB, nome com hash que
muda a cada build) e o REACT (~6,7 MB, nome fixo) — e dentro deles estão
escritas as rotas de API (`"baseUrl","/payable-installments"`), os métodos que
as chamam, as telas (`path:"/accounts"`), os hosts de cada back-end e o número
de build. A sentinela baixa os dois, extrai isso tudo com expressões regulares,
guarda a fotografia e compara com a de ontem. Rota que SUMIU é o que quebra o
app, por isso vem primeiro no alerta; rota que apareceu é o que o app poderia
passar a usar. Hash de bundle que mudou sem o inventário mudar é build novo
sem mudança de contrato — vale saber, e vale menos.

Ela **não corrige nada e não decide nada**, como a irmã: uma linha por rodada
em `sentinela.log` e, se algo mudou, um `sentinela.ALERTA.txt` com o resumo
legível. Rodada igual à anterior apaga o ALERTA — arquivo de alarme que fica
para trás depois de resolvido é a forma mais rápida de ensinar alguém a
ignorar alarme.

ELA NUNCA LOGA EM NADA
----------------------
Baixar os bundles é um GET público: o mesmo que o navegador de qualquer pessoa
faz antes de existir tela de login. Não há senha envolvida, não há sessão de
ERP tomada de ninguém, e por isso ela pode rodar às 07:05 com o dono
trabalhando. O único cabeçalho que importa é o `user-agent` de Chrome
(`erp.sessao.USER_AGENT`): o WAF do ERP devolve 403 a quem se identifica como
robô, e o Python-urllib se identifica como robô.

Quando ela alarma, o passo seguinte é HUMANO: abrir o ALERTA, ver o que sumiu
e, se a dúvida for "o app ainda entra?", rodar `python -m ferramentas.sonda`
à mão. A sentinela sugere e não roda, porque a sonda loga no ERP e logar é
decisão de quem sabe se há alguém com sessão aberta.

ELA RODA FORA DO EXE
--------------------
`ferramentas/` está em `_PASTAS_SO_DO_REPO`, no `tests/test_empacotamento.py`:
nada daqui viaja no `codigo.zip`. É tarefa agendada do Windows, e o app não
sabe que ela existe.

COMO RODAR
----------
    python -m ferramentas.sentinela_erp             # fotografa, compara, grava
    python -m ferramentas.sentinela_erp --mostrar   # só imprime o inventário
    python -m ferramentas.sentinela_erp --pasta X   # guarda em X, não na base

Da RAIZ do repositório, e como MÓDULO, pela mesma razão da sonda: é a raiz que
precisa estar no caminho de import para `util` e `erp` serem encontrados.

Os arquivos: `sentinela.log` e `sentinela.ALERTA.txt` ao lado dos da sonda
(em `util.pasta_base()`, que rodando como script é a raiz do repositório), e
as fotografias em `sentinela/` — `ultimo.json`, que é o que a próxima rodada
compara, e uma cópia datada `AAAA-MM-DD.json` por dia, para se poder olhar o
que mudou entre duas datas.

Código de saída 1 quando o inventário mudou ou quando não deu para baixar,
0 quando está igual — é o que o Agendador de Tarefas do Windows mostra na
coluna "Resultado da última execução". A primeira rodada, sem `ultimo.json`,
só grava ("primeira fotografia") e sai com 0: não há com o que comparar.

AGENDAR (uma vez, à mão — este módulo NÃO cria a tarefa)
------------------------------------------------------
Cinco minutos depois da sonda, e com o Python pelo caminho absoluto, porque a
tarefa agendada não herda o PATH de ninguém (`where python` diz o caminho):

    schtasks /Create /TN "Sentinela do ERP" /SC DAILY /ST 07:05 /F ^
      /TR "cmd /c cd /d \\"C:\\caminho\\do\\repositorio\\" && ^
           \\"C:\\Python311\\python.exe\\" -m ferramentas.sentinela_erp"

O `cd /d` é o que faz o `-m` encontrar o pacote; sem ele a tarefa roda na
pasta do sistema e morre num `ModuleNotFoundError` que ninguém vê.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import util

from erp import hosts
from erp.sessao import USER_AGENT

log = util.log("sentinela")

#: Mais folgado que o da sonda, de propósito: aqui são ~12 MB em dois GETs, e
#: a pergunta é "o que está escrito lá dentro?", não "responde rápido?".
TIMEOUT_S = 60

ARQUIVO_LOG = "sentinela.log"
ARQUIVO_ALERTA = "sentinela.ALERTA.txt"
PASTA_FOTOS = "sentinela"
ARQUIVO_ULTIMO = "ultimo.json"

#: O índice da tela. É nele que está escrito o nome do bundle legado de hoje.
URL_INDICE = f"{hosts.ACESSAR}/"

#: O bundle React tem nome fixo. O legado não — ver `nome_do_legado`.
URL_REACT = f"{hosts.ACESSAR}/react-app/mc-react-app.js"

# ---------------------------------------------------------------- expressões
#
# Medidas contra os bundles reais em 08/09/2026. Cada uma casa UM tipo de
# coisa que o front escreve de forma regular, e o que ela devolve é sempre
# uma lista de strings ordenada e sem repetição: é isso que se compara.

_RE_LEGADO_NO_INDICE = re.compile(r"/(main-[0-9a-f]+\.js)")

_RE_RECURSO = re.compile(r'"baseUrl","(/[A-Za-z0-9/_-]*)"')
_RE_METODO = re.compile(
    r'key:"([A-Za-z0-9_$]+)",value:function *\(([^)]*)\)\{(.*?)'
    r'(?=key:"[A-Za-z0-9_$]+",value:|$)', re.DOTALL)
_RE_VERBO = re.compile(r"\.(get|post|put|patch|delete)\(")
_RE_ROTA = re.compile(r'"(/[^"]{0,120})"')
_RE_TELA = re.compile(r'path:"(/[A-Za-z0-9/_:-]*)"')
_RE_HOST = re.compile(
    r'(legacyApi|coreApiUrl|ofxApiUrl|exportingApi|purchasingApi|financialApi'
    r'|workManagementApi|inventoryApi|catalogApi|dailyFieldReportApi'
    r'|authorizationApi|importationsApiUrl|preLaunchesApiUrl|reportOnlineUrl'
    r'|knowledgeBaseApiUrl|clientPortalUrl|biEmbeddedUrl|dataIngestionApiUrl)'
    r':"([^"]+)"')
_RE_COMANDO = re.compile(r'"([a-z-]+)":\{inputSchema')
_RE_BUILD = re.compile(r'buildNumber:Number\(null!=="(\d+)"')

_RE_RECURSO_LEGADO = re.compile(r'\.(?:one|all)\("([^"]+)"')
_RE_TELA_LEGADO = re.compile(r'\.state\("([A-Za-z0-9._-]+)"')

#: As categorias do inventário, na ordem em que aparecem no ALERTA. O que está
#: em cima é o que quebra o app quando some; o que está embaixo é contexto.
CATEGORIAS = (
    "react/recursos",
    "react/metodos",
    "react/telas",
    "react/hosts",
    "react/comandos",
    "legado/recursos",
    "legado/telas",
)


def _unicos(itens) -> list[str]:
    return sorted(set(itens))


def _n(numero: int) -> str:
    """6712345 -> "6.712.345": ponto de milhar, como se lê aqui."""
    return f"{numero:,}".replace(",", ".")


# ------------------------------------------------------------ os extratores

def nome_do_legado(indice_html: str) -> str:
    """O `main-<hash>.js` de hoje, lido do HTML do índice. Vazio se não achar.

    O hash muda a cada build do legado, então o próprio nome é o número de
    versão dele — não há `buildNumber` escrito lá dentro como no React.
    """
    achado = _RE_LEGADO_NO_INDICE.search(indice_html)
    return achado.group(1) if achado else ""


def recursos_do_react(texto: str) -> list[str]:
    """As rotas base da API: `"baseUrl","/payable-installments"`."""
    return _unicos(_RE_RECURSO.findall(texto))


def metodos_do_react(texto: str) -> list[str]:
    """Os métodos de cada recurso, com os verbos HTTP e as rotas que chamam.

    O bundle escreve cada serviço como uma classe transpilada: primeiro o
    `baseUrl`, depois os métodos em `key:"nome",value:function(args){corpo}`.
    O trecho de um recurso vai do `baseUrl` dele até o `baseUrl` seguinte; o
    que houver ali de `key:...` é dele.

    Só entra método cujo corpo tem um verbo HTTP OU uma rota: entre dois
    serviços o bundle também escreve componentes de tela, com `render`,
    `componentDidMount` e afins, e listar isso seria inventariar o que não é
    contrato. Uma linha por método: `recurso metodo [verbos] rotas`.
    """
    posicoes = list(_RE_RECURSO.finditer(texto))
    linhas = []
    for i, achado in enumerate(posicoes):
        recurso = achado.group(1)
        fim = posicoes[i + 1].start() if i + 1 < len(posicoes) else len(texto)
        trecho = texto[achado.end():fim]
        for nome, _args, corpo in _RE_METODO.findall(trecho):
            verbos = _unicos(_RE_VERBO.findall(corpo))
            rotas = list(dict.fromkeys(_RE_ROTA.findall(corpo)))
            if not verbos and not rotas:
                continue
            linhas.append(f"{recurso} {nome} [{','.join(verbos)}] "
                          f"{' '.join(rotas)}".rstrip())
    return _unicos(linhas)


def telas_do_react(texto: str) -> list[str]:
    """As telas do roteador React: `path:"/accounts"`."""
    return _unicos(_RE_TELA.findall(texto))


def hosts_do_react(texto: str) -> list[str]:
    """Os hosts de cada back-end, da configuração embutida: `chave=valor`."""
    return _unicos(f"{chave}={valor}" for chave, valor in _RE_HOST.findall(texto))


def comandos_do_react(texto: str) -> list[str]:
    """Os comandos da API de pré-lançamentos: `"create-manual-pre-launch":{inputSchema`."""
    return _unicos(_RE_COMANDO.findall(texto))


def build_do_react(texto: str) -> str:
    """O `buildNumber` do front React. Vazio se não estiver escrito."""
    achado = _RE_BUILD.search(texto)
    return achado.group(1) if achado else ""


def recursos_do_legado(texto: str) -> list[str]:
    """Os recursos Restangular: `.one("purchase-order"` / `.all("quotation"`."""
    return _unicos(_RE_RECURSO_LEGADO.findall(texto))


def telas_do_legado(texto: str) -> list[str]:
    """Os estados do ui-router: `.state("base.purchaseOrderList"`."""
    return _unicos(_RE_TELA_LEGADO.findall(texto))


# ------------------------------------------------------------- o inventário

def _sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def inventariar(react: bytes, legado: bytes, nome_legado: str,
                quando: datetime | None = None) -> dict:
    """O inventário dos dois bundles: um dicionário ordenado e serializável.

    `react` e `legado` são os BYTES baixados — o hash é deles, não do texto
    decodificado, para que um byte trocado apareça como bundle diferente.
    """
    texto_react = react.decode("utf-8", errors="replace")
    texto_legado = legado.decode("utf-8", errors="replace")
    return {
        "quando": (quando or datetime.now()).strftime("%Y-%m-%dT%H:%M:%S"),
        "react": {
            "url": URL_REACT,
            "bytes": len(react),
            "sha256": _sha256(react),
            "build": build_do_react(texto_react),
        },
        "legado": {
            "arquivo": nome_legado,
            "bytes": len(legado),
            "sha256": _sha256(legado),
        },
        "categorias": {
            "react/recursos": recursos_do_react(texto_react),
            "react/metodos": metodos_do_react(texto_react),
            "react/telas": telas_do_react(texto_react),
            "react/hosts": hosts_do_react(texto_react),
            "react/comandos": comandos_do_react(texto_react),
            "legado/recursos": recursos_do_legado(texto_legado),
            "legado/telas": telas_do_legado(texto_legado),
        },
    }


# ------------------------------------------------------------- a comparação

@dataclass
class Diferencas:
    """O que mudou entre duas fotografias. Vazia quando nada mudou.

    `removidos` vem antes de `adicionados` em tudo que se imprime: rota que
    sumiu é o que quebra o app; rota que apareceu é curiosidade.
    """

    removidos: dict[str, list[str]] = field(default_factory=dict)
    adicionados: dict[str, list[str]] = field(default_factory=dict)
    bundles: list[str] = field(default_factory=list)

    @property
    def contrato_mudou(self) -> bool:
        return bool(self.removidos or self.adicionados)

    @property
    def mudou(self) -> bool:
        return self.contrato_mudou or bool(self.bundles)

    def resumo(self) -> str:
        """Curto, para a linha do log: `-3 +2` ou `build novo` ou `igual`."""
        if not self.mudou:
            return "igual"
        menos = sum(len(v) for v in self.removidos.values())
        mais = sum(len(v) for v in self.adicionados.values())
        partes = []
        if self.contrato_mudou:
            partes.append(f"contrato mudou: -{menos} +{mais}")
        if self.bundles:
            partes.append("; ".join(self.bundles))
        return " | ".join(partes)


def comparar(antes: dict, agora: dict) -> Diferencas:
    """Compara duas fotografias, categoria a categoria e bundle a bundle.

    `quando` fica de fora, é claro. O que entra: as listas de cada categoria
    (o contrato), o hash e o tamanho de cada bundle, o nome do legado e o
    `buildNumber` do React (a versão).
    """
    dif = Diferencas()
    antes_cat = antes.get("categorias", {})
    agora_cat = agora.get("categorias", {})
    for categoria in CATEGORIAS:
        de = set(antes_cat.get(categoria, []))
        para = set(agora_cat.get(categoria, []))
        if de - para:
            dif.removidos[categoria] = sorted(de - para)
        if para - de:
            dif.adicionados[categoria] = sorted(para - de)

    r0, r1 = antes.get("react", {}), agora.get("react", {})
    l0, l1 = antes.get("legado", {}), agora.get("legado", {})
    if r0.get("build") != r1.get("build"):
        dif.bundles.append(f"buildNumber {r0.get('build') or '?'} -> "
                           f"{r1.get('build') or '?'}")
    if l0.get("arquivo") != l1.get("arquivo"):
        dif.bundles.append(f"legado {l0.get('arquivo') or '?'} -> "
                           f"{l1.get('arquivo') or '?'}")
    for nome, de, para in (("react", r0, r1), ("legado", l0, l1)):
        if de.get("sha256") != para.get("sha256"):
            dif.bundles.append(f"{nome}: bytes diferentes "
                               f"({_n(de.get('bytes', 0))} -> "
                               f"{_n(para.get('bytes', 0))})")
    return dif


# ------------------------------------------------------------- o transporte

def baixar(url: str) -> bytes:
    """Um GET público, com o `user-agent` que passa pelo WAF. Levanta se não der.

    `urllib` e não `requests`, como a sonda: é biblioteca padrão, e dois GETs
    por dia não precisam de pool, retry nem sessão.
    """
    req = urllib.request.Request(url)
    req.add_header("user-agent", USER_AGENT)
    req.add_header("accept-language", "pt-BR")
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resposta:
        return resposta.read()


class NaoBaixou(RuntimeError):
    """Um dos três GETs não voltou inteiro. A mensagem diz qual e por quê."""


def fotografar(baixar_: Callable[[str], bytes] | None = None,
               quando: datetime | None = None) -> dict:
    """Baixa o índice e os dois bundles, e devolve o inventário.

    `baixar_` é o ponto que os testes trocam: recebe a URL, devolve os bytes.
    Resolvido na CHAMADA (e não como valor padrão do parâmetro) para que
    trocar `sentinela_erp.baixar` por monkeypatch alcance também quem entra
    por `main()`. Índice primeiro, porque é nele que está o nome do legado.
    """
    baixar_ = baixar_ or baixar
    try:
        indice = baixar_(URL_INDICE).decode("utf-8", errors="replace")
    except Exception as e:                                   # noqa: BLE001
        raise NaoBaixou(f"índice {URL_INDICE}: {_curto(e)}") from e
    nome_legado = nome_do_legado(indice)
    if not nome_legado:
        raise NaoBaixou("o índice veio sem o nome do bundle legado "
                        "(main-<hash>.js) — a tela mudou de forma")

    url_legado = f"{hosts.ACESSAR}/{nome_legado}"
    baixados = {}
    for nome, url in (("react", URL_REACT), ("legado", url_legado)):
        try:
            baixados[nome] = baixar_(url)
        except Exception as e:                               # noqa: BLE001
            raise NaoBaixou(f"{nome} {url}: {_curto(e)}") from e
        if not baixados[nome]:
            raise NaoBaixou(f"{nome} {url}: veio vazio")
    return inventariar(baixados["react"], baixados["legado"], nome_legado,
                       quando)


def _curto(erro: object, limite: int = 90) -> str:
    """A primeira linha do erro, cortada — uma linha por rodada no log."""
    texto = str(erro).strip().splitlines()
    primeira = texto[0].strip() if texto else erro.__class__.__name__
    return primeira[:limite]


# ---------------------------------------------------------------- os arquivos

def _pasta_fotos(base: Path) -> Path:
    return base / PASTA_FOTOS


def ler_ultimo(base: Path) -> dict | None:
    """A fotografia anterior, ou `None` na primeira rodada.

    Arquivo corrompido conta como "não há": a rodada grava por cima e diz
    "primeira fotografia", em vez de morrer todo dia no mesmo JSON quebrado.
    """
    arquivo = _pasta_fotos(base) / ARQUIVO_ULTIMO
    if not arquivo.is_file():
        return None
    try:
        return json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("lendo %s", arquivo, exc_info=True)
        return None


def gravar(base: Path, inventario: dict) -> Path:
    """`ultimo.json` (o que a próxima rodada compara) e a cópia do dia."""
    pasta = _pasta_fotos(base)
    pasta.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(inventario, ensure_ascii=False, indent=1)
    ultimo = pasta / ARQUIVO_ULTIMO
    ultimo.write_text(texto, encoding="utf-8")
    dia = inventario["quando"][:10]
    (pasta / f"{dia}.json").write_text(texto, encoding="utf-8")
    return ultimo


def linha(inventario: dict | None, desfecho: str,
          agora: datetime | None = None) -> str:
    """Uma linha do `sentinela.log`: data, os dois bundles, o desfecho."""
    quando = (agora or datetime.now()).strftime("%d/%m/%Y %H:%M:%S")
    if not inventario:
        return f"{quando}  falhou  {desfecho}"
    r, lg = inventario["react"], inventario["legado"]
    return (f"{quando}  react {_n(r['bytes'])} B build {r['build'] or '?'}  |  "
            f"legado {lg['arquivo']} {_n(lg['bytes'])} B  |  {desfecho}")


def texto_do_alerta(dif: Diferencas, inventario: dict,
                    agora: datetime | None = None) -> str:
    """O resumo que vai para o `sentinela.ALERTA.txt`. O que sumiu primeiro."""
    quando = (agora or datetime.now()).strftime("%d/%m/%Y %H:%M:%S")
    partes = [f"SENTINELA DO ERP — {quando}"]
    if dif.contrato_mudou:
        partes.append("O CONTRATO do front do ERP mudou desde a última "
                      "fotografia.")
    else:
        partes.append("Build novo do front do ERP, SEM mudança no inventário "
                      "de rotas e telas.")
    partes.append("")

    for titulo, grupo in (("SUMIU (é o que quebra o app):", dif.removidos),
                          ("APARECEU:", dif.adicionados)):
        if not grupo:
            continue
        partes.append(titulo)
        for categoria in CATEGORIAS:
            for item in grupo.get(categoria, []):
                partes.append(f"  - {categoria}: {item}")
        partes.append("")

    if dif.bundles:
        partes.append("BUNDLES:")
        partes.extend(f"  - {b}" for b in dif.bundles)
        partes.append("")

    r, lg = inventario["react"], inventario["legado"]
    partes.append(f"Hoje: React build {r['build'] or '?'} "
                  f"({_n(r['bytes'])} bytes), legado {lg['arquivo']} "
                  f"({_n(lg['bytes'])} bytes).")
    partes.append(f"As fotografias estão em {PASTA_FOTOS}/ (uma por dia); o "
                  f"histórico das rodadas no {ARQUIVO_LOG}.")
    partes.append("Para saber se o app ainda ENTRA no ERP, rode à mão: "
                  "python -m ferramentas.sonda")
    partes.append("Este arquivo some sozinho na primeira rodada em que nada "
                  "tiver mudado.")
    return "\n".join(partes) + "\n"


def _anotar(base: Path, texto: str) -> None:
    with (base / ARQUIVO_LOG).open("a", encoding="utf-8", newline="\n") as f:
        f.write(texto + "\n")


# ---------------------------------------------------------------- a rodada

def rodar(pasta=None, baixar_: Callable[[str], bytes] | None = None,
          agora: datetime | None = None, escrever=print) -> int:
    """Fotografa, compara, grava, alarma. Devolve o código de saída.

    0 quando o inventário está igual ao de ontem (ou na primeira fotografia);
    1 quando algo mudou OU quando não deu para baixar — nos dois casos há
    algo para uma pessoa olhar. A falha de download NÃO toca no `ultimo.json`
    nem no ALERTA: uma manhã sem rede não pode apagar um alarme de ontem que
    ninguém viu, nem virar a fotografia de referência.
    """
    base = Path(pasta or util.pasta_base())
    base.mkdir(parents=True, exist_ok=True)
    quando = agora or datetime.now()

    try:
        inventario = fotografar(baixar_, quando)
    except NaoBaixou as e:
        log.warning("sentinela: %s", e, exc_info=True)
        registro = linha(None, str(e), quando)
        _anotar(base, registro)
        escrever(registro)
        escrever("\nNão deu para fotografar o ERP. A fotografia anterior e o "
                 "ALERTA (se havia) ficaram como estavam.")
        return 1

    anterior = ler_ultimo(base)
    gravar(base, inventario)
    alerta = base / ARQUIVO_ALERTA

    if anterior is None:
        registro = linha(inventario, "primeira fotografia", quando)
        _anotar(base, registro)
        escrever(registro)
        escrever(f"\nPrimeira fotografia gravada em {_pasta_fotos(base)}. "
                 "Nada com que comparar ainda; amanhã há.")
        return 0

    dif = comparar(anterior, inventario)
    registro = linha(inventario, dif.resumo(), quando)
    (log.warning if dif.mudou else log.info)("sentinela: %s", dif.resumo())
    _anotar(base, registro)
    escrever(registro)

    if dif.mudou:
        alerta.write_text(texto_do_alerta(dif, inventario, quando),
                          encoding="utf-8")
        escrever(f"\nMudou. Resumo em {alerta}")
        return 1
    # `missing_ok`: rodada igual depois de outra igual não tem ALERTA para
    # apagar, e isso é o normal, não erro.
    alerta.unlink(missing_ok=True)
    escrever(f"\nIgual à fotografia anterior. Histórico em {base / ARQUIVO_LOG}")
    return 0


def mostrar(baixar_: Callable[[str], bytes] | None = None,
            escrever=print) -> int:
    """Imprime o inventário de agora e sai. Não compara e não grava nada."""
    try:
        inventario = fotografar(baixar_)
    except NaoBaixou as e:
        escrever(f"falhou: {e}")
        return 1
    r, lg = inventario["react"], inventario["legado"]
    escrever(f"React   {r['url']}  {_n(r['bytes'])} bytes  "
             f"build {r['build'] or '?'}")
    escrever(f"Legado  {lg['arquivo']}  {_n(lg['bytes'])} bytes")
    for categoria in CATEGORIAS:
        itens = inventario["categorias"][categoria]
        escrever(f"\n{categoria} ({len(itens)})")
        for item in itens:
            escrever(f"  {item}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ferramentas.sentinela_erp",
        description="Fotografa o inventário de rotas e telas do front do ERP "
                    "e alarma quando algo sumiu ou apareceu.")
    parser.add_argument("--mostrar", action="store_true",
                        help="imprime o inventário de agora e sai, sem "
                             "comparar nem gravar")
    parser.add_argument("--pasta", default=None,
                        help="onde guardar log, ALERTA e fotografias "
                             "(padrão: a pasta base do app)")
    args = parser.parse_args(argv)
    if args.mostrar:
        return mostrar()
    return rodar(args.pasta)


if __name__ == "__main__":
    sys.exit(main())
