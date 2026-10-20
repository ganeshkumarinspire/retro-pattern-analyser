"""Send retro notes to Claude and get back a structured analysis.

The API key is read from the ANTHROPIC_API_KEY environment variable, which
`load_dotenv()` fills from the .env file. It is never written in the code.
"""

import os
from pathlib import Path

import anthropic
import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).parent / ".env")

MODEL = "claude-opus-5-5"


# --- The shape of the answer we want back -----------------------------------
# Claude is asked to reply in exactly this structure ("structured outputs"),
# so the app can display it without guessing how to parse free text.

class Theme(BaseModel):
    name: str = Field(description="Short theme name, e.g. 'Test environment instability'")
    sprints: list[str] = Field(description="Sprints where this theme appeared")
    evidence_quotes: list[str] = Field(description="2-3 verbatim quotes from the notes")


class RootCause(BaseModel):
    cause: str
    explanation: str


class Recommendation(BaseModel):
    title: str
    detail: str
    owner: str = Field(description="Who should drive it, e.g. Scrum Master, PO, Basis lead")


class RetroInsights(BaseModel):
    top_themes: list[Theme]
    root_causes: list[RootCause]
    recommendations: list[Recommendation] = Field(description="Exactly 3 recommendations")


SYSTEM_PROMPT = """You are an experienced agile coach helping a Scrum Master \
analyse several sprints of retrospective notes from one team.

Look across sprints, not inside one: the value is in spotting what keeps \
coming back and whether the team's action items changed anything.
- Top themes: the 3-5 most important recurring patterns. Quote the notes \
word for word as evidence; do not paraphrase inside quotes.
- Root causes: go one level deeper than the symptoms (systemic, process or \
organisational causes), and say which notes point to each one.
- Recommendations: exactly 3, concrete enough to try in the next sprint, and \
different from action items the team already tried that did not stick.
Be direct and practical. Write in plain English for a mixed business/IT team."""


def notes_to_text(df: pd.DataFrame) -> str:
    """Turn the notes table into a compact, readable block grouped by sprint."""
    lines = []
    for sprint, group in df.groupby("sprint", sort=False):
        lines.append(f"## {sprint}")
        for _, row in group.iterrows():
            lines.append(f"- [{row['category']}] {row['note']}")
        lines.append("")
    return "\n".join(lines)


DEMO_RESULT = Path(__file__).parent / "data" / "sample_ai_analysis.json"


def has_api_key() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def load_demo_result() -> RetroInsights:
    """Pre-generated analysis of the sample data, used in free demo mode (no API key)."""
    return RetroInsights.model_validate_json(DEMO_RESULT.read_text(encoding="utf-8"))


def analyse_with_claude(df: pd.DataFrame, follow_through: pd.DataFrame | None = None) -> RetroInsights:
    """Call Claude once with all notes and return the parsed insights.

    Raises RuntimeError with a friendly message if something goes wrong.
    """
    client = anthropic.Anthropic()  # picks up ANTHROPIC_API_KEY automatically

    prompt = "Here are our retrospective notes, oldest sprint first:\n\n" + notes_to_text(df)
    if follow_through is not None and not follow_through.empty:
        prompt += (
            "\nOur own follow-through check (did the theme come back within 2 sprints "
            "after the action?):\n"
            + "\n".join(
                f"- {r.sprint}: {r.action} -> {r.status}" for r in follow_through.itertuples()
            )
        )

    try:
        response = client.beta.messages.parse(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            output_format=RetroInsights,
            output_config={"effort": "medium"},
            # If the main model declines a request, let the API retry on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError:
        raise RuntimeError("The API key was rejected. Check ANTHROPIC_API_KEY in your .env file.")
    except anthropic.RateLimitError:
        raise RuntimeError("Rate limit reached. Wait a minute and try again.")
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"The Anthropic API returned an error ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise RuntimeError("Could not reach the Anthropic API. Check your internet connection.")

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to analyse these notes.")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise RuntimeError("The answer was cut off or could not be read. Please try again.")
    return response.parsed_output
