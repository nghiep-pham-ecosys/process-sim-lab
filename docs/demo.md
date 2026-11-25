# Local demo

A small web form around the week-3 flowsheet (a CSTR, a flash drum and a purged vapour recycle), to try the library
without writing code. Change the feed, the kinetics, the K-values, the drum sizing data, the purge fraction or the tear
update rule, press **Solve**, and read three tables: every stream, the sizing of every unit, and the convergence of the
tear loop (passes, residual per pass, overall mole balance). The full result JSON is under the tables.

Code: [`src/process_sim_lab/demo.py`](../src/process_sim_lab/demo.py) ·
tests: [`tests/test_demo.py`](../tests/test_demo.py)

## Run it

The demo needs Gradio (Apache-2.0 licence), the optional extra `demo`. The library itself stays standard library only.

```bash
python3 -m pip install -e '.[demo]'
python3 -m process_sim_lab.demo            # open http://127.0.0.1:7860 ; stop with Ctrl+C
python3 -m process_sim_lab.demo --port 7861
```

The demo runs on your machine only: it listens on 127.0.0.1, never creates a public share link and turns Gradio's
usage analytics off.

## Without the web form

`solve_week3` is the function behind the form. It takes the same values as keywords, needs no Gradio, and returns
plain tables, or an error message instead of raising:

```python
from process_sim_lab.demo import solve_week3

out = solve_week3(purge_fraction=0.2, method="wegstein")      # the example's values by default
print(out["streams"]["headers"])        # ['stream', 'A (mol/s)', 'I (mol/s)', 'B (mol/s)', ...]
print(out["convergence"]["iterations"]) # 3
assert out["ok"] and out["convergence"]["iterations"] == 3

bad = solve_week3(method="direct", max_iter=3)
assert not bad["ok"] and "did not converge" in bad["error"]
```

With the default values the answer is the hand derivation of the [worked example](flowsheet-worked-example.md):
recycle (1, 0.6, 0.4) mol/s, liquid (0.75, 2.25, 4.5) mol/s, drum D = 0.206 m and H = 0.823 m.
