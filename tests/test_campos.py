# -*- coding: utf-8 -*-
"""Testes de extração de campos a partir do TEXTO do comprovante.

As fixtures em tests/fixtures/*.txt são o texto que sairia do pdfplumber (ou
do OCR, no layout impresso). São SINTÉTICAS — nomes/documentos fake — porque
o repositório é público e não pode conter comprovantes reais. Para cobrir um
banco/layout novo, salve aqui o texto ANONIMIZADO de um exemplo."""
from pathlib import Path

import pytest

# separar_renomear importa tkinter/pdfplumber no topo; se faltarem, pula.
sr = pytest.importorskip("separar_renomear.separar_renomear")

FIX = Path(__file__).resolve().parent / "fixtures"


def _ler(nome):
    return (FIX / nome).read_text(encoding="utf-8")


def test_campos_inter_pix_antigo():
    c = sr.campos(_ler("inter_pix_antigo.txt"))
    assert c["banco"] == "INTER"
    assert c["valor"] == "70,00"
    assert c["data"] == "20/07/2026"
    assert "OC 5979" in c["desc"]


def test_campos_sicoob_pix_impresso():
    c = sr.campos(_ler("sicoob_pix_impresso.txt"))
    assert c["banco"] == "SICOOB"
    assert c["valor"] == "1.890,00"
    assert "5428" in c["desc"]


def test_campos_inter_pix_sobre_transacao():
    """Layout atual do Inter: traz 'Sobre a transação' e 'Banco Inter', mas os
    rótulos vêm com o valor NA MESMA LINHA — tem de cair no parser clássico.
    Antes o parser 'impresso' sequestrava esse layout e o nome saía
    '4632,00 - Instituição Banco Inter', sem descrição e sem data."""
    c = sr.campos(_ler("inter_pix_sobre_transacao.txt"))
    assert c["banco"] == "INTER"
    assert c["valor"] == "4.632,00"
    assert c["data"] == "31/07/2026"
    assert c["desc"] == "ADM - GESTOR COMERCIAL - 06 2026"
    assert sr.nome_arquivo(c) == "4632,00 - ADM - GESTOR COMERCIAL - 06 2026 - 31-07"


def test_campos_inter_pagamento_boleto():
    """Pagamento de boleto pelo Inter: a descrição não tem OC/NF/centro de
    custo, e o nome saía com a linha de 'Autenticação' no lugar dela."""
    c = sr.campos(_ler("inter_pgto_boleto.txt"))
    assert c["valor"] == "7.020,00"
    assert c["data"] == "31/07/2026"
    assert sr.nome_arquivo(c) == "7020,00 - RECRUTAMENTO E SELECAO - 31-07"


def test_campos_sicoob_boleto_impresso():
    """Layout impresso (rótulos num bloco, valores em outro): a descrição boa
    é a observação com centro de custo — não a razão social do fornecedor,
    que casava com 'DISTRIBUI' e passava na frente."""
    c = sr.campos(_ler("sicoob_boleto_impresso.txt"))
    assert c["valor"] == "1.150,00"
    assert c["desc"] == "DONA MORENA QD 18 LT 8 11 B1 OC 5624"
    assert sr.nome_arquivo(c) == "1150,00 - DONA MORENA QD 18 LT 8 11 B1 OC 5624 - 31-07"


def test_campos_sicoob_darf():
    """Comprovante de tributo: rótulos em CAIXA ALTA ('VALOR TOTAL:',
    'DATA DE PAGAMENTO:'). Sem o casamento sem diferenciar maiúsculas o
    arquivo saía como 'SEM VALOR - SEM DESCRICAO' e não casava com nada."""
    c = sr.campos(_ler("sicoob_darf.txt"))
    assert c["valor"] == "240,22"
    assert c["data"] == "31/07/2026"
    assert sr.nome_arquivo(c) == "240,22 - PAGAMENTO DARF - 31-07"


