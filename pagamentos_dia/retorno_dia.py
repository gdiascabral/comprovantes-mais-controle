# -*- coding: utf-8 -*-
"""O que o banco respondeu — lido do arquivo de retorno e casado com a remessa.

Sem tela e sem rede: recebe o caminho do arquivo e o registro das remessas,
devolve o que a aba vai mostrar. É o mesmo arranjo do `remessa_dia.py`, e é o
que permite testar a regra inteira sem abrir janela nem falar com o banco.

**O primeiro retorno quase nunca é o desfecho.** No fluxo desta empresa quem
gera o arquivo não é quem assina: o app agenda, e o master entra no SicoobNet
e libera. Por isso o retorno do mesmo dia costuma vir com `PD` (pendente de
assinatura) em tudo — isso é o estado normal, não defeito, e a tela precisa
dizer isso com todas as letras. O desfecho real exige baixar o retorno DE NOVO
depois da assinatura.

**E quase nunca é UM arquivo.** São até 18 contas, lidas duas vezes cada, e o
SicoobNet ("Gerenciamento de Arquivos → Obter Retorno") baixa vários de uma
vez — soltos ou dentro de um `.zip`. Por isso a regra deste módulo é escrita
sobre TEXTO (`ler_conteudo`) e não sobre caminho: o membro de um zip não tem
caminho no disco, e a alternativa seria extraí-lo para um arquivo temporário.

**O zip é lido em MEMÓRIA, e isso não é elegância.** `zipfile.read(nome)`
devolve os bytes do membro sem tocar o disco. Extrair para `tempfile` traria
um módulo a mais para a conta do PyInstaller — o exe só contém o que alguém
importa a partir do `motor.py` (ver a v1.0.71 no CLAUDE.md) — e espalharia
retorno de banco por pasta temporária. Um `.RET` de 18 contas cabe folgado na
memória: são linhas de 240 caracteres.
"""
from __future__ import annotations

import datetime as _dt
import re
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

#: O CNAB 240 é texto de 240 posições em latin-1. `latin-1` também é a única
#: codificação que vai e volta sem perder byte nenhum (todo valor de 0 a 255
#: tem um caractere), e é isso que permite guardar a CÓPIA do arquivo a partir
#: do texto já lido, byte a byte igual ao que o banco mandou.
CODIFICACAO = "latin-1"


@dataclass
class Linha:
    """Um pagamento do retorno, já casado (ou não) com o que foi enviado."""
    seu_numero: str
    favorecido: str
    valor: Decimal
    estado: str                      # "ok" | "pendente" | "rejeitado" | "?"
    motivos: str
    #: Os códigos de ocorrência, na ordem em que o banco os mandou. O
    #: `motivos` é para GENTE ler ("AG=conta invalida; BD=saldo insuficiente")
    #: e o `codigos` é para gravar — e são coisas diferentes o bastante para
    #: não se derivar uma da outra. Enquanto só existia o `motivos`, quem
    #: precisava dos códigos os arrancava de volta da frase
    #: (`motivos.split("=")[0]`), o que dava certo com UMA ocorrência e
    #: guardava só a primeira quando o banco mandava duas.
    codigos: list[str] = field(default_factory=list)
    #: O id do lançamento no ERP, quando o "seu número" achou par na remessa.
    #: Vazio significa que o banco devolveu algo que não saiu por aqui.
    referencia: str = ""
    #: Quando o dinheiro saiu de verdade (campo 22.3A do retorno). É a data
    #: que a baixa no ERP tem de levar: usar "hoje" registraria o pagamento no
    #: dia em que alguém leu o arquivo, e não no dia em que ele aconteceu.
    data_real: "_dt.date | None" = None

    @property
    def rotulo(self) -> str:
        return {"ok": "PAGO", "pendente": "AGUARDA ASSINATURA",
                "rejeitado": "REJEITADO"}.get(self.estado, "SEM RESPOSTA")


