# Polymarket Money Generator 🎯

**量化套利掃描器 & 預測市場監控系統**

利用數學模型、線性規劃和 AI 分析，自動掃描 Polymarket 預測市場中的套利機會。

---

## 架構概覽

```
polymarket_money_generator/
├── main.py                        # 主入口 (scan / monitor / analyze)
├── config/
│   └── settings.py                # 環境配置
├── src/
│   ├── api/
│   │   └── polymarket_client.py   # Polymarket CLOB + Gamma API 客戶端
│   ├── models/
│   │   ├── arbitrage_detector.py  # LP 求解器 — 套利檢測核心
│   │   ├── correlation_analyzer.py # PCA / SVD / 特徵值分析
│   │   ├── garch_model.py         # GARCH(1,1) 波動率模型
│   │   ├── var_calculator.py      # VaR 風險管理 (參數法/蒙特卡洛/歷史模擬)
│   │   └── regression_model.py    # 加權迴歸 & 穩健迴歸
│   ├── ai/
│   │   └── market_analyzer.py     # LLM 邏輯關係分析
│   ├── scanner/
│   │   └── market_scanner.py      # 主掃描引擎 (整合所有模組)
│   ├── execution/
│   │   └── trade_executor.py      # 交易執行器 (默認 dry-run)
│   ├── dashboard/
│   │   └── dashboard.py           # Rich 終端即時儀表板
│   └── utils/
│       ├── data_models.py         # 資料模型定義
│       └── logger.py              # 日誌工具
├── requirements.txt
└── .env.example                   # 環境變數範本
```

## 數學模型

本系統基於 MIT 金融數學課程的核心概念，對應 Polymarket 實戰場景：

### 1. 套利檢測 (Linear Programming)

**核心問題：** 不同市場之間存在邏輯關聯，但往往分開定價，可能出現概率總和 > 100% 或 < 100% 的矛盾。

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

### 2. 相關性分析 (PCA / SVD)

**特徵值分解:** 揭示 100 個持倉其實只有 3 個獨立風險因子

```python
# 你以為持有 100 個獨立倉位？
# PCA 告訴你：3 個特徵向量解釋了 80% 的總方差
# 你的「分散化」是假象
eigenvalues, eigenvectors = np.linalg.eig(correlation_matrix)
n_effective_bets = exp(-Σ pᵢ·ln(pᵢ))  # 有效獨立注數
```

### 3. GARCH(1,1) 波動率

**波動率聚集:** 大新聞後，高波動會持續一段時間再衰減

```
σ²ₜ = α₀ + α₁ε²ₜ₋₁ + β₁σ²ₜ₋₁

β₁ 控制衰減速度 → 決定做市商何時收緊報價
半衰期 = ln(2) / ln(α₁ + β₁)
```

### 4. VaR 風險管理

三種方法交叉驗證：
| 方法 | 優點 | 缺點 |
|------|------|------|
| 參數法 | 快速 (σ²_p = w'Σw) | 假設正態 — 接近結算時完全錯誤 |
| 蒙特卡洛 | 處理非正態分布 | 計算較慢 |
| 歷史模擬 | 無分布假設 | 只包含已發生的事件 |

> **"最危險的風險，不是模型能衡量的風險，而是模型根本不知道要去找的風險。"**
> — Morgan Stanley 講師

**當三種方法結果分歧 > 2 倍時，系統自動發出紅色警報。**

### 5. 加權迴歸 (GLS)

預測市場天然違反 OLS 的「等方差」假設：
- 接近結算 → 方差小 → 權重低
- 遠離結算 → 方差大 → 權重高

加入穩健迴歸 (Huber weights) 抵禦預言機故障產生的極端異常值。

### 6. AI 邏輯分析

LLM 檢測人類難以逐一比對的邏輯關係：
- **蘊含關係:** 「共和黨在賓州贏超過 5%」→ 蘊含「川普贏得賓州」
- **互斥關係:** 多候選人事件，概率總和不應超過 1
- **互補關係:** 相反事件的概率應接近 1
- **相關性:** 受同一因子驅動的市場應聯動

## 快速開始

### 安裝

```bash
cd polymarket_money_generator
pip install -r requirements.txt
```

### 配置

```bash
cp .env.example .env
# 編輯 .env 填入你的配置
```

最低配置（只需掃描，無需交易/AI）：
```env
# 無需任何 API key 即可運行基礎掃描
SCAN_INTERVAL_SECONDS=30
MIN_ARBITRAGE_EDGE_PCT=1.0
```

啟用 AI 分析：
```env
OPENAI_API_KEY=sk-your-key-here
```

### 運行

```bash
# 單次掃描 — 印出結果後退出
python main.py scan

# 即時監控儀表板 — 持續掃描 + Rich UI
python main.py monitor

# AI 分析模式 — 深度邏輯關係分析
python main.py analyze
```

## 使用模式

### 模式 1: 掃描 (scan)
快速掃描所有活躍市場，檢測套利機會，印出結果。適合 cron job 或一次性檢查。

### 模式 2: 監控 (monitor)
啟動 Rich 終端儀表板，持續掃描並即時更新顯示：
- 套利機會列表（按 edge × confidence × liquidity 排序）
- AI 邏輯關係警報
- 掃描統計（事件數、市場數、耗時）
- VaR 風險指標
- SVD 相關性結構

### 模式 3: AI 分析 (analyze)
使用 LLM 對當前市場進行深度邏輯分析，產出：
- 市場簡報
- 跨市場邏輯關係圖
- 定價矛盾檢測

## 競爭焦點

正如文章所述，套利策略的數學框架和工具都已公開。真正的競爭優勢在於：

1. **系統整合速度** — 從數據獲取到機會檢測到下單的端到端延遲
2. **LP 求解效率** — 壓縮 9×10¹⁸ 種結果空間為幾秒內可解的線性約束
3. **AI + 數學結合** — LLM 發現邏輯關係，LP 量化套利空間
4. **風險管理** — GARCH + VaR 確保不會在波動中爆倉
5. **反同質化** — 千禧橋效應：當所有人用同一策略時，加入隨機性

## 重要聲明

- 默認 **dry-run 模式** — 不會執行任何真實交易
- 套利機會可能因流動性、執行延遲或結算規則而無法實現
- 本工具僅供研究和教育目的
- 在真實交易前請充分理解 Polymarket 的費用結構和結算機制
- 預測市場交易存在風險，請自行評估