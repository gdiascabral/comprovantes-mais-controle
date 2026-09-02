# -*- coding: utf-8 -*-
"""Sonda diária dos sistemas de terceiros. Avisa cedo, e não conserta nada.

O QUE ELA EXISTE PARA IMPEDIR
----------------------------
Três sistemas de fora sustentam o app e nenhum deles tem contrato de interface
com a gente: o **ERP**, por uma API interna que ninguém publicou; o **Inter** e
o **Sicoob**, por navegador, com as telas deles. Os três já quebraram — a tela
`#/accounts` do ERP virou React em 10/08/2026 e derrubou a leitura de saldos,
e a raspagem de contas já havia quebrado antes disso. As duas vezes a
descoberta veio no meio de um pagamento, que é o pior momento possível para
descobrir.

Esta sonda pergunta às 07:00, antes de alguém precisar. Ela **não corrige nada
e não decide nada**: escreve uma linha por sistema em `sonda.log` e, se algo
falhou, um `sonda.ALERTA.txt` com o resumo. Passando tudo, o ALERTA é apagado —
arquivo de alarme que fica para trás depois de resolvido é a forma mais rápida
de ensinar alguém a ignorar alarme.

ELA NÃO ABRE NAVEGADOR NENHUM
-----------------------------
E isso não é economia, é a única forma de ela poder rodar sozinha. O ERP aceita
**uma sessão de navegador por usuário**: um Chrome aberto por aqui às 07:00
derrubaria o da pessoa que estivesse trabalhando. O que a sonda faz no ERP é o
login por **API** (`POST /users/login`, o `jwtToken`), exatamente o que
`conciliacao/erp/api.py` já faz a cada abertura do app — é HTTP puro, não
disputa a sessão do navegador, e por isso os dois coexistem. Nos dois portais
de banco ela nem loga: pede só a **página de login**, para saber se ela ainda
responde.

E ela prova coisas diferentes sobre cada portal, porque os portais respondem
coisas diferentes. O Inter serve a página a um cliente HTTP comum; o Sicoob
**não responde a quem não é navegador** — medido em 02/09/2026, com os dois
métodos e o jogo completo de cabeçalhos. Ali sobra o aperto de mão TLS, que
prova menos e não mente: ver `_aperto_de_mao_tls`. Dizer menos é melhor que
alarmar todo dia sobre um sistema que está de pé — alarme falso ensina a
ignorar alarme.

ELA RODA FORA DO EXE
--------------------
`ferramentas/` está em `_PASTAS_SO_DO_REPO`, no `tests/test_empacotamento.py`:
nada dessa pasta viaja no `codigo.zip`. Uma sonda que fosse junto no exe teria
de ser ligada e desligada por alguém; aqui ela é uma tarefa agendada do
Windows, e o app não sabe que ela existe.

COMO RODAR
----------
    python -m ferramentas.sonda

Da RAIZ do repositório, e como MÓDULO: `ferramentas/` é pacote desde
02/09/2026, e é a raiz que precisa estar no caminho de import para o `util` e
as abas serem encontrados. Quem tiver a tarefa agendada apontando para
`python -m ferramentas.sonda` precisa trocar a linha de comando.

Saída no console (uma linha por sistema) e nos arquivos. Código de saída 1
quando algo falhou, 0 quando não — é o que o Agendador de Tarefas do Windows
mostra na coluna "Resultado da última execução".
"""
from __future__ import annotations

import contextlib
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import util

from anexar import credenciais
from baixar_comprovantes import inter_baixar
from conciliacao.erp import api
from extratos_sicoob import sicoob_config
from nuvem import rest, sessao
from nuvem.contas_novas import API_BASE, LEGACY_BASE

log = util.log("sonda")

#: Curto de propósito. A pergunta da sonda é "responde?", não "responde bem?" —
#: e um sistema que leva mais de 10 s para servir a própria página de login já
#: é notícia, ainda que acabe respondendo no décimo primeiro segundo.
TIMEOUT_S = 10

ARQUIVO_LOG = "sonda.log"
ARQUIVO_ALERTA = "sonda.ALERTA.txt"

