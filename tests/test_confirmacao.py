# -*- coding: utf-8 -*-
"""A janela "Confirmar o que entra" do passo 2, sem janela nenhuma.

Até 14/09/2026 ela abria ANTES da leitura dos anexos: mostrava "BOLETO sem
código de barras" para o título cujo boleto estava dentro do PDF da nota, e
não mostrava nada do que depois ia para a aba NÃO ENTRARAM. O dono quase
deixou pagamentos de fora por causa disso. Agora ela mostra a leitura real —
o que a planilha vai ter, o que a remessa vai fazer com cada linha e o que
não entrou, com o motivo —, e a regra de tudo isso mora em
`pagamentos_dia/confirmacao.py`, puro, testado aqui.

Nenhum dado real: nomes, chaves, OCs e valores são inventados. O repo é
público.
"""
import datetime as _dt
from pathlib import Path

from extratos_sicoob import sicoob_contas
from pagamentos_dia import confirmacao
from pagamentos_dia import regras_pagamento as regras
from pagamentos_dia import relatorio
from pagamentos_dia import remessa_dia
from pagamentos_dia.remessa_dia import Candidato
from relatorios import contas_mc

#: Linha digitável sintética cujos dígitos verificadores FECHAM — a mesma dos
#: testes da remessa. Valor embutido: R$ 1.150,00.
LINHA_BANCARIA = "34191.57007 00024.924375 24177.010006 9 15340000115000"
HOJE = _dt.date(2026, 9, 14)
CONTA = "EMPRESA EXEMPLO - SICOOB"


def _lanc(ident, conta="CONTA A", favorecido="Fornecedor Modelo Ltda",
          valor=100.0, **extra):
    """Um lançamento a pagar, na forma que a API do ERP devolve."""
    item = {"id": ident, "tradePayableId": f"T-{ident}", "paidTo": favorecido,
            "remainingValue": valor, "plannedDate": "2026-09-14",
            "tradePayableAccount": {"name": conta},
            "tradePayablePaymentMethod": "Pix",
            "paidToBankAccount": "PIX EMAIL fornecedor@exemplo.com",
            "documentNumber": "1234",
            "costCentreDetails": [{"workName": "OBRA MODELO"}],
            "paid": False}
    item.update(extra)
    return item


def _entradas(lancamentos, anexos=None, textos=None, regras_fornecedor=None):
    return confirmacao.Entradas(
        selecionados=list(lancamentos), anexos=anexos or {}, overviews={},
        textos=textos or {}, urls_ocr=set(), cadastro_reembolso={},
        regras_fornecedor=regras_fornecedor or {}, participantes={},
        periodo=(HOJE, HOJE))


# ==========================================================================
# O que não entrou precisa carregar o que a janela mostra
# ==========================================================================
def test_o_nao_apto_carrega_id_e_o_que_a_janela_mostra():
    """Sem o `id` a janela não sabe de que lançamento é a linha vermelha, e
    sem OC, centro de custo e observação o dono não acha o título no ERP."""
    item = _lanc("L9", valor=250.0, paidToBankAccount="",
                 documentNumber="", description="Material OC 4321")
    res = relatorio.montar_registros([item], {}, {}, {})
    assert res.contas == {}
    o, = res.omitidos
    assert o["motivo"] == regras.MOTIVO_SEM_PAGAR
    assert (o["id"], o["oc"], o["centro_custo"], o["dados"]) \
        == ("L9", "4321", "OBRA MODELO", "")
    assert "Pix sem chave" in o["obs"]
    assert not o.get("fora_do_recorte")


def test_a_conta_fora_do_recorte_se_anuncia():
    """A janela não mostra a conta ignorada — mas quem decide isso é uma
    chave, e não o começo de um texto que alguém pode reescrever."""
    item = _lanc("L7", conta="EMPRESA - APENAS LANCAMENTO")
    o, = relatorio.montar_registros([item], {}, {}, {}).omitidos
    assert o["fora_do_recorte"] is True
    assert o["id"] == "L7"


