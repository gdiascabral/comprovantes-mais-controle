"""Leitura por IA ligada à leitura do dia. Sem rede, sem OCR, sem janela:
o cliente da API é um dublê. Dados fictícios."""
import json
from decimal import Decimal as D
from types import SimpleNamespace as NS

from pagamentos_dia import ia_do_dia as ia
from pagamentos_dia import leitura_ia as li


def _leitura(**k):
    base = {"tipo_papel": "recibo", "legivel": True, "total": "410,00",
            "total_por_extenso": "quatrocentos e dez reais", "ordem_de_compra": "6803",
            "numero_documento": "", "data": "", "quadra": "26A", "lote": "10", "itens": [],
            "cartao_valor": "", "cartao_nome": "", "duvidas": []}
    base.update(k)
    return base


class Cliente:
    def __init__(self, leitura=None, erro=None):
        self.chamadas = 0
        self._leitura, self._erro = leitura or _leitura(), erro
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.chamadas += 1
        if self._erro:
            raise self._erro
        return NS(stop_reason="end_turn", usage=NS(input_tokens=100, output_tokens=10),
                  content=[NS(type="text", text=json.dumps(self._leitura))])


def _ia(tmp_path, cliente=None, teto=60):
    return ia.IaDoDia(cliente or Cliente(), li.CacheLeituras(tmp_path / "c.json"), teto=teto)


def _item(ident="L1", valor=410.0, tp="T1"):
    return {"id": ident, "tradePayableId": tp, "remainingValue": valor,
            "paidTo": "Fornecedor Modelo Ltda", "plannedDate": "2026-11-25",
            "costCentreDetails": [{"workName": "OBRA MODELO QD 26A LT 10"}]}


def _anexo(nome="recibo.jpg", tag="Outros", **k):
    return {"filename": nome, "tagName": tag, "extension": "." + nome.rsplit(".", 1)[-1],
            "downloadUrl": f"https://exemplo.invalid/{nome}", **k}


# ---------------------------------------------------------------- sessão
def test_le_uma_vez_e_depois_vem_do_cache(tmp_path):
    c = Cliente()
    s = _ia(tmp_path, c)
    assert s.ler("k", b"x", "image/jpeg")["origem"] == "api"
    assert s.ler("k", b"x", "image/jpeg")["origem"] == "cache"
    assert c.chamadas == 1 and (s.feitas, s.do_cache) == (1, 1)
    assert s.custo_estimado_usd == D("0.02")


def test_falha_nao_e_guardada_e_conta(tmp_path):
    s = _ia(tmp_path, Cliente(erro=li.LeituraFalhou("caiu")))
    r = s.ler("k", b"x", "image/jpeg")
    assert r == {"ok": False, "erro": "caiu"} and s.falhas == 1
    assert s.cache.obter("k") is None


def test_erro_inesperado_tambem_falha_fechado(tmp_path):
    r = _ia(tmp_path, Cliente(erro=RuntimeError("x"))).ler("k", b"x", "image/png")
    assert r["ok"] is False


def test_teto_para_de_pedir_mas_o_cache_continua_valendo(tmp_path):
    c = Cliente()
    s = _ia(tmp_path, c, teto=1)
    s.ler("a", b"x", "image/jpeg")
    r = s.ler("b", b"x", "image/jpeg")
    assert r["ok"] is False and "teto" in r["pulado"] and s.acima_do_teto == 1
    assert s.ler("a", b"x", "image/jpeg")["origem"] == "cache"
    assert c.chamadas == 1


def test_resumo_traz_contagens_e_custo(tmp_path):
    s = _ia(tmp_path)
    s.ler("a", b"x", "image/jpeg")
    texto = s.resumo()
    assert "1 lida(s)" in texto and "0 do cache" in texto and "0 falha" in texto
    assert "US$ 0.02" in texto


def test_chave_do_anexo_nao_usa_a_url_e_muda_com_o_conteudo():
    f = _anexo(id="a1", updatedAt="2026-11-01")
    k1 = ia.chave_do_anexo(f, b"abc")
    assert "exemplo.invalid" not in k1 and k1.startswith("a1|3|2026-11-01")
    sem_data = _anexo(id="a1")
    assert ia.chave_do_anexo(sem_data, b"abc") != ia.chave_do_anexo(sem_data, b"abd")


