package main

import (
	"fmt"

	"github.com/gofiber/fiber/v2"
)

func main() {
	fmt.Print("dasdas")
	app := fiber.New()
	app.Listen(":8000")
}
