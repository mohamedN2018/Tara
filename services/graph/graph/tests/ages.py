"""Test helper: mark accounts as adults the way graph learns it (rule E9b).

Graph keeps an account's age class only from that account's own token
(``graph/age.py``); a fixture account never calls graph, so tests store the class
through the same ``store`` the middleware uses."""

from graph import age


def adult(*account_ids: str) -> None:
    for account_id in account_ids:
        age.store(account_id, age.ADULT)
