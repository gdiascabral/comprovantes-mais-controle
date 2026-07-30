# Testes

Testes de unidade das partes puras (sem navegador, sem rede) do app:

- `test_matcher.py` — leitura do nome do PDF (`parse_pdf`) e casamento
  PDF↔pagamento (`casar`). Não depende de nada além do `matcher`.
- `test_campos.py` — extração de valor/data/descrição do TEXTO do comprovante
  (`campos`, `nome_arquivo`). Importa `separar_renomear`, que puxa
  `pdfplumber`/`tkinter`; se faltarem, os testes são pulados.

## Rodar

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest            # a partir da raiz do repositório
```

## Fixtures

`tests/fixtures/*.txt` guardam o TEXTO que o `pdfplumber` (ou o OCR, no layout
impresso) extrairia de um comprovante.

**Regra:** são arquivos SINTÉTICOS — nomes, CPF/CNPJ e documentos fake. O
repositório é público; **nunca** commite comprovantes reais (PDF) nem texto com
dados de cliente. Para cobrir um banco/layout novo, salve aqui o texto
ANONIMIZADO de um exemplo e escreva o `assert` do resultado esperado.
