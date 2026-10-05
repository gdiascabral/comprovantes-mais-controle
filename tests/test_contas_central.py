import json
from types import SimpleNamespace

import pytest

from nuvem import contas_central as cc
from nuvem import contas_novas_dialogo as dialogo


def _cru(i, ativa=True):
    return {"id": f"u-{i}", "name": f"EMPRESA MODELO - CONTA NOVA FICTICIA {i:02d}",
            "isActive": ativa, "bankCode": "756", "agency": "1234",
            "account": f"{90000 + i}", "accountDigit": "1"}


def _cadastro(pasta, nomes):
    (pasta / "contas_mc.json").write_text(json.dumps(
        {"contas": [{"erp": n} for n in nomes]}), encoding="utf-8")


def test_guarda_e_le_a_lista(tmp_path):
    assert cc.guardar_lista([_cru(2), _cru(1)], tmp_path)
    lista = cc.ler_lista(tmp_path)
    assert [c["id"] for c in lista] == ["u-1", "u-2"]
    assert lista[0] == {"id": "u-1",
                        "nome": "EMPRESA MODELO - CONTA NOVA FICTICIA 01",
                        "banco": "756", "agencia": "1234", "numero": "90001-1"}


def test_lista_vazia_nunca_apaga_a_que_estava(tmp_path):
    cc.guardar_lista([_cru(1)], tmp_path)
    assert cc.guardar_lista([], tmp_path) is False
    assert cc.guardar_lista([{"id": "", "name": ""}], tmp_path) is False
    assert [c["id"] for c in cc.ler_lista(tmp_path)] == ["u-1"]


def test_sem_arquivo_a_lista_e_vazia(tmp_path):
    assert cc.ler_lista(tmp_path) == []


def test_sem_painel_so_pergunta_pelo_cadastro(tmp_path):
    _cadastro(tmp_path, ["EMPRESA MODELO - CONTA NOVA FICTICIA 01"])
    pend = cc.pendencias([_cru(1), _cru(2)], tmp_path, pasta_painel=tmp_path)
    assert [(p.nome, p.falta_cadastro, p.falta_painel) for p in pend] == [
        ("EMPRESA MODELO - CONTA NOVA FICTICIA 02", True, False)]


def test_conta_inativa_nao_e_pendencia(tmp_path):
    _cadastro(tmp_path, [])
    assert cc.pendencias([_cru(1, ativa=False)], tmp_path,
                         pasta_painel=tmp_path) == []


class _MapaDuble:
    """Casa pelo id: as contas em `no_painel` têm linha viva."""

    def __init__(self, no_painel):
        self.no_painel = set(no_painel)


def test_cadastro_e_painel_se_juntam_por_conta(tmp_path, monkeypatch):
    _cadastro(tmp_path, ["EMPRESA MODELO - CONTA NOVA FICTICIA 01"])
    mapa = _MapaDuble({"u-2"})
    monkeypatch.setattr(cc, "mapa_do_painel", lambda _p=None: mapa)
    monkeypatch.setattr(
        cc, "_fora_do_painel",
        lambda contas, m: [c for c in contas if c.id not in m.no_painel])
    pend = {p.erp.id: p for p in cc.pendencias([_cru(1), _cru(2), _cru(3)],
                                               tmp_path, tmp_path)}
    assert (pend["u-1"].falta_cadastro, pend["u-1"].falta_painel) == (False, True)
    assert (pend["u-2"].falta_cadastro, pend["u-2"].falta_painel) == (True, False)
    assert (pend["u-3"].falta_cadastro, pend["u-3"].falta_painel) == (True, True)
    assert pend["u-3"].falta_em == "cadastro e painel"
    assert pend["u-1"].falta_em == "painel"
    assert pend["u-3"].rotulo == "EMPRESA MODELO - CONTA NOVA FICTICIA 03"


def test_ignorada_no_mapping_nao_e_pendencia_de_cadastro(tmp_path):
    _cadastro(tmp_path, [])
    (tmp_path / "mapping.yaml").write_text(
        "ignored_erp_accounts:\n  - CONTA NOVA FICTICIA 01\n", encoding="utf-8")
    pend = cc.pendencias([_cru(1)], tmp_path, pasta_painel=tmp_path)
    assert pend == []


def _p(i):
    from conciliacao.erp.api import conta_do_erp
    return SimpleNamespace(erp=conta_do_erp(_cru(i)), nome=_cru(i)["name"])


