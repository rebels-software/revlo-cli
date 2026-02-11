"""Extract structured DatasheetSpec from PDF text using Claude Haiku."""

from __future__ import annotations

import logging
from typing import Any

import anthropic

from revlo.datasheet.models import DatasheetSpec

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 4096
_PDF_TEXT_LIMIT = 100_000

# ---------------------------------------------------------------------------
# Tool-use schema for structured output
# ---------------------------------------------------------------------------
_SPEC_TOOL: dict[str, Any] = {
    "name": "record_datasheet_spec",
    "description": "Record the structured specifications extracted from the datasheet.",
    "input_schema": DatasheetSpec.model_json_schema(),
}

_TOOL_CHOICE: dict[str, str] = {"type": "tool", "name": "record_datasheet_spec"}

# ---------------------------------------------------------------------------
# System / user prompt
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """\
You are an expert electronics engineer. Your task is to extract structured \
specifications from a component datasheet. Be thorough and accurate. Extract \
all information that is explicitly stated in the text; do not guess or \
fabricate values."""

_USER_PROMPT_TEMPLATE = """\
Below is the text extracted from the PDF datasheet for part number: {mpn}

Extract the following information and record it using the provided tool:
- Manufacturer name
- Brief component description (one sentence)
- Supply voltage range (min and max, in volts)
- Maximum current rating (in amps)
- Pin functions: for each pin, extract the pin number, name, function \
description, and electrical type (e.g. power, input, output, bidirectional, \
passive, no-connect)
- Absolute maximum ratings (as key-value pairs, e.g. "VCC" -> "7V")
- Recommended operating conditions (as key-value pairs, e.g. \
"Supply voltage" -> "3.0V to 3.6V")
- Important notes: crystal requirements, boot pin configuration, \
decoupling recommendations, or any other critical application notes

If a value is not found in the text, omit it or leave it as the default.

--- DATASHEET TEXT ---
{pdf_text}
--- END DATASHEET TEXT ---"""


async def extract_spec(pdf_text: str, mpn: str) -> DatasheetSpec | None:
    """Extract a structured :class:`DatasheetSpec` from raw PDF text.

    Uses Claude Haiku with the tool-use structured-output pattern to
    guarantee a well-formed JSON response.

    Args:
        pdf_text: The raw text extracted from a PDF datasheet.
        mpn: The manufacturer part number for the component.

    Returns:
        A validated :class:`DatasheetSpec` on success, or *None* if
        extraction fails for any reason (API error, malformed response,
        validation failure, etc.).
    """
    truncated = pdf_text[:_PDF_TEXT_LIMIT]

    user_prompt = _USER_PROMPT_TEMPLATE.format(mpn=mpn, pdf_text=truncated)

    client = anthropic.AsyncAnthropic()

    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[_SPEC_TOOL],
            tool_choice=_TOOL_CHOICE,
        )
    except Exception:
        logger.warning("API call failed for MPN %r", mpn, exc_info=True)
        return None

    # Extract the tool_use block from the response.
    tool_input: dict[str, Any] | None = None
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            tool_input = block.input
            break

    if tool_input is None:
        logger.warning(
            "No tool_use block in response for MPN %r, skipping", mpn
        )
        return None

    try:
        return DatasheetSpec.model_validate(tool_input)
    except Exception:
        logger.warning(
            "Failed to validate DatasheetSpec for MPN %r", mpn, exc_info=True
        )
        return None
