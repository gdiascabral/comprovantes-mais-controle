"""Pagamentos por conta: vão sair × bloqueados. Linhas fictícias."""
from decimal import Decimal as D

import pytest

from conciliacao.mapping import AccountMapping
from pagamentos_dia import confirmacao
from tela_do_dia import pagamentos as pg

MAPA = ("model_rows:\n"
        "- row: 8\n  label: Conta Alfa - Banco\n  uuid: uuid-alfa\n  erp_name: ALFA LTDA - BANCO\n"
        "- row: 9\n  label: Conta Beta - Banco\n  uuid: uuid-beta\n  erp_name: BETA LTDA - BANCO\n"
        "- row: 10\n  label: Conta Delta - Banco\n  exists_in_erp: false\n  erp_name: DELTA LTDA - BANCO\n"
        "ignored_erp_accounts:\n- CONTA DE AJUSTE\n")


@pytest.fixture
def mapa(tmp_path):
    caminho = tmp_path / "mapping.yaml"
    caminho.write_text(MAPA, encoding="utf-8")
    return AccountMapping.load(caminho)


class _JaEnviado:
    ja_enviado = "remessa nº 7"


def _ln(secao, ident, conta, valor, candidato=None, rejeitado=False):
    return confirmacao.Linha(secao=secao, id=ident, conta=conta, valor=valor,
                             favorecido=f"Fornecedor {ident}", tipo="Pix", dados="",
                             por_onde="", vencimento=None, oc="", centro_custo="",
                             descricao="", situacao="motivo ficticio", estado="ok",
                             olhar=False, candidato=candidato, envio_rejeitado=rejeitado)


def _grupos():
    alfa = "ALFA LTDA - BANCO"
    return [
        confirmacao.Grupo(alfa, entram=[_ln("entra", "A1", alfa, 100.1),
                                        _ln("entra", "A2", alfa, 50.0, candidato=_JaEnviado()),
                                        _ln("entra", "A3", alfa, 25.0, candidato=_JaEnviado(), rejeitado=True)],
                          nao_aptos=[_ln("nao_apto", "A4", alfa, 9.99)]),
        confirmacao.Grupo("GAMA SPE - BANCO", entram=[_ln("entra", "G1", "GAMA SPE - BANCO", 10.0)], nao_aptos=[]),
        confirmacao.Grupo("CONTA DE AJUSTE", entram=[_ln("entra", "X1", "CONTA DE AJUSTE", 1.0)], nao_aptos=[]),
    ]


def test_vai_sair_ja_enviado_e_bloqueado_ficam_separados(mapa):
    painel, _fora = pg.por_conta(_grupos(), mapa)
    alfa = painel[8]
    assert [p.id for p in alfa.vao_sair] == ["A1", "A3"]        # rejeitado volta a sair
    assert [p.id for p in alfa.ja_enviados] == ["A2"]           # não gera de novo...
    assert [p.id for p in alfa.bloqueados] == ["A4"]            # ...e só o não apto é bloqueado
    assert alfa.valor_bloqueado == D("9.99")
    assert alfa.valor_ja_enviado == D("50.00")


def test_ja_enviado_soma_no_a_pagar_porque_ainda_sai_da_conta(mapa):
    """Enviado em remessa e ainda não pago no ERP: o banco ainda vai debitar.
    Fora do a pagar, o D do painel e o aporte mínimo sairiam baixos."""
    painel, _fora = pg.por_conta(_grupos(), mapa)
    assert painel[8].a_pagar == D("175.10")                    # 100,10 + 25 + 50 (já enviado)
    assert painel[8].qtd_a_pagar == 3
    assert [p.id for p in painel[8].saem] == ["A1", "A3"]       # o que se GERA hoje


