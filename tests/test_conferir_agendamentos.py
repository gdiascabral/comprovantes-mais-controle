# -*- coding: utf-8 -*-
"""O motor do "Conferir agendamentos", separado da tela da Remessa/Retorno
para a aba "Pagamentos do dia" usar o MESMO (pedido do dono, 23/10/2026).

Sem Chrome e sem banco: o `SicoobClient` e o `pendencias.ler_conta` são
dublês. Dados FICTÍCIOS (repo público)."""
import datetime as dt
from types import SimpleNamespace as NS

import pytest

from extratos_sicoob import pendencias
from pagamentos_dia import agendamentos_sicoob as A
from pagamentos_dia import conferir_agendamentos as ca

INI, FIM = dt.date(2026, 9, 1), dt.date(2026, 11, 30)


def _conta(nome, *centavos):
    return {"nome": nome, "entries": [
        {"centavos": c, "favorecido": "Loja Exemplo", "descricao": f"OC {c}"}
        for c in centavos]}


def _pendencia(centavos):
    return {"valor": centavos / 100, "detalhe": "LOJA EXEMPLO",
            "nomeTransacao": "Pagamento de Título",
            "situacao": A.PENDENTE_ASSINATURA, "pendencia": centavos}


class _Cliente:
    """O Chrome do Sicoob de mentira: cada sessão (`with`) enxerga um
    conjunto de contas, como um login do SicoobNet."""

    def __init__(self, contas, abertos):
        self.contas = list(contas)
        self.abertos = abertos

    def __enter__(self):
        self.abertos.append(self)
        return self

    def __exit__(self, *a):
        return False

    def aguardar_login(self):
        pass

    def listar_contas(self):
        return list(self.contas)


def _abrir(*logins):
    """`abrir()` devolve um login por vez, na ordem dada."""
    abertos, fila = [], list(logins)

    def abrir():
        return _Cliente(fila.pop(0), abertos)
    return abrir, abertos


def _ler_conta(agendado):
    """`ler_conta` de mentira: a conta que o login não enxerga dá a MESMA
    falha do `pendencias.ler_conta` de verdade."""
    def ler(cli, numero, inicio, fim):
        if numero not in cli.contas:
            raise pendencias.PendenciasFalhou(pendencias.FORA_DESTE_LOGIN)
        return [_pendencia(c) for c in agendado.get(numero, ())]
    return ler


def _separado(*pares):
    """`no_sicoob` como o `separar` devolve: (conta do HTML, número, '')."""
    return [(_conta(nome, *cents), numero, "") for nome, numero, cents in pares]


# ------------------------------------------------------------ separar


def test_separar_divide_sicoob_outro_banco_e_cadastro(monkeypatch):
    respostas = {"A - SICOOB": ("11.111-1", ""),
                 "B - INTER": ("", A.MOTIVO_FORA_SICOOB),
                 "C - SICOOB": ("", A.MOTIVO_CONTA_DESCONHECIDA)}
    monkeypatch.setattr(A, "conta_sicoob", lambda nome, m, e: respostas[nome])
    sep = ca.separar([_conta(n, 100) for n in respostas], None, None)
    assert [c["nome"] for c, _n, _m in sep.no_sicoob] == ["A - SICOOB"]
    assert [c["nome"] for c, _n, _m in sep.fora] == ["B - INTER", "C - SICOOB"]
    assert [c["nome"] for c, _m in sep.sem_cadastro] == ["C - SICOOB"]
    assert sep.recusa() is None


def test_sem_conta_do_sicoob_com_cadastro_torto_e_aviso_e_nao_recado_neutro(monkeypatch):
    monkeypatch.setattr(A, "conta_sicoob",
                        lambda nome, m, e: ("", A.MOTIVO_CONTA_DESCONHECIDA))
    nivel, texto = ca.separar([_conta("C - SICOOB", 100)], None, None).recusa()
    assert nivel == "aviso"
    assert "confira-as à mão antes de assinar" in texto and "C - SICOOB" in texto


def test_so_outro_banco_e_recado_neutro(monkeypatch):
    monkeypatch.setattr(A, "conta_sicoob", lambda nome, m, e: ("", A.MOTIVO_FORA_SICOOB))
    nivel, texto = ca.separar([_conta("B - INTER", 100)], None, None).recusa()
    assert nivel == "info" and "Nenhuma conta deste HTML é do Sicoob" in texto


