"""Receive exact message attachments with the selected client's native CDN API."""
import hashlib,json,re,threading,time,uuid
from pathlib import Path
from importlib.resources import files

MAX_BYTES=32*1024*1024
class NativeCdnDownload:
    def __init__(self,session):
        if session._session is None or session.mode not in ('receive','full'):
            raise RuntimeError('Native attachment reads require a connected receive/full session')
        self.session=session;self._script=None;self._lock=threading.RLock()
        config=session.profile.get('nativeCdnDownload') or {};bridge=config.get('bridge') or {}
        if not bridge.get('path') or hashlib.sha256(Path(bridge['path']).read_bytes()).hexdigest()!=bridge.get('sha256'):
            raise RuntimeError('Native CDN reader fingerprint unavailable or changed')
        root=Path.home()/'Library/Containers'/str(session.profile.get('bundle_id'))/'Data/Library/Caches/Wemac-auto/Downloads'
        self.root=Path(config['cacheRoot']).resolve()
        if self.root!=root.resolve():raise ValueError('CDN output must belong to the selected WeChat container')
        self.root.mkdir(parents=True,exist_ok=True)
        self.root.chmod(0o700)
        options={k:session.profile[k] for k in ('corePath','functions','nativeCdnDownload')}
        script=session._session.create_script('const CONFIG='+json.dumps(options)+';\n'+files(__package__).joinpath('cdn_download_agent.js').read_text())
        errors=[];script.on('message',lambda m,d:errors.append(m.get('description','Native CDN agent failed')) if m.get('type')=='error' else None)
        try:
            script.load()
            if errors:raise RuntimeError('; '.join(errors))
            self._script=script
        except Exception:
            script.unload();raise
    def download(self,file_id,aes_key,*,kind='image',expected_size=0,timeout=30):
        if (not isinstance(file_id,str) or not 1<=len(file_id)<=8192 or '\0' in file_id
                or (kind!='http' and not re.fullmatch(r'[a-fA-F0-9]{32}(?:[a-fA-F0-9]{32})?',aes_key or ''))):
            raise ValueError('Native attachment CDN metadata is incomplete')
        if kind not in ('image','file','video','http') or not 0<=int(expected_size)<=MAX_BYTES or not 0<timeout<=60:
            raise ValueError('Native attachment download exceeds bounds')
        if kind=='http':
            import socket,ipaddress
            from urllib.parse import urlsplit
            parsed=urlsplit(file_id)
            if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443) or any(ord(c)<33 for c in file_id):
                raise ValueError('Native public download requires a public HTTPS URL')
            addresses=socket.getaddrinfo(parsed.hostname,443,type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
                raise ValueError('Native public download refuses local or private addresses')
        key='wemac_read_'+uuid.uuid4().hex;path=self.root/(key+'.bin')
        with self.session._rpc_lock,self._lock:
            if self.session._closing or self._script is None:raise RuntimeError('Native CDN reader is closing')
            api=self._script.exports_sync;job=api.start(key,file_id,aes_key,str(path),{'image':2,'file':5,'video':4,'http':8}[kind])
            if job['code']:
                api.release(job['id']);raise RuntimeError('Native CDN request rejected: '+str(job['code']))
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline and not self.session._detached:
                result=api.status(job['id'])
                if result['ready']:
                    try:
                        if result['error'] or result['secondary']:raise RuntimeError('Native CDN download failed: '+str(result['error']))
                        if not path.is_file() or path.is_symlink() or not 0<path.stat().st_size<=MAX_BYTES:
                            raise ValueError('Native downloaded attachment size is invalid')
                        if kind=='file' and expected_size and path.stat().st_size!=int(expected_size):
                            raise ValueError('Native attachment length differs from the message')
                        path.chmod(0o600)
                        return {'path':str(path),'native_download':True,'output_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                    finally:api.release(job['id'])
                time.sleep(.1)
        raise RuntimeError('Native attachment download is unconfirmed; no automatic duplicate request')
    def close(self):
        with self._lock:
            if self._script:self._script.exports_sync.dispose();self._script.unload();self._script=None
