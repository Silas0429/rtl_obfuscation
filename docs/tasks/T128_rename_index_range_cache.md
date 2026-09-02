# T128 RenameIndex 低内存范围与路径缓存

- 状态：`ACCEPTED`
- 主 Agent：Codex
- 实现负责人：子 Agent（`gpt-5.6-luna`，`xhigh`）
- 起始 HEAD：`553dffd165896f94d1eaf92fc142dde1a7e8bdcf`
- 起始工作树：clean
- 前置任务：T127 已由主 Agent 验收并以 `553dffd` 推送
- 任务类型：RenameIndex 内部性能优化；决策与持久化结果必须逐项一致
- Formal verification：`REQUIRED`；本任务会改变生成 RenameIndex 时读取物理范围的实现，必须用实际 compact gate 证明正向等价并用固定功能负例证明门禁有效

## 1. 已冻结的问题与证据

T127 永久探针在服务器单模块 `StChTop` 上给出：

```text
总用时                              145.346s
RenameIndex                          90.166s
rename_index.occurrences             57.461s
rename_index.declarations            14.722s
rename_index.name_completeness        9.835s
```

当前 `rtl_obfuscator/rename_index.py` 的声明和 occurrence 物理范围校验会反复调用
`Path.read_bytes()` 读取整个文件，并反复执行 `SourceManager.getFullPath()`、`Path.resolve()` 和
source-root 相对化。同一个物理 identifier 因 elaboration alias 或多次语义访问被校验时，这些工作重复发生；
共享存储会放大耗时，整文件缓存又会放大供应商模型的常驻内存。

本任务只消除这两种重复工作。候选收缩、紧凑事实表、遍历合并、区间索引和最后约 40.8 秒的未细分后处理
均不属于 T128。

## 2. 主 Agent 固定实现计划

本任务从开始到验收只允许以下三步，后续不得追加或替换功能：

1. 冻结当前 RenameIndex 的逐项决策摘要和缓存行为合同；
2. 子 Agent 只实现单次构建作用域内的字节片段缓存与路径缓存，并完成固定自测；
3. 主 Agent 独立复跑同一验收，检查 exact digest、actual gate、Formal 和 Git 边界后决定是否接受。

T128 不实现第二轮结构性 RenameIndex 优化，也不创建下一任务。

## 3. 单一目标

在静态、未被并发修改的同一 SourceSet 输入上，使 `build_rename_index()` 对同一个 PySlang buffer 的物理路径
最多执行一次成功解析，对同一个 `(file, start, end)` 物理片段最多执行一次实际读取；后续访问复用本次构建
的私有缓存。缓存只能改变取得相同物理字节证据的成本，不能改变候选、绑定、范围、顺序、action、reason、
issue、异常、安全判据或任何公共输出。

## 4. 固定实现合同

### 4.1 生命周期与所有权

- 在 `rtl_obfuscator/rename_index.py` 内新增一个最小私有 range/path context；名称由实现选择。
- 每次 `build_rename_index()` 必须新建且只新建一个 context，并传给该次构建的内部范围/路径 helper。
- 禁止模块级缓存、`functools` 全局 cache、环境变量、磁盘 cache、持久化 cache 或跨两次构建复用。
- 不得把 cache 写入 `SourceCatalog`、`RenameIndex`、mapping、report 或 gate。
- 不得使用 `id(buffer)` 或短生命周期 Python wrapper 地址作为语义身份。路径 memo 应沿用当前
  `_buffer_file()` 的可哈希 buffer 键语义；不可哈希时仍直接解析且不得因此降级成功。

### 4.2 路径缓存

- source root 的规范化结果在一次 context 中只计算一次。
- 同一个可哈希 PySlang buffer 的 `getFullPath -> resolve -> relative_to(source_root)` 成功或失败结果只计算一次。
- 宏位置仍先通过当前 `_physical_location()` 还原；缓存不得改变宏来源、越界或异常处理。
- 现有 diagnostic、dead-source 和 name-completeness helper 可以复用同一个路径 memo，但不得改变调用顺序和判据。

### 4.3 低内存字节片段缓存

- point-range 校验只读取 `[start, end)` 所需字节：以二进制打开文件、seek 到 `start`、读取恰好
  `end - start` 字节；不得为一次 identifier 校验调用 `Path.read_bytes()` 读取整个文件。
