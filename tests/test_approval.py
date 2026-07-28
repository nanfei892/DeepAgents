from app.approval import compose_final_reply


def test_approved_ticket_has_fixed_reply():
    # approve 不接受模型自由发挥，使用固定合规文案。
    result = compose_final_reply({"decision": "approve", "human_reply": ""})
    assert "已批准" in result["final_reply"]


def test_human_edited_reply_wins():
    # 人工编辑的内容优先级最高，不能被系统模板覆盖。
    result = compose_final_reply({"decision": "edit", "human_reply": "人工客服将在今天 18:00 前回电"})
    assert result["final_reply"] == "人工客服将在今天 18:00 前回电"