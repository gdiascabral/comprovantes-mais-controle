"""Da tela do dia para a aba Aportes. Cadastro fictício."""
from datetime import date
from decimal import Decimal as D

from aportes.regras import TIPO_INVESTIDOR
from conciliacao.aportadores import Regra
from tela_do_dia import para_aportes as pa

HOJE = date(2026, 10, 21)
ENTIDADES = {
    "MAE - BANCO": {"nome_oficial": "MAE FICTICIA LTDA", "conta": "MAE - BANCO", "nome_descricao": None},
    "FILHA UM - BANCO": {"nome_oficial": "FILHA UM LTDA", "conta": "FILHA UM - BANCO", "nome_descricao": None},
    "SOCIO FICTICIO A": {"nome_oficial": "SOCIO FICTICIO A", "conta": None, "nome_descricao": None},
    "SOCIO FICTICIO B": {"nome_oficial": "SOCIO FICTICIO B", "conta": None, "nome_descricao": None},
    "HOLDING - SUBCONTA 33333-3": {"nome_oficial": "HOLDING FICTICIA", "conta": "HOLDING - SUBCONTA 33.333-3",
                                   "nome_descricao": None},
}
SUBCONTAS = {"33333-3": {"obras": ["OBRA MODELO"], "investidores": ["INVESTIDOR X", "INVESTIDOR Y"],
                         "pesos": {"INVESTIDOR X": 1, "INVESTIDOR Y": 1}}}
REGRAS = [
    Regra("Filha Um - Banco", "Mae - Banco", None, "Aporte", True, linha=5),
    Regra("Mae - Banco", "Socio Ficticio A", None, "Aporte", False, linha=6),
    Regra("Holding - Subconta 33333-3", "INVESTIDOR X", None, "Aporte", False, linha=7),
    Regra("Holding - Subconta 33333-3", "INVESTIDOR Y", None, "Aporte", False, linha=8),
    Regra("Filha Um - Banco", "Desconhecido Ficticio", None, "Aporte", False, linha=9),
    Regra("Mae - Banco", "Socio Ficticio", None, "Aporte", False, linha=10),
]


def _envio(definidos, enviados=None, sem_saldo=()):
    return pa.operacoes(definidos, REGRAS, ENTIDADES, SUBCONTAS, HOJE, enviados=enviados,
                        sem_saldo=sem_saldo)


def test_conta_do_painel_para_conta_do_painel_e_pagamento_mais_recebimento():
    envio = _envio({("Filha Um - Banco", "Mae - Banco"): D("300.00")})
    (op, chaves), = envio.itens
    assert (op.pagador, op.recebedor, op.valor, op.tipo, op.modo) == (
        "MAE - BANCO", "FILHA UM - BANCO", D("300.00"), "Aporte de Capital", "Pagamento + Recebimento")
    assert chaves == [pa.chave_de_envio("Filha Um - Banco", "Mae - Banco")]
    assert envio.valores == {chaves[0]: D("300.00")}
    assert op.validar(ENTIDADES, SUBCONTAS) == []
    assert envio.pendentes == []


def test_chave_de_envio_nao_leva_o_valor():
    assert pa.chave_de_envio("Filha Um - Banco", "Mae - Banco") == "Filha Um - Banco|Mae - Banco"


def test_socio_pessoa_fisica_e_so_recebimento():
    (op, _), = _envio({("Mae - Banco", "Socio Ficticio A"): D("50.00")}).itens
    assert op.modo == "Só recebimento"


def test_nome_que_o_cadastro_nao_tem_vira_pendencia_e_nunca_chute():
    envio = _envio({("Filha Um - Banco", "Desconhecido Ficticio"): D("10.00")})
    assert envio.itens == [] and "não achei" in envio.pendentes[0].motivo


def test_nome_incompleto_nao_casa_com_quem_comeca_igual():
    # "Socio Ficticio" não é "Socio Ficticio A" nem "Socio Ficticio B":
    # nome completo, sem chute pelo começo.
    assert pa.nome_no_cadastro("Socio Ficticio", ENTIDADES) is None
    envio = _envio({("Mae - Banco", "Socio Ficticio"): D("10.00")})
    assert envio.itens == [] and "não achei" in envio.pendentes[0].motivo


