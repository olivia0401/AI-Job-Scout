# AI Job Scout — 全量工签雇主 AI/LLM 岗位雷达

扫描**全部** Skilled Worker 工签雇主（官方 sponsor register，12 万+ 家）的在招 AI / ML / LLM 岗位，
精选科技公司单独标 ⭐，岗位按首次发现时间排序，自动标记 NEW / 长期在招 / ⭐LLM。

## 启动

```
cd AI-Job-Scout
python app.py
```

浏览器打开 **http://127.0.0.1:5050**。依赖：`flask`、`requests`、`openpyxl`。

## 三种扫描模式

| 按钮 | 干什么 | 耗时 |
|---|---|---|
| ⚡ 快速刷新 | 只重扫已探测到招聘系统的公司，抓最新岗位 | 几分钟 |
| 🌊 全量清查 | 探测所有还没查过的 register 雇主（可随时停止，续跑不重复） | 首次约 14 小时 |
| ⭐ 只扫精选 | 只扫精选科技公司 | ~4 分钟 |

全量清查只需要跑一次；之后日常用 ⚡ 快速刷新即可。设置里可开自动刷新（每 N 小时，需程序开着）。

## 岗位标记

- **NEW**：首次发现 ≤3 天（数据从第一次扫描开始积累）
- **长期在招**：持续在线 ≥30 天——说明岗位难招/长期开放，值得投
- **⭐LLM**：标题命中 LLM / GenAI / foundation model / agentic / RAG / NLP 等
- **⭐精选**：来自精选科技公司清单（与 register 其余公司可一键切换）

## 视图

- 🕒 **最新岗位流**：所有 AI 岗按上架时间排序，蹲新岗位用这个
- 🏢 **按公司看**：每家公司的岗位 + LinkedIn 招聘官搜索 / Hunter 查邮箱 / Google 直达链接

## 导入

- 📂 官方 register CSV（gov.uk 每周更新，填路径导入，自动取 Skilled Worker 路线并去重）
- 自己的清单（xlsx/csv/txt/粘贴）会标为 ⭐精选

## 附属脚本

`verify_sponsors.py`：把精选科技雇主清单与 register 交叉核验，输出 `verified_tech_sponsors.csv`。

## 说明与限制

- 岗位来自 Greenhouse / Lever / Ashby / Workable / SmartRecruiters / Recruitee 六大招聘系统的**公开接口**，无需 API key。
- 自研招聘系统的大厂（Google/Amazon/大银行等）探测不到，用公司卡片里的直达链接手动查。
- LinkedIn 禁止自动抓取，联系人部分是一键直达搜索链接，不是爬虫。
- 数据在 `data/` 目录：`companies.json`（公司名单）、`ats_cache.json`（探测缓存，全量清查的进度就存在这）、`state.json`（岗位与首见日期）。
