# T046：mapping vNext 单次改写、strict gate 与解密闭环

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 所属重构阶段：R3-C
- 前置任务：T045 ACCEPTED，交付提交 27902a1
- 设计依据：docs/three_mode_refactor_plan.md 第 1–7 节
- 执行规范：docs/refactor_subagent_protocol.md
- Formal 依据：docs/formal_verification.md
- 验收类型：rewrite/mapping；产生 rewritten RTL
- Formal verification：必须执行 compact multi-file 正例和固定功能负例

## 1. 当前项目位置与拆分决策

~~~text
SourceSet -> SourceCatalog -> SymbolGraph -> RewritePolicy -> MappingVNext
                                                               |
                                                               +-> T046 one-pass gate
                                                               +-> strict compile
                                                               +-> gate-range audit
                                                               +-> restore byte identity
                                                               +-> compact Formal +/-
~~~

T045 已冻结 planned mapping、名称、source ranges 和 input manifest。T046 是新架构第一次生成
rewritten RTL，只实现 MappingVNext 到 gate 和 restored files 的执行闭环。

本任务不实现 CLI、per-file mapping、metrics、rate selection 或 project-root adapter。执行层只能
消费 MappingVNext.records，禁止重新收集 symbol、reference、owner 或 category。

## 2. 单一目标

新增 rtl_obfuscator/rewrite_vnext.py，并在 rtl_obfuscator/systemverilog_names.py 增加安全随机
NameFactory：

1. 验证 MappingVNext 与当前 input manifest 仍一致；
2. 将全部 rename record 的 declaration 和 occurrences 按文件一次性倒序改写；
3. 计算并审计每个 token 的 source range 与 gate range；
4. 原子写出所有 SourceSet physical files 和 canonical design.f；
5. 使用同一 SourceSet compile context 严格建立 gate SourceCatalog；
6. 记录 gate manifest、compile evidence 和 edit evidence；
7. 只依赖 execution + gate bytes 逆向恢复全部 physical files；
8. restored manifest 必须等于 mapping input manifest；
9. actual renamed gate 必须通过 compact Yosys Formal，固定功能变更必须失败。

## 3. 固定输入

不新增或修改 RTL/formal fixture。只读复用 T043/T045 已提交输入：

