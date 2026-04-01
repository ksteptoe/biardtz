# Asyncio in biardtz

This guide explains how biardtz uses Python's [asyncio](https://docs.python.org/3/library/asyncio.html) library to run its real-time detection pipeline concurrently in a single thread.

## What is asyncio?

`asyncio` is Python's built-in library for **cooperative multitasking**. Instead of using multiple threads, it runs all code in a single thread where tasks voluntarily yield control at `await` points, letting other tasks run. This avoids thread-safety bugs while keeping the program responsive.

For a full introduction, see the [official asyncio documentation](https://docs.python.org/3/library/asyncio.html).

## Key concepts used in this project

### `async def` / `await`

An `async def` function is a **coroutine** -- it can be paused and resumed. The `await` keyword pauses the current coroutine until the awaited operation completes, allowing other tasks to run in the meantime.

For example, in `logger.py` the database write yields control while SQLite flushes to disk:

```python
async def log(self, detection: Detection) -> None:
    await self._db.execute(...)
    await self._db.commit()
```

See: [Coroutines and Tasks](https://docs.python.org/3/library/asyncio-task.html)

### `asyncio.Queue`

An async-aware FIFO buffer for passing data between tasks. `put()` blocks when full; `get()` blocks when empty -- providing natural **backpressure**.

biardtz uses two queues in `main.py`:

```python
audio_queue: asyncio.Queue = asyncio.Queue(maxsize=8)      # ~24s of audio
dashboard_queue: asyncio.Queue = asyncio.Queue(maxsize=32)  # detection results
```

- `audio_queue` connects the audio producer to the detection worker. With `maxsize=8` and 3-second chunks, up to ~24 seconds of audio can buffer before the producer stalls.
- `dashboard_queue` connects the detection worker to the Rich terminal dashboard.

See: [asyncio.Queue](https://docs.python.org/3/library/asyncio-queue.html)

### `asyncio.create_task()`

Schedules a coroutine to run concurrently as a **Task**. In `main.py`, the pipeline launches up to three tasks:

```python
tasks = [
    asyncio.create_task(audio_producer(config, audio_queue), name="audio"),
    asyncio.create_task(_detection_worker(...), name="worker"),
]
if config.enable_dashboard:
    tasks.append(asyncio.create_task(dashboard.run(dashboard_queue), name="dashboard"))
```

All three tasks run concurrently in the same thread, cooperating via the queues.

See: [Creating Tasks](https://docs.python.org/3/library/asyncio-task.html#creating-tasks)

### `asyncio.Event`

A simple signalling primitive -- one task calls `event.set()`, others `await event.wait()`. biardtz uses it for graceful shutdown:

```python
stop_event = asyncio.Event()

def _signal_handler():
    stop_event.set()

# Main coroutine blocks here until Ctrl+C
await stop_event.wait()
```

When SIGINT or SIGTERM arrives, `_signal_handler` sets the event, unblocking `run()` so it can cancel tasks and shut down cleanly.

### `loop.run_in_executor()`

Asyncio runs in a single thread, so CPU-heavy or blocking code would freeze the entire event loop. `run_in_executor()` offloads work to a **thread pool**, returning a future that can be awaited.

biardtz uses this in two places:

**1. Audio capture** (`audio_capture.py`) -- bridging the sounddevice callback thread to asyncio:

```python
# Blocks in a thread until audio data arrives from the callback
data = await loop.run_in_executor(None, thread_q.get)
```

**2. BirdNET inference** (`detector.py`) -- offloading CPU-bound model prediction:

```python
async def predict(self, audio_chunk: np.ndarray) -> list[Detection]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, self._predict_sync, audio_chunk)
```

The `None` argument uses the default `ThreadPoolExecutor`. While inference runs in the thread pool, the event loop remains free to process audio and update the dashboard.

See: [Event Loop — Executing code in thread or process pools](https://docs.python.org/3/library/asyncio-eventloop.html#executing-code-in-thread-or-process-pools)

## The pipeline

The complete data flow through the async pipeline:

```
Microphone
    |
    v
audio_producer()  ──>  audio_queue (maxsize=8)  ──>  _detection_worker()
                                                          |          |
                                                          v          v
                                              DetectionLogger   dashboard_queue (maxsize=32)
                                              (SQLite DB)            |
                                                                     v
                                                              Dashboard.run()
                                                              (Rich terminal)
```

Each box is an async task. The queues decouple producers from consumers and provide backpressure -- if BirdNET inference is slow, the audio queue fills up and the producer pauses until space is available.

## Why asyncio?

- **Low overhead on Raspberry Pi** -- no extra threads or processes needed for I/O coordination
- **Natural fit for I/O-bound work** -- waiting on the microphone, database writes, and terminal updates are all I/O operations
- **Executor escape hatch** -- CPU-bound BirdNET inference is offloaded to a thread pool via `run_in_executor()`, keeping the event loop responsive
- **Clean shutdown** -- `asyncio.Event` and task cancellation provide a straightforward way to handle SIGINT/SIGTERM gracefully
- **Backpressure via queues** -- prevents memory buildup if any stage falls behind

## Further reading

- [asyncio — Asynchronous I/O](https://docs.python.org/3/library/asyncio.html) -- module overview
- [Coroutines and Tasks](https://docs.python.org/3/library/asyncio-task.html) -- `async def`, `await`, `create_task()`
- [Queues](https://docs.python.org/3/library/asyncio-queue.html) -- `asyncio.Queue`
- [Event Loop](https://docs.python.org/3/library/asyncio-eventloop.html) -- `run_in_executor()`, signal handlers
