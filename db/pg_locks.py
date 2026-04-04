"""
PostgreSQL advisory lock keys for startup DDL.

Serializes :func:`db.create_tables` when many processes start together — especially on a
**fresh** database, when concurrent ``CREATE`` runs would otherwise collide on system
catalogs (e.g. ``pg_type``).

``pg_advisory_lock(bigint)`` blocks until acquired; unlock on the same session.
"""

# Distinct int64 values — avoid collisions with other products on the same DB.
PG_ADV_LOCK_SQLALCHEMY_CREATE_ALL = 712_944_019_283_746_001
