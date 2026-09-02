# -*- coding: utf-8 -*-
"""A ordem da coleta, e por que ela custava um login a cada rodada.

O ERP aceita UMA sessão por usuário. Lendo os saldos pela API primeiro, a
sessão do navegador cai — e o app tinha de entrar de novo para ler a grade.
Era o "entra, sai, entra" que aparecia no Registro do dono em 18/08/2026.

Aqui se testa só a ORDEM: quem fala com o navegador vem antes de quem fala com
a API. Nada de rede.
"""
from datetime import date
from pathlib import Path

import pytest

class _Pagina:
    url = "https://erp/#/payable-installments"

    def screenshot(self, **_k):
        pass


@pytest.fixture
def espiao(monkeypatch):
    """Registra a ordem em que a coleta chama cada fonte."""
    from conciliacao.erp import collect

    ordem = []
    monkeypatch.setattr(collect, "coletar_contas",
                        lambda *a, **k: (ordem.append("api-saldos"), [])[1])
    monkeypatch.setattr(collect, "ir_para", lambda *a, **k: None)
    monkeypatch.setattr(collect, "_ler_pagamentos",
                        lambda *a, **k: (ordem.append("navegador-grade"),
                                         ([], None))[1])
    return collect, ordem


def _config():
    class _C:
        erp = {"rota_pagamentos": "#/payable-installments"}

        def caminho(self, *_a):
            return Path(".")
    return _C()


def test_navegador_vem_antes_da_api(espiao):
    """A API derruba a sessão do navegador; usá-la por último evita o
    segundo login."""
    collect, ordem = espiao
    collect.coletar_com_pagina(_Pagina(), _config(),
                               data_referencia=date(2026, 8, 18))
    assert ordem == ["navegador-grade", "api-saldos"]


def test_relogin_acontece_depois_de_tudo(espiao):
    """Refazer o login é cortesia para a PRÓXIMA aba, não parte desta coleta."""
    collect, ordem = espiao
    collect.coletar_com_pagina(_Pagina(), _config(),
                               data_referencia=date(2026, 8, 18),
                               revalidar_sessao=lambda: ordem.append("relogin"))
    assert ordem == ["navegador-grade", "api-saldos", "relogin"]


def test_falha_ao_refazer_o_login_nao_derruba_a_coleta(espiao):
    """Nesse ponto a grade e os saldos já foram lidos. Perder tudo porque o
    relogin falhou seria jogar fora trabalho concluído."""
    collect, ordem = espiao

    def _explode():
        raise RuntimeError("chrome fechou")

    snap = collect.coletar_com_pagina(_Pagina(), _config(),
                                      data_referencia=date(2026, 8, 18),
                                      revalidar_sessao=_explode)
    assert snap is not None
    assert ordem == ["navegador-grade", "api-saldos"]
