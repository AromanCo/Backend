package api

import (
	"github.com/AromanCo/Backend/configs"
	"github.com/AromanCo/Backend/internal/api/rest"
	"github.com/AromanCo/Backend/internal/api/rest/handlers"
	"github.com/gofiber/fiber/v2"
)

func StartServer(config configs.AppConfig) {

	app := fiber.New()
	rh := &rest.RestHandler{
		App: app,
	}
	setupRoutes(rh)
	app.Listen(config.ServerPort)
}

func setupRoutes(rh *rest.RestHandler) {
	handlers.SetupUserRoutes(rh)
}
