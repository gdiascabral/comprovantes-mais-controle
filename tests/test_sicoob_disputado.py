# -*- coding: utf-8 -*-
"""O perfil do Chrome do Sicoob é um só. A tela do dia (Reler Sicoob) já
recusava ler com os Extratos ou o Baixar comprovantes rodando; aqui o
contrário: as duas abas recusam começar enquanto a tela do dia lê o saldo.

Sem Tk: as abas nascem por __new__ e os botões são dublês. O callback
`sicoob_ocupado` é o que o comprovantes_app.py liga (padrão da Remessa)."""
import queue
import threading

QUEM = "Pagamentos do dia — lendo o saldo do Sicoob"


class _Widget:
    def __init__(self):
        self.estado = {}

    def configure(self, **kw):
        self.estado.update(kw)


class _Exec:
    def __init__(self):
        self.enviados = []

    def submit(self, fn, *a, **k):
        self.enviados.append(fn)
        return None


def _avisos(monkeypatch, modulo):
    vistos = []
    monkeypatch.setattr(modulo.messagebox, "showinfo",
                        lambda titulo, texto, **k: vistos.append((titulo, texto)))
    return vistos


# ---------------------------------------------------------------- Extratos
def _extratos():
    from extratos_sicoob import extratos_frame as m
    aba = m.ExtratosSicoobFrame.__new__(m.ExtratosSicoobFrame)
    aba.q = queue.Queue()
    aba.worker = None
    aba._parar = threading.Event()
    aba._tarefa_atual = ""
    aba.exec = _Exec()
    return m, aba


def test_extratos_recusa_baixar_quando_a_tela_do_dia_le_o_sicoob(monkeypatch):
    m, aba = _extratos()
    vistos = _avisos(monkeypatch, m)
    aba.sicoob_ocupado = lambda: QUEM
    aba.baixar()
    assert aba.exec.enviados == []
    assert aba.q.empty()                      # nenhum botão foi apagado
    assert aba._tarefa_atual == ""
    assert len(vistos) == 1 and QUEM in vistos[0][1]


def test_extratos_baixa_quando_o_sicoob_esta_livre(monkeypatch):
    m, aba = _extratos()
    vistos = _avisos(monkeypatch, m)
    aba.sicoob_ocupado = lambda: None
    aba.baixar()
    assert aba.exec.enviados == [aba._t_baixar]
    assert vistos == []


def test_extratos_sem_callback_baixa_como_antes(monkeypatch):
    m, aba = _extratos()
    vistos = _avisos(monkeypatch, m)
    aba.baixar()
    assert aba.exec.enviados == [aba._t_baixar]
    assert vistos == []


# ------------------------------------------------------ Baixar comprovantes
class _Var:
    def __init__(self, v):
        self.v = v

    def get(self):
        return self.v


def _comprovantes(monkeypatch, tmp_path, bancos=("Sicoob",)):
    from baixar_comprovantes import comprovantes_frame as m
    aba = m.ComprovantesFrame.__new__(m.ComprovantesFrame)
    aba.q = queue.Queue()
    aba.worker = None
    aba._parar = threading.Event()
    aba.v_pasta = _Var(str(tmp_path))
    aba.v_ini, aba.v_fim = _Var("01/10/2026"), _Var("21/10/2026")
    aba.linhas = {f"{b}:{i}": {"banco": b, "conta": str(i), "marcada": True}
                  for i, b in enumerate(bancos)}
    aba.b_ir, aba.b_parar, aba.lbl = _Widget(), _Widget(), _Widget()
    registro = []
    aba._log = registro.append
    criadas = []

    class _Thread:
        def __init__(self, target=None, args=(), daemon=None):
            criadas.append(target)

        def start(self):
            pass

        def is_alive(self):
            return True

    monkeypatch.setattr(m.threading, "Thread", _Thread)
    return m, aba, criadas


def test_comprovantes_recusa_comecar_quando_a_tela_do_dia_le_o_sicoob(
        monkeypatch, tmp_path):
    m, aba, criadas = _comprovantes(monkeypatch, tmp_path)
    vistos = _avisos(monkeypatch, m)
    aba.sicoob_ocupado = lambda: QUEM
    aba._comecar()
    assert criadas == []
    assert aba.b_ir.estado == {} and aba.b_parar.estado == {}
    assert aba.lbl.estado == {}
    assert len(vistos) == 1 and QUEM in vistos[0][1]
    assert list(tmp_path.iterdir()) == []     # nem a pasta da rodada nasce


def test_comprovantes_so_inter_nao_usa_o_sicoob_e_comeca(monkeypatch, tmp_path):
    m, aba, criadas = _comprovantes(monkeypatch, tmp_path, bancos=("Inter",))
    vistos = _avisos(monkeypatch, m)
    aba.sicoob_ocupado = lambda: QUEM
    aba._comecar()
    assert criadas == [aba._trabalhar]
    assert vistos == []


def test_comprovantes_comeca_quando_o_sicoob_esta_livre(monkeypatch, tmp_path):
    m, aba, criadas = _comprovantes(monkeypatch, tmp_path)
    vistos = _avisos(monkeypatch, m)
    aba.sicoob_ocupado = lambda: None
    aba._comecar()
    assert criadas == [aba._trabalhar]
    assert aba.b_ir.estado == {"state": "disabled"}
    assert vistos == []


def test_comprovantes_sem_callback_comeca_como_antes(monkeypatch, tmp_path):
    m, aba, criadas = _comprovantes(monkeypatch, tmp_path)
    vistos = _avisos(monkeypatch, m)
    aba._comecar()
    assert criadas == [aba._trabalhar]
    assert vistos == []
