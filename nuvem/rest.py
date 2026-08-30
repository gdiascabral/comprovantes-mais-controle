# -*- coding: utf-8 -*-
"""HTTP com o Supabase. Não sabe o que é conta, aporte nem janela.

Este módulo existe para que o resto do pacote nunca escreva um cabeçalho nem
leia um código HTTP. Quem chama recebe dado pronto ou uma exceção com NOME —
e o nome importa: "sem rede" e "sua senha venceu" pedem coisas diferentes de
quem está na frente da tela, e um traceback não pede nada.
"""
from __future__ import annotations

import requests

#: Endereço do projeto e chave PÚBLICA. Ficam no código de propósito.
#:
#: A chave `anon` é pública por desenho: ela identifica o projeto e não abre
#: nada sozinha. Quem protege é a RLS — toda tabela nega tudo a quem não está
#: logado, e isso está conferido por teste (ler `conta` sem sessão responde
#: 401). O cadastro de novos usuários está DESLIGADO no projeto, então nem
#: mesmo criar conta com ela é possível.
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
        r = requests.request(metodo, f"{URL}{caminho}", headers=cab,
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
        r = requests.post(f"{URL}/auth/v1/token?grant_type=password",
                          headers=_cabecalhos(None),
                          json={"email": email, "password": senha},
                          timeout=ESPERA)
    except requests.RequestException as e:
        raise SemRede(f"não deu para falar com o servidor: {e}") from e
    if r.status_code in (400, 401):
        raise PrecisaEntrar("e-mail ou senha incorretos")
    return _resposta(r)


def renovar(refresh_token: str) -> dict:
    """Troca o token de renovação por uma sessão nova."""
    try:
        r = requests.post(f"{URL}/auth/v1/token?grant_type=refresh_token",
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
        requests.post(f"{URL}/auth/v1/logout", headers=_cabecalhos(token),
                      timeout=ESPERA)
    except requests.RequestException:
        pass
