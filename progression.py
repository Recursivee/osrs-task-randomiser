import json
import math
import sqlite3
from pathlib import Path

# Paths to configurations
CONFIG_DIR = Path(__file__).resolve().parent / "Config"
DATA_DIR = Path(__file__).resolve().parent / "Data"
HISTORY_LOG_PATH = Path(__file__).resolve().parent / "history.log"
POOL_PATH = CONFIG_DIR / "tasks_pool.json"
META_PATH = CONFIG_DIR / "meta_data.json" 

# --- 1. AUTHENTIC OSRS XP TABLE GENERATION ---
def _generate_xp_table():
    """Generates an exact OSRS cumulative experience table for levels 1-100."""
    xp_table = [0] * 101
    points = 0.0
    for lvl in range(1, 100):
        points += math.floor(lvl + 300.0 * math.pow(2.0, lvl / 7.0))
        xp_table[lvl + 1] = math.floor(points / 4.0)
    return xp_table

XP_TABLE = _generate_xp_table()

def get_level_for_xp(xp):
    """Returns the precise OSRS level matching a specific XP total."""
    if xp >= 13034431:  # Level 99 baseline cap
        return 99
    for lvl in range(1, 100):
        if xp < XP_TABLE[lvl + 1]:
            return lvl
    return 99

