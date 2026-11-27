# -*- coding: utf-8 -*-
import os
import time

from pagamento_api import robo


def test_uma_rodada_por_vez(tmp_path):
    with robo.trava_da_rodada(tmp_path) as primeira:
        assert primeira is True
        with robo.trava_da_rodada(tmp_path) as segunda:
            assert segunda is False
    with robo.trava_da_rodada(tmp_path) as depois:
        assert depois is True


def test_trava_velha_e_assumida(tmp_path):
    arq = tmp_path / "robo.trava"
    arq.write_text("123")
    velho = time.time() - robo.TRAVA_VELHA_SEGUNDOS - 60
    os.utime(arq, (velho, velho))
    with robo.trava_da_rodada(tmp_path) as minha:
        assert minha is True


def test_ensaio_sem_credencial_do_sandbox_nao_roda(capsys):
    assert robo.main(["--ensaio-sandbox"]) == 2
    assert "client_id" in capsys.readouterr().out


def test_argumentos_sem_argparse():
    assert robo._argumentos(["--config", "a.json", "--ensaio-sandbox"]) == ("a.json", True)
    assert robo._argumentos(["--config=b.json"]) == ("b.json", False)
    assert robo.main([]) == 2
