# -*- coding: utf-8 -*-
"""A aba Água e energia: dispara, acompanha, mostra o resumo e registra."""
from pathlib import Path

from concessionarias import frame as F
from concessionarias import rodada as R


class _Proc:
    def __init__(self, codigos):
        self._codigos = list(codigos)

    def poll(self):
        return self._codigos.pop(0) if self._codigos else 0


def _instalacao(tmp_path) -> Path:
    raiz = tmp_path / "agua_energia"
    (raiz / "coletor" / "logs").mkdir(parents=True)
    (raiz / "relatorios").mkdir()
    (raiz / "coletor" / "rodada_diaria.bat").write_text("@echo off\n")
    return raiz


def _aba(raiz_tk, pasta, **kw):
    chamadas = {"iniciar": [], "registrar": [], "perguntar": []}

    def iniciar(p, *, so, origem):
        chamadas["iniciar"].append((p, so, origem))
        return kw.pop("_proc", _Proc([None, 0]))

    def registrar(acao, detalhe="", **k):
        chamadas["registrar"].append((acao, detalhe, k))

    def perguntar(titulo, texto):
        chamadas["perguntar"].append(texto)
        return kw.pop("_resposta", True)

    aba = F.AguaEnergiaFrame(raiz_tk, None if "anx" not in kw else kw.pop("anx"),
                             pasta=pasta, iniciar=iniciar, registrar=registrar,
                             perguntar=perguntar,
                             central_ligado=kw.pop("central_ligado", lambda: True),
                             quem=lambda: "Fulano")
    return aba, chamadas


def test_sem_instalacao_o_botao_fica_desligado(raiz):
    aba, ch = _aba(raiz, None)
    assert str(aba.b_rodar["state"]) == "disabled"
    assert "não está instalado" in aba.v_status.get()
    aba.rodar()
    assert ch["iniciar"] == []


def test_dispara_acompanha_e_mostra_o_resumo(raiz, tmp_path):
    pasta = _instalacao(tmp_path)
    resumo = pasta / "relatorios" / "rodada_teste.txt"
    resumo.write_text("=== RODADA ===\nsaúde: sem alertas\n", encoding="utf-8")
    aba, ch = _aba(raiz, pasta, _proc=_Proc([None, 0]))
    aba.v_so.set("equatorial")
    aba.rodar()
    assert ch["iniciar"] == [(pasta, "equatorial", "app: Fulano")]
    assert aba.ocupado()
    with open(R.caminho_do_log(pasta), "a", encoding="utf-8") as f:
        f.write("[2/4] Equatorial:\n")
    aba._acompanhar()                                  # poll -> None: segue
    assert "[2/4] Equatorial:" in aba.log.get("1.0", "end")
    with open(R.caminho_do_log(pasta), "a", encoding="utf-8") as f:
        f.write(f"resumo salvo em {resumo}\n")
    aba._acompanhar()                                  # poll -> 0: terminou
    assert aba.ocupado() is None
    assert "saúde: sem alertas" in aba.resumo.get("1.0", "end")
    assert "sem alertas" in aba.v_status.get()
    acoes = [a for a, _, _ in ch["registrar"]]
    assert acoes == ["Água e energia: rodada disparada", "Água e energia: rodada terminou"]
    assert "--so equatorial" in ch["registrar"][0][1]


def test_recusada_porque_ja_havia_outra(raiz, tmp_path):
    pasta = _instalacao(tmp_path)
    aba, ch = _aba(raiz, pasta, _proc=_Proc([R.CODIGO_OCUPADA]))
    aba.rodar()
    aba._acompanhar()
    assert "já estava em andamento" in aba.v_status.get()
    assert ch["registrar"][-1][2].get("resultado") == "aviso"


def test_central_desligado_e_anexar_ocupado_recusa(raiz, tmp_path):
    class _Anx:
        def ocupado(self):
            return "Anexando comprovantes"

    aba, ch = _aba(raiz, _instalacao(tmp_path), anx=_Anx(),
                   central_ligado=lambda: False)
    aba.rodar()
    assert ch["iniciar"] == [] and ch["perguntar"] == []
    assert "Anexando comprovantes" in aba.v_status.get()


def test_central_desligado_pede_confirmacao(raiz, tmp_path):
    aba, ch = _aba(raiz, _instalacao(tmp_path), central_ligado=lambda: False,
                   _resposta=False)
    aba.rodar()
    assert ch["iniciar"] == []
    assert "sessão" in ch["perguntar"][0]


def test_central_ligado_nao_pergunta(raiz, tmp_path):
    aba, ch = _aba(raiz, _instalacao(tmp_path))
    aba.rodar()
    assert ch["perguntar"] == [] and len(ch["iniciar"]) == 1


def test_ao_abrir_mostra_a_rodada_dos_outros(raiz, tmp_path, monkeypatch):
    pasta = _instalacao(tmp_path)
    monkeypatch.setattr(F.rodada, "em_andamento",
                        lambda p: {"origem": "agendada", "inicio": "2026-10-14T05:30:00"})
    aba, ch = _aba(raiz, pasta)
    aba.ao_abrir()
    assert "agendada" in aba.v_status.get()
    aba.rodar()
    assert ch["iniciar"] == []                          # não dispara a segunda
