# -*- coding: utf-8 -*-
"""Confronto HTML × agendamentos pendentes no Sicoob (dono, 15/10/2026).

Dados FICTÍCIOS: nomes, valores e descrições inventados (repo público)."""
import datetime as dt
from types import SimpleNamespace as NS

import pytest

from extratos_sicoob import pendencias
from pagamentos_dia import agendamentos_sicoob as A
from pagamentos_dia import html_pagamentos


def entrada(centavos, favorecido="Loja Exemplo", descricao="OBRA X QD 1 LT 2 OC 100"):
    return {"centavos": centavos, "favorecido": favorecido,
            "descricao": descricao}


def pendencia(valor, detalhe="LOJA EXEMPLO", observacao=None, pid=None):
    return {"valor": valor, "detalhe": detalhe, "observacao": observacao,
            "nomeTransacao": "Pagamento de Título", "pendencia": pid}


# ------------------------------------------------------------- o confronto

def test_valor_e_nome_batendo_e_ok():
    [li] = A.confrontar([entrada(12345)], [pendencia(123.45)])
    assert li.situacao == A.OK


def test_valor_bate_e_nome_nao_divide_palavra_sai_ambar():
    # Reembolso que vai para quem pagou: legítimo, mas é o que se olha.
    [li] = A.confrontar([entrada(5000, "Fulano (reembolso de Loja Exemplo)")],
                        [pendencia(50.0, "BELTRANO DE TAL")])
    assert li.situacao == A.NOME_DIFERENTE
    assert A.ESTADO[li.situacao] == "atencao"


def test_boleto_sem_nome_casa_pela_descricao_colada():
    # Em boleto o Sicoob devolve só "Observação: <descrição>", sem recebedor.
    desc = "OBRA X QD 9 LT 9 NF 123 OC 456"
    [li] = A.confrontar([entrada(4500, "Fornecedor Exemplo", desc)],
                        [pendencia(45.0, f"Observação: {desc}", observacao=desc)])
    assert li.situacao == A.OK


def test_observacao_cortada_pelo_banco_ainda_casa():
    desc = "CONDOMINIO EXEMPLO Constituicao do CNPJ RET 10 unidades RPB 99"
    [li] = A.confrontar([entrada(10000, "Escritorio Exemplo", desc)],
                        [pendencia(100.0, "Observação: " + desc[:49],
                                   observacao=desc[:49])])
    assert li.situacao == A.OK


def test_pedaco_curto_demais_nao_prova_nada():
    [li] = A.confrontar([entrada(10000, "Fornecedor Exemplo",
                                 "OBRA X QD 1 LT 2 OC 300")],
                        [pendencia(100.0, "Observação: OBRA X",
                                   observacao="OBRA X")])
    assert li.situacao == A.NOME_DIFERENTE


def test_boleto_de_mesmo_valor_e_outra_descricao_nao_e_ok():
    [li] = A.confrontar([entrada(4500, "Fornecedor Exemplo", "OBRA X OC 1")],
                        [pendencia(45.0, "Observação: OBRA Y OC 2",
                                   observacao="OBRA Y OC 2")])
    assert li.situacao == A.NOME_DIFERENTE


def test_nome_desempata_dois_agendamentos_do_mesmo_valor():
    e1 = entrada(1000, "Alfa Materiais")
    e2 = entrada(1000, "Beta Servicos")
    p_beta = pendencia(10.0, "BETA SERVICOS LTDA")
    p_alfa = pendencia(10.0, "ALFA MATERIAIS")
    linhas = A.confrontar([e1, e2], [p_beta, p_alfa])
    assert all(li.situacao == A.OK for li in linhas)
    pares = {li.html["favorecido"]: li.banco["detalhe"] for li in linhas}
    assert pares == {"Alfa Materiais": "ALFA MATERIAIS",
                     "Beta Servicos": "BETA SERVICOS LTDA"}


def test_sobra_do_html_e_falta_no_banco():
    linhas = A.confrontar([entrada(100), entrada(200)], [pendencia(1.0)])
    assert [li.situacao for li in linhas] == [A.FALTA_NO_BANCO, A.OK]


