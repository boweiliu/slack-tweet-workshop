<p align="center">
  <img alt="Slack Tweet Workshop" src="template.svg" width="480">
</p>

# Slack Tweet Workshop

<p align="center">
  <a href="https://studio.imbue.com/open?git_url=https://github.com/boweiliu/slack-tweet-workshop"><img alt="Open in Imbue Studio" height="64" src="https://img.shields.io/badge/Open%20in%20Imbue%20Studio-D8D1C0?style=for-the-badge"></a>
</p>

Didn't work? Create a Studio workspace and paste this to your agent:
` /use-template https://github.com/boweiliu/slack-tweet-workshop`

## Why you care

Good tweet ideas get dropped in Slack all day and then sit there, because turning a link or a half-thought into something postable is the slow part. This writes the first drafts for you, in your own voice, within minutes of an idea landing, and gives the team one place to pick, polish and track what actually goes out.

## How to use it

1. **Set it up once.** Ask your agent to set up Tweet Workshop. It walks you through creating a small Slack bot from the included manifest (you paste one token into a secure card, never into chat), asks which channel your team posts ideas in, the name your account tweets as, and a link to your voice or brand guide, and whether drafts should also be replied in Slack.
2. **Drop ideas in Slack as usual.** A link, a quote, a screenshot description, a rough thought. Within about 10 minutes each one gets three draft tweets at different angles, written to your guide, with a note on any missing material (a number, a demo clip). If Slack replies are on, the drafts appear in the idea's thread with a pencil reaction.
3. **Work them in the Tweet Workshop app.** Ideas sit in a queue by status:

   | Tab | What's there |
   | --- | --- |
   | New | Fresh ideas with their drafts |
   | Workshopping | Ideas someone has started on |
   | Needs material | Waiting on a number, a clip, a quote |
   | Ready to post | A picked, polished draft, with a copy button |
   | Posted | Filed with the link to the live tweet |
   | Skipped | Not a tweet, or not now; one click brings it back |

   On an idea you can pick a draft, edit it by hand, ask Claude to rework it ("shorter and punchier", "more concrete", or your own instruction), ask for more drafts at new angles, and leave notes for the team. Every idea links back to its Slack message and to the saved original.

Nothing is ever tweeted for you: the app gets a draft to "ready", and a person posts it.

## Ideas for making it yours

- **Draft for more than one network.** Add a LinkedIn or Bluesky variant next to each tweet, with its own length limit and tone notes in the guide.
- **Change the batch.** Ask for five drafts instead of three, or a thread when an idea is too big for one tweet.
- **Send a daily digest.** Add a morning routine that posts the "Ready to post" queue to the channel, so whoever is posting that day has the list.
- **Pull Slack replies back in.** Read each idea's thread on the next run so teammates' comments in Slack show up beside the drafts.
- **Learn from what ships.** Feed the posted tweets back into the prompt as examples, so drafts drift toward what the team actually picks.

## What this is

This repository is a published **Imbue Studio template**: a clean, bootable
snapshot of what an agent built, ready to adapt into your own. It is NOT the
generic workspace template -- it is this specific project.

[`template.md`](template.md) is the full manifest -- what it is, how it
works, what it needs to run, and what to adapt -- with the
machine-readable half (recipe, requirements, and the environment it needs
installed) in [`template.toml`](template.toml).
