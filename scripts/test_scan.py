#!/usr/bin/env python3
"""Unit tests for scan.py — Claude Code capability scanner."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scan import (
    CacheHealth,
    Capability,
    DiffResult,
    RiskEntry,
    diff_snapshots,
    extract_body,
    extract_description,
    format_cache_health,
    format_detail,
    format_diff,
    format_diff_json,
    format_inventory,
    format_json,
    format_risk_json,
    format_risk_report,
    load_snapshot,
    parse_frontmatter,
    save_snapshot,
    scan_all,
    scan_cache_health,
    scan_directory,
    scan_hooks_json,
    scan_installed_plugins,
    scan_markdown_file,
    scan_plugin_dir,
    score_all,
    score_capability,
)


class TestParseFrontmatter(unittest.TestCase):
    """Tests for YAML-subset frontmatter parser."""

    def should_parse_simple_key_value_when_valid_frontmatter(self):
        text = "---\nname: test-cmd\ndescription: A test command\n---\n# Body"
        result = parse_frontmatter(text)
        self.assertEqual(result["name"], "test-cmd")
        self.assertEqual(result["description"], "A test command")

    def should_return_empty_dict_when_no_frontmatter(self):
        text = "# Just a heading\nSome body text."
        result = parse_frontmatter(text)
        self.assertEqual(result, {})

    def should_parse_bracket_list_when_allowed_tools(self):
        text = "---\nallowed-tools: [Read, Glob, Grep, Bash]\n---\n"
        result = parse_frontmatter(text)
        self.assertEqual(result["allowed-tools"], ["Read", "Glob", "Grep", "Bash"])

    def should_handle_quoted_values_when_present(self):
        text = '---\nname: "my-skill"\ndescription: \'A skill\'\n---\n'
        result = parse_frontmatter(text)
        self.assertEqual(result["name"], "my-skill")
        self.assertEqual(result["description"], "A skill")

    def should_skip_comments_when_in_frontmatter(self):
        text = "---\nname: test\n# This is a comment\ndescription: hello\n---\n"
        result = parse_frontmatter(text)
        self.assertEqual(result["name"], "test")
        self.assertEqual(result["description"], "hello")

    def should_handle_empty_frontmatter_when_delimiters_only(self):
        text = "---\n---\nBody"
        result = parse_frontmatter(text)
        self.assertEqual(result, {})

    def should_handle_complex_allowed_tools_when_bash_patterns(self):
        text = "---\nallowed-tools: [Bash(git add:*), Bash(git commit:*)]\n---\n"
        result = parse_frontmatter(text)
        self.assertEqual(
            result["allowed-tools"],
            ["Bash(git add:*)", "Bash(git commit:*)"],
        )


class TestExtractBody(unittest.TestCase):
    """Tests for body extraction after frontmatter."""

    def should_return_body_after_frontmatter_when_present(self):
        text = "---\nname: test\n---\n# Heading\nBody text."
        result = extract_body(text)
        self.assertEqual(result, "# Heading\nBody text.")

    def should_return_full_text_when_no_frontmatter(self):
        text = "# Heading\nBody text."
        result = extract_body(text)
        self.assertEqual(result, "# Heading\nBody text.")


class TestExtractDescription(unittest.TestCase):
    """Tests for description extraction."""

    def should_use_frontmatter_description_when_present(self):
        text = "---\ndescription: From frontmatter\n---\nFirst paragraph."
        fm = parse_frontmatter(text)
        result = extract_description(text, fm)
        self.assertEqual(result, "From frontmatter")

    def should_use_first_paragraph_when_no_frontmatter_description(self):
        text = "---\nname: test\n---\n# Heading\n\nFirst paragraph here."
        fm = parse_frontmatter(text)
        result = extract_description(text, fm)
        self.assertEqual(result, "First paragraph here.")

    def should_skip_headings_when_extracting_from_body(self):
        text = "# Title\n## Subtitle\nActual content."
        fm = {}
        result = extract_description(text, fm)
        self.assertEqual(result, "Actual content.")

    def should_return_empty_string_when_no_content(self):
        text = ""
        fm = {}
        result = extract_description(text, fm)
        self.assertEqual(result, "")


class TestScanMarkdownFile(unittest.TestCase):
    """Tests for single markdown file scanning."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def should_extract_command_capability_when_valid_md(self):
        cmd_file = self.tmpdir / "test-cmd.md"
        cmd_file.write_text(
            "---\n"
            "description: A test command\n"
            "allowed-tools: [Read, Bash]\n"
            "---\n"
            "# Test Command\nDo something.\n"
        )
        cap = scan_markdown_file(cmd_file, "plugin:test", "command")
        self.assertIsNotNone(cap)
        self.assertEqual(cap.name, "test-cmd")
        self.assertEqual(cap.capability_type, "command")
        self.assertEqual(cap.invocation, "/test-cmd")
        self.assertEqual(cap.description, "A test command")
        self.assertEqual(cap.permissions, ("Read", "Bash"))
        self.assertEqual(cap.source, "plugin:test")

    def should_extract_skill_capability_when_skill_md(self):
        skill_dir = self.tmpdir / "my-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: my-skill\n"
            "description: A test skill\n"
            "tools: Read, Glob, Grep\n"
            "---\n"
            "# My Skill\nDetails.\n"
        )
        cap = scan_markdown_file(skill_file, "user", "skill")
        self.assertIsNotNone(cap)
        self.assertEqual(cap.name, "my-skill")
        self.assertEqual(cap.invocation, "Auto-triggered by model")
        self.assertEqual(cap.permissions, ("Read", "Glob", "Grep"))

    def should_extract_agent_capability_when_agent_md(self):
        agent_file = self.tmpdir / "code-reviewer.md"
        agent_file.write_text(
            "---\n"
            "name: code-reviewer\n"
            "description: Reviews code for quality\n"
            "model: sonnet\n"
            "---\n"
            "You are a code reviewer.\n"
        )
        cap = scan_markdown_file(agent_file, "plugin:test", "agent")
        self.assertIsNotNone(cap)
        self.assertEqual(cap.name, "code-reviewer")
        self.assertEqual(cap.invocation, "Use code-reviewer agent")
        self.assertEqual(cap.metadata["model"], "sonnet")

    def should_use_filename_when_no_name_in_frontmatter(self):
        cmd_file = self.tmpdir / "my-command.md"
        cmd_file.write_text("---\ndescription: No name field\n---\nBody.\n")
        cap = scan_markdown_file(cmd_file, "user", "command")
        self.assertEqual(cap.name, "my-command")

    def should_return_none_when_file_not_readable(self):
        cap = scan_markdown_file(self.tmpdir / "nonexistent.md", "user", "command")
        self.assertIsNone(cap)


