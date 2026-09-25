# Templates de e-mail

As fontes dos e-mails são mantidas em MJML em `src/`:

- `daily.mjml`: alerta diário de uma nova proposição;
- `weekly.mjml`: resumo semanal de proposições.
- `confirmation.mjml`: confirmação de inscrição nos alertas.

Os assets locais de cada template ficam em `assets/`. O cabeçalho do alerta
diário está em `assets/daily-header.png`.

O HTML compilado é criado em `dist/` e é carregado pelo Django em tempo de
envio. A imagem Docker gera esse diretório durante o build; ele não precisa ser
versionado.

## Uso local

```bash
npm install --prefix apps/subscriptions/emails
npm run build --prefix apps/subscriptions/emails
```

Para compilar apenas um template, use `build:daily`, `build:weekly` ou
`build:confirmation`.

Os cabeçalhos são hospedados pela API em `/api/v1/assets/emails/`, para que os
clientes de e-mail possam carregá-los fora do ambiente da aplicação.

## Variáveis do alerta diário

O template `daily.mjml` preserva os placeholders do layout de referência:

- `titulo_curto`, `tipo`, `numero`, `ementa`, `autor`, `partido_uf` e `orgao`;
- `link_tramitacao`, `link_acompanhar`, `link_descadastro` e `ano`.

Antes do envio, o HTML recebe valores para essas variáveis e o cabeçalho é
resolvido para uma URL pública de assets da API.

## Variáveis do resumo semanal

O `weekly.mjml` recebe `edicao`, `data`, `temas_html`, `link_acompanhar`,
`link_descadastro` e `ano`. `temas_html` é um fragmento HTML já montado pelo remetente,
com os temas e as proposições a exibir. O template usa apenas placeholders
`{{ ... }}` compatíveis com o renderizador atual; não contém tags de controle
como `{% for %}`.

## Variáveis da confirmação

O `confirmation.mjml` recebe `confirmation_header_url`, `link_confirmacao` e
`ano`. O botão chama a rota pública de confirmação da API; depois de ativar as
inscrições pendentes daquele e-mail, a rota redireciona para a home do site.
