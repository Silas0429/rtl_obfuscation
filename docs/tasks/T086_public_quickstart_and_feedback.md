# T086：用户快速入口与可读反馈

- 状态：`ACCEPTED`
- 主 Agent：`/root`
- 前置任务：T085 已 `ACCEPTED`
- 任务类型：公开 CLI 与用户文档整理；不增加加密能力

## 1. 单一目标

让第一次接触项目的 RTL 用户无需通读 README，即可在首页完成一次“加密、判断结果、解密”；同时让
终端摘要、`--help` 和失败提示明确区分实际改名、保留及不支持对象。

最高优先级是缩短首次成功路径。不得为了完整介绍内部能力继续扩张 README。

## 2. 固定输入

- 起始 HEAD：`57cddd34b159c5c460c0dcba9f3dfcd92e4fe692`
- 单文件样例：`rtl_samples/11_supported_obfuscation.sv`
- 多文件样例：`rtl_samples/example_fifo/design.f`，top=`fifo_top`
- 保守反馈样例：`tests/fixtures/t085_typedef_lexical_firewall/design.f`，top=`t085_top`
- 公开入口：`python rtl_encrypt.py`、`python rtl_decrypt.py`

## 3. 必须交付

1. README 开头先给出不超过三分钟的完整样例：环境前提一句、加密命令、成功判断、解密命令；安装细节后置。
2. README 明确真实工程优先使用显式 filelist，并建议从少量 category 开始逐类扩大；不得把默认 19 类描述为
   任意工程均已稳定支持。
3. 公开加密 JSON 在保留 schema 1 和已有字段的前提下，新增清晰的 action 计数：rename、preserve、unsupported；
   `encryption_summary.txt` 同步显示这三项，零改名不得表现成完整能力成功。
4. `rtl_encrypt.py --help` 和 `rtl_decrypt.py --help` 为每个公开参数提供简短中文说明，并提供三种输入模式提示。
5. 失败输出保留稳定首行 `error: <CODE>`，第二行提供用户可执行的中文 hint；失败仍原子化且不发布输出目录。
6. README 保留三种模式、解密、常用参数和文档链接，但删除重复架构解释与重复命令。安装平台范围不扩展。
7. README.pdf 与新 README 同步，修复标题挤压；只做清晰度优化，不引入新的视觉风格或生成依赖。

## 4. 不包含

- 不增加或修复任何 SystemVerilog category、SymbolGraph、policy、mapping 或 rewrite 行为；
- 不改变默认 category 集合、加密率算法、mapping schema、restore schema 或稳定错误码；
- 不增加 Windows、macOS、ARM wheel 或安装方案；
- 不运行真实工程矩阵或 RISC-V-Vector Formal；
- 不删除历史测试、脚本或文档。

## 5. 预期可观察结果

- README 的“3 分钟快速开始”位于安装细节之前，并在首屏给出 encrypt/decrypt 命令；
- T085 typedef profile 的公开摘要精确报告 `rename=1, preserve=6, unsupported=3, modified_tokens=2`；
- 同一 profile 的文字摘要包含上述三项，`mapping.json` 既有 action/reason 保持不变；
- 缺少 project-root `--top` 时首行为 `error: CLI_VNEXT_INPUT_INVALID`，第二行为中文检查提示，输出目录不存在；
- README 三个公开示例严格编译并可从 gate+mapping 无源恢复，逐字节一致；
- PDF 文本可提取、命令齐全、全部页面无重叠、截断或缺字方框。

## 6. 允许修改文件

- `docs/tasks/T086_public_quickstart_and_feedback.md`
- `README.md`
- `README.pdf`
- `docs/systemverilog_renaming_table.md`
- `rtl_obfuscator/rewrite.py`
- `tests/test_public_cli.py`

除此之外不得修改。所有临时 gate、restore、PDF 渲染图和日志写入 `/private/tmp` 或测试临时目录。

## 7. 验收命令

1. `conda run -n rtl_obfuscation python -m unittest tests.test_public_cli -v`
2. `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rewrite.py tests/test_public_cli.py`
3. 使用 README 的单文件、filelist、project-root 和 decrypt 命令在新 `/private/tmp` 目录重放，逐文件 `cmp`；
   另对 T085 profile 检查 action 计数与失败 hint。
4. 检查 README/用户文档本地 Markdown 链接为零失效；提取 README.pdf 文本并渲染全部页面人工检查。
5. `git diff --check HEAD`，随后执行精确状态与允许文件 guard。

公开 CLI 测试中的 actual renamed-gate Formal 正例和固定功能负例必须保持通过；本任务不改变 rewritten RTL
语义，不新增独立 Formal 场景，不运行 RISC-V-Vector Formal。

## 8. 执行记录