def test_a_pagar_e_decimal_exato(mapa):
    painel, _fora = pg.por_conta(_grupos(), mapa)
    assert painel[8].a_pagar == D("175.10") and painel[8].qtd_a_pagar == 3
    assert pg.totais_para_o_painel(painel) == {8: (D("175.10"), 3)}


def test_conta_fora_do_painel_aparece_com_o_motivo(mapa):
    _painel, fora = pg.por_conta(_grupos(), mapa)
    motivos = {c.rotulo: c.motivo_fora for c in fora}
    assert motivos["GAMA SPE - BANCO"] == pg.SEM_LINHA
    assert motivos["CONTA DE AJUSTE"] == pg.FORA_POR_CONFIGURACAO


def test_linha_do_painel_marcada_como_fora_do_erp_tem_motivo_proprio(mapa):
    delta = "DELTA LTDA - BANCO"
    grupos = [confirmacao.Grupo(delta, entram=[_ln("entra", "D1", delta, 7.0)], nao_aptos=[])]
    painel, fora = pg.por_conta(grupos, mapa)
    assert painel == {}
    assert [(c.rotulo, c.motivo_fora, c.linha) for c in fora] == [(delta, pg.LINHA_FORA_DO_ERP, None)]
    assert pg.LINHA_FORA_DO_ERP not in (pg.SEM_LINHA, pg.FORA_POR_CONFIGURACAO)
    assert fora[0].a_pagar == D("7.00")        # aparece, nunca some


def test_liberados_e_a_mao_somam_no_a_pagar(mapa):
    painel, _ = pg.por_conta(_grupos(), mapa)
    alfa = painel[8]
    alfa.a_mao.append(pg.Pagamento("M1", "ALFA LTDA - BANCO", "Fulano Ficticio", D("30.00"), "à mão", "ok"))
    assert alfa.a_pagar == D("205.10")


def test_ids_que_nao_saem_sao_so_os_ja_enviados():
    assert pg.ids_que_nao_saem(_grupos()) == {"A2"}


# ------------------------------------------------------------ entrega 2: conferência
from tela_do_dia import conferencia as cf  # noqa: E402


def _conf(eventos=(), a_mao=()):
    return cf.Conferencia.da_nuvem(list(eventos), list(a_mao))


def test_sem_conferencia_e_o_de_antes(mapa):
    a, _ = pg.por_conta(_grupos(), mapa)
    b, _ = pg.por_conta(_grupos(), mapa, None)
    c, _ = pg.por_conta(_grupos(), mapa, _conf())
    assert {k: v.a_pagar for k, v in a.items()} == {k: v.a_pagar for k, v in b.items()}
    assert {k: v.a_pagar for k, v in a.items()} == {k: v.a_pagar for k, v in c.items()}
    assert [p.id for p in a[8].ja_enviados] == [p.id for p in c[8].ja_enviados] == ["A2"]


def test_liberar_desmarcar_e_a_mao_mudam_o_a_pagar(mapa):
    conf = _conf([{"id": 1, "alvo": "A4", "acao": cf.LIBERAR, "motivo": "ok"},
                  {"id": 2, "alvo": "A1", "acao": cf.DESMARCAR},
                  {"id": 3, "alvo": "A2", "acao": cf.LIBERAR, "motivo": "reenviar"}],
                 [{"id": 7, "conta": "ALFA LTDA - BANCO", "valor": "5.00", "descricao": "taxa",
                   "motivo": "combinado"}])
    alfa = pg.por_conta(_grupos(), mapa, conf)[0][8]
    assert [p.id for p in alfa.liberados] == ["A2", "A4"]
    assert [p.id for p in alfa.desmarcados] == ["A1"] and alfa.ja_enviados == []
    assert [p.id for p in alfa.a_mao] == ["mao:7"]
    assert alfa.a_pagar == D("25.00") + D("50.00") + D("9.99") + D("5.00")   # A3 + A2 + A4 + à mão


