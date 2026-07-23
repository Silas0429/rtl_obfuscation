# T045：mapping vNext 核心与命名器合同

- 状态：`READY`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 所属重构阶段：R3-B
- 前置任务：T044 ACCEPTED，交付提交 451cf13
- 设计依据：docs/three_mode_refactor_plan.md 第 1–7 节
- 执行规范：docs/refactor_subagent_protocol.md
- 验收类型：mapping-only；不产生 rewritten RTL
- Formal verification：N/A - no rewritten RTL is produced

## 1. 当前项目位置与拆分决策

~~~text
SourceSet -> SourceCatalog -> SymbolGraph -> RewritePolicy
                                                |
                                                +-> T045 planned mapping vNext
                                                +-> 后续一次性 rewrite / gate / decrypt
                                                +-> 后续 metrics / manifests / adapters
~~~

T044 已冻结每个 SourceSymbol 的 rename、preserve 或 unsupported 决定。T045 只把这些决定转换为
一对一、可序列化、带新名称和完整 source ranges 的 planned mapping。它不应用 edit，不生成 gate，
不实现 decrypt、metrics、CLI 或 project-root 产品分支。

本任务必须先完成 mapping 边界校验，后续 rewrite 才能只消费同一份 records，禁止再次收集
declaration、reference、owner 或 category。

## 2. 单一目标

新增 rtl_obfuscator/mapping_vnext.py 和 rtl_obfuscator/systemverilog_names.py：

1. 只消费一个已建立的 RewritePolicy；
2. 重新验证公开 dataclass 可能被 replace 后的 policy 一致性；
3. 对全部 graph symbols 验证 owner、物理 range、source bytes、重复和重叠；
4. 通过显式 NameFactory 只为 action=rename 的 records 生成合法、唯一、无碰撞的新名称；
5. 产生一个 canonical planned mapping vNext report；
6. 记录输入物理文件 SHA-256 manifest；
7. 不修改输入 policy、graph、catalog、SourceSet 或 RTL 文件。

## 3. 固定输入

不新增或修改 fixture。只读复用 T043 已提交的 18 个冻结文件：

- tests/fixtures/refactor_symbol_graph_parameters/
- tests/fixtures/refactor_symbol_graph_parameters_invalid/

文件 bytes 与 SHA-256 以 docs/tasks/T043_symbol_graph_parameters.md 第 3.3 节和提交 22fee37 为准。
T045 正例只使用 design.f、closure.f、single.f、single.sv、positional.f 及其现有 RTL。
负例只通过公开 dataclasses.replace 构造，不修改磁盘 fixture。

子 Agent 开始前必须验证 18/18 hash；不一致时记录并停止，不得更新 oracle。

## 4. 主 Agent预检事实

T044 和冻结 fixture 的固定事实如下：

| input / request | symbols | rename | preserve | declarations | occurrences | total ranges |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| full，无 top，全部三类 | 20 | 13 | 7 | 20 | 33 | 53 |
| full + parameter_top + parameter ABI | 20 | 16 | 4 | 20 | 33 | 53 |
| closure + parameter_top + parameter ABI | 17 | 14 | 3 | 17 | 31 | 48 |
| single，无 top，signals + parameters | 3 | 2 | 1 | 3 | 2 | 5 |
| positional + positional_top + parameter ABI | 1 | 1 | 0 | 1 | 0 | 1 |
| full + parameter_top，仅 signals | 20 | 7 | 13 | 20 | 33 | 53 |

full 的 canonical source files 为：

~~~text
rtl/child.sv
rtl/shadow.sv
rtl/top.sv
rtl/unreachable.sv
~~~

closure 为前三个文件，single 为 single.sv，positional 为 rtl/positional.sv。当前这些 SourceSet
没有 included_files。上述数量只属于 compact fixture，产品实现不得按数量或路径分支。

## 5. 固定公开 API

rtl_obfuscator/systemverilog_names.py：

~~~python
SYSTEMVERILOG_KEYWORDS: frozenset[str]

