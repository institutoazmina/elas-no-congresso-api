# Checklist de teste local do CMS

Ambiente:

- Site: http://127.0.0.1:4321
- Admin: http://localhost:18000/admin/
- Login local: `admin` / `admin123`
- API: http://localhost:18000/api/v1/docs

> O servidor de desenvolvimento do site reutiliza GETs por até 60 segundos.
> Depois de salvar no admin, aguarde ou reinicie o servidor se a alteração não
> aparecer imediatamente.

## Acesso e estado inicial

- [ ] O site abre sem erro.
- [ ] O admin aceita o login local.
- [ ] O grupo **CMS** aparece no menu do admin.
- [ ] Cada item do CMS abre diretamente seu formulário de edição.
- [ ] Não é possível criar um segundo registro nem excluir o registro existente.
- [ ] Home, Alertas, Reportagens, Atividade Legislativa, IA Feminista e Sobre carregam sem erro.
- [ ] Não há erros ou requisições `404/500` no console do navegador.

## Alertas

- [ ] Alterar título e subtítulo, salvar e conferir em `/alertas`.
- [ ] Enviar uma imagem horizontal e salvar com sucesso.
- [ ] Enviar uma imagem vertical e salvar com sucesso.
- [ ] Enviar uma imagem quadrada e salvar com sucesso.
- [ ] Enviar uma imagem de baixa resolução e salvar com sucesso.
- [ ] Conferir que a imagem não deforma, corta nem ultrapassa o hero no desktop.
- [ ] Conferir que proporções extremas são contidas pelo CSS sem quebrar o texto.
- [ ] Conferir que a imagem continua oculta no celular e não deixa espaço vazio.
- [ ] Confirmar que arquivo acima de 5 MB é recusado.
- [ ] Confirmar que formato diferente de PNG, JPEG ou WebP é recusado.
- [ ] Restaurar título, subtítulo e imagem desejados ao terminar.

## Reportagens

- [ ] Alterar título e subtítulo, salvar e conferir em `/reportagens`.
- [ ] Substituir a ilustração por uma imagem válida e conferir no site.
- [ ] Enviar ilustrações horizontal, vertical e quadrada e conferir que não deformam nem cortam.
- [ ] Conferir as versões desktop e celular.
- [ ] Confirmar que listagem, paginação e links das reportagens continuam funcionando.
- [ ] Restaurar o conteúdo desejado ao terminar.

## Atividade Legislativa

- [ ] Alterar título e subtítulo, salvar e conferir em `/atividade-legislativa`.
- [ ] Substituir a ilustração por uma imagem válida e conferir no site.
- [ ] Enviar ilustrações horizontal, vertical e quadrada e conferir que não deformam nem cortam.
- [ ] Conferir as versões desktop e celular.
- [ ] Confirmar que filtros, resultados e links de proposições continuam funcionando.
- [ ] Restaurar o conteúdo desejado ao terminar.

## IA Feminista

- [ ] Alterar título SEO e descrição SEO.
- [ ] Alterar título, destaque e descrição da abertura.
- [ ] Substituir a ilustração da abertura e conferir no site.
- [ ] Enviar ilustrações horizontal, vertical e quadrada e conferir que não deformam nem cortam.
- [ ] Alterar textos das seções e conferir destaques e links.
- [ ] Adicionar, editar, reordenar e remover uma categoria.
- [ ] Adicionar, editar, reordenar e remover uma limitação.
- [ ] Editar métricas e conferir valores, links e tendências.
- [ ] Editar partições e conferir as tabelas.
- [ ] Substituir os fluxogramas desktop e celular.
- [ ] Conferir que cada fluxograma aparece no breakpoint correto.
- [ ] Confirmar que fluxogramas fora das proporções indicadas são recusados.
- [ ] Restaurar o conteúdo desejado ao terminar.

## Sobre

- [ ] Alterar título SEO e descrição SEO.
- [ ] Alterar textos e links da abertura.
- [ ] Substituir a ilustração da abertura e conferir no site.
- [ ] Enviar ilustrações horizontal, vertical e quadrada e conferir que não deformam nem cortam.
- [ ] Adicionar, editar, reordenar e remover um marco da linha do tempo.
- [ ] Conferir a rolagem horizontal da linha do tempo no celular.
- [ ] Adicionar, editar, reordenar e remover um desafio.
- [ ] Adicionar uma organização com logo.
- [ ] Confirmar que logos com proporções diferentes são aceitos sem deformação.
- [ ] Editar e remover uma organização existente.
- [ ] Conferir links externos e textos de acessibilidade.
- [ ] Restaurar o conteúdo desejado ao terminar.

## Home

- [ ] Alterar título SEO e descrição SEO.
- [ ] Alterar textos e destaques da abertura.
- [ ] Substituir a imagem da abertura.
- [ ] Enviar imagens de abertura horizontal, vertical e quadrada e conferir que não deformam nem cortam.
- [ ] Alterar títulos, textos, legendas, post-its e chamadas das seções.
- [ ] Conferir se links internos e externos continuam corretos.
- [ ] Substituir as imagens de Explore e QuitérIA.
- [ ] Conferir as versões desktop e celular.
- [ ] Confirmar que gráficos, mapas, notícias, tabelas e carrosséis continuam funcionando.
- [ ] Confirmar que dados legislativos não foram substituídos por conteúdo editorial.
- [ ] Restaurar o conteúdo desejado ao terminar.

## Chamada global de alertas

- [ ] Alterar título, texto, chamada e URL do botão no item **Footer: receba nossos alertas**.
- [ ] Conferir a alteração na Home.
- [ ] Conferir a alteração em Alertas, Reportagens, Atividade, IA Feminista e Sobre.
- [ ] Conferir o botão com URL interna.
- [ ] Conferir o botão com URL externa.
- [ ] Restaurar o conteúdo desejado ao terminar.

## Integração e acabamento

- [ ] Conferir que as imagens novas são servidas como WebP.
- [ ] Conferir que uma segunda substituição de imagem aparece após atualizar a página.
- [ ] Conferir que nenhum texto editável exibe HTML bruto.
- [ ] Conferir navegação por teclado e foco visível nos formulários e páginas.
- [ ] Conferir o site em largura de celular, tablet e desktop.
- [ ] Conferir que não há texto sobreposto, overflow horizontal ou layout quebrado.
- [ ] Conferir títulos, descrições e canonical no HTML gerado.
- [ ] Conferir que API e site continuam saudáveis após reiniciar os serviços.

## Encerramento

- [ ] Todo conteúdo temporário de teste foi removido ou restaurado.
- [ ] Todas as imagens temporárias foram substituídas pelas versões desejadas.
- [ ] Bugs encontrados foram registrados com página, ação, resultado esperado e resultado obtido.
- [ ] Capturas de tela foram anexadas aos bugs visuais.
- [ ] PR da API está pronto para publicar antes do PR do site.
- [ ] Endpoints `/api/v1/cms/*` foram validados após publicar a API.
- [ ] Build do site passou contra a API publicada.

## Bugs encontrados

- [ ] Nenhum bug bloqueante.
- [ ] Bug 1 registrado: <!-- link ou descrição -->
- [ ] Bug 2 registrado: <!-- link ou descrição -->
- [ ] Bug 3 registrado: <!-- link ou descrição -->