# --- 2. LOGGING WRITER TOOL ---
def log_action(action_string):
    """Appends an execution event line to history.log for Feature 5 recovery."""
    with open(HISTORY_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(action_string + "\n")

# --- 3. CORE STAT MANAGEMENT ENGINE ---
def add_xp(cursor, skill_name, amount):
    """Adds XP to a skill, calculates level ups, and updates player stats."""
    skill_clean = skill_name.strip().capitalize()
    
    cursor.execute("""
        SELECT current_level, current_xp, is_unlocked 
        FROM player_stats WHERE skill_name = ?
    """, (skill_clean,))
    row = cursor.fetchone()
    
    if not row:
        print(f"   [!] Error: Skill '{skill_clean}' not recognized in database.")
        return
        
    old_level, old_xp, is_unlocked = row[0], row[1], row[2]
    
    if is_unlocked == 0:
        print(f"   [*] Note: Storing {amount} XP in locked skill '{skill_clean}'.")

    new_xp = old_xp + int(amount)
    new_level = get_level_for_xp(new_xp)
    
    cursor.execute("""
        UPDATE player_stats 
        SET current_xp = ?, current_level = ? 
        WHERE skill_name = ?
    """, (new_xp, new_level, skill_clean))
    
    if new_level > old_level:
        print(f"   [LEVEL UP] Your {skill_clean} level advanced from {old_level} to {new_level}!")

def award_gold(cursor, amount):
    """Increments the global profile wallet balance."""
    cursor.execute("UPDATE metadata SET gold_available = gold_available + ? WHERE id = 1", (float(amount),))
    print(f"   [+ COINS] Received {amount} Gold.")

# --- 4. DYNAMIC QUEST COMPLETION GATEKEEPER ---
def complete_quest_by_name(conn, cursor, quest_name):
    """Marks a quest complete, issues rewards, updates quest points, and rolls dynamic configurations."""
    # 1. Fetch quest details including the quest point reward allocation
    cursor.execute("""
        SELECT quest_id, quest_type, status, quest_point_reward 
        FROM quests WHERE quest_name = ?
    """, (quest_name,))
    row = cursor.fetchone()
    
    if not row:
        print(f"[!] Error: Quest '{quest_name}' not found in database.")
        return
        
    quest_id, quest_type, status, qp_reward = row[0], row[1], row[2], row[3]
    
    if status == 2:
        print(f"[!] '{quest_name}' is already completed!")
        return

    print(f"\n[+] Processing completion for Quest: {quest_name}")
    
    # 2. Update Quest State to Completed (2)
    cursor.execute("UPDATE quests SET status = 2 WHERE quest_id = ?", (quest_id,))
    
    # 3. Grant Quest Points directly to your metadata profile row
    qp_reward = int(qp_reward) if qp_reward else 0
    if qp_reward > 0:
        cursor.execute("UPDATE metadata SET total_quest_points = total_quest_points + ? WHERE id = 1", (qp_reward,))
        print(f"   [+ QP] Earned {qp_reward} Quest Points!")

    # 4. Grant Dynamic XP Rewards from quest_xp_rewards
    cursor.execute("SELECT skill_name, xp_reward FROM quest_xp_rewards WHERE quest_id = ?", (quest_id,))
    rewards = cursor.fetchall()
    for skill, xp_amt in rewards:
        add_xp(cursor, skill, xp_amt)

    # 5. Dynamic Lock Triggers (Replaces your old hardcoded if/elifs)
    check_and_unlock_skills(cursor)

    log_action(f"QUEST_COMPLETE|{quest_name}")

# --- 5. AUTOMATED METADATA REWARD LOOKUPS ---
def _get_task_difficulty_tier(template_id):
    """Looks up the tier string (Easy, Medium, Hard, etc.) for a template ID from your task pool."""
    if not POOL_PATH.exists():
        return "Easy"
    try:
        with open(POOL_PATH, "r", encoding="utf-8") as f:
            pool_config = json.load(f)
        for task in pool_config.get("Tasks", []):
            if task.get("template_id") == template_id:
                return task.get("difficulty_tier", "Easy")
    except Exception:
        pass
    return "Easy"

def _get_gold_reward_for_tier(tier_name):
    """Loads meta_data.json and retrieves the standard gold reward value for a difficulty tier."""
    if not META_PATH.exists():
        print(f"meta_path file not found: {META_PATH}")
        return 0.0
    try:
        with open(META_PATH, "r", encoding="utf-8") as f:
            meta_config = json.load(f)
        rewards = meta_config.get("Rewards", {})
        # Use float instead of int to preserve 0.5 balances!
        return float(rewards.get(tier_name.strip().capitalize(), 0.0))
    except Exception as e:
        print(f"   [!] Warning: Failed to calculate tier gold rewards from metadata: {e}")
        return 0.0

# --- 6. RUNTIME TASK PROGRESSION INTERFACE ---
def handle_completions(conn, cursor):
    """
    Bypasses menu screening: Directly processes active workslots, evaluates 
    automatic gold multipliers from metadata rules, and updates metrics cleanly.
    """
    cursor.execute("SELECT slot_type, current_task_description, current_task_id FROM active_slots WHERE current_task_id IS NOT NULL")
    active_assignments = cursor.fetchall()
    
    if not active_assignments:
        print("\n[!] No active tasks currently assigned to your workslots.")
        return
        
    print("\n--- CURRENT ACTIVE TASK WORKSLOTS ---")
    for idx, (slot, desc, t_id) in enumerate(active_assignments, 1):
        print(f"  {idx}. [{slot}] {desc}")
    print("  0. Back")
        
    try:
        pick = input("\nSelect which task slot you have finished: ").strip()
        if pick == "0" or not pick:
            return
            
        pick = int(pick)
        if pick < 1 or pick > len(active_assignments):
            return
            
        slot_type, task_desc, template_id = active_assignments[pick - 1]
        
        difficulty_tier = _get_task_difficulty_tier(template_id)
        gold_pay = _get_gold_reward_for_tier(difficulty_tier)
        
        print(f"\n[+] Processing completion for {difficulty_tier} task...")

        # 1. PARSE AUTOMATIC XP TASK REWARDS
        if "xp in" in task_desc.lower():
            try:
                parts = task_desc.split()
                xp_amt = int(parts[1].replace(",", ""))
                skill_target = parts[-1].strip().capitalize()
                
                add_xp(cursor, skill_target, xp_amt)
                log_action(f"TASK_XP|{skill_target}|{xp_amt}")

                # --- NEW: COMBAT LEVEL TRIGGER ---
                combat_skills = {"Attack", "Strength", "Defence", "Hitpoints", "Prayer", "Ranged", "Magic"}
                if skill_target in combat_skills:
                    recalculate_combat_and_guild(cursor)
                    
            except Exception:
                print("   [*] Note: Could not auto-parse skill text rewards. Apply XP manually via Lamp if needed.")
                
        # 2. PARSE QUEST AUTOMATION
        if "complete the quest:" in task_desc.lower():
            try:
                colon_idx = task_desc.lower().find("complete the quest:") + len("complete the quest:")
                quest_name_extracted = task_desc[colon_idx:].strip()
                complete_quest_by_name(conn, cursor, quest_name_extracted)
            except Exception as e:
                print(f"   [!] Warning: Failed to auto-trigger quest completion details: {e}")

        # 3. CLEAR WORKSLOT AND AWARD REWARDS
        cursor.execute("UPDATE active_slots SET current_task_id = NULL, current_task_description = NULL WHERE slot_type = ?", (slot_type,))
        
        award_gold(cursor, gold_pay)
        log_action(f"TASK_COMPLETE|{task_desc}|{gold_pay}")
        conn.commit()
        print(f"[✓] {slot_type} slot task successfully cleared out! Awarded {gold_pay} gold.")

        # --- NEW: SLAYER SLOT PROCESSING FLAG ---
        # If the closed slot was your Slayer block, immediately prompt for their updated stat line
        if "slayer assignment" in task_desc.lower():
            complete_slayer_task(conn, cursor)
        
    except ValueError:
        print("[!] Processing error or invalid numerical entry selection.")
    
def check_and_unlock_skills(cursor):
    """
    Scans skill_requirements.json, evaluates if all region and quest criteria
    are met, and automatically flips is_unlocked to 1 for eligible skills.
    """
    SKILL_REQ_PATH = CONFIG_DIR / "skill_requirements.json" if (CONFIG_DIR / "skill_requirements.json").exists() else DATA_DIR / "skill_requirements.json"
    
    if not SKILL_REQ_PATH.exists():
        return

    try:
        with open(SKILL_REQ_PATH, "r", encoding="utf-8") as f:
            requirements_data = json.load(f)
            
        # Iterate over every skill defined in your json file
        for skill_name, reqs in requirements_data.items():
            skill_clean = skill_name.strip().capitalize()
            
            # Check if this skill is already unlocked in the DB
            cursor.execute("SELECT is_unlocked FROM player_stats WHERE skill_name = ?", (skill_clean,))
            status_row = cursor.fetchone()
            if not status_row or status_row[0] == 1:
                continue # Skip if already unlocked or doesn't exist

            # Validate Region Requirements
            regions_met = True
            required_regions = reqs.get("regions", [])
            for region in required_regions:
                cursor.execute("SELECT is_unlocked FROM unlockable_shop WHERE name = ? AND content_type = 'REGION'", (region.strip(),))
                reg_row = cursor.fetchone()
                if not reg_row or reg_row[0] == 0:
                    regions_met = False
                    break
            
            if not regions_met:
                continue

            # Validate Quest Requirements
            quests_met = True
            required_quests = reqs.get("quests", [])
            for quest in required_quests:
                cursor.execute("SELECT status FROM quests WHERE quest_name = ?", (quest.strip(),))
                q_row = cursor.fetchone()
                if not q_row or q_row[0] != 2:
                    quests_met = False
                    break
                    
            if not quests_met:
                continue

            # If both checks passed, unlock the skill!
            cursor.execute("UPDATE player_stats SET is_unlocked = 1 WHERE skill_name = ?", (skill_clean,))
            print(f"   [UNLOCKED] The {skill_clean.upper()} skill has been unlocked via requirements match!")
            log_action(f"SKILL_UNLOCKED|{skill_clean}")
            
    except Exception as e:
        print(f"   [!] Warning: Failed to process dynamic skill requirements file: {e}")

def recalculate_combat_and_guild(cursor):
    """
    Queries current base stats from player_stats and applies the 
    official OSRS formula to update 'Combat' and 'Warriors_guild_total'.
    """
    # 1. Fetch relevant skill levels from the database
    skills = ["Attack", "Strength", "Defence", "Hitpoints", "Prayer", "Ranged", "Magic"]
    stats = {}
    
    for s in skills:
        cursor.execute("SELECT current_level FROM player_stats WHERE skill_name = ?", (s,))
        row = cursor.fetchone()
        stats[s] = row[0] if row else 1

    # 2. Official OSRS Combat Level Calculation Formula
    base = 0.25 * (stats["Defence"] + stats["Hitpoints"] + (stats["Prayer"] // 2))
    melee = 0.325 * (stats["Attack"] + stats["Strength"])
    ranged = 0.325 * (stats["Ranged"] * 1.5 // 1)
    magic = 0.325 * (stats["Magic"] * 1.5 // 1)
    
    # Combat level is determined by the highest offensive type multiplier
    combat_level = int(base + max(melee, ranged, magic))
    
    # 3. Warriors' Guild Total Calculation Formula (Attack + Strength)
    warriors_guild_total = stats["Attack"] + stats["Strength"]

    # 4. Push updates to your virtual rows in player_stats
    cursor.execute("UPDATE player_stats SET current_level = ? WHERE skill_name = 'combat'", (combat_level,))
    cursor.execute("UPDATE player_stats SET current_level = ? WHERE skill_name = 'warriors_guild_total'", (warriors_guild_total,))
    
    print(f"   [RECALCULATED] Combat Level: {combat_level} | Warriors' Guild Total: {warriors_guild_total}")

def complete_slayer_task(conn, cursor):
    """Prompts the user for updated combat statuses, saves them, and forces a profile recalculation."""
    print("\n==============================================")
    print("SLAYER TASK COMPLETION COMBAT UPDATER")
    print("==============================================")
    print("Please input your updated levels to sync profile balances:")

    tracked_skills = ["Slayer", "Attack", "Strength", "Defence", "Hitpoints", "Ranged", "Magic", "Prayer"]
    updated_profiles = {}

    for skill in tracked_skills:
        while True:
            try:
                user_input = input(f"  Enter current {skill} level: ").strip()
                if not user_input:
                    # Fallback to current database value if left blank
                    cursor.execute("SELECT current_level FROM player_stats WHERE skill_name = ?", (skill,))
                    row = cursor.fetchone()
                    level = row[0] if row else 1
                else:
                    level = int(user_input)
                    if level < 1 or level > 99:
                        raise ValueError
                
                updated_profiles[skill] = level
                break
            except ValueError:
                print("   [!] Input Error: Please enter a valid integer level between 1 and 99.")

    # Push entries back down to your SQL profile
    print("\n   [+] Updating combat records...")
    for skill_name, current_level in updated_profiles.items():
        # Standardize matching cases
        skill_clean = skill_name.strip().capitalize()
        cursor.execute("""
            UPDATE player_stats 
            SET current_level = ? 
            WHERE skill_name = ?
        """, (current_level, skill_clean))

    # Trigger automatic virtual skill evaluations!
    recalculate_combat_and_guild(cursor)
    conn.commit()
    print("[✓] Profile database metrics fully unified!")

def use_lamp(conn, cursor):
    """Feature 4: Rub an XP lamp to manually inject experience points."""
    print("\n--- RUB AN EXPERIENCE LAMP ---")
    skill_choice = input("Target Skill: ").strip().capitalize()
    xp_amt = input("Experience Amount: ").strip()
    
    try:
        xp_amt = int(xp_amt)
        add_xp(cursor, skill_choice, xp_amt)
        log_action(f"LAMP|{skill_choice}|{xp_amt}")
        conn.commit()
        print("[✓] Experience lamp applied.")
    except ValueError:
        print("[!] Error: Invalid numeric XP amount entered.")