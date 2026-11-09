# -*- coding: utf-8 -*-
"""O pipeline inteiro, com uma API dublê — nenhum teste toca o ERP.

O cenário abaixo é um mês em miniatura, com nomes trocados: quatro casas que
receberam, duas delas numa obra de PESSOA FÍSICA, que não tem pasta de
fechamento, e um recebimento sem casa na descrição. O resultado certo é 2
arquiváveis e 3 em revisão.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from contratos.pipeline import (Achado, _sem_copias_de_texto, anexo_atual,
                                aplicar_resolucao, arquivar,
                                chave_da_casa, esperado_da_conferencia,
                                levantar, pode_resolver, preparar_destino,
                                reaplicar, reaplicar_distratos)


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
          descricao=None, cliente="EMPRESA BURITIS LTDA"):
    return {"workName": obra,
            "description": descricao or f"VENDA CASA {casa:02d} - {comprador}",
            "readjustmentType": condicao, "nature": "Venda",
            "dateOfReceipt": "2026-08-15", "sumOfReceivedValues": valor,
            "saleValue": 245000.0, "customerName": cliente,
            "id": f"{obra}-{casa}-{condicao}"}


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

    def impressao(self):
        return (self.total, ())


class ApiDuble:
    """Só o que o pipeline usa. Registra o que foi pedido."""

    def __init__(self, registros, credenciais=True, anexos=None):
        self.registros = registros
        self.anexos = ANEXOS if anexos is None else anexos
        #: Bytes por URL; o que não está aqui baixa como o PDF falso de sempre.
        self.conteudos = {}
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
        return {i: self.anexos.get(i, []) for i in ids}

    def detalhe_da_obra(self, work_id):
        return {"address": {"address": "Rua TB 21", "complement": "QD 46 LT 18"}}

    def baixar_anexo(self, url):
        self.baixados.append(url)
        return self.conteudos.get(url, b"%PDF-falso")


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


# ------------------------------------------------------ quem é o comprador
def test_o_cliente_do_recebimento_e_o_comprador_quando_e_pessoa():
    """Regra do dono: "sempre o cliente do contrato". As linhas novas de
    agosto/2026 vêm assim: descrição `CASA 3` e o comprador no Cliente."""
    registros = [receb("TB 21 QD 46 LT 18", 1, "", descricao="CASA 1",
                       cliente="PESSOA QUE COMPROU A CASA")]
    a = _levantar(registros)[0]
    assert a.imovel.comprador == "PESSOA QUE COMPROU A CASA"
    assert esperado_da_conferencia(a)["comprador"] == "PESSOA QUE COMPROU A CASA"


def test_cliente_que_e_a_propria_spe_nao_vira_comprador():
    """Em agosto/2026 o Cliente era a SPE em 20 das 25 linhas (financiamento,
    FGTS, juros). Aí vale o nome da descrição."""
    registros = [receb("TB 21 QD 46 LT 18", 1, "PRIMEIRO COMPRADOR EXEMPLO",
                       "1ª FINANCIAMENTO", cliente="EMPRESA BURITIS LTDA"),
                 receb("TB 21 QD 46 LT 18", 2, "SEGUNDO COMPRADOR EXEMPLO",
                       "1ª FGTS", cliente="EMPRESA BURITIS EMPREENDIMENTOS LTDA")]
    achados = _levantar(registros)
    assert achados[0].imovel.comprador == "PRIMEIRO COMPRADOR EXEMPLO"
    assert achados[1].imovel.comprador == "SEGUNDO COMPRADOR EXEMPLO"


def test_cliente_pessoa_vence_o_nome_da_descricao():
    registros = [receb("TB 21 QD 46 LT 18", 1, "NOME ABREVIADO",
                       cliente="NOME COMPLETO DO COMPRADOR")]
    a = _levantar(registros)[0]
    assert a.imovel.comprador == "NOME COMPLETO DO COMPRADOR"
    assert a.imovel.comprador_descricao == "NOME ABREVIADO"


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


# ------------------------------------------------- casa com distrato
#: Dois contratos da casa 01, de compradores diferentes, e o distrato do
#: PRIMEIRO. O recebimento do mês é do SEGUNDO (a casa foi revendida).
CCV_PRIMEIRO = "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01 .pdf"
CCV_SEGUNDO = "CONTRATO DE COMPRA E VENDA TB 21 QD46 LT18 CS 01 .pdf"
DISTRATO_CS01 = "DISTRATO TB 21 QD 46 LT 18 C1 .pdf"
URL_PRIMEIRO = "https://exemplo.invalid/p1"
URL_SEGUNDO = "https://exemplo.invalid/s1"
URL_DISTRATO = "https://exemplo.invalid/dt"

ANEXOS_COM_DISTRATO = {
    "obra-1": [
        {"id": "p1", "filename": CCV_PRIMEIRO, "extension": ".pdf",
         "downloadUrl": URL_PRIMEIRO},
        {"id": "s1", "filename": CCV_SEGUNDO, "extension": ".pdf",
         "downloadUrl": URL_SEGUNDO},
        {"id": "dt", "filename": DISTRATO_CS01, "extension": ".pdf",
         "downloadUrl": URL_DISTRATO},
    ],
}

TEXTO_PRIMEIRO = TEXTO
TEXTO_SEGUNDO = TEXTO.replace("PRIMEIRO", "SEGUNDO")
TEXTO_DISTRATO = ("TERMO DE DISTRATO entre a vendedora e PRIMEIRO COMPRADOR "
                  "EXEMPLO, referente ao imovel TB 21 QD 46 LT 18 CASA 01, "
                  "desfeito por vontade das partes.")


def _abrir_texto(dados):
    """O leitor dublê lê os bytes como texto: o conteúdo baixado É o texto."""
    return Leitor(dados.decode())


def _api_com_distrato():
    api = ApiDuble([receb("TB 21 QD 46 LT 18", 1, "SEGUNDO COMPRADOR EXEMPLO")],
                   anexos=ANEXOS_COM_DISTRATO)
    api.conteudos = {URL_PRIMEIRO: TEXTO_PRIMEIRO.encode(),
                     URL_SEGUNDO: TEXTO_SEGUNDO.encode(),
                     URL_DISTRATO: TEXTO_DISTRATO.encode()}
    return api


def _levantar_com_distrato(api, abrir_pdf=_abrir_texto, log=_sem_log):
    return levantar(api, 2026, 8, EMPRESAS, log=log, abrir_pdf=abrir_pdf)


def test_casa_com_distrato_vira_uma_linha_por_comprador():
    recados = []
    achados = _levantar_com_distrato(_api_com_distrato(), log=recados.append)
    assert len(achados) == 2
    atual, antigo = achados
    assert atual.comprador_contrato == "SEGUNDO COMPRADOR EXEMPLO"
    assert atual.contrato == CCV_SEGUNDO
    assert not atual.outro_contrato and not atual.distrato
    assert not atual.distrato_sugerido and atual.casa_com_distrato
    assert antigo.comprador_contrato == "PRIMEIRO COMPRADOR EXEMPLO"
    assert antigo.contrato == CCV_PRIMEIRO
    assert antigo.outro_contrato and antigo.distrato and antigo.distrato_sugerido
    assert antigo.casa_com_distrato
    assert all(a.empresa == "BURITIS" and not a.revisao and a.marcado
               for a in achados)
    assert chave_da_casa(atual) != chave_da_casa(antigo)
    assert any("2 contrato(s) e 1 distrato(s)" in m
               and "PRIMEIRO COMPRADOR EXEMPLO (distratado)" in m
               for m in recados)


def test_sem_abrir_pdf_a_casa_segue_a_regra_de_hoje():
    achados = levantar(_api_com_distrato(), 2026, 8, EMPRESAS, log=_sem_log)
    assert len(achados) == 1
    assert achados[0].revisao and not achados[0].anexo
    assert not achados[0].casa_com_distrato


def test_casa_sem_distrato_nao_baixa_nada_na_busca():
    api = ApiDuble([receb("TB 21 QD 46 LT 18", 1, "PRIMEIRO COMPRADOR EXEMPLO")])
    achados = _levantar_com_distrato(api)
    assert len(achados) == 1 and achados[0].contrato == CCV_CS01
    assert api.baixados == []
    assert not achados[0].casa_com_distrato and achados[0].dados is None


def test_comprador_ilegivel_fica_desmarcado():
    recados = []
    api = _api_com_distrato()
    api.conteudos[URL_PRIMEIRO] = b"%PDF-escaneado"     # sem camada de texto
    achados = _levantar_com_distrato(api, log=recados.append)
    assert len(achados) == 2
    extra = achados[1]
    assert extra.outro_contrato and extra.contrato == CCV_PRIMEIRO
    assert extra.distrato is False and extra.comprador_contrato == ""
    assert extra.revisao == ""
    assert extra.marcado is False           # o arquivar recusaria
    assert achados[0].marcado
    assert any("não consegui ler o comprador de" in m
               and "Distrato fica desmarcado" in m for m in recados)


def test_contrato_que_nao_baixa_deixa_a_casa_em_revisao():
    api = _api_com_distrato()
    api.conteudos[URL_SEGUNDO] = b""
    achados = _levantar_com_distrato(api)
    assert len(achados) == 1
    assert "não consegui baixar" in achados[0].revisao
    assert CCV_SEGUNDO.strip() in achados[0].revisao
    assert not achados[0].marcado


def test_casa_com_contratos_demais_vai_para_revisao():
    anexos = {"obra-1": [
        {"id": f"c{n}", "filename": f"CONTRATO DE COMPRA E VENDA V{n} TB 21 "
         f"QD 46 LT 18 CS 01 .pdf", "extension": ".pdf",
         "downloadUrl": f"https://exemplo.invalid/c{n}"} for n in range(7)
    ] + ANEXOS_COM_DISTRATO["obra-1"][2:]}
    api = ApiDuble([receb("TB 21 QD 46 LT 18", 1, "SEGUNDO COMPRADOR EXEMPLO")],
                   anexos=anexos)
    achados = _levantar_com_distrato(api)
    assert len(achados) == 1
    assert "7 contratos e distrato na casa" in achados[0].revisao
    assert api.baixados == []


def test_esperado_da_linha_extra_e_o_comprador_do_contrato():
    atual, antigo = _levantar_com_distrato(_api_com_distrato())
    esperado = esperado_da_conferencia(antigo)
    assert esperado["comprador"] == "PRIMEIRO COMPRADOR EXEMPLO"
    assert esperado["valor_venda"] is None
    # a linha do recebimento segue conferindo o comprador e o valor de hoje
    assert esperado_da_conferencia(atual)["comprador"] == \
        "SEGUNDO COMPRADOR EXEMPLO"
    assert str(esperado_da_conferencia(atual)["valor_venda"]) == "245000.00"


def test_arquivar_grava_os_dois_e_o_distratado_com_sufixo(tmp_path):
    api = _api_com_distrato()
    achados = _levantar_com_distrato(api)
    baixados_na_busca = list(api.baixados)
    _arquivar(api, achados, tmp_path, leitor=_abrir_texto)

    assert all(a.arquivado and not a.revisao for a in achados), \
        [a.revisao for a in achados]
    pasta = achados[0].destino.parent
    nomes = sorted(p.name for p in pasta.iterdir())
    assert len(nomes) == 2
    assert sum(n.endswith("(Distratado).pdf") for n in nomes) == 1
    assert achados[1].destino.name.endswith("(Distratado).pdf")
    assert "PRIMEIRO COMPRADOR EXEMPLO" in achados[1].destino.name
    assert "SEGUNDO COMPRADOR EXEMPLO" in achados[0].destino.name
    assert achados[0].destino.read_bytes() == TEXTO_SEGUNDO.encode()
    assert achados[1].destino.read_bytes() == TEXTO_PRIMEIRO.encode()
    assert api.baixados == baixados_na_busca        # usou o que já tinha


def test_rodada_refeita_diz_ja_estava(tmp_path):
    api = _api_com_distrato()
    achados = _levantar_com_distrato(api)
    _arquivar(api, achados, tmp_path, leitor=_abrir_texto)
    _arquivar(api, achados, tmp_path, leitor=_abrir_texto)
    assert all(a.arquivado and a.ja_existia for a in achados), \
        [a.revisao for a in achados]


def test_busca_refeita_depois_de_arquivar_diz_ja_estava(tmp_path):
    api = _api_com_distrato()
    _arquivar(api, _levantar_com_distrato(api), tmp_path, leitor=_abrir_texto)
    de_novo = _levantar_com_distrato(api)
    _arquivar(api, de_novo, tmp_path, leitor=_abrir_texto)
    assert all(a.arquivado and a.ja_existia for a in de_novo), \
        [a.revisao for a in de_novo]


def test_linha_extra_sem_comprador_lido_nao_grava_com_o_nome_do_recebimento(
        tmp_path):
    """Sem o comprador lido, o nome do arquivo cairia no do recebimento — e
    o contrato de outra pessoa iria para a pasta com o nome errado."""
    api = _api_com_distrato()
    api.conteudos[URL_PRIMEIRO] = b"%PDF-escaneado"
    achados = _levantar_com_distrato(api)
    achados[0].marcado = False              # só a linha extra na rodada,
    achados[1].marcado = True               # marcada à mão na tabela
    _arquivar(api, achados, tmp_path, leitor=_abrir_texto)
    extra = achados[1]
    assert not extra.arquivado and "comprador" in extra.revisao
    pasta = tmp_path / "2026" / "AGOSTO" / "AGOSTO 2026 - BURITIS" / "CONTRATOS"
    assert not pasta.exists() or not any(pasta.iterdir())


def test_escolher_outro_contrato_a_mao_descarta_o_pdf_ja_baixado():
    """O PDF baixado na busca é do anexo escolhido ali; trocar o anexo à mão
    e gravar os bytes antigos poria um arquivo com o nome do outro."""
    achados = _levantar_com_distrato(_api_com_distrato())
    atual = achados[0]
    assert atual.dados
    aplicar_resolucao(atual, anexo=ANEXOS_COM_DISTRATO["obra-1"][0])
    assert atual.dados is None


def test_duas_versoes_do_mesmo_comprador_sem_marca_ficam_em_revisao():
    """Grupo sem escolha: a linha fica sem anexo e diz por quê; a outra linha
    da casa segue normal."""
    anexos = {"obra-1": ANEXOS_COM_DISTRATO["obra-1"] + [
        {"id": "s2", "filename": "CONTRATO DE COMPRA E VENDA TB21 QD 46 LT 18 "
         "CS 01 .pdf", "extension": ".pdf",
         "downloadUrl": "https://exemplo.invalid/s2"}]}
    api = _api_com_distrato()
    api.anexos = anexos
    api.conteudos["https://exemplo.invalid/s2"] = (
        TEXTO_SEGUNDO + "\nversao revista").encode()
    atual, antigo = _levantar_com_distrato(api)
    assert not atual.anexo and atual.dados is None
    assert "2 versões diferentes" in atual.revisao and not atual.marcado
    assert atual.comprador_contrato == "SEGUNDO COMPRADOR EXEMPLO"
    assert antigo.anexo and antigo.distrato and antigo.marcado


def _api_so_do_distratado():
    """O recebimento é do SEGUNDO, mas a casa só tem o contrato do PRIMEIRO
    e o distrato dele: o contrato de quem pagou não está na obra."""
    api = _api_com_distrato()
    api.anexos = {"obra-1": [ANEXOS_COM_DISTRATO["obra-1"][0],
                             ANEXOS_COM_DISTRATO["obra-1"][2]]}
    return api


def test_sem_o_contrato_de_quem_pagou_a_linha_do_recebimento_fica_em_revisao():
    recados = []
    achados = _levantar_com_distrato(_api_so_do_distratado(),
                                     log=recados.append)
    assert len(achados) == 2
    receb_, antigo = achados
    assert not receb_.outro_contrato and not receb_.anexo
    assert receb_.dados is None and not receb_.marcado
    assert receb_.revisao == ("não achei o contrato de SEGUNDO COMPRADOR "
                              "EXEMPLO entre os 1 contrato(s) da casa")
    assert antigo.outro_contrato and antigo.distrato and antigo.marcado
    assert antigo.comprador_contrato == "PRIMEIRO COMPRADOR EXEMPLO"
    assert any("1 contrato(s) e 1 distrato(s)" in m for m in recados)


def test_sem_o_contrato_de_quem_pagou_so_o_distratado_vai_para_a_pasta(
        tmp_path):
    api = _api_so_do_distratado()
    achados = _levantar_com_distrato(api)
    _arquivar(api, achados, tmp_path, leitor=_abrir_texto)
    receb_, antigo = achados
    assert not receb_.arquivado and "não achei o contrato" in receb_.revisao
    assert antigo.arquivado
    pasta = antigo.destino.parent
    assert [p.name for p in pasta.iterdir()] == [
        "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01 - "
        "PRIMEIRO COMPRADOR EXEMPLO (Distratado).pdf"]


def test_o_log_conta_os_distratos_lidos_nao_os_achados():
    recados = []
    api = _api_com_distrato()
    api.conteudos[URL_DISTRATO] = b""           # o distrato não baixou
    achados = _levantar_com_distrato(api, log=recados.append)
    assert not any(a.distrato for a in achados)
    assert any("2 contrato(s) e 0 distrato(s)" in m for m in recados)


# ------------------------------------------------- revisão final
def test_resumo_da_linha_extra_e_do_comprador_do_contrato():
    """A linha extra é o contrato de OUTRA pessoa: o resumo (registro e
    conferência) não pode trazer o nome nem o dinheiro de quem pagou."""
    atual, antigo = _levantar_com_distrato(_api_com_distrato())
    assert "PRIMEIRO COMPRADOR EXEMPLO" in antigo.resumo
    assert "SEGUNDO COMPRADOR EXEMPLO" not in antigo.resumo
    assert "R$" not in antigo.resumo
    assert "outro contrato da casa" in antigo.resumo
    assert "SEGUNDO COMPRADOR EXEMPLO" in atual.resumo and "R$" in atual.resumo


def test_distrato_marcado_em_casa_sem_distrato_ainda_confere_comprador_e_valor():
    """Marcar DISTRATO numa casa comum não tira o comprador da conferência
    (o contrato sairia com "(Distratado)" sem conferir de quem é)."""
    a = next(x for x in _levantar() if x.anexo)
    assert not a.comprador_contrato and a.imovel.comprador
    a.distrato = True
    esperado = esperado_da_conferencia(a)
    assert esperado["comprador"] == a.imovel.comprador
    assert esperado["valor_venda"] == a.imovel.valor_venda
    assert esperado["valor_venda"] is not None


def test_linha_do_recebimento_marcada_como_distrato_confere_o_valor():
    atual, antigo = _levantar_com_distrato(_api_com_distrato())
    atual.distrato = True
    esperado = esperado_da_conferencia(atual)
    assert esperado["comprador"] == "SEGUNDO COMPRADOR EXEMPLO"
    assert str(esperado["valor_venda"]) == "245000.00"
    assert esperado_da_conferencia(antigo)["valor_venda"] is None


def test_marca_de_distrato_feita_a_mao_volta_na_busca_seguinte():
    atual, antigo = _levantar_com_distrato(_api_com_distrato())
    marcas = {chave_da_casa(atual): True, chave_da_casa(antigo): False}
    de_novo = _levantar_com_distrato(_api_com_distrato())
    assert reaplicar_distratos(de_novo, marcas) == 2
    assert de_novo[0].distrato is True and de_novo[1].distrato is False
    # a sugestão fica como estava: é a marca que a pessoa mudou
    assert de_novo[1].distrato_sugerido is True


def test_marca_de_distrato_de_linha_que_sumiu_nao_volta():
    atual, antigo = _levantar_com_distrato(_api_com_distrato())
    marcas = {chave_da_casa(antigo): False}
    so_a_casa = _levantar_com_distrato(_api_so_do_distratado())
    receb_ = so_a_casa[0]                     # sem anexo: nada a marcar
    marcas[chave_da_casa(receb_)] = True
    assert reaplicar_distratos(so_a_casa, marcas) == 1
    assert receb_.distrato is False
    assert so_a_casa[1].distrato is False
    # casa comum, sem marca guardada, fica como veio
    comum = _levantar()
    assert reaplicar_distratos(comum, {chave_da_casa(antigo): True}) == 0
    assert not any(a.distrato for a in comum)


def test_parar_no_meio_da_casa_com_distrato_para_limpo():
    api = _api_com_distrato()
    achados = levantar(api, 2026, 8, EMPRESAS, log=_sem_log,
                       abrir_pdf=_abrir_texto,
                       cancelar=lambda: len(api.baixados) >= 1)
    assert len(api.baixados) == 1
    assert len(achados) == 1
    assert "interrompida" in achados[0].revisao
    assert not achados[0].marcado and not achados[0].anexo


# ---------------------------------------------------------------------------
# 09/11/2026: condomínio lê o contrato no lançamento da venda; anexos de mesmo
# nome só são cópia se o conteúdo provar. Tudo inventado.
# ---------------------------------------------------------------------------
OBRA_COND = {"id": "obra-c", "name": "CONDOMINIO EXEMPLO",
             "customer": {"name": "EMPRESA BURITIS LTDA"}}
CONTRATO_COND = {"id": "c1", "filename": "CONTRATO CONDOMINIO EXEMPLO CASA 15 - PESSOA EXEMPLO",
                 "extension": ".pdf", "downloadUrl": "https://exemplo.invalid/c1"}
TEXTO_COND = """CONTRATO DE PROMESSA DE COMPRA E VENDA
VENDEDORA: EMPRESA BURITIS EMPREENDIMENTOS LTDA, CNPJ 12.345.678/0001-90.
COMPRADOR: PESSOA EXEMPLO, brasileira.
Endereço: Rua XYZ-24, Quadra 9, Lote 03.
IMOVEL OBJETO DO CONTRATO (UNIDADE) a) Unidade: Casa nº 15, Tipo 02.
As partes assinam em duas vias de igual teor e forma.
"""


class ApiCondominio(ApiDuble):
    def __init__(self, anexos_venda=None, anexos_obra=None, falha=None):
        super().__init__([], anexos={"obra-c": anexos_obra or []})
        self.registros = [dict(
            receb("CONDOMINIO EXEMPLO", 15, "PESSOA EXEMPLO",
                  descricao="VENDA UNIDADE 15 - PESSOA EXEMPLO",
                  cliente="PESSOA EXEMPLO"), saleId="venda-15")]
        self.anexos_venda = [CONTRATO_COND] if anexos_venda is None else anexos_venda
        self.falha = falha
        self.vendas_lidas = []

    def listar_obras(self, log=print):
        return [OBRA_COND]

    def anexos_da_venda(self, venda_id):
        self.vendas_lidas.append(venda_id)
        if self.falha:
            raise RuntimeError(self.falha)
        return self.anexos_venda

    def detalhe_da_obra(self, work_id):
        return {"address": {"address": "Rua XYZ 24", "complement": "QD 9 LT 03"}}


def _uma_linha(api, **kw):
    [a] = levantar(api, 2026, 10, EMPRESAS, log=_sem_log, **kw)
    return a


def test_condominio_acha_o_contrato_no_lancamento_da_venda():
    api = ApiCondominio()
    a = _uma_linha(api)
    assert api.vendas_lidas == ["venda-15"]
    assert a.anexo is CONTRATO_COND
    assert a.revisao == "" and a.marcado


def test_condominio_nao_escolhe_sozinho_anexo_da_obra():
    """O contrato do condomínio é o do lançamento: a obra guarda 200 arquivos
    e não pode responder por ele."""
    da_obra = {"id": "o1", "filename": "CONTRATO DE COMPRA E VENDA UNIDADE 15",
               "extension": ".pdf", "downloadUrl": "https://exemplo.invalid/o1"}
    a = _uma_linha(ApiCondominio(anexos_venda=[], anexos_obra=[da_obra]))
    assert not a.anexo and not a.marcado
    assert "UN 15" in a.revisao
    # mas a janela de resolver mostra o da obra, para a pessoa poder decidir
    assert da_obra in a.anexos_da_obra


def test_falha_ao_ler_o_lancamento_nega_e_nao_parece_falta_de_contrato():
    a = _uma_linha(ApiCondominio(falha="A API respondeu 500"))
    assert not a.anexo and not a.marcado
    assert "não consegui ler" in a.revisao


def test_recebimento_de_condominio_sem_venda_vai_para_revisao():
    api = ApiCondominio()
    del api.registros[0]["saleId"]
    a = _uma_linha(api)
    assert not a.anexo and not a.marcado
    assert api.vendas_lidas == []


def test_casa_de_rua_nao_le_o_lancamento():
    api = ApiDuble(REGISTROS)
    api.anexos_da_venda = lambda _v: pytest.fail("casa de rua não usa o lançamento")
    linhas = levantar(api, 2026, 8, EMPRESAS, log=_sem_log)
    assert any(x.anexo for x in linhas)


def test_condominio_arquiva_o_contrato_do_lancamento(tmp_path):
    api = ApiCondominio()
    achados = levantar(api, 2026, 10, EMPRESAS, log=_sem_log)
    _arquivar(api, achados, tmp_path, leitor=lambda _b: Leitor(TEXTO_COND))
    assert achados[0].revisao == ""
    assert achados[0].arquivado
    assert achados[0].destino.name == (
        "CONTRATO DE COMPRA E VENDA CONDOMINIO EXEMPLO UN 15 - PESSOA EXEMPLO.pdf")


NOME_IGUAL = "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01 .pdf"
IGUAIS = [{"id": "i1", "filename": NOME_IGUAL, "extension": ".pdf",
           "downloadUrl": "https://exemplo.invalid/i1"},
          {"id": "i2", "filename": NOME_IGUAL, "extension": ".pdf",
           "downloadUrl": "https://exemplo.invalid/i2"}]
UMA_CASA = [receb("TB 21 QD 46 LT 18", 1, "PRIMEIRO COMPRADOR EXEMPLO")]


def _api_iguais(primeiro=b"%PDF-um", segundo=b"%PDF-dois"):
    api = ApiDuble(UMA_CASA, anexos={"obra-1": IGUAIS})
    api.conteudos = {IGUAIS[0]["downloadUrl"]: primeiro,
                     IGUAIS[1]["downloadUrl"]: segundo}
    return api


def test_mesmo_nome_e_mesmos_bytes_e_copia():
    a = _uma_linha(_api_iguais(b"%PDF-um", b"%PDF-um"))
    assert a.anexo["id"] == "i1" and a.revisao == ""


def test_mesmo_nome_e_bytes_diferentes_fica_em_revisao():
    a = _uma_linha(_api_iguais())
    assert not a.anexo and "DIFERENTES" in a.revisao


class _LeitorOCR(Leitor):
    usou_ocr = True


def test_bytes_diferentes_e_texto_inteiro_igual_e_o_mesmo_contrato():
    a = _uma_linha(_api_iguais(), abrir_pdf=lambda _b: Leitor(TEXTO))
    assert a.anexo["id"] == "i1" and a.revisao == ""


def test_texto_igual_so_nas_primeiras_paginas_nao_e_o_mesmo_contrato():
    """Assinaturas ficam no fim: o começo igual não prova o mesmo documento."""
    fins = {b"%PDF-um": "assinado por todos", b"%PDF-dois": "falta assinar"}
    a = _uma_linha(_api_iguais(),
                   abrir_pdf=lambda b: Leitor(TEXTO, resto=fins[b], total=9))
    assert not a.anexo and "DIFERENTES" in a.revisao


def test_texto_vindo_de_ocr_nao_prova_que_e_o_mesmo_contrato():
    a = _uma_linha(_api_iguais(), abrir_pdf=lambda _b: _LeitorOCR(TEXTO))
    assert not a.anexo and "DIFERENTES" in a.revisao


def test_pdf_sem_texto_nao_prova_que_e_o_mesmo_contrato():
    a = _uma_linha(_api_iguais(), abrir_pdf=lambda _b: Leitor(""))
    assert not a.anexo and "DIFERENTES" in a.revisao


def test_casa_com_distrato_junta_versoes_de_texto_inteiro_igual():
    """Mesmo comprador, dois PDFs do mesmo envelope: uma linha, sem revisão."""
    nomes = ["CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01 .pdf",
             "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT18 CS 01 .pdf",
             "DISTRATO TB 21 QD 46 LT 18 CS 01 .pdf"]
    anexos = [{"id": f"v{i}", "filename": n, "extension": ".pdf",
               "downloadUrl": f"https://exemplo.invalid/v{i}"}
              for i, n in enumerate(nomes)]
    api = ApiDuble(UMA_CASA, anexos={"obra-1": anexos})
    api.conteudos = {anexos[0]["downloadUrl"]: b"%PDF-um",
                     anexos[1]["downloadUrl"]: b"%PDF-dois",
                     anexos[2]["downloadUrl"]: b"%PDF-distrato"}
    contrato = "COMPRADOR: PRIMEIRO COMPRADOR EXEMPLO, brasileiro.\n" + TEXTO
    textos = {b"%PDF-um": contrato, b"%PDF-dois": contrato,
              b"%PDF-distrato": "Distrato de outra pessoa qualquer"}
    a = _uma_linha(api, abrir_pdf=lambda b: Leitor(textos[b]))
    assert a.anexo["id"] == "v0" and a.revisao == ""


def test_escolha_a_mao_com_nome_repetido_nao_volta_sozinha():
    """Dois anexos com o nome escolhido: voltar pelo nome poderia pegar o
    outro documento. A casa volta a perguntar."""
    a = _uma_linha(_api_iguais())
    assert reaplicar([a], {chave_da_casa(a): NOME_IGUAL}, log=_sem_log) == 0
    assert not a.anexo


# --- achados da revisão de 09/11/2026 ---------------------------------------
def test_duas_vendas_da_unidade_no_mes_vao_para_revisao():
    api = ApiCondominio()
    outra = dict(api.registros[0], saleId="venda-16", id="r2")
    api.registros.append(outra)
    a = _uma_linha(api)
    assert not a.anexo and not a.marcado
    assert "2 vendas" in a.revisao
    assert CONTRATO_COND in a.anexos_da_obra     # a janela mostra para escolher


def test_condominio_sem_comprador_vai_para_revisao():
    api = ApiCondominio()
    api.registros[0].update(description="VENDA UNIDADE 15",
                            customerName="EMPRESA BURITIS LTDA")
    a = _uma_linha(api)
    assert not a.anexo and "comprador" in a.revisao


def test_condominio_retem_o_que_nao_se_confirma_como_contrato_de_venda(tmp_path):
    api = ApiCondominio()
    achados = levantar(api, 2026, 10, EMPRESAS, log=_sem_log)
    sem_partes = TEXTO_COND.replace("VENDEDORA:", "").replace("COMPRADOR:", "")
    _arquivar(api, achados, tmp_path, leitor=lambda _b: Leitor(sem_partes))
    assert not achados[0].arquivado
    assert "contrato de venda" in achados[0].revisao


def test_guarda_escolhido_a_mao_no_condominio_ainda_grava(tmp_path):
    api = ApiCondominio()
    achados = levantar(api, 2026, 10, EMPRESAS, log=_sem_log)
    aplicar_resolucao(achados[0], anexo=CONTRATO_COND)
    sem_partes = TEXTO_COND.replace("VENDEDORA:", "").replace("COMPRADOR:", "")
    _arquivar(api, achados, tmp_path, leitor=lambda _b: Leitor(sem_partes))
    assert achados[0].arquivado


def test_copias_de_texto_mantem_a_versao_que_se_diz_completa():
    nomes = ["CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01 .pdf",
             "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01 ASSINADO .pdf",
             "DISTRATO TB 21 QD 46 LT 18 CS 01 .pdf"]
    anexos = [{"id": f"v{i}", "filename": n, "extension": ".pdf",
               "downloadUrl": f"https://exemplo.invalid/v{i}"}
              for i, n in enumerate(nomes)]
    api = ApiDuble(UMA_CASA, anexos={"obra-1": anexos})
    api.conteudos = {anexos[0]["downloadUrl"]: b"%PDF-um",
                     anexos[1]["downloadUrl"]: b"%PDF-dois",
                     anexos[2]["downloadUrl"]: b"%PDF-distrato"}
    contrato = "COMPRADOR: PRIMEIRO COMPRADOR EXEMPLO, brasileiro.\n" + TEXTO
    textos = {b"%PDF-um": contrato, b"%PDF-dois": contrato,
              b"%PDF-distrato": "Distrato de outra pessoa qualquer"}
    a = _uma_linha(api, abrir_pdf=lambda b: Leitor(textos[b]))
    assert a.anexo["id"] == "v1"


class _LeitorSemProva(Leitor):
    def impressao(self):
        return None


def test_pagina_sem_texto_ou_erro_nao_prova_o_mesmo_contrato():
    a = _uma_linha(_api_iguais(), abrir_pdf=lambda _b: _LeitorSemProva(TEXTO))
    assert not a.anexo and "DIFERENTES" in a.revisao


def test_imagens_diferentes_nao_sao_o_mesmo_contrato():
    """Assinatura em imagem sobre a página não muda o texto."""
    class ComImagem(Leitor):
        def __init__(self, texto, imagens):
            super().__init__(texto)
            self.imagens = imagens

        def impressao(self):
            return (3, self.imagens)

    fotos = {b"%PDF-um": (0, 0, 1), b"%PDF-dois": (0, 0, 2)}
    a = _uma_linha(_api_iguais(), abrir_pdf=lambda b: ComImagem(TEXTO, fotos[b]))
    assert not a.anexo and "DIFERENTES" in a.revisao


def test_comparar_copias_abre_cada_pdf_uma_vez():
    abertos = []

    def abrir(b):
        abertos.append(b)
        return Leitor(TEXTO)

    grupo = [SimpleNamespace(anexo={"filename": "A"}, dados=d)
             for d in (b"um", b"dois", b"tres")]
    assert len(_sem_copias_de_texto(grupo, abrir)) == 1
    assert sorted(abertos) == [b"dois", b"tres", b"um"]


def test_parar_interrompe_a_comparacao_de_copias():
    def abrir(_b):
        pytest.fail("com o Parar acionado não se lê PDF")

    grupo = [SimpleNamespace(anexo={"filename": "A"}, dados=d) for d in (b"um", b"dois")]
    assert _sem_copias_de_texto(grupo, abrir, cancelar=lambda: True) == grupo


def _api_de_abrir(obra, venda=()):
    return SimpleNamespace(
        anexos_de_obras=lambda ids, log=None: {ids[0]: list(obra)},
        anexos_da_venda=lambda _v: list(venda))


def test_abrir_acha_pelo_id_e_nao_pelo_nome():
    a1 = dict(IGUAIS[0], downloadUrl="fresca-1")
    a2 = dict(IGUAIS[1], downloadUrl="fresca-2")
    achado = _uma_linha(_api_iguais())
    assert anexo_atual(_api_de_abrir([a1, a2]), achado, IGUAIS[1]) == a2


def test_abrir_relê_o_anexo_do_lancamento_no_condominio():
    fresco = dict(CONTRATO_COND, downloadUrl="fresca")
    achado = _uma_linha(ApiCondominio())
    assert anexo_atual(_api_de_abrir([], [fresco]), achado, CONTRATO_COND) == fresco


def test_abrir_sem_lista_nova_fica_com_o_que_tinha():
    achado = _uma_linha(ApiCondominio())
    assert anexo_atual(_api_de_abrir([], []), achado, CONTRATO_COND) == CONTRATO_COND
