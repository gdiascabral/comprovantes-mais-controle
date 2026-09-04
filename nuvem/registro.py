# -*- coding: utf-8 -*-
"""O registro das remessas CNAB — o que precisa ser UM para as duas máquinas.

O `cnab240.Historico` continua existindo e continua sendo gravado: ele é o
espelho local, legível, que sobrevive ao Supabase sumir. O que mudou é **quem
manda no NSA**.

Por que ele não podia continuar mandando: a trava do histórico é um arquivo
`.lock` ao lado do `remessas.json`, e protege dois processos na MESMA pasta.
Duas máquinas têm dois arquivos, cada uma com a sua trava, e as duas leem
"último NSA = 5" antes de qualquer uma gravar 6. A prova disso já existia sem
precisar de duas pessoas: nesta máquina, a instalação dizia que o próximo era
1 e a pasta de código dizia 2.

**Reservar e espiar são coisas diferentes**, e a separação não é preciosismo:
a janela de conferência mostra o número antes de gerar, e se mostrar
reservasse, abrir a janela e desistir queimaria um NSA por vez. Então
`proximo_nsa()` só olha e `alocar_nsa()` consome.

Aqui não há cache, ao contrário do `cadastro.py`. O valor inteiro deste
módulo é a resposta ser a mesma nas duas máquinas no mesmo instante; um cache
diria "pelo que eu sei, ninguém usou o 6" — indistinguível de "ninguém usou o
6" na hora de decidir, e é assim que se paga duas vezes. Sem banco, gerar
remessa **para**, e parar é o desfecho certo.
"""
from __future__ import annotations

import datetime as _dt

#: Estados em que a remessa ainda "vale" — os pagamentos dela contam como
#: enviados. É a MESMA tupla do `cnab240.historico`, IMPORTADA e não copiada:
#: enquanto foram duas listas escritas à mão, elas divergiram em silêncio, e a
#: divergência custava dinheiro. A de cá tinha "aceito" (que não existe no
#: cnab240) e NÃO tinha "rejeitado" (que existe lá desde sempre) — então um
#: retorno com uma rejeição tirava a remessa inteira da pergunta "isto já foi
#: mandado?" e liberava para sair de novo, inclusive os pagamentos que o banco
#: já tinha pago.
#:
#: **"aceito" SAIU em vez de entrar no cnab240**, e a escolha é a que não mexe
#: em nada já gravado: ninguém nunca escreveu esse estado. Quem grava é
#: `registrar` ("gerado"), `marcar` e o retorno — e o espelho local
#: (`cnab240.Historico.marcar`) sempre RECUSOU "aceito", logo ele jamais
#: poderia ter sido usado sem estourar. As remessas reais estão em "gerado",
#: "enviado" e "descartado", todas contempladas dos dois lados. Inventá-lo do
#: outro lado seria alargar o que o `marcar` local aceita para atender a uma
#: lista que ninguém consultava.
#:
#: Importar no topo não cria ciclo: o `cnab240` é stdlib pura e não importa
#: nada do app (`tests/test_cnab240_pacote.py` cobra isso por AST). Também não
#: pesa: quem monta o `Espelhado` (`remessa_dia._historico`) importa o
#: `cnab240` na linha de cima, sempre.
from cnab240.historico import ESTADOS_VIVOS

from . import rest

import util

log = util.log(__name__)

#: As colunas que a visão do dia (`pagamentos_dia.painel_dia`) precisa, e só
#: elas. `remessas()` pede `*,remessa_item(*)`, que traz `sha256`,
#: `documento`, `identificador` e `referencia` de cada pagamento — dado da
#: empresa que esta tela não mostra e que, com 18 contas, é a diferença entre
#: uma resposta pequena e uma resposta grande a cada "Recarregar".
COLUNAS_DO_PAINEL = ("convenio,nsa,empresa,agencia,conta,estado,observacao,"
                     "gerado_em,arquivo,"
                     "remessa_item(valor,retorno_estado,retorno_em)")

#: Quantos "seus números" cabem num filtro `in.(…)` por vez. O limite que
#: aperta não é o do banco, é o TAMANHO DA URL: um retorno de 18 contas traz
#: centenas de pagamentos, cada "seu número" tem 20 posições, e uma URL de
#: alguns milhares de caracteres é recusada por proxy antes de chegar ao
#: PostgREST — o que apareceria como erro de rede numa consulta que estava
#: certa. Cem por vez é folgado dos dois lados.
LOTE_DE_SEUS_NUMEROS = 100

