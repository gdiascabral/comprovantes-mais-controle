# -*- coding: utf-8 -*-
"""A tela de Comprovantes do Sicoob muda de endereço sem aviso.

Em 25/09/2026 a lista saiu de `/api/comprovantes/consultar` para
`/api/comprovantes/pagamentos?isNovaEmissao=true`, e o documento de
`POST /api/comprovantes/detalhar` para `POST /api/comprovantes/pagamentos`.
Os dois antigos passaram a responder 500 — e como a lista falhava antes do
Pix, nenhuma conta baixava nada, nem o Pix, que não tinha mudado.

Estes testes cobrem o que faz a próxima mudança não precisar de ninguém:
rotas conhecidas em ordem, o endereço aprendido pela própria tela e
guardado para a rodada seguinte, e a falha dos comuns sem levar o Pix junto.
"""
from __future__ import annotations

import base64
import inspect
import json

import pytest

from baixar_comprovantes import sicoob_baixar as sb

LISTA_NOVA = "/api/comprovantes/pagamentos?isNovaEmissao=true"
LISTA_ANTIGA = "/api/comprovantes/consultar"
DOC_NOVO = "/api/comprovantes/pagamentos"
DOC_ANTIGO = "/api/comprovantes/detalhar"

ERRO_500 = {"status": 500, "erro": "HTTP 500",
            "corpo": '{"mensagem":"Ocorreu um erro ao executar a operação."}'}

TITULO = {"idAgendamento": "10000001", "valorLancamento": "99.99",
          "situacao": "EFETIVADO", "dataLancamento": "2026-09-25 00:00:00.0",
          "tipoAgendamento": "TÍTULO", "tipoComprovante": 2}


class Pagina:
    """Responde por rota: {trecho da URL: resposta}. Guarda o que foi pedido."""

    def __init__(self, respostas):
        self.respostas = respostas
        self.pedidos = []

    def evaluate(self, _js, args):
        url, metodo, _corpo = args
        self.pedidos.append((metodo, url))
        for trecho, resposta in self.respostas.items():
            m, rota = trecho
            if m == metodo and url.split("sicoobnet", 1)[1].split("?")[0] \
                    == rota.split("?")[0] and \
                    all(p in url for p in rota.split("?")[1:]):
                return resposta
        return {"status": 404, "erro": "HTTP 404", "corpo": ""}


@pytest.fixture
def rotas(tmp_path):
    return sb.Rotas(tmp_path / "sicoob_rotas.json")


# ------------------------------------------------------------------ a lista

def test_a_lista_pede_primeiro_o_endereco_novo(rotas):
    pagina = Pagina({("GET", LISTA_NOVA): {"dado": [TITULO]}})
    assert sb.listar(pagina, "01/09/2026", "30/09/2026", rotas=rotas) == [TITULO]
    metodo, url = pagina.pedidos[0]
    assert "/api/comprovantes/pagamentos?isNovaEmissao=true&tipoPagamento=TODOS" \
        "&dataInicio=01/09/2026&dataFim=30/09/2026" in url


def test_rota_que_da_500_cede_a_vez_para_a_seguinte(tmp_path):
    """Um endereço aprendido que morreu não pode travar a rodada: a próxima
    conhecida é tentada, e a que funcionou passa a ser a primeira."""
    rotas = sb.Rotas(tmp_path / "r.json")
    rotas.aprender("lista", "/api/comprovantes/que-morreu")
    pagina = Pagina({("GET", "/api/comprovantes/que-morreu"): ERRO_500,
                     ("GET", LISTA_NOVA): {"dado": [TITULO]}})
    assert sb.listar(pagina, "01/09/2026", "30/09/2026", rotas=rotas) == [TITULO]
    assert sb.Rotas(tmp_path / "r.json").candidatas("lista")[0] == LISTA_NOVA


