"""アプリ横断で使う権限判定。

user_passes_test / UserPassesTestMixin に渡す述語をここに集める。
"""


def is_superuser(user):
    """管理者権限チェック"""
    return user.is_superuser
