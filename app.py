"""NHCC Provider Outreach & Relationship Management Dashboard - Main Entry Point."""
import streamlit as st
import os
import sys

# set_page_config MUST be the first Streamlit call — keep it before other imports
# so that if any import below fails, Streamlit can still render an error page
# instead of showing the blank "Oh no. Error running app." screen.
st.set_page_config(
    page_title="NHCC Provider Outreach",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Ensure app directory is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Wrap non-stdlib imports so any failure is shown in the browser, not "Oh no"
_startup_error = None
try:
    from database import init_db, db_exists
    from data_import import get_import_status
    from utils import load_config, is_cloud
except Exception:
    import traceback as _tb
    _startup_error = _tb.format_exc()

# ── Session state initialization (MUST be before any widgets) ─────────
st.session_state.setdefault("user", None)                   # logged-in user dict or None
st.session_state.setdefault("active_contact_form", None)   # practice_id or None
st.session_state.setdefault("active_lunch_form", None)      # practice_id or None
st.session_state.setdefault("show_contact_success", None)   # message or None
st.session_state.setdefault("show_lunch_success", None)     # message or None
st.session_state.setdefault("active_event_date", None)
st.session_state.setdefault("active_event_id", None)
st.session_state.setdefault("active_fax_form", None)       # practice_id or None
st.session_state.setdefault("contact_type_default", None)   # e.g. "Email Sent"

# Custom CSS — light clinical theme
st.markdown("""
<style>
    /* ── Main layout ─────────────────────────────────────── */
    .main .block-container { padding-top: 1rem; }

    /* ── Global text: dark on light background ───────────── */
    .main, .main .block-container,
    .main .stMarkdown, .main .stMarkdown p,
    .main .stMarkdown h1, .main .stMarkdown h2,
    .main .stMarkdown h3, .main .stMarkdown h4,
    .main .stMarkdown li, .main .stMarkdown span,
    .main label, .main .stCaption, .main caption,
    .main .stAlert p {
        color: #1E293B !important;
    }

    /* ── Metrics ──────────────────────────────────────────── */
    div[data-testid="stMetric"] {
        background: #FFFFFF;
        padding: 12px;
        border-radius: 8px;
        border: 1px solid #E2E8F0;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    div[data-testid="stMetric"] label,
    div[data-testid="stMetric"] div {
        color: #1E293B !important;
    }

    /* ── Score colors ─────────────────────────────────────── */
    .score-high { color: #16a34a; font-weight: bold; }
    .score-med  { color: #d97706; font-weight: bold; }
    .score-low  { color: #dc2626; font-weight: bold; }

    /* ── Sidebar: teal background, white text ─────────────── */
    section[data-testid="stSidebar"] { background: #0D9488; }
    section[data-testid="stSidebar"] * { color: #FFFFFF !important; }
    section[data-testid="stSidebar"] .stMarkdown,
    section[data-testid="stSidebar"] .stMarkdown p,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] span {
        color: #FFFFFF !important;
    }

    /* ── Buttons: teal with white text ───────────────────── */
    .stButton > button {
        color: #FFFFFF !important;
        background-color: #0D9488 !important;
        border: none !important;
        border-radius: 6px !important;
    }
    .stButton > button:hover {
        background-color: #0F766E !important;
    }

    /* ── Form labels & inputs ─────────────────────────────── */
    .stTextInput label, .stTextArea label,
    .stSelectbox label, .stDateInput label,
    .stTimeInput label, .stNumberInput label,
    .stRadio label, .stCheckbox label,
    .stMultiSelect label {
        color: #1E293B !important;
    }

    /* ── Expander headers ─────────────────────────────────── */
    .streamlit-expanderHeader, .streamlit-expanderHeader p {
        color: #1E293B !important;
    }

    /* ── Tabs ─────────────────────────────────────────────── */
    .stTabs [data-baseweb="tab"] {
        color: #1E293B !important;
    }

    /* ── Table / dataframe text ────────────────────────────── */
    .stDataFrame, .stDataFrame td, .stDataFrame th,
    .stTable td, .stTable th {
        color: #1E293B !important;
    }

    /* ── Success / error / info / warning messages ─────────── */
    .stAlert p, .stAlert span, .stAlert div {
        color: #1E293B !important;
    }

    /* ── Modal / dialog popups ───────────────────────────── */
    div[data-testid="stDialog"],
    div[data-testid="stModal"],
    div[role="dialog"] {
        background: #FFFFFF !important;
        border-radius: 12px;
    }
    div[data-testid="stDialog"] *,
    div[data-testid="stModal"] *,
    div[role="dialog"] * {
        color: #1E293B !important;
    }
    div[data-testid="stDialog"] .stButton > button,
    div[data-testid="stModal"] .stButton > button,
    div[role="dialog"] .stButton > button {
        color: #FFFFFF !important;
        background-color: #0D9488 !important;
    }
    div[data-testid="stDialog"] label,
    div[data-testid="stModal"] label,
    div[role="dialog"] label {
        color: #1E293B !important;
    }

    /* ── Input fields: white bg, dark text ───────────────── */
    .main input, .main textarea, .main select,
    .stTextInput input, .stTextArea textarea,
    .stSelectbox select, .stDateInput input,
    .stTimeInput input, .stNumberInput input,
    div[data-baseweb="input"] input,
    div[data-baseweb="textarea"] textarea,
    div[data-baseweb="select"] > div {
        background-color: #FFFFFF !important;
        color: #1E293B !important;
        border: 1px solid #CBD5E1 !important;
    }
    div[data-baseweb="select"] span,
    div[data-baseweb="select"] div[class*="value"] {
        color: #1E293B !important;
    }

    /* ── Clickable contact methods ──────────────────────────── */
    a.contact-phone {
        color: #0D9488 !important;
        text-decoration: none;
        cursor: pointer;
    }
    a.contact-phone:hover { text-decoration: underline; }

    a.contact-email {
        color: #0D9488 !important;
        text-decoration: none;
        cursor: pointer;
    }
    a.contact-email:hover { text-decoration: underline; }

    a.contact-fax {
        color: #6366F1 !important;
        text-decoration: none;
        cursor: pointer;
    }
    a.contact-fax:hover { text-decoration: underline; }

    a.contact-website {
        color: #0D9488 !important;
        text-decoration: none;
        cursor: pointer;
    }
    a.contact-website:hover { text-decoration: underline; }

    /* ── Calendar event cells ─────────────────────────────── */
    .cal-event-blue  { color: #FFFFFF; background: #0D9488; padding: 2px 4px; border-radius: 3px; display: inline-block; margin: 1px 0; font-size: 0.8em; }
    .cal-event-green { color: #FFFFFF; background: #16a34a; padding: 2px 4px; border-radius: 3px; display: inline-block; margin: 1px 0; font-size: 0.8em; }
    .cal-event-yellow { color: #1E293B; background: #fbbf24; padding: 2px 4px; border-radius: 3px; display: inline-block; margin: 1px 0; font-size: 0.8em; }
    .cal-event-pink  { color: #FFFFFF; background: #e83e8c; padding: 2px 4px; border-radius: 3px; display: inline-block; margin: 1px 0; font-size: 0.8em; }
    .cal-event-gray  { color: #FFFFFF; background: #64748b; padding: 2px 4px; border-radius: 3px; display: inline-block; margin: 1px 0; font-size: 0.8em; }
    .cal-event-orange { color: #FFFFFF; background: #ea580c; padding: 2px 4px; border-radius: 3px; display: inline-block; margin: 1px 0; font-size: 0.8em; }

    /* ── Provider card ────────────────────────────────────── */
    .provider-card {
        border-left-width: 4px;
        border-left-style: solid;
        padding: 12px;
        margin-bottom: 12px;
        background: #FFFFFF;
        border-radius: 4px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    .provider-card strong { color: #1E293B; }
    .provider-card small { color: #64748b; }

    /* ── Hide Streamlit branding, GitHub icon, deploy button ───── */
    #MainMenu                         { display: none !important; }
    footer                            { display: none !important; }
    .stAppDeployButton                { display: none !important; }
    [data-testid="stToolbar"]         { display: none !important; }
    [data-testid="stHeader"]          { visibility: hidden !important; }
    .viewerBadge_container__1QSob     { display: none !important; }
    ._profileContainer_1yi6l_53       { display: none !important; }
</style>
""", unsafe_allow_html=True)


def check_login():
    """Multi-user username + password login."""
    if st.session_state.get("user"):
        return True

    st.markdown("## 🏥 NHCC Provider Outreach Dashboard")
    st.markdown("---")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("### Login")
        username = st.text_input("Username", key="login_user")
        password = st.text_input("Password", type="password", key="login_pw")
        if st.button("Login", use_container_width=True, type="primary"):
            if not username.strip():
                st.error("Please enter your username")
            else:
                try:
                    import bcrypt
                    from database import get_user_by_username, update_last_login
                    user = get_user_by_username(username.strip().lower())
                    if user and bcrypt.checkpw(
                        password.encode(), user["password_hash"].encode()
                    ):
                        update_last_login(user["id"])
                        st.session_state.user = {
                            "id":        user["id"],
                            "username":  user["username"],
                            "full_name": user.get("full_name") or user["username"],
                            "role":      user.get("role", "staff"),
                        }
                        st.rerun()
                    else:
                        st.error("Invalid username or password")
                except Exception as e:
                    st.error(f"Login error: {e}")
                    st.info(
                        "If this is the first setup, run `python setup_users.py` "
                        "locally to create the users table and default admin account."
                    )
    return bool(st.session_state.get("user"))


def main():
    # Show import errors in the browser instead of crashing silently
    if _startup_error:
        st.error("Startup error — please report this to support:")
        st.code(_startup_error)
        return

    # Restore database from GitHub if running on cloud and no local DB exists
    try:
        from database_persistence import auto_restore_database
        auto_restore_database()
    except Exception:
        pass

    # Restore flyers from GitHub if running on cloud
    try:
        from flyer_management import load_flyers_from_github
        load_flyers_from_github()
    except Exception:
        pass

    # Initialize database (safe — creates schema if DB doesn't exist yet)
    try:
        init_db()
        from database import ensure_default_admin
        ensure_default_admin()
    except Exception:
        pass  # DB will be created when user uploads data

    if not check_login():
        return

    current_user = st.session_state.get("user", {})
    is_admin = current_user.get("role") == "admin"

    # Sidebar navigation
    with st.sidebar:
        st.markdown("## 🏥 NHCC Outreach")
        st.caption(f"👤 {current_user.get('full_name', 'User')} ({current_user.get('role', '').capitalize()})")
        st.markdown("---")

        nav_options = [
            "📊 Dashboard",
            "🏢 Providers",
            "📋 Action Items",
            "📅 Calendar",
            "📨 Flyer Campaigns",
            "📈 Analytics",
        ]
        if is_admin:
            nav_options += ["⚙️ Settings", "👥 User Management"]

        _nav_override = st.session_state.pop("_nav_override", None)
        _default_idx = 0
        if _nav_override == "My Daily Work":
            _default_idx = 2  # "📋 Action Items"
        page = st.radio(
            "Navigation",
            nav_options,
            index=_default_idx,
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
            st.session_state.user = None
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
    elif page == "⚙️ Settings" and is_admin:
        from pages.settings import show_settings
        show_settings()
    elif page == "👥 User Management" and is_admin:
        from pages.user_management import show_user_management
        show_user_management()

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
