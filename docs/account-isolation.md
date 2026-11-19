# 正版与原生自动化副本的账号隔离

更新：2026-11-14。独立副本已登录与原实验副本不同的账号，并完成后台双向收发、
媒体发送、引用、撤回和朋友圈读取验证。朋友圈评论的指定目标验收在原账号上执行。

| 对象 | 正版 | 独立副本 |
| --- | --- | --- |
| 程序 | `/Applications/WeChat.app` | `research/WeChat-Wemac.app` |
| Bundle ID | `com.tencent.xinWeChat` | `com.wemac.auto.client` |
| 私有容器 | `~/Library/Containers/com.tencent.xinWeChat` | `~/Library/Containers/com.wemac.auto.client` |
| App Group | `5A4RE8SF68.com.tencent.xinWeChat` | `5A4RE8SF68.com.wemac.auto.client` |
| URL Scheme | 微信原协议 | `wemac-auto` |
| 原生 profile | 正版不注入、不修改签名 | `research/native-profile-isolated.json` |

`WeChat-Hook.app` 是之前使用相同标识的实验副本，会共用正版容器。
不要把它与正版同时运行；保留它仅供回溯旧实验。自动化推荐改用独立的 `WeChat-Wemac.app`。

## 构建与维护

先准备本机 `native-profile-4.2.0.json`（可从 example 复制并按本机情况核对）。
`prepare_isolated_copy.py` 默认只生成计划，`--apply` 才创建独立副本：

```bash
.venv-hook/bin/python research/prepare_isolated_copy.py
.venv-hook/bin/python research/prepare_isolated_copy.py --apply
open research/WeChat-Wemac.app
```

脚本校验原版签名、build 和原始 core 指纹，复制程序而不复制账号数据。
它重映射 Bundle ID、嵌套组件标识、App Group、相关 Mach 服务和 URL Scheme，
等长替换程序中直接嵌入的原标识，并按每个组件原有权限逐层签名。
辅助进程保留自己的 sandbox inheritance，不继承主程序整套权限。
只对主程序增加调试和关闭 library validation 的 entitlement。
最后同时校验原版和独立副本的签名。

已存在的独立程序或容器会使构建脚本停止，避免覆盖已登录的数据；这不是覆盖升级脚本。
不要将原账号容器复制到新容器。第二个账号通过正常扫码登录。

维护 completion 桥时，先退出对应实验副本，再明确提供 profile：

```bash
.venv-hook/bin/python research/build_completion.py \
  --profile research/native-profile-isolated.json --install
```

该命令拒绝向 `/Applications/WeChat.app` 安装 helper。

## 进程选择和本机验证

SDK 不再按“整个系统只有一个 WeChat 进程”选择目标，而是比较真实可执行文件路径。
传入 `pid=` / `--pid` 时也必须匹配 profile 指定的 app，无法借 PID 越过路径校验。
两个应用可各建一个原生会话；同一 PID 仍只允许一个连接。

```bash
./wechat-aumac native-status --profile research/native-profile-isolated.json
./wechat-aumac native-watch --profile research/native-profile-isolated.json --direction both
```

本机验证记录（运行数据均忽略，不上传）：

- `isolated-copy-build.json`：103 个签名组件、标识替换与签名检查。
- `two-account-identity-verification.json`：两进程账号 ID 不同；报告不保存账号明文。
- `two-account-background-verification.json`：前台为 Word，两个账号完成后台收取与回复。
- `isolated-features-verification.json`：独立副本的媒体、引用、撤回、编解码和朋友圈读取。

后台收发测试使用明确绑定的测试聊天；不会自动对任意新消息回复。
生产监听请把读取、业务处理和发送放在同一个会话中，避免对同一 PID 重复 attach。

设计依据：[Apple App Groups](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.application-groups)
和 [容器路径 API](https://developer.apple.com/documentation/foundation/filemanager/containerurl%28forsecurityapplicationgroupidentifier%3A%29)。
实际隔离状态还应核对进程打开的容器路径与各自账号，不能只凭修改应用显示名称判断。
