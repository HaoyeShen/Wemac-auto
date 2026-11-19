// 4.2.0 arm64 native C2C download. All async completion code is NODELETE.
#include <array>
#include <cstdint>
#include <cstring>
#include <memory>
#include <mutex>
#include <map>
#include <string>
#include <vector>
using Shared=std::shared_ptr<void>;
static_assert(sizeof(std::string)==24&&sizeof(Shared)==16);
static constexpr unsigned fields[]={0x10,0x28,0x40,0x58,0x70,0x88,0x2c8};
struct Job {
    alignas(8) std::array<unsigned char,0x600> bytes{};
    bool submitted=false,ready=false;int error=-99997,secondary=0,submit_code=0;std::string key;
    Job(){new(bytes.data()) Shared();for(auto o:fields)new(bytes.data()+o) std::string();}
    std::string& str(unsigned o){return *reinterpret_cast<std::string*>(bytes.data()+o);}
    Shared& cb(){return *reinterpret_cast<Shared*>(bytes.data());}
    ~Job(){for(auto o:fields)str(o).~basic_string();cb().~shared_ptr();}
};
static std::mutex mutex;
static std::map<uint64_t,std::unique_ptr<Job>> jobs;
static uint64_t next=1;
static std::array<void*,29> result_vtable{};static void* source_vtable=nullptr;
static int complete(void* self,const std::string& key,const void* result) noexcept {
    std::lock_guard<std::mutex> guard(mutex);
    for(auto& entry:jobs){auto& j=*entry.second;if(j.cb().get()!=self)continue;
        if(j.ready)return 0;
        if(result&&key==j.key){
            const auto* p=static_cast<const unsigned char*>(result);
            std::memcpy(&j.error,p,4);std::memcpy(&j.secondary,p+4,4);
            const auto& actual=*reinterpret_cast<const std::string*>(p+0x38);
            if(actual.size()>128||actual!=j.key)j.error=-99997;
        }else j.error=-99997;
        j.ready=true;return 0;
    }return 0;
}
extern "C" {
uint64_t wemac_download_create(void* getter,void* factory,void* expected,const char* key,const char* url,const char* aes,const char* path,int type) noexcept {
 try{
    if(!getter||!factory||!expected||!key||!url||!aes||!path||std::strlen(key)>120||std::strlen(url)>8192||std::strlen(aes)>64||std::strlen(path)>2000||(type!=2&&type!=4&&type!=5&&type!=8))return 0;
    auto j=std::make_unique<Job>();auto ctx=reinterpret_cast<void*(*)()>(getter)();if(!ctx)return 0;
    j->cb()=reinterpret_cast<Shared(*)(void*,void* const*)>(factory)(nullptr,&ctx);if(!j->cb())return 0;
    auto actual=*static_cast<void***>(j->cb().get());if(actual!=expected)return 0;
    j->key=key;j->str(0x40)=key;j->str(0x58)=url;j->str(0x70)=aes;j->str(0x88)=path;
    if(type==8){j->str(0x2c8)=url;type=5;}
    std::memcpy(j->bytes.data()+0xa0,&type,4);int app=1;std::memcpy(j->bytes.data()+0xa4,&app,4);
    std::lock_guard<std::mutex> g(mutex);if(jobs.size()>=32)return 0;
    if(!source_vtable){std::memcpy(result_vtable.data(),actual-2,sizeof(result_vtable));result_vtable[2+0x40/8]=reinterpret_cast<void*>(complete);source_vtable=actual;}
    if(source_vtable!=actual)return 0;
    *static_cast<void***>(j->cb().get())=result_vtable.data()+2;
    uint64_t id=next++;jobs[id]=std::move(j);return id;
 }catch(...){return 0;}
}
int wemac_download_submit(uint64_t id,void* submit) noexcept {
 Job* j;{std::lock_guard<std::mutex> g(mutex);auto it=jobs.find(id);if(it==jobs.end()||it->second->submitted||!submit)return -99999;j=it->second.get();j->submitted=true;}
 try{j->submit_code=reinterpret_cast<int(*)(void*)>(submit)(j->bytes.data());return j->submit_code;}catch(...){return -99998;}
}
int wemac_download_status(uint64_t id,int* error,int* secondary) noexcept {
 std::lock_guard<std::mutex> g(mutex);auto it=jobs.find(id);if(it==jobs.end())return -1;
 if(error)*error=it->second->error;if(secondary)*secondary=it->second->secondary;return it->second->ready?1:0;
}
int wemac_download_release(uint64_t id) noexcept {
 std::unique_ptr<Job> release;{std::lock_guard<std::mutex> g(mutex);auto it=jobs.find(id);if(it==jobs.end()||(it->second->submitted&&!it->second->ready&&!it->second->submit_code))return 0;release=std::move(it->second);jobs.erase(it);}return 1;
}
unsigned wemac_download_sweep() noexcept {
 std::vector<std::unique_ptr<Job>> finished;{std::lock_guard<std::mutex> g(mutex);for(auto it=jobs.begin();it!=jobs.end();){if(it->second->ready||!it->second->submitted){finished.push_back(std::move(it->second));it=jobs.erase(it);}else ++it;}}return static_cast<unsigned>(finished.size());
}
}
