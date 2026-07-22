# T039：统一 SourceSet 与三入口输入合同

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 所属重构阶段：R1
- 前置处置：T038 以提交 `e4f3f94` 保存为 `BLOCKED / NOT_ACCEPTED` 快照，不在本任务继续
- 设计依据：`docs/three_mode_refactor_plan.md`
- 执行规范：`docs/refactor_subagent_protocol.md`
- Formal verification：`N/A`，本任务不产生 rewritten RTL

## 1. 单一目标

新增统一的 `SourceSet` 输入层，使单文件、显式 filelist 和 project-root 三个入口输出同一种、
可比较、可序列化的数据结构。

本任务只确定文件集合、显式顺序、include/define、top、top closure 和 compile order；不收集
可重命名对象，不生成 mapping，不改写 RTL，也不改变现有 CLI 行为。

## 2. 固定公开 API

新增 `rtl_obfuscator/source_set.py`，提供以下公开对象：

```python
@dataclass(frozen=True)
class SourceSet:
    schema_version: int
    origin: str
    source_root: Path
    ordered_source_files: tuple[str, ...]
    included_files: tuple[str, ...]
    include_dirs: tuple[str, ...]
    defines: tuple[tuple[str, str], ...]
    top: str | None
    top_closure_files: tuple[str, ...]
    compile_order: tuple[str, ...]

    def to_report(self) -> dict[str, object]: ...

class SourceSetError(ValueError):
    code: str
    message: str
    path: str | None

def from_single_file(
    *, source_file: Path, source_root: Path,
    include_dirs: Iterable[Path | str] = (),
    defines: Iterable[str] = (), top: str | None = None,
) -> SourceSet: ...

def from_filelist(
    *, filelist: Path, source_root: Path,
    include_dirs: Iterable[Path | str] = (),
    defines: Iterable[str] = (), top: str | None = None,
) -> SourceSet: ...

def from_project_root(
    *, project_root: Path, top: str | None = None,
    include_dirs: Iterable[Path | str] = (),
    defines: Iterable[str] = (),
) -> SourceSet: ...
```

本任务不增加 CLI 子命令，也不要求从 `rtl_obfuscator/__init__.py` 重导出这些对象。

## 3. SourceSet 固定语义

### 3.1 共同规范化规则

1. `schema_version` 固定为 `1`；
2. `source_root` 保存为绝对、已解析的 `Path`；
3. 其余所有文件和目录字段使用 source-root-relative POSIX 路径；
4. `include_dirs` 保持调用者首次出现的顺序并去重；
5. define 接受 `NAME` 或 `NAME=VALUE`，无值时规范为 `NAME=1`；
6. `defines` 按 name 排序后保存为 `(name, value)` tuple，重复 name 取最后一次值；
7. `.sv` 只能进入 `ordered_source_files`、`top_closure_files` 和 `compile_order`；
8. `.svh` 只能进入 `included_files`，按 source-relative path 排序去重；
9. include 必须从 SourceSet 内 `.sv` 的有效 `` `include`` 依赖递归发现；
10. adapters 和 `to_report()` 不写文件、不创建缓存、不修改输入。

`to_report()` 固定返回以下 JSON-compatible 形状，tuple 转换为 list，`source_root` 转换为绝对
POSIX string：

```text
schema_version
origin
source_root
ordered_source_files
included_files
include_dirs
defines: [{name, value}, ...]
top
top_closure_files
compile_order
```

同一个 SourceSet 连续调用两次 `to_report()`，经
`json.dumps(report, sort_keys=True, separators=(",", ":"))` 后必须 byte-identical。

### 3.2 单文件入口

- `origin="single-file"`；
- `source_file` 必须是 source root 内的一个 `.sv`；
- `ordered_source_files=(source_file,)`；
- `compile_order=ordered_source_files`；
- 未提供 top 时 `top_closure_files=()`；
- 提供 top 时，只验证 top 位于该单文件 SourceSet，并计算该 SourceSet 内闭包；
- 除 `origin` 外，结果必须与只含同一文件的 filelist 入口相同。

### 3.3 显式 filelist 入口

- `origin="filelist"`；
- filelist 只接受空行、以 `#` 开始的注释行以及 source-root-relative `.sv`/`.svh` 路径；
- 本任务不支持 `-f`、`+incdir+`、`+define+`、library、glob 或命令行转义；
- 显式 `.sv` 顺序必须原样进入 `ordered_source_files`，禁止按路径排序；
- 显式 `.svh` 不成为 source unit，只合并到 `included_files`；
- `compile_order=ordered_source_files`，显式 filelist 的编译顺序属于用户输入合同；
- 未提供 top 时 `top_closure_files=()`；
- 提供 top 时仍保留 filelist 中全部 `.sv`，只把 top 可达的 `.sv` 子集写入
  `top_closure_files`；closure 外文件不得被删除；
