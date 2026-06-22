# hunzor-data

**hunzor 股票诊断系统的数据层** —— 每晚自动计算全 A 股估值、分位数、行业排名与共振评分，输出为前端可直接消费的 JSON。

> 与你的前端 PWA 配合：前端只管展示与交互，数据计算全部在 GitHub Actions 中完成。

---

## 架构

```
GitHub Actions (每晚 20:00)
    │
    ├── Tushare / AKShare → 拉取全市场日行情
    ├── DuckDB → 本地计算分位数、行业排名、共振评分
    └── data/stocks/*.json → 个股诊断数据
    └── data/latest.json → 全市场快照
    │
GitHub Pages (静态托管)
    │
手机端 PWA → fetch('data/stocks/600519.json')
```

---

## 快速开始

### 1. Fork 本仓库

点击右上角 **Fork**，把仓库复制到自己的 GitHub 账号下。

### 2. 注册 Tushare（免费）

1. 访问 https://tushare.pro/register
2. 注册后获取 **Token**（免费版额度足够）
3. 也可以跳过这一步 —— 脚本会自动回退到 AKShare（纯免费，零配置）

### 3. 配置 GitHub Secrets

在你的仓库页面 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

- Name: `TUSHARE_TOKEN`
- Value: 你的 Tushare token

### 4. 启用 GitHub Pages

仓库 → **Settings** → **Pages** → Source: **GitHub Actions**

### 5. 手动触发第一次运行

仓库 → **Actions** → **hunzor 数据更新** → **Run workflow**

等待约 5-10 分钟，数据会生成到 `data/` 目录。

### 6. 获取数据 URL

数据更新后，GitHub Pages 会托管这些数据：

```
https://<你的用户名>.github.io/hunzor-data/data/stocks/600519_SH.json
https://<你的用户名>.github.io/hunzor-data/data/latest.json
```

把这个 URL 填入你的前端配置即可。

---

## 本地测试

```bash
# 克隆仓库
git clone https://github.com/<你的用户名>/hunzor-data.git
cd hunzor-data

# 安装依赖
pip install -r requirements.txt

# 设置环境变量（可选，不用 Tushare 则跳过）
export TUSHARE_TOKEN=你的token

# 测试运行（只处理 50 只股票）
python scripts/main.py --limit 50

# 查看输出
ls data/stocks/
ls data/latest.json
```

---

## 指标说明

### 估值分位数
- 基于近 10 年、5 年、3 年日线数据计算
- PE_TTM、PB、PS、股息率四个维度

### 行业排名
- 申万三级行业分类
- 在同行中按 PE/PB/市值排名

### 共振评分（0-1）

| 等级 | 分数 | 含义 |
|------|------|------|
| 🟢 强共振 | ≥ 0.7 | 估值低 + 盈利趋势好 + 动量温和，适合建仓 |
| 🟡 中共振 | 0.4-0.7 | 两维度好，一维度一般，适合定投/持有 |
| 🔴 弱共振 | < 0.4 | 估值高或盈利恶化或动量过热，建议观望 |

评分维度：
- 估值（40%）：PE 分位数越低越好
- 行业相对（20%）：在同行中越便宜越好
- 盈利趋势（20%）：价格趋势向上
- 动量（20%）：温和上涨最理想，避免过热或暴跌

---

## 数据更新频率

- **自动触发**：周一至周五 北京时间 20:00（收盘后）
- **手动触发**：随时通过 Actions 页面点击 Run
- **数据时效**：基于前一日收盘数据（盘前/盘后分析场景）

---

## 成本

- **Tushare**：免费版够用（每晚 2-3 次 API 调用）
- **GitHub Actions**：免费额度 2000 分钟/月，每晚约 5 分钟
- **GitHub Pages**：完全免费
- **总计：¥0/月**

---

## License

MIT
