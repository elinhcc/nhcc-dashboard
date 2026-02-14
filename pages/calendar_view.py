"""Calendar view: monthly outreach calendar with color-coded events."""
import streamlit as st
from datetime import datetime, timedelta
import calendar
from database import get_lunches, get_contact_log, get_cookie_visits, get_flyer_campaigns
from database import list_events, get_event, create_event, update_event, delete_event


EVENT_COLORS = {
    "Lunch": "#28a745",
    "Call": "#007bff",
    "Cookie Visit": "#ff6f00",
    "Flyer": "#6f42c1",
    "Thank You Letter": "#e83e8c",
    "Other": "#6c757d",
}


def show_calendar():
    st.markdown("## 📅 Outreach Calendar")

    # Month/year selector
    col1, col2, col3 = st.columns([1, 1, 4])
    with col1:
        year = st.number_input("Year", min_value=2024, max_value=2030, value=datetime.now().year)
    with col2:
        month = st.number_input("Month", min_value=1, max_value=12, value=datetime.now().month)

    # Legend
    legend_cols = st.columns(len(EVENT_COLORS))
    for i, (etype, color) in enumerate(EVENT_COLORS.items()):
        legend_cols[i].markdown(
            f'<span style="color:{color};">●</span> {etype}',
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # Gather events for the month
    events = _gather_events(year, month)

    # Build calendar grid
    cal = calendar.Calendar(firstweekday=6)  # Sunday start
    month_days = cal.monthdayscalendar(year, month)

    # Header row
    day_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    header_cols = st.columns(7)
    for i, name in enumerate(day_names):
        header_cols[i].markdown(f"**{name}**")

    # Calendar cells (click day to create an event; click existing event to edit)
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

                    bg = "#e3f2fd" if is_today else "#f8f9fa"
                    html = f'<div style="background:{bg}; padding:4px; border-radius:4px; min-height:80px; border: 1px solid #dee2e6;">'
                    html += f'<strong>{"📌 " if is_today else ""}{day}</strong><br>'

                    for evt in day_events[:3]:
                        color = EVENT_COLORS.get(evt.get("type"), "#666")
                        html += f'<small style="color:{color};">● {evt.get("label","")[:20]}</small><br>'

                    if len(day_events) > 3:
                        html += f'<small style="color:#999;">+{len(day_events)-3} more</small>'

                    html += '</div>'
                    st.markdown(html, unsafe_allow_html=True)

                    # Action buttons: create new event or open existing
                    a_col, b_col = st.columns([1, 4])
                    with a_col:
                        if st.button("New", key=f"new_evt_{date_str}"):
                            st.session_state.active_event_date = date_str
                            st.session_state.active_event_id = None
                            st.experimental_rerun()
                    with b_col:
                        for evt in day_events:
                            if isinstance(evt, dict) and evt.get("id"):
                                label = f"{evt.get('type','Evt')}: {evt.get('label','')[:18]}"
                                if st.button(label, key=f"edit_evt_{evt['id']}"):
                                    st.session_state.active_event_id = evt['id']
                                    st.session_state.active_event_date = None
                                    st.experimental_rerun()

    # ICS export for scheduled lunches
    st.markdown("---")
    lunches_this_month = [l for l in get_lunches(status_filter="Scheduled")
                          if (l.get("scheduled_date") or "")[:7] == f"{year}-{month:02d}"]

    if lunches_this_month:
        ics_lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//NHCC//Outreach Dashboard//EN"]
        for l in lunches_this_month:
            import re as _re
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
            uid = f"nhcc-{l['id']}@nhcc"
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
        ics_lines.append("END:VCALENDAR")
        ics_text = "\r\n".join(ics_lines) + "\r\n"
        st.download_button(
            f"📅 Export {len(lunches_this_month)} Lunch(es) to Outlook (.ics)",
            data=ics_text,
            file_name=f"nhcc_lunches_{year}_{month:02d}.ics",
            mime="text/calendar",
        )

    # Events list for the month
    st.markdown("### Events This Month")

    all_month_events = []
    for date_str, evts in sorted(events.items()):
        for evt in evts:
            all_month_events.append({
                "Date": date_str,
                "Type": evt["type"],
                "Details": evt["label"],
            })

    if all_month_events:
        import pandas as pd
        df = pd.DataFrame(all_month_events)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No events this month.")

    # Event modal for create / edit / delete
    if st.session_state.get("active_event_date") or st.session_state.get("active_event_id"):
        with st.modal("Event"):
            eid = st.session_state.get("active_event_id")
            if eid:
                evt = get_event(eid) or {}
                st.markdown(f"### Edit Event — {evt.get('label','')}")
            else:
                evt = {"scheduled_date": st.session_state.get("active_event_date"), "scheduled_time": "12:00"}
                st.markdown("### Create Event")

            with st.form("event_form"):
                etypes = ["Lunch", "Cookie Visit", "Call", "Flyer", "Other"]
                try:
                    idx = etypes.index(evt.get('event_type')) if evt.get('event_type') in etypes else 0
                except Exception:
                    idx = 0
                etype = st.selectbox("Type", etypes, index=idx)
                # defensive date parsing
                sd = (evt.get('scheduled_date') or "")[:10]
                try:
                    dval = datetime.strptime(sd, "%Y-%m-%d") if sd else datetime.now()
                except Exception:
                    dval = datetime.now()
                date_val = st.date_input("Date", value=dval)
                time_val = st.text_input("Time", value=(evt.get('scheduled_time') or "12:00"))
                notes = st.text_area("Notes", value=evt.get('notes',''))
                col_save, col_del = st.columns([1,1])
                with col_save:
                    submitted = st.form_submit_button("Save")
                with col_del:
                    deleted = st.form_submit_button("Delete")

                if submitted:
                    data = {
                        "event_type": etype,
                        "label": f"{etype} - {evt.get('practice_name','')}",
                        "scheduled_date": date_val.isoformat(),
                        "scheduled_time": time_val,
                        "status": "Scheduled",
                        "notes": notes,
                        "created_by": "ui",
                    }
                    try:
                        if eid:
                            update_event(eid, data)
                        else:
                            create_event(data)
                    except Exception:
                        st.error("Failed to save event")
                    st.session_state.active_event_date = None
                    st.session_state.active_event_id = None
                    st.experimental_rerun()

                if deleted and eid:
                    try:
                        delete_event(eid)
                    except Exception:
                        st.error("Failed to delete event")
                    st.session_state.active_event_date = None
                    st.session_state.active_event_id = None
                    st.experimental_rerun()


def _gather_events(year: int, month: int) -> dict:
    """Gather all events for a given month. Returns {date_str: [event_dicts]}."""
    events = {}
    month_start = f"{year}-{month:02d}-01"
    month_end = f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]}"

    def add_event(date_str, event_type, label, eid=None):
        if not date_str:
            return
        day = (date_str or "")[:10]
        if day >= month_start and day <= month_end:
            entry = {"type": event_type, "label": label}
            if eid:
                entry["id"] = eid
            events.setdefault(day, []).append(entry)

    # Contacts
    contacts = get_contact_log(limit=500)
    for c in contacts:
        add_event(c.get("contact_date"), c.get("contact_type", "Other"),
                  f"{c.get('contact_type')}: {c.get('practice_name', '')}")

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

    # Custom events table
    try:
        evts = list_events(month=month, year=year)
        for e in evts:
            add_event(e.get("scheduled_date"), e.get("event_type", "Other"), e.get("label", ""), eid=e.get("id"))
    except Exception:
        # Be defensive; if events table isn't present or a bad record exists, ignore
        pass

    return events