def test_aplica_cadastro_e_painel(monkeypatch, tmp_path):
    from conciliacao import painel_novas
    gravados, incluidos = [], []
    monkeypatch.setattr(cc.contas_novas, "gravar",
                        lambda tok, esc: gravados.extend(esc) or [])

    def incluir(pasta, inclusoes, contas_erp):
        incluidos.extend((i.conta.id, i.rotulo) for i in inclusoes)
        assert {c.id for c in contas_erp} == {"u-1", "u-2"}
        return painel_novas.ResultadoInclusao(linhas=[(34, "LINHA 02")],
                                             copia=tmp_path)

    monkeypatch.setattr(painel_novas, "incluir_no_painel", incluir)
    r = dialogo.Respostas(cadastro=[{"nome_erp": "X"}],
                          painel=[(_p(2), "LINHA 02")])
    recado = cc.aplicar("tok", r, [_cru(1), _cru(2)], tmp_path)
    assert gravados == [{"nome_erp": "X"}]
    assert incluidos == [("u-2", "LINHA 02")]
    assert "1 conta(s) cadastrada(s)." in recado
    assert "1 conta(s) incluída(s) no painel do Saldo (linha 34)." in recado
    assert "aba Regras do MODELO.xlsx" in recado


def test_varias_linhas_e_avisos_do_cadastro(monkeypatch, tmp_path):
    from conciliacao import painel_novas
    monkeypatch.setattr(cc.contas_novas, "gravar",
                        lambda tok, esc: ["Y: sem pasta"])
    monkeypatch.setattr(
        painel_novas, "incluir_no_painel",
        lambda *a, **k: painel_novas.ResultadoInclusao(
            linhas=[(34, "A"), (36, "B")], copia=tmp_path))
    r = dialogo.Respostas([{"nome_erp": "X"}, {"nome_erp": "Y"}],
                          [(_p(1), "A"), (_p(2), "B")])
    recado = cc.aplicar("tok", r, [_cru(1), _cru(2)], tmp_path)
    assert "1 conta(s) cadastrada(s)." in recado
    assert "Não gravadas no cadastro:" + chr(10) + "Y: sem pasta" in recado
    assert "(linhas 34 a 36)" in recado


def test_painel_recusado_nao_desfaz_o_cadastro(monkeypatch, tmp_path):
    from conciliacao import painel_novas
    monkeypatch.setattr(cc.contas_novas, "gravar", lambda tok, esc: [])

    def recusa(*_a, **_k):
        raise painel_novas.InclusaoRecusada("o MODELO.xlsx está aberto no Excel")

    monkeypatch.setattr(painel_novas, "incluir_no_painel", recusa)
    r = dialogo.Respostas(cadastro=[{"nome_erp": "X"}],
                          painel=[(_p(1), "LINHA 01")])
    recado = cc.aplicar("tok", r, [_cru(1)], tmp_path)
    assert "1 conta(s) cadastrada(s)." in recado
    assert "O painel do Saldo NÃO mudou" in recado
    assert "aberto no Excel" in recado


def test_sem_painel_nao_chama_o_painel(monkeypatch, tmp_path):
    from conciliacao import painel_novas
    monkeypatch.setattr(cc.contas_novas, "gravar", lambda tok, esc: [])
    monkeypatch.setattr(painel_novas, "incluir_no_painel",
                        lambda *a, **k: pytest.fail("não devia incluir"))
    recado = cc.aplicar("tok", dialogo.Respostas([{"nome_erp": "X"}], []),
                        [_cru(1)], tmp_path)
    assert "painel" not in recado


def test_erro_inesperado_do_painel_nao_perde_o_recado(monkeypatch, tmp_path):
    from conciliacao import painel_novas
    monkeypatch.setattr(cc.contas_novas, "gravar", lambda tok, esc: [])

    def quebra(*_a, **_k):
        raise OSError("disco cheio")

    monkeypatch.setattr(painel_novas, "incluir_no_painel", quebra)
    r = dialogo.Respostas([{"nome_erp": "X"}], [(_p(1), "LINHA 01")])
    recado = cc.aplicar("tok", r, [_cru(1)], tmp_path)
    assert "1 conta(s) cadastrada(s)." in recado
    assert "NÃO mudou" in recado and "disco cheio" in recado


def test_so_painel_nao_tem_linha_de_cadastro(monkeypatch, tmp_path):
    from conciliacao import painel_novas
    monkeypatch.setattr(
        painel_novas, "incluir_no_painel",
        lambda *a, **k: painel_novas.ResultadoInclusao(
            linhas=[(34, "A")], copia=tmp_path))
    recado = cc.aplicar("tok", dialogo.Respostas([], [(_p(1), "A")]),
                        [_cru(1)], tmp_path)
    assert "cadastrada" not in recado


def test_nada_a_aplicar_devolve_recado_vazio(tmp_path):
    assert cc.aplicar("tok", dialogo.Respostas([], []), [], tmp_path) == ""


def test_ler_do_erp_guarda_e_devolve(monkeypatch, tmp_path):
    monkeypatch.setattr(cc.contas_novas, "contas_do_erp",
                        lambda log=print: [_cru(1)])
    assert cc.ler_do_erp(tmp_path) == [_cru(1)]
    assert [c["id"] for c in cc.ler_lista(tmp_path)] == ["u-1"]