class TestScanHooksJson(unittest.TestCase):
    """Tests for hooks.json scanning."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def should_parse_hook_entries_when_valid_json(self):
        hooks_file = self.tmpdir / "hooks.json"
        hooks_file.write_text(json.dumps({
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "Write|Edit",
                        "hooks": [
                            {"type": "command", "command": "lint.sh", "timeout": 30}
                        ],
                    }
                ]
            }
        }))
        caps = scan_hooks_json(hooks_file, "test-plugin")
        self.assertEqual(len(caps), 1)
        self.assertEqual(caps[0].name, "PostToolUse:Write|Edit")
        self.assertEqual(caps[0].capability_type, "hook")
        self.assertEqual(caps[0].description, "lint.sh")
        self.assertEqual(caps[0].source, "plugin:test-plugin")

    def should_handle_multiple_event_types_when_present(self):
        hooks_file = self.tmpdir / "hooks.json"
        hooks_file.write_text(json.dumps({
            "hooks": {
                "PostToolUse": [
                    {"matcher": "Edit", "hooks": [{"command": "lint.sh"}]}
                ],
                "SessionStart": [
                    {"matcher": "startup", "hooks": [{"command": "init.sh"}]}
                ],
            }
        }))
        caps = scan_hooks_json(hooks_file, "test")
        self.assertEqual(len(caps), 2)
        names = {c.name for c in caps}
        self.assertIn("PostToolUse:Edit", names)
        self.assertIn("SessionStart:startup", names)

    def should_return_empty_when_invalid_json(self):
        hooks_file = self.tmpdir / "hooks.json"
        hooks_file.write_text("not json")
        caps = scan_hooks_json(hooks_file, "test")
        self.assertEqual(caps, [])


class TestScanPluginDir(unittest.TestCase):
    """Tests for plugin directory scanning."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _create_plugin(self, name: str, *, commands=None, skills=None, agents=None):
        """Helper to create a mock plugin directory."""
        plugin_dir = self.tmpdir / name
        meta_dir = plugin_dir / ".claude-plugin"
        meta_dir.mkdir(parents=True)
        (meta_dir / "plugin.json").write_text(
            json.dumps({"name": name, "description": f"Plugin {name}"})
        )

        if commands:
            cmd_dir = plugin_dir / "commands"
            cmd_dir.mkdir()
            for cmd_name, desc in commands.items():
                (cmd_dir / f"{cmd_name}.md").write_text(
                    f"---\ndescription: {desc}\n---\n# {cmd_name}\n"
                )

        if skills:
            skills_dir = plugin_dir / "skills"
            skills_dir.mkdir()
            for skill_name, desc in skills.items():
                skill_sub = skills_dir / skill_name
                skill_sub.mkdir()
                (skill_sub / "SKILL.md").write_text(
                    f"---\nname: {skill_name}\ndescription: {desc}\n---\n"
                )

        if agents:
            agents_dir = plugin_dir / "agents"
            agents_dir.mkdir()
            for agent_name, desc in agents.items():
                (agents_dir / f"{agent_name}.md").write_text(
                    f"---\nname: {agent_name}\ndescription: {desc}\n---\n"
                )

        return plugin_dir

    def should_find_commands_when_commands_dir_exists(self):
        plugin_dir = self._create_plugin(
            "test-plugin",
            commands={"do-stuff": "Does stuff"},
        )
        caps = scan_plugin_dir(plugin_dir)
        cmd_caps = [c for c in caps if c.capability_type == "command"]
        self.assertEqual(len(cmd_caps), 1)
        self.assertEqual(cmd_caps[0].name, "do-stuff")
        self.assertEqual(cmd_caps[0].source, "plugin:test-plugin")

    def should_find_skills_when_skills_dir_exists(self):
        plugin_dir = self._create_plugin(
            "test-plugin",
            skills={"my-skill": "A skill"},
        )
        caps = scan_plugin_dir(plugin_dir)
        skill_caps = [c for c in caps if c.capability_type == "skill"]
        self.assertEqual(len(skill_caps), 1)
        self.assertEqual(skill_caps[0].name, "my-skill")

    def should_find_agents_when_agents_dir_exists(self):
        plugin_dir = self._create_plugin(
            "test-plugin",
            agents={"reviewer": "Reviews code"},
        )
        caps = scan_plugin_dir(plugin_dir)
        agent_caps = [c for c in caps if c.capability_type == "agent"]
        self.assertEqual(len(agent_caps), 1)
        self.assertEqual(agent_caps[0].name, "reviewer")

    def should_find_hooks_when_hooks_json_exists(self):
        plugin_dir = self._create_plugin("test-plugin")
        hooks_dir = plugin_dir / "hooks"
        hooks_dir.mkdir()
        (hooks_dir / "hooks.json").write_text(json.dumps({
            "hooks": {
                "PostToolUse": [
                    {"matcher": "Edit", "hooks": [{"command": "check.sh"}]}
                ]
            }
        }))
        caps = scan_plugin_dir(plugin_dir)
        hook_caps = [c for c in caps if c.capability_type == "hook"]
        self.assertEqual(len(hook_caps), 1)

    def should_read_plugin_name_from_plugin_json(self):
        plugin_dir = self._create_plugin(
            "my-plugin",
            commands={"cmd": "A command"},
        )
        caps = scan_plugin_dir(plugin_dir)
        self.assertTrue(all(c.source == "plugin:my-plugin" for c in caps))

    def should_handle_marketplace_indirection_when_present(self):
        # Create marketplace-style plugin (like semgrep)
        root = self.tmpdir / "mp-plugin"
        mp_meta = root / ".claude-plugin"
        mp_meta.mkdir(parents=True)
        (mp_meta / "marketplace.json").write_text(json.dumps({
            "name": "marketplace-entry",
            "plugins": [
                {"name": "inner-plugin", "source": "./inner"}
            ],
        }))

        inner_dir = root / "inner"
        inner_meta = inner_dir / ".claude-plugin"
        inner_meta.mkdir(parents=True)
        (inner_meta / "plugin.json").write_text(
            json.dumps({"name": "inner-plugin"})
        )
        cmd_dir = inner_dir / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "setup.md").write_text(
            "---\ndescription: Setup command\n---\n# Setup\n"
        )

        caps = scan_plugin_dir(root)
        self.assertTrue(len(caps) >= 1)
        self.assertEqual(caps[0].source, "plugin:inner-plugin")


