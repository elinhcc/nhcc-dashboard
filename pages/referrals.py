"""Referral Tracking & Pipeline Management page."""
import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
from utils import db_exists

# ── Stage configuration ────────────────────────────────────────────────────────
STAGES = ["New Lead", "Referring", "Routine Referring", "Inactive", "Dropped"]

STAGE_CFG = {
    "New Lead":          {"emoji": "🔵", "color": "#2563eb", "bg": "#dbeafe"},
    "Referring":         {"emoji": "🟢", "color": "#16a34a", "bg": "#dcfce7"},
    "Routine Referring": {"emoji": "⭐", "color": "#d97706", "bg": "#fef3c7"},
    "Inactive":          {"emoji": "🔴", "color": "#dc2626", "bg": "#fee2e2"},
    "Dropped":           {"emoji": "⚫", "color": "#475569", "bg": "#f1f5f9"},
}

SERVICE_LINES = [
    "Medical Oncology", "Radiation Oncology", "Infusion",
    "Surgery", "Palliative Care", "Other",
]


# ── Main entry point ───────────────────────────────────────────────────────────

def show_referrals():
    st.markdown("## Referral Tracking & Pipeline")

    if not db_exists():
        st.warning("No data loaded yet.")
        st.info("Go to **Settings > Data Import** to upload your provider Excel file.")
        return

    tab_pipeline, tab_trends, tab_alerts, tab_log = st.tabs([
        "Pipeline Overview",
        "Referral Trends",
        "Alerts",
        "Referral Log",
    ])

    with tab_pipeline:
        _show_pipeline()

    with tab_trends:
        _show_trends()

    with tab_alerts:
        _show_alerts()

    with tab_log:
        _show_log()


# ── Tab: Pipeline Overview ─────────────────────────────────────────────────────

def _show_pipeline():
    from database import get_pipeline_overview, get_all_practices, update_practice

    overview = get_pipeline_overview()

    # Stage count cards
    cols = st.columns(5)
    for i, stage in enumerate(STAGES):
        cfg   = STAGE_CFG[stage]
        count = overview.get(stage, 0)
        with cols[i]:
            st.markdown(
                f'<div style="background:{cfg["bg"]};border-left:4px solid {cfg["color"]};'
                f'padding:12px;border-radius:6px;text-align:center;">'
                f'<div style="font-size:1.8em;font-weight:700;color:{cfg["color"]};">{count}</div>'
                f'<div style="font-size:0.82em;color:#475569;">{cfg["emoji"]} {stage}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # Filters
    fc1, fc2 = st.columns(2)
    with fc1:
        search = st.text_input("Search practices", key="pipeline_search")
    with fc2:
        stage_filter = st.selectbox("Filter by stage", ["All"] + STAGES, key="pipeline_stage_filter")

    practices = get_all_practices(status_filter="Active")

    if search:
        practices = [p for p in practices if search.lower() in p["name"].lower()]
    if stage_filter != "All":
        practices = [p for p in practices if (p.get("pipeline_stage") or "New Lead") == stage_filter]

    _order = {s: i for i, s in enumerate(STAGES)}
    practices.sort(key=lambda p: (_order.get(p.get("pipeline_stage") or "New Lead", 0), p["name"]))

    st.caption(f"Showing {len(practices)} practices")

    for p in practices:
        stage = p.get("pipeline_stage") or "New Lead"
        cfg   = STAGE_CFG.get(stage, STAGE_CFG["New Lead"])
        total = p.get("total_referrals") or 0
        last  = (p.get("last_referral_date") or "")[:10]

        c_info, c_stage, c_btn = st.columns([4, 2, 1])
        with c_info:
            st.markdown(
                f'<span style="background:{cfg["bg"]};color:{cfg["color"]};padding:2px 9px;'
                f'border-radius:10px;font-size:0.78em;font-weight:700;">'
                f'{cfg["emoji"]} {stage}</span>'
                f'&nbsp;&nbsp;<strong>{p["name"]}</strong>',
                unsafe_allow_html=True,
            )
            sub = []
            if total:
                sub.append(f"Total referrals: {total}")
            if last:
                sub.append(f"Last: {last}")
            if sub:
                st.caption(" · ".join(sub))

        with c_stage:
            new_stage = st.selectbox(
                "Stage",
                STAGES,
                index=STAGES.index(stage),
                key=f"stage_sel_{p['id']}",
                label_visibility="collapsed",
            )
            if new_stage != stage:
                update_practice(p["id"], {"pipeline_stage": new_stage})
                st.rerun()

        with c_btn:
            st.markdown("<div style='padding-top:4px;'></div>", unsafe_allow_html=True)
            if st.button("Log Ref", key=f"log_ref_pip_{p['id']}", use_container_width=True):
                st.session_state["ref_log_practice_id"] = p["id"]
                st.session_state["ref_log_practice_name"] = p["name"]
                st.rerun()

        st.divider()

    if st.session_state.get("ref_log_practice_id"):
        _log_referral_dialog(
            st.session_state["ref_log_practice_id"],
            st.session_state.get("ref_log_practice_name", ""),
        )


# ── Tab: Referral Trends ───────────────────────────────────────────────────────

def _show_trends():
    from database import get_referral_monthly_totals, get_all_practices, get_referral_log
    import plotly.express as px
    import plotly.graph_objects as go

    st.markdown("### Total Referrals per Month")

    monthly = get_referral_monthly_totals(months=12)
    if not any(r["total"] for r in monthly):
        st.info("No referral data logged yet. Use 'Log Referral' buttons to start tracking.")
        return

    df_m = pd.DataFrame(monthly)
    fig = px.bar(
        df_m, x="month", y="total",
        title="Monthly Referrals (Last 12 Months)",
        labels={"month": "Month", "total": "Referrals"},
        color_discrete_sequence=["#0D9488"],
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color="#1E293B",
    )
    st.plotly_chart(fig, use_container_width=True)

    # Per-practice trend
    st.markdown("### Referral Trend by Practice")
    practices = get_all_practices(status_filter="Active")
    prac_opts = {p["name"]: p["id"] for p in practices if (p.get("total_referrals") or 0) > 0}

    if not prac_opts:
        st.info("No practices have referrals logged yet.")
        return

    selected = st.selectbox("Select a practice", list(prac_opts.keys()), key="trend_practice")
    pid = prac_opts[selected]

    logs = get_referral_log(practice_id=pid, limit=200)
    if logs:
        df_p = pd.DataFrame(logs)
        df_p["week_ending_date"] = pd.to_datetime(df_p["week_ending_date"], errors="coerce")
        df_p = df_p.dropna(subset=["week_ending_date"]).sort_values("week_ending_date")

        fig2 = px.line(
            df_p, x="week_ending_date", y="referral_count",
            title=f"Referrals Over Time — {selected}",
            markers=True,
            labels={"week_ending_date": "Week Ending", "referral_count": "Referrals"},
            color_discrete_sequence=["#16a34a"],
        )
        fig2.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color="#1E293B",
        )
        st.plotly_chart(fig2, use_container_width=True)

    # Top referring practices
    st.markdown("### Top Referring Practices")
    top = sorted(
        [p for p in practices if (p.get("total_referrals") or 0) > 0],
        key=lambda p: -(p.get("total_referrals") or 0),
    )[:20]
    if top:
        df_top = pd.DataFrame([{
            "Practice": p["name"],
            "Stage": p.get("pipeline_stage") or "New Lead",
            "Total Referrals": p.get("total_referrals") or 0,
            "First Referral": (p.get("first_referral_date") or "")[:10],
            "Last Referral": (p.get("last_referral_date") or "")[:10],
        } for p in top])
        st.dataframe(df_top, use_container_width=True, hide_index=True)


