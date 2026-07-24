# Google Meet AI Agent — Project Handoff & Build Brief

> **Purpose of this file.** This is a self-contained brief for building a **Google Meet**
> meeting-AI-agent in **Python**, in a currently-empty repository. It is distilled from a
> working sibling project that did the same thing for **Microsoft Teams**. Read it end to
> end, then scaffold the base project described in §9–§11.
>
> **You (Claude, in the new repo) should:** treat §4 (transcript schema) and §5 (pipeline
> contract) as *fixed carry-overs*, treat §6 (STT worker) and §7 (analysis agent) as *code
> you can port nearly verbatim*, and treat §3 + §8 (Google Meet audio ingestion) as *the one
> part that must be redesigned*, because Google Meet's model differs fundamentally from Teams.
> Before writing ingestion code, surface the §3 decision to the human — it changes everything
> downstream of the audio bytes and has real cost/eligibility implications.

---

## 1. What we're building (the whole system, platform-independent)

An automated meeting assistant. When a covered meeting happens, the system:

1. **Captures** the meeting audio (+ who was present, when, meeting metadata).
2. **Transcribes** it into speaker-labeled, timestamped text.
3. **Analyzes** it with an LLM → summary, action items, and analysis (topics, decisions,
   sentiment, follow-ups, talk-time).
4. **Stores / surfaces** it: an archive + search, a web UI, and (optionally) a Notion sync.

The original manager requirements (Russian, verbatim) and their component mapping:

| Requirement (RU) | Component | Stage |
|---|---|---|
| ИИ-агент для анализа встреч с веб-интерфейсом | Agent service + Web UI | 4, 5 |
| Автоматическая транскрибация встреч и звонков | Capture → STT | 1, 2 |
| Автоматическое саммари каждой встречи | Agent (summary) | 3 |
| Выделение action items и задач | Agent (extraction) | 3 |
| Анализ встреч | Agent (analysis) | 3 |
| Опциональная интеграция (Teams surface) | *(N/A here — this is the Meet variant)* | — |
| Архив встреч и поиск | Storage + search index | — |
| Внедрение в инфраструктуру Заказчика (Notion) | Notion sync worker | — |

The crucial design principle carried over from the Teams build: **the capture stage only
produces `audio + metadata JSON`; everything downstream consumes a frozen JSON schema (§4).**
That decoupling let the STT/agent/UI/Notion teams work in parallel without waiting on the
hard capture piece. Keep that seam.

---

## 2. How the Teams version worked (context — so you understand the shape you're porting)

The Teams build had three deployable pieces communicating only through files on disk:

```
[C# Teams media bot]  →  writes  C:\Recordings\{callId}\{callId}.wav  +  {callId}.json
        │                          (16 kHz / 16-bit / mono PCM WAV)   (MeetingTranscript, segments[] EMPTY)
        ▼
[stt-worker  (Python)]  →  fills segments[] in {callId}.json          (Azure AI Speech)
        │
        ▼
[agent       (Python)]  →  fills summary / actionItems / analysis     (Azure OpenAI)
        │
        ▼
[archive / search / web UI / Notion]  →  consume the finished {callId}.json
```

> **Current Meet stack (Azure dropped for cost):** STT is now **`faster-whisper`**
> (self-hosted, free) in `stt/whisper_backend.py`; the analysis agent uses **OpenAI**
> (or any OpenAI-compatible endpoint) in `agent/analyze.py`. The diagram above shows the
> original Teams origin; the two "Full reference source" blocks below are archival.

- The **bot** was the only Teams-specific, hard, Windows-only, always-on piece. It used
  Microsoft Graph Communications + the Skype media SDK to receive raw PCM frames (50/sec,
  20 ms each) via a **compliance recording policy** — an admin assigned a policy once and
  every covered user's meetings auto-invited the bot. No user ever pressed "record."
- The **stt-worker** and **agent** are Python, run post-call, and are *completely
  platform-agnostic*: they only know the WAV format and the JSON schema. **These port to
  Google Meet unchanged** (see §6, §7 — full source included).

**The single thing that does not carry over is the capture mechanism.** Google Meet has no
Teams-style "compliance recording policy + raw-media bot" model. §3 covers your options.

---

## 3. ⚠️ The one big difference: capturing audio from Google Meet

Google Meet gives you **three fundamentally different** ways to get meeting audio/transcript.
Pick one *before* building — they have very different cost, latency, eligibility, and
engineering profiles. **Raise this decision with the human first.**

### Option A — Google Meet REST API (post-meeting artifacts) ✅ recommended first
Google Workspace's **Google Meet API** exposes, *after a meeting ends*, `conferenceRecords`
and their child **`recordings`** (the video/audio file, landed in the organizer's Google
Drive) and **`transcripts`** / **`transcripts.entries`** (Google's own speaker-labeled
transcript, if transcription was on).

