# renchengsong.github.io

个人主页。**所有内容都在 `data/` 里，HTML 是生成出来的，不要直接改 HTML。**

```
data/                 ← 唯一需要你动的地方
  profile.yml         简介、职务、方向定义、基金、教学、News
  publications.json   论文总库（谷歌学术会往里加新论文）
  overrides.json      人工修正，优先级最高，抓取永远不会覆盖
  patents.json  conferences.json  students.json
templates/            页面模板（Jinja2）
assets/css/style.css  样式
scripts/
  build.py            data → HTML
  fetch_scholar.py    抓谷歌学术、去重、合并
  classify.py         把新论文归到三个方向之一
  migrate_legacy.py   一次性迁移脚本（已跑完，留作存档）
index.html  publications.html  students.html  sitemap.xml   ← 生成物
pdfs/ pic/ papers/    你原来的三个文件夹，原样保留
```

## 一次性配置（约 10 分钟）

1. 把本目录内容覆盖到仓库根目录，保留你原有的 `pdfs/ pic/ papers/`。
2. 仓库 **Settings → Actions → General → Workflow permissions**，选 *Read and write permissions*，
   并勾选 *Allow GitHub Actions to create and approve pull requests*。
3. **Settings → Secrets and variables → Actions → New repository secret**，加两个：

   | 名称 | 用途 | 怎么拿 |
   |---|---|---|
   | `SERPAPI_KEY` | 抓谷歌学术（推荐） | serpapi.com 注册，免费额度每月上百次，这里每月只用 1 次 |
   | `DEEPSEEK_API_KEY` | 少数拿不准的论文交给大模型归类 | platform.deepseek.com，一次分类不到一分钱 |

   两个都可以不填：不填 `SERPAPI_KEY` 会退回免费的 `scholarly` 直连（GitHub 机房 IP 有时会被谷歌拦，
   拦了就在 Actions 页面手动重跑）；不填 `DEEPSEEK_API_KEY` 时，拿不准的论文按关键词最高分归类并标 `check`。
4. 到 **Actions** 页面手动跑一次 *Sync Google Scholar*，确认能出 PR。

## 日常怎么用

**每月 1 号早上**：Actions 自动抓谷歌学术 → 新论文自动归类 → 开一个 PR，标题写"新增 N 篇"。
你在手机上点开 PR 看一眼分类对不对，对就 Merge，页面几十秒后自动更新。

**分类改错了**：直接在 PR 里改 `data/publications.json` 那一行的 `"category"`（`vision` / `hmi` / `em`）。
想永久钉死某篇，写进 `data/overrides.json`：

```json
{
  "song2023uncertainty": { "category": "vision", "selected": true, "corresponding": true },
  "someid2024xxx":       { "hidden": true }
}
```

**想让某篇上首页**：把它的 `"selected"` 改成 `true`。

**挂 PDF**：文件放 `papers/`，然后在这篇论文里写 `"pdf": "papers/xxx.pdf"`。

**改简介 / 加基金 / 加 News / 换照片**：只改 `data/profile.yml`。

**本地预览**：

```bash
pip install -r requirements.txt
python3 scripts/build.py
python3 -m http.server 8000     # 浏览器打开 http://localhost:8000
```

## 分类规则

`scripts/classify.py` 里是三个方向的关键词表（权重 3 = 强特征，1 = 弱线索），
期刊名只作为很弱的先验，避免 IEEE TIM 把所有论文都吸到一个方向去。
分数够高且第一名领先第二名 2 分以上就直接定，否则才调大模型。

拿现有 69 篇论文回测，规则单独就能 100% 复现原来的人工分类，其中 5 篇会转给大模型确认。
以后出现新方向的论文，往关键词表里补几个词就行，改完跑 `python3 scripts/classify.py --selftest` 自检。
