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
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import NamedTuple

from . import modelos_html
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

SUBTITULO_GERAL = "vencimentos em aberto no Mais Controle - todas as contas"

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
            entradas.append({
                "id": str(r.get("id") or ""),
                "tipo": tipo,
                "dados_original": str(r.get("dados") or ""),
                "dados_limpo": dado_para_colar(tipo, r.get("dados")),
                "valor": valor_para_colar(r.get("valor")),
                "centavos": centavos(r.get("valor")),
                "descricao": para_colar(r.get("descricao")),
                "favorecido": para_colar(r.get("favorecido")),
                "status": str(r.get("status") or ""),
                "conferencia": str(r.get("conferencia") or ""),
                "obs": str(r.get("obs") or ""),
            })
        contas.append({"nome": str(nome),
                       "total": reais(total_da_conta(regs)).replace("R$ ", "", 1),
                       "entries": entradas})
    return contas


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


def html_geral(contas: list[dict], ini: date, fim: date) -> str:
    titulo = _br(ini) if ini == fim else f"{_br(ini)} a {_br(fim)}"
    return _preencher(modelos_html.MODELO_GERAL, {
        "TITULO": escapar(titulo),
        "SUB": escapar(SUBTITULO_GERAL),
        "JSON": json_para_script({"contas": contas}),
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
           hoje: date | None = None, pastas_extras=()) -> Gerados:
    """Grava os dois HTMLs na `pasta` (a da planilha) e devolve o resumo.

    `resultado` é o `Resultado` do passo 2; `lancamentos` e `anexos` são os
    do passo 1. `pastas_extras` diz onde procurar o logotipo e o rodapé
    (sem ela, só na própria `pasta`)."""
    hoje = hoje or date.today()
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    periodo = rotulo_periodo(ini, fim)

    contas = contas_do_html_geral(resultado)
    itens = itens_pessoa_fisica(lancamentos, anexos, vencimento_padrao=fim)
    logo, rodape = ler_extras(pastas_extras or (pasta,))

    geral = pasta / f"pagamentos_{periodo}.html"
    pf = pasta / f"pagamentos_pessoa_fisica_lancamento_{periodo}.html"
    geral.write_text(html_geral(contas, ini, fim), encoding="utf-8")
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
        tem_logo=bool(logo), tem_rodape=bool(rodape))
