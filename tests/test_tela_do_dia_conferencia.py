"""A conferência editável: eventos dobrados, travas e o casamento do Anexar."""
from decimal import Decimal as D

from pagamentos_dia import confirmacao
from pagamentos_dia.remessa_dia import MOTIVO_SEM_DOCUMENTO
from tela_do_dia import conferencia as cf
from tela_do_dia.lancamento_do_erp import LancamentoLido

LINHA_BANCARIA = "34191.57007 00024.924375 24177.010006 9 15340000115000"   # a de tests/test_remessa_dia.py


def _ev(i, alvo, acao, **k):
    return cf.Evento.de_linha({"id": i, "alvo": alvo, "conta": "C", "acao": acao, **k})


def test_a_ultima_palavra_vale_e_desfazer_volta_ao_erp():
    d = cf.dobrar([_ev(1, "L1", cf.LIBERAR, motivo="pago hoje"),
                   _ev(2, "L1", cf.DESMARCAR)])
    assert d["L1"].desmarcado and not d["L1"].liberado
    d = cf.dobrar([_ev(3, "L1", cf.DESFAZER), _ev(1, "L1", cf.LIBERAR, motivo="pago hoje")])
    assert "L1" not in d                                    # ordem é pelo id, não pela lista


def test_acao_desconhecida_nao_decide_nada():
    d = cf.dobrar([_ev(1, "L1", "acao_do_app_mais_novo", motivo="x")])
    assert d == {}


def test_quem_e_quando_vem_do_servidor():
    d = cf.dobrar([_ev(1, "L1", cf.LIBERAR, motivo="pago hoje", quem_nome="Fulano Ficticio",
                       quando="2026-10-22T10:00:00")])["L1"]
    assert d.liberado and d.motivo_liberacao == "pago hoje"
    assert (d.quem_nome, d.quando, d.conta) == ("Fulano Ficticio", "2026-10-22T10:00:00", "C")


def test_edicao_acumula_e_guarda_o_primeiro_original():
    d = cf.dobrar([_ev(1, "L1", cf.EDITAR, campos={"descricao": "A"}, antes={"descricao": "orig"}, motivo="erro do ERP"),
                   _ev(2, "L1", cf.EDITAR, campos={"descricao": "B"}, antes={"descricao": "A"}, motivo="de novo",
                       corrigir_no_erp=True)])["L1"]
    assert d.edicoes == {"descricao": "B"} and d.antes == {"descricao": "orig"} and d.corrigir_no_erp
    assert d.editado and d.motivo_edicao == "de novo"


def test_edicao_ignora_campo_que_nao_se_edita():
    d = cf.dobrar([_ev(1, "L1", cf.EDITAR, campos={"valor": "1.00", "descricao": "OBRA"},
                       motivo="erro do ERP")])["L1"]
    assert d.edicoes == {"descricao": "OBRA"}


def test_a_mao_removida_some_da_conferencia():
    conf = cf.Conferencia.da_nuvem(
        [{"id": 9, "alvo": "mao:5", "acao": cf.REMOVER_A_MAO, "motivo": "lancei errado"}],
        [{"id": 5, "conta": "C", "valor": "30.00", "descricao": "parcela", "motivo": "combinado"},
         {"id": 6, "conta": "C", "valor": "10.00", "descricao": "taxa", "motivo": "combinado"}])
    assert [p.id for p in conf.a_mao] == [6] and conf.a_mao[0].valor == D("10.00")
    assert conf.a_mao[0].alvo == "mao:6" and conf.a_mao[0].valor_em_aberto is None


def test_conferencia_acrescenta_sem_mudar_a_anterior():
    vazia = cf.Conferencia()
    com = vazia.com_evento({"id": 1, "alvo": "L1", "conta": "C", "acao": cf.DESMARCAR})
    com = com.com_a_mao({"id": 2, "conta": "C", "valor": "5.00", "descricao": "taxa",
                         "motivo": "combinado", "valor_em_aberto": "8.00"})
    assert vazia.decisoes == {} and vazia.a_mao == []
    assert com.decisoes["L1"].desmarcado and com.a_mao[0].valor_em_aberto == D("8.00")


