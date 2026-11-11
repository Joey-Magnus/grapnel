"""Bounded native DLSS5 settings protocol, pending edits and worker-only I/O."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
RUN_ALL_ARGS=["--cxx","{cxx}"]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx",default="g++")
    args=parser.parse_args()
    fixture=r'''
#include "dlss5_controls.h"
#include <cstdio>
#include <cstdlib>
using namespace mkwvk::dlss5_controls;
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"%d: %s\n",__LINE__,#x);std::abort();}}while(0)
std::string state_text(uint64_t ack,const std::array<int,Count>& values,int error=0){
 auto text=request(1,values);text.erase(text.find("sequence="),11);
 return text+"ack="+std::to_string(ack)+"\navailable=1\nhelper_state=4\nmodel_up=1\nerror="+std::to_string(error)+"\n";
}
std::string contents(const std::filesystem::path& path){std::ifstream f(path);return {std::istreambuf_iterator<char>(f),{}};}
template<class F>void wait_for(F action){
 const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(4);
 while(!action()){CHECK(std::chrono::steady_clock::now()<until);std::this_thread::sleep_for(std::chrono::milliseconds(10));}
}
int main(int argc,char**argv){
 CHECK(argc==2);std::string encoded=argv[1],directory;
 for(size_t at=0;at<encoded.size();at+=2)directory+=char(std::stoi(encoded.substr(at,2),nullptr,16));
 std::filesystem::path dir(reinterpret_cast<const char8_t*>(directory.c_str()));
 std::array<int,Count> values{};for(int i=0;i<Count;++i)values[i]=specs[i].lo;
 values[Detail]=100;values[WorkingScale]=50;
 auto text=state_text(7,values);auto parsed=parse(text);
 CHECK(parsed.valid && parsed.ack==7 && parsed.values==values);
 CHECK(!parse(text+"enabled=1\n").valid);CHECK(!parse(text+"unexpected=1\n").valid);
 CHECK(!parse(text.substr(0,text.find("ack="))).valid);
 CHECK(!parse(std::string(4097,'x')).valid);
 auto wrong=text;wrong.replace(wrong.find("workingscale=50"),15,"workingscale=24");CHECK(!parse(wrong).valid);
 CHECK(request(0,values).empty());auto invalid=values;invalid[WorkingScale]=101;CHECK(request(8,invalid).empty());
 CHECK(replace(dir/"state",text));
 Client absent;CHECK(!absent.configured() && !absent.tick(true));
 Client relative("relative/path");CHECK(!relative.configured());
 Client client(directory.c_str());CHECK(client.configured());CHECK(!client.set(Enabled,1));
 wait_for([&]{client.tick(true);return client.available();});
 CHECK(client.values==values && !client.pending());
 CHECK(client.set(Enabled,1));CHECK(client.set(Colour,123));CHECK(client.pending());
 wait_for([&]{return contents(dir/"request").find("sequence=9\n")!=std::string::npos;});
 auto sent=contents(dir/"request");CHECK(sent.find("enabled=1\n")!=std::string::npos && sent.find("colour=123\n")!=std::string::npos);
 CHECK(!client.set(WorkingScale,24));
 // Old acknowledgements cannot clobber newer local edits.
 CHECK(replace(dir/"state",state_text(8,values)));
 wait_for([&]{client.tick(true);return client.state.ack==8;});
 CHECK(client.values[Enabled]==1 && client.values[Colour]==123 && client.pending());
 CHECK(replace(dir/"state",state_text(9,values,1)));
 wait_for([&]{client.tick(true);return client.state.ack==9;});
 CHECK(!client.pending() && client.values==values && std::string(client.status())=="Change failed");
 std::filesystem::last_write_time(dir/"state",std::filesystem::file_time_type::clock::now()-std::chrono::seconds(10));
 CHECK(!read(dir/"state").available);
 wait_for([&]{client.tick(true);return !client.available();});CHECK(!client.set(Enabled,1));
 client.tick(false);std::this_thread::sleep_for(std::chrono::milliseconds(600));
 auto poll=contents(dir/"poll");std::this_thread::sleep_for(std::chrono::milliseconds(600));
 CHECK(contents(dir/"poll")==poll); // no periodic helper polls during gameplay
 std::puts("DLSS5 controls: strict protocol, async requests, pending/failed changes and inactive polling passed");
}
'''
    with tempfile.TemporaryDirectory(prefix="dlss5 native ü ") as temporary:
        path=Path(temporary);cpp=path/"fixture.cpp";exe=path/("fixture.exe" if os.name=="nt" else "fixture")
        cpp.write_text(fixture)
        if Path(args.cxx).name.lower() in ("cl", "cl.exe", "clang-cl", "clang-cl.exe"):
            command=[args.cxx,"/nologo","/std:c++20","/EHsc","/I"+str(ROOT/"gpu/vk"),
                     str(cpp),"/Fo"+str(path/"fixture.obj"),"/Fe"+str(exe)]
        else:
            command=[args.cxx,"-std=c++20","-O1","-pthread","-Wall","-Wextra","-Werror",
                     "-I"+str(ROOT/"gpu/vk"),str(cpp),"-o",str(exe)]
        subprocess.run(command,cwd=path,check=True)
        # ASCII transport avoids the Windows CRT's narrow argv code page, while
        # the production client still receives the original UTF-8 directory.
        subprocess.run([str(exe),str(path).encode("utf-8").hex()],check=True,timeout=10)


if __name__=="__main__":main()
