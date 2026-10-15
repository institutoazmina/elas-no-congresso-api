# ADR-006: CMS do site no admin da API

## Estado e contexto

**Implementada para as páginas de alertas, reportagens e atividade legislativa em 14/10/2026.**

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
  do topo tem até 24 caracteres, no máximo duas linhas). Imagens
  precisam da proporção do recorte (±2%), têm no máximo 5 MB, aceitam PNG, JPEG
  ou WebP (SVG não) e são regravadas em WebP no tamanho exato.
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

## Consequências

- Sem rascunho: salvar publica após um build. O histórico do admin mostra quem
  alterou, mas não guarda versões do conteúdo.
- Se a API cair, o build do site falha, como já acontece com os dados.
- Novo campo editável exige migração e deploy da API e do site.
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
