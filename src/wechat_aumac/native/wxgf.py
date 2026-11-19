"""Decode WXGF with the selected WeChat's own version-pinned multimedia codec.

The native codec runs in a disposable worker so malformed cached artwork cannot
take down either WeChat or the desktop bot. No account keys enter this worker.
"""
from __future__ import annotations
import ctypes as c
import hashlib,json,struct,subprocess,sys
from pathlib import Path

MAX_PIXELS=16_000_000
MAX_DECODED_BYTES=256*1024*1024

def _worker(request):
    from PIL import Image
    codec=request['codec'];library=Path(codec['path']).resolve()
    if codec.get('abi')!='wxam-5-bgra' or hashlib.sha256(library.read_bytes()).hexdigest()!=codec['sha256']:
        raise ValueError('Native WXGF codec fingerprint/ABI mismatch')
    source=Path(request['source']);data=source.read_bytes()
    if not data.startswith(b'wxgf') or len(data)>8*1024*1024:raise ValueError('Invalid WXGF container')
    lib=c.CDLL(str(library));buffer=c.create_string_buffer(data);info=c.create_string_buffer(128)
    getinfo=lib.wxam_dec_getWXGFInfo_5
    getinfo.argtypes=[c.c_void_p,c.c_int,c.c_void_p];getinfo.restype=c.c_int
    if getinfo(buffer,len(data),info)!=0:raise ValueError('WeChat rejected WXGF metadata')
    width,height,count=struct.unpack_from('<3i',info.raw)
    if (not 0<width<=8192 or not 0<height<=8192 or not 1<=count<=600
            or width*height>MAX_PIXELS or width*height*4*count>MAX_DECODED_BYTES):
        raise ValueError('WXGF frame dimensions/count exceed the decode bound')
    init=lib.wxam_dec_init_5
    init.argtypes=[c.c_int,c.c_void_p,c.c_void_p,c.POINTER(c.c_int)];init.restype=c.c_void_p
    decode=lib.wxam_dec_decode_buffer_5
    decode.argtypes=[c.c_void_p,c.c_void_p,c.c_int,c.c_int,c.c_void_p,c.POINTER(c.c_int)];decode.restype=c.c_int
    close=lib.wxam_dec_uninit_5;close.argtypes=[c.c_void_p];close.restype=None
    status=c.c_int();context=init(4,None,None,c.byref(status))
    if not context or status.value:
        if context:close(context)
        raise ValueError('WeChat could not initialize the WXGF decoder')
    frames=[];durations=[]
    try:
        if decode(context,buffer,len(data),1,None,c.byref(status)) or status.value:
            raise ValueError('WeChat rejected WXGF input')
        for index in range(count):
            pointer=c.c_void_p()
            if decode(context,None,0,2,c.byref(pointer),c.byref(status)) or status.value or not pointer.value:
                raise ValueError('WeChat did not decode every WXGF frame')
            layout=c.string_at(pointer,112)
            frame_width,frame_height,channels,duration=struct.unpack_from('<4I',layout,64)
            address=struct.unpack_from('<Q',layout,0)[0];stride=struct.unpack_from('<Q',layout,32)[0]
            if ((frame_width,frame_height,channels)!=(width,height,4) or not address
                    or not width*4<=stride<=width*4+8192):raise ValueError('Native WXGF frame ABI mismatch')
            pixels=c.string_at(address,stride*height)
            frames.append(Image.frombytes('RGBA',(width,height),pixels,'raw','BGRA',stride))
            durations.append(max(10,min(10000,int(duration) or 100)))
    finally:close(context)
    destination=Path(request['destination'])
    if count == 1:
        frames[0].save(destination, format='PNG', optimize=True)
    else:
        frames[0].save(destination,format='GIF',save_all=True,append_images=frames[1:],
                       duration=durations,loop=0,disposal=2,optimize=False)
    if destination.stat().st_size>8*1024*1024:
        destination.unlink();raise ValueError('Converted animation exceeds the native send bound')
    with Image.open(destination) as check:
        # Identical consecutive frames may be merged by the GIF encoder.
        saved_frames=getattr(check,'n_frames',1)
    return {'native_decoded':True,'source_format':'wxgf','transcoded':True,
        'source_sha256':hashlib.sha256(data).hexdigest(),'codec_sha256':codec['sha256'],
        'width':width,'height':height,'source_frames':count,'frames':saved_frames,
        'output_sha256':hashlib.sha256(destination.read_bytes()).hexdigest()}

def convert(source,destination,codec):
    request={'source':str(source),'destination':str(destination),'codec':codec}
    command=([sys.executable,'--wxgf-worker'] if getattr(sys,'frozen',False)
             else [sys.executable,str(Path(__file__).resolve())])
    result=subprocess.run(command,input=json.dumps(request),
        capture_output=True,text=True,timeout=30)
    if result.returncode:
        raise RuntimeError('Native WXGF decoder worker failed; no fallback image was substituted')
    report=json.loads(result.stdout)
    if not report.get('native_decoded'):raise ValueError('Native WXGF decode was not confirmed')
    return report

def verify(path,source_md5,codec):
    path=Path(path);data=path.read_bytes()
    if hashlib.md5(data).hexdigest()==source_md5:return {'transcoded':False,'verified_md5':True}
    manifest=json.loads(path.with_suffix(path.suffix+'.native.json').read_text())
    if (manifest.get('source_md5')!=source_md5 or not manifest.get('native_decoded')
            or manifest.get('codec_sha256')!=codec.get('sha256')
            or manifest.get('output_sha256')!=hashlib.sha256(data).hexdigest()):
        raise ValueError('Cached native animation provenance mismatch')
    return manifest

if __name__=='__main__':
    print(json.dumps(_worker(json.load(sys.stdin))))
