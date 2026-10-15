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
(hoje só **Alertas**: título, subtítulo e ilustração do topo). Cada página tem
um registro único: o menu abre direto o formulário. Ver
[ADR-006](decisions/006-cms-do-site.md).

- Os limites de texto e as exigências da imagem aparecem no formulário e vêm do
  layout do site. Imagens fora da proporção não são aceitas.
- Salvar dispara o deploy do site; a alteração aparece em alguns minutos.
  Salvamentos seguidos viram um único deploy.
- Imagens só podem ser substituídas, não removidas. A primeira versão é a
  ilustração original, publicada pelo comando `cms_publish_defaults` no deploy.

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
