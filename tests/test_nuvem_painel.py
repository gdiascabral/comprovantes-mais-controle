# -*- coding: utf-8 -*-
"""Os arquivos do painel do Saldo vêm da nuvem (17/11/2026)."""
import base64
import datetime as dt
import json

import pytest

import widgets
from nuvem import painel, rest

AGORA = dt.datetime(2026, 11, 17, 9, 0, 5)
COPIA = "2026-11-17 09h00m05 nuvem"


@pytest.mark.parametrize("local,nuvem,ultimo,admin,esperado", [
    (None, None, None, True, "nada"),
    ("a", None, None, True, "nada"),         # nuvem vazia: 1ª carga é ato do dono
    (None, "b", None, False, "baixar"),      # máquina nova
    ("a", "a", None, False, "nada"),
    ("a", "b", "a", True, "baixar"),         # só a nuvem mudou
    ("c", "a", "a", True, "subir"),          # só o disco mudou (admin)
    ("c", "a", "a", False, "baixar"),        # não-admin espelha a nuvem
    ("c", "b", "a", True, "conflito"),       # os dois mudaram
    ("c", "b", None, True, "conflito"),      # admin sem sincronia anterior
])
def test_decidir(local, nuvem, ultimo, admin, esperado):
    assert painel.decidir(local, nuvem, ultimo, admin) == esperado


class _Nuvem:
    """Dublê da tabela `arquivo_do_painel` (e do filtro do PATCH)."""

    def __init__(self, arquivos=None):
        self.linhas = {}
        for n, c in (arquivos or {}).items():
            self.por(n, c)
        self.recusar = False

    def por(self, nome, conteudo):
        self.linhas[nome] = {"nome": nome, "sha256": painel.sha(conteudo),
                             "conteudo": base64.b64encode(conteudo).decode()}

    def conteudo(self, nome):
        return base64.b64decode(self.linhas[nome]["conteudo"])

    def ler(self, tabela, token, *, colunas="*", filtro=""):
        if filtro:
            nome = filtro.split("=eq.")[1]
            return [ln for ln in self.linhas.values() if ln["nome"] == nome]
        return list(self.linhas.values())

    def alterar(self, tabela, token, filtro, mudancas):
        if self.recusar:
            return []                    # RLS: zero linhas, sem erro
        partes = dict(p.split("=eq.") for p in filtro.split("&"))
        ln = self.linhas.get(partes["nome"])
        if ln is None or ln["sha256"] != partes["sha256"]:
            return []
        ln.update(mudancas)
        return [ln]


@pytest.fixture
def nuvem(monkeypatch):
    n = _Nuvem()
    monkeypatch.setattr(rest, "ler", n.ler)
    monkeypatch.setattr(rest, "alterar", n.alterar)
    monkeypatch.setattr(rest, "inserir", lambda *a, **k: pytest.fail("nunca insere"))
    return n


@pytest.fixture
def confere(monkeypatch):
    """O pacote confere (o de verdade abre os três: `test_conferir_pacote_*`)."""
    estado = {"porque": ""}
    monkeypatch.setattr(painel, "conferir_pacote", lambda c, m, x: estado["porque"])
    return estado


PAC = {"config.yaml": b"cfg 1\n", "mapping.yaml": b"map 1\n", "MODELO.xlsx": b"PK xlsx 1"}


def _escrever(pasta, arquivos):
    for n, c in arquivos.items():
        (pasta / n).write_bytes(c)


def _sinc(tmp_path, admin):
    return painel.sincronizar("tok", admin, tmp_path, agora=AGORA)


def test_maquina_nova_recebe_o_pacote_inteiro(tmp_path, nuvem, confere):
    nuvem.__init__(dict(PAC, **{"conciliacao_ofx.json": b'{"ignorar": []}'}))
    r = _sinc(tmp_path, admin=False)
    assert sorted(r.baixados) == sorted(list(PAC) + ["conciliacao_ofx.json"])
    for n, c in PAC.items():
        assert (tmp_path / n).read_bytes() == c
    assert _sinc(tmp_path, admin=False).baixados == []          # 2ª abertura: nada


def test_nuvem_vazia_nao_recebe_nada_do_admin(tmp_path, nuvem, confere):
    _escrever(tmp_path, PAC)
    r = _sinc(tmp_path, admin=True)
    assert r.subidos == [] and nuvem.linhas == {}


def test_pacote_da_nuvem_que_nao_confere_nao_desce(tmp_path, nuvem, confere):
    nuvem.__init__(PAC)
    confere["porque"] = "rótulo da linha 9 diverge"
    r = _sinc(tmp_path, admin=False)
    assert r.baixados == [] and not (tmp_path / "mapping.yaml").exists()
    assert any("linha 9" in a for a in r.avisos)


def test_pacote_incompleto_na_nuvem_nao_desce(tmp_path, nuvem, confere):
    nuvem.__init__({"config.yaml": PAC["config.yaml"], "mapping.yaml": PAC["mapping.yaml"]})
    r = _sinc(tmp_path, admin=False)
    assert r.baixados == [] and any("incompleto" in a for a in r.avisos)


