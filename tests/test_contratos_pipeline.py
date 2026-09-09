# -*- coding: utf-8 -*-
"""O pipeline inteiro, com uma API dublê — nenhum teste toca o ERP.

O cenário abaixo é um mês em miniatura, com nomes trocados: quatro casas que
receberam, duas delas numa obra de PESSOA FÍSICA, que não tem pasta de
fechamento, e um recebimento sem casa na descrição. O resultado certo é 2
arquiváveis e 3 em revisão.
"""
from pathlib import Path

import pytest

from contratos.pipeline import (Achado, aplicar_resolucao, arquivar,
                                chave_da_casa, esperado_da_conferencia,
                                levantar, pode_resolver, preparar_destino,
                                reaplicar)


class _Empresa:
    def __init__(self, nome, clientes, cnpj="", razao_social=""):
        self.nome, self.clientes_erp = nome, clientes
        self.cnpj, self.razao_social = cnpj, razao_social


EMPRESAS = [_Empresa("BURITIS", ["EMPRESA BURITIS LTDA"],
                     cnpj="12.345.678/0001-90",
                     razao_social="EMPRESA BURITIS EMPREENDIMENTOS LTDA")]

OBRAS = [
    {"id": "obra-1", "name": "TB 21 QD 46 LT 18",
     "customer": {"name": "EMPRESA BURITIS LTDA"}},
    {"id": "obra-2", "name": "FERROVIARIOS QD 01 LT 12",
     "customer": {"name": "PESSOA FISICA QUALQUER"}},
]

CCV_CS01 = "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01 .pdf"
CCV_CS02 = "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 02 .pdf"

ANEXOS = {
    "obra-1": [
        {"id": "x1", "filename": "CONTRATO TB 21 QD 46 LT 18 CS 01 .pdf",
         "extension": ".pdf", "downloadUrl": "https://exemplo.invalid/1"},
        {"id": "x2", "filename": "CONTRATO TB 21 QD 46 LT 18 CS 02 .pdf",
         "extension": ".pdf", "downloadUrl": "https://exemplo.invalid/2"},
        {"id": "x3", "filename": CCV_CS01,
         "extension": ".pdf", "downloadUrl": "https://exemplo.invalid/3"},
        {"id": "x4", "filename": CCV_CS02,
         "extension": ".pdf", "downloadUrl": "https://exemplo.invalid/4"},
    ],
    "obra-2": [
        {"id": "y1", "filename": "CONTRATO DE COMPRA E VENDA FERROVIARIOS QD 01 LT 12 CS 01 .pdf",
         "extension": ".pdf", "downloadUrl": "https://exemplo.invalid/5"},
        {"id": "y2", "filename": "CONTRATO DE COMPRA E VENDA FERROVIARIOS QD 01 LT 12 CS 02 .pdf",
         "extension": ".pdf", "downloadUrl": "https://exemplo.invalid/6"},
    ],
}

TEXTO = """CONTRATO DE COMPRA E VENDA
VENDEDOR: EMPRESA BURITIS EMPREENDIMENTOS LTDA, CNPJ 12.345.678/0001-90.
COMPRADOR: PRIMEIRO COMPRADOR EXEMPLO, brasileiro.
Imovel na Rua TB 21, QD 46 LT 18, CASA 01, bairro exemplo.
Valor de aquisicao: R$ 245.000,00.
As partes assinam em duas vias de igual teor e forma.
"""


def receb(obra, casa, comprador, condicao="1ª Sinal", valor=10000.0,
          descricao=None):
    return {"workName": obra,
            "description": descricao or f"VENDA CASA {casa:02d} - {comprador}",
            "readjustmentType": condicao, "nature": "Venda",
            "dateOfReceipt": "2026-08-15", "sumOfReceivedValues": valor,
            "saleValue": 245000.0, "id": f"{obra}-{casa}-{condicao}"}