- cache key 固定为规范化的 `(file, start, end)`；缓存值只能是该片段的原始 bytes，不得保存整个物理文件。
- 同一个 key 在一次构建内最多执行一次实际片段读取；不同 expected spelling 仍各自对同一原始 bytes 做比较，
  不得把“曾经匹配”作为后续判定。
- 负 offset、空/逆序区间、短读、字节不匹配、文件不可读和 SourceSet 外路径必须维持当前 fail-closed 结果与
  `RenameIndexError` code/message/file/start 语义；禁止捕获后跳过或转为成功。
- `_range_for_location()`、`_expression_range()`、`_member_access_range()` 及其 declaration/occurrence 调用链必须
  使用同一个 context。没有传入 context 的现有私有 helper 测试调用可以保持当前调用方式，但不得在正式
  `build_rename_index()` 路径退化为每次新建 cache。

### 4.4 必须保留的整文件读取

`_tokens_spelling()`、`_names_in_dead_source()` 等为了枚举全部物理 identifier 或验证完整分母而进行的现有
逐文件扫描不在本任务中改成片段扫描。它们可以继续保持当前函数内的每文件一次 `file_bytes` 缓存，并复用路径
memo。不得借 T128 排除 token、文件、只读声明、供应商模型或 rewrite-root 外事实。

## 5. 决策完全一致合同

对以下两个现有 compact fixture，按固定投影序列化后 SHA-256 必须与起始 HEAD 完全相同：

```text
tests/fixtures/t108_pyslang_rename_index/design.f, top=top
symbols=42, occurrences=70
digest=0180e2d80e623f5677e3dbce6cf0259e9a486380d8b4ad7142c023350f23bf9f

tests/fixtures/t115_name_completeness/design.f, top=t115_top
symbols=56, occurrences=125
digest=dbbc8fb76135251abcd8f87dca6e78ce3a5df7c19101e1c3907f020d8dd49a78
```

固定投影必须包含且保持顺序：

- selected categories；
- 每个 symbol 的 `symbol_id/category/kind/semantic_kind/name/declaration/owner_module/semantic_owner`；
- 每个 occurrence 的 source range 与 provenance；
- `impact/abi/support/reason`；
- 每个 decision 的 `symbol_id/category/action/reason`；
- 完整 `category_outcomes` 与 issues。

不得只比较 counts、coverage 或最终 gate。随机生成的新名字不进入该投影。

## 6. 目标测试与机器输出

新增 `tests/test_t128_rename_index_range_cache.py`，至少证明：

1. §5 两个 exact digest、symbol 数和 occurrence 数完全一致；
2. 一次真实 `build_rename_index()` 中，同一 hashable buffer 只发生一次底层路径解析；
3. 一次真实构建中，同一 `(file,start,end)` 只发生一次底层片段读取，且存在至少一个 cache hit，证明缓存已接入
   正式 declaration/occurrence 路径而非只测试孤立 helper；
4. cache 只保存请求片段，重复请求返回相同 bytes；新 context 不复用旧 context 的数据；
5. 越界/短读/字节不匹配和不可读输入仍 fail closed，错误 code 与起始实现一致；
6. 测试结束向 stdout 输出一行机器可解析证据，字段名固定：

```text
T128_CACHE_EVIDENCE_JSON={"path_requests":<int>,"path_resolutions":<int>,"range_requests":<int>,"range_reads":<int>,"range_cache_hits":<int>,"t108_digest":"...","t115_digest":"..."}
```

必须满足 `path_requests > path_resolutions > 0`、`range_requests > range_reads > 0`、
`range_cache_hits == range_requests - range_reads`。不冻结开发机秒数，不以 wall time 作为单元测试通过条件。

## 7. 包含与不包含

### 包含

- RenameIndex 私有、单次构建生命周期的路径 memo；
- identifier 精确片段读取与同 range memo；
- 两个现有 fixture 的 exact decision digest；
- cache hit/read 次数的确定性单元证据；
- 一个既有 compact actual gate 的 strict compile、byte-identical restore、Formal 正例和固定功能负例。

### 不包含

- 不改变 CLI 参数、stderr/stdout、SourceSet、SourceCatalog 公共结构或输入模式；
- 不改变 mapping/SourceSet/orchestration/metrics/manifest/restore schema；
- 不提前限制候选声明，不增加 analysis-root，不按 `-v`、目录或供应商来源裁剪分析；
- 不提取紧凑事实表，不合并 semantic/CST 遍历，不新增区间索引；
- 不改变四组定义、rewrite-root、readonly firewall、dead-source、name-completeness、range conflict 或
  fail-closed 判据；
