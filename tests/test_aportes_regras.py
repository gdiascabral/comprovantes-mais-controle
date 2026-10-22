# -*- coding: utf-8 -*-
"""Regras de aporte e distribuição — o módulo que ESCREVE valores no ERP.

Nada aqui toca navegador: `expandir` só transforma uma operação na lista de
lançamentos a criar. Nenhum dado real — nomes e contas são inventados.
"""
import datetime
from decimal import Decimal

import pytest

from aportes import regras
from aportes.regras import Operacao, como_dinheiro, dividir_em_centavos, expandir

HOJE = datetime.date(2026, 8, 11)

ENTIDADES = {
    "EMPRESA A": {"nome_oficial": "EMPRESA A LTDA", "conta": "EMPRESA A - BANCO",
                  "nome_descricao": None},
    "EMPRESA B": {"nome_oficial": "EMPRESA B LTDA", "conta": "EMPRESA B - BANCO",
                  "nome_descricao": None},
    "SUBCONTA 111-1": {"nome_oficial": "EMPRESA C LTDA",
                       "conta": "EMPRESA C - SUBCONTA 111-1",
                       "nome_descricao": None},
    "PESSOA FISICA": {"nome_oficial": "FULANO DE TAL", "conta": None,
                      "nome_descricao": None},
}
SUBCONTAS = {
    "111-1": {"obras": ["OBRA 1", "OBRA 2"],
              "investidores": ["INVESTIDOR X", "INVESTIDOR Y"]},
    "_obra_padrao": "CONTROLE DE APORTES",
}


def op(**kw):
    base = dict(data=HOJE, pagador="EMPRESA A", recebedor="EMPRESA B",
                valor=como_dinheiro("1000.00"), tipo="Aporte de Capital",
                modo="Pagamento + Recebimento", forma="Pix")
    base.update(kw)
    return Operacao(**base)


# ------------------------------------------------------------------ dinheiro
def test_como_dinheiro_limpa_o_lixo_do_float():
    # 0.1 + 0.2 == 0.30000000000000004 em float
    assert como_dinheiro(0.1 + 0.2) == Decimal("0.30")


def test_divisao_fecha_com_o_total_ate_no_caso_feio():
    for total, n in (("100.00", 3), ("0.01", 1), ("10.00", 7), ("999.99", 4)):
        partes = dividir_em_centavos(Decimal(total), n)
        assert len(partes) == n
        assert sum(partes) == Decimal(total), f"{total} / {n} não fechou"


def test_divisao_por_zero_e_erro_e_nao_silencio():
    with pytest.raises(ValueError):
        dividir_em_centavos(Decimal("10.00"), 0)


# ------------------------------------------------------------------ expandir
def test_pagamento_mais_recebimento_gera_dois():
    itens = expandir(op(), ENTIDADES, SUBCONTAS, "OBRA PADRAO")
    assert [i["tipo_lancamento"] for i in itens] == ["pagamento", "recebimento"]
    assert all(isinstance(i["valor"], Decimal) for i in itens)


def test_so_pagamento_gera_um():
    itens = expandir(op(modo="Só pagamento"), ENTIDADES, SUBCONTAS, "OBRA")
    assert len(itens) == 1 and itens[0]["tipo_lancamento"] == "pagamento"


def test_rateio_uma_linha_por_obra_x_investidor_e_soma_fecha():
    o = op(pagador="INVESTIDOR SUBCONTA 111-1", tipo=regras.TIPO_INVESTIDOR, recebedor="SUBCONTA 111-1",
           modo="Só recebimento", valor=como_dinheiro("1000.00"))
    itens = expandir(o, ENTIDADES, SUBCONTAS, "OBRA")
    assert len(itens) == 4                       # 2 obras x 2 investidores
    assert sum(i["valor"] for i in itens) == Decimal("1000.00")


# --------------------------------------------------- rateio vazio come o valor
def test_validar_reclama_de_subconta_sem_investidores():
    subcontas = {"111-1": {"obras": ["OBRA 1"], "investidores": []}}
    o = op(pagador="INVESTIDOR SUBCONTA 111-1", tipo=regras.TIPO_INVESTIDOR, recebedor="SUBCONTA 111-1",
           modo="Só recebimento")
    erros = o.validar(ENTIDADES, subcontas)
    assert any("INVESTIDORES" in e for e in erros)


