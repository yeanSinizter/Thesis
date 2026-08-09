"""Positive control: SQL built from string concatenation (Bandit B608 class)."""
import sqlite3


def unsafe_lookup(user_id: str):
    conn = sqlite3.connect(":memory:")
    # nosec comments intentionally omitted — this file is meant to trigger Bandit.
    return conn.execute("SELECT * FROM users WHERE id = " + str(user_id)).fetchall()