class _Enviado:
    ja_enviado = "remessa nº 000007 de 20/10"


def _linha(secao, situacao="", candidato=None, envio_rejeitado=False):
    return confirmacao.Linha(secao=secao, id="L1", conta="C", valor=10.0, favorecido="F", tipo="Pix",
                             dados="", por_onde="", vencimento=None, oc="", centro_custo="",
                             descricao="", situacao=situacao, estado="ok", olhar=False, candidato=candidato,
                             envio_rejeitado=envio_rejeitado)


def test_ja_enviado_e_fora_dos_contatos_pedem_certeza():
    assert "JÁ SAIU" in cf.pede_certeza(_linha("entra", candidato=_Enviado()))
    assert "Contatos" in cf.pede_certeza(_linha("entra", "pix · o favorecido não está no cadastro de Contatos do ERP, …"))
    assert "Contatos" in cf.pede_certeza(_linha("nao_apto", MOTIVO_SEM_DOCUMENTO))   # o texto real da Remessa
    assert cf.pede_certeza(_linha("nao_apto", "sem anexo — sem anexo, sem pagamento")) == ""
    assert cf.pode_liberar(_linha("nao_apto")) and cf.pode_liberar(_linha("entra", candidato=_Enviado()))
    assert not cf.pode_liberar(_linha("entra"))


def test_envio_rejeitado_ja_sai_e_nao_pede_certeza():
    rejeitado = _linha("entra", candidato=_Enviado(), envio_rejeitado=True)
    assert not cf.pode_liberar(rejeitado)                   # nasce marcado: já vai sair
    assert cf.pede_certeza(rejeitado) == ""


def test_motivo_curto_e_com_teto_do_banco():
    assert cf.validar_motivo("ok") != "" and cf.validar_motivo("   ") != ""
    assert cf.validar_motivo("pago hoje") == ""
    assert "200" in cf.validar_motivo("x" * 201)
    assert cf.validar_motivo("x" * 200) == ""


def test_edicao_de_forma_exige_chave_com_tipo_ou_linha_que_fecha():
    assert cf.validar_edicao({"tipo": "Pix", "dados": "PIX EMAIL fulano@exemplo.com"}, "erro do ERP") == ""
    assert "tipo" in cf.validar_edicao({"tipo": "Pix", "dados": "62999999999"}, "erro do ERP")
    assert cf.validar_edicao({"tipo": "Pix", "dados": "PIX CELULAR 62999999999"}, "erro do ERP") == ""
    assert cf.validar_edicao({"tipo": "Boleto", "dados": LINHA_BANCARIA}, "boleto novo") == ""
    assert "dígitos" in cf.validar_edicao({"tipo": "Boleto", "dados": "123"}, "boleto novo")
    assert "motivo" in cf.validar_edicao({"descricao": "OBRA MODELO 1234"}, "")
    assert "CPF" in cf.validar_edicao({"reembolso_nome": "Fulano Ficticio",
                                       "reembolso_documento": "11111111111"}, "reembolso")


def test_edicao_recusa_o_que_o_banco_recusaria():
    assert "junto" in cf.validar_edicao({"tipo": "Pix"}, "erro do ERP")
    assert "500" in cf.validar_edicao({"tipo": "Transferência", "dados": "BANCO " + "1" * 500}, "erro do ERP")
    assert "=" in cf.validar_edicao({"descricao": "=HYPERLINK(1)"}, "erro do ERP")
    assert "200" in cf.validar_edicao({"descricao": "x" * 201}, "erro do ERP")
    assert "200" in cf.validar_edicao({"reembolso_nome": "x" * 201,
                                       "reembolso_documento": "52998224725"}, "reembolso")
    assert "Nada" in cf.validar_edicao({}, "erro do ERP")
    assert "valor" in cf.validar_edicao({"valor": "1"}, "erro do ERP")
    assert "copia-e-cola" in cf.validar_edicao(
        {"tipo": "Pix", "dados": "00020126580014br.gov.bcb.pix0136123e4567-e12b-12d1-a456-4266554400005204000053039865802BR"
                                 "5913FULANO FICTIC6008BRASILIA62070503***63041D3D"}, "erro do ERP")