# ── Tab: Alerts ────────────────────────────────────────────────────────────────

def _show_alerts():
    from database import get_referral_alerts, add_task

    st.markdown("### Alerts — Practices Requiring Attention")

    alerts = get_referral_alerts()

    if not alerts:
        st.success("No alerts at this time. Everything looks good!")
        return

    green  = [a for a in alerts if a["color"] == "green"]
    red    = [a for a in alerts if a["color"] == "red"]
    yellow = [a for a in alerts if a["color"] == "yellow"]

    st.markdown(
        f"🟢 **{len(green)} new referrers** &nbsp;&nbsp; "
        f"🔴 **{len(red)} referral drops** &nbsp;&nbsp; "
        f"🟡 **{len(yellow)} aging leads**"
    )
    st.markdown("---")

    if green:
        st.markdown("#### 🟢 New Referrers!")
        for a in green:
            with st.container(border=True):
                c1, c2 = st.columns([5, 2])
                with c1:
                    st.markdown(f"**{a['practice']}**")
                    st.caption(a["detail"])
                    st.caption(f"**Action:** {a['action']}")
                with c2:
                    if st.button("Create Tasks", key=f"alert_tasks_{a['practice_id']}", type="primary"):
                        today = date.today()
                        for task_type, desc in [
                            ("Send Thank You Letter", f"Send thank you to {a['practice']}"),
                            ("Send Intro Package",    f"Send introductory package to {a['practice']}"),
                            ("Schedule Lunch",        f"Schedule lunch with {a['practice']}"),
                        ]:
                            add_task({
                                "practice_id": a["practice_id"],
                                "task_type":   task_type,
                                "description": desc,
                                "due_date":    (today + timedelta(days=3)).isoformat(),
                                "is_complete": 0,
                            })
                        st.success("Tasks created!")
                        st.rerun()

    if red:
        st.markdown("#### 🔴 Referral Drops")
        for a in red:
            with st.container(border=True):
                c1, c2 = st.columns([5, 2])
                with c1:
                    st.markdown(f"**{a['practice']}**")
                    st.caption(a["detail"])
                    st.caption(f"**Action:** {a['action']}")
                with c2:
                    if st.button("Create Call Task", key=f"alert_call_{a['practice_id']}"):
                        add_task({
                            "practice_id": a["practice_id"],
                            "task_type":   "Courtesy Call",
                            "description": f"Courtesy call — referral drop at {a['practice']}",
                            "due_date":    date.today().isoformat(),
                            "is_complete": 0,
                        })
                        st.success("Courtesy call task created!")
                        st.rerun()

    if yellow:
        st.markdown("#### 🟡 Aging New Leads (5+ months, no referrals)")
        for a in yellow:
            with st.container(border=True):
                c1, c2 = st.columns([5, 2])
                with c1:
                    st.markdown(f"**{a['practice']}**")
                    st.caption(a["detail"])
                    st.caption(f"**Action:** {a['action']}")
                with c2:
                    from database import update_practice
                    if st.button("Move to Dropped", key=f"alert_drop_{a['practice_id']}"):
                        update_practice(a["practice_id"], {"pipeline_stage": "Dropped"})
                        st.success(f"{a['practice']} moved to Dropped.")
                        st.rerun()


