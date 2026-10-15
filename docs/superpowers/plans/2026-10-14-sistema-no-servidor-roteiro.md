# Sistema no servidor — roteiro (14/10/2026)

O pedido do dono: o sistema inteiro roda no servidor do escritório, e cada
pessoa usa por um "atalho". Um Chrome central é dono da sessão do ERP, e
várias automações trabalham ao mesmo tempo sem uma derrubar a outra, como
várias abas no mesmo perfil.

## Decisões já tomadas pelo dono (14/10/2026)

1. **ERP sempre pelo Chrome do app.** Nenhum robô faz `POST /users/login` por
   HTTP. Todo pedido sai de dentro de uma aba do Chrome central (fetch na
   página), ou o robô abre a própria aba nesse mesmo Chrome.
2. **O porteiro gerencia vários acessos.** Cada acesso é um usuário do ERP, com
   o próprio perfil de Chrome e a própria porta. Dois usuários diferentes
   somam duas sessões que não se derrubam.
3. **Sem Área de Trabalho Remota como atalho**, porque um acesso remoto derruba
   o outro. O atalho é uma **página web** servida pelo servidor e aberta pelo
   Tailscale.
4. **Só existe a empresa Morais.** O seletor de empresa não é risco.
5. **O ERP mostrar um usuário só não é problema**, desde que o nosso registro
   (tabela `auditoria`, e depois o livro de rodadas) diga quem pediu o quê.
6. **Água e energia também pelo app**, para rodar a qualquer hora, além da
   tarefa agendada.

## Onde fica cada coisa

- Servidor: o servidor do escritório (endereço no cofre). Não confundir com
  a máquina antiga, que está offline.
- Pasta central de configuração: `C:\AUTOMAÇÕES MAIS CONTROLE\_central\`, com
  `acessos.json` e as travas. Pode ser trocada pela variável de ambiente
  `MC_CENTRAL`; `MC_CENTRAL=off` desliga o modo central.

## Os quatro planos, em ordem

| # | Plano | Entrega que se sustenta sozinha | Arquivo |
|---|---|---|---|
| 1 | **Porteiro do ERP** | Um Chrome central por acesso; o app e o água e energia conectam a ele em vez de logar. Duas rotinas ao mesmo tempo, sem queda. | `2026-10-14-porteiro-do-erp.md` |
| 2 | **Água e energia pelo app** | Botão no app que dispara a rodada (com `--forcar`), com trava contra duas rodadas e registro de quem disparou. | escrito depois do plano 1 |
| 3 | **Página web no servidor** | A tela nova (`tela/`, React + `http.server`) passa a ouvir no IP do Tailscale, com login pelo Supabase. As rotinas viram pedidos numa fila que o servidor executa. | escrito depois do plano 2 |
| 4 | **Sicoob e Inter pela página** | O Chrome do banco roda no servidor; a página mostra o QR code para a pessoa ler no celular. | depende da decisão abaixo |

### Pendente para o plano 4: de quem é o acesso ao banco no servidor

O Sicoob reconhece "um PC cadastrado por usuário" pelo retrato do navegador
(`extratos_sicoob/sicoob_client.py:121-127`). Cadastrar o usuário do Gustavo
no Chrome do servidor **descadastra o PC dele**. Há dois caminhos:

- **(A, recomendado)** Criar no Sicoob e no Inter um **usuário operador só do
  robô**, com permissão de consulta (extrato e comprovantes), cadastrado uma
  vez no servidor. Cada pessoa continua com o seu acesso no próprio PC, sem
  mudar nada.
- **(B)** Um perfil de Chrome por pessoa no servidor
  (`.chrome_profile_sicoob_<pessoa>`). O PC de cada pessoa deixa de ser o
  "cadastrado" no banco.

O Inter já pede QR toda vez, conta a conta (`baixar_comprovantes/inter_baixar.py:32-37`):
pela página, o QR aparece para quem pediu.
