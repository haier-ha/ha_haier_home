# DISCLAIMER

> Version: 2.0\
> Last Updated: 2026-08-07

------------------------------------------------------------------------

# 风险提示与免责声明

感谢您使用 **Home Assistant 海尔智家集成（Haier Home Integration）**。

在安装、配置或使用本集成前，请仔细阅读以下内容。

## 1. 数据与凭据

为实现账号授权、设备发现、状态同步和设备控制，本集成可能在您的 Home
Assistant 环境中处理或存储相关信息，包括但不限于：

-   海尔账号授权相关信息；
-   OAuth Access Token、Refresh Token 或其他授权凭据；
-   已授权设备及设备状态信息；
-   本地配置、缓存和运行所需的数据。

当您通过本集成访问 **Haier Cloud Services** 或 **Haier Cloud APIs** 时，相关账号、设备、控制指令及服务数据亦可能由海尔云服务按照适用的用户协议、隐私政策、服务条款及法律法规进行处理。

因此，不应将本集成理解为所有相关数据均仅在本地 Home Assistant 环境中处理或存储。

海尔无法控制或保证由用户自行部署或管理的 Home Assistant 系统、操作系统、第三方插件、网络环境或存储设备的安全性。您应根据自身环境采取适当的安全措施，包括访问控制、系统更新、备份以及对账号凭据和授权 Token 的妥善保护。

## 2. 开源代码与社区版本