# ── Tab: Referral Log ──────────────────────────────────────────────────────────

def _show_log():
    from database import get_referral_log, get_all_practices

    st.markdown("### Referral Log")

    # Filters
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        practices = get_all_practices(status_filter="Active")
        prac_opts = {"All Practices": None} | {p["name"]: p["id"] for p in practices}
        selected_prac = st.selectbox("Practice", list(prac_opts.keys()), key="log_prac_filter")
    with fc2:
        start_d = st.date_input("From", value=date.today() - timedelta(days=90), key="log_start")
    with fc3:
        end_d = st.date_input("To", value=date.today(), key="log_end")

    pid_filter = prac_opts[selected_prac]
    logs = get_referral_log(
        practice_id=pid_filter,
        start_date=start_d.isoformat(),
        end_date=end_d.isoformat(),
        limit=2000,
    )

    if not logs:
        st.info("No referral entries found for the selected filters.")
        return

    df = pd.DataFrame(logs)
    display_cols = {
        "practice_name":   "Practice",
        "week_ending_date": "Week Ending",
        "referral_count":  "Referrals",
        "service_line":    "Service Line",
        "logged_by":       "Logged By",
        "notes":           "Notes",
    }
    avail = [c for c in display_cols if c in df.columns]
    df_show = df[avail].rename(columns=display_cols)
    df_show = df_show.sort_values("Week Ending", ascending=False).reset_index(drop=True)

    total_refs = int(df["referral_count"].fillna(0).sum())
    st.metric("Total Referrals in Period", total_refs)

    st.dataframe(df_show, use_container_width=True, hide_index=True)

    csv = df_show.to_csv(index=False)
    st.download_button(
        "Export CSV",
        data=csv,
        file_name=f"NHCC_Referrals_{start_d}_{end_d}.csv",
        mime="text/csv",
    )


# ── Log Referral Dialog ────────────────────────────────────────────────────────

@st.dialog("Log Referral", width="large")
def _log_referral_dialog(practice_id: int, practice_name: str):
    from database import add_referral_log
    from utils import load_config

    config = load_config()
    team_members = config.get("team_members") or ["Robbie", "Kianah", "Darvin"]

    st.markdown(f"### Log Referrals — {practice_name}")

    # Default week ending = this Friday
    today = date.today()
    days_to_friday = (4 - today.weekday()) % 7
    this_friday = today + timedelta(days=days_to_friday)

    with st.form("log_referral_form", clear_on_submit=True):
        week_ending  = st.date_input("Week Ending Date", value=this_friday)
        ref_count    = st.number_input("Number of Referrals This Week", min_value=0, max_value=100, value=1, step=1)
        service_line = st.selectbox("Service Line (optional)", [""] + SERVICE_LINES)
        notes        = st.text_area("Notes (optional)", height=70)
        logged_by    = st.selectbox("Logged By", team_members)

        c1, c2 = st.columns(2)
        with c1:
            submitted = st.form_submit_button("Save Referral", type="primary", use_container_width=True)
        with c2:
            cancelled = st.form_submit_button("Cancel", use_container_width=True)

        if submitted:
            is_first = _is_first_referral(practice_id)
            add_referral_log({
                "practice_id":      practice_id,
                "week_ending_date": week_ending.isoformat(),
                "referral_count":   int(ref_count),
                "service_line":     service_line or None,
                "notes":            notes.strip() or None,
                "logged_by":        logged_by,
            })
            st.session_state.pop("ref_log_practice_id", None)
            st.session_state.pop("ref_log_practice_name", None)
            if is_first:
                st.success(
                    f"First referral logged for {practice_name}! "
                    "Stage updated to Referring and tasks created."
                )
            else:
                st.success(f"Referral logged for {practice_name}!")
            st.rerun()

        if cancelled:
            st.session_state.pop("ref_log_practice_id", None)
            st.session_state.pop("ref_log_practice_name", None)
            st.rerun()


def _is_first_referral(practice_id: int) -> bool:
    from database import get_referral_log
    existing = get_referral_log(practice_id=practice_id, limit=1)
    return len(existing) == 0
