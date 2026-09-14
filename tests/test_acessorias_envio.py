# -*- coding: utf-8 -*-
"""O envio ao portal Acessórias e o "Gerar os .zip" da aba, sem navegador.

O portal é site de terceiro e continua fora de teste de verdade. O que se
prova aqui é a ORDEM das chamadas, que foi o defeito de 14/09/2026: o
Salvar/Enviar sobe o zip por XHR, a espera era pela PÁGINA (que já estava
pronta) e a conferência fazia `goto` para a lista com o upload ainda subindo —
o que o cancela. Onze empresas, onze "não confirmado". Quem prova é uma página
falsa que anota cada chamada.

A aba é exercitada sem `Tk()`: `_t_enviar` e `_t_zipar` só falam com a fila,
então o objeto nasce por `__new__` e a janela nunca abre.

Nomes de empresa e endereço INVENTADOS: o repositório é público.
"""
import queue
from threading import Event

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import TimeoutError as PWTimeout  # noqa: E402

from acessorias import config as cfg  # noqa: E402
from acessorias import frame as aba_mod  # noqa: E402
from acessorias import pacote  # noqa: E402
from acessorias import portal  # noqa: E402
from acessorias.portal import EnvioNaoConfirmado, PortalClient  # noqa: E402
from extratos_sicoob import sicoob_config as scfg  # noqa: E402
from extratos_sicoob import sicoob_contas as sc  # noqa: E402

URL = "https://exemplo.invalido/escritorio"
MES, ANO = 7, 2026


# -------------------------------------------------------------- página falsa

class _Pedido:
    def __init__(self, method, headers):
        self.method = method
        self.headers = headers or {}


class Resposta:
    def __init__(self, url, status=200, method="POST", headers=None):
        self.url = url
        self.status = status
        self.request = _Pedido(method, headers)

    @property
    def ok(self):
        return 200 <= self.status < 300


class _Espera:
    """O `EventContextManager` do Playwright síncrono: o corpo roda, e é na
    SAÍDA que se espera a resposta — sem ela, `TimeoutError` ali mesmo; com
    exceção no corpo, ela sobe sem esperar nada."""

    def __init__(self, pagina, predicado):
        self.pagina = pagina
        self.predicado = predicado

    def __enter__(self):
        self.pagina.chamadas.append(("espera", "entra"))
        return self

    def __exit__(self, tipo, _exc, _tb):
        if tipo is not None:
            return False
        for r in self.pagina.respostas:
            if self.predicado(r):
                self.value = r
                self.pagina.chamadas.append(("espera", "respondeu"))
                return False
        raise PWTimeout("sem resposta")


class _Localizador:
    def __init__(self, n):
        self.n = n

    def count(self):
        return self.n


class Pagina:
    """`leituras` é o que a lista de solicitações devolve a cada leitura (a
    última se repete); `respostas` o que a rede devolve depois do clique."""

    def __init__(self, respostas=(), leituras=((),), texto="", clique=None):
        self.url = URL
        self.respostas = list(respostas)
        self.leituras = [list(x) for x in leituras]
        self.texto = texto
        self.clique = clique
        self.chamadas: list[tuple] = []

    def goto(self, url, wait_until=None):
        self.chamadas.append(("goto", url))

    def click(self, seletor):
        if self.clique is not None:
            raise self.clique
        self.chamadas.append(("click", seletor))

    def expect_response(self, predicado, timeout=None):
        return _Espera(self, predicado)

    def evaluate(self, js, *_):
        if "go2link" in js:
            lida = self.leituras[0]
            if len(self.leituras) > 1:
                self.leituras.pop(0)
            return lida
        return []                          # SolDptoDcvID sem opções

    def locator(self, seletor):
        # O botão Sair existe (sessão aberta); a aba Encerradas, não.
        return _Localizador(1 if "?out" in seletor else 0)

    def inner_text(self, _sel):
        return self.texto

    def wait_for_timeout(self, _ms):
        pass

    def wait_for_selector(self, *_a, **_k):
        pass

    def wait_for_load_state(self, *_a, **_k):
        pass

    def fill(self, *_a):
        pass

    def select_option(self, *_a, **_k):
        pass

    def set_input_files(self, *_a):
        pass