def test_nome_no_cadastro_casa_por_nome_completo_ou_numero_da_conta():
    assert pa.nome_no_cadastro("Socio Ficticio A", ENTIDADES) == "SOCIO FICTICIO A"
    assert pa.nome_no_cadastro("mãe - banco", ENTIDADES) == "MAE - BANCO"
    assert pa.nome_no_cadastro("Qualquer Coisa 33.333-3", ENTIDADES) == "HOLDING - SUBCONTA 33333-3"


def test_subconta_de_investidor_vira_uma_operacao_quando_a_divisao_bate():
    envio = _envio({("Holding - Subconta 33333-3", "INVESTIDOR X"): D("500.00"),
                    ("Holding - Subconta 33333-3", "INVESTIDOR Y"): D("500.00")})
    (op, chaves), = envio.itens
    assert (op.pagador, op.recebedor, op.valor, op.tipo, op.modo) == (
        "INVESTIDOR SUBCONTA 33333-3", "HOLDING - SUBCONTA 33333-3", D("1000.00"),
        TIPO_INVESTIDOR, "Só recebimento")
    # Uma operação, UMA chave pelo número da subconta, com o total (A4).
    assert chaves == [pa.chave_da_subconta("33333-3", "Holding - Subconta 33333-3")]
    assert op.validar(ENTIDADES, SUBCONTAS) == []
    assert envio.valores == {chaves[0]: D("1000.00")}


def test_subconta_com_divisao_diferente_do_cadastro_vira_pendencia():
    envio = _envio({("Holding - Subconta 33333-3", "INVESTIDOR X"): D("600.00"),
                    ("Holding - Subconta 33333-3", "INVESTIDOR Y"): D("400.00")})
    assert envio.itens == [] and len(envio.pendentes) == 2
    assert all("divisão" in p.motivo for p in envio.pendentes)


def test_o_que_ja_foi_mandado_nao_vai_de_novo():
    chave = pa.chave_de_envio("Filha Um - Banco", "Mae - Banco")
    envio = _envio({("Filha Um - Banco", "Mae - Banco"): D("300.00")}, enviados={chave: D("300.00")})
    assert envio.itens == [] and envio.pendentes[0].motivo.startswith("já mandado")


def test_valor_corrigido_depois_de_mandado_vira_pendencia_e_nao_segunda_operacao():
    chave = pa.chave_de_envio("Filha Um - Banco", "Mae - Banco")
    envio = _envio({("Filha Um - Banco", "Mae - Banco"): D("350.00")}, enviados={chave: D("300.00")})
    assert envio.itens == []
    (p,) = envio.pendentes
    assert p.valor == D("350.00")
    assert p.motivo.startswith("já mandado R$ 300,00 hoje; agora R$ 350,00")
    assert "aba Aportes" in p.motivo


def _op_na_aba(pagador, recebedor, valor, data=HOJE):
    from aportes.regras import Operacao
    return Operacao(data=data, pagador=pagador, recebedor=recebedor, valor=valor,
                    tipo="Aporte de Capital", modo="Pagamento + Recebimento")


def test_ja_mandado_que_ainda_esta_na_aba_aportes_manda_conferir_la():
    chave = pa.chave_de_envio("Filha Um - Banco", "Mae - Banco")
    na_aba = [_op_na_aba("MAE - BANCO", "FILHA UM - BANCO", D("300.00"))]
    envio = pa.operacoes({("Filha Um - Banco", "Mae - Banco"): D("350.00")}, REGRAS, ENTIDADES,
                         SUBCONTAS, HOJE, enviados={chave: D("300.00")}, na_aba_aportes=na_aba)
    (p,) = envio.pendentes
    assert "confira a aba Aportes" in p.motivo
    assert pa.FORA_DA_ABA not in p.motivo


