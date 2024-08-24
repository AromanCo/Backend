# Go JWT Authentication Backend

This project is a simple Go backend that provides JWT-based authentication. It includes routes for user signup, login, and a protected route that requires a valid JWT to access. The authentication is handled using JSON Web Tokens (JWT).

## Features

- User Signup
- User Login
- JWT Generation and Validation
- Protected Route Example

## Directory Structure

```plaintext
go-auth-backend/
├── main.go
├── handlers/
│   ├── auth.go
├── middleware/
│   ├── jwt_middleware.go
├── models/
│   ├── user.go
├── utils/
│   ├── token.go
├── go.mod
└── go.sum
