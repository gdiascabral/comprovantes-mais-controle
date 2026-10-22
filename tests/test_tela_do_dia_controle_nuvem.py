# tests/test_tela_do_dia_controle_nuvem.py
# -*- coding: utf-8 -*-
"""Controle de aportes na nuvem (`tela_do_dia/controle_nuvem.py`). Dublê do
`nuvem.rest`; nomes fictícios."""
import datetime
from decimal import Decimal
from urllib.parse import unquote

import pytest

from tela_do_dia import controle_aportes as ca
from tela_do_dia import controle_nuvem as cn

D = Decimal
ABRE, HOJE = datetime.date(2026, 10, 21), datetime.date(2026, 10, 23)
ALFA, BETA = "FULANO ALFA DA SILVA", "FULANO BETA SOUZA"


class Banco:
    def __init__(self):
        self.t = {cn.CONTAS: [], cn.APORTADORES: [], cn.APONTAMENTOS: []}
        self.ordem, self._id = [], 0
        self.barra_alterar = self.barra_apagar = False   # simula a RLS
        self.ao_inserir = None                           # gancho de corrida

    @staticmethod
    def _casa(linha, filtro):
        for parte in filter(None, filtro.split("&")):
            campo, _, cond = parte.partition("=")
            op, _, valor = cond.partition(".")
            valor = unquote(valor)
            if op == "eq" and str(linha.get(campo)) != valor:
                return False
            if op == "in" and str(linha.get(campo)) not in valor.strip("()").split(","):
                return False
        return True

    def ler(self, tabela, _tok, colunas="*", filtro=""):
        return [dict(l) for l in self.t[tabela] if self._casa(l, filtro)]

    def inserir(self, tabela, _tok, linhas, devolver=True):
        self.ordem.append(f"inserir {tabela}")
        if self.ao_inserir:
            gancho, self.ao_inserir = self.ao_inserir, None
            gancho(self)
        saida = []
        for l in linhas:
            self._id += 1
            nova = dict(l, id=self._id)
            self.t[tabela].append(nova)
            saida.append(dict(nova))
        return saida

    def alterar(self, tabela, _tok, filtro, mudancas):
        self.ordem.append(f"alterar {tabela}")
        feitas = []
        for l in self.t[tabela]:
            if not self.barra_alterar and self._casa(l, filtro):
                l.update(mudancas)
                feitas.append(dict(l))
        return feitas

    def apagar(self, tabela, _tok, filtro):
        self.ordem.append(f"apagar {tabela}")
        if self.barra_apagar:
            return
        self.t[tabela] = [l for l in self.t[tabela] if not self._casa(l, filtro)]


@pytest.fixture
def banco(monkeypatch):
    from nuvem import rest
    b = Banco()
    for nome in ("ler", "inserir", "alterar", "apagar"):
        monkeypatch.setattr(rest, nome, getattr(b, nome))
    return b


def _conta(**kw):
    base = dict(conta_erp="CONTA MAE - BANCO", abertura=ABRE, aportadores=(
        ca.Aportador(ALFA, D(1), D("40000.00")), ca.Aportador(BETA, D(1), D("0.00"))))
    base.update(kw)
    return ca.ContaControlada(**base)


def _ids(conta):
    """O `vistos` que a tela manda: os aportadores que o formulário carregou."""
    return ca.vistos_do_formulario(conta)


def _salva():
    """Conta já gravada (id 7) com o aportador de id 3."""
    return ca.ContaControlada("CONTA MAE - BANCO", ABRE, id=7, aportadores=(
        ca.Aportador(ALFA, D(1), D("0.00"), id=3), ca.Aportador(BETA, D(1), id=4)))


def test_grava_conta_nova_com_numero_em_texto_e_le_de_volta(banco):
    anotado = []
    cn.gravar_conta("tok", _conta(), HOJE, anotar=lambda a, d: anotado.append(a))
    assert banco.t[cn.CONTAS][0]["abertura"] == "2026-10-21"
    assert {(l["nome_erp"], l["peso"], l["abertura"]) for l in banco.t[cn.APORTADORES]} == \
        {(ALFA, "1", "40000.00"), (BETA, "1", "0.00")}
    contas, apont = cn.ler("tok")
    assert contas[0].aportadores[0].abertura == D("40000.00") and apont == {}
    assert anotado and "Controle de aportes" in anotado[0]


