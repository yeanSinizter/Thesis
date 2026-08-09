"""Positive control: subprocess with shell=True (Bandit B602)."""
import subprocess


def unsafe_ls(user_fragment: str) -> None:
    subprocess.call("ls -la " + user_fragment, shell=True)
