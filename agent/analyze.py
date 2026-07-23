"""
Analysis agent (Stage 2). Reads a transcribed meeting via shared.store, sends the
transcript to Azure OpenAI, and writes summary / actionItems / analysis back onto
the record. Talk-time is computed locally, never by the LLM. Config comes from
shared.config (AZURE_OPENAI_* + AGENT_OUTPUT_LANGUAGE); _client() is the single
swap point for a Vertex/Gemini backend later.

Usage:
    python -m agent.analyze <meetingId>
    python -m agent.analyze --all        # every meeting with segments[] but no summary
"""

import json
import sys
import time
from openai import OpenAI
from shared.config import settings
from shared import store
from shared.schema import Summary, ActionItem, Analysis
from urllib.parse import urlparse


def _client():
    """Build an OpenAI client against the Azure OpenAI v1 (OpenAI-compatible) API.

    Works for both classic Azure OpenAI (*.openai.azure.com) and Azure AI Foundry
    (*.services.ai.azure.com) resources. We only keep scheme+host from whatever
    AZURE_OPENAI_ENDPOINT is set to and append /openai/v1, so pasting the full
    "target URI" (with /openai/v1/responses etc.) still works.
    """
    endpoint = settings.require("azure_openai_endpoint")
    key = settings.require("azure_openai_key")
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
        speaker = (seg.speaker.name or "Unknown")
        lines.append(f"[{_fmt_ts(seg.startMs)}] {speaker}: {seg.text}")
    return "\n".join(lines)


def _talk_time_seconds(segments):
    totals = {}
    for seg in segments:
        speaker = (seg.speaker.name or "Unknown")
        dur = max(0, seg.endMs - seg.startMs)
        totals[speaker] = round(totals.get(speaker, 0) + dur / 1000.0, 1)
    return totals

OUTPUT_LANGUAGE = settings.agent_output_language

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


def analyze_meeting(meeting_id, client, deployment):
    record = store.load_record(meeting_id)
    if not record.segments:
        print(f"[{meeting_id}] no segments --- run STT first"); return
    if record.summary:
        print(f"[{meeting_id}] already analyzed --- skipping"); return
    participants = [p.name for p in record.participants if p.name]
    transcript = _build_transcript(record.segments)

    user_prompt = (
        f"Participants: {', '.join(participants) if participants else 'unknown'}\n"
        f"Meeting subject: {record.subject or 'n/a'}\n\n"
        f"Transcript:\n{transcript}"
    )

    print(f"[{meeting_id}] analyzing {len(record.segments)} segment(s) via {deployment} ...")
    resp = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    data = json.loads(resp.choices[0].message.content)

    record.summary = Summary(**data["summary"]) if data.get("summary") else None
    record.actionItems = [ActionItem(**a) for a in data.get("actionItems", [])]
    record.analysis = Analysis(**(data.get("analysis") or {}), talkTimeSeconds=_talk_time_seconds(record.segments)) #computed locally
    store.save_record(record)
    print(
        f"[{meeting_id}] wrote summary + {len(record.actionItems)} action item(s) "
    )


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)

    client = _client()
    deployment = settings.require("azure_openai_deployment")

    if args[0] == "--all":
        for meeting_id in store.list_meetings():
            analyze_meeting(meeting_id, client, deployment)
    else:
        analyze_meeting(args[0], client, deployment)


if __name__ == "__main__":
    start = time.time()
    main()
    print(f"done in {time.time() - start:.1f}s")
