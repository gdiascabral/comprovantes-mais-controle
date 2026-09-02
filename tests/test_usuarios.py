# -*- coding: utf-8 -*-
"""Quem entra no app, e o que cada um alcança — a regra e a tela.

O que estes testes seguram tem dois lados que não podem se soltar um do
outro: o que a tela ESCONDE e o que o banco NEGA. Esconder sem negar é
teatro; negar sem esconder é uma tela cheia de botões que respondem "não".
A parte do banco está em `test_rls_supabase.py`; aqui está a de cima.

E há um caminho sem volta no meio: o administrador que se rebaixa ou se
desativa fecha a porta desta tela por dentro. Ninguém mais aprova ninguém, e
o conserto passa a exigir SQL no painel do Supabase — que é exatamente o que
estas quatro fases existem para não precisar mais.
"""

import pytest

from nuvem import rest, usuarios
from nuvem import usuarios_frame


def _u(uid, nome="", email="", papel="operador", situacao="ativo"):
    return usuarios.Usuario(user_id=uid, nome=nome, email=email or f"{uid}@x.com",
                            papel=papel, situacao=situacao)


# ------------------------------------------------------------------ a lista

def test_a_fila_vem_primeiro(monkeypatch):
    """Quem espera é o motivo desta tela existir; quem foi desligado só
    continua na lista para a auditoria ter a quem associar o que já foi
    feito."""
    monkeypatch.setattr(rest, "ler", lambda *_a, **_k: [
        {"user_id": "3", "nome": "Zulmira Ativa", "situacao": "ativo"},
        {"user_id": "4", "nome": "Ana Fora", "situacao": "desativado"},
        {"user_id": "1", "nome": "Bruno Espera", "situacao": "pendente"},
        {"user_id": "2", "nome": "Ana Espera", "situacao": "pendente"},
    ])
    assert [u.nome for u in usuarios.listar("tok")] == [
        "Ana Espera", "Bruno Espera", "Zulmira Ativa", "Ana Fora"]


def test_conta_sem_nome_aparece_pelo_email():
    """Conta criada antes da tela de cadastro não tem nome: o backfill só
    tinha o e-mail para copiar."""
    assert _u("1", email="fulano@exemplo.com").como_chamar == "fulano"
    assert _u("1", nome="  Fulano De Tal  ").como_chamar == "Fulano De Tal"


# ---------------------------------------------------------------- as ações

def _espiar(monkeypatch, resposta=None):
    """Guarda o que foi mandado ao PostgREST, sem rede nenhuma."""
    pedido = {}

    def falso(tabela, token, filtro, mudancas):
        pedido.update(tabela=tabela, filtro=filtro, mudancas=mudancas)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta if resposta is not None else [
            dict({"user_id": "2"}, **mudancas)]
    monkeypatch.setattr(rest, "alterar", falso)
    return pedido


def test_aprovar_libera_e_da_o_papel_de_uma_vez(monkeypatch):
    """São uma decisão só: liberar sem dizer o que a pessoa faz deixaria uma
    conta ativa com o papel padrão, que não foi escolhido por ninguém."""
    pedido = _espiar(monkeypatch)
    usuarios.aprovar("tok", "2", "aprovador")
    assert pedido["filtro"] == "user_id=eq.2"
    assert pedido["mudancas"] == {"situacao": "ativo", "papel": "aprovador"}


def test_papel_inventado_nao_chega_ao_banco(monkeypatch):
    """O check da tabela também recusa — mas errar aqui é mais barato, e a
    mensagem diz o nome do papel."""
    _espiar(monkeypatch)
    for chamar in (usuarios.aprovar, usuarios.mudar_papel):
        with pytest.raises(ValueError):
            chamar("tok", "2", "aprovadaor")


def test_desativar_nao_apaga(monkeypatch):
    """A linha fica: é ela que responde "quem era este user_id?" quando
    alguém olhar a auditoria de três meses atrás."""
    pedido = _espiar(monkeypatch)
    usuarios.desativar("tok", "2")
    assert pedido["mudancas"] == {"situacao": "desativado"}


