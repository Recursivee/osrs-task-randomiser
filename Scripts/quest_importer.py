import requests
import re
import json
import time
import sqlite3
from pathlib import Path
from init_db import initialise_database

database_location = Path(__file__).resolve().parent.parent / "Database" / "database.db"
schema_location = Path(__file__).resolve().parent.parent / "Database" / "schema.sql"

conn = initialise_database(database_location, schema_location)
cursor = conn.cursor()

def save_to_db(quest_name, data):
    # 1. Insert the main quest (Ignore if already there)
    cursor.execute("INSERT OR IGNORE INTO quests (name, qp) VALUES (?, ?)", 
                   (quest_name, data['qp']))
    
    # Get the ID of the quest we just handled
    cursor.execute("SELECT id FROM quests WHERE name = ?", (quest_name,))
    quest_id = cursor.fetchone()[0]

    # 2. Insert Skill Requirements
    for s in data['skills']:
        cursor.execute("""
            INSERT OR REPLACE INTO skill_requirements (quest_id, skill, level) 
            VALUES (?, ?, ?)""", (quest_id, s['skill'], s['level']))

    # 3. Insert Quest Prerequisites
    for req_name in data['quests']:
        # We store the NAME for now; we can link IDs in a second pass
        cursor.execute("""
            INSERT OR IGNORE INTO quest_dependencies (quest_id, requirement_name) 
            VALUES (?, ?)""", (quest_id, req_name))
            
    conn.commit()

def get_all_quest_titles():
    """Fetches real quest articles only."""
    url = "https://oldschool.runescape.wiki/api.php"
    # We use 'allpages' in namespace 0 (Articles) to avoid Categories/Modules
    params = {
        "action": "query",
        "format": "json",
        "list": "categorymembers",
        "cmtitle": "Category:Quests",
        "cmtype": "page", # ONLY fetch pages, skip sub-categories like 'Quests/Novice'
        "cmlimit": "500",
        "formatversion": "2"
    }
    headers = {"User-Agent": "OSRS_Task_Generator/1.0 (Contact: matthew_k_hill@proton.me)"}
    
    response = requests.get(url, params=params, headers=headers)
    if not response.ok:
        return []
        
    data = response.json()
    titles = [page['title'] for page in data['query']['categorymembers']]
    
    # Final filter to remove meta-pages that are technically 'pages'
    forbidden_words = ["Quests/", "List of", "Quest points", "Template:", "User:"]
    clean_titles = [
        t for t in titles 
        if not any(word in t for word in forbidden_words)
    ]
    
    return clean_titles

