module github.com/mrq/aroman/product-service

go 1.21

require (
	github.com/lib/pq v1.10.9
	github.com/mrq/aroman/shared v0.0.0
	google.golang.org/grpc v1.60.0
	go.uber.org/zap v1.27.0
)

replace github.com/mrq/aroman/shared => ../../shared
