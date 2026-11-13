"""Create a small AMR-NB 'test' fixture in a separate process, not in WeChat.

Encoder ABI follows the upstream OpenCORE example:
https://github.com/BelledonneCommunications/opencore-amr/blob/master/test/amrnb-enc.c
The downloaded Apache-2.0 source and license stay under research/deps.
"""
import ctypes as C
import hashlib
import json
from pathlib import Path
import wave

ROOT=Path(__file__).resolve().parent
library=ROOT/'deps/opencore-amr-master/local-build/libopencore-amrnb.dylib'
lib=C.CDLL(str(library))
lib.Encoder_Interface_init.argtypes=[C.c_int];lib.Encoder_Interface_init.restype=C.c_void_p
lib.Encoder_Interface_Encode.argtypes=[C.c_void_p,C.c_int,C.POINTER(C.c_short),C.POINTER(C.c_ubyte),C.c_int]
lib.Encoder_Interface_Encode.restype=C.c_int
lib.Encoder_Interface_exit.argtypes=[C.c_void_p];lib.Encoder_Interface_exit.restype=None
lib.Decoder_Interface_init.argtypes=[];lib.Decoder_Interface_init.restype=C.c_void_p
lib.Decoder_Interface_Decode.argtypes=[C.c_void_p,C.POINTER(C.c_ubyte),C.POINTER(C.c_short),C.c_int]
lib.Decoder_Interface_Decode.restype=None
lib.Decoder_Interface_exit.argtypes=[C.c_void_p];lib.Decoder_Interface_exit.restype=None
encoder=lib.Encoder_Interface_init(0);decoder=lib.Decoder_Interface_init()
if not encoder or not decoder:raise SystemExit('AMR state allocation failed')
frames=0;nonzero=0;data=bytearray(b'#!AMR\n')
try:
    with wave.open(str(ROOT/'fixtures/test.wav'),'rb') as wav:
        if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())!=(1,2,8000):
            raise SystemExit('Expected mono 8 kHz 16-bit PCM')
        while block:=wav.readframes(160):
            pcm=(C.c_short*160).from_buffer_copy(block.ljust(320,b'\0'))
            output=(C.c_ubyte*500)()
            size=lib.Encoder_Interface_Encode(encoder,7,pcm,output,0)
            if not 0<size<=500:raise SystemExit('AMR encoding failed')
            data.extend(bytes(output[:size]));frames+=1
            decoded=(C.c_short*160)()
            lib.Decoder_Interface_Decode(decoder,output,decoded,0)
            nonzero+=sum(value!=0 for value in decoded)
finally:
    lib.Encoder_Interface_exit(encoder);lib.Decoder_Interface_exit(decoder)
if not frames or not nonzero:raise SystemExit('AMR self-decode did not produce audio')
(ROOT/'fixtures/test.amr').write_bytes(data)
report={'format':'AMR-NB','sample_rate':8000,'frames':frames,'duration_ms':frames*20,
        'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
        'decoded_nonzero_samples':nonzero,'encoder_sha256':hashlib.sha256(library.read_bytes()).hexdigest()}
(ROOT/'fixtures/amr-fixture.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
