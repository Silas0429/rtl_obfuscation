# T109：只读 identifier 绑定覆盖率探测器

- 状态：`ACCEPTED`
- 主 Agent：Claude Fable 5
- 执行者：主 Agent 直接实现（用户在本轮明确要求"先把探测器本身实现出来"）
- 起始 HEAD：`c3cf87ade670e3234b2787bc1176e959122f2545`
- 任务类型：只读诊断工具 + 确定性测试 + 架构论证文档
- 前置任务：[`T108`](T108_pyslang_rename_index.md) 已置 `BLOCKED`，本任务不修改其产品代码
- 架构依据：[`token_first_binding.md`](../development/architecture/token_first_binding.md)

## 1. 单一目标

提供一个只读工具，对任意 SourceSet 回答一个问题并输出机器可读结果：

> 源码集合中每一个物理 identifier token，有多少能归因到唯一 PySlang 语义目标，剩下的是什么。

工具不改写 RTL、不产生 gate、不创建输出目录、不引入任何 preserve/rename 决策。
它的用途是把"我们究竟能绑定多少"从推断变成一次可复现的测量，为是否改造产品提供依据。

## 2. 不包含的内容

- 不修改 `rtl_obfuscator/` 下任何产品代码；
- 不新增或修改公开 CLI、category、mapping schema、SourceSet 语义、PySlang 编译配置；
- 不实现声明维度表达式的作用域重解析（`token_first_binding.md` §4 已记录该边界与理由）；
- 不实现类二的任何语法规则（本任务只**测量**残差，不消除残差）；
- 不运行 Yosys/Formal，不运行 `tests.test_risc_v_vector_project_root`，不使用 blanket discovery。

## 3. 固定输入

三种输入模式与产品一致且互斥，复用 `rtl_obfuscator/source_set.py` 的
`from_filelist / from_project_root / from_single_file`：

| 模式 | 参数 |
| --- | --- |
| filelist | `--filelist FILE`，`--top` 可选 |
| project-root | `--source-root DIR --top TOP` |
| 单文件 | `--input FILE` |

附加 `--include-dir`（可重复）、`--define`（可重复）、`--json PATH`、`--examples N`、
`--worst-names N`、`--quiet`。编译复用 `rtl_obfuscator/project_discovery.py` 的
`compile_pyslang_source_set`（`SourceCatalog` 不暴露 `syntax_tree`，故直接取该 view）。

本地固定 fixture：`tests/fixtures/t109_binding_coverage/design.f`，其 `design.sv` 必须同时复现
三个服务器根因形状 —— 命名端口连接顺序与声明顺序不同、modport 限定的 interface port、
成员后接 part-select，并含 `data.a.a` 形式的嵌套同名成员。

## 4. 机器可读输出

`format=rtl-obfuscation.binding-coverage`、`schema_version=1`，至少包含：

- `tokens`：物理 identifier token 总数、宏展开视图数、`byte_mismatch`、`outside_source_set`、
  转义标识符数、同一物理 token 的最大展开次数、`design_units`、`elaborated_design_units`、
  `dead_generate_blocks`、`tokens_in_unelaborated_source`；
- `semantic_references`：引用节点数、可用引用数、不同目标符号数；
- `declarations`：命名符号数、已归属声明数、聚合字段数、in-scope 名字数及其按组分布；
- `join` 的三层分母：`overall`、`in_scope`、`in_scope_elaborated`。前两层各含
  `identifier_tokens / accounted / unaccounted / ambiguous / coverage_ratio`；
  `in_scope_elaborated` 另含 `excluded_unelaborated_tokens`，是**决策数字**；
- `residual_by_syntax_kind`、`residual_in_scope_by_syntax_kind`、
  `residual_in_scope_elaborated_by_syntax_kind`：每项含 `syntax_kind`、`parent_syntax_kind`、
  `tokens`、`distinct_names`、带 file/start/text 的 examples；
  `in_scope_elaborated` 版本另含 `reasons` 计数与 `reason_sample`，用于区分
  `no_reference_for_this_spelling`（确需类二规则）与 `reference_range_excludes_token`
  （区间锚定问题或该 token 是标签而非表达式）；
- `completeness` 的三层：`overall`、`in_scope`、`in_scope_elaborated`，各含 `distinct_names`、
  `names_fully_accounted`、`names_with_unaccounted_tokens`、`renameable_name_ratio`、`worst_names`。

死源码判定：设计单元的名字 token 不在任何 `InstanceBodySymbol`/`PackageSymbol` 的声明位置集合里，
或位于 `GenerateBlockSymbol.isUninstantiated` 为真的 generate 分支内。此类 token 不可能带语义引用，
是既有 preserve 边界（见 T101），必须从决策分母中扣除并单独计数。

