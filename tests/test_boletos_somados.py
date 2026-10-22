# -*- coding: utf-8 -*-
"""Entrega 5 (A): um lançamento pago com N boletos. Dados fictícios — o repo é público."""
import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

from pagamentos_dia import boletos_somados as bs
from pagamentos_dia import confirmacao, ocr_boleto, relatorio, remessa_dia
from pagamentos_dia import leitura_do_dia as ld
from tela_do_dia import conferencia as tdc
from tela_do_dia import geracao

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


# ------------------------------------------------------ tarefa 3: só a tela nova divide
def test_campo_livre_e_a_fatia_do_codigo_de_barras():
    """Pina o slice: o campo livre lido de volta é o mesmo que gerou a linha."""
    assert bs._campo_livre(gera_linha(40000, livre=OUTRO_LIVRE)) == OUTRO_LIVRE
    assert bs._campo_livre(gera_linha(40000)) == "157070002443437524" + "0040000"


def test_entradas_nascem_sem_dividir_e_o_remontar_de_sempre_fica(monkeypatch):
    entradas = _entradas([_item()], [40000, 60000], titulos_erp=UMA_PARCELA)
    assert entradas.dividir_boletos is False

    def _nao(*_a, **_k):
        raise AssertionError("a Remessa não divide")
    monkeypatch.setattr(confirmacao.boletos_somados, "dividir", _nao)
    assert [r["status"] for r in _linhas(confirmacao.remontar(entradas))] == [bs.STATUS_VARIOS]


def test_com_a_chave_e_o_titulo_lido_o_remontar_divide():
    entradas = _entradas([_item()], [40000, 60000], dividir_boletos=True,
                         titulos_erp=UMA_PARCELA)
    assert [r["parte"] for r in _linhas(confirmacao.remontar(entradas))] == ["1/2", "2/2"]


def test_com_a_chave_mas_sem_o_titulo_lido_nao_divide():
    entradas = _entradas([_item()], [40000, 60000], dividir_boletos=True)
    (linha,) = _linhas(confirmacao.remontar(entradas))
    assert "parte" not in linha and bs.NAO_SEI_AS_PARCELAS in linha["obs"]


def test_desmarcar_o_lancamento_tira_as_n_linhas():
    entradas = _entradas([_item()], [40000, 60000], dividir_boletos=True,
                         titulos_erp=UMA_PARCELA)
    res = confirmacao.remontar(entradas, {"L1"})
    assert _linhas(res) == [] and [o["id"] for o in res.omitidos] == ["L1"]


def test_o_remontar_dividido_continua_passando_os_liberados(monkeypatch):
    """Achado 4: a divisão vem DEPOIS do `montar_registros`, que ainda recebe
    `ids_liberados`."""
    real, visto = relatorio.montar_registros, {}

    def espiao(*a, **k):
        visto.update(k)
        return real(*a, **k)
    monkeypatch.setattr(confirmacao.relatorio, "montar_registros", espiao)
    entradas = _entradas([_item()], [40000, 60000], dividir_boletos=True,
                         titulos_erp=UMA_PARCELA)
    res = confirmacao.remontar(entradas, ids_liberados={"L9"})
    assert visto["ids_liberados"] == {"L9"}
    assert len(_linhas(res)) == 2


def _cand(ident, codigo="", impedimento=""):
    return remessa_dia.Candidato(id=ident, conta_erp=CONTA, tipo="Boleto", valor=1.0,
                                 favorecido="F", descricao="D", status="APTO",
                                 codigo_barras=codigo, impedimento=impedimento)


def test_candidato_sem_parte_e_o_primeiro_de_sempre():
    a, b, c = _cand("1"), _cand("2"), _cand("2")
    analise = confirmacao.AnaliseRemessa(preparado={CONTA: [a, b, c]})
    assert analise.candidato(CONTA, "2") is b
    assert analise.candidato(CONTA, "") is None and analise.candidato(CONTA, "3") is None


