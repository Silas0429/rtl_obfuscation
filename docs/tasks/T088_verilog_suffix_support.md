# T088：`.v/.vh` 三入口端到端加密支持

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：GPT-5.6 Luna（reasoning effort=`xhigh`）子 Agent
- 前置任务：T087 `ACCEPTED`，提交 `a7e0453`
- 任务类型：adapter migration + compact rewrite/restore/Formal
- 设计依据：[`three_mode_refactor_plan.md`](../development/architecture/three_mode_refactor_plan.md)、[`T039_sourceset_input_contract.md`](T039_sourceset_input_contract.md)、[`formal_verification.md`](../formal_verification.md)
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- Formal verification：必须使用本任务 compact `.v/.vh` fixture 的 actual renamed gate 执行正例和固定功能负例

## 1. 单一目标

在不新增重命名 category、不建立第二套 Verilog parser/rewrite 分支的前提下，让当前唯一
`SourceSet -> SourceCatalog -> SymbolGraph -> RewritePolicy -> MappingVNext -> gate/restore`
流水线端到端接受并处理：

- source unit：小写 `.sv`、`.v`；
- included physical header：小写 `.svh`、`.vh`。

`.v/.vh` 继续由当前 PySlang SystemVerilog semantic frontend 解析，Formal 继续使用现有
Yosys `read_verilog -sv`。本任务交付的是后缀兼容和现有加密能力复用，不宣称新增一套 strict
legacy-Verilog 方言或关键字模式。

本任务一次完成 single-file、显式 filelist、project-root 三入口、实际 `.vh` token 改名、gate、
持久化 mapping/manifest、direct restore、README/开发文档和 actual-gate Formal，不再拆分后续
实现任务。

## 2. 冻结背景与基线

起始基线必须为 `a7e0453` 且工作树干净。主 Agent 已完成以下只读/`/tmp` preflight：

1. 当前 single `.v` 返回 `SOURCESET_UNSUPPORTED_FILE`；
2. 当前 filelist `.v` 返回 `SOURCESET_UNSUPPORTED_FILE`；
3. 当前 project-root 只含 `.v` 时忽略该文件并返回 `SOURCESET_TOP_NOT_FOUND`；
4. 同一份 Verilog-2001 源码仅改后缀为 `.sv` 后，public encrypt、strict compile、direct restore、
   byte identity 和 multi-file actual-gate Formal 均通过；
5. 当前 `.svh` 中物理声明和引用可产生 actual rename edit：compact preflight 为
   `rename=1`、`modified_tokens=3`、strict/restore true，声明和一个引用均位于 header。

因此本任务只扩展受控 physical suffix contract，并复用现有 semantic/rewrite/restore 行为；不得
借机修改 SymbolGraph category/owner、mapping schema、rate/metrics 方程或 Formal 强度。

## 3. 冻结文件语义

### 3.1 source/header 分类

1. source unit suffix 集合精确为 `{.sv, .v}`；
2. header suffix 集合精确为 `{.svh, .vh}`；
3. physical RTL suffix 集合为上述并集；
4. suffix 区分大小写；`.V/.VH` 继续返回稳定 unsupported 输入错误或被 project-root 忽略；
5. `.v` 与 `.sv` 可在同一 filelist/SourceSet 中混用并保持用户顺序；
6. `.vh/.svh` 只进入 `included_files` 和 physical manifests，不进入 `compile_order`；
7. gate、mapping ranges、manifests、`design.f` 和 restore 保留原始相对路径及后缀，不把 `.v/.vh`
   改名为 `.sv/.svh`。

### 3.2 唯一实现来源

新增一个最小 `rtl_obfuscator/rtl_files.py`，只定义 canonical suffix 常量和纯路径分类 helper。
`source_set.py`、`project_discovery.py`、`source_catalog.py` 和 `rewrite_vnext.py` 必须复用它，禁止在
这些模块继续散落新的 `.v/.vh` 特判或建立模式专用分支。

### 3.3 三入口行为

- single-file：`--input path.v` 与现有 `.sv` 使用同一 adapter 和默认 category；
- filelist：source 行接受 `.sv/.v`，header 行接受 `.svh/.vh`，T087 的环境变量、嵌套 `-f`、
  顺序、重复、cycle 和 fail-closed 语义不变；
- project-root：递归发现四种小写后缀，以 `.sv/.v` 建立 source/top closure，以 `.svh/.vh` 建立
  include/physical dependency；closure 外文件仍排除；
