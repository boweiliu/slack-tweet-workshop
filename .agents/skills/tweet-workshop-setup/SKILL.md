---
name: tweet-workshop-setup
description: Set up or change Tweet Workshop's Slack drafter -- connect its Slack bot, pick the ideas channel, store the voice guide from a link the user gives, and turn Slack replies on or off. Use when the Tweet Workshop app says it is not set up yet, when the user asks to connect it to Slack or change its channel, when they give a new voice guide link, or when they want drafts posted (or no longer posted) in Slack.
secrets:
  - file: tweet-workshop-slack
    variables: [SLACK_BOT_TOKEN]
    note: the Bot User OAuth Token (xoxb-...) of the Slack bot created from system/apps/tweet_workshop/slack_app_manifest.yaml
---

# Setting up Tweet Workshop

Tweet Workshop has two parts:

- **The drafter**: the `tweet-idea-drafter` routine. Every 10 minutes it runs
  `python -m tweet_workshop.drafter run`, which reads new messages in one Slack
  channel and writes three draft tweets per idea to the voice guide. When
  posting is on, it also replies in each idea's thread and adds a pencil
  reaction.
- **The app**: where the team picks, reworks and files those drafts.

Its settings live in `data/.apps/tweet-workshop/settings.json`, and the guide in
`data/.apps/tweet-workshop/voice_guide.md`. Only change either through the
drafter's own commands:

```bash
uv run --no-sync python -m tweet_workshop.drafter show
uv run --no-sync python -m tweet_workshop.drafter configure --account-name "<brand>" \
    --slack-workspace-url https://<team>.slack.com --channel-id C... --channel-name <name> --post-to-slack on|off
uv run --no-sync python -m tweet_workshop.drafter set-voice-guide --url <link> --file <saved copy>
```

Run them from the workspace root.

## First-time setup

Do these in order. Skip any that `show` says are already done.

1. **The Slack bot.** The drafter runs as its own bot, and the user creates it
   once:
   1. Have them go to <https://api.slack.com/apps> and choose "Create New App",
      then "From a manifest". They pick their workspace and paste
      `system/apps/tweet_workshop/slack_app_manifest.yaml`.
   2. They install the app to the workspace.
   3. They copy the **Bot User OAuth Token**, which starts with `xoxb-`.

   Take the token through the secret card, never in chat, with
   `--file tweet-workshop-slack --var SLACK_BOT_TOKEN`. The
   `connect-external-service` skill has the card's rules. The routine reads
   that secret file through `system/scripts/with_secrets.py`.
2. **The channel.** Ask which channel the team posts tweet ideas in. In Slack,
   the user types `/invite @Tweet Drafter` in that channel. Get the channel's
   ID: it's at the bottom of the channel's details, or it's the `C...` part of
   a link to the channel. Then run `configure` with the ID, the channel's name,
   the workspace's address and the brand the account tweets as.
3. **The voice guide: a link the user provides.** Templates ship without a
   guide. Ask for a link to the team's voice or brand guide (a Notion page,
   Google Doc, or any web page).
   1. Read the page through the `connect-external-service` skill. A page behind
      a login needs the user's connected account.
   2. Save its text as markdown to a scratch file under `data/.tasks/`.
   3. Run `set-voice-guide --url <the link> --file <that file>`.

   With no guide stored, the drafter refuses to run, and the app's rework
   buttons answer that it is not set up.
4. **Posting.** Ask whether drafts should also be replied in the Slack thread,
   or stay in the app. Set the answer with `configure --post-to-slack on|off`.
5. **Turn it on.** Run `uv run --no-sync routines enable tweet-idea-drafter`,
   then `uv run --no-sync routines run tweet-idea-drafter`. The first run only
   records "now", so nothing already in the channel is drafted. New posts show
   up in the app within about 10 minutes.

## Changing it later

- **A new guide link:** repeat step 3. Drafts already written stay as they are.
- **Posting on or off:** run `configure --post-to-slack on` or
  `configure --post-to-slack off`. The next run follows the new setting.
- **Another channel:** run `configure --channel-id ... --channel-name ...`.
  The drafter keeps a separate reading position for each channel.
