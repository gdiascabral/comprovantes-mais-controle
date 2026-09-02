# -*- coding: utf-8 -*-
"""HTTP com o Supabase. Não sabe o que é conta, aporte nem janela.

Este módulo existe para que o resto do pacote nunca escreva um cabeçalho nem
leia um código HTTP. Quem chama recebe dado pronto ou uma exceção com NOME —
e o nome importa: "sem rede" e "sua senha venceu" pedem coisas diferentes de
quem está na frente da tela, e um traceback não pede nada.
"""
from __future__ import annotations


import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import util

log = util.log(__name__)

#: Endereço do projeto e chave PÚBLICA. Ficam no código de propósito.
#:
#: A chave `anon` é pública por desenho: ela identifica o projeto e não abre
#: nada sozinha. Quem protege é a RLS — toda tabela nega tudo a quem não está
#: logado, e isso está conferido por teste (ler `conta` sem sessão responde
#: 401).
#:
#: Até 30/08/2026 havia uma segunda tranca: o auto-cadastro estava desligado,
#: então esta chave nem conta criava. A fase 3 o ligou — é o que permite
#: alguém novo entrar sem o admin digitar a senha por ela — e por isso a
#: tranca mudou de lugar: agora TODA política e as duas funções de NSA exigem
#: `privado.e_ativo()`, ou seja, perfil liberado por um administrador. Conta
#: recém-criada loga, lê o próprio perfil, e não alcança mais nada. Ver
#: `supabase/migrations/20260830180000_so_conta_liberada_entra.sql`.
#:
#: A chave `service_role` ignora a RLS inteira e NUNCA pode aparecer aqui,
#: no exe, nem no CI.
URL = "https://hhvuvqayaqxpypdissci.supabase.co"
CHAVE_PUBLICA = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhodnV2cWF5YXF4cHlwZGlzc2NpIiwicm9sZSI6"
    "ImFub24iLCJpYXQiOjE3ODY2Mzg0MDYsImV4cCI6MjEwMjIxNDQwNn0"
    ".Q25lP5jz1hmCzPRiQ7YxJe354iAp_xUSz44ispnZS_U")

#: Generoso porque a alternativa é pior: o cadastro inteiro são poucos KB, e
#: uma leitura que desiste cedo manda o app para o cache sem precisar.
ESPERA = 20


def _montar_sessao() -> requests.Session:
    """Uma conexão viva por execução, em vez de refazer DNS/TCP/TLS a cada
    chamada — e nova tentativa automática quando o gateway responde 5xx.

    Só GET repete. Reenviar um POST que criou algo e perdeu a resposta
    duplicaria o que foi criado (empresa/conta em dobro, cadastro repetido);
    quem chama um POST vê a falha uma vez e decide se tenta de novo.
    `raise_on_status=False`: esgotadas as tentativas, a ÚLTIMA resposta 5xx
    volta como resposta comum — é `_resposta()` quem já sabe traduzir status
    HTTP em exceção NOMEADA, e duplicar essa tradução aqui criaria duas
    fontes para a mesma regra.
    """
    sessao = requests.Session()
    novas_tentativas = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[502, 503, 504],
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    sessao.mount("https://", HTTPAdapter(max_retries=novas_tentativas))
    return sessao


#: Módulo inteiro fala com o mesmo projeto (URL fixa acima), então uma sessão
#: só basta — é o ponto único que os testes trocam para simular o transporte.
_SESSAO = _montar_sessao()


class ErroDaNuvem(RuntimeError):
    """Raiz de tudo que pode dar errado aqui."""


class SemRede(ErroDaNuvem):
    """Não deu para falar com o servidor: sem internet, DNS, projeto pausado.

    É o erro que o cadastro ENGOLE (caindo no cache) e que o registro NÃO
    engole."""


class PrecisaEntrar(ErroDaNuvem):
    """A sessão venceu ou não existe. Quem vê isto tem de pedir a senha."""


class RecusadoPeloBanco(ErroDaNuvem):
    """O banco entendeu e disse não: trava de unicidade, regra violada.

    Erro de PROGRAMA ou de cadastro, não de rede — repetir não resolve."""