status: READY_FOR_REVIEW
starting_head: `57cddd34b159c5c460c0dcba9f3dfcd92e4fe692`；开始时仅本任务单为未跟踪文件，其他工作区内容干净
changed_files: `README.md`; `README.pdf`; `docs/systemverilog_renaming_table.md`; `rtl_obfuscator/rewrite.py`; `tests/test_public_cli.py`; `docs/tasks/T086_public_quickstart_and_feedback.md`
commands: `conda run -n rtl_obfuscation python -m unittest tests.test_public_cli -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rewrite.py tests/test_public_cli.py`; README 单文件/filelist/project-root/decrypt 命令在 `/private/tmp/t086-readme-smoke.2VuM3f` 重放并逐文件 `cmp`; T085 profile 与 missing-top hint 在 `/private/tmp/t086-feedback.yXQ5a2` 检查；103 个 README/docs Markdown 文件本地链接检查；使用现有 reportlab/pypdf/Poppler 从 README 生成、提取并渲染 PDF；`git diff --check HEAD`; 精确状态与允许文件 guard
results: baseline 13/13 PASS；最终目标回归 14/14 PASS（8.232s），py_compile PASS；三种模式均 strict/restore PASS，单文件 1 个、多文件 4 个恢复文件逐字节一致；T085 公开 JSON 与文字摘要均为 `rename=1, preserve=6, unsupported=3, modified_tokens=2`；missing-top exit 1，固定错误码首行与中文 hint 第二行正确且输出目录不存在；103 个 Markdown 文件 broken_links=0；PDF 为 A4 3 页、文本检查 PASS，3 页全部人工检查无标题挤压、重叠、截断、缺字方框或黑块；diff check、精确 READY_FOR_REVIEW 状态与 6 文件允许列表 guard 均 PASS
schema_or_behavior: 公开加密 stdout 保留 schema 1 与已有字段，新增顶层 `action_counts`；持久化 mapping/restore schema 不变；`encryption_summary.txt` 前置 action 计数与 modified token；公开 help 全参数中文说明；产品及 argparse 失败均为固定错误码首行和可执行中文 hint 第二行
boundaries: 不增加任何加密 category、闭包或 rewrite 行为；不改变默认 category、加密率、mapping/restore schema 或错误码；不扩平台安装；不运行真实工程矩阵或 RISC-V-Vector Formal
cleanup_candidates: none
formal_verification: PASS；复用 `tests.test_public_cli.PublicCliTests.test_public_implicit_project_actual_gate_formal_and_negative`，actual renamed gate top=`parameter_top`, seq=5，正例 JSON `formal_equivalence=pass`，固定功能负例非零退出且包含 unproven；本任务未改变 rewritten RTL 语义
review_request: READY；请主 Agent 独立复跑第 7 节五项验收、检查公开 JSON/help/hint，并逐页检查 README.pdf 后决定是否 ACCEPTED

## 9. 主 Agent 验收

status: ACCEPTED
review_head: `57cddd34b159c5c460c0dcba9f3dfcd92e4fe692`
implementation_review: PASS；公开入口只新增 action 计数、中文 help/hint 与 README/PDF 信息重排；
  加密 category、默认选择、mapping/restore schema、错误码和 rewritten RTL 语义均未改变
target_tests: PASS；`conda run -n rtl_obfuscation python -m unittest tests.test_public_cli -v`；
  exit 0；Ran 14 tests；OK；actual renamed-gate Formal 正例通过，固定功能负例按预期失败
py_compile: PASS；`rtl_obfuscator/rewrite.py` 与 `tests/test_public_cli.py`
public_smoke: PASS；主 Agent fresh root `/private/tmp/t086-main-smoke.UACp7U`；README 单文件、filelist、
  project-root 与公开 decrypt 全部 exit 0；单文件 1 个、多文件各 4 个恢复文件逐字节一致
feedback_oracle: PASS；T085 profile 公开 JSON 为 `rename=1, preserve=6, unsupported=3`、
  `modified_tokens=2`，文字摘要前四行一致；missing-top exit 1，首行稳定错误码、第二行中文 hint，
  output absent
documentation: PASS；README 285 行压缩为 177 行，3 分钟快速入口先于安装；103 个 README/docs
  Markdown 文件失效本地链接为 0；类型表明确默认选择不等于完整支持
pdf: PASS；主 Agent evidence root `/private/tmp/t086-main-pdf.CL9xEU`；A4 3 页、关键文本提取通过；
  三页逐页检查无标题挤压、重叠、截断、缺字方框或黑块
diff_and_guard: PASS；`git diff --check HEAD` exit 0；仅第 6 节六个允许路径有修改；
  starting HEAD 未漂移，无 staged change
decision: ACCEPTED；首次用户路径已前置并显著压缩，真实工程保守边界和少加密结果可直接观察；
  符合用户“无需通读 README 即可先成功运行”的最高目标
delivery: 未 commit、未 push；等待用户明确 Git 交付指令
