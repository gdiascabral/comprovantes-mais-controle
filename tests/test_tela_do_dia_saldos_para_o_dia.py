# -*- coding: utf-8 -*-
"""O saldo da Prova de saldos vale para o Pagamentos do dia (16/11/2026)."""
import datetime as dt
import json
from decimal import Decimal

from tela_do_dia import prova_saldos as ps
from tela_do_dia import saldo_sicoob as ss
from tela_do_dia import saldos_para_o_dia as spd
from tela_do_dia.saldos import LinhaSaldo

HOJE = dt.date(2026, 11, 16)
AS_8 = dt.datetime(2026, 11, 16, 8, 0)
AS_9 = dt.datetime(2026, 11, 16, 9, 0)


def _sic(numero, linha=1, motivo=""):
    return ps.ContaDaProva(linha, f"Conta {linha}", ps.SICOOB, numero=numero, motivo=motivo)


def _int(apelido, linha=2, numero="123", motivo=""):
    return ps.ContaDaProva(linha, f"Conta {linha}", ps.INTER, numero=numero,
                           apelido=apelido, motivo=motivo)


# ------------------------------------------------------------- Sicoob
def test_lida_pela_prova_troca_o_saldo_de_antes():
    antes = ss.LeituraSicoob(HOJE, {"111": ss.SaldoLido("1.11", Decimal("5"), AS_8)})
    nova = spd.juntar_sicoob(antes, {"111": ps.Leitura(Decimal("7"), AS_9)},
                             {"111": "1.11"}, HOJE)
    assert nova.contas["111"].saldo == Decimal("7")
    assert nova.contas["111"].lido_em == AS_9


def test_falha_da_prova_nao_apaga_saldo_bom():
    antes = ss.LeituraSicoob(HOJE, {"111": ss.SaldoLido("1.11", Decimal("5"), AS_8)})
    nova = spd.juntar_sicoob(antes, {"111": ps.Leitura(None, motivo="caiu")},
                             {"111": "1.11"}, HOJE)
    assert nova.contas["111"].saldo == Decimal("5")


def test_falha_sem_saldo_antes_entra_com_o_motivo():
    nova = spd.juntar_sicoob(None, {"222": ps.Leitura(None, motivo="não aparece")},
                             {"222": "2.22"}, HOJE)
    assert nova.contas["222"].saldo is None
    assert nova.contas["222"].motivo == "não aparece"


def test_leitura_de_outro_dia_nao_se_mistura():
    ontem = ss.LeituraSicoob(HOJE - dt.timedelta(days=1),
                             {"111": ss.SaldoLido("1.11", Decimal("5"), AS_8)})
    nova = spd.juntar_sicoob(ontem, {"222": ps.Leitura(Decimal("1"), AS_9)},
                             {"222": "2.22"}, HOJE)
    assert set(nova.contas) == {"222"}


def test_conta_de_fora_do_arquivo_continua():
    antes = ss.LeituraSicoob(HOJE, {"333": ss.SaldoLido("3.33", Decimal("9"), AS_8)})
    nova = spd.juntar_sicoob(antes, {"111": ps.Leitura(Decimal("1"), AS_9)},
                             {"111": "1.11"}, HOJE)
    assert nova.contas["333"].saldo == Decimal("9")


# -------------------------------------------------------------- Inter
def test_inter_so_grava_conta_lida_e_sem_motivo():
    contas = [_int("A", 2), _int("B", 3), _int("C", 4, motivo="dois logins")]
    inter = {"A": ps.Leitura(Decimal("10"), AS_9), "B": ps.Leitura(None, motivo="QR"),
             "C": ps.Leitura(Decimal("1"), AS_9)}
    lidos, numeros = spd.inter_para_gravar(contas, inter)
    assert set(lidos) == {"A"} and numeros == {"A": "123"}
    assert lidos["A"].via == spd.VIA_PROVA


def test_ler_inter_de_outro_dia_ou_estragado_e_vazio(tmp_path):
    arq = tmp_path / "inter.json"
    assert spd.ler_inter(arq, HOJE) == {}
    arq.write_text("{estragado", encoding="utf-8")
    assert spd.ler_inter(arq, HOJE) == {}
    arq.write_text(json.dumps({"data": "2026-11-15", "contas": {
        "A": {"saldo": "1", "lido_em": "2026-11-15T09:00:00"}}}), encoding="utf-8")
    assert spd.ler_inter(arq, HOJE) == {}


