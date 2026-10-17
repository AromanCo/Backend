// Package errors provides centralized error types for the Aroman system.
package errors

import "fmt"

// ErrorCode represents the type of error.
type ErrorCode string

const (
	// Client errors
	ErrorCodeValidation ErrorCode = "VALIDATION_ERROR"
	ErrorCodeNotFound   ErrorCode = "NOT_FOUND"
	ErrorCodeUnauthorized ErrorCode = "UNAUTHORIZED"
	ErrorCodeForbidden  ErrorCode = "FORBIDDEN"
	ErrorCodeConflict   ErrorCode = "CONFLICT"

	// Server errors
	ErrorCodeInternal    ErrorCode = "INTERNAL_ERROR"
	ErrorCodeUnavailable ErrorCode = "SERVICE_UNAVAILABLE"
	ErrorCodeTimeout     ErrorCode = "TIMEOUT"
)

// AppError is the standard error type for the application.
type AppError struct {
	Code    ErrorCode
	Message string
	Detail  string
	Cause   error
}

// Error implements the error interface.
func (e *AppError) Error() string {
	if e.Detail != "" {
		return fmt.Sprintf("%s: %s (%s)", e.Code, e.Message, e.Detail)
	}
	return fmt.Sprintf("%s: %s", e.Code, e.Message)
}

// New creates a new AppError.
func New(code ErrorCode, message string) *AppError {
	return &AppError{
		Code:    code,
		Message: message,
	}
}

// NewWithDetail creates a new AppError with additional detail.
func NewWithDetail(code ErrorCode, message, detail string) *AppError {
	return &AppError{
		Code:    code,
		Message: message,
		Detail:  detail,
	}
}

// IsCode checks if an error is of a specific ErrorCode.
func IsCode(err error, code ErrorCode) bool {
	appErr, ok := err.(*AppError)
	return ok && appErr.Code == code
}
