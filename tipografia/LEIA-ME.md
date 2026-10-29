# Tipografia do app

Manrope (SIL Open Font License 1.1, `OFL.txt`), dos arquivos oficiais do projeto
(github.com/googlefonts/manrope, `fonts/ttf/`), recortada com `fontTools.subset`
para Latin básico + Latin-1 + travessões, aspas, reticências, € e seta (o que o
português usa). Pesos: regular, semibold, bold e extrabold.

O app NÃO instala a fonte no Windows: `widgets._carregar_tipografia()` a carrega
só para o próprio processo (`AddFontResourceExW` com `FR_PRIVATE`) antes de criar
as fontes nomeadas. Se falhar, o app segue na fonte do sistema.

Entrou na repaginada visual de 28/10/2026 (protótipo `mockups/2026-10-22-repaginada`).
