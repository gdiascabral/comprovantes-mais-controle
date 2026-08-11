# -*- coding: utf-8 -*-
"""O pipeline inteiro, com uma API dublê — nenhum teste toca o ERP.

O cenário abaixo é o de julho/2026 em miniatura, com nomes trocados: quatro
casas financiadas, duas delas numa obra de PESSOA FÍSICA, que não tem pasta de
fechamento. O resultado certo é 2 arquiváveis e 2 em revisão.
"""
from pathlib import Path

from contratos.pipeline import Achado, arquivar, levantar, preparar_destino


class _Empresa:
    def __init__(self, nome, clientes):
        self.nome, self.clientes_erp = nome, clientes


EMPRESAS = [_Empresa("BURITIS", ["EMPRESA BURITIS LTDA"])]

OBRAS = [
    {"id": "obra-1", "name": "TB 21 QD 46 LT 18",
     "customer": {"name": "EMPRESA BURITIS LTDA"}},
    {"id": "obra-2", "name": "FERROVIARIOS QD 01 LT 12",
     "customer": {"name": "PESSOA FISICA QUALQUER"}},
]

ANEXOS = {
    "obra-1": [
        {"id": "x1", "filename": "CONTRATO TB 21 QD 46 LT 18 CS 01 .pdf",
         "extension": ".pdf", "downloadUrl": "https://exemplo.invalid/1"},
        {"id": "x2", "filename": "CONTRATO TB 21 QD 46 LT 18 CS 02 .pdf",
         "extension": ".pdf", "downloadUrl": "https://exemplo.invalid/2"},
        {"id": "x3", "filename": "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01 .pdf",
         "extension": ".pdf", "downloadUrl": "https://exemplo.invalid/3"},
    ],
    "obra-2": [
        {"id": "y1", "filename": "CONTRATO FERROVIARIOS QD 01 LT 12 CS 01 .pdf",
         "extension": ".pdf", "downloadUrl": "https://exemplo.invalid/4"},
        {"id": "y2", "filename": "CONTRATO FERROVIARIOS QD 01 LT 12 CS 02 .pdf",
         "extension": ".pdf", "downloadUrl": "https://exemplo.invalid/5"},
    ],
}

TEXTO = """CONTRATO DE FINANCIAMENTO
Imovel na Rua TB 21, QD 46 LT 18, CASA 01, bairro exemplo.
Comprador: PRIMEIRO COMPRADOR EXEMPLO.
Valor do financiamento: R$ 245.000,00.
As partes assinam em duas vias de igual teor e forma.
"""


def receb(obra, casa, comprador, condicao="1ª FINANCIAMENTO", valor=245000.0):
    return {"workName": obra, "description": f"VENDA CASA {casa:02d} - {comprador}",
            "readjustmentType": condicao, "nature": "Venda",
            "dateOfReceipt": "2026-07-30", "sumOfReceivedValues": valor,
            "id": f"{obra}-{casa}"}


class ApiDuble:
    """Só o que o pipeline usa. Registra o que foi pedido."""

    def __init__(self, registros, texto=TEXTO):
        self.registros = registros
        self.texto = texto
        self.baixados = []

    def listar_recebimentos(self, inicio, fim, log=print):
        return self.registros

    def listar_obras(self, log=print):
        return OBRAS

    def anexos_de_obras(self, ids, log=print, cancelar=None):
        return {i: ANEXOS.get(i, []) for i in ids}

    def detalhe_da_obra(self, work_id):
        return {"address": {"address": "Rua TB 21", "complement": "QD 46 LT 18"}}

    def baixar_anexo(self, url):
        self.baixados.append(url)
        return b"%PDF-falso"


REGISTROS = [
    receb("TB 21 QD 46 LT 18", 1, "PRIMEIRO COMPRADOR EXEMPLO"),
    receb("TB 21 QD 46 LT 18", 2, "SEGUNDO COMPRADOR EXEMPLO"),
    receb("FERROVIARIOS QD 01 LT 12", 1, "TERCEIRO COMPRADOR EXEMPLO"),
    receb("FERROVIARIOS QD 01 LT 12", 2, "QUARTO COMPRADOR EXEMPLO"),
]


