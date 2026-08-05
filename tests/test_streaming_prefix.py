from app.streaming_prefix import static_stream_prefix


def test_extracts_bold_bracketed_html_speaker() -> None:
    text = "<b>[АРХИВАРИУС]</b>\n\nПрактически… я больше не уверен."

    assert static_stream_prefix(text, "HTML") == "[АРХИВАРИУС]\n\n"


def test_ignores_regular_bold_text() -> None:
    text = "<b>Соединение восстановлено.</b>\n\nПродолжаю."

    assert static_stream_prefix(text, "HTML") == ""


def test_ignores_non_html_messages() -> None:
    text = "<b>[NPC]</b>\n\nВообще-то я здесь ведущ"

    assert static_stream_prefix(text, "none") == ""
