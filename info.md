# Haier Smart Home

海尔智能家居 Home Assistant 集成，支持海尔空调设备的控制与状态同步。

## ✨ 功能特性

- ✅ **OAuth2 账号认证** - 安全的海尔账号登录与授权
- ✅ **WebSocket 实时同步** - 设备状态变化即时推送
- ✅ **空调全面控制**（`climate` 平台）
  - 开关机（始终可用）
  - 模式切换（制冷 / 制热 / 除湿 / 送风 / 自动）
  - 温度调节（设备支持时启用）
  - 风速控制（设备支持时启用）
  - 室内温度显示
- ✅ **场景同步**（`scene` 平台） - 海尔云端手动场景以 HA 场景实体呈现
- 🌐 **多语言配置向导** - 简体中文 / English

## 📦 支持的设备

集成通过海尔 `appTypeCode` 判定设备是否受支持：命中下表则识别为空调并创建
`climate` 实体，未命中的设备会被跳过。

| appTypeCode | 内部类型 |
|-------------|---------|
| `A177` | AC（空调） |
| `A178` | AC（空调） |
| `A120` | AC（空调） |

> 设备的具体能力（可用模式、是否支持风速/温度调节、是否上报室内温度）由该设备的
> `digital model` 属性动态决定，而非按机型硬编码。

## 🚀 快速开始

1. 在 Home Assistant 中进入 **Settings → Devices & Services**
2. 点击 **+ Add Integration**，搜索 **Haier Smart Home**
3. 点击安装，按照 OAuth 授权向导完成海尔账号登录
4. 选择要管理的家庭和设备

## 🔗 链接

- 📖 [文档与源码](https://github.com/haier-ha/ha_haier_home)
- 🐛 [问题反馈](https://github.com/haier-ha/ha_haier_home/issues)

---

本项目基于 Apache License 2.0 开源。
