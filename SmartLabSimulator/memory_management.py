"""
memory_management.py  -  contiguous allocation and page replacement
====================================================================
"""


def _allocate(blocks, processes, choose):
    """
    Shared loop for first/best/worst fit.
    'choose' receives the list of (index, size) of blocks that are big enough
    and returns the one block to use.
    """
    free = [int(b) for b in blocks]                 # copy so the caller's list is not changed
    sizes = [int(p) for p in processes]
    allocation = [-1] * len(sizes)                  # -1 means "not allocated"

    for i, need in enumerate(sizes):
        fitting = [(j, size) for j, size in enumerate(free) if size >= need]
        if fitting:
            j, _ = choose(fitting)
            allocation[i] = j
            free[j] -= need
    return allocation, free


def first_fit_full(blocks, processes):
    """First block that is big enough."""
    return _allocate(blocks, processes, lambda fitting: fitting[0])


def best_fit_full(blocks, processes):
    """Smallest block that is big enough (least waste)."""
    return _allocate(blocks, processes, lambda fitting: min(fitting, key=lambda x: x[1]))


def worst_fit_full(blocks, processes):
    """Largest block (leaves the biggest leftover)."""
    return _allocate(blocks, processes, lambda fitting: max(fitting, key=lambda x: x[1]))


def first_fit(blocks, processes):
    """Old name: returns only the allocation list."""
    return first_fit_full(blocks, processes)[0]


def allocate(strategy, blocks, processes):
    functions = {"first": first_fit_full, "best": best_fit_full, "worst": worst_fit_full}
    if strategy not in functions:
        raise ValueError("strategy must be first, best or worst")
    allocation, remaining = functions[strategy](blocks, processes)
    return {"strategy": strategy, "allocation": allocation, "remaining_blocks": remaining,
            "unallocated": [i for i, a in enumerate(allocation) if a == -1],
            "external_fragmentation": sum(remaining)}


# ---------------------------------------------------------------------------
# Page replacement: which page leaves memory when all frames are full?
# ---------------------------------------------------------------------------
def page_replacement(pages, frames, algorithm="fifo"):
    pages = [int(p) for p in pages]
    if frames < 1:
        raise ValueError("frames must be at least 1")
    memory = []             # pages currently in memory
    last_used = {}          # page -> last time it was used (for LRU)
    steps, faults = [], 0

    for time, page in enumerate(pages):
        fault = page not in memory
        if fault:
            faults += 1
            if len(memory) == frames:                         # memory full: choose a victim
                if algorithm == "fifo":
                    victim = memory[0]                        # oldest page
                elif algorithm == "lru":
                    victim = min(memory, key=lambda p: last_used[p])   # used longest ago
                elif algorithm == "optimal":
                    future = pages[time + 1:]                 # page used furthest in the future
                    victim = max(memory, key=lambda p: future.index(p) if p in future else len(future) + 1)
                else:
                    raise ValueError("algorithm must be fifo, lru or optimal")
                memory.remove(victim)
            memory.append(page)
        last_used[page] = time
        steps.append({"page": page, "memory": list(memory), "fault": fault})

    return {"algorithm": algorithm, "frames": frames, "steps": steps,
            "page_faults": faults, "hit_ratio": round((len(pages) - faults) / len(pages), 2) if pages else 0}
