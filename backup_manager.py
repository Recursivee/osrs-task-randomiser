from progression import add_xp, recalculate_all_virtual_stats

def restore_from_log(conn, cursor, log_file_path):
    """
    Parses a history.log file line-by-line and re-applies changes
    to rebuild a corrupted or fresh character profile.
    """
    if not log_file_path.exists():
        print(f"[!] Log file not found at: {log_file_path}")
        return

    print(f"\n[Engine] Replaying logs from '{log_file_path.name}'...")
    restored_actions = 0

    with open(log_file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or "|" not in line:
                continue

            try:
                # Strip timestamp if present (e.g., "2026-07-22 17:00:00 | TASK_XP|Smithing|5000")
                if " | " in line:
                    action_data = line.split(" | ", 1)[1]
                else:
                    action_data = line

                parts = action_data.split("|")
                action_type = parts[0]

                # --- 1. XP REWARDS ---
                if action_type == "TASK_XP" and len(parts) >= 3:
                    skill, xp_amt = parts[1], int(parts[2])
                    add_xp(cursor, skill, xp_amt)
                    restored_actions += 1

                # --- 2. LEVEL MILESTONES ---
                elif action_type == "TASK_LEVEL_UP" and len(parts) >= 3:
                    skill, target_lvl = parts[1], int(parts[2])
                    cursor.execute(
                        "UPDATE player_stats SET current_level = ? WHERE skill_name = ?",
                        (target_lvl, skill)
                    )
                    restored_actions += 1

                # --- 3. TASK COMPLETION & GOLD AWARD ---
                elif action_type == "TASK_COMPLETE" and len(parts) >= 3:
                    try:
                        gold_reward = float(parts[2])
                        cursor.execute(
                            "UPDATE metadata SET gold_available = gold_available + ? WHERE id = 1",
                            (gold_reward,)
                        )
                        restored_actions += 1
                    except ValueError:
                        print(f"  [!] Invalid gold amount in line: '{line}'")

                # --- 4. SKILL UNLOCKS ---
                elif action_type == "SKILL_UNLOCKED" and len(parts) >= 2:
                    skill_name = parts[1]
                    cursor.execute(
                        "UPDATE player_stats SET is_unlocked = 1 WHERE skill_name = ?",
                        (skill_name,)
                    )
                    restored_actions += 1

                # --- 5. DIARY COMPLETIONS ---
                elif action_type == "DIARY_COMPLETE" and len(parts) >= 3:
                    diary_name, tier = parts[1], parts[2]
                    cursor.execute(
                        "UPDATE achievement_diaries SET is_completed = 1 WHERE diary_name = ? AND tier = ?",
                        (diary_name, tier)
                    )
                    restored_actions += 1

                # --- 6. QUEST COMPLETIONS ---
                elif action_type == "QUEST_COMPLETE" and len(parts) >= 2:
                    quest_name = parts[1]

                    # 1. Fetch Quest ID and Quest Points
                    cursor.execute(
                        "SELECT quest_id, quest_point_reward FROM quests WHERE quest_name = ?", 
                        (quest_name,)
                    )
                    q_row = cursor.fetchone()

                    if q_row:
                        quest_id, qp_reward = q_row[0], q_row[1]

                        # 2. Mark Quest Completed
                        cursor.execute("UPDATE quests SET status = 2 WHERE quest_id = ?", (quest_id,))

                        # 3. Add Quest Points to metadata
                        cursor.execute(
                            "UPDATE metadata SET total_quest_points = total_quest_points + ? WHERE id = 1", 
                            (qp_reward,)
                        )

                        # 4. Fetch and award Quest XP Rewards
                        cursor.execute(
                            "SELECT skill_name, xp_reward FROM quest_xp_rewards WHERE quest_id = ?", 
                            (quest_id,)
                        )
                        xp_rewards = cursor.fetchall()

                        for skill_name, xp_amt in xp_rewards:
                            add_xp(cursor, skill_name, xp_amt)

                    restored_actions += 1

            except Exception as e:
                print(f"  [!] Skipped corrupt log line: '{line}' ({e})")

    # Recalculate virtual levels (Combat, Total Level, etc.) after state replay
    recalculate_all_virtual_stats(cursor)
    conn.commit()
    print(f"[✓] Restoration complete! Replayed {restored_actions} logged events.")