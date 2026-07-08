# 持久化训练动作日志

本日志记录每一次针对程序训练、调参、数据接入和策略纪律修改的动作。每条记录必须先说明问题、计划、意义和改动范围，再进入代码修改或运行验证。

## 动作 001 - 建立持久化训练闭环

- 遇到了什么问题？
  - 当前程序已经能对单只股票做历史回放、信号识别、模拟盘成交和报告输出，但训练证据主要停留在单股单次结果。
  - 单只股票内混合了散户、机构、游资、量化、消息和流动性噪声，不能把一次回放收益直接当成可泛化策略。
  - 现有文档已提示样本太小不能投射收益，但程序层面还缺少“多参数候选 -> 重复回放 -> 结果落盘 -> 下轮对比”的持久化训练动作。
- 打算怎么做？
  - 新增一个训练模块，围绕现有 `HistoricalReplayRunner` 和 `TradeDiscipline` 做参数候选评估。
  - 候选参数按前面讨论过的 skill 思路拆成几类：聪明钱追踪、追击试仓、机会成本/耐心持有、基线纪律。
  - 新增 CLI 命令，让训练可以对一组股票运行，并把每个候选参数的结果写入本地训练目录。
- 这么做有什么意义？
  - 把“我感觉某个策略更好”改成“每轮参数、样本、收益、回撤、闭合交易数、样本质量都有记录”。
  - 为后续接入 smart-money、交易日志、投资大师风格框架或更多 A 股数据源提供统一评估口径。
  - 避免程序继续困在单股单次结果里，也避免直接把外部 skill 输出当成买卖指令。
- 需要改什么？
  - 新增 `src/wealth_lab/training.py`，负责候选参数、训练评估、结果汇总和 JSONL/Markdown 落盘。
  - 扩展 `src/wealth_lab/cli.py`，增加 `train-replay` 命令。
  - 新增训练测试，确保候选参数能在合成回放数据上稳定输出结果。
  - 本日志保留为后续每次训练/调参的审计入口。

## 动作 002 - 落地 `train-replay` 训练入口

- 遇到了什么问题？
  - 只有 `analyze-stock` 时，每次只能看单只股票的一次回放报告，结果难以横向比较。
  - 参数调整没有统一记录，后续很容易忘记“为什么改、改了什么、上一轮结果如何”。
  - 前面找到的 skill 更适合作为分析视角，而不是直接替代程序里的交易纪律。
- 打算怎么做？
  - 在程序里增加默认参数候选：`baseline_discipline`、`smart_money_strict`、`pursuit_probe_only`、`opportunity_cost_patient`。
  - 让每个候选都跑同一批历史数据，并统一记录收益、回撤、闭合交易数、样本质量、期望收益和目标评估结论。
  - 增加 `python run.py train-replay ...` 命令，训练结果写入 `runtime/training/`。
- 这么做有什么意义？
  - 把 skill 的作用定位成“生成假设和参数候选”，把是否有效交给程序回放和持久化记录验证。
  - 从单股单次观察升级到多股、多参数、多轮对比，减少只对一只股票过拟合的风险。
  - JSONL 可以给后续程序继续读取，Markdown 可以人工复盘和继续编号记录。
- 需要改什么？
  - 已新增 `src/wealth_lab/training.py`。
  - 已扩展 `src/wealth_lab/cli.py` 的 `train-replay` 子命令。
  - 已新增 `tests/test_training.py`。
  - 已更新 `README.md` 的快速运行说明。
  - 已执行 `python -m pytest`，20 个测试全部通过。

## 动作 003 - 跑第一轮真实训练并修正评分偏差

- 遇到了什么问题？
  - 第一轮 `000620` 训练已能输出 4 个候选结果，但初版 `evidence_score` 把 `opportunity_cost_patient` 排到第一。
  - 该候选排名高的原因是“不交易所以无回撤”，但它没有闭合交易，不能证明策略有效。
  - 这属于训练评估口径的问题，如果不修，会鼓励程序选择“什么也不做”的参数。
- 打算怎么做？
  - 给 `evidence_score` 增加样本质量上限：`no_closed_trades` 最高 15 分，`too_small_do_not_project` 最高 40 分。
  - 增加测试，确保无闭合交易的训练结果不会因为零回撤被误排到前面。
  - 重新运行 `000620` 的训练，生成使用新评分口径的结果。
- 这么做有什么意义？
  - 训练目标从“表面收益/回撤最好”改成“有足够交易证据才有资格比较”。
  - 防止参数搜索退化成极端保守、不交易、无样本的伪优胜。
  - 让后续多股票训练更重视闭合交易数、样本质量和可复盘性。
- 需要改什么？
  - 已修改 `src/wealth_lab/training.py` 的 `_evidence_score`。
  - 已在 `tests/test_training.py` 增加评分上限测试。
  - 已执行 `python -m pytest`，21 个测试全部通过。
  - 已重新运行训练：`runtime/training/20260707T021314Z-summary.md` 和 `runtime/training/20260707T021314Z-training.jsonl`。
  - 最新结论：`pursuit_probe_only` 分数最高但仍为极小样本，`baseline_discipline` 接近，所有有交易候选期望收益为负，当前不能进入资金配置讨论。

## 动作 004 - 扩展到小样本股票池并加入候选聚合表

- 遇到了什么问题？
  - 单只 `000620` 仍然无法摆脱样本过小，3 笔左右闭合交易不能支撑调参结论。
  - 逐条候选排行榜容易让人只看某只股票的局部结果，忽略候选参数跨股票的整体表现。
  - 当前数据中每只股票大约 246 根 K 线、120 条资金流，缺失资金流日期仍然较多。
- 打算怎么做？
  - 用 `000620 000001 300750 600519 688981 002594 300059` 跑一轮 7 只股票的小样本池训练。
  - 在训练报告里新增 `Candidate Aggregate` 表，按候选参数聚合股票数、闭合交易数、低置信度样本数、无交易样本数、平均收益、平均回撤和平均分。
  - 保留单票明细，同时用聚合表判断候选是否值得进入下一轮。
- 这么做有什么意义？
  - 开始从“单只股票训练”转向“小股票池参数验证”，降低单票噪声影响。
  - 让前面讨论过的 smart-money、tradingagents、opportunity-cost 等视角落实为不同候选参数，而不是直接变成买卖指令。
  - 为后续扩大到 10-30 只观察标的提供稳定输出格式。
- 需要改什么？
  - 已修改 `src/wealth_lab/training.py`，在 Markdown 训练摘要中加入候选聚合表。
  - 已更新 `tests/test_training.py` 覆盖聚合表结构。
  - 已执行 `python -m pytest`，21 个测试全部通过。
  - 已运行小样本池训练：`runtime/training/20260707T021509Z-summary.md` 和 `runtime/training/20260707T021509Z-training.jsonl`。
  - 本轮聚合结论：`baseline_discipline` 闭合交易最多 22 笔但平均收益 -0.21%；`pursuit_probe_only` 闭合交易 17 笔、平均回撤较低但平均收益 -0.18%；`opportunity_cost_patient` 平均收益 0.03% 但 7 只里 5 只无交易，证据不足。
  - 下一步不应直接放宽入场条件；优先扩大观察标的、改善资金流覆盖，并增加按候选/股票池的训练门槛。

## 动作 005 - 建立资金行为和交易状态多节点模型

- 遇到了什么问题？
  - 现有报告能列出资金流信号、主力意图代理画像、买卖清单和训练结果，但这些信息分散在不同章节。
  - 买入/卖出训练需要一个统一状态层：先判断资金行为，再判断行为动作，再映射到交易模式。
  - 仅靠单个 `FundSignal` 或单个形态标签，容易忽略数据覆盖、资金持续性、派发风险、回放样本质量和当前持仓状态。
- 打算怎么做？
  - 新增资金数据模型：刻画数据覆盖、最新主力净流入、3/5/10 日资金方向、资金持续性和小单/大单分歧。
  - 新增行为动作模型：把吸筹、拉升、派发、回落、震荡观察映射成可解释动作状态。
  - 新增多节点交易状态模型：用数据质量、资金方向、行为阶段、买入路径、卖出风险、样本质量、持仓状态等节点综合给出 `BUY_READY`、`PROBE_READY`、`HOLD`、`SELL_READY`、`WAIT` 等状态。
- 这么做有什么意义？
  - 让程序不再只输出“买/卖/等”，而是说明这个状态由哪些资金行为节点共同形成。
  - 后续训练可以围绕节点失败原因调参，而不是盲目调单个阈值。
  - 这也是把 smart-money、交易日志和机会成本这些 skill 思路落实为程序内部结构化模型。
- 需要改什么？
  - 已新增 `src/wealth_lab/behavior_model.py`，供报告和训练复盘使用。
  - 已在 `analyze-stock` 报告中输出 `Multi-Node Trading State Model`。
  - 已将 `trading_mode`、`behavior_phase`、`fund_flow_bias`、`buy_state`、`sell_state` 写入训练候选结果。
  - 已新增 `tests/test_behavior_model.py`，并扩展 `tests/test_training.py`。
  - 已执行 `python -m pytest`，24 个测试全部通过。
  - 已重新运行小样本池训练：`runtime/training/20260707T022522Z-summary.md` 和 `runtime/training/20260707T022522Z-training.jsonl`。
  - 对 `000620` 的最新行为结论：所有候选均为 `WAIT_SELL_RISK`，`behavior_phase=distribution_or_failed_breakout`，`fund_flow_bias=sustained_outflow`，当前是卖出风险/禁止追买样本，不是买入样本。

## 动作 006 - 建立“暗中吸筹”假设验证器

- 遇到了什么问题？
  - 用户提出：即使表面是主力资金流出、小单流入，也可能是主力用拆单或伪装方式收集筹码。
  - 这个说法不能靠主观判断确认，也不能只凭当天一条资金流确认。
  - 需要把“暗中吸筹”变成可证伪命题，并用历史相似样本和后续结果验证。
- 打算怎么做？
  - 定义候选形态：主力/超大单/大单流出，小单流入，价格走弱或突破失败。
  - 定义确认条件：后续窗口内支撑守住、主力资金回流、价格修复。
  - 在历史回放中搜索相同候选形态，统计确认/失败/未定样本。
  - 对今日信号只给出“待验证清单”，不提前把它归为吸筹事实。
- 这么做有什么意义？
  - 把“主力是否在吸筹”的讨论从解释性猜测变成可复核证据链。
  - 允许保留用户的假设，但要求它接受后续数据检验。
  - 后续买入卖出训练可以把该验证结果作为一个节点，而不是直接用当天小单流入下结论。
- 需要改什么？
  - 已新增 `src/wealth_lab/accumulation_proof.py`，把“暗中吸筹”拆成候选形态、后续确认条件和历史相似样本统计。
  - 已扩展 `src/wealth_lab/cli.py`，增加 `prove-accumulation` 命令。
  - 已增加证明结果落盘能力，默认写入 `runtime/proofs/`，便于后续复盘同一天不同数据刷新后的证据差异。
  - 已新增 `tests/test_accumulation_proof.py`，覆盖确认、失败、非候选和 Markdown 持久化。
  - 已更新 `README.md`，说明 `prove-accumulation` 的使用方式和证明文件位置。
  - 本次真实验证命令：`python run.py prove-accumulation 000620 --days 370 --horizon 5 --min-cases 5`。
  - 已执行 `python -m pytest`，28 个测试全部通过。
  - 当前证明文件：`runtime/proofs/000620-2026-07-07-h5-20260707T032108Z.md`。
  - 当前信号日期：`2026-07-07`；收盘价约 `3.35`；主力净流入约 `-2961.66w`；主力占比约 `-4.56%`；超大单约 `-2114.58w`；大单约 `-847.08w`；小单约 `4509.74w`；涨跌幅约 `-3.18%`；标签为 `突破失败`。
  - 候选形态检查结果：`apparent_selling=True`、`small_order_absorption=True`、`weak_price=True`、`failed_breakout=True`、`is_candidate=True`。
  - 历史相似样本：`42` 个；确认 `21` 个；失败 `8` 个；未定 `13` 个；已决样本确认率 `72.41%`，失败率 `27.59%`。
  - 科学结论：历史统计支持“该形态存在暗中吸筹的可能性”，但今天仍是 `pending_future_confirmation`，不能提前确认主力正在吸筹；后续需要观察 5 个可用信号行中是否至少满足“支撑守住、价格修复、主力资金回流”中的 2 项。

## 动作 007 - 将“暗中吸筹证明”接入近一年模拟交易

- 遇到了什么问题？
  - `prove-accumulation` 已经能单独证明“表面主力流出 + 小单流入”是否属于暗中吸筹候选，但 `analyze-stock` 的近一年交易回放还没有把该证明作为交易门禁。
  - 如果证明只停留在单独命令里，程序仍可能在交易报告里只显示买卖纪律，而没有明确说明“候选吸筹为什么不能直接买”。
  - 用户要求再次跑近一年交易，并且必须把当前证明应用到程序。
- 打算怎么做？
  - 在交易纪律中加入 `wait_accumulation_proof` 门禁：表面主力/超大单/大单流出、小单流入、价格走弱或突破失败时，空仓不允许直接买入，只能等待后续确认。
  - 在 `analyze-stock` 报告中加入 `Disguised Accumulation Proof Gate`，显示当前信号、历史相似样本、确认率和交易门禁。
  - 在机会雷达中保留这些候选样本，标记 `proof_disguised_accumulation_confirmation`，方便后续复盘它们是否被确认。
- 这么做有什么意义？
  - 把“我的判断来自资金流”升级为“资金流候选 + 历史相似样本 + 后续确认规则 + 交易门禁”的可证伪流程。
  - 防止把历史 72.41% 的已决确认率误用成“今天已经证明吸筹”的买入结论。
  - 让买入/卖出训练能看到哪些日期被证明门禁拦住，从而后续可以统计“等待确认”是否比直接买入更稳。
- 需要改什么？
  - 已在 `src/wealth_lab/accumulation_proof.py` 暴露 `build_accumulation_seed` 和 `is_disguised_accumulation_candidate`。
  - 已修改 `src/wealth_lab/trade_discipline.py`，将候选吸筹接入交易纪律，未确认前输出 `wait_accumulation_proof`。
  - 已修改 `src/wealth_lab/decision_explainer.py`，在买入检查清单和机会雷达中显示证明门禁。
  - 已修改 `src/wealth_lab/report.py`，在 `analyze-stock` 报告中新增 `Disguised Accumulation Proof Gate`。
  - 已修改 `src/wealth_lab/analysis.py`，近一年回放报告会尽量抓取当前信号用于证明门禁；实时抓取失败时退回最新回放信号。
  - 已新增 `tests/test_trade_discipline.py`，并扩展 `tests/test_decision_explainer.py`。
  - 已执行 `python -m pytest`，30 个测试全部通过。
  - 已执行近一年交易回放：`python run.py analyze-stock 000620 --days 370 --initial-cash 100000 --no-persist`。
  - 本次近一年交易结果：区间 `2025-07-02` 至 `2026-07-06`，K 线 `245` 条，资金流 `120` 条，缺失资金流日期 `125` 个；模拟成交 `6` 笔，闭合交易 `3` 组；最终权益 `99366.00`，总收益 `-0.63%`，最大回撤 `1.03%`，样本质量 `too_small_do_not_project`。
  - 当前证明门禁结果：`current_status=pending_future_confirmation`，信号日期 `2026-07-07`，本次实时抓取主力净流入约 `-2632.38w`，小单净流入约 `4476.18w`；历史相似样本 `42` 个，确认/失败/未定为 `21/8/13`，已决确认率 `72.41%`；交易结论是等待确认，不追买。实时资金流会随数据源刷新，后续复盘以每次落盘或日志记录的运行结果为准。

## 动作 008 - 验证“等确认会不会买不到”和早期试探仓

- 遇到了什么问题？
  - 用户指出：如果等到真正确认才买，可能已经买不到好价格；同时当前近一年回放收益太低。
  - 动作 007 的证明门禁能避免把候选吸筹误当事实，但没有回答“能否更早参与”的问题。
  - 如果直接把所有候选都买入，可能会增加交易次数和亏损，需要用回放证明，而不能凭感觉调大仓位。
- 打算怎么做？
  - 新增点时证明上下文：每个历史信号日只能使用该日之前已经完成验证窗口的候选样本，避免前视偏差。
  - 增加可选 `--enable-proof-probe` 参数，允许对历史支持的候选吸筹做小仓位早期试探。
  - 把 `disguised_accumulation_probe` 加入训练候选，与基线、严格聪明钱、追击试仓、机会成本候选同场比较。
  - 修正训练评分：负收益、负期望或无交易的候选不能因为样本更多或无回撤而获得晋级分。
