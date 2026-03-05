"""Extract structured DatasheetSpec from PDF text via the configured LLM provider."""

from __future__ import annotations

import logging

from revlo.config import DEFAULT_PROVIDER, resolve_extraction_model
from revlo.datasheet.models import DatasheetSpec
from revlo.llm import generate_structured

logger = logging.getLogger(__name__)

_MODEL = resolve_extraction_model(DEFAULT_PROVIDER)
_MAX_TOKENS = 4096
_PDF_TEXT_LIMIT = 100_000

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


async def extract_spec(
    pdf_text: str,
    mpn: str,
    *,
    provider: str = DEFAULT_PROVIDER,
    model: str | None = None,
) -> DatasheetSpec | None:
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

    try:
        spec = await generate_structured(
            provider=provider,
            model=resolve_extraction_model(provider, model),
            schema_model=DatasheetSpec,
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_output_tokens=_MAX_TOKENS,
            tool_name="record_datasheet_spec",
            tool_description="Record the structured specifications extracted from the datasheet.",
        )
        if spec is None:
            logger.warning("Structured extraction returned no result for MPN %r", mpn)
        return spec
    except Exception:
        logger.warning("API call failed for MPN %r", mpn, exc_info=True)
        return None
