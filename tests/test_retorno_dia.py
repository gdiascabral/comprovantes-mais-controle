# -*- coding: utf-8 -*-
"""A leitura do retorno: o que o banco respondeu, casado com o que saiu.

Sem tela e sem rede. O que se testa aqui não é o parser do CNAB (isso é do
`cnab240`), e sim as decisões da aba: o que conta como pago, o que conta como
"ainda falta assinar", e o que fazer com pagamento que o banco simplesmente
não citou.
"""
from dataclasses import dataclass
from decimal import Decimal

import pytest

from cnab240 import historico
from nuvem import registro
from pagamentos_dia import retorno_dia


# ------------------------------------------------------------------ dublês

@dataclass
class _Pagamento:
    seu_numero: str
    favorecido: str = "FULANO"
    valor: Decimal = Decimal("100.00")
    ocorrencias: list = None
    _sucesso: bool = False
    _pendente: bool = False

    def __post_init__(self):
        if self.ocorrencias is None:
            self.ocorrencias = []

    @property
    def sem_ocorrencia(self):
        return not self.ocorrencias

    @property
    def sucesso(self):
        return self._sucesso

    @property
    def pendente(self):
        return self._pendente


class _Arquivo:
    def __init__(self, pagamentos, *, e_retorno=True, nsa=1, convenio="1814"):
        self._pg = pagamentos
        self.e_retorno = e_retorno
        self.nsa = nsa
        self.convenio = convenio
        self.empresa = "EMPRESA A"

    def pagamentos(self):
        return iter(self._pg)


class _Historico:
    def __init__(self, remessas):
        self._r = remessas

    def remessas(self, *, convenio=None):
        return self._r


@pytest.fixture
def ler(monkeypatch):
    def _ler(pagamentos, historico=None, **kw):
        arq = _Arquivo(pagamentos, **kw)
        import cnab240
        monkeypatch.setattr(cnab240, "ler_arquivo_retorno",
                            lambda _c: arq, raising=False)
        return retorno_dia.ler("qualquer.RET", historico)
    return _ler


def _remessa(itens, nsa=1, convenio="1814"):
    return [{"nsa": nsa, "convenio": convenio,
             "remessa_item": [{"seu_numero": s, "referencia": r}
                              for s, r in itens]}]


# ------------------------------------------------------------------ testes

def test_arquivo_de_remessa_e_recusado(ler):
    """Confundir os dois é fácil: os dois saem do SicoobNet e têm o mesmo
    formato. Ler uma remessa como retorno mostraria "nenhuma resposta" em
    tudo, que parece problema no banco."""
    with pytest.raises(ValueError, match="não é um retorno"):
        ler([], e_retorno=False)


def test_pago_pendente_e_rejeitado_sao_estados_distintos(ler):
    resumo = ler([
        _Pagamento("001", ocorrencias=[("00", "ok")], _sucesso=True),
        _Pagamento("002", ocorrencias=[("PD", "pendente de assinatura")],
                   _pendente=True),
        _Pagamento("003", ocorrencias=[("AG", "conta invalida")]),
    ])
    assert [l.estado for l in resumo.linhas] == ["ok", "pendente", "rejeitado"]
    assert resumo.quantos("ok") == 1
    assert resumo.linhas[1].rotulo == "AGUARDA ASSINATURA"


def test_sem_ocorrencia_nao_e_sucesso(ler):
    """Registro sem código não é "deu certo": é "o banco não disse nada".
    Tratar como sucesso daria o pagamento por feito sem nenhuma prova."""
    resumo = ler([_Pagamento("001")])
    assert resumo.linhas[0].estado == "?"
    assert resumo.linhas[0].rotulo == "SEM RESPOSTA"


def test_tudo_pendente_mantem_a_remessa_como_enviada(ler):
    """O caso normal do primeiro retorno: o app agenda e o master assina
    depois. Marcar como processada esconderia que o dinheiro não saiu."""
    resumo = ler([_Pagamento("001", ocorrencias=[("PD", "x")], _pendente=True)])
    assert resumo.estado_da_remessa == "enviado"