def test_validar_reclama_de_subconta_sem_obras():
    subcontas = {"111-1": {"obras": [], "investidores": ["X"]}}
    o = op(pagador="INVESTIDOR SUBCONTA 111-1", tipo=regras.TIPO_INVESTIDOR, recebedor="SUBCONTA 111-1",
           modo="Só recebimento")
    erros = o.validar(ENTIDADES, subcontas)
    assert any("OBRAS" in e for e in erros)


def test_expandir_recusa_rateio_vazio_em_vez_de_sumir_com_o_valor():
    """Antes: `max(1, 0)` evitava a divisão por zero, o laço não rodava e a
    operação virava ZERO lançamentos — o valor sumia sem erro nem aviso."""
    subcontas = {"111-1": {"obras": [], "investidores": []}}
    o = op(pagador="INVESTIDOR SUBCONTA 111-1", tipo=regras.TIPO_INVESTIDOR, recebedor="SUBCONTA 111-1",
           modo="Só recebimento", valor=como_dinheiro("500.00"))
    with pytest.raises(ValueError, match="sumiria|rateio"):
        expandir(o, ENTIDADES, subcontas, "OBRA")


# ------------------------------------------------------------------ validação
def test_pessoa_fisica_sem_conta_so_pode_ser_recebimento():
    erros = op(pagador="PESSOA FISICA", modo="Só pagamento").validar(
        ENTIDADES, SUBCONTAS)
    assert any("pessoa física" in e for e in erros)


def test_pagador_igual_recebedor_e_erro():
    erros = op(recebedor="EMPRESA A").validar(ENTIDADES, SUBCONTAS)
    assert any("não podem ser o mesmo" in e for e in erros)


def test_valor_zero_e_erro():
    erros = op(valor=como_dinheiro("0")).validar(ENTIDADES, SUBCONTAS)
    assert any("maior que zero" in e for e in erros)


def test_descricao_usa_o_apelido_quando_existe():
    entidades = dict(ENTIDADES)
    entidades["EMPRESA B"] = {**ENTIDADES["EMPRESA B"],
                              "nome_descricao": "B / SÓCIOS"}
    d = op().descricao(entidades, SUBCONTAS)
    assert d.endswith("PARA B / SÓCIOS")
    assert d.startswith("APORTE CAPITAL - ")


def test_o_modulo_nao_usa_float_para_dinheiro():
    """Guarda-corpo: se alguém reintroduzir float aqui, o teste avisa."""
    itens = expandir(op(), ENTIDADES, SUBCONTAS, "OBRA")
    assert not any(isinstance(i["valor"], float) for i in itens)
    assert regras.como_dinheiro("1.005") == Decimal("1.01")   # arredonda p/ cima


# ------------------------------------------- a baixa do recebimento (dinheiro)
from aportes import mc_lancamentos


@pytest.mark.parametrize("parcela, esperado", [
    ({"id": 1, "receipts": [{"id": 9}]}, "feita"),
    ({"id": 1, "isReceived": True}, "feita"),
    ({"id": 1, "received": True}, "feita"),
    ({"id": 1, "settled": True}, "feita"),
    ({"id": 1, "isReceived": False}, "aberta"),
    ({"id": 1, "receipts": []}, "aberta"),
    ({"id": 1, "plannedValue": 100}, "desconhecida"),
    ({}, "desconhecida"),
    (None, "desconhecida"),
])
def test_estado_da_baixa_tem_tres_respostas(parcela, esperado):
    """A diferença entre "aberta" e "desconhecida" é a diferença entre
    lançar de novo e NÃO lançar.

    A versão anterior devolvia booleano e dizia ser "conservadora: na dúvida
    devolve False" — mas `False` faz o chamador TENTAR a baixa, então a dúvida
    levava justamente ao segundo lançamento (R$ 2,00 no lugar de R$ 1,00) que
    o comentário dizia evitar. O `POST /sales` já leva `isReceived=true`, e o
    caminho da parcela dentro da resposta nunca foi confirmado por captura:
    resposta em formato novo = não se sabe nada sobre a baixa.
    """
    assert mc_lancamentos.estado_da_baixa(parcela) == esperado


