# -*- coding: utf-8 -*-
"""
Comprovantes — Mais Controle (app unificado)

Janela em três faixas, no feitio de painel de controle:

  a barra azul do topo   logotipo, busca, estado do navegador, quem entrou;
  o menu branco (232 px) as dez telas, em quatro seções;
  o painel cinza         a tela aberta, feita de cartões brancos.

A primeira tela é o Início: quatro números do dia, a situação de cada rotina
e o que aconteceu por último. As outras nove continuam sendo as mesmas, com
o mesmo fluxo — o que mudou foi só a camada visual (ver `widgets.py`, que é
onde moram TODAS as cores e fontes do app).

Tema claro/escuro com opção "Automático" (segue o Windows), salvo em
"preferencias.json" ao lado do executável.
"""
import json
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

import util
import widgets

#: A medida de layout que segue a fonte. `px(14)` são "os 14 px de quem
#: desenhou esta tela a 100%", ditos na escala de hoje — a 150% saem 21, e
#: a 100% saem os mesmos 14. Ver o bloco do `px` no `widgets.py`.
px = widgets.px
from nuvem import (auditoria, cadastro, login_dialogo, rest, sessao,
                   usuarios)
from nuvem.usuarios_frame import UsuariosFrame
from inicio.inicio_frame import InicioFrame
from separar_renomear.separar_renomear import SepararFrame
from anexar.anexar_comprovantes import AnexarFrame
from anexar.conferencia import ConferenciaFrame
from aportes.aportes_frame import AportesFrame
from relatorios.relatorio_frame import RelatorioFrame
from pagamentos_dia.pagamentos_frame import PagamentosDiaFrame
from extratos_sicoob.extratos_frame import ExtratosSicoobFrame
from conciliacao.frame import ConciliacaoFrame
from contratos.frame import ContratosFrame
from acessorias.frame import AcessoriasFrame
from baixar_comprovantes.comprovantes_frame import ComprovantesFrame


def _nitidez():
    """Deixa o texto nítido em telas de alta resolução (Windows)."""
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def _versao_app():
    """Versão do código em uso (versao.txt gravado pela build)."""
    candidatos = [Path(__file__).resolve().parent]
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidatos.append(Path(base))
        candidatos.append(Path(base) / "codigo_embutido")
    for c in candidatos:
        try:
            return (c / "versao.txt").read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return None


def _versao_curta(versao: str | None) -> str:
    """"v2.0.108" -> "v2.0". O que se diz em voz alta.

    O número de build (o `<run_number>` da esteira) muda a cada push e não
    significa nada para quem usa: entre a v2.0.108 e a v2.0.109 pode não haver
    diferença nenhuma na tela. Ele continua existindo e continua acessível — na
    dica do próprio rótulo —, porque é ele que diz qual código está rodando
    quando alguém precisa comparar com uma release.

    Lixo entra e sai inteiro: versão que não tem a forma esperada é melhor
    aparecer estranha do que aparecer cortada no lugar errado.
    """
    if not versao:
        return ""
    partes = versao.strip().lstrip("vV").split(".")
    if len(partes) < 2 or not all(p.isdigit() for p in partes[:2]):
        return versao.strip()
    return f"v{partes[0]}.{partes[1]}"


def _pasta_dados() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def _token_ou_vazio(pasta) -> str:
    """O token da sessão, ou "" se não der para consegui-lo agora.

    Vazio faz a sincronização falhar com um recado, em vez de estourar: nesta
    altura o login já aconteceu, e o único jeito de chegar aqui sem token é a
    rede ter caído entre uma coisa e outra. Não é motivo para não abrir."""
    try:
        return sessao.token(pasta)
    except rest.ErroDaNuvem:
        return ""


def _carregar_prefs() -> dict:
    try:
        return json.loads((_pasta_dados() / "preferencias.json")
                          .read_text(encoding="utf-8"))
    except Exception:
        return {}


