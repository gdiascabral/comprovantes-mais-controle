# -*- coding: utf-8 -*-
"""Costura as peças: recebimentos -> imóveis -> obra -> contrato -> destino.

Não sabe que existe interface. Recebe a `MCApi` de uma sessão aberta e devolve
uma lista de `Achado` — um por casa que recebeu no mês, cada um dizendo o que
foi resolvido e o que faltou.

`revisao` é campo de primeira classe, não exceção: uma casa sem contrato, sem
obra ou sem empresa é um resultado normal do mês, e a aba mostra o motivo. Só
erro de infraestrutura (sessão caída, API fora) sobe como exceção.

A ordem das duas metades tem uma razão prática: o `downloadUrl` dos anexos é
URL pré-assinada do S3 com `Expires` curto, então **listar e baixar têm de
acontecer na mesma execução**. Por isso `levantar()` só monta a lista e
`arquivar()` baixa logo em seguida, em vez de guardar URLs para depois.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import util

from . import conferencia as conf
from . import distrato as dist
from .destino import (caminho_longo, empresa_de, mesmo_contrato_na_pasta,
                      nome_arquivo, pasta_do_contrato)
from .escolha import candidatos_distintos, contrato_de, distratos_da_casa
from .leitura import PAGINAS_INICIAIS
from .regras import Imovel, imoveis_do_mes

#: Até quantos candidatos em disputa o pipeline baixa para comparar. Acima
#: disso a obra está bagunçada demais para decidir sem gente.
MAXIMO_PARA_DESEMPATAR = 4

#: Casa com distrato: até quantos contratos a busca baixa e lê para separar
#: por comprador. Acima disso a pessoa escolhe à mão.
MAXIMO_COM_DISTRATO = 6

#: Quantos distratos da casa a busca baixa e lê (o texto inteiro) para dizer
#: qual contrato foi desfeito.
MAXIMO_DE_DISTRATOS = 3


@dataclass
class Achado:
    """Uma casa que recebeu no mês, com tudo que se sabe dela."""

    imovel: Imovel
    obra_id: str = ""
    cliente_erp: str = ""
    empresa: str = ""
    cnpj: str = ""                  # da empresa de destino, para a vendedora
    razao_social: str = ""
    endereco: dict = field(default_factory=dict)
    anexo: dict = field(default_factory=dict)
    #: Todos os anexos da obra, como vieram do ERP. É o que a janela de
    #: resolver mostra quando o app não soube escolher sozinho — antes esta
    #: lista era lida e jogada fora, e a pessoa ficava sem saída pela tela.
    anexos_da_obra: list = field(default_factory=list)
    destino: Path | None = None
    revisao: str = ""
    #: Entra nesta rodada de arquivamento. Quem decide é a aba (a marcação da
    #: tabela); o padrão é False para ninguém arquivar por esquecimento.
    marcado: bool = False
    contrato_manual: bool = False
    empresa_manual: bool = False
    resultado_conferencia: dict = field(default_factory=dict)
    leitura: str = ""               # "camada de texto", "OCR"...
    arquivado: bool = False
    ja_existia: bool = False        # o mesmo arquivo já estava na pasta
    # Casa com distrato. Todos os padrões deixam a casa sem distrato igual a
    # antes: uma linha, nada baixado na busca, o nome de sempre.
    #: A marca da coluna Distrato; é ela que põe o sufixo no nome do arquivo.
    distrato: bool = False
    #: O que a leitura do distrato sugeriu (a marca pode ser mudada à mão).
    distrato_sugerido: bool = False
    casa_com_distrato: bool = False
    #: Linha extra da casa: o contrato de OUTRO comprador, não o do
    #: recebimento do mês.
    outro_contrato: bool = False
    #: O comprador como o próprio contrato o qualifica (lido do PDF).
    comprador_contrato: str = ""
    #: O PDF baixado na busca. O arquivar grava estes bytes em vez de baixar
    #: de novo — e eles valem só para o `anexo` em que foram lidos.
    dados: bytes | None = None

    @property
    def contrato(self) -> str:
        return (self.anexo or {}).get("filename", "")

    @property
    def resumo(self) -> str:
        i = self.imovel
        return (f"{i.obra} {i.rotulo} · {i.comprador or i.descricao} · "
                f"R$ {i.recebido:,.2f}")


def _garantir_acesso(api, log=print) -> None:
    """Deixa a API pronta para os DOIS back-ends antes da primeira leitura.

    Os recebimentos saem de um; as obras, os anexos e o contrato saem do
    outro — e o cabeçalho de autenticação de cada um só passa a existir depois
    que o navegador faz uma requisição de verdade naquela tela.

    A garantia mora aqui, e não na aba, porque quem sabe que precisa dos dois é
    este módulo: a aba anunciava "Preparando o acesso aos anexos..." e não
    preparava nada, e a busca morria em "Credenciais de anexos ainda não
    capturadas" logo depois de "Lendo as obras..." — mensagem que não diz o que
    fazer e some do caminho de quem só queria os contratos do mês."""
    if not api.garantir_credenciais_anexos(log):
        raise RuntimeError(
            "não consegui preparar o acesso ao cadastro de obras e anexos do "
            "Mais Controle.\n"
            "Abra a tela de Pagamentos no Chrome, entre em um pagamento "
            "qualquer e rode de novo.")


def _primeiro_dia(ano: int, mes: int) -> str:
    return f"{ano:04d}-{mes:02d}-01"


def _ultimo_dia(ano: int, mes: int) -> str:
    import calendar
    return f"{ano:04d}-{mes:02d}-{calendar.monthrange(ano, mes)[1]:02d}"


def _definir_empresa(achado: Achado, empresa) -> None:
    """A empresa de destino, com o que a conferência da vendedora precisa."""
    achado.empresa = getattr(empresa, "nome", "") or ""
    achado.cnpj = getattr(empresa, "cnpj", "") or ""
    achado.razao_social = getattr(empresa, "razao_social", "") or ""


def _nomes_de_empresa(empresas, cliente_erp: str = "") -> set[str]:
    """Tudo que, como Cliente de um recebimento, significa "a própria SPE"."""
    nomes = {util.norm_espaco(cliente_erp)} if cliente_erp else set()
    for e in empresas or []:
        for n in (getattr(e, "clientes_erp", None) or []):
            nomes.add(util.norm_espaco(n))
        for n in (getattr(e, "razao_social", ""), getattr(e, "nome", "")):
            if n:
                nomes.add(util.norm_espaco(n))
    nomes.discard("")
    return nomes


def _definir_comprador(achado: Achado, empresas) -> None:
    """Regra do dono (09/09/2026): o comprador é o Cliente do recebimento.

    Com uma ressalva que os dados impuseram: em agosto/2026 o Cliente era a
    própria SPE em 20 das 25 linhas (financiamento, FGTS e juros nascem com a
    empresa como cliente). Cliente que é empresa do cadastro não é comprador
    de ninguém — aí vale o nome que está na descrição. Errar aqui não arquiva
    errado: o ponto COMPRADOR da conferência ainda exige o nome no PDF."""
    i = achado.imovel
    if i.cliente and util.norm_espaco(i.cliente) not in _nomes_de_empresa(
            empresas, achado.cliente_erp):
        i.comprador = i.cliente
    else:
        i.comprador = i.comprador_descricao


def levantar(api, ano: int, mes: int, empresas, log=print,
             cancelar=None, abrir_pdf=None) -> list[Achado]:
    """Passo 1: quem recebeu, qual o contrato e para qual empresa vai.

    Não grava nada, e em casa sem distrato também não baixa (fora o desempate
    de dois nomes pelo conteúdo). É o que a aba mostra ANTES de o usuário
    mandar arquivar — e é onde um erro do mapa cliente→empresa aparece.

    Casa com distrato (e `abrir_pdf` dado, o mesmo do `arquivar`): a busca
    baixa os contratos e os distratos da casa, separa os contratos por
    comprador lido no PDF e devolve uma linha por comprador — a do recebimento
    primeiro, as outras logo depois com `outro_contrato`. A marca Distrato
    vem sugerida pelo texto do distrato. Baixar aqui é obrigatório: a URL do
    S3 expira, e o arquivar grava os mesmos bytes que foram lidos. Sem
    `abrir_pdf` a casa segue a regra antiga, sem ler PDF nenhum."""
    _garantir_acesso(api, log)
    inicio, fim = _primeiro_dia(ano, mes), _ultimo_dia(ano, mes)
    log(f"Lendo os recebimentos de venda de {inicio} a {fim}...")
    registros = api.listar_recebimentos(inicio, fim, log)

    if not registros:
        log("Nenhum recebimento de venda no período.")
        log("Confira o mês: isso costuma ser filtro errado, não mês parado.")
        return []

    imoveis = imoveis_do_mes(registros, log)
    log(f"{len(registros)} recebimento(s) em {len(imoveis)} casa(s).")

    log("Lendo as obras...")
    obras = api.listar_obras(log)
    por_nome = {util.norm_espaco(o.get("name")): o for o in obras}

    achados = [Achado(imovel=i, revisao=i.revisao) for i in imoveis]

    # Só as obras que interessam, e uma vez cada (o mesmo lote tem 2 casas).
    # A casa sem número também acha a obra: é o que deixa a linha em revisão
    # dizer de quem é, mesmo sem ter contrato para escolher.
    ids: list[str] = []
    for a in achados:
        if not a.imovel.obra:
            continue
        obra = por_nome.get(util.norm_espaco(a.imovel.obra))
        if obra is None:
            a.revisao = a.revisao or (
                f"não achei a obra \"{a.imovel.obra}\" no cadastro do Mais "
                "Controle")
            continue
        a.obra_id = obra.get("id") or ""
        a.cliente_erp = ((obra.get("customer") or {}).get("name") or "").strip()
        if a.obra_id and a.obra_id not in ids and a.imovel.unidade:
            ids.append(a.obra_id)

    if not ids:
        return achados

    log(f"Lendo os anexos de {len(ids)} obra(s)...")
    anexos_por_obra = api.anexos_de_obras(ids, log, cancelar=cancelar)

    saida: list[Achado] = []
    for a in achados:
        saida.append(a)
        if a.obra_id:
            _definir_comprador(a, empresas)
        if a.revisao or not a.obra_id:
            continue
        a.anexos_da_obra = anexos_por_obra.get(a.obra_id) or []
        linhas = None
        distratos = distratos_da_casa(a.anexos_da_obra, a.imovel.unidade)
        if distratos and abrir_pdf is not None:
            linhas = _casa_com_distrato(api, a, distratos, abrir_pdf, log)
        if linhas is None:
            linhas = [a]
            anexo, motivo = contrato_de(a.anexos_da_obra, a.imovel.unidade)
            if anexo is None and "disputam" in motivo:
                anexo, motivo = _desempatar_por_conteudo(api, a, motivo, log)
            if anexo is None:
                a.revisao = motivo
            else:
                a.anexo = anexo
        saida.extend(linhas[1:])

        # A empresa é resolvida mesmo sem contrato: as duas pendências são
        # independentes, e a janela de resolver só deve perguntar o que
        # realmente falta. As linhas da mesma casa vão para a mesma empresa.
        empresa = empresa_de(a.cliente_erp, empresas)
        for linha in linhas:
            if empresa is None:
                linha.revisao = linha.revisao or _sem_empresa(linha.cliente_erp)
            else:
                _definir_empresa(linha, empresa)

    achados = saida
    for a in achados:
        a.marcado = not a.revisao and bool(a.anexo)
    return achados


def _desempatar_por_conteudo(api, achado: Achado, motivo: str,
                             log=print) -> tuple[dict | None, str]:
    """Dois nomes, um arquivo? Baixa os candidatos e compara os bytes.

    Em agosto/2026, das cinco casas em disputa, várias eram o MESMO contrato
    subido duas vezes com o nome escrito de outro jeito (`QD 26 A, LT, 14` e
    `QD 26A LT 14`). Bytes iguais são o mesmo documento, e aí qualquer um
    serve. Bytes diferentes são versões diferentes (uma com a assinatura da
    corretora, outra sem), e isso só gente decide — o motivo passa a dizer o
    tamanho de cada um, que já ajuda a escolher.

    Baixa AQUI, na busca, porque a URL do S3 expira: guardar para depois é
    guardar um link morto."""
    distintos = candidatos_distintos(achado.anexos_da_obra, achado.imovel.unidade)
    if len(distintos) > MAXIMO_PARA_DESEMPATAR:
        return None, motivo
    conteudos = []
    for a in distintos:
        try:
            dados = api.baixar_anexo(a.get("downloadUrl"))
        except Exception:
            dados = None
        if not dados:
            return None, motivo            # sem o arquivo não há o que comparar
        conteudos.append(dados)
    if all(c == conteudos[0] for c in conteudos[1:]):
        nomes = ", ".join(f'"{(a.get("filename") or "").strip()}"' for a in distintos)
        log(f"  {achado.imovel.obra} {achado.imovel.rotulo}: {len(distintos)} "
            f"nomes, um só arquivo — {nomes}")
        return distintos[0], f"{len(distintos)} nomes para o mesmo arquivo"
    tamanhos = "; ".join(
        f'"{(a.get("filename") or "").strip()}" ({len(c) // 1024} KB)'
        for a, c in zip(distintos, conteudos))
    return None, (f"{len(distintos)} anexos DIFERENTES disputam a "
                  f"{achado.imovel.rotulo}: {tamanhos}")


def _baixar(api, anexo: dict) -> bytes | None:
    try:
        return api.baixar_anexo(anexo.get("downloadUrl")) or None
    except Exception:
        return None


def _ler(abrir_pdf, dados: bytes, ate) -> str:
    """Texto do PDF; "" quando o leitor falha (vira "comprador não lido")."""
    try:
        return abrir_pdf(dados).texto(ate) or ""
    except Exception:
        return ""


def _casa_com_distrato(api, achado: Achado, distratos: list[dict], abrir_pdf,
                       log=print) -> list[Achado] | None:
    """Uma linha por comprador de contrato da casa; None = regra de sempre.

    Regra do dono (05/10/2026): casa revendida tem o contrato do primeiro
    comprador, o distrato dele e o contrato do novo. Os dois contratos vão
    para a pasta — o desfeito com "(Distratado)" no nome —, e quem diz qual
    foi desfeito é o texto do distrato, não o ERP (que só conhece o comprador
    atual).

    Preenche o próprio `achado` com o grupo do comprador do recebimento (o
    primeiro de `agrupar`) e devolve as linhas extras logo depois dele."""
    i = achado.imovel
    cands = candidatos_distintos(achado.anexos_da_obra, i.unidade)
    if not cands:
        return None                         # "nenhum anexo de COMPRA E VENDA"
    achado.casa_com_distrato = True
    if len(cands) > MAXIMO_COM_DISTRATO:
        achado.revisao = (f"{len(cands)} contratos e distrato na casa — "
                          "escolha à mão")
        return [achado]

    versoes = []
    for anexo in cands:
        dados = _baixar(api, anexo)
        if not dados:
            achado.revisao = ("não consegui baixar "
                              f"{(anexo.get('filename') or '').strip()}")
            return [achado]
        versoes.append(dist.Versao(anexo, dados,
                                   _ler(abrir_pdf, dados, PAGINAS_INICIAIS)))

    # Distrato que não baixa ou não lê só deixa de sugerir: a marca é
    # sugestão, e a pessoa ainda a confere na tabela.
    textos_distrato = []
    for anexo in distratos[:MAXIMO_DE_DISTRATOS]:
        dados = _baixar(api, anexo)
        texto = _ler(abrir_pdf, dados, None) if dados else ""
        if texto:
            textos_distrato.append(texto)

    linhas: list[Achado] = []
    for n, grupo in enumerate(dist.agrupar(versoes, i.comprador)):
        linha = achado if n == 0 else replace(
            achado, outro_contrato=True, endereco=dict(achado.endereco),
            resultado_conferencia={})
        versao, motivo = dist.escolher(grupo)
        comprador = (versao or grupo[0]).comprador
        linha.comprador_contrato = comprador
        linha.distrato_sugerido = dist.foi_distratado(comprador,
                                                      textos_distrato)
        linha.distrato = linha.distrato_sugerido
        if versao is None:
            linha.anexo, linha.dados, linha.revisao = {}, None, motivo
        else:
            linha.anexo, linha.dados, linha.revisao = versao.anexo, versao.dados, ""
            if not comprador:
                log(f"  não consegui ler o comprador de "
                    f"{(versao.anexo.get('filename') or '').strip()}; "
                    "Distrato fica desmarcado")
        linhas.append(linha)

    quem = ", ".join(
        (x.comprador_contrato or "comprador não lido")
        + (" (distratado)" if x.distrato else "") for x in linhas)
    log(f"  {i.obra} {i.rotulo}: {len(linhas)} contrato(s) e "
        f"{len(distratos)} distrato(s) — {quem}")
    return linhas


# ------------------------------------------------- resolver à mão
def _sem_empresa(cliente_erp: str) -> str:
    return (f"o cliente \"{cliente_erp or '(sem cliente)'}\" não está mapeado "
            "em nenhuma empresa (clientes_erp no contas_sicoob.json)")


def pode_resolver(achado: Achado) -> bool:
    """Dá para decidir alguma coisa à mão nesta casa?

    Sem obra no cadastro do ERP não há anexo para escolher nem cliente para
    mapear. Sem o NÚMERO da casa também não: o nome do arquivo e a conferência
    dependem dele, e a correção é no ERP (a descrição do recebimento)."""
    return bool(achado.obra_id) and bool(achado.imovel.unidade)


def que_falta(achado: Achado) -> str:
    """O motivo que AINDA impede o arquivamento; "" quando não há mais."""
    if not achado.obra_id or not achado.imovel.unidade:
        return achado.revisao
    if not achado.anexo:
        return achado.revisao or "falta escolher o contrato desta casa"
    if not achado.empresa:
        return _sem_empresa(achado.cliente_erp)
    return ""


def aplicar_resolucao(achado: Achado, anexo: dict | None = None,
                      empresa_nome: str = "", empresas=None) -> str:
    """Aplica o que a pessoa decidiu e devolve o que ainda falta.

    Devolver o que falta, em vez de sim/não, é o que deixa a janela resolver
    metade do problema sem mentir: escolher o contrato de uma casa cujo cliente
    continua sem empresa não arquiva nada, e a linha tem de seguir dizendo por
    quê. Só sai marcada a casa que não deve mais nada.

    `empresas` (o cadastro) é o que dá CNPJ e razão social à empresa escolhida
    — sem eles a vendedora ficaria em `?` justo na casa decidida à mão."""
    if anexo is not None:
        # Os bytes baixados na busca são do anexo de antes: gravá-los com o
        # anexo escolhido agora poria na pasta o PDF de outro contrato.
        if anexo is not achado.anexo:
            achado.dados = None
        achado.anexo = anexo
        achado.contrato_manual = True
    if empresa_nome:
        escolhida = next((e for e in (empresas or [])
                          if util.norm_espaco(getattr(e, "nome", ""))
                          == util.norm_espaco(empresa_nome)), None)
        if escolhida is not None:
            _definir_empresa(achado, escolhida)
        else:
            achado.empresa = empresa_nome
        achado.empresa_manual = True
    achado.revisao = que_falta(achado)
    achado.marcado = not achado.revisao
    return achado.revisao


def chave_da_casa(achado: Achado) -> tuple:
    """Identidade da linha entre uma busca e outra: obra + unidade e, na
    linha extra de uma casa com distrato, o comprador do contrato — senão a
    escolha feita numa linha voltaria na outra da mesma casa."""
    return achado.imovel.chave + (
        (achado.comprador_contrato,) if achado.outro_contrato else ())


def reaplicar(achados: list[Achado], escolhas: dict, log=print) -> int:
    """Devolve as escolhas de contrato feitas à mão a uma lista recém-buscada.

    Guardamos o NOME do arquivo, não o anexo: a busca refeita traz outro
    objeto, com `downloadUrl` novo (o do S3 expira em minutos). Se o nome sumiu
    da obra, a casa volta a perguntar em vez de arquivar um arquivo que ninguém
    olhou."""
    voltaram = 0
    for a in achados:
        nome = escolhas.get(chave_da_casa(a))
        if not nome:
            continue
        alvo = next((x for x in a.anexos_da_obra
                     if util.norm_espaco(x.get("filename") or "")
                     == util.norm_espaco(nome)), None)
        if alvo is None:
            log(f"  a escolha anterior não está mais na obra: {nome}")
            continue
        aplicar_resolucao(a, anexo=alvo)
        voltaram += 1
    return voltaram


def preparar_destino(achado: Achado, raiz: Path, ano: int, mes: int,
                     nome_do_mes, nome_pasta_empresa) -> str:
    """Preenche `achado.destino`. Devolve "" ou o motivo de não dar."""
    if not achado.empresa or not achado.anexo or not achado.imovel.unidade:
        return achado.revisao or "sem empresa, sem contrato ou sem casa"
    # A linha extra é o contrato de OUTRA pessoa: sem o comprador lido, o
    # nome cairia no do recebimento e a pasta ganharia um contrato alheio com
    # o nome de quem pagou — e a conferência, sem comprador esperado, não
    # seguraria.
    if achado.outro_contrato and not achado.comprador_contrato:
        return ("não consegui ler o comprador deste contrato no PDF — "
                "arquive à mão")
    pasta = pasta_do_contrato(raiz, ano, mes, achado.empresa,
                              nome_do_mes, nome_pasta_empresa)
    comprador = achado.comprador_contrato or achado.imovel.comprador
    alvo = pasta / nome_arquivo(achado.imovel.obra, achado.imovel.unidade,
                                comprador,
                                achado.anexo.get("extension") or ".pdf",
                                distratado=achado.distrato)
    passou = caminho_longo(alvo)
    if passou:
        return (f"o caminho ficaria com {passou} caracteres, acima do limite "
                f"de 260 do Windows:\n{str(alvo).replace(chr(92), '/')}")
    achado.destino = alvo
    return ""


def esperado_da_conferencia(achado: Achado) -> dict:
    """O que o contrato precisa dizer, montado do que o ERP e o cadastro
    informaram."""
    end = achado.endereco or {}
    # O contrato de outro comprador (ou o desfeito) é OUTRA venda: o nome que
    # ele tem de trazer é o lido nele, e o valor de venda do ERP é o da venda
    # atual — `None` vira `?`, que não retém.
    outra_venda = achado.outro_contrato or achado.distrato
    return {
        "rua": end.get("address") or "",
        "complemento": end.get("complement") or "",
        "unidade": achado.imovel.unidade,
        "comprador": (achado.comprador_contrato if outra_venda
                      else achado.imovel.comprador),
        "cnpj": achado.cnpj,
        "vendedora": [n for n in (achado.razao_social, achado.cliente_erp) if n],
        "valor_venda": None if outra_venda else achado.imovel.valor_venda,
    }


def _conferir_progressivo(leitor, esperado: dict) -> dict:
    """As primeiras páginas primeiro; o resto só se sobrou `?`.

    O contrato tem as partes, o objeto e o valor no começo. Ler as 20 páginas
    (e, escaneado, passar OCR em todas) para confirmar o que a página 2 já
    disse é o que deixava a rodada lenta."""
    texto = leitor.texto(PAGINAS_INICIAIS)
    resultado = conf.conferir(texto, esperado)
    if conf.ressalvas(resultado) and leitor.tem_mais(PAGINAS_INICIAIS):
        resultado = conf.conferir(leitor.texto(None), esperado)
    return resultado


def _mesmo_conteudo(caminho: Path, dados: bytes) -> bool:
    try:
        return caminho.stat().st_size == len(dados) and \
            caminho.read_bytes() == dados
    except OSError:
        return False


def arquivar(api, achados: list[Achado], raiz: Path, ano: int, mes: int,
             nome_do_mes, nome_pasta_empresa, abrir_pdf,
             log=print, cancelar=None, progresso=None) -> list[Achado]:
    """Passo 2: baixa, confere o conteúdo e grava só o que passou.

    `abrir_pdf(bytes) -> leitor` entra por parâmetro para este módulo não
    depender do pdfplumber nem do OCR: quem sabe ler PDF é `leitura.py`, e
    aqui só se decide o que fazer com o texto.

    Nunca grava por cima. Arquivo de mesmo nome e mesmo conteúdo é "já
    estava"; de conteúdo diferente, ou a mesma casa com outro nome, é revisão
    — a pasta CONTRATOS tem arquivos postos à mão desde 2024.

    Casa com distrato: as linhas da mesma casa nesta rodada são irmãs, e o
    arquivo de uma não conta como "a mesma casa com outro nome" para a
    outra — é por isso que os destinos de todas são preparados antes do
    laço. A linha que já trouxe o PDF da busca (`dados`) grava esses bytes,
    os mesmos que foram lidos para separar os compradores."""
    # Repetido de propósito: entre buscar e arquivar o ERP pode ter derrubado a
    # sessão (ele aceita uma por usuário), e aí a API é outra, sem cabeçalho
    # nenhum. Custa nada quando já está capturado.
    _garantir_acesso(api, log)
    # `marcado` é a decisão de quem confere, tomada na tabela. Sem ela aqui, o
    # passo 2 arquivaria de novo o que a pessoa tirou da rodada de propósito.
    prontos = [a for a in achados if a.marcado and not a.revisao and a.anexo]
    total = len(prontos)

    # Primeiro passo: o destino de todos (não toca disco). Assim cada linha
    # sabe o nome dos arquivos das irmãs da mesma casa nesta rodada.
    motivos: dict[int, str] = {}
    irmaos: dict[tuple, set] = {}
    for achado in prontos:
        motivos[id(achado)] = preparar_destino(achado, raiz, ano, mes,
                                               nome_do_mes, nome_pasta_empresa)
        if not motivos[id(achado)]:
            irmaos.setdefault(achado.imovel.chave, set()).add(achado.destino)

    for i, achado in enumerate(prontos, 1):
        if cancelar and cancelar():
            log("⏹ Interrompido — o que já foi arquivado continua no lugar.")
            break
        if progresso:
            progresso(i, total)

        # O endereço só existe no detalhe da obra, e é dele que saem a rua e a
        # quadra/lote da conferência.
        if not achado.endereco:
            try:
                achado.endereco = (api.detalhe_da_obra(achado.obra_id)
                                   .get("address") or {})
            except Exception as e:
                achado.revisao = f"não consegui ler o endereço da obra: {e}"
                continue

        motivo = motivos[id(achado)]
        if motivo:
            achado.revisao = motivo
            continue

        outro = mesmo_contrato_na_pasta(
            achado.destino.parent, achado.imovel.obra, achado.imovel.unidade,
            exceto={achado.destino, *irmaos.get(achado.imovel.chave, ())})
        if outro is not None:
            achado.revisao = ("esta casa já tem contrato de compra e venda na "
                              f"pasta, com outro nome: {outro.name}")
            log(f"  [{i}/{total}] JÁ EXISTE {achado.resumo} — {outro.name}")
            continue

        dados = achado.dados or api.baixar_anexo(achado.anexo.get("downloadUrl"))
        if not dados:
            achado.revisao = ("o download do contrato falhou ou veio vazio "
                              "(a URL do S3 expira: rode a busca de novo)")
            continue

        if achado.destino.exists():
            if _mesmo_conteudo(achado.destino, dados):
                achado.arquivado = True
                achado.ja_existia = True
                log(f"  [{i}/{total}] já estava {achado.resumo}")
                continue
            achado.revisao = ("já existe um arquivo com este nome e conteúdo "
                              "diferente na pasta — confira à mão: "
                              f"{achado.destino.name}")
            log(f"  [{i}/{total}] RETIDO {achado.resumo} — nome já usado")
            continue

        leitor = abrir_pdf(dados)
        resultado = _conferir_progressivo(leitor, esperado_da_conferencia(achado))
        achado.resultado_conferencia = resultado
        achado.leitura = getattr(leitor, "origem", "")

        if not conf.pode_gravar(resultado):
            pontos = ", ".join(conf.divergencias(resultado))
            achado.revisao = f"o conteúdo do contrato diverge em: {pontos}"
            log(f"  [{i}/{total}] RETIDO {achado.resumo} — {pontos}")
            continue

        try:
            achado.destino.parent.mkdir(parents=True, exist_ok=True)
            achado.destino.write_bytes(dados)
        except OSError as e:
            achado.revisao = f"não consegui gravar: {e}"
            continue

        # "Arquivado" só depois de o arquivo existir com tamanho maior que
        # zero. Dizer que arquivou sem o arquivo no disco é o tipo de mentira
        # que só aparece no fechamento, meses depois.
        if not achado.destino.is_file() or achado.destino.stat().st_size <= 0:
            achado.revisao = "o arquivo não ficou no disco depois de gravar"
            continue

        achado.arquivado = True
        rs = conf.ressalvas(resultado)
        extra = f"  (ressalvas: {', '.join(rs)})" if rs else ""
        if achado.leitura == "OCR":
            extra += "  [lido por OCR]"
        log(f"  [{i}/{total}] ok {achado.resumo}{extra}")

    return achados
