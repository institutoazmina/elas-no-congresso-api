.PHONY: help up down migrate seed test test-integration loadtest lint clean

help:
	@echo "Elas no Congresso API - Comandos disponíveis:"
	@echo "  make up              - Inicia todos os serviços"
	@echo "  make down           - Para todos os serviços"
	@echo "  make migrate       - Executa migrações"
	@echo "  make seed           - Popula dados sintéticos"
	@echo "  make test           - Executa testes unitários"
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

test:
	docker-compose exec api pytest tests/unit/ -v

test-integration:
	docker-compose exec api pytest tests/integration/ -v --reuse-db

loadtest:
	docker-compose exec api locust -f tests/load/test_load.py --host http://api:8000

lint:
	docker-compose exec api ruff check .
	docker-compose exec api mypy .

clean:
	docker-compose down -v
	rm -rf .venv/__pycache__ apps/*/__pycache__ config/*/__pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true