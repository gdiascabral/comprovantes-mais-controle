# -*- coding: utf-8 -*-
"""O aviso do banco por cima do ⇄ não derruba mais a troca de conta.

Em 20/10/2026 a primeira "Conferir agendamentos" pelo app parou antes da
primeira conta: o login caiu na Home, o clique no ⇄ esperou 45s e estourou,
e as seis contas do Sicoob saíram "não foi lida". Os scripts da prova de
15/10 fechavam o aviso (SweetAlert2) à mão antes do ⇄; o app não. Página
falsa, sem navegador.
"""
from playwright.sync_api import TimeoutError as PWTimeout

from extratos_sicoob import sicoob_client as sc
from pagamentos_dia import agendamentos_sicoob as A


class _Botao:
    def __init__(self, pagina, texto):
        self.pagina, self.texto = pagina, texto

    def inner_text(self, timeout=None):
        return self.texto

    def click(self, timeout=None):
        self.pagina.cliques.append(self.texto)
        self.pagina.avisos.pop(0)


class _Aviso:
    def __init__(self, pagina, texto, botoes):
        self.pagina, self.texto = pagina, texto
        self.botoes = [_Botao(pagina, b) for b in botoes]

    def inner_text(self, timeout=None):
        return self.texto

    def locator(self, _sel):
        return self

    def all(self):
        return self.botoes


class _Loc:
    def __init__(self, itens):
        self.itens = itens

    def count(self):
        return len(self.itens)

    @property
    def first(self):
        return self.itens[0]


class _Teclado:
    def __init__(self, pagina):
        self.pagina = pagina

    def press(self, tecla):
        self.pagina.teclas.append(tecla)
        if tecla == "Escape" and self.pagina.avisos:
            self.pagina.avisos.pop(0)


class _Trocar:
    def __init__(self, pagina):
        self.pagina = pagina

    def click(self, timeout=None):
        self.pagina.cliques.append("⇄")
        if self.pagina.avisos or self.pagina.cabecalho_morto:
            raise PWTimeout("Timeout 10000ms exceeded.\n=== logs ===")
        self.pagina.na_lista = True


class _Pagina:
    def __init__(self, avisos=(), cabecalho_morto=False):
        self.avisos = list(avisos)
        self.cabecalho_morto = cabecalho_morto
        self.na_lista = False
        self.cliques, self.teclas, self.recargas = [], [], 0
        self.keyboard = _Teclado(self)
        self.url = "https://ib.sicoob.com.br/sicoobnet/ib/#/home"

    def locator(self, sel):
        if sel == sc.SEL_AVISO:
            return _Loc(self.avisos)
        if sel == "div.seletor-conta":
            return _Loc([object()] if self.na_lista else [])
        if sel == sc.SEL_TROCAR_CONTA_NOVO:
            return _Loc([_Trocar(self)])
        return _Loc([])

    def wait_for_selector(self, sel, timeout=None):
        if not self.na_lista:
            raise PWTimeout(f"Timeout {timeout}ms exceeded.")

    def wait_for_timeout(self, _ms):
        pass

    def reload(self):
        self.recargas += 1
        self.cabecalho_morto = False

    def goto(self, url):
        raise AssertionError("não devia cair no endereço da seleção")


def _cliente(pagina):
    cli = sc.SicoobClient(log=lambda *_a, **_k: None)
    cli.page = pagina
    return cli


def test_o_aviso_do_banco_e_fechado_pelo_ok_antes_do_trocar_conta():
    p = _Pagina(avisos=[])
    p.avisos.append(_Aviso(p, "Comunicado importante", ["OK"]))
    _cliente(p).ir_para_selecao()
    assert p.cliques == ["OK", "⇄"]
    assert p.na_lista and p.recargas == 0


def test_aviso_sem_botao_de_fechar_vai_por_esc_e_nunca_clica_em_confirmar():
    p = _Pagina()
    p.avisos.append(_Aviso(p, "Deseja assinar agora?", ["Sim", "Assinar"]))
    _cliente(p).ir_para_selecao()
    assert "Sim" not in p.cliques and "Assinar" not in p.cliques
    assert p.teclas == ["Escape"]
    assert p.na_lista


def test_ok_ao_lado_de_cancelar_e_confirmar_e_nao_e_clicado():
    """No SweetAlert2 "OK" é o texto padrão do botão que CONFIRMA."""
    p = _Pagina()
    p.avisos.append(_Aviso(p, "Excluir o agendamento?", ["OK", "Cancelar"]))
    _cliente(p).ir_para_selecao()
    assert "OK" not in p.cliques
    assert p.teclas == ["Escape"]


def test_avisos_empilhados_sao_fechados_um_a_um():
    p = _Pagina()
    p.avisos += [_Aviso(p, "Um", ["Entendi"]), _Aviso(p, "Dois", ["Fechar"])]
    _cliente(p).ir_para_selecao()
    assert p.cliques == ["Entendi", "Fechar", "⇄"]


def test_lista_que_nao_abre_recarrega_a_pagina_e_tenta_de_novo():
    p = _Pagina(cabecalho_morto=True)
    _cliente(p).ir_para_selecao()
    assert p.recargas == 1
    assert p.cliques == ["⇄", "⇄"]
    assert p.na_lista


def test_sessao_que_caiu_nao_e_recarregada():
    p = _Pagina(cabecalho_morto=True)
    p.url = "https://ib.sicoob.com.br/sicoobnet/ib/#/login"
    try:
        _cliente(p).ir_para_selecao()
    except sc.SessaoPerdida:
        pass
    else:
        raise AssertionError("devia dizer que a sessão caiu")
    assert p.recargas == 0


def test_a_tabela_diz_por_que_a_leitura_parou():
    erro = PWTimeout("Timeout 45000ms exceeded.\n=== logs ===\nwaiting …")
    motivo = A.motivo_da_parada(erro)
    assert motivo.startswith(A.MOTIVO_NAO_LIDA)
    assert "Timeout 45000ms exceeded." in motivo
    assert "logs" not in motivo
    # continua vermelha: não foi conferida e é do Sicoob
    assert A.Confronto("C", "12.345-6", motivo=motivo).falhou


def test_erro_sem_texto_fica_com_o_nome_da_excecao_ou_a_frase_de_sempre():
    assert A.motivo_da_parada(RuntimeError()).endswith(": RuntimeError")
    assert A.motivo_da_parada(None) == A.MOTIVO_NAO_LIDA
