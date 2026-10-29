
import json
import uuid
from pathlib import Path

import streamlit as st
from langgraph.types import Command
from src.graph import build_graph


st.set_page_config(
    page_title="Ticket Triage Bot",
    page_icon="🎫",
    layout="wide",
)

st.title("🎫 Support Ticket Triage Bot")
st.write(
    "Classify support tickets, retrieve knowledge, draft replies, "
    "and review decisions."
)


@st.cache_resource
def get_graph():
    return build_graph()


graph = get_graph()

# Store manual-ticket state across Streamlit reruns.
if "thread_id" not in st.session_state:
    st.session_state.thread_id = None

if "pending_review" not in st.session_state:
    st.session_state.pending_review = False

if "ticket_result" not in st.session_state:
    st.session_state.ticket_result = None

if "sample_results" not in st.session_state:
    st.session_state.sample_results = None


def start_ticket(ticket_id, customer_tier, message):
    thread_id = f"manual-{uuid.uuid4().hex}"
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "ticket_id": ticket_id,
        "customer_tier": customer_tier,
        "ticket_text": message,
        "audit_log": [],
    }

    result = graph.invoke(initial_state, config=config)

    st.session_state.thread_id = thread_id
    st.session_state.ticket_result = result
    st.session_state.pending_review = bool(result.get("__interrupt__"))


def resume_review(decision):
    config = {
        "configurable": {
            "thread_id": st.session_state.thread_id
        }
    }

    result = graph.invoke(Command(resume=decision), config=config)

    st.session_state.ticket_result = result
    st.session_state.pending_review = bool(result.get("__interrupt__"))


def run_sample_file():
    sample_path = Path("documents/sample_tickets.json")

    with sample_path.open("r", encoding="utf-8") as file:
        tickets = json.load(file)

    results = []
    run_id = uuid.uuid4().hex[:8]

    for ticket in tickets:
        ticket_id = ticket["ticket_id"]
        config = {
            "configurable": {
                "thread_id": f"sample-{run_id}-{ticket_id}"
            }
        }

        initial_state = {
            **ticket,
            "ticket_text": ticket["message"],
            "audit_log": [],
        }

        result = graph.invoke(initial_state, config=config)
        review_handling = "Not required"

        # For this batch demonstration only, automatically approve
        # tickets that pause for human review.
        if result.get("__interrupt__"):
            review_handling = "Demo auto-approval"
            result = graph.invoke(
                Command(resume={"action": "approve"}),
                config=config,
            )

        results.append({
            "Ticket ID": ticket_id,
            "Customer Tier": ticket.get("customer_tier", "free"),
            "Category": result.get("category", ""),
            "Priority": result.get("priority", ""),
            "Sentiment": result.get("sentiment", ""),
            "Draft Attempts": result.get("draft_count", 0),
            "Outcome": result.get("outcome", "unknown"),
            "Review Handling": review_handling,
            "Escalation Reason": result.get("escalation_reason") or "",
            "Final Reply": result.get("final_response") or "",
            "Audit Log": result.get("audit_log", []),
            "Customer Message": ticket["message"],
        })

    return results


ticket_tab, sample_tab = st.tabs(
    ["📝 Process a Ticket", "📊 Sample File Results"]
)