class TestScanDirectory(unittest.TestCase):
    """Tests for generic directory scanning."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def should_find_md_files_when_directory_exists(self):
        cmd_dir = self.tmpdir / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "hello.md").write_text(
            "---\ndescription: Say hello\n---\n# Hello\n"
        )
        (cmd_dir / "goodbye.md").write_text(
            "---\ndescription: Say goodbye\n---\n# Goodbye\n"
        )
        caps = scan_directory(cmd_dir, "user", "command")
        self.assertEqual(len(caps), 2)
        names = {c.name for c in caps}
        self.assertEqual(names, {"hello", "goodbye"})

    def should_return_empty_when_directory_missing(self):
        caps = scan_directory(self.tmpdir / "nonexistent", "user", "command")
        self.assertEqual(caps, [])

    def should_find_skill_md_when_skill_type(self):
        skills_dir = self.tmpdir / "skills"
        skill_sub = skills_dir / "my-skill"
        skill_sub.mkdir(parents=True)
        (skill_sub / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A skill\n---\n"
        )
        caps = scan_directory(skills_dir, "user", "skill")
        self.assertEqual(len(caps), 1)
        self.assertEqual(caps[0].name, "my-skill")

    def should_recurse_subdirectories_when_nested_commands(self):
        cmd_dir = self.tmpdir / "commands"
        sub_dir = cmd_dir / "sub"
        sub_dir.mkdir(parents=True)
        (sub_dir / "nested.md").write_text(
            "---\ndescription: Nested command\n---\n"
        )
        caps = scan_directory(cmd_dir, "user", "command")
        self.assertEqual(len(caps), 1)
        self.assertEqual(caps[0].name, "nested")


class TestScanInstalledPlugins(unittest.TestCase):
    """Tests for installed_plugins.json scanning."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def should_scan_plugins_from_installed_json(self):
        # Create mock home dir structure
        plugins_dir = self.tmpdir / ".claude" / "plugins"
        plugins_dir.mkdir(parents=True)

        # Create a mock plugin
        plugin_dir = self.tmpdir / "cache" / "test-plugin" / "1.0.0"
        meta_dir = plugin_dir / ".claude-plugin"
        meta_dir.mkdir(parents=True)
        (meta_dir / "plugin.json").write_text(
            json.dumps({"name": "test-plugin"})
        )
        cmd_dir = plugin_dir / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "test.md").write_text(
            "---\ndescription: Test command\n---\n"
        )

        # Write installed_plugins.json
        (plugins_dir / "installed_plugins.json").write_text(json.dumps({
            "version": 2,
            "plugins": {
                "test-plugin@marketplace": [
                    {
                        "scope": "user",
                        "installPath": str(plugin_dir),
                        "version": "1.0.0",
                    }
                ]
            },
        }))

        caps = scan_installed_plugins(self.tmpdir)
        self.assertEqual(len(caps), 1)
        self.assertEqual(caps[0].name, "test")
        self.assertEqual(caps[0].source, "plugin:test-plugin")

    def should_return_empty_when_no_installed_json(self):
        caps = scan_installed_plugins(self.tmpdir)
        self.assertEqual(caps, [])

    def should_deduplicate_paths_when_same_plugin_multiple_scopes(self):
        plugins_dir = self.tmpdir / ".claude" / "plugins"
        plugins_dir.mkdir(parents=True)

        plugin_dir = self.tmpdir / "cache" / "dup" / "1.0.0"
        meta_dir = plugin_dir / ".claude-plugin"
        meta_dir.mkdir(parents=True)
        (meta_dir / "plugin.json").write_text(
            json.dumps({"name": "dup-plugin"})
        )

        (plugins_dir / "installed_plugins.json").write_text(json.dumps({
            "version": 2,
            "plugins": {
                "dup@mp": [
                    {"scope": "user", "installPath": str(plugin_dir)},
                    {"scope": "project", "installPath": str(plugin_dir)},
                ]
            },
        }))

        caps = scan_installed_plugins(self.tmpdir)
        # Should not scan the same path twice
        self.assertEqual(len(caps), 0)  # No commands/skills/agents in this plugin