def test_candidato_da_parte_e_pela_linha_e_nao_pela_posicao():
    l4, l6 = gera_linha(40000), gera_linha(60000)
    c4 = _cand("L1", ocr_boleto.codigo_de_barras(l4))
    c6 = _cand("L1", ocr_boleto.codigo_de_barras(l6))
    analise = confirmacao.AnaliseRemessa(preparado={CONTA: [c6, c4]})   # fora de ordem
    assert analise.candidato(CONTA, "L1", parte_linha=ocr_boleto.digitos(l4)) is c4
    assert analise.candidato(CONTA, "L1", parte_linha=ocr_boleto.digitos(l6)) is c6
    assert analise.candidato(CONTA, "L1", parte_linha=ocr_boleto.digitos(
        gera_linha(12345))) is None


def test_candidato_da_parte_impedida_so_com_o_mesmo_impedimento():
    """Impedida, o Candidato não tem código de barras: só serve o impedimento,
    e só quando todas as partes dizem o mesmo."""
    linha = ocr_boleto.digitos(gera_linha(40000))
    a, b = _cand("L1", impedimento="pagar à mão"), _cand("L1", impedimento="pagar à mão")
    assert confirmacao.AnaliseRemessa(preparado={CONTA: [a, b]}).candidato(
        CONTA, "L1", parte_linha=linha) is a
    c = _cand("L1", impedimento="outro motivo")
    assert confirmacao.AnaliseRemessa(preparado={CONTA: [a, c]}).candidato(
        CONTA, "L1", parte_linha=linha) is None


class _ApiDoDia:
    """O mínimo que `ler_pagamentos` chama (formato de tests/test_leitura_do_dia.py),
    mais o GET do título (`_base_legacy` + `_fetch_json`)."""
    _req_anexos = ("https://exemplo.invalid/attachments/v2", {"authorization": "x"})
    titulos_sem_leitura = ()

    def __init__(self, itens, anexos, arquivos, titulos=None):
        self._itens, self._anexos, self._arquivos = itens, anexos, arquivos
        self._titulos = {"T1": {"numberOfInstallments": 1}} if titulos is None else titulos
        self.lidos = []

    def capturar_credenciais(self, log=print):
        return True

    def capturar_credenciais_anexos(self, launch_id):
        return True

    def listar_a_pagar(self, ini, fim, log=print):
        return list(self._itens)

    def anexos_de_titulos(self, ids, log=print, progresso=None, cancelar=None):
        return {i: self._anexos.get(i, []) for i in ids}

    def listar_overviews(self, ids, log=print, progresso=None, cancelar=None):
        return {i: {} for i in ids}

    def listar_participantes(self, log=print):
        return {}

    def baixar_anexo(self, url):
        return self._arquivos[url]

    def _base_legacy(self, caminho):
        return f"https://exemplo.invalid/legacy/{caminho}", {"authorization": "x"}

    def _fetch_json(self, url, headers):
        self.lidos.append(url)
        r = self._titulos.get(url.rsplit("/", 1)[1])
        if isinstance(r, Exception):
            raise r
        return r


def _sem(*_a):
    raise RuntimeError("sem nuvem/cadastro no teste")


def _ler_o_dia(valores, titulos=None, log=print):
    linhas = _linhas_dos_boletos(valores)
    anexos = {"T1": [_anexo(f"boleto {i}", f"u{i}") for i in range(1, len(linhas) + 1)]}
    arquivos = {f"u{i}": f"Banco Exemplo\n{ln}\n".encode("utf-8")
                for i, ln in enumerate(linhas, 1)}
    api = _ApiDoDia([_item()], anexos, arquivos, titulos)
    leitura = ld.ler_pagamentos(
        api, DIA, DIA,
        abrir_historico=_sem, carregar_mapas=_sem, ler_qr=lambda d, pdf: [],
        texto_pdf=lambda d: d.decode("utf-8"), ocr_pdf=lambda d, log=print: "",
        ocr_imagem=lambda d: "", log=log)
    return leitura, linhas, api


