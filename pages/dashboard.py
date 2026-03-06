"""Main dashboard page with provider cards, stats, and overview."""
import streamlit as st
from utils import db_exists


def show_dashboard():
    st.markdown("## Provider Outreach Dashboard")

    # ── Morning summary card ───────────────────────────────────────────
    try:
        if db_exists():
            from database import get_tasks, get_all_practices, get_contact_log, get_lunches, get_call_attempt_count
            from datetime import date, timedelta

            current_user = st.session_state.get("current_user", "") or "Admin"
            is_admin = current_user == "Admin"
            hour = __import__("datetime").datetime.now().hour
            greeting = "Good morning" if hour < 12 else ("Good afternoon" if hour < 17 else "Good evening")
            name = current_user if not is_admin else "there"

            today_str   = date.today().isoformat()
            in_3_days   = (date.today() + timedelta(days=3)).isoformat()

            tasks = get_tasks() if is_admin else get_tasks(assigned_to=current_user)
            open_tasks = [t for t in tasks if t.get("status") != "done"]
            overdue_count = sum(
                1 for t in open_tasks
                if t.get("due_date") and t["due_date"] < today_str
            )
            today_count = sum(1 for t in open_tasks if t.get("due_date") == today_str)

            # Count practices in contact queue (attempted but no lunch)
            practices = get_all_practices(status_filter="Active")
            queue_count = 0
            for p in practices:
                contacts   = get_contact_log(practice_id=p["id"], limit=1)
                lunches    = get_lunches(practice_id=p["id"])
                call_count = get_call_attempt_count(p["id"])
                has_lunch  = any(l.get("status") in ("Scheduled", "Completed") for l in lunches)
                if contacts and not has_lunch and call_count > 0:
                    queue_count += 1

            with st.container(border=True):
                st.markdown(f"**{greeting} {name}! Here's your day:**")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Overdue Tasks",    overdue_count)
                c2.metric("Due Today",        today_count)
                c3.metric("Awaiting Contact", queue_count)
                c4.metric("Open Tasks",       len(open_tasks))
                if st.button("Go to My Daily Work →", type="primary"):
                    st.session_state["_nav_override"] = "My Daily Work"
                    st.rerun()
    except Exception:
        pass

    # Check if database has data
    if not db_exists():
        st.warning("No data loaded yet.")
        st.info("Go to **Settings > Data Import** to upload your provider Excel file and get started.")

        # Show empty metrics as placeholder
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Active Practices", 0)
        c2.metric("Active Providers", 0)
        c3.metric("Contacts This Month", 0)
        c4.metric("Lunches Scheduled", 0)
        c5.metric("Pending Thank Yous", 0)
        c6.metric("Flyers Sent (Month)", 0)
        return

    try:
        from database import get_dashboard_stats, get_all_practices, get_providers_for_practice
        from utils import relationship_score, score_color, score_label, get_overdue_items, format_phone_link

        # Top stats row
        stats = get_dashboard_stats()
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Active Practices", stats["total_practices"])
        c2.metric("Active Providers", stats["total_providers"])
        c3.metric("Contacts This Month", stats["contacts_this_month"])
        c4.metric("Lunches Scheduled", stats["lunches_scheduled"])
        c5.metric("Pending Thank Yous", stats["pending_thank_yous"])
        c6.metric("Flyers Sent (Month)", stats["flyers_sent_this_month"])

        # Cookie visit metrics
        c7, c8 = st.columns([1, 5])
        with c7:
            st.metric("Cookie Visits (Month)", stats.get("cookie_visits_this_month", 0))
        with c8:
            st.metric("Cookie Visits (Total)", stats.get("cookie_visits_total", 0))

        st.markdown("---")

        # Overdue items alert
        try:
            overdue = get_overdue_items()
            high_priority = [i for i in overdue if i.get("priority") == "high"]
            if high_priority:
                with st.expander(f"Warning: {len(high_priority)} High Priority Items", expanded=True):
                    for item in high_priority[:5]:
                        st.warning(f"**{item['type']}** - {item['practice']}: {item['detail']}")
        except Exception:
            pass

        # Location tabs
        tab_h, tab_w, tab_o = st.tabs([
            f"Huntsville ({stats['huntsville_practices']})",
            f"Woodlands ({stats['woodlands_practices']})",
            f"Other ({stats['total_practices'] - stats['huntsville_practices'] - stats['woodlands_practices']})",
        ])

        for tab, category in [(tab_h, "Huntsville"), (tab_w, "Woodlands"), (tab_o, "Other")]:
            with tab:
                practices = get_all_practices(status_filter="Active")
                filtered = [p for p in practices if p.get("location_category") == category]

                if not filtered:
                    st.info(f"No {category} practices found.")
                    continue

                # Search within tab
                search = st.text_input(f"Search {category} practices", key=f"search_{category}")
                if search:
                    search_lower = search.lower()
                    filtered = [p for p in filtered if search_lower in p["name"].lower() or search_lower in (p.get("address") or "").lower()]

                # Provider cards grid
                cols = st.columns(3)
                for i, practice in enumerate(filtered):
                    with cols[i % 3]:
                        score = relationship_score(practice["id"])
                        color = score_color(score)
                        label = score_label(score)
                        providers = get_providers_for_practice(practice["id"])

                        phone_html = format_phone_link(practice.get('phone', ''))
                        st.markdown(f"""
                        <div class="provider-card" style="border-left-color: {color};">
                            <strong>{practice['name']}</strong><br>
                            <small>{practice.get('address', '')[:60]}</small><br>
                            <span style="color: {color};">● {label} ({score}/100)</span><br>
                            <small>Providers: {len(providers)} | {phone_html} | Fax: {'Yes' if practice.get('fax') else 'No'}</small>
                        </div>
                        """, unsafe_allow_html=True)

    except Exception as e:
        st.error(f"Error loading dashboard: {e}")
        st.info("Go to **Settings > Data Import** to re-import your data.")