@dataclass
class Falha:
    """Um arquivo que não deu para ler, sem derrubar os outros.

    Lendo 18 retornos de uma vez, um zip corrompido ou uma remessa escolhida
    por engano não pode custar a leitura dos 17 que estavam bons — quem
    escolheu os arquivos já fechou o diálogo e não vai repetir a escolha.
    """
    origem: str
    motivo: str


@dataclass
class Resumo:
    #: O convênio e o NSA **DA REMESSA REGISTRADA** — não necessariamente os
    #: que o header do arquivo traz. São eles que vão para o
    #: `aplicar_retorno(convenio, nsa, …)` e para o `nome_da_copia`, e é por
    #: isso que eles têm de ser os do REGISTRO: o retorno tem de ir para a
    #: remessa certa, e é a linha do registro que tem os lançamentos do ERP.
    #: Sem casamento nenhum (`remessa_desconhecida`), continuam sendo o que o
    #: arquivo diz — é tudo o que se sabe.
    convenio: str
    nsa: int
    empresa: str
    linhas: list[Linha] = field(default_factory=list)
    #: Pagamentos que estavam na remessa e NÃO vieram no retorno. É a pergunta
    #: que ninguém faz e que o arquivo não responde sozinho: o banco devolve o
    #: que processou, e o que sumiu no caminho não aparece em lugar nenhum.
    faltando: list[str] = field(default_factory=list)
    #: A remessa não foi encontrada no registro central — por convênio+NSA
    #: NEM pelos "seus números". Só aí: enquanto um dos dois caminhos acha, a
    #: tela guarda o resultado e dá baixa como sempre.
    remessa_desconhecida: bool = False
    #: O convênio e o número de arquivo que o HEADER do retorno traz — o que o
    #: arquivo DIZ, contra o que o registro SABE. Iguais no caso normal; quando
    #: diferem, são eles que explicam à pessoa por que a tela está falando de
    #: outro número que não o da tela do banco.
    convenio_do_header: str = ""
    nsa_do_header: int = 0
    #: A remessa foi reencontrada pelo "seu número", e não pelo header. Vale
    #: aviso na tela: os números que o arquivo mostra não são os que o registro
    #: guarda, e quem confere precisa saber disso antes de estranhar.
    casado_pelo_seu_numero: bool = False
    #: De onde este resumo veio: o nome do arquivo, ou `zip.zip/membro.RET`
    #: quando saiu de dentro de um compactado. Com 18 retornos numa lista só,
    #: "arquivo nº 000031" não basta para alguém achar de novo o que leu.
    origem: str = ""
    #: A agência e a conta do HEADER do retorno. É o que separa uma linha da
    #: outra na tela quando várias empresas vêm juntas — e o que nomeia a
    #: cópia guardada.
    agencia: str = ""
    conta: str = ""
    #: A pasta onde mora o `.REM` que esta remessa gerou, vinda do registro
    #: central (`remessa.arquivo`). É para lá que a CÓPIA do retorno vai:
    #: pergunta e resposta na mesma pasta. Vazio quando a remessa é
    #: desconhecida ou quando o registro não guardou o caminho.
    pasta_da_remessa: str = ""
    #: Os bytes do arquivo lido, para poderem ser guardados depois. O membro
    #: de um zip não existe no disco, então quem quiser copiá-lo tem de tê-lo
    #: em mãos — reler pelo caminho não é opção.
    conteudo: bytes = b""

    def quantos(self, estado: str) -> int:
        return sum(1 for l in self.linhas if l.estado == estado)

    @property
    def total(self) -> Decimal:
        return sum((l.valor for l in self.linhas), Decimal("0"))

    @property
    def estado_da_remessa(self) -> str:
        """Como marcar a remessa no registro, a partir do que veio.

        `processado` só quando TODOS deram certo. Enquanto houver um pendente,
        a remessa continua `enviado` — marcar como processada esconderia que
        falta assinatura, e a remessa sairia da lista de coisas a acompanhar
        com dinheiro ainda parado.

        **O que sai daqui é SEMPRE um estado VIVO** — um dos
        `cnab240.historico.ESTADOS_VIVOS`, que é a mesma tupla que o
        `nuvem.registro` usa —, e isso é regra de dinheiro, não de arrumação.
        Quem pergunta "este boleto já saiu?" (`remessa_dia._ja_enviado`) só
        enxerga item de remessa VIVA: um estado fora da lista some com a
        remessa inteira dessa pergunta, e os pagamentos que o banco PAGOU
        voltam marcáveis na geração seguinte. Rejeição de UM item não devolve
        aos outros o direito de sair de novo — foi o que o `"com_erro"` fazia,
        e ele não existia em lista nenhuma (a coluna `estado` do banco não tem
        `check`, então a marcação era aceita em silêncio).

        O outro lado da moeda, e é o lado seguro: com a remessa viva, o item
        REJEITADO também fica bloqueado, porque `_ja_enviado` casa por código
        de barras/referência do ITEM. Bloqueia demais, nunca de menos.
        Reenviar hoje exige `descartar` a remessa (sem tela ainda); o reenvio
        por item, lendo o `retorno_codigo` de cada um, é outro PR."""
        if not self.linhas:
            return "enviado"
        if self.quantos("rejeitado"):
            return "rejeitado"
        if self.quantos("pendente") or self.quantos("?"):
            return "enviado"
        return "processado"