class Leitor:
    """Dublê do LeitorPDF: devolve o texto combinado e anota o que pediram."""

    def __init__(self, texto, resto=None, total=3):
        self.t, self.resto, self.total = texto, resto, total
        self.pedidos = []
        self.origem = "camada de texto"

    def texto(self, ate=None):
        self.pedidos.append(ate)
        if ate is None and self.resto is not None:
            return self.t + "\n" + self.resto
        return self.t

    def tem_mais(self, ate):
        return self.total > ate


class ApiDuble:
    """Só o que o pipeline usa. Registra o que foi pedido."""

    def __init__(self, registros, credenciais=True):
        self.registros = registros
        self.baixados = []
        self.credenciais = credenciais     # a captura do 2º back-end deu certo?
        self.chamadas = []                 # em que ordem o pipeline pediu

    def garantir_credenciais_anexos(self, log=print):
        self.chamadas.append("credenciais")
        return self.credenciais

    def listar_recebimentos(self, inicio, fim, log=print):
        self.chamadas.append("recebimentos")
        return self.registros

    def listar_obras(self, log=print):
        self.chamadas.append("obras")
        return OBRAS

    def anexos_de_obras(self, ids, log=print, cancelar=None):
        return {i: ANEXOS.get(i, []) for i in ids}

    def detalhe_da_obra(self, work_id):
        return {"address": {"address": "Rua TB 21", "complement": "QD 46 LT 18"}}

    def baixar_anexo(self, url):
        self.baixados.append(url)
        return b"%PDF-falso"


REGISTROS = [
    receb("TB 21 QD 46 LT 18", 1, "PRIMEIRO COMPRADOR EXEMPLO", "1ª Sinal"),
    receb("TB 21 QD 46 LT 18", 1, "PRIMEIRO COMPRADOR EXEMPLO", "1ª Entrada",
          valor=20000.0),
    receb("TB 21 QD 46 LT 18", 2, "SEGUNDO COMPRADOR EXEMPLO", "1ª FINANCIAMENTO",
          valor=200000.0),
    receb("FERROVIARIOS QD 01 LT 12", 1, "TERCEIRO COMPRADOR EXEMPLO"),
    receb("FERROVIARIOS QD 01 LT 12", 2, "QUARTO COMPRADOR EXEMPLO"),
    receb("TB 21 QD 46 LT 18", 0, "QUINTO COMPRADOR EXEMPLO",
          descricao="VENDA DO IMOVEL - QUINTO COMPRADOR EXEMPLO"),
]


def _sem_log(_m):
    pass


def _levantar(registros=REGISTROS, api=None):
    return levantar(api or ApiDuble(registros), 2026, 8, EMPRESAS, log=_sem_log)


def test_o_mes_devolve_cinco_linhas_tres_em_revisao():
    """2 arquiváveis; 2 de obra de pessoa física (sem pasta de fechamento) e
    1 recebimento sem casa na descrição, os três em revisão e visíveis."""
    achados = _levantar()
    assert len(achados) == 5
    com_destino = [a for a in achados if not a.revisao]
    em_revisao = [a for a in achados if a.revisao]
    assert len(com_destino) == 2 and len(em_revisao) == 3
    assert sum("não está mapeado" in a.revisao for a in em_revisao) == 2
    assert sum("não diz a casa" in a.revisao for a in em_revisao) == 1
    assert {a.empresa for a in com_destino} == {"BURITIS"}


def test_cada_casa_pega_o_contrato_de_compra_e_venda():
    achados = _levantar()
    por_casa = {a.imovel.unidade: a.contrato for a in achados if a.empresa}
    assert por_casa[1] == CCV_CS01
    assert por_casa[2] == CCV_CS02


def test_os_recebimentos_da_casa_ficam_juntos():
    a = next(x for x in _levantar() if x.imovel.unidade == 1 and x.empresa)
    assert len(a.imovel.recebimentos) == 2
    assert str(a.imovel.recebido) == "30000.00"