def _cliente(pagina):
    cli = PortalClient(URL, log=lambda *_: None)
    cli.page = pagina
    return cli


def _card(id_, assunto):
    return {"id": id_, "texto": f"{assunto} [{id_}]\n14/09/2026 10:00:00 - Aberta"}


@pytest.fixture
def zip_(tmp_path):
    alvo = tmp_path / "JULHO 2026 - EMPRESA TESTE.zip"
    alvo.write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    return alvo


# -------------------------------------------------------- a espera do envio

def test_o_clique_acontece_dentro_da_espera_pela_resposta(zip_):
    """O defeito de 14/09: sem esperar a resposta, a função voltava com o
    upload subindo e a conferência saía da página por cima dele."""
    pagina = Pagina(respostas=[Resposta(URL + cfg.CAMINHO_ENVIO)])
    _cliente(pagina).criar_solicitacao("10", "Assunto", "Corpo", zip_)

    ordem = pagina.chamadas
    entra = ordem.index(("espera", "entra"))
    clique = ordem.index(("click", cfg.SEL_SALVAR))
    respondeu = ordem.index(("espera", "respondeu"))
    assert entra < clique < respondeu
    # Nenhuma navegação entre o clique e a resposta: é ela que cancela o envio.
    assert not [c for c in ordem[clique:respondeu] if c[0] == "goto"]


def test_portal_mudo_vira_nao_confirmado_e_nao_sucesso(zip_):
    with pytest.raises(EnvioNaoConfirmado, match="não respondeu"):
        _cliente(Pagina(respostas=[])).criar_solicitacao(
            "10", "Assunto", "Corpo", zip_)


def test_resposta_de_erro_vira_nao_confirmado(zip_):
    pagina = Pagina(respostas=[Resposta(URL + cfg.CAMINHO_ENVIO, status=500)])
    with pytest.raises(EnvioNaoConfirmado, match="500"):
        _cliente(pagina).criar_solicitacao("10", "Assunto", "Corpo", zip_)


def test_botao_que_nao_existe_nao_se_disfarca_de_envio_duvidoso(zip_):
    """Sem clique nada saiu daqui: é erro comum, não "pode ter chegado"."""
    pagina = Pagina(respostas=[], clique=PWTimeout("sem o botão"))
    with pytest.raises(PWTimeout):
        _cliente(pagina).criar_solicitacao("10", "Assunto", "Corpo", zip_)


@pytest.mark.parametrize("resposta, e_o_envio", [
    (Resposta(URL + "/sysvipsolAjax"), True),
    (Resposta(URL + "/outro", headers={
        "content-type": "multipart/form-data; boundary=x"}), True),
    (Resposta(URL + "/sysvipsolAjax", method="GET"), False),
    (Resposta(URL + "/outro", headers={"content-type": "application/json"}),
     False),
])
def test_qual_resposta_e_a_do_envio(resposta, e_o_envio):
    assert portal._e_o_envio(resposta) is e_o_envio


# ------------------------------------------------------------ a conferência

def test_conferencia_rele_a_lista_antes_de_desistir():
    assunto = "Conciliações bancárias Julho/2026 - EMPRESA TESTE"
    pagina = Pagina(leituras=([], [_card("77", assunto)]),
                    texto="anexo: JULHO 2026 - EMPRESA TESTE.zip")
    s = _cliente(pagina).conferir_envio(
        "10", assunto, "JULHO 2026 - EMPRESA TESTE.zip")
    assert s.id == "77"


def test_conferencia_que_desiste_diz_quantas_leu():
    """Zero lidas numa empresa com meses enviados é "o robô não enxerga a
    lista", e não "não chegou" — a mensagem precisa deixar isso à vista."""
    pagina = Pagina(leituras=([_card("5", "Outro assunto")],))
    with pytest.raises(EnvioNaoConfirmado, match="li 1 solicitação"):
        _cliente(pagina).conferir_envio("10", "Assunto", "x.zip")
    listas = [c for c in pagina.chamadas
              if c[0] == "goto" and c[1].endswith("/10/SOL/")]
    assert len(listas) == cfg.RELEITURAS_DA_LISTA


