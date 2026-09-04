# -*- coding: utf-8 -*-
"""A regra do passo 3: quem pode sair na remessa, e como o arquivo é montado.

Sem tela. O que se testa aqui é dinheiro saindo para a pessoa certa, na conta
certa, uma vez só.
"""
import datetime as _dt
from pathlib import Path

import pytest


from pagamentos_dia import ocr_boleto
from pagamentos_dia import remessa_dia
from relatorios import contas_mc
from extratos_sicoob import sicoob_contas

HOJE = _dt.date(2026, 8, 13)
LINHA_BANCARIA = "34191.57007 00024.924375 24177.010006 9 15340000115000"
LINHA_ARRECADACAO = "86860000026-5 70860161209-4 22026081001-8 61001177300-1"
CONTA = "EMPRESA EXEMPLO - SICOOB"
# CNPJ e CPF sintéticos, com DV calculado — o repositório é público.
CNPJ_OK = "11222333000181"
CPF_OK = "52998224725"
#: Onze dígitos que NÃO fecham o DV — a forma do CPF de preenchimento que fez o
#: Sicoob devolver a remessa de 20/08/2026. É o CPF_OK com o último dígito
#: trocado: tem o tamanho certo, e era só o tamanho que alguém conferia.
CPF_NAO_FECHA = "52998224726"
#: CPF que TAMBÉM tem forma de celular (DDD 11, 9 na 3ª casa, DV fechando).
#: É o único caso que continua sem resposta depois das duas provas.
CHAVE_AMBIGUA = "11900000083"


# ------------------------------------------------------- código de barras
def test_linha_bancaria_vira_44_digitos():
    barras = ocr_boleto.codigo_de_barras(LINHA_BANCARIA)
    assert len(barras) == 44 and barras.isdigit()
    assert barras[:3] == "341"            # o banco sobrevive à conversão
    assert barras[9:19] == "0000115000"   # e o valor, em centavos


def test_linha_de_arrecadacao_vira_44_digitos():
    barras = ocr_boleto.codigo_de_barras(LINHA_ARRECADACAO)
    assert len(barras) == 44 and barras.startswith("8686")


def test_o_dv_geral_do_codigo_de_barras_fecha():
    """Prova independente: o DV do barcode confere com os outros 43 dígitos."""
    barras = ocr_boleto.codigo_de_barras(LINHA_BANCARIA)
    sem_dv = barras[:4] + barras[5:]
    assert str(ocr_boleto._mod11_geral(sem_dv)) == barras[4]


def test_linha_com_digito_trocado_nao_converte():
    """OCR troca 8 por B. Um dígito a mais no lugar errado paga outra pessoa."""
    d = list(ocr_boleto.digitos(LINHA_BANCARIA))
    d[7] = "0" if d[7] != "0" else "1"
    assert ocr_boleto.codigo_de_barras("".join(d)) == ""


@pytest.mark.parametrize("entrada", ["", "12345", "abc", None])
def test_lixo_nao_converte(entrada):
    assert ocr_boleto.codigo_de_barras(entrada) == ""


# ------------------------------------------------------------- candidatos
def registro(**troca):
    base = {"tipo": "Boleto", "dados": LINHA_BANCARIA, "valor": 1150.00,
            "descricao": "OC 5825 - material", "favorecido": "FORNECEDOR SA",
            "status": "APTO", "conferencia": "", "obs": "",
            "id": "id-erp-1", "parcial": False}
    base.update(troca)
    return base


def preparar(*registros, quando=HOJE):
    return remessa_dia.preparar({CONTA: list(registros)}, quando=quando)[CONTA]


def test_apto_nasce_marcado():
    c, = preparar(registro())
    assert c.marcado and c.pode
    assert c.codigo_barras == ocr_boleto.codigo_de_barras(LINHA_BANCARIA)


def test_atencao_nasce_desmarcado():
    """O normal segue sozinho; o duvidoso exige um clique."""
    c, = preparar(registro(status="ATENÇÃO — sem anexo"))
    assert c.pode and not c.marcado


def test_o_autorizado_tambem_nasce_marcado():
    """"APTO (autorizado)" é APTO como qualquer outro."""
    c, = preparar(registro(status="APTO (autorizado)"))
    assert c.marcado


def test_o_reembolso_e_o_apto_que_nasce_desmarcado():
    """"APTO* (reembolso)" também é APTO, e mesmo assim pede um clique.

    O asterisco não é enfeite: é a única linha em que o app TROCA o favorecido
    por conta própria, e quem confere o total não tem como perceber a troca.
    Ver `test_reembolso_resolvido_nasce_desmarcado` para a linha completa.
    """
    c, = preparar(registro(status="APTO* (reembolso)", reembolso=True,
                           tipo="Pix", dados="PIX CPF 111.444.777-35",
                           reembolso_nome="PESSOA DE EXEMPLO",
                           reembolso_documento="11144477735"))
    assert c.apto and c.pode and not c.marcado


# ------------------------------------------- as travas contra pagar 2 vezes
def test_reembolso_do_anexo_e_impedido():
    """O aviso "PAGAR PARA" manda o dinheiro para quem NÃO é o favorecido.

    O segmento B carrega UM par nome/documento, e os dois lados vinham de
    origens diferentes: o documento do FORNECEDOR (casado pelo `paidTo` no
    cadastro de Contatos) com a chave Pix DA PESSOA. Os campos passavam a
    contradizer a Informação 12, e o validador não vê. A observação
    equivalente ("PAGAR À MÃO") já era impedimento; o anexo não era, e ainda
    nascia marcado, porque a planilha o classifica como APTO.
    """
    c, = preparar(registro(tipo="Pix", dados="529.982.247-25",
                           status="APTO* (reembolso)", reembolso=True))
    assert not c.pode
    assert c.impedimento == remessa_dia.MOTIVO_REEMBOLSO


def test_valor_que_o_boleto_contradiz_e_impedido():
    """Na planilha é alarme — a linha existe para alguém abrir e olhar.

    Aqui viraria dinheiro saindo pelo valor do LANÇAMENTO, que é justamente
    o lado que o boleto contradiz.
    """
    c, = preparar(registro(status="ATENÇÃO — valor do boleto diverge",
                           valor_diverge=True))
    assert not c.pode
    assert c.impedimento == remessa_dia.MOTIVO_VALOR_DIVERGE


class _HistoricoFalso:
    """Só o que o `preparar` pergunta: as duas buscas de "já saiu?"."""

    def __init__(self, por_barras=None, por_referencia=None):
        self._barras = por_barras or {}
        self._ref = por_referencia or {}

    def _achado(self, nsa):
        remessa = type("R", (), {"nsa": nsa, "gerado_em": None})()
        return (remessa, object())

    def envio_de(self, codigo):
        return self._achado(self._barras[codigo]) if codigo in self._barras else None

    def envio_da_referencia(self, referencia):
        return self._achado(self._ref[referencia]) if referencia in self._ref else None


def test_boleto_que_ja_saiu_em_outra_remessa_volta_avisado_e_desmarcado():
    """A trava do "seu número" só pegava repetição no MESMO dia.

    Ele começa com a data (`260813-0001-…`), então refazer o dia seguinte com
    o título ainda aberto — porque o retorno do banco não foi lido — mandava o
    mesmo boleto de novo, com NSA novo e validador limpo.

    Descobrir isso virou IMPEDIMENTO, e em 20/08/2026 virou AVISO: o envio
    anterior também falha de verdade, e aí este pagamento precisa ir de novo.
    A linha volta a ter caixa; o que sobrou da trava é ela nascer vazia.
    """
    barras = ocr_boleto.codigo_de_barras(LINHA_BANCARIA)
    hist = _HistoricoFalso(por_barras={barras: 31})
    c, = remessa_dia.preparar({CONTA: [registro()]}, quando=HOJE,
                              historico=hist)[CONTA]
    assert c.pode and not c.impedimento
    assert "000031" in c.ja_enviado
    assert not c.marcado


def test_pix_que_ja_saiu_volta_avisado_pela_referencia():
    """Pix não tem código de barras; quem responde é o id do lançamento."""
    hist = _HistoricoFalso(por_referencia={"id-erp-1": 7})
    c, = remessa_dia.preparar(
        {CONTA: [registro(tipo="Pix", dados="11.222.333/0001-81")]},
        quando=HOJE, historico=hist)[CONTA]
    assert c.pode and not c.impedimento
    assert "000007" in c.ja_enviado
    assert not c.marcado


def test_o_reenvio_recebe_seu_numero_novo():
    """É por ele que o retorno do banco casa com o REENVIO, e não com o velho.

    Cai do código que já existia — o `seu_numero` só era atribuído a quem não
    tinha impedimento —, mas é a consequência que faz o reenvio ser rastreável
    em vez de ambíguo, e por isso está escrita aqui.
    """
    barras = ocr_boleto.codigo_de_barras(LINHA_BANCARIA)
    hist = _HistoricoFalso(por_barras={barras: 31})
    c, = remessa_dia.preparar({CONTA: [registro()]}, quando=HOJE,
                              historico=hist)[CONTA]
    assert c.seu_numero and c.seu_numero.startswith(HOJE.strftime("%y%m%d"))


def test_linha_sem_envio_anterior_nao_ganha_aviso():
    """O aviso é sobre o histórico, não sobre a linha: sem envio, vazio."""
    c, = remessa_dia.preparar({CONTA: [registro()]}, quando=HOJE,
                              historico=_HistoricoFalso())[CONTA]
    assert c.ja_enviado == "" and c.marcado


class _RemessaFalsa:
    def __init__(self, *seus):
        self.itens = [type("I", (), {"seu_numero": s})() for s in seus]


class _RegistroFalso:
    """O bastante de um histórico para a numeração do dia."""

    def __init__(self, *remessas, explode=False):
        self._remessas = list(remessas)
        self._explode = explode

    def remessas(self, **_kw):
        if self._explode:
            raise RuntimeError("registro fora do ar")
        return self._remessas

    def envio_de(self, _c):
        return None

    def envio_da_referencia(self, _r):
        return None


