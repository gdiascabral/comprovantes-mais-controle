"""Autenticar no banco: o casamento agendado × banco. Dados fictícios."""
from datetime import date
from decimal import Decimal as D

from tela_do_dia import agendados as agd
from tela_do_dia import autenticar as au

HOJE = date(2026, 10, 29)
CONTA = "CONTA FICTICIA - SICOOB"
OUTRA = "OUTRA FICTICIA - SICOOB"
DESC = "OBRA MODELO CASA 7 NF 1234 OC 55 CIMENTO FICTICIO E AREIA FINA"
# Linha digitável fictícia que fecha nos DVs (a mesma família do teste do OCR).
LINHA = "34191570070002492437524177010006915340000115000"


def _ag(id_=1, valor="200.00", dia=date(2026, 10, 28), conta=CONTA, **foto):
    base = {"descricao_colada": DESC, "em_aberto": valor}
    base.update(foto)
    return agd.Agendado(id=id_, dia=dia, conta=conta, alvo=str(id_), lancamento_id=f"L{id_}",
                        favorecido="FORNECEDOR FICTICIO", valor=D(valor), foto=base)


def _mov(valor="200.00", dia=date(2026, 10, 28), desc=DESC, conta=CONTA, cod="", fav="",
         origem="Sicoob comprovante"):
    return au.Movimento(conta, dia, D(valor), cod, desc, fav, origem)


def _aut(pend, movs, **kw):
    kw.setdefault("lidas", {CONTA, OUTRA})
    return au.autenticar(pend, movs, hoje=HOJE, **kw)


def test_valor_e_descricao_colada_provam():
    r = _aut([_ag()], [_mov()])
    assert r[1].prova.startswith("banco — Sicoob comprovante 28/10: mesmo valor e descrição")


def test_descricao_cortada_pelo_banco_ainda_prova_mas_lote_vizinho_nao():
    assert _aut([_ag()], [_mov(desc=DESC[:45])])[1].prova
    # Corte curto não é corte do banco: pode ser OUTRO pagamento mais curto.
    assert not _aut([_ag()], [_mov(desc=DESC[:30])])[1].prova
    ag = _ag(**{"descricao_colada": "OBRA MODELO CASAS VIZINHAS LT 10"})
    assert not _aut([ag], [_mov(desc="OBRA MODELO CASAS VIZINHAS LT 10 E 11")])[1].prova
    ag2 = _ag(**{"descricao_colada": "OBRA MODELO CASAS VIZINHAS LT 10 E 11"})
    assert not _aut([ag2], [_mov(desc="OBRA MODELO CASAS VIZINHAS LT 10")])[1].prova


def test_so_valor_nao_prova():
    assert _aut([_ag()], [_mov(desc="OUTRA COISA QUALQUER DE MESMO VALOR")])[1].prova == ""


def test_codigo_de_barras_prova_mesmo_sem_descricao():
    cod = au.barras(LINHA)
    assert len(cod) == 44
    r = _aut([_ag(linha=LINHA, descricao_colada="")], [_mov(desc="", cod=cod)])
    assert "código de barras" in r[1].prova


def test_codigo_diferente_derruba_mesmo_com_valor_e_descricao():
    outro = "1" * 44
    assert _aut([_ag(linha=LINHA)], [_mov(cod=outro)])[1].prova == ""


def test_outra_conta_nao_prova():
    assert _aut([_ag()], [_mov(conta=OUTRA)])[1].prova == ""


def test_data_antes_do_dia_anterior_nao_prova():
    assert _aut([_ag()], [_mov(dia=date(2026, 10, 26))])[1].prova == ""
    assert _aut([_ag()], [_mov(dia=date(2026, 10, 27))])[1].prova


def test_dois_agendados_iguais_e_dois_pagamentos_iguais_provam_os_dois():
    r = _aut([_ag(1), _ag(2)], [_mov(), _mov()])
    assert r[1].prova and r[2].prova