def test_a_empresa_traz_cnpj_e_razao_social_para_a_vendedora():
    a = next(x for x in _levantar() if x.empresa)
    esperado = esperado_da_conferencia(a)
    assert esperado["cnpj"] == "12.345.678/0001-90"
    assert "EMPRESA BURITIS EMPREENDIMENTOS LTDA" in esperado["vendedora"]
    assert "EMPRESA BURITIS LTDA" in esperado["vendedora"]      # cliente no ERP
    assert str(esperado["valor_venda"]) == "245000.00"


def test_mes_vazio_e_resposta_e_nao_falha():
    assert _levantar([]) == []


def test_qualquer_condicao_entra():
    registros = [receb("TB 21 QD 46 LT 18", 1, "X", condicao="1ª Reembolso Vistoria")]
    achados = _levantar(registros)
    assert len(achados) == 1 and achados[0].contrato == CCV_CS01


def test_obra_que_nao_existe_no_cadastro_vai_para_revisao():
    achados = _levantar([receb("OBRA QUE NAO EXISTE", 1, "X")])
    assert len(achados) == 1 and "não achei a obra" in achados[0].revisao


def test_linha_sem_casa_ainda_diz_a_obra_e_o_cliente():
    a = next(x for x in _levantar() if "não diz a casa" in x.revisao)
    assert a.obra_id == "obra-1" and a.cliente_erp == "EMPRESA BURITIS LTDA"
    assert not pode_resolver(a)               # a correção é no ERP


# ------------------------------------------------- desempate pelo conteúdo
DISPUTA = {
    "obra-1": [
        {"id": "d1", "filename": "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01 .pdf",
         "extension": ".pdf", "downloadUrl": "https://exemplo.invalid/d1"},
        {"id": "d2", "filename": "CONTRATO DE COMPRA E VENDA TB 21 QD46 LT18 CS 01 .pdf",
         "extension": ".pdf", "downloadUrl": "https://exemplo.invalid/d2"},
    ],
}


class ApiDisputa(ApiDuble):
    def __init__(self, registros, por_url):
        super().__init__(registros)
        self.por_url = por_url

    def anexos_de_obras(self, ids, log=print, cancelar=None):
        return {i: DISPUTA.get(i, []) for i in ids}

    def baixar_anexo(self, url):
        self.baixados.append(url)
        return self.por_url.get(url)


def test_dois_nomes_para_o_mesmo_arquivo_resolvem_sozinhos():
    """Metade das disputas de agosto/2026 era isto: o mesmo PDF subido duas
    vezes com o nome escrito de outro jeito."""
    api = ApiDisputa([REGISTROS[0]], {"https://exemplo.invalid/d1": b"%PDF-igual",
                                      "https://exemplo.invalid/d2": b"%PDF-igual"})
    recados = []
    a = levantar(api, 2026, 8, EMPRESAS, log=recados.append)[0]
    assert a.anexo and a.anexo["id"] == "d1" and not a.revisao and a.marcado
    assert sorted(api.baixados) == ["https://exemplo.invalid/d1", "https://exemplo.invalid/d2"]
    assert any("um só arquivo" in m for m in recados)


def test_dois_arquivos_diferentes_continuam_em_revisao_com_os_tamanhos():
    api = ApiDisputa([REGISTROS[0]], {"https://exemplo.invalid/d1": b"%PDF-" + b"a" * 2048,
                                      "https://exemplo.invalid/d2": b"%PDF-" + b"b" * 4096})
    a = levantar(api, 2026, 8, EMPRESAS, log=_sem_log)[0]
    assert not a.anexo and "DIFERENTES" in a.revisao
    assert "(2 KB)" in a.revisao and "(4 KB)" in a.revisao


def test_download_que_falha_no_desempate_deixa_a_disputa_como_estava():
    api = ApiDisputa([REGISTROS[0]], {"https://exemplo.invalid/d1": b"%PDF-igual"})
    a = levantar(api, 2026, 8, EMPRESAS, log=_sem_log)[0]
    assert not a.anexo and "disputam" in a.revisao and "DIFERENTES" not in a.revisao


