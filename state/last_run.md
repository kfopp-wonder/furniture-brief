# Last run 2026-09-18 11:46 UTC (exit 2)

```
11:44:10 INFO    brief: collected 40 items from 10 feeds, 39 after merge
11:45:22 INFO    brief: newsletters: 29 emails from 13 senders, 170 links
11:45:22 INFO    brief: dedupe: kept 151, dropped 18
11:45:25 INFO    httpx2: HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"
11:45:25 INFO    brief: claude-haiku-4-5-20251001: 4869 in / 252 out (stop=end_turn)
11:45:28 ERROR   trafilatura.utils: parsed tree length: 0, wrong data type or not valid HTML
11:45:28 ERROR   trafilatura.core: empty HTML tree: None
11:45:28 INFO    brief: extracted 13/19 full texts
11:46:20 INFO    httpx2: HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"
11:46:20 INFO    brief: claude-sonnet-5: 16200 in / 4246 out (stop=end_turn)
11:46:20 ERROR   brief: pipeline failed
Traceback (most recent call last):
  File "/home/runner/work/furniture-brief/furniture-brief/brief/main.py", line 222, in main
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
json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 95 column 3 (char 12060)
```