def test_a_ordem_do_dia_continua_de_onde_parou():
    """Duas remessas no mesmo dia não podem repetir "seu número".

    Em 20/08/2026 a segunda remessa do dia repetiu QUATRO números da primeira
    (260820-0007 a 260820-0010). O "seu número" é o que o banco devolve no
    retorno para casar cada pagamento; repetido, casa com o errado — e foi por
    isso que o espelho local recusou aquela remessa.
    """
    hist = _RegistroFalso(_RemessaFalsa(f"{HOJE:%y%m%d}-0001",
                                        f"{HOJE:%y%m%d}-0010-OC55"))
    assert remessa_dia.sequencia_ja_usada(hist, HOJE) == 10
    c, = remessa_dia.preparar({CONTA: [registro()]}, quando=HOJE,
                              historico=hist)[CONTA]
    assert c.seu_numero.startswith(f"{HOJE:%y%m%d}-0011")


def test_a_ordem_do_dia_continua_de_onde_parou_contra_a_nuvem():
    """A MESMA garantia, na forma que o registro de verdade devolve.

    `nuvem.registro.Registro.remessas()` (que o `Espelhado` repassa, e é ele
    que o app usa desde que o NSA saiu do arquivo local) devolve DICTS com a
    chave `remessa_item` — não objetos com `.itens`. Contra ela a conferência
    devolvia 0 SEMPRE, calada, e a segunda remessa do dia recomeçava o "seu
    número" em 0001, repetindo os da primeira: exatamente o defeito de
    20/08/2026 que o teste de cima existe para impedir.
    """
    hist = _RegistroFalso({"nsa": 3, "remessa_item": [
        {"seu_numero": f"{HOJE:%y%m%d}-0001"},
        {"seu_numero": f"{HOJE:%y%m%d}-0015-OC55"},
    ]})
    assert remessa_dia.sequencia_ja_usada(hist, HOJE) == 15
    c, = remessa_dia.preparar({CONTA: [registro()]}, quando=HOJE,
                              historico=hist)[CONTA]
    assert c.seu_numero.startswith(f"{HOJE:%y%m%d}-0016")


def test_numero_de_outro_dia_nao_conta():
    """A ordem é do DIA: ontem não empurra a numeração de hoje."""
    hist = _RegistroFalso(_RemessaFalsa("260819-0042"))
    assert remessa_dia.sequencia_ja_usada(hist, HOJE) == 0


def test_registro_fora_do_ar_nao_derruba_a_remessa():
    """Perder a remessa por causa da conferência seria pior que renumerar."""
    assert remessa_dia.sequencia_ja_usada(_RegistroFalso(explode=True), HOJE) == 0


def test_sem_historico_a_numeracao_e_a_de_antes():
    assert remessa_dia.sequencia_ja_usada(None, HOJE) == 0


def test_sem_historico_a_regra_continua_a_mesma():
    """`historico` é opcional: os testes de regra chamam `preparar` sem ele."""
    c, = preparar(registro())
    assert c.pode and c.marcado


def test_ja_pago_nao_e_candidato():
    c, = preparar(registro(status="JÁ PAGO em 12/08/2026"))
    assert not c.pode and c.impedimento == remessa_dia.MOTIVO_JA_PAGO


def test_pagar_a_mao_nao_entra_nem_desmarcado():
    """A observação manda pagar outra pessoa; na remessa ninguém lê."""
    c, = preparar(registro(obs="PAGAR À MÃO — a observação manda pagar outra pessoa."))
    assert not c.pode and c.impedimento == remessa_dia.MOTIVO_MAO
    assert not c.marcado


def test_pagamento_parcial_nao_vai_como_boleto():
    c, = preparar(registro(parcial=True))
    assert c.impedimento == remessa_dia.MOTIVO_PARCIAL


def test_linha_digitavel_quebrada_nao_entra():
    c, = preparar(registro(dados="34191570070002492437524177010006915340000115001"))
    assert c.impedimento == remessa_dia.MOTIVO_LINHA


def test_sem_dados_de_pagamento_nao_entra():
    c, = preparar(registro(dados=""))
    assert c.impedimento == remessa_dia.MOTIVO_SEM_CHAVE


def test_pix_por_cnpj_entra():
    c, = preparar(registro(tipo="Pix", dados="PIX CNPJ 11.222.333/0001-81"))
    assert c.pode and c.documento_favorecido == "11222333000181"
    assert c.forma_iniciacao == "03"


def test_pix_por_cpf_entra():
    c, = preparar(registro(tipo="Pix", dados="PIX CPF 529.982.247-25"))
    assert c.pode and c.documento_favorecido == "52998224725"


def test_pix_por_celular_sem_cadastro_fica_de_fora():
    """O segmento B exige o CPF/CNPJ, e a chave de celular não o carrega."""
    c, = preparar(registro(tipo="Pix", dados="PIX CELULAR (62) 99999-1234"))
    assert c.impedimento == remessa_dia.MOTIVO_SEM_DOCUMENTO


def test_pix_por_cpf_cru_agora_e_reconhecido_sem_cadastro():
    """As duas provas (DV do CPF + forma de celular) resolvem 93% dos CPFs.

    `52998224725` fecha o DV e não tem forma de celular — o DDD 52 não existe.
    """
    c, = preparar(registro(tipo="Pix", dados=CPF_OK))
    assert c.pode and c.forma_iniciacao == "03"


def test_pix_com_onze_digitos_realmente_ambiguos_fica_de_fora():
    """CPF que TAMBÉM tem forma de celular: DDD válido, 9 na 3ª casa, DV fecha.

    É o que sobra depois das duas provas — ~6,6% dos CPFs. Aqui escolher seria
    escolher para quem o dinheiro vai.
    """
    c, = preparar(registro(tipo="Pix", dados=CHAVE_AMBIGUA))
    assert c.impedimento == remessa_dia.MOTIVO_CHAVE_AMBIGUA


# ------------------------------------- o cadastro de Contatos resolve o Pix
CADASTRO = {"FORNECEDOR SA": CNPJ_OK}


def test_cadastro_libera_pix_por_celular():
    """O que faltava era o documento, não a chave — e ele vem do cadastro."""
    preparado = remessa_dia.preparar(
        {CONTA: [registro(tipo="Pix", dados="PIX CELULAR 62999991234")]},
        participantes=CADASTRO, quando=HOJE)
    c, = preparado[CONTA]
    assert c.pode
    assert c.documento_favorecido == CNPJ_OK      # do cadastro
    assert c.chave == "PIX CELULAR 62999991234"   # a chave segue sendo a chave
    assert c.forma_iniciacao == "01"


def test_cadastro_com_documento_que_nao_fecha_nao_libera_o_pix():
    """Estar no cadastro não é o mesmo que ter documento que o banco aceite.

    Foi assim que a remessa de 20/08/2026 voltou inteira: o favorecido ESTAVA
    no cadastro de Contatos, com um CPF de preenchimento. O documento vindo do
    cadastro entrava sem conferência nenhuma — o `documento_valido`, que é quem
    checa o DV, só era aplicado à chave Pix, o caminho de trás. E o
    `_impedimento` sabe perguntar se o documento EXISTE, não se ele fecha.

    O certo é cair na conferência como se não houvesse cadastro: sem documento
    de verdade, não há segmento B que o banco aceite.
    """
    preparado = remessa_dia.preparar(
        {CONTA: [registro(tipo="Pix", dados="PIX CELULAR 62999991234")]},
        participantes={"FORNECEDOR SA": CPF_NAO_FECHA}, quando=HOJE)
    c, = preparado[CONTA]
    assert c.impedimento == remessa_dia.MOTIVO_SEM_DOCUMENTO
    assert not c.documento_favorecido


def test_boleto_nao_leva_cedente_com_documento_que_nao_fecha():
    """No J-52 o documento inválido não impede o pagamento — mas não entra.

    O boleto se paga pelo código de barras, e o comentário do `preparar` já
    aceitava cedente em branco. Branco é honesto; um documento que não fecha
    aponta para ninguém e ainda arrisca a recusa do registro.
    """
    preparado = remessa_dia.preparar(
        {CONTA: [registro()]},
        participantes={"FORNECEDOR SA": CPF_NAO_FECHA}, quando=HOJE)
    c, = preparado[CONTA]
    assert c.pode                       # o boleto continua saindo
    assert not c.documento_favorecido   # sem cedente inventado


def test_cadastro_libera_pix_por_email_e_aleatoria():
    for dados, forma in (("fulano@exemplo.com.br", "02"),
                         ("2b9e0c8a-1f3d-4c5e-8a7b-0d1e2f3a4b5c", "04")):
        preparado = remessa_dia.preparar(
            {CONTA: [registro(tipo="Pix", dados=dados)]},
            participantes=CADASTRO, quando=HOJE)
        c, = preparado[CONTA]
        assert c.pode and c.forma_iniciacao == forma, dados


def test_cadastro_desempata_os_onze_digitos():
    """Bate com o documento do cadastro: é o CPF dele, não um telefone."""
    preparado = remessa_dia.preparar(
        {CONTA: [registro(tipo="Pix", dados=CPF_OK)]},
        participantes={"FORNECEDOR SA": CPF_OK}, quando=HOJE)
    c, = preparado[CONTA]
    assert c.pode and c.forma_iniciacao == "03"


def test_celular_e_reconhecido_pela_forma_e_o_documento_vem_do_cadastro():
    """O cadastro diz CNPJ e a chave é um celular: as duas coisas convivem.

    O documento do segmento B é do FAVORECIDO; a chave é só o endereço do Pix.
    """
    preparado = remessa_dia.preparar(
        {CONTA: [registro(tipo="Pix", dados="62999991234")]},
        participantes=CADASTRO, quando=HOJE)
    c, = preparado[CONTA]
    assert c.pode
    assert c.forma_iniciacao == "01"              # telefone
    assert c.documento_favorecido == CNPJ_OK      # do cadastro


def test_ambigua_de_verdade_nao_e_salva_por_cadastro_de_outro_documento():
    preparado = remessa_dia.preparar(
        {CONTA: [registro(tipo="Pix", dados=CHAVE_AMBIGUA)]},
        participantes=CADASTRO, quando=HOJE)
    c, = preparado[CONTA]
    assert c.impedimento == remessa_dia.MOTIVO_CHAVE_AMBIGUA