class _CatalogosFalso:
    """Só o que `criar_recebimento` consulta. Devolve tudo com id fictício."""

    def __init__(self, resposta):
        self._resposta = resposta
        self.postagens = []

    def _achado(self, nome):
        return {"id": f"id-{nome}", "name": nome}

    conta = participante = natureza = obra = _achado
    forma_recebimento = _achado

    def condicao_a_vista_recebimento(self):
        return self._achado("a-vista")

    def postar(self, url, corpo):
        self.postagens.append(url)
        return self._resposta


def _recebimento(resposta):
    cat = _CatalogosFalso(resposta)
    r = mc_lancamentos.criar_recebimento(
        cat, data=HOJE, valor=Decimal("100.00"), descricao="APORTE",
        conta_recebedora="BANCO", cliente="EMPRESA A", natureza="APORTE",
        forma="TED", obra="OBRA 1", id_usuario="u1")
    return r, cat


def test_resposta_sem_noticia_da_baixa_nao_tenta_de_novo():
    """Venda criada + baixa em estado desconhecido: avisa, e NÃO repete.

    A segunda chamada é a que duplicaria a entrada. E o resultado carrega o
    `id_criado`, que é o que impede a aba de criar uma SEGUNDA venda no
    clique seguinte.
    """
    r, cat = _recebimento({"id": "venda-1",
                           "installments": [{"id": "p1", "plannedValue": 100.0}]})
    assert not r.ok
    assert r.id_criado == "venda-1"
    assert "não deu para saber" in (r.erro or "")
    assert len(cat.postagens) == 1          # só o POST /sales


def test_baixa_que_ja_veio_feita_nao_e_repetida():
    r, cat = _recebimento({"id": "venda-2",
                           "installments": [{"id": "p1", "isReceived": True}]})
    assert r.ok and r.id_criado == "venda-2"
    assert len(cat.postagens) == 1


def test_parcela_declarada_em_aberto_recebe_a_baixa():
    r, cat = _recebimento({"id": "venda-3",
                           "installments": [{"id": "p1", "isReceived": False}]})
    assert r.ok
    assert len(cat.postagens) == 2          # /sales e depois a baixa
    assert "receipts" in cat.postagens[1]


# ------------------------------------------- aporte de investidor (01/10/2026)
def test_peso_divide_na_proporcao_e_fecha_o_total():
    assert regras.dividir_por_peso(Decimal("1000.00"), ["A", "B"],
                                   {"A": "2", "B": "1"}) == \
        [Decimal("666.67"), Decimal("333.33")]
    assert regras.dividir_por_peso(Decimal("1000.00"), ["A", "B"],
                                   {"A": "60", "B": "40"}) == \
        [Decimal("600.00"), Decimal("400.00")]


def test_peso_um_um_um_fecha_no_centavo():
    partes = regras.dividir_por_peso(Decimal("100.00"), ["A", "B", "C"],
                                     {"A": "1", "B": "1", "C": "1"})
    assert sum(partes) == Decimal("100.00")


def test_sem_peso_continua_partes_iguais():
    assert regras.dividir_por_peso(Decimal("100.00"), ["A", "B", "C"], {}) == \
        regras.dividir_em_centavos(Decimal("100.00"), 3)


@pytest.mark.parametrize("pesos, pedaco", [
    ({"A": "2"}, "falta a parte de: B"),
    ({"A": "1", "B": "0"}, "maior que zero"),
    ({"A": "1.00001", "B": "1"}, "4 casas"),
])
def test_peso_incompleto_e_recusado(pesos, pedaco):
    assert pedaco in regras.problema_dos_pesos(["A", "B"], pesos)
    with pytest.raises(ValueError):
        regras.dividir_por_peso(Decimal("10.00"), ["A", "B"], pesos)


def test_percentuais_dos_pesos_para_mostrar():
    assert regras.percentuais_dos_pesos(["A", "B"], {"A": "2", "B": "1"}) == \
        [Decimal("66.67"), Decimal("33.33")]
    assert regras.percentuais_dos_pesos(["A", "B"], {}) == \
        [Decimal("50.00"), Decimal("50.00")]


