#!/usr/bin/env python3
"""scan.py — Claude Code capability scanner.

Scans installed plugins, user-level and project-level commands/agents/skills,
and outputs a structured capability inventory. Zero external dependencies.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Capability:
    """A single discoverable capability (command, skill, agent, or hook)."""

    name: str
    capability_type: str   # "command" | "skill" | "agent" | "hook"
    source: str            # "plugin:<name>" | "user" | "project"
    source_path: str       # absolute filesystem path to the defining file
    invocation: str        # how to invoke: "/name", "Use <name> agent", etc.
    description: str       # short description
    permissions: tuple[str, ...] = ()   # allowed-tools list
    provider: str = ""     # marketplace name, e.g. "claude-plugins-official"
    metadata: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Frontmatter parser (YAML subset, no PyYAML)
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---", re.DOTALL)


def parse_frontmatter(text: str) -> dict[str, str | list[str]]:
    """Parse YAML-subset frontmatter delimited by --- markers.

    Supports simple key: value pairs, comma-separated lists in brackets,
    and boolean strings.  Returns an empty dict when no frontmatter found.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}

    result: dict[str, str | list[str]] = {}
    raw_block = match.group(1)

    for line in raw_block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        colon_idx = line.find(":")
        if colon_idx == -1:
            continue

        key = line[:colon_idx].strip()
        value = line[colon_idx + 1:].strip()

        # Handle bracket-wrapped lists: [Read, Glob, Grep, Bash]
        if value.startswith("[") and value.endswith("]"):
            items = [item.strip() for item in value[1:-1].split(",") if item.strip()]
            result[key] = items
        else:
            # Strip surrounding quotes if present
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            result[key] = value

    return result


def extract_body(text: str) -> str:
    """Return markdown body after frontmatter (or entire text if none)."""
    match = _FRONTMATTER_RE.match(text)
    if match:
        return text[match.end():].strip()
    return text.strip()


def extract_description(text: str, frontmatter: dict) -> str:
    """Get description from frontmatter or first non-empty paragraph."""
    desc = frontmatter.get("description", "")
    if isinstance(desc, str) and desc:
        return desc

    body = extract_body(text)
    for line in body.splitlines():
        line = line.strip()
        # Skip headings and empty lines
        if not line or line.startswith("#"):
            continue
        return line

    return ""


# ---------------------------------------------------------------------------
# Markdown file scanner
# ---------------------------------------------------------------------------

def scan_markdown_file(
    path: Path,
    source: str,
    cap_type: str,
) -> Optional[Capability]:
    """Parse a single markdown file into a Capability.

    Args:
        path: absolute path to the .md file
        source: origin label ("plugin:<name>", "user", "project")
        cap_type: "command" | "skill" | "agent"
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    fm = parse_frontmatter(text)
    name = fm.get("name", path.stem)
    if isinstance(name, list):
        name = name[0] if name else path.stem
    description = extract_description(text, fm)

    # Determine invocation method
    if cap_type == "command":
        invocation = f"/{name}"
    elif cap_type == "agent":
        invocation = f"Use {name} agent"
    elif cap_type == "skill":
        invocation = "Auto-triggered by model"
    else:
        invocation = name

    # Parse permissions
    perms_raw = fm.get("allowed-tools", fm.get("tools", []))
    if isinstance(perms_raw, str):
        perms = tuple(p.strip() for p in perms_raw.split(",") if p.strip())
    elif isinstance(perms_raw, list):
        perms = tuple(perms_raw)
    else:
        perms = ()

    # Collect remaining metadata
    skip_keys = {"name", "description", "allowed-tools", "tools"}
    meta = {k: str(v) for k, v in fm.items() if k not in skip_keys}

    return Capability(
        name=str(name),
        capability_type=cap_type,
        source=source,
        source_path=str(path),
        invocation=invocation,
        description=description,
        permissions=perms,
        metadata=meta,
    )


# ---------------------------------------------------------------------------
# Hooks scanner
# ---------------------------------------------------------------------------

def scan_hooks_json(path: Path, plugin_name: str) -> list[Capability]:
    """Parse a hooks.json file and return hook Capabilities."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    hooks_section = data.get("hooks", data)
    if not isinstance(hooks_section, dict):
        return []

    results: list[Capability] = []
    for event_type, entries in hooks_section.items():
        if not isinstance(entries, list):
            continue

        for entry in entries:
            matcher = entry.get("matcher", "*")
            hook_list = entry.get("hooks", [])
            for hook in hook_list:
                cmd = hook.get("command", "")
                hook_name = f"{event_type}:{matcher}"
                results.append(Capability(
                    name=hook_name,
                    capability_type="hook",
                    source=f"plugin:{plugin_name}",
                    source_path=str(path),
                    invocation=f"Auto-trigger on {event_type} matching {matcher}",
                    description=cmd,
                    permissions=(),
                    metadata={"timeout": str(hook.get("timeout", ""))},
                ))

    return results


