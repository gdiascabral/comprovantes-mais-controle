# -*- coding: utf-8 -*-
"""Entrega 5 (A): um lançamento pago com N boletos. Dados fictícios — o repo é público."""
import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

from pagamentos_dia import boletos_somados as bs
from pagamentos_dia import confirmacao, ocr_boleto, relatorio

DIA = date(2026, 10, 21)
CONTA = "CONTA EXEMPLO - SICOOB"
RAIZ = Path(__file__).resolve().parents[1]
OUTRO_LIVRE = "2680800035545486352881211"
#: O título inteiro lido no ERP (tarefa 3): uma parcela só.
UMA_PARCELA = {"T1": {"numberOfInstallments": 1}}


def gera_linha(valor_centavos, fator=9999, livre=None):
    """Linha digitável bancária com os DVs fechando (a de tests/test_casamento_html.py).

    Sem `livre`, o campo livre (o "nosso número" do banco) sai do valor: dois
    boletos de valores diferentes são duas dívidas; o mesmo valor com outro
    `fator` é a 2ª via do mesmo boleto."""
    livre = livre or ("157070002443437524" + f"{valor_centavos:07d}")
    b43 ="3419" + f"{fator:04d}" + f"{valor_centavos:010d}" + livre
    b = b43[:4] + str(ocr_boleto._mod11_geral(b43)) + b43[4:]
    campos = [b[0:4] + b[19:24], b[24:34], b[34:44]]
    c = [x + str(ocr_boleto._mod10(x)) for x in campos]
    linha = (f"{c[0][:5]}.{c[0][5:]} {c[1][:5]}.{c[1][5:]} "
             f"{c[2][:5]}.{c[2][5:]} {b[4]} {b[5:19]}")
    assert ocr_boleto.valida(linha)
    return linha


def _anexo(nome, url):
    return {"filename": nome, "tagName": "Boleto", "extension": ".pdf", "downloadUrl": url}


def _item(**extra):
    base = {"id": "L1", "tradePayableId": "T1", "paidTo": "Fornecedor Modelo Ltda",
            "remainingValue": 1000.0, "plannedDate": "2026-10-21", "paid": False,
            "tradePayableAccount": {"name": CONTA}, "tradePayablePaymentMethod": "Boleto",
            "documentNumber": "64000", "costCentreDetails": [{"workName": "OBRA MODELO"}]}
    base.update(extra)
    return base


def _linhas_dos_boletos(valores_centavos, livres=None):
    livres = livres or [None] * len(valores_centavos)
    return [gera_linha(v, livre=l) if l else gera_linha(v)
            for v, l in zip(valores_centavos, livres)]


def _entradas(itens, valores_centavos, livres=None, **k):
    linhas = _linhas_dos_boletos(valores_centavos, livres)
    anexos = {"T1": [_anexo(f"boleto {i}", f"u{i}") for i in range(1, len(linhas) + 1)]}
    textos = {f"u{i}": f"Banco Exemplo\n{ln}\n" for i, ln in enumerate(linhas, 1)}
    return confirmacao.Entradas(
        selecionados=itens, anexos=anexos, overviews={}, textos=textos, urls_ocr=set(),
        cadastro_reembolso=None, regras_fornecedor={}, participantes={},
        periodo=(DIA, DIA), **k)


def _linhas(resultado):
    return [r for regs in resultado.contas.values() for r in regs]


# ------------------------------------------------------ o caso de hoje
def test_dois_boletos_que_somam_o_lancamento_viram_uma_linha_de_varios_boletos():
    """O caso real: 400 + 600 anexados a um lançamento de 1.000. Hoje nenhuma
    linha tem o valor do lançamento e a linha sai sem dado de pagamento."""
    (linha,) = _linhas(confirmacao.remontar(_entradas([_item()], [40000, 60000])))
    assert linha["status"] == "ATENÇÃO — vários boletos no título"
    assert linha["dados"] == ""
    assert linha["obs"].split(" · ")[0] == ("Há 2 boletos no título, não dá para saber "
                                            "qual é desta parcela — conferir antes de pagar")


def test_o_frame_da_remessa_nunca_liga_a_divisao():
    """Guarda: a Remessa/Retorno monta as Entradas dela sem a chave nova."""
    arvore = ast.parse((RAIZ / "pagamentos_dia/pagamentos_frame.py").read_text(encoding="utf-8"))
    assert not [kw for no in ast.walk(arvore) if isinstance(no, ast.Call)
                for kw in no.keywords if kw.arg == "dividir_boletos"]


