# -*- coding: utf-8 -*-
"""As duas janelas que aparecem ANTES do app: entrar/criar conta, e a espera.

São as únicas telas que uma pessoa nova vê, e as duas rodam antes de existir
qualquer aba — um erro de digitação aqui não aparece num log, aparece como app
que não abre. Por isso o teste monta as janelas de verdade e mexe nelas, em vez
de conferir só as funções por trás.

O truque para elas não travarem o teste: `pedir_login` termina em
`root.wait_window(dlg)`, e é ele quem segura. Trocando esse método por um que
inspeciona e fecha, a janela é construída inteira — que é justamente a parte
que pode quebrar.
"""
import sys
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))

from nuvem import login_dialogo, rest, sessao  # noqa: E402


def _todos(pai):
    """Todo widget da janela, em qualquer profundidade."""
    for filho in pai.winfo_children():
        yield filho
        yield from _todos(filho)


def _por_tipo(pai, nome_da_classe):
    return [w for w in _todos(pai)
            if w.winfo_class() == nome_da_classe]


def _botao(pai, texto):
    for w in _todos(pai):
        if w.winfo_class() == "TButton" and texto in str(w.cget("text")):
            return w
    raise AssertionError(f"não achei o botão {texto!r}")


def _abrir(raiz, monkeypatch, funcao, pasta, inspecionar):
    """Roda uma das duas janelas, deixa o teste olhar, e fecha."""
    guardado = {}

    def em_vez_de_esperar(dlg):
        try:
            guardado["visto"] = inspecionar(dlg)
        finally:
            dlg.destroy()
    monkeypatch.setattr(raiz, "wait_window", em_vez_de_esperar)
    funcao(raiz, pasta)
    return guardado.get("visto")


# ------------------------------------------------------------ entrar/criar

def test_a_janela_de_login_tem_as_duas_abas(raiz, monkeypatch, tmp_path):
    """Sem sessão salva, `pedir_login` monta a janela inteira — e é a única
    tela que uma pessoa sem conta alcança."""
    def olhar(dlg):
        cadernos = _por_tipo(dlg, "TNotebook")
        assert len(cadernos) == 1, "a janela devia ter um caderno de abas"
        caderno = cadernos[0]
        return [caderno.tab(i, "text").strip()
                for i in range(caderno.index("end"))]

    abas = _abrir(raiz, monkeypatch, login_dialogo.pedir_login, tmp_path, olhar)
    assert abas == ["Entrar", "Criar conta"]


def test_criar_conta_confere_antes_de_viajar(raiz, monkeypatch, tmp_path):
    """Nome pela metade, e-mail torto, senha curta e senha repetida errada são
    pegos aqui: a viagem à toa é a de menos, mas senha digitada errada em
    campo escondido vira conta que ninguém abre."""
    def falar_com_o_servidor(*_a, **_k):
        raise AssertionError("não devia ter chamado o servidor")
    monkeypatch.setattr(rest, "criar_conta", falar_com_o_servidor)

    def olhar(dlg):
        campos = _por_tipo(dlg, "TEntry")
        # dois na aba Entrar, quatro na de criar conta
        assert len(campos) == 6
        nome, email, senha, repete = campos[2], campos[3], campos[4], campos[5]
        criar = _botao(dlg, "Criar conta")
        recados = []

        def tentar(v_nome, v_email, v_senha, v_repete):
            for campo, valor in ((nome, v_nome), (email, v_email),
                                 (senha, v_senha), (repete, v_repete)):
                campo.delete(0, "end")
                campo.insert(0, valor)
            criar.invoke()
            avisos = [str(w.cget("text")) for w in _todos(dlg)
                      if w.winfo_class() == "TLabel"
                      and str(w.cget("style")) == "Erro.TLabel"]
            recados.append(" ".join(a for a in avisos if a.strip()))

        tentar("", "", "", "")
        tentar("Fulano", "f@x.com", "uma-senha-boa", "uma-senha-boa")
        tentar("Fulano De Tal", "sem-arroba", "uma-senha-boa", "uma-senha-boa")
        tentar("Fulano De Tal", "f@x.com", "curta", "curta")
        tentar("Fulano De Tal", "f@x.com", "uma-senha-boa", "outra-senha")
        return recados

    vazio, so_nome, email, curta, diferentes = _abrir(
        raiz, monkeypatch, login_dialogo.pedir_login, tmp_path, olhar)
    assert "Preencha" in vazio
    assert "nome completo" in so_nome
    assert "e-mail" in email
    assert "8" in curta
    assert "não são iguais" in diferentes


def test_conta_criada_manda_abrir_o_email(raiz, monkeypatch, tmp_path):
    """A pessoa não entra por ter criado a conta: falta confirmar o endereço,
    e depois falta o administrador liberar. As duas coisas têm de estar na
    tela, senão ela fica esperando um app que não vai abrir."""
    pedido = {}

    def aceitar(nome, email, senha):
        pedido.update(nome=nome, email=email, senha=senha)
        return True                      # ainda falta confirmar o e-mail
    monkeypatch.setattr(rest, "criar_conta", aceitar)

    def olhar(dlg):
        campos = _por_tipo(dlg, "TEntry")
        for campo, valor in zip(campos[2:], ("Fulano De Tal", "f@x.com",
                                             "uma-senha-boa", "uma-senha-boa")):
            campo.delete(0, "end")
            campo.insert(0, valor)
        _botao(dlg, "Criar conta").invoke()
        return " ".join(str(w.cget("text")) for w in _todos(dlg)
                        if w.winfo_class() == "TLabel"
                        and str(w.cget("style")) == "Ok.TLabel")

    recado = _abrir(raiz, monkeypatch, login_dialogo.pedir_login, tmp_path,
                    olhar)
    assert pedido == {"nome": "Fulano De Tal", "email": "f@x.com",
                      "senha": "uma-senha-boa"}
    assert "f@x.com" in recado, "tem de dizer QUAL caixa de e-mail abrir"
    assert "liberado" in recado or "administrador" in recado


