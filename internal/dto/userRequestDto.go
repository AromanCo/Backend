package dto

type UseLogin struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

type UserSignUp struct {
	UseLogin
	Phone string `json:"phone"`
}

type VerificationCodeInput struct {
	Code int `json:"code"`
}