不变量：`tokens.byte_mismatch` 必须为 0；未提供 `--json` 时不得写任何文件；
输入模式冲突时以退出码 2 和 `PROBE_INPUT_MODE_INVALID` 失败。

## 5. 允许修改

- 新增 `scripts/binding_coverage.py`
- 新增 `tests/test_binding_coverage.py`
- 新增 `tests/fixtures/t109_binding_coverage/design.f`、`design.sv`、`dead_code.f`、`dead_code.sv`
- 新增 `docs/development/architecture/token_first_binding.md`
- 新增本任务单
- 修改 `docs/tasks/T108_pyslang_rename_index.md`（仅更正 §14 误诊并置 `BLOCKED`）
- 修改 `docs/development/architecture/README.md`（仅为新文档补索引条目，避免孤儿文档）

不得修改其他任何文件。

## 6. 固定验收命令（5 条）

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_binding_coverage -v

conda run -n rtl_obfuscation python scripts/binding_coverage.py \
  --filelist tests/fixtures/t109_binding_coverage/design.f --top t109_top --quiet

conda run -n rtl_obfuscation python scripts/binding_coverage.py \
  --filelist rtl_samples/example_fifo/design.f --top fifo_top --quiet

conda run -n rtl_obfuscation python -m py_compile \
  scripts/binding_coverage.py tests/test_binding_coverage.py

git diff --check HEAD
```

状态守卫（实现完成时用 `READY_FOR_REVIEW` 形式验证并通过，主 Agent 验收后改为下列当前形式）：

```sh
conda run -n rtl_obfuscation python -c 'from pathlib import Path; \
s=next(l for l in Path("docs/tasks/T109_binding_coverage_probe.md").read_text().splitlines() if l.startswith("- 状态：")); \
t=next(l for l in Path("docs/tasks/T108_pyslang_rename_index.md").read_text().splitlines() if l.startswith("- 状态：")); \
assert s=="- 状态：`ACCEPTED`", s; assert t=="- 状态：`BLOCKED`", t; print("t109_accepted=pass")'
```

## 7. 服务器测量（验收的第二半）

```sh
export PROJ=/home/lufengchi/workspace/ChipPlatform
python scripts/binding_coverage.py \
  --filelist "$PROJ/aic_ss/src/stcache/StCache.f" \
  --top StChCore \
  --include-dir "$PROJ/common/src/StLib/common" \
  --include-dir "$PROJ/common/src/StLib/impl_template/tsmc4" \
  --json /home/lufengchi/workspace/test/stcache_binding_coverage_001.json
```

判读顺序见 `token_first_binding.md` §5。本任务的 `ACCEPTED` 不要求某个覆盖率数值达标 ——
探测器的正确性由第 6 节门禁保证；服务器数据用于决定**下一张**任务，不作为本任务的通过条件。
若服务器运行出现异常退出或 `byte_mismatch != 0`，本任务回到 `IN_PROGRESS` 修正探测器本身。

## 8. Formal verification

```text
formal_verification: N/A
reason: this task produces no rewritten RTL; the probe is read-only and emits
        only a JSON measurement report
```

## 9. 执行记录

```text
status: ACCEPTED（实现完成时为 READY_FOR_REVIEW，主 Agent 独立复跑第 6 节门禁后转 ACCEPTED）
starting_head: c3cf87ade670e3234b2787bc1176e959122f2545
changed_files: scripts/binding_coverage.py; tests/test_binding_coverage.py;
  tests/fixtures/t109_binding_coverage/design.f; tests/fixtures/t109_binding_coverage/design.sv;
  tests/fixtures/t109_binding_coverage/dead_code.f; tests/fixtures/t109_binding_coverage/dead_code.sv;
  docs/development/architecture/token_first_binding.md; docs/development/architecture/README.md;
  docs/tasks/T109_binding_coverage_probe.md;
  docs/tasks/T108_pyslang_rename_index.md (§14 更正 + 置 BLOCKED)
commands: 第 6 节 5 条门禁
results: unittest 15 tests exit 0; 两次探测退出码 0，byte_mismatch=0；py_compile exit 0；
  git diff --check HEAD exit 0
findings: 1. 实测推翻 T108 §14 的两处机制描述（见 T108 §15）；
  2. 实测确认声明维度不产生 AST 表达式节点，故计划中的"维度表达式遍历"无从实现，已改为如实记录该边界；
  3. 首版探测器用 id(target) 标识语义目标，在 RISC-V-Vector 上报出 1294 个 in-scope 歧义；
     根因是 elaboration 为同一物理声明产生多个 Python 对象（eb_one_slot.sv 被实例化 4 次）；
     改为按物理声明位置标识后 in-scope 覆盖 70.75%→92.47%、残差 1737→447、歧义 1294→0
