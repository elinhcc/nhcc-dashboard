"""Outreach Management — inline lunch and cookie outreach tracking per practice.

Status changes happen directly on the page with no pop-up modals.
Dropdowns auto-fill the status date to today on change (via on_change callbacks).
History opens only via the History button. Practice Name navigates to Providers.
"""
import streamlit as st
from datetime import datetime, date, timedelta
from utils import db_exists

# ── Status lists ───────────────────────────────────────────────────────────────

LUNCH_STATUSES = [
    "Not Started",
    "Call 1 - LVM",
    "Call 2 - Follow Up",
    "Call 3 - Follow Up",
    "Approved - Need Schedule",
    "Scheduled",
    "Completed",
    "Cancelled",
    "Declined",
    "Thank You Sent",
]

COOKIE_STATUSES = [
    "Not Started",
    "Scheduled",
    "Completed",
    "Cancelled",
    "Declined",
]

# ── Color palettes (cool = Lunch, warm = Cookie — visually distinct) ───────────

_LC = {                                     # Lunch — cool palette
    "Not Started":             "#94a3b8",
    "Call 1 - LVM":            "#3b82f6",
    "Call 2 - Follow Up":      "#60a5fa",
    "Call 3 - Follow Up":      "#60a5fa",
    "Approved - Need Schedule":"#7c3aed",
    "Scheduled":               "#0D9488",
    "Completed":               "#16a34a",
    "Cancelled":               "#dc2626",
    "Declined":                "#4b5563",
    "Thank You Sent":          "#065f46",
}

_CC = {                                     # Cookie — warm palette
    "Not Started":  "#94a3b8",
    "Scheduled":    "#ea580c",
    "Completed":    "#15803d",
    "Cancelled":    "#dc2626",
    "Declined":     "#4b5563",
}


# ── Small helpers ──────────────────────────────────────────────────────────────

def _badge(text, color="#94a3b8", fg="#fff"):
    return (
        f'<span style="background:{color};color:{fg};padding:2px 8px;'
        f'border-radius:4px;font-size:0.78em;font-weight:600;">{text}</span>'
    )


def _score_info(vol):
    v = vol or 0
    if v >= 10: return "High", "#16a34a"
    if v >= 5:  return "Med",  "#d97706"
    if v >= 1:  return "Low",  "#3b82f6"
    return "None", "#94a3b8"


def _fmt(d):
    return str(d)[:10] if d else "—"


def _parse_date(s):
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except Exception:
        return None


def _create_task(pid, task_type, description, due_date, username, notes=""):
    from database import add_task
    add_task({
        "practice_id": pid,
        "task_type":   task_type,
        "description": description,
        "due_date":    due_date.isoformat() if hasattr(due_date, "isoformat") else str(due_date),
        "assigned_to": username,
        "is_complete": 0,
        "notes":       notes,
        "created_at":  datetime.now().isoformat(),
    })


def _create_event(pid, event_type, label, ev_date, ev_time, notes, username):
    from database import create_event
    create_event({
        "practice_id":    pid,
        "event_type":     event_type,
        "label":          label,
        "scheduled_date": ev_date.isoformat() if hasattr(ev_date, "isoformat") else str(ev_date),
        "scheduled_time": ev_time or "12:00 PM",
        "status":         "Scheduled",
        "notes":          notes or "",
        "created_by":     username,
        "created_at":     datetime.now().isoformat(),
    })


# ── on_change callbacks (auto-fill date to today when dropdown changes) ────────

def _on_lunch_change(pid):
    st.session_state[f"ol_ld_{pid}"] = date.today()


def _on_cookie_change(pid):
    st.session_state[f"ol_cd_{pid}"] = date.today()


# ── History dialog (only place a dialog is used) ───────────────────────────────

