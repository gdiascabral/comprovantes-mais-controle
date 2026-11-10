"""GET de dentro da página cortado pela navegação (10/11/2026): repete uma vez."""
import pytest

from anexar import mc_api


class _Pagina:
    def __init__(self, erros):
        self.erros, self.chamadas, self.esperas = list(erros), 0, []

    def evaluate(self, js, args):
        self.chamadas += 1
        if self.erros:
            raise self.erros.pop(0)
        return {"ok": args["url"]}

    def wait_for_timeout(self, ms):
        self.esperas.append(ms)


def _api(pagina):
    api = mc_api.MCApi.__new__(mc_api.MCApi)
    pagina.on = lambda *_a: None
    api._cliente = type("C", (), {"page": pagina})()
    api._pagina_ouvida = pagina
    return api


def test_failed_to_fetch_repete_uma_vez():
    p = _Pagina([RuntimeError("Error: TypeError: Failed to fetch")])
    assert _api(p)._fetch_json("u", {}) == {"ok": "u"}
    assert p.chamadas == 2 and p.esperas == [mc_api.ESPERA_CORRIDA_MS]


def test_contexto_destruido_tambem_repete():
    p = _Pagina([RuntimeError("Execution context was destroyed, most likely because")])
    assert _api(p)._fetch_json("u", {}) == {"ok": "u"}


def test_segunda_falha_sobe():
    p = _Pagina([RuntimeError("Failed to fetch"), RuntimeError("Failed to fetch")])
    with pytest.raises(RuntimeError):
        _api(p)._fetch_json("u", {})
    assert p.chamadas == 2


def test_outro_erro_nao_repete():
    p = _Pagina([RuntimeError("Target page, context or browser has been closed")])
    with pytest.raises(RuntimeError):
        _api(p)._fetch_json("u", {})
    assert p.chamadas == 1
