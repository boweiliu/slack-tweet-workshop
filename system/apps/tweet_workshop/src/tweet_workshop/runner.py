"""Workshop first-draft tweets that Studio writes from ideas posted in Slack, then pick and polish what gets posted.

Services run from /home/user/workspace (the repo root). Conventions:

- Persistent state (anything written and read across runs -- cursors,
  caches, snapshots, user records): read and write it under ``DATA_DIR``
  (defined below), never a hardcoded ``data/.apps/tweet-workshop/`` at the
  call site. ``DATA_DIR`` defaults to ``data/.apps/tweet-workshop/`` but
  honors the ``TWEET_WORKSHOP_DATA_DIR`` env var, so an editing agent can point a
  throwaway instance at a *copy* of the data instead of the live store
  (see the update-app skill). Do NOT use ``Path(__file__)``-based
  paths for state -- the bug to avoid is one process writing to
  ``/home/user/workspace/data/.apps/...`` while another reads from
  ``/home/user/workspace/system/apps/<pkg>/data/...``.
- Static assets shipped alongside this file (templates, default
  configs, bundled JSON): ``Path(__file__).parent / "assets/..."`` is
  fine and is the right pattern.
- Listen port: bind ``PORT`` (defined below), which defaults to this
  app's assigned port but honors the ``TWEET_WORKSHOP_PORT`` env var, so
  an editing agent can boot a throwaway instance on a *spare* port
  alongside the live one (see the update-app skill). Never hardcode
  the port at the ``run_simple`` call.

This is a synchronous Flask app served by the threaded Werkzeug server.
The app owns its own browser origin (the forwarder routes
``http://tweet-workshop.<workspace-host>/`` straight to this port), so it serves
at ``/`` and root-absolute URLs, cookies, and service workers all work
unmodified -- nothing rewrites anything. Use ``flask_sock`` if you need
WebSockets.
"""

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlparse
from pathlib import Path

from app_schema.api_schema import (
    DEFAULT_API_SCHEMA_PATH,
    RouteModels,
    RouteTable,
    SchemalessRoute,
    register_api_schema_route,
)
from app_schema.routes import error_response, model_response, parse_request_body
from flask import Flask, Response, abort, request, send_file
from imbue.imbue_common.frozen_model import FrozenModel
from imbue.imbue_common.logging import setup_logging
from loguru import logger
from pydantic import Field
from werkzeug.serving import run_simple

from tweet_workshop import drafter, store

# Persistent state lives under DATA_DIR (store.py), overridable via ``TWEET_WORKSHOP_DATA_DIR``
# so a throwaway instance can run against a *copy* of the data -- see the update-app skill.

# Listen port. Defaults to this app's assigned port but is overridable via
# the ``TWEET_WORKSHOP_PORT`` env var so an editing agent can boot a throwaway
# instance on a spare port next to the live one (see the update-app skill).
# Never hardcode the port at the ``run_simple`` call, or the override is bypassed.
PORT = int(os.environ.get("TWEET_WORKSHOP_PORT", "8088"))

# The browser-side modules the workspace shell builds and every app serves from
# its own origin: the app contract (how a page talks to the shell framing it) and
# the element context menu (the right-click menu whose last rows hand the
# clicked element to a chat). A module import is a fetch without cookies, which
# the forwarder refuses across origins, so they are served here rather than from
# the shell. Relative to the repo root the service runs from, like DATA_DIR.
SHELL_STATIC_MODULES_DIR = Path("system/apps/system_interface/imbue/system_interface/static/_static")
SHELL_STATIC_MODULE_NAMES = ('app_contract.js', 'context_menu.js')

# The script every page serves (keep it on every page): it connects the page to
# the shell, reports where the page is on the handshake so the shell can reopen
# this app's window at the same place, and installs the element context menu.
# A page visited outside the shell runs it harmlessly: nothing arrives, and the
# menu's Explain and Modify rows grey out.
SHELL_PAGE_SCRIPT_BODY = """
  import { connectToShell } from "/_static/app_contract.js";
  import { installElementContextMenu } from "/_static/context_menu.js";
  let handshake = null;
  const connection = connectToShell({
    onHandshake: (received) => {
      handshake = received;
      connection.location(location.pathname + location.search, document.title);
    },
  });
  installElementContextMenu({ connection, handshake: () => handshake });
"""
SHELL_PAGE_SCRIPT = f'<script type="module">{SHELL_PAGE_SCRIPT_BODY}</script>'


def inline_script_source(body: str) -> str:
    """The Content-Security-Policy source admitting one inline <script> whose body is exactly ``body``."""
    return "'sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() + "'"