# ---------------------------------------------------------------------------
# Plugin directory scanner
# ---------------------------------------------------------------------------

def scan_plugin_dir(install_path: Path, provider: str = "") -> list[Capability]:
    """Scan a single plugin installation directory for all capabilities."""
    # Read plugin.json for metadata
    plugin_json_path = install_path / ".claude-plugin" / "plugin.json"
    plugin_name = install_path.name
    try:
        pj = json.loads(plugin_json_path.read_text(encoding="utf-8"))
        plugin_name = pj.get("name", plugin_name)
    except (OSError, json.JSONDecodeError):
        # Try marketplace.json indirection pattern (e.g. semgrep)
        # Structure: .claude-plugin/marketplace.json -> plugins[0].source -> subdir
        marketplace_json = install_path / ".claude-plugin" / "marketplace.json"
        try:
            mj = json.loads(marketplace_json.read_text(encoding="utf-8"))
            # Check plugins array first, then top-level source
            mp_plugins = mj.get("plugins", [])
            source_dir = ""
            if isinstance(mp_plugins, list) and mp_plugins:
                source_dir = mp_plugins[0].get("source", "")
            if not source_dir:
                source_dir = mj.get("source", "")
            if source_dir:
                # Normalize: strip leading "./"
                source_dir = source_dir.lstrip("./")
                alt_path = install_path / source_dir / ".claude-plugin" / "plugin.json"
                if alt_path.is_file():
                    pj = json.loads(alt_path.read_text(encoding="utf-8"))
                    plugin_name = pj.get("name", plugin_name)
                    install_path = install_path / source_dir
        except (OSError, json.JSONDecodeError):
            pass

    source = f"plugin:{plugin_name}"
    caps: list[Capability] = []

    # Scan commands/
    commands_dir = install_path / "commands"
    if commands_dir.is_dir():
        for md in sorted(commands_dir.glob("*.md")):
            cap = scan_markdown_file(md, source, "command")
            if cap:
                caps.append(cap)

    # Scan skills/*/SKILL.md
    skills_dir = install_path / "skills"
    if skills_dir.is_dir():
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            cap = scan_markdown_file(skill_md, source, "skill")
            if cap:
                caps.append(cap)

    # Scan agents/
    agents_dir = install_path / "agents"
    if agents_dir.is_dir():
        for md in sorted(agents_dir.glob("*.md")):
            cap = scan_markdown_file(md, source, "agent")
            if cap:
                caps.append(cap)

    # Scan hooks
    hooks_json = install_path / "hooks" / "hooks.json"
    if hooks_json.is_file():
        caps.extend(scan_hooks_json(hooks_json, plugin_name))

    # Stamp provider on all capabilities from this plugin
    if provider:
        caps = [replace(cap, provider=provider) for cap in caps]

    return caps


# ---------------------------------------------------------------------------
# Installed plugins scanner
# ---------------------------------------------------------------------------

