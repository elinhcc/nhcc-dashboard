"""NHCC Provider Outreach & Relationship Management Dashboard - Main Entry Point."""
import streamlit as st
import os
import sys

# Ensure app directory is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import init_db
from data_import import get_import_status
from utils import load_config

st.set_page_config(
    page_title="NHCC Provider Outreach",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state initialization (MUST be before any widgets) ─────────
st.session_state.setdefault("authenticated", False)
st.session_state.setdefault("active_contact_form", None)   # practice_id or None
st.session_state.setdefault("active_lunch_form", None)      # practice_id or None
st.session_state.setdefault("show_contact_success", None)   # message or None
st.session_state.setdefault("show_lunch_success", None)     # message or None
st.session_state.setdefault("active_event_date", None)
st.session_state.setdefault("active_event_id", None)

# Custom CSS
st.markdown("""
<style>
    .main .block-container { padding-top: 1rem; }
    .stMetric { background: #f8f9fa; padding: 10px; border-radius: 8px; }
    div[data-testid="stMetric"] { background: #f0f2f6; padding: 12px; border-radius: 8px; }
    .score-high { color: #28a745; font-weight: bold; }
    .score-med { color: #ffc107; font-weight: bold; }
    .score-low { color: #dc3545; font-weight: bold; }
    section[data-testid="stSidebar"] { background: #1a1a2e; }
    section[data-testid="stSidebar"] .stMarkdown { color: white; }
    section[data-testid="stSidebar"] * { color: #fff !important; }
    .st-bf { color: #fff !important; }
    .stButton>button { color: #fff !important; }
    .css-1v3fvcr { color: #fff !important; }
</style>
""", unsafe_allow_html=True)


def check_login():
    """Simple password login."""
    if st.session_state.authenticated:
        return True

    st.markdown("## 🏥 NHCC Provider Outreach Dashboard")
    st.markdown("---")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("### Login")
        password = st.text_input("Password", type="password", key="login_pw")
        if st.button("Login", use_container_width=True):
            config = load_config()
            stored_hash = config.get("app_password_hash", "")
            if not stored_hash:
                # No password set yet - first run, accept anything or set default
                st.session_state.authenticated = True
                st.rerun()
            else:
                import bcrypt
                if bcrypt.checkpw(password.encode(), stored_hash.encode()):
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Incorrect password")
        if not load_config().get("app_password_hash"):
            st.info("No password set. Click Login to enter. Set a password in Settings.")
    return st.session_state.authenticated


def main():
    # Initialize database
    init_db()

    if not check_login():
        return

    # Sidebar navigation
    with st.sidebar:
        st.markdown("## 🏥 NHCC Outreach")
        st.markdown("---")

        page = st.radio(
            "Navigation",
            [
                "📊 Dashboard",
                "🏢 Providers",
                "📋 Action Items",
                "📅 Calendar",
                "📨 Flyer Campaigns",
                "📈 Analytics",
                "⚙️ Settings",
            ],
            label_visibility="collapsed",
        )

        st.markdown("---")

        # Quick stats in sidebar
        if get_import_status():
            from database import get_dashboard_stats
            stats = get_dashboard_stats()
            st.metric("Active Practices", stats["total_practices"])
            st.metric("Pending Thank Yous", stats["pending_thank_yous"])

        st.markdown("---")
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.authenticated = False
            st.rerun()

    # ── Sidebar forms for Contact Log / Lunch Scheduling ────────────
    from pages.providers import render_sidebar_contact_form, render_sidebar_lunch_form

    # Route to page
    if not get_import_status():
        show_import_page()
    elif page == "📊 Dashboard":
        from pages.dashboard import show_dashboard
        show_dashboard()
    elif page == "🏢 Providers":
        from pages.providers import show_providers
        show_providers()
    elif page == "📋 Action Items":
        from pages.action_items import show_action_items
        show_action_items()
    elif page == "📅 Calendar":
        from pages.calendar_view import show_calendar
        show_calendar()
    elif page == "📨 Flyer Campaigns":
        from pages.flyer_campaigns import show_flyer_campaigns
        show_flyer_campaigns()
    elif page == "📈 Analytics":
        from pages.analytics import show_analytics
        show_analytics()
    elif page == "⚙️ Settings":
        from pages.settings import show_settings
        show_settings()

    # Render any modal forms (contact / lunch) if active (modals overlay main)
    render_sidebar_contact_form()
    render_sidebar_lunch_form()


def show_import_page():
    """Show the initial data import page."""
    st.markdown("## 📥 Initial Data Import")
    st.markdown("Welcome! Let's import your provider data from Excel to get started.")

    config = load_config()
    excel_path = config["excel_path"]

    if os.path.exists(excel_path):
        st.success(f"Found Excel file: `{os.path.basename(excel_path)}`")

        if st.button("🚀 Import Provider Data", type="primary", use_container_width=True):
            with st.spinner("Importing data... This may take a moment."):
                from data_import import import_excel
                stats = import_excel(excel_path)

            st.balloons()
            st.success("Import complete!")
            col1, col2, col3 = st.columns(3)
            col1.metric("Practices Imported", stats["practices_imported"])
            col2.metric("Providers Imported", stats["providers_imported"])
            col3.metric("Fax Numbers Found", stats["fax_numbers_found"])

            if stats["backup_path"]:
                st.info(f"Backup saved to: `{stats['backup_path']}`")

            st.markdown("---")
            if st.button("Continue to Dashboard →"):
                st.rerun()
    else:
        st.error(f"Excel file not found at: `{excel_path}`")
        st.info("Update the path in Settings or place the file in the expected location.")


if __name__ == "__main__":
    main()
