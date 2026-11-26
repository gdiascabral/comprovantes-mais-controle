# -*- coding: utf-8 -*-
"""O saldo do Inter para a Prova de saldos. Sem Chrome: a parte de tela é
dublê; a lógica (resposta, conta aberta) é pura. Tela e números fictícios,
no formato medido ao vivo em 27/10/2026."""
from decimal import Decimal as D

import pytest

from baixar_comprovantes import inter_baixar as ib
from baixar_comprovantes import inter_saldo as m

TELA = ("Saldo\nR$ 1.234,56\n123456789\n\nEMPRESA FICTICIA LTDA\n"
        "Saldo em conta R$ 1.234,56")


def test_saldo_e_o_disponivel_em_decimal():
    dado = {"disponivel": 1234.56, "chequeEspecialDisponivel": 0.0,
            "disponivelComChequeEspecial": 1234.56}
    assert m.saldo_da_resposta(200, dado) == D("1234.56")
    assert m.saldo_da_resposta(200, {"disponivel": -12.3}) == D("-12.30")
    assert m.saldo_da_resposta(200, {"disponivel": 0}) == D("0.00")


@pytest.mark.parametrize("dado", [{}, {"disponivel": None}, {"disponivel": True},
                                  {"disponivel": "1.234,56"}, [], None])
def test_resposta_sem_disponivel_valido_nao_vira_saldo(dado):
    with pytest.raises(m.SaldoInterFalhou):
        m.saldo_da_resposta(200, dado)


def test_sessao_vencida_e_erro_do_banco():
    with pytest.raises(m.SaldoInterFalhou, match="sessão"):
        m.saldo_da_resposta(401, {"disponivel": 1})
    with pytest.raises(m.SaldoInterFalhou, match="HTTP 500"):
        m.saldo_da_resposta(500, None)


def test_numero_no_texto_da_tela_medida():
    assert ib.numero_no_texto(TELA) == "123456789"
    assert ib.numero_no_texto("R$ 1.234,56\n01/10/2026") == ""
    assert ib.numero_no_texto("") == ""


def test_conta_da_pagina_usa_a_mesma_leitura():
    pagina = type("P", (), {"evaluate": lambda self, js: TELA})()
    assert ib.conta_da_pagina(pagina) == "123456789"


def test_conferir_a_conta_certa():
    assert m.conferir_conta(TELA, "12345678-9", ("Empresa Fictícia",)) == ""
    assert m.conferir_conta(TELA, "0123456789", ("EMPRESA FICTICIA",)) == ""


def test_outra_conta_aberta_nao_le():
    motivo = m.conferir_conta(TELA, "987654321", ("EMPRESA FICTICIA",))
    assert "outra conta aberta" in motivo and "987654321" in motivo


def test_nome_de_outra_empresa_nao_le():
    motivo = m.conferir_conta(TELA, "123456789", ("OUTRA EMPRESA",))
    assert "nome da empresa" in motivo and "outra conta aberta" in motivo


def test_sem_numero_na_tela_nao_le():
    assert m.conferir_conta("Saldo\nR$ 1,00", "123456789", ("X",)) == m.SEM_NUMERO


def test_sem_numero_esperado_o_nome_curto_nao_basta():
    """Revisão de dinheiro (27/10): sem o número no ERP, "EMPRESA FICTICIA"
    também está dentro de "EMPRESA FICTICIA 2 LTDA" — o nome curto não prova
    de quem é a conta aberta."""
    assert m.conferir_conta(TELA, "", ("EMPRESA FICTICIA",)) == m.SEM_COMO_CONFERIR
    assert "o ERP não tem o número desta conta Inter" in m.SEM_COMO_CONFERIR
    assert "confira o cadastro" in m.SEM_COMO_CONFERIR


def test_sem_numero_esperado_so_a_razao_social_inteira_confere():
    assert m.conferir_conta(TELA, "", ("EMPRESA FICTICIA",),
                            razoes=("Empresa  Fictícia Ltda",)) == ""


