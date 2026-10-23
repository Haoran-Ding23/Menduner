# Local Docker stack

web (nginx + built frontend) + api (FastAPI) + neo4j, on one machine.

```powershell
docker compose -f deploy/docker-compose.yml up --build -d
#   http://localhost:8080        the product
#   http://localhost:8000/docs   the API directly
#   http://localhost:7474        Neo4j browser (neo4j / menduner-dev-only)
```

Stop with `docker compose -f deploy/docker-compose.yml down`. Add `-v` only when you also want to
throw away the Neo4j volume.

## Two things that have to be true before `up`

**1. `data/menduner.sqlite3` must exist.** The compose file bind-mounts `../data` into the api
container, so an empty directory means an empty product — the server will happily start and show
zero events. Copy a database in first (it is git-ignored):

```powershell
# from the production server, as the deploy user
scp -i ~/.ssh/menduner_deploy admin@47.116.133.230:/tmp/menduner.sqlite3 data/menduner.sqlite3
```

**2. Docker Hub has to be reachable, or a mirror configured.** `registry-1.docker.io` is not
reachable from mainland networks; without a mirror the build dies at the first base image with
`dial tcp ...:443: connectex: A connection attempt failed`. Put mirrors in
`%USERPROFILE%\.docker\daemon.json` and restart Docker Desktop:

```json
{
  "registry-mirrors": [
    "https://docker.1panel.live",
    "https://docker.m.daocloud.io",
    "https://hub.rat.dev",
    "https://dockerproxy.net"
  ]
}
```

Verify with `docker info` — the list appears under *Registry Mirrors*.

## Neo4j is a derived view

SQLite stays the single source of truth. The graph is rebuilt from it, never patched by hand:

```powershell
docker compose -f deploy/docker-compose.yml exec -T api python -X utf8 -m backend.graph_sync            # count only
docker compose -f deploy/docker-compose.yml exec -T api python -X utf8 -m backend.graph_sync --apply    # write
```

Re-run it after any import, crawl or manual entry. Because the sync starts with
`MATCH (n) DETACH DELETE n`, a broken graph is repaired by re-running it — which is the whole point
of keeping it derived.

Graph shape:

```
(:Event)-[:HELD_AT]->(:Venue)
(:Event)-[:IN_DISTRICT]->(:District)
(:Venue)-[:IN_DISTRICT]->(:District)
(:Hotel)-[:IN_DISTRICT]->(:District)
```

## Known limitation on this stack

The AMap map tiles need the browser key's domain whitelist to include `localhost`. When it does
not, the map panel stays blank while every list, table and count still works — that is a key
configuration issue, not a data or rendering bug in the app.