def is_plain_identifier(value: object) -> bool: ...
~~~

plain identifier 固定为 ASCII 正则：

~~~text
[A-Za-z][A-Za-z0-9_]*
~~~

它必须排除全部 IEEE 1800 关键字。不得从 legacy inventory 导入关键字或名称 helper。

rtl_obfuscator/mapping_vnext.py：

~~~python
from collections.abc import Callable

NameFactory = Callable[[str, int, frozenset[str]], str]

@dataclass(frozen=True)
class InputFileDigest:
    file: str
    sha256: str

@dataclass(frozen=True)
class MappingRecord:
    symbol_id: str
    category: str
    action: str
    reason: str | None
    original_name: str
    renamed_name: str | None
    owner_module: str
    semantic_owner: str
    declaration: SourceRange
    occurrences: tuple[SymbolOccurrence, ...]
    impact: str
    abi: str

@dataclass(frozen=True)
class MappingVNext:
    format: str
    schema_version: int
    rewrite_policy: RewritePolicy = field(repr=False, compare=False)
    name_length: int
    input_manifest: tuple[InputFileDigest, ...]
    records: tuple[MappingRecord, ...]

    def to_report(self) -> dict[str, object]: ...

class MappingVNextError(ValueError):
    code: str
    message: str

def build_mapping_vnext(
    rewrite_policy: RewritePolicy,
    *,
    name_length: int,
    name_factory: NameFactory,
) -> MappingVNext: ...
~~~

不要求从 rtl_obfuscator/__init__.py 重导出。不得修改 T039–T044 的 dataclass 或 schema。

NameFactory 的三个参数依次是当前 symbol_id、固定 name_length 和当前全部 unavailable names 的
frozenset。调用方不能通过该集合修改 builder 状态。

## 6. mapping vNext core schema

build_mapping_vnext 固定产生：

~~~text
format = rtl-obfuscation.mapping-vnext
schema_version = 1
state = planned
~~~

to_report 顶层 key 顺序和 schema 固定为：

~~~text
format
schema_version
state
source_set
selection
name_length
input_manifest
records
summary
range_audit
~~~

source_set 只记录可移植 compile context：

~~~text
schema_version
ordered_source_files
included_files
include_dirs
defines
top
top_closure_files
compile_order
~~~

不得记录或按 SourceSet.origin 分支；不得记录 source_root 绝对路径。等价 single-file 与 single
filelist 的 planned mapping report 必须 byte-identical。

selection 固定记录：

~~~text
selected_categories
abi_categories
preserve_top_boundary = true
~~~

每个 record 固定记录：

~~~text
symbol_id
category
action
reason
original_name
renamed_name
owner_module
semantic_owner
declaration: file/start/end
occurrences:
  - source_range: file/start/end
    provenance
impact
abi
~~~

records 与 SymbolGraph.symbols、RewritePolicy.decisions 恰好一对一并保持 canonical 顺序。
rename record 必须 reason=null 且 renamed_name 为字符串；preserve/unsupported 必须
renamed_name=null 并沿用 policy reason。

input_manifest 按 ordered_source_files 后接未重复 included_files 的顺序记录 file 和小写 64 位
SHA-256。summary 固定为 rename、preserve、unsupported、total。range_audit 固定为 declarations、
occurrences、total_ranges。

连续两次 canonical JSON 序列化必须 byte-identical。T046 以后会增加 gate/restored execution
evidence；不得因此改变本任务已冻结的 core fields 或 records 语义。

## 7. policy、owner 与 range fail-closed

### 7.1 policy 重新验证

公开 frozen dataclass 可以被 dataclasses.replace 构造，因此 mapping 边界不能仅信任字段：

1. RewritePolicy、SymbolGraph、SourceCatalog 和 SourceSet schema_version 必须为 1；
2. 使用公开 build_rewrite_policy，以同一 graph、selected_categories 和 abi_categories 重建
   canonical expected policy；
3. expected decisions 必须与输入 decisions 在数量、顺序和全部字段上完全一致；
4. policy format、action、reason、symbol_id 或 category 任一被篡改均 fail-closed；
5. 不得修正、排序、跳过或输出部分 mapping。