- 下游 SourceCatalog、strict gate 和 rewrite audit 必须接受 mixed `.sv/.v` compile order。

## 4. 固定 compact fixture

新增 `tests/fixtures/t088_verilog_suffix/`：

```text
tests/fixtures/t088_verilog_suffix/
├── design.f
├── single.v
├── include/
│   └── internal.vh
└── rtl/
    ├── child.v
    └── top.v
```

fixture 必须只使用可由当前 SystemVerilog frontend 接受的 Verilog-2001 风格语法：

- top 固定为 `t088_top`；
- `top.v` 实例化 `t088_child`；
- `child.v` 在 module 内 include `internal.vh`；
- `internal.vh` 物理声明内部 signal `header_wire`，并至少包含一个绑定引用；
- top module 名和 top ports 保持；child ABI 按现有 top-enabled policy 处理；
- `header_wire` 必须为 `signals/rename`，declaration 和至少一个 occurrence 的 file 都是
  `include/internal.vh`，另一个绑定 occurrence 可位于 `child.v`；
- fixture 保持可综合，固定功能负例只把 actual gate 中一个 RHS ASCII `^` 改为 `|`，修改后 strict
  compile 仍通过而 Formal 必须非零失败。

`design.f` 必须显式列出两个 `.v` source 和 `.vh` header，并保持 source 顺序。`single.v` 用于公开
single-file smoke；project-root 使用同一目录和 `t088_top`，不得另建第二套 fixture。

## 5. 机器可检查结果

目标测试必须证明：

1. direct SourceSet 的 single/filelist/project-root 均接受 `.v`；filelist/project-root 正确分类
   `.vh`；T039/T087 原有 `.sv/.svh` 行为全部保持；
2. public single `.v`、filelist `.v/.vh`、project-root `.v/.vh` 三种加密均退出 `0`、
   `action_counts.rename > 0`、strict compile/内部 restore true；
3. filelist 与等价 project-root 的 normalized SourceSet/compile order/top closure 一致；
4. gate 中保留 `single.v`、`rtl/child.v`、`rtl/top.v`、`include/internal.vh` 后缀；canonical
   `design.f` 只列 source units，不把 `.vh` 当独立编译单元；
5. mapping/manifest/range 对 `.v/.vh` 路径可移植且 bytes 精确；`header_wire` 在 actual `.vh` 中
   被改名，不得只复制 header 后宣称支持；
6. public direct restore 无原始源码即可恢复 `.v/.vh`，全部 physical files byte-identical；
7. compact actual renamed gate Formal 正例退出 `0` 且 JSON `formal_equivalence=pass`；固定 `^ -> |`
   负例 strict compile 通过但 Formal 非零，并包含 unproven / `equiv_status -assert` 证据；
8. `.txt` source、`.V/.VH`、把 `.vh` 用作 single-file source unit 继续 fail-closed，失败不发布 gate；
9. public help、README、类型表、项目结构和 Formal 文档准确说明四种后缀及
   “`.v/.vh` 仍按 SystemVerilog semantic mode 解析”的边界；
10. README.pdf 与 README Markdown 同步，A4、文本可提取、页面无截断/重叠/黑块。

## 6. 明确不包含

- 不新增 strict Verilog-95/2001 parser mode、语言开关或按后缀切换 parser；
- 不承诺接受在 SystemVerilog 中已成为关键字的 legacy Verilog identifier；
- 不支持大写 `.V/.VH`、`.vp`、加密 vendor container、library map、glob 或新 filelist 指令；
- 不新增或修改 19 个 canonical category、SymbolGraph owner/range collector、RewritePolicy、
  MappingVNext schema、rate/metrics 方程；
- 不修改 restore/formal API 或 `scripts/formal_equivalence.py` 的证明强度；
- 不运行 RISC-V-Vector Formal、blanket unittest discovery、真实外部工程或历史 acceptance driver；
- 不删除旧测试/脚本，不修改历史任务合同，不创建 T089。

普通合同内失败（实现、test、strict、restore、Formal、PDF）必须由同一子 Agent 在本任务内修正，
不得拆成下一任务；只有触发协议停止条件才记录 BLOCKED。

## 7. 允许修改