def test_sem_numero_esperado_razao_social_pela_metade_nao_confere():
    """A revisão de 27/10: "EMPRESA FICTICIA" está dentro de "EMPRESA
    FICTICIA 2 LTDA" e NÃO é ela. Só o tipo da empresa no fim é ignorado."""
    tela_outra = TELA.replace("EMPRESA FICTICIA LTDA", "EMPRESA FICTICIA 2 LTDA")
    assert m.conferir_conta(tela_outra, "", (), razoes=("EMPRESA FICTICIA LTDA",)) ==         m.SEM_COMO_CONFERIR
    assert m.conferir_conta(tela_outra, "", (), razoes=("EMPRESA FICTICIA",)) ==         m.SEM_COMO_CONFERIR
    tela_meio = TELA.replace("EMPRESA FICTICIA LTDA", "EMPRESA FICTICIA SPE")
    assert m.conferir_conta(tela_meio, "", (), razoes=("EMPRESA FICTICIA",)) ==         m.SEM_COMO_CONFERIR


def test_tela_do_inter_sem_o_tipo_da_empresa_confere():
    """Medido ao vivo em 29/10/2026: a tela escreve "… SPE" e o cadastro
    "… SPE LTDA" — é a mesma empresa (era o "não reconhecida" da Buritis)."""
    tela = TELA.replace("EMPRESA FICTICIA LTDA", "EMPRESA FICTICIA SPE")
    assert m.conferir_conta(tela, "", (), razoes=("Empresa Fictícia SPE Ltda",)) == ""
    assert m.conferir_conta(TELA, "", (), razoes=("EMPRESA FICTICIA S/A",)) == ""
    assert m.sem_sufixo_legal("Empresa X Ltda. ME") == "EMPRESA X"
    # Nome comprido: a tela corta o "LTDA" em "LTD" (medido em 29/10/2026).
    assert m.sem_sufixo_legal("EMPRESA X CONSTRUTORA LTD") == "EMPRESA X CONSTRUTORA"
    assert m.sem_sufixo_legal("LTDA") == "LTDA"          # nome que é só o tipo fica


def test_sem_numero_nem_nome_recusa():
    assert m.conferir_conta(TELA, "", ()) == m.SEM_COMO_CONFERIR


class _Resp:
    def __init__(self, status, dado, url=m.URL_SALDO):
        self.status, self._dado, self.url = status, dado, url

    def json(self):
        return self._dado


class _Pag:
    def __init__(self):
        self.pedidos, self.ouvintes = [], {}

    def evaluate(self, js, args=None):
        self.pedidos.append((js, args))
        return {"status": 200, "dado": {"disponivel": 1.5}}

    def wait_for_timeout(self, ms):
        pass

    def on(self, evento, fn):
        self.ouvintes[evento] = fn


def test_resposta_ouvida_vale():
    pag = _Pag()
    assert m._resposta_do_saldo(pag, [_Resp(200, {"disponivel": 2})], {"valor": ""},
                                tempo=0) == (200, {"disponivel": 2})
    assert pag.pedidos == []


def test_sem_ouvir_pede_de_dentro_da_pagina_com_os_tres_cabecalhos():
    """29/10/2026: só com o `authorization` o Inter respondeu HTTP 412."""
    pag = _Pag()
    sessao = {"authorization": "Bearer x", "x-inter-conta-corrente": "1",
              "x-inter-organization": "2"}
    assert m._resposta_do_saldo(pag, [], sessao, tempo=0) == (200, {"disponivel": 1.5})
    assert pag.pedidos[0][1] == [m.URL_SALDO, sessao]


def test_sem_ouvir_e_sem_sessao_falha():
    with pytest.raises(m.SaldoInterFalhou, match="não pediu o saldo"):
        m._resposta_do_saldo(_Pag(), [], {}, tempo=0)


def test_cabecalhos_da_sessao_so_com_o_authorization():
    pedido = {"authorization": "Bearer x", "x-inter-conta-corrente": "1",
              "x-inter-organization": "2", "user-agent": "Chrome", "cookie": "c"}
    assert m.cabecalhos_da_sessao(pedido) == {
        "authorization": "Bearer x", "x-inter-conta-corrente": "1", "x-inter-organization": "2"}
    assert m.cabecalhos_da_sessao({"x-inter-conta-corrente": "1"}) == {}


