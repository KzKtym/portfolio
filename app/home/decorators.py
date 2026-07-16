# TODO: homeアプリを ./app/ 配下に移動する際に、
#       ./app/common/decorators.py 等へ移動・統合を検討すること。
#       その際、./app/download/views.py 側のデコレータ定義も統合すること。

import functools
from django.views.decorators.cache import never_cache
from django.views.decorators.http import condition


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