def test_a_chave_nao_desempata_a_si_mesma():
    """Sem cadastro, um CPF válido na chave NÃO vira prova de que é chave CPF.

    Se o desempate aceitasse o documento já resolvido, ele viria da própria
    chave e confirmaria a si mesmo — e a trava dos onze dígitos, que existe
    desde o `tipo_de_chave_pix`, deixaria de existir aqui.
    """
    assert remessa_dia.forma_de_iniciacao(CHAVE_AMBIGUA, "") == ""
    assert remessa_dia.forma_de_iniciacao(CHAVE_AMBIGUA, CHAVE_AMBIGUA) == "03"


def test_favorecido_fora_do_cadastro_nao_pega_documento_de_outro():
    preparado = remessa_dia.preparar(
        {CONTA: [registro(tipo="Pix", dados="PIX CELULAR 62999991234",
                          favorecido="OUTRO QUALQUER")]},
        participantes=CADASTRO, quando=HOJE)
    c, = preparado[CONTA]
    assert c.impedimento == remessa_dia.MOTIVO_SEM_DOCUMENTO


def test_o_cadastro_casa_ignorando_acento_e_caixa():
    """Os dois lados são digitados por gente — é a lição do `norm_espaco`."""
    preparado = remessa_dia.preparar(
        {CONTA: [registro(tipo="Pix", dados="PIX CELULAR 62999991234",
                          favorecido="Fornecedor  Sa")]},
        participantes=CADASTRO, quando=HOJE)
    c, = preparado[CONTA]
    assert c.pode and c.documento_favorecido == CNPJ_OK


def test_cartao_de_credito_nao_e_transferencia():
    c, = preparar(registro(tipo="Cartão de Crédito", dados="algo"))
    assert not c.pode


# ------------------------------------------------------------ seu número
def test_seu_numero_traz_data_ordem_e_oc():
    c, = preparar(registro())
    assert c.seu_numero == "260813-0001-OC5825"
    assert len(c.seu_numero) <= remessa_dia.TAMANHO_SEU_NUMERO


def test_seu_numero_sem_oc_ainda_identifica():
    c, = preparar(registro(descricao="material diverso"))
    assert c.seu_numero == "260813-0001"


def test_seu_numero_nao_estoura_as_20_posicoes():
    c, = preparar(registro(descricao="OC 1234567 - obra"))
    assert len(c.seu_numero) <= remessa_dia.TAMANHO_SEU_NUMERO


def test_seu_numero_nao_repete_entre_contas():
    preparado = remessa_dia.preparar(
        {"A - SICOOB": [registro(id="a")], "B - SICOOB": [registro(id="b")]},
        quando=HOJE)
    numeros = [c.seu_numero for linhas in preparado.values() for c in linhas]
    assert len(numeros) == len(set(numeros))


def test_impedido_nao_gasta_numero():
    linhas = preparar(registro(obs="PAGAR À MÃO — x"), registro(id="id-erp-2"))
    assert linhas[0].seu_numero == ""
    assert linhas[1].seu_numero.endswith("-0001-OC5825")


# --------------------------------------------------------------- pagador
def mapa_mc():
    return contas_mc.Mapa(raiz=Path("."), destinos=[
        contas_mc.Destino(erp=CONTA, empresa="EXEMPLO", pasta="SICOOB",
                          banco="SICOOB"),
        contas_mc.Destino(erp="EMPRESA EXEMPLO - INTER", empresa="EXEMPLO",
                          pasta="INTER", banco="INTER"),
    ])


def empresas(convenio="123456"):
    """O convênio vai na CONTA — a empresa fica sem, de propósito.

    O Sicoob dá um convênio por conta corrente, e desde 04/09/2026 é de lá
    que `resolver_pagador` o lê. A empresa nasce com o campo vazio aqui para
    que qualquer teste que volte a depender dela falhe."""
    return [sicoob_contas.Empresa(
        nome="EXEMPLO",
        contas=[sicoob_contas.Conta(numero="12.345-6", pasta="SICOOB",
                                    banco="756", agencia="4321-0",
                                    convenio=convenio)],
        cnpj="12.345.678/0001-95",
        razao_social="EMPRESA EXEMPLO LTDA",
    )]


def test_conta_do_erp_vira_empresa_e_conta_do_sicoob():
    pagador, motivo = remessa_dia.resolver_pagador(CONTA, mapa_mc(), empresas())
    assert motivo == ""
    assert (pagador.convenio, pagador.agencia, pagador.dv_agencia) == ("123456", "4321", "0")
    assert (pagador.conta, pagador.dv_conta) == ("12345", "6")


def test_conta_de_outro_banco_nao_gera_remessa():
    _, motivo = remessa_dia.resolver_pagador("EMPRESA EXEMPLO - INTER",
                                             mapa_mc(), empresas())
    assert motivo == remessa_dia.MOTIVO_FORA_SICOOB


def test_conta_sem_banco_nao_gera_remessa_com_motivo_proprio():
    """Sem banco não é "de outro banco": não há outro banco, há campo vazio.

    O mapa carrega a conta assim de propósito — uma linha ruim não derruba as
    outras —, e é aqui que ela para, com o recado dizendo onde consertar."""
    mapa = mapa_mc()
    mapa.destinos.append(contas_mc.Destino(
        erp="EMPRESA EXEMPLO - SEM BANCO", empresa="EXEMPLO",
        pasta="OUTRO", banco=""))
    _, motivo = remessa_dia.resolver_pagador("EMPRESA EXEMPLO - SEM BANCO",
                                             mapa, empresas())
    assert motivo == remessa_dia.MOTIVO_SEM_BANCO
    assert motivo != remessa_dia.MOTIVO_FORA_SICOOB
    assert "contas_mc.json" in motivo
    # e a conta boa da mesma empresa continua saindo
    assert remessa_dia.resolver_pagador(CONTA, mapa, empresas())[1] == ""


def test_conta_fora_do_mapa_nao_gera_remessa():
    _, motivo = remessa_dia.resolver_pagador("CONTA QUE NINGUEM CADASTROU",
                                             mapa_mc(), empresas())
    assert motivo == remessa_dia.MOTIVO_CONTA_DESCONHECIDA


def test_conta_sem_convenio_nao_gera_remessa():
    """A trava natural: quase toda conta ainda está sem convênio."""
    _, motivo = remessa_dia.resolver_pagador(CONTA, mapa_mc(), empresas(convenio=""))
    assert motivo == remessa_dia.MOTIVO_SEM_CONVENIO
    assert "esta conta" in motivo


def test_convenio_da_empresa_nao_e_herdado_pela_conta():
    """O teste que impede alguém de reintroduzir `or empresa.convenio`.

    O Sicoob dá um convênio por CONTA CORRENTE (04/09/2026): uma holding
    daqui tem a principal e oito subcontas, cada uma com o seu. Herdar o da
    empresa faria uma subconta AINDA NÃO ADERIDA sair com o número da
    principal — e o convênio é o campo 07.0 do header e o nome da sequência
    do NSA. O desfecho bom é o banco recusar o arquivo, e o NSA já foi
    queimado; o ruim é ele aceitar em nome de uma conta que ninguém escolheu.
    """
    empresa, = empresas(convenio="")
    empresa.convenio = "123456"                # o cadastro velho, ainda no JSON
    pagador, motivo = remessa_dia.resolver_pagador(CONTA, mapa_mc(), [empresa])
    assert pagador is None
    assert motivo == remessa_dia.MOTIVO_SEM_CONVENIO


# ------------------------------- duas contas na mesma pasta: quem paga?
# Há empresa no cadastro com QUATRO contas Sicoob na pasta "SICOOB", e o que
# as separa é o `sufixo`. Achar a pagadora só pela pasta fazia as quatro
# virarem a MESMA conta: o dinheiro sairia de uma conta que ninguém escolheu,
# com header, pasta e nome de arquivo idênticos aos da certa.
def _duas_na_mesma_pasta(sufixo_a="A", sufixo_b="B",
                         convenio_a="123456", convenio_b="654321"):
    """Duas contas da mesma empresa — e, desde 04/09/2026, dois convênios.

    É o caso da holding: o Sicoob dá um convênio por conta corrente, então
    cada uma tem o seu. A empresa fica sem convênio nenhum."""
    return [sicoob_contas.Empresa(
        nome="EXEMPLO",
        contas=[
            sicoob_contas.Conta(numero="12.345-6", pasta="SICOOB",
                                sufixo=sufixo_a, banco="756", agencia="4321-0",
                                convenio=convenio_a),
            sicoob_contas.Conta(numero="98.765-4", pasta="SICOOB",
                                sufixo=sufixo_b, banco="756", agencia="4321-0",
                                convenio=convenio_b),
        ],
        cnpj="12.345.678/0001-95",
        razao_social="EMPRESA EXEMPLO LTDA",
    )]


def _mapa_com_sufixos():
    mapa = mapa_mc()
    mapa.destinos.append(contas_mc.Destino(
        erp="EMPRESA EXEMPLO - SICOOB B", empresa="EXEMPLO", pasta="SICOOB",
        banco="SICOOB", sufixo="B"))
    # a conta que já existia passa a ser a "A" da mesma pasta
    mapa.destinos[0].sufixo = "A"
    return mapa


def test_o_sufixo_escolhe_a_conta_quando_duas_dividem_a_pasta():
    """Cada conta do ERP resolve para a SUA conta — não para a primeira."""
    mapa = _mapa_com_sufixos()
    a, motivo_a = remessa_dia.resolver_pagador(CONTA, mapa, _duas_na_mesma_pasta())
    b, motivo_b = remessa_dia.resolver_pagador("EMPRESA EXEMPLO - SICOOB B",
                                               mapa, _duas_na_mesma_pasta())
    assert (motivo_a, motivo_b) == ("", "")
    assert (a.conta, a.dv_conta) == ("12345", "6")
    assert (b.conta, b.dv_conta) == ("98765", "4")
    assert a.conta != b.conta


def test_duas_contas_na_pasta_sem_sufixo_recusam_a_remessa():
    """Sem desempate o app não sabe de qual conta o dinheiro sai — e recusa.

    Escolher a primeira é pagar pela conta errada sem nada denunciar: o
    header, a pasta e o nome do arquivo saem idênticos aos da conta certa.
    """
    pagador, motivo = remessa_dia.resolver_pagador(
        CONTA, mapa_mc(), _duas_na_mesma_pasta(sufixo_a="", sufixo_b=""))
    assert pagador is None
    assert motivo == remessa_dia.MOTIVO_CONTA_AMBIGUA
    assert "sufixo" in motivo


