'use strict';
// Read-only calls into the client's own, already-open embedded SQLite engine.
// No keys, file opens, ATTACH, PRAGMA writes, or database mutations are exposed.
const module=Process.enumerateModules().find(m=>m.path===CONFIG.corePath);
if(!module||Process.arch!=='arm64')throw Error('Native database module mismatch');
const base=module.base,layout=CONFIG.nativeDatabase,functions={};
for(const [name,entry] of Object.entries(CONFIG.functions)){
    if(!name.startsWith('database'))continue;
    const p=base.add(entry.offset);
    const head=Array.from(new Uint8Array(p.readVolatile(entry.head.length/2))).map(b=>b.toString(16).padStart(2,'0')).join('');
    if(head!==entry.head)throw Error('Database instruction mismatch: '+name);
    functions[name]=p;
}
if(new NativeFunction(functions.databaseVersion,'int',[])()!==layout.version)throw Error('Embedded database version mismatch');
for(const [slot,name] of [[layout.mutexTrySlot,'databaseMutexTry'],[layout.mutexLeaveSlot,'databaseMutexLeave']]){
    if(!base.add(slot).readPointer().equals(functions[name]))throw Error('Database mutex implementation mismatch');
}
const nativeExec=new NativeFunction(functions.databaseExec,'int',['pointer','pointer','pointer','pointer','pointer']);
const dlerror=new NativeFunction(Module.getGlobalExportByName('dlerror'),'pointer',[]);
const dlopen=new NativeFunction(Module.getGlobalExportByName('dlopen'),'pointer',['pointer','int']);
if(dlopen(Memory.allocUtf8String(layout.bridge.path),0x2|0x80).isNull()){const error=dlerror();throw Error('Cannot load permanent database mutex bridge: '+(error.isNull()?'unknown':error.readUtf8String()));}
const bridge=Process.enumerateModules().find(m=>m.path===layout.bridge.path);
if(!bridge)throw Error('Database bridge identity mismatch');
const wrap=(name,result,args)=>new NativeFunction(bridge.getExportByName(name),result,args);
const gateLock=wrap('wemac_db_gate_lock','int',[]),gateUnlock=wrap('wemac_db_gate_unlock','void',[]);
const gateActive=wrap('wemac_db_gate_active','int',[]),gateStop=wrap('wemac_db_gate_stop','void',[]);
if(!wrap('wemac_db_gate_start','int',[])())throw Error('Previous database operation is still running');
const handles=new Map(),hooks=[];let active=0,closing=false,lastDiscovery=0;
function cstring(p,max){
    if(p.isNull())return null;
    for(let offset=0;offset<max;){
        const cursor=p.add(offset);
        const count=Math.min(256,max-offset,Process.pageSize-(cursor.toUInt32()%Process.pageSize));
        const bytes=new Uint8Array(cursor.readVolatile(count)),end=bytes.indexOf(0);
        if(end>=0)return offset+end===0?'':p.readUtf8String(offset+end);
        offset+=count;
    }
    throw Error('Database text exceeds the read limit');
}
function valid(p){
    try{
        if(p.isNull()||p.add(layout.magicOffset).readU32()!==layout.magic)return false;
        const n=p.add(0x28).readS32(),vfs=p.readPointer(),a=p.add(0x20).readPointer();
        return n>=1&&n<=16&&!vfs.isNull()&&vfs.readS32()>=1&&vfs.readS32()<=3&&
            !a.isNull()&&cstring(a.readPointer(),16)==='main';
    }catch(e){return false;}
}
function discover(force=false){
    if(closing)throw Error('Database channel closed');
    if(!force&&Date.now()-lastDiscovery<5000)return;
    lastDiscovery=Date.now();
    for(const r of Process.enumerateMallocRanges()){
        if(r.size!==layout.allocationSize||!valid(r.base))continue;
        if(!handles.has(r.base.toString()))handles.set(r.base.toString(),{pointer:r.base,path:null});
    }
    for(const [key,entry]of handles)if(!valid(entry.pointer))handles.delete(key);
}
const clientEnter=wrap('wemac_db_gate_enter','void',['pointer']);
const clientLeave=wrap('wemac_db_gate_leave','void',['pointer']);
// Non-null engine mutexes already synchronize themselves. In particular, their
// try-lock paths must not be mixed with the null connection-mutex barrier.
hooks.push(Interceptor.attach(functions.databaseEnter,{onEnter(args){if(args[0].isNull())clientEnter(ptr(0));}}));
hooks.push(Interceptor.attach(functions.databaseLeave,{onEnter(args){this.nullMutex=args[0].isNull();},onLeave(){if(this.nullMutex)clientLeave(ptr(0));}}));
for(const name of ['databasePrepare','databaseLockPrepare'])hooks.push(Interceptor.attach(functions[name],{
    onEnter(args){const p=args[0];if(!closing&&valid(p)&&!handles.has(p.toString()))handles.set(p.toString(),{pointer:p,path:null});}
}));
hooks.push(Interceptor.attach(functions.databaseClose,{onEnter(args){handles.delete(args[0].toString());}}));
function query(entry,sql,limit=1000){
    if(closing)throw Error('Database channel closing');
    if(!gateLock())return {code:5,rows:[],busy:true};
    if(!handles.has(entry.pointer.toString())||!valid(entry.pointer)){gateUnlock();throw Error('Database handle no longer open');}
    let rows=[],bytes=0,issue='',started=Date.now();active++;
    const callback=new NativeCallback((ctx,n,values,names)=>{
        try{
            if(n>100||rows.length>=limit||Date.now()-started>2000)throw Error('Database result limit reached');
            let row={};
            for(let i=0;i<n;i++){
                const name=cstring(names.add(i*8).readPointer(),128);
                const p=values.isNull()?ptr(0):values.add(i*8).readPointer();
                const value=p.isNull()?null:cstring(p,2*1024*1024+1);
                bytes+=(name.length+(value||'').length)*2;
                if(bytes>16*1024*1024)throw Error('Database byte budget reached');
                row[name]=value;
            }
            rows.push(row);return 0;
        }catch(e){issue=String(e);return 1;}
    },'int',['pointer','int','pointer','pointer']);
    try{
        const code=nativeExec(entry.pointer,Memory.allocUtf8String(sql),callback,ptr(0),ptr(0));
        return {code,rows,issue};
    }finally{active--;gateUnlock();}
}
function filename(path){return String(path||'').split('/').pop();}
function allowedDatabase(name){return ['contact.db','session.db','emoticon.db','message_resource.db','hardlink.db'].includes(name)||/^message_[0-9]+\.db$/.test(name);}
function allowedTable(db,table){
    const exact={'contact.db':['contact','name2id','chat_room','chatroom_member','chat_room_info_detail'],
        'session.db':['SessionTable','Name2Id'],
        'emoticon.db':['kNonStoreEmoticonTable','kFavEmoticonOrderTable','kCustomEmoticonOrderTable','kStoreEmoticonPackageTable','kStoreEmoticonFilesTable','kStoreEmoticonCaptionsTable'],
        'message_resource.db':['ChatName2Id','SenderName2Id','MessageResourceInfo','MessageResourceDetail'],
        'hardlink.db':['image_hardlink_info_v4','file_hardlink_info_v4','video_hardlink_info_v4','dir2id']};
    return (exact[db]||[]).includes(table)||(/^message_[0-9]+\.db$/.test(db)&&(/^(?:Name2Id|wcdb_builtin_compression_record)$/.test(table)||/^Msg_[a-f0-9]{32}$/.test(table)));
}
function databases(){
    discover();let result=[],seen=new Set();
    for(const entry of [...handles.values()]){
        if(entry.path===null){
            const response=query(entry,'PRAGMA database_list',20);
            if(response.code!==0)continue;
            entry.path=(response.rows.find(r=>r.name==='main')||{}).file||'';
        }
        const name=filename(entry.path);
        if(!allowedDatabase(name)||seen.has(entry.path))continue;
        seen.add(entry.path);result.push({name,path:entry.path,entry});
    }
    return result;
}
function quote(value){if(value===null)return 'NULL';if(typeof value==='boolean')return value?'1':'0';return "'"+String(value).replace(/'/g,"''")+"'";}
function identifier(name){if(!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name))throw Error('Invalid database identifier');return '"'+name+'"';}
function tableRead(options){
    if(!options||!allowedTable(options.database,options.table))throw Error('Database table is not allowlisted');
    const candidates=databases().filter(d=>d.name===options.database&&(!options.path||d.path===options.path));
    if(candidates.length!==1)throw Error('Database identity is unavailable or ambiguous');
    const entry=candidates[0].entry;
    const schema=query(entry,'PRAGMA table_info('+identifier(options.table)+')',100);
    if(schema.code!==0)return schema;
    if(!schema.rows.length)throw Error('Table does not exist');
    if(options.schema)return schema;
    const names=new Set(schema.rows.map(r=>r.name));names.add('rowid');
    const check=name=>{if(!names.has(name))throw Error('Unknown database column');return identifier(name);};
    if(!Array.isArray(options.columns)||!options.columns.length||options.columns.length>50)throw Error('Explicit columns required');
    const columns=options.columns.map(c=>typeof c==='string'?check(c):c.encoding==='hex'?'hex('+check(c.name)+') AS '+check(c.name):(()=>{throw Error('Unknown column encoding');})());
    const clauses=(options.filters||[]).map(f=>{
        const col=check(f.column);
        if(f.op==='in'){
            if(!Array.isArray(f.value)||f.value.length<1||f.value.length>1000)throw Error('Invalid filter list');
            return col+' IN ('+f.value.map(quote).join(',')+')';
        }
        if(!['=','!=','>','>=','<','<='].includes(f.op||'='))throw Error('Invalid filter operator');
        return col+' '+(f.op||'=')+' '+quote(f.value);
    });
    const order=(options.order||[]).map(o=>check(o.column)+(o.desc?' DESC':' ASC'));
    const limit=options.limit===undefined?100:options.limit,offset=options.offset||0;
    if(!Number.isInteger(limit)||limit<1||limit>2000||!Number.isInteger(offset)||offset<0||offset>100000)throw Error('Invalid read bounds');
    const sql='SELECT '+columns.join(',')+' FROM '+identifier(options.table)+(clauses.length?' WHERE '+clauses.join(' AND '):'')+
        (order.length?' ORDER BY '+order.join(','):'')+' LIMIT '+limit+' OFFSET '+offset;
    return query(entry,sql,limit);
}
const materials=new Map();let nextMaterial=0;
function emojiMaterial(digest){
    if(!/^[a-f0-9]{32}$/.test(digest))throw Error('Invalid emoji identity');
    const response=tableRead({database:'emoticon.db',table:'kNonStoreEmoticonTable',columns:['aes_key'],filters:[{column:'md5',value:digest}],limit:1});
    if(response.code!==0||response.rows.length!==1)throw Error('Native emoji key unavailable');
    const value=response.rows[0].aes_key||'';
    if(!/^(?:[a-f0-9]{32}|[a-f0-9]{64})$/i.test(value))throw Error('Native emoji key format unavailable');
    const data=Memory.alloc(value.length/2);data.writeByteArray(value.match(/../g).map(v=>parseInt(v,16)));
    const id=String(++nextMaterial);materials.set(id,{data,size:value.length/2});
    return {id,pointer:data.toString(),size:value.length/2};
}
function releaseMaterial(id){const entry=materials.get(id);if(entry){entry.data.writeByteArray(new Array(entry.size).fill(0));materials.delete(id);}return true;}
rpc.exports={emojiMaterial,releaseMaterial,catalog(){return databases().map(d=>({name:d.name,path:d.path}));},read:tableRead,
    async dispose(){if(active)throw Error('Database read in progress');closing=true;for(const id of [...materials.keys()])releaseMaterial(id);gateStop();const until=Date.now()+5000;while(gateActive()&&Date.now()<until)await new Promise(resolve=>setTimeout(resolve,10));if(gateActive())throw Error('Database engine is still finishing a call');for(const hook of hooks)hook.detach();hooks.length=0;handles.clear();return true;}};
