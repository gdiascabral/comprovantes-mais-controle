"""A leitura do dia, como a Remessa lê, sem tela. Lançamentos fictícios (o
formato é o de tests/test_regras_14_10.py)."""
from datetime import date

from pagamentos_dia import confirmacao
from pagamentos_dia import leitura_do_dia as ld
from pagamentos_dia import regras_pagamento as regras

DIA = date(2026, 10, 21)


def _lanc(ident, conta="CONTA EXEMPLO - SICOOB", **extra):
    item = {"id": ident, "tradePayableId": f"T-{ident}", "paidTo": "Fornecedor Modelo Ltda",
            "remainingValue": 100.0, "plannedDate": "2026-10-21",
            "tradePayableAccount": {"name": conta}, "tradePayablePaymentMethod": "Pix",
            "paidToBankAccount": "PIX EMAIL fornecedor@exemplo.com", "documentNumber": "1234",
            "costCentreDetails": [{"workName": "OBRA MODELO"}], "paid": False}
    item.update(extra)
    return item


def _anexo(nome, tag="Nota Fiscal", ext=".pdf"):
    return {"filename": nome, "tagName": tag, "extension": ext,
            "downloadUrl": f"https://exemplo.invalid/{nome}{ext}"}


class ApiFalsa:
    def __init__(self, lancamentos, anexos=None, arquivos=None, contatos=None):
        self._lanc, self._anexos = lancamentos, anexos or {}
        self._arq = arquivos or {}
        self._contatos = contatos
        self._req_anexos = ("https://exemplo.invalid/attachments/v2", {"authorization": "x"})
        self.titulos_sem_leitura, self.baixados, self.periodo = set(), [], None

    def capturar_credenciais(self, log=print):
        return True

    def capturar_credenciais_anexos(self, launch_id):
        return True

    def listar_a_pagar(self, ini, fim, log=print):
        self.periodo = (ini, fim)
        return list(self._lanc)

    def anexos_de_titulos(self, ids, log=print, progresso=None, cancelar=None):
        return {i: self._anexos.get(i, []) for i in ids}

    def listar_overviews(self, ids, log=print, progresso=None, cancelar=None):
        return {i: {} for i in ids}

    def listar_participantes(self, log=print):
        if isinstance(self._contatos, Exception):
            raise self._contatos
        return self._contatos or {}

    def baixar_anexo(self, url):
        self.baixados.append(url)
        return self._arq.get(url, b"%PDF-1.4 ficticio")


LEITORES = dict(ler_qr=lambda d, pdf: [], texto_pdf=lambda d: "",
                ocr_pdf=lambda d, log=print: "", ocr_imagem=lambda d: "")


def _sem_nuvem():
    raise RuntimeError("sem nuvem no teste")


def _sem_cadastro():
    raise RuntimeError("sem cadastro no teste")


def _ler(api, **k):
    return ld.ler_pagamentos(api, DIA, DIA, abrir_historico=_sem_nuvem,
                             carregar_mapas=_sem_cadastro, **LEITORES, **k)


def test_le_como_a_remessa_e_separa_quem_pode_sair():
    api = ApiFalsa([_lanc("L1"), _lanc("L2"), _lanc("L3", paid=True, sumOfPaidValues=100.0),
                    _lanc("L4", conta="PESSOA FISICA - APENAS LANCAMENTO")],
                   anexos={"T-L1": [_anexo("nota 1234")]})
    leitura = _ler(api)
    assert api.periodo == ("2026-10-21", "2026-10-21")
    assert leitura.resultado is not None and not leitura.interrompida
    linhas = [ln for g in leitura.grupos for ln in (*g.entram, *g.nao_aptos)]
    assert sorted(ln.id for ln in linhas) == ["L1", "L2"]          # pago e conta de ajuste fora
    sem_anexo = next(ln for ln in linhas if ln.id == "L2")
    assert sem_anexo.secao == confirmacao.NAO_APTO and sem_anexo.situacao == regras.MOTIVO_SEM_ANEXO
    assert any(confirmacao.AVISO_SEM_REGISTRO in a for a in leitura.avisos)
    assert any(confirmacao.AVISO_SEM_CADASTRO in a for a in leitura.avisos)