def _estado(pagamento) -> str:
    if pagamento.sem_ocorrencia:
        return "?"
    if pagamento.sucesso:
        return "ok"
    if pagamento.pendente:
        return "pendente"
    return "rejeitado"


def ler_conteudo(texto: str, nome: str = "", historico=None) -> Resumo:
    """A regra inteira, sobre o TEXTO do arquivo já lido.

    É aqui que mora tudo o que o `ler()` fazia; ele virou a casca que abre o
    arquivo. A separação existe por causa do zip: o membro de um compactado
    não tem caminho no disco, e a única alternativa a esta função seria
    extraí-lo para um arquivo temporário só para poder relê-lo.

    `historico` é o registro das remessas (o `nuvem.registro.Espelhado`).
    Passando-o, cada linha ganha o id do lançamento no ERP, a lista do que
    ficou faltando e a pasta onde o `.REM` foi gravado. Sem ele, o resumo sai
    só com o que o arquivo diz.
    """
    from cnab240 import ler_retorno

    arquivo = ler_retorno(texto)
    if not arquivo.e_retorno:
        raise ValueError(
            "este arquivo não é um retorno: o código do header diz que é "
            "remessa. Baixe o arquivo de RETORNO no SicoobNet.")

    resumo = Resumo(convenio=arquivo.convenio, nsa=arquivo.nsa,
                    empresa=arquivo.empresa, origem=nome,
                    agencia=arquivo.agencia, conta=arquivo.conta,
                    convenio_do_header=arquivo.convenio,
                    nsa_do_header=arquivo.nsa,
                    # `latin-1` vai e volta sem perder byte, então isto é o
                    # arquivo original — é o que a cópia vai gravar.
                    conteudo=texto.encode(CODIFICACAO, "replace"))

    # A lista dos pagamentos é MATERIALIZADA antes de perguntar ao registro, e
    # não é detalhe: `arquivo.pagamentos()` é um gerador que percorre os
    # registros do lote uma vez só, e o segundo caminho do casamento precisa
    # dos "seus números" ANTES de as linhas serem montadas.
    pagamentos = list(arquivo.pagamentos())
    seus = [(p.seu_numero or "").strip() for p in pagamentos]

    # O de-para "seu número" -> id do lançamento vem da remessa registrada.
    enviados: dict[str, str] = {}
    if historico is not None:
        achado = _itens_da_remessa(historico, arquivo.convenio, arquivo.nsa,
                                   seus)
        if achado is None:
            resumo.remessa_desconhecida = True
        else:
            enviados = achado.itens
            resumo.pasta_da_remessa = achado.pasta
            # Os do REGISTRO, e não os do header: é para esta remessa que o
            # `aplicar_retorno` vai gravar e é o nome dela que a cópia leva.
            resumo.convenio = achado.convenio
            resumo.nsa = achado.nsa
            resumo.casado_pelo_seu_numero = achado.pelo_seu_numero

    vistos = set()
    for pagamento, seu in zip(pagamentos, seus):
        vistos.add(seu)
        ocorrencias = list(pagamento.ocorrencias)
        resumo.linhas.append(Linha(
            seu_numero=seu,
            favorecido=(pagamento.favorecido or "").strip(),
            valor=pagamento.valor,
            estado=_estado(pagamento),
            motivos="; ".join(f"{c}={d}" for c, d in ocorrencias),
            codigos=[str(c) for c, _d in ocorrencias],
            referencia=enviados.get(seu, ""),
            data_real=getattr(pagamento, "data_real", None),
        ))

    resumo.faltando = sorted(s for s in enviados if s not in vistos)
    return resumo


