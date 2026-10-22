# -*- coding: utf-8 -*-
"""Entrega 5, tarefa 3b: a entrega 2 continua certa quando um lançamento vira
N linhas com o MESMO id (boletos que somam exato). Dados fictícios — o repo é
público."""
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace as NS

from test_boletos_somados import _ler_o_dia, _linhas

from pagamentos_dia import baixa_erp, confirmacao, retorno_dia
from tela_do_dia import agendados as ag
from tela_do_dia import conferencia as cf
from tela_do_dia import geracao
from tela_do_dia import lista_diretor as ldr
from tela_do_dia import pagamentos as pg
from tela_do_dia import passo2 as p2
from tela_do_dia.pagamentos import Pagamento, PagamentosDaConta

RAIZ = Path(__file__).resolve().parents[1]
CONTA = "CONTA EXEMPLO - SICOOB"
RECADO_2 = ("lançamento dividido em 2 boletos: edite/libere no ERP ou pague as "
            "partes como estão")


class _Mapa:
    """O mínimo do `AccountMapping` que `por_conta` usa: toda conta é a linha 8."""

    def is_ignored(self, conta):
        return False

    def resolve_label(self, conta):
        return NS(row=8, label="Conta Exemplo", exists_in_erp=True)


class _JaEnviado:
    ja_enviado = "já saiu na remessa nº 7"


def _dividido():
    """A leitura real do dia (passo 1 → divisão): L1 de R$ 1.000 em 400 + 600."""
    leitura, linhas, _api = _ler_o_dia([40000, 60000])
    return leitura, linhas


def _entram(grupos):
    return [ln for g in grupos for ln in g.entram]


def _ev(i, alvo, acao, **k):
    return {"id": i, "alvo": alvo, "conta": CONTA, "acao": acao, **k}


# ------------------------------------------------- a parte chega à tela
def test_a_linha_da_confirmacao_e_o_pagamento_trazem_a_parte():
    leitura, _l = _dividido()
    entram = _entram(leitura.grupos)
    assert sorted(ln.parte for ln in entram) == ["1/2", "2/2"]
    assert all(ln.parte_linha and ln.parte_linha.isdigit() for ln in entram)
    painel, _fora = pg.por_conta(leitura.grupos, _Mapa())
    saem = painel[8].saem
    assert sorted(p.parte for p in saem) == ["1/2", "2/2"]
    assert {p.parte_linha for p in saem} == {ln.parte_linha for ln in entram}


def test_linha_nao_dividida_nao_tem_parte():
    leitura, _l, _api = _ler_o_dia([100000])
    (ln,) = _entram(leitura.grupos)
    assert (ln.parte, ln.parte_linha) == ("", "")
    painel, _fora = pg.por_conta(leitura.grupos, _Mapa())
    assert painel[8].saem[0].parte == ""


# ----------------------------------------------------- (a) iid estável
def _pag(ident, valor="10.00", parte="", parte_linha=""):
    return Pagamento(id=ident, conta_erp=CONTA, favorecido=f"Fornecedor {ident}",
                     valor=D(valor), situacao="ok", estado="ok", parte=parte,
                     parte_linha=parte_linha)


def test_iid_e_o_id_com_a_linha_da_parte_e_nao_muda_entre_recalculos():
    p1, p2_ = _pag("L1", "30.00", "1/2", "111"), _pag("L1", "20.00", "2/2", "222")
    antes = p2.linhas_da_conta(PagamentosDaConta("Conta Alfa", 8, vao_sair=[p1, p2_]), 0)
    assert [ln.iid for ln in antes] == ["L1|111", "L1|222"]
    # Desmarcado (outro grupo, outra posição, outra conta na frente): mesmo iid.
    depois = p2.linhas_da_conta(PagamentosDaConta("Conta Alfa", 8, vao_sair=[_pag("L0")],
                                                  desmarcados=[p1, p2_]), 5)
    assert [ln.iid for ln in depois if ln.pagamento.id == "L1"] == ["L1|111", "L1|222"]


