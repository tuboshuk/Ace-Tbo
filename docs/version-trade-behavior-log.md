# 版本交易行为记录

用途：记录每一版程序在训练时“程序认为自己看到了什么、为什么买、为什么卖、为什么跳过”，方便多 Worker 监督和回顾。

边界：这里只记录研究回放和模拟交易行为，不记录真实资金建议；策略逻辑由策略 Worker 修改，本文件和工具只负责版本行为台账。

## 固定记录模板

- 版本/动作编号：
- 策略候选：
- 训练命令：
- 股票池：
- 交易笔数：
- 买入原因：
- 卖出原因：
- 跳过原因：
- 程序当时认为的市场状态：
- 收益/回撤/期望：
- 是否达到年化 10%：
- 下一步：

## 使用方式

后续每完成一次训练或策略版本变更，用 `wealth_lab.version_journal.VersionTradeBehaviorEntry` 生成记录，再通过 `append_version_entry` 追加到本文件。

本台账只回答“这一版程序当时如何理解市场和交易行为”，不替代 `docs/persistent-training-log.md` 的动作复盘，也不修改任何现有训练逻辑。

## 版本 v015 / 动作 015

- 记录时间：2026-07-07T08:26:06+00:00
- 策略候选：volume_price_trial_probe
- 训练命令：
```shell
python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000
```
- 股票池：000620, 000001, 300750, 600519, 002594, 300059
- 交易笔数：22
- 买入原因：
  - 同类量价节点通过历史胜率和平均收益门槛后，进入小仓位次日开盘试错
  - 实际开盘落在由成交额、近几日成交量、节点量比、涨跌幅和区间位置推断的动态预期范围内
- 卖出原因：
  - volume-probe 默认在下一个可执行开盘进行定时退出
  - 若先触发资金流风险、疑似派发或止损，则由风险退出优先处理
- 跳过原因：
  - 开盘低于突破节点动态预期范围，视为延续失败
  - 缩量或整理节点高于预期中枢过多，视为追价风险
  - 热突破预期应正开但实际低开，取消承接
- 程序当时认为的市场状态：volume_price_trial_probe aggregate OBSERVE; positive but below promotion threshold
- 收益/回撤/期望：总收益 0.01%；年化 0.01%；最大回撤 0.07%；每笔期望 未计算
- 是否达到年化 10.00%：否
- 下一步：等待策略 Worker 拆解 000001 负期望样本，并验证是否能提高多股聚合结果到年化 10% 附近。
- 备注：
  - 训练落盘 runtime/training/20260707T082606Z-summary.md
  - 当前不达成年化 10%，只能保持 OBSERVE，不晋级默认策略。

## 版本 v016 / 动作 016

- 记录时间：2026-07-07T09:10:38+00:00
- 策略候选：volume_price_intent_filtered_probe
- 训练命令：
```shell
python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000
```
- 股票池：000620, 000001, 300750, 600519, 002594, 300059
- 交易笔数：19
- 买入原因：
  - 保留 volume_price_trial_probe 的同类量价历史门槛和动态开盘确认
  - 仅当非突破类量价试错未被主力意图画像判定为弱势过滤时才允许买入
- 卖出原因：
  - volume-probe 定时退出规则继续生效
  - 持仓后若先出现资金流风险、疑似派发或止损，则由风险退出优先处理
- 跳过原因：
  - quiet_consolidation 且周线已经 down 时拦截试错买入
  - dry_up_base 距离 vwap60 过远时可由默认过滤规则拦截；训练候选暂只启用 quiet weekly-down 过滤
  - 原动态开盘模型仍会拦截追价高开、突破低于预期和热突破失败低开
- 程序当时认为的市场状态：intent-filtered volume probe OBSERVE; reduced 000001 bad trades but still below target
- 收益/回撤/期望：总收益 0.02%；年化 0.02%；最大回撤 0.06%；每笔期望 未计算
- 是否达到年化 10.00%：否
- 下一步：继续验证动态仓位和支撑风险预算；当前结果没有达到年化 10%，不能晋级默认策略。
- 备注：
  - 训练落盘 runtime/training/20260707T091038Z-summary.md
  - 000001 从 9 笔 -0.17% 改善到 6 笔 -0.11%，但仍为负期望。

## 版本 v017 / 动作 017

- 记录时间：2026-07-07T09:20:09+00:00
- 策略候选：volume_price_risk_sized_probe
- 训练命令：
```shell
python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000
```
- 股票池：000620, 000001, 300750, 600519, 002594, 300059
- 交易笔数：24
- 买入原因：
  - 先通过 volume_price_trial_probe 的同类量价历史门槛和动态开盘确认
  - 再通过主力意图过滤，避免部分非突破弱势整理节点
  - 最后用次日实际开盘价到信号日最低价的支撑距离计算风险预算仓位
- 卖出原因：
  - volume-probe 定时退出规则继续生效
  - 持仓后若先触发资金流风险、疑似派发或止损，则由风险退出优先处理
- 跳过原因：
  - 原动态开盘模型仍会拦截追价高开、突破低于预期和热突破失败低开
  - 意图过滤会拦截 quiet_consolidation 且周线 down 的弱势试错
  - 风险仓位模型会取消支撑无效、止损距离无效或风险预算无效的买入
- 程序当时认为的市场状态：volume_price_risk_sized_probe aggregate OBSERVE; best current volume-price candidate but still below target
- 收益/回撤/期望：聚合平均收益 0.10%；最大回撤 0.13%；聚合平均分 28.3；单一聚合期望未计算
- 是否达到年化 10.00%：否
- 下一步：优先拆解 000001 负期望样本，验证支撑距离质量过滤、弱势节点黑名单/白名单和低边际节点降权，不能直接把仓位继续放大。
- 备注：
  - 训练落盘 runtime/training/20260707T092009Z-summary.md
  - 002594 新增 5 笔闭合交易且收益 0.38%，但 000001 恶化到 -0.23%，说明仓位模型只能放大边际，不能修复坏买点。

## 版本 v018 / 动作 018

- 记录时间：2026-07-07T09:47:36+00:00
- 策略候选：volume_price_support_quality_probe
- 训练命令：
```shell
python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000
```
- 股票池：000620, 000001, 300750, 600519, 002594, 300059
- 交易笔数：11
- 买入原因：
  - 先通过同类量价历史门槛、动态开盘确认和主力意图过滤
  - dry_up_base 必须有可用且非负的 main_flow_5，并且同类历史平均收益不能低于支撑质量门槛
  - 通过支撑质量后，再按风险预算和开盘到信号日低点的距离计算仓位
- 卖出原因：
  - volume-probe 定时退出规则继续生效
  - 若持仓后先触发资金流风险、疑似派发或止损，则由风险退出优先处理
