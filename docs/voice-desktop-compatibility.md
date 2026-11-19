# Desktop voice compatibility

The bot encodes mono 24 kHz PCM as Tencent-framed SILK using the locally built Skype reference codec (24 kbps, 20 ms packets). UploadVoiceRequest field 13 is 4 for SILK and remains 0 for legacy AMR. Field 9 is the end flag, not the format. The SDK validates framing, decodes every packet to validate duration, and bounds upload size and duration before submission.

Build the local codec with the companion application's `bot/scripts/install_silk.py` and point `ARONA_SILK_LIBRARY` at the resulting `libwemac-silk.dylib`. The script uses kn007/silk-v3-decoder commit `507be6bca8ce1fb977a061481f1d79e8c610e309`. [Build script](https://github.com/HaoyeShen/Aronabot-MacOS/blob/main/bot/scripts/install_silk.py) · [Skype license](https://github.com/HaoyeShen/Aronabot-MacOS/blob/main/bot/vendor/SILK-LICENSE)

The 2026-11-15 authorized test received a server acknowledgment and the user confirmed audible playback on desktop. Old AMR messages are not rewritten.

The Moments page provides explicit public text/image publishing and exact-post comments through the native adapter. Reads do not interact. Submissions receive a persistent local receipt before transmission; repeated identical content is blocked to avoid duplicates after uncertain outcomes. Existing daily diary and opt-in automatic comment settings remain available.

Native image publishing is now implemented and live verified; see [Native SNS images](native-sns-images.md).
