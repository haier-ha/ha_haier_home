# Haier Home Integration - Developer Guide

本文档介绍如何设置开发环境、运行测试和使用代码检查工具。

## 环境要求

- Python 3.14+
- Home Assistant Core 2026.5+
- Conda (推荐) 或其他虚拟环境管理工具

## 开发环境设置

### 使用 Conda

```bash
# 创建并激活虚拟环境
conda create -n ha_dev python=3.14 -y
conda activate ha_dev

# 安装开发依赖
pip install -r requirements_dev.txt
```

### 使用 venv

```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境 (Linux/macOS)
source .venv/bin/activate

# 激活虚拟环境 (Windows)
.venv\Scripts\activate

# 安装开发依赖
pip install -r requirements_dev.txt
```

## 代码检查 (Ruff)

### 运行 Lint 检查

```bash
# 检查所有 Python 文件
python -m ruff check custom_components/haier_home/

# 检查并自动修复可修复的问题
python -m ruff check custom_components/haier_home/ --fix

# 检查特定文件
python -m ruff check custom_components/haier_home/climate.py
```

### 代码格式化

```bash
# 格式化所有 Python 文件
python -m ruff format custom_components/haier_home/

# 格式化特定文件
python -m ruff format custom_components/haier_home/climate.py
```

### 配置说明

Ruff 的配置位于 `pyproject.toml` 文件中：

```toml
[tool.ruff]
required-version = ">=0.15.1"
line-length = 88
target-version = "py314"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "C4", "UP", "PL", "SIM", "RET", "BLE", "SLF", "TRY"]
ignore = [
    "E501",  # 行太长
    "B006",  # 危险的默认值
    "C901",  # 函数太复杂
    # ... 其他忽略规则
]
```

## Git Pre-commit 钩子

### 安装 Pre-commit

```bash
# 安装 pre-commit 工具
pip install pre-commit

# 安装钩子到项目
pre-commit install

# 更新钩子版本
pre-commit autoupdate
```

### 配置文件

配置文件位于 `.pre-commit-config.yaml`，包含以下钩子：

- `ruff-check`: Ruff 代码检查
- `ruff-format`: Ruff 代码格式化
- `codespell`: 拼写检查
- `check-json`: JSON 文件格式检查
- `yamllint`: YAML 文件格式检查
- `prettier`: 通用代码格式化
- `mypy`: 类型检查
- `pytest`: 单元测试

### 手动运行所有钩子

```bash
# 运行所有钩子检查所有文件
pre-commit run --all-files

# 运行特定钩子
pre-commit run ruff-check

# 跳过某个钩子
SKIP=prettier pre-commit run --all-files
```

## 单元测试

### 运行所有测试

```bash
# 运行所有测试
python -m pytest tests/ -v

# 运行特定测试文件
python -m pytest tests/test_climate.py -v

# 运行特定测试类或方法
python -m pytest tests/test_climate.py::TestClimateModeMaps -v
python -m pytest tests/test_climate.py::TestClimateModeMaps::test_mode_name_map_values -v

python -m pytest tests/ --cov=custom_components.haier_home --cov-report=term-missing --tb=no
```

### 测试配置

测试配置位于 `pyproject.toml` 文件中：

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = ["-v", "--tb=short", "--asyncio-mode=auto"]
```

### 测试覆盖率

```bash
# 运行测试并生成覆盖率报告
python -m pytest tests/ --cov=custom_components/haier_home --cov-report=term-missing

# 生成 HTML 覆盖率报告
python -m pytest tests/ --cov=custom_components/haier_home --cov-report=html
```

## 静态类型检查 (Mypy)

```bash
# 运行类型检查
python -m mypy custom_components/haier_home/

# 配置文件位于 pyproject.toml
```

## 开发工作流程

1. **创建分支**: `git checkout -b feature/my-feature`
2. **编写代码**: 实现功能或修复 Bug
3. **运行检查**:
   ```bash
   python -m ruff check custom_components/haier_home/ --fix
   python -m pytest tests/
   ```
4. **提交代码**: 提交前 pre-commit 会自动运行检查
5. **创建 PR**: 推送分支并创建 Pull Request

## 调试技巧

### 在 Home Assistant 中调试

```bash
# 将集成链接到 HA 配置目录
ln -s $(pwd)/custom_components/haier_home /path/to/ha-config/custom_components/

# 启用调试日志
logger:
  default: info
  logs:
    custom_components.haier_home: debug
```

## 常用命令汇总

| 命令 | 说明 |
|------|------|
| `python -m ruff check .` | 运行 Lint 检查 |
| `python -m ruff format .` | 格式化代码 |
| `python -m pytest tests/` | 运行单元测试 |
| `python -m mypy custom_components/haier_home/` | 运行类型检查 |
| `pre-commit run --all-files` | 运行所有 pre-commit 钩子 |
| `pre-commit install` | 安装 pre-commit 钩子 |

## 注意事项

1. 提交代码前确保所有测试通过
2. 遵循 Home Assistant 的代码风格指南
3. 为新功能编写单元测试
4. 更新相关文档

## 参考链接

- [Home Assistant Developer Documentation](https://developers.home-assistant.io/)
- [Ruff Documentation](https://docs.astral.sh/ruff/)
- [pytest Documentation](https://docs.pytest.org/)
- [pre-commit Documentation](https://pre-commit.com/)
