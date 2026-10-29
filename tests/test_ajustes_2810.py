"""Pedidos do dono de 28/10/2026 na aba "Pagamentos do dia".

- reembolso dos sócios escolhido no cartão 2 (`geracao.sem_reembolsos`);
- ordem das contas no HTML (`html_pagamentos.ordenar_contas`,
  `decisoes.contas_que_aportam`);
- descrição curta no rateio entre lotes vizinhos (`html_pagamentos.cc_compacto`);
- a renovação da sessão da nuvem depois de o app ficar parado (`nuvem.rest`).

Nomes fictícios: o repositório é público.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest
import requests

from nuvem import rest
from pagamentos_dia import html_pagamentos as h
from tela_do_dia import conferencia as cf
from tela_do_dia import decisoes as dc
from tela_do_dia import geracao


# ------------------------------------------------------------ reembolso
def _linha(ident, nome="", reembolso=False):
    return SimpleNamespace(id=ident, reembolso=reembolso, reembolso_nome=nome,
                           favorecido="LOJA", valor=10.0)


def _grupos(*linhas, nao_aptos=()):
    return [SimpleNamespace(conta="CONTA A", entram=list(linhas), nao_aptos=list(nao_aptos))]


def test_sem_reembolsos_desmarca_so_os_das_pessoas():
    grupos = _grupos(_linha("1", "FULANO DE TAL", True), _linha("2", "CICLANO", True),
                     _linha("3"), nao_aptos=[_linha("4", "BELTRANO", True)])
    c, tirados = geracao.sem_reembolsos(cf.Conferencia(), grupos,
                                        ["FULANO DE TAL", "BELTRANO SOUZA"])
    d = c.decisoes
    assert len(tirados) == 2 and "reembolso para FULANO DE TAL" in tirados[0]
    assert set(d) == {"1", "4"}
    assert all(x.desmarcado and x.motivo_desmarcar == geracao.MOTIVO_SEM_REEMBOLSO
               for x in d.values())


def test_sem_reembolsos_ganha_de_liberar_gravado_e_le_o_nome_editado():
    liberar = cf.Evento(id=7, alvo="1", conta="CONTA A", acao=cf.LIBERAR, motivo="ok")
    editar = cf.Evento(id=8, alvo="2", conta="CONTA A", acao=cf.EDITAR, motivo="x",
                       campos={"reembolso_nome": "FULANO DE TAL"})
    base = cf.Conferencia(eventos=(liberar, editar))
    grupos = _grupos(_linha("1", "FULANO DE TAL", True), _linha("2"))
    d = geracao.sem_reembolsos(base, grupos, ["FULANO"])[0].decisoes
    assert d["1"].desmarcado and not d["1"].liberado
    assert d["2"].desmarcado
    # a conferência de origem (a da nuvem) não muda
    assert len(base.eventos) == 2


def test_sem_pessoas_ou_sem_reembolso_a_conferencia_e_a_mesma():
    base = cf.Conferencia()
    grupos = _grupos(_linha("1", "FULANO", True))
    assert geracao.sem_reembolsos(base, grupos, [])[0] is base
    assert geracao.sem_reembolsos(base, _grupos(_linha("1")), ["FULANO"])[0] is base


def test_sem_reembolsos_acha_pelo_reembolso_para_do_registro(monkeypatch):
    """A observação "REEMBOLSAR X" e o documento de quem não é sócio só
    preenchem o `reembolso_para` do registro, não a `Linha` (revisão de
    dinheiro, achado 1) — e o não apto liberado também conta."""
    pedidos = {}

    def remontar(entradas, nao, *, ids_liberados=()):
        pedidos["liberados"] = set(ids_liberados)
        from pagamentos_dia import relatorio
        return relatorio.Resultado({"CONTA A": [
            {"id": "1", "favorecido": "LOJA", "valor": 5.0, "reembolso_para": "FULANO"},
            {"id": "9", "favorecido": "LOJA", "valor": 6.0, "reembolso_para": ""}]}, [])

    monkeypatch.setattr(geracao.confirmacao, "remontar", remontar)
    grupos = _grupos(_linha("1"), _linha("9"), nao_aptos=[_linha("4")])
    c, tirados = geracao.sem_reembolsos(cf.Conferencia(), grupos, ["FULANO DE TAL"],
                                        entradas=object())
    assert set(c.decisoes) == {"1"} and pedidos["liberados"] == {"4"}
    assert tirados == ["LOJA — R$ 5,00 — reembolso para FULANO"]


def test_linha_tirada_pela_caixa_nao_aceita_acao():
    """Desfazer nela gravaria DESFAZER na nuvem e apagaria a edição real."""
    editar = cf.Evento(id=3, alvo="1", conta="A", acao=cf.EDITAR, motivo="x",
                       campos={"reembolso_nome": "FULANO"})
    nuvem = cf.Conferencia(eventos=(editar,))
    vale, _ = geracao.sem_reembolsos(nuvem, _grupos(_linha("1")), ["FULANO"])
    assert geracao.so_pela_caixa(nuvem, vale, "1")
    assert not geracao.so_pela_caixa(nuvem, nuvem, "1")
    desmarcado = cf.Evento(id=4, alvo="1", conta="A", acao=cf.DESMARCAR, motivo="dono")
    nuvem2 = cf.Conferencia(eventos=(editar, desmarcado))
    vale2, _ = geracao.sem_reembolsos(nuvem2, _grupos(_linha("1")), ["FULANO"])
    assert not geracao.so_pela_caixa(nuvem2, vale2, "1")


# ------------------------------------------------------------ ordem do HTML
def _conta(nome, n):
    return {"nome": nome, "entries": [{}] * n}


def test_ordem_quem_aporta_primeiro_depois_por_quantidade():
    contas = [_conta("ALFA", 2), _conta("BETA", 14), _conta("GAMA", 1),
              _conta("DELTA", 14), _conta("EPSILON", 7)]
    saida = h.ordenar_contas(contas, primeiras=["GAMA", "alfa", "NAO EXISTE"])
    assert [c["nome"] for c in saida] == ["GAMA", "ALFA", "BETA", "DELTA", "EPSILON"]


def test_contas_que_aportam_pela_soma_do_que_sai():
    movimentos = [
        {"de": "Rotulo B", "valor": Decimal("100.00")},
        {"de": "Rotulo A", "valor": Decimal("300.00")},
        {"de": "Rotulo B", "valor": Decimal("50.00")},
        {"de": "Pessoa de fora", "valor": Decimal("999.00")},
        {"de": "Rotulo C", "valor": Decimal("0.00")},
    ]
    rotulos = {"ERP A": "Rotulo A", "ERP B": "rotulo  b", "ERP C": "Rotulo C", "ERP D": ""}
    assert dc.contas_que_aportam(movimentos, list(rotulos), rotulos.get) == ["ERP A", "ERP B"]


def test_html_grava_na_ordem_pedida(tmp_path):
    from pagamentos_dia import relatorio
    reg = {"tipo": "Pix", "dados": "fulano@exemplo.com", "valor": 10.0, "favorecido": "X"}
    resultado = relatorio.Resultado({"ALFA - SICOOB": [dict(reg)],
                                     "BETA - SICOOB": [dict(reg), dict(reg, valor=11.0)]}, [])
    from datetime import date
    g = h.gravar(resultado, [], {}, tmp_path, date(2026, 10, 28), date(2026, 10, 28),
                 primeiras=["ALFA - SICOOB"])
    texto = g.geral.read_text(encoding="utf-8")
    assert texto.index("ALFA - SICOOB") < texto.index("BETA - SICOOB")
    g = h.gravar(resultado, [], {}, tmp_path, date(2026, 10, 28), date(2026, 10, 28))
    texto = g.geral.read_text(encoding="utf-8")
    assert texto.index("BETA - SICOOB") < texto.index("ALFA - SICOOB")


# ------------------------------------------------------------ descrição
def test_cc_compacto_junta_lotes_vizinhos():
    cc = "RUA X QD 9 LT 7A | RUA X QD 9 LT 7B | RUA X QD 9 LT 7C"
    assert h.cc_compacto(cc) == "RUA X QD 9 LT 7A 7B 7C"
    assert h.cc_compacto("RUA X QD 9 LT 7A") == "RUA X QD 9 LT 7A"
    assert h.cc_compacto("RUA X QD 9 LT 7A | OUTRA Y") == "RUA X QD 9 LT 7A OUTRA Y"
    # Só a última palavra muda é que encurta: outra quadra entra inteira.
    assert h.cc_compacto("QD 01 LT 01 | QD 02 LT 02") == "QD 01 LT 01 QD 02 LT 02"
    assert h.cc_compacto("RUA X QD 9 LT 7A | RUA X QD 9 LT 7A 2") == "RUA X QD 9 LT 7A RUA X QD 9 LT 7A 2"
    assert h.cc_compacto("") == ""


def test_descricao_do_rateio_fica_curta_e_o_anexar_ainda_casa():
    from anexar import matcher
    reg = {"centro_custo": "RUA X QD 9 LT 7A | RUA X QD 9 LT 7B | RUA X QD 9 LT 7C",
           "descricao_lancamento": "DESMEMBRAMENTO", "nf": "12345678", "tipo": "Boleto"}
    desc = h.descricao_para_colar(reg, "EMPRESA - SICOOB")
    assert desc == "RUA X QD 9 LT 7A 7B 7C DESMEMBRAMENTO 12345678"
    pe = {"doc": "", "desc": "", "data": None,
          "works": ["RUA X QD 9 LT 7A", "RUA X QD 9 LT 7B", "RUA X QD 9 LT 7C"]}
    pd = {"ocs": set(), "nfs": set(), "ndesc": matcher._norm(desc), "data": None}
    assert matcher._features(pe, pd)[1] is True


# ------------------------------------------------------------ nuvem
class _Resposta:
    status_code = 200
    content = b"{}"
    text = "{}"

    def json(self):
        return {"access_token": "a", "refresh_token": "r"}


class _SessaoQueCai:
    """A 1ª chamada cai como o socket que o servidor fechou; a 2ª responde."""

    def __init__(self, falhas):
        self.falhas, self.chamadas, self.fechou = falhas, 0, 0

    def post(self, *_a, **_k):
        self.chamadas += 1
        if self.chamadas <= self.falhas:
            raise requests.ConnectionError("Connection aborted: RemoteDisconnected")
        return _Resposta()

    def close(self):
        self.fechou += 1


def test_renovar_tenta_de_novo_por_conexao_nova(monkeypatch):
    sessao = _SessaoQueCai(falhas=1)
    monkeypatch.setattr(rest, "_SESSAO", sessao)
    assert rest.renovar("r")["access_token"] == "a"
    assert sessao.chamadas == 2 and sessao.fechou >= 1


def test_renovar_nao_repete_tempo_esgotado(monkeypatch):
    """A resposta perdida pode ter trocado o token: repetir deslogaria."""
    sessao = _SessaoQueCai(falhas=0)

    def post(*_a, **_k):
        sessao.chamadas += 1
        raise requests.ReadTimeout("sem resposta")

    sessao.post = post
    monkeypatch.setattr(rest, "_SESSAO", sessao)
    with pytest.raises(rest.SemRede):
        rest.renovar("r")
    assert sessao.chamadas == 1


def test_renovar_duas_quedas_e_sem_rede(monkeypatch):
    monkeypatch.setattr(rest, "_SESSAO", _SessaoQueCai(falhas=2))
    with pytest.raises(rest.SemRede):
        rest.renovar("r")


def test_conexao_parada_e_fechada_antes_do_proximo_pedido(monkeypatch):
    sessao = _SessaoQueCai(falhas=0)
    monkeypatch.setattr(rest, "_SESSAO", sessao)
    relogio = iter([1000.0, 1010.0, 1200.0])
    monkeypatch.setattr(rest.time, "monotonic", lambda: next(relogio))
    monkeypatch.setattr(rest, "_ultimo_pedido", 0.0)
    rest._acordar()           # primeiro pedido: nada a fechar
    rest._acordar()           # 10 s depois: conexão ainda boa
    assert sessao.fechou == 0
    rest._acordar()           # 190 s parado: fecha
    assert sessao.fechou == 1
