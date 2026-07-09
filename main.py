import sys
import sqlite3
from pathlib import Path

# Connect to core script domains
import task_roller
import progression
import shop
import backup_manager

DB_PATH = Path(__file__).resolve().parent / "Database" / "database.db"

def display_menu():
    print("\n" + "=" * 50)
    print("      OSRS SNOWFLAKE TASK GENERATOR DASHBOARD")
    print("=" * 50)
    print("  1. Roll Task Selection (Generate 3 Choices)")
    print("  2. Complete Active Task / Quest")
    print("  3. Open Progression Unlock Shop")
    print("  4. Rub an Experience Lamp (Add Manual XP)")
    print("  5. Restore Profile State from Log File")
    print("  6. View Character Sheet Status")
    print("  0. Exit")
    print("-" * 50)

def view_character_sheet(cursor):
    """Quick diagnostic utility printout."""
    cursor.execute("SELECT total_quest_points, gold_available FROM metadata WHERE id = 1")
    meta = cursor.fetchone()
    qp = meta[0] if meta else 0
    gold = meta[1] if meta else 0
    
    print(f"\n[CHARACTER SHEET] Quest Points: {qp}  |  Gold/Keys: {gold}")
    print("Unlocked Regions:")
    cursor.execute("SELECT name FROM unlockable_shop WHERE content_type = 'REGION' AND is_unlocked = 1")
    for r in cursor.fetchall():
        print(f" - {r[0]}")

def main():
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}. Please run full_db_setup.py first!")
        sys.exit(1)

    while True:
        # We establish a clean connection/cursor context for every loop cycle 
        # to guarantee the database file doesn't lock up if sub-windows crash
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        display_menu()
        choice = input("Select an option (0-6): ").strip()
        
        if choice == "1":
            task_roller.generate_three_choices(conn, cursor)
        elif choice == "2":
            progression.handle_completions(conn, cursor)
        elif choice == "3":
            shop.open_shop_menu(conn, cursor)
        elif choice == "4":
            progression.use_lamp(conn, cursor)
        elif choice == "5":
            backup_manager.restore_from_log(conn, cursor)
        elif choice == "6":
            view_character_sheet(cursor)
        elif choice == "0":
            print("\nSafe travels, Adventurer.")
            conn.close()
            break
        else:
            print("[!] Invalid option. Please try again.")
            
        conn.close()

if __name__ == "__main__":
    main()