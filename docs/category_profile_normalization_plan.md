# 单-module / 多-module Category 统一实现方案

- 文档状态：`IN_PROGRESS`
- 适用入口：单文件、显式 filelist、`project-root + top`
- 当前基线：T027–T034 `ACCEPTED`
- 当前任务：T035 `IN_PROGRESS`，filelist/project-root 默认与手动 profile 统一；T033/T034 已完成

## 1. 目标

将加密对象按语义影响范围分为 `single_module` 和 `multi_module` 两类，并统一单文件、
显式 filelist、`project-root + top` 的用户 category 语义：

- 默认 profile 只选择 `single_module` 且非 ABI 的对象；
- `multi_module` 或 ABI 对象只能在确认 top context 后手动选择；filelist 使用显式 filelist 内
  bounded closure，project-root 使用自动发现 closure；
- filelist 默认编译和输出所有列出的文件，但只修改其中符合默认 profile 的 ranges；手动 profile
  只修改 filelist bounded closure，closure 外文件镜像并记录 skipped；
- project-root 只输出 top 的依赖闭包，再按默认或手动 profile 修改闭包内对象。

## 2. 影响与 ABI 是两个正交维度

不能只按 category 名称判断影响范围。每个 inventory entry 应计算：

```text
impact: single_module | multi_module
abi: internal | cross_module | top_abi
```

`impact` 根据声明和所有语义引用涉及的 module owner 集合计算；`abi` 根据对象是否改变
module/port/interface/top 外部名称契约计算。默认 profile 要求：

```text
impact == single_module && abi == internal
```

top module、top ports、top interface ABI 和 top value parameter 即使 impact 为
`single_module`，也必须保持 `top_abi` preserved。

## 3. Category policy oracle

### 3.1 默认候选

下列 category 通常属于默认 profile：

```text
signals
enum_values
genvars
functions
tasks
arguments
generate_blocks
typedefs            # 仅 module-scoped/local
struct_types        # 仅 module-scoped/local
struct_fields       # 仅 module-scoped/local
union_fields        # 仅 module-scoped/local
instances           # 当前只改本 module declaration；hierarchical reference 仍不支持
```

`parameters` 必须逐 entry 分类：`localparam` 和只在 owner module 内引用的参数可以进入
默认 profile；named override、跨 module RHS/引用或外部 ABI 风险使其变为 `multi_module`
或 `top_abi`。T033 冻结的具体 oracle 见任务单。

### 3.2 两入口手动类别

下列类别默认不启用，只有 filelist/project-root 手动 profile 在确认 closure 后才允许改写：

```text
modules
ports
interfaces
interface_instances
interface_ports
modports
```

共享 compilation-unit 类型、跨 module parameter override、跨 module aggregate field 和
存在外部层次引用的 instance 也归入 `multi_module`，即使其底层 category 名称本身属于
默认候选。

### 3.3 Category ownership

一个 physical identifier range 只能属于一个 category。特别是 interface port/member
不能同时作为普通 `ports`、`interface_instances` 或 `interface_ports` occurrence 输出。
T033 必须冻结并验证这种 disjoint ownership，否则组合 profile 会产生 duplicate ranges。

## 4. 统一 CLI/profile

建议保留现有底层 category 名称和 mapping category，增加共享 registry：

```text
all = 默认 single_module profile
```

- 单文件：`all` 及显式默认 category；multi/ABI category 拒绝；
- filelist：默认 profile 与单文件相同；手动 multi/ABI category 使用显式 filelist 内
  `--top` 建立 bounded closure，缺失依赖时事务性失败；
- project-root：默认使用同一 profile，可额外显式选择 multi/ABI category；top 始终必需；
- `--debug`：默认只遍历 single-module profile；multi/ABI 类别使用普通 project-root 命令
  单独验收。

旧 project-root 的 `struct`、`interface` 概念组保留为共享 registry alias，registry 的 canonical
category 仍是实际底层 category。manual workflow 使用 mapping v4；旧 v1/v2/v3 mapping 继续只读
支持 decrypt。

## 5. Mapping/metrics 方案

T035 的 normalized workflow 使用 mapping v4，记录：

```json
{
  "version": 4,
  "profile": "single_module",
  "mode": "filelist",
  "requested_categories": [],
  "selected_categories": [],
  "entries": [],
  "preserved": [],
  "skipped": []
}
```

`skipped` 必须记录默认/手动 profile 跳过的 out-of-closure、multi-module、ABI、macro 和
unsupported 对象及稳定 reason。旧 mapping 只读兼容，不回写旧 schema。

## 6. 分阶段任务

| 任务 | 目标 | RTL | Formal |
| --- | --- | --- | --- |
| T033 | impact classifier、category registry、ownership 和 oracle | 否 | N/A |
| T034 | 单文件/filelist 默认 profile、file scope、multi/ABI fail-closed | 是 | 必须 PASS/FAIL 正负例 |
| T035 | filelist/project-root default/manual profile 统一、bounded manual closure、跨 module parameter/ABI | 是 | 必须 PASS/FAIL 正负例 |
| T037 | RISC-V-Vector Formal 验收与 `encrypt.py` 演示脚本 | 是 | 必须 PASS/FAIL 正负例 |
| T038 | 条件性默认 profile 晋级与 oracle 重冻结 | 是 | 复用 T037 |

T033 完成前不得修改 T030/T032 默认数量或历史合同。T034/T035 通过后再更新用户文档和
FIFO/RISC-V-Vector 数字；历史任务单保留当时的事实。

## 7. 共同验收要求

必须验证：

1. filelist 默认改写所有列出文件中的 single-module ranges；
2. filelist 默认 profile 不改写 multi-module/ABI ranges，并输出可审计 skip；filelist 手动 profile
   在 bounded closure 内可改写已绑定的 multi-module/ABI ranges；
3. project-root 默认只改写 top closure；
4. filelist/project-root 手动 profile 可改写各自确认 closure 内 multi-module ranges，但 top ABI 保持；
5. category ranges 不重叠，mapping ranges 与 gold/gate bytes 精确一致；
6. gate strict reanalysis、decrypt byte identity、metrics coverage 和 formal 正负例通过；
7. legacy v1/v2/v3 decrypt 回归保持通过；
8. filelist 与 project-root 使用相同 canonical category/profile 名称。

## 8. 停止条件

遇到无法确认 module owner、interface port ownership、parameter override binding、外部
hierarchical reference 或 shared type scope 时，必须输出 preserved/unsupported，不能按文本
名称猜测，也不能把 multi-module 对象降级为默认 single-module。
