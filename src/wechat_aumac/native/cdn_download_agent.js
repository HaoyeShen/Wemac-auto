'use strict';
const core=Process.enumerateModules().find(m=>m.path===CONFIG.corePath),config=CONFIG.nativeCdnDownload;
if(!core||Process.arch!=='arm64')throw Error('Native C2C download core differs');
function pinned(name){const e=CONFIG.functions[name],p=core.base.add(e.offset);const actual=Array.from(new Uint8Array(p.readVolatile(e.head.length/2))).map(v=>v.toString(16).padStart(2,'0')).join('');if(actual!==e.head)throw Error('C2C instructions differ');return p;}
const getter=pinned('snsContextGetter'),factory=pinned('snsCallbackFactory'),nativeSubmit=pinned('cdnDownload');
const nativeHttps=CONFIG.functions.cdnHttpsDownload ? pinned('cdnHttpsDownload') : null;
const open=new NativeFunction(Module.getGlobalExportByName('dlopen'),'pointer',['pointer','int']);
if(open(Memory.allocUtf8String(config.bridge.path),0x82).isNull())throw Error('Native downloader not loaded');
const lib=Process.enumerateModules().find(m=>m.path===config.bridge.path);
const api=(name,ret,args)=>new NativeFunction(lib.getExportByName('wemac_download_'+name),ret,args);
const create=api('create','uint64',['pointer','pointer','pointer','pointer','pointer','pointer','pointer','int']);
const submit=api('submit','int',['uint64','pointer']),status=api('status','int',['uint64','pointer','pointer']);
const release=api('release','int',['uint64']),sweep=api('sweep','uint',[]);
rpc.exports={start(key,url,aes,path,type){
 if(!path.startsWith(config.cacheRoot+'/')||path.includes('/../')||path.includes('\0'))throw Error('Download path outside container');
 sweep();const id=create(getter,factory,core.base.add(config.callbackVtableOffset),Memory.allocUtf8String(key),Memory.allocUtf8String(url),Memory.allocUtf8String(aes),Memory.allocUtf8String(path),type);
 if(id.equals(uint64(0)))throw Error('Native download request unavailable');
 if(type===8&&!nativeHttps)throw Error('Native HTTPS reader unavailable');
 return {id:id.toString(),code:submit(id,type===8?nativeHttps:nativeSubmit)};
},status(id){const a=Memory.alloc(4),b=Memory.alloc(4);const ready=status(uint64(id),a,b);return {ready:ready===1,error:a.readS32(),secondary:b.readS32()};},release(id){return release(uint64(id))===1;},dispose(){return true;}};
