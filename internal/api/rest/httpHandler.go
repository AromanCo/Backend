package rest

import (
	"github.com/AromanCo/Backend/configs"
	"github.com/AromanCo/Backend/internal/helper"
	"github.com/gofiber/fiber/v2"
	"gorm.io/gorm"
)

type RestHandler struct {
	App    *fiber.App
	DB     *gorm.DB
	Auth   helper.Auth
	Config configs.AppConfig
}
