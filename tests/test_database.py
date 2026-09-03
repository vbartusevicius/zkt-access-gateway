"""Database layer: dedup, migration, name enrichment and filtered queries."""


def _ev(ts, door=1, card="100", pin="1", etype=0, **kw):
    return {"timestamp": ts, "door_id": door, "card_id": card, "pin": pin,
            "event_type": etype, "entry_exit": kw.get("entry_exit", ""),
            "verify_mode": kw.get("verify_mode", "")}


class TestDedup:
    def test_insert_or_ignore_dedupes(self, fresh_db):
        fresh_db.save_events([_ev("2026-09-03T10:00:00"), _ev("2026-09-03T10:00:00")])
        assert len(fresh_db.get_latest_events(10)) == 1

    def test_different_events_kept(self, fresh_db):
        fresh_db.save_events([_ev("2026-09-03T10:00:00"), _ev("2026-09-03T10:01:00")])
        assert len(fresh_db.get_latest_events(10)) == 2

    def test_same_timestamp_different_card_allowed(self, fresh_db):
        fresh_db.save_events([_ev("2026-09-03T10:00:00"), _ev("2026-09-03T10:00:00", card="200")])
        assert len(fresh_db.get_latest_events(10)) == 2


class TestLegacyMigration:
    def test_duplicates_removed_and_unique_index_recreated(self, fresh_db):
        with fresh_db.get_db() as conn:
            conn.execute("DROP INDEX IF EXISTS idx_events_dedup")
            conn.executemany(
                "INSERT INTO events (timestamp, door_id, card_id, pin, event_type) VALUES (?,?,?,?,?)",
                [("2026-09-03T10:00:00", 1, "100", "1", 0)] * 3 +
                [("2026-09-03T11:00:00", 2, "200", "2", 200)],
            )
            conn.commit()
        fresh_db.init_db()  # migration path
        rows = fresh_db.get_latest_events(10)
        assert len(rows) == 2

    def test_entry_exit_columns_added(self, fresh_db):
        with fresh_db.get_db() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(events)")]
        assert {"entry_exit", "verify_mode"} <= set(cols)


class TestFilteredQueries:
    def test_filters(self, fresh_db):
        fresh_db.save_events([
            _ev("2026-09-03T10:00:00", door=1, card="100", etype=0),
            _ev("2026-09-03T11:00:00", door=2, card="999", pin="", etype=27),
            _ev("2026-09-03T12:00:00", door=2, card="555", pin="", etype=200),
        ])
        assert len(fresh_db.get_events_filtered({"door_id": 2, "limit": 10})) == 2
        assert len(fresh_db.get_events_filtered({"event_type": 27, "limit": 10})) == 1
        assert len(fresh_db.get_events_filtered({"q": "99", "limit": 10})) == 1
        assert len(fresh_db.get_events_filtered(
            {"dt_from": "2026-09-03T10:30:00", "dt_to": "2026-09-03T12:00:00", "limit": 10})) == 2

    def test_limit_capped(self, fresh_db):
        fresh_db.save_events([_ev(f"2026-09-03T10:{i:02d}:00") for i in range(5)])
        assert len(fresh_db.get_events_filtered({"limit": 99999})) == 5

    def test_latest_per_door(self, fresh_db):
        fresh_db.save_events([
            _ev("2026-09-03T10:00:00", door=1), _ev("2026-09-03T10:05:00", door=1),
            _ev("2026-09-03T10:02:00", door=2),
        ])
        per_door = fresh_db.get_latest_event_per_door()
        assert len(per_door) == 2
        assert max(e["timestamp"] for e in per_door if e["door_id"] == 1) == "2026-09-03T10:05:00"


class TestUserNames:
    def test_names_resolved_by_pin_and_card(self, fresh_db):
        fresh_db.save_user_name("5", "Jane Doe")
        fresh_db.save_users([{"pin": "5", "card": "16268812", "group": "1"}])
        fresh_db.save_events([
            _ev("2026-09-03T10:00:00", card="16268812", pin="5"),   # both match
            _ev("2026-09-03T11:00:00", card="16268812", pin=""),    # card match only
        ])
        rows = fresh_db.get_events_filtered({"limit": 10})
        assert {r["user_name"] for r in rows} == {"Jane Doe"}

    def test_unregistered_card_has_empty_name(self, fresh_db):
        fresh_db.save_events([_ev("2026-09-03T10:00:00", card="999", pin="", etype=27)])
        assert fresh_db.get_events_filtered({"limit": 10})[0]["user_name"] == ""

    def test_empty_name_clears_row(self, fresh_db):
        fresh_db.save_user_name("5", "Jane Doe")
        fresh_db.save_user_name("5", "")
        with fresh_db.get_db() as conn:
            assert conn.execute("SELECT COUNT(*) FROM user_names").fetchone()[0] == 0