def test_liberar_o_ja_enviado_nao_conta_em_dobro(mapa):
    """O liberado de já enviado soma UMA vez: sai de `ja_enviados` e entra em `liberados`."""
    antes = pg.por_conta(_grupos(), mapa)[0][8]
    conf = _conf([{"id": 1, "alvo": "A2", "acao": cf.LIBERAR, "motivo": "reenviar"}])
    alfa = pg.por_conta(_grupos(), mapa, conf)[0][8]
    assert alfa.a_pagar == antes.a_pagar            # o dinheiro é o mesmo: só mudou de lista
    assert alfa.qtd_a_pagar == antes.qtd_a_pagar == 3
    assert [p.id for p in alfa.liberados] == ["A2"] and alfa.ja_enviados == []
    assert alfa.liberados[0].origem == "liberado"
    assert "reenviar" in alfa.liberados[0].situacao and "motivo ficticio" in alfa.liberados[0].situacao


def test_desmarcar_o_ja_enviado_nao_tira_do_a_pagar(mapa):
    """O já enviado nem era gerado; desmarcá-lo não o paga nem o tira da conta."""
    antes = pg.por_conta(_grupos(), mapa)[0][8]
    conf = _conf([{"id": 1, "alvo": "A2", "acao": cf.DESMARCAR}])
    alfa = pg.por_conta(_grupos(), mapa, conf)[0][8]
    assert alfa.a_pagar == antes.a_pagar and [p.id for p in alfa.ja_enviados] == ["A2"]


def test_desfazer_volta_ao_de_antes(mapa):
    conf = _conf([{"id": 1, "alvo": "A1", "acao": cf.DESMARCAR},
                  {"id": 2, "alvo": "A1", "acao": cf.DESFAZER}])
    alfa = pg.por_conta(_grupos(), mapa, conf)[0][8]
    assert [p.id for p in alfa.vao_sair] == ["A1", "A3"] and alfa.desmarcados == []


def test_a_mao_em_conta_fora_do_painel_vai_para_fora(mapa):
    conf = _conf(a_mao=[{"id": 2, "conta": "GAMA SPE - BANCO", "valor": "3.00",
                         "descricao": "x", "motivo": "m"}])
    _painel, fora = pg.por_conta(_grupos(), mapa, conf)
    gama = next(c for c in fora if c.rotulo == "GAMA SPE - BANCO")
    assert [p.id for p in gama.a_mao] == ["mao:2"]


def test_editado_leva_nota_e_origem(mapa):
    conf = _conf([{"id": 1, "alvo": "A1", "acao": cf.EDITAR, "motivo": "troca",
                   "campos": {"descricao": "nova"}, "antes": {"descricao": "velha"}}])
    alfa = pg.por_conta(_grupos(), mapa, conf)[0][8]
    a1 = next(p for p in alfa.vao_sair if p.id == "A1")
    assert a1.origem == "editado" and "descricao" in a1.nota


def _cenario(tmp_path):
    from datetime import date
    dia, conta = date(2026, 10, 22), "CONTA EXEMPLO - SICOOB"
    caminho = tmp_path / "mapping.yaml"
    caminho.write_text("model_rows:\n- row: 8\n  label: Conta Exemplo\n  uuid: u\n"
                       f"  erp_name: {conta}\n", encoding="utf-8")
    mapa = AccountMapping.load(caminho)

    def lanc(i):
        return {"id": i, "tradePayableId": f"T-{i}", "paidTo": "Fornecedor Modelo Ltda",
                "remainingValue": 100.0, "plannedDate": "2026-10-22",
                "tradePayableAccount": {"name": conta}, "tradePayablePaymentMethod": "Pix",
                "paidToBankAccount": "PIX EMAIL fulano@exemplo.com", "documentNumber": "1234",
                "costCentreDetails": [{"workName": "OBRA MODELO"}], "paid": False}
    nf = {"filename": "n", "tagName": "Nota Fiscal", "extension": ".pdf",
          "downloadUrl": "https://exemplo.invalid/n.pdf"}
    e = confirmacao.Entradas(selecionados=[lanc("L1"), lanc("L2"), lanc("L3")],
                             anexos={"T-L1": [nf], "T-L3": [nf]}, overviews={}, textos={}, urls_ocr=set(),
                             cadastro_reembolso=None, regras_fornecedor={}, participantes={},
                             periodo=(dia, dia))
    grupos = confirmacao.grupos_da_confirmacao(confirmacao.remontar(e), None, e.selecionados)
    return conta, mapa, e, grupos