# --------------------------------------------- acesso ao segundo back-end
def test_a_busca_prepara_o_acesso_antes_de_ler_as_obras():
    api = ApiDuble(REGISTROS)
    _levantar(api=api)
    assert api.chamadas[0] == "credenciais"
    assert "obras" in api.chamadas


def test_sem_acesso_ao_segundo_back_end_a_busca_para_e_diz_o_que_fazer():
    api = ApiDuble(REGISTROS, credenciais=False)
    with pytest.raises(RuntimeError) as e:
        _levantar(api=api)
    assert "obras e anexos" in str(e.value)
    assert "rode de novo" in str(e.value)
    assert "obras" not in api.chamadas      # nem tentou ler sem cabeçalho


# ------------------------------------------------------------- arquivamento
def _nome_mes(m):
    return "AGOSTO"


def _pasta_empresa(a, m, e):
    return f"AGOSTO {a} - {e}"


def _arquivar(api, achados, raiz, leitor=None, **kw):
    return arquivar(api, achados, raiz, 2026, 8, _nome_mes, _pasta_empresa,
                    abrir_pdf=leitor or (lambda b: Leitor(TEXTO)),
                    log=_sem_log, **kw)


def test_arquiva_o_que_confere_e_retem_o_que_diverge(tmp_path):
    api = ApiDuble(REGISTROS)
    achados = _levantar(api=api)
    _arquivar(api, achados, tmp_path)

    arquivados = [a for a in achados if a.arquivado]
    # A casa 01 confere; a 02 diverge (o texto diz CASA 01 e outro comprador).
    assert len(arquivados) == 1
    assert arquivados[0].imovel.unidade == 1
    assert arquivados[0].destino.is_file()
    assert arquivados[0].destino.stat().st_size > 0
    assert arquivados[0].destino.name.startswith(
        "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01 - PRIMEIRO")
    assert arquivados[0].destino.parent == (
        tmp_path / "2026" / "AGOSTO" / "AGOSTO 2026 - BURITIS" / "CONTRATOS")
    assert arquivados[0].leitura == "camada de texto"

    retido = [a for a in achados if a.anexo and not a.arquivado and a.empresa]
    assert retido and "diverge em" in retido[0].revisao
    assert "casa" in retido[0].revisao and "comprador" in retido[0].revisao


def test_texto_ilegivel_nao_retem(tmp_path):
    """`?` não segura o arquivo: contrato ilegível não é contrato errado."""
    api = ApiDuble(REGISTROS)
    achados = _levantar(api=api)
    _arquivar(api, achados, tmp_path, leitor=lambda b: Leitor(""))
    assert len([a for a in achados if a.arquivado]) == 2


def test_le_o_resto_do_contrato_so_quando_sobrou_interrogacao(tmp_path):
    """As primeiras páginas primeiro; o documento inteiro só se faltou algo."""
    inicio = TEXTO.replace("Valor de aquisicao: R$ 245.000,00.", "")
    leitores = []

    def abrir(_b):
        leitor = Leitor(inicio, resto="Valor de aquisicao: R$ 245.000,00.",
                        total=20)
        leitores.append(leitor)
        return leitor

    api = ApiDuble(REGISTROS)
    achados = _levantar(api=api)
    _arquivar(api, achados, tmp_path, leitor=abrir)
    casa1 = next(a for a in achados if a.imovel.unidade == 1 and a.empresa)
    assert casa1.arquivado
    assert casa1.resultado_conferencia["valor"] == "CONFERE"
    assert leitores[0].pedidos == [3, None]       # pediu o resto


def test_nao_le_o_resto_quando_as_primeiras_paginas_bastam(tmp_path):
    leitores = []

    def abrir(_b):
        leitor = Leitor(TEXTO, resto="nada", total=20)
        leitores.append(leitor)
        return leitor

    api = ApiDuble(REGISTROS)
    achados = _levantar(api=api)
    _arquivar(api, achados, tmp_path, leitor=abrir)
    assert leitores[0].pedidos == [3]


