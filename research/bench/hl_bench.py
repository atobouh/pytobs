import time, sys
import tree_sitter_python as tsp
from tree_sitter import Language, Parser, Query, QueryCursor
from pygments.lexers.python import PythonLexer
import pygments, textual.widgets._text_area as ta
for path in sys.argv[1:]:
    src=open(path).read(); n=src.count("\n")
    lx=PythonLexer()
    t=time.perf_counter(); toks=list(lx.get_tokens(src)); tp=(time.perf_counter()-t)*1000
    # pygments on a 60-line viewport (what an editor redraw would need if lexing only visible lines)
    view="\n".join(src.split("\n")[1000:1060])
    t=time.perf_counter(); list(lx.get_tokens(view)); tv=(time.perf_counter()-t)*1000
    lang=Language(tsp.language()); parser=Parser(lang)
    b=src.encode()
    t=time.perf_counter(); tree=parser.parse(b); tparse=(time.perf_counter()-t)*1000
    # incremental edit: insert one char in the middle
    mid=len(b)//2; nb=b[:mid]+b"x"+b[mid:]
    row=b[:mid].count(b"\n"); col=mid-(b.rfind(b"\n",0,mid)+1)
    tree.edit(start_byte=mid,old_end_byte=mid,new_end_byte=mid+1,start_point=(row,col),old_end_point=(row,col),new_end_point=(row,col+1))
    t=time.perf_counter(); tree2=parser.parse(nb,tree); tinc=(time.perf_counter()-t)*1000
    q=Query(lang, tsp.HIGHLIGHTS_QUERY)
    t=time.perf_counter(); caps=QueryCursor(q).captures(tree2.root_node); tq=(time.perf_counter()-t)*1000
    qc=QueryCursor(q); qc.set_point_range((1000,0),(1060,0))
    t=time.perf_counter(); qc.captures(tree2.root_node); tqv=(time.perf_counter()-t)*1000
    print(f"{path.split('/')[-1]:12s} {n:5d} lines | pygments full {tp:6.1f} ms, 60-line view {tv:4.1f} ms | tree-sitter full parse {tparse:5.1f} ms, incremental {tinc:4.2f} ms, full query {tq:5.1f} ms, viewport query {tqv:4.2f} ms")
