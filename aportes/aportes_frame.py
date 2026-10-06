# -*- coding: utf-8 -*-
"""
Aba "Aportes": lança aportes e distribuições direto no Mais Controle.

Compartilha o navegador e a thread do AnexarFrame — o Playwright síncrono só
aceita uma thread, e abrir um segundo Chrome significaria um segundo login.
É o mesmo arranjo que a Conferência já usa.
"""
from __future__ import annotations

import datetime
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk


from . import dados as cadastro
from . import novo_cadastro
from . import rateio_subconta
from . import regras
from .mc_catalogos import Catalogos, ErpRecusou
from .mc_lancamentos import criar_pagamento, criar_recebimento, ErroLancamento
from . import erp_sessao
from .erp_sessao import ouvinte
from .regras import (Operacao, expandir, ler_valor_brl,
                     numero_subconta)

import util
import widgets

#: A medida de layout que segue a fonte. `px(14)` são "os 14 px de quem
#: desenhou esta tela a 100%", ditos na escala de hoje — a 150% saem 21, e
#: a 100% saem os mesmos 14. Ver o bloco do `px` no `widgets.py`.
px = widgets.px

CampoData = widgets.CampoData

URL_PAGAMENTOS = "https://acessar.maiscontroleerp.com.br/#/payable-installments"


class AutenticacaoNaoCapturada(RuntimeError):
    """A página não fez as chamadas de que a captura da autenticação precisa —
    em geral porque a sessão caiu e ela foi para a tela de login."""