- 这么做有什么意义？
  - 正面回答“等确认是否会太晚”：可以更早买到，但必须用收益、回撤、期望和交易次数验证是否值得。
  - 防止把 `72.41%` 历史确认率误解为“买入一定赚钱”；确认率只说明形态可能存在，不等于交易期望为正。
  - 把“买得到”和“值得买”分开验证：买得到不代表策略应晋级。
- 需要改什么？
  - 已在 `src/wealth_lab/accumulation_proof.py` 增加 `AccumulationProofContext` 和 `build_point_in_time_proof_context`。
  - 已在 `src/wealth_lab/trade_discipline.py` 增加可选早期试探仓配置，默认关闭；开启后使用 `proof_probe_entry`。
  - 已在 `src/wealth_lab/cli.py` 增加 `--enable-proof-probe` 和 `--proof-probe-weight`。
  - 已在 `src/wealth_lab/report.py`、`src/wealth_lab/decision_explainer.py` 中同步展示 `TRADE_READY_PROOF_PROBE` 和 proof-probe 检查项。
  - 已在 `src/wealth_lab/training.py` 增加 `disguised_accumulation_probe` 候选，并修正负期望候选评分。
  - 已新增/扩展 `tests/test_accumulation_proof.py`、`tests/test_trade_discipline.py`、`tests/test_training.py`。
  - 已执行 `python -m pytest`，33 个测试全部通过。
  - 默认保守回放：`python run.py analyze-stock 000620 --days 370 --initial-cash 100000 --no-persist`，最终权益 `99366.00`，总收益 `-0.63%`，最大回撤 `1.03%`，成交 `6` 笔，闭合交易 `3` 组。
  - 开启 8% 早期试探：`python run.py analyze-stock 000620 --days 370 --initial-cash 100000 --no-persist --enable-proof-probe --proof-probe-weight 8`，最终权益 `97801.00`，总收益 `-2.20%`，最大回撤 `2.46%`，成交 `47` 笔，闭合交易 `23` 组。
  - 最新训练结果：`runtime/training/20260707T034712Z-summary.md`；5 个候选全部 `score=0.0`，没有任何候选达到晋级标准。
  - 结论：早期试探确实能更早买到，但当前规则会过度交易并扩大亏损；所以该规则保留为显式训练开关，不晋级为默认买入纪律。

## 动作 009 - 参考 GitHub 量化项目增加候选对比和晋级门禁

- 遇到了什么问题？
  - 近一年收益仍然偏低，单靠手动解释单只股票的资金流和形态，容易陷入过拟合。
  - 之前 `disguised_accumulation_probe` 提高了交易样本数，但收益和期望为负，说明“样本更多”不等于“策略更好”。
  - 训练摘要缺少明确的候选晋级门禁，容易误读小样本正收益或无交易低回撤。
- 打算怎么做？
  - 参考 GitHub 上 Qlib、RQAlpha、qstock、Backtesting.py 的做法，把优化重点放在完整研究链路、多候选回测、风险指标、样本质量和晋级规则上。
  - 新增 `breakout_only_no_pursuit` 候选：关闭追击试仓，只保留确认突破/吸筹路径，验证当前亏损是否主要来自追击试仓。
  - 给 `analyze-stock` 增加 `--disable-pursuit-probe`，方便直接对比默认纪律和关闭追击纪律。
  - 在训练摘要中加入 `Candidate Promotion Gate`，明确 `PROMOTE_CANDIDATE`、`OBSERVE`、`BLOCK`。
- 这么做有什么意义？
  - 把外部项目的启发落到当前程序可验证的结构：候选参数、真实回放、聚合统计、晋级门禁。
  - 避免因为单只股票 `000620` 的正收益就立刻改默认纪律。
  - 让后续每一轮优化都有“能不能晋级”的明确口径，而不是只看收益排序。
- 需要改什么？
  - 已在 `src/wealth_lab/training.py` 增加 `breakout_only_no_pursuit` 候选。
  - 已在 `src/wealth_lab/cli.py` 增加 `--disable-pursuit-probe`。
  - 已在 `src/wealth_lab/training.py` 增加 `_promotion_decision` 和训练摘要中的 `Candidate Promotion Gate`。
  - 已更新 `README.md`，加入关闭追击试仓的回放命令。
  - 已扩展 `tests/test_training.py` 覆盖晋级门禁输出。
  - 已执行 `python -m pytest`，33 个测试全部通过。
  - `000620` 对比结果：默认纪律 `final_value=99366.00`、收益 `-0.63%`、最大回撤 `1.03%`、成交 `6` 笔；关闭追击试仓 `final_value=100420.00`、收益 `0.42%`、最大回撤 `0.62%`、成交 `2` 笔。
  - 单股训练结果：`runtime/training/20260707T035840Z-summary.md`，`breakout_only_no_pursuit` 在 `000620` 上排名第一，但只有 1 组闭合交易，仍是 `too_small_do_not_project`。
  - 小股票池训练结果：`runtime/training/20260707T040217Z-summary.md`，6 只有结果、1 只 `688981` 数据源失败；聚合上 `breakout_only_no_pursuit` 平均收益 `-0.07%`，仍为 `BLOCK`；`opportunity_cost_patient` 平均收益 `0.03%` 但样本太少，只能 `OBSERVE`。
  - 当前结论：关闭追击试仓是有效的风险改进候选，但没有通过小股票池晋级门禁；保持为可选优化，不直接改默认纪律。下一轮应优先扩大股票池、修复 `688981` 数据源失败，并加入更严格的趋势/流动性过滤，而不是继续放大仓位。

## 动作 010 - 降低参数暴露并新增买入诊断

- 遇到了什么问题？
  - 用户指出当前程序没有达标，继续堆参数和开关会让程序难以理解，也容易变成单票调参。
  - 训练报告能告诉我们收益低，但还不能清楚回答“为什么在这个时候买入、买入是如何检测到的、哪类买点拖累收益”。
  - 当前确认模式虽然在 `000620` 上收益转正，但只有 1 组闭合交易，不能证明策略已经有效。
- 打算怎么做？
  - 把日常 CLI 参数压缩为 `--strategy-mode baseline|confirmed|proof-probe`，减少直接暴露的手动阈值。
  - 保留底层 `DisciplineConfig` 给训练候选使用，但普通回放优先使用策略模式。
  - 新增 `diagnostics` 模块，把每一笔闭合交易追溯到信号日，输出买入家庭、收益、持有天数、主力资金、形态、量比、阶段评分等检测证据。
  - 在 `analyze-stock` 报告中新增 `Strategy Diagnostics`，直接说明低收益原因和买入时机。
- 这么做有什么意义？
  - 让优化方向从“调更多参数”转为“少数策略模式 + 可解释买入证据 + 多样本训练验证”。
  - 让每次买入都能回答：什么时候发现、为什么买、主力资金是否确认、形态是否确认、买完结果如何。
  - 低收益原因可以定位到数据覆盖、交易样本不足、入口家庭亏损，而不是泛泛说策略不好。
- 需要改什么？
  - 已在 `src/wealth_lab/trade_discipline.py` 增加 `discipline_config_for_mode`。
  - 已在 `src/wealth_lab/cli.py` 增加 `--strategy-mode`，并保留旧开关兼容。
  - 已新增 `src/wealth_lab/diagnostics.py`。
  - 已在 `src/wealth_lab/report.py` 增加 `Strategy Diagnostics`。
  - 已新增 `tests/test_diagnostics.py`。
  - 已更新 `README.md`，推荐使用 `--strategy-mode confirmed` 和 `--strategy-mode proof-probe`。
  - 已执行 `python -m pytest`，34 个测试全部通过。
  - 已运行 `python run.py analyze-stock 000620 --days 370 --initial-cash 100000 --no-persist --strategy-mode confirmed`。
  - 诊断结论：确认模式最终权益 `100420.00`，收益 `0.42%`，最大回撤 `0.62%`，成交 `2` 笔，闭合交易 `1` 组；低收益主因是资金流覆盖仅约 `49.0%`、闭合交易只有 `1` 组，样本不能投射。
  - 确认模式唯一买入：信号日 `2026-05-15`，执行日 `2026-05-18`，退出日 `2026-05-20`；检测依据为 `fund_signal=买入`、`tags=放量突破,箱体突破`、主力净流入约 `122778179`、主力占比 `8.63%`、超大单约 `22738579`、涨幅约 `5.50%`、量比约 `2.06`、阶段 `accumulation_watch`、`markup=55.0`、`acc=93.0`、`dist=40.0`。
  - 当前结论：程序仍未达标；确认模式只是减少亏损和提高可解释性的候选，后续必须扩大股票池、提高资金流覆盖、再验证趋势/流动性过滤，不能因为单票 0.42% 就交付为高收益策略。

## 动作 011 - 风险收益门槛与 active-probe 早退训练

- 遇到了什么问题？
  - 用户要求减少无效买点，同时扩大可训练交易次数，并允许“可能买入”和“推断性卖出”，但这些判断不能停留在主观猜测。
  - 旧的 `proof-probe` 能显著增加交易次数，但在 `000620` 上把近一年结果扩大为亏损，说明“多交易”本身不是目标。
  - `confirmed` 模式能减少亏损并转正，但 `000620` 近一年只有 1 组闭合交易，样本仍然太小，不能证明策略有效。
- 打算怎么做？
  - 新增可复核的买点质量模型：用当前价、前 20 日高低点、VWAP 成本代理计算 `reward_risk`、`risk_pct`、`support`、`target`，用它过滤赔率差的买点。
  - 新增推断性卖出模型：当持仓后出现主力净流出、超大单转负、价格走弱、跌破成本、派发分上升等组合证据时，允许在明确卖出标签前先退出。
  - 新增 `active-probe` 策略模式和训练候选，用小仓位、风险收益过滤后的试探买入，加上推断性卖出；先训练验证，不直接晋级默认纪律。
- 这么做有什么意义？
  - 把“猜测性判断”变成可审计的证据分数，而不是凭感觉判断主力行为。
  - 把“扩大交易次数”限制在风险收益通过的样本上；如果放宽门槛带来亏损，程序必须记录并拒绝晋级。
  - 报告里的买入解释现在能同时回答资金流、形态、阶段评分和买点赔率，便于复盘无效买点到底被什么拖累。
- 需要改什么？
  - 新增 `src/wealth_lab/trade_quality.py`，提供 `estimate_entry_quality` 和 `estimate_inferred_exit_pressure`。
  - 修改 `src/wealth_lab/trade_discipline.py`，接入买点质量门槛、`active-probe` 模式、推断性卖出和风险收益过滤后的追击试仓。
  - 修改 `src/wealth_lab/decision_explainer.py`，在买入/卖出清单里输出 active-probe、entry_quality 和 inferred_exit 证据。
  - 修改 `src/wealth_lab/diagnostics.py`，在每笔闭合交易的检测证据中加入 `rr/risk/support/target/quality`。
  - 修改 `src/wealth_lab/training.py`，加入并调优 `active_probe_with_inferred_exit` 候选。
  - 修改 `src/wealth_lab/cli.py` 和 `README.md`，增加 `--strategy-mode active-probe` 的可复现入口。
  - 新增 `tests/test_trade_quality.py`，扩展 `tests/test_trade_discipline.py`、`tests/test_decision_explainer.py`、`tests/test_replay.py`。
- 本轮验证结果
  - `python -m pytest`：`41 passed`。
  - `000620` 最终版 active-probe：`final_value=100144.00`，`total_return=0.14%`，`max_drawdown=0.22%`，`fills=2`，`closed_round_trips=1`。
  - `000620` 临时放宽 `min_entry_reward_risk` 到 `1.05` 会新增 1 笔 `2026-06-29` active-probe 买入，但次日失败退出，最终约 `-0.11%`；因此不能为了交易次数降低该门槛。
  - 股票池训练文件：`runtime/training/20260707T045520Z-summary.md` 和 `runtime/training/20260707T045520Z-training.jsonl`。
  - 股票池聚合：`active_probe_with_inferred_exit` 闭合交易 `7` 组，平均收益约 `-0.01%`，平均最大回撤 `0.13%`；比 baseline 的 `-0.10% / 0.35%` 更稳，但仍为负收益。
  - 晋级结论：`active_probe_with_inferred_exit` 仍为 `BLOCK`，原因是聚合收益未转正；本轮不能交付为高收益策略，只能保留为下一轮候选。

## 动作 012 - 增加历史量价节点回放

- 遇到了什么问题？
  - 用户指出其他程序会回看历史数据，观察什么位置放量、什么位置缩量，再结合资金交易量判断策略。
  - 当前程序虽然已有 `volume_ratio`，但主要散落在信号判断和报告表格里，没有把历史上的放量突破、放量失败、缩量回踩、缩量整理系统化回放。
  - 资金流覆盖不足时，如果只看资金流信号，会漏掉完整 K 线里的量价结构。
- 打算怎么做？
  - 新增历史量价节点模型，基于完整 `Bar` 数据逐日回放。
  - 每个节点只使用该日之前的窗口均量、前高、前低，避免未来函数。
  - 标记 `volume_breakout`、`high_volume_failed_breakout`、`volume_selloff`、`breakdown_on_volume`、`shrink_pullback`、`dry_up_base`、`quiet_consolidation` 等观察节点。
  - 在报告中输出最近的重要量价节点，并在有资金流数据的日期附加主力净流入和主力占比。
- 这么做有什么意义？
  - 把“放量/缩量在哪里发生”变成可复盘表格，而不是人工翻图主观描述。
  - 后续可以统计：哪些放量突破容易失败，哪些缩量回踩更可能形成低风险买点。
  - 在资金流覆盖不完整时，仍能保留完整的历史量价结构，帮助判断买点质量和无效买点来源。
- 需要改什么？
  - 修改 `src/wealth_lab/replay.py`，在 `ReplayResult` 中保留完整 `bars`。
  - 新增 `src/wealth_lab/volume_replay.py`，构建历史量价节点回放。
  - 修改 `src/wealth_lab/report.py`，新增 `Historical Volume-Price Replay` 报告章节。
  - 新增 `tests/test_volume_replay.py`，验证放量、缩量节点分类，并验证只使用过去窗口计算量比。
- 本轮验证结果
  - `python -m pytest`：`43 passed`。
  - `python run.py analyze-stock 000620 --days 370 --initial-cash 100000 --no-persist --strategy-mode active-probe` 已输出量价回放章节。
  - `000620` 近一年量价统计：`expansion_nodes=41`，`shrink_nodes=98`，`constructive_nodes=75`，`risk_nodes=19`。
  - 报告中可见 `2026-05-15`、`2026-05-18`、`2026-06-26`、`2026-07-01` 为 `volume_breakout`；`2026-05-07`、`2026-06-25`、`2026-06-29` 为 `high_volume_failed_breakout`。
  - 最新节点为 `2026-07-07 shrink_pullback`，量比约 `0.48`，位置为 `middle`；这是观察节点，不是自动买入证明。

## 动作 013 - 建立量价试错买入的每日回放模型

- 遇到了什么问题？
  - 动作 012 已经能逐日回放放量、缩量、突破、失败突破等量价节点，但它仍然只是观察层，没有把“今天量价状态可能提示明天机会”变成可交易、可验证的程序规则。
  - 原 `HistoricalReplayRunner` 在缺少资金流数据的日期会直接跳过决策，这会导致完整日 K 里的量价信息没有进入每日交易观察。
  - 用户要求可以试错买入，但必须是科学验证，不是凭感觉猜主力行为。
- 打算怎么做？
  - 新增点时量价验证器：今日先分类量价节点，再只使用今日以前已经完成结果的同类历史节点，统计次日开盘买入、再下一交易日开盘退出的胜率和平均收益。
  - 新增 `volume-probe` 策略模式：关闭普通资金流买入，只允许通过量价同类样本门槛的小仓位试错买入；持仓后按下一可卖开盘退出，但如果止损或资金流风险先触发，则优先风险退出。
  - 让量价试错在每个日 K 上运行，即使当天没有资金流数据，也要产生每日观察记录。
- 这么做有什么意义？
  - 把“低价买、高价卖、今天量价感知明天机会”的想法变成可反复回放的假设检验。
  - 避免前视偏差：当前日期不能使用未来才知道的同类节点结果。
  - 可以清楚解释每次买入来自哪个量价节点、历史样本数、胜率、平均收益和门槛原因。
- 需要改什么？
  - 新增 `src/wealth_lab/volume_probe.py`，实现点时量价同类节点验证。
  - 修改 `src/wealth_lab/replay.py`，让量价试错成为每日观察分支，并写入 `ReplayDecision`。
  - 修改 `src/wealth_lab/trade_discipline.py`，新增 `volume-probe` 策略模式、试错买入和固定观察期退出。
  - 修改 `src/wealth_lab/report.py`，新增 `Volume-Price Trial Proof` 报告章节。
  - 修改 `src/wealth_lab/diagnostics.py`，让量价买点诊断显示 `volume_node/cases/win_rate/avg_return/gate`。
  - 修改 `src/wealth_lab/cli.py`、`src/wealth_lab/training.py`、`README.md`，接入 CLI 和训练候选。
  - 新增 `tests/test_volume_probe.py`，验证无前视统计和无资金流时的量价交易路径。
