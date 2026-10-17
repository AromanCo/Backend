// Package logger provides structured logging using Uber's zap library.
package logger

import "go.uber.org/zap"

// Logger wraps zap.Logger for the application.
type Logger struct {
	sugar *zap.SugaredLogger
}

// New creates a new logger.
func New(level string) *Logger {
	var l *zap.Logger
	var err error

	switch level {
	case "debug":
		l, err = zap.NewDevelopment()
	case "info", "warn", "error":
		l, err = zap.NewProduction()
	default:
		l, err = zap.NewProduction()
	}

	if err != nil {
		panic("failed to initialize logger: " + err.Error())
	}

	return &Logger{
		sugar: l.Sugar(),
	}
}

// Debug logs a debug message.
func (l *Logger) Debug(msg string, keysAndValues ...interface{}) {
	l.sugar.Debugw(msg, keysAndValues...)
}

// Info logs an info message.
func (l *Logger) Info(msg string, keysAndValues ...interface{}) {
	l.sugar.Infow(msg, keysAndValues...)
}

// Warn logs a warning message.
func (l *Logger) Warn(msg string, keysAndValues ...interface{}) {
	l.sugar.Warnw(msg, keysAndValues...)
}

// Error logs an error message.
func (l *Logger) Error(msg string, keysAndValues ...interface{}) {
	l.sugar.Errorw(msg, keysAndValues...)
}

// Fatal logs a fatal message and exits.
func (l *Logger) Fatal(msg string, keysAndValues ...interface{}) {
	l.sugar.Fatalw(msg, keysAndValues...)
}
