package helper

import (
	"github.com/AromanCo/Backend/internal/domain"
	"github.com/gofiber/fiber/v2"
)

type Auth struct {
	Secret string
}


func (a Auth) CreateHashedPassword(p string) (string, error) {
	
	if len(p) < 6 {
		return "", errors.New("password lenght should be at least 6 character long")
	}

	hashP, err := bcrypt.GenerateFromPassword([]byte(p), 10)

	if err != nil {
		// log actual error and report to logging tool
		return "", errors.New("password hash failed")
	}

	return string(hashP), nil
}

func (a Auth) GenerateToken(id uint, email string, role string) (string, error) {
	
	if id == 0 || email == "" || role == "" {
		return "", errors.New("Requ ")
	}


	return "", nil
}

func (a Auth) VerifyPassword(pP string, hP string) error {
	
	return nil
}

func (a Auth) VerifyToken(t string) (domain.User, error) {
	
	return domain.User{}, nil
}

func (a Auth) Authorize(ctx *fiber.Ctx) error {
	
	return nil
}

func (a Auth) GetCurrentUser(ctx *fiber.Ctx) domain.User {
	
	return domain.user{}
}

