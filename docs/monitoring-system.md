# 实时异动监控系统

系统定位：这是盘中观察、历史回放、模拟盘和提醒系统，不是自动交易系统。它的职责是发现值得人工复核的异动，并保留数据、规则和信号证据链。

## 主链路

```text
quote_collector.py / fund_collector.py / sector_collector.py
        |
        v
storage.py: SQLite 快照缓存和审计
        |
        v
signal_engine.py: 指标计算 + 异动筛选 + 形态标签
        |
        v
dashboard.py / alert.py: 看板和提醒
```

历史回放链路：

```text
historical_provider.py + fund_collector.py
        |
        v
features.py: rolling high/low/volume ratio, no future leakage
        |
        v
intent_features.py: daily/weekly/monthly trend + VWAP/OBV/ADL proxies
        |
        v
signal_engine.py
        |
        v
trade_discipline.py -> PaperBroker -> report.py
```

## 标准输出字段

个股监控结果包含：

- `fund_signal`：买入 / 卖出 / 分歧 / 疑似出货 / 疑似吸筹 / 无明显动作
- `pattern_tags`：疑似吸筹 / 疑似派发 / 放量突破 / 资金价格背离 / VCP蓄势 / 箱体突破 / 关键点确认 / 突破失败 / 无明显主力动作
- `anomalies`：突然放量 / 突破近20日高点 / 涨幅不大但成交额放大 / 临近涨停 / 临近跌停 / 板块同步异动 / 自选股纪律触发
- `score`：用于提醒排序，不是胜率。
- `reasons`：程序触发原因，便于复盘。
- `intent_profile`：主力意图代理画像，包含日/周/月趋势、60/120 日 VWAP 成本代理、3/5/10 日主力净流入、20/60 日换手、OBV/ADL 斜率、吸筹/拉升/派发分。
- `return_estimate`：基于闭合模拟交易的胜率、单笔期望、账户期望、平均盈亏、profit factor 和样本质量。
- `Main-Force Opportunity Radar`：所有接近买入的主力资金/形态异动都会列入雷达，风险管控只阻止交易，不删除信号。

`intent_profile` 是证据链，不是结论。程序不能知道真实主力仓位、真实成本和真实意图，只能用可见行情、成交量、成交额和资金流做代理估计。

## 监控和交易分层

系统必须分成两层：

1. 监控层：不因风险管控而删除异动。主力净流入、放量突破、VCP、疑似吸筹、资金价格背离都进入雷达和数据库。
2. 交易层：把信号分为标准买入、追踪试仓、仅观察。风险条件不足时不一定完全放弃，可以用小仓位追踪试仓；明显失败或派发风险则只观察。

因此，程序不是“过滤掉主力信号”，而是“完整记录主力信号，再决定用多大资金、以什么退出纪律参与”。

## 资金流口径

```text
主力净流入 = 超大单净流入 + 大单净流入
```

个股字段：

- 主力净流入
- 主力净流入占比
- 超大单净流入
- 大单净流入
- 中单净流入
- 小单净流入
- 涨跌幅
- 成交额
- 换手率

## 形态方法如何落成程序规则

Wyckoff：

- 疑似吸筹：低位附近、涨跌幅不大、主力净流入、超大单不明显流出、成交温和放大。
- 疑似派发：高位附近、成交或换手活跃、主力净流出、超大单净流出、小单净流入。

William O'Neil / CAN SLIM：

- 放量突破：突破近20日高点或平台压力位、成交量/量比明显放大、主力净流入为正。

Mark Minervini VCP：

- VCP 蓄势：接近阶段高点、波动收缩、成交萎缩、主力净流入不为负。

Jesse Livermore：

- 关键点确认：只在突破关键价位后升级信号。
- 突破失败：跌回突破位下方并伴随主力流出。

Darvas Box：

- 箱体突破：突破近 N 日箱体上沿、成交放大、主力资金同步流入。

## 主力意图代理画像

当前 `analyze-stock` 会为每个有资金流的历史交易日生成 `MainForceProfile`：

- 趋势：日线、周线、月线分别判断 `up`、`down`、`base_up`、`base_down` 或 `insufficient`。
- 成本代理：使用 60/120 日滚动 VWAP。它是市场成交成本代理，不是主力真实成本。
- 资金持续性：统计最近 3/5/10 条可用日级主力净流入。
- 筹码活跃度：统计 20/60 日换手率合计。
- 量价代理：使用 OBV 斜率和 ADL 斜率观察量价累积/派发倾向。
- 评分：输出 `accumulation_score`、`markup_score`、`distribution_score`。
- 阶段：输出 `accumulation_watch`、`markup_confirmed`、`distribution_risk`、`markdown_risk` 或 `neutral`。

模拟盘买入时会检查这些画像：突破信号需要拉升分达到阈值，疑似吸筹信号需要吸筹分达到阈值，派发分过高时不允许新开仓。

## 收益预估口径

收益预估不是明日收益预测。当前只使用已闭合模拟交易计算：

```text
单笔期望收益 = 平均(每笔闭合交易净收益率)
账户期望收益 = 平均(每笔闭合交易净盈亏 / 初始资金)
Profit Factor = 总盈利 / |总亏损|
```

样本质量分级：

