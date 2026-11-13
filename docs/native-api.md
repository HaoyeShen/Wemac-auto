# 原生接口、使用与验收范围

更新：2026-11-13。仅适用于本机已核对的微信 4.2.0 / build 270348 / arm64 实验副本。
所有收发、朋友圈请求均调用客户端内部函数；不通过鼠标、键盘、剪贴板或外部机器人服务发送。

## 当前状态

| 接口 | 状态 | 范围 |
| --- | --- | --- |
| `send_text(receiver_id, text)` | 原生提交及服务器确认 | 接收者必须是内部 ID |
| `send_image(receiver_id, path)` | 单块及两块 PNG 已验证 | PNG/JPEG；最多 20 MiB；64 KiB 分块；JPEG 尚未单独实测 |
| `send_sticker(receiver_id, path)` | 小 GIF 已获服务器确认 | GIF，最多 64 KiB，单块 |
| `send_video(receiver_id, path, thumbnail=..., duration_seconds=...)` | 两阶段小样本已确认 | MP4，最多 20 MiB；JPEG 缩略图最多 64 KiB；时长由调用方提供 |
| `send_voice(receiver_id, path)` | AMR 小样本已获服务器确认 | 已编码 AMR-NB，最多 64 KiB / 60 秒；不会把普通音频文件伪装成语音；SILK 未接入 |
| `read(chat_id, limit=50)` | 观察缓存查询 | 连接后最近最多 2000 条；不是旧历史库查询 |
| `watch(chat_id, direction=...)` | 实时收发事件 | `incoming`、`outgoing`、`both`；发出事件在服务器确认或自发消息同步后产生 |
| `get_moments(max_id=0)` | 一页 10 条动态已读通 | 每次只请求一页，返回动态 ID、所有者、正文、时间及 XML |
| `get_moment(post_id)` | 单条详情 ID 核对通过 | 只读，便于核对互动目标 |
| `prepare_moment(text, visibility=...)` | 本地原生编解码通过 | 只创建纯文字草稿，不发布 |
| `publish_moment(text, visibility=...)` | 实验接口，未做服务器验收 | 纯文字；可见性必须明确指定 `private` 或 `public`；不支持朋友圈媒体上传 |
| `like_moment(post_id)` | 实验接口，未做服务器验收 | 先读取确切目标，再构造动作 1 |
| `comment_moment(post_id, text)` | 实验接口，未做服务器验收 | 根评论，动作 2；回复、删除评论未实现 |
| `unlike_moment(post_id)` | 实验接口，未做服务器验收 | 对象操作 5；不是把点赞动作改为 0 |

2026-11-13 用户两次确认手机 `test` 聊天已经收到文字及所有测试媒体，记录见
`research/recipient-confirmation.json`。这不等于接收端已读或所有媒体编码均可播放；
视频／语音播放没有获得单独的明确确认。当前所有发送都绕过了 UI 的本地入库／
气泡插入流程，发送端窗口可能不立即显示发出气泡。
发生 `unconfirmed` 时保留消息 ID、任务 ID 与诊断，不自动重试，避免重复消息。

## 常规收发

```python
from wechat_aumac import WeChatNative

profile = 'research/native-profile-4.2.0.json'
with WeChatNative(profile, mode='full') as wx:
    print(wx.identity())
    # 以下调用都会实际发送；请自行填写明确的接收者和文件。
    # wx.send_text(CHAT_ID, '正文')
    # wx.send_image(CHAT_ID, IMAGE_PATH)
    # wx.send_sticker(CHAT_ID, GIF_PATH)
    # wx.send_voice(CHAT_ID, AMR_PATH)
    # wx.send_video(CHAT_ID, MP4_PATH, thumbnail=JPEG_PATH, duration_seconds=2)
    for message in wx.watch(direction='both'):
        print(message['direction'], message['chat_id'], message['text'])
```

`mode='full'` 加载已校验的原生 completion 桥；仅发送经过 profile 标记的能力。
未验证的媒体协议需调用方显式指定 `experimental_operations`。不能用该选项启用朋友圈写入。
图片与视频的 `timeout` 覆盖整个分块上传过程，收到不匹配的接收者、客户端 ID、偏移或
最终消息 ID 时不会报告成功。

