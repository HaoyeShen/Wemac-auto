# Wemac-auto

**通过 macOS 微信客户端读取和发送消息的 Python 库**，定位类似 Windows 上的 `wxauto`。
保留 UI 自动化后端，并增加调用内部函数的实验性原生后端。UI 后端不读微信数据库；
原生后端需要本机单独准备和签名实验副本、安装 Frida，并校验精确版本及文件指纹。
Python 包名 `wechat_aumac` 和命令 `wechat-aumac` 保持兼容。

> 只在你自己的账号、自己的设备上使用。读取会选中并复制当前聊天，不会发送；
> 发送会真实写入当前聊天，请先在测试群验证。

## 状态

- 95 个单元测试通过，覆盖 UI、原生会话防护、媒体、朋友圈请求和签名逻辑。
- 微信 4.2.0 / build 270348 原生后台发送文字、图片、GIF、短视频、AMR-NB 语音，均已收到服务器成功响应，并由用户确认手机端收到。
- 已验证朋友圈列表与详情读取；发布纯文字、点赞、取消点赞和评论接口默认关闭，尚未进行服务器写入验收。
- 原生读取返回连接后观察到的缓存，不包含完整历史数据库。配置与功能限制见 [原生 API](docs/native-api.md)。
- 仓库仅包含源码、文档、测试和静态分析配置；实验副本、账号和聊天数据、本机 profile、素材与运行报告均排除，见 [research 说明](research/README.md)。
- 已在 macOS 26 + 微信 4.1.15 上真实跑通：
  - `read()`：全屏/最大化 → 滚轮到底 → 2° 斜拖到顶部 → 按住左键 3 秒 → `Cmd+C` → 解析；
  - `send()`：点击输入框 → 粘贴 → 校验输入框内容 → Enter；读回验证成功。

## 安装

仓库自带启动脚本，**零安装**即可运行：

```bash
cd Wemac-auto
./wechat-aumac doctor
# 等价于：
PYTHONPATH=src python3 -m wechat_aumac doctor
```

如需 `pip install`（pip 会自动安装 hatchling 构建后端）：

```bash
python3 -m pip install -e .
```

要求：

- macOS，微信 4.x 已登录并保持窗口打开；
- 运行 Python 的终端需要“辅助功能”权限；
- 微信窗口最大化（库会自动尝试 `AXZoomWindow` 最大化，不会切到独立的全屏 Space）；
- 微信设置为 **Enter 发送**。

## 快速开始

```python
from wechat_aumac import WeChatUI

wx = WeChatUI()

# 读取当前聊天（完整已加载历史）
messages = wx.read()
for m in messages[-5:]:
    print(m.time, m.sender, m.text)

# 只取最后 10 条
last10 = wx.read(limit=10)

# 搜索打开指定聊天（best-effort；只用于读取）
wx.open_chat("test")
messages = wx.read(chat="test")

# 发送到当前聊天（send 永远只发当前聊天）
wx.send("你好，这是 Python 发来的消息")

# 发送并读回验证
wx.send("你好", verify=True)

# 发给指定聊天：先 open_chat/read 确认，再 send 当前聊天
wx.open_chat("test")
wx.read(chat="test")       # 确认内容真的是 test
wx.send("你好", verify=True)

# 导出当前聊天
wx.export("exports", formats=("json", "txt", "md"), prefix="chat")
```

`read()` 返回 `list[Message]`；`Message` 字段：

| 字段 | 说明 |
|---|---|
| `sender` | 发送者显示名 |
| `time` | 微信复制出来的时间文本，如 `2026年10月31日  7:23` |
| `timestamp` | 解析后的 `datetime`，失败为 `None` |
| `text` | 消息正文（可含换行） |

## CLI

```bash
# 诊断权限/窗口
PYTHONPATH=src python3 -m wechat_aumac doctor

# 读取最后 5 条，输出 JSON
PYTHONPATH=src python3 -m wechat_aumac read --limit 5 --json

# 读取当前聊天并导出
PYTHONPATH=src python3 -m wechat_aumac read --export exports --prefix test

# 发送并读回验证
PYTHONPATH=src python3 -m wechat_aumac send "hello" --verify

# 搜索打开 test（只读验证）
PYTHONPATH=src python3 -m wechat_aumac open test
PYTHONPATH=src python3 -m wechat_aumac read --chat test --limit 5
```

`--chat` 使用微信搜索：`Cmd+F` → 粘贴群名 → Enter。
搜索结果没有 AX 标题可校验，属于 **best-effort**。`send` 不带 `--chat`，
只发当前聊天；要发给指定聊天，先 `open`/`read --chat` 确认，再 `send`。

也可以直接用仓库里的 `./wechat-aumac`：

```bash
./wechat-aumac doctor
./wechat-aumac read --limit 5
./wechat-aumac send "hello" --verify
```

## 读取手势

库每次读取都会执行同一套动作（这是实测稳定版）：

1. 激活微信并确保窗口最大化；
2. 鼠标滚轮在聊天区向下滚 4 次，回到最底部；
3. 先在**窗口最右端、输入框上方最下方**的空白处点一下；
4. 再在**水平中间 `x=0.618`** 的同一高度按住左键；
5. 以 **约 2°** 的斜角在 **2 秒**内拖到聊天区顶部；
6. **按住左键原地停 3 秒**（触发向上扩展选择/自动滚动）；
7. 松开左键，把 `Cmd+C` 直接发到微信进程，读取剪贴板；
8. 按“发送者 / 时间 / 正文”解析，正文可包含空行。

