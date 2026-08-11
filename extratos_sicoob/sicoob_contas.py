# -*- coding: utf-8 -*-
"""
Leitura e validação do mapa conta -> pasta.

O mapa vive em `contas_sicoob.json`, fora do repositório. Cada empresa declara
duas coisas: as pastas que só são criadas (bancos que não entram nesta
automação) e as contas Sicoob, que além da pasta recebem os arquivos.

Sem navegador e sem tkinter: roda inteiro em teste.
"""
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import sicoob_config as cfg

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util


class MapaInvalido(RuntimeError):
    """O JSON não existe, não é JSON, ou não descreve um mapa utilizável."""


@dataclass
class Conta:
    numero: str                 # como a pessoa escreve: "50.019-4"
    pasta: str                  # subpasta de destino dentro da empresa
    empresa: str = ""

    @property
    def chave(self) -> str:
        return so_digitos(self.numero)


@dataclass
class Empresa:
    nome: str
    pastas_vazias: list[str] = field(default_factory=list)
    contas: list[Conta] = field(default_factory=list)
    #: Nomes com que esta empresa aparece como CLIENTE das obras no ERP.
    #: `TERRA BELA MORAIS ENGENHARIA SPE` (ERP) e a pasta `TERRA BELA` nao se
    #: derivam um do outro, e a aba Contratos precisa da ponte. Vazio por
    #: padrao, para o contas_sicoob.json de quem nao atualizou seguir valido.
    clientes_erp: list[str] = field(default_factory=list)

    @property
    def subpastas(self) -> list[str]:
        """Tudo que existe dentro da empresa, com e sem download."""
        return self.pastas_vazias + [c.pasta for c in self.contas]


@dataclass
class Mapa:
    raiz: Path
    empresas: list[Empresa]

    @property
    def contas(self) -> list[Conta]:
        return [c for e in self.empresas for c in e.contas]

    def conta_por_numero(self, numero: str) -> Conta | None:
        """Busca ignorando pontuação: '50.019-4', '50019-4' e '500194' são a
        mesma conta. O OFX do Sicoob traz o ACCTID sem ponto, e a pessoa
        escreve com — comparar texto cru daria falso negativo."""
        alvo = so_digitos(numero)
        return next((c for c in self.contas if c.chave == alvo), None)


def so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


# ---------------------------------------------------------------- leitura

def carregar(caminho: Path | None = None) -> Mapa:
    """Lê o mapa. Levanta MapaInvalido com mensagem útil — quem chama mostra
    o recado para o usuário, que não sabe o que é JSON."""
    caminho = caminho or cfg.ARQUIVO_CONTAS
    if not caminho.exists():
        raise MapaInvalido(
            f"O arquivo de contas não existe:\n{str(caminho).replace(chr(92), '/')}\n\n"
            "Um modelo pode ser criado com `criar_modelo()` — preencha-o com "
            "as contas reais antes de rodar.")
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise MapaInvalido(f"Não consegui ler {caminho.name}: {e}") from e

    if not isinstance(dados, dict) or not dados.get("empresas"):
        raise MapaInvalido(f"{caminho.name} não tem a lista 'empresas'.")

    raiz = Path(dados.get("raiz") or cfg.RAIZ_PADRAO)
    empresas = []
    for i, e in enumerate(dados["empresas"]):
        nome = (e.get("nome") or "").strip()
        if not nome:
            raise MapaInvalido(f"A empresa nº {i + 1} está sem 'nome'.")
        contas = []
        for c in e.get("contas", []):
            numero, pasta = (c.get("numero") or "").strip(), (c.get("pasta") or "").strip()
            if not numero or not pasta:
                raise MapaInvalido(
                    f"Conta incompleta em '{nome}': precisa de 'numero' e 'pasta'.")
            contas.append(Conta(numero=numero, pasta=pasta, empresa=nome))
        empresas.append(Empresa(
            nome=nome,
            pastas_vazias=[p.strip() for p in e.get("pastas_vazias", [])],
            contas=contas,
            clientes_erp=[c.strip() for c in (e.get("clientes_erp") or [])
                          if (c or "").strip()]))
    return Mapa(raiz=raiz, empresas=empresas)


# ------------------------------------------------------------- escrita

