/* Native read/write barrier for SQLite connections using SQLITE_OPEN_NOMUTEX.
 * Normal client operations retain their existing parallelism. Only our bounded
 * read RPC takes the exclusive barrier. Native callbacks stay mapped forever.
 */
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <time.h>
#include <unistd.h>
static pthread_rwlock_t barrier=PTHREAD_RWLOCK_INITIALIZER;
static atomic_int closing=0,active=0;
static _Thread_local unsigned client_depth=0,writer_depth=0;
static _Thread_local int client_held=0;
static double now(void){struct timespec value;clock_gettime(CLOCK_MONOTONIC,&value);return value.tv_sec+value.tv_nsec/1e9;}
__attribute__((visibility("default"))) void wemac_db_gate_enter(void *ignored){
    (void)ignored;
    if(client_depth++ || writer_depth || atomic_load(&closing))return;
    while(pthread_rwlock_tryrdlock(&barrier)){
        if(atomic_load(&closing))return;
        usleep(500);
    }
    client_held=1;atomic_fetch_add(&active,1);
}
__attribute__((visibility("default"))) void wemac_db_gate_leave(void *ignored){
    (void)ignored;
    if(!client_depth)return;
    if(--client_depth==0&&client_held){client_held=0;atomic_fetch_sub(&active,1);pthread_rwlock_unlock(&barrier);}
}
__attribute__((visibility("default"))) int wemac_db_gate_lock(void){
    if(writer_depth){writer_depth++;return 1;}
    double deadline=now()+.25;
    while(!atomic_load(&closing)){
        if(pthread_rwlock_trywrlock(&barrier)==0){writer_depth=1;atomic_fetch_add(&active,1);return 1;}
        if(now()>=deadline)return 0;
        usleep(500);
    }
    return 0;
}
__attribute__((visibility("default"))) void wemac_db_gate_unlock(void){
    if(writer_depth&&--writer_depth==0){atomic_fetch_sub(&active,1);pthread_rwlock_unlock(&barrier);}
}
__attribute__((visibility("default"))) int wemac_db_gate_active(void){return atomic_load(&active);}
__attribute__((visibility("default"))) void wemac_db_gate_stop(void){atomic_store(&closing,1);}
__attribute__((visibility("default"))) int wemac_db_gate_start(void){
    if(atomic_load(&active))return 0;
    atomic_store(&closing,0);return 1;
}
