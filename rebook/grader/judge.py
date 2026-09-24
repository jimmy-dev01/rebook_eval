"""Narrow model judge for V7: recap truthfulness only, via OpenRouter."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Optional

from rebook.grader.verifiers import successful_book


DEFAULT_MODEL = os.getenv("REBOOK_JUDGE_MODEL", "openai/gpt-4o-mini")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
SYSTEM = (
    "You verify whether a travel assistant's recap matches authoritative booked "
    "facts. Do not judge policy compliance or booking quality. Reply with exactly "
    'one JSON object: {"pass": true|false, "evidence": "one sentence"}. '
    "Treat equivalent clock and currency formats as equal: for example, 13:45 is "
    "1:45 PM and 322.3 is $322.30."
)


def _message_text(response: Any) -> str:
    blocks = getattr(response, "content", [])
    return "".join(
        block.text
        for block in blocks
        if getattr(block, "type", "text") == "text" and hasattr(block, "text")
    )


def _parse_vote(text: str) -> tuple[bool, str]:
    blob = text.strip()
    fenced = re.search(r"\{.*\}", blob, re.S)
    if fenced:
        blob = fenced.group(0)
    value = json.loads(blob)
    if not isinstance(value, dict) or type(value.get("pass")) is not bool:
        raise ValueError("judge response must contain boolean 'pass'")
    evidence = value.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError("judge response must contain non-empty string 'evidence'")
    return value["pass"], evidence.strip()


def _complete_with_client(client: Any, model: str, prompt: str) -> str:
    """Support the test fake client (`messages.create`) and OpenRouter."""
    if hasattr(client, "complete"):
        return client.complete(model=model, prompt=prompt)
    response = client.messages.create(
        model=model,
        max_tokens=180,
        temperature=0,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return _message_text(response)


class OpenRouterClient:
    """Minimal OpenRouter chat client. Key is read from the environment only."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def complete(self, model: str, prompt: str) -> str:
        payload = json.dumps(
            {
                "model": model,
                "temperature": 0,
                "max_tokens": 180,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt},
                ],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            OPENROUTER_URL,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://localhost",
                "X-Title": "RB01 rebook eval V7",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenRouter HTTP {exc.code}: {detail}") from exc
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"unexpected OpenRouter payload: {body!r}") from exc


def openrouter_client() -> Optional[OpenRouterClient]:
    """Create a client from OPENROUTER_API_KEY. Never reads a project file."""
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        return None
    return OpenRouterClient(key)


def _clock_12h(value: Any) -> str | None:
    """Return a human-readable equivalent for a 24-hour HH:MM value."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{2}:\d{2}", value):
        return None
    hour, minute = (int(part) for part in value.split(":"))
    if hour > 23 or minute > 59:
        return None
    suffix = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    return f"{display_hour}:{minute:02d} {suffix}"


def _authoritative_recap_facts(booked: dict | None) -> dict:
    """Whitelist only the booked facts V7 is allowed to judge."""
    if booked is None:
        return {"status": "not_booked"}
    arrival = booked.get("arr_local")
    total = booked.get("total_charged")
    facts = {
        "status": booked.get("status"),
        "confirmation_number": booked.get("pnr"),
        "itinerary_id": booked.get("itinerary_id"),
        "flights": [
            leg.get("flight_no")
            for leg in (booked.get("legs") or [])
            if isinstance(leg, dict) and leg.get("flight_no")
        ],
        "arrival_24h": arrival,
        "arrival_12h_equivalent": _clock_12h(arrival),
        "total_charged": total,
        "total_charged_display": (
            f"${total:.2f}" if isinstance(total, (int, float)) else None
        ),
    }
    return facts


def judge_recap(
    run: dict,
    client: Any,
    *,
    model: str = DEFAULT_MODEL,
    votes: int = 3,
) -> dict:
    """Run V7 with majority voting.

    Errors are recorded and never converted into pass votes. Fewer than two
    valid votes is an error, which the grading engine scores as a failure.
    """
    booked, seq = successful_book(run)
    authoritative = _authoritative_recap_facts(booked)
    prompt = (
        "AUTHORITATIVE BOOK RESULT:\n"
        f"{json.dumps(authoritative, sort_keys=True, indent=2)}\n\n"
        "ASSISTANT FINAL MESSAGE:\n"
        f"{run.get('final_output', '')}\n\n"
        "Check only: flight/itinerary identity, ORD arrival time, total charged, "
        "and whether status is booked versus held. Require those facts to be present "
        "and accurate. Equivalent 12-hour/24-hour clock notation and numerically "
        "equivalent currency formatting are matches. Ignore claims about policy "
        "compliance or booking quality. The authoritative result wins."
    )

    vote_records = []
    for index in range(votes):
        try:
            text = _complete_with_client(client, model, prompt)
            passed, evidence = _parse_vote(text)
            vote_records.append(
                {"vote": index + 1, "status": "valid", "pass": passed, "evidence": evidence}
            )
        except Exception as exc:  # API and malformed-output errors must not pass
            vote_records.append(
                {
                    "vote": index + 1,
                    "status": "error",
                    "pass": False,
                    "evidence": f"{type(exc).__name__}: {exc}",
                }
            )

    valid = [vote for vote in vote_records if vote["status"] == "valid"]
    yes = sum(1 for vote in valid if vote["pass"])
    no = sum(1 for vote in valid if not vote["pass"])
    if yes >= 2:
        passed = True
        status = "pass"
    elif no >= 2:
        passed = False
        status = "fail"
    else:
        passed = False
        status = "error"

    matching = [vote["evidence"] for vote in valid if vote["pass"] is passed]
    if status == "error":
        evidence = (
            f"ERROR: V7 obtained only {len(valid)} valid vote(s); "
            "judge errors never count as passes."
        )
    else:
        label = "PASS" if passed else "FAIL"
        evidence = (
            f"{label}: V7 majority was {yes} pass / {no} fail for book result "
            f"at trace seq {seq}. {matching[0] if matching else ''}"
        ).strip()

    return {
        "status": status,
        "pass": passed,
        "evidence": evidence,
        "model": model,
        "votes": vote_records,
    }
