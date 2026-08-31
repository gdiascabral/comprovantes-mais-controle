# -*- coding: utf-8 -*-
"""A trava do banco, lida das migrations — sem precisar de um Postgres.

Por que isto existe, e por que agora: até 30/08/2026 o auto-cadastro estava
DESLIGADO no projeto Supabase, e era ele quem segurava a porta. A chave `anon`
está no código, o código está num repositório público, e a única razão pela
qual um estranho não conseguia um token de `authenticated` era não haver como
se cadastrar.

A fase 3 ligou o auto-cadastro. A partir dela, "está autenticado" deixou de
significar "trabalha aqui", e toda política que dizia `using (true)` virou uma
porta aberta para qualquer pessoa do mundo — o cadastro da empresa, o que foi
pago e a quem, e até o contador de NSA das remessas.

Estes testes não conferem o banco: conferem o que as migrations MANDAM. É de
propósito. O que eles pegam é o defeito que ninguém vê chegando — alguém
escreve uma política nova daqui a dois meses, copia o `using (true)` da linha
de cima, e o buraco reabre em silêncio.
"""
import re
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent
_MIGRACOES = sorted((_RAIZ / "supabase" / "migrations").glob("*.sql"))

#: As duas tabelas de fora, e o motivo: quem está PENDENTE precisa ler o
#: próprio perfil (é assim que o app sabe dizer "aguardando liberação") e
#: precisa gravar a própria linha de auditoria (é o que põe a pessoa na fila
#: que o admin olha). Nenhuma das duas dá acesso a dado da empresa: as
#: políticas delas já filtram por `auth.uid()`.
FORA = {"public.perfil", "public.auditoria"}

#: A função que responde "esta pessoa foi liberada por um administrador?".
PORTEIRA = "e_ativo"


def _sem_corpo_de_funcao(sql: str) -> str:
    """Tira o miolo dos `$$ ... $$`: lá dentro há `;` que não termina comando."""
    return re.sub(r"\$\$.*?\$\$", " CORPO_DA_FUNCAO ", sql, flags=re.S)


def _comandos():
    """Cada comando SQL das migrations, na ordem em que serão aplicados."""
    for arquivo in _MIGRACOES:
        limpo = _sem_corpo_de_funcao(arquivo.read_text(encoding="utf-8"))
        # Comentário de linha inteira não muda nada e atrapalha o casamento.
        limpo = re.sub(r"--[^\n]*", " ", limpo)
        for comando in limpo.split(";"):
            comando = " ".join(comando.split())
            if comando:
                yield arquivo.name, comando


def _politicas() -> dict:
    """Nome+tabela -> tudo que já foi dito sobre aquela política.

    Vale a ordem: `drop` apaga a história, e um `alter` posterior acrescenta —
    é assim que uma política nascida `using (true)` fica em dia."""
    vivas = {}
    for _arquivo, comando in _comandos():
        achado = re.match(
            r"(create|alter|drop) policy (\w+) on (public\.\w+)",
            comando, re.I)
        if not achado:
            continue
        verbo, nome, tabela = (achado.group(1).lower(), achado.group(2),
                               achado.group(3).lower())
        chave = (nome, tabela)
        if verbo == "drop":
            vivas.pop(chave, None)
        elif verbo == "create":
            vivas[chave] = comando
        else:
            vivas[chave] = vivas.get(chave, "") + " " + comando
    return vivas


def test_ha_migrations_para_conferir():
    """Se o glob quebrar, os testes abaixo passariam sem olhar nada."""
    assert len(_MIGRACOES) >= 10


def test_toda_politica_de_dado_exige_conta_liberada():
    """A conta nova loga — e não alcança nada até um administrador liberar.

    Esconder as abas no app não resolve: a API responde a quem tem token, e o
    app é só um dos jeitos de falar com ela."""
    abertas = [f"{tabela}.{nome}"
               for (nome, tabela), texto in _politicas().items()
               if tabela not in FORA and PORTEIRA not in texto]
    assert not abertas, (
        "estas políticas deixam entrar qualquer conta autenticada, e desde "
        "que o auto-cadastro foi ligado isso é qualquer pessoa do mundo: "
        + ", ".join(sorted(abertas)))


def test_as_duas_tabelas_de_fora_filtram_por_quem_chama():
    """`perfil` e `auditoria` ficam fora da porteira de propósito — mas não
    ficam abertas: cada um só alcança as próprias linhas."""
    for (nome, tabela), texto in _politicas().items():
        if tabela in FORA:
            assert "auth.uid()" in texto or "e_admin" in texto, (
                f"{tabela}.{nome} não filtra por quem está chamando")


def _ultima_definicao(funcao: str) -> str:
    """O corpo da última vez que a função foi criada — é o que vale no banco."""
    corpo = ""
    for arquivo in _MIGRACOES:
        sql = arquivo.read_text(encoding="utf-8")
        for achado in re.finditer(
                r"create or replace function " + re.escape(funcao)
                + r"\b.*?\$\$(.*?)\$\$", sql, re.S | re.I):
            corpo = achado.group(1)
    return corpo


@pytest.mark.parametrize("funcao", ["public.alocar_nsa",
                                    "public.ajustar_nsa"])
def test_o_contador_de_nsa_so_atende_conta_liberada(funcao):
    """As duas são `security definer`: a RLS não as alcança, e a checagem tem
    de estar dentro delas.

    Queimar NSA de um convênio de verdade não se desfaz sozinho — o número
    pulado só volta por `ajustar_nsa`, com motivo escrito."""
    corpo = _ultima_definicao(funcao)
    assert corpo, f"não achei a definição de {funcao} nas migrations"
    assert PORTEIRA in corpo, (
        f"{funcao} aceita qualquer conta autenticada; desde o auto-cadastro, "
        "isso é qualquer pessoa do mundo")
    assert "auth.uid() is null" not in corpo, (
        f"{funcao} ainda usa a checagem antiga, que só perguntava se havia "
        "alguém logado")


def test_as_funcoes_que_atravessam_a_rls_moram_fora_do_public():
    """`security definer` no `public` vira endpoint do PostgREST.

    Uma função que atravessa a RLS de propósito não pode ser chamável de
    fora. As do `public` (as de NSA) são exceção consciente: elas existem para
    ser chamadas pelo app, e conferem quem chama por dentro."""
    for _arquivo, comando in _comandos():
        achado = re.match(
            r"create (?:or replace )?function (privado|public)\.(\w+)",
            comando, re.I)
        if achado and "security definer" in comando.lower():
            schema, nome = achado.group(1).lower(), achado.group(2)
            if schema == "public":
                assert nome in ("alocar_nsa", "ajustar_nsa"), (
                    f"public.{nome} é security definer e o PostgREST a "
                    "publica como endpoint")


def test_ninguem_apaga_perfil_nem_auditoria():
    """Desligar alguém é `situacao = 'desativado'`, que deixa rastro. Apagar a
    linha levaria junto a resposta de "quem era este user_id na auditoria?"."""
    for (nome, tabela), texto in _politicas().items():
        if tabela in FORA:
            assert " for delete " not in f" {texto} ".lower(), (
                f"{tabela}.{nome} permite apagar")
