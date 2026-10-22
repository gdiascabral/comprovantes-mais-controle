# -*- coding: utf-8 -*-
"""
HTML dos pagamentos do dia — **PROVISÓRIO**, até a remessa CNAB virar o
caminho do dia (pedido do dono em 11/09/2026).

Até aqui estes dois HTMLs eram gerados FORA do app, por um script solto que
relia o `.xlsx` do passo 2 e um JSON tirado do ERP à parte. Agora saem do
botão "Gerar HTML dos pagamentos" da aba Remessa/Retorno, do que a aba já tem
em memória — sem login e sem chamada nova ao ERP:

- **geral** (`pagamentos_<período>.html`): todas as contas do passo 2 num
  HTML só, com "Copiar" no dado de pagamento, no valor e na descrição, e a
  caixa "já paguei" que risca a linha. Sai do `self.resultado`
  (`relatorio.Resultado.contas`) — as MESMAS linhas das abas por conta da
  planilha;
- **pessoa física** (`pagamentos_pessoa_fisica_lancamento_<período>.html`):
  a conta/centro de custo PESSOA FISICA - APENAS LANÇAMENTO ("PF" para o
  dono — não é separação por CPF/CNPJ), com "Gerar PDF" no layout do
  "Relatório de Pagamentos por Vencimento" do Mais Controle. Sai da lista do
  passo 1 (`self.lancamentos`): a aba NÃO ENTRARAM não traz vencimento,
  categoria, nº do documento nem centro de custo, e a lista traz. Vem de lá
  também porque essa conta nasce DESMARCADA no passo 2 (é conta de ajuste) —
  tirar dela o HTML obrigaria a marcá-la só para isso.

Módulo puro: sem tkinter, sem rede, sem navegador. Quem chama é o
`pagamentos_frame._gerar_html_pagamentos`, na thread da interface — é disco
local e leva milissegundos.

**Como remover** quando a remessa assumir: apagar este arquivo, o
`modelos_html.py` e `tests/test_html_pagamentos.py`; no `pagamentos_frame.py`,
apagar o método `_gerar_html_pagamentos` e as linhas marcadas
"HTML provisório" (o import, o botão `b_html` e as duas que o acendem e
apagam); e o parágrafo do CLAUDE.md na entrada do `pagamentos_frame.py`.
"""
from __future__ import annotations

import base64
import json
import re
import unicodedata
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import NamedTuple

from . import modelos_html
from . import ocr_boleto
from . import regras_pagamento as regras
from . import relatorio

#: O nome da conta como o ERP escreve. A comparação é por `e_conta_pf`, sem
#: acento, caixa, espaço nem pontuação — o nome é digitado por gente.
CONTA_PF = "PESSOA FISICA - APENAS LANÇAMENTO"
_CHAVE_PF = "pessoafisicaapenaslancamento"

#: O logotipo do cabeçalho do PDF de pessoa física, procurado ao lado da
#: planilha e depois na pasta do app. O primeiro é o nome "oficial"; o
#: segundo é o que o script de fora já usava, e que a pasta do dono já tem.
NOMES_LOGO = ("logo_relatorio_pf.png", "logo_mais_controle.png")
#: O rodapé do PDF: uma linha por linha do arquivo (a 1ª sai em negrito).
#: Mora fora do repositório porque é nome, endereço e e-mail da empresa.
NOME_RODAPE = "rodape_relatorio_pf.txt"
_LOGO_MAX = 2_000_000
_RODAPE_MAX_LINHAS = 4

#: Prefixo do link de um lançamento (parcela) no Mais Controle. É cópia de
#: `anexar.config.MC_URL_LANCAMENTO` (o que `anexar/mc_api.py` usa para abrir
#: um lançamento): este módulo é puro e não importa o `anexar`, que puxa
#: `util`. Um teste confere que as duas continuam iguais.
URL_LANCAMENTO = "https://acessar.maiscontroleerp.com.br/#/payable-installments/"

SUBTITULO_GERAL = "vencimentos em aberto no Mais Controle - todas as contas"

#: Até quantos caracteres a descrição do HTML geral vai para o campo de
#: descrição do banco. O Inter aceita bem mais (dono, 14/09/2026), e só a
#: conta que diz INTER no nome leva 140. Todas as outras levam 100: no Sicoob
#: o campo deixou digitar 140, mas "vira e mexe ele limita", e um limite que
#: muda sem aviso é descoberto na hora de colar. O lado seguro é o curto —
#: com a regra ao contrário ("SICOOB no nome → 100"), a conta Sicoob cujo
#: nome não dissesse SICOOB levava 140, e o banco podia cortar justamente a
#: NF e a OC do fim. Quem aplica é `descricao_para_colar`, sem cortar NF nem OC.
LIMITE_DESCRICAO_INTER = 140
LIMITE_DESCRICAO = 100

_CENTAVO = Decimal("0.01")
_PLACEHOLDER = re.compile(r"__([A-Z][A-Z_]*[A-Z])__")


# --------------------------------------------------------------------------
# Texto e dinheiro
# --------------------------------------------------------------------------
def e_conta_pf(nome) -> bool:
    """A conta é a PESSOA FISICA - APENAS LANÇAMENTO?"""
    return re.sub(r"[^a-z0-9]", "", relatorio.chave(nome or "")) == _CHAVE_PF


