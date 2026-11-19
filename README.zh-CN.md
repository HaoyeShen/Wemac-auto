# Wemac-auto

macOS 微信原生自动化，**只通过内部函数收发消息**。从 0.3.0 起，已删除 UIA／辅助功能、
鼠标键盘模拟、剪贴板读写、窗口管理和聊天名称搜索功能，不再提供 `WeChatUI`。
包名 `wechat_aumac` 和命令 `wechat-aumac` 保持兼容；`WeChat`、`WeChatAuMac`、
`WeChatNative`、`NativeSession` 均使用原生会话，需要明确提供 profile。

## 环境与安装

已分析的版本为微信 4.2.0 / build 270348、Apple Silicon arm64。
运行需要本机实验副本、Frida、精确的 core／helper SHA-256 和函数头校验。
安装与签名说明见 [原生后端](docs/background-send.md)、[研究目录](research/README.md)。
仓库不包含微信程序、本机账号数据、运行 profile、消息捕获、素材和日志。

```bash
python3 -m venv .venv-hook
.venv-hook/bin/python -m pip install -e '.[hook]'
./wechat-aumac native-status --profile research/native-profile-isolated.json
```

## 后台监听、读取与回复

监听直接挂在内部 NewSync／AddMsg 路径，发送走内部请求构造、网络提交及响应函数。
全过程不要求打开指定聊天或把微信切到前台。微信必须已登录、进程正常运行且网络可用。
电脑休眠、网络断开或微信退出时，不保证继续收发；进程退出后会停止，不自动重发未知结果。

```bash
# 持续监听，JSON Lines；聊天必须使用内部 ID。
./wechat-aumac native-watch --profile research/native-profile-isolated.json \
  --chat INTERNAL_CHAT_ID --direction both

# 收集 10 秒内观察到的消息；不查询连接前的历史数据库。
./wechat-aumac native-read --profile research/native-profile-isolated.json \
  --chat INTERNAL_CHAT_ID --seconds 10

# 仅对明确指定的聊天回复，默认最多一条。此命令会真实发送。
./wechat-aumac native-reply --profile research/native-profile-isolated.json \
  --chat INTERNAL_CHAT_ID --text '你好' --max-replies 1 --seconds 300
```

Python 可持续复用同一连接，按自己的业务规则处理消息：

```python
from wechat_aumac import WeChat

with WeChat('research/native-profile-isolated.json', mode='full') as wx:
    for message in wx.watch(chat_id='INTERNAL_CHAT_ID', direction='incoming'):
        if message['message_type'] == 1:
            result = wx.reply(message, '已收到')
            print(result)
            break
```

`reply()` 拒绝回复自己的消息和系统通知。监听只维护最近 2000 条消息缓存，
`read()` 返回观察缓存。需要已存储的历史消息时，为 profile 配置原生数据库目录，
再调用 `get_history(chat_id, limit=50)`。

## 发送与引用

文字、PNG／JPEG、小 GIF、MP4＋JPEG 缩略图、SILK 和 AMR-NB 语音均有原生接口。
具体大小、编码和验收范围见 [API 文档](docs/native-api.md)。

```bash
./wechat-aumac native-send --profile research/native-profile-isolated.json \
  --to INTERNAL_CHAT_ID '你好'

# reference.json 是原生监听输出的一条消息对象，保留 chat_id、sender、message_id 等字段。
./wechat-aumac native-send-quote --profile research/native-profile-isolated.json \
  --to INTERNAL_CHAT_ID --reference reference.json '引用回复内容'
```

引用通过 `SendAppMsg` 的 57 子类型发送，并校验原消息属于目标聊天、发送者及 64 位服务器 ID。
真实发送已取得服务器成功码和新消息 ID，客户端本地发出气泡更新仍未接入。

## 撤回

```bash
./wechat-aumac native-revoke --profile research/native-profile-isolated.json \
  --message outgoing-message.json
```

`outgoing-message.json` 使用 SDK 发送结果的 `message` 或同一会话 `read()` 中的原生发出消息对象。
需要保留原发送时间、客户端请求 ID、服务器消息 ID、发送者及目标聊天；不猜测缺失字段。
文字、引用、图片、GIF、语音和视频的发送与撤回均已在独立副本得到服务器成功响应。
服务器决定撤回时间范围；失败或未知响应不会删除本地缓存，也不会自动重发。

## 卡片内部链接

```bash
./wechat-aumac native-card-links --profile research/native-profile-isolated.json \
  --chat INTERNAL_CHAT_ID --seconds 15
```

原生同步提供卡片 XML；SDK 输出 `card`、`links`，并对引用卡片提供 `quote`。
解析不限制已知卡片子类型，会检查各层节点、属性和合并转发内嵌 XML。
支持多个 XML 片段、CDATA 和有限层实体转义；保留 URL 的来源路径。
小程序只有 appid／pagepath 时会返回这些原始路由，不伪造网页链接。
加密附件或服务器未下发的 URL 无法从已有消息内容凭空还原；未知内容仍保留原始 `text`。

## 朋友圈

列表和详情通过内部 211／210 请求读取。Python 接口包含 `like_moment()`、
`comment_moment()`、`unlike_moment()`，必须在创建会话时明确启用对应操作。
CLI 对应 `native-moment-like`、`native-moment-comment`、`native-moment-unlike`，均须指定动态 ID。
评论已按用户指定动态和文本完成真实提交，并从返回详情中确认当前账号和评论正文。
点赞／取消点赞保留实验标记，未自动对这条动态点赞。
发布接口保留为显式实验接口，不会在安装、启动、监听或测试过程中自动发布朋友圈。

## 两个账号独立运行

独立副本使用 `com.wemac.auto.client`，与正版的 Bundle ID、数据容器、App Group、
辅助程序和 URL Scheme 分开，不复制原账号数据。原生会话按应用路径选择进程，
必要时可传 `--pid`，不再要求整台电脑只能有一个微信进程。
详见 [账号隔离](docs/account-isolation.md)。

## 验证

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

单元测试不发送聊天消息或发布朋友圈。后台双向实测已完成：两个账号均在后台时，
一个账号发送 `test`，另一个账号接收并回复，发送账号再次接收到回复；前台为 Word。功能验收范围、已知限制和原生接口见
[API 文档](docs/native-api.md)。

### 朋友圈配图与原生语音更新

现已支持 `publish_image_moment(text, path, visibility=...)` 及 `native-moment-publish --image`。图片上传、发布与评论均调用内部函数，已完成服务器确认和独立回读；见 [配图与评论说明](docs/native-sns-images.md)。机器人提供独立“朋友圈”页面，日记配图也使用该接口。语音默认改为 24 kHz SILK，以解决旧 AMR 语音在电脑端无声的问题。

### Incoming media and documents

Native background image/attachment downloads, readable animation frames, local document parsing and actual video observations are described in [后台图片、附件与分享内容读取](docs/native-incoming-media.md).
