"""A leitura por IA ponta a ponta na leitura do dia: do anexo sem texto até o
nível da linha. Sem rede e sem OCR: dublês. Dados fictícios."""
import json
from types import SimpleNamespace as NS

from pagamentos_dia import ia_do_dia, nivel
from pagamentos_dia import leitura_do_dia as ld
from pagamentos_dia import leitura_ia as li
from tests.test_leitura_do_dia import DIA, LEITORES, ApiFalsa, _anexo, _lanc, _sem_cadastro, _sem_nuvem

FOTO = _anexo("recibo", tag="Outros", ext=".jpg")


def _leitura(**k):
    base = {"tipo_papel": "recibo", "legivel": True, "total": "100,00",
            "total_por_extenso": "cem reais", "ordem_de_compra": "", "numero_documento": "",
            "data": "", "quadra": "", "lote": "", "itens": [], "cartao_valor": "",
            "cartao_nome": "", "duvidas": []}
    base.update(k)
    return base


class Cliente:
    def __init__(self, leitura=None, erro=None):
        self.chamadas, self._l, self._erro = 0, leitura or _leitura(), erro
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.chamadas += 1
        if self._erro:
            raise self._erro
        return NS(stop_reason="end_turn", usage=NS(input_tokens=10, output_tokens=5),
                  content=[NS(type="text", text=json.dumps(self._l))])


def _ler(api, ia, **k):
    return ld.ler_pagamentos(api, DIA, DIA, abrir_historico=_sem_nuvem,
                             carregar_mapas=_sem_cadastro, ia=ia, **LEITORES, **k)


def _sessao(tmp_path, cliente, teto=60):
    return ia_do_dia.IaDoDia(cliente, li.CacheLeituras(tmp_path / "leituras_ia.json"), teto=teto)


def _linha(leitura):
    (ln,) = [r for c in leitura.resultado.contas.values() for r in c]
    return ln


def _api(**k):
    return ApiFalsa([_lanc("L1")], anexos={"T-L1": [FOTO]},
                    arquivos={FOTO["downloadUrl"]: b"\xff\xd8 foto ficticia"}, **k)


def test_baixar_textos_guarda_foto_e_pdf_sem_texto_so_quando_pedido():
    pdf = _anexo("pedido", ext=".pdf")
    alvos = [(FOTO["downloadUrl"], False, False), (pdf["downloadUrl"], True, True)]
    brutos = {}
    ld.baixar_textos(lambda u: b"bytes", alvos, brutos_ia=brutos, **LEITORES)
    assert set(brutos) == {FOTO["downloadUrl"], pdf["downloadUrl"]}
    assert brutos[FOTO["downloadUrl"]] == (b"bytes", False) and brutos[pdf["downloadUrl"]][1] is True
    # PDF com camada de texto e aviso "PAGAR PARA" (foto com texto lido) não são guardados.
    brutos = {}
    ld.baixar_textos(lambda u: b"bytes", alvos, brutos_ia=brutos,
                     **{**LEITORES, "texto_pdf": lambda d: "texto"})
    assert set(brutos) == {FOTO["downloadUrl"]}
    brutos = {}
    ld.baixar_textos(lambda u: b"bytes", [(FOTO["downloadUrl"], False, True)], brutos_ia=brutos,
                     **LEITORES)
    assert brutos == {}
    ld.baixar_textos(lambda u: b"bytes", alvos, **LEITORES)          # sem IA: nada muda


def test_sem_ia_a_linha_e_como_sempre(tmp_path):
    leitura = _ler(_api(), None)
    assert _linha(leitura).get("leitura_ia") is None and leitura.ia_resumo == ""


def test_foto_sem_texto_lida_por_ia_que_bate_e_olhe_nunca_pode_pagar(tmp_path):
    c = Cliente()
    leitura = _ler(_api(), _sessao(tmp_path, c))
    ln = _linha(leitura)
    assert c.chamadas == 1 and ln["leitura_ia"]["estado"] == li.BATE
    n = nivel.nivel_da_linha(ln)
    assert n.nome != nivel.PODE_PAGAR
    assert any(m.startswith("lido por IA: R$ 100,00 × lançamento R$ 100,00 — bate") for m in n.motivos)
    assert "1 lida(s) pela IA" in leitura.ia_resumo and "custo estimado" in leitura.ia_resumo


def test_diverge_vira_motivo_claro(tmp_path):
    leitura = _ler(_api(), _sessao(tmp_path, Cliente(_leitura(total="150,00", total_por_extenso=""))))
    n = nivel.nivel_da_linha(_linha(leitura))
    assert "lido por IA: R$ 150,00 × lançamento R$ 100,00 — diverge" in n.motivos


def test_falha_da_ia_e_nao_li_com_o_motivo(tmp_path):
    leitura = _ler(_api(), _sessao(tmp_path, Cliente(erro=li.LeituraFalhou("prazo"))))
    ln = _linha(leitura)
    assert ln["leitura_ia"]["falhou"]
    n = nivel.nivel_da_linha(ln)
    assert n.nome == nivel.NAO_LI and "IA não respondeu" in n.motivos
    assert "1 falha(s)" in leitura.ia_resumo


def test_segunda_geracao_vem_do_cache_sem_chamar_a_api(tmp_path):
    c = Cliente()
    _ler(_api(), _sessao(tmp_path, c))
    leitura = _ler(_api(), _sessao(tmp_path, c))
    assert c.chamadas == 1 and "1 do cache" in leitura.ia_resumo


def test_teto_deixa_a_linha_como_antes(tmp_path):
    leitura = _ler(_api(), _sessao(tmp_path, Cliente(), teto=0))
    ln = _linha(leitura)
    assert ln.get("leitura_ia") is None
    assert nivel.nivel_da_linha(ln).nome == nivel.NAO_LI
    assert "acima do teto" in leitura.ia_resumo


def test_ocr_que_acha_o_valor_dispensa_a_ia(tmp_path):
    c = Cliente()
    leitores = {**LEITORES, "ocr_imagem": lambda d: "TOTAL 100,00"}
    ld.ler_pagamentos(_api(), DIA, DIA, abrir_historico=_sem_nuvem, carregar_mapas=_sem_cadastro,
                      ia=_sessao(tmp_path, c), **leitores)
    assert c.chamadas == 0


def test_os_dados_do_erp_nao_vao_para_a_api(tmp_path):
    pedidos = []

    class Espia(Cliente):
        def _create(self, **kw):
            pedidos.append(json.dumps(kw, default=str))
            return super()._create(**kw)
    _ler(_api(), _sessao(tmp_path, Espia()))
    texto = pedidos[0]
    for dado in ("Fornecedor Modelo", "fornecedor@exemplo.com", "OBRA MODELO", "1234"):
        assert dado not in texto
