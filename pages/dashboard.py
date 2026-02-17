"""Main dashboard page with provider cards, stats, and overview."""
import streamlit as st
from utils import db_exists


def show_dashboard():
    st.markdown("## Provider Outreach Dashboard")

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
