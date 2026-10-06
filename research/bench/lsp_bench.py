import json, subprocess, sys, time, os, psutil, threading, queue
cmd = sys.argv[1:]
t0=time.perf_counter()
p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
q=queue.Queue()
def reader():
    f=p.stdout
    while True:
        h={}
        while True:
            line=f.readline()
            if not line: return
            line=line.strip()
            if not line: break
            k,v=line.decode().split(":",1); h[k.lower()]=v.strip()
        q.put(json.loads(f.read(int(h["content-length"]))))
threading.Thread(target=reader,daemon=True).start()
nid=[0]
def send(method, params, notify=False):
    msg={"jsonrpc":"2.0","method":method,"params":params}
    if not notify: nid[0]+=1; msg["id"]=nid[0]
    b=json.dumps(msg).encode(); p.stdin.write(b"Content-Length: %d\r\n\r\n"%len(b)+b); p.stdin.flush()
    return msg.get("id")
def wait(i):
    while True:
        m=q.get(timeout=60)
        if m.get("id")==i and "method" not in m: return m
        if "method" in m and "id" in m:  # server request -> reply null
            b=json.dumps({"jsonrpc":"2.0","id":m["id"],"result":None}).encode(); p.stdin.write(b"Content-Length: %d\r\n\r\n"%len(b)+b); p.stdin.flush()
root="/tmp/lspws"; os.makedirs(root,exist_ok=True)
uri="file://"+root+"/x.py"
wait(send("initialize",{"processId":os.getpid(),"rootUri":"file://"+root,"capabilities":{"textDocument":{"completion":{"completionItem":{"snippetSupport":False}}}}}))
send("initialized",{},True)
tinit=(time.perf_counter()-t0)*1000
v=[1]
def complete(src):
    v[0]+=1
    if v[0]==2: send("textDocument/didOpen",{"textDocument":{"uri":uri,"languageId":"python","version":1,"text":src}},True)
    else: send("textDocument/didChange",{"textDocument":{"uri":uri,"version":v[0]},"contentChanges":[{"text":src}]},True)
    lines=src.split("\n")
    t=time.perf_counter(); r=wait(send("textDocument/completion",{"textDocument":{"uri":uri},"position":{"line":len(lines)-1,"character":len(lines[-1])}}))
    res=r.get("result") or []; n=len(res["items"] if isinstance(res,dict) else res)
    return (time.perf_counter()-t)*1000, n
print(f"{os.path.basename(cmd[0])}: init {tinit:.0f} ms")
for name,src in [("os.path.","import os\nos.path."),("json.","import json\njson."),("local obj","class Foo:\n    def bar(self): pass\nf = Foo()\nf."),("textual App.","from textual.app import App\nApp.")]:
    a=complete(src); b=complete(src+"\n"[:0]); c=complete(src)
    print(f"  {name:14s} first {a[0]:6.0f} ms  repeat {min(b[0],c[0]):5.0f} ms  n={a[1]}")
proc=psutil.Process(p.pid); rss=sum(x.memory_info().rss for x in [proc]+proc.children(recursive=True))/2**20
print(f"  server RSS (incl children) {rss:.0f} MB")
p.kill()
