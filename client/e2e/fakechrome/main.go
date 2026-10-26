// fakechrome records the URL passed by the real Windows client.
package main

import (
	"os"
	"strings"
)

func main() {
	path := os.Getenv("QEUKAO_FAKE_CHROME_LOG")
	if path == "" {
		os.Exit(2)
	}
	file, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		os.Exit(3)
	}
	defer file.Close()
	for _, arg := range os.Args[1:] {
		if strings.HasPrefix(arg, "http://") || strings.HasPrefix(arg, "https://") {
			if _, err := file.WriteString(arg + "\n"); err != nil {
				os.Exit(4)
			}
		}
	}
}
