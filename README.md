# Polymarket Money Generator 🎯💰

> **全自動量化套利引擎 — 用 $1,000 模擬資金在 Polymarket 預測市場上尋找 alpha**

[![Python 3.14+](https://img.shields.io/badge/Python-3.14%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一套端到端的預測市場量化交易系統，集成了：

- 🧮 **線性規劃套利檢測** — scipy LP solver 尋找無風險利潤
- 📊 **統計策略引擎** — Overround / Underround / 價值投注 / Spread Capture
- 🤖 **AI 邏輯分析** — GPT-4o 檢測跨市場定價矛盾
- 📈 **GARCH 波動率 + VaR 風控** — 三種方法交叉驗證
- 🎯 **Kelly Criterion 倉位管理** — 連續 Kelly 公式 + 1/5 安全因子
- 🌐 **Web Dashboard** — 即時 WebSocket 推送，瀏覽器看盤

---

## 目錄

- [系統架構](#系統架構)
- [快速開始](#快速開始)
- [運行模式](#運行模式)
- [交易策略詳解](#交易策略詳解)
- [數學模型](#數學模型)
- [倉位管理 (Kelly Criterion)](#倉位管理-kelly-criterion)
- [風險控制](#風險控制)
- [Web Dashboard](#web-dashboard)
- [API 接口](#api-接口)
- [配置參數](#配置參數)
- [項目結構](#項目結構)
- [技術棧](#技術棧)
- [常見問題](#常見問題)
- [免責聲明](#免責聲明)

---

## 系統架構

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Web Dashboard (port 8899)                    │
│                    aiohttp + WebSocket 即時推送                       │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────┐
│                        Trading Engine (引擎核心)                      │
│                                                                      │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────────────────┐  │
│  │ Market Scan  │→ │ Opportunity   │→ │ Position Manager         │  │
│  │ (30s cycle)  │  │ Evaluator     │  │ (Kelly sizing + exits)   │  │
│  └──────────────┘  └───────────────┘  └──────────────────────────┘  │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────┐
│                     Simulated Account ($1,000)                        │
│              Thread-safe · Full order history · Real-time P&L         │
└─────────────────────────────────────────────────────────────────────┘
```

### 數據流

```
Polymarket Gamma API (事件元數據 + 快照價格)
         │
         ▼
┌─────────────────┐     ┌─────────────────────┐
│  Event/Market   │────▶│  Arbitrage Detector  │──── LP solver (scipy.linprog)
│  Fetcher        │     │  (多結果互斥檢測)     │
└────────┬────────┘     └─────────────────────┘
         │
         ▼
Polymarket CLOB API (即時 orderbook midpoint)
         │
         ▼
┌─────────────────┐     ┌─────────────────────┐
│  Statistical    │────▶│  AI Analyzer         │──── GPT-4o (optional)
│  Strategies     │     │  (邏輯關係檢測)       │
└────────┬────────┘     └─────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────┐
│  Ranked Opportunities                        │
│  (sorted by edge × confidence × liquidity)   │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
              Trading Engine Decision
              (fee-adjusted edge > threshold?)
                       │
                       ▼
              Kelly Sizing → Execute Order
```

---

## 快速開始

### 系統需求

- Python 3.14+ (使用了最新語法特性)
- Windows / macOS / Linux
- 網路連接 (訪問 Polymarket 公開 API)

### 安裝

```bash
git clone https://github.com/yourusername/polymarket_money_generator.git
cd polymarket_money_generator

# 安裝依賴
pip install -r requirements.txt

# 複製環境配置
cp .env.example .env
```

### 最小化啟動 (零配置)

```bash
# 無需任何 API key，直接啟動 Web Dashboard
python main.py ui
```

打開瀏覽器訪問 `http://localhost:8899`，系統會自動：
1. 創建 $1,000 模擬帳戶
2. 每 30 秒掃描 Polymarket 所有活躍市場
3. 自動做出交易決策並執行
4. 通過 WebSocket 推送即時狀態到瀏覽器

---

## 運行模式

```bash
python main.py [command] [options]
```

| 命令 | 說明 | 是否需要 API Key |
|------|------|:---:|
| `ui` | 啟動 Web Dashboard + 自動交易引擎 (默認) | ❌ |
| `scan` | 單次掃描，印出結果後退出 | ❌ |
| `monitor` | Rich 終端即時儀表板，持續掃描 | ❌ |
| `analyze` | AI 深度邏輯分析 | ✅ OpenAI |

### 選項

```bash
# 自定義起始資金
python main.py ui --balance 5000

# 單次掃描 (適合 cron job)
python main.py scan
```

### 模式詳解

#### `ui` — Web Dashboard (推薦)

啟動 aiohttp web server，提供：
- 即時帳戶狀態（餘額、持倉、P&L）
- 交易歷史和決策日誌
- WebSocket 自動刷新
- 一鍵啟動 / 停止交易引擎
- RESTful API 接口

#### `monitor` — 終端儀表板

使用 Rich 庫在終端渲染即時 UI：
- 套利機會列表（按 edge × confidence × liquidity 排序）
- AI 邏輯關係警報
- 掃描統計（事件數、市場數、耗時）
- VaR 風險指標
- SVD 相關性結構

#### `scan` — 單次掃描

適合 cron job 或腳本整合：
```bash
# 每 5 分鐘掃描一次 (Linux/macOS crontab)
*/5 * * * * cd /path/to/project && python main.py scan >> scan.log
```

#### `analyze` — AI 分析

使用 GPT-4o 檢測跨市場邏輯矛盾：
```bash
# 需要設置 OPENAI_API_KEY
python main.py analyze
```

輸出：
- 市場簡報
- 跨市場邏輯關係圖
- 定價矛盾檢測 (蘊含、互斥、互補)

---

## 交易策略詳解

系統同時運行多種策略，每個策略獨立生成機會，由引擎統一評估和排序。

### 策略 1: LP 套利 (Arbitrage Detection)

**原理：** 在預測市場中，互斥事件的概率之和應等於 1。偏離 = 套利。

| 子策略 | 描述 | 觸發條件 |
|--------|------|----------|
| 單市場 Spread | YES + NO 偏離 1.0 | edge > 1% |
| 多結果 Buy-All-YES | 所有結果 YES 價格之和 < 1.0 | LP cost < $1 |
| LP Optimal | 求解最優多結果組合 | LP edge < 50%, cost > $0.5 |

```
LP 形式化:
    minimize    c'x        (購買成本)
    subject to  Ax >= 1    (所有狀態下保證 $1 回報)
                x >= 0     (不能做空)

    若最優 c'x* < 1.0 → 套利存在，edge = (1 - c'x*) / c'x*
```

### 策略 2: Overround Value

**原理：** 當多結果事件的概率總和 > 1.0 (overround)，最被低估的結果有正期望值。

- 條件：`sum(prices) > 1.02` (overround > 2%)
- 動作：買入最便宜的 YES token
- 置信度：0.55
- 邏輯：市場對某結果定價偏高，連帶壓低其他結果

### 策略 3: Underround Value

**原理：** 當概率總和 < 0.95 (underround > 5%)，買入所有 YES token 構成近似套利。

- 條件：`sum(prices) < 0.95`
- 動作：買入全部 YES tokens
- 置信度：0.65
- 邏輯：無論哪個結果發生，你都持有贏家的 YES token

### 策略 4: Liquid Value (統計偏差)

**原理：** 在高流動性市場中，極端價格 (<0.30 或 >0.70) 更可能存在真實定價偏差。

嚴格過濾條件：
- 流動性 > $2,000
- 交易量 > $50,000
- 價格 < 0.30 或 > 0.70 (避免 coin-flip 區間)
- 按交易量排序（不用隨機性）
- 置信度：0.60
- 每次掃描最多 2 個信號

### 策略 5: Spread Capture

**原理：** 利用 bid-ask spread，在 mid price 附近做市。

- 條件：spread > 3%, 流動性 > $1,000
- 動作：在有利的一側下單
- 置信度：0.55

---

## 數學模型

### 1. 套利檢測 — Linear Programming

不同市場之間存在邏輯關聯，但往往分開定價。LP 求解器找到最優組合：

```
最小化: c'x (購買成本)
約束:   Ax >= 1 (所有狀態下保證 $1 回報)
        x >= 0 (不能負數持倉)

若最優成本 < $1 → 套利存在！
```

三層掃描策略：
- **單一市場:** YES + NO 價格偏離 1.0
- **多結果事件:** 互斥結果的 LP 最優組合
- **跨市場約束:** 邏輯蘊含關係 (A ⊂ B → P(A) ≤ P(B))

### 2. 相關性分析 — PCA / SVD

特徵值分解揭示持倉之間的真實獨立性：

```python
# PCA 告訴你：3 個特徵向量解釋了 80% 的總方差
eigenvalues, eigenvectors = np.linalg.eig(correlation_matrix)
n_effective_bets = exp(-Σ pᵢ·ln(pᵢ))  # 有效獨立注數 (Shannon entropy)
```

> 你以為持有 10 個不同市場的倉位？PCA 告訴你其實只有 3 個獨立風險因子。分散化是假象。

### 3. GARCH(1,1) 波動率模型

波動率聚集：大新聞後，高波動會持續一段時間再衰減。

```
σ²ₜ = α₀ + α₁ε²ₜ₋₁ + β₁σ²ₜ₋₁

α₁ = 對新信息的反應速度
β₁ = 波動率的持續性
半衰期 = ln(2) / ln(α₁ + β₁)
```

應用：決定做市商何時收緊報價，以及何時是入場的最佳時機。

### 4. VaR 風險管理

三種方法交叉驗證：

| 方法 | 公式 | 優點 | 缺點 |
|------|------|------|------|
| 參數法 | `σ²_p = w'Σw` | 計算快速 | 假設正態分布 |
| 蒙特卡洛 | 模擬 10,000 路徑 | 處理非正態 | 計算較慢 |
| 歷史模擬 | 用歷史 returns | 無分布假設 | 受限於歷史數據 |

**當三種方法結果分歧 > 2 倍時，系統自動發出紅色警報。**

### 5. 加權迴歸 (GLS)

預測市場天然違反 OLS 的等方差假設：
- 接近結算 → 價格波動小 → 數據點權重高
- 遠離結算 → 價格波動大 → 數據點權重低

加入穩健迴歸 (Huber weights) 抵禦極端異常值。

### 6. AI 邏輯分析 (GPT-4o)

LLM 檢測人類難以逐一比對的邏輯關係：

| 關係類型 | 示例 | 約束 |
|----------|------|------|
| 蘊含 | "賓州贏 5%+" → "贏賓州" | P(A) ≤ P(B) |
| 互斥 | 多候選人選舉 | Σ P(i) ≤ 1 |
| 互補 | "勝" vs "負" | P(A) + P(B) ≈ 1 |
| 相關 | 同一驅動因子 | 價格應聯動 |

---

## 倉位管理 (Kelly Criterion)

系統使用**連續 Kelly 公式**進行倉位計算，配合安全因子防止過度集中。

### 公式

```
f* = μ / σ²

其中:
  μ  = net_edge = raw_edge - 4% (扣除往返手續費)
  σ² = variance = edge / confidence
  f* = 最優下注比例 (佔總權益)
```

### 安全機制

| 參數 | 值 | 說明 |
|------|-----|------|
| Kelly 分數 | 1/5 | 只使用 Kelly 建議倉位的 20% |
| 最小倉位 | 0.5% 權益 | 過小的機會不值得執行成本 |
| 最大倉位 | 10% 權益 | 防止單一市場過度暴露 |
| 最大總曝險 | 60% 權益 | 始終保留 40% 現金緩衝 |
| 最大持倉數 | 10 | 防止過度分散 |
| 手續費扣除 | 4% | 2% 入場 + 2% 出場 (round-trip) |

### 計算示例

```
原始 edge = 6%, confidence = 0.70

1. 扣除手續費: net_edge = 6% - 4% = 2%
2. 計算方差:   variance = 0.06 / 0.70 = 0.0857
3. Kelly 最優: f* = 0.02 / 0.0857 = 23.3%
4. 安全因子:   actual = 23.3% × (1/5) = 4.66% 權益
5. 若權益 $998: position_size = $998 × 4.66% = $46.51
```

### 為什麼是 1/5 Kelly？

| Kelly 分數 | 長期回報率 | 最大回撤 | 適用場景 |
|:---:|:---:|:---:|:---|
| Full (1/1) | 最高 | ~100% | 理論最優，實際不可行 |
| Half (1/2) | ~75% of full | ~50% | 職業賭徒 |
| Quarter (1/4) | ~50% of full | ~25% | 保守量化 |
| **Fifth (1/5)** | **~40% of full** | **~15%** | **本系統 (估計誤差大)** |

> *"quants don't win every trade — they win the sizing game"* — @RohOnChain thread

---

## 風險控制

### 止盈止損 (Asymmetric TP/SL)

```
Take Profit:  +30% (讓盈利奔跑)
Stop Loss:    -12% (快速截斷虧損)
```

非對稱設計的數學邏輯：
- 期望值 = (win_rate × TP) - ((1 - win_rate) × SL)
- 只需 30% 勝率即可打平: 0.30 × 30% - 0.70 × 12% = 0.6%

### 時間退出 (Time-based Exit)

- 持倉 > 4 小時且 P&L 在 ±3% 以內 → 自動平倉
- 理由：機會成本。資金困在不動的市場裡不如釋放出來

### 事件集中度限制

- 同一事件最多 3 個持倉
- 防止相關性爆倉（千禧橋效應：所有人走同一步，橋會搖）

### 流動性門檻

| 策略 | 最低流動性 |
|------|:---:|
| 通用入場 | $100 |
| Spread Capture | $1,000 |
| Liquid Value | $2,000 |

### 每週期交易限制

- 每個掃描週期 (30s) 最多 3 筆新交易
- 防止引擎在異常數據下一次性 all-in

### Fee-Adjusted Edge Filter

```
顯示 edge: 5.0%
實際 net_edge: 5.0% - 4.0% = 1.0%  ← 只有這才是真正的利潤

若 net_edge < min_edge_to_trade (1.0%) → 拒絕交易
```

很多看似有利可圖的機會，扣除 4% 往返手續費後其實是虧損的。

---

## Web Dashboard

### 啟動

```bash
python main.py ui
# 默認: http://localhost:8899
```

### 功能

| 功能 | 說明 |
|------|------|
| 帳戶概覽 | 餘額、權益、總 P&L、持倉數量 |
| 持倉列表 | 即時 CLOB midpoint 價格更新、未實現盈虧 |
| 訂單歷史 | 完整交易記錄和已實現 P&L |
| 決策日誌 | 每筆交易的理由、edge、confidence |
| 引擎控制 | Start / Stop 按鈕 |
| WebSocket | 每秒自動推送狀態更新 |

### 界面示意

```
╔══════════════════════════════════════════════════╗
║  POLYMARKET MONEY GENERATOR                      ║
║  ─────────────────────────────────────────────── ║
║  Balance: $918.46  │  Equity: $998.15            ║
║  Total P&L: -$1.85 (-0.2%)                      ║
║  Open Positions: 11  │  Total Trades: 22         ║
║  Win Rate: 45%  │  Scans: 5                     ║
╠══════════════════════════════════════════════════╣
║  OPEN POSITIONS                                  ║
║  ┌────────────────────────────────────────────┐  ║
║  │ Heidenheim NO  │ Entry: 0.138 │ Now: 0.135 │  ║
║  │ Unrealized: -$0.25 (-2.5%)                 │  ║
║  ├────────────────────────────────────────────┤  ║
║  │ Arsenal YES    │ Entry: 0.670 │ Now: 0.673 │  ║
║  │ Unrealized: +$0.12 (+0.4%)                 │  ║
║  └────────────────────────────────────────────┘  ║
╠══════════════════════════════════════════════════╣
║  RECENT DECISIONS                                ║
║  [10:30:01] BUY_YES Heidenheim — edge: 2.1%     ║
║  [10:30:01] BUY_NO  Lyman — edge: 1.8%          ║
║  [10:32:15] EXIT Arsenal — TP hit +30.1%         ║
╚══════════════════════════════════════════════════╝
```

---

## API 接口

Web server 提供以下 RESTful + WebSocket API：

### REST Endpoints

| 方法 | 路徑 | 說明 |
|------|------|------|
| `GET` | `/` | Web Dashboard HTML 頁面 |
| `GET` | `/api/state` | 獲取完整帳戶狀態 (JSON) |
| `POST` | `/api/start` | 啟動交易引擎 |
| `POST` | `/api/stop` | 停止交易引擎 |

### WebSocket

| 路徑 | 說明 |
|------|------|
| `GET` | `/ws` | WebSocket 連接，每秒推送帳戶狀態 JSON |

### `/api/state` 返回格式

```json
{
  "balance": 918.46,
  "equity": 998.15,
  "starting_balance": 1000.0,
  "total_pnl": -1.85,
  "total_pnl_pct": -0.185,
  "open_positions": 11,
  "total_trades": 22,
  "winning_trades": 10,
  "losing_trades": 12,
  "win_rate": 0.4545,
  "positions": [
    {
      "market_id": "0x...",
      "market_question": "Will Heidenheim win?",
      "side": "BUY_NO",
      "size": 48.31,
      "avg_entry_price": 0.138,
      "current_price": 0.1345,
      "unrealized_pnl": -0.25,
      "opened_at": 1747312200.0
    }
  ],
  "orders": [...],
  "engine_running": true,
  "scan_count": 5,
  "decisions": [
    {
      "timestamp": "2026-05-15T10:30:01",
      "action": "BUY_YES",
      "market": "Heidenheim",
      "edge_pct": 2.1,
      "confidence": 0.65,
      "size_usd": 6.66,
      "reason": "overround_value: cheapest YES in overround event"
    }
  ]
}
```

---

## 配置參數

### 環境變量 (`.env`)

```env
# ═══════════════════════════════════════════════════
# Polymarket API (無需 key 即可掃描)
# ═══════════════════════════════════════════════════
POLYMARKET_API_URL=https://clob.polymarket.com
POLYMARKET_GAMMA_URL=https://gamma-api.polymarket.com
POLYMARKET_WS_URL=wss://ws-subscriptions-clob.polymarket.com/ws

# ═══════════════════════════════════════════════════
# 交易 (可選 - 實盤才需要)
# ═══════════════════════════════════════════════════
POLYMARKET_PRIVATE_KEY=
POLYMARKET_API_KEY=
POLYMARKET_API_SECRET=
POLYMARKET_API_PASSPHRASE=

# ═══════════════════════════════════════════════════
# AI 分析 (可選)
# ═══════════════════════════════════════════════════
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o

# ═══════════════════════════════════════════════════
# 掃描器參數
# ═══════════════════════════════════════════════════
SCAN_INTERVAL_SECONDS=30       # 掃描間隔 (秒)
MIN_ARBITRAGE_EDGE_PCT=1.0     # 最小邊際 (%)
MIN_LIQUIDITY_USD=500          # 最小流動性 ($)
MAX_POSITION_SIZE_USD=1000     # 最大單倉 ($)

# ═══════════════════════════════════════════════════
# 風控
# ═══════════════════════════════════════════════════
VAR_CONFIDENCE=0.99            # VaR 置信度
MAX_PORTFOLIO_VAR_USD=5000     # 組合最大 VaR
GARCH_LOOKBACK_DAYS=30         # GARCH 回溯天數

# ═══════════════════════════════════════════════════
# 儀表板
# ═══════════════════════════════════════════════════
DASHBOARD_REFRESH_SECONDS=5    # Rich UI 刷新頻率
```

### 引擎內部參數

| 參數 | 默認值 | 說明 |
|------|--------|------|
| `max_position_pct` | 10% | 單倉最大佔權益比 |
| `max_total_exposure_pct` | 60% | 最大總曝險佔權益比 |
| `min_edge_to_trade` | 1.0% | 最小邊際 (手續費後) |
| `min_confidence` | 0.50 | 最低置信度門檻 |
| `max_open_positions` | 10 | 最大同時持倉數 |
| `take_profit_pct` | 30% | 止盈觸發點 |
| `stop_loss_pct` | 12% | 止損觸發點 |
| `time_exit_hours` | 4h | 時間退出閾值 |
| `time_exit_threshold` | ±3% | 時間退出 P&L 範圍 |
| `kelly_fraction` | 1/5 | Kelly 安全因子 |
| `fee_round_trip` | 4% | 往返手續費 (2% × 2) |
| `max_trades_per_cycle` | 3 | 每週期最多交易數 |
| `max_event_positions` | 3 | 同事件最多持倉數 |

---

## 項目結構

```
polymarket_money_generator/
│
├── main.py                           # 主入口
│                                     # Commands: ui / scan / monitor / analyze
│                                     # Options: --balance <amount>
│
├── config/
│   └── settings.py                   # 環境配置 (dataclass-based)
│                                     # APIConfig, ScannerConfig, RiskConfig,
│                                     # AIConfig, DashboardConfig
│
├── src/
│   ├── __init__.py
│   │
│   ├── api/
│   │   └── polymarket_client.py      # Polymarket API 客戶端
│   │       │                         # - Gamma API: 事件/市場元數據 + 快照價格
│   │       │                         # - CLOB API: 即時 orderbook midpoint
│   │       │                         # - Token parsing (parallel-array format)
│   │       └── Features:
│   │           ├── get_all_active_events()   # 批量獲取活躍事件
│   │           ├── refresh_market_prices()   # 批量刷新 CLOB midpoint
│   │           └── get_midpoint()            # 單個 token midpoint
│   │
│   ├── models/
│   │   ├── arbitrage_detector.py     # LP 套利求解器
│   │   │   ├── Single-market spread detection
│   │   │   ├── Multi-outcome buy-all-YES
│   │   │   └── LP optimal (scipy.linprog)
│   │   │
│   │   ├── correlation_analyzer.py   # PCA / SVD 相關性分析
│   │   │   └── 有效獨立注數 (Shannon entropy)
│   │   │
│   │   ├── garch_model.py            # GARCH(1,1) 波動率模型
│   │   │   └── 半衰期計算 + 做市商報價建議
│   │   │
│   │   ├── var_calculator.py         # VaR 風險管理
│   │   │   ├── Parametric VaR
│   │   │   ├── Monte Carlo VaR
│   │   │   └── Historical Simulation VaR
│   │   │
│   │   └── regression_model.py       # 加權迴歸 + Huber 穩健迴歸
│   │
│   ├── ai/
│   │   └── market_analyzer.py        # GPT-4o 邏輯分析
│   │       ├── analyze_event_relationships()  # 跨市場邏輯檢測
│   │       └── generate_market_brief()        # 市場簡報生成
│   │
│   ├── scanner/
│   │   └── market_scanner.py         # 掃描引擎 Hub
│   │       ├── scan_once()            # 完整掃描週期
│   │       ├── _find_statistical_opportunities()
│   │       │   ├── Strategy: overround_value
│   │       │   ├── Strategy: underround_value
│   │       │   ├── Strategy: liquid_value
│   │       │   └── Strategy: spread_capture
│   │       └── Opportunity ranking (edge × confidence × liquidity)
│   │
│   ├── simulation/
│   │   ├── account.py                # 模擬交易帳戶
│   │   │   ├── SimulatedAccount (Thread-safe, RLock)
│   │   │   ├── Position tracking (entry price, current price, P&L)
│   │   │   ├── Order history (full audit trail)
│   │   │   └── get_state() → JSON-serializable dict
│   │   │
│   │   └── engine.py                 # 交易決策引擎
│   │       ├── _evaluate_opportunity()   # Edge/confidence/liquidity 過濾
│   │       ├── _kelly_size()             # 連續 Kelly f*=μ/σ² + 1/5
│   │       ├── _check_exits()            # TP/SL + time exit
│   │       └── _update_positions()       # CLOB midpoint 價格刷新
│   │
│   ├── execution/
│   │   └── trade_executor.py         # 交易執行器 (默認 dry-run)
│   │
│   ├── web/
│   │   ├── server.py                 # aiohttp web server
│   │   │   ├── GET /               → Dashboard HTML
│   │   │   ├── GET /api/state      → Account JSON
│   │   │   ├── POST /api/start     → Start engine
│   │   │   ├── POST /api/stop      → Stop engine
│   │   │   └── GET /ws             → WebSocket (1s push)
│   │   │
│   │   └── templates/
│   │       └── index.html            # Dashboard 前端
│   │
│   ├── dashboard/
│   │   └── dashboard.py              # Rich 終端即時 UI
│   │
│   └── utils/
│       ├── data_models.py            # 核心數據模型
│       │   ├── Event, Market, Token
│       │   ├── ArbitrageOpportunity
│       │   ├── PriceHistory, OrderBook
│       │   └── RiskMetrics
│       │
│       └── logger.py                 # 統一日誌工具
│
├── requirements.txt                  # Python 依賴清單
├── .env.example                      # 環境變量範本
└── .gitignore                        # Git 忽略規則
```

---

## 技術棧

| 類別 | 技術 | 用途 |
|------|------|------|
| **Language** | Python 3.14 | 異步 IO + 最新語法 |
| **Web Server** | aiohttp | HTTP + WebSocket server |
| **HTTP Client** | httpx | 異步 Polymarket API 調用 |
| **LP Solver** | scipy.optimize.linprog | 套利最優化 |
| **Linear Algebra** | numpy | 矩陣運算、SVD |
| **Statistics** | statsmodels | 加權迴歸、穩健迴歸 |
| **Volatility** | arch | GARCH(1,1) 模型 |
| **ML** | scikit-learn | PCA 降維 |
| **AI** | openai (GPT-4o) | 邏輯關係分析 |
| **Terminal UI** | rich | 即時儀表板 |
| **Config** | python-dotenv | 環境變量 |
| **Concurrency** | asyncio + threading | 異步掃描 + thread-safe 帳戶 |
| **Data** | pandas | 時間序列處理 |

---

## 性能表現

### 系統指標 (典型運行)

| 指標 | 數值 |
|------|------|
| 單次掃描耗時 | 2-5 秒 |
| 掃描事件數 | 40-60 個 |
| 掃描市場數 | 100-200 個 |
| 每次掃描機會數 | 5-25 個 |
| Fee-adjusted 後通過率 | ~30% |
| 典型倉位大小 | $5-15 (1/5 Kelly) |
| 總曝險率 | 5-15% 權益 |

### 優化前 vs 優化後

| 指標 | 優化前 | 優化後 | 改善 |
|------|--------|--------|------|
| 止盈/止損 | TP 15% / SL 20% | TP 30% / SL 12% | 修正反向 |
| 倉位大小 | $12-18/leg | $5-7/leg | 更保守 |
| 置信度門檻 | 0.52 | 0.60+ | 過濾雜訊 |
| 手續費考量 | 無 | 扣除 4% | 避免假邊際 |
| 勝率 | 40% | TBD (改善中) | — |
| P&L | -$28.67 | -$1.85 | +94% 改善 |

---

## 常見問題

### Q: 不設置任何 API key 能運行嗎？

**A:** 可以。基礎掃描和模擬交易只使用 Polymarket 的公開 API (Gamma + CLOB)，無需認證。只有 `analyze` 模式需要 OpenAI API key。

### Q: 這能真正賺錢嗎？

**A:** 這是一個**研究和模擬工具**。預測市場的套利機會確實存在，但：
- 流動性可能不足以執行理論上的套利
- 執行延遲可能讓機會消失
- 2% 手續費會吃掉大部分微小邊際
- 結算規則可能導致意外結果
- 市場效率在提高，機會窗口在縮短

### Q: 為什麼用 aiohttp 而不是 FastAPI？

**A:** Python 3.14 的 `asyncio` 循環機制和 uvicorn/FastAPI 存在兼容性問題。aiohttp 直接基於 asyncio event loop，運行更穩定。

### Q: 掃描頻率能調多高？

**A:** 默認 30 秒。可通過 `SCAN_INTERVAL_SECONDS` 調低，但注意：
- Polymarket Gamma API 有 rate limit
- CLOB API midpoint 查詢有頻率限制
- 建議不低於 10 秒

### Q: Kelly Criterion 為什麼只用 1/5？

**A:**
1. 模型估計的 edge 本身有 ±2% 的誤差
2. 預測市場不是理想的二項式分布（有結算風險）
3. Full Kelly 在連續虧損時 drawdown 可達 100%
4. 1/5 Kelly 犧牲 ~40% 的理論長期回報，但將最大回撤控制在 ~15%

### Q: 能連接真實交易嗎？

**A:** 系統架構支持（有 `execution/trade_executor.py`），但默認 dry-run。如需實盤：
1. 設置 `POLYMARKET_PRIVATE_KEY` 和 API credentials
2. 修改 trade executor 移除 dry-run 標記
3. **強烈建議先用模擬跑出 100+ 筆交易的正收益再考慮**

### Q: 價格數據來源是什麼？

**A:** 雙層價格系統：
- **Gamma API:** 用於獲取事件元數據和市場列表（價格是快照，可能延遲）
- **CLOB API:** 用於獲取即時 orderbook midpoint（真實市場價格）
- 入場和持倉更新都使用 CLOB midpoint，確保價格真實

### Q: 如何添加自定義策略？

**A:** 在 `src/scanner/market_scanner.py` 的 `_find_statistical_opportunities()` 方法中添加新的策略塊。每個策略需要輸出 `ArbitrageOpportunity` 對象，包含 `edge_pct`、`confidence`、`required_capital` 等字段。

---

## 開發指南

### 添加新策略

```python
# src/scanner/market_scanner.py → _find_statistical_opportunities()

# Strategy N: Your Custom Strategy
for event in events:
    for market in event.markets:
        if your_condition(market):
            opportunities.append(ArbitrageOpportunity(
                opportunity_type="your_strategy_name",
                markets=[market.condition_id],
                edge_pct=calculated_edge,
                confidence=your_confidence,
                required_capital=amount,
                expected_profit=amount * calculated_edge / 100,
                description=f"Your description: {market.question}",
                legs=[{
                    "market": market.question,
                    "side": "BUY_YES",
                    "price": market.yes_price,
                    "token_id": market.tokens[0].token_id,
                }],
            ))
```

### 調整引擎參數

```python
# src/web/server.py → 初始化時修改
engine = TradingEngine(
    account=account,
    max_position_pct=15.0,      # 放寬單倉限制
    min_edge_to_trade=0.5,      # 降低邊際門檻
    min_confidence=0.55,        # 提高置信度要求
    max_open_positions=15,      # 允許更多持倉
)
```

### 日誌格式

```
[2026-05-15 10:30:00] scanner    | Scan #5: 47 events, 126 markets → 12 opportunities
[2026-05-15 10:30:01] engine     | TRADE: BUY_YES Heidenheim @ 0.1380, size=$6.66 (kelly=0.67%)
[2026-05-15 10:30:01] engine     | EXIT: SELL_YES Arsenal @ 0.7100 → P&L +$2.34 (+30.1% TP)
[2026-05-15 10:30:01] engine     | SKIP: liquid_value confidence=0.52 < min 0.60
[2026-05-15 10:30:01] engine     | SKIP: spread_capture net_edge=-1.2% (after 4% fees)
```

---

## 免責聲明

⚠️ **重要提示：**

- 本系統默認為**模擬模式** — 不執行任何真實交易
- 套利機會可能因流動性、延遲或結算規則而無法實現
- 本工具**僅供研究和教育目的**
- 預測市場交易存在風險，過往模擬結果不代表未來真實表現
- 在真實交易前請充分理解 Polymarket 的費用結構和結算機制
- 作者不對任何財務損失負責
- 本項目不構成投資建議

---

## License

MIT

---

## 致謝

- [Polymarket](https://polymarket.com) — 預測市場平台和公開 API
- [@RohOnChain](https://x.com/RohOnChain) — 量化策略思路、Kelly Criterion 討論
- [scipy](https://scipy.org/) / [numpy](https://numpy.org/) — LP solver + 線性代數
- [arch](https://arch.readthedocs.io/) — GARCH 波動率建模
- [statsmodels](https://www.statsmodels.org/) — 統計模型
- [MIT OpenCourseWare](https://ocw.mit.edu/) — 金融數學課程基礎
