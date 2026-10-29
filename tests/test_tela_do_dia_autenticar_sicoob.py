"""Autenticar no banco: a leitura do Sicoob, com dublês (sem Chrome)."""
from contextlib import contextmanager
from datetime import date
from decimal import Decimal as D

import pytest

from tela_do_dia import agendados as agd
from tela_do_dia import autenticar_sicoob as asi

HOJE = date(2026, 10, 29)


def _ag(id_, conta, dia=date(2026, 10, 27), valor="10.00"):
    return agd.Agendado(id=id_, dia=dia, conta=conta, alvo=str(id_), lancamento_id="L",
                        favorecido="F", valor=D(valor))


def test_periodo_vai_do_dia_anterior_ao_mais_antigo_ate_hoje():
    assert asi.periodo([_ag(1, "A", date(2026, 10, 24)), _ag(2, "A")], HOJE) == (
        date(2026, 10, 23), HOJE)
    assert asi.periodo([], HOJE) is None


def test_contas_a_ler_separa_mesmo_numero_e_outro_banco():
    from pagamentos_dia.agendamentos_sicoob import MOTIVO_FORA_SICOOB
    mapa = {"A": ("111", ""), "B": ("222", ""), "B2": ("222", ""),
            "INTER": ("", MOTIVO_FORA_SICOOB), "SEM": ("", "sem cadastro")}
    pend = [_ag(i, c) for i, c in enumerate(mapa)]
    contas, falhas = asi.contas_a_ler(pend, lambda c: mapa[c])
    assert contas == {"111": "A"}
    assert falhas == {"B": asi.MESMO_NUMERO, "B2": asi.MESMO_NUMERO, "SEM": "sem cadastro"}


class _Cli:
    def __init__(self, contas):
        self.contas, self.page, self.abertas = contas, object(), []

    def aguardar_login(self):
        pass

    def acessar_conta(self, numero):
        self.abertas.append(numero)
        return numero in self.contas

    def listar_contas(self):
        return list(self.contas)


def _abrir(*clientes):
    fila = list(clientes)

    @contextmanager
    def abrir():
        yield fila.pop(0)
    return abrir


def test_ler_marca_lida_so_a_conta_que_respondeu_e_guarda_o_motivo():
    def ler_uma(cli, numero, conta, ini, fim, valores):
        if numero == "222":
            raise RuntimeError("HTTP 500\nresto")
        return ["mov"], ["pend"]
    r = asi.ler({"111": "A", "222": "B"}, HOJE, HOJE, log=lambda *_: None,
                abrir=_abrir(_Cli({"111", "222"})), ler_uma=ler_uma)
    assert r.lidas == {"A"} and r.movimentos == ["mov"] and r.pendencias == ["pend"]
    assert r.falhas == {"B": "o Sicoob não respondeu: HTTP 500"}


def test_chrome_que_cai_deixa_as_contas_nao_lidas_com_o_porque():
    @contextmanager
    def abrir():
        raise RuntimeError("perfil em uso")
        yield
    r = asi.ler({"111": "A"}, HOJE, HOJE, log=lambda *_: None, abrir=abrir)
    assert r.lidas == set() and "perfil em uso" in r.falhas["A"]


def test_outro_acesso_le_so_as_que_faltaram():
    lidas = []

    def ler_uma(cli, numero, conta, *_a):
        if numero not in cli.contas:
            raise LookupError(asi.FORA_DESTE_LOGIN)
        lidas.append(numero)
        return [], []
    r = asi.ler({"111": "A", "222": "B"}, HOJE, HOJE, log=lambda *_: None,
                abrir=_abrir(_Cli({"111"}), _Cli({"222"})), ler_uma=ler_uma,
                perguntar=lambda nomes: nomes == ["B"])
    assert lidas == ["111", "222"] and r.lidas == {"A", "B"} and r.falhas == {}


def test_outro_acesso_que_volta_no_mesmo_login_diz_para_sair():
    def ler_uma(cli, numero, conta, *_a):
        if numero not in cli.contas:
            raise LookupError(asi.FORA_DESTE_LOGIN)
        return [], []
    r = asi.ler({"111": "A", "222": "B"}, HOJE, HOJE, log=lambda *_: None,
                abrir=_abrir(_Cli({"111"}), _Cli({"111"})), ler_uma=ler_uma,
                perguntar=lambda nomes: True)
    assert r.falhas == {"B": asi.MESMO_ACESSO}


# ------------------------------------------------------------- uma conta
def _sb(monkeypatch, aberta="111"):
    from baixar_comprovantes import sicoob_baixar as sb
    monkeypatch.setattr(sb, "ir_para_comprovantes", lambda page: None)
    monkeypatch.setattr(sb, "conta_aberta", lambda page: aberta)


