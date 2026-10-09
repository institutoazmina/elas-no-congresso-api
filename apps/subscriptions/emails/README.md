# Templates de e-mail

As fontes dos e-mails são mantidas em MJML em `src/`:

- `daily.mjml`: resumo diário das proposições acompanhadas, por tema e celeridade;
- `confirmation.mjml`: confirmação de inscrição nos alertas.

Os assets locais de cada template ficam em `assets/`. O cabeçalho do alerta
diário está em `assets/daily-header.png`, e o da confirmação em
`assets/header.png`.

O HTML compilado é criado em `dist/` e é carregado pelo Django em tempo de
envio. A imagem Docker gera esse diretório durante o build; ele não precisa ser
versionado.

## Uso local

```bash
npm install --prefix apps/subscriptions/emails
npm run build --prefix apps/subscriptions/emails
```

Para compilar apenas um template, use `build:daily` ou `build:confirmation`.

Os cabeçalhos são hospedados pela API em `/api/v1/assets/emails/`, para que os
clientes de e-mail possam carregá-los fora do ambiente da aplicação.

## Variáveis do alerta diário

O template `daily.mjml` recebe `data`, `temas_html`, `daily_header_url`,
`link_acompanhar`, `link_descadastro` e `ano`.

`temas_html` agrupa as proposições pelas Categorias 2026 das anotações humanas,
com fallback para a análise concluída da QuitérIA ou “Sem tema informado”.
Dentro de cada tema, a ordem é “Tá voando”, “Rápida”, “Lenta”, “Travada” e
“Esquecida”, usando o mesmo cálculo de celeridade do painel público. Cada
proposição aparece uma vez por tema distinto, mesmo com anotações repetidas.
Os cards incluem número, ementa, autoria, situação e link de tramitação;
relatoria atual, regime e lei resultante aparecem quando disponíveis.
O texto simples segue os mesmos grupos, e os valores inseridos no HTML são
escapados pelo renderizador.

O envio ocorre uma vez por endereço/dia às 09:00 de America/Sao_Paulo, ajustável
por `DAILY_DIGEST_TIME=HH:MM`. As regras de corte e retry estão em
[`docs/alertas.md`](../../../docs/alertas.md#resumo-diário).

## Variáveis da confirmação

O `confirmation.mjml` recebe `confirmation_header_url`, `link_confirmacao` e
`ano`. O botão chama a rota pública de confirmação da API; depois de ativar as
inscrições pendentes daquele e-mail, a rota redireciona para a home do site.
