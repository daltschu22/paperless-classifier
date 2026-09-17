"""Offline checks for experiment integrity and result validation."""

import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("probe", ROOT / "tools/investigate_jev.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class InvestigationTests(unittest.TestCase):
    def setUp(self):
        self.dataset = json.loads((ROOT / "examples/investigation-cases.json").read_text())
        self.case = self.dataset["cases"][0]
        self.request = probe.prepare(self.case, self.dataset, "test-model")
        answers = {}
        for name, question in self.request["questions"].items():
            if question["type"] == "noul":
                answers[name] = {"type": "noul", "noul": 1.0 if name[4:] in self.case["expected_tags"] else 0.0}
            else:
                answers[name] = {"type": "choice", "choice": "invoice", "confidence": 1.0,
                                 "probabilities": {key: float(key == "invoice") for key in question["criteria"]}}
        self.response = {"model": "test-model", "answers": answers, "usage": {"input_tokens": 100, "output_tokens": 20}}

    def test_gold_labels_and_ids_are_not_model_inputs(self):
        changed = dict(self.case, id="DO_NOT_SEND", expected_type="LEAK", expected_tags=["LEAK"])
        self.assertEqual(self.request, probe.prepare(changed, self.dataset, "test-model"))
        self.assertEqual(self.request["state"], {"ocr_text": self.case["text"]})

    def test_tags_are_independent_and_type_can_abstain(self):
        self.assertEqual(len(self.request["questions"]), 13)
        self.assertIn("unknown", self.request["questions"]["document_type"]["criteria"])
        for tag in self.dataset["tags"]:
            question = self.request["questions"]["tag_" + tag]
            self.assertEqual(question["type"], "noul")
            self.assertIn(self.dataset["tags"][tag], question["instructions"])

    def test_missing_ocr_does_not_make_a_request(self):
        self.assertIsNone(probe.prepare(dict(self.case, text=" \n "), self.dataset, "test-model"))

    def test_valid_result(self):
        probe.validate(self.response, self.request)

    def test_missing_answer_is_rejected(self):
        del self.response["answers"]["tag_water"]
        with self.assertRaises(ValueError):
            probe.validate(self.response, self.request)

    def test_invalid_probabilities_are_rejected(self):
        for value in (float("nan"), float("inf"), -0.1, 1.1, True, "0.5"):
            with self.subTest(value=value):
                response = copy.deepcopy(self.response)
                response["answers"]["tag_water"]["noul"] = value
                with self.assertRaises(ValueError):
                    probe.validate(response, self.request)

    def test_unknown_choice_and_broken_distribution_are_rejected(self):
        for update in ({"choice": "invented"}, {"probabilities": {"invoice": 1.0}}, {"confidence": 2.0}):
            response = copy.deepcopy(self.response)
            response["answers"]["document_type"].update(update)
            with self.assertRaises(ValueError):
                probe.validate(response, self.request)
        self.response["answers"]["document_type"]["probabilities"]["unknown"] = 0.5
        with self.assertRaises(ValueError):
            probe.validate(self.response, self.request)

    def test_summary_excludes_errors_and_skips_from_accuracy(self):
        records = [
            {"case_id": self.case["id"], "status": "success", "elapsed_seconds": 0.2, "response": self.response},
            {"case_id": "empty_ocr", "status": "ocr_missing"},
            {"case_id": "water_invoice", "status": "error", "error_class": "TimeoutError"},
        ]
        result = probe.summarize(records, self.dataset, 0.042)
        self.assertEqual(result["successful_calls"], 1)
        self.assertEqual(result["type_correct"], 1)
        self.assertEqual(result["skipped_empty"], 1)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["tag_thresholds"]["0.5"]["true_positive"], 2)
        self.assertAlmostEqual(result["estimated_cost_usd"], 0.0000042)

    def test_summary_counts_false_additions_and_missed_tags(self):
        self.response["answers"]["tag_water"]["noul"] = 0.8
        self.response["answers"]["tag_electricity"]["noul"] = 0.3
        records = [{"case_id": self.case["id"], "status": "success", "elapsed_seconds": 0.2, "response": self.response}]
        metrics = probe.summarize(records, self.dataset, 0.042)["tag_thresholds"]["0.5"]
        self.assertEqual((metrics["true_positive"], metrics["false_positive"], metrics["false_negative"]), (1, 1, 1))

    def test_scale_matches_observed_collection_dimensions(self):
        recipe = json.loads((ROOT / "examples/investigation-scale.json").read_text())
        scaled = probe.scale_dataset(self.dataset, recipe)
        self.assertEqual(len(scaled["tags"]), 56)
        self.assertEqual(len(set(scaled["document_types"]) - {"unknown"}), 15)
        self.assertEqual(len(scaled["cases"]), 3)
        self.assertEqual(len(scaled["cases"][1]["text"]), 32000)
        self.assertEqual(len(scaled["cases"][2]["text"]), 32000)
        self.assertEqual(len(self.dataset["tags"]), 12)


if __name__ == "__main__":
    unittest.main()
