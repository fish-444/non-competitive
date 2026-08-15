"""백업·복원 스모크 테스트 (네트워크 불필요)

실행:  python3 test_backup.py

farm.db 를 실수로 지워 기록을 통째로 잃은 적이 있다. 그때 되돌릴 방법이 없었다.
"""

import asyncio
import io
import json
import os
import tempfile

os.environ["FARM_DB"] = ""

from fastapi import HTTPException                    # noqa: E402

import main                                          # noqa: E402

# 사진 보관함은 끈다. main 이 부를 때마다 환경변수를 읽으므로 여기서 정하면 된다
# (모듈 속성을 덮어쓰던 방식은 get_photo_dir() 로 바뀌면서 더는 안 먹는다).
os.environ["PHOTO_DIR"] = ""


class _Upload:
    content_type = "application/json"

    def __init__(self, raw):
        self._raw = raw

    async def read(self):
        return self._raw


def _fill():
    """되살릴 거리를 만들어 둔다."""
    _wipe()
    main.PLANTS["p1"] = {"id": "p1", "name": "프라이덱", "pos": "A1", "x": 0, "z": 0,
                         "rot": 0, "leaf_count": 5, "water_log": ["2026-08-01"],
                         "growth_log": [{"on": "2026-08-01", "canopy_cm": 15.0}]}
    main.POTS.append({"slot": "A1", "u": 0.5, "v": 0.5})
    main.LEAVES["lf_1"] = {"leaf_id": "lf_1", "plant_id": "p1"}
    main.LEAF_FIXES.append({"u": 0.1, "v": 0.2, "pot_slot": "A1"})
    main.ENVIRONMENT["lights"] = [{"x": 1}]
    main.SCANS.append({"id": "sc_1", "rel": "2026-08/scan.jpg", "plants": 1})
    main.CALIB.update({"corners": [[0, 0], [1, 0], [1, 1], [0, 1]]})


def _wipe():
    main.PLANTS.clear(); main.POTS.clear(); main.LEAVES.clear()
    main.LEAF_FIXES.clear(); main.ENVIRONMENT.clear()
    main.SCANS.clear(); main.CALIB.clear()


def _round_trip():
    payload = main.backup_payload()
    _wipe()
    return main.restore_payload(json.loads(json.dumps(payload, ensure_ascii=False)))


# ── 무엇이 담기는가 ──────────────────────────────────────────────────────
def test_the_backup_carries_every_part_that_gets_saved():
    """save_state 가 저장하는 것과 같은 목록이어야 한다 — 한쪽에만 있으면 조용히 빠진다."""
    saved = {"plants", "pots", "leaves", "leaf_fixes", "env", "scans", "calib"}
    assert {k for k, _ in main.BACKUP_PARTS} == saved
    _wipe()


def test_everything_comes_back_after_a_round_trip():
    _fill()
    _round_trip()
    assert main.PLANTS["p1"]["name"] == "프라이덱"
    assert main.PLANTS["p1"]["water_log"] == ["2026-08-01"]
    assert main.PLANTS["p1"]["growth_log"][0]["canopy_cm"] == 15.0
    assert main.POTS[0]["slot"] == "A1"
    assert main.LEAVES["lf_1"]["plant_id"] == "p1"
    assert main.LEAF_FIXES[0]["pot_slot"] == "A1"
    assert main.ENVIRONMENT["lights"] == [{"x": 1}]
    assert main.SCANS[0]["id"] == "sc_1"
    assert main.CALIB["corners"][2] == [1, 1]
    _wipe()


def test_restoring_replaces_rather_than_merges():
    """예전 기록이 남아 섞이면 안 된다 — 백업 시점 그대로여야 한다."""
    _fill()
    payload = main.backup_payload()
    payload = json.loads(json.dumps(payload, ensure_ascii=False))
    main.PLANTS["p2"] = {"id": "p2", "name": "나중에 심은 것", "pos": "A2"}
    main.restore_payload(payload)
    assert list(main.PLANTS) == ["p1"], list(main.PLANTS)
    _wipe()


def test_the_file_says_photos_are_not_inside():
    """사진은 용량 때문에 안 담는다 — 파일만 보고도 알 수 있어야 한다."""
    _fill()
    assert "photos" in main.backup_payload()["note"]
    _wipe()


def test_counts_are_reported_so_you_can_sanity_check():
    _fill()
    assert main.backup_payload()["counts"]["plants"] == 1
    _wipe()


# ── 잘못된 파일 ──────────────────────────────────────────────────────────
def test_some_other_json_is_refused():
    _fill()
    for bad in ({"hello": "world"}, {"kind": "다른앱", "state": {}}, [], "문자열"):
        try:
            main.restore_payload(bad)
        except HTTPException as e:
            assert e.status_code == 400
        else:
            raise AssertionError(f"거부해야 한다: {bad}")
    assert main.PLANTS, "거부했으면 지금 기록은 그대로여야 한다"
    _wipe()


def test_a_backup_without_state_is_refused():
    try:
        main.restore_payload({"kind": "alocasia-farm-backup", "version": 1})
    except HTTPException as e:
        assert e.status_code == 400 and "state" in e.detail
    else:
        raise AssertionError("state 없는 파일은 거부해야 한다")
    _wipe()


def test_a_part_with_the_wrong_shape_is_refused():
    """plants 가 목록으로 와 있으면 넣는 순간 깨진다 — 먼저 막는다."""
    _fill()
    try:
        main.restore_payload({"kind": "alocasia-farm-backup", "version": 1,
                              "state": {"plants": ["이건 목록"]}})
    except HTTPException as e:
        assert e.status_code == 400 and "plants" in e.detail
    else:
        raise AssertionError("모양이 다른 부분은 거부해야 한다")
    assert main.PLANTS, "거부했으면 지금 기록은 그대로여야 한다"
    _wipe()


def test_broken_json_is_refused():
    try:
        asyncio.run(main.upload_backup(file=_Upload(b"{\xea\xb9\xa8\xec\xa1\x8c")))
    except HTTPException as e:
        assert e.status_code == 400
    else:
        raise AssertionError("깨진 JSON 은 거부해야 한다")
    _wipe()


def test_a_missing_part_just_comes_back_empty():
    """옛 버전 백업에 없는 항목이 있어도 복원 자체는 되어야 한다."""
    _fill()
    main.restore_payload({"kind": "alocasia-farm-backup", "version": 1,
                          "state": {"plants": {"x": {"id": "x", "name": "하나만"}}}})
    assert list(main.PLANTS) == ["x"] and main.POTS == [] and main.SCANS == []
    _wipe()


# ── 되돌릴 길 ────────────────────────────────────────────────────────────
def test_the_state_before_a_restore_is_written_to_a_file():
    """잘못된 파일로 복원해도 되돌릴 수 있어야 한다."""
    cwd = os.getcwd()
    try:
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            _fill()
            out = main.restore_payload({"kind": "alocasia-farm-backup", "version": 1,
                                        "state": {"plants": {}}})
            path = out["previous_saved_to"]
            assert path and os.path.exists(path), out
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
            assert saved["state"]["plants"]["p1"]["name"] == "프라이덱"
    finally:
        os.chdir(cwd)
        _wipe()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ✔ {t.__name__}")
    print(f"\n{len(tests)}개 통과")
