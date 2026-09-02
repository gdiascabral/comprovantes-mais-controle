# -*- coding: utf-8 -*-
"""A lista do `codigo.zip` é escrita à mão, e quem esquece dela não sente falta.

O `build.yml` monta o pacote de código copiando pasta por pasta, uma linha por
pasta. Quem cria uma aba nova precisa lembrar de acrescentar a linha lá — e o
preço de esquecer é o pior que existe aqui: os 749 testes passam (na máquina de
quem escreve o código está tudo no disco), o CI passa, a release sai, e o app
**não abre** na máquina de quem usa, porque o `import` da aba estoura antes de
existir janela para mostrar o erro. É a mesma família do `tkinter.font` da
v1.0.71 e do `cnab240/spec/*.json`: o que ninguém copia não chega no usuário.

O `test_cnab240_pacote.py` já faz esta vigilância para UM pacote, comparando
duas strings literais. Este arquivo generaliza: em vez de uma lista à mão para
vigiar outra lista à mão, ele **descobre** as pastas de código no repositório
(as que têm `.py` rastreados pelo git) e cobra cada uma no `build.yml`. Pasta
nova nasce vigiada, sem ninguém precisar lembrar.

O que fica de fora do `codigo.zip` fica de fora **por escrito**, em
`_FORA_DE_PROPOSITO`, com o motivo ao lado — e um teste confere que cada item
dessa lista continua realmente de fora, senão a allowlist envelhece e passa a
perdoar o que não deveria.
"""
import ast
import re
import subprocess
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent
_BUILD_REL = ".github/workflows/build.yml"
_BUILD = _RAIZ / ".github" / "workflows" / "build.yml"

#: Pastas que têm `.py` e NÃO são código do app: nada aqui viaja no codigo.zip.
#: `tests/` roda no CI e na máquina de quem desenvolve; `supabase/` é schema e
#: configuração do banco (o `.py` que houver ali é ferramenta de migração);
#: `docs/` e `.github/` não são executados pelo app em momento nenhum.
_PASTAS_FORA = {"tests", "supabase", "docs", ".github"}

#: Fica FORA do `codigo.zip` de propósito — e cada linha diz por quê.
#: Acrescentar item aqui é decisão, não conveniência: o que entra nesta lista
#: deixa de ser cobrado pelos testes abaixo.
_FORA_DE_PROPOSITO = {
    # O motor é o exe: quem o empacota é o PyInstaller, e ele nunca é lido do
    # codigo.zip (é justamente ele quem BAIXA o zip).
    "motor.py": "é o próprio motor — o PyInstaller o embute no exe",
    # Idem: roda motor-side, antes de existir código novo para rodar.
    "atualizador.py": "roda dentro do exe, antes de o código novo existir",
    # Ferramenta de uma vez só, rodada à mão no repositório com a chave de
    # serviço do Supabase. O app nunca a importa, e ela não pode viajar no zip.
    "nuvem/migrar.py": "ferramenta de administração, rodada à mão no repositório",
}

#: Pastas INTEIRAS que ficam fora do `codigo.zip`, e por quê. É o
#: `_FORA_DE_PROPOSITO` um nível acima: lá a unidade é o arquivo, aqui é a
#: pasta. Vale para ferramenta rodada à mão NO repositório — o app não a
#: importa, então ela não tem por que viajar para a máquina de quem usa.
#:
#: O caminho é comparado inteiro, e não pelo primeiro pedaço como o
#: `_PASTAS_FORA`: `cnab240/ferramentas` sai, `cnab240` continua cobrado.
#: Confundir os dois deixaria o pacote que move dinheiro fora do zip — e essa
#: é a falha que este arquivo inteiro existe para impedir.
_PASTAS_SO_DO_REPO = {
    "cnab240/ferramentas": (
        "ferramentas de validação com o banco, rodadas à mão na máquina que "
        "tem o cadastro; o app nunca as importa"),
    "ferramentas": (
        "ferramenta de desenvolvimento local (fotografa as telas do app "
        "para conferir o visual antes/depois de mexer nele); roda à mão no "
        "repositório e o app nunca a importa"),
}

