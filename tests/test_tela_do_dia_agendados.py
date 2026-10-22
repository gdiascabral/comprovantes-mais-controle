"""Agendados: nada some sem resposta, e sumiu/mudou nunca se resolve sozinho."""
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from tela_do_dia import agendados as ag

HOJE = date(2026, 10, 23)


def _ag(i=1, valor="100.00", em_aberto="100.00", lanc="L1"):
    return ag.Agendado.de_linha({"id": i, "dia": "2026-10-22", "conta": "C", "alvo": lanc or f"mao:{i}",
                                 "lancamento_id": lanc, "favorecido": "Fornecedor Modelo Ltda",
                                 "valor": valor, "foto": {"em_aberto": em_aberto, "vencimento": "2026-10-22"}})


def _r(i, agendado, resposta, **k):
    return ag.Resposta(id=i, agendado_id=agendado, resposta=resposta, **k)


def test_so_resposta_final_tira_da_lista_e_a_ultima_vale():
    a1, a2, a3 = _ag(1), _ag(2), _ag(3)
    resp = [_r(1, 1, "pago"), _r(2, 2, "reagendado", nova_data=HOJE), _r(3, 3, "pago"), _r(4, 3, "reagendado", nova_data=HOJE)]
    assert [a.id for a in ag.pendentes([a1, a2, a3], resp)] == [2, 3]


def test_a_ultima_vale_pelo_id_e_nao_pela_ordem_da_lista():
    resp = [_r(9, 1, "reagendado", nova_data=HOJE), _r(2, 1, "pago")]
    assert [a.id for a in ag.pendentes([_ag(1)], resp)] == [1]


def test_resposta_da_nuvem_vira_resposta():
    r = ag.Resposta.de_linha({"id": 5, "agendado_id": "7", "resposta": "reagendado",
                              "nova_data": "2026-10-23", "quem_nome": "Fulano Ficticio"})
    assert (r.agendado_id, r.nova_data, r.quem_nome, r.motivo) == (7, HOJE, "Fulano Ficticio", "")


def test_agendado_sem_valor_valido_nao_nasce():
    with pytest.raises(ValueError):
        _ag(valor="abc")


def test_pago_no_erp_pre_marca_com_prova():
    s = ag.situacao(_ag(), {"id": "L1", "paid": True, "remainingValue": 0.0})
    assert s.pre_marca and s.prova == ag.PROVA_BAIXA


def test_titulo_sumiu_nunca_se_resolve_mesmo_com_retorno_ok():
    s = ag.situacao(_ag(), None, SimpleNamespace(retorno_estado="ok"))
    assert not s.pre_marca and s.tag == "erro" and "título sumiu do ERP — era R$ 100,00" in s.frase


def test_valor_mudou_espera_o_dono():
    s = ag.situacao(_ag(), {"id": "L1", "paid": False, "remainingValue": 120.0})
    assert not s.pre_marca and "era R$ 100,00, agora R$ 120,00" in s.frase


def test_valor_mudou_nao_se_resolve_nem_com_retorno_ok():
    s = ag.situacao(_ag(), {"id": "L1", "paid": False, "remainingValue": 120.0},
                    SimpleNamespace(retorno_estado="ok"))
    assert not s.pre_marca and s.tag == "erro"


def test_baixa_parcial_ao_centavo_e_prova():
    s = ag.situacao(_ag(valor="30000.00", em_aberto="80000.00"), {"id": "L1", "paid": False, "remainingValue": 50000.0})
    assert s.pre_marca and s.prova == ag.PROVA_BAIXA_PARCIAL


def test_baixa_parcial_um_centavo_fora_nao_e_prova():
    s = ag.situacao(_ag(valor="30000.00", em_aberto="80000.00"), {"id": "L1", "paid": False, "remainingValue": 50000.01})
    assert not s.pre_marca and "era R$ 80.000,00, agora R$ 50.000,01" in s.frase


def test_retorno_ok_com_titulo_igual_e_prova_e_sem_releitura_nao_ha():
    titulo = {"id": "L1", "paid": False, "remainingValue": 100.0}
    assert ag.situacao(_ag(), titulo, SimpleNamespace(retorno_estado="ok")).prova == ag.PROVA_RETORNO
    assert not ag.situacao(_ag(), titulo, SimpleNamespace(retorno_estado="ok"), relido=False).pre_marca


def test_sem_releitura_titulo_ausente_nao_e_sumiu():
    s = ag.situacao(_ag(), None, relido=False)
    assert not s.pre_marca and "sumiu" not in s.frase


def test_retorno_que_nao_e_ok_nao_prova():
    titulo = {"id": "L1", "paid": False, "remainingValue": 100.0}
    for estado in ("", "rejeitado", None):
        s = ag.situacao(_ag(), titulo, SimpleNamespace(retorno_estado=estado))
        assert not s.pre_marca and s.prova == ""


def test_sem_foto_do_valor_ou_sem_valor_no_erp_nunca_pre_marca():
    titulo = {"id": "L1", "paid": False, "remainingValue": 100.0}
    s = ag.situacao(_ag(em_aberto=""), titulo, SimpleNamespace(retorno_estado="ok"))
    assert not s.pre_marca and s.tag == "atencao"
    s = ag.situacao(_ag(), {"id": "L1", "paid": False}, SimpleNamespace(retorno_estado="ok"))
    assert not s.pre_marca and s.tag == "atencao"