def test_a_leitura_do_dia_divide_e_cada_linha_tem_o_seu_candidato():
    leitura, linhas, api = _ler_o_dia([40000, 60000])
    assert leitura.entradas.dividir_boletos is True
    assert api.lidos == ["https://exemplo.invalid/legacy/trade-payables/T1"]
    entram = [ln for g in leitura.grupos for ln in g.entram]
    assert sorted(ln.valor for ln in entram) == [400.0, 600.0]
    for ln in entram:   # cada linha com o candidato do SEU boleto
        assert ocr_boleto.valor_da_linha(ln.dados) == ln.valor
        assert ln.candidato.codigo_barras == ocr_boleto.codigo_de_barras(ln.dados)
    assert {ln.candidato.codigo_barras for ln in entram} == {
        ocr_boleto.codigo_de_barras(x) for x in linhas}
    assert all(bs.status_dividido(2) in ln.situacao for ln in entram)
    assert any("1 lançamento virou 2 boletos" in a for a in leitura.avisos)


def test_a_leitura_do_dia_so_le_o_titulo_de_quem_e_candidato():
    """Lançamento de um boleto só (não é 'vários boletos'): nenhum GET a mais."""
    leitura, _l, api = _ler_o_dia([100000])
    assert api.lidos == []
    assert [ln.valor for g in leitura.grupos for ln in g.entram] == [1000.0]


def test_leitura_do_titulo_que_falha_nao_divide_e_avisa_no_log():
    for falha in ({"__erro": 500}, {}, None, RuntimeError("caiu")):
        log = []
        leitura, _l, _api = _ler_o_dia([40000, 60000], titulos={"T1": falha},
                                       log=log.append)
        regs = _linhas(leitura.resultado)
        assert len(regs) == 1 and "parte" not in regs[0], falha
        assert bs.NAO_SEI_AS_PARCELAS in regs[0]["obs"]
        assert any("T1" in str(m) and "não li o título" in str(m) for m in log), falha


def test_o_que_a_remessa_recebe_da_tela_nova_tem_as_n_linhas():
    """Achado 6: a tela manda `geracao.para_a_remessa(resultado_da_tela(...))`."""
    leitura, _l, _api = _ler_o_dia([40000, 60000])
    res = geracao.para_a_remessa(geracao.resultado_da_tela(
        leitura.entradas, leitura.grupos, tdc.Conferencia()))
    assert sorted(r["valor"] for r in _linhas(res)) == [400.0, 600.0]


def test_so_a_leitura_do_dia_liga_a_divisao():
    arvore = ast.parse((RAIZ / "pagamentos_dia/leitura_do_dia.py").read_text(encoding="utf-8"))
    (kw,) = [kw for no in ast.walk(arvore) if isinstance(no, ast.Call)
             for kw in no.keywords if kw.arg == "dividir_boletos"]
    assert isinstance(kw.value, ast.Constant) and kw.value.value is True
    for pasta in ("pagamentos_dia", "tela_do_dia", "anexar"):
        for caminho in (RAIZ / pasta).glob("*.py"):
            if caminho.name == "leitura_do_dia.py":
                continue
            assert "dividir_boletos=True" not in caminho.read_text(encoding="utf-8"), caminho


def test_a_remessa_nao_le_o_titulo_no_erp():
    """O caminho da Remessa/Retorno não ganha leitura nenhuma do ERP."""
    texto = (RAIZ / "pagamentos_dia/pagamentos_frame.py").read_text(encoding="utf-8")
    assert "titulo_no_erp" not in texto and "titulos_erp" not in texto
    assert "trade-payables/" not in texto


# ------------------------------------------- HTML e remessa da tela nova (E5-T4)
from pagamentos_dia import html_pagamentos as hp  # noqa: E402


def _a_mao_com_link(res):
    """Um pagamento à mão com link para o MESMO lançamento (id "<lançamento>#mao:1")."""
    mao = dict(_linhas(res)[0])
    for k in ("parte", "parte_linha", "anexo_parte", "valor_do_lancamento"):
        mao.pop(k, None)
    mao["a_mao"] = "mao:1"
    return mao


def test_html_separa_as_partes_pela_linha_e_mantem_o_link_do_lancamento():
    _base, res = _dividido([40000, 60000])
    entradas = [e for c in hp.contas_do_html_geral(res) for e in c["entries"]]
    esperado = {"L1#" + r["parte_linha"] for r in _linhas(res)}
    assert {e["id"] for e in entradas} == esperado and len(entradas) == 2
    assert {e["link"] for e in entradas} == {hp.URL_LANCAMENTO + "L1"}
    assert not any("mesma linha digitável" in e["bloqueio"] for e in entradas)
    assert all(e["bloqueio"] for e in entradas)                          # ATENÇÃO: conferir


