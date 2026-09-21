# -*- coding: utf-8 -*-
"""De onde saiu cada comprovante, e de que conta é cada lançamento.

É o que alimenta a regra do dono de 14/09/2026 no casamento: PDF que saiu de
outra conta que não a cadastrada no lançamento não disputa. O lado do PDF vem
do registro da baixa (`.ja-baixados.json`); o do lançamento, do MESMO cadastro
de contas que a remessa usa (`contas_mc.json` + `contas_sicoob.json` +
`contas_inter.json`). Tudo fictício: empresas, contas e nomes são inventados.
"""
import json
from pathlib import Path

from anexar import matcher, origem
from baixar_comprovantes import ja_baixados
from baixar_comprovantes.contas_inter import ContaInter
from extratos_sicoob import sicoob_contas
from relatorios import contas_mc


# ------------------------------------------------------------ o registro
def test_o_registro_guarda_de_onde_saiu_e_quem_recebeu(tmp_path):
    reg = ja_baixados.Registro(tmp_path)
    reg.anotar("sicoob_pix:12.345-6:E1", tmp_path / "10,00 - OBRA - 02-09.pdf",
               origem="SICOOB:12.345-6", recebedor="FORNECEDOR EXEMPLO")
    reg.anotar("pix:E2", tmp_path / "20,00 - X - 02-09.pdf")
    reg.gravar()
    dados = json.loads((tmp_path / ja_baixados.ARQUIVO).read_text(encoding="utf-8"))
    assert dados["sicoob_pix:12.345-6:E1"]["origem"] == "SICOOB:12.345-6"
    assert dados["sicoob_pix:12.345-6:E1"]["recebedor"] == "FORNECEDOR EXEMPLO"
    assert "origem" not in dados["pix:E2"], "campo vazio não se grava"


# ------------------------------------------------------------ o lado do PDF
def _registro(pasta: Path, dados: dict):
    (pasta / ja_baixados.ARQUIVO).write_text(json.dumps(dados), encoding="utf-8")


def test_pdf_ganha_origem_pelo_registro_da_pasta_mae(tmp_path):
    dia = tmp_path / "2026-09-14"
    dia.mkdir()
    _registro(tmp_path, {
        "sicoob_pix:12.345-6:E1": {"arquivo": "10,00 - OBRA - 02-09.pdf",
                                   "quando": "2026-09-14T10:00:00",
                                   "origem": "SICOOB:12.345-6",
                                   "recebedor": "FORNECEDOR EXEMPLO"},
        # registro antigo: sem `origem`, o banco e a conta saem da CHAVE
        "sicoob:98.765-4:777": {"arquivo": "30,00 - BOLETO - 02-09.pdf",
                                "quando": "2026-09-14T10:01:00"},
        # Inter antigo: a chave só diz o banco
        "pix:E00416968X": {"arquivo": "40,00 - REEMBOLSO - 02-09.pdf",
                           "quando": "2026-09-14T10:02:00"},
        # outro dia: mesmo nome de arquivo, outra pasta -- não vale para esta
        "sicoob:11.111-1:888": {"arquivo": "50,00 - OUTRO - 02-09.pdf",
                                "quando": "2026-09-11T10:00:00"},
    })
    achado = origem.origens_dos_pdfs(dia)
    assert achado["10,00 - OBRA - 02-09.pdf"] == {
        "origem": ("SICOOB", "123456"), "recebedor": "FORNECEDOR EXEMPLO",
        "doc_recebedor": None}
    assert achado["30,00 - BOLETO - 02-09.pdf"]["origem"] == ("SICOOB", "987654")
    assert achado["40,00 - REEMBOLSO - 02-09.pdf"]["origem"] == ("INTER", "")
    assert "50,00 - OUTRO - 02-09.pdf" not in achado


def test_inter_novo_fica_com_o_apelido_da_conta(tmp_path):
    """No Inter a conta é o LOGIN (apelido): duas contas da mesma empresa são
    contas diferentes, e comparar pela empresa as juntaria (revisão do #94)."""
    _registro(tmp_path, {
        "pix:E2": {"arquivo": "40,00 - REEMBOLSO - 02-09.pdf",
                   "quando": "2026-09-14T10:02:00", "origem": "INTER:Exemplo Eng"}})
    achado = origem.origens_dos_pdfs(tmp_path)
    assert achado["40,00 - REEMBOLSO - 02-09.pdf"]["origem"] == ("INTER", "EXEMPLO ENG")


def test_sem_registro_ninguem_ganha_origem(tmp_path):
    assert origem.origens_dos_pdfs(tmp_path) == {}


# ------------------------------------------------------ o lado do lançamento
def _mapa():
    return contas_mc.Mapa(raiz=Path("."), destinos=[
        contas_mc.Destino(erp="EXEMPLO - SICOOB", empresa="EXEMPLO",
                          pasta="SICOOB", banco="SICOOB"),
        contas_mc.Destino(erp="EXEMPLO - INTER", empresa="EXEMPLO",
                          pasta="INTER", banco="INTER"),
        contas_mc.Destino(erp="FULANO - PAGBANK", empresa="PESSOAS FISICAS",
                          pasta="PAGBANK", banco="PAGBANK"),
        contas_mc.Destino(erp="SEM BANCO", empresa="PESSOAS FISICAS",
                          pasta="X", banco=""),
    ])


