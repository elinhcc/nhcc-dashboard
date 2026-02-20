"""Calendar view: fully interactive monthly outreach calendar with color-coded events.

Events only appear on the calendar if they exist in the `events` table.
Fax sends, flyer sends, and thank-you letters are intentionally NOT shown here.
Only Lunches, Cookie Visits, manually-added events, and Recurring Reminders appear.
"""
import streamlit as st
from datetime import datetime, timedelta
import calendar
from utils import db_exists

# Color scheme: Blue = Lunches, Green = Cookie Visits, Orange = Reminders
EVENT_COLORS = {
    "Lunch":        {"bg": "#007bff", "css": "cal-event-blue"},
    "Cookie Visit": {"bg": "#28a745", "css": "cal-event-green"},
    "Reminder":     {"bg": "#FF8C42", "css": "cal-event-orange"},
    "Call":         {"bg": "#6c757d", "css": "cal-event-gray"},
    "Other":        {"bg": "#6c757d", "css": "cal-event-gray"},
}

# CSS class used as a "color marker" injected before each event button so that
# the adjacent-sibling CSS rule can color it correctly (`:has()` + `+` combinator).
_EVT_MARKER = {
    "Lunch":        "nhcc-evt-lunch",
    "Cookie Visit": "nhcc-evt-cookie",
    "Reminder":     "nhcc-evt-reminder",
    "Call":         "nhcc-evt-call",
    "Other":        "nhcc-evt-other",
}

# Event types that must NEVER appear on the calendar
_EXCLUDED_TYPES = {"Flyer", "Thank You Letter", "Fax Sent", "Fax", "flyer", "fax"}

# ── CSS injected once per page load ──────────────────────────────────
_CALENDAR_CSS = """
<style>
/* ─── NHCC Calendar — Compact, Outlook-style cell buttons ───────── */

/* Scope: all column elements that come AFTER the nhcc-cal-grid-start marker
   and live inside a 7-column horizontal week block.                        */

/* Remove extra vertical gaps between widgets inside calendar day columns */
div.element-container:has(.nhcc-cal-grid-start)
  ~ div.element-container
  div[data-testid="stHorizontalBlock"]
  div[data-testid="stColumn"]
  div.element-container {
    margin-bottom: 1px !important;
    padding-bottom: 0   !important;
}

/* Thin, compact buttons inside calendar day cells */
div.element-container:has(.nhcc-cal-grid-start)
  ~ div.element-container
  div[data-testid="stHorizontalBlock"]
  div[data-testid="stColumn"]
  button {
    padding:      1px 4px  !important;
    min-height:   20px     !important;
    height:       auto     !important;
    font-size:    0.72em   !important;
    border-radius:3px      !important;
    line-height:  1.3      !important;
    white-space:  normal   !important;
    text-align:   left     !important;
    width:        100%     !important;
    border:       none     !important;
    cursor:       pointer  !important;
}

/* Remove margin below the HTML day-header div */
div.element-container:has(.nhcc-cal-grid-start)
  ~ div.element-container
  div[data-testid="stHorizontalBlock"]
  div[data-testid="stColumn"]
  div.stMarkdown {
    margin-bottom: 0 !important;
}

/* ── Event button colors via adjacent marker divs ── */
div.element-container:has(.nhcc-evt-lunch)
  + div.element-container button {
    background: #007bff !important;
    color: white        !important;
}
div.element-container:has(.nhcc-evt-cookie)
  + div.element-container button {
    background: #28a745 !important;
    color: white        !important;
}
div.element-container:has(.nhcc-evt-reminder)
  + div.element-container button {
    background: #FF8C42 !important;
    color: white        !important;
}
div.element-container:has(.nhcc-evt-call)
  + div.element-container button,
div.element-container:has(.nhcc-evt-other)
  + div.element-container button {
    background: #5a6268 !important;
    color: white        !important;
}

/* "Add event" (＋) button — subtle, not competing with event buttons */
div.element-container:has(.nhcc-add-btn-marker)
  + div.element-container button {
    background: transparent !important;
    color: #888             !important;
    border: 1px dashed #555 !important;
    font-size: 0.7em        !important;
}
div.element-container:has(.nhcc-add-btn-marker)
  + div.element-container button:hover {
    background: #2a2a3f !important;
    color: #ccc         !important;
}
</style>
"""


