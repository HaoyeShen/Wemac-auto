"""Export cached artwork with WeChat's account-bound native resource getter."""
from __future__ import annotations
import hashlib,json,re,threading,tempfile
from pathlib import Path
from importlib.resources import files

class NativeResources:
    def __init__(self,session):
        if session._session is None or not session.profile.get('nativeResources'):
            raise RuntimeError('This profile has no native cached-resource ABI')
        self.session=session;self._lock=threading.RLock()
        rows=[r for r in session._database().catalog() if r['name']=='emoticon.db']
        if len(rows)!=1:raise RuntimeError('The active account resource directory is ambiguous')
        self.root=Path(rows[0]['path']).parents[2].resolve()
        self.owner=session.identity()['user_id']
        if not self.root.name.startswith(self.owner+'_'):raise RuntimeError('Resource directory belongs to another account')
        config={k:session.profile[k] for k in ('corePath','functions')};config['accountRoot']=str(self.root)
        script=session._session.create_script('const CONFIG='+json.dumps(config)+';\n'+files(__package__).joinpath('resource_agent.js').read_text())
        errors=[]
        script.on('message',lambda message,data:errors.append(message.get('description','Resource agent error')) if message.get('type')=='error' else None)
        try:
            script.load()
            if errors:raise RuntimeError('; '.join(errors))
        except Exception:
            script.unload();raise
        self._script=script
    def close(self):
        with self._lock:
            if self._script:
                self._script.exports_sync.dispose()
                self._script.unload()
                self._script=None
    def _decode(self,path,offset=0,length=0,material=None,variant=0):
        if self.session.identity()['user_id']!=self.owner:raise RuntimeError('Account changed; reconnect resource reader')
        path=path.resolve()
        if not path.is_relative_to(self.root):raise ValueError('Cached resource outside the selected account')
        with self._lock:result=self._script.exports_sync.decode(str(path),offset,length,material,variant)
        return bytes(result['bytes'])

    def _decode_file(self,path):
        if self.session.identity()['user_id']!=self.owner:raise RuntimeError('Account changed; reconnect resource reader')
        path=Path(path).resolve()
        if not path.is_relative_to(self.root) or not 0<path.stat().st_size<=32*1024*1024:
            raise ValueError('Cached attachment outside account or exceeds 32 MiB')
        with self._lock:result=self._script.exports_sync.decode_image(str(path))
        return bytes(result['bytes'])

    def download_image(self,message,directory):
        from .cards import parse_xml
        from .wire import decode
        from datetime import datetime
        import io
        from PIL import Image
        xml=parse_xml(message.get('text') or '')
        node=xml if xml.tag=='img' else xml.find('.//img')
        if node is None:raise ValueError('Image message has no native resource metadata')
        digest=str(node.get('md5') or '').lower()
        if not re.fullmatch('[a-f0-9]{32}',digest):raise ValueError('Image has no exact content digest')
        folder=Path(directory).expanduser().resolve();folder.mkdir(parents=True,exist_ok=True)
        destination=folder/(digest+'.image')
        if destination.is_file():
            try:
                data=destination.read_bytes()
                if hashlib.md5(data).hexdigest()==digest:return destination
                proof=json.loads(destination.with_suffix(destination.suffix+'.native.json').read_text())
                if (proof.get('source_md5')==digest and proof.get('native_decoded')
                        and proof.get('output_sha256')==hashlib.sha256(data).hexdigest()):return destination
                raise ValueError('Image provenance differs')
            except (ValueError,OSError):pass
        names=[]
        try:
            record=self.session._database().message_resources(message)
            for number,kind,value in decode(bytes.fromhex(record['message'].get('packed_info') or '')):
                if number!=2 or kind!=2:continue
                for n,k,v in decode(value):
                    if n==1 and k==2:
                        name=v.decode('ascii')
                        if re.fullmatch('[a-f0-9]{32}',name):names.append(name)
        except RuntimeError:pass  # Resource rows can lag behind the sync notification.
        chat=hashlib.md5(message['chat_id'].encode()).hexdigest()
        month=datetime.fromtimestamp(float(message['timestamp'])).strftime('%Y-%m')
        base=self.root/'msg/attach'/chat/month/'Img'
        # Exact content verification prevents using either a stale bubble or a
        # thumbnail as if it were the full image.
        failures=[]
        paths=[base/(name+suffix) for name in set(names) for suffix in ('_h.dat','.dat')]
        for path in paths:
            if not path.is_file():continue
            try:
                data=self._verified(self._decode_file(path),digest)
                if data.startswith(b'wxgf'):
                    from .wxgf import convert
                    codec=self.session.profile['nativeResources'].get('wxgfCodec') or {}
                    with tempfile.TemporaryDirectory(prefix='wemac-image-') as temp:
                        source=Path(temp)/'source.wxgf';source.write_bytes(data)
                        report=convert(source,destination,codec)
                    report.update(source_md5=digest,quality='full',message_id=str(message['message_id']))
                    destination.with_suffix(destination.suffix+'.native.json').write_text(json.dumps(report))
                else:
                    with Image.open(io.BytesIO(data)) as image:
                        if image.width*image.height>32_000_000:raise ValueError('Image dimensions exceed bound')
                        image.verify()
                    destination.write_bytes(data)
                destination.chmod(0o600);return destination
            except Exception as exc:failures.append(type(exc).__name__)
        # The native CDN returns a compatible decoded JPEG for WXGF sources;
        # its bytes need not equal the message's original compressed MD5.
        # Bind the result to the exact per-message file ID and native completion.
        if self.session.profile.get('nativeCdnDownload'):
            proof=self.session._cdn_download().download(node.get('cdnmidimgurl') or node.get('cdnbigimgurl') or '',
                node.get('aeskey') or '',expected_size=int(node.get('length') or 0))
            source=Path(proof['path']);data=source.read_bytes()
            with Image.open(io.BytesIO(data)) as image:
                if image.width*image.height>32_000_000:raise ValueError('Native image dimensions exceed bound')
                width,height=image.size;image.verify()
            destination.write_bytes(data);destination.chmod(0o600)
            proof.update(native_decoded=True,source_md5=digest,quality='full',message_id=str(message['message_id']),width=width,height=height)
            proof.pop('path',None)
            destination.with_suffix(destination.suffix+'.native.json').write_text(json.dumps(proof))
            return destination
        raise RuntimeError('Full native image resource is not ready: '+','.join(failures))

    def download_attachment(self,message,directory):
        from .cards import parse_xml
        text=message.get('text') or ''
        if message.get('chat_id','').endswith('@chatroom'):
            text=re.sub(r'^[A-Za-z0-9_.@-]{1,128}:\r?\n(?=<)','',text)
        root=parse_xml(text)
        app=root if root.tag=='appmsg' else root.find('.//appmsg')
        if app is None or app.findtext('type')!='6':raise ValueError('Not a native file message')
        attach=app.find('appattach')
        if attach is None:raise ValueError('File message has no attachment metadata')
        name=Path((app.findtext('title') or 'attachment').replace('\\','/')).name
        ext=attach.findtext('fileext') or ''
        if not Path(name).suffix and re.fullmatch('[A-Za-z0-9]{1,12}',ext):name+='.'+ext
        name=re.sub(r'[\x00-\x1f/:]', '_', name)[:180]
        suffix=Path(name).suffix[:16]
        stem=name[:-len(suffix)] if suffix else name
        name=stem.encode('utf-8')[:180].decode('utf-8','ignore')+suffix
        if name in ('','.','..'):raise ValueError('Invalid native attachment name')
        size=int(attach.findtext('totallen') or 0)
        if not 0<size<=32*1024*1024:raise ValueError('Attachment exceeds 32 MiB')
        proof=self.session._cdn_download().download(attach.findtext('cdnattachurl') or '',
            attach.findtext('aeskey') or '',kind='file',expected_size=size)
        folder=Path(directory).resolve();folder.mkdir(parents=True,exist_ok=True)
        key=hashlib.sha256((message['chat_id']+':'+str(message['message_id'])).encode()).hexdigest()[:20]
        destination=folder/(key+'-'+name)
        if destination.is_symlink():raise ValueError('Attachment output must be a regular file')
        destination.write_bytes(Path(proof['path']).read_bytes());destination.chmod(0o600)
        return destination
    @staticmethod
    def _verified(data,digest):
        if hashlib.md5(data).hexdigest()==digest:return data
        pad=data[-1] if data else 0
        if 0<pad<=16 and data[-pad:]==bytes([pad])*pad:
            candidate=data[:-pad]
            if hashlib.md5(candidate).hexdigest()==digest:return candidate
        raise ValueError('Decoded artwork does not match the exact message/sticker MD5')
    def _write_artwork(self,data,digest,destination,location):
        if not data.startswith(b'wxgf'):
            destination.write_bytes(self._verified(data,digest));return destination
        # WXGF is WeChat's native representation, not a GIF Pillow can open.
        # It must be decoded even when its MD5 already matches the message.
        codec=self.session.profile['nativeResources'].get('wxgfCodec')
        if not codec:raise ValueError('Native WXGF codec is not pinned')
        pad=data[-1] if data else 0
        if 0<pad<=16 and data[-pad:]==bytes([pad])*pad:data=data[:-pad]
        from .wxgf import convert
        with tempfile.TemporaryDirectory(prefix='wemac-wxgf-') as temp:
            source=Path(temp)/'source.wxgf';source.write_bytes(data)
            report=convert(source,destination,codec)
        report.update(source_md5=digest,resource_location=location)
        destination.with_suffix(destination.suffix+'.native.json').write_text(json.dumps(report))
        destination.chmod(0o600);return destination
    def download_sticker(self,entry,directory):
        digest=str(entry.get('md5') or '').lower()
        if not re.fullmatch('[a-f0-9]{32}',digest):raise ValueError('Expected a verified sticker MD5')
        folder=Path(directory).expanduser().resolve();folder.mkdir(parents=True,exist_ok=True)
        destination=folder/(digest+'.image')
        if destination.is_file():
            try:
                data=destination.read_bytes()
                if data.startswith(b'wxgf'):return self._write_artwork(data,digest,destination,'previous-native-cache')
                self.verify_sticker_file(entry,destination);return destination
            except ValueError:destination.unlink()
        candidates=[]
        for location in entry.get('locations',[]):
            if location.get('page') in (None,'favorite'):continue
            package=hashlib.md5(location['page'].encode()).hexdigest()
            path=self.root/'business/emoticon/PersistStore'/package[:2]/package
            candidates.append((path,int(location.get('offset') or 0),int(location.get('size') or 0)))
        candidates.append((self.root/'business/emoticon/Persist'/digest[:2]/digest,0,0))
        candidates.extend((p,0,0) for p in (self.root/'cache').glob('????-??/Emoticon/'+digest[:2]+'/'+digest))
        failures=[]
        for path,offset,size in candidates:
            if not path.is_file():continue
            try:
                if path.stat().st_size>64*1024*1024:raise ValueError('Resource container too large')
                data=self._decode(path,offset,size)
                return self._write_artwork(data,digest,destination,str(path.relative_to(self.root)))
            except Exception as exc:failures.append(type(exc).__name__)
        # Non-store emoji may retain their own CDN encryption instead of the
        # installed-pack cipher. Keep this material inside the WeChat process.
        database=self.session._database();material=None
        try:
            with database._lock:material=database._script.exports_sync.emoji_material(digest)
            for path,offset,size in candidates:
                if not path.is_file() or offset:continue
                for variant in (0,1,2):
                    try:
                        data=self._decode(path,0,0,material,variant)
                        return self._write_artwork(data,digest,destination,str(path.relative_to(self.root)))
                    except Exception:continue
        except Exception as exc:failures.append(type(exc).__name__)
        finally:
            if material:
                with database._lock:database._script.exports_sync.release_material(material['id'])
        raise RuntimeError('Exact cached sticker unavailable through native resource decoding: '+','.join(failures))

    def verify_sticker_file(self,entry,path):
        from .wxgf import verify
        return verify(path,str(entry.get('md5') or '').lower(),
                      self.session.profile['nativeResources'].get('wxgfCodec') or {})

    def download_emoji(self,entry,node,directory):
        """A sync notification can arrive before WeChat populates its pack cache."""
        try:return self.download_sticker(entry,directory)
        except (ValueError,RuntimeError,OSError):pass
        from urllib.parse import urlsplit,urlunsplit
        digest=str(entry.get('md5') or '').lower()
        if not re.fullmatch('[a-f0-9]{32}',digest):raise ValueError('Emoji has no exact digest')
        url=node.get('cdnurl') or ''
        parts=urlsplit(url)
        if parts.scheme=='http':url=urlunsplit(parts._replace(scheme='https'))
        if not url:raise RuntimeError('Full emoji is not cached and has no original CDN URL')
        # Use WeChat's HTTPS function, never a thumbnail or an encrypted URL
        # masquerading as decoded artwork. Digest validation is mandatory.
        receipt=self.session.download_public_resource(url,timeout=15)
        data=self._verified(Path(receipt['path']).read_bytes(),digest)
        folder=Path(directory).resolve();folder.mkdir(parents=True,exist_ok=True)
        destination=folder/(digest+'.image')
        return self._write_artwork(data,digest,destination,'native-original-cdn')