def test_a_aba_nao_entraram_continua_com_as_mesmas_colunas(tmp_path):
    """As chaves novas são da janela; o Excel lê só as de sempre."""
    item = _lanc("L9", paidToBankAccount="", documentNumber="")
    res = relatorio.montar_registros([item], {}, {}, {})
    arquivo = relatorio.gerar_excel(res, tmp_path / "p.xlsx", log=lambda *_: None)
    from openpyxl import load_workbook
    ws = load_workbook(arquivo)[relatorio.ABA_OMITIDOS]
    assert [c.value for c in ws[3]] == relatorio.HEADERS_OMITIDOS
    assert len([c for c in ws[4] if c.value not in (None, "")]) \
        == len(relatorio.HEADERS_OMITIDOS)


# ==========================================================================
# A remontagem: o que a pessoa desmarcou sai, sem baixar nada de novo
# ==========================================================================
def test_o_desmarcado_sai_com_o_motivo_e_o_resto_fica():
    e = _entradas([_lanc("L1"), _lanc("L2", favorecido="Outro Fornecedor Ltda")])
    todos = confirmacao.remontar(e)
    assert sorted(r["id"] for r in todos.contas["CONTA A"]) == ["L1", "L2"]
    assert todos.omitidos == []

    sem_l2 = confirmacao.remontar(e, {"L2"})
    assert [r["id"] for r in sem_l2.contas["CONTA A"]] == ["L1"]
    assert [(o["id"], o["motivo"]) for o in sem_l2.omitidos] \
        == [("L2", regras.MOTIVO_NAO_CONFIRMADO)]


def test_a_remontagem_usa_os_anexos_ja_lidos():
    """Confirmar não baixa nada: o boleto lido na apuração continua lido.

    Sem os textos guardados, remontar a planilha depois da janela devolveria
    exatamente o "BOLETO sem código de barras" que a janela nova veio
    desmentir."""
    url = "https://exemplo.invalid/boleto-oc-1234.pdf"
    anexo = {"filename": "boleto oc 1234", "tagName": "Boleto",
             "extension": ".pdf", "downloadUrl": url}
    item = _lanc("L1", valor=1150.0, tradePayablePaymentMethod="Boleto",
                 paidToBankAccount="")
    lido = _entradas([item], anexos={"T-L1": [anexo]},
                     textos={url: f"Linha digitável: {LINHA_BANCARIA}"})
    reg, = confirmacao.remontar(lido).contas["CONTA A"]
    assert reg["dados"] == LINHA_BANCARIA

    nao_lido = _entradas([item], anexos={"T-L1": [anexo]})
    reg, = confirmacao.remontar(nao_lido).contas["CONTA A"]
    assert reg["dados"] == "", "sem o texto guardado não há de onde tirar a linha"


# ==========================================================================
# A análise da remessa, na apuração do passo 2
# ==========================================================================
def _registro(ident, **troca):
    """Uma linha da planilha como o `montar_registros` a deixa."""
    base = {"tipo": "Boleto", "dados": LINHA_BANCARIA, "valor": 1150.00,
            "descricao": "OC 1234 - material", "favorecido": "Fornecedor Modelo Ltda",
            "status": "APTO", "conferencia": "", "obs": "", "id": ident,
            "parcial": False, "oc": "1234", "centro_custo": "OBRA MODELO"}
    base.update(troca)
    return base


class _RegistroFalso:
    """O registro de remessas, com as leituras que o `preparar` faz e as
    duas escritas que a análise NUNCA pode fazer — anotadas, para o teste
    cobrar que ficaram vazias."""

    def __init__(self, enviados=None, mudo=False):
        self.enviados, self.mudo, self.escritas = enviados or {}, mudo, []

    def maior_ordem_do_dia(self, _quando):
        if self.mudo:
            raise OSError("sem rede")
        return 0

    def envio_de(self, _codigo):
        return None

    def envio_da_referencia(self, referencia):
        nsa = self.enviados.get(referencia)
        if not nsa:
            return None
        remessa = type("R", (), {"nsa": nsa,
                                 "gerado_em": _dt.date(2026, 9, 10)})()
        return remessa, None

    def alocar_nsa(self, convenio):
        self.escritas.append(("alocar_nsa", convenio))
        return 1

    def registrar(self, *a, **k):
        self.escritas.append(("registrar", a, k))


