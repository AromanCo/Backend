package repository

import (
	"errors"
	"log"

	"github.com/AromanCo/Backend/internal/domain"
	"gorm.io/gorm"
)

type UserRepository interface {
	CreateUser(usr domain.User) (domain.User, error)
	FindUser(email string) (domain.User, error)
	FindUserById(id uint) (domain.User, error)
	UpdateUser(id uint, u domain.User) (domain.User, error)
}

type userRepository struct {
	db *gorm.DB
}

func NewUserRepository(db *gorm.DB) UserRepository {
	return &userRepository{
		db: db,
	}
}

func (r userRepository) CreateUser(usr domain.User) (domain.User, error) {
	err := r.db.Create(&usr).Error

	if err != nil {
		log.Printf("create user error %v", err)

		return domain.User{}, errors.New("failed to create user")
	}

	return usr, nil
}

func (r userRepository) FindUser(email string) (domain.User, error) {
	var usr domain.User

	err := r.db.Find(&usr, "email=?", email).Error

	if err != nil {
		log.Printf("find user error %v", err)

		return domain.User{}, errors.New("faild to find user")
	}

	return usr, nil
}

func (r userRepository) FindUserById(id uint) (domain.User, error) {
	return domain.User{}, nil
}

func (r userRepository) UpdateUser(id uint, u domain.User) (domain.User, error) {
	return domain.User{}, nil
}
