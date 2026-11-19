"""Account-bound SNS image uploads through the selected WeChat's native CDN API."""
import hashlib,io,json,math,threading,time,uuid
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

def validate_result(result,key,data):
    if not result.get('ready'):return False
    if result.get('return_code') or result.get('secondary_error'):raise ValueError('Native SNS upload failed')
    if (result.get('client_id')!=key or result.get('data_type')!=3 or result.get('file_type')!=101
            or result.get('scene')!=20201 or result.get('uploaded_bytes')!=len(data)
            or result.get('md5','').lower()!=hashlib.md5(data).hexdigest()):
        raise ValueError('Native SNS upload identity, length or checksum differs')
    for field in ('url','thumb'):
        url=result.get(field,'');parsed=urlsplit(url)
        if (not isinstance(url,str) or len(url)>8192 or parsed.scheme not in ('http','https')
                or parsed.hostname!='mmsns.qpic.cn' or parsed.username or parsed.password
                or parsed.port is not None or not parsed.path.startswith('/mmsns/') or parsed.fragment):
            raise ValueError('Native SNS upload returned an unexpected media URL')
    return True

class NativeSnsUpload:
    def __init__(self,session):
        if session._session is None or session.mode!='full':raise RuntimeError('SNS uploads require a connected full session')
        self.session=session;self._script=None;self._lock=threading.RLock()
        config=session.profile.get('nativeSnsUpload') or {};bridge=config.get('bridge') or {}
        if not bridge.get('path') or hashlib.sha256(Path(bridge['path']).read_bytes()).hexdigest()!=bridge.get('sha256'):
            raise RuntimeError('SNS upload bridge fingerprint mismatch')
        self.folder=Path(config['cacheRoot']).expanduser().resolve()
        bundle=session.profile.get('bundle_id')
        allowed=Path.home()/'Library/Containers'/str(bundle)/'Data/Library/Caches/Wemac-auto/SNS'
        if not bundle or self.folder!=allowed.resolve():raise ValueError('SNS cache must belong to the selected client container')
        self.folder.mkdir(parents=True,exist_ok=True)
        options={k:session.profile[k] for k in ('corePath','functions','nativeSnsUpload')}
        script=session._session.create_script('const CONFIG='+json.dumps(options)+';\n'+files(__package__).joinpath('sns_upload_agent.js').read_text())
        errors=[]
        script.on('message',lambda m,d:errors.append(m.get('description','SNS agent failed')) if m.get('type')=='error' else None)
        try:
            script.load()
            if errors:raise RuntimeError('; '.join(errors))
            self._script=script
        except Exception:
            script.unload();raise
    def upload(self,path,*,timeout=40):
        if not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or timeout<=0:raise ValueError('Invalid SNS timeout')
        path=Path(path).expanduser().resolve()
        if not path.is_file() or not 0<path.stat().st_size<=32*1024*1024:raise ValueError('SNS source image must be at most 32 MiB')
        from PIL import Image,ImageOps
        with Image.open(path) as image:
            if image.format not in ('JPEG','PNG','WEBP','GIF') or not 0<image.width*image.height<=16_000_000:raise ValueError('SNS upload expects a bounded image')
            frame=ImageOps.exif_transpose(image).convert('RGBA');frame.thumbnail((2048,2048))
            background=Image.new('RGBA',frame.size,'white');background.alpha_composite(frame)
            output=io.BytesIO();background.convert('RGB').save(output,format='JPEG',quality=90,optimize=True)
            width,height=background.size
        data=output.getvalue()
        if len(data)>8*1024*1024:raise ValueError('SNS JPEG exceeds 8 MiB')
        digest=hashlib.sha256(data).hexdigest();staged=self.folder/(digest+'.jpg')
        # A path outside this container is inaccessible to the sandboxed client.
        key='wemac_sns_'+uuid.uuid4().hex
        with self.session._rpc_lock,self._lock:
            if self.session._closing or self._script is None:raise RuntimeError('SNS upload session is closing')
            if staged.is_symlink():raise ValueError('SNS staging path must be a regular file')
            if not staged.exists() or hashlib.sha256(staged.read_bytes()).hexdigest()!=digest:staged.write_bytes(data)
            staged.chmod(0o600)
            api=self._script.exports_sync;job=api.prepare(key,str(staged))
            code=api.upload(job['id'])
            if code:
                api.release(job['id']);return {'status':'rejected','return_code':code,'stage':'image_upload','published':False}
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline and not self.session._detached:
                result=api.result(job['id'])
                if result.get('ready'):
                    try:
                        validate_result(result,key,data)
                        return {**result,'status':'acknowledged','width':width,'height':height,'source_sha256':digest,'published':False}
                    finally:api.release(job['id'])
                time.sleep(.1)
            # Native-owned callbacks and input files remain valid after timeout.
            return {'status':'unconfirmed','stage':'image_upload','published':False,'upload_job':job['id'],'client_id':key}
    def close(self):
        with self._lock:
            if self._script:
                self._script.exports_sync.dispose();self._script.unload();self._script=None