def test_recusa_do_servidor_aparece_como_frase(raiz, monkeypatch, tmp_path):
    """A frase vem pronta do `rest`: é lá que se sabe o que o GoTrue disse."""
    monkeypatch.setattr(rest, "criar_conta", lambda *_a: (_ for _ in ()).throw(
        rest.RecusadoPeloBanco("O cadastro de contas novas está desligado")))

    def olhar(dlg):
        campos = _por_tipo(dlg, "TEntry")
        for campo, valor in zip(campos[2:], ("Fulano De Tal", "f@x.com",
                                             "uma-senha-boa", "uma-senha-boa")):
            campo.delete(0, "end")
            campo.insert(0, valor)
        _botao(dlg, "Criar conta").invoke()
        return " ".join(str(w.cget("text")) for w in _todos(dlg)
                        if w.winfo_class() == "TLabel"
                        and str(w.cget("style")) == "Erro.TLabel")

    recado = _abrir(raiz, monkeypatch, login_dialogo.pedir_login, tmp_path,
                    olhar)
    assert "desligado" in recado


# --------------------------------------------------------------- a espera

@pytest.fixture
def pendente(monkeypatch):
    monkeypatch.setattr(sessao, "quem", lambda _p=None: sessao.Quem(
        email="novo@exemplo.com", nome="Fulano De Tal",
        papel="operador", situacao="pendente"))


def test_a_tela_de_espera_diz_quem_entrou_e_o_que_falta(raiz, monkeypatch,
                                                        tmp_path, pendente):
    def olhar(dlg):
        return " ".join(str(w.cget("text")) for w in _todos(dlg)
                        if w.winfo_class() == "TLabel")

    texto = _abrir(raiz, monkeypatch, login_dialogo.avisar_que_espera,
                   tmp_path, olhar)
    assert "novo@exemplo.com" in texto, "quem está esperando precisa se ver"
    assert "administrador" in texto


def test_conferir_de_novo_abre_o_app_quando_a_liberacao_sai(
        raiz, monkeypatch, tmp_path, pendente):
    """Liberaram agora: fechar e abrir o app para descobrir vira telefonema."""
    monkeypatch.setattr(sessao, "reconferir", lambda _p=None: sessao.Quem(
        email="novo@exemplo.com", papel="operador", situacao="ativo"))

    # Aqui o `_abrir` não serve: quem fecha a janela é o próprio botão, e é
    # justamente isso que se quer ver acontecer.
    guardado = {}

    def em_vez_de_esperar(dlg):
        _botao(dlg, "Conferir de novo").invoke()
        guardado["fechou"] = not dlg.winfo_exists()
        if dlg.winfo_exists():
            dlg.destroy()
    monkeypatch.setattr(raiz, "wait_window", em_vez_de_esperar)
    assert login_dialogo.avisar_que_espera(raiz, tmp_path) is True
    assert guardado["fechou"], "liberada, a janela tinha de se fechar sozinha"


def test_conferir_de_novo_sem_liberacao_continua_esperando(
        raiz, monkeypatch, tmp_path, pendente):
    monkeypatch.setattr(sessao, "reconferir", lambda _p=None: sessao.Quem(
        email="novo@exemplo.com", papel="operador", situacao="pendente"))

    def olhar(dlg):
        _botao(dlg, "Conferir de novo").invoke()
        return " ".join(str(w.cget("text")) for w in _todos(dlg)
                        if w.winfo_class() == "TLabel"
                        and str(w.cget("style")) == "Erro.TLabel")

    recado = _abrir(raiz, monkeypatch, login_dialogo.avisar_que_espera,
                    tmp_path, olhar)
    assert "Ainda não" in recado


def test_conta_desativada_nao_ganha_botao_de_conferir(raiz, monkeypatch,
                                                      tmp_path):
    """Desativada não é "espere um pouco": é uma decisão tomada. Um botão de
    conferir aqui só convidaria a insistir."""
    monkeypatch.setattr(sessao, "quem", lambda _p=None: sessao.Quem(
        email="exfuncionario@exemplo.com", papel="operador",
        situacao="desativado"))

    def olhar(dlg):
        return [str(w.cget("text")) for w in _todos(dlg)
                if w.winfo_class() == "TButton"]

    botoes = _abrir(raiz, monkeypatch, login_dialogo.avisar_que_espera,
                    tmp_path, olhar)
    assert not any("Conferir" in b for b in botoes)
    assert any("Sair do app" in b for b in botoes)


def test_entrar_com_outra_conta_esquece_a_sessao(raiz, monkeypatch, tmp_path,
                                                 pendente):
    """Entrou com a conta errada: a próxima abertura tem de perguntar de novo."""
    esqueceu = {"sim": False}
    monkeypatch.setattr(sessao, "esquecer",
                        lambda _p=None: esqueceu.__setitem__("sim", True))

    def em_vez_de_esperar(dlg):
        _botao(dlg, "Entrar com outra conta").invoke()
        if dlg.winfo_exists():
            dlg.destroy()
    monkeypatch.setattr(raiz, "wait_window", em_vez_de_esperar)
    assert login_dialogo.avisar_que_espera(raiz, tmp_path) is False
    assert esqueceu["sim"]
