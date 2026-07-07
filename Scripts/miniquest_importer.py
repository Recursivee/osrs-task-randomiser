import json
import sqlite3
from pathlib import Path

# Paths
database_location = Path(__file__).resolve().parent.parent / "Database" / "database.db"
schema_location = Path(__file__).resolve().parent.parent / "Database" / "schema.sql"
json_location = Path(__file__).resolve().parent.parent / "Data" / "miniquests.json"


def populate_miniquests():
    # 1. Ensure the JSON configuration file exists
    if not json_location.exists():
        print(f"Error: Could not find miniquests file at {json_location}")
        return

    # 2. Connect to database
    print("Connecting to SQLite database...")
    conn = sqlite3.connect(database_location)
    cursor = conn.cursor()

    # 3. Clean out old miniquest and requirement data to keep executions clean
    print("Purging stale miniquest configurations...")
    # This prevents deleting scraped MAIN quests while wiping old custom data
    cursor.execute("DELETE FROM quests WHERE quest_type = 'MINI'")
    

    with open(json_location, "r") as f:
        miniquests_config = json.load(f)
        
    for mq_name in miniquests_config.keys():
        # Clean any entries where this miniquest is either the requirement or the target
        cursor.execute("DELETE FROM diary_requirements WHERE req_name = ?", (mq_name,))
        cursor.execute("DELETE FROM diary_requirements WHERE req_type = 'QUEST' AND req_name IN (SELECT quest_name FROM quests WHERE quest_type = 'MINI')")

    print("Beginning miniquest structural import...")
    mq_count = 0
    req_count = 0

    # --- ROUND 1: Insert ALL miniquests into the quests table first ---
    # Primary key column is 'quest_id' and name unique index is 'quest_name'
    for mq_name, data in miniquests_config.items():
        region = data.get("region", "Unknown")

        cursor.execute("""
            INSERT INTO quests (quest_name, region, quest_type, status)
            VALUES (?, ?, 'MINI', 0)
        """, (mq_name, region))
        mq_count += 1

    # --- ROUND 2: Process all requirements and dependencies ---
    for mq_name, data in miniquests_config.items():
        # Fetch the numeric quest_id of the current miniquest
        cursor.execute("SELECT quest_id FROM quests WHERE quest_name = ?", (mq_name,))
        current_mq_id = cursor.fetchone()[0]

        # --- A. Process Skill Requirements ---
        # Maps to: skill_requirements (target_type, target_id, skill_name, level_required)
        for skill_name, level_needed in data.get("skills", {}).items():
            cursor.execute("""
                INSERT INTO skill_requirements (target_type, target_id, skill_name, level_required)
                VALUES ('QUEST', ?, ?, ?)
            """, (current_mq_id, skill_name, int(level_needed)))
            req_count += 1

        # --- B. Process Quest/Miniquest Prerequisites ---
        # Maps to: quest_requirements (quest_id, required_quest_id)
        prereqs = data.get("quests", []) + data.get("miniquests", [])
        for prereq_name in prereqs:
            # Find the ID of the required prerequisite quest
            cursor.execute("SELECT quest_id FROM quests WHERE quest_name = ?", (prereq_name,))
            prereq_row = cursor.fetchone()
            
            if prereq_row:
                prereq_id = prereq_row[0]
                # Using INSERT OR IGNORE to safely handle duplicate entries if they appear
                cursor.execute("""
                    INSERT OR IGNORE INTO quest_requirements (quest_id, required_quest_id)
                    VALUES (?, ?)
                """, (current_mq_id, prereq_id))
                req_count += 1
            else:
                print(f"Warning: Prerequisite quest '{prereq_name}' not found for '{mq_name}'")

        # --- C. Process Reverse Dependencies ("unlocks_quests") ---
        # Maps to: quest_requirements (quest_id, required_quest_id)
        # Where the blocked quest needs the miniquest
        for blocked_quest_name in data.get("unlocks_quests", []):
            cursor.execute("SELECT quest_id FROM quests WHERE quest_name = ?", (blocked_quest_name,))
            blocked_quest_row = cursor.fetchone()
            
            if blocked_quest_row:
                blocked_quest_id = blocked_quest_row[0]
                cursor.execute("""
                    INSERT OR IGNORE INTO quest_requirements (quest_id, required_quest_id)
                    VALUES (?, ?)
                """, (blocked_quest_id, current_mq_id))
                req_count += 1
            else:
                print(f"Warning: Blocked quest '{blocked_quest_name}' not found in DB. Skipping reverse dependency.")

    conn.commit()
    conn.close()

    print("-" * 50)
    print(f"Success! Imported {mq_count} custom Miniquests into global 'quests' table.")
    print(f"Applied {req_count} dynamic dependency structures to 'quest_requirements'.")
    print("-" * 50)

if __name__ == "__main__":
    populate_miniquests()