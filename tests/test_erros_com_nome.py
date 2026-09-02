# -*- coding: utf-8 -*-
"""O `widgets.explicar_erro`: a exceção vira o que houve, de quem é e o que fazer.

Dez diálogos do app mostravam a exceção CRUA, e o que a pessoa lia era
`HTTPSConnectionPool(host='...'): Max retries exceeded` ou
`[Errno 13] Permission denied: 'C:/.../remessa.xlsx'`. Nenhum dos dois diz de
quem é a falha — e é essa parte que decide se a pessoa espera, se reclama com
quem cuida do cadastro ou se simplesmente fecha o Excel.

Um teste por FAMÍLIA, porque a diferença entre elas é justamente o conselho:
"tente de novo" e "avise quem cuida do cadastro" são opostos.

Sem tela nenhuma: `explicar_erro` é texto sobre exceção, e roda no CI.
"""
import pytest

import widgets


# As famílias reais, importadas dos módulos onde elas vivem. Não são dublês: se
# alguém renomear `SemRede`, este arquivo para de importar — que é exatamente o
# aviso que se quer, já que a `explicar_erro` casa pelo NOME da classe.
from conciliacao import errors as erros_conc
from erp import sessao as erp_sessao
from nuvem import rest


class TimeoutError(Exception):                        # noqa: A001
    """O `TimeoutError` do Playwright, em pé de igualdade com o de verdade.

    O de verdade só existe com o pacote instalado, e teste que PULA não aparece
    em vermelho — foi assim que nove testes do campo de data sumiram por um
    momento. Como a `explicar_erro` casa pelo NOME da classe, esta aqui
    exercita exatamente o mesmo caminho, sempre. O Playwright de verdade tem
    teste próprio logo abaixo, e esse pode pular."""


def _partes(exc):
    o_que, de_quem, passo = widgets.explicar_erro(exc)
    assert o_que and de_quem and passo, "alguma das três partes veio vazia"
    return o_que, de_quem, passo


# ------------------------------------------------------------------ famílias
def test_sessao_do_erp():
    o_que, de_quem, passo = _partes(erp_sessao.SessaoRecusada("401", codigo=401))
    assert "ERP" in o_que
    assert "ERP" in de_quem and "não do app" in de_quem
    # A regra que a pessoa precisa lembrar aqui, e que nenhum texto de
    # biblioteca diria: o ERP aceita UMA sessão por usuário.
    assert "uma sessão" in passo.lower()


def test_sessao_expirada_da_conciliacao_e_a_mesma_familia():
    """`conciliacao.errors.SessaoExpirada` e `erp.sessao.SessaoRecusada` são a
    mesma coisa com dois nomes: pedem o mesmo de quem lê."""
    assert (widgets.explicar_erro(erros_conc.SessaoExpirada("caiu"))
            == widgets.explicar_erro(erp_sessao.SessaoRecusada("caiu")))


def test_erro_generico_do_erp():
    o_que, de_quem, passo = _partes(erp_sessao.ErpErro("500", codigo=500))
    assert "ERP" in o_que and "ERP" in de_quem
    assert "preencheu" in de_quem, (
        "o texto não tira a culpa de quem preencheu, que é o primeiro palpite "
        "de quem lê um erro")


def test_erp_error_da_conciliacao_cai_na_mesma_familia():
    assert (widgets.explicar_erro(erros_conc.ErpError("grade sumiu"))
            == widgets.explicar_erro(erp_sessao.ErpErro("grade sumiu")))


def test_sem_rede():
    o_que, de_quem, passo = _partes(rest.SemRede("Max retries exceeded"))
    assert "servidor" in o_que.lower()
    assert "internet" in de_quem.lower()
    assert "conex" in passo.lower()
    # O texto cru da biblioteca de rede não pode vazar para a tela.
    assert "Max retries" not in " ".join((o_que, de_quem, passo))


def test_sem_rede_do_navegador_usa_a_mensagem_que_ja_vem_pronta():
    """O `anexar/mc_client.SemRede` promete no docstring que a mensagem dele já
    está escrita para o usuário. A da nuvem não promete, e por isso é
    substituída."""
    mc_client = pytest.importorskip("anexar.mc_client")
    pronta = "Sem internet: não consegui abrir o Mais Controle."
    o_que, _, _ = _partes(mc_client.SemRede(pronta))
    assert o_que == pronta


def test_precisa_entrar_usa_a_frase_que_o_sessao_montou():
    """Só o `nuvem/sessao.py` sabe separar "sem internet e a sessão venceu" de
    "a sessão não vale mais". A frase dele é consumida como está."""
    o_que, de_quem, passo = _partes(
        rest.PrecisaEntrar("sem internet e a sessão salva venceu"))
    assert o_que.startswith("Sem internet e a sessão salva venceu")
    assert "login do app" in de_quem
    assert "abra o app" in passo


