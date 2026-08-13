"""Memória das remessas — o que o layout exige e o arquivo não guarda.

O CNAB 240 tem quatro numerações sequenciais, e três delas se resolvem sozinhas
dentro do próprio arquivo: o número do lote (``0001``, ``0002``…), o NSR (que
reinicia em 1 a cada lote) e o "seu número", que é por pagamento. A quarta é
diferente:

    G018 — Número Seqüencial do Arquivo (header, posições 158-163)
    "Número seqüencial adotado e controlado pelo responsável pela geração do
     arquivo. Evoluir um número seqüencial a cada header de arquivo."
    Sicoob: "deverá ser preenchido de forma crescente."

Quem controla é quem gera — o banco não guarda isso por você, e o
``ArquivoRemessa`` recebe o NSA pronto. Este módulo é a memória que faltava.

Decisões, e o porquê de cada uma
--------------------------------

**O contador é por convênio, não por conta.** O guia não diz em que nível o
Sicoob confere o NSA. Contar por convênio é a escolha grosseira de propósito:
se o banco conferir por conta, contar por convênio apenas pula números — e
pular é inofensivo. O inverso não: contar por conta quando o banco confere por
convênio faria dois arquivos nascerem com o mesmo NSA. Entre errar para o lado
do furo e errar para o lado da repetição, o furo é o único aceitável.

**Mora em arquivo próprio, longe do cadastro.** O cadastro das empresas é
copiado, editado à mão e restaurado de backup. Um contador dentro dele voltaria
no tempo junto com a restauração — e voltar no tempo é a única coisa que este
número não pode fazer.

**Ele nunca anda sozinho para trás.** Só ``ajustar_nsa`` recua, o ajuste exige
motivo e fica gravado. Um histórico que apaga a própria correção mente
exatamente onde alguém foi consultá-lo.

**Descartar devolve o número, mas só se ninguém pegou depois.** Gerou, conferiu
e desistiu: o número volta se ainda for o último. Se outra remessa já saiu no
meio, fica o furo — porque o alternativo é repetir.

Uso
---

    historico = Historico("remessas.json")

    arquivo = ArquivoRemessa(empresa, nsa=historico.proximo_nsa("123456"))
    ...
    caminho = arquivo.salvar("REM0007.REM")
    historico.registrar(arquivo, caminho_arquivo=caminho,
                        referencias={"260813-0001": "<id do lançamento>"})

E o que o histórico passa a responder:

    historico.envio_de(codigo_barras)          # já mandei este boleto?
    historico.envio_da_referencia(id_erp)      # já mandei este lançamento?
    historico.remessas(convenio="123456")        # a tela de histórico
    historico.ajustar_nsa("123456", 42, motivo="...")   # o campo editável
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from .modelos import dinheiro, so_digitos

#: O campo G018 tem 6 posições — passar disso não cabe no header.
NSA_MAXIMO = 999_999

#: Estados do ciclo de vida de uma remessa. O app só transmite à mão, então
#: "enviado" em diante é marcação humana (ou, adiante, leitura do retorno).
ESTADOS = ("gerado", "enviado", "processado", "rejeitado", "descartado")

#: Estados em que a remessa ainda vale como "já mandei isso".
ESTADOS_VIVOS = tuple(e for e in ESTADOS if e != "descartado")

_VERSAO_ARQUIVO = 1

_AJUDA = [
    "Memória das remessas CNAB 240: o contador do NSA por convênio, o que já",
    "foi gerado e o de-para 'seu número' -> lançamento de origem.",
    "O NSA (header do arquivo, posições 158-163) tem de ser CRESCENTE por",
    "convênio. Pular número é inofensivo; repetir, não — um arquivo reenviado",
    "que passe pelo banco é pagamento em dobro.",
    "Para corrigir o contador use a função de ajuste (ela exige motivo e fica",
    "registrada em 'ajustes'), e não a edição deste arquivo na mão.",
    "Tem dado de pagamento da empresa: NUNCA vai para o repositório.",
]


class HistoricoInvalido(ValueError):
    """Operação que deixaria o histórico incoerente."""


# --------------------------------------------------------------------------
# Registros
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    """Um pagamento dentro de uma remessa — a linha do de-para.

    ``identificador`` é a chave natural do *instrumento* e só existe quando ela
    é de fato única: o código de barras de um boleto. Chave Pix e dados de
    conta ficam de fora de propósito — o mesmo fornecedor recebe várias vezes
    por dia, e transformar isso em "duplicado" seria alarme falso diário.

    ``referencia`` é a chave do *lançamento* no sistema de origem (o id do
    ERP). É ela que responde "este lançamento já foi mandado?" para qualquer
    forma de pagamento, e é ela que o retorno reencontra pelo "seu número".
    """

    seu_numero: str
    valor: Decimal
    favorecido: str = ""
    produto: str = ""
    identificador: str = ""
    referencia: str = ""

    def como_json(self) -> dict[str, Any]:
        return {
            "seu_numero": self.seu_numero,
            "valor": str(self.valor),
            "favorecido": self.favorecido,
            "produto": self.produto,
            "identificador": self.identificador,
            "referencia": self.referencia,
        }

    @classmethod
    def do_json(cls, d: dict[str, Any]) -> "Item":
        return cls(
            seu_numero=d.get("seu_numero", ""),
            valor=dinheiro(d.get("valor", "0")),
            favorecido=d.get("favorecido", ""),
            produto=d.get("produto", ""),
            identificador=d.get("identificador", ""),
            referencia=d.get("referencia", ""),
        )


@dataclass
class RemessaGerada:
    """Um arquivo gerado, com o que foi mandado dentro dele."""

    convenio: str
    nsa: int
    empresa: str = ""
    documento: str = ""
    agencia: str = ""
    conta: str = ""
    gerado_em: _dt.datetime | None = None
    arquivo: str = ""
    sha256: str = ""
    estado: str = "gerado"
    observacao: str = ""
    itens: list[Item] = field(default_factory=list)

    @property
    def quantidade(self) -> int:
        return len(self.itens)

    @property
    def total(self) -> Decimal:
        return sum((i.valor for i in self.itens), Decimal("0"))

    @property
    def viva(self) -> bool:
        return self.estado in ESTADOS_VIVOS

    def como_json(self) -> dict[str, Any]:
        return {
            "convenio": self.convenio,
            "nsa": self.nsa,
            "empresa": self.empresa,
            "documento": self.documento,
            "agencia": self.agencia,
            "conta": self.conta,
            "gerado_em": self.gerado_em.isoformat(timespec="seconds") if self.gerado_em else "",
            "arquivo": self.arquivo,
            "sha256": self.sha256,
            "estado": self.estado,
            "observacao": self.observacao,
            "quantidade": self.quantidade,
            "total": str(self.total),
            "itens": [i.como_json() for i in self.itens],
        }

    @classmethod
    def do_json(cls, d: dict[str, Any]) -> "RemessaGerada":
        quando = d.get("gerado_em") or ""
        return cls(
            convenio=str(d.get("convenio", "")),
            nsa=int(d.get("nsa", 0)),
            empresa=d.get("empresa", ""),
            documento=d.get("documento", ""),
            agencia=d.get("agencia", ""),
            conta=d.get("conta", ""),
            gerado_em=_dt.datetime.fromisoformat(quando) if quando else None,
            arquivo=d.get("arquivo", ""),
            sha256=d.get("sha256", ""),
            estado=d.get("estado", "gerado"),
            observacao=d.get("observacao", ""),
            itens=[Item.do_json(i) for i in d.get("itens", [])],
        )


@dataclass(frozen=True)
class Ajuste:
    """Uma correção manual do contador — o campo editável, com rastro."""

    convenio: str
    de: int
    para: int
    motivo: str
    quando: _dt.datetime

    def como_json(self) -> dict[str, Any]:
        return {
            "convenio": self.convenio,
            "de": self.de,
            "para": self.para,
            "motivo": self.motivo,
            "quando": self.quando.isoformat(timespec="seconds"),
        }

    @classmethod
    def do_json(cls, d: dict[str, Any]) -> "Ajuste":
        return cls(
            convenio=str(d.get("convenio", "")),
            de=int(d.get("de", 0)),
            para=int(d.get("para", 0)),
            motivo=d.get("motivo", ""),
            quando=_dt.datetime.fromisoformat(d["quando"]) if d.get("quando") else _dt.datetime.min,
        )


# --------------------------------------------------------------------------
# Derivação dos itens a partir do arquivo gerado
# --------------------------------------------------------------------------


def _identificador(pagamento: Any) -> str:
    """Chave natural do instrumento — só o código de barras a tem de verdade.

    O ``PixQRCode`` traz 44 zeros no campo de código de barras (o manual manda
    preencher mesmo sem boleto); zeros não identificam nada e ficam de fora.
    """
    barras = so_digitos(getattr(pagamento, "codigo_barras", ""))
    if barras and set(barras) != {"0"}:
        return barras
    return ""


def _favorecido(pagamento: Any) -> str:
    fav = getattr(pagamento, "favorecido", None)
    if fav is not None and getattr(fav, "nome", ""):
        return str(fav.nome)
    for attr in ("nome_cedente", "nome_concessionaria", "nome_contribuinte"):
        nome = getattr(pagamento, attr, "")
        if nome:
            return str(nome)
    return ""


def itens_de(arquivo: Any, referencias: dict[str, str] | None = None) -> list[Item]:
    """Extrai o de-para de um ``ArquivoRemessa`` já montado.

    ``referencias`` liga cada "seu número" ao lançamento de origem; o que não
    estiver no dicionário fica com referência vazia — visível, não inventada.
    """
    de_para = referencias or {}
    itens: list[Item] = []
    for lote in arquivo.lotes:
        for pagamento in lote.pagamentos:
            seu_numero = str(getattr(pagamento, "seu_numero", "") or "")
            itens.append(
                Item(
                    seu_numero=seu_numero,
                    valor=dinheiro(pagamento.valor),
                    favorecido=_favorecido(pagamento),
                    produto=lote.produto,
                    identificador=_identificador(pagamento),
                    referencia=str(de_para.get(seu_numero, "")),
                )
            )
    return itens


# --------------------------------------------------------------------------
# Gravação
# --------------------------------------------------------------------------


class _Trava:
    """Exclusão mútua entre processos para o ciclo ler-alterar-gravar.

    Sem ela, dois app abertos leem o mesmo último NSA e gravam o mesmo próximo
    — o único desfecho que este módulo existe para impedir. A trava é um
    arquivo criado com ``O_EXCL``; travas órfãs (de um processo que morreu)
    expiram por idade.
    """

    def __init__(self, caminho: Path, *, espera: float = 10.0, validade: float = 60.0) -> None:
        self.caminho = caminho.with_suffix(caminho.suffix + ".lock")
        self.espera = espera
        self.validade = validade
        self._fd: int | None = None

    def __enter__(self) -> "_Trava":
        limite = time.monotonic() + self.espera
        while True:
            try:
                self._fd = os.open(self.caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                if self._orfa():
                    continue
                if time.monotonic() >= limite:
                    raise HistoricoInvalido(
                        f"o histórico está travado por outro processo ({self.caminho}). "
                        "Feche a outra janela do app; se ninguém mais estiver gerando "
                        "remessa, apague esse arquivo de trava."
                    ) from None
                time.sleep(0.05)

    def _orfa(self) -> bool:
        try:
            idade = time.time() - self.caminho.stat().st_mtime
        except OSError:
            return True
        if idade <= self.validade:
            return False
        try:
            self.caminho.unlink()
        except OSError:
            return False
        return True

    def __exit__(self, *_: Any) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self.caminho.unlink()
        except OSError:
            pass


class Historico:
    """O contador do NSA e o registro do que já foi gerado.

    Cada operação de escrita relê o arquivo sob trava antes de gravar: quem
    tem o objeto na mão pode estar com uma cópia velha na memória, e o número
    que sai daqui não pode depender disso.
    """

    def __init__(self, caminho: str | Path) -> None:
        self.caminho = Path(caminho)
        self._dados = self._ler()

    # -- leitura ------------------------------------------------------------

    def _ler(self) -> dict[str, Any]:
        if not self.caminho.exists():
            return {"versao": _VERSAO_ARQUIVO, "_ajuda": _AJUDA, "convenios": {}, "remessas": [], "ajustes": []}
        try:
            dados = json.loads(self.caminho.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as erro:
            raise HistoricoInvalido(
                f"não consegui ler o histórico de remessas em {self.caminho}: {erro}. "
                "Sem ele não dá para saber o último NSA usado — restaure o arquivo "
                "antes de gerar remessa."
            ) from erro
        dados.setdefault("convenios", {})
        dados.setdefault("remessas", [])
        dados.setdefault("ajustes", [])
        return dados

    def recarregar(self) -> "Historico":
        self._dados = self._ler()
        return self

    @staticmethod
    def _chave(convenio: str) -> str:
        chave = str(convenio or "").strip().upper()
        if not chave:
            raise HistoricoInvalido(
                "convênio vazio: o contador do NSA é por convênio, e empresa sem "
                "convênio não pode gerar remessa (o header do arquivo não fecha)."
            )
        return chave

    def ultimo_nsa(self, convenio: str) -> int:
        """O último número usado. Zero quando o convênio nunca gerou nada."""
        registro = self._dados["convenios"].get(self._chave(convenio))
        return int(registro["ultimo_nsa"]) if registro else 0

    def contadores(self) -> dict[str, dict[str, Any]]:
        """O último NSA de cada convênio — o que a tela de histórico mostra."""
        return {chave: dict(dados) for chave, dados in sorted(self._dados["convenios"].items())}

    def proximo_nsa(self, convenio: str) -> int:
        """O número que a próxima remessa vai usar. Consulta — não consome."""
        proximo = self.ultimo_nsa(convenio) + 1
        if proximo > NSA_MAXIMO:
            raise HistoricoInvalido(
                f"o NSA do convênio {convenio} chegou a {NSA_MAXIMO}, o teto das 6 "
                "posições do campo G018. Combine o reinício com a cooperativa e use "
                "ajustar_nsa() para voltar a zero."
            )
        return proximo

    def remessas(self, *, convenio: str | None = None, estado: str | None = None) -> list[RemessaGerada]:
        """As remessas gravadas, da mais recente para a mais antiga."""
        todas = [RemessaGerada.do_json(r) for r in self._dados["remessas"]]
        if convenio is not None:
            chave = self._chave(convenio)
            todas = [r for r in todas if r.convenio == chave]
        if estado is not None:
            todas = [r for r in todas if r.estado == estado]
        return sorted(todas, key=lambda r: (r.gerado_em or _dt.datetime.min, r.nsa), reverse=True)

    def remessa(self, convenio: str, nsa: int) -> RemessaGerada | None:
        chave = self._chave(convenio)
        for bruto in self._dados["remessas"]:
            if str(bruto.get("convenio")) == chave and int(bruto.get("nsa", 0)) == int(nsa):
                return RemessaGerada.do_json(bruto)
        return None

    def ajustes(self, *, convenio: str | None = None) -> list[Ajuste]:
        todos = [Ajuste.do_json(a) for a in self._dados["ajustes"]]
        if convenio is not None:
            chave = self._chave(convenio)
            todos = [a for a in todos if a.convenio == chave]
        return sorted(todos, key=lambda a: a.quando, reverse=True)

    # -- consultas do de-para ----------------------------------------------

    def _itens_vivos(self) -> Iterable[tuple[RemessaGerada, Item]]:
        for bruto in self._dados["remessas"]:
            remessa = RemessaGerada.do_json(bruto)
            if not remessa.viva:
                continue
            for item in remessa.itens:
                yield remessa, item

    def envio_de(self, identificador: str) -> tuple[RemessaGerada, Item] | None:
        """Este boleto já foi mandado? Compara pelo código de barras.

        Código de barras igual é o mesmo título, sempre — carrega banco, valor,
        vencimento e o nosso número do cedente. É chave natural, não palpite,
        e por isso serve para bloquear.
        """
        alvo = so_digitos(identificador)
        if not alvo:
            return None
        for remessa, item in self._itens_vivos():
            if item.identificador == alvo:
                return remessa, item
        return None

    def envio_da_referencia(self, referencia: str) -> tuple[RemessaGerada, Item] | None:
        """Este lançamento já foi mandado? Vale para qualquer forma de pagamento."""
        alvo = str(referencia or "").strip()
        if not alvo:
            return None
        for remessa, item in self._itens_vivos():
            if item.referencia == alvo:
                return remessa, item
        return None

    def item_por_seu_numero(self, seu_numero: str) -> tuple[RemessaGerada, Item] | None:
        """O caminho de volta do arquivo de retorno até o lançamento de origem."""
        alvo = str(seu_numero or "").strip()
        if not alvo:
            return None
        for remessa, item in self._itens_vivos():
            if item.seu_numero == alvo:
                return remessa, item
        return None

    # -- escrita ------------------------------------------------------------

    def _gravar(self, dados: dict[str, Any]) -> None:
        dados["versao"] = _VERSAO_ARQUIVO
        dados["_ajuda"] = _AJUDA
        temporario = self.caminho.with_suffix(self.caminho.suffix + ".tmp")
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        temporario.write_text(
            json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporario, self.caminho)
        self._dados = dados

    def registrar(
        self,
        arquivo: Any,
        *,
        convenio: str | None = None,
        caminho_arquivo: str | Path | None = None,
        referencias: dict[str, str] | None = None,
        itens: Iterable[Item] | None = None,
        quando: _dt.datetime | None = None,
        estado: str = "gerado",
    ) -> RemessaGerada:
        """Consome o NSA do arquivo gerado e grava a remessa.

        Recebe o ``ArquivoRemessa`` depois de montado — o NSA gravado é o que
        de fato foi para dentro do arquivo, não um número calculado de novo.
        """
        if estado not in ESTADOS:
            raise HistoricoInvalido(f"estado {estado!r} não existe (use um de {ESTADOS})")

        empresa = arquivo.empresa
        chave = self._chave(convenio if convenio is not None else empresa.convenio)
        nsa = int(arquivo.nsa)
        registrados = list(itens) if itens is not None else itens_de(arquivo, referencias)

        conteudo = arquivo.texto()
        caminho = Path(caminho_arquivo) if caminho_arquivo else None

        with _Trava(self.caminho):
            dados = self._ler()
            ultimo = int(dados["convenios"].get(chave, {}).get("ultimo_nsa", 0))
            if nsa <= ultimo:
                raise HistoricoInvalido(
                    f"NSA {nsa} não é maior que o último usado no convênio {chave} "
                    f"({ultimo}). O campo G018 tem de ser crescente — gere o arquivo "
                    f"com proximo_nsa() em vez de repetir um número."
                )
            if nsa > NSA_MAXIMO:
                raise HistoricoInvalido(f"NSA {nsa} passa do teto de 6 posições ({NSA_MAXIMO})")

            self._conferir_seus_numeros(dados, registrados)

            agora = quando or _dt.datetime.now()
            remessa = RemessaGerada(
                convenio=chave,
                nsa=nsa,
                empresa=empresa.nome,
                documento=so_digitos(empresa.documento),
                agencia=str(empresa.agencia),
                conta=str(empresa.conta),
                gerado_em=agora.replace(microsecond=0),
                arquivo=caminho.name if caminho else "",
                sha256=hashlib.sha256(conteudo.encode("latin-1")).hexdigest(),
                estado=estado,
                itens=registrados,
            )
            dados["remessas"].append(remessa.como_json())
            dados["convenios"][chave] = {
                "ultimo_nsa": nsa,
                "atualizado_em": remessa.gerado_em.isoformat(timespec="seconds"),
            }
            self._gravar(dados)
        return remessa

    @staticmethod
    def _conferir_seus_numeros(dados: dict[str, Any], itens: list[Item]) -> None:
        """O "seu número" é o que o retorno devolve — repetido, ele casa errado.

        Vale só contra remessa viva: uma remessa descartada libera os seus, de
        propósito, para que a segunda tentativa do mesmo pagamento possa sair
        com o mesmo número.
        """
        novos = [i.seu_numero for i in itens if i.seu_numero]
        repetidos = {n for n in novos if novos.count(n) > 1}
        if repetidos:
            raise HistoricoInvalido(
                f"'seu número' repetido dentro da mesma remessa: {sorted(repetidos)}"
            )
        usados = {
            item.get("seu_numero"): int(bruto.get("nsa", 0))
            for bruto in dados["remessas"]
            if bruto.get("estado") in ESTADOS_VIVOS
            for item in bruto.get("itens", [])
            if item.get("seu_numero")
        }
        colisao = [(n, usados[n]) for n in novos if n in usados]
        if colisao:
            descricao = ", ".join(f"{n} (NSA {nsa})" for n, nsa in colisao)
            raise HistoricoInvalido(
                f"'seu número' já usado em remessa anterior: {descricao}. "
                "O banco devolve esse número no retorno; repetido, ele casaria "
                "com o pagamento errado."
            )

    def ajustar_nsa(self, convenio: str, novo_ultimo: int, *, motivo: str) -> int:
        """O campo editável: força o contador, com motivo e rastro.

        Existe para três situações reais — a conta já enviou remessa por outro
        caminho e o contador não pode começar em 1; um arquivo foi gerado e
        descartado; o app foi reinstalado e a memória se perdeu.

        Recuar é permitido (é metade da razão de existir), mas nunca para
        aquém de um NSA já gravado: isso faria a próxima remessa repetir um
        número que já saiu.
        """
        chave = self._chave(convenio)
        novo = int(novo_ultimo)
        if novo < 0:
            raise HistoricoInvalido("o NSA não pode ser negativo")
        if novo > NSA_MAXIMO:
            raise HistoricoInvalido(f"o NSA não pode passar de {NSA_MAXIMO} (6 posições)")
        if not str(motivo or "").strip():
            raise HistoricoInvalido(
                "ajuste de NSA exige motivo — é o que explica o furo na sequência "
                "para quem for conferir com o banco depois."
            )

        with _Trava(self.caminho):
            dados = self._ler()
            anterior = int(dados["convenios"].get(chave, {}).get("ultimo_nsa", 0))
            gravados = [
                int(r.get("nsa", 0))
                for r in dados["remessas"]
                if str(r.get("convenio")) == chave and r.get("estado") in ESTADOS_VIVOS
            ]
            maior_gravado = max(gravados, default=0)
            if novo < maior_gravado:
                raise HistoricoInvalido(
                    f"o convênio {chave} já gerou a remessa NSA {maior_gravado}; baixar o "
                    f"contador para {novo} faria a próxima repetir um número já enviado. "
                    "Descarte aquela remessa antes, se ela não foi ao banco."
                )
            agora = _dt.datetime.now().replace(microsecond=0)
            dados["convenios"][chave] = {
                "ultimo_nsa": novo,
                "atualizado_em": agora.isoformat(timespec="seconds"),
            }
            dados["ajustes"].append(
                Ajuste(chave, anterior, novo, str(motivo).strip(), agora).como_json()
            )
            self._gravar(dados)
        return novo

    def marcar(self, convenio: str, nsa: int, estado: str, *, observacao: str = "") -> RemessaGerada:
        """Anda com a remessa no ciclo de vida (gerado -> enviado -> ...)."""
        if estado not in ESTADOS:
            raise HistoricoInvalido(f"estado {estado!r} não existe (use um de {ESTADOS})")
        if estado == "descartado":
            return self.descartar(convenio, nsa, motivo=observacao)
        chave = self._chave(convenio)
        with _Trava(self.caminho):
            dados = self._ler()
            bruto = self._achar(dados, chave, nsa)
            bruto["estado"] = estado
            if observacao:
                bruto["observacao"] = observacao
            self._gravar(dados)
        return RemessaGerada.do_json(bruto)

    def descartar(self, convenio: str, nsa: int, *, motivo: str = "") -> RemessaGerada:
        """Marca a remessa como não enviada e devolve o número, se der.

        O número só volta se ainda for o último do convênio. Se outra remessa
        saiu depois, o contador fica onde está e o furo permanece — devolver
        aqui seria fabricar uma repetição.
        """
        chave = self._chave(convenio)
        with _Trava(self.caminho):
            dados = self._ler()
            bruto = self._achar(dados, chave, nsa)
            bruto["estado"] = "descartado"
            if motivo:
                bruto["observacao"] = motivo
            atual = int(dados["convenios"].get(chave, {}).get("ultimo_nsa", 0))
            if atual == int(nsa):
                vivos = [
                    int(r.get("nsa", 0))
                    for r in dados["remessas"]
                    if str(r.get("convenio")) == chave and r.get("estado") in ESTADOS_VIVOS
                ]
                dados["convenios"][chave] = {
                    "ultimo_nsa": max(vivos, default=0),
                    "atualizado_em": _dt.datetime.now().replace(microsecond=0).isoformat(
                        timespec="seconds"
                    ),
                }
            self._gravar(dados)
        return RemessaGerada.do_json(bruto)

    @staticmethod
    def _achar(dados: dict[str, Any], convenio: str, nsa: int) -> dict[str, Any]:
        for bruto in dados["remessas"]:
            if str(bruto.get("convenio")) == convenio and int(bruto.get("nsa", 0)) == int(nsa):
                return bruto
        raise HistoricoInvalido(f"não há remessa NSA {nsa} no convênio {convenio}")
