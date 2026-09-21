# Last run 2026-09-21 09:57 UTC (exit 2)

```
09:54:55 INFO    brief: collected 47 items from 10 feeds, 46 after merge
09:55:57 INFO    brief: newsletters: 38 emails from 15 senders, 259 links
09:55:57 INFO    brief: dedupe: kept 228, dropped 15
09:56:00 INFO    httpx2: HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"
09:56:00 INFO    brief: claude-haiku-4-5-20251001: 6211 in / 290 out (stop=tool_use)
09:56:05 INFO    brief: redirect not followed for https://substack.com/redirect/52e9a8b0-305a-4043-8fe8-52252eec12a8?j=e (HTTP 200, text/html; charset=utf-8)
09:56:10 INFO    brief: extracted 18/20 full texts
09:57:10 INFO    httpx2: HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"
09:57:10 INFO    brief: claude-sonnet-5: 21372 in / 4948 out (stop=tool_use)
09:57:10 INFO    brief: writer output shape: {title:str, subtitle:str, greeting:str, hero:str, sections:{top_stories:list[5], industry_moves:list[3], retail_trends:list[3], supply_chain:list[1], ai_tech:list[4]}, one_thing:str, body:str, closing:str}
09:57:10 ERROR   brief: pipeline failed
Traceback (most recent call last):
  File "/home/runner/work/furniture-brief/furniture-brief/brief/main.py", line 233, in main
    return run(args)
           ^^^^^^^^^
  File "/home/runner/work/furniture-brief/furniture-brief/brief/main.py", line 145, in run
    content, warnings = render.validate_and_attach(cfg, content, articles)
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/furniture-brief/furniture-brief/brief/render.py", line 35, in validate_and_attach
    content["one_thing"] = {"headline": _clean(ot.get("headline", "")), "body": _clean(ot.get("body", ""))}
                                               ^^^^^^
AttributeError: 'str' object has no attribute 'get'
```
