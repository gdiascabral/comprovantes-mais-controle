# -*- coding: utf-8 -*-
"""A leitura do retorno: o que o banco respondeu, casado com o que saiu.

Sem tela e sem rede. O que se testa aqui não é o parser do CNAB (isso é do
`cnab240`), e sim as decisões da aba: o que conta como pago, o que conta como
"ainda falta assinar", e o que fazer com pagamento que o banco simplesmente
não citou.
"""
import datetime
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest

from cnab240 import historico
from nuvem import registro
from pagamentos_dia import retorno_dia


# ------------------------------------------------------------------ dublês

@dataclass
class _Pagamento:
    seu_numero: str
    favorecido: str = "FULANO"
    valor: Decimal = Decimal("100.00")
    ocorrencias: list = None
    _sucesso: bool = False
    _pendente: bool = False

    def __post_init__(self):
        if self.ocorrencias is None:
            self.ocorrencias = []

    @property
    def sem_ocorrencia(self):
        return not self.ocorrencias

    @property
    def sucesso(self):
        return self._sucesso

    @property
    def pendente(self):
        return self._pendente


class _Arquivo:
    def __init__(self, pagamentos, *, e_retorno=True, nsa=1, convenio="1814",
                 agencia="4321", conta="123456"):
        self._pg = pagamentos
        self.e_retorno = e_retorno
        self.nsa = nsa
        self.convenio = convenio
        self.empresa = "EMPRESA A"
        self.agencia = agencia
        self.conta = conta

    def pagamentos(self):
        return iter(self._pg)


class _Historico:
    """O registro central, como o `nuvem.registro.Espelhado` responde.

    Guarda as remessas na forma que o PostgREST devolve (dicionário com
    `remessa_item` dentro) e sabe as DUAS perguntas que a leitura do retorno
    faz: por convênio (o header) e pelos "seus números" (o segundo caminho).
    A regra do segundo é a mesma do registro de verdade — só responde quando
    todos os achados caem na MESMA remessa —, porque é ela que está sendo
    comprada aqui.
    """

    def __init__(self, remessas):
        self._r = remessas
        #: O que foi perguntado pelo segundo caminho, na ordem. Vazio prova
        #: que o caminho de sempre resolveu sozinho.
        self.perguntas = []

    def remessas(self, *, convenio=None):
        return self._r

    def remessa_dos_seus_numeros(self, seus):
        self.perguntas.append(list(seus))
        alvos = set(seus)
        achadas = [r for r in self._r
                   if any(str(i.get("seu_numero") or "") in alvos
                          for i in r.get("remessa_item") or [])]
        return achadas[0] if len(achadas) == 1 else None


class _HistoricoAntigo:
    """Um registro que só sabe a pergunta de sempre — sem o segundo caminho."""

    def remessas(self, *, convenio=None):
        return []


@pytest.fixture
def ler(monkeypatch):
    """Lê um retorno inventado, sem tocar no parser do CNAB nem no disco.

    O dublê entra no lugar de `cnab240.ler_retorno` — que é quem recebe o
    TEXTO desde que a leitura passou a valer também para membro de zip, onde
    não há caminho no disco para abrir.
    """
    def _ler(pagamentos, historico=None, **kw):
        arq = _Arquivo(pagamentos, **kw)
        import cnab240
        monkeypatch.setattr(cnab240, "ler_retorno",
                            lambda _c: arq, raising=False)
        return retorno_dia.ler_conteudo("qualquer texto", "qualquer.RET",
                                        historico)
    return _ler


def _remessa(itens, nsa=1, convenio="1814", arquivo=""):
    return [{"nsa": nsa, "convenio": convenio, "arquivo": arquivo,
             "remessa_item": [{"seu_numero": s, "referencia": r}
                              for s, r in itens]}]


# ------------------------------------------------------------------ testes

def test_arquivo_de_remessa_e_recusado(ler):
    """Confundir os dois é fácil: os dois saem do SicoobNet e têm o mesmo
    formato. Ler uma remessa como retorno mostraria "nenhuma resposta" em
    tudo, que parece problema no banco."""
    with pytest.raises(ValueError, match="não é um retorno"):
        ler([], e_retorno=False)