- 不缓存整文件，不并行读取，不增加依赖；
- 不优化 mapping、写出、报告、发布或最后约 40.8 秒的未细分后处理；
- 不运行真实 AIClusterWrapper；性能收益由任务接受后的服务器同输入复测确认，不作为本地正确性门禁。

## 8. 允许修改文件

子 Agent 只能修改：

```text
docs/tasks/T128_rename_index_range_cache.md
rtl_obfuscator/rename_index.py
tests/test_t128_rename_index_range_cache.py
```

需要修改其它产品、测试、fixture、文档、schema 或命令时，先记录偏差并停止，不得扩大范围。

## 9. 固定验收命令

子 Agent 与主 Agent 只运行以下五条，不追加 blanket discovery、RISC Formal 或结构性性能实验：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t128_rename_index_range_cache -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_modport_ports_are_alias_occurrences_of_interface_members \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_macro_typedef_and_conversion_shapes_are_semantically_scoped \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_unknown_cross_record_claim_preserves_the_entire_core_group \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_same_record_declaration_range_keeps_only_the_declaration \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_interface_arrays_are_root_aliases_without_anonymous_element_records \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_actual_compact_gate_strict_compiles_and_restores_direct_bytes \
  tests.test_t115_name_completeness -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/rename_index.py \
  tests/test_t128_rename_index_range_cache.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; \
s=next(l for l in Path("docs/tasks/T128_rename_index_range_cache.md").read_text().splitlines() if l.startswith("- 状态：")); \
assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t128_ready_for_review=pass")'
```

Formal 固定证据由 `tests.test_t115_name_completeness.T115NameCompletenessTests.`
`test_actual_gate_formal_positive_and_fixed_functional_negative` 产生：

```text
gold: tests/fixtures/t115_name_completeness/formal.f
gate: 该测试从本次实际 RenameIndex/mapping 生成的临时 gate
top: t115_formal_top
positive command: scripts/formal_equivalence.py --gold-filelist <formal.f> --gate-filelist <actual gate design.f> --top t115_formal_top --json <positive.json> --quiet
positive required: exit 0 and formal_equivalence=pass
negative: 从同一 actual gate 只反转一个功能表达式
negative required: nonzero, unproven, and equiv_status -assert
```

## 10. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 553dffd165896f94d1eaf92fc142dde1a7e8bdcf
start_time: 2026-09-02T11:11:57+08:00
first_command: git status --short --branch && git rev-parse HEAD && conda run -n rtl_obfuscation python -m unittest tests.test_t128_rename_index_range_cache -v
allowed_files: docs/tasks/T128_rename_index_range_cache.md; rtl_obfuscator/rename_index.py; tests/test_t128_rename_index_range_cache.py
changed_files:
  - docs/tasks/T128_rename_index_range_cache.md
  - rtl_obfuscator/rename_index.py
  - tests/test_t128_rename_index_range_cache.py
commands:
  - `conda run -n rtl_obfuscation python -m unittest tests.test_t128_rename_index_range_cache -v`
  - `conda run -n rtl_obfuscation python -m unittest tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_modport_ports_are_alias_occurrences_of_interface_members tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_macro_typedef_and_conversion_shapes_are_semantically_scoped tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_unknown_cross_record_claim_preserves_the_entire_core_group tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_same_record_declaration_range_keeps_only_the_declaration tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_interface_arrays_are_root_aliases_without_anonymous_element_records tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_actual_compact_gate_strict_compiles_and_restores_direct_bytes tests.test_t115_name_completeness -v`
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rename_index.py tests/test_t128_rename_index_range_cache.py`
  - `git diff --check HEAD`
  - `conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T128_rename_index_range_cache.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t128_ready_for_review=pass")'`
results:
  - `tests.test_t128_rename_index_range_cache`: 5 tests passed; `T128_CACHE_EVIDENCE_JSON={"path_requests":586,"path_resolutions":3,"range_requests":252,"range_reads":122,"range_cache_hits":130,"t108_digest":"0180e2d80e623f5677e3dbce6cf0259e9a486380d8b4ad7142c023350f23bf9f","t115_digest":"dbbc8fb76135251abcd8f87dca6e78ce3a5df7c19101e1c3907f020d8dd49a78"}`
  - Fixed T108/T115 row: 17 tests passed; actual-gate Formal positive `exit=0`, JSON `formal_equivalence=pass`, top `t115_formal_top`; fixed functional negative `exit=1`, evidence `unproven; equiv_status -assert`.
  - `py_compile`: exit 0.
  - `git diff --check HEAD`: exit 0.
  - READY guard: `t128_ready_for_review=pass`.
