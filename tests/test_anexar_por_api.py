# -*- coding: utf-8 -*-
"""O comprovante sobe pela API, e a tela é o plano B.

Sem navegador: a página é falsa e faz de conta que é o ERP — responde à
listagem, às etiquetas, ao batch e ao PUT no S3 — e anota cada chamada. O que
se prova aqui é o CONTRATO (o que sai, em que ordem, com que cabeçalho) e os
desfechos: quando é "anexado", quando é "ja_anexado", e em quais erros a tela
ainda pode tentar (nada subiu) e em quais NÃO pode (o arquivo pode estar lá).
"""
import base64

import pytest

from anexar import mc_api
from anexar.anexar_comprovantes import RESULTADOS_OK, anexar_um

HOST = "https://prod-erp-api.maiscontroleerp.com.br"
CABECALHOS = {"accept": "application/json, text/plain, */*",
              "authorization": "Bearer jwt-de-teste",
              "company-id": "empresa-1"}
PAID = "paid-0001"
URL_S3 = "https://bucket.s3.sa-east-1.amazonaws.com/anexos/x.pdf?X-Amz-Signature=abc"


class PaginaFalsa:
    """O bastante de `page.evaluate` para o contrato do anexo — e o ERP por trás.

    `anexos` é a listagem do sub-pagamento; `tags` a lista de etiquetas (ou um
    status, para simular recusa); `batch` é None (aceita) ou o status da
    recusa; `put_status` o que o S3 responde; `lista_apos_put` diz se o
    arquivo passa a aparecer na listagem depois do PUT."""

    def __init__(self, anexos=None, tags=None, batch=None, put_status=200,
                 lista_apos_put=True, listagem_erro=None):
        self.url = "https://acessar.maiscontroleerp.com.br/#/payable-installments"
        self.anexos = list(anexos or [])
        self.tags = tags if tags is not None else [
            {"id": "tag-nf", "name": "Nota Fiscal"},
            {"id": "tag-comp", "name": "Comprovante"}]
        self.batch = batch
        self.put_status = put_status
        self.lista_apos_put = lista_apos_put
        self.listagem_erro = listagem_erro
        self.chamadas: list[tuple] = []
        self._pendente = None

    def on(self, _evento, _funcao):
        pass

    def evaluate(self, js, arg):
        if js is mc_api._JS_FETCH_JSON:
            return self._get(arg["url"], arg["headers"])
        if js is mc_api.JS_POST_JSON:
            return self._post(arg["url"], arg["headers"], arg["corpo"])
        if js is mc_api._JS_PUT_S3:
            return self._put(arg["url"], arg["contentType"], arg["b64"])
        raise AssertionError("bloco JS desconhecido")

    def _get(self, url, headers):
        self.chamadas.append(("GET", url, headers))
        if "/attachments/tags" in url:
            return {"__erro": self.tags} if isinstance(self.tags, int) else self.tags
        if "/attachments/v2?" in url:
            if self.listagem_erro:
                return {"__erro": self.listagem_erro}
            return list(self.anexos)
        raise AssertionError(f"GET inesperado: {url}")

    def _post(self, url, headers, corpo):
        self.chamadas.append(("POST", url, headers, corpo))
        if isinstance(self.batch, int):
            return {"__erro": self.batch, "__corpo": {"message": "recusado"}}
        self._pendente = corpo["attachmentsItem"][0]
        return {"attachments": [{"id": "anexo-1", "presignedUrl": URL_S3}]}

    def _put(self, url, content_type, b64):
        self.chamadas.append(("PUT", url, {"content-type": content_type}, b64))
        if self.put_status >= 300:
            return {"status": self.put_status, "body": "AccessDenied"}
        if self.lista_apos_put and self._pendente:
            self.anexos.append({"id": "anexo-1", "filename": self._pendente["name"],
                                "extension": "." + self._pendente["extension"],
                                "sizeInBytes": self._pendente["sizeInBytes"]})
        return {"status": 200, "body": ""}

    def metodos(self):
        return [c[0] for c in self.chamadas]


class ClienteFalso:
    def __init__(self, pagina):
        self.page = pagina


def _api(pagina, com_credencial=True):
    api = mc_api.MCApi(ClienteFalso(pagina))
    if com_credencial:
        api._req_anexos = (f"{HOST}/attachments/v2", dict(CABECALHOS))
    return api


@pytest.fixture
def pdf(tmp_path):
    arquivo = tmp_path / "123,45 - Fornecedor A - 0109.pdf"
    arquivo.write_bytes(b"%PDF-1.4\n% comprovante de teste\n" + b"x" * 500)
    return arquivo


