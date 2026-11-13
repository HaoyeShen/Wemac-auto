# 微信 4.2.0 原生后端与稳定性

最新验收：2026-11-13。当前 API、命令和各类型的验证范围见 [原生接口用法](native-api.md)。

适用环境：macOS 26.7.1、Apple Silicon arm64、微信 4.2.0 / build 270348。
本机运行对象是 `research/WeChat-Hook.app`，原版 `/Applications/WeChat.app`
未修改，系统 SIP 保持开启。原生接口仍为实验性接口，按精确版本和文件指纹校验。

## 当前功能

| 功能 | 实际验证情况 |
| --- | --- |
| 文字后台发送 | 内部请求构造、提交、服务器成功响应及消息 ID 已验证 |
| 文字发送结束处理 | 已补齐原生完成回调；回调返回 true，由微信释放任务对象 |
| 实时新消息读取 | 内部 NewSync / AddMsg 解析已验证；含聊天 ID、发送者、正文、类型 |
| 已观察消息查询 | `read()` 查询连接后缓存的最近消息；最多保留 2000 条 |
| 历史记录查询 | 尚未接入内部存储查询接口 |
| 图片发送 | PNG 的单块与两块发送均收到服务器成功码、完整偏移和消息 ID |
| 视频发送 | 两秒 H.264 MP4，经缩略图／视频两阶段上传收到完整偏移和消息 ID |
| 动态表情发送 | 小 GIF 经 UploadEmoji 请求收到 MD5、完整偏移和消息 ID |
| 语音发送 | AMR-NB 测试语音收到服务器成功码、完整长度和消息 ID；修正 SDK 用保存的真实响应回放验证 |
| 朋友圈读取 | 内部 211／210 请求返回一页 10 条动态及一条匹配 ID 的详情 |
| 朋友圈发布、点赞、取消点赞、评论 | 已实现实验接口；默认关闭，只完成静态及原生编解码检查，没有执行服务器写入验收 |

发送当前经过内部网络请求层，尚未接入客户端本地消息入库和发出气泡更新。
返回服务器成功响应代表服务器接受消息，不等于对方已读。
普通 Unicode Emoji 可随文字发送，动态表情包是独立媒体功能。
2026-11-13 用户已确认手机端收到文字及所有测试媒体。视频／语音播放尚未获得单独明确确认。
当前小样本通过不等于所有编码、文件大小、聊天类别和长期运行情况均已验证。

## 已修复的退出原因

实际发送结束时，微信在 `0x4762728` 读取 scene + 0x68 的完成回调。
原型传入了空 `std::function`，跳到 `0x47627a4 -> 0x222c2c` 抛出异常。
崩溃报告的调用链包含 `0x222c60`、`0x47627a8`、`__cxa_throw`、
`std::__terminate` 和 `abort()`。因此服务器响应可以成功，但客户端仍在结束任务时退出。

修复采用 `native/completion.cpp`，构造与已观察调用 ABI 一致的非空 libc++ 回调：
`bool(Scene* const&, const int&, const int&)`。返回 true 交由微信释放 scene。
临时回调被复制进任务后，销毁临时对象；任务中的副本仍可正常执行。
回调位于实验副本内的原生动态库中，使用 RTLD_NODELETE 保持加载，独立于 Frida
脚本生命周期。禁止把空回调或依赖临时 JavaScript 对象的回调传入异步任务。

额外防护：

- 单个微信 PID 只允许一个本项目原生连接，重复连接在 attach 前拒绝。
- Hook 内仅复制内存与解码，不再调用 C++ 方法，避免重入目标函数。
- 动态缓冲区使用 `readVolatile`；无效指针不能依赖原生信号异常恢复。
- 退出前先 detach Hook、flush、卸载脚本，再断开 session。
- 进程退出或重启后停止监听，不使用旧地址重连或自动重发消息。
- 老的独立实时探针 `observe_tasks.py`、`observe_media.py` 已归档禁用。

报告：`research/completion-crash-analysis.json`、`research/stability-verification.json`。
原生回调回归测试在独立进程复现空回调异常，并验证复制、移动与临时对象销毁后的调用。

## 使用

安装可选 Python 依赖（当前实验环境已安装）：

```bash
python3 -m venv .venv-hook
.venv-hook/bin/python -m pip install 'frida>=17,<18'
```

构建或更新完成回调库时，先退出实验副本，再运行：

```bash
.venv-hook/bin/python research/build_completion.py --install
```

该脚本只更新停止运行的实验副本，并校验签名、更新 helper 指纹。
重建完整副本后需要重新校验 core 指纹与 profile，不能直接套用旧文件指纹。

```bash
# 版本与进程检查；inventory 模式不安装 Hook
PYTHONPATH=src .venv-hook/bin/python -m wechat_aumac native-status \
  --profile research/native-profile-4.2.0.json

# 接收新消息；Ctrl+C 停止。聊天名称必须先解析为内部 ID
PYTHONPATH=src .venv-hook/bin/python -m wechat_aumac native-watch \
  --profile research/native-profile-4.2.0.json --chat CHATROOM_ID

# 实际发送；请使用明确的内部接收者 ID
PYTHONPATH=src .venv-hook/bin/python -m wechat_aumac native-send \
  --profile research/native-profile-4.2.0.json --to CHATROOM_ID '测试文字'
```

同时收发请复用同一个连接：

```python
from wechat_aumac import WeChatNative

with WeChatNative('research/native-profile-4.2.0.json', mode='full') as wx:
    result = wx.send_text('明确的 wxid 或 @chatroom ID', '测试文字')
    print(result)
    for message in wx.watch():
        print(message['sender'], message['text'])
```

默认 `mode='receive'`；发送须显式 `mode='full'`。`read()` 仅查询连接后观察到的缓存。
超时返回 `unconfirmed`，不自动重发，避免重复发送。

新增 `native-send-image`、`native-send-sticker`、`native-send-video`、`native-send-voice`。
`native-watch --direction both` 可接收双向消息事件；`observe` 模式禁止提交，
`codec` 模式只运行本地请求编解码。媒体、朋友圈的完整参数见 [原生接口用法](native-api.md)。

## 稳定性复测

以下命令会向已确认的 test 聊天发送测试文字；接收者绑定保存在本机 research 目录：

```bash
.venv-hook/bin/python research/stability_check.py --seconds 60 --send-test
.venv-hook/bin/python research/verify_pending_completion.py
```

前者分 inventory、接收、收发阶段验证进程、回调计数、清理错误及新增崩溃报告。
后者提交请求后立即卸载探针，检查原生回调是否仍完成、进程是否保持存活。
有限时长回归通过不代表所有微信操作和长期运行情况均已验证。

## 实验副本签名

辅助进程必须保留各自的沙箱继承权限。不能使用统一的 `--deep --entitlements`
把主程序权限覆盖给全部组件。`research/repair_copy_signing.py` 按组件使用原始
identifier 和 entitlement，仅向主程序增加调试权限。

参考资料：
- https://github.com/yincongcyincong/wechat_chatter
- https://github.com/Tencent/mars/blob/master/mars/comm/autobuffer.h
- https://frida.re/docs/javascript-api/#nativepointer