schema_or_behavior:
  - 每次 `build_rename_index()` 新建一个私有 `_RangePathContext`；同一可哈希 buffer 的路径成功/失败结果只解析一次；同一规范化 `(file,start,end)` 只读取一次并复用原始 bytes。
  - declaration、occurrence、dead-source、name-completeness 的判据和公共结果由 exact digest 与兼容行验证保持不变。
boundaries:
  - 保留 `_tokens_spelling()`、`_names_in_dead_source()` 的现有逐文件读取；未修改 CLI、schema、SourceSet、mapping、安全判据、候选集合或遍历结构。
cleanup_candidates:
  - 无。未创建仓库内临时文件，未删除既有文件。
formal_verification:
  - PASS；由固定 T115 actual gate 产生：gold `tests/fixtures/t115_name_completeness/formal.f`，gate 为本次测试从实际 RenameIndex/mapping 生成的临时 gate，top `t115_formal_top`；正例 exit 0 且 `formal_equivalence=pass`，固定单表达式负例 exit 1 且包含 `unproven; equiv_status -assert`。
review_request:
  - 子 Agent 自测完成，三条允许路径已记录，申请主 Agent 独立按第 9 节五条命令复核；未提交、未推送、未设置 `ACCEPTED`。
```

主 Agent 冻结合同时的 baseline：

```text
conda run -n rtl_obfuscation python -m unittest tests.test_t128_rename_index_range_cache -v
exit 1; ModuleNotFoundError: tests.test_t128_rename_index_range_cache（目标测试尚不存在，符合实现前基线）
```

## 11. 主 Agent 验收

```text
main_result: PASS；冻结的三步计划和三个允许路径内一次完成，无范围扩张
scope_review: PASS；只修改 T128 任务单、rtl_obfuscator/rename_index.py 和目标测试；无 CLI、SourceSet、SourceCatalog 公共结构、mapping/schema、候选、遍历、区间索引或安全判据改动
code_review: PASS；每次 build_rename_index 只创建一个私有 context；路径使用可哈希 buffer memo 且不使用 id()；range cache 只保存规范化 (file,start,end) 的精确 bytes；_tokens_spelling 与 dead-source 仍按原规则逐文件验证完整分母；无全局、跨构建、整文件或持久化缓存
decision_digest: PASS；T108 42 symbols/70 occurrences，SHA-256 0180e2d80e623f5677e3dbce6cf0259e9a486380d8b4ad7142c023350f23bf9f；T115 56 symbols/125 occurrences，SHA-256 dbbc8fb76135251abcd8f87dca6e78ce3a5df7c19101e1c3907f020d8dd49a78；逐项投影与起始 HEAD 完全一致
cache_evidence: PASS；path_requests=586，path_resolutions=3；range_requests=252，range_reads=122，range_cache_hits=130；同 buffer 和同 range 的底层工作各至多一次，cache hit 已接入真实 build 路径
target_result: PASS；tests.test_t128_rename_index_range_cache，Ran 5 tests，exit 0
compatibility_result: PASS；固定 T108/T115 行 Ran 17 tests，exit 0；actual compact gate strict compile、range audit、public CLI 和 byte-identical restore 均通过
py_compile: PASS；精确第 9 节命令 exit 0
git_diff_check: PASS；git diff --check HEAD exit 0
ready_for_review_guard: PASS；接受前输出 t128_ready_for_review=pass
formal_verification: PASS；T115 actual gate 正例 exit 0，JSON formal_equivalence=pass，top=t115_formal_top；同 gate 固定 1'b0 -> 1'b1 功能负例 exit 1，evidence=unproven; equiv_status -assert
accepted_by: Main Agent Codex，2026-09-02 Asia/Shanghai
```

## 12. 验收后的唯一下一步

T128 接受并推送后，只在服务器使用与本次 `StChTop` 完全相同的命令重新记录七个 RenameIndex 子阶段。
该复测用于判断是否需要后续结构性 RenameIndex 任务；T128 本身不预先授权候选收缩、紧凑事实、遍历合并或
区间索引。
