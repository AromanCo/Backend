package helper

import (
	"crypto/rand"
	"strconv"
)

func RandomNumbers(lenght int) (int, error) {

	const numbers = "1234567890"

	buffer := make([]byte, lenght)
	_, err := rand.Read(buffer)

	if err != nil {
		return 0, err
	}

	numLenght := len(numbers)
	for i := 0; i < lenght; i++ {
		buffer[i] = numbers[int(buffer[i])%numLenght]
	}
	return strconv.Atoi(string(buffer))
}
