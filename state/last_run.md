# Last run 2026-09-18 02:34 UTC (exit 2)

```
02:34:58 INFO    brief: collected 37 items from 10 feeds, 36 after merge
02:34:59 INFO    brief: dedupe: kept 34, dropped 2
02:34:59 ERROR   brief: pipeline failed
Traceback (most recent call last):
  File "/home/runner/work/furniture-brief/furniture-brief/brief/main.py", line 177, in main
    return run(args)
           ^^^^^^^^^
  File "/home/runner/work/furniture-brief/furniture-brief/brief/main.py", line 89, in run
    picks = llm.select(cfg, candidates, recent, notes, date_str, usage,
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/furniture-brief/furniture-brief/brief/llm.py", line 119, in select
    raw = call_model(cfg, m["selector"], SELECT_SYSTEM,
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/furniture-brief/furniture-brief/brief/llm.py", line 57, in call_model
    resp = client.messages.create(
           ^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.14/x64/lib/python3.12/site-packages/anthropic/_utils/_utils.py", line 294, in wrapper
    return func(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^
TypeError: Messages.create() got an unexpected keyword argument 'temperature'
```