```text
AGENTS.md
README.md
README.pdf
docs/systemverilog_renaming_table.md
docs/formal_verification.md
docs/development/project_structure.md
docs/development/future_work.md
docs/tasks/T088_verilog_suffix_support.md
rtl_obfuscator/rtl_files.py
rtl_obfuscator/source_set.py
rtl_obfuscator/project_discovery.py
rtl_obfuscator/source_catalog.py
rtl_obfuscator/rewrite_vnext.py
rtl_obfuscator/rewrite.py
tests/test_source_set.py
tests/test_public_cli.py
tests/test_t088_verilog_suffix.py
tests/fixtures/t088_verilog_suffix/**
```

允许列表内文件只做本任务需要的最小改动。不得修改 `symbol_graph.py`、`rewrite_policy.py`、
`mapping_vnext.py`、`orchestration_vnext.py`、`restore_vnext.py`、`formal_vnext.py`、
`scripts/formal_equivalence.py`、现有 RTL samples、T087 fixture 或其他任务单。

## 8. 固定验收命令

本任务选择 adapter migration 验收行，只运行以下四项：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t088_verilog_suffix tests.test_source_set tests.test_public_cli -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/rtl_files.py rtl_obfuscator/source_set.py \
  rtl_obfuscator/project_discovery.py rtl_obfuscator/source_catalog.py \
  rtl_obfuscator/rewrite_vnext.py rtl_obfuscator/rewrite.py \
  tests/test_source_set.py tests/test_public_cli.py tests/test_t088_verilog_suffix.py

/Users/lufengchi/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -c \
  'from pathlib import Path; from pypdf import PdfReader; task=Path("docs/tasks/T088_verilog_suffix_support.md").read_text(encoding="utf-8"); pdf=PdfReader("README.pdf"); text="\n".join(page.extract_text() or "" for page in pdf.pages); assert "- 状态：`READY_FOR_REVIEW`" in task; assert all(x in text for x in (".v", ".vh", "SystemVerilog")); assert all(float(page.mediabox.width) > 590 and float(page.mediabox.height) > 840 for page in pdf.pages); print(f"README.pdf pages={len(pdf.pages)} text_and_a4=pass")'

