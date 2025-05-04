import psycopg2

DATABASE_URL = "postgresql://postgres:[YOUR-PASSWORD]@db.beuvyrvloopqgffoscrd.supabase.co:5432/postgres"

try:
    # Attempt to connect to the database
    conn = psycopg2.connect(DATABASE_URL)
    print("Connection successful!")
except Exception as e:
    print("Error connecting to the database:", e)
finally:
    if 'conn' in locals() and conn:
        conn.close()
