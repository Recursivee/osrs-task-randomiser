import json
import sqlite3
from pathlib import Path

# Paths
database_location = Path(__file__).resolve().parent.parent / "Database" / "database.db"
schema_location = Path(__file__).resolve().parent.parent / "Database" / "schema.sql"
json_location = Path(__file__).resolve().parent.parent / "Data" / "miniquests.json"


def populate_miniquests():
    if not json_location.exists():
        print(f"Error: Could not find miniquests file at {json_location}")
        return

    print("Connecting to SQLite database...")
    conn = sqlite3.connect(database_location)
    cursor = conn.cursor()

    print("Purging stale miniquest configurations...")
    # Wipe old custom data, but safeguard main scraped quests
    cursor.execute("DELETE FROM quests WHERE quest_type = 'MINI'")
    
    with open(json_location, "r") as f:
        miniquests_config = json.load(f)
        
    for mq_name in miniquests_config.keys():
        cursor.execute("DELETE FROM diary_requirements WHERE req_name = ?", (mq_name,))
        
    # Clean out existing rewards linked to miniquests before re-inserting to prevent bloating
    cursor.execute("""
        DELETE FROM quest_xp_rewards 
        WHERE quest_id IN (SELECT quest_id FROM quests WHERE quest_type = 'MINI')
    """)

    print("Beginning miniquest structural import...")
    mq_count = 0
    req_count = 0
    xp_count = 0

    # --- ROUND 1: Insert all miniquests into the quests table first ---
    for mq_name, data in miniquests_config.items():
        region = data.get("region", "Unknown")

        cursor.execute("""
            INSERT INTO quests (quest_name, region, quest_type, status)
            VALUES (?, ?, 'MINI', 0)
        """, (mq_name, region))
        mq_count += 1

    # --- ROUND 2: Process all requirements, dependencies, and REWARDS ---
    for mq_name, data in miniquests_config.items():
        cursor.execute("SELECT quest_id FROM quests WHERE quest_name = ?", (mq_name,))
        current_mq_id = cursor.fetchone()[0]

        # --- A. Process Skill Requirements ---
        for skill_name, level_needed in data.get("skills", {}).items():
            cursor.execute("""
                INSERT INTO skill_requirements (target_type, target_id, skill_name, level_required)
                VALUES ('QUEST', ?, ?, ?)
            """, (current_mq_id, skill_name.strip().capitalize(), int(level_needed)))
            req_count += 1

        # --- B. Process Quest/Miniquest Prerequisites ---
        prereqs = data.get("quests", []) + data.get("miniquests", [])
        for prereq_name in prereqs:
            cursor.execute("SELECT quest_id FROM quests WHERE quest_name = ?", (prereq_name,))
            prereq_row = cursor.fetchone()
            
            if prereq_row:
                prereq_id = prereq_row[0]
                cursor.execute("""
                    INSERT OR IGNORE INTO quest_requirements (quest_id, required_quest_id)
                    VALUES (?, ?)
                """, (current_mq_id, prereq_id))
                req_count += 1
            else:
                print(f"Warning: Prerequisite quest '{prereq_name}' not found for '{mq_name}'")

        # --- C. Process Reverse Dependencies ("unlocks_quests") ---
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

        # --- D. Process XP Rewards ---
        xp_rewards = data.get("xp_rewards")
        if isinstance(xp_rewards, dict):
            for skill, amount in xp_rewards.items():
                clean_skill_name = skill.strip().capitalize()
                
                cursor.execute("""
                    INSERT INTO quest_xp_rewards (quest_id, skill_name, xp_reward)
                    VALUES (?, ?, ?)
                """, (current_mq_id, clean_skill_name, int(amount)))
                xp_count += 1

    conn.commit()
    conn.close()

    print("-" * 50)
    print(f"Success! Imported {mq_count} custom Miniquests into global 'quests' table.")
    print(f"Applied {req_count} dynamic dependency structures to 'quest_requirements'.")
    print(f"Seeded {xp_count} experience payloads into 'quest_xp_rewards'.")
    print("-" * 50)

if __name__ == "__main__":
    populate_miniquests()