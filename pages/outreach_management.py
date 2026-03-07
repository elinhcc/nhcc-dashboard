"""Outreach Management — lunch and cookie relationship outreach tracking per practice."""
import streamlit as st
from datetime import datetime, date, timedelta
from utils import db_exists

LUNCH_STATUSES = [
    "Not Started",
    "Call 1 - LVM",
    "Call 2 - Follow Up",
    "Call 3 - Follow Up",
    "Approved - Need Schedule",
    "Scheduled",
    "Cancelled",
    "Declined",
    "Completed",
    "Thank You Sent",
]

COOKIE_STATUSES = [
    "Not Started",
    "Scheduled",
    "Cancelled",
    "Completed",
    "Declined",
]

# Status badge colors
_LUNCH_COLORS = {
    "Not Started":            "#94a3b8",
    "Call 1 - LVM":           "#3b82f6",
    "Call 2 - Follow Up":     "#6366f1",
    "Call 3 - Follow Up":     "#8b5cf6",
    "Approved - Need Schedule": "#f59e0b",
    "Scheduled":              "#0D9488",
    "Cancelled":              "#64748b",
    "Declined":               "#ef4444",
    "Completed":              "#16a34a",
    "Thank You Sent":         "#0891b2",
}

_COOKIE_COLORS = {
    "Not Started":  "#94a3b8",
    "Scheduled":    "#0D9488",
    "Cancelled":    "#64748b",
    "Completed":    "#16a34a",
    "Declined":     "#ef4444",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _badge(text, color="#94a3b8"):
    return (
        f'<span style="background:{color};color:#fff;padding:2px 8px;'
        f'border-radius:4px;font-size:0.78em;font-weight:600;">{text}</span>'
    )


def _score_label(referral_volume):
    v = referral_volume or 0
    if v >= 10:
        return "High", "#16a34a"
    elif v >= 5:
        return "Med", "#d97706"
    elif v >= 1:
        return "Low", "#3b82f6"
    return "None", "#94a3b8"


def _fmt_date(d):
    if not d:
        return "—"
    return str(d)[:10]


def _create_task(practice_id, task_type, description, due_date, username, notes=""):
    from database import add_task
    add_task({
        "practice_id": practice_id,
        "task_type":   task_type,
        "description": description,
        "due_date":    due_date.isoformat() if hasattr(due_date, "isoformat") else str(due_date),
        "assigned_to": username,
        "is_complete": 0,
        "notes":       notes,
        "created_at":  datetime.now().isoformat(),
    })


def _create_calendar_event(practice_id, event_type, label, event_date, event_time, notes, username):
    from database import create_event
    create_event({
        "practice_id":    practice_id,
        "event_type":     event_type,
        "label":          label,
        "scheduled_date": event_date.isoformat() if hasattr(event_date, "isoformat") else str(event_date),
        "scheduled_time": event_time or "12:00 PM",
        "status":         "Scheduled",
        "notes":          notes or "",
        "created_by":     username,
        "created_at":     datetime.now().isoformat(),
    })


# ── Lunch save logic ───────────────────────────────────────────────────────────

def _save_lunch_update(practice_id, practice_name, new_status, status_date, note, extra, username):
    from database import upsert_outreach_record, add_outreach_history

    record_update = {
        "lunch_status":      new_status,
        "lunch_status_date": status_date.isoformat() if hasattr(status_date, "isoformat") else str(status_date),
        "lunch_note":        note,
    }

    history_entry = {
        "practice_id":  practice_id,
        "outreach_type": "Lunch",
        "status":       new_status,
        "status_date":  status_date.isoformat() if hasattr(status_date, "isoformat") else str(status_date),
        "note":         note,
        "updated_by":   username,
    }

    today = date.today()

    if new_status == "Call 1 - LVM":
        follow_up = extra.get("follow_up_date", today + timedelta(days=3))
        _create_task(
            practice_id, "Follow Up Call",
            f"Lunch Outreach - Follow Up Call to {practice_name}",
            follow_up, username,
            notes="Auto-created: follow up after Call 1 LVM",
        )

    elif new_status in ("Approved - Need Schedule", "Scheduled"):
        if extra.get("schedule_now") and extra.get("event_date"):
            event_date = extra["event_date"]
            event_time = extra.get("event_time", "12:00 PM")
            label = f"Lunch - {practice_name}"
            _create_calendar_event(practice_id, "Lunch", label, event_date, event_time, note, username)
            # Order food task: 2 days before
            order_due = event_date - timedelta(days=2)
            _create_task(practice_id, "Catering Order", f"Order Food for Lunch - {practice_name}", order_due, username,
                         notes="Auto-created: 2 days before lunch")
            # Confirmation call task: 1 day before
            confirm_due = event_date - timedelta(days=1)
            _create_task(practice_id, "Confirmation Call", f"Confirmation Call for Lunch - {practice_name}", confirm_due, username,
                         notes="Auto-created: 1 day before lunch")
        else:
            schedule_due = today + timedelta(days=3)
            _create_task(practice_id, "Schedule Lunch", f"Schedule Lunch - {practice_name}", schedule_due, username,
                         notes="Auto-created: schedule later selected")

    elif new_status == "Completed":
        completed_date = extra.get("completed_date", status_date)
        amount = extra.get("amount_spent", 0.0)
        next_due = (completed_date + timedelta(days=183)) if hasattr(completed_date, "isoformat") else (today + timedelta(days=183))
        record_update["last_lunch_date"]    = completed_date.isoformat() if hasattr(completed_date, "isoformat") else str(completed_date)
        record_update["next_lunch_due"]     = next_due.isoformat()
        record_update["lunch_amount_spent"] = amount
        history_entry["amount_spent"]       = amount
        _create_task(practice_id, "Lunch Outreach", f"Next Lunch Outreach - {practice_name}", next_due, username,
                     notes="Auto-created: 6 months after completed lunch")

    upsert_outreach_record(practice_id, record_update)
    add_outreach_history(history_entry)


# ── Cookie save logic ──────────────────────────────────────────────────────────

def _save_cookie_update(practice_id, practice_name, new_status, status_date, note, extra, username):
    from database import upsert_outreach_record, add_outreach_history

    record_update = {
        "cookie_status":      new_status,
        "cookie_status_date": status_date.isoformat() if hasattr(status_date, "isoformat") else str(status_date),
        "cookie_note":        note,
    }

    history_entry = {
        "practice_id":   practice_id,
        "outreach_type": "Cookie",
        "status":        new_status,
        "status_date":   status_date.isoformat() if hasattr(status_date, "isoformat") else str(status_date),
        "note":          note,
        "updated_by":    username,
    }

    today = date.today()

    if new_status == "Scheduled":
        if extra.get("schedule_now") and extra.get("event_date"):
            event_date = extra["event_date"]
            event_time = extra.get("event_time", "10:00 AM")
            label = f"Cookie Visit - {practice_name}"
            _create_calendar_event(practice_id, "Cookie Visit", label, event_date, event_time, note, username)
            order_due = event_date - timedelta(days=1)
            _create_task(practice_id, "Catering Order", f"Order Cookies - {practice_name}", order_due, username,
                         notes="Auto-created: 1 day before cookie visit")
        else:
            schedule_due = today + timedelta(days=3)
            _create_task(practice_id, "Schedule Cookie Visit", f"Schedule Cookie Visit - {practice_name}", schedule_due, username,
                         notes="Auto-created: schedule later selected")

    elif new_status == "Completed":
        completed_date = extra.get("completed_date", status_date)
        amount = extra.get("amount_spent", 0.0)
        next_due = (completed_date + timedelta(days=91)) if hasattr(completed_date, "isoformat") else (today + timedelta(days=91))
        record_update["last_cookie_date"]    = completed_date.isoformat() if hasattr(completed_date, "isoformat") else str(completed_date)
        record_update["next_cookie_due"]     = next_due.isoformat()
        record_update["cookie_amount_spent"] = amount
        history_entry["amount_spent"]        = amount
        _create_task(practice_id, "Cookie Outreach", f"Next Cookie Outreach - {practice_name}", next_due, username,
                     notes="Auto-created: 3 months after completed cookie visit")

    upsert_outreach_record(practice_id, record_update)
    add_outreach_history(history_entry)


# ── Dialogs ────────────────────────────────────────────────────────────────────

@st.dialog("Update Lunch Status", width="large")
def _lunch_dialog(practice_id, practice_name, record, username):
    st.markdown(f"**Practice:** {practice_name}")
    current = (record.get("lunch_status") or "Not Started") if record else "Not Started"
    curr_idx = LUNCH_STATUSES.index(current) if current in LUNCH_STATUSES else 0

    new_status = st.selectbox("New Lunch Status", LUNCH_STATUSES, index=curr_idx)
    status_date = st.date_input("Status Date", value=date.today())
    note = st.text_input("Note", placeholder="Brief note (required)", key="lunch_note_input")

    extra = {}
    error = None

    if new_status == "Call 1 - LVM":
        st.markdown("**Next Follow-Up**")
        extra["follow_up_date"] = st.date_input(
            "Next Follow Up Due Date", value=date.today() + timedelta(days=3), key="lunch_followup_date"
        )

    elif new_status in ("Approved - Need Schedule", "Scheduled"):
        st.markdown("**Would you like to schedule this lunch now?**")
        schedule_choice = st.radio("", ["Schedule Later", "Schedule Now"], horizontal=True, key="lunch_schedule_choice")
        if schedule_choice == "Schedule Now":
            extra["schedule_now"] = True
            extra["event_date"] = st.date_input("Lunch Date", value=date.today() + timedelta(days=7), key="lunch_event_date")
            extra["event_time"] = st.text_input("Lunch Time", value="12:00 PM", key="lunch_event_time")
            st.caption("A calendar event will be created and tasks for ordering food and a confirmation call will be added automatically.")
        else:
            extra["schedule_now"] = False
            st.caption("A 'Schedule Lunch' task will be created due in 3 days.")

    elif new_status == "Completed":
        extra["completed_date"] = st.date_input("Completed Date", value=date.today(), key="lunch_completed_date")
        extra["amount_spent"] = st.number_input("Amount Spent ($)", min_value=0.0, step=0.50, value=0.0, key="lunch_amount")
        st.caption("Next Lunch Due will be set to 6 months from the completed date.")

    st.markdown("---")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("Save", type="primary", use_container_width=True, key="lunch_save_btn"):
            if not note.strip():
                error = "Note is required."
            elif new_status == "Completed" and extra.get("amount_spent") is None:
                error = "Please enter the amount spent."
            else:
                _save_lunch_update(practice_id, practice_name, new_status, status_date, note.strip(), extra, username)
                st.session_state.outreach_lunch_info = None
                st.success("Lunch status updated!")
                st.rerun()

    with col2:
        if st.button("Cancel", use_container_width=True, key="lunch_cancel_btn"):
            st.session_state.outreach_lunch_info = None
            st.rerun()

    if error:
        st.error(error)


@st.dialog("Update Cookie Status", width="large")
def _cookie_dialog(practice_id, practice_name, record, username):
    st.markdown(f"**Practice:** {practice_name}")
    current = (record.get("cookie_status") or "Not Started") if record else "Not Started"
    curr_idx = COOKIE_STATUSES.index(current) if current in COOKIE_STATUSES else 0

    new_status = st.selectbox("New Cookie Status", COOKIE_STATUSES, index=curr_idx)
    status_date = st.date_input("Status Date", value=date.today())
    note = st.text_input("Note", placeholder="Brief note (required)", key="cookie_note_input")

    extra = {}
    error = None

    if new_status == "Scheduled":
        st.markdown("**Would you like to schedule this cookie visit now?**")
        schedule_choice = st.radio("", ["Schedule Later", "Schedule Now"], horizontal=True, key="cookie_schedule_choice")
        if schedule_choice == "Schedule Now":
            extra["schedule_now"] = True
            extra["event_date"] = st.date_input("Cookie Visit Date", value=date.today() + timedelta(days=3), key="cookie_event_date")
            extra["event_time"] = st.text_input("Visit Time", value="10:00 AM", key="cookie_event_time")
            st.caption("A calendar event will be created and a task to order cookies will be added automatically.")
        else:
            extra["schedule_now"] = False
            st.caption("A 'Schedule Cookie Visit' task will be created due in 3 days.")

    elif new_status == "Completed":
        extra["completed_date"] = st.date_input("Completed Date", value=date.today(), key="cookie_completed_date")
        extra["amount_spent"] = st.number_input("Amount Spent ($)", min_value=0.0, step=0.50, value=0.0, key="cookie_amount")
        st.caption("Next Cookie Due will be set to 3 months from the completed date.")

    st.markdown("---")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("Save", type="primary", use_container_width=True, key="cookie_save_btn"):
            if not note.strip():
                error = "Note is required."
            else:
                _save_cookie_update(practice_id, practice_name, new_status, status_date, note.strip(), extra, username)
                st.session_state.outreach_cookie_info = None
                st.success("Cookie status updated!")
                st.rerun()

    with col2:
        if st.button("Cancel", use_container_width=True, key="cookie_cancel_btn"):
            st.session_state.outreach_cookie_info = None
            st.rerun()

    if error:
        st.error(error)


@st.dialog("Outreach History", width="large")
def _history_dialog(practice_id, practice_name):
    from database import get_outreach_history
    st.markdown(f"**{practice_name}** — Outreach History")

    tab_lunch, tab_cookie, tab_all = st.tabs(["Lunch", "Cookie", "All"])

    def _render_history(entries):
        if not entries:
            st.info("No history yet.")
            return
        for h in entries:
            otype  = h.get("outreach_type", "")
            status = h.get("status", "")
            color  = _LUNCH_COLORS.get(status, "#94a3b8") if otype == "Lunch" else _COOKIE_COLORS.get(status, "#94a3b8")
            col_a, col_b = st.columns([3, 2])
            with col_a:
                st.markdown(
                    f'{_badge(otype, "#0D9488" if otype=="Lunch" else "#16a34a")} '
                    f'{_badge(status, color)}',
                    unsafe_allow_html=True,
                )
                if h.get("note"):
                    st.caption(h["note"])
            with col_b:
                st.caption(f"Date: {_fmt_date(h.get('status_date'))}")
                if h.get("amount_spent"):
                    st.caption(f"Spent: ${h['amount_spent']:.2f}")
                st.caption(f"By: {h.get('updated_by','?')}  |  {str(h.get('created_at',''))[:16]}")
            st.divider()

    with tab_lunch:
        _render_history(get_outreach_history(practice_id, outreach_type="Lunch"))
    with tab_cookie:
        _render_history(get_outreach_history(practice_id, outreach_type="Cookie"))
    with tab_all:
        _render_history(get_outreach_history(practice_id))

    if st.button("Close", use_container_width=True):
        st.session_state.outreach_history_info = None
        st.rerun()


# ── Main page ─────────────────────────────────────────────────────────────────

def show_outreach_management():
    st.markdown("## Outreach Management")

    if not db_exists():
        st.warning("No data loaded yet.")
        st.info("Go to **Settings > Data Import** to upload your provider Excel file.")
        return

    from database import (
        get_all_practices, get_tasks,
        get_all_outreach_records, get_practices_with_new_referrers,
    )

    # Session state defaults
    st.session_state.setdefault("outreach_lunch_info",   None)
    st.session_state.setdefault("outreach_cookie_info",  None)
    st.session_state.setdefault("outreach_history_info", None)

    user_dict = st.session_state.get("user", {})
    username  = user_dict.get("username", "")
    is_admin  = user_dict.get("role") == "admin"
    today_str = date.today().isoformat()

    # Load data
    practices      = get_all_practices(status_filter="Active")
    outreach_map   = get_all_outreach_records()         # {practice_id: record}
    new_ref_pids   = get_practices_with_new_referrers() # set of practice_ids
    all_open_tasks = get_tasks(is_complete=0)
    task_counts    = {}
    for t in all_open_tasks:
        pid = t.get("practice_id")
        if pid:
            task_counts[pid] = task_counts.get(pid, 0) + 1

    # Build rows
    rows = []
    for p in practices:
        pid     = p["id"]
        record  = outreach_map.get(pid) or {}
        score_label, score_color = _score_label(p.get("referral_volume"))
        rows.append({
            "practice":         p,
            "record":           record,
            "score_label":      score_label,
            "score_color":      score_color,
            "new_referrer":     pid in new_ref_pids,
            "open_tasks":       task_counts.get(pid, 0),
            "lunch_status":     record.get("lunch_status") or "Not Started",
            "lunch_date":       record.get("lunch_status_date"),
            "lunch_note":       record.get("lunch_note") or "",
            "last_lunch":       record.get("last_lunch_date"),
            "next_lunch":       record.get("next_lunch_due"),
            "cookie_status":    record.get("cookie_status") or "Not Started",
            "cookie_date":      record.get("cookie_status_date"),
            "cookie_note":      record.get("cookie_note") or "",
            "last_cookie":      record.get("last_cookie_date"),
            "next_cookie":      record.get("next_cookie_due"),
        })

    # ── Filters ────────────────────────────────────────────────────────────────
    with st.expander("Filters", expanded=False):
        fc1, fc2, fc3, fc4 = st.columns(4)
        with fc1:
            filter_name = st.text_input("Practice Name", key="of_name").strip().lower()
        with fc2:
            filter_lunch = st.selectbox("Lunch Status", ["All"] + LUNCH_STATUSES, key="of_lunch")
        with fc3:
            filter_cookie = st.selectbox("Cookie Status", ["All"] + COOKIE_STATUSES, key="of_cookie")
        with fc4:
            filter_alert  = st.checkbox("New Referrer Alert Only", key="of_alert")
            filter_tasks  = st.checkbox("Has Open Tasks Only",     key="of_tasks")
            filter_score  = st.selectbox("Min Score", ["Any", "Low", "Med", "High"], key="of_score")

    # Apply filters
    _score_rank = {"None": 0, "Low": 1, "Med": 2, "High": 3}
    min_rank    = _score_rank.get(filter_score, 0) if filter_score != "Any" else 0
    filtered = [
        r for r in rows
        if (not filter_name   or filter_name in r["practice"]["name"].lower())
        and (filter_lunch  == "All" or r["lunch_status"]  == filter_lunch)
        and (filter_cookie == "All" or r["cookie_status"] == filter_cookie)
        and (not filter_alert or r["new_referrer"])
        and (not filter_tasks or r["open_tasks"] > 0)
        and (_score_rank.get(r["score_label"], 0) >= min_rank)
    ]

    # Sort: new referrers first, then by score desc, then by name
    filtered.sort(key=lambda r: (
        not r["new_referrer"],
        -_score_rank.get(r["score_label"], 0),
        r["practice"]["name"],
    ))

    # ── Summary metrics ────────────────────────────────────────────────────────
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Practices", len(filtered))
    m2.metric("New Referrer Alerts", sum(1 for r in filtered if r["new_referrer"]))
    m3.metric("Lunch In Progress", sum(
        1 for r in filtered if r["lunch_status"] not in ("Not Started", "Completed", "Declined")
    ))
    m4.metric("Cookie In Progress", sum(
        1 for r in filtered if r["cookie_status"] not in ("Not Started", "Completed", "Declined")
    ))
    overdue_lunch = sum(
        1 for r in filtered
        if r["next_lunch"] and r["next_lunch"] < today_str
        and r["lunch_status"] not in ("Scheduled", "Approved - Need Schedule")
    )
    m5.metric("Lunch Overdue", overdue_lunch, delta=None)

    st.markdown("---")

    if not filtered:
        st.info("No practices match the current filters.")
    else:
        _show_table(filtered, username, is_admin)

    # ── Render dialogs ─────────────────────────────────────────────────────────
    info = st.session_state.get("outreach_lunch_info")
    if info:
        _lunch_dialog(info["pid"], info["name"], info["record"], username)

    info = st.session_state.get("outreach_cookie_info")
    if info:
        _cookie_dialog(info["pid"], info["name"], info["record"], username)

    info = st.session_state.get("outreach_history_info")
    if info:
        _history_dialog(info["pid"], info["name"])


# ── Table rendering ───────────────────────────────────────────────────────────

def _show_table(rows, username, is_admin):
    today_str = date.today().isoformat()

    for r in rows:
        p            = r["practice"]
        pid          = p["id"]
        pname        = p["name"]
        lunch_status = r["lunch_status"]
        cookie_status = r["cookie_status"]
        lunch_color  = _LUNCH_COLORS.get(lunch_status, "#94a3b8")
        cookie_color = _COOKIE_COLORS.get(cookie_status, "#94a3b8")

        # Overdue flags
        lunch_overdue = (
            r["next_lunch"] and r["next_lunch"] < today_str
            and lunch_status not in ("Scheduled", "Approved - Need Schedule")
        )
        cookie_overdue = (
            r["next_cookie"] and r["next_cookie"] < today_str
            and cookie_status not in ("Scheduled",)
        )

        # ── Practice header row ────────────────────────────────────────────
        hcol1, hcol2 = st.columns([5, 2])
        with hcol1:
            # Practice name as navigation button
            name_label = pname
            if r["new_referrer"]:
                name_label += "  🔔 NEW REFERRER"
            if st.button(
                name_label,
                key=f"pname_{pid}",
                help="Go to Providers page",
                use_container_width=False,
            ):
                st.session_state._nav_override = "Providers"
                st.rerun()
        with hcol2:
            badges = f'{_badge(r["score_label"], r["score_color"])}'
            if r["new_referrer"]:
                badges += f'&nbsp;{_badge("New Referrer", "#dc2626")}'
            if r["open_tasks"]:
                badges += f'&nbsp;{_badge(str(r["open_tasks"]) + " tasks", "#f59e0b")}'
            st.markdown(badges, unsafe_allow_html=True)

        # ── Lunch + Cookie two-column layout ──────────────────────────────
        lcol, ccol = st.columns(2)

        with lcol:
            st.markdown(
                f'**Lunch:** {_badge(lunch_status, lunch_color)}',
                unsafe_allow_html=True,
            )
            if r["lunch_date"]:
                st.caption(f"Status date: {_fmt_date(r['lunch_date'])}")
            if r["lunch_note"]:
                st.caption(f"Note: {r['lunch_note']}")
            info_parts = []
            if r["last_lunch"]:
                info_parts.append(f"Last: {_fmt_date(r['last_lunch'])}")
            if r["next_lunch"]:
                nd = _fmt_date(r["next_lunch"])
                label = f"Next due: **:red[{nd} OVERDUE]**" if lunch_overdue else f"Next due: {nd}"
                info_parts.append(label)
            if info_parts:
                st.markdown("  |  ".join(info_parts))
            bcol1, bcol2 = st.columns(2)
            with bcol1:
                if st.button("Update Lunch", key=f"ul_{pid}", use_container_width=True):
                    st.session_state.outreach_lunch_info = {
                        "pid": pid, "name": pname, "record": r["record"]
                    }
                    st.rerun()
            with bcol2:
                if st.button("History", key=f"lh_{pid}", use_container_width=True):
                    st.session_state.outreach_history_info = {"pid": pid, "name": pname}
                    st.rerun()

        with ccol:
            st.markdown(
                f'**Cookies:** {_badge(cookie_status, cookie_color)}',
                unsafe_allow_html=True,
            )
            if r["cookie_date"]:
                st.caption(f"Status date: {_fmt_date(r['cookie_date'])}")
            if r["cookie_note"]:
                st.caption(f"Note: {r['cookie_note']}")
            info_parts = []
            if r["last_cookie"]:
                info_parts.append(f"Last: {_fmt_date(r['last_cookie'])}")
            if r["next_cookie"]:
                nd = _fmt_date(r["next_cookie"])
                label = f"Next due: **:red[{nd} OVERDUE]**" if cookie_overdue else f"Next due: {nd}"
                info_parts.append(label)
            if info_parts:
                st.markdown("  |  ".join(info_parts))
            bcol3, bcol4 = st.columns(2)
            with bcol3:
                if st.button("Update Cookies", key=f"uc_{pid}", use_container_width=True):
                    st.session_state.outreach_cookie_info = {
                        "pid": pid, "name": pname, "record": r["record"]
                    }
                    st.rerun()
            with bcol4:
                if st.button("History", key=f"ch_{pid}", use_container_width=True):
                    st.session_state.outreach_history_info = {"pid": pid, "name": pname}
                    st.rerun()

        st.divider()
