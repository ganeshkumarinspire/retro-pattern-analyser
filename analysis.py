"""Pure analysis logic for the Retro Pattern Analyser.

Nothing in here knows about Streamlit, so every function can be tested on its
own with a plain pandas DataFrame.
"""

import re

import pandas as pd

REQUIRED_COLUMNS = ["sprint", "date", "category", "note"]
CATEGORIES = ["went_well", "didnt_go_well", "action"]

# Theme -> keywords. A note gets the FIRST theme whose keyword it contains,
# so order matters: put the most specific themes first.
# Edit this dictionary to fit your own team's vocabulary.
THEMES = {
    "Unclear requirements": [
        "requirement", "requirements", "unclear", "spec", "acceptance criteria",
        "vague", "definition of ready", "3 amigos", "misunderstanding",
        "misunderstandings", "edge cases",
    ],
    "Test environments": [
        "qas", "test environment", "test system", "test data", "environment",
        "transport", "transports", "system copy", "refresh",
    ],
    "Scope changes": [
        "scope", "mid-sprint", "urgent request", "new request", "new requests",
        "swapped in",
    ],
    "Dependencies": [
        "dependency", "dependencies", "waiting on", "fi team", "fi/co", "interface",
    ],
    "Communication": [
        "communication", "meeting", "meetings", "offshore", "handover", "stand-up",
    ],
}
OTHER = "Other"

# How many sprints after an action we look for the same problem coming back.
FOLLOW_UP_WINDOW = 2


def classify_theme(note: str) -> str:
    """Return the first theme whose keyword appears in the note (whole words only)."""
    text = str(note).lower()
    for theme, keywords in THEMES.items():
        for kw in keywords:
            if re.search(rf"\b{re.escape(kw)}\b", text):
                return theme
    return OTHER


def validate(df: pd.DataFrame) -> list[str]:
    """Return a list of human-readable problems with an uploaded CSV (empty = OK)."""
    problems = []
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        problems.append(f"Missing column(s): {', '.join(missing)}")
        return problems
    bad = sorted(set(df["category"].dropna()) - set(CATEGORIES))
    if bad:
        problems.append(
            f"Unknown category value(s): {', '.join(map(str, bad))}. "
            f"Use one of: {', '.join(CATEGORIES)}"
        )
    return problems


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Clean the raw notes and add a `theme` column."""
    df = df[REQUIRED_COLUMNS].copy()
    df["sprint"] = df["sprint"].astype(str).str.strip()
    df["category"] = df["category"].astype(str).str.strip().str.lower()
    df["note"] = df["note"].astype(str).str.strip()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df[df["note"] != ""]
    df["theme"] = df["note"].map(classify_theme)
    return df.reset_index(drop=True)


def sprint_order(df: pd.DataFrame) -> list[str]:
    """Sprints in chronological order (by earliest date, then by name)."""
    first_dates = df.groupby("sprint")["date"].min()
    return sorted(first_dates.index, key=lambda s: (first_dates[s], _sprint_number(s), s))


def _sprint_number(name: str) -> int:
    match = re.search(r"\d+", name)
    return int(match.group()) if match else 0


def theme_heatmap(df: pd.DataFrame) -> pd.DataFrame:
    """Rows = themes, columns = sprints, values = count of 'didnt_go_well' notes."""
    order = sprint_order(df)
    problems = df[df["category"] == "didnt_go_well"]
    table = pd.crosstab(problems["theme"], problems["sprint"])
    table = table.reindex(columns=order, fill_value=0)
    # Most frequent themes on top
    return table.loc[table.sum(axis=1).sort_values(ascending=False).index]


def recurring_issues(df: pd.DataFrame, min_sprints: int = 2) -> pd.DataFrame:
    """Themes that showed up as a problem in at least `min_sprints` sprints."""
    total = len(sprint_order(df))
    heat = theme_heatmap(df)
    rows = []
    for theme, counts in heat.iterrows():
        sprints_hit = int((counts > 0).sum())
        if sprints_hit >= min_sprints and theme != OTHER:
            rows.append({
                "theme": theme,
                "sprints_with_issue": sprints_hit,
                "total_sprints": total,
                "notes": int(counts.sum()),
                "summary": f"{theme}: {sprints_hit} of {total} sprints",
            })
    return pd.DataFrame(rows, columns=["theme", "sprints_with_issue", "total_sprints", "notes", "summary"])


def action_follow_through(df: pd.DataFrame, window: int = FOLLOW_UP_WINDOW) -> pd.DataFrame:
    """For every action item, check whether its theme came back in the next `window` sprints.

    - "Didn't stick"      -> the same theme was raised as a problem again
    - "Worked"            -> a full window of later sprints exists and the theme stayed away
    - "Too early to tell" -> fewer than `window` sprints have happened since, and no recurrence yet
    """
    order = sprint_order(df)
    problems = df[df["category"] == "didnt_go_well"]
    problem_sprints = problems.groupby("theme")["sprint"].apply(set).to_dict()

    rows = []
    for _, action in df[df["category"] == "action"].iterrows():
        idx = order.index(action["sprint"])
        later = order[idx + 1: idx + 1 + window]
        came_back = [s for s in later if s in problem_sprints.get(action["theme"], set())]

        if action["theme"] == OTHER:
            status = "Can't classify"
        elif came_back:
            status = "Didn't stick"
        elif len(later) < window:
            status = "Too early to tell"
        else:
            status = "Worked"

        rows.append({
            "sprint": action["sprint"],
            "action": action["note"],
            "theme": action["theme"],
            "checked_sprints": ", ".join(later) if later else "-",
            "came_back_in": ", ".join(came_back) if came_back else "-",
            "status": status,
        })
    return pd.DataFrame(rows, columns=["sprint", "action", "theme", "checked_sprints", "came_back_in", "status"])
