# -*- coding: utf-8 -*-
import subprocess
import sys
import textwrap

import pytest

from pagamento_api import robo


def test_uma_rodada_por_vez(tmp_path):
    with robo.trava_da_rodada(tmp_path) as primeira:
        assert primeira is True
        with robo.trava_da_rodada(tmp_path) as segunda:
            assert segunda is False
        # a segunda, ao sair, NÃO solta a trava da primeira
        with robo.trava_da_rodada(tmp_path) as terceira:
            assert terceira is False
    with robo.trava_da_rodada(tmp_path) as depois:
        assert depois is True


def test_arquivo_que_sobrou_de_rodada_morta_nao_trava(tmp_path):
    (tmp_path / "robo.trava").write_text("123")
    with robo.trava_da_rodada(tmp_path) as minha:
        assert minha is True


def test_outro_processo_com_a_trava_barra_esta_rodada(tmp_path):
    codigo = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(robo.Path(robo.__file__).parent.parent)!r})
        from pagamento_api import robo
        with robo.trava_da_rodada({str(tmp_path)!r}) as minha:
            print("ok" if minha else "nao", flush=True)
            time.sleep(5)
    """)
    p = subprocess.Popen([sys.executable, "-c", codigo], stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "ok"
        with robo.trava_da_rodada(tmp_path) as minha:
            assert minha is False
    finally:
        p.kill()
        p.wait()


def test_rodada_contra_a_nuvem_exige_a_chave_de_ensaio(tmp_path):
    with pytest.raises(SystemExit) as e:
        robo.rodada({"pasta_comprovantes": str(tmp_path)})
    assert "nuvem_de_ensaio" in str(e.value)


def test_hoje_e_o_de_sao_paulo():
    assert robo.FUSO_SP.utcoffset(None).total_seconds() == -3 * 3600


def test_ensaio_sem_credencial_do_sandbox_nao_roda(capsys):
    assert robo.main(["--ensaio-sandbox"]) == 2
    assert "client_id" in capsys.readouterr().out


def test_argumentos_sem_argparse():
    assert robo._argumentos(["--config", "a.json", "--ensaio-sandbox"]) == ("a.json", True)
    assert robo._argumentos(["--config=b.json"]) == ("b.json", False)
    assert robo.main([]) == 2
