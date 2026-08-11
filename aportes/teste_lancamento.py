# -*- coding: utf-8 -*-
"""
Teste de fogo: cria UM pagamento e UM recebimento de R$ 1,00 no Mais Controle.

ATENÇÃO: este script ESCREVE no sistema. Os dois lançamentos saem com uma
descrição gritante para serem achados e apagados na tela depois.

É o menor teste que prova o caminho inteiro — autenticação, catálogos,
resolução de nomes em UUID e criação. Em especial, prova a parte que só
existe como dedução até aqui: onde vem o id da parcela na resposta da venda,
e se a baixa já vem feita pelo próprio lançamento.

Uso:
    python aportes/teste_lancamento.py

Tudo que o ERP responder vai para `teste_lancamento.json`, gravado ANTES de
qualquer impressão — perder a resposta custa uma rodada inteira de login.
"""
from __future__ import annotations

import datetime
import json
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mc_catalogos import Catalogos                    # noqa: E402
from mc_lancamentos import (criar_pagamento,          # noqa: E402
                            criar_recebimento, ErroLancamento)

BASE_URL = "https://acessar.maiscontroleerp.com.br"
PERFIL = Path(__file__).resolve().parent / ".chrome_profile_teste"
SAIDA = Path(__file__).resolve().parent / "teste_lancamento.json"
TELA_PAGAMENTOS = f"{BASE_URL}/#/payable-installments"

from erp_sessao import ouvinte                # noqa: E402

# --------------------------------------------------------------- o que criar
# Valor de R$ 1,00 e descrição em maiúsculas: se algo escapar da limpeza, fica
# evidente num relatório em vez de se disfarçar de movimento real.
VALOR = 1.00
DESCRICAO = "TESTE INTEGRACAO APAGAR"
DATA = datetime.date.today()

# Nomes de contas e empresas NÃO ficam no código: este repositório é público.
# Crie o arquivo abaixo (já está no .gitignore) com os nomes exatamente como
# estão cadastrados no seu Mais Controle.
ARQUIVO_ALVO = Path(__file__).resolve().parent / "teste_lancamento.local.json"

MODELO = {
    "conta_pagadora": "<conta que paga, como está no ERP>",
    "conta_recebedora": "<conta que recebe>",
    "favorecido": "<quem recebe, na planilha de Pagamentos>",
    "cliente": "<quem paga, na planilha de Recebimentos>",
    "categoria": "APORTE CAPITAL",
    "natureza": "Aporte de Capital",
    "forma": "Pix",
    "obra": "<centro de custo / obra>",
}


