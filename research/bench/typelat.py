import os, pty, sys, select, time, struct, fcntl, termios, statistics
pid, fd = pty.fork()
if pid == 0:
    os.environ["TERM"]="xterm-256color"; os.environ["COLORTERM"]="truecolor"; os.execvp(sys.argv[1], sys.argv[1:])
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 45, 160, 0, 0))
def drain(quiet):
    first=None; last=None
    while True:
        r,_,_=select.select([fd],[],[],quiet)
        if not r: return first,last
        os.read(fd,1<<20); now=time.perf_counter()
        first=first or now; last=now
drain(0.6)
lat=[]; settle=[]
for i in range(60):
    t=time.perf_counter(); os.write(fd, b"a" if i%5 else b"\x7f")
    f,l=drain(0.4)
    if f: lat.append((f-t)*1000); settle.append((l-t)*1000)
os.write(fd,b"\x11"); time.sleep(0.3)
try: os.kill(pid,9)
except: pass
q=lambda xs,p: sorted(xs)[int(len(xs)*p)-1]
print(f"{sys.argv[-1]:12s} {os.environ['F'].split('/')[-1]:14s} key->first byte median {statistics.median(lat):5.1f} ms p95 {q(lat,.95):5.1f} | key->frame complete median {statistics.median(settle):5.1f} ms p95 {q(settle,.95):5.1f}  (n={len(lat)})")
