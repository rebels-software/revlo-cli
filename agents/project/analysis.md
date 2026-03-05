# Overview

Revlo is a Python 3.11+ package published as `revlo-cli`, currently version `0.1.3`, and it is fundamentally a local CLI/TUI product rather than a web service or API backend.

The intended product is clear and coherent: parse KiCad schematics, enrich them with datasheet facts, run an LLM-based EE review, then present findings interactively.

Scope has grown beyond the original parser-only brief. The codebase now includes parsing, datasheet fetch and extraction, review generation, Markdown export, persistent history, a branded Rich CLI, a Textual TUI, and Ask Mode with tool use.

# Architecture

The main execution path is `revlo review <file>`. It validates the file and `ANTHROPIC_API_KEY`, optionally exports a KiCad netlist for more accurate connectivity, parses the schematic, optionally enriches it with datasheets, runs the review, auto-saves the result, then either prints JSON, Markdown, finding cards, or launches the TUI.

The parser is the strongest technical part of the project. It handles unsupported legacy formats cleanly, recursively loads hierarchical sheets, resolves instance-specific references, and includes custom workarounds for `kicad-sch-api` and KiCad 9 pin metadata. It can also prefer `kicad-cli` netlists as ground-truth connectivity.

Review input is simplified into two chunk types: per-IC context and per-power-rail context. That keeps the review pipeline understandable, but it also means review quality depends heavily on how much relevant context fits into those chunk shapes.

The live review engine is not the multi-agent Agent SDK design from the planning docs. The current code sends all chunks in one direct Anthropic call, then falls back to per-chunk prompts if needed. The older agent-definition layer remains only as prompt assets and backward-compatibility helpers.

Datasheet enrichment is a substantial subsystem. It normalizes candidate MPNs, skips obvious generic parts, resolves URLs from component properties or distributor APIs, downloads PDFs, extracts targeted text pages, uses Claude Haiku to structure specs, and caches results locally.

The UX layer is polished for a terminal app. Findings are grouped and filtered in the Textual app, datasheet pages can be opened from findings, and Ask Mode runs a tool-use loop over the parsed schematic. Reviews and chats are stored beside the source schematic in `.revlo/`.
