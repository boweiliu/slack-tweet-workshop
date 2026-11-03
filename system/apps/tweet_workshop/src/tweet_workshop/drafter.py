"""Read new tweet ideas from a Slack channel, write first drafts to the voice guide, and keep them for Tweet Workshop.

Each run reads the channel named in ``settings.json`` from where the last run stopped, drafts three tweets
for each new idea, and saves one record per message under ``ideas/``, raw Slack message included. With
``post_to_slack`` on it also replies in the idea's thread and adds a pencil reaction.

Run from the workspace root with the bot token in the environment::

    SLACK_BOT_TOKEN=... uv run --no-sync python -m tweet_workshop.drafter run

The first run for a channel only records "now", so nothing already in the channel is drafted. The other
subcommands set the drafter up: ``configure`` (channel, account, posting) and ``set-voice-guide``.
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from tweet_workshop import store
from tweet_workshop.claude_p import claude_p_completion

DRAFT_MODEL = "claude-sonnet-5-5"
DONE_REACTION = "pencil2"

SYSTEM = """You write first-draft tweets for {account}'s X account.
Someone on the team dropped raw material in Slack: a link, a thought, a screenshot description, a quote.
Your drafts are a starting point that the socials editors will react to and rework, so give them distinct angles to choose from.
Follow the voice guide below exactly. Unless the guide says otherwise: lowercase, conversational, specific, no hype, no hashtags, no emoji, no "we're excited to announce".
Each draft must be under 280 characters. Write [link] where the shared link would go, and only if the idea included a link.
Write as {account}: a "we", never "i". If the idea is someone's personal story or hot take, still write it as {account}, and say in "needs" that it may work better on their own account with {account} quote-tweeting.
Do not name teammates or mention who posted the idea or that it came from Slack, unless the idea is about that person (an intern spotlight, a talk).
Never invent facts, numbers, or details you were not given; leave a [bracketed placeholder] instead.
If the message is not a tweet idea at all (chatter, a question for the team, a logistics note), say so.

Reply with only a JSON object, no prose around it:
{{"is_idea": true|false,
 "drafts": ["...", "...", "..."],          // exactly 3 drafts with different angles; empty if not an idea
 "angle": "...",                           // one sentence: the {account} angle you saw
 "needs": "..."}}                          // at most one short sentence: the most important missing material (a demo clip, a number, who said it), or ""

VOICE GUIDE:
"""

REWRITE_SYSTEM = """You help {account}'s socials editors rework a draft tweet for {account}'s X account.
Follow the voice guide below; unless it says otherwise: lowercase, conversational, specific, no hype, no hashtags, no emoji.
Keep it under 280 characters, keep any [link] or [bracketed placeholder], and never invent facts.
Reply with only the rewritten tweet, no quotes and no prose around it.

VOICE GUIDE:
"""

MORE_SYSTEM = """You write first-draft tweets for {account}'s X account, following the voice guide below; unless it says otherwise: lowercase, conversational, specific, no hype, no hashtags, no emoji.
You are given an idea and the drafts already written for it. Write {count} more drafts with angles none of the existing ones take.
Each under 280 characters; never invent facts, use [bracketed placeholders] instead.
Reply with only a JSON array of strings.

