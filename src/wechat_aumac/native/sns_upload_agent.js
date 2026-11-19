'use strict';
// All asynchronous callbacks live in the NODELETE native bridge, never JS.
const core=Process.enumerateModules().find(m=>m.path===CONFIG.corePath);
if(!core||Process.arch!=='arm64')throw Error('Unexpected SNS upload core');
const config=CONFIG.nativeSnsUpload, fn={};
for(const name of ['snsContextGetter','snsCallbackFactory','snsCdnSend','snsRequestCopy']){
 const e=CONFIG.functions[name],p=core.base.add(e.offset);
 const actual=Array.from(new Uint8Array(p.readByteArray(e.head.length/2))).map(x=>x.toString(16).padStart(2,'0')).join('');
 if(actual!==e.head)throw Error('SNS instruction mismatch: '+name);fn[name]=p;
}
const open=new NativeFunction(Module.getGlobalExportByName('dlopen'),'pointer',['pointer','int']);
if(open(Memory.allocUtf8String(config.bridge.path),0x2|0x80).isNull())throw Error('SNS native helper could not load');
const library=Process.enumerateModules().find(m=>m.path===config.bridge.path);
const api=(name,type,args)=>new NativeFunction(library.getExportByName('wemac_sns_'+name),type,args);
const create=api('create','uint64',['pointer','pointer','pointer','pointer']);
const callback=api('callback','pointer',['uint64']),copycheck=api('copycheck','int',['uint64','pointer']);
const bind=api('bind_result','int',['uint64','pointer']),submit=api('submit','int',['uint64','pointer']);
const result=api('result','uint64',['uint64','pointer','uint64']),release=api('release','int',['uint64']);
const sweep=api('sweep','uint',[]);
rpc.exports={
 prepare(key,path){
  sweep();
  const id=create(fn.snsContextGetter,fn.snsCallbackFactory,Memory.allocUtf8String(key),Memory.allocUtf8String(path));
  if(id.equals(uint64(0)))throw Error('Could not construct native SNS request');
  try{
   const p=callback(id),expected=core.base.add(config.callbackVtableOffset);
   if(p.isNull()||!p.readPointer().equals(expected)||copycheck(id,fn.snsRequestCopy)!==1)throw Error('Native SNS object ABI differs');
   if(bind(id,expected)!==1)throw Error('Native SNS completion binding failed');
   return {id:id.toString(),native_copy_validated:true};
  }catch(e){release(id);throw e;}
 },
 upload(id){return submit(uint64(id),fn.snsCdnSend);},
 result(id){const output=Memory.alloc(65536);const size=result(uint64(id),output,uint64(65536)).toNumber();
  if(size<2||size>65536)throw Error('Invalid SNS native completion size');return JSON.parse(output.readUtf8String());},
 release(id){return release(uint64(id))===1;},
 dispose(){return true;}
};
