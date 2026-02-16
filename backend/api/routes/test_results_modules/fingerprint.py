"""
SQL Fingerprinting and Canonicalization Utilities.

Provides functions to normalize SQL queries and generate fingerprints
for identifying similar workloads across different templates.
"""

import re
import hashlib

def canonicalize_sql(sql: str) -> str:
    """
    Normalize SQL query for comparison.
    
    - Removes comments
    - Normalizes whitespace
    - Uppercases keywords (basic)
    - Removes string literals (basic)
    
    Args:
        sql: Raw SQL query string.
        
    Returns:
        Canonicalized SQL string.
    """
    if not sql:
        return ""
        
    # Remove single line comments (-- ...)
    sql = re.sub(r'--.*$', '', sql, flags=re.MULTILINE)
    
    # Remove multi-line comments (/* ... */)
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    
    # Replace string literals with placeholder
    # This is a simple regex and might not handle escaped quotes perfectly
    sql = re.sub(r"'[^']*'", "'?'", sql)
    
    # Replace numeric literals with placeholder
    sql = re.sub(r'\b\d+\b', '?', sql)
    
    # Normalize whitespace (replace newlines/tabs with single space)
    sql = re.sub(r'\s+', ' ', sql).strip()
    
    # Uppercase for case-insensitivity
    return sql.upper()

def compute_sql_fingerprint(sql: str) -> str:
    """
    Compute a hash fingerprint for a SQL query.
    
    Args:
        sql: Raw SQL query string.
        
    Returns:
        MD5 hash hexdigest of the canonicalized SQL.
    """
    canonical = canonicalize_sql(sql)
    return hashlib.md5(canonical.encode('utf-8')).hexdigest()