class TestScanAll(unittest.TestCase):
    """Integration tests for full scan."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def should_aggregate_all_sources_when_called(self):
        # Create user-level commands
        user_cmds = self.tmpdir / ".claude" / "commands"
        user_cmds.mkdir(parents=True)
        (user_cmds / "user-cmd.md").write_text(
            "---\ndescription: User command\n---\n"
        )

        # Create user-level agents
        user_agents = self.tmpdir / ".claude" / "agents"
        user_agents.mkdir(parents=True)
        (user_agents / "user-agent.md").write_text(
            "---\nname: user-agent\ndescription: User agent\n---\n"
        )

        # Create project-level commands
        project_dir = self.tmpdir / "project"
        project_cmds = project_dir / ".claude" / "commands"
        project_cmds.mkdir(parents=True)
        (project_cmds / "proj-cmd.md").write_text(
            "---\ndescription: Project command\n---\n"
        )

        # Create installed_plugins.json (empty)
        plugins_dir = self.tmpdir / ".claude" / "plugins"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "installed_plugins.json").write_text(
            json.dumps({"version": 2, "plugins": {}})
        )

        caps = scan_all(home_dir=self.tmpdir, project_dir=project_dir)
        self.assertEqual(len(caps), 3)

        sources = {c.source for c in caps}
        self.assertIn("user", sources)
        self.assertIn("project", sources)

    def should_handle_missing_directories_gracefully(self):
        empty_home = self.tmpdir / "empty-home"
        empty_home.mkdir()
        empty_project = self.tmpdir / "empty-project"
        empty_project.mkdir()
        caps = scan_all(home_dir=empty_home, project_dir=empty_project)
        self.assertEqual(caps, [])


class TestFormatInventory(unittest.TestCase):
    """Tests for inventory text formatting."""

    def should_produce_structured_output_when_capabilities_provided(self):
        caps = [
            Capability(
                name="test-cmd",
                capability_type="command",
                source="plugin:test",
                source_path="/path/to/test-cmd.md",
                invocation="/test-cmd",
                description="A test command",
                permissions=("Read", "Bash"),
            ),
            Capability(
                name="user-skill",
                capability_type="skill",
                source="user",
                source_path="/path/to/SKILL.md",
                invocation="Auto-triggered by model",
                description="A user skill",
            ),
        ]
        output = format_inventory(caps)
        self.assertIn("=== CAPABILITY INVENTORY ===", output)
        self.assertIn("Total capabilities found: 2", output)
        self.assertIn("[plugin:test] test-cmd (command)", output)
        self.assertIn("[user] user-skill (skill)", output)
        self.assertIn("=== END INVENTORY ===", output)

    def should_group_by_source_when_mixed_sources(self):
        caps = [
            Capability(
                name="plug-cmd", capability_type="command",
                source="plugin:p1", source_path="/a", invocation="/plug-cmd",
                description="Plugin cmd",
            ),
            Capability(
                name="usr-cmd", capability_type="command",
                source="user", source_path="/b", invocation="/usr-cmd",
                description="User cmd",
            ),
            Capability(
                name="proj-cmd", capability_type="command",
                source="project", source_path="/c", invocation="/proj-cmd",
                description="Project cmd",
            ),
        ]
        output = format_inventory(caps)
        self.assertIn("--- PLUGINS (1) ---", output)
        self.assertIn("--- USER-LEVEL (1) ---", output)
        self.assertIn("--- PROJECT-LEVEL (1) ---", output)

    def should_show_none_found_when_empty_section(self):
        output = format_inventory([])
        self.assertIn("Total capabilities found: 0", output)
        self.assertIn("(none found)", output)


class TestFormatDetail(unittest.TestCase):
    """Tests for detail text formatting."""

    def should_include_all_fields_when_capability_found(self):
        caps = [
            Capability(
                name="test-cmd",
                capability_type="command",
                source="plugin:test",
                source_path="/path/to/test-cmd.md",
                invocation="/test-cmd",
                description="A test command",
                permissions=("Read", "Bash"),
                metadata={"model": "sonnet"},
            ),
        ]
        output = format_detail(caps, "test-cmd")
        self.assertIn("=== CAPABILITY DETAIL: test-cmd ===", output)
        self.assertIn("Name: test-cmd", output)
        self.assertIn("Type: command", output)
        self.assertIn("Source: plugin:test", output)
        self.assertIn("- Read", output)
        self.assertIn("- Bash", output)
        self.assertIn("model: sonnet", output)

    def should_show_not_found_when_name_missing(self):
        caps = [
            Capability(
                name="other", capability_type="command",
                source="user", source_path="/a", invocation="/other",
                description="Other",
            ),
        ]
        output = format_detail(caps, "nonexistent")
        self.assertIn("CAPABILITY NOT FOUND", output)
        self.assertIn("other", output)  # Shows available suggestions

    def should_match_case_insensitive_when_different_case(self):
        caps = [
            Capability(
                name="Code-Review", capability_type="command",
                source="plugin:cr", source_path="/a", invocation="/Code-Review",
                description="Reviews code",
            ),
        ]
        output = format_detail(caps, "code-review")
        self.assertIn("CAPABILITY DETAIL: Code-Review", output)

    def should_match_substring_when_partial_name(self):
        caps = [
            Capability(
                name="claude-md-improver", capability_type="skill",
                source="plugin:cm", source_path="/a",
                invocation="Auto-triggered by model",
                description="Improves CLAUDE.md",
            ),
        ]
        output = format_detail(caps, "improver")
        self.assertIn("CAPABILITY DETAIL: claude-md-improver", output)


class TestFormatJson(unittest.TestCase):
    """Tests for JSON output."""

    def should_produce_valid_json_when_capabilities_provided(self):
        caps = [
            Capability(
                name="test", capability_type="command",
                source="user", source_path="/a", invocation="/test",
                description="Test", permissions=("Read",),
            ),
        ]
        output = format_json(caps)
        data = json.loads(output)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "test")
        self.assertEqual(data[0]["permissions"], ["Read"])


class TestScanCacheHealth(unittest.TestCase):
    """Tests for cache health scanning."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _setup_cache(self):
        """Create a mock cache structure with active and orphaned versions."""
        plugins_dir = self.tmpdir / ".claude" / "plugins"
        plugins_dir.mkdir(parents=True)
        cache_dir = plugins_dir / "cache" / "test-marketplace"
        cache_dir.mkdir(parents=True)

        # Active plugin version
        active_dir = cache_dir / "my-plugin" / "v1.0.0"
        active_meta = active_dir / ".claude-plugin"
        active_meta.mkdir(parents=True)
        (active_meta / "plugin.json").write_text(
            json.dumps({"name": "my-plugin"})
        )
        # Add a file so size > 0
        (active_dir / "README.md").write_text("Active version")

        # Orphaned plugin version
        orphan_dir = cache_dir / "my-plugin" / "v0.9.0"
        orphan_dir.mkdir(parents=True)
        (orphan_dir / "README.md").write_text("Orphaned version")
        (orphan_dir / ".orphaned_at").write_text("1771934506335")

        # installed_plugins.json referencing only active version
        (plugins_dir / "installed_plugins.json").write_text(json.dumps({
            "version": 2,
            "plugins": {
                "my-plugin@test-marketplace": [
                    {
                        "scope": "user",
                        "installPath": str(active_dir),
                        "version": "v1.0.0",
                    }
                ]
            },
        }))

        return plugins_dir, active_dir, orphan_dir

    def should_detect_orphaned_versions_when_not_in_manifest(self):
        _plugins_dir, _active_dir, orphan_dir = self._setup_cache()
        health = scan_cache_health(home_dir=self.tmpdir)
        self.assertEqual(len(health.orphaned_versions), 1)
        self.assertEqual(health.orphaned_versions[0].version, "v0.9.0")
        self.assertEqual(health.orphaned_versions[0].path, str(orphan_dir))
        self.assertIn("2026-02-24", health.orphaned_versions[0].orphaned_at)

    def should_report_zero_orphans_when_all_active(self):
        plugins_dir = self.tmpdir / ".claude" / "plugins"
        plugins_dir.mkdir(parents=True)
        cache_dir = plugins_dir / "cache" / "mp" / "plug" / "v1"
        cache_dir.mkdir(parents=True)
        (cache_dir / "file.txt").write_text("content")

        (plugins_dir / "installed_plugins.json").write_text(json.dumps({
            "version": 2,
            "plugins": {
                "plug@mp": [
                    {"scope": "user", "installPath": str(cache_dir), "version": "v1"}
                ]
            },
        }))

        health = scan_cache_health(home_dir=self.tmpdir)
        self.assertEqual(len(health.orphaned_versions), 0)
        self.assertEqual(health.orphaned_size_bytes, 0)

    def should_detect_version_conflicts_when_different_versions(self):
        plugins_dir = self.tmpdir / ".claude" / "plugins"
        plugins_dir.mkdir(parents=True)
        cache_dir = plugins_dir / "cache" / "mp"
        v1_dir = cache_dir / "plug" / "v1"
        v2_dir = cache_dir / "plug" / "v2"
        v1_dir.mkdir(parents=True)
        v2_dir.mkdir(parents=True)

        (plugins_dir / "installed_plugins.json").write_text(json.dumps({
            "version": 2,
            "plugins": {
                "plug@mp": [
                    {"scope": "user", "installPath": str(v1_dir), "version": "v1"},
                    {"scope": "project", "installPath": str(v2_dir), "version": "v2"},
                ]
            },
        }))

        health = scan_cache_health(home_dir=self.tmpdir)
        self.assertEqual(len(health.version_conflicts), 1)
        self.assertEqual(health.version_conflicts[0].plugin_key, "plug@mp")

    def should_detect_no_conflicts_when_same_version(self):
        plugins_dir = self.tmpdir / ".claude" / "plugins"
        plugins_dir.mkdir(parents=True)
        v1_dir = plugins_dir / "cache" / "mp" / "plug" / "v1"
        v1_dir.mkdir(parents=True)

        (plugins_dir / "installed_plugins.json").write_text(json.dumps({
            "version": 2,
            "plugins": {
                "plug@mp": [
                    {"scope": "user", "installPath": str(v1_dir), "version": "v1"},
                    {"scope": "project", "installPath": str(v1_dir), "version": "v1"},
                ]
            },
        }))

        health = scan_cache_health(home_dir=self.tmpdir)
        self.assertEqual(len(health.version_conflicts), 0)

    def should_read_blocklist_when_present(self):
        plugins_dir = self.tmpdir / ".claude" / "plugins"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "installed_plugins.json").write_text(
            json.dumps({"version": 2, "plugins": {}})
        )
        (plugins_dir / "blocklist.json").write_text(
            json.dumps(["bad-plugin@marketplace", "another@mp"])
        )

        health = scan_cache_health(home_dir=self.tmpdir)
        self.assertEqual(len(health.blocked_plugins), 2)
        keys = {bp.key for bp in health.blocked_plugins}
        self.assertIn("bad-plugin@marketplace", keys)

    def should_handle_missing_cache_dir_gracefully(self):
        empty_home = self.tmpdir / "empty"
        empty_home.mkdir()
        health = scan_cache_health(home_dir=empty_home)
        self.assertEqual(len(health.orphaned_versions), 0)
        self.assertEqual(len(health.version_conflicts), 0)
        self.assertEqual(len(health.blocked_plugins), 0)
        self.assertEqual(health.total_cache_size_bytes, 0)

    def should_skip_temp_git_dirs_when_scanning(self):
        plugins_dir = self.tmpdir / ".claude" / "plugins"
        plugins_dir.mkdir(parents=True)
        cache_dir = plugins_dir / "cache"

        # Create a temp_git_ directory (should be skipped)
        temp_dir = cache_dir / "temp_git_12345_abc"
        temp_sub = temp_dir / ".git" / "objects"
        temp_sub.mkdir(parents=True)
        (temp_sub / "pack").write_text("data")

        (plugins_dir / "installed_plugins.json").write_text(
            json.dumps({"version": 2, "plugins": {}})
        )

        health = scan_cache_health(home_dir=self.tmpdir)
        # temp_git_ should not appear as orphaned versions
        self.assertEqual(len(health.orphaned_versions), 0)
        # temp_git_ should not count toward cache size
        self.assertEqual(health.total_cache_size_bytes, 0)