# ------------------------------------------------------------------- a aba

def _aba(mapa=None):
    aba = aba_mod.AcessoriasFrame.__new__(aba_mod.AcessoriasFrame)
    aba.q = queue.Queue()
    aba._parar = Event()
    aba.portal = None
    aba.mapa = mapa
    aba.envios = []
    return aba


def _mensagens(aba):
    saida = []
    while True:
        try:
            saida.append(aba.q.get_nowait())
        except queue.Empty:
            return saida


def test_lote_para_na_primeira_empresa_nao_confirmada(monkeypatch, tmp_path):
    criadas = []

    class Cliente:
        def __init__(self, *_a, **_k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def aguardar_login(self):
            pass

        def procurar(self, *_):
            return None

        def criar_solicitacao(self, vip_id, *_):
            criadas.append(vip_id)

        def conferir_envio(self, *_):
            raise EnvioNaoConfirmado("não apareceu")

    monkeypatch.setattr(aba_mod, "PortalClient", Cliente)
    envios = [pacote.Envio(empresa=f"EMPRESA {n}", rotulo=f"EMPRESA {n}",
                           vip_id=str(n), caminho=tmp_path / f"{n}.zip",
                           tamanho=1)
              for n in (1, 2, 3)]
    aba = _aba(sc.Mapa(raiz=tmp_path, empresas=[], vip_url=URL))
    aba.envios = envios
    aba._t_enviar(list(envios))

    assert criadas == ["1"]
    textos = [v for t, v in _mensagens(aba) if t == "log"]
    assert any("Parei o lote" in t for t in textos)
    assert all(e.pronta for e in envios)   # as outras continuam na fila


def test_gerar_os_zip_empacota_e_ja_prepara(tmp_path):
    empresa = sc.Empresa(nome="EMPRESA TESTE", vip_id="10")
    pasta = (tmp_path / str(ANO) / scfg.nome_do_mes(MES)
             / scfg.nome_pasta_empresa(ANO, MES, empresa.nome))
    (pasta / "SICOOB").mkdir(parents=True)
    (pasta / "SICOOB" / "extrato.ofx").write_text("x", encoding="utf-8")
    aba = _aba(sc.Mapa(raiz=tmp_path, empresas=[empresa], vip_url=URL))
    aba._garantir_mapa = lambda: True

    aba._t_zipar(ANO, MES, pacote.MODELO_ASSUNTO, pacote.MODELO_COMENTARIO)

    assert (pasta.parent / (pasta.name + ".zip")).is_file()
    mensagens = _mensagens(aba)
    envios = [v for t, v in mensagens if t == "envios"]
    assert len(envios) == 1 and [e.empresa for e in envios[0]] == [empresa.nome]
    assert envios[0][0].pronta
    assert mensagens[-1] == ("botoes", "normal")


def test_gerar_os_zip_sem_pasta_nenhuma_nao_manda_zipar_de_novo(tmp_path):
    """Sem pasta de empresa, emendar o Preparar diria "clique em Gerar os .zip"
    a quem acabou de clicar."""
    (tmp_path / str(ANO) / scfg.nome_do_mes(MES)).mkdir(parents=True)
    empresa = sc.Empresa(nome="EMPRESA TESTE", vip_id="10")
    aba = _aba(sc.Mapa(raiz=tmp_path, empresas=[empresa], vip_url=URL))
    aba._garantir_mapa = lambda: True

    aba._t_zipar(ANO, MES, pacote.MODELO_ASSUNTO, pacote.MODELO_COMENTARIO)

    mensagens = _mensagens(aba)
    assert not [v for t, v in mensagens if t == "envios"]
    assert any(t == "log" and "Nenhuma pasta de empresa" in v
               for t, v in mensagens)
    assert mensagens[-1] == ("botoes", "normal")
