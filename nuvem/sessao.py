# -*- coding: utf-8 -*-
"""Quem está usando o app, e como ele continua entrando amanhã.

A sessão fica em `sessao.dat`, ao lado do exe, cifrada pela DPAPI — o mesmo
cofre do `login.dat`. Guardar o token em texto seria pior que guardar a senha:
o token entra sem precisar dela.

**O que acontece quando o servidor não responde** é a parte que exige cuidado,
e são três desfechos diferentes de propósito:

  vencido, com rede    -> pede a senha de novo. Normal.
  sem rede, no prazo   -> ABRE. O app já não faz nada sem internet (ERP,
                          Sicoob e portal são todos web), então travar aqui
                          só transformaria uma queda do Supabase em app
                          parado com o ERP de pé.
  sem rede, vencido    -> não abre, e diz isso.

E é preciso ser exato sobre o que o caso do meio garante: **sem servidor, o
app confere a VALIDADE, não a assinatura.** O token é assinado com um segredo
do projeto, que não pode viajar dentro de um exe público; sem ele, só dá para
ler a data de expiração de dentro do próprio token. Quem sustenta a garantia
aqui é a DPAPI: o `sessao.dat` só é decifrável pelo mesmo usuário do Windows
na mesma máquina que o gravou, e quem chegou nessa conta já tem o app, os
arquivos e o `login.dat`. Havendo rede, quem julga é o servidor — a renovação
é recusada se o usuário foi removido ou teve a senha trocada.

**O papel viaja junto.** Desde 30/08/2026 a sessão guarda também quem a pessoa
é no cadastro — nome, papel e situação, lidos da tabela `perfil`. Ele é
perguntado ao servidor nas duas horas em que já se está falando com ele
(entrar e renovar), e não a cada chamada: renovação é de hora em hora, então o
papel na tela nunca está mais de uma hora atrasado.

E é preciso ser exato sobre o que ele decide: o papel guardado aqui escolhe o
que APARECE, e nada mais. Quem barra de verdade é a RLS do banco, que julga o
token a cada chamada — um papel adulterado no arquivo local abriria abas cujos
botões o servidor recusaria.
"""
from __future__ import annotations

import base64
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

try:
    from . import rest
except ImportError:
    import rest

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

ARQUIVO = "sessao.dat"

#: Renova com folga: token que vence em 2 minutos vence no meio do trabalho.
FOLGA = 120

#: O que vale para a conta que o servidor conhece e que ainda não tem perfil.
#: É o mesmo padrão da tabela: entra, mas não trabalha até alguém liberar.
#: Só o servidor pode levar a isto — "não deu para perguntar" é outra coisa, e
#: nunca rebaixa ninguém.
SEM_PERFIL = {"nome": "", "papel": "operador", "situacao": "pendente"}

#: Sessão gravada por versão anterior a esta não tem papel nenhum. A busca de
#: recuperação é feita UMA vez por execução: sem este freio, um app aberto sem
#: internet pagaria os 20s de espera do `rest` em cada chamada, e a espera é
#: por uma informação que só serve para desenhar o menu.
_ja_procurei_o_perfil = False


def _caminho(pasta=None) -> Path:
    return Path(pasta or util.pasta_base()) / ARQUIVO


def _dentro(token: str) -> dict:
    """O miolo do JWT, ou {} quando não dá para ler.

    Sem verificar assinatura — ver o cabeçalho do módulo. `+ "=="` cobre o
    padding que o base64url do JWT omite; sobra de padding é ignorada."""
    try:
        corpo = token.split(".")[1]
        dados = json.loads(base64.urlsafe_b64decode(corpo + "==").decode())
        return dados if isinstance(dados, dict) else {}
    except Exception:
        return {}


def _quando_vence(token: str) -> int:
    """Lê o `exp` de dentro do JWT. 0 quando não dá para ler."""
    try:
        return int(_dentro(token).get("exp") or 0)
    except (TypeError, ValueError):
        return 0


def _email(token: str) -> str:
    return _dentro(token).get("email") or ""


def _sub(token: str) -> str:
    """O `user_id` de dentro do token — a chave do perfil e da auditoria.

    É o mesmo valor que o `auth.uid()` do banco enxerga, porque é dele que o
    Postgres o tira: a claim `sub` do JWT que chega na chamada."""
    return _dentro(token).get("sub") or ""