def _cabecalhos(token: str | None) -> dict:
    # Sempre os DOIS: `apikey` diz qual projeto, `Authorization` diz quem é.
    # Sem token, o Authorization leva a chave pública e o banco trata como
    # anônimo — que é justamente quem não pode ler nada.
    return {"apikey": CHAVE_PUBLICA,
            "Authorization": f"Bearer {token or CHAVE_PUBLICA}",
            "Content-Type": "application/json"}


def _motivo_do_servidor(r) -> str:
    """O que o PostgREST escreveu junto da recusa. "" quando não escreveu.

    Sem isto, 401 e 403 viravam a mesma frase e a causa se perdia: "sua sessão
    venceu" e "esta tabela não aceita escrita" pedem coisas opostas de quem lê
    — uma pede login, a outra pede permissão no banco. Em 24/08/2026 um
    cadastro recusado deixou as duas hipóteses abertas, e nada no recado
    ajudava a separar.
    """
    try:
        corpo = r.json()
    except Exception:
        log.warning("lendo o motivo da recusa do servidor (HTTP %s): a "
                    "resposta não veio em JSON", getattr(r, "status_code", "?"),
                    exc_info=True)
        return ""
    if not isinstance(corpo, dict):
        return ""
    for chave in ("message", "msg", "error_description", "error", "hint"):
        valor = corpo.get(chave)
        if valor:
            return str(valor)[:160]
    return ""


def _resposta(r) -> object:
    if r.status_code in (401, 403):
        motivo = _motivo_do_servidor(r)
        # 401 é sessão; 403 é permissão. Dizer "entre de novo" para um 403
        # manda a pessoa refazer login para um problema que o login não
        # resolve.
        base = ("sua sessão venceu — entre de novo" if r.status_code == 401
                else "o banco recusou a operação (sem permissão)")
        raise PrecisaEntrar(f"{base} [HTTP {r.status_code}]"
                            + (f": {motivo}" if motivo else ""))
    if r.status_code >= 400:
        try:
            corpo = r.json()
            recado = corpo.get("message") or corpo.get("msg") or str(corpo)
        except ValueError:
            recado = (r.text or "")[:300]
        raise RecusadoPeloBanco(f"HTTP {r.status_code}: {recado}")
    if not r.content:
        return None
    try:
        return r.json()
    except ValueError as e:
        # Resposta 200 que não é JSON costuma ser página de manutenção ou
        # portal de wi-fi sequestrando a conexão. É problema de rede.
        raise SemRede(f"resposta não é JSON ({e})")


def _chamar(metodo: str, caminho: str, token, dados=None, prefer="") -> object:
    cab = _cabecalhos(token)
    if prefer:
        cab["Prefer"] = prefer
    try:
        r = _SESSAO.request(metodo, f"{URL}{caminho}", headers=cab,
                            json=dados, timeout=ESPERA)
    except requests.RequestException as e:
        raise SemRede(f"não deu para falar com o servidor: {e}") from e
    return _resposta(r)


# ------------------------------------------------------------------ tabelas

def ler(tabela: str, token: str, *, colunas: str = "*", filtro: str = "") -> list:
    """Linhas de uma tabela. `filtro` é sintaxe do PostgREST ("id=eq.3")."""
    caminho = f"/rest/v1/{tabela}?select={colunas}"
    if filtro:
        caminho += f"&{filtro}"
    return _chamar("GET", caminho, token) or []


def inserir(tabela: str, token: str, linhas: list[dict], *,
            devolver: bool = True) -> list:
    """Insere e devolve o que ficou gravado (com os ids)."""
    if not linhas:
        return []
    prefer = "return=representation" if devolver else "return=minimal"
    return _chamar("POST", f"/rest/v1/{tabela}", token, linhas, prefer) or []


