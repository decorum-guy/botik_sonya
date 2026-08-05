from app.memory_variables import collect_memory_variables_from_data


def test_memory_label_escapes_placeholder_tags() -> None:
    variables = collect_memory_variables_from_data(
        {
            "steps": [
                {
                    "actions": [
                        {
                            "type": "memory_reconstruction",
                            "memory_id": "next_memory",
                            "title": "Воспоминание <id> & детали",
                        }
                    ]
                }
            ]
        }
    )

    assert variables[0].label == "Воспоминание &lt;id&gt; &amp; детали"
