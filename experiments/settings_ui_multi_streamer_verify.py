"""Multi-streamer settings UI verification (headless-friendly).

Tests:
  T1. Legacy single-streamer fixture loads via normalize_streamers as 1 row.
  T2. Multi-streamer fixture loads as N rows preserving all fields.
  T3. Save policy: cfg["streamers"] canonical + legacy mirror (target_channel_id,
      streamer_name, fmkorea_search_keywords) all equal first row.
  T4. Round-trip: save then re-load → normalize_streamers returns identical list.
  T5. Empty/malformed streamers list falls back gracefully.
  T6. settings_ui import smoke (module loads, FIELDS structure preserved,
      streamer scalars NOT in FIELDS).
  T7. Live SettingsWindow UI test (skipped if Tk not available):
      load → modify → collect → destroy round-trip with both legacy and multi fixture.

Run:
  PYTHONIOENCODING=utf-8 python experiments/settings_ui_multi_streamer_verify.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path
from unittest import mock


def _print(msg: str) -> None:
    print(msg, flush=True)


def _ok(name: str) -> None:
    _print(f"[PASS] {name}")


def _fail(name: str, detail: str) -> None:
    _print(f"[FAIL] {name} -- {detail}")


def t1_legacy_load() -> bool:
    from pipeline.config import normalize_streamers

    cfg = {
        "target_channel_id": "a7e175625fdea5a7d98428302b7aa57f",
        "streamer_name": "탬탬",
        "fmkorea_search_keywords": ["탬탬", "탬탬버린"],
    }
    streamers = normalize_streamers(cfg)
    if len(streamers) != 1:
        _fail("T1 legacy_load", f"expected 1 row, got {len(streamers)}")
        return False
    s = streamers[0]
    if s["channel_id"] != "a7e175625fdea5a7d98428302b7aa57f":
        _fail("T1 legacy_load", f"channel_id mismatch: {s}")
        return False
    if s["name"] != "탬탬":
        _fail("T1 legacy_load", f"name mismatch: {s}")
        return False
    if s["search_keywords"] != ["탬탬", "탬탬버린"]:
        _fail("T1 legacy_load", f"keywords mismatch: {s}")
        return False
    _ok("T1 legacy_load -- single streamer normalized as 1 canonical row")
    return True


def t2_multi_load() -> bool:
    from pipeline.config import normalize_streamers

    cfg = {
        "streamers": [
            {"channel_id": "a" * 32, "name": "스트리머A", "search_keywords": ["A1", "A2"]},
            {"channel_id": "b" * 32, "name": "스트리머B", "search_keywords": ["B1"]},
            {"channel_id": "c" * 32, "name": "스트리머C", "search_keywords": []},
        ],
    }
    streamers = normalize_streamers(cfg)
    if len(streamers) != 3:
        _fail("T2 multi_load", f"expected 3 rows, got {len(streamers)}")
        return False
    if streamers[0]["channel_id"] != "a" * 32 or streamers[0]["name"] != "스트리머A":
        _fail("T2 multi_load", f"row 0 mismatch: {streamers[0]}")
        return False
    if streamers[2]["search_keywords"] != []:
        # default fallback in normalize: keywords empty list defaults to [name]
        if streamers[2]["search_keywords"] != ["스트리머C"]:
            _fail(
                "T2 multi_load",
                f"row 2 empty keywords expected [] or fallback ['스트리머C'], "
                f"got {streamers[2]['search_keywords']}",
            )
            return False
    _ok("T2 multi_load -- 3 streamers preserved")
    return True


def _simulate_save_payload(streamers: list[dict], base_cfg: dict | None = None) -> dict:
    """Reproduce SettingsWindow._collect_values() save payload for streamers.

    This mirrors the canonical-form-plus-legacy-mirror policy.
    """
    cfg = dict(base_cfg or {})
    cfg["streamers"] = list(streamers)
    first = streamers[0]
    cfg["target_channel_id"] = first["channel_id"]
    cfg["streamer_name"] = first["name"]
    cfg["fmkorea_search_keywords"] = list(first["search_keywords"])
    return cfg


def t3_save_policy() -> bool:
    streamers = [
        {"channel_id": "a" * 32, "name": "first", "search_keywords": ["k1", "k2"]},
        {"channel_id": "b" * 32, "name": "second", "search_keywords": ["k3"]},
    ]
    cfg = _simulate_save_payload(streamers, {"poll_interval_sec": 300})

    if cfg["streamers"] != streamers:
        _fail("T3 save_policy", "streamers list mismatch after save")
        return False
    if cfg["target_channel_id"] != "a" * 32:
        _fail("T3 save_policy", f"legacy target_channel_id mirror wrong: {cfg['target_channel_id']!r}")
        return False
    if cfg["streamer_name"] != "first":
        _fail("T3 save_policy", f"legacy streamer_name mirror wrong: {cfg['streamer_name']!r}")
        return False
    if cfg["fmkorea_search_keywords"] != ["k1", "k2"]:
        _fail("T3 save_policy", f"legacy keywords mirror wrong: {cfg['fmkorea_search_keywords']}")
        return False
    if cfg["poll_interval_sec"] != 300:
        _fail("T3 save_policy", f"unrelated key dropped: {cfg}")
        return False
    _ok("T3 save_policy -- streamers + legacy mirror correct")
    return True


def t4_roundtrip() -> bool:
    from pipeline.config import normalize_streamers

    streamers = [
        {"channel_id": "deadbeef" * 4, "name": "alpha", "search_keywords": ["x", "y", "z"]},
        {"channel_id": "feedface" * 4, "name": "beta", "search_keywords": ["q"]},
    ]
    saved = _simulate_save_payload(streamers, {})
    # Round-trip via JSON to validate serializability
    serialized = json.dumps(saved, ensure_ascii=False)
    reloaded = json.loads(serialized)
    rebuilt = normalize_streamers(reloaded)

    if rebuilt != streamers:
        _fail("T4 roundtrip", f"rebuilt {rebuilt} != original {streamers}")
        return False
    _ok("T4 roundtrip -- save → JSON → load preserves streamers list exactly")
    return True


def t5_empty_streamers_fallback() -> bool:
    from pipeline.config import normalize_streamers

    # streamers=None → legacy fallback (1 row from target_channel_id)
    cfg1 = {"streamers": None, "target_channel_id": "x" * 32, "streamer_name": "y"}
    out1 = normalize_streamers(cfg1)
    if len(out1) != 1 or out1[0]["channel_id"] != "x" * 32:
        _fail("T5 empty_fallback", f"streamers=None did not fall back: {out1}")
        return False

    # streamers=[] (truthy=False) → also legacy fallback per current normalize_streamers
    cfg2 = {"streamers": [], "target_channel_id": "y" * 32, "streamer_name": "z"}
    out2 = normalize_streamers(cfg2)
    if len(out2) != 1 or out2[0]["channel_id"] != "y" * 32:
        _fail("T5 empty_fallback", f"streamers=[] did not fall back: {out2}")
        return False

    _ok("T5 empty_streamers_fallback -- None/[] both fall back to legacy scalars")
    return True


def t6_import_smoke() -> bool:
    try:
        import importlib
        import pipeline.settings_ui as ui
        importlib.reload(ui)
    except Exception as e:
        _fail("T6 import_smoke", f"import failed: {e}\n{traceback.format_exc()}")
        return False

    field_keys = {f[0] for f in ui.FIELDS}
    forbidden = {"streamer_name", "target_channel_id", "fmkorea_search_keywords"}
    leftover = forbidden & field_keys
    if leftover:
        _fail(
            "T6 import_smoke",
            f"streamer scalars must NOT be in FIELDS (managed by streamers section): {leftover}",
        )
        return False
    expected_min = {"poll_interval_sec", "download_resolution", "output_dir", "auto_cleanup"}
    missing = expected_min - field_keys
    if missing:
        _fail("T6 import_smoke", f"FIELDS missing required scalars: {missing}")
        return False
    if not hasattr(ui, "SettingsWindow"):
        _fail("T6 import_smoke", "SettingsWindow class missing")
        return False
    if not hasattr(ui, "open_settings"):
        _fail("T6 import_smoke", "open_settings function missing")
        return False
    # Verify methods needed for streamers
    expected_methods = ("_add_streamer_row", "_remove_streamer_row", "_collect_streamers", "_load_values", "_collect_values")
    for m in expected_methods:
        if not hasattr(ui.SettingsWindow, m):
            _fail("T6 import_smoke", f"SettingsWindow missing method: {m}")
            return False

    if not ui.SettingsWindow._is_valid_channel_id("a" * 32):
        _fail("T6 import_smoke", "valid 32-hex channel_id rejected")
        return False
    if ui.SettingsWindow._is_valid_channel_id("g" * 32):
        _fail("T6 import_smoke", "non-hex 32-char channel_id accepted")
        return False

    _ok("T6 import_smoke -- module imports, FIELDS clean, SettingsWindow methods present")
    return True


def t7_live_ui_roundtrip() -> bool:
    """End-to-end test using a real (withdrawn) Tk root.

    Skips gracefully if tkinter cannot create a display (CI/headless Linux).
    """
    try:
        import tkinter as tk
    except Exception as e:
        _print(f"[SKIP] T7 live_ui_roundtrip -- tkinter not available: {e}")
        return True

    try:
        root = tk.Tk()
        root.withdraw()
    except Exception as e:
        _print(f"[SKIP] T7 live_ui_roundtrip -- Tk() failed (likely no display): {e}")
        return True

    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cfg_path = tmp_path / "pipeline_config.json"

            # Patch _config_path to use a temp file
            with mock.patch("pipeline.config._config_path", return_value=cfg_path):
                # ---- T7a: legacy fixture → 1 row, modify → save → reload as 1 row ----
                legacy = {
                    "target_channel_id": "a" * 32,
                    "streamer_name": "탬탬",
                    "fmkorea_search_keywords": ["탬탬"],
                    "poll_interval_sec": 300,
                    "download_resolution": 144,
                    "bootstrap_mode": None,
                    "bootstrap_latest_n": 1,
                    "fmkorea_enabled": True,
                    "fmkorea_max_pages": 3,
                    "fmkorea_max_posts": 20,
                    "chunk_max_chars": 8000,
                    "chunk_overlap_sec": 30,
                    "claude_timeout_sec": 300,
                    "output_dir": "./output",
                    "work_dir": "./work",
                    "auto_cleanup": True,
                    "cookies": {"NID_AUT": "x", "NID_SES": "y"},
                }
                cfg_path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

                from pipeline.settings_ui import SettingsWindow

                win = SettingsWindow(parent=root)

                if len(win.streamer_rows) != 1:
                    _fail("T7a legacy_load_ui", f"expected 1 row, got {len(win.streamer_rows)}")
                    win.root.destroy()
                    root.destroy()
                    return False
                row0 = win.streamer_rows[0]
                if row0["channel_id"].get() != "a" * 32:
                    _fail("T7a legacy_load_ui", f"channel_id Entry not populated: {row0['channel_id'].get()!r}")
                    win.root.destroy()
                    root.destroy()
                    return False
                if row0["name"].get() != "탬탬":
                    _fail("T7a legacy_load_ui", f"name Entry not populated: {row0['name'].get()!r}")
                    win.root.destroy()
                    root.destroy()
                    return False

                # Programmatically add a 2nd streamer row
                win._add_streamer_row({"channel_id": "b" * 32, "name": "스트리머B", "search_keywords": ["kwB"]})
                if len(win.streamer_rows) != 2:
                    _fail("T7a legacy_load_ui", f"add row failed: {len(win.streamer_rows)}")
                    win.root.destroy()
                    root.destroy()
                    return False

                # Collect and verify save payload
                payload = win._collect_values()
                if payload is None:
                    _fail("T7a legacy_load_ui", "_collect_values returned None")
                    win.root.destroy()
                    root.destroy()
                    return False
                if len(payload["streamers"]) != 2:
                    _fail("T7a legacy_load_ui", f"payload streamers wrong count: {payload['streamers']}")
                    win.root.destroy()
                    root.destroy()
                    return False
                if payload["target_channel_id"] != "a" * 32:
                    _fail(
                        "T7a legacy_load_ui",
                        f"legacy mirror wrong: {payload['target_channel_id']!r}",
                    )
                    win.root.destroy()
                    root.destroy()
                    return False
                if payload["streamer_name"] != "탬탬":
                    _fail("T7a legacy_load_ui", f"streamer_name mirror wrong: {payload['streamer_name']!r}")
                    win.root.destroy()
                    root.destroy()
                    return False
                if payload["fmkorea_search_keywords"] != ["탬탬"]:
                    _fail(
                        "T7a legacy_load_ui",
                        f"keywords mirror wrong: {payload['fmkorea_search_keywords']}",
                    )
                    win.root.destroy()
                    root.destroy()
                    return False

                # Save and re-load
                win._save = win._save  # no patch
                from pipeline.config import save_config, load_config, normalize_streamers
                save_config(payload)
                reloaded = load_config()
                rebuilt = normalize_streamers(reloaded)
                if len(rebuilt) != 2:
                    _fail("T7a legacy_load_ui", f"reload streamers wrong count: {rebuilt}")
                    win.root.destroy()
                    root.destroy()
                    return False
                if rebuilt[1]["channel_id"] != "b" * 32:
                    _fail("T7a legacy_load_ui", f"reload row 1 wrong: {rebuilt[1]}")
                    win.root.destroy()
                    root.destroy()
                    return False
                win.root.destroy()

                # ---- T7b: multi-streamer fixture → N rows, delete row → save ----
                multi = {
                    "streamers": [
                        {"channel_id": "1" * 32, "name": "S1", "search_keywords": ["k1"]},
                        {"channel_id": "2" * 32, "name": "S2", "search_keywords": ["k2"]},
                        {"channel_id": "3" * 32, "name": "S3", "search_keywords": ["k3"]},
                    ],
                    "poll_interval_sec": 300,
                    "download_resolution": 144,
                    "bootstrap_mode": None,
                    "bootstrap_latest_n": 1,
                    "fmkorea_enabled": True,
                    "fmkorea_max_pages": 3,
                    "fmkorea_max_posts": 20,
                    "chunk_max_chars": 8000,
                    "chunk_overlap_sec": 30,
                    "claude_timeout_sec": 300,
                    "output_dir": "./output",
                    "work_dir": "./work",
                    "auto_cleanup": True,
                    "cookies": {"NID_AUT": "", "NID_SES": ""},
                }
                cfg_path.write_text(json.dumps(multi, ensure_ascii=False), encoding="utf-8")

                win2 = SettingsWindow(parent=root)
                if len(win2.streamer_rows) != 3:
                    _fail("T7b multi_load_ui", f"expected 3 rows, got {len(win2.streamer_rows)}")
                    win2.root.destroy()
                    root.destroy()
                    return False

                # Delete middle row programmatically
                middle_row = win2.streamer_rows[1]
                win2._remove_streamer_row(middle_row)
                if len(win2.streamer_rows) != 2:
                    _fail("T7b multi_load_ui", f"after delete expected 2 rows, got {len(win2.streamer_rows)}")
                    win2.root.destroy()
                    root.destroy()
                    return False
                if win2.streamer_rows[0]["channel_id"].get() != "1" * 32:
                    _fail("T7b multi_load_ui", "row 0 wrong after delete")
                    win2.root.destroy()
                    root.destroy()
                    return False
                if win2.streamer_rows[1]["channel_id"].get() != "3" * 32:
                    _fail("T7b multi_load_ui", "row 1 wrong after delete")
                    win2.root.destroy()
                    root.destroy()
                    return False

                payload2 = win2._collect_values()
                if payload2 is None:
                    _fail("T7b multi_load_ui", "_collect_values returned None")
                    win2.root.destroy()
                    root.destroy()
                    return False
                if [s["name"] for s in payload2["streamers"]] != ["S1", "S3"]:
                    _fail("T7b multi_load_ui", f"streamers names wrong after delete: {payload2['streamers']}")
                    win2.root.destroy()
                    root.destroy()
                    return False
                save_config(payload2)
                rebuilt2 = normalize_streamers(load_config())
                if [s["name"] for s in rebuilt2] != ["S1", "S3"]:
                    _fail("T7b multi_load_ui", f"reload streamers wrong: {rebuilt2}")
                    win2.root.destroy()
                    root.destroy()
                    return False
                win2.root.destroy()

                _ok("T7 live_ui_roundtrip -- legacy & multi-streamer load/add/delete/save round-trips PASS")
                return True
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    tests = [
        ("T1 legacy_load", t1_legacy_load),
        ("T2 multi_load", t2_multi_load),
        ("T3 save_policy", t3_save_policy),
        ("T4 roundtrip", t4_roundtrip),
        ("T5 empty_streamers_fallback", t5_empty_streamers_fallback),
        ("T6 import_smoke", t6_import_smoke),
        ("T7 live_ui_roundtrip", t7_live_ui_roundtrip),
    ]
    failures = 0
    for name, fn in tests:
        try:
            ok = fn()
        except Exception as e:
            _fail(name, f"unhandled exception: {e}\n{traceback.format_exc()}")
            ok = False
        if not ok:
            failures += 1

    _print("")
    if failures:
        _print(f"=== {failures} test(s) FAILED ===")
        return 1
    _print(f"=== all {len(tests)} tests PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
