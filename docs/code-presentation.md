# Haier Home 项目代码介绍

> 本文档对 Haier Home 项目代码进行整体介绍，帮助读者快速理解项目的定位、架构与核心实现逻辑。

---

## 目录

1. [项目概述](#1-项目概述)
2. [技术栈与规模](#2-技术栈与规模)
3. [整体架构总览](#3-整体架构总览)
4. [核心数据流](#4-核心数据流)
5. [设计要点](#5-设计要点)
6. [模块级实现说明](#6-模块级实现说明)
7. [测试与质量保障](#7-测试与质量保障)

---

## 1. 项目概述

本项目是一个运行在 **Home Assistant（HA，开源智能家居中枢）** 平台上的**第三方集成（HACS 自定义组件）**。

它的作用是：把**海尔智能家居云**（空调、场景）接入 HA，使用户可以在 HA 中**查看空调状态、控制空调、执行场景**，并实现**实时同步**——手机端海尔 App 对设备状态的修改，HA 侧同步更新；HA 侧的操作，也能下发到海尔云。

**项目三个核心特征：**
- **桥接**：不实现设备底层协议，而是在 HA 与海尔云之间完成协议适配与转换。
- **实时**：通过 **WebSocket 长连接**接收设备状态推送，而非轮询获取。
- **可扩展**：同一套框架支持不同类型设备，新增设备只需补充差异配置即可。

**一句话总结**：本项目本质上是"海尔云协议"与"Home Assistant 实体模型"之间的一张适配层，同时承载认证、缓存、实时同步与扩展性。

---

## 2. 技术栈与规模

**技术栈**
| 项 | 说明 |
|----|------|
| 语言/运行时 | Python / asyncio（异步主导） |
| 宿主框架 | Home Assistant 集成规范（config_entry、entity、标准 HA platforms） |
| 网络 | aiohttp（REST + WebSocket），OAuth2 认证 |
| 数据模型 | dataclass 纯数据容器，无 ORM |
| 分发 | HACS（Home Assistant Community Store 自定义集成） |
| 测试 | pytest + unittest.mock（mock HA 环境，无真实设备/网络依赖） |

**规模**（约 11600 行）
- 生产代码约 **3900 行**（12 个核心模块）
- 测试代码约 **5500+ 行**（21 个测试文件）
- 测试/生产代码比例约 **1.4:1**

**核心目录结构**
```
custom_components/haier_home/
├── __init__.py            # 集成入口：装配协调器、事件总线、启动/卸载
├── const.py               # 常量与配置（region/API端点/平台清单/选项）
├── config_flow.py         # 配置向导（EULA→选区域→OAuth→选家庭→选项）
├── device.py              # 数据模型层：Attribute / ValueRange / HaierDevice
├── entity.py              # 实体基类 + 三级继承注册表机制
├── climate.py             # HA climate（空调）平台实现
├── scene.py               # HA scene（场景）平台实现
├── application_credentials.py  # OAuth 应用凭据注册
├── extend/                # 按 PID 的设备差异扩展（自动发现加载）
└── haier/                 # 云连接内核
    ├── coordinator.py     # 协调器：WS连接/重连/token刷新/命令下发
    ├── http_client.py     # REST 客户端（签名、错误码）
    ├── websocket_client.py# WebSocket 客户端（心跳/订阅/命令）
    ├── oauth2.py          # OAuth2 实现
    ├── storage.py         # 本地持久化缓存（重启后保留）
    └── flow_i18n.py       # 配置向导多语言
tests/                     # 21 个测试文件
```

---

## 3. 整体架构总览

整体架构可以概括为 **三层结构 + 一条实时数据通道贯穿**：

```
                        ┌────────────────────────────────────────────┐
                        │          Home Assistant (宿主)             │
                        │   climate 实体   │   scene 实体  │ ...      │
                        └───────────────────┬────────────────────────┘
                                            │  read / write 实体属性
                        ┌───────────────────▼────────────────────────┐
  【平台实体层】         │  HaierClimateEntity / HaierScene            │
  （HA 实体入口，        │  （将 HA 标准属性 ↔ 设备指令翻译）            │
   差异收敛点）          └───────────────────┬────────────────────────┘
                                            │  get_value / send_command
                        ┌───────────────────▼────────────────────────┐
  【能力抽象层】         │  HaierDeviceEntity (基类+注册表)             │
  （共享读/写/映射）     │  三级继承：基类→平台→PID扩展                  │
                        └───────────────────┬────────────────────────┘
                        ┌───────────────────▼────────────────────────┐
  【接入/数据层】        │  HaierCoordinator（协调器）                  │
  （状态中枢）           │  持有 HaierDevice 列表，统一对外提供状态      │
                        │      │                        ▲              │
                        │  HTTP 客户端             WebSocket 客户端    │
                        │  （REST 拉取模型）         （实时推送+命令下行）│
                        │  oauth2 / storage(缓存)    心跳/重连/token    │
                        └──────┬─────────────────────────┬────────────┘
                               │                         │
                        ┌──────▼─────────────┐   ┌───────▼────────────┐
                        │  海尔云 REST API     │   │ 海尔云 WebSocket   │
                        │  （设备清单/数字模型/  │   │ （状态推送 + 命令） │
                        │   家庭/场景）         │   │                   │
                        └────────────────────┘   └────────────────────┘
```

**各层职责：**
- **接入/数据层**：负责与云端连接——认证、REST 拉取、WebSocket 推送、缓存、重连。该层通晓海尔云协议。
- **能力抽象层**：描述"设备长什么样"——将云端"数字模型"（attributes / valueRange）统一为业务对象，提供通用读/写/映射工具，并通过注册表机制收敛设备差异。
- **平台实体层**：负责"设备如何出现在 HA 中"——将业务对象翻译为 HA 的 climate/scene 实体属性，使 HA 生态（UI、自动化、语音）无感接入。

三层相互独立、职责清晰：协议的变更只影响接入层，设备型号的增加只涉及能力层扩展，新增 HA 实体类型只涉及平台层。

---

## 4. 核心数据流

### 4.1 控制流（下行）：在 HA 中调节空调温度到 26 度

```
HA climate 实体.async_set_temperature(temperature=26)
   │  climate.py 通过 MODE_NAME_MAP / to_command_value 将 UI 值转为云端指令值
   ▼
send_command(targetTemperature="26")
   │  entity.py：转发给协调器（带 device_id + 指令 dict）
   ▼
HaierCoordinator.async_send_command(device_id, {targetTemperature:"26"})
   │  组装 BatchCmdReq 载荷：{deviceId, index, cmdArgs:{...}}
   ▼
HaierWebSocketClient.send_command(cmd_list)
   │  通过带 token 的 wss 长连接发送 JSON
   ▼
海尔云 → 设备执行 → 回推状态（触发上行流）
```

### 4.2 状态流（上行）：设备状态变化 → HA 界面更新

```
海尔云 WebSocket 推送 GenMsgDown 消息
   │  content.data 为 base64 → 解出 JSON → args 可能为 gzip(base64)
   ▼
coordinator._handle_gen_msg_down 解析
   │  将"云端的 args.attributes"扁平化为统一信封 {"data":[{name,value},...]}
   ▼
HaierDevice.async_on_message(...)   // 设备模型逐条更新 Attribute
   │  Attribute.update() 仅选择性更新出现字段，未知字段忽略
   ▼
coordinator._notify_listeners()      // 通知所有实体
   ▼
实体.async_write_ha_state()          // HA 界面刷新
```

**核心价值**：云端推送格式（base64 / gzip / 各种嵌套结构）的适配集中在 coordinator 一处完成，下游 device/entity 拿到的是统一、干净的格式，实现了协议格式与业务逻辑的解耦。

---

## 5. 设计要点

### 5.1 实体三级继承 + 注册表机制 —— 以"差异"而非"分支"扩展设备

- **机制**：新增与当前型号行为不同的设备时，**无需修改任何现有文件**，只需在 `extend/` 下新建一个自包含的 `.py` 文件并注册（见 [extend/common_ab.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/extend/common_ab.py)）。
- **实现**：`entity.py` 维护三个注册表——specific（某 PID）/ generic（一组 PID）/ platform（整平台——见 [entity.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/entity.py#L81-L104)）。创建实体时按 **specific → generic → platform → 基类** 优先级查找。
- **价值**：设备差异从"散落的 if/else"收敛为"声明式覆写"，体现开闭原则（OCP）。新设备接入成本从"改代码"降为"加文件"。

### 5.2 纯数据模型与协议格式解耦 —— "数字模型"驱动一切

- [device.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/device.py) 通过一组 dataclass（`Attribute`/`ValueRange`/`DataStep`…）将海尔云"数字模型"结构化为纯数据容器，不含协议逻辑。
- **数字模型优先**：设备属性、可读可写、取值范围均**来自云端下发的模型**而非硬编码。海尔云新增属性时，集成可自动支持，几乎无需改代码。
- **ValueRange 统一建模**：将云端的 NONE/LIST/STEP/TIME/DATE 五种值域统一建模，`Attribute.is_numeric/is_enum/is_bool` 成为通用判断（见 [device.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/device.py#L206-L228)）。

### 5.3 WebSocket 实时推送 + 三层健壮性保障

- 实时状态通过 WebSocket 长连接接收（[websocket_client.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/haier/websocket_client.py)），coordinator 提供三层修复机制：
  1. **心跳**（60s）：保活并检测连接质量；
  2. **指数退避重连**（10s→最多 300s）：应对断线（见 [coordinator.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/haier/coordinator.py#L400-L473)）；
  3. **Token 提前刷新**（到期前 5 分钟触发，每天检查）：避免因 token 过期导致连接失效（见 [coordinator.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/haier/coordinator.py#L221-L259)）。

### 5.4 Cloud-first + 本地缓存兜底 —— 重启不掉状态

- HA 服务重启时内存全部清空。[storage.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/haier/storage.py) 将设备清单与数字模型持久化到 `config/.storage`，重启后保留。
- **策略**：**优先从云端拉取**（保证拿到最新数据与设备增删），**云端不可达时回退到缓存**（避免重启后界面为空）。同时区分"网络不可达 → 设备标离线"与"接口报错 → 保留在线标志"两种情形（见 [__init__.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/__init__.py#L147-L199)）。
- **价值**：在"体验（重启秒开）"与"正确性（不丢云端变更）"之间取得平衡。

---

## 6. 模块级实现说明

### 6.1 device.py —— 数据模型层

- **职责**：将云端数字模型解析为结构化对象，纯数据、无 I/O。
- **关键实现**：
  - `parse_digital_model()` 兼容云端多种响应结构（直接 list / attributes / data.attributes…），并同时支持 snake_case 与 camelCase 字段。
  - `Attribute.update()` 采用**选择性更新**：仅更新 WebSocket 推送中出现过的字段，未知字段忽略，保证向前兼容。
  - `Transform`：云端声明了 `y=kx+c` 线性变换，但实测读写值都在同一标尺上，应用变换反而出错。代码**有意不应用 transform，但保留解析用于诊断**，并记录了实测证据（见 [device.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/device.py#L30-L62)）。
- **边界处理**：对非法/越界值做防御式处理（`out_of_range`、`_coerce`），异常 payload 不导致崩溃。

### 6.2 entity.py —— 能力抽象层

- **职责**：承载所有设备实体的公共逻辑与设备差异注册表。
- **关键实现**：
  - 提供通用 valueRange 读写工具：`get_number_value/min/max/step`、`get_enum_options/items`、`get_bool_value`、`to_command_value`、`async_set_bool`，避免各平台重复实现。
  - `available` 由"**设备在线 && 协调器已连接**"共同决定（见 [entity.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/entity.py#L150-L153)），将"设备"与"通道"两个可用性维度解耦。
  - `_attr_unique_id` 由 region + device_id + 实体 key 组成，保证跨家庭/账户不冲突（`test_entry_uuid_redundancy.py` 覆盖）。
  - `async_added_to_hass` 注册监听，`async_will_remove_from_hass` 反注册，避免实体残留监听。

### 6.3 climate.py —— 空调平台

- **职责**：将 HA 标准空调模型（HVACMode/HVACAction/temp/fan）翻译为海尔设备特性。
- **关键实现**：
  - 双映射表 `MODE_NAME_MAP`（operationMode 码 ↔ HA 模式）与 `FAN_MODE_MAP`（windSpeed 码 ↔ 风量），并**优先使用设备自身枚举**反查可发送的码（`_resolve_operation_mode_value`），避免发送设备不支持的码（见 [climate.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/climate.py#L279-L297)）。
  - **动态兜底**：风量码若无静态映射，使用云端枚举的 `desc` 兜底，未知风速不丢失（见 [climate.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/climate.py#L189-L216)）。
  - `hvac_action` 由模式推断得到（设备不单独上报压缩机状态）；AUTO 模式如实返回"未知"，不作误导性推断（见 [climate.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/climate.py#L118-L140)）。
  - `supported_features` 依据设备属性是否可写（如 targetTemperature / windSpeed）动态给出，不写死。
- **边界**：越界温度按"无设定值"处理，避免哨兵值显示为假读数。

### 6.4 scene.py —— 场景平台

- **职责**：将海尔云"手动场景"暴露为 HA 的 Scene 实体。
- **关键实现**：
  - 场景为**无状态**实体，每次激活都调用云端 `execute_scene`（携带 family_id + scene_id）（见 [scene.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/scene.py#L103-L131)）。
  - 场景无物理设备，通过实体注册表自动挂到以"家"命名的区域，且**仅在无区域时填充**，尊重用户后续手动设置（见 [scene.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/scene.py#L76-L101)）。
  - **孤儿清理**：当取消选家、关闭场景同步或云端删除场景时，计算"应存在"的 unique_id 集合，自动移除已过期的 scene 实体，避免失效实体堆积（见 [scene.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/scene.py#L163-L184)）。

### 6.5 coordinator.py —— 协调器（状态中枢 + 生命周期）

- **职责**：持有设备列表；管理 WebSocket 连接/重连/心跳/token；命令下发；向实体广播状态变化。
- **关键实现**：
  - **生命周期严谨**：`async_start` / `async_stop` 通过 `_stopped` 标志使所有后台协程（连接/重连/token 刷新）优雅退出，并使用 `wait_for(timeout=10)` 避免阻塞（见 [coordinator.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/haier/coordinator.py#L504-L547)）。
  - **监听器模式**：`async_add_listener` 注册实体回调，状态变化时通过 `_notify_listeners()` 广播，实体与 coordinator 保持松耦合。
  - **协议封装**：`_handle_gen_msg_down` 完成 base64 → JSON →（gzip）解包，并将扁平化数据交给设备模型。
  - **token 刷新联动 WS**：刷新后同步更新 HTTP client 与 WS client 的 token 并重连，避免长连接因 token 失效。

### 6.6 http_client.py / websocket_client.py / oauth2.py —— 云连接层

- **http_client**：统一 REST 调用、SHA-256 签名、`retCode` 业务码校验（非 `00000` 抛 `HaierAPIError`）、单例 session 复用 + 双重锁防止并发建会话。
- **websocket_client**：管理 wss 连接、`BoundDevs`（登记设备订阅）、`HeartBeat`/`HeartBeatAck`（sn 序号核对）、`BatchCmdReq`（命令），并通过 `generate_sn` 序号贯穿。
- **oauth2**：复用 HA 的 OAuth2 框架（`AbstractOAuth2Implementation`），authorization code / refresh_token 两段式，token 存入 config entry。

### 6.7 config_flow.py —— 配置向导

- **流程**：EULA/风险告知 → 区域与语言 → OAuth 授权 → 选家庭 → 房间同步/场景同步选项。重新同步设备/场景直接使用 HA 内置的「重新加载」（云端优先重新拉取），不再单独提供 OptionsFlow。
- **多语言**：通过 [flow_i18n.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/haier/flow_i18n.py) 的 `translate()` 加载 `haier/i18n/<lang>.json`，使"选语言之后的界面文案"跟随所选语言，不依赖 HA 全局语言；选语言前的步骤（EULA/区域）跟随 HA 全局语言。
- **风险告知**：首次拉取云端风险告知正文供用户确认，失败则中止（`risk_notice_error`）。

### 6.8 extend/ —— PID 扩展

- [extend/__init__.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/extend/__init__.py) 的 `load_extensions()` 自动 `importlib` 加载 `extend/*.py`（扫描目录/导入这类阻塞操作放到 executor 线程，不阻塞事件循环）。
- 示例 [common_ab.py](file:///Users/user/Documents/code_base/ha_haier_home/custom_components/haier_home/extend/common_ab.py) 演示了"同平台、不同 PID、不同模式映射"的覆写范式。

---

## 7. 测试与质量保障

- **测试规模**：21 个测试文件、5500+ 行，覆盖所有核心模块（device/entity/climate/scene/coordinator/http/ws/oauth/storage/config_flow/init）。
- **纯 mock、无外部依赖**：`conftest.py` 使用 `unittest.mock` mock 掉 Home Assistant 环境（Entity、ClimateEntity、OAuth2、aiohttp、registry…），测试**不依赖真实网络/设备/HA 实例**，可离线稳定运行（见 [conftest.py](file:///Users/user/Documents/code_base/ha_haier_home/tests/conftest.py)）。
- **重点回归测试**：
  - `test_climate_registration.py`：验证三级继承 + 注册表查找优先级（specific→generic→platform→基类）。
  - `test_entry_uuid_redundancy.py`：多家庭/账户下 unique_id 不冲突。
  - `test_risk_notice_mapping_regression.py`：多语言的回归防护。
  - `test_coordinator.py`（1098 行）：覆盖协调器连接/重连/token/命令下发等核心逻辑。
- **工程质量**：CI（`.github/workflows/` 含 HACS + hassfest 官方校验）、`pre-commit`、`quality_scale.yaml`（HA 官方质量评级）、严格类型（`py.typed`）、大量中文注释说明"为什么"。
