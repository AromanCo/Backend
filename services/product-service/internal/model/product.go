// Package model defines domain models for products.
package model

import "time"

// Product represents a perfume product in the system.
type Product struct {
	ID            int64
	ExternalID    string
	Name          string
	Description   string
	Brand         string
	Price         float64
	StockQuantity int
	CreatedAt     time.Time
	UpdatedAt     time.Time
	DeletedAt     *time.Time
}

// IsDeleted checks if the product is soft-deleted.
func (p *Product) IsDeleted() bool {
	return p.DeletedAt != nil
}
