# Haier Smart Home

海尔智能家居 Home Assistant 集成，支持海尔空调设备的控制与状态同步。

## ✨ 功能特性

- ✅ **OAuth2 账号认证** - 安全的海尔账号登录与授权
- ✅ **WebSocket 实时同步** - 设备状态变化即时推送
- ✅ **空调全面控制**
  - 开关机、模式切换（制冷/制热/除湿/送风/自动）
  - 温度调节、风速控制
  - 室内/室外温度显示
- ✅ **场景管理** - 支持海尔场景的触发与控制
- 🌐 **多语言支持** - 中文 / English

## 📦 支持的设备

| 设备类型码 | 设备名称 | 说明 |
|-----------|---------|------|
| 02 | 分体空调 | 标准家用空调 |
| 03 | 柜机空调 | 大功率立柜式空调 |
| 0d | 商用空调 | 部分型号不支持室内温度 |

## 🚀 快速开始

1. 在 Home Assistant 中进入 **Settings → Devices & Services**
2. 点击 **+ Add Integration**，搜索 **Haier Smart Home**
3. 点击安装，按照 OAuth 授权向导完成海尔账号登录
4. 选择要管理的家庭和设备

## 🔗 链接

- 📖 [文档与源码](https://github.com/haier-ha/ha_haier_home)
- 🐛 [问题反馈](https://github.com/haier-ha/ha_haier_home/issues)

---

*本项目基于 MIT 许可证开源。*
