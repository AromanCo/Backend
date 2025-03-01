package api

import (
	"log"

	"github.com/AromanCo/Backend/configs"
	"github.com/AromanCo/Backend/internal/api/rest"
	"github.com/AromanCo/Backend/internal/api/rest/handlers"
	"github.com/AromanCo/Backend/internal/domain"
	"github.com/AromanCo/Backend/internal/helper"
	"github.com/gofiber/fiber/v2"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
)

func StartServer(config configs.AppConfig) {

	app := fiber.New()
	db, err := gorm.Open(postgres.Open(config.Dsn), &gorm.Config{})

	if err != nil {
		log.Fatalf("database conncetion error %v\n", err)
	}

	log.Println("database connected")
	db.AutoMigrate(&domain.User{})

	auth := helper.SetupAuth(config.AppSecret)

	rh := &rest.RestHandler{
		App:  app,
		DB:   db,
		Auth: auth,
	}

	setupRoutes(rh)
	app.Listen(config.ServerPort)
}

func setupRoutes(rh *rest.RestHandler) {
	handlers.SetupUserRoutes(rh)
}
