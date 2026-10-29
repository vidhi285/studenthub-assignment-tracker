"""Gunicorn settings. Values can be tuned with environment variables."""
import os

bind = "0.0.0.0:5000"
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
worker_class = "gthread"
timeout = 60
graceful_timeout = 20
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
# Inside Docker only the reverse proxy (or your browser via the published port) reaches us.
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "*")
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms "%(a)s"'