### 7.2 owner 和物理文件

1. owner_module 必须对应 SourceCatalog.modules 中的唯一 module name；
2. semantic_owner 必须为非空字符串；
3. physical files 是 ordered_source_files 与 included_files 的稳定去重并集；
4. 文件必须仍位于 source_root 内、存在且为普通文件；
5. 每个 declaration/occurrence.file 必须属于 physical files。

### 7.3 range audit

对全部 records，包括 preserve 和 unsupported：

1. start/end 必须为非 bool 整数，满足 0 <= start < end <= file bytes；
2. source[start:end] 必须 byte-identical 等于 original_name 的 UTF-8；
3. 一个 symbol 内和不同 symbols 间都不允许 exact duplicate 或任意 overlap；
4. declaration 与 occurrences 全部参与同一全局 audit；
5. audit 失败不调用 NameFactory，不产生 mapping。

mapping 只能复制 SymbolGraph 已有 ranges 和 provenance，禁止 AST/CST、正则或 legacy collector
再次寻找 declaration/reference。

## 8. 命名合同

### 8.1 name_length

- 必须是非 bool 整数且不小于 4；
- 非法时返回 MAPPING_NAME_LENGTH_INVALID；
- 每个 renamed_name 的字符长度必须精确等于 name_length。

### 8.2 unavailable names

unavailable names 是以下集合的并集：

1. 所有 physical source bytes 中 ASCII identifier 的保守 lexical over-approximation；
2. SourceCatalog.catalog_root 现有 semantic node 的非空 name；
3. 全部 SourceSymbol.original_name；
4. 已接受的 renamed_name。

lexical/semantic 收集只用于避免命名碰撞，不能产生 mapping candidate、range、owner 或 classification。
允许访问已有 catalog_root；禁止重新编译。

### 8.3 NameFactory 调用与验证

- 只对 rename decisions 调用，按 records canonical 顺序，每项恰好一次；
- preserve/unsupported 不调用；
- name_factory 必须 callable，否则 MAPPING_NAME_FACTORY_INVALID；
- factory 抛出异常时包装为 MAPPING_NAME_FACTORY_FAILED；
- 返回值必须是精确长度的 plain identifier 且不是关键字，否则 MAPPING_NAME_INVALID；
- 返回值已在 unavailable names 中时返回 MAPPING_NAME_COLLISION；
- 验证通过后立即加入 unavailable names，再处理下一 record；
- 不重试、不静默跳过、不自动修改 factory 返回值。

T045 只冻结注入式命名器边界，不实现默认随机命名器。后续产品入口必须通过同一 NameFactory
合同接入安全随机实现；目标测试使用基于 symbol_id 的显式确定性 factory。

## 9. 稳定错误码与优先级

异常字符串必须以 '<code>: ' 开头。验证顺序固定为：

1. name_length；
2. name_factory callable；
3. policy/schema/decision；
4. owner/physical file；
5. range bytes/overlap；
6. NameFactory 调用及 candidate。

| condition | code |
| --- | --- |
| name_length 非法 | MAPPING_NAME_LENGTH_INVALID |
| name_factory 不可调用 | MAPPING_NAME_FACTORY_INVALID |
| factory 抛出 | MAPPING_NAME_FACTORY_FAILED |
| policy/schema/decision 不一致 | MAPPING_POLICY_INVALID |
| owner 或 physical file 不成立 | MAPPING_SOURCE_INVALID |
| range 越界、文件错误或 bytes 不匹配 | MAPPING_RANGE_INVALID |
| duplicate 或 overlap | MAPPING_RANGE_OVERLAP |
| candidate 类型、长度、语法或关键字非法 | MAPPING_NAME_INVALID |
| candidate 与已有或本次名称碰撞 | MAPPING_NAME_COLLISION |

任一错误不返回部分 records 或 manifest。

## 10. 冻结正例 oracle

使用显式确定性 factory：