def ler(caminho: str | Path, historico=None) -> Resumo:
    """Lê UM arquivo do disco e casa com a remessa que o gerou.

    Casca sobre `ler_conteudo`: abre, decodifica e entrega o texto. Quem
    precisa ler vários (ou de dentro de um zip) chama `ler_varios`.
    """
    caminho = Path(caminho)
    texto = caminho.read_bytes().decode(CODIFICACAO)
    return ler_conteudo(texto, caminho.name, historico)


def ler_varios(caminhos, historico=None) -> "list[Resumo | Falha]":
    """Lê `.RET`/`.TXT` e `.zip` numa passada, na ordem em que vieram.

    Devolve `Resumo` para o que deu e `Falha` para o que não deu — **um
    arquivo ruim não derruba os outros**. É o ponto inteiro desta função: o
    dono baixa os retornos de até 18 contas de uma vez no SicoobNet, e um zip
    corrompido no meio da lista não pode custar a leitura dos que estavam
    bons, porque a essa altura o diálogo de escolha já foi fechado.

    Os membros do zip saem em ordem de NOME, e não na ordem física de dentro
    do arquivo: a do zip é a ordem em que o compactador gravou, que não quer
    dizer nada para quem lê.
    """
    saida: list = []
    for caminho in caminhos:
        caminho = Path(caminho)
        if caminho.suffix.lower() == ".zip":
            saida.extend(_ler_zip(caminho, historico))
            continue
        try:
            saida.append(ler(caminho, historico))
        except Exception as e:
            saida.append(Falha(caminho.name, _motivo(e)))
    return saida


def _motivo(erro: Exception) -> str:
    """A frase que vai para a `Falha`, em português.

    O resto já vem em português — é mensagem escrita aqui ou no `cnab240` —,
    mas as duas do sistema de arquivos chegam em inglês e com um errno na
    frente, e são o caso mais provável de todos: o retorno mora na pasta de
    downloads, que é onde as coisas somem.
    """
    if isinstance(erro, FileNotFoundError):
        return ("não achei o arquivo — ele foi movido ou apagado depois de "
                "ser escolhido")
    if isinstance(erro, PermissionError):
        return ("o Windows não deixou abrir o arquivo — ele pode estar aberto "
                "em outro programa")
    return str(erro) or type(erro).__name__


def _ler_zip(caminho: Path, historico) -> "list[Resumo | Falha]":
    """Cada membro do zip, lido em MEMÓRIA.

    Sem `tempfile` e sem extrair para disco, e isso é regra da casa, não
    gosto: o exe do usuário só contém os módulos da biblioteca padrão que
    alguém importa a partir do `motor.py`, e um import novo custa exe novo
    (ver a v1.0.71 no CLAUDE.md). O `zipfile` já está lá — o `atualizador.py`
    o usa para trocar o `codigo.zip`.
    """
    try:
        with zipfile.ZipFile(caminho) as compactado:
            nomes = sorted(nome for nome in compactado.namelist()
                           if not nome.endswith("/"))
            if not nomes:
                return [Falha(caminho.name, "o arquivo compactado está vazio")]
            saida: list = []
            for nome in nomes:
                origem = f"{caminho.name}/{nome}"
                try:
                    texto = compactado.read(nome).decode(CODIFICACAO)
                    saida.append(ler_conteudo(texto, origem, historico))
                except Exception as e:
                    saida.append(Falha(origem, _motivo(e)))
            return saida
    except Exception as e:
        # Zip corrompido, arquivo que não é zip, disco ilegível: uma falha só,
        # pelo compactado inteiro. Não há membro para culpar.
        return [Falha(caminho.name, _motivo(e))]


