package main

import (
	"io/ioutil"
	"net/http"
)

// Task-aligned probe: CWE-22-style user-controlled path segment in ReadFile.
func handler(w http.ResponseWriter, r *http.Request) {
	p := r.URL.Query().Get("path")
	b, err := ioutil.ReadFile("/srv/data/" + p)
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	_, _ = w.Write(b)
}

func main() {}
