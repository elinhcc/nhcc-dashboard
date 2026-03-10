"""Main dashboard page with provider cards, stats, and overview."""
import streamlit as st
from utils import db_exists


@st.cache_data(ttl=60)
def _cached_tasks(is_complete, assigned_to=None):
    from database import get_tasks
    if assigned_to:
        return get_tasks(is_complete=is_complete, assigned_to=assigned_to)
    return get_tasks(is_complete=is_complete)


@st.cache_data(ttl=60)
def _cached_contact_queue_data():
    from database import get_contact_queue_data
    return get_contact_queue_data()


@st.cache_data(ttl=60)
def _cached_dashboard_stats():
    from database import get_dashboard_stats
    return get_dashboard_stats()


@st.cache_data(ttl=300)
def _cached_practices(status_filter=None):
    from database import get_all_practices
    return get_all_practices(status_filter=status_filter)


@st.cache_data(ttl=300)
def _cached_providers_by_practice():
    from database import get_all_providers_by_practice
    return get_all_providers_by_practice()


@st.cache_data(ttl=120)
def _cached_relationship_bulk():
    from database import get_relationship_bulk_data
    return get_relationship_bulk_data()


@st.cache_data(ttl=120)
def _cached_overdue_items():
    from utils import get_overdue_items
    return get_overdue_items()


def show_dashboard():
    st.markdown("## Provider Outreach Dashboard")

    # ── Morning summary card ───────────────────────────────────────────
    try:
        if db_exists():
            from datetime import date, datetime

            user_dict = st.session_state.get("user", {})
            username  = user_dict.get("username", "")
            full_name = user_dict.get("full_name", "") or username
            is_admin  = user_dict.get("role") == "admin"
            hour      = datetime.now().hour
            greeting  = "Good morning" if hour < 12 else ("Good afternoon" if hour < 17 else "Good evening")
            name      = full_name.split()[0] if full_name else "there"

            today_str = date.today().isoformat()

            # 1 call for tasks instead of filtering after fetch
            if is_admin:
                open_tasks = _cached_tasks(is_complete=False)
            else:
                open_tasks = _cached_tasks(is_complete=False, assigned_to=username)

            overdue_count = sum(
                1 for t in open_tasks
                if t.get("due_date") and t["due_date"] < today_str
            )
            today_count = sum(1 for t in open_tasks if t.get("due_date") == today_str)

            # Bulk contact queue data: 3 calls total instead of 275×3
            practices_cq, last_contact_by_pid, lunch_active_pids, phone_count_by_pid = _cached_contact_queue_data()
            queue_count = sum(
                1 for p in practices_cq
                if last_contact_by_pid.get(p["id"])
                and p["id"] not in lunch_active_pids
                and phone_count_by_pid.get(p["id"], 0) > 0
            )

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
        from utils import score_color, score_label, format_phone_link, relationship_score_from_bulk

        # Top stats row — single cached call
        stats = _cached_dashboard_stats()
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Active Practices", stats["total_practices"])
        c2.metric("Active Providers", stats["total_providers"])
        c3.metric("Contacts This Month", stats["contacts_this_month"])
        c4.metric("Lunches Scheduled", stats["lunches_scheduled"])
        c5.metric("Pending Thank Yous", stats["pending_thank_yous"])
        c6.metric("Flyers Sent (Month)", stats["flyers_sent_this_month"])

        # Cookie visit metrics
        c7, c8, c9, c10, c11 = st.columns([1, 1, 1, 1, 1])
        with c7:
            st.metric("Cookie Visits (Month)", stats.get("cookie_visits_this_month", 0))
        with c8:
            st.metric("Cookie Visits (Total)", stats.get("cookie_visits_total", 0))
        with c9:
            tasks_due = stats.get("tasks_due_today", 0)
            st.metric("Tasks Due Today", tasks_due)
        with c10:
            tasks_ovr = stats.get("tasks_overdue", 0)
            st.metric("Overdue Tasks", tasks_ovr)
        with c11:
            needs_attn = stats.get("needs_attention", 0)
            st.metric("Needs Attention", needs_attn)

        st.markdown("---")

        # Overdue items alert — uses bulk queries internally
        try:
            overdue = _cached_overdue_items()
            high_priority = [i for i in overdue if i.get("priority") == "high"]
            if high_priority:
                with st.expander(f"Warning: {len(high_priority)} High Priority Items", expanded=True):
                    for item in high_priority[:5]:
                        st.warning(f"**{item['type']}** - {item['practice']}: {item['detail']}")
        except Exception:
            pass

        # Load bulk data once for all provider cards — 3 calls total
        contacts_by_pid, lunches_by_pid, cookies_by_pid = _cached_relationship_bulk()
        providers_by_practice = _cached_providers_by_practice()

        # Location tabs — load practices ONCE (not 3 times)
        practices = _cached_practices(status_filter="Active")
        tab_h, tab_w, tab_o = st.tabs([
            f"Huntsville ({stats['huntsville_practices']})",
            f"Woodlands ({stats['woodlands_practices']})",
            f"Other ({stats['total_practices'] - stats['huntsville_practices'] - stats['woodlands_practices']})",
        ])

        for tab, category in [(tab_h, "Huntsville"), (tab_w, "Woodlands"), (tab_o, "Other")]:
            with tab:
                filtered = [p for p in practices if p.get("location_category") == category]

                if not filtered:
                    st.info(f"No {category} practices found.")
                    continue

                # Search within tab
                search = st.text_input(f"Search {category} practices", key=f"search_{category}")
                if search:
                    search_lower = search.lower()
                    filtered = [p for p in filtered if search_lower in p["name"].lower() or search_lower in (p.get("address") or "").lower()]

                # Provider cards grid — no per-practice DB calls
                cols = st.columns(3)
                for i, practice in enumerate(filtered):
                    with cols[i % 3]:
                        score = relationship_score_from_bulk(
                            practice["id"], contacts_by_pid, lunches_by_pid, cookies_by_pid
                        )
                        color = score_color(score)
                        label = score_label(score)
                        providers = providers_by_practice.get(practice["id"], [])

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