#: O que pode entrar num filtro `in.(…)` sem aspas e sem susto. O "seu número"
#: é `yymmdd-NNNN[-OC…]`, então este conjunto o cobre inteiro — e o que sobra
#: dele não vem de nós: vem do ARQUIVO que o banco devolveu, que num dia ruim
#: é um `.RET` truncado ou de outro layout. Vírgula, parêntese ou aspas ali
#: dentro não seriam um "seu número" que não achamos, seriam um filtro
#: diferente do que se quis escrever.
_LETRAS_DO_SEU_NUMERO = frozenset(
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-")


def _limites_do_dia(quando: _dt.date) -> tuple[str, str]:
    """O começo e o fim do dia LOCAL, em ISO com offset, prontos para a URL.

    `gerado_em` é `timestamptz`: o banco guarda o instante e o devolve em UTC.
    Filtrar por `gerado_em=like.2026-09-04*` compararia texto de UTC com uma
    data que a pessoa leu no relógio dela — e no fuso do Brasil isso perde
    toda remessa gerada depois das 21h (que em UTC já é o dia seguinte) e
    inclui as da noite anterior. Por isso os limites saem de
    `datetime.combine(dia, 00:00).astimezone()`, que carimba o offset local
    de verdade, inclusive o do horário de verão se ele voltar.

    O `+` do offset vira `%2B`. Não é zelo com a biblioteca de HTTP: um `+`
    cru numa query string é decodificado como ESPAÇO do outro lado, e o filtro
    chegaria com a hora do offset separada por um espaço — recusa do
    PostgREST, ou pior, comparação com outro instante. Aqui o offset é
    negativo e o caso não aparece; ele aparece no dia em que alguém rodar isto
    de outro lugar do mundo.
    """
    inicio = _dt.datetime.combine(quando, _dt.time()).astimezone()
    fim = _dt.datetime.combine(quando + _dt.timedelta(days=1),
                               _dt.time()).astimezone()
    return (inicio.isoformat().replace("+", "%2B"),
            fim.isoformat().replace("+", "%2B"))


def _seus_numeros_limpos(seus) -> list[str]:
    """Os "seus números" que dá para perguntar, sem repetição e na ordem.

    Descartar o que não passa no crivo não muda a resposta: um número que não
    dá para perguntar é um número que não vai ser achado, e a regra do
    `remessa_dos_seus_numeros` já exige que os ACHADOS caiam todos na mesma
    remessa.
    """
    limpos: list[str] = []
    vistos: set[str] = set()
    for cru in seus or ():
        seu = str(cru or "").strip()
        if not seu or seu in vistos or len(seu) > 40:
            continue
        if set(seu) <= _LETRAS_DO_SEU_NUMERO:
            vistos.add(seu)
            limpos.append(seu)
    return limpos


class Envio:
    """Onde um pagamento já saiu. O bastante para o app montar o recado.

    Tem os mesmos nomes de campo que o `cnab240.RemessaGerada` usa no
    `_ja_enviado` (`nsa`, `gerado_em`), de propósito: quem pergunta não
    precisa saber se a resposta veio do arquivo ou do banco.
    """

    __slots__ = ("nsa", "gerado_em", "convenio", "estado", "seu_numero")

    def __init__(self, linha: dict) -> None:
        remessa = linha.get("remessa") or {}
        self.nsa = int(remessa.get("nsa") or 0)
        self.convenio = remessa.get("convenio") or ""
        self.estado = remessa.get("estado") or ""
        self.seu_numero = linha.get("seu_numero") or ""
        quando = remessa.get("gerado_em") or ""
        try:
            self.gerado_em = _dt.datetime.fromisoformat(quando) if quando else None
        except ValueError:
            self.gerado_em = None


class Registro:
    """A conversa com o registro central. Um por sessão do app."""

    def __init__(self, token: str) -> None:
        self._token = token

    # ------------------------------------------------------------- contador

    def ultimo_nsa(self, convenio: str) -> int:
        """O último número usado. Não reserva nada."""
        linhas = rest.ler("remessa_contador", self._token,
                          colunas="ultimo_nsa",
                          filtro=f"convenio=eq.{convenio}")
        return int(linhas[0]["ultimo_nsa"]) if linhas else 0

    def proximo_nsa(self, convenio: str) -> int:
        """Que número SAIRIA agora — para mostrar na tela, sem consumir.

        Entre esta leitura e a geração, outra máquina pode ter reservado: por
        isso quem gera chama `alocar_nsa`, e não isto."""
        return self.ultimo_nsa(convenio) + 1

    def alocar_nsa(self, convenio: str) -> int:
        """RESERVA o próximo número e o devolve. Cada chamada consome um.

        Chamado ANTES de montar o arquivo, não depois: o número entra no
        conteúdo do arquivo, e reservá-lo depois deixaria uma janela em que
        outra máquina pega o mesmo."""
        return int(rest.chamar("alocar_nsa", self._token, p_convenio=convenio))

    def ajustar_nsa(self, convenio: str, novo_ultimo: int, *, motivo: str) -> int:
        """Corrige o contador à mão, com o motivo por escrito. Devolve o valor
        anterior. O banco recusa motivo vazio — é ele que explica o furo na
        sequência para quem for olhar depois."""
        return int(rest.chamar("ajustar_nsa", self._token, p_convenio=convenio,
                               p_novo=int(novo_ultimo), p_motivo=motivo))

    def maior_ordem_do_dia(self, quando: _dt.date) -> int:
        """A maior ordem do dia já gravada no "seu número". UMA linha, UMA ida.

        Antes, quem numerava varria `remessas()` — TODAS as remessas com todos
        os itens dentro, a cada geração (0,44 s com sete; 18 contas vezes os
        dias não cabe nisso). E, mesmo varrendo, era só uma LEITURA: duas
        máquinas gerando no mesmo instante liam o mesmo maior e repetiam. Quem
        impede a repetição agora é o índice único
        `remessa_item_seu_numero_unico_no_dia`; esta consulta existe para a
        recusa dele ser rara, não para ser a trava.

        **Sem filtro de convênio, de propósito**: a ordem é do DIA, de todas as
        contas e de todas as máquinas. É ela que o banco devolve no retorno para
        casar cada pagamento, e o índice único que a protege também não olha
        convênio — numerar por conta daria dois pagamentos com o mesmo número e
        o arquivo recusado no INSERT. Sem filtro de ESTADO pelo mesmo motivo: o
        índice alcança a remessa descartada também.

        Erro de rede LEVANTA, e é a diferença que este método traz: devolver 0
        aqui é a segunda remessa do dia recomeçando em 0001.
        """
        from cnab240.historico import ordem_do_dia    # importado aqui para o
                                                      # módulo não puxar o
                                                      # cnab240 sem uso
        # `*` é o curinga do `like` no PostgREST (ele o troca por `%`); `order`
        # e `limit` viajam no filtro, como já fazem em `_procurar`.
        linhas = rest.ler("remessa_item", self._token, colunas="seu_numero",
                          filtro=(f"seu_numero=like.{quando:%y%m%d}-*"
                                  f"&order=seu_numero.desc&limit=1"))
        if not linhas:
            return 0
        return ordem_do_dia(linhas[0].get("seu_numero") or "", quando)

    # ------------------------------------------------------------- remessas

    def registrar(self, remessa, *, caminho_arquivo=None,
                  referencias: dict[str, str] | None = None) -> None:
        """Grava a remessa e seus itens.

        Recebe o mesmo `ArquivoRemessa` que o `cnab240.Historico.registrar`
        recebe, para os dois serem alimentados do mesmo jeito no app.
        """
        import hashlib

        from cnab240.historico import itens_de

        cabecalho = remessa.empresa
        itens = itens_de(remessa, referencias)

        # O sha256 do conteúdo REAL do arquivo. É o que responde, meses
        # depois, se o `.REM` que está na pasta é mesmo o que foi registrado —
        # a única prova possível quando alguém pergunta "foi este que subi?".
        try:
            sha = hashlib.sha256(remessa.texto().encode("latin-1")).hexdigest()
        except Exception:
            log.warning("calculando o sha256 da remessa nsa %s para registrar "
                        "na nuvem", getattr(remessa, "nsa", "?"),
                        exc_info=True)
            sha = ""

        linha = {
            "convenio": str(cabecalho.convenio or ""),
            "nsa": int(remessa.nsa),
            "empresa": str(cabecalho.nome or ""),
            "documento": str(cabecalho.documento or ""),
            "agencia": str(cabecalho.agencia or ""),
            "conta": str(cabecalho.conta or ""),
            "arquivo": str(caminho_arquivo or ""),
            "sha256": sha,
            "estado": "gerado",
        }
        gravada = rest.inserir("remessa", self._token, [linha])
        if not gravada:
            raise rest.RecusadoPeloBanco("a remessa não foi gravada")
        remessa_id = gravada[0]["id"]

        if not itens:
            return

        try:
            rest.inserir("remessa_item", self._token, [{
                "remessa_id": remessa_id,
                "seu_numero": i.seu_numero,
                "valor": str(i.valor),
                "favorecido": i.favorecido,
                "produto": i.produto,
                "identificador": i.identificador,
                "referencia": i.referencia,
            } for i in itens], devolver=False)
        except Exception as e:
            # A corrida vira recusa LIMPA. São dois INSERTs, e desde o índice
            # único do "seu número" do dia o segundo pode ser recusado depois
            # de o primeiro ter passado: duas máquinas que leram a mesma "maior
            # ordem" montam arquivos com os mesmos números, e a segunda a
            # gravar perde os itens — com a linha da `remessa` já dentro e o
            # NSA já queimado.
            #
            # Sem isto, o que fica na nuvem é uma remessa `gerado` SEM ITEM
            # NENHUM: ela conta como envio vivo em toda consulta, não tem
            # de-para para o retorno do banco achar o caminho de volta, e nada
            # no registro diz por que ela está vazia. Marcá-la é best-effort —
            # se nem isso passar, a exceção original continua sendo a que
            # sobe, porque é ela que impede o `.tmp` de virar `.REM`.
            try:
                self.marcar(str(cabecalho.convenio or ""), int(remessa.nsa),
                            "descartado",
                            observacao=f"itens recusados pelo banco: {e}"[:400])
            except Exception:
                log.warning("marcando como descartada a remessa nsa %s, cujos "
                            "itens o banco recusou", getattr(remessa, "nsa", "?"),
                            exc_info=True)
            raise

    def marcar(self, convenio: str, nsa: int, estado: str,
               *, observacao: str = "") -> None:
        """Muda o estado de uma remessa (enviada, rejeitada, descartada).

        Os estados são os do `cnab240.historico.ESTADOS`, e só "descartado"
        tira a remessa da pergunta "isto já foi mandado?" — inclusive
        "rejeitado", que o retorno grava: rejeição de um item não devolve aos
        outros o direito de sair de novo."""
        mudancas = {"estado": estado}
        if observacao:
            mudancas["observacao"] = observacao
        rest.alterar("remessa", self._token,
                     f"convenio=eq.{convenio}&nsa=eq.{nsa}", mudancas)

    def remessas(self, *, convenio: str | None = None) -> list[dict]:
        """As remessas COM os itens dentro.

        Os itens vêm juntos porque quem pergunta por remessa quase sempre
        quer o de-para "seu número → id do lançamento" — é ele que faz o
        retorno do banco reencontrar o caminho de volta ao ERP. Buscar em
        duas viagens seria uma consulta por remessa."""
        filtro = f"convenio=eq.{convenio}" if convenio else ""
        return rest.ler("remessa", self._token,
                        colunas="*,remessa_item(*)", filtro=filtro)

    def remessas_do_dia(self, quando: _dt.date) -> list[dict]:
        """O que saiu HOJE, de TODAS as contas — numa consulta só.

        É a pergunta que `remessas(convenio=)` não responde: ela é por conta,
        e a visão do dia é o contrário disso — dezoito contas de uma vez, para
        se saber qual delas ainda não fechou. Fazê-la em dezoito idas seria
        dezoito viagens para montar uma tela que se recarrega a cada ação.

        Os itens vêm juntos (`remessa_item(…)`) porque é deles que saem as
        contagens de pago/aguardando/rejeitado — o `retorno_estado` que o
        retorno grava. Sem eles a tabela teria estado e mais nada, e "enviada"
        não distingue a conta que já foi paga da que está esperando
        assinatura.

        **Sem filtro de estado**, e a descartada aparece: uma remessa que
        alguém tirou da frente hoje é parte do que aconteceu hoje, e esconder
        as descartadas faria o painel dizer que um NSA sumiu.

        O `order` viaja no filtro, como já fazem `_procurar` e
        `maior_ordem_do_dia`. Ordenado pelo banco e não aqui: a ordem é a de
        quem gerou primeiro, e é ela que faz a lista corresponder à sequência
        do dia mesmo quando duas máquinas geraram ao mesmo tempo.
        """
        inicio, fim = _limites_do_dia(quando)
        return rest.ler("remessa", self._token, colunas=COLUNAS_DO_PAINEL,
                        filtro=(f"gerado_em=gte.{inicio}"
                                f"&gerado_em=lt.{fim}"
                                f"&order=gerado_em.asc"))

    def _linha_do_painel(self, convenio: str, nsa: int):
        """A remessa (uma só), já contada, para as regras de transição.

        **Relida do banco, e não recebida da tela.** As duas regras de
        `painel_dia` dependem dos ITENS — "tem algum pago?" —, e a tela pode
        estar aberta desde antes de alguém guardar o retorno noutra máquina.
        Decidir pelo que está na tabela é decidir pelo que era verdade quando
        a janela abriu.
        """
        from pagamentos_dia import painel_dia   # importado aqui: o `nuvem` é a
                                                # camada de baixo e não carrega
                                                # aba nenhuma para quem só
                                                # grava remessa
        linhas = rest.ler("remessa", self._token, colunas=COLUNAS_DO_PAINEL,
                          filtro=f"convenio=eq.{convenio}&nsa=eq.{int(nsa)}")
        if not linhas:
            raise rest.RecusadoPeloBanco(
                f"a remessa {nsa} do convênio {convenio} não está registrada")
        return painel_dia.linhas_do_dia(linhas)[0]

    def marcar_enviada(self, convenio: str, nsa: int) -> None:
        """"Subi este arquivo no SicoobNet" — o passo que o app não vê.

        Casca sobre `marcar`, e a casca é a regra: `painel_dia`
        `pode_marcar_enviada` só deixa de `gerado`. De qualquer outro estado a
        marca não acrescenta nada e pode TIRAR — sobre uma remessa já
        `processado`, ela apagaria o desfecho que o retorno gravou.
        """
        from pagamentos_dia import painel_dia

        linha = self._linha_do_painel(convenio, nsa)
        if not painel_dia.pode_marcar_enviada(linha):
            raise rest.RecusadoPeloBanco(
                f"a remessa {nsa} está como '{linha.estado}', e só uma remessa "
                f"'gerado' pode ser marcada como enviada")
        self.marcar(convenio, nsa, "enviado")

    def descartar(self, convenio: str, nsa: int, motivo: str) -> None:
        """Tira a remessa da pergunta "isto já foi mandado?" — com motivo.

        É a única transição que DEVOLVE dinheiro à fila: `descartado` é o
        único estado fora de `ESTADOS_VIVOS`, e `remessa_dia._ja_enviado` só
        enxerga item de remessa viva. Por isso as duas travas de
        `painel_dia.pode_descartar` são conferidas aqui, e não só no botão:
        um item PAGO recusa (seria autorizar o mesmo dinheiro a sair duas
        vezes) e motivo em branco recusa (o furo na sequência de NSA tem de
        ter explicação escrita, como no `ajustar_nsa`).

        A remessa é RELIDA antes de decidir — a regra do item pago precisa dos
        itens, e eles podem ter mudado desde que a tela abriu.
        """
        from pagamentos_dia import painel_dia

        linha = self._linha_do_painel(convenio, nsa)
        pode, recusa = painel_dia.pode_descartar(linha, motivo)
        if not pode:
            raise rest.RecusadoPeloBanco(recusa)
        self.marcar(convenio, nsa, "descartado",
                    observacao=painel_dia.observacao_do_descarte(motivo))

    def remessa_dos_seus_numeros(self, seus: list[str]) -> dict | None:
        """A remessa que gerou estes "seus números" — o segundo caminho do retorno.

        O primeiro caminho é o header do arquivo (convênio + NSA), e ele falha
        em casos reais: retorno de remessa gerada por outra máquina antes do
        registro central, convênio reescrito no painel, NSA ajustado à mão.
        O "seu número" é a chave melhor para esse segundo caminho porque ela é
        NOSSA: `yymmdd-NNNN[-OC…]`, 20 posições que nós definimos, que o banco
        devolve idênticas, e que o `remessa_item` guarda com a `remessa`
        ligada. Desde 04/09/2026 ela é única no dia entre todas as contas e
        todas as máquinas — o índice `remessa_item_seu_numero_unico_no_dia`.

        **Exige que TODOS os achados caiam na MESMA remessa**, e essa é a
        regra inteira. O índice é PARCIAL pela data (`criado_em >=
        2026-09-05`), porque o histórico é append-only e a repetição de
        20/08/2026 continua lá dentro — naquele dia a segunda remessa repetiu
        `260820-0004`…`0010`. Um "seu número" daquela época aponta para duas
        remessas, e escolher uma delas é aplicar o retorno na remessa errada:
        dar por pago o pagamento de outra conta e baixar o lançamento errado
        no ERP. Achando mais de uma remessa — ou nenhuma —, devolve `None` e
        quem chamou trata o retorno como de remessa desconhecida, que é o
        desfecho que já existia e que ninguém perde nada em ter.

        **Sem filtro de estado**, ao contrário do `_procurar`: uma remessa
        descartada que compartilhe o número não é para ser ignorada, é para
        ser a SEGUNDA candidata que faz esta consulta recusar. Aqui não se
        procura "onde este pagamento ainda vale"; procura-se "de que remessa
        este arquivo está falando", e ambiguidade é resposta.

        Devolve a linha da remessa COM os itens dentro — a mesma forma que
        `remessas()` entrega —, porque quem lê o retorno precisa do de-para
        inteiro: os itens que o banco NÃO citou é que dizem o que ficou
        faltando.
        """
        alvos = _seus_numeros_limpos(seus)
        if not alvos:
            return None

        achada: dict | None = None
        remessa_id = None
        for inicio in range(0, len(alvos), LOTE_DE_SEUS_NUMEROS):
            lote = alvos[inicio:inicio + LOTE_DE_SEUS_NUMEROS]
            linhas = rest.ler(
                "remessa_item", self._token,
                colunas="seu_numero,remessa_id,"
                        "remessa(id,convenio,nsa,estado,arquivo)",
                filtro=f"seu_numero=in.({','.join(lote)})")
            for linha in linhas:
                remessa = linha.get("remessa") or {}
                atual = linha.get("remessa_id")
                if atual is None:
                    atual = remessa.get("id")
                if atual is None:
                    continue
                if remessa_id is None:
                    remessa_id, achada = atual, remessa
                elif atual != remessa_id:
                    return None
        if achada is None:
            return None

        # Os itens vêm numa segunda ida, e não embutidos na primeira: o que se
        # quer aqui são TODOS os itens da remessa, e a consulta de cima traz só
        # os que o arquivo citou. `remessas(convenio=)` já pede
        # `remessa_item(*)` e já é a forma que quem lê o retorno sabe ler —
        # duas viagens no caminho raro valem menos que uma segunda montagem da
        # mesma linha.
        convenio = str(achada.get("convenio") or "")
        nsa = int(achada.get("nsa") or 0)
        if not convenio or not nsa:
            return None
        for r in self.remessas(convenio=convenio):
            if int(r.get("nsa") or 0) == nsa:
                return r
        return None

    def aplicar_retorno(self, convenio: str, nsa: int, respostas: dict,
                        *, estado: str = "") -> int:
        """Grava o que o banco respondeu de cada pagamento.

        `respostas` é `{seu_numero: {"codigo": ..., "estado": ...}}` — o que
        `retorno_dia.respostas_para_registro` monta. Uma string simples no
        lugar do dicionário continua valendo (vira `{"codigo": s, "estado":
        ""}`), para nenhum chamador antigo quebrar. Devolve quantos itens
        receberam resposta. Item que o retorno não citou fica como estava —
        silêncio do banco não é resposta, e sobrescrevê-lo com vazio apagaria
        o que um retorno anterior já tinha dito.

        **`retorno_codigo` é a resposta de AGORA e é sobrescrito; o
        `retorno_historico` nunca perde nada.** No fluxo desta empresa quem
        gera não é quem assina: o primeiro retorno vem `PD` (pendente de
        assinatura) e o segundo, depois de o master liberar, vem `00`. O `00`
        é a resposta certa para "e agora?", e escrevê-lo por cima do `PD`
        apagava a única prova de que o arquivo tinha sido ACEITO. Agora cada
        passagem acrescenta `AAAA-MM-DD HH:MM codigo=estado` ao histórico,
        separado por `;`, na frente do que já estava lá.

        **A limitação aceita, escrita para não ser redescoberta:** o append é
        ler-concatenar-gravar aqui no app, não um `||` do Postgres, então duas
        pessoas guardando o MESMO retorno no MESMO instante podem perder uma
        LINHA de histórico — a última gravação vence. Nunca se perde a
        resposta atual (as duas escrevem o mesmo `retorno_codigo`), e nada que
        mexe em dinheiro lê o histórico: quem decide o que baixar no ERP é
        `baixa_erp.separar`, sobre o `Resumo` lido do arquivo. Trocar isto por
        uma coluna que o banco concatena sozinho custaria uma função nova no
        Postgres, e o preço da corrida é uma linha de texto que ninguém usa
        para decidir.
        """
        remessa = next((r for r in self.remessas(convenio=convenio)
                        if int(r.get("nsa") or 0) == int(nsa)), None)
        if remessa is None:
            raise rest.RecusadoPeloBanco(
                f"a remessa {nsa} do convênio {convenio} não está registrada")

        instante = _dt.datetime.now(_dt.timezone.utc)
        agora = instante.isoformat(timespec="seconds")
        # O mesmo instante nas duas colunas, de propósito: `retorno_em` e a
        # última linha do histórico contradizerem-se seria a pior forma de
        # descobrir que uma das duas está errada.
        carimbo = instante.strftime("%Y-%m-%d %H:%M")
        quantos = 0
        for item in remessa.get("remessa_item") or []:
            resposta = respostas.get(str(item.get("seu_numero") or "").strip())
            if isinstance(resposta, str):
                resposta = {"codigo": resposta, "estado": ""}
            codigo = (resposta or {}).get("codigo") or ""
            if not codigo:
                continue
            marca = (resposta or {}).get("estado") or ""
            # O item já vem com a coluna: `remessas()` pede `remessa_item(*)`.
            # O `.get(..., "")` cobre o item gravado antes de a coluna existir.
            antes = str(item.get("retorno_historico") or "")
            entrada = f"{carimbo} {codigo}={marca}"
            rest.alterar("remessa_item", self._token, f"id=eq.{item['id']}",
                         {"retorno_codigo": codigo,
                          "retorno_em": agora,
                          "retorno_estado": marca,
                          "retorno_historico": f"{antes};{entrada}"
                                               if antes else entrada})
            quantos += 1

        if estado:
            self.marcar(convenio, nsa, estado)
        return quantos

    # ------------------------------------------- "isto já foi mandado?"

    def _procurar(self, coluna: str, valor: str) -> Envio | None:
        if not valor:
            return None
        vivos = ",".join(ESTADOS_VIVOS)
        linhas = rest.ler(
            "remessa_item", self._token,
            colunas="seu_numero,remessa(nsa,convenio,estado,gerado_em)",
            filtro=(f"{coluna}=eq.{valor}"
                    f"&remessa.estado=in.({vivos})"
                    f"&order=id.desc&limit=1"))
        # O PostgREST devolve a linha com `remessa: null` quando o filtro do
        # relacionamento não casa, em vez de omiti-la. Sem esta checagem, uma
        # remessa DESCARTADA passaria por envio vivo — e descartar existe
        # justamente para devolver o direito de reenviar.
        linhas = [l for l in linhas if l.get("remessa")]
        return Envio(linhas[0]) if linhas else None

    def envio_de(self, identificador: str) -> tuple[Envio, None] | None:
        """Este BOLETO já saiu? Procura pelo código de barras.

        Devolve uma tupla para ter a mesma forma do `cnab240.Historico`, que
        entrega `(remessa, item)` — quem chama só usa o primeiro."""
        achado = self._procurar("identificador", identificador)
        return (achado, None) if achado else None

    def envio_da_referencia(self, referencia: str) -> tuple[Envio, None] | None:
        """Este LANÇAMENTO já saiu? Procura pelo id do ERP.

        É a pergunta que pega o Pix, que não tem código de barras."""
        achado = self._procurar("referencia", referencia)
        return (achado, None) if achado else None


class Espelhado:
    """Grava nos DOIS: a nuvem manda, o arquivo local acompanha.

    A nuvem é a autoridade — dela sai o NSA e para ela vai a pergunta "já
    mandei isto?", porque essas duas precisam valer entre máquinas. O
    `remessas.json` continua sendo escrito porque é backup legível: se o
    projeto sumisse amanhã, o histórico de tudo que saiu continuaria em cada
    computador, em texto, sem depender de ninguém.

    Falha ao gravar o espelho **não derruba a operação**: o arquivo já foi
    gerado com um NSA que a nuvem reservou, e recusar a remessa por causa de
    um backup seria trocar o problema pequeno pelo grande.
    """

    def __init__(self, nuvem: Registro, local, avisar=None) -> None:
        self._nuvem = nuvem
        self._local = local
        self._avisar = avisar or (lambda _msg: None)

    def ultimo_nsa(self, convenio: str) -> int:
        return self._nuvem.ultimo_nsa(convenio)

    def proximo_nsa(self, convenio: str) -> int:
        return self._nuvem.proximo_nsa(convenio)

    def alocar_nsa(self, convenio: str) -> int:
        return self._nuvem.alocar_nsa(convenio)

    def maior_ordem_do_dia(self, quando: _dt.date) -> int:
        """Da NUVEM, como o NSA. O espelho local não tem voto aqui também: a
        ordem do dia precisa valer entre máquinas, e o arquivo local só conhece
        as remessas que saíram DESTE computador."""
        return self._nuvem.maior_ordem_do_dia(quando)

    def envio_de(self, identificador: str):
        return self._nuvem.envio_de(identificador)

    def envio_da_referencia(self, referencia: str):
        return self._nuvem.envio_da_referencia(referencia)

    def remessas(self, *, convenio: str | None = None):
        return self._nuvem.remessas(convenio=convenio)

    def remessas_do_dia(self, quando: _dt.date):
        """Da NUVEM, e aqui não há nem espelho a consultar: o painel do dia é
        sobre TODAS as máquinas, e o `remessas.json` só conhece as remessas
        que saíram desta."""
        return self._nuvem.remessas_do_dia(quando)

    def marcar_enviada(self, convenio: str, nsa: int):
        """A nuvem decide, o espelho acompanha — como em `marcar`.

        A regra é conferida lá (`Registro.marcar_enviada` relê a remessa), e
        aqui o local recebe o mesmo `marcar` que já recebe hoje: ele não tem
        voto e a falha dele não desfaz o que a nuvem gravou."""
        self._nuvem.marcar_enviada(convenio, nsa)
        try:
            self._local.marcar(convenio, nsa, "enviado")
        except Exception as e:
            self._avisar(f"marcado na nuvem, mas não no espelho local: {e}")

    def descartar(self, convenio: str, nsa: int, motivo: str):
        """Idem — e a MESMA observação nos dois lados.

        A frase sai de `painel_dia.observacao_do_descarte`, e não de duas
        redações: comparar o espelho com a nuvem (que é para isso que ele
        existe) não pode exigir traduzir um texto no outro."""
        from pagamentos_dia import painel_dia

        self._nuvem.descartar(convenio, nsa, motivo)
        try:
            self._local.marcar(convenio, nsa, "descartado",
                               observacao=painel_dia.observacao_do_descarte(motivo))
        except Exception as e:
            self._avisar(f"descartada na nuvem, mas não no espelho local: {e}")

    def remessa_dos_seus_numeros(self, seus: list[str]):
        """Da NUVEM, como o NSA e a ordem do dia.

        O espelho local tem o método (é a mesma pergunta sobre o
        `remessas.json`), mas só conhece as remessas que saíram DESTE
        computador — e o caso que este caminho existe para resolver é
        justamente o retorno de uma remessa gerada em OUTRA máquina."""
        return self._nuvem.remessa_dos_seus_numeros(seus)

    def aplicar_retorno(self, convenio: str, nsa: int, respostas: dict,
                        *, estado: str = ""):
        """Só na nuvem: o espelho local não guarda resposta do banco.

        O `cnab240.Historico` sabe marcar a remessa inteira (`marcar`), mas
        não tem onde pôr o código de ocorrência de CADA pagamento — e é isso
        que responde "por que este não pagou?" meses depois. Vale para as
        quatro colunas do item, histórico incluído: o espelho é backup do que
        SAIU, e o que o banco respondeu depois nunca esteve nele."""
        return self._nuvem.aplicar_retorno(convenio, nsa, respostas,
                                           estado=estado)

    def registrar(self, remessa, *, caminho_arquivo=None, referencias=None):
        # A nuvem PRIMEIRO: é ela que pode recusar (NSA repetido, "seu
        # número" duplicado), e é a recusa dela que tem de impedir o arquivo
        # de virar definitivo. O espelho vem depois justamente porque não
        # pode ter voto.
        self._nuvem.registrar(remessa, caminho_arquivo=caminho_arquivo,
                              referencias=referencias)
        try:
            self._local.registrar(remessa, caminho_arquivo=caminho_arquivo,
                                  referencias=referencias)
        except Exception as e:
            self._avisar(f"a remessa foi registrada na nuvem, mas o espelho "
                         f"local não pôde ser gravado: {e}")

    def marcar(self, convenio: str, nsa: int, estado: str, *, observacao=""):
        self._nuvem.marcar(convenio, nsa, estado, observacao=observacao)
        try:
            self._local.marcar(convenio, nsa, estado, observacao=observacao)
        except Exception as e:
            self._avisar(f"marcado na nuvem, mas não no espelho local: {e}")

    def ajustar_nsa(self, convenio: str, novo_ultimo: int, *, motivo: str):
        anterior = self._nuvem.ajustar_nsa(convenio, novo_ultimo, motivo=motivo)
        try:
            self._local.ajustar_nsa(convenio, novo_ultimo, motivo=motivo)
        except Exception as e:
            self._avisar(f"ajustado na nuvem, mas não no espelho local: {e}")
        return anterior