def test_dois_agendados_iguais_e_um_pagamento_nenhum_prova():
    r = _aut([_ag(1), _ag(2)], [_mov()])
    assert r[1].prova == r[2].prova == "" and "responda" in r[1].nota


def test_um_agendado_e_dois_pagamentos_iguais_nao_prova():
    r = _aut([_ag()], [_mov(), _mov()])
    assert r[1].prova == "" and "responda" in r[1].nota


def test_favorecido_desempata():
    movs = [_mov(fav="FORNECEDOR FICTICIO"), _mov(fav="OUTRO FORNECEDOR")]
    assert _aut([_ag()], movs)[1].prova


def test_comprovante_de_agendamento_nao_entra():
    item = {"situacao": "AGENDADO", "valorLancamento": 200.0, "dataLancamento": "2026-10-28"}
    assert au.do_comprovante_sicoob(item, CONTA) is None
    item["situacao"] = "EFETIVADO"
    assert au.do_comprovante_sicoob(item, CONTA).valor == D("200.00")


def test_pix_conta_uma_vez_so_o_espelho_da_lista_comum_sai():
    espelho = {"situacao": "EFETIVADO", "valorLancamento": 200.0, "dataLancamento": "2026-10-28",
               "tipoAgendamento": "Pix via chave", "tipoOperacaoPix": "CHAVE"}
    assert au.do_comprovante_sicoob(espelho, CONTA) is None
    pix = au.do_pix_sicoob({"valor": "200,00", "descricao": DESC, "situacao": "EFETIVADO",
                            "dataHoraEnvioLancamento": "2026-10-28 10:00:00.000",
                            "destino": {"nome": "FORNECEDOR FICTICIO"}}, CONTA)
    assert pix is not None and pix.data == date(2026, 10, 28)
    assert _aut([_ag()], [pix])[1].prova


def test_pendencia_de_assinatura_derruba_a_prova():
    pend = au.da_pendencia({"situacao": "PENDENTE_ASSINATURA", "valor": 200.0,
                            "observacao": DESC}, CONTA)
    r = _aut([_ag()], [_mov()], pendencias=[pend])
    assert r[1].prova == "" and "pendente de assinatura" in r[1].nota


def test_dividido_em_n_boletos_so_prova_com_todas_as_partes():
    cod1, cod2 = au.barras(LINHA), "2" * 44
    partes = [{"parte_linha": LINHA, "valor": "120.00"}, {"parte_linha": "2" * 44, "valor": "80.00"}]
    ag = _ag(partes=partes)
    tudo = _aut([ag], [_mov("120.00", cod=cod1), _mov("80.00", cod=cod2)])
    assert "2 parte(s)" in tudo[1].prova
    falta = _aut([ag], [_mov("120.00", cod=cod1)])
    assert falta[1].prova == "" and "1 de 2" in falta[1].nota


def test_conta_que_falhou_diz_por_que_e_conta_de_outro_banco_fica_de_fora():
    r = au.autenticar([_ag(1), _ag(2, conta="CAIXA FICTICIA")], [_mov()],
                      lidas=set(), falhas={CONTA: "conta aberta no Sicoob não é a pedida"},
                      hoje=HOJE)
    assert r[1].nota.startswith("banco não lido") and 2 not in r


def test_a_prova_do_banco_vira_pre_marca_mas_nao_vence_valor_mudou():
    ag = _ag()
    prova = _aut([ag], [_mov()])[1].prova
    titulo = {"remainingValue": 200.0}
    assert agd.situacao(ag, titulo, prova_extra=prova).pre_marca
    mudou = {"remainingValue": 350.0}
    assert not agd.situacao(ag, mudou, prova_extra=prova).pre_marca


