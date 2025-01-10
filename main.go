package main

import (
	appConfig "github.com/AromanCo/Backend/configs"
	api "github.com/AromanCo/Backend/internal/api"
)

func main() {
	api.StartServer()
	appConfig.LoadAppSettings()
}
