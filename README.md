# AI Job Scout — 英国工签雇主岗位雷达

**一句话：** 它会自动去「有英国 Skilled Worker 工签担保资质的公司」的官方招聘系统里，
把它们正在招的岗位一次性抓出来、按新鲜度排好，还能上传你的简历自动算匹配度、给修改建议。

> 默认找 **AI / 机器学习**岗，但**换几个关键词就能找任何行业**（护士、会计、市场、工程师…见下）。
> 最大好处：这些公司都**具备英国 Skilled Worker 工签担保资质**，比全网乱投效率高很多。
> （注意：有担保资质 ≠ 每个岗位都一定 sponsor 你，具体仍以 JD 说明或面试确认为准。）

> **完全不懂电脑也能用。** 照下面的步骤一步步点就行；任何一步卡住，把屏幕上的报错**整段复制**，
> 打开 [claude.ai](https://claude.ai) 或 Claude App 粘给它、问「怎么办」，它会手把手教你。这是你的万能求助按钮。

---

# 🚀 第一次使用：三步跑起来

只需要做一次安装。之后每次打开只要最后一小步（见「以后每次怎么打开」）。

## 🪟 Windows 用户

### 第 1 步：装 Python（只需一次）
1. 打开 https://www.python.org/downloads/
2. 点页面上那个大大的黄色按钮 **「Download Python 3.x」**，下载完双击运行。
3. ⚠️ **最关键的一步**：安装窗口**最下面**有个勾选框 **「Add python.exe to PATH」**，**一定要打勾**，再点 **Install Now**。
   （忘了打勾的话，后面会报「不是内部或外部命令」——重装一次、记得打勾即可。）
4. 装完点 Close。

### 第 2 步：下载本工具（只需一次）
1. 在本项目的 GitHub 页面，点绿色的 **「Code」** 按钮 → **「Download ZIP」**。
2. 到「下载」文件夹找到那个 zip，**右键 →「全部解压缩」**，解压到**桌面**方便找。
3. 你会得到一个叫 `AI-Job-Scout` 的文件夹。

### 第 3 步：启动
1. 打开 `AI-Job-Scout` 文件夹。
2. 点一下窗口**顶部的地址栏**（显示文件夹路径的那一条），把里面清空，输入 **`cmd`**，按回车。
   → 会弹出一个**黑色的窗口**（命令行），别怕，它就是用来打字下命令的。
3. 在黑窗口里**粘贴这一行**，按回车，等它装完（第一次要一两分钟）：
   ```
   pip install -r requirements.txt
   ```
4. 装完后再**粘贴这一行**，按回车：
   ```
   python app.py
   ```
5. 看到类似 `AI Job Scout 已启动: http://127.0.0.1:5050` 就成功了。
6. 打开浏览器，地址栏输入 **http://127.0.0.1:5050** 回车 → 工具界面就出来了 🎉

> **别关那个黑窗口**——它一关，工具就停了。用的时候让它一直开着就行。

## 🍎 Mac 用户

1. **装 Python**：去 https://www.python.org/downloads/ 下载 macOS 版，双击 `.pkg` 一路下一步装好。
2. **下载工具**：GitHub 页面 **Code → Download ZIP**，双击解压到桌面，得到 `AI-Job-Scout` 文件夹。
3. **打开终端**：在 Finder 里**右键点** `AI-Job-Scout` 文件夹 →「服务」→「**新建位于文件夹位置的终端窗口**」。
4. 在终端里依次运行（把 `pip`/`python` 换成 `pip3`/`python3`）：
   ```
   pip3 install -r requirements.txt
   python3 app.py
   ```
5. 浏览器打开 **http://127.0.0.1:5050**。别关终端窗口。

---

# 🔁 以后每次怎么打开（不用重装）

**Windows 用户最简单的方式：双击文件夹里的 `启动求职雷达.bat`** ——
它会自动启动服务器并打开浏览器，什么都不用敲。弹出的黑窗口是网站的服务器，
用的时候别关（可以最小化），想关掉工具就关掉它。

手动方式（Mac 用户 / bat 打不开时）：

1. 打开 `AI-Job-Scout` 文件夹 → 地址栏输入 `cmd` 回车（Mac：右键 → 在文件夹位置打开终端）。
2. 运行 **`python app.py`**（Mac：`python3 app.py`）。
3. 浏览器打开 **http://127.0.0.1:5050**。

**想关掉它**：直接关掉那个黑窗口 / 终端就行。

---

# 🆘 卡住了？对号入座（99% 的问题都在这）

| 屏幕上出现… | 什么意思 / 怎么办 |
|---|---|
| `python 不是内部或外部命令` / `command not found` | 装 Python 时忘了勾 **Add to PATH**。重装 Python 记得打勾；或重启电脑再试。Mac 上用 `python3`。 |
| `pip 不是内部或外部命令` | 同上。可改用 `python -m pip install -r requirements.txt`（Mac：`python3 -m pip …`）。 |
| `Address already in use` / 端口被占用 | 工具已经在另一个黑窗口开着了。关掉多余的窗口，或直接用已经开着的那个。 |
| 浏览器说「无法访问 / 拒绝连接」 | 确认那个黑窗口还开着、且显示「已启动」；地址要**完全等于** `http://127.0.0.1:5050`。 |
| 上传 PDF 简历失败 | 你的 PDF 可能是**扫描图片版**。用 Word 另存成**文字版 PDF**，或直接把简历文字**粘贴**进去。 |
| 其它任何看不懂的报错 | **整段复制**，粘给 [claude.ai](https://claude.ai) 问「怎么解决」。真的，这招最省事。 |

---

# 📖 装好之后，怎么用（照这个顺序）

### ① 先给它一份「能担保工签的公司名单」
- 去 gov.uk 搜 **「register of licensed sponsors workers」**，下载官方 CSV（每周更新，12 万家）。
- 回到工具页面，展开 **「⚙️ 高级」**，把 CSV 的**文件路径**填进去导入。
- 也可以把你自己整理的公司清单（Excel / CSV / 直接粘贴）拖进来，会被标 **⭐精选**。

### ② 扫描岗位
- **🔄 刷新最新岗位**：日常就点这个，几分钟，抓已知公司的新岗。
- **🌊 全量清查**：**第一次跑一次**（约十几小时，可随时停、下次自动接着跑），把所有公司探一遍。之后就不用再跑了。

### ③ 上传你的简历
- 把 **PDF / Word / txt** 简历拖进去，工具会自动给每个岗位算 **匹配度**，并列出你缺哪些技能。

### ④ 看结果 / 导出 / 要建议
- 岗位默认按上架时间排，带 🆕新上架、⏳长期在招、⭐LLM、📄正文AI 等标记。
- 点 **📥 导出** 存成 Excel。
- 点 **🎯 简历提升建议** 看「全平台最该补的技能」（见下面专门一节）。

---

# 🔁 不是找 AI 岗？换成你的行业

这个工具本质是「扫公司招聘系统里，标题或正文含**你指定关键词**的岗位」，**跟行业无关**。
展开 **「⚙️ 高级 → 岗位关键词」**，改成你的词，保存后重新扫描即可。举例：

| 行业 | 关键词就填这些 |
|---|---|
| 护理 / 医疗 | nurse, healthcare assistant, clinical, care worker |
| 会计 / 金融 | accountant, financial analyst, audit, tax, bookkeeper |
| 市场 / 运营 | marketing, social media, content, brand, growth |
| 工程 | mechanical engineer, civil engineer, electrical engineer |
| 教育 | teacher, lecturer, teaching assistant |
| 供应链 | supply chain, logistics, procurement, warehouse |

> 不确定填什么词？问 Claude：「我想找 XX 行业的英国工签岗位，帮我列一组关键词」。

---

# 🤖 想改点什么？让 Claude 帮你（零基础也能改）

不用学编程。装个 **Claude Code**，或直接用 [claude.ai](https://claude.ai) 把项目文件夹发给它，
用**大白话**说你要什么就行，比如：

- 「把岗位关键词换成护士、医疗相关的」
- 「我只想看伦敦的岗位，别的地区都别显示」
- 「匹配度更看重工作年限，帮我调一下」
- 「加一个按薪资高低排序的功能」
- 「启动报错了，这是报错：（粘贴）——帮我修」

你只描述**想要的结果**，Claude 负责改代码并解释。小贴士：让它改完顺手跑一下 `pytest tests/` 确认没改坏。

---

# 🌐 这些主流平台它抓不到，得你自己去搜 / 投

工具只抓公司**官方招聘系统**的公开接口。下面这些是**盲区**，要你自己上平台搜：

| 平台 | 说明 |
|---|---|
| **LinkedIn** | 禁止程序抓取，只能自己搜（工具给了每家公司的「LinkedIn 招聘官搜索」一键链接） |
| **Indeed** | 最大的聚合站，需自己搜 |
| **Glassdoor** | 需自己搜 |
| **Totaljobs / CV-Library / Reed 官网** | 英国本土大站，建议自己也逛逛 |
| **大厂自建系统**（Google、Amazon、大银行等） | 探测不到，用公司卡片里的「Google 直达」链接手动查 |

> 每个公司卡片都附了 **LinkedIn 招聘官搜索 / Hunter 查邮箱 / Google 搜岗位** 的一键链接，
> 方便你手动补齐这些平台、顺便找到 HR 联系人（工具不替你爬联系人，只给搜索入口）。

**想抓更全、更快？**（选配，需免费注册）把 `api_keys.example.json` 复制成 `data/api_keys.json`，
填上下面**四个聚合源**的免费 key（填得越多覆盖越全），再点页面上的 **🌐 搜聚合平台**，几秒横扫全英国相关岗位，
并自动标出哪些公司在工签担保名单里：

| 聚合源 | 注册地址 | 补的是什么 |
|---|---|---|
| **Adzuna** | https://developer.adzuna.com/ | 全英国岗位聚合（每月约 1000 次） |
| **Reed** | https://www.reed.co.uk/developers | 英国本土最大招聘站之一 |
| **Jooble** | https://jooble.org/api/about | 聚合大量英国招聘站，补充面广 |
| **JSearch（RapidAPI）** | https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch | ⭐抓 **Google for Jobs**，覆盖 **LinkedIn / Indeed / Glassdoor / ZipRecruiter**——正是上面那张「盲区」表的主要来源。填 `rapidapi_key`（免费档约每月 200 次） |

> **想补齐 LinkedIn/Indeed 盲区，就配 `rapidapi_key`（JSearch）**——它是唯一能把那几家大聚合站的岗位自动拉进来的源。
> 其余靠公司卡片里的「LinkedIn 招聘官搜索 / Google 直达」链接手动补。
> 说到底：**没有任何免费官方 API 能直连 LinkedIn/Indeed 全量**，JSearch 借道 Google for Jobs 是最实际的近似。

---

# 🏢 已内置的大厂/AI 雇主（无需配置）

工具**开箱就预置了一批**知名雇主，第一次启动就会加入清单并被扫描，你不用手动加：

- **AI/ML 明星公司**（多在 Greenhouse/Lever/Ashby，自动识别）：Anthropic、OpenAI、Cohere、Hugging Face、DeepMind、Databricks、Palantir、Wayve、Faculty、Quantexa、Synthesia、Stability AI、ElevenLabs、Speechmatics、Graphcore、Monzo、Wise、Revolut 等。
- **Workday 大厂**（用自建/Workday 系统，已内置直连地址）：NVIDIA、Salesforce、Adobe、Dell、Mastercard、Capital One、Autodesk、AstraZeneca、Sanofi 等。

> ⚠️ Workday 地址是**尽力而为**的预置：某家若抓不到（公司改了地址），**不影响其它公司**，工具会自动跳过。
> 想修正某家：在它的公司卡片上用「手动修正」填新的 `host`/`site` 即可（会存进 `data/slug_overrides.json`，覆盖内置）。
>
> ❗ **Google / Amazon / Meta / Microsoft / 摩根**等用的是**自建招聘系统（非 Workday）**，没有公开接口可抓——
> 这几家只能靠公司卡片里的「Google 直达 / LinkedIn 搜索」手动查，这是所有工具都绕不过的硬限制。

---

# ✍️ 全平台简历提升建议

上传简历、算完匹配度后，点简历卡片上的 **🎯 简历提升建议**：工具把**全部已匹配岗位**汇总，
按影响排序告诉你「最该补的技能」——例如 `research·83（🎯27）` 意思是这个技能缺失于 83 个岗位、
其中 27 个是中等匹配（补上最能提分）。还会用**语料挖掘**列出 JD 里高频、但技能词表可能漏掉的表达。

想要**成段的文字建议**、直接在工具里出结果：在 `data/api_keys.json` 里填一个大模型 key——
**用 ChatGPT** 填 `openai_api_key`（默认模型 `gpt-4o`，也可设环境变量 `OPENAI_API_KEY`），
或**用 Claude** 填 `anthropic_api_key`。两个都填时用 `llm_provider` 指定（`openai` / `anthropic`），不填默认用 ChatGPT。
配好后按钮会变成 **✍️ 用 ChatGPT 生成修改建议**，给你一份可执行清单：先补哪几项、每项加到简历哪段怎么写、该改写哪几条经历。**不会编造你没有的经历。**

## 🎯 针对单个岗位改简历

除了「全平台」建议，你还能**对某一个具体岗位**出定制建议：在岗位卡片上点 **匹配 %** 徽章展开，
里面有 **✍️ 用 ChatGPT 针对此岗位改简历**——它会拿这份 **JD 正文 + 你简历的匹配缺口 + 简历全文**，
生成这一个岗位专属的改法（补哪些词、改写哪几条经历、给一段求职信开场白），结果直接显示在卡片里。
没配大模型 key 时，旁边的 **📋 复制 Prompt** 仍可把整段提示词复制出去，贴到 claude.ai / chatgpt.com 手动生成。

---

# 🔒 隐私

所有数据（公司名单、你的简历、抓到的岗位）**只存在你自己电脑**的 `data/` 文件夹里，
不上传任何服务器。`data/` 已设为不进 Git，不会被同步到 GitHub。

---

<details>
<summary><b>🧠 进阶：匹配度怎么算 / 覆盖哪些系统（给好奇的人，非必读）</b></summary>

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
想验证准确性，可准备 30–50 条「简历+JD+人工标签」放进 `eval/dataset.jsonl`，跑 `python eval/run_eval.py`。

**覆盖的招聘系统**：Greenhouse、Lever、Ashby、Workable、SmartRecruiters、Recruitee、Personio（自动探测）；
Workday（大厂/银行，需手动配 host/site，见 `data/slug_overrides.json`）；Adzuna / Reed / Jooble / JSearch(RapidAPI) 聚合器（需免费 key，JSearch 借道 Google for Jobs 覆盖 LinkedIn/Indeed/Glassdoor）。

**开发者相关**：依赖见 `requirements.txt`；自动测试 `pytest tests/`；评估脚本 `eval/`。
数据文件都在 `data/`：`companies.json`（名单）、`ats_cache.json`（探测缓存 = 全量清查进度）、
`state.json`（岗位/首见日期/匹配分）、`slug_overrides.json`（手动修正）、`api_keys.json`（各种 key）。

</details>
