# Aroman Backend - Perfume Shop Microservices

A production-grade Go microservices backend for an online perfume shop, designed for **learning and best practices**.

## Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                   API Gateway                            │
│         (REST, Auth, Rate Limiting, Routing)            │
└────────┬───────────────────┬───────────────────┬────────┘
         │                   │                   │
    ┌────▼──────┐      ┌─────▼────────┐   ┌────▼───────┐
    │   Auth    │      │  Product     │   │   Order    │
    │  Service  │      │  Service     │   │  Service   │
    │(gRPC)     │      │ (gRPC)       │   │  (gRPC)    │
    └────┬──────┘      └─────┬────────┘   └────┬───────┘
         │                   │                   │
    ┌────▼──────┐      ┌─────▼────────┐   ┌────▼───────┐
    │  Redis    │      │ PostgreSQL   │   │ PostgreSQL │
    │  Sessions │      │  Products    │   │   Orders   │
    └───────────┘      └──────────────┘   └────────────┘
         ▲                   ▲                    ▲
         └───────────────────┼────────────────────┘
                      Kafka (Events)
```

## Quick Start

### Prerequisites
- Go 1.21+
- Docker & Docker Compose
- Git

### Setup Development Environment

1. **Clone & Install Dependencies**
```bash
git clone <repo>
cd Backend
cp .env.example .env
go mod download
```

2. **Start Infrastructure (Postgres, Redis, Kafka, etc)**
```bash
make docker-up
```

This starts:
- **PostgreSQL** (5432)
- **Redis** (6379)
- **Elasticsearch** (9200)
- **Kafka** (9092)
- **Prometheus** (9090)
- **Grafana** (3000) - user: `admin`, password: `admin`
- **Jaeger** (16686)

3. **Build Services**
```bash
make build
```

4. **Run Services**
```bash
make build-gateway && ./bin/api-gateway
make build-product && ./bin/product-service
```

### Useful Commands

```bash
make lint          # Run linters
make test          # Run tests
make fmt           # Format code
make docker-logs   # View container logs
make db-shell      # Access PostgreSQL
make clean         # Clean build artifacts
make docker-down   # Stop all containers
```

## Project Structure

```
Backend/
├── shared/                    # Shared libraries for all services
│   ├── pkg/
│   │   ├── errors/           # Centralized error handling
│   │   ├── logger/           # Structured logging
│   │   ├── tracer/           # Distributed tracing
│   │   ├── metrics/          # Prometheus metrics
│   │   ├── middleware/       # gRPC/HTTP middleware
│   │   └── pb/               # Protobuf definitions
│   └── go.mod
│
├── services/                 # Individual microservices
│   ├── api-gateway/          # REST API entry point
│   │   ├── cmd/main.go
│   │   ├── internal/
│   │   │   ├── handler/      # HTTP handlers
│   │   │   ├── middleware/   # Auth, CORS, rate-limiting
│   │   │   └── config/
│   │   ├── config.yaml
│   │   └── Dockerfile
│   │
│   └── product-service/      # Product catalog & inventory
│       ├── cmd/main.go
│       ├── internal/
│       │   ├── handler/      # gRPC handlers
│       │   ├── service/      # Business logic
│       │   ├── repository/   # Database access
│       │   └── model/        # Domain models
│       ├── migrations/       # DB schema
│       ├── config.yaml
│       └── Dockerfile
│
├── infrastructure/           # Infrastructure & monitoring
│   ├── k8s/                  # Kubernetes manifests
│   └── monitoring/           # Prometheus, Grafana configs
│
└── docker-compose.yml        # Full stack definition
```

## Architectural Decisions & Learning

### 1. **Microservices Over Monolith**
- **Why?** Each service has independent scaling, deployment, and data management
- **Trade-off:** More operational complexity, but enables rapid iteration per domain

### 2. **gRPC Between Services, REST to Clients**
- **Why gRPC?** Type-safe (protobuf), fast (binary), built-in load balancing
- **Why REST?** Universal client support, cache-friendly, standard HTTP
- **Impact:** Requires learning protobuf, but reduces runtime bugs

### 3. **PostgreSQL as Primary DB**
- **Why?** ACID transactions (critical for payments), complex queries, JSON support
- **Alternative considered:** NoSQL (MongoDB) - abandoned due to transaction need
- **Trade-off:** Less flexible schema, but safer data

### 4. **Redis for Sessions & Cache**
- **Why?** Sub-millisecond reads, automatic expiration, distributed locking
- **Use case:** Session tokens, inventory locks, rate-limit counters

### 5. **Elasticsearch for Search**
- **Why?** Full-text search, filtering, aggregations (essential for perfume discovery)
- **Alternative:** PostgreSQL full-text (simpler but less powerful)

### 6. **Kafka for Event Streaming**
- **Why?** Immutable log, event sourcing, multiple consumers per event
- **Use case:** "Product updated" → triggers search indexing, inventory sync, notifications
- **Alternative:** RabbitMQ (simpler, but single consumer per message)

### 7. **Layered Architecture (Handler → Service → Repository)**
- **Why?** Clear separation of concerns:
  - `handler`: converts external format to domain
  - `service`: pure business logic (testable, reusable)
  - `repository`: data access (easy to mock)
- **Benefits:** Unit tests are fast and don't touch DB

### 8. **Structured Logging & Distributed Tracing**
- **Why?** In microservices, request flows across 5+ services. Need to correlate logs.
- **Stack:** Zap (logging) + Jaeger (tracing)
- **Example:** "Why was checkout slow?" → Trace request through 3 services, find bottleneck

## Technologies Used

| Component | Technology | Why |
|-----------|-----------|------|
| Language | Go 1.21 | Fast, simple, great for backends |
| API Framework | Gin | Fast HTTP router, middleware-friendly |
| RPC Framework | gRPC + Protobuf | Type-safe, fast, language-agnostic |
| Database | PostgreSQL 15 | ACID, complex queries, JSON support |
| Cache | Redis 7 | Fast, expiring keys, locking |
| Search | Elasticsearch 8 | Full-text, facets, aggregations |
| Events | Kafka | Immutable log, event sourcing |
| Observability | Prometheus + Grafana + Jaeger | Industry standard |
| Containers | Docker | Reproducible environments |
| Container Orchestration | Kubernetes (future) | Production scaling |

## Testing Strategy

- **Unit tests:** Service logic (fast, no DB)
- **Integration tests:** Service + DB (realistic, slower)
- **Contract tests:** API contracts between services
- **End-to-end tests:** Full flow through docker-compose

```bash
make test              # All tests
make test-product      # Product service only
```

## Deployment

### Local Development
```bash
docker-compose up      # Start infrastructure
make build-all         # Build services
./bin/api-gateway      # Run in separate terminal
./bin/product-service
```

### Production (Future)
- **Container registry:** Docker Hub / GitHub Container Registry
- **Orchestration:** Kubernetes
- **CI/CD:** GitHub Actions (stub provided)
- **Monitoring:** Prometheus + Grafana + Jaeger

See `.github/workflows/` for initial CI/CD setup.

## Key Learning Goals

This project emphasizes:

1. ✅ **Clean Architecture:** Clear separation of concerns, testable code
2. ✅ **Best Practices:** Error handling, logging, validation, security
3. ✅ **Scalability:** Independent services, async processing, caching
4. ✅ **Observability:** Metrics, traces, structured logs
5. ✅ **Production-Ready:** Graceful shutdown, health checks, retries
6. ✅ **Testing:** Unit, integration, and contract tests
7. ✅ **DevOps:** Docker, docker-compose, Makefile, deployment strategies

## Roadmap

- [ ] Database migrations engine (db/sql, sqlc, or migrate)
- [ ] Auth service skeleton
- [ ] User service skeleton
- [ ] Order service skeleton
- [ ] Payment integration (Stripe stub)
- [ ] API documentation (OpenAPI/Swagger)
- [ ] Performance benchmarks
- [ ] Security hardening (secrets management, HTTPS)
- [ ] Kubernetes deployment configs

## Contributing & Learning

This is a **learning project**. Contributions and discussions about architecture are encouraged!

### Common Patterns to Explore

1. Circuit breaker (resilience)
2. Retry with exponential backoff
3. Bulkhead isolation
4. Graceful degradation
5. Request tracing across services
6. Event-driven workflows

## Resources

- **Go Best Practices:** https://golang.org/doc/effective_go
- **Clean Architecture:** Robert C. Martin's "Clean Architecture"
- **Microservices Patterns:** Chris Richardson's patterns
- **gRPC Guide:** https://grpc.io/docs/
- **PostgreSQL Tuning:** https://www.postgresql.org/docs/current/performance.html

## License

MIT

---

**Built with ❤️ to learn Go and microservices architecture.**
