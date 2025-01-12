# https://superfastpython.com/asyncio-log-blocking/
# example of asyncio logging with a queue handler and listener
import logging
from logging.handlers import QueueHandler
from logging.handlers import QueueListener
from logging import StreamHandler
from queue import Queue
import asyncio
import sys

# helper coroutine to setup and manage the logger
async def init_logger():
    # get the root logger
    log = logging.getLogger()
    # create the shared queue
    que = Queue()
    # add a handler that uses the shared queue
    log.addHandler(loggingHandler := QueueHandler(que))
    loggingHandler.setFormatter(
        logging.Formatter(style="{", fmt="{levelname[0]:s}: {name:s}: {message:s}"))
    # log all messages, debug and up
    log.setLevel(logging.DEBUG)
    # create a listener for messages on the queue
    listener = QueueListener(que, StreamHandler(sys.stdout))
    try:
        # start the listener
        listener.start()
        # report the logger is ready
        logging.debug(f'Logger has started')
        # wait forever
        while True:
            await asyncio.sleep(60)
    except Exception as err:
        print(err)
    finally:
        # report the logger is done
        logging.debug(f'Logger is shutting down')
        # ensure the listener is closed
        listener.stop()

# reference to the logger task
LOGGER_TASK = None
# coroutine to safely start the logger
async def safely_start_logger():
    # initialize the logger
    LOGGER_TASK = asyncio.create_task(init_logger())
    # allow the logger to start
    await asyncio.sleep(0)

def stream_logs(func):
    async def wrapper(*args, **kwargs):
        # initialize the logger
        await safely_start_logger()
        logging.info('Begin streaming logs...')

        loop = asyncio.get_running_loop()
        try:
            await loop.create_task(func(*args, **kwargs))
        except Exception as err:
            print(f"Logging stream closed due to error: {err=}")
        finally:
            print("Logging stream shut down. Goodbye")
    return wrapper