# -*- coding: utf-8 -*-
"""O OCR que falha numa máquina tem de dizer POR QUÊ.

Em 14/09/2026 o dono contou que noutro PC o Renomear devolvia quase tudo
"SEM VALOR - SEM DESCRICAO": o PDF sem camada de texto vai para o Tesseract
embutido no exe, e ali ele não lia nada. Nesta máquina funciona, e nada no
`diagnostico.log` de lá dizia qual Tesseract foi achado, se ele chegou a rodar
nem se o arquivo do idioma existia. Estes testes guardam o relato que passa a
ser gravado. Nenhum Tesseract de verdade roda aqui: o executável é um arquivo
falso numa pasta temporária, e as chamadas ao pytesseract são dublês.
"""
import sys

import pytest

sr = pytest.importorskip("separar_renomear.separar_renomear")
pytesseract = pytest.importorskip("pytesseract")


@pytest.fixture
def ocr_limpo(monkeypatch):
    monkeypatch.setitem(sr._OCR, "pronto", None)
    monkeypatch.setitem(sr._OCR, "avisado", False)
    monkeypatch.setitem(sr._OCR, "relato", None)
    monkeypatch.setitem(sr._OCR, "erro_registrado", False)
    gravado = []
    monkeypatch.setattr(sr, "_diag_ocr", lambda texto: gravado.append(texto))
    return gravado


def _tesseract_falso(pasta, com_por=True):
    base = pasta / "tesseract"
    (base / "tessdata").mkdir(parents=True)
    (base / "tesseract.exe").write_bytes(b"falso")
    if com_por:
        (base / "tessdata" / "por.traineddata").write_bytes(b"x")
    return base


def test_o_relato_diz_qual_tesseract_versao_e_idiomas(tmp_path, monkeypatch, ocr_limpo):
    base = _tesseract_falso(tmp_path)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(pytesseract, "get_tesseract_version", lambda: "5.3.1")
    monkeypatch.setattr(pytesseract, "get_languages", lambda config="": ["eng", "por"])

    assert sr._configurar_ocr() is True
    relato = sr._OCR["relato"]
    assert relato["escolhido"] == str(base / "tesseract.exe")
    assert relato["versao"] == "5.3.1"
    assert relato["idiomas"] == ["eng", "por"]
    assert relato["por_traineddata"] is True
    assert ocr_limpo and "5.3.1" in ocr_limpo[0]


def test_tesseract_barrado_ao_rodar_fica_no_relato(tmp_path, monkeypatch, ocr_limpo):
    """O antivírus que barra o .exe da pasta temporária aparece como erro ao
    RODAR, não como arquivo ausente — e é essa diferença que o relato guarda."""
    _tesseract_falso(tmp_path)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    def barrado():
        raise PermissionError("Acesso negado")

    monkeypatch.setattr(pytesseract, "get_tesseract_version", barrado)
    monkeypatch.setattr(pytesseract, "get_languages", lambda config="": [])

    sr._configurar_ocr()
    relato = sr._OCR["relato"]
    assert "PermissionError" in relato["versao"] and "Acesso negado" in relato["versao"]
    assert "Acesso negado" in ocr_limpo[0]


def test_sem_o_idioma_portugues_o_relato_avisa(tmp_path, monkeypatch, ocr_limpo):
    _tesseract_falso(tmp_path, com_por=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(pytesseract, "get_tesseract_version", lambda: "5.3.1")
    monkeypatch.setattr(pytesseract, "get_languages", lambda config="": ["eng"])

    sr._configurar_ocr()
    assert sr._OCR["relato"]["por_traineddata"] is False
    assert sr._OCR["lang"] == "eng"


def test_caminho_com_acento_fica_marcado(tmp_path, monkeypatch, ocr_limpo):
    pasta = tmp_path / "Usuário"
    pasta.mkdir()
    _tesseract_falso(pasta)
    monkeypatch.setattr(sys, "_MEIPASS", str(pasta), raising=False)
    monkeypatch.setattr(pytesseract, "get_tesseract_version", lambda: "5.3.1")
    monkeypatch.setattr(pytesseract, "get_languages", lambda config="": ["por"])

    sr._configurar_ocr()
    assert sr._OCR["relato"]["caminho_fora_do_ascii"] is True


def test_sem_tesseract_nenhum_o_relato_lista_onde_procurou(tmp_path, monkeypatch, ocr_limpo):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(sr, "_CAMINHOS_TESSERACT_FIXOS", ())
    monkeypatch.setattr("shutil.which", lambda _n: None)

    assert sr._configurar_ocr() is False
    relato = sr._OCR["relato"]
    assert relato["escolhido"] == ""
    assert relato["candidatos"] and all(not existe for _c, existe in relato["candidatos"])
    assert "nenhum Tesseract" in ocr_limpo[0]


def test_o_primeiro_erro_de_reconhecimento_vai_para_o_diagnostico(monkeypatch, ocr_limpo):
    """O Registro já mostrava "[ERRO] OCR: …"; o diagnostico.log não, e é ele
    que chega de outra máquina. Só o PRIMEIRO, para não encher o arquivo."""
    monkeypatch.setitem(sr._OCR, "pronto", True)

    def falha(_img, lang="por"):
        raise RuntimeError("tessdata não encontrado")

    monkeypatch.setattr(pytesseract, "image_to_string", falha)

    class Pagina:
        def to_image(self, resolution=300):
            class Img:
                original = object()
            return Img()

    class Pl:
        pages = [Pagina(), Pagina(), Pagina()]

    registro = []
    saida = sr._ocr_em_lote(Pl(), [0, 1, 2], registro.append)
    assert saida == {0: "", 1: "", 2: ""}
    assert sum("tessdata não encontrado" in t for t in ocr_limpo) == 1
    assert any("não leu texto nenhum" in t for t in registro)
