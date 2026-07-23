# OSRS Task Generator & Dashboard

An interactive task locked Old School RuneScape challenge generator and progression manager built via python scripts, sqlite and flask (html, css, javascript). Created with AI assistance. 

Inspired by snowflake accounts and TadPie's gameplay mode "Adventurescape", this application generates random active and AFK tasks for your account, tracks skill levels, handles combat/slayer stat updating, and provides an unlock shop powered by task completion rewards.

---

## Features

- **Dual Task Slots**: Maintain **1 Active Task** and **1 AFK Task** concurrently.
- **Task Rolling System**: Roll 3 task choices for either Active or AFK slots and select the one you want to complete.
- **Unlock Shop**: Earn Gold by completing tasks to purchase new regions, bosses, minigames, and content unlocks.
- **XP Lamp Mechanics**:
  - Rub XP lamps to apply XP directly to any skill.
  - Supports banking XP into **locked skills** so levels immediately register when unlocked in the shop.
- **Smart Stat & Combat Recalculation**:
  - Completing Slayer tasks automatically prompts a stats update modal.
  - Automatically recalculates Virtual Stats (total level, warriors guild total, combat level) upon stat updates.
- **Full Web Dashboard**: Dynamic single-page dashboard displaying active tasks, metrics, stats grid, shop, and XP lamp interface.

---

## Tech Stack

- **Backend**: Python 3, Flask, SQLite3
- **Frontend**: HTML5, CSS3, JavaScript (Fetch API, Async/Await)
- **Database**: SQLite (`sqlite3`)

---

## To use

- 1: clone the repository:
```git clone [https://github.com/your-username/osrs-task-generator.git](https://github.com/your-username/osrs-task-generator.git)
cd osrs-task-generator```

- 2: Create a virtual environment (recommended):
```python -m venv venv
#on windows:
venv\Scripts\activate
#on linux/mac
source venv/bin/activate```

- 3: Install dependencies
```pip install requirements.txt```

- 4: Run database setup
```cd Scripts/
python full_db_setup.py```

- 5: Run main app
```python app.py```

---

## How to Play

Click to roll tasks, you can have 1 active and 1 afk task at a time. When rolling a task 3 options will present, pick whichever you want to complete as your task.
Completing tasks rewards gold, this gold can be spent on unlocking areas, bosses, minigames and raids. 
Quest completions have xp tracked automatically, and quest requirements are tracked automatically for future quests, bosses, raids, minigames, regions and achievement dairies. 
Slayer tasks are treated as free xp, you can choose combat style and on task completion stats will be updated as per user input. 
XP lamps can be put into any skill, these are recorded through the xp lamp section. Locked skills will bank xp until they are unlocked. 
The shop will only show content that you meet the requirements to purchase. 