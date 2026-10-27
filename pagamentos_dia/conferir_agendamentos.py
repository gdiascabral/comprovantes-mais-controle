# -*- coding: utf-8 -*-
"""O "Conferir agendamentos" sem a tela: quem o chama é a Remessa/Retorno
(`pagamentos_frame`) e a aba "Pagamentos do dia" (`tela_do_dia/
agendamentos_na_tela.py`), e as duas fazem a MESMA coisa por aqui.

Pedido do dono em 15/10/2026: agendar pelo HTML e, antes de assinar,
conferir se cada agendamento bate — valor, quem recebe e se nada ficou de
fora. Em 23/10/2026: "já acrescente o de verificar os agendamentos no
pagamentos do dia". O que era do frame da Remessa (separar as contas, ler o
banco, a janela do resumão) mudou para cá sem mudar de comportamento; a
regra do confronto continua em `agendamentos_sicoob` e a leitura do banco
em `extratos_sicoob.pendencias`, SÓ LEITURA (nada é assinado, cancelado nem
alterado no banco).

**O outro acesso do Sicoob** (as contas de outra empresa ficam noutro login,
com outro QR Code — prova ao vivo de 22/10/2026 no saldo): com `perguntar`,
a conta que este login não enxerga não fica só vermelha — a tela pergunta e
o MESMO Chrome do app (o mesmo perfil) abre de novo para o outro acesso,
lendo só as que faltaram. É o caminho de `saldo.ler_em_dois_acessos`. Sem
`perguntar` (a Remessa/Retorno), nada muda: a conta fica "não conferida".
"""
from __future__ import annotations

import datetime
import os
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import messagebox, ttk

import util
import widgets

from . import agendamentos_sicoob
from . import relatorio

px = widgets.px
TITULO = "Conferir agendamentos"

#: O Chrome voltou no MESMO acesso (a sessão ficou no perfil): ler de novo
#: daria "em nenhum dos dois", e não é verdade.
MESMO_ACESSO = ("o Chrome voltou no mesmo acesso do Sicoob: saia do SicoobNet "
                "(botão Sair) e clique em Conferir agendamentos de novo para "
                "entrar com o outro acesso")
EM_NENHUM_ACESSO = ("esta conta não aparece em nenhum dos dois acessos lidos "
                    "do Sicoob")


# --------------------------------------------------------------- separar


@dataclass
class Separacao:
    """As contas do HTML: `no_sicoob` = [(conta, número, "")], `fora` =
    [(conta, "", motivo)] (outro banco ou cadastro que não diz a conta) e
    `sem_cadastro` = [(conta, motivo)], as de `fora` que NÃO são de outro
    banco — as que seriam assinadas sem conferência."""
    no_sicoob: list = field(default_factory=list)
    fora: list = field(default_factory=list)
    sem_cadastro: list = field(default_factory=list)

    def recusa(self) -> tuple[str, str] | None:
        """`("aviso"|"info", texto)` quando não há conta do Sicoob a ler.

        "Não há o que conferir" só quando TODAS são de outro banco. A conta
        do Sicoob que o cadastro não resolve (subconta nova fora do
        `contas_sicoob.json`) não pode ganhar o mesmo recado neutro: as
        pendências dela seriam assinadas sem conferência."""
        if self.no_sicoob:
            return None
        if self.sem_cadastro:
            return ("aviso",
                    "Nenhuma conta pôde ser conferida. Estas ficaram de fora "
                    "por cadastro — confira-as à mão antes de assinar:\n\n"
                    + "\n".join(f"• {c.get('nome')}: {m}"
                                for c, m in self.sem_cadastro[:12]))
        return ("info", "Nenhuma conta deste HTML é do Sicoob — não há o que "
                        "conferir no SicoobNet.")


def separar(contas, mapa_mc, empresas) -> Separacao:
    """Cada conta do HTML (`agendamentos_sicoob.ler_html`) pelo MESMO
    caminho da remessa (`agendamentos_sicoob.conta_sicoob`)."""
    A = agendamentos_sicoob
    sep = Separacao()
    for c in contas:
        numero, motivo = A.conta_sicoob(str(c.get("nome") or ""), mapa_mc, empresas)
        (sep.no_sicoob if numero else sep.fora).append((c, numero, motivo))
    sep.sem_cadastro = [(c, m) for c, _n, m in sep.fora
                        if m != A.MOTIVO_FORA_SICOOB]
    return sep


