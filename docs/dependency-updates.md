# Atualizações de dependências

O [renovate.json](../renovate.json) configura o Renovate como responsável pelos
PRs de atualização. O app já está instalado na organização e tem acesso a este
repositório. A política passa a valer quando o arquivo chegar à branch `main`.
O PR inicial de onboarding é [#5](https://github.com/institutoazmina/elas-no-congresso-api/pull/5);
esta configuração substitui a configuração mínima proposta nele.

## Política

- Atualizações rotineiras: segunda-feira, das 00:00 às 05:59 em
  `America/Sao_Paulo`, com espera mínima de três dias após o release.
- Até dois PRs rotineiros e um PR de segurança simultâneos: três no total.
  Os PRs de segurança têm orçamento próprio no Renovate.
- Grupos separados para Python, templates de e-mail, GitHub Actions e containers.
  Upgrades major ficam separados e exigem aprovação no Dependency Dashboard
  antes da criação do PR.
- Django fica fora do grupo geral de Python.
- PyTorch e Transformers são revisados juntos, com aprovação no dashboard
  inclusive para upgrades minor. Valide inferência da QuitérIA com o modelo
  fixado e confira as wheels CPU no lockfile; a suíte de CI usa mocks de IA.
- Manutenção semanal dos lockfiles, incluindo `uv.lock` e `package-lock.json`.
- Automerge desativado para todos os updates. Cada merge em `main` dispara o
  pipeline de deploy, e o bot não recebe bypass das proteções da branch.

Os PRs de segurança usam os alertas do GitHub, não esperam a janela semanal
nem o prazo mínimo de release e exigem aprovação no dashboard antes de serem
abertos. Essa revisão também mantém upgrades major e de IA sob aprovação.
Os alertas do Dependabot continuam habilitados; a criação automática de PRs
pelo Dependabot é desativada para evitar duplicação com o Renovate.

As atualizações precisam passar pelo check obrigatório `CI passed`, incluindo
os audits. A configuração não adiciona exceções para os findings Python já
documentados em [segurança no CI](security-ci.md). O saneamento inicial dessas
dependências precisa ser coordenado: um PR isolado pode continuar vermelho
enquanto outros pacotes vulneráveis permanecerem no lockfile.

O app gerenciado executa o Renovate; não há workflow próprio nem token de bot
adicionado ao projeto. O dashboard é criado pelo bot no GitHub após o onboarding.
Não é preciso mesclar o PR de onboarding genérico se esta configuração já tiver
chegado a `main`; confira a reavaliação do bot antes de tratar PRs duplicados.

## Limites

Os managers habilitados cobrem `pyproject.toml`/uv, npm, Dockerfile, Compose e
GitHub Actions, incluindo as referências SHA. Pins escritos em comandos shell
ou código, como a versão/checksum do Gitleaks e o pip-audit, precisam de revisão
manual. O modelo e sua revisão fixa também não são atualizados automaticamente.

## Validar alterações

Com Node 24.11 ou superior dentro da série 24:

```bash
npm exec --yes --package renovate@44.165.1 -- renovate-config-validator --strict --no-global renovate.json
```

Consulte o [Dependency Dashboard](https://docs.renovatebot.com/key-concepts/dashboard/)
para aprovar upgrades e os logs do app para falhas na regeneração dos lockfiles.