#: A tabela mais barata que prova que a sessão vale e a RLS deixa ler. Não
#: interessa o CONTEÚDO — só que o servidor respondeu 200 a quem está logado.
TABELA_DA_SONDA = "empresa"

ERP = "erp"
SUPABASE = "supabase"
INTER = "inter"
SICOOB = "sicoob"

#: Os dois portais de banco, com a URL saindo de quem já a usa: nenhuma URL de
#: terceiro é escrita duas vezes no repositório. Só a página de login — a sonda
#: não tem senha de banco nenhuma, e não teria o que fazer com uma.
PORTAIS = (
    (INTER, inter_baixar.URL_LOGIN),
    (SICOOB, sicoob_config.URL_LOGIN),
)


@dataclass(frozen=True)
class Resultado:
    """O que se soube de UM sistema nesta rodada.

    `ok=False` é o que faz nascer o ALERTA, então o que entra aqui como falha
    tem de ser falha DO TERCEIRO. Sessão vencida e senha que não está guardada
    são problemas nossos e não alarmam ninguém — ver `sondar_supabase`.
    """

    sistema: str
    ok: bool
    ms: int
    motivo: str = ""


def _ms(inicio: float) -> int:
    return int(round((time.monotonic() - inicio) * 1000))


def _curto(erro: object, limite: int = 90) -> str:
    """A primeira linha do erro, cortada. O resto vai para o diagnostico.log.

    As exceções daqui são conversadas de propósito (o `erp/api.py` explica em
    três linhas o que fazer com um 403 do WAF), e isso é certo na tela do app e
    errado numa coluna de log: uma linha por sistema só serve se couber numa
    linha.
    """
    texto = str(erro).strip().splitlines()
    primeira = texto[0].strip() if texto else erro.__class__.__name__
    return primeira[:limite]


# --------------------------------------------------------------------- o ERP

class _ConfigDoErp:
    """O bastante do `config` da Conciliação para o `SessaoApi` logar.

    As duas bases saem de `nuvem/contas_novas.py`, que resolveu este mesmo
    problema para a abertura do app: importar `conciliacao/config.py` exigiria
    o `config.yaml`, que fica FORA do repositório e diverge de máquina para
    máquina. Uma sonda que não roda por falta de arquivo de configuração é uma
    sonda que ninguém conserta.

    O pacote `erp/` nasceu para ser o dono desses endereços, e o `__init__.py`
    dele diz que nenhum consumidor migrou ainda — `nuvem/contas_novas.py` é o
    PRIMEIRO da fila. Pendurar a sonda nessas constantes é de propósito: quando
    aquele PR trocar as duas por `erp.hosts`, a sonda vai junto sem que ninguém
    precise lembrar dela.
    """

    erp = {"api_base": API_BASE, "legacy_api_base": LEGACY_BASE}


@contextlib.contextmanager
def _relogio_curto_do_erp():
    """Aperta o relógio do `erp/api.py` durante a sondagem, e o devolve depois.

    Lá os números são 45 s de espera e 3 tentativas em GET, e estão certos para
    uma RODADA de verdade: um 504 passageiro do gateway não pode custar a
    coleta inteira. Para uma sonda são o oposto do que se quer — 3 tentativas
    com espera dobrada esticam uma pergunta de 10 s para mais de meio minuto, e
    escondem justamente a lentidão que a sonda existe para notar.

    Trocado aqui, e não no `erp/api.py`: o app depende daqueles números, e
    mudá-los por causa de uma ferramenta seria a ferramenta mandando no
    produto.
    """
    antes = (api._TIMEOUT_S, api._TENTATIVAS_GET)
    api._TIMEOUT_S, api._TENTATIVAS_GET = TIMEOUT_S, 1
    try:
        yield
    finally:
        api._TIMEOUT_S, api._TENTATIVAS_GET = antes