def test_alteracao_que_nao_alcancou_ninguem_e_erro(monkeypatch):
    """PATCH que não pega linha nenhuma volta 200 com lista vazia. Sem este
    erro, a tela diria "pronto" para uma aprovação que não houve."""
    _espiar(monkeypatch, resposta=[])
    with pytest.raises(rest.RecusadoPeloBanco):
        usuarios.aprovar("tok", "2", "operador")


def test_sem_user_id_nao_vira_alteracao_sem_filtro(monkeypatch):
    _espiar(monkeypatch)
    with pytest.raises(ValueError):
        usuarios.desativar("tok", "")


# --------------------------------------------------- o caminho sem volta

def test_o_ultimo_admin_nao_pode_se_rebaixar_nem_se_desligar():
    lista = [_u("1", "A Admin", papel="admin"), _u("2", "B Operador")]
    assert not usuarios.sobraria_admin(lista, "1", papel="operador")
    assert not usuarios.sobraria_admin(lista, "1", situacao="desativado")


def test_com_dois_admins_um_pode_sair():
    lista = [_u("1", papel="admin"), _u("2", papel="admin"), _u("3")]
    assert usuarios.sobraria_admin(lista, "1", papel="operador")
    assert usuarios.sobraria_admin(lista, "1", situacao="desativado")


def test_admin_desativado_nao_conta_como_admin():
    """Quem barra é a SITUAÇÃO, não o papel — a mesma regra do banco."""
    lista = [_u("1", papel="admin", situacao="desativado"),
             _u("2", papel="admin")]
    assert not usuarios.sobraria_admin(lista, "2", papel="operador")


def test_promover_alguem_sempre_sobra_admin():
    lista = [_u("1", papel="admin"), _u("2")]
    assert usuarios.sobraria_admin(lista, "2", papel="admin")


# ------------------------------------------------------- o menu por papel

def test_o_aprovador_ve_duas_abas():
    """Ele entra para conferir e liberar a remessa do dia. Nove rotinas na
    frente dele é convite ao clique errado numa tela que mexe com pagamento."""
    todas = ["ini", "sep", "anx", "conf", "apt", "rel", "pag", "ext", "con",
             "ctr", "acs"]
    assert usuarios.abas_do_papel("aprovador", todas) == ("ini", "pag")


@pytest.mark.parametrize("papel", ["admin", "operador"])
def test_admin_e_operador_veem_tudo(papel):
    todas = ["ini", "sep", "pag"]
    assert usuarios.abas_do_papel(papel, todas) == tuple(todas)


def test_papel_desconhecido_ve_tudo():
    """Situação vazia quer dizer "não deu para perguntar ao servidor". Nesse
    caso o certo é o app seguir como sempre foi — quem nega o dado é a RLS."""
    todas = ["ini", "sep", "pag"]
    assert usuarios.abas_do_papel("", todas) == tuple(todas)


# --------------------------------------------------------------- a tela

@pytest.fixture
def sem_thread(monkeypatch):
    """A tela roda a rede noutra thread. Aqui ela roda na mesma, para o teste
    não depender de tempo — foi um teste que dependia de tempo que passou
    meses falhando sozinho."""
    class Agora:
        def __init__(self, target=None, daemon=None):
            self._alvo = target

        def start(self):
            self._alvo()
    monkeypatch.setattr(usuarios_frame.threading, "Thread", Agora)


@pytest.fixture
def tela(raiz, monkeypatch, sem_thread):
    """A tela montada, com a lista abaixo e sem servidor nenhum."""
    lista = [_u("1", "Ana Espera", situacao="pendente"),
             _u("9", "Gustavo Admin", papel="admin"),
             _u("5", "Bento Operador")]
    monkeypatch.setattr(usuarios, "listar", lambda _t: list(lista))
    quadro = usuarios_frame.UsuariosFrame(
        raiz, lambda: "tok", eu=_u("9", "Gustavo Admin", papel="admin"))
    quadro._drenar()                     # aplica a lista que já está na fila
    yield quadro, lista
    quadro.destroy()


def _linhas(quadro):
    return [quadro.tabela.item(i, "values") for i in
            quadro.tabela.get_children()]


