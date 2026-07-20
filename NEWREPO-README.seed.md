# Google Meet AI Agent

Automated meeting assistant for **Google Meet**: it captures finished meetings, transcribes
them into speaker-labeled text, and uses an LLM to produce a summary, action items, and
analysis — then archives the result, exposes it in a web UI, and (optionally) syncs to Notion.

> **New here? Read [`GOOGLE-MEET-AGENT-HANDOFF.md`](./GOOGLE-MEET-AGENT-HANDOFF.md) first.**
> It is the full build brief (schema, ported STT/agent code, the capture-option decision, and
> build order), distilled from a working Microsoft Teams sibling project.

## Architecture (a pipeline over one JSON-per-meeting contract)

```
Stage 0  CAPTURE   Google Meet REST API (post-meeting)  → writes {meetingId}.json + audio artifact
Stage 1  STT       transcribe audio                     → fills segments[]   (skippable if using Google's own transcript)
Stage 2  AGENT     LLM analysis                         → fills summary / actionItems / analysis
Stage 3  ARCHIVE   DB + object storage + search index
Stage 4  UI        meeting list + detail + search
Stage 5  NOTION    idempotent sync (page per meeting, row per action item)
```

Every stage reads/writes the **same JSON object per meeting** (see the schema in the handoff,
`shared/schema.py`). Stages are idempotent and keyed on `meetingId`, so each can be built and
re-run independently.

## ⚠️ First decision: how to capture Meet audio

Google Meet has **no** Teams-style raw-media recording bot. Pick one (details in the handoff §3):

- **Option A — Google Meet REST API (recommended):** post-meeting recordings/transcripts.
  Requires **Google Workspace** with recording/transcription enabled. Lowest risk.
- **Option B — Meet Media API:** real-time streams (developer preview).
- **Option C — headless-browser bot:** joins as a participant (works on consumer Gmail; fragile).

**Confirm the customer's Google Workspace edition + recording settings before building capture —
it decides whether Option A is even available.**

## Quick start (dev)

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt      # or: pip install -e .
cp .env.example .env                 # fill in your keys
```

Run the pipeline on one meeting once capture has produced a `{meetingId}` folder:

```bash
python -m stt.transcribe <meetingId>     # or --all
python -m agent.analyze   <meetingId>     # or --all
```

## Repo layout

See the handoff §9 for the full tree. Top level:
`shared/` (schema + config + store) · `capture/` (Meet-specific) · `stt/` · `agent/` ·
`archive/` · `api/` · `web/` · `notion/`.

## Configuration

All configuration is via environment variables — see [`.env.example`](./.env.example).

## Build order

1. Freeze the schema (`shared/schema.py`).
2. Capture Option A happy path (one real meeting → valid `{meetingId}.json`).
3. STT (or Google-transcript importer).
4. Agent (summary → action items → analysis).
5. Archive + search, then web UI.
6. Notion sync.

Get 1–4 working on one real meeting before building the rest.