@st.dialog("Outreach History", width="large")
def _history_dialog(pid, pname):
    from database import get_outreach_history
    st.markdown(f"**{pname}** — Outreach History")

    tab_all, tab_lunch, tab_cookie = st.tabs(["All", "Lunch", "Cookie"])

    def _render(entries):
        if not entries:
            st.info("No history yet.")
            return
        for h in entries:
            otype  = h.get("outreach_type", "")
            status = h.get("status", "")
            color  = _LC.get(status, "#94a3b8") if otype == "Lunch" else _CC.get(status, "#94a3b8")
            c1, c2 = st.columns([3, 2])
            with c1:
                st.markdown(
                    _badge(otype, "#0D9488" if otype == "Lunch" else "#ea580c") +
                    " " + _badge(status, color),
                    unsafe_allow_html=True,
                )
                if h.get("note"):
                    st.caption(h["note"])
            with c2:
                st.caption(f"Date: {_fmt(h.get('status_date'))}")
                if h.get("amount_spent"):
                    st.caption(f"Spent: ${float(h['amount_spent']):.2f}")
                st.caption(f"By: {h.get('updated_by','?')}  ·  {str(h.get('created_at',''))[:16]}")
            st.divider()

    with tab_all:
        _render(get_outreach_history(pid))
    with tab_lunch:
        _render(get_outreach_history(pid, outreach_type="Lunch"))
    with tab_cookie:
        _render(get_outreach_history(pid, outreach_type="Cookie"))

    if st.button("Close", use_container_width=True, key=f"hist_close_{pid}"):
        st.session_state.ol_history = None
        st.rerun()


# ── Save logic ─────────────────────────────────────────────────────────────────

def _save_lunch(pid, pname, record, new_status, status_date, note, amount, followup, username):
    from database import upsert_outreach_record, add_outreach_history
    today = date.today()
    sd    = status_date or today

    update  = {
        "lunch_status":      new_status,
        "lunch_status_date": sd.isoformat(),
        "lunch_note":        note or "",
    }
    history = {
        "practice_id":   pid,
        "outreach_type": "Lunch",
        "status":        new_status,
        "status_date":   sd.isoformat(),
        "note":          note or "",
        "updated_by":    username,
    }

    if new_status == "Completed":
        next_due = sd + timedelta(days=183)
        update["last_lunch_date"]    = sd.isoformat()
        update["next_lunch_due"]     = next_due.isoformat()
        update["lunch_amount_spent"] = amount or 0.0
        history["amount_spent"]      = amount or 0.0
        _create_task(pid, "Lunch Outreach",
                     f"Next Lunch Outreach — {pname}", next_due, username,
                     "Auto-created: 6 months after completed lunch")

    elif new_status == "Call 1 - LVM":
        fu = followup or (today + timedelta(days=3))
        _create_task(pid, "Follow Up Call",
                     f"Follow Up Call — {pname}", fu, username,
                     "Auto-created: follow up after Call 1 LVM")

    upsert_outreach_record(pid, update)
    add_outreach_history(history)

    # Clear widget keys so next render re-initialises from fresh DB data
    for k in [f"ol_ls_{pid}", f"ol_ld_{pid}", f"ol_ln_{pid}",
              f"ol_la_{pid}", f"ol_lf_{pid}"]:
        st.session_state.pop(k, None)


def _save_cookie(pid, pname, record, new_status, status_date, note, amount, username):
    from database import upsert_outreach_record, add_outreach_history
    today = date.today()
    sd    = status_date or today

    update  = {
        "cookie_status":      new_status,
        "cookie_status_date": sd.isoformat(),
        "cookie_note":        note or "",
    }
    history = {
        "practice_id":   pid,
        "outreach_type": "Cookie",
        "status":        new_status,
        "status_date":   sd.isoformat(),
        "note":          note or "",
        "updated_by":    username,
    }

    if new_status == "Completed":
        next_due = sd + timedelta(days=91)
        update["last_cookie_date"]    = sd.isoformat()
        update["next_cookie_due"]     = next_due.isoformat()
        update["cookie_amount_spent"] = amount or 0.0
        history["amount_spent"]       = amount or 0.0
        _create_task(pid, "Cookie Outreach",
                     f"Next Cookie Outreach — {pname}", next_due, username,
                     "Auto-created: 3 months after completed cookie visit")

    upsert_outreach_record(pid, update)
    add_outreach_history(history)

    for k in [f"ol_cs_{pid}", f"ol_cd_{pid}", f"ol_cn_{pid}", f"ol_ca_{pid}"]:
        st.session_state.pop(k, None)


