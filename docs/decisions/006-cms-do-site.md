# ADR-006: CMS do site no admin da API

## Estado e contexto

**Implementada para alertas, reportagens e atividade legislativa em 14/10/2026;
estendida à IA Feminista em 17/10/2026, à página Sobre e à home em 18/10/2026.**

Textos e imagens do site estático (Astro, S3 + CloudFront) estavam no código:
cada ajuste editorial exigia um desenvolvedor e um deploy. A equipe precisa
trocar textos e imagens sem mexer em estrutura ou layout. O layout do site é
ajustado ao pixel (alturas fixas, títulos sem quebra de linha, imagens
recortadas com porcentagens), então o conteúdo editável precisa de limites.

Alternativas avaliadas: CMS baseados em Git (Sveltia, Keystatic, Pages CMS),
SaaS headless (Storyblok, Sanity) e WordPress da AzMina. O admin da API já
existe, tem login, tema da marca e fica atrás do Cloudflare Access; o host EC2
compartilhado não tem folga de memória para outro processo.

## Decisão

Usar o Django admin como CMS, no app `apps.cms` (grupo **CMS** no menu).

- **Uma página, um model de registro único** (`CmsPage`, `pk=1`). Páginas com o
  topo padrão do site (título, subtítulo, ilustração 4:5) herdam de `HeroPage`. O menu abre
  direto o formulário; criar e excluir são bloqueados. Só texto e imagens são
  editáveis; rotas, rótulos de interface e layout continuam no site.
- **Limites vêm do layout**: `max_length` medido com a fonte do site (o título
  do topo tem até 24 caracteres, no máximo duas linhas). Imagens têm no máximo
  5 MB, aceitam PNG, JPEG ou WebP (SVG não) e são regravadas em WebP. A imagem
  de Alertas aceita qualquer dimensão e é enquadrada pelo CSS; as demais seguem
  a proporção do recorte (±2%) e são regravadas no tamanho exato.
- **Imagens direto no bucket do site**, como as imagens de compartilhamento
  (`apps.og`), num arquivo fixo por campo: `cms/<página>/<campo>.webp`. Enviar
  outra imagem sobrescreve o arquivo e invalida o caminho no CloudFront. Não
  há remoção, só substituição: o bucket guarda um arquivo por campo. A
  primeira versão é a ilustração original (`apps/cms/defaults/`), publicada
  pelo comando `cms_publish_defaults` a cada deploy, que só envia o que ainda
  não existe no bucket. Migrações só mexem no banco; o registro único nasce dos
  valores padrão do model na primeira visita ao admin.
  A API devolve a URL com `?v=<atualização>` para o navegador não reaproveitar
  a versão anterior do cache (`max-age=3600`).
- **Cada salvamento dispara o deploy do site**: `post_save` → `on_commit` →
  `request_site_deploy` (Celery), que chama `repository_dispatch`
  (`cms-content-updated`) no repositório do site. Salvamentos numa janela de
  `SITE_DEPLOY_DELAY_SECONDS` (30 s) viram um único disparo.
- **O site roda um deploy por vez** (`cancel-in-progress: false`); o GitHub
  mantém só um pendente por grupo, e o build lê o conteúdo mais recente.
- **Leitura pelo build**: `GET /api/v1/cms/<página>` com `Cache-Control:
  no-store`, para o build disparado não ler uma resposta em cache.
- **Página longa de IA Feminista**: mantém o mesmo registro único para os textos,
  títulos, links, cartões e três imagens. Categorias, limitações, métricas,
  partições e links de código/dados são linhas ordenadas em models próprios,
  editadas por inlines do admin. O layout e a quantidade de seções são fixos;
  a equipe edita conteúdo sem HTML, JSON ou código. O conteúdo publicado em
  17/10/2026 é o ponto de partida de uma migração de dados; o arquivo
  `defaults/feminist-ai-content.json` é parte histórica dessa migração e não
  deve ser alterado para publicar atualizações futuras. A tabela de categorias
  nessa página é editorial e não altera a taxonomia usada pela API.
- **Página Sobre**: o registro único guarda SEO, ilustração e nota da timeline.
  A página publicada tem muitos trechos com formatação e links intercalados;
  `AboutCopy` expõe cada trecho como texto simples, filtrável por seção e
  editável em lote no admin. As posições do markup ficam no Astro, de modo que
  a equipe não edita HTML. Marcos, desafios e organizações parceiras são linhas
  ordenadas próprias: a timeline aceita qualquer quantidade de marcos e usa
  etiquetas visuais repetíveis. Logos novos aceitam proporções variadas, são
  regravados em WebP com até 640 px e substituídos em uma URL estável. Os
  logos originais das organizações atuais continuam nos assets do site até
  serem substituídos. `defaults/about-content.json` é o snapshot da migração
  de dados inicial, não um arquivo de edição editorial.
- **Home**: `HomePage` guarda três imagens e `HomeCopy` expõe os 70 trechos
  editoriais por seção, com rótulos legíveis e edição em lista. A equipe pode
  trocar títulos, textos, post-its, legendas e CTAs sem editar HTML. Frases
  intercaladas com destaques visuais têm campos separados; o percentual do
  post-it de autoria feminina continua calculado pelos dados da API. Gráficos,
  cards de notícias, tabelas e mapas continuam nas fontes atuais. O bloco
  **Receba nossos alertas** é um singleton separado (`FooterAlertsPage`) porque
  aparece em todo o site. O build consulta esse bloco uma vez e inclui seu
  conteúdo na chave de cache das páginas de autoria para que edições no footer
  atualizem também essas páginas. `defaults/home-content.json` registra apenas
  o conteúdo inicial da migração.

## Consequências

- Sem rascunho: salvar publica após um build. O histórico do admin mostra quem
  alterou, mas não guarda versões do conteúdo.
- Se a API cair, o build do site falha, como já acontece com os dados.
- Novo campo editável exige migração e deploy da API e do site. As páginas de IA
  Feminista, Sobre e Home têm PRs pareados no site para trocar o conteúdo fixo
  pela leitura dos endpoints correspondentes no build.
- A imagem nova vale assim que é salva, alguns minutos antes do texto, que
  depende do deploy.
- A role do EC2 precisa de `s3:GetObject`/`s3:PutObject` em `cms/*` e
  `cloudfront:CreateInvalidation` na distribuição do site; o deploy do site
  exclui `cms/*` do `sync --delete`.
- Segredo `SITE_DEPLOY_GITHUB_TOKEN`: token fine-grained restrito ao repositório
  do site, permissão Contents (read and write). Sem ele, nada é disparado.

## Referências

- `apps/cms/models.py`, `admin.py`, `images.py`, `storage.py`, `tasks.py`, `deploy.py`
- `apps/cms/tests/test_cms.py`
- Site: `.github/workflows/build.yml`
