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
    achado = origem.origens_dos_pdfs(dia, contas_inter=[])
    assert achado["10,00 - OBRA - 02-09.pdf"] == {
        "origem": ("SICOOB", "123456"), "recebedor": "FORNECEDOR EXEMPLO"}
    assert achado["30,00 - BOLETO - 02-09.pdf"]["origem"] == ("SICOOB", "987654")
    assert achado["40,00 - REEMBOLSO - 02-09.pdf"]["origem"] == ("INTER", "")
    assert "50,00 - OUTRO - 02-09.pdf" not in achado


def test_inter_novo_vira_a_empresa_pelo_apelido(tmp_path):
    _registro(tmp_path, {
        "pix:E2": {"arquivo": "40,00 - REEMBOLSO - 02-09.pdf",
                   "quando": "2026-09-14T10:02:00", "origem": "INTER:EXEMPLO ENG"}})
    achado = origem.origens_dos_pdfs(
        tmp_path, contas_inter=[ContaInter(apelido="EXEMPLO ENG", empresa="EXEMPLO")])
    assert achado["40,00 - REEMBOLSO - 02-09.pdf"]["origem"] == ("INTER", "EXEMPLO")


def test_sem_registro_ninguem_ganha_origem(tmp_path):
    assert origem.origens_dos_pdfs(tmp_path, contas_inter=[]) == {}


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
        nome="EXEMPLO",
        contas=[sicoob_contas.Conta(numero="12.345-6", pasta="SICOOB")])]


def test_conta_do_erp_vira_banco_e_conta():
    m, e = _mapa(), _empresas()
    assert origem.origem_da_conta_erp("EXEMPLO - SICOOB", m, e) == ("SICOOB", "123456")
    assert origem.origem_da_conta_erp("exemplo - inter", m, e) == ("INTER", "EXEMPLO")
    assert origem.origem_da_conta_erp("FULANO - PAGBANK", m, e) == ("PAGBANK", "PESSOAS FISICAS")
    assert origem.origem_da_conta_erp("SEM BANCO", m, e) is None
    assert origem.origem_da_conta_erp("CONTA QUE NAO EXISTE", m, e) is None


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
