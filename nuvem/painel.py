# -*- coding: utf-8 -*-
"""Os arquivos do painel do Saldo moram na nuvem (17/11/2026).

`config.yaml`, `mapping.yaml`, `MODELO.xlsx` e `conciliacao_ofx.json`
existiam só na máquina do dono, e toda aba que os lê (Saldo de pagamentos,
Pagamentos do dia, Conciliação) quebrava nas outras ("No such file
or directory: config.yaml"). Agora ficam na tabela `arquivo_do_painel`
(migration `20261117100000`), e `sincronizar` roda na abertura, logo depois
do cadastro, e depois do «Atualizar contas».

**Três versões por arquivo, e quem ganha.** O disco (`local`), a nuvem e a
última que esta máquina sincronizou (`estado`, em `painel_nuvem.json`):

- igual nos dois lados → nada;
- só a nuvem mudou (o disco é o da última sincronia, ou não existe) → baixa;
- só o disco mudou e quem usa é ADMIN → sobe, e só se a nuvem ainda for a
  que ele conhecia (PATCH filtrado pelo sha antigo: outra máquina que subiu
  antes faz alterar zero linhas, e isso vira aviso, nunca sobrescrita);
- quem NÃO é admin espelha a nuvem: o disco diferente é guardado em
  `copias do painel/<data hora> nuvem/` e troca pelo da nuvem;
- admin com os dois lados mudados (ou sem sincronia anterior e diferente)
  → fica o do disco e avisa. Nunca se escolhe sozinho.

**Revisão de dinheiro (17/11/2026):**

- **a nuvem vazia nunca recebe nada automático.** A primeira carga é um ato
  do dono (feita pelo SQL a partir da pasta da instalação dele): senão o
  primeiro admin a abrir o app — com um MODELO velho — subiria o dele para
  todo mundo;
- **config, mapping e MODELO são UM pacote** (`PACOTE`): uma inclusão de
  conta muda os três juntos, e mapping novo com MODELO velho põe o saldo de
  uma conta na linha de outra. O pacote só baixa ou sobe inteiro e só depois
  de CONFERIDO (`conferir_pacote`: os três abrem e os rótulos do mapping
  batem com a coluna B do modelo, a mesma régua do Saldo). Subida que falha
  no meio volta a tentar na abertura seguinte (o estado só anota o que foi);
- os avisos vão para a tela (o app mostra depois de montar a janela), não só
  para o `diagnostico.log`.

Toda troca no disco guarda antes a cópia do arquivo velho. Gravar falhando
(o MODELO aberto no Excel) só avisa: o app abre igual.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import io
import json
import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import util

from . import cache, rest

log = logging.getLogger(__name__)

TABELA = "arquivo_do_painel"
PACOTE = ("config.yaml", "mapping.yaml", "MODELO.xlsx")
SOLTOS = ("conciliacao_ofx.json",)
NOMES = PACOTE + SOLTOS
ESTADO = "painel_nuvem.json"
COPIAS = "copias do painel"


@dataclass
class Resultado:
    ok: bool
    recado: str = ""
    baixados: list = field(default_factory=list)
    subidos: list = field(default_factory=list)
    avisos: list = field(default_factory=list)

    def linhas(self) -> list[str]:
        """O que vai ao diagnóstico."""
        saida = []
        if self.recado:
            saida.append(f"arquivos do painel: {self.recado}")
        if self.baixados:
            saida.append("arquivos do painel baixados da nuvem: " + ", ".join(self.baixados))
        if self.subidos:
            saida.append("arquivos do painel enviados à nuvem: " + ", ".join(self.subidos))
        saida.extend(f"arquivos do painel: {a}" for a in self.avisos)
        return saida


def sha(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


def _ler_estado(pasta) -> dict:
    dados = cache.ler_json(ESTADO, pasta)
    return {k: v for k, v in dados.items() if k in NOMES and isinstance(v, str)}


def _gravar_estado(estado: dict, pasta) -> None:
    cache.gravar_json(ESTADO, {
        "_ajuda": ["O sha256 de cada arquivo do painel na última sincronia com a "
                   "nuvem (nuvem/painel.py). Apagar este arquivo é seguro: na "
                   "próxima abertura o app compara de novo."],
        **estado}, pasta)


def conteudo_valido(nome: str, conteudo: bytes) -> bool:
    """Só para os soltos (o pacote passa por `conferir_pacote`)."""
    if not conteudo:
        return False
    try:
        json.loads(conteudo.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return False
    return True


def conferir_pacote(config: bytes, mapping: bytes, modelo: bytes) -> str:
    """"" quando os três abrem e se entendem; senão, o porquê. A mesma régua
    do Saldo (`workbook.check_labels`): rótulo do mapping fora da coluna B do
    modelo é o saldo de uma conta na linha de outra."""
    import openpyxl

    from conciliacao import workbook
    from conciliacao.config import load_config
    from conciliacao.mapping import AccountMapping
    try:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.yaml").write_bytes(config)
            (Path(d) / "mapping.yaml").write_bytes(mapping)
            cfg = load_config(Path(d) / "config.yaml")
            mapa = AccountMapping.load(Path(d) / "mapping.yaml")
        wb = openpyxl.load_workbook(io.BytesIO(modelo))
        workbook.check_labels(workbook._sheet(wb, cfg.planilha), mapa)
    except Exception as e:                                   # noqa: BLE001
        texto = (str(e).strip().splitlines() or [type(e).__name__])[0][:200]
        return f"o pacote não confere ({type(e).__name__}: {texto})"
    return ""


def _pasta_da_copia(pasta, agora: datetime.datetime) -> Path:
    destino = Path(pasta) / COPIAS / f"{agora:%Y-%m-%d %Hh%Mm%S} nuvem"
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def decidir(local: str | None, nuvem: str | None, ultimo: str | None,
            admin: bool) -> str:
    """'nada' | 'baixar' | 'subir' | 'conflito' — pura, para o teste."""
    if nuvem is None:
        return "nada"                    # 1ª carga é ato do dono, nunca automática
    if local == nuvem:
        return "nada"
    if local is None:
        return "baixar"
    if not admin:
        return "baixar"
    if ultimo is not None and local == ultimo:
        return "baixar"
    if ultimo is not None and nuvem == ultimo:
        return "subir"
    return "conflito"


def _acao_do_pacote(acoes: dict) -> str:
    """Uma ação para os três: misturar baixar e subir é conflito."""
    tipos = {a for a in acoes.values() if a != "nada"}
    if not tipos:
        return "nada"
    if tipos == {"baixar"}:
        return "baixar"
    if tipos == {"subir"}:
        return "subir"
    return "conflito"


def sincronizar(token: str, admin: bool, pasta=None,
                agora: datetime.datetime | None = None) -> Resultado:
    """Na abertura e depois do "Atualizar contas". Nunca levanta por rede."""
    pasta = Path(pasta or util.pasta_base())
    agora = agora or datetime.datetime.now()
    if not token:
        return Resultado(False, "sem sessão na nuvem — fica o que está no disco")
    try:
        linhas = rest.ler(TABELA, token, colunas="nome,sha256,conteudo")
    except rest.ErroDaNuvem as e:
        return Resultado(False, f"sem resposta da nuvem ({e}) — fica o que está no disco")
    na_nuvem = {ln["nome"]: ln for ln in linhas if ln.get("nome") in NOMES}
    estado = _ler_estado(pasta)
    r = Resultado(True)

    local, shas, acoes = {}, {}, {}
    for nome in NOMES:
        p = cache.caminho(nome, pasta)
        try:
            local[nome] = p.read_bytes() if p.is_file() else None
        except OSError as e:
            r.avisos.append(f"não consegui ler {nome} ({e})")
            local[nome] = None
            acoes[nome] = "erro"
            continue
        shas[nome] = sha(local[nome]) if local[nome] is not None else None
        linha = na_nuvem.get(nome)
        acoes[nome] = decidir(shas[nome], linha["sha256"] if linha else None,
                              estado.get(nome), admin)

    def da_nuvem(nome) -> bytes | None:
        linha = na_nuvem[nome]
        conteudo = base64.b64decode(linha["conteudo"])
        return conteudo if sha(conteudo) == linha["sha256"] else None

    def baixar(nomes, conteudos):
        copia = None
        for nome in nomes:
            p = cache.caminho(nome, pasta)
            try:
                if local[nome] is not None:
                    copia = copia or _pasta_da_copia(pasta, agora)
                    shutil.copy2(p, copia / nome)
                cache._trocar(p, conteudos[nome])
            except OSError as e:
                r.avisos.append(f"{nome}: não consegui gravar no disco ({e}) — "
                                "feche o arquivo se estiver aberto")
                continue
            estado[nome] = sha(conteudos[nome])
            r.baixados.append(nome)

    def subir(nome):
        b64 = base64.b64encode(local[nome]).decode("ascii")
        antigo = estado[nome]
        filtro = f"nome=eq.{quote(nome)}&sha256=eq.{quote(antigo)}"
        try:
            feitas = rest.alterar(TABELA, token, filtro,
                                  {"conteudo": b64, "sha256": shas[nome]})
            if len(feitas) != 1:
                agora_na_nuvem = rest.ler(TABELA, token, colunas="sha256",
                                          filtro=f"nome=eq.{quote(nome)}")
                if agora_na_nuvem and agora_na_nuvem[0].get("sha256") == antigo:
                    r.avisos.append(f"{nome}: a nuvem recusou a troca (só o "
                                    "administrador ativo envia o painel)")
                else:
                    r.avisos.append(f"{nome}: outra máquina mudou a da nuvem antes "
                                    "— o seu não subiu; confira qual vale")
                return False
        except rest.ErroDaNuvem as e:
            r.avisos.append(f"{nome}: a nuvem recusou ({e})")
            return False
        estado[nome] = shas[nome]
        r.subidos.append(nome)
        return True

    # --- o pacote: os três juntos, sempre conferidos
    acao = _acao_do_pacote({n: acoes.get(n, "nada") for n in PACOTE})
    if "erro" in (acoes.get(n) for n in PACOTE):
        acao = "nada"
    if acao == "conflito":
        r.avisos.append("o painel (config, mapping e MODELO) mudou no disco e na "
                        "nuvem — fica o do disco; confira qual vale")
    elif acao == "baixar":
        novos = {n: (da_nuvem(n) if acoes[n] == "baixar" else local[n]) for n in PACOTE}
        if any(c is None for c in novos.values()):
            r.avisos.append("o painel da nuvem está incompleto ou não confere — "
                            "fica o do disco")
        else:
            porque = conferir_pacote(novos["config.yaml"], novos["mapping.yaml"],
                                     novos["MODELO.xlsx"])
            if porque:
                r.avisos.append(f"o painel da nuvem não foi baixado: {porque}")
            else:
                baixar([n for n in PACOTE if acoes[n] == "baixar"], novos)
    elif acao == "subir":
        if any(local[n] is None for n in PACOTE):
            r.avisos.append("o painel do disco está incompleto — não subiu")
        else:
            porque = conferir_pacote(local["config.yaml"], local["mapping.yaml"],
                                     local["MODELO.xlsx"])
            if porque:
                r.avisos.append(f"o painel do disco não subiu: {porque}")
            else:
                # MODELO primeiro e config por último: falhando no meio, o
                # mapping nunca chega antes do modelo que o casa; a abertura
                # seguinte tenta de novo o que faltou.
                for nome in ("MODELO.xlsx", "mapping.yaml", "config.yaml"):
                    if acoes[nome] == "subir" and not subir(nome):
                        break
    for n in PACOTE:
        if acoes.get(n) == "nada" and shas.get(n) and na_nuvem.get(n, {}).get("sha256") == shas[n]:
            estado[n] = shas[n]

    # --- os soltos, um a um
    for nome in SOLTOS:
        a = acoes.get(nome)
        if a == "baixar":
            conteudo = da_nuvem(nome)
            if conteudo is None or not conteudo_valido(nome, conteudo):
                r.avisos.append(f"{nome} da nuvem não confere — fica o do disco")
            else:
                baixar([nome], {nome: conteudo})
        elif a == "subir":
            if conteudo_valido(nome, local[nome] or b""):
                subir(nome)
            else:
                r.avisos.append(f"{nome} do disco não é um JSON válido — não subiu")
        elif a == "conflito":
            r.avisos.append(f"{nome}: mudou no disco e na nuvem — fica o do disco")
        elif a == "nada" and shas.get(nome) and na_nuvem.get(nome, {}).get("sha256") == shas[nome]:
            estado[nome] = shas[nome]

    try:
        _gravar_estado(estado, pasta)
    except OSError as e:
        r.avisos.append(f"não consegui gravar {ESTADO} ({e})")
    return r
