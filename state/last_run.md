# Last run 2026-09-18 12:00 UTC (exit 2)

```
11:59:32 INFO    brief: collected 43 items from 10 feeds, 42 after merge
12:00:52 INFO    brief: newsletters: 29 emails from 13 senders, 170 links
12:00:52 INFO    brief: dedupe: kept 154, dropped 18
12:00:57 INFO    httpx2: HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"
12:00:57 INFO    brief: claude-haiku-4-5-20251001: 5754 in / 279 out (stop=tool_use)
12:00:57 ERROR   brief: pipeline failed
Traceback (most recent call last):
  File "/home/runner/work/furniture-brief/furniture-brief/brief/main.py", line 222, in main
    return run(args)
           ^^^^^^^^^
  File "/home/runner/work/furniture-brief/furniture-brief/brief/main.py", line 112, in run
    picks = llm.select(cfg, candidates, recent, notes, date_str, usage,
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/furniture-brief/furniture-brief/brief/llm.py", line 209, in select
    out["hero"] = hero if hero in valid else (out["top_stories"][0] if out["top_stories"] else None)
                          ^^^^^^^^^^^^^
TypeError: unhashable type: 'list'
```