# ------------------------------------------------------------- o caminho feliz

def test_feliz_tags_batch_put_prova_e_anexado(pdf):
    pag = PaginaFalsa()
    r = _api(pag).anexar_por_api(PAID, pdf, log=lambda _m: None)
    assert r == "anexado"
    # listagem prévia, etiquetas, batch, PUT, listagem de prova — nessa ordem
    assert pag.metodos() == ["GET", "GET", "POST", "PUT", "GET"]
    assert "/attachments/v2?entityIds=paid-0001&entityOrigin=PAID" in pag.chamadas[0][1]
    assert pag.chamadas[1][1] == f"{HOST}/attachments/tags"


def test_o_batch_leva_o_corpo_do_contrato(pdf):
    pag = PaginaFalsa()
    _api(pag).anexar_por_api(PAID, pdf)
    _, url, headers, corpo = pag.chamadas[2]
    assert url == f"{HOST}/attachments/v2/batch"
    assert headers["authorization"] == "Bearer jwt-de-teste"
    assert headers["company-id"] == "empresa-1"
    assert corpo["entityOrigin"] == "PAID"
    assert corpo["entityId"] == PAID, "o comprovante fica no SUB-pagamento"
    (item,) = corpo["attachmentsItem"]
    assert item == {"name": pdf.name, "contentType": "application/pdf",
                    "extension": "pdf", "sizeInBytes": pdf.stat().st_size,
                    "tagId": "tag-comp"}


def test_o_put_vai_cru_para_o_s3_sem_cabecalho_do_erp(pdf):
    pag = PaginaFalsa()
    _api(pag).anexar_por_api(PAID, pdf)
    _, url, headers, b64 = pag.chamadas[3]
    assert url == URL_S3
    assert headers == {"content-type": "application/pdf"}, \
        "qualquer cabeçalho do ERP quebra a assinatura da URL"
    assert base64.b64decode(b64) == pdf.read_bytes()


def test_o_js_do_put_so_manda_content_type():
    assert "'Content-Type': contentType" in mc_api._JS_PUT_S3
    assert "authorization" not in mc_api._JS_PUT_S3.lower()
    assert "method: 'PUT'" in mc_api._JS_PUT_S3


# ------------------------------------------------------------------ já anexado

def test_ja_anexado_pelo_nome_nao_sobe_de_novo(pdf):
    pag = PaginaFalsa(anexos=[{"name": pdf.name.upper(), "extension": ".pdf"}])
    r = _api(pag).anexar_por_api(PAID, pdf)
    assert r == "ja_anexado"
    assert pag.metodos() == ["GET"], "nem etiqueta, nem batch, nem PUT"


def test_ja_anexado_pelo_nome_sem_extensao_mais_extension_com_ponto(pdf):
    """A listagem traz `filename` sem extensão e `extension` COM ponto."""
    pag = PaginaFalsa(anexos=[{"filename": pdf.stem, "extension": ".pdf"}])
    assert _api(pag).anexar_por_api(PAID, pdf) == "ja_anexado"


def test_ja_anexado_pelo_tamanho_quando_a_listagem_traz_bytes(pdf):
    pag = PaginaFalsa(anexos=[{"name": "outro nome (2).pdf", "extension": ".pdf",
                               "sizeInBytes": pdf.stat().st_size}])
    assert _api(pag).anexar_por_api(PAID, pdf) == "ja_anexado"
    assert pag.metodos() == ["GET"]


def test_anexo_diferente_no_mesmo_pagamento_nao_impede(pdf):
    pag = PaginaFalsa(anexos=[{"name": "boleto.pdf", "extension": ".pdf",
                               "sizeInBytes": 99}])
    assert _api(pag).anexar_por_api(PAID, pdf) == "anexado"


# ------------------------------------------------- batch recusado: a tela tenta

def test_batch_400_e_erro_batch_sem_put(pdf):
    pag = PaginaFalsa(batch=400)
    r = _api(pag).anexar_por_api(PAID, pdf)
    assert r == "erro:batch:400"
    assert "PUT" not in pag.metodos()
    assert pag.metodos().count("POST") == 1, "o POST nunca se repete daqui"
    assert mc_api.tela_pode_tentar(r)


def test_listagem_previa_recusada_e_erro_batch(pdf):
    pag = PaginaFalsa(listagem_erro=401)
    r = _api(pag).anexar_por_api(PAID, pdf)
    assert r == "erro:batch:listagem:401"
    assert pag.metodos() == ["GET"]
    assert mc_api.tela_pode_tentar(r)


