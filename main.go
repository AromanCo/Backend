package main

import (
	"Backend/handlers"
	"Backend/middleware"
	"log"
	"net/http"

	"github.com/gorilla/mux"
)

func main() {
	r := mux.NewRouter()

	// Authentication routes
	r.HandleFunc("/api/signup", handlers.Signup).Methods("POST")
	r.HandleFunc("/api/login", handlers.Login).Methods("POST")

	// Protected route with middleware
	r.Handle("/api/protected", middleware.JwtMiddleware(http.HandlerFunc(handlers.Protected))).Methods("GET")

	log.Println("Server running on port 8080")
	log.Fatal(http.ListenAndServe(":8080", r))
}
