"""Passo 2 editável: as regras da tela, sem janela. Dados fictícios."""
import datetime as dt
from decimal import Decimal as D
from types import SimpleNamespace as NS

import pytest

from pagamentos_dia import confirmacao
from tela_do_dia import conferencia as cf
from tela_do_dia import passo2 as p2
from tela_do_dia.pagamentos import PagamentosDaConta, Pagamento

DIA = dt.date(2026, 10, 22)
PIX_OK = "PIX EMAIL fulano@exemplo.com"
CPF_OK = "52998224725"


def _pag(ident, valor="10.00", origem="", nota="", situacao="motivo ficticio"):
    return Pagamento(id=ident, conta_erp="CONTA EXEMPLO - SICOOB", favorecido=f"Fornecedor {ident}",
                     valor=D(valor), situacao=situacao, estado="ok", origem=origem, nota=nota)


def _ln(secao, ident="L1", situacao="", candidato=None, rejeitado=False, conta="CONTA EXEMPLO - SICOOB"):
    return confirmacao.Linha(secao=secao, id=ident, conta=conta, valor=10.0,
                             favorecido="Fornecedor Modelo Ltda", tipo="Pix", dados="",
                             por_onde="", vencimento=None, oc="", centro_custo="",
                             descricao="", situacao=situacao, estado="ok", olhar=False,
                             candidato=candidato, envio_rejeitado=rejeitado)


# ------------------------------------------------------------- tabela
def test_iid_aguenta_o_mesmo_id_em_varias_linhas():
    """Lançamento dividido (entrega 5): N linhas com o mesmo id. O Treeview
    recusa iid repetido. Desde a tarefa 3b da entrega 5 o iid é a chave
    (id, parte_linha) — estável entre recálculos — e a chave igual ganha
    "#2", "#3"… (antes era por posição: "vai|3.0")."""
    conta = PagamentosDaConta("Conta Alfa - Banco", 8, vao_sair=[_pag("L1"), _pag("L1")],
                              bloqueados=[_pag("L1")])
    linhas = p2.linhas_da_conta(conta, 3)
    assert len({ln.iid for ln in linhas}) == 3
    assert [ln.iid for ln in linhas] == ["L1|", "L1|#2", "L1|#3"]


def test_ordem_valores_e_cores_de_cada_tipo():
    conta = PagamentosDaConta(
        "Conta Alfa - Banco", 8,
        vao_sair=[_pag("V1"), _pag("V2", origem="editado", nota="editado: descricao")],
        liberados=[_pag("B1", origem="liberado")], a_mao=[_pag("mao:1", origem="a_mao")],
        ja_enviados=[_pag("E1")], desmarcados=[_pag("D1")], bloqueados=[_pag("X1")])
    linhas = p2.linhas_da_conta(conta, 0)
    assert [ln.tipo for ln in linhas] == ["vai", "vai", "lib", "mao", "env", "desm", "bloq"]
    por = {ln.pagamento.id: ln for ln in linhas}
    assert por["V1"].valores == ("vai sair", "R$ 10,00", "", "motivo ficticio") and por["V1"].tags == ()
    assert por["V2"].tags == ("atencao",) and "editado: descricao" in por["V2"].valores[3]
    assert por["B1"].valores[0] == "liberado" and por["B1"].tags == ("atencao",)
    assert por["mao:1"].valores[0] == "à mão"
    assert por["E1"].valores[0] == "já enviado"
    assert por["D1"].valores[:3] == ("", "", "desmarcado · R$ 10,00") and por["D1"].tags == ("erro",)
    assert por["X1"].valores[2] == "bloqueado · R$ 10,00"


def test_a_mao_so_se_remove_e_ja_enviado_so_se_libera():
    assert p2.acoes_da_linha("mao", False) == {p2.A_REMOVER}
    assert p2.acoes_da_linha("mao", True) == {p2.A_REMOVER}
    assert p2.acoes_da_linha("env", False) == {p2.A_LIBERAR}
    assert p2.acoes_da_linha("vai", False) == {p2.A_DESMARCAR, p2.A_EDITAR}
    assert p2.A_DESFAZER in p2.acoes_da_linha("vai", True)        # vai editado
    assert p2.acoes_da_linha("desm", True) == {p2.A_DESFAZER}
    assert p2.A_DESFAZER not in p2.acoes_da_linha("bloq", False)