def test_nenhuma_rota_conhecida_serve_entao_aprende_pela_tela(rotas, monkeypatch):
    novissima = "/api/comprovantes/v3/lista?canal=ib"
    monkeypatch.setattr(sb, "ROTAS_LISTA", (LISTA_ANTIGA,))
    monkeypatch.setattr(sb, "_descobrir_rota_da_lista", lambda _p: novissima)
    pagina = Pagina({("GET", LISTA_ANTIGA): ERRO_500,
                     ("GET", novissima): {"dado": [TITULO]}})
    assert sb.listar(pagina, "01/09/2026", "30/09/2026", rotas=rotas) == [TITULO]
    assert rotas.candidatas("lista")[0] == novissima
    guardado = json.loads(rotas.caminho.read_text(encoding="utf-8"))
    assert guardado["lista"] == novissima


def test_sem_rota_e_sem_aprender_a_mensagem_diz_que_a_tela_mudou(rotas, monkeypatch):
    monkeypatch.setattr(sb, "_descobrir_rota_da_lista", lambda _p: "")
    pagina = Pagina({("GET", LISTA_NOVA): ERRO_500, ("GET", LISTA_ANTIGA): ERRO_500})
    with pytest.raises(sb.SicoobFalhou) as e:
        sb.listar(pagina, "01/09/2026", "30/09/2026", rotas=rotas)
    assert "mudou" in str(e.value)


def test_400_com_motivo_de_verdade_nao_troca_de_rota(rotas):
    """400 com texto é o servidor ENTENDENDO o pedido e recusando — a rota
    está certa. Trocar de rota aqui esconderia o motivo real."""
    pagina = Pagina({("GET", LISTA_NOVA): {"status": 400, "erro": "HTTP 400",
                                          "corpo": "periodo fora do limite"}})
    with pytest.raises(sb.SicoobFalhou) as e:
        sb.listar(pagina, "01/01/2020", "31/01/2020", rotas=rotas)
    assert "periodo fora do limite" in str(e.value)
    assert len(pagina.pedidos) == 1


def test_a_frase_nova_de_conta_parada_e_conta_parada(rotas):
    """A frase exata que o endereço novo devolveu em 25/09/2026."""
    parada = {"status": 400, "erro": "HTTP 400",
              "corpo": '{"titulo":"Internet Banking","mensagem":"Não existem '
                       'comprovantes para essa conta corrente no período '
                       'informado","status":400}'}
    pagina = Pagina({("GET", LISTA_NOVA): parada})
    assert sb.listar(pagina, "01/01/2026", "02/01/2026", rotas=rotas) == []


def test_rota_da_url_capturada_tira_so_os_filtros():
    url = ("https://ib.sicoob.com.br/sicoobnet/api/comprovantes/pagamentos?"
           "isNovaEmissao=true&tipoPagamento=TODOS&dataInicio=01/09/2026"
           "&dataFim=30/09/2026")
    assert sb.rota_da_url(url) == LISTA_NOVA
    assert sb.rota_da_url(
        "https://ib.sicoob.com.br/sicoobnet/api/comprovantes/pagamentos") == DOC_NOVO


def test_rota_de_outro_site_nunca_e_aprendida():
    assert sb.rota_da_url("https://outro.site/sicoobnet/api/x") == ""
    assert sb.rota_da_url("https://ib.sicoob.com.br/sicoobnet/ib/#/home") == ""


def test_arquivo_de_rotas_ilegivel_volta_as_conhecidas(tmp_path):
    caminho = tmp_path / "r.json"
    caminho.write_text("{quebrado", encoding="utf-8")
    assert sb.Rotas(caminho).candidatas("lista")[0] == LISTA_NOVA
    caminho.write_text(json.dumps({"lista": "https://outro.site/x"}), encoding="utf-8")
    assert sb.Rotas(caminho).candidatas("lista")[0] == LISTA_NOVA


# ------------------------------------------------------------------ os Pix

def test_os_pix_saem_da_lista_dos_comprovantes_comuns():
    """Regra do dono: Pix só pela tela de Extrato Pix. A lista nova passou a
    trazer os Pix também, e baixá-los aqui duplicaria cada um."""
    pix_chave = {"idAgendamento": "E00000000202609010000AAAAAAAAAAA",
                 "tipoAgendamento": "Pix via chave", "tipoOperacaoPix": "Pagamento",
                 "situacao": "EFETIVADO"}
    pix_qr = {"idAgendamento": "E00000000202609010000AAAAAAAAAAB",
              "tipoAgendamento": "Pix copia e cola", "tipoOperacaoPix": "Pagamento",
              "situacao": "EFETIVADO"}
    transf = {"idAgendamento": "10000002", "situacao": "EFETIVADO",
              "tipoAgendamento": "TRANSF.CTA.CORRENTE X CTA.CORRENTE"}
    assert sb.sem_pix([pix_chave, TITULO, pix_qr, transf]) == [TITULO, transf]