def escapar(texto) -> str:
    """Texto para dentro do HTML. Escrito à mão (cinco trocas) para não
    trazer módulo novo para o exe — ver a regra de ouro do CLAUDE.md."""
    s = "" if texto is None else str(texto)
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def json_para_script(dado) -> str:
    """JSON que pode ir dentro de `<script>` sem fechá-lo.

    `<`, `>` e `&` viram escape unicode: um favorecido escrito
    `</script><script>…` deixa de ser tag e continua sendo o mesmo texto
    quando o navegador lê o JSON."""
    return (json.dumps(dado, ensure_ascii=False)
            .replace("&", "\\u0026").replace("<", "\\u003c")
            .replace(">", "\\u003e").replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


def dinheiro(valor) -> Decimal:
    """O valor em Decimal, com duas casas. O ERP manda float; a soma é aqui."""
    try:
        d = valor if isinstance(valor, Decimal) else Decimal(
            str(valor if valor not in (None, "") else 0))
        return d.quantize(_CENTAVO, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def centavos(valor) -> int:
    """O que viaja para o navegador: inteiro, que soma sem perder centavo."""
    return int(dinheiro(valor) * 100)


def valor_para_colar(valor) -> str:
    """`1234,56` — sem milhar, que é como o campo de valor do banco aceita."""
    return f"{dinheiro(valor):.2f}".replace(".", ",")


def reais(valor) -> str:
    """`R$ 1.234,56`, pelo formatador de sempre da aba."""
    return relatorio.brl(dinheiro(valor))


def para_colar(texto) -> str:
    """Descrição e favorecido como o campo de descrição do banco aceita: sem
    acento e só letra, número, espaço e `. , / -` — o mesmo corte que o
    script de fora fazia."""
    s = relatorio.sem_acento(texto or "").replace("\n", " ")
    s = re.sub(r"[^A-Za-z0-9 .,/\-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


#: Quem recebe o reembolso não é informação para o extrato do banco (dono,
#: 14/09/2026). "(Reembolso Fulano)" sai inteiro; fora de parênteses sai a
#: palavra "reembolso" e as palavras só de letras depois dela — o nome —, até
#: uma parada e no máximo `_MAX_PALAVRAS_DE_QUEM`. Tirar "até o próximo
#: separador" apagava o que vinha depois ("Reembolso material QD 98 LT 97
#: casa 2" perdia o lote); o teto de três deixava o fim de um nome comprido
#: ("Reembolso Fulana Sicrana de Tal" sobrava "Tal").
_REEMBOLSO_ENTRE_PARENTESES = re.compile(r"\([^()]*reembols[^()]*\)", re.I)
_MAX_PALAVRAS_DE_QUEM = 5
#: As PARADAS do filtro do reembolso, numa lista só: palavras que abrem centro
#: de custo ou imóvel (o que vem depois é o lote) e rótulos de documento (o
#: que vem depois é o número, e o rótulo "NF"/"OC" é o que o Anexar lê — sem
#: ele, "Reembolso NF 1234 material" virava "1234 material").
PARADAS_DO_REEMBOLSO = frozenset({
    "QD", "LT", "TB", "RR", "RPB", "CASA", "CS", "LOTE", "QUADRA",
    "NF", "NFE", "NFS", "OC", "OS"})
_PEDACOS = re.compile(r"[A-Za-z0-9]+|\s+|[^A-Za-z0-9\s]")
_SO_LETRAS = re.compile(r"[A-Za-z]+")


def _sem_reembolso(s: str) -> str:
    """O texto (já sem acento) sem a menção de reembolso.

    Depois de "reembolso" saem as palavras só de letras, no máximo cinco;
    para antes disso em palavra com dígito, numa das `PARADAS_DO_REEMBOLSO`
    e em pontuação — "REEMBOLSO FULANO - CIMENTO" guarda o "CIMENTO". O
    separador colado na palavra ("Reembolso: Fulano") vai junto."""
    pedacos = _PEDACOS.findall(_REEMBOLSO_ENTRE_PARENTESES.sub(" ", s))

    def proximo(i):
        while i < len(pedacos) and pedacos[i].isspace():
            i += 1
        return i

    saida, i = [], 0
    while i < len(pedacos):
        if not pedacos[i].casefold().startswith("reembols"):
            saida.append(pedacos[i])
            i += 1
            continue
        i += 1
        j = proximo(i)
        if j < len(pedacos) and pedacos[j] in (":", "-", "–", "—"):
            i = j + 1
        for _ in range(_MAX_PALAVRAS_DE_QUEM):
            j = proximo(i)
            if (j >= len(pedacos) or not _SO_LETRAS.fullmatch(pedacos[j])
                    or pedacos[j].upper() in PARADAS_DO_REEMBOLSO):
                break
            i = j + 1
        saida.append(" ")
    return "".join(saida)


def _e_inter(conta) -> bool:
    """A conta é do Inter? INTER como palavra inteira: "CONTA INTERNA" não é
    do Inter e fica no lado seguro. Com SICOOB no nome, é do Sicoob."""
    nome = relatorio.chave(conta or "")
    return (bool(re.search(r"\binter\b", nome))
            and not re.search(r"\bsicoob\b", nome))


def limite_da_descricao(conta) -> int:
    """Quantos caracteres cabem na descrição do banco desta conta."""
    return LIMITE_DESCRICAO_INTER if _e_inter(conta) else LIMITE_DESCRICAO


def _sem_hifen(palavras) -> list[str]:
    """O hífen colado entre dígitos vira " E ": "LT 10-11" sai "LT 10 E 11".
    O Sicoob não aceita "-" na descrição (dono, 14/10/2026), e partir em
    "LT 10 11" faria o Anexar ler "LT 10" — "10 E 11" é o que o casamento lê
    como "10-11" (`anexar.matcher._com_hifen`).

    "10 E 11" continua UMA palavra: o corte por tamanho (`_que_cabem`) leva
    ou deixa a faixa inteira. Partida em três, cabia "LT 10" — outro lote."""
    return [" E ".join(x for x in p.split("-") if x) for p in palavras]


#: Uma palavra do banco: letras e dígitos, mais o hífen COLADO entre dois
#: dígitos. "LT 10-11" partido em "LT 10 11" faz o casamento do Anexar ler
#: "LT 10" e anexar o comprovante no lote errado; o hífen que separa palavras
#: ("ESCRITORIO - X", "ESCRITORIO-X") continua saindo.
_PALAVRA = re.compile(r"(?:[A-Za-z0-9]|(?<=\d)-(?=\d))+")


def _palavras(texto, tirar_reembolso: bool = True) -> list[str]:
    """As palavras que vão ao banco: sem acento, sem menção de reembolso e só
    letra, número e o hífen entre dígitos — todo o resto é separador.

    O centro de custo passa com `tirar_reembolso=False`: ele é o nome do
    imóvel ou da obra no cadastro, não recado de quem lançou, e é por ele que
    o Anexar casa o comprovante."""
    s = relatorio.sem_acento(str(texto or ""))
    if tirar_reembolso:
        s = _sem_reembolso(s)
    return _PALAVRA.findall(s)


#: O ponto de milhar dentro do número da NF ou da OC ("1.234").
_PONTO_ENTRE_DIGITOS = re.compile(r"(?<=\d)\.(?=\d)")


def _palavras_do_numero(texto) -> list[str]:
    """As palavras do nº da NF ou da OC.

    Só o PONTO entre dígitos some sem virar espaço: "1.234" partido em
    "1 234" deixa de bater com a nota e com o casamento do Anexar. Barra e
    hífen entre dígitos separam números — "5678/5679" são duas notas, e
    juntá-las dava "56785679", um número que não existe —, então aqui o hífen
    colado também vira espaço, ao contrário do centro de custo."""
    s = _PONTO_ENTRE_DIGITOS.sub("", relatorio.sem_acento(str(texto or "")))
    return [p for palavra in _palavras(s) for p in palavra.split("-") if p]


def _que_cabem(palavras, espaco: int) -> list[str]:
    """As primeiras `palavras` que, juntas por espaço, cabem em `espaco`.
    Nunca corta palavra ao meio: um "LT 12" que vira "LT 1" aponta para outro
    lote, e a palavra ausente não engana ninguém."""
    saida, usado = [], 0
    for p in palavras:
        custo = len(p) + (1 if saida else 0)
        if usado + custo > espaco:
            break
        saida.append(p)
        usado += custo
    return saida


def _sem_sequencia(palavras, sequencia) -> list[str]:
    """`palavras` sem as ocorrências da `sequencia` (palavras inteiras, sem
    diferenciar caixa): o número do documento que a descrição já traz não se
    repete."""
    n = len(sequencia)
    alvo = [p.casefold() for p in sequencia]
    saida, i = [], 0
    while i < len(palavras):
        if n and [p.casefold() for p in palavras[i:i + n]] == alvo:
            i += n
            relatorio.tira_rotulo_de_nota(saida)
            continue
        saida.append(palavras[i])
        i += 1
    return saida


def descricao_para_colar(registro, conta, limite: int | None = None) -> str:
    """A descrição que o botão "Copiar" do HTML geral põe no campo do banco.

    Não é a `descricao` da planilha: aquela é para conferir, esta é para o
    extrato. Sai das peças soltas que `relatorio.partes_no_registro` pôs na
    linha — nunca da frase pronta, que teria de ser reparseada. As regras são
    do dono (14/09/2026):

    - o centro de custo sempre NA FRENTE: é por ele que o Anexar casa o
      comprovante com o lançamento;
    - NF e OC → "CC NF x OC y"; só OC → "CC OC y"; só NF → "CC NF x"; nenhuma
      das duas → "CC " + a descrição do lançamento, ou "CC C x M y" quando ela
      é de medição de mão de obra (a forma curta que a planilha já mostra);
    - água e luz continuam como na planilha (CC + descrição + OC): ali o
      "número da NF" é o da fatura e não identifica nada;
    - **documento sem OC** leva também a descrição do lançamento, entre o
      centro de custo e o documento: "CC desc NF x" / "CC desc x". Com OC
      nada muda; a descrição é a primeira a ser cortada e o documento nunca;
      número que a descrição já traz como palavra inteira não se repete
      (dono, 01/10/2026);
    - **"NF" só com nota fiscal anexada** no lançamento (`nf_anexada`): nem
      todo número de documento é nota (o da prefeitura, por exemplo). Sem a
      NF anexada, ou sem a chave no registro, o número fica sozinho: "CC x OC
      y" ou "CC x" (dono, 01/10/2026);
    - **ficha de arrecadação** (tributo, taxa, órgão público —
      `ocr_boleto.eh_arrecadacao`) também não rotula "NF": ela não tem
      cedente, então o campo do documento é só uma referência (o nº do DARF
      da Receita Federal, por exemplo), e "NF x" inventaria uma nota que não
      existe. O número continua na descrição, sozinho: "CC x OC y" ou "CC x"
      (dono, 22/09/2026);
    - sem menção de reembolso, sem acento e sem caractere especial (o hífen
      que separa palavras incluído; o COLADO entre dígitos, como em
      "LT 10-11", fica só no Inter — fora dele vira "LT 10 E 11", porque o
      Sicoob não aceita "-", dono 14/10/2026), e sem repetir o centro de
      custo que a descrição já traz; no
      nº da NF e da OC só o ponto entre dígitos some sem virar espaço
      ("1.234" é "1234", não "1 234"), e barra ou hífen separam números
      ("5678/5679" é "5678 5679");
    - no tamanho do banco (`limite_da_descricao`), cortando em fronteira de
      palavra. A NF e a OC NUNCA são cortadas — são o que liga o pagamento ao
      documento; quem cede é a descrição do lançamento e, se ainda não
      couber, o centro de custo.

    `limite` troca o tamanho do banco (`limite_da_descricao(conta)`): a
    remessa CNAB usa o do campo do layout (38 no Pix, 30 no boleto) e passa
    por esta MESMA função, para o documento nunca ser cortado lá também.
    """
    r = registro or {}
    editada = str(r.get("descricao_editada") or "").strip()
    if editada:
        # Escrita pelo dono na tela "Pagamentos do dia" (entrega 2). Vai como
        # ele escreveu, só limpa e no tamanho do banco; a tela avisa antes de
        # gravar se ela perdeu o centro de custo ou o documento no fim
        # (`tela_do_dia.conferencia.aviso_de_casamento`). Registro sem a
        # chave — todos os da Remessa — segue o caminho de sempre abaixo.
        tirar = (lambda ps: ps) if _e_inter(conta) else _sem_hifen
        espaco = limite_da_descricao(conta) if limite is None else limite
        return " ".join(_que_cabem(tirar(_palavras(editada)), espaco))
    utilidade = bool(r.get("utilidade"))
    # Fora do Inter (o Sicoob, e a remessa CNAB, que é do Sicoob e chega com
    # `conta=None`) a descrição não leva "-" nenhum (dono, 14/10/2026).
    hifen = (lambda ps: ps) if _e_inter(conta) else _sem_hifen
    cc = hifen(_palavras(r.get("centro_custo"), tirar_reembolso=False))
    nf = [] if utilidade else _palavras_do_numero(r.get("nf"))
    oc = _palavras_do_numero(r.get("oc_da_descricao"))
    # Arrecadação não tem cedente nem Nota Fiscal atrás: rotular o número
    # de "NF" inventaria um documento que não existe.
    arrecadacao = (r.get("tipo") == "Boleto"
                  and ocr_boleto.eh_arrecadacao(r.get("dados") or ""))
    # "NF" só com nota fiscal anexada (`nf_anexada`, de
    # `relatorio.tem_nf_anexada`); registro sem a chave fica SEM rótulo: não
    # inventa documento (dono, 01/10/2026).
    rotula_nf = bool(r.get("nf_anexada")) and not arrecadacao
    fixos = ((["NF", *nf] if rotula_nf else nf) if nf else []) + \
            (["OC", *oc] if oc else [])
    medicao = (None if utilidade or fixos
               else relatorio.contrato_e_medicao(r.get("descricao_lancamento")))
    if medicao:
        # Mão de obra: a forma curta da planilha, que também não se corta.
        fixos = ["C", *_palavras_do_numero(medicao[0]),
                 "M", *_palavras_do_numero(medicao[1])]

    # Documento SEM OC leva também a descrição do lançamento, entre o centro
    # de custo e o documento (dono, 01/10/2026). Com OC nada muda, e a medição
    # de mão de obra continua na forma curta.
    com_descricao = bool(nf) and not oc and not relatorio.contrato_e_medicao(
        r.get("descricao_lancamento"))
    texto = []
    if utilidade or not fixos or com_descricao:
        texto = hifen(_palavras(r.get("descricao_lancamento")))
        n = len(cc)
        if n and [p.casefold() for p in texto[:n]] == [p.casefold() for p in cc]:
            texto = texto[n:]
        if com_descricao and relatorio.numero_tem_4_digitos(nf):
            # Só número de 4+ dígitos: o curto pode ser lote.
            texto = _sem_sequencia(texto, nf)

    limite = limite_da_descricao(conta) if limite is None else limite
    if len(" ".join(cc + texto + fixos)) > limite:
        resto = cc + fixos
        texto = _que_cabem(texto, limite - len(" ".join(resto)) - (1 if resto else 0))
    if len(" ".join(cc + texto + fixos)) > limite:
        cc = _que_cabem(cc, limite - len(" ".join(fixos)) - (1 if fixos else 0))
    return " ".join(cc + texto + fixos)


def quem_recebe(registro) -> str:
    """O que vai na coluna do favorecido do HTML geral.

    No reembolso ("PAGAR PARA") o dinheiro vai para a PESSOA, não para o
    fornecedor do lançamento, e o HTML é o caminho de pagar à mão: com o
    fornecedor na coluna, quem paga por aqui erra o destinatário. É a mesma
    forma da coluna QUEM RECEBE da janela de confirmação
    (`confirmacao.Linha.quem_recebe`, que é propriedade de uma linha da
    janela e por isso não se chama daqui) — "<pessoa ou ?> (reembolso de
    <fornecedor>)" — e um teste confere que as duas continuam iguais. Cada
    nome passa por `para_colar` sozinho, porque ele tira os parênteses."""
    r = registro or {}
    favorecido = para_colar(r.get("favorecido"))
    if r.get("reembolso"):
        return (f"{para_colar(r.get('reembolso_nome')) or '?'} "
                f"(reembolso de {favorecido or '?'})")
    return favorecido


def dado_para_colar(tipo, dados) -> str:
    """O que o botão "Copiar" do dado de pagamento põe na área de transferência.

    Boleto vira só os dígitos. Pix copia-e-cola vai inteiro, como veio — tirar
    dele o que não é dígito (o que o script de fora fazia) destruía o código.
    E-mail em minúsculas; CPF/CNPJ/celular pontuados viram só dígitos.
    """
    d = str(dados or "").strip()
    if not d:
        return ""
    if regras.PIX_COPIA_COLA.search(re.sub(r"\s+", "", d)):
        return d
    if "@" in d:
        return d.lower()
    digitos = re.sub(r"\D", "", d)
    if str(tipo or "") == "Boleto":
        return digitos
    if len(digitos) in (10, 11, 14):
        return digitos
    if re.fullmatch(r"[0-9a-fA-F-]{20,40}", d):
        return d                         # chave aleatória
    return digitos or d


def _texto(valor) -> str:
    """Nome legível de um campo que pode vir string, dict ou lista."""
    if not valor:
        return ""
    if isinstance(valor, str):
        return re.sub(r"\s+", " ", valor).strip()
    if isinstance(valor, (int, float)):
        return str(valor)
    if isinstance(valor, list):
        return " | ".join(t for t in (_texto(v) for v in valor) if t)
    if isinstance(valor, dict):
        for chave in ("name", "description", "workName", "taskName"):
            texto = valor.get(chave)
            if isinstance(texto, str) and texto.strip():
                return re.sub(r"\s+", " ", texto).strip()
    return ""


def _br(d: date) -> str:
    return f"{d:%d/%m/%Y}"


def rotulo_periodo(ini: date, fim: date) -> str:
    """O mesmo sufixo do `.xlsx` do passo 2: `2026-09-01` ou
    `2026-09-01_a_2026-09-10`."""
    return f"{ini:%Y-%m-%d}" if ini == fim else f"{ini:%Y-%m-%d}_a_{fim:%Y-%m-%d}"


# --------------------------------------------------------------------------
# As linhas
# --------------------------------------------------------------------------
def total_da_conta(regs) -> Decimal:
    return sum((dinheiro(r.get("valor")) for r in regs), Decimal("0.00"))


def _chave_de_repeticao(tipo, dado_limpo: str) -> str:
    """Identidade do que o dono cola no banco, para achar a MESMA cobrança em
    duas linhas: boleto = só os dígitos da linha digitável (>= 20, para uma
    chave curta nunca contar); Pix copia-e-cola = o código inteiro. Chave Pix
    comum (CPF, e-mail) repetida é legítima (várias NFs do mesmo fornecedor)
    e não entra."""
    d = str(dado_limpo or "")
    if not d:
        return ""
    if regras.PIX_COPIA_COLA.search(re.sub(r"\s+", "", d)):
        return "pix:" + re.sub(r"\s+", "", d)
    if str(tipo or "") == "Boleto":
        dig = re.sub(r"\D", "", d)
        if len(dig) < 20:
            return ""
        # Linha digitável (47/48) e código de barras (44) do mesmo boleto
        # têm de dar a mesma chave: tudo vira o código de barras de 44.
        barras = dig if len(dig) == 44 else ocr_boleto.codigo_de_barras(dig)
        return "bol:" + (barras or dig)
    return ""


def _norm(texto) -> str:
    """Sem acento (NFKD, também de entrada já decomposta), maiúsculas e
    espaços colapsados: a grafia do status/obs não decide o bloqueio."""
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().upper()


def _motivo_do_bloqueio(r: dict) -> str:
    """Por que a linha não pode ser copiada às cegas (vazio = livre). "JÁ PAGO"
    entra: copiar o boleto/Pix de quem já pagou é pagar de novo."""
    status = _norm(r.get("status"))
    obs = _norm(r.get("obs"))
    motivos = []
    if status.startswith("JA PAGO"):
        motivos.append("já pago — não pagar de novo")
    if status.startswith("ATENCAO"):
        resto = re.sub(r"^\S+[\s\-:–—]*", "",
                       str(r.get("status") or "").strip())
        motivos.append(resto or "atenção")
    if "PAGAR A MAO" in obs:
        motivos.append("pagar à mão (a observação manda pagar outra pessoa)")
    if r.get("parcial"):
        motivos.append("boleto parcial: não pagar pela linha")
    if r.get("valor_diverge") and "diverge" not in " ".join(motivos).lower():
        motivos.append("valor do boleto diverge do lançamento")
    return "; ".join(motivos)


def contas_do_html_geral(resultado) -> list[dict]:
    """As contas do passo 2, uma entrada por linha das abas por conta.

    A conta de pessoa física nunca entra aqui: ela não chega a
    `Resultado.contas` (é conta de ajuste, `relatorio.CONTAS_IGNORAR`), e o
    filtro abaixo é só a garantia de que, se um dia chegar, continua indo
    para o HTML dela e não para este."""
    contas = []
    for nome, regs in (getattr(resultado, "contas", None) or {}).items():
        if e_conta_pf(nome) or not regs:
            continue
        entradas = []
        for r in regs:
            tipo = str(r.get("tipo") or "-")
            id_ = str(r.get("id") or "")
            # O pagamento À MÃO da tela "Pagamentos do dia" (só ela põe a
            # chave `a_mao`): o mesmo lançamento pode estar na lista do dia, e
            # o id é a chave do "já paguei" e do "Conferido" desta página —
            # "<lançamento>#mao:<n>", e o link continua o do lançamento.
            # Registro sem a chave (todos os da Remessa) não muda.
            a_mao = str(r.get("a_mao") or "")
            # A linha de um lançamento dividido em N boletos
            # (`boletos_somados`) leva a SUA linha digitável no id (dígitos,
            # a chave estável da parte; na falta, o "k/N"): é a chave do "já
            # paguei" (`rowKey`) e do "Conferido". Nunca a posição na lista.
            # Não colide com "#mao:<n>" (dígitos x "mao:") nem entre partes.
            parte = str(r.get("parte_linha") or r.get("parte") or "")
            entradas.append({
                "id": (f"{id_}#{a_mao}" if id_ else a_mao) if a_mao
                else (f"{id_}#{parte}" if id_ and parte else id_),
                # Sem id não há para onde ir: link vazio, sem botão na tela.
                "link": URL_LANCAMENTO + id_ if id_ else "",
                # Só para a checagem de repetição abaixo (sai antes de devolver):
                # as partes do MESMO lançamento dividido herdam as chaves
                # extras (Pix do QR, linha da guia) e não são repetição.
                "_lancamento": id_ if (parte and id_ and not a_mao) else "",
                "tipo": tipo,
                "dados_original": str(r.get("dados") or ""),
                "dados_limpo": dado_para_colar(tipo, r.get("dados")),
                # O Pix do QR Code do boleto, num segundo "Copiar" (dono,
                # 08/10/2026). Copia-e-cola vai inteiro (`dado_para_colar`).
                "pix_qr": dado_para_colar("Pix", r.get("pix_qr")),
                # As OUTRAS identidades da mesma cobrança, para a checagem de
                # repetição: o Pix do QR do boleto e a linha da guia que virou
                # Pix (revisão de dinheiro, 08/10/2026).
                "chaves_extra": [k for k in (
                    _chave_de_repeticao("Pix", dado_para_colar("Pix", r.get("pix_qr"))),
                    _chave_de_repeticao("Boleto", r.get("linha_da_guia")),
                ) if k],
                "valor": valor_para_colar(r.get("valor")),
                "centavos": centavos(r.get("valor")),
                "descricao": descricao_para_colar(r, nome),
                "favorecido": quem_recebe(r),
                "status": str(r.get("status") or ""),
                "conferencia": str(r.get("conferencia") or ""),
                "obs": str(r.get("obs") or ""),
                "bloqueio": _motivo_do_bloqueio(r),
            })
        contas.append({"nome": str(nome),
                       "total": reais(total_da_conta(regs)).replace("R$ ", "", 1),
                       "entries": entradas})
    # C2: a mesma linha digitável / Pix copia-e-cola em mais de um lançamento.
    por_chave: dict[str, list[dict]] = {}
    for c in contas:
        for e in c["entries"]:
            chaves = {_chave_de_repeticao(e["tipo"], e["dados_limpo"]),
                      *e.pop("chaves_extra", ())}
            for k in chaves - {""}:
                por_chave.setdefault(k, []).append(e)
    for grupo in por_chave.values():
        ids = {e["_lancamento"] or e["id"] or id(e) for e in grupo}
        if len(ids) > 1:
            m = (f"mesma linha digitável em {len(grupo)} lançamentos "
                 "— risco de pagar em dobro")
            for e in grupo:
                e["bloqueio"] = (e["bloqueio"] + "; " + m) if e["bloqueio"] else m
    for c in contas:
        for e in c["entries"]:
            e.pop("_lancamento", None)
    return contas


def movimentos_do_html(movimentos) -> list[dict]:
    """Os movimentos à mão do dia (aporte que entra na mãe, transferência
    entre contas, distribuição de lucros) como linhas INFORMATIVAS do HTML
    geral — item A, 22/10/2026, dono: "não precisa colocar os pix pq tem
    salvo no banco já, só a informação pra não ficar nenhum pra trás".

    Só de, para, tipo e valor: nenhuma chave, nada para copiar. Não são
    `Resultado.contas`, então não entram no total das contas nem na remessa
    (que lê o `Resultado`). Zero ou negativo fica de fora."""
    linhas = []
    for m in movimentos or ():
        valor = m.get("valor")
        if valor is None or dinheiro(valor) <= 0:
            continue
        linhas.append({"de": str(m.get("de") or ""), "para": str(m.get("para") or ""),
                       "tipo": str(m.get("tipo") or ""),
                       "valor": valor_para_colar(valor), "centavos": centavos(valor)})
    return linhas


def _palavras_do_nome(nome) -> list[str]:
    return re.findall(r"[A-Z0-9]+", relatorio.sem_acento(str(nome or "")).upper())


def e_reembolso_de(nome, pessoas) -> bool:
    """O `nome` escrito no reembolso é uma das `pessoas`?

    Casa por palavras do começo, sem acento nem caixa: "FULANO" e "FULANO
    SILVA NETO" casam com "FULANO SILVA" (o aviso às vezes traz só o primeiro
    nome, e o documento às vezes o nome inteiro); "FULANA" não casa com
    "FULANO", nem "FULANO PEREIRA" com "FULANO SILVA". Nome vazio nunca casa."""
    alvo = _palavras_do_nome(nome)
    if not alvo:
        return False
    for pessoa in pessoas or ():
        p = _palavras_do_nome(pessoa)
        n = min(len(p), len(alvo))
        if n and alvo[:n] == p[:n]:
            return True
    return False


def tirar_reembolsos(resultado, lancamentos, pessoas, overviews=None):
    """(resultado, lancamentos, tirados) sem os reembolsos das `pessoas`.

    `tirados` é a lista do que saiu, uma frase por linha ("FAVORECIDO — R$ x
    — reembolso para Y"), para o Registro dizer QUEM saiu e não só quantos:
    o nome casa pelo começo, e um homônimo tirado por engano tem de aparecer
    para quem paga pelo HTML (revisão de dinheiro, 14/10/2026).

    Pedido do dono (14/10/2026): ao gerar o HTML o app pergunta se entram
    os reembolsos dos nomes do `confirmar_antes.json`; "não" tira as linhas
    deles dos DOIS HTMLs. No geral, a linha é reembolso de alguém pelo
    `reembolso_para` do registro (aviso "PAGAR PARA" ou "REEMBOLSO <nome>" no
    documento); no de pessoa física, pelo nome depois de "REEMBOLSO" no nº do
    documento. Nada é apagado de `self.resultado`: a planilha e a remessa
    continuam com o que o passo 2 confirmou — só o HTML deixa as linhas de
    fora."""
    pessoas = [p for p in (pessoas or ()) if str(p).strip()]
    if not pessoas:
        return resultado, list(lancamentos or ()), []
    tirados = []
    contas = {}
    for nome, regs in (getattr(resultado, "contas", None) or {}).items():
        ficam = []
        for r in regs:
            if e_reembolso_de(r.get("reembolso_para"), pessoas):
                tirados.append(f"{r.get('favorecido') or '?'} — "
                               f"{reais(r.get('valor') or 0)} — reembolso para "
                               f"{r.get('reembolso_para')}")
            else:
                ficam.append(r)
        if ficam:
            contas[nome] = ficam
    novo = (resultado._replace(contas=contas)
            if hasattr(resultado, "_replace") else resultado)
    ficam_pf = []
    for item in lancamentos or ():
        overview = (overviews or {}).get(str(item.get("id"))) or {}
        quem = (relatorio.quem_o_documento_diz_reembolsar(item, overview)
                if relatorio.documento_declara_reembolso(item, overview) else "")
        if (e_conta_pf(relatorio.nome_da_conta(item)) and not item.get("paid")
                and e_reembolso_de(quem, pessoas)):
            tirados.append(f"{_texto(item.get('paidTo')) or '?'} — "
                           f"{reais(relatorio.valor_do_item(item))} — "
                           f"reembolso para {quem} (pessoa física)")
            continue
        ficam_pf.append(item)
    return novo, ficam_pf, tirados


def itens_pessoa_fisica(lancamentos, anexos=None,
                        vencimento_padrao: date | None = None) -> list[dict]:
    """Os lançamentos A PAGAR da conta de pessoa física, no formato do modelo.

    Saem da lista do passo 1 (`mc_api.listar_a_pagar`), que já traz o que a
    aba NÃO ENTRARAM não traz: vencimento (`plannedDate`), categoria
    (`category`), nº do documento (`documentNumber`) e centro de custo
    (`costCentreDetails[].workName`). O ITEM do centro de custo e a condição
    de pagamento não estão provados nessa lista: são lidos se vierem
    (`taskName`/`task`, `paymentCondition`) e, se não, o item fica vazio e a
    condição sai "À Vista", como o script de fora fazia.
    """
    itens = []
    for n, item in enumerate(lancamentos or ()):
        if item.get("paid") or not e_conta_pf(relatorio.nome_da_conta(item)):
            continue
        files = (anexos or {}).get(str(item.get("tradePayableId"))) or []
        venc = relatorio.data_do_item(item) or vencimento_padrao
        cc = []
        for c in item.get("costCentreDetails") or []:
            if not isinstance(c, dict):
                continue
            obra = _texto(c.get("workName"))
            etapa = re.sub(r"^Item\s+", "", _texto(c.get("taskName") or c.get("task")),
                           flags=re.I)
            par = {"obra": obra, "item": etapa}
            if (obra or etapa) and par not in cc:
                cc.append(par)
        valor = dinheiro(relatorio.valor_do_item(item))
        itens.append({
            "id": str(item.get("id") or f"sem-id-{n}"),
            "favorecido": _texto(item.get("paidTo")),
            "centavos": centavos(valor),
            "valor": valor_para_colar(valor),
            "metodo": relatorio.tipo_de_pagamento(item, files) or "-",
            "dados": _texto(item.get("paidToBankAccount")),
            "descricao": _texto(item.get("description")),
            "categoria": _texto(item.get("category")),
            "condicao": _texto(item.get("paymentCondition")) or "À Vista",
            "conta": relatorio.nome_da_conta(item),
            "doc": _texto(item.get("documentNumber")),
            "obras": relatorio.centro_de_custo(item),
            "cc": cc,
            "venc": venc.isoformat() if venc else "",
            "venc_br": _br(venc) if venc else "",
            "venc_do_erp": bool(relatorio.data_do_item(item)),
        })
    itens.sort(key=lambda i: (i["venc"], i["favorecido"].lower(), i["obras"],
                              i["centavos"]))
    return itens


def ler_extras(pastas) -> tuple[str, list[str]]:
    """O logotipo (data URI) e as linhas do rodapé, se houver arquivo.

    Procura nas `pastas` na ordem dada — a da planilha primeiro, depois a do
    app. Nada disso é obrigatório: faltando, o PDF sai sem logotipo e sem
    rodapé, e o Registro diz qual arquivo pôr onde."""
    logo, rodape = "", []
    for pasta in pastas or ():
        if not pasta:
            continue
        pasta = Path(pasta)
        if not logo:
            for nome in NOMES_LOGO:
                arq = pasta / nome
                try:
                    if arq.is_file() and arq.stat().st_size <= _LOGO_MAX:
                        logo = ("data:image/png;base64,"
                                + base64.b64encode(arq.read_bytes()).decode("ascii"))
                        break
                except OSError:
                    continue
        if not rodape:
            arq = pasta / NOME_RODAPE
            try:
                if arq.is_file():
                    rodape = [linha.strip() for linha in
                              arq.read_text(encoding="utf-8-sig").splitlines()
                              if linha.strip()][:_RODAPE_MAX_LINHAS]
            except (OSError, UnicodeDecodeError):
                rodape = []
    return logo, rodape


# --------------------------------------------------------------------------
# Os dois HTMLs
# --------------------------------------------------------------------------
def _preencher(modelo: str, valores: dict) -> str:
    """Troca os `__NOME__` numa passada só: o que entra não é relido, então
    um favorecido chamado `__DATA__` não vira outra coisa."""
    return _PLACEHOLDER.sub(
        lambda m: valores.get(m.group(1), m.group(0)), modelo)


def html_geral(contas: list[dict], ini: date, fim: date, movimentos=()) -> str:
    """`movimentos`: as linhas de `movimentos_do_html` (já prontas)."""
    titulo = _br(ini) if ini == fim else f"{_br(ini)} a {_br(fim)}"
    return _preencher(modelos_html.MODELO_GERAL, {
        "TITULO": escapar(titulo),
        "SUB": escapar(SUBTITULO_GERAL),
        "JSON": json_para_script({"contas": contas, "movimentos": list(movimentos or ())}),
        "STORAGE": json_para_script(f"pagamentos_{rotulo_periodo(ini, fim)}"),
    })


def html_pessoa_fisica(itens: list[dict], ini: date, fim: date, hoje: date,
                       logo: str = "", rodape=()) -> str:
    cfg = {"hoje": hoje.isoformat(), "hoje_br": _br(hoje),
           "ini_br": _br(ini), "fim_br": _br(fim),
           "periodo": rotulo_periodo(ini, fim), "conta": CONTA_PF,
           "logo": logo or "", "rodape": list(rodape or ())}
    return _preencher(modelos_html.MODELO_PF, {
        "HOJE_BR": escapar(_br(hoje)),
        "INI_BR": escapar(_br(ini)),
        "FIM_BR": escapar(_br(fim)),
        "CFG": json_para_script(cfg),
        "DATA": json_para_script(itens),
    })


class Gerados(NamedTuple):
    """O que o botão gravou — e o que ele escreve no Registro da aba."""
    geral: Path
    pessoa_fisica: Path
    contas: int
    linhas: int
    total: Decimal
    linhas_pf: int
    total_pf: Decimal
    #: {campo: quantos lançamentos de PF saíram sem ele}
    pf_sem: dict
    tem_logo: bool
    tem_rodape: bool
    #: Os movimentos à mão do dia, só informativos (fora de `total`).
    movimentos: int = 0
    total_movimentos: Decimal = Decimal("0.00")

    def registro(self) -> list[str]:
        def caminho(p):
            return str(p).replace("\\", "/")
        linhas = [
            "",
            "HTML dos pagamentos (provisório, até a remessa CNAB virar o "
            "caminho do dia):",
            f"  geral: {self.contas} conta(s), {self.linhas} lançamento(s), "
            f"{reais(self.total)}  ->  {caminho(self.geral)}",
            f"  pessoa física: {self.linhas_pf} lançamento(s), "
            f"{reais(self.total_pf)}  ->  {caminho(self.pessoa_fisica)}",
        ]
        if self.movimentos:
            linhas.append(f"  movimentos do dia (só informação, fora do total e da "
                          f"remessa): {self.movimentos}, {reais(self.total_movimentos)}")
        faltas = [f"{n} sem {campo}" for campo, n in self.pf_sem.items() if n]
        if faltas:
            linhas.append("  (pessoa física: " + " · ".join(faltas) + ")")
        if self.linhas_pf and not self.tem_logo:
            linhas.append(f"  sem logotipo no PDF: ponha {NOMES_LOGO[0]} ao lado "
                          "da planilha")
        if self.linhas_pf and not self.tem_rodape:
            linhas.append(f"  sem rodapé no PDF: ponha {NOME_RODAPE} ao lado da "
                          "planilha (uma linha por linha do rodapé)")
        return linhas


def gravar(resultado, lancamentos, anexos, pasta, ini: date, fim: date,
           hoje: date | None = None, pastas_extras=(), movimentos=()) -> Gerados:
    """Grava os dois HTMLs na `pasta` (a da planilha) e devolve o resumo.

    `resultado` é o `Resultado` do passo 2; `lancamentos` e `anexos` são os
    do passo 1. `pastas_extras` diz onde procurar o logotipo e o rodapé
    (sem ela, só na própria `pasta`). `movimentos`: os movimentos à mão do
    dia ({de, para, tipo, valor}), só informativos (`movimentos_do_html`)."""
    hoje = hoje or date.today()
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    periodo = rotulo_periodo(ini, fim)

    contas = contas_do_html_geral(resultado)
    movs = movimentos_do_html(movimentos)
    itens = itens_pessoa_fisica(lancamentos, anexos, vencimento_padrao=fim)
    logo, rodape = ler_extras(pastas_extras or (pasta,))

    geral = pasta / f"pagamentos_{periodo}.html"
    pf = pasta / f"pagamentos_pessoa_fisica_lancamento_{periodo}.html"
    geral.write_text(html_geral(contas, ini, fim, movs), encoding="utf-8")
    pf.write_text(html_pessoa_fisica(itens, ini, fim, hoje, logo, rodape),
                  encoding="utf-8")

    regs = [r for nome, rs in (getattr(resultado, "contas", None) or {}).items()
            if not e_conta_pf(nome) for r in rs]
    return Gerados(
        geral=geral, pessoa_fisica=pf,
        contas=len(contas), linhas=sum(len(c["entries"]) for c in contas),
        total=total_da_conta(regs),
        linhas_pf=len(itens),
        total_pf=sum((Decimal(i["centavos"]) / 100 for i in itens),
                     Decimal("0.00")),
        pf_sem={"vencimento no ERP": sum(1 for i in itens if not i["venc_do_erp"]),
                "categoria": sum(1 for i in itens if not i["categoria"]),
                "nº doc": sum(1 for i in itens if not i["doc"]),
                "centro de custo": sum(1 for i in itens if not i["obras"])},
        tem_logo=bool(logo), tem_rodape=bool(rodape),
        movimentos=len(movs),
        total_movimentos=sum((Decimal(m["centavos"]) / 100 for m in movs),
                             Decimal("0.00")))
