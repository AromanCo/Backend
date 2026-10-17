package main

import (
	"context"
	"fmt"
	"net"
	"os"
	"os/signal"
	"syscall"
	"time"

	"google.golang.org/grpc"
	"github.com/mrq/aroman/shared/pkg/logger"
)

func main() {
	// Initialize logger
	log := logger.New("debug")
	defer func() {
		// Sync logger on exit
		_ = log
	}()

	log.Info("Starting Product Service",
		"version", "0.0.1",
		"environment", "development",
	)

	// Setup gRPC server
	addr := ":9001"
	lis, err := net.Listen("tcp", addr)
	if err != nil {
		log.Fatal("Failed to listen", "address", addr, "error", err)
	}

	grpcServer := grpc.NewServer()

	// Register services here
	// pb.RegisterProductServiceServer(grpcServer, &productHandler{})

	log.Info("gRPC Server starting", "address", addr)

	// Handle graceful shutdown
	go func() {
		sigChan := make(chan os.Signal, 1)
		signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
		<-sigChan

		log.Info("Shutdown signal received")

		// Graceful stop with timeout
		done := make(chan struct{})
		go func() {
			grpcServer.GracefulStop()
			close(done)
		}()

		select {
		case <-done:
			log.Info("gRPC server stopped gracefully")
		case <-time.After(30 * time.Second):
			log.Warn("Graceful shutdown timeout exceeded, forcing stop")
			grpcServer.Stop()
		}
	}()

	if err := grpcServer.Serve(lis); err != nil {
		log.Fatal("gRPC server error", "error", err)
	}

	log.Info("Product Service stopped")
}
