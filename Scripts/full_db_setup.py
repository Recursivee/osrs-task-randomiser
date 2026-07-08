import os
import json
import sqlite3
from pathlib import Path

# Import existing functional blocks
from init_db import initialise_database
from quest_importer import run_scraper
from miniquest_importer import populate_miniquests
from achievement_importer import populate_diary_database

# Setup absolute path roots
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "Database" / "database.db"
SCHEMA_PATH = BASE_DIR / "Database" / "schema.sql"

def seed_starting_stats(cursor):
    json_path = BASE_DIR / "Data" / "starting_stats.json"
        
    if not json_path.exists():
        print("   [!] Error: starting_stats.json could not be located.")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        master_data = json.load(f)

    # 1. Seed Character Meta Data (Quest Points) into your metadata table
    char_data = master_data.get("Character", {})
    starting_qp = char_data.get("quest_points", 0)
    
    # Using INSERT OR REPLACE to initialize or update row ID 1
    cursor.execute("""
        INSERT OR REPLACE INTO metadata (id, total_quest_points, gold_available)
        VALUES (1, ?, COALESCE((SELECT gold_available FROM metadata WHERE id = 1), 0))
    """, (starting_qp,))
    print(f"   [+] Seeded global metadata profile with {starting_qp} starter Quest Points.")

    # 2. Iterate through the Skills Array list
    skills_list = master_data.get("Skills", [])
    print("   [+] Seeding fresh player profile stats array...")
    
    for skill_node in skills_list:
        skill_name = skill_node["name"]
        level = skill_node["level"]
        xp = skill_node["experience"]
        unlocked = skill_node["unlocked"]

        cursor.execute("""
            INSERT OR REPLACE INTO player_stats (skill_name, current_level, current_xp, is_unlocked)
            VALUES (?, ?, ?, ?)
        """, (skill_name, level, xp, unlocked))
        
    print(f"   [+] Successfully assigned {len(skills_list)} starter skills into 'player_stats'.")

def seed_unlockable_shop(cursor):
    # Adjust path if needed
    json_path = BASE_DIR / "Data" / "unlockable_content.json"
        
    if not json_path.exists():
        print("   [!] Error: unlockable_content.json could not be located.")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        shop_data = json.load(f)

    print("   [+] Populating progression storefront costs and sub-skill restrictions...")
    shop_item_count = 0
    skill_req_count = 0

    # Group configuration categories directly mapped to schema content_types
    category_map = {
        "Regions": "REGION",
        "Bosses": "BOSS",
        "Raids": "RAID",
        "Minigames": "MINIGAME"
    }

    # Default storefront unlocks pricing matrix matching schema constraints
    cost_matrix = {
        "REGION": 0,
        "BOSS": 1,
        "RAID": 3,
        "MINIGAME": 1
    }

    for json_key, content_type in category_map.items():
        items_list = shop_data.get(json_key, [])
        
        for item in items_list:
            name = item["name"]
            is_initially_unlocked = 1 if item.get("unlocked", False) else 0
            key_cost = cost_matrix[content_type]
            
            # Unpack parent quest requirement lists safely 
            # (e.g. ["Children of the Sun"] or "Priest in Peril")
            quest_reqs = item.get("quest_requirements", [])
            parent_id = None
            
            if isinstance(quest_reqs, list) and len(quest_reqs) > 0:
                parent_quest_name = quest_reqs[0]
            elif isinstance(quest_reqs, str):
                parent_quest_name = quest_reqs
            else:
                parent_quest_name = None

            # Look up quest ID dynamically 
            if parent_quest_name:
                cursor.execute("SELECT quest_id FROM quests WHERE quest_name = ?", (parent_quest_name,))
                row = cursor.fetchone()
                if row:
                    parent_id = row[0]
                else:
                    print(f"   [!] Warning: Quest '{parent_quest_name}' needed for '{name}' not found in DB.")

            # 1. Insert item into the unlockable storefront pool
            cursor.execute("""
                INSERT OR IGNORE INTO unlockable_shop (name, content_type, key_cost, parent_quest_id, is_unlocked)
                VALUES (?, ?, ?, ?, ?)
            """, (name, content_type, key_cost, parent_id, is_initially_unlocked))
            shop_item_count += 1

            # Get the accurate item ID inserted
            cursor.execute("SELECT id FROM unlockable_shop WHERE name = ?", (name,))
            shop_item_db_id = cursor.fetchone()[0]

            # 2. Insert corresponding profile skill rules into skill_requirements
            # Maps entry parameters matching target_type 'SHOP_ITEM'
            skill_requirements = item.get("skill_requirements", {})
            for skill, level_needed in skill_requirements.items():
                # Capitalise input keys to guarantee clean matching strings (e.g. 'slayer' -> 'Slayer')
                clean_skill_name = skill.strip().capitalize()
                
                cursor.execute("""
                    INSERT INTO skill_requirements (target_type, target_id, skill_name, level_required)
                    VALUES ('SHOP_ITEM', ?, ?, ?)
                """, (shop_item_db_id, clean_skill_name, int(level_needed)))
                skill_req_count += 1
                
    print(f"   [+] Successfully seeded {shop_item_count} unlock milestones into 'unlockable_shop'.")
    print(f"   [+] Applied {skill_req_count} shop tier skill dependencies into 'skill_requirements'.")

