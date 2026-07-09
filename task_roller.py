import random
import sqlite3
import json
from pathlib import Path

# Paths to data assets
CONFIG_DIR = Path(__file__).resolve().parent / "Config"
DATA_DIR = Path(__file__).resolve().parent / "Data"
POOL_PATH = CONFIG_DIR / "tasks_pool.json" if (CONFIG_DIR / "tasks_pool.json").exists() else DATA_DIR / "tasks_pool.json"

def get_current_player_stats(cursor):
    """Returns a dictionary of {SkillName: CurrentLevel} ONLY for unlocked skills."""
    cursor.execute("SELECT skill_name, current_level FROM player_stats WHERE is_unlocked = 1")
    return {row[0]: row[1] for row in cursor.fetchall()}

def is_quest_eligible(quest_id, cursor, player_stats):
    """
    Returns True if the player meets skill levels, prerequisite quests,
    AND has unlocked the region where the quest begins.
    """
    cursor.execute("SELECT status, region FROM quests WHERE quest_id = ?", (quest_id,))
    quest_row = cursor.fetchone()
    if not quest_row or quest_row[0] == 2:
        return False
    
    quest_status, quest_region = quest_row[0], quest_row[1]

    if quest_region and quest_region.upper() != "MISTHALIN":
        cursor.execute("""
            SELECT is_unlocked FROM unlockable_shop 
            WHERE name = ? AND content_type = 'REGION'
        """, (quest_region,))
        region_row = cursor.fetchone()
        if not region_row or region_row[0] == 0:
            return False

    cursor.execute("""
        SELECT skill_name, level_required FROM skill_requirements 
        WHERE target_type = 'QUEST' AND target_id = ?
    """, (quest_id,))
    for skill_name, level_req in cursor.fetchall():
        if player_stats.get(skill_name, 1) < level_req:
            return False

    cursor.execute("""
        SELECT required_quest_id FROM quest_requirements WHERE quest_id = ?
    """, (quest_id,))
    for (req_id,) in cursor.fetchall():
        cursor.execute("SELECT status FROM quests WHERE quest_id = ?", (req_id,))
        req_status = cursor.fetchone()
        if not req_status or req_status[0] != 2:
            return False

    return True

def is_diary_eligible(diary_name, tier, cursor, player_stats):
    """
    Returns True if the player has unlocked the parent region, meets all 
    skill thresholds, and has completed all prerequisite quests for this diary tier.
    """
    region_name = diary_name.replace(" Diary", "").strip()
    
    if region_name.upper() not in ["MISTHALIN", "LUMBRIDGE & DRAYNOR", "LUMBRIDGE", "VARROCK"]:
        cursor.execute("""
            SELECT is_unlocked FROM unlockable_shop 
            WHERE name = ? AND content_type = 'REGION'
        """, (region_name,))
        region_row = cursor.fetchone()
        if not region_row or region_row[0] == 0:
            return False

    cursor.execute("""
        SELECT dr.req_type, dr.req_name, dr.req_value 
        FROM diary_requirements dr
        JOIN achievement_diaries ad ON dr.diary_id = ad.diary_id
        WHERE ad.diary_name = ? AND ad.tier = ?
    """, (diary_name, tier.strip().capitalize()))
    
    requirements = cursor.fetchall()
    
    for req_type, req_name, req_value in requirements:
        req_type = req_type.upper()
        
        if req_type == "SKILL":
            clean_skill = req_name.strip().capitalize()
            if player_stats.get(clean_skill, 1) < int(req_value):
                return False
                
        elif req_type == "QUEST":
            cursor.execute("SELECT status FROM quests WHERE quest_name = ?", (req_name.strip(),))
            quest_row = cursor.fetchone()
            if not quest_row or quest_row[0] != 2:
                return False

    return True

def gather_eligible_content(cursor, player_stats):
    """Scans save state and builds a collection of valid available content targets."""
    pools = {
        "Skill": [],
        "Quest": [],
        "Boss": [],
        "Minigame": [],
        "Raid": [],
        "Slayer": [],        
        "Achievement": [],
        "Clue": ["Clue Scroll Run"] 
    }

    meta_path = CONFIG_DIR / "meta_data.json" if (CONFIG_DIR / "meta_data.json").exists() else DATA_DIR / "meta_data.json"
    excluded_skills = []
    
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta_config = json.load(f)
            excluded_skills = meta_config.get("skill_check", {}).get("Excluded", [])
            excluded_skills = [s.strip().capitalize() for s in excluded_skills]
        except Exception as e:
            print(f"   [!] Warning: Failed to parse skill exclusions from meta_data.json: {e}")

    for skill_name in player_stats.keys():
        if skill_name in excluded_skills:
            continue  
        pools["Skill"].append(skill_name)

    cursor.execute("SELECT quest_id, quest_name FROM quests WHERE status != 2")
    for q_id, q_name in cursor.fetchall():
        if is_quest_eligible(q_id, cursor, player_stats):
            pools["Quest"].append(q_name)

    if "Slayer" in player_stats:
        pools["Slayer"] = ["Slayer Assignment"]

    cursor.execute("SELECT name, content_type, id FROM unlockable_shop WHERE is_unlocked = 1")
    for name, content_type, shop_id in cursor.fetchall():
        cursor.execute("""
            SELECT skill_name, level_required FROM skill_requirements 
            WHERE target_type = 'SHOP_ITEM' AND target_id = ?
        """, (shop_id,))
        skills_pass = True
        for s_name, s_level in cursor.fetchall():
            if player_stats.get(s_name, 1) < s_level:
                skills_pass = False
                break
        
        if not skills_pass:
            continue

        if content_type == "BOSS":
            pools["Boss"].append(name)
        elif content_type == "MINIGAME":
            pools["Minigame"].append(name)
        elif content_type == "RAID":
            pools["Raid"].append(name)

    cursor.execute("SELECT diary_name, tier FROM achievement_diaries WHERE is_completed = 0")
    for d_name, tier in cursor.fetchall():
        if is_diary_eligible(d_name, tier, cursor, player_stats):
            pools["Achievement"].append(f"{d_name} ({tier})")

    return pools

