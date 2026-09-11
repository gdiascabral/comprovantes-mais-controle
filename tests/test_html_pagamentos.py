# -*- coding: utf-8 -*-
"""O HTML provisório dos pagamentos do dia (`pagamentos_dia/html_pagamentos.py`).

Puro: monta um `Resultado` e uma lista de lançamentos FICTÍCIOS, grava os dois
HTMLs numa pasta temporária e lê de volta o JSON que foi para dentro de cada
um. Não abre janela nem navegador.

Nenhum nome, conta, CPF ou CNPJ aqui é de verdade — o repositório é público.
"""
import ast
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from pagamentos_dia import html_pagamentos as hp
from pagamentos_dia import modelos_html
from pagamentos_dia import regras_pagamento as regras
from pagamentos_dia.relatorio import Resultado

INI, FIM, HOJE = date(2026, 9, 1), date(2026, 9, 10), date(2026, 9, 11)
PF = "PESSOA FISICA - APENAS LANÇAMENTO"
PERIGOSO = '</script><script>alert("x")</script> <!-- \'aspas\' & "duplas"'


def _linha(favorecido, valor, id_, tipo="Pix", dados="fulano@exemplo.com",
           **extra):
    linha = {"tipo": tipo, "dados": dados, "valor": valor,
             "descricao": "OBRA TESTE QD 1 LT 1 NF 10", "favorecido": favorecido,
             "status": "APTO", "conferencia": "(não cruzado)", "obs": "",
             "id": id_}
    linha.update(extra)
    return linha


def _resultado(**contas_extra):
    contas = {
        "CONTA ALFA - SICOOB": [
            _linha("FORNECEDOR UM", 0.1, "101"),
            _linha("FORNECEDOR DOIS", 0.2, "102"),
            _linha("FORNECEDOR TRES", 1234.56, "103", tipo="Boleto",
                   dados="00190.00009 01234.567890 12345.678901 1 00000000000000"),
        ],
        "CONTA BETA - INTER": [
            _linha("FORNECEDOR QUATRO", 99.99, "104", obs=PERIGOSO),
        ],
    }
    contas.update(contas_extra)
    omitidos = [{"conta": PF, "tipo": "Pix", "valor": 50.0, "descricao": "X",
                 "favorecido": "PESSOA FICTICIA PF",
                 "motivo": "conta fora do recorte"}]
    return Resultado(contas, omitidos)


def _lancamentos():
    base = {"tradePayableAccount": {"name": PF}, "paid": False,
            "tradePayablePaymentMethod": "Pix"}
    return [
        dict(base, id="201", tradePayableId="9201", paidTo="PESSOA FICTICIA PF",
             plannedDate="2026-09-05", remainingValue=50.0,
             paidToBankAccount="PIX EMAIL fulana@exemplo.com",
             description="REEMBOLSO TESTE", category={"name": "Materiais"},
             documentNumber="77",
             costCentreDetails=[{"workName": "OBRA TESTE QD 1 LT 1"},
                                {"workName": "OBRA TESTE QD 1 LT 1"}]),
        # Já paga: não é para pagar de novo, e não aparece.
        dict(base, id="202", tradePayableId="9202", paidTo="PESSOA JA PAGA PF",
             plannedDate="2026-09-02", remainingValue=0.0, sumOfPaidValues=30.0,
             paid=True),
        # Sem data prevista: vence no último dia do período, como no script.
        dict(base, id="203", tradePayableId="9203", paidTo="OUTRA PESSOA PF",
             remainingValue=10.05, description=PERIGOSO),
        # Conta comum: vai pelo `Resultado`, nunca pelo HTML de PF.
        {"id": "101", "tradePayableId": "9101", "paid": False,
         "tradePayableAccount": {"name": "CONTA ALFA - SICOOB"},
         "paidTo": "FORNECEDOR UM", "plannedDate": "2026-09-03",
         "remainingValue": 0.1},
    ]


def _gravar(tmp_path, resultado=None, lancamentos=None, **kw):
    return hp.gravar(resultado or _resultado(),
                     _lancamentos() if lancamentos is None else lancamentos,
                     {}, tmp_path, INI, FIM, hoje=HOJE, **kw)


