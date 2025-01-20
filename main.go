package main

import (
	"log"

	config "github.com/AromanCo/Backend/configs"
	api "github.com/AromanCo/Backend/internal/api"
)

func main() {
	cfg, err := config.SetupEnv()

	if err != nil {
		log.Fatalf("config loaded error %v\n", err)
	}
	api.StartServer(cfg)
}
