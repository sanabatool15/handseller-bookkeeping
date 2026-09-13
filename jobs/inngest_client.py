"""Shared Inngest client instance.

Assumption / documented limitation: the `inngest` PyPI package's exact
constructor signature has shifted across versions (event_key vs signing_key
kwargs, sync vs async `send`). We pin the shape we use here explicitly and
isolate all Inngest SDK access behind this module + `jobs/financial_agent_job.py`
so a version mismatch only requires touching this file. See README section
"Inngest integration assumptions".
"""
from __future__ import annotations

import inngest

from app.config import get_settings

_settings = get_settings()

inngest_client = inngest.Inngest(
    app_id="handseller-bookkeeping",
    event_key=_settings.inngest_event_key,
    signing_key=_settings.inngest_signing_key,
    is_production=not _settings.inngest_dev,
)
