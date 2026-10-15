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
    # O caso de 15/10: boleto agendado com R$ 0,00, observação idêntica.
    desc = "CONDOMINIO EXEMPLO Constituicao do CNPJ"
    linhas = A.confrontar(
        [entrada(467500, "Escritorio Contabil Exemplo", desc)],
        [pendencia(0.0, f"Observação: {desc}", observacao=desc)])
    assert [li.situacao for li in linhas] == [A.VALOR_DIVERGE]
    assert linhas[0].valor_html == A.Decimal("4675.00")
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


def test_periodo_vai_do_dia_1_ao_fim_do_mes_seguinte():
    assert A.periodo_da_consulta(dt.date(2026, 10, 15)) == (
        dt.date(2026, 10, 1), dt.date(2026, 11, 30))
    assert A.periodo_da_consulta(dt.date(2026, 12, 31)) == (
        dt.date(2026, 12, 1), dt.date(2027, 1, 31))


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
