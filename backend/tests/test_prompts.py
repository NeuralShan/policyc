import pytest

from app.core.llm.prompts import ModelTier, PromptRegistry


def write(directory, name, body):
    (directory / name).write_text(body, encoding="utf-8")


def test_repository_prompts_load():
    smoke = PromptRegistry().get("smoke_test")
    assert smoke.tier == ModelTier.FLASH
    messages = smoke.render({"sentence": 'Use {"json": true} braces'})
    assert messages[0][0] == "system"
    assert 'Use {"json": true} braces' in messages[1][1]


def test_latest_version_wins_and_specific_versions_resolve(tmp_path):
    write(tmp_path, "p.v1.toml", 'id = "p"\nversion = 1\ntier = "pro"\nuser = "one"')
    write(tmp_path, "p.v2.toml", 'id = "p"\nversion = 2\ntier = "pro"\nuser = "two"')
    registry = PromptRegistry(tmp_path)
    assert registry.get("p").version == 2
    assert registry.get("p", 1).render() == [("human", "one")]
    assert registry.get("p", 1).content_hash != registry.get("p", 2).content_hash
    with pytest.raises(KeyError):
        registry.get("p", 3)
    with pytest.raises(KeyError):
        registry.get("nope")


@pytest.mark.parametrize(
    ("filename", "body"),
    [
        ("Bad-Name.toml", 'id = "x"\nversion = 1\ntier = "pro"\nuser = "u"'),
        ("x.v1.toml", 'id = "y"\nversion = 1\ntier = "pro"\nuser = "u"'),
        ("x.v1.toml", 'id = "x"\nversion = 1\ntier = "ultra"\nuser = "u"'),
    ],
)
def test_invalid_prompt_files_are_rejected(tmp_path, filename, body):
    write(tmp_path, filename, body)
    with pytest.raises(ValueError):
        PromptRegistry(tmp_path)