def test_aviso_de_casamento_diz_o_que_o_anexar_vai_perder():
    reg = {"centro_custo": "OBRA MODELO QD 1", "nf": "1234", "valor": 10.0}
    assert cf.aviso_de_casamento({**reg, "descricao_editada": "OBRA MODELO QD 1 COMPRA 1234"}, "C") == ""
    aviso = cf.aviso_de_casamento({**reg, "descricao_editada": "COMPRA DE MATERIAL"}, "C")
    assert "centro de custo" in aviso and "número do documento" in aviso


def test_aviso_de_casamento_aceita_documento_rotulado_e_sem_documento():
    reg = {"centro_custo": "OBRA MODELO QD 1", "nf": "1234", "valor": 10.0}
    assert cf.aviso_de_casamento({**reg, "descricao_editada": "OBRA MODELO QD 1 NF 1234 OC 55"}, "C") == ""
    assert cf.aviso_de_casamento({"centro_custo": "OBRA MODELO", "valor": 10.0,
                                  "descricao_editada": "OBRA MODELO COMPRA"}, "C") == ""


def test_a_mao_com_link_nao_paga_mais_que_o_em_aberto_nem_titulo_pago():
    lido = LancamentoLido(id="L9", conta="C", favorecido="Fornecedor Modelo Ltda",
                          centro_custo="OBRA MODELO", nf="1234", em_aberto=D("80000.00"))
    linha, erro = cf.nova_a_mao(conta="C", valor_texto="30.000,00", descricao="parcela",
                                motivo="combinado", contas={"C"}, lido=lido)
    assert erro == "" and linha["lancamento_id"] == "L9" and linha["valor"] == "30000.00"
    assert linha["valor_em_aberto"] == "80000.00" and linha["favorecido"] == "Fornecedor Modelo Ltda"
    _l, erro = cf.nova_a_mao(conta="C", valor_texto="90.000,00", descricao="parcela",
                             motivo="combinado", contas={"C"}, lido=lido)
    assert "em aberto" in erro
    _l, erro = cf.nova_a_mao(conta="C", valor_texto="10,00", descricao="parcela", motivo="combinado",
                             contas={"C"}, lido=LancamentoLido(id="L9", conta="C", pago=True))
    assert "PAGO" in erro
    _l, erro = cf.nova_a_mao(conta="C", valor_texto="10,00", descricao="parcela", motivo="combinado",
                             contas={"C", "D"}, lido=LancamentoLido(id="L9", conta="D"))
    assert "conta D" in erro


def test_a_mao_sem_link_recusa_o_que_nao_fecha():
    def nova(**k):
        base = dict(conta="C", valor_texto="10,00", descricao="parcela", motivo="combinado", contas={"C"})
        return cf.nova_a_mao(**{**base, **k})
    linha, erro = nova()
    assert erro == "" and linha["valor"] == "10.00" and "lancamento_id" not in linha
    assert "conta" in nova(conta="X")[1]
    assert "zero" in nova(valor_texto="0,00")[1] and "zero" in nova(valor_texto="-5,00")[1]
    assert "ambíguo" in nova(valor_texto="1500.50")[1]
    assert "descrição" in nova(descricao="ab")[1] and "descrição" in nova(descricao="=1+1")[1]
    assert "motivo" in nova(motivo="")[1].lower()
    assert "tipo" in nova(tipo="Pix", dados="62999999999")[1]
    assert nova(tipo="Pix", dados="PIX EMAIL fulano@exemplo.com")[1] == ""
    assert "200" in nova(favorecido="x" * 201)[1]