def test_precisa_entrar_sem_mensagem_ainda_diz_alguma_coisa():
    o_que, _, _ = _partes(rest.PrecisaEntrar())
    assert "sessão" in o_que.lower()


def test_recusado_pelo_banco():
    o_que, de_quem, passo = _partes(
        rest.RecusadoPeloBanco("HTTP 409: duplicate key"))
    assert "recus" in o_que.lower()
    # A parte que evita a viagem errada: não é a senha, e não é a internet.
    assert "senha" in de_quem and "internet" in de_quem
    assert "cadastro" in passo


def test_tempo_esgotado():
    o_que, de_quem, passo = _partes(TimeoutError("Timeout 45000ms exceeded"))
    assert "espera" in o_que.lower()
    assert "não do app" in de_quem
    assert "lento" in passo


def test_o_timeout_do_playwright_de_verdade_cai_na_mesma_familia():
    erros = pytest.importorskip("playwright.sync_api")
    assert (widgets.explicar_erro(erros.TimeoutError("45000ms"))
            == widgets.explicar_erro(TimeoutError("45000ms")))


def test_arquivo_aberto_no_excel():
    """O clássico daqui: a planilha do dia aberta no Excel enquanto a rotina
    tenta gravar por cima."""
    e = PermissionError(13, "Permission denied",
                        "C:/Pagamentos do dia/02-09-2026.xlsx")
    o_que, de_quem, passo = _partes(e)
    assert "Windows" in o_que
    # O caminho TEM de aparecer: "feche o arquivo no Excel" sem dizer qual
    # arquivo é conselho pela metade.
    assert "02-09-2026.xlsx" in o_que
    assert "aberto" in de_quem
    assert "Excel" in passo


def test_outro_erro_de_arquivo():
    o_que, de_quem, passo = _partes(
        FileNotFoundError(2, "No such file or directory", "C:/some/pasta"))
    assert "gravar o arquivo" in o_que
    assert "C:/some/pasta" in o_que
    assert "computador" in de_quem


def test_o_timeout_embutido_nao_cai_no_saco_de_arquivo():
    """O `TimeoutError` embutido do Python É subclasse de `OSError`, e "esperei
    demais" não pede a mesma coisa que "o disco não deixou". A ordem do
    `explicar_erro` depende disto."""
    import builtins

    o_que, _, _ = _partes(builtins.TimeoutError("timed out"))
    assert "espera" in o_que.lower()


def test_o_generico_e_honesto_sobre_nao_saber():
    """Cair no genérico é legítimo; esconder o erro original não é — quem for
    consertar precisa do tipo e da mensagem."""
    o_que, de_quem, passo = _partes(ValueError("time data 'x' does not match"))
    assert "ValueError" in o_que
    assert "time data 'x' does not match" in o_que
    assert "não tem nome conhecido" in de_quem
    assert "quem cuida do app" in passo


def test_erro_sem_mensagem_nao_devolve_parte_vazia():
    o_que, _, _ = _partes(RuntimeError())
    assert o_que == "RuntimeError"


# ------------------------------------------------------------------ a caixa
def test_o_recado_junta_o_que_a_tela_tentava_com_o_que_houve():
    texto = widgets.recado_de_erro(rest.SemRede(),
                                   "Não consegui ler o cadastro.")
    linhas = [l for l in texto.splitlines() if l.strip()]
    assert linhas[0] == "Não consegui ler o cadastro."
    assert len(linhas) == 4, (
        "a caixa tem de ter o passo da tela mais as três partes: " + texto)


def test_sem_o_passo_da_tela_o_recado_e_so_as_tres_partes():
    texto = widgets.recado_de_erro(rest.SemRede())
    assert len([l for l in texto.splitlines() if l.strip()]) == 3


# ------------------------------------------------ o login não tem cópia disso
def test_o_login_usa_a_funcao_do_widgets_em_vez_de_uma_copia():
    """O `_frase` do `nuvem/login_dialogo.py` era a melhor peça de texto do
    projeto e valia só para UMA janela. Ela virou a `widgets.explicar_erro`, e
    o login passou a chamá-la: duas cópias da mesma verdade envelhecem
    separadas, e foi o que já aconteceu com o mapa de contas e com o pacote do
    CNAB."""
    from nuvem import login_dialogo

    for e in (rest.SemRede(), rest.RecusadoPeloBanco("HTTP 500"),
              rest.PrecisaEntrar("a sessão salva não vale mais"),
              ValueError("qualquer outra coisa")):
        assert login_dialogo._frase(e) == widgets.recado_de_erro(e), (
            f"o login voltou a traduzir {type(e).__name__} por conta própria")
