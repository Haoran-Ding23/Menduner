#!/bin/bash
# End-to-end check of the private-data chain on production, then clean up after itself.
set -u
cd /srv/menduner

echo "=== 1. create an invite ==="
CODE=$(sudo -u menduner env MENDUNER_DB_PATH=/srv/menduner/data/menduner.sqlite3 ./venv/bin/python -X utf8 -c "
from backend import accounts
from backend.database import connect
import os
with connect(os.environ['MENDUNER_DB_PATH']) as con:
    acc = {'id': 'op', 'name': 'op'}
    inv = accounts.create_invite(con, created_by='op', days=1)
    print(inv['code'])
")
echo "  invite: $CODE"

echo
echo "=== 2. register a test hotel ==="
JAR=/tmp/e2e.cookies
rm -f $JAR
REG=$(curl -s -c $JAR -X POST http://127.0.0.1/api/account/register \
  -H 'Content-Type: application/json' \
  -d "{\"invite_code\":\"$CODE\",\"login\":\"zz-e2e-tenant\",\"password\":\"test-password-1\",\"name\":\"端到端测试\",\"hotel\":\"端到端测试酒店\"}")
echo "  $REG" | head -c 200
echo

echo
echo "=== 3. upload a CSV (dry run) ==="
cat > /tmp/e2e.csv <<'CSV'
日期,出租率(%),平均房价,间夜
2026-10-01,82.5,620,120
2026-10-02,78,610,115
2026-10-03,150,600,100
2026-09-30 至 2026-09-30,88.1,640,130
CSV
curl -s -b $JAR -X POST "http://127.0.0.1/api/private/import?filename=e2e.csv&apply=0" \
  --data-binary @/tmp/e2e.csv > /tmp/e2e-preview.json
sudo -u menduner ./venv/bin/python -X utf8 -c "
import json
d = json.load(open('/tmp/e2e-preview.json'))
print('  tenant:', d.get('tenant'))
print('  mapping:', d.get('mapping'))
print('  rowsRead:', d.get('rowsRead'), ' accepted:', d.get('acceptedCount'))
print('  issues:')
for i in d.get('issues', []):
    print('    row', i['row'], ':', i['reason'])
"

echo
echo "=== 4. apply ==="
curl -s -b $JAR -X POST "http://127.0.0.1/api/private/import?filename=e2e.csv&apply=1" \
  --data-binary @/tmp/e2e.csv > /tmp/e2e-apply.json
sudo -u menduner ./venv/bin/python -X utf8 -c "
import json
d = json.load(open('/tmp/e2e-apply.json'))
print('  written:', d.get('written'), ' dryRun:', d.get('dryRun'))
"

echo
echo "=== 5. read back this hotel's own rows ==="
curl -s -b $JAR http://127.0.0.1/api/private/metrics > /tmp/e2e-metrics.json
sudo -u menduner ./venv/bin/python -X utf8 -c "
import json
d = json.load(open('/tmp/e2e-metrics.json'))
print('  tenant:', d.get('tenant'), ' count:', d.get('count'))
for r in d['rows'][:6]:
    print('   ', r['metric'], r['period_start'], r['value'], r['channel'] or '')
"
echo
echo "  说明：这是端到端测试写入的数据，下面会清理"
