# Podcast Digest

An AI-powered podcast intelligence pipeline that turns long-form industry conversations into decision-ready strategic briefs — built first and foremost to surface **interviews with competitor executives**.

## What it does

Podcast Digest monitors selected RSS and YouTube podcast sources, filters each new episode for strategic relevance, enriches the best candidates with full transcripts or captions, and generates a structured intelligence digest.

Its **top priority is competitor-executive interviews.** When a competitor's founder / C-level / VP — or a notable creator-economy, streaming, music, or AI-content operator — is a guest, that episode is caught as a priority and surfaced at the top of the digest in its own section. Strong general industry conversations still make the cut, but in a separate, secondary section. It is designed for teams that need to track fast-moving signals across media, creator economy, streaming, AI content production, short drama, music, platform competition, and related regulation — without manually listening to hours of podcasts every week.

The system helps answer questions like:

- **Which competitor executives went on record this week, and what did they say?**
- Which episodes actually matter to our strategy?
- What competitor moves, platform shifts, or AI capability changes are worth tracking?
- What did the speakers say, and why does it matter?
- Which insights should be pushed to a team channel as a weekly digest?

Instead of producing generic summaries, Podcast Digest applies a configurable screening and analysis framework so each output is tied to topics, competitors, relevance scores, and strategic implications.

## Design philosophy

Three principles shape the project:

- **Low / no-code, built to be shared on a team.** Everything you'd normally tune — which podcasts to follow, what counts as "relevant," where to send the digest — lives in plain config files (`sources.yaml`, `filters.yaml`) and a `.env` file. A non-engineer can add a source, adjust the filters, and run it without touching Python. It's meant to be set up once and handed around a team, not owned by one developer.
- **Cost- and token-efficient by design.** This is meant to run as an always-on digest bot, so it's careful with money. Cheap screening (keyword matching or a small, fast model) decides what's worth a closer look; the expensive, high-quality model is only spent on the handful of episodes that pass. Low-signal episodes are skipped before any enrichment or deep analysis happens.
- **Always-on and hands-off.** Point it at your sources once, put your relevance criteria in config, and let it run on a schedule — it collects, filters, analyzes, and pushes a digest to your team channel on its own.

## How it works

1. **Collect episodes** — Pulls recent episodes from configured podcast RSS feeds and YouTube channel RSS sources.
2. **Parse and clean content** — Extracts show notes, episode metadata, links, and available text. Cleans HTML into model-ready text.
3. **Screen for relevance + spot the guest** — Scores episodes against configurable topics, competitors, and exclusion rules, *and* identifies who the guest is. A competitor-executive guest makes an episode a priority interview (see *Two ways to screen* and *Guest priority* below).
4. **Enrich selected episodes** — Fetches full transcripts, articles, or captions only for relevant episodes. Keeps cost low by skipping low-signal content.
5. **Analyze with an LLM** — Produces cross-episode insights, episode-level summaries, key quotes, competitor moves, and strategic implications — **only for episodes where a real transcript/full text was obtained.** Relevant episodes with no transcript are flagged, not deep-analyzed (so the expensive model is never spent on thin show notes).
6. **Deliver the digest** — Prints a report and pushes structured cards to a Feishu/Lark group via webhook, split into **competitor-exec interviews** (primary) and **strong industry topics** (secondary).
7. **Log everything (optional)** — Appends every processed episode — Relevant, Irrelevant, and Skipped — to a Feishu spreadsheet for audit, so data you already spent compute on is never lost (see *Audit logging*).

### Two ways to screen for relevance

There are two modes for deciding whether an episode is worth analyzing:

- **Default — Claude reads the show notes.** Each episode's show notes are sent to a fast, low-cost Claude model that judges relevance against the topics and competitors you've configured. This is the most accurate option and works for any source.
- **Keyword match (opt-in).** For podcasts whose show notes are **well-documented and comprehensive** — i.e. they reliably spell out the platforms, people, and topics covered — you can set `screening: keyword` on that source. Relevance is then decided by simple keyword matching, with **no LLM call and zero tokens**. Best for high-volume sources you trust to describe themselves clearly.

