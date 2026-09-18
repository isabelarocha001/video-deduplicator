"""
Access to video-deduplicator fingerprint store on Supabase.

Tables (this project only — NOT Luxa):
  vd_media
  vd_media_fingerprints
  vd_duplicate_checks

Environment (never commit secrets):
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY

dry_run=True  → reads only, no writes
dry_run=False → allows upsert/insert
"""

from __future__ import annotations

import os
from typing import Any, Optional

try:
    from supabase import create_client, Client
except ImportError:
    create_client = None  # type: ignore
    Client = Any  # type: ignore


class SupabaseFingerprintStore:
    """Wrapper around vd_media / vd_media_fingerprints / vd_duplicate_checks."""

    def __init__(
        self,
        url: Optional[str] = None,
        service_key: Optional[str] = None,
        dry_run: bool = True,
    ):
        self.dry_run = dry_run
        self.url = url or os.environ.get("SUPABASE_URL", "")
        self.service_key = service_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        self._client: Optional[Client] = None

        if not self.url or not self.service_key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set "
                "(never commit these values)."
            )
        if create_client is None:
            raise ImportError("Install supabase: pip install supabase")

        self._client = create_client(self.url, self.service_key)

    # ------------------------------------------------------------------
    # Media registry
    # ------------------------------------------------------------------

    def create_media(self, row: dict[str, Any]) -> Optional[dict]:
        if self.dry_run:
            return {"dry_run": True, "would_insert": row}
        r = self._client.table("vd_media").insert(row).execute()
        return (r.data or [None])[0]

    def update_media_status(self, media_id: str, status: str, **extra: Any) -> Optional[dict]:
        if self.dry_run:
            return {"dry_run": True, "media_id": media_id, "status": status}
        payload = {"status": status, **extra}
        r = self._client.table("vd_media").update(payload).eq("id", media_id).execute()
        return (r.data or [None])[0]

    def get_media(self, media_id: str) -> Optional[dict]:
        r = self._client.table("vd_media").select("*").eq("id", media_id).limit(1).execute()
        rows = r.data or []
        return rows[0] if rows else None

    # ------------------------------------------------------------------
    # Fingerprint reads
    # ------------------------------------------------------------------

    def find_by_exact_hash(self, sha256: str) -> list[dict[str, Any]]:
        r = (
            self._client.table("vd_media_fingerprints")
            .select("id, media_id, algorithm, version, exact_sha256, metadata")
            .eq("exact_sha256", sha256)
            .eq("algorithm", "exact")
            .execute()
        )
        return r.data or []

    def get_fingerprints_for_media(self, media_id: str) -> list[dict[str, Any]]:
        r = (
            self._client.table("vd_media_fingerprints")
            .select("*")
            .eq("media_id", media_id)
            .execute()
        )
        return r.data or []

    def candidate_by_pdq(self, limit: int = 50) -> list[dict]:
        r = (
            self._client.table("vd_media_fingerprints")
            .select("id, media_id, pdq_hash, version, metadata")
            .eq("algorithm", "pdq")
            .not_.is_("pdq_hash", "null")
            .limit(limit)
            .execute()
        )
        return r.data or []

    def candidate_by_sscd(self, limit: int = 20) -> list[dict]:
        r = (
            self._client.table("vd_media_fingerprints")
            .select("id, media_id, sscd_embedding, version, metadata")
            .eq("algorithm", "sscd")
            .not_.is_("sscd_embedding", "null")
            .limit(limit * 3)
            .execute()
        )
        return r.data or []

    # ------------------------------------------------------------------
    # Writes (blocked when dry_run=True)
    # ------------------------------------------------------------------

    def upsert_fingerprint(self, row: dict[str, Any]) -> Optional[dict]:
        if self.dry_run:
            return {"dry_run": True, "would_upsert": {k: v for k, v in row.items() if k != "sscd_embedding"}}
        r = (
            self._client.table("vd_media_fingerprints")
            .upsert(row, on_conflict="media_id,algorithm,version")
            .execute()
        )
        return (r.data or [None])[0]

    def insert_duplicate_check(self, row: dict[str, Any]) -> Optional[dict]:
        if self.dry_run:
            return {"dry_run": True, "would_insert": row}
        r = self._client.table("vd_duplicate_checks").insert(row).execute()
        return (r.data or [None])[0]

    def health(self) -> dict[str, Any]:
        r = (
            self._client.table("vd_media_fingerprints")
            .select("id", count="exact")
            .limit(1)
            .execute()
        )
        m = (
            self._client.table("vd_media")
            .select("id", count="exact")
            .limit(1)
            .execute()
        )
        return {
            "ok": True,
            "project": "video-deduplicator (vd_*)",
            "media_count": m.count,
            "fingerprint_count": r.count,
            "dry_run": self.dry_run,
        }