#: Sempre entram, e não são código: a versão desta build, a trava do motor e o
#: ícone. Ficam aqui para o teste da raiz não os cobrar como se fossem `.py`.
_NAO_SAO_PY = ("versao.txt", "motor_minimo.txt", "icone.ico")


# ------------------------------------------------------------- o repositório
def _rastreados(padrao: str = "") -> list:
    """O que o git conhece, em caminho relativo com "/". `None` sem git."""
    cmd = ["git", "ls-files"] + ([padrao] if padrao else [])
    try:
        saida = subprocess.run(cmd, cwd=_RAIZ, capture_output=True, text=True,
                               timeout=60)
    except (OSError, subprocess.SubprocessError):       # sem git na máquina
        return None
    if saida.returncode != 0 or not saida.stdout.strip():
        return None
    return sorted(l.strip() for l in saida.stdout.splitlines() if l.strip())


def _arquivos_py() -> list[str]:
    """Os `.py` RASTREADOS pelo git, em caminho relativo com "/".

    Rastreado, e não "existe no disco": o que não está no git não chega na
    release, então cobrá-lo no `build.yml` seria acusar defeito que não existe.
    O contrário também vale — arquivo novo já `git add`ado aparece aqui e passa
    a ser cobrado no mesmo instante.
    """
    do_git = _rastreados("*.py")
    if do_git:
        return do_git

    # Cópia sem git (zip do código, por exemplo): vale o disco, tirando o que
    # nunca é rastreado. É o caminho de emergência; no CI o git sempre existe.
    lixo = {".git", "__pycache__", "venv", ".venv", "build", "dist",
            "codigo_embutido", "codigo", ".chrome_profile"}
    achados = []
    for arq in _RAIZ.rglob("*.py"):
        partes = arq.relative_to(_RAIZ).parts
        if any(p in lixo or p.startswith(".") for p in partes[:-1]):
            continue
        achados.append(arq.relative_to(_RAIZ).as_posix())
    return sorted(achados)


def _pastas_de_codigo() -> list[str]:
    """As pastas de código do app, descobertas — nunca escritas à mão.

    "Do app" quer dizer: o que o app importa quando roda na máquina de quem
    usa. Ferramenta que só existe no repositório (`_PASTAS_SO_DO_REPO`) não
    entra, porque cobrá-la no `build.yml` seria mandar para o usuário código
    que ele nunca vai executar.
    """
    pastas = set()
    for arq in _arquivos_py():
        pasta = arq.rsplit("/", 1)[0] if "/" in arq else ""
        if not pasta or pasta.split("/")[0] in _PASTAS_FORA:
            continue
        if pasta in _PASTAS_SO_DO_REPO:
            continue
        pastas.add(pasta)
    return sorted(pastas)


def _py_da_raiz() -> list[str]:
    return sorted(a for a in _arquivos_py() if "/" not in a)


# ----------------------------------------------------------------- o build.yml
def _texto_build() -> str:
    return _BUILD.read_text(encoding="utf-8")


def _linha_para_acrescentar() -> int:
    """Onde a pasta nova tem de entrar: logo ANTES do `Compress-Archive`.

    Depois dele o zip já está fechado, e a linha não teria efeito nenhum —
    falha silenciosa, que é a que este arquivo inteiro existe para evitar.
    """
    for n, linha in enumerate(_texto_build().splitlines(), start=1):
        if "Compress-Archive" in linha:
            return n
    return 0


def _copiadas() -> set:
    """As pastas que o `build.yml` copia: `Copy-Item <pasta>/*.py ...`."""
    return set(re.findall(r"Copy-Item\s+([\w/]+)/\*\.py", _texto_build()))