def test_sobra_do_banco_e_so_no_banco():
    linhas = A.confrontar([], [pendencia(9.99)])
    assert [li.situacao for li in linhas] == [A.SO_NO_BANCO]


def test_mesma_descricao_com_valor_diferente_vira_valor_diverge():
    # Boleto agendado com R$ 0,00 e observação idêntica à descrição.
    desc = "CONDOMINIO EXEMPLO Constituicao do CNPJ"
    linhas = A.confrontar(
        [entrada(250000, "Escritorio Contabil Exemplo", desc)],
        [pendencia(0.0, f"Observação: {desc}", observacao=desc)])
    assert [li.situacao for li in linhas] == [A.VALOR_DIVERGE]
    assert linhas[0].valor_html == A.Decimal("2500.00")
    assert linhas[0].valor_banco == A.Decimal("0")


def test_cada_pendencia_e_usada_uma_vez_so():
    linhas = A.confrontar([entrada(500), entrada(500)], [pendencia(5.0)])
    assert sorted(li.situacao for li in linhas) == [A.FALTA_NO_BANCO, A.OK]


def test_centavos_do_banco_nao_sofre_com_float():
    assert A.centavos_do_banco({"valor": 0.29}) == 29
    assert A.centavos_do_banco({"valor": 4721.75}) == 472175
    assert A.centavos_do_banco({"valor": None}) == 0


def test_resumo_e_pior_da_conta():
    conf = A.Confronto("CONTA X - SICOOB", "1.234-5",
                       linhas=A.confrontar([entrada(100), entrada(300)],
                                           [pendencia(1.0)]))
    assert conf.pior == A.FALTA_NO_BANCO
    assert "1 não está agendado no banco" in conf.resumo()
    assert conf.total_html == A.Decimal("4.00")
    assert conf.total_banco == A.Decimal("1.00")
    tudo_ok = A.Confronto("C", "1", linhas=A.confrontar([entrada(100)],
                                                        [pendencia(1.0)]))
    assert tudo_ok.resumo().startswith("tudo bate")
    assert A.Confronto("C", motivo="conta de outro banco").resumo().startswith(
        "não conferida")


# ---------------------------------------------------------------- o HTML

def test_le_de_volta_o_html_que_o_app_grava():
    contas = [{"nome": "CONTA X - SICOOB", "total": "1,00",
               "entries": [{"centavos": 100, "favorecido": "</script>&<b>",
                            "descricao": "OC 1"}]}]
    texto = ("<html><script>\nconst DATA = "
             + html_pagamentos.json_para_script({"contas": contas})
             + ";\nfunction x(){}\n</script></html>")
    assert A.ler_html(texto) == contas


def test_html_que_nao_e_dos_pagamentos_e_recusado():
    with pytest.raises(ValueError, match="não é um HTML dos pagamentos"):
        A.ler_html("<html><body>nada</body></html>")


# --------------------------------------------------------- conta do Sicoob

def _mapa(destinos):
    return NS(de=lambda nome: next((d for d in destinos if d.erp == nome), None))


def test_conta_sicoob_pelo_mesmo_caminho_da_remessa():
    destino = NS(erp="EMPRESA X - SICOOB", empresa="EMPRESA X", pasta="SICOOB",
                 banco="SICOOB", sufixo="")
    empresas = [NS(nome="EMPRESA X", contas=[
        NS(numero="12.345-6", pasta="SICOOB", sufixo="")])]
    assert A.conta_sicoob("EMPRESA X - SICOOB", _mapa([destino]),
                          empresas) == ("12.345-6", "")


def test_conta_de_outro_banco_fica_fora_com_motivo():
    destino = NS(erp="EMPRESA X - INTER", empresa="EMPRESA X", pasta="INTER",
                 banco="INTER", sufixo="")
    numero, motivo = A.conta_sicoob("EMPRESA X - INTER", _mapa([destino]), [])
    assert numero == "" and motivo == A.MOTIVO_FORA_SICOOB


def test_conta_fora_do_mapa():
    assert A.conta_sicoob("NAO EXISTE", _mapa([]), [])[1] == \
        A.MOTIVO_CONTA_DESCONHECIDA


