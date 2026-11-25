# -*- coding: utf-8 -*-
"""O relatório de aportes e distribuições de lucros de uma conta do Controle
de aportes, para o SÓCIO ler (pedido de 25/11/2026). Sem tela e sem rede: a
aba (`controle_frame.py`) lê o ERP e chama `montar`; o PDF sai de
`relatorio_aportes_pdf.py`.

Aportes: os MESMOS recebimentos de aporte que o Controle lê (Aporte de
Capital e Aporte de Investidor), no período escolhido, e de quem é cada um
pela MESMA decisão da conta (`controle_aportes.dono_do_recebimento`) — o
relatório nunca discorda da tela sobre quem pôs o quê. Leitura duvidosa
(parcela repetida, fora do período, zero ou negativa) PARA, como na tela.

Distribuições: os pagamentos pagos com a categoria DISTRIBUIÇÃO DE LUCROS
(`aportes.regras.CATEGORIA_PAGAMENTO`) que saíram das contas da conta do
controle (ela e as somadas) para um aportador dela — o favorecido (`paidTo`)
pelo nome COMPLETO, como o Cliente dos aportes. Distribuição para outra
empresa não é do sócio e fica de fora.

O que vai ao sócio é só dinheiro que entrou e saiu: sem saldo, sem "para
igualar", sem nota interna (o dono riscou isso no relatório de 25/11). O que
ficou FORA — sem dono no período — volta em `Relatorio.fora`, para a tela
avisar ANTES de gerar; não entra no PDF.
"""
from __future__ import annotations

import datetime
import re
import unicodedata
from dataclasses import dataclass, field, replace
from decimal import Decimal

import util
from aportes.regras import CATEGORIA_PAGAMENTO

from . import controle_aportes as ca
from .valores import brl

ZERO = Decimal("0.00")
CATEGORIA_DISTRIBUICAO = CATEGORIA_PAGAMENTO["Distribuição de Lucro"]
TODOS = "Todos os sócios"
#: Quantos Clientes o aviso do "fora" lista (o resto vai ao Registro).
MAX_GRUPOS_FORA = 4
MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro")


@dataclass(frozen=True)
class Movimento:
    data: datetime.date
    conta: str        # a conta do ERP onde entrou (aporte) ou de onde saiu (distribuição)
    socio: str        # o aportador, nome como está no controle
    valor: Decimal


@dataclass
class Relatorio:
    empresa: str
    socios: tuple                 # os nomes pedidos (um, ou todos da conta)
    de: datetime.date
    ate: datetime.date
    aportes: list = field(default_factory=list)
    distribuicoes: list = field(default_factory=list)
    #: [(Recebimento, motivo)] — sem dono no período; só para a tela avisar.
    fora: list = field(default_factory=list)
    #: [(Movimento com o favorecido do ERP, motivo)] — distribuições destas
    #: contas no período que não entraram; só para a tela avisar.
    distribuicoes_fora: list = field(default_factory=list)

    @property
    def total_aportes(self) -> Decimal:
        return sum((m.valor for m in self.aportes), ZERO)

    @property
    def total_distribuicoes(self) -> Decimal:
        return sum((m.valor for m in self.distribuicoes), ZERO)


def periodo_do_formulario(de_texto, ate_texto, hoje: datetime.date) -> tuple:
    """(de, até) digitados DD/MM/AAAA. Até depois de hoje vira hoje (o futuro
    não tem recebimento pago). `ValueError` com o recado da tela."""
    try:
        de = ca.ler_data(de_texto)
        ate = ca.ler_data(ate_texto)
    except ValueError:
        raise ValueError("Escreva as datas como DD/MM/AAAA.") from None
    ate = min(ate, hoje)
    if de > ate:
        raise ValueError("A data inicial tem de ser antes da final (e não depois de hoje).")
    return de, ate


def empresa_da_conta(conta: ca.ContaControlada) -> str:
    """O nome da empresa, sem o banco: "EMPRESA X - SICOOB" + "EMPRESA X -
    INTER" → "EMPRESA X". Contas de empresas diferentes somadas: o rótulo
    inteiro (só para mostrar; nada se decide por isto)."""
    prefixos = {nome.rsplit(" - ", 1)[0].strip() if " - " in nome else nome.strip()
                for nome in ca.contas_do_erp(conta)}
    return prefixos.pop() if len(prefixos) == 1 else ca.rotulo_da_conta(conta)


def banco_da_conta(nome: str) -> str:
    """O que vem depois do último " - " ("EMPRESA X - SICOOB" → "SICOOB"): a
    empresa já está no título do relatório."""
    return nome.rsplit(" - ", 1)[1].strip() if " - " in nome else nome.strip()


def socios_da_conta(conta: ca.ContaControlada) -> list:
    return [a.nome_erp for a in conta.aportadores]


def _escolhidos(conta: ca.ContaControlada, socio: str) -> tuple:
    nomes = socios_da_conta(conta)
    if socio == TODOS:
        return tuple(nomes)
    achados = [n for n in nomes if util.norm_espaco(n) == util.norm_espaco(socio)]
    if len(achados) != 1:
        raise ValueError(f'"{socio}" não é aportador desta conta.')
    return (achados[0],)


