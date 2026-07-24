# Google Meet AI Agent

Automated meeting assistant for **Google Meet**. It captures finished meetings, transcribes
them into speaker-labeled text, and uses an LLM to produce a summary, action items, and
analysis — writing everything into one JSON file per meeting.

The whole transcription stack is **open-source and self-hosted** ([faster-whisper]) — no paid
speech API. The only external paid dependency is the LLM (OpenAI, or any OpenAI-compatible
provider), and audio capture via the Google Meet REST API.

> New to the codebase? Read [`GOOGLE-MEET-AGENT-HANDOFF.md`](./GOOGLE-MEET-AGENT-HANDOFF.md) —
> the full design brief (schema, capture-option decision, build order). Note its two
> "Full reference source" blocks are archival Azure code; the live stack is described below.

---

## Architecture

A pipeline over a single **JSON-per-meeting** contract (`shared/schema.py`). Every stage reads
and writes the same `{meetingId}.json`, is idempotent, and keyed on `meetingId`, so stages run
and re-run independently.

```
Stage 0  CAPTURE   Google Meet REST API   → writes {meetingId}.json (+ imports Google transcript)   ✅ implemented
Stage 1  STT       faster-whisper         → fills segments[]  (skipped if Google transcript present) ✅ implemented
Stage 2  AGENT     OpenAI LLM             → fills summary / actionItems / analysis                    ✅ implemented
Stage 3+ ARCHIVE / UI / NOTION            → downstream consumers                                       🔜 planned
```

Talk-time per speaker is computed **locally** from segment durations — never by the LLM.

---

## Requirements

- **Python 3.10+**
- **A Google Workspace** with Meet recording/transcription enabled (for capture — see below)
- **An OpenAI API key** (or an OpenAI-compatible endpoint) for the analysis stage
- **(Optional) An NVIDIA GPU** to accelerate transcription. CPU works but is slower.

---

## Setup

```powershell
python -m venv gma_venv
.\gma_venv\Scripts\Activate.ps1          # macOS/Linux: source gma_venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                   # then fill in .env
```

Install the STT engine (kept out of the base install so the pipeline runs without it):

```powershell
pip install faster-whisper
```

### Configuration

All config is environment variables, read from `.env` by `shared/config.py`. **Secrets live only
in `.env`, which is git-ignored and never committed.** `config.py` contains only field names and
non-secret defaults.

| Variable | Default | Purpose |
|---|---|---|
| `RECORDINGS_ROOT` | `./recordings` | Where `{meetingId}/` folders are read/written |
| **Capture (Google)** | | |
| `GOOGLE_APPLICATION_CREDENTIALS` | — | Path to service-account JSON |
| `GOOGLE_IMPERSONATE_SUBJECT` | — | Workspace user to impersonate (domain-wide delegation) |
| `CAPTURE_TRIGGER` | `poll` | `poll` or `pubsub` |
| `USE_GOOGLE_TRANSCRIPT` | `true` | Prefer Google's own transcript; skips STT when available |
| **STT (faster-whisper)** | | |
| `STT_LANGUAGE` | `auto` | BCP-47 tag (`ru-RU`) or `auto` to detect per file |
| `WHISPER_MODEL` | `large-v3` | Base multilingual model (strong ru/en, decent kk) |
| `WHISPER_KK_MODEL` | — | Optional Kazakh specialist, e.g. `abilmansplus/whisper-turbo-ksc2` |
| `WHISPER_DEVICE` | `auto` | `auto` \| `cpu` \| `cuda` |
| `WHISPER_COMPUTE_TYPE` | `auto` | `auto` \| `int8` \| `float16` \| `int8_float16` |
| `HF_TOKEN` | — | HuggingFace token — only for pyannote diarization (mixed-WAV path) |
| **Agent (LLM)** | | |
| `OPENAI_API_KEY` | — | OpenAI (or compatible) API key |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model name |
| `OPENAI_BASE_URL` | — | Set to point at a compatible provider (e.g. DeepSeek); empty = OpenAI |
| `AGENT_OUTPUT_LANGUAGE` | `ru` | Language of generated summary/action-items/analysis |