def test_pergunta_de_abrir_diz_que_e_so_leitura():
    texto = ca.pergunta_de_abrir(3, INI, FIM)
    assert "3 conta(s)" in texto and "01/09 a 30/11/2026" in texto
    assert "nada é assinado, cancelado nem alterado" in texto


def test_recado_em_uso_diz_quem():
    assert "Extratos Sicoob" in ca.recado_em_uso("Extratos Sicoob")


# ------------------------------------------------------------ ler no banco


def test_um_login_so_le_e_confronta_como_a_remessa():
    abrir, abertos = _abrir(["11.111-1"])
    registro = []
    confs = ca.ler_no_banco(_separado(("A - SICOOB", "11.111-1", (100, 250))),
                            [(_conta("B - INTER", 9), "", A.MOTIVO_FORA_SICOOB)],
                            INI, FIM, log=registro.append, abrir=abrir,
                            ler_conta=_ler_conta({"11.111-1": (100, 250)}))
    assert [c.conta_erp for c in confs] == ["B - INTER", "A - SICOOB"]
    inter, sicoob = confs
    assert inter.motivo == A.MOTIVO_FORA_SICOOB and not inter.falhou
    assert sicoob.conferida and sicoob.pior == A.OK
    assert len(abertos) == 1
    assert any("A - SICOOB (11.111-1)" in r for r in registro)


def test_sem_pergunta_a_conta_de_outro_login_fica_vermelha_como_antes():
    """A Remessa/Retorno não passa `perguntar`: nada muda para ela."""
    abrir, abertos = _abrir(["11.111-1"])
    confs = ca.ler_no_banco(_separado(("A", "11.111-1", (100,)), ("M", "22.222-2", (300,))),
                            [], INI, FIM, log=lambda m: None, abrir=abrir,
                            ler_conta=_ler_conta({"11.111-1": (100,), "22.222-2": (300,)}))
    assert len(abertos) == 1
    moura = confs[1]
    assert moura.falhou
    assert moura.motivo == f"o Sicoob não respondeu: {pendencias.FORA_DESTE_LOGIN}"


def test_conta_de_outro_acesso_le_no_segundo_login_so_as_que_faltaram():
    abrir, abertos = _abrir(["11.111-1"], ["22.222-2"])
    perguntas, lidas = [], []
    ler = _ler_conta({"11.111-1": (100,), "22.222-2": (300,)})

    def ler_contando(cli, numero, inicio, fim):
        lidas.append((len(abertos), numero))
        return ler(cli, numero, inicio, fim)

    confs = ca.ler_no_banco(_separado(("A", "11.111-1", (100,)), ("M", "22.222-2", (300,))),
                            [], INI, FIM, log=lambda m: None, abrir=abrir,
                            ler_conta=ler_contando,
                            perguntar=lambda faltam: perguntas.append(faltam) or True)
    assert perguntas == [["M"]]
    assert lidas == [(1, "11.111-1"), (1, "22.222-2"), (2, "22.222-2")]
    assert all(c.conferida and c.pior == A.OK for c in confs)


def test_dono_diz_nao_ao_outro_acesso_e_a_conta_fica_nao_conferida():
    abrir, abertos = _abrir(["11.111-1"], ["22.222-2"])
    confs = ca.ler_no_banco(_separado(("A", "11.111-1", (100,)), ("M", "22.222-2", (300,))),
                            [], INI, FIM, log=lambda m: None, abrir=abrir,
                            ler_conta=_ler_conta({}), perguntar=lambda faltam: False)
    assert len(abertos) == 1
    assert confs[1].falhou and pendencias.FORA_DESTE_LOGIN in confs[1].motivo


def test_chrome_que_volta_no_mesmo_acesso_nao_le_de_novo_e_explica():
    abrir, abertos = _abrir(["11.111-1"], ["11.111-1"])
    lidas = []
    ler = _ler_conta({})
    confs = ca.ler_no_banco(_separado(("A", "11.111-1", ()), ("M", "22.222-2", (300,))),
                            [], INI, FIM, log=lambda m: None, abrir=abrir,
                            ler_conta=lambda *a: lidas.append(a[1]) or ler(*a),
                            perguntar=lambda faltam: True)
    assert len(abertos) == 2
    assert lidas == ["11.111-1", "22.222-2"]          # nada lido no 2º login
    assert confs[1].falhou and confs[1].motivo == ca.MESMO_ACESSO
    assert "Conferir agendamentos" in ca.MESMO_ACESSO


