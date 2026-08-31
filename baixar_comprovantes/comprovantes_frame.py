# -*- coding: utf-8 -*-
"""Aba "Baixar Comprovantes": um clique, a fila dos dois bancos.

O trabalho que a pessoa deve fazer é o que o banco EXIGE dela — entrar. O
resto é do robô: percorrer as contas, filtrar o período, baixar cada
comprovante e arquivar na pasta do mês.

**A ordem da fila não é arbitrária: Sicoob primeiro.** Lá um login enxerga as
18 contas; no Inter cada conta é um login, e o QR é pedido a cada abertura —
conferido, o perfil salvo não vence essa trava. Então a fila começa pelo que
resolve muito com um acesso só, e deixa para o fim o que cobra um acesso por
conta.

Nada aqui fala com banco: o que sabe disso são `sicoob_baixar` e
`inter_baixar`. Esta tela mostra a fila, conta o que aconteceu e não deixa a
janela congelar — o trabalho roda noutra thread, como nas outras abas.
"""
from __future__ import annotations

import datetime as _dt
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

try:                                     # widgets compartilhados (raiz)
    import widgets
except ModuleNotFoundError:              # rodando este módulo isoladamente
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import widgets

try:
    import util                          # noqa: F401
except ModuleNotFoundError:              # pragma: no cover
    pass

try:
    from . import contas_inter
except ImportError:                      # rodando este módulo isoladamente
    import contas_inter


def pasta_padrao() -> Path:
    """`<pasta do app>/Comprovantes` — criada na primeira vez que se usa.

    Ao lado do app, como a "Pagamentos do dia" que já vive lá. Quem quiser
    outro lugar troca no campo; o padrão existe para não obrigar ninguém a
    escolher pasta antes de baixar o primeiro comprovante."""
    return Path(util.pasta_base()) / "Comprovantes"


def pasta_da_rodada(base, quando=None) -> Path:
    """`<base>/2026-08-31` — uma subpasta por dia de download.

    TUDO junto lá dentro: sem separar por conta nem por empresa. Não é
    desleixo — é o que o Anexar precisa. Ele varre uma pasta e casa cada
    comprovante com o lançamento pelo conteúdo do nome; separar em galhos só
    obrigaria a percorrer galho por galho para juntar de novo no fim.

    A data é a do DOWNLOAD, e não a do pagamento: ela responde "o que eu
    baixei hoje?", que é a pergunta de quem está com a pasta aberta."""
    dia = (quando or _dt.date.today()).strftime("%Y-%m-%d")
    return Path(base) / dia


#: A marca da primeira coluna. Símbolo, e não caixa de marcar: o Treeview do
#: Tk não aceita widget dentro de célula.
MARCADA = "☑"
DESMARCADA = "☐"

#: Como cada situação aparece na tabela. O símbolo vem junto do texto: a tag
#: do Treeview só pinta duas das situações, e cor sozinha não diz nada a quem
#: não a enxerga.
SITUACOES = {
    "espera": ("·  na fila", "info"),
    "qr": ("⚠  aguardando login", "atencao"),
    "trabalhando": ("·  baixando…", "info"),
    "ok": ("✓  {n} comprovantes", "ok"),
    "vazio": ("·  sem lançamentos", "info"),
    "erro": ("✖  {motivo}", "erro"),
}