def _css_class(event_type):
    return EVENT_COLORS.get(event_type, EVENT_COLORS["Other"])["css"]


def _color(event_type):
    return EVENT_COLORS.get(event_type, EVENT_COLORS["Other"])["bg"]


# ── Modal dialogs ────────────────────────────────────────────────────

@st.dialog("Event Details", width="large")
def _view_event_dialog(event_id):
    """Modal popup: view, edit, complete, or delete a calendar event."""
    from database import get_event, update_event, delete_event
    evt = get_event(event_id)
    if not evt:
        st.error("Event not found.")
        return

    etype = evt.get("event_type", "Other")
    color = _color(etype)
    st.markdown(
        f'<span style="background:{color}; color:#fff; padding:4px 10px; '
        f'border-radius:4px; font-weight:bold;">{etype}</span>',
        unsafe_allow_html=True,
    )
    st.markdown(f"### {evt.get('label', 'Event')}")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Date:** {(evt.get('scheduled_date') or 'N/A')[:10]}")
        if evt.get("scheduled_time"):
            st.markdown(f"**Time:** {evt['scheduled_time']}")
    with col2:
        st.markdown(f"**Status:** {evt.get('status', 'N/A')}")
        if evt.get("practice_name"):
            st.markdown(f"**Practice:** {evt['practice_name']}")
    if evt.get("notes"):
        st.markdown(f"**Notes:** {evt['notes']}")

    st.markdown("---")

    if st.session_state.get("cal_edit_mode"):
        # ── Edit form ──────────────────────────────────────────────
        with st.form("edit_event_form"):
            etypes = ["Lunch", "Cookie Visit", "Call", "Other"]
            idx = etypes.index(etype) if etype in etypes else 0
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
            si = status_opts.index(cur_status) if cur_status in status_opts else 0
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
        # ── Action buttons ─────────────────────────────────────────
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
                st.warning("Delete this event?")
                y_col, n_col = st.columns(2)
                with y_col:
                    if st.button("Yes, Delete", type="primary", use_container_width=True):
                        delete_event(event_id)
                        st.session_state.cal_confirm_delete = False
                        st.session_state.active_event_id = None
                        st.rerun()
                with n_col:
                    if st.button("No, Keep", use_container_width=True):
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


@st.dialog("Add Event", width="large")
def _create_event_dialog(date_str):
    """Modal popup for creating a new event on a given date."""
    from database import get_all_practices, create_event
    st.markdown(f"**Date:** {date_str}")

    with st.form("create_event_form"):
        etypes = ["Lunch", "Cookie Visit", "Call", "Other"]
        etype = st.selectbox("Event Type", etypes)
        label = st.text_input("Label / Description", placeholder="e.g. Lunch - ABC Medical")

        try:
            practices = get_all_practices(status_filter="Active")
            practice_opts = ["(None)"] + [p["name"] for p in practices]
            practice_ids  = [None]       + [p["id"]   for p in practices]
        except Exception:
            practice_opts = ["(None)"]
            practice_ids  = [None]
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
            submitted = st.form_submit_button("Save Event", type="primary", use_container_width=True)
        with col_c:
            cancelled = st.form_submit_button("Cancel", use_container_width=True)

        if submitted:
            final_label = label or f"{etype}{' - ' + selected_practice if selected_practice != '(None)' else ''}"
            data = {
                "event_type":     etype,
                "label":          final_label,
                "scheduled_date": new_date.isoformat(),
                "scheduled_time": new_time,
                "status":         "Scheduled",
                "notes":          notes,
                "created_by":     "ui",
            }
            if practice_id:
                data["practice_id"] = practice_id
            try:
                create_event(data)
            except Exception:
                st.error("Failed to save event.")
            st.session_state.active_event_date = None
            st.rerun()

        if cancelled:
            st.session_state.active_event_date = None
            st.rerun()


