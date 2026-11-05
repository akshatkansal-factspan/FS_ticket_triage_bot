import traceback

from src.databases import (
    create_ticket,
    generate_ticket_id,
    save_ticket_result,
    get_ticket_details,
)

from src.nodes import process_one
from src.config import get_mock_data


def process_ticket(customer_id, subject, ticket_text):

    ticket_id = generate_ticket_id()

    create_ticket(
        ticket_id=ticket_id,
        customer_id=customer_id,
        subject=subject,
        ticket_text=ticket_text,
    )

    ticket = {
        "ticket_id": ticket_id,
        "customer_id": customer_id,
        "ticket_text": ticket_text,
    }

    result = process_one(ticket, subject)

    save_ticket_result(result)

    return result


def process_mock_tickets():

    results = []

    mock_data = get_mock_data()

    for ticket in mock_data.get("tickets", []):

        try:

            ticket_id = ticket["ticket_id"]

            # Avoid processing the same mock ticket twice.
            existing = get_ticket_details(ticket_id)

            if existing:
                results.append({
                    "ticket_id": ticket_id,
                    "customer_id": ticket["customer_id"],
                    "category": existing.get("category"),
                    "priority": existing.get("priority"),
                    "sentiment": existing.get("sentiment"),
                    "outcome": existing.get("outcome"),
                    "escalation_reason": existing.get(
                        "escalation_reason"
                    ),
                    "skipped": "already processed",
                })

                continue

            create_ticket(
                ticket_id=ticket_id,
                customer_id=ticket["customer_id"],
                subject=ticket.get(
                    "subject",
                    "Mock support request",
                ),
                ticket_text=ticket["ticket_text"],
                task=ticket.get("task", "mock"),
                ticket_date=ticket.get("date"),
            )

            result = process_one(ticket)

            save_ticket_result(result)

            results.append(result)

        except Exception:
            print(
                f"BATCH ERROR for {ticket.get('ticket_id')}:"
            )
            traceback.print_exc()

            results.append({
                "ticket_id": ticket.get("ticket_id"),
                "outcome": "error",
                "escalation_reason": "processing error",
            })

    return results