def test_uma_conta_na_pasta_dispensa_sufixo():
    """O caso comum não pode passar a exigir cadastro novo para funcionar."""
    pagador, motivo = remessa_dia.resolver_pagador(CONTA, mapa_mc(), empresas())
    assert motivo == ""
    assert (pagador.conta, pagador.dv_conta) == ("12345", "6")


def test_duas_contas_da_mesma_empresa_tem_convenios_diferentes():
    """Cada conta paga pelo SEU convênio — é o caso da holding.

    Enquanto o convênio era da empresa, as duas sairiam com o mesmo campo
    07.0 no header e dividindo UMA sequência de NSA, que é o número que o
    banco confere para não aceitar arquivo repetido."""
    mapa = _mapa_com_sufixos()
    contas = _duas_na_mesma_pasta()
    a, motivo_a = remessa_dia.resolver_pagador(CONTA, mapa, contas)
    b, motivo_b = remessa_dia.resolver_pagador("EMPRESA EXEMPLO - SICOOB B",
                                               mapa, contas)
    assert (motivo_a, motivo_b) == ("", "")
    assert (a.convenio, b.convenio) == ("123456", "654321")
    assert a.conta != b.conta


def test_a_conta_sem_convenio_para_sozinha():
    """Subconta não aderida não derruba a irmã que já aderiu — e, sobretudo,
    não sai com o convênio dela."""
    mapa = _mapa_com_sufixos()
    contas = _duas_na_mesma_pasta(convenio_b="")
    a, motivo_a = remessa_dia.resolver_pagador(CONTA, mapa, contas)
    b, motivo_b = remessa_dia.resolver_pagador("EMPRESA EXEMPLO - SICOOB B",
                                               mapa, contas)
    assert motivo_a == "" and a.convenio == "123456"
    assert b is None and motivo_b == remessa_dia.MOTIVO_SEM_CONVENIO


# ------------------------------------------------- prontidão do cadastro
# A validação acontecia TARDE (só ao clicar em "Gerar remessa") e SEM SUJEITO
# ("Não consegui ler o cadastro", sem dizer de qual conta). Com doze empresas
# e dezessete contas aderidas, isso é o dia parado. A prontidão junta TODOS os
# problemas de TODAS as contas antes de alguém tentar gerar coisa alguma.
def _destino(erp, pasta, banco="SICOOB", empresa="EXEMPLO", sufixo=""):
    return contas_mc.Destino(erp=erp, empresa=empresa, pasta=pasta,
                             banco=banco, sufixo=sufixo)


def _conta(pasta, numero="12.345-6", agencia="4321-0", convenio="123456",
           sufixo=""):
    return sicoob_contas.Conta(numero=numero, pasta=pasta, sufixo=sufixo,
                               banco="756", agencia=agencia, convenio=convenio)


def _empresa(contas, nome="EXEMPLO", cnpj=CNPJ_OK, razao="EMPRESA EXEMPLO LTDA"):
    return sicoob_contas.Empresa(nome=nome, contas=contas, cnpj=cnpj,
                                 razao_social=razao)


def _mapa(*destinos):
    return contas_mc.Mapa(raiz=Path("."), destinos=list(destinos))


def test_prontidao_aponta_a_conta_e_o_campo():
    """Três contas, três vereditos — e cada um diz de QUEM é e o QUE falta.

    É a diferença inteira para `resolver_pagador`: aquele para no primeiro
    problema, porque quem gera precisa de um veredito; esta junta todos,
    porque quem corrige precisa da lista. Descobrir a agência hoje e o
    convênio amanhã é o mesmo dia parado duas vezes."""
    mapa = _mapa(_destino("EXEMPLO - SEM AGENCIA", "SEM AGENCIA"),
                 _destino("EXEMPLO - SEM CONVENIO", "SEM CONVENIO"),
                 _destino("EXEMPLO - COMPLETA", "COMPLETA"))
    cadastro = [_empresa([
        _conta("SEM AGENCIA", numero="11.111-1", agencia="", convenio="111111"),
        _conta("SEM CONVENIO", numero="22.222-2", convenio=""),
        _conta("COMPLETA", numero="33.333-3", convenio="333333"),
    ])]
    por_conta = {c.conta_erp: c for c in remessa_dia.prontidao(mapa, cadastro)}
    assert len(por_conta) == 3

    sem_agencia = por_conta["EXEMPLO - SEM AGENCIA"]
    assert not sem_agencia.pronta and sem_agencia.campos_falta == ["agência"]
    assert "painel" in sem_agencia.faltas[0]

    sem_convenio = por_conta["EXEMPLO - SEM CONVENIO"]
    assert sem_convenio.campos_falta == ["convênio"]
    assert sem_convenio.faltas == [remessa_dia.MOTIVO_SEM_CONVENIO]

    completa = por_conta["EXEMPLO - COMPLETA"]
    assert completa.pronta and completa.faltas == [] and completa.avisos == []
    assert completa.situacao == ("ok", "pronta")
    # o sujeito é o REGISTRO: a conta, a empresa e a conta do banco estão nele
    assert (completa.empresa, completa.conta, completa.convenio) == (
        "EXEMPLO", "33.333-3", "333333")


def test_conta_sem_banco_e_falta_e_a_prontidao_diz_qual_conta():
    """Conta sem `banco` no contas_mc.json entra na lista (pode ser Sicoob),
    e o registro carrega o nome dela — que era o que faltava no recado."""
    mapa = _mapa(_destino("EXEMPLO - SEM BANCO", "SICOOB", banco=""))
    c, = remessa_dia.prontidao(mapa, empresas())
    assert c.conta_erp == "EXEMPLO - SEM BANCO"
    assert c.campos_falta[0] == "banco"
    assert c.faltas[0] == remessa_dia.MOTIVO_SEM_BANCO


def test_conta_de_outro_banco_nao_entra_na_prontidao():
    """Conta do Inter não é pendência: é conta que não faz remessa CNAB, e
    nunca vai fazer. Uma lista que a carrega para sempre é uma lista que
    ninguém lê."""
    conferencias = remessa_dia.prontidao(mapa_mc(), empresas())
    assert [c.conta_erp for c in conferencias] == [CONTA]


def test_e_sicoob_aceita_o_nome_e_o_codigo():
    """O cadastro tem os dois jeitos — o mesmo motivo do
    `nuvem/cadastro._e_inter`, que aceita "INTER" ou "77"."""
    assert all(remessa_dia._e_sicoob(v)
               for v in ("SICOOB", "sicoob", " Sicoob ", "756", "0756"))
    assert not any(remessa_dia._e_sicoob(v)
                   for v in ("", "INTER", "77", "CAIXA", "7560"))


def test_conta_com_banco_756_gera_remessa_e_avisa():
    """Recusar a conta escrita por código dizia "esta conta é de outro banco"
    — manda conferir a coisa errada, para uma conta que É do Sicoob.

    Ela gera, então; e continua sendo AVISO porque é esse campo que nomeia o
    extrato do Relatório Mensal ("202607 756 MAIS CONTROLE.pdf")."""
    mapa = _mapa(_destino(CONTA, "SICOOB", banco="756"))
    c, = remessa_dia.prontidao(mapa, empresas())
    assert c.pronta and c.campos_aviso == ["banco"]
    assert "756 MAIS CONTROLE" in c.avisos[0]
    assert c.situacao == ("info", "aviso: banco")

    pagador, motivo = remessa_dia.resolver_pagador(CONTA, mapa, empresas())
    assert motivo == "" and pagador is not None
    assert motivo != remessa_dia.MOTIVO_FORA_SICOOB


def test_razao_social_vazia_e_aviso_e_nao_falta():
    """O header cai para o nome da pasta, cortado nas 30 posições do campo
    13.0 — o arquivo sai, e sair é o que separa aviso de falta."""
    mapa = _mapa(_destino(CONTA, "SICOOB"))
    cadastro = [_empresa([_conta("SICOOB")], razao="")]
    c, = remessa_dia.prontidao(mapa, cadastro)
    assert c.pronta and c.campos_aviso == ["razão social"]
    pagador, _ = remessa_dia.resolver_pagador(CONTA, mapa, cadastro)
    assert pagador.razao_social == "EXEMPLO"


def test_cnpj_de_preenchimento_do_pagador_e_falta():
    """Ninguém conferia o documento do PAGADOR antes do validador.

    Em 20/08/2026 um CPF de preenchimento do FAVORECIDO — onze dígitos, DV que
    não fecha — fez o Sicoob devolver um arquivo inteiro. O do pagador entra no
    campo 06.0 do header e erra do mesmo jeito, só que em todas as linhas de
    uma vez: aqui a conta para ANTES de o NSA ser queimado."""
    mapa = _mapa(_destino(CONTA, "SICOOB"))
    # o CNPJ sintético de sempre, com o último dígito trocado
    cadastro = [_empresa([_conta("SICOOB")], cnpj="12.345.678/0001-99")]
    c, = remessa_dia.prontidao(mapa, cadastro)
    assert not c.pronta and c.campos_falta == ["CNPJ"]
    assert "dígito verificador" in c.faltas[0]
    assert remessa_dia.resolver_pagador(CONTA, mapa, cadastro)[0] is None
    # e o mesmo cadastro com o CNPJ certo passa
    cadastro[0].cnpj = "12.345.678/0001-95"
    assert remessa_dia.prontidao(mapa, cadastro)[0].pronta


def test_conta_sem_dv_e_falta():
    """"12345" não é conta: o DV é campo próprio no layout (06.0), e montar o
    header sem ele manda o dinheiro sair de uma conta que não existe."""
    mapa = _mapa(_destino(CONTA, "SICOOB"))
    cadastro = [_empresa([_conta("SICOOB", numero="123456")])]
    c, = remessa_dia.prontidao(mapa, cadastro)
    assert not c.pronta and c.campos_falta == ["conta"]
    assert remessa_dia.resolver_pagador(CONTA, mapa, cadastro)[0] is None