@st.dialog("Manage Monthly Reminders", width="large")
def _manage_reminders_dialog():
    """Modal for creating and deleting recurring monthly reminders."""
    from database import get_recurring_reminders, create_recurring_reminder, delete_recurring_reminder

    st.markdown("### Existing Reminders")
    reminders = get_recurring_reminders()
    if reminders:
        for r in reminders:
            col_name, col_day, col_del = st.columns([4, 2, 1])
            with col_name:
                st.markdown(f"**{r['name']}**")
            with col_day:
                st.markdown(f"Day {r['day_of_month']} of every month")
            with col_del:
                if st.button("🗑", key=f"del_reminder_{r['id']}", help="Delete this reminder"):
                    delete_recurring_reminder(r["id"])
                    st.rerun()
    else:
        st.info("No recurring reminders yet.")

    st.markdown("---")
    st.markdown("### Add New Reminder")
    with st.form("create_reminder_form"):
        name = st.text_input(
            "Reminder Name",
            value="Monthly Flyer Campaign Due",
            placeholder="e.g. Monthly Flyer Campaign Due",
        )
        day = st.number_input(
            "Day of Month", min_value=1, max_value=28, value=1,
            help="1–28 (28 avoids end-of-month issues in short months)",
        )
        col_s, col_c = st.columns(2)
        with col_s:
            submitted = st.form_submit_button("Add Reminder", type="primary", use_container_width=True)
        with col_c:
            cancelled = st.form_submit_button("Close", use_container_width=True)

        if submitted:
            if name.strip():
                create_recurring_reminder({"name": name.strip(), "day_of_month": int(day)})
                st.success(f"Reminder added — appears on day {day} of every month.")
                st.rerun()
            else:
                st.error("Please enter a reminder name.")
        if cancelled:
            st.session_state.active_reminder_dialog = False
            st.rerun()


# ── Main page ────────────────────────────────────────────────────────