# --------------------------------------------------------------------------
# A cópia do `.RET` — o arquivo que ninguém guardava
# --------------------------------------------------------------------------

def nome_da_copia(resumo: Resumo, quando: _dt.datetime) -> str:
    """`RET_ACME_4321-123456_000031_20260904-1512.RET`.

    A mesma limpeza de nome do `remessa_dia.nome_do_arquivo` (só letras e
    dígitos, o resto vira `-`), pelo mesmo motivo: o nome da empresa vem de
    cadastro digitado por gente e o Windows recusa metade da pontuação.

    O carimbo de data e hora está aí porque **o mesmo NSA é lido duas vezes**:
    o retorno do dia, com tudo `PD`, e o de depois da assinatura. Os dois são
    prova de coisas diferentes e nenhum substitui o outro.
    """
    empresa = _limpo(resumo.empresa) or "EMPRESA"
    conta = _limpo(f"{resumo.agencia}-{resumo.conta}") or "CONTA"
    return f"RET_{empresa}_{conta}_{resumo.nsa:06d}_{quando:%Y%m%d-%H%M}.RET"


def _limpo(texto: str) -> str:
    """Um pedaço de nome de arquivo que o Windows aceita, em maiúsculas."""
    return re.sub(r"[^A-Za-z0-9]+", "-", texto or "").strip("-").upper()


def guardar_copia(conteudo: bytes, pasta, nome: str) -> Path:
    """Grava a cópia do retorno e devolve onde ela ficou. **Nunca sobrescreve.**

    Havendo um arquivo com o mesmo nome, tenta `-2`, `-3`… A primeira cópia é
    a prova de que o arquivo foi ACEITO pelo banco, e o segundo retorno do
    mesmo NSA na mesma hora não pode apagá-la — é o mesmo defeito que o
    `retorno_historico` fechou do lado do banco de dados.

    A criação é exclusiva (`open(..., "xb")`), e não "olhar se existe e depois
    gravar": entre o olhar e o gravar cabe a outra máquina.
    """
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    base, sufixo = Path(nome).stem, Path(nome).suffix
    for tentativa in range(1, 100):
        alvo = pasta / (nome if tentativa == 1 else
                        f"{base}-{tentativa}{sufixo}")
        try:
            with open(alvo, "xb") as saida:
                saida.write(conteudo)
            return alvo
        except FileExistsError:
            continue
    raise OSError(f"já existem 99 cópias de {nome} em {pasta}")


def respostas_para_registro(resumo: Resumo) -> dict:
    """{seu_numero: {"codigo": ..., "estado": ...}} para o registro central.

    O que a aba manda gravar, montado aqui e não na tela: a classificação é
    julgamento de retorno (`Linha.estado`), e traduzi-la de novo lá na frente
    seria uma segunda tabela de códigos de ocorrência, envelhecendo em
    silêncio ao lado desta.

    Todos os códigos, separados por `;`, e não só o primeiro: o banco manda
    mais de uma ocorrência por pagamento, e a que explica a recusa nem sempre
    é a de cima.

    **Linha sem ocorrência fica de fora**, e essa é a regra que já existe no
    `aplicar_retorno`: silêncio do banco não é resposta, e gravá-lo como vazio
    apagaria o que um retorno anterior tinha dito.
    """
    return {l.seu_numero: {"codigo": ";".join(l.codigos), "estado": l.estado}
            for l in resumo.linhas if l.codigos}


@dataclass(frozen=True)
class _Achado:
    """A remessa registrada de que este retorno fala, e como se chegou nela."""
    #: `{seu_numero: referencia}` — o de-para com os lançamentos do ERP. Vazio
    #: quer dizer "conheço a remessa, e ela não tinha item nenhum", que é
    #: diferente de não achar remessa (aí não há `_Achado`).
    itens: dict
    #: A pasta do `.REM` que saiu, para a cópia do retorno cair ao lado dele.
    pasta: str
    #: O convênio e o NSA DA REMESSA REGISTRADA. Iguais aos do header no
    #: caminho de sempre; os do registro quando o casamento foi pelo "seu
    #: número", que é justamente o caso em que os dois divergem.
    convenio: str
    nsa: int
    pelo_seu_numero: bool


