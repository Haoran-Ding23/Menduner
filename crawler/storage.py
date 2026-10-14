import json


def put_evidence(con, evidence, event_id):
    con.execute(
        """INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                event_id=excluded.event_id, entity_id=excluded.entity_id, field=excluded.field,
                value=excluded.value, source_url=excluded.source_url, verification_status=excluded.verification_status,
                payload=excluded.payload""",
        (
            evidence["id"],
            event_id,
            evidence["entityId"],
            evidence["field"],
            json.dumps(evidence["value"], ensure_ascii=False),
            evidence["sourceUrl"],
            evidence["status"],
            json.dumps(evidence, ensure_ascii=False),
        ),
    )
