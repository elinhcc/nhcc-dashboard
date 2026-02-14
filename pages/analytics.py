"""Analytics page: charts, reports, exports."""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from database import (
    get_all_practices, get_all_providers, get_contact_log,
    get_lunches, get_cookie_visits, get_flyer_campaigns,
    get_thank_yous, get_dashboard_stats, get_connection,
)
from utils import relationship_score, score_label


def show_analytics():
    st.markdown("## 📈 Analytics & Reports")

    tab_overview, tab_contacts, tab_lunches, tab_export = st.tabs([
        "Overview", "Contact Analysis", "Lunch & Outreach", "Export Data",
    ])

    # ── Overview ───────────────────────────────────────────────────────
    with tab_overview:
        stats = get_dashboard_stats()

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Active Practices", stats["total_practices"])
        col2.metric("Total Active Providers", stats["total_providers"])
        col3.metric("Contacts This Month", stats["contacts_this_month"])
        col4.metric("Flyers Sent (Month)", stats["flyers_sent_this_month"])

        # Location distribution
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
            st.plotly_chart(fig, use_container_width=True)

        # Relationship score distribution
        st.markdown("### Relationship Score Distribution")
        if practices:
            scores = []
            for p in practices:
                s = relationship_score(p["id"])
                scores.append({"Practice": p["name"], "Score": s, "Status": score_label(s)})

            df_scores = pd.DataFrame(scores)
            fig = px.histogram(
                df_scores, x="Score", nbins=10,
                title="Relationship Score Distribution",
                color="Status",
                color_discrete_map={"Strong": "#28a745", "Moderate": "#ffc107", "Needs Attention": "#dc3545"},
            )
            st.plotly_chart(fig, use_container_width=True)

            # Top and bottom practices
            df_scores = df_scores.sort_values("Score", ascending=False)
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("#### 🏆 Top 10 Practices")
                st.dataframe(df_scores.head(10)[["Practice", "Score", "Status"]], hide_index=True)
            with col2:
                st.markdown("#### ⚠️ Bottom 10 (Needs Attention)")
                st.dataframe(df_scores.tail(10)[["Practice", "Score", "Status"]], hide_index=True)

    # ── Contact Analysis ───────────────────────────────────────────────
    with tab_contacts:
        st.markdown("### Contact Activity Over Time")

        contacts = get_contact_log(limit=1000)
        if contacts:
            df = pd.DataFrame(contacts)
            df["contact_date"] = pd.to_datetime(df["contact_date"], errors="coerce")
            df = df.dropna(subset=["contact_date"])

            # Monthly contact count
            df["month"] = df["contact_date"].dt.to_period("M").astype(str)
            monthly = df.groupby("month").size().reset_index(name="count")
            fig = px.bar(monthly, x="month", y="count", title="Contacts per Month")
            st.plotly_chart(fig, use_container_width=True)

            # Contact type breakdown
            type_counts = df["contact_type"].value_counts().reset_index()
            type_counts.columns = ["Type", "Count"]
            fig = px.pie(type_counts, names="Type", values="Count", title="Contact Types")
            st.plotly_chart(fig, use_container_width=True)

            # Team member activity
            if "team_member" in df.columns:
                team = df["team_member"].value_counts().reset_index()
                team.columns = ["Team Member", "Contacts"]
                fig = px.bar(team, x="Team Member", y="Contacts", title="Activity by Team Member")
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No contact data yet. Start logging contacts to see analytics.")

    # ── Lunch & Outreach ───────────────────────────────────────────────
    with tab_lunches:
        st.markdown("### Lunch Status Summary")
        lunches = get_lunches()
        if lunches:
            df_lunch = pd.DataFrame(lunches)
            status_counts = df_lunch["status"].value_counts().reset_index()
            status_counts.columns = ["Status", "Count"]
            fig = px.pie(
                status_counts, names="Status", values="Count",
                title="Lunch Status Breakdown",
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            st.plotly_chart(fig, use_container_width=True)

            # Lunch timeline
            completed = df_lunch[df_lunch["status"] == "Completed"]
            if not completed.empty and "completed_date" in completed.columns:
                completed["completed_date"] = pd.to_datetime(completed["completed_date"], errors="coerce")
                completed = completed.dropna(subset=["completed_date"])
                if not completed.empty:
                    completed["month"] = completed["completed_date"].dt.to_period("M").astype(str)
                    monthly_lunch = completed.groupby("month").size().reset_index(name="count")
                    fig = px.bar(monthly_lunch, x="month", y="count", title="Completed Lunches per Month")
                    st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No lunch data yet.")

        # Cookie visits
        st.markdown("### Cookie Visit Frequency")
        cookies = get_cookie_visits()
        if cookies:
            df_cook = pd.DataFrame(cookies)
            df_cook["visit_date"] = pd.to_datetime(df_cook["visit_date"], errors="coerce")
            df_cook = df_cook.dropna(subset=["visit_date"])
            if not df_cook.empty:
                df_cook["month"] = df_cook["visit_date"].dt.to_period("M").astype(str)
                monthly_cookie = df_cook.groupby("month").size().reset_index(name="count")
                fig = px.bar(monthly_cookie, x="month", y="count", title="Cookie Visits per Month")
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No cookie visit data yet.")

        # Overdue follow-ups (Lunches and Cookies)
        st.markdown("### Overdue Follow-ups")
        from datetime import date
        overdue_items = []
        if lunches:
            for l in lunches:
                sd = (l.get('scheduled_date') or '')[:10]
                try:
                    if sd and datetime.strptime(sd, '%Y-%m-%d').date() < date.today() and l.get('status') != 'Completed':
                        overdue_items.append({'practice': l.get('practice_name'), 'type': 'Lunch', 'date': sd})
                except Exception:
                    continue
        cookies = get_cookie_visits()
        if cookies:
            for c in cookies:
                vd = (c.get('visit_date') or '')[:10]
                try:
                    if vd and datetime.strptime(vd, '%Y-%m-%d').date() < date.today():
                        overdue_items.append({'practice': c.get('practice_name'), 'type': 'Cookie Visit', 'date': vd})
                except Exception:
                    continue

        if overdue_items:
            import pandas as pd
            df_over = pd.DataFrame(overdue_items)
            st.dataframe(df_over, use_container_width=True, hide_index=True)
        else:
            st.info("No overdue follow-ups for Lunches or Cookie Visits.")

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

    # ── Export ─────────────────────────────────────────────────────────
    with tab_export:
        st.markdown("### Export Data to Excel")

        export_options = st.multiselect(
            "Select data to export",
            ["Practices", "Providers", "Contact Log", "Lunches", "Cookie Visits", "Thank You Letters", "Flyer Campaigns"],
            default=["Practices", "Providers"],
        )

        if st.button("📥 Generate Export", type="primary"):
            import io
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                if "Practices" in export_options:
                    practices = get_all_practices()
                    pd.DataFrame(practices).to_excel(writer, sheet_name="Practices", index=False)

                if "Providers" in export_options:
                    providers = get_all_providers()
                    pd.DataFrame(providers).to_excel(writer, sheet_name="Providers", index=False)

                if "Contact Log" in export_options:
                    contacts = get_contact_log(limit=5000)
                    pd.DataFrame(contacts).to_excel(writer, sheet_name="Contact Log", index=False)

                if "Lunches" in export_options:
                    lunches = get_lunches()
                    pd.DataFrame(lunches).to_excel(writer, sheet_name="Lunches", index=False)

                if "Cookie Visits" in export_options:
                    cookies = get_cookie_visits()
                    pd.DataFrame(cookies).to_excel(writer, sheet_name="Cookie Visits", index=False)

                if "Thank You Letters" in export_options:
                    tys = get_thank_yous()
                    pd.DataFrame(tys).to_excel(writer, sheet_name="Thank You Letters", index=False)

                if "Flyer Campaigns" in export_options:
                    camps = get_flyer_campaigns()
                    pd.DataFrame(camps).to_excel(writer, sheet_name="Flyer Campaigns", index=False)

            output.seek(0)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.download_button(
                "📥 Download Excel",
                data=output,
                file_name=f"NHCC_Outreach_Export_{timestamp}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
