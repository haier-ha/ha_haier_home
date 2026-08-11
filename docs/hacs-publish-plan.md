# HACS 发布准备计划

> **目标：** 将 haier_home 集成发布到 HACS (Home Assistant Community Store)

## 1. 当前状态评估

### ✅ 已完成项

| 项目 | 状态 | 位置 |
|-----|------|-----|
| 目录结构符合 HACS 规范 | ✅ | `custom_components/haier_home/` |
| `manifest.json` 存在 | ✅ | `custom_components/haier_home/manifest.json` |
| `hacs.json` 已创建 | ✅ | `hacs.json` |
| `info.md` 已创建 | ✅ | `info.md` |
| `README.md` 存在 | ✅ | `README.md` |
| 集成功能开发完成 | ✅ | - |

### ❌ 待完成项

| 项目 | 优先级 | 描述 |
|-----|-------|-----|
| `manifest.json` 占位符 | 🔴 高 | `documentation`、`issue_tracker` 和 `codeowners` 使用了占位符 |
| GitHub Actions 验证工作流 | 🔴 高 | 需要添加 HACS Action 和 hassfest 验证 |
| GitHub Description | 🟡 中 | 需要在 GitHub 仓库设置中添加描述 |
| GitHub Topics | 🟡 中 | 需要添加搜索标签 |
| Home Assistant Brands | 🟡 中 | 需要提交品牌图标到 `home-assistant/brands` |

---

## 2. 详细变更任务

### 任务 1：更新 `manifest.json`

**文件：** `custom_components/haier_home/manifest.json`

**HACS 要求的必需字段：**
- `domain` — 集成域名
- `name` — 显示名称
- `version` — 版本号
- `documentation` — 文档 URL
- `issue_tracker` — Issue 追踪 URL
- `codeowners` — 维护者列表

**当前问题：**
- `documentation`: `"https://github.com/your-github-username/ha_haier_home"` — 需要替换为实际用户名
- `issue_tracker`: `"https://github.com/your-github-username/ha_haier_home/issues"` — 需要替换为实际用户名
- `codeowners`: `["@your-github-username"]` — 需要替换为实际用户名

**最终内容：**
```json
{
    "domain": "haier_home",
    "name": "Haier Home",
    "version": "0.1.0",
    "documentation": "https://github.com/<YOUR_GITHUB_USERNAME>/ha_haier_home",
    "issue_tracker": "https://github.com/<YOUR_GITHUB_USERNAME>/ha_haier_home/issues",
    "config_flow": true,
    "integration_type": "hub",
    "iot_class": "cloud_push",
    "requirements": [],
    "dependencies": [],
    "codeowners": ["@<YOUR_GITHUB_USERNAME>"]
}
```

**注意：**
- 将 `<YOUR_GITHUB_USERNAME>` 替换为实际的 GitHub 用户名
- `codeowners` 数组中必须包含至少一个 GitHub ID（格式：`@username`）

---

### 任务 2：创建 HACS GitHub Action 验证工作流

**文件：** `.github/workflows/hacs.yml`

**用途：** HACS 官方提供的 GitHub Action，使用与 HACS 相同的代码验证仓库，确保集成在 HACS 中有效。

**触发时机：**
- Push 时自动验证
- Pull Request 时自动验证
- 每天午夜定时验证（检查 HACS 更新后是否仍然兼容）
- 手动触发（workflow_dispatch）

**内容：**
```yaml
name: HACS Validation

on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: "0 0 * * *"
  workflow_dispatch:

jobs:
  validate-hacs:
    runs-on: "ubuntu-latest"
    steps:
      - uses: "actions/checkout@v4"
      - name: HACS validation
        uses: "hacs/action@main"
        with:
          category: "integration"
```

**说明：**
- `category` 必须设置为 `integration`（集成类型）
- 此 Action 使用与 HACS 完全相同的验证逻辑
- 每日定时检查可以确保 HACS 更新后集成仍然有效

---

### 任务 3：创建 hassfest 验证工作流

**文件：** `.github/workflows/hassfest.yml`

