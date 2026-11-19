"""Read the selected client's live databases through its version-pinned C APIs.

No database file is opened, copied or decrypted outside WeChat. The agent only
accepts allowlisted tables and structured, bounded SELECT requests.
"""
from __future__ import annotations
import hashlib,json,re,threading,time
from importlib.resources import files

class NativeDatabase:
    def __init__(self,session):
        if session._session is None or session.mode not in {'receive','full'}:
            raise RuntimeError('Native database reads require a connected receive/full session')
        if not session.profile.get('nativeDatabase'):
            raise RuntimeError('This profile has no pinned native database read catalog')
        from pathlib import Path
        helper=session.profile['nativeDatabase'].get('bridge') or {}
        if not helper.get('path') or hashlib.sha256(Path(helper['path']).read_bytes()).hexdigest()!=helper.get('sha256'):
            raise RuntimeError('Native database mutex bridge fingerprint mismatch')
        self._lock=threading.RLock();self._script=None;self._contact_cache={}
        config={k:session.profile[k] for k in ('corePath','functions','nativeDatabase')}
        script=session._session.create_script('const CONFIG='+json.dumps(config)+';\n'+files(__package__).joinpath('database_agent.js').read_text())
        errors=[]
        script.on("message",lambda message,data:errors.append(message.get("description","Native database agent failed")) if message.get("type")=="error" else None)
        try:
            script.load()
            if errors:raise RuntimeError("; ".join(errors))
            self._script=script
            time.sleep(.25)  # Let any calls predating hook installation finish.
        except Exception:
            try:script.unload()
            except Exception:pass
            raise
    def close(self):
        with self._lock:
            if self._script:
                self._script.exports_sync.dispose()
                self._script.unload()
                self._script=None
    def catalog(self):
        with self._lock:return self._script.exports_sync.catalog()
    def read(self,database,table,columns=None,*,filters=(),order=(),limit=100,offset=0,schema=False):
        request={'database':database,'table':table,'columns':columns or [],'filters':list(filters),
                 'order':list(order),'limit':limit,'offset':offset,'schema':schema}
        with self._lock:
            for attempt in range(4):
                result=self._script.exports_sync.read(request)
                if result.get('code')!=5:break
                time.sleep(.025*(attempt+1))
        if result.get('code')!=0:raise RuntimeError('Native read failed: '+str(result.get('issue') or result.get('code')))
        return result['rows']
    def get_contact(self,user_id):
        if not isinstance(user_id,str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,128}',user_id):return None
        cached=self._contact_cache.get(user_id)
        if cached and time.monotonic()-cached[0]<300:return dict(cached[1])
        rows=self.read('contact.db','contact',['username','nick_name','remark','alias','is_in_chat_room'],
                       filters=[{'column':'username','value':user_id}],limit=2)
        if len(rows)!=1:return None
        row=rows[0];nickname=row.get('nick_name') or '';remark=row.get('remark') or ''
        contact={'user_id':user_id,'username':user_id,'nickname':nickname,'remark':remark,'alias':row.get('alias') or '',
                 'name':remark or nickname or user_id,'type':'group' if user_id.endswith('@chatroom') else 'friend'}
        if len(self._contact_cache)>=2000:self._contact_cache.pop(next(iter(self._contact_cache)))
        self._contact_cache[user_id]=(time.monotonic(),contact)
        return dict(contact)
    def resolve_contact(self,value):
        found={}
        for column in ('username','remark','nick_name','alias'):
            rows=self.read('contact.db','contact',['username'],filters=[{'column':column,'value':value}],limit=3)
            for row in rows:found[row['username']]=row
            if len(found)>1:return None
        return self.get_contact(next(iter(found))) if len(found)==1 else None
    @staticmethod
    def _text(hex_value):
        data=bytes.fromhex(hex_value or '')
        if not data:return ''
        if data.startswith(b'\x28\xb5\x2f\xfd'):
            import zstandard
            data=zstandard.ZstdDecompressor().decompress(data,max_output_size=1024*1024)
        return data.decode('utf-8')
    def get_history(self,chat_id,*,own_id,limit=50):
        if not re.fullmatch(r'[A-Za-z0-9_.@-]{1,128}',chat_id):raise ValueError('Expected an internal chat ID')
        if not 1<=limit<=2000:raise ValueError('History limit must be 1–2000')
        table='Msg_'+hashlib.md5(chat_id.encode()).hexdigest();messages={}
        databases=[d['name'] for d in self.catalog() if re.fullmatch(r'message_[0-9]+\.db',d['name'])]
        for database in databases:
            try:
                rows=self.read(database,table,['local_id','server_id','local_type','sort_seq','real_sender_id','create_time',
                    {'name':'message_content','encoding':'hex'},{'name':'compress_content','encoding':'hex'},
                    {'name':'source','encoding':'hex'}],order=[{'column':'sort_seq','desc':True}],limit=limit)
            except Exception as exc:
                if 'Table does not exist' in str(exc):continue
                raise
            ids=list({r['real_sender_id'] for r in rows if r.get('real_sender_id')})
            names=self.read(database,'Name2Id',['rowid','user_name'],filters=[{'column':'rowid','op':'in','value':ids}],limit=min(2000,len(ids))) if ids else []
            users={r['rowid']:r['user_name'] for r in names}
            for row in rows:
                sender=users.get(row['real_sender_id'],'');kind=int(row.get('local_type') or 0)&0xffffffff
                try:text=self._text(row['message_content']) or self._text(row['compress_content'])
                except (ValueError,UnicodeError,RuntimeError) as exc:raise RuntimeError('Stored native message could not be decoded') from exc
                if chat_id.endswith('@chatroom') and text.startswith(sender+':\n'):text=text[len(sender)+2:]
                message={'chat_id':chat_id,'message_id':str(row.get('server_id') or f'local:{database}:{row["local_id"]}'),
                    'sender':sender,'text':text,'message_type':kind,'timestamp':int(row['create_time']),
                    'direction':'outgoing' if sender==own_id else 'incoming','source_xml':self._text(row['source']),
                    'local_id':int(row['local_id']),'sort_seq':int(row['sort_seq'])}
                messages[message['message_id']]=message
        return sorted(messages.values(),key=lambda r:(r['timestamp'],r['sort_seq']))[-limit:]
    def get_sessions(self,limit=200):
        rows=self.read('session.db','SessionTable',['username','unread_count','type','last_timestamp','last_msg_sender','last_sender_display_name'],
                       order=[{'column':'last_timestamp','desc':True}],limit=limit)
        return [{'user_id':r['username'],'unread':int(r.get('unread_count') or 0),'timestamp':int(r.get('last_timestamp') or 0),
                 'last_sender':r.get('last_msg_sender'),'last_sender_name':r.get('last_sender_display_name')} for r in rows]

    def message_resources(self, message):
        """Resolve one exact server message; never search by attachment name."""
        server = str(message.get('message_id') or '')
        chat = str(message.get('chat_id') or '')
        if not server.isdecimal() or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,128}', chat):
            raise ValueError('Attachment needs an exact server message and chat ID')
        rows = self.read('message_resource.db', 'MessageResourceInfo',
            ['message_id', 'chat_id', 'message_local_id', 'message_svr_id', 'message_local_type',
             {'name':'packed_info', 'encoding':'hex'}],
            filters=[{'column':'message_svr_id', 'value':server}], limit=2)
        if len(rows) != 1:
            raise RuntimeError('Native attachment resource record is not ready or ambiguous')
        row = rows[0]
        # The resource identity is independently checked against its chat map.
        names = self.read('message_resource.db', 'ChatName2Id', ['rowid', 'user_name'],
            filters=[{'column':'rowid', 'value':row['chat_id']}], limit=2)
        if len(names) != 1 or names[0]['user_name'] != chat:
            raise ValueError('Attachment resource belongs to another chat')
        details = self.read('message_resource.db', 'MessageResourceDetail',
            ['resource_id','message_id','type','size','status','data_index',{'name':'packed_info','encoding':'hex'}],
            filters=[{'column':'message_id','value':row['message_id']}], limit=30)
        return {'message':row, 'resources':details}

    def all_rows(self,database,table,columns,*,filters=(),order=()):
        result=[]
        for offset in range(0,100000,1000):
            rows=self.read(database,table,columns,filters=filters,order=order,limit=1000,offset=offset)
            result.extend(rows)
            if len(rows)<1000:return result
        raise RuntimeError('Native catalog exceeds the supported read bound; no complete catalog was returned')

    def get_installed_stickers(self):
        favorites=self.all_rows('emoticon.db','kFavEmoticonOrderTable',['md5'])
        packages=self.all_rows('emoticon.db','kStoreEmoticonPackageTable',['package_id_','package_name_'],
            filters=[{'column':'download_status_','value':1},{'column':'remove_time_','value':0}],
            order=[{'column':'sort_order_'},{'column':'package_id_'}])
        pages=[];unsupported=[]
        favorite_items=[]
        for row in favorites:
            digest=(row.get('md5') or '').lower()
            if not re.fullmatch('[a-f0-9]{32}',digest):
                unsupported.append({'page':'收藏的表情','reason':'互动或管理项没有固定图片 MD5'});continue
            details=self.read('emoticon.db','kNonStoreEmoticonTable',['caption'],filters=[{'column':'md5','value':digest}],limit=1)
            favorite_items.append({'md5':digest,'name':(details[0].get('caption') if details else '') or '收藏的表情','locations':[{'page':'favorite','order':len(favorite_items)+1}]})
        pages.append({'id':'favorite','name':'收藏的表情','items':favorite_items})
        for package in packages:
            identity=package['package_id_'];flt=[{'column':'package_id_','value':identity}]
            captions=self.all_rows('emoticon.db','kStoreEmoticonCaptionsTable',['md5_','language_','caption_'],filters=flt)
            names={}
            for row in sorted(captions,key=lambda r:not (r.get('language_') or '').startswith('zh')):
                if row.get('caption_'):names.setdefault(row['md5_'],row['caption_'])
            rows=self.all_rows('emoticon.db','kStoreEmoticonFilesTable',
                ['md5_','sort_order_','emoticon_offset_','emoticon_size_','thumb_offset_','thumb_size_'],filters=flt,
                order=[{'column':'sort_order_'},{'column':'md5_'}])
            items=[]
            for row in rows:
                digest=(row.get('md5_') or '').lower()
                if not re.fullmatch('[a-f0-9]{32}',digest):continue
                location={'page':identity,'order':int(row['sort_order_'] or 0),
                    'offset':int(row['emoticon_offset_'] or 0),'size':int(row['emoticon_size_'] or 0),
                    'thumb_offset':int(row['thumb_offset_'] or 0),'thumb_size':int(row['thumb_size_'] or 0)}
                items.append({'md5':digest,'name':names.get(digest) or '未命名动画表情','locations':[location]})
            pages.append({'id':identity,'name':package['package_name_'] or identity,'items':items})
        return {'complete':True,'pages':pages,'unavailable':unsupported}

    def sticker_locations(self,digest):
        if not re.fullmatch('[a-f0-9]{32}',digest or ''):raise ValueError('Invalid sticker MD5')
        rows=self.read('emoticon.db','kStoreEmoticonFilesTable',
            ['package_id_','emoticon_offset_','emoticon_size_'],
            filters=[{'column':'md5_','value':digest}],limit=10)
        return [{'page':r['package_id_'],'offset':int(r['emoticon_offset_'] or 0),'size':int(r['emoticon_size_'] or 0)} for r in rows]