def test_a_tela_e_os_arquivos_concordam(tmp_path):
    """O que a tela soma (fora o já enviado) é exatamente o que sai nos arquivos."""
    from tela_do_dia import geracao as ge
    conta, mapa, e, grupos = _cenario(tmp_path)
    conf = _conf([{"id": 1, "alvo": "L2", "acao": cf.LIBERAR, "motivo": "ok"},
                  {"id": 2, "alvo": "L3", "acao": cf.DESMARCAR}],
                 [{"id": 4, "conta": conta, "valor": "30.00", "descricao": "parcela", "motivo": "acordo"}])
    painel, fora = pg.por_conta(grupos, mapa, conf)
    na_tela = {p.id for c in [*painel.values(), *fora] for p in c.saem}
    assert na_tela == ge.chaves_que_saem(ge.resultado_da_tela(e, grupos, conf)) == {"L1", "L2", "mao:4"}


def test_a_pagar_da_tela_e_o_dos_geradores_em_dinheiro(tmp_path):
    """Ponto de dinheiro, em valores e não só em ids. O à mão com link para um
    lançamento do dia NÃO colide com o lançamento (chave `mao:<n>`)."""
    from tela_do_dia import geracao as ge
    from tela_do_dia.valores import de_float
    conta, mapa, e, grupos = _cenario(tmp_path)
    cenarios = [
        _conf(),
        _conf([{"id": 1, "alvo": "L2", "acao": cf.LIBERAR, "motivo": "ok"},
               {"id": 2, "alvo": "L3", "acao": cf.DESMARCAR}]),
        _conf([{"id": 1, "alvo": "L1", "acao": cf.DESMARCAR}],
              [{"id": 4, "conta": conta, "valor": "30.00", "descricao": "parcela", "motivo": "acordo"},
               {"id": 5, "conta": conta, "valor": "40.00", "descricao": "parcial", "motivo": "acordo",
                "lancamento_id": "L1", "valor_em_aberto": "100.00"}]),
        _conf(a_mao=[{"id": 6, "conta": conta, "valor": "40.00", "descricao": "parcial",
                      "motivo": "acordo", "lancamento_id": "L2", "valor_em_aberto": "100.00"}]),
    ]
    for conf in cenarios:
        resultado = ge.resultado_da_tela(e, grupos, conf)
        dos_arquivos = sum((de_float(r["valor"]) for regs in resultado.contas.values() for r in regs),
                           D("0.00"))
        painel, fora = pg.por_conta(grupos, mapa, conf)
        contas = [*painel.values(), *fora]
        assert sum((c.a_pagar - c.valor_ja_enviado for c in contas), D("0.00")) == dos_arquivos
        assert {p.id for c in contas for p in c.saem} == ge.chaves_que_saem(resultado)
        assert sum(len(c.saem) for c in contas) == sum(len(r) for r in resultado.contas.values())


def test_ja_enviado_usa_a_mesma_regra_dos_geradores():
    """Os ids do "já enviado" da tela e os que o gerador tira do `remontar`
    saem da mesma pergunta (`ids_que_nao_saem`); liberar um deles o move de lista."""
    from tela_do_dia import geracao as ge
    grupos = _grupos()
    assert set(ge._ja_enviados(grupos)) == pg.ids_que_nao_saem(grupos) == {"A2"}
