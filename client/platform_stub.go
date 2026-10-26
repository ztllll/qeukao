//go:build !windows

package main

import (
	"errors"
	"os/exec"
)

func installSelf() (bool, error)              { return false, nil }
func singleInstance(string) (func(), bool)    { return func() {}, true }
func hideProcess(*exec.Cmd)                   {}
func runTray()                                {}
func setTrayConnected(bool)                   {}
func showNotice(string, func(), func()) error { return errors.New("Win32 popup requires Windows") }
func openChrome(string, string) (string, error) {
	return "", errors.New("Chrome launcher requires Windows")
}
