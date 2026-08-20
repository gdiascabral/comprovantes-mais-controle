# -*- coding: utf-8 -*-
"""A regra do passo 3: quem pode sair na remessa, e como o arquivo é montado.

Sem tela. O que se testa aqui é dinheiro saindo para a pessoa certa, na conta
certa, uma vez só.
"""
import datetime as _dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ocr_boleto                                    # noqa: E402
import remessa_dia                                   # noqa: E402
import contas_mc                                     # noqa: E402
import sicoob_contas                                 # noqa: E402

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
    return [sicoob_contas.Empresa(
        nome="EXEMPLO",
        contas=[sicoob_contas.Conta(numero="12.345-6", pasta="SICOOB",
                                    banco="756", agencia="4321-0")],
        cnpj="12.345.678/0001-95",
        razao_social="EMPRESA EXEMPLO LTDA",
        convenio=convenio,
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


def test_conta_fora_do_mapa_nao_gera_remessa():
    _, motivo = remessa_dia.resolver_pagador("CONTA QUE NINGUEM CADASTROU",
                                             mapa_mc(), empresas())
    assert motivo == remessa_dia.MOTIVO_CONTA_DESCONHECIDA


def test_empresa_sem_convenio_nao_gera_remessa():
    """A trava natural: 11 das 12 empresas ainda estão sem convênio."""
    _, motivo = remessa_dia.resolver_pagador(CONTA, mapa_mc(), empresas(convenio=""))
    assert motivo == remessa_dia.MOTIVO_SEM_CONVENIO


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
    """O passo 3 alcança cadastros de OUTRAS abas — e isso é frágil no exe.

    O app põe cada pasta de aba PLANA no sys.path, e o `sicoob_contas` faz
    `import sicoob_config`, que só resolve com a pasta dele no caminho. Um
    `from extratos_sicoob import sicoob_contas` passaria aqui (o conftest põe
    tudo no path) e quebraria na máquina do usuário, ao abrir a aba.
    """
    import importlib

    frame = importlib.import_module("pagamentos_frame")
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


def test_ficha_de_arrecadacao_nao_entra_na_remessa():
    """Duas guias municipais viajaram como título de cobrança em 17/08/2026.

    O banco aceitou — mas o produto certo é outro (segmento O, forma 11), e o
    dono decidiu pagá-las à parte, pelo QR Code Pix. Elas saem da remessa com
    o motivo escrito, em vez de irem no produto errado.

    A conversão do código de barras NÃO as denuncia: ficha de arrecadação
    converte para 44 dígitos como qualquer boleto. Quem separa é o formato da
    linha — 48 dígitos começando em 8.
    """
    c, = preparar(registro(dados=LINHA_ARRECADACAO, valor=2670.86))
    assert not c.pode
    assert c.impedimento == remessa_dia.MOTIVO_ARRECADACAO
    # e o motivo viaja para a lista do que ficou de fora
    preparado = remessa_dia.preparar(
        {CONTA: [registro(dados=LINHA_ARRECADACAO, valor=2670.86)]}, quando=HOJE)
    assert remessa_dia.fora(preparado)[0]["motivo"] == remessa_dia.MOTIVO_ARRECADACAO


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
