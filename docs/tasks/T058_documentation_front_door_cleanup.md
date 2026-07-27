# T058：三文档入口收敛与废弃演示清理

- 状态：ACCEPTED
- 合同版本：1.1
- 设计时间：2026-07-27
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T057 `ACCEPTED`
- 起始 HEAD：`391063280c437b07cf57ca8b831c6f43f8d94b53`
- 任务类型：文档入口收敛 + 已授权 legacy demo cleanup

## 1. 单一目标

把当前产品的对外信息收敛到三份主文档，并删除不再属于产品入口的 `encrypt.py`：

1. `README.md`：只提供单文件、filelist、project-root 三种最简加密示例，以及完整
   `encrypt-vnext` 选项表；
2. `docs/systemverilog_renaming_table.md`：只用用户语言说明 19 个可加密类型、默认选择、
   alias 和跨模块名称选择方法；
3. `docs/project_structure.md`：面向开发者描述当前代码结构、模块职责和内部规范入口。

本任务不修改产品 CLI、加密语义、mapping schema、restore 或 Formal 行为。

## 2. 用户冻结要求

- 三份主文档和其他面向用户的命令都直接使用 `python`。
- 默认用户 Python 环境已安装 `pyslang`；文档不要求、推荐或展示 Conda。
- 子 Agent 和主 Agent 的实际测试、编译及验收命令使用
  `conda run -n rtl_obfuscation`；不得因用户文档使用 `python` 而改用缺少依赖的默认解释器验收。
- 不得安装或升级 Python 包。
- 用户文档只需要解释加密指令和可加密类型，不解释实现原理。
- `vNext` 只是新统一实现相对已删除旧路径的内部代号，不是加密算法或用户模式。本任务保留
  当前实际子命令 `encrypt-vnext`，不进行未授权的 CLI rename。

## 3. 三份主文档合同

### 3.1 `README.md`

固定顺序：

1. 一句话说明在仓库根目录运行；
2. 单文件加密；
3. 多文件/filelist 加密，并展示最小 `.f` 文件内容；
4. `project-root + top` 加密；
5. 明确 filelist 支持可选 `--top`：所有 filelist 文件继续执行普通类型加密，只有 top
   依赖闭包内的 ABI 名称可按显式授权加密，top 自身边界保持；
6. 简述 `--output-dir`、`--map`、`--metrics`；
7. 链接可加密类型表和开发者项目结构；
8. 文档末尾提供完整选项表。

三个示例必须：

- 使用 `python -m rtl_obfuscator.rewrite encrypt-vnext`；
- 可直接复制，并先建立三个彼此独立的输出父目录；
- single/filelist 的 `--input`、`--filelist` 使用相对于 `--source-root` 的路径；
- project-root 必须提供 `--top`；
- 默认示例不加入 category、ABI、rate 或 Formal 参数；
- 明确三个输出目标必须尚不存在，失败后应换新路径或先自行处理旧输出。

选项表必须完整覆盖：

```text
--input --filelist --project-root --source-root --top
--include-dir --define --category --abi-category
--encryption-rate --name-length --output-dir --map --metrics
```

README 不再包含 decrypt 操作、内部流水线、FIFO wrapper、Formal、RISC 发布或历史任务说明。

### 3.2 `docs/systemverilog_renaming_table.md`

- 保留 19 个 canonical category，名称和实现 registry 完全一致；
- 每行只包含：选项值、加密对象、默认选择、跨模块名称要求；
- 明确 `all` 只展开前 13 类；
- 明确 `struct` 展开 `struct_types + struct_fields`；
- 明确 `interface` 展开
  `interfaces + interface_instances + interface_ports + modports`；
- 明确一旦用户显式提供任一 `--category`，默认集合不会自动追加；
- 明确跨模块名称需要 `--top`，并同时出现在 `--category` 和
  `--abi-category`；
- 不解释 semantic owner、source range、mapping、gate 或 fail-closed 原理。

### 3.3 `docs/project_structure.md`

以当前仓库为准描述：

- 唯一产品 CLI：`rtl_obfuscator/rewrite.py`；
- `source_set.py`、`project_discovery.py`、`source_catalog.py`、
  `symbol_graph.py`、`category_registry_vnext.py`、`rewrite_policy.py`、
  `mapping_vnext.py`、`rewrite_vnext.py`、rate/metrics/orchestration/restore/Formal
  模块的职责；
- `tests/`、`scripts/`、`rtl_samples/`、`docs/tasks/` 的用途；
- 一行当前数据流；
- 链接 `docs/formal_verification.md`、`docs/future_work.md`、
  `docs/tasks/README.md` 和历史重构计划；