```bash
PYTHONPATH=src .venv-hook/bin/python -m wechat_aumac native-watch \
  --profile research/native-profile-4.2.0.json --direction both --chat CHAT_ID

# 以下命令会实际发送文件；替换 CHAT_ID 和路径后使用。
PYTHONPATH=src .venv-hook/bin/python -m wechat_aumac native-send-image \
  --profile research/native-profile-4.2.0.json --to CHAT_ID /absolute/image.png

PYTHONPATH=src .venv-hook/bin/python -m wechat_aumac native-send-sticker \
  --profile research/native-profile-4.2.0.json --to CHAT_ID /absolute/sticker.gif

PYTHONPATH=src .venv-hook/bin/python -m wechat_aumac native-send-voice \
  --profile research/native-profile-4.2.0.json --to CHAT_ID /absolute/voice.amr

PYTHONPATH=src .venv-hook/bin/python -m wechat_aumac native-send-video \
  --profile research/native-profile-4.2.0.json --to CHAT_ID \
  --thumbnail /absolute/thumbnail.jpg --duration 2 /absolute/video.mp4
```

## 朋友圈读取和草稿

```python
with WeChatNative(profile, mode='full',
                  read_operations=['moment_timeline', 'moment_detail']) as wx:
    page = wx.get_moments()
    if page.get('posts'):
        detail = wx.get_moment(page['posts'][0]['post_id'])
```

```bash
# 只读取一页，绝不发布。
PYTHONPATH=src .venv-hook/bin/python -m wechat_aumac native-moments \
  --profile research/native-profile-4.2.0.json

# 只生成并校验草稿，输出 published: false。
PYTHONPATH=src .venv-hook/bin/python -m wechat_aumac native-moment-draft \
  --profile research/native-profile-4.2.0.json --visibility private '待核对正文'
```

## 朋友圈写入默认关闭

普通 `full` 连接也不能调用朋友圈发布、点赞、取消点赞或评论。调用方需要显式设置
`moments_operations`，取值为 `publish`、`like`、`unlike`、`comment`；每一类单独启用。
这些方法是真实的内部提交路径，尚未通过服务器写入验收，不应作为自动测试运行。
本轮没有执行任何朋友圈写入。

```python
# 仅展示如何单独启用评论；这段代码自身不执行评论。
wx = WeChatNative(profile, mode='full', moments_operations=['comment'])
# 进入连接后，仍需显式调用 wx.comment_moment(明确的动态ID, 明确的正文)。
```

互动前自动读取目标详情，失败或 ID 不匹配则不提交；请求使用新的客户端 ID，不自动重放。
发布返回值还会核对作者、正文和可见性；若无法确认，则返回 `unconfirmed` 并提示帖子可能已存在。
本地原生编解码通过只能验证对象格式、构造／析构等路径，不能证明服务器认可全部业务字段。

## 诊断与证据

- `inventory`：不安装 Hook；检查进程、核心指纹、指令字节与当前能力。
- `receive`：接收同步消息；不允许提交。
- `observe`：显式观察所选请求与响应；不允许提交。CLI 输出字段号和长度，不打印原始内容。
- `codec`：仅构造、解析、序列化和析构请求对象；不允许提交。
- `full`：允许已验证聊天发送；朋友圈写入仍需单独显式启用。

队列同时限制事件数和约 16 MiB 的估算内存，积压时丢弃旧事件并增加 `dropped_events`。
单进程只允许一个原生连接；监听与发送应复用同一连接。

报告：

- `research/request-codec-verification.json`：10 类请求原生编解码。
- `research/image-send-verification.json`、`image-chunked-send-verification.json`：单块／分块图片。
- `research/remaining-media-verification.json`：GIF、视频及最初语音字段判断的原始结果。
- `research/voice-response-field-verification.json`：保存完整响应后的语音字段核对。
- `research/voice-api-verification.json`：修正 SDK 回放真实响应通过，没有为回放再次发送。
- `research/moments-read-verification.json`：朋友圈只读请求。
- `research/moments-write-codec-verification.json`：四种写入请求的本地编解码及关闭状态检查。
- `research/final-text-watch-verification.json`：请求编号为 0、响应编号非 0 时，按同一原生 scene 关联并产生发出事件。
- `research/recipient-confirmation.json`：手机端收到文字及所有测试媒体的用户确认。

测试素材由用户授权的本机图片生成小 GIF／MP4；AMR 为系统合成的“test”。
AMR 编码器构建参考上游 [OpenCORE 编码示例](https://github.com/BelledonneCommunications/opencore-amr/blob/master/test/amrnb-enc.c)，
素材、下载依赖与账号响应样本均保留在本机并加入忽略列表。