def scan_installed_plugins(home_dir: Path) -> list[Capability]:
    """Read installed_plugins.json and scan each plugin."""
    installed_json = home_dir / ".claude" / "plugins" / "installed_plugins.json"
    try:
        data = json.loads(installed_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    plugins = data.get("plugins", {})
    seen_paths: set[str] = set()
    caps: list[Capability] = []

    for key, installs in plugins.items():
        if not isinstance(installs, list):
            continue

        # Extract provider from key: "plugin-name@marketplace" -> "marketplace"
        provider = key.split("@", 1)[1] if "@" in key else ""

        for entry in installs:
            install_path = entry.get("installPath", "")
            if not install_path or install_path in seen_paths:
                continue
            seen_paths.add(install_path)

            p = Path(install_path)
            if p.is_dir():
                caps.extend(scan_plugin_dir(p, provider=provider))

    return caps


# ---------------------------------------------------------------------------
# Generic directory scanner (user-level / project-level)
# ---------------------------------------------------------------------------

def scan_directory(
    dir_path: Path,
    source: str,
    cap_type: str,
) -> list[Capability]:
    """Scan a directory of markdown files (commands, agents, or skills).

    For skills directories, looks for SKILL.md inside subdirectories.
    For commands/agents, looks for *.md files directly.
    """
    if not dir_path.is_dir():
        return []

    caps: list[Capability] = []

    if cap_type == "skill":
        # Skills use subdirectory pattern: skill-name/SKILL.md
        for skill_md in sorted(dir_path.glob("*/SKILL.md")):
            cap = scan_markdown_file(skill_md, source, cap_type)
            if cap:
                caps.append(cap)
    else:
        # Commands and agents: *.md files (recursive)
        for md in sorted(dir_path.rglob("*.md")):
            cap = scan_markdown_file(md, source, cap_type)
            if cap:
                caps.append(cap)

    return caps


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

def scan_all(
    home_dir: Optional[Path] = None,
    project_dir: Optional[Path] = None,
) -> list[Capability]:
    """Scan all capability sources and return aggregated list."""
    if home_dir is None:
        home_dir = Path.home()
    if project_dir is None:
        project_dir = Path.cwd()

    caps: list[Capability] = []

    # 1. Installed plugins
    caps.extend(scan_installed_plugins(home_dir))

    # 2. User-level directories
    claude_dir = home_dir / ".claude"
    caps.extend(scan_directory(claude_dir / "commands", "user", "command"))
    caps.extend(scan_directory(claude_dir / "agents", "user", "agent"))
    caps.extend(scan_directory(claude_dir / "skills", "user", "skill"))

    # 3. Project-level directories
    project_claude = project_dir / ".claude"
    caps.extend(scan_directory(project_claude / "commands", "project", "command"))
    caps.extend(scan_directory(project_claude / "agents", "project", "agent"))
    caps.extend(scan_directory(project_claude / "skills", "project", "skill"))

    return caps


# ---------------------------------------------------------------------------
# Cache health scanner
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OrphanedVersion:
    """A cached plugin version no longer referenced by installed_plugins.json."""

    plugin_name: str       # directory name under marketplace
    marketplace: str       # marketplace directory name
    version: str           # version directory name
    path: str              # absolute path to orphaned directory
    orphaned_at: str       # ISO timestamp or "unknown"
    size_bytes: int        # total directory size


@dataclass(frozen=True)
class VersionConflict:
    """Same plugin installed at different versions across scopes."""

    plugin_key: str        # e.g. "frontend-design@claude-plugins-official"
    entries: tuple[dict, ...]  # list of {scope, version, installPath}


@dataclass(frozen=True)
class BlockedPlugin:
    """A plugin on the blocklist."""

    key: str               # e.g. "code-review@claude-plugins-official"
    reason: str            # blocklist reason if available


@dataclass(frozen=True)
class CacheHealth:
    """Aggregated cache health report."""

    orphaned_versions: tuple[OrphanedVersion, ...]
    version_conflicts: tuple[VersionConflict, ...]
    blocked_plugins: tuple[BlockedPlugin, ...]
    total_cache_size_bytes: int
    orphaned_size_bytes: int


def _dir_size(path: Path) -> int:
    """Calculate total size of a directory recursively."""
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _parse_orphaned_at(path: Path) -> str:
    """Read .orphaned_at file and convert ms timestamp to ISO string."""
    orphaned_file = path / ".orphaned_at"
    if not orphaned_file.is_file():
        return ""
    try:
        raw = orphaned_file.read_text(encoding="utf-8").strip()
        ts_ms = int(raw)
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OSError, ValueError):
        return "unknown"


