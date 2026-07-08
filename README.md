# A Share Wealth Lab

个人理财学习、A 股规则学习、实时异动监控、资金流回放和模拟盘框架。

系统定位：这是学习、观察、回放和模拟盘系统，不是自动交易系统，也不输出确定性投资建议。

## 当前能力

1. `monitor-demo`：用离线 CSV demo 跑通行情、资金流、板块资金、信号、看板和提醒。
2. `watch-once`：用真实数据跑一次自选股监控。
3. `analyze-stock`：用真实历史数据跑单股资金流回放、主力意图代理画像和模拟盘。
4. `analyze-stock` 报告会输出资金数据模型、行为动作模型、多节点交易状态和暗中吸筹证明门禁。
5. `prove-accumulation`：验证“表面主力流出是否可能是暗中吸筹”的可证伪假设。
6. `train-replay`：对一组股票运行当前主策略基准，把训练结果持久化为 JSONL 和 Markdown。
7. `backtest-demo`：保留原来的简单均线回测 demo。

核心原则：监控层不过滤主力资金异动，所有接近买入的资金/形态信号都会进入 `Main-Force Opportunity Radar`；交易层再决定标准买入、追踪试仓或仅观察。强主力异动允许小仓位追踪试仓，错了按退出纪律处理。

## 快速运行

运行真实自选股单次监控：

```powershell
cd D:\Work\chentou\a-share-wealth-lab
python run.py watch-once 000620 --alerts
```

运行盈新发展近一年资金流回放和模拟盘：

```powershell
cd D:\Work\chentou\a-share-wealth-lab
python run.py analyze-stock 000620 --days 370 --initial-cash 100000
```

对比关闭追击试仓、只做确认路径的近一年回放：

```powershell
cd D:\Work\chentou\a-share-wealth-lab
python run.py analyze-stock 000620 --days 370 --initial-cash 100000 --strategy-mode confirmed
```

对比开启“暗中吸筹早期试探仓”的近一年回放：

```powershell
cd D:\Work\chentou\a-share-wealth-lab
python run.py analyze-stock 000620 --days 370 --initial-cash 100000 --strategy-mode proof-probe
```

Run the active probe mode, which tests smaller possible-entry buys with a
reward/risk gate plus inferred exits:

```powershell
cd D:\Work\chentou\a-share-wealth-lab
python run.py analyze-stock 000620 --days 370 --initial-cash 100000 --strategy-mode active-probe
```

Run the volume-price trial probe mode. It validates today's node against
previous resolved same-node outcomes, then simulates a small next-open trial
entry and a following-open timed exit unless risk exits first.

```powershell
cd D:\Work\chentou\a-share-wealth-lab
python run.py analyze-stock 000620 --days 370 --initial-cash 100000 --strategy-mode volume-probe
```

验证“表面主力流出 + 小单承接”是否可能是暗中吸筹：

```powershell
cd D:\Work\chentou\a-share-wealth-lab
python run.py prove-accumulation 000620 --days 370 --horizon 5 --min-cases 5
```

证明结果会写入 `runtime/proofs/`，终端输出中的 `proof:` 是本次证据文件路径。

运行一轮持久化训练和参数候选对比：

```powershell
cd D:\Work\chentou\a-share-wealth-lab
python run.py train-replay 000620 000001 --days 370 --initial-cash 100000
```

训练结果会写入 `runtime/training/`，其中 JSONL 保留机器可读记录，Markdown 用于人工复盘。

运行离线监控 demo：

```powershell
cd D:\Work\chentou\a-share-wealth-lab
python run.py monitor-demo --alerts --limit 5
```

运行测试：

```powershell
cd D:\Work\chentou\a-share-wealth-lab
python -m pytest
```

## 真实数据勘测结果

以盈新发展 `000620` 为样本，已实测：

- efinance 今日分钟资金流已接入；接口可能返回空结果或缺少部分行情字段，程序已降级到最近历史日级资金流。
- efinance 历史资金流可用，本次取到 121 条日级资金流。
- efinance 历史 K 线端点有时会被远端断开。
- BaoStock 历史 K 线可用，本次取到 246 条近一年日 K，字段包括开高低收、成交量、成交额、换手率、涨跌幅。
- 程序已实现 efinance 历史 K 线优先、失败后 BaoStock 兜底。

## 盈新发展样例结果

2026-07-07 实测运行：

```powershell
python run.py analyze-stock 000620 --days 370 --initial-cash 100000 --no-persist
```

本轮回放 K 线截至 2026-07-07，历史资金流和最新回放信号截至 2026-07-06：

