"""Small GitHub Issues API client used by the user feedback endpoint."""

from dataclasses import dataclass

import httpx


@dataclass
class GitHubIssueResult:
    success: bool
    issue_url: str | None = None
    issue_number: int | None = None
    error: str | None = None
    status_code: int | None = None


async def create_github_issue(
    *, token: str, repository: str, title: str, body: str, labels: list[str]
) -> GitHubIssueResult:
    """Create one issue without exposing the GitHub token to the browser."""
    if "/" not in repository or repository.count("/") != 1:
        return GitHubIssueResult(False, error="GitHub repository must be owner/repository.")

    owner, repo = repository.split("/", 1)
    url = f"https://api.github.com/repos/{owner}/{repo}/issues"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "add-feedback",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                url,
                headers=headers,
                json={"title": title, "body": body, "labels": labels},
            )
    except httpx.RequestError as exc:
        return GitHubIssueResult(False, error=f"GitHub niet bereikbaar: {exc}")

    if response.is_error:
        if response.status_code in {401, 403}:
            message = "GitHub-toegang geweigerd. Controleer GITHUB_TOKEN en repositoryrechten."
        elif response.status_code == 404:
            message = "GitHub-repository niet gevonden. Controleer GITHUB_REPO."
        elif response.status_code == 422:
            message = "GitHub kon deze issue niet valideren."
        else:
            message = f"GitHub gaf fout {response.status_code}."
        return GitHubIssueResult(False, error=message, status_code=response.status_code)

    try:
        payload = response.json()
        return GitHubIssueResult(
            True,
            issue_url=payload["html_url"],
            issue_number=payload["number"],
        )
    except (KeyError, ValueError, TypeError):
        return GitHubIssueResult(False, error="GitHub gaf een ongeldig antwoord.", status_code=response.status_code)
