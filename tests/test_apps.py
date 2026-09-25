"""Apps are folders with a manifest; the platform finds them, serves their components and routes to them."""

import pytest

from gold import apps, config


def test_both_sample_apps_are_found_with_their_components():
    found = apps.all_apps()
    assert list(found) == ["data-analyst", "sales-copilot"]
    assert apps.get(None).name == "data-analyst"  # the default: the first app
    components = apps.components()
    assert components["sql-agent"] == "apps.data_analyst.agents.sql_agent"
    assert components["account-agent"] == "apps.sales_copilot.agents.account_agent"
    assert found["data-analyst"].instructions.startswith("You are Talk to your Data")


def test_an_app_serves_the_agents_it_lists_and_agents_that_tag_themselves():
    data = apps.get("data-analyst")
    assert data.serves({"name": "SQL agent"})
    assert not data.serves({"name": "Account agent"})
    assert data.serves({"name": "Trends agent", "skills": [{"tags": ["app:data-analyst"]}]})


def test_apps_declare_document_collections():
    [playbook] = apps.knowledge_collections()
    assert playbook.name == "sales-playbook" and playbook.path.endswith("apps/sales_copilot/knowledge")


def test_hooks_resolve_to_app_code():
    check = apps.get("data-analyst").hook("check_correction")
    assert check("SELECT 1").upper().startswith("SELECT")
    assert apps.get("sales-copilot").hook("check_correction") is None


def test_gold_apps_limits_what_is_served(monkeypatch):
    monkeypatch.setattr(config, "APPS", ["sales-copilot"])
    apps.all_apps.cache_clear()
    try:
        assert list(apps.all_apps()) == ["sales-copilot"]
        with pytest.raises(LookupError):
            apps.get("data-analyst")
        monkeypatch.setattr(config, "APPS", ["nope"])
        apps.all_apps.cache_clear()
        with pytest.raises(ValueError, match="do not exist"):
            apps.all_apps()
    finally:
        apps.all_apps.cache_clear()


def test_a_manifest_needs_a_name_title_and_instructions(tmp_path):
    (tmp_path / "app.yaml").write_text("name: x\n")
    with pytest.raises(ValueError, match="missing: title, instructions"):
        apps.load(tmp_path)


def test_the_platform_never_imports_an_app():
    """gold/ is app-agnostic: apps are found through manifests, never imported by name."""
    from pathlib import Path

    platform = Path(apps.__file__).parent
    offenders = [str(p) for p in platform.rglob("*.py")
                 if any(line.lstrip().startswith(("from apps", "import apps")) for line in p.read_text().splitlines())]
    assert offenders == []
