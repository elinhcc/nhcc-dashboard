"""Calendar view: fully interactive monthly outreach calendar with color-coded events."""
import streamlit as st
from datetime import datetime, timedelta
import calendar
from utils import db_exists

# Color scheme per requirements:
# Blue = Lunches, Green = Cookie Visits, Yellow = Flyers, Pink = Thank You Letters
EVENT_COLORS = {
    "Lunch":            {"bg": "#007bff", "css": "cal-event-blue"},
    "Cookie Visit":     {"bg": "#28a745", "css": "cal-event-green"},
    "Flyer":            {"bg": "#ffc107", "css": "cal-event-yellow"},
    "Thank You Letter": {"bg": "#e83e8c", "css": "cal-event-pink"},
    "Call":             {"bg": "#6c757d", "css": "cal-event-gray"},
    "Other":            {"bg": "#6c757d", "css": "cal-event-gray"},
}


def _css_class(event_type):
    return EVENT_COLORS.get(event_type, EVENT_COLORS["Other"])["css"]


def _color(event_type):
    return EVENT_COLORS.get(event_type, EVENT_COLORS["Other"])["bg"]


# ── Modal dialogs ────────────────────────────────────────────────────

@st.dialog("Event Details", width="large")
def _view_event_dialog(event_id):
    """Modal popup showing event details with Edit / Delete / Mark Completed."""
    from database import get_event, update_event, delete_event
    evt = get_event(event_id)
    if not evt:
        st.error("Event not found.")
        return

    etype = evt.get("event_type", "Other")
    color = _color(etype)
    st.markdown(f'<span style="background:{color}; color:#fff; padding:4px 10px; border-radius:4px;">{etype}</span>', unsafe_allow_html=True)
    st.markdown(f"### {evt.get('label', 'Event')}")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Date:** {evt.get('scheduled_date', 'N/A')}")
        st.markdown(f"**Time:** {evt.get('scheduled_time', 'N/A')}")
    with col2:
        st.markdown(f"**Status:** {evt.get('status', 'N/A')}")
        if evt.get("practice_name"):
            st.markdown(f"**Practice:** {evt['practice_name']}")

    if evt.get("notes"):
        st.markdown(f"**Notes:** {evt['notes']}")

    st.markdown("---")

    # Edit mode toggle
    if st.session_state.get("cal_edit_mode"):
        with st.form("edit_event_form"):
            etypes = ["Lunch", "Cookie Visit", "Call", "Flyer", "Thank You Letter", "Other"]
            try:
                idx = etypes.index(etype) if etype in etypes else 0
            except Exception:
                idx = 0
            new_type = st.selectbox("Type", etypes, index=idx)

            label = st.text_input("Label", value=evt.get("label", ""))

            sd = (evt.get("scheduled_date") or "")[:10]
            try:
                dval = datetime.strptime(sd, "%Y-%m-%d") if sd else datetime.now()
            except Exception:
                dval = datetime.now()
            new_date = st.date_input("Date", value=dval)
            new_time = st.text_input("Time", value=evt.get("scheduled_time", "12:00"))

            status_opts = ["Scheduled", "Completed", "Cancelled"]
            cur_status = evt.get("status", "Scheduled")
            try:
                si = status_opts.index(cur_status) if cur_status in status_opts else 0
            except Exception:
                si = 0
            new_status = st.selectbox("Status", status_opts, index=si)

            new_notes = st.text_area("Notes", value=evt.get("notes", ""))

            col_s, col_c = st.columns(2)
            with col_s:
                save = st.form_submit_button("Save Changes", type="primary", use_container_width=True)
            with col_c:
                cancel = st.form_submit_button("Cancel", use_container_width=True)

            if save:
                update_event(event_id, {
                    "event_type": new_type,
                    "label": label,
                    "scheduled_date": new_date.isoformat(),
                    "scheduled_time": new_time,
                    "status": new_status,
                    "notes": new_notes,
                })
                st.session_state.cal_edit_mode = False
                st.session_state.active_event_id = None
                st.rerun()

            if cancel:
                st.session_state.cal_edit_mode = False
                st.rerun()
    else:
        col_edit, col_complete, col_del, col_close = st.columns(4)
        with col_edit:
            if st.button("Edit", use_container_width=True, type="primary"):
                st.session_state.cal_edit_mode = True
                st.rerun()
        with col_complete:
            if evt.get("status") != "Completed":
                if st.button("Mark Completed", use_container_width=True):
                    update_event(event_id, {"status": "Completed"})
                    st.session_state.active_event_id = None
                    st.rerun()
        with col_del:
            if st.session_state.get("cal_confirm_delete"):
                st.warning("Are you sure you want to delete this event?")
                yes_col, no_col = st.columns(2)
                with yes_col:
                    if st.button("Yes, Delete", type="primary"):
                        delete_event(event_id)
                        st.session_state.cal_confirm_delete = False
                        st.session_state.active_event_id = None
                        st.rerun()
                with no_col:
                    if st.button("No, Keep"):
                        st.session_state.cal_confirm_delete = False
                        st.rerun()
            else:
                if st.button("Delete", use_container_width=True):
                    st.session_state.cal_confirm_delete = True
                    st.rerun()
        with col_close:
            if st.button("Close", use_container_width=True):
                st.session_state.active_event_id = None
                st.session_state.cal_edit_mode = False
                st.rerun()