def test_pago_pendente_e_rejeitado_sao_estados_distintos(ler):
    resumo = ler([
        _Pagamento("001", ocorrencias=[("00", "ok")], _sucesso=True),
        _Pagamento("002", ocorrencias=[("PD", "pendente de assinatura")],
                   _pendente=True),
        _Pagamento("003", ocorrencias=[("AG", "conta invalida")]),
    ])
    assert [l.estado for l in resumo.linhas] == ["ok", "pendente", "rejeitado"]
    assert resumo.quantos("ok") == 1
    assert resumo.linhas[1].rotulo == "AGUARDA ASSINATURA"


def test_sem_ocorrencia_nao_e_sucesso(ler):
    """Registro sem código não é "deu certo": é "o banco não disse nada".
    Tratar como sucesso daria o pagamento por feito sem nenhuma prova."""
    resumo = ler([_Pagamento("001")])
    assert resumo.linhas[0].estado == "?"
    assert resumo.linhas[0].rotulo == "SEM RESPOSTA"


def test_tudo_pendente_mantem_a_remessa_como_enviada(ler):
    """O caso normal do primeiro retorno: o app agenda e o master assina
    depois. Marcar como processada esconderia que o dinheiro não saiu."""
    resumo = ler([_Pagamento("001", ocorrencias=[("PD", "x")], _pendente=True)])
    assert resumo.estado_da_remessa == "enviado"


def test_tudo_pago_marca_como_processada(ler):
    resumo = ler([_Pagamento("001", ocorrencias=[("00", "x")], _sucesso=True)])
    assert resumo.estado_da_remessa == "processado"


def test_um_rejeitado_contamina_a_remessa(ler):
    resumo = ler([
        _Pagamento("001", ocorrencias=[("00", "x")], _sucesso=True),
        _Pagamento("002", ocorrencias=[("AG", "y")]),
    ])
    assert resumo.estado_da_remessa == "rejeitado"


def test_o_estado_gravado_mantem_a_remessa_viva(ler):
    """A trava contra pagar duas vezes, em um assert.

    `remessa_dia._ja_enviado` só enxerga item de remessa VIVA. Um estado fora
    da lista tira a remessa inteira da pergunta "isto já foi mandado?" — e os
    pagamentos que o banco PAGOU voltam marcáveis na geração seguinte. Foi o
    que o `"com_erro"` fazia, sem erro nenhum: a coluna `estado` do banco não
    tem `check`, então a marcação era aceita em silêncio."""
    casos = {
        "vazio": [],
        "tudo pendente": [_Pagamento("001", ocorrencias=[("PD", "x")],
                                     _pendente=True)],
        "tudo pago": [_Pagamento("001", ocorrencias=[("00", "x")],
                                 _sucesso=True)],
        "um rejeitado": [_Pagamento("001", ocorrencias=[("AG", "y")])],
        "mistura": [_Pagamento("001", ocorrencias=[("00", "x")], _sucesso=True),
                    _Pagamento("002", ocorrencias=[("PD", "x")], _pendente=True),
                    _Pagamento("003", ocorrencias=[("AG", "y")]),
                    _Pagamento("004")],
    }
    for nome, pagamentos in casos.items():
        estado = ler(pagamentos).estado_da_remessa
        assert estado in historico.ESTADOS, nome
        assert estado in registro.ESTADOS_VIVOS, nome


def test_casa_com_o_lancamento_do_erp(ler):
    """É o de-para que faz o retorno reencontrar o caminho de volta: sem ele,
    "002 rejeitado" não diz qual pagamento do ERP precisa de atenção."""
    resumo = ler([_Pagamento("001", ocorrencias=[("00", "x")], _sucesso=True)],
                 _Historico(_remessa([("001", "id-do-erp-99")])))
    assert resumo.linhas[0].referencia == "id-do-erp-99"
    assert not resumo.remessa_desconhecida