class TestFormatCacheHealth(unittest.TestCase):
    """Tests for cache health text formatting."""

    def should_show_clean_cache_when_no_issues(self):
        health = CacheHealth(
            orphaned_versions=(),
            version_conflicts=(),
            blocked_plugins=(),
            total_cache_size_bytes=1024 * 500,
            orphaned_size_bytes=0,
        )
        output = format_cache_health(health)
        self.assertIn("=== CACHE HEALTH REPORT ===", output)
        self.assertIn("(none — cache is clean)", output)
        self.assertIn("(none — all plugins use consistent versions)", output)

    def should_show_orphan_details_when_present(self):
        from scan import OrphanedVersion
        health = CacheHealth(
            orphaned_versions=(
                OrphanedVersion(
                    plugin_name="old-plugin",
                    marketplace="mp",
                    version="v0.1",
                    path="/cache/mp/old-plugin/v0.1",
                    orphaned_at="2026-02-20T10:00:00Z",
                    size_bytes=50000,
                ),
            ),
            version_conflicts=(),
            blocked_plugins=(),
            total_cache_size_bytes=200000,
            orphaned_size_bytes=50000,
        )
        output = format_cache_health(health)
        self.assertIn("ORPHANED VERSIONS (1)", output)
        self.assertIn("[mp/old-plugin] vv0.1", output)
        self.assertIn("48.8 KB", output)
        self.assertIn("2026-02-20", output)