@st.dialog("Create Event", width="large")
def _create_event_dialog(date_str):
    """Modal popup for creating a new event on a given date."""
    from database import get_all_practices, create_event
    st.markdown(f"### Add New Event — {date_str}")

    with st.form("create_event_form"):
        etypes = ["Lunch", "Cookie Visit", "Call", "Flyer", "Thank You Letter", "Other"]
        etype = st.selectbox("Event Type", etypes)

        label = st.text_input("Label / Description", placeholder="e.g. Lunch - ABC Medical")

        # Practice selector
        try:
            practices = get_all_practices(status_filter="Active")
            practice_opts = ["(None)"] + [p["name"] for p in practices]
            practice_ids = [None] + [p["id"] for p in practices]
        except Exception:
            practice_opts = ["(None)"]
            practice_ids = [None]
        selected_practice = st.selectbox("Practice (optional)", practice_opts)
        practice_id = practice_ids[practice_opts.index(selected_practice)] if selected_practice != "(None)" else None

        try:
            dval = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            dval = datetime.now()
        new_date = st.date_input("Date", value=dval)
        new_time = st.text_input("Time", value="12:00 PM", placeholder="11:30 AM")
        notes = st.text_area("Notes", height=80)

        col_s, col_c = st.columns(2)
        with col_s:
            submitted = st.form_submit_button("Save", type="primary", use_container_width=True)
        with col_c:
            cancelled = st.form_submit_button("Cancel", use_container_width=True)

        if submitted:
            final_label = label or f"{etype} - {selected_practice if selected_practice != '(None)' else ''}"
            data = {
                "event_type": etype,
                "label": final_label,
                "scheduled_date": new_date.isoformat(),
                "scheduled_time": new_time,
                "status": "Scheduled",
                "notes": notes,
                "created_by": "ui",
            }
            if practice_id:
                data["practice_id"] = practice_id
            try:
                create_event(data)
            except Exception:
                st.error("Failed to create event.")
            st.session_state.active_event_date = None
            st.rerun()

        if cancelled:
            st.session_state.active_event_date = None
            st.rerun()


# ── Main page ────────────────────────────────────────────────────────