def mostrar_recusa(recusa, parent=None) -> None:
    """A `Separacao.recusa()` na tela, no nível que ela pede."""
    nivel, texto = recusa
    mostrar = messagebox.showwarning if nivel == "aviso" else messagebox.showinfo
    if parent is None:
        mostrar(TITULO, texto)
    else:
        mostrar(TITULO, texto, parent=parent)


def pergunta_de_abrir(quantas: int, inicio, fim) -> str:
    return (f"Vou abrir o Chrome do Sicoob e ler as transações pendentes de "
            f"assinatura de {quantas} conta(s), de "
            f"{inicio:%d/%m} a {fim:%d/%m/%Y}.\n\n"
            "É só leitura: nada é assinado, cancelado nem alterado no "
            "banco.\n\nFaça o login quando a janela abrir.")


def recado_em_uso(quem: str) -> str:
    return (f"O Chrome do Sicoob está em uso ({quem}). Espere terminar: "
            "os dois usariam o mesmo perfil do banco.")


# ---------------------------------------------------------- ler no banco


def _primeira_linha(erro) -> str:
    texto = (str(erro or "").strip().splitlines() or [""])[0].strip()
    return texto[:160] or type(erro).__name__


def _mesmas_contas(a, b) -> bool:
    """As duas listas de contas do login são a mesma (pelos dígitos)? Lista
    não lida ou vazia não prova nada."""
    from extratos_sicoob.pendencias import so_digitos
    if not a or not b:
        return False
    return sorted(so_digitos(n) for n in a) == sorted(so_digitos(n) for n in b)


def ler_no_banco(no_sicoob, fora, inicio, fim, *, log, abrir=None, ler_conta=None,
                 perguntar=None, parar=lambda: False) -> list:
    """Lê as pendências de assinatura de cada conta do Sicoob e confronta
    com o HTML. Roda na thread do Sicoob de quem chama; não toca em Tk.

    Toda conta do Sicoob nasce "não lida" ANTES de abrir o navegador, e só
    troca de estado quando é lida de verdade: uma exceção no meio (sessão
    que cai, login que não acontece) não pode fazer as contas que faltavam
    SUMIREM da tabela — a que some é assinada sem conferência (revisão de
    dinheiro, 15/10/2026). Duas contas do ERP com o mesmo número do Sicoob
    são conferidas JUNTAS (`agrupar_por_numero`): lidas uma vez cada, o
    mesmo agendamento casaria nas duas e pintaria de verde dois pagamentos
    com um só agendado.

    `abrir()` devolve o `SicoobClient` (o mesmo perfil, a extensão e o
    pt-BR que fazem o banco reconhecer o PC); `ler_conta` é
    `pendencias.ler_conta`. `perguntar(nomes)` liga o outro acesso (ver o
    docstring do módulo)."""
    A = agendamentos_sicoob
    confrontos = [A.Confronto(conta_erp=str(c.get("nome") or ""), motivo=motivo)
                  for c, _n, motivo in fora]
    grupos = A.agrupar_por_numero(no_sicoob)
    pendentes = [A.Confronto(conta_erp=nome, numero=numero, motivo=A.MOTIVO_NAO_LIDA)
                 for nome, numero, _e in grupos]
    confrontos.extend(pendentes)

    def ler(cli, conf, grupo) -> bool:
        """Lê UMA conta; True = este login não a enxerga."""
        nome, numero, entradas = grupo
        try:
            lidas = ler_conta(cli, numero, inicio, fim)
        except Exception as e:                               # noqa: BLE001
            conf.motivo = f"o Sicoob não respondeu: {e}"
            fora_do_login = str(e) == fora_deste_login
        else:
            conf.linhas = A.confrontar(entradas, lidas)
            conf.motivo = ""
            fora_do_login = False
        log(f"  {nome} ({numero}): {conf.resumo()}")
        return fora_do_login

    faltam, contas_do_login, fora_deste_login = [], None, None
    try:
        # Os imports moram DENTRO do try (revisão de 23/10/2026): fora dele,
        # uma falha ao carregar o Chrome matava a thread de quem chama sem
        # nada na fila, e o botão ficava apagado para sempre.
        from extratos_sicoob import pendencias
        fora_deste_login = pendencias.FORA_DESTE_LOGIN
        if ler_conta is None:
            ler_conta = pendencias.ler_conta
        if abrir is None:
            from extratos_sicoob.sicoob_client import SicoobClient

            def abrir():
                return SicoobClient(log=lambda m: log(f"  {m}"))
        with abrir() as cli:
            cli.aguardar_login()
            for conf, grupo in zip(pendentes, grupos):
                if ler(cli, conf, grupo):
                    faltam.append((conf, grupo))
            if faltam and perguntar is not None:
                try:
                    contas_do_login = list(cli.listar_contas() or [])
                except Exception:                            # noqa: BLE001
                    contas_do_login = None
    except Exception as e:                                   # noqa: BLE001
        log(f"[!] Conferir agendamentos: {e}")
        # As que ficaram para trás levam o porquê para a tabela.
        for conf in pendentes:
            if conf.motivo == A.MOTIVO_NAO_LIDA:
                conf.motivo = A.motivo_da_parada(e)
        return confrontos

    if not faltam or perguntar is None or parar() \
            or not perguntar([conf.conta_erp for conf, _g in faltam]):
        return confrontos
    log(f"  {len(faltam)} conta(s) de outro acesso — abrindo o Chrome do Sicoob "
        "de novo; entre com o outro acesso (QR Code).")
    try:
        with abrir() as cli:
            cli.aguardar_login()
            outra = list(cli.listar_contas() or [])
            if _mesmas_contas(contas_do_login, outra):
                log(f"  {MESMO_ACESSO}")
                for conf, _g in faltam:
                    conf.motivo = MESMO_ACESSO
            else:
                for conf, grupo in faltam:
                    if ler(cli, conf, grupo):
                        conf.motivo = EM_NENHUM_ACESSO
    except Exception as e:                                   # noqa: BLE001
        motivo = f"o outro acesso do Sicoob não entrou: {_primeira_linha(e)}"
        log(f"  {motivo}")
        for conf, _g in faltam:
            if not conf.conferida:
                conf.motivo = motivo
    return confrontos