def test_erp_fora_do_ar_nao_apaga_a_lista(monkeypatch, tmp_path):
    cc.guardar_lista([_cru(1)], tmp_path)
    monkeypatch.setattr(cc.contas_novas, "contas_do_erp", lambda log=print: [])
    assert cc.ler_do_erp(tmp_path) == []
    assert [c["id"] for c in cc.ler_lista(tmp_path)] == ["u-1"]


def test_avisar_abas_chama_quem_tem_o_gancho_e_aguenta_falha():
    chamadas = []

    class Ok:
        def recarregar_contas(self):
            chamadas.append("ok")

    class Quebra:
        def recarregar_contas(self):
            raise RuntimeError("x")

    class Sem:
        pass

    linhas = []
    cc.avisar_abas({"a": Quebra(), "b": Ok(), "c": Sem()}, log=linhas.append)
    assert chamadas == ["ok"]
    assert len(linhas) == 1
    assert linhas[0].startswith("aba a:")


def test_a_moldura_usa_a_central_e_tem_o_botao():
    from pathlib import Path
    fonte = (Path(__file__).resolve().parents[1]
             / "comprovantes_app.py").read_text(encoding="utf-8")
    assert "Atualizar contas" in fonte
    assert "contas_central.ler_do_erp" in fonte
    assert "contas_central.avisar_abas" in fonte
    assert "avisar_se_ocupado(\"a atualização das contas\")" in fonte
    assert "contas_novas.novidades(" not in fonte
    # ERP mudo no botao nao pode virar "nenhuma conta nova".
    assert "Não consegui ler as contas do ERP agora." in fonte
    assert "As contas já estão sendo atualizadas." in fonte
    # O aviso de ocupado vem antes da trava: se ele levantar, nada fica preso.
    ocupado = fonte.index("avisar_se_ocupado(\"a atualização das contas\")")
    trava = fonte.index("if not _rodada_de_contas.acquire(blocking=False):\n"
                        "            messagebox.showinfo(")
    assert ocupado < trava


# ------------------------------------------------- revisão final (05/10/2026)

def test_abertura_so_pergunta_pelo_cadastro():
    """Conta deixada fora do painel de propósito não pode virar pergunta a
    cada abertura: só pendência de cadastro abre a janela ali."""
    so_painel = SimpleNamespace(falta_cadastro=False, falta_painel=True)
    so_cad = SimpleNamespace(falta_cadastro=True, falta_painel=False)
    os_dois = SimpleNamespace(falta_cadastro=True, falta_painel=True)
    assert cc.pendencias_da_abertura([so_painel]) == []
    assert cc.pendencias_da_abertura([so_painel, os_dois, so_cad]) == [
        os_dois, so_cad]
    assert cc.pendencias_da_abertura([]) == []


def _fonte_da_abertura():
    from pathlib import Path
    fonte = (Path(__file__).resolve().parents[1]
             / "comprovantes_app.py").read_text(encoding="utf-8")
    ini = fonte.index("    def _abertura():")
    return fonte[ini:fonte.index("\n    def ", ini + 10)]


def test_a_abertura_filtra_o_cadastro_e_avisa_as_abas_sempre():
    corpo = _fonte_da_abertura()
    assert "contas_central.pendencias_da_abertura(" in corpo
    # As abas ouvem a lista nova mesmo sem pendência (o Relatório Mensal
    # mostra a lista já na primeira visita), e pela thread do Tk.
    aviso = corpo.index("root.after(0, lambda: contas_central.avisar_abas(")
    assert aviso < corpo.index("if not pend:")
    assert corpo.index("contas_central.ler_do_erp(") < aviso


def test_a_janela_recebe_a_conferencia_do_painel():
    from pathlib import Path
    fonte = (Path(__file__).resolve().parents[1]
             / "comprovantes_app.py").read_text(encoding="utf-8")
    assert "conferir_painel=contas_central.conferidor_do_painel(" in fonte


def test_conferidor_sem_painel_e_none(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "mapa_do_painel", lambda _p=None: None)
    assert cc.conferidor_do_painel(tmp_path) is None


def test_conferidor_usa_os_problemas_da_inclusao(tmp_path, monkeypatch):
    from conciliacao import painel_novas
    mapa = object()
    monkeypatch.setattr(cc, "mapa_do_painel", lambda _p=None: mapa)
    vistos = []

    def problemas(inclusoes, mapping):
        vistos.append(([(i.conta.id, i.rotulo) for i in inclusoes], mapping))
        return ["um problema"]
    monkeypatch.setattr(painel_novas, "problemas_da_inclusao", problemas)
    conferir = cc.conferidor_do_painel(tmp_path)
    assert conferir([(_p(1), "LINHA 01")]) == ["um problema"]
    assert vistos == [([("u-1", "LINHA 01")], mapa)]