# ── Inline schedule event form ─────────────────────────────────────────────────

def _render_schedule_form(pid, pname, etype, username):
    """Inline (no modal) form that creates a Calendar event + automation tasks."""
    label        = f"{'Lunch' if etype == 'Lunch' else 'Cookie Visit'} - {pname}"
    default_time = "12:00 PM" if etype == "Lunch" else "10:00 AM"
    flag_k       = f"ol_sf_{etype}_{pid}"

    st.markdown(f"**Schedule {etype} on Calendar**")
    ev_date  = st.date_input("Date", value=date.today() + timedelta(days=7),
                              key=f"ol_sf_dt_{etype}_{pid}")
    ev_time  = st.text_input("Time", value=default_time,
                              key=f"ol_sf_tm_{etype}_{pid}")
    ev_notes = st.text_input("Notes (optional)", placeholder="e.g. bring brochures",
                              key=f"ol_sf_nt_{etype}_{pid}")

    sc1, sc2 = st.columns(2)
    with sc1:
        if st.button("Create Calendar Event", key=f"ol_sf_save_{etype}_{pid}",
                     type="primary", use_container_width=True):
            _create_event(pid, etype, label, ev_date, ev_time, ev_notes, username)
            if etype == "Lunch":
                _create_task(pid, "Catering Order",
                             f"Order Food for Lunch — {pname}",
                             ev_date - timedelta(days=2), username,
                             "Auto-created: 2 days before lunch")
                _create_task(pid, "Confirmation Call",
                             f"Confirmation Call for Lunch — {pname}",
                             ev_date - timedelta(days=1), username,
                             "Auto-created: 1 day before lunch")
            else:
                _create_task(pid, "Catering Order",
                             f"Order Cookies — {pname}",
                             ev_date - timedelta(days=1), username,
                             "Auto-created: 1 day before cookie visit")
            st.session_state[flag_k] = False
            st.success("Calendar event created. Check the Calendar page.")
            st.rerun()
    with sc2:
        if st.button("Schedule Later", key=f"ol_sf_skip_{etype}_{pid}",
                     use_container_width=True):
            later = date.today() + timedelta(days=3)
            if etype == "Lunch":
                _create_task(pid, "Schedule Lunch",
                             f"Schedule Lunch — {pname}", later, username,
                             "Auto-created: schedule later selected")
            else:
                _create_task(pid, "Schedule Cookie Visit",
                             f"Schedule Cookie Visit — {pname}", later, username,
                             "Auto-created: schedule later selected")
            st.session_state[flag_k] = False
            st.rerun()


# ── Per-practice section renderers ─────────────────────────────────────────────

