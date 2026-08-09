package main

import "database/sql"

// Positive control: SQL built from string concatenation (Semgrep flags under p/security-audit).
func unsafeUserLookup(db *sql.DB, userID string) (*sql.Rows, error) {
	return db.Query("SELECT * FROM users WHERE id = " + userID)
}

func main() {}
