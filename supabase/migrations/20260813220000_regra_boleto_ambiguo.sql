-- O campo `ambiguo` das regras de boleto, que o modelo tinha perdido.
--
-- Quatro das seis regras o preenchem, e o que ele guarda e o mais caro de
-- reconstruir: POR QUE aquela regra nao pode anexar sozinha. Sao paragrafos
-- escritos a mao depois de investigar casos reais -- duas salas de um mesmo
-- condominio que o e-mail nao distingue, varias UCs sob um remetente so.
--
-- Quem o descobriu foi o teste de ida e volta (arquivos -> banco -> arquivos):
-- a contagem batia, 6 regras de um lado e 6 do outro, e mesmo assim o texto
-- tinha sumido. Contar linha nao e conferir conteudo.
alter table public.regra_boleto
  add column ambiguo text not null default '';

comment on column public.regra_boleto.ambiguo is
  'Por que esta regra nao anexa sozinha: o que o e-mail nao distingue. '
  'Vazio = nao ha ambiguidade conhecida.';

comment on column public.regra_boleto.nota is
  'Observacao livre sobre a regra.';
