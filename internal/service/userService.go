package service

import (
	"errors"
	"fmt"

	"github.com/AromanCo/Backend/internal/domain"
	"github.com/AromanCo/Backend/internal/dto"
	"github.com/AromanCo/Backend/internal/repository"
)

type UserService struct {
	Repo repository.UserRepository
}

func (s UserService) findUserByEmail(email string) (*domain.User, error) {
	user, err := s.Repo.FindUser(email)
	return &user, err
}

// any -> interface{}
func (s UserService) Register(input dto.UserSignUp) (string, error) {
	user, err := s.Repo.CreateUser(domain.User{
		Email:    input.Email,
		Password: input.Password,
		Phone:    input.Phone,
	})

	userInfo := fmt.Sprintf("%v, %v, %v", user.ID, user.Email, user.UserType)

	return userInfo, err
}

func (s UserService) Login(email string, password string) (string, error) {
	user, err := s.findUserByEmail(email)
	if err != nil {
		return "", errors.New("user dose not exist with the sended info")
	}

	return user.Email, nil
}

func (s UserService) GetVerificationCode(e domain.User) (int, error) {
	return 0, nil
}

func (s UserService) VerifyCode(id uint, code int) error {
	return nil
}

func (s UserService) CreateProfile(id uint, input any) error {
	return nil
}

func (s UserService) GetProfile(id uint) (*domain.User, error) {
	return nil, nil
}

func (s UserService) UpdateProile(id uint, input any) (string, error) {
	return "", nil
}

func (s UserService) BecomeSeller(id uint, input any) (string, error) {
	return "", nil
}

func (s UserService) FindCart(id uint) ([]interface{}, error) {
	return nil, nil
}

func (s UserService) CreateCart(input any, u domain.User) ([]interface{}, error) {
	return nil, nil
}

func (s UserService) CreateOrder(u domain.User) (int, error) {
	return 0, nil
}

func (s UserService) GetOrders(u domain.User) ([]interface{}, error) {
	return nil, nil
}

func (s UserService) GetOrderById(id uint, uId uint) (interface{}, error) {
	return nil, nil
}
