"""Where Tweet Workshop keeps its data, shared by the app and the Slack drafter.

Everything lives under ``DATA_DIR`` (default ``data/.apps/tweet-workshop/``, overridable through
``TWEET_WORKSHOP_DATA_DIR`` so a throwaway instance can run on a copy):

- ``settings.json``: which Slack channel to read, whether to reply there, and where the voice guide came from.
- ``voice_guide.md``: the voice guide drafts are written to, a copy of the page at ``voice_guide_url``.
- ``ideas/<channel>-<ts>.json``: one record per Slack message the drafter handled, raw message included.
  Written only by the drafter.
- ``workshop/<channel>-<ts>.json``: what the team did with that idea in the app (status, picked and
  edited drafts, comments). Written only by the app.
"""

import json
import os
import re
from pathlib import Path

from imbue.imbue_common.frozen_model import FrozenModel
from pydantic import Field

DATA_DIR = Path(os.environ.get("TWEET_WORKSHOP_DATA_DIR", "data/.apps/tweet-workshop"))
SETTINGS_PATH = DATA_DIR / "settings.json"
VOICE_GUIDE_PATH = DATA_DIR / "voice_guide.md"
IDEAS_DIR = DATA_DIR / "ideas"
WORKSHOP_DIR = DATA_DIR / "workshop"
STATE_PATH = DATA_DIR / "drafter_state.json"

IDEA_ID_PATTERN = re.compile(r"^[A-Z0-9]+-\d+\.\d+$")


class Settings(FrozenModel):
    """How the drafter is set up."""

    account_name: str = Field(default="", description="Whose X account the drafts are for, e.g. Acme")
    slack_workspace_url: str = Field(default="", description="The Slack workspace's address, e.g. https://example.slack.com")
    channel_id: str = Field(default="", description="The Slack channel ideas are read from, e.g. C0123456789")
    channel_name: str = Field(default="", description="That channel's name without the #, for display")
    post_to_slack: bool = Field(default=True, description="Whether the drafter replies in the idea's Slack thread")
    voice_guide_url: str = Field(default="", description="The page the voice guide was copied from")


def load_settings() -> Settings:
    if not SETTINGS_PATH.exists():
        return Settings()
    return Settings.model_validate_json(SETTINGS_PATH.read_text())


def write_json_atomically(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False))
    tmp.replace(path)


def save_settings(settings: Settings) -> None:
    write_json_atomically(SETTINGS_PATH, settings.model_dump())


def read_voice_guide() -> str | None:
    return VOICE_GUIDE_PATH.read_text() if VOICE_GUIDE_PATH.exists() else None


def idea_id(channel: str, ts: str) -> str:
    return f"{channel}-{ts}"
