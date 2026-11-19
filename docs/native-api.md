# 原生接口、使用与验收范围

更新：2026-11-14，版本 0.3.0。支持已核对的微信 4.2.0 / build 270348 / arm64。
已删除 UI 自动化后端。收发、监听、引用、撤回及朋友圈请求通过客户端内部函数完成。
推荐使用独立副本的 `research/native-profile-isolated.json`；安装及双账号说明见
[账号隔离](account-isolation.md)。

## 当前状态

| 接口 | 验证情况 | 范围 |
| --- | --- | --- |
| `send_text(receiver_id, text)` | 两个账号间后台发送与收取已验证 | 目标必须是内部 ID |
| `send_quote(receiver_id, text, reference)` | AppMsg 57 原生编解码、发送、服务器 ID 与撤回已验证 | 明确原消息的聊天、发送者、类型、服务器 ID；不可跨聊天引用 |
| `revoke_message(message)` | 文字、引用、图片、GIF、AMR、MP4 已逐类返回成功 | 仅自己的发出消息；需要原发送时间、客户端 ID、服务器 ID 和聊天绑定 |
| `send_image(receiver_id, path)` | PNG 单块／分块和 JPEG 已验证 | 最多 20 MiB；64 KiB 分块 |
| `send_sticker(receiver_id, path)` | 小 GIF 已验证并撤回 | GIF，最多 64 KiB，单块 |
| `send_video(receiver_id, path, thumbnail=..., duration_seconds=...)` | MP4 两阶段上传及撤回已验证 | 视频最多 20 MiB，JPEG 缩略图最多 64 KiB，时长由调用方提供 |
| `send_voice(receiver_id, path)` | SILK 与 AMR-NB 发送已验证 | 默认 24 kHz SILK，最多 64 KiB / 60 秒 |
| `read(chat_id, limit=50)` | 原生观察缓存查询 | 最近最多 2000 条、约 32 MiB 估算内存；不查连接前历史数据库 |
| `watch(chat_id, direction=..., timeout=None)` | 两客户端都在后台时已收取并回复 | `incoming`、`outgoing`、`both`；可设置监听截止时间 |
| `reply(message, text, quote=False)` | 后台接收、发送、另一账号收到回复全链路验证 | 拒绝回复自己的消息和协议通知；引用回复需单独启用 quote |
| `get_card_links(message)` | 真实引用卡片和链接卡片已解析 | 所有 XML 卡片子类型通用扫描，支持内嵌转发和多段 XML |
| `get_moments(max_id=0)` / `get_moment(post_id)` | 原账号及独立账号读取已验证 | 列表分页；详情返回作者、正文、XML、评论和点赞列表 |
| `comment_moment(post_id, text)` | 用户明确指定的动态上，提交与精确评论回读已验证 | 根评论，动作 2；不支持回复或删除评论 |
| `like_moment(post_id)` | 实验接口、原生编解码已检查 | 动作 1；不能把评论成功等同于点赞实机验证 |
| `unlike_moment(post_id)` | 实验接口、原生编解码已检查 | 对象操作 5 |
| `prepare_moment(text, visibility=...)` | 本地原生编解码 | 不发布 |
| `publish_moment(text, visibility=...)` | 实验接口、未做服务器发布验收 | 纯文字，明确 private/public；不支持朋友圈媒体上传 |

服务器成功响应不代表对方已读。原生发送绕过客户端本地消息入库／气泡插入流程，
发送端窗口可能不立即显示气泡。2026-11-13 用户确认手机收到全部测试类型；
2026-11-14 在独立账号中重新验证了这些媒体及撤回。
视频／语音播放没有得到单独的明确确认。大小和编码边界未做穷举验证。

## 连接与后台运行

```python
from wechat_aumac import WeChat

profile = 'research/native-profile-isolated.json'
with WeChat(profile, mode='full') as wx:
    for message in wx.watch(chat_id='INTERNAL_CHAT_ID', direction='incoming', timeout=300):
        if message['message_type'] == 1:
            result = wx.reply(message, '已收到')
            print(result)
            break
```

微信必须已登录、进程正常运行、网络可用；不要求其窗口在前台或打开目标聊天。
系统休眠、网络中断或进程被停止时，库无法保证继续收发；退出／重启会停止监听。
收到 `unconfirmed` 不自动重试，避免重复消息。

多个账号按真实可执行文件路径选择；`pid=` / CLI `--pid` 也必须匹配所选 app。
同一 PID 只允许一个本项目连接，监听与发送请复用同一会话。
事件队列限制 2048 项及约 16 MiB 估算内存；消息缓存同时限制条数及约 32 MiB。
积压会丢弃旧内容，并在 `status()` 返回 `dropped_events`／`dropped_messages`。

