# T148：公开 filelist export 保留环境变量与原绝对路径

- 状态：`ACCEPTED`
- Main Agent：合同、冻结黑盒测试、独立验收和 Git 交付
- 实现：Luna extra high 子 Agent；只改本任务白名单，停在 `READY_FOR_REVIEW`
- 起点：`d52a7e260bcc3c093ab2ef33a61d899d6c1db723`，`main` 与 `origin/main` 一致，工作区原本干净
- 前置：T147 已 `ACCEPTED`；本任务是本轮唯一活动任务
- 验收类型：adapter 迁移；compact actual gate、relocated export Formal 与既有固定功能负例

## 单一目标与冻结输出

显式公开 `--filelist` 的 `export_design.f` 对路径 token 实现原文优先规则，保留原有逐份 filelist 行序与非路径字节：

1. 原 token 含 `${VAR}` 或 `$VAR` 时，export 对该 token 逐字节保留；`design.f` 仍在加密时展开并写实际 gate 绝对路径。交付用户在新环境中重设变量；不能依赖加密时的变量值完成 downstream 编译。
2. 原 token 为绝对路径且不含环境变量时，export 写 `$OUT` 加原绝对路径，即 `/a/b.sv` → `$OUT/a/b.sv`。该输出路径下必须有与 canonical gate 对应的普通物理文件；canonical gate 已在该路径时不得重复复制。对绝对 `-f`、`-v`、普通文件和 `+incdir+` 内的路径应用同一规则。
3. 不含环境变量的相对 token 沿用当前 root-relative `$OUT` 交付规则。`-f` 不内联；reachable nested filelist 在其各自文件中保序替换。env 形式的 `-f` 必须在变量重设后命中 gate 内改写后的子 filelist；必要的自然位置别名以普通物理文件发布，不使用 symlink。
4. `original_design.f` 仍与输入顶层逐字节相同；`design.f`、`export_design.f`、nested 各自的非路径文字、行数、行序、注释、空白和 CRLF 均保留。CLI-only context 不注入三视图。
5. 只发布实现上述引用所需的 gate 内 alias。源文件、included physical、改名结果、restored RTL 字节不变。Restore 对新 alias 的存在、范围、内容及无额外文件做 fail-closed 审计；不得放宽现有 symlink、escape、tamper 拒绝。
6. 在 `.rtl_obfuscation/filelists/original/` 保存每份 reachable nested filelist 的原始字节。`mapping.json` 仅在公开 filelist 交付时增加一个顶层 `delivery_filelists` manifest：以 gate 相对路径和 SHA256 锚定 `original_design.f` 与每份原始 nested 快照。保留 schema version 2、原有 mapping/source_set/metrics payload 与非 filelist 的旧报告形状。Restore 严格检查 manifest 类型、成员、摘要及所有原始快照；按对应原始文档逐条验证 export 的环境变量路径 token 完全相同、绝对路径 token 为 `$OUT/原绝对路径`，并审计快照缺失、额外项和 symlink。旧报告继续按旧合同恢复，不误判为本轮新交付。

本任务不产生 `src_flattened`、`design_flattened.f` 或 `src_flattened_log`；下一任务只在 T148 验收后创建。不改 FAST 分支、RISC、语义类别或 source discovery。

## 冻结输入与黑盒预期

Main Agent 新增并冻结 `tests/test_t148_export_original_paths.py`；子 Agent 不得修改。测试创建单根目录 fixture，故当前实现的 canonical gate 路径为 `gate/rtl/top.sv`，而绝对源 token 所需 export 路径为 `gate/<原绝对路径去首斜杠>`，可检验必要 alias。顶层 `-f ${COMM_HDL_PATH}/lists/nested.f` 与 nested `-v`、`+incdir+` 原样保留；用 `COMM_HDL_PATH=<relocated gate>` 与 `OUT=<relocated gate>` 对 actual gate 执行 Formal。原始路径目录和 gate 内 alias 都经公开 decrypt 审计，篡改 alias 必须拒绝。

主 Agent 在审查阶段新增冻结负例：同时篡改 export nested 与自然位置副本中的环境变量名，或者篡改原始 nested 快照，公开 decrypt 均必须以对应规则或摘要错误拒绝；别名篡改也须报具体内容错误。测试检查原始快照字节与 manifest 的 SHA256。每个篡改负例重新加密到独立输出目录，再在该 gate 原位篡改，确保拒绝原因是目标审计规则。搬迁后的 `export_design.f` 仍须通过 Formal；`design.f` 保存加密时的输出绝对路径，本任务不新增搬迁后直接 decrypt 的接口承诺。此测试仍由 Main Agent 持有，子 Agent 不得修改。

