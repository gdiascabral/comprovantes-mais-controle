"""Os ganchos da tela do dia no código da Remessa: SEM eles, tudo igual a hoje."""
from datetime import date

from pagamentos_dia import confirmacao, html_pagamentos as hp, relatorio, remessa_dia
from pagamentos_dia import regras_pagamento as regras

DIA = date(2026, 10, 22)
CONTA = "CONTA EXEMPLO - SICOOB"
NF = {"filename": "nf", "tagName": "Nota Fiscal", "extension": ".pdf",
      "downloadUrl": "https://exemplo.invalid/nf.pdf"}


def _lanc(ident):
    return {"id": ident, "tradePayableId": f"T-{ident}", "paidTo": "Fornecedor Modelo Ltda",
            "remainingValue": 100.0, "plannedDate": "2026-10-22",
            "tradePayableAccount": {"name": CONTA}, "tradePayablePaymentMethod": "Pix",
            "paidToBankAccount": "PIX EMAIL fulano@exemplo.com", "documentNumber": "1234",
            "costCentreDetails": [{"workName": "OBRA MODELO"}], "paid": False}


LANCS = [_lanc("L1"), _lanc("L2")]
ANEXOS = {"T-L1": [NF]}                      # L2 sem anexo -> não apto


def test_sem_liberados_o_resultado_e_identico():
    assert (relatorio.montar_registros(LANCS, ANEXOS, {}, {})
            == relatorio.montar_registros(LANCS, ANEXOS, {}, {}, ids_liberados=()))


def test_liberado_sai_dos_omitidos_com_o_bloqueio_anotado():
    r = relatorio.montar_registros(LANCS, ANEXOS, {}, {}, ids_liberados={"L2"})
    assert not [o for o in r.omitidos if o["id"] == "L2"]
    reg = next(x for x in r.contas[CONTA] if x["id"] == "L2")
    assert reg["bloqueio_liberado"] == regras.MOTIVO_SEM_ANEXO
    assert "bloqueio_liberado" not in next(x for x in r.contas[CONTA] if x["id"] == "L1")


def test_desmarcado_ganha_de_liberado():
    r = relatorio.montar_registros(LANCS, ANEXOS, {}, {}, ids_nao_confirmados={"L2"},
                                   ids_liberados={"L2"})
    assert any(o["id"] == "L2" and o["motivo"] == regras.MOTIVO_NAO_CONFIRMADO
               for o in r.omitidos)


def test_remontar_sem_liberados_e_o_de_sempre():
    e = confirmacao.Entradas(selecionados=LANCS, anexos=ANEXOS, overviews={}, textos={},
                             urls_ocr=set(), cadastro_reembolso=None, regras_fornecedor={},
                             participantes={}, periodo=(DIA, DIA))
    assert confirmacao.remontar(e, {"L1"}) == confirmacao.remontar(e, {"L1"}, ids_liberados=())


def test_remontar_repassa_os_liberados():
    e = confirmacao.Entradas(selecionados=LANCS, anexos=ANEXOS, overviews={}, textos={},
                             urls_ocr=set(), cadastro_reembolso=None, regras_fornecedor={},
                             participantes={}, periodo=(DIA, DIA))
    r = confirmacao.remontar(e, ids_liberados={"L2"})
    assert [x["id"] for x in r.contas[CONTA] if x.get("bloqueio_liberado")] == ["L2"]


REG = {"tipo": "Pix", "dados": "fulano@exemplo.com", "valor": 10.0, "centro_custo": "OBRA MODELO",
       "nf": "1234", "nf_anexada": True, "oc_da_descricao": "", "descricao_lancamento": "compra",
       "utilidade": False}


def test_descricao_sem_a_chave_nova_nao_muda():
    for conta in (CONTA, "CONTA X - INTER"):
        assert hp.descricao_para_colar(REG, conta) == hp.descricao_para_colar(
            {**REG, "descricao_editada": ""}, conta)