def _json(html: str, nome: str):
    """O JSON que o modelo recebeu em `const <nome> = …;`."""
    m = re.search(r"const " + nome + r" = (.*?);\n", html, re.S)
    assert m, f"não achei const {nome} no HTML"
    return json.loads(m.group(1))


def _ler(caminho: Path) -> str:
    return caminho.read_text(encoding="utf-8")


# ------------------------------------------------------------------ arquivos
def test_grava_os_dois_htmls_na_pasta_da_planilha(tmp_path):
    g = _gravar(tmp_path)
    assert g.geral == tmp_path / "pagamentos_2026-09-01_a_2026-09-10.html"
    assert g.pessoa_fisica == (
        tmp_path / "pagamentos_pessoa_fisica_lancamento_2026-09-01_a_2026-09-10.html")
    assert g.geral.is_file() and g.pessoa_fisica.is_file()


def test_um_dia_so_usa_o_mesmo_nome_da_planilha(tmp_path):
    g = hp.gravar(_resultado(), [], {}, tmp_path, INI, INI, hoje=HOJE)
    assert g.geral.name == "pagamentos_2026-09-01.html"


def test_nenhum_placeholder_fica_para_tras(tmp_path):
    g = _gravar(tmp_path)
    for html in (_ler(g.geral), _ler(g.pessoa_fisica)):
        assert not re.findall(
            r"__(JSON|STORAGE|TITULO|SUB|CFG|DATA|HOJE_BR|INI_BR|FIM_BR|HOJE|"
            r"PERIODO|LOGO)__", html)


# --------------------------------------------------------------- HTML geral
def test_toda_linha_do_passo_2_aparece_no_geral(tmp_path):
    dados = _json(_ler(_gravar(tmp_path).geral), "DATA")
    ids = [e["id"] for c in dados["contas"] for e in c["entries"]]
    assert sorted(ids) == ["101", "102", "103", "104"]
    favorecidos = {e["favorecido"] for c in dados["contas"] for e in c["entries"]}
    assert favorecidos == {"FORNECEDOR UM", "FORNECEDOR DOIS", "FORNECEDOR TRES",
                           "FORNECEDOR QUATRO"}


def test_o_total_por_conta_bate_no_centavo(tmp_path):
    """0,10 + 0,20 + 1.234,56 = 1.234,86 — em Decimal, e em centavos no
    navegador. Em float a primeira soma já dá 0,30000000000000004."""
    g = _gravar(tmp_path)
    contas = {c["nome"]: c for c in _json(_ler(g.geral), "DATA")["contas"]}
    alfa, beta = contas["CONTA ALFA - SICOOB"], contas["CONTA BETA - INTER"]
    assert alfa["total"] == "1.234,86"
    assert sum(e["centavos"] for e in alfa["entries"]) == 123486
    assert [e["valor"] for e in alfa["entries"]] == ["0,10", "0,20", "1234,56"]
    assert beta["total"] == "99,99"
    assert g.total == Decimal("1334.85") and g.linhas == 4 and g.contas == 2
    assert hp.total_da_conta(_resultado().contas["CONTA ALFA - SICOOB"]) == \
        Decimal("1234.86")


def test_dinheiro_e_decimal_e_nao_float():
    assert hp.dinheiro(0.1) + hp.dinheiro(0.2) == Decimal("0.30")
    assert hp.centavos(1234.565) == 123457
    assert hp.centavos(None) == 0 and hp.centavos("lixo") == 0
    assert hp.reais(Decimal("1234.5")) == "R$ 1.234,50"
    assert hp.valor_para_colar(1234.5) == "1234,50"


def test_o_dado_de_pagamento_sai_pronto_para_colar():
    assert hp.dado_para_colar(
        "Boleto", "00190.00009 01234.567890 12345.678901 1 00000000000000") == \
        "00190000090123456789012345678901100000000000000"
    assert hp.dado_para_colar("Pix", "Fulano@Exemplo.com") == "fulano@exemplo.com"
    assert hp.dado_para_colar("Pix", "111.222.333-44") == "11122233344"
    # Copia-e-cola vai inteiro: sem ele, o QR do Pix deixa de fechar.
    copia = ("00020126360014br.gov.bcb.pix0114+556299999999952040000530398654"
             "0510.005802BR5905TESTE6007CIDADE62070503***6304ABCD")
    assert hp.dado_para_colar("Pix", copia) == copia
    assert hp.dado_para_colar("Pix", "") == ""


