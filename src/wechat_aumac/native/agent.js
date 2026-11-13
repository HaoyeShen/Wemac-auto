'use strict';
// Original implementation based on locally observed 4.2.0 call sites.
// Native offsets are accepted only after host file and instruction validation.
const core = Process.enumerateModules().find(m => m.path === CONFIG.corePath);
if (!core || Process.arch !== 'arm64') throw Error('Unexpected target module/architecture');
function address(name) {
    const entry=CONFIG.functions[name];
    const p=core.base.add(entry.offset);
    const actual=Array.from(new Uint8Array(p.readByteArray(entry.head.length/2)))
        .map(x=>x.toString(16).padStart(2,'0')).join('');
    if(actual!==entry.head)throw Error('Instruction mismatch: '+name);
    return p;
}
const fn={};
for(const name of Object.keys(CONFIG.functions))fn[name]=address(name);
const watches=[];
const mode=CONFIG.runtimeMode || 'receive';
const observedOperations=CONFIG.observeOperations || [];
const experimentalOperations=CONFIG.experimentalOperations || [];
const readOperations=CONFIG.readOperations || [];
const momentWriteKinds=CONFIG.momentWriteKinds || [];
let shuttingDown=false;
const state={observedTextRequest:false};
let completionBridge=null;
function bridge(){
    if(completionBridge!==null)return completionBridge;
    if(!CONFIG.completionHelper)throw Error('A native completion bridge is required');
    const path=Memory.allocUtf8String(CONFIG.completionHelper.path);
    // Keep native callback code mapped even after this script is unloaded.
    const open=new NativeFunction(Module.getGlobalExportByName('dlopen'),'pointer',['pointer','int']);
    const handle=open(path,0x2|0x80); // RTLD_NOW | RTLD_NODELETE
    if(handle.isNull())throw Error('Could not load completion bridge');
    const module=Process.enumerateModules().find(m=>m.path===CONFIG.completionHelper.path);
    if(!module)throw Error('Completion bridge module identity mismatch');
    const wrap=(name,result,args)=>new NativeFunction(module.getExportByName(name),result,args);
    const size=wrap('aumac_completion_size','uint64',[])().toNumber();
    const align=wrap('aumac_completion_alignment','uint64',[])().toNumber();
    if(size!==32 || align>16)throw Error('Unsupported libc++ completion ABI');
    completionBridge={size:size,
        construct:wrap('aumac_completion_construct','void',['pointer']),
        destroy:wrap('aumac_completion_destroy','void',['pointer']),
        count:wrap('aumac_completion_count','uint64',[]),
        failures:wrap('aumac_completion_failures','uint64',[])};
    return completionBridge;
}
function manager() {
    const singleton=new NativeFunction(fn.singleton,'pointer',[])();
    if(singleton.isNull())throw Error('No logged-in service');
    const getter=singleton.readPointer().add(0x18).readPointer();
    const service=new NativeFunction(getter,'pointer',['pointer'])(singleton);
    if(service.isNull())throw Error('No network manager');
    const submit=service.readPointer().add(0x28).readPointer();
    if(!submit.equals(fn.expectedManagerSend))throw Error('Network manager implementation mismatch');
    return service;
}
function emit(event){if(shuttingDown)return;event.time=Date.now();send(event);}
function safeView(p,length){
    const bytes=p.readVolatile(length);
    if(bytes===null || bytes.byteLength!==length)throw Error('Memory is no longer readable');
    return new DataView(bytes);
}
function safePointer(p){return ptr(safeView(p,8).getBigUint64(0,true).toString());}
function safeU32(p){return safeView(p,4).getUint32(0,true);}
function boundedBuffer(buffer){
    // Disassembly verified: handle -> descriptor; descriptor[0]=data,
    // descriptor+0x0c=uint32 length. Never call C++ from a hook callback.
    const descriptor=safePointer(buffer);
    const view=safeView(descriptor,16);
    const p=ptr(view.getBigUint64(0,true).toString());
    const length=view.getUint32(12,true);
    if(length>4*1024*1024)throw Error('Invalid buffer length');
    if(length===0)return [];
    const bytes=p.readVolatile(length);
    if(bytes===null || bytes.byteLength!==length)throw Error('Buffer became unreadable');
    return Array.from(new Uint8Array(bytes));
}
function wireFields(bytes) {
    let i=0;
    function integer(){let value=0,multiplier=1;for(let n=0;n<10;n++){if(i>=bytes.length)throw Error('Truncated varint');const b=bytes[i++];value+=(b&127)*multiplier;if(b<128)return value;multiplier*=128;}throw Error('Varint overflow');}
    const fields=[];
    while(i<bytes.length){
        const tag=integer(),field=Math.floor(tag/8),kind=tag&7;
        if(!field)throw Error('Invalid field');
        if(kind===0)fields.push({field:field,kind:kind,value:integer()});
        else if(kind===2){const length=integer();if(length>bytes.length-i)throw Error('Truncated bytes');fields.push({field:field,kind:kind,value:bytes.slice(i,i+length)});i+=length;}
        else if(kind===1 || kind===5){i+=kind===1?8:4;if(i>bytes.length)throw Error('Truncated fixed field');}
        else throw Error('Unknown wire type');
    }
    return fields;
}
if(['receive','full','observe'].includes(mode) && fn.parseSyncResponse)watches.push(Interceptor.attach(fn.parseSyncResponse,{
    onEnter(args){
        try{
            const response=wireFields(boundedBuffer(args[1]));
            let count=0,commands=0;
            for(const list of response.filter(f=>f.field===2 && f.kind===2)){
                for(const command of wireFields(list.value).filter(f=>f.field===2 && f.kind===2)){
                    commands++;
                    const parts=wireFields(command.value);
                    if(!parts.some(f=>f.field===1 && f.kind===0 && f.value===5))continue;
                    for(const buffer of parts.filter(f=>f.field===2 && f.kind===2)){
                        for(const item of wireFields(buffer.value).filter(f=>f.field===2 && f.kind===2)){
                            count++;emit({event:'incoming_message',bytes:item.value});
                        }
                    }
                }
            }
            emit({event:'sync_summary',commands:commands,messages:count});
        }catch(e){emit({event:'probe_error',detail:'sync: '+String(e)});}
    }
}));
if(mode==='full' || mode==='observe')watches.push(Interceptor.attach(fn.serializeText,{
    onEnter(args){this.output=args[1];this.scene=args[0];},
    onLeave(ret){
        try{
            const bytes=boundedBuffer(this.output);
            state.observedTextRequest=true;
            emit({event:'text_request',scene:this.scene.toString(),taskId:safeU32(this.scene.add(8)),bytes:bytes});
        }catch(e){emit({event:'probe_error',detail:String(e)});}
    }
}));
if(mode==='full' || mode==='observe')watches.push(Interceptor.attach(fn.parseTextResponse,{
    onEnter(args){
        try{emit({event:'text_response',scene:args[0].toString(),taskId:safeU32(args[0].add(8)),bytes:boundedBuffer(args[1])});}
        catch(e){emit({event:'probe_error',detail:String(e)});}
    }
}));
// Explicit opt-in observations. Copy completed wire buffers only; never call
// constructors, serializers or any other C++ method from an interceptor.
for(const operation of mode==='observe'?observedOperations:mode==='full'?[...experimentalOperations,...readOperations,...momentWriteKinds]:[]){
    const entry=(CONFIG.observations || {})[operation];
    if(!entry || !fn[entry.serialize] || !fn[entry.response])throw Error('Unknown observer: '+operation);
    watches.push(Interceptor.attach(fn[entry.serialize],{
        onEnter(args){this.output=args[1];this.scene=args[0];},
        onLeave(ret){
            if(ret.toInt32()===0)return;
            try{emit({event:'native_request',operation:operation,commandId:entry.command_id,
                scene:this.scene.toString(),taskId:safeU32(this.scene.add(8)),bytes:boundedBuffer(this.output)});}
            catch(e){emit({event:'probe_error',operation:operation,detail:String(e)});}
        }
    }));
    watches.push(Interceptor.attach(fn[entry.response],{
        onEnter(args){
            try{emit({event:'native_response',operation:operation,commandId:entry.command_id,
                scene:args[0].toString(),taskId:safeU32(args[0].add(8)),bytes:boundedBuffer(args[1])});}
            catch(e){emit({event:'probe_error',operation:operation,detail:String(e)});}
        }
    }));
}
function submitNative(bytes,kind){
    if(mode!=='full' || shuttingDown)throw Error('Native submission is not enabled');
    const text=kind==='text';
    const readOnly=readOperations.includes(kind) && (CONFIG.readSubmits || {})[kind];
    const momentWrite=momentWriteKinds.includes(kind) && (CONFIG.momentSubmits || {})[kind];
    if(!text && !readOnly && !momentWrite && !experimentalOperations.includes(kind))throw Error('Native operation is not enabled');
    if(!Array.isArray(bytes) || !bytes.length || bytes.length>(text?65536:1024*1024))throw Error('Invalid payload length');
    const entry=(CONFIG.requestTypes || {text:{constructor:'requestConstructor',destructor:'requestDestructor',size:48}})[kind];
    const submit=text?fn.submitText:fn[(readOnly?CONFIG.readSubmits:momentWrite?CONFIG.momentSubmits:CONFIG.mediaSubmits || {})[kind]];
    if(!entry || !submit || !fn[entry.constructor] || !fn[entry.destructor])throw Error('Unsupported request type');
    const service=manager(),request=Memory.alloc(entry.size),input=Memory.alloc(bytes.length);
    input.writeByteArray(bytes);
    new NativeFunction(fn[entry.constructor],'void',['pointer'])(request);
    try{
        const parsed=new NativeFunction(fn.parseProtobuf,'bool',['pointer','pointer','int'])(request,input,bytes.length);
        if(!parsed)throw Error('Native request parser rejected payload');
        const user=Memory.alloc(24),options=Memory.alloc(40),cb=bridge(),callback=Memory.alloc(cb.size);
        cb.construct(callback);
        try{
            const taskId=new NativeFunction(submit,'uint32',['pointer','pointer','pointer','pointer','pointer'])(service,request,user,options,callback);
            return {taskId:taskId,submitted:taskId!==0};
        }finally{cb.destroy(callback);}
    }finally{new NativeFunction(fn[entry.destructor],'void',['pointer'])(request);}
}
rpc.exports={
    context(){
        const singleton=new NativeFunction(fn.singleton,'pointer',[])();
        const accountGetter=singleton.readPointer().add(0x28).readPointer();
        return {manager:manager().toString(),validated:true,
            accountGetterOffset:accountGetter.sub(core.base).toString()};
    },
    identity(){
        const singleton=new NativeFunction(fn.singleton,'pointer',[])();
        if(singleton.isNull())throw Error('Account service is unavailable');
        if(!fn.accountGetter || !singleton.readPointer().add(0x28).readPointer().equals(fn.accountGetter))throw Error('Account getter mismatch');
        const str=new NativeFunction(fn.accountGetter,'pointer',['pointer'])(singleton);
        const view=safeView(str,24),flag=view.getUint8(23),long=(flag&128)!==0;
        const length=long?Number(view.getBigUint64(8,true)):flag;
        if(length<1 || length>128)throw Error('Account is not logged in');
        const bytes=new Uint8Array((long?safePointer(str):str).readVolatile(length));
        const name=Array.from(bytes).map(b=>String.fromCharCode(b)).join('');
        if(!/^[A-Za-z0-9_.@-]{1,128}$/.test(name))throw Error('Unexpected account identifier');
        return {user_id:name};
    },
    completionStatus(){const cb=bridge();return {size:cb.size,completed:cb.count().toString(),failures:cb.failures().toString()};},
    submit(bytes){
        return submitNative(bytes,'text');
    },
    submitMedia(bytes,kind){if(!['image','video','voice','sticker'].includes(kind))throw Error('Unsupported media type');return submitNative(bytes,kind);},
    fetchNative(bytes,kind){if(!['moment_timeline','moment_detail'].includes(kind) || !readOperations.includes(kind))throw Error('Unsupported read operation');return submitNative(bytes,kind);},
    writeMoment(bytes,kind){if(!['moment_post','moment_interaction','moment_objectop'].includes(kind) || !momentWriteKinds.includes(kind))throw Error('Moments writing is disabled');return submitNative(bytes,kind);},
    status(){return {module:core.path,base:core.base.toString(),mode:mode,hookCount:watches.length,
        observedOperations:observedOperations,codecTypes:Object.keys(CONFIG.requestTypes || {text:{}}),
        mediaOperations:experimentalOperations,readOperations:readOperations,momentWriteKinds:momentWriteKinds,
        observedTextRequest:state.observedTextRequest};},
    dispose(){
        shuttingDown=true;
        for(const watch of watches)watch.detach();
        watches.length=0;
        Interceptor.flush();
        return {disposed:true};
    },
    roundtrip(bytes,kind){
        if(shuttingDown)throw Error('Native session is closing');
        if(!Array.isArray(bytes) || bytes.length>4*1024*1024)throw Error('Invalid codec payload length');
        kind=kind || 'text';
        const entry=(CONFIG.requestTypes || {text:{constructor:'requestConstructor',destructor:'requestDestructor',size:48}})[kind];
        if(!entry || !fn[entry.constructor] || !fn[entry.destructor])throw Error('Unknown codec type');
        if(!Number.isInteger(entry.size) || entry.size<16 || entry.size>65536)throw Error('Invalid request size');
        const request=Memory.alloc(entry.size);
        const input=Memory.alloc(bytes.length || 1);input.writeByteArray(bytes);
        new NativeFunction(fn[entry.constructor],'void',['pointer'])(request);
        try{
            const ok=new NativeFunction(fn.parseProtobuf,'bool',['pointer','pointer','int'])(request,input,bytes.length);
            if(!ok)return {parsed:false};
            // The serializer returns a 24-byte libc++ string through ARM64 x8.
            const result=new NativeFunction(fn.serializeProtobuf,['uint64','uint64','uint64'],['pointer'])(request);
            const str=Memory.alloc(24);for(let i=0;i<3;i++)str.add(i*8).writeU64(result[i]);
            const long=(str.add(23).readU8()&128)!==0;
            const size=long?str.add(8).readU64().toNumber():str.add(23).readU8();
            if(size>4*1024*1024)throw Error('Invalid serialized string');
            const ptr=long?str.readPointer():str;
            const output=Array.from(new Uint8Array(ptr.readByteArray(size)));
            if(long)new NativeFunction(fn.sizedDelete,'void',['pointer','uint64'])(ptr,str.add(16).readU64().and(uint64('0x7fffffffffffffff')));
            return {parsed:true,bytes:output};
        }finally{new NativeFunction(fn[entry.destructor],'void',['pointer'])(request);}
    }
};
emit({event:'ready',module:core.path});