# --------------------------------------------------------------- o documento

def test_o_documento_vem_do_endereco_novo(rotas):
    pagina = Pagina({("POST", DOC_NOVO): {"dado": [{"comprovanteBase64": False,
                                                    "comprovante": "<div>ok</div>"}]}})
    assert sb.detalhar(pagina, [TITULO], rotas=rotas) == [(TITULO, "<div>ok</div>")]
    assert pagina.pedidos[0] == ("POST", "https://ib.sicoob.com.br/sicoobnet" + DOC_NOVO)


def test_o_documento_cai_para_o_endereco_antigo(tmp_path):
    rotas = sb.Rotas(tmp_path / "r.json")
    pagina = Pagina({("POST", DOC_NOVO): ERRO_500,
                     ("POST", DOC_ANTIGO): {"dado": [{"comprovante": "<p>a</p>"}]}})
    assert sb.detalhar(pagina, [TITULO], rotas=rotas) == [(TITULO, "<p>a</p>")]
    assert sb.Rotas(tmp_path / "r.json").candidatas("documento")[0] == DOC_ANTIGO


def test_o_documento_aprende_pela_tela(rotas, monkeypatch):
    novissima = "/api/comprovantes/emitir"
    monkeypatch.setattr(sb, "ROTAS_DOCUMENTO", (DOC_ANTIGO,))
    monkeypatch.setattr(sb, "_descobrir_rota_do_documento",
                        lambda _p, _i: novissima)
    pagina = Pagina({("POST", DOC_ANTIGO): ERRO_500,
                     ("POST", novissima): {"dado": [{"comprovante": "<p>b</p>"}]}})
    assert sb.detalhar(pagina, [TITULO, dict(TITULO, idAgendamento="2")],
                       rotas=rotas) == [(TITULO, "<p>b</p>"),
                                        (dict(TITULO, idAgendamento="2"), "<p>b</p>")]
    # aprendeu UMA vez, e o segundo item já foi direto
    assert [u for m, u in pagina.pedidos].count(
        "https://ib.sicoob.com.br/sicoobnet" + DOC_ANTIGO) == 1


def test_documento_em_base64_sai_como_pdf_pronto(rotas):
    pdf = b"%PDF-1.4 comprovante"
    pagina = Pagina({("POST", DOC_NOVO): {"dado": [{
        "comprovanteBase64": True,
        "comprovante": base64.b64encode(pdf).decode()}]}})
    assert sb.detalhar(pagina, [TITULO], rotas=rotas) == [(TITULO, pdf)]


def test_documento_que_nao_vem_fica_vazio_e_nao_derruba_os_outros(rotas, monkeypatch):
    monkeypatch.setattr(sb, "_descobrir_rota_do_documento", lambda _p, _i: "")
    pagina = Pagina({("POST", DOC_NOVO): ERRO_500, ("POST", DOC_ANTIGO): ERRO_500})
    assert sb.detalhar(pagina, [TITULO], rotas=rotas) == [(TITULO, "")]


def test_pdf_pronto_e_gravado_sem_passar_pelo_navegador(tmp_path):
    destino = tmp_path / "x.pdf"
    sb.gravar_comprovante(None, b"%PDF-1.4 x", destino)
    assert destino.read_bytes() == b"%PDF-1.4 x"


# ------------------------------------------- a falha dos comuns e o Pix