def test_a_marca_ja_paguei_e_pelo_id_do_lancamento():
    """Pela posição, gerar de novo com uma linha a mais movia a marca para a
    linha de baixo — e a linha marcada por engano é o pagamento que não sai."""
    assert "rowKey(c, e, idx)" in modelos_html.MODELO_GERAL
    assert "'id:' + e.id" in modelos_html.MODELO_GERAL


# ------------------------------------------------------------ pessoa física
def test_pessoa_fisica_vai_so_para_o_html_dela(tmp_path):
    g = _gravar(tmp_path)
    geral, pf = _ler(g.geral), _ler(g.pessoa_fisica)
    itens = _json(pf, "ITENS")
    assert [i["id"] for i in itens] == ["201", "203"]
    assert "PESSOA FICTICIA PF" not in geral
    assert "OUTRA PESSOA PF" not in geral
    assert "FORNECEDOR UM" not in pf
    assert "PESSOA JA PAGA PF" not in pf          # já paga não se paga de novo
    assert g.linhas_pf == 2 and g.total_pf == Decimal("60.05")


def test_conta_pf_no_resultado_continua_fora_do_geral(tmp_path):
    """Hoje ela nunca chega ao `Resultado.contas`; se um dia chegar, o geral
    não pode passar a mostrá-la."""
    res = _resultado(**{"PESSOA  FISICA - APENAS LANCAMENTO": [
        _linha("PESSOA FICTICIA PF", 50.0, "201")]})
    g = _gravar(tmp_path, resultado=res)
    nomes = [c["nome"] for c in _json(_ler(g.geral), "DATA")["contas"]]
    assert nomes == ["CONTA ALFA - SICOOB", "CONTA BETA - INTER"]
    assert g.total == Decimal("1334.85")


def test_os_campos_do_pdf_de_pf_vem_da_lista_do_passo_1(tmp_path):
    itens = {i["id"]: i for i in _json(_ler(_gravar(tmp_path).pessoa_fisica),
                                         "ITENS")}
    um = itens["201"]
    assert um["venc"] == "2026-09-05" and um["venc_br"] == "05/09/2026"
    assert um["categoria"] == "Materiais" and um["doc"] == "77"
    assert um["obras"] == "OBRA TESTE QD 1 LT 1"
    assert um["cc"] == [{"obra": "OBRA TESTE QD 1 LT 1", "item": ""}]
    assert um["centavos"] == 5000 and um["metodo"] == "Pix"
    assert um["conta"] == PF and um["condicao"] == "À Vista"
    assert um["dados"] == "PIX EMAIL fulana@exemplo.com"
    sem_data = itens["203"]
    assert sem_data["venc"] == "2026-09-10" and not sem_data["venc_do_erp"]


def test_o_registro_diz_o_que_faltou(tmp_path):
    g = _gravar(tmp_path)
    texto = "\n".join(g.registro())
    assert "provisório" in texto
    assert str(g.geral).replace("\\", "/") in texto
    assert "1 sem vencimento no ERP" in texto and "1 sem categoria" in texto
    assert hp.NOMES_LOGO[0] in texto and hp.NOME_RODAPE in texto


# ------------------------------------------------------------------ escape
def test_texto_com_script_e_aspas_nao_escapa_do_json(tmp_path):
    g = _gravar(tmp_path)
    for caminho, modelo in ((g.geral, modelos_html.MODELO_GERAL),
                            (g.pessoa_fisica, modelos_html.MODELO_PF)):
        html = _ler(caminho)
        # Nenhuma tag nova: só as do modelo.
        assert html.count("</script>") == modelo.count("</script>")
        assert html.count("<script") == modelo.count("<script")
        assert "<!--" not in html
    obs = [e["obs"] for c in _json(_ler(g.geral), "DATA")["contas"]
           for e in c["entries"] if e["obs"]]
    assert obs == [PERIGOSO]                      # o mesmo texto, de volta
    descricoes = [i["descricao"] for i in _json(_ler(g.pessoa_fisica), "ITENS")]
    assert PERIGOSO in descricoes


def test_escapar_troca_os_cinco():
    assert hp.escapar('<a href="x">\'&') == \
        "&lt;a href=&quot;x&quot;&gt;&#39;&amp;"
    assert hp.escapar(None) == ""


