"""Phase 6 NLP: the shared command rules (values, tool calls, approval), the honest validation
split and the baseline parsers. The dataset tests are skipped when commands.jsonl is missing."""

import pytest

from ai.nlp.commands import (
    DATA,
    WRITE_TOOLS,
    bio,
    honest_validation,
    load_commands,
    mentions,
    normalize,
    requires_approval,
    same_calls,
    spans_from_bio,
    tool_calls,
)
from ai.nlp.evaluation import evaluate, noisy
from ai.nlp.intent_parser import RuleParser, TfidfParser, regex_entities
from ai.nlp.understanding import understand

needs_data = pytest.mark.skipif(not DATA.exists(), reason="run scripts/generate_nlp_data.py")


@pytest.mark.parametrize(
    ("etype", "surface", "value"),
    [
        ("ROBOT", "robot twelve", "R12"),
        ("ROBOT", "R-07", "R7"),
        ("AISLE", "aisle 3", "AISLE_03"),
        ("PRIORITY", "urgent", "HIGH"),
    ],
)
def test_entities_are_normalised_to_canonical_ids(etype, surface, value):
    assert normalize(etype, surface) == value


def test_spans_from_bio_drop_the_possessive():
    spans = spans_from_bio("check R7's battery", ["O", "B-ROBOT", "O"])
    assert spans == [{"type": "ROBOT", "start": 6, "end": 8, "text": "R7"}]


def test_bio_tags_round_trip_to_the_same_spans():
    text = "assign order 12 to robot 7"
    entities = [
        {"type": "ORDER", "start": 7, "end": 15, "text": "order 12"},
        {"type": "ROBOT", "start": 19, "end": 26, "text": "robot 7"},
    ]
    _, tags = bio(text, entities)
    assert spans_from_bio(text, tags) == entities


def test_phrases_survive_one_swapped_letter_pair():
    assert mentions("do it by hnad", "by hand")
    assert not mentions("do it now", "by hand")


def test_tool_calls_and_approval():
    calls = tool_calls("pause_robot", [{"type": "ROBOT", "value": "R12"}], "pause R12")
    assert calls == [{"name": "pause_robot", "arguments": {"robot_id": "R12"}}]
    assert requires_approval(calls) and "pause_robot" in WRITE_TOOLS
    read = tool_calls("robot_status", [{"type": "ROBOT", "value": "R7"}], "where is R7")
    assert not requires_approval(read)
    with pytest.raises(KeyError):  # a required entity is missing
        tool_calls("pause_robot", [], "pause it")
    assert same_calls(calls, list(calls)) and not same_calls(calls, read)


def test_missing_entity_asks_a_question_and_low_confidence_is_unsure():
    missing = understand("pause the robot", "pause_robot", 0.9, [])
    assert missing["status"] == "needs_information" and missing["question"]
    assert missing["tool_calls"] == []
    unsure = understand(
        "pause R12", "pause_robot", 0.2, [{"type": "ROBOT", "start": 6, "end": 9, "text": "R12"}]
    )
    assert unsure["status"] == "unsure"


def test_rule_parser_end_to_end():
    p = RuleParser()
    r = p.parse("close aisle 30 for maintenance")
    assert r["intent"] == "close_aisle" and r["requires_approval"]
    assert r["tool_calls"][0]["arguments"] == {"aisle_id": "AISLE_30", "reason": "maintenance"}
    assert p.parse("order me a pizza")["status"] == "out_of_scope"
    assert {e["type"] for e in regex_entities("send R3 to packing station 2")} >= {
        "ROBOT",
        "STATION",
    }


@needs_data
def test_dataset_labels_agree_with_the_shared_rules():
    df = load_commands().head(400)
    for row in df.itertuples():
        assert bio(row.text, row.entities)[1] == row.bio_tags
        assert same_calls(tool_calls(row.intent, row.entities, row.text), row.tool_calls)
        assert requires_approval(row.tool_calls) == row.requires_approval


@needs_data
def test_honest_validation_holds_out_whole_templates():
    df = load_commands()
    train = df[df.split == "train"]
    split = honest_validation(train, share=0.2, seed=0)
    fit, val = train[split == "train"], train[split == "validation"]
    assert len(val) > 0 and not set(fit.template_id) & set(val.template_id)
    assert set(val.intent) <= set(fit.intent)  # every intent is still learned


@needs_data
def test_tfidf_beats_nothing_and_noise_keeps_entities():
    df = load_commands()
    train, test = df[df.split == "train"], df[df.split == "test"].head(300)
    parser = TfidfParser().fit(train.text.tolist(), train.intent.tolist())
    scores = evaluate(parser.parse, test)
    assert scores["intent_accuracy"] > 0.5 and scores["entity_F1"] > 0.9
    texts = noisy(test, seed=0)
    assert len(texts) == len(test) and texts != test.text.tolist()
