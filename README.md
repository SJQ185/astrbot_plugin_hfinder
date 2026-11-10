<div align="center">

# 找本子 · 找里番

**AstrBot 插件：按标签搜本子 / 里番，或者丢一张图找出处**

![AstrBot](https://img.shields.io/badge/AstrBot-v4.28.2%20%E5%AE%9E%E6%B5%8B-blue)
![Python](https://img.shields.io/badge/Python-%E2%89%A53.10-3776AB)
![License](https://img.shields.io/badge/License-MIT-green)
![18+](https://img.shields.io/badge/内容-18%2B-red)

</div>

> 一个给 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 机器人用的成人向搜索插件。只搜索、只回资料和链接，不下载、不转存任何内容。**仅限已满 18 岁的人使用。**
>
> An AstrBot plugin that searches doujinshi (E-Hentai / nhentai) and hentai anime (hanime1 / AniList), and finds the source of a page or screenshot (soutubot / SauceNAO / trace.moe). 18+ only. Chinese UI.

## 能做什么

| 指令 | 干什么 | 用到的站 |
|---|---|---|
| `/找本子 关键词或标签` | 搜本子，回本子名、语言、页数、评分、链接，再发一张带序号的封面拼图 | E-Hentai / ExHentai + nhentai，同一本自动合并 |
| `/本子出处` | 一张内页 / 残页 / 截图 → 哪一本、第几页 | soutubot → E 站以图搜本 → SauceNAO |
| `/找里番 标签或片名` | 搜里番，回片名、有没有中文字幕、时长、播放页链接 + 封面拼图 | hanime1（连不上时退到 AniList 查资料） |
| `/里番出处` | 一张截图或一小段视频 → 哪部、第几集、第几分钟；是里番还附播放页 | trace.moe（+ SauceNAO） |
| `/找片帮助` | 用法和当前配置 | |

同样四件事也注册成了**给模型调用的工具**（`doujin_search` / `doujin_find_source` / `hanime_search` / `hanime_find_source`）。机器人配好对话模型以后，直接说「帮我找几本女仆的本子」「这张截图是哪部番」就行，不用记指令。

## 效果

```
你：/找本子 女仆 中文
机器人：在 E 站和 N 站上找，E 站要求慢慢翻，十几秒……
机器人：找本子 · 女仆 中文
#1 [社团名 (作者)] 本子名 [中国翻訳]
    E-Hentai · 中文 · 32P · ★4.6 · https://e-hentai.org/g/xxxxxxx/xxxxxxxxxx/
    N 站同一本：https://nhentai.net/g/xxxxxx/
#2 ……
（没列出来的：涉及未成年 3 本（内置红线，不能关）；还有下一页（第 2 页））
[一张带 #1 #2 … 序号的封面拼图]

你：（回复一张动画截图）/里番出处
机器人：截图出处（≥90% 基本就是它，87%~90% 只是画面像）：
#1 片名（罗马音）
    97% · 第 2 集 12:31–12:35 · https://anilist.co/anime/xxxxx
    hanime1：片名 2（中文字幕）https://hanime1.me/watch?v=xxxxxx
（trace.moe 今天还剩 97 次）
```

## 安装

**方法一（推荐）**：到 [Releases](../../releases) 下载 `astrbot_plugin_hfinder.zip`，在 AstrBot 网页后台 →「插件」→「从文件安装」选它。

**方法二**：

```bash
cd AstrBot/data/plugins
git clone https://github.com/SJQ185/astrbot_plugin_hfinder.git
```

然后重启 AstrBot，或者在后台「插件」里重载。

依赖只有 Pillow 和 websockets，AstrBot 官方 Docker 镜像里都已经装好。截视频找出处要 ffmpeg，官方镜像也有。

在 AstrBot v4.28.2 上实测过（QQ / OneBot 接入）。其他 4.x 版本应该也能用，遇到问题欢迎提 Issue。

装好以后**默认只在私聊里能用**。要在群里用，到「插件配置」里打开「群里可以用」，建议同时填上群白名单。

> ⚠️ **QQ 风控**：封面拼图里是本子 / 里番的封面缩略图，在 QQ 这类平台上可能被判成违规图片，轻则发不出去，重则机器人账号被限制。在乎账号的话，到配置里关掉「发封面拼图」，只回文字和链接。

## 用法

```
/找本子 女仆 中文
/找本子 热门                 排行榜：热门 / 日榜 / 月榜 / 年榜 / 总榜
/找本子 月榜 精灵             在排行榜上筛标签
/找本子 female:maid 第2页     E 站标签直接写也行
/本子出处                    发图时带上这句，或者回复那张图再发

/找里番 女仆
/找里番 3D 本周              分区：里番 泡面番 动态漫画 3D 2.5D 2D动画 AI MMD 全部
                            排序：最新 本周 本月 今日 好评 热门 最长
/找里番 巫女 -NTR            前面加减号 = 不要这个标签
/找里番 某个片名              认不出的词当片名搜
/里番出处                    发截图 / 短视频时带上，或者回复它
```

中文常用词（女仆、修女、精灵、丝袜、中文……）会自动换成各站的标签；认不出的标签会提示相近的写法。

## 配置

全部在 AstrBot 后台「插件配置」里填，**都可以不填**。

| 配置项 | 不填会怎样 | 填了有什么用 |
|---|---|---|
| 私聊 / 群里可以用、群白名单 | 只有私聊能用 | 控制在哪些聊天里能用 |
| 让模型自己调用 | 默认开 | 关掉就只能用指令 |
| E 站 cookie：`ipb_member_id`、`ipb_pass_hash`、`igneous` | 走表站 e-hentai.org | 三个都填就走里站 exhentai.org，结果更全。浏览器登录 E 站后，在开发者工具 → 应用 → Cookie 里复制 |
| SauceNAO API key | 出处少一个后备引擎 | 压缩过的本子页、动画截图没把握时多问一次。到 [saucenao.com](https://saucenao.com/user.php) 免费注册 |
| 浏览器远程调试地址 | soutubot 用不了；hanime1 被拦时改查 AniList | 见下一节 |
| 代理 | 用系统环境变量里的代理，没有就直连 | 例：`http://127.0.0.1:7890` |
| 不想看的标签 / 词 | | 命中的不列出来。例：`male:yaoi`、`NTR`，或者某个作者名 |
| 一次最多列几条 | 8 | 1~15 |
| 本子优先语言 | 中文 | 中文 / 日文 / 英文 / 韩文 |
| 发封面拼图 | 发 | 关掉只回文字和链接（在乎 QQ 风控的建议关） |

### 浏览器（可选，但很有用）

**soutubot**（残页、截图找本子目前最准的）和 **hanime1** 前面都挡着 Cloudflare，服务器 IP 直接访问经常被拦。插件的办法是借一个真浏览器：在浏览器里打开站点首页，再在页面里发和站点自己网页一样的请求。

1. 在能被 AstrBot 访问到的机器上，用远程调试口启动一个 Chrome / Chromium（用单独的用户目录）：

   ```bash
   chrome --remote-debugging-port=9222 --user-data-dir=/path/to/hfinder-profile
   ```

2. 插件配置「浏览器远程调试地址」填 `http://127.0.0.1:9222`。
   - AstrBot 和 Chrome 在同一台机器上：直接填 `127.0.0.1`。
   - AstrBot 在 Docker 里、Chrome 在宿主机上：Chrome 的调试口只监听本机，容器里连不到。可以让 AstrBot 用 host 网络模式（`network_mode: host`），或者在宿主机上用 socat 之类把 9222 转发到容器能访问的地址，再填那个地址。
3. 站点弹出人机验证时，插件会停下来提示你。**由你自己在那个浏览器里点一下验证**，再搜一次就行。

插件**不会**自动点验证、不改浏览器指纹、不接打码服务。没有浏览器也能用：soutubot 那一步跳过，并提示你去 soutubot.moe 网页上手动上传；hanime1 被拦时改用 AniList 查片名，每部附一个 hanime1 搜索链接让你自己点开。

## 内置筛选（关不掉）

**涉及未成年的成人内容一律不搜、不列、不报出处**，配置里没有开关：

- 搜索词里有萝莉、正太、JK、学生、校服、school、loli 这类词：直接不搜。
- 结果的标签、标题、简介、原作名碰到：不列出来，只说「有几条碰到筛选没列」，不说是什么。
- 成人内容核不了标签的（站点没给标签）：先不列，宁可漏，不放过。

学生 / 校园题材也算在内，因为高中生是未成年；「大学生」不算。名单在 [`hfinder/redline.py`](hfinder/redline.py)。

这是按标签和关键词判断的一道基础防线，不是人工审核，可能拦多，也可能漏。发现漏网的，欢迎提 Issue 补词。**不接受放宽这条的 PR。**

## 工作原理

- **找本子**：E 站搜索（搜索词后面拼上排除条件）→ 取每本的资料（gdata）→ 按标签和标题再过一遍筛选；同时搜 nhentai 新接口（`/api/v2`）；标题相似的并成一条。
- **本子出处**：soutubot（局部特征匹配，能定位到第几页）→ E 站以图搜本（只认得整页原图）→ SauceNAO 认出本子名，再回 E 站按名字找。soutubot 只给标题和链接，插件会回 N 站 / E 站取标签核一遍，核不了的不列。
- **找里番**：hanime1 搜索页 → 每部都打开播放页核一遍标签（播放页资料缓存 3 天）→ 过筛选；站被拦时退到 AniList GraphQL。
- **里番出处**：图片直接查 trace.moe；视频 / GIF 用 ffmpeg 均匀抽几帧分别查，按「哪部 + 第几集」投票；没有 90% 以上的结果再问 SauceNAO 的动画库；对上的是里番，就去 hanime1 找那一集的播放页。

请求节奏照各站的规矩来：E 站两次请求至少隔 3 秒，hanime1 同一时间只排一个队。所以一次搜索要十几秒，属于正常现象。

## 常见问题

**找里番总是变成「AniList（只有资料）」？**
hanime1 把你服务器的 IP 拦了。配一个浏览器（见上面），或者给插件配一个能正常打开 hanime1 的代理。

**提示「弹了 Cloudflare 人机验证」？**
去你配置的那个浏览器里打开提示的网址，点一下验证，再搜一次。

**提示「里站（exhentai）没登录进去」？**
E 站 cookie 过期了，重新从浏览器里复制三个值填进去。

**trace.moe / SauceNAO / soutubot 说次数用完了？**
它们都有每日免费次数（trace.moe 免登录每 24 小时 100 次，按出口 IP 算），第二天恢复。

**soutubot 说「当前搜索任务较多」？**
它那边正忙，过半分钟再试。

**封面拼图发不出去，或者机器人被 QQ 警告？**
拼图里是成人封面，容易触发平台的图片审核。到配置里关掉「发封面拼图」。

**群里发指令没反应？**
默认只开私聊。去插件配置里打开「群里可以用」。

**能不能顺便下载？**
不做。这个插件只负责找。

## 开发

核心逻辑在 `hfinder/`，不依赖 AstrBot，可以单独测试；`main.py` 只是 AstrBot 的外壳（指令、工具、配置）。

```
hfinder/
  finder.py      四个入口：doujin_search / doujin_source / hanime_search / hanime_source
  redline.py     内置筛选 + 使用者的「不想看」
  ehentai.py  nhentai.py  soutubot.py  hanime1.py  anime.py（trace.moe / SauceNAO / AniList）
  net.py         请求、代理、借浏览器（CDP）
  grid.py        封面拼图
tests/
  test_core.py   离线单测
  live_smoke.py  连真站点的冒烟测试（只打印条数和站点）
```

```bash
python -m unittest discover -s tests
python tests/live_smoke.py book h
```

## 致谢

数据都来自这些站点和服务的公开页面 / 接口：E-Hentai、nhentai、[soutubot](https://soutubot.moe)、hanime1、[trace.moe](https://trace.moe)、[AniList](https://anilist.co)、[SauceNAO](https://saucenao.com)。插件跑在 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 上。请合理使用，别给这些站点添麻烦。

## 免责声明

- 只给已满 18 岁、且所在地法律允许的人使用。
- 插件不下载、不存放本子页和视频，只把公开网站的搜索结果整理成文字和链接。封面拼图用的是站点公开的缩略图，插件本地只留最近 30 张拼图。
- 链接打开以后看到什么、怎么用，由使用者自己负责。站点改版可能让某一部分暂时失效。

## 许可证

[MIT](LICENSE)