def test_conta_que_nao_esta_em_nenhum_dos_dois_acessos_diz_isso():
    abrir, _ = _abrir(["11.111-1"], ["33.333-3"])
    confs = ca.ler_no_banco(_separado(("A", "11.111-1", ()), ("M", "22.222-2", (300,))),
                            [], INI, FIM, log=lambda m: None, abrir=abrir,
                            ler_conta=_ler_conta({}), perguntar=lambda faltam: True)
    assert confs[1].falhou and confs[1].motivo == ca.EM_NENHUM_ACESSO


def test_segundo_login_que_falha_nao_perde_o_primeiro():
    abertos = []

    def abrir():
        if abertos:
            raise RuntimeError("tempo esgotado esperando o login\nlog do Playwright")
        return _Cliente(["11.111-1"], abertos)

    confs = ca.ler_no_banco(_separado(("A", "11.111-1", (100,)), ("M", "22.222-2", (300,))),
                            [], INI, FIM, log=lambda m: None, abrir=abrir,
                            ler_conta=_ler_conta({"11.111-1": (100,)}),
                            perguntar=lambda faltam: True)
    assert confs[0].conferida and confs[0].pior == A.OK
    assert confs[1].falhou
    assert confs[1].motivo == ("o outro acesso do Sicoob não entrou: "
                               "tempo esgotado esperando o login")


def test_parar_antes_da_pergunta_nao_abre_o_outro_acesso():
    abrir, abertos = _abrir(["11.111-1"], ["22.222-2"])
    perguntas = []
    confs = ca.ler_no_banco(_separado(("A", "11.111-1", ()), ("M", "22.222-2", (300,))),
                            [], INI, FIM, log=lambda m: None, abrir=abrir,
                            ler_conta=_ler_conta({}), perguntar=perguntas.append,
                            parar=lambda: True)
    assert perguntas == [] and len(abertos) == 1 and confs[1].falhou


def test_login_que_cai_no_meio_deixa_as_que_faltavam_com_o_porque():
    class _Cai(_Cliente):
        def aguardar_login(self):
            raise RuntimeError("o Chrome do Sicoob fechou")

    confs = ca.ler_no_banco(_separado(("A", "11.111-1", (100,))), [], INI, FIM,
                            log=lambda m: None,
                            abrir=lambda: _Cai([], []), ler_conta=_ler_conta({}),
                            perguntar=lambda faltam: pytest.fail("não pergunta"))
    assert confs[0].falhou
    assert confs[0].motivo == A.motivo_da_parada(RuntimeError("o Chrome do Sicoob fechou"))


def test_falha_de_uma_conta_nao_e_tratada_como_outro_acesso():
    """Só "não aparece neste login" leva ao outro acesso; HTTP 500 numa
    conta não é motivo para abrir o Chrome de novo."""
    abrir, abertos = _abrir(["11.111-1"])

    def ler(cli, numero, inicio, fim):
        raise pendencias.PendenciasFalhou("transacao-pendente/consultar devolveu HTTP 500")

    confs = ca.ler_no_banco(_separado(("A", "11.111-1", (100,))), [], INI, FIM,
                            log=lambda m: None, abrir=abrir, ler_conta=ler,
                            perguntar=lambda faltam: pytest.fail("não pergunta"))
    assert len(abertos) == 1 and confs[0].falhou and "HTTP 500" in confs[0].motivo


def test_duas_contas_do_erp_no_mesmo_numero_sao_lidas_juntas_uma_vez():
    abrir, _ = _abrir(["11.111-1"])
    lidas = []
    ler = _ler_conta({"11.111-1": (100,)})
    confs = ca.ler_no_banco(_separado(("A", "11.111-1", (100,)), ("A2", "11.111-1", (100,))),
                            [], INI, FIM, log=lambda m: None, abrir=abrir,
                            ler_conta=lambda *a: lidas.append(a[1]) or ler(*a))
    assert lidas == ["11.111-1"]
    assert [c.conta_erp for c in confs] == ["A + A2"]
    assert confs[0].pior != A.OK                 # um agendado para dois pagamentos