- 明确 `scripts/risc_v_vector_acceptance.py` 是专项发布工具，不是用户入口。

不得把历史任务流水账复制进该文档。

## 4. 文档同步边界

- `AGENTS.md`：恢复内部开发和验收使用 `rtl_obfuscation` Conda 环境的规则，同时明确三份
  用户文档只展示 `python`；增加 `docs/project_structure.md` 为当前结构来源；
- `docs/tasks/README.md`：更新三份主文档入口，并恢复内部验收使用 Conda、用户文档使用
  `python` 的双层规则；
- `docs/formal_verification.md`：示例命令改用 `python`；
- `docs/three_mode_refactor_plan.md`：只修正 R0–R5/T057 已完成状态，并指向当前结构文档；
- `rtl_samples/README.md`：删除 project-root 不接受 `all` 的过时说明，命令改用 `python`，
  并指向三份主文档。

历史任务合同、未来事项、Formal 规则和历史设计文档不得删除。

## 5. Cleanup manifest

允许删除：

- `encrypt.py`
- `tests/test_encrypt_demo.py`

删除原因：

- `encrypt.py` 只是 FIFO demo 的 subprocess wrapper，不是产品 CLI；
- 产品唯一入口已经是 `python -m rtl_obfuscator.rewrite encrypt-vnext`；
- wrapper 的非空 work-dir 行为不是产品合同。

必须保留或迁移的有效覆盖：

- single/filelist 正式 CLI：`tests/test_cli_vnext_encryption.py`；
- FIFO project-root 正式 CLI、strict gate、4 个 physical file 的 restore identity：
  `tests/test_project_root_vnext.py`；
- `tests/test_project_root_vnext.py` 必须增加一个显式 filelist + top 完整加密用例：
  - 输入 filelist 必须同时包含 top closure 和 closure 外文件；
  - category 选择必须由 `all` 加手动 `modules`、`ports`、`interface` 组成，最终 normalized
    selection 为全部 19 类；
  - ABI 必须显式选择全部 11 个 `MODULE_ABI_CATEGORIES`；
  - 所有 filelist physical files 必须进入 gate 和 restore；
  - closure 外文件的 eligible 非 ABI 对象必须 rename；
  - closure 外 ABI 必须 preserve 为 `outside_top_closure`；
  - closure 内授权 ABI 必须 rename；
  - selected top ABI 必须 preserve 为 `selected_top_boundary`；
  - strict compile 与全部 physical files restore byte identity 必须通过；
- 19 类和 ABI 边界继续由当前 category/product/RISC 已验收覆盖负责。

不得为了保留 wrapper 行为新增另一个演示脚本或兼容入口。

## 6. 允许修改的文件

```text
AGENTS.md
README.md
docs/formal_verification.md
docs/systemverilog_renaming_table.md
docs/project_structure.md
docs/tasks/README.md
docs/tasks/T058_documentation_front_door_cleanup.md
docs/three_mode_refactor_plan.md
rtl_samples/README.md
encrypt.py
tests/test_encrypt_demo.py
tests/test_cli_vnext_encryption.py
tests/test_project_root_vnext.py
```

不允许修改任何其他产品实现、fixture、脚本或历史任务合同。

## 7. 实现步骤

1. 将状态设为 `IN_PROGRESS`，记录 HEAD、工作区和
   `conda run -n rtl_obfuscation python` 的 PySlang 检查；
2. 先完成三份主文档和当前规则链接同步；
3. 把 FIFO 有效覆盖迁到正式 project-root CLI 测试；
4. 删除 wrapper 及其专属测试；
5. 执行下列五条验收命令并记录实际结果；
6. 全部通过才设置 `READY_FOR_REVIEW`。

版本 1.0 因错误地使用缺少 PySlang 的默认解释器而停止。版本 1.1 恢复时不得复用该运行时失败
作为阻塞证据；必须使用冻结的 Conda 环境重新执行全部验收命令。

## 8. 子 Agent 验收命令

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_cli_vnext_encryption tests.test_project_root_vnext -v
```

```sh
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rewrite.py tests/test_cli_vnext_encryption.py tests/test_project_root_vnext.py
```

```sh
conda run -n rtl_obfuscation python -c "from pathlib import Path; required=(Path('README.md'),Path('docs/systemverilog_renaming_table.md'),Path('docs/project_structure.md')); assert all(p.is_file() for p in required); assert not Path('encrypt.py').exists(); assert not Path('tests/test_encrypt_demo.py').exists(); text='\\n'.join(p.read_text(encoding='utf-8') for p in required); assert 'python -m rtl_obfuscator.rewrite encrypt-vnext' in text; assert 'conda run' not in text"
```

```sh
git diff --check HEAD
```

```sh
rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T058_documentation_front_door_cleanup.md
```

## 9. Formal verification

```text
formal_verification: N/A
reason: documentation and obsolete wrapper cleanup only; no rewrite engine, selection, gate, restore, or RTL semantics are modified
```

## 10. 执行记录

### 10.1 起始基线

- starting HEAD：`391063280c437b07cf57ca8b831c6f43f8d94b53`
- 起始工作区：`## main...origin/main`，仅有未跟踪的本任务合同
  `docs/tasks/T058_documentation_front_door_cleanup.md`