def test_descricao_editada_vai_limpa_e_no_tamanho():
    texto = hp.descricao_para_colar({**REG, "descricao_editada": "OBRA MODELO pé-direito 1234"},
                                    CONTA, 20)
    assert texto == "OBRA MODELO pe"       # sem acento, sem hífen fora do Inter, corte em palavra


def test_remessa_so_leva_a_descricao_editada_quando_ela_existe():
    reg = {**REG, "status": "APTO", "id": "L1", "favorecido": "Fornecedor Modelo Ltda"}
    sem = remessa_dia.preparar({CONTA: [reg]})[CONTA][0]
    com = remessa_dia.preparar({CONTA: [{**reg, "descricao_editada": "OBRA MODELO 1234"}]})[CONTA][0]
    assert "descricao_editada" not in sem.partes
    assert remessa_dia.etiqueta_do_banco(com) == "OBRA MODELO 1234"
    assert remessa_dia.etiqueta_do_banco(sem) == hp.descricao_para_colar(sem.partes, None, 38)


# Conserto (ruling do coordenador): liberado na tela do dia nunca nasce APTO,
# então nunca nasce marcado na remessa CNAB nem na janela de confirmação.
SIMBOLICO = [{**_lanc("L5"), "remainingValue": 1.0}]
ANEXO_L5 = {"T-L5": [NF]}
SO_REEMBOLSO = {"FORNECEDOR MODELO": {"so_com_reembolso": True}}
#: Com o documento no cadastro de Contatos, uma linha APTO nasce MARCADA na
#: remessa (controle positivo abaixo) — é o que torna o "marcado is False"
#: do liberado uma prova, e não efeito de outro impedimento. CPF fictício
#: (o mesmo de `tests/test_remessa_dia.py`).
CONTATOS = {"FORNECEDOR MODELO LTDA": "52998224725"}


def test_controle_positivo_apto_com_documento_nasce_marcado():
    r = relatorio.montar_registros(LANCS, ANEXOS, {}, {})
    reg = next(x for x in r.contas[CONTA] if x["id"] == "L1")
    assert reg["status"] == "APTO"
    assert remessa_dia.preparar({CONTA: [reg]}, participantes=CONTATOS)[CONTA][0].marcado is True


def _liberado_nao_nasce_marcado(lancs, anexos, motivo, **kw):
    antes = relatorio.montar_registros(lancs, anexos, {}, {}, **kw)
    assert [o["motivo"] for o in antes.omitidos] == [motivo]       # o bloqueio existe
    r = relatorio.montar_registros(lancs, anexos, {}, {}, ids_liberados={"L5"}, **kw)
    reg = r.contas[CONTA][0]
    assert reg["status"] == relatorio.STATUS_LIBERADO and reg["bloqueio_liberado"] == motivo
    assert reg["status"].startswith("ATENÇÃO")
    cand = remessa_dia.preparar({CONTA: [reg]}, participantes=CONTATOS)[CONTA][0]
    assert cand.marcado is False and not cand.apto and not cand.impedimento


def test_liberado_valor_simbolico_nao_nasce_marcado():
    _liberado_nao_nasce_marcado(SIMBOLICO, ANEXO_L5, regras.MOTIVO_SIMBOLICO)


def test_liberado_so_com_reembolso_nao_nasce_marcado():
    _liberado_nao_nasce_marcado([_lanc("L5")], ANEXO_L5, regras.MOTIVO_REEMBOLSO,
                                regras_fornecedor=SO_REEMBOLSO)


def test_liberado_que_ja_era_atencao_guarda_o_alarme_de_sempre():
    r = relatorio.montar_registros(LANCS, ANEXOS, {}, {}, ids_liberados={"L2"})
    assert next(x for x in r.contas[CONTA] if x["id"] == "L2")["status"] == "ATENÇÃO — sem anexo"
