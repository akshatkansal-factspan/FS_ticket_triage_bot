import os
import traceback
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

from src.config import ROOT, get_mock_data

load_dotenv(ROOT / ".env")


def get_connection():
    required = [
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
    ]

    missing = [key for key in required if not os.getenv(key)]

    if missing:
        raise RuntimeError(
            "Missing database environment variables: "
            + ", ".join(missing)
        )

    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        sslmode=os.getenv("DB_SSLMODE", "require"),
        connect_timeout=15,
    )


@contextmanager
def db_cursor(commit=True):
    connection = get_connection()

    try:
        with connection.cursor(
            cursor_factory=RealDictCursor
        ) as cursor:
            yield cursor

        if commit:
            connection.commit()

    except Exception:
        connection.rollback()
        print("DATABASE ERROR:")
        traceback.print_exc()
        raise

    finally:
        connection.close()


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS customers (
        customer_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        tier TEXT NOT NULL,
        region TEXT NOT NULL,
        mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS invoices (
        invoice_id TEXT PRIMARY KEY,
        customer_id TEXT NOT NULL
            REFERENCES customers(customer_id),
        month DATE NOT NULL,
        amount_inr NUMERIC(12,2) NOT NULL,
        status TEXT NOT NULL,
        note TEXT
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS tickets (
        ticket_id TEXT PRIMARY KEY,
        customer_id TEXT NOT NULL
            REFERENCES customers(customer_id),
        subject TEXT NOT NULL,
        ticket_text TEXT NOT NULL,
        ticket_date DATE DEFAULT CURRENT_DATE,
        category TEXT,
        priority TEXT,
        sentiment TEXT,
        status TEXT DEFAULT 'new',
        outcome TEXT,
        final_response TEXT,
        escalation_reason TEXT,
        task TEXT
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS ticket_issues (
        issue_id TEXT PRIMARY KEY,
        ticket_id TEXT NOT NULL
            REFERENCES tickets(ticket_id) ON DELETE CASCADE,
        issue_number INTEGER NOT NULL,
        issue_text TEXT NOT NULL,
        category TEXT,
        response TEXT,
        status TEXT,
        UNIQUE(ticket_id, issue_number)
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS refunds (
        refund_id TEXT PRIMARY KEY,
        ticket_id TEXT NOT NULL
            REFERENCES tickets(ticket_id),
        invoice_id TEXT NOT NULL
            REFERENCES invoices(invoice_id),
        amount_inr NUMERIC(12,2) NOT NULL,
        status TEXT NOT NULL,
        approval_status TEXT NOT NULL,
        UNIQUE(invoice_id)
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS outbox (
        id BIGSERIAL PRIMARY KEY,
        ticket_id TEXT NOT NULL UNIQUE
            REFERENCES tickets(ticket_id),
        message TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'drafted'
    )
    """,
]


def refresh_database():
    """
    Create all tables if they do not exist.
    Seed only customers and invoices from mock JSON.
    """

    data = get_mock_data()

    with db_cursor() as cursor:

        for statement in SCHEMA:
            cursor.execute(statement)

        for customer in data.get("customers", []):

            cursor.execute(
                """
                INSERT INTO customers (
                    customer_id,
                    name,
                    tier,
                    region,
                    mfa_enabled
                )
                VALUES (%s, %s, %s, %s, %s)

                ON CONFLICT(customer_id)
                DO UPDATE SET
                    name = EXCLUDED.name,
                    tier = EXCLUDED.tier,
                    region = EXCLUDED.region,
                    mfa_enabled = EXCLUDED.mfa_enabled
                """,
                (
                    customer["customer_id"],
                    customer["name"],
                    customer["tier"],
                    customer["region"],
                    customer["mfa_enabled"],
                ),
            )

        for invoice in data.get("invoices", []):

            cursor.execute(
                """
                INSERT INTO invoices (
                    invoice_id,
                    customer_id,
                    month,
                    amount_inr,
                    status,
                    note
                )
                VALUES (
                    %s,
                    %s,
                    TO_DATE(%s, 'YYYY-MM'),
                    %s,
                    %s,
                    %s
                )

                ON CONFLICT(invoice_id)
                DO UPDATE SET
                    customer_id = EXCLUDED.customer_id,
                    month = EXCLUDED.month,
                    amount_inr = EXCLUDED.amount_inr,
                    status = EXCLUDED.status,
                    note = EXCLUDED.note
                """,
                (
                    invoice["invoice_id"],
                    invoice["customer_id"],
                    invoice["month"],
                    invoice["amount_inr"],
                    invoice["status"],
                    invoice.get("note"),
                ),
            )

    return {
        "customers": len(data.get("customers", [])),
        "invoices": len(data.get("invoices", [])),
    }


# Alias for the database refresh action.
seed_customers = refresh_database


def get_customer_ids():
    with db_cursor(commit=False) as cursor:
        cursor.execute(
            """
            SELECT customer_id
            FROM customers
            ORDER BY customer_id
            """
        )

        return [
            row["customer_id"]
            for row in cursor.fetchall()
        ]


def get_customer(customer_id):
    with db_cursor(commit=False) as cursor:
        cursor.execute(
            """
            SELECT *
            FROM customers
            WHERE customer_id = %s
            """,
            (customer_id,),
        )

        return cursor.fetchone()


def generate_ticket_id():
    """
    Generate the next ticket ID from the largest existing
    numeric ticket suffix. Empty table starts at T-0001.
    """

    with db_cursor() as cursor:

        cursor.execute(
            "SELECT pg_advisory_xact_lock(731904)"
        )

        cursor.execute(
            """
            SELECT COALESCE(
                MAX(
                    NULLIF(
                        SUBSTRING(
                            ticket_id FROM '^T-([0-9]+)$'
                        ),
                        ''
                    )::BIGINT
                ),
                0
            ) AS number
            FROM tickets
            WHERE ticket_id ~ '^T-[0-9]+$'
            """
        )

        number = int(cursor.fetchone()["number"]) + 1

        return f"T-{number:04d}"


def create_ticket(
    ticket_id,
    customer_id,
    subject,
    ticket_text,
    task="manual",
    ticket_date=None,
):
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tickets (
                ticket_id,
                customer_id,
                subject,
                ticket_text,
                task,
                ticket_date
            )
            VALUES (
                %s, %s, %s, %s, %s,
                COALESCE(%s, CURRENT_DATE)
            )
            """,
            (
                ticket_id,
                customer_id,
                subject,
                ticket_text,
                task,
                ticket_date,
            ),
        )


def save_ticket_result(result):
    with db_cursor() as cursor:

        cursor.execute(
            """
            UPDATE tickets
            SET
                category = %s,
                priority = %s,
                sentiment = %s,
                status = %s,
                outcome = %s,
                final_response = %s,
                escalation_reason = %s
            WHERE ticket_id = %s
            """,
            (
                result.get("category"),
                result.get("priority"),
                result.get("sentiment"),
                result.get("outcome", "processed"),
                result.get("outcome"),
                result.get("final_response"),
                result.get("escalation_reason"),
                result["ticket_id"],
            ),
        )

        for number, issue in enumerate(
            result.get("issues", []), 1
        ):
            cursor.execute(
                """
                INSERT INTO ticket_issues (
                    issue_id,
                    ticket_id,
                    issue_number,
                    issue_text,
                    category,
                    response,
                    status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)

                ON CONFLICT(issue_id)
                DO UPDATE SET
                    response = EXCLUDED.response,
                    status = EXCLUDED.status
                """,
                (
                    f'{result["ticket_id"]}-{number}',
                    result["ticket_id"],
                    number,
                    issue["issue_text"],
                    issue.get("category"),
                    issue.get("response"),
                    issue.get("status", "processed"),
                ),
            )

        refund = result.get("refund")

        if refund:
            cursor.execute(
                """
                INSERT INTO refunds (
                    refund_id,
                    ticket_id,
                    invoice_id,
                    amount_inr,
                    status,
                    approval_status
                )
                VALUES (%s, %s, %s, %s, %s, %s)

                ON CONFLICT(invoice_id) DO NOTHING
                """,
                (
                    refund["refund_id"],
                    result["ticket_id"],
                    refund["invoice_id"],
                    refund["amount_inr"],
                    refund["status"],
                    refund["approval_status"],
                ),
            )

        if result.get("draft"):
            cursor.execute(
                """
                INSERT INTO outbox (
                    ticket_id,
                    message,
                    status
                )
                VALUES (%s, %s, 'drafted')

                ON CONFLICT(ticket_id) DO NOTHING
                """,
                (
                    result["ticket_id"],
                    result["draft"],
                ),
            )


def get_ticket_summaries():
    with db_cursor(commit=False) as cursor:
        cursor.execute(
            """
            SELECT
                ticket_id,
                customer_id,
                subject,
                category,
                priority,
                sentiment,
                outcome,
                escalation_reason
            FROM tickets
            ORDER BY ticket_id DESC
            """
        )

        return [dict(row) for row in cursor.fetchall()]


def get_ticket_details(ticket_id):
    with db_cursor(commit=False) as cursor:

        cursor.execute(
            """
            SELECT *
            FROM tickets
            WHERE ticket_id = %s
            """,
            (ticket_id,),
        )

        ticket = cursor.fetchone()

        if not ticket:
            return None

        cursor.execute(
            """
            SELECT *
            FROM ticket_issues
            WHERE ticket_id = %s
            ORDER BY issue_number
            """,
            (ticket_id,),
        )

        ticket["issues"] = [
            dict(row) for row in cursor.fetchall()
        ]

        cursor.execute(
            """
            SELECT *
            FROM refunds
            WHERE ticket_id = %s
            """,
            (ticket_id,),
        )

        ticket["refunds"] = [
            dict(row) for row in cursor.fetchall()
        ]

        cursor.execute(
            """
            SELECT *
            FROM outbox
            WHERE ticket_id = %s
            """,
            (ticket_id,),
        )

        ticket["outbox"] = cursor.fetchone()

        return dict(ticket)


def get_existing_ticket_id():
    with db_cursor(commit=False) as cursor:
        cursor.execute(
            """
            SELECT ticket_id
            FROM tickets
            ORDER BY ticket_id DESC
            LIMIT 1
            """
        )

        row = cursor.fetchone()

        return row["ticket_id"] if row else None


def get_invoice(invoice_id):
    with db_cursor(commit=False) as cursor:
        cursor.execute(
            """
            SELECT *
            FROM invoices
            WHERE invoice_id = %s
            """,
            (invoice_id,),
        )

        return cursor.fetchone()


def get_customer_invoices(customer_id):
    """
    Retrieve all invoices belonging to a customer,
    including any existing refund information.
    """

    with db_cursor(commit=False) as cursor:
        cursor.execute(
            """
            SELECT
                i.invoice_id,
                i.customer_id,
                i.month,
                i.amount_inr,
                i.status,
                i.note,
                r.refund_id,
                r.status AS refund_status,
                r.approval_status
            FROM invoices i
            LEFT JOIN refunds r
                ON i.invoice_id = r.invoice_id
            WHERE i.customer_id = %s
            ORDER BY i.month, i.amount_inr, i.invoice_id
            """,
            (customer_id,),
        )

        return [
            dict(row)
            for row in cursor.fetchall()
        ]


def next_refund_id():
    with db_cursor() as cursor:

        cursor.execute(
            "SELECT pg_advisory_xact_lock(731905)"
        )

        cursor.execute(
            """
            SELECT COALESCE(
                MAX(
                    NULLIF(
                        SUBSTRING(
                            refund_id FROM '^RF-([0-9]+)$'
                        ),
                        ''
                    )::BIGINT
                ),
                0
            ) AS number
            FROM refunds
            """
        )

        number = int(cursor.fetchone()["number"]) + 1

        return f"RF-{number:04d}"