def test_periodo_vai_do_mes_passado_ao_fim_do_seguinte():
    assert A.periodo_da_consulta(dt.date(2026, 10, 15)) == (
        dt.date(2026, 9, 1), dt.date(2026, 11, 30))
    assert A.periodo_da_consulta(dt.date(2026, 12, 31)) == (
        dt.date(2026, 11, 1), dt.date(2027, 1, 31))
    # No dia 1º o agendamento da véspera continua dentro.
    assert A.periodo_da_consulta(dt.date(2026, 11, 1))[0] == dt.date(2026, 10, 1)


# ------------------------------------------------- o lado do banco (sem rede)

class PaginaFalsa:
    """Responde ao `fetch` como o Sicoob respondeu em 15/10/2026."""

    def __init__(self, abertas, respostas):
        self.abertas = abertas
        self.respostas = list(respostas)
        self.pedidos = []

    def evaluate(self, _js, args):
        url, metodo, corpo = args
        self.pedidos.append((url, metodo, corpo))
        if url == pendencias.ROTA_CONTAS:
            import json
            return {"status": 200, "corpo": json.dumps(
                [{"contaCorrente": int(c)} for c in self.abertas])}
        return self.respostas.pop(0)


def test_consulta_confere_a_conta_aberta_antes_de_pedir():
    pagina = PaginaFalsa(["999999"], [])
    with pytest.raises(pendencias.PendenciasFalhou, match="outra conta"):
        pendencias.consultar(pagina, "12.345-6", dt.date(2026, 10, 1),
                             dt.date(2026, 10, 31))
    assert all(u != pendencias.ROTA_CONSULTAR for u, _m, _c in pagina.pedidos)


def test_400_de_sem_resultados_e_lista_vazia():
    vazio = {"status": 400, "corpo": '{"mensagem":"Não existem resultados '
                                     'para o período informado."}'}
    pagina = PaginaFalsa(["123456"], [vazio])
    assert pendencias.consultar(pagina, "12.345-6", dt.date(2026, 10, 1),
                                dt.date(2026, 10, 31)) == []
    _u, metodo, corpo = pagina.pedidos[-1]
    assert metodo == "POST"
    assert corpo["contasCorrentes"] == [123456] and corpo["tipo"] == 0


def test_outro_erro_do_banco_nao_vira_lista_vazia():
    pagina = PaginaFalsa(["123456"], [{"status": 500, "corpo": "pane"}])
    with pytest.raises(pendencias.PendenciasFalhou, match="HTTP 500"):
        pendencias.consultar(pagina, "12.345-6", dt.date(2026, 10, 1),
                             dt.date(2026, 10, 31))


def test_ler_conta_pede_mes_a_mes_e_nao_repete_pendencia():
    import json
    p1 = {"status": 200, "corpo": json.dumps([{"pendencia": 1, "valor": 1.0}])}
    p2 = {"status": 200, "corpo": json.dumps([{"pendencia": 1, "valor": 1.0},
                                              {"pendencia": 2, "valor": 2.0}])}
    pagina = PaginaFalsa(["123456"], [p1, p2])
    cli = NS(page=pagina, acessar_conta=lambda n: True)
    lidas = pendencias.ler_conta(cli, "12.345-6", dt.date(2026, 10, 1),
                                 dt.date(2026, 11, 30))
    assert [p["pendencia"] for p in lidas] == [1, 2]
    consultas = [c for u, _m, c in pagina.pedidos
                 if u == pendencias.ROTA_CONSULTAR]
    assert len(consultas) == 2


def test_conta_fora_do_login_e_falha_e_nao_lista_vazia():
    cli = NS(page=PaginaFalsa([], []), acessar_conta=lambda n: False)
    with pytest.raises(pendencias.PendenciasFalhou, match="não aparece"):
        pendencias.ler_conta(cli, "12.345-6", dt.date(2026, 10, 1),
                             dt.date(2026, 10, 31))


def test_meses_corta_no_fim_de_cada_mes():
    assert pendencias.meses(dt.date(2026, 10, 15), dt.date(2026, 12, 5)) == [
        (dt.date(2026, 10, 15), dt.date(2026, 10, 31)),
        (dt.date(2026, 11, 1), dt.date(2026, 11, 30)),
        (dt.date(2026, 12, 1), dt.date(2026, 12, 5))]