- 跳过原因：
  - 阻断缺少 main_flow_5 或 main_flow_5 为负的 dry_up_base
  - 阻断同类历史平均收益低于 0.35% 的 dry_up_base
  - 原动态开盘模型继续拦截追价高开、突破低于预期和热突破失败低开
- 程序当时认为的市场状态：volume_price_support_quality_probe aggregate OBSERVE; lower drawdown and fewer bad dry-up trades, but sample too small
- 收益/回撤/期望：聚合平均收益 0.14%；最大回撤 0.08%；聚合平均分 25.5；单一聚合期望未计算
- 是否达到年化 10.00%：否
- 下一步：在不重新放开低质量 dry-up 的前提下扩大高质量 breakout、shrink_pullback、quiet_consolidation 样本；尤其要验证 002594 和 300059 的 quiet/shrink 规则是否能跨股票稳定。
- 备注：
  - 训练落盘 runtime/training/20260707T094736Z-summary.md
  - 本版比 v017 平均收益更高、回撤更低，但交易数从 24 降到 11，不能作为达标策略。

## 版本 v019 / 动作 019

- 记录时间：2026-07-07T10:01:38+00:00
- 策略候选：volume_price_node_quality_expansion_probe
- 训练命令：
```shell
python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000
```
- 股票池：000620, 000001, 300750, 600519, 002594, 300059
- 交易笔数：2
- 买入原因：
  - 放宽基础 volume-probe 同节点历史样本门槛，尝试扩大非 dry-up 节点样本
  - 非 dry-up 节点必须通过更强的历史收益、历史胜率、main_flow_5、趋势、stage 和 distribution_score 质量门
  - 通过后仍使用动态开盘确认和风险预算仓位
- 卖出原因：
  - volume-probe 定时退出规则继续生效
  - 若持仓后先触发资金流风险、疑似派发或止损，则由风险退出优先处理
- 跳过原因：
  - 阻断低历史边际或低胜率的 quiet/shrink/breakout 节点
  - 阻断缺少 main_flow_5 或 main_flow_5 弱于阈值的非 dry-up 节点
  - 阻断日线/周线趋势不在允许范围、处于 markdown/distribution 阶段或 distribution_score 超限的非 dry-up 节点
- 程序当时认为的市场状态：volume_price_node_quality_expansion_probe aggregate OBSERVE; positive but over-filtered and failed expansion goal
- 收益/回撤/期望：聚合平均收益 0.07%；最大回撤 0.02%；聚合平均分 6.7；单一聚合期望未计算
- 是否达到年化 10.00%：否
- 下一步：不要晋级该候选；回到 v018，重点分析 002594/300059 的 quiet/shrink 正贡献条件，避免用过强趋势和 main_flow_5 门槛把有效样本全部过滤掉。
- 备注：
  - 训练落盘 runtime/training/20260707T100138Z-summary.md
  - 本版只在 000620 产生 2 笔 volume_breakout，闭合交易数低于 v018 的 11 笔，不能作为收益 10% 目标的推进版本。

## 版本 v020 / 动作 020

- 记录时间：2026-07-07T10:12:10+00:00
- 策略候选：volume_price_quiet_exception_probe
- 训练命令：
```shell
python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000
```
- 股票池：000620, 000001, 300750, 600519, 002594, 300059
- 交易笔数：14
- 买入原因：
  - 在 v018 支撑质量和风险预算候选的基础上，尝试给 quiet 相关节点保留例外空间，避免 v019 的强趋势和资金流门槛把有效 quiet/shrink 样本全部过滤。
  - 仍以量价同类节点、动态开盘确认和风险预算仓位作为执行基础，不把单票正收益直接视为可推广买点。
  - 候选目标是扩大有效交易数，同时观察 `000001` 负期望节点是否被继续放大。
- 卖出原因：
  - volume-probe 定时退出规则继续生效。
  - 若持仓后先触发资金流风险、疑似派发或止损，则由风险退出优先处理。
- 跳过原因：
  - `300750` 和 `600519` 在本轮无交易，说明候选仍未覆盖所有股票。
  - `002594` 虽有 5 笔闭合交易和 0.41% 收益，但样本标记为 `low_confidence`，不能直接当作晋级证据。
  - `000001` 仍产生 3 笔负期望交易，说明 quiet 例外没有修复该股票的坏买点。
- 程序当时认为的市场状态：volume_price_quiet_exception_probe aggregate OBSERVE; trade count and score improved, but return did not beat v018 and drawdown worsened
- 收益/回撤/期望：聚合平均收益 0.13%；最大回撤 0.11%；聚合平均分 30.3；002594 每笔期望 0.89%；000620 每笔期望 0.75%；300059 每笔期望 0.76%；000001 每笔期望 -0.62%
- 是否达到年化 10.00%：否
- 下一步：不晋级该候选；重点拆解 `000001` 的 3 笔负期望样本，并验证 quiet 例外是否只应在 `002594/300059` 这类有正贡献证据的节点上保留。
- 备注：
  - 训练落盘 runtime/training/20260707T101210Z-summary.md
  - 训练明细 runtime/training/20260707T101210Z-training.jsonl
  - v020 相比 v018 闭合交易从 11 增至 14、平均分从 25.5 增至 30.3，但平均收益从 0.14% 降至 0.13%，平均最大回撤从 0.08% 升至 0.11%；结论只能是 OBSERVE，不能作为 10% 目标的达标版本。

## 版本 v021 / 动作 021

- 记录时间：2026-07-07T10:30:54+00:00
- 策略候选：volume_price_quiet_exception_flow_guard_probe
- 训练命令：
```shell
python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000
```
- 股票池：000620, 000001, 300750, 600519, 002594, 300059
- 交易笔数：12
- 买入原因：
  - 沿用 v020 的量价同节点、动态开盘确认、支撑风险预算和 dry-up 支撑质量门。
  - 只对 quiet weekly-down 例外增加守门：同类已解析样本数至少 `10`，`distribution_score <= 40`，且 `main_flow_10 >= 0`。
  - 依据来自 v020 新增逐笔交易拆解：`000001` 新增亏损样本 `cases=5/6`、`dist=60`，`002594` 新增盈利样本 `cases=10`、`dist=20`。
- 卖出原因：
  - volume-probe 定时退出规则继续生效。
  - 若持仓后先触发资金流风险、疑似派发或止损，则由风险退出优先处理。
- 跳过原因：
  - quiet weekly-down 例外在 `cases < 10`、`distribution_score > 40` 或 `main_flow_10 < 0` 时被阻断。
  - 原有 opening gate 继续拦截追价高开、低于预期突破开盘和跌破信号日低点的执行。
  - dry-up 仍受支撑质量门约束，避免重新放开 v017 中被证明低质量的 dry-up 样本。
