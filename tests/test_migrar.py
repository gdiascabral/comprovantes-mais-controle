# -*- coding: utf-8 -*-
"""A crítica do `nuvem/migrar.py`: o que ela BARRA antes de escrever no banco.

O script roda uma vez e à mão, então é tentador não testá-lo. Só que a parte
testada aqui não é a escrita — é a recusa. Migrar uma divergência é levá-la
para dentro do banco, onde ela fica mais difícil de enxergar do que estava nos
dois arquivos: ali pelo menos existia um `conferir_mapas.py` para acusá-la.

Nada aqui toca a rede: `criticar()` é função pura sobre os dicionários lidos
do disco.
"""
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ / "nuvem"))

import migrar  # noqa: E402


def _dados(**troca):
    """Um cadastro mínimo e VÁLIDO, para cada teste estragar um pedaço só."""
    base = {
        "sicoob": {
            "raiz": "C:/x",
            "empresas": [{
                "nome": "EMPRESA A",
                "pastas_vazias": [],
                "contas": [{"numero": "11.111-1", "pasta": "BANCO",
                            "banco": "756", "agencia": "0000-0"}],
                "clientes_erp": [],
            }],
        },
        "mc": {
            "raiz": "C:/x",
            "contas": [{"erp": "EMPRESA A 11.111-1", "empresa": "EMPRESA A",
                        "pasta": "BANCO", "banco": "NOME DO BANCO"}],
        },
        "subcontas": {},
        "regras_forn": {},
        "confirmar": {},
        "boletos": {},
        "pix": {},
        "entidades": [],
    }
    base.update(troca)
    return base


def test_cadastro_coerente_passa():
    assert migrar.criticar(_dados()) == []


def test_pastas_divergentes_barram():
    """O defeito que partiu julho/2026 ao meio: o PDF do ERP numa pasta e o
    OFX do banco na outra, cada aba seguindo o seu mapa."""
    d = _dados()
    d["mc"]["contas"][0]["pasta"] = "OUTRA PASTA"
    problemas = migrar.criticar(d)
    assert problemas and "manda para" in problemas[0]


def test_sufixos_divergentes_barram():
    """O sufixo desempata duas contas que dividem uma pasta, e vale para os
    DOIS lados. Divergente, cada aba nomeia o arquivo de um jeito — e o pior
    caso não é o nome feio, é a segunda conta gravar por cima da primeira."""
    d = _dados()
    d["mc"]["contas"][0]["sufixo"] = "11111"
    d["sicoob"]["empresas"][0]["contas"][0]["sufixo"] = "OUTRO"
    problemas = migrar.criticar(d)
    assert problemas and "sufixo" in problemas[0]


def test_sufixo_em_um_lado_so_nao_e_divergencia():
    """Cadastrado num arquivo e ausente no outro é o estado normal de quem
    acabou de preencher: a migração aproveita o que existe."""
    d = _dados()
    d["sicoob"]["empresas"][0]["contas"][0]["sufixo"] = "11111"
    assert migrar.criticar(d) == []
    conta = migrar.montar_contas(d)[0]
    assert conta["sufixo"] == "11111"


def test_raizes_divergentes_barram():
    d = _dados()
    d["mc"]["raiz"] = "D:/outro lugar"
    problemas = migrar.criticar(d)
    assert problemas and "raizes" in problemas[0]


def test_subconta_sem_obra_ou_sem_investidor_barra():
    """Sem um dos dois o rateio sai vazio e o valor some sem erro nenhum —
    a mesma checagem que `aportes/regras.validar()` faz na tela."""
    d = _dados(subcontas={"00000-0": {"obras": [], "investidores": ["X"]}})
    assert any("sem obras" in p for p in migrar.criticar(d))

    d = _dados(subcontas={"00000-0": {"obras": ["OBRA"], "investidores": []}})
    assert any("sem investidores" in p for p in migrar.criticar(d))


def test_investidor_nao_precisa_estar_no_contas_csv():
    """Ele entra como `cliente` do lançamento no ERP, não como entidade que
    aporta. Exigir a linha no contas.csv obrigaria a inventar entidades."""
    d = _dados(subcontas={"00000-0": {"obras": ["OBRA"],
                                      "investidores": ["ALGUEM DE FORA"]}})
    assert migrar.criticar(d) == []


def test_empresa_sem_conta_e_sem_pasta_barra():
    """Ela não criaria nada na árvore do mês — é cadastro pela metade."""
    d = _dados()
    d["sicoob"]["empresas"][0]["contas"] = []
    assert any("nem pasta" in p for p in migrar.criticar(d))


def test_conta_do_mc_sem_par_entra_sozinha():
    """São as de outros bancos (Caixa, Inter), que o SicoobNet não tem."""
    d = _dados()
    d["mc"]["contas"].append({"erp": "EMPRESA A CAIXA", "empresa": "EMPRESA A",
                              "pasta": "CAIXA", "banco": "CAIXA"})
    contas = migrar.montar_contas(d)
    assert len(contas) == 2
    sozinha = [c for c in contas if c["numero"] is None]
    assert len(sozinha) == 1 and sozinha[0]["banco"] == "CAIXA"


def test_banco_nome_e_codigo_nao_se_misturam():
    """`banco` quer dizer coisas diferentes nos dois arquivos: nome no
    contas_mc, código no contas_sicoob. Uma coluna só arquivaria o extrato
    como "202607 756.pdf"."""
    conta = migrar.montar_contas(_dados())[0]
    assert conta["banco"] == "NOME DO BANCO"
    assert conta["banco_codigo"] == "756"