- **Pros:** No real-time media plumbing. No always-on bot. No browser automation. Google
  already did diarization + STT for you if transcripts are enabled — you may be able to
  **skip our §6 STT stage entirely** and feed Google's transcript straight into the §7 agent.
- **Cons:** Requires **Google Workspace** (not consumer Gmail) with **recording and/or
  transcription enabled** (Business Standard+/Enterprise editions). Post-meeting only — no
  live captions. You need OAuth with the right scopes and Drive access to fetch the recording.
- **Key APIs / scopes:** `meet.googleapis.com` (`ConferenceRecords`, `Recordings`,
  `Transcripts`, `Transcripts.Entries`); scopes like
  `https://www.googleapis.com/auth/meetings.space.readonly` (or `.created`) and Drive scopes
  to download the recording file. Use a **service account with domain-wide delegation** for
  an org-wide, no-user-interaction deployment (the equivalent of the Teams "policy" model).
- **Trigger:** poll the Meet API for new `conferenceRecords`, **or** subscribe to Google
  Workspace Events / Pub/Sub push notifications for conference-record / recording / transcript
  "created" events, then run the pipeline.

> **This is the closest Google analog to the Teams compliance-recording model** and the
> lowest-risk first target. Start here unless the customer needs live/real-time results or
> can't enable Workspace recording.

### Option B — Google Meet **Media API** (real-time streams, developer preview)
A newer API that lets a backend client **join a meeting and receive real-time audio/video
streams** (WebRTC-based). This is the true analog of the Teams raw-media bot.

- **Pros:** Real-time audio → enables live captions and lowest-latency processing. Closest
  1:1 with what the Teams bot did (feed PCM into §6 STT as it arrives).
- **Cons:** **Developer preview** — availability, quotas, and API surface can change; may
  require allow-listing. Significantly more engineering (WebRTC, an always-on reachable
  client, per-meeting session state) — same operational burden the Teams bot had
  (must run 24/7, stateful, media ports). C++/reference clients exist; a Python path is
  thinner.
- **Use when:** live results are a hard requirement, or Workspace recording can't be enabled.

### Option C — "Meeting bot" via browser automation (headless Chrome)
Spin up a headless Chromium (Playwright/Puppeteer) that **joins the meeting as a participant**
using the join URL, and capture the tab's audio (virtual audio device / `getUserMedia` tap /
screen+audio recording). This is how third-party vendors (Recall.ai, Otter-style bots) do it
across *all* platforms.

- **Pros:** Works on consumer Google Meet too (no Workspace edition requirement). Platform-
  agnostic — same bot could later handle Zoom/Teams. Full control over raw audio.
- **Cons:** Fragile (UI changes break it), needs a "bot joined the meeting" participant
  (visible to attendees, consent implications), heavy infra (a browser per concurrent
  meeting), and you must handle join links / waiting rooms / admission. Speaker attribution
  is harder (you get mixed tab audio unless you scrape the on-screen active-speaker UI).
- **Use when:** you must support non-Workspace meetings or want one bot across platforms, and
  you accept the fragility/consent trade-offs.

### Recommendation
**Build against Option A first** (post-meeting Meet REST API). It de-risks the hardest part,
reuses Google's own transcription, and matches the "admin enables it once, no per-meeting
action" model the customer already accepted for Teams. Keep the capture stage behind a small
interface so you can add Option B/C later without touching §6/§7. **Confirm with the human
which Workspace edition + recording/transcription settings the customer has** — that single
fact decides whether Option A is even available.

### Consent / legal note (carries over, stricter here)
Meeting recording is personal data. For Option C especially, a bot silently joining a call
raises consent/notification requirements. Whatever option you pick: notify participants,
set a retention policy, document processing. (The Teams build targeted a specific region for
data-residency compliance — confirm the equivalent requirement with the customer.)

---

## 4. The transcript schema — the frozen cross-stage contract (CARRY OVER VERBATIM)

Every stage after capture reads and writes this one JSON object, one file per meeting. This
is the most important thing to preserve from the Teams build. **Freeze it before writing any
consumer** — changing it later breaks STT, agent, archive, search, UI, and Notion at once.