def scan_cache_health(home_dir: Optional[Path] = None) -> CacheHealth:
    """Scan plugin cache for orphaned versions, conflicts, and blocklist."""
    if home_dir is None:
        home_dir = Path.home()

    plugins_dir = home_dir / ".claude" / "plugins"
    cache_dir = plugins_dir / "cache"

    # --- Collect active install paths from installed_plugins.json ---
    active_paths: set[str] = set()
    version_map: dict[str, list[dict]] = {}  # key -> [{scope, version, path}]

    installed_json = plugins_dir / "installed_plugins.json"
    try:
        data = json.loads(installed_json.read_text(encoding="utf-8"))
        for key, installs in data.get("plugins", {}).items():
            if not isinstance(installs, list):
                continue
            entries = []
            for entry in installs:
                ip = entry.get("installPath", "")
                if ip:
                    active_paths.add(ip)
                    entries.append({
                        "scope": entry.get("scope", "unknown"),
                        "version": entry.get("version", "unknown"),
                        "installPath": ip,
                    })
            if len(entries) > 1:
                # Check if multiple entries have different versions
                versions = {e["version"] for e in entries}
                if len(versions) > 1:
                    version_map[key] = entries
    except (OSError, json.JSONDecodeError):
        pass

    # --- Scan cache for orphaned versions ---
    orphans: list[OrphanedVersion] = []
    total_cache_size = 0
    orphaned_size = 0

    if cache_dir.is_dir():
        for marketplace_dir in sorted(cache_dir.iterdir()):
            if not marketplace_dir.is_dir():
                continue
            # Skip temp git clone directories at cache root
            if marketplace_dir.name.startswith("temp_git_"):
                continue
            marketplace = marketplace_dir.name
            for plugin_dir in sorted(marketplace_dir.iterdir()):
                if not plugin_dir.is_dir():
                    continue
                plugin_name = plugin_dir.name
                for version_dir in sorted(plugin_dir.iterdir()):
                    if not version_dir.is_dir():
                        continue

                    dir_size = _dir_size(version_dir)
                    total_cache_size += dir_size

                    if str(version_dir) not in active_paths:
                        orphaned_at = _parse_orphaned_at(version_dir)
                        orphans.append(OrphanedVersion(
                            plugin_name=plugin_name,
                            marketplace=marketplace,
                            version=version_dir.name,
                            path=str(version_dir),
                            orphaned_at=orphaned_at,
                            size_bytes=dir_size,
                        ))
                        orphaned_size += dir_size

    # --- Version conflicts ---
    conflicts = [
        VersionConflict(plugin_key=k, entries=tuple(v))
        for k, v in version_map.items()
    ]

    # --- Blocklist ---
    blocked: list[BlockedPlugin] = []
    blocklist_json = plugins_dir / "blocklist.json"
    try:
        bl_data = json.loads(blocklist_json.read_text(encoding="utf-8"))
        for entry in bl_data if isinstance(bl_data, list) else []:
            if isinstance(entry, str):
                blocked.append(BlockedPlugin(key=entry, reason=""))
            elif isinstance(entry, dict):
                blocked.append(BlockedPlugin(
                    key=entry.get("key", entry.get("name", str(entry))),
                    reason=entry.get("reason", ""),
                ))
    except (OSError, json.JSONDecodeError):
        pass

    return CacheHealth(
        orphaned_versions=tuple(orphans),
        version_conflicts=tuple(conflicts),
        blocked_plugins=tuple(blocked),
        total_cache_size_bytes=total_cache_size,
        orphaned_size_bytes=orphaned_size,
    )


def format_cache_health(health: CacheHealth) -> str:
    """Format cache health report as structured text."""
    def _fmt_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"

    lines: list[str] = [
        "=== CACHE HEALTH REPORT ===",
        f"Total cache size: {_fmt_size(health.total_cache_size_bytes)}",
        f"Orphaned size: {_fmt_size(health.orphaned_size_bytes)}",
        "",
    ]

    # Orphaned versions
    lines.append(f"--- ORPHANED VERSIONS ({len(health.orphaned_versions)}) ---")
    lines.append("")
    if not health.orphaned_versions:
        lines.append("(none — cache is clean)")
        lines.append("")
    else:
        for ov in health.orphaned_versions:
            lines.append(f"[{ov.marketplace}/{ov.plugin_name}] v{ov.version}")
            lines.append(f"  Size: {_fmt_size(ov.size_bytes)}")
            lines.append(f"  Orphaned at: {ov.orphaned_at or '(no marker)'}")
            lines.append(f"  Path: {ov.path}")
            lines.append("")

    # Version conflicts
    lines.append(f"--- VERSION CONFLICTS ({len(health.version_conflicts)}) ---")
    lines.append("")
    if not health.version_conflicts:
        lines.append("(none — all plugins use consistent versions)")
        lines.append("")
    else:
        for vc in health.version_conflicts:
            lines.append(f"[{vc.plugin_key}]")
            for e in vc.entries:
                lines.append(f"  scope={e['scope']}  version={e['version']}")
                lines.append(f"    path: {e['installPath']}")
            lines.append("")

    # Blocklist
    lines.append(f"--- BLOCKED PLUGINS ({len(health.blocked_plugins)}) ---")
    lines.append("")
    if not health.blocked_plugins:
        lines.append("(none)")
        lines.append("")
    else:
        for bp in health.blocked_plugins:
            reason = f" — {bp.reason}" if bp.reason else ""
            lines.append(f"  - {bp.key}{reason}")
        lines.append("")

    lines.append("=== END CACHE HEALTH ===")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _group_capabilities(caps: list[Capability]) -> dict[str, list[Capability]]:
    """Group capabilities by source category (plugins / user / project)."""
    groups: dict[str, list[Capability]] = {
        "plugins": [],
        "user": [],
        "project": [],
    }
    for cap in caps:
        if cap.source.startswith("plugin:"):
            groups["plugins"].append(cap)
        elif cap.source == "user":
            groups["user"].append(cap)
        elif cap.source == "project":
            groups["project"].append(cap)
        else:
            groups["plugins"].append(cap)
    return groups


