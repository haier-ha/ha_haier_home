# HACS 发布操作手册

> **目标：** 让用户能在 HACS 中搜索并安装 `haier_home` 集成。
> **仓库：** `haier-ha/ha_haier_home`（remote: `git@ha:haier-ha/ha_haier_home.git`，默认分支 `main`）
> **最后核对时间：** 2026-09-07（基于当前代码库实际状态）

---

## 0. 两种"能被搜到"的路径先说清楚

HACS 有两种让用户用到集成的方式，请先明确你的目标：

| 方式 | 用户操作 | 是否需要审核 | 说明 |
|-----|---------|------------|-----|
| **A. 自定义仓库（Custom Repository）** | 用户手动添加你的仓库 URL | 否，立即可用 | 用户在 HACS 里粘贴仓库地址即可安装。**无法通过关键词搜索到。** |
| **B. 默认商店（Default Store）** | 用户直接搜索 "Haier Smart Home" | 是，需向 `hacs/default` 提 PR 并合并 | 这才是"在 HACS 里搜索到"的唯一方式。 |

**要实现"在 HACS 里搜索到"，必须走方式 B。** 本手册以方式 B 为最终目标，方式 A 作为发布前的自测手段。

---

## 1. 当前状态评估（已实际核对）

### ✅ 已满足项

| 要求 | 状态 | 证据 / 位置 |
|-----|------|-----|
| 目录结构：单一集成位于 `custom_components/haier_home/` | ✅ | 仅有 `haier_home` 一个子目录 |
| `manifest.json` 含全部必需键 | ✅ | `domain` / `name` / `version` / `documentation` / `issue_tracker` / `codeowners` 均已填写，无占位符 |
| `hacs.json` 含 `name` | ✅ | `"name": "Haier Smart Home"` |
| `info.md` 有内容 | ✅ | 根目录 `info.md` |
| `README.md` 存在 | ✅ | 根目录 |
| `LICENSE` 存在 | ✅ | 根目录（Apache License 2.0，标准全文，GitHub 可识别） |
| hassfest 工作流 | ✅ | `.github/workflows/hassfest.yaml`（`checkout@v5`） |
| HACS 验证工作流 | ✅ | `.github/workflows/validate.yml`（`checkout@v5`） |
| 品牌图标（本地） | ✅ | `custom_components/haier_home/brand/icon.png`、`icon@2x.png` |

### ❌ 待完成项（阻塞"被搜索到"）

| 项目 | 优先级 | 说明 |
|-----|-------|-----|
| 提交品牌到 `home-assistant/brands` | 🔴 必须 | HACS 默认商店 CI 会检查 `home-assistant/brands` 是否包含 `haier_home`，不通过则 PR 被拒 |
| GitHub 仓库设置（描述 / Issues / Topics） | 🔴 必须 | 默认商店 CI 检查：必须有 description、启用 Issues、定义 topics |
| 创建 GitHub Release / Tag | 🟡 推荐 | 非必需，但推荐（HACS 会展示最近 5 个版本供下载） |
| 向 `hacs/default` 提交 PR | 🔴 必须 | 最终把集成加入默认商店的动作 |

### ⚠️ 已在本次修复