def test_o_mes_devolve_quatro_casas_duas_em_revisao():
    """O critério do plano: 4 financiamentos, 2 sem destino por serem de obra
    de pessoa física — que não tem pasta de fechamento e nunca terá."""
    achados = levantar(ApiDuble(REGISTROS), 2026, 7, EMPRESAS, log=lambda m: None)
    assert len(achados) == 4
    com_destino = [a for a in achados if not a.revisao]
    em_revisao = [a for a in achados if a.revisao]
    assert len(com_destino) == 2
    assert len(em_revisao) == 2
    assert all("não está mapeado" in a.revisao for a in em_revisao)
    assert {a.empresa for a in com_destino} == {"BURITIS"}


def test_cada_casa_pega_o_seu_contrato():
    achados = levantar(ApiDuble(REGISTROS), 2026, 7, EMPRESAS, log=lambda m: None)
    por_casa = {a.imovel.unidade: a.contrato for a in achados if a.empresa}
    assert "CS 01" in por_casa[1] and "COMPRA E VENDA" not in por_casa[1]
    assert "CS 02" in por_casa[2]


def test_mes_vazio_e_resposta_e_nao_falha():
    assert levantar(ApiDuble([]), 2026, 7, EMPRESAS, log=lambda m: None) == []


def test_mes_sem_financiamento_nenhum():
    registros = [receb("TB 21 QD 46 LT 18", 1, "X", condicao="1ª Sinal")]
    assert levantar(ApiDuble(registros), 2026, 7, EMPRESAS,
                    log=lambda m: None) == []


def test_obra_que_nao_existe_no_cadastro_vai_para_revisao():
    registros = [receb("OBRA QUE NAO EXISTE", 1, "X")]
    achados = levantar(ApiDuble(registros), 2026, 7, EMPRESAS, log=lambda m: None)
    assert len(achados) == 1 and "não achei a obra" in achados[0].revisao


# ------------------------------------------------------------- arquivamento
def _nome_mes(m):
    return "JULHO"


def _pasta_empresa(a, m, e):
    return f"JULHO {a} - {e}"


def test_arquiva_o_que_confere_e_retem_o_que_diverge(tmp_path):
    api = ApiDuble(REGISTROS)
    achados = levantar(api, 2026, 7, EMPRESAS, log=lambda m: None)
    arquivar(api, achados, tmp_path, 2026, 7, _nome_mes, _pasta_empresa,
             texto_do_pdf=lambda b: TEXTO, log=lambda m: None)

    arquivados = [a for a in achados if a.arquivado]
    # A casa 01 confere; a 02 diverge (o texto diz CASA 01 e outro comprador).
    assert len(arquivados) == 1
    assert arquivados[0].imovel.unidade == 1
    assert arquivados[0].destino.is_file()
    assert arquivados[0].destino.stat().st_size > 0
    assert "CONTRATO TB 21 QD 46 LT 18 CS 01" in arquivados[0].destino.name

    retido = [a for a in achados if a.anexo and not a.arquivado and a.empresa]
    assert retido and "diverge em" in retido[0].revisao


def test_texto_ilegivel_nao_retem(tmp_path):
    """`?` não segura o arquivo: contrato ilegível não é contrato errado."""
    api = ApiDuble(REGISTROS)
    achados = levantar(api, 2026, 7, EMPRESAS, log=lambda m: None)
    arquivar(api, achados, tmp_path, 2026, 7, _nome_mes, _pasta_empresa,
             texto_do_pdf=lambda b: "", log=lambda m: None)
    assert len([a for a in achados if a.arquivado]) == 2


def test_download_vazio_nao_derruba_os_outros(tmp_path):
    api = ApiDuble(REGISTROS)
    api.baixar_anexo = lambda url: None
    achados = levantar(api, 2026, 7, EMPRESAS, log=lambda m: None)
    arquivar(api, achados, tmp_path, 2026, 7, _nome_mes, _pasta_empresa,
             texto_do_pdf=lambda b: TEXTO, log=lambda m: None)
    assert not any(a.arquivado for a in achados)
    assert all("download" in a.revisao for a in achados if a.anexo and a.empresa)


def test_caminho_longo_demais_e_recusado_antes_de_gravar(tmp_path):
    achado = Achado(imovel=levantar(ApiDuble(REGISTROS), 2026, 7, EMPRESAS,
                                    log=lambda m: None)[0].imovel)
    achado.empresa = "BURITIS"
    achado.anexo = {"extension": ".pdf"}
    fundo = Path("C:/" + "x" * 240)
    motivo = preparar_destino(achado, fundo, 2026, 7, _nome_mes, _pasta_empresa)
    assert "260" in motivo
    assert achado.destino is None
