"""配置和报错。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class FindError(Exception):
    """直接给用户看的一句话（中文，说清楚哪一步没成、怎么办）。"""


class NeedVerify(FindError):
    """站点弹了 Cloudflare 人机验证：只能由人在浏览器里点，插件不绕。"""


@dataclass
class Settings:
    data_dir: Path
    eh_cookies: dict[str, str] = field(default_factory=dict)   # ipb_member_id / ipb_pass_hash / igneous（填全了走里站）
    saucenao_key: str = ""
    proxy: str = ""                 # 例：http://127.0.0.1:7890；空 = 用系统环境变量里的代理（没有就直连）
    browser_cdp: str = ""           # 例：http://127.0.0.1:9222；空 = 不用浏览器（soutubot 用不了，hanime1 被拦就退 AniList）
    block: list[str] = field(default_factory=list)              # 使用者自己不想看的标签 / 词
    limit: int = 8
    language: str = "chinese"       # 本子哪种语言排前面
    grid: bool = True               # 拼封面图

    @property
    def cache(self) -> Path:
        path = Path(self.data_dir) / "cache"
        path.mkdir(parents=True, exist_ok=True)
        return path
