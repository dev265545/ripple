import threading
import time

from ripple.graph import apply_schema, connect, drop, read
from ripple.investigation import add_task, claim_task, finish_task


def run(tenants: int = 2, workers: int = 4, tasks: int = 100) -> dict:
    """Many workers race for tasks on several tenants at once; every task must be claimed exactly once."""
    names = [f"load-{n}" for n in range(tenants)]
    for name in names:
        drop(name)
        graph = connect(name)
        apply_schema(graph)
        graph.query("CREATE (:Investigation {id: 'INV-1', tasks: 0, steps: 0})")
        for _ in range(tasks):
            add_task(graph, "INV-1", "triage", stage=1)

    claims: dict[str, list[str]] = {name: [] for name in names}
    latencies: list[float] = []
    lock = threading.Lock()

    def worker(name: str, agent: str) -> None:
        graph = connect(name)
        while True:
            started = time.perf_counter()
            task = claim_task(graph, "INV-1", agent)
            elapsed = time.perf_counter() - started
            if task is None:
                return
            finish_task(graph, task["id"], "done", agent)
            with lock:
                claims[name].append(task["id"])
                latencies.append(elapsed)

    threads = [threading.Thread(target=worker, args=(name, f"worker-{n}")) for name in names for n in range(workers)]
    started = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    seconds = time.perf_counter() - started

    leaked = sum(read(connect(name), "MATCH (t:Task) RETURN count(t) AS n")[0]["n"] != tasks for name in names)
    for name in names:
        drop(name)
    total = sum(len(ids) for ids in claims.values())
    latencies.sort()
    return {
        "tenants": tenants, "workers_per_tenant": workers, "tasks_per_tenant": tasks, "claimed": total,
        "double_claims": total - sum(len(set(ids)) for ids in claims.values()),
        "tenants_with_wrong_task_count": leaked,
        "claims_per_second": round(total / seconds),
        "p95_claim_ms": round(latencies[int(len(latencies) * 0.95)] * 1000, 2),
    }
