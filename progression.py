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


def complete_task_programmatic(conn, cursor, slot_type="ACTIVE"):
    """
    Programmatic entry point for Flask API completions.
    Evaluates active task, updates database, awards gold, clears slot,
    and flags whether the frontend should display a Combat/Slayer update modal.
    """
    # 1. Fetch active task details
    cursor.execute(
        "SELECT current_task_description, current_task_id FROM active_slots WHERE slot_type = ?", 
        (slot_type,)
    )
    row = cursor.fetchone()
    
    if not row or not row[0]:
        return {"success": False, "message": f"No active task found in {slot_type} slot."}

    task_desc, template_id = row[0], row[1]

    # 2. Determine reward amount and category
    difficulty_tier = _get_task_difficulty_tier(template_id)
    gold_pay = _get_gold_reward_for_tier(difficulty_tier)

    task_category = "Unknown"
    if POOL_PATH.exists():
        try:
            with open(POOL_PATH, "r", encoding="utf-8") as f:
                pool_config = json.load(f)
            for task in pool_config.get("Tasks", []):
                if task.get("template_id") == template_id:
                    task_category = task.get("category", "Unknown")
                    break
        except Exception:
            pass

    # 3. Parse and apply automatic rewards (XP, Levels, Quests, Diaries)
    if "xp" in task_desc.lower() and "in" in task_desc.lower():
        try:
            gain_start = task_desc.lower().find("gain ") + 5
            xp_end = task_desc.lower().find(" xp")
            xp_str = task_desc[gain_start:xp_end].strip().replace(",", "")
            xp_amt = int(xp_str)
            skill_target = task_desc.split()[-1].strip().capitalize()

            add_xp(cursor, skill_target, xp_amt)
            log_action(f"TASK_XP|{skill_target}|{xp_amt}")
        except Exception as e:
            print(f" [!] XP Parsing error: {e}")

    elif "reach level" in task_desc.lower():
        try:
            parts = task_desc.lower().split()
            lvl_idx = parts.index("level") + 1
            target_lvl = int(parts[lvl_idx])
            skill_target = parts[-1].strip().capitalize()
            target_xp = XP_TABLE[target_lvl]

            cursor.execute("""
                UPDATE player_stats 
                SET current_level = ?, current_xp = ? 
                WHERE skill_name = ?
            """, (target_lvl, target_xp, skill_target))
            log_action(f"TASK_LEVEL_UP|{skill_target}|{target_lvl}")
        except Exception as e:
            print(f" [!] Level milestone error: {e}")

    if "complete the quest:" in task_desc.lower():
        try:
            colon_idx = task_desc.lower().find("complete the quest:") + len("complete the quest:")
            quest_name = task_desc[colon_idx:].strip()
            complete_quest_by_name(conn, cursor, quest_name)
        except Exception as e:
            print(f" [!] Quest trigger error: {e}")

    if "achievement diary:" in task_desc.lower():
        try:
            colon_idx = task_desc.lower().find("achievement diary:") + len("achievement diary:")
            diary_content = task_desc[colon_idx:].strip()
            open_bracket = diary_content.find("(")
            close_bracket = diary_content.find(")")
            diary_name = diary_content[:open_bracket].strip()
            tier_extracted = diary_content[open_bracket+1:close_bracket].strip().capitalize()

            cursor.execute("""
                UPDATE achievement_diaries 
                SET is_completed = 1 
                WHERE diary_name = ? AND tier = ?
            """, (diary_name, tier_extracted))
            log_action(f"DIARY_COMPLETE|{diary_name}|{tier_extracted}")
        except Exception as e:
            print(f" [!] Diary trigger error: {e}")

    # 4. Clear slot and award gold
    cursor.execute("""
        UPDATE active_slots 
        SET current_task_id = NULL, current_task_description = NULL 
        WHERE slot_type = ?
    """, (slot_type,))

    award_gold(cursor, gold_pay)
    log_action(f"TASK_COMPLETE|{task_desc}|{gold_pay}")
    
    # Recalculate virtual stats and commit changes
    recalculate_all_virtual_stats(cursor)
    conn.commit()

    # 5. Check if Slayer or Boss requires user input modal
    is_slayer = "slayer" in task_desc.lower() or task_category in ("Slayer", "Boss")

    if is_slayer:
        tracked_skills = ["Slayer", "Attack", "Strength", "Defence", "Hitpoints", "Ranged", "Magic", "Prayer"]
        current_levels = {}
        for skill in tracked_skills:
            cursor.execute("SELECT current_level FROM player_stats WHERE LOWER(skill_name) = LOWER(?)", (skill,))
            r = cursor.fetchone()
            current_levels[skill] = (r["current_level"] if isinstance(r, sqlite3.Row) else r[0]) if r else 1

        return {
            "success": True,
            "requires_input": True,
            "input_type": "slayer_combat",
            "current_levels": current_levels,
            "message": f"Task cleared! Awarded {gold_pay} Gold. Please update your combat levels."
        }

    return {
        "success": True,
        "requires_input": False,
        "message": f"Task completed successfully! Awarded {gold_pay} Gold."
    }