class AportesFrame(ttk.Frame):
    def __init__(self, master, anexar_frame):
        super().__init__(master, padding=12)
        self.anx = anexar_frame          # dono do navegador e da thread
        # Mesma bomba de UI das outras cinco abas: a thread do navegador só
        # empilha aqui e QUEM mexe no Tk é o _drain, na thread da interface.
        # Escrever no Text direto da thread do navegador travava a aba.
        self.q = queue.Queue()
        self._recarga_pendente = False
        self.operacoes: list[Operacao] = []
        # Para cada operação, os ÍNDICES dos lançamentos que já entraram no ERP.
        # Sem isso, tentar de novo depois de uma falha parcial recria o que deu
        # certo — e aporte duplicado é dinheiro duplicado, desfeito à mão.
        self.criados: list[set[int]] = []
        self.catalogos: Catalogos | None = None
        self._cabecalhos: dict = {}

        self.entidades = cadastro.carregar_contas()
        self.subcontas = cadastro.carregar_subcontas()
        self.obra_padrao = cadastro.config_obra_padrao()

        self._montar()
        self._recarregar_listas()
        self.after(150, self._drain)

    # ------------------------------------------------------------ interface
    def _montar(self):
        PADX = px(widgets.PADX)

        cab = widgets.Cabecalho(
            self, "Aportes e Distribuições",
            "Lança direto no Mais Controle — sem planilha, sem importação.",
            trilha="Comprovantes  ›  Aportes")
        cab.pack(fill="x", padx=PADX, pady=px((16, 12)))
        # O meio da tela rola quando não cabe (ver `widgets.AreaRolavel`).
        corpo = widgets.AreaRolavel(self)
        self.b_conferir = widgets.Botao(cab.acoes, "Conferir cadastro",
                                        papel="passo", command=self._conferir)
        self.b_conferir.pack(side="left", padx=px((0, 8)))
        # Obra nova no ERP = alguém que manda e uma conta que recebe aporte.
        # Antes era SQL no painel; ver `novo_cadastro.py`.
        self.b_novo = widgets.Botao(cab.acoes, "+  Novo cadastro",
                                    papel="passo", command=self._novo_cadastro)
        self.b_novo.pack(side="left", padx=px((0, 8)))
        self.b_lancar = widgets.Botao(cab.acoes, "Lançar no Mais Controle",
                                      papel="acao", command=self._lancar)
        self.b_lancar.pack(side="left")

        form = widgets.Cartao(corpo, "Novo lançamento", 1)
        form.pack(fill="x", padx=PADX, pady=px((0, 12)))

        # Rótulo EM CIMA de cada campo, e não ao lado: com o rótulo à esquerda
        # cada linha do formulário começava numa coluna diferente (a largura do
        # rótulo mandava), e "Data", "Pagou" e "Tipo" nunca se alinhavam.
        linha1 = ttk.Frame(form)
        linha1.pack(fill="x")
        self.var_data = tk.StringVar(value=f"{datetime.date.today():%d/%m/%Y}")
        widgets.Campo(linha1, "Data", lambda p: CampoData(p, self.var_data)
                      ).pack(side="left", padx=px((0, 16)))
        self.var_valor = tk.StringVar()
        widgets.Campo(linha1, "Valor R$",
                      lambda p: ttk.Entry(p, textvariable=self.var_valor,
                                          width=14)).pack(side="left")

        # São ~19 contas e ~440 participantes: rolar a lista até achar
        # "Morais Participações - SUBCONTA 55696-3" é trabalho que a máquina
        # faz melhor. Digitar no PRÓPRIO campo filtra a lista dele.
        linha2 = ttk.Frame(form)
        linha2.pack(fill="x", pady=px((12, 0)))
        campo_pag = widgets.Campo(
            linha2, "Pagou", lambda p: widgets.ComboBusca(p, width=38))
        campo_pag.pack(side="left", padx=px((0, 16)))
        self.cb_pagador = campo_pag.widget
        self.cb_pagador.bind("<<ComboboxSelected>>", self._pagador_escolhido,
                             add="+")
        self.cb_pagador.bind("<FocusOut>", self._pagador_escolhido, add="+")
        campo_rec = widgets.Campo(
            linha2, "Recebeu", lambda p: widgets.ComboBusca(p, width=38))
        campo_rec.pack(side="left")
        self.cb_recebedor = campo_rec.widget

        linha3 = ttk.Frame(form)
        linha3.pack(fill="x", pady=px((12, 0)))
        for rotulo, atributo, largura, valores in (
                ("Tipo", "cb_tipo", 22, cadastro.TIPOS),
                ("Lançar", "cb_modo", 24, cadastro.MODOS),
                ("Forma", "cb_forma", 20, cadastro.FORMAS)):
            campo = widgets.Campo(linha3, rotulo, lambda p, l=largura, v=valores:
                                  ttk.Combobox(p, state="readonly", width=l,
                                               values=v))
            campo.pack(side="left", padx=px((0, 16)))
            campo.widget.current(0)
            setattr(self, atributo, campo.widget)

        ttk.Label(form, style="Tenue.TLabel", wraplength=px(760),
                  justify="left",
                  text="Em Pagou e Recebeu, digite para procurar — sem acento e "
                       "por pedaço do nome (\"696\", \"livia\"). A seta abre a "
                       "lista já filtrada."
                  ).pack(anchor="w", pady=px((10, 0)))

        # É esta que o Enter dispara, e não "Lançar no Mais Controle": num
        # formulário que monta uma lista, Enter fecha a LINHA. Mandar dinheiro
        # para o ERP continua exigindo o clique nos botões do alto.
        self.acao_enter = widgets.Botao(form, "+   Adicionar à lista",
                                        papel="passo", command=self._adicionar)
        self.acao_enter.pack(anchor="w", pady=px((12, 0)))

        lista = widgets.Cartao(corpo, "A lançar", 2)
        lista.pack(fill="both", expand=True, padx=PADX, pady=px((0, 12)))
        self.rodape = widgets.RodapeTabela(lista.acoes)
        self.rodape.pack()
        self.rodape.link("Remover selecionado", self._remover)
        self.rodape.link("Limpar tudo", self._limpar)
        grade = ttk.Frame(lista)
        grade.pack(fill="both", expand=True)
        self.tabela = ttk.Treeview(grade, columns=("op",), show="headings",
                                   height=7)
        self.tabela.heading("op", text="OPERAÇÃO")
        self.tabela.column("op", width=760, anchor="w")
        widgets.estilo_tabela(self.tabela)
        self.tabela.pack(fill="both", expand=True, side="left")
        ttk.Scrollbar(grade, orient="vertical", command=self.tabela.yview
                      ).pack(side="right", fill="y")
        # O total continua existindo, agora no rodapé do cartão — que é onde
        # ele fica em todas as outras telas desde o redesenho.
        self.lbl_total = self.rodape.resumo

        # O Registro ganhou cartão, como nas outras abas: é o cartão que
        # leva a alça, o "Ampliar" e o "Copiar" (ver `registro_elastico`).
        self.reg = widgets.Cartao(self, "Registro", padding=(12, 10))
        self.reg.pack(fill="x", padx=PADX, pady=px((0, 12)))
        self.texto = tk.Text(self.reg, wrap="word", relief="flat",
                             borderwidth=0, highlightthickness=0)
        self.texto.pack(fill="both", expand=True)
        widgets.estilo_log(self.texto)
        widgets.registro_elastico(self.reg, self.texto)
        corpo.encaixar(self.reg)

    def _pagador_escolhido(self, _ev=None):
        """Escolheu "INVESTIDOR SUBCONTA 00000-0" em Pagou: o tipo vira
        "Aporte de Investidor", o modo "Só recebimento", e Recebeu, a conta
        dessa subconta — os três únicos valores que esse pagador aceita."""
        numero = numero_subconta(self.cb_pagador.get().strip(), self.subcontas)
        if numero is None:
            # Saiu de um investidor para outro pagador: o tipo que ele pôs
            # não gruda — "Aporte de Investidor" com empresa da casa deixaria
            # a saída dela fora do ERP.
            if self.cb_tipo.get() == regras.TIPO_INVESTIDOR:
                self.cb_tipo.set(cadastro.TIPOS[0])
                self.cb_modo.set(cadastro.MODOS[0])
            return
        self.cb_tipo.set(regras.TIPO_INVESTIDOR)
        self.cb_modo.set("Só recebimento")
        # Só com UM candidato pelo número exato; dois ou nenhum, a pessoa
        # escolhe — chute aqui seria aporte na conta errada.
        candidatos = [nome for nome, dados in self.entidades.items()
                      if regras.e_da_subconta(nome, dados, numero)]
        if len(candidatos) == 1:
            self.cb_recebedor.set(candidatos[0])

    def _recarregar_listas(self):
        nomes = list(self.entidades)
        pagadores = nomes + [cadastro.INVESTIDOR_PREFIXO + n
                             for n in self.subcontas if not n.startswith("_")]
        # Quem guarda a lista completa é o próprio combo: é dela que ele parte
        # a cada tecla, senão um filtro comeria o resultado do anterior.
        self.cb_pagador.definir_valores(pagadores)
        self.cb_recebedor.definir_valores(nomes)
        if pagadores:
            self.cb_pagador.current(0)
        if len(nomes) > 1:
            self.cb_recebedor.current(1)
        if not nomes:
            self._log("Nenhuma conta cadastrada. Crie o arquivo contas.csv "
                      f"em {cadastro.ARQUIVO_CONTAS}")

    def _log(self, msg=""):
        """Pode ser chamado de QUALQUER thread: só enfileira."""
        self.q.put(str(msg))

    def _drain(self):
        try:
            while True:
                msg = self.q.get_nowait()
                self.texto.insert("end", f"{msg}\n")
                self.texto.see("end")
        except queue.Empty:
            pass
        except Exception:
            pass                     # a bomba de UI nunca pode morrer
        try:
            # Recarga que ficou esperando o comando terminar: o `_drain` roda
            # na thread do Tk e é o único laço que vê o fim de QUALQUER comando
            # desta aba (conferir, lançar, novo cadastro).
            if self._recarga_pendente and self.anx.dona_ocupada() is not self:
                self._recarga_pendente = False
                self._recarregar_cadastros()
        except Exception:
            pass                     # a bomba de UI nunca pode morrer
        finally:
            self.after(150, self._drain)

    def aplicar_cores(self, escuro: bool):
        try:
            widgets.estilo_log(self.texto, escuro)
        except tk.TclError:
            pass

    # ------------------------------------------------------------- lista
    def _adicionar(self):
        try:
            data = datetime.datetime.strptime(self.var_data.get().strip(),
                                              "%d/%m/%Y").date()
        except ValueError:
            messagebox.showwarning("Data", "Use o formato dd/mm/aaaa.")
            return
        try:
            # Decimal, não float: este número vira lançamento no ERP. Ponto
            # sem vírgula é RECUSADO (ver `regras.ler_valor_brl`): apagar todo
            # ponto fazia "1500.50" virar R$ 150.050,00.
            valor = ler_valor_brl(self.var_valor.get())
        except ValueError as e:
            messagebox.showwarning("Valor", str(e))
            return

        op = Operacao(data=data, pagador=self.cb_pagador.get(),
                      recebedor=self.cb_recebedor.get(), valor=valor,
                      tipo=self.cb_tipo.get(), modo=self.cb_modo.get(),
                      forma=self.cb_forma.get())
        erros = op.validar(self.entidades, self.subcontas)
        if erros:
            messagebox.showwarning("Não dá para lançar assim", "\n".join(erros))
            return
        self.operacoes.append(op)
        self.criados.append(set())
        self.tabela.insert("", "end", values=(op.resumo(),))
        self.var_valor.set("")
        self._atualizar_total()

    def _remover(self):
        # De trás para frente: apagar pelo índice desloca os seguintes.
        for item in sorted(self.tabela.selection(),
                           key=self.tabela.index, reverse=True):
            indice = self.tabela.index(item)
            self.tabela.delete(item)
            del self.operacoes[indice]
            del self.criados[indice]
        self._atualizar_total()

    def _limpar(self):
        self.tabela.delete(*self.tabela.get_children())
        self.operacoes.clear()
        self.criados.clear()
        self._atualizar_total()

    def _retirar_concluidas(self):
        """Tira da fila as operações cujos lançamentos TODOS entraram no ERP.

        Roda na thread da interface. O que falhou fica para nova tentativa; o
        que já foi criado sai da lista, senão o próximo clique em Lançar
        recriaria o mesmo aporte."""
        sobrou_ops, sobrou_criados, concluidas = [], [], 0
        for op, feitos in zip(self.operacoes, self.criados):
            total = len(expandir(op, self.entidades, self.subcontas,
                                 self.obra_padrao))
            if total and len(feitos) >= total:
                concluidas += 1
                continue
            sobrou_ops.append(op)
            sobrou_criados.append(feitos)

        if concluidas:
            self.operacoes[:] = sobrou_ops
            self.criados[:] = sobrou_criados
            self.tabela.delete(*self.tabela.get_children())
            for op in self.operacoes:
                self.tabela.insert("", "end", values=(op.resumo(),))
            self._atualizar_total()
            self._log(f"{concluidas} operação(ões) concluída(s) saíram da lista.")
        if self.operacoes:
            self._log("O que sobrou ainda NÃO foi criado — corrija o cadastro e "
                      "clique em Lançar de novo; o que já entrou será pulado.")

    def _atualizar_total(self):
        total = sum(o.valor for o in self.operacoes)
        # Conta os lançamentos que realmente vão para o ERP: uma operação pode
        # virar dois, e o rateio vira vários. É esse número que tem que bater
        # com o que aparece no Mais Controle depois.
        n = sum(len(expandir(o, self.entidades, self.subcontas,
                             self.obra_padrao)) for o in self.operacoes)
        self.lbl_total.configure(
            text=f"{len(self.operacoes)} operação(ões) · {n} lançamento(s) · "
                 f"{widgets.brl(total)}")

    # --------------------------------------------------------- Mais Controle
    def _preparar_sessao(self, recarregar: bool = False):
        """Roda NA THREAD do navegador. Garante login e catálogos.

        Os cadastros são lidos UMA vez por sessão. Reler a cada botão custava
        centenas de idas ao servidor (são ~440 participantes) e era o que
        deixava a tela parada — os cadastros não mudam no meio do trabalho.

        **Leitura pela metade nunca fica guardada** (06/10/2026). O ERP aceita
        UMA sessão por usuário, e um login feito por fora — o do próprio app na
        abertura, no "Atualizar contas" ou na coleta dos saldos — cancela o
        token curto do legacy-api do Chrome, enquanto o JWT do prod-erp-api
        continua valendo. A leitura vinha com contas e participantes e parava
        num 401 nas categorias; o objeto já estava em `self.catalogos`, então o
        "Lançar" seguinte usava categorias e naturezas VAZIAS e acusava
        "Nada parecido no cadastro" para cadastros que existiam. Agora a leitura
        só é guardada inteira, e o 401 do legado leva a UM novo login e UMA
        releitura — o `garantir_login` recarrega a página, que cai no login
        quando o token foi cancelado (provado ao vivo, ver
        tests/test_aportes_cadastro_401.py)."""
        api = self.anx.garantir_sessao(self._log)
        if self.catalogos is not None and not recarregar:
            return
        self.catalogos = None
        try:
            catalogos = self._ler_cadastros()
        except (ErpRecusou, AutenticacaoNaoCapturada) as e:
            # As duas caras da MESMA situação — a sessão do Chrome cancelada por
            # um login feito por fora: com o token velho ainda guardado, a
            # leitura toma 401; sem ele, a página recarregada cai no login e
            # nem faz as chamadas que a captura espera (visto ao vivo em
            # 06/10/2026, depois do primeiro conserto). Outra recusa sobe.
            if isinstance(e, ErpRecusou) and e.status != 401:
                raise
            self._log("A sessão do Chrome no Mais Controle caiu (houve outro "
                      "login no ERP) — entrando de novo e relendo os "
                      "cadastros...")
            if not self.anx.mc.garantir_login():
                raise
            catalogos = self._ler_cadastros()
        self.catalogos = catalogos
        self._carregar_obras(api)

    def _ler_cadastros(self) -> Catalogos:
        """Captura a autenticação da página e lê os cadastros. Levanta se não
        der — e não grava nada em `self.catalogos`: quem decide é
        `_preparar_sessao`.

        A captura começa SEM o token velho dos hosts de cadastro. A espera
        termina quando todos estão capturados, e com o de antes ainda no
        dicionário ela terminava na hora — a releitura depois de um novo login
        usaria o mesmo token cancelado que provocou o 401."""
        for host in erp_sessao.HOSTS_CADASTRO:
            self._cabecalhos.pop(host, None)
        pagina = self.anx.mc.page
        alvos = erp_sessao.HOSTS_CADASTRO

        # A página é COMPARTILHADA com as outras abas: dizer que vamos navegar
        # evita a surpresa de ver o Chrome sair da tela onde estava.
        self._log("Passando pela tela de Pagamentos para o ERP autenticar os "
                  "serviços de cadastro...")

        ao_requisitar = ouvinte(self._cabecalhos)
        pagina.on("request", ao_requisitar)
        try:
            # `goto` para a MESMA URL não dispara requisição nenhuma: o ERP é
            # single-spa e trocar só o "#" é navegação de cliente. Como as
            # outras abas deixam o Chrome justamente nesta tela, o listener
            # ficava 15 s esperando chamadas que nunca sairiam — e a aba
            # morria com "não consegui a autenticação" logo depois de você ter
            # usado o Anexar. Recarregar força o bootstrap e as chamadas saem.
            # A tela de UM lançamento também tem "payable-installments" no
            # endereço, e recarregar ELA não dispara as chamadas de cadastro.
            # Como a busca das obras abre um lançamento para capturar o outro
            # back-end, a página costuma ficar parada justamente ali.
            if erp_sessao.na_lista_de_pagamentos(pagina.url):
                pagina.reload(wait_until="domcontentloaded")
            else:
                pagina.goto(URL_PAGAMENTOS, wait_until="domcontentloaded")
            # Espera TODOS os hosts de cadastro, e não só o primeiro:
            # normalmente chegam em 1 ou 2 segundos. Sair na primeira captura
            # era o que deixava o legacy-api de fora.
            for _ in range(60):
                if all(a in self._cabecalhos for a in alvos):
                    break
                pagina.wait_for_timeout(250)
        finally:
            # Sem remover, o listener segue pendurado na página compartilhada e
            # roda em TODA requisição das outras abas, para sempre.
            try:
                pagina.remove_listener("request", ao_requisitar)
            except Exception:
                pass

        faltando = [a for a in alvos if a not in self._cabecalhos]
        if faltando:
            # Parar aqui, e não seguir com metade: sem o legacy-api o cadastro
            # vem pela metade (401 nas categorias) E o lançamento morre depois
            # em "não achei o usuário responsável", que não diz o que houve.
            raise AutenticacaoNaoCapturada(
                "não consegui a autenticação de " + ", ".join(faltando) + ".\n"
                "Abra a LISTA de Pagamentos na janela do Chrome (ou recarregue-a "
                "com F5) e tente de novo.")

        catalogos = Catalogos(pagina, self._cabecalhos, self._log)
        self._log("Lendo os cadastros do Mais Controle:")
        catalogos.carregar()
        return catalogos

    def _carregar_obras(self, api):
        """As obras saem do REST, pela mesma porta da aba Contratos.

        O caminho antigo era GraphQL, e o host dele (`execute-api`) só entra
        nos cabeçalhos quando o ERP carrega o FORMULÁRIO de lançamento. Esta
        aba passa pela tela de PAGAMENTOS, que nunca chama o GraphQL — então
        `obras` vinha 0 e todo lançamento falhava com "Obra não encontrado.
        Nada parecido no cadastro — talvez precise ser criado lá", mandando
        procurar no ERP um cadastro que está lá, certo, o tempo todo.

        `garantir_credenciais_anexos` é quem sabe achar a credencial do outro
        back-end sem ter um lançamento na mão — ela procura a isca sozinha.
        """
        try:
            api.garantir_credenciais_anexos(self._log)
            self.catalogos.definir_obras(api.listar_obras(self._log))
        except Exception as e:                              # noqa: BLE001
            # Sem obras o lançamento não sai, mas o resto do cadastro serve
            # para conferir — e o motivo tem de aparecer, senão vira de novo
            # um "obras: 0" sem explicação.
            self.catalogos.definir_obras([])
            self._log(f"  aviso (obras): {e}")

    def recarregar_contas(self):
        """Gancho do "Atualizar contas" do menu: relê o cadastro local.

        Com um comando desta aba no navegador (conferir, lançar) não relê:
        `_recarregar_cadastros` zera os catálogos do ERP que ele está usando."""
        if self.anx.dona_ocupada() is self:
            if not self._recarga_pendente:
                self._log("As contas novas entram nos Aportes quando o "
                          "comando atual terminar.")
            self._recarga_pendente = True     # o `_drain` refaz ao terminar
            return
        self._recarga_pendente = False
        self._recarregar_cadastros()

    def _recarregar_cadastros(self):
        """Relê contas.csv e os cadastros do ERP. Para quando algo foi criado
        no Mais Controle com o app já aberto."""
        self.entidades = cadastro.carregar_contas()
        self.subcontas = cadastro.carregar_subcontas()
        self.obra_padrao = cadastro.config_obra_padrao()
        self._recarregar_listas()
        self.catalogos = None
        self._log("Cadastros locais relidos; os do ERP serão relidos no "
                  "próximo comando.")

    def _novo_cadastro(self):
        """Abre a janela única de cadastro (investidor / conta / pessoa).

        Lê, na thread do navegador: os aportadores e as obras do Mais
        Controle (a opção de investidor só escolhe nomes que o ERP conhece)
        e, da nuvem, conta, entidade e rateios FRESCOS — o motivo de clicar
        aqui costuma ser a conta que entrou hoje, e o cache só é regravado
        na abertura. Sem o ERP a janela abre do mesmo jeito, com a opção de
        investidor desligada."""
        if self.anx.avisar_se_ocupado("os Aportes"):
            return
        self.b_novo.configure(state="disabled")
        self.anx.submeter("Aportes — novo cadastro", self._t_novo_cadastro,
                          dona=self)

    def _t_novo_cadastro(self):
        participantes = centros = None
        try:
            # `_preparar_sessao` não navega quando os catálogos já foram
            # lidos nesta sessão (Conferir, Lançar ou um cadastro anterior).
            self._preparar_sessao()
            participantes = sorted(
                {p.get("name", "").strip()
                 for p in self.catalogos.participantes.values()} - {""},
                key=util.norm_espaco)
            centros = sorted(
                {o.get("name", "").strip()
                 for o in getattr(self.catalogos, "obras", {}).values()} - {""},
                key=util.norm_espaco) or None
        except Exception as e:                              # noqa: BLE001
            self._log(f"  aviso: aportadores e obras do Mais Controle não "
                      f"vieram ({e}); a opção de investidor fica desligada.")
            participantes = centros = None
        try:
            from nuvem import sessao
            token = sessao.token()
            contas, entidades = novo_cadastro.ler(token)
            rateios = rateio_subconta.ler_rateios(token)
        except Exception as e:                              # noqa: BLE001
            self._log(f"[!] Não deu para ler o cadastro da nuvem: {e}")
            self.after(0, lambda: self.b_novo.configure(state="normal"))
            return
        self.after(0, lambda: self._perguntar_novo(
            token, contas, entidades, rateios, participantes, centros))

    def _no_fundo(self, tarefa, depois, falhou: str, ao_fim=None,
                  titulo: str = "Novo cadastro"):
        """Roda `tarefa` numa thread e entrega o resultado a `depois` na
        thread do Tk. Erro vira janela com `falhou`."""
        resposta: queue.Queue = queue.Queue()

        def rodar():
            try:
                resposta.put(("ok", tarefa()))
            except Exception as e:                          # noqa: BLE001
                resposta.put(("erro", e))

        def esperar():
            try:
                tipo, valor = resposta.get_nowait()
            except queue.Empty:
                self.after(100, esperar)
                return
            if ao_fim:
                ao_fim()
            if tipo == "erro":
                self._log(f"[!] {falhou} {valor}")
                messagebox.showerror(titulo,
                                     widgets.recado_de_erro(valor, falhou))
                return
            depois(valor)

        threading.Thread(target=rodar, daemon=True).start()
        self.after(100, esperar)

    def _perguntar_novo(self, token, contas, entidades, rateios,
                        participantes, centros):
        from .novo_cadastro_dialogo import perguntar
        self.b_novo.configure(state="normal")
        r = perguntar(self.winfo_toplevel(), contas, entidades, rateios,
                      participantes, centros)
        if r is None:
            return
        tipo, dados = r
        if tipo == "investidor":
            self._gravar_investidor(token, dados, entidades)
            return
        self.b_novo.configure(state="disabled")
        self._no_fundo(lambda: novo_cadastro.gravar(token, dados),
                       lambda _r: self._cadastrou(dados),
                       "Não deu para cadastrar. Se o recado for de nome "
                       "repetido, ele já entrou: clique em Recarregar "
                       "cadastros.",
                       ao_fim=lambda: self.b_novo.configure(state="normal"))

    def _gravar_investidor(self, token, inv, entidades):
        if self._subconta_em_andamento(inv.numero):
            messagebox.showwarning(
                "Novo cadastro",
                f"A lista \"A lançar\" tem um aporte da subconta {inv.numero} "
                "que já entrou em parte no Mais Controle.\n\nTermine esse "
                "lançamento (ou tire-o da lista) antes de mudar o rateio — "
                "senão o que falta seria redividido e lançaria valor a mais.")
            return

        def gravou(criou):
            pagou, recebeu = self.cb_pagador.get(), self.cb_recebedor.get()
            self.entidades = cadastro.carregar_contas()
            self.subcontas = cadastro.carregar_subcontas()
            self._recarregar_listas()
            for combo, antes in ((self.cb_pagador, pagou),
                                 (self.cb_recebedor, recebeu)):
                if antes in combo.valores_completos():
                    combo.set(antes)
            self._atualizar_total()
            pcts = regras.percentuais_dos_pesos(inv.aportadores, inv.pesos)
            self._log(
                f"Subconta de investidor {inv.numero} gravada"
                + (" (conta nova em Recebeu)" if criou else "") + ": "
                + ", ".join(f"{a} {str(p).replace('.', ',')}%"
                            for a, p in zip(inv.aportadores, pcts))
                + f"; {len(inv.obras)} obra(s), partes iguais. Para lançar: "
                f"Pagou \"{inv.em_pagou}\", tipo '{regras.TIPO_INVESTIDOR}', "
                "modo 'Só recebimento'.")
            widgets.registrar_atividade(
                "apt", "Subconta de investidor", "ok", inv.numero,
                {"aportadores": len(inv.aportadores), "obras": len(inv.obras)})

        def ao_fim():
            # Deu certo ou não, o cache já tem o que o banco tem.
            self.entidades = cadastro.carregar_contas()
            self.subcontas = cadastro.carregar_subcontas()
            self.b_novo.configure(state="normal")

        self.b_novo.configure(state="disabled")
        self._no_fundo(
            lambda: novo_cadastro.gravar_investidor(token, inv, entidades),
            gravou, "Não deu para gravar a subconta de investidor.",
            ao_fim=ao_fim, titulo="Novo cadastro")

    def _cadastrou(self, novo):
        # A escolha de Pagou/Recebeu sobrevive: `_recarregar_listas` põe o
        # 1º e o 2º nomes, e quem já tinha escolhido as contas e só parou
        # para cadastrar um nome adicionaria a operação entre as erradas.
        pagou, recebeu = self.cb_pagador.get(), self.cb_recebedor.get()
        # Só a lista: `_recarregar_cadastros` zeraria os catálogos do ERP à
        # toa, e a lista "A lançar" continua intacta.
        self.entidades = cadastro.carregar_contas()
        self._recarregar_listas()
        for combo, antes in ((self.cb_pagador, pagou),
                             (self.cb_recebedor, recebeu)):
            if antes in combo.valores_completos():
                combo.set(antes)
        self._log(f"Cadastrado: {novo.nome_exibicao.strip()} — contato "
                  f"\"{novo.nome_oficial.strip()}\""
                  + (f", conta \"{novo.conta.strip()}\"" if novo.conta.strip()
                     else " (sem conta)")
                  + ". Já está em Pagou/Recebeu. Clique em Conferir cadastro "
                    "para ver se os nomes batem com o Mais Controle.")
        widgets.registrar_atividade(
            "apt", "Novo cadastro", "ok", novo.nome_exibicao.strip(),
            {"conta": novo.conta.strip() or None})

    def _subconta_em_andamento(self, numero: str) -> bool:
        """Há na lista um aporte desta subconta lançado pela METADE?

        `criados` guarda a POSIÇÃO de cada item do rateio, não o par (CC ×
        investidor). Trocar o rateio no meio muda o que cada posição quer
        dizer: o próximo Lançar pularia um par nunca criado e criaria outros
        com o valor redividido — dinheiro a mais no ERP."""
        for op, feitos in zip(self.operacoes, self.criados):
            if feitos and numero_subconta(op.pagador, {numero: {}}) == numero:
                return True
        return False

    def _conferir(self):
        if self.anx.avisar_se_ocupado("os Aportes"):
            return
        self.anx.submeter("Aportes — conferir cadastro", self._t_conferir,
                          dona=self)

    def _t_conferir(self):
        try:
            self._preparar_sessao()
            resultado = self.catalogos.conferir(self.entidades)
        except Exception as e:                              # noqa: BLE001
            # Roda numa thread: o que não for capturado aqui vira uma exceção
            # guardada no Future e some — a aba fica parada, sem mensagem, e
            # parece que o botão não fez nada.
            self._log(f"[!] {e}")
            if not isinstance(e, (RuntimeError, ErroLancamento)):
                import traceback
                self._log(traceback.format_exc())
            return
        self._log(f"\n{len(resultado['ok'])} de {len(self.entidades)} contas "
                  "existem no Mais Controle.")
        for item in resultado["faltando"]:
            self._log(f"  NAO ENCONTRADA: {item['nome']}")
            for p in item["problemas"]:
                self._log(f"     {p['o_que']}: \"{p['procurado']}\"")
                for parecido in p["parecidos"]:
                    self._log(f"        parecido no ERP: \"{parecido}\"")
        if not resultado["faltando"]:
            self._log("Nenhuma pendência de cadastro.")

    def _lancar(self):
        if not self.operacoes:
            messagebox.showinfo("Aportes", "A lista está vazia.")
            return
        n = sum(len(expandir(o, self.entidades, self.subcontas,
                             self.obra_padrao)) for o in self.operacoes)
        total = sum(o.valor for o in self.operacoes)
        # Confirmação explícita: daqui em diante escreve no sistema, e desfazer
        # significa apagar lançamento por lançamento na tela do ERP.
        if not messagebox.askyesno(
                "Confirmar",
                f"Criar {n} lançamento(s) no Mais Controle, "
                f"somando {widgets.brl(total)}?\n\nIsso escreve no sistema."):
            return
        if self.anx.avisar_se_ocupado("os Aportes"):
            return
        self.b_lancar.configure(state="disabled")
        self.anx.submeter("Aportes — lançar", self._t_lancar, dona=self)

    def _rateios_frescos(self):
        """Antes de montar o plano: o rateio das subcontas da lista como o
        BANCO tem agora. Outra máquina pode tê-lo mudado depois que esta
        abriu, e lançar pelo cache velho rateia pelos CCs de antes.

        Sem rede, segue com o cache (como sempre foi) e diz. Mudou num
        aporte já lançado em parte: PARA — redividir o que falta lançaria
        valor a mais (ver `_subconta_em_andamento`)."""
        numeros = {numero_subconta(op.pagador, self.subcontas)
                   for op in self.operacoes} - {None}
        if not numeros:
            return
        try:
            from nuvem import sessao
            frescos = rateio_subconta.ler_rateios(sessao.token())
        except Exception as e:                              # noqa: BLE001
            self._log(f"  aviso: não deu para conferir o rateio na nuvem "
                      f"({e}); seguindo com o desta máquina.")
            return
        for numero in sorted(numeros):
            if not rateio_subconta.mudou(self.subcontas, frescos, numero):
                continue
            if self._subconta_em_andamento(numero):
                raise RuntimeError(
                    f"o rateio da subconta {numero} mudou na nuvem depois que "
                    "parte deste aporte já tinha sido lançada. Confira no Mais "
                    "Controle o que entrou e tire a operação da lista antes de "
                    "lançar o resto.")
            self._log(f"  O rateio da subconta {numero} mudou na nuvem; "
                      "lançando pelo atual.")
            self.subcontas[numero] = frescos[numero]

    def _t_lancar(self):
        try:
            self._preparar_sessao()
            self._rateios_frescos()
            id_usuario = self.catalogos.cabecalho("user-id")
            if not id_usuario:
                raise RuntimeError("não achei o usuário responsável.")

            # Só o que AINDA não entrou no ERP. Numa segunda tentativa depois
            # de falha parcial, repetir o que deu certo duplicaria o aporte.
            plano = []                      # (i_op, i_item, item)
            pulados = 0
            for i_op, op in enumerate(self.operacoes):
                for i_item, item in enumerate(
                        expandir(op, self.entidades, self.subcontas,
                                 self.obra_padrao)):
                    if i_item in self.criados[i_op]:
                        pulados += 1
                        continue
                    plano.append((i_op, i_item, item))

            if pulados:
                self._log(f"\n{pulados} lançamento(s) já criado(s) numa tentativa "
                          "anterior — pulados para não duplicar.")
            if not plano:
                self._log("Nada a criar: tudo desta lista já foi lançado.")
                self.after(0, self._retirar_concluidas)
                return

            self._log(f"\nCriando {len(plano)} lançamento(s):")
            feitos, falhas = 0, []
            for i, (i_op, i_item, item) in enumerate(plano, 1):
                especie = item.pop("tipo_lancamento")
                try:
                    if especie == "pagamento":
                        r = criar_pagamento(self.catalogos, id_usuario=id_usuario,
                                            **item)
                    else:
                        r = criar_recebimento(self.catalogos,
                                              id_usuario=id_usuario, **item)
                except ErroLancamento as e:
                    self._log(f"  {i}/{len(plano)} FALHOU: {e}")
                    falhas.append(str(e))
                    continue
                # O que decide "não crie de novo" é EXISTIR NO ERP, não ter
                # dado tudo certo. `criar_recebimento` tem saídas em que a
                # venda JÁ FOI criada e o resultado é `ok=False` — baixa que
                # falhou, parcela que não apareceu na resposta. Marcando só
                # pelo `ok`, o clique seguinte em "Lançar" criava uma SEGUNDA
                # venda do mesmo valor, e desfazer isso é à mão, lançamento
                # por lançamento. Marca antes de qualquer outra coisa: se o
                # app morrer aqui, o pior caso é a lista sobreviver sabendo o
                # que já foi.
                if r.ok or r.id_criado:
                    self.criados[i_op].add(i_item)
                if r.ok:
                    feitos += 1
                    self._log(f"  {i}/{len(plano)} ok — {especie} "
                              f"{widgets.brl(item['valor'])}")
                elif r.id_criado:
                    # Existe no ERP e não está redondo. É diferente de falhar:
                    # relançar duplica, e ignorar deixa dinheiro em aberto.
                    self._log(f"  {i}/{len(plano)} ATENÇÃO — criado no ERP, mas "
                              f"pendente: {r.erro}")
                    falhas.append(r.erro or "criado, pendente de conferência")
                else:
                    self._log(f"  {i}/{len(plano)} FALHOU: {r.erro}")
                    falhas.append(r.erro or "erro desconhecido")

            self._log(f"\n{feitos} criado(s), {len(falhas)} com problema.")
            widgets.registrar_atividade(
                "apt", "Lançar aportes", "atencao" if falhas else "ok",
                f"{feitos} criado(s)"
                + (f" · {len(falhas)} com problema" if falhas else ""),
                {"criados": feitos, "falhas": len(falhas)})
            self.after(0, self._retirar_concluidas)
        except Exception as e:                              # noqa: BLE001
            # Ver o comentário em _t_conferir: exceção não capturada numa
            # thread some dentro do Future e a aba fica muda. Aqui é pior —
            # o usuário não saberia se algum lançamento chegou a ser criado.
            self._log(f"[!] {e}")
            if not isinstance(e, RuntimeError):
                import traceback
                self._log(traceback.format_exc())
            self._log("Confira no Mais Controle o que entrou antes do erro; a "
                      "lista guarda o que já foi criado e não repete.")
            self.after(0, self._retirar_concluidas)
        finally:
            self.after(0, lambda: self.b_lancar.configure(state="normal"))