def test_escutar_sessao_guarda_o_pedido_mais_completo_da_api():
    pag = _Pag()
    sessao = m.escutar_sessao(pag)
    pedido = lambda url, h: type("Q", (), {"url": url, "headers": h})()
    pag.ouvintes["request"](pedido("https://outro.site/x", {"authorization": "Bearer fora"}))
    assert sessao == {}
    pag.ouvintes["request"](pedido(ib.API_INTER + "/cc/x", {"authorization": "Bearer a"}))
    pag.ouvintes["request"](pedido("https://cd.web.bancointer.com.br/ib-pfj/y",
                                   {"authorization": "Bearer b", "x-inter-conta-corrente": "1"}))
    pag.ouvintes["request"](pedido(ib.API_INTER + "/cc/z", {"authorization": "Bearer c"}))
    assert sessao == {"authorization": "Bearer b", "x-inter-conta-corrente": "1"}


def test_escutar_saldo_so_guarda_a_rota_do_saldo():
    pag = _Pag()
    ouvidas = m.escutar_saldo(pag)
    pag.ouvintes["response"](_Resp(200, {}, url=ib.API_INTER + "/cc/pix/v1/extrato"))
    pag.ouvintes["response"](_Resp(200, {"disponivel": 1}))
    assert [r.url for r in ouvidas] == [m.URL_SALDO]


class _PagDaTela(_Pag):
    """Tela inicial do Inter já logada: o texto, a resposta e o print."""

    def __init__(self, texto=TELA, extrato_texto=None, extrato_corpo=None, extratos=None):
        super().__init__()
        self.texto, self.fotos = texto, []
        self.extrato_texto, self.extrato_corpo = extrato_texto, extrato_corpo
        self.extratos, self.idas = extratos, []

    def goto(self, url, **kw):
        """A tela do extrato completo: troca o texto e "recebe" o corpo."""
        self.idas.append(url)
        if url == m.URL_EXTRATO_COMPLETO:
            if self.extrato_texto is not None:
                self.texto = self.extrato_texto
            if self.extrato_corpo is not None and self.extratos is not None:
                self.extratos.append(_Resp(200, self.extrato_corpo))

    def evaluate(self, js, args=None):
        return self.texto if args is None else super().evaluate(js, args)

    def screenshot(self, path):
        self.fotos.append(path)


def test_conta_certa_le_e_fotografa(tmp_path):
    pag = _PagDaTela()
    lido = m._ler_na_pagina(pag, [_Resp(200, {"disponivel": 9.9})], {"valor": ""},
                            "123456789", ("EMPRESA FICTICIA",), (), tmp_path / "b.png",
                            agora=lambda: "agora")
    assert (lido.saldo, lido.lido_em, lido.motivo) == (D("9.90"), "agora", "")
    assert lido.imagem == tmp_path / "b.png" and pag.fotos == [str(tmp_path / "b.png")]


def test_conta_errada_nao_e_fotografada(tmp_path):
    """Revisão de 27/10: o print era tirado ANTES de conferir, e a página
    "CONTA X" do PDF mostrava o saldo de outra empresa."""
    pag = _PagDaTela()
    lido = m._ler_na_pagina(pag, [_Resp(200, {"disponivel": 9.9})], {"valor": ""},
                            "987654321", ("EMPRESA FICTICIA",), (), tmp_path / "b.png",
                            agora=lambda: "agora")
    assert lido.saldo is None and "outra conta aberta" in lido.motivo
    assert lido.imagem is None and lido.sem_imagem == m.SEM_PRINT_OUTRA_CONTA
    assert "conta aberta era outra" in m.SEM_PRINT_OUTRA_CONTA
    assert pag.fotos == []


