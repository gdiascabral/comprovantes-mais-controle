# -*- coding: utf-8 -*-
"""O núcleo do envio ao portal Acessórias: os zips do mês e a mensagem deles.

Só `acessorias/pacote.py`, que é puro. O `portal.py` fala com um site de
terceiro por navegador de verdade e não entra em teste automatizado, como o
cliente do Sicoob.

Os zips são montados aqui na hora, com nomes INVENTADOS: o repositório é
público, e nome de comprador é dado de pessoa.
"""
import zipfile

import pytest

from extratos_sicoob import sicoob_config as scfg
from extratos_sicoob import sicoob_contas as sc
from acessorias import pacote

MES, ANO = 7, 2026                       # JULHO 2026


# ------------------------------------------------------------------ fixtures

def _empresa(nome, vip_id="", vip_nome=""):
    return sc.Empresa(nome=nome, vip_id=vip_id, vip_nome=vip_nome)


def _zipar(pasta, nome_da_pasta, arquivos):
    """Cria `<pasta>/<nome_da_pasta>.zip` com as entradas pedidas.

    Reproduz o que o `sicoob_zipar` grava: os caminhos dentro do zip começam
    pela pasta da empresa."""
    alvo = pasta / f"{nome_da_pasta}.zip"
    with zipfile.ZipFile(alvo, "w") as z:
        for relativo, conteudo in arquivos.items():
            z.writestr(f"{nome_da_pasta}/{relativo}", conteudo)
    return alvo


@pytest.fixture
def mes(tmp_path):
    """A pasta do mês, vazia: `<raiz>/2026/JULHO/`."""
    pasta = tmp_path / str(ANO) / scfg.nome_do_mes(MES)
    pasta.mkdir(parents=True)
    return pasta


def _mapa(tmp_path, empresas, vip_url="https://exemplo.invalido/escritorio"):
    return sc.Mapa(raiz=tmp_path, empresas=empresas, vip_url=vip_url)


def _montar(mapa):
    return pacote.montar(mapa, ANO, MES, scfg.nome_do_mes,
                         scfg.nome_pasta_empresa)


# -------------------------------------------------------------- caixa de nome

@pytest.mark.parametrize("cru, esperado", [
    ("FULANO DE TAL", "Fulano de Tal"),
    ("MARIA DAS DORES DOS SANTOS", "Maria das Dores dos Santos"),
    ("JOANA E PEDRO", "Joana e Pedro"),
    ("DA SILVA", "Da Silva"),            # partícula na 1ª posição não abaixa
    ("ANA", "Ana"),
    ("", ""),
])
def test_caixa_de_titulo(cru, esperado):
    assert pacote.caixa_de_titulo(cru) == esperado


# ---------------------------------------------------------- linha do contrato

def test_linha_do_contrato_troca_cs_por_casa_e_ajusta_o_nome():
    nome = "CONTRATO RPB 99 QD 1A LT 2 CS 01 - FULANO DE TAL.pdf"
    assert (pacote.linha_do_contrato(nome)
            == "RPB 99 QD 1A LT 2 Casa 01 - Fulano de Tal")


def test_linha_do_contrato_com_unidade_de_dois_digitos():
    nome = "CONTRATO TB 21 QD 46 LT 18 CS 12 - BELTRANO DA COSTA.pdf"
    assert (pacote.linha_do_contrato(nome)
            == "TB 21 QD 46 LT 18 Casa 12 - Beltrano da Costa")


def test_linha_do_contrato_sem_comprador():
    assert (pacote.linha_do_contrato("CONTRATO XY 1 QD 2 LT 3 CS 04.pdf")
            == "XY 1 QD 2 LT 3 Casa 04")


def test_linha_de_formato_desconhecido_vai_como_esta():
    """Informação a mais no comentário é melhor que informação perdida."""
    assert pacote.linha_do_contrato("ADITIVO SEM PADRAO.pdf") == "ADITIVO SEM PADRAO"


