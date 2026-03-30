"""
PostgreSQL advisory lock keys for startup DDL.

Serializes schema creation and LangGraph migrations when many processes start together —
especially the first time against an **empty** database, when concurrent ``CREATE`` runs
would otherwise collide on system catalogs (e.g. ``pg_type``) or migration rows.

``pg_advisory_lock(bigint)`` blocks until acquired; unlock on the same session.
"""

# Distinct int64 values — avoid collisions with other products on the same DB.
PG_ADV_LOCK_SQLALCHEMY_CREATE_ALL = 712_944_019_283_746_001