# ---------------------------------------------------------------- seleção
def _brutos(*urls, pdf=False):
    return {u: (b"dados", pdf) for u in urls}


def test_foto_sem_valor_no_ocr_vai_para_a_ia():
    f = _anexo()
    c = ia.selecionar([_item()], {"T1": [f]}, {}, _brutos(f["downloadUrl"]),
                      ocr_imagem=lambda d: "rabisco")
    assert list(c) == [f["downloadUrl"]] and c[f["downloadUrl"]]["ids"] == {"L1"}


def test_foto_cujo_ocr_acha_o_valor_nao_vai():
    f = _anexo()
    c = ia.selecionar([_item()], {"T1": [f]}, {}, _brutos(f["downloadUrl"]),
                      ocr_imagem=lambda d: "TOTAL 410,00")
    assert c == {}


def test_comprovante_e_aviso_pagar_para_nao_vao():
    a, b = _anexo("comprovante pix.jpg"), _anexo("pagar para fulano.jpg")
    c = ia.selecionar([_item()], {"T1": [a, b]}, {}, _brutos(a["downloadUrl"], b["downloadUrl"]),
                      ocr_imagem=lambda d: "")
    assert c == {}


def test_tipo_de_arquivo_que_a_api_nao_le_nao_vai():
    f = _anexo("foto.heic")
    assert ia.selecionar([_item()], {"T1": [f]}, {}, _brutos(f["downloadUrl"]),
                         ocr_imagem=lambda d: "") == {}


def test_anexo_que_nao_foi_guardado_como_bruto_nao_vai():
    f = _anexo()
    assert ia.selecionar([_item()], {"T1": [f]}, {}, {}, ocr_imagem=lambda d: "") == {}


def test_pdf_sem_texto_vai_e_pdf_com_o_valor_no_ocr_nao():
    f = _anexo("pedido.pdf", tag="Nota Fiscal")
    u = f["downloadUrl"]
    assert u in ia.selecionar([_item()], {"T1": [f]}, {u: ""}, _brutos(u, pdf=True))
    assert ia.selecionar([_item()], {"T1": [f]}, {u: "valor 410,00"}, _brutos(u, pdf=True)) == {}


def test_o_mesmo_anexo_serve_a_dois_lancamentos_do_titulo():
    f = _anexo()
    c = ia.selecionar([_item("L1"), _item("L2")], {"T1": [f]}, {}, _brutos(f["downloadUrl"]),
                      ocr_imagem=lambda d: "")
    assert c[f["downloadUrl"]]["ids"] == {"L1", "L2"}


def test_ler_candidatos_le_cada_url_uma_vez_e_loga_o_resumo(tmp_path):
    f = _anexo(id="a1")
    cands = ia.selecionar([_item()], {"T1": [f]}, {}, _brutos(f["downloadUrl"]),
                          ocr_imagem=lambda d: "")
    linhas = []
    r = ia.ler_candidatos(_ia(tmp_path), cands, log=linhas.append)
    assert r[f["downloadUrl"]]["ok"] and r[f["downloadUrl"]]["ids"] == {"L1"}
    assert any("Leitura por IA:" in x and "custo estimado" in x for x in linhas)


# ---------------------------------------------------------------- por lançamento
def _entrada(leitura=None, ok=True, ids=("L1",), erro="x", origem="api"):
    e = {"ok": ok, "ids": set(ids), "origem": origem}
    e.update({"leitura": leitura or _leitura()} if ok else {"erro": erro})
    return e


def test_leitura_do_item_bate_com_extenso_e_traz_oc_e_endereco():
    f = _anexo()
    r = ia.leitura_do_item(_item(), [f], {f["downloadUrl"]: _entrada()}, oc="6803")
    assert r["estado"] == li.BATE and r["total_lido"] == "410.00"
    assert r["provas"] == ["valor por extenso"] and r["oc"] == "OC 6803 ✓"
    assert r["endereco"].startswith("endereço ✓") and r["origem"] == "api"