def test_tudo_pago_marca_como_processada(ler):
    resumo = ler([_Pagamento("001", ocorrencias=[("00", "x")], _sucesso=True)])
    assert resumo.estado_da_remessa == "processado"


def test_um_rejeitado_contamina_a_remessa(ler):
    resumo = ler([
        _Pagamento("001", ocorrencias=[("00", "x")], _sucesso=True),
        _Pagamento("002", ocorrencias=[("AG", "y")]),
    ])
    assert resumo.estado_da_remessa == "rejeitado"


def test_o_estado_gravado_mantem_a_remessa_viva(ler):
    """A trava contra pagar duas vezes, em um assert.

    `remessa_dia._ja_enviado` só enxerga item de remessa VIVA. Um estado fora
    da lista tira a remessa inteira da pergunta "isto já foi mandado?" — e os
    pagamentos que o banco PAGOU voltam marcáveis na geração seguinte. Foi o
    que o `"com_erro"` fazia, sem erro nenhum: a coluna `estado` do banco não
    tem `check`, então a marcação era aceita em silêncio."""
    casos = {
        "vazio": [],
        "tudo pendente": [_Pagamento("001", ocorrencias=[("PD", "x")],
                                     _pendente=True)],
        "tudo pago": [_Pagamento("001", ocorrencias=[("00", "x")],
                                 _sucesso=True)],
        "um rejeitado": [_Pagamento("001", ocorrencias=[("AG", "y")])],
        "mistura": [_Pagamento("001", ocorrencias=[("00", "x")], _sucesso=True),
                    _Pagamento("002", ocorrencias=[("PD", "x")], _pendente=True),
                    _Pagamento("003", ocorrencias=[("AG", "y")]),
                    _Pagamento("004")],
    }
    for nome, pagamentos in casos.items():
        estado = ler(pagamentos).estado_da_remessa
        assert estado in historico.ESTADOS, nome
        assert estado in registro.ESTADOS_VIVOS, nome


def test_casa_com_o_lancamento_do_erp(ler):
    """É o de-para que faz o retorno reencontrar o caminho de volta: sem ele,
    "002 rejeitado" não diz qual pagamento do ERP precisa de atenção."""
    resumo = ler([_Pagamento("001", ocorrencias=[("00", "x")], _sucesso=True)],
                 _Historico(_remessa([("001", "id-do-erp-99")])))
    assert resumo.linhas[0].referencia == "id-do-erp-99"
    assert not resumo.remessa_desconhecida


def test_pagamento_que_nao_voltou_e_apontado(ler):
    """O banco devolve o que processou. O que sumiu no caminho não aparece
    em lugar nenhum do arquivo — só comparando com o que foi enviado."""
    resumo = ler([_Pagamento("001", ocorrencias=[("00", "x")], _sucesso=True)],
                 _Historico(_remessa([("001", "a"), ("002", "b"),
                                      ("003", "c")])))
    assert resumo.faltando == ["002", "003"]


def test_remessa_de_outra_maquina_e_reconhecida_como_desconhecida(ler):
    """Não confundir com "remessa vazia": uma pede aviso na tela e impede
    guardar o resultado, a outra é só uma remessa sem itens."""
    resumo = ler([_Pagamento("001")], _Historico(_remessa([("x", "y")], nsa=99)))
    assert resumo.remessa_desconhecida
    assert resumo.faltando == []


def test_sem_historico_le_o_arquivo_do_mesmo_jeito(ler):
    """O arquivo é a informação; o registro só enriquece. Sem rede, ver o que
    o banco respondeu continua valendo."""
    resumo = ler([_Pagamento("001", ocorrencias=[("00", "x")], _sucesso=True)])
    assert len(resumo.linhas) == 1
    assert resumo.linhas[0].referencia == ""
    assert not resumo.remessa_desconhecida