def show_calendar():
    st.markdown("## Outreach Calendar")

    # Session state defaults
    st.session_state.setdefault("cal_year", datetime.now().year)
    st.session_state.setdefault("cal_month", datetime.now().month)
    st.session_state.setdefault("cal_edit_mode", False)
    st.session_state.setdefault("cal_confirm_delete", False)

    has_data = db_exists()

    year = st.session_state.cal_year
    month = st.session_state.cal_month

    # ── Navigation: Prev / Today / Next + Month/Year selectors ────
    nav_c1, nav_c2, nav_c3, nav_c4, nav_c5 = st.columns([1, 1, 1, 1, 2])
    with nav_c1:
        if st.button("< Prev Month", use_container_width=True):
            if month == 1:
                st.session_state.cal_year = year - 1
                st.session_state.cal_month = 12
            else:
                st.session_state.cal_month = month - 1
            st.rerun()
    with nav_c2:
        if st.button("Today", use_container_width=True):
            st.session_state.cal_year = datetime.now().year
            st.session_state.cal_month = datetime.now().month
            st.rerun()
    with nav_c3:
        if st.button("Next Month >", use_container_width=True):
            if month == 12:
                st.session_state.cal_year = year + 1
                st.session_state.cal_month = 1
            else:
                st.session_state.cal_month = month + 1
            st.rerun()
    with nav_c4:
        new_month = st.selectbox(
            "Month", range(1, 13),
            index=month - 1,
            format_func=lambda m: calendar.month_name[m],
            key="cal_month_sel",
            label_visibility="collapsed",
        )
        if new_month != month:
            st.session_state.cal_month = new_month
            st.rerun()
    with nav_c5:
        new_year = st.number_input("Year", min_value=2024, max_value=2030, value=year, key="cal_year_sel", label_visibility="collapsed")
        if new_year != year:
            st.session_state.cal_year = new_year
            st.rerun()

    # Re-read after potential changes
    year = st.session_state.cal_year
    month = st.session_state.cal_month

    month_name = calendar.month_name[month]
    st.markdown(f"### {month_name} {year}")

    if not has_data:
        st.info("No data loaded yet. Go to **Settings > Data Import** to upload your provider data.")

    # ── Legend ─────────────────────────────────────────────────────
    legend_items = [
        ("Lunches", "#007bff", "cal-event-blue"),
        ("Cookie Visits", "#28a745", "cal-event-green"),
        ("Flyers", "#ffc107", "cal-event-yellow"),
        ("Thank You Letters", "#e83e8c", "cal-event-pink"),
    ]
    legend_html = " &nbsp; ".join(
        f'<span class="{css}">{name}</span>' for name, _, css in legend_items
    )
    st.markdown(legend_html, unsafe_allow_html=True)

    # ── + Add Event button ────────────────────────────────────────
    if has_data:
        add_col, export_col, _ = st.columns([1, 1, 4])
        with add_col:
            if st.button("+ Add Event", type="primary"):
                today_str = f"{year}-{month:02d}-{min(datetime.now().day, calendar.monthrange(year, month)[1]):02d}"
                st.session_state.active_event_date = today_str
                st.session_state.active_event_id = None
                st.rerun()

    st.markdown("---")

    # Gather events for the month (empty dict if no data)
    events = _gather_events(year, month) if has_data else {}

    # Build calendar grid
    cal_obj = calendar.Calendar(firstweekday=6)  # Sunday start
    month_days = cal_obj.monthdayscalendar(year, month)

    # Header row
    day_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    header_cols = st.columns(7)
    for i, name in enumerate(day_names):
        header_cols[i].markdown(f"**{name}**")

    # Calendar cells
    for week in month_days:
        cols = st.columns(7)
        for i, day in enumerate(week):
            with cols[i]:
                if day == 0:
                    st.markdown("&nbsp;", unsafe_allow_html=True)
                else:
                    date_str = f"{year}-{month:02d}-{day:02d}"
                    day_events = events.get(date_str, [])
                    is_today = (datetime.now().year == year and datetime.now().month == month and datetime.now().day == day)

                    # Cell background: highlight today
                    bg = "#1e3a5f" if is_today else "#1e1e2f"
                    border = "2px solid #4CAF50" if is_today else "1px solid #333"

                    html = f'<div style="background:{bg}; padding:4px; border-radius:4px; min-height:80px; border:{border};">'
                    day_label = f'<strong style="color:#FFFFFF;">{">> " if is_today else ""}{day}</strong><br>'
                    html += day_label

                    for evt in day_events[:3]:
                        css = _css_class(evt.get("type", "Other"))
                        html += f'<span class="{css}">{evt.get("label","")[:22]}</span><br>'

                    if len(day_events) > 3:
                        html += f'<small style="color:#aaa;">+{len(day_events)-3} more</small>'

                    html += '</div>'
                    st.markdown(html, unsafe_allow_html=True)

                    # Buttons: "+" to add, clickable events to view/edit
                    btn_cols = st.columns([1, 3])
                    with btn_cols[0]:
                        if st.button("+", key=f"add_{date_str}", help="Add event on this date"):
                            st.session_state.active_event_date = date_str
                            st.session_state.active_event_id = None
                            st.rerun()
                    with btn_cols[1]:
                        for evt in day_events:
                            if isinstance(evt, dict) and evt.get("id"):
                                elabel = f"{evt.get('label','')[:16]}"
                                if st.button(elabel, key=f"view_{evt['id']}", help="Click to view/edit"):
                                    st.session_state.active_event_id = evt["id"]
                                    st.session_state.active_event_date = None
                                    st.session_state.cal_edit_mode = False
                                    st.session_state.cal_confirm_delete = False
                                    st.rerun()

    # ── ICS Export ────────────────────────────────────────────────
    st.markdown("---")

    # Export ALL events this month (not just lunches)
    all_month_events = []
    for date_str, evts in sorted(events.items()):
        for evt in evts:
            all_month_events.append({
                "Date": date_str,
                "Type": evt["type"],
                "Details": evt["label"],
            })

    # ICS export for all scheduled events
    try:
        if has_data:
            from database import get_lunches
            lunches_this_month = [l for l in get_lunches(status_filter="Scheduled")
                                  if (l.get("scheduled_date") or "")[:7] == f"{year}-{month:02d}"]
        else:
            lunches_this_month = []
    except Exception:
        lunches_this_month = []

    exp_col1, exp_col2 = st.columns([1, 4])
    with exp_col1:
        if lunches_this_month or all_month_events:
            ics_text = _build_ics_for_month(year, month, lunches_this_month, events)
            st.download_button(
                f"Export Month to Outlook (.ics)",
                data=ics_text,
                file_name=f"nhcc_calendar_{year}_{month:02d}.ics",
                mime="text/calendar",
                use_container_width=True,
            )

    # Events list table
    st.markdown("### Events This Month")
    if all_month_events:
        import pandas as pd
        df = pd.DataFrame(all_month_events)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No events this month.")

    # ── Render modals if active ───────────────────────────────────
    if has_data:
        if st.session_state.get("active_event_id"):
            _view_event_dialog(st.session_state.active_event_id)
        elif st.session_state.get("active_event_date"):
            _create_event_dialog(st.session_state.active_event_date)


