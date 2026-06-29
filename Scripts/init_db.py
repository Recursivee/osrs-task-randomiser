from pathlib import Path
import sqlite3


def initialise_database(database_location, schema_location):
    try:
        with sqlite3.connect(database_location) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")
        
        with schema_location.open("r") as file:
            content = file.read()
            cursor.executescript(content)
    except sqlite3.Error as e:
        print(f"An error occurred during initialisation: {e}")
    