- 本轮验证结果
  - `python -m pytest`：46 个测试全部通过。
  - 单股近一年每日回放命令：`python run.py analyze-stock 000620 --days 370 --initial-cash 100000 --no-persist --strategy-mode volume-probe`。
  - `000620` 回放结果：`final_value=99431.00`，`total_return=-0.57%`，`max_drawdown=0.68%`，`fills=16`，`closed_round_trips=8`，`expectancy_per_trade=-1.25%`。
  - `000620` 量价每日观察：`daily_observations=246`，`passed_history_gate=10`，`trial_buy_decisions=8`。
  - `000620` 最新交易日状态：`2026-07-07 shrink_pullback`，同类已解析样本 `15`，胜率 `46.67%`，平均收益 `-0.26%`，低于 `55%` 胜率门槛，因此被拦截，不生成试错买入。
  - 多股票训练命令：`python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000`。
  - 训练落盘：`runtime/training/20260707T065631Z-summary.md` 和 `runtime/training/20260707T065631Z-training.jsonl`，共 `48` 个候选结果。
  - `volume_price_trial_probe` 聚合结果：6 只股票，闭合交易 `28`，`low_confidence=3`，`no_trades=3`，平均收益 `-0.07%`，平均最大回撤 `0.16%`，平均分 `10.8`，晋级门槛结论为 `BLOCK`，原因是聚合收益仍未转正。
  - 结论：量价试错模型已经跑通，并且能扩大交易样本，但当前规则没有达标；它只能作为训练候选保留，不能交付为高收益策略或默认买入纪律。

## 动作 014 - 稳固量价试错的次日开盘确认

- 遇到了什么问题？
  - 用户指出不能只理想化扩充更多模型，必须先把现有 `volume-probe` 的高开、低开、是否买入、是否加仓、是否卖出讲清楚。
  - 动作 013 的 `volume-probe` 已经能找到历史同类量价节点，但它在次日开盘直接执行买入，没有区分高开追价、低开失败、温和低吸和热突破低开的不同风险。
  - `000620` 上亏损样本显示，错误并不只来自节点胜率，而是来自次日开盘已经暴露的确认失败或追价风险。
- 打算怎么做？
  - 不新增分钟线系统，先用现有日 K 中已经可获得的次日开盘价，模拟开盘集合竞价后的执行确认。
  - 对 `volume_price_trial_entry` 增加执行前确认：
    - 高开超过 `3%`：取消买入，定义为追价和回补缺口风险。
    - 低开低于 `-3%`：取消买入，定义为信号失败风险。
    - 开盘跌破信号日最低价：取消买入，定义为结构破坏。
    - 放量突破且信号日涨幅大于等于 `7%` 后，次日低开：取消买入，定义为热突破承接失败。
    - 温和低开且未破坏结构：保留小仓试错，不能加仓。
- 这么做有什么意义？
  - 这是对现有买点链路的稳固，不是继续扩张版图。
  - 把“高开/低开到底意味着什么”落实成执行前可复核的规则。
  - 加仓权限暂不开放；当前模型仍是试错仓，只有先证明正期望，后续才讨论加仓。
- 需要改什么？
  - 修改 `src/wealth_lab/trade_discipline.py`，新增 `confirm_volume_probe_opening` 和开盘取消规则。
  - 修改 `src/wealth_lab/replay.py`，在次日开盘创建订单前执行开盘确认，取消的订单写入 `skipped_orders`。
  - 修改 `src/wealth_lab/report.py`，在 `Volume-Price Trial Proof` 中区分 `trial_buy_decisions`、`opening_cancelled` 和 `executed_trial_buys`。
  - 扩展 `tests/test_volume_probe.py`，覆盖高开取消、热突破低开取消和温和低开允许试错。
- 本轮验证结果
  - `python -m pytest`：`49 passed`。
  - `000620` 回放命令：`python run.py analyze-stock 000620 --days 370 --initial-cash 100000 --no-persist --strategy-mode volume-probe`。
  - `000620` 改进前：`final_value=99431.00`，`total_return=-0.57%`，`closed_round_trips=8`，`win_rate=25.00%`，`expectancy=-1.25%`。
  - `000620` 改进后：`final_value=100181.00`，`total_return=0.18%`，`max_drawdown=0.16%`，`closed_round_trips=4`，`win_rate=50.00%`，`expectancy=0.75%`。
  - `000620` 本轮开盘取消 `4` 笔：`2026-01-09 low_open_signal_failure`、`2026-02-03 high_open_chase_risk`、`2026-06-29 hot_breakout_low_open_failed_continuation`、`2026-07-02 hot_breakout_low_open_failed_continuation`。
  - 多股票训练命令：`python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000`。
  - 训练落盘：`runtime/training/20260707T074659Z-summary.md` 和 `runtime/training/20260707T074659Z-training.jsonl`。
  - `volume_price_trial_probe` 聚合结果：6 只股票，闭合交易 `22`，平均收益 `0.01%`，平均最大回撤 `0.07%`，平均分 `17.5`，晋级门槛从上一轮 `BLOCK` 改为 `OBSERVE`。
  - 结论：次日开盘确认是当前最有效的稳固动作，已经把量价试错从负收益拉到微正收益，但证据仍不足以晋级默认策略；下一轮应继续围绕这条开盘确认链路优化，而不是扩展新模型。

## 动作 015 - 用成交额和近几日量价状态推断动态开盘区间

- 遇到了什么问题？
  - 动作 014 的开盘确认虽然有效，但仍然带有固定 `+3%/-3%` 的硬阈值，不能回答用户提出的核心问题：主力资金状态、近几日成交量和成交额如果不同，合理开盘范围也应不同。
  - 直接把固定阈值改成宽松动态区间后，`000620` 会重新放行 `2026-02-03` 的缩量回调高开买入，单股回测从 `+0.18%` 退到 `-0.02%`，说明“动态”本身不等于更科学，区间过宽会把试错买点变成追价买点。
  - 当前数据仍然只有日线 OHLCV、成交额、成交量和部分资金流，不能伪装成已经拥有历史集合竞价分钟级委托明细；因此本轮只能先用日线成交额和近几日交易量做可验证代理。
- 打算怎么做？
  - 在 `volume-probe` 内建立点时开盘预期模型：只使用信号日以前已经知道的同类量价节点样本，统计这些样本的次日开盘缺口。
  - 相似度不再用固定高低开范围，而是按成交额相对近几日均值、近几日成交量比、节点量比、涨跌幅和区间位置排序，取最相似的同类样本形成预期开盘中枢和动态区间。
  - 对实际次日开盘做分层判断：高于动态区间取消；突破节点低于预期且低开取消；缩量/整理类买点如果虽在宽区间内但明显高于预期中枢，也取消，防止低风险试错变追价。
  - 删除不再使用的固定 `max_volume_price_high_open_gap_pct` 和 `max_volume_price_low_open_gap_pct` 参数，减少无效参数干扰。
- 这么做有什么意义？
  - 把“人性开盘预期”落成可回测命题：历史上相似成交额、成交量和量价节点下，市场通常给出什么样的次日开盘，而不是凭感觉判断主力。
  - 允许高开不是绝对风险：如果历史相似样本本来就预期高开，则高开可以继续试错；如果缩量回调高开只是偏离预期中枢，则视为追价风险。
  - 保持当前版图稳定，只强化 `volume-probe` 的买点执行确认，不新增分钟线、集合竞价或外部复杂系统，避免在当前收益未达标时继续扩散。
- 需要改什么？
  - 修改 `src/wealth_lab/volume_probe.py`，新增 `OpeningExpectationConfig`、`OpeningExpectationCase`、`OpeningExpectation` 和 `build_volume_probe_opening_expectation`。
  - 修改 `src/wealth_lab/trade_discipline.py`，让 `confirm_volume_probe_opening` 接收完整 bars 和索引，基于动态预期区间确认或取消开盘买入。
  - 修改 `src/wealth_lab/replay.py`，在执行 pending volume-probe 买单前传入完整 K 线和信号/执行索引。
  - 修改 `src/wealth_lab/report.py`，把 `Volume-Price Trial Proof` 的执行模型说明更新为“先推断预期开盘区间，再判断是否试错买入”。
  - 扩展 `tests/test_volume_probe.py`，覆盖动态高开取消、历史预期高开时允许、缩量回调高于预期中枢取消、突破低于预期取消，以及开盘预期不读取未来样本。
- 本轮验证结果
  - `python -m pytest`：`52 passed`。
  - `python run.py analyze-stock 000620 --days 370 --initial-cash 100000 --no-persist --strategy-mode volume-probe`：
    - 初版纯动态宽区间：`final_value=99977.00`，`total_return=-0.02%`，`closed_round_trips=5`，说明区间过宽会放行无效高开买点。
    - 加入缩量/整理高于预期中枢的追价取消后：`final_value=100181.00`，`total_return=0.18%`，`max_drawdown=0.16%`，`closed_round_trips=4`，`expectancy_per_trade=0.75%`。
    - 开盘取消 `4` 笔：`2026-01-09 opening_below_expected_range_after_breakout`，`2026-02-03 opening_above_expected_pullback_premium`，`2026-06-29 hot_breakout_failed_expected_positive_open`，`2026-07-02 hot_breakout_failed_expected_positive_open`。
  - 多股训练命令：`python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000`。
  - 训练落盘：`runtime/training/20260707T082606Z-summary.md` 和 `runtime/training/20260707T082606Z-training.jsonl`。
  - `volume_price_trial_probe` 聚合结果：6 只股票，闭合交易 `22`，`low_confidence=2`，`no_trades=3`，平均收益 `0.01%`，平均最大回撤 `0.07%`，平均分 `17.5`，晋级门槛仍为 `OBSERVE`，原因是有正向证据但分数低于晋级阈值。
  - 结论：动态开盘预期已经替代固定高低开范围，并恢复动作 014 的单股和多股表现；但收益仍远未达到可交付高收益策略，只能继续作为观察候选，下一轮应优先解释和改进 `000001` 的 9 笔负期望样本，而不是继续扩大新模型。

## 动作 016 - 多 Worker 并发监督：知识库、策略过滤候选和版本交易行为台账

- 遇到了什么问题？
  - 用户要求使用多个 worker subagents 并发推进三件事：学习投资理财知识生成程序知识库、根据知识反馈继续改进程序直到年化 10%、记录每一版本程序认为的交易行为。
  - 动作 015 的 `volume_price_trial_probe` 已经从固定开盘阈值升级为动态开盘预期，但 6 股票聚合收益仍只有 `0.01%`，没有接近年化 10%。
  - 当前最大拖累来自 `000001` 的量价试错负期望样本；`300750`、`600519`、`002594` 又几乎没有贡献成交，说明不能靠单票正收益宣称策略达标。
- 打算怎么做？
  - 启动并监督 3 个 worker：
    - Worker A：只写 `docs/investment-knowledge-base.md`，把投资知识拆成可程序化特征、风险、可验证假设和可接入模块。
    - Worker B：只改策略/训练代码和测试，先做一轮保守策略改进，不替换原候选。
    - Worker C：只建立版本交易行为记录机制，不改训练逻辑。
  - 主线程负责审查输出、跑全量测试和 6 股票训练，确认是否真正接近年化 10%。
  - 新增监督状态文件 `docs/agent-supervision-status.md`，记录每个 worker 的 agent id、写入范围和完成状态。
- 这么做有什么意义？
  - 把“学习知识”和“程序调参”分离，避免知识库直接变成未经验证的买卖规则。
  - 把策略改进限定成新增候选，保留原 `volume_price_trial_probe` 作为对照，防止一次小优化破坏基线。
  - 把每个版本程序当时认为的买入、卖出、跳过原因落盘，后续能复盘“程序为什么这么交易”，而不只看收益数字。
- 需要改什么？
  - 新增 `docs/investment-knowledge-base.md`，记录趋势、量价、开盘缺口、注意力交易、突破失败、缩量回踩、流动性、仓位、止损和样本外验证等知识条目。
  - 新增 `docs/agent-supervision-status.md`，记录 Worker A/B/C 的监督状态。
  - 新增 `docs/version-trade-behavior-log.md`、`src/wealth_lab/version_journal.py`、`tests/test_version_journal.py`，支持版本交易行为 Markdown 台账。
  - 修改 `src/wealth_lab/trade_discipline.py`，新增 `enable_volume_price_intent_filter` 及量价试错意图过滤逻辑。
  - 修改 `src/wealth_lab/replay.py`，仅在候选启用意图过滤时，为量价试错构建点时主力意图画像。
  - 修改 `src/wealth_lab/training.py`，新增候选 `volume_price_intent_filtered_probe`，保留原 `volume_price_trial_probe`。
  - 扩展 `tests/test_volume_probe.py` 和 `tests/test_training.py`，验证过滤规则和候选注册。
- 本轮验证结果
  - Worker A 完成：知识库只写文档，未改代码。
  - Worker C 完成：`python -m pytest tests\test_version_journal.py` 为 `4 passed`。
  - 主线程全量测试：`python -m pytest` 为 `59 passed`。
  - 主线程多股训练命令：`python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000`。
  - 训练落盘：`runtime/training/20260707T091038Z-summary.md` 和 `runtime/training/20260707T091038Z-training.jsonl`。
  - 原 `volume_price_trial_probe`：6 只股票，闭合交易 `22`，平均收益 `0.01%`，平均最大回撤 `0.07%`，平均分 `17.5`，结论 `OBSERVE`。
  - 新 `volume_price_intent_filtered_probe`：6 只股票，闭合交易 `19`，平均收益 `0.02%`，平均最大回撤 `0.06%`，平均分 `17.5`，结论 `OBSERVE`。
  - `000001` 从 `9` 笔、`-0.17%` 改善到 `6` 笔、`-0.11%`；`000620` 和 `300059` 正样本保持不变。
  - 结论：本轮减少了一部分无效买点，但远未达到年化 10%。不能晋级默认策略；下一轮应继续围绕“扩大有效交易次数”和“动态仓位/支撑风险预算”做候选验证，而不是宣称已达标。

## 动作 017 - 支撑风险预算仓位候选验证

- 遇到了什么问题？
  - 动作 016 的意图过滤减少了 `000001` 的部分无效买点，但聚合收益仍只有 `0.02%`，远低于年化 10% 目标。
  - 原 `volume_price_trial_probe` 使用固定 `6%` 试错仓位，无法区分“开盘价离支撑很近”和“离支撑很远”的风险差异。
  - 用户要求减少无效买点的同时扩大交易次数，因此不能只继续收紧过滤，也需要验证有效买点是否能在风险受控下提高仓位贡献。
- 打算怎么做？
  - 保留原始 `volume_price_trial_probe` 和 `volume_price_intent_filtered_probe`，新增独立候选 `volume_price_risk_sized_probe`。
  - 该候选沿用意图过滤和动态开盘确认，再按账户风险预算决定仓位：用次日实际开盘价到信号日最低价的距离作为支撑止损距离，仓位约等于 `account_risk_pct / stop_distance_pct`。
  - 如果实际开盘不属于预期内开盘，则降低仓位；如果支撑无效或风险预算无效，则取消买入。
- 这么做有什么意义？
  - 这是对现有买点链路的稳固：买点仍来自量价历史同类节点和动态开盘确认，仓位只根据可回测的支撑距离调整。
  - 它能验证一个科学命题：同样的试错买点，离支撑越近，单位亏损预算能承载的仓位越高；离支撑越远，仓位必须下降。
  - 同时它也能暴露策略瓶颈：如果坏买点仍存在，风险仓位会放大亏损，说明下一轮应该修正买点识别，而不是继续提高仓位。
- 需要改什么？
  - 修改 `src/wealth_lab/trade_discipline.py`，新增 `enable_volume_price_risk_sizing`、账户风险、最大仓位、最小止损距离和不确定开盘降权参数，并实现 `_apply_volume_price_risk_sizing`。
  - 修改 `src/wealth_lab/training.py`，新增候选 `volume_price_risk_sized_probe`，不替换旧候选。
  - 扩展 `tests/test_volume_probe.py`，验证近支撑时仓位被最大仓位上限约束，远支撑时仓位低于原固定试错仓位。
  - 扩展 `tests/test_training.py`，验证新候选存在且旧候选配置不被覆盖。