~~~python
name = "n" + sha256(symbol_id.encode("utf-8")).hexdigest()[: name_length - 1]
~~~

测试 name_length 固定为 16。必须验证：

1. 第 4 节六组 counts 和 range audit；
2. NameFactory 调用次数分别为 13、16、14、2、1、7；
3. full input_manifest 依次为四个 source files 及 T043 冻结 SHA-256；
4. closure/single/positional manifest 分别只含其 SourceSet physical files；
5. full/top parameter ABI 的 4 个 preserve reasons 仍为 selected_top_boundary=3、
   outside_top_closure=1；
6. single-file 和 single filelist report 完全一致，不需要删除 origin/source_root；
7. 所有 renamed_name 唯一、合法、长度 16，且不等于任何 unavailable input name；
8. 输入 policy、graph 和 source bytes 在构建前后不变。

## 11. 目标测试（恰好 14 项）

新增 tests/test_mapping_vnext.py，只通过第 5 节公开 API 覆盖：

1. full/no-top 的 20 records、13/7 summary、53 ranges；
2. full/top + parameter ABI 的 16/4、preserve reasons 和 16 次命名；
3. closure/top + parameter ABI 的 14/3、48 ranges；
4. single-file 与 single filelist report byte-identical 且 2/1；
5. positional/top + ABI 为 1/0；full/top signals-only 为 7/13；
6. records 与 graph/policy 一对一同序，字段、dataclass 和 report schema 精确稳定；
7. deterministic factory 参数、调用顺序、unavailable 增长、连续 JSON 稳定；
8. input_manifest 的文件顺序和 frozen SHA-256，且 report 无 origin/source_root；
9. name_length 与不可调用 factory 请求错误矩阵；
10. factory exception、非法类型/长度/语法/关键字和碰撞错误矩阵；
11. replace 构造的 policy/schema/decision 数量、顺序、字段篡改全部 fail-closed；
12. unknown owner、空 semantic_owner、非 physical file、越界和 bytes mismatch 全部 fail-closed；
13. exact duplicate 与 partial overlap ranges 都返回 MAPPING_RANGE_OVERLAP；
14. graph 建立后阻断 source_catalog._compile_view、symbol_graph.build_symbol_graph、legacy
    inventory/rewrite/category profile 入口；mapping 仍成功，输入对象和 fixture 不变。

测试不得调用 mapping 私有 helper，不得修改 fixture，不得创建 fake semantic root，不得调用默认
随机源。T044 12 tests 与 T045 14 tests 在同一命令运行，共 26 tests。

## 12. 允许修改的文件

- rtl_obfuscator/systemverilog_names.py
- rtl_obfuscator/mapping_vnext.py
- tests/test_mapping_vnext.py
- docs/tasks/T045_mapping_vnext_naming.md，仅状态和执行记录

其他实现、测试、fixture、README、计划文档和历史任务全部只读。需要修改允许列表外文件时，先在
任务单记录原因并停止，不得自行扩大 scope。

## 13. 明确不包含

- 不应用 source edits，不写 gate 或 restored RTL；
- 不实现 strict compile、gate audit、decrypt 或 Formal；
- 不实现默认随机命名器、CLI、name-length 参数 adapter；
- 不生成 per-file mapping；
- 不生成 gate/restored manifest；
- 不实现 effective-line、rate selection 或 metrics；
- 不接入 project-root 产品入口，不按 origin 分支；
- 不新增 category，不修改 RewritePolicy 或 SymbolGraph；
- 不导入、调用或复制 legacy inventory/rewrite mapping builder；
- 不清理 legacy 测试、schema 或兼容路径。

Formal 必须记录为 N/A - no rewritten RTL is produced，不得运行 identity comparison。

## 14. 子 Agent强制执行规范