SUB_INV = {"11111-1": {"obras": ["LOTE 1", "LOTE 2"],
                       "investidores": ["INV A", "INV B"],
                       "pesos": {"inv a": "3", "INV B": "1"}}}
ENT_INV = {"SUBCONTA 11111-1 - BANCO - INVESTIDOR": {
    "nome_oficial": "HOLDING", "conta": "Holding - SUBCONTA 11111-1",
    "nome_descricao": None}}


def _op_inv(**kw):
    base = dict(data=datetime.date(2026, 10, 1),
                pagador="INVESTIDOR SUBCONTA 11111-1",
                recebedor="SUBCONTA 11111-1 - BANCO - INVESTIDOR",
                valor=Decimal("1000.00"), tipo=regras.TIPO_INVESTIDOR,
                modo="Só recebimento")
    base.update(kw)
    return Operacao(**base)


def test_aporte_de_investidor_proporcao_entre_aportadores_obras_iguais():
    o = _op_inv()
    assert o.validar(ENT_INV, SUB_INV) == []
    itens = expandir(o, ENT_INV, SUB_INV, "PADRAO")
    assert [(i["obra"], i["cliente"], i["valor"]) for i in itens] == [
        ("LOTE 1", "INV A", Decimal("375.00")), ("LOTE 1", "INV B", Decimal("125.00")),
        ("LOTE 2", "INV A", Decimal("375.00")), ("LOTE 2", "INV B", Decimal("125.00"))]
    assert sum(i["valor"] for i in itens) == Decimal("1000.00")
    assert {i["natureza"] for i in itens} == {"Aporte de Investidor"}
    assert all(i["descricao"].startswith("APORTE INVESTIDOR - ") for i in itens)


def test_subconta_de_investidor_exige_o_tipo_novo():
    erros = _op_inv(tipo="Aporte de Capital").validar(ENT_INV, SUB_INV)
    assert any("Aporte de Investidor" in e for e in erros)


def test_tipo_investidor_so_como_recebimento():
    o = Operacao(data=HOJE, pagador="EMPRESA A", recebedor="EMPRESA B",
                 valor=Decimal("10.00"), tipo=regras.TIPO_INVESTIDOR,
                 modo="Pagamento + Recebimento")
    assert any("Só recebimento" in e for e in o.validar(ENTIDADES, SUBCONTAS))


def test_validar_barra_peso_incompleto():
    sub = {"11111-1": dict(SUB_INV["11111-1"], pesos={"INV A": "3"})}
    assert any("falta a parte" in e for e in _op_inv().validar(ENT_INV, sub))


def test_anexar_ignora_a_descricao_do_aporte_de_investidor():
    from anexar import config
    assert "APORTE INVESTIDOR" in config.IGNORAR_APORTES


def test_peso_nan_vindo_do_banco_e_recusado():
    assert "não é número" in regras.problema_dos_pesos(["A", "B"],
                                                       {"A": "NaN", "B": "1"})


@pytest.mark.parametrize("texto, numero", [
    ("EMPRESA - INTER 1234567-8", ""),          # 7 dígitos: não é subconta
    ("SICOOB 112345-6", ""),
    ("Holding - SUBCONTA 12345-6 - BANCO", "12345-6"),
    ("Holding - 12.345-6", "12345-6"),
])
def test_numero_da_conta_nao_le_de_dentro_de_outro_numero(texto, numero):
    assert regras.numero_da_conta(texto) == numero


def test_recebedor_da_subconta_pelo_numero_exato():
    ent = dict(ENT_INV)
    ent["OUTRA"] = {"nome_oficial": "X", "conta": "OUTRA - SICOOB 112345-6",
                    "nome_descricao": None}
    o = _op_inv(recebedor="OUTRA")
    assert any("deve ser a subconta" in e for e in o.validar(ent, SUB_INV))