class TestScoreCapability(unittest.TestCase):
    """Tests for risk scoring of individual capabilities."""

    def should_score_low_when_no_permissions(self):
        cap = Capability(
            name="safe-cmd", capability_type="command",
            source="user", source_path="/a", invocation="/safe-cmd",
            description="No tools", permissions=(),
        )
        entry = score_capability(cap)
        self.assertEqual(entry.score, 0)
        self.assertEqual(entry.level, "low")

    def should_score_critical_when_unrestricted_bash(self):
        cap = Capability(
            name="danger", capability_type="command",
            source="plugin:x", source_path="/a", invocation="/danger",
            description="Dangerous", permissions=("Bash",),
        )
        entry = score_capability(cap)
        self.assertGreaterEqual(entry.score, 15)
        self.assertEqual(entry.level, "critical")
        self.assertTrue(any("Unrestricted Bash" in f for f in entry.factors))

    def should_score_medium_when_read_only(self):
        cap = Capability(
            name="reader", capability_type="command",
            source="user", source_path="/a", invocation="/reader",
            description="Reads files", permissions=("Read", "Glob", "Grep"),
        )
        entry = score_capability(cap)
        self.assertEqual(entry.score, 4)  # 2 + 1 + 1
        self.assertEqual(entry.level, "low")

    def should_add_hook_bonus_when_hook_type(self):
        cap = Capability(
            name="PostToolUse:Edit", capability_type="hook",
            source="plugin:test", source_path="/a",
            invocation="Auto-trigger on PostToolUse matching Edit",
            description="lint.sh", permissions=(),
        )
        entry = score_capability(cap)
        self.assertGreaterEqual(entry.score, 3)  # hook bonus
        self.assertTrue(any("Auto-triggered" in f for f in entry.factors))

    def should_add_wildcard_bonus_when_broad_matcher(self):
        cap = Capability(
            name="UserPromptSubmit: ", capability_type="hook",
            source="plugin:test", source_path="/a",
            invocation="Auto-trigger on UserPromptSubmit matching ",
            description="inject.sh", permissions=(),
        )
        entry = score_capability(cap)
        self.assertGreaterEqual(entry.score, 5)  # hook(3) + wildcard(2)

    def should_score_high_when_bash_pattern_plus_write(self):
        cap = Capability(
            name="builder", capability_type="command",
            source="plugin:x", source_path="/a", invocation="/builder",
            description="Builds", permissions=("Bash(npm:*)", "Write"),
        )
        entry = score_capability(cap)
        self.assertEqual(entry.score, 14)  # Bash pattern(8) + Write(6)
        self.assertEqual(entry.level, "high")