def format_inventory(caps: list[Capability]) -> str:
    """Format full capability inventory as structured text."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = [
        "=== CAPABILITY INVENTORY ===",
        f"Scan time: {now}",
        f"Total capabilities found: {len(caps)}",
        "",
    ]

    groups = _group_capabilities(caps)

    for section, label in [
        ("plugins", "PLUGINS"),
        ("user", "USER-LEVEL"),
        ("project", "PROJECT-LEVEL"),
    ]:
        items = groups[section]
        lines.append(f"--- {label} ({len(items)}) ---")
        lines.append("")

        if not items:
            lines.append("(none found)")
            lines.append("")
            continue

        for cap in items:
            perms_str = ", ".join(cap.permissions) if cap.permissions else "(none)"
            provider_str = f" @{cap.provider}" if cap.provider else ""
            lines.append(f"[{cap.source}] {cap.name} ({cap.capability_type}){provider_str}")
            lines.append(f"  Invocation: {cap.invocation}")
            lines.append(f"  Description: {cap.description}")
            lines.append(f"  Permissions: {perms_str}")
            lines.append(f"  Path: {cap.source_path}")
            lines.append("")

    lines.append("=== END INVENTORY ===")
    return "\n".join(lines)


def format_detail(caps: list[Capability], name: str) -> str:
    """Format detailed view for a single capability by name."""
    # Exact match first, then case-insensitive, then substring
    matches: list[Capability] = []
    for cap in caps:
        if cap.name == name:
            matches = [cap]
            break

    if not matches:
        name_lower = name.lower()
        matches = [c for c in caps if c.name.lower() == name_lower]

    if not matches:
        name_lower = name.lower()
        matches = [c for c in caps if name_lower in c.name.lower()]

    if not matches:
        suggestions = [c.name for c in caps]
        return (
            f"=== CAPABILITY NOT FOUND: {name} ===\n\n"
            f"No capability matching '{name}'.\n\n"
            f"Available capabilities ({len(suggestions)}):\n"
            + "\n".join(f"  - {s}" for s in sorted(set(suggestions)))
            + "\n\n=== END ==="
        )

    lines: list[str] = []
    for cap in matches:
        perms_str = "\n".join(f"  - {p}" for p in cap.permissions) if cap.permissions else "  (none)"
        meta_str = "\n".join(f"  {k}: {v}" for k, v in cap.metadata.items()) if cap.metadata else "  (none)"

        lines.extend([
            f"=== CAPABILITY DETAIL: {cap.name} ===",
            "",
            f"Name: {cap.name}",
            f"Type: {cap.capability_type}",
            f"Source: {cap.source}",
            f"Provider: {cap.provider or '(none)'}",
            f"Invocation: {cap.invocation}",
            f"Path: {cap.source_path}",
            "",
            "Description:",
            f"  {cap.description}",
            "",
            "Permissions (allowed-tools):",
            perms_str,
            "",
            "Metadata:",
            meta_str,
            "",
            "=== END DETAIL ===",
            "",
        ])

    return "\n".join(lines).rstrip()


def format_json(caps: list[Capability]) -> str:
    """Format capabilities as JSON for programmatic consumption."""
    data = []
    for cap in caps:
        d = asdict(cap)
        d["permissions"] = list(cap.permissions)
        data.append(d)
    return json.dumps(data, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Risk scoring
# ---------------------------------------------------------------------------

# Tool weights for risk calculation (higher = riskier)
_TOOL_RISK_WEIGHTS: dict[str, int] = {
    "Bash": 10,
    "Write": 6,
    "Edit": 5,
    "NotebookEdit": 5,
    "WebFetch": 4,
    "WebSearch": 3,
    "Read": 2,
    "Glob": 1,
    "Grep": 1,
    "Task": 3,
}

# Risk level thresholds
_RISK_LEVELS = [
    (0, "low"),
    (5, "medium"),
    (10, "high"),
    (15, "critical"),
]


@dataclass(frozen=True)
class RiskEntry:
    """Risk assessment for a single capability."""

    capability: Capability
    score: int            # 0-30+
    level: str            # "low" | "medium" | "high" | "critical"
    factors: tuple[str, ...]  # human-readable risk factors


def _classify_risk_level(score: int) -> str:
    """Map numeric score to risk level label."""
    level = "low"
    for threshold, label in _RISK_LEVELS:
        if score >= threshold:
            level = label
    return level


def _score_permission(perm: str) -> tuple[int, str]:
    """Score a single permission string and return (points, reason)."""
    # Check for unrestricted Bash (most dangerous)
    perm_upper = perm.strip()
    if perm_upper == "Bash" or perm_upper == "Bash(*)":
        return 15, "Unrestricted Bash access"

    # Check for Bash with pattern (partially restricted)
    if perm_upper.startswith("Bash("):
        return 8, f"Bash access: {perm_upper}"

    # Look up known tools
    for tool_name, weight in _TOOL_RISK_WEIGHTS.items():
        if perm_upper == tool_name or perm_upper.startswith(f"{tool_name}("):
            return weight, f"{tool_name} access"

    # Unknown tool — medium risk by default
    return 3, f"Unknown tool: {perm_upper}"


def score_capability(cap: Capability) -> RiskEntry:
    """Calculate risk score for a single capability."""
    total_score = 0
    factors: list[str] = []

    # Score each permission
    for perm in cap.permissions:
        pts, reason = _score_permission(perm)
        total_score += pts
        factors.append(f"+{pts} {reason}")

    # Hook auto-trigger bonus: hooks run without user invocation
    if cap.capability_type == "hook":
        bonus = 3
        total_score += bonus
        factors.append(f"+{bonus} Auto-triggered hook (no user confirmation)")

        # Wildcard matcher is especially risky
        if ":*" in cap.name or cap.name.endswith(": "):
            extra = 2
            total_score += extra
            factors.append(f"+{extra} Broad/wildcard hook matcher")

    # No permissions declared at all — low risk
    if not cap.permissions and cap.capability_type != "hook":
        factors.append("+0 No tool permissions declared")

    level = _classify_risk_level(total_score)
    return RiskEntry(
        capability=cap,
        score=total_score,
        level=level,
        factors=tuple(factors),
    )


def score_all(caps: list[Capability]) -> list[RiskEntry]:
    """Score all capabilities and return sorted by risk (highest first)."""
    entries = [score_capability(cap) for cap in caps]
    entries.sort(key=lambda e: (-e.score, e.capability.name))
    return entries


def format_risk_report(entries: list[RiskEntry]) -> str:
    """Format risk report as structured text."""
    lines: list[str] = [
        "=== RISK REPORT ===",
        f"Total capabilities assessed: {len(entries)}",
        "",
    ]

    # Summary counts by level
    counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for entry in entries:
        counts[entry.level] = counts.get(entry.level, 0) + 1

    lines.append("--- SUMMARY ---")
    lines.append("")
    for level in ("critical", "high", "medium", "low"):
        lines.append(f"  {level.upper()}: {counts[level]}")
    lines.append("")

    # Detail by risk level (skip low for brevity)
    for level in ("critical", "high", "medium", "low"):
        level_entries = [e for e in entries if e.level == level]
        if not level_entries:
            continue

        lines.append(f"--- {level.upper()} RISK ({len(level_entries)}) ---")
        lines.append("")

        for entry in level_entries:
            cap = entry.capability
            provider_str = f" @{cap.provider}" if cap.provider else ""
            lines.append(
                f"[{cap.source}] {cap.name} ({cap.capability_type}){provider_str}"
                f"  score={entry.score}"
            )
            lines.append(f"  Invocation: {cap.invocation}")
            for factor in entry.factors:
                lines.append(f"    {factor}")
            lines.append("")

    lines.append("=== END RISK REPORT ===")
    return "\n".join(lines)


def format_risk_json(entries: list[RiskEntry]) -> str:
    """Format risk entries as JSON."""
    data = []
    for entry in entries:
        data.append({
            "name": entry.capability.name,
            "capability_type": entry.capability.capability_type,
            "source": entry.capability.source,
            "provider": entry.capability.provider,
            "invocation": entry.capability.invocation,
            "score": entry.score,
            "level": entry.level,
            "factors": list(entry.factors),
            "permissions": list(entry.capability.permissions),
        })
    return json.dumps(data, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Diff — compare two scan snapshots
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DiffResult:
    """Result of comparing two scan snapshots."""

    added: tuple[Capability, ...]    # new capabilities
    removed: tuple[Capability, ...]  # capabilities no longer present
    changed: tuple[tuple[Capability, Capability], ...]  # (old, new) pairs


def _cap_key(cap: Capability) -> str:
    """Unique key for a capability: source + type + name."""
    return f"{cap.source}|{cap.capability_type}|{cap.name}"


def diff_snapshots(
    old_caps: list[Capability],
    new_caps: list[Capability],
) -> DiffResult:
    """Compare two capability lists and return changes."""
    old_map = {_cap_key(c): c for c in old_caps}
    new_map = {_cap_key(c): c for c in new_caps}

    old_keys = set(old_map.keys())
    new_keys = set(new_map.keys())

    added = tuple(new_map[k] for k in sorted(new_keys - old_keys))
    removed = tuple(old_map[k] for k in sorted(old_keys - new_keys))

    # Changed: same key but different content
    changed: list[tuple[Capability, Capability]] = []
    for k in sorted(old_keys & new_keys):
        old_c = old_map[k]
        new_c = new_map[k]
        # Compare significant fields (ignore source_path since it may differ)
        if (
            old_c.description != new_c.description
            or old_c.permissions != new_c.permissions
            or old_c.invocation != new_c.invocation
            or old_c.provider != new_c.provider
            or old_c.metadata != new_c.metadata
        ):
            changed.append((old_c, new_c))

    return DiffResult(
        added=added,
        removed=removed,
        changed=tuple(changed),
    )


def save_snapshot(caps: list[Capability], path: Path) -> None:
    """Save capability snapshot as JSON for later diffing."""
    data = []
    for cap in caps:
        d = asdict(cap)
        d["permissions"] = list(cap.permissions)
        data.append(d)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_snapshot(path: Path) -> list[Capability]:
    """Load capability snapshot from JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    caps: list[Capability] = []
    for d in data:
        d["permissions"] = tuple(d.get("permissions", []))
        d.setdefault("provider", "")
        d.setdefault("metadata", {})
        caps.append(Capability(**d))
    return caps