# ------------------------------------------------------ travas da nuvem
def test_nuvem_travada_e_gravacao_em_curso_recusam_gravar():
    assert "busque de novo" in p2.recusa_de_gravar("não li a nuvem (x)", False)
    assert "não li a nuvem" in p2.recusa_de_gravar("não li a nuvem (x)", True)
    assert p2.recusa_de_gravar("", True) == "Espere a gravação anterior terminar."
    assert p2.recusa_de_gravar("", False) == ""
    assert p2.botoes_ligados(True, "", False)
    assert not p2.botoes_ligados(True, "ainda não li a nuvem", False)
    assert not p2.botoes_ligados(True, "", True)
    assert not p2.botoes_ligados(False, "", False)


# ------------------------------------------------------------ liberar
def test_liberar_bloqueado_sim_vai_sair_nao_e_parte_nunca():
    assert p2.pode_liberar(_ln(confirmacao.NAO_APTO))
    assert not p2.pode_liberar(_ln(confirmacao.ENTRA))               # já vai sair
    assert p2.pode_liberar(_ln(confirmacao.ENTRA, candidato=NS(ja_enviado="remessa nº 7")))
    parte = _ln(confirmacao.NAO_APTO)
    parte.parte = "1/2"                    # atributo que a entrega 5 traz
    assert not p2.pode_liberar(parte)
    assert not p2.pode_liberar(None)


def test_ja_enviado_e_fora_dos_contatos_pedem_tem_certeza():
    enviado = _ln(confirmacao.ENTRA, candidato=NS(ja_enviado="remessa nº 7"))
    assert "JÁ SAIU" in p2.certeza_ao_liberar(enviado)
    assert p2.certeza_ao_liberar(enviado).endswith("Tem certeza?")
    fora = _ln(confirmacao.NAO_APTO, situacao="o favorecido não está no cadastro de Contatos do ERP")
    assert p2.certeza_ao_liberar(fora).endswith("Tem certeza?")
    assert p2.certeza_ao_liberar(_ln(confirmacao.NAO_APTO, situacao="sem anexo")) == ""


def test_ids_do_dia_e_linha_do_id():
    g = [confirmacao.Grupo("C1", entram=[_ln("entra", "A", conta="C1")],
                           nao_aptos=[_ln("nao_apto", "B", conta="C1")]),
         confirmacao.Grupo("C2", entram=[_ln("entra", "A", conta="C2")], nao_aptos=[])]
    assert p2.ids_do_dia(g) == {"A", "B"}
    assert p2.linha_do_id(g, "A", "C2").conta == "C2"
    assert p2.linha_do_id(g, "B").id == "B"
    assert p2.linha_do_id(g, "Z") is None


def test_conta_pf_nao_aparece_para_pagamento_a_mao():
    mapa = NS(resolve_label=lambda n: n != "SEM LINHA")
    contas = [NS(name="CONTA EXEMPLO - SICOOB"), NS(name="SEM LINHA"),
              NS(name="PESSOA FISICA - APENAS LANÇAMENTO")]
    grupos = [NS(conta="Conta Alfa - Banco")]
    assert p2.contas_para_a_mao(contas, mapa, grupos) == ["CONTA EXEMPLO - SICOOB", "Conta Alfa - Banco"]


# ------------------------------------------------------------- editar
INI = {"tipo": "Pix", "dados": "PIX EMAIL fornecedor@exemplo.com", "reembolso_nome": "",
       "reembolso_documento": "", "descricao": "OBRA MODELO NF 123"}


def test_so_o_que_mudou_vai_para_a_nuvem():
    assert p2.campos_da_edicao(INI, dict(INI)) == {}
    assert p2.campos_da_edicao(INI, {**INI, "descricao": "OBRA MODELO NF 124"}) == {
        "descricao": "OBRA MODELO NF 124"}
    # forma de pagar muda inteira
    assert p2.campos_da_edicao(INI, {**INI, "dados": PIX_OK}) == {"tipo": "Pix", "dados": PIX_OK}


def test_reembolso_leva_a_forma_de_pagar_junto():
    campos = p2.campos_da_edicao(INI, {**INI, "reembolso_nome": "Fulano Ficticio",
                                       "reembolso_documento": CPF_OK})
    assert set(campos) == {"tipo", "dados", "reembolso_nome", "reembolso_documento"}


def test_reembolso_sem_tipo_ou_dado_e_recusado():
    """Decisão (b): o dado do reembolso só grava com tipo + dado."""
    reg = {"tipo": "Pix", "dados": "PIX EMAIL fornecedor@exemplo.com"}
    so_reembolso = {"reembolso_nome": "Fulano Ficticio", "reembolso_documento": CPF_OK}
    assert "tipo" in p2.validar_edicao_da_tela(reg, so_reembolso, "reembolso do sócio")
    sem_dado = {**so_reembolso, "tipo": "Pix", "dados": ""}
    assert p2.validar_edicao_da_tela(reg, sem_dado, "reembolso do sócio") != ""