class TestScoreAll(unittest.TestCase):
    """Tests for scoring and sorting all capabilities."""

    def should_sort_by_score_descending(self):
        caps = [
            Capability(
                name="safe", capability_type="command",
                source="user", source_path="/a", invocation="/safe",
                description="Safe", permissions=(),
            ),
            Capability(
                name="risky", capability_type="command",
                source="plugin:x", source_path="/a", invocation="/risky",
                description="Risky", permissions=("Bash",),
            ),
        ]
        entries = score_all(caps)
        self.assertEqual(entries[0].capability.name, "risky")
        self.assertEqual(entries[1].capability.name, "safe")


class TestFormatRiskReport(unittest.TestCase):
    """Tests for risk report formatting."""

    def should_include_summary_counts(self):
        entries = [
            RiskEntry(
                capability=Capability(
                    name="cmd", capability_type="command",
                    source="user", source_path="/a", invocation="/cmd",
                    description="Test",
                ),
                score=0, level="low", factors=(),
            ),
        ]
        output = format_risk_report(entries)
        self.assertIn("=== RISK REPORT ===", output)
        self.assertIn("LOW: 1", output)
        self.assertIn("CRITICAL: 0", output)

    def should_show_critical_entries_when_present(self):
        entries = [
            RiskEntry(
                capability=Capability(
                    name="danger", capability_type="command",
                    source="plugin:x", source_path="/a", invocation="/danger",
                    description="Dangerous", permissions=("Bash",),
                ),
                score=15, level="critical",
                factors=("+15 Unrestricted Bash access",),
            ),
        ]
        output = format_risk_report(entries)
        self.assertIn("CRITICAL RISK (1)", output)
        self.assertIn("Unrestricted Bash access", output)

    def should_produce_valid_json_when_json_format(self):
        entries = [
            RiskEntry(
                capability=Capability(
                    name="cmd", capability_type="command",
                    source="user", source_path="/a", invocation="/cmd",
                    description="Test",
                ),
                score=0, level="low", factors=(),
            ),
        ]
        output = format_risk_json(entries)
        data = json.loads(output)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["level"], "low")


