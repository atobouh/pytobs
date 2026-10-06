import time, resource, os, sys
t=time.perf_counter(); import jedi; ti=(time.perf_counter()-t)*1000
rss0=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
cases = {
 "stdlib os.path.": "import os\nos.path.",
 "json.": "import json\njson.",
 "local obj": "class Foo:\n    def bar(self): pass\n    def baz(self): pass\nf = Foo()\nf.",
 "rich.console.": "import rich.console\nrich.console.",
 "textual.app.App.": "from textual.app import App\nApp.",
}
print(f"jedi import {ti:.0f} ms, rss {rss0:.1f} MB")
for name, src in cases.items():
    lines=src.split("\n"); l=len(lines); c=len(lines[-1])
    ts=[]
    for i in range(4):
        # simulate typing: new Script each keystroke (same as editors)
        t=time.perf_counter(); comps=jedi.Script(src, path="/tmp/x.py").complete(l,c); ts.append((time.perf_counter()-t)*1000)
    print(f"  {name:20s} cold {ts[0]:6.0f} ms  warm {min(ts[1:]):5.0f} ms  n={len(comps)}")
t=time.perf_counter(); sig=jedi.Script("import json\njson.dumps(", path="/tmp/x.py").get_signatures(2,11); print(f"  signature json.dumps  {(time.perf_counter()-t)*1000:.0f} ms -> {sig[0].to_string()[:60]}")
t=time.perf_counter(); d=jedi.Script("import json\njson.dumps", path="/tmp/x.py").complete(2,9)[0].docstring(); print(f"  docstring fetch {(time.perf_counter()-t)*1000:.0f} ms")
print(f"maxrss after {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.1f} MB")
