# -*- coding: utf-8 -*-
"""`util.fotografar`: o print é prova, não leitura — falhar não levanta."""
from pathlib import Path

import util


class _Alvo:
    def __init__(self, erro=None):
        self.erro, self.caminhos = erro, []

    def screenshot(self, path):
        if self.erro:
            raise self.erro
        self.caminhos.append(path)
        Path(path).write_bytes(b"png")


def test_fotografar_grava_e_devolve_vazio(tmp_path):
    arquivo = tmp_path / "sub" / "a.png"
    assert util.fotografar(_Alvo(), arquivo) == ""
    assert arquivo.read_bytes() == b"png"


def test_fotografar_que_falha_diz_por_que_e_nao_levanta(tmp_path):
    motivo = util.fotografar(_Alvo(RuntimeError("Target closed\nmais coisa")), tmp_path / "a.png")
    assert motivo == "o print não saiu (Target closed)"


def test_fotografar_com_recorte_passa_o_clip(tmp_path):
    recebidos = []

    class _Pagina:
        def screenshot(self, path, clip=None):
            recebidos.append(clip)
            Path(path).write_bytes(b"png")

    clip = {"x": 0, "y": 10, "width": 100, "height": 50}
    assert util.fotografar(_Pagina(), tmp_path / "a.png", clip=clip) == ""
    assert recebidos == [clip]


class _Olho:
    def __init__(self, ha=1, erro=None):
        self.ha, self.erro, self.cliques, self.esperas = ha, erro, 0, []

    def locator(self, sel):
        return self

    @property
    def first(self):
        return self

    def count(self):
        return self.ha

    def click(self):
        if self.erro:
            raise self.erro
        self.cliques += 1

    def wait_for_timeout(self, ms):
        self.esperas.append(ms)


def test_revelar_clica_no_olho_so_com_seletor_e_nunca_levanta():
    assert util.revelar(object(), "") is False          # vazio: nem toca na página
    pag = _Olho()
    assert util.revelar(pag, "#olho") is True and pag.cliques == 1 and pag.esperas
    assert util.revelar(_Olho(ha=0), "#olho") is False
    assert util.revelar(_Olho(erro=RuntimeError("detached")), "#olho") is False
