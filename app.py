import streamlit as st
import pandas as pd
import traceback

from src.databases import (
    refresh_database,
    get_customer_ids,
)

from src.graph import (
    process_ticket,
    process_mock_tickets,
)


def display_ticket_result(result):
    """Display ticket information in a readable format."""

    st.divider()
    st.subheader(f"Ticket {result.get('ticket_id', 'Unknown')}")

    # Status
    outcome = result.get("outcome", "processing")

    if outcome == "waiting_for_review":
        st.warning("Waiting for human review")
    elif outcome == "human_approved":
        st.success("Human approved")
    elif outcome == "auto_replied":
        st.success("Automatically processed")
    elif outcome == "escalated":
        st.error("Escalated to support team")
    else:
        st.info(outcome.replace("_", " ").title())

    # Ticket information
    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Customer ID", result.get("customer_id", "—"))
    col2.metric("Category", result.get("category", "—").title())
    col3.metric("Priority", result.get("priority", "—").title())
    col4.metric("Sentiment", result.get("sentiment", "—").title())

    st.markdown("### Ticket details")

    st.write("**Subject**")
    st.write(result.get("subject", "—"))

    st.write("**Customer message**")
    st.info(result.get("message", result.get("ticket_text", "—")))

    # Processing information
    col1, col2 = st.columns(2)
    col1.metric("Draft attempts", result.get("draft_count", 0))
    col2.metric(
        "PII detected",
        "Yes" if result.get("pii_redacted") else "No"
    )

    if result.get("escalation_reason"):
        st.warning(
            f"**Reason:** {result['escalation_reason']}"
        )

    # Draft response
    draft = result.get("draft") or result.get("draft_response")

    if draft:
        st.markdown("### Draft reply")
        st.text_area(
            "Generated response",
            value=draft,
            height=220,
            disabled=False,
            key=f"display_draft_{result.get('ticket_id', 'unknown')}",
        )

    # Final response
    final_response = result.get("final_response")

    if final_response:
        st.markdown("### Final response")
        st.success(final_response)

    # Issues
    issues = result.get("issues", [])

    if issues:
        st.markdown("### Identified issues")

        for index, issue in enumerate(issues, start=1):
            if isinstance(issue, dict):
                issue_text = issue.get("issue_text", "—")
                issue_category = issue.get("category", "other")
            else:
                issue_text = str(issue)
                issue_category = "other"

            with st.container(border=True):
                st.write(f"**Issue {index}:** {issue_text}")
                st.caption(f"Category: {issue_category.title()}")

st.set_page_config(
    page_title="Support Ticket Triage Bot",
    page_icon="🎫",
    layout="wide",
)

st.title("Support Ticket Triage Bot")


# --------------------------------------------------
# SIDEBAR: DATABASE REFRESH
# --------------------------------------------------

with st.sidebar:

    st.subheader("Database")

    if st.button(
        "Refresh database",
        type="primary",
        use_container_width=True,
    ):

        try:

            counts = refresh_database()

            st.success(
                "Database ready. "
                f"Seeded {counts['customers']} customers "
                f"and {counts['invoices']} invoices."
            )

        except Exception as exc:

            print("DATABASE REFRESH FAILED:")
            traceback.print_exc()

            st.error(
                f"Database refresh failed: {exc}"
            )


# --------------------------------------------------
# TWO APPLICATION TABS
# --------------------------------------------------

tab_new, tab_mock = st.tabs([
    "Create New Ticket",
    "Process Mock Tickets",
])


# ==================================================
# TAB 1: CREATE NEW TICKET
# ==================================================

with tab_new:

    st.subheader("Create a support ticket")

    try:
        customer_ids = get_customer_ids()

    except Exception as exc:

        customer_ids = []

        st.warning(
            "Could not load customers. "
            "Refresh the database first. "
            f"Details: {exc}"
        )

    with st.form("new_ticket_form"):

        customer_id = st.selectbox(
            "Customer ID",
            customer_ids,
            disabled=not customer_ids,
        )

        subject = st.text_input("Subject")

        message = st.text_area(
            "Message",
            height=150,
        )

        submitted = st.form_submit_button(
            "Submit and process ticket",
            type="primary",
            disabled=not customer_ids,
        )

    if submitted:

        if not subject.strip() or not message.strip():

            st.error(
                "Please enter both a subject and a message."
            )

        else:

            try:

                result = process_ticket(
                    customer_id=customer_id,
                    subject=subject.strip(),
                    ticket_text=message.strip(),
                )

                st.success(
                    f"Ticket {result['ticket_id']} "
                    f"processed: {result['outcome']}"
                )

                # Do not display the retained original PII map. 
                display_result = {
                    key: value
                    for key, value in result.items()
                    if key != "pii_originals_for_human_only"
                }

                display_ticket_result(display_result)

            except Exception as exc:

                print("MANUAL TICKET FAILED:")
                traceback.print_exc()

                st.error(
                    f"Ticket processing failed: {exc}"
                )


# ==================================================
# TAB 2: PROCESS MOCK TICKETS
# ==================================================

with tab_mock:

    st.subheader("Process all tickets from mock JSON")

    if st.button(
        "Ingest and process all mock tickets",
        type="primary",
    ):

        try:

            with st.spinner("Processing mock tickets..."):
                results = process_mock_tickets()

            st.success(
                f"Batch completed: {len(results)} tickets."
            )

            if results:

                # Summary table first.
                summary = [
                    {
                        key: result.get(key)
                        for key in [
                            "ticket_id",
                            "customer_id",
                            "category",
                            "priority",
                            "sentiment",
                            "draft_count",
                            "outcome",
                            "escalation_reason",
                        ]
                    }
                    for result in results
                ]

                st.markdown("### Summary")

                st.dataframe(
                    pd.DataFrame(summary),
                    use_container_width=True,
                    hide_index=True,
                )

                # Individual ticket details.
                st.markdown("### Individual ticket details")

                for result in results:

                    ticket_id = result.get(
                        "ticket_id",
                        "Unknown ticket",
                    )

                    outcome = result.get(
                        "outcome",
                        "unknown",
                    )

                    with st.expander(
                        f"{ticket_id} — {outcome}"
                    ):
                        display_ticket_result(result)

                        if result.get("refund"):
                            st.markdown("### Refund record")
                            st.write(result["refund"])

        except Exception as exc:

            print("MOCK BATCH FAILED:")
            traceback.print_exc()

            st.error(
                f"Batch processing failed: {exc}"
            )


st.divider()

st.caption(
    "Replies are stored as drafts in the database outbox. "
    "Refunds are recorded only; no email or payment is sent."
)