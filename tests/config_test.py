# tests/config_test.py

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import toml
from main import load_config


def test_load_config_success(tmp_path):
    # 模拟配置文件内容
    config_data = {"key1": "value1", "key2": "value2"}
    config_file = tmp_path / "temp_config.toml"
    with open(config_file, "w", encoding="utf-8") as file:
        toml.dump(config_data, file)

    # 调用 load_config 方法，并断言结果
    result = load_config(str(config_file))
    assert result == config_data


def test_load_config_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_config("nonexistent_file.toml")


def test_load_config_invalid_format(tmp_path):
    # 模拟格式错误的配置文件
    invalid_config_data = "invalid_toml_data"
    invalid_config_file = tmp_path / "invalid_config.toml"
    invalid_config_file.write_text(invalid_config_data)

    with pytest.raises(toml.TomlDecodeError):
        load_config(str(invalid_config_file))