def _render_lunch(pid, pname, record, username, today):
    """Render the inline Lunch outreach section for one practice."""
    saved = record.get("lunch_status") or "Not Started"
    idx   = LUNCH_STATUSES.index(saved) if saved in LUNCH_STATUSES else 0

    # Initialise date key once from DB; on_change callback overwrites it to today
    if f"ol_ld_{pid}" not in st.session_state:
        st.session_state[f"ol_ld_{pid}"] = _parse_date(record.get("lunch_status_date")) or today

    # Status dropdown — on_change auto-fills date to today
    new_status = st.selectbox(
        "Lunch Status", LUNCH_STATUSES, index=idx,
        key=f"ol_ls_{pid}",
        on_change=_on_lunch_change, args=(pid,),
        label_visibility="collapsed",
    )

    # Coloured badge showing current selection
    st.markdown(_badge(new_status, _LC.get(new_status, "#94a3b8")), unsafe_allow_html=True)

    # Status date (auto-filled by on_change, always editable)
    st.date_input("Status Date", key=f"ol_ld_{pid}", label_visibility="collapsed")
    status_date = st.session_state.get(f"ol_ld_{pid}", today)

    # Note field
    if f"ol_ln_{pid}" not in st.session_state:
        st.session_state[f"ol_ln_{pid}"] = record.get("lunch_note") or ""
    st.text_input("Note", key=f"ol_ln_{pid}",
                  placeholder="Note…", label_visibility="collapsed")
    note = st.session_state.get(f"ol_ln_{pid}", "")

    # Extra fields that appear for specific statuses
    amount    = None
    followup  = None

    if new_status == "Completed":
        if f"ol_la_{pid}" not in st.session_state:
            st.session_state[f"ol_la_{pid}"] = float(record.get("lunch_amount_spent") or 0)
        st.number_input("Amount Spent ($)", min_value=0.0, step=0.50,
                        key=f"ol_la_{pid}", label_visibility="collapsed")
        amount = st.session_state.get(f"ol_la_{pid}", 0.0)

    elif new_status == "Call 1 - LVM":
        if f"ol_lf_{pid}" not in st.session_state:
            st.session_state[f"ol_lf_{pid}"] = today + timedelta(days=3)
        st.date_input("Follow-up Due", key=f"ol_lf_{pid}")
        followup = st.session_state.get(f"ol_lf_{pid}")

    # Last / Next summary line
    last_s = _fmt(record.get("last_lunch_date"))
    next_s = _fmt(record.get("next_lunch_due"))
    next_d = str(record.get("next_lunch_due") or "")[:10]
    overdue = next_d and next_d < today.isoformat() and new_status not in (
        "Scheduled", "Approved - Need Schedule")
    if last_s != "—" or next_s != "—":
        nd_display = f":red[{next_s} OVERDUE]" if overdue else next_s
        st.caption(f"Last: {last_s}  ·  Next due: {nd_display}")

    # Schedule Now button (only for scheduling statuses)
    sched_k = f"ol_sf_Lunch_{pid}"
    if new_status in ("Approved - Need Schedule", "Scheduled"):
        if st.button("Schedule Now", key=f"ol_lsn_{pid}", use_container_width=True):
            st.session_state[sched_k] = True

    if st.session_state.get(sched_k):
        _render_schedule_form(pid, pname, "Lunch", username)

    # Save button — primary (teal) when pending, secondary when unchanged
    is_pending = new_status != saved
    if st.button("Save Lunch", key=f"ol_lsave_{pid}",
                 type="primary" if is_pending else "secondary",
                 use_container_width=True):
        _save_lunch(pid, pname, record, new_status, status_date,
                    note, amount, followup, username)
        st.rerun()


def _render_cookie(pid, pname, record, username, today):
    """Render the inline Cookie outreach section for one practice."""
    saved = record.get("cookie_status") or "Not Started"
    idx   = COOKIE_STATUSES.index(saved) if saved in COOKIE_STATUSES else 0

    if f"ol_cd_{pid}" not in st.session_state:
        st.session_state[f"ol_cd_{pid}"] = _parse_date(record.get("cookie_status_date")) or today

    new_status = st.selectbox(
        "Cookie Status", COOKIE_STATUSES, index=idx,
        key=f"ol_cs_{pid}",
        on_change=_on_cookie_change, args=(pid,),
        label_visibility="collapsed",
    )

    st.markdown(_badge(new_status, _CC.get(new_status, "#94a3b8")), unsafe_allow_html=True)

    st.date_input("Status Date", key=f"ol_cd_{pid}", label_visibility="collapsed")
    status_date = st.session_state.get(f"ol_cd_{pid}", today)

    if f"ol_cn_{pid}" not in st.session_state:
        st.session_state[f"ol_cn_{pid}"] = record.get("cookie_note") or ""
    st.text_input("Note", key=f"ol_cn_{pid}",
                  placeholder="Note…", label_visibility="collapsed")
    note = st.session_state.get(f"ol_cn_{pid}", "")

    amount = None
    if new_status == "Completed":
        if f"ol_ca_{pid}" not in st.session_state:
            st.session_state[f"ol_ca_{pid}"] = float(record.get("cookie_amount_spent") or 0)
        st.number_input("Amount Spent ($)", min_value=0.0, step=0.50,
                        key=f"ol_ca_{pid}", label_visibility="collapsed")
        amount = st.session_state.get(f"ol_ca_{pid}", 0.0)

    last_s = _fmt(record.get("last_cookie_date"))
    next_s = _fmt(record.get("next_cookie_due"))
    next_d = str(record.get("next_cookie_due") or "")[:10]
    overdue = next_d and next_d < today.isoformat() and new_status != "Scheduled"
    if last_s != "—" or next_s != "—":
        nd_display = f":red[{next_s} OVERDUE]" if overdue else next_s
        st.caption(f"Last: {last_s}  ·  Next due: {nd_display}")

    sched_k = f"ol_sf_Cookie Visit_{pid}"
    if new_status == "Scheduled":
        if st.button("Schedule Now", key=f"ol_csn_{pid}", use_container_width=True):
            st.session_state[sched_k] = True

    if st.session_state.get(sched_k):
        _render_schedule_form(pid, pname, "Cookie Visit", username)

    is_pending = new_status != saved
    if st.button("Save Cookies", key=f"ol_csave_{pid}",
                 type="primary" if is_pending else "secondary",
                 use_container_width=True):
        _save_cookie(pid, pname, record, new_status, status_date,
                     note, amount, username)
        st.rerun()