def _mapas():
    mapa = contas_mc.Mapa(raiz=Path("."), destinos=[
        contas_mc.Destino(erp=CONTA, empresa="EXEMPLO", pasta="SICOOB",
                          banco="SICOOB"),
        contas_mc.Destino(erp="EMPRESA EXEMPLO - INTER", empresa="EXEMPLO",
                          pasta="INTER", banco="INTER"),
    ])
    empresas = [sicoob_contas.Empresa(
        nome="EXEMPLO",
        contas=[sicoob_contas.Conta(numero="12.345-6", pasta="SICOOB",
                                    banco="756", agencia="4321-0",
                                    convenio="123456")],
        cnpj="11.222.333/0001-81", razao_social="EMPRESA EXEMPLO LTDA")]
    return mapa, empresas


def test_a_analise_so_le_e_diz_o_que_a_remessa_faria():
    registro = _RegistroFalso(enviados={"L2": 7})
    contas = {CONTA: [_registro("L1"), _registro("L2"),
                      _registro("L3", parcial=True)],
              "EMPRESA EXEMPLO - INTER": [_registro("L4")]}
    analise = confirmacao.analisar_remessa(
        contas, {}, carregar_mapas=_mapas, abrir_historico=lambda: registro,
        quando=HOJE)
    assert analise.avisos == []
    assert analise.contas_conferidas is True
    assert analise.sem_remessa == {
        "EMPRESA EXEMPLO - INTER": remessa_dia.MOTIVO_FORA_SICOOB}
    assert analise.candidato(CONTA, "L1").pode
    assert analise.candidato(CONTA, "L2").ja_enviado \
        == "já saiu na remessa nº 000007 de 10/09/2026"
    assert analise.candidato(CONTA, "L3").impedimento == remessa_dia.MOTIVO_PARCIAL
    assert analise.candidato(CONTA, "NAO-EXISTE") is None
    assert registro.escritas == [], "conferir não reserva NSA nem registra nada"


def test_sem_registro_de_remessas_a_planilha_segue_com_aviso():
    def sem_sessao():
        raise RuntimeError("ninguém entrou neste computador ainda")

    analise = confirmacao.analisar_remessa(
        {CONTA: [_registro("L1")]}, {}, carregar_mapas=_mapas,
        abrir_historico=sem_sessao, quando=HOJE)
    aviso, = analise.avisos
    assert aviso.startswith(confirmacao.AVISO_SEM_REGISTRO)
    assert "ninguém entrou" in aviso
    assert analise.candidato(CONTA, "L1").pode, "o resto da análise continua"


def test_registro_que_nao_responde_tambem_vira_aviso():
    """O `preparar` levanta `RegistroMudo` quando a nuvem cala — na remessa é
    recusa, porque o "seu número" sairia repetido. Aqui não sai arquivo
    nenhum, e parar a planilha por isso seria esconder o dia inteiro."""
    analise = confirmacao.analisar_remessa(
        {CONTA: [_registro("L1")]}, {}, carregar_mapas=_mapas,
        abrir_historico=lambda: _RegistroFalso(mudo=True), quando=HOJE)
    aviso, = analise.avisos
    assert aviso.startswith(confirmacao.AVISO_SEM_REGISTRO)
    assert analise.candidato(CONTA, "L1").pode


def test_sem_cadastro_de_contas_a_analise_nao_inventa_conta_sem_remessa():
    def torto():
        raise ValueError("linha 3 do contas_mc.json sem pasta")

    analise = confirmacao.analisar_remessa(
        {CONTA: [_registro("L1")]}, {}, carregar_mapas=torto,
        abrir_historico=_RegistroFalso, quando=HOJE)
    aviso, = analise.avisos
    assert aviso.startswith(confirmacao.AVISO_SEM_CADASTRO)
    assert "linha 3" in aviso
    assert analise.contas_conferidas is False
    assert analise.sem_remessa == {}