def test_download_vazio_nao_derruba_os_outros(tmp_path):
    api = ApiDuble(REGISTROS)
    api.baixar_anexo = lambda url: None
    achados = _levantar(api=api)
    _arquivar(api, achados, tmp_path)
    assert not any(a.arquivado for a in achados)
    assert all("download" in a.revisao for a in achados if a.anexo and a.empresa)


# ------------------------------------------------- nunca grava por cima
def _pasta_buritis(raiz):
    p = raiz / "2026" / "AGOSTO" / "AGOSTO 2026 - BURITIS" / "CONTRATOS"
    p.mkdir(parents=True)
    return p


def test_mesmo_arquivo_ja_na_pasta_e_ja_estava(tmp_path):
    pasta = _pasta_buritis(tmp_path)
    (pasta / "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01 - PRIMEIRO COMPRADOR EXEMPLO.pdf"
     ).write_bytes(b"%PDF-falso")
    api = ApiDuble(REGISTROS)
    achados = _levantar(api=api)
    _arquivar(api, achados, tmp_path)
    casa1 = next(a for a in achados if a.imovel.unidade == 1 and a.empresa)
    assert casa1.arquivado and casa1.ja_existia


def test_mesmo_nome_com_conteudo_diferente_e_revisao(tmp_path):
    pasta = _pasta_buritis(tmp_path)
    alvo = pasta / "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01 - PRIMEIRO COMPRADOR EXEMPLO.pdf"
    alvo.write_bytes(b"outro conteudo, posto a mao")
    api = ApiDuble(REGISTROS)
    achados = _levantar(api=api)
    _arquivar(api, achados, tmp_path)
    casa1 = next(a for a in achados if a.imovel.unidade == 1 and a.empresa)
    assert not casa1.arquivado and "conteúdo diferente" in casa1.revisao
    assert alvo.read_bytes() == b"outro conteudo, posto a mao"   # intocado


def test_mesma_casa_com_outro_nome_na_pasta_e_revisao_sem_baixar(tmp_path):
    pasta = _pasta_buritis(tmp_path)
    (pasta / "CONTRATO DE COMPRA E VENDA TB 21 QD46 LT18 CASA 1 - OUTRO NOME.pdf"
     ).write_bytes(b"x")
    api = ApiDuble(REGISTROS)
    achados = _levantar(api=api)
    _arquivar(api, achados, tmp_path)
    casa1 = next(a for a in achados if a.imovel.unidade == 1 and a.empresa)
    assert not casa1.arquivado and "outro nome" in casa1.revisao
    assert "https://exemplo.invalid/3" not in api.baixados


def test_o_contrato_da_caixa_na_pasta_nao_atrapalha(tmp_path):
    """A pasta guarda o da Caixa desde 2024, com o nome sem prefixo."""
    pasta = _pasta_buritis(tmp_path)
    (pasta / "CONTRATO TB 21 QD 46 LT 18 CS 01 - PRIMEIRO COMPRADOR EXEMPLO.pdf"
     ).write_bytes(b"caixa")
    api = ApiDuble(REGISTROS)
    achados = _levantar(api=api)
    _arquivar(api, achados, tmp_path)
    casa1 = next(a for a in achados if a.imovel.unidade == 1 and a.empresa)
    assert casa1.arquivado and not casa1.ja_existia
    assert len(list(pasta.iterdir())) == 2


# -------------------------------------------- marcação e resolver à mão
def test_nasce_marcado_so_o_que_da_para_arquivar():
    achados = _levantar()
    assert [a.marcado for a in achados].count(True) == 2
    assert all(a.marcado is False for a in achados if a.revisao)


