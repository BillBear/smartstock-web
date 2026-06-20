#!/usr/bin/env python3
"""将 coach SQLite 数据迁移到 PostgreSQL。"""
import argparse
import os
import sqlite3

SQLITE_PATH = os.getenv("SQLITE_PATH", "/Users/xiong/Documents/SmartStock/smartstock-web/backend/data/coach.db")
PG_DSN = os.getenv("PG_DSN", "postgresql://smartstock@127.0.0.1:5432/smartstock")


def fetch_all(conn, table):
    cur = conn.execute(f"SELECT * FROM {table}")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return rows


def _connect_postgres(pg_dsn):
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError("psycopg2 is required to run the SQLite to PostgreSQL migration") from exc
    return psycopg2.connect(pg_dsn)


def migrate(sqlite_path=SQLITE_PATH, pg_dsn=PG_DSN):
    if not os.path.exists(sqlite_path):
        print(f"[skip] sqlite not found: {sqlite_path}")
        return

    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    dst = _connect_postgres(pg_dsn)
    dst.autocommit = False

    try:
        s_cur = src.cursor()
        d_cur = dst.cursor()

        # risk_profiles
        rows = fetch_all(src, "risk_profiles")
        for r in rows:
            d_cur.execute(
                """
                INSERT INTO risk_profiles (user_id, risk_level, horizon_days_min, horizon_days_max, max_position_pct, max_industry_pct, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(user_id) DO UPDATE SET
                  risk_level=EXCLUDED.risk_level,
                  horizon_days_min=EXCLUDED.horizon_days_min,
                  horizon_days_max=EXCLUDED.horizon_days_max,
                  max_position_pct=EXCLUDED.max_position_pct,
                  max_industry_pct=EXCLUDED.max_industry_pct,
                  updated_at=EXCLUDED.updated_at
                """,
                (
                    r.get("user_id"), r.get("risk_level"), r.get("horizon_days_min"), r.get("horizon_days_max"),
                    r.get("max_position_pct"), r.get("max_industry_pct"), r.get("updated_at"),
                ),
            )
        print(f"risk_profiles: {len(rows)}")

        # pick_actions
        rows = fetch_all(src, "pick_actions")
        for r in rows:
            d_cur.execute(
                """
                INSERT INTO pick_actions (id, user_id, pick_id, symbol, action_type, action_price, action_qty, note, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(id) DO NOTHING
                """,
                (
                    r.get("id"), r.get("user_id"), r.get("pick_id"), r.get("symbol"), r.get("action_type"),
                    r.get("action_price"), r.get("action_qty"), r.get("note"), r.get("created_at"),
                ),
            )
        print(f"pick_actions: {len(rows)}")

        # paper_positions
        rows = fetch_all(src, "paper_positions")
        for r in rows:
            d_cur.execute(
                """
                INSERT INTO paper_positions (
                    id, user_id, symbol, name, qty, avg_price, cost_amount, market_value,
                    unrealized_pnl, unrealized_pnl_pct, status, opened_at, updated_at, closed_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(id) DO NOTHING
                """,
                (
                    r.get("id"), r.get("user_id"), r.get("symbol"), r.get("name"), r.get("qty"), r.get("avg_price"),
                    r.get("cost_amount"), r.get("market_value"), r.get("unrealized_pnl"), r.get("unrealized_pnl_pct"),
                    r.get("status"), r.get("opened_at"), r.get("updated_at"), r.get("closed_at"),
                ),
            )
        print(f"paper_positions: {len(rows)}")

        # paper_trades
        rows = fetch_all(src, "paper_trades")
        for r in rows:
            d_cur.execute(
                """
                INSERT INTO paper_trades (
                    id, user_id, symbol, name, pick_id, side, price, qty, amount, fee, reason, created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(id) DO NOTHING
                """,
                (
                    r.get("id"), r.get("user_id"), r.get("symbol"), r.get("name"), r.get("pick_id"), r.get("side"),
                    r.get("price"), r.get("qty"), r.get("amount"), r.get("fee"), r.get("reason"), r.get("created_at"),
                ),
            )
        print(f"paper_trades: {len(rows)}")

        # backtest_runs
        rows = fetch_all(src, "backtest_runs")
        for r in rows:
            d_cur.execute(
                """
                INSERT INTO backtest_runs (run_id, user_id, strategy_code, config_json, result_json, status, started_at, finished_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(run_id) DO UPDATE SET
                  user_id=EXCLUDED.user_id,
                  strategy_code=EXCLUDED.strategy_code,
                  config_json=EXCLUDED.config_json,
                  result_json=EXCLUDED.result_json,
                  status=EXCLUDED.status,
                  started_at=EXCLUDED.started_at,
                  finished_at=EXCLUDED.finished_at
                """,
                (
                    r.get("run_id"), r.get("user_id"), r.get("strategy_code"), r.get("config_json"),
                    r.get("result_json"), r.get("status"), r.get("started_at"), r.get("finished_at"),
                ),
            )
        print(f"backtest_runs: {len(rows)}")

        rows = fetch_all(src, "pick_snapshots")
        for r in rows:
            d_cur.execute(
                """
                INSERT INTO pick_snapshots (
                    pick_id, user_id, trade_date, symbol, name, strategy_code, risk_level, snapshot_json, created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(pick_id) DO UPDATE SET
                  user_id=EXCLUDED.user_id,
                  trade_date=EXCLUDED.trade_date,
                  symbol=EXCLUDED.symbol,
                  name=EXCLUDED.name,
                  strategy_code=EXCLUDED.strategy_code,
                  risk_level=EXCLUDED.risk_level,
                  snapshot_json=EXCLUDED.snapshot_json,
                  created_at=EXCLUDED.created_at
                """,
                (
                    r.get("pick_id"), r.get("user_id"), r.get("trade_date"), r.get("symbol"), r.get("name"),
                    r.get("strategy_code"), r.get("risk_level"), r.get("snapshot_json"), r.get("created_at"),
                ),
            )
        print(f"pick_snapshots: {len(rows)}")

        # 修正序列
        d_cur.execute("SELECT setval(pg_get_serial_sequence('pick_actions','id'), COALESCE((SELECT MAX(id) FROM pick_actions),1), true)")
        d_cur.execute("SELECT setval(pg_get_serial_sequence('paper_positions','id'), COALESCE((SELECT MAX(id) FROM paper_positions),1), true)")
        d_cur.execute("SELECT setval(pg_get_serial_sequence('paper_trades','id'), COALESCE((SELECT MAX(id) FROM paper_trades),1), true)")

        dst.commit()
        print("migration done")
    except Exception:
        dst.rollback()
        raise
    finally:
        src.close()
        dst.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Migrate SmartStock coach data from SQLite to PostgreSQL.")
    parser.add_argument("--sqlite-path", default=SQLITE_PATH)
    parser.add_argument("--pg-dsn", default=PG_DSN)
    return parser.parse_args()


def main():
    args = parse_args()
    migrate(sqlite_path=args.sqlite_path, pg_dsn=args.pg_dsn)


if __name__ == "__main__":
    main()