```jsonc
{
  "meetingId": "uuid",                     // Meet: conferenceRecord name / space id
  "tenantId": "...",                       // Google: Workspace customer id (or null)
  "joinUrl": "https://meet.google.com/xxx-xxxx-xxx",
  "subject": "Weekly Sync",                // Meet may not provide; may be null
  "organizer": { "name": "...", "aadObjectId": "..." },   // rename aadObjectId → a neutral "id" for Google (see note)
  "startedAt": "2026-06-28T09:00:00Z",
  "endedAt":   "2026-06-28T09:42:00Z",
  "participants": [
    { "name": "...", "aadObjectId": "...", "joinedAt": "...", "leftAt": "..." }
  ],
  "segments": [                            // EMPTY from capture; filled by STT (§6) or Google transcript
    {
      "speaker": { "name": "...", "aadObjectId": "..." },
      "startMs": 12340,
      "endMs": 15880,
      "text": "..."
    }
  ],
  "language": "ru",
  "audioArtifactUri": "https://.../meetingId.wav",   // or gs:// / Drive file id

  // ---- filled by the analysis agent (§7): ----
  "summary":    { "tldr": "...", "narrative": "..." },
  "actionItems":[ { "title": "...", "owner": "Name|null", "due": "YYYY-MM-DD|null", "sourceStartMs": 12340 } ],
  "analysis":   { "topics": [], "decisions": [], "sentiment": "...", "followUps": [],
                  "talkTimeSeconds": { "Name": 42.0 } }
}
```

**Naming note for the port:** the Teams schema used `aadObjectId` (Azure AD object id) as the
stable per-person key. For Google, the natural equivalent is the Google **`people`/directory
user id** or the participant's `signedinUser.user` resource name. Recommend renaming
`aadObjectId` → a neutral **`id`** (or `personId`) throughout the new codebase so it isn't
Azure-flavored. Whatever you choose, keep it a single stable id field with the same role.

Rules that must hold:
- Capture fills **everything except** `segments`, `summary`, `actionItems`, `analysis`.
- STT (or Google's transcript import) fills `segments[]`, sorted by `startMs`.
- The agent fills `summary` / `actionItems` / `analysis`.
- Persist the **roster with real names** at capture time — "who said what" is the difference
  between a useful summary and a useless one. Don't leave speakers as raw ids.

---

## 5. The pipeline contract (stage boundaries)

```
Stage 0  CAPTURE   (Google-Meet-specific, §3)  → writes {meetingId}.json (no segments) + audio artifact
Stage 1  STT       (§6, port from Teams)        → fills segments[]   (SKIP if using Google's own transcript)
Stage 2  AGENT     (§7, port from Teams)        → fills summary / actionItems / analysis
Stage 3  ARCHIVE   → meeting record → DB; audio → object storage; index for search
Stage 4  UI        → meeting list + detail (summary, action items, transcript w/ speaker labels, analysis)
Stage 5  NOTION    → one page per meeting + one row per action item (idempotent on meetingId)
```

Each stage is idempotent and re-runnable, keyed on `meetingId`, triggered by "previous stage
produced its fields." A finished-artifact directory (mirroring the Teams layout) works fine as
the v1 message bus:

```
{RECORDINGS_ROOT}/{meetingId}/
    {meetingId}.<wav|mp4>      ← audio/recording artifact
    {meetingId}.json           ← the schema object above, progressively filled
    {personId}.wav             ← OPTIONAL per-speaker streams (enables clean attribution, see §6)
```

Later you can swap the disk drop-box for Pub/Sub + a database without changing stage code.

---

## 6. STT worker — IMPLEMENTED with faster-whisper (Azure dropped)

> **Status:** the Teams build used **Azure AI Speech**, but it was **removed for cost**.
> The live implementation is `stt/transcribe.py` + `stt/whisper_backend.py` using
> **`faster-whisper`** — open-source, self-hosted, free. The reference block below is the
> original Teams Azure worker, kept for historical context only.

The worker interface is unchanged from the Teams design: it reads a meeting folder, transcribes
the WAV(s), and writes `segments[]` back into the JSON — so everything downstream is unaffected.

Two decisions for the Meet port:

1. **If you use Option A (Google transcripts):** you may not need this stage at all — instead
   write a tiny importer that maps Google's `transcripts.entries` (which already have speaker +
   start/end times) into our `segments[]` shape. Much cheaper and simpler than re-transcribing.
2. **STT engine (decided):** **`faster-whisper`** with `WHISPER_MODEL=large-v3` as the base
   multilingual model — strong ru/en, decent kk for trilingual meetings. Set `WHISPER_KK_MODEL`
   (e.g. `abilmansplus/whisper-turbo-ksc2`, MIT-licensed) to route Kazakh-detected audio to a
   specialist. The mixed-WAV path adds **WhisperX + pyannote** diarization when `HF_TOKEN` is set.
   The *interface* (WAV in → `segments[]` out) is identical to the Azure version it replaced.

Key behaviors to preserve when porting:
- Auto-detect **two input modes**: per-speaker WAVs (`{personId}.wav`, clean attribution, no
  diarization needed) vs. a single mixed WAV (needs diarization → generic `Guest-1/2` ids).
  Prefer per-speaker streams — platform attribution beats acoustic diarization.
- Expect **16 kHz / 16-bit / mono PCM**; resample at the worker if your capture differs.
- Write `segments[]` sorted by `startMs`; set `language`.
- `--all` mode: process every meeting folder that has no `segments[]` yet.

