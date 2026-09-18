# Last run 2026-09-18 11:57 UTC (exit 2)

```
11:55:13 INFO    brief: collected 43 items from 10 feeds, 42 after merge
11:56:15 INFO    brief: newsletters: 29 emails from 13 senders, 170 links
11:56:15 INFO    brief: dedupe: kept 154, dropped 18
11:56:18 INFO    httpx2: HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"
11:56:18 INFO    brief: claude-haiku-4-5-20251001: 5750 in / 271 out (stop=tool_use)
11:56:20 INFO    brief: redirect not followed for https://link.mail.beehiiv.com/ss/c/u001.Nip_UK5BFIEP7ebSvurEeUXqxPikqx (HTTP 403, text/html; charset=UTF-8)
11:56:21 INFO    brief: redirect not followed for https://link.mail.beehiiv.com/ss/c/u001.cbTlTBbOm0oxrOJrFZNEqW0H3faEwe (HTTP 403, text/html; charset=UTF-8)
11:56:22 ERROR   trafilatura.utils: parsed tree length: 0, wrong data type or not valid HTML
11:56:22 ERROR   trafilatura.core: empty HTML tree: None
11:56:24 INFO    brief: extracted 13/19 full texts
11:57:17 INFO    httpx2: HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"
11:57:17 INFO    brief: claude-sonnet-5: 19261 in / 4441 out (stop=tool_use)
11:57:17 ERROR   brief: pipeline failed
Traceback (most recent call last):
  File "/home/runner/work/furniture-brief/furniture-brief/brief/main.py", line 222, in main
    return run(args)
           ^^^^^^^^^
  File "/home/runner/work/furniture-brief/furniture-brief/brief/main.py", line 139, in run
    content, warnings = render.validate_and_attach(cfg, content, articles)
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/furniture-brief/furniture-brief/brief/render.py", line 42, in validate_and_attach
    for raw in sections.get(s["key"], []) or []:
               ^^^^^^^^^^^^
AttributeError: 'str' object has no attribute 'get'
```