- 程序当时认为的市场状态：volume_price_quiet_exception_flow_guard_probe aggregate OBSERVE; improved v020 side effect but still far below target
- 收益/回撤/期望：聚合平均收益 0.15%；最大回撤 0.08%；聚合平均分 29.7；002594 每笔期望 0.89%；000620 每笔期望 0.75%；300059 每笔期望 0.76%；000001 每笔期望 -0.77%
- 是否达到年化 10.00%：否
- 下一步：保留 v021 为新的观察候选；下一轮应解决 `300750`、`600519` 无交易和整体收益太低的问题，优先分析哪些股票/阶段根本不适合量价试错，而不是继续只对 quiet 例外加规则。
- 备注：
  - 训练落盘 runtime/training/20260707T103054Z-summary.md
  - 训练明细 runtime/training/20260707T103054Z-training.jsonl
  - v021 相比 v020 闭合交易从 14 降至 12，平均收益从 0.13% 升至 0.15%，平均最大回撤从 0.11% 降至 0.08%；`000001` 从 3 笔 -0.21% 改善到 1 笔 -0.09%，说明新增守门有效挡掉了 v020 的主要坏样本，但仍未达到 10% 目标。

## 版本 v022 / 动作 022

- 记录时间：2026-07-07T10:44:24+00:00
- 策略候选：two_symbol_diagnostic_run
- 训练命令：
```shell
python run.py train-replay 000620 002031 --days 370 --initial-cash 100000
```
- 股票池：000620, 002031
- 交易笔数：最佳双票聚合候选 `volume_price_risk_sized_probe` 为 `27` 笔闭合交易；v021 观察候选 `volume_price_quiet_exception_flow_guard_probe` 为 `5` 笔闭合交易。
- 买入原因：
  - 本轮没有新增买入逻辑，只复用现有候选的量价同节点历史胜率、动态开盘确认、主力行为过滤、支撑风险预算和 quiet 例外守门。
  - `000620` 的有效样本主要来自 volume_breakout / shrink_pullback 后的试错买入，样本少但每笔期望相对正。
  - `002031` 的交易主要来自 dry_up_base / 整理类节点，交易次数多但每笔期望接近 0，说明资金流入不能直接等价为可买买点。
- 卖出原因：
  - volume-probe 定时退出规则继续生效。
  - 持仓后若先触发资金流风险、疑似派发、失败突破或止损，则由风险退出优先处理。
- 跳过原因：
  - `000620` 最新阶段为失败突破/派发风险，当前行为状态是 `WAIT_SELL_RISK`，不是追买状态。
  - `002031` 最新虽为资金持续流入和吸筹观察，但当前买入路径被阻断：缺少合格突破/吸筹触发形态，且入场风险高于现有风险上限。
  - 双票里出现的 `PROMOTE_CANDIDATE` 只是当前弱门槛下的候选排序结果，不能解释为策略达标。
- 程序当时认为的市场状态：
  - `000620`：`WAIT_SELL_RISK`，`distribution_or_failed_breakout`，`sustained_outflow`，买入 blocked，卖出状态 avoid_entry。
  - `002031`：`WATCH_ACCUMULATION`，`accumulation`，`sustained_inflow`，买入 blocked，卖出状态 clean。
- 收益/回撤/期望：
  - `volume_price_risk_sized_probe` 双票聚合：闭合交易 `27`，平均收益 `0.27%`，平均最大回撤 `0.64%`，平均分 `52.5`。
  - `000620` 在风险仓位/支撑质量/v021 类候选中约 `4` 笔闭合交易、收益 `0.38%`、每笔期望约 `0.75%`。
  - `002031` 在 volume trial/risk-sized 类候选中约 `23` 笔闭合交易，但收益只有 `0.04%` 到 `0.15%`，每笔期望约 `0.03%`。
- 是否达到年化 10.00%：否
- 下一步：不要因为双票弱门槛出现 `PROMOTE_CANDIDATE` 就晋级默认策略；优先拆解 `002031` 多交易低期望的 dry-up/整理节点，并单独检查 `000620` 突破后失败开盘和卖出风险节点。
- 备注：
  - 训练落盘 runtime/training/20260707T104424Z-summary.md
  - 训练明细 runtime/training/20260707T104424Z-training.jsonl
  - 本轮是诊断运行，不是代码版本变更；记录为 v022 是为了保持动作和交易行为回顾连续。

## 版本 v023 / 动作 023

- 记录时间：2026-07-07T11:14:05+00:00
- 策略候选：volume_price_dry_up_flow_support_guard_probe
- 训练命令：
```shell
python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000
```
- 股票池：000620, 000001, 300750, 600519, 002594, 300059
- 交易笔数：18
- 买入原因：
  - 先通过点时同节点量价历史门和动态开盘确认。
  - 继续使用支撑风险预算仓位。
  - 如果节点是 `dry_up_base`，额外要求不处于 `markdown_risk`，周线不是 `down`，派发分不高于 `40`，可用的 `main_flow_10` 不为负。
  - 次日开盘执行前，要求开盘到信号日低点的支撑距离在 `0.5%..2.0%`，且高开不超过 `1.0%`。
- 卖出原因：
  - volume-probe 定时退出规则继续生效。
  - 若持仓后先触发资金流风险、疑似派发、失败突破或止损，则风险退出优先。
- 跳过原因：
  - `dry_up_base` 在 markdown 阶段或周线下跌时被阻断。
  - `distribution_score > 40` 的 dry-up 被阻断。
  - 可用的 `main_flow_10 < 0` 时阻断。
  - 次日开盘支撑距离过近、过远或高开过高时取消执行。
- 程序当时认为的市场状态：v023 在 `002031` 上明显改善 dry-up 买点质量，但在 6 股池聚合上仍为 OBSERVE；不是默认策略。
- 收益/回撤/期望：
  - 双票 `000620/002031`：聚合闭合交易 `11`，平均收益 `1.19%`，平均最大回撤 `0.33%`，平均分 `52.5`。
  - `002031` 单票：`7` 笔闭合交易，收益 `2.00%`，最大回撤 `0.45%`，每笔期望 `2.50%`。
  - 6 股池：闭合交易 `18`，平均收益 `0.08%`，平均最大回撤 `0.14%`，平均分 `20.0`。
- 是否达到年化 10.00%：否
- 下一步：不要晋级该候选；下一轮应基于 6 股池寻找跨股票更稳的组合候选，优先研究 v021 与 markdown 守门的组合，或给 `000001` 的负期望 dry-up 单独增加非符号化、可泛化的过滤条件。
- 备注：
  - 双票训练落盘 runtime/training/20260707T111231Z-summary.md
  - 6 股池训练落盘 runtime/training/20260707T111405Z-summary.md
  - 全量测试 `python -m pytest` 为 `77 passed`。
  - 本轮已清理 `.pytest_cache` 和 `__pycache__`；训练证据和文档没有删除。

## 版本 v024 / 动作 024