def _ler(pasta=None) -> dict | None:
    caminho = _caminho(pasta)
    if not caminho.exists():
        return None                      # sem sessão salva: silêncio é certo
    try:
        return json.loads(util.revelar_bytes(caminho.read_bytes()).decode())
    except Exception:
        # DPAPI recusando (outro usuário, perfil restaurado) ou arquivo
        # truncado. Nos dois casos o certo é pedir a senha, nunca adivinhar.
        return None


def _gravar(sessao: dict, pasta=None) -> None:
    try:
        _caminho(pasta).write_bytes(
            util.proteger_bytes(json.dumps(sessao).encode()))
    except OSError:
        # Pasta somente-leitura ou antivírus: quem acertou a senha entra
        # assim mesmo, e amanhã o app pergunta de novo. Pior é ficar de fora.
        pass


@dataclass(frozen=True)
class Quem:
    """Quem está usando o app: o e-mail de sempre, e agora o papel.

    Era uma string com o e-mail. Virou isto porque a partir da Fase 4 o menu
    se monta pelo papel, e passar papel adiante como um segundo valor solto
    é como as duas metades da mesma pessoa acabam desencontradas.

    `situacao` vazia quer dizer "ainda não perguntei", e é diferente de
    `pendente`: pendente é resposta do servidor, vazio é ausência dela. Quem
    for esconder aba precisa saber a diferença — esconder tudo de quem ficou
    sem internet é o app sumindo sozinho."""

    email: str = ""
    nome: str = ""
    papel: str = ""
    situacao: str = ""
    user_id: str = ""

    def __bool__(self) -> bool:
        return bool(self.email or self.user_id)

    @property
    def conhecido(self) -> bool:
        """O servidor já disse quem é esta pessoa?"""
        return bool(self.situacao)

    @property
    def ativo(self) -> bool:
        return self.situacao == "ativo"

    @property
    def pendente(self) -> bool:
        return self.situacao == "pendente"

    @property
    def admin(self) -> bool:
        return self.ativo and self.papel == "admin"

    @property
    def aprovador(self) -> bool:
        return self.ativo and self.papel == "aprovador"

    @property
    def primeiro_nome(self) -> str:
        """Para a barra do topo: o primeiro nome, ou o que vem antes do @."""
        return (self.nome.split()[0] if self.nome.strip()
                else self.email.split("@")[0])


def _perfil_do_servidor(acesso: str) -> dict | None:
    """Pergunta o papel ao banco. `None` = não deu para perguntar.

    Nunca levanta. Quem chama está no meio de um login que JÁ deu certo, e
    derrubá-lo por causa de uma segunda viagem transformaria uma oscilação de
    rede em "não consigo entrar" — com a senha certa e o token na mão."""
    try:
        return rest.perfil(acesso, _sub(acesso)) or dict(SEM_PERFIL)
    except rest.ErroDaNuvem:
        return None


def _com_perfil(nova: dict, anterior: dict | None = None) -> dict:
    """Acrescenta nome, papel e situação à sessão. Devolve a mesma sessão.

    Não perguntou, não esquece: sem resposta do servidor fica valendo o que já
    se sabia. O contrário — zerar o papel a cada tropeço de rede — faria a
    pessoa perder as abas por causa do wi-fi."""
    perfil = _perfil_do_servidor(nova.get("acesso", ""))
    if perfil is None:
        perfil = {c: (anterior or {}).get(c, "")
                  for c in ("nome", "papel", "situacao")}
    nova["user_id"] = _sub(nova.get("acesso", ""))
    for campo in ("nome", "papel", "situacao"):
        nova[campo] = perfil.get(campo) or ""
    return nova


def _recuperar_o_perfil(sessao: dict, pasta=None) -> None:
    """Busca o papel da sessão que veio sem ele, uma vez por execução.

    Existe por causa do dia da atualização: quem já estava entrado tem um
    `sessao.dat` gravado por uma versão que não guardava papel, e o token
    dentro dele ainda vale por até uma hora — ou seja, o app abriria sem
    renovar e, portanto, sem nunca perguntar quem é a pessoa. Numa manhã em
    que o menu se monta pelo papel, isso é a equipe inteira sem abas."""
    global _ja_procurei_o_perfil
    if sessao.get("situacao") or _ja_procurei_o_perfil:
        return
    _ja_procurei_o_perfil = True
    completa = _com_perfil(dict(sessao), sessao)
    if completa.get("situacao"):         # só grava o que o servidor disse
        sessao.update(completa)
        _gravar(completa, pasta)


