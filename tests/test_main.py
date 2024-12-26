# /tests/test_main.py

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import query_and_add_course, load_config
import pytest


@pytest.fixture
def mock_request_post(mocker):
    # 模拟 HTTP 请求响应
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "list": {
                "rows": [
                    {
                        "numberOfSelected": 5,
                        "classCapacity": 10,
                        "JXBID": "12345",
                        "secretVal": "secret",
                    }
                ]
            }
        }
    }
    mocker.patch("requests.post", return_value=mock_response)


def test_query_and_add_course(mock_request_post):
    # 测试 query_and_add_course 函数
    global config
    config = {"selected_courses": {}}
    course = {"KCH": "08305014", "JSH": "1005"}
    result = query_and_add_course(course)
    assert result is True


def test_load_config(tmp_path):
    # 创建临时配置文件
    config_content = """
    [default]
    key = "value"
    """
    config_file = tmp_path / "config.toml"
    config_file.write_text(config_content)

    # 加载配置文件
    config = load_config(str(config_file))
    assert config is not None
    assert "default" in config
    assert config["default"]["key"] == "value"


def test_query_and_add_course(mock_request_post):
    # 测试 query_and_add_course 函数
    course = {"KCH": "08305014", "JSH": "1005"}
    result = query_and_add_course(course)
    assert result is True