def test_tipo_investidor_com_pagador_da_casa_e_recusado():
    o = Operacao(data=HOJE, pagador="EMPRESA A", recebedor="EMPRESA B",
                 valor=Decimal("10.00"), tipo=regras.TIPO_INVESTIDOR,
                 modo="Só recebimento")
    assert any("tem conta no app" in e for e in o.validar(ENTIDADES, SUBCONTAS))


# ---------------------------------------------------------------- rótulo
# 21/10/2026: a lista de Pagou mostra os investidores NA FRENTE da subconta,
# para a busca achar pelo nome; a operação continua guardando o nome curto.

def test_rotulo_poe_os_investidores_na_frente():
    assert regras.rotulo_investidor("111-1", SUBCONTAS["111-1"]) == \
        "INVESTIDOR X / INVESTIDOR Y - INVESTIDOR SUBCONTA 111-1"


def test_rotulo_sem_investidor_fica_o_nome_curto():
    assert regras.rotulo_investidor("111-1", {"investidores": []}) == \
        "INVESTIDOR SUBCONTA 111-1"


def test_numero_sai_do_rotulo_e_do_nome_curto():
    rotulo = regras.rotulo_investidor("111-1", SUBCONTAS["111-1"])
    assert regras.numero_subconta(rotulo, SUBCONTAS) == "111-1"
    assert regras.numero_subconta("INVESTIDOR SUBCONTA 111-1", SUBCONTAS) == "111-1"


@pytest.mark.parametrize("texto", [
    "INVESTIDOR SUBCONTA 999-9",            # subconta que não existe
    "INVESTIDOR X",                          # só o nome
    "FULANOINVESTIDOR SUBCONTA 111-1",       # sem o " - " separando
    "INVESTIDOR SUBCONTA 111-1 EXTRA",
])
def test_numero_nao_adivinha(texto):
    assert regras.numero_subconta(texto, SUBCONTAS) is None


def test_operacao_guarda_o_pagador_curto():
    rotulo = regras.rotulo_investidor("111-1", SUBCONTAS["111-1"])
    assert regras.pagador_canonico(rotulo, SUBCONTAS) == "INVESTIDOR SUBCONTA 111-1"
    assert regras.pagador_canonico("EMPRESA A", SUBCONTAS) == "EMPRESA A"


def test_busca_pelo_nome_do_investidor_acha_a_subconta():
    import util
    lista = list(ENTIDADES) + [regras.rotulo_investidor(n, d)
                               for n, d in SUBCONTAS.items()
                               if not n.startswith("_")]
    achados = util.filtrar(lista, "investidor y")
    assert any(regras.numero_subconta(a, SUBCONTAS) == "111-1" for a in achados)


class _Combo:
    def __init__(self, valores, atual):
        self.valores, self.atual = list(valores), atual

    def valores_completos(self):
        return list(self.valores)

    def set(self, v):
        self.atual = v

    def get(self):
        return self.atual


def test_gravar_rateio_nao_tira_a_subconta_do_pagou():
    """Revisão de dinheiro 21/10: gravar o rateio muda o rótulo da subconta;
    comparando o TEXTO, Pagou caía no 1º nome da lista em silêncio."""
    from types import SimpleNamespace
    from aportes.aportes_frame import AportesFrame
    antes = regras.rotulo_investidor("111-1", SUBCONTAS["111-1"])
    novos = {**SUBCONTAS, "111-1": {**SUBCONTAS["111-1"],
             "investidores": ["INVESTIDOR X", "INVESTIDOR Y", "INVESTIDOR Z"]}}
    depois = regras.rotulo_investidor("111-1", novos["111-1"])
    chamadas = []
    fake = SimpleNamespace(
        subcontas=novos,
        cb_pagador=_Combo(list(ENTIDADES) + [depois], "EMPRESA A"),
        cb_recebedor=_Combo(list(ENTIDADES), "EMPRESA B"),
        _pagador_escolhido=lambda: chamadas.append(1))
    AportesFrame._restaurar_escolha(fake, antes, "SUBCONTA 111-1")
    assert fake.cb_pagador.get() == depois
    assert fake.cb_recebedor.get() == "SUBCONTA 111-1"
    assert chamadas == [1]