def format_diff(result: DiffResult) -> str:
    """Format diff result as structured text."""
    total_changes = len(result.added) + len(result.removed) + len(result.changed)
    lines: list[str] = [
        "=== CAPABILITY DIFF ===",
        f"Total changes: {total_changes}",
        f"  Added: {len(result.added)}",
        f"  Removed: {len(result.removed)}",
        f"  Changed: {len(result.changed)}",
        "",
    ]

    if not total_changes:
        lines.append("No changes detected.")
        lines.append("")
        lines.append("=== END DIFF ===")
        return "\n".join(lines)

    if result.added:
        lines.append(f"--- ADDED ({len(result.added)}) ---")
        lines.append("")
        for cap in result.added:
            lines.append(f"  + [{cap.source}] {cap.name} ({cap.capability_type})")
            lines.append(f"    Invocation: {cap.invocation}")
            lines.append(f"    Description: {cap.description}")
            lines.append("")

    if result.removed:
        lines.append(f"--- REMOVED ({len(result.removed)}) ---")
        lines.append("")
        for cap in result.removed:
            lines.append(f"  - [{cap.source}] {cap.name} ({cap.capability_type})")
            lines.append(f"    Invocation: {cap.invocation}")
            lines.append(f"    Description: {cap.description}")
            lines.append("")

    if result.changed:
        lines.append(f"--- CHANGED ({len(result.changed)}) ---")
        lines.append("")
        for old_cap, new_cap in result.changed:
            lines.append(
                f"  ~ [{new_cap.source}] {new_cap.name} ({new_cap.capability_type})"
            )
            if old_cap.description != new_cap.description:
                lines.append(f"    Description: {old_cap.description}")
                lines.append(f"           --> : {new_cap.description}")
            if old_cap.permissions != new_cap.permissions:
                lines.append(f"    Permissions: {', '.join(old_cap.permissions)}")
                lines.append(f"           --> : {', '.join(new_cap.permissions)}")
            if old_cap.invocation != new_cap.invocation:
                lines.append(f"    Invocation: {old_cap.invocation}")
                lines.append(f"          --> : {new_cap.invocation}")
            lines.append("")

    lines.append("=== END DIFF ===")
    return "\n".join(lines)


