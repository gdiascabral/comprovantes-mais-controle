# -*- coding: utf-8 -*-
"""Importar OFX no ERP pela tela ("Selecionar novo OFX"), numa aba do robô.
Página e Chrome são dublês; UUIDs e nomes fictícios."""
from contextlib import contextmanager
from pathlib import Path

from conciliacao_dia import importar_erp as m

UA, UB = "aaaaaaaa-0001", "bbbbbbbb-0002"


class _Loc:
    def __init__(self, aba, texto, exact):
        self.aba, self.texto, self.exact = aba, texto, exact
        self.first = self

    def _visivel(self) -> bool:
        if self.texto == m.TEXTO_OK:
            return self.aba.aviso_na_tela
        if self.texto == m.TEXTO_BOTAO:
            return True
        if self.exact:
            return self.texto in self.aba.nomes
        return any(self.texto in n for n in self.aba.nomes)

    def count(self):
        return 1 if self._visivel() else 0

    def wait_for(self, timeout=None):
        if not self._visivel():
            raise TimeoutError("Timeout 40000ms exceeded")

    def click(self):
        self.aba.cliques.append(self.texto)


class _Escolha:
    def __init__(self, aba):
        self.aba = aba

    def set_files(self, caminho):
        self.aba.enviados.append((self.aba.url, Path(caminho).name))
        if self.aba.confirma:
            self.aba.aviso_na_tela = True


class _Aba:
    def __init__(self, confirma=True, quebra=None, nomes=("CONTA A", "CONTA B"),
                 aviso_que_nao_some=False):
        self.confirma, self.quebra, self.nomes = confirma, quebra, nomes
        self.url, self.cliques, self.enviados, self.fechada = "", [], [], False
        self.aviso_na_tela, self.aviso_que_nao_some = False, aviso_que_nao_some
        self.idas = []

    def goto(self, url, **k):
        if self.quebra:
            raise RuntimeError(self.quebra)
        self.idas.append(url)
        if url == "about:blank" and not self.aviso_que_nao_some:
            self.aviso_na_tela = False           # recarregar apaga o aviso velho
        self.url = url

    def get_by_text(self, texto, exact=False):
        return _Loc(self, texto, exact)

    def wait_for_timeout(self, ms):
        pass

    @contextmanager
    def expect_file_chooser(self, timeout=None):
        espera = type("E", (), {})()
        yield espera
        espera.value = _Escolha(self)

    def close(self):
        self.fechada = True


class _Mc:
    def __init__(self, aba=None, nao_abre=False):
        self.aba, self.nao_abre, self._minhas, self.abertas = aba, nao_abre, set(), 0

    def _nova_aba_do_robo(self):
        if self.nao_abre:
            raise RuntimeError("Target closed")
        self.abertas += 1
        self._minhas.add(self.aba)
        return self.aba


def _pedidos(tmp_path):
    return [(UA, "CONTA A", tmp_path / "1.ofx"), (UB, "CONTA B", tmp_path / "2.ofx")]


def test_importa_cada_um_numa_aba_so_recarregando_entre_as_contas(tmp_path):
    aba = _Aba()
    mc = _Mc(aba)
    r = m.importar(mc, _pedidos(tmp_path), log=lambda s: None)
    assert r == {UA: (m.OK, ""), UB: (m.OK, "")}
    assert [u.rsplit("/", 1)[1] for u, _ in aba.enviados] == [UA, UB]
    assert [n for _, n in aba.enviados] == ["1.ofx", "2.ofx"]
    assert aba.idas[0] == "about:blank" and aba.idas[2] == "about:blank"
    assert mc.abertas == 1 and aba.fechada and mc._minhas == set()


def test_uuid_invalido_nem_navega(tmp_path):
    aba = _Aba()
    r = m.importar(_Mc(aba), [('x"]; drop', "CONTA A", tmp_path / "1.ofx")], log=lambda s: None)
    assert r == {'x"]; drop': (m.FALHOU, m.SEM_UUID)} and aba.url == ""


def test_sem_confirmacao_depois_do_envio_e_incerto_e_segue(tmp_path):
    r = m.importar(_Mc(_Aba(confirma=False)), _pedidos(tmp_path), log=lambda s: None)
    assert r == {UA: (m.INCERTO, m.SEM_CONFIRMACAO), UB: (m.INCERTO, m.SEM_CONFIRMACAO)}


def test_aviso_velho_na_tela_nao_da_a_conta_por_importada(tmp_path):
    """O aviso verde da conta anterior ainda na tela confirmaria a seguinte
    sem ela ter entrado (revisão de 16/11/2026): a conta não recebe nada."""
    aba = _Aba(aviso_que_nao_some=True)
    r = m.importar(_Mc(aba), _pedidos(tmp_path), log=lambda s: None)
    assert r[UA] == (m.OK, "")
    assert r[UB][0] == m.FALHOU and "aviso" in r[UB][1]
    assert [n for _, n in aba.enviados] == ["1.ofx"]


def test_nome_que_so_aparece_como_pedaco_de_outro_nao_abre_a_porta(tmp_path):
    aba = _Aba(nomes=("CONTA A 2", "CONTA B"))
    r = m.importar(_Mc(aba), _pedidos(tmp_path), log=lambda s: None)
    assert r[UA][0] == m.FALHOU and "não abriu" in r[UA][1]
    assert [n for _, n in aba.enviados] == ["2.ofx"]


def test_conta_que_nao_abre_no_erp_nao_recebe_o_arquivo(tmp_path):
    """A tela tem de mostrar o NOME da conta antes do upload: o OFX nunca
    vai para a conta que estava aberta antes."""
    aba = _Aba(nomes=("CONTA B",))
    r = m.importar(_Mc(aba), _pedidos(tmp_path), log=lambda s: None)
    assert r[UA][0] == m.FALHOU and "não abriu" in r[UA][1]
    assert r[UB] == (m.OK, "") and [n for _, n in aba.enviados] == ["2.ofx"]


def test_parar_deixa_os_que_faltam(tmp_path):
    vezes = []
    aba = _Aba()
    r = m.importar(_Mc(aba), _pedidos(tmp_path), log=lambda s: None,
                   parar=lambda: vezes.append(1) or len(vezes) > 1)
    assert r == {UA: (m.OK, ""), UB: (m.FALHOU, m.PARADO)}


def test_aba_que_nao_abre_vira_motivo_em_todos(tmp_path):
    r = m.importar(_Mc(nao_abre=True), _pedidos(tmp_path), log=lambda s: None)
    assert all(estado == m.FALHOU and "Target closed" in motivo for estado, motivo in r.values())
    assert set(r) == {UA, UB}
