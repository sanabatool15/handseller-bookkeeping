from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(_wire_fakes):
    with TestClient(app) as c:
        yield c
