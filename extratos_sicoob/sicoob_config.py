# -*- coding: utf-8 -*-
"""
Ajustes do módulo de extratos do Sicoob.

Aqui só entra o que é genérico. O mapa das contas e a árvore de empresas são
dado da empresa (número de conta e razão social) e o repositório é público,
então moram em `contas_sicoob.json`, fora do git — mesma decisão já tomada
para `pix_reembolso.json`.

Os nomes dos módulos deste pacote começam com `sicoob_` de propósito: o app
põe todas as pastas de aba no mesmo sys.path, então nome de módulo é global.
Um `config.py` aqui sequestraria o `import config` do Anexar.
"""
import sys
from pathlib import Path

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

# Empacotado, é a pasta do .exe, para o JSON e o perfil do Chrome persistirem
# entre execuções. Sai de `util.pasta_base()` e não de um cálculo próprio:
# rodando como SCRIPT, o cálculo próprio apontava para `extratos_sicoob/`
# enquanto o `nuvem/cache.py` regrava o mapa na raiz.
_AQUI = util.pasta_base()

# Mapa das contas e da árvore de pastas (fora do repositório).
ARQUIVO_CONTAS = _AQUI / "contas_sicoob.json"

# Perfil do Chrome do Sicoob, separado do perfil do Mais Controle: são sites e
# logins diferentes, e o Playwright síncrono não divide thread entre eles.
PASTA_PERFIL_CHROME = _AQUI / ".chrome_profile_sicoob"

# Usada quando o JSON não traz "raiz".
RAIZ_PADRAO = Path("C:/Arquivos Morais/EXTRATOS")

#: A tabela de pasta mora em `util.MESES_PASTA`: as três cópias que
#: existiam aqui produzem NOME DE PASTA no disco, e uma divergir entre
#: elas parte o mês ao meio. O nome local continua porque é por ele que
#: o resto do módulo chama.
MESES = util.MESES_PASTA

# Internet banking.
URL_LOGIN = "https://ib.sicoob.com.br/sicoobnet/ib/#/login"
URL_SELECAO_CONTAS = "https://ib.sicoob.com.br/sicoobnet/ib/#/selecao-contas"
URL_EXTRATO = "https://ib.sicoob.com.br/sicoobnet/ib/#/home-extrato"

# Rótulos exatos da tela de extrato (o painel de exportação oferece oito
# formatos; estes são os dois que interessam).
FORMATO_OFX = "OFX (Money 2000 em diante)"
# O PDF sai do HTML, não do formato "PDF" do painel: aquele botão chama
# window.print() e abre o preview do Chrome, que é modal e trava o navegador
# (ver sicoob_client.exportar_pdf).
FORMATO_HTML = "HTML"
ORDENACAO = "Mais antigos"

# O OFX do Sicoob vem em Windows-1252, não UTF-8.
CODIFICACAO_OFX = "cp1252"


def nome_do_mes(mes: int) -> str:
    """1 -> 'JANEIRO'."""
    return MESES[mes - 1]


def nome_arquivo(ano: int, mes: int, sufixo: str = "") -> str:
    """Nome dos arquivos, sem extensão: 2026, 7 -> '202607 SICOOB'.

    O `sufixo` desempata as contas que dividem a mesma pasta: sem ele as duas
    gravavam "202607 SICOOB.ofx" no mesmo lugar e a segunda passava por cima
    da primeira sem uma palavra — a pasta é escolhida pela conta, cada OFX foi
    conferido contra a SUA conta e o `shutil.move` sobrescreve calado.

    O formato é o MESMO de `relatorios/contas_mc.nome_arquivo` (um espaço e o
    sufixo no fim) de propósito: o PDF do ERP e o OFX do banco são da mesma
    conta, caem na mesma pasta e têm de terminar igual para se reconhecerem.
    """
    base = f"{ano}{mes:02d} SICOOB"
    if sufixo:
        base += f" {sufixo}"
    return base


def nome_pasta_empresa(ano: int, mes: int, empresa: str) -> str:
    """'JULHO 2026 - BURITIS'."""
    return f"{nome_do_mes(mes)} {ano} - {empresa}"


def mes_anterior(ano: int, mes: int) -> tuple[int, int]:
    """O mês de referência padrão: o anterior ao de hoje."""
    return (ano - 1, 12) if mes == 1 else (ano, mes - 1)
