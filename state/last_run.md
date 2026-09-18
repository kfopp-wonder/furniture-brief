# Last run 2026-09-18 09:55 UTC (exit 2)

```
09:54:08 INFO    brief: collected 41 items from 10 feeds, 40 after merge
09:54:08 INFO    brief: dedupe: kept 22, dropped 18
09:54:10 INFO    httpx2: HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"
09:54:10 INFO    brief: claude-haiku-4-5-20251001: 2775 in / 261 out (stop=end_turn)
09:54:11 ERROR   trafilatura.utils: parsed tree length: 0, wrong data type or not valid HTML
09:54:11 ERROR   trafilatura.core: empty HTML tree: None
09:54:11 ERROR   trafilatura.utils: parsed tree length: 0, wrong data type or not valid HTML
09:54:11 ERROR   trafilatura.core: empty HTML tree: None
09:54:30 INFO    brief: extracted 14/17 full texts
09:55:15 INFO    httpx2: HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"
09:55:15 INFO    brief: claude-sonnet-5: 15201 in / 3705 out (stop=end_turn)
09:55:15 ERROR   brief: pipeline failed
Traceback (most recent call last):
  File "/home/runner/work/furniture-brief/furniture-brief/brief/main.py", line 211, in main
    return run(args)
           ^^^^^^^^^
  File "/home/runner/work/furniture-brief/furniture-brief/brief/main.py", line 134, in run
    content = llm.write(cfg, date_str, weekday, picks, articles, backups, notes, usage,
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/furniture-brief/furniture-brief/brief/llm.py", line 207, in write
    return call_model(cfg, m["writer"], system,
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/furniture-brief/furniture-brief/brief/llm.py", line 74, in call_model
    return _json_from(text)
           ^^^^^^^^^^^^^^^^
  File "/home/runner/work/furniture-brief/furniture-brief/brief/llm.py", line 48, in _json_from
    return json.loads(text[start:end + 1])
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.14/x64/lib/python3.12/json/__init__.py", line 346, in loads
    return _default_decoder.decode(s)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.14/x64/lib/python3.12/json/decoder.py", line 338, in decode
    obj, end = self.raw_decode(s, idx=_w(s, 0).end())
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.14/x64/lib/python3.12/json/decoder.py", line 354, in raw_decode
    obj, end = self.scan_once(s, idx)
               ^^^^^^^^^^^^^^^^^^^^^^
json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 86 column 3 (char 10874)
```
