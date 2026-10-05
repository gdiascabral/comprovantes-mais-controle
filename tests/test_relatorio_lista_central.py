"""Relatório Mensal: a lista de contas vem da busca central, sem abrir Chrome."""
from relatorios import extrato_mc


def test_ids_da_tela_casa_pelo_nome_normalizado():
    tela = [{"id": 7, "nome": "Empresa  Modelo - SICOOB"},
            {"id": 8, "nome": "OUTRA EMPRESA MODELO - INTER"}]
    ids, faltam = extrato_mc.ids_da_tela(
        ["EMPRESA MODELO - SICOOB", "CONTA QUE SUMIU"], tela)
    assert ids == {"EMPRESA MODELO - SICOOB": 7}
    assert faltam == ["CONTA QUE SUMIU"]


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