- `.github/workflows/validate.yml` 之前**缺少 `actions/checkout` 步骤**，`hacs/action` 无法拿到仓库内容会失败 —— 已补上。补上后与 [HACS 官方文档](https://www.hacs.dev/docs/publish/action) 示例一致（checkout 版本为 `@v3`）。
- `.github/workflows/hassfest.yaml` 的 checkout 版本对齐到 [home-assistant/actions 官方仓库](https://github.com/home-assistant/actions) 当前示例（`@v4`）。

### 📌 需你确认的一致性问题

- `manifest.json` 里 `"name": "Haier Home"`，而 `hacs.json` / `README` / `info.md` 用的是 `"Haier Smart Home"`。两者不影响校验通过，但商店显示名以 `hacs.json` 的 `name` 为准。若希望统一，建议把 `manifest.json` 的 `name` 也改为 `Haier Smart Home`。

---

## 2. HACS 默认商店的准入要求（官方，2026-09 核对）

来源：[HACS - Integrations](https://www.hacs.dev/docs/publish/integration) 与 [HACS - Include default repositories](https://www.hacs.dev/docs/publish/include)（内容经改写以符合授权要求）。

**仓库结构与文件：**
- `custom_components/` 下只能有一个集成子目录。
- `manifest.json` 必须至少包含：`domain`、`documentation`、`issue_tracker`、`codeowners`、`name`、`version`。
- `hacs.json` 至少要有 `name`。
- 必须存在有内容的 `info.md`（或按配置的 README）。

**集成专属：**
- 集成必须已加入 `home-assistant/brands`。
- 必须同时通过 `home-assistant/actions` 的 hassfest 与 `hacs/action` 两个校验。

**仓库层面（默认商店 CI 会检查）：**
- 仓库有描述（description）。
- 已启用 Issues。
- 已定义 Topics。
- 仓库未被归档。
- 提交 PR 的人必须是仓库 owner 或主要贡献者。

**PR 相关限制：**
- 从个人账号 fork `hacs/default`，**不能用组织账号**提交（PR 需可编辑）。
- 从 `master` 新建分支改动，不要直接改 `master`。
- 列表**区分大小写**。

---

## 3. 操作步骤（按顺序执行即可）

### 步骤 1 —— （可选）统一显示名

如果希望名称一致，编辑 `custom_components/haier_home/manifest.json`：

```json
"name": "Haier Smart Home",
```

### 步骤 2 —— 提交品牌图标到 home-assistant/brands（必须）

1. Fork [home-assistant/brands](https://github.com/home-assistant/brands)。
2. 新建目录 `custom_integrations/haier_home/`，放入：
   - `icon.png`（256×256，可直接用仓库里 `custom_components/haier_home/brand/icon.png`）
   - `icon@2x.png`（512×512，用 `brand/icon@2x.png`）
   - 如有 logo 再加 `logo.png` / `logo@2x.png`（非必需）
3. 提交 PR，等待合并。

> 说明：这一步的合并可能需要几天。可以先并行推进步骤 3–5，但**默认商店 PR（步骤 6）必须在 brands 合并后才会通过 CI**。

### 步骤 3 —— 配置 GitHub 仓库设置（必须）

在 `https://github.com/haier-ha/ha_haier_home` 页面：

1. **Description**（About → 齿轮图标）填写，例如：
   ```
   Haier Smart Home integration for Home Assistant - 海尔智能家居 Home Assistant 集成
   ```
2. **Topics** 添加（用于 HACS 搜索）：
   ```
   home-assistant  hacs  haier  smart-home  iot  climate  oauth2
   ```
3. 确认 **Settings → General → Features → Issues** 已勾选启用。
4. 确认仓库**未归档**。

### 步骤 4 —— 推送代码，确保两个 Action 通过（必须）

```bash
git add .github/workflows/validate.yml .github/workflows/hassfest.yaml custom_components/haier_home/manifest.json docs/hacs-publish-plan.md
git commit -m "chore: fix HACS/hassfest workflows and update publish plan"
git push origin main
```

在 GitHub **Actions** 页查看，或用 CLI：

```bash
gh run list --workflow=validate.yml
gh run list --workflow=hassfest.yaml
```

**两个都必须是绿色（success）再继续。** 如果红色，点进日志按提示修复。

### 步骤 5 —— 创建 Release（推荐，非必须）

```bash
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0

gh release create v1.0.0 \
  --title "Haier Smart Home v1.0.0" \
  --notes $'## 首个正式版本\n\n- 海尔空调设备控制（分体/柜机/商用）\n- OAuth2 账号认证\n- WebSocket 实时状态同步\n- 场景控制'
```

> `manifest.json` 当前 `version` 为 `1.0.0`，tag 建议与之一致（`v1.0.0`）。

### 步骤 6 —— 发布前自测：以自定义仓库方式安装（强烈建议）

在提交默认商店 PR 之前，先用方式 A 验证真实可安装：

1. Home Assistant 里打开 HACS。
2. 右上角菜单 → **Custom repositories**。
3. Repository 填 `https://github.com/haier-ha/ha_haier_home`，Category 选 **Integration**，点 Add。
4. 回到 HACS 列表，应能看到并下载安装，重启后能在集成里正常配置。

确认无误后，进入最后一步。

### 步骤 7 —— 提交到 HACS 默认商店（这一步才让用户能"搜索到"）

1. **用你的个人 GitHub 账号**（不是 `haier-ha` 组织账号）Fork [hacs/default](https://github.com/hacs/default)。
2. 从 `master` 新建分支（例如 `add-haier-home`）。
3. 编辑仓库里的 `integration` 文件，把你的仓库 slug 按**字母顺序、正确大小写**加入：
   ```
   haier-ha/ha_haier_home
   ```
4. 提交 PR 到 `hacs/default`（PR 来自个人 fork，保持"允许维护者编辑"）。
5. 等待 CI 全绿 + 维护者合并。合并后，在下一次定时扫描后，用户即可在 HACS 中**搜索到** "Haier Smart Home"。

> HACS 仓库量很大，合并前请先查 backlog，不要频繁催促。

---

## 4. 提交前最终检查清单

- [ ] `manifest.json` 六个必需键无占位符（✅ 当前已满足）
- [ ] `hacs.json` 含 `name`（✅ 当前已满足）
- [ ] `info.md` 有实际内容（✅ 当前已满足）
- [ ] `custom_components/` 下只有 `haier_home` 一个目录（✅ 当前已满足）
- [ ] `home-assistant/brands` 已包含 `haier_home`（⬜ 步骤 2）
- [ ] GitHub 仓库有 description（⬜ 步骤 3）
- [ ] GitHub Issues 已启用（⬜ 步骤 3）
- [ ] GitHub Topics 已定义（⬜ 步骤 3）
- [ ] `validate.yml`（HACS）Action 通过（⬜ 步骤 4）
- [ ] `hassfest.yaml` Action 通过（⬜ 步骤 4）
- [ ] 已用自定义仓库方式自测安装成功（⬜ 步骤 6）
- [ ] 已从**个人 fork** 向 `hacs/default` 提交 PR（⬜ 步骤 7）

---

## 5. 参考链接

- [HACS - Integrations](https://www.hacs.dev/docs/publish/integration)
- [HACS - Include default repositories](https://www.hacs.dev/docs/publish/include)
- [HACS Action](https://github.com/hacs/action)
- [home-assistant/actions (hassfest)](https://github.com/home-assistant/actions)
- [home-assistant/brands](https://github.com/home-assistant/brands)
- [hacs/default](https://github.com/hacs/default)
- [Home Assistant 集成 manifest 文档](https://developers.home-assistant.io/docs/creating_integration_manifest)

---

*内容已根据授权要求改写。*