def test_aplicar_inter_poe_o_saldo_na_linha_do_login():
    linhas = [LinhaSaldo(1, "Conta 1", Decimal("1"), banco=Decimal("2")),
              LinhaSaldo(2, "Conta 2", Decimal("3")),
              LinhaSaldo(3, "Conta 3", Decimal("4"))]
    contas = [_int("A", 2), _int("B", 3, motivo="sem login"), _int("A", 1)]
    saida = spd.aplicar_inter(linhas, contas, {"A": (Decimal("50"), AS_9, "123"),
                                              "B": (Decimal("60"), AS_9, "")}, AS_9)
    assert saida[0].banco == Decimal("2")          # já lida (Sicoob): não mexe
    assert saida[1].banco == Decimal("50")
    assert saida[2].banco is None                  # conta com motivo não recebe


def test_inter_lido_ha_mais_de_2h_vira_nota_e_nao_saldo():
    linhas = [LinhaSaldo(2, "Conta 2", Decimal("3"))]
    tarde = AS_9 + dt.timedelta(minutes=spd.IDADE_MAXIMA_MIN + 1)
    saida = spd.aplicar_inter(linhas, [_int("A", 2)], {"A": (Decimal("50"), AS_9, "")}, tarde)
    assert saida[0].banco is None
    assert "09:00" in saida[0].nota_banco
    assert saida[0].situacao()[0] == "atencao"


def test_inter_de_outra_conta_nao_entra():
    linhas = [LinhaSaldo(2, "Conta 2", Decimal("3"))]
    saida = spd.aplicar_inter(linhas, [_int("A", 2, numero="123")],
                              {"A": (Decimal("50"), AS_9, "999")}, AS_9)
    assert saida[0].banco is None and "999" in saida[0].nota_banco


def test_sem_numero_de_um_lado_vale_o_login():
    linhas = [LinhaSaldo(2, "Conta 2", Decimal("3"))]
    saida = spd.aplicar_inter(linhas, [_int("A", 2, numero="")],
                              {"A": (Decimal("50"), AS_9, "999")}, AS_9)
    assert saida[0].banco == Decimal("50")


def test_lido_de_outro_dia_nao_vai_para_o_arquivo():
    ontem_23h = dt.datetime(2026, 11, 15, 23, 52)
    nova = spd.juntar_sicoob(None, {"111": ps.Leitura(Decimal("7"), ontem_23h)},
                             {"111": "1.11"}, HOJE)
    assert nova.contas["111"].saldo is None
    lidos, _n = spd.inter_para_gravar([_int("A", 2)],
                                      {"A": ps.Leitura(Decimal("1"), ontem_23h)}, HOJE)
    assert lidos == {}


def test_prova_sem_nenhum_sicoob_lido_nao_grava(tmp_path):
    spd.guardar(tmp_path, HOJE, [_sic("1.11", 1)], {"111": ps.Leitura(None, motivo="Parar")},
                {}, log=lambda m: None)
    assert not ss.caminho(tmp_path, HOJE).exists()


def test_guardar_grava_nos_arquivos_que_o_dia_le(tmp_path):
    from tela_do_dia import autenticar_inter as ai
    contas = [_sic("1.11", 1), _int("A", 2)]
    spd.guardar(tmp_path, HOJE, contas,
                {"111": ps.Leitura(Decimal("7"), AS_9)},
                {"A": ps.Leitura(Decimal("50"), AS_9)}, log=lambda m: None)
    lida, aviso = ss.ler(ss.caminho(tmp_path, HOJE), HOJE)
    assert aviso == "" and lida.contas["111"].saldo == Decimal("7")
    inter = spd.ler_inter(ai.caminho_dos_saldos(tmp_path, HOJE), HOJE)
    assert inter == {"A": (Decimal("50"), AS_9, "123")}


def test_guardar_sem_nada_lido_nao_cria_arquivo(tmp_path):
    from tela_do_dia import autenticar_inter as ai
    spd.guardar(tmp_path, HOJE, [_int("A", 2)], {}, {"A": ps.Leitura(None, motivo="QR")},
                log=lambda m: None)
    assert not ss.caminho(tmp_path, HOJE).exists()
    assert not ai.caminho_dos_saldos(tmp_path, HOJE).exists()
