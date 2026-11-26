# -*- coding: utf-8 -*-
"""O saldo da Caixa para a Prova, sem navegador. Contas, CNPJs e valores
fictícios; o HTML e o JSON imitam só a forma medida em 26/11/2026."""
import datetime as dt
from decimal import Decimal as D
from pathlib import Path

import pytest

from tela_do_dia import saldo_caixa as sc

AGORA = dt.datetime(2026, 11, 26, 9, 30)
EMP_A, EMP_B, EMP_C = "11111111000111", "22222222000122", "33333333000133"

LOGIN = {"cliente": "FULANO", "conta": [
    {"agencia": "01234", "tipo": "1292", "numero": "000111111111-1", "cpfcnpj": EMP_A,
     "chaveRecurso": "R1", "selecionada": True},
    {"agencia": "05678", "tipo": "1292", "numero": "000222222222-2", "cpfcnpj": EMP_B,
     "chaveRecurso": "R2", "selecionada": False},
    {"agencia": "05678", "tipo": "1292", "numero": "000333333333-3", "cpfcnpj": EMP_C,
     "chaveRecurso": "R3", "selecionada": False},
]}
K_A, K_B, K_C = "1234-1292-1111111111", "5678-1292-2222222222", "5678-1292-3333333333"

RESUMO = """
<table class="produto titulo"><tbody><tr><td class="txt-tit01" colspan="6">Resumo</td></tr>
<tr><td class="txt-cab">N&uacute;mero da Conta</td><td>Apelido da Conta</td>
<td>Saldo Bloqueado</td><td>Saldo Dispon&iacute;vel s/ Limite</td>
<td>Saldo Dispon&iacute;vel</td><td>Total</td></tr>
<tr class="even"><td><a href="javascript:x('')">1234 1292 111111111-1</a></td><td></td>
<td>R$ 0,00</td><td>R$ 5.000,00</td><td>R$ 5.000,00</td><td>R$ 5.000,00</td></tr>
<tr class="odd"><td><a>5678 1292 222222222-2</a></td><td></td>
<td>R$ 0,00</td><td>-R$ 10,00</td><td>R$ 990,00</td><td>R$ 990,00</td></tr>
<tr class="even"><td><a>5678 1292 333333333-3</a></td><td></td>
<td>R$ 0,00</td><td>R$ 9.000,00</td><td>R$ 10.000,00</td><td>R$ 10.000,00</td></tr>
<tr class="odd"><td><b>Saldo total (R$)</b></td><td></td><td></td><td></td><td></td>
<td><b>R$ 14.990,00</b></td></tr>
</tbody></table>
"""


def _atual(texto):
    return {"consultaLancamentoBean": [{"descricao": "Saldo atual", "valor": texto},
                                       {"descricao": "Saldo disponivel", "valor": "9,99 C"}]}


def test_resumo_le_a_coluna_sem_limite_de_cada_conta():
    assert sc.saldos_do_resumo(RESUMO) == {K_A: "R$ 5.000,00", K_B: "-R$ 10,00",
                                           K_C: "R$ 9.000,00"}


def test_resumo_sem_a_coluna_ou_com_linha_de_outra_largura_e_erro():
    with pytest.raises(sc.CaixaFalhou, match="formato"):
        sc.saldos_do_resumo(RESUMO.replace("s/ Limite", "Livre"))
    with pytest.raises(sc.CaixaFalhou, match="largura"):
        sc.saldos_do_resumo(RESUMO.replace("<td>R$ 0,00</td><td>-R$ 10,00</td>",
                                           "<td>-R$ 10,00</td>"))


def test_resumo_com_a_mesma_conta_em_dois_valores_nao_escolhe():
    dobro = RESUMO.replace("</tbody>", '<tr><td>1234 1292 111111111-1</td><td></td>'
                           '<td>R$ 0,00</td><td>R$ 7,00</td><td>R$ 7,00</td><td>R$ 7,00</td>'
                           '</tr></tbody>')
    assert sc.saldos_do_resumo(dobro)[K_A] is None