def test_conta_que_nao_da_para_conferir_tambem_fica_sem_print(tmp_path, sem_espera):
    pag = _PagDaTela(texto="Saldo\nR$ 1,00")
    lido = m._ler_na_pagina(pag, [_Resp(200, {"disponivel": 1})], {"valor": ""},
                            "123456789", (), (), tmp_path / "b.png", agora=lambda: None)
    assert lido.motivo == m.SEM_NUMERO and lido.sem_imagem == m.SEM_PRINT_SEM_CONFERIR
    assert pag.fotos == []


def test_parar_interrompe_a_espera_do_qr(monkeypatch):
    """Revisão de 27/10: o Parar não chegava ao esperar_login (até 300 s)."""
    monkeypatch.setattr(ib.time, "sleep", lambda s: None)
    pag = _PagDaTela(texto="Ler o QR code")
    vezes = []

    def parar():
        vezes.append(1)
        return len(vezes) > 2
    with pytest.raises(ib.InterFalhou, match="parad"):
        ib.esperar_login(pag, tempo=3600, log=lambda s: None, parar=parar)
    assert len(vezes) == 3


def test_gancho_do_olho_do_inter_clica_antes_do_print(monkeypatch, tmp_path):
    ordem = []
    monkeypatch.setattr(m, "SELETOR_MOSTRAR_SALDO", "#olho")
    monkeypatch.setattr(m.util, "revelar", lambda page, sel: ordem.append(("olho", sel)))
    monkeypatch.setattr(m.util, "fotografar", lambda alvo, arquivo: ordem.append("foto") or "")
    m._fotografar(_PagDaTela(), tmp_path / "b.png")
    assert ordem == [("olho", "#olho"), "foto"]


def test_tela_so_para_com_o_saldo_escrito_e_o_mesmo_texto_duas_vezes():
    """27/10/2026: o print saiu com metade da tela ainda carregando."""
    assert m.tela_parou("Saldo\nR$ 1,00", "Saldo\nR$ 1,00", False)
    assert not m.tela_parou("Saldo\nR$ 1,00", "Saldo\nR$ 1,00", True)
    assert not m.tela_parou("Saldo", "Saldo\nR$ 1,00", False)
    assert not m.tela_parou("Carregando", "Carregando", False)
    assert not m.tela_parou("", "", False)


# --------------------- extrato completo como segunda fonte (conta PJ, 29/10/2026)
EXTRATO = {"balance": {"data": {"balances": [{"id": "DIGITAL_ACCOUNT",
                                               "available": "R$ 2.500,10"}]}}}


@pytest.fixture
def sem_espera(monkeypatch):
    monkeypatch.setattr(m, "TEMPO_EXTRATO", 0)


def test_saldo_do_extrato():
    assert m.saldo_do_extrato(EXTRATO) == D("2500.10")
    neg = {"balance": {"data": {"balances": [{"id": "DIGITAL_ACCOUNT", "available": "-R$ 5,00"}]}}}
    assert m.saldo_do_extrato(neg) == D("-5.00")
    assert m.saldo_do_extrato({}) is None and m.saldo_do_extrato(None) is None


def test_sem_saldo_na_tela_inicial_le_do_extrato_completo(tmp_path, sem_espera):
    extratos = []
    pag = _PagDaTela(extrato_corpo=EXTRATO, extratos=extratos)
    lido = m._ler_na_pagina(pag, [_Resp(500, None)], {"valor": ""}, "123456789",
                            ("EMPRESA FICTICIA",), (), tmp_path / "b.png", agora=lambda: "agora",
                            extratos=extratos)
    assert (lido.saldo, lido.via, lido.motivo) == (D("2500.10"), "extrato", "")
    assert pag.idas == [m.URL_EXTRATO_COMPLETO] and pag.fotos


def test_sem_numero_na_tela_inicial_confere_a_conta_no_extrato(tmp_path, sem_espera):
    extratos = []
    pag = _PagDaTela(texto="Olá", extrato_texto=TELA, extrato_corpo=EXTRATO, extratos=extratos)
    lido = m._ler_na_pagina(pag, [_Resp(200, {"disponivel": 9.9})], {"valor": ""},
                            "123456789", ("EMPRESA FICTICIA",), (), tmp_path / "b.png",
                            agora=lambda: None, extratos=extratos)
    assert (lido.saldo, lido.via, lido.motivo) == (D("9.90"), "inicio", "")


