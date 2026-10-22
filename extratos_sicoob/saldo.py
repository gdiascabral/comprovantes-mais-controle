# -*- coding: utf-8 -*-
"""O saldo de cada conta do Sicoob — só LEITURA. Par de `pendencias.py`.

Usado pela aba "Pagamentos do dia" (botão "Reler Sicoob"): o saldo do banco
das contas do Sicoob deixa de ser digitado. Nada é assinado, agendado ou
alterado no banco.

**A conta é implícita na sessão**, como nas pendências: o robô entra na conta
pelo seletor (`SicoobClient.acessar_conta`), CONFERE no cabeçalho que a conta
aberta é a pedida e só então pede o saldo, com o `fetch` da própria página.
Saldo de uma empresa gravado na linha de outra é o pior erro possível aqui —
e nada na tela o denunciaria. A resposta também diz a conta
(`numContaCorrente`), e ela é conferida de novo (`mesma_conta`).

**O endereço foi medido em 22/10/2026**, com o dono logado e conferindo os
saldos na tela do banco: é o que a Home do SicoobNet pede para o quadro de
movimentações, um GET sem conta no endereço nem no pedido — a resposta é da
conta SELECIONADA. A página chama com `?block-ui=...`; o `fetch` daqui não
leva, como as pendências, e a prova ao vivo de 22/10/2026 (só leitura, depois
do `acessar_conta` do app) deu HTTP 200 nas três contas assim.

**O endereço e o formato são do Sicoob, que os troca sem aviso** (fez isso
com os comprovantes em 25/09/2026). Por isso moram num bloco só, logo abaixo.
Endereço que some (404/405/410), resposta que não é JSON e DUAS contas
seguidas sem o campo (ou com saldo que não é número) viram `EnderecoMudou`,
que PARA a leitura (não adianta trocar de conta 20 vezes)
com um recado que diz o endereço; a pessoa digita o saldo à mão até medirem
de novo. `ROTA_SALDO = ""` desliga a leitura inteira (`medido()`).

**Contingência (plano da entrega 4, tarefa 8, passo 5b):** se a prova ao vivo
der HTTP 401/403 com a sessão viva — o endereço exigiria um cabeçalho que o
`fetch` com `credentials: 'include'` não leva —, o caminho é voltar
`ROTA_SALDO = ""` (a build sai com o saldo digitado, como antes) e ler a
resposta que a própria Home recebe, escutando a Rede (como `_escutar`, em
`baixar_comprovantes/sicoob_baixar.py`), num plano à parte. Hoje um 401/403
aqui é lido como sessão caída (`SessaoPerdida`).
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .pendencias import _JS as _JS_FETCH        # o mesmo fetch, com a sessão do banco
from .sicoob_client import JS_TEXTOS_DA_CONTA, SessaoPerdida, conta_do_cabecalho

BASE = "https://ib.sicoob.com.br/sicoobnet"

# ======================= O ENDEREÇO E O EXTRATOR =========================
# Medidos em 22/10/2026 na Home do SicoobNet, com o dono logado.
# "{conta}" em ROTA_SALDO ou em valor de texto do CORPO_SALDO vira os
# DÍGITOS da conta pedida (hoje não se usa: a conta é a selecionada na tela).
# Nenhum número de conta real aqui: o repo é público.
ROTA_SALDO = "/api/home/obter-informacoes-widget-movimentacoes-inicio"
METODO_SALDO = "GET"
CORPO_SALDO = None              # dict do POST, ou None
#: Número JSON, sem sinal confiável: o sinal vem de CAMPO_SINAL.
CAMPO_SALDO = "contaCorrente.extratoContaCorrente.resumo.saldoEmContaCorrente"
#: "C" (credor) ou "D" (devedor → saldo negativo). "" = o número já tem sinal.
CAMPO_SINAL = "contaCorrente.extratoContaCorrente.resumo.naturezaSaldoRes"
SINAIS_DEVEDORES = ("D", "-", "DEVEDOR", "NEGATIVO")
SINAIS_CREDORES = ("C", "+", "CREDOR", "POSITIVO")
#: Número JSON da conta da resposta; "" = a resposta não diz.
CAMPO_CONTA = "contaCorrente.extratoContaCorrente.cabecalho.numContaCorrente"
#: Booleano: true = o banco não conseguiu montar o movimento desta conta.
CAMPO_ERRO = "contaCorrente.erroServicoMovimentoContaCorrente"
# =========================================================================

NAO_MEDIDO = ("a leitura do saldo do Sicoob ainda não está ligada (o "
              "endereço do banco não foi medido) — digite o saldo à mão")
SESSAO_CAIU = ("a sessão do Sicoob caiu antes desta conta — faça o login de "
               "novo e clique em Reler Sicoob")
INTERROMPIDA = "leitura interrompida antes desta conta"
#: A conta não está na lista do login aberto (é de OUTRO acesso do Sicoob).
FORA_DESTE_LOGIN = "esta conta não aparece neste login do Sicoob"
EM_NENHUM_ACESSO = "esta conta não aparece em nenhum dos dois acessos lidos do Sicoob"
ERRO_DO_SERVICO = ("o Sicoob disse que não conseguiu ler o movimento desta "
                   "conta agora — clique em Reler Sicoob ou digite o saldo")
CENTAVO = Decimal("0.01")
FORMATO_MUDOU = ("duas contas seguidas vieram num formato que o app não "
                 "conhece — o formato do Sicoob provavelmente mudou; digite o "
                 "saldo à mão e peça para medir de novo")
_ENDERECO_SUMIU = (404, 405, 410)
_VERDADE = ("true", "s", "sim", "1")


class SaldoFalhou(RuntimeError):
    """O saldo desta conta não foi lido; a mensagem diz o porquê."""


class EnderecoMudou(SaldoFalhou):
    """O Sicoob mudou o endereço ou o formato: vale para TODAS as contas."""


class FormatoDaConta(SaldoFalhou):
    """A resposta DESTA conta veio sem um campo, com saldo que não é número
    ou natureza que não é C nem D. Só esta conta fica sem ler; duas seguidas
    param a fila (`FORMATO_MUDOU`)."""


class ContaNaoEncontrada(SaldoFalhou):
    pass


class OutraConta(SaldoFalhou):
    pass


@dataclass(frozen=True)
class Lido:
    numero: str
    saldo: Decimal | None = None
    lido_em: _dt.datetime | None = None
    motivo: str = ""
    #: De que leitura veio: 1 = o login aberto primeiro; 2 = o OUTRO acesso
    #: do Sicoob (`ler_em_dois_acessos`).
    acesso: int = 1

    @property
    def ok(self) -> bool:
        return self.saldo is not None


def so_digitos(texto) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def mesma_conta(da_resposta, pedida: str) -> bool:
    """A conta que a resposta diz é a pedida?

    O cadastro escreve a conta do Sicoob com o dígito ("12.345-6"). O
    `numContaCorrente` da resposta é um NÚMERO JSON com todos os dígitos,
    INCLUINDO o DV (conferido ao vivo em 22/10/2026: "12.345-6" → 123456),
    como o `contaCorrente` das pendências. A comparação é de igualdade exata
    dos dígitos; só os zeros à esquerda são ignorados, porque um número JSON
    não os carrega. Sem o DV não vale, e resposta sem número é RECUSADA
    (falha fechada)."""
    r = so_digitos(da_resposta).lstrip("0")
    p = so_digitos(pedida).lstrip("0")
    return bool(r) and r == p


def medido() -> bool:
    return bool(ROTA_SALDO and CAMPO_SALDO)


def exigir_medido() -> None:
    if not medido():
        raise SaldoFalhou(NAO_MEDIDO)


def _com_conta(valor, digitos: str):
    if isinstance(valor, str):
        return valor.replace("{conta}", digitos)
    if isinstance(valor, dict):
        return {k: _com_conta(v, digitos) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_com_conta(v, digitos) for v in valor]
    return valor


def montar_pedido(numero: str) -> tuple[str, str, dict | None]:
    d = so_digitos(numero)
    corpo = None if CORPO_SALDO is None else _com_conta(CORPO_SALDO, d)
    return BASE + ROTA_SALDO.replace("{conta}", d), METODO_SALDO, corpo


def no_caminho(dado, caminho: str):
    atual = dado
    for parte in caminho.split("."):
        if isinstance(atual, list) and parte.isdigit() and int(parte) < len(atual):
            atual = atual[int(parte)]
        elif isinstance(atual, dict) and parte in atual:
            atual = atual[parte]
        else:
            raise EnderecoMudou(f"a resposta do saldo não tem mais '{caminho}' — "
                                "o formato do Sicoob mudou")
    return atual


def para_decimal(valor) -> Decimal:
    if isinstance(valor, bool) or valor is None:
        raise EnderecoMudou(f"o saldo veio como {valor!r}, que não é número")
    if isinstance(valor, (int, Decimal)):
        d = Decimal(valor)
    elif isinstance(valor, float):                 # não chega: parse_float=Decimal
        d = Decimal(str(valor))
    elif isinstance(valor, str):
        t = valor.replace("R$", "").replace("\xa0", "").replace(" ", "")
        if "," in t:
            t = t.replace(".", "").replace(",", ".")
        try:
            d = Decimal(t)
        except InvalidOperation:
            raise EnderecoMudou(f"o saldo veio como '{valor[:30]}', que não é número") from None
    else:
        raise EnderecoMudou("o saldo veio num formato que não é número")
    if not d.is_finite():
        raise EnderecoMudou("o saldo veio como um número inválido")
    return d.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def extrair_saldo(dado) -> Decimal:
    saldo = para_decimal(no_caminho(dado, CAMPO_SALDO))
    if not CAMPO_SINAL or saldo == 0:
        return saldo
    sinal = str(no_caminho(dado, CAMPO_SINAL) or "").strip().upper()
    if sinal in SINAIS_DEVEDORES:
        return -abs(saldo)
    if sinal in SINAIS_CREDORES:
        return saldo
    # Sem saber se é credor ou devedor, o número pode estar com o sinal
    # trocado: dinheiro errado na tela. Melhor não ler.
    raise EnderecoMudou(f"o indicador de saldo ('{CAMPO_SINAL}') veio como "
                        f"'{sinal[:10]}', nem credor nem devedor — o formato "
                        "do Sicoob mudou")


def extrair_conta(dado) -> str:
    return so_digitos(no_caminho(dado, CAMPO_CONTA)) if CAMPO_CONTA else ""


def _erro_do_servico(dado) -> bool:
    if not CAMPO_ERRO:
        return False
    try:
        v = no_caminho(dado, CAMPO_ERRO)
    except EnderecoMudou:
        return False                    # sem a bandeira: o saldo decide
    return v is True or str(v).strip().lower() in _VERDADE


def interpretar(resposta: dict, numero: str, url_da_pagina: str = "") -> Decimal:
    status = int(resposta.get("status") or 0)
    corpo = resposta.get("corpo") or ""
    if status in (401, 403) or "#/login" in url_da_pagina or "#/operador" in url_da_pagina:
        raise SessaoPerdida(SESSAO_CAIU)
    if status in _ENDERECO_SUMIU:
        raise EnderecoMudou(
            f"o Sicoob não reconhece mais o endereço do saldo ({ROTA_SALDO}, "
            f"HTTP {status}) — a tela do banco mudou; digite o saldo à mão e "
            "peça para medir de novo")
    if status != 200:
        raise SaldoFalhou(f"o Sicoob respondeu HTTP {status}: {corpo.strip()[:200]}")
    try:
        dado = json.loads(corpo, parse_float=Decimal)
    except ValueError:
        raise EnderecoMudou("o endereço do saldo não devolveu JSON — a tela "
                            "do banco mudou") from None
    # Daqui para baixo, formato ruim é desta conta: a fila segue (ou para em
    # `ler_contas`, se duas seguidas vierem assim). Só param a fila sozinhos
    # a sessão caída, o endereço que sumiu e a resposta que não é JSON.
    try:
        if _erro_do_servico(dado):
            raise SaldoFalhou(ERRO_DO_SERVICO)
        if CAMPO_CONTA and not mesma_conta(extrair_conta(dado), numero):
            raise OutraConta(f"pedi o saldo da conta {numero} e a resposta é de "
                             "outra conta (ou não diz qual) — não uso")
        return extrair_saldo(dado)
    except EnderecoMudou as e:
        raise FormatoDaConta(str(e)) from None


def conta_na_tela(page) -> str:
    textos = page.evaluate(JS_TEXTOS_DA_CONTA) or {}
    return conta_do_cabecalho(textos.get("novo"), textos.get("corpo", ""))


def ler_saldo(page, numero: str) -> Decimal:
    """O saldo da conta `numero`, que tem de ser a ABERTA na tela."""
    exigir_medido()
    na_tela = conta_na_tela(page)
    if so_digitos(na_tela) != so_digitos(numero):
        raise OutraConta(
            f"pedi a conta {numero} e a tela está em "
            f"{na_tela or '(não consegui ler)'} — não leio o saldo de outra "
            "conta com o nome desta")
    url, metodo, corpo = montar_pedido(numero)
    return interpretar(page.evaluate(_JS_FETCH, [url, metodo, corpo]), numero,
                       getattr(page, "url", ""))


def como_na_lista(lista, numero: str) -> str | None:
    """O número como o seletor do Sicoob o ESCREVE, achado pelos dígitos.

    `SicoobClient.acessar_conta` procura a linha pelo TEXTO: o cadastro com
    "12345-6" não achava "12.345-6" e a conta saía "não aparece neste login"
    (prova ao vivo de 22/10/2026). Zeros à esquerda não contam, como em
    `mesma_conta`."""
    alvo = so_digitos(numero).lstrip("0")
    if not alvo:
        return None
    for n in lista or []:
        if so_digitos(n).lstrip("0") == alvo:
            return n
    return None


def _acessar(cli, numero: str) -> bool:
    """Entra pelo número da LISTA quando ele bate em dígitos; sem achar (a
    lista não reconheceu a linha), tenta como veio — o caminho de antes."""
    escrito = como_na_lista(cli.listar_contas(), numero) or numero
    return cli.acessar_conta(escrito)


def entrar(cli, numero: str) -> None:
    """Como `pendencias.ler_conta`: o ⇄ some depois de várias trocas, e um
    `reload` o traz de volta — tenta uma segunda vez. Sessão que caiu não volta
    com reload: sobe."""
    try:
        entrou = _acessar(cli, numero)
    except SessaoPerdida:
        raise
    except Exception:                                        # noqa: BLE001
        cli.page.reload()
        cli.page.wait_for_timeout(3000)
        entrou = _acessar(cli, numero)
    if not entrou:
        raise ContaNaoEncontrada(FORA_DESTE_LOGIN)


def _primeira_linha(erro) -> str:
    texto = (str(erro or "").strip().splitlines() or [""])[0].strip()
    return texto[:160] or type(erro).__name__


def ler_contas(cli, numeros, *, agora=_dt.datetime.now, parar=lambda: False,
               log=print, progresso=lambda feitas, total: None) -> list[Lido]:
    """Uma `Lido` por conta, NA ORDEM pedida; nenhuma some. Sessão caída e
    endereço mudado param a fila (as que faltavam levam o porquê); o resto
    falha só na conta."""
    exigir_medido()
    vistos, fila = set(), []
    for n in numeros:
        if so_digitos(n) and so_digitos(n) not in vistos:
            vistos.add(so_digitos(n))
            fila.append(n)
    lidos: list[Lido] = []
    formato_ruim_seguido = 0
    for i, numero in enumerate(fila):
        if parar():
            lidos += [Lido(n, motivo=INTERROMPIDA) for n in fila[i:]]
            break
        progresso(i, len(fila))
        try:
            entrar(cli, numero)
            valor = ler_saldo(cli.page, numero)
        except SessaoPerdida:
            log(SESSAO_CAIU)
            lidos += [Lido(n, motivo=SESSAO_CAIU) for n in fila[i:]]
            break
        except EnderecoMudou as e:
            log(str(e))
            lidos += [Lido(n, motivo=str(e)) for n in fila[i:]]
            break
        except FormatoDaConta as e:
            formato_ruim_seguido += 1
            if formato_ruim_seguido >= 2:
                parou = str(EnderecoMudou(FORMATO_MUDOU))
                log(parou)
                lidos += [Lido(n, motivo=parou) for n in fila[i:]]
                break
            lidos.append(Lido(numero, motivo=_primeira_linha(e)))
            log(f"{numero}: não lido — {_primeira_linha(e)}")
        except Exception as e:                               # noqa: BLE001
            formato_ruim_seguido = 0
            lidos.append(Lido(numero, motivo=_primeira_linha(e)))
            log(f"{numero}: não lido — {_primeira_linha(e)}")
        else:
            formato_ruim_seguido = 0
            lidos.append(Lido(numero, valor, agora()))
            log(f"{numero}: lido")
    progresso(len(fila), len(fila))
    return lidos


def ler_em_dois_acessos(abrir, numeros, *, perguntar, agora=_dt.datetime.now,
                        parar=lambda: False, log=print,
                        progresso=lambda feitas, total: None) -> list[Lido]:
    """`ler_contas` no login que o dono abrir e, se sobrar conta "não aparece
    neste login", no OUTRO acesso do Sicoob — só as que faltaram.

    Um login do Sicoob enxerga as contas de UM grupo; as de outra empresa
    ficam noutro acesso, com outro QR Code (prova ao vivo de 22/10/2026: 19
    lidas, 4 de outro acesso; o dono: "tem que abrir outro QR code pra ler
    depois que finaliza"). `abrir()` devolve o gerenciador de contexto do
    Chrome do Sicoob do app (o MESMO perfil); trocar de acesso é fechar este
    Chrome e abrir de novo, que pede o login outra vez — o caminho provado de
    `baixar_comprovantes.sicoob_baixar.baixar_em_varios_logins`: o SicoobNet
    não tem um "sair" que o app já use, e nada aqui digita senha nem clica em
    aceite. `perguntar(faltam)` é a tela (padrão "sim"); "não" deixa as contas
    "não lidas", como antes.

    O resultado vem NA ORDEM pedida, cada uma com o `acesso` de onde veio. Se
    o segundo login falhar (tempo esgotado, Chrome fechado), a primeira
    leitura NÃO se perde: as que faltavam levam o porquê."""
    with abrir() as cli:
        cli.aguardar_login()
        lidos = ler_contas(cli, numeros, agora=agora, parar=parar, log=log,
                           progresso=progresso)
    faltam = [l.numero for l in lidos if l.motivo == FORA_DESTE_LOGIN]
    if not faltam or parar() or not perguntar(faltam):
        return lidos
    log(f"{len(faltam)} conta(s) de outro acesso — abrindo o Chrome do Sicoob de "
        "novo; entre com o outro acesso (QR Code).")
    try:
        with abrir() as cli:
            cli.aguardar_login()
            segunda = ler_contas(cli, faltam, agora=agora, parar=parar, log=log,
                                 progresso=progresso)
        segunda = [replace(l, acesso=2, motivo=EM_NENHUM_ACESSO
                           if l.motivo == FORA_DESTE_LOGIN else l.motivo)
                   for l in segunda]
    except Exception as e:                                   # noqa: BLE001
        motivo = f"o outro acesso do Sicoob não entrou: {_primeira_linha(e)}"
        log(motivo)
        segunda = [Lido(n, motivo=motivo, acesso=2) for n in faltam]
    por_digitos = {so_digitos(l.numero): l for l in segunda}
    return [por_digitos.get(so_digitos(l.numero), l) for l in lidos]