<details>
<summary><b>Full reference source — Teams <code>stt-worker/transcribe.py</code> (Azure AI Speech)</b></summary>

> ⚠️ **Historical / archival.** This is the *original* Teams Azure worker. The live Meet
> implementation replaced it with faster-whisper — see `stt/whisper_backend.py`. Do not treat
> the code below as current.

```python
"""
Post-call STT worker for the Meeting AI Agent.

Reads a finalized call recording from the recordings root (default
C:\\Recordings\\{callId}\\), runs Azure AI Speech on it, and writes the
transcript ``segments[]`` back into ``{callId}.json`` -- the MeetingTranscript
schema the capture stage produces.

Two input modes, auto-detected per call folder:
  * Per-speaker WAVs (unmixed capture): one WAV per participant named
    ``{personId}.wav``. Each transcribed alone, labeled with that person's real
    name (looked up from participants[]). No diarization needed.
  * Single mixed WAV (``{callId}.wav``): transcribed with ConversationTranscriber,
    which diarizes into generic speaker ids (Guest-1, Guest-2, ...).

Config via environment variables:
    SPEECH_KEY       (required)  Azure Speech resource key
    SPEECH_REGION    (required)  e.g. uaenorth, westeurope
    STT_LANGUAGE     (optional)  BCP-47 tag, default "ru-RU". "auto" to detect.
    STT_LANGUAGE_CANDIDATES      comma list for auto mode, default "ru-RU,en-US"
    RECORDINGS_ROOT  (optional)  default "C:\\Recordings"

Usage:
    python transcribe.py <callId>      # one call
    python transcribe.py --all         # every call folder missing segments
"""

import json
import os
import sys
import threading
import time
from pathlib import Path

import azure.cognitiveservices.speech as speechsdk

RECORDINGS_ROOT = Path(os.environ.get("RECORDINGS_ROOT", r"C:\Recordings"))
TICKS_PER_MS = 10_000  # Azure SDK offsets/durations are in 100-ns ticks


def _speech_config():
    key = os.environ.get("SPEECH_KEY")
    region = os.environ.get("SPEECH_REGION")
    if not key or not region:
        sys.exit("ERROR: set SPEECH_KEY and SPEECH_REGION environment variables.")
    cfg = speechsdk.SpeechConfig(subscription=key, region=region)
    cfg.request_word_level_timestamps()
    lang = os.environ.get("STT_LANGUAGE", "ru-RU")
    if lang.lower() != "auto":
        cfg.speech_recognition_language = lang
    return cfg


def _auto_detect_config():
    if os.environ.get("STT_LANGUAGE", "ru-RU").lower() != "auto":
        return None
    cands = os.environ.get("STT_LANGUAGE_CANDIDATES", "ru-RU,en-US").split(",")
    cands = [c.strip() for c in cands if c.strip()]
    return speechsdk.languageconfig.AutoDetectSourceLanguageConfig(languages=cands)


def _run_continuous(recognizer, collect):
    """Drive a recognizer/transcriber to completion, invoking collect(evt)."""
    done = threading.Event()

    def _stop(_evt):
        done.set()

    # ConversationTranscriber raises .transcribed; SpeechRecognizer raises .recognized.
    if hasattr(recognizer, "transcribed"):
        recognizer.transcribed.connect(collect)
        recognizer.session_stopped.connect(_stop)
        recognizer.canceled.connect(_stop)
        recognizer.start_transcribing_async().get()
        done.wait()
        recognizer.stop_transcribing_async().get()
    else:
        recognizer.recognized.connect(collect)
        recognizer.session_stopped.connect(_stop)
        recognizer.canceled.connect(_stop)
        recognizer.start_continuous_recognition_async().get()
        done.wait()
        recognizer.stop_continuous_recognition_async().get()


def _segment(text, offset_ticks, duration_ticks, name, person_id):
    return {
        "speaker": {"name": name, "aadObjectId": person_id},
        "startMs": int(offset_ticks // TICKS_PER_MS),
        "endMs": int((offset_ticks + duration_ticks) // TICKS_PER_MS),
        "text": text,
    }


def transcribe_mixed(wav_path):
    """Diarize + transcribe a single mixed WAV. Speakers are generic ids."""
    cfg = _speech_config()
    audio = speechsdk.audio.AudioConfig(filename=str(wav_path))
    auto = _auto_detect_config()
    if auto is not None:
        transcriber = speechsdk.transcription.ConversationTranscriber(
            speech_config=cfg, audio_config=audio, auto_detect_source_language_config=auto)
    else:
        transcriber = speechsdk.transcription.ConversationTranscriber(
            speech_config=cfg, audio_config=audio)

    segments = []

    def collect(evt):
        r = evt.result
        if r.reason == speechsdk.ResultReason.RecognizedSpeech and r.text:
            speaker = getattr(r, "speaker_id", None) or "Unknown"
            segments.append(_segment(r.text, r.offset, r.duration, speaker, None))

    _run_continuous(transcriber, collect)
    return segments


def transcribe_one_speaker(wav_path, name, person_id):
    """Transcribe a single-speaker WAV; every segment attributed to that speaker."""
    cfg = _speech_config()
    audio = speechsdk.audio.AudioConfig(filename=str(wav_path))
    auto = _auto_detect_config()
    if auto is not None:
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=cfg, audio_config=audio, auto_detect_source_language_config=auto)
    else:
        recognizer = speechsdk.SpeechRecognizer(speech_config=cfg, audio_config=audio)

    segments = []

    def collect(evt):
        r = evt.result
        if r.reason == speechsdk.ResultReason.RecognizedSpeech and r.text:
            segments.append(_segment(r.text, r.offset, r.duration, name, person_id))

    _run_continuous(recognizer, collect)
    return segments


def process_call(call_dir):
    call_id = call_dir.name
    json_path = call_dir / f"{call_id}.json"
    if not json_path.exists():
        print(f"[{call_id}] SKIP: no {call_id}.json")
        return

    record = json.loads(json_path.read_text(encoding="utf-8"))
    participants = {p.get("aadObjectId"): p.get("name") for p in record.get("participants", [])}

    # Per-speaker WAVs = any *.wav whose stem is not the callId (the mixed file).
    per_speaker = [w for w in call_dir.glob("*.wav") if w.stem != call_id]
    mixed = call_dir / f"{call_id}.wav"

    segments = []
    if per_speaker:
        print(f"[{call_id}] per-speaker mode: {len(per_speaker)} stream(s)")
        for wav in per_speaker:
            pid = wav.stem
            name = participants.get(pid, pid)
            print(f"  - {wav.name} -> {name}")
            segments.extend(transcribe_one_speaker(wav, name, pid))
    elif mixed.exists() and mixed.stat().st_size > 44:
        print(f"[{call_id}] mixed mode (diarized): {mixed.name} ({mixed.stat().st_size} bytes)")
        segments = transcribe_mixed(mixed)
    else:
        print(f"[{call_id}] SKIP: no audio (mixed WAV is empty/header-only)")
        return

    segments.sort(key=lambda s: s["startMs"])
    record["segments"] = segments
    if os.environ.get("STT_LANGUAGE", "ru-RU").lower() != "auto":
        record["language"] = os.environ.get("STT_LANGUAGE", "ru-RU")

    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{call_id}] wrote {len(segments)} segment(s) -> {json_path}")


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)

    if args[0] == "--all":
        if not RECORDINGS_ROOT.exists():
            sys.exit(f"ERROR: recordings root not found: {RECORDINGS_ROOT}")
        for call_dir in sorted(p for p in RECORDINGS_ROOT.iterdir() if p.is_dir()):
            record_path = call_dir / f"{call_dir.name}.json"
            if record_path.exists():
                rec = json.loads(record_path.read_text(encoding="utf-8"))
                if rec.get("segments"):
                    print(f"[{call_dir.name}] already transcribed; skipping")
                    continue
            process_call(call_dir)
    else:
        call_dir = RECORDINGS_ROOT / args[0]
        if not call_dir.is_dir():
            sys.exit(f"ERROR: call folder not found: {call_dir}")
        process_call(call_dir)


if __name__ == "__main__":
    start = time.time()
    main()
    print(f"done in {time.time() - start:.1f}s")
```

