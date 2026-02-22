"""Tests for src/prompts_service.py — system prompt content and user message builders."""

import src.prompts_service as prompts


class TestSystemPrompts:
    def test_summarize_system_has_three_required_keys(self):
        for key in ("summary", "technologies", "structure"):
            assert f'"{key}"' in prompts.SUMMARIZE_SYSTEM

    def test_summarize_system_requires_json_output(self):
        assert "JSON" in prompts.SUMMARIZE_SYSTEM or "json" in prompts.SUMMARIZE_SYSTEM

    def test_summarize_system_prohibits_markdown_fences(self):
        assert "markdown" in prompts.SUMMARIZE_SYSTEM.lower()

    def test_map_system_has_purpose_key(self):
        assert '"purpose"' in prompts.MAP_SYSTEM

    def test_map_system_has_technologies_key(self):
        assert '"technologies"' in prompts.MAP_SYSTEM

    def test_map_system_has_structure_key(self):
        assert '"structure"' in prompts.MAP_SYSTEM

    def test_reduce_system_has_three_required_keys(self):
        for key in ("summary", "technologies", "structure"):
            assert f'"{key}"' in prompts.REDUCE_SYSTEM

    def test_reduce_system_mentions_deduplication(self):
        assert "dedup" in prompts.REDUCE_SYSTEM.lower()

    def test_json_repair_system_names_all_three_keys(self):
        for key in ("summary", "technologies", "structure"):
            assert f'"{key}"' in prompts.JSON_REPAIR_SYSTEM

    def test_json_repair_system_says_only_fix_syntax(self):
        text = prompts.JSON_REPAIR_SYSTEM.lower()
        assert "syntax" in text or "fix" in text


class TestUserMessageBuilders:
    def test_summarize_user_embeds_context(self):
        ctx = "<repository_context>hello</repository_context>"
        msg = prompts.summarize_user(ctx)
        assert ctx in msg

    def test_summarize_user_has_instruction(self):
        msg = prompts.summarize_user("ctx")
        assert "repository" in msg.lower()

    def test_map_user_embeds_chunk(self):
        chunk = "def foo(): pass"
        msg = prompts.map_user(chunk)
        assert chunk in msg

    def test_map_user_has_instruction(self):
        msg = prompts.map_user("chunk")
        assert "chunk" in msg.lower() or "repository" in msg.lower()

    def test_reduce_user_embeds_each_note(self):
        notes = ["note one", "note two", "note three"]
        msg = prompts.reduce_user(notes)
        for note in notes:
            assert note in msg

    def test_reduce_user_formats_as_bullet_list(self):
        msg = prompts.reduce_user(["a", "b"])
        assert "- a" in msg
        assert "- b" in msg

    def test_reduce_user_empty_notes(self):
        msg = prompts.reduce_user([])
        assert isinstance(msg, str)

    def test_json_repair_user_embeds_bad_json(self):
        bad = '{"summary": missing_quote}'
        msg = prompts.json_repair_user(bad, "JSONDecodeError")
        assert bad in msg

    def test_json_repair_user_embeds_error(self):
        msg = prompts.json_repair_user("{}", "JSONDecodeError at line 1")
        assert "JSONDecodeError at line 1" in msg