def test_falha_nos_comuns_nao_impede_o_pix(monkeypatch, tmp_path):
    """O que aconteceu em 25/09/2026: a lista dos comuns deu 500, a conta
    inteira abortou, e o Pix — que funcionava — nem foi tentado."""
    class Cli:
        page = object()
        ctx = object()

        def acessar_conta(self, _n):
            return True

    monkeypatch.setattr(sb, "ir_para_comprovantes", lambda _p: None)
    monkeypatch.setattr(sb, "conta_aberta", lambda _p: "12.345-6")

    def lista_quebrada(*_a, **_k):
        raise sb.SicoobFalhou("a tela de Comprovantes mudou")

    monkeypatch.setattr(sb, "listar", lista_quebrada)
    chamado = []
    monkeypatch.setattr(sb, "_baixar_pix_da_conta",
                        lambda *a, **k: chamado.append(a[1]))
    r = sb.baixar_conta(Cli(), "12.345-6", "01/09/2026", "30/09/2026", tmp_path,
                        log=lambda _m: None)
    assert chamado == ["12.345-6"]
    assert "mudou" in r.motivo, "a falha dos comuns continua aparecendo"


# --------------------------------------------------------- F1: `_escutar`

class PaginaEscuta:
    """Como o Playwright sync de verdade: `on(evento, f)` faz
    `setattr(f, "_pw_impl_instance_", ...)` no handler recebido, e o
    `remove_listener` tem de receber o MESMO objeto que foi passado ao `on`.
    Um `list.append` (método embutido) recusa `setattr` com `AttributeError`."""

    def __init__(self):
        self._handler = None

    def on(self, _evento, f):
        setattr(f, "_pw_impl_instance_", object())
        self._handler = f

    def remove_listener(self, _evento, f):
        assert f is self._handler, "remove_listener recebeu outro objeto"

    def wait_for_timeout(self, _ms):
        pass


class _Resp:
    def __init__(self, url):
        self.url = url


def test_escutar_sobrevive_ao_setattr_do_playwright_sync():
    pagina = PaginaEscuta()
    resposta = _Resp("https://ib.sicoob.com.br/sicoobnet/api/x")

    def acao():
        pagina._handler(resposta)

    assert sb._escutar(pagina, acao, lambda _r: True) == resposta.url


# --------------------------------------------------- F2: `rota_da_url` segura

def test_rota_da_url_nao_aprende_parametro_de_conta():
    url = ("https://ib.sicoob.com.br/sicoobnet/api/comprovantes/pagamentos?"
          "isNovaEmissao=true&numeroContaCorrente=123450&dataInicio=01/09/2026")
    assert sb.rota_da_url(url) == ""


def test_rota_da_url_nao_aprende_caminho_com_conta():
    assert sb.rota_da_url(
        "https://ib.sicoob.com.br/sicoobnet/api/contas/123450/comprovantes") == ""


def test_rota_da_url_descarta_paginacao_e_filtro():
    url = ("https://ib.sicoob.com.br/sicoobnet/api/comprovantes/pagamentos?"
          "isNovaEmissao=true&page=0&size=10")
    assert sb.rota_da_url(url) == "/api/comprovantes/pagamentos?isNovaEmissao=true"


# --------------------------------------------- F3: lista vazia não é prova

def test_lista_vazia_nao_aprende_a_rota():
    """`all([])` é True — uma lista vazia não pode passar por prova de que o
    endereço é o certo."""
    assert sb._e_resposta_da_lista(
        type("R", (), {"request": type("Q", (), {"method": "GET"})(),
                       "url": "https://ib.sicoob.com.br/sicoobnet" + LISTA_NOVA
                       + "&dataInicio=01/09/2026",
                       "status": 200, "json": lambda self=None: []})()) is False


def test_400_so_vale_prova_se_caminho_tem_comprovante():
    falso = type("R", (), {
        "request": type("Q", (), {"method": "GET"})(),
        "url": "https://ib.sicoob.com.br/sicoobnet/api/contas/dataInicio=01/09",
        "status": 400,
        "text": lambda self=None: "nenhum registro",
    })()
    assert sb._e_resposta_da_lista(falso) is False


# ------------------------------------------------- F4: `_conteudo` seguro

def test_conteudo_sem_base64_exige_tag():
    assert sb._conteudo({"dado": [{"comprovanteBase64": False,
                                   "comprovante": "so texto solto"}]}) == ""
    assert sb._conteudo({"dado": [{"comprovanteBase64": False,
                                   "comprovante": "<div>ok</div>"}]}) == "<div>ok</div>"


def test_conteudo_base64_so_aceita_pdf_de_verdade():
    pdf = b"%PDF-1.4 x"
    assert sb._conteudo({"dado": [{"comprovanteBase64": True,
                                   "comprovante": base64.b64encode(pdf).decode()}]}) == pdf