Requirements: `azure-cognitiveservices-speech>=1.40.0`
</details>

---

## 7. Analysis agent — IMPLEMENTED on OpenAI (Azure dropped)

The `agent/analyze.py` is **fully platform-independent** — it reads a transcribed
`{meetingId}.json`, calls an OpenAI-compatible LLM, and writes `summary` / `actionItems` /
`analysis` back.

> **Status:** the Teams build used **Azure OpenAI**; the live Meet build uses the **OpenAI API**
> directly (`OPENAI_API_KEY` / `OPENAI_MODEL`, default `gpt-4o-mini`). `OPENAI_BASE_URL` points the
> same client at any OpenAI-compatible provider (e.g. DeepSeek) for cheaper inference — no code
> change. The prompt + JSON-object response format is the reusable asset; only the client changed.

Preserved behaviors worth keeping:
- **Talk-time is computed locally** from segment durations (never trust the LLM for arithmetic).
- Strict JSON-object response format; `owner` must be an actual participant name or null;
  `due` is `YYYY-MM-DD` or null; `sourceStartMs` ties an action item back to a transcript
  segment (provenance for the UI and Notion).
- Output language is configurable (`AGENT_OUTPUT_LANGUAGE`, default `ru`).
- Sends the whole transcript in one call — fine for normal meetings; **chunk very long
  meetings** (known future work).