- 本轮验证结果
  - Worker B 第二轮完成：`volume_price_risk_sized_probe` 已实现为独立候选。
  - 主线程全量测试：`python -m pytest` 为 `61 passed`。
  - 多股训练命令：`python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000`。
  - 训练落盘：`runtime/training/20260707T092009Z-summary.md` 和 `runtime/training/20260707T092009Z-training.jsonl`。
  - 原 `volume_price_trial_probe`：6 只股票，闭合交易 `22`，平均收益 `0.01%`，平均最大回撤 `0.07%`，平均分 `17.5`，结论 `OBSERVE`。
  - `volume_price_intent_filtered_probe`：6 只股票，闭合交易 `19`，平均收益 `0.02%`，平均最大回撤 `0.06%`，平均分 `17.5`，结论 `OBSERVE`。
  - 新 `volume_price_risk_sized_probe`：6 只股票，闭合交易 `24`，平均收益 `0.10%`，平均最大回撤 `0.13%`，平均分 `28.3`，结论 `OBSERVE`。
  - 单票变化：`000620` 从 `0.18%` 提升到 `0.38%`；`002594` 新增 `5` 笔闭合交易且收益 `0.38%`；`300059` 为 `0.07%`；`000001` 从 `-0.11%` 恶化到 `-0.23%`。
  - 结论：这是当前最好的量价候选，但远未达到年化 10%，不能晋级默认策略。下一轮应优先定位 `000001` 这类低边际、负期望节点，增加“支撑距离质量”和“弱势节点黑名单/白名单”验证，而不是直接继续放大仓位。

## 动作 018 - 支撑质量过滤：阻断低边际 dry-up 放大仓位

- 遇到了什么问题？
  - 动作 017 的 `volume_price_risk_sized_probe` 把聚合收益从 `0.02%` 提高到 `0.10%`，但本质是放大同一批买点仓位，并没有提高买点质量。
  - `000001` 的 6 笔 risk-sized 交易仍是负期望，且亏损从 `-0.11%` 放大到 `-0.23%`；只靠仓位公式不能修复坏买点。
  - 只读 explorer `019f3be9-72d3-7221-a2d6-4a80a5911f48` 指出，失败样本集中在低边际 `dry_up_base`，并且很多交易日缺少 `main_flow_5` 资金流确认。
- 打算怎么做？
  - 新增独立候选 `volume_price_support_quality_probe`，继续保留前面所有候选作为对照。
  - 对 `dry_up_base` 增加支撑质量门：没有 `main_flow_5` 或 `main_flow_5 < 0` 时阻断；同类历史平均收益低于 `0.35%` 时阻断。
  - 对极窄支撑距离增加保护：当 `raw_stop` 小于配置的最小可加仓距离时，不把它当成可放大仓位机会，只保留基础试错仓。
- 这么做有什么意义？
  - 把“主力收集筹码”的猜测改成可验证门槛：至少需要资金流覆盖或足够历史边际，否则不能因为离日内低点近就放大仓位。
  - 这个候选验证的是买点质量，不是继续提高仓位；如果收益提高且回撤降低，说明减少低质量 dry-up 有价值。
  - 保留旧候选能防止过拟合：如果新候选只是减少交易而不是提升整体质量，训练报告会直接暴露。
- 需要改什么？
  - 修改 `src/wealth_lab/trade_discipline.py`，新增 `enable_volume_price_support_quality_filter`、`volume_price_block_dry_up_without_main_flow`、`volume_price_support_quality_min_dry_up_avg_return_pct` 和 `volume_price_min_raw_stop_upsize_pct`，并新增支撑质量阻断逻辑。
  - 修改 `src/wealth_lab/training.py`，新增候选 `volume_price_support_quality_probe`。
  - 扩展 `tests/test_volume_probe.py`，覆盖 dry-up 缺少资金流阻断、资金流存在时允许、低历史边际阻断、raw stop 太窄时保留基础仓位。
  - 扩展 `tests/test_training.py`，验证新候选存在且启用支撑质量过滤。
- 本轮验证结果
  - 针对性测试：`python -m pytest tests\test_volume_probe.py tests\test_training.py` 为 `22 passed`。
  - 全量测试：`python -m pytest` 为 `65 passed`。
  - 多股训练命令：`python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000`。
  - 训练落盘：`runtime/training/20260707T094736Z-summary.md` 和 `runtime/training/20260707T094736Z-training.jsonl`。
  - `volume_price_risk_sized_probe`：6 只股票，闭合交易 `24`，平均收益 `0.10%`，平均最大回撤 `0.13%`，平均分 `28.3`，结论 `OBSERVE`。
  - 新 `volume_price_support_quality_probe`：6 只股票，闭合交易 `11`，平均收益 `0.14%`，平均最大回撤 `0.08%`，平均分 `25.5`，结论 `OBSERVE`，原因是收益为正但样本仍太小。
  - 单票变化：`000001` 从 `6` 笔 `-0.23%` 改善到 `1` 笔 `-0.09%`；`300059` 从 `9` 笔 `0.07%` 改善到 `2` 笔 `0.18%`；`002594` 从 `5` 笔 `0.38%` 变为 `4` 笔 `0.36%`；`000620` 保持 `4` 笔 `0.38%`。
  - 结论：支撑质量过滤降低了坏买点和回撤，但交易次数减少，仍远未达到年化 10%。不能晋级默认策略；下一轮必须解决“有效交易样本不足”，优先研究如何在不放宽低质量 dry-up 的情况下扩大高质量 breakout / shrink / quiet 样本。

## 动作 019 - 非 dry-up 节点质量扩展候选验证

- 遇到了什么问题？
  - 动作 018 的 `volume_price_support_quality_probe` 提高了平均收益并降低回撤，但闭合交易从 `24` 降到 `11`，没有解决“有效交易次数不足”。
  - 如果重新放开低质量 `dry_up_base`，会回到动作 017 中 `000001` 亏损被仓位放大的问题。
  - 因此本轮需要验证一个新命题：能否降低基础历史样本数门槛来扩大 `volume_breakout`、`shrink_pullback`、`quiet_consolidation` 样本，同时用更强的非 dry-up 节点质量门控制风险。
- 打算怎么做？
  - 启动两个 worker：
    - 只读分析 worker `019f3c01-b01c-75d1-9794-5ffd4465c072`：分析 v018 逐笔交易和被拦截节点，寻找可扩大样本的证据。
    - 策略 worker `019f3c01-f6ea-7712-bd79-1b764e721ae8`：新增独立候选 `volume_price_node_quality_expansion_probe`，不覆盖旧候选。
  - 新候选把基础量价历史样本门从 `5` 降到 `3`，但对非 dry-up 节点增加更强质量门：历史平均收益、历史胜率、`main_flow_5`、日线/周线趋势、阶段和派发风险。
- 这么做有什么意义？
  - 这是对“扩大交易次数”的直接验证，而不是继续缩小交易范围。
  - 质量门全部使用信号日或以前的 `VolumeProbeContext` 和 `MainForceProfile`；次日开盘仍只在执行时由已有 opening gate 使用。
  - 如果新候选既增加交易又保持收益，就说明可以继续扩展；如果交易减少或收益下降，就说明质量门过严或方向不对。
- 需要改什么？
  - 修改 `src/wealth_lab/trade_discipline.py`，新增 `enable_volume_price_node_quality_filter` 及非 dry-up 节点质量门。
  - 修改 `src/wealth_lab/training.py`，新增候选 `volume_price_node_quality_expansion_probe`。
  - 扩展 `tests/test_volume_probe.py`，覆盖低边际 quiet 阻断、弱资金 shrink 阻断和有效 shrink 放行。
  - 扩展 `tests/test_training.py`，验证候选存在、旧候选不被覆盖、候选名称不重复。
- 本轮验证结果
  - 策略 worker 针对性测试：`python -m pytest tests\test_volume_probe.py tests\test_training.py` 为 `25 passed`。
  - 主线程全量测试：`python -m pytest` 为 `68 passed`。
  - 多股训练命令：`python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000`。
  - 训练落盘：`runtime/training/20260707T100138Z-summary.md` 和 `runtime/training/20260707T100138Z-training.jsonl`。
  - `volume_price_support_quality_probe`：6 只股票，闭合交易 `11`，平均收益 `0.14%`，平均最大回撤 `0.08%`，平均分 `25.5`，结论 `OBSERVE`。
  - 新 `volume_price_node_quality_expansion_probe`：6 只股票，闭合交易 `2`，平均收益 `0.07%`，平均最大回撤 `0.02%`，平均分 `6.7`，结论 `OBSERVE`，原因是收益为正但样本仍太小。
  - 单票行为：新候选只在 `000620` 产生 `2` 笔 `volume_breakout` 闭合交易，收益 `0.40%`，最大回撤 `0.11%`，每笔期望 `1.57%`；`000001`、`300750`、`600519`、`002594`、`300059` 均无闭合交易。
  - 结论：本轮没有达到扩大交易次数的目标，反而从 v018 的 `11` 笔降到 `2` 笔；收益也从 `0.14%` 降到 `0.07%`。不能晋级，且不应作为下一轮主方向。下一轮应优先分析 v018 中被保留的 `quiet_consolidation` 和 `shrink_pullback` 为什么在 `002594/300059` 有贡献，而不是继续用强趋势和 `main_flow_5` 硬过滤它们。

## 动作 020 - quiet 例外候选验证

- 遇到了什么问题？
  - 动作 018 的 `volume_price_support_quality_probe` 是当前更稳的对照：闭合交易 `11`、平均收益 `0.14%`、平均最大回撤 `0.08%`、平均分 `25.5`，但交易数不足。
  - 动作 019 的 `volume_price_node_quality_expansion_probe` 试图扩大非 dry-up 节点，结果闭合交易降到 `2`、平均收益 `0.07%`、平均分 `6.7`，说明强趋势和资金流硬门槛过度过滤。
  - 因此需要验证 `quiet_consolidation` 一类样本能否通过更有针对性的例外规则增加交易，同时不重新放开低质量 dry-up。
- 打算怎么做？
  - 使用独立候选 `volume_price_quiet_exception_probe`，保留 v018/v019 作为对照，不把新候选直接晋级。
  - 继续用 6 股票池做同一条训练命令，比较闭合交易数、平均收益、平均最大回撤、平均分、低置信样本和无交易样本。
  - 单票层面重点检查 `000001` 是否继续负贡献，以及 `002594/300059` 的 quiet/shrink 贡献是否能在更大交易数下保留。
- 这么做有什么意义？
  - 这是对“不要把有效 quiet 样本被过强过滤门槛误杀”的直接验证。
  - 如果交易数上升但收益或回撤恶化，说明例外规则扩大了样本，却还没有修复负期望节点。
  - 结论必须以 6 股票池聚合为准，不能因为 `002594` 或 `000620` 局部表现好就宣称达成年化 10%。
- 需要改什么？
  - 策略侧已产生 `volume_price_quiet_exception_probe` 的训练结果；本记录只补齐监督状态、动作日志和版本交易行为记录。
  - 本记录不修改训练逻辑，不回退其他 worker 的改动，只在允许的 docs 文件内补录 v020 证据。
- 本轮验证结果
  - 全量测试：`python -m pytest` 为 `70 passed`。
  - 多股训练命令：`python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000`。
  - 训练落盘：`runtime/training/20260707T101210Z-summary.md` 和 `runtime/training/20260707T101210Z-training.jsonl`。
  - v018 对照：闭合交易 `11`，平均收益 `0.14%`，平均最大回撤 `0.08%`，平均分 `25.5`。
  - v019 对照：闭合交易 `2`，平均收益 `0.07%`，平均最大回撤 `0.02%`，平均分 `6.7`。
  - v020 `volume_price_quiet_exception_probe`：6 只股票，闭合交易 `14`，低置信样本 `1`，无交易样本 `2`，平均收益 `0.13%`，平均最大回撤 `0.11%`，平均分 `30.3`。
  - 单票结果：`002594` 闭合交易 `5`、收益 `0.41%`、最大回撤 `0.17%`、每笔期望 `0.89%`、`low_confidence`、分数 `65.0`；`000620` 闭合交易 `4`、收益 `0.38%`、最大回撤 `0.20%`、每笔期望 `0.75%`；`300059` 闭合交易 `2`、收益 `0.18%`、最大回撤 `0.05%`、每笔期望 `0.76%`；`000001` 闭合交易 `3`、收益 `-0.21%`、最大回撤 `0.21%`、每笔期望 `-0.62%`；`300750` 和 `600519` 无交易。
  - 结论：v020 增加了交易数和平均分，但平均收益低于 v018，平均最大回撤高于 v018，并且 `000001` 仍然恶化。结论为 `OBSERVE`，不能晋级，不能计为年化 10%，也不能作为默认策略。

## 动作 021 - quiet 例外样本数、派发风险和 10 日资金流守门验证

- 遇到了什么问题？
  - 动作 020 的 `volume_price_quiet_exception_probe` 证明了 quiet 例外能增加交易数，但新增的 3 笔 quiet weekly-down 交易中，`000001` 两笔亏损，`002594` 一笔盈利，新增交易净效果为负。
  - 只读分析 worker `019f3c14-c1e8-7d90-ba4b-1811170bf92a` 复跑逐笔明细后发现：`main_flow_5` 不能区分好坏样本，因为 `000001` 坏样本的 `main_flow_5` 也为正；更有区分力的是同类已解析样本数 `cases` 和 `distribution_score`。
  - 本地复核补充发现：`000001` 两笔新增亏损的 `main_flow_10` 为负或接近负，`002594` 新增盈利样本的 `main_flow_10` 为正，可以作为辅助守门，但不能单独作为科学证明。
- 打算怎么做？
  - 新增独立候选 `volume_price_quiet_exception_flow_guard_probe`，保留 v018/v020/v019 作为对照，不覆盖旧候选。
  - 该候选只收紧 quiet weekly-down 例外：要求同节点已解析样本数 `cases >= 10`，`distribution_score <= 40`，且 `main_flow_10 >= 0`。
  - 阻断原因中补充输出 `main_flow_10`，方便后续复盘判断是样本不足、派发风险过高，还是 10 日资金流不支持。
- 这么做有什么意义？
  - 这一步不是凭资金流猜测主力意图，而是把 v020 的新增亏损拆成可验证字段：样本数、派发风险、10 日主力净流。
  - 它验证一个窄命题：quiet weekly-down 例外不能只看短期同节点胜率，必须同时有足够样本、低派发风险和中期资金流不拖后腿。
  - 如果 v021 能挡掉 `000001` 新增亏损并保留 `002594` 正样本，就说明 v020 的瓶颈不在“不能试错”，而在“试错例外的质量门不够”。
- 需要改什么？
  - 修改 `src/wealth_lab/trade_discipline.py`：新增默认关闭的 `enable_volume_price_quiet_weekly_down_exception_flow_guard` 和 `volume_price_quiet_weekly_down_exception_min_main_flow_10`，并在 quiet weekly-down 阻断说明中输出 `main_flow_10`。
  - 修改 `src/wealth_lab/training.py`：新增独立候选 `volume_price_quiet_exception_flow_guard_probe`，配置为 `cases>=10`、`distribution_score<=40`、`main_flow_10>=0`。
  - 扩展 `tests/test_volume_probe.py`：验证 v020 strong sample 仍可放行，v021 在 `main_flow_10 < 0` 时阻断，在 `main_flow_10 >= 0` 且分布风险达标时放行。
  - 扩展 `tests/test_training.py`：验证 v020 和 v021 同时存在，且 v020 未开启 flow guard，v021 开启并使用更严格阈值。
- 本轮验证结果
  - 策略 worker 针对性测试：`python -m pytest tests\test_volume_probe.py tests\test_training.py` 为 `29 passed`。
  - 主线程全量测试：`python -m pytest` 为 `72 passed`。
  - 多股训练命令：`python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000`。
  - 训练落盘：`runtime/training/20260707T103054Z-summary.md` 和 `runtime/training/20260707T103054Z-training.jsonl`。
  - v018 对照 `volume_price_support_quality_probe`：闭合交易 `11`，平均收益 `0.14%`，平均最大回撤 `0.08%`，平均分 `25.5`。
  - v020 对照 `volume_price_quiet_exception_probe`：闭合交易 `14`，平均收益 `0.13%`，平均最大回撤 `0.11%`，平均分 `30.3`。
  - 新 v021 `volume_price_quiet_exception_flow_guard_probe`：闭合交易 `12`，低置信样本 `1`，无交易样本 `2`，平均收益 `0.15%`，平均最大回撤 `0.08%`，平均分 `29.7`，结论 `OBSERVE`。
  - 单票变化：`000001` 从 v020 的 `3` 笔、`-0.21%`、最大回撤 `0.21%` 改善回 `1` 笔、`-0.09%`、最大回撤 `0.09%`；`002594` 保持 v020 的 `5` 笔、`0.41%`、`low_confidence`；`000620`、`300059` 与 v020 基本相同；`300750`、`600519` 仍无交易。
  - 结论：v021 修复了 v020 的主要副作用，并略高于 v018/v020 的聚合平均收益，但仍远低于年化 10% 目标，且平均分低于晋级门槛。只能作为新的最佳观察候选，不能晋级默认策略。