def test_extrato_de_outra_conta_nao_le(tmp_path, sem_espera):
    extratos = []
    outra = TELA.replace("123456789", "999999999")
    pag = _PagDaTela(texto="Olá", extrato_texto=outra, extrato_corpo=EXTRATO, extratos=extratos)
    lido = m._ler_na_pagina(pag, [_Resp(200, {"disponivel": 9.9})], {"valor": ""},
                            "123456789", ("EMPRESA FICTICIA",), (), tmp_path / "b.png",
                            agora=lambda: None, extratos=extratos)
    assert lido.saldo is None and "outra conta aberta" in lido.motivo and pag.fotos == []


def test_extra_usa_a_mesma_sessao_e_falha_dele_nao_perde_o_saldo(tmp_path, sem_espera):
    extratos = []
    pag = _PagDaTela(extrato_corpo=EXTRATO, extratos=extratos)
    vistos = []

    def extra(page, autorizacao, extrato):
        vistos.append((page, extrato()))
        return "listas"
    lido = m._ler_na_pagina(pag, [_Resp(200, {"disponivel": 1})], {"valor": "x"}, "123456789",
                            ("EMPRESA FICTICIA",), (), tmp_path / "b.png", agora=lambda: None,
                            extratos=extratos, extra=extra)
    assert lido.extra == "listas" and vistos == [(pag, EXTRATO)]

    def quebra(*a):
        raise RuntimeError("API mudou")
    lido = m._ler_na_pagina(_PagDaTela(), [_Resp(200, {"disponivel": 1})], {"valor": "x"},
                            "123456789", ("EMPRESA FICTICIA",), (), tmp_path / "c.png",
                            agora=lambda: None, extra=quebra)
    assert lido.saldo == D("1.00") and lido.extra_erro == "API mudou"


def test_saldo_pelo_extrato_fotografa_o_extrato_e_usa_os_tres_cabecalhos(monkeypatch, tmp_path, sem_espera):
    """Medido em 29/10/2026: só com o `authorization` a tela inicial deu HTTP
    412 — o pedido de dentro da página leva os três cabeçalhos da sessão; e,
    com o saldo vindo do extrato, o print é o da tela do Extrato."""
    extratos = []
    pag = _PagDaTela(extrato_corpo=EXTRATO, extratos=extratos)
    fotos = []
    monkeypatch.setattr(m, "_fotografar_extrato", lambda page, arq: fotos.append(arq) or (arq, ""))
    pedidos = []
    monkeypatch.setattr(m, "_resposta_do_saldo",
                        lambda page, ouvidas, cab, tempo=0: pedidos.append(cab) or (412, None))
    sessao = {"authorization": "Bearer x", "x-inter-conta-corrente": "1",
              "x-inter-organization": "2"}
    lido = m._ler_na_pagina(pag, [], {"valor": "Bearer x"}, "123456789", ("EMPRESA FICTICIA",),
                            (), tmp_path / "b.png", agora=lambda: 1, extratos=extratos,
                            sessao=sessao)
    assert (lido.saldo, lido.via, lido.imagem) == (D("2500.10"), "extrato", tmp_path / "b.png")
    assert pedidos == [sessao] and fotos == [tmp_path / "b.png"] and pag.fotos == []


def test_sem_sessao_completa_pede_so_com_o_authorization():
    assert m._cabecalhos_para_pedir({"valor": "B"}, {}) == {"authorization": "B"}
    assert m._cabecalhos_para_pedir({"valor": ""}, None) == {}
    s = {"authorization": "B", "x-inter-organization": "2"}
    assert m._cabecalhos_para_pedir({"valor": "A"}, s) == s


# ---------------------------------------------- menos idas de página (26/11/2026)