def test_agencia_fora_de_quatro_ou_cinco_digitos_e_falta():
    """Vazia já parava; fora do tamanho passava, e quem recusava era o banco —
    depois de o NSA ter sido queimado."""
    mapa = _mapa(_destino(CONTA, "SICOOB"))
    for agencia in ("", "12-3", "1234567-8"):
        cadastro = [_empresa([_conta("SICOOB", agencia=agencia)])]
        c, = remessa_dia.prontidao(mapa, cadastro)
        assert c.campos_falta == ["agência"], agencia
    for agencia in ("4321-0", "43210-1"):
        cadastro = [_empresa([_conta("SICOOB", agencia=agencia)])]
        assert remessa_dia.prontidao(mapa, cadastro)[0].pronta, agencia


def test_duas_contas_com_o_mesmo_convenio_sao_falta_nas_duas():
    """Duas contas com o mesmo convênio dividem UMA sequência de NSA, que é o
    número que o banco confere para não aceitar arquivo repetido.

    Falta nas DUAS porque não há como saber qual está com o número errado, e
    escolher uma é gerar em nome da conta que ninguém escolheu."""
    mapa = _mapa_com_sufixos()
    cadastro = _duas_na_mesma_pasta(convenio_b="123456")     # igual ao da irmã
    conferencias = remessa_dia.prontidao(mapa, cadastro)
    assert len(conferencias) == 2
    assert all(not c.pronta and "convênio" in c.campos_falta
               for c in conferencias)
    for conta in (CONTA, "EMPRESA EXEMPLO - SICOOB B"):
        assert remessa_dia.resolver_pagador(conta, mapa, cadastro)[0] is None
    # com convênios diferentes, as duas voltam a estar prontas
    assert all(c.pronta for c in remessa_dia.prontidao(
        mapa, _duas_na_mesma_pasta()))


def test_duas_contas_com_a_mesma_agencia_e_conta_sao_falta_nas_duas():
    """Mesma agência e mesma conta em duas linhas do cadastro: as duas gerariam
    header idêntico, e nada no arquivo diria de qual delas o dinheiro saiu."""
    mapa = _mapa(_destino("EXEMPLO - A", "PASTA A"),
                 _destino("EXEMPLO - B", "PASTA B"))
    cadastro = [_empresa([
        _conta("PASTA A", numero="12.345-6", convenio="111111"),
        _conta("PASTA B", numero="12.345-6", convenio="222222"),
    ])]
    conferencias = remessa_dia.prontidao(mapa, cadastro)
    assert all(not c.pronta and "conta" in c.campos_falta for c in conferencias)


def _cadastro_com_todos_os_defeitos():
    """Um mapa com uma conta de cada defeito, três sem defeito nenhum e uma de
    outro banco — a matéria-prima do teste que impede a divergência."""
    mapa = _mapa(
        _destino("BOA", "BOA"),
        _destino("BANCO POR CODIGO", "CODIGO", banco="756"),
        _destino("SEM RAZAO", "SEM RAZAO", empresa="SEM RAZAO SOCIAL"),
        _destino("SEM BANCO", "NAO CADASTRADA", banco=""),
        _destino("DE OUTRO BANCO", "INTER", banco="INTER"),
        _destino("EMPRESA QUE NAO EXISTE", "SICOOB", empresa="NINGUEM"),
        _destino("PASTA QUE NAO EXISTE", "NAO CADASTRADA"),
        _destino("AMBIGUA", "DIVIDIDA"),
        _destino("AGENCIA CURTA", "AGENCIA CURTA"),
        _destino("CONTA SEM DV", "CONTA SEM DV"),
        _destino("SEM CONVENIO", "SEM CONVENIO"),
        _destino("CNPJ RUIM", "CNPJ RUIM", empresa="CNPJ RUIM"),
        _destino("CONVENIO REPETIDO A", "REPETIDO A"),
        _destino("CONVENIO REPETIDO B", "REPETIDO B"),
        _destino("MESMA CONTA A", "MESMA CONTA A"),
        _destino("MESMA CONTA B", "MESMA CONTA B"),
    )
    cadastro = [
        _empresa([
            _conta("BOA", numero="10.001-1", convenio="100001"),
            _conta("CODIGO", numero="10.002-2", convenio="100002"),
            _conta("DIVIDIDA", numero="10.003-3", convenio="100003"),
            _conta("DIVIDIDA", numero="10.004-4", convenio="100004"),
            _conta("AGENCIA CURTA", numero="10.005-5", agencia="12-3",
                   convenio="100005"),
            _conta("CONTA SEM DV", numero="100066", convenio="100006"),
            _conta("SEM CONVENIO", numero="10.007-7", convenio=""),
            _conta("REPETIDO A", numero="10.008-8", convenio="999999"),
            _conta("REPETIDO B", numero="10.009-9", convenio="999999"),
            _conta("MESMA CONTA A", numero="10.010-0", convenio="100010"),
            _conta("MESMA CONTA B", numero="10.010-0", convenio="100011"),
        ]),
        _empresa([_conta("SEM RAZAO", numero="10.020-0", convenio="100020")],
                 nome="SEM RAZAO SOCIAL", razao=""),
        _empresa([_conta("CNPJ RUIM", numero="10.021-1", convenio="100021")],
                 nome="CNPJ RUIM", cnpj="12.345.678/0001-99"),
    ]
    return mapa, cadastro


def test_a_prontidao_e_o_resolver_pagador_concordam():
    """O teste que impede as duas de divergirem em silêncio.

    São duas leituras do MESMO cadastro para duas perguntas diferentes ("o que
    conserto?" e "esta conta gera?"), e enquanto forem duas listas de
    checagens elas vão se separar sem ninguém perceber: a tabela diria
    "pronta" e o botão recusaria, ou — pior — a tabela diria "falta" e o
    arquivo sairia assim mesmo."""
    mapa, cadastro = _cadastro_com_todos_os_defeitos()
    conferencias = remessa_dia.prontidao(mapa, cadastro)
    prontas = [c.conta_erp for c in conferencias if c.pronta]
    assert prontas == ["BOA", "BANCO POR CODIGO", "SEM RAZAO"]
    assert len(conferencias) - len(prontas) >= 8      # defeitos de todo tipo

    for c in conferencias:
        pagador, motivo = remessa_dia.resolver_pagador(c.conta_erp, mapa,
                                                       cadastro)
        assert c.pronta == (pagador is not None), (c.conta_erp, c.faltas, motivo)
        # e o motivo que o botão mostra é uma das faltas que a tabela lista
        assert c.pronta or motivo in c.faltas, (c.conta_erp, motivo)


def test_toda_falta_e_todo_aviso_tem_o_nome_do_campo():
    """As listas são paralelas de propósito (a frase inteira para quem
    conserta, o nome do campo para a coluna SITUAÇÃO), e listas paralelas
    divergem: aqui elas são contadas."""
    _mapa_defeitos, cadastro = _cadastro_com_todos_os_defeitos()
    for c in remessa_dia.prontidao(_mapa_defeitos, cadastro):
        assert len(c.campos_falta) == len(c.faltas), c.conta_erp
        assert len(c.campos_aviso) == len(c.avisos), c.conta_erp
        estado, texto = c.situacao
        # os três são chaves de `widgets.MARCAS_ESTADO`, e a tabela indexa por
        # eles — o `widgets` não é importado aqui para este arquivo continuar
        # sendo teste de REGRA, sem tkinter.
        assert estado in ("ok", "atencao", "info")
        assert texto


# ------------------------------------------------- o que ficou sem remessa
def test_contas_sem_remessa_conta_o_que_nao_virou_arquivo():
    """A aritmética do cartão "Contas sem remessa" do Início.

    Ela morava dentro de `_gravar_remessas`, no caminho em que ALGUM arquivo
    saiu — então o dia em que nenhum saía não registrava nada, e o cartão
    mostrava "—": o mesmo que ele mostra quando ninguém rodou. Pura aqui para
    o caso de nenhum arquivo poder ser testado sem abrir janela."""
    preparado = {"A - SICOOB": [1], "B - SICOOB": [1], "C - SICOOB": [1]}
    assert remessa_dia.contas_sem_remessa(preparado, ["a.REM"]) == 2
    # o caso do achado K: nenhum arquivo saiu, e são TRÊS contas sem remessa
    assert remessa_dia.contas_sem_remessa(preparado, []) == 3
    assert remessa_dia.contas_sem_remessa({}, []) == 0
    # mais arquivos que contas não vira número negativo
    assert remessa_dia.contas_sem_remessa(preparado, list("abcd")) == 0


# --------------------------------------------------------------- arquivo
def pagador():
    p, _ = remessa_dia.resolver_pagador(CONTA, mapa_mc(), empresas())
    return p


def test_boleto_e_pix_viram_dois_lotes_no_mesmo_arquivo():
    from cnab240 import validar

    linhas = preparar(registro(),
                      registro(id="id-erp-2", tipo="Pix", valor=840.00,
                               dados="PIX CNPJ 11.222.333/0001-81"))
    arquivo = remessa_dia.montar_arquivo(pagador(), linhas, nsa=31, quando=HOJE)
    assert [l.produto for l in arquivo.lotes] == ["TITULOS_COBRANCA",
                                                  "PIX_TRANSFERENCIA"]
    registros = arquivo.gerar()
    assert validar(registros) == []
    assert registros[0][157:163] == "000031"          # o NSA pedido
    assert registros[0][32:52] == "123456".ljust(20)    # o convênio da empresa


def test_so_boleto_gera_um_lote_so():
    arquivo = remessa_dia.montar_arquivo(pagador(), preparar(registro()),
                                         nsa=1, quando=HOJE)
    assert len(arquivo.lotes) == 1


def test_desmarcado_nao_entra_no_arquivo():
    from cnab240 import validar

    linhas = preparar(registro(), registro(id="id-erp-2", valor=99.00))
    linhas[1].marcado = False
    arquivo = remessa_dia.montar_arquivo(pagador(), linhas, nsa=1, quando=HOJE)
    assert len(arquivo.lotes[0].pagamentos) == 1
    assert validar(arquivo.gerar()) == []


