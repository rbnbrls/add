#!/usr/bin/env python3
"""The Coolify deployment-authorisation contract, owned in one place.

Both the backend contract test and the CI shell gate used to pin the *literal*
text of the workflow's ``--header`` argument. That made an ordinary refactor of
the workflow — composing the header from a shell variable instead of spelling it
inline — fail the suite with a bare ``assert 0 == 2`` and no hint that the
workflow was still correct. CI run #30 failed exactly that way after a
reconciliation merge left the refactored workflow next to the old assertion.

These functions assert the invariant — every request to the Coolify webhook
authenticates with the token under the Bearer scheme — and stay silent about how
the header is spelled, so the guard keeps its meaning across a refactor and
cannot turn a harmless edit into a red build.

Run it directly for the same verdict the CI shell gate reports:

    python3 scripts/deployment_contract.py [.github/workflows/deploy.yml]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

#: The workflow the contract is asserted against when no path is given.
DEFAULT_WORKFLOW = Path(".github/workflows/deploy.yml")
#: The two Coolify requests must post to the webhook, not to an arbitrary URL.
WEBHOOK = "$COOLIFY_WEBHOOK"
#: ``$COOLIFY_TOKEN`` or ``${COOLIFY_TOKEN}``: the ordinary shell spellings.
TOKEN_RE = re.compile(r"\$\{?COOLIFY_TOKEN\}?")
#: The value of a ``--header`` argument, in either quoting style GitHub uses.
HEADER_RE = re.compile(r'--header "([^"]*)"')
#: A secret scanner redacts a committed credential to this; no request may ship it.
PLACEHOLDER = "Bearer ***"
#: How many Coolify requests the workflow makes: the test and production jobs.
REQUESTS = 2


def logical_lines(workflow: str) -> list[str]:
    """Shell logical lines: a trailing backslash joins the next physical line."""
    return workflow.replace("\\\n", " ").splitlines()


def coolify_requests(workflow: str) -> list[str]:
    """The logical lines that POST to the Coolify webhook."""
    return [
        line for line in logical_lines(workflow)
        if "curl" in line and WEBHOOK in line
    ]


def token_headers(workflow: str) -> list[str]:
    """Every ``--header`` value that carries the Coolify token."""
    return [
        value
        for line in logical_lines(workflow)
        for value in HEADER_RE.findall(line)
        if TOKEN_RE.search(value)
    ]


def violations(workflow: str) -> list[str]:
    """Return the contract violations; an empty list means the contract holds."""
    problems: list[str] = []
    requests = coolify_requests(workflow)
    if len(requests) != REQUESTS:
        problems.append(
            f"expected {REQUESTS} curl requests to {WEBHOOK}, found {len(requests)}")
    headers = token_headers(workflow)
    if len(headers) != REQUESTS:
        problems.append(
            f"expected {REQUESTS} token-bearing --header arguments, found {len(headers)}")
    for value in headers:
        if "Bearer" not in value:
            problems.append(f"header does not use the Bearer scheme: {value!r}")
    # The scheme name may be written inline or defined once and referenced by the
    # header, so count the definitions rather than requiring them on the header
    # line — the indirection is exactly what a naive literal match used to miss.
    definitions = len(re.findall(r"Authorization:", workflow))
    if definitions != REQUESTS:
        problems.append(
            f"expected {REQUESTS} Authorization definitions, found {definitions}")
    if PLACEHOLDER in workflow:
        problems.append("literal redacted authorization header remains")
    return problems


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_WORKFLOW
    if not path.is_file():
        print(f"deployment contract: missing {path}", file=sys.stderr)
        return 1
    problems = violations(path.read_text(encoding="utf-8"))
    for problem in problems:
        print(f"deployment contract: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("deployment workflow authentication verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
