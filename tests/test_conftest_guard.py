"""テスト実行時に実 API キーが使われないことを保証する回帰テスト。

conftest.pytest_configure が setdefault に戻された場合、開発者の環境に設定された
実キーがテストプロセスへ流れ込む。モックの掛け忘れがあると実 API への通信と課金が
発生するため、ガードが効いていること自体をテストで固定する。
"""

import os

from conftest import DUMMY_OPENAI_API_KEY


def test_openai_api_key_is_dummy():
    """テストプロセスの OPENAI_API_KEY はダミー値で上書きされている。"""
    assert os.environ["OPENAI_API_KEY"] == DUMMY_OPENAI_API_KEY


def test_openai_api_key_is_not_a_real_key():
    """実キーの形式（sk-proj- / sk- 始まり）でないことを確認する。"""
    key = os.environ["OPENAI_API_KEY"]
    assert not key.startswith("sk-"), (
        "テストプロセスに実 API キーらしき値が設定されています。"
        "conftest.pytest_configure の上書きが効いているか確認してください。"
    )