1. 完整阅读 AGENTS.md、本任务、docs/refactor_subagent_protocol.md 和重构计划第 1–7 节；
2. 确认 451cf13 是 HEAD 祖先、T044 为 ACCEPTED、T045 是唯一 READY 任务；
3. 校验 18/18 fixture hash并通过公开 API 复核第 4 节全部 counts；
4. 编辑实现前将状态改为 IN_PROGRESS，填写 starting HEAD、工作区和 baseline；
5. baseline 只运行第 15 节 unittest，预期 T044 12 tests 通过，随后仅因 T045 模块不存在失败；
6. 一次建立第 11 节全部 14 项测试，再实现 identifier helper、policy/range validation、naming 和 report；
7. 普通实现失败、NameFactory 测试失败或 report 差异属于任务内问题，不得分批暂停要求补设计；
8. 只有冻结 API/fixture 事实冲突、需要允许文件外修改、无法证明 range 唯一或已有 catalog 无法提供
   collision set 时才停止；
9. 完成后只运行第 15 节四条命令，一次填写完整证据并设 READY_FOR_REVIEW；
10. 不得设置 ACCEPTED，不得 git add/commit/push，不得创建 T046，不得写主 Agent验收记录。

子 Agent不得以旧 mapping v1/v2/v3/v4 测试失败为由增加兼容代码或运行历史 acceptance。

## 15. 唯一验收命令

~~~sh
conda run -n rtl_obfuscation python -m unittest tests.test_rewrite_policy tests.test_mapping_vnext -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/systemverilog_names.py rtl_obfuscator/mapping_vnext.py tests/test_mapping_vnext.py
git diff --check HEAD
rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T045_mapping_vnext_naming.md
~~~

不运行 blanket discovery、legacy tests、HDL compile、gate、decrypt、Yosys、RISC 或历史 acceptance。
主 Agent只独立复跑以上四条命令，不增加隐藏 probe。

## 16. 子 Agent执行记录

~~~text
status: NOT_STARTED
starting_head:
fixture_hash_check:
preflight_counts:
baseline_command:
baseline_result:
changed_files:
commands:
results:
schema_or_behavior:
deviations_or_blockers:
boundaries:
formal_verification: N/A - no rewritten RTL is produced
review_request:
~~~

## 17. READY_FOR_REVIEW 条件

- 第 11 节恰好 14 项测试全部覆盖，T044+T045 共 26 tests 通过；
- 第 15 节四条命令全部退出 0；
- diff 只包含第 12 节四个允许文件，18 个 fixture hash 不变；
- policy、owner、physical files、ranges 和 names 全部 fail-closed；
- records 与 graph/policy 一对一同序，report 和 manifest canonical；
- single-file 与 single filelist mapping report 完全一致；
- 没有 recompile、graph rebuild、legacy 调用、source edit 或 origin 分支；
- Formal 准确记录 N/A，状态严格为 READY_FOR_REVIEW。

## 18. 主 Agent验收边界

主 Agent只执行：

1. 审查 starting HEAD、允许文件、fixture hash 和预检 counts；
2. 审查 14 项测试只使用公开 API 和真实 T043/T044 对象；
3. 审查 policy 重建、range audit、collision set 与 NameFactory fail-closed；
4. 确认 report 不含 origin/source_root，records 不来自第二 collector；
5. 在状态仍为 READY_FOR_REVIEW 时独立运行第 15 节四条命令；
6. 全部通过后写验收记录并设置 ACCEPTED。

退回必须引用本合同具体条款或测试项。不得在验收时追加随机命名、rewrite、gate、metrics、
project-root 或 legacy compatibility 要求。

## 19. 主 Agent合同冻结记录（2026-07-23）

~~~text
status: READY
baseline_commit: 451cf13
decision: freeze one canonical planned mapping and injected naming boundary before any RTL edit
format: rtl-obfuscation.mapping-vnext schema_version 1 state planned
inputs: committed T043 fixtures + accepted T044 RewritePolicy
positive_oracles: 20/13/7/53, 20/16/4/53, 17/14/3/48, 3/2/1/5, 1/1/0/1
negative_matrix: request, factory, policy, owner, file, bytes, duplicate, overlap, collision
acceptance: exactly four commands; 26 tests; no Formal or hidden probe
formal_verification: N/A - no rewritten RTL is produced
~~~
