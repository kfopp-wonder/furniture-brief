# Last run 2026-09-18 02:38 UTC (exit 2)

```
02:37:13 INFO    brief: collected 51 items from 10 feeds, 49 after merge
02:37:13 INFO    brief: dedupe: kept 45, dropped 4
02:37:16 INFO    httpx2: HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"
02:37:16 INFO    brief: claude-haiku-4-5-20251001: 4143 in / 261 out
02:37:16 ERROR   trafilatura.utils: parsed tree length: 0, wrong data type or not valid HTML
02:37:16 ERROR   trafilatura.core: empty HTML tree: None
02:37:16 ERROR   trafilatura.utils: parsed tree length: 0, wrong data type or not valid HTML
02:37:16 ERROR   trafilatura.core: empty HTML tree: None
02:37:17 ERROR   trafilatura.utils: parsed tree length: 0, wrong data type or not valid HTML
02:37:17 ERROR   trafilatura.core: empty HTML tree: None
02:37:17 INFO    brief: extracted 17/20 full texts
02:38:24 INFO    httpx2: HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"
02:38:24 INFO    brief: claude-sonnet-5: 16925 in / 6000 out
02:38:24 ERROR   brief: pipeline failed
Traceback (most recent call last):
  File "/home/runner/work/furniture-brief/furniture-brief/brief/main.py", line 177, in main
    return run(args)
           ^^^^^^^^^
  File "/home/runner/work/furniture-brief/furniture-brief/brief/main.py", line 111, in run
    content = llm.write(cfg, date_str, weekday, picks, articles, backups, notes, usage,
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/furniture-brief/furniture-brief/brief/llm.py", line 194, in write
    return call_model(cfg, m["writer"], system,
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/furniture-brief/furniture-brief/brief/llm.py", line 65, in call_model
    return _json_from(text)
           ^^^^^^^^^^^^^^^^
  File "/home/runner/work/furniture-brief/furniture-brief/brief/llm.py", line 47, in _json_from
    raise ValueError("no JSON object in model output")
ValueError: no JSON object in model output
```
