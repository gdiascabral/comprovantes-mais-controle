# -*- coding: utf-8 -*-
"""Quem trabalha aqui, e o que cada um alcança. Sem tela.

Este módulo é o lado do ADMIN do que a fase 2 fez para cada pessoa: lá, o app
descobre o próprio papel; aqui, quem administra vê a fila inteira e decide.

A separação entre os dois não é enfeite. `sessao.quem()` lê um arquivo local e
nunca falha; isto aqui fala com o servidor a cada chamada, de propósito —
aprovar alguém com uma lista de ontem é aprovar quem já foi desativado hoje.

**Onde a regra mora de verdade.** Nada do que está aqui protege coisa alguma:
o `papel` decide o que APARECE, e quem nega o dado é a RLS do banco, que julga
o token a cada chamada. As duas metades existem porque esconder sem negar é
teatro, e negar sem esconder é uma tela cheia de botões que respondem "não".
"""
from __future__ import annotations

from dataclasses import dataclass

try:
    from . import rest
except ImportError:
    import rest

#: Os três papéis, com o que cada um faz — o texto vai para a tela.
PAPEIS = (
    ("admin", "Administrador",
     "tudo, mais aprovar contas e trocar papéis"),
    ("operador", "Operador",
     "todas as abas de trabalho; prepara a remessa"),
    ("aprovador", "Aprovador",
     "só Início e Remessa/Retorno; é quem libera o arquivo"),
)

SITUACOES = ("pendente", "ativo", "desativado")

#: Quais abas cada papel enxerga. `None` quer dizer "todas".
#:
#: O aprovador é o chefe: ele entra para conferir e liberar a remessa do dia, e
#: mais nada. Encher o menu dele com nove rotinas que ele não vai rodar é
#: convidar ao clique errado numa tela que mexe com pagamento.
#:
#: Papel desconhecido também vê tudo, e isso é deliberado: situação vazia quer
#: dizer "não deu para perguntar ao servidor" (ver `sessao.Quem`), e nesse caso
#: o certo é o app continuar como sempre foi — quem nega o dado é a RLS, não
#: este dicionário.
ABAS_DO_PAPEL: dict[str, tuple[str, ...] | None] = {
    "admin": None,
    "operador": None,
    "aprovador": ("ini", "pag"),
}


@dataclass(frozen=True)
class Usuario:
    """Uma linha da tabela `perfil`, do jeito que a tela precisa."""

    user_id: str = ""
    nome: str = ""
    email: str = ""
    papel: str = "operador"
    situacao: str = "pendente"
    criado_em: str = ""

    @property
    def como_chamar(self) -> str:
        """O nome, ou o que vem antes do @ quando ele não foi preenchido.

        Conta criada antes da tela de cadastro (fase 3) não tem nome: o
        backfill só tinha o e-mail para copiar."""
        return self.nome.strip() or self.email.split("@")[0]

    @property
    def espera(self) -> bool:
        return self.situacao == "pendente"

    @property
    def manda(self) -> bool:
        return self.papel == "admin" and self.situacao == "ativo"


def _do_banco(linha: dict) -> Usuario:
    return Usuario(user_id=str(linha.get("user_id") or ""),
                   nome=str(linha.get("nome") or ""),
                   email=str(linha.get("email") or ""),
                   papel=str(linha.get("papel") or "operador"),
                   situacao=str(linha.get("situacao") or "pendente"),
                   criado_em=str(linha.get("criado_em") or ""))


def _ordem(u: Usuario) -> tuple:
    """Quem espera vem primeiro: a fila é o motivo desta tela existir.

    Depois, os que trabalham; por último os desligados, que só continuam na
    lista para a auditoria ter a quem associar o que já foi feito."""
    peso = {"pendente": 0, "ativo": 1, "desativado": 2}
    return (peso.get(u.situacao, 3), u.como_chamar.lower(), u.email.lower())


def listar(token: str) -> list[Usuario]:
    """Todo mundo, em ordem de quem precisa de atenção.

    Para quem NÃO é admin, a RLS devolve só a própria linha — a tela nem é
    oferecida a essas pessoas, mas se fosse, não vazaria nada."""
    linhas = rest.ler("perfil", token,
                      colunas="user_id,nome,email,papel,situacao,criado_em")
    return sorted((_do_banco(l) for l in linhas), key=_ordem)


def _mudar(token: str, user_id: str, mudancas: dict) -> Usuario:
    if not user_id:
        # O `rest.alterar` já recusa filtro vazio; aqui o erro é dito com o
        # nome do que faltou, que é o que resolve o defeito.
        raise ValueError("sem user_id não dá para saber quem alterar")
    linhas = rest.alterar("perfil", token, f"user_id=eq.{user_id}", mudancas)
    if not linhas:
        # PATCH que não alcançou linha nenhuma volta 200 com lista vazia. Sem
        # este erro, a tela diria "pronto" para uma alteração que não houve —
        # e é assim que alguém acha que aprovou quem continua esperando.
        raise rest.RecusadoPeloBanco(
            "a alteração não alcançou ninguém: ou o usuário não existe mais, "
            "ou a sua conta não tem permissão para alterá-lo")
    return _do_banco(linhas[0])


def aprovar(token: str, user_id: str, papel: str) -> Usuario:
    """Libera a conta e diz o que ela faz. É a decisão que só gente toma."""
    if papel not in {p for p, _, _ in PAPEIS}:
        raise ValueError(f"papel desconhecido: {papel!r}")
    return _mudar(token, user_id, {"situacao": "ativo", "papel": papel})


def mudar_papel(token: str, user_id: str, papel: str) -> Usuario:
    if papel not in {p for p, _, _ in PAPEIS}:
        raise ValueError(f"papel desconhecido: {papel!r}")
    return _mudar(token, user_id, {"papel": papel})


def desativar(token: str, user_id: str) -> Usuario:
    """Desliga sem apagar.

    A linha fica: é ela que responde "quem era este user_id?" quando alguém
    olhar a auditoria de três meses atrás. Por isso não existe política de
    DELETE em `perfil` — ver a migration da fase 1."""
    return _mudar(token, user_id, {"situacao": "desativado"})


def reativar(token: str, user_id: str) -> Usuario:
    return _mudar(token, user_id, {"situacao": "ativo"})


def sobraria_admin(usuarios, user_id: str, papel: str = "",
                   situacao: str = "") -> bool:
    """Depois desta mudança, ainda haveria um administrador ativo?

    Existe por causa de um caminho sem volta: o admin que se rebaixa ou se
    desativa fecha a porta desta tela por dentro. Ninguém mais aprova ninguém,
    ninguém mais troca papel, e o conserto passa a exigir SQL no painel do
    Supabase — que é exatamente o que estas quatro fases existem para não
    precisar mais.

    Função pura, e separada da tela, porque a conta que ela faz é a parte que
    tem de estar certa: `papel` e `situacao` vazios querem dizer "não muda"."""
    for u in usuarios:
        if u.user_id == user_id:
            novo_papel = papel or u.papel
            nova_situacao = situacao or u.situacao
        else:
            novo_papel, nova_situacao = u.papel, u.situacao
        if novo_papel == "admin" and nova_situacao == "ativo":
            return True
    return False


def abas_do_papel(papel: str, todas) -> tuple:
    """As chaves de aba que este papel enxerga, na ordem em que vieram.

    Papel que não está na tabela vê tudo — ver o comentário de
    `ABAS_DO_PAPEL`."""
    permitidas = ABAS_DO_PAPEL.get(papel, None)
    if permitidas is None:
        return tuple(todas)
    return tuple(c for c in todas if c in permitidas)
