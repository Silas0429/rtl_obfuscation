# T023：自动单 Category debug CLI

- 状态：`ACCEPTED`
- 负责人：主 Agent
- 前置任务：T022 `ACCEPTED`

## 1. 单一目标

为两个加密命令增加 `--debug <directory>`：

- `encrypt`：从同一个单文件 gold 独立运行 13 个默认 category；
- `encrypt-project`：从同一个 filelist gold 独立运行全部 19 个 category；
- 不为 `decrypt` 或 `decrypt-project` 增加 debug 行为。

## 2. CLI 契约

单文件：

```sh
python -m rtl_obfuscator.rewrite encrypt \
  --input <gold.sv> \
  --debug <debug-root> \
  --name-length 8
```

每个 category 输出：

```text
<debug-root>/<category>/gate.sv
<debug-root>/<category>/mapping.json
<debug-root>/<category>/metrics.json
```

多文件：

```sh
python -m rtl_obfuscator.rewrite encrypt-project \
  --filelist <design.f> \
  --source-root <gold-root> \
  --top <top> \
  --debug <debug-root> \
  --name-length 8
```

每个 category 输出：

```text
<debug-root>/<category>/gate/<mirrored project files>
<debug-root>/<category>/maps/<per-file JSON>
<debug-root>/<category>/mapping.json
<debug-root>/<category>/metrics.json
```

debug 模式禁止传入普通模式的 `--category`、`--output`、`--output-dir`、
`--map`、`--metrics` 或 `--file-map-dir`。非 debug 模式保持原有必填参数和行为。

## 3. stdout

debug 成功时只输出一个 JSON：

```json
{
  "debug": true,
  "mode": "single-file | project",
  "category_count": 13,
  "runs": [
    {"category": "signals", "files": 1, "mapping_entries": 7, "modified_tokens": 24}
  ]
}
```

`runs` 顺序与 `inventory._ALL_CATEGORIES` / `inventory._SUPPORTED_CATEGORIES` 一致。
任一 category 失败时命令非零退出；已完成子目录保留作为调试证据。

## 4. 允许文件

- `rtl_obfuscator/rewrite.py`
- `tests/test_debug_mode.py`
- `read.md`
- `docs/tasks/T023_debug_cli.md`

## 5. 验收

1. 单文件 debug 精确生成 13 个 category 目录，包括无可替换对象的 `0/0` 运行。
2. FIFO project debug 精确生成 19 个 category 目录，计数与重命名表一致。
3. 每个子 mapping 只包含对应 category，每次都基于 gold source range。
4. 旧的单文件和多文件普通命令保持兼容。
5. `--debug` 与普通模式参数混用时非零退出并给出明确错误。
6. 单文件和 project debug 代表 gate 通过 PySlang 和 Yosys formal。
7. 完整 unittest、`py_compile`、`git diff --check` 通过。

## 6. 验收结果

- 单文件 `--debug` 实际生成 13 个子目录，stdout 为 `category_count=13`；
  含 `instances`、`struct_types`、`struct_fields`、`union_fields` 四个 `0/0` 运行。
- FIFO project `--debug` 实际生成 19 个子目录，stdout 为
  `category_count=19`；各类 entries/tokens 与重命名表一致，每类都包含
  gate、global mapping、metrics 和四个 per-file mapping。
- 所有 32 个 debug gate 的 PySlang compilation 检查为 `errors=0`。
- 单文件代表 gate `single/signals/gate.sv` 的 Yosys formal 结果为
  `formal_equivalence=pass`；project 代表 gate `project/parameters/gate/` 也为
  `formal_equivalence=pass`。

  ```text
  formal_verification: PASS
  gold: rtl_samples/11_supported_obfuscation.sv
  gate: /tmp/t023_debug_review.ci95xR/single/signals/gate.sv
  top: sample11_supported_obfuscation
  command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold rtl_samples/11_supported_obfuscation.sv --gate /tmp/t023_debug_review.ci95xR/single/signals/gate.sv --top sample11_supported_obfuscation
  exit_code: 0
  result: {"formal_equivalence":"pass","seq":5,"top":"sample11_supported_obfuscation"}

  formal_verification: PASS
  gold: rtl_samples/example_fifo/design.f; root=rtl_samples/example_fifo
  gate: /tmp/t023_debug_review.ci95xR/project/parameters/gate/design.f; root=/tmp/t023_debug_review.ci95xR/project/parameters/gate
  top: fifo_top
  command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist rtl_samples/example_fifo/design.f --gold-root rtl_samples/example_fifo --gate-filelist /tmp/t023_debug_review.ci95xR/project/parameters/gate/design.f --gate-root /tmp/t023_debug_review.ci95xR/project/parameters/gate --top fifo_top
  exit_code: 0
  result: {"formal_equivalence":"pass","seq":5,"top":"fifo_top"}
  ```

- 与普通模式参数混用会在产生输出前非零退出；decrypt 不接受
  `--debug`。旧的普通加密、解密和 formal 正负例全部通过。
- 完整回归实际 `Ran 33 tests`、`OK`；`py_compile` 和 `git diff --check`
  通过。
- 主 Agent 验收：`ACCEPTED`。
