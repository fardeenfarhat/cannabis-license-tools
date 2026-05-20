import sqlite3
con = sqlite3.connect("data/rfp_monitor.db")
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("Tables:", tables)
for t in tables:
    cols = [c[1] for c in con.execute(f"PRAGMA table_info({t})").fetchall()]
    print(f"\n--- {t}: {cols}")
    rows = con.execute(f"SELECT * FROM {t} LIMIT 3").fetchall()
    for r in rows:
        print(" ", str(r)[:200])
con.close()