- `no_closed_trades`：没有闭合交易，不能估计。
- `too_small_do_not_project`：闭合交易少于 5 笔，只能做功能验证。
- `low_confidence`：闭合交易 5-29 笔，只能观察。
- `medium_confidence`：闭合交易 30-99 笔，可用于策略比较。
- `higher_confidence`：闭合交易 100 笔以上，仍需跨周期验证。

程序不会把 1-2 笔交易的正收益当成可投放资金的依据。

## 买卖状态机

程序现在不再只输出标签，而是输出 `Trading Action Plan`：

- `WAIT`：空仓等待。没有完整买入路径，不追单。
- `BUY_NEXT_OPEN`：空仓，买入路径通过，下一交易日开盘模拟买入。
- `BUY_NEXT_OPEN` 也可能来自 `pursuit_probe_entry`：强主力资金异动但标准条件不完整时，用小仓位追踪试仓。
- `HOLD_WITH_STOP`：已有持仓，没有卖出触发，继续持有并盯止损。
- `SELL_NEXT_OPEN`：已有持仓，出现卖出/风控触发，下一交易日开盘模拟卖出。
- `NO_DATA`：没有足够信号。

### 买入路径 A：放量突破

全部满足才买：

1. `fund_signal == 买入`
2. `pattern_tags` 包含 `放量突破`
3. `markup_score >= 55`
4. `distribution_score <= 65`
5. `close_vs_vwap60 <= 12%`
6. `turnover_rate <= 15%`
7. 如果 `volume_ratio >= 2.5`，则 `weekly_trend` 必须为 `up`

满足后，下一交易日开盘按突破目标仓位模拟买入。

### 买入路径 B：疑似吸筹

全部满足才轻仓买：

1. `fund_signal == 疑似吸筹`
2. `pattern_tags` 包含 `疑似吸筹` 或 `VCP蓄势`
3. `accumulation_score >= 65`
4. `distribution_score <= 65`

满足后，下一交易日开盘按吸筹目标仓位模拟买入。

### 买入路径 C：追踪试仓

用于追主力资金异动。满足后用小仓位参与：

1. `fund_signal == 买入`
2. `main_net_inflow_pct >= 8%`
3. `super_large_net_inflow > 0`
4. 股价涨幅为正
5. `distribution_score <= 65`
6. 有 `放量突破`，或 `volume_ratio >= 1.5`
7. 没有 `突破失败` 或 `疑似派发` 标签

追踪试仓不是无脑追高，它的核心是：允许参与强异动，但仓位小，错了快速退出。

### 卖出路径

有持仓时，任一条件触发就卖：

1. `fund_signal == 卖出`
2. `fund_signal == 疑似出货`
3. `pattern_tags` 包含 `突破失败`
4. `pattern_tags` 包含 `疑似派发`
5. `distribution_score >= 75`
6. 当前价触发止损线

对 `000620` 最新状态，程序输出的是 `WAIT`：因为当前没有持仓，最新信号是 `卖出 + 突破失败`，所以不能买；如果已有持仓，这两个条件会触发卖出。

## 反追高过滤

标准买入仍然保留反追高过滤：

- 距 60 日 VWAP 成本代理超过阈值时，不追放量突破。
- 换手率过高时，不追放量突破。
- 量比极高但周线趋势未确认时，不追放量突破。

这些条件不再代表“完全不参与”，而是从标准买入降级为追踪试仓。2026-06-26 的 000620 会进入雷达并触发 `TRADE_READY_PURSUIT`，用小仓位参与；如果次日失败，按退出纪律卖出。

## 参考资料

- [Lee & Swaminathan, Price Momentum and Trading Volume](https://doi.org/10.1111/0022-1082.00280)：成交量会影响动量持续性和反转风险。
- [Moskowitz & Grinblatt, Do Industries Explain Momentum?](https://doi.org/10.1111/0022-1082.00146)：行业/板块动量是个股动量的重要背景。
- [IBD CAN SLIM](https://www.investors.com/ibd-university/can-slim/)：放量突破需要结合趋势、基本面和市场确认，不应只看单日放量。
- [StockCharts Wyckoff Method](https://chartschool.stockcharts.com/table-of-contents/market-analysis/wyckoff-analysis-articles/the-wyckoff-method-a-tutorial)：用价格、成交量和区间判断吸筹/派发。

## 当前命令

离线 demo：

```powershell
python run.py monitor-demo --alerts --limit 5
```

真实自选股单次监控：

```powershell
python run.py watch-once 000620 --alerts
```

真实单股历史回放和模拟盘：

```powershell
python run.py analyze-stock 000620 --days 370 --initial-cash 100000
```

## 当前实现状态

- efinance 今日分钟资金流已接入，空结果时降级到最近历史日级资金流。
- efinance 历史资金流已接入。
- efinance 历史行情已接入，但东方财富端点不稳定。
- BaoStock 历史行情已作为兜底接入。
- AKShare 资金流接口保留为备用适配器。
- 主力意图代理画像已接入历史回放和模拟盘纪律。
- 收益预估已接入历史回放报告。
- 主力机会雷达已接入历史回放报告，风险闸门不会删除观察信号。
- 追踪试仓已接入，强主力异动可以小仓位参与。
- `000620` 近一年样例已跑通，测试命令 `python -m pytest` 当前为 18 项通过。
- 当前默认不接实盘交易，先跑至少 1-3 个月模拟盘和复盘。
