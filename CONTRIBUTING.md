# 贡献指南（Contributing）

感谢你愿意为 Haier Home 集成做贡献。以下约定用于保证协作顺畅与代码质量一致。

## 本地开发环境

- Python 3.14+
- 安装开发依赖：`pip install -e ".[dev]"`（或在项目内虚拟环境中执行）
- 运行测试：`python -m pytest tests/`
- 代码风格检查：`ruff check .`

## 代码结构

```
custom_components/haier_home/
├── __init__.py            # 组件入口与平台加载
├── const.py               # 常量、端点与设备类型映射
├── climate.py             # 空调平台
├── coordinator.py         # 数据协调器：令牌刷新与 WebSocket 生命周期
├── config_flow.py         # 配置向导
└── haier/
    ├── http_client.py     # 云 API 客户端
    ├── websocket_client.py# 实时状态 WebSocket 客户端
    └── oauth2.py          # OAuth2 认证
```

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