VOICE GUIDE:
"""


class SetupError(RuntimeError):
    """The drafter is missing something it needs: a channel, the voice guide, or the token."""


def account(settings: store.Settings) -> str:
    return settings.account_name or "the company"


def require_voice_guide() -> str:
    guide = store.read_voice_guide()
    if not guide:
        raise SetupError(
            "No voice guide yet. Copy the guide's page in with: "
            "python -m tweet_workshop.drafter set-voice-guide --url <link> --file <saved copy>"
        )
    return guide


def slack(method: str, params: dict, post: bool = False) -> dict:
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise SetupError("SLACK_BOT_TOKEN is not set: run the drafter with the Slack bot's token in its environment.")
    headers = {"Authorization": f"Bearer {token}"}
    if post:
        req = urllib.request.Request(
            f"https://slack.com/api/{method}",
            data=json.dumps(params).encode(),
            headers={**headers, "Content-Type": "application/json; charset=utf-8"},
        )
    else:
        req = urllib.request.Request(f"https://slack.com/api/{method}?{urllib.parse.urlencode(params)}", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    if not data.get("ok"):
        raise RuntimeError(f"slack {method} failed: {data.get('error')}")
    return data


def is_candidate(msg: dict, bot_user: str) -> bool:
    """A top-level human message the bot has not handled yet."""
    if msg.get("bot_id") or msg.get("user") == bot_user:
        return False
    if msg.get("subtype") not in (None, "file_share", "thread_broadcast"):
        return False
    if msg.get("thread_ts") and msg.get("thread_ts") != msg.get("ts"):
        return False
    for r in msg.get("reactions", []):
        if r["name"] == DONE_REACTION and bot_user in r.get("users", []):
            return False
    return bool(msg.get("text") or msg.get("files") or msg.get("attachments"))


def describe(msg: dict, author: str) -> str:
    """The idea as text Claude can read: message, link previews, and attached file names."""
    parts = [f"Posted by {author}:", msg.get("text", "")]
    for a in msg.get("attachments", []):
        bits = [a.get(k) for k in ("title", "title_link", "text", "service_name") if a.get(k)]
        if bits:
            parts.append("Link preview: " + " | ".join(bits))
    for f in msg.get("files", []):
        parts.append(f"Attached file: {f.get('name') or f.get('title')} ({f.get('filetype', '')})")
    return "\n".join(p for p in parts if p)


def parse_reply(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start : end + 1])


def format_reply(result: dict) -> str:
    lines = ["*First drafts* (written to the voice guide)", ""]
    for i, d in enumerate(result["drafts"], 1):
        lines += [f"*{i}.* {d}", ""]
    lines.append(f"_Angle: {result['angle']}_")
    if result.get("needs"):
        lines.append(f"_Would help: {result['needs']}_")
    lines.append("_Workshop them in this thread._")
    return "\n".join(lines)


def load_state() -> dict:
    return json.loads(store.STATE_PATH.read_text()) if store.STATE_PATH.exists() else {}


def run(channel: str, post: bool, dry_run: bool, since: str | None, test_own_posts: bool) -> None:
    settings = store.load_settings()
    guide = require_voice_guide()
    bot_user = slack("auth.test", {})["user_id"]
    state = load_state()
    cursor = since or state.get(channel)
    if cursor is None:
        state[channel] = f"{time.time():.6f}"
        store.write_json_atomically(store.STATE_PATH, state)
        print(f"first run for {channel}: starting from now, nothing older is drafted")
        return

    msgs: list[dict] = []
    params = {"channel": channel, "oldest": cursor, "limit": 200}
    while True:
        page = slack("conversations.history", params)
        msgs += page["messages"]
        nxt = page.get("response_metadata", {}).get("next_cursor")
        if not nxt:
            break
        params["cursor"] = nxt
    msgs.sort(key=lambda m: float(m["ts"]))
    print(f"{len(msgs)} new message(s) in {channel}")

    system = SYSTEM.format(account=account(settings)) + guide
    names: dict[str, str] = {}
    total_cost = 0.0
    for msg in msgs:
        is_test = test_own_posts and msg.get("user") == bot_user and msg.get("text", "").startswith("_Test")
        is_test = is_test and not any(r["name"] == DONE_REACTION for r in msg.get("reactions", []))
        if not (is_candidate(msg, bot_user) or is_test):
            continue
        uid = msg.get("user", "")
        if uid and uid not in names:
            prof = slack("users.info", {"user": uid})["user"]
            names[uid] = prof.get("real_name") or prof.get("name") or uid
        author = names.get(uid, "someone")
        started = time.time()
        res = claude_p_completion(describe(msg, author), system=system, model=DRAFT_MODEL)
        total_cost += res.cost_usd
        result = parse_reply(res.text)
        workspace_url = settings.slack_workspace_url.rstrip("/")
        link = f"{workspace_url}/archives/{channel}/p{msg['ts'].replace('.', '')}" if workspace_url else ""
        record = {
            "channel": channel,
            "ts": msg["ts"],
            "source_url": link,
            "author": author,
            "raw": msg,
            "result": result,
            "model": DRAFT_MODEL,
            "cost_usd": res.cost_usd,
            "seconds": round(time.time() - started, 1),
            "posted_reply_ts": None,
        }
        print(f"- {author}: is_idea={result['is_idea']} ${res.cost_usd:.4f} {record['seconds']}s {link}")
        if result["is_idea"] and result["drafts"]:
            text = format_reply(result)
            if dry_run:
                print(text)
            elif post:
                reply = slack(
                    "chat.postMessage",
                    {"channel": channel, "thread_ts": msg["ts"], "text": text, "unfurl_links": False, "unfurl_media": False},
                    post=True,
                )
                record["posted_reply_ts"] = reply["ts"]
                slack("reactions.add", {"channel": channel, "timestamp": msg["ts"], "name": DONE_REACTION}, post=True)
        if not dry_run:
            store.write_json_atomically(store.IDEAS_DIR / f"{store.idea_id(channel, msg['ts'])}.json", record)
            if float(msg["ts"]) > float(state.get(channel, "0")):
                state[channel] = msg["ts"]
                store.write_json_atomically(store.STATE_PATH, state)
    print(f"total drafting cost ${total_cost:.4f}")


def rewrite_draft(idea_text: str, draft: str, instruction: str) -> str:
    """One draft reworked the way the editor asked ("shorter", "more playful", or their own words)."""
    settings = store.load_settings()
    system = REWRITE_SYSTEM.format(account=account(settings)) + require_voice_guide()
    prompt = f"The idea:\n{idea_text}\n\nThe draft:\n{draft}\n\nWhat to change: {instruction}"
    return claude_p_completion(prompt, system=system, model=DRAFT_MODEL).text.strip().strip('"')


def more_drafts(idea_text: str, existing: list[str], count: int = 2) -> list[str]:
    """``count`` more drafts for an idea, at angles the existing drafts do not take."""
    settings = store.load_settings()
    system = MORE_SYSTEM.format(account=account(settings), count=count) + require_voice_guide()
    prompt = f"The idea:\n{idea_text}\n\nExisting drafts:\n" + "\n".join(f"- {d}" for d in existing)
    text = claude_p_completion(prompt, system=system, model=DRAFT_MODEL).text
    drafts = json.loads(text[text.find("[") : text.rfind("]") + 1])
    return [str(d) for d in drafts][:count]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="draft new ideas from the configured channel")
    r.add_argument("--channel", help="read this channel instead of the configured one")
    r.add_argument("--since", help="Slack ts to read from, overriding the saved cursor")
    r.add_argument("--dry-run", action="store_true", help="print drafts; save and post nothing")
    r.add_argument("--no-post", action="store_true", help="save drafts for the app but post nothing to Slack, whatever the settings say")
    r.add_argument("--test-own-posts", action="store_true", help="also draft the bot's own posts that start with _Test (for trying it in a test channel)")

    c = sub.add_parser("configure", help="set the channel, the account and whether to reply in Slack")
    c.add_argument("--account-name")
    c.add_argument("--slack-workspace-url")
    c.add_argument("--channel-id")
    c.add_argument("--channel-name")
    c.add_argument("--post-to-slack", choices=["on", "off"])

    g = sub.add_parser("set-voice-guide", help="store the voice guide drafts are written to, and the link it came from")
    g.add_argument("--url", required=True, help="the page the guide lives at")
    g.add_argument("--file", required=True, help="a saved copy of that page's text (markdown or plain text)")

    sub.add_parser("show", help="print the current settings and whether a voice guide is stored")

    args = ap.parse_args()
    try:
        if args.command == "run":
            settings = store.load_settings()
            channel = args.channel or settings.channel_id
            if not channel:
                raise SetupError("No channel set: python -m tweet_workshop.drafter configure --channel-id C... --channel-name ...")
            run(channel, settings.post_to_slack and not args.no_post, args.dry_run, args.since, args.test_own_posts)
        elif args.command == "configure":
            changes = {
                k: v
                for k, v in {
                    "account_name": args.account_name,
                    "slack_workspace_url": args.slack_workspace_url,
                    "channel_id": args.channel_id,
                    "channel_name": (args.channel_name or "").lstrip("#") or None,
                    "post_to_slack": None if args.post_to_slack is None else args.post_to_slack == "on",
                }.items()
                if v is not None
            }
            store.save_settings(store.load_settings().model_copy(update=changes))
            print(store.SETTINGS_PATH.read_text())
        elif args.command == "set-voice-guide":
            text = Path(args.file).read_text().strip()
            if not text:
                raise SetupError(f"{args.file} is empty")
            store.VOICE_GUIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
            store.VOICE_GUIDE_PATH.write_text(text + "\n")
            store.save_settings(store.load_settings().model_copy(update={"voice_guide_url": args.url}))
            print(f"voice guide stored ({len(text)} characters) from {args.url}")
        elif args.command == "show":
            print(json.dumps(store.load_settings().model_dump(), indent=2))
            guide = store.read_voice_guide()
            print(f"voice guide: {len(guide)} characters" if guide else "voice guide: none yet")
    except SetupError as e:
        print(f"Not set up yet: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
