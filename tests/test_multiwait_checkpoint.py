"""Production multiwait scanning must not yield its virtual core under mw_lock."""
import os
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[1]
source=(root/'host/nn_os_sync.c').read_text()
def function(name):
    start=source.index(name); brace=source.index('{',start); depth=1; end=brace+1
    while depth:
        depth += (source[end]=='{') - (source[end]=='}'); end+=1
    return source[start:end]
lookup = function('static Obj *obj(uint64_t key, int kind) {')
if 'static Obj *obj_cached(' in source:
    lookup=function('static Obj *obj_cached(uint64_t key, int kind) {')+'\n'+lookup
code=r'''
#include <stdint.h>
#include <stdlib.h>
#include <assert.h>
typedef unsigned DWORD;
enum { K_EVENT=3,K_SEMA,K_QUEUE,K_MULTIWAIT=7,K_TIMER=9 };
enum { H_EVENT,H_TIMER,H_THREAD,H_SEMA,H_QUEUE_NOT_EMPTY,H_QUEUE_NOT_FULL,H_NATIVE };
typedef struct Obj {uint64_t key,event;int kind,sem,sem_max,qlen,qcap,signaled,autoclear,nlinks;int64_t due_ns;struct Obj **links;} Obj;
static Obj objects[8]; static int mw_lock,mw_cv,mw_waiting,checkpoints,sleeps;
static int64_t now=1000000000;
static Obj *obj_lookup(uint64_t key,int kind){for(int i=0;i<8;i++)if(objects[i].key==key && objects[i].kind==kind)return &objects[i];abort();}
static void hos_vcore_checkpoint(void){assert(!mw_lock);++checkpoints;}
static int64_t hos_now_ns(void){return now;}
static void AcquireSRWLockExclusive(int *lock){assert(!*lock);*lock=1;}
static void ReleaseSRWLockExclusive(int *lock){assert(*lock);*lock=0;}
static void InterlockedIncrement(int *v){++*v;}
static void InterlockedDecrement(int *v){--*v;}
static int event_wait(Obj *o,int64_t timeout,int try_only){assert(timeout==0 && try_only);int r=o->signaled;if(r && o->autoclear)o->signaled=0;return r;}
static int hos_cv_sleep(int *cv,int *lock,unsigned ms){(void)cv;assert(*lock);++sleeps;now+=(int64_t)ms*1000000;return 1;}
'''
code+=lookup+'\n'+function('static int holder_ready(Obj *h) {')+'\n'+function('static uint64_t wait_any(uint64_t multiwait, int64_t timeout_ns) {')
code+=r'''
int main(void){
 objects[0]=(Obj){.key=1,.kind=K_MULTIWAIT};objects[1]=(Obj){.key=2,.kind=K_EVENT,.signaled=1,.autoclear=1};
 objects[2]=(Obj){.key=3,.kind=K_TIMER,.due_ns=now+3000000};objects[3]=(Obj){.key=4,.kind=K_SEMA,.sem=1};
 objects[4]=(Obj){.key=5,.kind=K_QUEUE,.qlen=1,.qcap=2};
 Obj holder={.key=99,.event=2,.sem_max=H_EVENT};Obj *links[]={&holder};objects[0].links=links;objects[0].nlinks=1;
 assert(wait_any(1,0)==99 && !objects[1].signaled && checkpoints==1 && !mw_lock && !mw_waiting);
 assert(wait_any(1,0)==0 && checkpoints==2 && !sleeps);
 holder.event=3;holder.sem_max=H_TIMER;
 assert(wait_any(1,10000000)==99 && sleeps==1 && now==1003000000 && checkpoints==3);
 objects[2].due_ns=now+20000000;assert(wait_any(1,1000000)==0 && checkpoints==4);
 holder.event=4;holder.sem_max=H_SEMA;assert(wait_any(1,0)==99 && objects[3].sem==1);
 holder.event=5;holder.sem_max=H_QUEUE_NOT_EMPTY;assert(wait_any(1,0)==99 && objects[4].qlen==1);
 holder.sem_max=H_QUEUE_NOT_FULL;assert(wait_any(1,0)==99);
 objects[4].qlen=2;assert(wait_any(1,0)==0);
 holder.sem_max=H_THREAD;assert(wait_any(1,0)==0);
 holder.sem_max=H_NATIVE;assert(wait_any(1,0)==0);
 assert(!mw_lock && !mw_waiting);
}
'''
with tempfile.TemporaryDirectory() as directory:
    p=Path(directory);(p/'test.c').write_text(code)
    subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror',str(p/'test.c'),'-o',str(p/'test')],check=True)
    for uncached in (False, True):
        env=dict(os.environ);env.pop('HOS_NO_OBJ_CACHE',None)
        if uncached:env['HOS_NO_OBJ_CACHE']='1'
        subprocess.run([str(p/'test')],env=env,check=True)
print('PASS: multiwait checkpoint placement, autoclear, timers, timeout, semaphore and queue readiness with/without cache')
