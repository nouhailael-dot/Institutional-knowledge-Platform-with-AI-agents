"""Event dates and editions (asked for on 27 Oct 2026, after a live map showed a
past event as upcoming and mixed the dates and cities of two editions on one
card). No paid calls."""
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from src.map_agent import research, select
from src.map_agent.dedup import deduplicate
from src.map_agent.event_dates import date_range, date_status, dates_text, same_edition

TODAY = date.today()
FIXED = date(2026, 10, 28)


def day(offset):
    return (TODAY + timedelta(days=offset)).isoformat()


def event(name, when="", **extra):
    return {"_entity_type": "event", "name": name, "next_date": when, **extra}


class DateStatusTests(unittest.TestCase):
    def test_partial_dates_are_read_as_the_days_they_could_be(self):
        self.assertEqual(date_range("2026-02")[:2], (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(date_range("2026")[:2], (date(2026, 1, 1), date(2026, 12, 31)))
        self.assertEqual(date_range("Spring 2027")[:2], (date(2027, 1, 1), date(2027, 12, 31)))
        self.assertIsNone(date_range("TBA"))
        self.assertIsNone(date_range("2026-13"))

    def test_status_comes_from_the_dates(self):
        for start, end, expected in (
                ("2026-03-01", "", "past"),             # ARPA-E: shown as upcoming on 26 Oct
                ("2026-02", "", "past"),                # SME: a past month
                ("2026-10", "", "date unconfirmed"),    # this month
                ("2026", "", "date unconfirmed"),       # this year
                ("2027", "", "upcoming"),
                ("2026-11-16", "2026-11-19", "upcoming"),
                ("2026-10-26", "2026-10-30", "upcoming"),  # on right now
                ("2026-10-20", "2026-10-22", "past"),
                ("", "", "date unconfirmed"),
                ("TBA", "", "date unconfirmed")):
            with self.subTest(start=start, end=end):
                self.assertEqual(date_status(start, end, today=FIXED), expected)

    def test_an_end_date_before_the_start_is_ignored(self):
        self.assertEqual(date_status("2026-10-20", "2026-10-01", today=FIXED), "past")

    def test_dates_are_shown_the_platform_way(self):
        self.assertEqual(dates_text("2026-11-16"), "11/16/2026")
        self.assertEqual(dates_text("2026-11-16", "2026-11-19"), "11/16/2026 – 11/19/2026")
        self.assertEqual(dates_text("2026-11-16", "2026-11-16"), "11/16/2026")
        self.assertEqual(dates_text("2026-02"), "02/2026")
        self.assertEqual(dates_text("2026"), "2026 (exact date not found)")
        self.assertEqual(dates_text("Spring 2027"), "Spring 2027")

    def test_dates_a_few_days_apart_are_one_edition(self):
        self.assertTrue(same_edition({"next_date": "2026-11-16"}, {"next_date": "2026-11-17"}))
        self.assertTrue(same_edition({"next_date": "2026-11"}, {"next_date": "2026-11-16"}))
        self.assertTrue(same_edition({"next_date": ""}, {"next_date": "2026-11-16"}))
        self.assertFalse(same_edition({"next_date": "2025-11-17"}, {"next_date": "2026-11-16"}))

    def test_extraction_status_is_recomputed(self):
        card = event("SME Annual Conference", "2026-02", date_status="upcoming")
        research._date_status(card, today=FIXED)
        self.assertEqual(card["date_status"], "past")


class EditionMergeTests(unittest.TestCase):
    def test_two_editions_are_never_mixed_on_one_card(self):
        past = event("RE+ 2025", day(-400), end_date=day(-397), date_status="past",
                     location="Anaheim Convention Center, Anaheim, CA", event_format="In-person",
                     description="Clean energy trade show.", sources=[{"url": "https://re-plus.events/2025"}])
        upcoming = event("RE+ (2026)", day(30), date_status="upcoming", location="Las Vegas",
                         sources=[{"url": "https://re-plus.events"}])
        [card] = deduplicate([past, upcoming])
        self.assertEqual((card["next_date"], card["location"], card["date_status"]),
                         (day(30), "Las Vegas", "upcoming"))
        self.assertNotIn("end_date", card)          # the 2025 end date does not travel
        self.assertNotIn("event_format", card)      # nor its format
        self.assertEqual(card["previous_edition"], day(-400))
        self.assertEqual(card["description"], "Clean energy trade show.")  # about the event
        self.assertEqual(len(card["sources"]), 2)

    def test_the_nearest_upcoming_edition_wins_over_a_later_one(self):
        [card] = deduplicate([event("RE+ 2027", day(380)), event("RE+", day(20))])
        self.assertEqual(card["next_date"], day(20))

    def test_the_longer_status_word_no_longer_wins(self):
        # The merge used to keep the longer text: "upcoming" beat "past".
        a = event("Innovations in Rare Earths", "2026-03-10", date_status="past")
        b = event("Innovations in Rare Earths", "", date_status="date unconfirmed")
        [card] = deduplicate([a, b])
        self.assertEqual(card["date_status"], date_status("2026-03-10"))

    def test_one_edition_takes_its_dates_from_the_more_precise_record(self):
        a = event("Tailings and Mine Waste", "2026-11", location="Colorado")
        b = event("Tailings and Mine Waste 2026", "2026-11-08", end_date="2026-11-11",
                  location="Westminster, Colorado, United States")
        [card] = deduplicate([a, b])
        self.assertEqual((card["next_date"], card["end_date"]), ("2026-11-08", "2026-11-11"))
        self.assertEqual(card["location"], "Westminster, Colorado, United States")

    def test_similar_names_are_flagged_not_merged(self):
        a = event("SME Arizona Section Conference", day(40), website="https://sme-az.org")
        b = event("SME Arizona Section Conferences", day(45), website="https://smenet.org")
        cards = deduplicate([a, b])
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0]["_possible_duplicates"], ["SME Arizona Section Conferences"])

    def test_close_names_from_a_live_map_are_flagged(self):
        for left, right in (("RE+ (Renewable Energy Plus) 2026", "RE+"),
                            ("CLEANPOWER 2027", "CLEANPOWER 2025 Conference & Exhibition")):
            with self.subTest(left=left):
                cards = deduplicate([event(left, day(30)), event(right, day(400))])
                self.assertEqual(len(cards), 2)
                self.assertEqual(cards[0]["_possible_duplicates"], [right])

    def test_a_shared_website_alone_does_not_merge_events(self):
        a = event("TechConnect World", day(40), website="https://techconnect.org")
        b = event("National SBIR Week", day(45), website="https://techconnect.org")
        self.assertEqual(len(deduplicate([a, b])), 2)


