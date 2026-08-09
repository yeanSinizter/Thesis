"""Lightweight tests for dynamic validation proxy logic."""

from dynamic_validation import evaluate_sample


def test_python_sqli_blocked():
    code = """
import sqlite3
def login(username, password):
    conn = sqlite3.connect("a.db")
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password))
    return cur.fetchone()
"""
    out = evaluate_sample("py_sql_login", "SQL Injection", "Python", code)
    assert out["dynamic_exploit_blocked"] is True


def test_python_sqli_not_blocked():
    code = """
import sqlite3
def login(username, password):
    query = f"SELECT * FROM users WHERE username='{username}' AND password='{password}'"
    return conn.execute(query).fetchone()
"""
    out = evaluate_sample("py_sql_login", "SQL Injection", "Python", code)
    assert out["dynamic_exploit_blocked"] is False


if __name__ == "__main__":
    test_python_sqli_blocked()
    test_python_sqli_not_blocked()
    print("dynamic_validation tests OK")
