---
title: "Slack Tweet Workshop"
description: "Turn tweet ideas your team drops in a Slack channel into first-draft tweets written to your voice guide, then pick, rework and file them in a shared workshop app."
thumbnail: "template.svg"
version: v1
format: v2
---

# Slack Tweet Workshop

This file is the manifest for the **Slack Tweet Workshop** template (slug:
`slack-tweet-workshop`). It is the one document a future agent reads to understand,
present, and adapt this template. If you are an agent in a workspace that was
created from this template, this file is your script: read all of it, then
follow "How to adapt it" below.

## What it is

Turn tweet ideas your team drops in a Slack channel into first-draft tweets written to your voice guide, then pick, rework and file them in a shared workshop app.

Tweet Workshop is for a company socials team whose tweet ideas start life as messages in a Slack channel: a link, a half-formed thought, a quote from a talk. Every 10 minutes a scheduled drafter reads new messages in that one channel and has Claude write three first-draft tweets for each idea, following the team's voice guide, plus a one-line angle and a note on what material is missing. With Slack replies turned on (the default), it also replies with the drafts in the idea's thread and adds a pencil reaction. The **Tweet Workshop** app, a window on the desktop, is where the team then works: ideas sit in a queue by status (New, Workshopping, Needs material, Ready to post, Posted, Skipped); people pick a draft, edit it, ask Claude to rework it ("shorter and punchier", or any instruction) or to write more drafts at fresh angles, leave comments, copy the final text, and file it under Posted with the tweet's link. Each idea links back to its Slack message and to the drafter's saved record, raw Slack message included. The template ships with no data and no voice guide: until setup is done, the app shows a "Not set up yet" banner.

## How it works

The snapshot includes these paths (each is a repo-root-relative path copied
from the original agent onto a clean default-workspace-template base):

- `system/apps/tweet_workshop/`
- `system/supervisord.conf.d/tweet-workshop.conf`
- `system/routines/tweet-idea-drafter.toml`
- `.agents/skills/tweet-workshop-setup/`

- `system/apps/tweet_workshop/` -- the Tweet Workshop package (Flask, with `app.toml`, so the build installs it as its own uv tool). `runner.py` is the web app: the page, `/api/ideas`, saving the team's work (`PUT /api/ideas/<id>/workshop`), rework and more-drafts calls to Claude, the raw record view, and its OpenAPI document at `/api/schema`. `drafter.py` is the Slack drafter, run as `python -m tweet_workshop.drafter` with subcommands `run`, `show`, `configure` and `set-voice-guide`. `store.py` is the data layer both share; `claude_p.py` is the copied keyless `claude -p` helper; `slack_app_manifest.yaml` is the Slack app manifest an adopter pastes into api.slack.com to create the bot.
- `system/supervisord.conf.d/tweet-workshop.conf` -- the `tweet-workshop` supervisord program. It registers the app with `system/scripts/forward_port.py` (from `app.toml`) and serves it on port 8088. The shell stops it a minute after its last window closes and starts it again on the next request (`stop_when_no_windows = true`).
- `system/routines/tweet-idea-drafter.toml` -- the routine that runs `tweet_workshop.drafter run` every 10 minutes (15 minute timeout) under `system/scripts/with_secrets.py`, which puts `SLACK_BOT_TOKEN` from `data/.secrets/tweet-workshop-slack.env` into its environment. It ships switched off; setup turns it on.
- `.agents/skills/tweet-workshop-setup/` -- the setup skill the agent follows: create the Slack bot from the manifest, take its token through the secret card, pick the channel, store the voice guide from a link the user gives, choose whether drafts are replied in Slack, and turn the routine on.

At runtime the two halves meet only through files under `data/.apps/tweet-workshop/`: `settings.json` (account name, Slack workspace address, channel, posting on/off) and `voice_guide.md` are written by the drafter's `configure` and `set-voice-guide`; each `run` reads the channel from where it last stopped (`drafter_state.json`, one position per channel; the first run only records "now") and writes one record per message to `ideas/<channel>-<ts>.json`. The app reads those records and writes the team's work to `workshop/<channel>-<ts>.json`, leaving the drafter's records untouched. The drafter talks to Slack's Web API directly with the bot token (`auth.test`, `conversations.history`, `users.info`, `chat.postMessage`, `reactions.add`); both the drafter and the app's rework buttons reach Claude through `claude -p`.

## Recipe

This template is version `v1`. It is not a fork of the
workspace it came from -- it is DERIVED from it by a recipe: include these
paths, leave these out, apply these published-version rules. An update re-runs
the recipe against the current workspace and publishes the result as the next
version, so anything excluded stays excluded even though it still exists in the
source workspace.

The recipe is machine-read, so it lives in the sibling
[`template.toml`](template.toml) -- its `[recipe]` table -- along with
the structured requirements and the environment this template needs
installed. That file is authoritative for all of it; this one holds the prose.

## Requirements

Everything the adopting agent must deal with before this template is really
theirs. Two kinds of entry, handled at different times:

