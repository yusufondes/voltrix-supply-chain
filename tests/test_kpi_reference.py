"""Nonwriting regression checks for model inventory and reference-only semantics."""
from pathlib import Path
import re
import sys
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kpi_reference as ref
from sc_kpi import customer_kpis, customer_line_status, supplier_kpis


class MeasureParserTests(unittest.TestCase):
    def test_quoted_and_unquoted_names(self):
        measures = ref.parse_measures("table T\n\tmeasure 'OTIF %' = 1\n\tmeasure DSO = 2\n\tmeasure DPO = 3\n\tmeasure DIO = [Days of Inventory]\n")
        self.assertEqual([m["name"] for m in measures], ["OTIF %", "DSO", "DPO", "DIO"])

    def test_escaped_apostrophe(self):
        self.assertEqual(ref.parse_measures("\tmeasure 'Customer''s KPI' = 1\n")[0]["name"], "Customer's KPI")

    def test_multiline_expression_format_and_hidden(self):
        result = ref.parse_measures('\tmeasure KPI =\n\t\t\tVAR X = 2\n\t\t\tRETURN X\n\t\tformatString: 0.0"%"\n\t\tisHidden\n')[0]
        self.assertEqual(result["dax"], "VAR X = 2\nRETURN X")
        self.assertEqual(result["format"], '0.0"%"')
        self.assertTrue(result["hidden"])

    def test_inline_expression_keeps_continuation(self):
        self.assertEqual(ref.parse_measures("\tmeasure KPI = VAR X = 1\n\t\t\tRETURN X\n")[0]["dax"], "VAR X = 1\nRETURN X")

    def test_quoted_format_decoding(self):
        self.assertEqual(ref.parse_measures('\tmeasure KPI = 1\n\t\tformatString: "0.0""%"""\n')[0]["format"], '0.0"%"')

    def test_invalid_heads_fail_with_context(self):
        for head in ("Bad Name = 1", "'Broken = 1", "MissingEquals"):
            with self.subTest(head=head), self.assertRaisesRegex(ValueError, "Unsupported measure declaration"):
                ref.parse_measures("\tmeasure " + head + "\n")

    def test_duplicate_fails(self):
        with self.assertRaisesRegex(ValueError, "Duplicate measure"):
            ref.parse_measures("\tmeasure KPI = 1\n\tmeasure 'KPI' = 2\n")

    def test_no_measure_fails(self):
        with self.assertRaisesRegex(ValueError, "No measure"):
            ref.parse_measures("table T\n")

    def test_empty_expression_fails(self):
        with self.assertRaisesRegex(ValueError, "Missing DAX"):
            ref.parse_measures("\tmeasure KPI =\n\t\tformatString: 0\n")

    def test_actual_inventory_and_reference_values_are_complete(self):
        text = (ref.MODEL / "tables/_KPI Measures.tmdl").read_text(encoding="utf-8")
        heads = re.findall(r"^\tmeasure (.+?)\s*=", text, re.M)
        expected = {head[1:-1].replace("''", "'") if head.startswith("'") else head for head in heads}
        measures = ref.parse_measures()
        self.assertEqual(len(heads), 104)
        self.assertEqual({m["name"] for m in measures}, expected)
        values = ref.evaluate(ref.load(), ref.parse_targets())
        self.assertEqual(set(values), expected)
        document = ref.build(measures, values, ref.parse_targets())
        self.assertNotIn("#D98E04", document)
        self.assertIn("#9C6500", document)
        self.assertEqual(values["Materials by Supplier Count"], 0)
        self.assertEqual(values["Supplier Count Colour"], "#005CA9")