def test_instante_e_meia_noite_local_em_utc():
    corpo = pendencias.corpo_da_consulta(1, dt.date(2026, 10, 1),
                                         dt.date(2026, 10, 31))
    assert corpo["periodoInicial"].endswith(".000Z")
    assert corpo["periodoFinal"].endswith(".000Z")
    assert corpo["periodoInicial"] < corpo["periodoFinal"]


# ------------------------------------------ achados da revisão de dinheiro

def test_reembolso_agendado_para_a_loja_nao_sai_verde():
    e = entrada(50000, "Fulano Exemplo (reembolso de Vidracaria Modelo)")
    [li] = A.confrontar([e], [pendencia(500.0, "VIDRACARIA MODELO LTDA")])
    assert li.situacao == A.NOME_DIFERENTE


def test_reembolso_para_a_pessoa_certa_sai_verde():
    e = entrada(50000, "Fulano Exemplo (reembolso de Vidracaria Modelo)")
    [li] = A.confrontar([e], [pendencia(500.0, "FULANO EXEMPLO")])
    assert li.situacao == A.OK


def test_reembolso_sem_nome_nunca_sai_verde_pelo_nome():
    e = entrada(50000, "? (reembolso de Loja Exemplo)")
    [li] = A.confrontar([e], [pendencia(500.0, "LOJA EXEMPLO")])
    assert li.situacao == A.NOME_DIFERENTE


def test_palavra_generica_nao_prova_que_e_a_mesma_empresa():
    [li] = A.confrontar([entrada(100000, "Alfa Materiais")],
                        [pendencia(1000.0, "BETA MATERIAIS")])
    assert li.situacao == A.NOME_DIFERENTE


def test_nome_inteiro_igual_vale_mesmo_feito_de_palavras_genericas():
    [li] = A.confrontar([entrada(100000, "Vidracaria Silva")],
                        [pendencia(1000.0, "VIDRACARIA SILVA LTDA")])
    assert li.situacao == A.OK


def test_melhor_prova_ganha_e_nao_a_primeira_candidata():
    e1 = entrada(10000, "Alfa Materiais")
    e2 = entrada(10000, "Gama Materiais")
    linhas = A.confrontar([e1, e2], [pendencia(100.0, "GAMA MATERIAIS"),
                                      pendencia(100.0, "ZETA QUALQUER")])
    por_html = {li.html["favorecido"]: li.situacao for li in linhas}
    assert por_html == {"Gama Materiais": A.OK,
                        "Alfa Materiais": A.NOME_DIFERENTE}


def test_ja_pago_e_agendado_de_novo_e_vermelho():
    e = dict(entrada(80000), status="JÁ PAGO em 10/10/2026")
    [li] = A.confrontar([e], [pendencia(800.0)])
    assert li.situacao == A.PAGO_E_AGENDADO
    assert A.ESTADO[li.situacao] == "erro"


def test_ja_pago_sem_agendamento_nao_e_falta():
    e = dict(entrada(80000), status="JÁ PAGO em 10/10/2026")
    conf = A.Confronto("C", "1", linhas=A.confrontar([e], []))
    assert [li.situacao for li in conf.linhas] == [A.JA_PAGO]
    assert conf.pior == A.OK
    assert conf.total_html == 0


def test_linha_bloqueada_no_html_nunca_sai_verde():
    e = dict(entrada(30000), bloqueio="mesma linha digitável em 2 lançamentos")
    [li] = A.confrontar([e], [pendencia(300.0)])
    assert li.situacao == A.BLOQUEADO
    assert "mesma linha digitável" in li.frase


def test_prefixo_cortado_no_meio_do_numero_nao_casa():
    desc = "CC OBRA X QD 1 LT 2 OC 3001"
    [li] = A.confrontar([entrada(10000, "Fornecedor Exemplo", desc)],
                        [pendencia(100.0, "Observação: " + desc[:-1],
                                   observacao=desc[:-1])])
    assert li.situacao == A.NOME_DIFERENTE


