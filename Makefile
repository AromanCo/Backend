.PHONY: help build run test clean docker-up docker-down lint fmt migrate-product

help:
	@echo "Aroman Backend - Perfume Shop Microservices"
	@echo ""
	@echo "Available commands:"
	@echo "  make build              Build all services"
	@echo "  make build-gateway      Build API gateway"
	@echo "  make build-product      Build product service"
	@echo "  make run                Run all services (requires docker-compose)"
	@echo "  make docker-up          Start infrastructure (Postgres, Redis, Kafka, etc)"
	@echo "  make docker-down        Stop all containers"
	@echo "  make docker-logs        View container logs"
	@echo "  make test               Run tests in all services"
	@echo "  make test-product       Run tests for product service"
	@echo "  make lint               Run linters (golangci-lint)"
	@echo "  make fmt                Format code (gofmt)"
	@echo "  make clean              Clean build artifacts"
	@echo "  make migrate-product    Run product service migrations"
	@echo "  make db-shell           Open PostgreSQL shell"
	@echo "  make logs               View all logs"

# Build targets
build: build-gateway build-product
	@echo "✓ All services built"

build-gateway:
	@echo "Building API Gateway..."
	cd services/api-gateway && go build -o ../../bin/api-gateway ./cmd

build-product:
	@echo "Building Product Service..."
	cd services/product-service && go build -o ../../bin/product-service ./cmd

# Docker targets
docker-up:
	@echo "Starting infrastructure..."
	docker-compose up -d
	@echo "✓ Infrastructure started"
	@echo "Waiting for services to be healthy..."
	sleep 10
	@echo ""
	@echo "Service URLs:"
	@echo "  PostgreSQL:     localhost:5432"
	@echo "  Redis:          localhost:6379"
	@echo "  Elasticsearch:  http://localhost:9200"
	@echo "  Kafka:          localhost:9092"
	@echo "  Prometheus:     http://localhost:9090"
	@echo "  Grafana:        http://localhost:3000 (admin/admin)"
	@echo "  Jaeger:         http://localhost:16686"

docker-down:
	@echo "Stopping containers..."
	docker-compose down
	@echo "✓ Stopped"

docker-logs:
	docker-compose logs -f

docker-clean: docker-down
	@echo "Removing volumes..."
	docker-compose down -v
	@echo "✓ Volumes removed"

# Development targets
test:
	@echo "Running tests..."
	cd services/api-gateway && go test ./...
	cd services/product-service && go test ./...

test-product:
	cd services/product-service && go test -v ./...

lint:
	@if ! command -v golangci-lint &> /dev/null; then \
		echo "Installing golangci-lint..."; \
		go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest; \
	fi
	@echo "Linting services..."
	cd services/api-gateway && golangci-lint run
	cd services/product-service && golangci-lint run

fmt:
	@echo "Formatting code..."
	fd services -e .go -x gofmt -w
	gofmt -w shared/

clean:
	@echo "Cleaning build artifacts..."
	rm -rf bin/
	go clean -testcache
	@echo "✓ Cleaned"

# Database targets
migrate-product:
	@echo "Running product service migrations..."
	@echo "Coming soon: implement with migrate tool"

db-shell:
	docker-compose exec postgres psql -U postgres

# Utility targets
tidy:
	@echo "Running go mod tidy..."
	cd shared && go mod tidy
	cd services/api-gateway && go mod tidy
	cd services/product-service && go mod tidy

logs:
	docker-compose logs -f --tail=100
