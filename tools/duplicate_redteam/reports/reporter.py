"""Reporting and metrics for the adversarial test laboratory."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class Reporter:
    def __init__(self, results_dir: Path, original_id: str):
        self.results_dir = Path(results_dir)
        self.original_id = original_id
        self.fn_dir = self.results_dir / "false_negatives" / original_id
        self.fn_dir.mkdir(parents=True, exist_ok=True)
        self.records: list[dict[str, Any]] = []
        self.start_time = time.time()

    def record_variant(
        self,
        variant_id: int,
        original_path: Path,
        variant_path: Path,
        transforms: list[Any],
        detection: Any,
        original_sha256: str,
        variant_sha256: str,
        media_info: Optional[dict] = None,
        seed: Optional[int] = None,
        commit: Optional[str] = None,
    ) -> None:
        transform_list = []
        families = []
        for t in transforms:
            if hasattr(t, "name"):
                transform_list.append({"name": t.name, "params": t.params, "family": t.family})
                families.append(t.family)
            else:
                transform_list.append(t)

        rec = {
            "variant_id": variant_id,
            "original": str(original_path),
            "original_sha256": original_sha256,
            "variant_path": str(variant_path),
            "variant_sha256": variant_sha256,
            "transforms": transform_list,
            "families": list(set(families)),
            "detection": detection.to_dict() if hasattr(detection, "to_dict") else detection,
            "media_info": media_info or {},
            "seed": seed,
            "commit": commit,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.records.append(rec)

        # Persist false negatives immediately
        if getattr(detection, "result", "") == "FALSE NEGATIVE":
            self._save_false_negative(variant_id, variant_path, rec)

    def _save_false_negative(self, variant_id: int, variant_path: Path, rec: dict) -> None:
        stem = f"variant_{variant_id:04d}"
        # copy media
        dest_media = self.fn_dir / f"{stem}{variant_path.suffix}"
        try:
            import shutil
            shutil.copy2(variant_path, dest_media)
        except Exception:
            pass
        # json
        dest_json = self.fn_dir / f"{stem}.json"
        with open(dest_json, "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=2, ensure_ascii=False)

    def summary(self) -> dict[str, Any]:
        total = len(self.records)
        if total == 0:
            return {"total": 0}

        detected = sum(1 for r in self.records if r["detection"]["policy"] == "DUPLICATE")
        fn = sum(1 for r in self.records if r["detection"]["result"] == "FALSE NEGATIVE")
        rate = detected / total if total else 0.0
        fn_rate = fn / total if total else 0.0

        # per-detector hit rates (how often each said MATCH)
        det_hits = defaultdict(int)
        for r in self.records:
            scores = r["detection"].get("scores", {})
            for name, data in scores.items():
                if isinstance(data, dict) and data.get("match"):
                    det_hits[name] += 1

        per_detector = {
            name: round(det_hits[name] / total * 100, 1) for name in [
                "exact_hash", "pdq", "sscd", "tmk_pdqf", "audio"
            ]
        }
        per_detector["combined_policy"] = round(rate * 100, 1)

        # by family
        family_stats: dict[str, dict] = defaultdict(lambda: {"total": 0, "detected": 0})
        for r in self.records:
            fams = r.get("families") or ["unknown"]
            for fam in fams:
                family_stats[fam]["total"] += 1
                if r["detection"]["policy"] == "DUPLICATE":
                    family_stats[fam]["detected"] += 1

        by_family = {}
        for fam, st in family_stats.items():
            t = st["total"]
            by_family[fam] = {
                "total": t,
                "detected": st["detected"],
                "rate_pct": round(st["detected"] / t * 100, 1) if t else 0.0,
            }

        return {
            "original_id": self.original_id,
            "variants_generated": total,
            "duplicate_detected": detected,
            "false_negatives": fn,
            "detection_rate": round(rate * 100, 1),
            "false_negative_rate": round(fn_rate * 100, 1),
            "per_detector": per_detector,
            "by_family": by_family,
            "duration_sec": round(time.time() - self.start_time, 1),
        }

    def print_summary(self) -> None:
        s = self.summary()
        print("\n" + "=" * 60)
        print("ADVERSARIAL DUPLICATE TEST")
        print("=" * 60)
        print(f"Original:              {s.get('original_id')}")
        print(f"Variants generated:    {s.get('variants_generated')}")
        print(f"Duplicate detected:    {s.get('duplicate_detected')}")
        print(f"False negatives:       {s.get('false_negatives')}")
        print(f"Detection rate:        {s.get('detection_rate')}%")
        print(f"False-negative rate:   {s.get('false_negative_rate')}%")
        print(f"Duration:              {s.get('duration_sec')}s")
        print("\nPOR DETECTOR")
        for k, v in s.get("per_detector", {}).items():
            print(f"  {k:20s} {v}%")
        print("\nPOR FAMÍLIA DE TRANSFORMAÇÃO")
        for fam, st in sorted(s.get("by_family", {}).items()):
            print(f"  {fam:20s} {st['rate_pct']}%  ({st['detected']}/{st['total']})")
        print("=" * 60)

    def print_variant(self, rec: dict) -> None:
        vid = rec["variant_id"]
        det = rec["detection"]
        print(f"\nVariant #{vid:03d}")
        print(f"Source: {rec['original']}")
        print("Transformations:")
        for t in rec["transforms"]:
            print(f"  - {t.get('name')} {t.get('params', {})}")
        print("RESULTS")
        scores = det.get("scores", {})
        for name in ["exact_hash", "pdq", "sscd", "tmk_pdqf", "audio"]:
            d = scores.get(name, {})
            match_str = "MATCH" if d.get("match") else "NO MATCH"
            score = d.get("score", "—")
            thr = d.get("threshold", "—")
            print(f"  {name:12s}  score={score}  threshold={thr}  → {match_str}")
        print(f"FINAL POLICY:  {det.get('policy')}")
        print(f"EXPECTED:      {det.get('expected')}")
        print(f"RESULT:        {det.get('result')}")

    def save_full_report(self, path: Optional[Path] = None) -> Path:
        path = path or (self.results_dir / f"report_{self.original_id}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "summary": self.summary(),
            "variants": self.records,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return path