# ---------------------------------------------------------- contratos do zip

def test_contratos_saem_de_dentro_do_zip_ordenados(mes):
    pasta = scfg.nome_pasta_empresa(ANO, MES, "ALFA")
    alvo = _zipar(mes, pasta, {
        "CONTRATOS/CONTRATO XY 2 QD 1 LT 9 CS 02 - BRUNO LIMA.pdf": b"b",
        "CONTRATOS/CONTRATO XY 1 QD 1 LT 1 CS 01 - ANA SOUZA.pdf": b"a",
        "SICOOB/202607 SICOOB.ofx": b"ofx",
        "CAIXA/extrato.pdf": b"pdf",
    })
    assert pacote.contratos_do_zip(alvo) == [
        "XY 1 QD 1 LT 1 Casa 01 - Ana Souza",
        "XY 2 QD 1 LT 9 Casa 02 - Bruno Lima",
    ]


def test_zip_sem_pasta_de_contratos_nao_inventa_lista(mes):
    pasta = scfg.nome_pasta_empresa(ANO, MES, "ALFA")
    alvo = _zipar(mes, pasta, {"SICOOB/202607 SICOOB.ofx": b"ofx"})
    assert pacote.contratos_do_zip(alvo) == []


def test_zip_vazio_nao_quebra(mes):
    alvo = _zipar(mes, scfg.nome_pasta_empresa(ANO, MES, "ALFA"), {})
    assert pacote.contratos_do_zip(alvo) == []


def test_arquivo_que_nao_e_zip_nao_derruba_a_preparacao(mes):
    falso = mes / "quebrado.zip"
    falso.write_bytes(b"isto nao e um zip")
    assert pacote.contratos_do_zip(falso) == []


# ------------------------------------------------------------------- modelos

def test_aplicar_modelo_troca_os_cinco_tokens():
    texto = pacote.aplicar_modelo(
        "{mes}/{ano} {mes_minusculo} {empresa}\n{contratos}",
        mes="Julho", ano=2026, empresa="ALFA", contratos=["um", "dois"])
    assert texto == "Julho/2026 julho ALFA\num\ndois"


def test_token_desconhecido_fica_visivel_em_vez_de_estourar():
    texto = pacote.aplicar_modelo("{mes} {mes_do_ano}", mes="Julho", ano=2026,
                                  empresa="ALFA", contratos=[])
    assert texto == "Julho {mes_do_ano}"


# -------------------------------------------------------------------- montar

def test_montar_casa_o_zip_com_a_empresa_e_escreve_a_mensagem(mes, tmp_path):
    pasta = scfg.nome_pasta_empresa(ANO, MES, "ALFA")
    _zipar(mes, pasta, {
        "CONTRATOS/CONTRATO XY 1 QD 1 LT 1 CS 01 - ANA SOUZA.pdf": b"a"})
    mapa = _mapa(tmp_path, [_empresa("ALFA", vip_id="340")])

    envios = _montar(mapa)

    assert len(envios) == 1
    e = envios[0]
    assert e.empresa == "ALFA" and e.vip_id == "340" and e.pronta
    assert e.assunto == "Conciliações bancárias Julho/2026 - ALFA"
    assert "julho/2026" in e.comentario
    assert "XY 1 QD 1 LT 1 Casa 01 - Ana Souza" in e.comentario


def test_vip_nome_e_quem_entra_no_assunto(mes, tmp_path):
    _zipar(mes, scfg.nome_pasta_empresa(ANO, MES, "ALFA"), {})
    mapa = _mapa(tmp_path, [_empresa("ALFA", vip_id="340",
                                     vip_nome="Alfa Empreendimentos")])
    assert _montar(mapa)[0].assunto.endswith("- Alfa Empreendimentos")