class NewerEditionTests(unittest.TestCase):
    def test_the_newer_edition_replaces_every_edition_detail(self):
        card = event("Decarb Connect 2025", "2025-02-25", end_date="2025-02-27", location="Houston",
                     event_format="In-person", organizer="Decarb Connect")
        research._adopt_edition(card, {"name": "Decarb Connect 2026", "next_date": day(90)})
        self.assertEqual(card["next_date"], day(90))
        self.assertNotIn("location", card)          # not the 2025 city
        self.assertNotIn("end_date", card)
        self.assertEqual(card["event_format"], "Not found")
        self.assertEqual(card["organizer"], "Decarb Connect")
        self.assertEqual((card["date_status"], card["previous_edition"]), ("upcoming", "2025-02-25"))

    def test_an_annual_event_weeks_later_is_not_its_next_edition(self):
        card = event("RE+ 2026", "2026-09-21", recurring_pattern="Annual")
        self.assertIsNone(research._newer_edition(card, [{"name": "RE+ 2026", "next_date": "2026-11-16"}]))
        newer = {"name": "RE+ 2027", "next_date": "2027-09-13"}
        self.assertIs(research._newer_edition(card, [newer]), newer)

    def test_the_window_reads_partial_dates(self):
        old = event("Future of Heavy Industries 2024", "2024", date_status="past")
        keep, left_out = research.window_split([old], "heavy industry conferences", {})
        self.assertEqual((keep, left_out), ([], [old]))


class UnaskedPeriodTests(unittest.TestCase):
    def test_a_period_the_user_never_named_is_dropped(self):
        reqs = {"hard_filters": ["Located in the United States", "Takes place in the 2026-2027 timeframe",
                                 "Must be upcoming", "Must focus on past mining sites"]}
        kept, dropped = research.drop_unasked_periods(
            reqs, "Conferences in the US on recovering critical minerals from mine waste")
        self.assertEqual(kept["hard_filters"], ["Located in the United States", "Must focus on past mining sites"])
        self.assertEqual(len(dropped), 2)
        self.assertEqual(len(reqs["hard_filters"]), 4)   # the plan itself is untouched

    def test_a_period_the_user_named_is_kept(self):
        reqs = {"hard_filters": ["Takes place in 2027"]}
        for request in ("Mining conferences in 2027", "Mining conferences over the next 12 months",
                        "Upcoming mining conferences"):
            with self.subTest(request=request):
                kept, dropped = research.drop_unasked_periods(reqs, request)
                self.assertEqual((kept["hard_filters"], dropped), (["Takes place in 2027"], []))


class SelectionDateTests(unittest.TestCase):
    def test_selection_is_told_today_and_sees_the_end_date(self):
        captured = {}

        def fake(*args, **kwargs):
            captured.update(kwargs)
            raise RuntimeError("stop")

        with patch.object(select, "paid_message", side_effect=fake), \
             patch.object(select, "_get_client", return_value=None):
            try:
                select.apply_request([event("RE+", "2026-11-16", end_date="2026-11-19")],
                                     "clean energy conferences", {"hard_filters": ["in the US"]})
            except RuntimeError:
                pass
        text = captured["messages"][0]["content"]
        self.assertIn(f"TODAY'S DATE: {TODAY.isoformat()}", text)
        self.assertIn("2026-11-19", text)


if __name__ == "__main__":
    unittest.main()