def test_pagamento_que_nao_voltou_e_apontado(ler):
    """O banco devolve o que processou. O que sumiu no caminho não aparece
    em lugar nenhum do arquivo — só comparando com o que foi enviado."""
    resumo = ler([_Pagamento("001", ocorrencias=[("00", "x")], _sucesso=True)],
                 _Historico(_remessa([("001", "a"), ("002", "b"),
                                      ("003", "c")])))
    assert resumo.faltando == ["002", "003"]


def test_remessa_de_outra_maquina_e_reconhecida_como_desconhecida(ler):
    """Não confundir com "remessa vazia": uma pede aviso na tela e impede
    guardar o resultado, a outra é só uma remessa sem itens."""
    resumo = ler([_Pagamento("001")], _Historico(_remessa([("x", "y")], nsa=99)))
    assert resumo.remessa_desconhecida
    assert resumo.faltando == []


# ------------------------------- o segundo caminho: o "seu número"

#: Um retorno cujo header não bate com nada: convênio reescrito no painel, NSA
#: ajustado à mão, ou remessa gerada em outra máquina antes do registro.
_HEADER_ERRADO = {"convenio": "9999", "nsa": 99}


def _pago(seu):
    return _Pagamento(seu, ocorrencias=[("00", "ok")], _sucesso=True)


def test_o_header_errado_nao_perde_mais_o_retorno(ler):
    """O caso que este caminho existe para resolver.

    Sem ele, convênio+NSA não casando era `remessa_desconhecida`: a tela lia o
    arquivo e não guardava nada nem dava baixa, porque a `referencia` de cada
    linha só existe com a remessa conhecida. O "seu número" é NOSSO, único no
    dia desde o índice, e o `remessa_item` o guarda com a remessa ligada.
    """
    hist = _Historico(_remessa(
        [("260904-0001", "id-erp-1"), ("260904-0002", "id-erp-2")],
        nsa=31, convenio="1814",
        arquivo=r"C:\PAGAMENTOS\EMPRESA A\SICOOB 4321-123456\REM_000031.REM"))

    resumo = ler([_pago("260904-0001"), _pago("260904-0002")], hist,
                 **_HEADER_ERRADO)

    assert not resumo.remessa_desconhecida
    assert resumo.casado_pelo_seu_numero
    # O que vale daqui em diante é o do REGISTRO: é para esta remessa que o
    # `aplicar_retorno` grava e é este número que nomeia a cópia do `.RET`.
    assert (resumo.convenio, resumo.nsa) == ("1814", 31)
    # E o que o arquivo dizia continua à mão, para a tela poder mostrar os dois.
    assert (resumo.convenio_do_header, resumo.nsa_do_header) == ("9999", 99)
    # A `referencia` é o que permite dar baixa no ERP — é ela que estava
    # faltando quando o retorno caía como desconhecido.
    assert [l.referencia for l in resumo.linhas] == ["id-erp-1", "id-erp-2"]
    assert Path(resumo.pasta_da_remessa).name == "SICOOB 4321-123456"


def test_seus_numeros_espalhados_em_duas_remessas_nao_casam(ler):
    """Adivinhar aqui é aplicar o retorno na remessa errada.

    A repetição de "seu número" existe no histórico de verdade: até o índice
    único do dia entrar (04/09/2026), a segunda remessa do dia podia repetir a
    numeração da primeira, e foi o que aconteceu em 20/08/2026. Dois donos para
    a mesma lista é a prova de que não dá para saber de qual delas o arquivo
    fala — e o desfecho seguro é o de sempre.
    """
    hist = _Historico(_remessa([("260904-0001", "a")], nsa=31)
                      + _remessa([("260904-0002", "b")], nsa=32))

    resumo = ler([_pago("260904-0001"), _pago("260904-0002")], hist,
                 **_HEADER_ERRADO)

    assert resumo.remessa_desconhecida
    assert not resumo.casado_pelo_seu_numero
    assert resumo.linhas[0].referencia == ""
    # E os números continuam sendo os do arquivo: é tudo o que se sabe.
    assert (resumo.convenio, resumo.nsa) == ("9999", 99)


