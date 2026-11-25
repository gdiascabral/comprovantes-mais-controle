"""Onde mora a chave da API: DPAPI (anthropic.dat) ou _chaves/anthropic-api.txt.
Sem DPAPI de verdade: cifra e decifra são dublês. Chave fictícia."""
from pagamentos_dia import chave_ia

CHAVE = "sk-ant-chave-ficticia-123"


def _cifra(b):
    return b[::-1]


def test_sem_nada_nao_ha_chave(tmp_path):
    assert chave_ia.carregar(tmp_path, decifrar=_cifra) is None


def test_salva_cifrada_e_nunca_em_texto(tmp_path):
    chave_ia.salvar(CHAVE, tmp_path, cifrar=_cifra)
    bruto = (tmp_path / chave_ia.ARQUIVO).read_bytes()
    assert CHAVE.encode() not in bruto
    assert chave_ia.carregar(tmp_path, decifrar=_cifra) == CHAVE


def test_arquivo_de_texto_da_maquina_do_lider(tmp_path):
    (tmp_path / "_chaves").mkdir()
    (tmp_path / "_chaves" / "anthropic-api.txt").write_text(f"  {CHAVE}\n", encoding="utf-8")
    assert chave_ia.carregar(tmp_path, decifrar=_cifra) == CHAVE


def test_dpapi_vence_o_arquivo_de_texto(tmp_path):
    chave_ia.salvar(CHAVE, tmp_path, cifrar=_cifra)
    (tmp_path / "_chaves").mkdir()
    (tmp_path / "_chaves" / "anthropic-api.txt").write_text("sk-ant-outra", encoding="utf-8")
    assert chave_ia.carregar(tmp_path, decifrar=_cifra) == CHAVE


def test_dpapi_que_recusa_cai_no_texto_ou_em_nada(tmp_path):
    chave_ia.salvar(CHAVE, tmp_path, cifrar=_cifra)

    def recusa(_b):
        raise OSError("outro usuário")
    assert chave_ia.carregar(tmp_path, decifrar=recusa) is None


def test_arquivo_vazio_ou_com_varias_linhas_nao_vale(tmp_path):
    (tmp_path / "_chaves").mkdir()
    f = tmp_path / "_chaves" / "anthropic-api.txt"
    f.write_text("\n", encoding="utf-8")
    assert chave_ia.carregar(tmp_path, decifrar=_cifra) is None
    f.write_text("isto parece um texto qualquer\ncom linhas", encoding="utf-8")
    assert chave_ia.carregar(tmp_path, decifrar=_cifra) is None


def test_salvar_chave_vazia_nao_grava(tmp_path):
    chave_ia.salvar("  ", tmp_path, cifrar=_cifra)
    assert not (tmp_path / chave_ia.ARQUIVO).exists()
