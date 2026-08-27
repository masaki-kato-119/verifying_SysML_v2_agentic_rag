"""pytest 共通設定（import より前に API キーを用意）。"""

import os

# 単体テスト用のダミーキー。実在しない形式であることが一目で分かる値にしておく。
DUMMY_OPENAI_API_KEY = "test-openai-key-for-pytest"


def pytest_configure(config):
    """OPENAI_API_KEY を必ずダミー値で上書きする。

    setdefault ではなく上書きにしているのは、開発者の環境に実キーが設定されている
    場合にそれがテストプロセスへ流れ込むのを防ぐため。モックの掛け忘れが 1 箇所でも
    あると、実 API への通信と課金が無自覚に発生してしまう。

    ここを setdefault に戻すと、その防御が失われる（test_conftest_guard.py で検知する）。
    実 API を使う結合テストを追加する場合は、このフックを条件分岐させるのではなく、
    テスト側で明示的にキーを注入する方式にすること。
    """
    os.environ["OPENAI_API_KEY"] = DUMMY_OPENAI_API_KEY