def _aportes(conta, recebimentos, apontamentos, de, ate) -> tuple:
    """([Movimento sem a conta], fora). A conta do aporte vem à parte
    (`contas_dos_recebimentos`), porque o item do LISTAR não diz a conta."""
    no_periodo = replace(conta, abertura=de)
    vistos: set = set()
    falhas = []
    for r in recebimentos:
        if r.id in vistos:
            raise ValueError(f"o recebimento {r.id} veio duas vezes do Mais Controle — "
                             "leitura não confiável, nenhum relatório foi gerado")
        vistos.add(r.id)
        falha = ca._leitura_que_nao_se_soma(no_periodo, r, ate)
        if falha:
            falhas.append(falha)
    if falhas:
        raise ValueError(" · ".join(falhas) + " — nenhum relatório foi gerado")
    por_id = {a.id: a for a in conta.aportadores if a.id is not None}
    apontado = {p.recebimento_id: p for p in apontamentos}
    dentro, fora = [], []
    for r in sorted(recebimentos, key=lambda x: (x.data, x.id)):
        destino, quem = ca.dono_do_recebimento(conta, r, apontado.get(r.id), por_id)
        if destino == ca.APORTE:
            dentro.append((r, quem))
        elif destino == ca.SEM_DONO:
            fora.append((r, quem))
    return dentro, fora


def distribuicoes_dos_pagos(pagos, contas_no_erp, socios, de, ate, todos_os_socios=None) -> tuple:
    """([Movimento], fora) dos `pagos` de `anexar.mc_api.montar_pagos` (um por
    sub-pagamento): entram os de distribuição de lucros que saíram de uma das
    `contas_no_erp` no período para um dos `socios`. Os filtros de conta e de
    categoria pedidos ao ERP são só para ler menos: quem decide é isto aqui,
    campo a campo.

    `fora` = [(Movimento com o favorecido do ERP, motivo)]: o que saiu DESTAS
    contas no período e não entrou — categoria que não é a de distribuição
    (o ERP mandou pelo filtro dela) ou favorecido que não é sócio da conta
    (nome abreviado, empresa). A tela avisa, como nos aportes; distribuição
    para OUTRO sócio da conta (relatório de um só) não é aviso.
    Sub-pagamento de outra conta não é desta empresa e sai calado.
    Pago sem data ou com valor zero/negativo PARA (`ValueError`)."""
    contas = {util.norm_espaco(c): c for c in contas_no_erp}
    nomes = {util.norm_espaco(s): s for s in socios}
    da_conta = {util.norm_espaco(s) for s in (todos_os_socios or socios)}
    alvo = util.norm_espaco(CATEGORIA_DISTRIBUICAO)
    vistos: set = set()
    saida, fora = [], []
    for p in pagos:
        conta = contas.get(util.norm_espaco(p.get("conta") or ""))
        if conta is None:
            continue
        favorecido = str(p.get("favorecido") or "").strip()
        ident = str(p.get("paidId") or "")
        if ident and ident in vistos:
            raise ValueError("a mesma distribuição veio duas vezes do Mais Controle — "
                             "leitura não confiável, nenhum relatório foi gerado")
        vistos.add(ident)
        try:
            data = ca.data_do_erp(p.get("dataFull"))
        except (ValueError, IndexError):
            raise ValueError(f"distribuição para {favorecido or 'sem favorecido'} sem data de "
                             "pagamento no Mais Controle — nenhum relatório foi gerado") from None
        valor = Decimal(int(p.get("valor") or 0)) / 100
        if valor <= 0:
            raise ValueError(f"distribuição para {favorecido or 'sem favorecido'} em "
                             f"{data:%d/%m/%Y} sem valor no Mais Controle — nenhum relatório "
                             "foi gerado")
        if not de <= data <= ate:
            continue
        mov = Movimento(data, conta, favorecido, valor.quantize(ca.CENTAVO))
        if util.norm_espaco(p.get("categoria") or "") != alvo:
            fora.append((mov, f'categoria "{p.get("categoria") or "vazia"}" no Mais Controle'))
            continue
        socio = nomes.get(util.norm_espaco(favorecido))
        if socio is None:
            if util.norm_espaco(favorecido) not in da_conta:
                fora.append((mov, "o favorecido não é sócio desta conta (nome completo, como "
                                  "o aportador)"))
            continue
        saida.append(replace(mov, socio=socio))
    ordem = lambda m: (m.data, m.socio, m.valor)          # noqa: E731
    return sorted(saida, key=ordem), sorted(fora, key=lambda f: ordem(f[0]))