# ---------------------------------------------------------------- conserto 1
def test_pix_de_onze_digitos_sem_tipo_e_recusado_mesmo_com_rotulo_generico():
    assert "tipo" in cf.validar_edicao({"tipo": "Pix", "dados": "PIX 62999999999"}, "erro do ERP")
    assert "tipo" in cf.validar_edicao({"tipo": "Pix", "dados": "chave: 52998224725"}, "erro do ERP")
    assert cf.validar_edicao({"tipo": "Pix", "dados": "(62) 99999-9999"}, "erro do ERP") == ""
    assert cf.validar_edicao({"tipo": "Pix", "dados": "529.982.247-25"}, "erro do ERP") == ""


def test_pix_cpf_ou_cnpj_declarado_confere_o_dv():
    assert cf.validar_edicao({"tipo": "Pix", "dados": "PIX CPF 52998224725"}, "erro do ERP") == ""
    assert "verificador" in cf.validar_edicao({"tipo": "Pix", "dados": "PIX CPF 52998224726"}, "erro do ERP")
    assert "verificador" in cf.validar_edicao({"tipo": "Pix", "dados": "PIX CNPJ 11.222.333/0001-80"},
                                              "erro do ERP")
    assert cf.validar_edicao({"tipo": "Pix", "dados": "PIX CNPJ 11.222.333/0001-81"}, "erro do ERP") == ""


def _a_mao(i, valor, lancamento_id="L9"):
    return cf.PagamentoAMao(id=i, conta="C", valor=D(valor), descricao="parcela", motivo="combinado",
                            lancamento_id=lancamento_id)


def test_a_mao_soma_as_outras_do_mesmo_lancamento_e_pergunta_se_ja_esta_no_dia():
    lido = LancamentoLido(id="L9", conta="C", em_aberto=D("100.00"))
    base = dict(conta="C", descricao="parcela", motivo="combinado", contas={"C"}, lido=lido)
    _l, erro = cf.nova_a_mao(valor_texto="50,00", a_mao_existentes=[_a_mao(1, "60.00")], **base)
    assert "já está à mão" in erro and "em aberto" in erro
    linha, erro = cf.nova_a_mao(valor_texto="40,00", **base,
                                a_mao_existentes=[_a_mao(1, "60.00"), _a_mao(2, "99.00", "L8")])
    assert erro == "" and "pergunta" not in linha
    linha, erro = cf.nova_a_mao(valor_texto="40,00", ids_do_dia={"L9", "L1"}, **base)
    assert erro == "" and "JÁ ESTÁ na lista do dia" in linha["pergunta"] and "Tem certeza" in linha["pergunta"]


def test_a_mao_com_em_aberto_desconhecido_pergunta():
    linha, erro = cf.nova_a_mao(conta="C", valor_texto="40,00", descricao="parcela", motivo="combinado",
                                contas={"C"}, lido=LancamentoLido(id="L9", conta="C"))
    assert erro == "" and "em aberto" in linha["pergunta"] and linha["valor_em_aberto"] is None


def test_aviso_de_casamento_usa_a_regua_do_nome_do_anexar():
    reg = {"centro_custo": "OBRA MODELO QD 1", "nf": "1234", "valor": 10.0}
    aviso = cf.aviso_de_casamento({**reg, "descricao_editada": "OBRA MODELO QD 1 NFS 1234"}, "C")
    assert "número do documento" in aviso and "centro de custo não está" not in aviso
    assert cf.aviso_de_casamento({**reg, "descricao_editada": "OBRA MODELO QD 1 NF 01234"}, "C") == ""


# ---------------------------------------------------------------- conserto (T5)
def test_a_mao_na_conta_pf_e_recusado():
    """Ruling: a PESSOA FISICA - APENAS LANÇAMENTO é paga pelo celular; o HTML
    geral não a mostra, e o à mão sairia na tela e em lugar nenhum para pagar."""
    pf = "PESSOA FISICA - APENAS LANÇAMENTO"
    linha, erro = cf.nova_a_mao(conta=pf, valor_texto="10,00", descricao="parcela",
                                motivo="combinado", contas={pf, "C"})
    assert linha is None and "PESSOA FISICA" in erro and "celular" in erro
    assert cf.nova_a_mao(conta="C", valor_texto="10,00", descricao="parcela",
                         motivo="combinado", contas={pf, "C"})[1] == ""
