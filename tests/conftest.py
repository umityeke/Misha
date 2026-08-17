from __future__ import annotations

import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from tests.fakes import (
    FakeAudioBackend,
    FakeProvider,
    FakeToolRegistry,
    FrozenClock,
    NetworkFixture,
)


@pytest.fixture
def fake_provider():
    return FakeProvider


@pytest.fixture
def fake_audio_device():
    return FakeAudioBackend()


@pytest.fixture
def fake_tool_registry():
    return FakeToolRegistry()


@pytest.fixture
def frozen_clock():
    return FrozenClock()


@pytest.fixture
def network_fixture():
    return NetworkFixture()


@pytest.fixture
def temporary_encrypted_store(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "private-data"
    monkeypatch.setenv("MISHA_DATA_DIR", str(data_dir))
    return {"path": data_dir, "cipher": Fernet(Fernet.generate_key())}