def _ha_credencial() -> bool:
    """Existe senha do ERP guardada nesta máquina?

    `credenciais.carregar()` é a função — a mesma que
    `conciliacao/erp/auth.obter_credenciais()` alcança lá dentro, lendo o
    `login.dat` cifrado pela DPAPI. A sonda pergunta antes para separar dois
    MOTIVOS que o `SessaoApi` junta numa exceção só, e que pedem coisas
    diferentes de quem lê o alerta: "não há senha guardada aqui" manda abrir o
    app e clicar em 🔑 Login; "o ERP recusou a senha" manda conferir se a senha
    mudou — ou se o contrato do login mudou. Os dois falham, porque os dois
    param a manhã seguinte; o que muda é o que fazer com eles.

    As variáveis de ambiente entram na conta porque `obter_credenciais` as
    prefere ao arquivo; sem elas aqui, uma máquina de desenvolvimento que só
    tem `MC_EMAIL`/`MC_SENHA` levaria um alarme falso todo dia.
    """
    if os.environ.get("MC_EMAIL") and os.environ.get("MC_SENHA"):
        return True
    guardado = credenciais.carregar()
    return bool(guardado and guardado[0] and guardado[1])


def sondar_erp() -> Resultado:
    """Login por API + um GET de contas. Sem navegador — ver o topo do módulo.

    O GET vai junto de propósito: o login pode continuar respondendo depois de
    o contrato da listagem mudar, e foi a LISTAGEM que quebrou as duas vezes.
    """
    inicio = time.monotonic()
    if not _ha_credencial():
        return Resultado(ERP, False, _ms(inicio),
                         "sem senha do ERP guardada (login.dat)")
    try:
        with _relogio_curto_do_erp():
            # `log` mudo: o `SessaoApi` escreve "conectado como Fulano
            # (Empresa)", e nome de pessoa e de empresa não entram no
            # `sonda.log`, que é arquivo comum na pasta do app.
            conectado = api.SessaoApi.logar(_ConfigDoErp(),
                                            log=lambda *_a, **_k: None)
            contas = conectado.listar_contas(ativas=True)
    except Exception as e:                                       # noqa: BLE001
        log.warning("sonda do ERP", exc_info=True)
        return Resultado(ERP, False, _ms(inicio), _curto(e))
    if not contas:
        # Zero conta ATIVA não acontece nesta empresa: ou o filtro parou de
        # filtrar, ou o contrato da resposta mudou. Nos dois casos, é notícia.
        return Resultado(ERP, False, _ms(inicio),
                         "login ok, mas a listagem veio sem nenhuma conta")
    return Resultado(ERP, True, _ms(inicio), f"{len(contas)} contas")


# ------------------------------------------------------------------ a nuvem

@contextlib.contextmanager
def _relogio_curto_da_nuvem():
    """Mesma troca do `_relogio_curto_do_erp`, no `nuvem/rest.py`.

    Os 20 s de lá são generosos porque a alternativa é pior: uma leitura que
    desiste cedo manda o app para o cache sem precisar. A sonda não tem cache
    para onde ir — ela só precisa saber se respondeu.
    """
    antes = rest.ESPERA
    rest.ESPERA = TIMEOUT_S
    try:
        yield
    finally:
        rest.ESPERA = antes


def sondar_supabase(pasta=None) -> Resultado:
    """Um GET de uma linha, com a sessão de `sessao.dat`.

    **Sessão vencida não é falha do Supabase**, e por isso não alarma: o token
    é nosso, vence sozinho, e a sonda não tem — nem pode ter — a senha de
    ninguém para renová-lo. Um alarme diário por causa disso ensinaria a
    ignorar o arquivo justamente no dia em que ele disser outra coisa.

    O mesmo vale para a recusa do banco (403): ali o servidor RESPONDEU, que é
    exatamente o que a sonda foi perguntar. Quem julga permissão é a RLS, e o
    dia em que ela mudar aparece na tela do app, não aqui.
    """
    inicio = time.monotonic()
    with _relogio_curto_da_nuvem():
        try:
            token = sessao.token(pasta)
        except rest.PrecisaEntrar:
            return Resultado(SUPABASE, True, _ms(inicio), "sessão vencida")
        except rest.ErroDaNuvem as e:
            log.warning("sonda da nuvem: obtendo o token", exc_info=True)
            return Resultado(SUPABASE, False, _ms(inicio), _curto(e))

        try:
            linhas = rest.ler(TABELA_DA_SONDA, token,
                              colunas="id", filtro="limit=1")
        except rest.PrecisaEntrar as e:
            return Resultado(SUPABASE, True, _ms(inicio),
                             f"sessão recusada — {_curto(e, 60)}")
        except rest.ErroDaNuvem as e:
            log.warning("sonda da nuvem: lendo %s", TABELA_DA_SONDA,
                        exc_info=True)
            return Resultado(SUPABASE, False, _ms(inicio), _curto(e))
    return Resultado(SUPABASE, True, _ms(inicio), f"{len(linhas)} linha(s)")


