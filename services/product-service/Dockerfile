# Build stage
FROM golang:1.21-alpine AS builder

WORKDIR /build
COPY ../../go.work .
COPY ../../shared ../shared
COPY . .

RUN go mod download
RUN CGO_ENABLED=1 GOOS=linux GOARCH=amd64 go build -o product-service ./cmd

# Runtime stage
FROM alpine:latest

RUN apk --no-cache add ca-certificates

WORKDIR /app
COPY --from=builder /build/product-service .
COPY ./config.yaml .

EXPOSE 9001

CMD ["./product-service"]
