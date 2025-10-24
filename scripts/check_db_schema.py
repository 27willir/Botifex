#!/usr/bin/env python3
"""
Check database schema
"""
import sqlite3

def check_schema():
    db_file = "superbot.db"
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    
    # Check rate_limits table structure
    c.execute("PRAGMA table_info(rate_limits)")
    columns = c.fetchall()
    
    print("rate_limits table columns:")
    for col in columns:
        print(f"  {col[1]} ({col[2]})")
    
    # Check if endpoint_type column exists
    column_names = [col[1] for col in columns]
    if 'endpoint_type' in column_names:
        print("endpoint_type column exists")
    else:
        print("endpoint_type column missing")
        print("Available columns:", column_names)
    
    conn.close()

if __name__ == "__main__":
    check_schema()