def test_editar_muda_so_o_que_mudou_e_insere_antes_de_apagar(banco):
    cn.gravar_conta("tok", _conta(), HOJE, anotar=lambda *a: None)
    salva = cn.ler("tok")[0][0]
    banco.ordem.clear()
    nova = ca.ContaControlada(salva.conta_erp, ABRE, id=salva.id, aportadores=(
        ca.Aportador(ALFA, D(1), D("30000.00")), ca.Aportador("CICLANO GAMA", D(1))))
    cn.gravar_conta("tok", nova, HOJE, [salva], anotar=lambda *a: None,
                    vistos=_ids(salva))
    assert banco.ordem == [f"alterar {cn.CONTAS}", f"inserir {cn.APORTADORES}",
                           f"alterar {cn.APORTADORES}", f"apagar {cn.APORTADORES}"]
    assert {l["nome_erp"] for l in banco.t[cn.APORTADORES]} == {ALFA, "CICLANO GAMA"}


def test_nao_tira_aportador_com_apontamento_e_nao_escreve_nada(banco):
    cn.gravar_conta("tok", _conta(), HOJE, anotar=lambda *a: None)
    salva = cn.ler("tok")[0][0]
    beta = salva.aportadores[1]
    cn.apontar("tok", salva, ca.Recebimento("r1", HOJE, D("10.00"), "X"), beta.id, "pix",
               anotar=lambda *a: None)
    banco.ordem.clear()
    sem_beta = ca.ContaControlada(salva.conta_erp, ABRE, (salva.aportadores[0],), id=salva.id)
    with pytest.raises(ValueError, match=BETA):
        cn.gravar_conta("tok", sem_beta, HOJE, [salva], anotar=lambda *a: None,
                        vistos=_ids(salva))
    assert banco.ordem == []


def test_conta_com_problema_nao_toca_no_banco(banco):
    with pytest.raises(ValueError):
        cn.gravar_conta("tok", _conta(aportadores=()), HOJE, anotar=lambda *a: None)
    assert banco.ordem == []


def test_apontar_insere_e_depois_corrige_o_mesmo_recebimento(banco):
    rec = ca.Recebimento("r/1", HOJE, D("10.00"), "X")
    cn.apontar("tok", _salva(), rec, 3, "pix", anotar=lambda *a: None)
    cn.apontar("tok", _salva(), rec, None, "devolução", anotar=lambda *a: None)
    linhas = banco.t[cn.APONTAMENTOS]
    assert len(linhas) == 1 and linhas[0]["aportador_id"] is None
    assert linhas[0]["valor"] == "10.00" and linhas[0]["recebimento_erp"] == "r/1"
    _c, apont = cn.ler("tok")
    assert apont[7][0].motivo == "devolução"
    cn.desfazer("tok", apont[7][0].id, anotar=lambda *a: None)
    assert banco.t[cn.APONTAMENTOS] == []


def test_apontar_sem_motivo_recusa(banco):
    with pytest.raises(ValueError, match="motivo"):
        cn.apontar("tok", _salva(), ca.Recebimento("r1", HOJE, D("10.00"), "X"), 3, "  ",
                   anotar=lambda *a: None)


def test_apontar_aportador_de_outra_conta_recusa_antes_de_gravar(banco):
    rec = ca.Recebimento("r1", HOJE, D("10.00"), "X")
    with pytest.raises(ValueError, match="não é desta conta"):
        cn.apontar("tok", _salva(), rec, 99, "pix", anotar=lambda *a: None)
    assert banco.ordem == [] and banco.t[cn.APONTAMENTOS] == []


def test_apontar_em_conta_nao_gravada_recusa(banco):
    sem_id = ca.ContaControlada("CONTA MAE - BANCO", ABRE, (ca.Aportador(ALFA, D(1), id=3),))
    with pytest.raises(ValueError, match="gravada"):
        cn.apontar("tok", sem_id, ca.Recebimento("r1", HOJE, D("10.00"), "X"), 3, "pix",
                   anotar=lambda *a: None)
    assert banco.ordem == []


def test_apontar_nao_exige_a_coluna_de_autor(banco):
    cn.apontar("tok", _salva(), ca.Recebimento("r1", HOJE, D("10.00"), "X"), 3, "pix",
               anotar=lambda *a: None)
    assert "alterado_por" not in banco.t[cn.APONTAMENTOS][0]


def _gravada(banco):
    cn.gravar_conta("tok", _conta(), HOJE, anotar=lambda *a: None)
    return cn.ler("tok")[0][0]


def test_alterar_barrado_pela_rls_nao_vira_gravado(banco):
    salva = _gravada(banco)
    banco.barra_alterar = True
    anotado = []
    with pytest.raises(cn.NaoGravou):
        cn.gravar_conta("tok", salva, HOJE, [salva], anotar=lambda a, d: anotado.append(a),
                        vistos=_ids(salva))
    assert anotado == []


