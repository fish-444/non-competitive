"""화면 테스트 — 실제 브라우저를 띄운다.

파이썬 테스트는 화면을 못 본다. 변수 중복 선언 하나로 스크립트 전체가 죽어도,
CSS 가 글자를 가려도, 버튼이 아무 일도 안 해도 전부 통과한다. 그래서 눈에
보이는 것은 눈으로 확인한다.

    pip install playwright && playwright install chromium
"""

import os
import socket
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pytest.importorskip("playwright", reason="playwright 가 없으면 화면 테스트는 건너뛴다")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    """진짜 서버를 띄운다. 저장은 임시 경로로 돌려 원본을 안 건드린다."""
    import tempfile
    port = _free_port()
    env = {**os.environ,
           "{{ENV}}_DB": os.path.join(tempfile.mkdtemp(), "ui.db"),
           "{{ENV}}_DATA": ""}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app:app",
         "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, env=env)
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):                       # 뜰 때까지 기다린다
        try:
            with socket.create_connection(("127.0.0.1", port), 0.3):
                break
        except OSError:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("서버가 안 떴다")
    yield url
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture
def page(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        # 설치 방식에 따라 headless shell 이 없을 수 있다 — 그때는 건너뛴다.
        try:
            browser = pw.chromium.launch()
        except Exception as e:                # noqa: BLE001
            pytest.skip(f"크로미움을 못 띄웠다: {e}")
        pg = browser.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(server, wait_until="networkidle")
        yield pg, errors
        browser.close()


def test_the_page_loads_without_script_errors(page):
    """스크립트가 죽으면 화면은 멀쩡해 보여도 아무 버튼도 안 먹는다."""
    pg, errors = page
    assert errors == [], errors
    assert pg.title()


def test_adding_an_item_updates_the_list_and_the_counters(page):
    pg, errors = page
    pg.fill("#name", "브라우저에서 추가")
    pg.fill("#tags", "확인")
    pg.click("#add button")
    pg.wait_for_selector("text=브라우저에서 추가")
    assert "전체" in pg.inner_text("#sum")
    assert errors == [], errors


def test_checking_the_box_moves_it_to_done(page):
    pg, errors = page
    pg.fill("#name", "완료할 항목")
    pg.click("#add button")
    pg.wait_for_selector("#list input[type=checkbox]")
    pg.check("#list input[type=checkbox]")
    pg.wait_for_selector("#list li.done")
    assert errors == [], errors