class ComprovantesFrame(ttk.Frame):
    """A aba. `obter_mapa` é passado de fora para a tela não decidir de onde
    vem o cadastro — quem sabe disso é quem monta a janela."""

    def __init__(self, pai, obter_mapa=None):
        super().__init__(pai, style="Fundo.TFrame")
        self._obter_mapa = obter_mapa
        self.q: queue.Queue = queue.Queue()
        self.worker = None
        self.linhas: dict[str, dict] = {}
        self._build()
        self.ao_abrir()
        self.after(150, self._drenar)

    # ---------------------------------------------------------------- layout
    def _build(self):
        PADX = widgets.PADX

        cab = widgets.Cabecalho(
            self, "Baixar Comprovantes",
            "Os comprovantes de pagamento de cada banco, arquivados na pasta "
            "do mês. Você só entra quando o banco pedir; o resto é automático.",
            trilha="Comprovantes  ›  Baixar Comprovantes")
        cab.pack(fill="x", padx=PADX, pady=(16, 12))
        self.b_ir = widgets.Botao(cab.acoes, "▶  Baixar comprovantes",
                                  papel="acao", command=self._comecar)
        self.b_ir.pack(side="right")
        widgets.Botao(cab.acoes, "Atualizar lista", papel="neutro",
                      command=self.ao_abrir).pack(side="right", padx=(0, 8))

        # ---- período e destino
        c_per = widgets.Cartao(self, "Período", numero=1)
        c_per.pack(fill="x", padx=PADX, pady=(0, 12))
        linha = ttk.Frame(c_per)
        linha.pack(fill="x")

        hoje = _dt.date.today()
        inicio = hoje - _dt.timedelta(days=7)
        self.v_ini = tk.StringVar(value=f"{inicio:%d/%m/%Y}")
        self.v_fim = tk.StringVar(value=f"{hoje:%d/%m/%Y}")
        for rotulo, var in (("De", self.v_ini), ("Até", self.v_fim)):
            campo = widgets.Campo(linha, rotulo,
                                  lambda pai, v=var: widgets.CampoData(pai, v))
            campo.pack(side="left", padx=(0, 14))

        self.v_pasta = tk.StringVar(value=str(pasta_padrao()))
        campo_pasta = widgets.Campo(
            linha, "Onde salvar",
            lambda pai: ttk.Entry(pai, textvariable=self.v_pasta, width=52))
        campo_pasta.pack(side="left", fill="x", expand=True)
        widgets.Botao(linha, "Escolher…", papel="neutro",
                      command=self._escolher_pasta).pack(side="left",
                                                         padx=(8, 0))

        # ---- a fila
        c_fila = widgets.Cartao(self, "Contas na fila", numero=2)
        c_fila.pack(fill="both", expand=True, padx=PADX, pady=(0, 12))
        colunas = ("marca", "banco", "conta", "empresa", "situacao")
        self.tabela = ttk.Treeview(c_fila, columns=colunas, show="headings",
                                   selectmode="browse", height=9)
        for col, titulo, larg, onde in (("marca", "", 34, "center"),
                                        ("banco", "BANCO", 90, "w"),
                                        ("conta", "CONTA", 130, "w"),
                                        ("empresa", "EMPRESA", 300, "w"),
                                        ("situacao", "SITUAÇÃO", 220, "w")):
            self.tabela.heading(col, text=titulo)
            self.tabela.column(col, width=larg, anchor=onde,
                               stretch=col == "empresa")
        # O cabeçalho da coluna da marca é o "todas": é onde a pessoa procura
        # esse botão numa tabela de seleção, antes de procurar no rodapé.
        self.tabela.heading("marca", text=MARCADA,
                            command=self._alternar_todas)
        widgets.estilo_tabela(self.tabela)
        self.tabela.pack(fill="both", expand=True)
        # Clique na primeira coluna marca e desmarca. Não é `Checkbutton`
        # porque o Treeview do Tk não aceita widget dentro de célula — o
        # símbolo faz o mesmo trabalho, e a coluna inteira é a área de clique.
        self.tabela.bind("<Button-1>", self._clicou)
        self.rodape = widgets.RodapeTabela(c_fila)
        self.rodape.pack(fill="x", pady=(8, 0))
        self.rodape.link("Marcar todas", lambda: self._todas(True))
        self.rodape.link("Desmarcar todas", lambda: self._todas(False))

        # ---- execução e registro
        acao = ttk.Frame(self, style="Fundo.TFrame")
        acao.pack(fill="x", padx=PADX, pady=(0, 10))
        self.barra_exec = widgets.BarraExecucao(acao)
        self.barra_exec.pack(side="left", fill="x", expand=True)
        self.lbl = self.barra_exec.lbl
        self.pb = self.barra_exec.pb

        self.reg = widgets.Cartao(self, "Registro", padding=(12, 10))
        self.reg.pack(fill="x", padx=PADX, pady=(0, 12))
        self.log = tk.Text(self.reg, wrap="word", relief="flat", borderwidth=0,
                           highlightthickness=0)
        self.log.pack(fill="both", expand=True)
        widgets.estilo_log(self.log)
        widgets.registro_elastico(self.reg, self.log)

    def _escolher_pasta(self):
        escolhida = filedialog.askdirectory(initialdir=self.v_pasta.get() or None)
        if escolhida:
            self.v_pasta.set(escolhida.replace("\\", "/"))

    # ----------------------------------------------------------- a lista
    def ao_abrir(self):
        """Relê o cadastro e remonta a fila. Chamado pelo menu a cada visita."""
        self.tabela.delete(*self.tabela.get_children())
        self.linhas.clear()
        try:
            contas = self._contas_do_cadastro()
        except Exception as e:                               # noqa: BLE001
            self._log(f"[!] não consegui ler o cadastro: {e}")
            contas = []

        for i, c in enumerate(contas):
            chave = f"{c['banco']}:{c['conta']}"
            self.linhas[chave] = dict(c, situacao="espera", marcada=True)
            texto, estado = SITUACOES["espera"]
            self.tabela.insert("", "end", iid=chave,
                               values=(MARCADA, c["banco"], c["conta"],
                                       c["empresa"], texto),
                               tags=widgets.linha_zebrada(i, estado))
        self._contar()
        if not contas:
            self._log("Nenhuma conta no cadastro. Rode a sincronização ou "
                      "confira o contas_sicoob.json.")

    def _clicou(self, evento):
        """Só a coluna da marca alterna; clique no resto seleciona a linha.

        Devolver "break" no cabeçalho mataria o `command` da coluna, porque a
        ligação do widget corre ANTES da ligação de classe que dispara o
        comando do cabeçalho — a marca de todas simplesmente não responderia
        ao clique."""
        if self.tabela.identify_region(evento.x, evento.y) != "cell":
            return None
        if self.tabela.identify_column(evento.x) != "#1":
            return None
        chave = self.tabela.identify_row(evento.y)
        if chave in self.linhas:
            self._marcar_conta(chave, not self.linhas[chave]["marcada"])
        return "break"

    def _marcar_conta(self, chave: str, ligada: bool):
        self.linhas[chave]["marcada"] = ligada
        try:
            self.tabela.set(chave, "marca", MARCADA if ligada else DESMARCADA)
        except tk.TclError:
            pass
        self._contar()

    def _todas(self, ligadas: bool):
        for chave in self.linhas:
            self._marcar_conta(chave, ligadas)

    def _alternar_todas(self):
        """Tudo marcado vira nada marcado; qualquer outra coisa vira tudo.

        É como o cabeçalho de uma tabela de seleção se comporta em toda parte:
        o clique responde ao que está na tela, sem terceiro estado."""
        self._todas(not all(c["marcada"] for c in self.linhas.values()))

    def _contar(self):
        """O rodapé conta o que VAI ser feito, não o que existe.

        Com 13 contas e 3 com movimento, o número que importa é o que a pessoa
        acabou de escolher — é ele que diz quantos logins ela vai fazer."""
        marcadas = [c for c in self.linhas.values() if c["marcada"]]
        sicoob = sum(1 for c in marcadas if c["banco"] == "Sicoob")
        inter = len(marcadas) - sicoob
        logins = (1 if sicoob else 0) + inter
        self.rodape.definir(
            texto=f"{len(marcadas)} de {len(self.linhas)} marcadas · "
                  f"{sicoob} Sicoob + {inter} Inter · {logins} login(s)")
        # Duas marcas, e não três: o cabeçalho diz o que o clique VAI fazer, e
        # o rodapé já diz quantas estão marcadas. Um símbolo de "algumas"
        # ocuparia o lugar da informação sem acrescentar nenhuma.
        todas = bool(self.linhas) and len(marcadas) == len(self.linhas)
        self.tabela.heading("marca", text=MARCADA if todas else DESMARCADA)

    def _contas_do_cadastro(self) -> list[dict]:
        """As contas que a fila vai percorrer, na ordem em que serão feitas.

        Sicoob primeiro, e não por gosto: um login resolve todas elas."""
        mapa = self._obter_mapa() if self._obter_mapa else None
        if mapa is None:
            return []
        contas = []
        for emp in getattr(mapa, "empresas", []):
            for conta in getattr(emp, "contas", []):
                contas.append({"banco": "Sicoob", "conta": conta.numero,
                               "empresa": emp.nome, "pasta": conta.pasta})
        # O Inter vem DEPOIS, e a lista dele é declarada: lá cada conta é um
        # login, então ninguém tem como enumerá-las — diferente do Sicoob, onde
        # basta entrar e perguntar.
        for c in contas_inter.carregar():
            contas.append({"banco": "Inter", "conta": c.apelido,
                           "empresa": c.empresa, "pasta": c.pasta})
        return contas

    # ------------------------------------------------------------ execução
    def _comecar(self):
        if self.worker and not self.worker.done():
            return
        destino = self.v_pasta.get().strip()
        if not destino:
            self._log("[!] escolha onde salvar antes de começar.")
            return
        if not any(c["marcada"] for c in self.linhas.values()):
            self._log("[!] marque ao menos uma conta.")
            return
        pasta = pasta_da_rodada(destino)
        try:
            pasta.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._log(f"[!] não consegui criar {pasta}: {e}")
            return
        self.b_ir.configure(state="disabled")
        self.lbl.configure(text="Preparando…")
        self._log(f"Os comprovantes vão para {pasta}")
        alvo = threading.Thread(target=self._trabalhar,
                                args=(self.v_ini.get(), self.v_fim.get(),
                                      pasta), daemon=True)
        alvo.start()
        self.worker = _Tarefa(alvo)

    def _trabalhar(self, inicio: str, fim: str, destino: Path):
        """Roda fora da thread da tela. Só fala com ela pela fila."""
        try:
            from baixar_comprovantes import ja_baixados
            from baixar_comprovantes import sicoob_baixar as sicoob

            # Um registro para o lote inteiro, na raiz da pasta de
            # comprovantes: a pergunta atravessa as rodadas e os bancos.
            registro = ja_baixados.Registro(destino.parent)
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                                   / "extratos_sicoob"))
            from sicoob_client import SicoobClient

            do_sicoob = [c for c in self.linhas.values()
                         if c["banco"] == "Sicoob" and c["marcada"]]
            if do_sicoob:
                self.q.put(("log", "Sicoob: um login para "
                                   f"{len(do_sicoob)} conta(s)."))
                for c in do_sicoob:
                    self.q.put(("situacao", (f"Sicoob:{c['conta']}", "qr", {})))
                with SicoobClient(log=lambda m: self.q.put(("log", m))) as cli:
                    cli.aguardar_login()
                    for i, c in enumerate(do_sicoob, start=1):
                        chave = f"Sicoob:{c['conta']}"
                        self.q.put(("situacao", (chave, "trabalhando", {})))
                        self.q.put(("progresso", (i, len(do_sicoob))))
                        r = sicoob.baixar_conta(
                            cli, c["conta"], inicio, fim, destino,
                            log=lambda m: self.q.put(("log", m)),
                            registro=registro)
                        if not r.ok:
                            self.q.put(("situacao",
                                        (chave, "erro", {"motivo": r.motivo})))
                        elif not r.baixados:
                            self.q.put(("situacao", (chave, "vazio", {})))
                        else:
                            self.q.put(("situacao", (chave, "ok",
                                                     {"n": len(r.baixados)})))
                registro.gravar()
            self._fazer_inter(inicio, fim, destino)
            self.q.put(("fim", None))
        except Exception as e:                               # noqa: BLE001
            self.q.put(("log", f"[!] {e}"))
            self.q.put(("fim", None))

    def _fazer_inter(self, inicio: str, fim: str, destino: Path):
        """Uma conta, um login, uma leitura de QR — nessa ordem, uma de cada vez.

        Não dá para adiantar: o Inter pede o código a cada abertura, e duas
        janelas no mesmo perfil se atrapalham. Então a linha da vez vira
        "aguardando login" e só ela; as outras seguem esperando, para quem está
        com o celular na mão saber de qual conta é o QR na tela."""
        from baixar_comprovantes import inter_baixar as inter

        do_inter = [c for c in self.linhas.values()
                    if c["banco"] == "Inter" and c["marcada"]]
        if not do_inter:
            return
        self.q.put(("log", f"Inter: {len(do_inter)} conta(s), um login cada."))
        for i, c in enumerate(do_inter, start=1):
            chave = f"Inter:{c['conta']}"
            self.q.put(("situacao", (chave, "qr", {})))
            self.q.put(("progresso", (i, len(do_inter))))
            self.q.put(("log", f"\nInter — {c['conta']}: escaneie o QR."))
            r = inter.baixar(c["conta"], inicio, fim, destino,
                             log=lambda m: self.q.put(("log", m)))
            if not r.ok:
                self.q.put(("situacao", (chave, "erro", {"motivo": r.motivo})))
            elif not r.baixados:
                self.q.put(("situacao", (chave, "vazio", {})))
            else:
                self.q.put(("situacao",
                            (chave, "ok", {"n": len(r.baixados)})))

    # ------------------------------------------------------- a tela reage
    def _drenar(self):
        try:
            while True:
                tipo, valor = self.q.get_nowait()
                if tipo == "log":
                    self._log(str(valor))
                elif tipo == "situacao":
                    chave, estado, dados = valor
                    self._marcar(chave, estado, dados)
                elif tipo == "progresso":
                    feitas, total = valor
                    self.lbl.configure(text=f"{feitas} de {total}")
                    self.pb.configure(maximum=total, value=feitas)
                elif tipo == "fim":
                    self.b_ir.configure(state="normal")
                    self.lbl.configure(text="Pronto.")
        except queue.Empty:
            pass
        self.after(150, self._drenar)

    def _marcar(self, chave: str, estado: str, dados: dict):
        if chave not in self.linhas:
            return
        modelo, cor = SITUACOES.get(estado, SITUACOES["espera"])
        try:
            self.tabela.set(chave, "situacao", modelo.format(**dados))
            indice = self.tabela.index(chave)
            self.tabela.item(chave, tags=widgets.linha_zebrada(indice, cor))
        except tk.TclError:
            pass

    def _log(self, texto: str):
        try:
            self.log.insert("end", texto.rstrip() + "\n")
            self.log.see("end")
            widgets.colorir_registro(self.log)
        except tk.TclError:
            pass

    def aplicar_cores(self, escuro: bool):
        try:
            widgets.estilo_log(self.log, escuro)
        except tk.TclError:
            pass


class _Tarefa:
    """Casca com a API mínima que o frame usa do executor das outras abas."""

    def __init__(self, thread):
        self._thread = thread

    def done(self) -> bool:
        return not self._thread.is_alive()