# ------------------------------------------------------ a divisão (tarefa 2)
def _dividido(valores, itens=None, livres=None):
    itens = itens or [_item()]
    entradas = _entradas(itens, valores, livres)
    base = relatorio.montar_registros(entradas.selecionados, entradas.anexos, {}, entradas.textos)
    return base, bs.dividir(base, entradas, titulos_erp=UMA_PARCELA)


def test_o_status_que_dispara_e_o_do_relatorio():
    (linha,) = _linhas(confirmacao.remontar(_entradas([_item()], [40000, 60000])))
    assert linha["status"] == bs.STATUS_VARIOS
    assert bs._OBS_VARIOS.fullmatch(linha["obs"].split(" · ")[0])


def test_boletos_que_somam_exato_viram_n_linhas():
    base, res = _dividido([40000, 60000])
    linhas = _linhas(res)
    assert [r["parte"] for r in linhas] == ["1/2", "2/2"]
    valores = [Decimal(str(r["valor"])) for r in linhas]
    assert sorted(valores) == [Decimal("400.00"), Decimal("600.00")]
    assert sum(valores) == Decimal("1000.00")
    assert {ocr_boleto.valor_da_linha(r["dados"]) for r in linhas} == {400.0, 600.0}
    assert all(r["status"] == bs.status_dividido(2) for r in linhas)
    assert all(r["id"] == "L1" for r in linhas)                   # o lançamento é o mesmo
    assert linhas[0]["descricao"] == linhas[1]["descricao"]       # o Anexar casa pela descrição
    assert not any(bs._OBS_VARIOS.fullmatch(p) for r in linhas for p in r["obs"].split(" · "))
    assert _linhas(base)[0]["dados"] == ""                        # o Resultado original não muda


def test_tres_boletos_que_somam_exato():
    _base, res = _dividido([20000, 30000, 50000])
    assert [r["parte"] for r in _linhas(res)] == ["1/3", "2/3", "3/3"]


def test_soma_que_nao_bate_ao_centavo_nao_divide_e_avisa():
    _base, res = _dividido([40000, 59999])
    (linha,) = _linhas(res)
    assert linha["status"] == bs.STATUS_VARIOS and linha["dados"] == ""
    assert "somam R$ 999,99" in linha["obs"] and "R$ 1.000,00" in linha["obs"]
    assert "não dividi" in bs.avisos(res)[0]


def test_parcelas_abertas_do_mesmo_titulo_nao_dividem():
    _base, res = _dividido([40000, 60000], itens=[_item(id="L1"), _item(id="L2")])
    assert [r["status"] for r in _linhas(res)] == [bs.STATUS_VARIOS] * 2
    assert all("2 parcelas em aberto" in r["obs"] for r in _linhas(res))


def test_titulo_com_pagamento_anterior_nao_divide():
    _base, res = _dividido([40000, 60000], itens=[_item(sumOfPaidValues=200.0)])
    (linha,) = _linhas(res)
    assert linha["status"] == bs.STATUS_VARIOS and "já tem pagamento" in linha["obs"]


def test_linha_que_nao_e_de_varios_boletos_passa_intacta():
    entradas = _entradas([_item(remainingValue=400.0)], [40000])
    base = relatorio.montar_registros(entradas.selecionados, entradas.anexos, {}, entradas.textos)
    assert bs.dividir(base, entradas).contas == base.contas


def test_avisos_dizem_que_o_lancamento_virou_n_boletos():
    _base, res = _dividido([40000, 60000])
    assert bs.avisos(res) == [
        "1 lançamento virou 2 boletos (somam exato) — conferir: Fornecedor Modelo Ltda, "
        f"R$ 1.000,00 ({CONTA})"]


# ------------------------------------------------------ conserto, rodada 1
def gera_arrecadacao(valor_centavos, ident="8"):
    """Ficha de arrecadação (48) com os DVs de bloco fechando. `ident` é o 3º
    dígito: 6/7 = valor efetivo, 8/9 = valor de referência."""
    modulo = ocr_boleto._mod11_arrecadacao if ident in "89" else ocr_boleto._mod10
    sem_dv = "81" + ident + f"{valor_centavos:011d}" + "0001" + "2026102100000000000000077"
    b = sem_dv[:3] + str(modulo(sem_dv)) + sem_dv[3:]
    blocos = [b[i:i + 11] for i in range(0, 44, 11)]
    linha = " ".join(f"{x}-{modulo(x)}" for x in blocos)
    assert ocr_boleto.valida(linha), linha
    return linha


