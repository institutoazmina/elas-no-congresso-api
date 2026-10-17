# Compatibilidade antes de atualizar dependências

O baseline foi gravado com o `uv.lock` anterior às correções de segurança:
PyTorch `2.12.0+cpu`, Transformers `5.7.0` e revisão do modelo
`6f258ee80c0ac410ce60317a4e31460590d7e594`. Essa referência permanece fixa após
as atualizações de segurança; as versões atuais estão no `uv.lock` e no
[registro das correções](security-ci.md#correções-de-dependências-python).

## Contratos cobertos

| Área | O que os testes exercitam |
| --- | --- |
| PDF | pypdf e PyMuPDF reais; acentos, ordem de páginas, conteúdo esperado, arquivo truncado, PDF criptografado e fallback sem renderer/OCR |
| OCR | Renderização de um PDF sem camada de texto e reconhecimento real com Tesseract em português; verifica frases e recuperação substancial do documento |
| HTTP | Servidor local com sockets reais; redirects, JSON UTF-8, gzip, retry de 503, JSON inválido sem retry e download de PDF comprimido com parsing real |
| Django | Login por senha, autenticação de hash PBKDF2 criado com o custo padrão do Django 5.1 e atualização para o custo atual, CSRF obrigatório, rejeição de origem não confiável, cookie seguro, sessão em cache, logout e restrição de acesso ao admin |
| E-mail | Endpoint público com EmailStr/email-validator/IDNA reais; normalização de domínio Unicode/punycode e rejeição sem gravação/envio em entradas inválidas |
| QuitérIA | Dois modelos BERT reais em CPU, hashes dos oito arquivos, tokenização, truncamento em 512 tokens, categorias, favorabilidade e vetores de probabilidades |

Os documentos em `tests/fixtures/compatibility/` são sintéticos, sem dados
pessoais ou conteúdo legislativo copiado. Os PDFs de texto e imagem foram
montados como objetos PDF 1.4 independentes dos parsers testados; o raster usa
DejaVu Sans. O PDF criptografado foi derivado do documento de texto com pypdf
6.13.2 e senha exclusiva de teste. Os arquivos são fixos: os testes não os
recriam usando a versão do parser que estiver instalada.

O PDF criptografado expôs uma exceção adiada pelo iterador de páginas do pypdf.
A extração agora valida a sequência dentro do tratamento de erro existente,
retornando `None` em vez de abortar a tarefa.

## Execução

Com o PostgreSQL/pgvector e os templates de e-mail preparados conforme o README,
instale Tesseract com dados de português no sistema. Em Ubuntu/Debian:

```bash
sudo apt-get install tesseract-ocr tesseract-ocr-por
make test-compatibility
```

O OCR é obrigatório nesses testes: a ausência do executável ou do idioma não
é tratada como um resultado aprovado. A comparação tolera diferenças pequenas
de espaços e pontuação, mantendo verificações de conteúdo.

Para baixar os mesmos pesos públicos usados na imagem de produção:

```bash
HF_HUB_DISABLE_XET=1 uv run hf download azmina/quiteria-2.0 \
  --revision 6f258ee80c0ac410ce60317a4e31460590d7e594 \
  --include 'tema/*' --include 'favorabilidade/*' \
  --local-dir /tmp/quiteria-model
QUITERIA_TEST_MODEL_DIR=/tmp/quiteria-model HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 make test-ml
```

O pytest comum pode excluir os testes pesados com `-m "not ml"`. O job
`Quiteria model compatibility` os executa em cada PR com `--run-ml`, cache dos
pesos e rede do Hub desabilitada durante inferência. Se o diretório/arquivo
estiver ausente ou alterado, o job falha. O check `CI passed` exige seu sucesso.

## Interpretação do baseline de IA

Os oito exemplos incluem seis pautas sintéticas, texto vazio e texto longo.
São um contrato de regressão do comportamento atual, não um conjunto de
avaliação de qualidade editorial. As categorias e os rótulos devem permanecer
iguais. Scores aceitam erro absoluto de `1e-4` e relativo de `1e-3` para pequenas
variações numéricas entre CPUs; o somatório das probabilidades também é validado.
A tokenização deve preservar o tamanho e o hash dos IDs de tokens.

O baseline registra versões, revisão do modelo e SHA-256 dos pesos/configs.
Quatro checksums públicos de arquivos `tokenizer*.json` coincidem com a regra
genérica de secrets. O `.gitleaksignore` registra somente os quatro fingerprints
históricos revisados; o arquivo e a regra continuam sendo verificados em novas
alterações. Não há exclusão geral do baseline.
Ele não é regenerado pela suíte. Para gravar uma nova referência deliberadamente:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run python -m scripts.record_quiteria_baseline \
  --model-dir /tmp/quiteria-model --output /tmp/quiteria-baseline-candidate.json
```

Compare o candidato com o arquivo versionado antes de aceitar mudanças. Não
substitua automaticamente o baseline para fazer um upgrade passar. Investigue
primeiro alterações de tokenização, rótulos, scores e limiar de favorabilidade.

## Limites

A suíte dá evidência de compatibilidade nos caminhos exercitados. Não prova
ausência de vulnerabilidades, qualidade global da IA ou resistência a todos os
PDFs malformados. A auditoria de dependências continua obrigatória. Os serviços
externos reais não são contatados pelos testes HTTP; TLS/proxies públicos não
são cobertos pelo servidor local. A integração SES existente continua cobrindo
Anymail/Boto3/urllib3 com MiniStack. Testes de carga e comportamento real de
Redis/workers permanecem verificações separadas.
