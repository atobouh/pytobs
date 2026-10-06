import os, resource
from rich.console import Console
from rich.syntax import Syntax
Console().print(Syntax("print('hi')", "python"))
os.write(2, f"MAXRSS_KB {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}\n".encode())