def _entradas_de(itens, linhas, nomes=None, extras=(), overviews=None, **k):
    """Como `_entradas`, mas com as linhas prontas (2ª via, arrecadação) e
    anexos a mais `(anexo, texto)`."""
    nomes = nomes or [f"boleto {i}" for i in range(1, len(linhas) + 1)]
    anexos = [_anexo(n, f"u-{n}") for n in nomes]
    textos = {f"u-{n}": f"Banco Exemplo\n{ln}\n" for n, ln in zip(nomes, linhas)}
    for anexo, texto in extras:
        anexos.append(anexo)
        textos[anexo["downloadUrl"]] = texto
    return confirmacao.Entradas(
        selecionados=itens, anexos={"T1": anexos}, overviews=overviews or {},
        textos=textos, urls_ocr=set(), cadastro_reembolso=None, regras_fornecedor={},
        participantes={}, periodo=(DIA, DIA), **k)


def _dividir(entradas):
    base = relatorio.montar_registros(entradas.selecionados, entradas.anexos, {},
                                      entradas.textos)
    return [r for r in _linhas(bs.dividir(base, entradas, titulos_erp=UMA_PARCELA))
            if r["id"] == "L1"]


def _nao_dividiu(linhas, trecho):
    (linha,) = linhas
    assert linha["status"] == bs.STATUS_VARIOS and linha["dados"] == ""
    assert "parte" not in linha
    assert trecho in linha["obs"], linha["obs"]
    return linha


# 1. segunda via
def test_segunda_via_do_mesmo_boleto_nao_divide():
    """A e a 2ª via de A (mesmo campo livre, outro vencimento) são a MESMA
    dívida: somar as duas dá o lançamento por acaso."""
    a = gera_linha(40000, fator=9990)
    a2 = gera_linha(40000, fator=9999)
    _nao_dividiu(_dividir(_entradas_de([_item(remainingValue=800.0)], [a, a2])),
                 "segunda via")


def test_valores_iguais_com_campo_livre_diferente_dividem():
    linhas = [gera_linha(50000), gera_linha(50000, livre=OUTRO_LIVRE)]
    partes = _dividir(_entradas_de([_item()], linhas))
    assert [r["parte"] for r in partes] == ["1/2", "2/2"]


# 2. parcelas fora do período
def test_titulo_com_mais_parcelas_no_erp_nao_divide():
    linhas = [gera_linha(40000), gera_linha(60000)]
    _nao_dividiu(_dividir(_entradas_de([_item(numberOfInstallments=3)], linhas)),
                 "3 parcelas")


def test_lista_de_parcelas_do_titulo_com_outra_em_aberto_nao_divide():
    linhas = [gera_linha(40000), gera_linha(60000)]
    item = _item(installments=[{"id": "L1", "paid": False}, {"id": "L9", "paid": False}])
    _nao_dividiu(_dividir(_entradas_de([item], linhas)), "2 parcelas")


def test_parcelas_vindas_do_overview_tambem_contam():
    linhas = [gera_linha(40000), gera_linha(60000)]
    _nao_dividiu(_dividir(_entradas_de([_item()], linhas,
                                       overviews={"L1": {"numberOfInstallments": 2}})),
                 "2 parcelas")


def test_valor_do_titulo_maior_que_o_lancamento_nao_divide():
    linhas = [gera_linha(40000), gera_linha(60000)]
    _nao_dividiu(_dividir(_entradas_de([_item(totalValue=2000.0)], linhas)),
                 "R$ 2.000,00")


def test_outra_parcela_ja_paga_do_mesmo_titulo_na_lista_nao_divide():
    linhas = [gera_linha(40000), gera_linha(60000)]
    itens = [_item(), _item(id="L0", paid=True, remainingValue=0.0, sumOfPaidValues=500.0)]
    _nao_dividiu(_dividir(_entradas_de(itens, linhas)), "outra parcela")


def test_uma_parcela_declarada_divide():
    linhas = [gera_linha(40000), gera_linha(60000)]
    item = _item(numberOfInstallments=1, totalValue=1000.0,
                 installments=[{"id": "L1", "paid": False}])
    assert len(_dividir(_entradas_de([item], linhas))) == 2


# 3. ordem estável
def test_ordem_das_partes_nao_depende_da_ordem_dos_anexos():
    linhas = [gera_linha(40000), gera_linha(60000)]
    ida = _dividir(_entradas_de([_item()], linhas, nomes=["a.pdf", "b.pdf"]))
    volta = _dividir(_entradas_de([_item()], linhas[::-1], nomes=["b.pdf", "a.pdf"]))
    chave = lambda rs: {r["parte_linha"]: (r["parte"], r["anexo_parte"]) for r in rs}  # noqa: E731
    assert chave(ida) == chave(volta)
    assert [r["parte_linha"] for r in ida] == sorted(ocr_boleto.digitos(x) for x in linhas)
    assert {r["anexo_parte"] for r in ida} == {"a.pdf", "b.pdf"}