**用途：** Home Assistant 官方的集成验证工具，检查集成是否符合 Home Assistant 的规范要求。

**触发时机：**
- Push 时自动验证
- Pull Request 时自动验证
- 每天午夜定时验证（检查 HA 更新后是否仍然兼容）

**内容：**
```yaml
name: Hassfest Validation

on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: "0 0 * * *"
  workflow_dispatch:

jobs:
  validate-hassfest:
    runs-on: "ubuntu-latest"
    steps:
      - uses: "actions/checkout@v4"
      - name: Hassfest validation
        uses: "home-assistant/actions/hassfest@master"
```

**说明：**
- hassfest 会跟踪 Home Assistant 的 beta 版本通道
- 如果集成与新版本 Home Assistant 不兼容，会收到通知
- 这是 HACS 推荐的验证方式

---

### 任务 4：更新 GitHub 仓库设置

这些设置需要在 GitHub 仓库页面手动完成：

#### 4.1 添加仓库描述 (Description)
在 GitHub 仓库 **Settings → General** 中，添加简短描述：
```
Haier Smart Home integration for Home Assistant - 海尔智能家居 Home Assistant 集成
```

**说明：** HACS 会使用这个描述展示在商店中。

#### 4.2 添加 Topics（搜索标签）
在 GitHub 仓库 **Settings → General** 中，添加以下 topics：
```
home-assistant, hacs, haier, smart-home, iot, climate, oauth2
```

**说明：** Topics 不会显示在 HACS UI 中，但用于 HACS 商店的搜索功能。

#### 4.3 启用 GitHub Releases
在 GitHub 仓库页面创建 Tag 和 Release：
```bash
# 创建 tag 并推送
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0

# 使用 GitHub CLI 创建 Release
gh release create v0.1.0 \
  --title "Haier Home v0.1.0" \
  --notes $'## What\'s New\n\n- Initial release\n- Support for Haier air conditioners\n- OAuth2 authentication\n- WebSocket real-time sync'
```

**说明：**
- HACS 会展示最近 5 个版本供用户选择下载
- 如果不使用 releases，HACS 会使用默认分支的文件

---

### 任务 5：Home Assistant Brands 提交

