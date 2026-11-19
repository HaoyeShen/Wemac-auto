// Host-only lifetime regression for the native async completion bridge.
#include "../src/wechat_aumac/native/sns_upload.cpp"
#include <cassert>
static int alive=0;
struct Callback {
    Callback(){++alive;}virtual ~Callback(){--alive;}
    virtual void a(){} virtual void b(){} virtual void c(){} virtual void d(){}
    virtual int done(const std::string&,const void*){return 0;}
#define SLOT(n) virtual void slot##n(){}
    SLOT(5) SLOT(6) SLOT(7) SLOT(8) SLOT(9) SLOT(10) SLOT(11) SLOT(12) SLOT(13) SLOT(14)
    SLOT(15) SLOT(16) SLOT(17) SLOT(18) SLOT(19) SLOT(20) SLOT(21) SLOT(22) SLOT(23) SLOT(24)
#undef SLOT
};
void* context(){return reinterpret_cast<void*>(1234);}
Shared factory(void*,void*const* p){assert(*p==context());return std::make_shared<Callback>();}
void copier(void* out,const void* input){
    auto src=static_cast<const unsigned char*>(input);auto dst=static_cast<unsigned char*>(out);
    new(dst) Shared(*reinterpret_cast<const Shared*>(src));
    for(auto off:strings)new(dst+off) std::string(*reinterpret_cast<const std::string*>(src+off));
}
int send_request(void* input){
    auto r=static_cast<unsigned char*>(input);
    assert(*reinterpret_cast<uint32_t*>(r+0x40)==3);
    assert(*reinterpret_cast<uint32_t*>(r+0x44)==101);
    assert(*reinterpret_cast<std::string*>(r+0xe8)=="/tmp/公开图片.jpg");return 0;
}
int main(){
    for(int repeat=0;repeat<100;++repeat){
        auto id=wemac_sns_create(reinterpret_cast<void*>(context),reinterpret_cast<void*>(factory),"wemac_sns_test","/tmp/公开图片.jpg");
        assert(id&&alive==1);assert(wemac_sns_copycheck(id,reinterpret_cast<void*>(copier))==1);
        auto object=wemac_sns_callback(id);auto native_vtable=*static_cast<void***>(object);
        assert(wemac_sns_bind_result(id,native_vtable)==1);
        auto request=static_cast<unsigned char*>(wemac_sns_request(id));
        Shared in_flight=*reinterpret_cast<Shared*>(request);
        assert(wemac_sns_submit(id,reinterpret_cast<void*>(send_request))==0);
        assert(wemac_sns_submit(id,reinterpret_cast<void*>(send_request))==-99999);
        assert(wemac_sns_release(id)==0);assert(wemac_sns_sweep()==0); // timeout keeps native callback alive
        alignas(8) unsigned char response[0x188]{};
        for(auto off:{0x28,0x98,0x158,0x170})new(response+off) std::string();
        *reinterpret_cast<std::string*>(response+0x28)="wemac_sns_test";
        *reinterpret_cast<std::string*>(response+0x98)="d41d8cd98f00b204e9800998ecf8427e";
        *reinterpret_cast<std::string*>(response+0x158)="http://mmsns.qpic.cn/mmsns/test/0";
        *reinterpret_cast<std::string*>(response+0x170)="http://mmsns.qpic.cn/mmsns/test/150";
        int kind=3,type=101,scene=20201;uint64_t bytes=10;
        std::memcpy(response+8,&kind,4);std::memcpy(response+0x14,&type,4);std::memcpy(response+0x18,&scene,4);std::memcpy(response+0x110,&bytes,8);
        auto notify=reinterpret_cast<int(*)(void*,const std::string&,const void*)>((*static_cast<void***>(object))[0x30/8]);
        assert(notify(object,"wemac_sns_test",response)==0);
        char json[4096];assert(wemac_sns_result(id,json,sizeof(json))>1);
        assert(std::string(json).find("\"ready\":true")!=std::string::npos);
        assert(wemac_sns_sweep()==1);assert(alive==1);
        assert(notify(object,"wemac_sns_test",response)==0); // native owner can finish after host released job
        in_flight.reset();assert(alive==0);assert(wemac_sns_jobs()==0);
        for(auto off:{0x28,0x98,0x158,0x170})reinterpret_cast<std::string*>(response+off)->~basic_string();
    }
}
