import json
import sqlite3
from pathlib import Path
from progression import check_and_unlock_skills, log_action

# Configuration paths
CONFIG_DIR = Path(__file__).resolve().parent / "Config"
DATA_DIR = Path(__file__).resolve().parent / "Data"
META_PATH = CONFIG_DIR / "meta_data.json"

def _get_shop_costs():
    """Loads default dynamic unlock costs from meta_data.json."""
    if not META_PATH.exists():
        return {"Region": 10, "Minigame": 5, "Boss": 3, "Raid": 15, "Reroll": 5}
    try:
        with open(META_PATH, "r", encoding="utf-8") as f:
            meta_config = json.load(f)
        return meta_config.get("Shop", {})
    except Exception:
        return {"Region": 10, "Minigame": 5, "Boss": 3, "Raid": 15, "Reroll": 5}

def open_shop_menu(conn, cursor):
    """Main interactive menu dashboard for the unlock store."""
    # 1. Grab current gold wallet balance
    cursor.execute("SELECT gold_available FROM metadata WHERE id = 1")
    gold_row = cursor.fetchone()
    current_gold = float(gold_row[0]) if gold_row else 0.0

    costs = _get_shop_costs()

    print(f"\n==============================================")
    print(f"       💰 THE CONTENT UNLOCK SHOP 💰          ")
    print(f"       Current Wallet Balance: {current_gold:.2f} Gold")
    print(f"==============================================")
    print(f"  1. Unlock a Region      (Cost: {costs.get('Region', 10)} Gold)")
    print(f"  2. Unlock a Boss        (Cost: {costs.get('Boss', 3)} Gold)")
    print(f"  3. Unlock a Minigame    (Cost: {costs.get('Minigame', 5)} Gold)")
    print(f"  4. Unlock a Raid        (Cost: {costs.get('Raid', 15)} Gold)")
    print(f"  0. Back")
    print(f"==============================================")

    choice = input("Select a category to view items: ").strip()

    category_map = {
        "1": ("REGION", costs.get("Region", 10)),
        "2": ("BOSS", costs.get("Boss", 3)),
        "3": ("MINIGAME", costs.get("Minigame", 5)),
        "4": ("RAID", costs.get("Raid", 15))
    }

    if choice not in category_map:
        return

    content_type, cost = category_map[choice]
    _browse_and_buy(conn, cursor, content_type, cost, current_gold)

def _browse_and_buy(conn, cursor, content_type, cost, current_gold):
    """Queries the specific content pool from the database, applies strict region filters, and handles purchases."""
    # 1. Fetch locked items, filtering out 'UNKNOWN' rows, and pulling parent quest and region details
    cursor.execute("""
        SELECT us.id, us.name, us.parent_quest_id, q.quest_name, q.status, us.region_dependency
        FROM unlockable_shop us
        LEFT JOIN quests q ON us.parent_quest_id = q.quest_id
        WHERE us.content_type = ? 
          AND us.is_unlocked = 0 
          AND UPPER(us.name) != 'UNKNOWN'
        ORDER BY us.name ASC
    """, (content_type,))
    locked_items = cursor.fetchall()

    if not locked_items:
        print(f"\n[🎉] You have already unlocked every valid item in the {content_type} category!")
        return

    print(f"\n--- LOCKED {content_type} ASSETS (Unlock Cost: {cost} Gold) ---")
    
    valid_menu_options = {}
    display_idx = 1

    for shop_id, name, parent_quest_id, parent_quest_name, quest_status, region_dependency in locked_items:
        
        # --- 1. DIRECT REGION LOCK GATEKEEPER ---
        # For non-region items, ensure its defined region_dependency is currently unlocked (is_unlocked = 1)
        if content_type != "REGION" and region_dependency:
            # We bypass Misthalin as it serves as the universal starter chunk
            if region_dependency.upper() != "MISTHALIN":
                cursor.execute("""
                    SELECT is_unlocked FROM unlockable_shop 
                    WHERE name = ? AND content_type = 'REGION'
                """, (region_dependency.strip(),))
                reg_row = cursor.fetchone()
                
                # Completely hide the asset from view if its map tile hasn't been paid for yet!
                if not reg_row or reg_row[0] == 0:
                    continue

        # --- 2. PROGRESSION ENFORCEMENT ---
        # A. Quest Gate: Parent quest must be fully completed (status 2)
        if parent_quest_id is not None and quest_status != 2:
            print(f"  [🔒 LOCK] {name} (Requires quest completion: '{parent_quest_name}')")
            continue

        # B. Skill Level Gates from skill_requirements table
        cursor.execute("""
            SELECT skill_name, level_required FROM skill_requirements 
            WHERE target_type = 'SHOP_ITEM' AND target_id = ?
        """, (shop_id,))
        
        skills_pass = True
        failed_skills = []
        for s_name, s_level in cursor.fetchall():
            cursor.execute("SELECT current_level FROM player_stats WHERE skill_name = ?", (s_name,))
            lvl_row = cursor.fetchone()
            current_lvl = lvl_row[0] if lvl_row else 1
            if current_lvl < s_level:
                skills_pass = False
                failed_skills.append(f"{s_name} {s_level}")

        if not skills_pass:
            req_str = ", ".join(failed_skills)
            print(f"  [🔒 LOCK] {name} (Requires levels: {req_str})")
            continue

        # If it passes region locks, quest locks, and level rules, display it as purchasable
        print(f"  {display_idx}. {name}")
        valid_menu_options[display_idx] = (shop_id, name)
        display_idx += 1
        
    print("  0. Cancel")

    if not valid_menu_options:
        print("\n[*] No items in this category are currently visible or claimable based on your region map progress.")
        return

    try:
        pick = input(f"\nSelect an item to purchase (0-{display_idx-1}): ").strip()
        if pick == "0" or not pick:
            return

        pick = int(pick)
        if pick not in valid_menu_options:
            print("[!] That selection is currently locked or hidden.")
            return

        target_id, target_name = valid_menu_options[pick]

        if current_gold < cost:
            print(f"\n[❌] Transaction Declined: You need {cost} gold, but only have {current_gold:.2f}.")
            return

        # Execute Transaction
        cursor.execute("UPDATE metadata SET gold_available = gold_available - ? WHERE id = 1", (float(cost),))
        cursor.execute("UPDATE unlockable_shop SET is_unlocked = 1 WHERE id = ?", (target_id,))
        
        print(f"\n[✓] Purchase Confirmed! Unlocked {content_type}: '{target_name}'")
        log_action(f"SHOP_UNLOCK|{content_type}|{target_name}|{cost}")

        if content_type == "REGION":
            from progression import check_and_unlock_skills
            check_and_unlock_skills(cursor)

        conn.commit()

    except ValueError:
        print("[!] Input error: Invalid transaction sequence.")