"""As abas que usam a lista de contas ouvem a busca central (`recarregar_contas`)
e não têm mais botão próprio para isso."""
from pathlib import Path

import pytest


@pytest.mark.parametrize("arquivo,classe", [
    ("baixar_comprovantes/comprovantes_frame.py", "ComprovantesFrame"),
    ("aportes/aportes_frame.py", "AportesFrame"),
    ("pagamentos_dia/pagamentos_frame.py", "PagamentosDiaFrame"),
    ("relatorios/relatorio_frame.py", "RelatorioFrame"),
])
def test_aba_tem_o_gancho_da_busca_central(arquivo, classe):
    fonte = Path(arquivo).read_text(encoding="utf-8")
    assert f"class {classe}" in fonte
    assert "def recarregar_contas(self)" in fonte


def test_botoes_proprios_sairam():
    assert '"Atualizar lista"' not in Path(
        "baixar_comprovantes/comprovantes_frame.py").read_text(encoding="utf-8")
    assert '"Recarregar cadastros"' not in Path(
        "aportes/aportes_frame.py").read_text(encoding="utf-8")
    anexar = Path("anexar/anexar_comprovantes.py").read_text(encoding="utf-8")
    assert "Carregar contas" not in anexar
    assert "Buscar pagamentos" in anexar


def test_baixar_comprovantes_recarrega_a_lista_ao_ouvir_a_busca(raiz, monkeypatch):
    from baixar_comprovantes import comprovantes_frame as cf

    contas = [{"banco": "Sicoob", "conta": "1", "empresa": "E1", "pasta": "p"}]
    monkeypatch.setattr(cf.ComprovantesFrame, "_contas_do_cadastro",
                        lambda self: list(contas))
    aba = cf.ComprovantesFrame(raiz)
    try:
        assert list(aba.linhas) == ["Sicoob:1"]
        contas.append({"banco": "Sicoob", "conta": "2", "empresa": "E2",
                       "pasta": "p"})
        aba.recarregar_contas()
        assert list(aba.linhas) == ["Sicoob:1", "Sicoob:2"]
        assert len(aba.tabela.get_children()) == 2
    finally:
        aba.destroy()


def test_baixar_comprovantes_nao_recarrega_com_rodada_andando(raiz, monkeypatch):
    from baixar_comprovantes import comprovantes_frame as cf

    contas = [{"banco": "Sicoob", "conta": "1", "empresa": "E1", "pasta": "p"}]
    monkeypatch.setattr(cf.ComprovantesFrame, "_contas_do_cadastro",
                        lambda self: list(contas))
    aba = cf.ComprovantesFrame(raiz)
    try:
        class _Andando:
            def done(self):
                return False
        aba.worker = _Andando()
        contas.append({"banco": "Sicoob", "conta": "2", "empresa": "E2",
                       "pasta": "p"})
        aba.recarregar_contas()
        assert list(aba.linhas) == ["Sicoob:1"]   # a fila da rodada não muda
    finally:
        aba.worker = None
        aba.destroy()


class _AnxDuble:
    """Só o que as abas perguntam ao dono do navegador."""
    mc = None
    dona = None

    def dona_ocupada(self):
        return self.dona

    def ocupado(self):
        return "tarefa" if self.dona is not None else None


def test_aportes_adia_a_recarga_ate_o_comando_terminar(raiz, monkeypatch):
    from aportes import aportes_frame as af

    anx = _AnxDuble()
    aba = af.AportesFrame(raiz, anx)
    try:
        chamadas = []
        monkeypatch.setattr(aba, "_recarregar_cadastros",
                            lambda: chamadas.append(1))
        anx.dona = aba                       # um comando desta aba no navegador
        aba.recarregar_contas()
        aba.recarregar_contas()
        assert chamadas == []
        aba._drain()
        assert chamadas == []                # ainda rodando: continua esperando
        assert aba.texto.get("1.0", "end").count(
            "As contas novas entram nos Aportes") == 1   # avisa uma vez só
        anx.dona = None                      # o comando terminou
        aba._drain()
        assert chamadas == [1]
        aba._drain()
        assert chamadas == [1]               # uma vez só
    finally:
        aba.destroy()


def test_remessa_retorno_so_recarrega_sem_rotina_andando(raiz, monkeypatch):
    from pagamentos_dia import pagamentos_frame as pf

    aba = pf.PagamentosDiaFrame(raiz, _AnxDuble())
    try:
        chamadas = []
        monkeypatch.setattr(aba, "_conferir_prontidao",
                            lambda: chamadas.append(1))

        class _Andando:
            def done(self):
                return False
        aba.worker = _Andando()
        aba.recarregar_contas()
        assert chamadas == []
        aba.worker = None
        aba.ao_abrir()
        assert chamadas == [1]
        aba.recarregar_contas()
        assert chamadas == [1, 1]
    finally:
        aba.worker = None
        aba.destroy()
