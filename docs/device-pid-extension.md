# 设备 PID 扩展

本文档说明如何在本集成中按设备 PID 扩展实体行为。所有扩展实现都放在
`custom_components/haier_home/extend/` 目录中，每个扩展文件**自包含**：
目标 PID（单个或列表）+ Entity 子类 + 自注册装饰器。新增或调整某个 PID
的行为时，只需在该目录下增删文件，**永远不需要修改任何现有文件**。

> 适用范围：截至当前版本，集成实现的 HA 平台为 `climate`（空调）与 `scene`
> （场景），其中**只有 `climate` 平台接入了本文所述的 PID 扩展机制**；`scene`
> 平台的实体（`scene.py` 的 `HaierScene`）直接继承 HA 基类，不经过注册表。
> 下文示例统一以 `climate` 为例。

## 核心思想

设备差异在 **Entity 层**处理。集成采用三级实体继承（详见 `README.md`）：

- **Level 1 `HaierDeviceEntity`**（`entity.py`）：所有设备共享逻辑——coordinator
  绑定、可用性、`get_value` / `send_command`，以及对 `valueRange` 的通用读写工具。
  它同时是**注册中心**，持有三张注册表并提供 `register` / `register_platform` /
  `create`。
- **Level 2 平台基类**（如 `climate.py` 的 `HaierClimateEntity`）：混入 HA 平台
  基类（`ClimateEntity`），提供该平台的默认实现，并用 `@register_platform("climate")`
  注册为整个平台的兜底类。
- **Level 3 PID 扩展**（`extend/*.py`）：按具体 PID 覆写差异，用
  `@HaierDeviceEntity.register(...)` 自注册。

平台入口通过 `HaierDeviceEntity.create()` 按 `(PID, 平台)` 自动选择正确的类。

## 自动发现机制

`extend/__init__.py` 提供 `load_extensions()`，遍历导入 `extend/` 下所有 `.py`
文件（`__init__.py` 除外），从而触发每个模块顶部的 `@register` 装饰器完成注册。
该文件**永不修改**：

```python
# extend/__init__.py（当前实现）
import importlib
from pathlib import Path

_current_dir = Path(__file__).parent
_loaded = False


def load_extensions() -> None:
    """Discover and import all extension modules (blocking; run in executor)."""
    global _loaded  # noqa: PLW0603
    if _loaded:
        return
    for _file in sorted(_current_dir.glob("*.py")):
        if _file.name != "__init__.py":
            importlib.import_module(f".{_file.stem}", package=__package__)
    _loaded = True
```

两点实现细节：

- **`_loaded` 幂等保护**：`load_extensions()` 只会真正执行一次，重复调用直接返回，
  避免重复导入。
- **必须在执行器线程中调用**：扫描目录与导入模块是阻塞操作，因此集成在
  `__init__.py` 的 `async_setup` 中通过执行器线程调用它，而不是在事件循环里：

  ```python
  # __init__.py -> async_setup
  from . import extend

  await hass.async_add_executor_job(extend.load_extensions)
  ```

## 注册与查找机制

`HaierDeviceEntity` 维护三张类级注册表：

| 注册表 | 键 | 写入方式 |
|--------|----|---------|
| `_specific_registry` | `(pid, platform)` | `@register("pid_x", platform)`（单个 PID，`str`） |
| `_generic_registry` | `(pid, platform)` | `@register([...], platform)`（PID 列表，`list`） |
| `_platform_registry` | `platform` | `@register_platform(platform)`（平台兜底） |

`register(pid, platform)` 根据参数类型决定写入哪张表（以下为省略类型标注与
docstring 的摘录，完整实现见 `entity.py`）：

```python
@classmethod
def register(cls, pid: str | list[str], platform: str):
    def decorator(entity_cls):
        if isinstance(pid, list):
            for p in pid:
                cls._generic_registry[(p, platform)] = entity_cls
        else:
            cls._specific_registry[(pid, platform)] = entity_cls
        return entity_cls

    return decorator
```

平台入口用 `create()` 按固定优先级查表，选出最终实体类（同为摘录）：

```python
@classmethod
def create(cls, coordinator, device, description, platform):
    key = (device.pid, platform)
    entity_cls = (
        cls._specific_registry.get(key)  # 1. 单个 PID 精确匹配
        or cls._generic_registry.get(key)  # 2. PID 列表（共享组）
        or cls._platform_registry.get(platform)  # 3. 平台级默认（Level 2）
        or cls  # 4. HaierDeviceEntity 兜底
    )
    return entity_cls(coordinator, device, description)
```

**关键规则**：`_specific_registry`（单个 PID）优先于 `_generic_registry`（PID 列表），
且与 import 顺序无关。这意味着某个 PID 可以从共享组中「脱离」而无需修改共享组。

平台侧的调用示例（见 `climate.py` 的 `async_setup_entry`）：

```python
entities.append(HaierDeviceEntity.create(coordinator, device, description=None, platform="climate"))
```

## 无需扩展的 PID

如果某个 PID 与平台级默认行为（Level 2，如 `HaierClimateEntity`）完全一致，
**无需创建任何扩展文件**。`create()` 会在前两级查表落空后，命中
`_platform_registry`，自动使用平台基类。

> 性能：三张注册表都是 `dict`，`dict.get()` 为 O(1)，即使上千 PID 也无性能影响。

## 场景一：单个 PID 特有扩展

发现某个 PID 与默认行为不一致时，新建一个文件单独处理。用 `@register("pid_x", ...)`
注册到 `_specific_registry`，只覆写与默认不同的部分：

