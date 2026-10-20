"""Retro Pattern Analyser - Streamlit app.

Run with:  streamlit run app.py
"""

from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import analysis
import ai_analysis

SAMPLE_CSV = Path(__file__).parent / "data" / "sample_retro_notes.csv"

# Single-hue blue ramp, light -> dark (light = few notes, dark = many).
HEAT_SCALE = [
    [0.0, "#f3f7fc"], [0.2, "#cde2fb"], [0.4, "#86b6ef"],
    [0.6, "#3987e5"], [0.8, "#1c5cab"], [1.0, "#0d366b"],
]
STATUS_ICONS = {
    "Worked": "✅ Worked",
    "Didn't stick": "🔁 Didn't stick",
    "Too early to tell": "⏳ Too early to tell",
    "Can't classify": "❔ Can't classify",
}
CATEGORY_LABELS = {
    "went_well": "Went well",
    "didnt_go_well": "Didn't go well",
    "action": "Action",
}

st.set_page_config(page_title="Retro Pattern Analyser", page_icon="🔁", layout="wide")


# --- Step 1: load the notes into session state -------------------------------
# st.session_state keeps data alive between reruns (Streamlit re-runs the whole
# script on every click), so notes you add in the app aren't lost.

if "notes" not in st.session_state:
    st.session_state.notes = pd.read_csv(SAMPLE_CSV)
    st.session_state.source = "Sample data (SAP order-to-cash team)"
    st.session_state.ai_result = None

with st.sidebar:
    st.header("📂 Data")

    uploaded = st.file_uploader("Upload your own CSV", type="csv",
                                help="Columns: sprint, date, category, note")
    if uploaded is not None and st.session_state.get("uploaded_id") != uploaded.file_id:
        new_df = pd.read_csv(uploaded)
        problems = analysis.validate(new_df)
        if problems:
            for p in problems:
                st.error(p)
        else:
            st.session_state.notes = new_df[analysis.REQUIRED_COLUMNS]
            st.session_state.source = f"Uploaded: {uploaded.name}"
            st.session_state.uploaded_id = uploaded.file_id
            st.session_state.ai_result = None

    if st.button("↩️ Reset to sample data", width="stretch"):
        st.session_state.notes = pd.read_csv(SAMPLE_CSV)
        st.session_state.source = "Sample data (SAP order-to-cash team)"
        st.session_state.ai_result = None
        st.session_state.pop("uploaded_id", None)

    st.caption(f"Using: **{st.session_state.source}**")

    st.divider()
    st.header("✍️ Add a note")
    existing_sprints = list(dict.fromkeys(st.session_state.notes["sprint"].astype(str)))
    with st.form("add_note", clear_on_submit=True):
        sprint_choice = st.selectbox("Sprint", ["New sprint…"] + existing_sprints[::-1])
        new_sprint = st.text_input("New sprint name (if 'New sprint…')", placeholder="Sprint 44")
        note_date = st.date_input("Date", value=date.today())
        category = st.radio("Category", analysis.CATEGORIES,
                            format_func=CATEGORY_LABELS.get, horizontal=True)
        note_text = st.text_area("Note", placeholder="e.g. QAS was down again on Tuesday")
        if st.form_submit_button("Add note", width="stretch"):
            sprint_name = new_sprint.strip() if sprint_choice == "New sprint…" else sprint_choice
            if not sprint_name or not note_text.strip():
                st.warning("Please fill in a sprint name and a note.")
            else:
                row = pd.DataFrame([{"sprint": sprint_name, "date": note_date.isoformat(),
                                     "category": category, "note": note_text.strip()}])
                st.session_state.notes = pd.concat([st.session_state.notes, row], ignore_index=True)
                st.session_state.ai_result = None
                st.success(f"Added to {sprint_name}")

    st.download_button("⬇️ Download notes as CSV",
                       st.session_state.notes.to_csv(index=False).encode("utf-8"),
                       file_name="retro_notes.csv", mime="text/csv", width="stretch")


# --- Step 2: analyse ---------------------------------------------------------

df = analysis.prepare(st.session_state.notes)
if df.empty:
    st.info("No notes yet. Upload a CSV or add a note in the sidebar.")
    st.stop()

sprints = analysis.sprint_order(df)
heat = analysis.theme_heatmap(df)
recurring = analysis.recurring_issues(df)
follow = analysis.action_follow_through(df)

st.title("🔁 Retro Pattern Analyser")
st.caption("Spot the issues your team keeps raising, and check whether your action items actually worked.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Sprints", len(sprints))
c2.metric("Problems raised", int((df["category"] == "didnt_go_well").sum()))
c3.metric("Action items", len(follow))
worked = int((follow["status"] == "Worked").sum()) if not follow.empty else 0
decided = int(follow["status"].isin(["Worked", "Didn't stick"]).sum()) if not follow.empty else 0
c4.metric("Actions worked", f"{worked} of {decided}" if decided else "-",
          help="Only counts actions with a verdict (not 'too early to tell').")

tab_patterns, tab_actions, tab_ai, tab_notes = st.tabs(
    ["📊 Patterns", "✅ Action follow-through", "🤖 Analyse with AI", "📝 Notes"])