def _linha_da_raiz() -> str:
    """A linha única que copia os arquivos soltos da raiz para o pacote."""
    for linha in _texto_build().splitlines():
        alvo = linha.strip()
        if alvo.startswith("Copy-Item ") and alvo.endswith("codigo_embutido/"):
            return alvo
    return ""


# ---------------------------------------------------------------------- testes
def test_todo_py_de_codigo_esta_no_git():
    """Arquivo de código IGNORADO é invisível para os testes daqui.

    Eles perguntam ao git o que existe (`git ls-files`), então um `.py` que o
    `.gitignore` engoliu não aparece — e não aparecer é exatamente o que
    ninguém percebe. Aconteceu em 31/08/2026: a regra que protegia o DADO
    `contas_inter.json` (nome de empresa real) foi escrita como
    `contas_inter*`, sem âncora e sem extensão, e casou também com
    `baixar_comprovantes/contas_inter.py`. A suíte passava na máquina de quem
    escreveu, porque lá o arquivo existe; quebrou no CI, que só tem o que o
    git carrega.

    Este teste olha o DISCO e cobra o git — o único ângulo em que o buraco
    aparece.
    """
    rastreados = _rastreados()
    if rastreados is None:
        pytest.skip("sem git para conferir")
    conhecidos = set(rastreados)

    # As pastas só do repositório entram AQUI de volta: elas não vão para o
    # `codigo.zip`, mas continuam sendo código, e um `.gitignore` largo demais
    # as engole do mesmo jeito — foi exatamente o que aconteceu com o
    # `baixar_comprovantes/contas_inter.py`.
    esquecidos = []
    for pasta in _pastas_de_codigo() + sorted(_PASTAS_SO_DO_REPO) + [""]:
        raiz = _RAIZ / pasta if pasta else _RAIZ
        for arquivo in sorted(raiz.glob("*.py")):
            rel = arquivo.relative_to(_RAIZ).as_posix()
            if "__pycache__" in rel or rel in _FORA_DE_PROPOSITO:
                continue
            if rel not in conhecidos:
                esquecidos.append(rel)

    assert not esquecidos, (
        "estes arquivos de código existem no disco e o git NÃO os conhece — "
        "provavelmente engolidos por uma regra do .gitignore larga demais. "
        "Eles não chegam no codigo.zip, e o app quebra na máquina de quem usa: "
        + ", ".join(esquecidos))


def test_toda_pasta_de_codigo_entra_no_codigo_zip():
    """Aba nova sem linha no `build.yml` = app que não abre no usuário.

    Este é o teste que a aba Acessórias, a Conciliação e o cnab240 teriam
    precisado no dia em que nasceram: cada uma dependeu de alguém lembrar.
    """
    pastas = _pastas_de_codigo()
    assert pastas, "nenhuma pasta de código encontrada — o descobridor quebrou"

    copiadas = _copiadas()
    faltando = [p for p in pastas if p not in copiadas]
    onde = _linha_para_acrescentar()
    receita = "\n".join(
        f"            New-Item -ItemType Directory codigo_embutido/{p} | Out-Null\n"
        f"            Copy-Item {p}/*.py codigo_embutido/{p}/" for p in faltando)
    assert not faltando, (
        f"estas pastas de código NÃO entram no codigo.zip: {faltando}. "
        "O `import` da aba estoura na máquina de quem usa, antes de existir "
        "janela para mostrar o erro — o app simplesmente não abre.\n"
        f"Conserto: em {_BUILD_REL}, ANTES da linha {onde} (a do "
        f"`Compress-Archive`), acrescente:\n{receita}\n"
        "Subpasta vem DEPOIS da linha que cria a pasta de cima. E lembre que "
        "mexer no build.yml exige subir o motor_minimo.txt no MESMO push.")