def _itens_da_remessa(historico, convenio: str, nsa: int,
                      seus: "list[str]") -> "_Achado | None":
    """De que remessa registrada este retorno fala. `None` quando não dá saber.

    São DOIS caminhos, e o segundo entrou em 04/09/2026:

    1. **convênio + NSA do header**, que é o de sempre e resolve o dia normal;
    2. **os "seus números" do arquivo**, quando o primeiro falha.

    O caminho 1 falha em casos reais: retorno de remessa gerada por outra
    máquina antes do registro central, convênio reescrito no painel, NSA
    ajustado à mão. Até aqui isso virava `remessa_desconhecida` — a tela lia o
    arquivo e não guardava nada, nem dava baixa, porque a `referencia` de cada
    linha (o id do lançamento no ERP) só existe com a remessa conhecida.

    O caminho 2 usa a chave melhor que existe para isso: o "seu número" é
    NOSSO (`yymmdd-NNNN[-OC…]`, 20 posições que nós definimos e o banco
    devolve idênticas), único no dia entre todas as contas e todas as máquinas
    desde o índice `remessa_item_seu_numero_unico_no_dia`, e o `remessa_item`
    o guarda com a `remessa` ligada. Quem decide se dá para responder é o
    registro (`remessa_dos_seus_numeros`), que exige que TODOS os números
    achados caiam na MESMA remessa — a repetição de antes do índice existe no
    histórico, e adivinhar aqui é aplicar o retorno na remessa errada.

    `None` e um `_Achado` de itens vazios querem dizer coisas diferentes: o
    primeiro é "não sei qual remessa é esta" e o segundo é "conheço, e ela não
    tinha item nenhum".

    A pasta vem junto porque sai da MESMA linha: o registro guarda o caminho
    do `.REM` que saiu (`remessa.arquivo`), e é a pasta dele que recebe a
    cópia do retorno. Buscá-la depois seria uma segunda consulta pela mesma
    remessa. Ela sai vazia quando o registro não tem o caminho — remessa
    gerada antes de o campo existir, ou gravada por uma versão que não o
    preenchia."""
    try:
        remessas = historico.remessas(convenio=convenio)
    except Exception:
        remessas = []
    for r in remessas:
        if int(r.get("nsa") or 0) == int(nsa):
            return _do_registro(r, convenio, int(nsa), pelo_seu_numero=False)

    # O segundo caminho é OFERTA, não exigência: um registro que não saiba
    # responder a esta pergunta (versão antiga, dublê de teste) volta a se
    # comportar exatamente como antes deste PR.
    perguntar = getattr(historico, "remessa_dos_seus_numeros", None)
    if perguntar is None:
        return None
    try:
        linha = perguntar([s for s in seus if s])
    except Exception:
        # Falhar aqui não pode custar a leitura do arquivo: o caminho 1 já
        # falhou, e o desfecho sem este caminho era `remessa_desconhecida` —
        # que continua sendo o desfecho.
        return None
    if not linha:
        return None
    return _do_registro(linha, str(linha.get("convenio") or ""),
                        int(linha.get("nsa") or 0), pelo_seu_numero=True)


def _do_registro(linha: dict, convenio: str, nsa: int, *,
                 pelo_seu_numero: bool) -> _Achado:
    """A linha da remessa como o registro a devolve, virada em `_Achado`."""
    itens = linha.get("remessa_item") or linha.get("itens") or []
    arquivo = str(linha.get("arquivo") or "").strip()
    return _Achado(
        itens={str(i.get("seu_numero") or "").strip():
               str(i.get("referencia") or "") for i in itens},
        pasta=str(Path(arquivo).parent) if arquivo else "",
        convenio=convenio,
        nsa=nsa,
        pelo_seu_numero=pelo_seu_numero)
