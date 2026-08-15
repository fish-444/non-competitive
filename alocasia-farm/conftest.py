"""테스트 공통 준비.

main 은 FARM_DB / PHOTO_DIR 을 **부를 때마다** 읽는다(get_db_path / get_photo_dir).
덕분에 모듈을 다시 읽어도 옛 값이 살아남지 않지만, 대신 어떤 테스트 파일이 최상단
에서 환경변수를 바꿔 두면 그 뒤에 도는 **모든** 파일에 새어 나간다 — 저장을 안
해야 할 테스트가 파일을 쓰고 photos/ 를 만들어 버린다.

그래서 매 테스트 앞에서 '아무것도 남기지 않는다'로 되돌린다. 다르게 써야 하는
파일(test_persist, test_photos)은 자기 모듈에 autouse 픽스처를 두어 덮어쓴다 —
모듈 픽스처가 conftest 픽스처보다 나중에 돌아 이긴다.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _leave_no_files_behind():
    os.environ["FARM_DB"] = ""
    os.environ["PHOTO_DIR"] = ""
    yield