boundaries: 探测器不消除残差、不改产品；`$no_enclosing_syntax` 是跨 buffer 语法节点的分类边界；
  维度里的 parameter/genvar 引用无 AST 节点，属核心组外；for 循环局部变量被计入 in-scope 分母，
  使覆盖率略偏悲观（方向安全）；RISC-V-Vector 的 files_rtl.f 含 `-sv` 指令，SourceSet 不支持，
  故规模验证改用 project-root 模式（既有产品边界，非探测器缺陷，失败方式为退出码 2 + 稳定错误码）
scale_evidence: rtl_samples/RISC-V-Vector（project-root，top vector_top，19 source units，
  7462 物理 identifier token，byte_mismatch=0）：in-scope 覆盖 5491/5938 (92.47%)，
  残差 447 全部落在四条规则族内，其中 NamedPortConnection 占 388（87%）；
  单独实现该一条规则即可把 in-scope 覆盖推到约 99%
cleanup_candidates: 无
formal_verification: N/A（见第 8 节）
review_request: 本地门禁已通过；服务器测量待用户执行后决定下一张任务
```

## 10. 主 Agent 验收记录

```text
local_gate_1: conda run -n rtl_obfuscation python -m unittest tests.test_binding_coverage -v
  → exit 0, 15 tests passed
local_gate_2: t109 fixture 探测 → exit 0；in-scope 覆盖 53/65；残差 6 条产生式；byte_mismatch=0
local_gate_3: example_fifo 探测 → exit 0；in-scope 覆盖 174/199；残差 7 条产生式；byte_mismatch=0
local_gate_4: py_compile → exit 0
local_gate_5: git diff --check HEAD → exit 0
status_guard: t109_ready_for_review=pass（T109=READY_FOR_REVIEW，T108=BLOCKED）
scale_check: RISC-V-Vector project-root 探测 → exit 0；in-scope 覆盖 92.47%；歧义 0；byte_mismatch=0
allowlist_review: pass；工作区仅含第 5 节 allowlist 的路径，无产品代码改动
local_result: PASS
accepted_at: 2026-08-27；依据第 7 节冻结条件，服务器数据用于决定下一张任务，不是本任务的通过条件
reopen_clause: 若服务器运行异常退出或 byte_mismatch != 0，本任务回到 IN_PROGRESS 修正探测器本身
server_measurement: 首次与死源码修正后复测均已完成（见第 11、11.1 节）；
  残差头部已定性，SVA 与 CSR 生成代码两簇需带归因的第三轮数据
