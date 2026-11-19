"""Local, bounded Tencent SILK framing and Skype reference SDK bindings."""
import ctypes as c
import os, struct
from pathlib import Path

HEADER=b'\x02#!SILK_V3'

def library():
    roots=[Path.home()/'Library/Application Support/WemacAuto/Arona/lib',
           Path(__file__).resolve().parents[3]/'bot/lib',
           Path(__file__).resolve().parents[3]/'lib',
           Path(__file__).resolve().parents[4]/'lib']
    if os.environ.get('ARONA_DATA_DIR'):roots.insert(0,Path(os.environ['ARONA_DATA_DIR'])/'lib')
    paths=([Path(os.environ['ARONA_SILK_LIBRARY'])] if os.environ.get('ARONA_SILK_LIBRARY') else [])
    paths += [p/'libwemac-silk.dylib' for p in roots]
    for p in paths:
        if p.is_file():return c.CDLL(str(p))
    raise RuntimeError('本地 SILK 编码器未安装，请将 ARONA_SILK_LIBRARY 指向 libwemac-silk.dylib')

def packets(data):
    if not data.startswith(HEADER):raise ValueError('Expected Tencent SILK audio')
    pos=len(HEADER);count=0
    while pos<len(data):
        if pos+2>len(data):raise ValueError('Truncated SILK packet length')
        size=struct.unpack_from('<h',data,pos)[0];pos+=2
        if not 0<size<=1024 or pos+size>len(data):raise ValueError('Invalid SILK packet')
        count+=1
        if count>3000:raise ValueError('Too many SILK packets')
        yield data[pos:pos+size];pos+=size
    if not count:raise ValueError('Empty SILK audio')

def duration_ms(data):
    return len(decode_pcm(data))//48

class DecoderControl(c.Structure):
    _fields_=[(key,c.c_int32) for key in ('rate','frame_size','frames','more','fec')]

def decode_pcm(data):
    lib=library();size=c.c_int32()
    get=lib.SKP_Silk_SDK_Get_Decoder_Size;get.argtypes=[c.POINTER(c.c_int32)];get.restype=c.c_int
    if get(c.byref(size)) or not 0<size.value<4*1024*1024:raise ValueError('Invalid SILK decoder state')
    state=c.create_string_buffer(size.value)
    init=lib.SKP_Silk_SDK_InitDecoder;init.argtypes=[c.c_void_p];init.restype=c.c_int
    if init(state):raise ValueError('SILK decoder initialization failed')
    fn=lib.SKP_Silk_SDK_Decode
    fn.argtypes=[c.c_void_p,c.POINTER(DecoderControl),c.c_int,c.c_void_p,c.c_int,c.c_void_p,c.POINTER(c.c_int16)];fn.restype=c.c_int
    control=DecoderControl(24000,0,0,0,0);result=bytearray()
    for packet in packets(data):
        source=c.create_string_buffer(packet)
        for _ in range(5):
            output=c.create_string_buffer(960);length=c.c_int16(480)
            if fn(state,c.byref(control),0,source,len(packet),output,c.byref(length)) or length.value!=480:
                raise ValueError('Invalid SILK audio packet')
            result+=output.raw[:length.value*2]
            if len(result)>60*24000*2:raise ValueError('Voice exceeds 60 seconds')
            if not control.more:break
        else:raise ValueError('Too many frames per SILK packet')
    return bytes(result)

class EncoderControl(c.Structure):
    _fields_=[(key,c.c_int32) for key in ('rate','max_rate','packet_size','bitrate','loss','complexity','fec','dtx')]

def encode_pcm(pcm, sample_rate=24000):
    if sample_rate!=24000 or not pcm or len(pcm)%2 or len(pcm)>60*sample_rate*2:
        raise ValueError('Expected bounded mono 24 kHz signed-16 PCM')
    lib=library();size=c.c_int32()
    get=lib.SKP_Silk_SDK_Get_Encoder_Size;get.argtypes=[c.POINTER(c.c_int32)];get.restype=c.c_int
    if get(c.byref(size)) or not 0<size.value<4*1024*1024:raise RuntimeError('SILK state size failed')
    state=c.create_string_buffer(size.value);control=EncoderControl()
    init=lib.SKP_Silk_SDK_InitEncoder;init.argtypes=[c.c_void_p,c.POINTER(EncoderControl)];init.restype=c.c_int
    if init(state,c.byref(control)):raise RuntimeError('SILK initialization failed')
    control=EncoderControl(sample_rate,sample_rate,sample_rate//50,24000,0,2,0,0)
    fn=lib.SKP_Silk_SDK_Encode
    fn.argtypes=[c.c_void_p,c.POINTER(EncoderControl),c.c_void_p,c.c_int,c.c_void_p,c.POINTER(c.c_int16)];fn.restype=c.c_int
    result=bytearray(HEADER);frame_bytes=sample_rate//50*2
    for pos in range(0,len(pcm),frame_bytes):
        frame=c.create_string_buffer(pcm[pos:pos+frame_bytes].ljust(frame_bytes,b'\0'))
        output=c.create_string_buffer(1024);length=c.c_int16(1024)
        if fn(state,c.byref(control),frame,sample_rate//50,output,c.byref(length)) or not 0<length.value<=1024:
            raise RuntimeError('SILK encoding failed')
        result+=struct.pack('<h',length.value)+output.raw[:length.value]
    if len(result)>65536:raise ValueError('Voice exceeds single-chunk upload bound; shorten the reply')
    return bytes(result)
