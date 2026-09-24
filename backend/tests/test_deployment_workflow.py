from pathlib import Path
import re


WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "deploy.yml"


def _production_section() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    return text.split("  deploy-production:", 1)[1]


def test_production_deploy_is_skipped_without_both_coolify_credentials() -> None:
    section = _production_section()

    credentials = re.search(
        r"- name: Check production credentials(?P<body>.*?)(?=\n      - name: Trigger Coolify production deployment)",
        section,
        re.DOTALL,
    )
    assert credentials, "production credential gate is missing"
    body = credentials.group("body")
    assert 'echo "available=true"' in body
    assert 'echo "available=false"' in body
    assert "COOLIFY_PRODUCTION_WEBHOOK" in body
    assert "COOLIFY_PRODUCTION_TOKEN" in body

    trigger = section.split("      - name: Trigger Coolify production deployment", 1)[1]
    verify = trigger.split("      - name: Verify production deployment", 1)
    assert len(verify) == 2
    assert "if: steps.credentials.outputs.available == 'true'" in verify[0]
    assert "if: steps.credentials.outputs.available == 'true'" in verify[1]
    assert "PRODUCTION_URL" in verify[1]


def test_missing_production_resource_is_reported_as_a_notice() -> None:
    section = _production_section()
    assert "Production promotion skipped" in section
    assert "No production Coolify resource exists for rbnbrls/add yet" in section