def test_descricao_colada_vence_o_nome_do_recebedor():
    """PIX impresso: o OCR come os espaços do centro de custo e a descrição
    vira um bloco só ('TB21QD51LT23C282M3'). Antes ela era descartada (parecia
    código, por ser cheia de dígito) e o nome caía no DESTINATÁRIO — saía
    '7130,00 - Fulano de Tal Exemplo'. Deve sair o centro de custo, espaçado
    para o matcher enxergar QD/LT."""
    c = sr.campos(_ler("sicoob_pix_desc_colada.txt"))
    assert c["valor"] == "7.130,00"
    assert c["data"] == "31/07/2026"
    assert sr.nome_arquivo(c) == "7130,00 - TB 21 QD 51 LT 23 C 282 M 3 - 31-07"


def test_espacar_codigo_so_mexe_no_que_deve():
    assert sr._espacar_codigo("TB21QD51LT23C282M3") == "TB 21 QD 51 LT 23 C 282 M 3"
    # vale por palavra: conserta também a descrição meio colada
    assert sr._espacar_codigo("DONA MORENA QD 18LT811B1C259M5") == \
        "DONA MORENA QD 18 LT 811 B 1 C 259 M 5"
    # já espaçado, curto demais, texto normal ou ID: não mexe
    for intocado in ("RPB 24 QD 26A LT 10 OC 6332", "COMBUSTIVEL",
                     "E0438868820260731180053vasuoyr4V", "ENGENHEIRO",
                     "Pos obra OC6323", "ADM - GESTOR COMERCIAL - 06 2026"):
        assert sr._espacar_codigo(intocado) == intocado


def test_recebedor_desempata_nomes_repetidos():
    """Dois comprovantes de mesmo valor e mesma descrição no mesmo dia viravam
    'X' e 'X (2)'. Com com_recebedor entra quem recebeu, que é o que de fato
    distingue os dois."""
    c = sr.campos(_ler("inter_pix_sobre_transacao.txt"))
    assert sr.nome_arquivo(c) == "4632,00 - ADM - GESTOR COMERCIAL - 06 2026 - 31-07"
    assert sr.nome_arquivo(c, com_recebedor=True) == (
        "4632,00 - ADM - GESTOR COMERCIAL - 06 2026 - FULANO DE TAL EXEMPLO - 31-07")
    # modelo personalizado que já pede RECEBEDOR não pode duplicar o nome
    modelo = "VALOR - DESCRIÇÃO - RECEBEDOR"
    assert sr.nome_arquivo(c, modelo, com_recebedor=True) == \
        sr.nome_arquivo(c, modelo)


def _pix(valor, desc, dest):
    return dict(banco="INTER", tipo="PIX", valor=valor, data="31/07/2026",
                desc=desc, pag="EMPRESA EXEMPLO LTDA", dest=dest)


def test_valor_repetido_poe_o_recebedor_em_TODOS():
    """Antes só o segundo do grupo levava o nome de quem recebeu, e sobrava um
    '1621,00 - ESTAGIÁRIO - 31-07' sem dono. Para o casamento distinguir os
    dois, os dois precisam do nome."""
    nomes = sr._nomes_finais([
        _pix("1.621,00", "ESTAGIÁRIO", "Fulano de Tal Exemplo"),
        _pix("1.621,00", "ESTAGIÁRIO", "Beltrano Exemplo"),
        _pix("500,00", "COMBUSTIVEL", "Sicrano Exemplo"),   # não repete
    ])
    assert nomes == [
        "1621,00 - ESTAGIÁRIO - Fulano de Tal Exemplo - 31-07",
        "1621,00 - ESTAGIÁRIO - Beltrano Exemplo - 31-07",
        "500,00 - COMBUSTIVEL - 31-07",
    ]


def test_nome_que_ja_existe_na_pasta_tambem_ganha_recebedor():
    nomes = sr._nomes_finais(
        [_pix("500,00", "COMBUSTIVEL", "Fulano de Tal Exemplo")],
        ja_existe=lambda b: b == "500,00 - COMBUSTIVEL - 31-07")
    assert nomes == ["500,00 - COMBUSTIVEL - Fulano de Tal Exemplo - 31-07"]


def test_recebedor_nao_repete_quando_ja_esta_no_nome():
    """Em aporte/transferência o miolo já é 'PAGADOR PARA RECEBEDOR'."""
    c = dict(banco="INTER", tipo="PIX", valor="1.000,00", data="31/07/2026",
             desc="APORTE CAPITAL", pag="EMPRESA A LTDA", dest="EMPRESA B LTDA")
    assert sr.nome_arquivo(c, com_recebedor=True) == \
        "1000,00 - EMPRESA A PARA EMPRESA B - 31-07"


