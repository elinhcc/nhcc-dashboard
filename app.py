"""NHCC Provider Outreach & Relationship Management Dashboard - Main Entry Point."""
import streamlit as st
import os
import sys

# Ensure app directory is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import init_db, db_exists
from data_import import get_import_status
from utils import load_config, is_cloud

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
st.session_state.setdefault("active_fax_form", None)       # practice_id or None
st.session_state.setdefault("contact_type_default", None)   # e.g. "Email Sent"

# Custom CSS — ensures text is always readable on all backgrounds
st.markdown("""
<style>
    /* ── Main layout ─────────────────────────────────────── */
    .main .block-container { padding-top: 1rem; }

    /* ── Global text: white on dark theme backgrounds ───── */
    .main, .main .block-container,
    .main .stMarkdown, .main .stMarkdown p,
    .main .stMarkdown h1, .main .stMarkdown h2,
    .main .stMarkdown h3, .main .stMarkdown h4,
    .main .stMarkdown li, .main .stMarkdown span,
    .main label, .main .stCaption, .main caption,
    .main .stAlert p {
        color: #FFFFFF !important;
    }

    /* ── Metrics ──────────────────────────────────────────── */
    div[data-testid="stMetric"] {
        background: #1e1e2f;
        padding: 12px;
        border-radius: 8px;
        border: 1px solid #333;
    }
    div[data-testid="stMetric"] label,
    div[data-testid="stMetric"] div {
        color: #FFFFFF !important;
    }

    /* ── Score colors ─────────────────────────────────────── */
    .score-high { color: #28a745; font-weight: bold; }
    .score-med  { color: #ffc107; font-weight: bold; }
    .score-low  { color: #dc3545; font-weight: bold; }

    /* ── Sidebar: dark background, white text ─────────────── */
    section[data-testid="stSidebar"] { background: #1a1a2e; }
    section[data-testid="stSidebar"] * { color: #FFFFFF !important; }
    section[data-testid="stSidebar"] .stMarkdown,
    section[data-testid="stSidebar"] .stMarkdown p,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] span {
        color: #FFFFFF !important;
    }

    /* ── Buttons: white text ──────────────────────────────── */
    .stButton > button {
        color: #FFFFFF !important;
    }

    /* ── Form labels & inputs ─────────────────────────────── */
    .stTextInput label, .stTextArea label,
    .stSelectbox label, .stDateInput label,
    .stTimeInput label, .stNumberInput label,
    .stRadio label, .stCheckbox label,
    .stMultiSelect label {
        color: #FFFFFF !important;
    }

    /* ── Expander headers ─────────────────────────────────── */
    .streamlit-expanderHeader, .streamlit-expanderHeader p {
        color: #FFFFFF !important;
    }

    /* ── Tabs ─────────────────────────────────────────────── */
    .stTabs [data-baseweb="tab"] {
        color: #FFFFFF !important;
    }

    /* ── Table / dataframe text ────────────────────────────── */
    .stDataFrame, .stDataFrame td, .stDataFrame th,
    .stTable td, .stTable th {
        color: #FFFFFF !important;
    }

    /* ── Success / error / info / warning messages ─────────── */
    .stAlert p, .stAlert span, .stAlert div {
        color: #1a1a2e !important;
    }

    /* ── Modal / dialog popups: LIGHT background, DARK text ─ */
    div[data-testid="stDialog"],
    div[data-testid="stModal"],
    div[role="dialog"] {
        background: #FFFFFF !important;
        border-radius: 12px;
    }
    div[data-testid="stDialog"] *,
    div[data-testid="stModal"] *,
    div[role="dialog"] * {
        color: #1a1a1a !important;
    }
    div[data-testid="stDialog"] .stButton > button,
    div[data-testid="stModal"] .stButton > button,
    div[role="dialog"] .stButton > button {
        color: #FFFFFF !important;
        background-color: #4CAF50;
    }
    div[data-testid="stDialog"] .stMarkdown h1,
    div[data-testid="stDialog"] .stMarkdown h2,
    div[data-testid="stDialog"] .stMarkdown h3,
    div[data-testid="stModal"] .stMarkdown h1,
    div[data-testid="stModal"] .stMarkdown h2,
    div[data-testid="stModal"] .stMarkdown h3,
    div[role="dialog"] .stMarkdown h1,
    div[role="dialog"] .stMarkdown h2,
    div[role="dialog"] .stMarkdown h3 {
        color: #1a1a1a !important;
    }
    div[data-testid="stDialog"] label,
    div[data-testid="stModal"] label,
    div[role="dialog"] label {
        color: #333333 !important;
    }

    /* ── Input fields: white bg, black text for readability ────── */
    .main input, .main textarea, .main select,
    .stTextInput input, .stTextArea textarea,
    .stSelectbox select, .stDateInput input,
    .stTimeInput input, .stNumberInput input,
    div[data-baseweb="input"] input,
    div[data-baseweb="textarea"] textarea,
    div[data-baseweb="select"] > div {
        background-color: #FFFFFF !important;
        color: #000000 !important;
    }
    /* Select dropdown text */
    div[data-baseweb="select"] span,
    div[data-baseweb="select"] div[class*="value"] {
        color: #000000 !important;
    }

    /* ── Clickable contact methods ──────────────────────────────── */
    a.contact-phone {
        color: #4A9EFF !important;
        text-decoration: none;
        cursor: pointer;
    }
    a.contact-phone:hover { text-decoration: underline; }

    a.contact-email {
        color: #50C878 !important;
        text-decoration: none;
        cursor: pointer;
    }
    a.contact-email:hover { text-decoration: underline; }

    a.contact-fax {
        color: #FF8C42 !important;
        text-decoration: none;
        cursor: pointer;
    }
    a.contact-fax:hover { text-decoration: underline; }

    /* ── Calendar event cells: ensure text readable on colors ── */
    .cal-event-blue  { color: #FFFFFF; background: #007bff; padding: 2px 4px; border-radius: 3px; display: inline-block; margin: 1px 0; font-size: 0.8em; }
    .cal-event-green { color: #FFFFFF; background: #28a745; padding: 2px 4px; border-radius: 3px; display: inline-block; margin: 1px 0; font-size: 0.8em; }
    .cal-event-yellow { color: #000000; background: #ffc107; padding: 2px 4px; border-radius: 3px; display: inline-block; margin: 1px 0; font-size: 0.8em; }
    .cal-event-pink  { color: #FFFFFF; background: #e83e8c; padding: 2px 4px; border-radius: 3px; display: inline-block; margin: 1px 0; font-size: 0.8em; }
    .cal-event-gray  { color: #FFFFFF; background: #6c757d; padding: 2px 4px; border-radius: 3px; display: inline-block; margin: 1px 0; font-size: 0.8em; }
    .cal-event-orange { color: #FFFFFF; background: #FF8C42; padding: 2px 4px; border-radius: 3px; display: inline-block; margin: 1px 0; font-size: 0.8em; }

    /* ── Provider card on dark bg ───────────────────────────────── */
    .provider-card {
        border-left-width: 4px;
        border-left-style: solid;
        padding: 12px;
        margin-bottom: 12px;
        background: #1e1e2f;
        border-radius: 4px;
    }
    .provider-card strong { color: #FFFFFF; }
    .provider-card small { color: #ccc; }
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
    # Initialize database (safe — creates schema if DB doesn't exist yet)
    try:
        init_db()
    except Exception:
        pass  # DB will be created when user uploads data

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
        try:
            if db_exists():
                from database import get_dashboard_stats
                stats = get_dashboard_stats()
                st.metric("Active Practices", stats["total_practices"])
                st.metric("Pending Thank Yous", stats["pending_thank_yous"])
            else:
                st.caption("No data loaded yet")
        except Exception:
            st.caption("No data loaded yet")

        st.markdown("---")
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.authenticated = False
            st.rerun()

    # Route to page — always allow navigation, pages handle empty state
    if page == "📊 Dashboard":
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

    # Render modal dialogs for contact/lunch/fax forms if active
    try:
        from pages.providers import render_contact_modal, render_lunch_modal, render_fax_modal
        render_contact_modal()
        render_lunch_modal()
        render_fax_modal()
    except Exception:
        pass


def show_import_page():
    """Show the initial data import page — supports both local files and browser uploads."""
    st.markdown("## 📥 Initial Data Import")
    st.markdown("Welcome! Let's import your provider data from Excel to get started.")

    config = load_config()
    excel_path = config.get("excel_path", "")

    # Option 1: Upload via browser (works on cloud and local)
    st.markdown("### Upload Excel File")
    uploaded_file = st.file_uploader(
        "Upload your provider Excel file (.xlsx / .xls)",
        type=["xlsx", "xls"],
        key="import_upload",
    )
    if uploaded_file is not None:
        if st.button("🚀 Import Uploaded File", type="primary", use_container_width=True):
            import tempfile
            with st.spinner("Importing data... This may take a moment."):
                # Save uploaded file to temp location
                with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                    tmp.write(uploaded_file.getvalue())
                    tmp_path = tmp.name
                try:
                    init_db()
                    from data_import import import_excel
                    stats = import_excel(tmp_path)
                finally:
                    os.unlink(tmp_path)

            st.balloons()
            st.success("Import complete!")
            col1, col2, col3 = st.columns(3)
            col1.metric("Practices Imported", stats["practices_imported"])
            col2.metric("Providers Imported", stats["providers_imported"])
            col3.metric("Fax Numbers Found", stats["fax_numbers_found"])

            st.markdown("---")
            if st.button("Continue to Dashboard →"):
                st.rerun()
        return

    # Option 2: Local file path (works on local/desktop only)
    if excel_path and os.path.exists(excel_path):
        st.markdown("### Or Import from Local File")
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

            if stats.get("backup_path"):
                st.info(f"Backup saved to: `{stats['backup_path']}`")

            st.markdown("---")
            if st.button("Continue to Dashboard →"):
                st.rerun()
    elif not uploaded_file:
        st.info("Upload an Excel file above, or go to **Settings** to configure a local file path.")


if __name__ == "__main__":
    main()