- include discovery 覆盖 filelist 中全部 `.sv`，不只覆盖 top closure。

### 3.4 project-root 入口

- `origin="project-root"`；
- top 必填；
- discovery 可以查看 project root 内全部非符号链接 `.sv`/`.svh`，但 SourceSet 只保留 top
  closure；
- `ordered_source_files=compile_order`，二者都是确定的依赖顺序；
- `top_closure_files` 与 `ordered_source_files` 包含相同 `.sv` 集合；
- closure 外 `.sv` 不进入 SourceSet；
- 相同输入连续运行必须产生相同顺序；
- project-root adapter 完成 discovery 后即返回 SourceSet，不得进入 inventory、mapping 或
  rewrite。

## 4. 稳定失败合同

所有预期输入失败均抛出 `SourceSetError`。`str(error)` 固定以 `"<code>: "` 开头，且异常至少
提供 `code`、`message` 和可选 `path`。首批错误码：

| 错误码 | 使用条件 |
| --- | --- |
| `SOURCESET_INVALID_ARGUMENT` | top identifier 或 define 语法无效 |
| `SOURCESET_EMPTY_FILELIST` | filelist 没有有效条目 |
| `SOURCESET_DUPLICATE_FILE` | 同一规范化路径在 filelist 重复出现 |
| `SOURCESET_PATH_OUTSIDE_ROOT` | source、header 或 include-dir 逃逸 source root |
| `SOURCESET_FILE_NOT_FOUND` | source root、source、filelist、header 或 include-dir 不存在 |
| `SOURCESET_UNSUPPORTED_FILE` | source unit 不是 `.sv`，或 filelist 条目类型不支持 |
| `SOURCESET_TOP_REQUIRED` | project-root 未提供非空 top |
| `SOURCESET_TOP_NOT_FOUND` | top 在当前 SourceSet 候选中不存在或不是 module |
| `SOURCESET_TOP_AMBIGUOUS` | top 在候选中存在多个定义 |
| `SOURCESET_DISCOVERY_FAILED` | include、parse 或 closure discovery 无法安全完成 |

失败必须发生在返回 SourceSet 或写出任何 artifact 之前。不得吞掉旧 discovery diagnostic 后返回
部分结果。

## 5. discovery 复用边界

当前 `rtl_obfuscator/project.py` 的公开分析入口会同时运行 category profile 和 inventory，T039
不得从 SourceSet adapter 调用以下入口：

- `analyze_project()`；
- `analyze_project_context()`；
- `analyze_filelist_context()`；
- `inspect_project()`。

如需复用旧 top closure 算法，允许在 `project.py` 提取一个不接收 categories、不调用 inventory、
不写 report 的 discovery-only helper。要求：

- 旧公开分析入口行为保持不变；
- helper 只返回候选文件、closure、include files 和依赖顺序；
- 不复制第二份 `_ProjectContext` 或 include/closure 算法；
- `source_set.py` 不得导入 `inventory.py`、`rewrite.py` 或 mapping schema；
- 不得通过 fixture/module 名称或固定文件列表实现 closure。

## 6. 固定 compact fixture