def seed_tasks_master(cursor):
    json_path = BASE_DIR / "Data" / "tasks_pool.json"
        
    if not json_path.exists():
        print("   [!] Error: tasks_pool.json could not be located.")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        pool_data = json.load(f)

    # Isolate "Tasks" array block
    tasks_list = pool_data.get("Tasks", [])
    
    print("   [+] Seeding Master Task Template Pool Blueprints...")
    inserted_count = 0

    for task in tasks_list:
        if not isinstance(task, dict):
            continue

        # Extract the description template string
        description = task.get("description_template")
        if not description:
            continue

        # Explicitly check for None/null and overwrite it with a safe default string.
        task_type = task.get("task_type")
        if task_type is None:
            task_type = "ACTIVE"  # Safe default fallback matching your schema constraint
        else:
            task_type = str(task_type).strip().upper()

        # Handle difficulty scaling strings safely
        difficulty = task.get("difficulty_tier") or "EASY"
        difficulty = str(difficulty).strip().upper()

        # Since these are global generation templates, they don't have static shop IDs yet
        associated_shop_id = None

        # Execute insertion matching schema rules
        cursor.execute("""
            INSERT INTO tasks_master (task_description, task_type, difficulty_tier, associated_shop_id)
            VALUES (?, ?, ?, ?)
        """, (description, task_type, difficulty, associated_shop_id))
        inserted_count += 1

    print(f"   [+] Successfully seeded {inserted_count} master templates into 'tasks_master'.")

def main():
    print("=" * 60)
    print("OSRS SNOWFLAKE CORE DATABASE CONFIGURATION GENERATOR")
    print("=" * 60)
    
    # Step 1: Schema creation
    print("\n[1/7] Initializing raw database schema structures...")
    conn = initialise_database(DB_PATH, SCHEMA_PATH)
    cursor = conn.cursor()
    
    # Step 2: Main Scraper Injection
    print("\n[2/7] Executing live web scraper for Main Quest parsing...")
    run_scraper(conn, cursor) 
    
    # Step 3: Custom Miniquests Injection
    print("\n[3/7] Parsing and linking hardcoded Miniquest relational dependencies...")
    populate_miniquests() 
    
    # Step 4: Achievement Diaries Processing
    print("\n[4/7] Parsing Achievement Diary blueprint levels...")
    populate_diary_database()
    
    # Reconnect/commit changes before doing file data seeds
    conn.commit()
    
    # Step 5: Seeding Player Stats Data
    print("\n[5/7] Seeding starting player profiles and level distributions...")
    seed_starting_stats(cursor)
    
    # Step 6: Seeding the Unlock Shop Configuration
    print("\n[6/7] Populating progression storefront costs and quest restrictions...")
    seed_unlockable_shop(cursor)
    
    # Step 7: Seeding structural Tasks Core
    print("\n[7/7] Instantiating template parameters for master task matrix tracking...")
    seed_tasks_master(cursor)
    
    # Final Transaction Safe Save
    conn.commit()
    conn.close()
    print("\n" + "=" * 60)
    print("SUCCESS! Total system database environment setup completed.")
    print("=" * 60)

if __name__ == "__main__":
    main()