def test_a_lista_de_anexos_da_obra_fica_guardada():
    """É o que a janela de resolver mostra. Antes era lida e jogada fora, e a
    casa em dúvida não tinha saída pela tela."""
    for a in _levantar():
        if a.imovel.unidade:
            assert len(a.anexos_da_obra) == len(ANEXOS[a.obra_id])


def test_desmarcar_tira_a_casa_da_rodada(tmp_path):
    api = ApiDuble(REGISTROS)
    achados = _levantar(api=api)
    for a in achados:
        a.marcado = False               # a pessoa desmarcou tudo
    _arquivar(api, achados, tmp_path)
    assert not any(a.arquivado for a in achados)
    assert api.baixados == []           # nem baixou


def test_resolver_a_empresa_libera_a_casa_e_traz_o_cnpj():
    achados = _levantar()
    sem_empresa = next(a for a in achados if "não está mapeado" in a.revisao)
    falta = aplicar_resolucao(sem_empresa, empresa_nome="BURITIS",
                              empresas=EMPRESAS)
    assert falta == ""
    assert sem_empresa.marcado and sem_empresa.empresa_manual
    assert sem_empresa.cnpj == "12.345.678/0001-90"
    assert not sem_empresa.contrato_manual


def test_resolver_so_o_contrato_nao_esconde_a_empresa_que_falta():
    """Meia solução não pode virar linha verde: sem empresa não há pasta."""
    achados = _levantar()
    a = next(x for x in achados if "não está mapeado" in x.revisao)
    falta = aplicar_resolucao(a, anexo=a.anexos_da_obra[0])
    assert "não está mapeado" in falta
    assert not a.marcado and a.contrato_manual


def test_sem_obra_no_cadastro_nao_ha_o_que_resolver():
    achados = _levantar([receb("OBRA QUE NAO EXISTE", 1, "X")])
    assert not pode_resolver(achados[0])


def test_a_escolha_da_sessao_volta_na_busca_seguinte():
    """A busca refeita traz outro objeto de anexo (o downloadUrl do S3
    expira), então o que se guarda é o nome do arquivo."""
    achados = _levantar()
    casa = next(a for a in achados if a.empresa)
    escolhido = "CONTRATO TB 21 QD 46 LT 18 CS 01 .pdf"     # a mão pode tudo

    outros = _levantar()
    assert reaplicar(outros, {chave_da_casa(casa): escolhido}, log=_sem_log) == 1
    de_novo = next(a for a in outros if chave_da_casa(a) == chave_da_casa(casa))
    assert de_novo.contrato == escolhido      # a mão venceu a regra
    assert de_novo.contrato_manual and de_novo.marcado


def test_escolha_que_sumiu_da_obra_volta_a_perguntar():
    achados = _levantar()
    casa = next(a for a in achados if a.empresa)
    antes = casa.contrato
    recados = []
    assert reaplicar(achados, {chave_da_casa(casa): "SUMIU .pdf"},
                     log=recados.append) == 0
    assert casa.contrato == antes and not casa.contrato_manual
    assert any("não está mais na obra" in m for m in recados)


def test_arquivar_tambem_confere_o_acesso_antes_de_baixar(tmp_path):
    """Entre buscar e arquivar o ERP pode ter derrubado a sessão (aceita uma
    por usuário). Baixar contrato com a sessão caída é download vazio gravado
    como se fosse contrato."""
    api = ApiDuble(REGISTROS)
    achados = _levantar(api=api)
    api.credenciais = False
    with pytest.raises(RuntimeError):
        _arquivar(api, achados, tmp_path)
    assert not any(a.arquivado for a in achados)
    assert api.baixados == []


def test_caminho_longo_demais_e_recusado_antes_de_gravar(tmp_path):
    achado = Achado(imovel=_levantar()[0].imovel)
    achado.empresa = "BURITIS"
    achado.anexo = {"extension": ".pdf"}
    fundo = Path("C:/" + "x" * 240)
    motivo = preparar_destino(achado, fundo, 2026, 8, _nome_mes, _pasta_empresa)
    assert "260" in motivo
    assert achado.destino is None
