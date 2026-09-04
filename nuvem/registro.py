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

        if itens:
            rest.inserir("remessa_item", self._token, [{
                "remessa_id": remessa_id,
                "seu_numero": i.seu_numero,
                "valor": str(i.valor),
                "favorecido": i.favorecido,
                "produto": i.produto,
                "identificador": i.identificador,
                "referencia": i.referencia,
            } for i in itens], devolver=False)

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

    def aplicar_retorno(self, convenio: str, nsa: int, respostas: dict,
                        *, estado: str = "") -> int:
        """Grava o que o banco respondeu de cada pagamento.

        `respostas` é {seu_numero: codigo}. Devolve quantos itens receberam
        resposta. Item que o retorno não citou fica como estava — silêncio do
        banco não é resposta, e sobrescrevê-lo com vazio apagaria o que um
        retorno anterior já tinha dito.
        """
        remessa = next((r for r in self.remessas(convenio=convenio)
                        if int(r.get("nsa") or 0) == int(nsa)), None)
        if remessa is None:
            raise rest.RecusadoPeloBanco(
                f"a remessa {nsa} do convênio {convenio} não está registrada")

        agora = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        quantos = 0
        for item in remessa.get("remessa_item") or []:
            codigo = respostas.get(str(item.get("seu_numero") or "").strip())
            if not codigo:
                continue
            rest.alterar("remessa_item", self._token, f"id=eq.{item['id']}",
                         {"retorno_codigo": codigo, "retorno_em": agora})
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

    def envio_de(self, identificador: str):
        return self._nuvem.envio_de(identificador)

    def envio_da_referencia(self, referencia: str):
        return self._nuvem.envio_da_referencia(referencia)

    def remessas(self, *, convenio: str | None = None):
        return self._nuvem.remessas(convenio=convenio)

    def aplicar_retorno(self, convenio: str, nsa: int, respostas: dict,
                        *, estado: str = ""):
        """Só na nuvem: o espelho local não guarda resposta do banco.

        O `cnab240.Historico` sabe marcar a remessa inteira (`marcar`), mas
        não tem onde pôr o código de ocorrência de CADA pagamento — e é isso
        que responde "por que este não pagou?" meses depois."""
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
