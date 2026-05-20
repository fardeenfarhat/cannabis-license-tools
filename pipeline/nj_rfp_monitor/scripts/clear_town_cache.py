"""Clear sub-task cache entries for a specific town so the next deep dive re-fetches them."""
import sqlite3
import sys

town = sys.argv[1] if len(sys.argv) > 1 else "Vineland"

con = sqlite3.connect("data/rfp_monitor.db")
tables = ["town_zoning", "town_zoning_meta", "town_rfp_signals", "town_attorneys"]
for t in tables:
    cur = con.execute(f"DELETE FROM {t} WHERE municipality = ?", (town,))
    print(f"  {t}: deleted {cur.rowcount} row(s)")
con.commit()
con.close()
print(f"Cache cleared for {town}. Re-run --deep to fetch fresh data.")