# ------------------------------------------------------- os portais de banco

#: O que a linha diz quando só o aperto de mão TLS respondeu. Ver
#: `_aperto_de_mao_tls` — a frase é longa de propósito: ela é a diferença
#: entre "o portal está de pé" e tudo o que esta sonda pode provar do Sicoob.
PORTA_ABERTA = "porta 443 aberta; a página não responde a cliente HTTP simples"


def _aperto_de_mao_tls(url: str) -> None:
    """Abre e fecha uma conexão TLS com o host da URL. Levanta se não der.

    Existe por uma medição de 02/09/2026: `ib.sicoob.com.br` **não responde a
    cliente HTTP que não seja navegador** — nem a `urllib` nem a `requests`,
    com HEAD ou GET, na raiz ou na página de login, com user-agent de Chrome e
    o jogo completo de cabeçalhos, esperando até 30 s. O TLS fecha em ~180 ms e
    a conexão depois trava na LEITURA, que é a assinatura de um guarda que
    reconhece o cliente pelo aperto de mão, não pelos cabeçalhos. O Inter, no
    mesmo teste, responde 200 em meio segundo.

    Isso deixa a sonda com uma escolha: alarmar todo dia sobre um Sicoob que
    está de pé, ou dizer menos e dizer verdade. Ela diz menos. O aperto de mão
    prova que o nome resolve, que a porta atende e que o certificado do host é
    válido — bem menos que um HTTP 200, e o suficiente para o que quebra na
    prática: DNS mudado, host derrubado, certificado vencido. Quem quiser mais
    que isso precisa de navegador, e navegador é o que esta sonda não abre.
    """
    partes = urllib.parse.urlsplit(url)
    porta = partes.port or (443 if partes.scheme == "https" else 80)
    with socket.create_connection((partes.hostname, porta),
                                  timeout=TIMEOUT_S) as tcp:
        if partes.scheme != "https":
            return
        contexto = ssl.create_default_context()
        with contexto.wrap_socket(tcp, server_hostname=partes.hostname):
            return


def sondar_portal(sistema: str, url: str) -> Resultado:
    """A página de login respondeu? HEAD, com GET de reserva. Nada além disso.

    HEAD primeiro porque é a pergunta inteira sem baixar página nenhuma; GET
    depois **só quando o servidor respondeu alguma coisa** — 405 e 403 no HEAD
    são comuns e não são o banco caindo. Depois de um silêncio, insistir com
    GET seria pagar o segundo timeout para ouvir o mesmo nada.

    O `user-agent` sai de `conciliacao/erp/api.USER_AGENT`, e não é frescura:
    lá ele é a única coisa que separa 200 de 403 no WAF do ERP, e o guarda dos
    bancos é da mesma família — quem se identifica como robô leva a página do
    WAF em vez da do site.

    Silêncio completo cai no `_aperto_de_mao_tls`, que separa "o portal caiu"
    de "o portal não fala com quem não é navegador".
    """
    inicio = time.monotonic()
    houve_resposta, ultimo = False, ""
    for metodo in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=metodo)
        req.add_header("user-agent", api.USER_AGENT)
        req.add_header("accept-language", "pt-BR")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resposta:
                return Resultado(sistema, True, _ms(inicio),
                                 f"HTTP {resposta.status} em {metodo}")
        except urllib.error.HTTPError as e:
            houve_resposta, ultimo = True, f"HTTP {e.code} em {metodo}"
        except Exception as e:             # noqa: BLE001 — rede, DNS, TLS
            ultimo = _curto(e)
            break                          # calou: o GET ouviria o mesmo nada

    if houve_resposta:
        # O servidor falou, e o que ele disse não serve: código de erro na
        # própria página de login é notícia sobre o portal.
        log.warning("sonda do portal %s: %s", sistema, ultimo)
        return Resultado(sistema, False, _ms(inicio), ultimo)

    try:
        _aperto_de_mao_tls(url)
    except Exception:                      # noqa: BLE001 — DNS, TCP, TLS
        log.warning("sonda do portal %s: %s", sistema, ultimo, exc_info=True)
        return Resultado(sistema, False, _ms(inicio), ultimo)
    return Resultado(sistema, True, _ms(inicio), PORTA_ABERTA)


