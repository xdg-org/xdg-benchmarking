import multiprocessing
import os

# Server socket
bind = "0.0.0.0:8050"
backlog = 2048

# Worker processes
workers = int(os.environ.get('MAX_WORKERS', 4))
worker_class = "sync"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50
timeout = int(os.environ.get('TIMEOUT', 120))
keepalive = 2

# Restart workers after this many requests, to help prevent memory leaks
preload_app = True

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get('LOG_LEVEL', 'INFO').lower()
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "xdg-dashboard"

# Server mechanics
daemon = False
pidfile = None
user = None
group = None
tmp_upload_dir = None

# SSL (uncomment if using SSL)
# keyfile = None
# certfile = None

# Server hooks
def on_starting(server):
    """Called just after the server is started."""
    server.log.info("XDG Benchmarking Dashboard starting up...")

def on_reload(server):
    """Called to reload the server configuration."""
    server.log.info("XDG Benchmarking Dashboard reloading...")

def worker_int(worker):
    """Called just after a worker has been initialized."""
    worker.log.info("Worker spawned (pid: %s)", worker.pid)

def pre_fork(server, worker):
    """Called just before a worker has been forked."""
    server.log.info("Worker will be spawned")

def post_fork(server, worker):
    """Called just after a worker has been forked."""
    server.log.info("Worker spawned (pid: %s)", worker.pid)

def post_worker_init(worker):
    """Called just after a worker has initialized the application."""
    worker.log.info("Worker initialized (pid: %s)", worker.pid)

def worker_abort(worker):
    """Called when a worker received the SIGABRT signal."""
    worker.log.info("Worker received SIGABRT!")

def pre_exec(server):
    """Called just before a new master process is forked."""
    server.log.info("Forked child, re-executing.")

def when_ready(server):
    """Called just after the server is started."""
    server.log.info("XDG Benchmarking Dashboard is ready to serve requests!")

def worker_exit(server, worker):
    """Called when a worker exits."""
    server.log.info("Worker exited (pid: %s)", worker.pid)

def on_exit(server):
    """Called just before exiting."""
    server.log.info("XDG Benchmarking Dashboard shutting down...")