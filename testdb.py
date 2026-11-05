import os
import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = (
    f"postgresql://{os.getenv('DB_USER')}:"
    f"{os.getenv('DB_PASSWORD')}@"
    f"{os.getenv('DB_HOST')}:"
    f"{os.getenv('DB_PORT')}/"
    f"{os.getenv('DB_NAME')}?"
    f"sslmode={os.getenv('DB_SSLMODE', 'require')}"
)

try:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), version()")
            result = cur.fetchone()

            print("Database connection successful!")
            print("Database:", result[0])
            print("PostgreSQL version:", result[1])

except Exception as e:
    print("Database connection failed:", e)