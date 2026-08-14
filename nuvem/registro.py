# -*- coding: utf-8 -*-
"""O que já foi feito — e que não pode ser feito duas vezes.

**Ainda sem uso.** O módulo existe agora porque arquivo novo custa uma release
com exe novo (~150 MB para cada pessoa): criá-lo junto do resto do pacote paga
o pedágio uma vez, e o conteúdo chega depois pelo `codigo.zip`, em segundos.

O que vai morar aqui, e por que cada um precisa da nuvem:

- **aportes lançados** — hoje em `self.criados`, memória do processo
  (`aportes/aportes_frame.py`). Falha parcial seguida de reabrir o app apaga a
  proteção, e relançar duplica dinheiro que se desfaz à mão, lançamento por
  lançamento.
- **NSA das remessas CNAB** — hoje em `remessas.json` com trava de arquivo
  (`cnab240/historico.py`). A trava protege duas execuções na MESMA máquina;
  duas máquinas gerando remessa no mesmo dia repetem o número, e NSA repetido
  pode significar pagamento em dobro.
- **retorno CNAB** — o que o banco respondeu de cada pagamento.
- **envios da Acessórias** — hoje conferidos relendo o portal, o que funciona
  e custa uma sessão.

**Aqui não haverá cache.** É a diferença deste módulo para o `cadastro.py`, e
ela é deliberada: o valor inteiro de gravar "isto já foi feito" é a resposta
ser a mesma nas duas máquinas no mesmo instante. Um cache local responderia
"pelo que eu sei, ninguém lançou" — que é indistinguível de "ninguém lançou"
na hora de decidir, e leva a lançar de novo. Sem banco, estas operações param,
e parar é o desfecho certo.

O desenho fica para o documento da Fase 3, depois de o retorno CNAB rodar de
verdade: ele define estado que ainda não existe em lugar nenhum, e schema
desenhado no escuro é o caro de corrigir depois que já tem dado dentro.
"""
