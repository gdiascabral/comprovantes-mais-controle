# -*- coding: utf-8 -*-
"""O que vai ser enviado ao escritório: um zip por empresa, e a mensagem dele.

**A mensagem é derivada do anexo.** A lista de contratos do comentário sai de
DENTRO do próprio zip, lendo as entradas `.../CONTRATOS/`. As duas alternativas
(reler o ERP, ou ler a aba Contratos em memória) custam uma sessão do ERP — que
só aceita uma por usuário — ou só funcionam se aquela aba tiver rodado na mesma
execução. Nenhuma das duas tem a propriedade que esta tem: **a mensagem não
pode contradizer o anexo**, porque é lida dele.

Puro: sem navegador, sem tkinter e sem escrever em disco — só lê zips e monta
texto. As funções de nome (`nome_do_mes`, `nome_pasta_empresa`) chegam por
parâmetro, e não por import do pacote do Sicoob, pelo mesmo motivo que em
`contratos/destino.py`: mantém este módulo testável sem arrastar dependência.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

#: Subpasta dos contratos dentro da pasta da empresa. É a mesma constante do
#: `contratos/destino.py`; aqui ela é LIDA, lá é escrita.
SUBPASTA_CONTRATOS = "CONTRATOS"

#: `CONTRATO RPB 99 QD 1A LT 2 CS 01 - FULANO DE TAL` -> partes.
#: O nome é montado por `contratos/destino.nome_arquivo`. Não casando, a linha
#: entra como está: informação a mais no comentário é melhor que informação
#: perdida em silêncio.
RE_CONTRATO = re.compile(
    r"^CONTRATO\s+(?P<obra>.+?)\s+CS\s+(?P<unidade>\d+)"
    r"(?:\s*-\s*(?P<comprador>.+))?$")

#: Partículas que ficam em minúscula na caixa de título de um nome.
PARTICULAS = {"de", "da", "do", "das", "dos", "e"}

MODELO_ASSUNTO = "Conciliações bancárias {mes}/{ano} - {empresa}"

MODELO_COMENTARIO = (
    "Segue em anexo os extratos (.pdf e .ofx) e relatórios do sistema "
    "(Mais Controle) das contas Caixa, Inter e Sicoob referentes a "
    "{mes_minusculo}/{ano}, além dos contratos de venda do mês:\n"
    "{contratos}")

#: Os tokens aceitos nos dois modelos, para a aba poder mostrá-los.
TOKENS = ("{mes}", "{mes_minusculo}", "{ano}", "{empresa}", "{contratos}")


@dataclass
class Envio:
    """Uma empresa do mês: o zip, a mensagem e o que impede de enviar."""

    empresa: str                 # nome da pasta do fechamento ("BURITIS")
    rotulo: str                  # como entra no assunto (vip_nome, ou o nome)
    vip_id: str
    caminho: Path
    tamanho: int                 # bytes do zip
    contratos: list[str] = field(default_factory=list)
    assunto: str = ""
    comentario: str = ""
    #: Vazio = pronta para enviar. Preenchido = a aba mostra o motivo e o lote
    #: para antes do primeiro envio.
    problema: str = ""
    #: Resultado da rodada, preenchido pelo portal.
    situacao: str = ""

    @property
    def pronta(self) -> bool:
        return not self.problema

    @property
    def tamanho_legivel(self) -> str:
        return fmt_tamanho(self.tamanho)


def fmt_tamanho(n: int) -> str:
    """1536 -> '1,5 MB'. Aparece na tela porque o limite de anexo do portal é
    desconhecido, e descobri-lo no envio nº 7 é caro."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB".replace(".", ",")
    return f"{n / (1024 * 1024):.1f} MB".replace(".", ",")


def caixa_de_titulo(nome: str) -> str:
    """'FULANO DE TAL' -> 'Fulano de Tal'.

    O nome vem em caixa alta do nome do arquivo, e é assim, em caixa de título,
    que ele aparecia nas solicitações escritas à mão. A primeira palavra nunca
    é partícula: 'DA SILVA' começando a linha viraria 'da Silva'."""
    palavras = (nome or "").split()
    saida = []
    for i, p in enumerate(palavras):
        baixa = p.lower()
        saida.append(baixa if i and baixa in PARTICULAS else baixa.capitalize())
    return " ".join(saida)


def linha_do_contrato(nome_do_arquivo: str) -> str:
    """'CONTRATO RPB 99 QD 1A LT 2 CS 01 - FULANO DE TAL.pdf'
    -> 'RPB 99 QD 1A LT 2 Casa 01 - Fulano de Tal'."""
    base = PurePosixPath(nome_do_arquivo).stem.strip()
    m = RE_CONTRATO.match(base)
    if not m:
        return base                      # formato desconhecido: vai como está
    linha = f"{m.group('obra').strip()} Casa {m.group('unidade')}"
    comprador = (m.group("comprador") or "").strip()
    if comprador:
        linha += f" - {caixa_de_titulo(comprador)}"
    return linha