```python
# extend/pid_x.py
from ..climate import HaierClimateEntity
from ..entity import HaierDeviceEntity


@HaierDeviceEntity.register("pid_x", "climate")
class PidXClimateEntity(HaierClimateEntity):
    """pid_x 特有扩展：模式编号与默认映射不同，只需覆写 MODE_NAME_MAP。"""

    # 注意：键必须是字符串——hvac_mode / hvac_modes 通过
    # MODE_NAME_MAP.get(str(v)) 查表。整数键将永远匹配不到，
    # 覆写会静默失效。
    MODE_NAME_MAP = {
        "0": "auto",
        "1": "cool",
        "2": "heat",
        "3": "dry",
        "6": "fan_only",
    }
```

> ⚠️ **字符串键注意**：`climate.py` 中所有对 `MODE_NAME_MAP` / `FAN_MODE_MAP`
> 的查表都使用 `map.get(str(value))`。若在扩展里写成整数键（`0: "auto"`），
> 查找 `"0"` 永远不命中，覆写形同虚设且不会报错。

## 场景二：多 PID 共享扩展

发现多个 PID 有共性后，整合为一个扩展。用 `@register([...], ...)` 传入 PID 列表，
注册到 `_generic_registry`。PID 列表定义在文件顶部，**新增 PID 只改这个列表**。

这也是当前仓库中已有的示例 `extend/common_ab.py`：

```python
# extend/common_ab.py（当前实现）
from ..climate import HaierClimateEntity
from ..entity import HaierDeviceEntity


@HaierDeviceEntity.register(["pid_common_a", "pid_common_b"], "climate")
class CommonABClimateEntity(HaierClimateEntity):
    """Climate entity with different mode mapping for PID A and B."""

    # 键必须是字符串（同上）。
    MODE_NAME_MAP = {
        "0": "auto",
        "1": "cool",
        "2": "heat",
        "3": "dry",
        "6": "fan_only",
    }
```

当 PID 列表较长时，建议把列表提到文件顶部作为常量，方便维护：

```python
# extend/common_group.py
from ..climate import HaierClimateEntity
from ..entity import HaierDeviceEntity

# PID 列表（新增 PID 只改这里）
PIDS_CLIMATE = ["pid_a", "pid_b", "pid_aa1", "pid_aa2"]


@HaierDeviceEntity.register(PIDS_CLIMATE, "climate")
class CommonGroupClimateEntity(HaierClimateEntity):
    """A/B 组共有的 Climate 扩展。"""

    MODE_NAME_MAP = {"0": "auto", "1": "cool", "2": "heat"}
```

## 演进过程

扩展体系的设计目标是让「特殊 → 共性 → 再特殊」的演进都能只靠增删 `extend/`
下的文件完成：

```
阶段1: 发现 pid_a 问题
       → 新建 pid_a.py，register("pid_a", ...)                 → _specific_registry

阶段2: 发现 pid_b 也有类似问题
       → 新建 pid_b.py，register("pid_b", ...)                 → _specific_registry

阶段3: 发现 a/b 共性，合并
       → 新建 common_ab.py，register(["pid_a", "pid_b"], ...)  → _generic_registry
       → 删除 pid_a.py / pid_b.py（或去掉其 register）
       → 注意：若不删旧文件，specific 优先级高于 generic，旧扩展仍会生效

阶段4: c/d/e 整合为另一组
       → 新建 common_cde.py，register(["pid_c", "pid_d", "pid_e"], ...)

阶段5: pid_a 需要脱离 ab 组，单独处理
       → 新建 pid_a.py，register("pid_a", ...)                 → _specific_registry
       → specific 优先于 generic，无需改 common_ab.py
```

**核心保证**：`_specific_registry`（单个 PID）优先于 `_generic_registry`（PID 列表），
与 import 顺序无关。PID 可以随时从共享组中「脱离」而不必修改共享组本身。

## 可覆写的能力

Level 3 扩展是标准的 Python 子类，可以覆写 Level 2 平台基类暴露的任意属性与方法。
以 climate 为例，常见覆写点包括：

- `MODE_NAME_MAP`：原始 `operationMode` 码 → HA `HVACMode` 名（键必须为 `str`）。
- `FAN_MODE_MAP`：原始 `windSpeed` 码 → HA `fan_mode` 键（键必须为 `str`）。
- 各类 `@property`（如 `current_temperature`、`supported_features`）与 `async_set_*`
  方法。

Level 1 `HaierDeviceEntity` 提供的通用工具可直接复用，避免在扩展里重复造轮子：

- `get_value(name)` / `send_command(**kwargs)`
- 数值范围：`get_number_value` / `get_number_min` / `get_number_max` /
  `get_number_step` / `to_command_value`
- 枚举：`get_enum_options` / `get_enum_items`
- 布尔：`get_bool_value` / `async_set_bool`
- 能力判断：`is_writable(name)` / `get_attribute(name)`

> 设计约定：像 `MODE_NAME_MAP` 这类带 HVAC 领域语义、且随 PID 变化的映射，
> 刻意放在 climate 平台/扩展类上，而不是集成级基类 `HaierDeviceEntity` 上——
> 因为其它平台并不共享这些语义。这正是 Level 3 的覆写点。

## 新增扩展的检查清单

1. 在 `extend/` 下新建一个文件，文件名语义化（单 PID 用 `pid_x.py`，共享组用
   `common_xxx.py`）。
2. 从 `..entity` 导入 `HaierDeviceEntity`，从对应平台模块（如 `..climate`）导入
   Level 2 基类。
3. 用 `@HaierDeviceEntity.register("pid", "platform")`（单个）或
   `@HaierDeviceEntity.register([...], "platform")`（多个）装饰你的子类。
4. 只覆写与默认不同的部分；映射表的键务必是 `str`。
5. **无需**修改 `extend/__init__.py` 或任何平台入口——自动发现会处理其余部分。