```

## 11. 服务器首次测量与探测器修正（2026-08-27）

服务器在提交 `cf5c96e` 上运行第 7 节命令，`byte_mismatch=0`、`ambiguous=2`、
`parse_errors=0`，探测器本身未异常退出。规模：154 source units，61659 个物理 identifier token，
112926 个引用节点，6403 个不同目标符号。

首版报告的 `in_scope` 覆盖仅 55.31%，但审查发现该数字被**未 elaboration 源码**污染：

```text
data_o     accounted=11  unaccounted=3000
data_i     accounted=15  unaccounted=2873
syndrome_o accounted=6   unaccounted=2860
```

三个名字占 in-scope 残差 20406 的 43%，全部位于 `src/common/ecc/ecc_list/prim_secded_*`。
本地实测确认：只被未选中 generate 分支实例化的模块，其 body 完全不进 AST，
所有 identifier 都不可能带语义引用；ECC 库多个位宽变体共用端口名，被选中变体把
`data_i/data_o/syndrome_o` 带进 in-scope 名字集合后，未选中变体的同名 token 全被计成"缺规则"。

这是 T101 已认识的 preserve 边界，不是绑定规则缺失。因此在同一任务内修正探测器口径：

- 新增死源码检测的两种形态：未 elaborate 的设计单元；`GenerateBlockSymbol.isUninstantiated`
  为真的 generate 分支；
- 报告改为三层分母，新增 `join.in_scope_elaborated`、
  `residual_in_scope_elaborated_by_syntax_kind`、`completeness.in_scope_elaborated`，
  并新增 `tokens.design_units / elaborated_design_units / dead_generate_blocks /
  tokens_in_unelaborated_source`；
- 新增 fixture `tests/fixtures/t109_binding_coverage/dead_code.{f,sv}` 复现 ECC 名字碰撞与
  死 generate 分支，并新增 3 条断言。

修正后的本地效果：

| 输入 | `in_scope` | `in_scope_elaborated` | 排除死源码 |
| --- | --- | --- | --- |
| `dead_code.f` | 39.13% | **90.00%** | 26 token（2 死单元 + 1 死分支） |
| RISC-V-Vector | 92.47% | **92.55%** | 410 token（39 个死 generate 分支） |
| example_fifo | 87.44% | 87.44% | 0 |
| `design.f` | 81.54% | 81.54% | 0 |

RISC-V-Vector 修正后残差 412，其中 `NamedPortConnection` 占 372（90%）；
`SimplePropertyExpr` 那 16 个也随死分支排除而消失，证明它们本来就是死源码而非 SVA 绑定问题。

服务器需在本次修正后**重跑一次**第 7 节命令，用 `join.in_scope_elaborated` 判读。

## 11.1 修正后的 StCache 复测结果（2026-08-27）

```text
in_scope_elaborated  23079 / 34261 = 67.36%
排除死源码 11399 token（140 单元中 103 elaborate，101 个死 generate 分支）
renameable_name_ratio 1035 / 3637 = 28.46%
byte_mismatch = 0    ambiguous = 2（均为 StChAssert.sv 宏体共享的 clk/rst_n，各 11 个竞争声明）
```

残差 11182 的头部与 RISC-V-Vector 完全一致：`NamedPortConnection` 4178（37%）居首，
`IdentifierName < ScopedName` 1075（interface 前缀）、`NamedType` 222、
`DotMemberClause` 97 + `InterfacePortHeader` 90（服务器 interface 根因）均在列。

但 StCache 有两簇 RISC-V 上不存在的残差尚未定性：

- `SimplePropertyExpr < SimpleSequenceExpr` 2143（19%），SVA 断言，names=1373；
- `csr_behvr.sv` 等生成式 CSR 文件簇约 2170（19%），特征是同名少量已归属、大量未归属
  （`reg_error 14/199`、`reg_we 14/192`、`wstrb_flattern 7/185`）。

本地已排除三种可能原因：function 体与 SVA 断言**都能被 `root.visit()` 遍历到**
（实测 `reg_error` 源码 4 次 = 1 声明 + 3 引用，AST 引用正好 3 次，含 property 与立即断言）；
宏展开引用的 `sourceRange` 转换**正常**（`macro_start=True` 时 converted 区间正好覆盖调用点实参）。
因此这两簇不是遍历缺口，也不是宏位置问题，需要 StCache 实际源码才能定性。

为避免继续推断，本次新增**残差归因**：每个未归属 token 标注失败原因
（`no_reference_for_this_spelling` / `reference_range_excludes_token` / `ambiguous_owner`），
直方图每项带 `reasons` 计数与 `reason_sample`（含最近同名引用的区间与节点种类）。
RISC-V-Vector 实测该归因有效：`NamedPortConnection` 分解为 231 无引用 + 141 区间不覆盖，
样本显示 token 是 `.clk(` 标签而最近引用是 10 字节后的实参 `clk`；
`NamedType` 残差 100% 为 `no_reference_for_this_spelling`，确认需要独立规则。

服务器需再跑一次以获得这两簇的归因。

## 12. 下一步的判定规则（不属于本任务的验收条件）

服务器数据回传后，按 `token_first_binding.md` §5.5 判读，并据此选择下一张任务：

- 若残差头部一两条产生式占绝大多数且与本地清单重合 → 新建任务，
  按频次实现 `NamedPortConnection` 等类二规则，从覆盖率收益最大的一条开始；
- 若 `join.in_scope.ambiguous` 很大 → 先核查目标身份口径是否退化为对象身份；
- 若出现大量本地未见的产生式 → "封闭尾巴"假设需修正，先扩充探测器分类再谈改造；
- 若 `byte_mismatch != 0` → 本任务回到 `IN_PROGRESS` 修正探测器本身。

产品改造的推荐顺序（待服务器复测确认后另立任务冻结）：

1. 用物理声明位置替换 `rename_index.py` 中一切基于对象身份的目标标识；
2. 实现 `NamedPortConnection` 标签绑定（服务器 ports 根因，覆盖率收益最大）；
3. 用 `header.nameOrKeyword` 修正 modport 限定的 interface port（服务器 interface 根因）；
4. 用 `sourceRange` 末端锚定 + 字节校验修正成员后接 select（服务器 struct 根因）；
5. 在逐符号完整性判据成立后，收缩 `_apply_group_binding_issues` 的全设计爆炸半径。