## 引用、撤回与媒体

```python
with WeChat(profile, mode='full', message_operations=['quote', 'revoke']) as wx:
    # 这些调用均会真实发送或撤回；替换目标后再使用。
    sent = wx.send_text(CHAT_ID, '正文')
    if sent['status'] == 'acknowledged':
        quoted = wx.send_quote(CHAT_ID, '引用回复', sent['message'])
        recalled = wx.revoke_message(sent['message'])
```

引用原文使用原生消息字典，包含 `chat_id`、`message_id`、`sender`、`message_type` 和 `text`。
撤回还需要 `direction='outgoing'`、`to_user`、`timestamp` 和 `revoke_client_id` 或原生数字 `client_id`。
SDK 的发出记录保留这些字段；不从不透明 UUID 猜测数字客户端 ID。
引用和媒体也可从同一连接的 `read()` 中取到精确发出记录后撤回。

撤回请求使用单条消息内部路径，不能套用批量撤回结构。
缺字段、错账号或错聊天会在提交前拒绝；失败／超时不删除缓存、不自动重放。
服务端决定消息是否仍允许撤回。服务器接受后，缓存标记 `revoked=True`，
并产生 `message_revoked` 事件；同步收到的撤回通知也会更新已观察缓存。

媒体默认启用 profile 中已经验收的类型。首次验证某类型时，可显式设置
`experimental_operations=['image', 'sticker', 'voice', 'video']` 中需要的项。
这不会启用朋友圈写入。图片和视频总超时覆盖分块传输；不会把部分偏移当作完整发送成功。

## 卡片链接

```python
with WeChat(profile, mode='observe') as wx:
    for message in wx.watch(direction='both'):
        if message.get('message_type') == 49:
            print(wx.get_card_links(message))
```

`card` 包含子类型、标题、链接列表及来源路径；`links` 提供 URL 字符串列表；
引用卡片还包含 `quote`。扫描各层节点、属性、合并转发的内嵌 XML、CDATA 和有限层转义。
不打开链接，不请求网页，不用外部服务解密附件。
小程序只含 appid／pagepath 时返回原始路由，不生成不存在的网页 URL。
URL 仅覆盖客户端已提供的消息内容（`link_scope='embedded_payload_only'`）；
加密、附件内或服务器未下发的字段无法据此恢复。XML 最大 1 MiB、深度和节点数也有边界，
不支持／异常格式保留原消息，并提供 `card_error`。

## 朋友圈显式写入

```python
with WeChat(profile, mode='full', moments_operations=['comment']) as wx:
    # 以下仅示意；调用时需要明确目标和内容。
    result = wx.comment_moment(POST_ID, '明确的评论正文')
```

`moments_operations` 支持 publish／like／unlike／comment，每类分别启用。
普通 full 会话不能写朋友圈。CLI 的 native-moment-like／comment／unlike 对应明确的单次操作，
不会启用其他写入；CLI 没有发布命令。

互动前读取确切 ID 的详情，失败则不提交。点赞／评论成功后，检查返回或重新读取的
点赞／评论列表，核对当前账号以及评论文本；无法确认则返回 unconfirmed，不重复写入。
发布还需明确可见性，并核对返回的作者、正文和可见性。
从未为调试擅自发布测试朋友圈。

## 诊断与证据

inventory 不安装 Hook；receive 接收同步；observe 只观察；codec 只进行原生编解码；
full 才允许已启用的提交。原生函数指纹、核心哈希、helper 哈希与 app/build 都会核对。
构建新消息入口目录时，还会检查候选地址是否确为 Mach-O 函数起点。

当前本机报告（包含运行数据而不上传）：

- `two-account-background-verification.json`：两账号后台发送、收取和回复；前台 Word。
- `isolated-features-verification.json`：独立副本的原生编解码、朋友圈读取、各媒体／引用发送与撤回。
- `quote-send-verification.json`、`revoke-send-verification-fixed.json`：引用与文字撤回。
- `moment-comment-verification.json`：明确授权的评论、返回成功及确切内容回读。
- `isolated-copy-build.json`、`two-account-identity-verification.json`：签名隔离和不同账号。

较早的 `request-codec-verification.json` 等报告属于旧实验；版本和范围以各报告及本页说明为准。
所有测试素材、账号绑定、捕获、运行报告、app 和依赖均留在本机，Git 只保留源码和静态目录。

`publish_image_moment(text, path, visibility=...)` 已接通原生 CDN 上传和 SNS 发布，并完成配图与评论实测回读；参见 [单图发布说明](native-sns-images.md)。
