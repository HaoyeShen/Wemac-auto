'use strict';
// The account-specific resource key is obtained by WeChat's own getter and is
// passed directly to its CommonCrypto dependency. It is never returned by RPC.
const core=Process.enumerateModules().find(m=>m.path===CONFIG.corePath);
if(!core)throw Error('Native resource module mismatch');
function pinned(name){const entry=CONFIG.functions[name];if(!entry)throw Error('Resource ABI missing');const p=core.base.add(entry.offset);
    const actual=Array.from(new Uint8Array(p.readVolatile(entry.head.length/2))).map(v=>v.toString(16).padStart(2,'0')).join('');
    if(actual!==entry.head)throw Error('Resource function instructions changed');return p;}
const keyGetter=new NativeFunction(pinned('resourceKeyGetter'),['uint64','uint64','uint64'],[]);
const imageDecoder=CONFIG.functions.decodeImageFile ? new NativeFunction(pinned('decodeImageFile'),'int',['pointer','pointer']) : null;
const sizedDelete=new NativeFunction(pinned('sizedDelete'),'void',['pointer','uint64']);
const api=(name,ret,args)=>new NativeFunction(Module.getGlobalExportByName(name),ret,args);
const fopen=api('fopen','pointer',['pointer','pointer']),fseek=api('fseek','int',['pointer','int64','int']);
const ftell=api('ftell','int64',['pointer']),fread=api('fread','uint64',['pointer','uint64','uint64','pointer']);
const fclose=api('fclose','int',['pointer']);
const crypt=api('CCCrypt','int',['uint32','uint32','uint32','pointer','uint64','pointer','pointer','uint64','pointer','uint64','pointer']);
let closed=false;
function file(path){
    if(typeof path!=='string'||!path.startsWith(CONFIG.accountRoot+'/')||path.includes('/../')||path.includes('\0'))throw Error('Resource path outside selected account');
    const relative=path.slice(CONFIG.accountRoot.length+1);
    if(!/^business\/emoticon\/(?:PersistStore|ThumbStore|Persist|Thumb)\/[a-f0-9]{2}\/[a-f0-9]{32}$/.test(relative)&&
       !/^cache\/[0-9]{4}-[0-9]{2}\/Emoticon\/[a-f0-9]{2}\/[a-f0-9]{32}$/.test(relative))throw Error('Resource path is not allowlisted');
    const stream=fopen(Memory.allocUtf8String(path),Memory.allocUtf8String('rb'));
    if(stream.isNull())throw Error('Native cached resource not found');
    try{
        if(fseek(stream,0,2)!==0)throw Error('Native resource seek failed');
        const size=ftell(stream).toNumber();
        if(size<16||size>64*1024*1024||size%16)throw Error('Native resource container size invalid');
        if(fseek(stream,0,0)!==0)throw Error('Native resource seek failed');
        const data=Memory.alloc(size);
        if(fread(data,1,size,stream).toNumber()!==size)throw Error('Native resource read incomplete');
        return {data,size};
    }finally{fclose(stream);}
}
rpc.exports={decodeImage(path){
    if(closed||!imageDecoder)throw Error('Native cached-file decoder unavailable');
    if(typeof path!=='string'||!path.startsWith(CONFIG.accountRoot+'/')||path.includes('/../')||path.includes('\0'))throw Error('Image outside selected account');
    const relative=path.slice(CONFIG.accountRoot.length+1);
    if(!/^msg\/attach\/[a-f0-9]{32}\/[0-9]{4}-[0-9]{2}\/(?:Img|File|Video)\/[^/]+$/.test(relative)&&
       !/^cache\/[0-9]{4}-[0-9]{2}\/Message\/[a-f0-9]{32}\/(?:Thumb|Bubble)\/[^/]+$/.test(relative))throw Error('Cached attachment path is not allowlisted');
    const bytes=Memory.allocUtf8String(path),size=unescape(encodeURIComponent(path)).length,input=Memory.alloc(24),output=Memory.alloc(24);
    input.writePointer(bytes);input.add(8).writeU64(size);input.add(16).writeU64(uint64('0x8000000000000000').or(uint64(size+1)));
    output.writeByteArray(new Array(24).fill(0));
    try {
        const code=imageDecoder(input,output),flag=output.add(23).readU8(),long=!!(flag&128),length=long?output.add(8).readU64().toNumber():flag;
        if(code<0||length<1||length>32*1024*1024)throw Error('Native cached-file decode failed: '+code);
        return {bytes:Array.from(new Uint8Array((long?output.readPointer():output).readVolatile(length))),native:true};
    }finally{if(output.add(23).readU8()&128)sizedDelete(output.readPointer(),output.add(16).readU64().and(uint64('0x7fffffffffffffff')));}
},decode(path,offset=0,length=0,material=null,variant=0){
    if(closed)throw Error('Native resource reader closed');
    if(!Number.isSafeInteger(offset)||offset<0||!Number.isSafeInteger(length)||length<0||length>8*1024*1024)throw Error('Native resource bounds invalid');
    const input=file(path),result=keyGetter(),string=Memory.alloc(24);
    for(let i=0;i<3;i++)string.add(i*8).writeU64(result[i]);
    const flag=string.add(23).readU8(),long=(flag&128)!==0;
    const count=long?string.add(8).readU64().toNumber():flag,key=long?string.readPointer():string;
    const actualKey=material?ptr(material.pointer):key,actualSize=material?material.size:count;
    try{
        if(![16,32].includes(actualSize))throw Error('Native resource key is not ready');
        if(![0,1,2].includes(variant))throw Error('Invalid cipher variant');
        const output=Memory.alloc(input.size),moved=Memory.alloc(8);moved.writeU64(0);
        const code=crypt(1,0,variant===2?2:0,actualKey,actualSize,variant===1?ptr(0):actualKey,input.data,input.size,output,input.size,moved);
        if(code!==0)throw Error('Native resource decode failed: '+code);
        const size=moved.readU64().toNumber(),wanted=length||size;
        if(wanted>8*1024*1024||offset+wanted>size)throw Error('Resource slice out of bounds');
        return {bytes:Array.from(new Uint8Array(output.add(offset).readVolatile(wanted))),native:true};
    }finally{
        if(!long)string.writeByteArray(new Array(24).fill(0));
        else sizedDelete(key,string.add(16).readU64().and(uint64('0x7fffffffffffffff')));
    }
},dispose(){closed=true;return true;}};