def adicionar_cliente_erp(empresa: str, cliente: str,
                          caminho: Path | None = None) -> None:
    """Grava `cliente` em `clientes_erp` da empresa, no arquivo do cadastro.

    A aba Contratos descobre o cliente de uma obra na hora de arquivar, e
    obrigar a pessoa a editar JSON à mão para seguir era o caminho mais curto
    para o contrato ir para a pasta errada. Por isso a decisão tomada na tela
    vira cadastro — o MESMO que as outras abas leem, e não um mapa paralelo.

    Duas travas, pelas quais este arquivo vale mais que o resto:

    1. cliente que já é de OUTRA empresa não é movido em silêncio — levanta
       `MapaInvalido` com as duas empresas no texto, que é o mesmo defeito que
       o `validar()` denuncia;
    2. a escrita passa por arquivo temporário e `os.replace`, atômico no
       Windows: interromper no meio deixaria o cadastro do fechamento inteiro
       pela metade, e o estrago apareceria na próxima aba a rodar, longe daqui.

    Repetir a mesma chamada não duplica nada (é idempotente)."""
    caminho = caminho or cfg.ARQUIVO_CONTAS
    empresa_alvo, cliente = util.norm_espaco(empresa), (cliente or "").strip()
    if not empresa_alvo or not cliente:
        raise MapaInvalido("Preciso da empresa e do cliente para gravar.")

    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise MapaInvalido(f"Não consegui ler {caminho.name}: {e}") from e
    if not isinstance(dados, dict) or not isinstance(dados.get("empresas"), list):
        raise MapaInvalido(f"{caminho.name} não tem a lista 'empresas'.")

    destino = None
    for e in dados["empresas"]:
        if not isinstance(e, dict):
            continue
        nome = util.norm_espaco(e.get("nome") or "")
        atuais = [c for c in (e.get("clientes_erp") or []) if (c or "").strip()]
        ja_tem = any(util.norm_espaco(c) == util.norm_espaco(cliente)
                     for c in atuais)
        if nome == empresa_alvo:
            destino = e
            if ja_tem:
                return                       # nada a fazer, e sem reescrever
        elif ja_tem:
            raise MapaInvalido(
                f"O cliente '{cliente}' já está na empresa '{e.get('nome')}'.\n"
                f"Um cliente do ERP em duas empresas manda o contrato para a "
                f"pasta errada. Tire de lá antes de pôr em '{empresa}'.")

    if destino is None:
        raise MapaInvalido(f"Não achei a empresa '{empresa}' em {caminho.name}.")

    destino["clientes_erp"] = [c for c in (destino.get("clientes_erp") or [])
                               if (c or "").strip()] + [cliente]

    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    try:
        temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        os.replace(temporario, caminho)
    except OSError as e:
        try:
            temporario.unlink()
        except OSError:
            pass
        raise MapaInvalido(f"Não consegui gravar {caminho.name}: {e}") from e


# ------------------------------------------------------------- validação

_RE_SUBCONTA = re.compile(r"^SUBCONTA - \d{5}-\d( - .+)? - SICOOB$")


def validar(mapa: Mapa) -> list[str]:
    """Devolve os problemas encontrados, em português, sem levantar exceção.

    Erro de digitação no mapa é o defeito mais caro deste projeto: manda o
    extrato de uma empresa para a pasta de outra. Vale conferir antes de rodar
    o lote, não depois."""
    avisos: list[str] = []

    vistas: dict[str, Conta] = {}
    for c in mapa.contas:
        if c.chave in vistas:
            avisos.append(
                f"Conta {c.numero} aparece duas vezes: "
                f"'{vistas[c.chave].empresa}' e '{c.empresa}'.")
        vistas[c.chave] = c
        if not re.fullmatch(r"\d{5}-\d", c.numero.replace(".", "")):
            avisos.append(f"Conta com formato estranho em '{c.empresa}': {c.numero}")

    for e in mapa.empresas:
        subs = e.subpastas
        for s in sorted(set(subs)):
            if subs.count(s) > 1:
                avisos.append(f"Pasta '{s}' repetida em '{e.nome}'.")
        # Regra de nome combinada para as subcontas (ver spec).
        for c in e.contas:
            if c.pasta.upper().startswith("SUBCONTA") and not _RE_SUBCONTA.match(c.pasta):
                avisos.append(
                    f"Subpasta fora do padrão em '{e.nome}': '{c.pasta}'\n"
                    "   esperado: SUBCONTA - 55696-3 - DESCRIÇÃO - SICOOB")

    # Cliente do ERP em duas empresas manda o contrato para a pasta errada, e
    # nada no disco denuncia depois — mesma classe de erro da conta repetida.
    donos: dict[str, str] = {}
    for e in mapa.empresas:
        for cliente in e.clientes_erp:
            chave = util.norm_espaco(cliente)
            if chave in donos and donos[chave] != e.nome:
                avisos.append(
                    f"Cliente do ERP '{cliente}' aparece em duas empresas: "
                    f"'{donos[chave]}' e '{e.nome}'.")
            donos[chave] = e.nome
    return avisos


# ----------------------------------------------------------------- modelo

_MODELO = {
    "raiz": "C:/Arquivos Morais/EXTRATOS",
    "_ajuda": [
        "pastas_vazias: pastas criadas mas NÃO preenchidas por esta automação",
        "contas: contas do Sicoob; 'pasta' é o destino dos arquivos da conta",
    ],
    "empresas": [
        {"nome": "EMPRESA EXEMPLO",
         "pastas_vazias": ["CAIXA", "INTER"],
         "contas": [{"numero": "12.345-6", "pasta": "SICOOB"}]},
        {"nome": "EMPRESA COM SUBCONTAS",
         "pastas_vazias": [],
         "contas": [
             {"numero": "11.111-1", "pasta": "CONTA PRINCIPAL - 11111-1 - SICOOB"},
             {"numero": "22.222-2", "pasta": "SUBCONTA - 22222-2 - LOTE 01 - SICOOB"},
         ]},
    ],
}


def criar_modelo(caminho: Path | None = None) -> Path:
    """Escreve um modelo com contas fictícias. Nunca sobrescreve o existente."""
    caminho = caminho or cfg.ARQUIVO_CONTAS
    if caminho.exists():
        return caminho
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(_MODELO, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    return caminho
