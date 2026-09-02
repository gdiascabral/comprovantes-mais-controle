# -*- coding: utf-8 -*-
"""Nome de módulo é global — a menos que toda pasta seja pacote.

Até 02/09/2026 o app montava um `sys.path` PLANO: `comprovantes_app.py`,
`motor.py`, o `conftest.py` e três ferramentas enfiavam cada pasta de aba
direto no caminho de import, e ali `config` é só `config`. Sete pastas não
tinham `__init__.py`, e havia `config.py` em três lugares, `frame.py` em três,
`conferencia.py`, `regras.py`, `pipeline.py` e `sicoob_baixar.py` em dois cada.
Quem entrasse por último no `sys.path` perdia — em silêncio, e a aba errada
funcionava com o módulo da vizinha.

O projeto conviveu com isso por convenção: os módulos do `extratos_sicoob/`
ganharam o prefixo `sicoob_` e o de regras do `pagamentos_dia/` virou
`regras_pagamento`, os dois **só** para não colidir. Convenção que ninguém
verifica é uma regra que já foi quebrada e ninguém soube.

Hoje toda pasta é pacote e todo import diz o caminho inteiro. Estes testes
guardam as duas metades disso: que as pastas continuam pacotes, e que nenhum
subdiretório do repositório voltou ao `sys.path` — porque é a volta dele, e só
ela, que faz dois módulos de mesmo nome curto disputarem o mesmo lugar.

São de texto e de caminho: não abrem janela e não importam aba nenhuma.
"""
import importlib.util
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent

#: Não são pasta de código do app nem de ferramenta: não se cobra pacote delas.
_NAO_SAO_CODIGO = {"tests", "docs", "supabase", ".github", ".git",
                   "__pycache__", "codigo", "codigo_embutido", "spec",
                   "fixtures", "migrations", "venv", ".venv", "build", "dist"}


def _pastas_com_py() -> list[Path]:
    """Toda pasta do repositório que tem `.py` — descoberta, nunca escrita.

    Descoberta pelo mesmo motivo do `test_empacotamento.py`: pasta nova nasce
    vigiada, sem ninguém precisar lembrar de acrescentá-la a uma lista.
    """
    achadas = set()
    for arq in _RAIZ.rglob("*.py"):
        pasta = arq.parent
        if pasta == _RAIZ:
            continue
        rel = pasta.relative_to(_RAIZ)
        if any(p in _NAO_SAO_CODIGO or p.startswith(".") for p in rel.parts):
            continue
        achadas.add(pasta)
    return sorted(achadas)


def test_toda_pasta_de_codigo_e_um_pacote():
    """Pasta sem `__init__.py` só se importa pondo-a no `sys.path`.

    E pôr uma pasta no `sys.path` é pôr TODOS os nomes curtos dela num espaço
    que já tem os das outras. A `conciliacao/` foi a primeira a ser pacote de
    verdade, em julho; as outras treze a seguiram em 02/09/2026.
    """
    sem_init = [p.relative_to(_RAIZ).as_posix()
                for p in _pastas_com_py() if not (p / "__init__.py").is_file()]
    assert not sem_init, (
        f"estas pastas têm `.py` e não são pacotes: {sem_init}. Sem "
        "`__init__.py` elas só se importam entrando no `sys.path`, e lá dentro "
        "nome de módulo é global: dois `config.py` viram um só, e quem perde é "
        "quem entrou primeiro. Conserto: um `__init__.py` com uma linha "
        "dizendo o que a pasta é.")