def contratos_do_zip(caminho: Path) -> list[str]:
    """As linhas de contrato de dentro do zip, ordenadas pelo nome do arquivo.

    Zip ilegível não derruba a preparação: devolve lista vazia, e a aba mostra
    'sem contratos no zip' naquela empresa. O comentário fica sem a lista, o
    que é visível — melhor que um `{contratos}` vazio disfarçado de certo."""
    try:
        with zipfile.ZipFile(caminho) as z:
            nomes = [n for n in z.namelist() if not n.endswith("/")]
    except (OSError, zipfile.BadZipFile):
        return []
    contratos = [n for n in nomes
                 if PurePosixPath(n).parent.name.upper() == SUBPASTA_CONTRATOS]
    return [linha_do_contrato(n) for n in sorted(contratos)]


def aplicar_modelo(modelo: str, *, mes: str, ano: int, empresa: str,
                   contratos: list[str]) -> str:
    """Troca os tokens do modelo. Token desconhecido fica como está — quem
    escreveu '{mes_do_ano}' vê o próprio erro na tela, em vez de um KeyError."""
    valores = {
        "{mes}": mes,
        "{mes_minusculo}": mes.lower(),
        "{ano}": str(ano),
        "{empresa}": empresa,
        "{contratos}": "\n".join(contratos),
    }
    for token, valor in valores.items():
        modelo = modelo.replace(token, valor)
    return modelo


def pasta_do_mes(raiz: Path, ano: int, mes: int, nome_do_mes) -> Path:
    return Path(raiz) / str(ano) / nome_do_mes(mes)


def zips_do_mes(raiz: Path, ano: int, mes: int, nome_do_mes) -> list[Path]:
    """Os .zip que estão na pasta do mês, em ordem. A pasta manda: um zip
    encontrado, uma solicitação."""
    base = pasta_do_mes(raiz, ano, mes, nome_do_mes)
    if not base.is_dir():
        return []
    return sorted((p for p in base.iterdir()
                   if p.is_file() and p.suffix.lower() == ".zip"),
                  key=lambda p: util.norm_espaco(p.name))


def montar(mapa, ano: int, mes: int, nome_do_mes, nome_pasta_empresa,
           modelo_assunto: str = MODELO_ASSUNTO,
           modelo_comentario: str = MODELO_COMENTARIO) -> list[Envio]:
    """Os envios do mês, prontos para a tela.

    Casa cada zip com a empresa comparando o nome do arquivo com
    `nome_pasta_empresa(...)` — a MESMA função que gerou aquele nome no
    `sicoob_zipar`, e não uma segunda regra de nomenclatura escrita aqui.
    Duas regras para o mesmo nome é como o mês ia parar em duas pastas."""
    mes_titulo = nome_do_mes(mes).capitalize()
    por_nome = {util.norm_espaco(nome_pasta_empresa(ano, mes, e.nome)): e
                for e in getattr(mapa, "empresas", None) or []}

    envios: list[Envio] = []
    for caminho in zips_do_mes(mapa.raiz, ano, mes, nome_do_mes):
        # `stem` tira só o ".zip" final; razão social com ponto ("EMPREEND.
        # BURITIS") continua inteira. É a armadilha que o `with_suffix()` já
        # causou no sicoob_zipar, do outro lado deste mesmo nome.
        empresa = por_nome.get(util.norm_espaco(caminho.stem))
        contratos = contratos_do_zip(caminho)
        try:
            tamanho = caminho.stat().st_size
        except OSError:
            tamanho = 0

        if empresa is None:
            envios.append(Envio(
                empresa=caminho.stem, rotulo=caminho.stem, vip_id="",
                caminho=caminho, tamanho=tamanho, contratos=contratos,
                problema="empresa desconhecida — o nome do zip não bate com "
                         "nenhuma empresa do contas_sicoob.json"))
            continue

        rotulo = (getattr(empresa, "vip_nome", "") or "").strip() or empresa.nome
        vip_id = str(getattr(empresa, "vip_id", "") or "").strip()
        envio = Envio(
            empresa=empresa.nome, rotulo=rotulo, vip_id=vip_id,
            caminho=caminho, tamanho=tamanho, contratos=contratos,
            problema="" if vip_id else
                     f"sem 'vip_id' no contas_sicoob.json — cadastre o id de "
                     f"'{empresa.nome}' no portal")
        envio.assunto = aplicar_modelo(
            modelo_assunto, mes=mes_titulo, ano=ano, empresa=rotulo,
            contratos=contratos)
        envio.comentario = aplicar_modelo(
            modelo_comentario, mes=mes_titulo, ano=ano, empresa=rotulo,
            contratos=contratos)
        if not contratos:
            envio.situacao = "sem contratos no zip"
        envios.append(envio)
    return envios


def impedimentos(envios: list[Envio]) -> list[str]:
    """Os motivos que travam o lote ANTES do primeiro envio.

    É a regra do Relatório Mensal para conta sem destino: decidir com o lote
    pela metade vira improviso, e desfazer envio ao escritório não é possível
    do lado de cá."""
    return [f"{e.empresa}: {e.problema}" for e in envios if e.problema]