def test_sem_etiqueta_comprovante_e_erro_batch(pdf):
    pag = PaginaFalsa(tags=[{"id": "tag-nf", "name": "Nota Fiscal"}])
    r = _api(pag).anexar_por_api(PAID, pdf)
    assert r == "erro:batch:sem_tag"
    assert "POST" not in pag.metodos()
    assert mc_api.tela_pode_tentar(r)


def test_sem_credencial_nao_toca_na_pagina(pdf):
    pag = PaginaFalsa()
    r = _api(pag, com_credencial=False).anexar_por_api(PAID, pdf)
    assert r == "erro:sem_credencial"
    assert pag.chamadas == []
    assert mc_api.tela_pode_tentar(r)


# ------------------------------------------ subiu e não confirmou: a tela NÃO tenta

def test_put_ok_mas_a_listagem_nao_mostra_e_nao_confirmado(pdf):
    pag = PaginaFalsa(lista_apos_put=False)
    r = _api(pag).anexar_por_api(PAID, pdf)
    assert r == "erro:nao_confirmado"
    assert pag.metodos() == ["GET", "GET", "POST", "PUT", "GET"]
    assert not mc_api.tela_pode_tentar(r), \
        "o arquivo pode estar lá: a tela anexaria uma segunda vez"


def test_s3_recusa_e_erro_upload_sem_segunda_tentativa(pdf):
    pag = PaginaFalsa(put_status=403)
    r = _api(pag).anexar_por_api(PAID, pdf)
    assert r == "erro:upload:403"
    assert pag.metodos().count("PUT") == 1
    assert pag.metodos().count("POST") == 1
    assert not mc_api.tela_pode_tentar(r), \
        "o batch já criou o registro: repetir pela tela é anexo em dobro"


def test_batch_sem_url_s3_e_erro_upload():
    """2xx sem URL: o registro pode ter nascido. Fica do lado que não duplica."""
    assert mc_api._primeira_url_s3({"attachments": [{"id": "a"}]}) is None
    assert mc_api._primeira_url_s3(
        {"x": [{"y": {"uploadUrl": URL_S3}}]}) == URL_S3
    assert mc_api._primeira_url_s3(
        {"link": "https://acessar.maiscontroleerp.com.br/#/x"}) is None


# --------------------------------------------------------------- a etiqueta

def test_a_tag_e_achada_sem_acento_e_sem_caixa(pdf):
    pag = PaginaFalsa(tags=[{"id": "t-1", "name": "Nota Fiscal"},
                            {"id": "t-2", "name": " COMPROVÁNTE "}])
    r = _api(pag).anexar_por_api(PAID, pdf, tag="comprovante")
    assert r == "anexado"
    assert pag.chamadas[2][3]["attachmentsItem"][0]["tagId"] == "t-2"


def test_a_tag_aceita_o_envelope_paginado():
    assert mc_api._achar_tag({"content": [{"id": "9", "name": "Comprovante"}]},
                             "COMPROVANTE") == "9"
    assert mc_api._achar_tag({"items": [{"id": "9", "name": "Comprovante"}]},
                             "comprovante") == "9"
    assert mc_api._achar_tag([{"id": "9", "name": "Comprovantes"}],
                             "Comprovante") is None, "parecido não é igual"


def test_a_tag_e_pedida_uma_vez_por_execucao(pdf, tmp_path):
    pag = PaginaFalsa()
    api = _api(pag)
    api.anexar_por_api(PAID, pdf)
    outro = tmp_path / "200,00 - Fornecedor A - 0209.pdf"
    outro.write_bytes(b"%PDF-1.4\n" + b"y" * 300)
    pag.anexos.clear()
    api.anexar_por_api("paid-0002", outro)
    tags = [c for c in pag.chamadas if c[0] == "GET" and "/tags" in c[1]]
    assert len(tags) == 1


def test_tags_recusadas_e_erro_batch(pdf):
    pag = PaginaFalsa(tags=500)
    r = _api(pag).anexar_por_api(PAID, pdf)
    assert r == "erro:batch:tags:500"
    assert mc_api.tela_pode_tentar(r)


# ------------------------------------------------------------------ simular

def test_simular_para_antes_do_post_depois_de_provar_as_leituras(pdf):
    pag = PaginaFalsa()
    r = _api(pag).anexar_por_api(PAID, pdf, dry_run=True)
    assert r == "dry_run"
    assert pag.metodos() == ["GET", "GET"], "listagem e etiquetas; nada escrito"


# ------------------------------------------------------- o chamador: anexar_um