def test_nenhum_seu_numero_conhecido_continua_desconhecida(ler):
    """Retorno de verdade de uma remessa que este registro nunca viu."""
    hist = _Historico(_remessa([("260904-0001", "a")], nsa=31))

    resumo = ler([_pago("260904-7777")], hist, **_HEADER_ERRADO)

    assert resumo.remessa_desconhecida
    assert not resumo.casado_pelo_seu_numero
    assert resumo.pasta_da_remessa == ""


def test_o_header_certo_nao_pergunta_pelo_seu_numero(ler):
    """O caminho de sempre resolve o dia normal, e continua sendo o primeiro.

    O segundo é consulta a mais no banco, e o caso comum não pode pagar por
    ele: são até 18 contas lidas duas vezes por dia.
    """
    hist = _Historico(_remessa([("260904-0001", "id-erp-1")], nsa=31,
                               convenio="1814"))

    resumo = ler([_pago("260904-0001")], hist, nsa=31, convenio="1814")

    assert not resumo.casado_pelo_seu_numero
    assert (resumo.convenio, resumo.nsa) == ("1814", 31)
    # O que o header diz é gravado sempre, mesmo batendo: é o par que a tela
    # compara, e um campo que só existe no caso raro é um campo que ninguém
    # confere.
    assert (resumo.convenio_do_header, resumo.nsa_do_header) == ("1814", 31)
    assert resumo.linhas[0].referencia == "id-erp-1"
    assert hist.perguntas == []


def test_registro_sem_o_segundo_caminho_volta_a_ser_o_de_antes(ler):
    """O segundo caminho é oferta, não exigência: quem não souber respondê-lo
    se comporta exatamente como antes deste PR."""
    resumo = ler([_pago("260904-0001")], _HistoricoAntigo(), **_HEADER_ERRADO)

    assert resumo.remessa_desconhecida
    assert not resumo.casado_pelo_seu_numero


def test_o_segundo_caminho_recebe_os_seus_numeros_do_arquivo(ler):
    """A lista vai inteira, e é a lista que decide — não o primeiro que casar."""
    hist = _Historico([])

    ler([_pago("260904-0001"), _pago("260904-0002")], hist, **_HEADER_ERRADO)

    assert hist.perguntas == [["260904-0001", "260904-0002"]]


def test_sem_historico_le_o_arquivo_do_mesmo_jeito(ler):
    """O arquivo é a informação; o registro só enriquece. Sem rede, ver o que
    o banco respondeu continua valendo."""
    resumo = ler([_Pagamento("001", ocorrencias=[("00", "x")], _sucesso=True)])
    assert len(resumo.linhas) == 1
    assert resumo.linhas[0].referencia == ""
    assert not resumo.remessa_desconhecida


# ------------------------------------------- o que vai para o registro

def test_as_duas_ocorrencias_entram_nos_codigos(ler):
    """O banco manda mais de um código por pagamento, e a que explica a
    recusa nem sempre é a de cima.

    Enquanto os códigos eram arrancados de volta da frase do `motivos`
    (`motivos.split("=")[0]`), o segundo sumia — e sumia calado, porque um
    código sozinho é exatamente o que se espera ver ali."""
    resumo = ler([_Pagamento("001", ocorrencias=[("AG", "conta invalida"),
                                                 ("BD", "saldo insuficiente")])])
    linha = resumo.linhas[0]
    assert linha.codigos == ["AG", "BD"]
    # E o `motivos` continua sendo a frase para gente ler, intacta: os dois
    # campos existem porque são coisas diferentes.
    assert linha.motivos == "AG=conta invalida; BD=saldo insuficiente"


def test_respostas_para_registro_leva_codigo_e_estado(ler):
    """A classificação é julgamento de RETORNO, e vai gravada.

    Sem ela, o painel do dia teria de traduzir código de ocorrência de novo —
    uma segunda tabela dizendo o que "AG" quer dizer, envelhecendo em silêncio
    ao lado desta."""
    resumo = ler([
        _Pagamento("001", ocorrencias=[("00", "ok")], _sucesso=True),
        _Pagamento("002", ocorrencias=[("PD", "pendente")], _pendente=True),
        _Pagamento("003", ocorrencias=[("AG", "x"), ("BD", "y")]),
    ])
    assert retorno_dia.respostas_para_registro(resumo) == {
        "001": {"codigo": "00", "estado": "ok"},
        "002": {"codigo": "PD", "estado": "pendente"},
        "003": {"codigo": "AG;BD", "estado": "rejeitado"},
    }