def test_cronometro_resume_cada_passo_e_o_total():
    horas = iter([0.0, 3.0, 15.5, 17.0])
    c = m.Cronometro(relogio=lambda: next(horas))
    c.marcar("Chrome")
    c.marcar("QR")
    c.marcar("saldo")
    assert c.resumo() == "Chrome 3,0 s · QR 12,5 s · saldo 1,5 s · total 17,0 s"


def test_entrou_so_sem_marca_de_login_e_com_numero_ou_sessao():
    completa = {k: "x" for k in m.CABECALHOS_DA_SESSAO}
    assert m.entrou(TELA, {})
    assert m.entrou("Olá\nSaldo", completa)
    assert not m.entrou("Olá\nSaldo", {"authorization": "x"})
    assert not m.entrou("Leia o QR Code\n123456789", completa)
    assert not m.entrou("", completa)


class _PagDoLogin(_Pag):
    """A tela inicial durante o QR: cada leitura do texto avança o relógio."""

    def __init__(self, textos, relogio):
        super().__init__()
        self.textos, self.relogio = list(textos), relogio

    def evaluate(self, js, args=None):
        self.relogio[0] += 1
        return self.textos.pop(0) if len(self.textos) > 1 else self.textos[0]


def test_esperar_entrar_confirma_na_propria_tela_inicial(monkeypatch):
    relogio = [0.0]
    pag = _PagDoLogin(["Leia o QR Code", "Leia o QR Code", TELA], relogio)
    monkeypatch.setattr(ib, "esperar_login", lambda *a, **k: pytest.fail("caminho antigo"))
    assert m.esperar_entrar(pag, {}, tempo=60, log=lambda s: None,
                            relogio=lambda: relogio[0]) is True


def test_esperar_entrar_cai_no_caminho_antigo_sem_numero_nem_sessao(monkeypatch):
    relogio = [0.0]
    pag = _PagDoLogin(["Leia o QR Code", "Carregando…"], relogio)
    antigo = []
    monkeypatch.setattr(ib, "esperar_login", lambda page, **k: antigo.append(k))
    assert m.esperar_entrar(pag, {}, tempo=300, log=lambda s: None,
                            relogio=lambda: relogio[0]) is False
    assert len(antigo) == 1 and 1 <= antigo[0]["tempo"] <= 300


def test_esperar_entrar_respeita_o_parar_e_o_tempo():
    relogio = [0.0]
    pag = _PagDoLogin(["Leia o QR Code"], relogio)
    with pytest.raises(ib.InterFalhou, match="Parar"):
        m.esperar_entrar(pag, {}, tempo=60, log=lambda s: None, parar=lambda: True,
                         relogio=lambda: relogio[0])
    with pytest.raises(ib.InterFalhou, match="não abriu"):
        m.esperar_entrar(pag, {}, tempo=5, log=lambda s: None,
                         relogio=lambda: relogio[0])


def test_escutar_saldo_deixa_de_fora_o_401_de_antes_do_qr():
    pag = _Pag()
    ouvidas = m.escutar_saldo(pag)
    pag.ouvintes["response"](_Resp(401, None))
    pag.ouvintes["response"](_Resp(412, None))
    assert [r.status for r in ouvidas] == [412]


def test_a_via_da_ultima_leitura_fica_ao_lado_do_perfil(monkeypatch, tmp_path):
    monkeypatch.setattr(ib, "pasta_do_perfil", lambda a: tmp_path / f".perfil_{a}")
    assert m.ler_via("ALFA") == ""
    m.gravar_via("ALFA", m.VIA_EXTRATO)
    assert m.ler_via("ALFA") == m.VIA_EXTRATO and m.ler_via("BETA") == ""
    assert not (tmp_path / ".perfil_ALFA").exists()      # o perfil do Chrome fica intacto