def test_apagar_barrado_pela_rls_nao_vira_desfeito(banco):
    rec = ca.Recebimento("r1", HOJE, D("10.00"), "X")
    cn.apontar("tok", _salva(), rec, 3, "pix", anotar=lambda *a: None)
    apont = cn.ler("tok")[1][7][0]
    banco.barra_apagar = True
    anotado = []
    with pytest.raises(cn.NaoGravou):
        cn.desfazer("tok", apont.id, anotar=lambda a, d: anotado.append(a))
    assert anotado == [] and len(banco.t[cn.APONTAMENTOS]) == 1
    banco.barra_apagar = False
    with pytest.raises(cn.NaoGravou):           # linha que já sumiu
        cn.desfazer("tok", 999, anotar=lambda a, d: anotado.append(a))
    assert anotado == []


def test_apagar_aportador_barrado_pela_rls_avisa(banco):
    salva = _gravada(banco)
    sem_beta = ca.ContaControlada(salva.conta_erp, ABRE, (salva.aportadores[0],), id=salva.id)
    banco.barra_apagar = True
    with pytest.raises(RuntimeError, match="parou no meio"):
        cn.gravar_conta("tok", sem_beta, HOJE, [salva], anotar=lambda *a: None,
                        vistos=_ids(salva))


def test_corrida_no_apontamento_vira_correcao(banco):
    from nuvem import rest
    rec = ca.Recebimento("r1", HOJE, D("10.00"), "X")

    def outro_admin(b):
        b.t[cn.APONTAMENTOS].append(dict(id=50, conta_id=7, recebimento_erp="r1",
                                         aportador_id=4, valor="10.00", motivo="outro"))
        raise rest.RecusadoPeloBanco("duplicate key value [HTTP 409]")
    banco.ao_inserir = outro_admin
    cn.apontar("tok", _salva(), rec, 3, "meu", anotar=lambda *a: None)
    linhas = banco.t[cn.APONTAMENTOS]
    assert len(linhas) == 1 and linhas[0]["aportador_id"] == 3 and linhas[0]["motivo"] == "meu"


def test_corrida_que_ainda_falha_da_mensagem_em_portugues(banco):
    from nuvem import rest
    rec = ca.Recebimento("r1", HOJE, D("10.00"), "X")

    def estranho(b):
        raise rest.RecusadoPeloBanco("duplicate key value [HTTP 409]")
    banco.ao_inserir = estranho
    with pytest.raises(cn.NaoGravou, match="Outro administrador"):
        cn.apontar("tok", _salva(), rec, 3, "meu", anotar=lambda *a: None)


def test_recusa_do_banco_que_nao_e_duplicata_sobe_como_esta(banco):
    from nuvem import rest

    def nega(b):
        raise rest.RecusadoPeloBanco("violates check constraint")
    banco.ao_inserir = nega
    with pytest.raises(rest.RecusadoPeloBanco):
        cn.apontar("tok", _salva(), ca.Recebimento("r1", HOJE, D("10.00"), "X"), 3, "m",
                   anotar=lambda *a: None)


def test_aportador_incluido_por_outro_admin_nao_e_apagado(banco):
    salva = _gravada(banco)
    banco.t[cn.APORTADORES].append(dict(id=99, conta_id=salva.id, nome_erp="CICLANO GAMA",
                                        peso="1", abertura="0.00"))
    banco.ordem.clear()
    with pytest.raises(ValueError, match="CICLANO GAMA"):
        cn.gravar_conta("tok", salva, HOJE, [salva], anotar=lambda *a: None,
                        vistos=_ids(salva))
    assert banco.ordem == []


def test_conta_existente_sem_vistos_recusa(banco):
    salva = _gravada(banco)
    with pytest.raises(ValueError, match="carregou"):
        cn.gravar_conta("tok", salva, HOJE, [salva], anotar=lambda *a: None)


def test_sem_rede_ou_login_vencido_sobe_como_esta(banco, monkeypatch):
    from nuvem import rest
    salva = _gravada(banco)
    for erro in (rest.SemRede("x"), rest.PrecisaEntrar("y")):
        def falha(*a, _e=erro, **k):
            raise _e
        monkeypatch.setattr(rest, "alterar", falha)   # nada gravado ainda
        with pytest.raises(type(erro)):
            cn.gravar_conta("tok", salva, HOJE, [salva], anotar=lambda *a: None,
                            vistos=_ids(salva))