def test_contas_do_erp_com_o_mesmo_numero_sao_conferidas_juntas():
    c1 = {"nome": "CONTA A - SICOOB", "entries": [entrada(100)]}
    c2 = {"nome": "CONTA B - SICOOB", "entries": [entrada(100)]}
    c3 = {"nome": "CONTA C - SICOOB", "entries": []}
    grupos = A.agrupar_por_numero([(c1, "12.345-6", ""), (c2, "12345-6", ""),
                                   (c3, "99.999-9", "")])
    assert [(n, num, len(ls)) for n, num, ls in grupos] == [
        ("CONTA A - SICOOB + CONTA B - SICOOB", "12.345-6", 2),
        ("CONTA C - SICOOB", "99.999-9", 0)]
    # Um agendamento só para as duas linhas: uma bate, a outra FALTA.
    linhas = A.confrontar(grupos[0][2], [pendencia(1.0)])
    assert sorted(li.situacao for li in linhas) == [A.FALTA_NO_BANCO, A.OK]


def test_conta_do_sicoob_nao_lida_e_falha_e_a_do_inter_nao():
    assert A.Confronto("C", "12.345-6", motivo=A.MOTIVO_NAO_LIDA).falhou
    assert not A.Confronto("C - INTER", "", motivo=A.MOTIVO_FORA_SICOOB).falhou


# ------------------------------------- segunda rodada da revisão de dinheiro

def test_um_prenome_comum_nao_prova_que_e_a_mesma_pessoa():
    [li] = A.confrontar([entrada(30000, "Maria Pereira")],
                        [pendencia(300.0, "MARIA MENDES")])
    assert li.situacao == A.NOME_DIFERENTE


def test_nome_maior_no_banco_nao_e_o_mesmo():
    for html, banco in (("Casa das Tintas", "NOVA CASA DAS TINTAS"),
                        ("Distribuidora de Materiais",
                         "BETA DISTRIBUIDORA DE MATERIAIS ELETRICOS"),
                        ("Joao Silva", "JOAO SILVA PEREIRA")):
        [li] = A.confrontar([entrada(1000, html)], [pendencia(10.0, banco)])
        assert li.situacao == A.NOME_DIFERENTE, (html, banco)


def test_uma_palavra_so_basta_quando_e_a_unica_propria_do_nome():
    [li] = A.confrontar([entrada(1000, "Reembolso Eng Zacarias")],
                        [pendencia(10.0, "11 222 333 ZACARIAS EXEMPLO")])
    assert li.situacao == A.OK
    [li] = A.confrontar([entrada(1000, "Alfa Beta")],
                        [pendencia(10.0, "ALFA GAMA")])
    assert li.situacao == A.NOME_DIFERENTE


def test_par_mais_provado_ganha_na_conta_inteira():
    e1 = entrada(1000, "Alfa")
    e2 = entrada(1000, "Alfa Beta")
    linhas = A.confrontar([e1, e2], [pendencia(10.0, "ALFA BETA"),
                                      pendencia(10.0, "GAMA DELTA")])
    por_html = {li.html["favorecido"]: (li.situacao, li.banco["detalhe"])
                for li in linhas}
    assert por_html["Alfa Beta"] == (A.OK, "ALFA BETA")
    assert por_html["Alfa"][0] == A.NOME_DIFERENTE


def test_descricao_curta_do_html_nao_casa_com_a_mais_longa_do_banco():
    curta = "OBRA EXEMPLO QD 1 LT 10"
    [li] = A.confrontar([entrada(1000, "Fornecedor Exemplo", curta)],
                        [pendencia(10.0, "Observação: " + curta + " E 11",
                                   observacao=curta + " E 11")])
    assert li.situacao == A.NOME_DIFERENTE


def test_observacao_curta_do_banco_so_com_o_centro_de_custo_nao_prova():
    longa = "RESIDENCIAL EXEMPLO QD 01 LT 05 NF 1234 OC 5678 cimento"
    [li] = A.confrontar([entrada(1000, "Fornecedor Exemplo", longa)],
                        [pendencia(10.0, "Observação: RESIDENCIAL EXEMPLO QD 01",
                                   observacao="RESIDENCIAL EXEMPLO QD 01")])
    assert li.situacao == A.NOME_DIFERENTE