def generate_three_choices(conn, cursor):
    print("\n[Engine] Gathering data configurations...")
    player_stats = get_current_player_stats(cursor)
    content_pools = gather_eligible_content(cursor, player_stats)

    with open(POOL_PATH, "r") as f:
        pool_config = json.load(f)

    weight_settings = pool_config.get("Task_Weighting", {})
    templates_list = pool_config.get("Tasks", [])

    categories = list(weight_settings.keys())
    weights = list(weight_settings.values())

    choices_generated = []
    attempts = 0

    slot_type = input("Are you rolling for an 'ACTIVE' or 'AFK' slot? ").strip().upper()
    if slot_type not in ["ACTIVE", "AFK"]:
        slot_type = "ACTIVE"

    while len(choices_generated) < 3 and attempts < 100:
        attempts += 1
        
        # Step A: Roll a category weighted by preferences
        rolled_category = random.choices(categories, weights=weights, k=1)[0]
        
        # Step B: Ensure the content pool for this category isn't empty
        if not content_pools[rolled_category]:
            continue

        # Step C: Filter and pick a random template matching category and slot type
        matching_templates = []
        for t in templates_list:
            if t.get("category") != rolled_category:
                continue
                
            t_type = t.get("task_type")
            if t_type is None:
                t_type_str = "BOTH" 
            else:
                t_type_str = str(t_type).strip().upper()
            
            if slot_type == "AFK" and t_type_str == "ACTIVE":
                continue
            if slot_type == "ACTIVE" and t_type_str == "AFK":
                continue
                
            matching_templates.append(t)

        if not matching_templates:
            continue
            
        template = random.choice(matching_templates)
        template_id = template.get("template_id", 1)

        # Step D: Populate template parameters based on category
        description = template["description_template"]
        min_amt = template.get("min_amount", 1)
        max_amt = template.get("max_amount", 1)
        rolled_amount = random.randint(min_amt, max_amt)

        meta_target = None
        meta_value = rolled_amount

        if rolled_category == "Skill":
            rolled_skill = random.choice(content_pools["Skill"])
            current_level = player_stats[rolled_skill]
            meta_target = rolled_skill

            if template.get("template_id") == 12 and current_level < 50:
                continue

            if "level" in description.lower():
                rolled_amount = current_level + rolled_amount
                if rolled_amount > 99: rolled_amount = 99
                if rolled_amount <= current_level: continue
                meta_value = rolled_amount
            
            task_text = description.format(amount=rolled_amount, skill=rolled_skill)
        
        elif rolled_category in ["Quest", "Boss", "Minigame", "Raid", "Achievement"]:
            specific_content = random.choice(content_pools[rolled_category])
            meta_target = specific_content
            task_text = description.format(content_name=specific_content, amount=rolled_amount)
        
        else:
            task_text = description.format(amount=rolled_amount)

        if not any(c["text"] == task_text for c in choices_generated):
            choices_generated.append({
                "template_id": template_id,
                "text": task_text,
                "category": rolled_category,
                "target": meta_target,
                "value": meta_value
            })

    if len(choices_generated) < 3:
        print("[!] Warning: Content pool too restrictive to roll choices.")
        return

    print(f"\n=== GENERATED 3 OPTIONS FOR YOUR {slot_type} TASK SLOT ===")
    for idx, choice in enumerate(choices_generated, 1):
        print(f"  {idx}. {choice['text']}")
    print("=========================================================")

    try:
        user_pick = int(input("Select which task to activate (1-3): ").strip())
        if user_pick in [1, 2, 3]:
            picked = choices_generated[user_pick - 1]
            
            cursor.execute("DELETE FROM active_slots WHERE slot_type = ?", (slot_type,))
            cursor.execute("""
                INSERT INTO active_slots (
                    slot_type, choice_1_id, choice_2_id, choice_3_id, 
                    choice_1_description, choice_2_description, choice_3_description,
                    current_task_id, current_task_description
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                slot_type, 
                choices_generated[0]["template_id"], choices_generated[1]["template_id"], choices_generated[2]["template_id"],
                choices_generated[0]["text"], choices_generated[1]["text"], choices_generated[2]["text"],
                picked["template_id"], picked["text"]
            ))
            conn.commit()
            print(f"\n[+] Task Accepted! Stored inside database active slots tracking system.")
    except ValueError:
        print("[!] Input canceled.")