def test_id_da_parte_nao_depende_da_posicao_na_lista():
    _base, res = _dividido([40000, 60000])
    antes = {e["id"] for c in hp.contas_do_html_geral(res) for e in c["entries"]}
    res.contas[CONTA].reverse()
    depois = [e["id"] for c in hp.contas_do_html_geral(res) for e in c["entries"]]
    assert set(depois) == antes


def test_partes_e_a_mao_com_link_do_mesmo_lancamento_nao_colidem():
    _base, res = _dividido([40000, 60000])
    res.contas[CONTA].append(_a_mao_com_link(res))
    ids = [e["id"] for c in hp.contas_do_html_geral(res) for e in c["entries"]]
    assert len(ids) == 3 and len(set(ids)) == 3
    assert "L1#mao:1" in ids


def test_html_de_linha_sem_parte_continua_com_o_id_do_lancamento():
    base, _res = _dividido([40000, 60000])
    assert [e["id"] for c in hp.contas_do_html_geral(base) for e in c["entries"]] == ["L1"]


def test_html_da_parte_sem_parte_linha_usa_k_de_n():
    _base, res = _dividido([40000, 60000])
    for r in _linhas(res):
        r.pop("parte_linha")
    ids = [e["id"] for c in hp.contas_do_html_geral(res) for e in c["entries"]]
    assert ids == ["L1#1/2", "L1#2/2"]


def test_remessa_da_tela_nova_leva_as_n_linhas_com_seus_numeros_proprios():
    _base, res = _dividido([40000, 60000])
    cands = remessa_dia.preparar(res.contas, {}, quando=DIA)[CONTA]
    assert len(cands) == 2 and len({c.seu_numero for c in cands}) == 2
    assert len({c.codigo_barras for c in cands}) == 2
    assert all(c.id == "L1" and c.pode and not c.marcado for c in cands)   # nasce desmarcada
    assert sorted(c.valor for c in cands) == [400.0, 600.0]
    # a soma das partes é o valor do lançamento
    assert round(sum(c.valor for c in cands), 2) == 1000.0
    for c in cands:
        c.marcado = True
    assert set(remessa_dia.referencias(cands).values()) == {"L1"}


def test_descricao_de_colar_e_a_mesma_nas_partes():
    _base, res = _dividido([40000, 60000])
    a, b = _linhas(res)
    assert hp.descricao_para_colar(a, CONTA) == hp.descricao_para_colar(b, CONTA)
    assert "OBRA MODELO" in hp.descricao_para_colar(a, CONTA)


def test_a_aba_remessa_montando_a_propria_leitura_segue_com_uma_linha():
    """(d) Sem `dividir_boletos` (o que a aba Remessa/Retorno monta) o HTML e a
    remessa levam UMA linha "vários boletos", com o id do lançamento."""
    res = confirmacao.remontar(_entradas([_item()], [40000, 60000]))
    assert [r.get("parte") for r in _linhas(res)] == [None]
    assert [e["id"] for c in hp.contas_do_html_geral(res) for e in c["entries"]] == ["L1"]


def test_partes_do_mesmo_lancamento_com_chave_extra_herdada_nao_sao_repeticao():
    _base, res = _dividido([40000, 60000])
    for r in _linhas(res):
        r["pix_qr"] = "00020126580014br.gov.bcb.pix0136chave-modelo"
        r["linha_da_guia"] = gera_linha(12345)
    entradas = [e for c in hp.contas_do_html_geral(res) for e in c["entries"]]
    assert len(entradas) == 2
    assert not any("mesma linha digitável" in e["bloqueio"] for e in entradas)
    assert all("_lancamento" not in e for e in entradas)


def test_dois_lancamentos_diferentes_com_a_mesma_linha_seguem_com_o_aviso():
    _base, res = _dividido([40000, 60000])
    outro = dict(_linhas(res)[0], id="L2")
    res.contas[CONTA].append(outro)           # parte do L1 copiada sob outro lançamento
    entradas = [e for c in hp.contas_do_html_geral(res) for e in c["entries"]]
    assert any("mesma linha digitável" in e["bloqueio"] for e in entradas)