def test_conta_do_sicoob_com_cadastro_torto_e_vermelha():
    assert A.Confronto("NOVA - SICOOB", "", motivo="conta não cadastrada").falhou
    assert not A.Confronto("X - INTER", "", motivo=A.MOTIVO_FORA_SICOOB).falhou


def test_ja_pago_nao_rouba_o_agendamento_da_linha_viva():
    paga = dict(entrada(50000, "Fornecedor Exemplo"), status="JÁ PAGO em 01/10")
    viva = entrada(50000, "Outro Fornecedor")
    linhas = A.confrontar([paga, viva], [pendencia(500.0, "TERCEIRO QUALQUER")])
    por = {li.html["favorecido"]: li.situacao for li in linhas}
    assert por == {"Fornecedor Exemplo": A.JA_PAGO,
                   "Outro Fornecedor": A.NOME_DIFERENTE}


def test_pendencia_que_nao_esta_pendente_nunca_sai_verde():
    p = dict(pendencia(10.0), situacao="CANCELADA")
    [li] = A.confrontar([entrada(1000)], [p])
    assert li.situacao == A.BLOQUEADO
    assert "CANCELADA" in li.frase


# -------------------------------------- terceira rodada da revisão de dinheiro

def test_pix_com_descricao_certa_e_recebedor_errado_nao_sai_verde():
    desc = "OBRA X QD 1 LT 2 OC 777 material"
    e = entrada(20000, "Fulano Exemplo", desc)
    p = dict(pendencia(200.0, "BELTRANO DE TAL", observacao=desc),
             nomeTransacao="Pagamento e Transferência Pix - via canal")
    [li] = A.confrontar([e], [p])
    assert li.situacao == A.NOME_DIFERENTE


def test_sigla_curta_diferente_nao_e_nome_igual():
    for html, banco in (("JL Materiais", "JR MATERIAIS"),
                        ("2 Irmaos Tintas", "3 IRMAOS TINTAS")):
        [li] = A.confrontar([entrada(1000, html)], [pendencia(10.0, banco)])
        assert li.situacao == A.NOME_DIFERENTE, (html, banco)


def test_empresa_com_uma_palavra_propria_nao_prova_por_ela():
    [li] = A.confrontar([entrada(1000, "Sao Jorge Materiais")],
                        [pendencia(10.0, "SAO BENTO TINTAS")])
    assert li.situacao == A.NOME_DIFERENTE
    [li] = A.confrontar([entrada(1000, "Zacarias Materiais")],
                        [pendencia(10.0, "ZACARIAS TINTAS")])
    assert li.situacao == A.NOME_DIFERENTE


def test_mei_com_numero_na_frente_prova_pelo_nome_unico():
    [li] = A.confrontar([entrada(1000, "Zacarias")],
                        [pendencia(10.0, "11 222 333 ZACARIAS EXEMPLO")])
    assert li.situacao == A.OK


def test_ja_pago_agendado_de_novo_nao_some_para_linha_viva_sem_prova():
    paga = dict(entrada(50000, "Fornecedor Exemplo"), status="JÁ PAGO em 01/10")
    viva = entrada(50000, "Outro Fornecedor")
    linhas = A.confrontar([viva, paga],
                          [pendencia(500.0, "FORNECEDOR EXEMPLO LTDA")])
    por = {li.html["favorecido"]: li.situacao for li in linhas}
    assert por == {"Fornecedor Exemplo": A.PAGO_E_AGENDADO,
                   "Outro Fornecedor": A.FALTA_NO_BANCO}


def test_convenio_com_observacao_crua_no_detalhe_casa_pela_descricao():
    desc = "OBRA X QD 01 LT 21 CERTIDAO 1234567890"
    [li] = A.confrontar([entrada(7700, "Orgao Exemplo", desc)],
                        [pendencia(77.0, desc, observacao=desc)])
    assert li.situacao == A.OK


