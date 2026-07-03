from pathlib import Path
import sqlite3

database_location = Path(__file__).resolve().parent.parent / "Database" / "database.db"
schema_location = Path(__file__).resolve().parent.parent / "Database" / "schema.sql"

def initialise_database(database_location, schema_location):
    try:
        with sqlite3.connect(database_location) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")
        
        with schema_location.open("r") as file:
            content = file.read()
            cursor.executescript(content)
            print(f"Created at: {schema_location}")
    except sqlite3.Error as e:
        print(f"An error occurred during initialisation: {e}")
    return conn


if __name__ == "__main__":
    db_connection = initialise_database(database_location, schema_location)
    