# ------------------------------------------------- Lançar preenchido sozinho
# 22/10/2026, pedido do dono: escolher Pagou/Recebeu já põe o "Lançar" certo.
# É SÓ padrão: a trava continua no `validar`.
ENTIDADES_PF = {**ENTIDADES,
                "OUTRA PESSOA": {"nome_oficial": "BELTRANO", "conta": None,
                                 "nome_descricao": None}}


@pytest.mark.parametrize("pagador, recebedor, esperado", [
    ("EMPRESA A", "EMPRESA B", "Pagamento + Recebimento"),
    ("PESSOA FISICA", "EMPRESA B", "Só recebimento"),
    ("EMPRESA A", "PESSOA FISICA", "Só pagamento"),
    # Os dois sem conta: não há modo que sirva; fica como está e o validar
    # avisa.
    ("PESSOA FISICA", "OUTRA PESSOA", None),
    # Investidor de subconta só aceita a perna do recebimento.
    ("INVESTIDOR SUBCONTA 111-1", "SUBCONTA 111-1", "Só recebimento"),
    # Um lado ainda desconhecido (digitando): só a PF já decide.
    ("PESSOA FISICA", "", "Só recebimento"),
    ("", "PESSOA FISICA", "Só pagamento"),
    ("EMPRESA A", "EMPR", None),
    ("", "", None),
])
def test_modo_padrao(pagador, recebedor, esperado):
    assert regras.modo_padrao(pagador, recebedor, ENTIDADES_PF,
                              SUBCONTAS) == esperado


def test_modo_padrao_bate_com_o_validar():
    """O padrão nunca sugere um modo que o próprio `validar` recusaria."""
    for pag in ENTIDADES_PF:
        for rec in ENTIDADES_PF:
            if pag == rec:
                continue
            modo = regras.modo_padrao(pag, rec, ENTIDADES_PF, SUBCONTAS)
            if modo is None:
                continue
            erros = op(pagador=pag, recebedor=rec, modo=modo).validar(
                ENTIDADES_PF, SUBCONTAS)
            assert not any("pessoa física" in e for e in erros), (pag, rec)


def test_pessoa_sem_conta():
    assert regras.pessoa_sem_conta(ENTIDADES, "PESSOA FISICA")
    assert not regras.pessoa_sem_conta(ENTIDADES, "EMPRESA A")
    assert not regras.pessoa_sem_conta(ENTIDADES, "NINGUEM")   # desconhecido


def _form(pagou, recebeu, modo="Pagamento + Recebimento"):
    from types import SimpleNamespace
    return SimpleNamespace(
        entidades=ENTIDADES_PF, subcontas=SUBCONTAS,
        cb_pagador=_Combo(list(ENTIDADES_PF), pagou),
        cb_recebedor=_Combo(list(ENTIDADES_PF), recebeu),
        cb_modo=_Combo([], modo), _partes_do_modo=None)


def test_escolher_pagou_ou_recebeu_preenche_o_lancar():
    from aportes.aportes_frame import AportesFrame
    f = _form("PESSOA FISICA", "EMPRESA B")
    AportesFrame._aplicar_modo_padrao(f)
    assert f.cb_modo.get() == "Só recebimento"
    f.cb_pagador.set("EMPRESA A")
    f.cb_recebedor.set("PESSOA FISICA")
    AportesFrame._aplicar_modo_padrao(f)
    assert f.cb_modo.get() == "Só pagamento"
    f.cb_recebedor.set("EMPRESA B")
    AportesFrame._aplicar_modo_padrao(f)
    assert f.cb_modo.get() == "Pagamento + Recebimento"


def test_troca_manual_do_lancar_sobrevive_ate_mudar_pagou_ou_recebeu():
    """Sair do campo de novo (FocusOut) sem trocar Pagou/Recebeu não desfaz a
    escolha do dono; trocar uma das partes também não (revisão de 22/10: o
    padrão só avisa no Registro quando discorda, ver os testes abaixo)."""
    from aportes.aportes_frame import AportesFrame
    f = _form("EMPRESA A", "EMPRESA B")
    AportesFrame._aplicar_modo_padrao(f)
    assert f.cb_modo.get() == "Pagamento + Recebimento"
    f.cb_modo.set("Só pagamento")                     # o dono trocou
    AportesFrame._aplicar_modo_padrao(f)              # FocusOut de novo
    assert f.cb_modo.get() == "Só pagamento"
    f.cb_recebedor.set("PESSOA FISICA")
    AportesFrame._aplicar_modo_padrao(f)
    assert f.cb_modo.get() == "Só pagamento"
    f.cb_modo.set("Pagamento + Recebimento")          # trocou de novo
    f.cb_recebedor.set("EMPRESA B")
    AportesFrame._aplicar_modo_padrao(f)
    assert f.cb_modo.get() == "Pagamento + Recebimento"


