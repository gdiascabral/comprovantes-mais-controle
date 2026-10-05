# -*- coding: utf-8 -*-
"""O Chrome do Sicoob abre SEMPRE em português do Brasil.

O Sicoob reconhece o "PC cadastrado" por um retrato que inclui o idioma do
navegador (`navigator.language`). Em 05/10/2026 o perfil do app estava com o
idioma das páginas vazio, o Chrome caiu em pt-PT, e o banco passou a pedir o
cadastro do PC a cada login — provado ao vivo: com pt-PT o "identificar
dispositivo" responde 3 (desconhecido), com pt-BR responde 2 (reconhecido),
mudando só o idioma. Este teste segura o idioma no lugar onde o Chrome nasce,
sem abrir navegador nenhum.
"""
from extratos_sicoob import sicoob_client as sc


class _Contexto:
    pages = []

    def new_page(self):
        return object()

    def set_default_timeout(self, _ms):
        pass


class _Chromium:
    def __init__(self):
        self.kwargs = None

    def launch_persistent_context(self, perfil, **kwargs):
        self.kwargs = kwargs
        return _Contexto()


class _Playwright:
    def __init__(self):
        self.chromium = _Chromium()

    def start(self):
        return self


def test_chrome_do_sicoob_nasce_em_portugues_do_brasil(monkeypatch, tmp_path):
    pw = _Playwright()
    monkeypatch.setattr(sc, "sync_playwright", lambda: pw)
    monkeypatch.setattr(sc.cfg, "PASTA_PERFIL_CHROME", tmp_path / "perfil")
    monkeypatch.setattr(sc.util, "limpar_historico_de_downloads", lambda _p: False)

    cli = sc.SicoobClient(log=lambda *_a, **_k: None)
    cli.__enter__()

    assert pw.chromium.kwargs["locale"] == "pt-BR"
    assert "--lang=pt-BR" in pw.chromium.kwargs["args"]
    # o que já existia continua: extensão do Sicoob ligada, janela maximizada
    assert pw.chromium.kwargs["ignore_default_args"] == ["--disable-extensions"]
    assert "--start-maximized" in pw.chromium.kwargs["args"]