def test_rotulo_nunca_vira_descricao():
    """Rótulos técnicos ('Instituição', 'CPF/CNPJ', 'Autenticação') não podem
    virar o miolo do nome do arquivo."""
    for fix in ("inter_pix_sobre_transacao.txt", "inter_pgto_boleto.txt",
                "sicoob_boleto_impresso.txt", "sicoob_pix_impresso.txt"):
        nome = sr.nome_arquivo(sr.campos(_ler(fix)))
        for lixo in ("Instituição", "CPF/CNPJ", "CPFCNPJ", "Autentica",
                     "Descrição", "Identificador"):
            assert lixo not in nome, f"{fix}: {nome}"


def test_nome_arquivo_round_trip_para_o_matcher():
    """O nome gerado pelo Separar precisa ser lido de volta pelo matcher."""
    from anexar import matcher
    c = sr.campos(_ler("inter_pix_antigo.txt"))
    nome = sr.nome_arquivo(c) + ".pdf"
    p = matcher.parse_pdf(nome)
    assert p is not None
    assert p["valor"] == 7000
    assert "5979" in p["ocs"]


# ------------------------------------------- o comprovante comum do Sicoob
# Rótulo e valor na mesma linha, SEM dois-pontos. É o texto que sai do PDF do
# Sicoob e também o que o OCR devolve de uma foto dele. Medido em 368
# comprovantes reais de 10 e 11/09/2026: o parser antigo acertava o valor em
# 113 e punha a descrição no nome em 73 de 223; o novo, 368 e 210 (as 13 que
# faltam são aportes, que viram "PAGADOR PARA RECEBEDOR" de propósito).
# Tudo SINTÉTICO: empresas, obra, documentos e códigos são inventados.

SICOOB_BOLETO = """\
SICOOB - SISTEMA DE COOPERATIVAS DE CRÉDITO DO BRASIL
SISBR - SISTEMA DE INFORMÁTICA DO SICOOB
COMPROVANTE DE
10/09/2026 15:06:02
PAGAMENTO DE BOLETO
Cooperativa 0000-0 / COOPERATIVA DE CRÉDITO EXEMPLO LTDA
Conta 00.000-0
Cliente EMPRESA EXEMPLO ENGENHARIA LTDA
Linha digitável 11111.22222 33333.444444 55555.666666 7 88880000115000
Número do documento --
Beneficiário
Nome/Razão Social FORNECEDOR FICTICIO DE MATERIAIS LTDA
Nome Fantasia FORNECEDOR FICTICIO
CPF/CNPJ 11.111.111/0001-11
Pagador
Nome/Razão social EMPRESA EXEMPLO ENGENHARIA LTDA
Nome fantasia EMPRESA EXEMPLO ENGENHARIA LTDA
CPF/CNPJ 00.000.000/0001-00
Datas
Realizado 07/09/2026 às 17:57:26
Pagamento 08/09/2026
Vencimento 07/09/2026
Valores
Documento R$ 1.100,00
Desconto/Abatimento R$ 0,00
Juros/Multa R$ 50,00
Pago R$ 1.150,00
Situação Efetivado
Observação{sep}RESIDENCIAL EXEMPLO QD 99 LT 1 NF 1234 OC 5678
Autenticação 11111111-2222-3333-4444-555566667777
OUVIDORIA SICOOB: 08007250996
"""


@pytest.mark.parametrize("sep", [" ", ": "], ids=["sem-dois-pontos", "com-dois-pontos"])
def test_sicoob_comum_valor_pago_data_do_pagamento_e_observacao(sep):
    """Sem os ":" o boleto do Sicoob saía sem valor (o "Pago R$" não era
    lido), com a data da IMPRESSÃO (10/09, o carimbo do topo) e sem a
    observação — o nome caía no fornecedor. O valor é o PAGO (com juros),
    não o do documento; a data é a do pagamento, não a do agendamento."""
    c = sr.campos(SICOOB_BOLETO.format(sep=sep))
    assert c["banco"] == "SICOOB"
    assert c["valor"] == "1.150,00"
    assert c["data"] == "08/09/2026"
    assert c["desc"] == "RESIDENCIAL EXEMPLO QD 99 LT 1 NF 1234 OC 5678"
    assert sr.nome_arquivo(c) == \
        "1150,00 - RESIDENCIAL EXEMPLO QD 99 LT 1 NF 1234 OC 5678 - 08-09"


