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


# ------------------------------------------------- revisão final
def test_linha_ja_arquivada_nao_troca_a_marca(raiz):
    """O arquivo já está na pasta com o nome de antes: trocar a marca aqui
    não renomeia nada, e a tabela mentiria sobre o que foi gravado."""
    aba = _aba(raiz)
    try:
        a = _achado("A.pdf", distrato=True, outro=True)
        a.arquivado = True
        a.destino = "X (Distratado).pdf"
        aba.achados = [a]
        aba._mostrar(aba.achados)
        aba._alternar_distrato("0")
        assert a.distrato is True
        assert aba.tabela.set("0", "distrato") == cf._MARCA[True]
        assert "já foi arquivado" in aba.lbl.cget("text")
        assert "renomeie o arquivo na pasta" in aba.lbl.cget("text")
        assert aba.marcas_distrato == {}
    finally:
        aba.destroy()


def _casa_com_dois(recebimentos=2):
    """A linha do recebimento e a extra da mesma casa: dividem o `imovel`."""
    from decimal import Decimal

    from contratos.regras import Recebimento
    im = Imovel(obra="OBRA EXEMPLO", unidade=1,
                comprador="SEGUNDO COMPRADOR EXEMPLO",
                recebido=Decimal("1000.00"),
                recebimentos=[Recebimento("2026-08-0%d" % (n + 1),
                                          "CONDICAO %d" % n, Decimal("500.00"))
                              for n in range(recebimentos)])
    atual = Achado(imovel=im, anexo={"filename": "A.pdf"}, empresa="E",
                   comprador_contrato="SEGUNDO COMPRADOR EXEMPLO",
                   casa_com_distrato=True)
    extra = Achado(imovel=im, anexo={"filename": "B.pdf"}, empresa="E",
                   comprador_contrato="PRIMEIRO COMPRADOR EXEMPLO",
                   outro_contrato=True, distrato=True, casa_com_distrato=True)
    return atual, extra


def test_resumo_do_mes_conta_a_casa_e_os_recebimentos_uma_vez(raiz, tmp_path):
    aba = _aba(raiz)
    try:
        atual, extra = _casa_com_dois()
        atual.arquivado = extra.arquivado = True
        atual.destino = tmp_path / "A - SEGUNDO.pdf"
        extra.destino = tmp_path / "B - PRIMEIRO (Distratado).pdf"
        aba.achados = [atual, extra]
        texto = aba._resumo(2026, 8, tmp_path).read_text(encoding="utf-8")
        assert "1 casa(s) com 2 recebimento(s)" in texto
        assert "R$ 1,000.00" in texto
        assert "2 arquivado(s)" in texto
        assert texto.count("CONDICAO 0") == 1
        assert texto.count("CONDICAO 1") == 1
        assert "PRIMEIRO COMPRADOR EXEMPLO" in texto
    finally:
        aba.destroy()


def test_resumo_do_mes_nao_repete_recebimentos_na_extra_em_revisao(raiz,
                                                                  tmp_path):
    aba = _aba(raiz)
    try:
        atual, extra = _casa_com_dois()
        atual.revisao = extra.revisao = "algum motivo"
        aba.achados = [atual, extra]
        texto = aba._resumo(2026, 8, tmp_path).read_text(encoding="utf-8")
        assert "1 casa(s) com 2 recebimento(s)" in texto
        assert texto.count("CONDICAO 0") == 1
    finally:
        aba.destroy()


class _ApiFalsa:
    def capturar_credenciais(self, _log):
        return True


class _AnxComSessao(_AnxFalso):
    def garantir_sessao(self, _log):
        return _ApiFalsa()


def test_marca_de_distrato_feita_a_mao_volta_na_busca_seguinte(raiz,
                                                                monkeypatch):
    aba = cf.ContratosFrame(raiz, _AnxComSessao())
    try:
        atual, extra = _casa_com_dois()
        aba.achados = [atual, extra]
        aba._mostrar(aba.achados)
        aba._alternar_distrato("1")             # a pessoa desmarca a extra
        assert extra.distrato is False

        class _Contas:
            @staticmethod
            def carregar():
                return type("Mapa", (), {"empresas": []})()

            @staticmethod
            def validar(_m):
                return []
        monkeypatch.setattr(cf, "_sicoob", lambda: (None, _Contas))
        novos = list(_casa_com_dois())          # a busca sugere de novo
        monkeypatch.setattr(cf.pipeline, "levantar",
                            lambda *a, **k: novos)
        while not aba.q.empty():
            aba.q.get_nowait()
        aba._t_buscar()
        assert aba.achados is novos
        assert novos[1].distrato is False
        assert novos[0].distrato is False
        recados = []
        while not aba.q.empty():
            tipo, val = aba.q.get_nowait()
            if tipo == "log":
                recados.append(val)
        assert any("1 marca(s) de distrato" in m for m in recados), recados
    finally:
        aba.destroy()
