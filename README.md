# RTL 工程加密

本项目读取工程 filelist，加密 SystemVerilog RTL 中可安全改写的名称，并输出加密源码、编译 filelist、映射和恢复所需文件。实际使用时选择以下一个分支：

| 方案 | 分支 | 加密内容 |
| --- | --- | --- |
| 快速加密 | `delivery/fast-local-signals` | 仅处理自有 RTL 中 module 直接声明的局部 `signals` 及可确认的引用 |
| 全量加密 | `main` | 以指定 `TOP` 为顶层，处理其层次闭包中的 `signals`、`ports`、`interface`、`struct` 四组 |

“全量”指选择四组名称；遇到无法确认的引用、只读文件或顶层接口边界时，工具会保留相关名称，不保证全部改名。

## 使用方法

### 1. 进入服务器

如果已经在可运行的服务器环境中，从第 2 步开始。以下资源参数按所在集群调整：

```sh
bsub \
  -q inta \
  -P ABC \
  -Is \
  -n 1 \
  -R "span[hosts=1] rusage[mem=65536]" \
  bash
```

### 2. 克隆仓库并选择分支

```sh
git clone https://gitlab.sunrise-ai.com/SenseGemini/RTL_ENDECRYPTOR.git
cd RTL_ENDECRYPTOR
```

快速加密执行 `git checkout delivery/fast-local-signals`；全量加密执行 `git checkout main`。运行 `git branch --show-current` 确认当前分支。

### 3. 准备 Python 环境

仓库内的 PySlang wheel 适用于 CPython 3.11、Linux x86_64：

```sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --no-index --no-deps \
  wheel/pyslang-11.0.0-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
```

### 4. 配置工程路径

```sh
export FILELIST=/absolute/path/to/project/design.f
export REWRITE=/absolute/path/to/project/src
export OUT=/absolute/path/to/output/gate_fast
```

`FILELIST` 指向原工程顶层 `.f` 文件；`REWRITE` 指向允许改写的自有 RTL 目录。两者建议使用绝对路径。`OUT` 是加密输出目录：父目录必须存在，`OUT` 本身在运行前不能存在。若 filelist 中使用了 `$NAME` 或 `${NAME}`，也要提前设置相应环境变量。

### 5A. 快速加密：`delivery/fast-local-signals`

```sh
python rtl_encrypt.py \
  --filelist "$FILELIST" \
  --rewrite-root "$REWRITE" \
  --category signals \
  --output-dir "$OUT"
```

快速路径要求只选择 `signals`，并且**不传 `--top` 或 `--encryption-rate`**。改成其他组合会离开快速路径。

### 5B. 全量加密：`main`

全量教程必须指定顶层模块。若已按第 2 步切到 `main`，只需设置 `TOP` 和新的 `OUT`：

```sh
export TOP=AIClusterWrapper
export OUT=/absolute/path/to/output/gate_full
python rtl_encrypt.py \
  --filelist "$FILELIST" \
  --rewrite-root "$REWRITE" \
  --top "$TOP" \
  --category all \
  --output-dir "$OUT"
```

把 `AIClusterWrapper` 换成工程的顶层 module 名。`all` 选择四组名称；`--top` 让工具按该顶层的层次闭包处理，并保留顶层对外接口边界。

### 6. 检查结果与恢复

```sh
cat "$OUT/encryption_summary.txt"
python rtl_decrypt.py \
  --map "$OUT/mapping.json" \
  --gate-dir "$OUT" \
  --output-dir "${OUT}_restored"
```

加密成功时退出码为 `0`，stdout JSON 中的 `summary.strict_compile_passed` 和 `summary.restored_byte_identical` 应为 `true`。`encryption_summary.txt` 汇总改名、保留和不支持对象数；`$OUT/design.f` 是加密后的编译 filelist。恢复目录 `${OUT}_restored` 在运行前也不能存在。

## 加密命令参数

| 参数 | 含义 |
| --- | --- |
| `--filelist "$FILELIST"` | 按原工程 filelist 读取源码和编译上下文 |
| `--rewrite-root "$REWRITE"` | 只允许改写此目录中的自有源码；多个自有目录可重复传入此参数 |
| `--top "$TOP"` | 全量教程必用：指定顶层模块，限定处理的层次闭包；快速路径不传 |
| `--category signals` / `--category all` | 前者选择快速局部信号；后者选择全量四组名称 |
| `--output-dir "$OUT"` | 写入新的输出目录；目录在运行前不能存在 |

更多加密边界见 [可加密名称类别](docs/systemverilog_renaming_table.md)，验证方法见 [Formal 验证说明](docs/formal_verification.md)。