- 记录时间：2026-07-07T11:37:53+00:00
- 策略候选：promotion_gate_and_loss_attribution_hardening
- 训练命令：
```shell
python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000
```
- 股票池：000620, 000001, 300750, 600519, 002594, 300059
- 交易笔数：本轮不新增交易逻辑；6 股池最佳核心候选 `volume_price_quiet_exception_flow_guard_probe` 为 `12` 笔闭合交易。
- 买入原因：
  - 本轮没有新增买点，只保留既有候选的点时量价历史门、动态开盘确认、支撑风险预算和 quiet exception flow guard。
  - 程序新增 `core/experimental` 候选分层：核心候选只保留基线、支撑质量、quiet exception flow guard；其余为实验分支。
- 卖出原因：
  - 本轮没有新增卖出逻辑，仍沿用 volume-probe 定时退出和风险退出优先。
- 跳过原因：
  - 晋级门槛改为硬约束：少于 `30` 笔闭合交易、少于 `2` 个有交易股票、平均期望不高于 `0.50%` 成本/滑点缓冲、聚合收益不为正，均不得晋级。
  - 双票中 `volume_price_risk_sized_probe` 虽有 `27` 笔、平均收益 `0.27%`，但闭合交易不足 `30`，只能 `OBSERVE`。
  - 6 股池中 `volume_price_quiet_exception_flow_guard_probe` 只有 `12` 笔，仍只能 `OBSERVE`。
  - `disguised_accumulation_probe` 有 `48` 笔但平均期望 `-1.03%`，不能因交易次数多而晋级。
- 程序当时认为的市场状态：当前程序是研究/回放/证据链系统，不是可实盘依赖的主力资金交易系统；当前价值是阻止冲动买入和暴露失败样本，而不是证明已经能抓主升浪。
- 收益/回撤/期望：
  - 双票 `000620/002031`：`volume_price_risk_sized_probe` 为 `27` 笔、平均收益 `0.27%`、平均期望 `0.13%`，新门槛结论 `OBSERVE`。
  - 双票 `volume_price_dry_up_flow_support_guard_probe` 为 `11` 笔、平均收益 `1.19%`、平均期望 `1.86%`，新门槛结论 `OBSERVE`。
  - 6 股池 `volume_price_quiet_exception_flow_guard_probe` 为 `12` 笔、平均收益 `0.15%`、平均最大回撤 `0.08%`、平均期望 `0.68%`，新门槛结论 `OBSERVE`。
  - 6 股池 `volume_price_dry_up_flow_support_guard_probe` 为 `18` 笔、平均收益 `0.08%`、平均最大回撤 `0.14%`、平均期望 `0.22%`，新门槛结论 `OBSERVE`。
- 是否达到年化 10.00%：否
- 下一步：不再增加买卖参数；先根据 `Loss Attribution Summary` 分析亏损集中簇，尤其 proof-probe、`002594/000001` 的吸筹亏损样本，以及 `002031` 残留 dry-up 亏损。
- 备注：
  - 双票训练落盘 runtime/training/20260707T113644Z-summary.md
  - 6 股池训练落盘 runtime/training/20260707T113753Z-summary.md
  - 全量测试 `python -m pytest` 为 `82 passed`。
  - 本轮已清理 `.pytest_cache` 和 `__pycache__`；训练证据和文档没有删除。

## 版本 v025 / 动作 025

- 记录时间：2026-07-08T09:18:35+08:00
- 策略候选：trade_thesis_story_layer
- 训练命令：
```shell
python run.py train-replay 000620 002031 --days 370 --initial-cash 100000
python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000
```
- 股票池：000620, 002031；以及 000620, 000001, 300750, 600519, 002594, 300059
- 交易笔数：本轮不新增交易执行逻辑；双票最佳交易数候选 `volume_price_risk_sized_probe` 为 `31` 笔闭合交易，6 股池最佳核心观察候选 `volume_price_quiet_exception_flow_guard_probe` 为 `11` 笔闭合交易。
- 买入原因：
  - 本轮不改变原买入触发器，而是在触发后为每笔交易补充 `TradeThesis`。
  - 每笔买入会被归类为 `breakout_start`、`dry_up_absorption_test`、`pullback_or_wash_support`、`accumulation_confirmation`、`disguised_accumulation_probe` 等 entry family。
  - 程序同时记录阶段、预期持有窗口、预期兑现信号、失效价、止盈逻辑、必须持有条件和必须退出条件。
- 卖出原因：
  - 本轮不改变原卖出触发器，仍由既有定时退出、风险退出、派发/失败突破/资金流风险等规则执行。
  - 新增的是卖出后的解释 verdict：`thesis_confirmed`、`thesis_failed`、`warnings_confirmed_exit`、`time_exit_needs_review`、`rule_exit_needs_review`。
- 跳过原因：
  - 该版本不是新策略候选，不直接产生新的买入或跳过决策。
  - 晋级门槛继续生效：闭合交易不足、平均收益低于成本缓冲、期望为负或样本不足的候选保持 `OBSERVE`。
  - 双票中 `volume_price_risk_sized_probe` 虽有 `31` 笔，但平均收益 `0.50%` 未明显高于成本/滑点缓冲；6 股池中核心候选只有 `11` 笔；`disguised_accumulation_probe` 有 `48` 笔但期望为负。
- 程序当时认为的市场状态：当前系统仍是研究/回放/证据链系统，但 v025 开始记录“买入后的剧本是否被市场验证”。这比只看资金流入或只看买卖信号更接近交易员复盘。
- 收益/回撤/期望：
  - 双票 `volume_price_risk_sized_probe`：`31` 笔、平均收益 `0.50%`、平均最大回撤 `0.64%`、平均期望 `0.24%`，结论 `OBSERVE`。
  - 双票 `volume_price_dry_up_flow_support_guard_probe`：`12` 笔、平均收益 `0.51%`、平均最大回撤 `0.37%`、平均期望 `0.71%`，结论 `OBSERVE`。
  - 6 股池 `volume_price_quiet_exception_flow_guard_probe`：`11` 笔、平均收益 `0.16%`、平均最大回撤 `0.07%`、平均期望 `0.81%`，结论 `OBSERVE`。
  - 6 股池 `volume_price_risk_sized_probe`：`25` 笔、平均收益 `0.10%`、平均最大回撤 `0.14%`、平均期望 `0.22%`，结论 `OBSERVE`。
  - 6 股池 `disguised_accumulation_probe`：`48` 笔、平均收益 `-0.51%`、平均最大回撤 `0.73%`、平均期望 `-1.03%`，不可晋级。
- 是否达到年化 10.00%：否
- 下一步：按 `Trade Thesis Stories` 对 `thesis_failed` 样本分组，优先检查失败最多的 `entry_family`、`stage`、`volume_node` 和退出 verdict；只有当某类剧本的失败原因稳定可解释时，才考虑修改持有、加仓或退出逻辑。
- 备注：
  - 双票训练落盘 runtime/training/20260708T011421Z-summary.md
  - 6 股池训练落盘 runtime/training/20260708T011505Z-summary.md
  - 全量测试 `python -m pytest` 为 `83 passed`。
  - 6 股池交易故事统计：`thesis_confirmed=25`、`thesis_failed=113`、`warnings_confirmed_exit=38`。