- 日 K：246 条，区间 2025-07-02 至 2026-07-07。
- 历史资金流：120 条，缺失资金流日期 126 个。
- 模拟盘初始资金 100000，期末 100420，收益率 0.42%，最大回撤 0.62%。
- 产生 2 笔模拟成交：一次放量突破后买入，一次突破失败退出。
- Return Estimate：闭合交易 1 笔，单笔期望收益 1.21%，账户期望收益 0.42%，样本质量为 `too_small_do_not_project`。
- 最新信号：`卖出`，标签为 `突破失败`；主力净流入约 -9934.07 万，主力净流入占比 -7.93%。
- 主力意图代理画像：日/周/月趋势为 `up/up/up`，60 日 VWAP 成本代理约 3.15，收盘价 3.46 高于该代理约 9.93%；吸筹分 60，拉升分 68，派发分 25。

这里的“成本”和“意图”都是可观测代理，不代表真实主力仓位、真实成本或确定意图。

## 模拟盘纪律

模拟盘的“买入/卖出”是程序纪律，不是实盘建议。

- 信号日收盘后形成交易意图。
- 下一交易日开盘模拟成交，避免前视偏差。
- 放量突破且资金确认：允许模拟买入，目标仓位 35%。
- 疑似吸筹/VCP 蓄势：允许轻仓模拟买入，目标仓位 25%。
- 买入前会检查主力意图代理画像：拉升分过低或派发风险过高时不买。
- 放量突破会做反追高过滤：离 60 日 VWAP 过远、高换手、量比过高但周线未确认时，不给标准仓位，可降级为追踪试仓。
- 强主力资金异动可以触发追踪试仓：目标仓位 10%，用于参与短期机会。
- 表面主力流出、小单承接、价格走弱或突破失败的“暗中吸筹候选”，默认必须等待支撑守住、价格修复、主力资金回流中的至少两项确认；未确认前不作为标准买点。
- 可用 `--enable-proof-probe` 单独回测小仓位早期试探，但该规则必须通过训练结果验证后才能晋级为默认纪律。
- 卖出、疑似出货、疑似派发、突破失败、止损：触发模拟卖出。
- 买入数量按 100 股整数倍，卖出遵守当前简化 T+1 规则。

## 目录

- `docs/monitoring-system.md`：实时异动监控系统设计。
- `docs/learning-summary.md`：理财学习总结。
- `docs/technical-plan.md`：数据源、规则、策略、回退和后续接入方案。
- `docs/trading-knowledge-graph.md`：交易知识图谱、节点关系和年化 10% 目标拆解。
- `docs/source-map.md`：交易所制度、公告网站和行情数据源参考。
- `src/wealth_lab/analysis.py`：真实数据 `watch-once` 和 `analyze-stock` 编排。
- `src/wealth_lab/replay.py`：日级历史回放和模拟盘驱动。
- `src/wealth_lab/accumulation_proof.py`：暗中吸筹假设验证器，统计历史相似形态的后续确认率。
- `src/wealth_lab/decision_explainer.py`：最新信号的买入/卖出/等待检查清单。
- `src/wealth_lab/behavior_model.py`：资金数据模型、行为动作模型和多节点交易状态。
- `src/wealth_lab/performance.py`：闭合交易、胜率、期望收益、盈亏比等收益预估指标。
- `src/wealth_lab/target_graph.py`：年化目标、交易图谱节点和阻塞原因评估。
- `src/wealth_lab/intent_features.py`：日/周/月趋势、VWAP 成本代理、OBV/ADL 和资金滚动画像。
- `src/wealth_lab/trade_discipline.py`：观察信号到模拟盘纪律的映射。
- `src/wealth_lab/signal_engine.py`：资金流、异动和形态标签。
- `src/wealth_lab/providers/historical_provider.py`：efinance/BaoStock 历史 K 线接入。
- `src/wealth_lab/fund_collector.py`：efinance/AKShare 资金流接入。
- `src/wealth_lab/dashboard.py`：终端看板。
- `src/wealth_lab/alert.py`：提醒消息生成。
- `runtime/wealth_lab.sqlite3`：本地 SQLite 缓存和审计库。

## 边界

- 免费开源行情源适合学习、研究、个人看盘和低频模拟。
- 商业使用、对外展示、自动交易或高频扫描，应使用授权行情商或券商合规接口。
- 所有真实交易前，必须人工核对交易所规则、券商规则、费用、税费、数据授权和程序化交易要求。
- 单股单年样本不能作为资金投放依据；至少要扩展到一组自选股和 30 笔以上闭合交易再看期望收益。
