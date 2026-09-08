# -*- coding: utf-8 -*-
"""A aba da pessoa no Chrome do app, e o defeito do Chrome 152 que ela expôs.

Nasceu em 08/09/2026, do pedido de usar o Mais Controle enquanto o robô
trabalha. O ERP aceita uma sessão por usuário, mas abas do mesmo Chrome
dividem a sessão — então a pessoa pode ter a aba dela no Chrome do app. O que
o app precisa garantir está em `test_sessao_mc.py` (o robô não adota a aba
dela) e aqui: o que ela baixar vai para a Downloads, o botão sabe por onde
abrir a aba, e o Chrome não cai no primeiro download.

O crash: o Chrome 152 (e o Edge 152) morrem com violação de acesso no
PRIMEIRO download de um perfil que já baixou algo numa abertura anterior pelo
Playwright. Foi medido em 08/09/2026 com perfil novo (baixa), o mesmo perfil
reaberto (cai) e o mesmo perfil sem o `History` (baixa de novo). Como o
Inter e o Sicoob baixam em perfis reaproveitados, eles também dependem disto.

Os testes do botão NÃO montam a aba de verdade. Uma `AnexarFrame(raiz)`
construída aqui, antes de `test_registro_visivel.py` medir as telas em outra
escala, deixava o Registro da aba Remessa/Retorno 28 px mais curto a 1,25x —
um teste de lógica não pode custar o resultado de um teste de layout. O que
se quer medir é a decisão de POR ONDE a aba entra, e para isso bastam os
atributos que a decisão lê."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import util


# ------------------------------------------------------------- util
def test_limpar_historico_apaga_so_o_history(tmp_path):
    perfil = tmp_path / "perfil"
    default = perfil / "Default"
    default.mkdir(parents=True)
    (default / "History").write_bytes(b"sqlite")
    (default / "History-journal").write_bytes(b"")
    (default / "Preferences").write_text("{}", encoding="utf-8")
    (default / "Login Data").write_bytes(b"senhas do chrome")

    assert util.limpar_historico_de_downloads(perfil) is True
    assert not (default / "History").exists()
    assert not (default / "History-journal").exists()
    # o resto do perfil (login guardado, preferências) fica intacto
    assert (default / "Preferences").exists()
    assert (default / "Login Data").read_bytes() == b"senhas do chrome"


def test_limpar_historico_de_perfil_novo_nao_estoura(tmp_path):
    """Primeira abertura: não há Default/, não há History — e não há erro."""
    assert util.limpar_historico_de_downloads(tmp_path / "nao_existe") is False


def test_nome_livre_numera_como_o_chrome(tmp_path):
    (tmp_path / "boleto.pdf").write_bytes(b"1")
    (tmp_path / "boleto (1).pdf").write_bytes(b"2")
    assert util.nome_livre(tmp_path, "boleto.pdf").name == "boleto (2).pdf"
    assert util.nome_livre(tmp_path, "outro.pdf").name == "outro.pdf"


def test_pasta_downloads_e_uma_pasta_da_pessoa():
    pasta = util.pasta_downloads()
    assert isinstance(pasta, Path)
    assert pasta.name.lower() == "downloads"


# ------------------------------------------------------- o botão da aba
class _MC:
    def __init__(self, fechado=False):
        self.fechado = fechado


@pytest.fixture
def aba(monkeypatch):
    """Uma AnexarFrame SEM tela: só o que `abrir_minha_aba`, `avisar_se_ocupado`
    e `_pulsar_navegador` leem. `chamadas` registra por onde a aba entrou."""
    pytest.importorskip("playwright")
    from anexar import anexar_comprovantes as modulo

    aba = modulo.AnexarFrame.__new__(modulo.AnexarFrame)
    aba.mc = None
    aba.exec = ThreadPoolExecutor(max_workers=1)
    aba._trabalho_atual = None
    aba._rotulo_atual = None
    aba._pulso_nav = None
    aba._encerrando = False
    aba.registro = []
    aba._log = aba.registro.append
    aba.after = lambda *a, **k: None       # o Tk não está aqui
    aba.chamadas = []
    aba.submeter = lambda rotulo, fn, *a, **k: aba.chamadas.append(("thread", rotulo))
    monkeypatch.setattr(modulo.mc_client, "abrir_aba_por_fora",
                        lambda *a, **k: aba.chamadas.append(("por_fora",)) or True)
    from tkinter import messagebox
    monkeypatch.setattr(messagebox, "showinfo",
                        lambda *a, **k: aba.chamadas.append(("aviso",)))
    try:
        yield aba
    finally:
        aba.exec.shutdown(wait=False)


def test_sem_chrome_a_aba_entra_pela_thread(aba):
    """Chrome fechado: abre o Chrome, entra e aí abre a aba — trabalho da
    thread do navegador, como qualquer outro."""
    aba.abrir_minha_aba()
    assert aba.chamadas == [("thread", "Minha aba no ERP")]


def test_com_o_robo_trabalhando_a_aba_entra_por_fora(aba, monkeypatch):
    """O caso que motivou tudo: a thread está tomada pelo robô, então a aba
    entra pelo chrome.exe, sem esperar."""
    aba.mc = _MC()
    monkeypatch.setattr(aba, "ocupado", lambda: "Anexar — casar e anexar")
    aba.abrir_minha_aba()
    assert aba.chamadas == [("por_fora",)]
    assert any("não feche a janela" in linha for linha in aba.registro)


def test_chrome_fechado_no_x_nao_abre_por_fora(aba, monkeypatch):
    """`fechado` é a trava: por fora, sem Chrome aberto, o chrome.exe abriria
    um Chrome comum no perfil do app — e a abertura seguinte pelo Playwright
    falharia com "perfil em uso". Com a thread ocupada, só resta avisar."""
    aba.mc = _MC(fechado=True)
    monkeypatch.setattr(aba, "ocupado", lambda: "Abrir o Mais Controle")
    aba.abrir_minha_aba()
    assert aba.chamadas == [("aviso",)]


def test_chrome_livre_a_aba_entra_pela_thread(aba):
    aba.mc = _MC()
    aba.abrir_minha_aba()
    assert aba.chamadas == [("thread", "Minha aba no ERP")]


def test_aviso_de_ocupado_oferece_a_aba(aba, monkeypatch):
    """O aviso "Navegador ocupado" passa a perguntar se quer a aba; "sim"
    abre por fora, porque ocupado é justamente o caso do robô trabalhando."""
    from tkinter import messagebox
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    aba.mc = _MC()
    monkeypatch.setattr(aba, "ocupado", lambda: "Conciliação")
    assert aba.avisar_se_ocupado("a Conferência") is True
    assert aba.chamadas == [("por_fora",)]


def test_navegador_livre_nao_avisa_nem_pergunta(aba, monkeypatch):
    from tkinter import messagebox
    monkeypatch.setattr(messagebox, "askyesno",
                        lambda *a, **k: pytest.fail("não devia perguntar"))
    assert aba.avisar_se_ocupado("a Conferência") is False


def test_pulso_nao_conta_como_trabalho_e_para_ao_encerrar(aba):
    """O pulso submete `mc.pulsar` ao executor sem registrar dono: a barra
    lateral não pode acender ● por causa dele. E com `_encerrando` ligado
    (o `fechar()` liga antes de desligar o executor) ele não submete mais."""
    pulsos = []

    class MCPulsante(_MC):
        def pulsar(self):
            pulsos.append(1)

    aba.mc = MCPulsante()
    aba._pulsar_navegador()
    aba._pulso_nav.result(timeout=5)
    assert pulsos == [1]
    assert aba.ocupado() is None
    aba._encerrando = True
    aba._pulsar_navegador()
    assert pulsos == [1]


def test_pulso_espera_o_navegador_ficar_livre(aba, monkeypatch):
    """Com o robô trabalhando, as chamadas dele já entregam os eventos — o
    pulso não entra na fila atrás de uma tarefa de meia hora."""
    aba.mc = _MC()
    monkeypatch.setattr(aba, "ocupado", lambda: "Anexar — casar e anexar")
    aba._pulsar_navegador()
    assert aba._pulso_nav is None
