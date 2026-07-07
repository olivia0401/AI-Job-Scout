# AI Job Scout — 英国工签雇主岗位雷达

**一句话：** 它会自动去「持有英国 Skilled Worker 工签资质的雇主」的官方招聘系统里，
把他们正在招的岗位一次性抓出来，按新鲜度排好，还能上传你的简历自动算匹配度、给优化建议。

> 默认找的是 **AI / 机器学习**岗位，但**换几个关键词就能找任何行业的岗位**（护士、会计、市场、工程师……见下）。
> 好处：这些公司都**有工签担保资质**，投递前不用再一家家查能不能 sponsor。

---

## 🚀 第一次使用（不需要懂编程，照做即可）

### 1. 装 Python
去 https://www.python.org/downloads/ 下载安装，**安装时勾选 “Add Python to PATH”**（很重要）。

### 2. 拿到本项目
点这个页面右上角绿色的 **Code → Download ZIP**，解压到桌面。
（或者如果你会用 git：`git clone https://github.com/olivia0401/AI-Job-Scout.git`）

### 3. 打开命令行，进入项目文件夹
- Windows：打开解压后的文件夹，在地址栏输入 `cmd` 回车。
- Mac：在文件夹上右键 →「服务」→「新建位于文件夹位置的终端窗口」。

### 4. 装依赖 + 启动（复制粘贴这两行，一行一行运行）
```
pip install -r requirements.txt
python app.py
```

### 5. 打开浏览器
访问 **http://127.0.0.1:5050** —— 界面就出来了。

> 卡住了？把报错整段复制给 Claude，问它「怎么解决」，它会一步步教你（见后面「让 Claude 帮你」）。

---

## 📖 日常怎么用（4 步）

1. **导入雇主名单**：去 gov.uk 下载官方 sponsor 名单 CSV（搜索 “register of licensed sponsors workers”），
   在页面「高级」里填文件路径导入。也可以把你自己整理的公司清单（Excel/CSV）拖进来，会标 ⭐精选。
2. **扫描岗位**：
   - 🔄 **刷新最新岗位**：日常用这个，几分钟，抓已知公司的新岗。
   - 🌊 **全量清查**：第一次跑一次（约十几小时，可随时停、下次续跑），把所有雇主都探一遍。
3. **上传简历**：拖进你的 PDF / Word / txt 简历，自动给每个岗位算 **匹配度**，并列出你缺哪些技能。
4. **看结果 / 导出**：岗位按时间排序，带 🆕新上架、⏳长期在招、⭐LLM 等标记；点 **📥 导出** 存成 Excel。

---

## 🔁 不是找 AI 岗？换成你的行业

这个工具本质是「扫雇主招聘系统里，标题或正文包含**你指定关键词**的岗位」，**跟行业无关**。
在页面「高级 → 岗位关键词」里改成你要的词，保存后重新扫描即可。举例：

| 行业 | 关键词填这些 |
|---|---|
| 护理 / 医疗 | nurse, healthcare assistant, clinical, care worker |
| 会计 / 金融 | accountant, financial analyst, audit, tax, bookkeeper |
| 市场 / 运营 | marketing, social media, content, brand, growth |
| 工程 | mechanical engineer, civil engineer, electrical engineer |
| 教育 | teacher, lecturer, teaching assistant |
| 供应链 | supply chain, logistics, procurement, warehouse |

---

## 🤖 不会改代码？让 Claude 帮你（零基础也能改）

装一个 **Claude Code**（或用网页版 Claude），把这个项目文件夹给它，然后用**大白话**说你想要什么，例如：

- 「把岗位关键词换成护士、医疗相关的」
- 「我只想看伦敦的岗位，别的地区都不要」
- 「匹配度更看重工作年限，帮我调一下」
- 「加一个按薪资高低排序的功能」
- 「启动时报错了，这是报错内容：（粘贴）——帮我解决」

你只需要描述**想要的结果**，不用懂代码，Claude 会帮你改好并解释。
小贴士：让它改完顺手跑一下 `pytest tests/`（自带的自动测试），确认没改坏。

---

## 🌐 这些主流平台它抓不到，需要你自己去搜 / 投

本工具只抓公司**官方招聘系统**的公开接口，下面这些**盲区**要你自己去平台上搜：

