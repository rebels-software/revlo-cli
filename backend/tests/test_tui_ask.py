"""Test suite for the TUI Ask mode (US-035).

Uses Textual's ``run_test`` / ``Pilot`` helper for headless async testing.
All Claude API calls are mocked.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from textual.widgets import Static

from revlo.parser.models import ParsedSchematic
from revlo.reviewer.models import (
    DatasheetEvidence,
    Finding,
    FindingCategory,
    FindingEvidence,
    FindingSourceType,
    ReviewReport,
    Severity,
)
from revlo.tui.app import (
    DetailPanel,
    FilterBar,
    FindingItem,
    FindingsSidebar,
    InvestigationTarget,
    RevloApp,
)
from revlo.tui.chat import (
    ChatMessage,
    ChatPanel,
    build_ask_system_prompt,
    markup_response,
)
from revlo.tui.tools import SCHEMATIC_TOOLS, execute_tool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_finding(
    severity: Severity = Severity.error,
    category: FindingCategory = FindingCategory.decoupling,
    ref: str = "U1",
    title: str = "Missing decoupling capacitor",
    description: str = "No decoupling capacitor found near U1.",
    recommendation: str = "Add a 100nF capacitor close to the power pins.",
    confidence: float = 0.95,
) -> Finding:
    return Finding(
        severity=severity,
        category=category,
        component_ref=ref,
        title=title,
        description=description,
        recommendation=recommendation,
        confidence=confidence,
    )


@pytest.fixture
def sample_report() -> ReviewReport:
    """Report with one finding per severity."""
    return ReviewReport(
        findings=[
            _make_finding(Severity.error, FindingCategory.decoupling, "U1", "Missing cap"),
            _make_finding(Severity.warning, FindingCategory.power, "R7", "High current path"),
            _make_finding(Severity.suggestion, FindingCategory.unused_pin, "U2", "Unused pin"),
        ],
        summary="3 findings",
        schematic_title="Test Schematic",
        review_date="2026-02-16",
    )


@pytest.fixture
def empty_report() -> ReviewReport:
    """Report with no findings."""
    return ReviewReport(
        findings=[],
        summary="No issues",
        schematic_title="Test Schematic",
        review_date="2026-02-16",
    )


@pytest.fixture
def schematic_path(tmp_path: Path) -> str:
    """Return a temporary path simulating a schematic file."""
    p = tmp_path / "test_board.kicad_sch"
    p.write_text("")
    return str(p)


# ---------------------------------------------------------------------------
# Unit tests -- markup_response
# ---------------------------------------------------------------------------

class TestMarkupResponse:
    def test_component_refs_highlighted(self):
        result = markup_response("Check U1 and R10 for issues")
        assert "#00D4AA" in result  # ELECTRIC_TEAL
        assert "U1" in result
        assert "R10" in result

    def test_page_citations_highlighted(self):
        result = markup_response("See datasheet p.42 for details")
        assert "#FFB347" in result  # WARM_AMBER
        assert "p.42" in result

    def test_page_word_citation(self):
        result = markup_response("Refer to page 15")
        assert "#FFB347" in result

    def test_plain_text_unchanged(self):
        result = markup_response("Hello world")
        assert "Hello" in result
        assert "world" in result

    def test_brackets_escaped(self):
        # Rich markup brackets should be escaped
        result = markup_response("array[0] = 5")
        assert "\\[" in result


# ---------------------------------------------------------------------------
# Unit tests -- ChatMessage
# ---------------------------------------------------------------------------

class TestChatMessage:
    def test_to_dict(self):
        msg = ChatMessage("user", "Hello", "2026-02-16T12:00:00Z")
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "Hello"
        assert d["timestamp"] == "2026-02-16T12:00:00Z"

    def test_to_api_dict(self):
        msg = ChatMessage("assistant", "Hi there")
        d = msg.to_api_dict()
        assert d == {"role": "assistant", "content": "Hi there"}


# ---------------------------------------------------------------------------
# Unit tests -- build_ask_system_prompt
# ---------------------------------------------------------------------------

class TestBuildAskSystemPrompt:
    def test_includes_base_ee_knowledge(self, sample_report):
        prompt = build_ask_system_prompt(sample_report)
        # Should include something from base_ee_knowledge.md
        assert "Ohm" in prompt or "Voltage" in prompt or "EE" in prompt

    def test_includes_role_instruction(self, sample_report):
        prompt = build_ask_system_prompt(sample_report)
        assert "Revlo" in prompt
        assert "expert" in prompt.lower() or "electronics" in prompt.lower()

    def test_includes_findings(self, sample_report):
        prompt = build_ask_system_prompt(sample_report)
        assert "U1" in prompt
        assert "Missing cap" in prompt

    def test_empty_report_no_findings_section(self, empty_report):
        prompt = build_ask_system_prompt(empty_report)
        assert "Current Review Findings" not in prompt

    def test_generic_prompt_omits_investigation_mode(self, sample_report):
        prompt = build_ask_system_prompt(sample_report)
        assert "## General Ask Mode" in prompt
        assert "## Investigation Mode" not in prompt

    def test_investigation_mode_prompt_requires_tool_backed_validation(self, sample_report):
        target = InvestigationTarget(
            severity="warning",
            title="Reset path issue",
            component_ref="U2",
            refs=["U2", "R5"],
            nets=["NRST"],
            recommendation="Add a pull-up.",
        )

        prompt = build_ask_system_prompt(
            sample_report,
            investigation_target=target.to_banner_text(),
        )

        assert "## Investigation Mode" in prompt
        assert "Active investigation target" in prompt
        assert target.to_banner_text() in prompt
        assert "call at least one relevant tool" in prompt
        assert "distinguish observed connectivity from inference" in prompt


def test_new_investigation_tools_are_registered():
    names = {tool["name"] for tool in SCHEMATIC_TOOLS}
    assert {
        "find_decoupling_caps",
        "trace_power_tree",
        "find_reset_chain",
        "find_boot_straps",
        "find_interface_bundle",
        "compare_two_refs",
        "explain_finding_evidence",
        "show_constraint_violations",
    }.issubset(names)


def test_registered_investigation_tool_executes_safely_with_missing_net():
    result = execute_tool("trace_power_tree", {"net_name": "3V3"}, ParsedSchematic())
    assert "Power net '3V3' not found." in result


def test_build_investigation_target_uses_finding_evidence(sample_report: ReviewReport):
    finding = sample_report.findings[0]
    finding.evidence.refs = ["C1"]
    finding.evidence.nets = ["3V3"]
    app = RevloApp(sample_report, "/tmp/test.kicad_sch")

    target = app._build_investigation_target(finding)

    assert target == InvestigationTarget(
        severity="error",
        title="Missing cap",
        component_ref="U1",
        refs=["U1", "C1"],
        nets=["3V3"],
        recommendation="Add a 100nF capacitor close to the power pins.",
    )


def test_investigation_target_banner_text():
    target = InvestigationTarget(
        severity="warning",
        title="Reset path issue",
        component_ref="U2",
        refs=["U2", "R5"],
        nets=["NRST"],
        recommendation="Add a pull-up.",
    )

    banner = target.to_banner_text()

    assert "[WARNING] U2: Reset path issue" in banner
    assert "refs=U2, R5" in banner
    assert "nets=NRST" in banner
    assert "recommendation=Add a pull-up." in banner


class TestDetailPanelEvidence:
    @pytest.mark.asyncio
    async def test_detail_panel_renders_structured_evidence(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        finding = sample_report.findings[0]
        finding.source_type = FindingSourceType.deterministic
        finding.evidence = FindingEvidence(
            refs=["U1", "C5"],
            nets=["+3V3", "GND"],
            sheet_paths=["/Power", "/MCU"],
            datasheets=[
                DatasheetEvidence(
                    mpn="STM32F103C8T6",
                    manufacturer="ST",
                    relevant_pages=[47, 48],
                )
            ],
            notes=["Observed VDD pin without nearby 100nF capacitor."],
        )
        app = RevloApp(sample_report, schematic_path)

        async with app.run_test():
            detail = app.query_one("#detail-panel", DetailPanel)
            detail.show_finding(finding)

            evidence = detail.query_one("#detail-evidence", Static)
            text = evidence.render().plain
            assert "Source: deterministic" in text
            assert "Refs: U1, C5" in text
            assert "Nets: +3V3, GND" in text
            assert "Sheets: /Power, /MCU" in text
            assert "STM32F103C8T6 | ST | p.47-48" in text
            assert "Observed VDD pin without nearby 100nF capacitor." in text

    @pytest.mark.asyncio
    async def test_detail_panel_labels_missing_evidence_clearly(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)

        async with app.run_test():
            detail = app.query_one("#detail-panel", DetailPanel)
            detail.show_finding(sample_report.findings[0])

            evidence = detail.query_one("#detail-evidence", Static)
            text = evidence.render().plain
            assert "Source: llm" in text
            assert "No structured evidence attached to this finding yet." in text


# ---------------------------------------------------------------------------
# Unit tests -- save_chat
# ---------------------------------------------------------------------------

class TestSaveChat:
    def test_saves_json_file(self, tmp_path):
        from revlo.storage import save_chat

        sch_path = str(tmp_path / "board.kicad_sch")
        Path(sch_path).write_text("")

        messages = [
            {"role": "user", "content": "What about U1?", "timestamp": "2026-02-16T12:00:00Z"},
            {"role": "assistant", "content": "U1 needs a cap.", "timestamp": "2026-02-16T12:00:05Z"},
        ]

        result = save_chat(messages, sch_path)
        assert result.exists()
        assert "-chat-" in result.name
        assert result.suffix == ".json"

        data = json.loads(result.read_text())
        assert data["messages"] == messages
        assert data["_meta"]["type"] == "chat"
        assert data["_meta"]["schematic"] == "board.kicad_sch"

    def test_creates_revlo_dir(self, tmp_path):
        from revlo.storage import save_chat

        sch_path = str(tmp_path / "board.kicad_sch")
        Path(sch_path).write_text("")

        save_chat([], sch_path)
        assert (tmp_path / ".revlo").is_dir()


# ---------------------------------------------------------------------------
# Async TUI tests -- keybinding remap
# ---------------------------------------------------------------------------

class TestKeybindingRemap:
    """Verify 'a' opens ask mode and 'f' filters all."""

    @pytest.mark.asyncio
    async def test_f_filters_all(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            # Filter to errors first
            await pilot.press("e")
            await pilot.pause()
            sidebar = app.query_one("#sidebar", FindingsSidebar)
            items = sidebar.query(FindingItem)
            assert len(items) == 1

            # Press 'f' to show all
            await pilot.press("f")
            await pilot.pause()
            items = sidebar.query(FindingItem)
            assert len(items) == 3

    @pytest.mark.asyncio
    async def test_a_enters_chat_mode(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            assert app._chat_mode is False
            await pilot.press("a")
            await pilot.pause()
            assert app._chat_mode is True

            # Chat panel should be mounted
            chat = app.query_one("#chat-panel", ChatPanel)
            assert chat is not None

    @pytest.mark.asyncio
    async def test_escape_exits_chat_mode(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.pause()
            assert app._chat_mode is True

            await pilot.press("escape")
            await pilot.pause()
            assert app._chat_mode is False

    @pytest.mark.asyncio
    async def test_detail_panel_hidden_in_chat_mode(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.pause()

            detail = app.query_one("#detail-panel", DetailPanel)
            assert str(detail.styles.display) == "none"

    @pytest.mark.asyncio
    async def test_detail_panel_restored_after_escape(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

            detail = app.query_one("#detail-panel", DetailPanel)
            assert str(detail.styles.display) != "none"


# ---------------------------------------------------------------------------
# Async TUI tests -- chat panel behaviour
# ---------------------------------------------------------------------------

class TestChatPanel:
    """Test the ChatPanel widget in isolation within the app."""

    @pytest.mark.asyncio
    async def test_chat_panel_has_input(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.pause()

            from textual.widgets import Input
            inp = app.query_one("#chat-input", Input)
            assert inp is not None

    @pytest.mark.asyncio
    async def test_chat_panel_has_scroll_area(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.pause()

            from textual.containers import VerticalScroll
            scroll = app.query_one("#chat-scroll", VerticalScroll)
            assert scroll is not None

    @pytest.mark.asyncio
    async def test_sidebar_stays_visible_in_chat_mode(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.pause()

            sidebar = app.query_one("#sidebar", FindingsSidebar)
            assert str(sidebar.styles.display) != "none"

    @pytest.mark.asyncio
    async def test_filter_keys_ignored_in_chat_mode(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.pause()

            # Filter key should be ignored
            old_filter = app.active_filter
            await pilot.press("e")
            await pilot.pause()
            assert app.active_filter == old_filter


# ---------------------------------------------------------------------------
# Async TUI tests -- context from highlighted finding
# ---------------------------------------------------------------------------

class TestFindingContext:
    """Test that highlighted finding is included as context."""

    @pytest.mark.asyncio
    async def test_highlighted_finding_provides_context(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            # Navigate to first finding item
            await pilot.pause()

            # Enter chat mode - should include highlighted finding as context
            await pilot.press("a")
            await pilot.pause()

            # Check that context banner was added (scroll area should have children)
            from textual.containers import VerticalScroll
            scroll = app.query_one("#chat-scroll", VerticalScroll)
            children = list(scroll.children)
            # There should be at least the context banner
            assert len(children) >= 1


# ---------------------------------------------------------------------------
# Async TUI tests -- streaming (mocked)
# ---------------------------------------------------------------------------

class TestChatStreaming:
    """Test the chat message sending with mocked Claude API."""

    @pytest.mark.asyncio
    async def test_send_message_adds_to_conversation(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        """Verify that sending a message updates the conversation history."""
        app = RevloApp(sample_report, schematic_path)

        # Mock the streaming worker so it doesn't actually call Claude
        async def mock_stream():
            if app._chat_panel is not None:
                app._chat_panel.finish_assistant_message("Mocked response")
                app._chat_panel.set_input_enabled(True)
            app._conversation.append({"role": "assistant", "content": "Mocked response"})

        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.pause()

            # Patch _do_stream to avoid real API calls
            with patch.object(app, "_do_stream", side_effect=mock_stream):
                app._send_chat_message("What about U1?")
                await pilot.pause()

            # User message should be in conversation
            assert any(m["role"] == "user" and "U1" in m["content"]
                      for m in app._conversation)


class TestParsedSchematicReuse:
    def test_uses_injected_parsed_schematic_without_reparse(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        parsed = object()
        app = RevloApp(sample_report, schematic_path, parsed_schematic=parsed)

        with patch("revlo.parser.parse_schematic") as mock_parse:
            assert app._get_parsed_schematic() is parsed
            assert app._get_parsed_schematic() is parsed

        mock_parse.assert_not_called()

    def test_failed_parse_is_cached(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)

        with patch(
            "revlo.parser.parse_schematic",
            side_effect=RuntimeError("parse failed"),
        ) as mock_parse:
            assert app._get_parsed_schematic() is None
            assert app._get_parsed_schematic() is None

        mock_parse.assert_called_once_with(schematic_path)

    @pytest.mark.asyncio
    async def test_reentering_chat_mode_reuses_cached_parse(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        parsed = object()

        with patch("revlo.parser.parse_schematic", return_value=parsed) as mock_parse:
            async with app.run_test() as pilot:
                await pilot.press("a")
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                await pilot.press("a")
                await pilot.pause()

        mock_parse.assert_called_once_with(schematic_path)


# ---------------------------------------------------------------------------
# Async TUI tests -- conversation save on exit
# ---------------------------------------------------------------------------

class TestConversationSave:
    """Test that conversation is saved when exiting chat mode."""

    @pytest.mark.asyncio
    async def test_exit_chat_saves_conversation(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.pause()

            # Manually add messages to the chat panel
            chat = app.query_one("#chat-panel", ChatPanel)
            chat.add_user_message("Test question")
            chat.messages.append(
                ChatMessage("assistant", "Test answer", "2026-02-16T12:00:00Z")
            )

            with patch("revlo.storage.save_chat") as mock_save:
                mock_save.return_value = Path("/tmp/fake-chat.json")
                await pilot.press("escape")
                await pilot.pause()

                mock_save.assert_called_once()
                saved_messages = mock_save.call_args[0][0]
                assert len(saved_messages) == 2
                assert saved_messages[0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_exit_chat_no_save_if_empty(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.pause()

            with patch("revlo.storage.save_chat") as mock_save:
                await pilot.press("escape")
                await pilot.pause()

                mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# FilterBar updated keybinding display
# ---------------------------------------------------------------------------

class TestFilterBarDisplay:
    """Verify the filter bar shows updated keybinding hints."""

    @pytest.mark.asyncio
    async def test_filter_bar_shows_ask_key(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test():
            fbar = app.query_one("#filter-bar", FilterBar)
            right_label = fbar.query_one("#filter-right")
            text = right_label.render().plain
            assert "ask" in text.lower() or "a" in text

    @pytest.mark.asyncio
    async def test_filter_bar_shows_filter_all_as_f(
        self, sample_report: ReviewReport, schematic_path: str
    ):
        app = RevloApp(sample_report, schematic_path)
        async with app.run_test():
            fbar = app.query_one("#filter-bar", FilterBar)
            center_label = fbar.query_one("#filter-center")
            text = center_label.render().plain
            assert "filter" in text.lower() or "f" in text