# ==========================================================================
# SITUAÇÃO: o veredito da planilha e o da remessa, lado a lado
# ==========================================================================
def _cand(ident="L1", **mudancas):
    campos = dict(id=ident, conta_erp="CONTA A", tipo="Boleto", valor=100.0,
                  favorecido="Fornecedor Modelo Ltda", descricao="",
                  status="APTO")
    campos.update(mudancas)
    return Candidato(**campos)


def test_situacao_junta_a_planilha_e_a_remessa():
    assert confirmacao.situacao_da_linha({"status": "APTO"}, _cand()) \
        == ("APTO · vai na remessa", "ok")
    assert confirmacao.situacao_da_linha(
        {"status": "ATENÇÃO — sem anexo"}, _cand(status="ATENÇÃO — sem anexo")) \
        == ("ATENÇÃO — sem anexo · vai na remessa", "atencao")


def test_o_que_a_remessa_nao_leva_diz_o_motivo_da_propria_remessa():
    """O texto é o MOTIVO_* do `remessa_dia`, e não uma segunda redação: dois
    textos para o mesmo motivo divergem, e aí a janela e a conferência da
    remessa passam a mandar conferir coisas diferentes."""
    texto, estado = confirmacao.situacao_da_linha(
        {"status": "APTO"}, _cand(impedimento=remessa_dia.MOTIVO_PARCIAL))
    assert texto == f"APTO · remessa não leva: {remessa_dia.MOTIVO_PARCIAL}"
    assert estado == "atencao"


def test_a_conta_sem_remessa_pesa_em_toda_linha_dela():
    texto, estado = confirmacao.situacao_da_linha(
        {"status": "APTO"}, _cand(),
        sem_remessa=remessa_dia.MOTIVO_SEM_CONVENIO)
    assert texto == f"APTO · conta sem remessa: {remessa_dia.MOTIVO_SEM_CONVENIO}"
    assert estado == "atencao"


def test_o_que_ja_saiu_em_remessa_pede_olhada():
    aviso = "já saiu na remessa nº 000007 de 10/09/2026"
    texto, estado = confirmacao.situacao_da_linha(
        {"status": "APTO"}, _cand(ja_enviado=aviso))
    assert texto == f"APTO · vai na remessa · {aviso}"
    assert estado == "atencao"


def test_sem_o_cadastro_de_contas_nao_se_promete_remessa():
    texto, estado = confirmacao.situacao_da_linha(
        {"status": "APTO"}, _cand(), contas_conferidas=False)
    assert confirmacao.VAI_NA_REMESSA not in texto
    assert texto.startswith("APTO · ")
    assert estado == "ok"


def test_sem_analise_fica_so_o_veredito_da_planilha():
    assert confirmacao.situacao_da_linha({"status": "APTO"}, None) \
        == ("APTO", "ok")


def test_por_onde_e_o_dado_que_a_planilha_vai_ter():
    digitos = "".join(ch for ch in LINHA_BANCARIA if ch.isdigit())
    assert confirmacao.por_onde("Pix", "fornecedor@exemplo.com") \
        == "PIX  fornecedor@exemplo.com"
    assert confirmacao.por_onde("Boleto", digitos) == f"BOLETO  {LINHA_BANCARIA}"
    assert confirmacao.por_onde("Boleto", "") \
        == f"BOLETO  {remessa_dia.MOTIVO_SEM_CHAVE}"
    assert confirmacao.por_onde(
        "Boleto", "86860000026-5 70860161209-4 22026081001-8 61001177300-1"
    ).startswith("ARRECADAÇÃO  ")


# ==========================================================================
# As linhas da janela: por conta, ENTRAM e NÃO APTOS
# ==========================================================================
def _reg(ident, favorecido="Fornecedor Modelo Ltda", **mudancas):
    base = {"id": ident, "tipo": "Pix", "dados": "fornecedor@exemplo.com",
            "valor": 100.0, "descricao": "OBRA MODELO NF 1234",
            "favorecido": favorecido, "status": "APTO",
            "conferencia": "NF ✓", "obs": "", "oc": "1234",
            "centro_custo": "OBRA MODELO"}
    base.update(mudancas)
    return base


