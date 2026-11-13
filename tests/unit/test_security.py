from app.core.security import generate_api_key, hash_key, parse_prefix


def test_generated_key_shape_and_hash():
    key, prefix, key_hash = generate_api_key()
    assert key.startswith(f"vs_{prefix}_")
    assert len(prefix) == 8
    assert key_hash == hash_key(key)
    assert key not in key_hash  # we never store the raw key


def test_keys_are_unique():
    assert generate_api_key()[0] != generate_api_key()[0]


def test_parse_prefix():
    key, prefix, _ = generate_api_key()
    assert parse_prefix(key) == prefix
    assert parse_prefix("nope") is None
    assert parse_prefix("xx_12345678_secret") is None
    assert parse_prefix("vs_short_secret") is None
    assert parse_prefix("vs_12345678_") is None