# ------------------------------------------- a situação refeita com a prova
def test_com_provas_do_banco_pre_marca_e_nao_vence_valor_mudou():
    from tela_do_dia import nuvem_do_dia as nd
    from tela_do_dia.conferencia import Conferencia
    a1, a2, a3 = _ag(1), _ag(2), _ag(3)
    sit = agd.Situacao("", "aguardando — responda")
    lido = nd.LidoDaNuvem(Conferencia(), pendentes=[(a1, sit, None), (a2, sit, None),
                                                    (a3, sit, None)],
                          titulos={"L1": {"remainingValue": 200.0},
                                   "L2": {"remainingValue": 999.0},
                                   "L3": {"remainingValue": 200.0}},
                          relido=True)
    aut = {1: au.Autenticacao("banco — Sicoob comprovante 28/10: mesmo valor e descrição"),
           2: au.Autenticacao("banco — x"),
           3: au.Autenticacao("", "pagamentos parecidos no banco, sem como separar — responda")}
    novo = nd.com_provas_do_banco(lido, aut)
    s1, s2, s3 = (s for _a, s, _r in novo.pendentes)
    assert s1.pre_marca and s1.prova.startswith("banco")
    assert not s2.pre_marca and "mudou" in s2.frase
    assert not s3.pre_marca and "banco: pagamentos parecidos" in s3.frase
    assert lido.pendentes[0][1] is sit                      # a leitura de antes não muda


def test_marcas_com_provas_marca_o_provado_e_guarda_o_resto():
    a1, a2 = _ag(1), _ag(2)
    sim, nao = agd.Situacao("ok", "p", True, "p"), agd.Situacao("", "x")
    antes = [(a1, nao, None), (a2, nao, None)]
    assert au.marcas_com_provas({1: False, 2: True}, antes,
                                [(a1, sim, None), (a2, nao, None)]) == {1: True, 2: True}
    # Quem perdeu a prova perde o ☑; quem o dono desmarcou e não mudou, fica.
    assert au.marcas_com_provas({1: True, 2: False}, [(a1, sim, None), (a2, sim, None)],
                                [(a1, nao, None), (a2, sim, None)]) == {1: False, 2: False}


def test_pix_sem_situacao_de_efetivado_nao_prova():
    item = {"valor": "200,00", "descricao": DESC, "dataHoraEnvioLancamento": "2026-10-28 10:00"}
    assert au.do_pix_sicoob(item, CONTA) is None
    assert au.do_pix_sicoob({**item, "situacao": "DEVOLVIDO"}, CONTA) is None


def test_pagamento_muito_depois_do_dia_e_do_vencimento_nao_prova():
    ag = _ag(dia=date(2026, 10, 20), vencimento="2026-10-21")
    assert _aut([ag], [_mov(dia=date(2026, 10, 24))])[1].prova
    assert _aut([ag], [_mov(dia=date(2026, 10, 25))])[1].prova == ""


def test_codigo_igual_com_valor_diferente_nao_prova():
    cod = au.barras(LINHA)
    assert _aut([_ag(linha=LINHA)], [_mov(valor="150.00", cod=cod)])[1].prova == ""


def test_dividido_com_uma_parte_so_usa_a_linha_dela_e_nunca_a_da_foto():
    cod_da_1a = au.barras(LINHA)
    ag = _ag(valor="80.00", linha=LINHA, partes=[{"parte_linha": "2" * 44, "valor": "80.00"}])
    # O comprovante da OUTRA parte (código da foto) não prova esta.
    assert _aut([ag], [_mov("80.00", cod=cod_da_1a)])[1].prova == ""
    assert _aut([ag], [_mov("80.00", cod="2" * 44)])[1].prova


def test_parte_de_dividido_nao_casa_por_descricao():
    ag = _ag(partes=[{"parte_linha": "", "valor": "120.00"}, {"parte_linha": "", "valor": "80.00"}])
    assert _aut([ag], [_mov("120.00"), _mov("80.00")])[1].prova == ""