<details>
<summary><b>Full reference source — Teams <code>agent/analyze.py</code> (Azure OpenAI)</b></summary>

> ⚠️ **Historical / archival.** This is the *original* Teams Azure-OpenAI agent. The live Meet
> implementation uses the OpenAI API directly — see `agent/analyze.py`. Do not treat the code
> below as current.

```python
"""
Summary / action-items / analysis agent for the Meeting AI Agent.

Reads a transcribed call ({callId}.json with segments[] populated), calls an
OpenAI-compatible LLM, and writes `summary`, `actionItems`, and `analysis`
back into the same JSON. Talk-time is computed locally (not by the LLM).

Env vars:
    AZURE_OPENAI_ENDPOINT      e.g. https://my-aoai.openai.azure.com/
    AZURE_OPENAI_KEY           resource key
    AZURE_OPENAI_DEPLOYMENT    the model *deployment* name (e.g. gpt-4o)
    AGENT_OUTPUT_LANGUAGE      optional, default "ru"
    RECORDINGS_ROOT            optional, default "C:\\Recordings"

Usage:
    python analyze.py <callId>
    python analyze.py --all        # every call with segments[] but no summary
"""

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from openai import OpenAI

RECORDINGS_ROOT = Path(os.environ.get("RECORDINGS_ROOT", r"C:\Recordings"))
OUTPUT_LANGUAGE = os.environ.get("AGENT_OUTPUT_LANGUAGE", "ru")


def _client():
    """OpenAI client against the Azure OpenAI v1 (OpenAI-compatible) API.
    For a Google-native build, swap this for OpenAI() direct or a Vertex/Gemini client;
    the rest of the file is unchanged.
    """
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    key = os.environ.get("AZURE_OPENAI_KEY")
    if not endpoint or not key:
        sys.exit("ERROR: set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY.")
    u = urlparse(endpoint.strip())
    if not u.scheme or not u.netloc:
        sys.exit(f"ERROR: AZURE_OPENAI_ENDPOINT looks malformed: {endpoint}")
    base_url = f"{u.scheme}://{u.netloc}/openai/v1"
    return OpenAI(base_url=base_url, api_key=key)


def _fmt_ts(ms):
    s = int(ms) // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


def _build_transcript(segments):
    lines = []
    for seg in segments:
        speaker = (seg.get("speaker") or {}).get("name") or "Unknown"
        lines.append(f"[{_fmt_ts(seg.get('startMs', 0))}] {speaker}: {seg.get('text', '')}")
    return "\n".join(lines)


def _talk_time_seconds(segments):
    totals = {}
    for seg in segments:
        speaker = (seg.get("speaker") or {}).get("name") or "Unknown"
        dur = max(0, int(seg.get("endMs", 0)) - int(seg.get("startMs", 0)))
        totals[speaker] = round(totals.get(speaker, 0) + dur / 1000.0, 1)
    return totals


SYSTEM_PROMPT = (
    "You are a meeting analyst. You are given a transcript of a meeting with "
    "speaker labels and timestamps. Produce a faithful, concise analysis. "
    "Do not invent facts not supported by the transcript. "
    "Respond with a single JSON object only, no prose, matching exactly this shape:\n"
    "{\n"
    '  "summary": {"tldr": string, "narrative": string},\n'
    '  "actionItems": [{"title": string, "owner": string|null, '
    '"due": string|null, "sourceStartMs": number|null}],\n'
    '  "analysis": {"topics": [string], "decisions": [string], '
    '"sentiment": string, "followUps": [string]}\n'
    "}\n"
    "Rules: owner must be one of the participant names when identifiable, else null. "
    '"due" is an ISO date (YYYY-MM-DD) or null. "sourceStartMs" is the startMs of the '
    "segment the action item came from, or null. Write all natural-language text "
    f"(tldr, narrative, titles, topics, decisions, followUps) in language code '{OUTPUT_LANGUAGE}'."
)


def analyze_call(call_dir, client, deployment):
    call_id = call_dir.name
    json_path = call_dir / f"{call_id}.json"
    if not json_path.exists():
        print(f"[{call_id}] SKIP: no {call_id}.json")
        return

    record = json.loads(json_path.read_text(encoding="utf-8"))
    segments = record.get("segments") or []
    if not segments:
        print(f"[{call_id}] SKIP: no segments[] — run the STT worker first.")
        return

    participants = [p.get("name") for p in record.get("participants", []) if p.get("name")]
    transcript = _build_transcript(segments)

    user_prompt = (
        f"Participants: {', '.join(participants) if participants else 'unknown'}\n"
        f"Meeting subject: {record.get('subject') or 'n/a'}\n\n"
        f"Transcript:\n{transcript}"
    )

    print(f"[{call_id}] analyzing {len(segments)} segment(s) via {deployment} ...")
    resp = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    data = json.loads(resp.choices[0].message.content)

    record["summary"] = data.get("summary")
    record["actionItems"] = data.get("actionItems", [])
    analysis = data.get("analysis", {}) or {}
    analysis["talkTimeSeconds"] = _talk_time_seconds(segments)  # computed locally
    record["analysis"] = analysis

    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[{call_id}] wrote summary + {len(record['actionItems'])} action item(s) "
        f"+ analysis -> {json_path}"
    )


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)

    client = _client()
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not deployment:
        sys.exit("ERROR: set AZURE_OPENAI_DEPLOYMENT (the model deployment name).")

    if args[0] == "--all":
        if not RECORDINGS_ROOT.exists():
            sys.exit(f"ERROR: recordings root not found: {RECORDINGS_ROOT}")
        for call_dir in sorted(p for p in RECORDINGS_ROOT.iterdir() if p.is_dir()):
            jp = call_dir / f"{call_dir.name}.json"
            if not jp.exists():
                continue
            rec = json.loads(jp.read_text(encoding="utf-8"))
            if not rec.get("segments"):
                continue
            if rec.get("summary"):
                print(f"[{call_dir.name}] already analyzed; skipping")
                continue
            analyze_call(call_dir, client, deployment)
    else:
        call_dir = RECORDINGS_ROOT / args[0]
        if not call_dir.is_dir():
            sys.exit(f"ERROR: call folder not found: {call_dir}")
        analyze_call(call_dir, client, deployment)


if __name__ == "__main__":
    start = time.time()
    main()
    print(f"done in {time.time() - start:.1f}s")
```

