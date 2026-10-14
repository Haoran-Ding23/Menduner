"""Source coverage from the existing job/raw/evidence tables, not search snippets."""
import json
from pathlib import Path
import yaml
from backend.database import connect
from crawler.registry import REGISTRY_PATH, load_registry


def source_coverage(db_path, report, *, registry_path=REGISTRY_PATH, update_registry=True):
    definitions = load_registry(registry_path)
    attempts = {a['source']: a for a in report['attempts']}
    rows = []
    with connect(db_path) as con:
        for definition in definitions:
            row = definition.model_dump()
            attempt = attempts.get(definition.source_id)
            row.update(attempted=attempt is not None, successful_pages=0,
                       events_extracted=0, evidence_generated=0, raw_records=0,
                       rejected_records=0, rejection_reasons=[])
            if attempt:
                raw = con.execute(
                    'SELECT validation_status,error FROM crawler_raw_items WHERE job_id=? AND source_id=?',
                    (report['jobId'], definition.source_id)).fetchall()
                rejected = sorted({r['error'] for r in raw if r['error']})
                status = {'Success': 'SUCCESS', 'Partial': 'PARTIAL', 'Failed': 'FAILED'}[attempt['status']]
                reasons = [attempt['error']] if attempt.get('error') else []
                reasons += attempt.get('warnings', [])
                reasons += rejected
                row.update(crawl_status=status, reason='; '.join(dict.fromkeys(reasons)) or None,
                           last_checked=report['updatedAt'], successful_pages=attempt['pagesCollected'],
                           events_extracted=attempt['accepted'], raw_records=len(raw),
                           rejected_records=attempt['rejected'], rejection_reasons=rejected,
                           evidence_generated=con.execute(
                               'SELECT COUNT(*) FROM crawler_evidence e JOIN crawler_raw_items r ON r.id=e.raw_item_id '
                               'WHERE r.job_id=? AND e.source=?',
                               (report['jobId'], definition.source_id)).fetchone()[0])
            rows.append(row)
        generated = con.execute(
            'SELECT COUNT(*) FROM crawler_evidence e JOIN crawler_raw_items r ON r.id=e.raw_item_id WHERE r.job_id=?',
            (report['jobId'],)).fetchone()[0]
    coverage = dict(
        registeredSources=len(definitions), tier1RegisteredSources=sum(d.tier == 1 for d in definitions),
        implementedSources=sum(d.adapter is not None for d in definitions),
        tier1ImplementedSources=sum(d.tier == 1 and d.adapter is not None for d in definitions),
        tier1EventExtractionAdapters=sum(d.tier == 1 and d.implementation == 'event_extraction' for d in definitions),
        tier1AuditOnlyAdapters=sum(d.tier == 1 and d.implementation == 'public_page_audit' for d in definitions),
        eventExtractionAdapters=sum(d.implementation == 'event_extraction' for d in definitions),
        auditOnlyAdapters=sum(d.implementation == 'public_page_audit' for d in definitions),
        manualOnlySources=sum(d.implementation == 'manual_only' for d in definitions),
        attemptedSources=len(attempts), successfulPages=report['pagesCollected'],
        failedSources=[r['source_id'] for r in rows if r['attempted'] and r['crawl_status'] == 'FAILED'],
        eventProducingSources=[r['source_id'] for r in rows if r['attempted'] and r['events_extracted']],
        eventsExtracted=report['eventsProcessed'], eventsStored=report['eventsStored'],
        evidenceGenerated=generated, currentEventEvidenceRecords=report['evidenceRecordsGenerated'],
        rawRecordsCollected=report['rawRecordsCollected'], sources=rows,
    )
    if update_registry:
        path = Path(registry_path)
        document = yaml.safe_load(path.read_text(encoding='utf-8'))
        current = {r['source_id']: r for r in rows}
        for item in document['sources']:
            row = current[item['source_id']]
            if row['attempted']:
                item.update({key: row[key] for key in ('crawl_status', 'reason', 'last_checked')})
        # Validate before writing; a failure always has its reason and manual stays manual.
        payload = '# Source trust does not imply Verified event fields. Last-observed crawl status only.\n' + yaml.safe_dump(document, allow_unicode=True, sort_keys=False)
        temporary = path.with_suffix(path.suffix + '.tmp')
        try:
            temporary.write_text(payload, encoding='utf-8')
            load_registry(temporary)
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()
    return coverage


def attach_coverage(db_path, report, *, registry_path=REGISTRY_PATH, output=None):
    report['sourceCoverage'] = source_coverage(db_path, report, registry_path=registry_path)
    with connect(db_path) as con:
        con.execute('UPDATE crawler_jobs SET report=? WHERE id=?',
                    (json.dumps(report, ensure_ascii=False, sort_keys=True), report['jobId']))
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report
