import os, pty, sys, select, re
pid, fd = pty.fork()
if pid == 0: os.execvp(sys.argv[1], sys.argv[1:])
buf=b""
while True:
    try:
        r,_,_=select.select([fd],[],[],5)
        if not r: break
        d=os.read(fd,65536)
        if not d: break
        buf+=d
    except OSError: break
print(" | ".join(m.decode() for m in re.findall(rb"PH ([^\r\n]+)", buf)))