def test_dois_sem_conta_deixa_o_lancar_como_esta():
    from aportes.aportes_frame import AportesFrame
    f = _form("PESSOA FISICA", "OUTRA PESSOA", modo="Só pagamento")
    AportesFrame._aplicar_modo_padrao(f)
    assert f.cb_modo.get() == "Só pagamento"


# ----------------------------------- o Lançar do dono não é sobrescrito (22/10)
# Revisão de dinheiro: depois que o dono troca o Lançar à mão, o padrão nunca
# mais o sobrescreve, nem quando o par Pagou/Recebeu muda — só avisa no
# Registro. Antes de ele mexer, o padrão aplica a cada par novo.
def _form_com_registro(pagou, recebeu, modo="Pagamento + Recebimento"):
    f = _form(pagou, recebeu, modo)
    f.registro = []
    f._log = f.registro.append
    f.cb_tipo = _Combo([], "Aporte")
    f._modo_aplicado, f._modo_manual = modo, False
    return f


def test_lancar_trocado_a_mao_nunca_e_sobrescrito_pelo_padrao():
    from aportes.aportes_frame import AportesFrame
    f = _form_com_registro("EMPRESA A", "EMPRESA B")
    AportesFrame._aplicar_modo_padrao(f)
    assert f.cb_modo.get() == "Pagamento + Recebimento" and f.registro == []
    f.cb_modo.set("Só recebimento")                   # o dono trocou
    f.cb_recebedor.set("PESSOA FISICA")               # par novo: padrão "Só pagamento"
    AportesFrame._aplicar_modo_padrao(f)
    assert f.cb_modo.get() == "Só recebimento"
    assert f.registro == ["Confira o Lançar: ficou 'Só recebimento' (o padrão "
                          "para este par seria 'Só pagamento')."]
    # Voltar ao mesmo valor do padrão não desliga a escolha do dono.
    f.cb_modo.set("Pagamento + Recebimento")
    f.cb_recebedor.set("EMPRESA B")
    AportesFrame._aplicar_modo_padrao(f)
    f.cb_pagador.set("PESSOA FISICA")                 # padrão "Só recebimento"
    AportesFrame._aplicar_modo_padrao(f)
    assert f.cb_modo.get() == "Pagamento + Recebimento"
    assert "seria 'Só recebimento'" in f.registro[-1]


def test_antes_do_dono_mexer_o_padrao_aplica_a_cada_par_novo():
    from aportes.aportes_frame import AportesFrame
    f = _form_com_registro("EMPRESA A", "EMPRESA B")
    for pagou, recebeu, esperado in (("EMPRESA A", "EMPRESA B", "Pagamento + Recebimento"),
                                     ("PESSOA FISICA", "EMPRESA B", "Só recebimento"),
                                     ("EMPRESA A", "PESSOA FISICA", "Só pagamento")):
        f.cb_pagador.set(pagou)
        f.cb_recebedor.set(recebeu)
        AportesFrame._aplicar_modo_padrao(f)
        assert f.cb_modo.get() == esperado
    assert f.registro == []


def test_sair_do_investidor_reaplica_o_padrao_mesmo_par_de_texto(monkeypatch):
    """Item 4: o ramo que devolve Tipo/Lançar ao primeiro valor zera o par,
    senão o padrão não reaplica e o Lançar fica no MODOS[0]."""
    from aportes import dados as cadastro
    from aportes.aportes_frame import AportesFrame
    f = _form_com_registro("PESSOA FISICA", "EMPRESA B", modo="Só recebimento")
    f.cb_tipo.set(regras.TIPO_INVESTIDOR)
    f._partes_do_modo = ("PESSOA FISICA", "EMPRESA B")    # o par já visto
    f._aplicar_modo_padrao = lambda: AportesFrame._aplicar_modo_padrao(f)
    AportesFrame._pagador_escolhido(f)
    assert f.cb_tipo.get() == cadastro.TIPOS[0]
    assert f.cb_modo.get() == "Só recebimento"           # o padrão, e não MODOS[0]
    assert f.registro == []