def test_sicoob_comum_round_trip_para_o_matcher():
    from anexar import matcher
    c = sr.campos(SICOOB_BOLETO.format(sep=" "))
    p = matcher.parse_pdf(sr.nome_arquivo(c) + ".pdf")
    assert p["valor"] == 115000
    assert p["data"] == "0809"
    assert p["ocs"] == {"5678"} and p["nfs"] == {"1234"}


SICOOB_PIX_ENVIADO = """\
SICOOB - SISTEMA DE COOPERATIVAS DE CRÉDITO DO BRASIL
SISBR - SISTEMA DE INFORMÁTICA DO SICOOB
COMPROVANTE DE EFETIVAÇÃO DE PAGAMENTO PIX
Tipo Pagamento Pix enviado
Pagador
Instituição COOPERATIVA DE CRÉDITO EXEMPLO LTDA.
Nome EMPRESA EXEMPLO ENGENHARIA LTDA
CPF/CNPJ **.000.000/0001-**
Destinatário
Nome FORNECEDOR FICTICIO
CPF/CNPJ **.111.111/0001-**
Instituição/Banco BANCO EXEMPLO S.A.
Dados do pagamento
Data do pagamento 03/09/2026 16:21:19
Valor R$ 123,45
ID Transação E00000000202609031919AAAAAAAAAAA
Situação do pagamento Finalizado com sucesso
OUVIDORIA SICOOB : 08007250996
"""


def test_pix_do_sicoob_com_pix_enviado_nao_vira_inter():
    """O Sicoob também escreve "Pix enviado", e o `detectar` antigo olhava
    isso primeiro: o Pix virava Inter e saía sem valor, pagador e recebedor.
    Sem descrição no banco, o nome é o de quem recebeu."""
    c = sr.campos(SICOOB_PIX_ENVIADO)
    assert (c["banco"], c["tipo"]) == ("SICOOB", "PIX")
    assert c["valor"] == "123,45"
    assert c["pag"] == "EMPRESA EXEMPLO ENGENHARIA LTDA"
    assert sr.nome_arquivo(c) == "123,45 - FORNECEDOR FICTICIO - 03-09"


def test_transferencia_do_sicoob_le_os_blocos_debito_e_credito():
    t = """\
SICOOB - SISTEMA DE COOPERATIVAS DE CRÉDITO DO BRASIL
SISBR - SISTEMA DE INFORMÁTICA DO SICOOB
COMPROVANTE DE TRANSFERÊNCIA
10/09/2026 16:41:54
ENTRE CONTAS CORRENTES
Número do agendamento 11111111
Data do agendamento 31/08/2026
Data do lançamento 01/09/2026
Valor R$ 11.000,00
Natureza TRANSF.INTERC.PIX-DIF. TIT
Débito
Cooperativa 0000-0 / SICOOB EXEMPLO
Conta 00.000-0 / EMPRESA EXEMPLO SPE LTDA
Crédito
Cooperativa 1111-1 / SICOOB OUTRO EXEMPLO
Conta 11.111-1 / FORNECEDOR FICTICIO LTDA
Autenticação AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE
OUVIDORIA SICOOB: 08007250996
"""
    c = sr.campos(t)
    assert (c["banco"], c["tipo"]) == ("SICOOB", "TRANSF")
    assert c["pag"] == "EMPRESA EXEMPLO SPE LTDA"
    assert sr.nome_arquivo(c) == "11000,00 - FORNECEDOR FICTICIO - 01-09"


