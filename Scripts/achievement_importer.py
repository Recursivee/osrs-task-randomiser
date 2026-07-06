import json
from pathlib import Path
from init_db import initialise_database

# Paths
database_location = Path(__file__).resolve().parent.parent / "Database" / "database.db"
schema_location = Path(__file__).resolve().parent.parent / "Database" / "schema.sql"
json_location = Path(__file__).resolve().parent.parent / "Data" / "diary_requirements.json"


conn = initialise_database(database_location, schema_location)
cursor = conn.cursor()

def populate_diary_database():
    # 1. Ensure the JSON configuration file exists
    if not json_location.exists():
        print(f"Error: Could not find configuration file at {json_location}")
        print("Please save your completed JSON template as 'diary_requirements.json' in the data folder.")
        return

    # 2. Connect to database and run schema safety initialization
    print("Connecting to SQLite database...")
    conn = initialise_database(database_location, schema_location)
    cursor = conn.cursor()

    # 3. Clean out old entries to avoid duplicating records on repeated runs
    print("Cleaning stale achievement records...")
    cursor.execute("DELETE FROM achievement_diaries")
    cursor.execute("DELETE FROM diary_requirements")

    # 4. Load the hardcoded data structures from JSON
    with open(json_location, "r") as f:
        diary_config = json.load(f)

    # 5. Core region mapping dictionary to automatically assign game areas
    region_mapping = {
        "Ardougne": "Kandarin", 
        "Desert": "Kharidian Desert", 
        "Falador": "Asgarnia",
        "Fremennik": "Fremennik Province", 
        "Kandarin": "Kandarin", 
        "Karamja": "Karamja",
        "Kourend & Kebos": "Great Kourend", 
        "Lumbridge & Draynor": "Misthalin",
        "Morytania": "Morytania", 
        "Varrock": "Misthalin", 
        "Western Provinces": "Kandarin",
        "Wilderness": "Wilderness"
    }


    diary_count = 0
    requirement_count = 0

    # 6. Parse JSON file and execute parameter queries
    for diary_name, tiers in diary_config.items():
        assigned_region = region_mapping.get(diary_name, diary_name)

        for tier_name, data in tiers.items():
            # Insert top-level achievement diary record
            cursor.execute("""
                INSERT INTO achievement_diaries (diary_name, tier, region, is_completed)
                VALUES (?, ?, ?, 0)
            """, (diary_name, tier_name, assigned_region))
            
            diary_id = cursor.lastrowid
            diary_count += 1

            # --- A. Insert Skill Requirements ---
            for skill_name, level_needed in data.get("skills", {}).items():
                cursor.execute("""
                    INSERT INTO diary_requirements (diary_id, req_type, req_name, req_value)
                    VALUES (?, 'SKILL', ?, ?)
                """, (diary_id, skill_name, int(level_needed)))
                requirement_count += 1
                
            # --- B. Insert Quest Requirements ---
            for quest_name in data.get("quests", []):
                cursor.execute("""
                    INSERT INTO diary_requirements (diary_id, req_type, req_name, req_value)
                    VALUES (?, 'QUEST', ?, 1)
                """, (diary_id, quest_name))
                requirement_count += 1

            # --- C. Insert Boss Requirements ---
            for boss_name in data.get("bosses", []):
                cursor.execute("""
                    INSERT INTO diary_requirements (diary_id, req_type, req_name, req_value)
                    VALUES (?, 'BOSS', ?, 1)
                """, (diary_id, boss_name))
                requirement_count += 1

            # --- D. Insert Minigame Requirements ---
            for minigame_name in data.get("minigames", []):
                cursor.execute("""
                    INSERT INTO diary_requirements (diary_id, req_type, req_name, req_value)
                    VALUES (?, 'MINIGAME', ?, 1)
                """, (diary_id, minigame_name))
                requirement_count += 1

            # --- E. Insert Special/Other Requirements ---
            for other_req in data.get("other", []):
                cursor.execute("""
                    INSERT INTO diary_requirements (diary_id, req_type, req_name, req_value)
                    VALUES (?, 'SPECIAL', ?, 1)
                """, (diary_id, other_req))
                requirement_count += 1

   
    conn.commit()
    conn.close()
    
    print("-" * 50)
    print(f"Imported {diary_count} Diary Tiers.")
    print(f"Populated {requirement_count} distinct rule rows in 'diary_requirements'.")
    print("-" * 50)

if __name__ == "__main__":
    populate_diary_database()