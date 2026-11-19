// Native callback lifetime/teardown test: no WeChat process is involved.
#include <cassert>
#include <thread>
#include <chrono>
#include <memory>
#include <string>
#include <array>
#include <cstring>
#include "../src/wechat_aumac/native/cdn_download.cpp"
static std::array<void*,29> fake_vtable{};
struct Callback {void** table=fake_vtable.data()+2;};
static void* context(){return reinterpret_cast<void*>(0x1000);}
static Shared factory(void*,void* const*){return std::make_shared<Callback>();}
struct Result {alignas(8) std::array<unsigned char,0x50> bytes{};Result(const std::string& k){new(bytes.data()+0x38)std::string(k);}~Result(){reinterpret_cast<std::string*>(bytes.data()+0x38)->~basic_string();}};
static Shared pending;
static std::string pending_key;
static int submit_stub(void* p){auto* bytes=static_cast<unsigned char*>(p);pending=*reinterpret_cast<Shared*>(bytes);pending_key=*reinterpret_cast<std::string*>(bytes+0x40);return 0;}
int main(){
 for(int i=0;i<100;i++){
  auto id=wemac_download_create(reinterpret_cast<void*>(context),reinterpret_cast<void*>(factory),fake_vtable.data()+2,"fixture-key","fixture-id","0123456789abcdef0123456789abcdef","/fixture/output",2);
  assert(id);assert(wemac_download_submit(id,reinterpret_cast<void*>(submit_stub))==0);
  assert(!wemac_download_release(id)); // A host timeout/unload cannot free it.
  int error=0,secondary=0;assert(wemac_download_status(id,&error,&secondary)==0);
  auto saved=pending;auto key=pending_key;std::thread native([saved,key]{
   Result result(key);auto* object=static_cast<Callback*>(saved.get());
   auto complete=reinterpret_cast<int(*)(void*,const std::string&,const void*)>(object->table[0x40/8]);complete(object,key,result.bytes.data());
  });native.join();
  assert(wemac_download_status(id,&error,&secondary)==1&&error==0&&secondary==0);
  assert(wemac_download_release(id));pending.reset();
 }
 assert(wemac_download_sweep()==0);
}
