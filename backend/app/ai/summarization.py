"""Document summarization (LP-65) — the Tier 2 lightweight "what is this?" gist.

Tier 2 documents (the ~60-80 *recognized* types) are classified + categorized but
**not** field-extracted. Instead, ONE shared path gives each a short 1-2 sentence
**summary** — a human-readable gist for a processor's quick reference (what the
document is + the key identifying detail), NOT structured data and NOT source
locations. The KEY contrast with Tier 1: Tier 1 extracts precise values that drive
decisions; Tier 2 just summarizes for reference.

So this is deliberately **cheap and forgiving**:

  * **Cheap** — a lightweight Haiku-class call (the classification model), capped
    low. Low cost-per-document is the point of Tier 2 (one summary path for ~80
    types, not ~80 extractors).
  * **Forgiving** — a slightly-off gist is fine (human reference, not a
    calculation). Low stakes; refine-able.
  * **Graceful** — like :func:`app.ai.classification.classify_document`, this NEVER
    raises: any failure (AI error, empty/unsupported document) returns ``None`` and
    the pipeline still finalizes the document (recognized + categorized, no summary).
  * **Private** — the document bytes/base64 and the raw response are never logged.
"""

import structlog

from app.ai.client import AIClientError, build_document_message, complete
from app.ai.prompt_loader import load_prompt
from app.core.config import settings

logger = structlog.get_logger(__name__)

_SUMMARY_PROMPT_PATH = "summarization/document_summary.txt"
# Same media allowlist as classification/extraction (LP-36 upload + LP-37 blocks).
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# A summary is 1-2 sentences — cap tokens low (cheap).
_MAX_TOKENS = 256
# A safety cap on the stored gist (the prompt asks for 1-2 sentences; this guards
# against a rambling response without failing it).
_MAX_SUMMARY_CHARS = 600


async def summarize_document(content: bytes, media_type: str) -> str | None:
    """Summarize a document into a 1-2 sentence gist. Never raises; ``None`` on failure.

    An empty/unsupported document short-circuits to ``None`` without an API call.
    Otherwise it loads the summary prompt, sends the **full document** to the
    Haiku-class model (cheap — it's a gist, not extraction), and returns a trimmed
    short string. Any AI error or empty output returns ``None`` (the pipeline
    finalizes the document without a summary). The document bytes/base64 and the
    raw response are never logged (PII).
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return None

    system_prompt = load_prompt(_SUMMARY_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return None

    try:
        result = await complete(
            model=settings.anthropic_model_classification,  # cheap Haiku-class model
            system=system_prompt,
            messages=[message],
            max_tokens=_MAX_TOKENS,
        )
    except AIClientError:
        logger.warning("summarization_ai_failed")  # metadata only — no bytes/content
        return None

    summary = result.text.strip()
    if not summary:
        return None
    if len(summary) > _MAX_SUMMARY_CHARS:  # guard a rambling response (don't fail it)
        summary = summary[:_MAX_SUMMARY_CHARS].rstrip()

    # Metadata only: the length, never the summary text (it can quote document PII).
    logger.info("summarization_succeeded", summary_chars=len(summary))
    return summary