def test_pasta_com_dados_leva_os_dados_junto():
    """`.py` copiado não basta quando o pacote lê arquivo em runtime.

    O `cnab240` é o caso conhecido (`spec/*.json`, guardado em detalhe por
    `test_cnab240_pacote.py`); aqui a checagem é genérica e vale para o próximo:
    arquivo de dados RASTREADO dentro de pasta de código precisa de uma linha
    própria no `build.yml`, senão o pacote importa normalmente e só falha no
    primeiro uso — na máquina de quem usa, no meio de um pagamento.

    Só conta o que o git rastreia. `contas_mc.json`, `contas_sicoob.json`,
    `contas.csv` e companhia ficam FORA do repositório (nome de empresa e
    número de conta) e são regravados como cache ao lado do exe: copiá-los
    seria o defeito, não a correção.
    """
    rastreados = _rastreados()
    if rastreados is None:
        pytest.skip("sem git para distinguir dado versionado de cache local")

    texto = _texto_build()
    codigo = tuple(f"{p}/" for p in _pastas_de_codigo())
    faltando = {}
    for arq in rastreados:
        if not arq.startswith(codigo):
            continue
        pasta, nome = arq.rsplit("/", 1)
        ext = Path(nome).suffix
        if ext in (".py", ".md"):           # código já tem linha; .md é papel
            continue
        if not re.search(rf"Copy-Item\s+{re.escape(pasta)}/\*\{ext}", texto):
            faltando.setdefault(pasta, set()).add(ext)

    assert not faltando, (
        "estas pastas levam DADOS versionados que o codigo.zip não carrega: "
        f"{ {k: sorted(v) for k, v in faltando.items()} }. O pacote vai "
        "importar e falhar só no primeiro uso, longe daqui. Acrescente em "
        f"{_BUILD_REL} a linha que copia esses arquivos, como já é feito com "
        "`Copy-Item cnab240/spec/*.json codigo_embutido/cnab240/spec/`.")


def test_todo_arquivo_da_raiz_que_o_app_importa_entra_no_codigo_zip():
    """A raiz não tem `*.py`: cada arquivo é nomeado um a um na linha.

    Foi assim que o `widgets.py` precisou entrar quando nasceu, e é onde o
    esquecimento é mais fácil — a pasta pelo menos tem uma linha só para ela.
    """
    linha = _linha_da_raiz()
    assert linha, (
        f"não achei em {_BUILD_REL} a linha que copia os arquivos da raiz "
        "para codigo_embutido/ — ela é a que leva comprovantes_app.py.")

    faltando = [a for a in _py_da_raiz()
                if a not in _FORA_DE_PROPOSITO and a not in linha]
    assert not faltando, (
        f"estes arquivos da raiz não entram no codigo.zip: {faltando}. "
        "Ou eles viajam no zip, ou entram em `_FORA_DE_PROPOSITO` com o motivo "
        f"escrito. Conserto: acrescente o nome na linha da raiz do "
        f"{_BUILD_REL}:\n    {linha}")


def test_o_que_nao_e_codigo_continua_entrando():
    """`versao.txt` e `motor_minimo.txt` no zip são o que sustenta a atualização.

    Sem o `versao.txt` o app não sabe se o código baixado é mais novo que o
    embutido; sem o `motor_minimo.txt` o código novo roda em motor velho sem
    ninguém perceber. Os dois são gerados/lidos fora do `.py`, então nenhum
    outro teste sentiria a falta.
    """
    linha = _linha_da_raiz()
    faltando = [a for a in _NAO_SAO_PY if a not in linha]
    assert not faltando, (
        f"o codigo.zip saiu sem {faltando} — acrescente na linha da raiz do "
        f"{_BUILD_REL}. Sem versao.txt/motor_minimo.txt a atualização perde a "
        "referência do que é novo e do que exige motor novo.")