## 版本 v026 / 动作 026

- 记录时间：2026-07-08T09:42:05+08:00
- 策略候选：position_action_review_layer
- 训练命令：
```shell
python run.py train-replay 000620 002031 601929 000592 600879 002255 002279 000725 600478 002369 --days 370 --initial-cash 100000
```
- 股票池：000620, 002031, 601929, 000592, 600879, 002255, 002279, 000725, 600478, 002369
- 交易笔数：本轮不新增交易执行逻辑；核心候选 `volume_price_support_quality_probe` 和 `volume_price_quiet_exception_flow_guard_probe` 均为 `38` 笔闭合交易。
- 买入原因：
  - 本轮不改变原买入触发器，而是在每笔闭合交易上增加开盘情境和仓位动作回放标签。
  - 新增字段包括 `gap_pct`、`gap_bucket(-5..+5)`、`opening_classification`、`support_distance_pct`、`position_action`、`action_reason`。
  - `position_action` 的取值为 `observe`、`probe_20`、`probe_30`、`buy_50`、`full_100`、`reduce`、`exit`，均为研究标签，不是下单指令。
- 卖出原因：
  - 本轮不改变原卖出触发器，仍由原 stop、distribution、failed breakout、timed exit、inferred exit 等逻辑执行。
  - 新增的 `exit/reduce` 只是对已有闭合交易的回放解释，用来判断当时是否应观察、减仓或清仓。
- 跳过原因：
  - 本轮没有把 `buy_50/full_100` 接入执行层，因为这些标签尚未证明能在同池回放中提高收益。
  - 改善超过原来的 `5%` 被定义为：同池同天数同候选基线下，相对改善 `>=5%`，绝对收益提升 `>=0.10pp`，平均期望提升 `>=0.05pp`，并且交易数、交易股票数和回撤不退化。
  - 新增股票池训练后，核心候选仍未超过成本/滑点缓冲，不能晋级。
- 程序当时认为的市场状态：
  - 扩池后程序仍是研究/回放/证据链系统，不是可实盘依赖的主力资金交易系统。
  - 当前最重要的新证据是：`Position Action Replay` 可以把同一类买点拆成 `exit/buy_50/reduce/observe` 等后验分组，下一轮可验证哪些动作标签值得转成真实执行规则。
- 收益/回撤/期望：
  - `volume_price_support_quality_probe`：`10` 股、`9` 个有交易股票、`38` 笔、平均期望 `0.31%`、平均收益 `-0.07%`、平均最大回撤 `0.44%`，结论 `OBSERVE`。
  - `volume_price_quiet_exception_flow_guard_probe`：`10` 股、`9` 个有交易股票、`38` 笔、平均期望 `0.31%`、平均收益 `-0.07%`、平均最大回撤 `0.44%`，结论 `OBSERVE`。
  - `volume_price_risk_sized_probe`：`79` 笔、平均期望 `0.07%`、平均收益 `-0.15%`、平均最大回撤 `0.68%`，结论 `OBSERVE`。
  - `disguised_accumulation_probe`：`106` 笔、平均期望 `-0.97%`、平均收益 `-0.82%`、平均最大回撤 `1.22%`，不可晋级。
  - 核心候选动作分层：`exit` 组 `18` 笔、平均收益约 `-2.36%`；`buy_50` 组 `8` 笔、平均收益约 `3.58%`；`reduce` 组 `8` 笔、平均收益约 `1.10%`；`observe` 组 `4` 笔、平均收益约 `4.16%`。
- 是否达到年化 10.00%：否
- 下一步：继续让 A 分析 `Position Action Replay` 中的 `exit` 负收益簇和 `buy_50/observe` 正收益簇，判断哪些标签有资格被 B 转成真实交易方案；C 只有在同池回放证明超过 5% 改善口径时，才允许把诊断标签推进到执行逻辑。
- 备注：
  - A agent：019f3f51-ee83-7bc3-ac50-8f332e9f3ced
  - B agent：019f3f52-3fe0-7f91-bfd8-56dc3f4b9416
  - C agent：019f3f58-7d53-7700-b2c6-0e40dce185dc
  - 最终训练落盘 runtime/training/20260708T014023Z-summary.md
  - 全量测试 `python -m pytest` 为 `86 passed`。

## 版本 v027 / 动作 027

- 记录时间：2026-07-08T09:56:18+08:00
- 策略候选：knowledge_hypothesis_diagnostics_layer
- 训练命令：
```shell
python run.py train-replay 000620 002031 601929 000592 600879 002255 002279 000725 600478 002369 --days 370 --initial-cash 100000
```
- 股票池：000620, 002031, 601929, 000592, 600879, 002255, 002279, 000725, 600478, 002369
- 交易笔数：本轮不新增交易执行逻辑；核心候选 `volume_price_support_quality_probe` 和 `volume_price_quiet_exception_flow_guard_probe` 均仍为 `38` 笔闭合交易。
- 买入原因：
  - 本轮不改变买入触发器，只给每笔闭合交易新增 `vpa_archetype` 和 `KnowledgeHypothesisReview`。
  - 书单被映射为 `source_id/lens/hypothesis/bucket`，包括量价结果、形态结构、开盘注意力、支撑风险和失效纪律。
  - 这些字段来自既有 `TradeStory`、`TradeThesis` 和 `PositionActionReview`，不是新的买入规则。
- 卖出原因：
  - 本轮不改变卖出触发器，仍由原 stop、distribution、failed breakout、timed exit、inferred exit 等逻辑执行。
  - 新增的 `hold_only_while_thesis_is_valid` 只是把卖后 verdict、confirmations、warnings、invalidations 聚合成知识假设诊断。
- 跳过原因：
  - 所有 `REVIEW_CANDIDATE` 都是诊断状态，不是晋级状态。
  - 核心候选平均期望 `0.31%` 低于 `0.50%` 成本/滑点缓冲，因此继续 `OBSERVE`。
  - `disguised_accumulation_probe` 有 `106` 笔但平均期望 `-0.97%`，仍不可晋级。
- 程序当时认为的市场状态：
  - 程序仍是研究/回放/证据链系统，不是可实盘依赖的主力资金交易系统。
  - 新知识诊断显示：突破类 `effort_vs_result_breakout` 有观察价值，但缩量回踩和安静整理仍有大量失败，不能笼统按“缩量就是吸筹”交易。