def test_iid_nunca_repete_mesmo_com_chave_igual():
    vistos = set()
    a = p2.linhas_da_conta(PagamentosDaConta("Conta Alfa", 8, vao_sair=[_pag("L1"), _pag("L1")]),
                           0, vistos)
    b = p2.linhas_da_conta(PagamentosDaConta("Conta Beta", 9, bloqueados=[_pag("L1")]), 1, vistos)
    iids = [ln.iid for ln in (*a, *b)]
    assert len(set(iids)) == 3 and iids[0] == "L1|"


def test_a_linha_e_o_registro_da_parte_selecionada():
    leitura, _l = _dividido()
    segunda = next(ln for ln in _entram(leitura.grupos) if ln.parte == "2/2")
    achada = p2.linha_do_id(leitura.grupos, "L1", CONTA, segunda.parte_linha)
    assert achada is segunda
    reg = geracao.registro_atual(leitura.resultado, "L1", segunda.parte_linha)
    assert reg["parte"] == "2/2"
    assert geracao.registro_atual(leitura.resultado, "L1")["parte"] == "1/2"   # o de sempre


# ------------------------------------------------- (b) agendado somado
def _conta_com(*pags):
    return PagamentosDaConta("Conta Exemplo", 8, vao_sair=list(pags))


def _lanc():
    return [{"id": "L1", "remainingValue": 50.0, "plannedDate": "2026-10-22",
             "paidTo": "Fornecedor Modelo Ltda", "tradePayableId": "T1",
             "description": "OBRA MODELO NF 9", "tradePayablePaymentMethod": "Boleto"}]


def _agendados(itens):
    return [ag.Agendado.de_linha({**linha, "id": i, "dia": "2026-10-22"})
            for i, linha in enumerate(ag.linhas_para_nuvem(itens), 1)]


def test_lancamento_dividido_vira_um_agendado_com_a_soma_e_a_lista_soma_50():
    conta = _conta_com(_pag("L1", "30.00", "1/2", "111"), _pag("L1", "20.00", "2/2", "222"))
    itens = ag.para_marcar({8: conta}, [], _lanc(), cf.Conferencia(), set())
    assert len(itens) == 1
    assert itens[0].valor == D("50.00")
    assert itens[0].foto["partes"] == [{"parte_linha": "111", "valor": "30.00"},
                                       {"parte_linha": "222", "valor": "20.00"}]
    linhas = ag.linhas_para_nuvem(itens)
    assert len(linhas) == 1 and linhas[0]["valor"] == "50.00"
    lista = ldr.montar(_agendados(itens), lambda c: "Conta Exemplo", {})
    assert [l.valor for l in lista] == [D("50.00")]


def test_so_uma_parte_sai_o_agendado_e_so_ela_e_a_foto_diz_qual():
    conta = _conta_com(_pag("L1", "30.00", "1/2", "111"))
    conta.desmarcados.append(_pag("L1", "20.00", "2/2", "222"))
    (item,) = ag.para_marcar({8: conta}, [], _lanc(), cf.Conferencia(), set())
    assert item.valor == D("30.00")
    assert item.foto["partes"] == [{"parte_linha": "111", "valor": "30.00"}]
    # Baixa só desta parte no ERP (50 → 20): prova de baixa parcial.
    (a,) = _agendados([item])
    s = ag.situacao(a, {"id": "L1", "paid": False, "remainingValue": 20.0})
    assert s.pre_marca and s.prova == ag.PROVA_BAIXA_PARCIAL


def test_nao_dividido_continua_sem_partes_na_foto():
    (item,) = ag.para_marcar({8: _conta_com(_pag("L1", "50.00"))}, [], _lanc(),
                             cf.Conferencia(), set())
    assert item.valor == D("50.00") and "partes" not in item.foto


# --------------------------------------- (c) liberar/editar recusam
def test_liberar_parte_recusa_com_o_recado():
    leitura, _l = _dividido()
    linha = _entram(leitura.grupos)[0]
    linha = replace(linha, candidato=_JaEnviado())          # um já enviado se libera...
    assert not p2.pode_liberar(linha)
    assert p2.recusa_de_liberar(linha) == RECADO_2
    assert p2.recusa_de_liberar(replace(linha, parte="", parte_linha="")) == ""


