# -*- coding: utf-8 -*-
"""O texto de um contrato em PDF: camada de texto primeiro, OCR só onde falta.

O contrato de compra e venda nasce de um .docx e é assinado no Clicksign, então
quase sempre tem camada de texto e a leitura é imediata. O OCR fica para o
escaneado, que é a exceção — e é lento: por isso a leitura é POR PÁGINA e
PREGUIÇOSA. O pipeline pede as primeiras páginas, confere, e só pede o resto
se algum ponto ficou em `?`. As partes, o objeto e o valor estão sempre no
começo do contrato; a página 20 é a de assinaturas.

Não sabe que existe interface. `log` recebe os avisos do OCR.
"""
from __future__ import annotations

import io

#: Página com menos texto que isto é tratada como sem camada de texto.
MINIMO_POR_PAGINA = 30

#: Quantas páginas o pipeline lê antes de decidir se precisa do resto.
PAGINAS_INICIAIS = 3


class LeitorPDF:
    """Texto das páginas de um PDF em memória, lido sob demanda e guardado.

    `texto(3)` lê as três primeiras; `texto()` lê todas — sem reler nem
    refazer OCR do que já foi lido."""

    def __init__(self, dados: bytes, log=None):
        self.dados = dados or b""
        self.log = log or (lambda m: None)
        self._paginas: dict[int, str] = {}
        self._total: int | None = None
        self.usou_ocr = False
        self.ocr_indisponivel = False
        self.erro = ""

    # ----------------------------------------------------------- consulta
    @property
    def total(self) -> int:
        if self._total is None:
            self._total = self._contar()
        return self._total

    def tem_mais(self, ate: int) -> bool:
        return self.total > ate

    def texto(self, ate: int | None = None) -> str:
        """Texto das páginas [0, ate) — todas quando `ate` é None."""
        n = self.total
        if n <= 0:
            return ""
        fim = n if ate is None else max(0, min(ate, n))
        faltam = [i for i in range(fim) if i not in self._paginas]
        if faltam:
            self._ler(faltam)
        return "\n".join(self._paginas.get(i, "") for i in range(fim))

    @property
    def origem(self) -> str:
        """Como o texto foi obtido, para o registro e o resumo."""
        if self.erro:
            return f"não li o PDF ({self.erro})"
        if self.usou_ocr:
            return "OCR"
        if self.ocr_indisponivel:
            return "sem texto e sem OCR disponível"
        return "camada de texto"

    # ------------------------------------------------------------ leitura
    def _abrir(self):
        import pdfplumber
        return pdfplumber.open(io.BytesIO(self.dados))

    def _contar(self) -> int:
        if not self.dados:
            return 0
        try:
            with self._abrir() as pl:
                return len(pl.pages)
        except ImportError:
            self.erro = "pdfplumber não está instalado"
            return 0
        except Exception as e:
            self.erro = str(e)[:120]
            return 0

    def _ler(self, indices: list[int]) -> None:
        try:
            with self._abrir() as pl:
                sem_texto = []
                for i in indices:
                    try:
                        t = pl.pages[i].extract_text() or ""
                    except Exception:
                        t = ""
                    self._paginas[i] = t
                    if len(t.strip()) < MINIMO_POR_PAGINA:
                        sem_texto.append(i)
                if sem_texto:
                    for i, t in (self._ocr(pl, sem_texto) or {}).items():
                        if (t or "").strip():
                            self._paginas[i] = t
                            self.usou_ocr = True
        except Exception as e:
            self.erro = self.erro or str(e)[:120]
            for i in indices:
                self._paginas.setdefault(i, "")

    def _ocr(self, pl, indices: list[int]) -> dict[int, str]:
        """OCR das páginas sem texto, pelo lote paralelo do Separar/Renomear
        (render em série, reconhecimento em paralelo). Sem Tesseract, avisa
        uma vez e devolve vazio — texto vazio vira `?` na conferência."""
        try:
            from separar_renomear.separar_renomear import (_ocr_disponivel,
                                                           _ocr_em_lote)
        except Exception:
            self.ocr_indisponivel = True
            return {}
        if not _ocr_disponivel(self.log):
            self.ocr_indisponivel = True
            return {}
        try:
            return _ocr_em_lote(pl, indices, self.log, 300) or {}
        except Exception as e:
            self.log(f"[aviso] OCR falhou: {e}")
            return {}


def abrir_pdf(dados: bytes, log=None) -> LeitorPDF:
    return LeitorPDF(dados, log)