def _escolher(quadro, iid):
    """Seleciona pela tabela, e não chamando `_escolheu` na mão.

    `selection_set` ENFILEIRA o `<<TreeviewSelect>>` em vez de dispará-lo, e
    sem o `update` a tela não fica sabendo — que é justamente o caminho que
    este teste existe para exercitar."""
    quadro.tabela.selection_set(iid)
    quadro.update()


def test_a_tela_mostra_quem_espera_no_topo(tela):
    quadro, _lista = tela
    linhas = _linhas(quadro)
    assert len(linhas) == 3
    assert linhas[0][0] == "Ana Espera"
    assert "esperando" in linhas[0][3]
    assert "esperando liberação" in quadro.rodape.resumo.cget("text")


def test_sem_ninguem_escolhido_nenhum_botao_acende(tela):
    quadro, _lista = tela
    for botao in (quadro.b_aprovar, quadro.b_papel, quadro.b_desativar):
        assert str(botao.cget("state")) == "disabled"


def test_aprovar_so_acende_para_quem_espera(tela):
    quadro, _lista = tela
    _escolher(quadro, "1")               # Ana, pendente
    assert str(quadro.b_aprovar.cget("state")) == "normal"
    assert str(quadro.b_papel.cget("state")) == "disabled"
    _escolher(quadro, "5")               # Bento, já ativo
    assert str(quadro.b_aprovar.cget("state")) == "disabled"
    assert str(quadro.b_papel.cget("state")) == "normal"


def test_aprovar_manda_o_papel_escolhido(tela, monkeypatch):
    """O critério de pronto da fase 4, do lado da tela."""
    quadro, _lista = tela
    pedido = {}
    monkeypatch.setattr(usuarios, "aprovar",
                        lambda t, uid, papel: pedido.update(uid=uid,
                                                            papel=papel))
    _escolher(quadro, "1")
    quadro.combo.set("Aprovador")
    quadro.b_aprovar.invoke()
    quadro._drenar()
    assert pedido == {"uid": "1", "papel": "aprovador"}
    assert "aprovador" in quadro.aviso.cget("text").lower()


def test_o_ultimo_admin_nao_se_rebaixa_pela_tela(tela, monkeypatch):
    """E a frase diz o que aconteceria, não só "não pode": quem lê precisa
    saber que a saída é promover outra pessoa antes."""
    quadro, _lista = tela
    monkeypatch.setattr(usuarios, "mudar_papel", lambda *_a: pytest.fail(
        "não devia ter chamado o servidor"))
    _escolher(quadro, "9")               # o próprio, único admin
    quadro.combo.set("Operador")
    quadro.b_papel.invoke()
    recado = quadro.aviso.cget("text")
    assert "sem nenhum administrador" in recado
    assert "Promova outra pessoa" in recado


def test_o_ultimo_admin_nao_se_desativa_pela_tela(tela, monkeypatch):
    quadro, _lista = tela
    monkeypatch.setattr(usuarios, "desativar", lambda *_a: pytest.fail(
        "não devia ter chamado o servidor"))
    _escolher(quadro, "9")
    quadro.b_desativar.invoke()
    assert "sem nenhum administrador" in quadro.aviso.cget("text")


def test_falha_do_servidor_vira_frase_e_nao_traceback(tela, monkeypatch):
    quadro, _lista = tela

    def caiu(*_a):
        raise rest.SemRede("dns")
    monkeypatch.setattr(usuarios, "aprovar", caiu)
    _escolher(quadro, "1")
    quadro.combo.set("Operador")
    quadro.b_aprovar.invoke()
    quadro._drenar()
    assert "Sem internet" in quadro.aviso.cget("text")


def test_sem_token_a_tela_nao_finge_que_tentou(raiz, monkeypatch, sem_thread):
    """Token vazio quer dizer que a sessão não deu para renovar agora. Chamar
    assim mesmo traria um 401 traduzido como "sua conta perdeu a permissão de
    administrador", que é uma acusação falsa."""
    monkeypatch.setattr(usuarios, "listar", lambda _t: pytest.fail(
        "não devia ter chamado o servidor sem token"))
    quadro = usuarios_frame.UsuariosFrame(raiz, lambda: "", eu=None)
    assert "Sem sessão" in quadro.aviso.cget("text")
    quadro.destroy()
