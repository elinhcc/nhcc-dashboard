"""Analytics page: charts, reports, exports with comprehensive metrics."""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, date
from utils import db_exists


def _safe_metric(label, value, delta=None, delta_color="normal"):
    """Render a metric, handling delta display."""
    if delta is not None and delta != 0:
        st.metric(label, value, delta=f"{'+' if delta > 0 else ''}{delta} vs last month",
                  delta_color=delta_color)
    else:
        st.metric(label, value)


def _get_month_count(table, date_col, ym, extra_where=""):
    """Count rows matching a year-month in a given table."""
    from database import get_connection
    conn = get_connection()
    q = f"SELECT COUNT(*) FROM {table} WHERE strftime('%Y-%m', {date_col})=?"
    if extra_where:
        q += f" AND {extra_where}"
    count = conn.execute(q, (ym,)).fetchone()[0]
    conn.close()
    return count


def show_analytics():
    st.markdown("## Analytics & Reports")

    tab_overview, tab_lunch_outreach, tab_call_email, tab_location, tab_contacts, tab_export = st.tabs([
        "Overview",
        "Lunch & Outreach",
        "Call & Email Tracking",
        "Location Comparison",
        "Contact Analysis",
        "Export Data",
    ])

    if not db_exists():
        with tab_overview:
            st.warning("No data loaded yet.")
            st.info("Go to **Settings > Data Import** to upload your provider Excel file.")
            # Show empty metrics
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Active Practices", 0)
            c2.metric("Active Providers", 0)
            c3.metric("Contacts This Month", 0)
            c4.metric("Flyers Sent (Month)", 0)
        for tab in [tab_lunch_outreach, tab_call_email, tab_location, tab_contacts, tab_export]:
            with tab:
                st.info("Import data to see analytics.")
        return

    # Lazy imports — only when database exists
    import plotly.express as px
    import plotly.graph_objects as go
    from database import (
        get_all_practices, get_all_providers, get_contact_log,
        get_lunches, get_cookie_visits, get_flyer_campaigns,
        get_thank_yous, get_dashboard_stats, get_connection,
        get_follow_ups,
    )
    from utils import relationship_score, score_label

    now = datetime.now()
    this_ym = now.strftime("%Y-%m")
    last_month = (now.replace(day=1) - timedelta(days=1))
    last_ym = last_month.strftime("%Y-%m")

    # ── Overview ───────────────────────────────────────────────────────
    with tab_overview:
        stats = get_dashboard_stats()

        st.markdown("### Key Metrics")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Active Practices", stats["total_practices"])
        c2.metric("Active Providers", stats["total_providers"])
        c3.metric("Contacts This Month", stats["contacts_this_month"])
        c4.metric("Flyers Sent (Month)", stats["flyers_sent_this_month"])

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Lunches Completed (Month)", stats.get("lunches_completed_month", 0))
        c6.metric("Lunches Scheduled", stats["lunches_scheduled"])
        c7.metric("Cookie Visits (Month)", stats.get("cookie_visits_this_month", 0))
        c8.metric("Pending Thank Yous", stats["pending_thank_yous"])

        c9, c10, c11, c12 = st.columns(4)
        c9.metric("Calls This Month", stats.get("calls_this_month", 0))
        c10.metric("Emails This Month", stats.get("emails_this_month", 0))
        c11.metric("Faxes This Month", stats.get("faxes_this_month", 0))
        c12.metric("Lunches Completed (All Time)", stats.get("lunches_completed_total", 0))

        # Practice distribution by location
        st.markdown("### Practice Distribution by Location")
        practices = get_all_practices(status_filter="Active")
        if practices:
            location_counts = {}
            for p in practices:
                loc = p.get("location_category", "Other")
                location_counts[loc] = location_counts.get(loc, 0) + 1

            fig = px.pie(
                names=list(location_counts.keys()),
                values=list(location_counts.values()),
                title="Practices by Location",
                color_discrete_sequence=["#007bff", "#28a745", "#ffc107"],
            )
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                              font_color="#FFFFFF")
            st.plotly_chart(fig, use_container_width=True)

        # Relationship score distribution
        st.markdown("### Relationship Score Distribution")
        if practices:
            scores = []
            for p in practices:
                s = relationship_score(p["id"])
                lbl = score_label(s)
                scores.append({"Practice": p["name"], "Score": s, "Status": lbl})

            df_scores = pd.DataFrame(scores)
            fig = px.histogram(
                df_scores, x="Score", nbins=10,
                title="Relationship Score Distribution",
                color="Status",
                color_discrete_map={
                    "Strong": "#28a745",
                    "Moderate": "#ffc107",
                    "Needs Attention": "#dc3545",
                },
            )
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                              font_color="#FFFFFF")
            st.plotly_chart(fig, use_container_width=True)

            df_scores = df_scores.sort_values("Score", ascending=False)
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("#### Top 10 Practices")
                st.dataframe(df_scores.head(10)[["Practice", "Score", "Status"]], hide_index=True)
            with col2:
                st.markdown("#### Bottom 10 (Needs Attention)")
                st.dataframe(df_scores.tail(10)[["Practice", "Score", "Status"]], hide_index=True)

    # ── Lunch & Outreach ───────────────────────────────────────────────
    with tab_lunch_outreach:
        st.markdown("### Lunch Statistics")
        lunches = get_lunches()
        if lunches:
            df_lunch = pd.DataFrame(lunches)

            # Status breakdown
            status_counts = df_lunch["status"].value_counts().reset_index()
            status_counts.columns = ["Status", "Count"]
            fig = px.pie(
                status_counts, names="Status", values="Count",
                title="Lunch Status Breakdown",
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="#FFFFFF")
            st.plotly_chart(fig, use_container_width=True)

            # Completed lunches by month (last 12 months)
            completed = df_lunch[df_lunch["status"] == "Completed"].copy()
            if not completed.empty and "completed_date" in completed.columns:
                completed["completed_date"] = pd.to_datetime(completed["completed_date"], errors="coerce")
                completed = completed.dropna(subset=["completed_date"])
                if not completed.empty:
                    completed["month"] = completed["completed_date"].dt.to_period("M").astype(str)
                    monthly_lunch = completed.groupby("month").size().reset_index(name="count")
                    monthly_lunch = monthly_lunch.tail(12)
                    fig = px.bar(monthly_lunch, x="month", y="count", title="Completed Lunches per Month (Last 12)")
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                      font_color="#FFFFFF")
                    st.plotly_chart(fig, use_container_width=True)

            # Lunches by location
            if "practice_name" in df_lunch.columns:
                practices_all = get_all_practices()
                loc_map = {p["name"]: p.get("location_category", "Other") for p in practices_all}
                df_lunch["location"] = df_lunch["practice_name"].map(loc_map).fillna("Other")
                loc_counts = df_lunch[df_lunch["status"] == "Completed"]["location"].value_counts().reset_index()
                loc_counts.columns = ["Location", "Count"]
                if not loc_counts.empty:
                    fig = px.pie(loc_counts, names="Location", values="Count",
                                 title="Completed Lunches by Location")
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="#FFFFFF")
                    st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No lunch data yet.")

        # Cookie visit stats
        st.markdown("### Cookie Visit Statistics")
        cookies = get_cookie_visits()
        if cookies:
            df_cook = pd.DataFrame(cookies)
            st.metric("Total Cookie Visits (All Time)", len(df_cook))
            df_cook["visit_date"] = pd.to_datetime(df_cook["visit_date"], errors="coerce")
            df_cook = df_cook.dropna(subset=["visit_date"])
            if not df_cook.empty:
                df_cook["month"] = df_cook["visit_date"].dt.to_period("M").astype(str)
                monthly_cookie = df_cook.groupby("month").size().reset_index(name="count")
                monthly_cookie = monthly_cookie.tail(12)
                fig = px.bar(monthly_cookie, x="month", y="count", title="Cookie Visits per Month (Last 12)")
                fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                  font_color="#FFFFFF")
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No cookie visit data yet.")

        # Flyer campaign stats
        st.markdown("### Flyer Campaign Summary")
        campaigns = get_flyer_campaigns()
        if campaigns:
            df_camp = pd.DataFrame(campaigns)
            display_cols = ["flyer_name", "sent_date", "sent_count", "failed_count"]
            available = [c for c in display_cols if c in df_camp.columns]
            st.dataframe(df_camp[available], use_container_width=True, hide_index=True)
        else:
            st.info("No flyer campaigns yet.")

    # ── Call & Email Tracking ──────────────────────────────────────────
    with tab_call_email:
        st.markdown("### Call & Email Tracking")

        contacts = get_contact_log(limit=5000)
        if contacts:
            df = pd.DataFrame(contacts)
            df["contact_date"] = pd.to_datetime(df["contact_date"], errors="coerce")
            df = df.dropna(subset=["contact_date"])

            # Contact type breakdown
            type_counts = df["contact_type"].value_counts().reset_index()
            type_counts.columns = ["Type", "Count"]
            fig = px.pie(type_counts, names="Type", values="Count", title="All Contacts by Type")
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="#FFFFFF")
            st.plotly_chart(fig, use_container_width=True)

            # Monthly contacts by type (stacked bar)
            df["month"] = df["contact_date"].dt.to_period("M").astype(str)
            monthly_type = df.groupby(["month", "contact_type"]).size().reset_index(name="count")
            monthly_type = monthly_type[monthly_type["month"] >= (now - timedelta(days=365)).strftime("%Y-%m")]
            if not monthly_type.empty:
                fig = px.bar(monthly_type, x="month", y="count", color="contact_type",
                             title="Monthly Contacts by Type (Last 12 Months)",
                             barmode="stack")
                fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                  font_color="#FFFFFF")
                st.plotly_chart(fig, use_container_width=True)

            # Call outcome breakdown
            phone_calls = df[df["contact_type"] == "Phone Call"]
            if not phone_calls.empty and "outcome" in phone_calls.columns:
                st.markdown("#### Call Outcome Breakdown")
                outcome_counts = phone_calls["outcome"].value_counts().reset_index()
                outcome_counts.columns = ["Outcome", "Count"]
                fig = px.bar(outcome_counts, x="Outcome", y="Count", title="Phone Call Outcomes")
                fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                  font_color="#FFFFFF")
                st.plotly_chart(fig, use_container_width=True)

                # Success rate: calls leading to scheduled lunches
                total_calls = len(phone_calls)
                scheduled_calls = len(phone_calls[phone_calls["outcome"] == "Scheduled lunch"])
                if total_calls > 0:
                    success_rate = round(scheduled_calls / total_calls * 100, 1)
                    st.metric("Call-to-Lunch Success Rate", f"{success_rate}%",
                              delta=f"{scheduled_calls} of {total_calls} calls")

            # Email metrics
            emails = df[df["contact_type"] == "Email Sent"]
            if not emails.empty:
                st.markdown("#### Email Metrics")
                st.metric("Total Emails Sent", len(emails))
                if "outcome" in emails.columns:
                    email_outcomes = emails["outcome"].value_counts().reset_index()
                    email_outcomes.columns = ["Outcome", "Count"]
                    fig = px.bar(email_outcomes, x="Outcome", y="Count", title="Email Outcomes")
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                      font_color="#FFFFFF")
                    st.plotly_chart(fig, use_container_width=True)

            # Fax metrics
            faxes = df[df["contact_type"] == "Fax Sent"]
            if not faxes.empty:
                st.markdown("#### Fax Metrics")
                st.metric("Total Faxes Sent", len(faxes))

            # Team member activity
            if "team_member" in df.columns:
                st.markdown("#### Activity by Team Member")
                team = df["team_member"].value_counts().reset_index()
                team.columns = ["Team Member", "Contacts"]
                fig = px.bar(team, x="Team Member", y="Contacts", title="Contacts by Team Member")
                fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                  font_color="#FFFFFF")
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No contact data yet.")

    # ── Location Comparison ────────────────────────────────────────────
    with tab_location:
        st.markdown("### Location Comparison: Huntsville vs Woodlands vs Other")

        practices = get_all_practices(status_filter="Active")
        providers = get_all_providers()
        lunches = get_lunches()
        cookies = get_cookie_visits()
        contacts = get_contact_log(limit=5000)

        locations = ["Huntsville", "Woodlands", "Other"]
        loc_practices = {loc: [p for p in practices if p.get("location_category") == loc] for loc in locations}
        loc_practice_ids = {loc: {p["id"] for p in ps} for loc, ps in loc_practices.items()}

        comparison = []
        for loc in locations:
            pids = loc_practice_ids[loc]
            loc_providers = [pr for pr in providers if pr.get("practice_id") in pids]
            loc_lunches = [l for l in lunches if l.get("practice_id") in pids]
            loc_completed = [l for l in loc_lunches if l.get("status") == "Completed"]
            loc_cookies_list = [c for c in cookies if c.get("practice_id") in pids]
            loc_contacts = [c for c in contacts if c.get("practice_id") in pids]
            loc_calls = [c for c in loc_contacts if c.get("contact_type") == "Phone Call"]
            loc_emails = [c for c in loc_contacts if c.get("contact_type") == "Email Sent"]

            # Average relationship score
            scores = [relationship_score(p["id"]) for p in loc_practices[loc]]
            avg_score = round(sum(scores) / len(scores), 1) if scores else 0

            comparison.append({
                "Location": loc,
                "Practices": len(loc_practices[loc]),
                "Providers": len(loc_providers),
                "Lunches Completed": len(loc_completed),
                "Lunches Scheduled": len([l for l in loc_lunches if l.get("status") == "Scheduled"]),
                "Cookie Visits": len(loc_cookies_list),
                "Total Contacts": len(loc_contacts),
                "Calls": len(loc_calls),
                "Emails": len(loc_emails),
                "Avg Score": avg_score,
            })

        df_comp = pd.DataFrame(comparison)
        st.dataframe(df_comp, use_container_width=True, hide_index=True)

        # Grouped bar chart
        fig = go.Figure()
        metrics = ["Practices", "Lunches Completed", "Cookie Visits", "Calls", "Emails"]
        for metric in metrics:
            fig.add_trace(go.Bar(name=metric, x=df_comp["Location"], y=df_comp[metric]))
        fig.update_layout(
            barmode="group", title="Location Comparison",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color="#FFFFFF",
        )
        st.plotly_chart(fig, use_container_width=True)

        # Which location needs more attention?
        st.markdown("#### Attention Needed")
        min_score_loc = min(comparison, key=lambda x: x["Avg Score"])
        st.warning(f"**{min_score_loc['Location']}** has the lowest average relationship score "
                   f"({min_score_loc['Avg Score']}/100) and may need more outreach attention.")

    # ── Contact Analysis ───────────────────────────────────────────────
    with tab_contacts:
        st.markdown("### Contact Activity Over Time")

        contacts = get_contact_log(limit=5000)
        if contacts:
            df = pd.DataFrame(contacts)
            df["contact_date"] = pd.to_datetime(df["contact_date"], errors="coerce")
            df = df.dropna(subset=["contact_date"])

            # Monthly contact count
            df["month"] = df["contact_date"].dt.to_period("M").astype(str)
            monthly = df.groupby("month").size().reset_index(name="count")
            fig = px.bar(monthly, x="month", y="count", title="Contacts per Month")
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                              font_color="#FFFFFF")
            st.plotly_chart(fig, use_container_width=True)

            # Contact type breakdown
            type_counts = df["contact_type"].value_counts().reset_index()
            type_counts.columns = ["Type", "Count"]
            fig = px.pie(type_counts, names="Type", values="Count", title="Contact Types")
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="#FFFFFF")
            st.plotly_chart(fig, use_container_width=True)

            # Heatmap: contacts by day of week
            df["day_of_week"] = df["contact_date"].dt.day_name()
            dow_counts = df["day_of_week"].value_counts().reindex(
                ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            ).fillna(0).reset_index()
            dow_counts.columns = ["Day", "Count"]
            fig = px.bar(dow_counts, x="Day", y="Count", title="Contacts by Day of Week")
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                              font_color="#FFFFFF")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No contact data yet. Start logging contacts to see analytics.")

    # ── Export ─────────────────────────────────────────────────────────
    with tab_export:
        st.markdown("### Export Data")

        export_options = st.multiselect(
            "Select data to export",
            [
                "Practices", "Providers", "Contact Log", "Lunches",
                "Cookie Visits", "Thank You Letters", "Flyer Campaigns",
                "Follow-ups", "Monthly Summary",
            ],
            default=["Practices", "Providers"],
        )

        export_format = st.radio("Export Format", ["Excel (.xlsx)", "CSV"], horizontal=True)

        if st.button("Generate Export", type="primary"):
            import io

            if export_format == "Excel (.xlsx)":
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    _write_export_sheets(writer, export_options)
                output.seek(0)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                st.download_button(
                    "Download Excel",
                    data=output,
                    file_name=f"NHCC_Export_{timestamp}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            else:
                # CSV: export each selected option as separate download
                for option in export_options:
                    df = _get_export_df(option)
                    if df is not None and not df.empty:
                        csv_data = df.to_csv(index=False)
                        st.download_button(
                            f"Download {option} CSV",
                            data=csv_data,
                            file_name=f"NHCC_{option.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.csv",
                            mime="text/csv",
                            key=f"csv_{option}",
                        )


def _write_export_sheets(writer, options):
    """Write selected data to Excel sheets."""
    if "Practices" in options:
        pd.DataFrame(get_all_practices()).to_excel(writer, sheet_name="Practices", index=False)
    if "Providers" in options:
        pd.DataFrame(get_all_providers()).to_excel(writer, sheet_name="Providers", index=False)
    if "Contact Log" in options:
        pd.DataFrame(get_contact_log(limit=10000)).to_excel(writer, sheet_name="Contact Log", index=False)
    if "Lunches" in options:
        pd.DataFrame(get_lunches()).to_excel(writer, sheet_name="Lunches", index=False)
    if "Cookie Visits" in options:
        pd.DataFrame(get_cookie_visits()).to_excel(writer, sheet_name="Cookie Visits", index=False)
    if "Thank You Letters" in options:
        pd.DataFrame(get_thank_yous()).to_excel(writer, sheet_name="Thank You Letters", index=False)
    if "Flyer Campaigns" in options:
        pd.DataFrame(get_flyer_campaigns()).to_excel(writer, sheet_name="Flyer Campaigns", index=False)
    if "Follow-ups" in options:
        pd.DataFrame(get_follow_ups()).to_excel(writer, sheet_name="Follow-ups", index=False)
    if "Monthly Summary" in options:
        summary = _build_monthly_summary()
        pd.DataFrame(summary).to_excel(writer, sheet_name="Monthly Summary", index=False)


def _get_export_df(option):
    """Return a DataFrame for a given export option."""
    mapping = {
        "Practices": lambda: pd.DataFrame(get_all_practices()),
        "Providers": lambda: pd.DataFrame(get_all_providers()),
        "Contact Log": lambda: pd.DataFrame(get_contact_log(limit=10000)),
        "Lunches": lambda: pd.DataFrame(get_lunches()),
        "Cookie Visits": lambda: pd.DataFrame(get_cookie_visits()),
        "Thank You Letters": lambda: pd.DataFrame(get_thank_yous()),
        "Flyer Campaigns": lambda: pd.DataFrame(get_flyer_campaigns()),
        "Follow-ups": lambda: pd.DataFrame(get_follow_ups()),
        "Monthly Summary": lambda: pd.DataFrame(_build_monthly_summary()),
    }
    fn = mapping.get(option)
    return fn() if fn else None


def _build_monthly_summary():
    """Build a monthly summary for the last 12 months."""
    rows = []
    now = datetime.now()
    for i in range(12):
        dt = now - timedelta(days=30 * i)
        ym = dt.strftime("%Y-%m")
        rows.append({
            "Month": ym,
            "Contacts": _get_month_count("contact_log", "contact_date", ym),
            "Phone Calls": _get_month_count("contact_log", "contact_date", ym, "contact_type='Phone Call'"),
            "Emails Sent": _get_month_count("contact_log", "contact_date", ym, "contact_type='Email Sent'"),
            "Faxes Sent": _get_month_count("contact_log", "contact_date", ym, "contact_type='Fax Sent'"),
            "Lunches Completed": _get_month_count("lunch_tracking", "completed_date", ym, "status='Completed'"),
            "Cookie Visits": _get_month_count("cookie_visits", "visit_date", ym),
        })
    rows.reverse()
    return rows