# --- Tab: heatmap + recurring issues -----------------------------------------
with tab_patterns:
    st.subheader("Recurring issues")
    if recurring.empty:
        st.info("No theme has come up as a problem in more than one sprint yet.")
    else:
        cols = st.columns(len(recurring))
        for col, r in zip(cols, recurring.itertuples()):
            # Plain markdown instead of st.metric so long theme names wrap instead of being cut off
            col.markdown(f"**{r.theme}**  \n"
                         f"<span style='font-size:1.9rem'>{r.sprints_with_issue} of {r.total_sprints}</span> sprints",
                         unsafe_allow_html=True)
            col.progress(r.sprints_with_issue / r.total_sprints)
            col.caption(f"{r.notes} 'didn't go well' notes")

    st.subheader("Problem themes by sprint")
    st.caption("Each cell counts the *didn't go well* notes for that theme in that sprint. Darker = raised more often.")
    if heat.empty:
        st.info("No 'didn't go well' notes yet.")
    else:
        fig = go.Figure(go.Heatmap(
            z=heat.values, x=heat.columns.tolist(), y=heat.index.tolist(),
            colorscale=HEAT_SCALE, zmin=0, xgap=2, ygap=2,
            text=heat.values, texttemplate="%{text}",
            hovertemplate="<b>%{y}</b><br>%{x}: %{z} note(s)<extra></extra>",
            colorbar=dict(title="Notes", thickness=12, dtick=1),
        ))
        fig.update_layout(height=80 + 55 * len(heat), margin=dict(l=10, r=10, t=10, b=10),
                          yaxis=dict(autorange="reversed"), xaxis=dict(side="top"))
        st.plotly_chart(fig, width="stretch")

    with st.expander("How are themes detected?"):
        st.write("Each note is matched against a keyword list (first match wins). "
                 "Notes with no match go to **Other**. Edit `THEMES` in `analysis.py` to fit your team's words.")
        st.json(analysis.THEMES, expanded=False)


# --- Tab: action follow-through ----------------------------------------------
with tab_actions:
    st.subheader("Did our action items work?")
    st.caption(f"For each action, we check whether the same theme came back as a problem "
               f"in the next {analysis.FOLLOW_UP_WINDOW} sprints.")
    if follow.empty:
        st.info("No action items yet.")
    else:
        counts = follow["status"].value_counts()
        cols = st.columns(3)
        for col, status in zip(cols, ["Worked", "Didn't stick", "Too early to tell"]):
            col.metric(STATUS_ICONS[status], int(counts.get(status, 0)))

        filter_status = st.multiselect("Show", list(STATUS_ICONS), default=list(STATUS_ICONS),
                                       format_func=STATUS_ICONS.get)
        shown = follow[follow["status"].isin(filter_status)].copy()
        shown["status"] = shown["status"].map(STATUS_ICONS)
        st.dataframe(shown, hide_index=True, width="stretch",
                     column_order=["sprint", "status", "action", "theme", "came_back_in", "checked_sprints"],
                     column_config={
                         "sprint": "Sprint", "status": "Verdict",
                         "action": st.column_config.TextColumn("Action item", width="large"),
                         "theme": "Theme", "came_back_in": "Problem came back in",
                         "checked_sprints": "Sprints checked",
                     })


# --- Tab: AI analysis --------------------------------------------------------
with tab_ai:
    st.subheader("Analyse with AI")
    st.write(f"Sends all **{len(df)} notes** to Claude (`{ai_analysis.MODEL}`) and asks for "
             "the top themes with evidence, likely root causes and 3 recommendations.")

    if ai_analysis.has_api_key():
        if st.button("🤖 Analyse with AI", type="primary"):
            with st.spinner("Claude is reading your retros…"):
                try:
                    st.session_state.ai_result = ai_analysis.analyse_with_claude(df, follow)
                    st.session_state.ai_is_demo = False
                except RuntimeError as e:
                    st.error(str(e))
    else:
        # Free demo mode: show a pre-generated analysis of the sample data.
        st.info("**Demo mode (free).** No API key found, so the button below shows an example "
                "analysis of the built-in sample data that was prepared in advance. "
                "To analyse your own notes live, add `ANTHROPIC_API_KEY=...` to a `.env` file "
                "next to `app.py` and restart the app.")
        if st.button("👀 Show example AI analysis", type="primary"):
            st.session_state.ai_result = ai_analysis.load_demo_result()
            st.session_state.ai_is_demo = True

    result = st.session_state.get("ai_result")
    if result:
        if st.session_state.get("ai_is_demo"):
            st.caption("📌 Example result for the built-in sample data (Sprints 38–43). "
                       "It does not change when you upload or add notes.")
        st.markdown("### 🧭 Top themes")
        for theme in result.top_themes:
            with st.container(border=True):
                st.markdown(f"**{theme.name}** · _{', '.join(theme.sprints)}_")
                for q in theme.evidence_quotes:
                    st.markdown(f"> {q}")

        st.markdown("### 🔍 Likely root causes")
        for rc in result.root_causes:
            st.markdown(f"- **{rc.cause}**: {rc.explanation}")

        st.markdown("### 💡 Recommendations for the team")
        for i, rec in enumerate(result.recommendations, 1):
            with st.container(border=True):
                st.markdown(f"**{i}. {rec.title}**  \n{rec.detail}  \n*Owner: {rec.owner}*")


# --- Tab: raw notes ----------------------------------------------------------
with tab_notes:
    st.subheader("All notes")
    cat_filter = st.multiselect("Category", analysis.CATEGORIES, default=analysis.CATEGORIES,
                                format_func=CATEGORY_LABELS.get)
    view = df[df["category"].isin(cat_filter)].copy()
    view["date"] = view["date"].dt.date
    view["category"] = view["category"].map(CATEGORY_LABELS)
    st.dataframe(view, hide_index=True, width="stretch",
                 column_config={"note": st.column_config.TextColumn("Note", width="large")})