def test_convenio_do_sicoob_usa_a_observacao_e_o_convenio():
    t = """\
SICOOB - SISTEMA DE COOPERATIVAS DE CRÉDITO DO BRASIL
SISBR - SISTEMA DE INFORMÁTICA DO SICOOB
COMPROVANTE
10/09/2026 15:06:02
DE PAGAMENTO DE CONVÊNIO
Cooperativa 0000 / SICOOB EXEMPLO
Conta 00.000-0 / EMPRESA EXEMPLO ENGENHARIA LTDA
Convênio AGUA EXEMPLO GO
Data do pagamento 08/09/2026
Valor do documento R$ 0,00
Valor total R$ 987,65
Observação AGUA EXEMPLO
"""
    c = sr.campos(t)
    assert c["dest"] == "AGUA EXEMPLO GO"
    assert sr.nome_arquivo(c) == "987,65 - AGUA EXEMPLO - 08-09"


def test_rotulo_sozinho_sem_dois_pontos_nao_puxa_o_vizinho():
    """No layout impresso (e no OCR que lê a coluna de rótulos inteira antes
    da de valores) "Observação" sozinho é só mais um rótulo do bloco: a linha
    de baixo é outro rótulo e não pode virar a descrição."""
    assert sr._descricao("Observação\nNome\nFULANO EXEMPLO\n", "SICOOB") is None
    # com ":" continua valendo o vizinho, como sempre foi
    assert sr._descricao("Observação:\nOBRA EXEMPLO QD 1\n", "SICOOB") == \
        "OBRA EXEMPLO QD 1"


def test_icone_do_pix_lido_como_aspas_nao_apaga_o_valor():
    """O OCR lê o ícone do Pix do Inter como aspas: "“ R$ 10.000,00". Nas
    fotos e escaneados de 37 comprovantes reais era a causa de TODOS os Pix
    do Inter que saíam "SEM VALOR"."""
    assert sr._valor("Pix enviado\n“ R$ 10.000,00\nSobre a transação\n") == "10.000,00"
    assert sr._valor("Pix enviado\n”. R$ 70,00\n") == "70,00"


def test_inter_lido_em_colunas_segue_a_ordem_dos_rotulos():
    """O OCR (psm 3) lê a coluna de rótulos inteira antes da de valores, e o
    texto cai no parser "impresso". Ele assumia "Quem pagou" antes de "Quem
    recebeu", mas o Pix enviado de hoje vem ao contrário: o aporte saía
    invertido. Texto SINTÉTICO, no formato que o OCR devolve."""
    t = """\
Pix enviado
“ R$ 2.500,00
Sobre a transação
Data do pagamento
Horário
ID da transação
Descrição
Quem recebeu
Nome
CPF/CNPJ
Instituição
Quem pagou
Nome
CPF/CNPJ
Instituição
Fale com a gente
Terça, 08/09/2026
17h50
E00000000202609081925AAAAAAAAAAA
APORTE CAPITAL
EMPRESA B EXEMPLO
00.000.000/0001-00
Banco Inter
EMPRESA A EXEMPLO LTDA
11.111.111/0001-11
Banco Inter S.A.
"""
    c = sr.campos(t)
    assert (c["pag"], c["dest"]) == ("EMPRESA A EXEMPLO LTDA", "EMPRESA B EXEMPLO")
    assert sr.nome_arquivo(c) == "2500,00 - EMPRESA A EXEMPLO PARA EMPRESA B EXEMPLO - 08-09"


def test_observacao_do_sicoob_em_duas_linhas():
    """A observação longa do Sicoob quebra em duas linhas com o rótulo
    CENTRADO entre elas — uma acima, outra abaixo. Assim o pdfplumber e o
    OCR a devolvem, e o convênio saía "SEM DESCRICAO" (7 dos 368 reais)."""
    t = """\
SICOOB - SISTEMA DE COOPERATIVAS DE CRÉDITO DO BRASIL
DE PAGAMENTO DE CONVÊNIO
Convênio AGUA EXEMPLO GO
Data do pagamento 01/09/2026
Valor total R$ 54,32
Autenticação AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE
RESIDENCIAL EXEMPLO QD 9 LT 1 UC 1234567-8 REF
Observação
AGO 2026
OUVIDORIA SICOOB: 08007250996
"""
    assert sr.campos(t)["desc"] == "RESIDENCIAL EXEMPLO QD 9 LT 1 UC 1234567-8 REF AGO 2026"
    # vizinha que é outro campo não é continuação: aí não inventa nada
    assert sr._descricao("Situação Efetivado\nObservação\nAutenticação X\n",
                         "SICOOB") is None


