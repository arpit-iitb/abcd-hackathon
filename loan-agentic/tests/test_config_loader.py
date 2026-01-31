from app.config import load_config_dir


def test_config_loader_required_keys():
    config = load_config_dir("configs")
    assert "policy" in config
    assert "thresholds" in config
    assert "suspicious_keywords" in config
    assert "roi" in config
