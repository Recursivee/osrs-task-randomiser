PRAGMA foreign_keys = ON;

-- 1. TRACKS CHARACTER PROGRESSION
CREATE TABLE IF NOT EXISTS player_stats (
    skill_name TEXT PRIMARY KEY,
    current_level INTEGER DEFAULT 1,
    current_xp INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS metadata (
    id INTEGER PRIMARY KEY CHECK (id = 1), -- Guarantees only one row exists
    total_quest_points INTEGER DEFAULT 0,
    keys_available INTEGER DEFAULT 0
);

-- 2. THE UNLOCK SHOP (Consolidated Regions, Bosses, Raids, Minigames)
CREATE TABLE IF NOT EXISTS unlockable_shop (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    content_type TEXT NOT NULL, -- 'REGION', 'BOSS', 'MINIGAME', 'RAID'
    key_cost INTEGER NOT NULL,
    parent_quest_id INTEGER, -- Optional quest needed to access it
    is_unlocked BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (parent_quest_id) REFERENCES quests(quest_id)
);

-- 3. QUESTS MASTER DATA
CREATE TABLE IF NOT EXISTS quests (
    quest_id INTEGER PRIMARY KEY AUTOINCREMENT,
    quest_name TEXT UNIQUE NOT NULL,
    quest_point_reward INTEGER DEFAULT 0,
    status INTEGER DEFAULT 0 -- 0 = Locked, 1 = In Progress, 2 = Completed
);

-- 4. LEVEL & QUEST PREREQUISITES (Universal for Quests or Shop Items)
CREATE TABLE IF NOT EXISTS skill_requirements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT NOT NULL, -- 'QUEST' or 'SHOP_ITEM'
    target_id INTEGER NOT NULL,
    skill_name TEXT NOT NULL,
    level_required INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS quest_requirements (
    quest_id INTEGER,
    required_quest_id INTEGER,
    PRIMARY KEY (quest_id, required_quest_id),
    FOREIGN KEY (quest_id) REFERENCES quests(quest_id),
    FOREIGN KEY (required_quest_id) REFERENCES quests(quest_id)
);

-- 5. THE CRUCIAL MISSING PIECE: THE MASTER TASK POOL
CREATE TABLE IF NOT EXISTS tasks_master (
    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_description TEXT NOT NULL,
    task_type TEXT NOT NULL, -- 'ACTIVE' or 'AFK'
    difficulty_tier TEXT NOT NULL, -- 'EASY', 'MEDIUM', 'HARD', 'ELITE'
    associated_shop_id INTEGER, -- The region/boss unlock required to roll this
    FOREIGN KEY (associated_shop_id) REFERENCES unlockable_shop(id)
);

-- 6. ACTIVE SLOTS TRACKER (Handles your current state and the 3 choices)
CREATE TABLE IF NOT EXISTS active_slots (
    slot_type TEXT PRIMARY KEY, -- 'ACTIVE' or 'AFK'
    current_task_id INTEGER,    -- The task currently being worked on
    choice_1_id INTEGER,        -- Rolled choice 1
    choice_2_id INTEGER,        -- Rolled choice 2
    choice_3_id INTEGER,        -- Rolled choice 3
    FOREIGN KEY (current_task_id) REFERENCES tasks_master(task_id),
    FOREIGN KEY (choice_1_id) REFERENCES tasks_master(task_id),
    FOREIGN KEY (choice_2_id) REFERENCES tasks_master(task_id),
    FOREIGN KEY (choice_3_id) REFERENCES tasks_master(task_id)
);