# ------------------------------------------------------------- a janela


def abrir_janela(master, caminho, confrontos):
    """O resumão do confronto e a tabela por conta, com a marca de quem
    conferiu (dono, 21/10/2026: "abra uma tela me mostrando um resumão e
    um campo pra eu marcar como certo/conferido").

    Só leitura no BANCO — nada aqui mexe no Sicoob. A marca é da pessoa e
    mora ao lado do HTML (`agendamentos_sicoob.caminho_das_marcas`), presa
    ao que foi visto: outra leitura que mude a linha a deixa sem marca."""
    A = agendamentos_sicoob
    arq_marcas = A.caminho_das_marcas(caminho)
    marcas = A.ler_marcas(arq_marcas)
    try:
        from nuvem import sessao
        quem = sessao.quem(util.pasta_base()).email or os.environ.get(
            "USERNAME", "")
    except Exception:                                    # noqa: BLE001
        quem = os.environ.get("USERNAME", "")

    def brl(valor):
        return "" if valor is None else relatorio.brl(float(valor))

    top = tk.Toplevel(master)
    top.title(f"Agendamentos no Sicoob × {caminho.name}")
    top.geometry(f"{px(1320)}x{px(720)}")
    widgets.barra_de_titulo(top)
    moldura = ttk.Frame(top, padding=14)
    moldura.pack(fill="both", expand=True)
    ttk.Label(moldura, style="Titulo.TLabel",
              text="Resumo dos agendamentos no Sicoob").pack(anchor="w")
    ttk.Label(moldura, style="Apoio.TLabel",
              text=f"{caminho.name} — só leitura: nada foi assinado, "
                   "cancelado nem alterado no banco.").pack(anchor="w")

    # O resumão: os números que respondem "posso assinar?".
    quadro = ttk.Frame(moldura)
    quadro.pack(fill="x", pady=px((10, 6)))
    numeros = {}
    for col, (chave, rotulo) in enumerate((
            ("contas", "Contas do Sicoob lidas"), ("batem", "Batem"),
            ("diferenca", "Com diferença"),
            ("nao_lidas", "Não conferidas"),
            ("html", "Total no HTML"), ("banco", "Total agendado"),
            ("marcadas", "Contas marcadas"))):
        caixa = ttk.Frame(quadro)
        caixa.grid(row=0, column=col, sticky="w", padx=px((0, 28)))
        ttk.Label(caixa, style="Apoio.TLabel",
                  text=rotulo).pack(anchor="w")
        numeros[chave] = ttk.Label(caixa, style="KPI.TLabel", text="")
        numeros[chave].pack(anchor="w")
    a_olhar = ttk.Label(moldura, style="Apoio.TLabel",
                        wraplength=px(1260), justify="left")
    a_olhar.pack(anchor="w")
    nao_lidas = [c for c in confrontos if c.falhou]
    if nao_lidas:
        # Em cima e em vermelho: é a conta cujas pendências seriam
        # assinadas SEM conferência, e um número escondido no meio da
        # tabela não segura ninguém.
        ttk.Label(moldura, style="Erro.TLabel", wraplength=px(1260),
                  justify="left",
                  text=f"✖  {len(nao_lidas)} conta(s) do Sicoob NÃO "
                       f"conferida(s): "
                       + ", ".join(c.conta_erp for c in nao_lidas)
                       + ". Não assine as pendências delas sem conferir."
                  ).pack(anchor="w", pady=px((4, 0)))
    ttk.Label(moldura, style="Apoio.TLabel", wraplength=px(1260),
              justify="left",
              text="Casado pelo valor; o nome só desempata. Âmbar é para "
                   "olhar antes de assinar, vermelho é diferença de "
                   "dinheiro. Clique no ☐ (ou selecione e aperte Espaço) "
                   "para marcar como conferido — na linha da conta, a "
                   "conta inteira.").pack(anchor="w", pady=px((4, 8)))

    def atualizar_resumao():
        r = A.resumao(confrontos, marcas)
        numeros["contas"].configure(
            text=f"{r.lidas} de {r.contas_sicoob}")
        numeros["batem"].configure(text=str(r.batem))
        numeros["diferenca"].configure(text=str(r.com_diferenca))
        numeros["nao_lidas"].configure(text=str(r.nao_lidas))
        numeros["html"].configure(text=brl(r.total_html))
        numeros["banco"].configure(text=brl(r.total_banco))
        numeros["marcadas"].configure(
            text=f"{r.contas_marcadas} de {r.contas_sicoob}")
        partes = [f"{n} {A.FRASES[s]}" for s, n in r.por_situacao.items()]
        if partes:
            a_olhar.configure(text=(
                "Para olhar: " + " · ".join(partes)
                + f" — {r.linhas_marcadas} de {r.linhas_a_olhar} "
                  "linha(s) já marcadas como conferidas."))
        else:
            a_olhar.configure(text="Nenhuma linha pede conferência: "
                                   "tudo o que foi lido bate.")

    colunas = ("conferido", "situacao", "html", "banco", "no_html",
               "no_banco")
    tabela = ttk.Treeview(moldura, columns=colunas, show="tree headings",
                          height=16)
    tabela.heading("#0", text="Conta")
    tabela.column("#0", width=px(250), anchor="w")
    for chave, titulo, larg, ancora in (
            ("conferido", "Conferido", 90, "center"),
            ("situacao", "Situação", 230, "w"),
            ("html", "Valor no HTML", 110, "e"),
            ("banco", "Valor no banco", 110, "e"),
            ("no_html", "No HTML", 280, "w"),
            ("no_banco", "No banco", 280, "w")):
        tabela.heading(chave, text=titulo)
        tabela.column(chave, width=larg, anchor=ancora)
    widgets.estilo_tabela(tabela, ordenavel=False)
    rolagem = ttk.Scrollbar(moldura, orient="vertical",
                            command=tabela.yview)
    tabela.configure(yscrollcommand=rolagem.set)

    # iid -> (confronto, linha ou None). Conta de outro banco e linha que
    # já bate não têm marca: não há o que conferir nelas.
    alvo = {}

    def marca_de(conf, li):
        if li is None:
            if not A.conta_marcavel(conf):
                return ""
            return "☑" if A.conta_conferida(conf, marcas) else "☐"
        if not A.precisa_olhar(li):
            return "✓"
        return "☑" if A.chave_da_linha(conf, li) in marcas else "☐"

    i = 0
    for conf in confrontos:
        estado = ("erro" if conf.falhou
                  else "info" if not conf.conferida
                  else A.ESTADO[conf.pior])
        pai = tabela.insert(
            "", "end", text=conf.conta_erp, open=conf.pior != A.OK,
            values=(marca_de(conf, None), conf.resumo(),
                    brl(conf.total_html) if conf.conferida else "",
                    brl(conf.total_banco) if conf.conferida else "",
                    "", conf.numero),
            tags=widgets.linha_zebrada(i, estado))
        alvo[pai] = (conf, None)
        i += 1
        for li in conf.linhas:
            h, b = li.html or {}, li.banco or {}
            no_html = " · ".join(x for x in (
                str(h.get("favorecido") or ""),
                str(h.get("descricao") or "")) if x)
            # A situação do banco só aparece quando NÃO é a de sempre:
            # "Todas" pode trazer o que já não está pendente.
            situacao_banco = str(b.get("situacao") or "")
            no_banco = " · ".join(x for x in (
                str(b.get("detalhe") or ""),
                str(b.get("nomeTransacao") or ""),
                situacao_banco if situacao_banco not in (
                    "", "PENDENTE_ASSINATURA") else "") if x)
            filho = tabela.insert(pai, "end", text="", values=(
                marca_de(conf, li), li.frase, brl(li.valor_html),
                brl(li.valor_banco), no_html, no_banco),
                tags=widgets.linha_zebrada(i, A.ESTADO[li.situacao]))
            alvo[filho] = (conf, li)
            i += 1

    def alternar(iid):
        if iid not in alvo:
            return
        conf, li = alvo[iid]
        if marca_de(conf, li) not in ("☐", "☑"):
            return
        chave = (A.chave_da_conta(conf) if li is None
                 else A.chave_da_linha(conf, li))
        if li is None and chave not in marcas:
            faltam = [x for x in conf.linhas if A.precisa_olhar(x)
                      and A.chave_da_linha(conf, x) not in marcas]
            if A.tem_erro(conf) or faltam:
                # Marcar a conta inteira por cima do vermelho é decisão
                # de quem confere, mas não pode sair de um clique só.
                por = (f"tem {len(faltam)} linha(s) ainda sem marca"
                       if faltam else "tem diferença de dinheiro")
                if not messagebox.askyesno(
                        "Conferir agendamentos",
                        f"A conta {conf.conta_erp} {por}.\n\nMarcar a "
                        "conta inteira como conferida mesmo assim?",
                        icon="warning", parent=top):
                    return
        antes = dict(marcas)
        A.alternar(marcas, chave, quem,
                   datetime.datetime.now().isoformat(timespec="seconds"))
        try:
            A.gravar_marcas(arq_marcas, marcas)
        except OSError as e:
            marcas.clear()
            marcas.update(antes)
            messagebox.showwarning(
                "Conferir agendamentos",
                widgets.recado_de_erro(
                    e, "Não consegui guardar a marca ao lado do HTML."),
                parent=top)
            return
        tabela.set(iid, "conferido", marca_de(conf, li))
        atualizar_resumao()

    def ao_clicar(evento):
        if tabela.identify_region(evento.x, evento.y) != "cell":
            return None
        if tabela.identify_column(evento.x) != "#1":
            return None
        iid = tabela.identify_row(evento.y)
        if not iid:
            return None
        alternar(iid)
        return "break"

    def ao_espaco(_evento):
        for iid in tabela.selection():
            alternar(iid)
        return "break"

    tabela.bind("<Button-1>", ao_clicar, add="+")
    tabela.bind("<space>", ao_espaco)

    # O rodapé entra no pack ANTES da tabela: com pouca altura, quem
    # cede é ela, e o botão de fechar nunca some.
    rodape = ttk.Frame(moldura)
    rodape.pack(side="bottom", fill="x", pady=px((10, 0)))
    ttk.Label(rodape, style="Apoio.TLabel",
              text=f"As marcas ficam em {arq_marcas.name}, ao lado do "
                   "HTML.").pack(side="left")
    widgets.Botao(rodape, "Fechar", papel="neutro",
                  command=top.destroy).pack(side="right")
    rolagem.pack(side="right", fill="y")
    tabela.pack(fill="both", expand=True)
    atualizar_resumao()
