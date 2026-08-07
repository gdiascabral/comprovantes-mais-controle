# -*- coding: utf-8 -*-
"""
Confere o cadastro de contas (contas.csv) contra o Mais Controle.

NÃO cria, não altera e não apaga nada — só lê.

Serve para responder, antes de qualquer lançamento: "todo nome que eu uso
existe no ERP, escrito exatamente assim?". Era essa pergunta sem resposta que
fazia a importação de planilha travar em "Validando Arquivo" sem dizer qual
linha estava errada.

Uso:
    python aportes/conferir_contas.py "C:/caminho/para/contas.csv"

Sem argumento, procura o contas.csv ao lado deste arquivo.
"""
from __future__ import annotations

import csv
import os
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mc_catalogos import Catalogos          # noqa: E402

BASE_URL = "https://acessar.maiscontroleerp.com.br"
PERFIL = Path(__file__).resolve().parent / ".chrome_profile_conferencia"

# Uma tela interna qualquer serve para o app disparar chamadas autenticadas —
# é delas que os cabeçalhos são copiados.
TELA_PAGAMENTOS = f"{BASE_URL}/#/payable-installments"

CABECALHOS = {"authorization", "company-id", "user-id", "organization-unit-id"}

# Hosts do ERP que importam. api-data-event e faro são TELEMETRIA e carregam
# token próprio — misturá-los com os demais faz o prod-erp-api devolver 401.
HOSTS_UTEIS = ("prod-erp-api.maiscontroleerp.com.br",
               "legacy-api.maiscontroleerp.com.br",
               "acessar.maiscontroleerp.com.br")

CANDIDATOS_CSV = [
    Path(__file__).resolve().parent / "contas.csv",
]


def achar_csv(argumento: str | None) -> Path:
    if argumento:
        caminho = Path(argumento)
        if not caminho.exists():
            raise SystemExit(f"não achei o arquivo: {caminho}")
        return caminho
    for candidato in CANDIDATOS_CSV:
        if candidato.exists():
            return candidato
    raise SystemExit(
        "não achei o contas.csv. Passe o caminho como argumento:\n"
        '    python aportes/conferir_contas.py "C:/.../contas.csv"')


def ler_entidades(caminho: Path) -> dict:
    entidades = {}
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        for linha in csv.DictReader(f, delimiter=";"):
            nome = (linha.get("nome_exibicao") or "").strip()
            if nome:
                entidades[nome] = {
                    "nome_oficial": (linha.get("nome_oficial") or "").strip(),
                    "conta": (linha.get("conta") or "").strip(),
                }
    return entidades


def main() -> int:
    # O console do Windows é cp1252 e derruba o programa em qualquer caractere
    # fora da tabela. Já aconteceu: o resultado da conferência inteira foi
    # perdido por causa de um "▸" na última linha.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    caminho_csv = achar_csv(sys.argv[1] if len(sys.argv) > 1 else None)
    entidades = ler_entidades(caminho_csv)
    print(f"Cadastro: {caminho_csv}  ({len(entidades)} contas)\n")

    capturados: dict = {}

    def ao_requisitar(req):
        from urllib.parse import urlsplit
        host = urlsplit(req.url).netloc
        if host not in HOSTS_UTEIS:
            return
        cabecalhos = {k: v for k, v in req.headers.items() if k.lower() in CABECALHOS}
        if "authorization" in {k.lower() for k in cabecalhos}:
            capturados[host] = cabecalhos

    # Perfil próprio e zerado: perfil reaproveitado depois de um encerramento
    # forçado faz o Chrome delegar a sessão e sair. Nunca apontar para o perfil
    # do app de Anexar — lá mora a senha salva do usuário.
    shutil.rmtree(PERFIL, ignore_errors=True)
    PERFIL.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        contexto = p.chromium.launch_persistent_context(
            user_data_dir=str(PERFIL),
            channel="chrome",
            headless=False,          # o WAF do ERP recusa navegador sem janela
            no_viewport=True,
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            args=["--no-first-run", "--no-default-browser-check",
                  "--start-maximized"],
        )
        contexto.set_default_timeout(60000)
        contexto.on("request", ao_requisitar)
        pagina = contexto.pages[0] if contexto.pages else contexto.new_page()

        pagina.goto(f"{BASE_URL}/#/login", wait_until="domcontentloaded")
        print(">>> 1. Faça login na janela do Chrome.")
        print(">>> 2. Abra Financeiro > Pagamentos > NOVO LANÇAMENTO e deixe a")
        print(">>>    tela carregar. NÃO precisa preencher nem salvar — é só")
        print(">>>    para o ERP chamar o serviço de cadastros uma vez.")
        print(">>> 3. Pode fechar o formulário. Eu sigo sozinho.\n")

        # Precisa dos DOIS: a lista de pagamentos autentica no legacy-api, mas
        # os cadastros (contas, participantes) moram no prod-erp-api, que só é
        # chamado quando o formulário de lançamento abre.
        necessarios = {"prod-erp-api.maiscontroleerp.com.br"}
        # Sem networkidle: o app mantém conexão aberta e a rede nunca fica ociosa.
        limite = time.monotonic() + 300
        ja_navegou = False
        while time.monotonic() < limite and not necessarios <= capturados.keys():
            try:
                if not pagina.locator("#userpassword").first.is_visible(timeout=1000):
                    if not ja_navegou:
                        pagina.goto(TELA_PAGAMENTOS, wait_until="domcontentloaded")
                        ja_navegou = True
                        pagina.wait_for_timeout(4000)
            except Exception:
                pass
            pagina.wait_for_timeout(1000)

        if not necessarios <= capturados.keys():
            print("[!] não capturei a autenticação do serviço de cadastros.")
            print("    A tela de Novo Lançamento chegou a ser aberta?")
            contexto.close()
            return 1
        print(f"Autenticado em: {', '.join(sorted(capturados))}")

        print("Carregando os cadastros do ERP:")
        catalogos = Catalogos(pagina, capturados)
        try:
            catalogos.carregar()
        except RuntimeError as e:
            print(f"[!] {e}")
            contexto.close()
            return 1

        resultado = catalogos.conferir(entidades)
        contexto.close()

    # Grava ANTES de imprimir: a sessão do ERP não sobrevive ao fechamento do
    # navegador, então perder o resultado custa uma rodada inteira de login.
    saida = Path(__file__).resolve().parent / "conferencia.json"
    try:
        import json
        saida.write_text(json.dumps(resultado, indent=2, ensure_ascii=False),
                         encoding="utf-8")
        print(f"\nResultado gravado em {saida}")
    except OSError as e:
        print(f"\n[!] não consegui gravar o resultado: {e}")

    print()
    print("=" * 70)
    print(f"OK: {len(resultado['ok'])} de {len(entidades)} contas resolvidas no ERP")
    if resultado["faltando"]:
        print(f"\nNAO ENCONTRADAS ({len(resultado['faltando'])}):\n")
        for item in resultado["faltando"]:
            print(f"  - {item['nome']}")
            for p in item["problemas"]:
                print(f"      {p['o_que']}: \"{p['procurado']}\"")
                if p["parecidos"]:
                    for parecido in p["parecidos"]:
                        print(f"         parecido no ERP: \"{parecido}\"")
                else:
                    print("         (nada parecido no ERP)")
        print("\nEnquanto isso não estiver resolvido, o lançamento dessas contas")
        print("falharia — é exatamente o que travava a importação da planilha.")
    else:
        print("\nTodas as contas do cadastro existem no Mais Controle.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