坐标按窗口比例计算（默认基于 1512×887 校准）：

| 参数 | 默认值 | 环境变量 |
|---|---|---|
| 右端定位点 x / y | 0.960 / 0.820 | `WECHAT_AUMAC_FOCUS_X_RATIO` / `FOCUS_Y_RATIO` |
| 起点 x / y 比例 | 0.618 / 0.820 | `WECHAT_AUMAC_START_X_RATIO` / `START_Y_RATIO` |
| 终点 y 比例 | 0.0305 | `WECHAT_AUMAC_END_Y_RATIO` |
| 拖动时间 | 2.0s | `WECHAT_AUMAC_DRAG_SECONDS` |
| 顶部按住 | 3.0s | `WECHAT_AUMAC_HOLD_SECONDS` |
| 斜角 | 2.0° | `WECHAT_AUMAC_ANGLE_DEGREES` |
| 滚轮行数 | 60 | `WECHAT_AUMAC_WHEEL_LINES` |

如果微信版本/窗口布局变化导致选不中，先用 `doctor` 看窗口 bounds，再微调这些比例。

## 发送稳定性

发送不是“盲敲 Enter”：

1. 点击输入框（窗口宽 50%、高 91% 的位置）；
2. 保存剪贴板，写入待发文本，`Cmd+V` 粘贴；
3. 用 `Cmd+A/C` 把输入框内容复制回来，**确认待发文本确实在输入框中**；
4. 失败会自动点击输入框并重试一次；
5. 确认后才按 `End` + `Enter` 发送；
6. `send(..., verify=True)` 会再读取一次聊天，检查最后一条是否包含刚发送的文本。

如果微信设置成 `Cmd+Enter` 发送，需要把 `send` 的 Enter 改成对应快捷键（当前默认 Enter）。

## 权限

系统设置 → 隐私与安全性 → **辅助功能**：勾选运行 Python 的终端/IDE（例如 Terminal、iTerm、VS Code）。
没有这个权限时，`doctor` 会显示 `window: None`，`read` 会抛出 `WindowNotFound`。

## 已知限制

- 只读取微信客户端**当前已加载**的聊天记录；换设备/清缓存后客户端没有的历史读不到。
- 读取会选中消息并复制，滚动位置会停在顶部；不会发送。
- `chat=` 通过微信搜索打开，搜索列表没有 AX 标题可校验，属于 **best-effort**；发送前请先 `read(chat=...)` 核对内容，或手动打开聊天后调用 `send(text)`。
- 微信版本/主题/字号变化可能影响坐标；可用环境变量校准。
- 不读数据库、不解密、不抓内存、不重签名微信。

## 测试

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
```

真实微信测试（会操作窗口；`read` 不发消息）：

```bash
PYTHONPATH=src python3 -m wechat_aumac read --limit 3 --json
```

## 目录

```
src/wechat_aumac/     UI 后端（coregraphics/applescript）
tests/                单元测试
examples/             读取/发送/轮询示例
docs/ui-automation.md 手势、权限、校准与排错
exports/              之前抓取的 test 群记录（TXT/JSON/MD）
```

## 监听新消息

```bash
# 当前聊天：首次读取建立基线，之后只输出新增消息
./wechat-aumac watch

# 开始时搜索打开指定聊天，每次读取结束后等待 10 秒
./wechat-aumac watch --chat test --interval 10

# 每条新增消息输出一行 JSON，方便其他程序处理
./wechat-aumac watch --json
```

Python API：

```python
from wechat_aumac import WeChatUI

for message in WeChatUI().watch(interval=10):
    print(message.sender, message.text, flush=True)
```

按 Ctrl+C 停止。监听期间请保持目标聊天打开；`--chat` 只在开始时搜索一次。
每次轮询都会操作鼠标、滚动并复制聊天，耗时数秒，并非后台推送。
复制文本没有收发方向标记，因此收到和发出的新消息都会输出，不能单独识别自己发出的消息。
按记录顺序匹配，支持同一分钟内相同内容的新增记录；如果新旧记录完全没有重叠，
会重新建立基线而不输出该批记录，以免把历史当成新消息。
若记录窗口完全由相同内容组成且条数不变，无法判断是否有同内容新消息替换旧消息。
读取或权限错误会停止监听并报告错误，修复后重新启动。

## 实验性原生后台收发

微信 4.2.0（270348）实验副本已验证文字后台发送、服务器确认及实时新消息解析。
已修复原型传入空完成回调导致发送结束后退出的问题。
现已补齐图片、GIF 表情、MP4 视频和 AMR-NB 语音的内部请求发送，并获得小样本服务器确认。
用户已确认手机 `test` 聊天收到文字和全部测试媒体。
朋友圈列表和单条详情已实际读通；发布、点赞、取消点赞和评论为默认关闭的实验接口，
尚未进行朋友圈写入验收，没有自动发布测试朋友圈。

使用 `native-status`、`native-send`、`native-send-image`、`native-send-sticker`、
`native-send-video`、`native-send-voice`、`native-watch`，或 Python 的 `WeChatNative`。
收发消息监听支持 `native-watch --direction both`。

详细环境、构建方法、当前限制与稳定性结果见
[原生后端说明](docs/background-send.md)；完整方法、格式限制与朋友圈默认关闭行为见
[原生接口用法](docs/native-api.md)。原生 `read()` 仍只查询连接后的观察缓存，未接入旧历史库。
