import pytest


@pytest.fixture(autouse=True)
def _no_local_models(monkeypatch):
    """Los tests nunca cargan Whisper ni OmniParser reales (GBs, GPU): se inyectan dobles donde hace falta."""
    from core import stt_local
    from perception import omniparser
    monkeypatch.setattr(stt_local, "available", lambda: False)
    monkeypatch.setattr(omniparser, "available", lambda: False)
