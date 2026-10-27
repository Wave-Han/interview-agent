# Interview Agent Phase 3(Eval 黄金集 + 生成器-评估器多 Agent)— 设计文档

- 日期:2026-10-27
- 状态:三节设计已与用户确认
- 前置:Phase 1/2 已完成(45 测试,https://github.com/Wave-Han/interview-agent)

## 1. 背景与目标

Phase 1/2 交付了刷题与 RAG 问答,但判题质量无量化。Phase 3 交付 **Eval 体系**:

1. **黄金集**:20 题 × 3 档答案(good/partial/bad)+ 期望分区间,`eval` 子命令自动判分比对,产出**档位命中率**等指标——简历可引用的硬数字;
2. **生成器-评估器多 Agent**:黄金集答案由生成器 Agent 生成(独立上下文,看不到 rubric),评估器(现有判题管线)打分——生成/评估隔离,这是本项目多 Agent 的真实落地,不做装饰性出题/判题拆分;
3. **清完 P2 终审遗留**:seed guard 白名单收紧、save_with_fallback 回退兜底、embed 64 分批下沉+单测、`_post` 死分支。

成功标准:`eval` 真跑一次,60 案例档位命中率落 `docs/eval/report-*.md`;quiz 流为零改动;全部测试绿。

## 2. 已确认决策

| 决策项 | 选择 |
|--------|------|
| 多 Agent 形态 | 生成器-评估器(Eval 的实现手段),不拆 quiz |
| 黄金集来源 | 生成器生成草稿 + 控制器(session 内)逐条校对定稿 |
| 命中规则 | score ∈ case.range 为 hit;报告总/分档命中率 + 平均分差 |
| eval 存储隔离 | 不落 attempts/wrong_notes;EvalRecorder 内存收集 |

## 3. 数据

`interview_agent/data/golden.json`:
```json
[{"question_id": 1, "cases": [
   {"band": "good",    "range": [0.7, 1.0], "answer": "..."},
   {"band": "partial", "range": [0.3, 0.6], "answer": "..."},
   {"band": "bad",     "range": [0.0, 0.2], "answer": "..."}]}]
```
- 20 题覆盖 8 topic,必含历史错题对应题(元空间、浮动垃圾、三次握手、工具调用分工、embedding 语义检索、物理序=主键、G1 大稳懒、小顶堆守门员等);
- 答案中文、口吻自然(像备考者口述),长度贴近真实作答(1~4 句);
- 校对规则(控制器执行):good 答案须覆盖该题全部要点;partial 须只覆盖约一半且不虚构新要点;bad 须方向错误或答非所问,但仍是"认真的错误答案"而非乱码。

## 4. 架构

### 4.1 判题核共享(不双轨)

`session.py` 抽出 `build_rubric_message(q: Question, answer: str) -> str`(现有格式逐字不变:`question_id: %d\nQuestion...` + USER ANSWER 定界);quiz 的 `grade()` 改调它——**行为零变化**(现有测试必须原样通过)。

### 4.2 Eval 管线(`interview_agent/eval/`)

- `runner.py`:`run_eval(client, qrepo, golden: list, sample: int | None = None) -> EvalReport`
  - 每个 case:构建与 quiz 相同的 rubric 消息 → `run_agent`(同一 loop)→ 但 registry 的工具面仅 `record_result`,其 handler 为 `EvalRecorder.record(question_id, score, feedback)`(内存 dict,不落库);
  - 循环结束后从 recorder 取该 case 的 score;**无 record_result 调用**(模型未调工具)记 score=None,标 `miss`(并计入报告的 `no_record` 计数);
  - `sample` 非空时随机抽 N 个 case(种子固定,可复现);
- `EvalReport`(dataclass):`total/hits/no_record/per_band: dict/avg_delta: float/cases: list[CaseResult]`;`format_table() -> str`(stdout 中文表格);`write_markdown(path)`(分档明细+参数+日期,供简历引用);
- `__main__.py` 增 `eval` 子命令(`--sample N` 可选):跑完打印表格并写 `docs/eval/report-YYYY-MM-DD.md`,退出码 0(命中与否不作为退出码——它是度量不是门禁)。

### 4.3 生成器(`scripts/generate_golden.py`,一次性基建,不进包)

- 复用 `LLMClient.chat`;输入:`--ids 1,2,...`(默认 20 题清单)→ 每题 3 次独立调用;
- prompt 仅含**题面 + 档位行为规格**("针对该题写一个'只覆盖一半要点'的口述答案"),**绝不给 answer_points**——生成/评估上下文隔离;
- 输出草稿 `scripts/golden_draft.json`(带 band 标注),由控制器(session 内)校对定稿为 `data/golden.json`(校对动作发生在 writing-plans 阶段:计划中给出 60 条定稿全文)。

### 4.4 P2 遗留清理

1. seed guard 白名单:`TERM_LIST_SINGLE_FACTS` 由全局字符串改为 `(question_id, point)` 二元组匹配;
2. `save_with_fallback`:回退后 SQLite 再 save 失败 → 捕获打印一行中文,不再裸抛;
3. 64 分批下沉:`LLMClient.embed` 内部按 `EMBED_BATCH=64` 分块(`__main__.py` index 分支改为一次调用),补一条分批单测(65 条输入 → 2 次请求拼接);
4. `client.py` `_post` 内不可达的 KeyError 捕获分支删除(解析已移出)。

## 5. 错误处理

- eval 中单 case LLM 异常:捕获记为该 case 失败(score=None, band 标 `error`),**继续跑完其余 case**(报告含 error 计数,不中断);
- golden.json 中 question_id 不存在:启动即校验,报中文错误退出(不静默跳过);
- 生成器脚本失败:草稿文件尽量落盘已生成部分,报错退出。

## 6. 测试(45 → 约 52)

- `build_rubric_message`:与 quiz 现格式逐字一致断言(共享后 quiz 测试原样通过即为回归保证);
- `EvalRecorder` + eval registry:fake client 走完 1 case,score/feedback 被记录、DB attempts 零新增(核心隔离断言);
- `run_eval`:fake client 三档 case 命中/越界/未调工具(no_record)三种路径;sample 抽样可复现;
- 报告:format_table 含总命中率字样;write_markdown 生成文件含分档明细;
- golden 校验:坏 id 报错;数据质量守护(good 答案非空、range 合法);
- 遗留项各一条:白名单二元组命中/未命中、fallback 双重失败打印、embed 65 条分 2 批;
- **真实运行**(交付时人工+子代理共执):`eval` 全量真跑,报告落 docs。

## 7. 验收标准(DoD)

1. `python -m interview_agent eval` 全量真跑成功,`docs/eval/report-*.md` 落盘,含总命中率数字;
2. quiz/ask/index 行为零变化(现有 45 测试原样绿);
3. P2 遗留 4 项全清;pytest 全绿(约 52);
4. README/CLAUDE.md 同步(eval 用法、生成器说明、Phase 4 待办);
5. 流程:writing-plans(含 60 条黄金集答案定稿)→ SDD(实现→逐任务评审→终审)。

## 8. 明确不做(Phase 4+)

Web 界面、ANN 索引、判题 prompt 自动调优闭环(本轮只测不调)、跨模型对比 eval。