def test_conta_errada_aberta_nao_le_nada(monkeypatch):
    _sb(monkeypatch, aberta="999")
    with pytest.raises(RuntimeError, match="não li"):
        asi.ler_conta(_Cli({"111"}), "111", "A", HOJE, HOJE,
                      listar=lambda *a: [], listar_pix=lambda *a: [], consultar=lambda *a: [])


def test_ler_conta_tira_agendamento_e_espelho_pix_e_abre_html_so_do_mesmo_valor(monkeypatch):
    _sb(monkeypatch)
    comuns = [
        {"situacao": "EFETIVADO", "valorLancamento": 10.0, "dataLancamento": "2026-10-28",
         "idAgendamento": 1},
        {"situacao": "AGENDADO", "valorLancamento": 10.0, "dataLancamento": "2026-10-28",
         "idAgendamento": 2},
        {"situacao": "EFETIVADO", "valorLancamento": 10.0, "dataLancamento": "2026-10-28",
         "idAgendamento": 3, "tipoAgendamento": "Pix via chave"},
        {"situacao": "EFETIVADO", "valorLancamento": 99.0, "dataLancamento": "2026-10-28",
         "idAgendamento": 4},
    ]
    abertos = []

    def detalhar(page, itens):
        abertos.extend(i["idAgendamento"] for i in itens)
        return [(itens[0], "<p>Observação: OBRA MODELO NF 1</p>")]
    pix = [{"valor": "10,00", "dataHoraEnvioLancamento": "2026-10-28 09:00:00.000",
            "descricao": "OBRA PIX", "destino": {"nome": "F"}, "estado": "FINALIZADO_SUCESSO", "tipo": "DEBITO"}]
    pend = [{"situacao": "PENDENTE_ASSINATURA", "valor": 5.0, "observacao": "X"}]
    movs, pends = asi.ler_conta(
        _Cli({"111"}), "111", "A", date(2026, 10, 27), HOJE, {D("10.00")},
        listar=lambda page, de, ate: comuns, listar_pix=lambda *a: pix,
        consultar=lambda *a: pend, detalhar=detalhar, detalhar_pix=None)
    assert abertos == [1]
    assert [(m.origem, m.valor, m.descricao) for m in movs] == [
        ("Sicoob comprovante", D("10.00"), "OBRA MODELO NF 1"),
        ("Sicoob comprovante", D("99.00"), ""),
        ("Sicoob Pix", D("10.00"), "OBRA PIX")]
    assert len(pends) == 1 and pends[0].conta == "A"


def test_lista_do_mes_inteiro_nao_conta_o_mesmo_comprovante_duas_vezes(monkeypatch):
    _sb(monkeypatch)
    item = {"situacao": "EFETIVADO", "valorLancamento": 10.0, "dataLancamento": "2026-10-01",
            "idAgendamento": 7}
    movs, _ = asi.ler_conta(_Cli({"111"}), "111", "A", date(2026, 9, 29), HOJE, set(),
                            listar=lambda *a: [item], listar_pix=lambda *a: [],
                            consultar=lambda *a: [], detalhar=None)
    assert len(movs) == 1


def test_valores_por_conta_inclui_as_partes():
    a = agd.Agendado(id=1, dia=HOJE, conta="A", alvo="1", lancamento_id="L", favorecido="F",
                     valor=D("30.00"), foto={"partes": [{"valor": "10.00"}, {"valor": "20.00"}]})
    assert asi.valores_por_conta([a]) == {"A": {D("30.00"), D("10.00"), D("20.00")}}



def test_observacao_do_html_e_so_o_campo_e_nao_o_resto_do_texto():
    from decimal import Decimal as D
    from tela_do_dia import autenticar as au
    html = ("<table><tr><td>Observação:</td><td>OBRA MODELO NF 1 OC 2</td></tr>"
            "<tr><td>Autenticação</td><td>ABC</td></tr></table>")
    m = au.Movimento("A", HOJE, D("10.00"))
    assert asi.completar_pelo_html(m, html).descricao == "OBRA MODELO NF 1 OC 2"


def test_observacao_vazia_nao_pega_o_rotulo_seguinte():
    from decimal import Decimal as D
    from tela_do_dia import autenticar as au
    html = ("<table><tr><td>Observação:</td><td></td></tr>"
            "<tr><td>Valor:</td><td>10,00</td></tr></table>")
    m = au.Movimento("A", HOJE, D("10.00"))
    assert asi.completar_pelo_html(m, html).descricao == ""