def _omit(ident, conta="CONTA A", motivo=regras.MOTIVO_SEM_PAGAR, **mudancas):
    base = {"conta": conta, "tipo": "Pix", "valor": 250.0,
            "descricao": "Locacao de equipamento", "motivo": motivo,
            "favorecido": "Locadora Modelo Ltda", "id": ident, "oc": "",
            "centro_custo": "OBRA MODELO", "dados": "",
            "obs": "Pix sem chave no cadastro — buscar no ERP",
            "conferencia": "(não cruzado)"}
    base.update(mudancas)
    return base


def test_cada_conta_mostra_o_que_entra_e_o_que_nao_entrou():
    resultado = relatorio.Resultado(
        contas={"CONTA B": [_reg("B1", "Zulu Materiais"),
                            _reg("B2", "Socio Ficticio"),
                            _reg("B3", "Alfa Materiais")],
                "CONTA A": [_reg("A1")]},
        omitidos=[_omit("A9"), _omit("B9", conta="CONTA B"),
                  _omit("X1", conta="EMPRESA - APENAS LANCAMENTO",
                        fora_do_recorte=True)])
    lancamentos = [_lanc("A1", plannedDate="2026-09-15")]
    grupos = confirmacao.grupos_da_confirmacao(
        resultado, None, lancamentos, destacar=["SOCIO FICTICIO"])

    assert [g.conta for g in grupos] == ["CONTA A", "CONTA B"], \
        "a conta ignorada não aparece: não é pendência a corrigir no ERP"
    assert [(ln.favorecido, ln.olhar) for ln in grupos[1].entram] == [
        ("Socio Ficticio", True), ("Alfa Materiais", False),
        ("Zulu Materiais", False)]
    entra, = grupos[0].entram
    assert entra.marcavel and entra.vencimento == _dt.date(2026, 9, 15)
    assert (entra.oc, entra.centro_custo) == ("1234", "OBRA MODELO")
    nao, = grupos[0].nao_aptos
    assert (nao.id, nao.situacao, nao.estado) \
        == ("A9", regras.MOTIVO_SEM_PAGAR, "erro")
    assert not nao.marcavel, "não apto não se força: corrige-se no ERP"
    assert nao.obs == "Pix sem chave no cadastro — buscar no ERP"


def test_a_linha_que_entra_traz_a_situacao_da_remessa():
    resultado = relatorio.Resultado(
        {CONTA: [_reg("L1", tipo="Boleto", dados=LINHA_BANCARIA)]}, [])
    candidato = _cand("L1", conta_erp=CONTA,
                      impedimento=remessa_dia.MOTIVO_PARCIAL)
    analise = confirmacao.AnaliseRemessa(preparado={CONTA: [candidato]},
                                         sem_remessa={})
    grupo, = confirmacao.grupos_da_confirmacao(resultado, analise, [])
    linha, = grupo.entram
    assert linha.situacao == f"APTO · remessa não leva: {remessa_dia.MOTIVO_PARCIAL}"
    assert linha.estado == "atencao"
    assert linha.candidato is candidato
    assert linha.por_onde == f"BOLETO  {LINHA_BANCARIA}"


def test_a_conta_sem_remessa_aparece_no_grupo():
    resultado = relatorio.Resultado({CONTA: [_reg("L1")]}, [])
    analise = confirmacao.AnaliseRemessa(
        preparado={CONTA: [_cand("L1", conta_erp=CONTA)]},
        sem_remessa={CONTA: remessa_dia.MOTIVO_SEM_CONVENIO})
    grupo, = confirmacao.grupos_da_confirmacao(resultado, analise, [])
    assert grupo.sem_remessa == remessa_dia.MOTIVO_SEM_CONVENIO
    assert grupo.entram[0].estado == "atencao"


def test_ja_pago_nao_e_pergunta():
    """Desmarcar um já pago não faria nada — o `montar_registros` não omite
    linha paga —, e marca que não tem efeito é mentira na tela."""
    resultado = relatorio.Resultado(
        {"CONTA A": [_reg("A1"), _reg("A2", status="JÁ PAGO em 13/09/2026")]},
        [])
    grupo, = confirmacao.grupos_da_confirmacao(
        resultado, None, [_lanc("A1"), _lanc("A2", paid=True)])
    assert [ln.id for ln in grupo.entram] == ["A1"]


