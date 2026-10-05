"""Relatório Mensal: a lista de contas vem da busca central, sem abrir Chrome."""
from relatorios import extrato_mc


def test_ids_da_tela_casa_pelo_nome_normalizado():
    tela = [{"id": 7, "nome": "Empresa  Modelo - SICOOB"},
            {"id": 8, "nome": "OUTRA EMPRESA MODELO - INTER"}]
    ids, faltam, ambiguos = extrato_mc.ids_da_tela(
        ["EMPRESA MODELO - SICOOB", "CONTA QUE SUMIU"], tela)
    assert ids == {"EMPRESA MODELO - SICOOB": 7}
    assert faltam == ["CONTA QUE SUMIU"]
    assert ambiguos == []


def test_nome_repetido_na_tela_nunca_casa():
    tela = [{"id": 1, "nome": "Conta Dupla"}, {"id": 2, "nome": "CONTA  DUPLA"},
            {"id": 3, "nome": "Outra"}]
    ids, faltam, ambiguos = extrato_mc.ids_da_tela(["CONTA DUPLA", "OUTRA"], tela)
    assert ids == {"OUTRA": 3}
    assert faltam == []
    assert ambiguos == ["CONTA DUPLA"]


class _MapaDuble:
    raiz = "C:/x"

    def de(self, nome):
        return None


class _AnxDuble:
    mc = None


def _aba(raiz, monkeypatch, lista):
    from relatorios import relatorio_frame as rf
    monkeypatch.setattr(rf.contas_central, "ler_lista",
                        lambda pasta=None: lista)
    aba = rf.RelatorioFrame(raiz, _AnxDuble())
    aba.mapa = _MapaDuble()
    monkeypatch.setattr(aba, "_garantir_mapa", lambda: True)
    return aba


def test_aba_monta_a_lista_sem_botao_de_carregar(raiz, monkeypatch):
    aba = _aba(raiz, monkeypatch,
               [{"id": "u-1", "nome": "EMPRESA MODELO - SICOOB"}])
    try:
        aba.recarregar_contas()
        assert list(aba.vars_contas) == ["u-1"]
        assert aba.vars_contas["u-1"].get() is False   # sem pasta: desmarcada
        assert not hasattr(aba, "b1")
        assert str(aba.b2.cget("state")) == "normal"
    finally:
        aba.destroy()


def test_lista_vazia_explica_onde_atualizar(raiz, monkeypatch):
    aba = _aba(raiz, monkeypatch, [])
    try:
        aba.ao_abrir()
        assert "Atualizar contas" in str(aba.lbl_vazio.cget("text"))
        assert str(aba.b2.cget("state")) == "disabled"
    finally:
        aba.destroy()


def test_recarregar_preserva_as_marcacoes(raiz, monkeypatch):
    aba = _aba(raiz, monkeypatch, [{"id": "u-1", "nome": "A"},
                                   {"id": "u-2", "nome": "B"}])
    try:
        aba.recarregar_contas()
        aba.vars_contas["u-2"].set(True)
        aba.vars_contas["u-1"].set(False)
        aba.recarregar_contas()
        assert aba.vars_contas["u-2"].get() is True
        assert aba.vars_contas["u-1"].get() is False
    finally:
        aba.destroy()


def test_lista_igual_nao_remonta_os_checkbuttons(raiz, monkeypatch):
    aba = _aba(raiz, monkeypatch, [{"id": "u-1", "nome": "A"}])
    try:
        aba.recarregar_contas()
        antes = list(aba.contas_box.winfo_children())
        aba.ao_abrir()
        assert list(aba.contas_box.winfo_children()) == antes
    finally:
        aba.destroy()


def test_mapa_invalido_mostra_o_motivo_e_nao_repete_no_registro(raiz, monkeypatch):
    from relatorios import relatorio_frame as rf, contas_mc
    aba = _aba(raiz, monkeypatch, [{"id": "u-1", "nome": "A"}])
    try:
        aba.mapa = None
        monkeypatch.undo()
        def _falha(*a, **k):
            raise contas_mc.MapaInvalido("mapa quebrado")
        monkeypatch.setattr(rf.contas_mc, "carregar", _falha)
        aba.recarregar_contas()
        aba.ao_abrir()
        assert "mapa quebrado" in str(aba.lbl_vazio.cget("text"))
        logs = [m for t, m in list(aba.q.queue) if t == "log"]
        assert logs == ["[!] mapa quebrado"]
    finally:
        aba.destroy()


def test_t_gerar_usa_id_da_tela_e_isola_falhas(raiz, monkeypatch, tmp_path):
    from relatorios import relatorio_frame as rf, contas_mc
    aba = _aba(raiz, monkeypatch, [])
    try:
        aba.mapa = contas_mc.Mapa(tmp_path, [
            contas_mc.Destino("OK", "EMP", "BANCO", "SICOOB"),
            contas_mc.Destino("SUMIDA", "EMP", "BANCO", "SICOOB"),
            contas_mc.Destino("DUPLA", "EMP", "BANCO", "SICOOB"),
            contas_mc.Destino("OUTRA", "EMP", "BANCO", "INTER")])

        class Anx:
            class mc:
                page = object()

            def garantir_sessao(self, log):
                pass
        aba.anx = Anx()
        monkeypatch.setattr(aba, "_conferir_mapas", lambda: None)
        monkeypatch.setattr(rf.widgets, "registrar_atividade", lambda *a, **k: None)
        em = rf.extrato_mc
        monkeypatch.setattr(em, "listar_contas", lambda p: [
            {"id": 101, "nome": "ok"}, {"id": 5, "nome": "Dupla"},
            {"id": 6, "nome": "DUPLA"}, {"id": 102, "nome": "OUTRA"}])
        abertos = []
        monkeypatch.setattr(em, "abrir_extrato",
                            lambda p, i, a, b: abertos.append(i))
        monkeypatch.setattr(em, "carregar_tudo", lambda p, parar=None: 1)
        monkeypatch.setattr(em, "estado", lambda p: {})
        monkeypatch.setattr(em, "conferir_antes_de_salvar", lambda e, n: [])
        monkeypatch.setattr(em, "restaurar_pagina", lambda p: None)

        def salvar(p, arq):
            arq.parent.mkdir(parents=True, exist_ok=True)
            arq.write_bytes(b"x")
        monkeypatch.setattr(em, "salvar_pdf", salvar)

        import datetime
        contas = [{"id": "api-1", "nome": n}
                  for n in ("OK", "SUMIDA", "DUPLA", "OUTRA")]
        aba._t_gerar(contas, datetime.date(2026, 7, 1), datetime.date(2026, 7, 31))
        assert abertos == [101, 102]        # id da TELA; os dois falhos pulados
        logs = "\n".join(m for t, m in list(aba.q.queue) if t == "log")
        assert "SUMIDA — FALHOU: não aparece no fluxo de caixa" in logs
        assert "DUPLA — FALHOU: aparece mais de uma vez" in logs
        assert "2 extrato(s) gerados" in logs
    finally:
        aba.destroy()
