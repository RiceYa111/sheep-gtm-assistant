# 🐑 小羊分析助手

汽车行业 GTM 分析原型：输入品牌或车型，查看市场趋势、竞品格局、用户洞察，再生成策略和角色任务，并导出 PDF。

这是简历作品的公开体验版本，基于 Streamlit、Plotly 和可选的 DeepSeek API 构建。

## 体验路径

1. 在首页输入“问界M7”等车型，进入市场大盘。
2. 查看地区、价格带、能源形式等维度的图表和分析结论。
3. 在竞品格局中查看竞争集中度和竞品分层。
4. 在用户洞察中使用演示资料，或上传 CSV / XLSX 问卷和用户原文材料。
5. 进入策略生成，确认目标、参与角色与职责，生成策略并下载 PDF。

上传的资料会延续到当前会话的策略分析。不同访客的上传资料、缓存和保存场景相互隔离。各页面的筛选条件可独立调整，生成策略前请核对策略页的分析口径。

## 数据与 AI 说明

- 销量由确定性模拟规则生成，**不是真实行业销量**；图表用于展示分析方法和交互流程。
- 内置问卷为拟定样本，用户材料为公开评论风格的演示改写，**不代表真实访谈或抽样调研**。来源和数据性质列保留在演示表中。
- 没有配置 API 密钥也可以使用看板、问卷统计、基础版策略和 PDF 导出。原文的在线 AI 分析需要部署者启用 DeepSeek。
- 点击 AI 分析会向 DeepSeek 发送所选车型、相关原文或统计摘要；请仅上传模拟或已脱敏资料。模型结论需要人工复核。
- 上传数据与结果仅保留在当前浏览器会话对应的临时存储中；刷新、断开连接或服务重启后可能丢失，请及时导出。

## 本地运行

需要 Python 3.12。

```bash
pip install -r requirements.txt
streamlit run sheep_v0_5_strategy.py
```

可选：通过环境变量设置 `DEEPSEEK_API_KEY`。不要将真实密钥提交到仓库。

## 部署到 Streamlit Community Cloud

1. 将本仓库上传到 GitHub。
2. 登录 [Streamlit Community Cloud](https://share.streamlit.io/)，创建应用并选择此仓库和 `main` 分支。
3. 入口文件选择 `sheep_v0_5_strategy.py`；高级设置中选择 Python 3.12。
4. 点击 Deploy，部署成功后把生成的 `https://你的应用名.streamlit.app` 作为简历的“在线体验”链接。
5. 如需在线 AI，在云端应用的 Secrets 中填写以下配置，**不要把密钥写进 GitHub 文件**。

```toml
DEEPSEEK_API_KEY = "在云端填写自己的密钥"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"
AI_DAILY_CALL_LIMIT = "40"
AI_SESSION_CALL_LIMIT = "8"
```

调用限额包括失败请求。每日共享限额保存在部署实例的临时数据库中，实例重建会重置；不等同于供应商账户的硬性消费上限。正式公开启用 AI 时，也应在供应商侧限制账户预算。

GitHub 仓库链接用于展示代码；Streamlit 应用链接用于实际操作。GitHub Pages 无法直接运行这个 Python 应用。

## 上传表格格式

问卷至少保留这些列（可直接参考 `data/user_profile_survey_demo_v01.csv`）：

`样本ID,品牌,车系,分析对象名称,年龄段,职业,购车预算,家庭结构,首购/增购/换购,决策周期,购车动因,主要决策人`

用户原文至少保留这些列（可参考 `data/user_materials_public_demo_v01.csv`）：

`材料ID,样本ID,品牌,车系,分析对象名称,来源类型,来源平台,用户原文`

请确保“车系”与首页选择的车型相符。当前上传文件上限为 5 MB。

## 项目结构

- `sheep_v0_5_strategy.py`：页面、图表、分析和策略工作流。
- `deepseek_user_insight.py`：原文分析与用户洞察总结。
- `deepseek_strategy.py`：AI 策略生成与结构检查。
- `pdf_report.py`：中文 PDF 报告。
- `session_runtime.py`：访客会话存储、上传资料延续与调用限额。
- `data/`：车型表和明确标注的演示资料。

## 原型边界

尚未接入真实销量数据库、账号系统和长期数据存储；这是可操作的分析原型，不是正式经营决策系统。