新增 `tests/fixtures/refactor_source_set/`：

```text
design.f
closure.f
single.f
duplicate.f
outside.f
include/common.svh
rtl/z_defs.sv
rtl/a_child.sv
rtl/top.sv
rtl/unused.sv
rtl/standalone.sv
```

fixture 约束：

- `design.f` 的顺序固定为 `z_defs.sv`、`a_child.sv`、`top.sv`、`unused.sv`，故意不同于路径排序；
- `closure.f` 只包含前三个 closure source，顺序与 project-root 依赖顺序一致；
- `single.f` 只包含 `standalone.sv`；
- `a_child.sv` 依赖 `z_defs.sv` 和 `include/common.svh`；
- `top.sv` 实例化 child；
- `unused.sv` 和 `standalone.sv` 不在 top closure；
- `duplicate.f` 重复列出同一 `.sv`；
- `outside.f` 包含 `../outside.sv`，且必须在文件存在性检查前按越界失败。

fixture 仅冻结 SourceSet 语义，不包含重命名数量、mapping 或 Formal oracle。

## 7. 目标测试

新增 `tests/test_source_set.py`，至少验证：

1. single-file 与 `single.f` 的 normalized report 除 `origin` 外完全相同；
2. 无 top filelist 保留 `design.f` 原始 `.sv` 顺序；
3. filelist + top 仍包含 `unused.sv`，但 `top_closure_files` 不包含它；
4. project-root + top 排除 `unused.sv` 和 `standalone.sv`；
5. project-root 与 `closure.f + top` 的 include dirs、defines、top、closure 和 compile order 相同；
6. `common.svh` 只出现在 `included_files`；
7. duplicate、outside 和 project-root 缺失 top 分别返回固定错误码；
8. 连续两次 `to_report()` canonical JSON byte-identical；
9. `SourceSet` 字段不可修改；
10. monkeypatch 旧 inventory 分析入口为立即失败时，三个 adapter 目标测试仍通过，证明 T039 没有
    调用完整 inventory 路径。

不得断言 RISC-V-Vector 文件数、entry 数、occurrence 数、mapping version 或随机重命名结果。

## 8. 允许修改的文件

- `rtl_obfuscator/source_set.py`；
- `rtl_obfuscator/project.py`，仅允许提取第 5 节 discovery-only helper；
- `tests/fixtures/refactor_source_set/**`；
- `tests/test_source_set.py`；
- `docs/tasks/T039_sourceset_input_contract.md`，仅更新状态和执行证据。

不允许修改：

- `encrypt.py`、`rtl_obfuscator/inventory.py`、`rtl_obfuscator/rewrite.py`；
- category profile、mapping validator、decrypt 或 Formal 脚本；
- 现有 tests、RTL samples、README 或历史任务单；
- T038 保存提交中的 fixture、测试和代码。

## 9. 子 Agent 执行步骤

1. 完整阅读 `AGENTS.md`、本任务、总重构计划和子 Agent 规范；
2. 记录 starting HEAD 和 `git status --short --branch`；
3. 确认允许文件没有用户未提交修改；
4. 将状态改为 `IN_PROGRESS` 并填写开始记录；
5. 先创建 compact fixture 和失败测试；
6. 实现 frozen SourceSet、错误合同和三个 adapter；
7. 如确有需要，最小提取 discovery helper，并确认旧入口测试行为未被修改；
8. 运行第 10 节三条命令；
9. 填写第 11 节证据后设为 `READY_FOR_REVIEW`；
10. 停止，不提交、不推送、不开始 SymbolGraph。

出现 API/闭包语义与合同冲突、需要允许列表外修改、或者必须调用 inventory 才能完成时，记录偏差
并停止，不得新增兼容分支。

## 10. 唯一验收命令

