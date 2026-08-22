"""Shared snapshot selection helpers.

Running snapshots are excluded because they may contain incomplete provider
data. Complete, partial, and failed snapshots are treated as finalised runs.

Contributor: Jena Jeong (23208300)
"""


def get_finalised_snapshot_ids(conn):
    """Return all non-running snapshot IDs in ascending order."""

    # Snapshot IDs follow insertion order, so ordering by ID also orders runs.
    rows = conn.execute(
        """
        SELECT id
        FROM snapshot
        WHERE status != 'running'
        ORDER BY id
        """
    ).fetchall()

    return [row[0] for row in rows]


def get_latest_snapshot_ids(conn):
    """Return the latest two finalised snapshot IDs."""

    ids = get_finalised_snapshot_ids(conn)

    if not ids:
        return None, None

    if len(ids) == 1:
        return None, ids[-1]

    return ids[-2], ids[-1]


def get_previous_snapshot_id(conn, current_snapshot_id):
    """Return the latest finalised snapshot before the current snapshot."""

    ids = [
        snapshot_id
        for snapshot_id in get_finalised_snapshot_ids(conn)
        if snapshot_id < current_snapshot_id
    ]

    return ids[-1] if ids else None


def require_selectable_snapshot(conn, snapshot_id):
    """Validate that a snapshot exists and is finalised."""

    row = conn.execute(
        """
        SELECT status
        FROM snapshot
        WHERE id = ?
        """,
        (snapshot_id,),
    ).fetchone()

    if row is None:
        raise ValueError(f"Snapshot {snapshot_id} does not exist")

    if row[0] == "running":
        raise ValueError(f"Snapshot {snapshot_id} is still running")

    return snapshot_id
