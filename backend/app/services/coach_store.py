"""
投资教练持久化存储（支持 PostgreSQL / SQLite）
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine


class CoachStore:
    """轻量化持久化存储层（推荐 PostgreSQL）"""

    def __init__(self, db_url: str):
        db_url = (db_url or "").strip()
        if not db_url:
            raise ValueError("db_url 不能为空")

        if "://" not in db_url:
            # 兼容历史路径传参（sqlite 文件路径）
            db_path = Path(db_url).expanduser().resolve()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            db_url = f"sqlite:///{db_path}"

        if db_url.startswith("sqlite:///"):
            raw = db_url.replace("sqlite:///", "", 1)
            path = Path(raw).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            self.db_url = f"sqlite:///{path}"
        else:
            self.db_url = db_url

        self.engine: Engine = create_engine(self.db_url, pool_pre_ping=True, future=True)
        self._dialect = self.engine.dialect.name
        self._is_postgres = self._dialect.startswith("postgresql")
        self._lock = RLock()
        self._init_schema()
        self._init_market_snapshot_schema()

    @staticmethod
    def _row_to_dict(row) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        return dict(row._mapping)

    @staticmethod
    def _normalize_trade_date(value: Any) -> Optional[str]:
        text_value = str(value or "").strip()
        if not text_value:
            return None
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            candidate = text_value[:10] if fmt == "%Y-%m-%d" else text_value[:8]
            try:
                return datetime.strptime(candidate, fmt).strftime("%Y-%m-%d")
            except Exception:
                continue
        return text_value

    def _init_schema(self) -> None:
        if self._is_postgres:
            sql = """
            CREATE TABLE IF NOT EXISTS risk_profiles (
                user_id TEXT PRIMARY KEY,
                risk_level TEXT NOT NULL,
                horizon_days_min INTEGER NOT NULL,
                horizon_days_max INTEGER NOT NULL,
                max_position_pct DOUBLE PRECISION NOT NULL,
                max_industry_pct DOUBLE PRECISION NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pick_actions (
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                pick_id TEXT NOT NULL,
                symbol TEXT,
                action_type TEXT NOT NULL,
                action_price DOUBLE PRECISION,
                action_qty DOUBLE PRECISION,
                note TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pick_actions_user_pick ON pick_actions(user_id, pick_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_pick_actions_user_symbol ON pick_actions(user_id, symbol, id DESC);
            CREATE INDEX IF NOT EXISTS idx_pick_actions_user_type ON pick_actions(user_id, action_type, id DESC);

            CREATE TABLE IF NOT EXISTS paper_positions (
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT,
                pick_id TEXT,
                qty DOUBLE PRECISION NOT NULL,
                avg_price DOUBLE PRECISION NOT NULL,
                cost_amount DOUBLE PRECISION NOT NULL,
                market_value DOUBLE PRECISION,
                unrealized_pnl DOUBLE PRECISION,
                unrealized_pnl_pct DOUBLE PRECISION,
                status TEXT NOT NULL DEFAULT 'open',
                opened_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                closed_at TEXT,
                UNIQUE(user_id, symbol, status)
            );
            CREATE INDEX IF NOT EXISTS idx_positions_user_status ON paper_positions(user_id, status, updated_at DESC);

            CREATE TABLE IF NOT EXISTS paper_trades (
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT,
                pick_id TEXT,
                side TEXT NOT NULL,
                price DOUBLE PRECISION NOT NULL,
                qty DOUBLE PRECISION NOT NULL,
                amount DOUBLE PRECISION NOT NULL,
                fee DOUBLE PRECISION NOT NULL DEFAULT 0,
                reason TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_trades_user_time ON paper_trades(user_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_trades_user_symbol ON paper_trades(user_id, symbol, id DESC);

            CREATE TABLE IF NOT EXISTS paper_trade_evaluations (
                eval_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT,
                pick_id TEXT,
                status TEXT NOT NULL,
                entry_date TEXT,
                exit_date TEXT,
                metrics_json TEXT NOT NULL,
                attribution_json TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                calibration_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_paper_trade_evaluations_user_status
                ON paper_trade_evaluations(user_id, status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_paper_trade_evaluations_symbol
                ON paper_trade_evaluations(user_id, symbol, updated_at DESC);

            CREATE TABLE IF NOT EXISTS backtest_runs (
                run_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                strategy_code TEXT NOT NULL,
                config_json TEXT,
                result_json TEXT,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT
            );

            CREATE TABLE IF NOT EXISTS strategy_profiles (
                user_id TEXT NOT NULL,
                strategy_code TEXT NOT NULL,
                profile_key TEXT,
                config_json TEXT NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT FALSE,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(user_id, strategy_code)
            );
            CREATE INDEX IF NOT EXISTS idx_strategy_profiles_active
                ON strategy_profiles(user_id, is_active, updated_at DESC);

            CREATE TABLE IF NOT EXISTS pick_snapshots (
                pick_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT,
                strategy_code TEXT,
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pick_snapshots_user_time
                ON pick_snapshots(user_id, trade_date DESC);
            CREATE INDEX IF NOT EXISTS idx_pick_snapshots_symbol_time
                ON pick_snapshots(symbol, trade_date DESC);

            CREATE TABLE IF NOT EXISTS news_events (
                id BIGSERIAL PRIMARY KEY,
                source TEXT NOT NULL,
                source_type TEXT NOT NULL,
                event_level TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT,
                url TEXT NOT NULL,
                publish_time TEXT NOT NULL,
                symbol TEXT,
                symbol_name TEXT,
                industry_tags_json TEXT,
                direction TEXT NOT NULL,
                impact_score DOUBLE PRECISION NOT NULL,
                confidence_score DOUBLE PRECISION NOT NULL,
                event_score DOUBLE PRECISION NOT NULL,
                content_hash TEXT NOT NULL UNIQUE,
                meta_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_news_events_publish ON news_events(publish_time DESC);
            CREATE INDEX IF NOT EXISTS idx_news_events_symbol_time ON news_events(symbol, publish_time DESC);
            CREATE INDEX IF NOT EXISTS idx_news_events_level_time ON news_events(event_level, publish_time DESC);

            CREATE TABLE IF NOT EXISTS ml_model_versions (
                model_id TEXT PRIMARY KEY,
                model_code TEXT NOT NULL,
                strategy_code TEXT NOT NULL,
                status TEXT NOT NULL,
                artifact_path TEXT NOT NULL,
                feature_names_json TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                train_config_json TEXT NOT NULL,
                train_start TEXT,
                train_end TEXT,
                sample_count INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ml_model_versions_created
                ON ml_model_versions(created_at DESC);

            CREATE TABLE IF NOT EXISTS ml_training_samples (
                id BIGSERIAL PRIMARY KEY,
                model_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                feature_json TEXT NOT NULL,
                label_json TEXT NOT NULL,
                meta_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ml_training_samples_model
                ON ml_training_samples(model_id, trade_date DESC);

            CREATE TABLE IF NOT EXISTS ml_model_metrics (
                id BIGSERIAL PRIMARY KEY,
                model_id TEXT NOT NULL,
                metric_key TEXT NOT NULL,
                metric_value DOUBLE PRECISION,
                metric_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ml_model_metrics_model
                ON ml_model_metrics(model_id, metric_key);

            CREATE TABLE IF NOT EXISTS ml_factor_importance (
                id BIGSERIAL PRIMARY KEY,
                model_id TEXT NOT NULL,
                feature TEXT NOT NULL,
                label TEXT,
                category TEXT,
                up_coef DOUBLE PRECISION,
                dd_coef DOUBLE PRECISION,
                importance DOUBLE PRECISION NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ml_factor_importance_model
                ON ml_factor_importance(model_id, importance DESC);

            CREATE TABLE IF NOT EXISTS ml_daily_predictions (
                id BIGSERIAL PRIMARY KEY,
                model_id TEXT NOT NULL,
                symbol TEXT,
                trade_date TEXT NOT NULL,
                prediction_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ml_daily_predictions_model_symbol
                ON ml_daily_predictions(model_id, symbol, trade_date DESC);

            CREATE TABLE IF NOT EXISTS monitor_snapshots (
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT,
                track_type TEXT NOT NULL,
                pick_id TEXT,
                snapshot_date TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                conclusion_json TEXT NOT NULL,
                data_quality_json TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, symbol, track_type, snapshot_date)
            );
            CREATE INDEX IF NOT EXISTS idx_monitor_snapshots_user_date
                ON monitor_snapshots(user_id, snapshot_date DESC);
            CREATE INDEX IF NOT EXISTS idx_monitor_snapshots_symbol
                ON monitor_snapshots(user_id, symbol, snapshot_date DESC);

            CREATE TABLE IF NOT EXISTS strategy_feedback_reports (
                report_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                report_date TEXT NOT NULL,
                report_type TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                suggestions_json TEXT NOT NULL,
                diagnostics_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_strategy_feedback_reports_user_date
                ON strategy_feedback_reports(user_id, report_date DESC);
            """
        else:
            sql = """
            CREATE TABLE IF NOT EXISTS risk_profiles (
                user_id TEXT PRIMARY KEY,
                risk_level TEXT NOT NULL,
                horizon_days_min INTEGER NOT NULL,
                horizon_days_max INTEGER NOT NULL,
                max_position_pct REAL NOT NULL,
                max_industry_pct REAL NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pick_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                pick_id TEXT NOT NULL,
                symbol TEXT,
                action_type TEXT NOT NULL,
                action_price REAL,
                action_qty REAL,
                note TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pick_actions_user_pick ON pick_actions(user_id, pick_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_pick_actions_user_symbol ON pick_actions(user_id, symbol, id DESC);
            CREATE INDEX IF NOT EXISTS idx_pick_actions_user_type ON pick_actions(user_id, action_type, id DESC);

            CREATE TABLE IF NOT EXISTS paper_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT,
                pick_id TEXT,
                qty REAL NOT NULL,
                avg_price REAL NOT NULL,
                cost_amount REAL NOT NULL,
                market_value REAL,
                unrealized_pnl REAL,
                unrealized_pnl_pct REAL,
                status TEXT NOT NULL DEFAULT 'open',
                opened_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                closed_at TEXT,
                UNIQUE(user_id, symbol, status)
            );
            CREATE INDEX IF NOT EXISTS idx_positions_user_status ON paper_positions(user_id, status, updated_at DESC);

            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT,
                pick_id TEXT,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                qty REAL NOT NULL,
                amount REAL NOT NULL,
                fee REAL NOT NULL DEFAULT 0,
                reason TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_trades_user_time ON paper_trades(user_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_trades_user_symbol ON paper_trades(user_id, symbol, id DESC);

            CREATE TABLE IF NOT EXISTS paper_trade_evaluations (
                eval_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT,
                pick_id TEXT,
                status TEXT NOT NULL,
                entry_date TEXT,
                exit_date TEXT,
                metrics_json TEXT NOT NULL,
                attribution_json TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                calibration_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_paper_trade_evaluations_user_status
                ON paper_trade_evaluations(user_id, status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_paper_trade_evaluations_symbol
                ON paper_trade_evaluations(user_id, symbol, updated_at DESC);

            CREATE TABLE IF NOT EXISTS backtest_runs (
                run_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                strategy_code TEXT NOT NULL,
                config_json TEXT,
                result_json TEXT,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT
            );

            CREATE TABLE IF NOT EXISTS strategy_profiles (
                user_id TEXT NOT NULL,
                strategy_code TEXT NOT NULL,
                profile_key TEXT,
                config_json TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(user_id, strategy_code)
            );
            CREATE INDEX IF NOT EXISTS idx_strategy_profiles_active
                ON strategy_profiles(user_id, is_active, updated_at DESC);

            CREATE TABLE IF NOT EXISTS pick_snapshots (
                pick_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT,
                strategy_code TEXT,
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pick_snapshots_user_time
                ON pick_snapshots(user_id, trade_date DESC);
            CREATE INDEX IF NOT EXISTS idx_pick_snapshots_symbol_time
                ON pick_snapshots(symbol, trade_date DESC);

            CREATE TABLE IF NOT EXISTS news_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                source_type TEXT NOT NULL,
                event_level TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT,
                url TEXT NOT NULL,
                publish_time TEXT NOT NULL,
                symbol TEXT,
                symbol_name TEXT,
                industry_tags_json TEXT,
                direction TEXT NOT NULL,
                impact_score REAL NOT NULL,
                confidence_score REAL NOT NULL,
                event_score REAL NOT NULL,
                content_hash TEXT NOT NULL UNIQUE,
                meta_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_news_events_publish ON news_events(publish_time DESC);
            CREATE INDEX IF NOT EXISTS idx_news_events_symbol_time ON news_events(symbol, publish_time DESC);
            CREATE INDEX IF NOT EXISTS idx_news_events_level_time ON news_events(event_level, publish_time DESC);

            CREATE TABLE IF NOT EXISTS ml_model_versions (
                model_id TEXT PRIMARY KEY,
                model_code TEXT NOT NULL,
                strategy_code TEXT NOT NULL,
                status TEXT NOT NULL,
                artifact_path TEXT NOT NULL,
                feature_names_json TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                train_config_json TEXT NOT NULL,
                train_start TEXT,
                train_end TEXT,
                sample_count INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ml_model_versions_created
                ON ml_model_versions(created_at DESC);

            CREATE TABLE IF NOT EXISTS ml_training_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                feature_json TEXT NOT NULL,
                label_json TEXT NOT NULL,
                meta_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ml_training_samples_model
                ON ml_training_samples(model_id, trade_date DESC);

            CREATE TABLE IF NOT EXISTS ml_model_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_id TEXT NOT NULL,
                metric_key TEXT NOT NULL,
                metric_value REAL,
                metric_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ml_model_metrics_model
                ON ml_model_metrics(model_id, metric_key);

            CREATE TABLE IF NOT EXISTS ml_factor_importance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_id TEXT NOT NULL,
                feature TEXT NOT NULL,
                label TEXT,
                category TEXT,
                up_coef REAL,
                dd_coef REAL,
                importance REAL NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ml_factor_importance_model
                ON ml_factor_importance(model_id, importance DESC);

            CREATE TABLE IF NOT EXISTS ml_daily_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_id TEXT NOT NULL,
                symbol TEXT,
                trade_date TEXT NOT NULL,
                prediction_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ml_daily_predictions_model_symbol
                ON ml_daily_predictions(model_id, symbol, trade_date DESC);

            CREATE TABLE IF NOT EXISTS monitor_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT,
                track_type TEXT NOT NULL,
                pick_id TEXT,
                snapshot_date TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                conclusion_json TEXT NOT NULL,
                data_quality_json TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, symbol, track_type, snapshot_date)
            );
            CREATE INDEX IF NOT EXISTS idx_monitor_snapshots_user_date
                ON monitor_snapshots(user_id, snapshot_date DESC);
            CREATE INDEX IF NOT EXISTS idx_monitor_snapshots_symbol
                ON monitor_snapshots(user_id, symbol, snapshot_date DESC);

            CREATE TABLE IF NOT EXISTS strategy_feedback_reports (
                report_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                report_date TEXT NOT NULL,
                report_type TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                suggestions_json TEXT NOT NULL,
                diagnostics_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_strategy_feedback_reports_user_date
                ON strategy_feedback_reports(user_id, report_date DESC);
            """

        statements = [part.strip() for part in sql.split(";") if part.strip()]
        with self._lock:
            with self.engine.begin() as conn:
                for stmt in statements:
                    conn.execute(text(stmt))
                self._run_schema_migrations(conn)

    def _run_schema_migrations(self, conn) -> None:
        """Keep existing local databases compatible with incremental coach schema changes."""
        def has_column(table_name: str, column_name: str) -> bool:
            if self._is_postgres:
                row = conn.execute(
                    text(
                        """
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = :table_name AND column_name = :column_name
                        LIMIT 1
                        """
                    ),
                    {"table_name": table_name, "column_name": column_name},
                ).first()
                return bool(row)
            rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            return any(str(row._mapping.get("name")) == column_name for row in rows)

        if not has_column("paper_positions", "pick_id"):
            conn.execute(text("ALTER TABLE paper_positions ADD COLUMN pick_id TEXT"))

    def _init_market_snapshot_schema(self) -> None:
        """Create persistent market-data snapshot tables used by the recommendation pipeline."""
        id_type = "BIGSERIAL PRIMARY KEY" if self._is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
        sql = f"""
        CREATE TABLE IF NOT EXISTS market_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            trade_date TEXT NOT NULL,
            source TEXT,
            snapshot_count INTEGER NOT NULL DEFAULT 0,
            quality_status TEXT NOT NULL DEFAULT 'unknown',
            meta_json TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_market_snapshots_date
            ON market_snapshots(trade_date DESC, created_at DESC);

        CREATE TABLE IF NOT EXISTS market_snapshot_items (
            id {id_type},
            snapshot_id TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT,
            industry TEXT,
            item_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(snapshot_id, symbol)
        );
        CREATE INDEX IF NOT EXISTS idx_market_snapshot_items_snapshot
            ON market_snapshot_items(snapshot_id);
        CREATE INDEX IF NOT EXISTS idx_market_snapshot_items_symbol
            ON market_snapshot_items(symbol, trade_date DESC);

        CREATE TABLE IF NOT EXISTS money_flow_snapshots (
            id {id_type},
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            quality TEXT NOT NULL,
            source TEXT,
            available BOOLEAN NOT NULL DEFAULT FALSE,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(trade_date, symbol)
        );
        CREATE INDEX IF NOT EXISTS idx_money_flow_snapshots_quality
            ON money_flow_snapshots(trade_date DESC, quality);

        CREATE TABLE IF NOT EXISTS theme_snapshots (
            id {id_type},
            trade_date TEXT NOT NULL,
            theme_id TEXT NOT NULL,
            theme_name TEXT NOT NULL,
            category TEXT,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(trade_date, theme_id)
        );
        CREATE INDEX IF NOT EXISTS idx_theme_snapshots_date
            ON theme_snapshots(trade_date DESC);

        CREATE TABLE IF NOT EXISTS data_quality_snapshots (
            id {id_type},
            trade_date TEXT NOT NULL,
            scope TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(trade_date, scope)
        );
        CREATE INDEX IF NOT EXISTS idx_data_quality_snapshots_date
            ON data_quality_snapshots(trade_date DESC, scope);
        """
        statements = [part.strip() for part in sql.split(";") if part.strip()]
        with self._lock:
            with self.engine.begin() as conn:
                for stmt in statements:
                    conn.execute(text(stmt))

    def get_risk_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT user_id, risk_level, horizon_days_min, horizon_days_max,
                               max_position_pct, max_industry_pct, updated_at
                        FROM risk_profiles
                        WHERE user_id = :user_id
                        """
                    ),
                    {"user_id": user_id},
                ).first()
                return self._row_to_dict(row)

    def upsert_risk_profile(self, user_id: str, profile: Dict[str, Any], updated_at: str) -> Dict[str, Any]:
        payload = {
            "user_id": user_id,
            "risk_level": profile.get("risk_level", "medium"),
            "horizon_days_min": int(profile.get("horizon_days_min", 5)),
            "horizon_days_max": int(profile.get("horizon_days_max", 20)),
            "max_position_pct": float(profile.get("max_position_pct", 10)),
            "max_industry_pct": float(profile.get("max_industry_pct", 30)),
            "updated_at": updated_at,
        }
        with self._lock:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO risk_profiles (
                            user_id, risk_level, horizon_days_min, horizon_days_max,
                            max_position_pct, max_industry_pct, updated_at
                        ) VALUES (
                            :user_id, :risk_level, :horizon_days_min, :horizon_days_max,
                            :max_position_pct, :max_industry_pct, :updated_at
                        )
                        ON CONFLICT(user_id) DO UPDATE SET
                            risk_level=excluded.risk_level,
                            horizon_days_min=excluded.horizon_days_min,
                            horizon_days_max=excluded.horizon_days_max,
                            max_position_pct=excluded.max_position_pct,
                            max_industry_pct=excluded.max_industry_pct,
                            updated_at=excluded.updated_at
                        """
                    ),
                    payload,
                )
        return payload

    def upsert_strategy_profile(
        self,
        user_id: str,
        strategy_code: str,
        profile_key: Optional[str],
        config: Dict[str, Any],
        updated_at: str,
        is_active: bool = True,
    ) -> Dict[str, Any]:
        params = {
            "user_id": user_id,
            "strategy_code": str(strategy_code or "trend_breakout"),
            "profile_key": profile_key,
            "config_json": json.dumps(config or {}, ensure_ascii=False),
            "is_active": bool(is_active),
            "updated_at": updated_at,
        }
        with self._lock:
            with self.engine.begin() as conn:
                if params["is_active"]:
                    conn.execute(
                        text(
                            """
                            UPDATE strategy_profiles
                            SET is_active = :inactive
                            WHERE user_id = :user_id AND strategy_code <> :strategy_code
                            """
                        ),
                        {
                            "inactive": False if self._is_postgres else 0,
                            "user_id": params["user_id"],
                            "strategy_code": params["strategy_code"],
                        },
                    )

                conn.execute(
                    text(
                        """
                        INSERT INTO strategy_profiles (
                            user_id, strategy_code, profile_key, config_json, is_active, updated_at
                        ) VALUES (
                            :user_id, :strategy_code, :profile_key, :config_json, :is_active, :updated_at
                        )
                        ON CONFLICT(user_id, strategy_code) DO UPDATE SET
                            profile_key=excluded.profile_key,
                            config_json=excluded.config_json,
                            is_active=excluded.is_active,
                            updated_at=excluded.updated_at
                        """
                    ),
                    {
                        "user_id": params["user_id"],
                        "strategy_code": params["strategy_code"],
                        "profile_key": params["profile_key"],
                        "config_json": params["config_json"],
                        "is_active": params["is_active"] if self._is_postgres else (1 if params["is_active"] else 0),
                        "updated_at": params["updated_at"],
                    },
                )
        return {
            "user_id": params["user_id"],
            "strategy_code": params["strategy_code"],
            "profile_key": params["profile_key"],
            "config": config or {},
            "is_active": params["is_active"],
            "updated_at": params["updated_at"],
        }

    def get_strategy_profile(self, user_id: str, strategy_code: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT *
                        FROM strategy_profiles
                        WHERE user_id = :user_id AND strategy_code = :strategy_code
                        """
                    ),
                    {
                        "user_id": user_id,
                        "strategy_code": str(strategy_code or "trend_breakout"),
                    },
                ).first()
                if not row:
                    return None
                data = dict(row._mapping)
                cfg = data.get("config_json")
                try:
                    data["config"] = json.loads(cfg) if cfg else {}
                except Exception:
                    data["config"] = {}
                data["is_active"] = bool(data.get("is_active"))
                return data

    def get_active_strategy_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT *
                        FROM strategy_profiles
                        WHERE user_id = :user_id AND is_active = :active
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """
                    ),
                    {
                        "user_id": user_id,
                        "active": True if self._is_postgres else 1,
                    },
                ).first()
                if not row:
                    return None
                data = dict(row._mapping)
                cfg = data.get("config_json")
                try:
                    data["config"] = json.loads(cfg) if cfg else {}
                except Exception:
                    data["config"] = {}
                data["is_active"] = bool(data.get("is_active"))
                return data

    def append_pick_action(self, record: Dict[str, Any]) -> Dict[str, Any]:
        params = {
            "user_id": record.get("user_id"),
            "pick_id": record.get("pick_id"),
            "symbol": record.get("symbol"),
            "action_type": record.get("action_type"),
            "action_price": record.get("action_price"),
            "action_qty": record.get("action_qty"),
            "note": record.get("note"),
            "created_at": record.get("created_at"),
        }
        with self._lock:
            with self.engine.begin() as conn:
                if self._is_postgres:
                    row = conn.execute(
                        text(
                            """
                            INSERT INTO pick_actions (
                                user_id, pick_id, symbol, action_type, action_price, action_qty, note, created_at
                            ) VALUES (
                                :user_id, :pick_id, :symbol, :action_type, :action_price, :action_qty, :note, :created_at
                            )
                            RETURNING *
                            """
                        ),
                        params,
                    ).first()
                    return self._row_to_dict(row) or record

                conn.execute(
                    text(
                        """
                        INSERT INTO pick_actions (
                            user_id, pick_id, symbol, action_type, action_price, action_qty, note, created_at
                        ) VALUES (
                            :user_id, :pick_id, :symbol, :action_type, :action_price, :action_qty, :note, :created_at
                        )
                        """
                    ),
                    params,
                )
                row_id = conn.execute(text("SELECT last_insert_rowid() AS id")).scalar_one()
                row = conn.execute(text("SELECT * FROM pick_actions WHERE id = :id"), {"id": row_id}).first()
                return self._row_to_dict(row) or record

    def get_latest_pick_actions(self, user_id: str) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT pa.*
                        FROM pick_actions pa
                        INNER JOIN (
                            SELECT pick_id, MAX(id) AS max_id
                            FROM pick_actions
                            WHERE user_id = :user_id
                            GROUP BY pick_id
                        ) last_rec
                        ON pa.id = last_rec.max_id
                        ORDER BY pa.id DESC
                        """
                    ),
                    {"user_id": user_id},
                ).fetchall()
                return {
                    row._mapping["pick_id"]: dict(row._mapping)
                    for row in rows
                }

    def list_pick_actions(self, user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT *
                        FROM pick_actions
                        WHERE user_id = :user_id
                        ORDER BY id DESC
                        LIMIT :limit
                        """
                    ),
                    {"user_id": user_id, "limit": max(1, min(limit, 1000))},
                ).fetchall()
                return [dict(row._mapping) for row in rows]

    def upsert_pick_snapshots(
        self,
        user_id: str,
        trade_date: str,
        strategy_code: str,
        picks: List[Dict[str, Any]],
    ) -> int:
        if not picks:
            return 0
        rows = []
        created_at = picks[0].get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for pick in picks:
            pick_id = str(pick.get("pick_id") or "").strip()
            symbol = str(pick.get("symbol") or "").strip()
            if not pick_id or not symbol:
                continue
            rows.append(
                {
                    "pick_id": pick_id,
                    "user_id": user_id,
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "name": str(pick.get("name") or symbol),
                    "strategy_code": strategy_code,
                    "snapshot_json": json.dumps(pick, ensure_ascii=False),
                    "created_at": str(created_at),
                }
            )
        if not rows:
            return 0

        with self._lock:
            with self.engine.begin() as conn:
                for row in rows:
                    if self._is_postgres:
                        conn.execute(
                            text(
                                """
                                INSERT INTO pick_snapshots (
                                    pick_id, user_id, trade_date, symbol, name, strategy_code, snapshot_json, created_at
                                ) VALUES (
                                    :pick_id, :user_id, :trade_date, :symbol, :name, :strategy_code, :snapshot_json, :created_at
                                )
                                ON CONFLICT (pick_id) DO UPDATE SET
                                    user_id=excluded.user_id,
                                    trade_date=excluded.trade_date,
                                    symbol=excluded.symbol,
                                    name=excluded.name,
                                    strategy_code=excluded.strategy_code,
                                    snapshot_json=excluded.snapshot_json,
                                    created_at=excluded.created_at
                                """
                            ),
                            row,
                        )
                    else:
                        conn.execute(
                            text(
                                """
                                INSERT INTO pick_snapshots (
                                    pick_id, user_id, trade_date, symbol, name, strategy_code, snapshot_json, created_at
                                ) VALUES (
                                    :pick_id, :user_id, :trade_date, :symbol, :name, :strategy_code, :snapshot_json, :created_at
                                )
                                ON CONFLICT(pick_id) DO UPDATE SET
                                    user_id=excluded.user_id,
                                    trade_date=excluded.trade_date,
                                    symbol=excluded.symbol,
                                    name=excluded.name,
                                    strategy_code=excluded.strategy_code,
                                    snapshot_json=excluded.snapshot_json,
                                    created_at=excluded.created_at
                                """
                            ),
                            row,
                        )
        return len(rows)

    def get_pick_snapshot(self, pick_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        clauses = ["pick_id = :pick_id"]
        params: Dict[str, Any] = {"pick_id": str(pick_id)}
        if user_id:
            clauses.append("user_id = :user_id")
            params["user_id"] = str(user_id)
        sql = text(
            f"""
            SELECT *
            FROM pick_snapshots
            WHERE {' AND '.join(clauses)}
            ORDER BY trade_date DESC
            LIMIT 1
            """
        )
        with self._lock:
            with self.engine.connect() as conn:
                row = conn.execute(sql, params).first()
                if not row:
                    return None
                data = dict(row._mapping)
                try:
                    data["snapshot"] = json.loads(data.get("snapshot_json") or "{}")
                except Exception:
                    data["snapshot"] = {}
                return data

    def get_latest_pick_snapshot_by_symbol(self, symbol: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        clauses = ["symbol = :symbol"]
        params: Dict[str, Any] = {"symbol": str(symbol)}
        if user_id:
            clauses.append("user_id = :user_id")
            params["user_id"] = str(user_id)
        sql = text(
            f"""
            SELECT *
            FROM pick_snapshots
            WHERE {' AND '.join(clauses)}
            ORDER BY trade_date DESC, created_at DESC
            LIMIT 1
            """
        )
        with self._lock:
            with self.engine.connect() as conn:
                row = conn.execute(sql, params).first()
                if not row:
                    return None
                data = dict(row._mapping)
                try:
                    data["snapshot"] = json.loads(data.get("snapshot_json") or "{}")
                except Exception:
                    data["snapshot"] = {}
                return data

    def get_latest_pick_snapshots_result(
        self,
        user_id: str = "default",
        trade_date: Optional[str] = None,
        limit: int = 60,
    ) -> Optional[Dict[str, Any]]:
        """Rebuild a lightweight recommendation result from persisted pick snapshots."""
        result_limit = max(1, min(int(limit or 60), 200))
        # Fetch the full latest batch first, then apply rank sorting in Python.
        # Applying SQL LIMIT before parsing rank_no can restore the wrong symbols
        # because relational rows are not stored in recommendation-rank order.
        params: Dict[str, Any] = {"user_id": user_id, "limit": 200}
        date_clause = ""
        if trade_date:
            date_clause = "AND trade_date = :trade_date"
            params["trade_date"] = str(trade_date)

        latest_date_sql = text(
            f"""
            SELECT trade_date
            FROM pick_snapshots
            WHERE user_id = :user_id {date_clause}
            GROUP BY trade_date
            ORDER BY trade_date DESC
            LIMIT 1
            """
        )
        with self._lock:
            with self.engine.connect() as conn:
                row = conn.execute(latest_date_sql, params).first()
                if not row:
                    return None
                latest_trade_date = str(row._mapping["trade_date"])
                batch_row = conn.execute(
                    text(
                        """
                        SELECT created_at
                        FROM pick_snapshots
                        WHERE user_id = :user_id AND trade_date = :trade_date
                        GROUP BY created_at
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ),
                    {**params, "trade_date": latest_trade_date},
                ).first()
                if not batch_row:
                    return None
                latest_created_at = str(batch_row._mapping["created_at"])
                rows = conn.execute(
                    text(
                        """
                        SELECT *
                        FROM pick_snapshots
                        WHERE user_id = :user_id
                            AND trade_date = :trade_date
                            AND created_at = :created_at
                        ORDER BY symbol
                        LIMIT :limit
                        """
                    ),
                    {**params, "trade_date": latest_trade_date, "created_at": latest_created_at},
                ).fetchall()

        picks = []
        strategy_code = None
        updated_at = None
        for row in rows:
            data = dict(row._mapping)
            try:
                pick = json.loads(data.get("snapshot_json") or "{}")
            except Exception:
                pick = {}
            if not pick:
                continue
            strategy_code = strategy_code or data.get("strategy_code")
            updated_at = updated_at or data.get("created_at")
            picks.append(pick)

        if not picks:
            return None
        picks.sort(key=lambda item: int(item.get("rank_no") or 9999))
        picks = picks[:result_limit]
        return {
            "status": "cached_from_store",
            "trade_date": latest_trade_date,
            "updated_at": updated_at,
            "strategy_code": strategy_code,
            "picks": picks,
        }

    def list_pick_snapshot_dates(self, user_id: str = "default", limit: int = 30) -> List[str]:
        """Return recent distinct persisted recommendation dates for a user."""
        with self._lock:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT DISTINCT trade_date
                        FROM pick_snapshots
                        WHERE user_id = :user_id
                          AND trade_date IS NOT NULL
                          AND trade_date != ''
                        """
                    ),
                    {"user_id": str(user_id or "default")},
                ).fetchall()
        dates = {
            normalized
            for row in rows
            for normalized in [self._normalize_trade_date(row._mapping.get("trade_date"))]
            if normalized
        }
        return sorted(dates, reverse=True)[: max(1, min(int(limit or 30), 365))]

    def list_pick_snapshots(
        self,
        user_id: str = "default",
        trade_date: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """Return the latest persisted recommendation batch for a date."""
        result_limit = max(1, min(int(limit or 200), 500))
        params: Dict[str, Any] = {"user_id": user_id}
        date_clause = ""
        if trade_date:
            date_clause = "AND trade_date = :trade_date"
            params["trade_date"] = str(trade_date)

        latest_date_sql = text(
            f"""
            SELECT trade_date
            FROM pick_snapshots
            WHERE user_id = :user_id {date_clause}
            GROUP BY trade_date
            ORDER BY trade_date DESC
            LIMIT 1
            """
        )
        with self._lock:
            with self.engine.connect() as conn:
                row = conn.execute(latest_date_sql, params).first()
                if not row:
                    return []
                latest_trade_date = str(row._mapping["trade_date"])
                batch_row = conn.execute(
                    text(
                        """
                        SELECT created_at
                        FROM pick_snapshots
                        WHERE user_id = :user_id AND trade_date = :trade_date
                        GROUP BY created_at
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"user_id": user_id, "trade_date": latest_trade_date},
                ).first()
                if not batch_row:
                    return []
                latest_created_at = str(batch_row._mapping["created_at"])
                rows = conn.execute(
                    text(
                        """
                        SELECT *
                        FROM pick_snapshots
                        WHERE user_id = :user_id
                            AND trade_date = :trade_date
                            AND created_at = :created_at
                        ORDER BY symbol
                        LIMIT :limit
                        """
                    ),
                    {
                        "user_id": user_id,
                        "trade_date": latest_trade_date,
                        "created_at": latest_created_at,
                        "limit": result_limit,
                    },
                ).fetchall()

        items: List[Dict[str, Any]] = []
        for row in rows:
            data = dict(row._mapping)
            try:
                data["snapshot"] = json.loads(data.get("snapshot_json") or "{}")
            except Exception:
                data["snapshot"] = {}
            items.append(data)
        items.sort(key=lambda item: int((item.get("snapshot") or {}).get("rank_no") or 9999))
        return items

    def upsert_market_snapshot(
        self,
        trade_date: str,
        source: str,
        items: List[Dict[str, Any]],
        quality_status: str,
        meta: Optional[Dict[str, Any]] = None,
        created_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        created_at = created_at or str(trade_date)
        safe_items = [item for item in (items or []) if str(item.get("symbol") or "").strip()]
        snapshot_id = f"{trade_date}:{source or 'unknown'}"
        snapshot_row = {
            "snapshot_id": snapshot_id,
            "trade_date": trade_date,
            "source": source,
            "snapshot_count": len(safe_items),
            "quality_status": quality_status,
            "meta_json": json.dumps(meta or {}, ensure_ascii=False),
            "created_at": created_at,
        }
        with self._lock:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO market_snapshots (
                            snapshot_id, trade_date, source, snapshot_count, quality_status, meta_json, created_at
                        ) VALUES (
                            :snapshot_id, :trade_date, :source, :snapshot_count, :quality_status, :meta_json, :created_at
                        )
                        ON CONFLICT(snapshot_id) DO UPDATE SET
                            source=excluded.source,
                            snapshot_count=excluded.snapshot_count,
                            quality_status=excluded.quality_status,
                            meta_json=excluded.meta_json,
                            created_at=excluded.created_at
                        """
                    ),
                    snapshot_row,
                )
                for item in safe_items:
                    symbol = str(item.get("symbol") or "").strip()
                    conn.execute(
                        text(
                            """
                            INSERT INTO market_snapshot_items (
                                snapshot_id, trade_date, symbol, name, industry, item_json, created_at
                            ) VALUES (
                                :snapshot_id, :trade_date, :symbol, :name, :industry, :item_json, :created_at
                            )
                            ON CONFLICT(snapshot_id, symbol) DO UPDATE SET
                                name=excluded.name,
                                industry=excluded.industry,
                                item_json=excluded.item_json,
                                created_at=excluded.created_at
                            """
                        ),
                        {
                            "snapshot_id": snapshot_id,
                            "trade_date": trade_date,
                            "symbol": symbol,
                            "name": str(item.get("name") or symbol),
                            "industry": str(item.get("industry") or ""),
                            "item_json": json.dumps(item, ensure_ascii=False),
                            "created_at": created_at,
                        },
                    )
        return {**snapshot_row, "items": safe_items}

    def get_latest_valid_market_snapshot(
        self,
        trade_date: Optional[str] = None,
        min_count: int = 500,
    ) -> Optional[Dict[str, Any]]:
        params: Dict[str, Any] = {"min_count": int(min_count or 0)}
        date_clause = ""
        if trade_date:
            date_clause = "AND trade_date <= :trade_date"
            params["trade_date"] = str(trade_date)
        with self._lock:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text(
                        f"""
                        SELECT *
                        FROM market_snapshots
                        WHERE snapshot_count >= :min_count {date_clause}
                        ORDER BY trade_date DESC, created_at DESC
                        LIMIT 1
                        """
                    ),
                    params,
                ).first()
                if not row:
                    return None
                snapshot = dict(row._mapping)
                rows = conn.execute(
                    text(
                        """
                        SELECT item_json
                        FROM market_snapshot_items
                        WHERE snapshot_id = :snapshot_id
                        """
                    ),
                    {"snapshot_id": snapshot["snapshot_id"]},
                ).fetchall()
        items = []
        for row in rows:
            try:
                items.append(json.loads(row._mapping.get("item_json") or "{}"))
            except Exception:
                continue
        try:
            snapshot["meta"] = json.loads(snapshot.get("meta_json") or "{}")
        except Exception:
            snapshot["meta"] = {}
        snapshot["items"] = items
        return snapshot

    def upsert_data_quality_snapshot(
        self,
        trade_date: str,
        scope: str,
        status: str,
        payload: Dict[str, Any],
        created_at: str,
    ) -> None:
        with self._lock:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO data_quality_snapshots (
                            trade_date, scope, status, payload_json, created_at
                        ) VALUES (
                            :trade_date, :scope, :status, :payload_json, :created_at
                        )
                        ON CONFLICT(trade_date, scope) DO UPDATE SET
                            status=excluded.status,
                            payload_json=excluded.payload_json,
                            created_at=excluded.created_at
                        """
                    ),
                    {
                        "trade_date": trade_date,
                        "scope": scope,
                        "status": status,
                        "payload_json": json.dumps(payload or {}, ensure_ascii=False),
                        "created_at": created_at,
                    },
                )

    def upsert_money_flow_snapshot(
        self,
        trade_date: str,
        symbol: str,
        payload: Dict[str, Any],
        created_at: str,
    ) -> None:
        quality = str(payload.get("quality") or ("proxy" if payload.get("estimated") else "real"))
        available = bool(payload.get("available", True)) and quality != "unavailable"
        with self._lock:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO money_flow_snapshots (
                            trade_date, symbol, quality, source, available, payload_json, created_at
                        ) VALUES (
                            :trade_date, :symbol, :quality, :source, :available, :payload_json, :created_at
                        )
                        ON CONFLICT(trade_date, symbol) DO UPDATE SET
                            quality=excluded.quality,
                            source=excluded.source,
                            available=excluded.available,
                            payload_json=excluded.payload_json,
                            created_at=excluded.created_at
                        """
                    ),
                    {
                        "trade_date": trade_date,
                        "symbol": str(symbol),
                        "quality": quality,
                        "source": payload.get("source"),
                        "available": available,
                        "payload_json": json.dumps(payload or {}, ensure_ascii=False),
                        "created_at": created_at,
                    },
                )

    def get_money_flow_snapshot_quality_counts(self, trade_date: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        date_clause = ""
        if trade_date:
            date_clause = "WHERE trade_date = :trade_date"
            params["trade_date"] = str(trade_date)
        with self._lock:
            with self.engine.connect() as conn:
                latest_row = conn.execute(
                    text(
                        f"""
                        SELECT trade_date
                        FROM money_flow_snapshots
                        {date_clause}
                        GROUP BY trade_date
                        ORDER BY trade_date DESC
                        LIMIT 1
                        """
                    ),
                    params,
                ).first()
                if not latest_row:
                    return {"trade_date": trade_date, "real": 0, "proxy": 0, "unavailable": 0, "total": 0}
                latest_date = str(latest_row._mapping["trade_date"])
                rows = conn.execute(
                    text(
                        """
                        SELECT quality, COUNT(*) AS count
                        FROM money_flow_snapshots
                        WHERE trade_date = :trade_date
                        GROUP BY quality
                        """
                    ),
                    {"trade_date": latest_date},
                ).fetchall()
        counts = {"trade_date": latest_date, "real": 0, "proxy": 0, "unavailable": 0, "total": 0}
        for row in rows:
            quality = str(row._mapping.get("quality") or "unavailable")
            count = int(row._mapping.get("count") or 0)
            if quality not in {"real", "proxy", "unavailable"}:
                quality = "unavailable"
            counts[quality] += count
            counts["total"] += count
        return counts

    def get_money_flow_snapshots_by_symbols(
        self,
        symbols: List[str],
        trade_date: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        clean_symbols = [str(symbol or "").strip() for symbol in symbols or [] if str(symbol or "").strip()]
        if not clean_symbols:
            return {}

        params: Dict[str, Any] = {"symbols": clean_symbols}
        date_clause = ""
        if trade_date:
            date_clause = "AND trade_date = :trade_date"
            params["trade_date"] = str(trade_date)

        with self._lock:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        f"""
                        SELECT trade_date, symbol, quality, source, available, payload_json, created_at
                        FROM money_flow_snapshots
                        WHERE symbol IN :symbols
                        {date_clause}
                        ORDER BY symbol, trade_date DESC, created_at DESC
                        """
                    ).bindparams(bindparam("symbols", expanding=True)),
                    params,
                ).fetchall()

        snapshots: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            data = dict(row._mapping)
            symbol = str(data.get("symbol") or "")
            if symbol in snapshots:
                continue
            try:
                payload = json.loads(data.get("payload_json") or "{}")
            except Exception:
                payload = {}
            data["payload"] = payload
            snapshots[symbol] = data
        return snapshots

    def upsert_theme_snapshots(self, trade_date: str, themes: List[Dict[str, Any]], created_at: str) -> int:
        rows = []
        for item in themes or []:
            theme_id = str(item.get("theme_id") or "").strip()
            theme_name = str(item.get("theme_name") or "").strip()
            if not theme_id or not theme_name:
                continue
            rows.append(
                {
                    "trade_date": trade_date,
                    "theme_id": theme_id,
                    "theme_name": theme_name,
                    "category": item.get("category"),
                    "payload_json": json.dumps(item, ensure_ascii=False),
                    "created_at": created_at,
                }
            )
        if not rows:
            return 0
        with self._lock:
            with self.engine.begin() as conn:
                for row in rows:
                    conn.execute(
                        text(
                            """
                            INSERT INTO theme_snapshots (
                                trade_date, theme_id, theme_name, category, payload_json, created_at
                            ) VALUES (
                                :trade_date, :theme_id, :theme_name, :category, :payload_json, :created_at
                            )
                            ON CONFLICT(trade_date, theme_id) DO UPDATE SET
                                theme_name=excluded.theme_name,
                                category=excluded.category,
                                payload_json=excluded.payload_json,
                                created_at=excluded.created_at
                            """
                        ),
                        row,
                    )
        return len(rows)

    def open_or_add_position(
        self,
        user_id: str,
        symbol: str,
        name: str,
        pick_id: str,
        price: float,
        qty: float,
        created_at: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        qty = max(float(qty), 0.0)
        price = max(float(price), 0.0)
        amount = round(price * qty, 6)
        if qty <= 0 or price <= 0:
            raise ValueError("模拟买入参数非法，price 和 qty 必须大于 0")

        with self._lock:
            with self.engine.begin() as conn:
                pos = conn.execute(
                    text(
                        """
                        SELECT *
                        FROM paper_positions
                        WHERE user_id = :user_id AND symbol = :symbol AND status = 'open'
                        """
                    ),
                    {"user_id": user_id, "symbol": symbol},
                ).first()

                if pos:
                    p = pos._mapping
                    old_qty = float(p["qty"])
                    old_cost = float(p["cost_amount"])
                    new_qty = round(old_qty + qty, 6)
                    new_cost = round(old_cost + amount, 6)
                    avg_price = round(new_cost / new_qty, 6) if new_qty > 0 else 0.0
                    conn.execute(
                        text(
                            """
                            UPDATE paper_positions
                            SET qty = :qty,
                                avg_price = :avg_price,
                                cost_amount = :cost_amount,
                                name = :name,
                                pick_id = COALESCE(:pick_id, pick_id),
                                updated_at = :updated_at
                            WHERE id = :id
                            """
                        ),
                        {
                            "qty": new_qty,
                            "avg_price": avg_price,
                            "cost_amount": new_cost,
                            "name": name,
                            "pick_id": pick_id,
                            "updated_at": created_at,
                            "id": p["id"],
                        },
                    )
                else:
                    conn.execute(
                        text(
                            """
                            INSERT INTO paper_positions (
                                user_id, symbol, name, pick_id, qty, avg_price, cost_amount, status, opened_at, updated_at
                            ) VALUES (
                                :user_id, :symbol, :name, :pick_id, :qty, :avg_price, :cost_amount, 'open', :opened_at, :updated_at
                            )
                            """
                        ),
                        {
                            "user_id": user_id,
                            "symbol": symbol,
                            "name": name,
                            "pick_id": pick_id,
                            "qty": qty,
                            "avg_price": price,
                            "cost_amount": amount,
                            "opened_at": created_at,
                            "updated_at": created_at,
                        },
                    )

                conn.execute(
                    text(
                        """
                        INSERT INTO paper_trades (
                            user_id, symbol, name, pick_id, side, price, qty, amount, fee, reason, created_at
                        ) VALUES (
                            :user_id, :symbol, :name, :pick_id, 'buy', :price, :qty, :amount, 0, :reason, :created_at
                        )
                        """
                    ),
                    {
                        "user_id": user_id,
                        "symbol": symbol,
                        "name": name,
                        "pick_id": pick_id,
                        "price": price,
                        "qty": qty,
                        "amount": amount,
                        "reason": reason,
                        "created_at": created_at,
                    },
                )

                row = conn.execute(
                    text(
                        """
                        SELECT *
                        FROM paper_positions
                        WHERE user_id = :user_id AND symbol = :symbol AND status = 'open'
                        """
                    ),
                    {"user_id": user_id, "symbol": symbol},
                ).first()
                return self._row_to_dict(row) or {}

    def close_position(
        self,
        user_id: str,
        symbol: str,
        close_price: float,
        close_qty: Optional[float],
        created_at: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        close_price = max(float(close_price), 0.0)
        if close_price <= 0:
            raise ValueError("平仓价格非法，close_price 必须大于 0")

        with self._lock:
            with self.engine.begin() as conn:
                pos = conn.execute(
                    text(
                        """
                        SELECT *
                        FROM paper_positions
                        WHERE user_id = :user_id AND symbol = :symbol AND status = 'open'
                        """
                    ),
                    {"user_id": user_id, "symbol": symbol},
                ).first()
                if not pos:
                    raise ValueError(f"未找到可平仓仓位: {symbol}")

                p = pos._mapping
                origin_qty = float(p["qty"])
                avg_price = float(p["avg_price"])
                cost_amount = float(p["cost_amount"])
                qty = origin_qty if close_qty is None else max(float(close_qty), 0.0)
                qty = min(qty, origin_qty)
                if qty <= 0:
                    raise ValueError("平仓数量非法，close_qty 必须大于 0")

                amount = round(close_price * qty, 6)
                remaining_qty = round(origin_qty - qty, 6)
                realized_pnl = round((close_price - avg_price) * qty, 6)
                remaining_cost = round(cost_amount * (remaining_qty / origin_qty), 6) if origin_qty > 0 else 0.0

                conn.execute(
                    text(
                        """
                        INSERT INTO paper_trades (
                            user_id, symbol, name, pick_id, side, price, qty, amount, fee, reason, created_at
                        ) VALUES (
                            :user_id, :symbol, :name, :pick_id, 'sell', :price, :qty, :amount, 0, :reason, :created_at
                        )
                        """
                    ),
                    {
                        "user_id": user_id,
                        "symbol": symbol,
                        "name": p.get("name"),
                        "pick_id": p.get("pick_id"),
                        "price": close_price,
                        "qty": qty,
                        "amount": amount,
                        "reason": reason,
                        "created_at": created_at,
                    },
                )

                if remaining_qty <= 0:
                    # 全平时直接删除 open 持仓，历史由 paper_trades 保留，避免 (user_id,symbol,status) 唯一约束冲突
                    conn.execute(
                        text(
                            """
                            DELETE FROM paper_positions
                            WHERE id = :id
                            """
                        ),
                        {"id": p["id"]},
                    )
                    result = {
                        "id": p["id"],
                        "user_id": user_id,
                        "symbol": symbol,
                        "name": p.get("name"),
                        "pick_id": p.get("pick_id"),
                        "qty": 0,
                        "avg_price": avg_price,
                        "cost_amount": 0,
                        "market_value": amount,
                        "unrealized_pnl": 0,
                        "unrealized_pnl_pct": 0,
                        "status": "closed",
                        "opened_at": p.get("opened_at"),
                        "updated_at": created_at,
                        "closed_at": created_at,
                    }
                else:
                    conn.execute(
                        text(
                            """
                            UPDATE paper_positions
                            SET qty = :qty,
                                cost_amount = :cost_amount,
                                updated_at = :updated_at
                            WHERE id = :id
                            """
                        ),
                        {
                            "qty": remaining_qty,
                            "cost_amount": remaining_cost,
                            "updated_at": created_at,
                            "id": p["id"],
                        },
                    )
                    row = conn.execute(
                        text("SELECT * FROM paper_positions WHERE id = :id"),
                        {"id": p["id"]},
                    ).first()
                    result = self._row_to_dict(row) or {}
                result["realized_pnl"] = realized_pnl
                result["closed_qty"] = qty
                result["pick_id"] = p.get("pick_id")
                return result

    def list_open_positions(self, user_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT *
                        FROM paper_positions
                        WHERE user_id = :user_id AND status = 'open'
                        ORDER BY updated_at DESC, id DESC
                        """
                    ),
                    {"user_id": user_id},
                ).fetchall()
                return [dict(row._mapping) for row in rows]

    def update_position_mark(
        self,
        position_id: int,
        market_value: float,
        unrealized_pnl: float,
        unrealized_pnl_pct: float,
        updated_at: str,
    ) -> None:
        with self._lock:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE paper_positions
                        SET market_value = :market_value,
                            unrealized_pnl = :unrealized_pnl,
                            unrealized_pnl_pct = :unrealized_pnl_pct,
                            updated_at = :updated_at
                        WHERE id = :id
                        """
                    ),
                    {
                        "market_value": round(float(market_value), 6),
                        "unrealized_pnl": round(float(unrealized_pnl), 6),
                        "unrealized_pnl_pct": round(float(unrealized_pnl_pct), 6),
                        "updated_at": updated_at,
                        "id": int(position_id),
                    },
                )

    def list_paper_trades(self, user_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT *
                        FROM paper_trades
                        WHERE user_id = :user_id
                        ORDER BY id DESC
                        LIMIT :limit
                        """
                    ),
                    {"user_id": user_id, "limit": max(1, min(limit, 2000))},
                ).fetchall()
                return [dict(row._mapping) for row in rows]

    def save_paper_trade_evaluation(self, record: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "eval_id": str(record.get("eval_id")),
            "user_id": str(record.get("user_id") or "default"),
            "symbol": str(record.get("symbol") or ""),
            "name": record.get("name"),
            "pick_id": record.get("pick_id"),
            "status": str(record.get("status") or "open"),
            "entry_date": record.get("entry_date"),
            "exit_date": record.get("exit_date"),
            "metrics_json": json.dumps(record.get("metrics") or {}, ensure_ascii=False),
            "attribution_json": json.dumps(record.get("attribution") or {}, ensure_ascii=False),
            "snapshot_json": json.dumps(record.get("snapshot") or {}, ensure_ascii=False),
            "calibration_json": json.dumps(record.get("calibration") or {}, ensure_ascii=False),
            "created_at": str(record.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "updated_at": str(record.get("updated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        }
        with self._lock:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO paper_trade_evaluations (
                            eval_id, user_id, symbol, name, pick_id, status, entry_date, exit_date,
                            metrics_json, attribution_json, snapshot_json, calibration_json, created_at, updated_at
                        ) VALUES (
                            :eval_id, :user_id, :symbol, :name, :pick_id, :status, :entry_date, :exit_date,
                            :metrics_json, :attribution_json, :snapshot_json, :calibration_json, :created_at, :updated_at
                        )
                        ON CONFLICT(eval_id) DO UPDATE SET
                            name=excluded.name,
                            pick_id=excluded.pick_id,
                            status=excluded.status,
                            entry_date=excluded.entry_date,
                            exit_date=excluded.exit_date,
                            metrics_json=excluded.metrics_json,
                            attribution_json=excluded.attribution_json,
                            snapshot_json=excluded.snapshot_json,
                            calibration_json=excluded.calibration_json,
                            updated_at=excluded.updated_at
                        """
                    ),
                    payload,
                )
        return {
            "eval_id": payload["eval_id"],
            "user_id": payload["user_id"],
            "symbol": payload["symbol"],
            "name": payload["name"],
            "pick_id": payload["pick_id"],
            "status": payload["status"],
            "entry_date": payload["entry_date"],
            "exit_date": payload["exit_date"],
            "metrics": record.get("metrics") or {},
            "attribution": record.get("attribution") or {},
            "snapshot": record.get("snapshot") or {},
            "calibration": record.get("calibration") or {},
            "created_at": payload["created_at"],
            "updated_at": payload["updated_at"],
        }

    def list_paper_trade_evaluations(
        self,
        user_id: str,
        status: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        clauses = ["user_id = :user_id"]
        params: Dict[str, Any] = {"user_id": str(user_id), "limit": max(1, min(int(limit or 500), 2000))}
        if status:
            clauses.append("status = :status")
            params["status"] = str(status)
        sql = text(
            f"""
            SELECT *
            FROM paper_trade_evaluations
            WHERE {' AND '.join(clauses)}
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        )
        with self._lock:
            with self.engine.connect() as conn:
                rows = conn.execute(sql, params).fetchall()

        out: List[Dict[str, Any]] = []
        for row in rows:
            data = dict(row._mapping)
            for source_key, target_key, default in (
                ("metrics_json", "metrics", {}),
                ("attribution_json", "attribution", {}),
                ("snapshot_json", "snapshot", {}),
                ("calibration_json", "calibration", {}),
            ):
                try:
                    data[target_key] = json.loads(data.get(source_key) or json.dumps(default, ensure_ascii=False))
                except Exception:
                    data[target_key] = default
            out.append(data)
        return out

    def delete_orphan_open_paper_trade_evaluations(self, user_id: str) -> int:
        """Remove open evaluation rows whose open position no longer exists."""
        with self._lock:
            with self.engine.begin() as conn:
                result = conn.execute(
                    text(
                        """
                        DELETE FROM paper_trade_evaluations
                        WHERE user_id = :user_id
                          AND status = 'open'
                          AND NOT EXISTS (
                              SELECT 1
                              FROM paper_positions p
                              WHERE p.user_id = paper_trade_evaluations.user_id
                                AND p.symbol = paper_trade_evaluations.symbol
                                AND p.status = 'open'
                          )
                        """
                    ),
                    {"user_id": str(user_id)},
                )
                return int(result.rowcount or 0)

    def save_backtest_run(
        self,
        run_id: str,
        user_id: str,
        strategy_code: str,
        config: Dict[str, Any],
        result: Dict[str, Any],
        status: str,
        started_at: str,
        finished_at: Optional[str],
    ) -> None:
        with self._lock:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO backtest_runs (
                            run_id, user_id, strategy_code, config_json, result_json, status, started_at, finished_at
                        ) VALUES (
                            :run_id, :user_id, :strategy_code, :config_json, :result_json, :status, :started_at, :finished_at
                        )
                        ON CONFLICT(run_id) DO UPDATE SET
                            user_id=excluded.user_id,
                            strategy_code=excluded.strategy_code,
                            config_json=excluded.config_json,
                            result_json=excluded.result_json,
                            status=excluded.status,
                            started_at=excluded.started_at,
                            finished_at=excluded.finished_at
                        """
                    ),
                    {
                        "run_id": run_id,
                        "user_id": user_id,
                        "strategy_code": strategy_code,
                        "config_json": json.dumps(config, ensure_ascii=False),
                        "result_json": json.dumps(result, ensure_ascii=False),
                        "status": status,
                        "started_at": started_at,
                        "finished_at": finished_at,
                    },
                )

    def get_backtest_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT *
                        FROM backtest_runs
                        WHERE run_id = :run_id
                        """
                    ),
                    {"run_id": run_id},
                ).first()
                if not row:
                    return None

                data = dict(row._mapping)
                result_json = data.get("result_json")
                if result_json:
                    try:
                        return json.loads(result_json)
                    except Exception:
                        return None
                return None

    def list_backtest_runs(
        self,
        user_id: Optional[str] = None,
        strategy_code: Optional[str] = None,
        limit: int = 30,
    ) -> List[Dict[str, Any]]:
        filters = []
        params: Dict[str, Any] = {"limit": max(1, min(int(limit or 30), 300))}
        if user_id:
            filters.append("user_id = :user_id")
            params["user_id"] = str(user_id)
        if strategy_code:
            filters.append("strategy_code = :strategy_code")
            params["strategy_code"] = str(strategy_code)

        where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
        sql = f"""
            SELECT run_id, user_id, strategy_code, result_json, status, started_at, finished_at
            FROM backtest_runs
            {where_sql}
            ORDER BY started_at DESC
            LIMIT :limit
        """

        rows_out: List[Dict[str, Any]] = []
        with self._lock:
            with self.engine.connect() as conn:
                rows = conn.execute(text(sql), params).fetchall()
                for row in rows:
                    data = dict(row._mapping)
                    raw = data.pop("result_json", None)
                    parsed: Dict[str, Any] = {}
                    if raw:
                        try:
                            parsed = json.loads(raw)
                        except Exception:
                            parsed = {}
                    data["result"] = parsed
                    rows_out.append(data)
        return rows_out

    def upsert_news_events(self, events: List[Dict[str, Any]]) -> int:
        if not events:
            return 0

        sql = text(
            """
            INSERT INTO news_events (
                source, source_type, event_level, event_type, title, summary, url, publish_time,
                symbol, symbol_name, industry_tags_json, direction, impact_score, confidence_score,
                event_score, content_hash, meta_json, created_at
            ) VALUES (
                :source, :source_type, :event_level, :event_type, :title, :summary, :url, :publish_time,
                :symbol, :symbol_name, :industry_tags_json, :direction, :impact_score, :confidence_score,
                :event_score, :content_hash, :meta_json, :created_at
            )
            ON CONFLICT(content_hash) DO UPDATE SET
                source=excluded.source,
                source_type=excluded.source_type,
                event_level=excluded.event_level,
                event_type=excluded.event_type,
                title=excluded.title,
                summary=excluded.summary,
                url=excluded.url,
                publish_time=excluded.publish_time,
                symbol=excluded.symbol,
                symbol_name=excluded.symbol_name,
                industry_tags_json=excluded.industry_tags_json,
                direction=excluded.direction,
                impact_score=excluded.impact_score,
                confidence_score=excluded.confidence_score,
                event_score=excluded.event_score,
                meta_json=excluded.meta_json,
                created_at=excluded.created_at
            """
        )
        count = 0
        with self._lock:
            with self.engine.begin() as conn:
                for event in events:
                    conn.execute(
                        sql,
                        {
                            "source": str(event.get("source") or ""),
                            "source_type": str(event.get("source_type") or ""),
                            "event_level": str(event.get("event_level") or ""),
                            "event_type": str(event.get("event_type") or ""),
                            "title": str(event.get("title") or ""),
                            "summary": event.get("summary"),
                            "url": str(event.get("url") or ""),
                            "publish_time": str(event.get("publish_time") or ""),
                            "symbol": event.get("symbol"),
                            "symbol_name": event.get("symbol_name"),
                            "industry_tags_json": json.dumps(event.get("industry_tags") or [], ensure_ascii=False),
                            "direction": str(event.get("direction") or "neutral"),
                            "impact_score": float(event.get("impact_score") or 0),
                            "confidence_score": float(event.get("confidence_score") or 0),
                            "event_score": float(event.get("event_score") or 0),
                            "content_hash": str(event.get("content_hash") or ""),
                            "meta_json": json.dumps(event.get("meta") or {}, ensure_ascii=False),
                            "created_at": str(event.get("created_at") or ""),
                        },
                    )
                    count += 1
        return count

    def list_news_events(
        self,
        event_level: Optional[str] = None,
        event_levels: Optional[List[str]] = None,
        symbol: Optional[str] = None,
        since_time: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        keyword: Optional[str] = None,
        source: Optional[str] = None,
        relevant_only: bool = False,
    ) -> List[Dict[str, Any]]:
        clauses = []
        params: Dict[str, Any] = {
            "limit": max(1, min(int(limit or 100), 1000)),
            "offset": max(0, int(offset or 0)),
        }
        if event_level:
            clauses.append("event_level = :event_level")
            params["event_level"] = str(event_level)
        elif event_levels:
            levels = [str(item).strip() for item in event_levels if str(item).strip()]
            if levels:
                placeholders = []
                for i, level in enumerate(levels):
                    key = f"event_level_{i}"
                    placeholders.append(f":{key}")
                    params[key] = level
                clauses.append(f"event_level IN ({', '.join(placeholders)})")
        if symbol:
            clauses.append("symbol = :symbol")
            params["symbol"] = str(symbol)
        if since_time:
            clauses.append("publish_time >= :since_time")
            params["since_time"] = str(since_time)
        if source:
            clauses.append("source = :source")
            params["source"] = str(source)
        if relevant_only:
            clauses.append(
                "(ABS(COALESCE(event_score, 0)) > 0.01 OR "
                "COALESCE(industry_tags_json, '') NOT IN ('', '[]') OR "
                "COALESCE(impact_score, 0) >= 2.8 OR "
                "event_type IN ('monetary_policy', 'market_regulation', 'geopolitical_event', 'industry_policy'))"
            )
        if keyword:
            raw_keyword = str(keyword).strip()
            lower_keyword = raw_keyword.lower()
            aliases = [raw_keyword]
            if lower_keyword in {"ai", "aigc", "人工智能"}:
                aliases.extend(["人工智能", "大模型", "AIGC", "算力", "云计算", "数据要素"])
            elif lower_keyword in {"ev", "新能源车", "新能源汽车"}:
                aliases.extend(["新能源汽车", "汽车消费", "充电桩", "锂电", "储能"])
            elif lower_keyword in {"半导体", "芯片"}:
                aliases.extend(["半导体", "芯片", "集成电路", "晶圆", "算力"])

            keyword_clauses = []
            for i, term in enumerate(dict.fromkeys(item for item in aliases if str(item).strip())):
                key = f"keyword_{i}"
                params[key] = f"%{str(term).strip().lower()}%"
                keyword_clauses.append(
                    "(LOWER(COALESCE(title, '')) LIKE :{key} OR "
                    "LOWER(COALESCE(summary, '')) LIKE :{key} OR "
                    "LOWER(COALESCE(symbol_name, '')) LIKE :{key} OR "
                    "LOWER(COALESCE(industry_tags_json, '')) LIKE :{key} OR "
                    "LOWER(COALESCE(event_type, '')) LIKE :{key} OR "
                    "LOWER(COALESCE(source, '')) LIKE :{key})".format(key=key)
                )
            if keyword_clauses:
                clauses.append(f"({' OR '.join(keyword_clauses)})")

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = text(
            f"""
            SELECT *
            FROM news_events
            {where_sql}
            ORDER BY publish_time DESC, id DESC
            LIMIT :limit
            OFFSET :offset
            """
        )
        out: List[Dict[str, Any]] = []
        with self._lock:
            with self.engine.connect() as conn:
                rows = conn.execute(sql, params).fetchall()
                for row in rows:
                    data = dict(row._mapping)
                    try:
                        data["industry_tags"] = json.loads(data.get("industry_tags_json") or "[]")
                    except Exception:
                        data["industry_tags"] = []
                    try:
                        data["meta"] = json.loads(data.get("meta_json") or "{}")
                    except Exception:
                        data["meta"] = {}
                    out.append(data)
        return out

    def save_ml_model_version(self, record: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "model_id": str(record.get("model_id")),
            "model_code": str(record.get("model_code") or "explainable_lr_v1"),
            "strategy_code": str(record.get("strategy_code") or "all"),
            "status": str(record.get("status") or "paper_only"),
            "artifact_path": str(record.get("artifact_path") or ""),
            "feature_names_json": json.dumps(record.get("feature_names") or [], ensure_ascii=False),
            "metrics_json": json.dumps(record.get("metrics") or {}, ensure_ascii=False),
            "train_config_json": json.dumps(record.get("train_config") or {}, ensure_ascii=False),
            "train_start": record.get("train_start"),
            "train_end": record.get("train_end"),
            "sample_count": int(record.get("sample_count") or 0),
            "created_at": str(record.get("created_at") or ""),
        }
        with self._lock:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO ml_model_versions (
                            model_id, model_code, strategy_code, status, artifact_path,
                            feature_names_json, metrics_json, train_config_json,
                            train_start, train_end, sample_count, created_at
                        ) VALUES (
                            :model_id, :model_code, :strategy_code, :status, :artifact_path,
                            :feature_names_json, :metrics_json, :train_config_json,
                            :train_start, :train_end, :sample_count, :created_at
                        )
                        ON CONFLICT(model_id) DO UPDATE SET
                            model_code=excluded.model_code,
                            strategy_code=excluded.strategy_code,
                            status=excluded.status,
                            artifact_path=excluded.artifact_path,
                            feature_names_json=excluded.feature_names_json,
                            metrics_json=excluded.metrics_json,
                            train_config_json=excluded.train_config_json,
                            train_start=excluded.train_start,
                            train_end=excluded.train_end,
                            sample_count=excluded.sample_count,
                            created_at=excluded.created_at
                        """
                    ),
                    payload,
                )
        return record

    @staticmethod
    def _decode_ml_model_row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        data = dict(row)
        for json_key, out_key, default in [
            ("feature_names_json", "feature_names", []),
            ("metrics_json", "metrics", {}),
            ("train_config_json", "train_config", {}),
        ]:
            try:
                data[out_key] = json.loads(data.get(json_key) or json.dumps(default))
            except Exception:
                data[out_key] = default
            data.pop(json_key, None)
        return data

    def get_latest_ml_model(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT *
                        FROM ml_model_versions
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    )
                ).first()
        return self._decode_ml_model_row(self._row_to_dict(row))

    def get_ml_model(self, model_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text("SELECT * FROM ml_model_versions WHERE model_id = :model_id"),
                    {"model_id": str(model_id)},
                ).first()
        return self._decode_ml_model_row(self._row_to_dict(row))

    def save_ml_training_samples(self, model_id: str, samples: List[Dict[str, Any]], feature_names: List[str]) -> int:
        if not samples:
            return 0
        now_str = samples[0].get("created_at") or ""
        if not now_str:
            from datetime import datetime

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = []
        for item in samples:
            features = {name: float(item.get(name) or 0.0) for name in feature_names}
            labels = {
                "future_return_pct": float(item.get("future_return_pct") or 0.0),
                "future_max_drawdown_pct": float(item.get("future_max_drawdown_pct") or 0.0),
                "future_return_3d_pct": float(item.get("future_return_3d_pct") or 0.0),
                "future_max_return_3d_pct": float(item.get("future_max_return_3d_pct") or 0.0),
                "future_max_drawdown_3d_pct": float(item.get("future_max_drawdown_3d_pct") or 0.0),
                "label_up": int(item.get("label_up") or 0),
                "label_swing_up_15d": int(item.get("label_swing_up_15d") or item.get("label_up") or 0),
                "label_short_continuation_3d": int(item.get("label_short_continuation_3d") or 0),
                "label_dd": int(item.get("label_dd") or 0),
                "label_risk_adjusted_return": float(item.get("label_risk_adjusted_return") or 0.0),
            }
            rows.append(
                {
                    "model_id": str(model_id),
                    "symbol": str(item.get("symbol") or ""),
                    "trade_date": str(item.get("date") or item.get("trade_date") or ""),
                    "feature_json": json.dumps(features, ensure_ascii=False),
                    "label_json": json.dumps(labels, ensure_ascii=False),
                    "meta_json": json.dumps({"name": item.get("name")}, ensure_ascii=False),
                    "created_at": now_str,
                }
            )
        with self._lock:
            with self.engine.begin() as conn:
                conn.execute(text("DELETE FROM ml_training_samples WHERE model_id = :model_id"), {"model_id": str(model_id)})
                conn.execute(
                    text(
                        """
                        INSERT INTO ml_training_samples (
                            model_id, symbol, trade_date, feature_json, label_json, meta_json, created_at
                        ) VALUES (
                            :model_id, :symbol, :trade_date, :feature_json, :label_json, :meta_json, :created_at
                        )
                        """
                    ),
                    rows,
                )
        return len(rows)

    def list_ml_training_samples(self, model_id: str, limit: int = 2000) -> List[Dict[str, Any]]:
        with self._lock:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT symbol, trade_date, feature_json, label_json, meta_json
                        FROM ml_training_samples
                        WHERE model_id = :model_id
                        ORDER BY trade_date DESC
                        LIMIT :limit
                        """
                    ),
                    {"model_id": str(model_id), "limit": int(limit)},
                ).fetchall()
        out = []
        for row in rows:
            data = dict(row._mapping)
            try:
                data["features"] = json.loads(data.pop("feature_json") or "{}")
            except Exception:
                data["features"] = {}
            try:
                data["labels"] = json.loads(data.pop("label_json") or "{}")
            except Exception:
                data["labels"] = {}
            try:
                data["meta"] = json.loads(data.pop("meta_json") or "{}")
            except Exception:
                data["meta"] = {}
            out.append(data)
        return out

    def save_ml_factor_importance(self, model_id: str, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0
        from datetime import datetime

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload = [
            {
                "model_id": str(model_id),
                "feature": str(item.get("feature") or ""),
                "label": item.get("label"),
                "category": item.get("category"),
                "up_coef": float(item.get("up_coef") or 0.0),
                "dd_coef": float(item.get("dd_coef") or 0.0),
                "importance": float(item.get("importance") or 0.0),
                "created_at": now_str,
            }
            for item in rows
        ]
        with self._lock:
            with self.engine.begin() as conn:
                conn.execute(text("DELETE FROM ml_factor_importance WHERE model_id = :model_id"), {"model_id": str(model_id)})
                conn.execute(
                    text(
                        """
                        INSERT INTO ml_factor_importance (
                            model_id, feature, label, category, up_coef, dd_coef, importance, created_at
                        ) VALUES (
                            :model_id, :feature, :label, :category, :up_coef, :dd_coef, :importance, :created_at
                        )
                        """
                    ),
                    payload,
                )
        return len(payload)

    def list_ml_factor_importance(self, model_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT feature, label, category, up_coef, dd_coef, importance
                        FROM ml_factor_importance
                        WHERE model_id = :model_id
                        ORDER BY importance DESC
                        LIMIT :limit
                        """
                    ),
                    {"model_id": str(model_id), "limit": int(limit)},
                ).fetchall()
        return [dict(row._mapping) for row in rows]

    def save_ml_model_metrics(self, model_id: str, metrics: Dict[str, Any]) -> int:
        """Persist calibration/readiness metrics as queryable rows."""
        if not model_id or not metrics:
            return 0

        rows: List[Dict[str, Any]] = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        def _append(prefix: str, value: Any) -> None:
            key = prefix.strip(".")
            if not key:
                return
            if isinstance(value, bool):
                rows.append(
                    {
                        "model_id": str(model_id),
                        "metric_key": key,
                        "metric_value": 1.0 if value else 0.0,
                        "metric_json": None,
                        "created_at": now_str,
                    }
                )
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                rows.append(
                    {
                        "model_id": str(model_id),
                        "metric_key": key,
                        "metric_value": float(value),
                        "metric_json": None,
                        "created_at": now_str,
                    }
                )
            elif isinstance(value, dict):
                scalar_items = {k: v for k, v in value.items() if isinstance(v, (bool, int, float))}
                if scalar_items:
                    for child_key, child_value in scalar_items.items():
                        _append(f"{key}.{child_key}", child_value)
                non_scalar = {k: v for k, v in value.items() if not isinstance(v, (bool, int, float))}
                if non_scalar:
                    rows.append(
                        {
                            "model_id": str(model_id),
                            "metric_key": key,
                            "metric_value": None,
                            "metric_json": json.dumps(non_scalar, ensure_ascii=False),
                            "created_at": now_str,
                        }
                    )
            elif isinstance(value, list):
                rows.append(
                    {
                        "model_id": str(model_id),
                        "metric_key": key,
                        "metric_value": None,
                        "metric_json": json.dumps(value, ensure_ascii=False),
                        "created_at": now_str,
                    }
                )

        for metric_key, metric_value in metrics.items():
            _append(str(metric_key), metric_value)

        if not rows:
            return 0
        with self._lock:
            with self.engine.begin() as conn:
                conn.execute(text("DELETE FROM ml_model_metrics WHERE model_id = :model_id"), {"model_id": str(model_id)})
                conn.execute(
                    text(
                        """
                        INSERT INTO ml_model_metrics (
                            model_id, metric_key, metric_value, metric_json, created_at
                        ) VALUES (
                            :model_id, :metric_key, :metric_value, :metric_json, :created_at
                        )
                        """
                    ),
                    rows,
                )
        return len(rows)

    def list_ml_model_metrics(self, model_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT metric_key, metric_value, metric_json, created_at
                        FROM ml_model_metrics
                        WHERE model_id = :model_id
                        ORDER BY metric_key ASC
                        LIMIT :limit
                        """
                    ),
                    {"model_id": str(model_id), "limit": max(1, min(int(limit or 200), 1000))},
                ).fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            data = dict(row._mapping)
            if data.get("metric_json"):
                try:
                    data["metric_payload"] = json.loads(data.get("metric_json") or "null")
                except Exception:
                    data["metric_payload"] = None
            out.append(data)
        return out

    def save_ml_prediction(self, record: Dict[str, Any]) -> None:
        payload = {
            "model_id": str(record.get("model_id") or ""),
            "symbol": record.get("symbol"),
            "trade_date": str(record.get("trade_date") or ""),
            "prediction_json": json.dumps(record.get("prediction") or {}, ensure_ascii=False),
            "created_at": str(record.get("created_at") or ""),
        }
        with self._lock:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO ml_daily_predictions (
                            model_id, symbol, trade_date, prediction_json, created_at
                        ) VALUES (
                            :model_id, :symbol, :trade_date, :prediction_json, :created_at
                        )
                        """
                    ),
                    payload,
                )

    def save_monitor_snapshots(
        self,
        user_id: str,
        snapshot_date: str,
        snapshots: List[Dict[str, Any]],
    ) -> int:
        if not snapshots:
            return 0
        from datetime import datetime

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = []
        for item in snapshots:
            symbol = str(item.get("symbol") or "").strip()
            track_type = str(item.get("track_type") or "").strip()
            if not symbol or not track_type:
                continue
            rows.append(
                {
                    "user_id": str(user_id),
                    "symbol": symbol,
                    "name": item.get("name") or symbol,
                    "track_type": track_type,
                    "pick_id": item.get("pick_id"),
                    "snapshot_date": str(snapshot_date),
                    "metrics_json": json.dumps(item.get("metrics") or {}, ensure_ascii=False),
                    "conclusion_json": json.dumps(item.get("conclusion") or {}, ensure_ascii=False),
                    "data_quality_json": json.dumps(item.get("data_quality") or {}, ensure_ascii=False),
                    "created_at": now_str,
                }
            )
        if not rows:
            return 0

        with self._lock:
            with self.engine.begin() as conn:
                for row in rows:
                    conn.execute(
                        text(
                            """
                            INSERT INTO monitor_snapshots (
                                user_id, symbol, name, track_type, pick_id, snapshot_date,
                                metrics_json, conclusion_json, data_quality_json, created_at
                            ) VALUES (
                                :user_id, :symbol, :name, :track_type, :pick_id, :snapshot_date,
                                :metrics_json, :conclusion_json, :data_quality_json, :created_at
                            )
                            ON CONFLICT(user_id, symbol, track_type, snapshot_date) DO UPDATE SET
                                name=excluded.name,
                                pick_id=excluded.pick_id,
                                metrics_json=excluded.metrics_json,
                                conclusion_json=excluded.conclusion_json,
                                data_quality_json=excluded.data_quality_json,
                                created_at=excluded.created_at
                            """
                        ),
                        row,
                    )
        return len(rows)

    def list_monitor_snapshots(
        self,
        user_id: str,
        snapshot_date: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        clauses = ["user_id = :user_id"]
        params: Dict[str, Any] = {"user_id": str(user_id), "limit": max(1, min(int(limit), 2000))}
        if snapshot_date:
            clauses.append("snapshot_date = :snapshot_date")
            params["snapshot_date"] = str(snapshot_date)
        with self._lock:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        f"""
                        SELECT *
                        FROM monitor_snapshots
                        WHERE {' AND '.join(clauses)}
                        ORDER BY snapshot_date DESC, id DESC
                        LIMIT :limit
                        """
                    ),
                    params,
                ).fetchall()

        out: List[Dict[str, Any]] = []
        for row in rows:
            data = dict(row._mapping)
            for source_key, target_key in (
                ("metrics_json", "metrics"),
                ("conclusion_json", "conclusion"),
                ("data_quality_json", "data_quality"),
            ):
                try:
                    data[target_key] = json.loads(data.get(source_key) or "{}")
                except Exception:
                    data[target_key] = {}
            out.append(data)
        return out

    def save_strategy_feedback_report(
        self,
        report_id: str,
        user_id: str,
        report_date: str,
        report_type: str,
        summary: Dict[str, Any],
        suggestions: List[Dict[str, Any]],
        diagnostics: Dict[str, Any],
        created_at: str,
        failure_reasons: Optional[List[Dict[str, Any]]] = None,
        execution_deviation: Optional[Dict[str, Any]] = None,
        strategy_adjustments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        diagnostics_payload = {
            **(diagnostics or {}),
            "failure_reasons": failure_reasons or [],
            "execution_deviation": execution_deviation or {},
            "strategy_adjustments": strategy_adjustments or [],
        }
        payload = {
            "report_id": str(report_id),
            "user_id": str(user_id),
            "report_date": str(report_date),
            "report_type": str(report_type or "daily"),
            "summary_json": json.dumps(summary or {}, ensure_ascii=False),
            "suggestions_json": json.dumps(suggestions or [], ensure_ascii=False),
            "diagnostics_json": json.dumps(diagnostics_payload, ensure_ascii=False),
            "created_at": str(created_at),
        }
        with self._lock:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO strategy_feedback_reports (
                            report_id, user_id, report_date, report_type,
                            summary_json, suggestions_json, diagnostics_json, created_at
                        ) VALUES (
                            :report_id, :user_id, :report_date, :report_type,
                            :summary_json, :suggestions_json, :diagnostics_json, :created_at
                        )
                        ON CONFLICT(report_id) DO UPDATE SET
                            summary_json=excluded.summary_json,
                            suggestions_json=excluded.suggestions_json,
                            diagnostics_json=excluded.diagnostics_json,
                            created_at=excluded.created_at
                        """
                    ),
                    payload,
                )
        return {
            "report_id": payload["report_id"],
            "user_id": payload["user_id"],
            "report_date": payload["report_date"],
            "report_type": payload["report_type"],
            "summary": summary or {},
            "suggestions": suggestions or [],
            "diagnostics": diagnostics_payload,
            "failure_reasons": failure_reasons or [],
            "execution_deviation": execution_deviation or {},
            "strategy_adjustments": strategy_adjustments or [],
            "created_at": payload["created_at"],
        }

    def get_latest_strategy_feedback_report(
        self,
        user_id: str,
        report_type: str = "daily",
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT *
                        FROM strategy_feedback_reports
                        WHERE user_id = :user_id AND report_type = :report_type
                        ORDER BY report_date DESC, created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"user_id": str(user_id), "report_type": str(report_type or "daily")},
                ).first()
        if not row:
            return None
        data = dict(row._mapping)
        for source_key, target_key, default in (
            ("summary_json", "summary", {}),
            ("suggestions_json", "suggestions", []),
            ("diagnostics_json", "diagnostics", {}),
        ):
            try:
                data[target_key] = json.loads(data.get(source_key) or json.dumps(default, ensure_ascii=False))
            except Exception:
                data[target_key] = default
        diagnostics = data.get("diagnostics") or {}
        data["failure_reasons"] = diagnostics.get("failure_reasons") or []
        data["execution_deviation"] = diagnostics.get("execution_deviation") or {}
        data["strategy_adjustments"] = diagnostics.get("strategy_adjustments") or []
        return data