def _salvar_prefs(prefs: dict):
    try:
        (_pasta_dados() / "preferencias.json").write_text(
            json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _tema_do_sistema() -> str:
    """Lê a preferência de tema do Windows (claro/escuro)."""
    try:
        import winreg
        chave = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        claro, _ = winreg.QueryValueEx(chave, "AppsUseLightTheme")
        return "light" if claro else "dark"
    except Exception:
        return "light"


def main():
    _nitidez()
    # Liga o diagnóstico do `cnab240` ao `diagnostico.log`. O pacote é stdlib
    # pura (não importa `util`; `test_cnab240_pacote.py` cobra) e emite no
    # logger do próprio nome; esta linha pendura o handler no logger pai, e
    # tudo de lá sobe por propagação. NUNCA pendurar `NullHandler` no logger
    # `cnab240`: o `if not logger.handlers` do `util.log()` ficaria mudo.
    util.log("cnab240")
    _v = _versao_app()
    prefs = _carregar_prefs()
    escolha_tema = prefs.get("tema", "auto")

    root = tk.Tk()
    _v_curta = _versao_curta(_v)
    root.title("Comprovantes — Mais Controle"
               + (f"  {_v_curta}" if _v_curta else ""))
    try:                                 # ícone da janela (se disponível)
        for _c in (Path(__file__).resolve().parent / "icone.ico",
                   Path(getattr(sys, "_MEIPASS", ".")) / "icone.ico"):
            if _c.exists():
                root.iconbitmap(str(_c))
                break
    except Exception:
        pass
    try:
        root.state("zoomed")            # janela ocupando a tela (Windows)
    except tk.TclError:
        root.geometry(f"{widgets.px(1150)}x{widgets.px(740)}")
    # A janela passa a ter um mínimo, e ele é PROPORCIONAL. Sem mínimo dava
    # para arrastar a borda até a moldura sumir; com um mínimo FIXO, quem
    # usa 150% teria o mesmo problema num número maior — ali o menu, a
    # barra e os cartões pedem 1,5× a largura, e 900 px já escondem a
    # coluna da direita do Início inteira.
    try:
        root.minsize(widgets.px(900), widgets.px(600))
    except tk.TclError:
        pass

    try:
        import sv_ttk                   # tema moderno (visual Windows 11)
    except Exception:
        sv_ttk = None

    def tema_efetivo(escolha: str) -> str:
        if escolha == "claro":
            return "light"
        if escolha == "escuro":
            return "dark"
        return _tema_do_sistema()       # automático

    if sv_ttk:
        sv_ttk.set_theme(tema_efetivo(escolha_tema))
    # Antes de construir qualquer aba: os estilos nomeados precisam existir na
    # hora em que os widgets pedem por eles, senão a primeira tela nasce com as
    # legendas na cor padrão e só acerta na primeira troca de tema.
    widgets.aplicar_estilos(tema_efetivo(escolha_tema) == "dark")
    # Antes da janela aparecer: a barra pintada depois do primeiro desenho
    # aparece clara por um instante e escurece na frente de quem olha.
    widgets.barra_de_titulo(root, tema_efetivo(escolha_tema) == "dark")

    # ---------------- quem está entrando
    # Antes de montar as abas: cada frame abre executor e estado próprios, e
    # construir tudo para depois recusar deixaria a janela piscando atrás do
    # diálogo. A principal fica escondida enquanto se pergunta; o tema já foi
    # aplicado acima, então o diálogo nasce na cor certa.
    #
    # Substituiu a senha de ativação, que era uma só para todo mundo e valia
    # para sempre naquela máquina.
    entrou, _recado = login_dialogo.entrar_sozinho(_pasta_dados())
    if not entrou:
        root.withdraw()
        if not login_dialogo.pedir_login(root, _pasta_dados()):
            root.destroy()
            return                       # sem entrar, o app não abre
        root.deiconify()
        try:
            root.state("zoomed")         # o withdraw desfaz a maximização
        except tk.TclError:
            pass

    # ---------------- a conta já foi liberada?
    # Entrar e PODER TRABALHAR são coisas diferentes desde a fase 3: qualquer
    # pessoa cria conta pela tela de login, e quem decide se ela trabalha aqui
    # é um administrador. Conta nova nasce `pendente`.
    #
    # A trava de verdade não é esta: é a RLS, que nega todo dado a quem não
    # tem perfil ativo. Isto aqui existe para a pessoa entender por que o app
    # está vazio, em vez de achar que ele quebrou.
    #
    # `conhecido` no teste, e não só `ativo`: situação vazia quer dizer "não
    # deu para perguntar ao servidor" — quem está sem internet com uma sessão
    # válida continua abrindo o app, como sempre abriu.
    _conta = sessao.quem(_pasta_dados())
    if _conta.conhecido and not _conta.ativo:
        root.withdraw()
        if not login_dialogo.avisar_que_espera(root, _pasta_dados()):
            root.destroy()
            return                       # ainda esperando: o app não abre
        root.deiconify()
        try:
            root.state("zoomed")
        except tk.TclError:
            pass

    # Relido DEPOIS da tela de espera: quem foi liberado ali mesmo, pelo botão
    # "Conferir de novo", chega aqui com o papel novo — e é o papel que decide
    # o menu daqui para baixo.
    _eu = sessao.quem(_pasta_dados())

    # A primeira linha da auditoria do dia. Não é zelo: sem ela, "quem estava
    # no app na hora em que isto foi gerado?" não tem resposta — e é a
    # pergunta que vem antes de todas as outras quando algo sai errado numa
    # remessa. Sobe numa thread solta e não pode atrasar a abertura.
    auditoria.registrar("Entrou no app",
                        _eu.papel or "papel ainda não conhecido")

    # ---------------- cadastro compartilhado
    # Aqui, e não dentro de cada aba: existe UM ponto onde a rede pode faltar,
    # ele acontece antes de qualquer trabalho começar, e o pior caso é rodar
    # com o cadastro de ontem. Espalhado pelas abas, viraria nove caminhos de
    # erro novos, cada um no meio de um lote.
    #
    # Falhar aqui NUNCA impede o app de abrir: os arquivos locais são a última
    # cópia, e é justamente quando o banco está fora do ar que eles importam.
    #
    # O `try` é o que torna a frase acima verdadeira. `sincronizar` engole a
    # falta de rede, mas deixa subir de propósito o que é assunto de quem cuida
    # do login (`rest.PrecisaEntrar`, do 401/403) — e aqui não há quem cuide:
    # esta linha roda ANTES de existir janela montada, e o exe é `--noconsole`,
    # então a exceção fechava o app sem tela, sem log e sem recado. Sessão
    # vencida entre o login e esta linha vira "cadastro offline", que é
    # exatamente o que ela é.
    #
    # Amplo de propósito: escrever o cache também pode falhar (disco cheio,
    # arquivo aberto no Excel, OneDrive segurando), e nenhuma dessas é razão
    # para o app não abrir.
    try:
        _sinc = cadastro.sincronizar(_token_ou_vazio(_pasta_dados()),
                                     _pasta_dados())
    except Exception as _e:
        _sinc = cadastro.Resultado(False, f"falha ao sincronizar: {_e}")

    # ---------------- a moldura: barra em cima, menu à esquerda, painel
    #
    # Três faixas, e cada uma responde a uma pergunta diferente:
    #
    #   a barra azul   onde estou, o que procuro, o app está livre?
    #   o menu branco  para onde vou;
    #   o painel       o que estou fazendo agora.
    #
    # Antes eram duas, e a coluna da esquerda acumulava navegação, tema,
    # versão, usuário e estado do navegador. O estado do navegador era o pior
    # deles: é a informação que se procura ANTES de clicar noutra aba, e
    # ficava no ponto mais baixo da tela, longe dos itens do menu.
    barra = widgets.BarraTopo(root)
    barra.pack(side="top", fill="x")
    corpo = ttk.Frame(root)
    corpo.pack(side="top", fill="both", expand=True)

    lateral = widgets.painel_menu(corpo, largura=232)
    lateral.pack(side="left", fill="y")
    conteudo = ttk.Frame(corpo, style="Fundo.TFrame")
    conteudo.pack(side="left", fill="both", expand=True)

    aba_ini = InicioFrame(conteudo)
    aba_sep = SepararFrame(conteudo)
    aba_anx = AnexarFrame(conteudo)
    aba_conf = ConferenciaFrame(conteudo, aba_anx)
    # Aportes divide o navegador e a thread do Anexar, como a Conferência:
    # o Playwright síncrono só aceita uma thread, e um segundo Chrome
    # significaria um segundo login.
    aba_apt = AportesFrame(conteudo, aba_anx)
    aba_rel = RelatorioFrame(conteudo, aba_anx)
    aba_pag = PagamentosDiaFrame(conteudo, aba_anx)
    # Extratos Sicoob NÃO recebe o aba_anx: é outro site e outro login, então
    # tem navegador e thread próprios (ver extratos_frame.py).
    aba_ext = ExtratosSicoobFrame(conteudo)
    # Conciliação volta a dividir navegador e thread do Anexar: é o mesmo ERP,
    # e ele só aceita uma sessão por usuário.
    aba_con = ConciliacaoFrame(conteudo, aba_anx)
    # Contratos usa o mesmo ERP: divide navegador e thread, como as outras.
    aba_ctr = ContratosFrame(conteudo, aba_anx)
    # Acessórias também NÃO recebe o aba_anx: é o portal do escritório
    # contábil, terceiro site e terceiro login (ver acessorias/portal.py).
    aba_acs = AcessoriasFrame(conteudo)
    # Baixar Comprovantes tem navegador PRÓPRIO, como os Extratos Sicoob: são
    # os sites dos bancos, com login e sessão que não têm nada a ver com o ERP.
    # O cadastro de contas é o mesmo `contas_sicoob.json` que os Extratos leem
    # — a tela não descobre isso sozinha, recebe de quem a monta.
    def _mapa_das_contas():
        from extratos_sicoob import sicoob_contas as _sc

        return _sc.carregar()

    aba_bxc = ComprovantesFrame(conteudo, _mapa_das_contas)
    quadros = {"ini": aba_ini, "sep": aba_sep, "anx": aba_anx,
               "conf": aba_conf, "apt": aba_apt, "rel": aba_rel,
               "pag": aba_pag, "ext": aba_ext, "con": aba_con,
               "ctr": aba_ctr, "acs": aba_acs, "bxc": aba_bxc}
    atual = {"nome": None}
    itens = {}

    # ---------------- o que este papel enxerga
    # As abas continuam todas CONSTRUÍDAS, inclusive as que não vão aparecer:
    # metade delas divide o navegador e a thread do Anexar (Conferência,
    # Aportes, Relatório, Remessa, Conciliação, Contratos), e deixar de criar
    # umas e não outras mexeria nessa fiação por um motivo que é só de menu.
    #
    # E esconder não é o que protege: quem nega o dado é a RLS, que julga o
    # token a cada chamada. O menu enxuto existe para o aprovador — que entra
    # para conferir e liberar a remessa do dia — não ter na frente nove
    # rotinas que ele não vai rodar, numa tela que mexe com pagamento.
    _permitidas = usuarios.abas_do_papel(_eu.papel, quadros.keys())

    def _pode(chave: str) -> bool:
        return chave in _permitidas

    def mostrar(nome: str):
        if atual["nome"] == nome:
            return
        for f in quadros.values():
            f.pack_forget()
        quadros[nome].pack(fill="both", expand=True)
        atual["nome"] = nome
        for n, it in itens.items():
            try:
                it.ativar(n == nome)
            except tk.TclError:
                pass
        # Uma aba dentro de um grupo fechado ficaria selecionada e invisível na
        # barra: abre o grupo para o destaque ter onde aparecer.
        for gnome, g in grupos.items():
            if nome in g["itens"] and not g["aberto"]:
                _alternar(gnome)
        # O Início conta o que as outras telas fizeram, e o que elas fizeram
        # muda enquanto ele está escondido. Recontar na hora de mostrar é
        # barato (lê um arquivo local) e evita um número velho na primeira
        # tela do app — que é justamente onde ele mais parece verdade.
        atualizar = getattr(quadros[nome], "ao_abrir", None)
        if atualizar is not None:
            try:
                atualizar()
            except Exception:                             # noqa: BLE001
                pass                     # tela de resumo não derruba o app
        # `after_idle`: a aba acabou de ser empacotada e ainda não tem
        # geometria, e é a geometria que decide qual campo é o de cima.
        root.after_idle(lambda: _focar_primeiro(quadros[nome]))

    def _focar_primeiro(quadro):
        try:
            widgets.focar_primeiro_campo(quadro)
        except tk.TclError:
            pass                         # aba fechando enquanto o idle rodava

    # Ícone e nome ficam guardados separados porque o lugar do ícone é também
    # onde entra a marca de "esta aba está trabalhando agora" (ver `_pulso`).
    nomes: dict[str, str] = {}

    def _item(pai, chave: str, icone: str, texto: str, recuo: int = 0):
        if not _pode(chave):
            return
        it = widgets.ItemMenu(pai, texto, icone=icone, recuo=recuo,
                              comando=lambda: mostrar(chave))
        it.pack(fill="x")
        itens[chave] = it
        nomes[chave] = texto

    if _pode("ini"):
        lateral.secao("Visão geral")
        _item(lateral.corpo, "ini", "▦", "Início")
    # O rótulo de seção sem nenhum item embaixo fica pior do que a seção
    # inteira ausente: parece que as abas sumiram, e não que elas não são
    # desta pessoa.
    if any(_pode(c) for c in ("bxc", "sep", "anx", "conf", "apt")):
        lateral.secao("Comprovantes")
    # Os rótulos encurtaram junto com a coluna: "Anexar Comprovantes" dentro
    # de um menu chamado COMPROVANTES repetia a palavra em duas alturas.
    # "Baixar" antes de "Separar" e "Anexar" porque é a ordem do dia: os
    # comprovantes chegam do banco, depois são separados, depois anexados.
    for _chave, _icone, _texto in (("bxc", "⬇", "Baixar Comprovantes"),
                                   ("sep", "✂", "Separar e Renomear"),
                                   ("anx", "📎", "Anexar"),
                                   ("conf", "✅", "Conferência"),
                                   ("apt", "💰", "Aportes")):
        _item(lateral.corpo, _chave, _icone, _texto)

    # ---- grupos que abrem e fecham
    # As rotinas de fechamento são muitas para uma lista plana, e cada uma se
    # usa num ritmo diferente: as diárias todo dia, as mensais uma vez por mês.
    # O grupo aberto/fechado fica em preferencias.json — quem só faz o diário
    # não reabre o mensal toda vez.
    grupos: dict[str, dict] = {}
    prefs_grupos = prefs.get("grupos") or {}

    def _alternar(nome: str, salvar: bool = True):
        g = grupos[nome]
        g["aberto"] = not g["aberto"]
        if g["aberto"]:
            g["corpo"].pack(fill="x", after=g["cabecalho"])
        else:
            g["corpo"].pack_forget()
        g["cabecalho"].configure(text=g["titulo"](g["aberto"]))
        if salvar:
            prefs.setdefault("grupos", {})[nome] = g["aberto"]
            _salvar_prefs(prefs)

    def _grupo(nome: str, rotulo: str, itens_do_grupo):
        itens_do_grupo = tuple(t for t in itens_do_grupo if _pode(t[0]))
        if not itens_do_grupo:
            return                       # grupo sem item nenhum não aparece
        titulo = lambda aberto: f"{'▾' if aberto else '▸'}  {rotulo}"  # noqa: E731
        # Continua sendo um Button — ele abre e fecha o grupo, e trocar por um
        # Label com bind de clique tiraria o item do Tab e do Espaço. O que
        # muda é o ESTILO: chapado e miúdo, para DIÁRIO e MENSAL parecerem os
        # rótulos de seção que estão logo acima deles, e não itens clicáveis
        # do mesmo nível das abas que eles agrupam.
        #
        # Até 02/09/2026 estes dois cabeçalhos eram as ÚNICAS paradas de Tab da
        # coluna: o `ItemMenu` não entrava no foco, então o teclado abria e
        # fechava os grupos sem alcançar uma só das doze telas dentro deles. A
        # regra escrita aqui valia para o cabeçalho e era desmentida logo
        # abaixo; agora o item também entra no Tab, e o Tab percorre a coluna
        # inteira na ordem em que ela é lida.
        cab = ttk.Button(lateral.corpo, style="Grupo.Toolbutton",
                         command=lambda: _alternar(nome))
        cab.pack(fill="x", pady=px((12, 2)), padx=px((10, 8)))
        corpo_g = tk.Frame(lateral.corpo, background=widgets.cores()["cartao"],
                           highlightthickness=0)
        grupos[nome] = {"cabecalho": cab, "corpo": corpo_g, "titulo": titulo,
                        "aberto": False,
                        "itens": [c for c, _, _ in itens_do_grupo]}
        # O recuo é o que diz "estes pertencem àquele": sem ele, fechar o
        # grupo era a única pista de que existia um grupo.
        for chave, icone, texto in itens_do_grupo:
            _item(corpo_g, chave, icone, texto, recuo=10)
        cab.configure(text=titulo(False))
        if prefs_grupos.get(nome, True):          # por padrão, abertos
            _alternar(nome, salvar=False)

    # Os rótulos dizem o que a aba FAZ hoje, e não o que ela fazia quando
    # nasceu: "Remessa/Retorno" gera a planilha do dia e também a remessa e o
    # retorno CNAB, e "Saldo de pagamentos" existe para dizer quanto falta em
    # cada conta para os pagamentos do dia fecharem.
    _grupo("diario", "DIÁRIO", (("pag", "🗓", "Remessa/Retorno"),
                                ("con", "⚖", "Saldo de pagamentos")))
    _grupo("mensal", "MENSAL", (("rel", "📊", "Relatório Mensal"),
                                ("ext", "🏦", "Extratos Sicoob"),
                                ("ctr", "📑", "Contratos"),
                                ("acs", "📤", "Acessorias")))

    # ---------------- canto direito da barra: navegador, versão, quem entrou
    chip = widgets.ChipStatus(barra.direita)
    chip.pack(side="left", padx=px((0, 18)), pady=px(14))
    if _v_curta:
        # Curta na tela, inteira na dica: o número de build só interessa a quem
        # está comparando com uma release, e para esse a dica basta.
        _lbl_versao = ttk.Label(barra.direita, text=_v_curta,
                                style="BarraTenue.TLabel")
        _lbl_versao.pack(side="left", padx=px((0, 16)), pady=px(14))
        widgets.Dica(_lbl_versao, f"versão {_v}")
    widgets.Avatar(barra.direita, _eu.email).pack(side="left", pady=px(11))
    _lbl_quem = ttk.Label(barra.direita, text=_eu.primeiro_nome[:22],
                          style="Barra.TLabel")
    _lbl_quem.pack(side="left", padx=px((8, 0)), pady=px(14))
    # O papel na dica, e não na barra: ele importa no dia em que alguém
    # estranha uma aba que não está lá, e nos outros 364 seria ruído.
    if _eu.papel:
        widgets.Dica(_lbl_quem, f"{_eu.email} — {_eu.papel}")

    # ---------------- rodapé do menu: usuários (admin), tema e cadastro
    # No rodapé, e não na lista de abas: administrar quem entra não é uma
    # rotina do dia — fica junto do tema e da versão, que são as outras coisas
    # que se mexe de vez em quando.
    if _eu.admin:
        aba_usr = UsuariosFrame(conteudo,
                                lambda: _token_ou_vazio(_pasta_dados()), _eu)
        quadros["usr"] = aba_usr
        _permitidas = _permitidas + ("usr",)
        _item(lateral.rodape, "usr", "👥", "Usuários")
        ttk.Frame(lateral.rodape, height=widgets.px(10)).pack()

    ttk.Label(lateral.rodape, text="TEMA", style="MenuSecao.TLabel"
              ).pack(anchor="w", pady=px((0, 3)))
    combo_tema = ttk.Combobox(lateral.rodape, state="readonly", width=19,
                              values=["Automático (sistema)", "Claro", "Escuro"])
    _ordem = ["auto", "claro", "escuro"]
    combo_tema.current(_ordem.index(escolha_tema)
                       if escolha_tema in _ordem else 0)
    combo_tema.pack(anchor="w", pady=px((0, 8)))
    # Cadastro velho não impede o app de rodar, mas quem está conferindo um
    # fechamento precisa saber que a conta nova cadastrada hoje pode não estar
    # aqui. Sem este aviso, "usando a cópia" é indistinguível de "tudo certo".
    if _sinc.usando_copia:
        widgets.Pilula(lateral.rodape, "⚠  cadastro offline", "atencao"
                       ).pack(anchor="w")
    else:
        widgets.Pilula(lateral.rodape, "✓  cadastro sincronizado", "ok"
                       ).pack(anchor="w")
    if _v_curta:
        # A versão também aqui, embaixo de tudo: é onde ela morava antes do
        # redesenho, e é o primeiro lugar onde se procura por ela. Mesma dica
        # da barra — o número inteiro está a um cursor de distância.
        _rodape_versao = ttk.Label(lateral.rodape, text=_v_curta,
                                   style="MenuSecao.TLabel")
        _rodape_versao.pack(anchor="w", pady=px((8, 0)))
        widgets.Dica(_rodape_versao, f"versão {_v}")

    def aplicar_tema(escolha: str):
        efetivo = tema_efetivo(escolha)
        if sv_ttk:
            sv_ttk.set_theme(efetivo)
        # Depois do sv-ttk, nunca antes: trocar de tema recria o tema do ttk
        # inteiro e apaga todo estilo nomeado configurado até aqui.
        widgets.aplicar_estilos(efetivo == "dark")
        widgets.barra_de_titulo(root, efetivo == "dark")
        try:                             # fundo da janela na cor exata do tema
            root.configure(background=widgets.cores()["fundo"])
        except tk.TclError:
            pass
        escuro = efetivo == "dark"
        for f in quadros.values():
            try:
                f.aplicar_cores(escuro)
            except Exception:
                pass

    def trocar_tema(_=None):
        nova = _ordem[combo_tema.current()]
        prefs["tema"] = nova
        _salvar_prefs(prefs)
        aplicar_tema(nova)

    combo_tema.bind("<<ComboboxSelected>>", trocar_tema)

    # ---------------- onde o trabalho está acontecendo
    # Dez abas dividem UM navegador (o ERP aceita uma sessão por usuário), e
    # até aqui isso só aparecia quando já era tarde: a pessoa clicava numa
    # segunda aba e levava o aviso "Navegador ocupado". A barra de cima agora
    # responde a pergunta ANTES do clique — a aba que trabalha troca o ícone
    # por ●, e o chip diz o que ela está fazendo.
    por_frame = {id(f): n for n, f in quadros.items()}
    _reticencias = ("", ".", "..", "...")
    pulso = {"i": 0}

    def _quem_trabalha() -> tuple[str | None, str]:
        """(aba que está com um navegador, o que ela está fazendo)."""
        for pergunta in (
                # o navegador do ERP, dividido por oito abas...
                lambda: (por_frame.get(id(aba_anx.dona_ocupada())),
                         aba_anx.ocupado()),
                # ...o do Sicoob, que é processo e login à parte...
                lambda: ("ext", aba_ext.ocupado()),
                # ...e o do portal do escritório, pelo mesmo motivo
                lambda: ("acs", aba_acs.ocupado()),
                # A Separar não tem navegador nenhum — o trabalho dela é OCR e
                # disco. Entra aqui mesmo assim porque um PDF de 107 páginas
                # leva minutos, e a aba que não responde parece parada: o ●
                # diz ONDE o trabalho está, e não só quem segurou o Chrome.
                # Vem por último para nunca disputar o sinal com quem está com
                # um navegador na mão, que é a informação mais cara.
                lambda: ("sep", aba_sep.ocupado())):
            try:
                chave, tarefa = pergunta()
            except Exception:
                continue                 # aba sem o método: só não sinaliza
            if tarefa:
                return chave, tarefa
        return None, ""

    def _pulso():
        chave, tarefa = _quem_trabalha()
        for n, it in itens.items():
            try:
                it.trabalhando(n == chave)
            except tk.TclError:
                pass
        if tarefa:
            pulso["i"] = (pulso["i"] + 1) % len(_reticencias)
            chip.definir(f"{tarefa}{_reticencias[pulso['i']]}", True)
        else:
            pulso["i"] = 0
            chip.definir("Navegador livre", False)
        root.after(600, _pulso)

    def _enter_aciona(_ev=None):
        """Enter num campo de texto dispara o passo principal da aba.

        Só a partir de um Entry, e nunca de um Text: o registro ocupa metade
        da tela em seis abas, e Enter ali é quebra de linha para quem leu o
        resultado — não é ordem para começar meia hora de trabalho no ERP."""
        try:
            foco = root.focus_get()
        except (KeyError, tk.TclError):
            return
        if not isinstance(foco, ttk.Entry) or isinstance(foco, ttk.Combobox):
            return
        quadro = quadros.get(atual["nome"])
        # O bind é global (`bind_all`), então o campo com o foco pode estar
        # numa janela de diálogo — a de dúvidas, a de escolher contrato. Enter
        # ali é para o diálogo, não para a aba atrás dele. O caminho do widget
        # no Tk é hierárquico, e conferi-lo é o teste exato de "está dentro".
        if quadro is None or not str(foco).startswith(f"{quadro}."):
            return
        # `acao_enter` quando a aba quer nomear o que o Enter faz (nos Aportes
        # é "adicionar à lista", e não o passo 1, que fala com o ERP); senão
        # `b1` nas abas de passos numerados e `btn` nas de ação única.
        # Aba sem nenhum dos três simplesmente não responde ao Enter.
        for nome_attr in ("acao_enter", "b1", "btn"):
            b = getattr(quadro, nome_attr, None)
            if b is not None and str(b.cget("state")) == "normal":
                b.invoke()
                return

    root.bind_all("<Return>", _enter_aciona)
    # Ctrl+K é o atalho que a própria barra anuncia no texto do campo. Vai no
    # `bind_all` para valer com o foco em qualquer lugar — inclusive dentro de
    # um campo de texto, que é de onde ele mais se usa.
    root.bind_all("<Control-k>", barra.focar_busca)
    root.bind_all("<Control-K>", barra.focar_busca)

    # ---------------- o menu pelo teclado
    # O `widgets.ItemMenu` passou a entrar no Tab (antes só escutava o clique,
    # e quem usa só o teclado alcançava DIÁRIO e MENSAL sem alcançar nenhuma
    # das doze telas que eles agrupam). Tab percorre a coluna; estes atalhos
    # são o caminho DIRETO — doze telas atrás de doze Tabs é alcançável, não é
    # usável.
    #
    # A ordem é a do menu, e sai do próprio `itens`: o `_item` insere na ordem
    # em que monta a coluna, e dicionário do Python preserva a ordem de
    # inserção. Uma segunda lista escrita à mão divergiria no primeiro dia em
    # que alguém trocasse duas abas de lugar — e divergiria em silêncio, com o
    # Ctrl+3 abrindo a quarta tela.
    #
    # Vai no `bind_all` como o Ctrl+K, e pelo mesmo motivo: o atalho tem de
    # valer com o foco em qualquer lugar da janela.
    def _telas() -> list:
        return list(itens)

    def _foco_num_text() -> bool:
        """O foco está dentro de um `tk.Text`?

        Ali o Tab é do EDITOR. O Tk já liga `<Control-Tab>` da classe Text à
        navegação de foco, e essa ligação roda antes desta; sem a pergunta, um
        Ctrl+Tab dentro do registro moveria o foco E trocaria de aba, o que
        deixa a pessoa noutra tela sem ter pedido."""
        try:
            return isinstance(root.focus_get(), tk.Text)
        except (KeyError, tk.TclError):
            return False

    def _ir_para(indice: int):
        telas = _telas()
        if 0 <= indice < len(telas):
            mostrar(telas[indice])

    def _vizinha(passo: int):
        telas = _telas()
        if not telas:
            return
        try:
            onde = telas.index(atual["nome"])
        except ValueError:
            onde = 0                     # nenhuma aberta ainda: começa do topo
        mostrar(telas[(onde + passo) % len(telas)])

    def _atalho_numero(ev=None):
        # Ctrl+1..9 alcançam as NOVE primeiras telas do menu. Não há Ctrl+0 nem
        # Ctrl+10: dez teclas de dígito para doze telas escolheria duas para
        # ficar de fora sem critério nenhum. Da décima em diante é o Ctrl+Tab.
        try:
            _ir_para(int(ev.keysym) - 1)
        except (AttributeError, ValueError):
            pass
        return "break"

    def _proxima(_ev=None):
        if _foco_num_text():
            return None                  # o Ctrl+Tab é do editor, não do menu
        _vizinha(1)
        return "break"

    def _anterior(_ev=None):
        if _foco_num_text():
            return None
        _vizinha(-1)
        return "break"

    for _n in range(1, 10):
        root.bind_all(f"<Control-Key-{_n}>", _atalho_numero)
    root.bind_all("<Control-Tab>", _proxima)
    root.bind_all("<Control-Shift-Tab>", _anterior)
    # No X11 o Shift+Tab chega com keysym próprio. Não custa nada aqui e é o
    # que faz o atalho existir para quem rodar o app como script fora do
    # Windows — que é como ele é desenvolvido.
    root.bind_all("<Control-ISO_Left_Tab>", _anterior)
    # A busca da barra é um "ir para uma tela", e é AQUI que ela ganha para
    # onde ir. Depois do menu montado, de propósito: a lista sai de `itens`, que
    # já respeita o papel de quem entrou — a busca não leva ninguém a uma tela
    # que o menu dessa pessoa não mostra. E o comando é o `acionar` do próprio
    # `ItemMenu`, que é o mesmíssimo caminho do clique: `mostrar` faz mais coisa
    # que trocar de quadro (abre o grupo fechado, chama o `ao_abrir` da aba, põe
    # o foco no primeiro campo), e uma segunda porta para a mesma tela seria
    # uma segunda chance de esquecer um desses passos.
    barra.definir_telas((it.texto(), it.acionar) for it in itens.values())
    aba_ini.definir_navegacao(mostrar)

    aplicar_tema(escolha_tema)
    # "ini" para quase todo mundo; para um papel que não a alcance, a
    # primeira que ele alcança. Abrir numa aba que o menu não mostra deixaria
    # o app com a tela de um item inexistente selecionado.
    mostrar("ini" if _pode("ini") else next(iter(_permitidas), "ini"))
    _pulso()

    def _sair():
        # Um `fechar()` que levanta não pode impedir o outro nem o destroy():
        # a janela ficaria aberta e sem resposta, e o jeito de sair viraria o
        # Gerenciador de Tarefas — que é justamente o que deixa Chrome órfão.
        #
        # Percorre TODAS as abas em vez de uma tupla escrita à mão. São TRÊS
        # navegadores (o do ERP, o do Sicoob e o do portal contábil), e a lista
        # fixa citava dois: o Chrome da aba Acessórias sobrevivia ao fechar do
        # app, com a sessão do escritório aberta, esperando o Gerenciador de
        # Tarefas. A barra lateral já pergunta às três se estão ocupadas
        # (`_quem_trabalha`) — quem sabe quem existe é o `quadros`, e não uma
        # tupla que a próxima aba com navegador próprio vai esquecer de novo.
        for _quadro in quadros.values():
            _fechar = getattr(_quadro, "fechar", None)
            if _fechar is None:
                continue                 # aba sem navegador: nada a fechar
            try:
                _fechar()
            except Exception:
                pass
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", _sair)

    # ---------------- conta nova no Mais Controle
    #
    # Roda DEPOIS de a janela existir e ANTES de qualquer aba abrir o Chrome.
    # A ordem e a unica defesa contra a sessao unica do ERP: o login por API
    # derruba a do navegador, e na abertura ainda nao ha navegador. Se a
    # pessoa abrir uma aba enquanto isto roda, o pior que acontece e aquela
    # aba refazer o login sozinha, que ela ja sabe fazer desde 18/08.
    #
    # Em thread, e engolindo tudo: conferencia opcional nao pode atrasar nem
    # impedir a abertura. E a mesma regra que protege o `sincronizar`.
    # O diagnostico desta conferencia. Era um `open(..., "a")` deste bloco so,
    # escrevendo a mensagem crua no MESMO `diagnostico.log` que todo o resto ja
    # usa - sem data, sem hora e sem dizer de onde a linha vinha, no meio de um
    # arquivo em que as demais nascem com prefixo. `util.log()` pendura a linha
    # no `RotatingFileHandler` de sempre, com o formato de sempre, e o texto das
    # mensagens nao muda; o arquivo e o mesmo (`util.pasta_base()` e a pasta do
    # exe congelado e a raiz rodando como script, igual ao `_pasta_dados()`).
    #
    # "contas_novas" e nao `__name__`: aqui `__name__` e "comprovantes_app"
    # (ou "__main__", rodando como script), e quem le o log depois quer saber
    # que a linha e da conferencia de contas, e nao da moldura da janela.
    #
    # `.info` e nao o logger inteiro porque `_anotar` continua sendo CHAMAVEL:
    # ele e passado adiante como `log=` para `contas_novas.novidades`.
    _anotar = util.log("contas_novas").info

    def _perguntar_contas(novas, empresas, token):
        from nuvem import contas_novas, contas_novas_dialogo
        try:
            escolhas = contas_novas_dialogo.perguntar(root, novas, empresas)
            if not escolhas:
                return
            avisos = contas_novas.gravar(token, escolhas)
            quantas = len(escolhas) - len(avisos)
            recado = f"{quantas} conta(s) cadastrada(s)."
            if avisos:
                recado += "\n\nNao gravadas:\n" + "\n".join(avisos)
            messagebox.showinfo("Contas novas", recado)
        except Exception as e:                            # noqa: BLE001
            _anotar(f"conferencia de contas (gravacao): {e}")
            messagebox.showerror(
                "Contas novas",
                widgets.recado_de_erro(e, "Nao deu para cadastrar as contas."))

    def _conferir_contas():
        from nuvem import contas_novas
        try:
            pasta = _pasta_dados()
            token = _token_ou_vazio(pasta)
            if not token:
                _anotar("conferencia de contas: sem sessao da nuvem; pulei.")
                return
            novas = contas_novas.novidades(pasta, log=_anotar)
            if not novas:
                return
            empresas = contas_novas.empresas(token)
            root.after(0, lambda: _perguntar_contas(novas, empresas, token))
        except Exception as e:                            # noqa: BLE001
            _anotar(f"conferencia de contas: {e}")

    threading.Thread(target=_conferir_contas, daemon=True).start()

    root.mainloop()


if __name__ == "__main__":
    main()