class TestDiffSnapshots(unittest.TestCase):
    """Tests for capability diff comparison."""

    def _make_cap(self, name, source="user", desc="Test", perms=()):
        return Capability(
            name=name, capability_type="command",
            source=source, source_path="/a", invocation=f"/{name}",
            description=desc, permissions=perms,
        )

    def should_detect_added_capabilities(self):
        old = [self._make_cap("cmd-a")]
        new = [self._make_cap("cmd-a"), self._make_cap("cmd-b")]
        result = diff_snapshots(old, new)
        self.assertEqual(len(result.added), 1)
        self.assertEqual(result.added[0].name, "cmd-b")
        self.assertEqual(len(result.removed), 0)

    def should_detect_removed_capabilities(self):
        old = [self._make_cap("cmd-a"), self._make_cap("cmd-b")]
        new = [self._make_cap("cmd-a")]
        result = diff_snapshots(old, new)
        self.assertEqual(len(result.removed), 1)
        self.assertEqual(result.removed[0].name, "cmd-b")

    def should_detect_changed_capabilities(self):
        old = [self._make_cap("cmd-a", desc="Old desc")]
        new = [self._make_cap("cmd-a", desc="New desc")]
        result = diff_snapshots(old, new)
        self.assertEqual(len(result.changed), 1)
        self.assertEqual(result.changed[0][0].description, "Old desc")
        self.assertEqual(result.changed[0][1].description, "New desc")

    def should_detect_permission_changes(self):
        old = [self._make_cap("cmd-a", perms=("Read",))]
        new = [self._make_cap("cmd-a", perms=("Read", "Bash"))]
        result = diff_snapshots(old, new)
        self.assertEqual(len(result.changed), 1)

    def should_report_no_changes_when_identical(self):
        caps = [self._make_cap("cmd-a")]
        result = diff_snapshots(caps, caps)
        self.assertEqual(len(result.added), 0)
        self.assertEqual(len(result.removed), 0)
        self.assertEqual(len(result.changed), 0)


class TestSaveLoadSnapshot(unittest.TestCase):
    """Tests for snapshot save/load round-trip."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def should_round_trip_capabilities_when_saved_and_loaded(self):
        caps = [
            Capability(
                name="test-cmd", capability_type="command",
                source="plugin:test", source_path="/path/to/test.md",
                invocation="/test-cmd", description="A test command",
                permissions=("Read", "Bash"), provider="my-marketplace",
                metadata={"model": "sonnet"},
            ),
        ]
        snapshot_path = self.tmpdir / "snapshot.json"
        save_snapshot(caps, snapshot_path)
        loaded = load_snapshot(snapshot_path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].name, "test-cmd")
        self.assertEqual(loaded[0].permissions, ("Read", "Bash"))
        self.assertEqual(loaded[0].provider, "my-marketplace")
        self.assertEqual(loaded[0].metadata["model"], "sonnet")


class TestFormatDiff(unittest.TestCase):
    """Tests for diff report formatting."""

    def should_show_no_changes_when_empty_diff(self):
        result = DiffResult(added=(), removed=(), changed=())
        output = format_diff(result)
        self.assertIn("No changes detected", output)
        self.assertIn("Total changes: 0", output)

    def should_show_added_removed_changed_when_present(self):
        added_cap = Capability(
            name="new-cmd", capability_type="command",
            source="user", source_path="/a", invocation="/new-cmd",
            description="New command",
        )
        removed_cap = Capability(
            name="old-cmd", capability_type="command",
            source="user", source_path="/a", invocation="/old-cmd",
            description="Old command",
        )
        old_cap = Capability(
            name="mod-cmd", capability_type="command",
            source="user", source_path="/a", invocation="/mod-cmd",
            description="Old desc",
        )
        new_cap = Capability(
            name="mod-cmd", capability_type="command",
            source="user", source_path="/a", invocation="/mod-cmd",
            description="New desc",
        )
        result = DiffResult(
            added=(added_cap,),
            removed=(removed_cap,),
            changed=((old_cap, new_cap),),
        )
        output = format_diff(result)
        self.assertIn("ADDED (1)", output)
        self.assertIn("+ [user] new-cmd", output)
        self.assertIn("REMOVED (1)", output)
        self.assertIn("- [user] old-cmd", output)
        self.assertIn("CHANGED (1)", output)
        self.assertIn("Old desc", output)
        self.assertIn("New desc", output)

    def should_produce_valid_json_when_json_format(self):
        result = DiffResult(added=(), removed=(), changed=())
        output = format_diff_json(result)
        data = json.loads(output)
        self.assertEqual(data["added"], [])
        self.assertEqual(data["removed"], [])
        self.assertEqual(data["changed"], [])


# Remap test methods to standard unittest discovery (test_ prefix)
# while keeping descriptive should_ names for readability.
def _remap_test_methods():
    """Auto-alias should_* methods to test_* for unittest discovery."""
    for cls_name, cls in list(globals().items()):
        if isinstance(cls, type) and issubclass(cls, unittest.TestCase):
            for attr_name in list(dir(cls)):
                if attr_name.startswith("should_"):
                    method = getattr(cls, attr_name)
                    setattr(cls, f"test_{attr_name}", method)


_remap_test_methods()


if __name__ == "__main__":
    unittest.main()
