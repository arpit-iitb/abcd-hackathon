from app.prompt_loader import load_prompts


def test_prompt_loader():
    prompts = load_prompts("prompts")
    assert "lead_sourcing" in prompts
    assert "system" in prompts["lead_sourcing"]
    assert "user_template" in prompts["lead_sourcing"]