def test_placeholder_dentro_do_dado_nao_e_trocado(tmp_path):
    res = _resultado(**{"CONTA GAMA": [_linha("__DATA__ __TITULO__", 1.0, "105",
                                              obs="__JSON__")]})
    dados = _json(_ler(_gravar(tmp_path, resultado=res).geral), "DATA")
    gama = [c for c in dados["contas"] if c["nome"] == "CONTA GAMA"][0]
    assert gama["entries"][0]["obs"] == "__JSON__"


# ----------------------------------------------------------- logo e rodapé
def test_logo_e_rodape_sao_opcionais(tmp_path):
    g = _gravar(tmp_path)
    cfg = _json(_ler(g.pessoa_fisica), "CFG")
    assert cfg["logo"] == "" and cfg["rodape"] == []
    assert not g.tem_logo and not g.tem_rodape


def test_logo_e_rodape_vem_de_arquivos_ao_lado_da_planilha(tmp_path):
    (tmp_path / hp.NOMES_LOGO[0]).write_bytes(b"\x89PNG\r\n\x1a\nFICTICIO")
    (tmp_path / hp.NOME_RODAPE).write_text(
        "EMPRESA FICTICIA\n\nRUA DE TESTE, 1 | contato@exemplo.com\n",
        encoding="utf-8")
    g = _gravar(tmp_path)
    cfg = _json(_ler(g.pessoa_fisica), "CFG")
    assert cfg["logo"].startswith("data:image/png;base64,")
    assert cfg["rodape"] == ["EMPRESA FICTICIA", "RUA DE TESTE, 1 | contato@exemplo.com"]
    assert g.tem_logo and g.tem_rodape
    assert hp.NOMES_LOGO[0] not in "\n".join(g.registro())


def test_a_pasta_do_app_vale_quando_a_da_planilha_nao_tem(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / hp.NOME_RODAPE).write_text("EMPRESA FICTICIA", encoding="utf-8")
    g = _gravar(tmp_path / "saida", pastas_extras=(tmp_path / "saida", app))
    assert _json(_ler(g.pessoa_fisica), "CFG")["rodape"] == ["EMPRESA FICTICIA"]


# ------------------------------------------------ o que não pode ir ao repo
def _corridas_de_digitos(texto: str):
    for m in re.finditer(r"\d[\d.\-/ ]{9,20}\d", texto):
        digitos = re.sub(r"\D", "", m.group(0))
        if len(digitos) in (11, 14):
            yield m.group(0), digitos


def test_os_modelos_nao_carregam_dado_real():
    """O repositório é público: nenhum CPF/CNPJ que feche no dígito
    verificador, nenhum e-mail e nenhuma imagem embutida (o logotipo vem de
    arquivo, ao lado da planilha)."""
    for modelo in (modelos_html.MODELO_GERAL, modelos_html.MODELO_PF):
        documentos = [t for t, d in _corridas_de_digitos(modelo)
                      if regras.documento_valido(d)]
        assert not documentos, documentos
        assert not re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", modelo)
        assert "base64," not in modelo


def test_os_modelos_recebem_dado_so_pelos_pontos_de_entrada():
    assert modelos_html.MODELO_GERAL.count("__JSON__") == 1
    assert modelos_html.MODELO_GERAL.count("__STORAGE__") == 1
    assert modelos_html.MODELO_PF.count("__CFG__") == 1
    assert modelos_html.MODELO_PF.count("__DATA__") == 1
    # O jsPDF continua vindo do CDN, e não embutido.
    assert "cdnjs.cloudflare.com/ajax/libs/jspdf/" in modelos_html.MODELO_PF


def test_os_dois_modulos_nao_importam_tkinter():
    """São regra e texto: rodam em teste sem tela, e quem os chama é que é tela."""
    raiz = Path(__file__).resolve().parent.parent / "pagamentos_dia"
    for nome in ("html_pagamentos.py", "modelos_html.py"):
        arvore = ast.parse((raiz / nome).read_text(encoding="utf-8"))
        importados = {a.name.split(".")[0] for no in ast.walk(arvore)
                      if isinstance(no, ast.Import) for a in no.names}
        importados |= {no.module.split(".")[0] for no in ast.walk(arvore)
                       if isinstance(no, ast.ImportFrom) and no.module}
        assert "tkinter" not in importados, nome
