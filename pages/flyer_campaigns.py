"""Flyer campaign page: select providers, preview, send via Outlook, campaign history."""
import streamlit as st
import pandas as pd
from datetime import datetime
from database import (
    get_all_practices, add_flyer_campaign, add_flyer_recipient,
    get_flyer_campaigns, get_flyer_recipients,
)
from outlook_integration import check_outlook_running, get_available_flyers, send_flyer_batch
from utils import load_config


def show_flyer_campaigns():
    st.markdown("## 📨 Flyer Campaigns")

    tab_send, tab_history = st.tabs(["Send Flyers", "Campaign History"])

    # ── Send Flyers ────────────────────────────────────────────────────
    with tab_send:
        # Check Outlook
        outlook_ok, outlook_msg = check_outlook_running()
        if outlook_ok:
            st.success("✅ Outlook is connected")
        else:
            st.warning(f"⚠️ {outlook_msg}")
            st.info("Please open Outlook and refresh this page.")

        # Select flyer
        st.markdown("### 1. Select Flyer")
        flyers = get_available_flyers()
        if not flyers:
            st.error("No flyers found in the flyer folder. Add PDF/PNG files to the Flyers folder.")
            return

        flyer_options = {f["name"]: f["path"] for f in flyers}
        selected_flyer = st.selectbox("Choose a flyer to send", list(flyer_options.keys()))

        if selected_flyer:
            flyer_info = next(f for f in flyers if f["name"] == selected_flyer)
            st.caption(f"Size: {flyer_info['size_kb']} KB")

        # Select recipients
        st.markdown("### 2. Select Recipients")
        practices = get_all_practices(status_filter="Active")
        fax_practices = [p for p in practices if p.get("fax_vonage_email")]

        st.caption(f"{len(fax_practices)} of {len(practices)} practices have fax/Vonage configured")

        col1, col2 = st.columns(2)
        with col1:
            location_filter = st.multiselect(
                "Filter by Location",
                ["Huntsville", "Woodlands", "Other"],
                default=["Huntsville", "Woodlands", "Other"],
            )

        filtered = [p for p in fax_practices if p.get("location_category") in location_filter]

        # Multi-select checkboxes
        select_all = st.checkbox("Select All", value=True)

        selected_practices = []
        for p in filtered:
            checked = st.checkbox(
                f"{p['name']} — {p.get('fax', '')} → {p.get('fax_vonage_email', '')}",
                value=select_all,
                key=f"flyer_sel_{p['id']}",
            )
            if checked:
                selected_practices.append(p)

        st.markdown(f"**{len(selected_practices)} recipients selected**")

        # Send
        st.markdown("### 3. Send")
        config = load_config()
        send_from = st.text_input("Send from email", value=config.get("send_from_email", ""))

        if st.button("🚀 Send Flyers", type="primary", disabled=not selected_practices or not outlook_ok):
            flyer_path = flyer_options[selected_flyer]

            # Create campaign record
            campaign_id = add_flyer_campaign({
                "sent_date": datetime.now().isoformat(),
                "flyer_name": selected_flyer,
                "sent_by": "Robbie",
            })

            # Build recipient list
            recipients = [{
                "practice_id": p["id"],
                "practice_name": p["name"],
                "vonage_email": p["fax_vonage_email"],
            } for p in selected_practices]

            # Send with progress bar
            progress = st.progress(0, text="Sending flyers...")
            results = send_flyer_batch(recipients, flyer_path, send_from)

            for i, result in enumerate(results):
                progress.progress((i + 1) / len(results), text=f"Sending to {result['practice_name']}...")
                add_flyer_recipient({
                    "campaign_id": campaign_id,
                    "practice_id": result["practice_id"],
                    "vonage_email": result["vonage_email"],
                    "status": result["status"],
                    "error_message": result.get("error_message", ""),
                })

            progress.progress(1.0, text="Complete!")

            # Summary
            sent = sum(1 for r in results if r["status"] == "Sent")
            failed = sum(1 for r in results if r["status"] == "Failed")
            st.success(f"Campaign complete! {sent} sent, {failed} failed.")

            if failed:
                st.markdown("**Failed sends:**")
                for r in results:
                    if r["status"] == "Failed":
                        st.error(f"{r['practice_name']}: {r['error_message']}")

    # ── Campaign History ───────────────────────────────────────────────
    with tab_history:
        campaigns = get_flyer_campaigns()
        if not campaigns:
            st.info("No campaigns sent yet.")
        else:
            for camp in campaigns:
                with st.expander(
                    f"📄 {camp['flyer_name']} — {camp.get('sent_date', '')[:10]} | "
                    f"{camp.get('sent_count', 0)} sent, {camp.get('failed_count', 0)} failed"
                ):
                    recipients = get_flyer_recipients(camp["id"])
                    if recipients:
                        df = pd.DataFrame(recipients)
                        display = ["practice_name", "vonage_email", "status", "error_message"]
                        available = [c for c in display if c in df.columns]
                        st.dataframe(df[available], use_container_width=True, hide_index=True)
