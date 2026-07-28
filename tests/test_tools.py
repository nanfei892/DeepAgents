from app.schemas import WorkerResult


def test_low_confidence_result_must_be_handed_off():
    # 该 DTO 是 Supervisor 路由到人工工单的输入。
    result = WorkerResult(answer="不知道", confidence=0.2, risk_level="medium", action="create_ticket", handoff_reason="无证据")
    assert result.confidence < 0.55
    assert result.action == "create_ticket"