def test_baixa_cada_url_uma_vez_e_da_foto_so_le_o_qr():
    pdf, foto = _anexo("boleto"), _anexo("foto", tag="Outros", ext=".jpg")
    alvos = ld.anexos_a_ler([_lanc("L1"), _lanc("L2", tradePayableId="T-L1")], {"T-L1": [pdf, foto]})
    assert alvos == [(pdf["downloadUrl"], True, True), (foto["downloadUrl"], False, False)]
    lidos_qr = []
    textos, ocr, nao_lidos, qrs = ld.baixar_textos(
        lambda url: b"x", alvos, ler_qr=lambda d, p: lidos_qr.append(p) or ["000201PIX"],
        texto_pdf=lambda d: "texto do boleto", ocr_pdf=lambda d, log=print: "",
        ocr_imagem=lambda d: "")
    assert list(textos) == [pdf["downloadUrl"]] and lidos_qr == [True, False]
    assert set(qrs) == {pdf["downloadUrl"], foto["downloadUrl"]} and not nao_lidos and not ocr


def test_download_que_falha_vira_anexo_nao_lido():
    def baixar(url):
        raise OSError("caiu")
    _t, _o, nao_lidos, _q = ld.baixar_textos(baixar, [("u", True, True)], **LEITORES)
    assert nao_lidos == {"u"}


def test_parar_no_meio_nao_monta_resultado():
    api = ApiFalsa([_lanc("L1")], anexos={"T-L1": [_anexo("nota 1234")]})
    leitura = _ler(api, cancelar=lambda: True)
    assert leitura.interrompida and leitura.resultado is None and leitura.grupos == []


def test_contatos_que_falham_viram_aviso_e_a_leitura_segue():
    api = ApiFalsa([_lanc("L1")], anexos={"T-L1": [_anexo("nota 1234")]}, contatos=RuntimeError("401"))
    leitura = _ler(api)
    assert leitura.resultado is not None
    assert any("Contatos" in a for a in leitura.avisos)


def test_sem_lancamentos_e_resultado_vazio():
    leitura = _ler(ApiFalsa([]))
    assert leitura.resultado.contas == {} and leitura.grupos == []


# --- Além do brief: o "parar" visto UMA vez vale para a leitura inteira ------

def _parar_so_na_vez(n):
    """Um `cancelar` que diz "pare" só na n-ésima pergunta e depois volta a
    dizer "siga" — o Event limpo por outra rotina, ou o botão que alguém
    soltou. A leitura que parou no meio continua pela metade."""
    vezes = [0]

    def cancelar():
        vezes[0] += 1
        return vezes[0] == n
    return cancelar


def test_parar_durante_os_downloads_nao_vira_leitura_inteira():
    anexos = {"T-L1": [_anexo("nota 1")], "T-L2": [_anexo("nota 2")]}
    api = ApiFalsa([_lanc("L1"), _lanc("L2")], anexos=anexos)
    # 1ª pergunta: depois dos Contatos; 2ª: antes do 1º download -> pare.
    leitura = _ler(api, cancelar=_parar_so_na_vez(2))
    assert api.baixados == []                       # parou antes de baixar
    assert leitura.interrompida
    assert leitura.resultado is None and leitura.analise is None
    assert leitura.entradas is None and leitura.grupos == []


def test_parar_durante_a_lista_de_anexos_nao_vira_leitura_inteira():
    class ApiQueOuveOParar(ApiFalsa):
        def anexos_de_titulos(self, ids, log=print, progresso=None, cancelar=None):
            if cancelar and cancelar():
                return {}                           # a lista ficou pela metade
            return super().anexos_de_titulos(ids, log=log)

    api = ApiQueOuveOParar([_lanc("L1")], anexos={"T-L1": [_anexo("nota 1")]})
    leitura = _ler(api, cancelar=_parar_so_na_vez(1))
    assert leitura.interrompida and leitura.resultado is None and leitura.grupos == []


