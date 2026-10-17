// Package metrics provides Prometheus metrics utilities.
package metrics

// Recorder defines the interface for recording metrics.
type Recorder interface {
	RecordRequestDuration(service, method string, duration float64)
	RecordRequestCount(service, method string)
	RecordError(service, method string)
}

// NoOpRecorder is a no-op implementation of Recorder.
type NoOpRecorder struct{}

// RecordRequestDuration records a request duration.
func (r *NoOpRecorder) RecordRequestDuration(service, method string, duration float64) {}

// RecordRequestCount records a request count.
func (r *NoOpRecorder) RecordRequestCount(service, method string) {}

// RecordError records an error.
func (r *NoOpRecorder) RecordError(service, method string) {}

// NewNoOpRecorder creates a new no-op recorder.
func NewNoOpRecorder() Recorder {
	return &NoOpRecorder{}
}
