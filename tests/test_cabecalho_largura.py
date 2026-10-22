# -*- coding: utf-8 -*-
"""O subtítulo do cabeçalho quebra a linha e os botões nunca encolhem — sem
janela (a régua é aritmética, e a ordem do `pack` é lida no código).

Galeria a 1280x800, 22/10/2026: na aba "Baixar Comprovantes" o botão verde
saía cortado ("Baixar comprova") porque o subtítulo longo, com `wraplength`
fixo de 820 px, pedia a largura toda e empurrava a área de ações para fora."""
import ast
from pathlib import Path

import widgets

RAIZ = Path(__file__).resolve().parents[1]


def test_largura_do_apoio_segue_o_espaco_que_sobrou_com_teto():
    assert widgets.largura_do_apoio(500, 820) == 500
    assert widgets.largura_do_apoio(1400, 820) == 820          # teto: linha legível
    assert widgets.largura_do_apoio(1, 820) == widgets.APOIO_MINIMO   # antes do layout


def _init_do_cabecalho():
    fonte = (RAIZ / "widgets.py").read_text(encoding="utf-8")
    cls = next(n for n in ast.walk(ast.parse(fonte))
               if isinstance(n, ast.ClassDef) and n.name == "Cabecalho")
    init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    return ast.get_source_segment(fonte, init)


def test_as_acoes_sao_empacotadas_antes_do_texto():
    """O `pack` reparte o espaço NA ORDEM: quem entra primeiro leva o que
    pediu. As ações primeiro = os botões nunca encolhem."""
    trecho = _init_do_cabecalho()
    assert trecho.index("self.acoes.pack(") < trecho.index("esquerda.pack(")


def test_o_apoio_quebra_pela_largura_real():
    trecho = _init_do_cabecalho()
    assert "largura_do_apoio(" in trecho and "<Configure>" in trecho
