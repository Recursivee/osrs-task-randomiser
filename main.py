from progression import recalculate_all_virtual_stats
from time import process_time_ns
from os import closerange
import sys
import sqlite3
from pathlib import Path

# Connect to core script domains
import task_roller
import progression
import shop
import backup_manager

DB_PATH = Path(__file__).resolve().parent / "Database" / "database.db"

def display_menu(cursor):
    cursor.execute("SELECT slot_type, current_task_description FROM active_slots")
    slots = cursor.fetchall()

    active_task = "None"
    afk_task = "None"

    for slot_type, description in slots:
        if slot_type.upper() == "ACTIVE":
            active_task = description
        elif slot_type.upper() == "AFK":
            afk_task = description

    print("\n" + "=" * 50)
    print("      OSRS SNOWFLAKE TASK GENERATOR DASHBOARD")
    print("=" * 50)
    print(f"[ACTIVE TASK]: {active_task}")
    print(f"[AFK TASK]: {afk_task}")
    print("-" * 50)
    print("  1. Roll Task Selection (Generate 3 Choices)")
    print("  2. Complete Active Task / Quest")
    print("  3. Open Progression Unlock Shop")
    print("  4. Rub an Experience Lamp (Add Manual XP)")
    print("  5. View Character Sheet Status")
    print("  9. Restore Profile State from Log File")
    print("  0. Exit")
    print("-" * 50)

def view_character_sheet(conn, cursor):
    """Quick diagnostic utility printout."""
    cursor.execute("SELECT total_quest_points, gold_available FROM metadata WHERE id = 1")
    meta = cursor.fetchone()
    qp = meta[0] if meta else 0
    gold = meta[1] if meta else 0
    
    print(f"\n[CHARACTER SHEET] Quest Points: {qp}  |  Gold: {gold}")
    print("Unlocked Regions:")
    cursor.execute("SELECT name FROM unlockable_shop WHERE content_type = 'REGION' AND is_unlocked = 1")
    for r in cursor.fetchall():
        print(f" - {r[0]}")
    
    print("Unlocked Bosses:")
    cursor.execute("SELECT name FROM unlockable_shop WHERE content_type = 'BOSS' AND is_unlocked = 1")
    for r in cursor.fetchall():
        print(f" - {r[0]}")

    print("Unlocked Minigames:")
    cursor.execute("SELECT name FROM unlockable_shop WHERE content_type = 'MINIGAME' AND is_unlocked = 1")
    for r in cursor.fetchall():
        print(f" - {r[0]}")

    print("Unlocked Raids:")
    cursor.execute("SELECT name FROM unlockable_shop WHERE content_type = 'RAID' AND is_unlocked = 1")
    for r in cursor.fetchall():
        print(f" - {r[0]}")

    cursor.execute("""
        SELECT skill_name, current_level, current_xp, is_unlocked
        FROM player_stats
    """)
    stats_list = cursor.fetchall()

    virtual_skills = []
    standard_skills = []

    for name, lvl, xp, unlocked in stats_list:
        if name in ["Combat", "Warriors_guild_total", "Total"]:
            virtual_skills.append((name, lvl))
        else:
            standard_skills.append((name, lvl, xp, unlocked))
    
    for name, lvl in virtual_skills:
        clean_name = name.replace("_", " ").title()
        print(f"{clean_name}: Level {lvl}")
    print("-" * 50)

    for name, lvl, xp, unlocked in standard_skills:
        lock_status = " " if unlocked else "[LOCKED]"
        xp_string = f"{xp:,} xp" if unlocked else "[LOCKED]"
        print(f"{name}: Level {lvl} ({xp_string}) {lock_status}")
    print("-" * 50)

def main():
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}. Please run full_db_setup.py first!")
        sys.exit(1)

    while True:
        # We establish a clean connection/cursor context for every loop cycle 
        # to guarantee the database file doesn't lock up if sub-windows crash
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        display_menu(cursor)
        choice = input("Select an option (0-9): ").strip()
        
        if choice == "1":
            task_roller.generate_three_choices(conn, cursor)
        elif choice == "2":
            progression.handle_completions(conn, cursor)
        elif choice == "3":
            progression.recalculate_all_virtual_stats(cursor)
            conn.commit()
            shop.open_shop_menu(conn, cursor)
        elif choice == "4":
            progression.use_lamp(conn, cursor)
        elif choice == "9":
            log_file = Path(__file__).parent / "history.log"
            backup_manager.restore_from_log(conn, cursor, log_file)
        elif choice == "5":
            progression.recalculate_all_virtual_stats(cursor)
            conn.commit()
            view_character_sheet(conn, cursor)
        elif choice == "0":
            print("\nSafe travels, Adventurer.")
            conn.close()
            break
        else:
            print("[!] Invalid option. Please try again.")
            
        conn.close()

if __name__ == "__main__":
    main()