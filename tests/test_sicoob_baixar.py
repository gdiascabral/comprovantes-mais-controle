# -*- coding: utf-8 -*-
"""
Testes da validação do OFX e da compactação.

A validação é a trava principal do projeto: sem ela, um extrato pode ser
gravado com o nome certo dentro da pasta da empresa errada, e nada no disco
denuncia o erro. Estes testes existem para que ela nunca deixe passar.

OFX fictício — o repositório é público.
"""
import json
import zipfile

import pytest

import sicoob_baixar as sb
import sicoob_contas as sc
import sicoob_zipar as sz

OFX = """OFXHEADER:100
DATA:OFXSGML
VERSION:102
CHARSET:1252
<OFX>
<BANKMSGSRSV1>
<STMTTRNRS>
<STMTRS>
<CURDEF>BRL
<BANKACCTFROM>
<BANKID>756
<BRANCHID>9999-9
<ACCTID>{conta}
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>{ini}120000[-3:BRT]
<DTEND>{fim}120000[-3:BRT]
<STMTTRN>
<TRNTYPE>CREDIT
<MEMO>PIX RECEBIDO - JOÃO ANTÔNIO
</STMTTRN>
</BANKTRANLIST>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""


def ofx(conta="11111-1", ini="20260701", fim="20260731") -> str:
    return OFX.format(conta=conta, ini=ini, fim=fim)


# ------------------------------------------------------------- validação

def test_ofx_correto_passa():
    assert sb.validar_ofx(ofx(), "11.111-1", 2026, 7) == []


def test_pontuacao_nao_atrapalha():
    # O Sicoob grava "11111-1"; a pessoa escreve "11.111-1".
    assert sb.validar_ofx(ofx(conta="11111-1"), "11.111-1", 2026, 7) == []


def test_conta_trocada_e_recusada():
    problemas = sb.validar_ofx(ofx(conta="22222-2"), "11.111-1", 2026, 7)
    assert problemas and "22222-2" in problemas[0]


def test_mes_errado_e_recusado():
    problemas = sb.validar_ofx(ofx(ini="20260601", fim="20260630"),
                               "11.111-1", 2026, 7)
    assert any("período" in p for p in problemas)


def test_mes_incompleto_e_recusado():
    # Baixou 01 a 10 de julho em vez do mês fechado.
    problemas = sb.validar_ofx(ofx(fim="20260710"), "11.111-1", 2026, 7)
    assert any("período" in p for p in problemas)


def test_fevereiro_bissexto_aceita_dia_29():
    assert sb.validar_ofx(ofx(ini="20240201", fim="20240229"),
                          "11.111-1", 2024, 2) == []


def test_arquivo_que_nao_e_ofx_e_recusado():
    problemas = sb.validar_ofx("<html>erro do servidor</html>", "11.111-1", 2026, 7)
    assert len(problemas) == 2          # sem ACCTID e sem período


def test_leitura_respeita_windows_1252(tmp_path):
    arq = tmp_path / "e.ofx"
    arq.write_text(ofx(), encoding="cp1252")
    assert "JOÃO ANTÔNIO" in sb.ler_ofx(arq)


# -------------------------------------------------------------- relatório

def test_relatorio_separa_completos_de_falhos():
    rel = sb.Relatorio(resultados=[
        sb.ResultadoConta("11.111-1", "ALFA", ofx=True, pdf=True),
        sb.ResultadoConta("22.222-2", "BETA", ofx=True, pdf=False),
        sb.ResultadoConta("33.333-3", "GAMA", problemas=["conta não encontrada"]),
    ])
    assert len(rel.completos) == 1 and len(rel.falhos) == 2
    texto = rel.texto()
    assert "1 de 3 contas completas" in texto
    assert "22.222-2" in texto and "PDF" in texto
    assert "conta não encontrada" in texto


# ------------------------------------------------------------------ zip

@pytest.fixture
def mapa(tmp_path):
    dados = {
        "raiz": str(tmp_path / "EXTRATOS"),
        "empresas": [
            {"nome": "ALFA", "pastas_vazias": ["CAIXA"],
             "contas": [{"numero": "11.111-1", "pasta": "SICOOB"}]},
            {"nome": "BETA", "pastas_vazias": [],
             "contas": [{"numero": "22.222-2", "pasta": "SICOOB"}]},
        ],
    }
    arq = tmp_path / "m.json"
    arq.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return sc.carregar(arq)


def test_zip_por_empresa_com_os_arquivos(mapa, tmp_path):
    import sicoob_pastas as sp
    sp.criar(sp.planejar(mapa, 2026, 7))
    base = sp.caminho_do_mes(mapa, 2026, 7)
    (base / "JULHO 2026 - ALFA" / "SICOOB" / "202607 SICOOB.ofx").write_text("x")
    (base / "JULHO 2026 - BETA" / "SICOOB" / "202607 SICOOB.ofx").write_text("y")

    resultados = sz.zipar_mes(mapa, 2026, 7, log=lambda *_: None)
    alfa = next(r for r in resultados if r.empresa == "ALFA")
    assert alfa.caminho.is_dir() is False and alfa.caminho.exists()
    assert alfa.arquivos == 1
    with zipfile.ZipFile(alfa.caminho) as z:
        assert any("202607 SICOOB.ofx" in n for n in z.namelist())


def test_zip_avisa_pasta_de_banco_vazia(mapa):
    import sicoob_pastas as sp
    sp.criar(sp.planejar(mapa, 2026, 7))
    base = sp.caminho_do_mes(mapa, 2026, 7)
    (base / "JULHO 2026 - ALFA" / "SICOOB" / "202607 SICOOB.ofx").write_text("x")
    resultados = sz.zipar_mes(mapa, 2026, 7, log=lambda *_: None)
    alfa = next(r for r in resultados if r.empresa == "ALFA")
    assert alfa.pastas_vazias == ["CAIXA"]     # o mês ainda não fechou


def test_zipar_mes_inexistente_avisa(mapa):
    with pytest.raises(FileNotFoundError):
        sz.zipar_mes(mapa, 2026, 7, log=lambda *_: None)