def test_a_allowlist_nao_apodrece():
    """Allowlist que perdoa o que já entrou é pior do que não existir.

    Cada item de `_FORA_DE_PROPOSITO` tem de (a) existir no repositório e
    (b) continuar fora do pacote. Se um dia o `migrar.py` passar a ser copiado,
    é aqui que se descobre — e não por uma chave de serviço viajando no zip.
    """
    texto = _texto_build()
    for arquivo, motivo in _FORA_DE_PROPOSITO.items():
        assert (_RAIZ / arquivo).is_file(), (
            f"`{arquivo}` está em _FORA_DE_PROPOSITO ({motivo}) mas não existe "
            "mais: apague a entrada, para a lista não guardar fantasma.")

    copiadas = _copiadas()
    for pasta, motivo in _PASTAS_SO_DO_REPO.items():
        assert (_RAIZ / pasta).is_dir(), (
            f"`{pasta}` está em _PASTAS_SO_DO_REPO ({motivo}) mas não existe "
            "mais: apague a entrada, para a lista não guardar fantasma.")
        assert pasta not in copiadas, (
            f"`{pasta}` está em _PASTAS_SO_DO_REPO ({motivo}) e passou a ser "
            f"copiada no {_BUILD_REL}. Ou ela é código do app — e aí sai da "
            "lista e ganha uma linha de verdade —, ou a linha do build.yml é "
            "que está sobrando.")

    assert "-Exclude migrar.py" in texto, (
        "a pasta `nuvem` é copiada inteira: o `migrar.py` (ferramenta de "
        "administração, roda com a chave de serviço) passou a viajar no "
        f"codigo.zip. Devolva o `-Exclude migrar.py` no {_BUILD_REL}.")

    linha = _linha_da_raiz()
    intrusos = [a for a in ("motor.py", "atualizador.py") if a in linha]
    assert not intrusos, (
        f"{intrusos} entrou no codigo.zip. Quem os empacota é o PyInstaller; "
        "no zip eles seriam uma segunda cópia, capaz de divergir do exe que "
        "está rodando.")


def test_o_build_nao_copia_pasta_que_nao_existe_mais():
    """Pasta renomeada deixa a linha velha para trás, e o `Copy-Item` falha.

    Falha barulhenta, mas cara: quebra a build DEPOIS dos testes e do
    PyInstaller, e build que falha CONSOME o número da release.
    """
    fantasmas = sorted(p for p in _copiadas() if not (_RAIZ / p).is_dir())
    assert not fantasmas, (
        f"o {_BUILD_REL} copia pastas que não existem mais: {fantasmas}. "
        "A build vai quebrar no `Copy-Item` — e queimar o número da release.")


def test_a_lista_do_test_imports_do_motor_acompanha_o_repositorio():
    """A segunda lista à mão, que ninguém lembra de atualizar.

    `test_imports_do_motor.py` percorre `_PASTAS` para saber onde procurar
    import de stdlib que o exe não tem. Pasta de fora daquela tupla não é
    examinada: o teste continua verde e para de guardar a aba nova — o modo de
    falhar mais caro que existe num teste, porque ele parece estar trabalhando.
    """
    fonte = (_RAIZ / "tests" / "test_imports_do_motor.py").read_text(
        encoding="utf-8")
    valor = None
    for no in ast.walk(ast.parse(fonte)):
        if (isinstance(no, ast.Assign) and len(no.targets) == 1
                and getattr(no.targets[0], "id", "") == "_PASTAS"):
            valor = ast.literal_eval(no.value)
    assert valor is not None, "não achei `_PASTAS` em test_imports_do_motor.py"

    faltando = sorted(set(_pastas_de_codigo()) - set(valor))
    assert not faltando, (
        f"`_PASTAS` em tests/test_imports_do_motor.py não conhece {faltando}: "
        "os imports dessas pastas não estão sendo comparados com o que o exe "
        "contém. Acrescente-as à tupla — é a lista que guarda a armadilha do "
        "`tkinter.font` (v1.0.71).")
    assert "" in valor, (
        "`_PASTAS` deixou de examinar a raiz (o item \"\"), que é onde moram "
        "comprovantes_app.py, util.py e widgets.py.")
