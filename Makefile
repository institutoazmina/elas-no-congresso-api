.PHONY: help up down migrate seed test test-integration loadtest lint clean

help:
	@echo "Elas no Congresso API - Comandos disponíveis:"
	@echo "  make up              - Inicia todos os serviços"
	@echo "  make down           - Para todos os serviços"
	@echo "  make migrate       - Executa migrações"
	@echo "  make seed           - Popula dados sintéticos"
	@echo "  make test           - Executa testes unitários e dos apps"
	@echo "  make test-integration - Executa testes de integração"
	@echo "  make loadtest       - Executa testes de carga"
	@echo "  make lint           - Executa lint e type check"
	@echo "  make clean           - Limpa containers e volumes"

up:
	docker-compose up -d
	@echo "Aguardando serviços prontos..."
	@sleep 10
	@docker-compose exec -T postgres pg_isready -U elas && echo "Postgres OK" || echo "Postgres ERRO"
	@docker-compose exec -T redis redis-cli ping && echo "Redis OK" || echo "Redis ERRO"
	@curl -sf http://localhost:4566/_localstack/health >/dev/null && echo "MiniStack OK" || echo "MiniStack ERRO"

down:
	docker-compose down

migrate:
	docker-compose exec api python manage.py migrate

seed:
	docker-compose exec api python manage.py loaddata fixtures/*.json || true

# pytest/ruff/mypy/locust rodam no host (via uv), não em `docker-compose exec api`:
# o runtime da imagem é distroless e buildado com `uv sync --no-dev`, então não
# tem shell nem as dev deps. Os testes de integração falam com o Postgres do
# compose pela porta publicada — `make up` antes.
test:
	uv run pytest tests/unit/ apps/

test-integration:
	uv run pytest tests/integration/ --reuse-db

loadtest:
	uv run locust -f tests/load/test_load.py --host http://localhost:8000

lint:
	uv run ruff check .
	uv run mypy .

clean:
	docker-compose down -v
	rm -rf .venv/__pycache__ apps/*/__pycache__ config/*/__pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true