def test_respostas_para_registro_pula_quem_o_banco_nao_citou(ler):
    """Silêncio do banco não é resposta. É a mesma regra do `aplicar_retorno`,
    e o motivo é o retorno de DEPOIS da assinatura: gravar "" por cima
    apagaria o `PD` que o primeiro retorno tinha dito."""
    resumo = ler([_Pagamento("001", ocorrencias=[("00", "x")], _sucesso=True),
                  _Pagamento("002")])
    respostas = retorno_dia.respostas_para_registro(resumo)
    assert list(respostas) == ["001"]
    assert resumo.linhas[1].estado == "?"     # a linha existe; a resposta não


# ------------------------------------------- a pasta da remessa que gerou

def test_a_pasta_da_remessa_sai_do_registro(ler):
    """A cópia do retorno vai para onde o `.REM` está — pergunta e resposta na
    mesma pasta. O caminho sai do registro central, que já o guarda."""
    resumo = ler([_Pagamento("001", ocorrencias=[("00", "x")], _sucesso=True)],
                 _Historico(_remessa(
                     [("001", "id-99")],
                     arquivo=r"C:\PAGAMENTOS\EMPRESA A\SICOOB 4321-123456"
                             r"\REM_EMPRESA-A_000001.REM")))
    assert Path(resumo.pasta_da_remessa).name == "SICOOB 4321-123456"


def test_sem_o_caminho_no_registro_a_pasta_sai_vazia(ler):
    """Remessa gerada antes de o campo existir: a leitura continua valendo, e
    quem chama é que decide para onde a cópia vai."""
    resumo = ler([_Pagamento("001", ocorrencias=[("00", "x")], _sucesso=True)],
                 _Historico(_remessa([("001", "id-99")])))
    assert resumo.pasta_da_remessa == ""


def test_remessa_desconhecida_nao_tem_pasta(ler):
    resumo = ler([_Pagamento("001")], _Historico(_remessa([("x", "y")], nsa=99)))
    assert resumo.remessa_desconhecida
    assert resumo.pasta_da_remessa == ""


# ------------------------------------------------- vários arquivos de uma vez

#: Os textos que o parser falso reconhece. O conteúdo não importa — quem lê
#: CNAB de verdade é o `cnab240`, e ele tem os testes dele.
_RETORNO = "RETORNO SINTETICO\n"
_REMESSA = "REMESSA SINTETICA\n"


@pytest.fixture
def parser(monkeypatch):
    """Põe um `cnab240.ler_retorno` que julga pelo primeiro pedaço do texto.

    É o que permite exercitar o `ler_varios` com arquivos DE VERDADE no disco
    (é disso que trata o teste) sem montar um CNAB 240 válido por arquivo.
    """
    import cnab240

    def _falso(texto):
        if texto.startswith("REMESSA"):
            return _Arquivo([], e_retorno=False)
        if texto.startswith("RETORNO"):
            return _Arquivo([_Pagamento("001", ocorrencias=[("00", "ok")],
                                        _sucesso=True)])
        raise ValueError("arquivo com menos de duas linhas")

    monkeypatch.setattr(cnab240, "ler_retorno", _falso, raising=False)


