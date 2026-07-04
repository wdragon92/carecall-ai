"""테스트는 항상 MOCK_MODE 강제 (tests §12). 실제 키/네트워크에 의존하지 않음."""
import os

os.environ["MOCK_MODE"] = "true"
os.environ["CLOVA_STUDIO_API_KEY"] = ""
os.environ["NCP_APIGW_CLIENT_ID"] = ""
os.environ["NCP_APIGW_CLIENT_SECRET"] = ""
os.environ["CLOVA_OCR_INVOKE_URL"] = ""
os.environ["CLOVA_OCR_SECRET"] = ""

import pytest

from app.config import get_settings

get_settings.cache_clear()

from app.main import create_app  # noqa: E402


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    from starlette.testclient import TestClient

    with TestClient(app) as c:
        yield c