def test_impedido_nao_entra_nem_marcado_a_forca():
    linhas = preparar(registro(obs="PAGAR À MÃO — x"))
    linhas[0].marcado = True
    with pytest.raises(ValueError, match="nenhum pagamento marcado"):
        remessa_dia.montar_arquivo(pagador(), linhas, nsa=1, quando=HOJE)


def test_conta_sem_nada_marcado_nao_gera_arquivo():
    linhas = preparar(registro(status="ATENÇÃO — sem anexo"))
    with pytest.raises(ValueError, match="nenhum pagamento marcado"):
        remessa_dia.montar_arquivo(pagador(), linhas, nsa=1, quando=HOJE)


def test_o_de_para_liga_seu_numero_ao_lancamento():
    linhas = preparar(registro())
    assert remessa_dia.referencias(linhas) == {"260813-0001-OC5825": "id-erp-1"}


def test_o_que_ficou_de_fora_viaja_com_o_motivo():
    preparado = remessa_dia.preparar(
        {CONTA: [registro(), registro(id="x", parcial=True)]}, quando=HOJE)
    de_fora = remessa_dia.fora(preparado)
    assert len(de_fora) == 1
    assert de_fora[0]["motivo"] == remessa_dia.MOTIVO_PARCIAL


def test_nome_do_arquivo_e_legivel_e_unico():
    assert remessa_dia.nome_do_arquivo(pagador(), 31) == "REM_EXEMPLO_000031.REM"


# ----------------------------------------------------- ponta a ponta, com NSA
def test_remessa_registrada_no_historico_nao_repete_o_numero(tmp_path):
    from cnab240 import Historico, HistoricoInvalido

    historico = Historico(tmp_path / "remessas.json")
    p = pagador()
    linhas = preparar(registro())

    nsa = historico.proximo_nsa(p.convenio)
    arquivo = remessa_dia.montar_arquivo(p, linhas, nsa=nsa, quando=HOJE)
    historico.registrar(arquivo, referencias=remessa_dia.referencias(linhas))

    assert historico.proximo_nsa(p.convenio) == nsa + 1
    with pytest.raises(HistoricoInvalido, match="crescente"):
        historico.registrar(
            remessa_dia.montar_arquivo(p, preparar(registro(id="outro")),
                                       nsa=nsa, quando=HOJE))


# ------------------------------------- onde mora o CPF/CNPJ do favorecido
def test_reconhece_cpf_e_cnpj_validos():
    assert remessa_dia.documento_valido("11.222.333/0001-81") == CNPJ_OK
    assert remessa_dia.documento_valido("529.982.247-25") == CPF_OK


def test_telefone_de_onze_digitos_nao_e_cpf():
    """Sem conferir o DV, todo celular viraria 'CPF encontrado'.

    É a mesma armadilha que já derrubou o `tipo_de_chave_pix`: CPF e celular
    têm os dois onze dígitos, e apontar o campo errado aqui mandaria dinheiro
    com o documento de outra pessoa.
    """
    assert remessa_dia.documento_valido("62999991234") == ""
    assert remessa_dia.documento_valido("11111111111") == ""      # repetido
    assert remessa_dia.documento_valido("12345678901") == ""      # DV não fecha


@pytest.mark.parametrize("entrada", [None, True, False, "", "abc", 3.5, []])
def test_lixo_nao_vira_documento(entrada):
    assert remessa_dia.documento_valido(entrada) == ""


def test_acha_documento_em_payload_aninhado():
    payload = {"comment": "x",
               "supplier": {"name": "F", "cpfCnpj": "11.222.333/0001-81"},
               "paids": [{"conta": "1"}, {"doc": CPF_OK}]}
    achados = remessa_dia.documentos_em(payload)
    assert achados == {"supplier.cpfCnpj": CNPJ_OK, "paids[].doc": CPF_OK}


def test_diagnostico_separa_o_fornecedor_da_propria_empresa():
    """Um valor por lançamento = fornecedor. O mesmo em todos = a empresa."""
    overviews = {
        "1": {"empresa": {"cnpj": CNPJ_OK}, "fornecedor": {"cnpj": CPF_OK}},
        "2": {"empresa": {"cnpj": CNPJ_OK}, "fornecedor": {"cnpj": "52998224725"}},
        "3": {"empresa": {"cnpj": CNPJ_OK}, "fornecedor": {"cnpj": "11222333000181"}},
    }
    achados = remessa_dia.diagnostico_documentos(overviews)
    caminhos = {c: (q, d) for c, q, d in achados}
    assert caminhos["empresa.cnpj"] == (3, 1)        # sempre o mesmo
    assert caminhos["fornecedor.cnpj"] == (3, 2)     # varia
    assert achados[0][0] == "fornecedor.cnpj"        # o que varia vem primeiro


def test_diagnostico_com_payload_vazio_nao_quebra():
    assert remessa_dia.diagnostico_documentos({}) == []
    assert remessa_dia.diagnostico_documentos({"1": {}}) == []


def test_diagnostico_atravessa_as_tres_formas_de_payload():
    """As três fontes do passo 1 têm formatos diferentes.

    A lista é uma lista de lançamentos, o detalhe é {id: dict} e os anexos são
    {título: [anexo, ...]}. Varrer só uma responderia sobre ela, não sobre o
    ERP — e foi esse o erro da primeira versão deste diagnóstico.
    """
    lista = {"a": {"fornecedor": {"cnpj": CNPJ_OK}}}
    anexos = {"t1": [{"nome": "nf.pdf", "emitente": CPF_OK}]}
    assert remessa_dia.diagnostico_documentos(lista) == [("fornecedor.cnpj", 1, 1)]
    assert remessa_dia.diagnostico_documentos(anexos) == [("[].emitente", 1, 1)]


def test_a_aba_importa_no_arranjo_do_app():
    """O passo 3 alcança cadastros de OUTRAS abas — e isso já foi frágil no exe.

    Enquanto o app punha cada pasta de aba PLANA no `sys.path`, `sicoob_contas`
    fazia `import sicoob_config` e só resolvia com a pasta dele no caminho: um
    `from extratos_sicoob import sicoob_contas` passava aqui (o conftest punha
    tudo no path) e quebrava na máquina do usuário, ao abrir a aba. Desde
    02/09/2026 os dois lados falam por pacote, e o arranjo do teste é o MESMO
    do app — que é o que este teste continua existindo para conferir.
    """
    import importlib

    frame = importlib.import_module("pagamentos_dia.pagamentos_frame")
    assert frame.remessa_dia and frame.contas_mc and frame.sicoob_contas
    assert callable(frame._historico)


def test_boleto_ja_enviado_e_reconhecido_na_remessa_seguinte(tmp_path):
    from cnab240 import Historico

    historico = Historico(tmp_path / "remessas.json")
    p = pagador()
    linhas = preparar(registro())
    historico.registrar(
        remessa_dia.montar_arquivo(p, linhas, nsa=1, quando=HOJE),
        referencias=remessa_dia.referencias(linhas))

    achado = historico.envio_de(ocr_boleto.codigo_de_barras(LINHA_BANCARIA))
    assert achado is not None and achado[0].nsa == 1


# ==========================================================================
# O que a PRIMEIRA REMESSA REAL (17/08/2026, NSA 000001) mostrou
# ==========================================================================
# Os 12 boletos chegaram ao banco com a inscrição do cedente ZERADA, e o
# Internet Banking exibiu "CPF/CNPJ do beneficiário: 000.000.000-00" nas doze
# telas. Passou por uma combinação exata: o teste da biblioteca preenchia
# `cedente_documento` à mão, e o teste do app não olhava byte nenhum do J-52.
# Estes testes olham os bytes.

def _linhas_do_arquivo(candidatos, **kw):
    arquivo = remessa_dia.montar_arquivo(pagador(), candidatos, nsa=1,
                                         quando=HOJE, **kw)
    return arquivo.gerar()


def _segmentos(linhas, codigo):
    """Os registros de detalhe (tipo 3) de um segmento. J-52 tem '52' em 18-19."""
    if codigo == "J52":
        return [l for l in linhas if l[7] == "3" and l[13] == "J" and l[17:19] == "52"]
    if codigo == "J":
        return [l for l in linhas if l[7] == "3" and l[13] == "J" and l[17:19] != "52"]
    return [l for l in linhas if l[7] == "3" and l[13] == codigo]


# ==========================================================================
# A DESCRIÇÃO no arquivo (20/08/2026)
# ==========================================================================
# Na tela de pendências do SicoobNet o boleto mostrava o nome do fornecedor e o
# Pix não mostrava nada. Medido na remessa 000003: `09.3J` levava o nome (e o
# banco o devolve idêntico no retorno, sem validar contra o título) e as 38
# primeiras posições de `24.3A` iam em branco. Agora as duas levam a descrição.

def _campo(linha: str, layout: str, campo: str) -> str:
    from cnab240 import spec
    from cnab240.campos import ler
    return ler(spec.layout(layout).campo(campo), linha)


def test_a_descricao_vai_no_campo_que_o_banco_mostra_no_boleto():
    linhas = _linhas_do_arquivo(preparar(registro(descricao="PISO 3 CASAS")))
    j, = _segmentos(linhas, "J")
    assert _campo(j, "segmento_j", "09.3J").strip() == "PISO 3 CASAS"


def test_o_boleto_sem_descricao_cai_para_o_nome_do_fornecedor():
    """Em branco aquela coluna não identificaria nada — pior do que antes."""
    linhas = _linhas_do_arquivo(preparar(registro(descricao="")))
    j, = _segmentos(linhas, "J")
    assert _campo(j, "segmento_j", "09.3J").strip() == "FORNECEDOR SA"


def test_o_J52_continua_dizendo_quem_recebe_de_verdade():
    """A troca em 09.3J não pode apagar a identidade: ela mora no J-52."""
    linhas = _linhas_do_arquivo(preparar(registro(descricao="PISO 3 CASAS")))
    j52, = _segmentos(linhas, "J52")
    achou = any("FORNECEDOR SA" in _campo(j52, "segmento_j52", c)
                for c in ("11.4.J52", "14.4.J52"))
    assert achou, "o nome do cedente sumiu do J-52"