def test_ler_varios_devolve_o_bom_e_os_dois_ruins_na_ordem(parser, tmp_path):
    """Um arquivo ruim não pode custar a leitura dos outros.

    Lendo os retornos de 18 contas de uma vez, quem escolheu os arquivos já
    fechou o diálogo: parar no primeiro erro obrigaria a repetir a escolha
    inteira, e é assim que alguém deixa de ler o retorno de uma conta.
    """
    bom = tmp_path / "bom.RET"; bom.write_text(_RETORNO, encoding="latin-1")
    ruim = tmp_path / "ruim.RET"; ruim.write_text(_REMESSA, encoding="latin-1")
    sumido = tmp_path / "nao-existe.RET"

    saida = retorno_dia.ler_varios([bom, ruim, sumido])

    assert [type(r) for r in saida] == [retorno_dia.Resumo,
                                        retorno_dia.Falha, retorno_dia.Falha]
    assert saida[0].origem == "bom.RET"
    assert saida[1].origem == "ruim.RET"
    assert "não é um retorno" in saida[1].motivo
    assert saida[2].origem == "nao-existe.RET"
    # E o motivo sai em português: o `FileNotFoundError` chega em inglês e com
    # um errno na frente, e sumir arquivo da pasta de downloads é o caso mais
    # provável de todos.
    assert "não achei o arquivo" in saida[2].motivo


def test_o_zip_do_sicoobnet_vira_um_resumo_por_membro(parser, tmp_path):
    """O SicoobNet entrega os retornos compactados, e ninguém vai descompactar
    18 arquivos à mão. Os membros saem em ordem de NOME: a ordem de dentro do
    zip é a do compactador, e não quer dizer nada para quem lê."""
    caminho = tmp_path / "retornos.zip"
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr("b.RET", _RETORNO)
        z.writestr("a.RET", _RETORNO)

    saida = retorno_dia.ler_varios([caminho])

    assert [r.origem for r in saida] == ["retornos.zip/a.RET",
                                         "retornos.zip/b.RET"]
    assert all(isinstance(r, retorno_dia.Resumo) for r in saida)


def test_zip_corrompido_vira_uma_falha_so(parser, tmp_path):
    """Não há membro para culpar: a falha é do compactado inteiro."""
    caminho = tmp_path / "quebrado.zip"
    caminho.write_bytes(b"PK\x03\x04 isto nao e um zip")

    saida = retorno_dia.ler_varios([caminho])

    assert len(saida) == 1
    assert isinstance(saida[0], retorno_dia.Falha)
    assert saida[0].origem == "quebrado.zip"
    assert saida[0].motivo


# ------------------------------------------------------- a cópia do arquivo

def test_o_nome_da_copia_diz_conta_nsa_e_quando(ler):
    """O mesmo NSA é lido DUAS vezes — o retorno do dia, com tudo pendente de
    assinatura, e o de depois de o master liberar. Sem a hora no nome, o
    segundo não teria como conviver com o primeiro."""
    resumo = ler([_Pagamento("001", ocorrencias=[("00", "x")], _sucesso=True)],
                 nsa=31)
    nome = retorno_dia.nome_da_copia(
        resumo, datetime.datetime(2026, 9, 4, 15, 12))

    assert nome == "RET_EMPRESA-A_4321-123456_000031_20260904-1512.RET"
    # E nada que o Windows recuse num nome de arquivo.
    assert not set(nome) & set('\\/:*?"<>|')


def test_guardar_copia_nunca_sobrescreve(tmp_path):
    """A primeira cópia é a prova de que o arquivo foi ACEITO pelo banco.

    É o mesmo defeito que o `retorno_historico` fechou do lado do banco de
    dados: o segundo retorno do mesmo NSA apagando o primeiro.
    """
    primeiro = retorno_dia.guardar_copia(b"o retorno do dia", tmp_path,
                                         "RET_X_000001_20260904-0900.RET")
    segundo = retorno_dia.guardar_copia(b"o retorno de depois", tmp_path,
                                        "RET_X_000001_20260904-0900.RET")

    assert primeiro != segundo
    assert segundo.name.endswith("-2.RET")
    assert primeiro.read_bytes() == b"o retorno do dia"
    assert segundo.read_bytes() == b"o retorno de depois"
    assert len(list(tmp_path.glob("*.RET"))) == 2


def test_guardar_copia_cria_a_pasta_que_falta(tmp_path):
    """A `_RETORNOS/` do destino do dia não existe até o primeiro retorno."""
    alvo = retorno_dia.guardar_copia(b"x", tmp_path / "_RETORNOS", "a.RET")
    assert alvo.read_bytes() == b"x"
