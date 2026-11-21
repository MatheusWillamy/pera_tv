"""
Módulo de Cache Local com Persistência em SQLite e TTL de 7 Dias.
Garante velocidade ultrarrápida e evita requisições redundantes ao TMDB.
"""
import json
import sqlite3
import time
from typing import Any, Dict, List, Optional
from config import CACHE_DB_PATH, CACHE_TTL_SECONDS


class SQLiteCache:
    def __init__(self, db_path: str = CACHE_DB_PATH, default_ttl: int = CACHE_TTL_SECONDS):
        self.db_path = db_path
        self.default_ttl = default_ttl
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tmdb_cache (
                    cache_key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tmdb_cache_updated_at 
                ON tmdb_cache (updated_at)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS manual_matches (
                    override_key TEXT PRIMARY KEY,
                    media_type TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    data TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    def get(self, key: str, max_age_seconds: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Recupera item do cache se existir e não tiver expirado.
        """
        ttl = max_age_seconds if max_age_seconds is not None else self.default_ttl
        now = time.time()
        min_timestamp = now - ttl

        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT data, updated_at FROM tmdb_cache WHERE cache_key = ?",
                (key,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            if row["updated_at"] < min_timestamp:
                # Expirado
                return None

            try:
                return json.loads(row["data"])
            except Exception:
                return None

    def set(self, key: str, data: Dict[str, Any]) -> None:
        """
        Grava ou atualiza item no cache com timestamp atual.
        """
        now = time.time()
        serialized = json.dumps(data, ensure_ascii=False)

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO tmdb_cache (cache_key, data, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    data = excluded.data,
                    updated_at = excluded.updated_at
                """,
                (key, serialized, now),
            )
            conn.commit()

    def clear(self) -> int:
        """
        Remove todos os registros do cache.
        """
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM tmdb_cache")
            conn.commit()
            return cursor.rowcount

    def delete_by_prefix(self, prefix: str) -> int:
        """
        Remove chaves do cache cujo cache_key comece com o prefixo informado.
        """
        if not prefix:
            return 0
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM tmdb_cache WHERE cache_key LIKE ?", (f"{prefix}%",)
            )
            conn.commit()
            return cursor.rowcount

    def purge_expired(self, max_age_seconds: Optional[int] = None) -> int:
        """
        Remove registros antigos que ultrapassaram o TTL.
        """
        ttl = max_age_seconds if max_age_seconds is not None else self.default_ttl
        cutoff = time.time() - ttl
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM tmdb_cache WHERE updated_at < ?", (cutoff,)
            )
            conn.commit()
            return cursor.rowcount

    def set_manual_match(self, media_type: str, item_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Grava ou atualiza um override manual permanente (não expira no purge TTL).
        """
        mt = "series" if str(media_type).lower() in ("series", "tv") else "movie"
        iid = str(item_id).strip()
        key = f"{mt}:{iid}"
        now = time.time()
        payload = {**data, "media_type": mt, "item_id": iid, "updated_at": now}
        serialized = json.dumps(payload, ensure_ascii=False)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO manual_matches (override_key, media_type, item_id, data, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(override_key) DO UPDATE SET
                    media_type = excluded.media_type,
                    item_id = excluded.item_id,
                    data = excluded.data,
                    updated_at = excluded.updated_at
                """,
                (key, mt, iid, serialized, now),
            )
            conn.commit()
        return payload

    def get_manual_match(self, media_type: str, item_id: str) -> Optional[Dict[str, Any]]:
        mt = "series" if str(media_type).lower() in ("series", "tv") else "movie"
        key = f"{mt}:{str(item_id).strip()}"
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT data FROM manual_matches WHERE override_key = ?", (key,)
            ).fetchone()
            if not row:
                return None
            try:
                return json.loads(row["data"])
            except Exception:
                return None

    def list_manual_matches(self, provider: Optional[str] = None) -> List[Dict[str, Any]]:
        prov_filter = provider.strip().lower() if provider else None
        out: List[Dict[str, Any]] = []
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT data FROM manual_matches ORDER BY updated_at DESC"
            ).fetchall()
            for row in rows:
                try:
                    entry = json.loads(row["data"])
                except Exception:
                    continue
                if not isinstance(entry, dict):
                    continue
                if prov_filter:
                    provs = [str(p).strip().lower() for p in (entry.get("providers") or [])]
                    if prov_filter not in provs:
                        continue
                out.append(entry)
        return out

    def delete_manual_match(self, media_type: str, item_id: str) -> bool:
        mt = "series" if str(media_type).lower() in ("series", "tv") else "movie"
        key = f"{mt}:{str(item_id).strip()}"
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM manual_matches WHERE override_key = ?", (key,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def stats(self) -> Dict[str, Any]:
        """
        Retorna métricas do cache local.
        """
        now = time.time()
        with self._get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM tmdb_cache").fetchone()[0]
            expired = conn.execute(
                "SELECT COUNT(*) FROM tmdb_cache WHERE updated_at < ?",
                (now - self.default_ttl,),
            ).fetchone()[0]
            manual_total = conn.execute("SELECT COUNT(*) FROM manual_matches").fetchone()[0]

        return {
            "db_path": self.db_path,
            "total_records": total,
            "active_records": total - expired,
            "expired_records": expired,
            "manual_overrides": manual_total,
            "default_ttl_seconds": self.default_ttl,
        }


# Instância singleton padrão do cache
cache_instance = SQLiteCache()
