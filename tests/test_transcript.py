from audio_transcriber.transcript import TranscriptAssembler, dedupe_boundary


def test_exact_boundary_repetition_is_removed():
    assert dedupe_boundary(
        "so we said hello there and then", "there and then we left"
    ) == "we left"


def test_no_match_keeps_the_full_incoming_text():
    assert dedupe_boundary("alpha beta gamma", "delta epsilon") == "delta epsilon"


def test_short_overlap_below_minimum_is_kept():
    assert dedupe_boundary("we said ok", "ok then") == "ok then"


def test_partial_token_match_is_kept():
    assert dedupe_boundary("that is the plan", "plan for later") == "plan for later"


def test_repeated_phrase_inside_the_incoming_text_is_not_removed():
    incoming = "we said ok then we said ok then we left"
    assert dedupe_boundary("completely different prefix", incoming) == incoming


def test_assembly_is_ordered_by_index_regardless_of_insertion_order():
    assembler = TranscriptAssembler()
    assembler.add(2, "third")
    assembler.add(0, "first")
    assembler.add(1, "second")
    assert assembler.text() == "first second third"
    assert assembler.covered_indices() == {0, 1, 2}


def test_empty_chunk_contributes_nothing():
    assembler = TranscriptAssembler()
    assembler.add(0, "hello")
    assembler.add(1, "   ")
    assembler.add(2, "world")
    assert assembler.text() == "hello world"


def test_all_empty_chunks_produce_empty_string():
    assembler = TranscriptAssembler()
    assembler.add(0, "")
    assembler.add(1, " \t")
    assert assembler.text() == ""


def test_assembler_deduplicates_only_at_join_points():
    assembler = TranscriptAssembler()
    assembler.add(0, "opening completely unique words")
    assembler.add(1, "we saw four bright stars in the sky")
    assembler.add(2, "four bright stars in the sky and then dawn")
    assert assembler.text() == (
        "opening completely unique words we saw four bright stars in the sky "
        "and then dawn"
    )
