from citations.schema import CitationVerdict, VerificationResult, VerifiedAnswer


def test_verified_answer_holds_answer_citations_coverage_and_flag():
    result = VerifiedAnswer(answer_text="...", citations=["a"], coverage=1.0, low_confidence=False)

    assert result.citations == ["a"]
    assert result.coverage == 1.0
    assert result.low_confidence is False


def test_verification_result_wraps_a_list_of_verdicts():
    result = VerificationResult(verdicts=[CitationVerdict(chunk_id="a", supported=True)])

    assert result.verdicts[0].chunk_id == "a"
    assert result.verdicts[0].supported is True