def alterar(tabela: str, token: str, filtro: str, mudancas: dict) -> list:
    """Altera as linhas que o filtro alcança. Filtro vazio é recusado aqui.

    O PostgREST aceita PATCH sem filtro e altera a TABELA INTEIRA. Um filtro
    montado a partir de uma variável vazia viraria isso sem erro nenhum."""
    if not filtro:
        raise ValueError("alterar sem filtro mudaria a tabela inteira")
    return _chamar("PATCH", f"/rest/v1/{tabela}?{filtro}", token, mudancas,
                   "return=representation") or []


def apagar(tabela: str, token: str, filtro: str) -> None:
    """Apaga as linhas que o filtro alcança. Pelo mesmo motivo do `alterar`,
    filtro vazio é recusado."""
    if not filtro:
        raise ValueError("apagar sem filtro esvaziaria a tabela")
    _chamar("DELETE", f"/rest/v1/{tabela}?{filtro}", token)


def perfil(token: str, user_id: str) -> dict | None:
    """O perfil de quem é dono deste token: nome, papel e situação.

    `None` quer dizer "o servidor respondeu, e essa pessoa não tem perfil" —
    não confundir com "não deu para perguntar", que sai como exceção. Os dois
    pedem coisas diferentes de quem chama, e é o `nuvem/sessao.py` que decide
    o quê.

    Filtra por `user_id` mesmo com a RLS já limitando cada um ao próprio
    perfil, porque para o ADMIN ela não limita: ele lê a tabela inteira, que é
    o que a fila de aprovação exige. Sem o filtro, o app do admin receberia a
    lista toda e leria o papel da primeira linha que viesse — o de outra
    pessoa.
    """
    if not user_id:
        return None
    linhas = ler("perfil", token,
                 colunas="user_id,nome,email,papel,situacao",
                 filtro=f"user_id=eq.{user_id}&limit=1")
    return linhas[0] if linhas else None


def chamar(funcao: str, token: str, **argumentos):
    """Executa uma função do banco e devolve o que ela retornou.

    Existe para o que precisa acontecer numa instrução só, dentro do banco —
    hoje, reservar o próximo NSA. Fazer isso em duas viagens (ler o contador,
    somar um, gravar) é exatamente como duas máquinas acabam com o mesmo
    número: as duas leem antes de qualquer uma gravar.
    """
    return _chamar("POST", f"/rest/v1/rpc/{funcao}", token, argumentos)


# --------------------------------------------------------------------- auth

def entrar(email: str, senha: str) -> dict:
    """Troca e-mail e senha por uma sessão. Devolve o corpo do GoTrue."""
    try:
        r = _SESSAO.post(f"{URL}/auth/v1/token?grant_type=password",
                         headers=_cabecalhos(None),
                         json={"email": email, "password": senha},
                         timeout=ESPERA)
    except requests.RequestException as e:
        raise SemRede(f"não deu para falar com o servidor: {e}") from e
    if r.status_code in (400, 401):
        raise PrecisaEntrar("e-mail ou senha incorretos")
    return _resposta(r)


#: O que o GoTrue responde quando recusa um cadastro, traduzido para quem
#: está na frente da tela. A chave é um PEDAÇO da mensagem dele, em minúsculas:
#: o texto vem em inglês e muda de versão para versão, mas o miolo fica.
_RECUSAS_DO_CADASTRO = (
    ("signups not allowed",
     "O cadastro de contas novas está desligado no projeto. Quem cuida do "
     "Supabase precisa ligá-lo em Authentication → Sign In / Providers → "
     "Allow new users to sign up."),
    ("already registered",
     "Já existe uma conta com esse e-mail. Use a aba “Entrar”."),
    # As três recusas de senha do GoTrue são coisas diferentes, e dizê-las
    # com a mesma frase manda a pessoa mexer no lugar errado: alongar uma
    # senha que já é longa, ou embaralhar uma que o servidor nem pede
    # embaralhada. A ordem importa — "should be at least" é mais específico
    # que "password", e vem antes.
    ("password should be at least",
     "A senha é curta demais para o servidor: %s. O mínimo é configurado no "
     "painel, em Authentication → Sign In / Providers → Minimum password "
     "length."),
    ("should contain at least one character of each",
     "O servidor exige tipos de caractere que faltam nessa senha — em geral "
     "letra minúscula, MAIÚSCULA e número. O que ele pediu: %s"),
    ("known to be weak",
     "Essa senha é conhecida por ser fácil de adivinhar (ela aparece em "
     "listas de senhas vazadas). Escolha outra."),
    ("weak password",
     "O servidor recusou essa senha por ser fraca: %s"),
    ("unable to validate email address",
     "Esse e-mail não parece válido. Confira o que foi digitado."),
    ("invalid format",
     "Esse e-mail não parece válido. Confira o que foi digitado."),
    ("rate limit",
     "Foram muitas tentativas seguidas. Espere alguns minutos e tente de "
     "novo — o limite é do servidor, não do app."),
)