def test_editar_forma_de_parte_recusa_e_descricao_passa():
    reg = {"tipo": "Boleto", "dados": "x", "parte": "1/2"}
    assert p2.validar_edicao_da_tela(reg, {"tipo": "Pix", "dados": "PIX EMAIL f@exemplo.com"},
                                     "erro do ERP") == RECADO_2
    assert cf.recusa_de_dividido(reg) == RECADO_2
    assert cf.recusa_de_dividido({"tipo": "Boleto"}) == ""
    assert p2.validar_edicao_da_tela(reg, {"descricao": "OBRA MODELO NF 9"}, "erro do ERP") == ""


def test_descricao_editada_vale_para_as_partes_e_a_forma_nao_vaza():
    leitura, linhas = _dividido()
    conf = cf.Conferencia((cf.Evento.de_linha(_ev(1, "L1", cf.EDITAR, motivo="ajuste da obra",
                                                  campos={"descricao": "OBRA MODELO LT 1 NF 9",
                                                          "tipo": "Pix",
                                                          "dados": "PIX EMAIL f@exemplo.com"})),))
    regs = _linhas(geracao.resultado_da_tela(leitura.entradas, leitura.grupos, conf))
    assert len(regs) == 2
    assert {r["descricao"] for r in regs} == {"OBRA MODELO LT 1 NF 9"}
    assert {r["tipo"] for r in regs} == {"Boleto"}             # forma de pagar ignorada
    assert sorted(r["dados"] for r in regs) == sorted(linhas)  # cada parte com o SEU boleto


def test_desmarcar_tira_todas_as_partes_na_tela_e_nos_arquivos():
    leitura, _l = _dividido()
    conf = cf.Conferencia((cf.Evento.de_linha(_ev(1, "L1", cf.DESMARCAR, motivo="depois")),))
    painel, _fora = pg.por_conta(leitura.grupos, _Mapa(), conf)
    assert painel[8].saem == [] and len(painel[8].desmarcados) == 2
    r = geracao.resultado_da_tela(leitura.entradas, leitura.grupos, conf)
    assert geracao.chaves_que_saem(r) == set()
    assert "2 partes" in p2.texto_do_desmarcar(painel[8].desmarcados[0])
    assert "partes" not in p2.texto_do_desmarcar(_pag("L9"))


# -------------------------------------------- (e) já enviado por id
def _com_um_enviado(leitura, todas=False):
    grupos = []
    for g in leitura.grupos:
        entram = [replace(ln, candidato=_JaEnviado()) if (todas or ln.parte == "1/2") else ln
                  for ln in g.entram]
        grupos.append(replace(g, entram=entram))
    return grupos


def test_uma_parte_ja_enviada_bloqueia_as_outras_lado_seguro():
    leitura, _l = _dividido()
    for todas in (False, True):
        grupos = _com_um_enviado(leitura, todas)
        painel, _fora = pg.por_conta(grupos, _Mapa())
        assert painel[8].saem == [] and len(painel[8].ja_enviados) == 2, todas
        r = geracao.resultado_da_tela(leitura.entradas, grupos, cf.Conferencia())
        assert geracao.chaves_que_saem(r) == {p.id for p in painel[8].saem}


def test_liberacao_gravada_para_lancamento_dividido_nao_reenvia_partes():
    """A tela recusa liberar parte; uma liberação que chegue pela nuvem (outra
    máquina, app velho) também não reenvia: a tela e os arquivos concordam."""
    leitura, _l = _dividido()
    grupos = _com_um_enviado(leitura, todas=True)
    conf = cf.Conferencia((cf.Evento.de_linha(_ev(1, "L1", cf.LIBERAR, motivo="pagar já")),))
    painel, _fora = pg.por_conta(grupos, _Mapa(), conf)
    assert painel[8].saem == [] and len(painel[8].ja_enviados) == 2
    r = geracao.resultado_da_tela(leitura.entradas, grupos, conf)
    assert geracao.chaves_que_saem(r) == set()