- `python --version`：exit code `0`，输出 `Python 3.13.5`
- `python -c "import pyslang; print(pyslang.__version__)"`：exit code `1`，
  `ModuleNotFoundError: No module named 'pyslang'`
- 已遵守用户冻结要求：未调用 Conda，未安装或升级 Python 包。

### 10.2 交付内容

- 三份主文档：
  - `README.md` 仅保留 single、filelist、project-root 三种加密示例、输出说明和完整
    `encrypt-vnext` 选项表；
  - `docs/systemverilog_renaming_table.md` 以用户语言列出与 registry 顺序一致的 19 类、
    默认集合、alias 和跨模块选择要求；
  - 新增 `docs/project_structure.md`，记录唯一 CLI、当前模块职责、数据流和内部规范入口。
- 当前规则和链接同步：`AGENTS.md`、`docs/tasks/README.md`、
  `docs/formal_verification.md`、`docs/three_mode_refactor_plan.md`、
  `rtl_samples/README.md`。
- replacement coverage：
  - `tests/test_cli_vnext_encryption.py` 的 single/filelist 正式 CLI 覆盖改用相对于
    `--source-root` 的输入路径；
  - `tests/test_project_root_vnext.py` 新增 FIFO 正式 project-root CLI 覆盖，检查全部 19 类和
    11 个 ABI category 的选择、strict gate、4 个 physical file 以及独立 restore
    byte identity。
- cleanup：删除 `encrypt.py` 和 `tests/test_encrypt_demo.py`；未新增 wrapper、兼容入口或
  wrapper 专属 work-dir 行为。
- 未修改产品实现、fixture、脚本或历史任务合同。

### 10.3 实际验收结果

1. `python -m unittest tests.test_cli_vnext_encryption tests.test_project_root_vnext -v`
   - exit code：`1`
   - 结果：两个测试模块都在 import 阶段失败，未执行实际测试方法；
   - 首个诊断：`rtl_obfuscator/symbol_graph.py` 导入 `pyslang` 时出现
     `ModuleNotFoundError: No module named 'pyslang'`。
2. `python -m py_compile rtl_obfuscator/rewrite.py tests/test_cli_vnext_encryption.py tests/test_project_root_vnext.py`
   - exit code：`0`
3. 第 8 节三文档、删除文件、加密命令和无 Conda 静态断言
   - exit code：`0`
4. `git diff --check HEAD`
   - exit code：`0`
5. `rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T058_documentation_front_door_cleanup.md`
   - exit code：`1`；任务按合同保持 `BLOCKED`，未设置 `READY_FOR_REVIEW`。

附加静态审计：

- 19 个 category 文档行与 `CANONICAL_CATEGORIES` 的名称和顺序一致：`category_rows=19`；
- 三份主文档及同步文档的相对链接检查通过；
- 允许文件中的当前文档不再引用 Conda、`encrypt.py`、`tests/test_encrypt_demo.py` 或
  project-root 不接受 `all` 的过时说明；
- 变更文件均位于第 6 节允许范围。

### 10.4 阻塞与边界

```text
status: BLOCKED
blocking_condition: default Python 3.13.5 cannot import pyslang
runtime_tests: NOT RUN; both requested modules failed during import
formal_verification: N/A
reason: documentation and obsolete wrapper cleanup only; no rewrite engine, selection, gate, restore, or RTL semantics are modified
review_request: none until the frozen runtime unittest command can execute successfully
```

未执行 `git add`、`git commit` 或 `git push`；未创建 T059。

### 10.5 v1.1 recovery 起始记录

- recovery starting HEAD：`391063280c437b07cf57ca8b831c6f43f8d94b53`
- recovery 起始工作区：保留并继续审计第 6 节允许范围内的 T058 v1.0 文档、测试和
  cleanup 改动；无范围外改动，无暂存改动。
- `conda run -n rtl_obfuscation python --version`：exit code `0`，输出
  `Python 3.12.13`。
- `conda run -n rtl_obfuscation python -c "import pyslang; print(pyslang.__version__)"`：
  exit code `0`，输出 `11.0.0`。