def test_conta_do_login_tem_a_mesma_chave_do_resumo():
    contas = sc.contas_do_login(LOGIN)
    assert [c.chave for c in contas] == list(sc.saldos_do_resumo(RESUMO))
    assert contas[0] == sc.ContaCaixa(K_A, "111111111-1", EMP_A, "R1", True)
    with pytest.raises(sc.CaixaFalhou):
        sc.contas_do_login({"erro": "x"})


@pytest.mark.parametrize("texto,esperado", [
    ("R$ 1.234,56", D("1234.56")), ("-R$ 10,00", D("-10.00")),
    ("R$ -10,00", D("-10.00")), ("1.234,56 D", D("-1234.56")),
    ("4.321,09 C", D("4321.09")), ("0,00 C", D("0.00")),
    ("R$ 1.234", None), ("", None), ("—", None), (None, None)])
def test_valor_so_com_dois_centavos(texto, esperado):
    assert sc.valor(texto) == esperado


def test_saldo_atual_da_resposta():
    assert sc.saldo_atual(_atual("0,00 C")) == "0,00 C"
    with pytest.raises(sc.CaixaFalhou):
        sc.saldo_atual({"consultaLancamentoBean": []})
    with pytest.raises(sc.CaixaFalhou):
        sc.saldo_atual({"outro": 1})


def _leituras(documentos, atuais, resumo=None):
    return sc.leituras(documentos, sc.contas_do_login(LOGIN), atuais,
                       sc.saldos_do_resumo(RESUMO) if resumo is None else resumo,
                       lido_em=AGORA, imagem=Path("caixa banco.png"))


def test_compara_o_saldo_atual_e_o_quadro_vira_nota():
    """Aplicação automática: saldo atual da conta 0,00; o quadro mostra a
    conta + a aplicação. Vale o saldo atual (a aplicação é outra conta no ERP)."""
    lidas = _leituras({EMP_A: "", EMP_C: ""}, {K_A: "0,00 C", K_C: "9.000,00 C"})
    assert lidas[EMP_A].saldo == D("0.00") and lidas[EMP_A].lido_em == AGORA
    assert lidas[EMP_A].imagem == Path("caixa banco.png")
    assert "R$ 5.000,00" in lidas[EMP_A].nota and "R$ 0,00" in lidas[EMP_A].nota
    assert lidas[EMP_C].saldo == D("9000.00") and lidas[EMP_C].nota == ""


def test_cnpj_fora_do_login_ou_numero_do_erp_que_nao_bate():
    lidas = _leituras({"99999999000199": "", EMP_A: "999-9", EMP_B: "000222222222-2"},
                      {K_A: "1,00 C", K_B: "2,00 C"})
    assert lidas["99999999000199"].motivo == sc.FORA_DO_LOGIN
    assert lidas[EMP_A].saldo is None and "999-9" in lidas[EMP_A].motivo
    assert lidas[EMP_B].saldo == D("2.00")


def test_duas_contas_da_mesma_empresa_sem_numero_no_erp_nao_escolhe():
    dado = {"conta": [*LOGIN["conta"], {**LOGIN["conta"][0], "numero": "000444444444-4",
                                        "selecionada": False}]}
    contas = sc.contas_do_login(dado)
    lidas = sc.leituras({EMP_A: ""}, contas, {K_A: "1,00 C"}, {}, lido_em=AGORA, imagem=None)
    assert lidas[EMP_A].saldo is None and lidas[EMP_A].motivo == sc.DUAS_CONTAS
    lidas = sc.leituras({EMP_A: "111111111-1"}, contas, {K_A: "1,00 C"}, {},
                        lido_em=AGORA, imagem=None)
    assert lidas[EMP_A].saldo == D("1.00")


def test_saldo_que_falhou_ou_nao_se_le_nao_bate():
    lidas = _leituras({EMP_A: "", EMP_B: "", EMP_C: ""},
                      {K_A: sc.CaixaFalhou("HTTP 500"), K_B: "R$ 10"})
    assert "HTTP 500" in lidas[EMP_A].motivo and lidas[EMP_A].saldo is None
    assert "não leio" in lidas[EMP_B].motivo and lidas[EMP_B].saldo is None
    assert "não foi lida" in lidas[EMP_C].motivo


