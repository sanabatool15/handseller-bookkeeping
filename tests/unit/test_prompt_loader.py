import pytest

from ai_agents.prompt_loader import load_prompt


def test_load_prompt_returns_content():
    text = load_prompt("financial_advisor_system")
    assert "financial advisor" in text.lower()


def test_load_prompt_formats_placeholders():
    text = load_prompt("financial_audit", org_id="org-1", year=2026, month=1, ledger_csv="type,date\n")
    assert "org-1" in text
    assert "2026-01" in text


def test_load_prompt_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_prompt("does_not_exist")