Haier Home Integration 源代码按照 **[LICENSE.md](https://github.com/haier-ha/ha_haier_home/blob/main/LICENSE.md)** 所载 Apache License 2.0 提供。

本项目可接受社区贡献。社区维护版本、Fork 版本、修改版本、第三方发行版本及非官方构建版本由其各自维护者负责，不因包含或衍生自 Haier Home Integration 代码而成为海尔官方版本。

除海尔另有明确说明外，海尔官方客服不负责 Home Assistant 平台本身、第三方组件或非官方版本的安装、配置、维护和故障排查。

## 3. 用户责任

本集成主要面向具备 Home Assistant、智能家居、网络配置以及基本软件安装和故障排查能力的用户。

您应根据自身部署环境负责必要的：

-   安装和配置；
-   系统与集成升级；
-   数据与配置备份；
-   网络和账号安全；
-   日常维护和故障排查。

## 4. 源代码与云服务的适用规则

Haier Home Integration **源代码** 的使用、复制、修改和分发以 **[LICENSE.md](https://github.com/haier-ha/ha_haier_home/blob/main/LICENSE.md)**（Apache License 2.0）为准。本免责声明不对 Apache License 2.0 已授予的代码权利增加额外的用途限制。

**Haier Cloud Services、Haier Cloud APIs 及其他在线服务不属于 Apache License 2.0 的授权范围。**

访问或使用上述服务，应遵守 **[LegalNotice.md](https://github.com/haier-ha/ha_haier_home/blob/main/LegalNotice.md)** 以及海尔届时适用的用户协议、隐私政策、API/开发者条款、授权规则和其他相关协议。

源代码可依据 Apache License 2.0 使用，并不意味着用户当然取得海尔云服务、API、账号体系、生产环境凭据或商业服务能力的访问或使用权。

## 5. 第三方软件和服务

本集成可能依赖、调用或与以下第三方软件或服务协同工作：

-   Home Assistant；
-   Python 及相关软件库；
-   第三方集成或插件；
-   操作系统和网络服务；
-   其他第三方平台或服务。

第三方软件和服务适用其各自的许可证、隐私政策和服务条款。海尔不控制第三方软件或服务，也不对其可用性、安全性、兼容性、内容或行为作出保证。

## 6. 可用性与兼容性

除适用法律或海尔另行书面承诺外，本集成按 **"现状（AS IS）"** 和 **"可用状态（AS AVAILABLE）"** 提供。

在适用法律允许的最大范围内，海尔不保证：

-   本集成或相关服务持续可用或不中断；
-   本集成不存在错误、缺陷或安全漏洞；
-   与所有 Home Assistant 版本持续兼容；
-   与所有第三方组件、网络环境或设备兼容；
-   Haier Cloud Services 或 APIs 始终保持现有接口、功能或可用性；
-   本集成满足任何特定用途或特定业务需求。

Home Assistant、第三方组件、海尔云服务或 API 的升级、调整或停止可能影响本集成的功能或兼容性。

## 7. 风险与责任限制

使用本集成可能受到软件更新、第三方组件、网络异常、云服务中断、配置错误、误操作、设备状态变化、凭据失效或其他因素影响。

对于源代码本身的保证免责声明和责任限制，以 **Apache License 2.0** 相关条款为准。

对于 Haier Cloud Services、Haier Cloud APIs 及其他在线服务，相关保证、责任及救济规则以适用于该服务的协议和法律法规为准。

在任何情况下，本免责声明均不排除或限制依据适用法律不得排除或限制的责任。

## 8. 合规

您应自行确保对本集成及相关服务的使用符合：

-   所在地适用法律法规；
-   **[LICENSE.md](https://github.com/haier-ha/ha_haier_home/blob/main/LICENSE.md)** ；
-   Home Assistant 适用的规则和条款；
-   海尔适用的用户协议、隐私政策、API/开发者条款和其他服务协议；
-   相关第三方软件或服务的适用条款。

------------------------------------------------------------------------

# Risk Notice and Disclaimer

Thank you for using the **Haier Home Integration** for Home Assistant.

Please read the following information carefully before installing, configuring, or using this integration.

## 1. Data and Credentials

To enable account authorization, device discovery, state synchronization, and device control, this integration may process or store information in your Home Assistant environment, including:

-   information related to authorization of a Haier account;
-   OAuth access tokens, refresh tokens, or other authorization
    credentials;
-   authorized device and device-state information; and
-   local configuration, cache, and operational data.

When you use the integration to access **Haier Cloud Services** or **Haier Cloud APIs**, relevant account, device, command, and service data may also be processed by Haier cloud services in accordance with applicable user agreements, privacy policies, service terms, and laws.

Accordingly, use of this integration should not be understood to mean that all relevant data is processed or stored exclusively within the local Home Assistant environment.

Haier does not control or guarantee the security of a Home Assistant installation, operating system, third-party integration, network environment, or storage device deployed or managed by the user. You should implement security measures appropriate to your environment, including access controls, software updates, backups, and protection of account credentials and authorization tokens.

## 2. Open-Source Code and Community Versions

The Haier Home Integration source code is provided under the Apache
License 2.0 as set forth in **[LICENSE.md](https://github.com/haier-ha/ha_haier_home/blob/main/LICENSE.md)**.

This project may accept community contributions. Community-maintained versions, forks, modified versions, third-party distributions, and unofficial builds are the responsibility of their respective maintainers and do not become official Haier releases merely because they contain or are derived from Haier Home Integration code.

Unless Haier expressly states otherwise, Haier customer support does not provide installation, configuration, maintenance, or troubleshooting support for Home Assistant itself, third-party components, or unofficial versions.

## 3. User Responsibilities

This integration is primarily intended for users familiar with Home Assistant, smart-home technologies, network configuration, and basic software installation and troubleshooting.

You are responsible, as appropriate to your deployment environment, for:

-   installation and configuration;
-   system and integration updates;
-   data and configuration backups;
-   network and account security; and
-   routine maintenance and troubleshooting.

## 4. Rules Applicable to Source Code and Cloud Services

Use, reproduction, modification, and distribution of the Haier Home Integration **source code** are governed by **[LICENSE.md](https://github.com/haier-ha/ha_haier_home/blob/main/LICENSE.md)** (Apache License 2.0). This Disclaimer does not impose additional purpose-of-use restrictions on rights granted by the Apache License 2.0.

**Haier Cloud Services, Haier Cloud APIs, and other online services are outside the scope of the Apache License 2.0.**

Access to or use of those services is subject to **[LegalNotice.md](https://github.com/haier-ha/ha_haier_home/blob/main/LegalNotice.md)** and the then-applicable Haier user agreements, privacy policies, API/developer terms, authorization rules, and other applicable agreements.

The ability to use source code under the Apache License 2.0 does not, by itself, grant access or usage rights to Haier cloud services, APIs, account systems, production credentials, or commercial service capabilities.

## 5. Third-Party Software and Services

This integration may depend on, invoke, or interoperate with:

-   Home Assistant;
-   Python and related software libraries;
-   third-party integrations or plugins;
-   operating systems and network services; and
-   other third-party platforms or services.

Third-party software and services are governed by their own licenses, privacy policies, and service terms. Haier does not control third-party software or services and makes no warranty regarding their availability, security, compatibility, content, or conduct.

## 6. Availability and Compatibility

Except as required by applicable law or expressly agreed by Haier in writing, this integration is provided on an **"AS IS"** and **"AS AVAILABLE"** basis.

To the maximum extent permitted by applicable law, Haier does not warrant that:

-   the integration or related services will remain continuously available or uninterrupted;
-   the integration will be free from errors, defects, or security vulnerabilities;
-   it will remain compatible with every Home Assistant release;
-   it will be compatible with every third-party component, network environment, or device;
-   Haier Cloud Services or APIs will retain their current interfaces, functionality, or availability; or
-   the integration will satisfy any particular purpose or business requirement.

Updates, changes, or discontinuation of Home Assistant, third-party components, Haier cloud services, or APIs may affect functionality or compatibility.

## 7. Risk and Limitation of Liability

Use of the integration may be affected by software updates, third-party components, network failures, cloud-service interruptions, configuration
errors, user actions, device-state changes, expired credentials, or other factors.

Warranty disclaimers and limitations of liability applicable to the source code itself are governed by the relevant provisions of the **Apache License 2.0**.

For Haier Cloud Services, Haier Cloud APIs, and other online services, applicable warranties, liabilities, and remedies are governed by the agreements and laws applicable to those services.

Nothing in this Disclaimer excludes or limits liability that cannot lawfully be excluded or limited under applicable law.

## 8. Compliance

You are responsible for ensuring that your use of the integration and related services complies with:

-   applicable laws and regulations;
-   **[LICENSE.md](https://github.com/haier-ha/ha_haier_home/blob/main/LICENSE.md)** ;
-   applicable Home Assistant rules and terms;
-   applicable Haier user agreements, privacy policies, API/developer terms, and other service agreements;
-   applicable terms governing relevant third-party software or services.
