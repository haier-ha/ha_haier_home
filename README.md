<p align="center">
  <img src="./custom_components/haier_home/brand/icon@2x.png" alt="Haier" width="200">
</p>

# Haier Smart Home - Home Assistant Integration

海尔智能家居 Home Assistant 集成，支持海尔空调设备的控制与状态同步。

## 功能特性

- ✅ OAuth2 认证
- ✅ WebSocket 实时状态同步
- ✅ 空调设备控制
  - 开关机
  - 模式切换（制冷/制热/除湿/送风/自动）
  - 温度调节
  - 风速控制
  - 室内温度显示
- ✅ 支持3种空调类型
  - 分体空调 (02)
  - 柜机空调 (03)
  - 商用空调 (0d)

## 安装方式

### 方式一：HACS（推荐）

1. 打开 Home Assistant
2. 进入 HACS > 集成
3. 搜索 "Haier Smart Home"
4. 点击安装

### 方式二：手动安装

```bash
cd /path/to/homeassistant/custom_components
git clone https://github.com/haier-ha/ha_haier_home.git haier_home
```

## 配置

1. 在 Home Assistant 中进入 **Settings** > **Devices & Services**
2. 点击 **Add Integration**
3. 搜索 **Haier Smart Home**
4. 按照向导完成海尔账号授权

## 语言行为

配置向导的「区域与语言」步骤提供 `language` 选项（中文 / English），它同时控制
两类内容：

- **云端返回数据语言**：作为 `Accept-Language` 请求头，决定设备名、家庭名、
  风险告知正文等接口数据的语言。
- **选语言之后的界面文案**：`oauth`、`homes` 以及选项流（重新同步等）页面的标题、
  描述、字段标签、selector 选项，会跟随该选项显示对应语言，**不依赖 HA 的全局
  前端语言**。该文案由内置文案表 `haier/flow_i18n.py` 提供，通过
  `description_placeholders` 与显式 selector label 注入。

约束与回退：

- 「风险告知 (eula)」「区域与语言 (region)」两步出现在选定语言**之前**，仍跟随 HA
  前端语言。由于集成仅提供 `en.json` 与 `zh-Hans.json`，**非简体中文环境会自动回退
  英文**。
- 风险告知正文语言按 HA 全局语言判定：简体中文 → 中文，其余（含英文及其它语言）
  → 英文。

> 维护提示：选语言之后页面的文案以 `haier/i18n/<lang>.json` 为准（由
> `haier/flow_i18n.py` 的 `translate()` 加载）；`strings.json` 与
> `translations/*.json` 中对应字段使用 `{占位符}`。详见
> `docs/config_flow_language_option_design.md`。

## 支持的设备

| 设备类型码 | 设备名称 | 说明 |
|-----------|---------|------|
| 02 | 分体空调 | 标准家用空调 |
| 03 | 柜机空调 | 大功率空调 |
| 0d | 商用空调 | 部分型号不支持室内温度 |

## 技术架构

> 当前已实现的 HA 平台：`climate`（空调）与 `scene`（场景），见 `const.py` 的 `PLATFORMS`。

```
custom_components/
└── haier_home/
    ├── __init__.py                 # 集成入口：协调器/扩展加载/平台转发
    ├── application_credentials.py  # OAuth Application Credentials 助手
    ├── climate.py                  # HA Climate 实体平台
    ├── config_flow.py              # 配置流程（OAuth + 区域/语言 + 同步选项）
    ├── const.py                    # 常量（域名、API 地址、PLATFORM 等）
    ├── device.py                   # 设备数据模型（HaierDevice / Attribute / ValueRange）
    ├── entity.py                   # 实体基类 HaierDeviceEntity（含 @register 装饰器）
    ├── icons.json                  # 平台图标定义
    ├── manifest.json               # HACS 清单
    ├── scene.py                    # HA Scene 实体平台
    ├── brand/                      # 品牌图标资源
    │   ├── icon.png
    │   └── icon@2x.png
    ├── extend/                     # PID 差异扩展（自动发现加载）
    │   ├── __init__.py             # load_extensions() 阻塞扫描入口
    │   └── common_ab.py            # 公共 PID 覆写示例
    ├── translations/               # HA 前端翻译
    │   ├── en.json
    │   └── zh-Hans.json
    └── haier/                      # 海尔 API 客户端包
        ├── __init__.py
        ├── coordinator.py          # 数据协调器：状态同步 + WebSocket 生命周期
        ├── flow_i18n.py            # 配置流语言文案 translate() 加载器
        ├── http_client.py          # REST API 客户端
        ├── oauth2.py               # OAuth2 实现
        ├── storage.py              # 本地持久化缓存
        ├── utils.py                # 通用工具函数（ID 生成等）
        ├── websocket_client.py     # WebSocket 客户端（实时状态/命令下发）
        └── i18n/                   # 配置流语言文案表
            ├── en.json
            └── zh.json

```

### 实体三级继承

设备差异在 **Entity 层**处理，`HaierDevice` 是纯数据容器（无需继承）：

- **Level 1 `HaierDeviceEntity`**（`entity.py`）：所有设备共享逻辑——coordinator 绑定、
  可用性、`get_value` / `send_command`，以及对 `valueRange` 的通用读写工具
  （数值上下限/步长、枚举选项、布尔读写）。
- **Level 2 平台基类**（如 `climate.py` 的 `HaierClimateEntity`）：混入 HA 平台基类，
  提供该平台默认实现。
- **Level 3 PID 扩展**（`extend/*.py`）：按具体 PID 覆写差异，用
  `@HaierDeviceEntity.register(...)` 自注册。

平台入口通过 `HaierDeviceEntity.create()` 按 `(PID, 平台)` 自动选择正确的类，
查找优先级为 specific → generic → platform → 基类。

## 开发指南

### 按 PID 扩展实体

发现某个 PID 与平台默认行为不一致时，在 `extend/` 下新建一个自包含文件即可，
**无需修改任何现有文件**（`extend/__init__.py` 会自动发现并加载）：

```python
# custom_components/haier_home/extend/pid_x.py
from ..climate import HaierClimateEntity
from ..entity import HaierDeviceEntity


@HaierDeviceEntity.register(["pid_x"], "climate")
class PidXClimateEntity(HaierClimateEntity):
    """仅覆写与默认不同的部分。"""

    # 注意：键必须是字符串——查表通过 MODE_NAME_MAP.get(str(v)) 进行，
    # 整数键将永远匹配不到，覆写会静默失效。
    MODE_NAME_MAP = {
        "0": "auto",
        "1": "cool",
        "2": "heat",
    }
```

若某 PID 与平台默认行为完全一致，则无需创建任何扩展文件。

## 许可证

Apache License 2.0

## 贡献

欢迎提交 Issue 和 Pull Request！