## 动作 022 - 盈新发展/巨轮智能双票数据跑通与状态诊断

- 遇到了什么问题？
  - 用户要求先暂停其他股票，只看盈新发展 `000620` 和巨轮智能 `002031`，以这两只票为例跑通当前程序。
  - v021 在 6 股池里仍远低于年化 10% 目标，需要先判断问题是普遍策略弱，还是不同股票的交易结构差异导致同一规则失效。
  - 两只票的表现明显不同：`000620` 交易次数少但每笔期望相对正；`002031` 交易次数多但边际接近 0，说明“扩大交易次数”本身没有解决收益问题。
- 打算怎么做？
  - 执行双票训练：`python run.py train-replay 000620 002031 --days 370 --initial-cash 100000`。
  - 分别用 `analyze-stock` 的 `volume-probe` 模式复核单票近一年回放、最新行为状态、买入阻断原因和卖出风险。
  - 本轮只记录诊断结果，不修改策略代码，避免用两只票的小样本直接覆盖已有候选。
- 这么做有什么意义？
  - 把问题从“收益低”拆成两个可验证子问题：`000620` 是有效样本太少，`002031` 是无效 dry-up/整理类交易太多。
  - 可以明确当前程序对“资金流入、放量、缩量、突破失败、开盘预期”的解释是否能落到买卖行为，而不是只看资金流方向。
  - 给下一轮策略改动提供靶点：不是继续叠参数，而是先定位 `002031` 这类多交易低期望样本为什么拖低收益。
- 需要改什么？
  - 本轮没有改代码。
  - 已生成训练落盘：`runtime/training/20260707T104424Z-summary.md` 和 `runtime/training/20260707T104424Z-training.jsonl`。
  - 双票聚合里 `volume_price_risk_sized_probe` 表现最好：闭合交易 `27`，平均收益 `0.27%`，平均最大回撤 `0.64%`，平均分 `52.5`。虽然当前弱晋级门显示 `PROMOTE_CANDIDATE`，但这只是双票正收益候选，不代表达到年化 10%。
  - `000620` 当前状态为 `WAIT_SELL_RISK`，行为阶段 `distribution_or_failed_breakout`，资金偏向 `sustained_outflow`；近一年 volume-probe 回放约 `4` 组闭合交易，收益约 `0.18%`，风险仓位/支撑质量类候选约 `0.38%`，当前不属于可买入状态。
  - `002031` 当前状态为 `WATCH_ACCUMULATION`，行为阶段 `accumulation`，资金偏向 `sustained_inflow`；但 volume-probe 约 `23` 组闭合交易仅 `0.04%`，risk-sized 约 `0.15%`，每笔期望约 `0.03%`，说明大量交易只是噪音交易。
  - 下一步如果继续优化，应先拆 `002031` 的 dry-up/quiet/shrink 逐笔样本，找出“资金流入但买点不赚钱”的共同条件，再决定是否新增一个独立候选。

## 动作 023 - dry-up 阶段/资金/支撑守门候选验证

- 遇到了什么问题？
  - `002031` 的 `volume_price_risk_sized_probe` 有 `23` 笔闭合交易，但总收益只有 `0.15%`，每笔期望约 `0.03%`，说明交易次数多但买点质量低。
  - 逐笔拆解后发现，这 `23` 笔全部来自 `dry_up_base`；其中 `markdown_risk + weekly_down` 的样本平均亏损，而 `neutral / 非 weekly_down` 样本平均收益更好。
  - 旧的 `support_quality` 一刀切要求 dry-up 必须有正 `main_flow_5`，在 `002031` 上只留下 1 笔亏损，说明 5 日资金流不是充分条件。
  - 文献启发也支持不能只看成交量：订单不平衡/资金方向、形态阶段、统计防过拟合都必须合并验证。
- 打算怎么做？
  - 清理无用缓存文件：删除 `.pytest_cache`、`src/**/__pycache__`、`tests/__pycache__`，保留训练产物、证明文件、数据库和文档证据链。
  - 先新增 `volume_price_markdown_guard_probe`：阻断非突破节点的 markdown 阶段试错。
  - 再新增更窄的 `volume_price_dry_up_flow_support_guard_probe`：仅针对 `dry_up_base` 加阶段、周线、派发分、10 日资金流、次日开盘支撑距离和高开幅度守门。
  - 保留所有旧候选，不覆盖 v021/v022 结果。
- 这么做有什么意义？
  - 把“缩量是不是机会”拆成可验证条件：不是缩量就买，而是必须处在非下跌阶段、非周线下跌、派发风险不高、资金中期不拖后腿、开盘支撑可用。
  - 回答“为什么收益低”：`002031` 的收益低不是缺交易，而是 `dry_up_base` 在下跌段被过度试错。
  - 回答“什么时候买”：只有当同节点历史通过、当前阶段没有 markdown/weekly-down 风险，并且次日开盘落在可承受支撑距离时才允许试错。
- 需要改什么？
  - 修改 `src/wealth_lab/training.py`：新增 `volume_price_markdown_guard_probe` 和 `volume_price_dry_up_flow_support_guard_probe`。
  - 修改 `src/wealth_lab/trade_discipline.py`：新增默认关闭的 dry-up 专用守门参数，并在 `decide_volume_probe` 和 `confirm_volume_probe_opening` 中接入。
  - 扩展 `tests/test_volume_probe.py`：覆盖 markdown 阶段阻断、周线 down 阻断、可用时 10 日资金流负值阻断、合格 profile 放行、开盘支撑距离过宽阻断。
  - 扩展 `tests/test_training.py`：验证两个新候选存在且旧候选不被覆盖。
- 本轮验证结果
  - 针对性测试：`python -m pytest tests\test_volume_probe.py tests\test_training.py` 为 `34 passed`。
  - 全量测试：`python -m pytest` 为 `77 passed`。
  - 双票训练命令：`python run.py train-replay 000620 002031 --days 370 --initial-cash 100000`。
  - 双票训练落盘：`runtime/training/20260707T111231Z-summary.md` 和 `runtime/training/20260707T111231Z-training.jsonl`。
  - 双票结果：`volume_price_dry_up_flow_support_guard_probe` 聚合闭合交易 `11`，平均收益 `1.19%`，平均最大回撤 `0.33%`，平均分 `52.5`；其中 `002031` 为 `7` 笔、`2.00%`、最大回撤 `0.45%`、每笔期望 `2.50%`，`000620` 保持 `4` 笔、`0.38%`。
  - 6 股池训练命令：`python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000`。
  - 6 股池训练落盘：`runtime/training/20260707T111405Z-summary.md` 和 `runtime/training/20260707T111405Z-training.jsonl`。
  - 6 股池结果：`volume_price_dry_up_flow_support_guard_probe` 为 `18` 笔、平均收益 `0.08%`、平均最大回撤 `0.14%`、平均分 `20.0`，低于 v021 `volume_price_quiet_exception_flow_guard_probe` 的平均收益 `0.15%`。
  - 结论：该候选有效解决了 `002031` 的 dry-up 噪音问题，但没有在 6 股池超越 v021，仍远低于年化 10% 目标。保留为观察候选，不晋级默认策略。

## 动作 024 - 证明纪律强化：监控分榜、严格晋级和亏损归因

- 遇到了什么问题？
  - 当前程序的问题不是不够复杂，而是还没有证明自己能稳定赚钱；继续堆策略参数会把研究框架推向调参游戏。
  - 监控层原来把 `SUSPECTED_DISTRIBUTION`、`FAILED_BREAKOUT`、`SUSPECTED_ACCUMULATION` 等高分信号混排，适合异动雷达，但不适合买入优先级。
  - 训练层原晋级门槛过弱，双票 `27` 笔或局部 `11` 笔正收益样本可能被显示为 `PROMOTE_CANDIDATE`，容易误导为策略达标。
  - 训练摘要只能看到收益、回撤、分数，不能直接看到亏损集中在哪个 entry reason、volume node 和股票。
- 打算怎么做？
  - 不新增买卖参数，不改变交易执行逻辑。
  - 监控输出顶部拆成 `风险异动榜` 和 `可交易候选榜`：风险榜收纳卖出、疑似派发、失败突破、资金流出、放量下跌；候选榜只允许 BUY 或建设性吸筹，并排除危险状态。
  - 给训练候选增加 `core/experimental` tier，把核心候选压缩为 `baseline_discipline`、`volume_price_support_quality_probe`、`volume_price_quiet_exception_flow_guard_probe`，其他保留为实验分支。
  - 收紧晋级门槛：至少 `30` 笔闭合交易、至少 `2` 个有交易股票、聚合收益为正、平均闭合交易期望高于 `0.50%` 成本/滑点缓冲后，才允许 `PROMOTE_CANDIDATE`。
  - 在训练摘要中新增 `Loss Attribution Summary`，聚合亏损交易的候选、股票、entry reason、volume node、亏损次数、平均亏损、总亏损和最差亏损。
- 这么做有什么意义？
  - 把“危险但重要”和“可以买观察”分开，避免高分风险信号被误当成买入排序。
  - 把 10% 目标从口头要求变成程序硬门槛：小样本、低期望、单票改善都不能晋级默认策略。
  - 后续优化必须先解释亏损来源，再决定是否改策略，减少无依据新增参数。
  - 当前程序继续作为研究/回放/证据链工具，而不是宣称可实盘依赖的主力资金交易系统。
- 需要改什么？
  - 修改 `src/wealth_lab/dashboard.py`：新增 `RISK_RANK`、`TRADE_CANDIDATES` 和风险/候选过滤函数。
  - 新增 `tests/test_dashboard.py`：验证失败突破/疑似派发不进入可交易候选，BUY/吸筹信号进入可交易候选。
  - 修改 `src/wealth_lab/training.py`：新增候选 tier、`LossAttribution`、亏损归因聚合、严格晋级门槛和摘要输出。
  - 扩展 `tests/test_training.py`：验证 `12/24` 笔小样本不晋级，`30+`、多股票、正期望、成本缓冲才可能晋级，并验证 summary 输出 tier 和亏损归因。
- 本轮验证结果
  - 针对性测试：`python -m pytest tests\test_dashboard.py tests\test_training.py -q` 为 `10 passed`。
  - 全量测试：`python -m pytest` 为 `82 passed`。
  - 双票训练命令：`python run.py train-replay 000620 002031 --days 370 --initial-cash 100000`。
  - 双票训练落盘：`runtime/training/20260707T113644Z-summary.md` 和 `runtime/training/20260707T113644Z-training.jsonl`。
  - 双票结果：`volume_price_risk_sized_probe` 为 `27` 笔、平均收益 `0.27%`、平均期望 `0.13%`，新门槛结论为 `OBSERVE`，原因是未达到 `30` 笔；`volume_price_dry_up_flow_support_guard_probe` 为 `11` 笔、平均收益 `1.19%`，仍为 `OBSERVE`。
  - 双票亏损归因显示：`disguised_accumulation_probe` 的 proof-probe 亏损最集中；`002031` 的 `volume_price_dry_up_flow_support_guard_probe` 仍有 `dry_up_base` 单笔亏损，说明局部改善不等于无风险。
  - 6 股池训练命令：`python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000`。
  - 6 股池训练落盘：`runtime/training/20260707T113753Z-summary.md` 和 `runtime/training/20260707T113753Z-training.jsonl`。
  - 6 股池结果：最佳核心候选 `volume_price_quiet_exception_flow_guard_probe` 为 `12` 笔、平均收益 `0.15%`、平均最大回撤 `0.08%`、平均期望 `0.68%`，仍因闭合交易不足保持 `OBSERVE`；`disguised_accumulation_probe` 虽有 `48` 笔，但平均期望 `-1.03%`、平均收益 `-0.51%`，保持 `OBSERVE`。
  - 本轮清理：删除 `.pytest_cache` 和 `__pycache__`，保留训练产物、证明文件、数据库和文档证据链。
  - 结论：本轮没有提高收益，但提高了证明标准和复盘透明度。当前仍未达到年化 10%，不能晋级默认策略。

## 动作 025 - 交易剧本层：买入假设、持仓验证和逐笔故事

- 遇到了什么问题？
  - 用户指出当前程序仍偏向“信号工程”：买入条件是触发器，卖出条件是防守器，中间缺少“观察-验证-加仓/持有-减仓/退出”的过程。
  - 程序能说明某一天像历史上的某类节点，但还不能在买入前写清楚后续应该发生什么，也不能在持仓过程中判断假设是在被验证、被警告，还是已经失败。
  - 训练摘要有收益、回撤和亏损归因，但还不够训练“观察力”：不知道每笔交易的买入剧本、预期持有窗口、期间确认/警告/失效证据和最终卖出理由是否一致。
- 打算怎么做？
  - 不新增策略候选，不新增买卖参数，不改变当前买入/卖出执行逻辑。
  - 给每笔闭合交易生成 `TradeThesis`：记录 `entry_family`、`stage`、`expected_holding_days`、`expected_follow_through`、`invalidation_price`、`take_profit_logic`、`must_hold_conditions`、`must_exit_conditions`。
  - 回放时对买入后的每日 K 线和资金状态生成 `ThesisCheck`，区分 `confirming`、`warning`、`invalidated`、`neutral`。
  - 给每笔交易生成 `TradeStory`：记录买入日期、卖出日期、实际持有天数、确认次数、警告次数、失效次数、卖出理由、收益和 verdict。
  - 在 `analyze-stock` 和 `train-replay` 报告里输出逐笔交易故事，而不是只输出聚合收益。
- 这么做有什么意义？
  - 把“为什么买”改成可验证的事前假设：不是因为出现信号就买，而是因为出现了一个可以被后续走势证明或证伪的剧本。
  - 把“为什么持有”改成过程判断：后续走势仍在证明原假设才持有；如果出现失效或风险证据，就能在报告中追踪。
  - 把“为什么卖”从固定 N 天或风险标签，扩展为假设兑现、假设失败、时间耗尽、规则退出待复核等可复盘结果。
  - 这一步不直接追求收益，而是为下一轮优化提供更硬的证据：先找出哪类 thesis 经常失败，再决定是否修改持有/退出行为。
- 需要改什么？
  - 修改 `src/wealth_lab/diagnostics.py`：新增 `TradeThesis`、`ThesisCheck`、`TradeStory`，并在 `diagnose_replay()` 中从闭合交易生成交易剧本和逐日验证证据。
  - 修改 `src/wealth_lab/report.py`：在 `Strategy Diagnostics` 中新增 `Trade thesis stories` 表，展示单股回放的逐笔持仓过程。
  - 修改 `src/wealth_lab/training.py`：训练候选保存 `trade_stories`，训练摘要新增 `Trade Thesis Stories` 表，按候选/股票输出逐笔交易故事。
  - 扩展 `tests/test_diagnostics.py`：验证突破启动交易能生成 thesis、确认信号和 verdict。
  - 扩展 `tests/test_training.py`：验证训练摘要输出 `Trade Thesis Stories`。
- 本轮验证结果
  - 针对性测试：`python -m pytest tests\test_diagnostics.py tests\test_training.py -q` 为 `10 passed`。
  - 全量测试：`python -m pytest` 为 `83 passed`。
  - 双票训练命令：`python run.py train-replay 000620 002031 --days 370 --initial-cash 100000`。
  - 双票训练落盘：`runtime/training/20260708T011421Z-summary.md` 和 `runtime/training/20260708T011421Z-training.jsonl`。
  - 双票结果：`volume_price_risk_sized_probe` 为 `31` 笔、平均收益 `0.50%`、平均期望 `0.24%`，因平均收益未超过 `0.50%` 成本/滑点缓冲而 `OBSERVE`；`volume_price_dry_up_flow_support_guard_probe` 为 `12` 笔、平均收益 `0.51%`、平均期望 `0.71%`，因闭合交易不足 `30` 笔而 `OBSERVE`。
  - 6 股池训练命令：`python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000`。
  - 6 股池训练落盘：`runtime/training/20260708T011505Z-summary.md` 和 `runtime/training/20260708T011505Z-training.jsonl`。
  - 6 股池结果：最佳核心观察候选 `volume_price_quiet_exception_flow_guard_probe` 为 `11` 笔、平均收益 `0.16%`、平均最大回撤 `0.07%`、平均期望 `0.81%`，因闭合交易不足保持 `OBSERVE`；`disguised_accumulation_probe` 为 `48` 笔但平均期望 `-1.03%`、平均收益 `-0.51%`，继续不可晋级。
  - 6 股池交易故事统计：`thesis_confirmed=25`、`thesis_failed=113`、`warnings_confirmed_exit=38`。这说明当前瓶颈不只是买点少，而是大量买入后的剧本没有被后续走势验证。
  - 结论：v025 没有证明年化 10%，也没有任何候选晋级默认策略；它把程序从“只看信号输赢”推进到“每笔交易都有事前假设和持仓证据链”。下一步应先按 thesis 类型和 verdict 分组，找出最常失败的买入剧本，再决定是否调整持有、加仓或退出逻辑。