def get_batch_quest_contents(titles_batch):
    """Fetches the content for 50 quests at once."""
    url = "https://oldschool.runescape.wiki/api.php"
    
    # We use POST to avoid URL length limits and look more 'official'
    data = {
        "action": "query",
        "prop": "revisions",
        "titles": "|".join(titles_batch), # The pipe '|' joins them for a batch request
        "rvprop": "content",
        "rvslots": "main",
        "format": "json",
        "formatversion": "2"
    }
    
    headers = {
        "User-Agent": "OSRS_Task_Generator/1.0 (Contact: matthew_k_hill@proton.me)",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    response = requests.post(url, data=data, headers=headers)
    
    if not response.ok:
        print(f"  Server Error: {response.status_code}")
        return []

    return response.json().get('query', {}).get('pages', [])

def parse_quest_data(text):
    # 1. FIND THE 'QUEST DETAILS' BLOCK
    details_match = re.search(r"\{\{Quest details(.*?)\n\}\}", text, re.DOTALL)
    if not details_match:
        details_match = re.search(r"\{\{Quest details(.*?)\}\}", text, re.DOTALL)
    
    if not details_match:
        return {"skills": [], "quests": [], "qp": 0, "series": None, "start_point": ""}
    
    details_block = details_match.group(1)

    # 2. TARGET THE REQUIREMENTS SECTION
    req_match = re.search(r"\|requirements\s*=\s*(.*?)(?=\n\|)", details_block, re.DOTALL)
    if not req_match:
        req_match = re.search(r"\|requirements\s*=\s*(.*?)(?=\|)", details_block, re.DOTALL)
    req_text = req_match.group(1) if req_match else ""

    # 3. PARSE SKILLS & QUESTS
    skill_pattern = r"\{\{\s*SCP\s*\|\s*(.*?)\s*\|\s*(\d+)"
    skills = re.findall(skill_pattern, req_text)
    
    quest_pattern = r"\[\[(.*?)\]\]"
    quests_raw = re.findall(quest_pattern, req_text)
    cleaned_quests = []
    for q in quests_raw:
        name = q.split("|")[0].strip()
        if not any(x in name for x in ["File:", "Category:", "Image:", "Special:", "Questreq", "SCP"]):
            cleaned_quests.append(name)

    # 4. PARSE QUEST POINTS
    qp_match = re.search(r"\|(?:qp|quest_points)\s*=\s*(\d+)", text)
    qp = qp_match.group(1) if qp_match else 0

    # 5. NEW: EXTRACTIONS FOR REGION AUTOMATION
    # Extract the quest series (if any)
    series_match = re.search(r"\|series\s*=\s*(.*?)\s*(?=\n\||\n\}\})", details_block)
    series = series_match.group(1).strip() if series_match else None

    # Extract the start point description string
    start_match = re.search(r"\|start\s*=\s*(.*?)\s*(?=\n\||\n\}\})", details_block)
    start_point = start_match.group(1).strip() if start_match else ""

# PARSE SKILL XP REWARDS (COMPREHENSIVE MULTI-MATCH EXTRACTION WITH COMMA HANDLING)
    xp_rewards = {}
    
    valid_skills = {
        "Attack", "Strength", "Defence", "Ranged", "Prayer", "Magic", "Runecraft", "Runecrafting", 
        "Construction", "Hitpoints", "Agility", "Herblore", "Thieving", "Crafting", "Fletching", 
        "Slayer", "Hunter", "Mining", "Smithing", "Fishing", "Cooking", "Firemaking", "Woodcutting", 
        "Farming", "Sailing"
    }
    
    # FIXED REGEX: Allows digits and commas in the second capture group [\d,]+
    scp_matches = re.findall(r"\{\{\s*SCP\s*\|\s*([^|]+?)\s*\|\s*([\d,]+)(?:[|}])", text, re.IGNORECASE)
    for skill_raw, amount_raw in scp_matches:
        skill = skill_raw.strip().capitalize()
        if skill == "Runecrafting": 
            skill = "Runecraft"
            
        # Strip out formatting commas (e.g., 40,000 -> 40000)
        clean_amount = re.sub(r'[^\d]', '', amount_raw)
        
        if skill in valid_skills and clean_amount.isdigit():
            xp_val = int(clean_amount)
            # Level requirement filter guard
            if xp_val > 99:
                xp_rewards[skill] = xp_rewards.get(skill, 0) + xp_val

    # Backup pattern for pages using lowercase {{xp|...}} macros
    xp_matches = re.findall(r"\{\{\s*xp\s*\|\s*([^|}]+?)\s*\|\s*([^|}]+?)\s*\}\}", text, re.IGNORECASE)
    for param1, param2 in xp_matches:
        p1, p2 = param1.strip(), param2.strip()
        
        skill_candidate = p1.capitalize() if p1.capitalize() in valid_skills else p2.capitalize()
        amount_candidate = p2 if p1.capitalize() in valid_skills else p1
        
        if skill_candidate in valid_skills:
            if skill_candidate == "Runecrafting": 
                skill_candidate = "Runecraft"
            clean_amount = re.sub(r'[^\d]', '', amount_candidate)
            if clean_amount.isdigit() and int(clean_amount) > 99:
                xp_rewards[skill_candidate] = xp_rewards.get(skill_candidate, 0) + int(clean_amount)
    

    return {
        "skills": [{"skill": s, "level": l} for s, l in skills],
        "quests": list(set(cleaned_quests)),
        "qp": qp,
        "series": series,
        "start_point": start_point,
        "xp_rewards": xp_rewards
    }

def determine_region(series, start_text):
    # Load configuration file
    config_path = Path(__file__).resolve().parent.parent / "Config" / "quest_regions.json"
    
    try:
        with open(config_path, "r", encoding="utf-8") as file:
            config_data = json.load(file)
            series_map = config_data.get("series_mappings", {})
            keyword_map = config_data.get("keyword_mappings", {})
    except FileNotFoundError:
        print(f"Warning: quest_regions.json not found at {config_path}. Falling back to UNKNOWN.")
        series_map = {}
        keyword_map = {}

    # Waterfall Step 1: Check quest series
    if series and series in series_map:
        return series_map[series]

    # Waterfall Step 2: Check start text location in quest regions keywords
    for region, keywords in keyword_map.items():
        if any(word.lower() in start_text.lower() for word in keywords):
            return region

    # Default fallback
    return "UNKNOWN"

    
def save_quest_to_db(title, data):
    # Call automated waterfall algorithm
    assigned_region = determine_region(data.get('series'), data.get('start_point'))

    # 1. Insert/Update the Quest (matching schema + status tracker)
    cursor.execute('''
        INSERT INTO quests (quest_name, quest_point_reward, region, status)
        VALUES (?, ?, ?, 0)
        ON CONFLICT(quest_name) DO UPDATE SET
            quest_point_reward=excluded.quest_point_reward,
            region=excluded.region
    ''', (title, data.get('qp', 0), assigned_region))
    
    # Get the generated quest_id
    cursor.execute("SELECT quest_id FROM quests WHERE quest_name = ?", (title,))
    quest_id = cursor.fetchone()[0]

    # 2. Insert Skill Requirements 
    cursor.execute("DELETE FROM skill_requirements WHERE target_type = 'QUEST' AND target_id = ?", (quest_id,))
    for s in data['skills']:
        cursor.execute('''
            INSERT OR IGNORE INTO skill_requirements (target_type, target_id, skill_name, level_required)
            VALUES ('QUEST', ?, ?, ?)
        ''', (quest_id, s['skill'].strip(), s['level']))
    
    # Insert XP Rewards 
    cursor.execute("DELETE FROM quest_xp_rewards WHERE quest_id = ?", (quest_id,))
    for skill, xp in data.get('xp_rewards', {}).items():
        cursor.execute('''
            INSERT INTO quest_xp_rewards (quest_id, skill_name, xp_reward)
            VALUES (?, ?, ?)
        ''', (quest_id, skill, xp))

    return (quest_id, data['quests'])


def link_quest_dependencies(pending_dependencies):
    print("Linking quest dependencies...")
    for quest_id, req_names in pending_dependencies:
        for req_name in req_names:
            # Look up the ID of the required quest
            cursor.execute("SELECT quest_id FROM quests WHERE quest_name = ?", (req_name,))
            result = cursor.fetchone()
            if result:
                req_id = result[0]
                cursor.execute('''
                    INSERT OR IGNORE INTO quest_requirements (quest_id, required_quest_id)
                    VALUES (?, ?)
                ''', (quest_id, req_id))
    conn.commit()
    

titles = get_all_quest_titles()
pending_deps = []

# Process in chunks
chunk_size = 50
for i in range(0, len(titles), chunk_size):
    batch = titles[i : i + chunk_size]
    pages = get_batch_quest_contents(batch)
    
    for page in pages:
        title = page.get('title')
        if "revisions" in page:
            content = page['revisions'][0]['slots']['main']['content']
            data = parse_quest_data(content)
            
            # Save the quest and skills, then queue the dependencies
            quest_info = save_quest_to_db(title, data)
            pending_deps.append(quest_info)
            
            print(f"  💾 Saved {title} to database.")
    
    conn.commit() # Commit after each batch
    time.sleep(5)

# Final Pass: Link all the IDs together
link_quest_dependencies(pending_deps)
print("Import complete!")