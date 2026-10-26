package main

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"errors"
	"net/url"
	"os"
	"strings"
)

type Config struct {
	V         int      `json:"v"`
	Servers   []string `json:"servers"`
	EnrollKey string   `json:"enrollKey"`
	Name      string   `json:"name"`
}

func (c *Config) Validate() error {
	if c.V != 1 || len(c.Servers) == 0 || c.EnrollKey == "" {
		return errors.New("invalid client configuration")
	}
	for i, s := range c.Servers {
		u, e := url.Parse(s)
		if e != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
			return errors.New("invalid server URL")
		}
		c.Servers[i] = strings.TrimRight(s, "/")
	}
	return nil
}

// ParseTrailer accepts only the versioned overlay; a magic mismatch means development mode.
func ParseTrailer(data []byte) (*Config, error) {
	magic := []byte("QKCFG-V1\n")
	if !bytes.HasSuffix(data, magic) {
		return nil, nil
	}
	if len(data) < 13 {
		return nil, errors.New("truncated trailer")
	}
	n := uint64(binary.LittleEndian.Uint32(data[len(data)-13:]))
	if n == 0 || n > uint64(len(data)-13) {
		return nil, errors.New("trailer length out of bounds")
	}
	var cfg Config
	if err := json.Unmarshal(data[len(data)-13-int(n):len(data)-13], &cfg); err != nil {
		return nil, err
	}
	return &cfg, cfg.Validate()
}

func loadConfig(server, key string) (*Config, error) {
	path, err := os.Executable()
	if err != nil {
		return nil, err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	cfg, err := ParseTrailer(data)
	if err != nil || cfg != nil {
		return cfg, err
	}
	cfg = &Config{V: 1, Servers: []string{server}, EnrollKey: key}
	return cfg, cfg.Validate()
}
