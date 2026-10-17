module github.com/mrq/aroman/api-gateway

go 1.21

require (
	github.com/gin-gonic/gin v1.9.1
	github.com/mrq/aroman/shared v0.0.0
	go.uber.org/zap v1.27.0
)

replace github.com/mrq/aroman/shared => ../../shared
