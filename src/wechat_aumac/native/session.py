"""Version-pinned Frida session with explicit process and instruction checks."""
from __future__ import annotations
import hashlib
from importlib.resources import files
import json
import math
from pathlib import Path
import plistlib
import queue
import subprocess
import threading
import secrets
import time
import uuid
import xml.etree.ElementTree as ET

from .wire import decode, parse_add_message, parse_text_request, parse_text_response, text_request
from .guard import AgentGuard, AgentBusyError
from .media import image_request, parse_image_request, parse_image_response, validate_image_response
from .moments import (timeline_request, detail_request, parse_timeline_response, parse_detail_response,
                      interaction_request,unlike_request,text_post_request,parse_objectop_response)
from .media_experimental import (voice_request,sticker_request,video_request,amr_duration_ms,
                                 parse_voice_response,parse_sticker_response,parse_video_response,
                                 observed_requests,confirmed_observations)

from ..errors import WeChatAuMacError
from ..hook_probe import process_path


class NativeError(WeChatAuMacError):
    pass


class NativeSession:
    def __init__(self, profile: str | Path, *, mode: str = 'receive', observe_operations=None,
                 experimental_operations=(), read_operations=(), moments_operations=()):
        if mode not in {'inventory', 'receive', 'full', 'observe', 'codec'}:
            raise ValueError('mode must be inventory, receive, full, observe or codec')
        self.mode = mode
        self.profile = json.loads(Path(profile).read_text())
        if observe_operations is None:
            observe_operations=tuple(kind for kind in ('image','video','voice','sticker')
                                     if mode=='observe' and kind in self.profile.get('observations',{})
                                     and f'send_{kind}_server_ack' in self.profile.get('verified_capabilities',[]))
        self.observe_operations = tuple(dict.fromkeys(observe_operations))
        if self.observe_operations and mode != 'observe':
            raise ValueError('observe_operations requires observe mode')
        if any(op not in self.profile.get('observations', {}) for op in self.observe_operations):
            raise ValueError('Unknown native observation operation')
        self.experimental_operations = tuple(dict.fromkeys(experimental_operations))
        if self.experimental_operations and mode != 'full':
            raise ValueError('Experimental sends require full mode')
        if any(op not in {'image','video','voice','sticker'} or op not in self.profile.get('mediaSubmits',{})
               for op in self.experimental_operations):
            raise ValueError('Unknown experimental media operation; Moments writes are not enabled')
        self._media_operations = tuple(dict.fromkeys((*self.experimental_operations, *(
            kind for kind in ('image','video','voice','sticker')
            if mode=='full' and f'send_{kind}_server_ack' in self.profile.get('verified_capabilities',[]) ))))
        self._moment_operations=tuple(dict.fromkeys(moments_operations))
        mapping={'publish':'moment_post','like':'moment_interaction','comment':'moment_interaction','unlike':'moment_objectop'}
        if self._moment_operations and mode!='full':raise ValueError('Moments writing requires explicit full mode')
        if any(op not in mapping for op in self._moment_operations):raise ValueError('Unknown Moments operation')
        self._moment_kinds=tuple(dict.fromkeys(mapping[op] for op in self._moment_operations))
        if any(kind not in self.profile.get('momentSubmits',{}) for kind in self._moment_kinds):
            raise ValueError('This profile has no Moments write ABI catalog')
        target_read=('moment_detail',) if any(op!='publish' for op in self._moment_operations) else ()
        self._read_operations = tuple(dict.fromkeys((*read_operations,*target_read)))
        if self._read_operations and mode!='full':
            raise ValueError('Native network reads require full mode and a completion bridge')
        if any(op not in {'moment_timeline','moment_detail'} or op not in self.profile.get('readSubmits',{})
               for op in self._read_operations):
            raise ValueError('Unknown native read operation')
        self._session = None
        self._script = None
        self._events = queue.Queue(maxsize=2048)
        self._event_lock = threading.Lock()
        self._event_bytes = 0
        self._event_budget = 16 * 1024 * 1024
        self.dropped_events = 0
        self._detached = False
        self._guard = None
        self._replies = {}
        self._native_replies = {}
        self._reply_condition = threading.Condition()
        self._send_lock = threading.Lock()
        self._messages = []
        self._message_ids = set()
        self._outgoing = {}
        self._outgoing_media = {}
        self._own_user_id = None
        self.cleanup_errors = []

    def connect(self):
        if self._session is not None:
            raise NativeError('Native session is already connected')
        try:
            import frida
        except ImportError as exc:
            raise NativeError('Install the optional hook dependencies first') from exc
        profile = self.profile
        app = Path(profile['app']).resolve()
        core = Path(profile['corePath']).resolve()
        if not core.is_relative_to(app):
            raise NativeError('Core library must belong to selected app')
        with (app / 'Contents/Info.plist').open('rb') as stream:
            info = plistlib.load(stream)
        if str(info['CFBundleVersion']) != str(profile['build']):
            raise NativeError('WeChat build mismatch')
        digest = hashlib.sha256()
        with core.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != profile['sha256']:
            raise NativeError('Core library fingerprint mismatch; rebuild and validate profile')
        if self.mode == 'full':
            helper = profile.get('completionHelper')
            if not helper:
                raise NativeError('Full mode requires a validated native completion bridge')
            helper_digest = hashlib.sha256(Path(helper['path']).read_bytes()).hexdigest()
            if helper_digest != helper['sha256']:
                raise NativeError('Completion bridge fingerprint mismatch')
        result = subprocess.run(['pgrep', '-x', 'WeChat'], capture_output=True, text=True)
        pids = [int(x) for x in result.stdout.splitlines() if x.isdigit()]
        if len(pids) != 1:
            raise NativeError('Expected one WeChat process')
        actual = process_path(pids[0])
        if actual is None or Path(actual).resolve() != app / 'Contents/MacOS/WeChat':
            raise NativeError('Running executable does not match selected app')
        source = 'const CONFIG=' + json.dumps({**profile, 'runtimeMode': self.mode,
                                             'observeOperations':self.observe_operations,
                                             'experimentalOperations':self._media_operations,
                                             'readOperations':self._read_operations,
                                             'momentWriteKinds':self._moment_kinds}) + ';\n' + files(__package__).joinpath('agent.js').read_text()
        ready = threading.Event()
        errors = []

        def receive(message, data):
            if message.get('type') == 'error':
                errors.append(message.get('description', 'agent error'))
                ready.set()
            elif message.get('type') == 'send':
                value = message['payload']
                self._handle_event(value)
                if value.get('event') == 'ready':
                    ready.set()
        try:
            self._guard = AgentGuard(pids[0])
            try:
                self._guard.acquire()
            except AgentBusyError as exc:
                self._guard = None
                raise NativeError(str(exc)) from exc
            self._session = frida.attach(pids[0])
            self._detached = False
            def detached(*args):
                with self._reply_condition:
                    self._detached = True
                    self._reply_condition.notify_all()
            self._session.on('detached', detached)
            self._script = self._session.create_script(source)
            self._script.on('message', receive)
            self._script.load()
            if not ready.wait(5) or errors:
                raise NativeError('; '.join(errors) or 'Agent readiness timeout')
            if self.mode in {'full','observe'}:
                try:
                    self.identity()
                except NativeError:
                    pass  # Observation can also start before login completes.
            return self
        except Exception:
            self.close()
            raise

    def _rpc(self, method, *args):
        if self._script is None or self._detached:
            raise NativeError('Native session is disconnected; reconnect to the current process')
        try:
            return getattr(self._script.exports_sync, method)(*args)
        except Exception as exc:
            raise NativeError(f'Native {method} failed: {exc}') from exc

    def status(self) -> dict:
        return self._rpc('status')

    def identity(self) -> dict:
        """Read the current account identifier through the checked native getter."""
        result=self._rpc('identity')
        self._own_user_id=result['user_id']
        return result

    def roundtrip(self, data: bytes, *, kind: str = 'text') -> dict:
        """Parse/serialize a request object locally; never submits a task."""
        if len(data) > 4 * 1024 * 1024:
            raise ValueError('Codec payload exceeds 4 MiB')
        if kind != 'text' and kind not in self.profile.get('requestTypes', {}):
            raise ValueError('Unknown codec type')
        # Inspect malformed wire data on the host before entering native code.
        decode(data)
        if kind == 'text':
            return self._rpc('roundtrip', list(data))
        return self._rpc('roundtrip', list(data), kind)

    def _enqueue(self, value):
        size = self._event_size(value)
        with self._event_lock:
            if size > self._event_budget:
                self.dropped_events += 1
                return
            while self._event_bytes + size > self._event_budget or self._events.full():
                try:
                    removed = self._events.get_nowait()
                except queue.Empty:
                    break
                self._event_bytes -= self._event_size(removed)
                self.dropped_events += 1
            self._events.put_nowait(value)
            self._event_bytes += size

    @staticmethod
    def _event_size(value):
        # A Python list of byte references costs much more than the wire bytes.
        message = value.get('message', {})
        return 1024 + len(value.get('bytes', ())) * 8 + len(message.get('text', '')) * 4

    def _remember(self, message):
        identity = (message['chat_id'], message['message_id'])
        with self._reply_condition:
            if identity in self._message_ids:
                return False
            self._message_ids.add(identity)
            self._messages.append(message)
            if len(self._messages) > 2000:
                removed = self._messages.pop(0)
                self._message_ids.discard((removed['chat_id'], removed['message_id']))
        return True

    def _record_outgoing_image(self, request, response, timestamp=None):
        message={'message_id':response['server_message_id'],'chat_id':request['receiver'],
                 'from_user':request['sender'],'to_user':request['receiver'],'sender':request['sender'],
                 'text':'[图片]','message_type':3,'timestamp':int(timestamp or time.time()),
                 'direction':'outgoing','delivery_status':'server_acknowledged',
                 'media':{'kind':'image','bytes':request['total'],'client_id':request['client_id']}}
        if self._remember(message):
            self._enqueue({'event':'outgoing_message','message':message})

    def _handle_event(self, payload):
        value = dict(payload)
        event = value.get('event')
        try:
            if event == 'text_request':
                items = parse_text_request(bytes(value['bytes']))
                with self._reply_condition:
                    self._outgoing[value.get('scene',value['taskId'])] = items
                    if len(self._outgoing) > 256:
                        self._outgoing.pop(next(iter(self._outgoing)))
            elif event == 'text_response':
                with self._reply_condition:
                    self._replies[value['taskId']] = value
                    if len(self._replies) > 256:
                        self._replies.pop(next(iter(self._replies)))
                    items = self._outgoing.pop(value.get('scene',value['taskId']), [])
                    self._reply_condition.notify_all()
                reply = parse_text_response(bytes(value['bytes']))
                results = reply.get('results', [])
                if reply.get('acknowledged') and len(results) == len(items):
                    for item, result in zip(items, results):
                        if result.get(1) != 0 or result.get(8, 0) <= 0:
                            continue
                        outgoing = {'message_id':str(result[8]),'chat_id':item['receiver'],
                                    'from_user':self._own_user_id,'to_user':item['receiver'],'sender':self._own_user_id,
                                    'text':item['text'],'message_type':item.get('type',1),
                                    'timestamp':item.get('timestamp'), 'direction':'outgoing',
                                    'delivery_status':'server_acknowledged'}
                        if self._remember(outgoing):
                            self._enqueue({'event':'outgoing_message','message':outgoing})
            elif event == 'incoming_message':
                message = parse_add_message(bytes(value.pop('bytes')))
                if message['message_type'] == 51:
                    return
                message['direction'] = ('outgoing' if self._own_user_id and message['sender']==self._own_user_id
                                        else 'incoming')
                if message['direction']=='outgoing':
                    value['event']='outgoing_message'
                    message['delivery_status']='synchronized'
                if not self._remember(message):
                    return
                value['message'] = message
            elif event == 'native_response':
                with self._reply_condition:
                    self._native_replies[(value['operation'],value['taskId'])] = value
                    if len(self._native_replies)>256:
                        self._native_replies.pop(next(iter(self._native_replies)))
                    self._reply_condition.notify_all()
                    request=self._outgoing_media.pop((value['operation'],value.get('scene',value['taskId'])),None)
                if value['operation']=='image' and request is not None:
                    response=parse_image_response(bytes(value['bytes']))
                    if validate_image_response(request,response)=='acknowledged':
                        self._record_outgoing_image(request,response,value.get('time',time.time()*1000)/1000)
                elif request is not None and value['operation'] in {'video','voice','sticker'}:
                    for item,server_id in confirmed_observations(value['operation'],request,bytes(value['bytes'])):
                        details={k:item[k] for k in ['duration_ms','duration_seconds'] if k in item}
                        self._record_media(value['operation'],item['sender'],item['receiver'],item['client_id'],
                                           item['total'],server_id,**details)
            elif event == 'native_request' and value.get('operation') in {'image','video','voice','sticker'}:
                kind=value['operation']
                request=(parse_image_request(bytes(value['bytes'])) if kind=='image'
                         else observed_requests(kind,bytes(value['bytes']),self._own_user_id))
                with self._reply_condition:
                    self._outgoing_media[(kind,value.get('scene',value['taskId']))]=request
                    if len(self._outgoing_media)>256:
                        self._outgoing_media.pop(next(iter(self._outgoing_media)))
        except (ValueError, UnicodeError, KeyError, TypeError) as exc:
            self._enqueue({'event':'decode_error','source_event':event,'detail':str(exc)})
            # A malformed response remains available to the waiting sender and
            # raw observer; no successful outgoing-message event is invented.
            if event == 'incoming_message':
                return
        self._enqueue(value)

    def _submit_media_request(self, kind: str, payload: bytes, *, timeout: float = 15) -> dict:
        """Research transport, not a file sender; requires explicit experimental opt-in.

        A response payload is not interpreted as media delivery success here.
        No timeout retry, request replay, or Moments submission is implemented.
        """
        if self.mode!='full' or kind not in self._media_operations:
            raise NativeError('This experimental media operation is not enabled')
        return self._perform_native_request('submitMedia',kind,payload,timeout=timeout)

    def _fetch_native_request(self, kind: str, payload: bytes, *, timeout: float = 15) -> dict:
        if self.mode!='full' or kind not in self._read_operations:
            raise NativeError('This native read operation is not enabled')
        return self._perform_native_request('fetchNative',kind,payload,timeout=timeout)

    def _perform_native_request(self, rpc, kind, payload, *, timeout):
        if timeout<=0 or not math.isfinite(timeout):
            raise ValueError('timeout must be finite and positive')
        if not payload or len(payload)>1024*1024:
            raise ValueError('Media request exceeds transport bounds')
        decode(payload)
        with self._send_lock:
            submission=self._rpc(rpc,list(payload),kind)
            task=submission['taskId']
            if not submission.get('submitted'):
                return {'status':'rejected','task_id':task}
            key=(kind,task)
            deadline=time.monotonic()+timeout
            with self._reply_condition:
                while key not in self._native_replies:
                    remaining=deadline-time.monotonic()
                    if remaining<=0 or self._detached:
                        return {'status':'unconfirmed','task_id':task,
                                'detail':'no server response; do not retry automatically'}
                    self._reply_condition.wait(remaining)
                response=self._native_replies.pop(key)
            return {'status':'response_received','task_id':task,'bytes':bytes(response['bytes'])}

    def send_image(self, receiver_id: str, path: str | Path, *, timeout: float = 30) -> dict:
        """Send a PNG/JPEG with native 64 KiB chunks and strict server confirmation.

        Timeout covers the entire upload. A partially uploaded or unknown result
        is never retried automatically. Does not insert a local outgoing bubble.
        """
        if self.mode!='full' or 'send_image_server_ack' not in self.profile.get('verified_capabilities',[]):
            raise NativeError('Native image sending is not verified/enabled for this profile')
        if timeout<=0 or not math.isfinite(timeout):
            raise ValueError('timeout must be finite and positive')
        source=Path(path).expanduser().resolve()
        if source.stat().st_size>20*1024*1024:
            raise ValueError('Image exceeds 20 MiB')
        with source.open('rb') as stream:
            data=stream.read(20*1024*1024+1)
        if not data or len(data)>20*1024*1024 or not (
            data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff')):
            raise ValueError('Expected a PNG/JPEG image of at most 20 MiB')
        own=self.identity()['user_id']
        client='aumac_'+uuid.uuid4().hex
        # Validate destination before any request can be submitted.
        image_request(own,receiver_id,client,data[:65536],total=len(data),offset=0)
        deadline=time.monotonic()+timeout
        tasks=[]
        confirmed=0
        for offset in range(0,len(data),65536):
            remaining=deadline-time.monotonic()
            if remaining<=0:
                return {'status':'unconfirmed','client_id':client,'task_ids':tasks,
                        'uploaded_bytes':confirmed,'detail':'image upload timed out; do not retry automatically'}
            payload=image_request(own,receiver_id,client,data[offset:offset+65536],total=len(data),offset=offset)
            request=parse_image_request(payload)
            result=self._submit_media_request('image',payload,timeout=remaining)
            tasks.append(result['task_id'])
            if result['status']!='response_received':
                return {**result,'client_id':client,'task_ids':tasks,'uploaded_bytes':confirmed}
            try:
                response=parse_image_response(result['bytes'])
                status=validate_image_response(request,response)
            except (ValueError,UnicodeError) as exc:
                return {'status':'unconfirmed','client_id':client,'task_ids':tasks,'uploaded_bytes':confirmed,
                        'detail':f'inconsistent image response; do not retry automatically: {exc}'}
            if status=='rejected':
                return {'status':'rejected','client_id':client,'task_ids':tasks,'uploaded_bytes':confirmed,
                        'return_code':response['return_code']}
            confirmed=response['next_offset']
        self._record_outgoing_image(request,response)
        return {'status':'acknowledged','client_id':client,'task_ids':tasks,
                'uploaded_bytes':confirmed,'server_message_id':response['server_message_id'],
                'file_sha256':hashlib.sha256(data).hexdigest()}

    def get_moments(self, *, max_id: int = 0, timeout: float = 15) -> dict:
        """Fetch one visible timeline page through native command 211."""
        if 'read_moments_server_ack' not in self.profile.get('verified_capabilities',[]):
            raise NativeError('Native Moments reading is not verified for this profile')
        result=self._fetch_native_request('moment_timeline',timeline_request(max_id=max_id),timeout=timeout)
        if result['status']!='response_received':return result
        try:
            return {**parse_timeline_response(result['bytes']),'task_id':result['task_id']}
        except (ValueError,UnicodeError) as exc:
            raise NativeError(f'Could not parse native timeline response: {exc}') from exc

    def get_moment(self, post_id: str | int, *, timeout: float = 15) -> dict:
        """Fetch one post's details through native command 210; never writes."""
        if 'read_moments_server_ack' not in self.profile.get('verified_capabilities',[]):
            raise NativeError('Native Moments reading is not verified for this profile')
        payload=detail_request(post_id)
        result=self._fetch_native_request('moment_detail',payload,timeout=timeout)
        if result['status']!='response_received':return result
        try:
            decoded=parse_detail_response(result['bytes'])
            if decoded.get('post') and decoded['post']['post_id']!=str(post_id):
                raise ValueError('Detail response belongs to another post')
            return {**decoded,'task_id':result['task_id']}
        except (ValueError,UnicodeError) as exc:
            raise NativeError(f'Could not parse native post response: {exc}') from exc

    def prepare_moment(self,text: str,*,visibility: str) -> dict:
        """Build and native-codec-check a plain-text post, without publishing it."""
        own=self.identity()['user_id'];client=uuid.uuid4().hex
        payload,xml=text_post_request(own,text,visibility=visibility,client_id=client,timestamp=int(time.time()))
        result=self.roundtrip(payload,kind='moment_post')
        if not result.get('parsed') or bytes(result.get('bytes',[]))!=payload:
            raise NativeError('Native Moments post codec rejected or changed the draft')
        return {'operation':'publish','text':text,'visibility':visibility,'owner_id':own,
                'client_id':client,'description_xml':xml,'payload':payload,
                'native_codec_validated':True,'server_validated':False,'published':False}

    def _require_moment(self,operation,timeout):
        if self.mode!='full' or operation not in self._moment_operations:
            raise NativeError(f'Moments {operation} is disabled; explicitly enable this experimental operation first')
        if timeout<=0 or not math.isfinite(timeout):raise ValueError('timeout must be finite and positive')

    def _moment_write(self,kind,payload,*,timeout):
        codec=self.roundtrip(payload,kind=kind)
        if not codec.get('parsed') or bytes(codec.get('bytes',[]))!=payload:
            raise NativeError('Native Moments codec rejected or changed the request')
        return self._perform_native_request('writeMoment',kind,payload,timeout=timeout)

    def publish_moment(self,text: str,*,visibility: str,timeout: float=30) -> dict:
        """Experimental plain-text publishing; visibility is mandatory.

        No Moments write has been server-tested by this project. This method
        requires moments_operations=['publish'] and an explicit caller action.
        """
        self._require_moment('publish',timeout)
        draft=self.prepare_moment(text,visibility=visibility)
        result=self._moment_write('moment_post',draft['payload'],timeout=timeout)
        if result['status']!='response_received':return result
        try:
            decoded=parse_detail_response(result['bytes'])
            if decoded['status']=='rejected':return {**decoded,'task_id':result['task_id']}
            post=decoded['post']
            if post['owner_id']!=draft['owner_id'] or post['text']!=text:
                raise ValueError('Published post identity/content was not confirmed')
            privacy=ET.fromstring(post.get('description_xml','')).findtext('private')
            if privacy!=('1' if visibility=='private' else '0'):
                raise ValueError('Published post visibility was not confirmed')
            return {**decoded,'task_id':result['task_id'],'visibility':visibility,'experimental':True}
        except (ValueError,UnicodeError,ET.ParseError) as exc:
            return {'status':'unconfirmed','task_id':result['task_id'],
                    'detail':f'{exc}; the post may exist; do not retry automatically','experimental':True}

    def _interact_moment(self,operation,post_id,text,*,nickname,timeout):
        self._require_moment(operation,timeout)
        target=self.get_moment(post_id,timeout=timeout)
        if target.get('status')!='acknowledged' or not target.get('post'):
            raise NativeError('Could not read the exact target post; no interaction was submitted')
        own=self.identity()['user_id']
        payload=interaction_request(post_id,own,target['post']['owner_id'],client_id=uuid.uuid4().hex,
                                    action=1 if operation=='like' else 2,timestamp=int(time.time()),
                                    text=text,nickname=nickname)
        result=self._moment_write('moment_interaction',payload,timeout=timeout)
        if result['status']!='response_received':return result
        try:
            decoded=parse_detail_response(result['bytes'])
            if decoded.get('post') and decoded['post']['post_id']!=str(post_id):
                raise ValueError('Interaction response belongs to another post')
            return {**decoded,'task_id':result['task_id'],'operation':operation,'experimental':True}
        except (ValueError,UnicodeError) as exc:
            return {'status':'unconfirmed','task_id':result['task_id'],
                    'detail':f'{exc}; do not retry automatically','experimental':True}

    def like_moment(self,post_id: str|int,*,nickname: str='',timeout: float=15) -> dict:
        """Experimental native like; no live write validation has been performed."""
        return self._interact_moment('like',post_id,'',nickname=nickname,timeout=timeout)

    def comment_moment(self,post_id: str|int,text: str,*,nickname: str='',timeout: float=15) -> dict:
        """Experimental root comment; replies/deleting comments are not implemented."""
        if not text or '\0' in text or len(text.encode('utf-8'))>4096:
            raise ValueError('Comment must be nonempty and at most 4096 UTF-8 bytes')
        return self._interact_moment('comment',post_id,text,nickname=nickname,timeout=timeout)

    def unlike_moment(self,post_id: str|int,*,timeout: float=15) -> dict:
        """Experimental native unlike using object operation 5, not action 0."""
        self._require_moment('unlike',timeout)
        payload=unlike_request(post_id)
        target=self.get_moment(post_id,timeout=timeout)
        if target.get('status')!='acknowledged' or not target.get('post'):
            raise NativeError('Could not read the target post; no unlike was submitted')
        result=self._moment_write('moment_objectop',payload,timeout=timeout)
        if result['status']!='response_received':return result
        try:
            return {**parse_objectop_response(result['bytes']),'post_id':str(post_id),
                    'task_id':result['task_id'],'experimental':True}
        except (ValueError,UnicodeError) as exc:
            return {'status':'unconfirmed','task_id':result['task_id'],
                    'detail':f'{exc}; do not retry automatically','experimental':True}

    def _require_media(self, kind, timeout):
        if self.mode!='full' or kind not in self._media_operations:
            raise NativeError(f'Native {kind} sending is not enabled for this session')
        if timeout<=0 or not math.isfinite(timeout):raise ValueError('timeout must be finite and positive')

    @staticmethod
    def _media_file(path, maximum):
        source=Path(path).expanduser().resolve()
        if source.stat().st_size>maximum:raise ValueError('Media file exceeds the supported size')
        with source.open('rb') as stream:data=stream.read(maximum+1)
        if not data or len(data)>maximum:raise ValueError('Empty or oversized media file')
        return data

    def _record_media(self,kind,own,receiver,client,total,server_id,**details):
        message={'message_id':server_id,'chat_id':receiver,'from_user':own,'to_user':receiver,
                 'sender':own,'text':{'voice':'[语音]','sticker':'[动画表情]','video':'[视频]'}[kind],
                 'message_type':{'voice':34,'sticker':47,'video':43}[kind],
                 'timestamp':int(time.time()),'direction':'outgoing','delivery_status':'server_acknowledged',
                 'media':{'kind':kind,'bytes':total,'client_id':client,**details}}
        if self._remember(message):self._enqueue({'event':'outgoing_message','message':message})

    def send_voice(self,receiver_id: str,path: str|Path,*,timeout: float=30) -> dict:
        """Send pre-encoded AMR-NB (one chunk, at most 64 KiB / 60 seconds)."""
        self._require_media('voice',timeout)
        data=self._media_file(path,65536);duration=amr_duration_ms(data)
        own=self.identity()['user_id'];client='aumac_'+uuid.uuid4().hex
        payload=voice_request(own,receiver_id,client,data,duration_ms=duration,timestamp=int(time.time()))
        result=self._submit_media_request('voice',payload,timeout=timeout)
        if result['status']!='response_received':return result
        try:
            reply=parse_voice_response(result['bytes'])
            if reply['return_code']!=0:
                return {'status':'rejected','task_id':result['task_id'],'return_code':reply['return_code']}
            if not (reply['sender']==own and reply['receiver']==receiver_id and reply['client_id']==client
                    and reply['offset']+reply['length']==len(data) and reply['duration_ms']==duration
                    and reply['result_flag']==2
                    and int(reply['server_message_id'])>0):raise ValueError('Voice response mismatch')
        except (ValueError,UnicodeError,TypeError) as exc:
            return {'status':'unconfirmed','task_id':result['task_id'],'detail':f'{exc}; do not retry automatically'}
        self._record_media('voice',own,receiver_id,client,len(data),reply['server_message_id'],duration_ms=duration)
        return {'status':'acknowledged','task_id':result['task_id'],'server_message_id':reply['server_message_id'],
                'duration_ms':duration,'uploaded_bytes':len(data)}

    def send_sticker(self,receiver_id: str,path: str|Path,*,timeout: float=30) -> dict:
        """Send a GIF sticker of at most 64 KiB through native UploadEmoji."""
        self._require_media('sticker',timeout)
        data=self._media_file(path,65536)
        own=self.identity()['user_id'];client='aumac_'+uuid.uuid4().hex
        payload,digest=sticker_request(receiver_id,client,data)
        result=self._submit_media_request('sticker',payload,timeout=timeout)
        if result['status']!='response_received':return result
        try:
            reply=parse_sticker_response(result['bytes'])
            if reply['return_code']!=0:
                return {'status':'rejected','task_id':result['task_id'],'return_code':reply['return_code']}
            if len(reply['items'])!=1:raise ValueError('Unexpected sticker response count')
            item=reply['items'][0]
            if item['return_code']!=0:
                return {'status':'rejected','task_id':result['task_id'],'return_code':item['return_code']}
            if not (item['md5']==digest and item['total']==len(data) and item['offset']==len(data)
                    and int(item['server_message_id'])>0):raise ValueError('Incomplete sticker upload')
        except (ValueError,UnicodeError,TypeError) as exc:
            return {'status':'unconfirmed','task_id':result['task_id'],'detail':f'{exc}; do not retry automatically'}
        self._record_media('sticker',own,receiver_id,client,len(data),item['server_message_id'])
        return {'status':'acknowledged','task_id':result['task_id'],'server_message_id':item['server_message_id'],
                'uploaded_bytes':len(data),'md5':digest}

    def send_video(self,receiver_id: str,path: str|Path,*,thumbnail: str|Path,
                   duration_seconds: int,timeout: float=60) -> dict:
        """Send an MP4 with a JPEG thumbnail through native two-phase upload."""
        self._require_media('video',timeout)
        video=self._media_file(path,20*1024*1024);thumb=self._media_file(thumbnail,65536)
        if len(video)<12 or video[4:8]!=b'ftyp' or not thumb.startswith(b'\xff\xd8\xff'):
            raise ValueError('Expected an MP4 video and JPEG thumbnail')
        if isinstance(duration_seconds,bool) or not isinstance(duration_seconds,int) or not 0<duration_seconds<=600:
            raise ValueError('duration_seconds must be an integer from 1 through 600')
        own=self.identity()['user_id'];client='aumac_'+uuid.uuid4().hex
        deadline=time.monotonic()+timeout;tasks=[];uploaded=0
        for phase,whole in [(0,thumb),(1,video)]:
            for offset in range(0,len(whole),65536):
                remaining=deadline-time.monotonic()
                if remaining<=0:
                    return {'status':'unconfirmed','task_ids':tasks,'detail':'video upload timeout; do not retry automatically'}
                chunk=whole[offset:offset+65536]
                payload=video_request(own,receiver_id,client,thumb_total=len(thumb),video_total=len(video),
                                      duration_seconds=duration_seconds,phase=phase,offset=offset,data=chunk)
                result=self._submit_media_request('video',payload,timeout=remaining);tasks.append(result['task_id'])
                if result['status']!='response_received':return {**result,'task_ids':tasks}
                try:
                    reply=parse_video_response(result['bytes'])
                    if reply['return_code']!=0:
                        return {'status':'rejected','task_ids':tasks,'return_code':reply['return_code']}
                    expected_thumb=offset+len(chunk) if phase==0 else len(thumb)
                    expected_video=0 if phase==0 else offset+len(chunk)
                    if not (reply['client_id']==client and reply['thumb_offset']==expected_thumb
                            and reply['video_offset']==expected_video):raise ValueError('Video chunk response mismatch')
                    if phase==1 and expected_video==len(video) and int(reply['server_message_id'])<=0:
                        raise ValueError('Final video response has no message ID')
                except (ValueError,UnicodeError,TypeError) as exc:
                    return {'status':'unconfirmed','task_ids':tasks,'detail':f'{exc}; do not retry automatically'}
                if phase==1:uploaded=expected_video
        self._record_media('video',own,receiver_id,client,len(video),reply['server_message_id'],duration_seconds=duration_seconds)
        return {'status':'acknowledged','task_ids':tasks,'server_message_id':reply['server_message_id'],
                'uploaded_bytes':uploaded,'thumbnail_bytes':len(thumb)}

    def send_text(self, receiver_id: str, text: str, *, timeout: float = 15) -> dict:
        """Submit through native code and wait for an explicit server result.

        Uses an internal ID, never a display name. Does not retry on timeout.
        Native submission bypasses the UI's local outgoing bubble insertion.
        """
        if self._script is None:
            raise NativeError('Native session is not connected')
        if self.mode != 'full':
            raise NativeError('Sending requires an explicit full-mode native session')
        if 'send_text_server_ack' not in self.profile.get('verified_capabilities', []):
            raise NativeError('Native text sending is not verified for this profile')
        if timeout <= 0 or not math.isfinite(timeout):
            raise ValueError('timeout must be finite and positive')
        payload = text_request(receiver_id, text, int(time.time()), secrets.randbits(32))
        with self._send_lock:
            submission = self._rpc('submit', list(payload))
            task = submission['taskId']
            if not submission.get('submitted'):
                return {'status': 'rejected', 'task_id': task, 'detail': 'native submission failed'}
            deadline = time.monotonic() + timeout
            with self._reply_condition:
                while task not in self._replies:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or self._detached:
                        return {'status': 'unconfirmed', 'task_id': task, 'detail': 'server reply timeout; do not retry automatically'}
                    self._reply_condition.wait(remaining)
                event = self._replies.pop(task)
            try:
                result = parse_text_response(bytes(event['bytes']))
            except (ValueError, KeyError, TypeError) as exc:
                return {'status':'unconfirmed','task_id':task,
                        'detail':f'malformed server reply; do not retry automatically: {exc}'}
            results = result.get('results', [])
            confirmed = (result.get('acknowledged') and len(results) == 1
                         and results[0].get(1) == 0 and results[0].get(8, 0) > 0)
            return {'status': 'acknowledged' if confirmed else 'rejected',
                    'task_id': task, 'server_message_id': str(results[0][8]) if confirmed else None,
                    'response': result}

    def read(self, chat_id: str | None = None, *, limit: int = 50) -> list[dict]:
        """Return messages observed since connecting, not stored chat history."""
        if limit < 1:
            raise ValueError('limit must be positive')
        with self._reply_condition:
            return [dict(m) for m in self._messages if chat_id is None or m['chat_id'] == chat_id][-limit:]

    def watch(self, chat_id: str | None = None, *, direction: str = 'incoming'):
        """Yield incoming AddMsg and/or server-acknowledged outgoing text."""
        if direction not in {'incoming','outgoing','both'}:
            raise ValueError('direction must be incoming, outgoing or both')
        if direction != 'incoming' and self.mode not in {'full','observe'}:
            raise NativeError('Outgoing observation requires full or observe mode')
        while self._session is not None and not self._detached:
            event = self.next_event()
            accepted = ({'incoming_message','outgoing_message'} if direction=='both'
                        else {direction+'_message'})
            if event and event.get('event') in accepted:
                message = event['message']
                if chat_id is None or message['chat_id'] == chat_id:
                    yield message
        if self._detached:
            raise NativeError('WeChat exited or restarted; the native watcher has stopped')

    def next_event(self, timeout: float = 1) -> dict | None:
        try:
            event = self._events.get(timeout=timeout)
            with self._event_lock:
                self._event_bytes -= self._event_size(event)
            return event
        except queue.Empty:
            return None

    def close(self):
        try:
            if self._session is not None and not self._detached:
                try:
                    if self._script is not None:
                        try:
                            self._script.exports_sync.dispose()
                        finally:
                            self._script.unload()
                except Exception as exc:
                    self.cleanup_errors.append(str(exc))
                finally:
                    try:
                        self._session.detach()
                    except Exception as exc:
                        if not self._detached:
                            self.cleanup_errors.append(str(exc))
        finally:
            self._script = None
            self._session = None
            if self._guard is not None:
                self._guard.release()
                self._guard = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()