冻结测试起始命令：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t148_export_original_paths -v
```

起始实测：3 个测试中 relocated Formal 正例通过；export token 规则失败；缺少绝对路径 alias 导致篡改测试无法读取。子 Agent 先记录此 baseline，再实现。

## 允许修改的文件

- `rtl_obfuscator/source_set.py`：原 token 分类与两份交付视图的确定性路径规则。
- `rtl_obfuscator/rewrite.py`：仅在公开 filelist 发布阶段写必要 alias、nested 交付文件、原始 nested 快照和上述顶层 manifest。
- `rtl_obfuscator/restore_vnext.py`：新交付别名、原始快照、manifest 与环境 token 的严格审计。
- `README.md`、`docs/development/project_structure.md`、`docs/formal_verification.md`：同步对外行为。
- `docs/tasks/T148_export_original_path_tokens.md`：执行记录、偏差、状态。

冻结测试 `tests/test_t148_export_original_paths.py`、既有测试、RTL fixtures、Mapping/Rewrite/SourceCatalog 和 Formal 脚本不可修改。若测试合同与真实工具行为冲突，先在本任务记录证据并通知 Main Agent，不自行改 oracle。

## 验收门禁

唯一 baseline：上节冻结测试。完成后只运行以下五条；禁止 blanket discovery 和 RISC-V-Vector Formal。

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t148_export_original_paths -v

conda run -n rtl_obfuscation python -m unittest tests.test_t139_filelist_delivery tests.test_restore_vnext -v

conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_set.py rtl_obfuscator/rewrite.py rtl_obfuscator/restore_vnext.py tests/test_t148_export_original_paths.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; p=Path("docs/tasks/T148_export_original_path_tokens.md"); s=next(x for x in p.read_text().splitlines() if x.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t148_ready_for_review=pass")'
```

第一条测试中的 `T148_FORMAL` 必须是原始 RTL 对 actual renamed gate 的 `scripts/formal_equivalence.py` 退出 0 与 `formal_equivalence=pass`。第二条复用 T139 fixed XOR→OR 功能负例，须保持非零、`unproven` 与 `equiv_status -assert`。Main Agent 独立复跑所有门禁，尤其 Formal 流程；任一失败不得 ACCEPTED 或提交。

## 执行记录与 READY_FOR_REVIEW 守卫

子 Agent 开始前先读 `AGENTS.md`、本合同、`docs/tasks/README.md`、`docs/development/process/refactor_subagent_protocol.md` 和 `docs/formal_verification.md`，核对 HEAD/status，然后将状态改为 `IN_PROGRESS` 并记录开始项。发现假设/API/边界变化先记录，不扩大 scope。完成后记录 changed files、五条精确命令与输出、actual gate Formal gold/gate/top/exit/JSON、未覆盖边界，最后改状态为 `READY_FOR_REVIEW` 并运行精确守卫。不得自行设置 `ACCEPTED`、commit 或 push。

Main Agent 验收记录：2026-09-24 UTC 在 `main` 的 `d52a7e2` 起点独立复跑合同五条命令：T148 新黑盒 5/5，T139+restore 18/18，py_compile、`git diff --check HEAD`、状态守卫均 exit 0。T148 的 relocated actual-gate Formal 为 `formal_equivalence=pass`（gold=`/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t148-export-paths-ryeihc7c/project`，gate=`/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t148-export-paths-ryeihc7c/relocated`，top=`t148_top`，seq=`5`）；T139 固定功能负例 `negative_exit=1`、`unproven=true`、`equiv_status_assert=true`。主 Agent 审查代码、改动范围和三份文档，将“目录内容”措辞收窄为“已登记的目录内物理依赖”；接受本任务。提交及推送结果见 Git 历史/交付说明。

## 执行记录