def test_conteudo_base64_lixo_vira_vazio():
    lixo = base64.b64encode(b"nada a ver").decode()
    assert sb._conteudo({"dado": [{"comprovanteBase64": True,
                                   "comprovante": lixo}]}) == ""


# --------------------------------------------- F5: não aprende rota de erro

def test_detalhar_nao_aprende_rota_que_respondeu_erro(tmp_path):
    rotas = sb.Rotas(tmp_path / "r.json")
    pagina = Pagina({("POST", DOC_NOVO): {"status": 400, "erro": "HTTP 400",
                                          "corpo": "item invalido"},
                     ("POST", DOC_ANTIGO): {"dado": [{"comprovante": "<p>ok</p>"}]}})
    assert sb.detalhar(pagina, [TITULO], rotas=rotas) == [(TITULO, "<p>ok</p>")]
    assert sb.Rotas(tmp_path / "r.json").candidatas("documento")[0] == DOC_ANTIGO


# ------------------------------------------ F6: Emitir desliga window.print

def test_emitir_desliga_window_print_antes_do_clique():
    fonte = inspect.getsource(sb._descobrir_rota_do_documento)
    pos_print = fonte.index("window.print")
    pos_clique = fonte.index("emitir.first.evaluate")
    assert pos_print < pos_clique


# ------------------------------------------------------- F7: sem_pix avisa

def test_baixar_conta_avisa_quantos_pix_ficam_para_o_extrato(monkeypatch, tmp_path):
    class Cli:
        page = object()
        ctx = object()

        def acessar_conta(self, _n):
            return True

    pix = {"idAgendamento": "E0111", "tipoAgendamento": "Pix via chave",
          "tipoOperacaoPix": "Pagamento", "situacao": "EFETIVADO"}
    monkeypatch.setattr(sb, "ir_para_comprovantes", lambda _p: None)
    monkeypatch.setattr(sb, "conta_aberta", lambda _p: "12.345-6")
    monkeypatch.setattr(sb, "listar", lambda *a, **k: [pix])
    monkeypatch.setattr(sb, "_baixar_pix_da_conta", lambda *a, **k: None)
    mensagens = []
    sb.baixar_conta(Cli(), "12.345-6", "01/09/2026", "30/09/2026", tmp_path,
                    log=mensagens.append)
    assert any("Pix ficam para o Extrato Pix" in m for m in mensagens)


# --------------------------------------- F8: erro repetido não é "mudou"

def test_rota_aprendida_repete_erro_diz_que_a_tela_nao_mudou(rotas, monkeypatch):
    """Rotas conhecidas dão 500 e a própria tela devolve UMA delas de novo —
    não é a tela que mudou, é uma instabilidade do endereço certo."""
    monkeypatch.setattr(sb, "_descobrir_rota_da_lista", lambda _p: LISTA_NOVA)
    pagina = Pagina({("GET", LISTA_NOVA): ERRO_500, ("GET", LISTA_ANTIGA): ERRO_500})
    with pytest.raises(sb.SicoobFalhou) as e:
        sb.listar(pagina, "01/09/2026", "30/09/2026", rotas=rotas)
    msg = str(e.value)
    assert "não consegui aprender" not in msg
    assert "tente de novo" in msg
    assert "o endereço é o mesmo" in msg


def test_conta_errada_na_tela_continua_sem_pix(monkeypatch, tmp_path):
    """A trava de conta vale para os DOIS: sem ela o Pix de outra empresa
    sairia com o nome desta."""
    class Cli:
        page = object()
        ctx = object()

        def acessar_conta(self, _n):
            return True

    monkeypatch.setattr(sb, "ir_para_comprovantes", lambda _p: None)
    monkeypatch.setattr(sb, "conta_aberta", lambda _p: "99.999-9")
    chamado = []
    monkeypatch.setattr(sb, "_baixar_pix_da_conta",
                        lambda *a, **k: chamado.append(a[1]))
    r = sb.baixar_conta(Cli(), "12.345-6", "01/09/2026", "30/09/2026", tmp_path,
                        log=lambda _m: None)
    assert chamado == []
    assert "99.999-9" in r.motivo