class _Pagina:
    """Dublê do `page.evaluate`: a troca de conta e o saldo da conta marcada."""
    def __init__(self, saldos, troca_errada=()):
        self.saldos, self.troca_errada = saldos, set(troca_errada)
        self.marcada, self.trocas = "R1", []

    def evaluate(self, js, args):
        if "selecionaConta" in js:
            self.trocas.append(args[0])
            if args[0] not in self.troca_errada:
                self.marcada = args[0]
            return {"status": 200, "marcada": self.marcada}
        assert args == ["Bearer x"]
        return {"status": 200, "dado": _atual(self.saldos[self.marcada])}


def test_ler_atuais_troca_conta_a_conta_e_volta_para_a_original():
    contas = sc.contas_do_login(LOGIN)
    pagina = _Pagina({"R1": "1,00 C", "R2": "2,00 D", "R3": "3,00 C"}, troca_errada={"R3"})
    atuais = sc.ler_atuais(pagina, contas, "Bearer x", lambda: False)
    assert atuais[K_A] == "1,00 C" and atuais[K_B] == "2,00 D"
    assert isinstance(atuais[K_C], sc.CaixaFalhou)        # não trocou: não lê a outra
    assert pagina.trocas[-1] == "R1" and pagina.marcada == "R1"


def test_falha_no_chrome_vira_a_mesma_ressalva_em_todas(monkeypatch):
    def quebra(*_a, **_k):
        raise sc.CaixaFalhou(sc.FECHADO)
    monkeypatch.setattr(sc, "_ler_no_chrome", quebra)
    lidas = sc.ler({EMP_A: "", EMP_B: "", "": ""}, Path("."))
    assert set(lidas) == {EMP_A, EMP_B}
    assert all(lida.saldo is None and lida.motivo == sc.FECHADO for lida in lidas.values())
    assert sc.ler({}, Path(".")) == {}


class _Entrada:
    """Dublê da página de entrada: o botão leva ao login; `com_botao=False`
    simula o botão que não aparece."""
    def __init__(self, com_botao=True, ja_logado=False):
        self.url, self.com_botao, self.ja_logado = "", com_botao, ja_logado
        self.idas, self.cliques = [], 0

    def goto(self, url, **_):
        self.idas.append(url)
        self.url = ("https://gerenciador.caixa.gov.br/empresa/dashboard"
                    if self.ja_logado else url)

    def locator(self, seletor):
        assert seletor == sc.SELETOR_ENTRAR
        return self

    @property
    def first(self):
        return self

    def wait_for(self, **_):
        if not self.com_botao:
            raise TimeoutError("sem botão")

    def evaluate(self, _js):
        self.cliques += 1
        self.url = "https://loginx.caixa.gov.br/auth/realms/x?state=novo"


def test_abre_a_entrada_das_empresas_e_clica_em_entrar():
    pagina = _Entrada()
    sc.abrir_login(pagina, log=lambda m: None)
    assert pagina.idas == [sc.URL_ENTRADA] and pagina.cliques == 1
    assert sc.HOST_LOGIN in pagina.url


def test_sem_o_botao_vai_ao_login_sem_state_nem_nonce():
    pagina, avisos = _Entrada(com_botao=False), []
    sc.abrir_login(pagina, log=avisos.append)
    assert pagina.idas == [sc.URL_ENTRADA, sc.URL_LOGIN] and pagina.cliques == 0
    assert "state=" not in sc.URL_LOGIN and "nonce=" not in sc.URL_LOGIN
    assert avisos


def test_ja_logado_nao_clica_em_nada():
    pagina = _Entrada(ja_logado=True)
    sc.abrir_login(pagina, log=lambda m: None)
    assert pagina.idas == [sc.URL_ENTRADA] and pagina.cliques == 0
