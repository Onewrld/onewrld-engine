"""Job handlers: the code that runs each kind of job.

Importing this package registers every handler with the job queue. Each later module
(video, posting, metrics) adds its own file here.
"""

from onewrld.handlers import demo  # noqa: F401  (import registers the handlers)
from onewrld import videos  # noqa: F401  (registers video.render)