- **Activation** -- what must be SET UP before anything runs, in the
  machine-readable `requires_` forms below. The adopting agent acts on these
  ITSELF, first, before asking anything.
- **Adaptation** -- what must be DECIDED or REWIRED, in prose. Worked through
  interactively with the user, after activation.


- requires_secret: data/.secrets/tweet-workshop-slack.env with SLACK_BOT_TOKEN (the Bot User OAuth Token, `xoxb-...`, of a Slack bot the user creates from `system/apps/tweet_workshop/slack_app_manifest.yaml` at https://api.slack.com/apps and installs to their workspace; scopes chat:write, channels:history, channels:read, groups:history, groups:read, users:read, reactions:write. Take it through the secret card as file `tweet-workshop-slack`, variable `SLACK_BOT_TOKEN`; the `tweet-workshop-setup` skill walks through it)
- requires_llm: keyless -- the drafter and the app's rework and more-drafts buttons call Claude through `claude -p` on the workspace's own Claude sign-in (no API key needed); the model is hardcoded as `DRAFT_MODEL` in `tweet_workshop/drafter.py`, and an adopter on a keyed (`ANTHROPIC_API_KEY`) setup who wants to bill against the key must switch the calls to litellm per the `use-ai-integration` skill

Adaptation (follow the `tweet-workshop-setup` skill for all of these):

- **The ideas channel and Slack workspace.** None ships. Ask which channel the team posts tweet ideas in, have the user `/invite @Tweet Drafter` there, and run `configure` with the channel's ID and name and the Slack workspace's address (`https://<team>.slack.com`, used for links back to each message).
- **The brand name.** The drafts are written as the account's "we"; with none set they say "the company". Ask what the account tweets as and pass it to `configure --account-name`.
- **The voice guide.** A slot: no guide ships, and the drafter refuses to run without one. Ask the user for a LINK to their voice or brand guide, read the page through the `connect-external-service` skill, save its text as markdown under `data/.tasks/`, and store it with `set-voice-guide --url <link> --file <that file>`.
- **Slack replies on or off.** On by default: the drafter replies with the drafts in each idea's thread and adds a pencil reaction. Ask whether the team wants that or wants drafts to stay in the app, and set `configure --post-to-slack on|off`.
- **Turning the drafter on.** The routine ships disabled. Once the token, channel and guide are in place, run `uv run --no-sync routines enable tweet-idea-drafter` and then `routines run tweet-idea-drafter`; the first run only records "now", so the user sees drafts for the next idea posted, within about 10 minutes.
- **Known limits to tell the user about.** Comments are attributed by a name typed into the page (there are no accounts); two people saving the same idea at once is last-write-wins; replies in the Slack thread are not pulled back into the app.

## Environment

What this template needs INSTALLED, beyond what the template already has.
Declared in `template.toml`'s `[environment]` table; an adopting agent
converges it at ITS OWN pinned apt snapshot timestamp, so package versions come
out consistent with the rest of that agent's environment rather than frozen to
whatever this publisher happened to have.

Nothing extra -- runs on the stock workspace environment.

## How to adapt it

Instructions for the NEXT agent -- the one adapting this template into a
new agent. This is the `use-template` skill's template path; in short:

1. Read this entire file first, especially "Requirements" below. It holds two
   kinds of entry and they are handled at different times: the machine-readable
   `requires_` lines are ACTIVATION (set them up before anything runs), and
   the prose bullets are ADAPTATION (decide or rewire them afterwards).
2. Present the template to the user in plain, non-technical language: what
   it is, what it does, and what it needs from them (name the activation
   requirements).
3. Ask whether they want to use the same connectors (e.g. their own Slack).
   If YES: ACTIVATE FIRST -- initiate every `requires_permission` line NOW
   via a latchkey permission request (see the `connect-external-service` skill; the request
   opens the approval/login flow in the Imbue Studio app), wire up any
   `requires_secret` values, start the services, and get the app showing
   THE USER'S OWN DATA. Done for a data-backed app means the user can open it
   and see their own data -- NOT that a service starts or an endpoint returns
   200. Then tell them it is live and to take a look.
4. Only AFTER that (or immediately, if they chose different connectors -- the
   swap is then the first adaptation) ask: "How do you want to adapt it?"
5. Work through each requirement interactively, one at a time. Translate each
   into plain language, ask for a decision only when you genuinely need one,
   and resolve the obvious ones yourself.
6. When done, append a dated entry to "Adaptation history" below (never
   rewrite earlier entries) and commit.

## Publication history

This template's changelog: what each published version changed. The PUBLISHER
appends one entry per version (newest last); earlier entries are never rewritten.
This is distinct from "Adaptation history" below, which is the ADOPTERS' log.

### v1 (2026-11-02) -- First version: the Tweet Workshop app, the Slack drafter routine (shipped switched off), and its setup skill; no data and no voice guide included.

## Adaptation history

Each agent that adapts this template appends one dated entry below. Earlier
entries are never rewritten.
