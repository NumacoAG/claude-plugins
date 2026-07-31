#!/usr/bin/env python3
"""Regression contract for the locked Numaco trading document family."""

import importlib.util
import json
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "build_trading_document.py"
SAMPLES = SKILL_DIR / "sample"


def load_builder():
    spec = importlib.util.spec_from_file_location("build_trading_document", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_sample(name):
    return json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))


class TradingDocumentTemplateContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = load_builder()

    def test_all_four_samples_validate(self):
        for name in ("quotation", "order_confirmation", "delivery_note", "invoice"):
            with self.subTest(name=name):
                self.builder.validate(load_sample(name))

    def test_quotation_keeps_all_four_price_fields(self):
        payload = load_sample("quotation")
        _, _, body = self.builder.build_html(payload)
        for label in ("Listenpreis CHF", "Rabatt", "Einzelpreis CHF", "Total CHF"):
            self.assertIn(label, body)

    def test_quotation_discount_must_reconcile(self):
        payload = load_sample("quotation")
        payload["lines"][0]["unit_price"] = 3000
        with self.assertRaises(self.builder.PayloadError):
            self.builder.validate(payload)

    def test_delivery_note_rejects_financial_fields(self):
        payload = load_sample("delivery_note")
        payload["lines"][0]["unit_price"] = 10
        with self.assertRaises(self.builder.PayloadError):
            self.builder.validate(payload)

    def test_invoice_has_no_worked_interest_amount(self):
        payload = load_sample("invoice")
        _, _, body = self.builder.build_html(payload)
        self.assertIn("5% per annum", body)
        self.assertNotIn("9.19", body)
        self.assertNotIn("30E/360", body)

    def test_financial_rows_are_vertically_centred(self):
        css = self.builder.TRADING_CSS
        self.assertIn("vertical-align:middle", css)
        self.assertIn("align-items:center", css)

    def test_total_rule_is_below_the_total_content(self):
        css = self.builder.TRADING_CSS
        self.assertIn("calc(100% - 2mm)", css)

    def test_invoice_totals_must_reconcile(self):
        payload = load_sample("invoice")
        payload["totals"]["grand_total"] = 900
        with self.assertRaises(self.builder.PayloadError):
            self.builder.validate(payload)


if __name__ == "__main__":
    unittest.main()
