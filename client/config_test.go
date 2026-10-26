package main

import (
	"encoding/binary"
	"testing"
)

func TestTrailer(t *testing.T) {
	payload := []byte(`{"v":1,"servers":["http://127.0.0.1:18001"],"enrollKey":"test-key"}`)
	exe := append([]byte("MZ"), payload...)
	exe = binary.LittleEndian.AppendUint32(exe, uint32(len(payload)))
	exe = append(exe, []byte("QKCFG-V1\n")...)
	cfg, err := ParseTrailer(exe)
	if err != nil || cfg == nil || cfg.EnrollKey != "test-key" {
		t.Fatalf("valid trailer: %v %v", cfg, err)
	}
	badMagic := append([]byte(nil), exe...)
	badMagic[len(badMagic)-1] = '!'
	if cfg, err := ParseTrailer(badMagic); err != nil || cfg != nil {
		t.Fatalf("magic mismatch: %v %v", cfg, err)
	}
	oversized := append([]byte(nil), exe...)
	binary.LittleEndian.PutUint32(oversized[len(oversized)-13:], ^uint32(0))
	for _, data := range [][]byte{oversized, []byte("QKCFG-V1\n"), append([]byte("MZ{"), exe[len(exe)-13:]...)} {
		if _, err := ParseTrailer(data); err == nil {
			t.Fatal("accepted truncated/out-of-bounds trailer")
		}
	}
}