**要求：** HACS 要求集成必须在 [home-assistant/brands](https://github.com/home-assistant/brands) 仓库中有品牌定义。

**步骤：**
1. Fork `home-assistant/brands` 仓库
2. 在 `custom_integrations/haier_home/` 目录下添加：
   - `icon.png` — 品牌图标（建议 256x256 像素）
   - `icon@2x.png` — 高分辨率图标（建议 512x512 像素）
   - `brand.json` — 品牌元信息

3. `brand.json` 示例：
```json
{
    "name": "Haier Smart Home",
    "domain": "haier_home",
    "issue_tracker": "https://github.com/<YOUR_GITHUB_USERNAME>/ha_haier_home/issues"
}
```

4. 提交 PR 到 `home-assistant/brands` 仓库

**注意：**
- 这一步可以在发布 HACS 后进行
- 在 Brands 合并前，HACS 会使用集成目录中的图标作为降级显示

---

## 3. 验证检查清单

在提交到 HACS 之前，使用以下清单验证：

### 3.1 文件结构验证
```
ha_haier_home/
├── .github/
│   └── workflows/
│       ├── hacs.yml             ✅ 新增：HACS 验证
│       └── hassfest.yml         ✅ 新增：hassfest 验证
├── hacs.json                    ✅ 已存在
├── info.md                      ✅ 已存在
├── README.md                    ✅ 已存在
├── LICENSE.md                   ✅ 已存在
└── custom_components/
    └── haier_home/
        ├── manifest.json        ✅ 更新
        ├── __init__.py          ✅ 已存在
        ├── climate.py           ✅ 已存在
        ├── config_flow.py       ✅ 已存在
        ├── const.py             ✅ 已存在
        ├── device.py            ✅ 已存在
        ├── entity.py            ✅ 已存在
        └── ...
```

### 3.2 manifest.json 验证
- [ ] `domain` 字段设置正确：`haier_home`
- [ ] `name` 字段设置正确：`Haier Home`
- [ ] `version` 字段格式正确：`0.1.0`
- [ ] `documentation` URL 有效且可达
- [ ] `issue_tracker` URL 有效且可达
- [ ] `codeowners` 包含至少一个维护者（格式：`@username`）

### 3.3 hacs.json 验证
- [ ] `name` 字段设置正确
- [ ] `homeassistant` 版本格式正确（使用 AwesomeVersion，如 `2024.1.0`）
- [ ] 所有必需字段已填写

### 3.4 GitHub Actions 验证
- [ ] HACS Action 工作流已创建：`.github/workflows/hacs.yml`
- [ ] hassfest 工作流已创建：`.github/workflows/hassfest.yml`
- [ ] HACS Action 中 `category` 设置为 `integration`
- [ ] 推送到 GitHub 后 Actions 能正常运行

### 3.5 功能验证
- [ ] 集成可以正常加载
- [ ] OAuth2 认证流程正常
- [ ] 设备发现和控制正常
- [ ] 没有错误日志输出

---

## 4. 发布到 HACS 的步骤

完成以上所有变更后，按照以下步骤发布：

### 4.1 推送到 GitHub
```bash
git add .
git commit -m "feat: prepare for HACS release"
git push origin main
```

### 4.2 等待 GitHub Actions 验证通过
```bash
# 查看 Actions 状态
gh workflow run "HACS Validation"
gh workflow run "Hassfest Validation"

# 查看运行结果
gh run list --workflow="HACS Validation"
gh run list --workflow="Hassfest Validation"
```

**确保两个验证都通过后再继续。**

### 4.3 创建 Release
```bash
# 使用 GitHub CLI 创建 release
gh release create v0.1.0 \
  --title "Haier Home v0.1.0" \
  --notes $'## What\'s New\n\n- Initial release\n- Support for Haier air conditioners\n- OAuth2 authentication\n- WebSocket real-time sync'
```

### 4.4 添加到 HACS 测试
1. 在 Home Assistant 中打开 HACS
2. 进入 **Settings** → **Custom repositories**
3. 添加你的仓库 URL：`https://github.com/<YOUR_GITHUB_USERNAME>/ha_haier_home`
4. 选择 **Integration** 作为类别
5. 检查集成是否正确显示

### 4.5 提交到 HACS Store（可选）
如果希望提交到 HACS 默认商店：
1. 访问 [HACS 提交页面](https://github.com/hacs/integration/issues/new?assignees=&labels=add+repository&template=add-repository.md&title=Add+new+repository)
2. 填写仓库信息
3. 等待审核（通常需要几周时间）

---

## 5. 建议的后续优化

### 5.1 添加 Python 测试 CI
建议添加专门的 Python 测试工作流：
```yaml
# .github/workflows/tests.yml
name: Tests

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.11', '3.12']
    
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -r requirements_dev.txt
      - run: pytest tests/ -v --tb=short
      - run: ruff check custom_components/
```

### 5.2 完善测试覆盖率
确保核心功能测试覆盖率 > 80%，HACS 用户会关注代码质量。

### 5.3 添加截图
在 `info.md` 或 `README.md` 中添加集成使用截图，可以在 HACS 商店页面更好地展示。

### 5.4 完善文档
- 添加 FAQ 章节
- 添加故障排除指南
- 添加贡献指南（CONTRIBUTING.md）

---

## 参考链接

- [HACS 发布指南 - General](https://www.hacs.dev/docs/publish/start/)
- [HACS 发布指南 - Integration](https://www.hacs.dev/docs/publish/integration/)
- [HACS GitHub Action](https://www.hacs.dev/docs/publish/action/)
- [hassfest 介绍](https://developers.home-assistant.io/blog/2020/04/16/hassfest)
- [Home Assistant Brands](https://github.com/home-assistant/brands)
- [AwesomeVersion 版本检查](https://ludeeus.github.io/awesomeversion)
- [HACS Action 仓库](https://github.com/hacs/action)
- [Home Assistant Actions](https://github.com/home-assistant/actions)