# ---------------------------------------------------------------- a rodada

def sondar(pasta=None) -> list[Resultado]:
    """Os quatro sistemas, na ordem em que doeriam: ERP, nuvem, Inter, Sicoob.

    Em série, e não em paralelo: são quatro perguntas de 10 s no pior caso, e
    uma sonda que sobe quatro threads para economizar meio minuto às 07:00 é
    complexidade comprada com o que não faltava.
    """
    resultados = [sondar_erp(), sondar_supabase(pasta)]
    resultados.extend(sondar_portal(nome, url) for nome, url in PORTAIS)
    return resultados


def linha(resultado: Resultado, agora: datetime | None = None) -> str:
    """Uma linha do `sonda.log`: data, sistema, ok/falhou, ms, motivo curto."""
    quando = (agora or datetime.now()).strftime("%d/%m/%Y %H:%M:%S")
    estado = "ok" if resultado.ok else "falhou"
    return (f"{quando}  {resultado.sistema:<9}  {estado:<6}  "
            f"{resultado.ms:>6} ms  {resultado.motivo}")


def texto_do_alerta(falhas: list[Resultado],
                    agora: datetime | None = None) -> str:
    """O resumo que vai para o `sonda.ALERTA.txt`. Só o que falhou."""
    quando = (agora or datetime.now()).strftime("%d/%m/%Y %H:%M:%S")
    corpo = "\n".join(f"  - {f.sistema}: {f.motivo} ({f.ms} ms)"
                      for f in falhas)
    return (f"SONDA — {quando}\n"
            f"{len(falhas)} sistema(s) não responderam como deveriam:\n"
            f"{corpo}\n\n"
            f"O detalhe de cada um está no diagnostico.log, e o histórico no "
            f"{ARQUIVO_LOG}.\nEste arquivo some sozinho na primeira rodada em "
            f"que tudo passar.\n")


def registrar(resultados: list[Resultado], pasta=None,
              agora: datetime | None = None) -> list[Resultado]:
    """Grava o log, cria ou apaga o ALERTA, e devolve as falhas.

    Append no log e reescrita inteira no ALERTA, de propósito: o log é
    histórico (uma linha corrompida custa uma linha) e o ALERTA é ESTADO —
    ele diz o que está errado AGORA, e um ALERTA de anteontem somado ao de
    hoje é ruído com cara de gravidade.
    """
    base = Path(pasta or util.pasta_base())
    quando = agora or datetime.now()
    falhas = [r for r in resultados if not r.ok]

    for r in resultados:
        (log.info if r.ok else log.warning)(
            "%s: %s (%s ms) %s", r.sistema, "ok" if r.ok else "falhou",
            r.ms, r.motivo)
    with (base / ARQUIVO_LOG).open("a", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(linha(r, quando) for r in resultados) + "\n")

    alerta = base / ARQUIVO_ALERTA
    if falhas:
        alerta.write_text(texto_do_alerta(falhas, quando), encoding="utf-8")
    else:
        # `missing_ok`: a rodada que passa depois de outra que passou não tem
        # ALERTA para apagar, e isso é o normal, não erro.
        alerta.unlink(missing_ok=True)
    return falhas


def main() -> int:
    resultados = sondar()
    for r in resultados:
        print(linha(r))
    falhas = registrar(resultados)
    base = util.pasta_base()
    if falhas:
        print(f"\n{len(falhas)} falha(s). Resumo em {base / ARQUIVO_ALERTA}")
    else:
        print(f"\nTudo respondeu. Histórico em {base / ARQUIVO_LOG}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