def test_baixar_textos_para_no_pedido_e_nao_baixa_o_resto():
    baixados = []
    alvos = [("a", True, True), ("b", True, True)]
    pedidos = iter([False, True])
    textos, _o, nao_lidos, _q = ld.baixar_textos(
        lambda url: baixados.append(url) or b"x", alvos,
        cancelar=lambda: next(pedidos), **LEITORES)
    assert baixados == ["a"] and list(textos) == ["a"] and not nao_lidos


def test_leitura_inteira_guarda_as_entradas_da_remessa():
    api = ApiFalsa([_lanc("L1"), _lanc("L3", paid=True, sumOfPaidValues=100.0)],
                   anexos={"T-L1": [_anexo("nota 1234")]})
    api.titulos_sem_leitura = {"T-L9"}
    leitura = _ler(api)
    assert [i["id"] for i in leitura.entradas.selecionados] == ["L1"]   # só o a pagar
    assert leitura.entradas.periodo == (DIA, DIA)
    assert leitura.entradas.titulos_nao_lidos == {"T-L9"}
    assert leitura.analise is not None and leitura.periodo == (DIA, DIA)


# ---------------------- adiantar boletos dos dias seguintes (dono, 29/10/2026)
def test_dos_dias_seguintes_so_entra_o_que_se_paga_por_codigo_de_barras():
    hoje_pix = _lanc("L1")
    futuro_boleto = _lanc("L2", plannedDate="2026-10-23", tradePayablePaymentMethod="Boleto")
    futuro_anexo = _lanc("L3", plannedDate="2026-10-24")         # Pix, mas com boleto anexado
    futuro_pix = _lanc("L4", plannedDate="2026-10-24")
    anexos = {"T-L3": [_anexo("boleto 1234", tag="Boleto")]}
    ficam, adiantados, fora = ld.separar_adiantados(
        [hoje_pix, futuro_boleto, futuro_anexo, futuro_pix], anexos, DIA)
    assert [i["id"] for i in ficam] == ["L1", "L2", "L3"]
    assert adiantados == {"L2", "L3"} and fora == 1


def test_leitura_com_adiantados_le_ate_o_fim_e_marca_a_obs():
    api = ApiFalsa([_lanc("L1"),
                    _lanc("L2", plannedDate="2026-10-23", tradePayablePaymentMethod="Boleto"),
                    _lanc("L4", plannedDate="2026-10-24")])
    leitura = _ler(api, adiantar_ate=date(2026, 10, 24))
    assert api.periodo == ("2026-10-21", "2026-10-24")
    assert leitura.periodo == (DIA, DIA)                      # o dia de trabalho não muda
    assert leitura.adiantados == {"L2"}
    ids = {i["id"] for i in leitura.lancamentos}
    assert ids == {"L1", "L2"}
    regs = [r for rs in leitura.resultado.contas.values() for r in rs]
    regs += leitura.resultado.omitidos
    l2 = [r for r in regs if r.get("id") == "L2"]
    assert l2, "o boleto adiantado tem de aparecer (apto ou não apto)"
    for r in regs:
        if r.get("id") == "L1":
            assert "adiantado" not in (r.get("obs") or "")


def test_sem_adiantar_nada_muda():
    api = ApiFalsa([_lanc("L1"), _lanc("L2", plannedDate="2026-10-23")])
    leitura = _ler(api)
    assert api.periodo == ("2026-10-21", "2026-10-21")
    assert leitura.adiantados == set() and leitura.entradas.adiantar_de is None


def test_obs_de_adiantado():
    assert confirmacao.obs_de_adiantado("2026-10-23", DIA) == "adiantado — vence 23/10"
    assert confirmacao.obs_de_adiantado("2026-10-21", DIA) == ""
    assert confirmacao.obs_de_adiantado("", DIA) == ""

    class R:
        contas = {"C": [{"vencimento": "2026-10-23", "obs": "x"},
                        {"vencimento": "2026-10-21", "obs": ""}]}
    confirmacao.marcar_adiantados(R, DIA)
    confirmacao.marcar_adiantados(R, DIA)                      # não repete
    assert R.contas["C"][0]["obs"] == "adiantado — vence 23/10 · x"
    assert R.contas["C"][1]["obs"] == ""
