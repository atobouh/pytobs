# run a command under a pty sized 120x40, return wall time and stderr MAXRSS
import os, pty, sys, time, statistics, struct, fcntl, termios, select, subprocess
def once(cmd):
    t0 = time.perf_counter()
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"; os.environ["COLORTERM"]="truecolor"
        os.execvp(cmd[0], cmd)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    buf = b""
    while True:
        try:
            r,_,_ = select.select([fd],[],[],5)
            if not r: break
            d = os.read(fd, 65536)
            if not d: break
            buf += d
        except OSError: break
    os.waitpid(pid, 0)
    dt = time.perf_counter() - t0
    import re
    m = re.search(rb"MAXRSS_KB (\d+)", buf)
    return dt, int(m.group(1)) if m else None
cmd = sys.argv[1:]
once(cmd)  # warm fs cache
res = [once(cmd) for _ in range(7)]
ts = sorted(r[0] for r in res)
print(f"{' '.join(cmd[1:])[:60]:60s} median {statistics.median(ts)*1000:7.1f} ms  min {ts[0]*1000:7.1f} ms  maxrss {res[-1][1]/1024 if res[-1][1] else 0:6.1f} MB")