def show_calendar():
    st.markdown("## Outreach Calendar")

    # ── Session state defaults ────────────────────────────────────
    st.session_state.setdefault("cal_year",             datetime.now().year)
    st.session_state.setdefault("cal_month",            datetime.now().month)
    st.session_state.setdefault("cal_edit_mode",        False)
    st.session_state.setdefault("cal_confirm_delete",   False)
    st.session_state.setdefault("active_reminder_dialog", False)

    has_data = db_exists()

    # ── One-time backfill: create events table entries for any lunches /
    #    cookie visits that predate the events table being the calendar source.
    if has_data and not st.session_state.get("cal_migrated"):
        try:
            from database import migrate_lunches_cookies_to_events
            migrate_lunches_cookies_to_events()
        except Exception:
            pass
        st.session_state.cal_migrated = True

    year  = st.session_state.cal_year
    month = st.session_state.cal_month

    # ── Navigation ────────────────────────────────────────────────
    nav_c1, nav_c2, nav_c3, nav_c4, nav_c5 = st.columns([1, 1, 1, 1, 2])
    with nav_c1:
        if st.button("◀ Prev", use_container_width=True):
            if month == 1:
                st.session_state.cal_year  = year - 1
                st.session_state.cal_month = 12
            else:
                st.session_state.cal_month = month - 1
            st.rerun()
    with nav_c2:
        if st.button("Today", use_container_width=True):
            st.session_state.cal_year  = datetime.now().year
            st.session_state.cal_month = datetime.now().month
            st.rerun()
    with nav_c3:
        if st.button("Next ▶", use_container_width=True):
            if month == 12:
                st.session_state.cal_year  = year + 1
                st.session_state.cal_month = 1
            else:
                st.session_state.cal_month = month + 1
            st.rerun()
    with nav_c4:
        new_month = st.selectbox(
            "Month", range(1, 13), index=month - 1,
            format_func=lambda m: calendar.month_name[m],
            key="cal_month_sel", label_visibility="collapsed",
        )
        if new_month != month:
            st.session_state.cal_month = new_month
            st.rerun()
    with nav_c5:
        new_year = st.number_input(
            "Year", min_value=2024, max_value=2030, value=year,
            key="cal_year_sel", label_visibility="collapsed",
        )
        if new_year != year:
            st.session_state.cal_year = new_year
            st.rerun()

    year  = st.session_state.cal_year
    month = st.session_state.cal_month

    st.markdown(f"### {calendar.month_name[month]} {year}")

    if not has_data:
        st.info("No data loaded. Go to **Settings > Data Import** to upload your provider data.")
        return

    # ── Legend ────────────────────────────────────────────────────
    legend_items = [
        ("Lunches",       "#007bff", "cal-event-blue"),
        ("Cookie Visits", "#28a745", "cal-event-green"),
        ("Reminders",     "#FF8C42", "cal-event-orange"),
    ]
    legend_html = " &nbsp; ".join(
        f'<span class="{css}" style="padding:2px 8px;border-radius:3px;">{name}</span>'
        for name, _color, css in legend_items
    )
    st.markdown(legend_html, unsafe_allow_html=True)

    # ── Top action buttons ────────────────────────────────────────
    add_col, remind_col, _ = st.columns([1, 1, 4])
    with add_col:
        if st.button("＋ Add Event", type="primary"):
            today_str = f"{year}-{month:02d}-{min(datetime.now().day, calendar.monthrange(year, month)[1]):02d}"
            st.session_state.active_event_date    = today_str
            st.session_state.active_event_id      = None
            st.session_state.active_reminder_dialog = False
            st.rerun()
    with remind_col:
        if st.button("🔔 Add Reminder"):
            st.session_state.active_reminder_dialog = True
            st.session_state.active_event_date      = None
            st.session_state.active_event_id        = None
            st.rerun()

    st.markdown("---")

    # ── Gather events ─────────────────────────────────────────────
    events = _gather_events(year, month)

    # ── Inject calendar CSS + grid-start marker ───────────────────
    st.markdown(_CALENDAR_CSS, unsafe_allow_html=True)
    st.markdown('<div class="nhcc-cal-grid-start" style="display:none"></div>',
                unsafe_allow_html=True)

    # ── Day-name header row ───────────────────────────────────────
    day_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    hdr = st.columns(7)
    for i, n in enumerate(day_names):
        hdr[i].markdown(f"<div style='text-align:center;font-weight:bold;color:#ccc;'>{n}</div>",
                        unsafe_allow_html=True)

    # ── Calendar grid ─────────────────────────────────────────────
    cal_obj    = calendar.Calendar(firstweekday=6)   # Sunday first
    month_days = cal_obj.monthdayscalendar(year, month)

    now = datetime.now()

    for week in month_days:
        cols = st.columns(7)
        for i, day in enumerate(week):
            with cols[i]:
                if day == 0:
                    # Empty padding cell
                    st.markdown(
                        '<div style="min-height:70px;background:#111;border:1px solid #222;'
                        'border-radius:4px;"></div>',
                        unsafe_allow_html=True,
                    )
                    continue

                date_str   = f"{year}-{month:02d}-{day:02d}"
                day_events = events.get(date_str, [])
                is_today   = (now.year == year and now.month == month and now.day == day)

                # ── Thin day-header bar ───────────────────────────
                bg     = "#1e3a5f" if is_today else "#1e1e2f"
                border = "2px solid #4CAF50" if is_today else "1px solid #333"
                today_mark = "📅 " if is_today else ""
                st.markdown(
                    f'<div style="background:{bg};border:{border};border-radius:4px 4px 0 0;'
                    f'padding:2px 5px;margin-bottom:0;">'
                    f'<strong style="color:#fff;font-size:0.85em;">{today_mark}{day}</strong>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                # ── Event buttons (colored via CSS marker trick) ──
                for evt in day_events[:4]:
                    eid    = evt.get("id")
                    etype  = evt.get("type", "Other")
                    label  = evt.get("label", "")[:24]
                    marker = _EVT_MARKER.get(etype, "nhcc-evt-other")

                    # Hidden marker div → CSS colors the next button
                    st.markdown(
                        f'<div class="{marker}" style="display:none"></div>',
                        unsafe_allow_html=True,
                    )
                    if eid:
                        if st.button(label, key=f"evt_{eid}", use_container_width=True,
                                     help="Click to view / edit"):
                            st.session_state.active_event_id      = eid
                            st.session_state.active_event_date    = None
                            st.session_state.cal_edit_mode        = False
                            st.session_state.cal_confirm_delete   = False
                            st.rerun()
                    else:
                        # Non-events-table item (reminder without ID) — show static chip
                        css = _css_class(etype)
                        st.markdown(
                            f'<span class="{css}" style="display:block;font-size:0.72em;'
                            f'margin:1px 0;padding:1px 4px;border-radius:3px;">{label}</span>',
                            unsafe_allow_html=True,
                        )

                if len(day_events) > 4:
                    st.caption(f"+{len(day_events) - 4} more")

                # ── "Add event on this date" button ───────────────
                st.markdown(
                    '<div class="nhcc-add-btn-marker" style="display:none"></div>',
                    unsafe_allow_html=True,
                )
                if st.button("＋", key=f"add_{date_str}", use_container_width=True,
                             help=f"Add event on {date_str}"):
                    st.session_state.active_event_date    = date_str
                    st.session_state.active_event_id      = None
                    st.rerun()

    # ── ICS Export (Outlook) ──────────────────────────────────────
    st.markdown("---")
    try:
        from database import get_lunches
        lunches_this_month = [
            l for l in get_lunches(status_filter="Scheduled")
            if (l.get("scheduled_date") or "")[:7] == f"{year}-{month:02d}"
        ]
    except Exception:
        lunches_this_month = []

    if lunches_this_month or events:
        exp_col, _ = st.columns([1, 4])
        with exp_col:
            ics_text = _build_ics_for_month(year, month, lunches_this_month, events)
            st.download_button(
                "Export to Outlook (.ics)",
                data=ics_text,
                file_name=f"nhcc_calendar_{year}_{month:02d}.ics",
                mime="text/calendar",
                use_container_width=True,
            )

    # ── Render modals ─────────────────────────────────────────────
    if st.session_state.get("active_event_id"):
        _view_event_dialog(st.session_state.active_event_id)
    elif st.session_state.get("active_event_date"):
        _create_event_dialog(st.session_state.active_event_date)
    elif st.session_state.get("active_reminder_dialog"):
        _manage_reminders_dialog()


# ── ICS builder ──────────────────────────────────────────────────────

def _build_ics_for_month(year, month, lunches, events_dict):
    import re as _re
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//NHCC//Outreach Dashboard//EN"]

    for l in lunches:
        hour, minute = 12, 0
        t = l.get("scheduled_time", "") or ""
        m = _re.match(r'(\d{1,2}):?(\d{2})?\s*(AM|PM|am|pm)?', t.strip())
        if m:
            hour   = int(m.group(1))
            minute = int(m.group(2) or 0)
            ampm   = (m.group(3) or "").upper()
            if ampm == "PM" and hour < 12:
                hour += 12
            elif ampm == "AM" and hour == 12:
                hour = 0
        ds     = l.get("scheduled_date", "")[:10].replace("-", "")
        dtstart = f"{ds}T{hour:02d}{minute:02d}00"
        dtend   = f"{ds}T{hour+1:02d}{minute:02d}00"
        uid     = f"nhcc-lunch-{l['id']}@nhcc"
        lines  += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTART:{dtstart}",
            f"DTEND:{dtend}",
            f"SUMMARY:Lunch - {l.get('practice_name', '')}",
            f"LOCATION:{l.get('restaurant', 'TBD')}",
            f"DESCRIPTION:Attendees: {l.get('staff_count', '')}\\nConfirmed with: {l.get('confirmed_with', '')}",
            "END:VEVENT",
        ]

    for date_str, evts in events_dict.items():
        for evt in evts:
            if evt.get("type") == "Lunch":
                continue  # already exported above with full detail
            ds  = date_str.replace("-", "")
            uid = f"nhcc-evt-{ds}-{(evt.get('label','') or '').replace(' ','')[:20]}@nhcc"
            lines += [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTART;VALUE=DATE:{ds}",
                f"SUMMARY:{evt.get('label', evt.get('type', 'Event'))}",
                "END:VEVENT",
            ]

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# ── Event data gatherer ───────────────────────────────────────────────

def _gather_events(year: int, month: int) -> dict:
    """Return {date_str: [event_dicts]} for the given month.

    Data source: ONLY the `events` table (all rows have integer IDs → all
    are rendered as clickable buttons).  Flyer, fax, and thank-you-letter
    types are filtered out at query time.  Recurring reminders are expanded
    for the month from the `recurring_reminders` table.
    """
    events     = {}
    month_start = f"{year}-{month:02d}-01"
    month_end   = f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]}"

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
        from database import list_events, get_recurring_reminders

        # ── Events table (lunches, cookies, manual, follow-ups) ───
        for e in list_events(month=month, year=year):
            etype = e.get("event_type", "Other")
            if etype in _EXCLUDED_TYPES:
                continue
            add_event(e.get("scheduled_date"), etype,
                      e.get("label", ""), eid=e.get("id"))

        # ── Recurring monthly reminders ───────────────────────────
        _, last_day = calendar.monthrange(year, month)
        for r in get_recurring_reminders():
            day = min(r["day_of_month"], last_day)
            add_event(f"{year}-{month:02d}-{day:02d}", "Reminder", r["name"])

    except Exception:
        pass

    return events