def test_direto_no_extrato_nem_passa_pela_tela_inicial(tmp_path, sem_espera):
    extratos, passos = [], []
    pag = _PagDaTela(extrato_corpo=EXTRATO, extratos=extratos)
    lido = m._ler_na_pagina(pag, [], {"valor": ""}, "123456789", ("EMPRESA FICTICIA",), (),
                            tmp_path / "b.png", agora=lambda: "agora", extratos=extratos,
                            comecar_no_extrato=True, marcar=passos.append)
    assert (lido.saldo, lido.via, lido.motivo) == (D("2500.10"), "extrato", "")
    assert pag.idas == [m.URL_EXTRATO_COMPLETO] and pag.fotos
    assert passos == ["saldo", "print"]


def test_direto_no_extrato_de_outra_conta_para_sem_print(tmp_path, sem_espera):
    extratos = []
    outra = TELA.replace("123456789", "987654321")
    pag = _PagDaTela(extrato_texto=outra, extrato_corpo=EXTRATO, extratos=extratos)
    lido = m._ler_na_pagina(pag, [], {"valor": ""}, "123456789", ("EMPRESA FICTICIA",), (),
                            tmp_path / "b.png", agora=lambda: "agora", extratos=extratos,
                            comecar_no_extrato=True)
    assert lido.saldo is None and "outra conta aberta" in lido.motivo
    assert pag.idas == [m.URL_EXTRATO_COMPLETO] and pag.fotos == []


def test_extrato_sem_saldo_volta_a_tela_inicial(tmp_path, sem_espera):
    extratos, ouvidas = [], []

    class _Pagina(_PagDaTela):
        def goto(self, url, **kw):
            super().goto(url, **kw)
            if url == ib.URL_LOGIN:          # a tela inicial pede o saldo de novo
                ouvidas.append(_Resp(200, {"disponivel": 9.9}))
    pag = _Pagina(extrato_corpo={"balance": {}}, extratos=extratos)
    lido = m._ler_na_pagina(pag, ouvidas, {"valor": ""},
                            "123456789", ("EMPRESA FICTICIA",), (), tmp_path / "b.png",
                            agora=lambda: "agora", extratos=extratos,
                            comecar_no_extrato=True)
    assert pag.idas == [m.URL_EXTRATO_COMPLETO, ib.URL_LOGIN]
    assert (lido.saldo, lido.motivo, lido.via) == (D("9.90"), "", "inicio")


def test_extra_marca_o_tempo_das_listas(tmp_path):
    passos = []
    pag = _PagDaTela()
    lido = m._ler_na_pagina(pag, [_Resp(200, {"disponivel": 1})], {"valor": ""},
                            "123456789", ("EMPRESA FICTICIA",), (), tmp_path / "b.png",
                            agora=lambda: None, extra=lambda p, a, e: "listas",
                            marcar=passos.append)
    assert lido.extra == "listas" and passos == ["saldo", "print", "listas"]


def test_volta_do_extrato_sem_numero_tira_o_print_na_tela_do_extrato(tmp_path, sem_espera):
    """Revisão de dinheiro de 26/11/2026: na volta, o corpo guardado fazia o
    print do extrato sair da tela INICIAL (saldo sem prova no PDF)."""
    extratos, ouvidas = [], []

    class _Pagina(_PagDaTela):
        def goto(self, url, **kw):
            self.idas.append(url)
            if url == m.URL_EXTRATO_COMPLETO:
                # 1ª vez ainda sem o número; na 2ª a tela já o mostra.
                self.texto = "Extrato" if self.idas.count(url) == 1 else TELA
                extratos.append(_Resp(200, EXTRATO))
            else:
                self.texto = TELA                 # inicial: confere, sem saldo
                ouvidas.append(_Resp(500, None))
    pag = _Pagina(extratos=extratos)
    lido = m._ler_na_pagina(pag, ouvidas, {"valor": ""}, "123456789",
                            ("EMPRESA FICTICIA",), (), tmp_path / "b.png",
                            agora=lambda: "agora", extratos=extratos,
                            comecar_no_extrato=True)
    assert (lido.saldo, lido.via) == (D("2500.10"), "extrato")
    assert pag.idas == [m.URL_EXTRATO_COMPLETO, ib.URL_LOGIN, m.URL_EXTRATO_COMPLETO]
    assert pag.texto == TELA and pag.fotos       # o print é o da tela do extrato