def test_reembolso_com_a_chave_do_fornecedor_e_recusado():
    reg = {"tipo": "Pix", "dados": "PIX EMAIL fornecedor@exemplo.com"}
    campos = {"reembolso_nome": "Fulano Ficticio", "reembolso_documento": CPF_OK,
              "tipo": "Pix", "dados": "PIX EMAIL fornecedor@exemplo.com"}
    assert "DELA" in p2.validar_edicao_da_tela(reg, campos, "reembolso do sócio")
    campos["dados"] = PIX_OK
    assert p2.validar_edicao_da_tela(reg, campos, "reembolso do sócio") == ""


def test_parte_de_lancamento_dividido_nao_muda_a_forma_de_pagar():
    reg = {"tipo": "Boleto", "dados": "x", "parte": "1/2"}
    erro = p2.validar_edicao_da_tela(reg, {"tipo": "Pix", "dados": PIX_OK}, "erro do ERP")
    assert "partes" in erro
    assert p2.validar_edicao_da_tela(reg, {"descricao": "OBRA MODELO NF 9"}, "erro do ERP") == ""


def test_edicao_herda_as_validacoes_da_conferencia():
    assert p2.validar_edicao_da_tela({}, {"descricao": "OBRA MODELO"}, "") != ""   # sem motivo
    assert p2.validar_edicao_da_tela({}, {}, "motivo ok") == "Nada mudou."


def test_antes_guarda_o_que_estava_na_tela():
    assert p2.antes_da_edicao(INI, {"descricao": "x"}) == {"descricao": "OBRA MODELO NF 123"}


# ----------------------------------------------------- gravar e reler
class _Nuvem:
    def __init__(self, *, falha_gravar=None, falha_ler=None):
        self.decisoes, self.a_mao = [], []
        self.falha_gravar, self.falha_ler = falha_gravar, falha_ler

    def registrar_decisao(self, dia, **kw):
        if self.falha_gravar:
            raise self.falha_gravar
        linha = {"id": len(self.decisoes) + 1, **kw, "quem_nome": "Fulano"}
        self.decisoes.append(linha)
        return linha

    def decisoes_do_dia(self, dia):
        if self.falha_ler:
            raise self.falha_ler
        return list(self.decisoes)

    def pagamentos_a_mao(self, dia):
        return list(self.a_mao)


def _liberar(c):
    return c.registrar_decisao(DIA, alvo="L1", conta="C", acao=cf.LIBERAR, motivo="ok do dono")


def test_depois_de_gravar_a_tela_rele_a_nuvem():
    nuvem = _Nuvem()
    nuvem.decisoes.append({"id": 1, "alvo": "OUTRA", "conta": "C", "acao": cf.DESMARCAR})
    g = p2.gravar_e_reler(nuvem, DIA, _liberar)
    assert g.erro == "" and g.travar == ""
    # vem da RELEITURA: inclui o que outra máquina gravou antes
    assert set(g.conferencia.decisoes) == {"OUTRA", "L1"}
    assert g.gravado["alvo"] == "L1"


def test_erro_ao_gravar_vira_recado_e_a_tela_rele_mesmo_assim():
    nuvem = _Nuvem(falha_gravar=RuntimeError("recusado"))
    g = p2.gravar_e_reler(nuvem, DIA, _liberar, recado=lambda e: f"Não gravei: {e}")
    assert g.erro.startswith("Não gravei: recusado")
    assert g.erro.endswith(p2.CONFIRA_DEPOIS_DO_ERRO)          # M1: pode ter gravado
    assert "Pode ter gravado ou não" in g.erro
    assert g.conferencia is not None and g.conferencia.decisoes == {}
    assert g.travar == ""


def test_releitura_que_falha_trava_a_tela():
    nuvem = _Nuvem(falha_ler=OSError("rede caiu"))
    g = p2.gravar_e_reler(nuvem, DIA, _liberar)
    assert g.conferencia is None
    assert "busque de novo" in g.travar and "rede caiu" in g.travar


def test_sem_sessao_nao_grava_e_trava():
    g = p2.gravar_e_reler(None, DIA, _liberar)
    assert g.conferencia is None and g.travar and g.erro


# --------------------------------------------------------------- data
def test_ler_data():
    assert p2.ler_data("23/10/2026") == dt.date(2026, 10, 23)
    assert p2.ler_data(" 1/2/27 ") == dt.date(2027, 2, 1)
    with pytest.raises(ValueError):
        p2.ler_data("2026-10-23")
    with pytest.raises(ValueError):
        p2.ler_data("31/02/2026")