def criar_conta(nome: str, email: str, senha: str) -> bool:
    """Cria a conta e pede ao Supabase que mande a confirmação por e-mail.

    Devolve True quando ainda falta confirmar o e-mail — que é o caso normal.

    NÃO entra. A sessão só nasce depois que a pessoa clica no link que chegou
    no endereço que ela digitou, e é justamente isso que prova que o endereço
    é dela. O app não vê, não guarda e não escolhe a senha de ninguém: ela vai
    daqui para o servidor e nunca mais volta.

    O `nome` viaja em `data`, que o GoTrue grava em `raw_user_meta_data` — é
    de lá que o gatilho `privado.criar_perfil()` o copia para o perfil. Sem
    ele o admin veria uma fila de e-mails sem gente.
    """
    try:
        r = _SESSAO.post(f"{URL}/auth/v1/signup",
                         headers=_cabecalhos(None),
                         json={"email": email.strip(), "password": senha,
                               "data": {"nome": nome.strip()}},
                         timeout=ESPERA)
    except requests.RequestException as e:
        raise SemRede(f"não deu para falar com o servidor: {e}") from e

    if r.status_code >= 400:
        cru = _motivo_do_servidor(r)
        dito = cru.lower()
        for pedaco, frase in _RECUSAS_DO_CADASTRO:
            if pedaco in dito:
                # O `%s` das frases de senha carrega o texto do servidor. Ele
                # vem em inglês, e ainda assim vale: é onde está o NÚMERO que
                # o painel configurou, e sem ele a frase manda tentar de novo
                # sem dizer até onde.
                raise RecusadoPeloBanco(frase % cru if "%s" in frase else frase)
        # Recusa que ainda não sabemos traduzir: vale mais mostrar o que o
        # servidor disse do que uma frase genérica que esconde a causa.
        raise RecusadoPeloBanco(
            "O servidor recusou o cadastro"
            + (f": {_motivo_do_servidor(r)}" if dito else
               f" [HTTP {r.status_code}]"))

    corpo = _resposta(r) or {}
    # Com a confirmação de e-mail ligada, o GoTrue devolve só o usuário. Se
    # vier token, é porque ela está DESLIGADA no projeto — a conta já nasce
    # confirmada, e quem está na tela precisa ouvir outra frase.
    return not (isinstance(corpo, dict) and corpo.get("access_token"))


def renovar(refresh_token: str) -> dict:
    """Troca o token de renovação por uma sessão nova."""
    try:
        r = _SESSAO.post(f"{URL}/auth/v1/token?grant_type=refresh_token",
                         headers=_cabecalhos(None),
                         json={"refresh_token": refresh_token},
                         timeout=ESPERA)
    except requests.RequestException as e:
        raise SemRede(f"não deu para falar com o servidor: {e}") from e
    if r.status_code in (400, 401):
        raise PrecisaEntrar("a sessão salva não vale mais")
    return _resposta(r)


def sair(token: str) -> None:
    """Encerra a sessão no servidor. Falhar aqui não é problema: o token
    local é apagado de qualquer forma, e ele vence sozinho."""
    try:
        _SESSAO.post(f"{URL}/auth/v1/logout", headers=_cabecalhos(token),
                     timeout=ESPERA)
    except requests.RequestException:
        pass
