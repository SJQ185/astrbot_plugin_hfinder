"""找本子 / 找里番 的核心（不依赖 AstrBot，单独能测）。

入口在 finder.py：doujin_search / doujin_source / hanime_search / hanime_source。
"""

from .settings import FindError, Settings

__all__ = ["FindError", "Settings"]