def update_slayer_combat_programmatic(conn, cursor, skill_levels_dict):
    """
    Programmatic entry point for Flask API.
    Accepts a dictionary of skill levels from web UI: {'Slayer': 75, 'Attack': 80, ...}
    Updates player_stats, recalculates combat, and commits.
    """
    for skill_name, current_level in skill_levels_dict.items():
        if current_level is None:
            continue
            
        skill_clean = skill_name.strip().capitalize()
        try:
            current_level = int(current_level)
            if 1 <= current_level <= 99:
                target_xp = XP_TABLE[current_level]
                cursor.execute("""
                    UPDATE player_stats 
                    SET current_level = ?, current_xp = ?
                    WHERE skill_name = ?
                """, (current_level, target_xp, skill_clean))
        except (ValueError, TypeError):
            continue

    recalculate_combat_and_guild(cursor)
    recalculate_all_virtual_stats(cursor)
    conn.commit()
    return True


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
        
        # --- NEW: Fetch category to explicitly check for Boss tasks ---
        task_category = "Unknown"
        if POOL_PATH.exists():
            try:
                with open(POOL_PATH, "r", encoding="utf-8") as f:
                    pool_config = json.load(f)
                for task in pool_config.get("Tasks", []):
                    if task.get("template_id") == template_id:
                        task_category = task.get("category", "Unknown")
                        break
            except Exception:
                pass
        
        print(f"\n[+] Processing completion for {difficulty_tier} task...")

        # --- NEW & IMPROVED PARSING BLOCK ---
        # --- FIXED Rule A: Parse standard & total XP tasks (Skill at the end) ---
        if "xp" in task_desc.lower() and "in" in task_desc.lower():
            try:
                # 1. Grab the XP amount (always between "Gain " and the first " xp")
                gain_start = task_desc.lower().find("gain ") + 5
                xp_end = task_desc.lower().find(" xp")
                xp_str = task_desc[gain_start:xp_end].strip().replace(",", "")
                xp_amt = int(xp_str)
                
                # 2. Grab the skill (always the very last word)
                skill_target = task_desc.split()[-1].strip().capitalize()
                
                # 3. Process database update
                add_xp(cursor, skill_target, xp_amt)
                log_action(f"TASK_XP|{skill_target}|{xp_amt}")

                # Combat Level trigger
                combat_skills = {"Attack", "Strength", "Defence", "Hitpoints", "Prayer", "Ranged", "Magic"}
                if skill_target in combat_skills:
                    recalculate_combat_and_guild(cursor)
                    
            except Exception as e:
                print(f"   [!] Error auto-parsing skill text rewards: {e}")
                
        # Rule B: Parse leveling-up tasks (e.g., "Reach level 7 in Smithing")
        elif "reach level" in task_desc.lower():
            try:
                parts = task_desc.lower().split()
                lvl_idx = parts.index("level") + 1
                target_lvl = int(parts[lvl_idx])
                skill_target = parts[-1].strip().capitalize()
                
                target_xp = XP_TABLE[target_lvl]
                
                cursor.execute("""
                    UPDATE player_stats 
                    SET current_level = ?, current_xp = ? 
                    WHERE skill_name = ?
                """, (target_lvl, target_xp, skill_target))
                
                print(f"   [LEVEL UP] Your {skill_target} level was successfully synced to level {target_lvl} ({target_xp:,} XP)!")
                log_action(f"TASK_LEVEL_UP|{skill_target}|{target_lvl}")

                combat_skills = {"Attack", "Strength", "Defence", "Hitpoints", "Prayer", "Ranged", "Magic"}
                if skill_target in combat_skills:
                    recalculate_combat_and_guild(cursor)

            except Exception as e:
                print(f"   [*] Note: Could not auto-parse leveling milestones: {e}")

        # Rule C: Parse Quest Automation
        if "complete the quest:" in task_desc.lower():
            try:
                colon_idx = task_desc.lower().find("complete the quest:") + len("complete the quest:")
                quest_name_extracted = task_desc[colon_idx:].strip()
                complete_quest_by_name(conn, cursor, quest_name_extracted)
            except Exception as e:
                print(f"   [!] Warning: Failed to auto-trigger quest completion details: {e}")

        # --- Rule D: Parse Achievement Diary Automation ---
        # Matches template: "Complete the achievement diary: Lumbridge & Draynor (Easy)"
        if "achievement diary:" in task_desc.lower():
            try:
                # Find where the actual diary data begins after the colon
                colon_idx = task_desc.lower().find("achievement diary:") + len("achievement diary:")
                diary_content = task_desc[colon_idx:].strip() # e.g., "Lumbridge & Draynor (Easy)"
                
                open_bracket = diary_content.find("(")
                close_bracket = diary_content.find(")")
                
                # Extract the exact name string without modifications
                diary_name_matched = diary_content[:open_bracket].strip() # e.g., "Lumbridge & Draynor"
                tier_extracted = diary_content[open_bracket+1:close_bracket].strip().capitalize()
                
                # Force update target row state
                cursor.execute("""
                    UPDATE achievement_diaries 
                    SET is_completed = 1 
                    WHERE diary_name = ? AND tier = ?
                """, (diary_name_matched, tier_extracted))
                
                if cursor.rowcount > 0:
                    print(f"   [DIARY ACHIEVEMENT] Achievement unlocked: {diary_name_matched} ({tier_extracted}) updated to Completed!")
                    log_action(f"DIARY_COMPLETE|{diary_name_matched}|{tier_extracted}")
                else:
                    print(f"   [!] Warning: Could not find a database diary row named '{diary_name_matched}' with tier '{tier_extracted}'")
                    
            except Exception as e:
                print(f"   [*] Note: Could not auto-parse diary milestone updates: {e}")

        # 3. CLEAR WORKSLOT AND AWARD REWARDS
        cursor.execute("UPDATE active_slots SET current_task_id = NULL, current_task_description = NULL WHERE slot_type = ?", (slot_type,))
        
        award_gold(cursor, gold_pay)
        log_action(f"TASK_COMPLETE|{task_desc}|{gold_pay}")
        conn.commit()
        print(f"[✓] {slot_type} slot task successfully cleared out! Awarded {gold_pay} gold.")

        # --- SLAYER OR BOSS COMPLETION FLAG ---
        if "slayer assignment" in task_desc.lower() or task_category == "Boss":
            if task_category == "Boss":
                print("\n[Boss Slain!] Launching Combat Updater to log your boss fight experience drops...")
            complete_slayer_task(conn, cursor)
            
        # --- MINIGAME CURRENT XP SYNC ---
        elif task_category == "Minigame":
            print(f"\n[Minigame Completed!] '{task_desc}'")
            print("Hover over your skills in-game and type their current total XP values below.")
            
            while True:
                skill_input = input("Enter a skill to sync XP for (or press Enter to finish): ").strip().capitalize()
                if not skill_input:
                    break
                
                # Fetch the database current XP to calculate the gain accurately
                cursor.execute("SELECT current_xp FROM player_stats WHERE skill_name = ?", (skill_input,))
                skill_row = cursor.fetchone()
                
                if not skill_row:
                    print(f"  [!] '{skill_input}' is not a valid skill name in the database. Try again.")
                    continue
                    
                db_current_xp = skill_row[0]
                
                try:
                    xp_input = input(f"Enter the CURRENT total XP for {skill_input}: ").strip().replace(",", "")
                    client_current_xp = int(xp_input)
                    
                    if client_current_xp < db_current_xp:
                        print(f"  [!] Entered XP ({client_current_xp:,}) is less than what's in the database ({db_current_xp:,}).")
                        print("      You cannot lose experience! Please verify the number.")
                        continue
                        
                    # Calculate the delta gain
                    xp_gained = client_current_xp - db_current_xp
                    
                    if xp_gained == 0:
                        print(f"  [-] No XP change detected for {skill_input}.")
                        continue
                        
                    # Channel the calculated difference into your existing progression routine
                    add_xp(cursor, skill_input, xp_gained)
                    log_action(f"MINIGAME_SYNC|{skill_input}|+{xp_gained} (Total: {client_current_xp})")
                    
                    # Update virtual totals if a combat skill was altered
                    combat_skills = {"Attack", "Strength", "Defence", "Hitpoints", "Prayer", "Ranged", "Magic"}
                    if skill_input in combat_skills:
                        recalculate_combat_and_guild(cursor)
                        
                    print(f"  [✓] Synced! Added +{xp_gained:,} XP to {skill_input} (New Total: {client_current_xp:,}).")
                except ValueError:
                    print("  [!] Invalid XP amount. Please enter a valid number.")
            
            # Recalculate global virtual tracking metrics (like Total level)
            recalculate_all_virtual_stats(cursor)
            conn.commit()
            print("[✓] Minigame session tracking successfully synced and saved.")
        
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