def carregar_alvo() -> dict:
    if not ARQUIVO_ALVO.exists():
        print(f"Falta o arquivo {ARQUIVO_ALVO.name}, com o que lançar.")
        print("Crie ao lado deste script, no formato:")
        print(json.dumps(MODELO, indent=2, ensure_ascii=False))
        raise SystemExit(1)
    dados = json.loads(ARQUIVO_ALVO.read_text(encoding="utf-8"))
    faltando = [c for c in MODELO if not dados.get(c)]
    if faltando:
        raise SystemExit(f"faltam campos em {ARQUIVO_ALVO.name}: {faltando}")
    return dados


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    alvo = carregar_alvo()
    CONTA_PAGADORA = alvo["conta_pagadora"]
    CONTA_RECEBEDORA = alvo["conta_recebedora"]
    FAVORECIDO = alvo["favorecido"]
    CLIENTE = alvo["cliente"]
    CATEGORIA = alvo["categoria"]
    NATUREZA = alvo["natureza"]
    FORMA = alvo["forma"]
    OBRA = alvo["obra"]

    print("=" * 70)
    print("  TESTE QUE ESCREVE NO MAIS CONTROLE")
    print(f"  {VALOR:.2f} — \"{DESCRICAO}\" — {DATA:%d/%m/%Y}")
    print(f"  Pagamento:   {CONTA_PAGADORA} -> {FAVORECIDO}")
    print(f"  Recebimento: {CLIENTE} -> {CONTA_RECEBEDORA}")
    print("  APAGUE OS DOIS NA TELA DEPOIS.")
    print("=" * 70)
    print()

    capturados: dict = {}
    registro: dict = {"quando": datetime.datetime.now().isoformat()}

    def gravar():
        try:
            SAIDA.write_text(json.dumps(registro, indent=2, ensure_ascii=False,
                                        default=str), encoding="utf-8")
        except OSError:
            pass

    ao_requisitar = ouvinte(capturados)

    shutil.rmtree(PERFIL, ignore_errors=True)
    PERFIL.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        contexto = p.chromium.launch_persistent_context(
            user_data_dir=str(PERFIL), channel="chrome", headless=False,
            no_viewport=True, locale="pt-BR", timezone_id="America/Sao_Paulo",
            args=["--no-first-run", "--no-default-browser-check",
                  "--start-maximized"])
        contexto.set_default_timeout(60000)
        contexto.on("request", ao_requisitar)
        pagina = contexto.pages[0] if contexto.pages else contexto.new_page()
        pagina.goto(f"{BASE_URL}/#/login", wait_until="domcontentloaded")

        print(">>> 1. Faça login.")
        print(">>> 2. Abra Financeiro > Pagamentos > NOVO LANÇAMENTO, deixe")
        print(">>>    carregar e feche sem salvar.")
        print(">>> 3. A partir daí eu crio os dois lançamentos.\n")

        necessarios = {"prod-erp-api.maiscontroleerp.com.br"}
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
            print("[!] não capturei a autenticação dos cadastros.")
            contexto.close()
            return 1

        # user-id é o responsável pelo lançamento. Nem todo host manda esse
        # cabeçalho — o prod-erp-api não manda, o legacy-api manda — então
        # procuramos em TODOS os conjuntos capturados.
        id_usuario = None
        for cabecalhos in capturados.values():
            for nome, valor in cabecalhos.items():
                if nome.lower() == "user-id" and valor:
                    id_usuario = valor
                    break
            if id_usuario:
                break
        if not id_usuario:
            print("[!] não achei o user-id em nenhum host.")
            print(f"    hosts capturados: {', '.join(sorted(capturados))}")
            for host, c in capturados.items():
                print(f"      {host}: {sorted(c)}")
            contexto.close()
            return 1
        registro["id_usuario"] = id_usuario

        print("Carregando cadastros:")
        catalogos = Catalogos(pagina, capturados)
        try:
            catalogos.carregar()
            catalogos.carregar_obras()
        except RuntimeError as e:
            print(f"[!] {e}")
            contexto.close()
            return 1

        if not catalogos.obra(OBRA):
            print(f"[!] não achei a obra \"{OBRA}\". Obras lidas: "
                  f"{len(getattr(catalogos, 'obras', {}))}")
            for motivo in getattr(catalogos, "erros_obras", []):
                print(f"    motivo: {motivo}")
            registro["obras_lidas"] = [o.get("name") for o in
                                       getattr(catalogos, "obras", {}).values()]
            registro["erros_obras"] = getattr(catalogos, "erros_obras", [])
            gravar()
            contexto.close()
            return 1

        print("\n--- 1/2 PAGAMENTO ---")
        try:
            r_pag = criar_pagamento(
                catalogos, data=DATA, valor=VALOR, descricao=DESCRICAO,
                conta_pagadora=CONTA_PAGADORA, favorecido=FAVORECIDO,
                categoria=CATEGORIA, forma=FORMA, obra=OBRA,
                id_usuario=id_usuario)
            registro["pagamento"] = r_pag.__dict__
            print(f"  ok={r_pag.ok}  id={r_pag.id_criado}  erro={r_pag.erro}")
            if r_pag.detalhes:
                print(f"  detalhes: {json.dumps(r_pag.detalhes, ensure_ascii=False)[:400]}")
        except ErroLancamento as e:
            registro["pagamento"] = {"ok": False, "erro": str(e)}
            print(f"  [!] {e}")
        gravar()

        print("\n--- 2/2 RECEBIMENTO ---")
        try:
            r_rec = criar_recebimento(
                catalogos, data=DATA, valor=VALOR, descricao=DESCRICAO,
                conta_recebedora=CONTA_RECEBEDORA, cliente=CLIENTE,
                natureza=NATUREZA, forma=FORMA, obra=OBRA,
                id_usuario=id_usuario)
            registro["recebimento"] = r_rec.__dict__
            print(f"  ok={r_rec.ok}  id={r_rec.id_criado}  erro={r_rec.erro}")
            if r_rec.detalhes:
                print(f"  detalhes: {json.dumps(r_rec.detalhes, ensure_ascii=False)[:400]}")
        except ErroLancamento as e:
            registro["recebimento"] = {"ok": False, "erro": str(e)}
            print(f"  [!] {e}")
        gravar()

        contexto.close()

    print(f"\nTudo gravado em {SAIDA}")
    print("\n>>> AGORA APAGUE os dois lançamentos \"" + DESCRICAO + "\" no ERP.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
