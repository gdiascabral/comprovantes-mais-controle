"""A coluna DISTRATO da aba Contratos, na aba de verdade (fixture `raiz`)."""
from contratos import frame as cf
from contratos.pipeline import Achado
from contratos.regras import Imovel


class _AnxFalso:
    """O dono do navegador, de mentira: a aba só o guarda ao nascer."""

    def avisar_se_ocupado(self, _quem):
        return False

    def submeter(self, *a, **_k):
        return None


def _achado(nome, distrato=False, outro=False, anexo=True):
    im = Imovel(obra="OBRA EXEMPLO", unidade=1,
                comprador="SEGUNDO COMPRADOR EXEMPLO")
    return Achado(imovel=im, anexo={"filename": nome} if anexo else {},
                  empresa="EMPRESA MODELO", distrato=distrato,
                  distrato_sugerido=distrato, outro_contrato=outro,
                  comprador_contrato="PRIMEIRO COMPRADOR EXEMPLO"
                  if outro else "")


def _aba(raiz):
    return cf.ContratosFrame(raiz, _AnxFalso())


def test_coluna_distrato_mostra_a_sugestao_e_alterna(raiz):
    aba = _aba(raiz)
    try:
        aba.achados = [_achado("A.pdf"), _achado("B.pdf", True, True)]
        aba._mostrar(aba.achados)
        assert aba.tabela.set("0", "distrato") == cf._MARCA[False]
        assert aba.tabela.set("1", "distrato") == cf._MARCA[True]
        assert aba.tabela.set("0", "comprador") == "SEGUNDO COMPRADOR EXEMPLO"
        assert aba.tabela.set("1", "comprador").startswith(
            "PRIMEIRO COMPRADOR EXEMPLO")
        assert "outro contrato da casa" in aba.tabela.set("1", "comprador")
        aba._alternar_distrato("1")
        assert aba.achados[1].distrato is False
        assert aba.tabela.set("1", "distrato") == cf._MARCA[False]
        aba._alternar_distrato("1")
        assert aba.achados[1].distrato is True
    finally:
        aba.destroy()


def test_linha_sem_contrato_nao_tem_distrato_para_marcar(raiz):
    aba = _aba(raiz)
    try:
        aba.achados = [_achado("", anexo=False)]
        aba._mostrar(aba.achados)
        assert aba.tabela.set("0", "distrato") == ""
        aba._alternar_distrato("0")
        assert aba.achados[0].distrato is False
        assert "não tem contrato" in aba.lbl.cget("text")
    finally:
        aba.destroy()


def test_cliques_na_coluna_2_alternam_o_distrato_e_a_1_a_marca(raiz):
    aba = _aba(raiz)
    try:
        aba.achados = [_achado("A.pdf")]
        aba._mostrar(aba.achados)
        col = {"x": "#2"}
        aba.tabela.identify_region = lambda x, y: "cell"
        aba.tabela.identify_column = lambda x: col["x"]
        aba.tabela.identify_row = lambda y: "0"

        class Ev:
            x = y = 1
        aba._clique_na_tabela(Ev)
        assert aba.achados[0].distrato is True
        assert aba.achados[0].marcado is False
        assert aba._duplo_clique(Ev) == "break"
        col["x"] = "#1"
        aba._clique_na_tabela(Ev)
        assert aba.achados[0].marcado is True
    finally:
        aba.destroy()