def test_a_mao_sem_lancamento_pede_resposta():
    s = ag.situacao(_ag(lanc=""), None)
    assert not s.pre_marca and "sem lançamento" in s.frase


def test_prova_extra_e_so_ponto_de_extensao_e_nunca_vence_sumiu_ou_mudou():
    """Comprovante baixado entra depois por `prova_extra`; nesta entrega ninguém
    passa, e mesmo passando não resolve título que sumiu ou mudou."""
    assert not ag.situacao(_ag(), None, prova_extra="comprovante").pre_marca
    assert not ag.situacao(_ag(), {"id": "L1", "paid": False, "remainingValue": 120.0},
                           prova_extra="comprovante").pre_marca
    s = ag.situacao(_ag(), {"id": "L1", "paid": False, "remainingValue": 100.0})
    assert not s.pre_marca and s.prova == ""


def test_intervalo_cobre_o_vencimento_mais_antigo():
    assert ag.intervalo_de_releitura([_ag()], HOJE) == (date(2026, 9, 21), date(2026, 11, 23))
    assert ag.intervalo_de_releitura([_ag(lanc="")], HOJE) is None


def _painel():
    p1 = SimpleNamespace(id="L1", conta_erp="C", favorecido="F", valor=D("10.00"))
    p2 = SimpleNamespace(id="L2", conta_erp="C", favorecido="F", valor=D("20.00"))
    return {8: SimpleNamespace(rotulo="Conta Alfa - Banco", linha=8, saem=[p1, p2])}


def test_para_marcar_nasce_marcado_e_pula_o_ja_marcado():
    lancs = [{"id": "L1", "remainingValue": 10.0, "plannedDate": "2026-10-22", "paidTo": "F",
              "tradePayableId": "T1", "tradePayablePaymentMethod": "Pix", "description": "compra"}]
    itens = ag.para_marcar(_painel(), [], lancs, None, {"L2"})
    assert [(i.alvo, i.marcado, i.ja_marcado) for i in itens] == [("L1", True, False), ("L2", False, True)]
    assert itens[0].foto["em_aberto"] == "10.00" and itens[0].foto["vencimento"] == "2026-10-22"
    linhas = ag.linhas_para_nuvem(itens)
    assert [l["alvo"] for l in linhas] == ["L1"] and linhas[0]["valor"] == "10.00"


def test_linhas_para_nuvem_nao_mandam_carimbo_nem_desmarcado():
    itens = ag.para_marcar(_painel(), [], [], None, set())
    itens[1].marcado = False
    linhas = ag.linhas_para_nuvem(itens)
    assert [l["alvo"] for l in linhas] == ["L1"]
    assert not {"quem", "quem_nome", "quando", "dia"} & set(linhas[0])
    # sem o item do ERP, a foto guarda o valor do dia como "em aberto"
    assert linhas[0]["foto"]["em_aberto"] == "10.00"


def test_a_mao_usa_o_registro_a_mao():
    p = SimpleNamespace(id="mao:4", conta_erp="C", favorecido="F", valor=D("50.00"))
    painel = {8: SimpleNamespace(rotulo="Conta Alfa - Banco", linha=8, saem=[p])}
    m = SimpleNamespace(alvo="mao:4", id=4, conta="C", lancamento_id="", descricao="d",
                        tipo="Pix", valor_em_aberto=None)
    conf = SimpleNamespace(a_mao=[m])
    (item,) = ag.para_marcar(painel, [], [], conf, set())
    assert (item.alvo, item.a_mao_id, item.lancamento_id, item.foto["a_mao"]) == ("mao:4", 4, "", True)
    assert ag.linhas_para_nuvem([item])[0]["a_mao_id"] == 4


def test_resposta_nao_saiu_exige_motivo_e_reagendado_exige_data():
    assert ag.validar_resposta("pago", "", None, HOJE) == ""
    assert "motivo" in ag.validar_resposta("nao_saiu", "", None, HOJE)
    assert "data" in ag.validar_resposta("reagendado", "", None, HOJE)
    assert "data" in ag.validar_resposta("reagendado", "", date(2026, 10, 1), HOJE)
    assert ag.validar_resposta("talvez", "", None, HOJE) != ""


def test_remarcar_no_mesmo_dia_e_reagendado_para_hoje():
    """O índice (dia, alvo) recusa marcar de novo no mesmo dia: remarcar é a
    resposta 'reagendado' com a data de hoje — e ela é válida."""
    assert ag.validar_resposta("reagendado", "", HOJE, HOJE) == ""
    assert ag.pendentes([_ag(1)], [_r(1, 1, "reagendado", nova_data=HOJE)])


def test_recado_das_repetidas_diz_o_que_fazer():
    assert ag.recado_das_repetidas([]) == ""
    r = ag.recado_das_repetidas([{"alvo": "L1", "favorecido": "Fornecedor Modelo Ltda", "valor": "10.00"}])
    assert "já estava marcado hoje" in r and "Fornecedor Modelo Ltda" in r and "R$ 10,00" in r
    assert "reagendado" in r and "hoje" in r
    r2 = ag.recado_das_repetidas([{"alvo": "L1", "valor": "10.00"}, {"alvo": "L2", "valor": "5.00"}])
    assert "2 pagamentos já estavam marcados hoje" in r2
