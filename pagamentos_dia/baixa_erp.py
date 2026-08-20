# -*- coding: utf-8 -*-
"""Baixa no Mais Controle o que o banco disse que pagou.

O retorno já sabe quem foi pago e a qual lançamento cada pagamento pertence —
`retorno_dia.Linha` traz `estado` e `referencia`, e a referência é gravada lá
atrás, na geração da remessa. O que faltava era o outro lado: pedir ao ERP que
dê a baixa.

**De onde vieram os endereços.** Não de captura de tráfego — ela falhou duas
vezes, porque a janela automatizada é indistinguível da janela da pessoa e
ninguém sabia em qual estava clicando. Vieram do bundle público do próprio
ERP (`acessar.maiscontroleerp.com.br/react-app/mc-react-app.js`), onde cada
cliente de API aparece com a URL montada:

    GET   /payable-installments/{id}/default-paid   -> o corpo pré-preenchido
    POST  /payables/{id}/paids                      -> cria a baixa
    DELETE /payables/{id}/paids/{paidId}            -> desfaz

É o par simétrico de `POST /receipt-installments/{id}/receipts`, que
`aportes/mc_lancamentos.py` já usa para recebimento.

**O corpo vem do ERP, não daqui.** Pedimos o `default-paid` daquela parcela e
devolvemos o que ele deu, com a data trocada pela data real do pagamento.
Montar o corpo à mão seria fixar o formato de hoje e quebrar calado quando ele
mudar — e é dinheiro sendo baixado.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

LEGADO = "https://legacy-api.maiscontroleerp.com.br/maiscontrole/services"
NOVA = "https://prod-erp-api.maiscontroleerp.com.br"

#: Os dois hosts, na ordem em que são tentados. O legado vem primeiro porque é
#: onde o `receipt-installments` mora — e o `default-paid` é LEITURA, então
#: descobrir errando não escreve nada.
HOSTS = (LEGADO, NOVA)

#: Nomes que o ERP pode dar ao campo da data no corpo da baixa. O
#: `updatePaidDate` usa `payingDate` como parâmetro; o `trade-payables` usa
#: `markedPayingDate` no corpo. Procuramos os dois em vez de fixar um.
CAMPOS_DATA = ("payingDate", "paidDate", "markedPayingDate", "date")
#: Idem para o valor — usado só para CONFERIR, nunca para escrever.
CAMPOS_VALOR = ("value", "paidValue", "amount", "paymentValue")

#: Onde o valor pago é ESCRITO. O `default-paid` devolve `account`,
#: `documentNumber`, `payingDate`, `paymentMethod` e `responsible` — e nenhum
#: campo de valor. Mandando o corpo dele intacto, o ERP aceitou (HTTP 200) e
#: gravou uma baixa de R$ 0,00, com a parcela seguindo em aberto: o pior
#: desfecho possível, porque parece sucesso.
#:
#: Os nomes vêm do análogo que já funciona neste projeto: o recebimento, em
#: `aportes/mc_lancamentos.py`, manda `value` + `receivedValue` ao lado de
#: `receivingDate`. Aqui a data se chama `payingDate`, então o par é
#: `value` + `paidValue`. Os dois vão preenchidos com o MESMO número, como lá.
ESCREVER_VALOR = ("value", "paidValue")

#: A rota da baixa, medida contra o ERP em 20/08/2026:
#:
#:   POST {legado}/payables/{id}/paids              -> 404, nao existe
#:   POST {legado}/payable-installments/{id}/paids  -> 400, existe e faltava
#:                                                     `isWorkFilterApplied`
#:
#: O bundle do front chama isso de `createPaid` no cliente `/payables`, mas o
#: `/payables` dele resolve para outra raiz — quem manda e o que o servidor
#: respondeu. A que existe vem primeiro; a outra fica como rede, para o dia em
#: que o ERP mover a rota de volta.
ROTAS = ("/payable-installments", "/payables")

#: O ERP exige este parametro na query, e disse o nome dele na recusa. No front
#: o sinalizador equivalente (`useWorkFilter`) e verdadeiro quando ha uma obra
#: filtrando a tela; a baixa pelo retorno nao filtra por obra nenhuma.
PARAMS_BAIXA = "isWorkFilterApplied=false"

MOTIVO_SEM_REFERENCIA = ("o banco pagou, mas este pagamento não tem lançamento "
                         "ligado a ele no registro — baixe à mão")
MOTIVO_VALOR_DIVERGE = ("o valor da baixa ({erp}) não bate com o que o banco "
                        "pagou ({banco}) — confira antes de baixar")


@dataclass
class Resultado:
    """O desfecho de UMA baixa. Uma que falhe não fala pelas outras."""

    seu_numero: str
    favorecido: str
    ok: bool
    erro: str = ""
    #: Host que respondeu — vai para o log, é o que responde "onde isso mora?"
    host: str = ""
    #: True quando o ERP já tinha essa parcela baixada.
    ja_estava: bool = False
    #: O id da baixa criada, quando o ERP devolve. É por ele que se desfaz
    #: (`DELETE /payable-installments/{parcela}/paids/{este id}`) — e foi
    #: exatamente o que faltou quando a primeira baixa saiu zerada.
    paid_id: str = ""


@dataclass
class Separacao:
    """O que dá para baixar, e o que não dá — com o motivo, sempre."""

    baixaveis: list = field(default_factory=list)      # [Linha]
    de_fora: list = field(default_factory=list)        # [(Linha, motivo)]


def separar(resumo) -> Separacao:
    """Quem do retorno pode ser baixado.

    Só entra ocorrência de PAGO (`estado == "ok"`). Pendente de assinatura é o
    estado normal do mesmo dia — baixar ali seria dizer que saiu dinheiro que
    ainda não saiu. Rejeitado, com mais razão, fica de fora.

    Pago sem `referencia` aparece na lista de fora, com o motivo: o banco pagou
    e o app não sabe em qual lançamento mexer. Sumir com ele seria esconder um
    pagamento real que ficou em aberto no ERP.
    """
    saida = Separacao()
    for linha in getattr(resumo, "linhas", []):
        if linha.estado != "ok":
            continue
        if not (linha.referencia or "").strip():
            saida.de_fora.append((linha, MOTIVO_SEM_REFERENCIA))
            continue
        saida.baixaveis.append(linha)
    return saida


def _erro_de(resposta) -> str:
    if isinstance(resposta, dict) and resposta.get("__erro"):
        return str(resposta["__erro"])
    return ""


def _detalhe_de(resposta) -> str:
    """O que o ERP escreveu junto do erro — truncado, mas presente.

    A primeira baixa real morreu num "HTTP 404" sem mais nada, e diagnosticar
    exigiu voltar ao bundle do ERP. O corpo da recusa costuma dizer se o
    problema é a rota, o id ou o payload; jogá-lo fora é jogar fora a resposta.
    """
    if not isinstance(resposta, dict):
        return ""
    corpo = resposta.get("__corpo")
    if not corpo:
        return ""
    texto = str(corpo)
    return texto[:180] + ("..." if len(texto) > 180 else "")


def _achar(corpo: dict, nomes) -> str:
    for nome in nomes:
        if nome in corpo:
            return nome
    return ""


def _dinheiro(valor) -> float:
    try:
        return round(float(valor), 2)
    except (TypeError, ValueError):
        return 0.0


def corpo_da_baixa(padrao: dict, quando: _dt.date, valor=None) -> tuple[dict, str]:
    """O corpo do `default-paid` com a data real e o valor pago.

    Devolve `(corpo, aviso)`. O aviso não é vazio quando não se achou onde
    escrever a data: aí vale a data que o ERP escolheu, e quem lê o relatório
    precisa saber disso — silenciar deixaria a baixa com a data de hoje sem
    ninguém perceber.

    O valor é ESCRITO, não conferido: o `default-paid` não traz campo de valor
    nenhum, e sem ele a baixa sai zerada com a parcela seguindo em aberto.
    """
    corpo = dict(padrao)
    if valor is not None:
        pago = _dinheiro(valor)
        for campo_valor in ESCREVER_VALOR:
            corpo[campo_valor] = pago
    campo = _achar(corpo, CAMPOS_DATA)
    if not campo:
        return corpo, ("não achei o campo da data no corpo que o ERP devolveu; "
                       "a baixa saiu com a data que ele mesmo sugeriu")
    corpo[campo] = quando.strftime("%Y-%m-%d")
    return corpo, ""


def conferir_valor(padrao: dict, valor_do_banco) -> str:
    """"" quando bate (ou quando não dá para comparar).

    Comparar é barato e evita o caso feio: o banco pagou parcial, o ERP
    propõe baixar o total, e a baixa fecharia uma parcela que continua aberta.
    Não achando o campo, não inventamos conferência — devolvemos vazio e
    seguimos, que é o comportamento de hoje.
    """
    campo = _achar(padrao, CAMPOS_VALOR)
    if not campo or valor_do_banco is None:
        return ""
    erp, banco = _dinheiro(padrao[campo]), _dinheiro(valor_do_banco)
    if not erp or not banco or abs(erp - banco) < 0.01:
        return ""
    return MOTIVO_VALOR_DIVERGE.format(erp=f"R$ {erp:,.2f}",
                                       banco=f"R$ {banco:,.2f}")


def baixar_uma(transporte, linha, quando: _dt.date, *, hosts=HOSTS,
               log=print) -> Resultado:
    """Baixa UM pagamento. Nunca levanta: devolve o desfecho.

    `transporte` precisa de dois métodos, `_buscar(url)` e `postar(url, corpo)`
    — é a interface do `mc_catalogos.Catalogos`, que fala de dentro da página
    logada. Depender só dos dois deixa a regra testável sem navegador.
    """
    parcela = linha.referencia
    padrao = None
    host_ok = ""
    for host in hosts:
        try:
            resposta = transporte._buscar(
                f"{host}/payable-installments/{parcela}/default-paid")
        except Exception as e:
            log(f"    {host}: {e}")
            continue
        erro = _erro_de(resposta)
        if erro:
            # 404 aqui é "não é este host"; qualquer outro é problema de
            # verdade e não adianta tentar o vizinho.
            if erro.startswith("404"):
                continue
            return Resultado(linha.seu_numero, linha.favorecido, False,
                             erro=f"o ERP recusou a consulta (HTTP {erro})",
                             host=host)
        if isinstance(resposta, dict):
            padrao, host_ok = resposta, host
            break

    if padrao is None:
        return Resultado(linha.seu_numero, linha.favorecido, False,
                         erro="não achei o endereço da baixa em nenhum dos "
                              "hosts conhecidos")

    # Só os NOMES dos campos: se a próxima recusa for de payload e não de
    # rota, é isto que diz o que o ERP esperava. Valor e conta não vão para o
    # log — é dinheiro de gente, e o log fica na tela e no arquivo.
    log(f"    o ERP devolveu: {', '.join(sorted(padrao)) or '(corpo vazio)'}")

    divergencia = conferir_valor(padrao, getattr(linha, "valor", None))
    if divergencia:
        return Resultado(linha.seu_numero, linha.favorecido, False,
                         erro=divergencia, host=host_ok)

    # A data do BANCO manda. `quando` é só a rede: retorno velho sem o campo
    # 22.3A preenchido cairia em "sem data", e aí vale o dia da leitura.
    corpo, aviso = corpo_da_baixa(padrao,
                                  getattr(linha, "data_real", None) or quando,
                                  getattr(linha, "valor", None))

    # O host do `default-paid` NÃO decide o host da baixa. Na primeira tentativa
    # real (20/08/2026) o `GET` passou no legado e o `POST` voltou 404 ali
    # mesmo: `/payable-installments` e `/payables` são clientes diferentes no
    # front do ERP, e nada garante que compartilhem a raiz. 404 é "esta rota
    # não existe aqui" — nada foi criado, então tentar o vizinho é seguro.
    # Qualquer outro código PARA a tentativa: repetir um POST que o servidor
    # entendeu é o caminho para baixar o mesmo pagamento duas vezes.
    # E nem a rota é certa. O `default-paid` mora no cliente
    # `/payable-installments` e o `createPaid` no cliente `/payables` — dois
    # clientes distintos no front do ERP, e a primeira tentativa real mostrou
    # que o segundo não responde onde o primeiro respondeu. Tentamos as duas
    # rotas nos dois hosts, sempre parando no primeiro que NÃO for 404.
    hospedes = [host_ok] + [h for h in hosts if h != host_ok]
    tentativas = [f"{h}{c}/{parcela}/paids?{PARAMS_BAIXA}"
                  for h in hospedes
                  for c in ROTAS]
    ultimo_erro, ultimo_detalhe, url = "", "", ""
    for url in tentativas:
        log(f"    baixando em {url}")
        resposta = transporte.postar(url, corpo)
        erro = _erro_de(resposta)
        if not erro:
            criado = (resposta or {}).get("id", "") if isinstance(resposta, dict) else ""
            return Resultado(linha.seu_numero, linha.favorecido, True,
                             erro=aviso, host=url, paid_id=str(criado))
        ultimo_erro, ultimo_detalhe = erro, _detalhe_de(resposta)
        if not erro.startswith("404"):
            break

    recado = f"o ERP recusou a baixa (HTTP {ultimo_erro}) em {url}"
    if ultimo_detalhe:
        recado += f" — o ERP disse: {ultimo_detalhe}"
    return Resultado(linha.seu_numero, linha.favorecido, False,
                     erro=recado, host=host_ok)


def baixar(transporte, linhas, quando: _dt.date, *, hosts=HOSTS,
           log=print) -> list[Resultado]:
    """Baixa cada uma, em ordem, e devolve um resultado por pagamento.

    Uma baixa que falha não impede as seguintes: o dia tem quinze pagamentos e
    parar no terceiro deixaria doze pagos sem baixa, sem ninguém saber quais.
    """
    resultados = []
    for linha in linhas:
        r = baixar_uma(transporte, linha, quando, hosts=hosts, log=log)
        resultados.append(r)
        log(f"  {'ok  ' if r.ok else 'FALHOU'} {linha.seu_numero} "
            f"{linha.favorecido[:28]}" + (f" — {r.erro}" if r.erro else ""))
    return resultados