def test_pendencias_usa_a_frase_do_motor():
    cli = NS(page=None, acessar_conta=lambda n: False)
    with pytest.raises(pendencias.PendenciasFalhou) as e:
        pendencias.ler_conta(cli, "11.111-1", INI, FIM)
    assert str(e.value) == pendencias.FORA_DESTE_LOGIN


def test_remessa_usa_o_motor_e_nao_uma_copia():
    """O frame da Remessa chama o motor: a regra mora num lugar só."""
    from pathlib import Path
    frame = (Path(ca.__file__).parent / "pagamentos_frame.py").read_text(encoding="utf-8")
    assert "conferir_agendamentos.ler_no_banco(" in frame
    assert "conferir_agendamentos.abrir_janela(" in frame
    assert "conferir_agendamentos.separar(" in frame
    assert "pendencias.ler_conta" not in frame
    assert "A.confrontar(" not in frame



def test_import_do_chrome_que_falha_nao_deixa_a_thread_muda(monkeypatch):
    """Revisão de 23/10/2026: o import do SicoobClient fora do try fazia a
    thread da Remessa morrer sem pôr nada na fila — botão apagado para
    sempre. Agora a falha vira o porquê de cada conta."""
    import sys
    monkeypatch.setitem(sys.modules, "extratos_sicoob.sicoob_client", None)
    registro = []
    confs = ca.ler_no_banco(_separado(("A", "11.111-1", (100,))), [], INI, FIM,
                            log=registro.append, ler_conta=_ler_conta({}))
    assert len(confs) == 1 and confs[0].falhou
    assert confs[0].motivo.startswith(A.MOTIVO_NAO_LIDA)
    assert any("Conferir agendamentos" in r for r in registro)


def _remessa(monkeypatch, tmp_path, ocupado_depois):
    """A Remessa por __new__, com o HTML escolhido e a pergunta respondida
    "OK"; `ocupado_depois` é quem pegou o Sicoob enquanto ela estava aberta."""
    from pagamentos_dia import pagamentos_frame as pf
    html = tmp_path / "pagamentos_2026-10-23.html"
    html.write_text("<html><script>\nconst DATA = "
                    + __import__("json").dumps({"contas": [{"nome": "A - SICOOB",
                                                             "entries": []}]})
                    + ";\n</script></html>", encoding="utf-8")
    aba = pf.PagamentosDiaFrame.__new__(pf.PagamentosDiaFrame)
    aba._agendamentos = None
    quem = {"agora": None}
    aba.sicoob_ocupado = lambda: quem["agora"]
    aba._html_sugerido = lambda: None
    aba.b_agend = NS(configure=lambda **k: estados.append(k))
    estados, criadas, avisos = [], [], []
    aba._log = lambda m="": None
    monkeypatch.setattr(pf.filedialog, "askopenfilename", lambda **k: str(html))
    monkeypatch.setattr(pf, "_carregar_mapas", lambda: (None, None))
    monkeypatch.setattr(A, "conta_sicoob", lambda n, m, e: ("11.111-1", ""))

    def ok(*a, **k):
        quem["agora"] = ocupado_depois
        return True
    monkeypatch.setattr(pf.messagebox, "askokcancel", ok)
    monkeypatch.setattr(pf.messagebox, "showinfo", lambda t, txt, **k: avisos.append(txt))

    class _Thread:
        def __init__(self, **k):
            criadas.append(k)

        def start(self):
            pass
    monkeypatch.setattr(pf, "Thread", _Thread)
    return aba, estados, criadas, avisos


def test_remessa_confere_o_sicoob_de_novo_depois_da_pergunta(monkeypatch, tmp_path):
    aba, estados, criadas, avisos = _remessa(
        monkeypatch, tmp_path, "Pagamentos do dia — lendo o saldo do Sicoob")
    aba._conferir_agendamentos()
    assert criadas == [] and estados == []
    assert len(avisos) == 1 and "lendo o saldo do Sicoob" in avisos[0]


def test_remessa_com_o_sicoob_livre_abre_a_thread(monkeypatch, tmp_path):
    aba, estados, criadas, avisos = _remessa(monkeypatch, tmp_path, None)
    aba._conferir_agendamentos()
    assert len(criadas) == 1 and avisos == []