def test_razao_social_com_ponto_continua_inteira(mes, tmp_path):
    """A armadilha que o `with_suffix()` já causou no sicoob_zipar, agora do
    lado de quem LÊ o nome: 'ALFA EMPREEND. BETA' não pode virar
    'ALFA EMPREEND'."""
    nome = "ALFA EMPREEND. BETA"
    _zipar(mes, scfg.nome_pasta_empresa(ANO, MES, nome), {})
    mapa = _mapa(tmp_path, [_empresa(nome, vip_id="340")])

    envios = _montar(mapa)
    assert len(envios) == 1
    assert envios[0].empresa == nome and envios[0].pronta


def test_zip_sem_empresa_no_cadastro_trava_o_lote(mes, tmp_path):
    _zipar(mes, scfg.nome_pasta_empresa(ANO, MES, "DESCONHECIDA"), {})
    mapa = _mapa(tmp_path, [_empresa("ALFA", vip_id="340")])

    envios = _montar(mapa)
    assert len(envios) == 1 and not envios[0].pronta
    assert "empresa desconhecida" in envios[0].problema
    assert pacote.impedimentos(envios)


def test_empresa_sem_vip_id_trava_o_lote(mes, tmp_path):
    _zipar(mes, scfg.nome_pasta_empresa(ANO, MES, "ALFA"), {})
    mapa = _mapa(tmp_path, [_empresa("ALFA")])

    envios = _montar(mapa)
    assert len(envios) == 1 and not envios[0].pronta
    assert "vip_id" in envios[0].problema
    assert pacote.impedimentos(envios) and len(pacote.impedimentos(envios)) == 1


def test_zip_sem_contratos_avisa_na_situacao(mes, tmp_path):
    _zipar(mes, scfg.nome_pasta_empresa(ANO, MES, "ALFA"),
           {"SICOOB/202607 SICOOB.ofx": b"ofx"})
    mapa = _mapa(tmp_path, [_empresa("ALFA", vip_id="340")])

    e = _montar(mapa)[0]
    assert e.pronta                       # sem contrato não impede o envio
    assert e.situacao == "sem contratos no zip"


def test_mes_sem_zip_nenhum_nao_e_erro(mes, tmp_path):
    mapa = _mapa(tmp_path, [_empresa("ALFA", vip_id="340")])
    assert _montar(mapa) == []


def test_pasta_do_mes_inexistente_nao_e_erro(tmp_path):
    mapa = _mapa(tmp_path, [_empresa("ALFA", vip_id="340")])
    assert _montar(mapa) == []


def test_so_arquivos_zip_entram(mes, tmp_path):
    _zipar(mes, scfg.nome_pasta_empresa(ANO, MES, "ALFA"), {})
    (mes / "anotacoes.txt").write_text("nada a ver", encoding="utf-8")
    mapa = _mapa(tmp_path, [_empresa("ALFA", vip_id="340")])
    assert [e.empresa for e in _montar(mapa)] == ["ALFA"]


def test_uma_solicitacao_por_zip_encontrado(mes, tmp_path):
    """A pasta manda: quem não foi zipado simplesmente não vai."""
    for nome in ("ALFA", "BETA"):
        _zipar(mes, scfg.nome_pasta_empresa(ANO, MES, nome), {})
    mapa = _mapa(tmp_path, [_empresa("ALFA", vip_id="1"),
                            _empresa("BETA", vip_id="2"),
                            _empresa("GAMA", vip_id="3")])

    envios = _montar(mapa)
    assert sorted(e.empresa for e in envios) == ["ALFA", "BETA"]
    assert not pacote.impedimentos(envios)


# ------------------------------------------------------------------ tamanho

@pytest.mark.parametrize("bytes_, esperado", [
    (512, "512 B"),
    (2048, "2 KB"),
    (5 * 1024 * 1024, "5,0 MB"),
])
def test_fmt_tamanho(bytes_, esperado):
    assert pacote.fmt_tamanho(bytes_) == esperado