def test_a_descricao_do_pix_vai_nas_38_primeiras_de_24_3A():
    c, = preparar(registro(tipo="Pix", dados="11.222.333/0001-81",
                           descricao="MESTRE DE OBRAS"))
    linhas = _linhas_do_arquivo([c])
    a, = _segmentos(linhas, "A")
    info = _campo(a, "segmento_a", "24.3A")
    assert len(info) == 40
    assert info[:38].strip() == "MESTRE DE OBRAS"
    # As duas últimas continuam sendo o tipo da conta de destino.
    assert info[38:].strip() != ""


def test_o_pix_sem_descricao_nao_quebra_o_layout():
    c, = preparar(registro(tipo="Pix", dados="11.222.333/0001-81",
                           descricao="", favorecido=""))
    linhas = _linhas_do_arquivo([c])
    a, = _segmentos(linhas, "A")
    info = _campo(a, "segmento_a", "24.3A")
    assert len(info) == 40 and info[:38].strip() == ""


def test_o_historico_guarda_o_fornecedor_e_nao_a_descricao():
    """A tela de retorno lê do nosso registro, não do arquivo do banco."""
    from cnab240 import historico as h

    linhas = preparar(registro(descricao="PISO 3 CASAS"))
    arquivo = remessa_dia.montar_arquivo(pagador(), linhas, nsa=1, quando=HOJE)
    item, = h.itens_de(arquivo)
    assert item.favorecido == "FORNECEDOR SA"


def test_o_documento_do_cedente_vai_no_J52():
    """A queixa da remessa real: "não puxou os dados de quem está recebendo".

    O NOME já ia; faltava a inscrição — 12.4.J52 (tipo) e 13.4.J52 (número).
    O documento vem do cadastro de Contatos do ERP, o mesmo que o Pix usa.
    """
    preparado = remessa_dia.preparar({CONTA: [registro()]},
                                     participantes=CADASTRO, quando=HOJE)
    j52, = _segmentos(_linhas_do_arquivo(preparado[CONTA]), "J52")
    assert j52[75] == "2"                          # 12.4.J52 tipo: 2 = CNPJ
    assert j52[76:91] == CNPJ_OK.zfill(15)         # 13.4.J52 número
    assert j52[91:131].strip() == "FORNECEDOR SA"  # 14.4.J52 nome


def test_sem_cadastro_o_cedente_fica_zerado_mas_o_boleto_ainda_sai():
    """Boleto se paga pelo código de barras: documento ausente empobrece o
    arquivo, não impede o pagamento. Diferente do Pix, onde é obrigatório."""
    j52, = _segmentos(_linhas_do_arquivo(preparar(registro())), "J52")
    assert j52[75] == "0" and j52[76:91] == "0" * 15
    assert j52[91:131].strip() == "FORNECEDOR SA"


def test_o_vencimento_sai_do_codigo_de_barras():
    """10.3J saía `00000000`. O dado estava no próprio boleto, conferido por
    DV — não precisava do ERP."""
    j, = _segmentos(_linhas_do_arquivo(preparar(registro())), "J")
    assert j[91:99] == f"{ocr_boleto.vencimento_da_linha(LINHA_BANCARIA):%d%m%Y}"
    assert j[91:99] != "00000000"


# ------------------------------------------------------------- arrecadação
# Em 17/08/2026 duas guias viajaram como TÍTULO DE COBRANÇA e o banco aceitou —
# no produto errado. A resposta de então foi excluí-las da remessa, e era o
# certo enquanto o app não sabia montar o outro produto. Desde 30/08/2026 sabe:
# serviço 22, forma 11, segmento O (guia CNAB 240 v3.3, seção 9).
#
# O que estes testes guardam é a distinção que custou caro: o código de barras
# NÃO denuncia a ficha (ela converte para 44 dígitos como qualquer boleto), e
# quem a separa é o formato da linha — 48 dígitos começando em 8.


def test_ficha_de_arrecadacao_entra_na_remessa():
    """Ela deixou de ser impedimento. O produto é que é outro."""
    c, = preparar(registro(dados=LINHA_ARRECADACAO, valor=2670.86))
    assert c.pode and c.marcado
    assert c.arrecadacao, "a ficha precisa se declarar, senão vai no lote errado"
    assert c.codigo_barras == ocr_boleto.codigo_de_barras(LINHA_ARRECADACAO)


def test_boleto_bancario_nao_e_confundido_com_ficha():
    """A outra metade da distinção: o boleto comum continua sendo boleto."""
    c, = preparar(registro())
    assert c.pode and not c.arrecadacao


def test_a_ficha_vai_num_lote_proprio_com_servico_22_e_forma_11():
    """Lote separado por exigência do LAYOUT, não por organização.

    Serviço e forma moram no header do lote (seção 9.1), e header é por lote:
    mandar a ficha junto dos boletos é declarar o produto errado no cabeçalho.
    Foi exatamente isso que aconteceu em 17/08/2026.
    """
    from cnab240 import validar

    linhas = preparar(registro(),
                      registro(id="id-erp-2", dados=LINHA_ARRECADACAO,
                               valor=2670.86, favorecido="CONCESSIONARIA X"))
    arquivo = remessa_dia.montar_arquivo(pagador(), linhas, nsa=31, quando=HOJE)
    assert [l.produto for l in arquivo.lotes] == ["TITULOS_COBRANCA",
                                                  "CONVENIOS_COM_CODIGO_BARRAS"]
    registros = arquivo.gerar()
    assert validar(registros) == []

    cabecalhos = [r for r in registros if r[7:8] == "1"]
    assert cabecalhos[0][9:13] == "2031", "boleto: serviço 20, forma 31"
    assert cabecalhos[1][9:13] == "2211", "arrecadação: serviço 22, forma 11"


def test_a_ficha_sai_no_segmento_O_com_o_codigo_de_barras_inteiro():
    """O que o banco lê para pagar. Errar aqui é pagar a conta de outro."""
    linhas = preparar(registro(id="so-a-ficha", dados=LINHA_ARRECADACAO,
                               valor=2670.86, favorecido="CONCESSIONARIA X"))
    registros = remessa_dia.montar_arquivo(pagador(), linhas, nsa=1,
                                           quando=HOJE).gerar()
    o, = [r for r in registros if r[7:8] == "3" and r[13:14] == "O"]
    assert o[17:61] == ocr_boleto.codigo_de_barras(LINHA_ARRECADACAO)   # 08.3O
    assert o[61:91].strip() == "CONCESSIONARIA X"                       # 09.3O
    assert o[99:107] == f"{HOJE:%d%m%Y}"                                # 11.3O
    assert o[107:122] == "000000000267086"                              # 12.3O
    assert len(o) == 240


def test_a_ficha_sai_sem_vencimento_porque_ela_nao_tem():
    """10.3O é "Data do Vencimento (Nominal)", e a ficha não carrega uma.

    Só o boleto bancário tem fator de vencimento no código de barras. Zerado é
    a resposta honesta; a data de hoje seria afirmar um vencimento que ninguém
    verificou.
    """
    linhas = preparar(registro(id="so-a-ficha", dados=LINHA_ARRECADACAO,
                               valor=2670.86))
    registros = remessa_dia.montar_arquivo(pagador(), linhas, nsa=1,
                                           quando=HOJE).gerar()
    o, = [r for r in registros if r[7:8] == "3" and r[13:14] == "O"]
    assert o[91:99] == "00000000"
    # e o boleto bancário continua levando o dele — a regra não se inverteu
    b, = preparar(registro())
    assert b.vencimento is not None


def test_a_concessionaria_que_o_banco_nao_aceita_fica_de_fora():
    """A exceção nomeada. Some inteira no dia em que o Sicoob aceitar."""
    c, = preparar(registro(dados=LINHA_ARRECADACAO, valor=99.10,
                           favorecido="SANESC SANEAMENTO SA"))
    assert not c.pode
    assert c.impedimento == remessa_dia.MOTIVO_SANESC
    # continua se declarando ficha: o motivo fala de arrecadação, e a
    # conferência precisa mostrar o produto ao lado dele
    assert c.arrecadacao
    preparado = remessa_dia.preparar(
        {CONTA: [registro(dados=LINHA_ARRECADACAO, favorecido="SANESC")]},
        quando=HOJE)
    assert remessa_dia.fora(preparado)[0]["motivo"] == remessa_dia.MOTIVO_SANESC


@pytest.mark.parametrize("nome, recusa", [
    ("SANESC", True),
    ("sanesc saneamento sa", True),        # sem caixa
    ("Companhia SANESC de Saneamento", True),   # por pedaço, no meio do nome
    ("SANEAGO", False),
    ("CONCESSIONARIA QUALQUER", False),
    ("", False),
])
def test_a_regra_da_recusa_casa_por_pedaco_sem_caixa(nome, recusa):
    """A mesma comparação que o resto do app usa para favorecido.

    O ERP escreve o nome da concessionária de mais de um jeito; exigir
    igualdade exata deixaria a exceção passar batido — e aí a ficha sairia num
    arquivo que o banco recusa inteiro."""
    assert bool(remessa_dia.arrecadacao_recusada(nome)) is recusa


def test_a_recusa_nao_alcanca_o_boleto_bancario():
    """A regra é da ARRECADAÇÃO. Um boleto comum desse favorecido continua
    saindo — o que o banco não aceita é a ficha, não a empresa."""
    c, = preparar(registro(favorecido="SANESC SANEAMENTO SA"))
    assert c.pode and not c.arrecadacao


def test_oc_e_centro_de_custo_viajam_para_a_conferencia():
    """As duas colunas da tela saem do registro, e não de reparsear a
    descrição — que é texto que o próprio `relatorio` acabou de montar."""
    c, = preparar(registro(oc="5825", centro_custo="TB 21 QD 51 LT 40"))
    assert c.oc == "5825"
    assert c.centro_custo == "TB 21 QD 51 LT 40"


def test_oc_e_centro_de_custo_tambem_no_que_ficou_de_fora():
    """A linha impedida é a que MAIS precisa ser identificada: é sobre ela que
    alguém vai ter de decidir alguma coisa depois."""
    c, = preparar(registro(dados=LINHA_ARRECADACAO, favorecido="SANESC",
                           oc="6001", centro_custo="QD 26A LT 12"))
    assert not c.pode
    assert (c.oc, c.centro_custo) == ("6001", "QD 26A LT 12")