def format_diff_json(result: DiffResult) -> str:
    """Format diff result as JSON."""
    def _cap_to_dict(cap: Capability) -> dict:
        d = asdict(cap)
        d["permissions"] = list(cap.permissions)
        return d

    data = {
        "added": [_cap_to_dict(c) for c in result.added],
        "removed": [_cap_to_dict(c) for c in result.removed],
        "changed": [
            {"old": _cap_to_dict(o), "new": _cap_to_dict(n)}
            for o, n in result.changed
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build argument parser."""
    parser = argparse.ArgumentParser(
        description="Claude Code capability scanner",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Scan all capabilities and output inventory",
    )
    parser.add_argument(
        "--detail",
        metavar="NAME",
        help="Show detailed info for a specific capability",
    )
    parser.add_argument(
        "--risk",
        action="store_true",
        help="Output risk assessment for all capabilities",
    )
    parser.add_argument(
        "--save-snapshot",
        metavar="PATH",
        help="Save current scan as JSON snapshot for later diffing",
    )
    parser.add_argument(
        "--diff",
        metavar="SNAPSHOT_PATH",
        help="Compare current scan against a saved snapshot",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--cache-health",
        action="store_true",
        help="Report cache health: orphaned versions, version conflicts, blocklist",
    )
    parser.add_argument(
        "--home-dir",
        metavar="PATH",
        help="Override home directory (for testing)",
    )
    parser.add_argument(
        "--project-dir",
        metavar="PATH",
        help="Override project directory (default: CWD)",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    home_dir = Path(args.home_dir) if args.home_dir else None
    project_dir = Path(args.project_dir) if args.project_dir else None

    outputs: list[str] = []

    if args.detail:
        caps = scan_all(home_dir=home_dir, project_dir=project_dir)
        outputs.append(format_detail(caps, args.detail))
    elif args.diff:
        # Compare current scan against saved snapshot
        snapshot_path = Path(args.diff)
        if not snapshot_path.is_file():
            print(f"SNAPSHOT_NOT_FOUND: No snapshot file found at {args.diff}.")
            print()
            print("To create a baseline snapshot, run:")
            print(f"  python scan.py --all --save-snapshot {args.diff}")
            return 0
        old_caps = load_snapshot(snapshot_path)
        new_caps = scan_all(home_dir=home_dir, project_dir=project_dir)
        result = diff_snapshots(old_caps, new_caps)
        if args.format == "json":
            outputs.append(format_diff_json(result))
        else:
            outputs.append(format_diff(result))
    elif args.risk:
        caps = scan_all(home_dir=home_dir, project_dir=project_dir)
        entries = score_all(caps)
        if args.format == "json":
            outputs.append(format_risk_json(entries))
        else:
            outputs.append(format_risk_report(entries))
    elif args.all:
        caps = scan_all(home_dir=home_dir, project_dir=project_dir)
        if args.format == "json":
            outputs.append(format_json(caps))
        else:
            outputs.append(format_inventory(caps))
            if args.cache_health:
                health = scan_cache_health(home_dir=home_dir)
                outputs.append(format_cache_health(health))
        # Save snapshot if requested
        if args.save_snapshot:
            save_snapshot(caps, Path(args.save_snapshot))
    elif args.cache_health:
        health = scan_cache_health(home_dir=home_dir)
        outputs.append(format_cache_health(health))
    else:
        parser.print_help()
        return 1

    print("\n".join(outputs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