- 收益/回撤/期望：
  - `volume_price_support_quality_probe`：`10` 股、`9` 个有交易股票、`38` 笔、平均期望 `0.31%`、平均收益 `-0.08%`、平均最大回撤 `0.46%`，结论 `OBSERVE`。
  - `volume_price_quiet_exception_flow_guard_probe`：`10` 股、`9` 个有交易股票、`38` 笔、平均期望 `0.31%`、平均收益 `-0.08%`、平均最大回撤 `0.46%`，结论 `OBSERVE`。
  - `disguised_accumulation_probe`：`106` 笔、平均期望 `-0.97%`、平均收益 `-0.84%`、平均最大回撤 `1.22%`，不可晋级。
  - 知识假设诊断：核心候选 `effort_vs_result_breakout` 为 `11` 笔、胜率 `54.55%`、平均收益 `2.35%`、`REVIEW_CANDIDATE`；`no_supply_pullback_or_wash` 为 `21` 笔、平均收益 `-0.52%`、`OBSERVE_ONLY`。
- 是否达到年化 10.00%：否
- 下一步：A 继续分析核心候选中 `effort_vs_result_breakout` 正收益分组和 `no_supply_pullback_or_wash` 负收益分组的差异；B 只允许提出诊断到执行的最小候选方案；C 必须用同池回放证明超过 5% 改善口径后才允许改执行层。
- 备注：
  - A agent：019f3f69-485b-78c2-b77b-017d7d0a401f
  - B agent：019f3f69-825c-70b3-861a-4bdf4696e801
  - 最终训练落盘 runtime/training/20260708T015641Z-summary.md
  - 全量测试 `python -m pytest` 为 `87 passed`。

## 版本 v028 / 动作 028

- 记录时间：2026-07-08T10:16:23+08:00
- 策略候选：volume_price_breakout_follow_through_probe
- 训练命令：
```shell
python run.py train-replay 000620 002031 601929 000592 600879 002255 002279 000725 600478 002369 --days 370 --initial-cash 100000
```
- 股票池：000620, 002031, 601929, 000592, 600879, 002255, 002279, 000725, 600478, 002369
- 交易笔数：新候选 `volume_price_breakout_follow_through_probe` 为 `9` 笔闭合交易，覆盖 `4` 个交易股票；core 对照仍为 `38` 笔闭合交易、`9` 个交易股票。
- 买入原因：
  - 只允许 `volume_breakout` 进入执行层，对应诊断中的 `effort_vs_result_breakout`。
  - 买入仍需通过点时同节点历史门槛、动态开盘确认、支撑风险预算仓位。
  - `shrink_pullback`、`quiet_consolidation` 和 `dry_up_base` 不再进入本候选买点；其中 shrink/quiet 是 v027 诊断中的失败簇。
- 卖出原因：
  - 如果持仓后收盘跌破支撑，则生成 `volume_price_follow_through_exit: invalidated`，下一交易日开盘卖出。
  - 如果 1-3 个持仓 bar 后 `confirmations <= warnings`，则生成 `volume_price_follow_through_exit: no_follow_through`。
  - 如果确认持续占优，则允许持有到 3-5 个 bar，并在最大持有窗口生成 `volume_price_follow_through_exit: max_hold`。
  - 原有资金流风险、疑似派发、突破失败等卖出仍可优先触发。
- 跳过原因：
  - `volume_price_probe_allowed_node_types=("volume_breakout",)` 直接阻断 `shrink_pullback`、`quiet_consolidation`、`dry_up_base`。
  - 新候选因为闭合交易只有 `9` 笔、低于 `30` 笔晋级门槛，继续 `OBSERVE`。
  - 交易股票从 core 的 `9` 个降到 `4` 个，覆盖退化，不能算通过无退化的 5% 改善口径。
- 程序当时认为的市场状态：
  - 这是一次诊断到执行的窄实验：程序只承认“突破簇相对有效”这一条学习结果，并把失败簇转成硬拦截。
  - 结果显示突破簇有更高期望，但不是跨股票池稳定交易系统；它更像一个高选择性观察候选。
- 收益/回撤/期望：
  - 新候选 `volume_price_breakout_follow_through_probe`：`10` 股、`4` 个交易股票、`9` 笔、平均期望 `5.57%`、平均收益 `0.21%`、平均最大回撤 `0.20%`，结论 `OBSERVE`。
  - 同池 core `volume_price_quiet_exception_flow_guard_probe`：`10` 股、`9` 个交易股票、`38` 笔、平均期望 `0.31%`、平均收益 `-0.05%`、平均最大回撤 `0.43%`，结论 `OBSERVE`。
  - v027 core 基线为 `38` 笔、`9` 个交易股票、平均期望 `0.31%`、平均收益 `-0.08%`、平均最大回撤 `0.46%`。
  - 新候选知识诊断：`effort_vs_result_breakout` 为 `9` 笔、胜率 `55.56%`、平均收益 `5.57%`、`REVIEW_CANDIDATE`。
- 是否达到年化 10.00%：否
- 下一步：
  - 不晋级该候选，不改默认策略。
  - 下一轮优先分析 `601929` 的三笔亏损突破交易：`support_too_wide_above_5pct`、`expected_open:gap_+0/+3`、`warnings_dominate/invalidated` 是否能形成更窄的守门规则。
  - 如果继续改执行层，只允许新增一个最小守门实验，并且必须同池回放证明交易数、交易股票数、收益、期望和回撤综合改善。
- 备注：
  - A agent：019f3f7d-79e8-75e2-bff6-2e3823dafcd8
  - B agent：019f3f7d-a84d-7a00-92cb-4d703a28a9d7
  - 主线程承担 C 实现与验证职责
  - 最终训练落盘 runtime/training/20260708T021623Z-summary.md
  - 全量测试 `python -m pytest` 为 `92 passed`。
## 版本 v029 / 动作 029

- 记录时间：2026-07-08T10:38:26+08:00
- 策略候选：volume_price_breakout_opening_guard_probe
- 训练命令：
```shell
python run.py train-replay 000620 002031 601929 000592 600879 002255 002279 000725 600478 002369 --days 370 --initial-cash 100000
```
- 股票池：000620, 002031, 601929, 000592, 600879, 002255, 002279, 000725, 600478, 002369
- 交易笔数：新候选 `volume_price_breakout_opening_guard_probe` 为 `6` 笔闭合交易，覆盖 `4` 个交易股票；v028 对照为 `9` 笔闭合交易、`4` 个交易股票。
- 买入原因：
  - 仍只允许 `volume_breakout`，对应 `effort_vs_result_breakout`。
  - 仍需通过点时同节点历史门槛、动态开盘确认、intent filter 和支撑风险预算仓位。
  - 新增开盘守门后，只有未触发“高开过热”或“极宽支撑但开盘需求不足”的突破，才允许下单。
- 卖出原因：
  - 保留 v028 的 follow-through exit：`invalidated`、`no_follow_through`、`max_hold`。
  - 原有疑似派发、资金价格背离、突破失败等风险卖出仍可优先触发。
