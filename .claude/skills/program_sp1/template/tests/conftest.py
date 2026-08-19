"""테스트 공통 준비.

config 는 환경변수를 **부를 때마다** 읽는다. 덕분에 모듈을 다시 읽어도 옛 값이
살아남지 않지만, 대신 어떤 테스트 파일이 최상단에서 환경변수를 바꿔 두면 그 뒤에
도는 **모든** 파일에 새어 나간다 — 저장을 안 해야 할 테스트가 파일을 쓴다.

그래서 매 테스트 앞에서 '아무것도 남기지 않는다'로 되돌린다. 저장을 실제로
확인해야 하는 파일은 자기 모듈에 autouse 픽스처를 두어 덮어쓴다(모듈 픽스처가
conftest 것보다 나중에 돌아 이긴다).

메모리 상태(app.ITEMS)도 매번 비운다. 안 그러면 앞 테스트가 남긴 항목 때문에
순서를 바꿀 때만 깨지는 테스트가 생긴다.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def clean_slate():
    os.environ["{{ENV}}_DB"] = ""
    os.environ["{{ENV}}_DATA"] = ""
    from backend import app
    app.ITEMS.clear()
    yield
    app.ITEMS.clear()