def test_ja_mandado_que_saiu_da_aba_aportes_manda_conferir_no_erp():
    """App fechado, "Limpar tudo" ou já lançado: a operação não está mais na
    lista, e "confira a aba Aportes" mandaria procurar onde não há nada."""
    chave = pa.chave_de_envio("Filha Um - Banco", "Mae - Banco")
    outra = [_op_na_aba("MAE - BANCO", "FILHA UM - BANCO", D("300.00"), data=date(2026, 10, 20)),
             _op_na_aba("SOCIO FICTICIO A", "MAE - BANCO", D("300.00"))]
    for na_aba in ([], outra):
        envio = pa.operacoes({("Filha Um - Banco", "Mae - Banco"): D("300.00")}, REGRAS, ENTIDADES,
                             SUBCONTAS, HOJE, enviados={chave: D("300.00")}, na_aba_aportes=na_aba)
        (p,) = envio.pendentes
        assert envio.itens == []
        assert p.motivo.startswith("já mandado R$ 300,00 hoje")
        assert pa.FORA_DA_ABA in p.motivo and "confira no ERP" in p.motivo


def test_subconta_ja_mandada_fora_da_aba_aportes_tambem_avisa():
    chave_x = pa.chave_de_envio("Holding - Subconta 33333-3", "INVESTIDOR X")
    envio = pa.operacoes({("Holding - Subconta 33333-3", "INVESTIDOR X"): D("500.00"),
                          ("Holding - Subconta 33333-3", "INVESTIDOR Y"): D("500.00")},
                         REGRAS, ENTIDADES, SUBCONTAS, HOJE, enviados={chave_x: D("500.00")},
                         na_aba_aportes=[])
    assert envio.itens == [] and len(envio.pendentes) == 2
    assert all(pa.FORA_DA_ABA in p.motivo for p in envio.pendentes)
    na_aba = [_op_na_aba("INVESTIDOR SUBCONTA 33333-3", "HOLDING - SUBCONTA 33333-3", D("1000.00"))]
    envio = pa.operacoes({("Holding - Subconta 33333-3", "INVESTIDOR X"): D("500.00"),
                          ("Holding - Subconta 33333-3", "INVESTIDOR Y"): D("500.00")},
                         REGRAS, ENTIDADES, SUBCONTAS, HOJE, enviados={chave_x: D("500.00")},
                         na_aba_aportes=na_aba)
    assert not any(pa.FORA_DA_ABA in p.motivo for p in envio.pendentes)


def test_ainda_na_aba_casa_pagador_recebedor_e_data():
    na_aba = [_op_na_aba("MAE - BANCO", "FILHA UM - BANCO", D("1.00"))]
    assert pa.ainda_na_aba("MAE - BANCO", "FILHA UM - BANCO", HOJE, na_aba) is True
    assert pa.ainda_na_aba("FILHA UM - BANCO", "MAE - BANCO", HOJE, na_aba) is False
    assert pa.ainda_na_aba("MAE - BANCO", "FILHA UM - BANCO", date(2026, 10, 22), na_aba) is False
    assert pa.ainda_na_aba("MAE - BANCO", "FILHA UM - BANCO", HOJE, None) is None
    assert pa.ainda_na_aba(None, "FILHA UM - BANCO", HOJE, na_aba) is None


def test_investidor_ja_mandado_segura_a_subconta_inteira():
    chave_x = pa.chave_de_envio("Holding - Subconta 33333-3", "INVESTIDOR X")
    envio = _envio({("Holding - Subconta 33333-3", "INVESTIDOR X"): D("500.00"),
                    ("Holding - Subconta 33333-3", "INVESTIDOR Y"): D("500.00")},
                   enviados={chave_x: D("500.00")})
    assert envio.itens == [] and len(envio.pendentes) == 2
    assert all(p.motivo.startswith("já mandado") for p in envio.pendentes)


def test_conta_sem_saldo_do_sistema_vai_com_aviso_e_nao_com_pendencia():
    envio = _envio({("Filha Um - Banco", "Mae - Banco"): D("300.00")}, sem_saldo={"Filha Um - Banco"})
    (op, _), = envio.itens
    assert envio.pendentes == []                      # pendência = não foi
    (a,) = envio.avisos                               # aviso = foi, mas confira
    assert a.motivo == pa.MOTIVO_SEM_SALDO and a.destino == "Filha Um - Banco"
    assert envio.sem_saldo == [op] and envio.sem_saldo[0] is op