# Every HTML page is served under this policy (the app is reachable from the
# internet once the workspace is shared): scripts only from this origin plus the
# inline blocks listed here by hash, fetches, sockets and images only from this
# origin, inline styles, frames of any http(s) page, no plugins. Anything else a
# page pulls in (a CDN script, Google Fonts, an image hosted elsewhere, a
# third-party API called from the browser) is blocked until its origin is added
# to the matching directive; a new inline <script> needs its
# ``inline_script_source`` added.
# The browser posts every block to ``/_csp-report`` below, which logs it on
# stderr (the supervisor log), so a blocked resource is never silent; the
# ``'report-sample'`` makes the browser include where a blocked inline script
# is and how it starts, since the report otherwise names it only as "inline".
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    f"script-src 'self' 'report-sample' {inline_script_source(SHELL_PAGE_SCRIPT_BODY)}; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; frame-src http: https:; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; "
    "report-uri /_csp-report"
)
BROWSER_EXTENSION_SCHEMES = ("chrome-extension:", "moz-extension:", "safari-web-extension:")


class HealthResponse(FrozenModel):
    """What the health probe answers."""

    status: str = Field(description="Always 'ok'")


class LinkPreview(FrozenModel):
    """The preview Slack showed for a link in the idea."""

    url: str
    host: str
    title: str
    desc: str


class Draft(FrozenModel):
    """One draft tweet and its edit history."""

    versions: list[str] = Field(description="Every version of the draft, oldest first; the last is current")
    picked: bool = Field(default=False, description="Whether this is the draft the team chose")


class Comment(FrozenModel):
    """A note someone left on an idea."""

    by: str
    when: str = Field(description="ISO timestamp")
    text: str


class Workshop(FrozenModel):
    """What the team has done with an idea in the app."""

    status: str = Field(description="new, workshopping, waiting, ready, posted or skipped")
    drafts: list[Draft]
    comments: list[Comment] = Field(default_factory=list)
    skip_reason: str = ""
    posted_url: str = ""


class Idea(FrozenModel):
    """A tweet idea from Slack with Studio's drafts and the team's work on them."""

    id: str
    author: str
    when: str = Field(description="When it was posted in Slack, ISO timestamp")
    text: str
    source_url: str = Field(description="The message in Slack, or empty when the Slack workspace is not set")
    link: LinkPreview | None
    is_idea: bool
    angle: str
    needs: str
    posted_to_slack: bool = Field(description="Whether the drafter replied in the Slack thread")
    workshop: Workshop


class VoiceGuide(FrozenModel):
    """Where the voice guide came from, and whether one is stored."""

    url: str
    stored: bool


class IdeasResponse(FrozenModel):
    """Every idea, newest first, with how the drafter is set up."""

    account_name: str
    channel_name: str
    channel_url: str
    post_to_slack: bool
    voice_guide: VoiceGuide
    ideas: list[Idea]


class RewriteRequest(FrozenModel):
    """Which draft to rework and how."""

    draft_index: int = Field(ge=0)
    instruction: str = Field(min_length=1, max_length=500)


class RewriteResponse(FrozenModel):
    """The reworked draft text."""

    text: str


class MoreDraftsResponse(FrozenModel):
    """New drafts at fresh angles."""

    drafts: list[str]


# What every route exchanges, which the app's API document publishes and every parse and answer
# is checked against (build-app skill, "The app describes its own API"): a route that reads or
# answers JSON names its pydantic models here and uses ``parse_request_body`` and
# ``model_response``; a page, a file or a stream is declared schemaless with the reason.
ROUTE_TABLE: RouteTable = {
    ("GET", "/"): SchemalessRoute(reason="the app's page"),
    ("GET", "/_static/{basename}"): SchemalessRoute(reason="a browser-side module the shell builds"),
    ("GET", "/assets/{basename}"): SchemalessRoute(reason="the page's own script and stylesheet"),
    ("GET", "/health"): RouteModels(response_model=HealthResponse),
    ("GET", "/api/ideas"): RouteModels(response_model=IdeasResponse),
    ("PUT", "/api/ideas/{idea_id}/workshop"): RouteModels(request_model=Workshop, response_model=Idea),
    ("POST", "/api/ideas/{idea_id}/rewrite"): RouteModels(request_model=RewriteRequest, response_model=RewriteResponse),
    ("POST", "/api/ideas/{idea_id}/more"): RouteModels(response_model=MoreDraftsResponse),
    ("GET", "/api/ideas/{idea_id}/record"): SchemalessRoute(reason="the drafter's saved record as it was written, raw Slack message included"),
    ("POST", "/_csp-report"): SchemalessRoute(reason="the browser's report of what the page's policy blocked"),
}