- 跳过原因：
  - `shrink_pullback`、`quiet_consolidation`、`dry_up_base` 继续被 `allowed_node_types=("volume_breakout",)` 阻断。
  - `gap > 3.0%` 的突破开盘被视为过热，取消买入。
  - `support_distance > 8.0%` 且 `gap < 0.5%` 的突破开盘被视为缺少需求确认，取消买入。
  - 该守门拦截了 v028 中 `601929` 的三笔亏损突破样本：`2025-08-15`、`2025-11-05`、`2026-05-20`。
- 程序当时认为的市场状态：
  - v029 是突破候选的开盘执行守门实验，不是默认策略。
  - 它解决的是 `601929` 亏损簇中的“次日开盘是否值得试错”问题，不解决突破机会池太窄的问题。
- 收益/回撤/期望：
  - v028 对照 `volume_price_breakout_follow_through_probe`：`10` 股、`4` 个交易股票、`9` 笔、平均期望 `5.57%`、平均收益 `0.21%`、平均最大回撤 `0.20%`。
  - v029 `volume_price_breakout_opening_guard_probe`：`10` 股、`4` 个交易股票、`6` 笔、平均期望 `11.12%`、平均收益 `0.27%`、平均最大回撤 `0.06%`。
  - `601929` 单票从 v028 的 `4` 笔、收益 `-0.20%`、最大回撤 `1.44%`、每笔期望 `-2.39%`，改善为 v029 的 `1` 笔、收益 `0.45%`、最大回撤 `0.06%`、每笔期望 `7.06%`。
- 是否达到年化 10.00%：否。
- 是否晋级：否。交易数从 `9` 降到 `6`，仍低于 `30` 笔门槛；虽然收益和回撤改善，但覆盖继续变窄，不满足无退化改善纪律。
- 下一步：
  - 不继续单纯加防守守门。
  - 先分析 v029 保留的 6 笔成功/失败样本，寻找能扩大同类高质量突破机会池的条件。
- 备注：
  - A agent：019f3f90-f8df-7913-afc4-c86bebf301fc
  - B agent：019f3f91-24bf-7050-a114-1b5a0eda353f
  - 主线程承担 C 实现与验证职责
  - 最终训练落盘 runtime/training/20260708T023826Z-summary.md
  - 全量测试 `python -m pytest -q` 为 `94 passed`。
## 版本 v030 / 动作 030

- 记录时间：2026-07-08T11:04:27+08:00
- 策略候选：volume_price_breakout_confirmation_entry_probe
- 训练命令：
```shell
python run.py train-replay 000620 002031 601929 000592 600879 002255 002279 000725 600478 002369 --days 370 --initial-cash 100000
```
- 股票池：000620, 002031, 601929, 000592, 600879, 002255, 002279, 000725, 600478, 002369
- 交易笔数：新候选 `volume_price_breakout_confirmation_entry_probe` 只有 `1` 笔闭合交易，覆盖 `1` 个交易股票；v029 对照为 `6` 笔闭合交易、`4` 个交易股票；v028 对照为 `9` 笔闭合交易、`4` 个交易股票。
- 买入原因：
  - 信号日必须先通过 `volume_price_trial_entry`，且属于 `volume_breakout / effort_vs_result_breakout`。
  - v030 不在信号日后的下一开盘直接买，而是先生成 `volume_price_breakout_observe` 观察记录。
  - 下一根 K 线必须完成承接确认：低点不破信号日低点，收盘不低于信号日收盘，量价状态不是明显风险，主力流可用时不能转负。
  - 确认通过后，才允许再下一交易日开盘买入。
- 卖出原因：
  - 继续保留 v028/v029 的 follow-through exit：`invalidated`、`no_follow_through`、`max_hold`。
  - 原有疑似派发、资金价格背离、突破失败等风险卖出仍可优先触发。
  - 唯一闭合交易 `000620` 最终由突破失败卖出，故事中出现连续资金价格弱势警告。
- 跳过原因：
  - `shrink_pullback`、`quiet_consolidation`、`dry_up_base` 继续被阻断。
  - 信号后的确认日如果跌破信号低点、收盘低于信号收盘、量价转弱或主力流转负，则取消观察，不进入买入队列。
  - v030 的确认规则过硬，导致 `000592`、`600879` 这类 v029 大赢家没有进入新候选闭合交易。
- 程序当时认为的市场状态：
  - v030 是“信号后承接证明再入场”的执行实验，不是默认策略。
  - 它验证的是买点是否应该从信号日后移到承接确认日；结果显示该规则没有扩大机会池，反而明显错过强突破样本。
- 收益/回撤/期望：
  - v028 对照 `volume_price_breakout_follow_through_probe`：`10` 股、`4` 个交易股票、`9` 笔、平均期望 `5.57%`、平均收益 `0.21%`、平均最大回撤 `0.20%`。
  - v029 对照 `volume_price_breakout_opening_guard_probe`：`10` 股、`4` 个交易股票、`6` 笔、平均期望 `11.12%`、平均收益 `0.27%`、平均最大回撤 `0.06%`。
  - v030 `volume_price_breakout_confirmation_entry_probe`：`10` 股、`1` 个交易股票、`1` 笔、平均期望 `1.52%`、平均收益 `0.02%`、平均最大回撤 `0.00%`。
- 是否达到年化 10.00%：否。
- 是否晋级：否。闭合交易只有 `1` 笔，低于 `30` 笔晋级门槛；并且相对 v029 覆盖和收益都退化。
- 下一步：
  - 不继续收紧确认规则。
  - 需要重新区分“强 `volume_node:volume_breakout` 可直接小仓试探”和“弱 `accumulation_watch` 必须观察确认”。
  - 如果下一轮仍只有 `6-8` 笔以内，优先扩大股票池或时间区间，而不是继续在 10 股池里调参。
- 备注：
  - A agent：019f3fa2-f573-7a92-8d94-26dd7709f5a3
  - B agent：019f3fa3-2214-79d3-9aa9-2f67476f9cf3
  - C agent：019f3fa3-4691-7f33-83bc-905829016a00
  - 主线程完成生产代码整合、测试修正和训练回放
  - 最终训练落盘 runtime/training/20260708T030427Z-summary.md
  - 全量测试 `python -m pytest -q` 为 `96 passed`。

## 版本 v031 / 动作 031

- 记录时间：2026-07-08T12:20:17+08:00
- 策略候选：random_pool_utilization_gate
- 训练/回顾命令：
```shell
python run.py train-replay --random-pool-size 100 --random-seed 20260708 --days 370 --initial-cash 100000
python run.py train-replay <20260708T032635Z same-seed 100-symbol pool> --days 370 --initial-cash 100000
```
- 股票池：`pool_seed=20260708` 的 100 只随机非创业板 A 股；实际有效结果为 `96` 只，`4` 只数据错误。
- 交易笔数：
  - `volume_price_breakout_follow_through_probe`：`32` 笔闭合交易，`18` 个交易股票。
  - `volume_price_breakout_opening_guard_probe`：`28` 笔闭合交易，`17` 个交易股票。
  - `volume_price_quiet_exception_flow_guard_probe`：`443` 笔闭合交易，`74` 个交易股票。