# ------------------------------------------------ (d) baixa no ERP
def _retorno(*linhas):
    return retorno_dia.Resumo(convenio="", nsa=0, empresa="", linhas=list(linhas))


def _ret(seu, ref, valor):
    return retorno_dia.Linha(seu_numero=seu, favorecido="Fornecedor Modelo Ltda",
                             valor=D(valor), estado="ok", motivos="", referencia=ref)


def test_baixa_de_lancamento_dividido_vindo_da_tela_nova_fica_de_fora_com_motivo():
    leitura, _l = _dividido()
    res = geracao.para_a_remessa(geracao.resultado_da_tela(
        leitura.entradas, leitura.grupos, cf.Conferencia()))
    divididos = baixa_erp.divididos_do_resultado(res)
    assert divididos == {"L1": 2}
    sep = baixa_erp.separar(_retorno(_ret("1", "L1", "400.00"), _ret("2", "L2", "10.00")),
                            divididos=divididos)
    assert [l.referencia for l in sep.baixaveis] == ["L2"]
    assert [(l.referencia, m) for l, m in sep.de_fora] == [
        ("L1", "lançamento dividido em 2 boletos — baixe no ERP quando todos saírem")]


def test_baixa_sem_resultado_da_tela_nova_e_a_de_sempre():
    leitura, _l, _api = _ler_o_dia([100000])
    assert baixa_erp.divididos_do_resultado(leitura.resultado) == {}
    assert baixa_erp.divididos_do_resultado(None) == {}
    sep = baixa_erp.separar(_retorno(_ret("1", "L1", "1000.00")))
    assert [l.referencia for l in sep.baixaveis] == ["L1"] and sep.de_fora == []


def test_a_aba_remessa_passa_os_divididos_do_resultado_que_recebeu():
    fonte = (RAIZ / "pagamentos_dia/pagamentos_frame.py").read_text(encoding="utf-8")
    trecho = fonte[fonte.index("def _seguir_para_a_baixa"):]
    trecho = trecho[:trecho.index("\n    def ", 10)]
    assert "baixa_erp.divididos_do_resultado(self.resultado)" in trecho


# ---------------------------------------------- (f) sem parte, nada muda
def test_registro_sem_parte_continua_recebendo_a_forma_editada():
    reg = {"tipo": "Boleto", "dados": "x", "status": "APTO", "id": "L1"}
    d = cf.dobrar([cf.Evento.de_linha(_ev(1, "L1", cf.EDITAR, motivo="erro do ERP",
                                          campos={"tipo": "Pix", "dados": "PIX EMAIL f@exemplo.com"}))])["L1"]
    out = geracao.aplicar_decisao(dict(reg), d, liberavel=False)
    assert (out["tipo"], out["dados"]) == ("Pix", "PIX EMAIL f@exemplo.com")
    assert confirmacao.Linha.__dataclass_fields__["parte"].default == ""


# ------------------------------------------------- conserto, rodada 1
def test_b1_retorno_com_duas_linhas_da_mesma_referencia_e_dividido_sem_resultado():
    resumo = _retorno(_ret("1", "L1", "400.00"), _ret("2", "L1", "600.00"),
                      _ret("3", "L2", "10.00"))
    assert baixa_erp.divididos_do_retorno(resumo) == {"L1": 2}
    sep = baixa_erp.separar(resumo, divididos=baixa_erp.divididos_do_retorno(resumo))
    assert [l.referencia for l in sep.baixaveis] == ["L2"]
    assert [(l.referencia, m) for l, m in sep.de_fora] == [
        ("L1", baixa_erp.MOTIVO_DIVIDIDO.format(n=2))] * 2


def test_b1_conta_qualquer_estado_e_junta_com_o_do_resultado():
    pendente = replace(_ret("2", "L1", "600.00"), estado="pendente")
    resumo = _retorno(_ret("1", "L1", "400.00"), pendente)
    assert baixa_erp.divididos_do_retorno(resumo) == {"L1": 2}
    assert baixa_erp.juntar_divididos({"L1": 2}, {"L3": 3}, {}) == {"L1": 2, "L3": 3}