~~~text
tests/fixtures/refactor_symbol_graph_parameters/design.f
tests/fixtures/refactor_symbol_graph_parameters/closure.f
tests/fixtures/refactor_symbol_graph_parameters/single.f
tests/fixtures/refactor_symbol_graph_parameters/single.sv
tests/fixtures/refactor_symbol_graph_parameters/positional.f
tests/fixtures/refactor_symbol_graph_parameters/rtl/*.sv
tests/fixtures/refactor_symbol_graph_parameters_invalid/**
~~~

18 个文件的 bytes 与 SHA-256 继续以 docs/tasks/T043_symbol_graph_parameters.md 第 3.3 节为准。
T046 不得修改 fixture，不新增 gate/non-equivalent fixture；全部输出和负例只在 TemporaryDirectory
中生成。

## 4. 主 Agent预检事实

固定主正例：

~~~text
input: design.f
top: parameter_top
categories: signals, parameters, genvars
abi_categories: parameters
name_length: 16
name_factory: T045 基于 symbol_id SHA-256 的显式确定性 factory
mapping records: 20
rename records: 16
preserve records: 4
modified tokens: 41
physical files: 4
source ranges: 53
renamed ranges: 41
preserved ranges: 12
~~~

四个 physical files 都包含至少一个 rename edit。主 Agent只读预检已经确认：

1. actual renamed gate 的 catalog/top-overlay parse/semantic errors 均为 0/0；
2. scripts/formal_equivalence.py 对 actual renamed gate、top=parameter_top、seq=5 返回
   formal_equivalence=pass；
3. 在 gate/rtl/child.sv 的精确字节序列 assign data_o = 后插入一个 ASCII ~，负例仍 strict
   compile 0/0；
4. 同一 Formal 对该负例退出非 0，并在 equiv_status -assert 报告 4 个 unproven equiv cells；
5. single mapping 为 3 records、2 rename records、3 modified tokens。

上述 exact count 只用于 compact fixture 测试，不得进入产品分支。

## 5. 固定公开 API

### 5.1 安全随机 NameFactory

在 rtl_obfuscator/systemverilog_names.py 增加：

~~~python
def secure_name_factory(
    symbol_id: str,
    name_length: int,
    unavailable: frozenset[str],
) -> str: ...
~~~

要求：

- 签名与 T045 NameFactory 完全一致；
- 使用 secrets 模块，首字符从 ASCII letters 选择，其余从 ASCII letters、digits、underscore 选择；
- 只返回 is_plain_identifier=true、长度精确且不在 unavailable 中的名称；
- 最多尝试 1000 次，耗尽后抛 RuntimeError；
- 不修改 unavailable，不读取 symbol/category/fixture，不引入 seed 或全局可预测状态；
- build_mapping_vnext 仍要求显式 name_factory，不增加默认参数。

### 5.2 rewrite execution

新增 rtl_obfuscator/rewrite_vnext.py：

~~~python
@dataclass(frozen=True)
class AppliedEdit:
    symbol_id: str
    provenance: str
    original_name: str
    renamed_name: str
    source_range: SourceRange
    gate_range: SourceRange

@dataclass(frozen=True)
class CompileEvidence:
    catalog_parse_errors: int
    catalog_semantic_errors: int
    top_overlay_parse_errors: int | None
    top_overlay_semantic_errors: int | None

@dataclass(frozen=True)
class RewriteExecution:
    schema_version: int
    mapping_vnext: MappingVNext = field(repr=False, compare=False)
    filelist: str
    gate_manifest: tuple[InputFileDigest, ...]
    edits: tuple[AppliedEdit, ...]
    compile_evidence: CompileEvidence

    def to_report(self) -> dict[str, object]: ...

@dataclass(frozen=True)
class RestoreResult:
    schema_version: int
    rewrite_execution: RewriteExecution = field(repr=False, compare=False)
    restored_manifest: tuple[InputFileDigest, ...]

    def to_report(self) -> dict[str, object]: ...

class RewriteVNextError(ValueError):
    code: str
    message: str

def write_gate_vnext(
    mapping_vnext: MappingVNext,
    *,
    output_dir: Path,
) -> RewriteExecution: ...

def restore_gate_vnext(
    rewrite_execution: RewriteExecution,
    *,
    gate_dir: Path,
    output_dir: Path,
) -> RestoreResult: ...
~~~

不要求从 rtl_obfuscator/__init__.py 重导出。不得修改 T039–T045 dataclass、MappingVNext core schema
或 scripts/formal_equivalence.py。

## 6. MappingVNext 执行前验证

write_gate_vnext 不接受任意 duck-typed dict。必须 fail-closed 验证：

1. mapping 是 MappingVNext，format=rtl-obfuscation.mapping-vnext，schema_version=1；
2. name_length 为非 bool int 且不小于 4；
3. mapping policy/graph/catalog/SourceSet schema 都为 1；
4. records、policy decisions、graph symbols 数量和顺序一对一；
5. 每个 record 的 symbol_id、category、action、reason、original_name、owner、ranges、impact、abi
   与对应 graph symbol/policy decision 完全一致；
6. rename record 的 renamed_name 必须是合法非关键字、精确长度、全局唯一、不同于任何 input
   lexical identifier；preserve/unsupported 的 renamed_name 必须为 null；
7. input_manifest 文件顺序必须等于 physical files，SHA-256 必须等于当前 source bytes；
8. source ranges 必须仍匹配 original_name，且全局无 duplicate/overlap；
9. compile_order 必须只引用 ordered_source_files 中的 .sv，顺序不变；
10. 任一 dataclasses.replace 篡改不产生部分输出。

允许为执行边界做结构、manifest 和 bytes 复核；禁止 AST/CST/semantic traversal 再次收集 mapping
candidate 或 occurrence，禁止调用 MappingVNext 私有 helper、legacy validator 或 inventory。

## 7. 一次性 edit 与 gate range

### 7.1 edit 集合

- 只为 action=rename 建 edit；
- 每个 record 按 declaration 后接 occurrences canonical 顺序；
- declaration provenance 固定为 declaration；occurrence 沿用 SymbolOccurrence.provenance；
- preserve/unsupported 不建 edit；
- compact 主正例必须得到 41 edits。

### 7.2 gate range 计算

对每个文件把 source edits 按 start/end 升序计算累计 byte delta：

~~~text
gate_start = source_start + 所有更早 edit 的 byte delta 之和
gate_end = gate_start + len(renamed_name.encode("utf-8"))
~~~

同一 source range 不存在重叠，因此“更早”固定为 edit.start < current.start。AppliedEdit 的公开顺序
仍按 MappingVNext.records，且每个 record declaration-first，不按文件重新排序。

### 7.3 单次应用与审计

- 每个 physical file 只读取一次 source bytes；
- 对该文件全部 edits 按 source start 倒序应用；
- 禁止逐 category 或逐 record 重写已经生成的 gate；
- 应用前 source bytes 必须匹配 original_name；
- 应用后每个 gate_range 必须精确匹配 renamed_name；
- 未被 edit 覆盖的 bytes 必须保持原样；
- 原 source files 不得变化。

## 8. 输出目录与 strict gate

### 8.1 原子输出

- output_dir 必须不存在，父目录必须存在；
- output_dir 不得等于或位于 source_root 内；
- 先在同父目录 staging directory 写入并验证，全部成功后一次 rename 为 output_dir；
- 任一失败必须清理 staging，不能留下 output_dir 或部分 gate；
- 不覆盖、删除、移动用户已有路径。

### 8.2 gate 内容

- 原相对路径写出 ordered_source_files 和 included_files 的全部 physical bytes；
- 未发生 edit 的 physical file 仍逐字节复制；
- 额外写出 canonical design.f，每行一个 compile_order .sv 文件，保留顺序，末尾换行；
- design.f 不进入 physical gate manifest；
- gate_manifest 按 input_manifest 同序记录改写后 physical file SHA-256。

### 8.3 strict compile

在 staging gate 上以原 SourceSet 为模板，只替换 source_root，并保持 ordered files、included files、
include_dirs、defines、top、top_closure_files 和 compile_order；然后调用公开
build_source_catalog，不能使用 legacy inspect/encrypt。

必须满足：

- catalog parse/semantic errors 为 0/0；
- 有 top 时 top-overlay parse/semantic errors 为 0/0；
- 无 top 时 top-overlay evidence 四个字段为 null；
- strict compile 失败不得发布 output_dir；
- 不在 gate 上重建 SymbolGraph 或 mapping。

## 9. restore 闭环

restore_gate_vnext 只能读取 RewriteExecution、gate_dir 和 gate physical files，不得读取 gold
source_root 或重新编译。

固定流程：

1. 验证 execution schema、mapping identity、edit schema 和 gate ranges；
2. gate_dir 必须存在，canonical design.f 必须匹配 execution compile_order；
3. 当前 gate manifest 必须等于 execution.gate_manifest；
4. 每个 gate_range bytes 必须等于 renamed_name；
5. 每文件按 gate_start 倒序把 renamed_name 替换为 original_name；
6. 原子写入不存在的 output_dir；
7. restored manifest 必须逐项等于 mapping.input_manifest；
8. 不需要 source_root 即可完成恢复。

restore 任一失败不能留下 output_dir。不得通过复制 gold 或调用 legacy decrypt 实现。

## 10. report schema

### 10.1 RewriteExecution

to_report 顶层 key 顺序固定：

~~~text
format = rtl-obfuscation.rewrite-execution
schema_version = 1
state = gate-verified
mapping = MappingVNext.to_report()
filelist = design.f
gate_manifest
edits
compile
summary
~~~

每个 edit：

~~~text
symbol_id
provenance
original_name
renamed_name
source_range: file/start/end
gate_range: file/start/end
~~~

compile key 固定对应 CompileEvidence 四字段。summary 固定：

~~~text
files
mapping_records
renamed_records
modified_tokens
~~~

### 10.2 RestoreResult

to_report 顶层 key 顺序固定：

~~~text
format = rtl-obfuscation.restore-result
schema_version = 1
state = restored
restored_manifest
summary:
  files
  modified_tokens
  byte_identical = true
~~~

不得记录 output_dir、source_root 或临时绝对路径。确定性 mapping 下连续 JSON 必须 byte-identical。

## 11. 稳定错误码与优先级

异常字符串固定以 '<code>: ' 开头。

write_gate_vnext 验证顺序：

1. output path；
2. mapping/schema/record；
3. source/input manifest；
4. source edit/range；
5. staging write 与 gate-range audit；
6. strict compile；
7. atomic publish。

restore_gate_vnext 验证顺序：

1. output path；
2. execution/schema/edit；
3. gate path/filelist/manifest；
4. gate range bytes；
5. reverse edits；
6. restored manifest；
7. atomic publish。

| condition | code |
| --- | --- |
| output 已存在、重叠 source/gate 或父目录非法 | REWRITE_OUTPUT_INVALID / RESTORE_OUTPUT_INVALID |
| mapping schema、record 或 renamed_name 非法 | REWRITE_MAPPING_INVALID |
| source 文件或 input manifest 已变化 | REWRITE_SOURCE_CHANGED |
| source edit/range/overlap 非法 | REWRITE_EDIT_INVALID |
| gate 写入或 range bytes 审计失败 | REWRITE_GATE_AUDIT_FAILED |
| strict gate SourceCatalog 失败 | REWRITE_GATE_COMPILE_FAILED |
| execution schema/edit 非法 | RESTORE_EXECUTION_INVALID |
| gate 文件、design.f 或 manifest 不匹配 | RESTORE_GATE_INVALID |
| gate range 不匹配 renamed_name | RESTORE_RANGE_INVALID |
| restored manifest 不等于 input manifest | RESTORE_BYTES_MISMATCH |
| 其他受控文件系统错误 | REWRITE_IO_ERROR / RESTORE_IO_ERROR |

不捕获后降级成功，不返回部分 execution/result。

## 12. 冻结正例与 Formal

### 12.1 compact filelist 主正例

使用第 4 节 deterministic mapping：

~~~text
RewriteExecution summary = files 4 / mapping_records 20 / renamed_records 16 / modified_tokens 41
edits = 41
gate manifest files = rtl/child.sv, rtl/shadow.sv, rtl/top.sv, rtl/unreachable.sv
compile = catalog 0/0, top-overlay 0/0
all 4 gate physical files differ from gold
restore = files 4 / modified_tokens 41 / byte_identical true
~~~

全部 restored physical files 必须与 gold bytes 完全一致。

### 12.2 single 子集

single-file 与 single filelist 使用各自 T045 mapping 后：

- 都得到 files=1、mapping_records=3、renamed_records=2、modified_tokens=3；
- gate/single.sv bytes 完全一致；
- 去除 mapping 对象 identity 后 execution report 完全一致；
- 两者 restore 均 byte-identical；
- 使用同一 write/restore API，不允许单文件分支。

### 12.3 no-top filelist

full/no-top 只改写 internal records；module ABI records 保持原名。gate strict compile 通过且 restore
byte-identical。不得因为无 top 跳过全部 module 或改写 ABI。

### 12.4 Formal 正例

目标测试必须对 actual 41-edit gate 运行：

~~~sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist tests/fixtures/refactor_symbol_graph_parameters/design.f \
  --gold-root tests/fixtures/refactor_symbol_graph_parameters \
  --gate-filelist <temporary-gate>/design.f \
  --gate-root <temporary-gate> \
  --top parameter_top \
  --seq 5
~~~

要求 exit 0，JSON 至少精确包含：

~~~json
{"formal_equivalence":"pass","seq":5,"top":"parameter_top"}
~~~

必须先证明 gate 至少一个 physical file 与 gold 不同、16 rename records 和 41 edits 均已应用，禁止
identity comparison、复制 gold 或 formal-align 恢复名称后再证明。

目标测试已经由 conda 环境中的 unittest 启动，内部 subprocess 应使用 sys.executable 调用
scripts/formal_equivalence.py；不得在测试内部嵌套 conda run。上面的命令表示必须记录的等价
用户命令和参数。

### 12.5 固定功能负例

从 actual verified gate 复制 negative gate，仅在 rtl/child.sv 的唯一字节序列
assign data_o = 后插入一个 ASCII ~：

- 必须精确增加 1 byte，其他 bytes 不变；
- negative gate strict SourceCatalog 仍为 0/0；
- 使用与正例相同 gold、filelist、top、seq；
- Formal 必须退出非 0；
- stdout/stderr 必须包含 unproven 和 equiv_status -assert；
- 不要求固定 Yosys 内部 cell 数，主 Agent预检的 4 cells 只作诊断事实。

## 13. 稳定负例矩阵

必须通过公开 dataclasses.replace 或 TemporaryDirectory 覆盖：

| case | expected |
| --- | --- |
| output_dir 已存在或位于 source_root 内 | REWRITE_OUTPUT_INVALID |
| mapping format/schema/name length/record count/order/identity 被改 | REWRITE_MAPPING_INVALID |
| renamed_name 非法、重复、等于 input identifier | REWRITE_MAPPING_INVALID |
| source byte 或 input manifest 在 mapping 后改变 | REWRITE_SOURCE_CHANGED |
| source range duplicate/overlap/bytes mismatch | REWRITE_EDIT_INVALID |
| gate strict compile 失败 | REWRITE_GATE_COMPILE_FAILED，且无发布目录 |
| restore output 已存在或与 gate 重叠 | RESTORE_OUTPUT_INVALID |
| execution schema/edit/gate range 被改 | RESTORE_EXECUTION_INVALID |
| gate physical byte、design.f 或 manifest 被改 | RESTORE_GATE_INVALID |
| execution manifest 同时被伪造但 gate token 不匹配 | RESTORE_RANGE_INVALID |
| reverse 后 hash 不等于 input manifest | RESTORE_BYTES_MISMATCH |

负例不修改冻结 fixture，不调用私有 helper，不留下部分输出。

## 14. 目标测试（恰好 12 项）

新增 tests/test_rewrite_vnext.py，只通过第 5 节公开 API 覆盖：

1. secure_name_factory 合法性、unavailable collision 重试、1000 次耗尽和输入集合不变；
2. full/top 主正例原子写出、4/20/16/41 summary、gate manifest 和全部 physical files；
3. 41 个 edits 的 canonical 顺序、provenance、delta gate ranges、一次性应用和 source 不变；
4. gate 使用同一 compile context strict 0/0；阻断 SymbolGraph rebuild 和 legacy inventory/rewrite；
5. restore 不读取 gold，4 files/41 tokens byte-identical，restored manifest 精确匹配；
6. single-file 与 single filelist gate bytes、normalized execution 和 restore 完全等价；
7. full/no-top 只改 internal、保留 module ABI，并完成 strict gate/decrypt；
8. malformed mapping、source/input manifest/range 负例按第 13 节 fail-closed 且无输出；
9. output path、受控 I/O 和 strict compile failure 原子失败，不留下部分目录；
10. malformed execution、gate/design.f/manifest/range/restored-hash 负例 fail-closed；
11. actual 41-edit gate 执行第 12.4 节 Formal 正例并验证 exit 0/JSON；
12. 精确 1-byte ~ 功能负例 strict compile 0/0，Formal 非 0 且输出包含固定失败证据。

T045 14 tests 与 T046 12 tests 在同一命令运行，共 26 tests。Formal 正负例只在第 11/12 项各
运行一次；不得运行 RISC、blanket discovery 或历史 acceptance。

## 15. 允许修改的文件

- rtl_obfuscator/systemverilog_names.py，仅增加 secure_name_factory 及必要常量；
- rtl_obfuscator/rewrite_vnext.py；
- tests/test_rewrite_vnext.py；
- docs/tasks/T046_rewrite_vnext_roundtrip.md，仅状态和执行记录。

以下全部只读：

- rtl_obfuscator/mapping_vnext.py、rewrite_policy.py、symbol_graph.py、source_catalog.py、source_set.py；
- rtl_obfuscator/inventory.py、rewrite.py、project.py、category_profile.py；
- scripts/formal_equivalence.py；
- 全部 fixture、README、计划和历史任务。

需要修改允许列表外文件时记录原因并停止。

## 16. 明确不包含

- 不增加 CLI command 或参数 adapter；
- 不实现 per-file mapping 或最终 mapping JSON envelope；
- 不实现 effective-line、coverage、plaintext leakage、rate selection 或 metrics；
- 不接入 project-root 产品入口，不按 SourceSet.origin 分支；
- 不新增 category 或 ABI 能力；
- 不修改 MappingVNext core schema；
- 不调用 legacy inventory/rewrite/decrypt/formal-align；
- 不删除旧路径或旧测试；
- 不运行 RISC-V-Vector Formal；
- 不修改或放宽 scripts/formal_equivalence.py；
- 不把 gold 复制为 gate，不在 Formal 前恢复名称。

## 17. 子 Agent强制执行规范

1. 完整阅读 AGENTS.md、本任务、docs/refactor_subagent_protocol.md、重构计划第 1–7 节和
   docs/formal_verification.md；
2. 确认 27902a1 是 HEAD 祖先、T045 为 ACCEPTED、T046 是唯一 READY 任务；
3. 校验 18/18 fixture hash，复核第 4 节 mapping/modified-token 数量；不重复主 Agent 的 identity
   preflight，最终证据只能来自 actual renamed gate；
4. 编辑前设置 IN_PROGRESS，记录 starting HEAD、工作区、baseline 和允许文件；
5. baseline 只运行第 18 节 unittest，预期 T045 14 tests 通过，随后仅因 T046 模块不存在失败；
6. 一次建立第 14 节全部 12 项测试，再实现 secure factory、mapping validation、one-pass edits、
   atomic gate、strict compile、execution report 和 restore；
7. 普通实现、strict compile、decrypt 或 compact Formal 失败属于任务内问题，不得分批暂停要求
   主 Agent补充设计；
8. 只有冻结 fixture/API 事实冲突、actual renamed gate 无法 Formal、需要允许文件外修改或必须
   删除真实 reference 才能编译时才停止；
9. 目标测试通过后只运行第 18 节四条命令，一次填写完整执行记录并设 READY_FOR_REVIEW；
10. Formal 记录必须包含 exact gold/gate/filelist/top/seq、正负命令、exit code、正例 JSON 和
    负例失败证据；
11. 不得设置 ACCEPTED，不得 git add/commit/push，不得创建 T047 或写主 Agent验收记录。

禁止用 legacy helper 快速通过；禁止在测试中弱化 equiv_status -assert 或接受 identity gate。

## 18. 唯一验收命令

~~~sh
conda run -n rtl_obfuscation python -m unittest tests.test_mapping_vnext tests.test_rewrite_vnext -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/systemverilog_names.py rtl_obfuscator/rewrite_vnext.py tests/test_rewrite_vnext.py
git diff --check HEAD
rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T046_rewrite_vnext_roundtrip.md
~~~

第一个 unittest 命令内部必须真实运行第 12.4/12.5 节 Yosys 正负例。其他命令不再重复 Formal。
主 Agent独立复跑同一四条命令，不增加 legacy、RISC 或隐藏 probe。

## 19. 子 Agent执行记录

~~~text
status: READY_FOR_REVIEW
starting_head: 8c366e742e9d87d61372da2f63d32134e711e689; required start HEAD 8c366e7; baseline 8c366e7
start_time: 2026-07-23T14:12:55+0800
first_command: `git status --short --branch`
inherited_worktree: clean (`## main...origin/main [ahead 8]`); no existing user modifications; allowed files are not overlapped
active_task_checks: PASS; 27902a1 is a HEAD ancestor; T045 top status is ACCEPTED; T046 is the only current READY task
allowed_files: rtl_obfuscator/systemverilog_names.py (secure factory only); rtl_obfuscator/rewrite_vnext.py; tests/test_rewrite_vnext.py; docs/tasks/T046_rewrite_vnext_roundtrip.md (status and execution record only)
fixture_hash_check: PASS; 18/18 T043 frozen fixture SHA-256 values match docs/tasks/T043_symbol_graph_parameters.md section 3.3; no fixture changed
preflight_mapping_counts: PASS; T045 accepted evidence confirms full/top mapping 20 records / 16 renames / 4 preserves / 53 ranges; T046 frozen main oracle is 4 physical files / 41 modified tokens / 41 renamed ranges / 12 preserved ranges; single oracle is 3 records / 2 renames / 3 modified tokens
baseline_command: `conda run -n rtl_obfuscation python -m unittest tests.test_mapping_vnext tests.test_rewrite_vnext -v`
baseline_result: expected pre-implementation result; T045 14 tests passed, T046 module import failed, exit_code=1 (`ModuleNotFoundError: No module named 'tests.test_rewrite_vnext'`)
changed_files: rtl_obfuscator/systemverilog_names.py; rtl_obfuscator/rewrite_vnext.py; tests/test_rewrite_vnext.py; docs/tasks/T046_rewrite_vnext_roundtrip.md
commands: `conda run -n rtl_obfuscation python -m unittest tests.test_mapping_vnext tests.test_rewrite_vnext -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/systemverilog_names.py rtl_obfuscator/rewrite_vnext.py tests/test_rewrite_vnext.py`; `git diff --check HEAD`; `rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T046_rewrite_vnext_roundtrip.md`
results: target unittest PASS, Ran 26 tests in 0.632s, OK, exit_code=0; py_compile PASS, exit_code=0; diff check PASS, exit_code=0; status guard PASS, matched `- 状态：`READY_FOR_REVIEW`` and exit_code=0
rewrite_summary: PASS; full/top execution report summary files=4, mapping_records=20, renamed_records=16, modified_tokens=41; edits=41; gate manifest has rtl/child.sv, rtl/shadow.sv, rtl/top.sv, rtl/unreachable.sv; all four gate physical files differ from gold; canonical design.f preserves compile_order
strict_compile: PASS; actual renamed gate catalog parse/semantic=0/0 and top-overlay parse/semantic=0/0; no-top gate catalog=0/0 and top-overlay fields=null; exact one-byte `~` negative gate catalog/top-overlay=0/0; no SymbolGraph rebuild or legacy path
restore_summary: PASS; full/top restore files=4, modified_tokens=41, restored_manifest exactly equals MappingVNext.input_manifest, all physical files byte-identical; single filelist and single-file use the same engine, gate bytes and normalized execution reports match; no-top restore byte-identical
formal_positive: PASS; actual renamed gate only (before restore), gold_filelist=`tests/fixtures/refactor_symbol_graph_parameters/design.f`, gold_root=`tests/fixtures/refactor_symbol_graph_parameters`, gate_filelist=`<TemporaryDirectory>/gate/design.f`, gate_root=`<TemporaryDirectory>/gate`, top=`parameter_top`, seq=5; command uses `sys.executable scripts/formal_equivalence.py`; exit_code=0; JSON contains `{"formal_equivalence":"pass","seq":5,"top":"parameter_top"}` (script also emits gold/gate paths)
formal_negative: PASS expected failure; negative gate copied from actual verified gate and only `rtl/child.sv` has one ASCII `~` inserted immediately after the unique `assign data_o = ` sequence (exactly +1 byte, all other bytes unchanged); same gold/filelist/top/seq; strict compile=0/0; Formal exit_code nonzero; combined output contains `unproven` and `equiv_status -assert`
schema_or_behavior: secure_name_factory uses secrets with 1000-attempt collision bound and immutable input set; rewrite execution validates MappingVNext/manifest/ranges/names, applies declaration-first edits once per file in reverse source order, records delta gate ranges, atomically publishes design.f and physical files, strict-compiles the same SourceSet context, and restores only from execution plus gate bytes; reports are canonical and omit source_root/output_dir
deviations_or_blockers: none; ordinary implementation/test/Formal failures were fixed within T046; no contract/API/schema/fixture expansion
boundaries: no legacy collector/rewrite/decrypt/formal-align, CLI, metrics, per-file mapping, project-root branch, fixture edit, MappingVNext core edit, gold copy, identity proof, or Formal script edit
formal_verification: PASS; compact actual renamed gate positive and exact one-byte functional negative both executed inside the target unittest command
review_request: READY_FOR_REVIEW; all T046 contract evidence is recorded; please independently rerun only the four section 18 commands
~~~

## 20. READY_FOR_REVIEW 条件

- 第 14 节恰好 12 项行为全部覆盖，T045+T046 共 26 tests 通过；
- 第 18 节四条命令全部退出 0；
- diff 只包含第 15 节四个允许文件，18 个 fixture hash 不变；
- full/top 为 4 files、20 records、16 renames、41 edits，strict compile 0/0；
- gate ranges/manifest 审计通过，source bytes 未改变；
- restore 不读 gold，全部 physical files byte-identical；
- single-file/filelist 使用同一 engine，无 top ABI 边界正确；
- actual renamed gate Formal 正例 exit 0/JSON pass；
- 精确 1-byte 功能负例 strict compile 通过而 Formal 按预期失败；
- 无 legacy、CLI、metrics、project-root 分支或 identity proof；
- 状态严格为 READY_FOR_REVIEW。

## 21. 主 Agent验收边界

主 Agent只执行：

1. 审查 starting HEAD、允许文件、fixture hash、mapping/edit counts；
2. 审查 12 项测试使用公开 API、真实 T045 mapping 和 TemporaryDirectory；
3. 审查 mapping revalidation、one-pass edits、gate ranges、atomic output 和 restore 不读 gold；
4. 确认 strict compile 使用同一 SourceSet context，不重建 SymbolGraph；
5. 确认 Formal 使用 actual renamed gate，正例 JSON pass，固定负例非 0；
6. 在 READY_FOR_REVIEW 时独立运行第 18 节四条命令；
7. 全部通过后写验收记录并设置 ACCEPTED。

退回必须引用本合同具体条款或测试项；不得追加 CLI、metrics、per-file mapping、project-root、RISC
或 legacy compatibility 要求。

## 22. 主 Agent合同冻结记录（2026-07-23）

~~~text
status: READY
baseline_commit: 27902a1
decision: first rewritten RTL task is one-pass MappingVNext execution plus strict gate, restore, and compact Formal
fixture: committed T043 parameter graph fixture; no new RTL/formal fixture
main_oracle: 4 files / 20 records / 16 renames / 41 edits / strict 0/0 / restore byte-identical
formal_positive: actual renamed gate, parameter_top, seq 5, exit 0 JSON pass
formal_negative: insert one ASCII ~ after unique "assign data_o = "; strict 0/0; Formal nonzero
negative_matrix: output, mapping, source manifest, ranges, compile, execution, gate manifest, gate token, restored hash
acceptance: exactly four commands; 26 tests; Formal runs only inside tests 11 and 12
forbidden: identity proof, gold copy, legacy helper, RISC, CLI, metrics, origin branch
~~~

## 23. 主 Agent最终验收记录（2026-07-23）

~~~text
status: ACCEPTED
reviewed_head: 8c366e742e9d87d61372da2f63d32134e711e689; required start HEAD 8c366e7
prerequisites: PASS; 27902a1 is a HEAD ancestor, T045 is ACCEPTED, and T046 was the only active READY task
scope: PASS; only the four contract-allowed paths are changed; no fixture, MappingVNext core, or Formal script change
fixture_hash: PASS; 18/18 frozen T043 fixture SHA-256 values match
acceptance_commands:
  - `conda run -n rtl_obfuscation python -m unittest tests.test_mapping_vnext tests.test_rewrite_vnext -v`
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/systemverilog_names.py rtl_obfuscator/rewrite_vnext.py tests/test_rewrite_vnext.py`
  - `git diff --check HEAD`
  - `rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T046_rewrite_vnext_roundtrip.md`
independent_results: unittest exit 0, Ran 26 tests in 0.657s, OK; py_compile exit 0; diff check exit 0; READY_FOR_REVIEW guard exit 0 before this acceptance update
rewrite_oracle: PASS; full/top files=4, mapping_records=20, renamed_records=16, edits=41, strict catalog/top-overlay=0/0, all gate files changed
restore_oracle: PASS; files=4, modified_tokens=41, restored manifest equals input manifest, all physical files byte-identical
formal_verification: PASS; actual renamed gate positive exits 0 with `formal_equivalence=pass`; exact one-byte `~` functional negative remains strict-compile 0/0 and exits nonzero with `unproven` and `equiv_status -assert`
decision: all frozen T046 requirements passed; ACCEPTED
delivery: accepted tree is ready for the Main Agent commit and push; no T047 implementation was included
~~~
