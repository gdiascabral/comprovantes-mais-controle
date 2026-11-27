# -*- coding: utf-8 -*-
"""O arquivo do servidor (pasta de chaves, NUNCA no repo), lido e conferido.

    {"ambiente": "producao",
     "nuvem_email": "...", "nuvem_senha": "...",          (o usuário de papel robo)
     "pasta": "c:/.../leitura-manha",                     (trava e registro)
     "empresas": [
       {"nome": "EMPRESA A",
        "sicoob": {"client_id": "...", "cert": ["c:/.../cert.pem", "c:/.../chave.pem"]},
        "inter":  {"client_id": "...", "client_secret": "...", "cert": ["...", "..."]},
        "contas": [
          {"banco": "sicoob", "numero": 123456, "conta_erp": "NOME DA CONTA NO ERP"},
          {"banco": "inter", "conta_corrente": "", "conta_erp": "NOME DA CONTA NO ERP"}]}]}

Cada CNPJ tem certificado e app próprios no banco: as credenciais são POR
EMPRESA. `conta_erp` é o nome da conta no Mais Controle (o mesmo de
`pagamento_agendado.conta`). Mensagem de erro nunca repete valor de segredo.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

AMBIENTES = ("producao", "sandbox")
BANCOS = ("sicoob", "inter")


class ConfigInvalida(ValueError):
    """O arquivo do servidor não serve. A mensagem diz o campo, nunca o valor."""


@dataclass(frozen=True)
class ContaBanco:
    empresa: str
    banco: str
    conta_erp: str
    numero: int = field(default=0, repr=False)              # Sicoob: numeroContaCorrente
    conta_corrente: str = field(default="", repr=False)     # Inter: x-conta-corrente (só com mais de uma conta)


@dataclass(frozen=True)
class Empresa:
    nome: str
    contas: tuple
    sicoob: dict | None = field(default=None, repr=False)
    inter: dict | None = field(default=None, repr=False)


@dataclass(frozen=True)
class Config:
    ambiente: str
    pasta: str
    empresas: tuple
    nuvem_email: str = field(default="", repr=False)
    nuvem_senha: str = field(default="", repr=False)

    def contas(self) -> list[ContaBanco]:
        return [c for e in self.empresas for c in e.contas]


def _texto(d: dict, campo: str, onde: str) -> str:
    v = d.get(campo)
    if not isinstance(v, str) or not v.strip():
        raise ConfigInvalida(f"{onde}: falta '{campo}'")
    return v.strip()


def _cert(d: dict, onde: str):
    c = d.get("cert")
    if c is None:
        return None
    if (not isinstance(c, list) or len(c) != 2
            or not all(isinstance(x, str) and x.strip() for x in c)):
        raise ConfigInvalida(f"{onde}: 'cert' tem de ser [certificado, chave]")
    return [x.strip() for x in c]


def _credencial_sicoob(d, ambiente: str, onde: str) -> dict:
    if not isinstance(d, dict):
        raise ConfigInvalida(f"{onde}: falta o bloco 'sicoob'")
    cred = {"client_id": _texto(d, "client_id", onde), "cert": _cert(d, onde)}
    if ambiente == "sandbox":
        cred["token_fixo"] = _texto(d, "token_fixo", onde)
    elif cred["cert"] is None:
        raise ConfigInvalida(f"{onde}: produção do Sicoob exige 'cert'")
    return cred


def _credencial_inter(d, onde: str) -> dict:
    if not isinstance(d, dict):
        raise ConfigInvalida(f"{onde}: falta o bloco 'inter'")
    cred = {"client_id": _texto(d, "client_id", onde),
            "client_secret": _texto(d, "client_secret", onde), "cert": _cert(d, onde)}
    if cred["cert"] is None:
        raise ConfigInvalida(f"{onde}: o Inter exige 'cert'")
    return cred


def de_dict(d: dict) -> Config:
    if not isinstance(d, dict):
        raise ConfigInvalida("o arquivo não é um objeto JSON")
    ambiente = d.get("ambiente")
    if ambiente not in AMBIENTES:
        raise ConfigInvalida(f"'ambiente' tem de ser um de {AMBIENTES}")
    empresas, vistas, nomes, numeros = [], set(), set(), set()
    for k, e in enumerate(d.get("empresas") or ()):
        onde = f"empresa {k + 1}"
        if not isinstance(e, dict):
            raise ConfigInvalida(f"{onde}: não é objeto")
        nome = _texto(e, "nome", onde)
        if nome in nomes:
            raise ConfigInvalida(f"{onde}: nome de empresa repetido no arquivo")
        nomes.add(nome)
        contas = []
        for j, c in enumerate(e.get("contas") or ()):
            ondec = f"{nome}, conta {j + 1}"
            if not isinstance(c, dict) or c.get("banco") not in BANCOS:
                raise ConfigInvalida(f"{ondec}: 'banco' tem de ser um de {BANCOS}")
            erp = _texto(c, "conta_erp", ondec)
            if erp in vistas:
                raise ConfigInvalida(f"{ondec}: conta_erp repetida no arquivo")
            vistas.add(erp)
            if c["banco"] == "sicoob":
                n = c.get("numero")
                if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
                    raise ConfigInvalida(f"{ondec}: 'numero' do Sicoob tem de ser inteiro > 0")
                if n in numeros:
                    raise ConfigInvalida(f"{ondec}: 'numero' do Sicoob repetido no arquivo")
                numeros.add(n)
                contas.append(ContaBanco(nome, "sicoob", erp, numero=n))
            else:
                cc = c.get("conta_corrente") or ""
                if not isinstance(cc, str) or (cc and not (cc.isascii() and cc.isdigit())):
                    raise ConfigInvalida(f"{ondec}: 'conta_corrente' do Inter só com dígitos")
                contas.append(ContaBanco(nome, "inter", erp, conta_corrente=cc))
        if not contas:
            raise ConfigInvalida(f"{onde}: sem contas")
        inter_cc = [c.conta_corrente for c in contas if c.banco == "inter"]
        if len(inter_cc) > 1 and not all(inter_cc):
            # sem o x-conta-corrente, as duas leriam a MESMA conta (a padrão da integração)
            raise ConfigInvalida(f"{nome}: com mais de uma conta do Inter, todas exigem 'conta_corrente'")
        if len(set(inter_cc)) != len(inter_cc):
            raise ConfigInvalida(f"{nome}: 'conta_corrente' do Inter repetida na empresa")
        bancos = {c.banco for c in contas}
        sicoob = _credencial_sicoob(e.get("sicoob"), ambiente, nome) if "sicoob" in bancos else None
        inter = _credencial_inter(e.get("inter"), nome) if "inter" in bancos else None
        empresas.append(Empresa(nome, tuple(contas), sicoob, inter))
    if not empresas:
        raise ConfigInvalida("sem empresas")
    pasta = _texto(d, "pasta", "arquivo")
    if ambiente == "producao":
        return Config(ambiente, pasta, tuple(empresas), _texto(d, "nuvem_email", "arquivo"),
                      _texto(d, "nuvem_senha", "arquivo"))
    return Config(ambiente, pasta, tuple(empresas))


def carregar(caminho) -> Config:
    try:
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ConfigInvalida(f"não consegui ler o arquivo ({type(e).__name__})") from None
    return de_dict(dados)
