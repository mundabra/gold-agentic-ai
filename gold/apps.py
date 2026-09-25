"""Apps: what GOLD serves. The platform is the same for every app; an app is a folder.

    apps/<your_app>/
      app.yaml          the manifest (below)
      instructions.md   what the app's orchestrator is told to do
      agents/, tools/   its A2A agents and MCP tool servers (optional: apps can reuse other apps' agents)

    # app.yaml
    name: data-analyst                    # id used in the API (/api/ask {"app": ...}), audit and sessions
    title: Talk to your Data
    description: One sentence for the app picker.
    instructions: instructions.md
    read_only: true                       # block requests to change data before any model call
    agents: [Definitions agent, SQL agent]  # registry agents this app may call, by Agent Card name
    components:                           # what `gold serve <component>` runs
      sql-agent: apps.data_analyst.agents.sql_agent
    cli: apps.data_analyst.cli            # optional: adds `gold <command>`s (register(sub), run(args))
    scripted: apps.data_analyst.scripted  # optional: canned replies for the scripted stand-in model
    hooks:                                # optional: app code the platform calls at set points
      check_correction: apps.data_analyst.curation:check_correction   # validate a user's correction
    ui:
      placeholder: Ask a question about your business data
      examples: ["What was our revenue by country last year?"]

An agent can also join an app without a manifest change: give one of its Agent Card
skills the tag "app:<name>" (see apps/data_analyst/examples/trends_agent.py).

Apps are found in the `apps` package and in any package listed in GOLD_APP_PACKAGES;
GOLD_APPS limits which are served.
"""

import importlib
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from pathlib import Path

import yaml

from gold import config


@dataclass(frozen=True)
class App:
    name: str
    title: str
    description: str
    instructions: str
    read_only: bool = False
    agents: tuple[str, ...] = ()
    components: dict = field(default_factory=dict)
    cli: str | None = None
    scripted: str | None = None
    hooks: dict = field(default_factory=dict)
    ui: dict = field(default_factory=dict)
    path: Path | None = None

    def serves(self, entry: dict) -> bool:
        """Whether a registry entry (an agent) belongs to this app."""
        tags = {t for s in entry.get("skills", []) for t in s.get("tags", [])}
        return entry.get("name") in self.agents or f"app:{self.name}" in tags

    def hook(self, name: str):
        """The app's function for a hook ("module:function"), or None if the app has none."""
        target = self.hooks.get(name)
        if not target:
            return None
        module, _, function = target.partition(":")
        return getattr(importlib.import_module(module), function)

    def public(self) -> dict:
        return {"name": self.name, "title": self.title, "description": self.description,
                "read_only": self.read_only, "agents": list(self.agents), "ui": self.ui}


def load(folder: Path) -> App:
    manifest = yaml.safe_load((folder / "app.yaml").read_text(encoding="utf-8")) or {}
    missing = [k for k in ("name", "title", "instructions") if not manifest.get(k)]
    if missing:
        raise ValueError(f"{folder}/app.yaml is missing: {', '.join(missing)}")
    instructions = manifest["instructions"]
    if instructions.endswith(".md"):
        instructions = (folder / instructions).read_text(encoding="utf-8").strip()
    return App(
        name=manifest["name"],
        title=manifest["title"],
        description=manifest.get("description", ""),
        instructions=instructions,
        read_only=bool(manifest.get("read_only", False)),
        agents=tuple(manifest.get("agents") or ()),
        components=dict(manifest.get("components") or {}),
        cli=manifest.get("cli"),
        scripted=manifest.get("scripted"),
        hooks=dict(manifest.get("hooks") or {}),
        ui=dict(manifest.get("ui") or {}),
        path=folder,
    )


@cache
def all_apps() -> dict[str, App]:
    """Every app found, in a stable order, limited to GOLD_APPS if it is set."""
    found: dict[str, App] = {}
    for package in ["apps", *config.APP_PACKAGES]:
        try:
            root = Path(str(resources.files(importlib.import_module(package))))
        except ModuleNotFoundError:
            continue
        for manifest in sorted(root.glob("*/app.yaml")):
            app = load(manifest.parent)
            if app.name in found:
                raise ValueError(f"Two apps are named '{app.name}': {found[app.name].path} and {app.path}")
            found[app.name] = app
    if config.APPS:
        unknown = set(config.APPS) - set(found)
        if unknown:
            raise ValueError(f"GOLD_APPS names apps that do not exist: {', '.join(sorted(unknown))}")
        found = {name: found[name] for name in config.APPS}
    return found


def get(name: str | None) -> App:
    """The named app, or the default one (GOLD_DEFAULT_APP, else the first)."""
    apps = all_apps()
    if not apps:
        raise LookupError("No apps found: add one under apps/ (see docs/build-an-app.md).")
    name = name or config.DEFAULT_APP or next(iter(apps))
    if name not in apps:
        raise LookupError(f"No app named '{name}'. Available: {', '.join(apps)}")
    return apps[name]


def components() -> dict[str, str]:
    """Component name -> module, across all apps (for `gold serve`)."""
    merged: dict[str, str] = {}
    for app in all_apps().values():
        for component, module in app.components.items():
            if merged.get(component, module) != module:
                raise ValueError(f"Component '{component}' is defined twice, by different modules.")
            merged[component] = module
    return merged