def test_reembolso_com_nome_unico_casa_com_o_nome_completo_no_banco():
    e = entrada(10000, "ZACARIAS (reembolso de Loja Exemplo)")
    [li] = A.confrontar([e], [pendencia(100.0, "Zacarias Exemplo de Tal Filho")])
    assert li.situacao == A.OK


def test_nome_cortado_pelo_banco_no_fim_ainda_e_igual():
    [li] = A.confrontar([entrada(1000, "A B C DA SILVA EXEMPLO GESTAO IMOBILIARIA")],
                        [pendencia(10.0, "A B C DA SILVA EXEMPLO GESTAO IMOBILIARI")])
    assert li.situacao == A.OK
    # Corte curto demais (2 letras) não conta como o mesmo nome.
    [li] = A.confrontar([entrada(1000, "Alfa Beta")],
                        [pendencia(10.0, "ALFA BE")])
    assert li.situacao == A.NOME_DIFERENTE


def test_nome_curto_do_banco_nao_e_corte_de_nome_maior():
    [li] = A.confrontar([entrada(1000, "Zacarias Mariano")],
                        [pendencia(10.0, "ZACARIAS MARIA")])
    assert li.situacao == A.NOME_DIFERENTE


def test_pix_sem_detalhe_nao_vale_so_pela_descricao():
    desc = "OBRA X QD 1 LT 2 OC 888 material"
    [li] = A.confrontar([entrada(1000, "Fulano Exemplo", desc)],
                        [pendencia(10.0, "", observacao=desc)])
    assert li.situacao == A.NOME_DIFERENTE


# ------------------------------------- subconta fora do cadastro (21/10/2026)

def test_subconta_sicoob_fora_do_cadastro_confere_pelo_numero_da_pasta():
    destino = NS(erp="Holding X - SUBCONTA 12345-6 - FULANO - SICOOB",
                 empresa="HOLDING X", pasta="SUBCONTA - 12345-6 - FULANO - SICOOB",
                 banco="SICOOB", sufixo="")
    empresas = [NS(nome="HOLDING X", contas=[])]
    assert A.conta_sicoob(destino.erp, _mapa([destino]), empresas) == \
        ("12.345-6", "")


def test_conta_sicoob_sem_numero_no_nome_continua_fora_com_o_motivo():
    destino = NS(erp="HOLDING X - SICOOB", empresa="HOLDING X",
                 pasta="SICOOB", banco="SICOOB", sufixo="")
    numero, motivo = A.conta_sicoob(destino.erp, _mapa([destino]),
                                    [NS(nome="HOLDING X", contas=[])])
    assert numero == "" and motivo


def test_cadastro_ganha_do_numero_do_nome():
    destino = NS(erp="EMPRESA X - 99999-9 - SICOOB", empresa="EMPRESA X",
                 pasta="SICOOB", banco="SICOOB", sufixo="")
    empresas = [NS(nome="EMPRESA X", contas=[
        NS(numero="12.345-6", pasta="SICOOB", sufixo="")])]
    assert A.conta_sicoob(destino.erp, _mapa([destino]), empresas)[0] == \
        "12.345-6"


def test_conta_fora_do_mapa_que_se_diz_sicoob_confere_pelo_numero():
    assert A.conta_sicoob("NOVA - 54321-0 - SICOOB", _mapa([]), []) == \
        ("54.321-0", "")


def test_conta_de_outro_banco_com_numero_no_nome_continua_fora():
    assert A.conta_sicoob("EMPRESA Y BRADESCO 48147", _mapa([]), [])[0] == ""
    destino = NS(erp="EMPRESA Y - 12345-6 - INTER", empresa="EMPRESA Y",
                 pasta="INTER", banco="INTER", sufixo="")
    assert A.conta_sicoob(destino.erp, _mapa([destino]), [])[1] == \
        A.MOTIVO_FORA_SICOOB


def test_numero_no_nome_exige_um_so():
    assert A.numero_no_nome("SUBCONTA 55.696-3 - TB 21 QD 51 LT 40") == "55.696-3"
    assert A.numero_no_nome("TB 21 QD 51 LT 40") == ""
    assert A.numero_no_nome("12345-6 E 65432-1") == ""
    assert A.numero_no_nome("12345-6 / 12.345-6") == "12.345-6"
    assert A.numero_no_nome("LT 10-11") == ""