# 4. conjunto inteiro
def test_anexo_nao_lido_no_titulo_nao_divide():
    linhas = [gera_linha(40000), gera_linha(60000)]
    _nao_dividiu(_dividir(_entradas_de([_item()], linhas,
                                       anexos_nao_lidos={"u-boleto 2"})), "não foi lido")


def test_titulo_cuja_lista_de_anexos_nao_veio_nao_divide():
    linhas = [gera_linha(40000), gera_linha(60000)]
    _nao_dividiu(_dividir(_entradas_de([_item()], linhas, titulos_nao_lidos={"T1"})),
                 "não foi lido")


def test_pdf_de_boleto_sem_linha_valida_nao_divide():
    linhas = [gera_linha(40000), gera_linha(60000)]
    extra = (_anexo("boleto 3", "u-sem-linha"), "Banco Exemplo\nboleto ilegivel\n")
    _nao_dividiu(_dividir(_entradas_de([_item()], linhas, extras=[extra])),
                 "sem linha")


# 5. arrecadação com valor de referência
def test_arrecadacao_com_valor_de_referencia_nao_divide():
    linhas = [gera_linha(40000), gera_arrecadacao(60000, ident="8")]
    _nao_dividiu(_dividir(_entradas_de([_item()], linhas)), "valor de referência")


# 6. os que faltavam
def _registro_varios(**extra):
    entradas = _entradas([_item()], [40000, 60000])
    (reg,) = _linhas(relatorio.montar_registros(entradas.selecionados, entradas.anexos,
                                                {}, entradas.textos))
    return {**reg, **extra}, entradas


def test_registro_parcial_nao_divide():
    reg, e = _registro_varios(parcial=True)
    assert bs.decidir(reg, _item(), e.anexos["T1"], e.textos) == bs.Decisao()


def test_boleto_de_valor_zero_nao_divide():
    linhas = [gera_linha(40000), gera_linha(60000), gera_linha(0, livre=OUTRO_LIVRE)]
    _nao_dividiu(_dividir(_entradas_de([_item()], linhas)), "não diz o valor")


def test_mesma_linha_em_dois_anexos_conta_uma_vez():
    """500 anexado duas vezes num lançamento de 1.000: é UM boleto, não dois."""
    ln = gera_linha(50000)
    linhas = _dividir(_entradas_de([_item()], [ln, ln]))
    assert len(linhas) == 1 and "parte" not in linhas[0]


def test_obs_vazia_nao_quebra():
    reg, e = _registro_varios(obs=None)
    d = bs.decidir(reg, _item(), e.anexos["T1"], e.textos,
                   titulo_erp=UMA_PARCELA["T1"])
    partes = bs._partes_do_registro(reg, d)
    assert len(partes) == 2 and all(p["obs"] for p in partes)
    assert bs._obs_sem_a_frase(None) == []


# ------------------------------------------------------ conserto, rodada 2
def test_sem_saber_as_parcelas_do_titulo_nao_divide():
    """Decisão do coordenador: sem número de parcelas nem valor do título, não
    se sabe se há outra parcela fora do período — não divide."""
    entradas = _entradas([_item()], [40000, 60000])
    base = relatorio.montar_registros(entradas.selecionados, entradas.anexos, {},
                                      entradas.textos)
    (linha,) = _linhas(bs.dividir(base, entradas))
    assert linha["status"] == bs.STATUS_VARIOS and "parte" not in linha
    assert "não sei se o título tem outras parcelas — não dividi" in linha["obs"]
    assert "não sei se o título tem outras parcelas" in bs.avisos(
        bs.dividir(base, entradas))[0]


def test_titulo_lido_no_erp_com_uma_parcela_e_valor_igual_divide():
    entradas = _entradas([_item()], [40000, 60000])
    base = relatorio.montar_registros(entradas.selecionados, entradas.anexos, {},
                                      entradas.textos)
    titulo = {"T1": {"numberOfInstallments": 1, "totalValue": 1000.0}}
    linhas = _linhas(bs.dividir(base, entradas, titulos_erp=titulo))
    assert [r["parte"] for r in linhas] == ["1/2", "2/2"]


def test_titulo_lido_no_erp_com_mais_parcelas_nao_divide():
    entradas = _entradas([_item()], [40000, 60000])
    base = relatorio.montar_registros(entradas.selecionados, entradas.anexos, {},
                                      entradas.textos)
    titulo = {"T1": {"numberOfInstallments": 2}}
    (linha,) = _linhas(bs.dividir(base, entradas, titulos_erp=titulo))
    assert "2 parcelas no ERP" in linha["obs"]