def _build_ics_for_month(year, month, lunches, events_dict):
    """Build an ICS file for the whole month."""
    import re as _re

    ics_lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//NHCC//Outreach Dashboard//EN"]

    # Lunches with full detail
    for l in lunches:
        hour, minute = 12, 0
        t = l.get("scheduled_time", "") or ""
        m = _re.match(r'(\d{1,2}):?(\d{2})?\s*(AM|PM|am|pm)?', t.strip())
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2) or 0)
            ampm = (m.group(3) or "").upper()
            if ampm == "PM" and hour < 12:
                hour += 12
            elif ampm == "AM" and hour == 12:
                hour = 0
        ds = l.get("scheduled_date", "")[:10].replace("-", "")
        dtstart = f"{ds}T{hour:02d}{minute:02d}00"
        dtend_h = hour + 1
        dtend = f"{ds}T{dtend_h:02d}{minute:02d}00"
        uid = f"nhcc-lunch-{l['id']}@nhcc"
        ics_lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTART:{dtstart}",
            f"DTEND:{dtend}",
            f"SUMMARY:Lunch - {l.get('practice_name', '')}",
            f"LOCATION:{l.get('restaurant', 'TBD')}",
            f"DESCRIPTION:Attendees: {l.get('staff_count', '')}\\nConfirmed with: {l.get('confirmed_with', '')}",
            "END:VEVENT",
        ]

    # Other events from the events table
    for date_str, evts in events_dict.items():
        for evt in evts:
            if evt.get("type") == "Lunch":
                continue  # Already exported above with more detail
            ds = date_str.replace("-", "")
            uid = f"nhcc-evt-{ds}-{evt.get('label','').replace(' ','')[:20]}@nhcc"
            ics_lines += [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTART;VALUE=DATE:{ds}",
                f"SUMMARY:{evt.get('label', evt.get('type', 'Event'))}",
                "END:VEVENT",
            ]

    ics_lines.append("END:VCALENDAR")
    return "\r\n".join(ics_lines) + "\r\n"


def _gather_events(year: int, month: int) -> dict:
    """Gather all events for a given month. Returns {date_str: [event_dicts]}."""
    events = {}
    month_start = f"{year}-{month:02d}-01"
    month_end = f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]}"

    def add_event(date_str, event_type, label, eid=None):
        if not date_str:
            return
        day = (date_str or "")[:10]
        if month_start <= day <= month_end:
            entry = {"type": event_type, "label": label}
            if eid:
                entry["id"] = eid
            events.setdefault(day, []).append(entry)

    try:
        from database import get_contact_log, get_lunches, get_cookie_visits, get_flyer_campaigns
        from database import get_all_practices, get_thank_yous, list_events

        # Contacts (calls, emails, etc.)
        contacts = get_contact_log(limit=500)
        for c in contacts:
            add_event(c.get("contact_date"), "Call",
                      f"{c.get('contact_type', 'Contact')}: {c.get('practice_name', '')}")

        # Lunches
        lunches = get_lunches()
        for l in lunches:
            if l.get("scheduled_date"):
                add_event(l["scheduled_date"], "Lunch",
                          f"Lunch: {l.get('practice_name', '')} ({l.get('status', '')})")

        # Cookie visits
        cookies = get_cookie_visits()
        for cv in cookies:
            add_event(cv.get("visit_date"), "Cookie Visit",
                      f"Cookies: {cv.get('practice_name', '')}")

        # Flyer campaigns
        campaigns = get_flyer_campaigns()
        for fc in campaigns:
            add_event(fc.get("sent_date"), "Flyer",
                      f"Flyer: {fc.get('flyer_name', '')}")

        # Thank you letters
        try:
            practices = get_all_practices(status_filter="Active")
            for p in practices:
                tys = get_thank_yous(practice_id=p["id"], status_filter="Pending")
                for ty in tys:
                    add_event(ty.get("created_at"), "Thank You Letter",
                              f"Thank You: {p['name']}")
        except Exception:
            pass

        # Custom events table
        try:
            evts = list_events(month=month, year=year)
            for e in evts:
                add_event(e.get("scheduled_date"), e.get("event_type", "Other"),
                          e.get("label", ""), eid=e.get("id"))
        except Exception:
            pass

    except Exception:
        pass  # No database available — return empty events

    return events