## 动作 026 - 多 agent 开盘情境与仓位动作回放层

- 遇到了什么问题？
  - 用户要求继续多 subagent 模式：A 负责不断追问为什么买卖、为什么没达标；B 根据 A 的分析提出可行方案并记录；C 根据 B 的方案修改程序并验证。
  - v025 已有 `TradeThesis` 和 `TradeStory`，但还没有把“高开/低开 1%..5%、支撑距离、thesis 是否验证”翻译成观察、2 成试错、3 成试错、5 成买入、减仓、清仓等可回放动作。
  - 当前程序已有动态开盘预期和风险仓位，但训练报告还不能回答：同样是次日高开 2%，为什么这次应该观察、那次可以试错；同样是低开 2%，为什么是洗盘试错还是支撑失效。
  - 新增股票池后，样本扩大但收益没有达标，说明不能靠扩池或放大仓位直接解决问题。
- 打算怎么做？
  - A agent `019f3f51-ee83-7bc3-ac50-8f332e9f3ced` 只读分析 v025：按 thesis、stage、verdict、symbol 聚合失败簇，解释买卖发生时间。
  - B agent `019f3f52-3fe0-7f91-bfd8-56dc3f4b9416` 只读提出方案：新增只读 `PositionActionReview`，不改交易执行，先把开盘 gap 桶、开盘分类、支撑距离和 thesis verdict 映射成动作建议。
  - C agent `019f3f58-7d53-7700-b2c6-0e40dce185dc` 按 B 的方案实现诊断层：只改诊断、报告、训练摘要和测试，不改 `trade_discipline.py`、`replay.py`、`paper.py`。
  - 主线程监督：修正支撑距离定义，使诊断层与执行层一致，统一为 `(entry_open - support) / entry_open`；跑全量测试和新增股票池训练。
  - 新增股票池：`000620`、`002031`、`601929` 吉视传媒、`000592` 平潭发展、`600879` 航天电子、`002255` 海陆重工、`002279` 久其软件、`000725` 京东方A、`600478` 科力远、`002369` 卓翼科技。
- 这么做有什么意义？
  - 把“高开/低开意味着什么”从主观描述变成可统计字段：`gap_pct`、`gap_bucket`、`opening_classification`、`support_distance_pct`。
  - 把“2 成/3 成/5 成/满仓/减仓/清仓”先定义成回放建议，而不是直接变成交易执行，防止未验证规则导致仓位抖动和系统崩溃。
  - 让后续几百次、几千次、几万次调配有统一标签：可以统计某类 `position_action` 在某个 thesis/stage/opening 下到底是正期望还是噪音。
  - 固定“改善超过原来的 5%”的验收口径：同股票池、同天数、同候选基线下，至少相对改善 `>=5%`，且绝对收益提升 `>=0.10pp`、平均期望提升 `>=0.05pp`，交易数/交易股票数/回撤不能退化；否则就是无效改善。
- 需要改什么？
  - 修改 `src/wealth_lab/diagnostics.py`：新增 `PositionActionReview`，从 `TradeStory`、`ReplayDecision`、bars 中生成 `gap_pct`、`gap_bucket(-5..+5)`、`opening_classification`、`support_distance_pct`、`position_action`、`action_reason`。
  - 修改 `src/wealth_lab/report.py`：在 `Strategy Diagnostics` 中新增 `Position action replay` 表。
  - 修改 `src/wealth_lab/training.py`：`CandidateResult` 保存 `position_action_reviews`，训练摘要新增 `## Position Action Replay` 聚合表，按 candidate/tier/action 输出 trades、avg_return、avg_gap、avg_support_distance。
  - 扩展 `tests/test_diagnostics.py` 和 `tests/test_training.py`：覆盖开盘分类、支撑距离、position action 和训练摘要输出。
  - 本轮明确没有修改交易执行逻辑；`observe/probe_20/probe_30/buy_50/full_100/reduce/exit` 都是研究标签，不是实盘或 paper broker 下单指令。
- 本轮验证结果
  - C agent 针对性测试：`python -m pytest tests\test_diagnostics.py tests\test_training.py -q` 为 `13 passed`。
  - 主线程修正支撑距离后，针对性测试：`13 passed`；全量测试：`python -m pytest` 为 `86 passed`。
  - 新增股票池基线训练：`python run.py train-replay 000620 002031 601929 000592 600879 002255 002279 000725 600478 002369 --days 370 --initial-cash 100000`。
  - 最终训练落盘：`runtime/training/20260708T014023Z-summary.md` 和 `runtime/training/20260708T014023Z-training.jsonl`。
  - 新股票池结果：核心候选 `volume_price_support_quality_probe` 与 `volume_price_quiet_exception_flow_guard_probe` 均为 `10` 股、`9` 个有交易股票、`38` 笔闭合交易、平均期望 `0.31%`、平均收益 `-0.07%`、平均最大回撤 `0.44%`，晋级结论仍为 `OBSERVE`，原因是平均闭合交易收益 `0.31% < 0.50%` 成本/滑点缓冲。
  - `disguised_accumulation_probe` 扩池后有 `106` 笔，但平均期望 `-0.97%`、平均收益 `-0.82%`，再次证明“交易次数多”不是优势。
  - 交易故事统计：`thesis_confirmed=138`、`thesis_failed=294`、`warnings_confirmed_exit=92`、`time_exit_needs_review=69`、`rule_exit_needs_review=31`。失败故事仍明显多于确认故事。
  - `Position Action Replay` 给出新诊断证据：核心候选中 `exit` 组 `18` 笔、平均收益约 `-2.36%`；`buy_50` 组 `8` 笔、平均收益约 `3.58%`；`reduce` 组 `8` 笔、平均收益约 `1.10%`；`observe` 组 `4` 笔、平均收益约 `4.16%`。这只是回放分层，不代表按该动作交易后已经达标。
  - 结论：动作 026 没有证明年化 10%，也没有产生可晋级策略；它完成的是“开盘情境 -> 仓位动作建议”的可统计诊断层。下一步如果要真正改交易，应让 A 继续分析 `exit` 组为什么明显负、`buy_50/observe` 组为什么正，再由 B 提出“只把哪些诊断标签转成执行规则”的方案，C 必须用同池回放证明收益改善超过 5% 口径，否则视为无效改善。

## 动作 027 - 经典读盘书单到知识假设诊断层

- 遇到了什么问题？
  - 用户给出 VPA、Wyckoff、K 线、图形形态、O'Neil、Minervini、Shannon、Livermore 等书单，并强调不能把书里的指标全加进去，而要转换成“买入前、买入后、持有中、卖出时”的可验证交易剧本。
  - v025/v026 已经有 `TradeThesis`、`TradeStory` 和 `PositionActionReview`，但还缺少“这条交易故事对应哪类经典知识假设”的统计入口。
  - 如果直接把书单变成执行规则，会回到继续堆参数和过拟合的问题；当前策略仍未证明能稳定赚钱，不能新增默认买卖候选。
- 打算怎么做？
  - 继续多 agent 监督：A 只读归纳交易剧本四问；B 只读提出最小落地方案；主线程按 C 的职责做受控实现和验证。
  - 不新增 `TrainingCandidate`，不修改 `trade_discipline.py`、`replay.py`、`paper.py`，不改变买入/卖出/仓位执行。
  - 在诊断层新增 `KnowledgeHypothesisReview`，把每笔闭合交易映射到 `source_id`、`lens`、`hypothesis_id`、`bucket`、`return_pct`、`verdict`、`diagnostic_status`。
  - 在训练摘要新增 `Knowledge Hypothesis Diagnostics`，按 `candidate/tier/lens/hypothesis/bucket` 聚合交易数、胜率、平均收益、确认数、失败数和状态。
- 这么做有什么意义？
  - 把经典书单从“主观经验”转换成可回放、可分组、可失败的知识假设，而不是直接变成买卖信号。
  - 让后续 A 可以严格追问：哪一类量价剧本失败最多？哪一类突破真正有后续？哪类开盘 gap 是噪音？哪种支撑距离值得试错？
  - 让 B 只能从稳定正期望分组提出候选方案；C 仍必须用同池、同天数、同基线证明超过 5% 改善口径，才允许进一步讨论执行层。
- 需要改什么？
  - 修改 `src/wealth_lab/diagnostics.py`：新增 `KnowledgeHypothesisReview`，并为每笔 `TradeStory` + `PositionActionReview` 生成五类假设诊断：量价结果、形态结构、开盘注意力、支撑风险、失效纪律。
  - 修改 `src/wealth_lab/training.py`：`CandidateResult` 保存 `knowledge_hypothesis_reviews`，训练摘要新增 `## Knowledge Hypothesis Diagnostics` 聚合表。
  - 修改 `src/wealth_lab/report.py`：单股回放报告新增知识假设诊断明细。
  - 扩展 `tests/test_diagnostics.py` 和 `tests/test_training.py`：覆盖 `vpa_archetype`、知识假设生成和训练摘要聚合。
  - 修改 `docs/investment-knowledge-base.md`：新增“经典读盘书单必须先转成可验证交易剧本”章节。
- 本轮验证结果
  - A agent `019f3f69-485b-78c2-b77b-017d7d0a401f` 完成只读归纳：书单应落成买入前、买入后 1-3 天、持有中、卖出时四问；`PositionActionReview` 和 `TradeStory.verdict` 只能观察，不能直接驱动执行。
  - B agent `019f3f69-825c-70b3-861a-4bdf4696e801` 完成只读方案：建议只改诊断层和训练摘要层，不新增候选、不改执行层。
  - 针对性测试：`python -m pytest tests\test_diagnostics.py tests\test_training.py -q` 为 `14 passed`。
  - 全量测试：`python -m pytest` 为 `87 passed`。
  - 10 股池训练命令：`python run.py train-replay 000620 002031 601929 000592 600879 002255 002279 000725 600478 002369 --days 370 --initial-cash 100000`。
  - 训练落盘：`runtime/training/20260708T015641Z-summary.md` 和 `runtime/training/20260708T015641Z-training.jsonl`。
  - 核心候选 `volume_price_support_quality_probe` 与 `volume_price_quiet_exception_flow_guard_probe` 均为 `10` 股、`9` 个有交易股票、`38` 笔闭合交易、平均期望 `0.31%`、平均收益 `-0.08%`、平均最大回撤 `0.46%`，继续 `OBSERVE`，原因是 `0.31% < 0.50%` 成本/滑点缓冲。
  - `disguised_accumulation_probe` 为 `106` 笔、平均期望 `-0.97%`、平均收益 `-0.84%`，继续证明该假设不能直接交易。
  - 知识假设诊断中，核心候选 `volume_price_quiet_exception_flow_guard_probe` 的 `effort_vs_result_breakout` 为 `11` 笔、胜率 `54.55%`、平均收益 `2.35%`、`REVIEW_CANDIDATE`；但 `no_supply_pullback_or_wash` 为 `21` 笔、平均收益 `-0.52%`，`quiet_consolidation_no_supply_test` 为 `5` 笔、平均收益 `-0.48%`，均为 `OBSERVE_ONLY`。
  - 结论：动作 027 仍没有证明年化 10%，也没有产生可晋级策略；它把书单转成了可统计诊断层。下一步应让 A 聚焦核心候选里“突破有效、缩量回踩失败、确认支配正收益、失效支配负收益”的分组，B 再提出是否只把“确认后持有/失效后退出”推进为执行候选。

## 动作 028 - 把有效突破观察簇推进到执行纪律

- 遇到了什么问题？
  - v027 已经证明 `effort_vs_result_breakout` 在核心候选里相对有效，但结论还停留在 `Knowledge Hypothesis Diagnostics` 报告里，没有进入交易层。
  - 同一份诊断也证明 `no_supply_pullback_or_wash` 和 `quiet_consolidation_no_supply_test` 是失败簇，继续把它们当成普通买点会让学习层和执行层断开。
  - 当前程序的问题不是缺少更多书本知识或指标，而是交易层还没有回答：下次遇到同类节点买不买、持有几天、什么时候必须卖。
- 打算怎么做？
  - 新增很窄的实验候选 `volume_price_breakout_follow_through_probe`，只允许 `volume_breakout`，即只执行 `effort_vs_result_breakout`。
  - 通过 `volume_price_probe_allowed_node_types=("volume_breakout",)` 硬阻断 `shrink_pullback`、`quiet_consolidation`，同时也排除 `dry_up_base`。
  - 新增默认关闭的跟随验证退出：`invalidated` 次日卖出；1-3 个持仓 bar 内没有确认则退出；若确认多于警告，允许持有到 3-5 个 bar。
  - 继续用同一 10 股池、同样 `370` 天、同样 `100000` 初始资金回放，和 v027 core 基线比较。
- 这么做有什么意义？
  - 这是把“学习结果”从报告层推进到执行纪律的最小实验，而不是继续扩充指标。
  - 如果失败簇仍能买入，就说明诊断没有真正影响交易；如果突破簇被单独执行后样本过小或回撤变差，也必须如实记录。
  - 这一步验证的是“只交易被证明相对有效的观察簇”是否能改善期望，而不是证明策略已经可实盘。
- 需要改什么？
  - 修改 `src/wealth_lab/trade_discipline.py`：新增 `enable_volume_price_follow_through_exit`、`volume_price_follow_through_no_confirm_bars`、`volume_price_follow_through_max_hold_bars`，并实现 follow-through 退出判断。
  - 修改 `src/wealth_lab/replay.py`：把当前 `bars/current_index` 传给 volume-probe 退出判断，使 T 日证伪能在 T+1 开盘执行卖出。
  - 修改 `src/wealth_lab/training.py`：新增 `volume_price_breakout_follow_through_probe` 实验候选。
  - 修改 `tests/test_volume_probe.py`：验证 shrink/quiet 失败簇被 `node_not_allowed` 阻断，并验证 invalidated、no_follow_through、max_hold 三类退出。
  - 修改 `tests/test_training.py`：验证新候选只允许 `volume_breakout`，且启用 follow-through exit。
- 本轮验证结果
  - A agent `019f3f7d-79e8-75e2-bff6-2e3823dafcd8` 完成只读复核：确认 `volume_breakout -> effort_vs_result_breakout`，`shrink_pullback -> no_supply_pullback_or_wash`，`quiet_consolidation -> quiet_consolidation_no_supply_test`。
  - B agent `019f3f7d-a84d-7a00-92cb-4d703a28a9d7` 完成基线提取：v027 core 基线为 `38` 笔、`9` 个交易股票、平均期望 `0.31%`、平均收益 `-0.08%`、平均最大回撤 `0.46%`。
  - 针对性测试：`python -m pytest tests\test_volume_probe.py tests\test_training.py -q` -> `45 passed`。
  - 全量测试：`python -m pytest` -> `92 passed`。
  - 10 股池训练命令：`python run.py train-replay 000620 002031 601929 000592 600879 002255 002279 000725 600478 002369 --days 370 --initial-cash 100000`。
  - 新训练落盘：`runtime/training/20260708T021623Z-summary.md` 和 `runtime/training/20260708T021623Z-training.jsonl`。
  - 同池 core 结果：`volume_price_support_quality_probe` 与 `volume_price_quiet_exception_flow_guard_probe` 均为 `10` 股、`9` 个交易股票、`38` 笔、平均期望 `0.31%`、平均收益 `-0.05%`、平均最大回撤 `0.43%`，继续 `OBSERVE`。
  - 新候选 `volume_price_breakout_follow_through_probe`：`10` 股、`4` 个交易股票、`9` 笔、平均期望 `5.57%`、平均收益 `0.21%`、平均最大回撤 `0.20%`，晋级结论 `OBSERVE`，原因是闭合交易只有 `9` 笔，低于 `30` 笔门槛。
  - 知识诊断中新候选只剩 `effort_vs_result_breakout`：`9` 笔、胜率 `55.56%`、平均收益 `5.57%`、`REVIEW_CANDIDATE`。
  - 跟随退出已进入逐笔故事：出现 `volume_price_follow_through_exit: invalidated`、`no_follow_through`、`max_hold` 三类卖出 reason。
- 是否达到年化 10.00%？
  - 否。收益和期望相对 core 明显改善，但闭合交易从 `38` 降到 `9`，交易股票从 `9` 降到 `4`，覆盖严重退化，不满足无退化的 5% 改善口径，也不能晋级为默认策略。