def test_leitura_do_item_diverge_com_o_total_lido():
    f = _anexo()
    e = _entrada(_leitura(total="435,00", total_por_extenso=""))
    r = ia.leitura_do_item(_item(), [f], {f["downloadUrl"]: e})
    assert r["estado"] == li.DIVERGE and r["total_lido"] == "435.00"


def test_falha_vira_estado_falhou():
    f = _anexo()
    r = ia.leitura_do_item(_item(), [f], {f["downloadUrl"]: _entrada(ok=False, erro="prazo")})
    assert r["falhou"] and r["estado"] == ia.FALHOU and "prazo" in r["motivos"][0]


def test_so_vale_para_os_lancamentos_do_anexo_e_none_sem_anexo_lido():
    f = _anexo()
    leituras = {f["downloadUrl"]: _entrada(ids=("L9",))}
    assert ia.leitura_do_item(_item("L1"), [f], leituras) is None
    assert ia.leitura_do_item(_item("L1"), [], leituras) is None


def test_dois_anexos_divergencia_manda_e_falha_so_vale_sem_leitura_usavel():
    f1, f2 = _anexo("a.jpg"), _anexo("b.jpg")
    ruim = _entrada(_leitura(total="435,00", total_por_extenso=""))
    r = ia.leitura_do_item(_item(), [f1, f2], {f1["downloadUrl"]: _entrada(),
                                               f2["downloadUrl"]: ruim})
    assert r["estado"] == li.DIVERGE
    falha = _entrada(ok=False)
    r = ia.leitura_do_item(_item(), [f1, f2], {f1["downloadUrl"]: _entrada(),
                                               f2["downloadUrl"]: falha})
    assert r["estado"] == li.BATE                   # uma leitura boa e outra que falhou
    r = ia.leitura_do_item(_item(), [f2], {f2["downloadUrl"]: falha})
    assert r["estado"] == ia.FALHOU


# ---------------------------------------------------------------- revisão de dinheiro (25/11)
def test_valor_ja_provado_por_outro_anexo_nao_manda_a_foto():
    foto, nf = _anexo(), _anexo("nota.pdf", tag="Nota Fiscal")
    brutos = _brutos(foto["downloadUrl"])
    textos = {nf["downloadUrl"]: "TOTAL DA NOTA 410,00"}
    c = ia.selecionar([_item()], {"T1": [foto, nf]}, textos, brutos, ocr_imagem=lambda d: "")
    assert c == {}
    # sem o valor no texto da nota, a foto vai
    c = ia.selecionar([_item()], {"T1": [foto, nf]}, {nf["downloadUrl"]: "nota sem valor"},
                      brutos, ocr_imagem=lambda d: "")
    assert foto["downloadUrl"] in c


def test_linha_digitavel_valida_ou_qr_com_o_valor_em_outro_anexo_tambem_dispensa():
    foto, outro = _anexo(), _anexo("boleto.pdf", tag="Boleto")
    brutos = _brutos(foto["downloadUrl"])
    pix = "00020126" + "0014br.gov.bcb.pix" + "5406410.00" + "6304ABCD"
    campo = lambda tag, v: f"{tag}{len(v):02d}{v}"  # noqa: E731
    copia = "000201" + campo("54", "410.00")
    c = ia.selecionar([_item()], {"T1": [foto, outro]}, {}, brutos, ocr_imagem=lambda d: "",
                      qr_pix={outro["downloadUrl"]: [copia]})
    assert c == {} and pix
    c = ia.selecionar([_item()], {"T1": [foto, outro]}, {}, brutos, ocr_imagem=lambda d: "",
                      qr_pix={outro["downloadUrl"]: ["000201" + campo("54", "99.00")]})
    assert foto["downloadUrl"] in c


def test_arquivo_grande_demais_e_pulado_sem_gastar_teto(tmp_path):
    c = Cliente()
    s = _ia(tmp_path, c, teto=1)
    r = s.ler("g", b"x" * (5 * 1024 * 1024 + 1), "image/jpeg")
    assert r["ok"] is False and r["pulado"] == "arquivo grande demais para a IA"
    r = s.ler("p", b"x" * (30 * 1024 * 1024 + 1), "application/pdf")
    assert r["pulado"] == "arquivo grande demais para a IA"
    assert c.chamadas == 0 and s.feitas == 0 and s.grandes == 2
    assert s.ler("ok", b"x" * (5 * 1024 * 1024), "image/jpeg")["ok"] and s.feitas == 1


