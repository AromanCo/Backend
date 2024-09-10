package handlers

import (
	"Backend/models"
	"Backend/utils"
	"encoding/json"
	"net/http"
)

var users = map[string]string{}

// Signup handler
func Signup(w http.ResponseWriter, r *http.Request) {
	var user models.User
	if err := json.NewDecoder(r.Body).Decode(&user); err != nil {
		http.Error(w, "Invalid input", http.StatusBadRequest)
		return
	}

	users[user.Username] = user.Password
	w.WriteHeader(http.StatusCreated)
}

// Login handler
func Login(w http.ResponseWriter, r *http.Request) {
	var user models.User
	if err := json.NewDecoder(r.Body).Decode(&user); err != nil {
		http.Error(w, "Invalid input", http.StatusBadRequest)
		return
	}

	// Validate credentials
	if storedPassword, ok := users[user.Username]; !ok || storedPassword != user.Password {
		http.Error(w, "Invalid credentials", http.StatusUnauthorized)
		return
	}

	// Generate JWT
	tokenString, err := utils.GenerateJWT(user.Username)
	if err != nil {
		http.Error(w, "Error generating token", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{
		"token": tokenString,
	})
}

// Protected route
func Protected(w http.ResponseWriter, r *http.Request) {
	w.Write([]byte("This is a protected route"))
}
