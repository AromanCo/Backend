package service

import (
	"errors"
	"fmt"
	"time"

	"github.com/AromanCo/Backend/configs"
	"github.com/AromanCo/Backend/internal/domain"
	"github.com/AromanCo/Backend/internal/dto"
	"github.com/AromanCo/Backend/internal/helper"
	"github.com/AromanCo/Backend/internal/repository"
	"github.com/AromanCo/Backend/pkg/notification"
)

type UserService struct {
	Repo   repository.UserRepository
	Auth   helper.Auth
	Config configs.AppConfig
}

func (s UserService) findUserByEmail(email string) (*domain.User, error) {
	user, err := s.Repo.FindUser(email)
	return &user, err
}

// any -> interface{}
func (s UserService) Register(input dto.UserSignUp) (string, error) {

	hPassword, err := s.Auth.CreateHashedPassword(input.Password)

	if err != nil {
		return "", err
	}

	user, err := s.Repo.CreateUser(domain.User{
		Email:    input.Email,
		Password: hPassword,
		Phone:    input.Phone,
	})

	return s.Auth.GenerateToken(user.ID, user.Email, user.UserType)
}

func (s UserService) Login(email string, password string) (string, error) {
	user, err := s.findUserByEmail(email)
	if err != nil {
		return "", errors.New("user dose not exist with the sended info")
	}

	err = s.Auth.VerifyPassword(password, user.Password)

	if err != nil {
		return "", err
	}

	return s.Auth.GenerateToken(user.ID, user.Email, user.UserType)
}

func (s UserService) isVerifiedUser(id uint) bool {
	currentUser, err := s.Repo.FindUserById(id)

	return err != nil && currentUser.Verified
}

func (s UserService) GetVerificationCode(e domain.User) error {

	if s.isVerifiedUser(e.ID) {
		return errors.New("User is Verified")
	}

	code, err := s.Auth.GenerateCode()

	if err != nil {
		return nil
	}

	user := domain.User{
		Expiry: time.Now().Add(30 * time.Minute),
		Code:   code,
	}

	_, err = s.Repo.UpdateUser(e.ID, user)

	if err != nil {
		return errors.New("unable to update verification code")
	}

	user, _ = s.Repo.FindUserById(e.ID)

	//TODO Send SMS
	notificationClient := notification.NewNotificationClient(s.Config)

	msg := fmt.Sprintf("Your verification code is %v", code)

	err = notificationClient.SendSMS(user.Phone, msg)

	if err != nil {
		return errors.New("Error to Sending SMS")
	}

	return nil
}

func (s UserService) VerifyCode(id uint, code int) error {

	if s.isVerifiedUser(id) {
		return errors.New("User is Verified")
	}

	user, err := s.Repo.FindUserById(id)

	if err != nil {
		return err
	}

	if user.Code != code {
		return errors.New("verification code dose not match")
	}

	if !time.Now().Before(user.Expiry) {
		return errors.New("verification code is expire")
	}

	updateUser := domain.User{
		Verified: true,
	}

	_, err = s.Repo.UpdateUser(id, updateUser)

	if err != nil {
		return errors.New("unable to verifiy user")
	}

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
