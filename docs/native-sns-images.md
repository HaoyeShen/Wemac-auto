# 原生朋友圈配图与评论

固定支持已验证的 macOS 微信 4.2.0（270348）、arm64 核心指纹。图片上传调用所选微信的 CDN 接口，动态发布调用原生 SNS 请求；不操作微信窗口、剪贴板或录屏。

```python
from wechat_aumac.native import NativeSession
with NativeSession(profile, mode="full", moments_operations=["publish", "comment"],
                   read_operations=["moment_detail"]) as wx:
    result = wx.publish_image_moment("测试动态", "/absolute/path/image.png", visibility="private")
    if result["status"] == "acknowledged":
        post_id = result["post"]["post_id"]
        wx.comment_moment(post_id, "测试评论")
```

每个写入都是明确调用。`visibility` 必须指定 `private` 或 `public`。CLI 支持：

```sh
wechat-aumac native-moment-publish --profile /path/profile.json --visibility private --image /path/image.png "测试动态"
wechat-aumac native-moment-comment --profile /path/profile.json --id POST_ID "评论内容"
```

机器人主页的“朋友圈”入口支持正文、单张配图、读取动态和选中目标评论；设置里的日记配图与主动评论沿用原有开关。未开启的自动功能不会因打开页面而开启。

图片支持 JPEG、PNG、WebP、GIF 首帧；输入不超过 32 MiB、1600 万像素。发送前旋转到正确方向、移除元数据、透明底合成白色，缩放到最长边 2048，输出不超过 8 MiB 的 JPEG。

桥接库中的请求对象、智能指针与异步回调均由原生 C++ 持有。回调和虚表随 NODELETE 库保持映射，不包含 JS/Python 回调；上传超时不会释放仍在使用的请求。完成结果核对客户端 ID、数据类型、字节数、MD5、图片与缩略图域名；发帖后核对作者、正文、可见范围及本次图片地址。上传失败不提交动态，结果不明不自动重发。

安装包自动放置原生桥并生成指纹。源码开发环境可用 `research/build_sns_upload.py --profile /path/profile.json` 编译及固定桥接库；这一步不修改或重启微信。需要 Xcode 命令行工具和 Python 的 `hook,resources` 可选依赖。

实机验证已完成：图片上传成功、发布成功、独立回读正文和图片地址成功、对同一测试动态评论并回读成功。另验证了短超时后卸载主机脚本，原生回调继续安全完成，后续上传成功；C++ AddressSanitizer 生命周期检查循环 100 次通过。