def test_rotulo_novo_do_rateio_nao_conta_como_par_novo():
    """Item 5: gravar o rateio muda o TEXTO do Pagou (rótulo do investidor);
    não é par novo, e o Lançar fica como estava."""
    from types import SimpleNamespace
    from aportes.aportes_frame import AportesFrame
    antes = regras.rotulo_investidor("111-1", SUBCONTAS["111-1"])
    novos = {**SUBCONTAS, "111-1": {**SUBCONTAS["111-1"],
             "investidores": ["INVESTIDOR X", "INVESTIDOR Y", "INVESTIDOR Z"]}}
    depois = regras.rotulo_investidor("111-1", novos["111-1"])
    fake = SimpleNamespace(
        subcontas=novos,
        cb_pagador=_Combo(list(ENTIDADES) + [depois], "EMPRESA A"),
        cb_recebedor=_Combo(list(ENTIDADES), "EMPRESA B"),
        _partes_do_modo=(antes, "SUBCONTA 111-1"),
        _pagador_escolhido=lambda: None)
    AportesFrame._restaurar_escolha(fake, antes, "SUBCONTA 111-1")
    assert fake._partes_do_modo == (depois, "SUBCONTA 111-1")
    # O que NÃO voltou (sumiu da lista) é par novo de verdade: não acompanha.
    fake2 = SimpleNamespace(
        subcontas=SUBCONTAS,
        cb_pagador=_Combo(list(ENTIDADES), "EMPRESA A"),
        cb_recebedor=_Combo(list(ENTIDADES), "EMPRESA A"),
        _partes_do_modo=("EMPRESA A", "SUMIU"),
        _pagador_escolhido=lambda: None)
    AportesFrame._restaurar_escolha(fake2, "EMPRESA A", "SUMIU")
    assert fake2._partes_do_modo == ("EMPRESA A", "SUMIU")


def test_renome_de_cadastro_acompanha_o_par_do_lancar():
    """Item 5: corrigir o nome de quem está em Pagou/Recebeu troca o texto do
    combo; não é par novo, e o Lançar trocado à mão não é revisto."""
    from aportes.aportes_frame import AportesFrame
    f = _form_com_registro("EMPRESA A", "EMPRESA B")
    f._partes_do_modo = ("EMPRESA A", "EMPRESA B")
    f.cb_pagador.valores.append("EMPRESA A NOVA")
    f.cb_pagador.set("EMPRESA A NOVA")
    AportesFrame._acompanhar_par(f, ("EMPRESA A", "EMPRESA B"), voltou=True)
    assert f._partes_do_modo == ("EMPRESA A NOVA", "EMPRESA B")
    f._partes_do_modo = ("EMPRESA A", "EMPRESA B")
    AportesFrame._acompanhar_par(f, ("EMPRESA A", "EMPRESA B"), voltou=False)
    assert f._partes_do_modo == ("EMPRESA A", "EMPRESA B")
    # Par antigo que não era o do Lançar (padrão nem aplicado): não mexe.
    f._partes_do_modo = None
    AportesFrame._acompanhar_par(f, ("EMPRESA A", "EMPRESA B"), voltou=True)
    assert f._partes_do_modo is None


def test_cadastro_corrigido_chama_o_acompanhar_par():
    import ast
    from pathlib import Path
    fonte = (Path(__file__).resolve().parents[1] / "aportes" / "aportes_frame.py"
             ).read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    metodo = next(n for n in ast.walk(arvore)
                  if isinstance(n, ast.FunctionDef) and n.name == "_cadastro_corrigido")
    chamadas = [n.func.attr for n in ast.walk(metodo)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert "_acompanhar_par" in chamadas