- 下一步
  - 不要把新候选提升为 core。
  - A 应继续分析新候选中亏损的 `601929` 三笔突破交易，尤其 `support_too_wide_above_5pct` 和 `expected_open:gap_+0/+3`，判断是否需要给突破簇增加“支撑距离/开盘 gap”守门。
  - B 只能提出一个最小后续方案，例如在突破簇里排除 `support_distance > 5%` 或高开过热；C 必须同池回放证明交易数、交易股票数、收益、期望和回撤的综合改善，否则视为无效改动。
## 动作 029 - 601929 亏损突破的开盘守门实验

- 遇到了什么问题？
  - v028 `volume_price_breakout_follow_through_probe` 已经只交易 `volume_breakout`，但样本太窄，且亏损集中在 `601929` 的三笔突破交易。
  - A 子代理复核发现：`2025-08-15` 亏损对应 `gap +3.01%`，`2025-11-05` 和 `2026-05-20` 亏损对应 `support_distance` 分别约 `10.71%` 和 `9.91%` 且开盘 `gap 0%`。
  - 但同池证据也显示，硬拦所有 `support_distance > 5%` 会误伤 `000592` 和 `600879` 的大幅盈利样本，因此不能机械使用 `>5%` 一刀切。
- 打算怎么做？
  - 保留 v028 原候选 `volume_price_breakout_follow_through_probe` 作为同场对照。
  - 新增独立实验候选 `volume_price_breakout_opening_guard_probe`，仍只允许 `volume_breakout`，只增加一个开盘守门组合：
    - 高开 `gap > 3.0%` 视为突破过热，取消买入。
    - 支撑距离 `> 8.0%` 且开盘 `gap < 0.5%` 视为“极宽支撑但没有开盘需求”，取消买入。
  - 不放开 `shrink_pullback`、`quiet_consolidation`、`dry_up_base`，不修改 core 候选。
- 这么做有什么意义？
  - 这是把 v028 的亏损复盘推进到执行层的最小实验：不是增加新指标，而是验证“同样是突破，哪些开盘状态不该试错”。
  - 保留 v028 原候选可以防止版本漂移，直接比较守门前后交易数、交易股票、收益、期望和回撤。
  - 使用组合守门而非 `support_distance > 5%` 一刀切，是因为当前证据显示宽支撑桶里同时存在大赢家，必须避免误杀高质量样本。
- 需要改什么？
  - 修改 `src/wealth_lab/trade_discipline.py`：新增默认关闭的 `volume_price_breakout_max_opening_gap_pct`、`volume_price_breakout_wide_support_distance_pct`、`volume_price_breakout_min_gap_for_wide_support_pct`，并在 `confirm_volume_probe_opening()` 中增加突破开盘守门。
  - 修改 `src/wealth_lab/training.py`：新增 `volume_price_breakout_opening_guard_probe`，保留 v028 候选不变。
  - 修改 `tests/test_volume_probe.py`：新增高开过热拦截、极宽支撑但开盘需求不足拦截测试。
  - 修改 `tests/test_training.py`：确认 v028 候选不带新守门，v029 候选带新守门。
- 本轮验证结果
  - A agent `019f3f90-f8df-7913-afc4-c86bebf301fc` 完成只读分析：建议从 601929 的宽支撑和 gap 过热入手，但不能放开 shrink/quiet/dry-up。
  - B agent `019f3f91-24bf-7050-a114-1b5a0eda353f` 完成只读方案：最小落点是 `confirm_volume_probe_opening()`，不需要改 `volume_probe.py` 或 `replay.py`。
  - 针对性测试：`python -m pytest tests\test_volume_probe.py tests\test_training.py -q` -> `47 passed`。
  - 全量测试：`python -m pytest -q` -> `94 passed`。
  - 10 股池训练命令：`python run.py train-replay 000620 002031 601929 000592 600879 002255 002279 000725 600478 002369 --days 370 --initial-cash 100000`。
  - 训练落盘：`runtime/training/20260708T023826Z-summary.md` 和 `runtime/training/20260708T023826Z-training.jsonl`。
  - v028 对照 `volume_price_breakout_follow_through_probe`：`10` 股、`4` 个交易股票、`9` 笔、平均期望 `5.57%`、平均收益 `0.21%`、平均最大回撤 `0.20%`，结论 `OBSERVE`。
  - v029 新候选 `volume_price_breakout_opening_guard_probe`：`10` 股、`4` 个交易股票、`6` 笔、平均期望 `11.12%`、平均收益 `0.27%`、平均最大回撤 `0.06%`，结论 `OBSERVE`。
  - `601929` 从 v028 的 `4` 笔、`-0.20%` 收益、`-2.39%` 每笔期望，改善为 v029 的 `1` 笔、`0.45%` 收益、`7.06%` 每笔期望；三笔亏损突破样本被开盘守门拦截。
- 是否达到年化 10.00%？
  - 否。v029 明显降低亏损和回撤，但闭合交易从 `9` 继续降到 `6`，仍低于 `30` 笔晋级门槛，也没有扩大高质量机会池。
  - 按 v026 的 5% 改善纪律，本轮属于“方向有效但过窄”的观察候选，不能晋级 core，也不能作为默认策略。
- 下一步
  - 不继续收窄突破候选，否则会变成只有少数大赢家支撑的过拟合观察。
  - 下一轮 A 应分析 v029 保留的 6 笔交易为什么盈利，尤其 `000592` 与 `600879` 的宽支撑大赢家和 `601929` 被拦截亏损之间的差异。
  - B 只能提出“扩大同类高质量突破机会池”的一个方案，而不是继续加更多防守参数；C 必须证明交易数不再下降。
## 动作 030 - 突破信号后承接确认再入场实验

- 遇到了什么问题？
  - v029 `volume_price_breakout_opening_guard_probe` 改善了质量，但闭合交易从 v028 的 `9` 笔降到 `6` 笔，方向越来越窄。
  - 同池诊断显示最强结构是 `breakout_start:volume_node:volume_breakout`：`2` 笔、胜率 `100%`、平均收益 `27.91%`，典型样本是 `000592 +29.92%` 和 `600879 +25.89%`。
  - `breakout_start:accumulation_watch` 只有观察价值：`3` 笔、平均收益 `2.48%`，其中包含 `600879 -0.82%`，不能直接当买点。
  - 因此本轮要验证用户提出的核心命题：真正买点是不是应该来自“信号日之后的承接证明”，而不是信号当天分类。
- 打算怎么做？
  - 新增独立实验候选 `volume_price_breakout_confirmation_entry_probe`，保留 v028/v029 作为同场对照。
  - 当信号日出现 `volume_breakout / effort_vs_result_breakout` 且原本会买入时，不立刻下单，而是写入观察记录。
  - 下一根 K 线收盘检查承接：不能跌破信号日低点，收盘不能低于信号日收盘，量价状态不能是 `volume_down_risk` 或 `high_volume_stall`，可用主力流不能转负。
  - 通过确认后，再把买入交给既有 pending open 执行路径，在再下一交易日开盘买入；持有和退出继续使用 follow-through 纪律。
  - 继续禁止重新打开 `shrink_pullback`、`quiet_consolidation`、`dry_up_base` 等失败簇。
- 这么做有什么意义？
  - 这是把“先识别异动，再观察承接，再决定是否入场”转成可回放规则，而不是继续加防守 guard。
  - 如果有效，应该在保留 v029 低回撤的同时，把交易数从 `6` 扩到 `12-20` 笔；如果仍然只有少数交易，说明瓶颈已经不是一个守门参数，而是样本池或确认规则本身。
  - 本轮实验直接检验“等待确认会不会买不到”这个问题：不是用主观判断回答，而是用同池近一年回放结果回答。
- 需要改什么？
  - 修改 `src/wealth_lab/trade_discipline.py`：新增 `enable_volume_price_breakout_confirmation_entry`、`volume_price_breakout_confirmation_bars`，并实现观察与确认/取消逻辑。
  - 修改 `src/wealth_lab/replay.py`：新增 `_VolumeConfirmationObservation`，让信号日观察、确认日判断、确认后再下一开盘买入复用既有订单路径。
  - 修改 `src/wealth_lab/training.py`：新增 `volume_price_breakout_confirmation_entry_probe`，继续使用 v029 opening guard、risk sizing 和 follow-through exit。
  - 修改 `tests/test_volume_probe.py`：覆盖信号日不买、确认后再下一开盘买、确认失败取消。
  - 修改 `tests/test_training.py`：确认 v030 候选注册、排序和配置开关。
- 本轮验证结果
  - A agent `019f3fa2-f573-7a92-8d94-26dd7709f5a3` 完成只读分析：强 `volume_node:volume_breakout` 可试探，`accumulation_watch` 只能观察确认，失败簇继续拦截。
  - B agent `019f3fa3-2214-79d3-9aa9-2f67476f9cf3` 完成方案设计：最小切入点是 replay 的 pending observation，不改变 v028/v029 即时买入语义。
  - C agent `019f3fa3-4691-7f33-83bc-905829016a00` 先写测试暴露生产缺口；主线程补齐生产代码和断言修正。
  - 针对性测试：`python -m pytest tests\test_volume_probe.py tests\test_training.py -q` -> `49 passed`。
  - 全量测试：`python -m pytest -q` -> `96 passed`。
  - 10 股池训练命令：`python run.py train-replay 000620 002031 601929 000592 600879 002255 002279 000725 600478 002369 --days 370 --initial-cash 100000`。
  - 训练落盘：`runtime/training/20260708T030427Z-summary.md` 和 `runtime/training/20260708T030427Z-training.jsonl`。
  - v028 对照 `volume_price_breakout_follow_through_probe`：`10` 股、`4` 个交易股票、`9` 笔、平均期望 `5.57%`、平均收益 `0.21%`、平均最大回撤 `0.20%`。
  - v029 对照 `volume_price_breakout_opening_guard_probe`：`10` 股、`4` 个交易股票、`6` 笔、平均期望 `11.12%`、平均收益 `0.27%`、平均最大回撤 `0.06%`。
  - v030 新候选 `volume_price_breakout_confirmation_entry_probe`：`10` 股、`1` 个交易股票、`1` 笔、平均期望 `1.52%`、平均收益 `0.02%`、平均最大回撤 `0.00%`，结论 `OBSERVE`，原因是闭合交易只有 `1` 笔，低于 `30` 笔门槛。
  - 唯一交易故事为 `000620`：`2026-05-19 -> 2026-05-20`，`breakout_start / effort_vs_result_breakout / accumulation_watch`，收益 `1.52%`，退出原因为突破失败，持仓证据里出现连续 `flow_out_with_price_weakness` 警告。
- 是否达到年化 10.00%？
  - 否。v030 没有扩大机会池，反而从 v029 的 `6` 笔继续降到 `1` 笔。
  - 按 5% 改善纪律，v030 覆盖、交易股票数和绝对收益均退化，不能晋级，也不能作为默认策略。
- 下一步
  - 不继续把同一个突破候选越收越窄。
  - A 应回到 v029/v028 的强样本，分析为什么 `000592`、`600879` 的强 `volume_breakout` 等一天确认会错过，而 `accumulation_watch` 又不能直接买。
  - B 下一步只能提出一个不降低覆盖的扩展方案，例如“强 `volume_node:volume_breakout` 保留直接试探，弱 `accumulation_watch` 才走确认队列”，或者扩大股票池/时间窗口验证样本不足问题。
  - C 必须同池回放证明闭合交易数不低于 v029，且收益、期望、回撤不退化，否则视为无效改善。

## 动作 031 - 100 股随机池扩展与资金利用率晋级门槛

- 遇到了什么问题？
  - 10 股池已经不足以判断突破结构是否可泛化；v028/v029 的交易太少，容易把局部样本当成规律。
  - 100 股池旧报告里 `volume_price_breakout_follow_through_probe` 因 `32` 笔闭合交易和 `3.14%` 平均期望被机械标记为 `PROMOTE_CANDIDATE`，但其平均收益只有 `0.06%`。
  - 用户指出核心问题可能不是“策略收益低”，而是“一年里程序到底有多少天真的在市场里”；旧晋级门槛没有单独检查持仓天数、平均仓位、空仓天数、过滤掉的买点和错过大涨原因。
- 打算怎么做？
  - 新增 100-300 股随机池能力，默认排除创业板 `300/301`，并用固定 seed 保证可复现。
  - 在每个候选策略中单独统计 `holding_days`、`cash_days`、`avg_position_pct`、`max_position_pct`、`filtered_buy_signals`、`ordinary_non_signal_days`、`missed_big_moves`。
  - 把 `node_not_allowed:normal` 从“真正被过滤的买点”里拆出来，避免普通非信号日污染过滤归因。
  - 把晋级门槛升级为：样本数、跨股票覆盖、正期望、成本滑点缓冲、持仓利用率、平均仓位、目标年化收益都必须过关。
- 这么做有什么意义？
  - 这一步直接回答“收益低是不是因为没下注”：100 股池证明突破候选的单笔期望仍有观察价值，但资金利用率极低。
  - 它阻止旧门槛把低利用率候选误晋级，避免程序因为几笔高期望交易而忽略全年大部分时间空仓的问题。
  - 它把“错过大涨”拆成三类：真正被合格过滤条件拦截、普通非信号日、完全未识别，后续才能科学判断是识别层问题还是过滤层问题。
- 需要改什么？
  - 新增 `src/wealth_lab/stock_pool.py`，实现 `select_random_a_share_pool()`，默认排除创业板并按 seed 随机抽样。
  - 修改 `src/wealth_lab/cli.py`，让 `train-replay` 支持 `--random-pool-size`、`--random-seed`、`--include-chinext`。
  - 修改 `src/wealth_lab/providers/efinance_provider.py`，兼容当前 efinance 返回的 `股票代码`、`股票名称` 字段。
  - 修改 `src/wealth_lab/training.py`，新增资金利用率、过滤归因、错过大涨诊断，并强化 `_promotion_decision()`。
  - 修改 `tests/test_stock_pool.py` 和 `tests/test_training.py`，覆盖随机池、非创业板过滤、利用率输出和新晋级门槛。
- 本轮验证结果
  - 针对性测试：`python -m pytest tests\test_stock_pool.py tests\test_training.py -q` -> `15 passed`。
  - 全量测试：`python -m pytest -q` -> `100 passed`。
  - 100 股随机池旧回放命令：`python run.py train-replay --random-pool-size 100 --random-seed 20260708 --days 370 --initial-cash 100000`。
  - 旧回放落盘：`runtime/training/20260708T032635Z-summary.md` 和 `runtime/training/20260708T032635Z-training.jsonl`。
  - 本轮新代码重跑随机池时，实时 efinance 全市场行情接口被远端断开，错误落盘在 `runtime/training/v031-random100-20260708T115506.err.log`。
  - 复用同 seed 已完成 100 股 JSONL 生成 v031 回顾报告：`runtime/training/20260708T032635Z-v031-utilization-review.md`。
  - 100 股池实际结果数：`96` 个有效股票结果，`4` 个数据错误；原始随机池 eligible 非创业板数量为 `3799`。
  - `volume_price_breakout_follow_through_probe`：`32` 笔、`18` 个交易股票、平均期望 `3.14%`、平均收益 `0.06%`、持仓利用率 `0.39%`、平均仓位 `0.02%`，新晋级结论为 `OBSERVE`，原因是持仓利用率低于 `1.00%`。
  - `volume_price_breakout_opening_guard_probe`：`28` 笔、`17` 个交易股票、平均期望 `4.28%`、平均收益 `0.06%`、持仓利用率 `0.35%`，仍低于 `30` 笔门槛。
  - 核心 `volume_price_quiet_exception_flow_guard_probe`：`443` 笔、`74` 个交易股票、平均期望 `0.18%`、平均收益 `0.06%`、持仓利用率 `1.89%`，但期望低于 `0.50%` 成本滑点缓冲。
  - `volume_price_breakout_follow_through_probe` 的过滤归因从旧口径 `23617` 个过滤观察拆为：合格过滤 `8478`、普通非信号 `15139`，最高合格过滤原因为 `node_not_allowed:dry_up_base`。
- 是否达到年化 10.00%？
  - 否。扩大到 100 股后，突破候选样本数确实从 `9` 扩到 `32`，但平均收益仍只有 `0.06%`，并且全年持仓利用率只有 `0.39%`。
  - 用户关于“低收益可能是因为大部分时间没下注”的判断被验证为关键瓶颈之一。
- 下一步
  - 不晋级任何候选。
  - 下一轮应优先研究如何提高“高质量买点覆盖率”，而不是继续收紧突破守门。
  - 对突破候选，先分析为什么大量大涨日前仍被归为 `ordinary_non_signal`；这表示程序没有把它们识别成合格买点，而不是已有买点被守门条件错杀。
## 动作 032 - v029 主策略基准的错过机会明细诊断