def test_nenhum_subdiretorio_do_repositorio_esta_no_sys_path():
    """A causa mecânica da colisão, medida onde ela acontece.

    A RAIZ pode (e precisa) estar no caminho — é ela que faz `import
    pagamentos_dia.relatorio` funcionar. Qualquer pasta ABAIXO dela, não: é
    exatamente a linha que devolve o espaço plano.

    Este teste vê o `sys.path` do processo do pytest, então ele pega tanto uma
    linha nova num módulo do app (importado por algum teste) quanto uma num
    arquivo de teste — que foi de onde as últimas sumiram.
    """
    intrusas = []
    for entrada in sys.path:
        if not entrada:
            continue
        try:
            caminho = Path(entrada).resolve()
        except (OSError, ValueError):     # entrada estranha do ambiente
            continue
        if caminho == _RAIZ or _RAIZ not in caminho.parents:
            continue
        if any(p in _NAO_SAO_CODIGO for p in caminho.relative_to(_RAIZ).parts):
            continue
        intrusas.append(caminho.relative_to(_RAIZ).as_posix())

    assert not intrusas, (
        f"estas subpastas do repositório voltaram ao `sys.path`: {intrusas}. "
        "Com elas ali, os nomes curtos de todas as pastas dividem um espaço "
        "só e `import config` passa a depender da ORDEM do caminho. Importe "
        "pelo pacote (`from anexar import config`) e apague o "
        "`sys.path.insert`.")


def _nomes_repetidos() -> dict:
    """{'config': ['acessorias', 'anexar', 'conciliacao'], ...}"""
    onde = {}
    for pasta in _pastas_com_py():
        for arq in pasta.glob("*.py"):
            if arq.stem.startswith("__"):
                continue
            onde.setdefault(arq.stem, []).append(
                pasta.relative_to(_RAIZ).as_posix())
    return {n: sorted(ps) for n, ps in onde.items() if len(ps) > 1}


def test_nome_curto_repetido_nao_e_importavel_por_nome_curto():
    """A prova do outro lado: o nome repetido não resolve sozinho.

    O teste acima olha o `sys.path`; este pergunta ao próprio Python. São
    perguntas diferentes e as duas importam: um `.pth`, um `PYTHONPATH` na
    máquina de quem roda ou um `sys.modules` sujo por outro teste também
    tornariam `import config` resolvível, sem nenhuma linha nova no
    repositório.

    Só interessa o que resolve para DENTRO do repositório. Um pacote instalado
    que por acaso se chame `config` é problema dele, não nosso.
    """
    achados = {}
    for nome, pastas in _nomes_repetidos().items():
        origem = None
        if nome in sys.modules:
            origem = getattr(sys.modules[nome], "__file__", None)
        if origem is None:
            try:
                spec = importlib.util.find_spec(nome)
            except (ImportError, ValueError):
                spec = None
            origem = getattr(spec, "origin", None) if spec else None
        if not origem:
            continue
        try:
            dentro = _RAIZ in Path(origem).resolve().parents
        except (OSError, ValueError):
            continue
        if dentro:
            achados[nome] = (pastas, Path(origem).resolve()
                             .relative_to(_RAIZ).as_posix())

    assert not achados, (
        "estes nomes existem em mais de uma pasta E continuam importáveis pelo "
        f"nome curto: {achados}. Quem escrever `import config` vai receber um "
        "dos dois, escolhido pela ordem do `sys.path` — e o outro módulo "
        "some sem erro. Importe pelo pacote: `from anexar import config`.")


def test_os_nomes_repetidos_continuam_repetidos():
    """A allowlist ao contrário: se nada mais colide, este arquivo perdeu o dono.

    Os dois testes acima ficariam verdes num repositório onde os nomes curtos
    fossem todos únicos — e aí eles não provariam nada, só pareceriam provar.
    Enquanto houver `config.py` em três pastas, o que eles medem tem risco de
    verdade. Sumindo a repetição, alguém lê isto e decide se apaga o arquivo.
    """
    repetidos = _nomes_repetidos()
    assert repetidos, (
        "nenhum nome de módulo se repete mais no repositório. Os testes deste "
        "arquivo passaram a guardar um risco que não existe — leia-os e decida "
        "se ainda valem.")
