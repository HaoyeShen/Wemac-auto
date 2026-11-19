// Version-pinned 4.2.0 arm64 SNS CDN bridge. Async completion stays native.
#include <cstdint>
#include <cstring>
#include <memory>
#include <mutex>
#include <map>
#include <string>
#include <array>
#include <vector>
#include <stdexcept>

static_assert(sizeof(std::string)==24 && sizeof(std::shared_ptr<void>)==16);
static constexpr unsigned strings[]={0x10,0x28,0x48,0x68,0x80,0xa8,0xc0,0xe8,0x100,0x118,0x130,0x148,
    0x1a0,0x1c0,0x1e8,0x200,0x218,0x230,0x248,0x268,0x280,0x2a0,0x2b8,0x2d8,0x2f0,0x308};
using Shared=std::shared_ptr<void>;
struct Request {
    alignas(8) std::array<unsigned char,0x320> bytes{};
    Request() {
        new(bytes.data()) Shared();
        for(auto off:strings)new(bytes.data()+off) std::string();
        put32(0x40,3);put32(0x44,101);put32(0x60,4);
        bytes[0x98]=1;put32(0x9c,20201);put64(0xe0,~uint64_t(0));
        put32(0x198,1);put64(0x1d8,1);bytes[0x1e1]=1;put32(0x260,256);put32(0x2d0,80);
    }
    void put32(unsigned off,uint32_t v){std::memcpy(bytes.data()+off,&v,4);}
    void put64(unsigned off,uint64_t v){std::memcpy(bytes.data()+off,&v,8);}
    Shared& callback(){return *reinterpret_cast<Shared*>(bytes.data());}
    std::string& string(unsigned off){return *reinterpret_cast<std::string*>(bytes.data()+off);}
    ~Request(){for(auto off:strings)string(off).~basic_string();callback().~shared_ptr();}
    Request(const Request&)=delete;
};
struct Job {
    Request request;int result=0;bool submitted=false,ready=false;
    int error=-99997,secondary_error=0,data_type=0,file_type=0,scene=0;
    uint64_t uploaded_bytes=0;
    std::string key,md5,url,thumb;
};
static std::mutex mutex;
static std::map<uint64_t,std::unique_ptr<Job>> jobs;
static uint64_t next=1;
static std::array<void*,29> result_vtable{};
static void* source_vtable=nullptr;
static std::string bounded_string(const unsigned char* p,unsigned off,size_t limit) {
    const auto& s=*reinterpret_cast<const std::string*>(p+off);
    if(s.size()>limit)throw std::runtime_error("Invalid SNS result string");return s;
}
static int complete(void* self,const std::string& key,const void* result) noexcept {
    std::lock_guard<std::mutex> guard(mutex);
    for(auto& entry:jobs) {
        auto& job=*entry.second;
        if(job.request.callback().get()!=self)continue;
        if(job.ready)return 0;
        try {
            if(!result||key!=job.request.string(0x48))throw std::runtime_error("SNS result key differs");
            const auto* p=static_cast<const unsigned char*>(result);
            std::memcpy(&job.error,p,4);std::memcpy(&job.secondary_error,p+4,4);
            std::memcpy(&job.data_type,p+8,4);std::memcpy(&job.file_type,p+0x14,4);std::memcpy(&job.scene,p+0x18,4);
            if(!job.error&&!job.secondary_error) {
                job.key=bounded_string(p,0x28,128);
                if(job.key!=key)throw std::runtime_error("SNS result identity differs");
                job.md5=bounded_string(p,0x98,64);
                std::memcpy(&job.uploaded_bytes,p+0x110,8);
                job.url=bounded_string(p,0x158,8192);job.thumb=bounded_string(p,0x170,8192);
            }
        }catch(...){job.error=-99997;job.url.clear();job.thumb.clear();}
        job.ready=true;return 0;
    }
    return 0;
}
static std::string quote(const std::string& value) {
    std::string out="\"";
    for(unsigned char v:value) {
        if(v=='"'||v=='\\'){out+='\\';out+=v;}
        else if(v<32)out+='?';else out+=v;
    }
    return out+'"';
}
extern "C" {
uint64_t wemac_sns_create(void* getter,void* factory,const char* key,const char* path) noexcept {
    try {
        if(!getter||!factory||!key||!path||std::strlen(key)>120||std::strlen(path)>2000)return 0;
        auto job=std::make_unique<Job>();
        auto context=reinterpret_cast<void*(*)()>(getter)();
        if(!context)return 0;
        job->request.callback()=reinterpret_cast<Shared(*)(void*,void* const*)>(factory)(nullptr,&context);
        if(!job->request.callback())return 0;
        job->request.string(0x48)=key;job->request.string(0xe8)=path;
        std::lock_guard<std::mutex> guard(mutex);
        if(jobs.size()>=32)return 0;
        uint64_t id=next++;jobs[id]=std::move(job);return id;
    }catch(...){return 0;}
}
void* wemac_sns_callback(uint64_t id) noexcept {
    std::lock_guard<std::mutex> guard(mutex);auto found=jobs.find(id);
    return found==jobs.end()?nullptr:found->second->request.callback().get();
}
void* wemac_sns_request(uint64_t id) noexcept {
    std::lock_guard<std::mutex> guard(mutex);auto found=jobs.find(id);
    return found==jobs.end()?nullptr:found->second->request.bytes.data();
}
int wemac_sns_submit(uint64_t id,void* send) noexcept {
    Job* job;
    {std::lock_guard<std::mutex> guard(mutex);auto found=jobs.find(id);
     if(found==jobs.end()||found->second->submitted||!send)return -99999;
     job=found->second.get();job->submitted=true;}
    try {job->result=reinterpret_cast<int(*)(void*)>(send)(job->request.bytes.data());return job->result;}
    catch(...){return -99998;}
}
unsigned wemac_sns_jobs() noexcept {std::lock_guard<std::mutex> guard(mutex);return jobs.size();}
unsigned wemac_sns_sweep() noexcept {
    std::vector<std::unique_ptr<Job>> finished;
    {std::lock_guard<std::mutex> guard(mutex);
     for(auto it=jobs.begin();it!=jobs.end();){
        if(it->second->ready||!it->second->submitted){finished.push_back(std::move(it->second));it=jobs.erase(it);}
        else ++it;
     }}
    return static_cast<unsigned>(finished.size());
}
int wemac_sns_bind_result(uint64_t id,void* expected_vtable) noexcept {
    std::lock_guard<std::mutex> guard(mutex);auto found=jobs.find(id);
    if(found==jobs.end()||found->second->submitted||!expected_vtable)return 0;
    auto object=found->second->request.callback().get();auto actual=*static_cast<void***>(object);
    if(actual!=expected_vtable)return 0;
    if(!source_vtable){
        // Preserve both RTTI words and every unrelated native virtual method.
        std::memcpy(result_vtable.data(),actual-2,sizeof(result_vtable));
        result_vtable[2+0x30/8]=reinterpret_cast<void*>(complete);source_vtable=actual;
    }
    if(source_vtable!=actual)return 0;
    *static_cast<void***>(object)=result_vtable.data()+2;return 1;
}
size_t wemac_sns_result(uint64_t id,char* output,size_t capacity) noexcept {
    try {
        std::lock_guard<std::mutex> guard(mutex);auto found=jobs.find(id);
        if(found==jobs.end())return 0;auto& j=*found->second;
        std::string result="{\"ready\":"+std::string(j.ready?"true":"false")+
          ",\"return_code\":"+std::to_string(j.error)+",\"secondary_error\":"+std::to_string(j.secondary_error)+
          ",\"data_type\":"+std::to_string(j.data_type)+",\"file_type\":"+std::to_string(j.file_type)+
          ",\"scene\":"+std::to_string(j.scene)+",\"uploaded_bytes\":"+std::to_string(j.uploaded_bytes)+
          ",\"client_id\":"+quote(j.key)+",\"md5\":"+quote(j.md5)+",\"url\":"+quote(j.url)+",\"thumb\":"+quote(j.thumb)+"}";
        if(!output||capacity<=result.size())return result.size()+1;
        std::memcpy(output,result.c_str(),result.size()+1);return result.size()+1;
    }catch(...){return 0;}
}
int wemac_sns_release(uint64_t id) noexcept {
    std::unique_ptr<Job> release;
    {std::lock_guard<std::mutex> guard(mutex);auto found=jobs.find(id);
     if(found==jobs.end()||(found->second->submitted&&!found->second->ready&&found->second->result==0))return 0;
     release=std::move(found->second);jobs.erase(found);}
    return 1;
}
int wemac_sns_copycheck(uint64_t id,void* copier) noexcept {
    std::lock_guard<std::mutex> guard(mutex);auto found=jobs.find(id);
    if(found==jobs.end()||!copier)return 0;
    alignas(8) unsigned char copy[0x320]{};
    try {
        auto& original=found->second->request;
        reinterpret_cast<void(*)(void*,const void*)>(copier)(copy,original.bytes.data());
        bool same=reinterpret_cast<Shared*>(copy)->get()==original.callback().get();
        for(auto off:strings){auto s=reinterpret_cast<std::string*>(copy+off);same &= *s==original.string(off);s->~basic_string();}
        reinterpret_cast<Shared*>(copy)->~shared_ptr();return same?1:0;
    }catch(...){return 0;}
}
// Pending requests remain owned after a host timeout. No callbacks enter Python
// or JS. The process-lifetime virtual table and code are mapped with NODELETE.
}