# --------------------------------------------------
# TAB 1: PROCESS A SINGLE TICKET
# --------------------------------------------------
with ticket_tab:
    st.subheader("Submit a support ticket")

    with st.form("ticket_form"):
        ticket_id = st.text_input("Ticket ID", value="T-2001")

        customer_tier = st.selectbox(
            "Customer tier",
            ["free", "pro", "enterprise"],
        )

        message = st.text_area(
            "Customer message",
            placeholder="Describe the customer's issue...",
            height=150,
        )

        submitted = st.form_submit_button(
            "Process ticket",
            type="primary",
        )

    if submitted:
        if not ticket_id.strip() or not message.strip():
            st.error("Enter both a ticket ID and a customer message.")
        else:
            try:
                start_ticket(
                    ticket_id.strip(),
                    customer_tier,
                    message.strip(),
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Could not process ticket: {exc}")

    result = st.session_state.ticket_result

    if result:
        st.divider()
        st.subheader("Ticket results")

        col1, col2, col3 = st.columns(3)
        col1.metric("Category", result.get("category", "Pending"))
        col2.metric("Priority", result.get("priority", "Pending"))
        col3.metric("Sentiment", result.get("sentiment", "Pending"))

        if st.session_state.pending_review:
            st.warning("This ticket requires human review.")

            interrupt_data = result["__interrupt__"][0].value
            draft = interrupt_data.get("draft_response", "")

            st.text_area(
                "Draft reply",
                value=draft,
                height=200,
                disabled=True,
                key=f"review_draft_{st.session_state.thread_id}",
            )

            decision = st.radio(
                "Choose an action",
                ["Approve", "Edit and approve", "Reject"],
                key=f"decision_{st.session_state.thread_id}",
            )

            edited_response = draft
            rejection_reason = ""

            if decision == "Edit and approve":
                edited_response = st.text_area(
                    "Edit the reply",
                    value=draft,
                    height=200,
                    key=f"edited_{st.session_state.thread_id}",
                )

            if decision == "Reject":
                rejection_reason = st.text_input(
                    "Reason for rejection",
                    key=f"reason_{st.session_state.thread_id}",
                )

            if st.button("Submit review", type="primary"):
                try:
                    if decision == "Approve":
                        payload = {"action": "approve"}
                    elif decision == "Edit and approve":
                        payload = {
                            "action": "approve_with_edit",
                            "edited_response": edited_response,
                        }
                    else:
                        payload = {
                            "action": "reject",
                            "reason": rejection_reason
                            or "Rejected by human reviewer.",
                        }

                    resume_review(payload)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not submit review: {exc}")

        else:
            st.write(f"**Outcome:** {result.get('outcome', 'processing')}")

            if result.get("escalation_reason"):
                st.warning(
                    f"Escalation reason: {result['escalation_reason']}"
                )

            if result.get("final_response"):
                st.subheader("Final reply")
                st.write(result["final_response"])

        with st.expander("Audit log"):
            for entry in result.get("audit_log", []):
                st.write(f"- {entry}")


# --------------------------------------------------
# TAB 2: RESULTS FROM THE SAMPLE JSON FILE
# --------------------------------------------------
with sample_tab:
    st.subheader("Sample File Results")

    st.write(
        "Run every ticket in documents/sample_tickets.json and "
        "view the classification, workflow outcome, and final reply."
    )

    st.caption(
        "Demo behavior: tickets requiring human review are automatically "
        "approved for this batch run. This does not represent a real "
        "human approval."
    )

    if st.button("Run Sample File", type="primary"):
        try:
            with st.spinner("Processing sample tickets..."):
                st.session_state.sample_results = run_sample_file()
        except Exception as exc:
            st.error(f"Could not process the sample file: {exc}")

    sample_results = st.session_state.sample_results

    if sample_results is not None:
        st.success(f"Processed {len(sample_results)} sample tickets.")

        total = len(sample_results)
        escalated = sum(
            row["Outcome"] == "escalated" for row in sample_results
        )
        auto_replied = sum(
            row["Outcome"] == "auto_replied" for row in sample_results
        )
        human_approved = sum(
            row["Outcome"] == "human_approved" for row in sample_results
        )

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Tickets", total)
        col2.metric("Auto-replied", auto_replied)
        col3.metric("Human-approved", human_approved)
        col4.metric("Escalated", escalated)

        st.subheader("All Ticket Results")

        table_rows = [
            {key: row[key] for key in [
                "Ticket ID",
                "Customer Tier",
                "Category",
                "Priority",
                "Sentiment",
                "Draft Attempts",
                "Outcome",
                "Review Handling",
                "Escalation Reason",
            ]}
            for row in sample_results
        ]

        st.dataframe(
            table_rows,
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Individual Ticket Details")

        for row in sample_results:
            with st.expander(
                f"{row['Ticket ID']} — {row['Outcome']}"
            ):
                st.write("**Customer message:**")
                st.write(row["Customer Message"])

                st.write(
                    f"**Classification:** {row['Category']} / "
                    f"{row['Priority']} / {row['Sentiment']}"
                )

                st.write(f"**Draft attempts:** {row['Draft Attempts']}")
                st.write(f"**Outcome:** {row['Outcome']}")

                if row["Escalation Reason"]:
                    st.warning(row["Escalation Reason"])

                if row["Final Reply"]:
                    st.write("**Final reply:**")
                    st.write(row["Final Reply"])

                st.write("**Audit log:**")
                for entry in row["Audit Log"]:
                    st.write(f"- {entry}")

        export_data = [
            {
                key: value
                for key, value in row.items()
                if key != "Audit Log"
            }
            for row in sample_results
        ]

        st.download_button(
            "Download Results as JSON",
            data=json.dumps(export_data, indent=2),
            file_name="sample_ticket_results.json",
            mime="application/json",
        )
