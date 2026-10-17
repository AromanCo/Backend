package main

import (
	"testing"
	"net/http"
	"net/http/httptest"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
)

func TestHealthEndpoint(t *testing.T) {
	router := gin.Default()
	
	router.GET("/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{
			"status": "ok",
		})
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/health", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)
	assert.Contains(t, w.Body.String(), "ok")
}
