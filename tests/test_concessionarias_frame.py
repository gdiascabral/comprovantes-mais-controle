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

    def iniciar(p, *, so, origem, log):
        chamadas["iniciar"].append((p, so, origem))
        chamadas["log"] = log
        if "_erro_iniciar" in kw:
            raise kw["_erro_iniciar"]
        if "_escreve" in kw:
            with open(log, "a", encoding="utf-8") as f:
                f.write(kw["_escreve"])
        return kw.pop("_proc", _Proc([None, 0]))

    def registrar(acao, detalhe="", **k):
        if kw.get("_registrar_quebra"):
            raise RuntimeError("nuvem fora")
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
    with open(ch["log"], "a", encoding="utf-8") as f:
        f.write("[2/4] Equatorial:\n")
    aba._acompanhar()                                  # poll -> None: segue
    assert "[2/4] Equatorial:" in aba.log.get("1.0", "end")
    with open(ch["log"], "a", encoding="utf-8") as f:
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


def test_resumo_nao_e_lido_quando_a_rodada_foi_recusada(raiz, tmp_path):
    pasta = _instalacao(tmp_path)
    resumo = pasta / "relatorios" / "velho.txt"
    resumo.write_text("CONTEUDO DE OUTRA RODADA\n", encoding="utf-8")
    aba, ch = _aba(raiz, pasta, _proc=_Proc([R.CODIGO_OCUPADA]),
                   _escreve=f"resumo salvo em {resumo}\n")
    aba.rodar()
    aba._acompanhar()
    texto = aba.resumo.get("1.0", "end")
    assert "CONTEUDO DE OUTRA RODADA" not in texto
    assert "não rodou" in texto


def test_disparo_e_termino_registram_aba_e_resultado(raiz, tmp_path):
    pasta = _instalacao(tmp_path)
    for rc, esperado in ((0, "ok"), (1, "aviso"), (9009, "erro")):
        aba, ch = _aba(raiz, pasta, _proc=_Proc([rc]))
        aba.rodar()
        aba._acompanhar()
        assert ch["registrar"][0][2] == {"aba": "agu", "resultado": "ok"}
        assert ch["registrar"][-1][2] == {"aba": "agu", "resultado": esperado}


def test_iniciar_que_falha_deixa_a_aba_livre(raiz, tmp_path):
    aba, ch = _aba(raiz, _instalacao(tmp_path), _erro_iniciar=OSError("sem cmd"))
    aba.rodar()
    assert "Não consegui iniciar" in aba.v_status.get()
    assert str(aba.b_rodar["state"]) == "normal"
    assert aba.leitor is None and aba.ocupado() is None
    assert ch["registrar"] == []


def test_novo_log_que_falha_deixa_a_aba_livre(raiz, tmp_path, monkeypatch):
    aba, ch = _aba(raiz, _instalacao(tmp_path))

    def sem_log(pasta):
        raise FileNotFoundError("sem coletor\logs")

    monkeypatch.setattr(F.rodada, "novo_log", sem_log)
    aba.rodar()
    assert "Não consegui iniciar" in aba.v_status.get()
    assert str(aba.b_rodar["state"]) == "normal"
    assert aba.leitor is None and aba.ocupado() is None
    assert ch["iniciar"] == [] and ch["registrar"] == []


def test_registrar_que_quebra_nao_prende_a_aba(raiz, tmp_path):
    aba, ch = _aba(raiz, _instalacao(tmp_path), _registrar_quebra=True,
                   _proc=_Proc([None, 0]))
    aba.rodar()
    assert str(aba.b_rodar["state"]) == "disabled" and aba.ocupado()
    aba._acompanhar()
    aba._acompanhar()
    assert aba.ocupado() is None
    assert str(aba.b_rodar["state"]) == "normal"
    assert "sem alertas" in aba.v_status.get()


def test_leitor_nasce_antes_do_iniciar(raiz, tmp_path):
    aba, ch = _aba(raiz, _instalacao(tmp_path), _escreve="[1/4] Primeira\n",
                   _proc=_Proc([0]))
    aba.rodar()
    aba._acompanhar()
    assert "[1/4] Primeira" in aba.log.get("1.0", "end")


def test_ao_abrir_sem_rodada_nao_muda_o_status(raiz, tmp_path):
    aba, ch = _aba(raiz, _instalacao(tmp_path))
    antes = aba.v_status.get()
    aba.ao_abrir()
    assert aba.v_status.get() == antes


def test_trava_ilegivel_nao_afirma_que_ha_rodada(raiz, tmp_path, monkeypatch):
    monkeypatch.setattr(F.rodada, "em_andamento", lambda p: {"ilegivel": True})
    aba, ch = _aba(raiz, _instalacao(tmp_path))
    aba.rodar()
    assert "não consegui conferir" in aba.v_status.get()
    assert "suporte" in aba.v_status.get()
    assert ch["iniciar"] == []


def test_trancada_sem_info_nao_chama_o_suporte(raiz, tmp_path, monkeypatch):
    monkeypatch.setattr(F.rodada, "em_andamento", lambda p: {})
    aba, ch = _aba(raiz, _instalacao(tmp_path))
    aba.rodar()
    assert "em andamento" in aba.v_status.get()
    assert "suporte" not in aba.v_status.get()
    assert ch["iniciar"] == []
