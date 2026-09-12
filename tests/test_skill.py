from pathlib import Path

import yaml


def test_discoverable_skill_metadata():
    root = Path(__file__).resolve().parents[1] / "skills" / "stitch-a1-video"
    text = (root / "SKILL.md").read_text()
    assert text.startswith("---\n")
    metadata = yaml.safe_load(text.split("---", 2)[1])
    assert metadata["name"] == root.name
    assert isinstance(metadata["description"], str) and metadata["description"].strip()
    config = yaml.safe_load((root / "agents" / "openai.yaml").read_text())
    assert config["policy"]["allow_implicit_invocation"] is True
    assert "$" + metadata["name"] in config["interface"]["default_prompt"]