def recalculate_all_virtual_stats(cursor):
    """
    Calculates and synchronizes all virtual metrics: 'combat', 'warriors_guild_total', 
    and 'total' (Total Level) directly inside the player_stats table.
    """
    # 1. Fetch all skill entries from the database
    cursor.execute("SELECT skill_name, current_level FROM player_stats")
    all_stats = cursor.fetchall()
    
    # Store them in a case-insensitive dictionary for safe math operations
    stats = {name.strip().lower(): lvl for name, lvl in all_stats}
    
    # Define our virtual skill keys so we don't accidentally sum them into the Total Level
    virtual_keys = {"combat", "warriors_guild_total", "total"}
    
    # 2. Calculate Total Level (Sum of all real/standard skills)
    total_level = sum(lvl for name, lvl in stats.items() if name not in virtual_keys)
    
    # 3. Official OSRS Combat Level Formula (safely defaulting missing skills to 1)
    defence = stats.get("defence", 1)
    hitpoints = stats.get("hitpoints", 1)
    prayer = stats.get("prayer", 1)
    attack = stats.get("attack", 1)
    strength = stats.get("strength", 1)
    ranged = stats.get("ranged", 1)
    magic = stats.get("magic", 1)
    
    base = 0.25 * (defence + hitpoints + (prayer // 2))
    melee = 0.325 * (attack + strength)
    ranged_calc = 0.325 * (ranged * 1.5 // 1)
    magic_calc = 0.325 * (magic * 1.5 // 1)
    
    combat_level = int(base + max(melee, ranged_calc, magic_calc))
    
    # 4. Warriors' Guild Total Formula (Attack + Strength)
    warriors_guild_total = attack + strength

    # 5. Push updates to the lowercase rows in the database
    cursor.execute("UPDATE player_stats SET current_level = ? WHERE skill_name = 'Total'", (total_level,))
    cursor.execute("UPDATE player_stats SET current_level = ? WHERE skill_name = 'Combat'", (combat_level,))
    cursor.execute("UPDATE player_stats SET current_level = ? WHERE skill_name = 'Warriors_guild_total'", (warriors_guild_total,))

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
        # Standardise matching cases
        skill_clean = skill_name.strip().capitalize()

        target_xp = XP_TABLE[current_level]

        cursor.execute("""
            UPDATE player_stats 
            SET current_level = ?, current_xp = ?
            WHERE skill_name = ?
        """, (current_level, target_xp, skill_clean))

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

def use_lamp_programmatic(conn, cursor, skill_name, xp_amt):
    """Applies an XP lamp to any target skill (locked or unlocked)."""
    try:
        xp_amt = int(xp_amt)
        skill_choice = skill_name.strip().capitalize()
        
        # Verify the skill exists in player_stats (regardless of locked status)
        cursor.execute("SELECT skill_name, is_unlocked FROM player_stats WHERE LOWER(skill_name) = LOWER(?)", (skill_choice,))
        row = cursor.fetchone()
        
        if not row:
            return {"success": False, "message": f"Skill '{skill_choice}' not found."}

        # Add XP directly (will bank XP even if skill is locked)
        add_xp(cursor, skill_choice, xp_amt)
        log_action(f"LAMP|{skill_choice}|{xp_amt}")
        
        # Recalculate virtual stats/levels
        recalculate_all_virtual_stats(cursor)
        conn.commit()
        
        is_unlocked = row[1] == 1 or row[1] is True
        status_msg = "applied" if is_unlocked else "banked for future unlock"
        
        return {
            "success": True, 
            "message": f"Successfully {status_msg} {xp_amt:,} XP for {skill_choice}!"
        }
    except ValueError:
        return {"success": False, "message": "Invalid numeric XP amount."}
    except Exception as e:
        return {"success": False, "message": f"Error applying lamp: {str(e)}"}