def test_link_sem_ler_ou_trocado_depois_de_lido_e_recusado():
    lido = NS(id="abc-1")
    assert p2.recado_do_link("", None, "") == ""
    assert "Ler o lançamento" in p2.recado_do_link("abc-1", None, "abc-1")
    assert "mudou" in p2.recado_do_link("abc-2", lido, "abc-2")
    assert p2.recado_do_link("abc-1", lido, "abc-1") == ""


# --------------------------------------------- conserto da rodada 1
def test_gravando_desliga_tudo_ate_o_buscar():
    """I1: no meio da gravação nada gera, nada manda aportes, ninguém busca."""
    b = p2.botoes(tem_leitura=True, gravando=True, travada="", sem_geradores=False)
    assert b == p2.Botoes(dia=False, geradores=False, passo2=False, buscar=False)


def test_botoes_sem_leitura_sem_apuracao_e_com_nuvem_travada():
    assert p2.botoes(tem_leitura=False, gravando=False, travada=p2.SEM_NUVEM,
                     sem_geradores=False) == p2.Botoes(False, False, False, True)
    assert p2.botoes(tem_leitura=True, gravando=False, travada="",
                     sem_geradores=True) == p2.Botoes(True, False, True, True)
    assert p2.botoes(tem_leitura=True, gravando=False, travada="não li a nuvem (x)",
                     sem_geradores=False) == p2.Botoes(True, True, False, True)
    assert p2.botoes(tem_leitura=True, gravando=False, travada="",
                     sem_geradores=False) == p2.Botoes(True, True, True, True)


def test_nuvem_com_erro_pergunta_antes_de_gerar():
    """I3: só a nuvem que FALHOU pergunta; a ainda não lida não chega a gerar."""
    assert p2.pergunta_ao_gerar("não li a nuvem (timeout)") == p2.PERGUNTA_SEM_NUVEM
    assert "NÃO estão aplicadas" in p2.PERGUNTA_SEM_NUVEM
    assert p2.PERGUNTA_SEM_NUVEM.endswith("Gerar mesmo assim?")
    assert p2.pergunta_ao_gerar("") == ""
    assert p2.pergunta_ao_gerar(p2.SEM_NUVEM) == ""


def test_selecao_sem_id_e_recusada():
    """M3: decisão para alvo vazio não vai à nuvem."""
    sem_id = p2.LinhaDaTabela("vai|0.0", "vai", _pag(""), "", (), ())
    assert "número do lançamento" in p2.recusa_da_selecao(sem_id, p2.A_DESMARCAR, False, "x")
    com_id = p2.LinhaDaTabela("vai|0.0", "vai", _pag("L1"), "", (), ())
    assert p2.recusa_da_selecao(com_id, p2.A_DESMARCAR, False, "x") == ""
    assert p2.recusa_da_selecao(com_id, p2.A_LIBERAR, False, "selecione") == "selecione"
    assert p2.recusa_da_selecao(None, p2.A_EDITAR, False, "selecione") == "selecione"


REG_ERP = {"tipo": "Pix", "dados": "PIX EMAIL fornecedor@exemplo.com", "descricao": "OBRA MODELO NF 123",
           "descricao_editada": "OBRA MODELO NF 123", "valor": 10.0}


def test_editar_abre_com_a_decisao_aplicada_e_volta_ao_erp():
    """I2: o diálogo mostra o que vale (ERP + edição gravada); digitar o valor
    do ERP de volta grava; o `antes` continua o do ERP."""
    conta = "CONTA EXEMPLO - SICOOB"
    d = cf.Decisao("L1", edicoes={"descricao": "OBRA MODELO NF 124", "tipo": "Pix", "dados": PIX_OK})
    erp = p2.valores_iniciais(REG_ERP, conta)
    mostrados = p2.valores_para_editar(REG_ERP, conta, d)
    assert mostrados["descricao"] == "OBRA MODELO NF 124" and mostrados["dados"] == PIX_OK
    assert p2.campos_da_edicao(mostrados, dict(mostrados)) == {}      # nada mudou
    de_volta = {**mostrados, "descricao": erp["descricao"]}
    campos = p2.campos_da_edicao(mostrados, de_volta)
    assert campos == {"descricao": erp["descricao"]}
    assert p2.antes_da_edicao(erp, campos) == {"descricao": erp["descricao"]}
    assert p2.valores_para_editar(REG_ERP, conta, None) == erp


def test_tirar_o_reembolso_e_pelo_desfazer():
    campos = {"reembolso_nome": "", "reembolso_documento": "", "tipo": "Pix", "dados": PIX_OK}
    assert "Desfazer" in p2.validar_edicao_da_tela({"reembolso": True}, campos, "engano")
