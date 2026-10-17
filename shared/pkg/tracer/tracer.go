// Package tracer provides distributed tracing utilities.
package tracer

// Span represents a distributed tracing span.
type Span interface {
	SetTag(key string, value interface{})
	SetError(err error)
	Finish()
}

// NoOpSpan is a no-op implementation of Span.
type NoOpSpan struct{}

// SetTag sets a tag on the span.
func (s *NoOpSpan) SetTag(key string, value interface{}) {}

// SetError sets an error on the span.
func (s *NoOpSpan) SetError(err error) {}

// Finish finishes the span.
func (s *NoOpSpan) Finish() {}

// Tracer defines the interface for distributed tracing.
type Tracer interface {
	StartSpan(operationName string) Span
}

// NoOpTracer is a no-op implementation of Tracer.
type NoOpTracer struct{}

// StartSpan starts a new span.
func (t *NoOpTracer) StartSpan(operationName string) Span {
	return &NoOpSpan{}
}

// NewNoOpTracer creates a new no-op tracer.
func NewNoOpTracer() Tracer {
	return &NoOpTracer{}
}