def montar(conta: ca.ContaControlada, socio: str, de, ate, recebimentos, contas_dos_recebimentos,
           apontamentos, pagos) -> Relatorio:
    """O relatório. `recebimentos`: [Recebimento] das contas da conta do
    controle no período; `contas_dos_recebimentos`: {id: nome da conta no
    ERP} (quem leu sabe de que conta veio cada um); `apontamentos`: os da
    conta; `pagos`: `montar_pagos` das mesmas contas no período."""
    socios = _escolhidos(conta, socio)
    dentro, fora = _aportes(conta, recebimentos, apontamentos, de, ate)
    pedidos = {util.norm_espaco(s) for s in socios}
    aportes = [Movimento(r.data, contas_dos_recebimentos.get(r.id, ""), quem, r.valor)
               for r, quem in dentro if util.norm_espaco(quem) in pedidos]
    distrib, distrib_fora = distribuicoes_dos_pagos(pagos, ca.contas_do_erp(conta), socios,
                                                    de, ate, socios_da_conta(conta))
    return Relatorio(empresa=empresa_da_conta(conta), socios=socios, de=de, ate=ate,
                     aportes=aportes, distribuicoes=distrib, fora=fora,
                     distribuicoes_fora=distrib_fora)


def resumo_mensal(rel: Relatorio) -> list:
    """[(primeiro dia do mês, aportes, distribuições)] de todo mês com
    movimento, em ordem."""
    meses: dict = {}
    for m in rel.aportes:
        meses.setdefault(m.data.replace(day=1), [ZERO, ZERO])[0] += m.valor
    for m in rel.distribuicoes:
        meses.setdefault(m.data.replace(day=1), [ZERO, ZERO])[1] += m.valor
    return [(mes, a, d) for mes, (a, d) in sorted(meses.items())]


def resumo_por_socio(rel: Relatorio) -> list:
    """[(sócio, aportou, recebeu)] na ordem do controle."""
    return [(s, sum((m.valor for m in rel.aportes if m.socio == s), ZERO),
             sum((m.valor for m in rel.distribuicoes if m.socio == s), ZERO))
            for s in rel.socios]


def nome_do_mes(mes: datetime.date) -> str:
    return f"{MESES[mes.month - 1]}/{mes.year}"


def titulo_dos_socios(rel: Relatorio) -> str:
    if len(rel.socios) == 1:
        return rel.socios[0]
    return " e ".join((", ".join(rel.socios[:-1]), rel.socios[-1])) if rel.socios else ""


def nome_do_arquivo(rel: Relatorio) -> str:
    """Nome seguro no Windows: "Aportes e distribuições - EMPRESA - SÓCIO -
    01-01-2026 a 25-11-2026.pdf"."""
    quem = rel.socios[0] if len(rel.socios) == 1 else "todos os sócios"
    texto = (f"Aportes e distribuições - {rel.empresa} - {quem} - "
             f"{rel.de:%d-%m-%Y} a {rel.ate:%d-%m-%Y}")
    texto = unicodedata.normalize("NFC", texto)
    texto = re.sub(r'[\\/:*?"<>|]+', "-", texto)
    texto = re.sub(r"\s+", " ", texto).strip(" .-")
    return texto[:150] + ".pdf"


def texto_do_fora(rel: Relatorio) -> str:
    """O aviso da tela quando há aporte sem dono no período ("" sem nenhum),
    somado por Cliente do ERP — é o Cliente que se corrige no ERP (ou se
    aponta na aba), e "103 de uma empresa que não é sócia" é outro caso que
    "19 com a própria empresa de Cliente"."""
    partes = []
    if rel.fora:
        total = sum((r.valor for r, _ in rel.fora), ZERO)
        partes.append(
            f"{len(rel.fora)} recebimento(s) de aporte no período ({brl(total)}) não são de "
            "nenhum sócio desta conta pelo Cliente do Mais Controle:\n"
            + "\n".join(_grupos([(r.cliente, r.valor) for r, _ in rel.fora], "sem Cliente")))
    if rel.distribuicoes_fora:
        total = sum((m.valor for m, _ in rel.distribuicoes_fora), ZERO)
        partes.append(
            f"{len(rel.distribuicoes_fora)} pagamento(s) com o filtro de distribuição destas "
            f"contas no período ({brl(total)}) não entraram (favorecido que não é sócio, ou "
            "outra categoria):\n"
            + "\n".join(_grupos([(m.socio, m.valor) for m, _ in rel.distribuicoes_fora],
                                "sem favorecido")))
    if not partes:
        return ""
    return ("Ficaram FORA do relatório:\n\n" + "\n\n".join(partes)
            + "\n\nSe algum é de sócio, corrija o Cliente/favorecido no Mais Controle (ou "
              "aponte o aporte na aba) e gere de novo.")


def _grupos(pares, vazio: str) -> list:
    """Linhas "  • N de NOME: R$ X", maior soma primeiro, até `MAX_GRUPOS_FORA`."""
    grupos: dict = {}
    for nome, valor in pares:
        chave = (nome or "").strip() or vazio
        n, soma = grupos.get(chave, (0, ZERO))
        grupos[chave] = (n + 1, soma + valor)
    linhas = [f"  • {n} de {nome}: {brl(soma)}" for nome, (n, soma)
              in sorted(grupos.items(), key=lambda g: (-g[1][1], g[0]))[:MAX_GRUPOS_FORA]]
    if len(grupos) > MAX_GRUPOS_FORA:
        linhas.append(f"  • e mais {len(grupos) - MAX_GRUPOS_FORA} — veja o Registro")
    return linhas
