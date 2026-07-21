# scripts/export_actors.py
import os, pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()
engine = create_engine(os.environ["DATABASE_URL"])

sql = """
SELECT a.actor_id, a.name,
       COALESCE(a.description,'') AS description,
       COALESCE(a.location_city,'')    AS location,
       COALESCE(string_agg(DISTINCT h.name, '; '),'') AS hubs
FROM actor a
LEFT JOIN hub_actor ha ON ha.actor_id = a.actor_id
LEFT JOIN hub h        ON h.hub_id     = ha.hub_id
GROUP BY a.actor_id, a.name, a.description, a.location_city
"""
pd.read_sql(sql, engine).to_csv("data/exports/actors.csv", index=False)
print("wrote data/exports/actors.csv")