class ReferenceSemanticsTests(unittest.TestCase):
    def test_supplier_lead_time_is_invariant_to_index_and_row_order(self):
        po = pd.DataFrame({"PurchaseOrderLineKey": [1, 2], "OrderedQuantity": [100, 100],
                           "ExpectedDeliveryDate": ["2024-01-15", "2024-02-25"],
                           "OrderDate": ["2024-01-01", "2024-02-01"]})
        gr = pd.DataFrame({"PurchaseOrderLineKey": [1, 2], "ReceiptDate": ["2024-01-11", "2024-02-21"],
                           "AcceptedQuantity": [100, 100], "ReceivedQuantity": [100, 100], "RejectedQuantity": [0, 0]})
        for frame in (gr, gr.iloc[::-1], gr.set_axis([10, 20])):
            with self.subTest(index=list(frame.index)):
                values = supplier_kpis(po, frame, "2024-03-31")
                self.assertEqual(values["MeanLeadTimeDays"], 15)
                self.assertAlmostEqual(values["LeadTimeStdDevDays"], 50 ** 0.5)
        self.assertEqual(supplier_kpis(po, gr.iloc[1:], "2024-03-31")["MeanLeadTimeDays"], 20)

    def test_due_denominator_and_split_record_invariance(self):
        so = pd.DataFrame({"SalesOrderLineKey": [1, 2, 3], "OrderedQuantity": [100, 100, 100],
                           "RequestedDeliveryDate": ["2024-03-10", "2024-03-31", "2024-04-01"]})
        shipments = pd.DataFrame({"SalesOrderLineKey": [1, 1], "ShippedQty": [40, 60],
                                  "DeliveryDate": ["2024-03-08", "2024-03-08"]})
        for frame in (shipments, shipments.iloc[::-1], shipments.iloc[:1].assign(ShippedQty=100)):
            values = customer_kpis(so, frame, "2024-03-31")
            self.assertEqual(values["DueLines"], 2)
            self.assertEqual(values["OTIFPct"], 50)
            self.assertEqual(values["LateOrderLines"], 1)
            states = customer_line_status(so, frame, "2024-03-31").set_index("SalesOrderLineKey")
            self.assertTrue(states.loc[2, "IsLate"])
            self.assertFalse(states.loc[3, "IsDue"])

    def test_total_otif_uses_unequal_group_denominators(self):
        so = pd.DataFrame({"SalesOrderLineKey": range(1, 102), "OrderedQuantity": [1] * 101,
                           "RequestedDeliveryDate": ["2024-03-10"] * 101})
        ships = pd.DataFrame({"SalesOrderLineKey": list(range(1, 51)) + [101], "ShippedQty": [1] * 51,
                              "DeliveryDate": ["2024-03-08"] * 51})
        value = customer_kpis(so, ships, "2024-03-31")["OTIFPct"]
        self.assertAlmostEqual(value, 51 / 101 * 100)
        self.assertNotEqual(value, (50 + 100) / 2)

    def test_target_colours_and_inclusive_boundaries(self):
        self.assertEqual(ref.target_status_colour(100, 100, "higher"), "#2E7D32")
        self.assertEqual(ref.target_status_colour(95, 100, "higher"), "#9C6500")
        self.assertEqual(ref.target_status_colour(94.9, 100, "higher"), "#C62828")
        self.assertEqual(ref.target_status_colour(100, 100, "lower"), "#2E7D32")
        self.assertEqual(ref.target_status_colour(105, 100, "lower"), "#9C6500")
        self.assertEqual(ref.target_status_colour(105.1, 100, "lower"), "#C62828")
        self.assertIsNone(ref.target_status_colour(None, 100, "higher"))
        self.assertIsNone(ref.target_status_colour(10, None, "lower"))

    def test_bad_direction_fails(self):
        with self.assertRaises(ValueError):
            ref.target_status_colour(10, 10, "unknown")

    def test_supplier_bucket_defaults_and_selection(self):
        po = pd.DataFrame({"ProductKey": [1, 1, 2, 2], "SupplierKey": [10, 10, 10, 20]})
        self.assertEqual(ref.supplier_count_helpers(po), (0, "#005CA9"))
        self.assertEqual(ref.supplier_count_helpers(po, 1), (1, "#C62828"))
        self.assertEqual(ref.supplier_count_helpers(po, 2), (1, "#005CA9"))
        self.assertEqual(ref.supplier_count_helpers(po, 3), (0, "#005CA9"))

    def test_status_palette_matches_actual_model(self):
        measures = ref.parse_measures()
        colours = [m for m in measures if m["name"].endswith(" Status Colour")]
        self.assertTrue(colours)
        for measure in colours:
            with self.subTest(measure=measure["name"]):
                self.assertIn('"#9C6500"', measure["dax"])
                self.assertNotIn('"#D98E04"', measure["dax"])


if __name__ == "__main__":
    unittest.main()