def test_transferencia_lida_por_ocr_com_linhas_em_branco():
    """O OCR põe uma linha em branco entre os campos, e a "Conta" do bloco
    Crédito caía fora das 3 linhas olhadas."""
    t = ("SICOOB\nCOMPROVANTE DE TRANSFERÊNCIA\n\nData do lançamento 09/09/2026\n\n"
         "Valor R$ 1.234,56\n\nDébito\n\nCooperativa 0000-0 / SICOOB EXEMPLO\n\n"
         "Conta 00.000-0 / EMPRESA EXEMPLO LTDA\nCrédito\n\n"
         "Cooperativa 1111-1 / SICOOB OUTRO\n\nConta 11.111-1 / FORNECEDOR FICTICIO\n")
    assert sr.nome_arquivo(sr.campos(t)) == "1234,56 - FORNECEDOR FICTICIO - 09-09"
    # o psm 6 do Tesseract às vezes nem lê o cabeçalho "COMPROVANTE DE
    # TRANSFERÊNCIA": os blocos Débito/Crédito bastam
    sem_cabecalho = t.replace("COMPROVANTE DE TRANSFERÊNCIA\n", "")
    assert sr.nome_arquivo(sr.campos(sem_cabecalho)) == \
        "1234,56 - FORNECEDOR FICTICIO - 09-09"


def test_centro_de_custo_estragado_pelo_ocr():
    """O OCR come o espaço do lote ("12BLT"), lê o O do OC como zero e o C
    como € ("0€ 1234") e cola a sigla no número ("AB12"). Sem o "OC 1234" o
    matcher perde a OC, que é o sinal mais forte do casamento."""
    from anexar import matcher
    c = dict(banco="INTER", tipo="PIX", valor="4.321,00", data="01/01/2026",
             desc="AB12 QD 12BLT 07 0€ 1234", pag=None, dest="FULANO EXEMPLO")
    nome = sr.nome_arquivo(c)
    assert nome == "4321,00 - AB 12 QD 12B LT 07 OC 1234 - 01-01"
    assert matcher.parse_pdf(nome + ".pdf")["ocs"] == {"1234"}
    assert sr._corrigir_codigo_ocr("RESIDENCIAL QD 1 LT 2 0C 5678") == \
        "RESIDENCIAL QD 1 LT 2 OC 5678"
    # o Q do QD lido como G ou O (o psm 6 do Tesseract faz isso)
    assert sr._corrigir_codigo_ocr("RESIDENCIAL 9 GD 12B LT 05") == "RESIDENCIAL 9 QD 12B LT 05"
    assert sr._corrigir_codigo_ocr("RESIDENCIAL 9 OD 12B LT 10") == "RESIDENCIAL 9 QD 12B LT 10"
    # sem cara de centro de custo, não mexe
    for intocado in ("ADM - SALARIO", "CONSULTORIA 0C 1234", "APORTE CAPITAL"):
        assert sr._corrigir_codigo_ocr(intocado) == intocado


def test_recebedor_de_tres_letras_nao_perde_para_o_horario():
    """Há recebedor com nome de três letras ("Ivo"): a regra antiga (mais de 4
    caracteres) pulava o nome e pegava a linha de cima — o horário ou o
    identificador da transação. Texto SINTÉTICO, como o OCR o devolve."""
    t = """\
Pix enviado
“ R$ 654,32
Sobre a transação
Data do pagamento
Horário
Quem recebeu
Nome
CPF/CNPJ
Quem pagou
Nome
CPF/CNPJ
Quinta, 01/01/2026
10h00
a0000b000€c000000000d0000e000000f
Ivo
00.000.000/0001-00
EMPRESA EXEMPLO LTDA
11.111.111/0001-11
"""
    c = sr.campos(t)
    assert c["dest"] == "Ivo"
    assert sr.nome_arquivo(c) == "654,32 - Ivo - 01-01"
    # e quando o OCR perde o nome, a linha de cima é a data — que não é nome
    assert not sr._serve_de_nome("Quinta, 01/01/2026")
    assert not sr._serve_de_nome("10h00")