| 平台 | 说明 |
|---|---|
| **LinkedIn** | 禁止程序抓取，只能自己上去搜（工具给了每家公司的「LinkedIn 招聘官搜索」一键链接） |
| **Indeed** | 最大的聚合站，需自己搜 |
| **Glassdoor** | 需自己搜 |
| **Totaljobs / CV-Library / Reed 网站** | 英国本土大站，建议自己也去逛 |
| **大厂自建系统**（Google、Amazon、大银行等） | 工具探测不到，用公司卡片里的「Google 直达」链接手动查 |

> 每个公司卡片都附了 **LinkedIn 招聘官搜索 / Hunter 查邮箱 / Google 搜岗位** 的一键链接，
> 方便你手动补齐这些平台 + 找到 HR 联系人（工具不替你爬取联系人，只给搜索入口）。

**想抓更全、更快？**（选配，需要免费注册）
配好 **Adzuna / Reed** 的免费 API key（把 `api_keys.example.json` 复制成 `data/api_keys.json` 填进去），
点页面上的 **🌐 搜聚合平台**，就能几秒内横扫全英国的相关岗位，并自动标出哪些公司在工签担保名单里。

---

## ✍️ 全平台简历提升建议

上传简历、算完匹配度后，点简历卡片上的 **🎯 简历提升建议**：工具会把**全部已匹配岗位**汇总，
按影响排序告诉你「最该补的技能」——例如 `research·83（🎯27）` 表示这个技能缺失于 83 个岗位、
其中 27 个是中等匹配（补上最能提分）。还会用**语料挖掘**列出 JD 里高频、但技能词表可能没收录的表达。

如果你在 `data/api_keys.json` 填了 **Claude API key**（`anthropic_api_key`，或设环境变量 `ANTHROPIC_API_KEY`），
再点 **✍️ 用 Claude 生成修改建议**，就能**在工具里直接**拿到一份可执行的简历修改建议
（优先补哪几项、每项加到哪段怎么写、该改写哪几条经历），不用复制到别处。它不会编造你没有的经历。

> 技能识别用固定词表 + 同义词归并，再叠加上面的语料挖掘兜底词表外的表达；建议基于真实岗位统计，不是空谈。

---

## 🔒 隐私

所有数据（公司名单、你的简历、抓到的岗位）**只存在你自己电脑**的 `data/` 文件夹里，
不会上传到任何服务器。`data/` 已设为不进 Git，不会被同步到 GitHub。

---

## 🧠 进阶：匹配度是怎么算的？（给好奇的人）

上传简历后，工具用 **Jobscan 式规则评分**给每个岗位算 0–100 的「ATS 匹配度」。
这**不是**机器学习准确率，而是可解释的加权分：

| 分项 | 权重 | 看什么 |
|---|---|---|
| 必备技能覆盖 | 55% | JD 要求的技能你简历里有几个 |
| 加分技能覆盖 | 20% | nice-to-have 的技能覆盖 |
| 职级匹配 | 10% | 岗位级别对应年限 vs 你的年限 |
| 领域匹配 | 10% | 方向对不对口（NLP/推荐/风控…） |
| JD 抓取置信度 | 5% | 抓到完整 JD 还是只有标题 |

另外会对「明确不担保签证 / 要求年限过高 / 需要安全许可」的岗位打 ⚠️ 提醒。
想验证准确性，可以准备 30–50 条「简历+JD+人工标签」放进 `eval/dataset.jsonl`，跑 `python eval/run_eval.py`。

**抓取覆盖的招聘系统**：Greenhouse、Lever、Ashby、Workable、SmartRecruiters、Recruitee、Personio（自动探测）；
Workday（大厂/银行，需手动配 host/site，见 `data/slug_overrides.json`）；Adzuna / Reed 聚合器（需免费 key）。

**开发者相关**：依赖见 `requirements.txt`；自动测试 `pytest tests/`；评估脚本 `eval/`。
数据文件都在 `data/`：`companies.json`（名单）、`ats_cache.json`（探测缓存 = 全量清查进度）、
`state.json`（岗位/首见日期/匹配分）、`slug_overrides.json`（手动修正）、`api_keys.json`（聚合器 key）。
