from flask import Flask, render_template, jsonify, request
import sqlite3
from pathlib import Path

# Import your existing backend logic modules
from progression import recalculate_all_virtual_stats, complete_task_programmatic, update_slayer_combat_programmatic, use_lamp_programmatic
import task_roller
import progression
from shop import get_available_shop_items
import backup_manager 

app = Flask(__name__)
DB_PATH = Path(__file__).parent / "Database" / "database.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Allows accessing columns by name (e.g. row['skill_name'])
    return conn

@app.route("/")
def index():
    """Renders the main dashboard page."""
    return render_template("index.html")

@app.route("/api/dashboard-data", methods=["GET"])
def dashboard_data():
    conn = get_db()
    cursor = conn.cursor()

    # 1. Fetch metadata (Gold, Quest Points)
    cursor.execute("SELECT gold_available, total_quest_points FROM metadata WHERE id = 1")
    meta = cursor.fetchone()
    gold = meta["gold_available"] if meta else 0.0
    qp = meta["total_quest_points"] if meta else 0

    # 2. Fetch Active Slots
    cursor.execute("SELECT slot_type, current_task_description FROM active_slots")
    slots = cursor.fetchall()
    active_slots_data = [dict(s) for s in slots]

    # 3. Fetch ALL skills with current_xp included (filtering virtual stats)
    cursor.execute("""
        SELECT skill_name, current_level, current_xp, is_unlocked 
        FROM player_stats 
        WHERE LOWER(skill_name) NOT IN ('combat', 'warriors_guild_total', 'total')
        ORDER BY skill_name ASC
    """)
    stats_rows = cursor.fetchall()
    stats_data = [dict(s) for s in stats_rows]

    conn.close()

    return jsonify({
        "metadata": {"gold": gold, "quest_points": qp},
        "active_slots": active_slots_data,
        "stats": stats_data
    })

@app.route("/api/complete_task", methods=["POST"])
def api_complete_task():
    data = request.get_json() or {}
    slot_type = data.get("slot_type", "ACTIVE")

    conn = get_db()
    cursor = conn.cursor()

    # Get response dict from progression
    result = complete_task_programmatic(conn, cursor, slot_type=slot_type)
    conn.close()

    return jsonify(result)

@app.route("/api/submit_slayer_combat", methods=["POST"])
def api_submit_slayer_combat():
    data = request.get_json() or {}
    levels = data.get("levels", {})

    conn = get_db()
    cursor = conn.cursor()

    success = update_slayer_combat_programmatic(conn, cursor, levels)
    conn.close()

    if success:
        return jsonify({"success": True, "message": "Combat stats successfully updated!"})
    return jsonify({"success": False, "message": "Failed to update combat stats."}), 400

@app.route("/api/roll-tasks", methods=["POST"])
def api_roll_tasks():
    # Safely extract JSON payload
    data = request.get_json(silent=True) or {}
    
    # Extract slot_type safely with a default
    slot_type = data.get("slot_type", "ACTIVE")

    conn = get_db()
    cursor = conn.cursor()

    try:
        # Pass slot_type explicitly
        choices = task_roller.generate_three_choices(conn, cursor, slot_type=slot_type) 
        conn.commit()
        conn.close()
        return jsonify({
            "status": "success", 
            "choices": choices, 
            "slot_type": slot_type
        })
    except Exception as e:
        conn.close()
        print(f"[!] Error rolling tasks: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/select-task", methods=["POST"])
def api_select_task():
    data = request.json or {}
    selected_text = data.get("description")
    slot_type = data.get("slot_type", "ACTIVE")

    conn = get_db()
    cursor = conn.cursor()

    # Delete existing active slot entry and insert accepted task
    cursor.execute("DELETE FROM active_slots WHERE slot_type = ?", (slot_type,))
    cursor.execute("""
        INSERT INTO active_slots (slot_type, current_task_description)
        VALUES (?, ?)
    """, (slot_type, selected_text))

    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Task accepted!"})

@app.route("/api/shop-items", methods=["GET"])
def get_shop_items():
    conn = get_db()
    cursor = conn.cursor()

    # Get only items meeting region, quest, and skill level requirements
    items = get_available_shop_items(cursor)
    
    conn.close()
    return jsonify({"items": items})


@app.route("/api/buy-item", methods=["POST"])
def buy_item():
    data = request.json or {}
    item_id = data.get("item_id")

    if not item_id:
        return jsonify({"status": "error", "message": "No item ID provided."}), 400

    conn = get_db()
    cursor = conn.cursor()

    try:
        # 1. Fetch current gold
        cursor.execute("SELECT gold_available FROM metadata WHERE id = 1")
        meta_row = cursor.fetchone()
        current_gold = float(meta_row["gold_available"]) if meta_row else 0.0

        # 2. Fetch item details
        cursor.execute("SELECT name, key_cost, is_unlocked FROM unlockable_shop WHERE id = ?", (item_id,))
        item = cursor.fetchone()

        if not item:
            conn.close()
            return jsonify({"status": "error", "message": "Item not found."}), 404

        item_name = item["name"]
        cost = float(item["key_cost"])
        is_unlocked = item["is_unlocked"]

        if is_unlocked == 1:
            conn.close()
            return jsonify({"status": "error", "message": f"'{item_name}' is already unlocked!"}), 400

        if current_gold < cost:
            conn.close()
            return jsonify({"status": "error", "message": f"Not enough Gold! Costs {cost} Gold (You have {current_gold})."}), 400

        # 3. Deduct Gold and unlock item
        new_gold = current_gold - cost
        cursor.execute("UPDATE metadata SET gold_available = ? WHERE id = 1", (new_gold,))
        cursor.execute("UPDATE unlockable_shop SET is_unlocked = 1 WHERE id = ?", (item_id,))

        # 4. Check if unlocking this region/item unlocks skills via progression.py
        if hasattr(progression, 'check_and_unlock_skills'):
            progression.check_and_unlock_skills(cursor)

        conn.commit()
        conn.close()

        return jsonify({
            "status": "success", 
            "message": f"Successfully unlocked {item_name} for {cost} Gold!"
        })

    except Exception as e:
        conn.close()
        print(f"[!] Error processing shop purchase: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/use-lamp", methods=["POST"])
def api_use_lamp():
    data = request.get_json() or {}
    skill_name = data.get("skill_name")
    xp_amount = data.get("xp_amount")

    if not skill_name or not xp_amount:
        return jsonify({"success": False, "message": "Missing skill name or XP amount."}), 400

    conn = get_db()
    cursor = conn.cursor()

    result = use_lamp_programmatic(conn, cursor, skill_name, xp_amount)

    conn.close()
    return jsonify(result)


if __name__ == "__main__":
    # Host on 0.0.0.0 so you can access it from other devices on your local Wi-Fi if desired
    app.run(host="0.0.0.0", port=5000, debug=True)