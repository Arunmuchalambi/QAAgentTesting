"""Lightweight CI smoke tests (no live Jira/GitHub/LLM calls)."""

from pathlib import Path
import importlib


ROOT = Path(__file__).resolve().parents[1]


def test_required_modules_import():
    modules = [
        "config",
        "jira_client",
        "github_client",
        "qa_agent",
        "product_knowledge",
        "pr_analyzer",
        "sheets_client",
        "pipeline_trigger",
        "test_execution_service",
    ]
    for name in modules:
        importlib.import_module(name)


def test_env_example_exists():
    assert (ROOT / "env.example").exists()


def test_llm_defaults_resolve():
    from config import settings

    assert settings.llm.resolved_provider in {"gemini", "groq", "openai"}
    assert settings.llm.resolved_model
    assert settings.llm.resolved_api_key  # provided by CI env


def test_jira_search_method_exists():
    from jira_client import JiraClient

    assert hasattr(JiraClient, "search_issues")