#: Cadastro de mentira, no formato de `carregar_fornecedores`.
_MARCADA = {"CONCESSIONARIA LUZ": {"so_marcador": True}}


def test_o_marcador_de_recorrencia_nao_ocupa_a_janela():
    """A queixa de 20/08/2026: três linhas de R$ 1,00 todo dia, sabidas.

    `so_marcador` é decisão tomada no cadastro; repeti-la em vermelho todo
    dia ensina a pular os vermelhos — e é neles que mora o pagamento que
    ficou de fora. A marca é sobre o R$ 1,00 DESTE fornecedor: a conta de
    verdade dele que não entrou aparece, e o R$ 1,00 de outro também."""
    marcador = _omit("M1", motivo=regras.MOTIVO_SIMBOLICO, valor=1.0,
                     favorecido="CONCESSIONARIA LUZ S/A")
    outro = _omit("M2", motivo=regras.MOTIVO_SIMBOLICO, valor=1.0,
                  favorecido="Fornecedor Modelo Ltda")
    de_verdade = _omit("M3", valor=87.50, favorecido="CONCESSIONARIA LUZ S/A")
    resultado = relatorio.Resultado({}, [marcador, outro, de_verdade])

    grupo, = confirmacao.grupos_da_confirmacao(resultado, None, [],
                                               fornecedores=_MARCADA)
    assert [ln.id for ln in grupo.nao_aptos] == ["M2", "M3"]
    grupo, = confirmacao.grupos_da_confirmacao(resultado, None, [])
    assert [ln.id for ln in grupo.nao_aptos] == ["M1", "M2", "M3"], \
        "sem cadastro, nada é escondido"


def test_rodape_e_o_que_volta_saem_das_mesmas_marcas():
    resultado = relatorio.Resultado(
        {"CONTA A": [_reg("A1", valor=100.0), _reg("A2", valor=250.5),
                     _reg("A3", valor=10.0)]},
        [_omit("A8"), _omit("A9")])
    grupos = confirmacao.grupos_da_confirmacao(resultado, None, [])
    por_id = {ln.id: ln for ln in grupos[0].entram}
    marcas = [(por_id["A1"], True), (por_id["A2"], False),
              (por_id["A3"], True)]
    assert confirmacao.resumo(grupos, marcas) == (2, 110.0, 1, 2)
    assert confirmacao.nao_confirmados(marcas) == {"A2"}
    assert confirmacao.nao_confirmados(
        [(ln, True) for ln, _m in marcas]) == set()


def test_a_frase_do_rodape_conta_os_nao_aptos():
    assert confirmacao.frase_do_rodape(2, 110.0, 1, 2) \
        == "2 marcados  ·  R$ 110,00  ·  1 fica de fora  ·  2 não aptos"
    assert confirmacao.frase_do_rodape(1, 10.0, 0, 1) \
        == "1 marcado  ·  R$ 10,00  ·  1 não apto"
    assert confirmacao.frase_do_rodape(3, 30.0, 0, 0) \
        == "3 marcados  ·  R$ 30,00"


def test_a_cor_da_linha_na_tela():
    """Desmarcado é vermelho seja qual for o dado; não apto é sempre vermelho;
    a linha marcada fica com o próprio estado — e a que entra SEM dado de
    pagamento é âmbar, não vermelha: ela entra na planilha, quem não a leva é
    a remessa."""
    resultado = relatorio.Resultado(
        {"CONTA A": [_reg("A1"),
                     _reg("A2", dados="", status="ATENÇÃO — sem dados de pgto")]},
        [_omit("A9")])
    grupo, = confirmacao.grupos_da_confirmacao(resultado, None, [])
    por_id = {ln.id: ln for ln in grupo.entram + grupo.nao_aptos}
    assert confirmacao.estado_na_tela(por_id["A1"], True) == "ok"
    assert confirmacao.estado_na_tela(por_id["A2"], True) == "atencao"
    assert confirmacao.estado_na_tela(por_id["A1"], False) == "erro"
    assert confirmacao.estado_na_tela(por_id["A9"], True) == "erro"