只运行以下三条命令：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_source_set -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_set.py tests/test_source_set.py
git diff --check HEAD
```

不运行全量 unittest、Verible、Icarus、Yosys、RISC-V-Vector 或历史 acceptance driver。本任务不
解析重命名对象，也不产生 rewritten RTL，因此 Formal 明确为 `N/A`。

## 11. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
starting_head: e4f3f9437599aa91fc516419635a89c1170bf711
changed_files: `rtl_obfuscator/source_set.py`; `rtl_obfuscator/project.py` (discovery-only helper only); `tests/fixtures/refactor_source_set/**`; `tests/test_source_set.py`; this task record
commands: `conda run -n rtl_obfuscation python -m unittest tests.test_source_set -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_set.py tests/test_source_set.py`; `git diff --check HEAD`
results: unittest exit 0, 8 tests passed including omitted project-root top → `SOURCESET_TOP_REQUIRED`; py_compile exit 0; `git diff --check HEAD` exit 0. Baseline before implementation exited 1 because `tests.test_source_set` did not exist.
schema_or_behavior: implemented frozen schema-v1 SourceSet, deterministic report serialization, normalized source-root-relative paths, ordered filelist handling, recursive include discovery, define normalization, top closure and compile order, stable SourceSetError codes, and inventory-free single/filelist/project-root adapters.
boundaries: no CLI, inventory, mapping, rewrite, profile, fixture, or legacy-entry changes outside the allowed list; project-root discovery excludes closure-external sources; project.py helper performs no inventory or artifact writes; existing user documentation modifications were preserved. Refreshing the corrected staged snapshot was attempted but `.git/index.lock` creation was denied; no commit or push was performed.
cleanup_candidates: none; no obsolete tests or scripts were removed
formal_verification: N/A - no rewritten RTL is produced
review_request: READY_FOR_REVIEW; corrective coverage and all three revised commands passed. Main Agent must independently review the allowed-file diff, rerun these commands, and then decide whether to set ACCEPTED.
```

## 12. READY_FOR_REVIEW 条件

- 第 7 节目标全部由黑盒测试覆盖；
- 第 10 节三条命令全部退出 `0`；
- 允许列表外没有新增修改；
- filelist 顺序未排序，project-root 只产生 closure SourceSet；
- 没有调用完整 inventory 入口，没有新增 mapping/profile/legacy 分支；
- 所有失败在返回 artifact 前发生；
- 未覆盖边界和实际 helper 提取情况已记录；
- Formal 记录为 `N/A: no rewritten RTL is produced`。

## 13. 主 Agent 验收

主 Agent 只执行以下检查：

1. 审查 diff 是否严格落在允许文件；
2. 独立运行第 10 节三条命令；
3. 对比 single/filelist/project-root normalized report；
4. 确认旧完整分析入口未被 SourceSet 调用且现有行为没有被改写；
5. 通过后设置 `ACCEPTED`、提交，再制定 R2 SymbolGraph 任务。

不得临时增加全量回归、历史 mapping 数量或 RISC Formal 作为 T039 验收条件。

## 14. 主 Agent 验收记录

```text
acceptance_time: 2026-07-22
acceptance_head: e4f3f9437599aa91fc516419635a89c1170bf711
independent_commands: `conda run -n rtl_obfuscation python -m unittest tests.test_source_set -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_set.py tests/test_source_set.py`; `git diff --check HEAD`
independent_results: target module independently ran 8 tests and passed; py_compile exit 0; combined HEAD-to-worktree diff check exit 0
contract_review: single-file and one-file filelist normalized reports match; explicit filelist order is preserved; filelist + top retains closure-external sources; project-root contains only the deterministic top closure; omitted top returns SOURCESET_TOP_REQUIRED; complete inventory analysis entry points are not called
diff_review: T039 implementation changes are limited to source_set.py, the additive discovery-only project.py helper, the compact fixture, test_source_set.py, and this task record; pre-existing Main Agent planning-document changes were preserved separately
formal_verification: N/A - no rewritten RTL is produced
index_state: the Git index still contains the pre-correction versions of this task record and test_source_set.py, while the accepted corrections are in the working tree; the index must be refreshed before commit
acceptance_conclusion: ACCEPTED by Main Agent after independent review; commit and push remain pending
```