def test_le_numeros_que_vieram_como_float_no_json(banco):
    banco.t[cn.CONTAS].append(dict(id=1, conta_erp="C", abertura="2026-10-21", ativa=True))
    banco.t[cn.APORTADORES].append(dict(id=2, conta_id=1, nome_erp=ALFA, peso=1.0,
                                        abertura=40000.0))
    banco.t[cn.APONTAMENTOS].append(dict(id=3, conta_id=1, recebimento_erp="r", aportador_id=2,
                                         valor=10.5, motivo="m"))
    contas, apont = cn.ler("tok")
    assert contas[0].aportadores[0].peso == D(1)
    assert contas[0].aportadores[0].abertura == D("40000.00")
    assert apont[1][0].valor == D("10.50")


# ---- onda final de consertos (22/10) ------------------------------------------

@pytest.mark.parametrize("erro", ["SemRede", "PrecisaEntrar"])
def test_sem_rede_depois_da_primeira_escrita_diz_que_parou_no_meio(banco, monkeypatch, erro):
    from nuvem import rest
    salva = _gravada(banco)
    nova = ca.ContaControlada(salva.conta_erp, ABRE, id=salva.id, aportadores=(
        *salva.aportadores, ca.Aportador("CICLANO GAMA", D(1))))

    def falha(*a, **k):
        raise getattr(rest, erro)("caiu")
    monkeypatch.setattr(rest, "inserir", falha)      # a conta já foi alterada
    with pytest.raises(RuntimeError, match="parou no meio") as info:
        cn.gravar_conta("tok", nova, HOJE, [salva], anotar=lambda *a: None,
                        vistos=_ids(salva))
    assert isinstance(info.value.__cause__, getattr(rest, erro))


@pytest.mark.parametrize("tabela", [cn.CONTAS, cn.APORTADORES, cn.APONTAMENTOS])
def test_ler_recusa_resposta_no_teto_de_linhas_do_banco(banco, tabela):
    from nuvem.registro import LINHAS_MAXIMAS_POR_CONSULTA
    modelo = {cn.CONTAS: dict(conta_erp="C", abertura="2026-10-21", ativa=True),
              cn.APORTADORES: dict(conta_id=1, nome_erp=ALFA, peso="1", abertura="0"),
              cn.APONTAMENTOS: dict(conta_id=1, recebimento_erp="r", aportador_id=None,
                                    valor="1", motivo="m")}[tabela]
    banco.t[tabela] = [dict(modelo, id=i) for i in range(LINHAS_MAXIMAS_POR_CONSULTA - 1)]
    cn.ler("tok")                                     # 999: ainda inteiro
    banco.t[tabela].append(dict(modelo, id=99999))
    with pytest.raises(cn.LeituraCortada, match="1000"):
        cn.ler("tok")


@pytest.mark.parametrize("campo, valor", [("peso", "2"), ("abertura", "123.45"),
                                          ("nome_erp", "FULANO ALFA DA SILVA JUNIOR")])
def test_gravar_recusa_quando_outro_admin_mudou_o_aportador_carregado(banco, campo, valor):
    salva = _gravada(banco)
    vistos = _ids(salva)                               # o que o formulário carregou
    linha = next(l for l in banco.t[cn.APORTADORES] if l["nome_erp"] == ALFA)
    linha[campo] = valor                               # outro administrador gravou
    banco.ordem.clear()
    with pytest.raises(ValueError, match="mudou") as info:
        cn.gravar_conta("tok", salva, HOJE, [salva], anotar=lambda *a: None, vistos=vistos)
    assert "Nada foi gravado" in str(info.value)
    assert banco.ordem == []


def test_gravar_recusa_quando_outro_admin_tirou_um_aportador_carregado(banco):
    salva = _gravada(banco)
    vistos = _ids(salva)
    banco.t[cn.APORTADORES] = [l for l in banco.t[cn.APORTADORES] if l["nome_erp"] != BETA]
    banco.ordem.clear()
    with pytest.raises(ValueError, match="Nada foi gravado"):
        cn.gravar_conta("tok", salva, HOJE, [salva], anotar=lambda *a: None, vistos=vistos)
    assert banco.ordem == []


def test_gravar_com_o_mesmo_valor_escrito_de_outro_jeito_nao_recusa(banco):
    salva = _gravada(banco)
    vistos = _ids(salva)
    for l in banco.t[cn.APORTADORES]:                  # o banco devolve 1.0 e 40000
        l["peso"], l["abertura"] = "1.0", l["abertura"].rstrip("0").rstrip(".")
    cn.gravar_conta("tok", salva, HOJE, [salva], anotar=lambda *a: None, vistos=vistos)


def test_gravar_recusa_vistos_so_com_ids(banco):
    salva = _gravada(banco)
    with pytest.raises(ValueError, match="carregou"):
        cn.gravar_conta("tok", salva, HOJE, [salva], anotar=lambda *a: None,
                        vistos=[a.id for a in salva.aportadores])