- v1.0 历史执行记录完整保留；v1.1 不复用默认 Python 缺少 PySlang 的阻塞证据。
- 状态已从 `READY` 变更为 `IN_PROGRESS`；未安装或升级任何依赖。

### 10.6 v1.1 recovery 交付与验收

恢复修正：

- `AGENTS.md` 和 `docs/tasks/README.md` 已恢复内部开发、测试和验收统一使用
  `conda run -n rtl_obfuscation` 的规则；三份主文档、样例说明及 Formal 展示命令仍只使用
  `python`。
- `README.md` 已明确 `vNext` 只是统一实现沿用的内部名称，并冻结 filelist + `--top`
  语义：全部 filelist physical files 继续处理普通 category；只有 top closure 内且显式
  `--category` + `--abi-category` 授权的 ABI 名称允许 rename；closure 外 ABI 与 selected
  top boundary 保持不变。
- `tests/test_project_root_vnext.py` 增加 filelist + top 完整加密黑盒用例；公共 helper 统一生成
  `all + modules + ports + interface` 以及全部 11 个 ABI 参数，并同时由 FIFO project-root
  用例复用。
- 新用例实际验证 normalized 19 类、11 类 ABI、4 个 filelist physical files 全部进入 gate
  和独立 restore、closure 外 internal symbol rename、closure 外 ABI
  `outside_top_closure` preserve、closure 内授权 ABI rename、selected top ABI
  `selected_top_boundary` preserve、strict compile 和 byte identity。
- v1.0 已删除的 `encrypt.py`、`tests/test_encrypt_demo.py` 以及 single/filelist 相对
  `--source-root` 测试继续保留；未修改任何产品实现、fixture 或范围外文件。

五条合同验收：

1. `conda run -n rtl_obfuscation python -m unittest tests.test_cli_vnext_encryption tests.test_project_root_vnext -v`
   - exit code：`0`
   - 结果：`Ran 10 tests in 2.477s`，`OK`
2. `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rewrite.py tests/test_cli_vnext_encryption.py tests/test_project_root_vnext.py`
   - exit code：`0`
3. 第 8 节三文档存在、废弃文件删除、用户命令包含 `python ... encrypt-vnext` 且三文档不含
   `conda run` 的静态断言
   - exit code：`0`
4. `git diff --check HEAD`
   - exit code：`0`
5. `rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T058_documentation_front_door_cleanup.md`
   - exit code：`0`

范围审计：

- 当前变更仅涉及第 6 节允许文件；
- 三份用户主文档、`rtl_samples/README.md` 和 `docs/formal_verification.md` 不含
  `conda run`；
- 未安装依赖，未执行 `git add`、`git commit` 或 `git push`，未创建 T059。

```text
formal_verification: N/A
reason: documentation and obsolete wrapper cleanup only; no rewrite engine, selection, gate, restore, or RTL semantics are modified
```

## 11. 主 Agent 验收

待 `READY_FOR_REVIEW` 后，主 Agent独立检查允许文件、三份主文档、cleanup replacement
coverage，并复跑第 8 节命令。只有全部通过才可设为 `ACCEPTED`、提交和推送。

### 11.1 独立验收记录

```text
acceptance_date: 2026-07-27
review_head: 391063280c437b07cf57ca8b831c6f43f8d94b53
scope: PASS; all modified, deleted and new files are in section 6
documentation:
  README single/filelist/project-root commands: PASS
  filelist optional top semantics: PASS
  19 canonical category table and aliases: PASS
  developer project structure: PASS
  three user-facing documents contain plain python commands and no conda run: PASS
cleanup:
  encrypt.py deleted: PASS
  tests/test_encrypt_demo.py deleted: PASS
  formal CLI replacement coverage migrated: PASS
filelist_top_full_encryption:
  selected_categories: 19/19
  abi_categories: 11/11
  physical_files_in_gate_and_restore: 4/4
  outside_closure_internal_rename: PASS
  outside_closure_abi_preserve: PASS; reason=outside_top_closure
  inside_closure_authorized_abi_rename: PASS
  selected_top_abi_preserve: PASS; reason=selected_top_boundary
  strict_compile: PASS
  restore_byte_identity: PASS
commands:
  conda unittest: 10 tests in 2.510s; OK; exit_code=0
  conda py_compile: PASS; exit_code=0
  documentation static assertion: PASS; exit_code=0
  git diff --check HEAD: PASS; exit_code=0
  READY_FOR_REVIEW guard before acceptance: PASS; exit_code=0
formal_verification: N/A
reason: no product implementation or rewritten RTL semantics changed
final_status: ACCEPTED
```
