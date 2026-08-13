# -*- coding: utf-8 -*-
"""Leva os cadastros locais para o banco. Roda UMA vez, a mao.

Nao entra no `codigo.zip`: e ferramenta de mudanca, como o
`aportes/conferir_contas.py`. Roda na maquina que tem os arquivos bons.

    python nuvem/migrar.py --conferir      # so le e critica, nao escreve
    python nuvem/migrar.py --subir         # escreve, e depois confere
    python nuvem/migrar.py --limpar        # apaga tudo do banco (recomeco)

A ordem importa: **conferir antes de subir**. Migrar divergencia e levar o
problema para dentro do banco, onde ele fica mais dificil de ver.

As chaves saem do proprio Supabase CLI (`npx supabase projects api-keys`), ja
autenticado nesta maquina -- assim nao ha segredo em arquivo nem em variavel
de ambiente para alguem esquecer.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

REF = "hhvuvqayaqxpypdissci"
BASE = f"https://{REF}.supabase.co"

#: Onde estao os arquivos de hoje. A pasta do exe, como todo o resto.
PASTA = Path(sys.argv[0]).resolve().parent.parent
if not (PASTA / "contas_sicoob.json").exists():
    PASTA = Path("C:/AUTOMAÇÕES MAIS CONTROLE/_app")

#: A ordem de apagar e a inversa da de criar: quem aponta sai antes.
TABELAS = ["subconta_obra", "subconta_investidor", "subconta", "entidade",
           "regra_boleto", "regra_fornecedor", "conta", "pasta_vazia",
           "cliente_erp", "empresa", "configuracao"]


# ------------------------------------------------------------------ conversa

def _chaves() -> dict:
    r = subprocess.run(
        ["npx", "--yes", "supabase@latest", "projects", "api-keys",
         "--project-ref", REF, "-o", "json"],
        capture_output=True, text=True, shell=True, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit("nao consegui falar com o Supabase CLI. Rode "
                         "`npx.cmd supabase login` primeiro.")
    return {k["name"]: k["api_key"] for k in json.loads(r.stdout)}


class Banco:
    """O minimo de PostgREST para migrar: inserir, ler e apagar.

    Entra com **login de pessoa**, e nao com a chave de servico. Dois motivos:
    a chave de servico ignora toda a RLS, entao um script que a usasse nao
    provaria nada sobre o caminho que o app vai percorrer; e ela nao tem
    privilegio nenhum nestas tabelas de proposito -- o projeto foi criado sem
    expor tabela automaticamente, e conceder acesso a ela so para migrar seria
    abrir uma porta permanente para um uso de uma vez so.
    """

    def __init__(self, email: str, senha: str) -> None:
        ks = _chaves()
        anon = ks.get("anon") or ks.get("publishable")
        if not anon:
            raise SystemExit(f"faltou a chave publica; vi: {sorted(ks)}")
        req = urllib.request.Request(
            f"{BASE}/auth/v1/token?grant_type=password",
            data=json.dumps({"email": email, "password": senha}).encode(),
            method="POST")
        req.add_header("apikey", anon)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                token = json.loads(r.read().decode())["access_token"]
        except urllib.error.HTTPError as e:
            raise SystemExit(f"login recusado: {e.read().decode()}")
        self._cab = {"apikey": anon, "Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"}

    def _pedir(self, caminho: str, dados=None, metodo="GET", prefer=""):
        req = urllib.request.Request(
            f"{BASE}/rest/v1/{caminho}",
            data=json.dumps(dados).encode() if dados is not None else None,
            method=metodo)
        for k, v in self._cab.items():
            req.add_header(k, v)
        if prefer:
            req.add_header("Prefer", prefer)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                texto = r.read().decode()
                return json.loads(texto) if texto.strip() else None
        except urllib.error.HTTPError as e:
            corpo = e.read().decode()
            raise SystemExit(f"\nERRO {e.code} em {metodo} {caminho}\n{corpo}\n"
                             f"enviado: {json.dumps(dados, ensure_ascii=False)[:400]}")

    def inserir(self, tabela: str, linhas: list[dict]) -> list[dict]:
        if not linhas:
            return []
        return self._pedir(tabela, linhas, "POST", "return=representation")

    def ler(self, tabela: str, colunas="*") -> list[dict]:
        return self._pedir(f"{tabela}?select={colunas}") or []

    def apagar_tudo(self, tabela: str) -> None:
        # PostgREST exige um filtro: `id=gte.0` alcanca todas as linhas.
        coluna = "chave" if tabela == "configuracao" else (
            "subconta_id" if tabela == "subconta_investidor" else "id")
        alvo = "not.is.null" if coluna == "chave" else "gte.0"
        self._pedir(f"{tabela}?{coluna}={alvo}", None, "DELETE")


# -------------------------------------------------------------------- leitura

def _norm(s) -> str:
    """Nome comparavel: sem acento, sem caixa, sem espaco duplo.

    E a mesma regra do `util.norm_espaco`, repetida aqui porque este script
    roda fora do app (e uma ferramenta, nao um modulo importado por ele).
    """
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


def _digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _numero_no_texto(t) -> str:
    m = re.search(r"\b(\d{1,3}[.\s]?\d{3}[-\s]?\d)\b", str(t or ""))
    return _digitos(m.group(1)) if m else ""


def _json(nome: str) -> dict:
    caminho = PASTA / nome
    if not caminho.exists():
        return {}
    return json.loads(caminho.read_text(encoding="utf-8"))


def ler_tudo() -> dict:
    dados = {
        "sicoob": _json("contas_sicoob.json"),
        "mc": _json("contas_mc.json"),
        "subcontas": _json("subcontas.json"),
        "regras_forn": _json("regras_fornecedor.json"),
        "confirmar": _json("confirmar_antes.json"),
        "boletos": _json("regras_boletos.json"),
        "pix": _json("pix_reembolso.json"),
        "entidades": [],
    }
    csv_contas = PASTA / "contas.csv"
    if csv_contas.exists():
        with open(csv_contas, encoding="utf-8-sig", newline="") as f:
            dados["entidades"] = [l for l in csv.DictReader(f, delimiter=";")
                                  if (l.get("nome_exibicao") or "").strip()]
    return dados


# ------------------------------------------------------------------ critica

def criticar(d: dict) -> list[str]:
    """Tudo que impediria uma migracao honesta. Lista vazia = pode subir."""
    problemas = []

    if not d["sicoob"] or not d["mc"]:
        problemas.append("faltou contas_sicoob.json ou contas_mc.json")
        return problemas

    raiz_s = d["sicoob"].get("raiz", "")
    raiz_m = d["mc"].get("raiz", "")
    if raiz_s != raiz_m:
        problemas.append(f"as duas raizes divergem: {raiz_s!r} != {raiz_m!r}")

    # A divergencia que motivou a unificacao. Migra-la seria leva-la para
    # dentro do banco, onde ela ficaria mais dificil de enxergar.
    pastas_mc = {}
    for c in d["mc"]["contas"]:
        num = _numero_no_texto(c.get("erp")) or _numero_no_texto(c.get("pasta"))
        if num:
            pastas_mc[num] = (c.get("pasta") or "").strip()
    for e in d["sicoob"]["empresas"]:
        for c in e.get("contas", []):
            num = _digitos(c.get("numero"))
            outra = pastas_mc.get(num)
            if outra and _norm(outra) != _norm(c.get("pasta")):
                problemas.append(
                    f"conta ...{num[-4:]}: contas_mc manda para {outra!r} e "
                    f"contas_sicoob para {c.get('pasta')!r}")

    # Subconta sem obra OU sem investidor faz o rateio sair vazio, e o valor
    # some sem erro nenhum -- e a mesma checagem que `regras.validar()` faz na
    # tela. O investidor NAO precisa estar no contas.csv: ele e cliente do
    # ERP, nao entidade que aporta.
    for sub, corpo in d["subcontas"].items():
        if sub.startswith("_") or not isinstance(corpo, dict):
            continue
        if not corpo.get("obras"):
            problemas.append(f"subconta {sub}: sem obras, o rateio sairia vazio")
        if not corpo.get("investidores"):
            problemas.append(f"subconta {sub}: sem investidores, idem")

    # Empresa sem conta E sem pasta vazia nao cria nada na arvore do mes.
    for e in d["sicoob"]["empresas"]:
        if not e.get("contas") and not e.get("pastas_vazias"):
            problemas.append(f"empresa {e.get('nome')!r} nao tem conta nem pasta")

    return problemas


# ------------------------------------------------------------------- montagem

def montar_contas(d: dict) -> list[dict]:
    """Une as duas fontes numa lista de contas, sem inventar casamento.

    Casa por NUMERO ou por (empresa, pasta) -- os dois criterios que a analise
    dos dados reais mostrou concordarem em 13 de 13 contas do Sicoob, sem um
    unico conflito. Conta do MC que nao casa com nenhuma do Sicoob entra
    sozinha: sao as de outros bancos, que o SicoobNet nao tem mesmo.
    """
    mc = d["mc"]["contas"]
    usadas = set()
    contas = []

    for e in d["sicoob"]["empresas"]:
        for c in e.get("contas", []):
            numero = c.get("numero", "")
            par = None
            for i, m in enumerate(mc):
                if i in usadas:
                    continue
                mesmo_numero = (_numero_no_texto(m.get("erp"))
                                and _numero_no_texto(m.get("erp")) == _digitos(numero))
                mesmo_lugar = (_norm(m.get("empresa")) == _norm(e["nome"])
                               and _norm(m.get("pasta")) == _norm(c.get("pasta")))
                if mesmo_numero or mesmo_lugar:
                    par, indice = m, i
                    break
            if par is not None:
                usadas.add(indice)
            contas.append({
                "_empresa": e["nome"],
                "numero": numero,
                "agencia": c.get("agencia", ""),
                "nome_erp": (par or {}).get("erp"),
                "pasta": c.get("pasta"),
                # O NOME vem do contas_mc; o CODIGO, do contas_sicoob.
                "banco": (par or {}).get("banco", ""),
                "banco_codigo": c.get("banco", ""),
                "sufixo": (par or {}).get("sufixo", "") or "",
            })

    for i, m in enumerate(mc):
        if i in usadas:
            continue
        contas.append({
            "_empresa": m.get("empresa"),
            "numero": None,
            "agencia": "",
            "nome_erp": m.get("erp"),
            "pasta": m.get("pasta"),
            "banco": m.get("banco", ""),
            "banco_codigo": "",
            "sufixo": m.get("sufixo", "") or "",
        })
    return contas


def montar_regras(d: dict) -> list[dict]:
    regras = []
    for nome, corpo in (d["regras_forn"] or {}).items():
        if nome.startswith("_") or not isinstance(corpo, dict):
            continue
        if corpo.get("so_com_reembolso"):
            regras.append({"tipo": "so_reembolso", "nome": nome, "valor": ""})
        if corpo.get("confirmar_sempre"):
            regras.append({"tipo": "pagar_a_mao", "nome": nome, "valor": ""})
    for nome in (d["confirmar"] or {}).get("nomes", []):
        regras.append({"tipo": "confirmar_antes", "nome": nome, "valor": ""})
    for nome, chave in (d["pix"] or {}).items():
        if not nome.startswith("_") and isinstance(chave, str) and chave.strip():
            regras.append({"tipo": "pix_reembolso", "nome": nome, "valor": chave})
    return regras


# --------------------------------------------------------------------- subir

def subir(banco: Banco, d: dict) -> None:
    print("configuracao...", end=" ", flush=True)
    cfg = [{"chave": "raiz", "valor": d["sicoob"].get("raiz", ""),
            "descricao": "Raiz da arvore de arquivamento do fechamento"},
           {"chave": "vip_url", "valor": d["sicoob"].get("vip_url", ""),
            "descricao": "Endereco do escritorio contabil no portal"}]
    padrao = (d["subcontas"] or {}).get("_obra_padrao", "")
    if padrao:
        cfg.append({"chave": "obra_padrao", "valor": padrao,
                    "descricao": "Obra usada quando a subconta nao diz outra"})
    banco.inserir("configuracao", cfg)
    print(f"{len(cfg)} linhas")

    print("empresas...", end=" ", flush=True)
    empresas = banco.inserir("empresa", [{
        "nome_pasta": e["nome"],
        "vip_id": e.get("vip_id", "") or "",
        "vip_nome": e.get("razao_social", "") or "",
        "cnpj": e.get("cnpj", "") or "",
        "razao_social": e.get("razao_social", "") or "",
        "convenio": e.get("convenio", "") or "",
    } for e in d["sicoob"]["empresas"]])
    ids = {_norm(e["nome_pasta"]): e["id"] for e in empresas}
    print(f"{len(empresas)}")

    print("clientes do ERP e pastas vazias...", end=" ", flush=True)
    clientes, vazias = [], []
    for e in d["sicoob"]["empresas"]:
        eid = ids[_norm(e["nome"])]
        clientes += [{"empresa_id": eid, "nome": n}
                     for n in e.get("clientes_erp", [])]
        vazias += [{"empresa_id": eid, "nome": n}
                   for n in e.get("pastas_vazias", [])]
    banco.inserir("cliente_erp", clientes)
    banco.inserir("pasta_vazia", vazias)
    print(f"{len(clientes)} clientes, {len(vazias)} pastas")

    print("contas...", end=" ", flush=True)
    linhas = []
    for c in montar_contas(d):
        empresa = c.pop("_empresa")
        c["empresa_id"] = ids[_norm(empresa)]
        linhas.append(c)
    contas = banco.inserir("conta", linhas)
    print(f"{len(contas)}")

    print("entidades...", end=" ", flush=True)
    entidades = banco.inserir("entidade", [{
        "nome_exibicao": l["nome_exibicao"].strip(),
        "nome_oficial": (l.get("nome_oficial") or "").strip(),
        "conta": (l.get("conta") or "").strip() or None,
        "nome_descricao": (l.get("nome_descricao") or "").strip() or None,
    } for l in d["entidades"]])
    ids_ent = {_norm(e["nome_exibicao"]): e["id"] for e in entidades}
    print(f"{len(entidades)}")

    print("subcontas...", end=" ", flush=True)
    nomes_sub = [s for s in d["subcontas"] if not s.startswith("_")]
    subs = banco.inserir("subconta", [{"nome": s} for s in nomes_sub])
    ids_sub = {s["nome"]: s["id"] for s in subs}
    obras, invs = [], []
    for s in nomes_sub:
        corpo = d["subcontas"][s]
        obras += [{"subconta_id": ids_sub[s], "nome": o}
                  for o in corpo.get("obras", [])]
        invs += [{"subconta_id": ids_sub[s], "nome": i}
                 for i in corpo.get("investidores", [])]
    banco.inserir("subconta_obra", obras)
    banco.inserir("subconta_investidor", invs)
    print(f"{len(subs)} subcontas, {len(obras)} obras, {len(invs)} investidores")

    print("regras de fornecedor...", end=" ", flush=True)
    regras = montar_regras(d)
    banco.inserir("regra_fornecedor", regras)
    print(f"{len(regras)}")

    print("regras de boleto...", end=" ", flush=True)
    boletos = [{
        "remetente": r.get("remetente", ""),
        "assunto_contem": r.get("assunto_contem", "") or "",
        "fornecedor_erp": r.get("fornecedor_erp", ""),
        "descricao_contem": r.get("descricao_contem", "") or "",
        "valor_varia": bool(r.get("valor_varia")),
        "janela_dias": int(r.get("janela_dias") or 0),
        "automatico": bool(r.get("automatico")),
        "confirmado_em": r.get("confirmado_em") or None,
        "nota": r.get("nota", "") or "",
        # Por que a regra nao anexa sozinha. E o campo mais caro de
        # reconstruir: sao paragrafos escritos depois de investigar casos.
        "ambiguo": r.get("ambiguo", "") or "",
    } for r in (d["boletos"] or {}).get("regras", [])]
    banco.inserir("regra_boleto", boletos)
    print(f"{len(boletos)}")


# ------------------------------------------------------------------ conferir

def conferir(banco: Banco, d: dict) -> list[str]:
    """Rele do banco e compara com o disco. "Subiu" nao e "esta certo la"."""
    erros = []

    def comparar(o_que, no_disco, no_banco):
        if no_disco != no_banco:
            erros.append(f"{o_que}: disco tem {no_disco}, banco tem {no_banco}")

    comparar("empresas", len(d["sicoob"]["empresas"]), len(banco.ler("empresa")))
    comparar("contas", len(montar_contas(d)), len(banco.ler("conta")))
    comparar("entidades", len(d["entidades"]), len(banco.ler("entidade")))
    comparar("regras de fornecedor", len(montar_regras(d)),
             len(banco.ler("regra_fornecedor")))
    comparar("regras de boleto", len((d["boletos"] or {}).get("regras", [])),
             len(banco.ler("regra_boleto")))

    # Contagem igual nao prova conteudo igual: confere campo a campo o que
    # decide onde o arquivo do mes vai parar.
    no_banco = {(_digitos(c["numero"]) or _norm(c["nome_erp"])): c
                for c in banco.ler("conta")}
    for c in montar_contas(d):
        chave = _digitos(c["numero"]) or _norm(c["nome_erp"])
        b = no_banco.get(chave)
        if not b:
            erros.append(f"conta {chave[-6:]} nao chegou ao banco")
            continue
        for campo in ("pasta", "banco", "banco_codigo", "sufixo", "agencia"):
            if (c[campo] or "") != (b[campo] or ""):
                erros.append(f"conta {chave[-6:]} campo {campo}: "
                             f"disco {c[campo]!r} != banco {b[campo]!r}")
    return erros


# ---------------------------------------------------------------------- main

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--conferir", action="store_true", help="so le e critica")
    p.add_argument("--subir", action="store_true", help="escreve no banco")
    p.add_argument("--limpar", action="store_true", help="apaga tudo do banco")
    p.add_argument("--email", help="quem entra no banco (login do app)")
    p.add_argument("--senha-de", help="arquivo com a senha, em vez de digitar")
    args = p.parse_args()
    if not (args.conferir or args.subir or args.limpar):
        p.print_help()
        return 2

    print(f"lendo de: {PASTA}\n")
    d = ler_tudo()

    problemas = criticar(d)
    if problemas:
        print("NAO DA PARA MIGRAR ainda:\n")
        for x in problemas:
            print(f"  - {x}")
        print("\nCorrija nos arquivos e rode de novo.")
        return 1
    print("critica: nenhum impedimento\n")

    if args.conferir and not (args.subir or args.limpar):
        contas = montar_contas(d)
        unidas = sum(1 for c in contas if c["numero"] and c["nome_erp"])
        print(f"o que subiria:")
        print(f"  {len(d['sicoob']['empresas'])} empresas")
        print(f"  {len(contas)} contas ({unidas} descritas hoje nos DOIS "
              f"arquivos, e que viram uma linha so)")
        print(f"  {len(d['entidades'])} entidades")
        print(f"  {len(montar_regras(d))} regras de fornecedor")
        print(f"  {len((d['boletos'] or {}).get('regras', []))} regras de boleto")
        return 0

    if not args.email:
        print("escrever no banco exige --email (o mesmo login do app).")
        return 2
    if args.senha_de:
        # Arquivo com "senha..: XXXX" numa das linhas, ou so a senha crua.
        texto = Path(args.senha_de).read_text(encoding="utf-8")
        senha = next((l.split(":", 1)[1].strip() for l in texto.splitlines()
                      if l.lower().startswith("senha")), texto.strip())
    else:
        import getpass
        senha = getpass.getpass(f"senha de {args.email}: ")

    banco = Banco(args.email, senha)

    if args.limpar:
        print("apagando...", end=" ", flush=True)
        for t in TABELAS:
            banco.apagar_tudo(t)
        print("pronto")
        if not args.subir:
            return 0

    subir(banco, d)
    print("\nconferindo o que chegou la...")
    erros = conferir(banco, d)
    if erros:
        print(f"\n{len(erros)} DIVERGENCIA(S):")
        for e in erros[:20]:
            print(f"  - {e}")
        print("\nO banco NAO esta igual ao disco. Os arquivos continuam "
              "mandando; rode --limpar --subir depois de entender.")
        return 1
    print("tudo confere: o banco tem o mesmo que o disco.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