@pytest.mark.parametrize("linha, esperado", [
    (LINHA_ARRECADACAO, True),
    (LINHA_BANCARIA, False),      # boleto bancário, 47 dígitos
    ("12345", False),
    ("", False),
])
def test_reconhece_ficha_de_arrecadacao(linha, esperado):
    assert ocr_boleto.eh_arrecadacao(linha) is esperado


def test_o_header_do_lote_leva_a_data_do_pagamento():
    """O segmento J não tem campo de descrição — os 40 caracteres do header de
    lote (18.1) são o único texto livre, e saíam em branco."""
    linhas = _linhas_do_arquivo(preparar(registro()))
    header, = [l for l in linhas if l[7] == "1"]
    assert header[102:142].strip() == f"PAGAMENTOS DO DIA {HOJE:%d/%m/%Y}"


def test_a_mensagem_do_lote_nao_estoura_as_40_posicoes():
    assert len(remessa_dia._mensagem_do_lote(HOJE)) <= remessa_dia.TAMANHO_MENSAGEM_LOTE


@pytest.mark.parametrize("linha, esperado", [
    (LINHA_BANCARIA, _dt.date(2026, 8, 10)),   # fator 1534, 2ª volta
    (LINHA_ARRECADACAO, None),                 # arrecadação não tem o campo
    ("12345", None),
    ("", None),
])
def test_vencimento_da_linha(linha, esperado):
    assert ocr_boleto.vencimento_da_linha(linha, hoje=HOJE) == esperado


def test_o_fator_de_vencimento_virou_em_2025():
    """O campo tem 4 dígitos e estourou em 21/02/2025. Fator baixo depois
    disso é a SEGUNDA volta — lê-lo com a base antiga daria 2001."""
    antes = ocr_boleto.vencimento_da_linha(LINHA_BANCARIA, hoje=_dt.date(2024, 1, 1))
    depois = ocr_boleto.vencimento_da_linha(LINHA_BANCARIA, hoje=_dt.date(2026, 8, 17))
    assert antes.year == 2001 and depois.year == 2026


# ==========================================================================
# Reembolso: o arquivo passa a declarar A PESSOA
# ==========================================================================
# Até 19/08/2026 todo reembolso era impedido, e com razão: o segmento B leva
# UM par nome/documento, e os dois lados vinham de origens diferentes — nome e
# documento do FORNECEDOR, chave Pix DA PESSOA. Agora a planilha resolve quem
# recebe (`reembolso.identificar`) e manda os dois campos juntos; aqui se
# prova que eles chegam ao arquivo, e que o do fornecedor NÃO chega.

CPF_DA_PESSOA = "11144477735"


def reembolso_resolvido(**troca):
    """Um reembolso cuja pessoa a planilha já identificou."""
    base = {"tipo": "Pix", "dados": "PIX CPF 111.444.777-35",
            "status": "APTO* (reembolso)", "favorecido": "FORNECEDOR SA",
            "reembolso": True, "reembolso_nome": "PESSOA DE EXEMPLO",
            "reembolso_documento": CPF_DA_PESSOA,
            "reembolso_origem": "Contatos do ERP"}
    base.update(troca)
    return registro(**base)


def test_reembolso_resolvido_entra_declarando_a_pessoa():
    """O favorecido do ARQUIVO é a pessoa; o do lançamento fica guardado.

    O `participantes` traz o CNPJ do FORNECEDOR de propósito: é o documento
    que a linha teria pegado antes, e o que ela não pode pegar agora.
    """
    c, = remessa_dia.preparar({CONTA: [reembolso_resolvido()]},
                              participantes=CADASTRO, quando=HOJE)[CONTA]
    assert c.pode
    assert c.favorecido == "PESSOA DE EXEMPLO"
    assert c.documento_favorecido == CPF_DA_PESSOA != CNPJ_OK
    assert c.reembolso and c.reembolso_de == "FORNECEDOR SA"


def test_reembolso_resolvido_nasce_desmarcado():
    """É APTO, e mesmo assim pede um clique.

    É a única linha em que o app troca o favorecido por conta própria — quem
    confere o total não tem como perceber a troca sozinho.
    """
    c, = remessa_dia.preparar({CONTA: [reembolso_resolvido()]},
                              participantes=CADASTRO, quando=HOJE)[CONTA]
    assert c.apto and c.pode and not c.marcado


def test_o_reembolso_declara_a_pessoa_nos_bytes_do_arquivo():
    """Os bytes, dos DOIS lados do par — que é onde estava a contradição.

    O nome do favorecido mora no segmento A e a inscrição no B (07.3B/08.3B).
    Era essa separação que deixava o defeito passar: cada campo, olhado
    sozinho, estava preenchido e plausível. O que não podia era o nome de um
    e o documento de outro.
    """
    linhas = remessa_dia.preparar({CONTA: [reembolso_resolvido()]},
                                  participantes=CADASTRO, quando=HOJE)[CONTA]
    for c in linhas:
        c.marcado = True                       # a pessoa confirmou na janela
    registros = _linhas_do_arquivo(linhas)
    a, = _segmentos(registros, "A")
    b, = _segmentos(registros, "B")
    assert "PESSOA DE EXEMPLO" in a            # nome: a pessoa
    assert "FORNECEDOR SA" not in a            # e não o fornecedor
    assert CPF_DA_PESSOA in b                  # documento: o dela
    assert CNPJ_OK not in b                    # e não o do fornecedor


def test_reembolso_sem_documento_continua_fora_com_o_motivo_de_la():
    """Não sabendo quem recebe, o impedimento vem da planilha e diz o que falta."""
    falta = "reembolso para 'PESSOA DE EXEMPLO': o CPF de quem recebe não foi encontrado"
    c, = preparar(reembolso_resolvido(reembolso_documento="", reembolso_nome="",
                                      reembolso_impedimento=falta))
    assert not c.pode and c.impedimento == falta


def test_reembolso_sem_veredito_nenhum_e_impedido():
    """A rede de baixo: registro que não passou pelo `reembolso.identificar`."""
    c, = preparar(registro(tipo="Pix", dados="PIX CPF 529.982.247-25",
                           status="APTO* (reembolso)", reembolso=True))
    assert not c.pode and c.impedimento == remessa_dia.MOTIVO_REEMBOLSO


# ------------------------------------- o que VOCÊ tirou também é relatado
def test_o_que_voce_desmarcou_tambem_sai_na_lista():
    """Omitir não é apagar — e vale para a escolha, não só para a regra.

    A linha desmarcada na conferência sumia do arquivo e não aparecia em lugar
    nenhum: quem olhasse a planilha via APTO, quem olhasse o arquivo não via o
    pagamento, e nada dizia por quê.
    """
    preparado = remessa_dia.preparar({CONTA: [registro()]}, quando=HOJE)
    preparado[CONTA][0].marcado = False
    de_fora = remessa_dia.fora(preparado)
    assert len(de_fora) == 1
    assert de_fora[0]["motivo"] == remessa_dia.MOTIVO_DESMARCADO
    assert de_fora[0]["favorecido"] == "FORNECEDOR SA"


def test_a_linha_marcada_e_sem_impedimento_nao_sai_na_lista():
    preparado = remessa_dia.preparar({CONTA: [registro()]}, quando=HOJE)
    assert preparado[CONTA][0].marcado
    assert remessa_dia.fora(preparado) == []


def test_impedido_nao_vira_escolha_sua():
    """A linha impedida nunca teve caixa; o motivo dela é o da regra."""
    preparado = remessa_dia.preparar({CONTA: [registro(parcial=True)]}, quando=HOJE)
    assert remessa_dia.fora(preparado)[0]["motivo"] == remessa_dia.MOTIVO_PARCIAL


# ------------------------------------------------- uma pasta por conta
# Cada conta pagadora gera o SEU arquivo. Numa pasta só, os nomes são
# parecidos demais — mesmo prefixo, NSA sequencial por convênio — e subir o
# arquivo de uma conta no acesso de outra só apareceria no SicoobNet, depois
# de enviado.

def _pagador(empresa="MORAIS ENGENHARIA LTDA", agencia="3299", conta="50022"):
    return remessa_dia.Pagador(
        conta_erp="x", empresa=empresa, razao_social=empresa, cnpj="1",
        convenio="1814", agencia=agencia, dv_agencia="", conta=conta,
        dv_conta="5")


def test_cada_conta_tem_a_sua_pasta():
    a = remessa_dia.pasta_do_pagador("D:/saida", _pagador(conta="50022"))
    b = remessa_dia.pasta_do_pagador("D:/saida", _pagador(conta="71234"))
    assert a != b
    assert a.parent == b.parent, "a mesma empresa, dois galhos irmãos"
    assert a.name == "SICOOB 3299-50022"


def test_empresas_diferentes_nao_dividem_galho():
    a = remessa_dia.pasta_do_pagador("D:/saida", _pagador(empresa="UMA LTDA"))
    b = remessa_dia.pasta_do_pagador("D:/saida", _pagador(empresa="OUTRA SA"))
    assert a.parent != b.parent


def test_nome_de_empresa_com_barra_nao_inventa_nivel():
    r"""`/` e `\` no nome viram pasta dentro de pasta — e o arquivo nasce num
    lugar que ninguém procurou."""
    p = remessa_dia.pasta_do_pagador(
        "D:/saida", _pagador(empresa="UMA / OUTRA: EMPRESA"))
    assert p.parts[-2] == "UMA OUTRA EMPRESA"


def test_nome_que_termina_em_ponto_e_aparado():
    """O Windows cria a pasta e depois não consegue abri-la."""
    p = remessa_dia.pasta_do_pagador("D:/saida", _pagador(empresa="EMPRESA S.A."))
    assert not p.parts[-2].endswith(".")


def test_empresa_sem_nome_ainda_tem_onde_cair():
    p = remessa_dia.pasta_do_pagador("D:/saida", _pagador(empresa=""))
    assert p.parts[-2] == "EMPRESA"


def test_o_arquivo_continua_com_o_nome_de_sempre():
    """A pasta mudou; o nome do arquivo, não — o histórico e o SicoobNet o
    reconhecem por ele."""
    assert remessa_dia.nome_do_arquivo(_pagador(), 7) ==         "REM_MORAIS-ENGENHARIA-LTDA_000007.REM"
