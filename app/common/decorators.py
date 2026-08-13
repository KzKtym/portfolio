"""アプリ横断で使うビューデコレータ。"""
import functools

from django.views.decorators.cache import never_cache


def no_cache_no_index(view_func):
    """
    ブラウザキャッシュとクローラーによるインデックスを防ぐデコレータ。

    設定するレスポンスヘッダー:
      - Cache-Control: no-store, no-cache, must-revalidate, max-age=0
      - Pragma: no-cache
      - Expires: 0
      - X-Robots-Tag: noindex, nofollow
    """
    @never_cache
    @functools.wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        response = view_func(request, *args, **kwargs)
        response['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    return wrapped_view