def entrar(email: str, senha: str, pasta=None) -> str:
    """Entra com e-mail e senha, guarda a sessão e devolve o token de acesso.

    Levanta `rest.PrecisaEntrar` se a senha não confere e `rest.SemRede` se
    não deu para perguntar."""
    corpo = rest.entrar(email.strip(), senha)
    sessao = {"acesso": corpo["access_token"],
              "renovacao": corpo["refresh_token"],
              "email": email.strip()}
    _gravar(_com_perfil(sessao, _ler(pasta)), pasta)
    return sessao["acesso"]


def token(pasta=None) -> str:
    """O token de acesso válido de agora, renovando se preciso.

    Levanta `rest.PrecisaEntrar` quando não há sessão utilizável — é o sinal
    de "mostre a janela de login"."""
    sessao = _ler(pasta)
    if not sessao:
        raise rest.PrecisaEntrar("ninguém entrou neste computador ainda")

    if _quando_vence(sessao.get("acesso", "")) - FOLGA > time.time():
        _recuperar_o_perfil(sessao, pasta)
        return sessao["acesso"]

    try:
        corpo = rest.renovar(sessao["renovacao"])
    except rest.SemRede:
        # Sem servidor para perguntar: vale enquanto o prazo do token durar.
        if _quando_vence(sessao.get("acesso", "")) > time.time():
            return sessao["acesso"]
        raise rest.PrecisaEntrar(
            "sem internet e a sessão salva venceu — conecte-se para entrar")
    except rest.PrecisaEntrar:
        esquecer(pasta)                  # não vale mais; não insista amanhã
        raise

    novo = {"acesso": corpo["access_token"],
            "renovacao": corpo["refresh_token"],
            "email": sessao.get("email") or _email(corpo["access_token"])}
    _gravar(_com_perfil(novo, sessao), pasta)
    return novo["acesso"]


def tem_sessao(pasta=None) -> bool:
    """Há sessão salva? Não diz se ela ainda vale — para isso, `token()`."""
    return _ler(pasta) is not None


def quem(pasta=None) -> Quem:
    """Quem está usando: e-mail, nome, papel e situação. Vazio se ninguém.

    Lê só o arquivo local — nunca a rede. O papel foi guardado ali por
    `entrar()` ou pela renovação; ver o cabeçalho do módulo."""
    guardada = _ler(pasta) or {}
    return Quem(email=guardada.get("email", "") or "",
                nome=guardada.get("nome", "") or "",
                papel=guardada.get("papel", "") or "",
                situacao=guardada.get("situacao", "") or "",
                # Sessão de versão anterior não tem `user_id` gravado, mas o
                # token dela tem: é o mesmo valor, e lê-lo de lá evita pedir
                # a senha de novo só para saber o número de alguém.
                user_id=(guardada.get("user_id")
                         or _sub(guardada.get("acesso", ""))))


def reconferir(pasta=None) -> Quem:
    """Pergunta o perfil ao servidor de novo e guarda o que vier.

    Serve à tela de espera: o admin acabou de liberar a conta, e ter de fechar
    e abrir o app para descobrir isso é o tipo de coisa que vira telefonema.

    Sem sessão salva não há a quem perguntar — devolve vazio em vez de
    levantar, porque quem chama está desenhando uma tela, não gravando nada."""
    guardada = _ler(pasta)
    if not guardada:
        return Quem()
    _gravar(_com_perfil(dict(guardada), guardada), pasta)
    return quem(pasta)


def esquecer(pasta=None) -> None:
    """Apaga a sessão local. Não fala com o servidor."""
    try:
        _caminho(pasta).unlink()
    except OSError:
        pass


def sair(pasta=None) -> None:
    """Encerra a sessão aqui e no servidor."""
    sessao = _ler(pasta)
    if sessao:
        rest.sair(sessao.get("acesso", ""))
    esquecer(pasta)
