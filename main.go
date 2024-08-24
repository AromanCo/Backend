package main

import (
    "log"
    "net/http"
    "go-auth-backend/handlers"
    "github.com/gorilla/mux"
)

func main() {
    r := mux.NewRouter()

    // Authentication routes
    r.HandleFunc("/api/signup", handlers.Signup).Methods("POST")
    r.HandleFunc("/api/login", handlers.Login).Methods("POST")

    // Protected route example
    r.Handle("/api/protected", handlers.JwtMiddleware(handlers.Protected)).Methods("GET")

    log.Println("Server running on port 8080")
    log.Fatal(http.ListenAndServe(":8080", r))
}