# --------------------------------------------- marcas de conferido (21/10)

def _conf(nome, entradas, pendencias_, motivo=""):
    c = A.Confronto(conta_erp=nome, numero="1", motivo=motivo)
    if not motivo:
        c.linhas = A.confrontar(entradas, pendencias_)
    return c


def test_resumao_conta_contas_totais_e_linhas_a_olhar():
    ok = _conf("A", [entrada(1000)], [pendencia(10.0)])
    dif = _conf("B", [entrada(2000), entrada(500, "Outro", "OBRA Y OC 9")],
                [pendencia(20.0)])
    nao = _conf("C", [], [], motivo=A.MOTIVO_NAO_LIDA)
    inter = _conf("D", [], [], motivo=A.MOTIVO_FORA_SICOOB)
    r = A.resumao([ok, dif, nao, inter], {})
    assert (r.contas_sicoob, r.lidas, r.batem, r.com_diferenca,
            r.nao_lidas, r.outro_banco) == (3, 2, 1, 1, 1, 1)
    assert r.total_html == A.Decimal("35.00")
    assert r.total_banco == A.Decimal("30.00")
    assert r.por_situacao == {A.FALTA_NO_BANCO: 1}
    assert (r.linhas_a_olhar, r.linhas_marcadas, r.contas_marcadas) == (1, 0, 0)


def test_marca_de_linha_e_de_conta_contam_no_resumao(tmp_path):
    dif = _conf("B", [entrada(500, "Outro", "OBRA Y OC 9")], [])
    [li] = dif.linhas
    marcas = {}
    assert A.alternar(marcas, A.chave_da_linha(dif, li), "eu", "agora")
    assert A.alternar(marcas, A.chave_da_conta(dif), "eu", "agora")
    caminho = A.caminho_das_marcas(tmp_path / "pagamentos_x.html")
    A.gravar_marcas(caminho, marcas)
    lidas = A.ler_marcas(caminho)
    r = A.resumao([dif], lidas)
    assert (r.linhas_marcadas, r.contas_marcadas) == (1, 1)
    assert A.linha_conferida(dif, li, lidas)
    assert not A.alternar(lidas, A.chave_da_conta(dif), "eu", "agora")


def test_marca_nao_passa_para_leitura_que_mudou():
    antes = _conf("B", [entrada(500)], [])
    marcas = {}
    A.alternar(marcas, A.chave_da_conta(antes), "eu", "agora")
    A.alternar(marcas, A.chave_da_linha(antes, antes.linhas[0]), "eu", "agora")
    depois = _conf("B", [entrada(500)], [pendencia(5.0, "OUTRO NOME")])
    assert not A.conta_conferida(depois, marcas)
    assert all(not A.linha_conferida(depois, li, marcas)
               for li in depois.linhas if A.precisa_olhar(li))


def test_arquivo_de_marcas_ausente_ou_torto_e_nada_marcado(tmp_path):
    assert A.ler_marcas(tmp_path / "nao_existe.json") == {}
    torto = tmp_path / "torto.json"
    torto.write_text("{nao é json", encoding="utf-8")
    assert A.ler_marcas(torto) == {}


def test_tem_erro_e_vermelho_ou_nao_lida():
    assert A.tem_erro(_conf("B", [entrada(500)], []))
    assert A.tem_erro(_conf("C", [], [], motivo=A.MOTIVO_NAO_LIDA))
    assert not A.tem_erro(_conf("A", [entrada(1000)], [pendencia(10.0)]))
    assert not A.tem_erro(_conf("D", [], [], motivo=A.MOTIVO_FORA_SICOOB))


def test_conta_de_outro_banco_fora_do_mapa_nao_e_sicoob_nao_conferido():
    numero, motivo = A.conta_sicoob("EMPRESA Y BRADESCO 48147", _mapa([]), [])
    assert (numero, motivo) == ("", A.MOTIVO_FORA_SICOOB)
    assert A.conta_sicoob("EMPRESA Z SEM BANCO", _mapa([]), [])[1] == \
        A.MOTIVO_CONTA_DESCONHECIDA