- 遇到了什么问题？
  - 用户明确要求保留 `volume_price_breakout_opening_guard_probe` 作为当前主策略基准，不再继续随便增加确认条件。
  - v031 只统计了 `missed_big_moves` 的聚合数量，不能回答“哪些大涨前一天没有买、到底是非 `volume_breakout`、开盘 guard、主力流/支撑风险还是历史样本门槛导致”。
  - 原口径只要信号日生成过 `BUY` 决策就不算错过，但 `opening_guard` 可能在次日开盘取消订单，实际没有买入；这会低估“开盘守门拦掉后继续上涨”的样本。
- 打算怎么做？
  - 不修改 `volume_price_breakout_opening_guard_probe` 的买卖规则、参数和候选顺序。
  - 在训练诊断层新增 `MissedOpportunity` 明细和 `missed_opportunity_attributions` 分类聚合。
  - 把“是否错过”改为以次日是否真实成交 `BUY` 为准，而不是以信号日是否产生过 `BUY` 意图为准。
  - 错过机会分类为：`ordinary_non_signal`、`not_volume_breakout`、`history_gate_failed`、`opening_guard_cancel`、`main_flow_or_support_risk_block`、`other_filtered_signal`、`no_buy_signal`。
- 这么做有什么意义？
  - 这一步回答的是“策略为什么没买”，不是“继续收紧策略”。
  - 可以区分识别层问题和执行层问题：如果大涨前多数是 `ordinary_non_signal`，说明程序根本没有把它识别成买点；如果多数是 `opening_guard_cancel`，才说明开盘守门可能误杀。
  - 可以保留 v029 的主策略基准，避免像 `confirmation_entry_probe` 一样因为新增确认条件把交易压到只剩极少数。
- 需要改什么？
  - 修改 `src/wealth_lab/training.py`：新增 `MissedOpportunity`、错过机会分类聚合、明细摘要表、真实成交口径判断、按 `volume_node` 优先归因。
  - 修改 `tests/test_training.py`：新增开盘守门取消但次日未成交的最小 replay 测试；扩展摘要测试覆盖 `Missed Opportunity Attribution` 和明细表。
  - 不修改 `src/wealth_lab/trade_discipline.py`、`src/wealth_lab/replay.py` 的交易执行规则。
- 本轮验证结果
  - 全量测试：`python -m pytest -q` -> `101 passed`。
  - 同一 100 股池重跑命令：
    ```shell
    python run.py train-replay <20260708T032635Z same-seed 100-symbol pool> --days 370 --initial-cash 100000
    ```
  - 最终训练落盘：`runtime/training/20260708T055337Z-summary.md` 和 `runtime/training/20260708T055337Z-training.jsonl`。
  - `volume_price_breakout_opening_guard_probe`：`99` 个有效股票结果，`1` 个数据错误，`30` 笔闭合交易，`18` 个交易股票，`20` 盈、`10` 亏、`0` 平，胜率 `66.67%`。
  - 年内账户口径平均收益：`0.07%`；平均单笔收益/期望：`5.39%`；平均盈利 `9.68%`，平均亏损 `-3.20%`，最好 `41.18%`，最差 `-7.98%`。
  - 资金利用率：`87 / 24176` symbol-days 持仓，持仓利用率 `0.36%`，平均仓位 `0.02%`，空仓 `24089` symbol-days。
  - 错过大涨诊断：`1986` 个平仓状态下未来 5 bars 最大收盘涨幅 >= `10%` 的错过节点；其中 `631` 个是合格过滤/守门导致，`1355` 个是普通非信号日，`0` 个完全无同日量价决策。
  - 错过机会分类：`ordinary_non_signal=1355`、`not_volume_breakout=498`、`history_gate_failed=114`、`opening_guard_cancel=16`、`other_filtered_signal=3`。
- 是否达到年收益 10.00%？
  - 否。虽然平均单笔收益较高，但全年资金部署极低，账户口径平均收益只有约 `0.07%`。
- 下一步
  - 不继续给 `opening_guard` 加确认条件。
  - 优先研究 `ordinary_non_signal` 与 `not_volume_breakout` 中的大涨样本，判断是识别层漏掉了可交易结构，还是这些上涨本身不可在事前稳定识别。

## 动作 033 - 删除默认策略池中的其他策略

- 遇到了什么问题？
  - 用户要求“其他策略都删除掉”，当前 `train-replay` 默认仍会注册大量历史实验候选，导致每次训练继续比较 baseline、quiet、dry-up、confirmation-entry 等旧策略。
  - 这会分散下一步研究重点，也让报告继续把已经被否定或搁置的候选放进同场比较。
- 打算怎么做？
  - 默认训练候选只保留 `volume_price_breakout_opening_guard_probe`。
  - 把它提升为当前唯一 `core` 策略基准。
  - 旧候选构造保留为 `_legacy_training_candidates()`，仅用于旧实验配置追溯，不再被默认训练入口调用。
- 这么做有什么意义？
  - 当前程序进入单主线：所有训练、资金利用率和错过机会分析都围绕 `opening_guard` 主策略展开。
  - 避免继续把失败策略或过窄策略混在训练报告里，减少调参噪声。
  - 保留旧配置追溯入口，避免破坏历史报告解释和诊断代码。
- 需要改什么？
  - 修改 `src/wealth_lab/training.py`：`default_training_candidates()` 只返回 `volume_price_breakout_opening_guard_probe`，`CORE_CANDIDATE_NAMES` 同步只保留该策略。
  - 修改 `tests/test_training.py`：默认候选测试改为只验证这一条主策略。
  - 修改 `README.md`：`train-replay` 描述从“多套模拟盘纪律参数”改成“当前主策略基准”。
- 本轮验证结果
  - `python -m pytest tests\test_training.py -q` -> `13 passed`。
  - `python -m pytest -q` -> `101 passed`。
  - 直接探针：
    ```text
    len(default_training_candidates()) = 1
    names = ['volume_price_breakout_opening_guard_probe']
    tiers = ['core']
    ```
- 是否达到年收益 10.00%？
  - 本轮没有重跑收益训练；这是策略池删减和默认入口收敛，不是收益改善。
- 下一步
  - 后续训练报告将只围绕 `volume_price_breakout_opening_guard_probe` 输出，先把主线研究清楚，再决定是否从错过机会分析中恢复新的子结构。

## 动作 034 - 主策略扩样验证入口与错过突破机会报告

- 遇到了什么问题？
  - 当前主策略 `volume_price_breakout_opening_guard_probe` 的方向暂时不能说错，但样本少、交易覆盖低、资金利用率低，不能直接通过调权重解决。
  - 旧摘要已经有错过机会聚合，但还缺少独立的 `missed_breakout_opportunity_report`，不方便逐笔复盘“大涨前一天为什么没买”。
  - 单次 300 股池运行暴露了数据层问题：外部历史行情/资金流请求在大池子下可能长时间等待，缺少断点续跑和单符号超时。
- 打算怎么做？
  - 不修改买卖规则、不改策略参数，只增强验证与报告。
  - 新增嵌套随机池选择：先抽最大池，再取 50/100/300 前缀，保证三轮样本可比较。
  - 新增 `validate-expansion` CLI，一次运行多轮扩样验证。
  - 在训练摘要中新增 `Trade Return Concentration`，检查收益是否靠 1-2 笔大肉支撑。
  - 为每轮训练单独输出 `*-missed_breakout_opportunity_report.md`，字段包含 `next_1d/3d/5d`、`max_gain`、`max_drawdown`、`strategy_action`、`blocked_reason`、`volume_node`。
- 这么做有什么意义？
  - 先回答“策略有没有结构优势”，再决定是否调权重。
  - 如果错过机会主要来自 `opening_guard_cancel`，才说明开盘守门可能误杀；如果主要来自 `ordinary_non_signal` 和 `not_volume_breakout`，说明问题在识别层覆盖，不应继续收紧守门。
  - 收益集中度可以防止少数大肉掩盖策略整体弱覆盖。
- 需要改什么？
  - 修改 `src/wealth_lab/stock_pool.py`：新增 `NestedStockPoolSelection` 和 `select_nested_random_a_share_pools()`。
  - 修改 `src/wealth_lab/training.py`：新增错过机会最大回撤字段、独立 missed report 渲染、扩样验证总表渲染、交易收益集中度聚合。
  - 修改 `src/wealth_lab/cli.py`：新增 `validate-expansion` 命令，并为大池验证增加逐股进度输出。
  - 修改 `src/wealth_lab/providers/efinance_provider.py`：当 efinance 全市场实时行情失败时，尝试东方财富 HTTPS 直连接口兜底。
  - 修改 `tests/test_stock_pool.py` 和 `tests/test_training.py`：覆盖嵌套池、收益集中度、missed report 和扩样汇总。
- 本轮验证结果
  - 针对性测试：`python -m pytest tests\test_stock_pool.py tests\test_training.py -q` -> `17 passed`。
  - 全量测试：`python -m pytest -q` -> `102 passed`；补充进度输出和行情兜底后再次全量测试仍为 `102 passed`。
  - 扩样命令：`python run.py validate-expansion --pool-sizes 50 100 300 --random-seed 20260708 --days 370 --initial-cash 100000`。
  - 50 股池落盘：`runtime/training/20260708T065056Z-summary.md`、`runtime/training/20260708T065056Z-missed_breakout_opportunity_report.md`、`runtime/training/20260708T065056Z-training.jsonl`。
  - 100 股池落盘：`runtime/training/20260708T065159Z-summary.md`、`runtime/training/20260708T065159Z-missed_breakout_opportunity_report.md`、`runtime/training/20260708T065159Z-training.jsonl`。
  - 阶段性扩样总结：`runtime/training/20260708T145054-expansion-validation-partial-summary.md`。
  - 50 股池：`49` 个有效结果、`1` 个数据错误、`16` 笔闭合交易、`8` 个交易股票、平均单笔期望 `5.11%`、平均账户收益 `0.09%`、持仓利用率 `0.39%`、平均仓位 `0.03%`。
  - 100 股池：`96` 个有效结果、`4` 个数据错误、`30` 笔闭合交易、`18` 个交易股票、平均单笔期望 `5.39%`、平均账户收益 `0.07%`、持仓利用率 `0.37%`、平均仓位 `0.02%`。
  - 100 股池错过机会归因：`ordinary_non_signal=1322`、`not_volume_breakout=479`、`history_gate_failed=113`、`opening_guard_cancel=16`、`other_filtered_signal=3`。
  - 100 股池收益集中度：`30` 笔交易中 `20` 盈，最大单笔盈利贡献占盈利总和 `21.25%`，前两笔盈利贡献 `33.84%`，不是完全靠 1-2 笔大肉，但资金利用率过低。
  - 300 股池未完成：第一次后台进程长时间无新训练产物、stdout/stderr 均为空，已停止。
  - 300 股池单独重试：`python -u run.py validate-expansion --pool-sizes 300 --random-seed 20260708 --days 370 --initial-cash 100000` 在选池阶段失败，错误落盘 `runtime/training/20260708T154845-validate-expansion-300.err.log`；根因是 `efinance quote request failed after 3 attempts`，随后 HTTPS 直连兜底也在 `eastmoney direct quote request failed on page 1` 失败。
  - 当前结论：300 池不是策略回放失败，而是全市场实时行情选池数据源在当前时间不可用；需要缓存池、断点续跑或更稳定的行情源后再补全 300。
- 是否达到年收益 10.00%？
  - 否。50/100 股池均保持正单笔期望，但账户口径平均收益仍接近 0，主要瓶颈是持仓利用率和识别覆盖率过低。
- 下一步
  - 先给 300 股池验证增加缓存池、断点续跑/分批落盘/单符号超时，保证大样本能稳定完成。
  - 在已完成的 missed report 中优先分析 `ordinary_non_signal` 和 `not_volume_breakout` 的大涨样本，而不是先调开盘 gap、支撑距离或仓位权重。
## 动作 035 - 扩样验证数据层加固与 300 池有效性复核

- 遇到了什么问题？
  - 用户要求下一步先扩大样本验证，再看错过与误买，最后才调权重；因此不能继续增加买卖条件或调策略参数。
  - 上一轮 300 股池在选池阶段失败，根因是 efinance/东方财富全市场现货接口断开，导致没有稳定 universe。
  - 直接重试 50/100/300 会重复拉取嵌套池前缀数据，且训练中 efinance 历史接口和 BaoStock login/logout 带来大量无效等待。

- 打算怎么做？
  - 不修改 `volume_price_breakout_opening_guard_probe` 的买入、卖出、仓位和 guard 条件。
  - 给 quote universe 增加缓存：live 成功时写入 `runtime/quote_universe/*.json`，live 失败时优先读最近缓存。
  - 增加 Tencent A 股 universe fallback，只用于生成代码池；真实训练仍逐只拉历史 K 线和资金流验证。
  - 将 `validate-expansion` 改为只跑最大池一次，再从同一嵌套前缀派生 50/100 报告，避免重复请求。
  - 训练阶段增加进度快照、BaoStock 会话复用、efinance 历史连续失败后跳过，以及每 10 只落盘一次，降低大池验证抖动。

- 这么做有什么意义？
  - 先把“大样本是否真的可验证”这件事做扎实，避免把数据源失败误判成策略失败。
  - 保证 50/100/300 来自同一个嵌套样本，并且 300 中途失败时仍有 partial JSONL/summary/missed report 可复盘。
  - 把当前瓶颈从“程序跑不完”推进到“跑完后能明确判断样本有效性不足在哪里”。

- 需要改什么？
  - 修改 `src/wealth_lab/stock_pool.py`：新增 quote universe 缓存读写、缓存回退、Tencent universe fallback 和 universe 来源记录。
  - 修改 `src/wealth_lab/cli.py`：`validate-expansion` 改为最大池单跑、前缀池派生报告，并打印 universe 来源和缓存路径。
  - 修改 `src/wealth_lab/training.py`：新增 `TrainingHistoricalBarFetcher`、进度落盘、公开 artifact 写入函数、训练期间跳过重复失败的 efinance 历史请求。
  - 修改 `src/wealth_lab/providers/historical_provider.py`：BaoStock 支持训练期间复用 session，并跳过空值 K 线行。
  - 修改 `tests/test_stock_pool.py`：覆盖缓存回退和 Tencent fallback。

- 本轮验证结果
  - 针对性测试：`python -m pytest tests\test_stock_pool.py tests\test_training.py -q` -> `19 passed`。
  - 全量测试：`python -m pytest -q` -> `104 passed`。
  - 扩样命令：`python run.py validate-expansion --pool-sizes 50 100 300 --random-seed 20260708 --days 370 --initial-cash 100000`。
  - universe 来源：`cache_after_live_failure`，缓存文件 `runtime/quote_universe/latest.json`，可选非创业板 universe 数量 `3805`。
  - 扩样汇总：`runtime/training/20260708T084723Z-expansion-validation-summary.md`。
  - 300 池主报告：`runtime/training/20260708T081658Z-summary.md`、`runtime/training/20260708T081658Z-training.jsonl`、`runtime/training/20260708T081658Z-missed_breakout_opportunity_report.md`。
  - 派生 50 池：`runtime/training/20260708T081658Z-pool50-summary.md`、`runtime/training/20260708T081658Z-pool50-training.jsonl`。
  - 派生 100 池：`runtime/training/20260708T081658Z-pool100-summary.md`、`runtime/training/20260708T081658Z-pool100-training.jsonl`。
  - 50 池：有效 symbol `31`，错误 `19`，闭合交易 `5`，交易股票 `3`，平均单笔期望 `0.77%`，平均账户收益 `0.01%`，持仓利用率 `0.14%`。
  - 100 池：有效 symbol `31`，错误 `69`，闭合交易 `5`，交易股票 `3`，平均单笔期望 `0.77%`，平均账户收益 `0.01%`，持仓利用率 `0.14%`。
  - 300 池：有效 symbol `32`，错误 `268`，闭合交易 `5`，交易股票 `3`，平均单笔期望 `0.77%`，平均账户收益 `0.01%`，持仓利用率 `0.14%`。
  - 错误归因：`241/268` 个错误为 `efinance fund-flow request failed after 3 attempts`，`27/268` 个为历史 K 线空值/缺失类错误；AKShare 个股资金流接口同样连接东方财富并被远端断开，不能作为有效 fallback。

- 是否达到年收益 10.00%？
  - 否。虽然 300 命令工程上跑通，但有效样本只有 `32/300`，闭合交易只有 `5`，不能作为 300 股扩样策略证据。
  - 当前主结论不是“策略失败”或“策略成功”，而是：资金流数据源可用性不足已经成为扩大样本验证的硬瓶颈。

- 下一步
  - 不调 `opening_guard`、支撑距离、仓位权重。
  - 先解决资金流历史数据稳定来源，或建立可审计的资金流缓存/离线数据集；否则 100-300 股扩样统计会被数据错误污染。
  - 在资金流数据稳定前，错过机会分析只能基于已经有效的 50/100 历史报告和本轮 32 个有效样本，不能宣称覆盖了 300 股池。