app = Flask("tweet_workshop", static_folder=None)
# The app describes its own API: an OpenAPI document of every route below, served at the
# manifest's api_schema_path.
register_api_schema_route(
    app, DEFAULT_API_SCHEMA_PATH, title='Tweet Workshop', description='Workshop first-draft tweets that Studio writes from ideas posted in Slack, then pick and polish what gets posted', route_table=ROUTE_TABLE
)


@app.after_request
def add_content_security_policy(response: Response) -> Response:
    if response.mimetype == "text/html":
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    return response


ASSETS_DIR = Path(__file__).parent / "assets"
ASSET_MIMETYPES = {"app.js": "text/javascript", "app.css": "text/css"}


@app.route("/")
def index() -> Response:
    """The workshop page."""
    page = (ASSETS_DIR / "index.html").read_text()
    return Response(page.replace("<!--SHELL_PAGE_SCRIPT-->", SHELL_PAGE_SCRIPT), mimetype="text/html")


@app.route("/assets/<basename>")
def asset(basename: str) -> Response:
    """The page's own script and stylesheet."""
    if basename not in ASSET_MIMETYPES:
        abort(404)
    return send_file(ASSETS_DIR / basename, mimetype=ASSET_MIMETYPES[basename], max_age=0)


WORKSHOP_STATUSES = {"new", "workshopping", "waiting", "ready", "posted", "skipped"}


def link_preview(raw: dict) -> LinkPreview | None:
    for a in raw.get("attachments") or []:
        url = a.get("title_link") or a.get("from_url") or a.get("original_url")
        if url and a.get("is_msg_unfurl"):
            # A Slack message shared into the channel: show who wrote it and what it said.
            return LinkPreview(url=url, host="Shared Slack message", title=a.get("author_name") or "Slack message", desc=a.get("text") or "")
        if url:
            return LinkPreview(
                url=url,
                host=urlparse(url).netloc.removeprefix("www."),
                title=a.get("title") or a.get("fallback") or url,
                desc=a.get("text") or "",
            )
    return None


def initial_workshop(record: dict) -> Workshop:
    result = record["result"]
    if not result.get("is_idea"):
        return Workshop(status="skipped", drafts=[], skip_reason="Not a tweet idea, so Studio didn't draft anything. Bring it back if that's wrong.")
    return Workshop(status="new", drafts=[Draft(versions=[d]) for d in result.get("drafts", [])])


def load_idea(path: Path) -> Idea:
    record = json.loads(path.read_text())
    iid = path.stem
    workshop_path = store.WORKSHOP_DIR / f"{iid}.json"
    workshop = Workshop.model_validate_json(workshop_path.read_text()) if workshop_path.exists() else initial_workshop(record)
    raw, result = record["raw"], record["result"]
    return Idea(
        id=iid,
        author=record.get("author") or "someone",
        when=datetime.fromtimestamp(float(record["ts"]), tz=timezone.utc).isoformat(),
        text=raw.get("text") or "",
        source_url=record.get("source_url") or "",
        link=link_preview(raw),
        is_idea=bool(result.get("is_idea")),
        angle=result.get("angle") or "",
        needs=result.get("needs") or "",
        posted_to_slack=bool(record.get("posted_reply_ts")),
        workshop=workshop,
    )


def idea_path(idea_id: str) -> Path:
    """The drafter's record for ``idea_id``; a malformed or unknown id is a 404."""
    if not store.IDEA_ID_PATTERN.match(idea_id):
        abort(404)
    path = store.IDEAS_DIR / f"{idea_id}.json"
    if not path.is_file():
        abort(404)
    return path


def idea_prompt_text(idea: Idea) -> str:
    text = f"Posted by {idea.author}:\n{idea.text}"
    if idea.link:
        text += f"\nLink preview: {idea.link.title} | {idea.link.url} | {idea.link.desc}"
    return text


@app.route("/api/ideas")
def list_ideas() -> Response:
    """Every idea from the configured Slack channel, newest first, with Studio's drafts and the team's work on them."""
    settings = store.load_settings()
    paths = sorted(store.IDEAS_DIR.glob("*.json")) if store.IDEAS_DIR.exists() else []
    if settings.channel_id:
        paths = [p for p in paths if p.stem.startswith(settings.channel_id + "-")]
    ideas = sorted((load_idea(p) for p in paths), key=lambda i: i.when, reverse=True)
    workspace_url = settings.slack_workspace_url.rstrip("/")
    return model_response(
        IdeasResponse(
            account_name=settings.account_name,
            channel_name=settings.channel_name,
            channel_url=f"{workspace_url}/archives/{settings.channel_id}" if workspace_url and settings.channel_id else "",
            post_to_slack=settings.post_to_slack,
            voice_guide=VoiceGuide(url=settings.voice_guide_url, stored=store.read_voice_guide() is not None),
            ideas=ideas,
        )
    )