def _empresas():
    return [sicoob_contas.Empresa(
        nome="EXEMPLO", cnpj="12.345.678/0001-95", clientes_erp=["EXEMPLO SPE ALFA"],
        contas=[sicoob_contas.Conta(numero="12.345-6", pasta="SICOOB")])]


def test_conta_do_erp_vira_banco_e_conta():
    m, e = _mapa(), _empresas()
    um_login = [ContaInter(apelido="Exemplo Eng", empresa="EXEMPLO")]
    assert origem.origem_da_conta_erp("EXEMPLO - SICOOB", m, e) == ("SICOOB", "123456")
    assert origem.origem_da_conta_erp("exemplo - inter", m, e, um_login) == ("INTER", "EXEMPLO ENG")
    assert origem.origem_da_conta_erp("FULANO - PAGBANK", m, e) == ("PAGBANK", "PESSOAS FISICAS")
    assert origem.origem_da_conta_erp("SEM BANCO", m, e) is None
    assert origem.origem_da_conta_erp("CONTA QUE NAO EXISTE", m, e) is None


def test_empresa_com_dois_logins_do_inter_nao_diz_qual_conta():
    """Dois apelidos para a mesma empresa: não dá para saber de qual login é o
    lançamento, então só o banco é conhecido (neutro contra PDF do Inter)."""
    dois = [ContaInter(apelido="Exemplo A", empresa="EXEMPLO"),
            ContaInter(apelido="Exemplo B", empresa="EXEMPLO")]
    assert origem.origem_da_conta_erp("EXEMPLO - INTER", _mapa(), _empresas(), dois) == ("INTER", "")


def test_ponta_a_ponta_titulo_de_pessoa_fisica_nao_leva_pix_da_empresa(tmp_path):
    """O caso de 14/09/2026: título na conta PagBank de uma pessoa casado em
    dúvida com o Pix de reembolso que a EMPRESA mandou pelo Sicoob."""
    _registro(tmp_path, {
        "sicoob_pix:12.345-6:E1": {"arquivo": "60,00 - REEMBOLSO - 11-09.pdf",
                                   "quando": "2026-09-14T10:00:00",
                                   "origem": "SICOOB:12.345-6"}})
    pdfs = [matcher.parse_pdf("60,00 - REEMBOLSO - 11-09.pdf")]
    pend = [{"paidId": "A", "launchId": "L-A", "valor": 6000, "valores": [6000],
             "doc": "", "desc": "", "works": [], "data": "1109",
             "conta": "FULANO - PAGBANK", "favorecido": "Fulano"}]
    resumo = origem.preencher(pend, pdfs, tmp_path, mapa_mc=_mapa(),
                              empresas=_empresas(), contas_inter=[])
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert not certezas and not duvidas and len(sem_par) == 1
    assert "outra conta" in sem_par[0]["motivo_sem_par"]
    assert resumo == {"pdfs": 1, "pdfs_com_origem": 1,
                      "lancamentos": 1, "lancamentos_com_conta": 1}


# ------------------------------------------------ CPF/CNPJ (14/09/2026)
def test_o_registro_guarda_o_documento_de_quem_recebeu(tmp_path):
    reg = ja_baixados.Registro(tmp_path)
    reg.anotar("pix:E3", tmp_path / "10,00 - X - 02-09.pdf", origem="INTER:A",
               doc_recebedor="11.222.333/0001-81")
    assert reg._dados["pix:E3"]["doc_recebedor"] == "11222333000181"


def test_pdf_e_lancamento_ganham_o_documento(tmp_path):
    _registro(tmp_path, {
        "pix:E3": {"arquivo": "10000,00 - EMPRESA PARA Empresa - 08-09.pdf",
                   "quando": "2026-09-14T10:00:00", "origem": "INTER:A",
                   "doc_recebedor": "11222333000181"}})
    pdfs = [matcher.parse_pdf("10000,00 - EMPRESA PARA Empresa - 08-09.pdf")]
    pend = [{"paidId": "A", "launchId": "L-A", "valor": 1000000, "valores": [1000000],
             "doc": "", "desc": "", "works": [], "data": "0809",
             "conta": "EXEMPLO - SICOOB", "favorecido": "Fornecedor  Exemplo"},
            {"paidId": "B", "launchId": "L-B", "valor": 1000000, "valores": [1000000],
             "doc": "", "desc": "", "works": [], "data": "0809",
             "conta": "EXEMPLO - SICOOB", "favorecido": "EXEMPLO SPE ALFA"}]
    origem.preencher(pend, pdfs, tmp_path, mapa_mc=_mapa(), empresas=_empresas(),
                     contas_inter=[], documentos={"FORNECEDOR EXEMPLO": "99888777000166"})
    assert pdfs[0]["doc_recebedor"] == "11222333000181"
    assert pend[0]["doc_favorecido"] == "99888777000166"
    # empresa do grupo: o CNPJ vem do contas_sicoob (nome e clientes do ERP)
    assert pend[1]["doc_favorecido"] == "12345678000195"


def test_documentos_do_grupo_saem_do_cadastro_das_empresas():
    docs = origem.documentos_do_grupo(_empresas())
    assert docs["EXEMPLO SPE ALFA"] == "12345678000195"
    assert docs["EXEMPLO"] == "12345678000195"


def test_a_oc_do_overview_do_erp():
    assert origem.ocs_do_overview({"purchaseOrder": {"number": 1111}}) == {"1111"}
    assert origem.ocs_do_overview({"purchaseOrder": None}) == set()
    assert origem.ocs_do_overview({}) == set()
    assert origem.ocs_do_overview(None) == set()