def test_admin_sobe_o_que_mudou_no_disco(tmp_path, nuvem, confere):
    nuvem.__init__(PAC)
    _escrever(tmp_path, PAC)
    _sinc(tmp_path, admin=True)                                  # sincroniza
    (tmp_path / "mapping.yaml").write_bytes(b"map 2\n")
    (tmp_path / "MODELO.xlsx").write_bytes(b"PK xlsx 2")
    r = _sinc(tmp_path, admin=True)
    assert r.subidos == ["MODELO.xlsx", "mapping.yaml"]          # MODELO antes
    assert nuvem.conteudo("mapping.yaml") == b"map 2\n"


def test_admin_nao_sobe_pacote_que_nao_confere(tmp_path, nuvem, confere):
    nuvem.__init__(PAC)
    _escrever(tmp_path, PAC)
    _sinc(tmp_path, admin=True)
    (tmp_path / "mapping.yaml").write_bytes(b"map torto\n")
    confere["porque"] = "rótulo diverge"
    r = _sinc(tmp_path, admin=True)
    assert r.subidos == [] and nuvem.conteudo("mapping.yaml") == PAC["mapping.yaml"]


def test_outra_maquina_subiu_antes_nao_sobrescreve(tmp_path, nuvem, confere):
    nuvem.__init__(PAC)
    _escrever(tmp_path, PAC)
    _sinc(tmp_path, admin=True)
    nuvem.por("mapping.yaml", b"map da outra\n")
    (tmp_path / "mapping.yaml").write_bytes(b"map minha\n")
    r = _sinc(tmp_path, admin=True)
    assert r.subidos == [] and any("mudou no disco e na" in a for a in r.avisos)
    assert (tmp_path / "mapping.yaml").read_bytes() == b"map minha\n"


def test_recusa_da_rls_diz_que_e_permissao(tmp_path, nuvem, confere):
    nuvem.__init__(PAC)
    _escrever(tmp_path, PAC)
    _sinc(tmp_path, admin=True)
    (tmp_path / "config.yaml").write_bytes(b"cfg 2\n")
    nuvem.recusar = True
    r = _sinc(tmp_path, admin=True)
    assert r.subidos == [] and any("administrador" in a for a in r.avisos)
    # o estado não registra o que não subiu: tenta de novo na próxima
    estado = json.loads((tmp_path / painel.ESTADO).read_text("utf-8"))
    assert estado["config.yaml"] == painel.sha(PAC["config.yaml"])


def test_nao_admin_com_arquivo_diferente_guarda_copia_e_espelha(tmp_path, nuvem, confere):
    nuvem.__init__(PAC)
    _escrever(tmp_path, dict(PAC, **{"config.yaml": b"velho\n"}))
    r = _sinc(tmp_path, admin=False)
    assert r.baixados == ["config.yaml"]
    assert (tmp_path / painel.COPIAS / COPIA / "config.yaml").read_bytes() == b"velho\n"


def test_baixar_e_subir_ao_mesmo_tempo_e_conflito(tmp_path, nuvem, confere):
    nuvem.__init__(PAC)
    _escrever(tmp_path, PAC)
    _sinc(tmp_path, admin=True)
    nuvem.por("config.yaml", b"cfg da nuvem\n")
    (tmp_path / "mapping.yaml").write_bytes(b"map do disco\n")
    r = _sinc(tmp_path, admin=True)
    assert r.subidos == [] and r.baixados == [] and r.avisos


def test_solto_que_nao_e_json_nao_desce(tmp_path, nuvem, confere):
    nuvem.__init__({"conciliacao_ofx.json": b"{nao e json"})
    r = _sinc(tmp_path, admin=False)
    assert r.baixados == [] and not (tmp_path / "conciliacao_ofx.json").exists()


def test_sem_rede_nao_mexe_em_nada(tmp_path, monkeypatch):
    def cai(*a, **k):
        raise rest.SemRede("fora")
    monkeypatch.setattr(rest, "ler", cai)
    (tmp_path / "config.yaml").write_bytes(b"x\n")
    r = _sinc(tmp_path, admin=True)
    assert not r.ok and (tmp_path / "config.yaml").read_bytes() == b"x\n"


def test_sem_token_nao_tenta(tmp_path):
    assert not painel.sincronizar("", True, tmp_path).ok


def test_conferir_pacote_recusa_o_que_nao_abre():
    assert painel.conferir_pacote(b"nao: [yaml", b"x", b"nao e xlsx")


def test_recado_de_arquivo_do_painel_faltando():
    erro = FileNotFoundError(2, "No such file or directory", r"C:\APP\config.yaml")
    houve, quem, passo = widgets.explicar_erro(erro)
    assert "config.yaml" in houve and "nuvem" in quem
    assert "OneDrive" not in houve + quem + passo
