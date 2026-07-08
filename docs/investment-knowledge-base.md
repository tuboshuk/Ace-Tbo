# Investment Knowledge Base for A-Share Wealth Lab

版本：Worker A v0.1  
范围：研究、回测、纸面交易规则库；不构成真实买卖建议。  
目标：为策略 worker 提供可程序化假设，服务于把项目回测年化目标推进到 10%。10% 是研究门槛，不是收益承诺。

## 使用原则

1. 任何规则必须能被历史数据逐日复现，不能依赖事后解释。
2. 每个新规则必须记录样本内、样本外、多股票、交易次数、最大回撤、滑点/手续费敏感性。
3. 资金流、成交量、开盘缺口只能作为概率证据，不能单独证明“主力一定在收集筹码”。
4. 参数越多，越容易过拟合；每次调参都要记录试验次数和失败结果。

## 来源清单

- 上海证券交易所交易时间与集合竞价：[SSE Trading Schedule](https://english.sse.com.cn/start/trading/schedule/)，[Trading Rules of Shanghai Stock Exchange 2023 Revision PDF](https://english.sse.com.cn/start/sserules/stocks/trading/c/10644064/files/7d100419dcca456b97cabaf2dfd3b904.pdf)
- 趋势跟随长期证据：Hurst, Ooi, Pedersen, [A Century of Evidence on Trend-Following Investing](https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing)
- 横截面动量：Jegadeesh, Titman, [Returns to Buying Winners and Selling Losers](https://ideas.repec.org/a/bla/jfinan/v48y1993i1p65-91.html)
- 技术形态可算法化：Lo, Mamaysky, Wang, [Foundations of Technical Analysis](https://www.nber.org/papers/w7613)
- 成交量与动量生命周期：Lee, Swaminathan, [Price Momentum and Trading Volume](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=92589)
- 流动性与冲击成本：Amihud, [Illiquidity and Stock Returns](https://archive.nyu.edu/handle/2451/26706)
- 注意力驱动交易：Barber, Odean, [All That Glitters](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=460660)
- 止损单风险：SEC Investor.gov, [Stop, Stop-Limit, and Trailing Stop Orders](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-15)
- 仓位与风险预算：CME Group, [The 2% Rule](https://www.cmegroup.com/education/courses/trade-and-risk-management/the-2-percent-rule)
- 回测过拟合：Bailey, Borwein, Lopez de Prado, Zhu, [The Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253)

## 01. 趋势不是买点，是交易背景过滤器

原则：趋势跟随和中期动量有长期研究证据，但趋势信号滞后，不能把“已经涨了”直接当作买点。程序应先判断当前是否处于可交易趋势，再寻找低风险触发点。

可程序化特征：
- `close > ma20 > ma60` 或 `ma20_slope > 0` 表示短中期上行背景。
- 近 `20/60/120` 日收益分位数，避免只看单日涨幅。
- `close_to_high_20_pct`、`drawdown_from_high_20_pct` 区分突破、回踩和追高。
- 市场状态过滤：指数或同板块趋势向下时，降低个股买入权重。

风险：
- 趋势信号容易在后段才出现，高位放量可能是分歧扩大或派发。
- A 股个股受涨跌停、停牌、题材轮动影响，趋势延续性不能照搬海外期货/美股结论。

可验证假设：
- 在 `volume-probe` 中，只允许 `ma20_slope > 0` 且 `close >= ma60` 的试错买入，是否提高胜率并降低回撤。
- 对比不加趋势过滤、加个股趋势过滤、加指数趋势过滤三组结果。

可能接入模块：
- `src/wealth_lab/features.py`
- `src/wealth_lab/volume_probe.py`
- `src/wealth_lab/trade_discipline.py`
- `src/wealth_lab/training.py`

## 02. 成交量要分阶段：放量不是天然利好

原则：成交量代表参与度和分歧，不等于主力净买入。研究显示历史成交量会影响动量的幅度和持续性，高成交量的赢家可能更接近动量后段，低成交量上涨可能代表更早期的趋势扩散。

可程序化特征：
- `volume_ratio_5 = volume / avg(volume, 5)`
- `amount_ratio_5 = amount / avg(amount, 5)`
- `turnover_rate` 与 `turnover_rate_zscore_20`
- `price_change_pct` 与 `amount_ratio_5` 组合成阶段：
  - 温和放量上涨：`0 < change_pct <= 5` 且 `1.2 <= amount_ratio_5 <= 2.5`
  - 极端注意力上涨：`change_pct >= 7` 且 `amount_ratio_5 >= 3`
  - 缩量回踩：`change_pct < 0` 且 `volume_ratio_5 < 0.8`

风险：
- 单日放量可能是消息刺激、游资接力或出货，不足以证明筹码收集。
- 成交量阈值跨股票不可直接固定，应使用分位数或相对均值。

可验证假设：
- 把 `volume_breakout` 拆成“温和放量突破”和“极端放量突破”，分别统计次日开盘买入后的胜率、收益、失败率。
- 对 `amount_ratio_5 >= 3` 的突破增加开盘确认门槛，测试是否减少追高亏损。

可能接入模块：
- `src/wealth_lab/volume_replay.py`
- `src/wealth_lab/volume_probe.py`
- `src/wealth_lab/report.py`

## 03. 开盘价应由资金量和近几日交易量推断，而不是固定区间

原则：A 股开盘由集合竞价形成，开盘缺口反映隔夜信息、挂单意愿和交易者情绪。程序不应固定使用 `+3%/-3%`，而应用当前资金量、成交额、近几日量价状态，在历史同类样本中估计“合理开盘区间”。

可程序化特征：
- 当前信号日特征：`node_type`、`change_pct`、`amount_ratio_5`、`volume_ratio_5`、`turnover_rate`、`range_position`。
- 历史同类样本：只使用当前信号日前已经发生的样本，计算 `next_open_gap_pct = next_open / signal_close - 1`。
- 动态预期开盘：
  - `expected_gap_pct = weighted_mean(similar_cases.next_open_gap_pct)`
  - `expected_low/high = expected_gap_pct +/- k * weighted_std`
  - 相似度距离包含 `node_type`、`amount_ratio_5`、`volume_ratio_5`、`change_pct`、`range_position`。
- 实际开盘分类：
  - `inside_expected_open_band`
  - `above_expected_attention_chase`
  - `below_expected_failed_continuation`
  - `discount_open_above_support`

风险：
- 如果同类样本少，动态区间会不稳定；低样本必须降权或禁止交易。
- 集合竞价挂单数据缺失时，只能用日线开盘价反推，无法还原 9:15-9:25 的撤单和竞价强弱。

可验证假设：
- 对每个买点记录 `actual_gap_pct - expected_gap_pct`，检验超预期高开是否降低后续两日收益。
- 对缩量回踩节点，测试“低于预期开盘但仍高于信号日低点”是否是更好的试错买点。

可能接入模块：
- `src/wealth_lab/volume_probe.py`
- `src/wealth_lab/trade_discipline.py`
- `src/wealth_lab/replay.py`
- `src/wealth_lab/report.py`

## 04. 注意力交易解释高开风险：越热越不能盲追

原则：注意力驱动研究显示，异常成交量、极端单日收益和新闻会吸引投资者买入。程序可以把极端放量高开理解为“注意力溢价”，需要确认持续性，否则容易买在情绪峰值。

可程序化特征：
- `attention_score = rank(abs(change_pct)) + rank(amount_ratio_5) + rank(gap_pct)`
- `hot_open = actual_gap_pct > expected_high_gap_pct`
- `hot_breakout = signal_change_pct >= 7 and amount_ratio_5 >= 2.5`
- 买入限制：`hot_open` 且开盘后无法站稳信号日高点时取消或缩小仓位。

风险：
- 注意力不一定马上反转，强势题材可能继续连板。
- 仅用日线无法判断开盘后 5-30 分钟承接，必须用保守仓位对冲信息不足。

可验证假设：
- 对 `attention_score` 分位数分组，验证最高分位买点的平均收益是否低于中等分位。
- 对 `hot_open` 样本，比较“直接买入”和“等待收盘仍强再买”的差异。

可能接入模块：
- `src/wealth_lab/intent_features.py`
- `src/wealth_lab/trade_discipline.py`
- `src/wealth_lab/trade_quality.py`

## 05. 突破失败比突破本身更重要

原则：形态必须算法化，不能凭眼睛看图。突破买点只有在价格越过关键区间、成交配合、且后续没有快速跌回区间时才有统计意义；快速跌回说明突破失败或供应压制。

可程序化特征：
- `breakout_level = high_20`
- `breakout_close = close > high_20_prev`
- `breakout_volume_ok = 1.2 <= amount_ratio_5 <= 3.0`
- 失败信号：
  - 次日 `open < signal_close` 且 `close < breakout_level`
  - 两日内 `low < signal_low`
  - 放量突破后缩量不能维持，或放量长上影
- 失败后动作：取消买入、提前退出、降低下一次同类节点评分。

风险：
- 有些强势股突破后不会回踩，过度等待会错过。
- 失败规则太敏感会提高空仓率，降低交易次数。

可验证假设：
- 在 `volume_breakout` 中加入“两日内跌回突破位则强制退出”，统计收益/回撤变化。
- 把突破后次日低开分为 `above_signal_low` 与 `below_signal_low` 两类，比较失败概率。

可能接入模块：
- `src/wealth_lab/rules.py`
- `src/wealth_lab/volume_replay.py`
- `src/wealth_lab/trade_discipline.py`
- `src/wealth_lab/replay.py`

## 06. 缩量回踩是低风险试错候选，但必须有支撑边界

原则：低价买入不是买下跌，而是在趋势背景仍有效时买分歧收敛。缩量回踩的核心是卖压下降，买点必须靠近可定义支撑，亏损边界要小。

可程序化特征：
- 趋势背景：`close > ma60` 或 `ma20_slope > 0`
- 缩量：`volume_ratio_5 < 0.8` 或 `amount_ratio_5 < 0.8`
- 支撑：`support = max(low_20, vwap_60, breakout_level * 0.985)`
- 入场风险：`risk_pct = (entry_price - support) / entry_price`
- 只允许 `risk_pct <= 3%` 的小仓试错。

风险：
- 缩量也可能是无人接盘，尤其在趋势转弱和流动性下降时。
- 支撑位如果由未来数据计算会造成未来函数。

可验证假设：
- 对 `shrink_pullback` 节点，要求 `risk_pct <= 3%` 是否提高期望值。
- 对比 `discount_open_above_support` 与 `discount_open_below_support` 的次日/两日收益。

可能接入模块：
- `src/wealth_lab/trade_quality.py`
- `src/wealth_lab/volume_probe.py`
- `src/wealth_lab/trade_discipline.py`

## 07. 流动性决定策略能不能真实成交

原则：成交额和流动性不是只用来找机会，也要用来过滤不能交易的机会。低流动性股票可能显示高收益回测，但实际滑点和冲击成本会吞掉利润。

可程序化特征：
- `amount_avg_20`
- `amihud_illiq = avg(abs(return_pct) / amount, 20)`
- `position_to_amount = order_value / amount_avg_20`
- 流动性门槛：
  - 禁止 `amount_avg_20` 过低的样本进入训练候选。
  - 若 `position_to_amount > 0.5%`，提高滑点或降低仓位。

风险：
- 小盘低流动性可能有更大弹性，但成交不可控。
- 当前回放如果没有滑点模型，会高估低流动性交易收益。

可验证假设：
- 对所有策略结果按 `amount_avg_20` 分组，确认收益是否集中在不可成交的小额样本。
- 在训练中加入成交额分位过滤和滑点压力测试，看 10% 年化目标是否仍成立。

可能接入模块：
- `src/wealth_lab/replay.py`
- `src/wealth_lab/performance.py`
- `src/wealth_lab/training.py`

## 08. 仓位来自亏损预算，不来自信心

原则：仓位应由账户可承受亏损和止损距离计算，而不是由“看好程度”直接决定。试错买入应小仓，只有统计证明和走势确认后才允许加仓。

可程序化特征：
- `account_risk_pct`：单笔最大账户风险，例如 `0.3%-1.0%`。
- `stop_distance_pct = (entry_price - stop_price) / entry_price`
- `target_weight = min(max_weight, account_risk_pct / stop_distance_pct)`
- 若 `opening_classification` 为不确定，则 `target_weight *= 0.5`。
- 连续亏损降档：最近 `N` 笔亏损或权益回撤超过阈值，自动降低仓位。

风险：
- 止损价格不是保证成交价，快速下跌和跌停会导致实际亏损超过预算。
- 仓位过小会让收益无法达到目标，仓位过大会让少数错误毁掉策略。

可验证假设：
- 把 `volume_price_probe_weight` 从固定 6% 改为基于 `risk_pct` 的动态仓位，比较收益和最大回撤。
- 对开盘高于预期的买点，只允许半仓或取消，检验收益/交易次数平衡。

可能接入模块：
- `src/wealth_lab/trade_discipline.py`
- `src/wealth_lab/paper.py`
- `src/wealth_lab/replay.py`

## 09. 止损不是证明错误的唯一方式，时间和结构也能证明错误

原则：买入假设必须有失效条件。失效条件可以是价格跌破支撑、突破失败、资金/成交额不再支持、或规定时间内没有兑现预期。

可程序化特征：
- 价格止损：`close < support` 或 `open < signal_low`
- 结构止损：突破后两日内回到箱体内。
- 时间止损：买入后 `2-5` 个交易日未达到 `target_progress_pct`。
- 资金止损：主力/大单净流入转负且价格弱于成本。
- 缺口止损：次日开盘低于动态预期下沿且节点为热突破。

风险：
- 过短时间止损会错过慢趋势。
- A 股 T+1 与涨跌停会让止损无法按设定价格执行。

可验证假设：
- 对 `volume-probe` 分别测试价格止损、结构止损、时间止损、组合止损。
- 统计每类止损触发后的“如果不卖”的后续收益，确认止损是否真实减少损失。

可能接入模块：
- `src/wealth_lab/trade_discipline.py`
- `src/wealth_lab/replay.py`
- `src/wealth_lab/trade_quality.py`

## 10. 样本外验证是晋级门槛，不是可选项

原则：达到 10% 年化不能靠反复调参碰出来。回测必须记录所有试验，包括失败版本；训练集表现必须通过样本外和多股票验证。

可程序化特征：
- 按时间切分：前 60%-70% 训练，后 30%-40% 样本外验证。
- 按标的切分：部分股票用于调参，未参与调参的股票用于验证。
- 记录全部候选：参数、收益、回撤、胜率、交易数、profit factor、expectancy。
- 晋级条件：
  - 样本外年化收益达到或接近 10%。
  - 最大回撤可接受。
  - 交易数足够，不是 1-2 笔偶然盈利。
  - 多股票结果不过度依赖单一标的。

风险：
- 试验次数越多，最好结果越可能是噪声。
- 样本不足时，提高收益目标会诱导过拟合。

可验证假设：
- 在 `training.py` 中保存每一次候选，不只保存最优结果。
- 对当前策略加入 walk-forward 验证：每月只使用此前数据重新估计开盘区间和阈值。

可能接入模块：
- `src/wealth_lab/training.py`
- `src/wealth_lab/performance.py`
- `docs/persistent-training-log.md`

## 最值得交给策略 Worker 的 5 个假设

1. 动态开盘区间优先级最高：用 `node_type + amount_ratio_5 + volume_ratio_5 + change_pct + range_position` 估计次日合理开盘，取消明显高于预期的追高买入。
2. 拆分放量突破阶段：温和放量突破可试错，极端放量高开只允许缩仓或等待确认，验证能否减少无效买点。
3. 缩量回踩低风险试错：只在趋势背景有效且入场到支撑的 `risk_pct <= 3%` 时买入，目标是提高胜率而不是追求单笔暴利。
4. 动态仓位替代固定仓位：用 `account_risk_pct / stop_distance_pct` 计算目标仓位，并对高注意力开盘降仓。
5. Walk-forward 防过拟合：所有开盘预期、阈值和节点胜率只能用当日之前数据滚动估计，并在样本外、多股票上决定是否晋级。

## 11. 成交量必须和方向、阶段、开盘执行一起验证

外部依据：
- Chordia, Roll, Subrahmanyam, 2002, Journal of Financial Economics, Order Imbalance, Liquidity, and Market Returns：订单不平衡比单纯成交量更能表达买卖方向压力；单纯成交量会隐藏买卖方向差异。参考：https://www.sciencedirect.com/science/article/abs/pii/S0304405X02001368
- Lo, Mamaysky, Wang, 2000, Journal of Finance, Foundations of Technical Analysis：技术形态需要变成可重复识别的算法，而不是主观画线。参考：https://www.nber.org/papers/w7613
- Sullivan, Timmermann, White, 1999, Journal of Finance, Data-Snooping, Technical Trading Rule Performance, and the Bootstrap：大量技术规则反复试验会产生数据挖掘偏差，必须记录失败版本并做样本外/多标的验证。参考：https://ideas.repec.org/a/bla/jfinan/v54y1999i5p1647-1691.html
- Brock, Lakonishok, LeBaron, 1992, Journal of Finance, Simple Technical Trading Rules and the Stochastic Properties of Stock Returns：移动平均和交易区间突破等简单技术规则可以被长期数据检验，但必须用统计验证而不是单次成功解释。参考：https://ideas.repec.org/a/bla/jfinan/v47y1992i5p1731-64.html

程序化规则：
- `volume_ratio` 只作为一级分流，不直接产生买入结论。
- `dry_up_base` 必须结合 `stage`、`weekly_trend`、`distribution_score`、`main_flow_10` 和次日开盘到信号日低点的 `support_distance_pct`。
- 下跌阶段的缩量不是天然吸筹；如果 `stage=markdown_risk` 或 `weekly_trend=down`，试错买点必须默认被阻断，除非有更强的独立证据。
- 如果 `main_flow_10` 可用且为负，说明中期资金方向没有支持，不应只因为 3/5 日短流入就放大仓位。
- 次日开盘必须靠近可用支撑，不能过近到轻易跌破，也不能过远到止损距离过大。

本轮可验证假设：
- 新增 `volume_price_dry_up_flow_support_guard_probe`，只针对 `dry_up_base` 加守门：
  - 阻断 `markdown_risk`。
  - 阻断 `weekly_trend=down`。
  - `distribution_score <= 40`。
  - 若 `main_flow_10` 可用，则要求 `main_flow_10 >= 0`。
  - 次日开盘支撑距离限制在 `0.5%..2.0%`。
  - 次日高开不超过 `1.0%`。

当前验证结果：
- 在 `000620/002031` 双票近一年回放中，`002031` 从 `volume_price_risk_sized_probe` 的 `23` 笔、`0.15%`、每笔期望 `0.03%`，改善到 `7` 笔、`2.00%`、每笔期望 `2.50%`。
- 在 6 股池近一年回放中，该候选聚合为 `18` 笔、平均收益 `0.08%`、平均最大回撤 `0.14%`、平均分 `20.0`，不如 v021 的 `0.15%` 聚合收益。
- 结论：该规则对 `002031` 的 dry-up 噪音过滤有效，但还不是跨股票通用最优策略；只能作为观察候选，不晋级默认策略。

## 12. 经典读盘书单必须先转成可验证交易剧本

原则：经典书单不能直接转成买卖参数。程序需要把书中的观点转换成 `source_id -> lens -> hypothesis -> observable_fields -> group_by -> metrics`，再用现有回放证据判断该假设是 `INSUFFICIENT_EVIDENCE`、`OBSERVE_ONLY` 还是 `REVIEW_CANDIDATE`。`REVIEW_CANDIDATE` 仍只是下一轮方案候选，不是下单规则。

书单到程序 lens：
- `coulling_wyckoff_weis`：量价与主力行为 lens。对应 VPA、Wyckoff、Weis，核心是假设“努力和结果必须一致”：放量突破要有后续需求，缩量回踩要真正止跌，表面卖出吸收必须后续修复。
- `nison_bulkowski_edwards_magee`：K 线与结构 lens。形态必须结合位置、阶段和确认，单个长上影、反包、突破、箱体、支撑压力不能直接交易。
- `oneil_minervini_livermore`：趋势、关键点和纪律 lens。突破、VCP、关键点和试探仓都必须由阶段、量能、失效位和后续跟随验证。
- `shannon_livermore`：多周期与开盘情境 lens。高开、低开、预期开盘区间和支撑距离共同决定是否观察、试错、减仓或退出。
- `edwards_magee_livermore`：支撑风险 lens。买点不是“低价”，而是离失效位足够近且不容易立即跌破；仓位来自亏损预算。

当前可程序化字段：
- 买入前：`TradeThesis.buy_type`、`TradeThesis.vpa_archetype`、`TradeThesis.stage`、`expected_holding_days`、`expected_follow_through`、`invalidation_price`。
- 买入后 1-3 天：`ThesisCheck.status`、`volume_state`、`main_flow`、`confirmations`、`warnings`、`invalidations`。
- 持有中：`TradeStory.verdict`、`holding_evidence`、`must_hold_conditions`、`must_exit_conditions`。
- 开盘和仓位动作回放：`PositionActionReview.gap_pct`、`gap_bucket`、`opening_classification`、`support_distance_pct`、`position_action`。
- 知识假设复盘：`KnowledgeHypothesisReview.source_id`、`lens`、`hypothesis_id`、`bucket`、`return_pct`、`verdict`、`diagnostic_status`。

五个核心假设：
- `effort_result_must_confirm_stage`：量价读盘必须看 `vpa_archetype` 后续是否被确认，不能因单日主力流入或放量直接买入。
- `pattern_requires_location_and_confirmation`：形态必须和 `buy_type + stage` 一起统计，突破和回踩在不同阶段含义不同。
- `opening_gap_changes_risk_reward`：开盘缺口必须按 `opening_classification + gap_bucket` 分组，不能固定用高开/低开百分比解释人性。
- `support_distance_controls_probe_size`：支撑距离决定试错质量，过近容易马上跌破，过远止损成本过大。
- `hold_only_while_thesis_is_valid`：持有不是因为没有触发卖出，而是因为 `confirmations` 压过 `warnings/invalidations`。

当前验证结果：
- 10 股池 v027 回放显示，核心候选 `volume_price_quiet_exception_flow_guard_probe` 的 `effort_vs_result_breakout` 分组为 `11` 笔、胜率 `54.55%`、平均收益 `2.35%`、`REVIEW_CANDIDATE`；但 `no_supply_pullback_or_wash` 为 `21` 笔、平均收益 `-0.52%`，`quiet_consolidation_no_supply_test` 为 `5` 笔、平均收益 `-0.48%`，均为 `OBSERVE_ONLY`。
- 同一核心候选的 `confirmations_dominate` 分组为 `10` 笔、平均收益 `5.53%`，而 `invalidated` 分组为 `18` 笔、平均收益 `-2.35%`。这说明“确认后持有”和“失效后退出”是下一轮应重点研究的方向。
- `disguised_accumulation_probe` 的 `apparent_selling_absorption_test` 为 `97` 笔、胜率 `32.99%`、平均收益 `-1.03%`，继续证明“表面主力流出 + 小单流入 = 暗中吸筹”不能直接交易。
- 当前所有结果仍未达到年化 10% 或晋级门槛；知识假设只能用于下一轮 A/B/C 分析，不允许直接接入执行层。

## 13. 学习结果进入执行层时必须先做窄实验

原则：只有已经在同池诊断中显示正证据的观察簇，才允许进入执行层实验；已经显示负期望的观察簇必须先变成拦截规则，而不是继续当买点。执行实验必须保持可回滚、可对照、可复盘，不能直接替换 core 策略。

v028 执行实验：
- 允许簇：`effort_vs_result_breakout`，执行 node 为 `volume_breakout`。
- 拦截簇：`no_supply_pullback_or_wash`，执行 node 为 `shrink_pullback`。
- 拦截簇：`quiet_consolidation_no_supply_test`，执行 node 为 `quiet_consolidation`。
- 同时排除 `dry_up_base`，因为本轮命题是“只交易突破簇”，不是重新解释 dry-up。

执行纪律：
- 买入后如果收盘跌破支撑，标记 `invalidated`，下一交易日开盘卖出。
- 买入后 1-3 个持仓 bar 内如果 `confirmations <= warnings`，标记 `no_follow_through`，下一交易日开盘卖出。
- 如果 `confirmations > warnings`，允许持有到 3-5 个 bar，并在最大持有窗口退出。
- 卖出 reason 必须记录 `support`、`hold_bars`、`confirmations`、`warnings`、`invalidations`，方便后续逐笔复盘。

当前验证结果：
- v028 新候选 `volume_price_breakout_follow_through_probe` 在 10 股池中为 `9` 笔、`4` 个交易股票、平均期望 `5.57%`、平均收益 `0.21%`、平均最大回撤 `0.20%`。
- 同池 core 候选仍为 `38` 笔、`9` 个交易股票、平均期望 `0.31%`、平均收益 `-0.05%`、平均最大回撤 `0.43%`。
- v027 core 基线为 `38` 笔、`9` 个交易股票、平均期望 `0.31%`、平均收益 `-0.08%`、平均最大回撤 `0.46%`。
- 新候选的 `effort_vs_result_breakout` 诊断为 `9` 笔、胜率 `55.56%`、平均收益 `5.57%`、`REVIEW_CANDIDATE`。

结论：
- 只交易突破簇能明显提高平均期望和平均收益，但会把交易数从 `38` 降到 `9`，交易股票从 `9` 降到 `4`。
- 因此它是有效研究方向，不是可晋级策略；它没有满足“交易数、交易股票数、回撤不退化”的 5% 改善纪律，也没有证明年化 10%。
- 下一步不应再泛化加指标，而应只分析新候选的亏损突破样本，优先验证 `support_distance > 5%`、高开 gap、`warnings_dominate` 和 `invalidated` 是否能成为更窄的突破守门规则。

## 14. 宽支撑不是天然坏信号，必须和开盘需求一起判断

原则：突破买点的支撑距离越宽，止损成本越高，但这不等于所有宽支撑都要拦截。宽支撑里可能同时包含情绪失败样本和真正的强趋势样本。程序不能把 `support_distance > 5%` 机械当成坏信号，必须结合次日开盘是否有需求、是否过热、以及买入后 1-3 天是否继续验证。

v029 可验证规则：
- 仍只允许 `volume_breakout / effort_vs_result_breakout`。
- 如果次日开盘 `gap > 3.0%`，视为突破开盘过热，取消试错买入。
- 如果 `support_distance > 8.0%` 且 `gap < 0.5%`，视为“极宽支撑但开盘没有需求溢价”，取消试错买入。
- 不把 `support_distance > 5%` 做成一刀切，因为 v028 证据显示 `000592` 与 `600879` 的大赢家也处于宽支撑区域。

当前验证结果：
- v028 `volume_price_breakout_follow_through_probe`：`9` 笔、`4` 个交易股票、平均期望 `5.57%`、平均收益 `0.21%`、平均最大回撤 `0.20%`。
- v029 `volume_price_breakout_opening_guard_probe`：`6` 笔、`4` 个交易股票、平均期望 `11.12%`、平均收益 `0.27%`、平均最大回撤 `0.06%`。
- `601929` 的三笔 v028 亏损突破被拦截后，单票从 `4` 笔、`-0.20%` 收益、`1.44%` 最大回撤、`-2.39%` 每笔期望，改善为 `1` 笔、`0.45%` 收益、`0.06%` 最大回撤、`7.06%` 每笔期望。

结论：
- 这条规则证明了“亏损簇可以被更窄的开盘守门减少”，但没有证明策略达标。
- 交易数从 `9` 继续降到 `6`，低于 `30` 笔晋级门槛，也没有扩大高质量机会池。
- 下一步不应继续加防守阈值，而应解释 v029 保留交易中 `000592`、`600879` 的宽支撑赢家为什么有效，再寻找类似结构来扩大样本。

## 15. 承接确认必须分层使用，不能让强突破全部等待

原则：信号后的承接证明是重要的交易剧本工具，但它不是免费的过滤器。强 `volume_node:volume_breakout` 有时本身就是启动资金的直接表达，如果所有强突破都被迫等一根 K 线确认，可能会错过主升段；而 `accumulation_watch` 这类弱结构又不能直接买，必须先观察承接。

v030 可验证规则：
- 信号日出现 `volume_breakout / effort_vs_result_breakout` 时，不立即买入，先记录 `volume_price_breakout_observe`。
- 下一根 K 线低点不能跌破信号日低点，收盘不能低于信号日收盘。
- 量价状态不能是 `volume_down_risk` 或 `high_volume_stall`。
- 主力流数据可用时不能转负。
- 确认后才进入再下一交易日开盘买入；持仓继续使用 follow-through 退出。

当前验证结果：
- v028 `volume_price_breakout_follow_through_probe`：`9` 笔、`4` 个交易股票、平均期望 `5.57%`、平均收益 `0.21%`、平均最大回撤 `0.20%`。
- v029 `volume_price_breakout_opening_guard_probe`：`6` 笔、`4` 个交易股票、平均期望 `11.12%`、平均收益 `0.27%`、平均最大回撤 `0.06%`。
- v030 `volume_price_breakout_confirmation_entry_probe`：`1` 笔、`1` 个交易股票、平均期望 `1.52%`、平均收益 `0.02%`、平均最大回撤 `0.00%`。
- 唯一 v030 闭合交易是 `000620` 的 `accumulation_watch`，收益 `1.52%`，但持仓中出现连续 `flow_out_with_price_weakness` 警告，最终由突破失败退出。

结论：
- v030 证明了“确认后再入场”不能粗暴套到所有突破信号上；它没有扩大高质量机会池，反而从 v029 的 `6` 笔降到 `1` 笔。
- 下一步更合理的知识规则是分层：强 `breakout_start:volume_node:volume_breakout` 可以保留小仓直接试探并用 1-3 日 follow-through 纠错；弱 `breakout_start:accumulation_watch` 必须进入观察队列，确认后才允许试错。
- 如果分层后样本仍不足，问题应转向股票池和时间区间，而不是继续加确认阈值。

## 16. 正期望不等于可赚钱，资金利用率必须进入晋级门槛

原则：单笔平均期望为正只能说明某类已交易样本有观察价值，不能证明策略能达到年化目标。一个策略如果全年大部分时间空仓，即使少数交易的单笔期望很高，账户级收益也可能接近 0。晋级判断必须同时检查交易质量和资金是否真正部署。

v031 可验证规则：
- 每个候选必须输出 `holding_days`、`cash_days`、`holding_utilization_pct`、`avg_position_pct`、`max_position_pct`。
- `filtered_buy_signals` 只统计合格买点被守门条件拦截；`node_not_allowed:normal` 必须单独归入 `ordinary_non_signal_days`。
- 晋级门槛必须至少包含：
  - 闭合交易数 `>= 30`。
  - 跨股票交易覆盖 `>= 2`。
  - 平均闭合交易期望 `>= 0.50%` 成本/滑点缓冲。
  - 持仓利用率 `>= 1.00%`。
  - 平均仓位 `>= 0.10%`。
  - 聚合收益达到配置的目标年化收益。
- 错过大涨必须拆成三类：`filtered`、`ordinary_non_signal`、`unrecognized`。其中 `ordinary_non_signal` 说明程序没有识别出合格买点，不应被解释为守门条件错杀。

当前验证结果：
- 100 股随机非创业板池中，`volume_price_breakout_follow_through_probe` 有 `32` 笔闭合交易和 `3.14%` 平均期望，但平均收益只有 `0.06%`，持仓利用率只有 `0.39%`，平均仓位只有 `0.02%`，因此新门槛为 `OBSERVE`。
- 同一候选的旧过滤观察 `23617` 个拆分为合格过滤 `8478` 和普通非信号 `15139`；最高合格过滤原因为 `node_not_allowed:dry_up_base`。
- 核心 `volume_price_quiet_exception_flow_guard_probe` 有 `443` 笔交易和 `1.89%` 持仓利用率，但平均期望只有 `0.18%`，低于成本/滑点缓冲。

结论：
- v031 验证了低收益的一个关键原因：策略并没有足够多、足够大地进入市场。
- 下一步不能只问“这个买点单笔赚钱吗”，还必须问“这个买点一年能让资金在市场里待多久、用多大仓位、错过的大涨到底是没识别还是被过滤”。
- 扩大股票池后仍不能晋级的候选，必须优先改进识别覆盖和资金利用率，而不是继续添加更窄的防守参数。
## 17. v032 错过机会诊断：不要把开盘守门误当成主要瓶颈

- v032 保留 `volume_price_breakout_opening_guard_probe` 的交易规则，只新增错过机会诊断。
- 同一 100 股池一年回放中，该候选有 `30` 笔闭合交易、`20` 盈、`10` 亏，胜率 `66.67%`，平均单笔期望 `5.39%`。
- 账户口径平均收益仍只有 `0.07%`，核心原因是持仓利用率只有 `0.36%`，平均仓位只有 `0.02%`。
- 错过大涨分类显示：`ordinary_non_signal=1355`、`not_volume_breakout=498`、`history_gate_failed=114`、`opening_guard_cancel=16`、`other_filtered_signal=3`。
- 因此当前主要瓶颈不是 `opening_guard` 误杀。开盘守门只解释了少量错过样本。
- 更大的问题是识别层：大量大涨前一天被归为普通非信号日，或被归为非 `volume_breakout` 节点。
- 下一步研究应优先问：
  - 普通非信号日中的大涨样本是否有可事前识别的量价/资金/集合竞价结构？
  - `dry_up_base`、`shrink_pullback`、`quiet_consolidation` 中是否存在独立的高质量子簇，而不是整体放开？
  - `history_gate_failed` 中的低样本强突破，是否应该用跨股票同类样本补足历史，而不是要求单股自身有足够历史案例？

## 18. v033 默认策略池收敛：只保留一个主策略基准

- v033 后，`train-replay` 默认只运行 `volume_price_breakout_opening_guard_probe`。
- 其他历史候选不再参与默认训练报告，避免报告继续被已否定或搁置的策略噪声污染。
- 这不是收益提升，也不是策略晋级证明；它只是把研究主线收敛到一个基准。
- 后续如果要恢复新策略，必须从错过机会分析中提出一个明确子结构，并作为新的受控实验进入，而不是恢复历史大候选池。