Requirements: `openai>=1.40.0`
</details>

---

## 8. Capture stage for Google Meet — what to build (Option A blueprint)

Assuming **Option A** (post-meeting Meet REST API), the capture stage replaces the entire C#
bot with a much smaller Python service:

1. **Auth.** A Google Cloud project with the **Google Meet API** (and Drive API) enabled. For
   an org-wide, unattended deployment use a **service account with domain-wide delegation**,
   granted the Meet + Drive read scopes by a Workspace admin (this is the Google analog of the
   Teams "compliance recording policy assigned once" model). For a dev prototype, a normal
   OAuth user-consent flow is fine.
2. **Trigger.** Either **poll** `conferenceRecords.list` for records newer than your last
   checkpoint, or (better) subscribe to **Google Workspace Events / Cloud Pub/Sub** push
   notifications for conference-record / recording / transcript created events.
3. **Fetch metadata → build the schema object.** For each new `conferenceRecord`:
   - `startTime`/`endTime` → `startedAt`/`endedAt`
   - `space` join URI → `joinUrl`
   - `participants` + `participantSessions` → `participants[]` (name via People/Directory API,
     `joinedAt`/`leftAt` from sessions)
   - organizer → `organizer`
4. **Fetch the artifact.**
   - If **transcripts** are enabled: pull `transcripts.entries` and map directly into
     `segments[]` (speaker resource name → look up name; `startTime`/`endTime` → `startMs`/
     `endMs`; `text`). **This lets you skip §6 STT entirely.**
   - If only **recordings** are enabled: get the recording's Drive file, download it, and feed
     it to the §6 STT worker (transcode to 16 kHz/16-bit/mono WAV first if needed).
5. **Write** `{meetingId}/{meetingId}.json` (+ the audio artifact) to `RECORDINGS_ROOT`, then
   let §6/§7 run.

Keep this behind an interface like `CaptureSource.fetch_finished_meetings() -> list[MeetingRecord]`
so Option B (Media API real-time) or Option C (browser bot) can be dropped in later without
touching downstream stages.

**Gotchas specific to Meet capture:**
- Recording/transcription must be **enabled by a Workspace admin** and actually turned on for
  the meeting — otherwise there's no artifact to fetch. Confirm the customer's edition supports
  it.
- Recordings/transcripts land in the **organizer's Drive** and take some minutes to finalize
  after the meeting ends — your trigger must wait for the "created" event, not fire at meeting
  end.
- Consumer (`@gmail.com`) Meet is **not** covered by the Workspace Meet API — Option A needs
  Workspace. If the customer has consumer accounts, you need Option C.
- Map Google speaker identities to real names once, at capture, via the People/Directory API.

---

## 9. Recommended repo structure (Python)

