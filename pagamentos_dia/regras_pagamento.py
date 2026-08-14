# -*- coding: utf-8 -*-
"""Quem NÃO entra na planilha do dia, e por quê.

O relatório nasceu listando tudo que o ERP devolvia. Quem confere descobriu na
prática que parte daquilo nunca vira pagamento: lançamento de R$ 1,00 que só
segura uma recorrência, título marcado como boleto que não tem boleto nenhum
anexado, fornecedor que só recebe por reembolso. Cada uma dessas linhas custa
uma conferência manual que sempre termina em "esta aqui não é para pagar".

REGRA DA CASA: OMITIR NÃO É APAGAR
----------------------------------
Nada some sem deixar rastro. `montar_registros` devolve as linhas omitidas
junto com o MOTIVO, e elas viram a aba "NÃO ENTRARAM" no fim do arquivo. Se
uma regra daqui errar, o erro fica visível na mesma planilha — em vez de o
pagamento simplesmente não existir mais para quem confere.

O QUE É REGRA E O QUE É CADASTRO
--------------------------------
Os CRITÉRIOS moram aqui (valor simbólico, falta de forma de pagar). Os NOMES
— fornecedor que só recebe por reembolso, pessoa cujo pagamento tem de ser
confirmado antes — moram em `regras_fornecedor.json` e `confirmar_antes.json`,
ao lado do exe e FORA do repositório, que é público. Sem os arquivos o app
funciona igual, só sem as regras: ausência de cadastro não pode virar erro.

Mora aqui também o TIPO da chave Pix (`tipo_de_chave_pix`), que é uma regra
pelo mesmo motivo: ele decide se a linha está pronta ou se precisa de
confirmação humana. O ERP não tem esse campo, e o que não se sabe não se
chuta.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util


#: Valores que o ERP usa como marcador, nunca como pagamento. A lista é
#: EXATA, e não um piso: "abaixo de R$ 5,00" descartaria calado o dia em que
#: aparecer uma taxa de R$ 3,00 de verdade. Marcador novo é uma linha aqui.
VALORES_SIMBOLICOS = (1.00, 0.01)

#: Tolerância da comparação de dinheiro vindo de float do JSON.
_EPS = 0.0001


def valor_simbolico(valor: float) -> bool:
    return any(abs(float(valor or 0) - v) < _EPS for v in VALORES_SIMBOLICOS)


def documento_contradiz_valor(valor: float, valor_documento: float | None,
                              tolerancia: float = 0.01) -> bool:
    """O boleto anexado codifica um valor DIFERENTE do que o ERP mandou pagar.

    O código de barras carrega o valor em centavos e é conferido por dígito
    verificador: quando ele discorda do lançamento, quem está errado é o
    lançamento, não o boleto.
    """
    if not valor_documento or not valor:
        return False
    return abs(float(valor_documento) - float(valor)) > tolerancia


def pagamento_parcial(valor: float, ja_pago: float, valor_documento: float | None,
                      tolerancia: float = 0.01) -> bool:
    """O boleto é do valor CHEIO e o lançamento traz só o que falta.

    Não é divergência: é a segunda parcela de um título que o ERP aceita
    quitar em vezes. Sem distinguir os dois casos, toda segunda parcela com
    boleto anexado viraria "ATENÇÃO — valor do boleto diverge", e o alarme
    que existe para pegar valor errado morreria afogado nos legítimos.
    """
    if not ja_pago or not valor_documento or not valor:
        return False
    return abs(float(valor_documento) - (float(valor) + float(ja_pago))) <= tolerancia


# --------------------------------------------------------------------------
# Cadastro (fora do repositório)
# --------------------------------------------------------------------------
ARQ_FORNECEDORES = "regras_fornecedor.json"
ARQ_CONFIRMAR = "confirmar_antes.json"


def _ler_json(nome: str, base: Path | None = None):
    """Cadastro ausente ou ilegível não pode derrubar o relatório inteiro."""
    try:
        caminho = (base or util.pasta_base()) / nome
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return None


def carregar_fornecedores(base: Path | None = None) -> dict:
    """{nome do fornecedor: {"so_com_reembolso": bool, "conferir_endereco": bool,
    "oc_no_documento": bool}}.

    O nome é o do cadastro do ERP, digitado por gente: a comparação usa
    `util.norm_espaco` e casa por PEDAÇO, como o resto do app faz com nome de
    conta. "VIDRACARIA MODELO" acha "VIDRACARIA MODELO COMERCIO LTDA".
    """
    dados = _ler_json(ARQ_FORNECEDORES, base)
    if not isinstance(dados, dict):
        return {}
    regras = {}
    for nome, regra in dados.items():
        if isinstance(regra, dict):
            regras[util.norm_espaco(nome)] = {k: bool(v) for k, v in regra.items()}
    return regras


def carregar_confirmar(base: Path | None = None) -> list[str]:
    """Nomes cujo pagamento tem de ser confirmado antes de gerar a planilha.

    É CPF/nome de gente da família — por isso arquivo, e não código.
    """
    dados = _ler_json(ARQ_CONFIRMAR, base)
    if isinstance(dados, dict):                       # {"nomes": [...]}
        dados = dados.get("nomes")
    if not isinstance(dados, list):
        return []
    return [str(n) for n in dados if str(n).strip()]


def regra_do_fornecedor(favorecido: str, regras: dict) -> dict:
    """A regra cadastrada para este favorecido, ou {} se não houver.

    Casa por pedaço e devolve a MAIS ESPECÍFICA (o nome cadastrado mais
    longo), para "SERVIÇOS MODELO" e "SERVIÇOS MODELO PINTURAS" poderem ter regras
    diferentes sem uma engolir a outra.
    """
    alvo = util.norm_espaco(favorecido)
    if not alvo:
        return {}
    achadas = [(nome, regra) for nome, regra in regras.items() if nome and nome in alvo]
    if not achadas:
        return {}
    return max(achadas, key=lambda kv: len(kv[0]))[1]


def exige_confirmacao(favorecido: str, nomes) -> bool:
    alvo = util.norm_espaco(favorecido)
    return bool(alvo) and any(util.norm_espaco(n) in alvo for n in nomes if str(n).strip())


# --------------------------------------------------------------------------
# Quem não entra
# --------------------------------------------------------------------------
#: Motivos, na ordem em que são testados. Texto vai para a aba NÃO ENTRARAM.
MOTIVO_SIMBOLICO = "valor simbólico (marcador de recorrência, não é pagamento)"
MOTIVO_REEMBOLSO = "fornecedor só entra com aviso de reembolso anexado"
MOTIVO_SEM_PAGAR = "sem forma de pagar (nem boleto anexado, nem chave Pix)"
MOTIVO_NAO_CONFIRMADO = "não confirmado na janela antes de gerar"


def motivo_omissao(valor: float, favorecido: str, dados: str,
                   tem_documento: bool, regras: dict,
                   valor_documento: float | None = None) -> str:
    """Por que esta linha NÃO entra — "" quando ela entra.

    `dados` é o que já se conseguiu apurar como forma de pagar (linha
    digitável, chave Pix, copia-e-cola). Vazio aqui significa que TODAS as
    tentativas já falharam: a linha digitável do boleto, o OCR do boleto em
    imagem, a chave do aviso de reembolso e a chave do cadastro. Por isso
    este teste vem por último — omitir por "sem forma de pagar" antes de
    tentar todas seria descartar pagamento que dava para fazer.

    `valor_documento` é o valor lido do código de barras, quando há um.
    """
    # O boleto MANDA no valor simbólico. No arquivo de 08 a 10/08/2026 havia
    # uma conta da Equatorial lançada como R$ 1,00 cujo código de barras
    # anexado dizia R$ 56,24 — conta de luz de verdade, com o valor errado no
    # ERP. Omitir por "marcador de recorrência" apagaria a conta em vez de
    # denunciar o lançamento, e ninguém sentiria falta antes do vencimento.
    # Contradisse, a linha FICA: quem confere vê os dois valores e corrige.
    if valor_simbolico(valor) and not documento_contradiz_valor(valor, valor_documento):
        return MOTIVO_SIMBOLICO

    regra = regra_do_fornecedor(favorecido, regras)
    if regra.get("so_com_reembolso") and not tem_documento:
        return MOTIVO_REEMBOLSO

    # "Não tem chave para pagar E não tem aviso para pagar" — as duas coisas.
    # Havendo documento anexado (boleto que virou foto, aviso de reembolso), a
    # linha fica: alguém abre o anexo e digita. Sem documento nenhum não há o
    # que digitar, e a linha só custa uma conferência que termina em nada.
    if not dados and not tem_documento:
        return MOTIVO_SEM_PAGAR
    return ""


# --------------------------------------------------------------------------
# Tipo da chave Pix
# --------------------------------------------------------------------------
#: Como a Febraban nomeia o tipo da chave no segmento B da remessa. "" é o
#: sexto estado, e o mais importante: NÃO SEI.
CHAVE_CNPJ = "CNPJ"
CHAVE_CPF = "CPF"
CHAVE_TELEFONE = "TELEFONE"
CHAVE_EMAIL = "EMAIL"
CHAVE_ALEATORIA = "ALEATORIA"

#: O tipo que a pessoa DECLAROU ao digitar. Medido nos 116 lançamentos com
#: `paidToBankAccount` preenchido entre 08 e 12/08/2026: 75 declaram
#: ("PIX CNPJ" 65 vezes, "PIX CELULAR" 7, "PIX CPF" 3). É a melhor fonte que
#: existe, porque o ERP não tem campo de tipo.
_TIPO_DECLARADO = (
    (re.compile(r"\bCNPJ\b", re.I), CHAVE_CNPJ),
    (re.compile(r"\bCPF\b", re.I), CHAVE_CPF),
    (re.compile(r"\b(?:CELULAR|TELEFONE|FONE|WHATS\w*)\b", re.I), CHAVE_TELEFONE),
    (re.compile(r"\bE-?MAIL\b", re.I), CHAVE_EMAIL),
    (re.compile(r"\bALEAT\w*\b", re.I), CHAVE_ALEATORIA),
)

#: Formatos que se denunciam sozinhos. A PONTUAÇÃO é quem decide entre CPF e
#: celular: "123.456.789-09" é CPF (ninguém escreve telefone com pontos), e
#: "(62) 91234-5678" é celular. Sem pontuação, os mesmos 11 dígitos servem
#: para os dois.
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_ALEATORIA = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_CNPJ_PONTUADO = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")
_CPF_PONTUADO = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
_TELEFONE_PONTUADO = re.compile(
    r"(?:\(\d{2}\)\s*|\b\d{2}\s+)9?\d{4}[-\s]\d{4}\b|\+55\s*\d{2}\s*9?\d{8}\b")


def tipo_de_chave_pix(texto: str) -> str:
    """O TIPO da chave Pix: CNPJ, CPF, TELEFONE, EMAIL, ALEATORIA — ou "".

    O ERP **não tem campo de tipo**: a chave chega dentro de um texto livre
    (`paidToBankAccount`, e o mesmo texto no `bankAccount` do cadastro),
    escrito à mão. Duas fontes, nesta ordem: o que a pessoa declarou
    ("PIX CNPJ: ...") e, onde ninguém declarou, o formato INEQUÍVOCO.

    Onze dígitos crus NÃO são decididos aqui. CPF e celular têm os dois onze
    dígitos, e escolher entre eles é escolher para quem o dinheiro vai —
    devolve "", e quem confere responde. Recusar é a única falha aceitável
    numa função que alimenta pagamento.
    """
    t = str(texto or "")
    if not t.strip():
        return ""
    for padrao, tipo in _TIPO_DECLARADO:
        if padrao.search(t):
            return tipo
    if _EMAIL.search(t):
        return CHAVE_EMAIL
    if _ALEATORIA.search(t):
        return CHAVE_ALEATORIA
    if _CNPJ_PONTUADO.search(t):
        return CHAVE_CNPJ
    if _CPF_PONTUADO.search(t):
        return CHAVE_CPF
    if _TELEFONE_PONTUADO.search(t):
        return CHAVE_TELEFONE
    return CHAVE_CNPJ if len(re.sub(r"\D", "", t)) == 14 else ""


def chave_pix_ambigua(texto: str, chave: str) -> bool:
    """Tem chave, mas ninguém sabe dizer de que tipo ela é.

    É o aviso que separa "posso montar o pagamento" de "preciso perguntar":
    ~30 dos 116 lançamentos do período caem aqui ("CHAVE PIX", "PIX", "PX",
    sem o tipo). Só alarma quando HÁ chave — chave nenhuma já é outro
    problema, com outro recado.
    """
    return bool(str(chave or "").strip()) and not tipo_de_chave_pix(texto or chave)


# --------------------------------------------------------------------------
# Observação que redireciona o pagamento
# --------------------------------------------------------------------------
#: Verbo de PAGAR, não de providenciar. "SOLICITAR FATURA PARA FULANA" fala
#: de nota, não de dinheiro — e é observação de verdade, das que aparecem em
#: 9% das linhas. Confundir as duas transformaria a trava em ruído diário.
_VERBO_DE_PAGAR = re.compile(
    r"\b(pagar|pague|paga|transferir|transfira|transfere|depositar|deposite|"
    r"enviar|envie|mandar)\b", re.I)

#: Valor em reais escrito por gente: "8.000,00", "R$ 2.500,00".
_VALOR_EM_REAIS = re.compile(r"(?:R\$\s*)?\b\d{1,3}(?:\.\d{3})*,\d{2}\b")


def observacao_redireciona_pagamento(comentario: str) -> bool:
    """A observação manda pagar OUTRA pessoa (ou parte para outra).

    O caso real, em 28/07/2026: um título de R$ 14.492 de um fornecedor cuja
    observação dizia "PAGAR 8.000,00 PARA <fulano> – PIX <chave> / APENAS A
    DIFERENÇA AO <beltrano>". O favorecido do lançamento é o FORNECEDOR; o
    dinheiro foi para duas pessoas físicas, e isso não existe em campo nenhum
    do ERP — nem em `paidTo`, nem em `paids`, que sequer tem favorecido.

    Enquanto quem paga é gente, a observação aparece na coluna Obs e alguém
    lê. Numa remessa não há quem leia: a mesma linha mandaria o dinheiro para
    a chave do cadastro do fornecedor — pessoa errada, valor certo, sem erro
    na tela e sem volta.

    Dois sinais, e é preciso um deles:
      - uma CHAVE PIX escrita na observação (a chave de quem vai receber);
      - um VERBO de pagar junto de um VALOR ("PAGAR 8.000,00").

    Nenhum dos dois aparece nas observações comuns ("carta de correção
    solicitada", "solicitar fatura para <fulana>", "a nota será encaminhada").
    """
    t = str(comentario or "")
    if not t.strip():
        return False
    if tipo_de_chave_pix(t):
        return True
    return bool(_VERBO_DE_PAGAR.search(t) and _VALOR_EM_REAIS.search(t))


def precisa_de_olhar_humano(comentario: str, favorecido: str,
                            regras: dict) -> str:
    """Por que esta linha não pode ser paga sozinha — "" quando pode.

    Duas portas, porque falham de jeitos diferentes: o TEXTO pega o caso em
    qualquer fornecedor, inclusive um novo; o CADASTRO
    (`"confirmar_sempre": true` em `regras_fornecedor.json`) pega o
    fornecedor conhecido mesmo no dia em que ninguém escreveu a observação —
    que é justamente o dia em que o texto não salva ninguém.
    """
    if observacao_redireciona_pagamento(comentario):
        return "a observação manda pagar outra pessoa"
    if regra_do_fornecedor(favorecido, regras).get("confirmar_sempre"):
        return "fornecedor marcado para confirmar sempre"
    return ""


# --------------------------------------------------------------------------
# "OC 1234" no campo Número do documento
# --------------------------------------------------------------------------
_OC_COMO_DOCUMENTO = re.compile(r"^\s*OC\s*[:\-]?\s*(\d{2,7})\s*$", re.I)


def oc_no_documento(document_number: str) -> str:
    """O número da OC quando o fornecedor a escreveu no campo do documento.

    Há fornecedor que preenche "OC5928" ali; o relatório lia aquilo como
    número de nota e a planilha saía com "NF 5928 OC 5928" — o mesmo número
    anunciado como duas coisas diferentes, e a conferência de NF virava ruído.
    """
    m = _OC_COMO_DOCUMENTO.match(str(document_number or ""))
    return m.group(1) if m else ""


def documento_e_a_oc(document_number: str, oc: str) -> bool:
    """True quando o "número do documento" é, na verdade, a OC.

    Dois jeitos de acontecer: escrito com o prefixo ("OC5928") ou só o
    número, igual ao da ordem de compra que veio do overview.
    """
    doc = str(document_number or "").strip()
    if not doc:
        return False
    if oc_no_documento(doc):
        return True
    return bool(oc) and doc.lstrip("0") == str(oc).strip().lstrip("0")


# --------------------------------------------------------------------------
# CPF/CNPJ: os dígitos verificadores
# --------------------------------------------------------------------------
# Moram AQUI, e não no `remessa_dia`, porque os dois lados precisam da mesma
# resposta: a remessa, para saber de quem é o documento do segmento B; e o
# relatório, para não exibir uma chave Pix que o OCR leu errado. Estavam só no
# lado da remessa, e por isso a planilha aceitava qualquer coisa com cara de
# número — a mesma família do "8 lido como B" que o `ocr_boleto` já recusa.


def _dv_cpf(d: str) -> bool:
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for tamanho in (9, 10):
        soma = sum(int(d[i]) * (tamanho + 1 - i) for i in range(tamanho))
        resto = (soma * 10) % 11 % 10
        if resto != int(d[tamanho]):
            return False
    return True


#: Pesos do DV do CNPJ, do 2º dígito para trás. O 1º DV usa os 12 últimos;
#: o 2º, os 13. Escritos por extenso de propósito: a versão calculada saía
#: deslocada em uma posição e reprovava CNPJ legítimo em silêncio.
_PESOS_CNPJ = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


def _dv_cnpj(d: str) -> bool:
    if len(d) != 14 or len(set(d)) == 1:
        return False
    for tamanho in (12, 13):
        pesos = _PESOS_CNPJ[-tamanho:]
        soma = sum(int(d[i]) * pesos[i] for i in range(tamanho))
        resto = soma % 11
        if (0 if resto < 2 else 11 - resto) != int(d[tamanho]):
            return False
    return True


def documento_valido(valor) -> str:
    """Os dígitos, se forem um CPF ou CNPJ que fecha. Senão, "".

    Os dígitos verificadores não são preciosismo: sem eles, todo telefone de
    onze dígitos viraria "CPF encontrado" e o diagnóstico apontaria para o
    campo errado — que é exatamente o erro que ele existe para evitar.
    """
    if isinstance(valor, bool) or not isinstance(valor, (str, int)):
        return ""
    digitos = re.sub(r"\D", "", str(valor))
    return digitos if (_dv_cpf(digitos) or _dv_cnpj(digitos)) else ""