---

## Usage

Once capture has produced a `{recordings_root}/{meetingId}/` folder:

```powershell
python -m capture.run                    # Stage 0: poll Meet, save new meetings
python -m stt.transcribe <meetingId>     # Stage 1: transcribe (or --all)
python -m agent.analyze  <meetingId>     # Stage 2: summarize (or --all)
```

`--all` processes every meeting missing that stage's output. Both STT and agent are idempotent —
re-running skips meetings already done.

---

## Speech-to-text details

`stt/transcribe.py` orchestrates; `stt/whisper_backend.py` does the work via [faster-whisper].

**Two input modes** (auto-detected per meeting folder):
- **Per-speaker WAVs** (`{personId}.wav`) — each transcribed alone and attributed to that person.
  No diarization needed. *Preferred* — platform attribution beats acoustic diarization.
- **Single mixed WAV** (`{meetingId}.wav`) — needs diarization to label speakers (see below).

**Trilingual (ru / kk / en):** `large-v3` handles all three, code-switching included. For weak
Kazakh, set `WHISPER_KK_MODEL` — Kazakh-detected audio then routes to that specialist while ru/en
stay on `large-v3` (a Kazakh-only fine-tune can regress on other languages, so it's never the base).

### GPU

Set `WHISPER_DEVICE=cuda`. Requires an NVIDIA GPU and the CUDA 12 runtime libs:

```powershell
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

Pick `WHISPER_COMPUTE_TYPE` by VRAM: `float16` (~5 GB, best) on ≥6 GB cards; `int8_float16`
(~3 GB) or `int8` (~2 GB) on smaller cards. `large-v3-turbo` is a smaller/faster alternative model
for tight VRAM.

### Diarization (mixed-WAV path only)

Speaker labels on a single combined WAV use [WhisperX] + [pyannote]:

1. `pip install whisperx` (large — pulls in PyTorch)
2. Accept the terms on `pyannote/speaker-diarization-3.1` and `pyannote/segmentation-3.0` on
   HuggingFace, create a `read` token, set `HF_TOKEN`.

Without `HF_TOKEN`, the mixed path still transcribes but labels every segment `Unknown`. The
per-speaker path needs none of this.

---

## Analysis details

`agent/analyze.py` sends the transcript to an OpenAI-compatible chat model and expects a strict
JSON object (summary, action items with owner/due/provenance, topics/decisions/sentiment/follow-ups).
`OPENAI_BASE_URL` lets the same code target any compatible provider without changes.

---

## Project layout

```
shared/     schema.py (frozen JSON contract) · config.py (env settings) · store.py (JSON drop-box)
capture/    Stage 0 — Google Meet REST source, auth, poll runner
stt/        Stage 1 — transcribe.py (orchestration) + whisper_backend.py (faster-whisper)
agent/      Stage 2 — analyze.py (LLM summary / action items / analysis)
```

---

## Testing

Self-contained smoketests (no live Google/OpenAI, no audio) — each prints `PASS`/`FAIL`:

```powershell
python -m stt._transcribe_smoketest      # STT orchestration (skip/no-audio paths)
python -m agent._analyze_smoketest       # LLM mapping + idempotency (fake client)
python -m _pipeline_e2e_smoketest        # capture → STT(skip) → agent, end to end
```

---

## Security

- Real secrets go **only** in `.env` (git-ignored, per `.gitignore`). `config.py` holds no secrets.
- `recordings/` (meeting audio + transcripts) and `secrets/` are git-ignored — private data stays local.

[faster-whisper]: https://github.com/SYSTRAN/faster-whisper
[WhisperX]: https://github.com/m-bain/whisperX
[pyannote]: https://github.com/pyannote/pyannote-audio