def test_aporte_sem_pagador_fica_com_a_descricao():
    """Faltando quem pagou, o miolo caía no recebedor e a descrição sumia:
    13 Pix do Inter com "APORTE CAPITAL" saíram só com o nome de quem
    recebeu. A descrição manda; o recebedor só entra para desempatar."""
    c = dict(banco="INTER", tipo="PIX", valor="1.000,00", data="31/07/2026",
             desc="APORTE CAPITAL", pag=None, dest="EMPRESA B LTDA")
    assert sr.nome_arquivo(c) == "1000,00 - APORTE CAPITAL - 31-07"
    assert sr.nome_arquivo(c, com_recebedor=True) == \
        "1000,00 - APORTE CAPITAL - EMPRESA B - 31-07"
    # sem recebedor também
    assert sr.nome_arquivo(dict(c, dest=None)) == "1000,00 - APORTE CAPITAL - 31-07"
    # com os dois lados continua "PAGADOR PARA RECEBEDOR"
    assert sr.nome_arquivo(dict(c, pag="EMPRESA A LTDA")) == \
        "1000,00 - EMPRESA A PARA EMPRESA B - 31-07"


def test_ltda_na_segunda_linha_nao_vira_o_recebedor():
    """No Pix impresso o nome longo quebra em duas linhas, e a de baixo é só
    "LTDA" ou "SPE". Com três letras bastando, ela virava o recebedor, o
    `_limpar_empresa` a apagava e o arquivo saía "SEM DESCRICAO". Texto
    SINTÉTICO, como o OCR o devolve."""
    t = """\
Pix enviado
R$ 500,00
Sobre a transação
Data do pagamento
Horário
Quem recebeu
Nome
CPF/CNPJ
Quem pagou
Nome
CPF/CNPJ
Segunda, 07/09/2026
10h15
a0000b000€c000000000d0000e000000f
FORNECEDOR EXEMPLO
LTDA
00.000.000/0001-00
EMPRESA PAGADORA EXEMPLO
SPE
11.111.111/0001-11
"""
    c = sr.campos(t)
    assert c["dest"] == "FORNECEDOR EXEMPLO"
    assert sr.nome_arquivo(c) == "500,00 - FORNECEDOR EXEMPLO - 07-09"
    for sufixo in ("LTDA", "SPE", "S/A", "EIRELI"):
        assert not sr._serve_de_nome(sufixo)
    assert sr._serve_de_nome("Ivo")


def test_frase_com_o_rotulo_nao_vira_descricao():
    """Sem ":" o rótulo só vale na grafia do banco e sem "de/do/da" depois:
    "Histórico de pagamentos da conta" é uma frase do comprovante, e antes
    passava na frente da Observação verdadeira."""
    t = """\
COMPROVANTE DE PAGAMENTO
Histórico de pagamentos da conta
Valor: R$ 120,00
Data do pagamento: 05/09/2026
Observação: OBRA TESTE QD 99 LT 01 OC 456
"""
    c = sr.campos(t)
    assert c["desc"] == "OBRA TESTE QD 99 LT 01 OC 456"
    assert sr.nome_arquivo(c) == "120,00 - OBRA TESTE QD 99 LT 01 OC 456 - 05-09"
    assert sr._descricao("Descrição do pagamento\nObservação: OBRA QD 1 LT 2",
                         "OUTRO") == "OBRA QD 1 LT 2"
    # o caso que motivou o "sem dois-pontos" continua valendo
    assert sr._descricao("Situação Efetivado\nObservação OBRA QD 1 LT 2\n",
                         "SICOOB") == "OBRA QD 1 LT 2"


def test_lt_colado_so_se_separa_depois_de_numero():
    """ "VOLT 220" é palavra: o conserto do "12BLT" a partia em "VO LT 220"."""
    assert sr._corrigir_codigo_ocr("VOLT 220 QD 01 LT 02") == "VOLT 220 QD 01 LT 02"
    assert sr._corrigir_codigo_ocr("OBRA QD 12BLT 07") == "OBRA QD 12B LT 07"
    assert sr._corrigir_codigo_ocr("OBRA QD 18LT8") == "OBRA QD 18 LT 8"
