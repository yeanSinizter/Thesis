package main

import (
	"fmt"
	"io/ioutil"
	"os"
)

// Instrument control: CLI path from os.Args into ReadFile (common model idiom).
func main() {
	if len(os.Args) < 2 {
		fmt.Println("usage: go_path_cli_args <path>")
		os.Exit(1)
	}
	path := os.Args[1]
	data, err := ioutil.ReadFile(path)
	if err != nil {
		fmt.Println(err)
		os.Exit(1)
	}
	fmt.Print(string(data))
}