class TelaFalsa:
    """O `MCClient.anexar` e o `resetar`, só anotando por onde passou."""

    def __init__(self, respostas=("anexado",)):
        self.respostas = list(respostas)
        self.chamadas: list[str] = []

    def anexar(self, launch_id, valor, arquivo, doc=None, dry_run=True, valores=None):
        self.chamadas.append("anexar")
        return self.respostas.pop(0) if len(self.respostas) > 1 else self.respostas[0]

    def resetar(self):
        self.chamadas.append("resetar")


class ApiFalsa:
    def __init__(self, resposta):
        self.resposta = resposta
        self.chamadas: list[tuple] = []

    def anexar_por_api(self, paid_id, arquivo, *, log=None, dry_run=False, **_k):
        self.chamadas.append((paid_id, dry_run))
        return self.resposta


def _um(api, tela, paid_id=PAID, por_api=True, registro=None, dry_run=False):
    log = registro.append if registro is not None else None
    return anexar_um(tela, api, "launch-1", "123,45", "x.pdf", paid_id=paid_id,
                     dry_run=dry_run, log=log, por_api=por_api)


def test_api_anexou_e_a_tela_nao_e_chamada():
    api, tela, registro = ApiFalsa("anexado"), TelaFalsa(), []
    assert _um(api, tela, registro=registro) == "anexado"
    assert api.chamadas == [(PAID, False)]
    assert tela.chamadas == []
    assert any("pela API" in linha for linha in registro), "o Registro diz o caminho"


def test_batch_recusado_cai_para_a_tela():
    api, tela, registro = ApiFalsa("erro:batch:400"), TelaFalsa(), []
    assert _um(api, tela, registro=registro) == "anexado"
    assert tela.chamadas == ["anexar"]
    assert any("indo pela tela" in linha for linha in registro)


def test_sem_credencial_cai_para_a_tela():
    api, tela = ApiFalsa("erro:sem_credencial"), TelaFalsa()
    assert _um(api, tela) == "anexado"
    assert tela.chamadas == ["anexar"]


def test_nao_confirmado_NAO_cai_para_a_tela():
    api, tela = ApiFalsa("erro:nao_confirmado"), TelaFalsa()
    assert _um(api, tela) == "erro:nao_confirmado"
    assert tela.chamadas == [], "o arquivo pode estar lá; a tela duplicaria"
    assert len(api.chamadas) == 1, "e a API não repete o POST"


def test_erro_de_upload_NAO_cai_para_a_tela():
    api, tela = ApiFalsa("erro:upload:403"), TelaFalsa()
    assert _um(api, tela) == "erro:upload:403"
    assert tela.chamadas == []


def test_ja_anexado_conta_como_ok_e_nao_vai_a_tela():
    api, tela = ApiFalsa("ja_anexado"), TelaFalsa()
    assert _um(api, tela) == "ja_anexado"
    assert tela.chamadas == []
    assert "ja_anexado" in RESULTADOS_OK


def test_a_tela_mantem_a_retentativa_com_resetar():
    api = ApiFalsa("erro:batch:500")
    tela = TelaFalsa(respostas=("erro:timeout", "anexado"))
    assert _um(api, tela) == "anexado"
    assert tela.chamadas == ["anexar", "resetar", "anexar"]


def test_sem_paid_id_vai_direto_pela_tela():
    """O modo "Por lista" só traz o link da parcela: a API não tem como."""
    api, tela = ApiFalsa("anexado"), TelaFalsa()
    assert _um(api, tela, paid_id=None) == "anexado"
    assert api.chamadas == []
    assert tela.chamadas == ["anexar"]


def test_com_a_chave_desligada_a_api_nem_e_chamada():
    api, tela = ApiFalsa("anexado"), TelaFalsa()
    assert _um(api, tela, por_api=False) == "anexado"
    assert api.chamadas == []
    assert tela.chamadas == ["anexar"]


def test_a_chave_vem_do_config(monkeypatch):
    from anexar import config
    monkeypatch.setattr(config, "ANEXAR_POR_API", False)
    api, tela = ApiFalsa("anexado"), TelaFalsa()
    anexar_um(tela, api, "launch-1", "1,00", "x.pdf", paid_id=PAID)
    assert api.chamadas == [] and tela.chamadas == ["anexar"]


def test_simular_passa_pela_api_em_modo_simular():
    api, tela = ApiFalsa("dry_run"), TelaFalsa()
    assert _um(api, tela, dry_run=True) == "dry_run"
    assert api.chamadas == [(PAID, True)]
    assert tela.chamadas == []