# ── Main page ──────────────────────────────────────────────────────────────────

def show_outreach_management():
    st.markdown("## Outreach Management")

    if not db_exists():
        st.warning("No data loaded yet.")
        st.info("Go to **Settings > Data Import** to upload your provider Excel file.")
        return

    from database import (
        get_all_practices,
        get_all_outreach_records,
        get_practices_with_new_referrers,
        get_all_last_contacts,
        get_open_task_counts,
    )

    st.session_state.setdefault("ol_history", None)

    user_dict = st.session_state.get("user", {})
    username  = user_dict.get("username", "")
    today     = date.today()
    today_str = today.isoformat()

    # ── Batch data load (minimal DB calls) ─────────────────────────────────────
    practices     = get_all_practices(status_filter="Active")
    outreach_map  = get_all_outreach_records()
    new_ref_pids  = get_practices_with_new_referrers()
    last_contacts = get_all_last_contacts()
    task_counts   = get_open_task_counts()

    # ── Build row dicts ────────────────────────────────────────────────────────
    rows = []
    for p in practices:
        pid    = p["id"]
        rec    = outreach_map.get(pid) or {}
        sl, sc = _score_info(p.get("referral_volume"))
        lc     = last_contacts.get(pid)
        lc_txt = (
            f"Last contact: {str(lc.get('contact_date',''))[:10]} ({lc.get('contact_type','')})"
            if lc else "No contact logged"
        )
        rows.append({
            "p": p, "pid": pid, "rec": rec,
            "score_label": sl, "score_color": sc,
            "new_ref":     pid in new_ref_pids,
            "open_tasks":  task_counts.get(pid, 0),
            "lc_txt":      lc_txt,
            "lunch_status":  rec.get("lunch_status")  or "Not Started",
            "cookie_status": rec.get("cookie_status") or "Not Started",
            "next_lunch":    str(rec.get("next_lunch_due")  or "")[:10],
            "next_cookie":   str(rec.get("next_cookie_due") or "")[:10],
        })

    # ── Filters ────────────────────────────────────────────────────────────────
    in_90 = (today + timedelta(days=90)).isoformat()
    with st.expander("Filters", expanded=False):
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            f_name   = st.text_input("Practice Name",   key="ol_fn").strip().lower()
            f_lunch  = st.selectbox("Lunch Status",  ["All"] + LUNCH_STATUSES,  key="ol_fl")
        with fc2:
            f_cookie = st.selectbox("Cookie Status", ["All"] + COOKIE_STATUSES, key="ol_fc")
            f_alert  = st.checkbox("New Referrer Alert Only",   key="ol_fa")
        with fc3:
            f_tasks      = st.checkbox("Has Open Tasks Only",   key="ol_ft")
            f_lunch_due  = st.checkbox("Lunch Due ≤ 90 days",  key="ol_fld")
            f_cookie_due = st.checkbox("Cookie Due ≤ 90 days", key="ol_fcd")

    _sr = {"None": 0, "Low": 1, "Med": 2, "High": 3}
    filtered = [
        r for r in rows
        if (not f_name      or f_name in r["p"]["name"].lower())
        and (f_lunch  == "All" or r["lunch_status"]  == f_lunch)
        and (f_cookie == "All" or r["cookie_status"] == f_cookie)
        and (not f_alert      or r["new_ref"])
        and (not f_tasks      or r["open_tasks"] > 0)
        and (not f_lunch_due  or (r["next_lunch"]  and today_str <= r["next_lunch"]  <= in_90))
        and (not f_cookie_due or (r["next_cookie"] and today_str <= r["next_cookie"] <= in_90))
    ]
    filtered.sort(key=lambda r: (
        not r["new_ref"],
        -_sr.get(r["score_label"], 0),
        r["p"]["name"],
    ))

    # ── Summary metrics ────────────────────────────────────────────────────────
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Practices",          len(filtered))
    m2.metric("New Referrer Alerts", sum(1 for r in filtered if r["new_ref"]))
    m3.metric("Lunch In Progress",   sum(
        1 for r in filtered
        if r["lunch_status"] not in ("Not Started", "Completed", "Declined", "Cancelled")
    ))
    m4.metric("Cookie In Progress",  sum(
        1 for r in filtered
        if r["cookie_status"] not in ("Not Started", "Completed", "Declined", "Cancelled")
    ))
    m5.metric("Lunch Overdue",       sum(
        1 for r in filtered
        if r["next_lunch"] and r["next_lunch"] < today_str
        and r["lunch_status"] not in ("Scheduled", "Approved - Need Schedule")
    ))

    st.markdown("---")

    if not filtered:
        st.info("No practices match the current filters.")
        return

    # ── Practice cards ─────────────────────────────────────────────────────────
    for r in filtered:
        p    = r["p"]
        pid  = r["pid"]
        pname = p["name"]

        # Header row: practice name (nav button) | badges | History
        hc1, hc2, hc3 = st.columns([4, 3, 1])
        with hc1:
            btn_lbl = pname + ("  🔔" if r["new_ref"] else "")
            if st.button(btn_lbl, key=f"ol_pn_{pid}",
                         help="Open Practice page", use_container_width=False):
                st.session_state._nav_override = "🏢 Providers"
                st.session_state.ol_jump_practice = pid
                st.rerun()

        with hc2:
            badge_html = _badge(r["score_label"], r["score_color"])
            if r["new_ref"]:
                badge_html += " " + _badge("New Referrer", "#dc2626")
            if r["open_tasks"]:
                badge_html += " " + _badge(
                    f"{r['open_tasks']} task{'s' if r['open_tasks'] != 1 else ''}",
                    "#f59e0b",
                )
            st.markdown(badge_html, unsafe_allow_html=True)

        with hc3:
            if st.button("History", key=f"ol_hist_{pid}", use_container_width=True):
                st.session_state.ol_history = (pid, pname)
                st.rerun()

        # Gray summary line
        st.caption(r["lc_txt"] + f"  ·  {r['open_tasks']} open task{'s' if r['open_tasks'] != 1 else ''}")

        # Two-column inline edit: Lunch (cool blue/teal) | Cookie (warm orange)
        lcol, ccol = st.columns(2)

        with lcol:
            st.markdown(
                '<p style="font-size:0.8em;font-weight:700;color:#0D9488;'
                'margin:4px 0 2px 0;">LUNCH</p>',
                unsafe_allow_html=True,
            )
            _render_lunch(pid, pname, r["rec"], username, today)

        with ccol:
            st.markdown(
                '<p style="font-size:0.8em;font-weight:700;color:#ea580c;'
                'margin:4px 0 2px 0;">COOKIES</p>',
                unsafe_allow_html=True,
            )
            _render_cookie(pid, pname, r["rec"], username, today)

        st.divider()

    # ── History dialog ─────────────────────────────────────────────────────────
    hist = st.session_state.get("ol_history")
    if hist:
        h_pid, h_name = hist if isinstance(hist, tuple) else (hist, "Practice")
        _history_dialog(h_pid, h_name)
