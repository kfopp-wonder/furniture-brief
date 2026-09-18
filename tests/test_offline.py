"""Offline unit tests: no network, no tokens.  Run: python tests/test_offline.py"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brief import collect, dedupe, llm, market, render  # noqa: E402
from brief.util import FIXTURES, Settings, normalize_url, word_count  # noqa: E402


def fx(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TestCollect(unittest.TestCase):
    def setUp(self):
        self.cfg = Settings.load()

    def test_scoring_prefers_furniture(self):
        kw = self.cfg.feeds["keywords"]
        feed = {"weight": 1.0}
        hi, _ = collect.score_item("La-Z-Boy reports Q2 earnings", "furniture retailer", feed, kw)
        lo, _ = collect.score_item("Bitcoin hits a record", "crypto", feed, kw)
        self.assertGreater(hi, 5)
        self.assertLess(lo, 0)

    def test_ai_flag(self):
        _, is_ai = collect.score_item("OpenAI launches shopping agent", "retail", {"weight": 1}, self.cfg.feeds["keywords"])
        self.assertTrue(is_ai)

    def test_merge_duplicates_by_title(self):
        a = {"title": "Hooker Furnishings posts third straight profit", "norm_title": "hooker furnishings posts third straight profit",
             "norm_url": "https://a.com/1", "google_news": False, "paywalled": False, "score": 5, "is_ai": False, "source": "A", "url": "https://a.com/1"}
        b = {"title": "Hooker Furnishings posts a third straight quarterly profit", "norm_title": "hooker furnishings posts a third straight quarterly profit",
             "norm_url": "https://b.com/2", "google_news": True, "paywalled": False, "score": 4, "is_ai": False, "source": "B", "url": "https://b.com/2"}
        merged = collect.merge_duplicates([a, b])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["source"], "A")          # non-Google-News version wins
        self.assertEqual(len(merged[0]["alternates"]), 1)

    def test_normalize_url_strips_tracking(self):
        self.assertEqual(normalize_url("https://www.x.com/a/?utm_source=rss&utm_medium=x#top"),
                         normalize_url("http://x.com/a"))


class TestDedupe(unittest.TestCase):
    def test_drops_published_url_and_title(self):
        cands = fx("candidates.json")
        hist = [{"date": "2026-09-16", "section": "top_stories", "headline": cands[0]["title"],
                 "norm_url": cands[0]["norm_url"], "norm_title": cands[0]["norm_title"], "status": "published"},
                {"date": "2026-09-15", "section": "ai_tech", "headline": cands[1]["title"],
                 "norm_url": "https://other.com/x", "norm_title": cands[1]["norm_title"], "status": "published"}]
        kept, dropped = dedupe.filter_candidates(cands, hist, edition=date(2026, 9, 17))
        self.assertEqual(len(dropped), 2)
        self.assertEqual({d["dropped_reason"] for d in dropped}, {"url already published", "title matches a recent headline"})

    def test_same_day_draft_does_not_block_rerun(self):
        cands = fx("candidates.json")
        hist = [{"date": "2026-09-17", "section": "top_stories", "headline": cands[0]["title"],
                 "norm_url": cands[0]["norm_url"], "norm_title": cands[0]["norm_title"], "status": "draft"}]
        kept, dropped = dedupe.filter_candidates(cands, hist, edition=date(2026, 9, 17))
        self.assertEqual(len(dropped), 0)

    def test_recent_headlines_excludes_today(self):
        hist = [{"date": "2026-09-17", "section": "top_stories", "headline": "Today"},
                {"date": "2026-09-16", "section": "top_stories", "headline": "Yesterday"},
                {"date": "2026-09-16", "section": "post", "headline": "Post title"}]
        self.assertEqual(dedupe.recent_headlines(hist, edition=date(2026, 9, 17)), ["Yesterday"])


class TestLLM(unittest.TestCase):
    def setUp(self):
        self.cfg = Settings.load()
        self.cands = fx("candidates.json")

    def test_select_sanitises_ids_and_counts(self):
        usage = llm.Usage()
        raw = fx("select_response.json")
        raw = dict(raw)
        raw["top_stories"] = raw["top_stories"] + ["bogus", raw["industry_moves"][0]]  # unknown + duplicate
        picks = llm.select(self.cfg, self.cands, [], "", "2026-09-17", usage, mock=raw)
        self.assertEqual(len(picks["top_stories"]), 5)
        self.assertNotIn("bogus", picks["top_stories"])
        # article claimed by top_stories is not also in industry_moves
        self.assertFalse(set(picks["top_stories"]) & set(picks["industry_moves"]))
        self.assertEqual(len(usage.calls), 1)

    def test_prompt_budget(self):
        """Selector prompt stays well under ~10k tokens for 60 candidates."""
        cands = (self.cands * 3)[:60]
        p = llm.select_prompt(self.cfg, cands, ["x"] * 40, "", "2026-09-17")
        self.assertLess(len(p) / 4, 9000)

    def test_json_from_handles_fences(self):
        self.assertEqual(llm._json_from('Sure:\n```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(llm._json_from('{"a": {"b": [1,2]}} trailing'), {"a": {"b": [1, 2]}})


class TestRender(unittest.TestCase):
    def setUp(self):
        self.cfg = Settings.load()
        cands = {c["id"]: c for c in fx("candidates.json")}
        ex = fx("extracted.json")
        self.articles = {i: {**cands[i], **ex[i]} for i in ex if i in cands}

    def test_validate_cleans_dashes_and_attaches_sources(self):
        content = fx("write_response.json")
        content["title"] = "Fed Hikes — Retail Braces"
        content["sections"]["top_stories"][0]["summary"] += " Rates rose – a lot — fast."
        content, warnings = render.validate_and_attach(self.cfg, content, self.articles)
        self.assertNotIn("—", content["title"])
        self.assertNotIn("—", content["sections"]["top_stories"][0]["summary"])
        self.assertTrue(all(i["source_url"].startswith("http") for i in content["sections"]["top_stories"]))
        self.assertTrue(any("excerpt only" in w for w in warnings))  # paywalled fixture flagged

    def test_unknown_article_id_dropped_and_flagged(self):
        content = fx("write_response.json")
        content["sections"]["ai_tech"].append({"headline": "Made up", "summary": "x " * 50, "article_id": "nope"})
        content, warnings = render.validate_and_attach(self.cfg, content, self.articles)
        self.assertEqual(len(content["sections"]["ai_tech"]), 4)
        self.assertTrue(any("unknown article" in w for w in warnings))

    def test_newsletter_html_matches_substack_markup(self):
        content, _ = render.validate_and_attach(self.cfg, fx("write_response.json"), self.articles)
        html = render.render_newsletter(self.cfg, date(2026, 9, 17), content, "https://x.github.io/r/pulse/2026-09-17.png")
        self.assertIn("Thursday, September 17, 2026", html)
        self.assertIn("1. ", html)
        self.assertIn("Market Pulse", html)
        self.assertIn("The One Thing", html)
        self.assertNotIn("Supply Chain &amp; Trade", html)   # empty section is omitted
        self.assertIn('href="https://homenewsnow.com', html)
        self.assertNotIn("—", html)
        # Market Pulse sits between Industry Moves and Retail & Consumer Trends
        self.assertLess(html.index("Industry Moves"), html.index("Market Pulse"))
        self.assertLess(html.index("Market Pulse"), html.index("Retail &amp; Consumer Trends"))

    def test_word_count(self):
        self.assertEqual(word_count("It's a white-glove test, isn't it"), 6)


class TestMarket(unittest.TestCase):
    def test_build_market_flags_bad_quotes(self):
        cfg = Settings.load()
        m = market.build_market(cfg, fixture=fx("market.json"))
        self.assertTrue(any("PRPL" in f for f in m["flags"]))   # fixture price below $0.50
        self.assertEqual(m["stocks"][0]["label"], "HD")           # sorted by price desc
        tsy = next(r for r in m["markets"] if r["label"].startswith("10-Yr"))
        self.assertEqual(tsy["change_text"], "+7 bp")
        wci = next(r for r in m["container"] if r["label"] == "US West Coast")
        self.assertEqual(wci["value_text"], "$7,352/FEU")
        self.assertEqual(wci["change_text"], "+2.00%")

    def test_card_renders(self):
        from brief import card
        cfg = Settings.load()
        m = market.build_market(cfg, fixture=fx("market.json"))
        with tempfile.TemporaryDirectory() as td:
            p = card.render_card(m, Path(td) / "c.png")
            self.assertGreater(p.stat().st_size, 20_000)


class TestSubstack(unittest.TestCase):
    def test_build_doc_structure(self):
        from brief import substack
        cfg = Settings.load()
        cands = {c["id"]: c for c in fx("candidates.json")}
        ex = fx("extracted.json")
        articles = {i: {**cands[i], **ex[i]} for i in ex if i in cands}
        content, _ = render.validate_and_attach(cfg, fx("write_response.json"), articles)
        doc = substack.build_doc(cfg, date(2026, 9, 17), content, "https://x/pulse.png")
        types = [n["type"] for n in doc["content"]]
        self.assertEqual(doc["type"], "doc")
        self.assertIn("heading", types)
        self.assertIn("bullet_list", types)
        self.assertIn("captionedImage", types)
        self.assertIn("blockquote", types)
        heads = [n["content"][0]["text"] for n in doc["content"] if n["type"] == "heading" and n["attrs"]["level"] == 2]
        self.assertEqual(heads[:3], ["Top Stories", "Industry Moves", "Market Pulse"])
        self.assertNotIn("Supply Chain & Trade", heads)          # empty section omitted
        stories = [n for n in doc["content"] if n["type"] == "heading" and n["attrs"]["level"] == 3]
        self.assertTrue(stories[0]["content"][0]["text"].startswith("1. "))
        links = json.dumps(doc).count('"type": "link"')
        self.assertGreaterEqual(links, 15)                        # one source link per item
        # serialisable and dash-free
        self.assertNotIn("—", json.dumps(doc, ensure_ascii=False))

    def test_cookie_parsing(self):
        from brief import substack
        self.assertEqual(substack.Substack._parse_cookie("abc123"), {"substack.sid": "abc123"})
        self.assertEqual(substack.Substack._parse_cookie("a=1; substack.sid=xyz; b=2")["substack.sid"], "xyz")
        with self.assertRaises(substack.SubstackError):
            substack.Substack._parse_cookie("a=1; b=2")


class TestNewsletters(unittest.TestCase):
    def test_extract_links_keeps_articles_drops_chrome(self):
        from brief import newsletters
        html = """
        <html><body>
        <a href="https://x.beehiiv.com/p/view-online">View in browser</a>
        <h2><a href="https://link.mail.beehiiv.com/ss/c/abc123">Mastercard is Giving AI Agents Their Own Credit Cards</a></h2>
        <p>The network launched Agent Pay, letting shopping agents transact with tokenized credentials. Merchants opt in.</p>
        <a href="https://example.com/read">Read more</a>
        <a href="https://twitter.com/therundownai">Follow us</a>
        <a href="https://cdn.beehiiv.com/img/logo.png"><img src="x"></a>
        <p><a href="https://openai.com/index/foo">OpenAI ships a retail agent toolkit for merchants</a> and more.</p>
        <a href="https://x.beehiiv.com/subscribe?ref=1">Subscribe to our newsletter today</a>
        <a href="https://x.com/unsubscribe">Unsubscribe from these emails</a>
        </body></html>"""
        links = newsletters.extract_links(html, 10)
        titles = [l["title"] for l in links]
        self.assertEqual(titles, ["Mastercard is Giving AI Agents Their Own Credit Cards",
                                  "OpenAI ships a retail agent toolkit for merchants"])
        self.assertIn("Agent Pay", links[0]["excerpt"])

    def test_sender_matching(self):
        from brief import newsletters
        s = {"match": ["@therundown.ai", "hello@tldr.tech"]}
        self.assertTrue(newsletters._match_sender(s, "news@daily.therundown.ai".lower()) or newsletters._match_sender(s, "news@therundown.ai"))
        self.assertTrue(newsletters._match_sender(s, "hello@tldr.tech"))
        self.assertFalse(newsletters._match_sender(s, "someone@gmail.com"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