@app.route("/api/ideas/<idea_id>/workshop", methods=["PUT"])
def save_workshop(idea_id: str) -> Response:
    """Save what the team did with an idea: its status, picked and edited drafts, comments, and where it was posted."""
    path = idea_path(idea_id)
    workshop = parse_request_body(Workshop)
    if workshop.status not in WORKSHOP_STATUSES:
        return error_response(f"status must be one of {sorted(WORKSHOP_STATUSES)}", 400)
    store.write_json_atomically(store.WORKSHOP_DIR / f"{idea_id}.json", workshop.model_dump())
    return model_response(load_idea(path))


@app.route("/api/ideas/<idea_id>/rewrite", methods=["POST"])
def rewrite(idea_id: str) -> Response:
    """Have Studio rework one draft the way the editor asked; nothing is saved until the editor keeps it."""
    idea = load_idea(idea_path(idea_id))
    body = parse_request_body(RewriteRequest)
    if body.draft_index >= len(idea.workshop.drafts):
        return error_response("no draft at that index", 400)
    current = idea.workshop.drafts[body.draft_index].versions[-1]
    try:
        text = drafter.rewrite_draft(idea_prompt_text(idea), current, body.instruction)
    except drafter.SetupError as e:
        return error_response(str(e), 409)
    return model_response(RewriteResponse(text=text))


@app.route("/api/ideas/<idea_id>/more", methods=["POST"])
def more(idea_id: str) -> Response:
    """Have Studio write two more drafts for an idea, at angles the existing ones don't take."""
    idea = load_idea(idea_path(idea_id))
    try:
        drafts = drafter.more_drafts(idea_prompt_text(idea), [d.versions[-1] for d in idea.workshop.drafts])
    except drafter.SetupError as e:
        return error_response(str(e), 409)
    return model_response(MoreDraftsResponse(drafts=drafts))


@app.route("/api/ideas/<idea_id>/record")
def idea_record(idea_id: str) -> Response:
    """The drafter's saved record for an idea, exactly as written, raw Slack message included."""
    record = json.loads(idea_path(idea_id).read_text())
    return Response(json.dumps(record, indent=2, ensure_ascii=False), mimetype="application/json")


@app.route("/_csp-report", methods=["POST"])
def content_security_policy_report() -> Response:
    """Where the browser reports what the page's security policy blocked."""
    body = request.get_json(force=True, silent=True)
    report = body.get("csp-report") if isinstance(body, dict) else None
    if not isinstance(report, dict):
        return Response(status=204)
    blocked, page, source, directive, line, sample = (
        str(report.get(key, ""))[:500]
        for key in ("blocked-uri", "document-uri", "source-file", "effective-directive", "line-number", "script-sample")
    )
    # A block caused by a browser extension is the policy doing its job and is not logged.
    if blocked.startswith(BROWSER_EXTENSION_SCHEMES) or source.startswith(BROWSER_EXTENSION_SCHEMES):
        return Response(status=204)
    # An inline script or style is reported as "inline": say where it is and how it starts instead.
    where = f" at {source}:{line}" if source and line else ""
    starting = f" starting {sample!r}" if sample else ""
    remedy = (
        "add its inline_script_source to CONTENT_SECURITY_POLICY if the page needs it"
        if blocked == "inline"
        else "add its origin to CONTENT_SECURITY_POLICY if the page needs it"
    )
    logger.error(
        "Content-Security-Policy blocked {!r} on {!r} ({}){}{}; {}", blocked, page, directive, where, starting, remedy
    )
    return Response(status=204)


@app.route("/_static/<basename>")
def shell_module(basename: str) -> Response:
    """One of the two browser-side modules the workspace shell builds and every app serves from its own origin."""
    # The two shell-built modules and nothing else: a name that is not one of
    # them is a 404, so this route can never read outside that directory.
    if basename not in SHELL_STATIC_MODULE_NAMES:
        abort(404)
    module_path = SHELL_STATIC_MODULES_DIR / basename
    if not module_path.is_file():
        abort(404)
    # Flask resolves a relative path against the app's own directory, not the cwd.
    return send_file(module_path.absolute(), mimetype="text/javascript")


@app.route("/health")
def health() -> Response:
    """Whether the app is up."""
    return model_response(HealthResponse(status="ok"))


def main() -> None:
    setup_logging()
    run_simple(
        "127.0.0.1", PORT, app, threaded=True, use_reloader=False, use_debugger=False
    )


if __name__ == "__main__":
    main()