- 开始：2026-09-24 03:31 UTC；starting_head=`d52a7e260bcc3c093ab2ef33a61d899d6c1db723`；开始前 `git status --short --branch` 为 `## main...origin/main`，只含主 Agent 提供的本任务单与冻结测试未跟踪项。开始前先设为 `IN_PROGRESS`。测试文件保持只读。
- baseline：首版冻结测试命令 `conda run -n rtl_obfuscation python -m unittest tests.test_t148_export_original_paths -v` exit `1`；3 tests，1 pass、1 fail、1 error。relocated export Formal 已通过；原 token 规则与绝对 alias 尚未实现。
- 合同增补后的 baseline：同一命令 exit `1`；5 tests 中 3 pass、2 error。两项 error 都是原始 nested snapshot 尚未交付，分别发生于快照字节断言和快照篡改负例。
- changed_files：`rtl_obfuscator/source_set.py`、`rtl_obfuscator/rewrite.py`、`rtl_obfuscator/restore_vnext.py`、`README.md`、`docs/development/project_structure.md`、`docs/formal_verification.md`、本任务单。主 Agent 提供的 `tests/test_t148_export_original_paths.py` 未修改。
- schema_or_behavior：公开 filelist 交付在 `.rtl_obfuscation/filelists/original/` 保存 reachable nested filelist 原始字节，并在 schema 2 报告顶层写入按发现顺序排列的 `delivery_filelists.originals` SHA256 manifest。Restore 核验 manifest、原始快照、env/absolute path token 规则及 alias/snapshot regular-file、symlink、extra-file 边界。mapping payload、SourceSet schema 与 RTL 不变；alias 使用普通物理副本，不用 symlink。
- 五条验收门禁：
  1. `conda run -n rtl_obfuscation python -m unittest tests.test_t148_export_original_paths -v`：exit `0`；5 tests passed。三个 tamper 精确拒绝原因为 `delivery alias content differs`、`export path token differs from original token rule`、`original filelist snapshot digest differs`，均为 `RESTORE_VNEXT_GATE_INVALID`。
  2. `conda run -n rtl_obfuscation python -m unittest tests.test_t139_filelist_delivery tests.test_restore_vnext -v`：exit `0`；18 tests passed。T139 功能负例字段为 `negative_exit=1`、`unproven=true`、`equiv_status_assert=true`；design positive 和 relocated export positive Formal 均 `formal_equivalence=pass`。
  3. `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_set.py rtl_obfuscator/rewrite.py rtl_obfuscator/restore_vnext.py tests/test_t148_export_original_paths.py`：exit `0`，无输出。
  4. `git diff --check HEAD`：exit `0`，无输出。
  5. `conda run -n rtl_obfuscation python -c 'from pathlib import Path; p=Path("docs/tasks/T148_export_original_path_tokens.md"); s=next(x for x in p.read_text().splitlines() if x.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t148_ready_for_review=pass")'`：exit `0`，输出 `t148_ready_for_review=pass`。
- actual-gate Formal：cwd=`/Users/lufengchi/Desktop/workspace/rtl_obfuscation`；`OUT=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t148-export-paths-3ildvuej/relocated`，`COMM_HDL_PATH` 同值。gold wrapper 使用原始项目的绝对 source 路径，变量重设到 relocated gate 后与 actual export gate 在同一进程比较。命令：`/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t148-export-paths-3ildvuej/gold_formal.f --gold-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t148-export-paths-3ildvuej/project --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t148-export-paths-3ildvuej/relocated/export_design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t148-export-paths-3ildvuej/relocated --top t148_top --seq 5`；exit=`0`；JSON=`{"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t148-export-paths-3ildvuej/relocated","gold":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t148-export-paths-3ildvuej/project","seq":5,"top":"t148_top"}`。
- 两层 nested 独立探针：`conda run -n rtl_obfuscation python /tmp/t148_two_level_probe.py` exit `0`。manifest 顺序是 `original_design.f`、`.rtl_obfuscation/filelists/original/lists/nested.f`、`.rtl_obfuscation/filelists/original/lists/nested2.f`；未篡改 decrypt exit `0`；同步改 export nested 与自然位置 alias 环境变量后 decrypt exit `1`，原因为 `export path token differs from original token rule`。
- 搬迁 decrypt 边界诊断：早期对 copytree 后的 gate 做 tamper 时，restore 在目标 token 审计前以 `design filelist path is invalid` 拒绝，因为 `design.f` 保存加密时输出目录的绝对路径。Main Agent 将冻结 tamper 用例改为各自重新加密到独立 gate 后原位篡改，并断言具体目标诊断；本任务不增加搬迁 gate 后直接 decrypt 的承诺。搬迁后的 `export_design.f` Formal 通过。
- boundaries：T148 冻结 fixture 覆盖绝对普通源 token 和 nested env `-f/-v/+incdir+`；绝对 `-f`、绝对 `-v`、绝对 `+incdir+` 复用相同分类与审计实现，但无各自独立 fixture。若新报告缺 manifest 而 snapshot 目录仍在，restore 拒绝；缺少清单中的快照、hash 不符、symlink 和额外文件也 fail-closed。若 manifest 与整套快照目录同时删除，产物与旧 schema 2 无法区分；为保留旧报告原有行为，使用兼容路径。`mapping.json` 未签名，联合改写报告与全部证据不属于本任务真实性保证。
- cleanup_candidates：无。
- review_request：请 Main Agent 独立复跑五条合同门禁并验收；子 Agent 不 commit、不 push、不设 `ACCEPTED`。
- 偏差或阻塞：原 nested token 缺少可信输入依据，已由 raw snapshots 与 `delivery_filelists` manifest 处理。早期 copytree tamper 探针的错误原因不是 token 规则，冻结测试现已原位篡改并检查精确拒绝诊断。
