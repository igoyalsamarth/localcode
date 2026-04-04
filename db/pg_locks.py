"""
PostgreSQL advisory lock keys for startup DDL.

Serializes :func:`db.create_tables` when many processes start together — especially on a
**fresh** database, when concurrent ``CREATE`` runs would otherwise collide on system
catalogs (e.g. ``pg_type``).

``pg_advisory_lock(bigint)`` blocks until acquired; unlock on the same **backend
session**. With **PgBouncer transaction pooling** (e.g. Supabase pooler :6543), a
``COMMIT`` returns the server to the pool and drops session locks, so lock + DDL + unlock
must run in **one DB transaction** on one checkout (see :func:`db.create_tables`).
"""

# Distinct int64 values — avoid collisions with other products on the same DB.
PG_ADV_LOCK_SQLALCHEMY_CREATE_ALL = 712_944_019_283_746_001