def test_b1_mesma_referencia_em_dois_retornos_nao_e_divisao():
    a, b = _retorno(_ret("1", "L1", "100.00")), _retorno(_ret("9", "L1", "100.00"))
    divididos = baixa_erp.juntar_divididos(*(baixa_erp.divididos_do_retorno(r) for r in (a, b)))
    assert divididos == {}
    sep = baixa_erp.separar(_retorno(*a.linhas, *b.linhas), divididos=divididos)
    assert len(sep.baixaveis) == 2


def test_b1_a_aba_calcula_por_resumo_antes_de_juntar():
    fonte = (RAIZ / "pagamentos_dia/pagamentos_frame.py").read_text(encoding="utf-8")
    assert "self._seguir_para_a_baixa(resumo.linhas, top.destroy,\n" in fonte
    assert "divididos=baixa_erp.divididos_do_retorno(resumo)" in fonte
    assert "baixa_erp.divididos_do_retorno(r) for r in conhecidos" in fonte
    trecho = fonte[fonte.index("def _seguir_para_a_baixa"):]
    trecho = trecho[:trecho.index("\n    def ", 10)]
    assert "baixa_erp.juntar_divididos(" in trecho


def test_i2_retorno_do_banco_nao_prova_agendado_dividido():
    envio = NS(retorno_estado="ok")
    linha = {"id": 1, "dia": "2026-10-22", "conta": CONTA, "alvo": "L1", "lancamento_id": "L1",
             "favorecido": "Fornecedor Modelo Ltda", "valor": "50.00",
             "foto": {"em_aberto": "50.00", "partes": [{"parte_linha": "111", "valor": "30.00"},
                                                       {"parte_linha": "222", "valor": "20.00"}]}}
    titulo = {"id": "L1", "paid": False, "remainingValue": 50.0}
    s = ag.situacao(ag.Agendado.de_linha(linha), titulo, envio)
    assert not s.pre_marca
    um = {**linha, "foto": {"em_aberto": "50.00"}}
    assert ag.situacao(ag.Agendado.de_linha(um), titulo, envio).prova == ag.PROVA_RETORNO
    pago = ag.situacao(ag.Agendado.de_linha(linha), {**titulo, "paid": True}, envio)
    assert pago.pre_marca and pago.prova == ag.PROVA_BAIXA


def test_m1_forma_editada_e_liberacao_da_nuvem_avisam_na_tela():
    leitura, _l = _dividido()
    conf = cf.Conferencia((cf.Evento.de_linha(_ev(1, "L1", cf.EDITAR, motivo="erro do ERP",
                                                  campos={"tipo": "Pix",
                                                          "dados": "PIX EMAIL f@exemplo.com"})),))
    painel, _fora = pg.por_conta(leitura.grupos, _Mapa(), conf)
    for p in painel[8].saem:
        assert "forma editada IGNORADA: lançamento dividido em 2 boletos" in p.nota
        assert p.estado == "atencao"
    grupos = _com_um_enviado(leitura, todas=True)
    conf = cf.Conferencia((cf.Evento.de_linha(_ev(1, "L1", cf.LIBERAR, motivo="pagar já")),))
    painel, _fora = pg.por_conta(grupos, _Mapa(), conf)
    for p in painel[8].ja_enviados:
        assert "liberação IGNORADA: lançamento dividido em 2 boletos" in p.nota
        assert p.estado == "atencao"
    # Só a descrição: nada de aviso.
    conf = cf.Conferencia((cf.Evento.de_linha(_ev(1, "L1", cf.EDITAR, motivo="ajuste",
                                                  campos={"descricao": "OBRA MODELO NF 9"})),))
    painel, _fora = pg.por_conta(leitura.grupos, _Mapa(), conf)
    assert all("IGNORADA" not in p.nota for p in painel[8].saem)