- 买入原因：
  - 本轮不新增买点执行逻辑；只扩大随机股票池并补齐资金利用率、过滤归因和错过大涨诊断。
  - 突破候选仍然只允许 `volume_breakout / effort_vs_result_breakout` 进入执行层。
- 卖出原因：
  - 本轮不改变卖出触发器；既有 follow-through exit、突破失败、派发风险、资金价格背离等规则保持不变。
- 跳过原因：
  - 旧口径把 `node_not_allowed:normal` 计入过滤买点，导致过滤最多的条件被普通非信号日淹没。
  - v031 新口径把普通非信号日拆出；`volume_price_breakout_follow_through_probe` 的 `23617` 个旧过滤观察拆为合格过滤 `8478`、普通非信号 `15139`，最高合格过滤为 `node_not_allowed:dry_up_base`。
- 程序当时认为的市场状态：
  - 100 股池证明突破结构有单笔期望优势，但不是可配置资金的策略，因为资金几乎没有被部署。
  - `volume_price_breakout_follow_through_probe` 的持仓利用率只有 `0.39%`，平均仓位只有 `0.02%`，说明全年大部分时间空仓。
- 收益/回撤/期望：
  - `volume_price_breakout_follow_through_probe`：平均期望 `3.14%`、平均收益 `0.06%`、持仓利用率 `0.39%`、平均仓位 `0.02%`。
  - `volume_price_breakout_opening_guard_probe`：平均期望 `4.28%`、平均收益 `0.06%`、持仓利用率 `0.35%`、平均仓位 `0.02%`。
  - `volume_price_quiet_exception_flow_guard_probe`：平均期望 `0.18%`、平均收益 `0.06%`、持仓利用率 `1.89%`、平均仓位 `0.19%`。
- 是否达到年化 10.00%：否。
- 是否晋级：否。旧的 `PROMOTE_CANDIDATE` 被新晋级门槛修正为 `OBSERVE`；核心原因是低持仓利用率和低平均仓位无法证明年化收益能力。
- 下一步：
  - 不继续收紧突破过滤条件。
  - 先分析错过大涨为什么大量落在 `ordinary_non_signal`，即程序根本没有识别成合格买点。
  - 如果继续扩池，优先跑 300 股或延长时间窗口，但必须保留资金利用率门槛。
- 备注：
  - 100 股旧训练落盘 runtime/training/20260708T032635Z-summary.md
  - v031 回顾报告 runtime/training/20260708T032635Z-v031-utilization-review.md
  - efinance 随机池重跑失败日志 runtime/training/v031-random100-20260708T115506.err.log
  - 全量测试 `python -m pytest -q` 为 `100 passed`。
## 版本 v032 / 动作 032

- 记录时间：2026-07-08T14:07:28+08:00
- 策略候选：volume_price_breakout_opening_guard_probe_missed_opportunity_diagnostics
- 训练/回放命令：
  ```shell
  python run.py train-replay <20260708T032635Z same-seed 100-symbol pool> --days 370 --initial-cash 100000
  ```
- 股票池：复用 `20260708T032635Z` 的同 seed 100 股随机非创业板 A 股池；最终有效结果 `99` 个股票，`1` 个数据错误。
- 交易行为是否改变：否。
  - `volume_price_breakout_opening_guard_probe` 的买入、开盘 guard、仓位和卖出规则均未改变。
  - 本轮只新增错过机会诊断：以次日是否真实成交 `BUY` 判断是否错过，而不是只看信号日是否产生过 `BUY` 意图。
- 买入原因：
  - 仍只允许 `volume_breakout / effort_vs_result_breakout` 进入该候选执行层。
  - 仍保留 v029 的开盘守门：高开过热、宽支撑但开盘无需求会取消买入。
- 卖出原因：
  - 仍使用既有 follow-through exit、突破失败、资金价格背离、派发风险等防守规则。
- 跳过/错过原因：
  - 新增 `Missed Opportunity Attribution`：`ordinary_non_signal=1355`、`not_volume_breakout=498`、`history_gate_failed=114`、`opening_guard_cancel=16`、`other_filtered_signal=3`。
  - 结论是：当前错过的大涨主要不是开盘 guard 误杀，而是识别层没有把普通非信号日或非 `volume_breakout` 节点纳入可交易结构。
- 收益/回撤/期望：
  - `volume_price_breakout_opening_guard_probe`：`30` 笔闭合交易，`18` 个交易股票，`20` 盈、`10` 亏，胜率 `66.67%`。
  - 年内账户口径平均收益 `0.07%`，平均单笔期望 `5.39%`，平均盈利 `9.68%`，平均亏损 `-3.20%`。
  - 最好交易 `41.18%`，最差交易 `-7.98%`。
  - 持仓利用率 `0.36%`，平均仓位 `0.02%`，空仓 `24089` symbol-days。
- 是否达到年收益 10.00%：否。
- 是否晋级：否。虽然交易胜率和单笔期望比多数候选更好，但资金利用率过低，账户收益远低于目标。
- 最终训练落盘：
  - `runtime/training/20260708T055337Z-summary.md`
  - `runtime/training/20260708T055337Z-training.jsonl`
- 测试：
  - `python -m pytest -q` -> `101 passed`

## 版本 v033 / 动作 033

- 记录时间：2026-07-08T14:15:54+08:00
- 策略候选：volume_price_breakout_opening_guard_probe_only
- 交易行为是否改变：不改变该策略自身买卖规则；改变默认训练候选池。
- 默认策略池：
  - 删除默认训练入口中的其他策略。
  - 当前 `default_training_candidates()` 只返回 `volume_price_breakout_opening_guard_probe`。
  - 该策略被标记为当前唯一 `core` 策略基准。
- 买入原因：
  - 仍只允许 `volume_breakout / effort_vs_result_breakout`。
  - 仍保留 v029 开盘守门规则。
- 卖出原因：
  - 仍使用既有 follow-through exit、突破失败、资金价格背离、派发风险等规则。
- 跳过原因：
  - 其他历史策略不再进入默认训练报告，因此不会再产生默认同场对照。
- 收益/回撤/期望：
  - 本轮未重跑收益训练；这是默认策略池删减，不是收益优化。
- 验证：
  - `python -m pytest tests\test_training.py -q` -> `13 passed`
  - `python -m pytest -q` -> `101 passed`
  - 探针确认默认候选：`['volume_price_breakout_opening_guard_probe']`，tier 为 `['core']`。
