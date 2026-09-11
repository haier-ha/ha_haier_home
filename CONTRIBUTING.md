# 贡献指南（Contributing）

感谢你愿意为 Haier Smart Home 集成做贡献。以下约定用于保证协作顺畅与代码质量一致。

## 本地开发环境

环境搭建、测试、lint、pre-commit 等完整命令见 [`DEVELOPER.md`](DEVELOPER.md)。快速上手：

```bash
pip install -e ".[dev]"   # 安装开发依赖（等价于 requirements_dev.txt）
python -m pytest tests/    # 运行测试
ruff check .               # 代码风格检查
```

## 代码结构

```
custom_components/haier_home/
├── __init__.py                 # 集成入口：协调器 / 扩展加载 / 平台转发
├── application_credentials.py  # OAuth Application Credentials 助手
├── climate.py                  # HA Climate 实体平台（空调）
├── config_flow.py              # 配置向导（OAuth + 区域/语言 + 同步选项）
├── const.py                    # 常量（域名、API 地址、PLATFORMS、DEVICE_TYPE_MAP 等）
├── device.py                   # 设备数据模型（HaierDevice / Attribute / ValueRange）
├── entity.py                   # 实体基类 HaierDeviceEntity（含 @register 装饰器）
├── scene.py                    # HA Scene 实体平台（场景）
├── icons.json                  # 平台图标定义
├── manifest.json               # HACS 清单
├── brand/                      # 品牌图标资源（icon.png、icon@2x.png）
├── extend/                     # 按 PID 的差异扩展（自动发现加载）
│   ├── __init__.py             # load_extensions() 阻塞扫描入口
│   └── common_ab.py            # 公共 PID 覆写示例
├── translations/               # HA 前端翻译
│   ├── en.json
│   └── zh-Hans.json
└── haier/                      # 海尔 API 客户端包
    ├── __init__.py
    ├── command_debouncer.py    # 命令去抖（合并短时间内的重复下发）
    ├── coordinator.py          # 数据协调器：令牌刷新 + WebSocket 生命周期
    ├── flow_i18n.py            # 配置流语言文案 translate() 加载器
    ├── http_client.py          # 云 API 客户端
    ├── oauth2.py               # OAuth2 认证
    ├── storage.py              # 本地持久化缓存
    ├── utils.py                # 通用工具函数（ID 生成等）
    ├── websocket_client.py     # 实时状态 WebSocket 客户端
    └── i18n/                   # 配置流语言文案表
        ├── en.json
        └── zh-Hans.json
```

> 完整架构说明（平台优先级、PID 扩展机制等）见 `README.md` 的「技术架构」与「开发指南」。

## 开发约定

- **先写测试，再写实现**：新增或修改行为时，先在 `tests/` 中补对应用例。
- **只描述当前实现**：注释与 docstring 精简、只说明当前行为与设计意图，不带历史变更过程。
- **安全红线**：不要提交内部/验收环境地址、测试端点、账号、企业内网路径等敏感信息；内部文档应放入 `docs/internal/`（已被 `.gitignore` 忽略）。

## 提交规范

采用 [Conventional Commits](https://www.conventionalcommits.org/)，提交信息用中文描述（与仓库历史一致）：

- `feat:` 新功能
- `fix:` 缺陷修复
- `chore:` 构建、依赖、仓库杂项
- `docs:` 文档
- `refactor:` 不影响行为的重构
- `perf:` 性能优化
- `test:` 测试

示例：`fix(climate): 修正非原生单位下温度边界`

## Pull Request 流程

1. 从最新的 `master` 创建功能分支。
2. 实现并补齐测试，本地通过 `pytest` 与 `ruff`。
3. 提交、推送，并创建 Pull Request 到 `master`。
4. 保持 PR 聚焦单一改动，便于评审与回滚。