def test_aportador_sem_saldo_do_sistema_tambem_avisa():
    envio = _envio({("Filha Um - Banco", "Mae - Banco"): D("300.00")}, sem_saldo={"Mae - Banco"})
    assert [p.motivo for p in envio.avisos] == [pa.MOTIVO_SEM_SALDO] and envio.pendentes == []


def test_pendencias_que_bloqueiam_nao_viram_aviso():
    envio = _envio({("Filha Um - Banco", "Desconhecido Ficticio"): D("10.00")})
    assert envio.avisos == [] and len(envio.pendentes) == 1


def _dois():
    envio = _envio({("Filha Um - Banco", "Mae - Banco"): D("300.00"),
                    ("Mae - Banco", "Socio Ficticio A"): D("50.00")})
    (op1, _), (op2, _) = envio.itens
    return envio, op1, op2


CH1 = pa.chave_de_envio("Filha Um - Banco", "Mae - Banco")
CH2 = pa.chave_de_envio("Mae - Banco", "Socio Ficticio A")


def test_marcar_enviados_guarda_o_valor_so_das_aceitas():
    envio, op1, op2 = _dois()
    mandadas = [op1, op2]
    recusadas = pa.operacoes_recusadas(mandadas, [(1, "recusada")])
    enviados = {}
    assert pa.marcar_enviados(envio, mandadas, recusadas, enviados) == [CH1]
    assert enviados == {CH1: D("300.00")}


def test_marcar_enviados_com_item_segurado_pela_tela_nao_desliza():
    envio, op1, op2 = _dois()
    mandadas = [op2]                                  # a tela segurou op1
    enviados = {}
    pa.marcar_enviados(envio, mandadas, pa.operacoes_recusadas(mandadas, []), enviados)
    assert enviados == {CH2: D("50.00")}              # op1 não foi: sem marca
    enviados = {}
    pa.marcar_enviados(envio, mandadas, pa.operacoes_recusadas(mandadas, [(0, "x")]), enviados)
    assert enviados == {}                             # a única mandada foi recusada


def test_marcar_enviados_com_ordem_trocada_marca_certo():
    envio, op1, op2 = _dois()
    mandadas = [op2, op1]
    recusadas = pa.operacoes_recusadas(mandadas, [(0, "recusada")])
    assert recusadas == [op2] and recusadas[0] is op2
    enviados = {}
    pa.marcar_enviados(envio, mandadas, recusadas, enviados)
    assert enviados == {CH1: D("300.00")}


def test_operacao_fora_do_envio_nao_marca_nada():
    envio, _op1, _op2 = _dois()
    _outro, o1, _ = _dois()                          # igual em valor, outro objeto
    enviados = {}
    pa.marcar_enviados(envio, [o1], [], enviados)
    assert enviados == {}


def test_enviados_antes_de_entregar_marcam_todas_as_mandadas_sem_mexer_no_original():
    """A tela grava o registro ANTES de entregar à aba Aportes: se a gravação
    falhar, nada vai; se der certo e a aba recusar algo, desmarca-se depois."""
    envio, op1, op2 = _dois()
    antes = {"Outra|Conta": D("1.00")}
    pre = pa.enviados_apos(antes, envio, [op1, op2], [])
    assert pre == {"Outra|Conta": D("1.00"), CH1: D("300.00"), CH2: D("50.00")}
    assert antes == {"Outra|Conta": D("1.00")}         # o original fica intacto


def test_enviados_depois_da_recusa_voltam_ao_antes_mais_as_aceitas():
    envio, op1, op2 = _dois()
    antes = {"Outra|Conta": D("1.00")}
    pos = pa.enviados_apos(antes, envio, [op1, op2], [op2])
    assert pos == {"Outra|Conta": D("1.00"), CH1: D("300.00")}