### Guest priority — the interview-first signal

Beyond topic relevance, Claude screening also reads the show notes to work out **who the guest is** and where they work. The guest's company is matched against your `competitor_companies` list (and the model recognizes notable creator-economy / streaming / video / music / AI-content operators too):

- **A competitor executive as guest → priority interview.** The episode is caught regardless of topic — *being from a competitor matters more than seniority* — and surfaced at the top of the digest in its own section.
- **Host solo / hot takes, or a journalist or commentator with no notable-company affiliation → deprioritized.** It can still qualify on a genuinely strong topic, but lands in the secondary "industry topics" section.

The guest's name and title are shown in the digest, and episodes are sorted so priority interviews come first. This needs **no web search** — show notes almost always name the guest's company and title, so the model judges the *company*, not the person. (Keyword-screened sources don't get guest scoring.)

## Current podcast sources

The sources are chosen to be **complementary** — each covers a different slice of the team's interests, so together they span AI capability, platform strategy, creator economy, music, and media business.

| Source | Hosts | What it covers | Full text via |
|---|---|---|---|
| **Decoder with Nilay Patel** | Nilay Patel (The Verge) | Tech & media business — platform strategy, AI, creator tools, executive interviews | The Verge article/transcript pages |
| **Big Technology** | Alex Kantrowitz | The AI industry & big tech — frontier models, platform strategy, and periodically creator economy / streaming (e.g. Spotify AI music, Netflix, Sora) | Substack auto-transcripts |
| **Your Morning Coffee** | Jay Gilbert & Mike Etchart | The music business — streaming economics, AI music, distribution, label & creator monetization | YouTube captions (`yt-dlp`) |
| **The Town with Matthew Belloni** | Matthew Belloni (Puck) | Hollywood & streaming business — studios, platforms, and the executives who run them | RSS monitor → matched to its YouTube channel → captions |
| **Trapital** | Dan Runcie | Hip-hop, music & the creator economy — label strategy, streaming, AI music, frequent exec interviews | RSS monitor → matched to its YouTube channel → captions (falls back to the site article) |

Roughly: **Decoder** and **The Town** give the platform/media-strategy layer, **Big Technology** the AI-capability/big-tech layer, and **Your Morning Coffee** + **Trapital** the music-industry/creator-monetization layer. Several of these — The Town, Trapital, Decoder — regularly land competitor executives on the mic, which is exactly what the digest is built to catch.

*Staged for later (configured but disabled):* **硅谷101** (Chinese tech/VC).

## Tech stack

- **Language:** Python
- **Feed parsing:** `feedparser`
- **HTTP:** `requests`
- **HTML parsing:** `beautifulsoup4`, `lxml`
- **Config:** `PyYAML`, `python-dotenv`
- **LLM:** Anthropic Claude (default); Volcengine Ark via OpenAI-compatible provider
- **YouTube captions:** `yt-dlp`
- **Delivery:** Feishu/Lark webhook cards + Sheets API audit log

---

## Adapting for Your Own Use

### 1. Clone and install

```bash
git clone https://github.com/CindyYiranW/podcast-digest.git
cd podcast-digest
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

> Python 3.9+ works. The repo is `.gitignore`-clean — your secrets (`.env`), virtualenv (`.venv/`), and cache (`data/cache/`) are never committed.

### 2. Configure environment variables

Secrets live in a local `.env` file (gitignored). Start from the template:

```bash
cp .env.example .env
```

Then edit `.env`:

```bash
# Which LLM provider to use: "anthropic" (default) or "ark" (Volcengine 火山方舟)
LLM_PROVIDER=anthropic

# --- provider = anthropic ---
# Get a key at https://console.anthropic.com (one key covers both models below)
ANTHROPIC_API_KEY=sk-ant-...

# --- provider = ark (only if LLM_PROVIDER=ark; requires `pip install openai`) ---
ARK_API_KEY=
# ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3   # optional override

# Models (optional — sensible defaults shown). For Ark, set your model/endpoint IDs.
LLM_SCREENING_MODEL=claude-haiku-4-5     # cheap/fast, used for screening
LLM_ANALYSIS_MODEL=claude-sonnet-4-6     # higher quality, used for analysis

# Delivery (optional): a Feishu/Lark custom-bot webhook. If unset, the digest
# only prints to the terminal.
FEISHU_WEBHOOK_URL=https://open.larkoffice.com/open-apis/bot/v2/hook/...

# Audit logging (optional): append every processed episode to a Feishu sheet.
# Needs a Feishu/Lark self-built app (App ID/Secret) with Sheets read/write,
# added as an editor on the target spreadsheet. Off unless ENABLED=true.
FEISHU_SHEET_ENABLED=false
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_SHEET_SPREADSHEET_TOKEN=        # the <token> in /sheets/<token>
FEISHU_SHEET_SHEET_ID=                 # the tab id (?sheet=<id>, or the first tab)
# FEISHU_API_BASE=https://open.larksuite.com   # only if your app is on Lark international
```

Switching to Ark later is just a config change — set `LLM_PROVIDER=ark`, fill `ARK_API_KEY`, and point the model variables at your Ark model/endpoint IDs. No business-logic code changes.

### 3. Add your own podcast sources

Sources are declared in `config/sources.yaml`. The pipeline supports **standard RSS feeds, show-notes-only sources, website/article enrichment, YouTube channel RSS with caption extraction, and matching a podcast to its YouTube channel to pull a transcript** — selected per source via `content_strategy`. Optionally set `screening: keyword` to use the no-LLM keyword path (see *Two ways to screen* above); omit it to use Claude.

```yaml
window_days: 14        # only process episodes published in the last N days

sources:
  # (a) Standard RSS, show notes only, screened by Claude (the default)
  - name: "Some Podcast"
    lang: "en"
    enabled: true
    rss: "https://example.com/feed.xml"
    content_strategy: "show_notes"

  # (b) RSS + scrape the full article/transcript from a website
  #     - theverge_scrape: match episode title on a Verge index page → article body
  #     - website_scrape:  e.g. Substack post → auto-generated transcript
  - name: "Decoder with Nilay Patel"
    lang: "en"
    enabled: true
    rss: "https://feeds.megaphone.fm/recodedecode"
    base_url: "https://www.theverge.com/decoder-with-nilay-patel"
    content_strategy: "theverge_scrape"

  - name: "Big Technology"
    lang: "en"
    enabled: true
    rss: "https://www.bigtechnology.com/feed"
    base_url: "https://www.bigtechnology.com"
    content_strategy: "website_scrape"

  # (c) RSS feed that publishes a <podcast:transcript> tag → read it directly
  - name: "Some Show With Transcripts"
    lang: "en"
    enabled: true
    rss: "https://example.com/feed.xml"
    content_strategy: "rss_transcript_tag"

  # (d) YouTube channel RSS as the monitor + yt-dlp caption extraction.
  #     Pair with screening: keyword when the show notes are clean enough.
  - name: "Your Morning Coffee"
    lang: "en"
    enabled: true
    content_strategy: "youtube_channel_rss"
    screening: "keyword"
    youtube_channel_id: "UC7Wp25QkW7B6uBjSldHDc2g"
    youtube_rss_url: "https://www.youtube.com/feeds/videos.xml?channel_id=UC7Wp25QkW7B6uBjSldHDc2g"

  # (e) Podcast RSS as the monitor, but pull the transcript from the show's
  #     YouTube channel by matching the episode title (best when the channel
  #     mixes full episodes with clips). Falls back to base_url, then show notes.
  - name: "The Town with Matthew Belloni"
    lang: "en"
    enabled: true
    rss: "https://feeds.megaphone.fm/the-town-with-matthew-belloni"
    content_strategy: "youtube_match_captions"
    youtube_channel_id: "UCnnIvsEv9cSQxp8LWyVhcew"
    youtube_channel_url: "https://www.youtube.com/@TheTownPodcast"
```

Notes:
- **`enabled: false`** keeps a source configured but skipped.
- Enrichment runs **only for episodes that pass screening**, so you never pay to fetch or analyze low-signal content. Any enrichment failure (no transcript, scrape error) **falls back to show notes** rather than crashing.

### 4. Customize relevance filters

`config/filters.yaml` defines what "relevant" means for your team. It is injected into the screening prompt (and powers keyword screening). Edit these sections:

- **`identity` / `scope`** — who the team is and the lens to judge by (e.g. "a strategy head at a major video platform").
- **`relevant_topics`** — themes you care about, each with weighted `keywords` and a tag.
- **`competitor_companies`** — companies whose mentions are a signal **and whose executives, as guests, trigger a priority interview** (grouped by track).
- **`guest_priority`** — the rule that promotes a competitor-executive guest to a top-priority interview, and deprioritizes host-solo / commentator episodes.
- **`analysis_framework`** — per-topic analytical questions applied during deep analysis.
- **`exclude_topics`** — what to filter out (e.g. unrelated hard tech, game-making, traditional theatrical-film business).
- **`scoring`** — the relevance threshold and scoring rules.

No code changes are needed — edit the YAML and re-run. The richer and more specific your topics/competitors, the sharper the screening.

### 5. Run it

```bash
# Full pipeline: collect → screen → enrich → analyze → print (+ Feishu push if configured)
python -m src.main
```

You can also exercise individual stages while iterating:

```bash
python -m src.fetch.rss_fetcher              # test RSS collection (no key needed)
python -m src.parse.shownotes_parser         # test HTML→text cleaning (no key needed)
python -m src.fetch.youtube_captions_fetcher # test yt-dlp captions + VTT cleaning
python -m src.llm.screening                  # test relevance screening
python -m src.output.feishu_webhook          # send a test card to your Feishu group
python -m src.integrations.feishu_sheet      # preview the 12-column row mapping (offline)
```

### 6. Automate (optional)

Run `python -m src.main` on a schedule (cron or GitHub Actions, weekly/bi-weekly) to deliver the digest hands-off. When running in a hosted CI environment, note that YouTube caption extraction may require additional auth (cookies / PO-token) because datacenter IPs are often rate-limited by YouTube.

### Audit logging (optional)

Every run can append **all** processed episodes — Relevant, Irrelevant, and Skipped — to a Feishu/Lark spreadsheet, so nothing you spent compute on is ever lost. Each row records the podcast, title, published date, relevance status + score, skip reason, link, transcript source, one-line summary, and a per-run id/timestamp. It's append-only and **batched into a single API call**; any failure is logged and never blocks the run.

To enable it:

1. Create a **Feishu/Lark self-built app**, give it **Sheets (电子表格) read/write** permission, and **publish/release** it.
2. **Add that app as an editor** on your target spreadsheet (open the sheet → Share → add the app).
3. Fill `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_SHEET_SPREADSHEET_TOKEN`, and `FEISHU_SHEET_SHEET_ID` in `.env`, and set `FEISHU_SHEET_ENABLED=true`. (On Lark international, also set `FEISHU_API_BASE=https://open.larksuite.com`.)

The sheet's first row should hold your headers — the pipeline only appends data rows below them.

---

## Project structure

```
config/
  sources.yaml     # podcast sources (content strategy + screening mode)
  filters.yaml     # relevance topics, competitors, frameworks, scoring
src/
  fetch/           # RSS, website/transcript enrichment, YouTube RSS + captions
  parse/           # show-notes / HTML cleaning
  filters/         # keyword screening (no-LLM path)
  llm/             # provider abstraction, screening (+ guest priority), analysis
  output/          # Feishu webhook delivery (two-section digest cards)
  integrations/    # Feishu Sheet audit logging (all processed episodes)
  prompts/         # editable screening & analysis prompt templates
  main.py          # pipeline entry point
data/cache/        # dedup + downloaded captions (gitignored)
```