git diff --check HEAD
```

第一条目标测试内部必须真实调用 public `rtl_encrypt.py` / `rtl_decrypt.py` 和
`scripts/formal_equivalence.py`，保留 exact gold、actual gate、top=`t088_top`、seq=5、退出码和 JSON
供执行记录引用。不得 mock strict compile、restore 或 Formal。

README.pdf 还必须全部渲染为 PNG 并逐页检查；这属于第三项 PDF 验收，不新增命令行验收项。

## 9. 子 Agent 启动与交付边界

子 Agent 必须使用 GPT-5.6 Luna、reasoning effort=`xhigh`。开始前完整阅读 `AGENTS.md`、本合同、
任务流程、refactor protocol、直接链接设计和 Formal 文档；确认唯一活动任务为 T088 `READY`。

第一次实现编辑前：

1. 记录 `starting_head=a7e0453...` 与 clean worktree；
2. 将本任务状态改为 `IN_PROGRESS`；
3. 填写开始记录、允许文件与 baseline 结果；
4. 只修改第 7 节文件。

完成后记录：changed files、四项命令、实际测试数、三入口结果、`.vh` actual edit、restore bytes、
Formal gold/gate/top/command/exit/JSON、功能负例、PDF 页数/视觉检查和未覆盖边界；然后设置
`READY_FOR_REVIEW` 并停止。不得 stage、commit、push、设置 `ACCEPTED` 或创建下一任务。

## 10. 执行记录

```text
status: READY_FOR_REVIEW
starting_head: a7e04530eb5460850455fc2b92d10cf883448e0c
changed_files: AGENTS.md; README.md; README.pdf; docs/systemverilog_renaming_table.md; docs/formal_verification.md; docs/development/project_structure.md; docs/development/future_work.md; docs/tasks/T088_verilog_suffix_support.md; rtl_obfuscator/rtl_files.py; rtl_obfuscator/source_set.py; rtl_obfuscator/project_discovery.py; rtl_obfuscator/source_catalog.py; rtl_obfuscator/rewrite_vnext.py; rtl_obfuscator/rewrite.py; tests/test_t088_verilog_suffix.py; tests/fixtures/t088_verilog_suffix/**
baseline_commands: `git status --short --branch`; `git rev-parse HEAD`
baseline_results: `## main...origin/main`; only untracked T088 contract; starting HEAD `a7e04530eb5460850455fc2b92d10cf883448e0c`; parent preflight in section 2 confirmed `.v` single/filelist/project-root rejected and equivalent `.sv` flow passed.
commands: fixed section 8 command 1 unittest; fixed section 8 command 2 py_compile; fixed section 8 command 3 PDF text/A4 guard; `pdftoppm -png -r 120 README.pdf /private/tmp/t088-pdf-render.SUYvAX/page`; fixed section 8 command 4 `git diff --check HEAD`
results: unittest exit 0, Ran 30 tests, OK; py_compile exit 0; PDF guard exit 0 with `README.pdf pages=3 text_and_a4=pass`; all three public entries exit 0 with action rename > 0, strict compile and internal restore true; filelist/project normalized compile order `rtl/child.v`, `rtl/top.v`; physical header `include/internal.vh` actual declaration and occurrence edits; direct decrypt exit 0 and all physical bytes identical; diff check exit 0.
schema_or_behavior: added canonical `rtl_files.py` suffix helpers; `.sv/.v` are source units and `.svh/.vh` are included physical headers; mixed source order and original suffixes persist in SourceSet, design.f, manifests, mapping and restore; no parser/category/mapping/schema/formal API branch was added; safe relative include resolution permits an in-root `../include/...` header needed by the fixed Yosys flow while still failing outside-root includes closed.
boundaries: lower-case suffixes only; `.V/.VH`, `.txt`, and `.vh` single-file source fail closed without gate; support remains current PySlang SystemVerilog semantic mode and Yosys `read_verilog -sv`, not strict legacy Verilog; no RISC, blanket discovery or real-project run.
formal_gold: `tests/fixtures/t088_verilog_suffix/design.f` and root `tests/fixtures/t088_verilog_suffix`
formal_gate: `/private/tmp/t088-formal-evidence.X11krp/gate` actual renamed gate, canonical design.f contains only `rtl/child.v` and `rtl/top.v`
formal_top: `t088_top`
formal_command: `conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t088_verilog_suffix/design.f --gold-root tests/fixtures/t088_verilog_suffix --gate-filelist /private/tmp/t088-formal-evidence.X11krp/gate/design.f --gate-root /private/tmp/t088-formal-evidence.X11krp/gate --top t088_top --seq 5`
formal_exit_code: positive 0; fixed functional negative non-zero
formal_json: `{"formal_equivalence":"pass","gate":"/private/tmp/t088-formal-evidence.X11krp/gate","gold":"tests/fixtures/t088_verilog_suffix","seq":5,"top":"t088_top"}`
negative_formal_result: `/private/tmp/t088-formal-evidence.X11krp/negative` copied actual gate, changed one RHS ASCII `^` to `|`; Icarus strict compile exit 0; Formal exit 1 and output contained `unproven` and `equiv_status -assert`.
pdf_result: README.pdf regenerated from current README; 3 A4 pages, text extractable, tables and required `.v`, `.vh`, and `SystemVerilog` present; all pages rendered to PNG at `/private/tmp/t088-pdf-render2.YN3MNR` and visually checked with no truncation, overlap, black blocks, or missing glyphs.
cleanup_candidates: none
review_request: READY；请主 Agent 按 section 8 独立复跑四项固定验收、复核 actual-gate Formal 正负例和 PDF 三页后决定是否 ACCEPTED。
correction_round_1: 主 Agent 首轮审查要求补齐 mixed `.sv/.v` filelist 顺序与分类、stdout action_counts 精确断言、实际 `.vh` invalid public smoke、help 后缀断言、in-root/escaped include 回归，以及 README placeholder 和 future_work header 语义；本轮仅修改第 7 节允许文件，完成后重新执行四项固定验收。
correction_commands: `conda run -n rtl_obfuscation python -m unittest tests.test_t088_verilog_suffix tests.test_source_set tests.test_public_cli -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rtl_files.py rtl_obfuscator/source_set.py rtl_obfuscator/project_discovery.py rtl_obfuscator/source_catalog.py rtl_obfuscator/rewrite_vnext.py rtl_obfuscator/rewrite.py tests/test_source_set.py tests/test_public_cli.py tests/test_t088_verilog_suffix.py`; README.pdf regenerated and all pages rendered to `/private/tmp/t088-pdf-correction.sEkVl4`; fixed PDF text/A4 guard; `git diff --check HEAD`
correction_results: unittest exit 0, Ran 33 tests, OK; `_encrypt` now parses public stdout and asserts exact `action_counts.rename > 0`; dynamic filelist preserves `b.v`, `a.sv` order and classifies `shared.vh`; public `--input include/internal.vh` exits non-zero with empty stdout and no gate; public help contains `.sv` and `.v`; fixed in-root `../include/internal.vh` resolves, escaped `../../outside.vh` raises `SOURCESET_PATH_OUTSIDE_ROOT`, public failure has empty stdout and no gate; py_compile exit 0; PDF guard exit 0 with `README.pdf pages=3 text_and_a4=pass`; correction render visually passes; diff check exit 0.
correction_behavior: README uses copyable placeholder `<input_file.sv_or_v>`; future_work states headers can carry semantic mapping/edit while remaining outside compile_order; no include semantics beyond safe in-root normalization was added.
correction_review_request: READY；首轮证据保留于本节原字段，本轮修正已完成，请主 Agent 按 section 8 独立复跑并决定是否 ACCEPTED。
```

## 11. 主 Agent 验收

```text
acceptance_status: ACCEPTED
acceptance_head: a7e04530eb5460850455fc2b92d10cf883448e0c
allowed_files: all changed and untracked paths are within section 7; no SymbolGraph, policy, mapping schema, restore API, Formal script, historical task, existing sample, or T087 fixture change.
independent_commands: exact section 8 unittest, py_compile, PDF text/A4 guard, and `git diff --check HEAD`; direct public filelist encrypt/decrypt; direct actual-gate positive Formal; fixed `^ -> |` negative Icarus compile and Formal.
independent_results: section 8 unittest exit 0, Ran 33 tests, OK; py_compile exit 0; PDF guard exit 0 with `README.pdf pages=3 text_and_a4=pass`; diff check exit 0. The PDF status guard was run while the task remained READY_FOR_REVIEW, before this acceptance update.
single_file_v: public single `.v` coverage passed, including original suffix publication, rename action, strict compile, restore, invalid `.vh` single input, and fail-closed no-gate checks.
filelist_v_vh: public filelist encrypt exit 0; stdout `rename=5`; actual gate `/tmp/rtl-obfuscation-t088-main.LDssYV/gate`; canonical design.f contains only `rtl/child.v` and `rtl/top.v`; mixed `.sv/.v` ordering and `.vh` classification tests passed.
project_root_v_vh: public project-root coverage passed against the same fixture/top, with normalized source closure and physical `.vh` dependency matching filelist mode.
header_actual_edit: mapping contains a rename declaration and occurrence in `include/internal.vh`; plaintext `header_wire` is absent from the actual gate header.
restore_byte_identity: direct public decrypt exit 0 with `restored_input_manifest_equal=true` and `restored_byte_identical=true`; independent byte comparison passed for both `.v` sources and `.vh` header.
formal_positive: gold filelist/root `tests/fixtures/t088_verilog_suffix/design.f` / fixture root; gate filelist/root `/tmp/rtl-obfuscation-t088-main.LDssYV/gate/design.f` / gate; top `t088_top`; seq 5; exit 0; JSON `formal_equivalence=pass`.
formal_negative: copied actual gate to `/tmp/rtl-obfuscation-t088-main.LDssYV/negative`, changed one RHS ASCII `^` to `|`; Icarus strict compile exit 0; Formal exit 1 with `Found 1 unproven $equiv cells` and `equiv_status -assert` failure.
pdf_review: README.pdf has 3 A4 pages and extractable `.v`, `.vh`, and SystemVerilog text; main Agent rendered all pages to `/tmp/rtl-obfuscation-t088-main-pdf.xdjXBQ` and visually confirmed no clipping, overlap, black blocks, or missing glyphs.
scope_review: implementation centralizes suffix classification in `rtl_files.py`, preserves the one semantic/rewrite/restore pipeline and original suffixes, and adds only safe in-root relative include normalization required by the frozen fixture; lower-case suffix and SystemVerilog-mode boundaries remain explicit.
decision: ACCEPTED；合同内三入口、actual `.vh` edit、direct restore、strict compile、Formal 正负例、文档/PDF 和失败原子性全部独立通过。
delivery: 主 Agent 在本状态更新后按 Git 规范提交并推送；本计划至此结束，不创建 T089。
```

主 Agent 只按本合同复跑四项验收和同一 compact actual-gate Formal，不增加 RISC、真实工程或新的
实现阶段。若发现普通合同内缺陷，退回同一 Luna xhigh 子 Agent 修正；全部通过后设置
`ACCEPTED`、提交并推送。随后只核对状态并结束本计划，不创建偏离本合同的 T089。
