# Wemac-auto

[中文说明](README.zh-CN.md)

macOS WeChat automation through **internal native functions only**. Version 0.3
removes the UI backend, mouse/keyboard simulation, clipboard reading and window
management. `WeChat`, `WeChatAuMac`, `WeChatNative` and `NativeSession` now refer to
the native session class and require an explicit version-pinned profile.

The Python package and executable retain the names `wechat_aumac` and
`wechat-aumac`. Install with `python3 -m pip install -e '.[hook]'` on Apple Silicon
macOS. The analyzed client is WeChat 4.2.0, build 270348. Native access requires a
locally prepared research copy, exact core/helper fingerprints and checked function
heads. WeChat binaries, account data, local profiles and captured payloads are not
shipped in this repository.

Incoming messages are observed from the native sync parser while WeChat remains
in the background. Replies use native submission and server responses. `read()`
returns the bounded observation cache. `get_history()` queries stored messages
through WeChat's database engine when the profile includes the database catalog.
Native card XML is inspected for embedded links across card subtypes, and
mini-program routes are retained when the payload contains no web URL.

Text, PNG, GIF, short MP4, SILK and AMR-NB voice sends have recorded server validation.
Quoted replies use the type-57 AppMsg path. See the current validation scope and
limitations in [the native API](docs/native-api.md). Moments timeline/detail reads
are validated; commenting has been validated on an explicitly chosen post, including
readback of the exact author and comment. Like/unlike APIs remain experimental
until their live writes are validated. Publishing is never performed by setup,
watching, reading or tests.

```bash
./wechat-aumac native-status --profile research/native-profile-isolated.json
./wechat-aumac native-watch --profile research/native-profile-isolated.json --chat INTERNAL_CHAT_ID
# Sends real replies only in the selected chat, once by default:
./wechat-aumac native-reply --profile research/native-profile-isolated.json \
  --chat INTERNAL_CHAT_ID --text 'hello' --max-replies 1
```

A second app can be prepared with a separate bundle ID, sandbox container, app
group, helper identifiers and URL scheme. See [account isolation](docs/account-isolation.md).
Session selection uses the executable path and optional PID, allowing distinct
clients to run concurrently. Log the second app into a different account manually.

Run offline unit tests with:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

See [native API](docs/native-api.md), [setup and stability](docs/background-send.md),
[research files](research/README.md) and [Moments entrypoints](docs/moments-entrypoints.md).

## Native SNS images and desktop voice compatibility

Single-image Moments publishing and exact-post comments now use the selected client’s native CDN/SNS functions. See [usage, bounds and validation](docs/native-sns-images.md). The bot includes a Moments page and supports diary illustrations. Voice output uses 24 kHz Tencent SILK with matching metadata, verified audible on desktop.

### Incoming media and documents

Native background image/attachment downloads, readable animation frames, local document parsing and actual video observations are described in [后台图片、附件与分享内容读取](docs/native-incoming-media.md).
