# Admin

Django admin com tema django-unfold, em `{ADMIN_URL}` (padrão `/admin/`).
Exige login de usuário com `is_staff`; permissões seguem o padrão do Django.

## Aparência

- Título "Admin · Elas no Congresso", ícone `gavel`.
- Paleta em `config/admin_theme.py`, derivada do `tailwind.css` do site, e CSS
  extra em `apps/core/static/core/css/admin-theme.css`.
- Os models do Celery (resultados e agendamentos) são removidos do menu em
  `apps/core/admin.py`. Continuam funcionando; ajustes de agenda exigem shell ou
  alteração das configurações.

## CMS do site

O grupo **CMS** reúne o conteúdo editável do site, uma entrada por página
(**Alertas**, **Reportagens**, **Atividade legislativa**, **IA Feminista**, **Sobre** e **Home**) e a **Galeria de imagens**. Cada página tem
um registro único: o menu abre direto o formulário. Ver
[ADR-006](decisions/006-cms-do-site.md).

### Galeria de imagens do Markdown

Os editores Markdown de **Home**, **IA Feminista** e **Sobre** têm um botão de
imagem que abre a galeria. Nela é possível buscar uma imagem existente, ajustar
o texto alternativo para aquele uso ou enviar uma nova imagem sem sair do
formulário. Ao escolher, o editor insere `![texto alternativo](URL)` na posição
do cursor.

Toda imagem nova exige título interno e texto alternativo. PNG, JPEG e WebP de
até 5 MB são aceitos e armazenados como WebP. Uma imagem presente no Markdown
de qualquer uma das três páginas não pode ser excluída; remova primeiro sua
referência da página e salve a alteração.

Na **Home**, as imagens das seções Explore e QuitérIA ficam no próprio Markdown
e podem ser trocadas com esse seletor. A ilustração da abertura continua no
campo dedicado do topo da página.

Na **IA Feminista**, os campos estão agrupados pelas seções da página. Títulos,
parágrafos, links, cartões, descrições de imagens e legendas das tabelas são
editáveis no formulário. As linhas de categorias, limitações, métricas,
partições e links ficam em tabelas editáveis ao final do formulário; o campo
**Ordem** controla a sequência exibida. Os números são textos para preservar a
formatação editorial (`0,87`, `80,93%`, `2.518`). Alterar o nome de uma
categoria nessa página não altera a taxonomia da API nem outros gráficos do
site. Links dentro de parágrafos têm campos separados para texto antes do
link, texto do link, endereço e texto depois, sem exigir HTML.

Em **Sobre: textos e links**, filtre pela seção (por exemplo, **Nossa história**
ou **Expediente**) e edite os trechos diretamente na lista. Os rótulos mostram
o texto publicado para facilitar a localização. Partes com negrito ou links
aparecem em linhas separadas para preservar a formatação sem editar HTML. O
campo **Conteúdo** pode ser salvo junto com outros trechos da mesma página.

Em **Sobre: página e linha do tempo**, edite título e descrição de busca,
ilustração do topo e a nota sob a timeline. Ao fim do formulário há listas de
**marcos**, **desafios** e **organizações parceiras**. É possível adicionar,
remover e mudar a ordem; não há limite de cinco marcos. Para um novo marco,
preencha período, ano, descrição e etiqueta. O link no texto é opcional.
Para uma nova organização, informe nome, ordem e envie um logo PNG, JPEG ou
WebP; as organizações atuais conservam o logo original até ser substituído.

Na **Home: textos e links**, filtre pela seção e edite títulos, textos,
post-its, legendas, botões e endereços diretamente na lista. Trechos com
destaque visual aparecem separados, com rótulos como **antes do destaque** e
**depois do destaque**. O percentual do post-it em **Mulheres na defesa** vem
dos dados do gráfico; edite apenas as frases ao redor dele. Em **Home: imagens
e textos**, substitua a imagem da abertura em qualquer dimensão e as imagens
de Explore (4:3) e QuitérIA (16:9). Gráficos, cards de notícias, tabelas e mapas
não são editados pelo CMS.

Em **Rodapé: receba nossos alertas**, edite título, texto, chamada e endereço
do botão. Ao fim do formulário, as listas de **redes sociais** e
**organizações financiadoras** permitem adicionar, remover e ordenar links,
selecionar seus ícones e substituir logos. Esse bloco é compartilhado e a
alteração aparece em todo o site.

- Os limites de texto e as exigências da imagem aparecem no formulário. Em
  todas as ilustrações de abertura aceitam qualquer dimensão e são ajustadas
  pelo site; imagens internas com proporção indicada no campo precisam respeitá-la.
- Nos textos de abertura, use `**texto**` para exibir apenas esse trecho em
  negrito, como em `Quem foi **Maria Quitéria?**`. HTML não é aceito.
- Salvar dispara o deploy do site; a alteração aparece em alguns minutos.
  Salvamentos seguidos viram um único deploy.
- Imagens só podem ser substituídas, não removidas. A primeira versão é a
  ilustração original, publicada pelo comando `cms_publish_defaults` no deploy.
  Na IA Feminista, a ilustração de Maria Quitéria aceita qualquer dimensão; os
  fluxogramas para computador e celular exigem as proporções informadas nos
  campos. Substituir um fluxograma não modifica automaticamente o outro. A
  ilustração de Sobre também aceita qualquer dimensão; logos das organizações
  aceitam proporções variadas e são reduzidos a até 640 px.

## Curadoria de proposições

**Proposições** traz inlines de autorias, relatorias, análise QuitérIA e
anotações, com busca por número, ementa e palavras-chave.

- Marcar **aprovada** (`is_approved`) publica a proposição na API e dispara a
  correspondência de alertas.
- Gravar uma **anotação** atualiza a avaliação exibida e também dispara
  correspondência. Excluir uma anotação também invalida o cache do painel.
- A coleta não altera `is_approved` nem anotações.

## Ações específicas

| Tela | Ação | Efeito |
| --- | --- | --- |
| Parlamentares | Botão **Atualizar perfis** (`enrich-profiles/`) | Pede confirmação e enfileira `enrich_parliamentarian_profiles` |
| Inscrições (ativa) | **Enviar alerta de teste** (`<id>/send-test-alert/`) | Ver [alertas.md](alertas.md#alerta-de-teste-no-admin) |
| Relatórios semanais | Exportar Markdown/HTML; **Repetir/reconciliar entrega** | Ver [newsletter.md](newsletter.md#admin) |

Templates em `templates/admin/legislatures/parliamentarian/` e
`templates/admin/subscriptions/subscription/`.

## Ingestão

- **Termos de relevância**: editáveis, com `is_active` na listagem. Mudanças
  valem para novas descobertas (o cache é invalidado ao salvar).
- **Execuções**, **checkpoints** e **itens**: somente leitura. Use para inspecionar
  erros e cobertura; operações são feitas com `ingestion_sync` (ver
  [ingestao.md](ingestao.md)).

## Inscrições

Listagem com e-mail, ativa, `needs_revalidation`, criação e confirmação. Tokens e
`query` são somente leitura.

## Demais apps

Votações, sessões, discursos, comissões, normas e taxonomia têm registros simples.

## Cache do painel

Salvar ou excluir temas, vínculos de tema, partidos, autores institucionais,
organizações avaliadoras e eventos pelo admin invalida o cache `activity:*`
(`apps/propositions/admin_cache.py`). Alterações fora do admin nesses models,
como scripts no shell, aguardam o TTL de 5 minutos.