def test_tres_falhas_de_rede_seguidas_desligam_a_ia_na_geracao(tmp_path):
    c = Cliente(erro=li.FalhaDeRede("sem rede"))
    s = _ia(tmp_path, c)
    for k in "abc":
        assert s.ler(k, b"x", "image/png")["erro"] == "sem rede"
    r = s.ler("d", b"x", "image/png")
    assert r["ok"] is False and "desligada" in r["pulado"] and c.chamadas == 3
    assert s.desligada and "IA desligada nesta geração após 3 falhas" in s.resumo()


def test_sucesso_ou_falha_de_conteudo_zera_a_contagem_do_disjuntor(tmp_path):
    erros = [li.FalhaDeRede("a"), li.FalhaDeRede("b"), None, li.FalhaDeRede("c"),
             li.FalhaDeRede("d"), li.LeituraFalhou("recusou"), li.FalhaDeRede("e")]

    class Variado(Cliente):
        def _create(self, **kw):
            self._erro = erros.pop(0)
            return super()._create(**kw)
    s = _ia(tmp_path, Variado())
    for k in "abcdefg":
        s.ler(k, b"x", "image/png")
    assert not s.desligada and s.feitas == 7


def test_cache_continua_valendo_com_a_ia_desligada(tmp_path):
    c = Cliente()
    s = _ia(tmp_path, c)
    s.ler("k", b"x", "image/png")
    s.desligada = True
    assert s.ler("k", b"x", "image/png")["origem"] == "cache"


def test_cache_guarda_o_modelo_que_respondeu(tmp_path):
    class ComModelo(Cliente):
        def _create(self, **kw):
            r = super()._create(**kw)
            r.model = "modelo-que-respondeu"
            return r
    s = _ia(tmp_path, ComModelo())
    s.ler("k", b"x", "image/png")
    assert json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))["k"]["modelo"] ==         "modelo-que-respondeu"


def test_com_varios_anexos_conta_os_nao_lidos():
    f1, f2 = _anexo("a.jpg"), _anexo("b.jpg")
    pulado = {"ok": False, "pulado": "acima do teto", "ids": {"L1"}}
    r = ia.leitura_do_item(_item(), [f1, f2], {f1["downloadUrl"]: _entrada(),
                                               f2["downloadUrl"]: pulado})
    assert r["estado"] == li.BATE and r["anexos"] == 2 and r["nao_lidos"] == 1
    r = ia.leitura_do_item(_item(), [f1], {f1["downloadUrl"]: _entrada()})
    assert r["anexos"] == 1 and r["nao_lidos"] == 0


def test_so_pulados_vira_nao_lido_com_o_motivo():
    f = _anexo()
    r = ia.leitura_do_item(_item(), [f], {f["downloadUrl"]: {
        "ok": False, "pulado": "arquivo grande demais para a IA", "ids": {"L1"}}})
    assert r["estado"] == ia.NAO_LIDO and r["pulado"] and not r["falhou"]
    assert r["motivos"] == ["arquivo grande demais para a IA"]


def test_ilegivel_entre_outros_conta_como_nao_lido():
    f1, f2 = _anexo("a.jpg"), _anexo("b.jpg")
    ilegivel = _entrada(_leitura(legivel=False))
    r = ia.leitura_do_item(_item(), [f1, f2], {f1["downloadUrl"]: _entrada(),
                                               f2["downloadUrl"]: ilegivel})
    assert r["nao_lidos"] == 1


def test_anotar_na_atividade_so_leva_contagens(tmp_path):
    notas = []
    s = ia.IaDoDia(Cliente(), li.CacheLeituras(tmp_path / "c.json"),
                   anotar=lambda resumo, numeros: notas.append((resumo, numeros)))
    f = _anexo(id="a1")
    cands = ia.selecionar([_item()], {"T1": [f]}, {}, _brutos(f["downloadUrl"]),
                          ocr_imagem=lambda d: "")
    ia.ler_candidatos(s, cands, log=lambda *_: None)
    (resumo, numeros), = notas
    assert "Leitura por IA" in resumo
    assert numeros == {"feitas": 1, "cache": 0, "falhas": 0}