```
google-meet-agent/
├── README.md
├── pyproject.toml               # or requirements per service
├── .env.example                 # all config keys documented, no secrets
├── shared/
│   ├── schema.py                # the §4 MeetingRecord as a dataclass/pydantic model + JSON (de)serialize
│   ├── store.py                 # RECORDINGS_ROOT read/write helpers (v1 disk drop-box)
│   └── config.py                # env-var loading
├── capture/                     # Stage 0 — the ONLY Google-Meet-specific piece (§3, §8)
│   ├── meet_rest_source.py      # Option A: post-meeting Meet API + Drive
│   ├── media_api_source.py      # Option B stub (real-time, dev preview) — later
│   ├── browser_bot_source.py    # Option C stub (headless Chrome) — later
│   └── run.py                   # trigger loop (poll or Pub/Sub) → writes {meetingId}.json
├── stt/
│   ├── transcribe.py            # §6 orchestration (or a Google-transcript importer)
│   └── whisper_backend.py       # §6 STT via faster-whisper (+ WhisperX diarization)
├── agent/
│   └── analyze.py               # §7 analysis via OpenAI (OpenAI-compatible client)
├── archive/                     # Stage 3 — DB + object storage + search index
├── api/                         # backend the web UI calls (FastAPI recommended)
├── web/                         # Stage 4 — web UI (see §10)
└── notion/                      # Stage 5 — idempotent Notion sync (§7 outputs → Notion)
```

Suggested stack: **FastAPI** for the API, **pydantic** for the schema model, a small DB
(Postgres/SQLite to start), object storage (GCS if Google-native) for audio, and the
**faster-whisper** STT worker (§6).

---

## 10. Downstream stages (unchanged in intent from the Teams plan)

- **Archive + search:** meeting records (schema + agent outputs) in a DB; audio in object
  storage. Index `subject`, `segments[].text`, `participants`, `summary`, `actionItems`.
  Set a **retention policy** — recordings are personal data. Add semantic/vector search on
  top of keyword for "find meetings about X."
- **Web UI:** meeting list (date, subject, participants, duration); meeting detail (summary,
  action items with provenance, full transcript with speaker labels + audio seek, analysis
  panel); cross-meeting search. Auth against Google (Workspace SSO) since users are already in
  the domain. (Teams plan suggested Vue; pick per team.)
- **Notion sync:** after the agent stage, write one **meeting page** and one **task row per
  action item** (`title`, `owner`, `due`, relation to meeting). Use a Notion internal
  integration token scoped to the target databases. Make it **idempotent on `meetingId`** so
  re-runs update rather than duplicate. Confirm target workspace/databases with the customer.

---

## 11. Suggested build order

1. **Freeze the schema** (§4) as `shared/schema.py`. Everything builds against it.
2. **Capture Option A happy path** (§8): fetch one finished Workspace meeting → write a valid
   `{meetingId}.json` + artifact. *De-risk the Google-specific part first.*
3. **Wire STT** (§6) — or, if using Google transcripts, the transcript→`segments[]` importer.
4. **Port the agent** (§7) verbatim; swap the LLM client if going Google-native. Run
   summary → action items → analysis end-to-end on one real meeting.
5. **Archive + search** (§10), then **web UI** (list + detail, then search).
6. **Notion sync** (§10).
7. Only then revisit **Option B/C** capture if live/consumer-Meet support is required.

Get steps 1–4 working on one real meeting before building anything else; downstream stages then
proceed in parallel against the frozen schema.

---

## 12. Collected gotchas (carry-over + Meet-specific)

**Carried over from the Teams build (still true):**
- **Freeze the transcript schema early** — changing it later breaks every consumer at once.
- **Persist real speaker names at capture** — "who said what" is what makes summaries useful.
- **Talk-time computed locally**, never by the LLM.
- **Idempotent, re-runnable stages keyed on meetingId** (`--all` skips already-done work).
- **Chunk very long meetings** before the LLM call (current agent sends the whole transcript).
- **Retention + consent**: recordings are personal data; set retention, document processing,
  confirm data-residency region with the customer.

**New for Google Meet:**
- **Pick the capture option (§3) before coding** — A/B/C are very different builds. Raise it
  with the human; confirm the customer's Workspace edition + recording/transcription settings.
- **Option A needs Google Workspace**, not consumer Gmail, with recording/transcription enabled.
- **Artifacts are delayed** post-meeting — trigger on "created" events, not meeting-end.
- **Service-account + domain-wide delegation** is the unattended, org-wide model (the analog of
  the Teams recording policy). Get admin to grant scopes once.
- **Media API is developer preview** — don't build the core path on it unless live is required.
- **Browser-bot (Option C)** is fragile and has a visible participant + consent implications.
- **Rename `aadObjectId` → a neutral id** in the schema so the codebase isn't Azure-flavored.

---

### TL;DR for the new-repo Claude
Reuse §4 (schema), §6 (STT), §7 (agent) almost as-is. Replace the Teams C# media bot with a
small Python **capture** stage against the **Google Meet REST API (Option A)** — and ask the
human to confirm the Google Workspace edition + recording settings before you build it, because
that decides whether Option A is viable at all. Scaffold the repo per §9, build in the §11 order.
```
